"""Слой «платформа» (Фаза 6, Л0): на какой системе работает панель и что на ней доступно.
Единственное место, где определяется ОС/дистрибутив/экран/systemd и набор возможностей (`capabilities`).
Правило: остальной код не проверяет `sys.platform` и не вызывает macOS-специфичные утилиты напрямую для ВЫБОРА поведения — он спрашивает здесь.
Ответ: `GET /api/platform`; интерфейс скрывает страницы без возможностей, операции каталога отказывают кодом `platform.unsupported` / unmet requirement."""
import os
import platform
import shutil
import sys
import time

_CACHE = {"at": 0.0, "value": None}
TTL = 30


def _os_release(path="/etc/os-release"):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep:
                    out[k] = v.strip().strip('"')
    except OSError:
        pass
    return out


def os_name():
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _has(*names):
    return any(shutil.which(n, path=os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/sbin", "/sbin"])) for n in names)


def _has_sys(*names):
    """Программа из СИСТЕМНЫХ каталогов (не из PATH пользователя): для всего, что связано с повышением прав и подтверждением."""
    return any(os.path.isfile(os.path.join(d, n)) and os.access(os.path.join(d, n), os.X_OK) for n in names for d in ("/usr/bin", "/usr/sbin", "/bin", "/sbin", "/usr/local/bin"))


def _display():
    """Есть ли графическая сессия, в которой можно показать диалог (Linux). macOS — всегда считаем, что вход выполнен."""
    if os_name() == "macos":
        return True
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return True
    import glob
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    socks = glob.glob(os.path.join(rt, "wayland-*")) + glob.glob("/tmp/.X11-unix/X*")
    uid = os.getuid()
    for s in socks:  # сокет чужой сессии (например, gdm) нам не подходит
        try:
            if os.stat(s).st_uid == uid:
                return True
        except OSError:
            pass
    return False


def _systemd():
    return os.path.isdir("/run/systemd/system")


def compute():
    osn = os_name()
    rel = _os_release() if osn == "linux" else {}
    mac = osn == "macos"
    linux = osn == "linux"
    gui = _display()
    caps = {
        "pkg.brew": _has("brew"),
        "pkg.apt": linux and _has("apt-get", "apt"),
        "service.brew": mac and _has("brew"),
        "service.systemd": linux and _systemd(),
        "vm.tart": _has("tart"),
        "vm.linux": False,  # драйвер ВМ для Linux — этап Л4
        "os.macos": mac,
        "mobile.xcode": mac,
        "mobile.toolchain": True,   # Flutter и Android SDK есть на обеих системах; Xcode/симуляторы — только macOS
        "herd": mac,
        "orbstack": mac,
        "approval.dialog": (mac and _has("osascript")) or (linux and gui and _has("zenity", "kdialog")),
        "approval.sudo": linux and _has_sys("sudo"),
        "elevation": (mac and _has("osascript")) or (linux and _has_sys("pkexec", "sudo")),
        "elevation.gui": linux and gui and _has_sys("pkexec"),
        "notify": (mac and _has("osascript")) or (linux and _has("notify-send")),
        "stats.apple_silicon": mac and platform.machine() == "arm64",
    }
    caps["vm.driver"] = caps["vm.tart"] or caps["vm.linux"]
    return {
        "os": osn,
        "distro": {"id": rel.get("ID", "macos" if mac else ""), "version": rel.get("VERSION_ID", platform.mac_ver()[0] if mac else ""),
                   "name": rel.get("PRETTY_NAME", f"macOS {platform.mac_ver()[0]}" if mac else "")},
        "arch": platform.machine(),
        "gui": gui,
        "headless": not gui,
        "systemd": linux and _systemd(),
        "root": os.geteuid() == 0,
        "capabilities": caps,
    }


def info(q=None):  # q — подпись обработчика маршрута, не используется
    now = time.time()
    if _CACHE["value"] is None or now - _CACHE["at"] > TTL:
        _CACHE.update(at=now, value=compute())
    return _CACHE["value"]


def report(q=None):
    """Ответ GET /api/platform: возможности + состояние канала подтверждения агентов (approval.py)."""
    import approval
    return {**info(), "approval": approval.channel()}


# Маршруты вне каталога операций, которые существуют только при некоторой возможности: сервер отказывает кодом platform.unsupported (а не 500/«tool_missing»),
# даже если страницу в интерфейсе открыли по адресу вручную.
ROUTE_CAPS = (("/api/herd", "herd"), ("/api/php/herd", "herd"), ("/api/mobile/runtimes", "mobile.xcode"), ("/api/mobile/screenshot", "mobile.xcode"),
              ("/api/mobile", "mobile.toolchain"), ("/api/activity-monitor", "os.macos"))


def route_missing(path):
    """→ имя недостающей возможности или None."""
    for prefix, cap in ROUTE_CAPS:
        if (path == prefix or path.startswith(prefix + "/")) and not has(cap):
            return cap
    return None


def has(cap):
    return bool(info()["capabilities"].get(cap))


def is_macos():
    return os_name() == "macos"
