"""Editor file konfigurasi: shell (zsh/bash), /etc/hosts, /etc/resolver, SSH,
Git, php.ini, tmux, vim, package manager, dan .env project.

Hanya file dari registry di bawah yang boleh dibaca/ditulis (tidak ada path
bebas dari browser). File milik root (/etc/...) ditulis lewat dialog password
admin macOS (osascript ... with administrator privileges)."""
import glob
import ipaddress
import json
import os
import re
import shlex
import shutil
import tempfile
import time
from http import HTTPStatus

try:  # tomllib ada sejak Python 3.11; jalur utama panel memakai Python bawaan (3.12+)
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # cadangan untuk interpreter lama
    except ModuleNotFoundError:
        tomllib = None  # validasi TOML dinonaktifkan dengan pesan jujur, bukan crash

from core import BREW_PREFIX, DATA_DIR, HOME, ApiError, output, run

BACKUP_DIR = os.path.join(DATA_DIR, "backups", "files")
HERD_PHP = os.path.join(HOME, "Library/Application Support/Herd/config/php")
SCAN_ROOTS = ["Documents", "Projects", "Code", "Sites", "Developer", "Herd", "Desktop"]
SCAN_SKIP = {"node_modules", "vendor", ".git", "storage", "Library", ".Trash", "public", "resources", "dist", "build"}


def h(p):
    return os.path.join(HOME, p)


# (id, group, label, path, validator, opsi)
STATIC = [
    ("zshrc", "Shell", ".zshrc", h(".zshrc"), "zsh", {}),
    ("zprofile", "Shell", ".zprofile", h(".zprofile"), "zsh", {}),
    ("zshenv", "Shell", ".zshenv", h(".zshenv"), "zsh", {}),
    ("zlogin", "Shell", ".zlogin", h(".zlogin"), "zsh", {"optional": True}),
    ("bashrc", "Shell", ".bashrc", h(".bashrc"), "bash", {"optional": True}),
    ("bash_profile", "Shell", ".bash_profile", h(".bash_profile"), "bash", {"optional": True}),
    ("inputrc", "Shell", ".inputrc", h(".inputrc"), None, {"optional": True}),
    ("hosts", "Sistem", "/etc/hosts", "/etc/hosts", "hosts", {"admin": True}),
    ("ssh_config", "SSH", "~/.ssh/config", h(".ssh/config"), "ssh", {}),
    ("gitconfig", "Git", ".gitconfig", h(".gitconfig"), "git", {}),
    ("git_ignore", "Git", "~/.config/git/ignore (global)", h(".config/git/ignore"), None, {"optional": True}),
    ("gitignore_global", "Git", ".gitignore_global", h(".gitignore_global"), None, {"optional": True}),
    ("gitattributes", "Git", ".gitattributes", h(".gitattributes"), None, {"optional": True}),
    ("tmux", "Editor & terminal", ".tmux.conf", h(".tmux.conf"), None, {"optional": True}),
    ("vimrc", "Editor & terminal", ".vimrc", h(".vimrc"), None, {"optional": True}),
    ("nvim_lua", "Editor & terminal", "nvim/init.lua", h(".config/nvim/init.lua"), None, {"optional": True}),
    ("editorconfig", "Editor & terminal", ".editorconfig", h(".editorconfig"), None, {"optional": True}),
    ("npmrc", "Package manager", ".npmrc", h(".npmrc"), None, {"optional": True}),
    ("yarnrc", "Package manager", ".yarnrc.yml", h(".yarnrc.yml"), None, {"optional": True}),
    ("composer", "Package manager", "composer/config.json", h(".composer/config.json"), "json", {"optional": True}),
    ("pip", "Package manager", "pip/pip.conf", h(".config/pip/pip.conf"), None, {"optional": True}),
    ("cargo", "Package manager", "cargo/config.toml", h(".cargo/config.toml"), "toml", {"optional": True}),
    ("gemrc", "Package manager", ".gemrc", h(".gemrc"), None, {"optional": True}),
    ("curlrc", "Package manager", ".curlrc", h(".curlrc"), None, {"optional": True}),
    ("mycnf", "Database", ".my.cnf (klien MySQL)", h(".my.cnf"), None, {"optional": True, "sensitive": True}),
]

_env_cache = {"t": 0, "data": []}


def env_files():
    """.env di folder project (maks. 3 level di bawah folder kode umum)."""
    if time.time() - _env_cache["t"] < 60:
        return _env_cache["data"]
    found, deadline = [], time.time() + 4
    for root in (h(r) for r in SCAN_ROOTS):
        stack = [(root, 0)]
        while stack and time.time() < deadline:
            path, depth = stack.pop()
            env = os.path.join(path, ".env")
            if depth and os.path.isfile(env):
                found.append(env)
                continue  # jangan masuk lebih dalam ke project
            if depth >= 3:
                continue
            try:
                stack += [(e.path, depth + 1) for e in os.scandir(path)
                          if e.is_dir(follow_symlinks=False) and e.name not in SCAN_SKIP and not e.name.startswith(".")]
            except OSError:
                pass
    found.sort(key=lambda p: -os.path.getmtime(p))
    _env_cache.update(t=time.time(), data=found)
    return found


def registry():
    items = []
    for fid, group, label, path, validator, opt in STATIC:
        exists = os.path.exists(path)
        if opt.get("optional") and not exists and fid not in ("gitignore_global", "tmux", "vimrc", "editorconfig"):
            # tampilkan file opsional yang belum ada hanya untuk yang umum dibuat
            continue
        items.append({"id": fid, "group": group, "label": label, "path": path, "validator": validator,
                      "exists": exists, "admin": bool(opt.get("admin")), "sensitive": bool(opt.get("sensitive"))})
    for f in sorted(glob.glob("/etc/resolver/*")):
        items.append({"id": f"resolver:{os.path.basename(f)}", "group": "Sistem", "label": f"/etc/resolver/{os.path.basename(f)}",
                      "path": f, "validator": "resolver", "exists": True, "admin": True, "sensitive": False})
    php_inis = [(f"Homebrew PHP {os.path.basename(os.path.dirname(p))}", p) for p in sorted(glob.glob(f"{BREW_PREFIX}/etc/php/*/php.ini"))]
    php_inis += [(f"Herd PHP {v[0]}.{v[1:]}", p) for p in sorted(glob.glob(f"{HERD_PHP}/*/php.ini"))
                 for v in [os.path.basename(os.path.dirname(p))]]
    for label, p in php_inis:
        items.append({"id": f"phpini:{p}", "group": "PHP", "label": f"php.ini — {label}", "path": p, "validator": "phpini",
                      "exists": True, "admin": False, "sensitive": False})
    generic = {"backend", "frontend", "worker", "portal", "app", "api", "server", "web", "src"}
    for p in env_files():
        rel = p.replace(HOME + "/", "~/")
        proj = os.path.dirname(p)
        label = os.path.basename(proj)
        if label.lower() in generic:
            label = f"{os.path.basename(os.path.dirname(proj))}/{label}"
        items.append({"id": f"env:{p}", "group": ".env project", "label": label,
                      "hint": rel, "path": p, "validator": "dotenv", "exists": True, "admin": False, "sensitive": True})
    return items


def find(fid):
    item = next((i for i in registry() if i["id"] == fid), None)
    if not item:
        raise ApiError("Неизвестный файл", HTTPStatus.NOT_FOUND, code="files.unknown_file")
    return item


def list_files(q):
    return {"files": registry()}


# ---------------------------------------------------------------- validator

def check_hosts(text):
    errors = []
    for no, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        try:
            ipaddress.ip_address(parts[0])
        except ValueError:
            errors.append(f"строка {no}: '{parts[0]}' не является IP-адресом")
            continue
        if len(parts) < 2:
            errors.append(f"строка {no}: не указано имя хоста")
        for host in parts[1:]:
            if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                errors.append(f"строка {no}: недопустимое имя хоста '{host}'")
    return errors


def check_resolver(text):
    keys = {"nameserver", "port", "domain", "search", "search_order", "timeout", "options", "sortlist"}
    errors = []
    for no, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(" ")
        if key not in keys:
            errors.append(f"строка {no}: '{key}' не является опцией resolver ({', '.join(sorted(keys))})")
        elif key == "nameserver":
            try:
                ipaddress.ip_address(value.strip())
            except ValueError:
                errors.append(f"строка {no}: nameserver должен быть IP-адресом")
    return errors


def check_dotenv(text):
    errors = []
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"(export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=(.*)$", s)
        if not m:
            errors.append(f"строка {no}: формат должен быть KEY=VALUE")
            continue
        v = m[3].strip()
        if v[:1] in "\"'" and (len(v) < 2 or v[-1] != v[0]) and "#" not in v:
            errors.append(f"строка {no}: кавычка {v[0]} не закрыта")
    return errors


def php_for_ini(path):
    if path.startswith(HERD_PHP):
        v = os.path.basename(os.path.dirname(path))
        return os.path.join(HOME, "Library/Application Support/Herd/bin", f"php{v}")
    ver = os.path.basename(os.path.dirname(path))
    for cand in (f"{BREW_PREFIX}/opt/php@{ver}/bin/php", f"{BREW_PREFIX}/opt/php/bin/php"):
        if os.path.exists(cand):
            return cand
    return None


def validate(item, text):
    """(ok, pesan). Konten divalidasi di file sementara sebelum disimpan."""
    kind = item["validator"]
    if kind == "hosts":
        errs = check_hosts(text)
    elif kind == "resolver":
        errs = check_resolver(text)
    elif kind == "dotenv":
        errs = check_dotenv(text)
    elif kind == "json":
        try:
            json.loads(text or "{}")
            errs = []
        except ValueError as e:
            errs = [f"Некорректный JSON: {e}"]
    elif kind == "toml":
        if tomllib is None:
            return True, "Проверка TOML отключена: интерпретатор старше Python 3.11. Запустите панель вшитым Python (install.sh)."
        try:
            tomllib.loads(text)
            errs = []
        except tomllib.TOMLDecodeError as e:
            errs = [f"Некорректный TOML: {e}"]
    elif kind in ("zsh", "bash", "ssh", "git", "phpini"):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as t:
            t.write(text)
        try:
            if kind in ("zsh", "bash"):
                code, out, err = run([kind, "-n", t.name], timeout=10)
                msg = err
            elif kind == "ssh":
                code, out, err = run(["ssh", "-G", "-F", t.name, "service-admin-check"], timeout=10)
                msg = err
            elif kind == "git":
                code, out, err = run(["git", "config", "--file", t.name, "--list"], timeout=10)
                msg = err
            else:
                php = php_for_ini(item["path"])
                if not php:
                    return True, "PHP для этого файла не найден, проверка пропущена."
                code, out, err = run([php, "-n", "-c", t.name, "-r", "echo 'OK';"], timeout=15)
                # hanya syntax error yang menggagalkan; "Deprecated ... on line 0" cuma peringatan
                bad = sorted({line.strip().removeprefix("OK") for line in (out + err).splitlines() if "syntax error" in line})
                code, msg = (1 if bad else 0), "\n".join(bad)
            for p in {t.name, os.path.realpath(t.name)}:
                msg = msg.replace(p, item["label"])
            errs = [] if code == 0 else [msg.strip() or f"exit {code}"]
        finally:
            os.unlink(t.name)
    else:
        return True, "Для этого типа файла нет валидатора."
    return (not errs), ("OK" if not errs else "\n".join(errs[:20]))


# ---------------------------------------------------------------- baca / simpan

def backups_of(item):
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", item["path"].strip("/"))
    if not os.path.isdir(BACKUP_DIR):
        return prefix, []
    names = sorted((f for f in os.listdir(BACKUP_DIR) if re.fullmatch(re.escape(prefix) + r"\.\d{8}-\d{6}", f)), reverse=True)
    return prefix, names


def read_file(q):
    item = find(q.get("id", ""))
    content = ""
    if item["exists"]:
        with open(item["path"], errors="replace") as f:
            content = f.read()
    _, names = backups_of(item)
    return {**item, "content": content, "backups": names,
            "writable": item["admin"] or os.access(item["path"] if item["exists"] else os.path.dirname(item["path"]) or HOME, os.W_OK)
            or not os.path.exists(os.path.dirname(item["path"]))}


def admin_write(src, dest, flush_dns):
    """Salin file sebagai root lewat dialog password admin macOS."""
    cmd = f"mkdir -p {shlex.quote(os.path.dirname(dest))} && cp {shlex.quote(src)} {shlex.quote(dest)} && chmod 644 {shlex.quote(dest)}"
    if flush_dns:
        cmd += " && dscacheutil -flushcache && killall -HUP mDNSResponder"
    script = f"do shell script {json.dumps(cmd)} with administrator privileges with prompt \"Service Admin хочет изменить {dest}\""
    code, out, err = run(["osascript", "-e", script], timeout=300)
    if code != 0:
        if "-128" in err or "User canceled" in err:
            raise ApiError("Отменено: пароль администратора не введён.", code="files.admin_cancelled")
        raise ApiError(err.strip() or "Не удалось записать от имени администратора", HTTPStatus.INTERNAL_SERVER_ERROR,
                       code=None if err.strip() else "files.admin_write_failed")


def save_file(body):
    item = find(body.get("id", ""))
    content = body.get("content")
    if not isinstance(content, str):
        raise ApiError("Недопустимое содержимое", code="files.bad_content")
    if content and not content.endswith("\n"):
        content += "\n"
    ok, msg = validate(item, content)
    if not ok and not body.get("force"):
        raise ApiError(f"Некорректно, файл НЕ сохранён:\n{msg}", HTTPStatus.UNPROCESSABLE_ENTITY,
                       code="files.invalid_not_saved", msg_detail=msg)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    prefix, _ = backups_of(item)
    backup = None
    if item["exists"]:
        backup = os.path.join(BACKUP_DIR, f"{prefix}.{time.strftime('%Y%m%d-%H%M%S')}")
        if not os.path.exists(backup):
            shutil.copy2(item["path"], backup)
        _, names = backups_of(item)
        for old in names[20:]:
            os.remove(os.path.join(BACKUP_DIR, old))
    if item["admin"]:
        with tempfile.NamedTemporaryFile("w", dir=DATA_DIR, delete=False) as t:
            t.write(content)
        try:
            admin_write(t.name, item["path"], flush_dns=True)
        finally:
            os.unlink(t.name)
    else:
        os.makedirs(os.path.dirname(item["path"]), exist_ok=True)
        mode = 0o600 if item["sensitive"] or item["id"] == "ssh_config" else None
        with open(item["path"], "w") as f:
            f.write(content)
        if mode:
            os.chmod(item["path"], mode)
    _env_cache["t"] = 0
    return {"ok": True, "backup": backup and os.path.basename(backup), "validation": msg}


def validate_file(body):
    item = find(body.get("id", ""))
    ok, msg = validate(item, body.get("content", ""))
    return {"ok": ok, "output": msg}


def read_backup(q):
    item = find(q.get("id", ""))
    _, names = backups_of(item)
    if q.get("backup") not in names:
        raise ApiError("Резервная копия не найдена", HTTPStatus.NOT_FOUND, code="files.backup_not_found")
    with open(os.path.join(BACKUP_DIR, q["backup"]), errors="replace") as f:
        return {"content": f.read()}


def create_resolver(body):
    """File baru di /etc/resolver, mis. domain 'test' -> nameserver 127.0.0.1."""
    domain = str(body.get("domain", "")).strip().lower()
    ns = str(body.get("nameserver", "127.0.0.1")).strip()
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", domain):
        raise ApiError("Недопустимое имя домена (примеры: test, local, dev.internal)", code="files.bad_domain")
    try:
        ipaddress.ip_address(ns)
    except ValueError:
        raise ApiError("nameserver должен быть IP-адресом", code="files.nameserver_not_ip")
    dest = f"/etc/resolver/{domain}"
    if os.path.exists(dest):
        raise ApiError(f"{dest} уже существует", code="files.dest_exists", dest=dest)
    with tempfile.NamedTemporaryFile("w", dir=DATA_DIR, delete=False) as t:
        t.write(f"nameserver {ns}\n")
    try:
        admin_write(t.name, dest, flush_dns=True)
    finally:
        os.unlink(t.name)
    return {"ok": True, "id": f"resolver:{domain}"}


# ---------------------------------------------------------------- SSH key

def ssh_keys(q):
    keys = []
    for pub in sorted(glob.glob(h(".ssh/*.pub"))):
        info = output(["ssh-keygen", "-lf", pub], timeout=5)  # "256 SHA256:xxx comment (ED25519)"
        m = re.match(r"(\d+)\s+(\S+)\s+(.*)\s+\((\w+)\)$", info)
        with open(pub) as f:
            key = f.read().strip()
        keys.append({"name": os.path.basename(pub)[:-4], "public": key,
                     "bits": m[1] if m else None, "fingerprint": m[2] if m else None,
                     "comment": m[3] if m else "", "type": m[4] if m else key.split()[0],
                     "has_private": os.path.exists(pub[:-4])})
    agent = output(["ssh-add", "-l"], timeout=5)
    return {"keys": keys, "agent": [] if "no identities" in agent.lower() or "could not open" in agent.lower()
            else [line for line in agent.splitlines() if line.strip()]}


def ssh_generate(body):
    name = str(body.get("name", "")).strip() or "id_ed25519"
    comment = str(body.get("comment", "")).strip()[:100]
    passphrase = str(body.get("passphrase", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise ApiError("Недопустимое имя файла ключа", code="files.bad_key_name")
    path = h(f".ssh/{name}")
    if os.path.exists(path) or os.path.exists(path + ".pub"):
        raise ApiError(f"~/.ssh/{name} уже существует — перезаписан не будет", code="files.key_exists", name=name)
    os.makedirs(h(".ssh"), mode=0o700, exist_ok=True)
    code, out, err = run(["ssh-keygen", "-t", "ed25519", "-C", comment or f"{os.getlogin()}@mac", "-f", path, "-N", passphrase], timeout=30)
    if code != 0:
        raise ApiError(err.strip() or "ssh-keygen завершился с ошибкой", HTTPStatus.INTERNAL_SERVER_ERROR,
                       code=None if err.strip() else "files.keygen_failed")
    if body.get("add_agent") and not passphrase:
        run(["ssh-add", "--apple-use-keychain", path], timeout=10)
    return {"ok": True, "name": name}


def git_identity(q):
    get = lambda k: output(["git", "config", "--global", k], timeout=5)  # noqa: E731
    return {"name": get("user.name"), "email": get("user.email"), "excludesfile": get("core.excludesfile")}
