"""Terminal sungguhan di browser: sesi zsh di pseudo-terminal (PTY).

Output dibaca lewat long-poll (GET /api/pty/read), input dikirim lewat POST.
Karena punya TTY, program interaktif (claude, vim, htop, tinker, ssh) berjalan
normal. Sesi tetap hidup walau halaman di-refresh (output di-replay dari buffer)."""
import base64
import fcntl
import itertools
import os
import pty
import signal
import struct
import termios
import threading
import sys
import time
import warnings
from http import HTTPStatus

from core import ENV, HOME, ApiError

SESSIONS = {}
IDS = itertools.count(1)
LOCK = threading.Lock()
BUFFER_MAX = 2 * 1024 * 1024  # simpan 2 MB output terakhir per sesi
# pty.fork() di server multi-thread aman di sini karena anak langsung exec zsh
warnings.filterwarnings("ignore", message=".*multi-threaded.*fork", category=DeprecationWarning)


def _set_size(fd, cols, rows):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _reader(s):
    while True:
        try:
            data = os.read(s["fd"], 65536)
        except OSError:
            data = b""
        with s["cond"]:
            if not data:
                s["alive"] = False
                s["cond"].notify_all()
                break
            s["buf"] += data
            s["last"] = time.time()
            if len(s["buf"]) > BUFFER_MAX:
                cut = len(s["buf"]) - BUFFER_MAX
                del s["buf"][:cut]
                s["base"] += cut  # offset absolut byte pertama di buffer
            s["cond"].notify_all()
    try:
        _, status = os.waitpid(s["pid"], 0)
        s["code"] = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        pass
    try:
        os.close(s["fd"])
    except OSError:
        pass


def _shell():
    """macOS — zsh (как раньше). Linux — оболочка пользователя ($SHELL: bash/zsh/fish/sh), иначе /bin/bash."""
    if sys.platform == "darwin":
        return "zsh"
    cand = ENV.get("SHELL") or ""
    if cand and os.path.basename(cand) in ("bash", "zsh", "fish", "sh") and os.access(cand, os.X_OK):
        return cand
    return "/bin/bash"


def new_session(body):
    cwd = os.path.realpath(os.path.expanduser(str(body.get("cwd") or "~")))
    if not os.path.isdir(cwd):
        cwd = HOME
    cols = max(20, min(int(body.get("cols") or 100), 500))
    rows = max(5, min(int(body.get("rows") or 30), 200))
    command = str(body.get("command") or "").strip()
    env = {k: v for k, v in ENV.items() if k not in ("NO_COLOR", "CLICOLOR", "PAGER", "GIT_PAGER")}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", TERM_PROGRAM="ServiceAdmin", LANG=env.get("LANG", "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"))
    # login shell interaktif: memuat .zprofile + .zshrc (PATH, alias, nvm, Herd, ...)
    shell = _shell()
    argv = [shell, "-l", "-i"] + (["-c", f"{command}; exec {shell} -l -i"] if command else [])
    pid, fd = pty.fork()
    if pid == 0:  # proses anak
        try:
            os.chdir(cwd)
            os.execvpe(shell, argv, env)
        finally:
            os._exit(127)
    _set_size(fd, cols, rows)
    sid = str(next(IDS))
    s = {"id": sid, "pid": pid, "fd": fd, "buf": bytearray(), "base": 0, "alive": True, "code": None,
         "cond": threading.Condition(), "cwd": cwd, "title": command.split()[0] if command else os.path.basename(shell),
         "started": time.time(), "cols": cols, "rows": rows, "last": time.time()}
    with LOCK:
        SESSIONS[sid] = s
    threading.Thread(target=_reader, args=(s,), daemon=True).start()
    return {"id": sid, "title": s["title"]}


def _get(sid):
    s = SESSIONS.get(str(sid))
    if not s:
        raise ApiError("Сессия терминала не найдена", HTTPStatus.NOT_FOUND, code="pty.session_not_found")
    return s


def read(q):
    """Long-poll: kembalikan output sejak `offset` (menunggu maks ~20 detik)."""
    s = _get(q.get("id"))
    offset = int(q.get("offset") or 0)
    deadline = time.time() + 20
    with s["cond"]:
        while s["alive"] and s["base"] + len(s["buf"]) <= offset and time.time() < deadline:
            s["cond"].wait(timeout=deadline - time.time())
        start = max(offset, s["base"]) - s["base"]
        data = bytes(s["buf"][start:])
        end = s["base"] + len(s["buf"])
    return {"data": base64.b64encode(data).decode(), "offset": end, "alive": s["alive"], "code": s["code"],
            "truncated": offset < s["base"]}


def peek(q):
    """Intip output terakhir sesi TANPA long-poll dan tanpa mengubah offset —
    dipakai halaman AI Sessions untuk pratinjau (read-only)."""
    s = _get(q.get("id"))
    limit = max(1000, min(int(q.get("limit") or 8000), 200_000))
    with s["cond"]:
        total = len(s["buf"])
        data = bytes(s["buf"][-limit:])
    return {"data": base64.b64encode(data).decode(), "alive": s["alive"], "code": s["code"],
            "bytes": total, "truncated": total > limit}


def write(body):
    s = _get(body.get("id"))
    if not s["alive"]:
        raise ApiError("Сессия уже завершена", HTTPStatus.GONE, code="pty.session_ended")
    data = str(body.get("data", "")).encode()
    if len(data) > 1_000_000:
        raise ApiError("Слишком большой ввод", code="pty.input_too_large")
    view = memoryview(data)
    while view:  # tulis sampai habis (tempel teks panjang)
        n = os.write(s["fd"], view)
        view = view[n:]
    return {"ok": True}


def resize(body):
    s = _get(body.get("id"))
    cols = max(20, min(int(body.get("cols") or 80), 500))
    rows = max(5, min(int(body.get("rows") or 24), 200))
    if s["alive"] and (cols, rows) != (s["cols"], s["rows"]):
        _set_size(s["fd"], cols, rows)
        s["cols"], s["rows"] = cols, rows
        try:
            os.kill(s["pid"], signal.SIGWINCH)
        except ProcessLookupError:
            pass
    return {"ok": True}


def kill(body):
    s = _get(body.get("id"))
    if s["alive"]:
        try:
            os.killpg(os.getpgid(s["pid"]), signal.SIGHUP)
        except (ProcessLookupError, PermissionError):
            pass
    with LOCK:
        SESSIONS.pop(s["id"], None)
    return {"ok": True}


def list_sessions(q=None):
    return {"sessions": [{"id": s["id"], "title": s["title"], "alive": s["alive"], "cwd": s["cwd"],
                          "started": s["started"], "last": s.get("last"), "pid": s["pid"]} for s in sorted(SESSIONS.values(), key=lambda s: int(s["id"]))]}
