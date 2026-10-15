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

PROFILES_MAC = [
    {
        "id": "base",
        "icon": "homebrew",
        "items": [
            {"id": "clt", "name": "Xcode Command Line Tools", "pkg": "xcode-select --install", "type": "system",
             "detect": ("clt",), "required": True, "note": "gui_only", "install": "setup"},
            {"id": "homebrew", "name": "Homebrew", "pkg": "/bin/bash -c \"$(curl …)\"", "type": "system",
             "detect": ("cmd", "brew", ("--version",)), "required": True, "install": "setup"},
            {"id": "python", "name": "Python 3.12", "pkg": "python@3.12", "type": "formula",
             "detect": ("cmd", "python3.12", ("--version",)), "required": False},
            {"id": "git", "name": "Git", "pkg": "git", "type": "formula",
             "detect": ("cmd", "git", ("--version",)), "required": True},
            {"id": "gh", "name": "GitHub CLI", "pkg": "gh", "type": "formula",
             "detect": ("cmd", "gh", ("--version",)), "required": False},
            {"id": "fzf", "name": "fzf", "pkg": "fzf", "type": "formula",
             "detect": ("cmd", "fzf", ("--version",)), "required": False},
            {"id": "jq", "name": "jq", "pkg": "jq", "type": "formula",
             "detect": ("cmd", "jq", ("--version",)), "required": False},
            {"id": "yq", "name": "yq", "pkg": "yq", "type": "formula",
             "detect": ("cmd", "yq", ("--version",)), "required": False},
            {"id": "ripgrep", "name": "ripgrep", "pkg": "ripgrep", "type": "formula",
             "detect": ("cmd", "rg", ("--version",)), "required": False},
            {"id": "lazygit", "name": "lazygit", "pkg": "lazygit", "type": "formula",
             "detect": ("cmd", "lazygit", ("--version",)), "required": False},
            {"id": "lazydocker", "name": "lazydocker", "pkg": "lazydocker", "type": "formula",
             "detect": ("cmd", "lazydocker", ("--version",)), "required": False},
            {"id": "git-delta", "name": "git-delta", "pkg": "git-delta", "type": "formula",
             "detect": ("cmd", "delta", ("--version",)), "required": False},
        ],
    },
    {
        "id": "ai",
        "icon": "claude",
        "items": [
            {"id": "claude", "name": "Claude Code", "pkg": "claude-code", "type": "cask",
             "detect": ("cmd", "claude", ("--version",)), "required": True},
            {"id": "codex", "name": "Codex CLI", "pkg": "codex", "type": "cask",
             "detect": ("cmd", "codex", ("--version",)), "required": False},
            {"id": "opencode", "name": "OpenCode", "pkg": "opencode", "type": "formula",
             "detect": ("cmd", "opencode", ("--version",)), "required": False},
            {"id": "gemini", "name": "Gemini CLI", "pkg": "gemini-cli", "type": "formula",
             "detect": ("cmd", "gemini", ("--version",)), "required": False},
            {"id": "node", "name": "Node.js LTS", "pkg": "node@22", "type": "formula",
             "detect": ("cmd", "node", ("-v",)), "required": True},
            {"id": "bun", "name": "Bun", "pkg": "bun", "type": "formula",
             "detect": ("cmd", "bun", ("--version",)), "required": False},
            {"id": "gh", "name": "GitHub CLI", "pkg": "gh", "type": "formula",
             "detect": ("cmd", "gh", ("--version",)), "required": False},
            {"id": "lazygit", "name": "lazygit", "pkg": "lazygit", "type": "formula",
             "detect": ("cmd", "lazygit", ("--version",)), "required": False},
        ],
    },
    {
        "id": "flutter",
        "icon": "flutter",
        "items": [
            {"id": "flutter", "name": "Flutter SDK", "pkg": "flutter", "type": "cask",
             "detect": ("flutter",), "required": True},
            {"id": "fvm", "name": "FVM", "pkg": "fvm", "type": "formula",
             "detect": ("cmd", "fvm", ("--version",)), "required": False},
            {"id": "dart", "name": "Dart", "pkg": "dart-sdk", "type": "formula",
             "detect": ("cmd", "dart", ("--version",)), "required": False},
            {"id": "java", "name": "JDK (Android)", "pkg": "openjdk@21", "type": "formula",
             "detect": ("jdk",), "required": True},
            {"id": "android-sdk", "name": "Android SDK", "pkg": "android-commandlinetools", "type": "cask",
             "detect": ("android_sdk",), "required": True, "note": "licenses"},
            {"id": "android-studio", "name": "Android Studio", "pkg": "android-studio", "type": "cask",
             "detect": ("app", "/Applications/Android Studio.app"), "required": False, "note": "gui_only", "install": "manual"},
            {"id": "cocoapods", "name": "CocoaPods", "pkg": "cocoapods", "type": "formula",
             "detect": ("cmd", "pod", ("--version",)), "required": False},
            {"id": "fastlane", "name": "fastlane", "pkg": "fastlane", "type": "formula",
             "detect": ("cmd", "fastlane", ("--version",)), "required": False},
        ],
    },
    {
        "id": "ios",
        "icon": "apple",
        "items": [
            {"id": "xcode", "name": "Xcode", "pkg": "App Store / xcodes", "type": "system",
             "detect": ("xcode",), "required": True, "note": "needs_apple_id_gui", "install": "manual"},
            {"id": "clt", "name": "Xcode Command Line Tools", "pkg": "xcode-select --install", "type": "system",
             "detect": ("clt",), "required": True, "note": "gui_only", "install": "setup"},
            {"id": "xcodes", "name": "Xcodes", "pkg": "xcodes", "type": "formula",
             "detect": ("cmd", "xcodes", ("--version",)), "required": False},
            {"id": "runtimes", "name": "iOS Simulator runtime", "pkg": "xcodebuild -downloadPlatform iOS", "type": "system",
             "detect": ("ios_runtimes",), "required": False, "note": "large_download", "install": "later"},
            {"id": "cocoapods", "name": "CocoaPods", "pkg": "cocoapods", "type": "formula",
             "detect": ("cmd", "pod", ("--version",)), "required": False},
            {"id": "fastlane", "name": "fastlane", "pkg": "fastlane", "type": "formula",
             "detect": ("cmd", "fastlane", ("--version",)), "required": False},
            {"id": "swiftformat", "name": "SwiftFormat", "pkg": "swiftformat", "type": "formula",
             "detect": ("cmd", "swiftformat", ("--version",)), "required": False},
            {"id": "xcbeautify", "name": "xcbeautify", "pkg": "xcbeautify", "type": "formula",
             "detect": ("cmd", "xcbeautify", ("--version",)), "required": False},
        ],
    },
    {
        "id": "backend",
        "icon": "docker",
        "items": [
            {"id": "docker", "name": "Docker / OrbStack", "pkg": "orbstack", "type": "cask",
             "detect": ("cmd", "docker", ("--version",)), "required": True, "note": "choose_runtime"},
            {"id": "postgresql", "name": "PostgreSQL", "pkg": "postgresql@17", "type": "formula",
             "detect": ("cmd", "psql", ("--version",)), "required": False},
            {"id": "redis", "name": "Redis", "pkg": "redis", "type": "formula",
             "detect": ("cmd", "redis-server", ("--version",)), "required": False},
            {"id": "mysql", "name": "MySQL", "pkg": "mysql", "type": "formula",
             "detect": ("cmd", "mysql", ("--version",)), "required": False},
            {"id": "go", "name": "Go", "pkg": "go", "type": "formula",
             "detect": ("cmd", "go", ("version",)), "required": False},
            {"id": "rust", "name": "Rust", "pkg": "rustup", "type": "formula",
             "detect": ("cmd", "rustc", ("--version",), "/opt/homebrew/opt/rustup/bin"), "required": False,
             "after": ["rustup-default-stable"]},
            {"id": "python", "name": "Python 3.12", "pkg": "python@3.12", "type": "formula",
             "detect": ("cmd", "python3.12", ("--version",)), "required": False},
        ],
    },
]

# ---------------------------------------------------------------- detektor

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
    for profile in PROFILES:
        items = []
        for item in profile["items"]:
            state = results.get(tuple(item["detect"])) or {"installed": False}
            items.append({"id": item["id"], "name": item["name"], "pkg": item["pkg"], "type": item["type"],
                          "required": bool(item.get("required")), "note": item.get("note"),
                          "install": _install_kind(item), **state})
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
