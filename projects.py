"""Project & Git: daftar repo, branch, worktree, diff, log, status.

FASE 1 — git HANYA BACA. Tidak ada `git worktree add`, `git checkout`, `git fetch`,
atau perintah git lain yang mengubah Working tree. Yang dijalankan hanya
perintah inspeksi (status, branch, log, diff, worktree list).

Keamanan (aturan CLAUDE.md): browser TIDAK BOLEH meminta path bebas.
`resolve()` hanya meloloskan folder yang sudah ada di registry server
(hasil pemindaian folder kode + daftar di ~/.service-admin/projects.json).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from core import DATA_DIR, ENV, HOME, ApiError, run
from http import HTTPStatus

GIT = shutil.which("git", path=ENV["PATH"]) or "/usr/bin/git"
GH = shutil.which("gh", path=ENV["PATH"])

# PENTING: `git status`/`git diff` normally take `.git/index.lock` to refresh the
# index. Kalau beberapa perintah baca dijalankan BERSAMAAN pada repo yang sama
# (dan detail memang begitu: 9 perintah paralel), mereka saling menunggu lock
# dan satu perintah bisa menggantung puluhan detik. GIT_OPTIONAL_LOCKS=0
# mematikan pengambilan lock opsional itu — tidak ada yang ditulis, jadi aman.
GIT_ENV = dict(ENV, GIT_OPTIONAL_LOCKS="0", GIT_PAGER="cat", GIT_TERMINAL_PROMPT="0")

SCAN_ROOTS = ["Documents", "Projects", "Code", "Developer", "Sites", "Desktop", "src", "work", "Worktrees"]
SCAN_SKIP = {"node_modules", "vendor", "Pods", ".build", "DerivedData", "Library", ".Trash",
             "build", "dist", ".venv", "venv", "__pycache__", "target"}
SCAN_MAX_DEPTH = 4
SCAN_BUDGET = 6.0  # detik; pemindaian selalu dibatasi supaya endpoint tidak menggantung

PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")

_cache = {"t": 0.0, "projects": {}}


# ---------------------------------------------------------------- registry

REGISTRY_MAX = 200
HOME_REAL = os.path.realpath(HOME)
PRESET_CMD_MAX_ARGS = 20
PRESET_CMD_MAX_LEN = 300
PRESET_SHELL_CHARS = set(";&|<>`$\n\r\0")  # пресеты — команды, а не shell-выражения


def _read_registry_file():
    try:
        with open(PROJECTS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"paths": [], "presets": {}}
    if isinstance(data, list):  # старый формат: просто список путей
        data = {"paths": data}
    if not isinstance(data, dict):
        return {"paths": [], "presets": {}}
    data["paths"] = [p for p in (data.get("paths") or []) if isinstance(p, str)]
    data["presets"] = data.get("presets") if isinstance(data.get("presets"), dict) else {}
    return data


def _write_registry_file(data):
    """Атомарно: временный файл + os.replace; права 0600. Неизвестные ключи сохраняются."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = PROJECTS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PROJECTS_FILE)


def _load_registry():
    """Project yang ditambahkan manual lewat panel (registry)."""
    return [_canon(os.path.realpath(os.path.expanduser(p))) for p in _read_registry_file()["paths"]]


def _looks_like_repo(path):
    """Repo biasa (.git folder) MAUPUN linked worktree (.git file berisi `gitdir:`)."""
    git = os.path.join(path, ".git")
    return os.path.isdir(git) or os.path.isfile(git)


def known_projects():
    """Semua path yang boleh diakses browser: hasil pemindaian + registry manual."""
    paths = set(_cache["projects"].keys()) | set(_load_registry())
    return {os.path.realpath(p) for p in paths}


def resolve(path):
    """Gerbang keamanan: path dari browser harus ada di registry server."""
    if not path:
        raise ApiError("Не указан путь проекта", code="proj.path_missing")
    real = os.path.realpath(os.path.expanduser(str(path).strip()))
    if real not in known_projects():
        raise ApiError("Неизвестный проект — сначала просканируйте папку на странице «Проекты»", HTTPStatus.NOT_FOUND,
                       code="proj.unknown")
    return real


# ---------------------------------------------------------------- git helper

def git(path, *args, timeout=10):
    """Jalankan git di dalam project (argumen list, tanpa shell).
    Selalu dengan GIT_OPTIONAL_LOCKS=0: perintah di modul ini hanya membaca,
    dan tanpa itu perintah paralel saling mengunci di index.lock."""
    try:
        code, out, err = run([GIT, "-C", path, *args], timeout=timeout, env=GIT_ENV)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return code, out if code == 0 else (out + err)


def _lines(text):
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def sanitize_url(url):
    """Buang kredensial dari URL remote (https://user:token@host -> https://host)."""
    if not url:
        return None
    return re.sub(r"^(https?://)[^@/]+@", r"\1", url.strip())


def _remote(path):
    code, out = git(path, "remote", "-v")
    if code != 0:
        return None, None
    for line in _lines(out):
        parts = line.split()
        if len(parts) >= 2:
            return parts[0], sanitize_url(parts[1])
    return None, None


def _worktree_self(path):
    """True kalau folder ini linked worktree (bukan checkout utama)."""
    gitfile = os.path.join(path, ".git")
    return os.path.isfile(gitfile)


def _status(path):
    """Ringkas `git status --porcelain=v2 --branch`. 8 detik: di repo besar
    perintah ini memang lambat, dan lebih baik menyerah daripada menggantung."""
    code, out = git(path, "status", "--porcelain=v2", "--branch", timeout=8)
    if code != 0:
        return None
    info = {"branch": None, "upstream": None, "ahead": 0, "behind": 0,
            "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0, "files": []}
    for line in _lines(out):
        if line.startswith("# branch.head "):
            info["branch"] = line[14:].strip()
        elif line.startswith("# branch.upstream "):
            info["upstream"] = line[18:].strip()
        elif line.startswith("# branch.ab "):
            m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
            if m:
                info["ahead"], info["behind"] = int(m[1]), int(m[2])
        elif line.startswith("1 ") or line.startswith("2 "):
            xy = line.split()[1]
            if xy[0] != ".":
                info["staged"] += 1
            if xy[1] != ".":
                info["modified"] += 1
            info["files"].append({"xy": xy, "path": line.split()[-1]})
        elif line.startswith("u "):
            info["conflicts"] += 1
            info["files"].append({"xy": "UU", "path": line.split()[-1]})
        elif line.startswith("? "):
            info["untracked"] += 1
            info["files"].append({"xy": "??", "path": line[2:]})
    info["files"] = info["files"][:80]
    info["dirty"] = info["staged"] + info["modified"] + info["conflicts"] + info["untracked"]
    if info["branch"] == "(detached)":
        code, out = git(path, "rev-parse", "--short", "HEAD")
        info["branch"] = f"detached@{out.strip()}" if code == 0 else "detached"
    return info


def _last_commit(path):
    code, out = git(path, "log", "-1", "--format=%h%x1f%s%x1f%an%x1f%ar%x1f%ct")
    if code != 0 or not out.strip():
        return None
    parts = out.strip().split("\x1f")
    if len(parts) < 5:
        return None
    return {"hash": parts[0], "subject": parts[1], "author": parts[2],
            "when": parts[3], "timestamp": int(parts[4]) if parts[4].isdigit() else None}


def _worktrees(path):
    code, out = git(path, "worktree", "list", "--porcelain")
    if code != 0:
        return []
    trees, current = [], {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current:
                trees.append(current)
            current = {"path": line[9:], "branch": None, "head": None, "bare": False, "detached": False}
        elif line.startswith("HEAD ") and current:
            current["head"] = line[5:7]
        elif line.startswith("branch ") and current:
            current["branch"] = line[7:].replace("refs/heads/", "")
        elif line.startswith("detached") and current:
            current["detached"] = True
        elif line.startswith("bare") and current:
            current["bare"] = True
    if current:
        trees.append(current)
    for t in trees:
        t["exists"] = os.path.isdir(t["path"])
        t["current"] = os.path.realpath(t["path"]) == os.path.realpath(path)
    return trees


def summarize(path):
    """Ringkasan satu repo untuk kartu di daftar.

    Dua tahap, dan urutannya penting: cabang/komit/remote dulu (perintah git
    yang cepat), `git status` terakhir karena di repo besar ia bisa makan
    belasan detik. Kalau status kehabisan waktu, kartu tetap tampil berguna
    dengan `dirty: null` + `slow: true` — bukan gagal total.
    """
    real = os.path.realpath(path)
    base = {"path": real, "name": os.path.basename(real), "worktree": _worktree_self(real)}
    code, head = git(real, "rev-parse", "--abbrev-ref", "HEAD", timeout=5)
    if code != 0:
        return {**base, "error": "git_failed"}
    _, remote = _remote(real)
    item = {**base, "branch": head.strip(), "remote": remote, "last": _last_commit(real)}
    status = _status(real)
    if status is None:
        return {**item, "dirty": None, "slow": True}
    return {**item, "dirty": status["dirty"], "ahead": status["ahead"], "behind": status["behind"],
            "conflicts": status["conflicts"], "untracked": status["untracked"], "slow": False}


# ---------------------------------------------------------------- scanning

def scan(q=None):
    """Cari repo git di folder kode user. Hanya membaca direktori."""
    roots = [_canon(os.path.join(HOME, r)) for r in SCAN_ROOTS if os.path.isdir(os.path.join(HOME, r))]
    extra = q.get("root") if q else None
    if extra:
        roots = [_canon(os.path.realpath(os.path.expanduser(extra)))]
    found, deadline = {}, time.time() + SCAN_BUDGET
    truncated = False
    for root in roots:
        if not os.path.isdir(root):
            continue
        stack = [(root, 0)]
        while stack:
            if time.time() > deadline:
                truncated = True
                break
            path, depth = stack.pop()
            if _looks_like_repo(path):
                real = os.path.realpath(path)
                found[real] = {"path": real, "worktree": _worktree_self(real)}
                continue  # jangan turun ke dalam repo
            if depth >= SCAN_MAX_DEPTH:
                continue
            try:
                entries = [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            stack += [(e.path, depth + 1) for e in entries
                      if e.name not in SCAN_SKIP and not e.name.startswith(".")]
    for p in _load_registry():
        if os.path.isdir(p):
            found.setdefault(os.path.realpath(p), {"path": os.path.realpath(p),
                                                   "worktree": _worktree_self(p)})
    _cache.update(t=time.time(), projects=found)
    return {"projects": sorted(found.keys()), "count": len(found), "truncated": truncated,
            "roots": [r for r in roots if os.path.isdir(r)]}


# ---------------------------------------------------------------- API

def list_projects(q=None):
    """Daftar repo (cepat — TANPA menjalankan git). `?scan=1` memaksa pemindaian
    ulang; kalau registry masih kosong, pemindaian dilakukan otomatis.
    Ringkasan git-nya diambil terpisah per repo lewat /api/projects/summary,
    supaya satu repo besar tidak menahan seluruh halaman."""
    force = bool(q and q.get("scan") == "1")
    if force or not _cache["projects"]:
        scan()
    registered = set(_load_registry())
    items = [{"path": p, "name": os.path.basename(p), "worktree": m.get("worktree", False),
              "registered": os.path.realpath(p) in registered}
             for p, m in sorted(_cache["projects"].items())]
    return {"projects": items, "scanned": True, "count": len(items)}


def project_summary(q):
    """Ringkasan git satu repo (dipanggil per kartu, paralel dari browser)."""
    return summarize(resolve(q.get("path")))


def project_detail(q):
    """Detail satu repo. Semua perintah git dijalankan paralel: `git status`
    dan `git branch` bisa lambat di repo besar, dan tidak boleh saling menunggu."""
    path = resolve(q.get("path"))
    jobs = {
        "status": lambda: _status(path),
        "worktrees": lambda: _worktrees(path),
        "log": lambda: git(path, "log", "-n", "20", "--format=%h%x1f%s%x1f%an%x1f%ar", timeout=4),
        # NB: `git branch --format` (for-each-ref) tidak mengenal escape %x1f,
        # jadi pemisahnya tab — nama branch tidak boleh mengandung tab.
        "branches": lambda: git(path, "branch", "--all",
                                "--format=%(refname:short)\t%(upstream:short)\t%(committerdate:relative)\t%(HEAD)\t%(refname)",
                                timeout=6),
        # --name-status, BUKAN --stat: menghitung jumlah baris (+) / (-) memaksa
        # git membaca isi setiap berkas yang berubah — diukur 13-25 detik pada
        # repo nyata, sedangkan daftar nama+status 0,06 detik. Statistik baris
        # disediakan terpisah lewat /api/projects/diffstat (dipicu user).
        "diff": lambda: git(path, "diff", "--name-status", "--no-renames", timeout=6),
        "staged": lambda: git(path, "diff", "--cached", "--name-status", "--no-renames", timeout=6),
        "stash": lambda: git(path, "stash", "list", timeout=4),
        "remote": lambda: _remote(path),
        "head": lambda: git(path, "rev-parse", "--abbrev-ref", "HEAD", timeout=5),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        r = {k: f.result() for k, f in futures.items()}

    status = r["status"]
    head_code, head_out = r["head"]
    if status is None and head_code != 0:
        raise ApiError("Это не git-репозиторий", HTTPStatus.BAD_REQUEST, code="proj.not_git")
    if status is None:  # git status kehabisan waktu, tapi repo-nya jelas ada
        status = {"branch": head_out.strip() or None, "upstream": None, "ahead": 0, "behind": 0,
                  "staged": 0, "modified": 0, "untracked": 0, "conflicts": 0, "files": [],
                  "dirty": None, "slow": True}

    commits = []
    for line in _lines(r["log"][1]):
        parts = line.split("\x1f")
        if len(parts) >= 4:
            commits.append({"hash": parts[0], "subject": parts[1], "author": parts[2], "when": parts[3]})
    branch_list = []
    for line in _lines(r["branches"][1]):
        parts = line.split("\t")
        if len(parts) < 5 or not parts[0]:
            continue
        if parts[4].endswith("/HEAD"):
            continue  # refs/remotes/origin/HEAD bukan branch, jangan ditampilkan
        branch_list.append({"name": parts[0], "upstream": parts[1], "when": parts[2],
                            "current": parts[3] == "*", "remote": parts[4].startswith("refs/remotes/")})
    return {"path": path, "name": os.path.basename(path), "status": status, "worktrees": r["worktrees"],
            "commits": commits, "branches": branch_list[:60], "remote": r["remote"][1],
            "worktree": _worktree_self(path),
            "changed": _name_status(r["diff"][1]), "staged_changed": _name_status(r["staged"][1]),
            "stashes": _lines(r["stash"][1])[:10],
            "registered": is_registered(path), "preset": presets_get(path)}


def _name_status(text):
    """Baris `git diff --name-status` -> [{status, path}]."""
    out = []
    for line in _lines(text):
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append({"status": parts[0], "path": parts[-1]})
    return out[:200]


def project_diffstat(q):
    """Statistik +/- per berkas. LAMBAT di repo besar (git harus membaca isi
    berkas), jadi hanya dijalankan saat user memintanya."""
    path = resolve(q.get("path"))
    args = ["diff", "--stat", "--no-renames"] + (["--cached"] if q.get("mode") == "staged" else [])
    code, out = git(path, *args, timeout=90)
    if code is None:
        raise ApiError("git diff --stat превысил лимит времени (90 с)", HTTPStatus.REQUEST_TIMEOUT,
                       code="proj.stat_timeout")
    if code != 0:
        raise ApiError("git diff --stat завершился с ошибкой", HTTPStatus.INTERNAL_SERVER_ERROR,
                       code="proj.stat_failed")
    return {"stat": out.strip() or None, "path": path}


def project_diff(q):
    """Isi diff. Path berkas (kalau ada) harus muncul di status repo itu."""
    path = resolve(q.get("path"))
    mode = q.get("mode") or "work"
    if mode not in ("work", "staged", "head"):
        raise ApiError("Недопустимый режим diff", code="proj.bad_diff_mode")
    # --no-renames WAJIB di sini: deteksi rename membuat `git diff` membaca isi
    # seluruh berkas yang berubah, dan di repo nyata itu 10+ detik vs 0,03 detik
    # (diukur). Efeknya hanya rename tampil sebagai hapus+tambah.
    args = {"work": ["diff", "--no-renames"], "staged": ["diff", "--cached", "--no-renames"],
            "head": ["diff", "HEAD", "--no-renames"]}[mode]
    target = (q.get("file") or "").strip()
    if target:
        status = _status(path) or {"files": []}
        allowed = {f["path"] for f in status["files"]}
        if target not in allowed:
            raise ApiError("Файла нет в статусе репозитория", HTTPStatus.NOT_FOUND, code="proj.file_not_in_status")
        args += ["--", target]
    code, out = git(path, *args, timeout=20)
    if code is None:
        raise ApiError("git diff превысил лимит времени — репозиторий слишком большой для полного diff",
                       HTTPStatus.REQUEST_TIMEOUT, code="proj.diff_timeout")
    if code != 0:
        raise ApiError("git diff завершился с ошибкой", HTTPStatus.INTERNAL_SERVER_ERROR, code="proj.diff_failed")
    return {"diff": out[:400_000], "path": path, "mode": mode, "file": target or None}


def github_info(q):
    """PR / issue / CI run lewat `gh` (hanya kalau gh terpasang dan remote-nya GitHub)."""
    path = resolve(q.get("path"))
    if not GH:
        return {"available": False, "reason": "gh_missing"}
    _, remote = _remote(path)
    if not remote or "github.com" not in remote:
        return {"available": False, "reason": "not_github"}
    cwd = path

    def gh(*args):
        try:
            code, out, err = run([GH, *args], timeout=25, cwd=cwd)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return _lines(out) if code == 0 else None

    prs = gh("pr", "list", "--limit", "15", "--json",
             "number,title,state,headRefName,author,isDraft,updatedAt")
    runs = gh("run", "list", "--limit", "10", "--json",
              "databaseId,displayTitle,status,conclusion,headBranch,event,createdAt")
    issues = gh("issue", "list", "--limit", "15", "--json", "number,title,state,author,updatedAt")
    try:
        prs = json.loads("".join(prs)) if prs else []
    except ValueError:
        prs = []
    try:
        runs = json.loads("".join(runs)) if runs else []
    except ValueError:
        runs = []
    try:
        issues = json.loads("".join(issues)) if issues else []
    except ValueError:
        issues = []
    return {"available": True, "remote": remote, "prs": prs, "runs": runs, "issues": issues}


# ---------------------------------------------------------------- registry: tulis (Fase 2.3)
# Path dari browser MASUK registry hanya lewat sini, jadi gerbangnya ketat: harus repo git,
# di dalam HOME user, bukan folder tersembunyi/Library, dan bukan symlink yang keluar dari HOME.

def _canon(real):
    """Привести регистр каждого компонента пути к тому, что реально лежит на диске.
    На APFS без учёта регистра `~/code/app` и `~/Code/app` — одна папка, но разные строки:
    без этого вручную добавленный проект дублировался бы с найденным сканом."""
    cur, out = os.sep, []
    for comp in [c for c in real.split(os.sep) if c]:
        name = comp
        try:
            for entry in os.listdir(cur):
                if entry.lower() == comp.lower() and os.path.samefile(os.path.join(cur, entry), os.path.join(cur, comp)):
                    name = entry
                    break
        except OSError:
            pass
        cur = os.path.join(cur, name)
        out.append(name)
    return os.sep + os.sep.join(out)


def _registrable(raw):
    if not raw or not isinstance(raw, str):
        raise ApiError("Укажите путь к проекту", code="proj.path_required")
    real = _canon(os.path.realpath(os.path.expanduser(raw.strip())))
    if not os.path.isdir(real):
        raise ApiError("Папка не найдена", HTTPStatus.NOT_FOUND, code="proj.dir_not_found")
    rel = os.path.relpath(real, HOME_REAL)
    if rel == "." or rel.startswith(".."):
        raise ApiError("Проект должен лежать внутри домашней папки", code="proj.outside_home")
    parts = rel.split(os.sep)
    if parts[0] == "Library" or any(x.startswith(".") for x in parts):
        raise ApiError("Скрытые папки и Library добавлять нельзя", code="proj.hidden_dir")
    if not _looks_like_repo(real):
        raise ApiError("Это не git-репозиторий (нет .git)", code="proj.no_dot_git")
    return real


def registry_add(body):
    real = _registrable(body.get("path"))
    data = _read_registry_file()
    existing = {_canon(os.path.realpath(os.path.expanduser(p))) for p in data["paths"]}
    if real in existing or real in _cache["projects"]:
        raise ApiError("Проект уже в списке", HTTPStatus.CONFLICT, code="proj.already_listed")
    if len(data["paths"]) >= REGISTRY_MAX:
        raise ApiError(f"Предел {REGISTRY_MAX} проектов в реестре", HTTPStatus.CONFLICT,
                       code="proj.registry_full", max=REGISTRY_MAX)
    data["paths"].append(real)
    _write_registry_file(data)
    _cache["projects"][real] = {"path": real, "worktree": _worktree_self(real)}
    return {"added": real, "registered": True}


def registry_remove(body):
    """Убрать из реестра. Папка проекта НЕ удаляется; проекты, найденные сканом, остаются в списке."""
    real = _canon(os.path.realpath(os.path.expanduser(str(body.get("path") or ""))))
    data = _read_registry_file()
    keep = [p for p in data["paths"] if _canon(os.path.realpath(os.path.expanduser(p))) != real]
    if len(keep) == len(data["paths"]):
        raise ApiError("Проекта нет в реестре (найденные сканом убрать нельзя)", HTTPStatus.NOT_FOUND,
                       code="proj.not_in_registry")
    data["paths"] = keep
    data["presets"].pop(real, None)
    _write_registry_file(data)
    _cache["projects"].pop(real, None)
    return {"removed": real}


def is_registered(path):
    real = _canon(os.path.realpath(path))
    return real in {_canon(p) for p in _load_registry()}


# Что можно запускать кнопкой test/build (Фаза 2.8). Это НЕ защита от произвольного кода: `npm test` и
# `make` по определению исполняют код проекта. Список отсекает случайное и чужое — `rm`, `curl`, `osascript`,
# `bash -c` и т.п. — и работает и при сохранении пресета, и при запуске (файл пресетов можно подправить руками).
RUN_TOOLS = {"flutter", "dart", "fvm", "npm", "npx", "pnpm", "yarn", "bun", "node", "deno", "cargo", "go", "make",
             "gradle", "mvn", "xcodebuild", "fastlane", "pod", "swift", "python3", "pytest", "uv", "poetry", "ruby",
             "bundle", "rake", "composer", "php", "phpunit", "dotnet"}
RUN_INTERPRETERS = {"python3", "node", "ruby", "php", "deno"}
RUN_EVAL_FLAGS = {"-c", "-e", "--eval", "-p", "--print", "-r", "--require", "--import", "-x"}  # «выполни это выражение»


def runnable_argv(project, value):
    """Строка пресета → argv, если она разрешена к запуску в проекте; иначе ApiError."""
    try:
        argv = shlex.split(value)
    except ValueError as e:
        raise ApiError(f"Команда: {e}", code="proj.cmd_parse", detail=str(e)) from None
    if not argv:
        raise ApiError("Команда пуста", code="proj.cmd_empty")
    exe = argv[0]
    if exe.startswith("./"):
        real = os.path.realpath(os.path.join(project, exe))
        if os.path.commonpath([real, os.path.realpath(project)]) != os.path.realpath(project) \
                or not os.path.isfile(real) or not os.access(real, os.X_OK):
            raise ApiError(f"«{exe}»: нужен исполняемый файл внутри проекта", code="proj.exe_inside", exe=exe)
    elif exe not in RUN_TOOLS:
        raise ApiError(f"«{exe}» не входит в список разрешённых инструментов ({', '.join(sorted(RUN_TOOLS))}) "
                       "и не является ./скриптом проекта", code="proj.exe_not_allowed", exe=exe,
                       tools=", ".join(sorted(RUN_TOOLS)))
    if os.path.basename(exe) in RUN_INTERPRETERS and any(a in RUN_EVAL_FLAGS for a in argv[1:]):
        raise ApiError("Флаги выполнения выражения (-c, -e, --eval …) не допускаются: используйте скрипт или модуль",
                       code="proj.eval_flags")
    return argv


def _check_cmd(name, value, project=None):
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > PRESET_CMD_MAX_LEN:
        raise ApiError(f"{name}: слишком длинная команда", code="proj.cmd_too_long", name=name)
    if PRESET_SHELL_CHARS & set(value):
        raise ApiError(f"{name}: символы ; & | < > ` $ и переводы строк не допускаются — пресет это команда, а не shell-выражение",
                       code="proj.cmd_shell_chars", name=name)
    try:
        argv = shlex.split(value)
    except ValueError as e:
        raise ApiError(f"{name}: {e}", code="proj.cmd_prefixed", name=name, detail=str(e)) from None
    if not argv or len(argv) > PRESET_CMD_MAX_ARGS:
        raise ApiError(f"{name}: от 1 до {PRESET_CMD_MAX_ARGS} аргументов", code="proj.cmd_args_count",
                       name=name, max=PRESET_CMD_MAX_ARGS)
    if project:
        try:
            runnable_argv(project, value)
        except ApiError as e:
            raise ApiError(f"{name}: {e}", code="proj.cmd_prefixed", name=name, detail=str(e)) from None
    return " ".join(shlex.quote(a) for a in argv)  # нормализованная запись


def presets_get(path):
    return _read_registry_file()["presets"].get(os.path.realpath(path), {"editor": "", "test": "", "build": ""})


def preset_set(body, editors=()):
    """Пресет проекта: редактор + команды test/build (запускаются кнопками, runs.py; список разрешённых — RUN_TOOLS)."""
    real = resolve(body.get("path"))
    editor = body.get("editor") or ""
    if editor and editor not in editors:
        raise ApiError("Неизвестный редактор", code="proj.unknown_editor")
    preset = {"editor": editor, "test": _check_cmd("test", body.get("test"), real), "build": _check_cmd("build", body.get("build"), real)}
    data = _read_registry_file()
    if any(preset.values()):
        data["presets"][real] = preset
    else:
        data["presets"].pop(real, None)
    _write_registry_file(data)
    return {"path": real, "preset": preset}
