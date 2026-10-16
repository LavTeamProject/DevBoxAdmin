"""Profil instalasi: katalog alat per skenario (AI, Flutter, iOS, backend).

Deteksi (Fase 1) hanya membaca: setiap baris menjawab "sudah ada / belum ada" beserta versinya.
Instalasi (Fase 2.4) di bagian bawah: `plan()` menyusun rencana TANPA mengubah apa pun, `install()`
menjalankannya lewat `core.start_steps` (job + log + audit) setelah konfirmasi di UI.

Katalog ini merangkum daftar alat dari project `new-macos-dev-setup`, tapi
tidak menyalin installer-nya: yang dipakai hanya daftar alatnya, dijalankan
lewat mekanisme job yang sudah ada di repo ini.
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from http import HTTPStatus
from concurrent.futures import ThreadPoolExecutor

from core import BREW_PREFIX, ENV, ApiError, clt_stub, has_clt, run, start_steps

VER_RE = re.compile(r"\d+\.\d+(?:\.\d+)*")
CACHE_TTL = 120
_cache = {"t": 0.0, "data": None}

# ---------------------------------------------------------------- katalog
# tiap item: id, pkg (nama Homebrew), type (formula|cask), butuh (wajib/tidak),
# dan cara mendeteksinya. `name` = nama produk (tidak diterjemahkan),
# `note` = kode catatan yang diterjemahkan UI (i18n), bukan prosa.

# Каждый инструмент описан ОДИН раз (ITEMS); профили ссылаются на него по id и при необходимости меняют `required`.
# Так gh, lazygit, clt, CocoaPods, fastlane, Node, Python и т. д. не дублируются между профилями, а проверка устанавливает/находит их одинаково.
def _f(id_, name, pkg, cmd, args=("--version",), required=False, **kw):
    return {"id": id_, "name": name, "pkg": pkg, "type": kw.pop("type", "formula"), "detect": ("cmd", cmd, tuple(args)) + ((kw.pop("path"),) if "path" in kw else ()),
            "required": required, **kw}


ITEMS = {i["id"]: i for i in [
    {"id": "clt", "name": "Xcode Command Line Tools", "pkg": "xcode-select --install", "type": "system", "detect": ("clt",), "required": True, "note": "gui_only", "install": "setup"},
    {"id": "homebrew", "name": "Homebrew", "pkg": "/bin/bash -c \"$(curl …)\"", "type": "system", "detect": ("cmd", "brew", ("--version",)), "required": True, "install": "setup"},
    _f("python", "Python 3.12", "python@3.12", "python3.12"),
    _f("git", "Git", "git", "git", required=True),
    _f("gh", "GitHub CLI", "gh", "gh"),
    _f("fzf", "fzf", "fzf", "fzf"), _f("jq", "jq", "jq", "jq"), _f("yq", "yq", "yq", "yq"), _f("ripgrep", "ripgrep", "ripgrep", "rg"),
    _f("lazygit", "lazygit", "lazygit", "lazygit"), _f("lazydocker", "lazydocker", "lazydocker", "lazydocker"), _f("git-delta", "git-delta", "git-delta", "delta"),
    # ИИ
    _f("claude", "Claude Code", "claude-code", "claude", type="cask"), _f("codex", "Codex CLI", "codex", "codex", type="cask"),
    _f("opencode", "OpenCode", "opencode", "opencode"), _f("gemini", "Gemini CLI", "gemini-cli", "gemini"),
    _f("node", "Node.js LTS", "node@22", "node", ("-v",)), _f("bun", "Bun", "bun", "bun"),
    # мобильная
    {"id": "flutter", "name": "Flutter SDK", "pkg": "flutter", "type": "cask", "detect": ("flutter",), "required": False},
    _f("fvm", "FVM", "fvm", "fvm"), _f("dart", "Dart", "dart-sdk", "dart"),
    {"id": "java", "name": "JDK (Android)", "pkg": "openjdk@21", "type": "formula", "detect": ("jdk",), "required": False},
    {"id": "android-sdk", "name": "Android SDK", "pkg": "android-commandlinetools", "type": "cask", "detect": ("android_sdk",), "required": False, "note": "licenses"},
    {"id": "android-studio", "name": "Android Studio", "pkg": "android-studio", "type": "cask", "detect": ("app", "/Applications/Android Studio.app"), "required": False,
     "note": "gui_only", "install": "manual"},
    _f("cocoapods", "CocoaPods", "cocoapods", "pod"), _f("fastlane", "fastlane", "fastlane", "fastlane"),
    {"id": "xcode", "name": "Xcode", "pkg": "App Store / xcodes", "type": "system", "detect": ("xcode",), "required": True, "note": "needs_apple_id_gui", "install": "manual"},
    _f("xcodes", "Xcodes", "xcodes", "xcodes"),
    {"id": "runtimes", "name": "iOS Simulator runtime", "pkg": "xcodebuild -downloadPlatform iOS", "type": "system", "detect": ("ios_runtimes",), "required": False,
     "note": "large_download", "install": "later"},
    _f("swiftformat", "SwiftFormat", "swiftformat", "swiftformat"), _f("xcbeautify", "xcbeautify", "xcbeautify", "xcbeautify"),
    # backend / web
    {"id": "docker", "name": "Docker / OrbStack", "pkg": "orbstack", "type": "cask", "detect": ("docker",), "required": False, "note": "choose_runtime"},
    _f("postgresql", "PostgreSQL", "postgresql@17", "psql", service="postgresql@17"),
    _f("redis", "Redis", "redis", "redis-server", service="redis"),
    _f("mysql", "MySQL", "mysql", "mysql", service="mysql"),
    _f("go", "Go", "go", "go", ("version",)),
    _f("rust", "Rust", "rustup", "rustc", path="/opt/homebrew/opt/rustup/bin", after=["rustup-default-stable"]),
    _f("php", "PHP", "php", "php", ("-v",)), _f("composer", "Composer", "composer", "composer"),
    {"id": "herd", "name": "Laravel Herd", "pkg": "herd", "type": "cask", "detect": ("app", "/Applications/Herd.app"), "required": False},
    _f("uv", "uv (Python)", "uv", "uv"), _f("pipx", "pipx", "pipx", "pipx"),
    _f("pnpm", "pnpm", "pnpm", "pnpm"), _f("yarn", "Yarn", "yarn", "yarn"),
    _f("cloudflared", "Cloudflared", "cloudflared", "cloudflared"), _f("mkcert", "mkcert (local HTTPS)", "mkcert", "mkcert", ("-version",)),
    _f("httpie", "HTTPie", "httpie", "http"),
    {"id": "chrome", "name": "Google Chrome", "pkg": "google-chrome", "type": "cask", "detect": ("app", "/Applications/Google Chrome.app"), "required": False},
]}


def _p(id_, icon, refs):
    """Профиль = ссылки на ITEMS. ref = "id" или ("id", required) — переопределяет обязательность только в этом профиле."""
    items = []
    for ref in refs:
        iid, req = (ref, None) if isinstance(ref, str) else ref
        item = dict(ITEMS[iid])
        if req is not None:
            item["required"] = req
        items.append(item)
    return {"id": id_, "icon": icon, "items": items}


PROFILES_MAC = [
    _p("base", "homebrew", ["clt", "homebrew", "python", "git", "gh", "fzf", "jq", "yq", "ripgrep", "lazygit", "lazydocker", "git-delta"]),
    _p("ai", "claude", [("claude", True), "codex", "opencode", "gemini", ("node", True), "bun", "gh", "lazygit"]),
    _p("flutter", "flutter", [("flutter", True), "fvm", "dart", ("java", True), ("android-sdk", True), "android-studio", "cocoapods", "fastlane"]),
    _p("ios", "apple", ["xcode", "clt", "xcodes", "runtimes", "cocoapods", "fastlane", "swiftformat", "xcbeautify"]),
    _p("backend", "docker", [("docker", True), "postgresql", "redis", "mysql", "go", "rust", "python"]),
    _p("backend-php", "php", [("php", True), ("composer", True), "herd", "mysql", "redis", "docker", "node", "cloudflared"]),
    _p("backend-node", "node", [("node", True), "pnpm", "postgresql", "redis", "docker", "cloudflared"]),
    _p("backend-python", "python", [("python", True), "uv", "pipx", "postgresql", "redis", "docker"]),
    _p("backend-go", "go", [("go", True), "postgresql", "redis", "docker"]),
    _p("web", "node", [("node", True), "pnpm", "yarn", ("git", True), "gh", "chrome", "mkcert", "httpie"]),
]

def _lp(pid_item, name, pkg, required=False, detect_pkg=None):
    return {"id": pid_item, "name": name, "pkg": pkg, "type": "apt", "detect": ("dpkg", detect_pkg or pkg), "required": required}


PROFILES_LINUX = [
    {"id": "linux-base", "icon": "git", "items": [
        _lp("git", "Git", "git", True), _lp("curl", "curl", "curl", True), _lp("build-essential", "Build tools (gcc, make)", "build-essential", True),
        _lp("python3", "Python 3", "python3"), _lp("python3-venv", "Python venv", "python3-venv"), _lp("python3-pip", "pip", "python3-pip"),
        _lp("jq", "jq", "jq"), _lp("ripgrep", "ripgrep", "ripgrep"), _lp("fzf", "fzf", "fzf"), _lp("gh", "GitHub CLI", "gh"),
        _lp("unzip", "unzip", "unzip"), _lp("htop", "htop", "htop")]},
    {"id": "linux-backend", "icon": "postgres", "items": [
        _lp("sqlite3", "SQLite", "sqlite3"), _lp("redis", "Redis", "redis-server"), _lp("postgresql", "PostgreSQL", "postgresql"),
        _lp("nginx", "nginx", "nginx"), _lp("nodejs", "Node.js (apt)", "nodejs"), _lp("npm", "npm", "npm")]},
    {"id": "linux-flutter", "icon": "flutter", "items": [
        _lp("git", "Git", "git", True), _lp("curl", "curl", "curl", True), _lp("unzip", "unzip", "unzip", True), _lp("xz-utils", "xz-utils", "xz-utils", True),
        _lp("zip", "zip", "zip", True), _lp("jdk", "Java JDK (Android)", "default-jdk-headless"), _lp("clang", "clang", "clang"), _lp("cmake", "CMake", "cmake"),
        _lp("ninja", "Ninja", "ninja-build"), _lp("pkg-config", "pkg-config", "pkg-config"), _lp("gtk3", "GTK 3 (Linux desktop builds)", "libgtk-3-dev"),
        _lp("glu", "libglu1-mesa", "libglu1-mesa"),
        {"id": "flutter", "name": "Flutter SDK", "pkg": "https://docs.flutter.dev/get-started/install/linux", "type": "manual", "detect": ("flutter",), "required": False,
         "note": "manual"},
        {"id": "android-sdk", "name": "Android SDK (command-line tools)", "pkg": "https://developer.android.com/studio#command-line-tools-only", "type": "manual",
         "detect": ("android_sdk",), "required": False, "note": "manual"}]},
    {"id": "linux-containers", "icon": "docker", "items": [
        _lp("docker", "Docker Engine", "docker.io"), _lp("compose", "Docker Compose", "docker-compose-v2")]},
]
PROFILES_LINUX.append({"id": "linux-web", "icon": "node",
                       "items": [_lp("git", "Git", "git", True), _lp("curl", "curl", "curl"), _lp("nodejs", "Node.js (apt)", "nodejs", True), _lp("npm", "npm", "npm", True)]})
PROFILES = PROFILES_MAC if sys.platform == "darwin" else PROFILES_LINUX
PROFILE_IDS = {p["id"] for p in PROFILES}


def _apt(item):
    """Пакет apt установлен? Версия берётся из dpkg."""
    code, out, _ = run(["dpkg-query", "-W", "-f", "${Status}\t${Version}", item], timeout=8)
    ok = code == 0 and out.startswith("install ok installed")
    return {"installed": ok, "version": out.split("\t", 1)[1] if ok and "\t" in out else None}


def _which(cmd, extra=""):
    return shutil.which(cmd, path=ENV["PATH"] + ((":" + extra) if extra else ""))


def _version(cmd, args, timeout=8):
    """Versi pertama yang cocok dari output perintah, atau None."""
    try:
        _, out, err = run([cmd, *args], timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = VER_RE.search(out or "") or VER_RE.search(err or "")
    return m[0] if m else None


def _cmd(cmd, args, extra=""):
    path = _which(cmd, extra)
    if not path:
        return {"installed": False}
    if clt_stub(path):  # stub /usr/bin tanpa CLT: jangan dijalankan (membuka dialog Apple)
        return {"installed": False, "note": "needs_clt"}
    return {"installed": True, "version": _version(path, args), "path": path}


def _docker():
    """Команда docker, а если её нет — установленное приложение OrbStack/Docker Desktop: команду `docker` оно создаёт только при первом запуске."""
    r = _cmd("docker", ("--version",))
    if r.get("installed"):
        return r
    for app in ("/Applications/OrbStack.app", "/Applications/Docker.app"):
        if os.path.isdir(app):
            return {"installed": True, "version": None, "path": app, "detail": [os.path.basename(app) + " — запустите один раз: появится команда docker"]}
    return r


def _clt():
    try:
        code, out, _ = run(["xcode-select", "-p"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False}
    path = out.strip()
    if code != 0 or not path:
        return {"installed": False}
    # /Library/Developer/CommandLineTools = CLT saja; /Applications/Xcode.app/... = Xcode penuh
    return {"installed": True, "version": None, "path": path,
            "full_xcode": "Xcode" in path}


def _app(path):
    if not os.path.isdir(path):
        return {"installed": False}
    version = None
    plist = os.path.join(path, "Contents/Info.plist")
    try:
        with open(plist, "rb") as f:
            version = plistlib.load(f).get("CFBundleShortVersionString")
    except (OSError, ValueError):
        pass
    return {"installed": True, "version": version, "path": path}


def _python_server():
    """Python yang benar-benar bisa menjalankan server ini (butuh >= 3.11)."""
    candidates = [os.path.join(ENV.get("PATH", "").split(":")[0], "python3")]
    candidates += ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
    import glob
    candidates += sorted(glob.glob("/Library/Frameworks/Python.framework/Versions/*/bin/python3"), reverse=True)
    for p in candidates:
        if not p or not os.path.isfile(p):
            continue
        try:
            code, out, _ = run([p, "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"], timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if code == 0 and out.strip():
            ok = tuple(int(x) for x in out.strip().split(".")[:2]) >= (3, 11)
            return {"installed": True, "version": out.strip(), "path": p,
                    "compatible": ok, "note": None if ok else "too_old"}
    return {"installed": False}


def _flutter():
    from mobile import flutter_info  # impor lokal: hindari ketergantungan melingkar
    try:
        info = flutter_info()
    except Exception:  # noqa: BLE001
        return {"installed": False}
    sdk = info.get("sdk") or {}
    if not sdk.get("path"):
        return {"installed": False}
    return {"installed": True, "version": sdk.get("version"), "path": sdk["path"]}


def _brew_jdk():
    """openjdk@N dari Homebrew tidak terlihat oleh /usr/libexec/java_home tanpa symlink ke
    /Library/Java/JavaVirtualMachines (butuh sudo). Panel mengelola Java lewat JAVA_HOME (runtimes.py),
    jadi JDK Homebrew yang terpasang dihitung sebagai ada."""
    import glob
    for d in sorted(glob.glob(os.path.join(BREW_PREFIX, "opt", "openjdk*")), reverse=True):
        java = os.path.join(d, "bin", "java")
        if os.path.exists(java):
            m = re.search(r"openjdk@?(\d+)?", os.path.basename(d))
            return {"installed": True, "version": (m[1] if m and m[1] else None), "path": d,
                    "detail": [os.path.basename(d) + " (Homebrew)"]}
    return None


def _jdk():
    try:
        code, out, _ = run(["/usr/libexec/java_home", "-V"], timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return {"installed": False}
    text = out or ""
    m = re.search(r"(\d+(?:\.\d+)*)", text) if code == 0 else None
    if bool(re.search(r"\d+\.\d+", text)):
        return {"installed": True, "version": m[1] if m else None, "detail": text.strip().splitlines()}
    return _brew_jdk() or {"installed": False, "detail": text.strip().splitlines()}


def _android_sdk():
    from mobile import android_info
    try:
        info = android_info()
    except Exception:  # noqa: BLE001
        return {"installed": False}
    if not info.get("sdk_path"):
        return {"installed": False}
    platforms = info.get("platforms") or []
    return {"installed": True, "version": platforms[-1].replace("android-", "") if platforms else None,
            "path": info["sdk_path"], "detail": platforms}


def _xcode():
    from mobile import xcode_info
    try:
        info = xcode_info()
    except Exception:  # noqa: BLE001
        return {"installed": False}
    active = info.get("active") or {}
    if not active:
        return {"installed": False}
    return {"installed": True, "version": active.get("version"), "path": active.get("path"),
            "detail": [i["path"] for i in info.get("installs", [])]}


def _ios_runtimes():
    from mobile import xcode_info
    try:
        runtimes = xcode_info().get("runtimes") or []
    except Exception:  # noqa: BLE001
        return {"installed": False}
    if not runtimes:
        return {"installed": False}
    return {"installed": True, "version": runtimes[-1].get("version"), "path": None,
            "detail": [r.get("name") for r in runtimes]}


DETECTORS = {
    "clt": _clt,
    "docker": _docker,
    "app": _app,
    "python_server": _python_server,
    "flutter": _flutter,
    "jdk": _jdk,
    "android_sdk": _android_sdk,
    "xcode": _xcode,
    "ios_runtimes": _ios_runtimes,
    "dpkg": _apt,
}


def _detect(spec):
    """spec = (jenis, argumen...). Setiap detektor mengembalikan dict
    {"installed": bool, "version": str|None, "path": str|None, ...}."""
    kind, *args = spec
    try:
        if kind == "cmd":
            return _cmd(args[0], args[1], args[2] if len(args) > 2 else "")
        fn = DETECTORS.get(kind)
        if not fn:
            return {"installed": False}
        return fn(args[0]) if kind in ("app", "dpkg") else fn()
    except Exception as e:  # noqa: BLE001
        return {"installed": False, "error": str(e)}


# ---------------------------------------------------------------- API

def _unique_specs():
    """Tiap alat dideteksi sekali saja walau muncul di beberapa profil
    (mis. CocoaPods ada di profil Flutter dan iOS)."""
    seen = {}
    for profile in PROFILES:
        for item in profile["items"]:
            seen.setdefault(tuple(item["detect"]), item)
    return seen


def _install_kind(item):
    """brew | setup (мастер «Подготовка системы») | manual (нельзя из панели) | later (позже в плане)."""
    if item.get("install"):
        return item["install"]
    return "brew" if item["type"] in ("formula", "cask", "apt") else "manual"  # "brew" здесь = «ставится менеджером пакетов» (на Linux — apt)


CONSENT_NOTES = {"licenses"}      # пункт требует согласия человека (лицензии Android SDK): панель само согласие не даёт


def _services_running():
    """{имя brew-сервиса: запущен ли} или None, если узнать нельзя (Linux, brew недоступен): «установлено» ≠ «работает»."""
    if sys.platform != "darwin":
        return None
    try:
        import brewsvc   # лениво: brewsvc → operations → profiles
        return {s["name"]: bool(s.get("running")) for s in brewsvc.list_services()}
    except Exception:  # noqa: BLE001 — признак «запущено» не должен ронять каталог
        return None


def catalog(q=None):
    """Katalog profil + status deteksi tiap alat (read-only).
    `?refresh=1` memaksa deteksi ulang, melewati cache."""
    force = bool(q and q.get("refresh") == "1")
    if not force and _cache["data"] and time.time() - _cache["t"] < CACHE_TTL:
        return _cache["data"]
    specs = _unique_specs()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(zip(specs.keys(), pool.map(_detect, specs.keys())))
    profiles = []
    running = _services_running() if any(i.get("service") for p in PROFILES for i in p["items"]) else None
    for profile in PROFILES:
        items = []
        for item in profile["items"]:
            state = results.get(tuple(item["detect"])) or {"installed": False}
            extra = {}
            if item.get("service"):
                extra = {"service": item["service"], "running": (running or {}).get(item["service"]) if state.get("installed") and running is not None else None}
            items.append({"id": item["id"], "name": item["name"], "pkg": item["pkg"], "type": item["type"],
                          "required": bool(item.get("required")), "note": item.get("note"), "consent": item.get("note") in CONSENT_NOTES,
                          "install": _install_kind(item), **extra, **state})
        have = sum(1 for i in items if i["installed"])
        missing_required = [i["id"] for i in items if i["required"] and not i["installed"]]
        profiles.append({"id": profile["id"], "icon": profile["icon"], "items": items,
                         "have": have, "total": len(items), "ready": not missing_required,
                         "missing_required": missing_required})
    data = {"profiles": profiles, "readonly": False}
    _cache.update(t=time.time(), data=data)
    return data


# ---------------------------------------------------------------- instalasi (Fase 2.4)

INSTALL_KIND = "profile-install"  # satu job pada satu waktu: dua `brew install` paralel saling mengunci
SCOPES = ("required", "all")


def _find_profile(pid):
    for p in PROFILES:
        if p["id"] == pid:
            return p
    raise ApiError("Неизвестный профиль", code="prof.unknown")


def _brew_bin():
    return next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(p)), None)


def plan(q):
    """Rencana instalasi satu profil — TANPA mengubah apa pun.
    Parameter: profile, scope=required|all (default required), items=a,b (menggantikan scope).
    Deteksi dijalankan ulang (refresh) supaya yang sudah terpasang dilewati (idempoten)."""
    profile = _find_profile(q.get("profile"))
    scope = q.get("scope") or "required"
    if scope not in SCOPES:
        raise ApiError("scope: required | all", code="prof.bad_scope")
    wanted = [x for x in (q.get("items") or "").split(",") if x]
    known = {i["id"] for i in profile["items"]}
    if any(x not in known for x in wanted):
        raise ApiError("Неизвестный пункт профиля", code="prof.unknown_item")
    state = {i["id"]: i for i in next(p for p in catalog({"refresh": "1"})["profiles"] if p["id"] == profile["id"])["items"]}
    entries = []
    for item in profile["items"]:
        if wanted and item["id"] not in wanted:
            continue
        if not wanted and scope == "required" and not item.get("required"):
            continue
        st, kind = state[item["id"]], _install_kind(item)
        entry = {"id": item["id"], "name": item["name"], "pkg": item["pkg"], "type": item["type"],
                 "required": bool(item.get("required")), "kind": kind}
        if st["installed"]:
            entry["action"] = "skip"
        elif kind == "brew":
            entry["action"] = "install"
        else:
            entry["action"] = kind  # setup | manual | later — из панели сейчас не ставится
        entries.append(entry)
    blocked = None
    if any(e["action"] == "install" for e in entries) and sys.platform != "darwin":
        import platform_info
        if not platform_info.has("pkg.apt"):
            blocked = "needs_apt"
    elif any(e["action"] == "install" for e in entries):
        if not has_clt():
            blocked = "needs_clt"
        elif not _brew_bin():
            blocked = "needs_homebrew"
    return {"profile": profile["id"], "scope": scope, "items": entries, "blocked": blocked,
            "to_install": sum(1 for e in entries if e["action"] == "install")}


def _verify(planned, before_id, log):
    """Заключительный шаг job: повторная детекция + снимок «после» + разница с «до»."""
    import snapshots  # локально: snapshots импортирует profiles
    state = {i["id"]: i for pr in catalog({"refresh": "1"})["profiles"] for i in pr["items"]}
    missing = []
    for e in planned:
        ok = bool(state.get(e["id"], {}).get("installed"))
        log(f"{'✔' if ok else '✖'} {e['name']}" + ("" if ok else "  — не обнаружено после установки"))
        if not ok:
            missing.append(e["name"])
    try:
        after = snapshots.create({"label": "после: " + planned[0]["profile_name"]})["id"]
        d = snapshots.diff({"a": before_id, "b": after}) if before_id else None
        if d:
            log(f"\nРазница со снимком «до» ({d['total']} изм.), подробно — страница «Снимки»:")
            for sec in d["sections"][:8]:
                for x in (sec["added"] + sec["changed"])[:6]:
                    log(f"  {sec['id']}: {x['key']} {x.get('to', '')}".rstrip())
    except Exception as e:  # noqa: BLE001 - разница вторична; установка уже выполнена
        log(f"(снимок «после» не сохранён: {e})")
    if missing:
        raise RuntimeError("не обнаружено после установки: " + ", ".join(missing))


def _install_linux(todo, planned_profile):
    """Linux: один вызов apt-get install для всех недостающих пакетов, с правами администратора (окно polkit или sudo в терминале)."""
    import aptsvc
    import elevate
    import platform_info
    pkgs = [e["pkg"] for e in todo]
    ids = [e["id"] for e in todo]
    if not all(aptsvc.APT_NAME.match(p) for p in pkgs):
        raise ApiError("Недопустимое имя пакета", code="srv.pkg_invalid")
    if not platform_info.has("elevation.gui"):  # без экрана пароль вводится только в терминале панели
        return dict(elevate.run_admin("profile", ["apt-get", "install", "-y", *pkgs]), planned=ids)
    ref = {"before": None}

    def snapshot_before(log):
        import snapshots
        try:
            ref["before"] = snapshots.create({"label": f"до: {planned_profile}"})["id"]
            log(f"Снимок «до» сохранён: {ref['before']}")
        except Exception as e:  # noqa: BLE001
            log(f"(снимок «до» не сохранён: {e})")

    planned = [dict(e, profile_name=planned_profile) for e in todo]
    steps = [("Снимок «до»", snapshot_before, {}),
             ("apt-get install (polkit спросит пароль)", ["pkexec", *elevate.admin_argv(["apt-get", "install", "-y", *pkgs])], {}),
             ("Проверка и разница «до/после»", lambda log: _verify(planned, ref["before"], log), {})]
    return {"job": start_steps(f"Профиль: {planned_profile}", steps, INSTALL_KIND), "planned": ids}


def install(body):
    """Выполнить план профиля через start_steps. План пересобирается заново (идемпотентность)."""
    q = {"profile": body.get("profile"), "scope": body.get("scope") or "required",
         "items": ",".join(body.get("items") or []) if isinstance(body.get("items"), list) else ""}
    pl = plan(q)
    if pl["blocked"]:
        raise ApiError("Сначала откройте «Подготовка системы»: " + pl["blocked"], HTTPStatus.CONFLICT, code="prof.blocked", blocked=pl["blocked"])
    todo = [e for e in pl["items"] if e["action"] == "install"]
    if not todo:
        raise ApiError("Нечего устанавливать: всё уже стоит или ставится вне панели", HTTPStatus.CONFLICT, code="prof.nothing")
    profile = _find_profile(pl["profile"])
    pname = {"base": "Фундамент", "ai": "AI", "flutter": "Flutter", "ios": "iOS", "backend": "Backend", "linux-base": "Фундамент",
             "linux-backend": "Backend", "linux-containers": "Контейнеры"}.get(profile["id"], profile["id"])
    if sys.platform != "darwin":
        return _install_linux(todo, planned_profile=pname)
    brew = _brew_bin()
    import setup  # локально: setup не зависит от profiles, но так импорт остаётся ленивым
    env = dict(ENV, NONINTERACTIVE="1", SUDO_ASKPASS=os.path.join(setup.DATA_DIR, "askpass.sh"))
    ref = {"before": None}

    def snapshot_before(log):
        import snapshots
        try:
            ref["before"] = snapshots.create({"label": f"до: {pname}"})["id"]
            log(f"Снимок «до» сохранён: {ref['before']}")
        except Exception as e:  # noqa: BLE001 - без снимка установка всё равно возможна
            log(f"(снимок «до» не сохранён: {e})")

    steps = [("Снимок «до»", snapshot_before, {})]
    if any(e["type"] == "cask" for e in todo):
        steps.append(("Диалог пароля администратора (на случай cask с pkg)", setup._write_askpass, {}))  # noqa: SLF001
    for e in todo:
        cmd = [brew, "install", *(["--cask"] if e["type"] == "cask" else []), e["pkg"]]
        steps.append((f"{e['name']}: {' '.join(['brew'] + cmd[1:])}", cmd, {"env": env, "optional": True}))
        for after in next(i for i in profile["items"] if i["id"] == e["id"]).get("after", []):
            if after == "rustup-default-stable":
                steps.append(("Rust: rustup default stable", [f"{BREW_PREFIX}/opt/rustup/bin/rustup", "default", "stable"],
                              {"env": env, "optional": True}))
    planned = [dict(e, profile_name=pname) for e in todo]
    steps.append(("Проверка и разница «до/после»", lambda log: _verify(planned, ref["before"], log), {}))
    return {"job": start_steps(f"Профиль: {pname}", steps, INSTALL_KIND), "planned": [e["id"] for e in todo]}


# ---------------------------------------------------------------- машиночитаемое описание профиля (Фаза 4.1)
# Знание о том, ЧТО ставится и в каком порядке, живёт здесь, а не в агенте: агент спрашивает каталог.

ITEM_DEPENDS = {"android-sdk": ["java"], "android-studio": ["java"], "gemini": ["node"], "fvm": [], "cocoapods": []}
MIN_MACOS = "13"


def describe(q):
    """Описание профиля: требования к ОС/архитектуре, предпосылки, пункты (пакет, способ, зависимости, шаги, проверка, откат)
    в порядке установки. Только чтение (детекция — как в `catalog`)."""
    profile = _find_profile(q.get("profile"))
    state = {i["id"]: i for i in next(p for p in catalog({"refresh": "1"})["profiles"] if p["id"] == profile["id"])["items"]}
    items = []
    for it in profile["items"]:
        kind = _install_kind(it)
        st = state[it["id"]]
        steps = []
        if kind == "brew" and sys.platform != "darwin":
            steps.append(f"apt-get install -y {it['pkg']}")
        elif kind == "brew":
            steps.append(f"brew install{' --cask' if it['type'] == 'cask' else ''} {it['pkg']}")
            steps += ["rustup default stable" for a in it.get("after", []) if a == "rustup-default-stable"]
        items.append({"id": it["id"], "name": it["name"], "package": it["pkg"], "type": it["type"], "install_via": kind,
                      "required": bool(it.get("required")), "depends_on": ITEM_DEPENDS.get(it["id"], []),
                      "prerequisites": (["apt", "administrator_rights"] if sys.platform != "darwin" else ["command_line_tools", "homebrew"]) if kind == "brew" else [],
                      "steps": steps, "verify": {"detector": it["detect"][0], "target": it["detect"][1] if len(it["detect"]) > 1 else None},
                      "rollback": {"operation": "package.uninstall", "params": {"name": it["pkg"], "type": it["type"]}} if kind == "brew" else None,
                      "installed": st["installed"], "version": st.get("version")})
    order, seen = [], set()

    def visit(i):
        if i["id"] in seen:
            return
        seen.add(i["id"])
        for d in i["depends_on"]:
            dep = next((x for x in items if x["id"] == d), None)
            if dep:
                visit(dep)
        order.append(i["id"])
    for i in items:
        visit(i)
    reqs = ({"os": f"macOS {MIN_MACOS}+", "arch": ["arm64", "x86_64"], "prerequisites": ["command_line_tools", "homebrew"]} if sys.platform == "darwin"
            else {"os": "Debian/Ubuntu (apt)", "arch": ["aarch64", "x86_64"], "prerequisites": ["apt", "administrator_rights"]})
    return {"profile": profile["id"], "requirements": reqs,
            "items": items, "install_order": order}
