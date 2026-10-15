"""Persiapan Sistem: apa yang dibutuhkan panel untuk dirinya sendiri di macOS bersih.

Python TIDAK diinstal dari sini: panel berjalan di Python bawaan (~/.service-admin/runtime, lihat
fetch-python.sh). Yang bisa dipasang dari panel: Command Line Tools (dialog Apple, panel menunggu
sampai selesai) dan Homebrew (installer resmi). Git ikut Command Line Tools.

Semua perubahan lewat core.start_steps (job + log) dan tercatat di audit (audit.py).
"""
import hashlib
import os
import shutil
import stat
import sys
import time
from http import HTTPStatus

from core import DATA_DIR, ENV, ApiError, clt_stub, has_clt, run, start_steps

BREW_CANDIDATES = ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]
BREW_INSTALLER_URL = "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
CLT_WAIT_SECONDS = 45 * 60
INSTALLABLE = ("clt", "homebrew")
# Измерено в ВМ (macOS 26.6): диалог Apple отказал — «нужно 24,27 ГБ, доступно 18,53 ГБ». Это предупреждение,
# а не запрет: точное требование зависит от версии macOS, мы знаем его по одному случаю.
CLT_LOW_DISK_GB = 26


def runtime_info(q=None):
    """Interpreter yang menjalankan panel: bawaan panel (~/.service-admin/runtime) atau bukan."""
    bundled_root = os.path.realpath(os.path.join(DATA_DIR, "runtime", "python"))
    exe = os.path.realpath(sys.executable)
    return {"python": sys.executable,
            "version": "%d.%d.%d" % sys.version_info[:3],
            "bundled": exe == bundled_root or exe.startswith(bundled_root + os.sep)}


def _brew_path():
    return next((p for p in BREW_CANDIDATES if os.path.exists(p)), None)


def _git():
    path = shutil.which("git", path=ENV["PATH"])
    if not path or clt_stub(path):
        return {"installed": False}
    _, out, _ = run([path, "--version"], timeout=8)
    return {"installed": True, "path": path, "version": out.strip().removeprefix("git version ")}


def status(q=None):
    clt = has_clt()
    brew = _brew_path()
    git = _git()
    rt = runtime_info()
    free_gb = round(shutil.disk_usage("/").free / 1e9, 1)
    items = [
        {"id": "clt", "installed": clt, "mode": "native_dialog",
         "path": run(["/usr/bin/xcode-select", "-p"], timeout=5)[1].strip() if clt else None,
         "can_install": not clt, "blocked_by": None,
         "free_gb": free_gb, "low_disk": (not clt) and free_gb < CLT_LOW_DISK_GB},
        {"id": "homebrew", "installed": bool(brew), "path": brew, "mode": "installer",
         "can_install": not brew and clt, "blocked_by": None if (brew or clt) else "clt"},
        {"id": "git", "installed": git["installed"], "path": git.get("path"), "version": git.get("version"),
         "mode": "bundled_with_clt", "can_install": False, "blocked_by": None if git["installed"] or clt else "clt"},
        {"id": "python", "installed": True, "version": rt["version"], "path": rt["python"],
         "mode": "bundled" if rt["bundled"] else "system", "can_install": False, "blocked_by": None,
         "informational": True},
    ]
    required = [i for i in items if not i.get("informational")]
    return {"items": items, "ready": all(i["installed"] for i in required),
            "missing": [i["id"] for i in required if not i["installed"]], "runtime": rt}


# ---------------------------------------------------------------- instalasi

def _wait_clt(log):
    """Dialog Apple berjalan di luar panel: tunggu sampai CLT benar-benar terpasang."""
    log("Установка идёт в окне Apple. Панель ждёт её завершения (до 45 минут)…")
    deadline = time.time() + CLT_WAIT_SECONDS
    last = 0.0
    while time.time() < deadline:
        if has_clt():
            log("Command Line Tools установлены.")
            return
        if time.time() - last > 60:
            log("…всё ещё ждём окно установки Apple")
            last = time.time()
        time.sleep(5)
    raise RuntimeError("timeout waiting for Command Line Tools")


ASKPASS = """#!/bin/sh
# Dialog password administrator milik macOS (bukan form panel). Hasilnya hanya dibaca `sudo -A`;
# panel tidak menyimpan, mencatat, atau mengirim password ke mana pun.
/usr/bin/osascript -e 'text returned of (display dialog "Service Admin: введите пароль администратора Mac, чтобы установить Homebrew.\\nEnter your Mac administrator password to install Homebrew." default answer "" with hidden answer with title "Service Admin" with icon caution buttons {"Cancel", "OK"} default button "OK")'
"""


def _write_askpass(log):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "askpass.sh")
    with open(path, "w") as f:
        f.write(ASKPASS)
    os.chmod(path, stat.S_IRWXU)
    log("Подготовлен диалог пароля администратора macOS.")


def _log_sha(path):
    def step(log):
        with open(path, "rb") as f:
            log(f"sha256 установщика: {hashlib.sha256(f.read()).hexdigest()}")
    return step


def _verify_brew(log):
    brew = _brew_path()
    if not brew:
        raise RuntimeError("Homebrew не найден после установки")
    _, out, _ = run([brew, "--version"], timeout=20)
    log(out.strip().splitlines()[0] if out.strip() else "brew ok")


def install(body):
    what = body.get("id")
    if what not in INSTALLABLE:
        raise ApiError("Неизвестный пункт подготовки", HTTPStatus.BAD_REQUEST, code="setup.unknown_item")
    st = {i["id"]: i for i in status()["items"]}[what]
    if st["installed"]:
        raise ApiError("Уже установлено", HTTPStatus.CONFLICT, code="setup.installed")
    if what == "clt":
        steps = [("xcode-select --install (диалог Apple)", ["/usr/bin/xcode-select", "--install"], {"optional": True}),
                 ("Ожидание установки", _wait_clt, {})]
        return {"job": start_steps("Command Line Tools", steps, "setup")}
    if not has_clt():
        raise ApiError("Сначала нужны Command Line Tools", HTTPStatus.CONFLICT, code="setup.need_clt")
    tmp = os.path.join(DATA_DIR, "tmp", "brew-install.sh")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    env = dict(ENV, NONINTERACTIVE="1", SUDO_ASKPASS=os.path.join(DATA_DIR, "askpass.sh"))
    steps = [("Диалог пароля администратора", _write_askpass, {}),
             ("Загрузка установщика Homebrew", ["/usr/bin/curl", "-fsSL", "-o", tmp, BREW_INSTALLER_URL], {}),
             ("Контрольная сумма установщика", _log_sha(tmp), {}),
             ("Установка Homebrew", ["/bin/bash", tmp], {"env": env}),
             ("Проверка", _verify_brew, {})]
    return {"job": start_steps("Homebrew", steps, "setup")}
