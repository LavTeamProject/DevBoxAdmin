"""Laravel Herd, версии PHP и Node.js (nvm): чтение состояния и действия.

Вынесено из server.py. Изменяющие действия (`php_select`, `herd_action`, `herd_site_action`, `herd_new`, `node_action`) исполняются
только здесь — и страницей, и (через каталог операций) агентами. Только стандартная библиотека; команды — списком аргументов, без shell.
"""
import json
import os
import re
import shutil
import subprocess
import time
from http import HTTPStatus

import brewsvc
import runtimes
from core import (shell_name, shell_rc, BREW_PREFIX, DATA_DIR, ENV, HOME, SHIM_DIR, ZSHRC_BLOCK_START, ApiError, load_state, loads_or, read_home, run,
                  save_state, set_shims, start_job, start_steps, tail)


HERD_BIN = os.path.join(HOME, "Library/Application Support/Herd/bin")


NVM_DIR = os.path.join(HOME, ".nvm")


NVM_SH = next((p for p in (os.path.join(NVM_DIR, "nvm.sh"),
                           os.path.join(BREW_PREFIX, "opt/nvm/nvm.sh")) if os.path.isfile(p)), None)


NODE_VER_RE = re.compile(r"^(v?\d+(\.\d+){0,2}|lts/[a-z*]+|node|system)$")


def php_versions():
    """Semua PHP yang terdeteksi: keg Homebrew + binary Laravel Herd."""
    found = []
    opt = os.path.join(BREW_PREFIX, "opt")
    seen = {}
    for entry in sorted(os.listdir(opt) if os.path.isdir(opt) else [], key=len):
        if not re.fullmatch(r"php(@\d+\.\d+)?", entry):
            continue
        real = os.path.realpath(os.path.join(opt, entry))
        if real in seen or not os.path.isfile(os.path.join(real, "bin/php")):
            continue
        seen[real] = entry
        found.append({"id": f"brew:{entry}", "source": "Homebrew", "formula": entry,
                      "bin": os.path.join(opt, entry, "bin/php"),
                      "version": os.path.basename(real)})
    if os.path.isdir(HERD_BIN):
        for entry in sorted(os.listdir(HERD_BIN)):
            m = re.fullmatch(r"php(\d)(\d)", entry)
            if m:
                found.append({"id": f"herd:{entry}", "source": "Herd",
                              "bin": os.path.join(HERD_BIN, entry),
                              "version": f"{m[1]}.{m[2]}"})
    for p in found:  # versi lengkap, mis. 8.4.23
        code, out, _ = run([p["bin"], "-r", "echo PHP_VERSION;"], timeout=10)
        if code == 0 and out.strip():
            p["version"] = out.strip()
    return found


def shell_check():
    """Apa yang benar-benar dipakai terminal baru (zsh interaktif)."""
    script = ('echo "__PHP__$(command -v php)"; echo "__PHPV__$(php -r \'echo PHP_VERSION;\' 2>/dev/null)"; '
              'echo "__NODE__$(command -v node)"; echo "__NODEV__$(node -v 2>/dev/null)"')
    try:
        _, out, _ = run([shell_name(), "-i", "-c", script], timeout=20)
    except subprocess.TimeoutExpired:
        return {}
    result = {}
    for line in out.splitlines():
        m = re.match(r"__(PHP|PHPV|NODE|NODEV)__(.*)", line)
        if m:
            result[m[1].lower()] = m[2].strip()
    return result


HERD = os.path.join(HERD_BIN, "herd")


def herd_versions():
    """Parse tabel `herd php:list` -> [{version, installed, global, update}]."""
    if not os.path.isfile(HERD):
        return []
    try:
        _, out, _ = run([HERD, "php:list", "--no-ansi"], timeout=30)
    except subprocess.TimeoutExpired:
        return []
    rows = []
    for line in out.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.match(r"\d+\.\d+", cells[0]):
            rows.append({"version": cells[0].rstrip(" *"), "global": cells[0].endswith("*"),
                         "installed": cells[1] == "Installed", "update": cells[2] == "Yes"})
    return rows


def php_info():
    state = load_state()
    active = state.get("php")
    link = os.path.join(SHIM_DIR, "php")
    shell = shell_check()
    return {
        "versions": php_versions(), "selected": active if os.path.islink(link) else None,
        "shell": {"path": shell.get("php"), "version": shell.get("phpv")},
        "shim_active": shell.get("php") == link,
        "block_installed": ZSHRC_BLOCK_START in read_home(shell_rc()),
        "herd": herd_versions(),
    }


def php_select(body):
    choice = body.get("id")
    if choice in (None, "", "default"):
        set_shims("php", {})
        save_state(php=None)
        runtimes._cache["data"] = None
        return {"ok": True}
    target = next((p for p in php_versions() if p["id"] == choice), None)
    if not target:
        raise ApiError("Неизвестная версия PHP", HTTPStatus.NOT_FOUND, code="srv.php_unknown")
    if target["source"] == "Homebrew":
        bindir = os.path.dirname(target["bin"])  # php, phpize, php-config, pecl, pear, ...
        set_shims("php", {exe: os.path.join(bindir, exe) for exe in os.listdir(bindir)})
    else:
        # Herd: ganti versi global Herd (dipakai situs + shim `php` milik Herd),
        # lalu arahkan shim kita ke shim Herd agar mengikuti `herd use`.
        ver = re.sub(r"php(\d)(\d)", r"\1.\2", target["id"].split(":")[1])
        code, out, err = run([HERD, "use", ver, "--no-interaction", "--no-ansi"], timeout=120)
        if code != 0:
            raise ApiError((out + err).strip() or "Ошибка herd use", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if (out + err).strip() else "srv.herd_use_failed")
        set_shims("php", {"php": os.path.join(HERD_BIN, "php")})
    save_state(php=choice)
    runtimes._cache["data"] = None
    return {"ok": True}


def herd_action(body):
    action, ver = body.get("action"), str(body.get("version", ""))
    if not re.fullmatch(r"\d+\.\d+", ver) or action not in ("install", "update"):
        raise ApiError("Недопустимый запрос", code="srv.request_invalid")
    return {"job": start_job(f"herd php:{action} {ver}",
                             [HERD, f"php:{action}", ver, "--no-interaction", "--no-ansi"], "herd")}


def nvm(*args, timeout=60):
    if not NVM_SH:
        raise ApiError("nvm не найден", HTTPStatus.NOT_FOUND, code="srv.nvm_missing")
    script = f'export NVM_DIR="{NVM_DIR}"; . "$1" --no-use; shift; nvm "$@"'
    return ["bash", "-c", script, "_", NVM_SH, *args] if timeout is None else \
        run(["bash", "-c", script, "_", NVM_SH, *args], timeout=timeout)


def node_info():
    versions_dir = os.path.join(NVM_DIR, "versions/node")
    installed = sorted(os.listdir(versions_dir) if os.path.isdir(versions_dir) else [],
                       key=lambda v: [int(x) for x in re.findall(r"\d+", v)], reverse=True)
    alias = ""
    try:
        with open(os.path.join(NVM_DIR, "alias/default")) as f:
            alias = f.read().strip()
    except OSError:
        pass
    _, resolved, _ = nvm("version", "default") if NVM_SH else (0, "", "")
    system = None
    brew_node = os.path.join(BREW_PREFIX, "bin/node")
    if os.path.exists(brew_node):
        _, out, _ = run([brew_node, "-v"], timeout=10)
        system = out.strip()
    shell = shell_check()
    return {"nvm": bool(NVM_SH), "installed": installed, "default_alias": alias,
            "default_resolved": resolved.strip(), "system": system,
            "shell": {"path": shell.get("node"), "version": shell.get("nodev")}}


def node_remote():
    code, out, err = nvm("ls-remote", "--lts", timeout=60)
    if code != 0:
        raise ApiError(err.strip() or "Не удалось получить список версий", HTTPStatus.BAD_GATEWAY, code=None if err.strip() else "srv.versions_list_failed")
    latest = []
    for line in out.splitlines():
        m = re.search(r"(v\d+\.\d+\.\d+)\s+\(Latest LTS: ([^)]+)\)", line)
        if m:
            latest.append({"version": m[1], "codename": m[2]})
    return {"lts": latest[::-1]}


def node_action(body):
    action, version = body.get("action"), str(body.get("version", "")).strip()
    if not NODE_VER_RE.match(version):
        raise ApiError("Недопустимая версия", code="srv.version_invalid")
    if action == "default":
        runtimes._cache["data"] = None
        code, out, err = nvm("alias", "default", version)
        if code != 0:
            raise ApiError((out + err).strip(), HTTPStatus.INTERNAL_SERVER_ERROR)
        return {"ok": True, "output": out.strip()}
    if action == "install":
        return {"job": start_job(f"nvm install {version}", nvm("install", version, timeout=None), "nvm")}
    if action == "uninstall":
        return {"job": start_job(f"nvm uninstall {version}", nvm("uninstall", version, timeout=None), "nvm")}
    raise ApiError("Недопустимое действие", code="srv.action_invalid")


HERD_LOG_DIR = os.path.join(HOME, "Library/Application Support/Herd/Log")


SITE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


PROXY_HOST_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d+)?/?$")


def herd(*args, timeout=60):
    """Jalankan CLI Herd dari $HOME (beberapa perintah bergantung pada cwd)."""
    if not os.path.isfile(HERD):
        raise ApiError("Herd не установлен", HTTPStatus.NOT_FOUND, code="srv.herd_not_installed")
    return run([HERD, *args, "--no-ansi", "--no-interaction"], timeout=timeout, cwd=HOME)


def parse_table(out):
    """Tabel ASCII Herd (+---+ | a | b |) -> list of dict."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in out.splitlines() if line.strip().startswith("|")]
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:]]


def herd_processes():
    procs = {"app": False, "nginx": False, "dnsmasq": False, "fpm": []}
    for line in sh_lines(["ps", "-Ao", "command="]):
        if "Herd.app/Contents/MacOS/Herd" in line:
            procs["app"] = True
        elif line.startswith("nginx: master") and "Herd" in line:
            procs["nginx"] = True
        elif "Herd.app" in line and "dnsmasq" in line:
            procs["dnsmasq"] = True
        m = re.search(r"php-fpm: master process .*Herd/config/fpm/([\d.]+)-fpm", line)
        if m:
            procs["fpm"].append(m[1])
    return procs


def sh_lines(cmd):
    try:
        return run(cmd, timeout=10)[1].splitlines()
    except subprocess.TimeoutExpired:
        return []


def herd_info():
    if not os.path.isfile(HERD):
        return {"installed": False}
    from concurrent.futures import ThreadPoolExecutor
    calls = {"sites": ("sites", "--json"), "links": ("links",), "isolated": ("isolated",),
             "proxies": ("proxies",), "paths": ("paths",), "tld": ("tld",), "version": ("--version",)}
    with ThreadPoolExecutor(len(calls) + 1) as pool:
        futures = {k: pool.submit(herd, *a) for k, a in calls.items()}
        versions_f = pool.submit(herd_versions)
        out = {k: f.result()[1] for k, f in futures.items()}
        versions = versions_f.result()
    try:
        sites = loads_or(out["sites"], [])
    except ValueError:
        sites = []
    links = {r.get("Site") for r in parse_table(out["links"])}
    isolated = {r.get("Path", "").rsplit(".", 1)[0] for r in parse_table(out["isolated"])}
    global_php = next((v["version"] for v in versions if v["global"]), None)
    clean = []
    for s in sites:
        # PENTING: field "env" berisi isi .env (APP_KEY, password DB, ...) — jangan dikirim ke browser
        clean.append({
            "name": s.get("site"), "url": s.get("url"), "secured": bool(s.get("secured")),
            "php": s.get("phpVersion"), "node": s.get("nodeVersion"),
            "path": os.path.realpath(s.get("path") or ""), "favorite": bool(s.get("favorite")),
            "isolated": s.get("site") in isolated, "linked": s.get("site") in links,
            "has_db": bool(s.get("hasDatabaseCredentials")),
        })
    try:
        paths = sorted({p.rstrip("/") for p in loads_or(out["paths"], [])})
    except ValueError:
        paths = []
    return {
        "installed": True, "version": out["version"].strip().replace("Herd ", ""),
        "tld": out["tld"].strip(), "global_php": global_php,
        "php_installed": [v["version"] for v in versions if v["installed"]],
        "processes": herd_processes(), "sites": clean,
        "proxies": parse_table(out["proxies"]), "paths": paths,
    }


def herd_site_action(body):
    action, name = body.get("action"), str(body.get("name", ""))
    if action in ("start", "stop", "restart"):
        return {"job": start_job(f"herd {action}", [HERD, action, "--no-ansi", "--no-interaction"], "herd", cwd=HOME)}
    if action == "open-app":
        run(["open", "-a", "Herd"])
        return {"ok": True}
    if action in ("link", "park", "forget"):
        path = os.path.realpath(os.path.expanduser(str(body.get("path", "")).strip()))
        if not os.path.isdir(path):
            raise ApiError(f"Папка не найдена: {path}", code="srv.folder_not_found", path=path)
        if action == "link":
            if name and not SITE_RE.match(name):
                raise ApiError("Недопустимое имя сайта", code="srv.site_name_invalid")
            cmd = [HERD, "link", *([name] if name else []), "--no-ansi", "--no-interaction"]
            if body.get("secure"):
                cmd.append("--secure")
            if re.fullmatch(r"\d+\.\d+", str(body.get("php", ""))):
                cmd.append(f"--isolate={body['php']}")
            return {"job": start_job(f"herd link {name or os.path.basename(path)}", cmd, "herd", cwd=path)}
        return {"job": start_job(f"herd {action} {path}", [HERD, action, path, "--no-ansi", "--no-interaction"], "herd", cwd=HOME)}
    if action == "proxy":
        host = str(body.get("host", "")).strip()
        if not SITE_RE.match(name) or not PROXY_HOST_RE.match(host):
            raise ApiError("Недопустимое имя или хост прокси (пример хоста: http://localhost:3000)", code="srv.proxy_invalid")
        cmd = [HERD, "proxy", name, host, "--no-ansi", "--no-interaction"] + (["--secure"] if body.get("secure") else [])
        return {"job": start_job(f"herd proxy {name}", cmd, "herd", cwd=HOME)}
    if not SITE_RE.match(name):
        raise ApiError("Недопустимое имя сайта", code="srv.site_name_invalid")
    if action == "php":
        ver = str(body.get("php", ""))
        if ver == "global":
            cmd = [HERD, "unisolate", f"--site={name}"]
        elif re.fullmatch(r"\d+\.\d+", ver):
            cmd = [HERD, "isolate", ver, f"--site={name}"]
        else:
            raise ApiError("Недопустимая версия PHP", code="srv.php_invalid")
        return {"job": start_job(f"herd PHP {name} → {ver}", cmd + ["--no-ansi", "--no-interaction"], "herd", cwd=HOME)}
    if action == "folder":
        site = next((s for s in herd_info()["sites"] if s["name"] == name), None)
        if not site:
            raise ApiError("Сайт не найден", HTTPStatus.NOT_FOUND, code="srv.site_not_found")
        run(["open", site["path"]])
        return {"ok": True}
    cmds = {"secure": ["secure", name], "unsecure": ["unsecure", name],
            "unlink": ["unlink", name], "unproxy": ["unproxy", name]}
    if action not in cmds:
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    return {"job": start_job(f"herd {' '.join(cmds[action])}", [HERD, *cmds[action], "--no-ansi", "--no-interaction"], "herd", cwd=HOME)}


SCAN_ROOTS = ["Documents", "Projects", "Code", "Sites", "Developer", "Herd", "Desktop"]


SCAN_SKIP = {"node_modules", "vendor", ".git", "storage", "Library", ".Trash", "bootstrap", "public", "resources"}


def project_type(path):
    has = lambda f: os.path.exists(os.path.join(path, f))  # noqa: E731
    if has("artisan"):
        return "Laravel"
    if has("wp-config.php") or has("wp-login.php"):
        return "WordPress"
    if has("composer.json"):
        return "PHP (Composer)"
    if has("index.php") or has("public/index.php"):
        return "PHP"
    return None


def php_constraint(path):
    try:
        with open(os.path.join(path, "composer.json")) as f:
            return (json.load(f).get("require") or {}).get("php")
    except (OSError, ValueError):
        return None


GENERIC_DIRS = {"portal", "app", "src", "web", "backend", "api", "server", "www", "public_html", "laravel", "site"}


def slugify(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "site"


def site_name(path):
    """Nama situs dari folder; folder generik (mis. portal/) diberi nama induknya."""
    base = os.path.basename(path.rstrip("/"))
    if base.lower() in GENERIC_DIRS:
        base = os.path.basename(os.path.dirname(path.rstrip("/"))) + "-" + base
    return slugify(base)


def herd_suggest(q):
    """Project PHP di folder kode yang belum dilayani Herd (belum di-link / di-park)."""
    info = herd_info()
    served = {os.path.realpath(s["path"]) for s in info.get("sites", [])}
    parked = [os.path.realpath(p) for p in info.get("paths", [])]
    found, deadline = [], time.time() + 4
    for root in (os.path.join(HOME, r) for r in SCAN_ROOTS):
        stack = [(root, 0)]
        while stack and time.time() < deadline:
            path, depth = stack.pop()
            try:
                entries = [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            kind = project_type(path) if depth else None
            if kind:
                real = os.path.realpath(path)
                if real not in served and os.path.dirname(real) not in parked:
                    found.append({"path": path, "name": site_name(path), "type": kind,
                                  "php": php_constraint(path), "modified": os.path.getmtime(path)})
                continue  # jangan masuk ke dalam project
            if depth < 3:
                stack += [(e.path, depth + 1) for e in entries
                          if e.name not in SCAN_SKIP and not e.name.startswith(".")]
    found.sort(key=lambda p: -p["modified"])
    return {"projects": found[:40]}


def pick_folder(body):
    """Dialog 'Pilih folder' bawaan macOS (Finder). Menunggu sampai user memilih."""
    start = os.path.realpath(os.path.expanduser(str(body.get("start") or "~/Documents")))
    if not os.path.isdir(start):
        start = HOME
    script = ('on run argv\n'
              '  activate\n'
              '  set f to choose folder with prompt (item 1 of argv) default location (POSIX file (item 2 of argv))\n'
              '  return POSIX path of f\n'
              'end run')
    prompt = str(body.get("prompt") or "Pilih folder project")[:120]
    try:
        code, out, err = run(["osascript", "-e", script, prompt, start], timeout=600)
    except subprocess.TimeoutExpired:
        raise ApiError("Диалог закрыт: слишком долгое ожидание", HTTPStatus.REQUEST_TIMEOUT, code="srv.dialog_timeout")
    if code != 0:
        if "-128" in err:  # user menekan Cancel
            return {"cancelled": True}
        raise ApiError(err.strip() or "Не удалось открыть диалог", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.dialog_open_failed")
    path = out.strip().rstrip("/")
    return {"path": path, "name": site_name(path), "type": project_type(path),
            "php": php_constraint(path)}


LARAVEL_PHP_MIN = {13: "8.3", 12: "8.2", 11: "8.2", 10: "8.1"}


EDITORS = {"vscode": ("Visual Studio Code", "Visual Studio Code"), "cursor": ("Cursor", "Cursor"),
           "phpstorm": ("PhpStorm", "PhpStorm"), "zed": ("Zed", "Zed"), "windsurf": ("Windsurf", "Windsurf"),
           "sublime": ("Sublime Text", "Sublime Text")}


_laravel_versions = {"t": 0, "v": None}


def installed_editors():
    return [{"id": k, "name": n} for k, (n, app) in EDITORS.items() if os.path.exists(f"/Applications/{app}.app")]


def laravel_versions():
    """Major version laravel/laravel dari Packagist (cache 1 hari), fallback statis."""
    if _laravel_versions["v"] and time.time() - _laravel_versions["t"] < 86400:
        return _laravel_versions["v"]
    majors = []
    try:
        _, out, _ = run(["curl", "-fsSL", "--max-time", "8", "https://repo.packagist.org/p2/laravel/laravel.json"], timeout=12)
        tags = [v["version"] for v in json.loads(out)["packages"]["laravel/laravel"]]
        majors = sorted({int(m[1]) for t in tags if (m := re.match(r"v?(\d+)\.\d+\.\d+$", t))}, reverse=True)
    except (ValueError, KeyError, subprocess.TimeoutExpired):
        pass
    majors = [m for m in majors if m >= 10][:4] or [13, 12, 11, 10]
    _laravel_versions.update(t=time.time(), v=majors)
    return majors


def herd_new_options(q):
    versions = herd_versions()
    installed = [v["version"] for v in versions if v["installed"]]
    return {
        "laravel": [{"major": m, "latest": i == 0, "php_min": LARAVEL_PHP_MIN.get(m, "8.2")}
                    for i, m in enumerate(laravel_versions())],
        "php_installed": installed, "global_php": next((v["version"] for v in versions if v["global"]), None),
        "editors": [{"id": k, "name": n} for k, (n, app) in EDITORS.items() if os.path.exists(f"/Applications/{app}.app")],
        "default_location": os.path.join(HOME, "Herd"), "tld": herd("tld")[1].strip() or "test",
        "mysql_running": any(s["name"].startswith(("mysql", "mariadb")) and s["running"] for s in brewsvc.list_services()),
        "postgres_running": any(s["name"].startswith("postgresql") and s["running"] for s in brewsvc.list_services()),
    }


def php_env(version):
    """ENV dengan `php` versi tertentu (Herd) paling depan di PATH, plus composer/laravel Herd."""
    shim = os.path.join(DATA_DIR, "php-shims", version)
    os.makedirs(shim, exist_ok=True)
    link = os.path.join(shim, "php")
    if os.path.islink(link):
        os.unlink(link)
    os.symlink(os.path.join(HERD_BIN, "php" + version.replace(".", "")), link)
    return dict(ENV, PATH=f"{shim}:{HERD_BIN}:" + ENV["PATH"]), link


def set_env_values(path, values):
    """Ubah/tambah KEY=VALUE di file .env."""
    with open(path) as f:
        text = f.read()
    for key, value in values.items():
        line = f"{key}={value}"
        text, n = re.subn(rf"^#?\s*{key}=.*$", line, text, count=1, flags=re.M)
        if not n:
            text = text.rstrip("\n") + f"\n{line}\n"
    with open(path, "w") as f:
        f.write(text)


def herd_new(body):
    name = str(body.get("name", "")).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
        raise ApiError("Имя проекта может содержать только строчные буквы, цифры, - и _ (пример: my-shop)", code="srv.project_name_invalid")
    location = os.path.realpath(os.path.expanduser(str(body.get("location") or "~/Herd")))
    if not os.path.isdir(location):
        raise ApiError(f"Папка расположения не найдена: {location}", code="srv.location_not_found", location=location)
    path = os.path.join(location, name)
    if os.path.exists(path):
        raise ApiError(f"Папка {path} уже существует", code="srv.folder_exists", path=path)
    major = int(body.get("laravel") or 0)
    majors = laravel_versions()
    if major not in majors:
        raise ApiError("Недопустимая версия Laravel", code="srv.laravel_invalid")
    latest = major == majors[0]
    php = str(body.get("php") or "")
    versions = herd_versions()
    installed = [v["version"] for v in versions if v["installed"]]
    if php not in installed:
        raise ApiError("Недопустимая версия PHP в Herd", code="srv.herd_php_invalid")
    need = LARAVEL_PHP_MIN.get(major, "8.2")
    if tuple(map(int, php.split("."))) < tuple(map(int, need.split("."))):
        raise ApiError(f"Для Laravel {major} нужен PHP {need} или новее", code="srv.laravel_needs_php", major=major, need=need)
    db = body.get("database") or "sqlite"
    if db not in ("sqlite", "mysql", "mariadb", "pgsql"):
        raise ApiError("Недопустимая база данных", code="srv.database_invalid")
    env, php_bin = php_env(php)
    steps = []

    if latest:
        cmd = [php_bin, os.path.join(HERD_BIN, "laravel"), "new", name, "--no-interaction", f"--database={db}"]
        kit = body.get("starter") or "none"
        if kit in ("react", "vue", "svelte", "livewire"):
            cmd.append(f"--{kit}")
            auth = body.get("auth") or "laravel"
            if auth == "workos":
                cmd.append("--workos")
            elif auth == "none":
                cmd.append("--no-authentication")
            if body.get("teams"):
                cmd.append("--teams")
            if kit == "livewire" and body.get("livewire_class"):
                cmd.append("--livewire-class-components")
        cmd.append("--phpunit" if body.get("testing") == "phpunit" else "--pest")
        pm = body.get("js") or "npm"
        cmd.append({"npm": "--npm", "pnpm": "--pnpm", "bun": "--bun", "yarn": "--yarn"}.get(pm, "--no-node"))
        if body.get("git"):
            cmd.append("--git")
        cmd.append("--boost" if body.get("boost") else "--no-boost")
        steps.append((f"laravel new {name} (Laravel {major})", cmd, {"cwd": location, "env": env}))
    else:
        steps.append((f"composer create-project laravel/laravel:^{major}.0",
                      [php_bin, os.path.join(HERD_BIN, "composer"), "create-project", f"laravel/laravel:^{major}.0",
                       name, "--no-interaction", "--prefer-dist"], {"cwd": location, "env": env}))
        if db != "sqlite":
            steps.append(("Настройка базы данных в .env", lambda log: set_env_values(os.path.join(path, ".env"), {
                "DB_CONNECTION": db, "DB_HOST": "127.0.0.1", "DB_PORT": "5432" if db == "pgsql" else "3306",
                "DB_DATABASE": name.replace("-", "_"), "DB_USERNAME": "postgres" if db == "pgsql" else "root",
                "DB_PASSWORD": ""}), {}))
        if body.get("git"):
            steps += [("git init", ["git", "init", "-b", "main"], {"cwd": path, "optional": True}),
                      ("git add", ["git", "add", "-A"], {"cwd": path, "optional": True}),
                      ("первый коммит", ["git", "commit", "-qm", "Initial commit"], {"cwd": path, "optional": True})]

    if db != "sqlite" and body.get("create_db"):
        dbname = name.replace("-", "_")
        if db in ("mysql", "mariadb"):
            mysql = shutil.which("mysql", path=f"{BREW_PREFIX}/bin:{BREW_PREFIX}/opt/mysql-client/bin:" + ENV["PATH"])
            if mysql:
                steps.append((f"Создание базы данных MySQL `{dbname}`",
                              [mysql, "-uroot", "-h127.0.0.1", "-e", f"CREATE DATABASE IF NOT EXISTS `{dbname}`"],
                              {"optional": True}))
        else:
            createdb = shutil.which("createdb", path=f"{BREW_PREFIX}/bin:" + ENV["PATH"])
            if createdb:
                steps.append((f"Создание базы данных PostgreSQL {dbname}", [createdb, dbname], {"optional": True}))
        if body.get("migrate"):
            steps.append(("php artisan migrate", [php_bin, "artisan", "migrate", "--force"],
                          {"cwd": path, "env": env, "optional": True}))

    # layani lewat Herd: folder di dalam parked path otomatis jadi situs; selain itu di-link
    parked = [os.path.realpath(p) for p in loads_or(herd("paths")[1], [])]
    link = [HERD, "link", name, "--no-ansi", "--no-interaction", f"--isolate={php}"]
    if location in parked:
        link = [HERD, "isolate", php, f"--site={name}", "--no-ansi", "--no-interaction"]
    steps.append((f"Регистрация в Herd ({name}.test, PHP {php})", link, {"cwd": path}))
    if body.get("secure"):
        steps.append(("Включение HTTPS", [HERD, "secure", name, "--no-ansi", "--no-interaction"], {"optional": True}))
    scheme = "https" if body.get("secure") else "http"
    steps.append(("Установка APP_URL", lambda log: set_env_values(os.path.join(path, ".env"), {"APP_URL": f"{scheme}://{name}.test"}),
                  {"optional": True}))
    editor = body.get("editor")
    if editor in EDITORS:
        steps.append((f"Открытие в {EDITORS[editor][0]}", ["open", "-a", EDITORS[editor][1], path], {"optional": True}))
    if body.get("open_browser"):
        steps.append(("Открытие в браузере", ["open", f"{scheme}://{name}.test"], {"optional": True}))
    return {"job": start_steps(f"Новое приложение Laravel: {name}", steps, "herd"), "path": path}


def herd_logs(q):
    name = q.get("file", "")
    if name not in ("nginx-error.log", "php-fpm.log"):
        raise ApiError("Неизвестный журнал", code="srv.log_unknown")
    return {"log": tail(os.path.join(HERD_LOG_DIR, name), 300), "path": os.path.join(HERD_LOG_DIR, name)}
