"""Helper bersama: menjalankan perintah, job background, state, dan
pengelolaan ~/.zshrc + shim runtime (~/.service-admin/bin)."""
import itertools
import json
import os
import re
import shlex
import shutil
import sys
import subprocess
import threading
import time
from collections import deque
from http import HTTPStatus

HOME = os.path.expanduser("~")
DATA_DIR = os.path.join(HOME, ".service-admin")
try:  # данные панели (журналы, токены, состояние) — только владельцу: домашние каталоги Debian/Ubuntu по умолчанию читаются другими пользователями
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
except OSError:
    pass
SHIM_DIR = os.path.join(DATA_DIR, "bin")
ENV_FILE = os.path.join(DATA_DIR, "env.zsh")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

BREW = shutil.which("brew") or "/opt/homebrew/bin/brew"
BREW_PREFIX = os.path.dirname(os.path.dirname(os.path.realpath(BREW)))
PKG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+/-]*$")

ZSH_FILES = [".zshrc", ".zprofile", ".zshenv", ".zlogin"]
ZSHRC_BLOCK_START = "# >>> mac-service-admin >>>"
ZSHRC_BLOCK = (f"{ZSHRC_BLOCK_START}\n"
               "# Versi runtime yang dipilih lewat Service Admin (PHP, Python, Java, ...)\n"
               'export PATH="$HOME/.service-admin/bin:$PATH"\n'
               '[ -f "$HOME/.service-admin/env.zsh" ] && source "$HOME/.service-admin/env.zsh"\n'
               "# <<< mac-service-admin <<<\n")

ENV = dict(os.environ, HOMEBREW_NO_ENV_HINTS="1", NONINTERACTIVE="1",
           PATH=f"{BREW_PREFIX}/bin:{BREW_PREFIX}/sbin:" + os.environ.get("PATH", "/usr/bin:/bin"))


class ApiError(Exception):
    """Ошибка для интерфейса. `msg` — понятный текст по-русски (язык по умолчанию, он же запасной).
    `code` + `params` — стабильный ключ и значения для перевода: интерфейс ищет `err.<code>` в словаре
    выбранного языка и подставляет `{param}`; нет перевода — показывает `msg`."""
    def __init__(self, msg, status=HTTPStatus.BAD_REQUEST, code=None, **params):
        super().__init__(msg)
        self.status = status
        self.code = code
        self.params = params


# /usr/bin/<alat> di macOS TANPA Command Line Tools hanyalah stub: memanggilnya tidak menjalankan
# apa pun, melainkan membuka dialog Apple "Install Command Line Tools". Panel tidak boleh memicu
# dialog itu secara tak sengaja (deteksi, scan project, dll.) — hanya lewat tombol di Persiapan Sistem.
CLT_SHIMS = {"git", "python3", "python", "pip3", "swift", "swiftc", "ruby", "make", "clang", "clang++",
             "gcc", "g++", "cc", "c++", "ld", "ar", "nm", "lipo", "otool", "strip", "svn", "xcrun",
             "xcodebuild", "lldb", "gdb", "bison", "flex", "m4", "patch", "git-lfs", "gnumake"}
_CLT_CACHE = {"t": 0.0, "ok": None}


def has_clt():
    """Command Line Tools (atau Xcode penuh) terpasang. Di-cache beberapa detik.
    Linux: «инструменты разработчика готовы» = есть git (стабов Apple там нет)."""
    if sys.platform != "darwin":
        return shutil.which("git", path=ENV["PATH"]) is not None
    now = time.time()
    if _CLT_CACHE["ok"] is None or now - _CLT_CACHE["t"] > 3:
        try:
            ok = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True, timeout=5,
                                stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        _CLT_CACHE.update(t=now, ok=ok)
    return _CLT_CACHE["ok"]


def clt_stub(cmd0, env=None):
    """True kalau cmd0 adalah stub /usr/bin yang akan membuka dialog CLT (CLT belum terpasang)."""
    if not cmd0 or sys.platform != "darwin":  # стабы /usr/bin, открывающие диалог CLT, бывают только на macOS
        return False
    path = cmd0 if "/" in cmd0 else shutil.which(cmd0, path=(env or ENV)["PATH"])
    return bool(path) and os.path.dirname(path) == "/usr/bin" and os.path.basename(path) in CLT_SHIMS \
        and not has_clt()


def run(cmd, timeout=60, cwd=None, env=None):
    if cmd and clt_stub(cmd[0], env):
        return 127, "", "Xcode Command Line Tools are not installed"
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=env or ENV, stdin=subprocess.DEVNULL, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


def loads_or(text, default):
    """JSON из вывода внешнего инструмента. Пустой вывод или текст ошибки (инструмент не установлен/не запущен,
    нет плагина) — не «внутренняя ошибка» панели, а просто «данных нет»: возвращаем `default`."""
    try:
        return json.loads(text) if text and text.strip() else default
    except ValueError:
        return default


def output(cmd, timeout=20, **kw):
    """stdout+stderr sebuah perintah, atau "" kalau gagal dijalankan."""
    try:
        _, out, err = run(cmd, timeout=timeout, **kw)
        return (out + err).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def tail(path, lines=200):
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", errors="replace") as f:
        return "".join(deque(f, maxlen=lines))


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    os.makedirs(DATA_DIR, exist_ok=True)
    state = {**load_state(), **changes}
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------- jobs
# Perintah lama (brew install, nvm install, ...) berjalan di background;
# UI mem-poll outputnya.

JOBS = {}
JOB_IDS = itertools.count(1)
JOB_LOCK = threading.Lock()


def spawn(target, *args):
    """Поток-демон, который наследует контекст (инициатора аудита); обычный threading.Thread его теряет."""
    import contextvars
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(target, *args), daemon=True)
    t.start()
    return t


def _initiator():
    try:
        import audit
        return audit.current_initiator()
    except Exception:  # noqa: BLE001
        return None


def _audit_job(job, label, kind):
    try:
        import audit
        audit.record("job:" + kind, {"label": label, "job": job["id"]}, "ok" if job["code"] == 0 else "failed",
                     int((time.time() - job["started"]) * 1000), code=job["code"], extra={"by": job.get("by")} if job.get("by") else None)
    except Exception:  # noqa: BLE001 - audit tidak boleh merusak job
        pass


def start_job(label, cmd, kind, cwd=None, env=None, exclusive=True):
    with JOB_LOCK:
        if exclusive and any(j["kind"] == kind and not j["done"] for j in JOBS.values()):
            raise ApiError(f"Уже выполняется процесс {kind}, дождитесь завершения.",
                           HTTPStatus.CONFLICT, code="core.job_running", kind=kind)
        job_id = str(next(JOB_IDS))
        job = JOBS[job_id] = {"id": job_id, "label": label, "kind": kind, "lines": [],
                              "done": False, "code": None, "started": time.time(), "by": _initiator()}

    def worker():
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd,
                                    stdin=subprocess.DEVNULL, text=True, env=env or ENV, bufsize=1,
                                    start_new_session=True)  # grup proses sendiri -> bisa dihentikan semua
            job["_proc"] = proc
            for line in proc.stdout:
                if line.startswith("__SA_PWD__"):  # folder kerja terakhir dari perintah shell
                    job["pwd"] = line[10:].strip()
                    if job["lines"] and job["lines"][-1] == "":
                        job["lines"].pop()  # baris kosong sebelum penanda
                    continue
                job["lines"].append(line.rstrip("\n"))
                del job["lines"][:-5000]
            job["code"] = proc.wait()
            if job.get("cancelled"):
                job["code"] = 143  # 128 + SIGTERM, walau trap EXIT di shell keluar dengan 0
                job["lines"].append("⏹  Остановлено.")
        except Exception as e:  # noqa: BLE001
            job["lines"].append(f"ERROR: {e}")
            job["code"] = -1
        job["done"] = True
        _audit_job(job, label, kind)

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def start_steps(label, steps, kind):
    """Job berisi beberapa langkah berurutan; berhenti di langkah pertama yang gagal.
    steps: [(judul, cmd_list | callable(log) , {"cwd":..., "env":..., "optional": bool})]"""
    with JOB_LOCK:
        if any(j["kind"] == kind and not j["done"] for j in JOBS.values()):
            raise ApiError(f"Уже выполняется процесс {kind}, дождитесь завершения.", HTTPStatus.CONFLICT,
                           code="core.job_running", kind=kind)
        job_id = str(next(JOB_IDS))
        job = JOBS[job_id] = {"id": job_id, "label": label, "kind": kind, "lines": [],
                              "done": False, "code": None, "started": time.time(), "by": _initiator()}

    def log(line):
        job["lines"].append(line)
        del job["lines"][:-5000]

    def worker():
        code = 0
        for i, (title, cmd, opt) in enumerate(steps, 1):
            if job.get("cancelled"):
                log("\n⏹ отменено")
                code = code or 130
                break
            log(f"\n▶ [{i}/{len(steps)}] {title}")
            try:
                if callable(cmd):
                    cmd(log)
                    rc = 0
                else:
                    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                            stdin=subprocess.DEVNULL, cwd=opt.get("cwd"), env=opt.get("env") or ENV)
                    for line in proc.stdout:
                        log(line.rstrip("\n"))
                    rc = proc.wait()
            except Exception as e:  # noqa: BLE001
                log(f"ERROR: {e}")
                rc = -1
            if rc != 0:
                if opt.get("optional"):
                    log(f"⚠️  Этот шаг завершился с ошибкой (exit {rc}), пропущен.")
                    continue
                log(f"❌ Сбой на шаге {i} (exit {rc}).")
                code = rc
                break
        else:
            log("\n✅ Готово.")
        job["code"] = code
        job["done"] = True
        _audit_job(job, label, kind)

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def ps_snapshot():
    """(procs, children) dari satu kali `ps -A`:
    procs[pid] = (cpu%, rss kB, etime), children[ppid] = [pid, ...].
    Mengembalikan ({}, {}) kalau `ps` tidak bisa dijalankan (mis. diblokir sandbox)."""
    try:
        _, out, _ = run(["ps", "-A", "-o", "pid=,ppid=,pcpu=,rss=,etime="])
    except OSError:
        return {}, {}
    procs, children = {}, {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        pid, ppid, cpu, rss, etime = parts
        try:
            procs[pid] = (float(cpu), int(rss), etime)
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    return procs, children


def pid_tree_stats(pids, snapshot=None):
    """CPU %, memori (MB) dan uptime per proses, termasuk anak-anaknya
    (mis. mysqld_safe -> mysqld, atau sesi Claude Code beserta sub-prosesnya).
    `snapshot` = hasil ps_snapshot() kalau pemanggil sudah punya, supaya tidak
    menjalankan `ps` berkali-kali."""
    pids = [str(p) for p in pids if p]
    if not pids:
        return {}
    procs, children = snapshot or ps_snapshot()
    stats = {}
    for root in pids:
        if root not in procs:
            continue
        cpu = rss = count = 0
        stack = [root]
        while stack:
            p = stack.pop()
            cpu += procs[p][0]
            rss += procs[p][1]
            count += 1
            stack.extend(children.get(p, []))
        stats[root] = {"cpu": round(cpu, 1), "mem_mb": round(rss / 1024, 1),
                       "uptime": procs[root][2], "procs": count}
    return stats


def list_jobs(q=None):
    """Proses terbaru (untuk tombol terminal di header)."""
    jobs = sorted(JOBS.values(), key=lambda j: -j["started"])[:30]
    return {"jobs": [{k: v for k, v in j.items() if k != "lines" and not k.startswith("_")} | {"lines_count": len(j["lines"])}
                     for j in jobs]}


def cancel_job(body):
    """Hentikan job (SIGTERM ke seluruh grup prosesnya, SIGKILL kalau bandel)."""
    import signal
    job = JOBS.get(str(body.get("id", "")))
    if not job:
        raise ApiError("Задача не найдена", HTTPStatus.NOT_FOUND, code="core.job_not_found")
    proc = job.get("_proc")
    if job["done"]:
        return {"ok": True}
    job["cancelled"] = True  # start_steps смотрит на флаг между шагами, даже если процесса сейчас нет
    if not proc:
        return {"ok": True}
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return {"ok": True}


def get_job(job_id, offset):
    job = JOBS.get(job_id)
    if not job:
        raise ApiError("Задача не найдена", HTTPStatus.NOT_FOUND, code="core.job_not_found")
    return {**{k: v for k, v in job.items() if k != "lines" and not k.startswith("_")},
            "lines": job["lines"][offset:], "offset": len(job["lines"])}


# ---------------------------------------------------------------- file zsh

def check_zsh_file(name):
    if name not in ZSH_FILES:
        raise ApiError("Файл не разрешён", code="core.file_not_allowed")
    return os.path.join(HOME, name)


def read_home(name):
    try:
        with open(check_zsh_file(name), errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def list_backups(name):
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted((f for f in os.listdir(BACKUP_DIR)
                   if re.fullmatch(re.escape(name) + r"\.\d{8}-\d{6}", f)), reverse=True)


def backup(name):
    path = check_zsh_file(name)
    if not os.path.isfile(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, f"{name}.{time.strftime('%Y%m%d-%H%M%S')}")
    if os.path.exists(dest):  # dua kali simpan di detik yang sama: pertahankan versi tertua
        return os.path.basename(dest)
    shutil.copy2(path, dest)
    for old in list_backups(name)[20:]:  # simpan 20 terakhir
        os.remove(os.path.join(BACKUP_DIR, old))
    return os.path.basename(dest)


def shell_name():
    """Оболочка пользователя: macOS — zsh; Linux — $SHELL, если это zsh/bash, иначе bash."""
    if sys.platform == "darwin":
        return "zsh"
    return "zsh" if os.path.basename(os.environ.get("SHELL", "")) == "zsh" and shutil.which("zsh") else "bash"


def shell_rc():
    return ".zshrc" if shell_name() == "zsh" else ".bashrc"


def ensure_zshrc_block():
    """Pastikan blok Service Admin ada di PALING BAWAH .zshrc supaya
    menang dari baris PATH lain (mis. yang disuntik Herd)."""
    path = os.path.join(HOME, shell_rc())
    content = read_home(shell_rc())
    stripped = re.sub(r"\n*# >>> mac-service-admin >>>.*?# <<< mac-service-admin <<<\n?", "\n",
                      content, flags=re.S).rstrip("\n")
    new = stripped + "\n\n" + ZSHRC_BLOCK
    if new != content:
        backup(shell_rc())
        with open(path, "w") as f:
            f.write(new)


# ---------------------------------------------------------------- shim & env per bahasa

def set_shims(lang, mapping):
    """Ganti symlink milik `lang` di ~/.service-admin/bin dengan {nama: target}.
    mapping kosong = hapus override bahasa itu."""
    os.makedirs(SHIM_DIR, exist_ok=True)
    state = load_state()
    shims = state.get("shims")
    if shims is None:  # versi lama: semua symlink milik PHP
        shims = {"php": [f for f in os.listdir(SHIM_DIR) if os.path.islink(os.path.join(SHIM_DIR, f))]}
    for name in shims.get(lang, []):
        p = os.path.join(SHIM_DIR, name)
        if os.path.islink(p):
            os.unlink(p)
    for other, names in shims.items():  # nama yang direbut bahasa lain
        if other != lang:
            shims[other] = [n for n in names if n not in mapping]
    for name, target in mapping.items():
        p = os.path.join(SHIM_DIR, name)
        if os.path.islink(p):
            os.unlink(p)
        os.symlink(target, p)
    shims[lang] = sorted(mapping)
    save_state(shims=shims)
    if mapping:
        ensure_zshrc_block()


def set_env(lang, variables):
    """Simpan variabel environment milik `lang` (mis. JAVA_HOME) ke env.zsh."""
    state = load_state()
    env = state.get("env", {})
    if variables:
        env[lang] = variables
    else:
        env.pop(lang, None)
    save_state(env=env)
    os.makedirs(DATA_DIR, exist_ok=True)
    lines = ["# Dibuat otomatis oleh Service Admin — jangan diedit manual"]
    for group in env.values():
        lines += [f"export {k}={shlex.quote(v)}" for k, v in group.items()]
    with open(ENV_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")
    ensure_zshrc_block()


def shell_probe(names):
    """Path + nilai yang dipakai terminal baru (zsh interaktif) untuk tiap
    perintah, mis. {"python3": "/opt/.../python3"}. Juga env JAVA_HOME dll."""
    script = "; ".join(f'echo "__{n}__$(command -v {shlex.quote(n)})"' for n in names)
    script += '; echo "__ENV_JAVA_HOME__${JAVA_HOME}"'
    try:
        _, out, _ = run([shell_name(), "-i", "-c", script], timeout=20)
    except subprocess.TimeoutExpired:
        return {}
    result = {}
    for line in out.splitlines():
        m = re.match(r"__(.+?)__(.*)", line)
        if m:
            result[m[1]] = m[2].strip()
    return result


def notify(title, text):
    """Уведомление macOS (центр уведомлений) — без диалога и без ожидания. Текст передаётся аргументами osascript (не подставляется в скрипт).
    Возвращает True, если команда отработала; любая ошибка (нет графического сеанса, запрет уведомлений) молча игнорируется."""
    if sys.platform != "darwin":
        exe = shutil.which("notify-send", path=ENV["PATH"])
        if not exe:
            return False
        try:
            return subprocess.run([exe, "--", str(title)[:80], str(text)[:240]], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    script = "on run argv\n display notification (item 1 of argv) with title (item 2 of argv)\nend run"
    try:
        r = subprocess.run(["/usr/bin/osascript", "-e", script, str(text)[:240], str(title)[:80]], capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
