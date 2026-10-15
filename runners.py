"""CI-раннеры (Фаза 5): провайдеры, реестр источников и токены. Шаг 1 — БЕЗ регистрации и запуска.

Провайдер = адаптер к конкретной системе CI с одним интерфейсом (`Provider`): найти последний официальный релиз раннера
(с контрольной суммой) и установить его файлы. Сейчас: `github` (actions/runner) и `gitea` (gitea/runner, он же act_runner;
подходит и для Forgejo). Новая система CI = новый класс-адаптер, остальной код не меняется.

Источник (`sources.json`) = «где живут репозитории»: провайдер + URL (ЛЮБОЙ инстанс, в т.ч. свой Gitea или GitHub Enterprise) +
область (репозиторий / организация / весь инстанс). Токен регистрации хранится в отдельном файле 0600 и НЕ возвращается ни в
одном ответе API, ни в аудите, ни в выводе job. Раннер здесь не регистрируется и не запускается: регистрация даёт внешнему
серверу право присылать на машину код из workflow — это L3 и отдельный шаг (в одноразовой ВМ).
Только стандартная библиотека; скачивание — urllib, только с адресов, которые разрешает адаптер.
"""
import hashlib
import json
import lzma
import os
import re
import secrets
import shutil
import stat
import tarfile
import tempfile
import threading
import time
import urllib.request
from http import HTTPStatus
from urllib.parse import urlsplit

import audit
import core
from core import ApiError, start_steps

RUNNERS_DIR = os.path.join(core.DATA_DIR, "runners")
SOURCES_FILE = os.path.join(core.DATA_DIR, "runner-sources.json")
TOKEN_DIR = os.path.join(core.DATA_DIR, "runner-tokens")
VER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
NAME_RE = re.compile(r"^\w[\w ._-]{0,39}$")
PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}(/[A-Za-z0-9][A-Za-z0-9._-]{0,99})?$")
LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
URL_PATH_RE = re.compile(r"^(/[A-Za-z0-9._~-]+)+$")
MAX_UNPACKED = 1024 * 1024 * 1024
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.=-]{8,300}$")
SCOPES = ("repo", "org", "instance")
MAX_SOURCES = 30
MAX_DOWNLOAD = 400 * 1024 * 1024
UA = {"User-Agent": "service-admin", "Accept": "application/json"}
_LOCK = threading.Lock()


def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:  # noqa: S310 - адрес задаёт адаптер
        return json.load(r)


def _get_text(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:  # noqa: S310
        return r.read(4096).decode("utf-8", "replace")


# ---------------------------------------------------------------- провайдеры

class Provider:
    id = "base"
    title = ""
    scopes = SCOPES
    binary = ""   # имя исполняемого файла после установки (проверка «установлено»)

    def release(self):
        """→ {"version", "url", "sha256", "kind": "tar"|"xz"}; бросает ApiError(runner.no_release)."""
        raise NotImplementedError

    def allowed_url(self, url):
        return False

    def installed(self):
        out = []
        base = os.path.join(RUNNERS_DIR, self.id)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            names = []
        for n in names:
            p = os.path.join(base, n)
            if VER_RE.match(n) and os.access(os.path.join(p, self.binary), os.X_OK):
                out.append({"version": n, "path": p})
        return out


def _plat():
    """Платформа ГОСТЯ = платформа хоста (гость той же ОС/архитектуры): (суффикс GitHub-раннера, суффикс gitea-runner)."""
    import platform
    import sys
    mach = platform.machine().lower()
    if sys.platform == "darwin":
        return "osx-arm64", "darwin-arm64"
    if mach in ("aarch64", "arm64"):
        return "linux-arm64", "linux-arm64"
    return "linux-x64", "linux-amd64"


class GithubProvider(Provider):
    id = "github"
    title = "GitHub Actions runner"
    binary = "run.sh"
    API = "https://api.github.com/repos/actions/runner/releases/latest"
    URL_RE = re.compile(r"^https://github\.com/actions/runner/releases/download/v[0-9.]+/actions-runner-(osx-arm64|linux-x64|linux-arm64)-[0-9.]+\.tar\.gz$")

    def allowed_url(self, url):
        return bool(self.URL_RE.match(url))

    def release(self):
        rel = _get_json(self.API)
        ver = str(rel.get("tag_name", "")).lstrip("v")
        for a in rel.get("assets", []):
            digest = str(a.get("digest") or "")
            if (a.get("name") == f"actions-runner-{_plat()[0]}-{ver}.tar.gz" and VER_RE.match(ver) and digest.startswith("sha256:")
                    and self.allowed_url(a.get("browser_download_url", ""))):
                return {"version": ver, "url": a["browser_download_url"], "sha256": digest[7:], "kind": "tar"}
        raise ApiError("Official runner release not found or has no checksum", HTTPStatus.BAD_GATEWAY, code="runner.no_release")


class GiteaProvider(Provider):
    id = "gitea"
    title = "Gitea / Forgejo Actions runner"
    binary = "gitea-runner"
    API = "https://gitea.com/api/v1/repos/gitea/runner/releases/latest"
    URL_RE = re.compile(r"^https://gitea\.com/gitea/runner/releases/download/v[0-9.]+/gitea-runner-[0-9.]+-(darwin-arm64|linux-amd64|linux-arm64)\.xz(\.sha256)?$")

    def allowed_url(self, url):
        return bool(self.URL_RE.match(url))

    def release(self):
        rel = _get_json(self.API)
        ver = str(rel.get("tag_name", "")).lstrip("v")
        if not VER_RE.match(ver) or rel.get("prerelease"):
            raise ApiError("Official runner release not found or has no checksum", HTTPStatus.BAD_GATEWAY, code="runner.no_release")
        urls = {a.get("name"): a.get("browser_download_url", "") for a in rel.get("assets", [])}
        name = f"gitea-runner-{ver}-{_plat()[1]}.xz"
        url, sum_url = urls.get(name, ""), urls.get(name + ".sha256", "")
        if not (self.allowed_url(url) and self.allowed_url(sum_url)):
            raise ApiError("Official runner release not found or has no checksum", HTTPStatus.BAD_GATEWAY, code="runner.no_release")
        m = re.match(r"^([0-9a-f]{64})\s", _get_text(sum_url))
        if not m:
            raise ApiError("Official runner release not found or has no checksum", HTTPStatus.BAD_GATEWAY, code="runner.no_release")
        return {"version": ver, "url": url, "sha256": m.group(1), "kind": "xz"}


PROVIDERS = {p.id: p for p in (GithubProvider(), GiteaProvider())}


def provider(pid):
    p = PROVIDERS.get(pid)
    if not p:
        raise ApiError("Unknown CI provider", HTTPStatus.BAD_REQUEST, code="runner.provider")
    return p


# ---------------------------------------------------------------- установка файлов

def _download(prov, rel, dest_file, log):
    if not prov.allowed_url(rel["url"]):
        raise RuntimeError("download address is not allowed for this provider")
    log(f"downloading {rel['url']}")
    h, total = hashlib.sha256(), 0
    with urllib.request.urlopen(urllib.request.Request(rel["url"], headers=UA), timeout=60) as r, open(dest_file, "wb") as f:  # noqa: S310
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD:
                raise RuntimeError("download is larger than allowed")
            h.update(chunk)
            f.write(chunk)
    if h.hexdigest() != rel["sha256"]:
        raise RuntimeError("checksum mismatch: the download was not installed")
    log("checksum OK")


def _unpack(prov, rel, arc, out):
    if rel["kind"] == "xz":
        written = 0
        with lzma.open(arc) as src, open(os.path.join(out, prov.binary), "wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UNPACKED:
                    raise RuntimeError("unpacked file is larger than allowed")
                dst.write(chunk)
        os.chmod(os.path.join(out, prov.binary), 0o755)
        return
    root = os.path.realpath(out)
    with tarfile.open(arc) as tf:
        for m in tf.getmembers():  # без выхода за пределы папки и без устройств
            target = os.path.realpath(os.path.join(out, m.name))
            if target != root and not target.startswith(root + os.sep):
                raise RuntimeError(f"unsafe path in archive: {m.name}")
            if m.isdev():
                raise RuntimeError(f"unsafe member in archive: {m.name}")
            if m.issym() or m.islnk():
                link = os.path.realpath(os.path.join(os.path.dirname(target), m.linkname)) if m.issym() else os.path.realpath(os.path.join(out, m.linkname))
                if link != root and not link.startswith(root + os.sep):
                    raise RuntimeError(f"unsafe link in archive: {m.name}")
        # члены проверены выше; filter="data" (Python ≥3.12 и обновлённые 3.9–3.11) — запасная защита от setuid/режимов
        if hasattr(tarfile, "data_filter"):
            tf.extractall(out, filter="data")
        else:
            tf.extractall(out)  # noqa: S202


def _install(pid):
    def step(log):
        prov = provider(pid)
        rel = prov.release()
        dest = os.path.join(RUNNERS_DIR, prov.id, rel["version"])
        if os.access(os.path.join(dest, prov.binary), os.X_OK):
            log(f"{prov.title} {rel['version']} is already installed")
            return
        os.makedirs(os.path.join(RUNNERS_DIR, prov.id), mode=0o700, exist_ok=True)
        if os.path.exists(dest):  # остаток прерванной/испорченной установки: без бинарника он только мешает
            shutil.rmtree(dest, ignore_errors=True)
        tmp = tempfile.mkdtemp(prefix="dl.", dir=os.path.join(RUNNERS_DIR, prov.id))
        try:
            arc, out = os.path.join(tmp, "archive"), os.path.join(tmp, "x")
            os.mkdir(out)
            _download(prov, rel, arc, log)
            _unpack(prov, rel, arc, out)
            os.replace(out, dest)
            log(f"installed to {dest} (not registered, not started)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return step


def install(body):
    """POST /api/runners/install {provider} → {"job": id}."""
    prov = provider((body or {}).get("provider"))
    if os.uname().machine.lower() not in (("arm64",) if os.uname().sysname == "Darwin" else ("arm64", "aarch64", "x86_64", "amd64")):
        raise ApiError("Only Apple Silicon (macOS) or arm64/x86_64 (Linux) hosts are supported", HTTPStatus.CONFLICT, code="runner.arch")
    if shutil.disk_usage("/").free < 5e9:
        raise ApiError("At least 5 GB of free disk space is needed", HTTPStatus.CONFLICT, code="runner.disk")
    return {"job": start_steps(f"Install {prov.title} (files only)", [("download, verify, unpack", _install(prov.id), {})], "runner")}


# ---------------------------------------------------------------- реестр источников

def _load():
    try:
        with open(SOURCES_FILE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("sources"), list) else {"sources": []}
    except (OSError, ValueError):
        return {"sources": []}


def _save(d):
    os.makedirs(core.DATA_DIR, mode=0o700, exist_ok=True)
    tmp = SOURCES_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SOURCES_FILE)


def normalize_url(url):
    """http(s)://хост[:порт][/префикс] без учётных данных, запроса и фрагмента; завершающий / убирается."""
    if not isinstance(url, str) or len(url) > 200:
        raise ApiError("Invalid server address", code="runner.bad_url")
    u = urlsplit(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ApiError("Address must look like https://git.example.com (no login, query or fragment)", code="runner.bad_url")
    try:
        port = u.port
    except ValueError:
        raise ApiError("Invalid server address", code="runner.bad_url") from None
    host = u.hostname.lower()
    is_v6 = ":" in host
    if not (is_v6 and re.match(r"^[0-9a-f:]+$", host)) and not all(LABEL_RE.match(x) for x in host.split(".")):
        raise ApiError("Invalid server address", code="runner.bad_url")
    path = u.path.rstrip("/")
    if path and (not URL_PATH_RE.match(path) or any(seg in ("..", ".") for seg in path.split("/"))):
        raise ApiError("Invalid server address", code="runner.bad_url")
    if port is not None and not 1 <= port <= 65535:
        raise ApiError("Invalid server address", code="runner.bad_url")
    netloc = f"[{host}]" if is_v6 else host
    if port is not None:
        netloc += f":{port}"
    return f"{u.scheme}://{netloc}{path}"


def _local_host(host):
    """Адрес допустим для http: loopback, частные сети, link-local, имена без точки или .local/.lan/.home.arpa."""
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return "." not in host or host.endswith((".local", ".lan", ".home.arpa", ".internal"))


def _public(s):
    out = {k: s.get(k) for k in ("id", "name", "provider", "url", "scope", "path", "created")}
    out["auth"] = s.get("auth", "registration")
    out["has_token"] = os.path.isfile(os.path.join(TOKEN_DIR, s["id"] + ".token"))
    return out


def _write_token(source_id, token):
    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    path = os.path.join(TOKEN_DIR, source_id + ".token")
    fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    os.replace(path + ".new", path)


def read_token(source_id):
    """Только для внутреннего использования следующими шагами (регистрация); в API и аудит не попадает."""
    try:
        with open(os.path.join(TOKEN_DIR, source_id + ".token")) as f:
            return f.read().strip()
    except OSError:
        return None


def add_source(body):
    """POST {name, provider, url, scope, path?, token?} — токен (если дан) сохраняется в файл 0600 и дальше не возвращается."""
    prov = provider(body.get("provider"))
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not NAME_RE.match(name):
        raise ApiError("Name: 1-40 characters (letters, digits, space, . _ -)", code="runner.bad_name")
    scope = body.get("scope")
    if scope not in prov.scopes:
        raise ApiError("Unknown scope for this provider", code="runner.bad_scope")
    path = body.get("path") or ""
    if not isinstance(path, str):
        raise ApiError("Path must be owner/repo for a repository, or the organization name", code="runner.bad_path")
    path = path.strip()
    need = {"repo": 2, "org": 1, "instance": 0}[scope]
    if (scope == "instance" and path) or (scope != "instance" and (not PATH_RE.match(path) or path.count("/") + 1 != need)):
        raise ApiError("Path must be owner/repo for a repository, or the organization name", code="runner.bad_path")
    url = normalize_url(body.get("url"))
    auth = body.get("auth", "api")
    if auth not in ("api", "registration"):
        raise ApiError("auth must be 'api' or 'registration'", code="runner.bad_auth")
    if auth == "api" and urlsplit(url).scheme == "http" and not _local_host(urlsplit(url).hostname):
        raise ApiError("An access token must not be sent over plain http to a non-local address; use https", code="runner.insecure_url")
    token = body.get("token")
    if token not in (None, "") and (not isinstance(token, str) or not TOKEN_RE.match(token)):
        raise ApiError("The token has an unexpected format", code="runner.bad_token")
    with _LOCK:
        d = _load()
        if len(d["sources"]) >= MAX_SOURCES:
            raise ApiError("Too many sources", HTTPStatus.CONFLICT, code="runner.too_many")
        if any(s["name"].lower() == name.lower() for s in d["sources"]):
            raise ApiError("A source with this name already exists", HTTPStatus.CONFLICT, code="runner.name_exists")
        s = {"id": "s" + secrets.token_hex(3), "name": name, "provider": prov.id, "url": url, "scope": scope, "path": path, "auth": auth, "created": time.time()}
        d["sources"].append(s)
        _save(d)
        if token:
            try:
                _write_token(s["id"], token)
            except OSError:
                d["sources"].remove(s)
                _save(d)
                raise ApiError("Could not store the token", HTTPStatus.INTERNAL_SERVER_ERROR, code="runner.token_write") from None
    audit.record("runner:source_add", {"id": s["id"], "name": name, "provider": prov.id, "url": url, "scope": scope, "path": path,
                                       "auth": auth, "token": bool(token)}, "ok")
    return {"source": _public(s)}


def remove_source(body):
    with _LOCK:
        d = _load()
        s = next((x for x in d["sources"] if x["id"] == body.get("id")), None)
        if not s:
            raise ApiError("Source not found", HTTPStatus.NOT_FOUND, code="runner.source_missing")
        d["sources"].remove(s)
        _save(d)
    try:
        os.unlink(os.path.join(TOKEN_DIR, s["id"] + ".token"))
    except OSError:
        pass
    audit.record("runner:source_remove", {"id": s["id"], "name": s["name"]}, "ok")
    return {"removed": s["id"]}


def status(q=None):
    """GET /api/runners — провайдеры (что установлено) и источники (без токенов)."""
    provs = [{"id": p.id, "title": p.title, "scopes": list(p.scopes), "installed": p.installed()} for p in PROVIDERS.values()]
    return {"providers": provs, "sources": [_public(s) for s in _load()["sources"]], "arch_supported": os.uname().machine == "arm64"}


def get_source(source_id):
    s = next((x for x in _load()["sources"] if x["id"] == source_id), None)
    if not s:
        raise ApiError("Source not found", HTTPStatus.NOT_FOUND, code="runner.source_missing")
    return s


def test_source(body):
    """POST {id} — проверить подключение: токен принят, можно получить регистрационный токен (сам он не возвращается)."""
    import ci_api
    s = get_source(body.get("id"))
    tok = read_token(s["id"])
    if not tok:
        raise ApiError("The source has no stored token", HTTPStatus.CONFLICT, code="runner.no_token")
    if s.get("auth", "registration") != "api":
        return {"ok": True, "auth": "registration", "note": "registration token stored; it cannot be tested without registering"}
    c = ci_api.client(s, tok)
    try:
        user = c.whoami()
        c.registration_token()
        n = len(c.list_runners())
    except ci_api.CIError as e:
        raise ci_api.friendly(e) from None
    audit.record("runner:source_test", {"id": s["id"], "name": s["name"]}, "ok")
    return {"ok": True, "auth": "api", "user": user, "runners": n}
