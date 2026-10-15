"""Toolchain mobile: Xcode, simulator iOS, Flutter/FVM, Android SDK, CocoaPods.

FASE 1 — HANYA BACA. Modul ini tidak memasang, mengunduh, atau mengubah apa pun:
tidak ada `xcode-select -s`, tidak ada `xcodebuild -downloadPlatform`,
tidak ada `sdkmanager`, tidak ada `fvm use`. Semua yang dijalankan di sini
hanya melaporkan keadaan.

Catatan penting soal Flutter: `flutter --version` MENULIS ke cache SDK
(bin/cache), jadi perintah itu tidak dipakai sama sekali. Versi dibaca
langsung dari berkas `bin/cache/flutter.version.json`, yang berarti benar-benar
tanpa efek samping.
"""
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from core import ENV, HOME, run

VER_RE = re.compile(r"\d+(?:\.\d+){1,3}")
CACHE_TTL = 60
_cache = {"t": 0.0, "data": None}

APPLICATION_DIRS = ["/Applications", os.path.join(HOME, "Applications")]
SIMCTL_TIMEOUT = 25


def _out(cmd, timeout=10, cwd=None):
    """(kode, stdout+stderr). Tidak pernah melempar."""
    try:
        code, out, err = run(cmd, timeout=timeout, cwd=cwd)
        return code, (out + err).strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _plist(path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except (OSError, ValueError):
        return {}


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _read_text(path):
    try:
        with open(path, errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _which(cmd, extra=""):
    return shutil.which(cmd, path=ENV["PATH"] + ((":" + extra) if extra else ""))


def _raw_version(cmd, args, timeout=10):
    code, text = _out([cmd, *args], timeout=timeout)
    if code != 0:
        return None
    m = VER_RE.search(text)
    return m[0] if m else None


# ---------------------------------------------------------------- Xcode

def _xcode_install_paths():
    """Semua Xcode*.app di folder Applications (skema multi-versi ala Xcodes)."""
    found = []
    for root in APPLICATION_DIRS:
        for path in sorted(glob.glob(os.path.join(root, "Xcode*.app"))):
            if os.path.isdir(os.path.join(path, "Contents/Developer")):
                found.append(path)
    return found


def _xcode_records(paths):
    def record(path):
        info = _plist(os.path.join(path, "Contents/Info.plist"))
        return {"path": path, "name": os.path.basename(path),
                "version": info.get("CFBundleShortVersionString"),
                "build": info.get("CFBundleVersion")}
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(record, paths))


def _simctl(kind):
    """`xcrun simctl list <kind> --json`. Menyalakan CoreSimulatorService
    kalau belum jalan — itu layanan bawaan Apple, bukan perubahan setelan."""
    code, text = _out(["/usr/bin/xcrun", "simctl", "list", kind, "--json"], timeout=SIMCTL_TIMEOUT)
    if code != 0:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def xcode_info():
    """Kondisi Xcode/CLT + runtime simulator + daftar simulator. Read-only."""
    installs = _xcode_records(_xcode_install_paths())

    code, selected = _out(["xcode-select", "-p"], timeout=5)
    selected = selected if code == 0 else ""
    active = None
    for inst in installs:
        if selected.startswith(inst["path"]):
            active = inst
            break

    clt_path = "/Library/Developer/CommandLineTools"
    clt_installed = os.path.isdir(clt_path)
    only_clt = bool(selected) and selected.startswith(clt_path) and active is None

    # -checkFirstLaunchStatus: 0 = lisensi sudah diterima, != 0 = masih perlu
    # `xcodebuild -runFirstLaunch` (butuh hak admin). Hanya MEMBACA status.
    first_launch = None
    xcodebuild = _which("xcodebuild")
    if xcodebuild:
        code, text = _out([xcodebuild, "-checkFirstLaunchStatus"], timeout=15)
        first_launch = {"done": code == 0, "detail": text or None}

    version = None
    if xcodebuild and active:
        version = _raw_version(xcodebuild, ["-version"])

    runtimes, devices, simctl_ok = [], [], True
    raw = _simctl("runtimes")
    if raw is None:
        simctl_ok = False
    else:
        for rt in raw.get("runtimes", []):
            runtimes.append({"name": rt.get("name"), "version": rt.get("version"),
                             "identifier": rt.get("identifier"), "platform": rt.get("platform"),
                             "available": bool(rt.get("isAvailable")),
                             "reason": rt.get("availabilityError")})
        raw_dev = _simctl("devices")
        if raw_dev is None:
            simctl_ok = False
        else:
            for rt_id, items in (raw_dev.get("devices") or {}).items():
                rt = next((r for r in runtimes if r["identifier"] == rt_id), {})
                for dev in items:
                    devices.append({"name": dev.get("name"), "udid": dev.get("udid"),
                                    "state": dev.get("state"), "runtime": rt.get("name"),
                                    "runtime_id": rt_id,
                                    "available": dev.get("isAvailable", True),
                                    "type": dev.get("deviceTypeIdentifier", "").rsplit(".", 1)[-1]})
    runtimes = sorted(runtimes, key=lambda r: r.get("version") or "", reverse=True)

    return {
        "installs": installs, "active": active, "selected_path": selected or None,
        "clt": {"installed": clt_installed, "path": clt_path if clt_installed else None,
                "only_clt": only_clt},
        "version": version, "first_launch": first_launch,
        "runtimes": runtimes, "devices": devices, "simctl": simctl_ok,
        "xcodes_cli": _which("xcodes"),
        "full_xcode": bool(installs),
    }


# ---------------------------------------------------------------- Flutter / FVM

FLUTTER_CANDIDATES = [
    os.path.join(HOME, "development/flutter"),
    os.path.join(HOME, "flutter"),
    "/opt/homebrew/share/flutter",
    "/usr/local/share/flutter",
    os.path.join(HOME, ".flutter"),
]


def _is_flutter_sdk(path):
    """SDK Flutter asli punya bin/flutter DAN bin/internal (bukan cuma symlink
    di /opt/homebrew/bin yang menunjuk ke sana)."""
    return (os.path.isfile(os.path.join(path, "bin/flutter"))
            and os.path.isdir(os.path.join(path, "bin/internal")))


def _flutter_sdk_paths():
    """Kandidat folder SDK Flutter: dari PATH, env, FVM, dan lokasi umum."""
    found = []

    def add(path):
        if not path:
            return
        path = os.path.realpath(os.path.expanduser(path))
        if os.path.basename(path) == "bin":
            path = os.path.dirname(path)
        if _is_flutter_sdk(path) and path not in found:
            found.append(path)

    which_flutter = _which("flutter")
    if which_flutter:
        # symlink /opt/homebrew/bin/flutter -> <sdk>/bin/flutter: ikuti dulu
        add(os.path.dirname(os.path.realpath(which_flutter)))
    add(os.environ.get("FLUTTER_ROOT"))
    for base in (os.path.join(HOME, "fvm/versions"), os.path.join(HOME, ".fvm/versions")):
        for entry in sorted(glob.glob(os.path.join(base, "*"))):
            add(entry)
    for path in FLUTTER_CANDIDATES:
        add(path)
    for entry in sorted(glob.glob("/opt/homebrew/Caskroom/flutter/*/flutter")):
        add(entry)
    for entry in sorted(glob.glob(os.path.join(HOME, ".puro/envs/*/flutter"))):
        add(entry)
    return found


def flutter_sdk_info(path):
    """Versi dibaca dari berkas cache, TANPA menjalankan `flutter`."""
    version = _read_json(os.path.join(path, "bin/cache/flutter.version.json")) or {}
    framework = version.get("frameworkVersion")
    if not framework:
        legacy = _read_text(os.path.join(path, "version"))
        if legacy:
            framework = legacy.split()[0]
    dart = (version.get("dartSdkVersion")
            or _read_text(os.path.join(path, "bin/cache/dart-sdk/version")))
    source = "puro" if "/.puro/" in path else ("fvm" if "/fvm/" in path
                                                else ("homebrew" if "/Caskroom/" in path or path.startswith("/opt/homebrew")
                                                      else "manual"))
    return {"path": path, "version": framework or None, "channel": version.get("channel"),
            "dart": dart or None,
            "engine": _read_text(os.path.join(path, "bin/internal/engine.version")) or None,
            "source": source,
            "cache_present": os.path.isdir(os.path.join(path, "bin/cache")),
            "has_dart_sdk": os.path.isdir(os.path.join(path, "bin/cache/dart-sdk"))}


def _fvm_info():
    fvm_bin = _which("fvm")
    roots = [os.path.join(HOME, "fvm"), os.path.join(HOME, ".fvm")]
    versions_dir = os.path.join(HOME, "fvm/versions")
    versions = []
    if os.path.isdir(versions_dir):
        versions = sorted(os.path.basename(p) for p in glob.glob(os.path.join(versions_dir, "*"))
                          if os.path.isdir(p))
    cache_dir = os.path.join(HOME, ".fvm/versions")
    if os.path.isdir(cache_dir):
        for name in sorted(os.path.basename(p) for p in glob.glob(os.path.join(cache_dir, "*"))):
            if name not in versions:
                versions.append(name)
    return {"installed": bool(fvm_bin), "path": fvm_bin,
            "root": next((r for r in roots if os.path.isdir(r)), None),
            "versions": versions}


def flutter_projects(limit=40):
    """Folder yang memakai FVM (punya .fvmrc / .fvm/flutter_sdk) atau pubspec.yaml."""
    roots = [os.path.join(HOME, d) for d in ("Documents", "Projects", "Code", "Developer", "Desktop", "Sites")]
    found, deadline = [], time.time() + 3
    for root in roots:
        stack = [(root, 0)]
        while stack and time.time() < deadline:
            path, depth = stack.pop()
            try:
                entries = [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)]
            except OSError:
                continue
            if os.path.isfile(os.path.join(path, "pubspec.yaml")):
                pinned = None
                for name in (".fvmrc", "fvm_config.json"):
                    data = _read_json(os.path.join(path, name))
                    if data:
                        pinned = data.get("flutter") or data.get("flutterSdkVersion")
                        break
                link = os.path.join(path, ".fvm/flutter_sdk")
                found.append({"path": path, "name": os.path.basename(path), "fvm_pinned": pinned,
                              "fvm_link": os.path.realpath(link) if os.path.islink(link) else None,
                              "modified": os.path.getmtime(path)})
                continue  # jangan masuk ke dalam project
            if depth < 3:
                stack += [(e.path, depth + 1) for e in entries
                          if e.name not in ("node_modules", "build", ".git", "ios", "android", "macos", "windows", "linux", "web")
                          and not e.name.startswith(".")]
    found.sort(key=lambda p: -p["modified"])
    return found[:limit]


def flutter_info():
    paths = _flutter_sdk_paths()
    sdks = [flutter_sdk_info(p) for p in paths]
    # SDK "aktif" = yang dipakai `flutter` di PATH, kalau tidak ada pakai yang pertama
    which_flutter = _which("flutter")
    active = None
    if which_flutter:
        real = os.path.realpath(which_flutter)
        active = next((s for s in sdks if real.startswith(s["path"] + os.sep)), None)
    active = active or (sdks[0] if sdks else None)
    pod = _which("pod")
    return {
        "sdk": active, "sdks": sdks, "fvm": _fvm_info(),
        "cocoapods": {"installed": bool(pod), "path": pod,
                      "version": _raw_version(pod, ["--version"]) if pod else None},
        "fastlane": {"installed": bool(_which("fastlane")), "path": _which("fastlane")},
        "dart": _which("dart"),
    }


# ---------------------------------------------------------------- Android

ANDROID_CANDIDATES = [
    os.path.join(HOME, "Library/Android/sdk"),
    os.path.join(HOME, "Android/Sdk"),
    "/opt/homebrew/share/android-commandlinetools",
    "/usr/local/share/android-commandlinetools",
]


def _android_sdk_root():
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(var)
        if value and os.path.isdir(value):
            return value
    return next((p for p in ANDROID_CANDIDATES if os.path.isdir(p)), None)


def android_info():
    root = _android_sdk_root()
    info = {"sdk_path": root, "platforms": [], "build_tools": [], "system_images": [],
            "ndk": [], "cmdline_tools": [], "licenses": 0, "avds": [], "adb": None,
            "emulator": False, "java_homes": [], "sdkmanager": None}
    if not root:
        return info
    def listing(sub):
        """Isi folder SDK tanpa berkas tersembunyi (.DS_Store dll.)."""
        path = os.path.join(root, sub)
        if not os.path.isdir(path):
            return []
        return sorted(e for e in os.listdir(path) if not e.startswith("."))

    info["platforms"] = [p for p in listing("platforms") if p.startswith("android-")]
    info["build_tools"] = listing("build-tools")
    info["ndk"] = listing("ndk")
    info["cmdline_tools"] = listing("cmdline-tools")
    info["emulator"] = os.path.isdir(os.path.join(root, "emulator"))
    # system-images/<api>/<varian>/<abi>
    images_root = os.path.join(root, "system-images")
    for api in listing("system-images"):
        for variant in sorted(os.listdir(os.path.join(images_root, api))) if os.path.isdir(os.path.join(images_root, api)) else []:
            info["system_images"].append({"api": api, "variant": variant})
    lic_dir = os.path.join(root, "licenses")
    if os.path.isdir(lic_dir):
        info["licenses"] = len([f for f in os.listdir(lic_dir) if f.endswith(".lic") or f == "android-sdk-license"])
    adb = os.path.join(root, "platform-tools/adb")
    if os.path.isfile(adb):
        info["adb"] = _raw_version(adb, ["version"])
    sm = os.path.join(root, "cmdline-tools/latest/bin/sdkmanager")
    if not os.path.isfile(sm):
        found = glob.glob(os.path.join(root, "cmdline-tools/*/bin/sdkmanager"))
        sm = found[0] if found else None
    info["sdkmanager"] = sm if sm and os.path.isfile(sm) else None
    # AVD: cukup baca berkas .ini di ~/.android/avd (tanpa menjalankan emulator)
    avd_dir = os.path.join(HOME, ".android/avd")
    if os.path.isdir(avd_dir):
        for ini in sorted(glob.glob(os.path.join(avd_dir, "*.ini"))):
            data = {}
            for line in _read_text(ini).splitlines():
                if "=" in line:
                    k, _, v = line.partition("=")
                    data[k.strip()] = v.strip()
            info["avds"].append({"name": os.path.basename(ini)[:-4], "target": data.get("target"),
                                 "path": data.get("path"), "basedir": data.get("path")})
    # java_home -V menulis ke stderr dengan format: "26.6 (arm64) \"...\" - \"/path\""
    _, text = _out(["/usr/libexec/java_home", "-V"], timeout=10)
    info["java_homes"] = re.findall(r'"(\/[^"]+)"', text)
    return info


# ---------------------------------------------------------------- ringkasan

def mobile_info(q=None):
    """Ringkasan semua toolchain mobile untuk sidebar + halaman.
    `?refresh=1` memaksa deteksi ulang, melewati cache."""
    force = bool(q and q.get("refresh") == "1")
    if not force and _cache["data"] and time.time() - _cache["t"] < CACHE_TTL:
        return _cache["data"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_xcode = pool.submit(xcode_info)
        f_flutter = pool.submit(flutter_info)
        f_android = pool.submit(android_info)
        xcode, flutter, android = f_xcode.result(), f_flutter.result(), f_android.result()

    xcode_ready = bool(xcode["installs"]) and bool(xcode["first_launch"] and xcode["first_launch"]["done"])
    flutter_ready = bool(flutter["sdk"] and flutter["sdk"].get("version"))
    android_ready = bool(android["sdk_path"] and android["platforms"])
    data = {
        "xcode": xcode, "flutter": flutter, "android": android,
        "summary": {
            "xcode": xcode_ready,
            "flutter": flutter_ready,
            "android": android_ready,
            "ios_runtimes": len([r for r in xcode["runtimes"] if r["platform"] == "iOS"]),
            "simulators": len(xcode["devices"]),
            "booted": len([d for d in xcode["devices"] if d["state"] == "Booted"]),
        },
        "readonly": True,
    }
    _cache.update(t=time.time(), data=data)
    return data
