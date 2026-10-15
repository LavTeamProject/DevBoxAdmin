"""Каналы подтверждения действий агентов человеком (Фаза 6, Л2; ADR-0001). Единственное место, откуда panel спрашивает человека.
  macOS            системный диалог osascript (кнопка по умолчанию «Отклонить», таймаут = отказ);
  Linux, канал A   диалог zenity/kdialog в графической сессии пользователя (абсолютные пути из системных каталогов, не из PATH);
  Linux, канал B   без экрана: человек выполняет `service-admin approve` → pkexec → корневой помощник пишет решение, которое панель принимает,
                   только если файл принадлежит root, не доступен другим на запись и совпадает по id/nonce/digest/сроку.
Нет подходящего канала (или он небезопасен: passwordless-sudo, root-эквивалентные группы) → "unavailable": планы агентов не исполняются (fail closed)."""
import grp
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time

import platform_info
from core import DATA_DIR

OSASCRIPT = "/usr/bin/osascript"
DIALOG_SECONDS = 110
HELPER = "/usr/local/libexec/service-admin-approve"
DEC_ROOT = "/var/lib/service-admin/approvals"
POLICY = "/usr/share/polkit-1/actions/local.service-admin.approve.policy"
SUDOERS = "/etc/sudoers.d/service-admin-approve"
REQ_DIR = os.path.join(DATA_DIR, "approvals")
HELPER_SECONDS = 150          # человеку нужно время, чтобы открыть терминал и ввести пароль
ROOT_EQUIVALENT_GROUPS = ("docker", "lxd", "incus", "incus-admin", "libvirt", "disk", "root")
_CACHE = {"t": 0.0, "v": []}
SYSTEM_BIN = ("/usr/bin", "/usr/local/bin", "/bin")
_ROOT_UID = 0                 # переопределяется только в тестах
_RID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _abs_tool(*names):
    for n in names:
        for d in SYSTEM_BIN:
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def _unsafe_reasons():
    """Почему канал B небезопасен для этого пользователя (агент мог бы одобрять сам)."""
    reasons = []
    if _CACHE["t"] and time.time() - _CACHE["t"] < 60:
        return list(_CACHE["v"])
    try:  # абсолютный путь и минимальное окружение: подмена sudo через PATH не должна скрыть passwordless-sudo
        if subprocess.run(["/usr/bin/sudo", "-n", "true"], capture_output=True, timeout=5, stdin=subprocess.DEVNULL,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C"}).returncode == 0:
            reasons.append("passwordless_sudo")
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import pwd
        me = pwd.getpwuid(os.getuid())
        mine = {grp.getgrgid(g).gr_name for g in set(os.getgrouplist(me.pw_name, me.pw_gid)) | set(os.getgroups())}
        bad = sorted(mine & set(ROOT_EQUIVALENT_GROUPS))
        if bad:
            reasons.append("root_equivalent_groups:" + ",".join(bad))
    except (KeyError, OSError):
        pass
    if _polkit_yes_rule():
        reasons.append("polkit_rule_without_password")
    _CACHE.update(t=time.time(), v=list(reasons))
    return reasons


def _polkit_yes_rule():
    """Правило polkit, которое выдаёт YES без пароля (для wheel/sudo или всем): тогда pkexec не требует пароля, и агент одобрил бы сам."""
    for d in ("/etc/polkit-1/rules.d", "/usr/share/polkit-1/rules.d"):
        try:
            for fn in os.listdir(d):
                if fn.endswith(".rules"):
                    with open(os.path.join(d, fn), encoding="utf-8", errors="replace") as f:
                        txt = f.read()
                    if "polkit.Result.YES" in txt and ("local.service-admin" in txt or ("action.id" not in txt and "action.lookup" not in txt)):
                        return True  # правило прямо про наше действие или YES для любого действия без фильтра
        except OSError:
            continue
    return False


def _gui_spoofable():
    """X11 (любой клиент может синтезировать ввод) или группа input (uinput/ydotool): диалог не защищает от агента того же пользователя."""
    try:
        wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or any(re.fullmatch(r"wayland-\d+", n) for n in os.listdir(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"))
        in_input = "input" in {grp.getgrgid(g).gr_name for g in os.getgroups()}
    except (OSError, KeyError):
        return True
    return (not wayland) or in_input


def _helper_ready():
    try:
        st = os.lstat(HELPER)
        return stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022 \
            and os.path.isdir(os.path.join(DEC_ROOT, str(os.getuid()))) \
            and (os.path.exists(SUDOERS) or (os.path.exists(POLICY) and platform_info._has_sys("pkexec")))  # noqa: SLF001
    except OSError:
        return False


def channel():
    """→ {"name": "macos_dialog"|"gui_dialog"|"root_helper"|None, "unsafe": [...], "detail": ...}"""
    if sys.platform == "darwin":
        return {"name": "macos_dialog" if os.path.exists(OSASCRIPT) else None, "unsafe": []}
    if not sys.platform.startswith("linux"):
        return {"name": None, "unsafe": []}
    gui_ok = platform_info.info()["gui"] and _abs_tool("zenity", "kdialog")
    if gui_ok and not (_gui_spoofable() and _helper_ready() and not _unsafe_reasons()):
        return {"name": "gui_dialog", "unsafe": [], "spoofable": _gui_spoofable()}
    if _helper_ready():
        unsafe = _unsafe_reasons()
        return {"name": None if unsafe else "root_helper", "unsafe": unsafe, "detail": "helper installed" if unsafe else None}
    return {"name": None, "unsafe": [], "detail": "no channel: no graphical session with zenity/kdialog, and the root helper is not installed"}


# ---------------------------------------------------------------- macOS

def _macos(text, d):
    script = ('on run argv\n display dialog (item 1 of argv) with title (item 2 of argv) '
              'buttons {(item 3 of argv), (item 4 of argv)} default button (item 3 of argv) cancel button (item 3 of argv) with icon caution '
              f'giving up after {DIALOG_SECONDS}\nend run')
    try:
        r = subprocess.run([OSASCRIPT, "-e", script, text, d["title"], d["reject"], d["approve"]],
                           capture_output=True, text=True, timeout=DIALOG_SECONDS + 15)
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if r.returncode != 0:
        return "reject" if "-128" in r.stderr or "User canceled" in r.stderr else "unavailable"
    return "approve" if f"button returned:{d['approve']}" in r.stdout and "gave up:false" in r.stdout else "reject"


# ---------------------------------------------------------------- Linux, канал A

def _gui_env():
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
                                                         "DBUS_SESSION_BUS_ADDRESS")}
    rt = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not env.get("WAYLAND_DISPLAY"):
        for n in sorted(os.listdir(rt)) if os.path.isdir(rt) else []:
            if re.fullmatch(r"wayland-\d+", n):
                env["WAYLAND_DISPLAY"] = n
                break
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY") and os.path.exists("/tmp/.X11-unix/X0"):
        env["DISPLAY"] = ":0"
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={rt}/bus")
    return env


def _gui(text, d):
    zenity, kdialog = _abs_tool("zenity"), _abs_tool("kdialog")
    if zenity:
        cmd = [zenity, "--question", "--no-markup", "--title", d["title"], "--text", text, "--ok-label", d["approve"], "--cancel-label", d["reject"],
               "--timeout", str(DIALOG_SECONDS), "--width", "560"]
        ok = lambda rc: "approve" if rc == 0 else ("reject" if rc in (1, 5) else "unavailable")  # noqa: E731 - 5 = таймаут → отказ
    elif kdialog:
        cmd = [kdialog, "--title", d["title"], "--warningyesno", text, "--yes-label", d["approve"], "--no-label", d["reject"]]
        ok = lambda rc: "approve" if rc == 0 else ("reject" if rc == 1 else "unavailable")  # noqa: E731
    else:
        return "unavailable"
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=DIALOG_SECONDS + 15, env=_gui_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "reject"
    except OSError:
        return "unavailable"
    return ok(r.returncode)


# ---------------------------------------------------------------- Linux, канал B

def _write_request(rid, text, lang):
    os.makedirs(REQ_DIR, mode=0o700, exist_ok=True)
    os.chmod(REQ_DIR, 0o700)
    req = {"id": rid, "uid": os.getuid(), "nonce": secrets.token_hex(16), "expires": time.time() + HELPER_SECONDS, "text": text[:4000], "lang": lang}
    raw = json.dumps(req, ensure_ascii=False)
    path = os.path.join(REQ_DIR, rid + ".req.json")
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(raw)
    os.replace(path + ".tmp", path)
    return req, path, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_decision(req, digest, dec_root=DEC_ROOT):
    """→ "approve" | "reject" | None (решения нет или оно не годится). Принимает ТОЛЬКО файл root, недоступный другим на запись."""
    d = os.path.join(dec_root, str(req["uid"]))
    path = os.path.join(d, f"{req['id']}.{req['nonce']}.dec.json")
    try:
        ds, fs = os.lstat(d), os.lstat(path)
    except OSError:
        return None
    for st in (ds, fs):
        if st.st_uid != _ROOT_UID or st.st_mode & 0o022 or stat.S_ISLNK(st.st_mode):
            return None
    if not stat.S_ISREG(fs.st_mode) or fs.st_size > 4096:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if (data.get("id"), data.get("nonce"), data.get("digest"), data.get("uid")) != (req["id"], req["nonce"], digest, req["uid"]):
        return None
    if time.time() > float(data.get("expires", 0)) + 5 or data.get("decision") not in ("approve", "reject"):
        return None
    return data["decision"]


def _root_helper(text, lang, rid):
    if not _RID.match(rid):
        return "unavailable"
    req, path, digest = _write_request(rid, text, lang)
    try:
        deadline = time.time() + HELPER_SECONDS
        while time.time() < deadline:
            res = verify_decision(req, digest)
            if res:
                return res
            time.sleep(1)
        return "reject"  # человек не ответил — отказ
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- вход

def ask(text, dialog_text, lang, rid):
    """→ "approve" | "reject" | "unavailable". rid — id плана или direct-<случайный> для прямых вызовов панели."""
    ch = channel()["name"]
    if ch == "macos_dialog":
        return _macos(text, dialog_text)
    if ch == "gui_dialog":
        return _gui(text, dialog_text)
    if ch == "root_helper":
        return _root_helper(text, lang, rid)
    return "unavailable"


def pending_requests():
    """Запросы, ожидающие человека (для `service-admin approve` без аргументов)."""
    out = []
    try:
        for fn in sorted(os.listdir(REQ_DIR)):
            if fn.endswith(".req.json"):
                with open(os.path.join(REQ_DIR, fn), encoding="utf-8") as f:
                    r = json.load(f)
                if float(r.get("expires", 0)) > time.time():
                    out.append(r["id"])
    except (OSError, ValueError, KeyError):
        pass
    return out
