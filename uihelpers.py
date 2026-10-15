"""Вспомогательные действия интерфейса: боковая панель (версии, Docker, Herd), чтение файла для диагностики, открыть Terminal /
Activity Monitor, детали проекта. Вынесено из server.py; server.py остаётся маршрутизацией HTTP.
"""
import os
import plistlib
import re
import shutil
import sys
import subprocess
from http import HTTPStatus

import core
import dockerx
import files
import gitops
import herdphp
import projects
import runtimes
from core import HOME, ApiError, run


def project_detail_w(q):
    """detail проекта + точный список файлов для действий записи (gitops.files_state)."""
    d = projects.project_detail(q)
    try:
        d["files_w"] = gitops.files_state(d["path"])[:gitops.MAX_FILES]
    except ApiError:
        d["files_w"] = None
    return d


def expand(p):
    p = p.strip().strip('"\'')
    p = re.sub(r"^~(?=/|$)", HOME, p)
    return re.sub(r"\$\{?HOME\}?", HOME, p)


def diagnose(content):
    """Peringatan sederhana: PATH/source ke folder yang tidak ada, baris dobel."""
    issues, seen = [], {}
    for no, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            issues.append({"line": no, "msg": f"Дубликат строки {seen[line]}"})
        else:
            seen[line] = no
        m = re.match(r"(?:export\s+)?PATH=(.+)", line)
        if m:
            for part in m[1].strip('"\'').split(":"):
                if "PATH" in part or "$(" in part:
                    continue
                d = expand(part)
                if "$" not in d and d and not os.path.isdir(d):
                    issues.append({"line": no, "msg": f"Папки из PATH не существует: {d}"})
        m = re.match(r"(?:source|\.)\s+([^\s;&|]+)", line)
        if m and "$(" not in m[1]:
            f = expand(m[1])
            if "$" not in f and not os.path.exists(f):
                issues.append({"line": no, "msg": f"Подключаемого через source файла не существует: {f}"})
    return issues


def file_read(q):
    data = files.read_file(q)
    if data["validator"] == "zsh":
        data["issues"] = diagnose(data["content"])  # PATH/source ke folder yang tidak ada, baris dobel
    return data


TERMINAL_APPS = {
    "terminal": ("Terminal", ["/System/Applications/Utilities/Terminal.app", "/Applications/Utilities/Terminal.app"]),
    "iterm": ("iTerm", ["/Applications/iTerm.app"]),
    "warp": ("Warp", ["/Applications/Warp.app"]),
    "ghostty": ("Ghostty", ["/Applications/Ghostty.app"]),
}


LINUX_TERMINALS = ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "kitty", "alacritty", "xterm")


def _linux_terminal():
    import platform_info
    if not platform_info.info()["gui"]:
        return None
    return next((n for n in LINUX_TERMINALS if shutil.which(n, path=core.ENV["PATH"])), None)


def terminal_apps(q=None):
    if sys.platform != "darwin":
        name = _linux_terminal()
        return {"apps": [{"id": "terminal", "name": name}] if name else []}
    return {"apps": [{"id": k, "name": n} for k, (n, paths) in TERMINAL_APPS.items() if any(os.path.exists(p) for p in paths)]}


def open_in_terminal(body):
    """Jalankan perintah interaktif (claude, vim, ssh, tinker, ...) di aplikasi terminal sungguhan (punya TTY)."""
    import shlex
    command = str(body.get("command", "")).strip()
    cwd = os.path.realpath(os.path.expanduser(str(body.get("cwd") or "~")))
    if not os.path.isdir(cwd):
        cwd = HOME
    app = body.get("app") if body.get("app") in TERMINAL_APPS else "terminal"
    if app not in [a["id"] for a in terminal_apps()["apps"]]:
        app = "terminal"
    line = f"cd {shlex.quote(cwd)}" + (f" && {command}" if command else "")
    if sys.platform != "darwin":
        name = _linux_terminal()
        if not name:
            raise ApiError("Нет графической сессии или эмулятора терминала: используйте терминал панели", HTTPStatus.CONFLICT, code="platform.unsupported")
        exe = shutil.which(name, path=core.ENV["PATH"])
        script = line + "; exec bash"
        lead = {"gnome-terminal": ["--"], "xfce4-terminal": ["-x"], "kitty": []}.get(name, ["-e"])  # у каждого эмулятора свой способ передать команду
        argv = [exe, *lead, "bash", "-c", script]
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=core.ENV)
        return {"ok": True, "app": name, "pasted": False}
    # perintah dikirim sebagai argumen (argv), bukan disisipkan ke teks AppleScript
    scripts = {
        "terminal": 'on run argv\n tell application "Terminal"\n  activate\n  do script (item 1 of argv)\n end tell\nend run',
        "iterm": ('on run argv\n tell application "iTerm"\n  activate\n  set w to (create window with default profile)\n'
                  '  tell current session of w to write text (item 1 of argv)\n end tell\nend run'),
    }
    if app in scripts:
        code, out, err = run(["osascript", "-e", scripts[app], line], timeout=20)
        if code != 0:
            raise ApiError(err.strip() or "Не удалось открыть терминал", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.terminal_open_failed")
        return {"ok": True, "app": TERMINAL_APPS[app][0], "pasted": False}
    # Warp/Ghostty: buka tab baru di folder tsb; perintah disalin ke clipboard untuk ditempel (⌘V)
    if command:
        subprocess.run(["pbcopy"], input=command, text=True, timeout=5)
    if app == "warp":
        from urllib.parse import quote
        run(["open", f"warp://action/new_tab?path={quote(cwd)}"], timeout=10)
    else:
        run(["open", "-na", "Ghostty", "--args", f"--working-directory={cwd}"], timeout=10)
    return {"ok": True, "app": TERMINAL_APPS[app][0], "pasted": bool(command)}


def open_activity_monitor(body):
    """Buka Activity Monitor; kalau belum jalan, pilih tab-nya dulu (CPU/Memori/Energi/Disk/Jaringan)."""
    if sys.platform != "darwin":
        raise ApiError("Мониторинг системы macOS недоступен на этой системе", HTTPStatus.CONFLICT, code="platform.unsupported")
    tab = {"cpu": 0, "mem": 1, "energy": 2, "disk": 3, "network": 4}.get(body.get("tab"), 0)
    running = run(["pgrep", "-x", "Activity Monitor"], timeout=5)[0] == 0
    if not running:
        run(["defaults", "write", "com.apple.ActivityMonitor", "SelectedTab", "-int", str(tab)], timeout=5)
    code, out, err = run(["open", "-a", "Activity Monitor"], timeout=10)
    if code != 0:
        raise ApiError(err.strip() or "Не удалось открыть Мониторинг системы", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.actmon_open_failed")
    return {"ok": True, "was_running": running}


def nav_info(q):
    """Versi & status untuk sidebar: bahasa terdeteksi + Docker + Herd."""
    data = dict(runtimes.detect(q.get("refresh") == "1"))
    docker = None
    DOCKER = dockerx.DOCKER
    if os.path.exists(DOCKER):
        try:
            code, out, _ = run([DOCKER, "info", "--format", "{{.ServerVersion}}"], timeout=4)
        except subprocess.TimeoutExpired:
            code, out = 1, ""
        client = re.search(r"\d+\.\d+(\.\d+)?", run([DOCKER, "--version"], timeout=5)[1])
        docker = {"running": code == 0 and bool(out.strip()),
                  "version": out.strip() if code == 0 and out.strip() else (client[0] if client else None)}
    herd_state = None
    plist = "/Applications/Herd.app/Contents/Info.plist"
    if os.path.exists(plist):
        with open(plist, "rb") as f:
            version = plistlib.load(f).get("CFBundleShortVersionString")
        p = herdphp.herd_processes()
        herd_state = {"version": version, "running": bool(p["nginx"] and p["fpm"])}
    return {**data, "docker": docker, "herd": herd_state}
