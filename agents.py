"""AI Sessions: pemantauan sesi agen (Claude Code, Codex, OpenCode, Gemini, Aider).

FASE 1 — HANYA MEMANTAU. Modul ini tidak menjalankan, menghentikan, atau
mengubah apa pun: ia membaca daftar proses (`ps`), memetakannya ke sesi PTY
yang sudah ada, dan menghitung pemakaian CPU/RAM per sesi. Tombol
"jalankan / hentikan agen" menyusul di fase berikutnya.

Pemetaan sesi: tiap sesi PTY punya pid shell. Proses agen yang merupakan
turunan pid itu (langsung atau lewat beberapa tingkat) dianggap milik sesi
tersebut. Agen yang tidak berasal dari sesi mana pun tetap ditampilkan
di grup "mandiri" — supaya sesi yang dijalankan dari Terminal.app tetap terlihat.
"""
import base64
import os
import re
import shutil
import time

import ptyterm
from core import ENV, ps_snapshot, pid_tree_stats, run

# nama binary -> perintah versi (dipakai juga untuk cek ketersediaan)
AGENTS = [
    {"key": "claude", "bin": "claude"},
    {"key": "codex", "bin": "codex"},
    {"key": "opencode", "bin": "opencode"},
    {"key": "gemini", "bin": "gemini"},
    {"key": "aider", "bin": "aider"},
    {"key": "cursor-agent", "bin": "cursor-agent"},
]
AGENT_KEYS = {a["key"] for a in AGENTS}
SHELLS = {"zsh", "bash", "sh", "fish", "dash", "login"}
# dipisah agar `grep claude` / `ps aux | grep claude` tidak ikut terhitung sebagai sesi
TOKEN_RE = re.compile(r"(?:^|[\s/])(claude|codex|opencode|gemini|aider|cursor-agent)(?:\s|$)")
NOISE = ("grep", "rg ", "pgrep", "ps -", "ps aux", "less ", "tail ", "head ", "watch ")
CACHE_TTL = 5
_cache = {"t": 0.0, "data": None}


def _read_ps():
    """Snapshot proses lengkap: pid -> dict(ppid, cpu, rss, etime, command).
    Mengembalikan {} kalau `ps` tidak bisa dijalankan — halaman tetap tampil."""
    try:
        _, out, _ = run(["ps", "-Ao", "pid=,ppid=,pcpu=,rss=,etime=,command="])
    except OSError:
        return {}
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, cpu, rss, etime, command = parts
        try:
            procs[pid] = {"pid": pid, "ppid": ppid, "cpu": float(cpu), "rss": int(rss),
                          "etime": etime, "command": command}
        except ValueError:
            continue
    return procs


def _agent_of(command):
    """Kunci agen kalau command ini benar-benar menjalankan agen."""
    if any(n in command[:48] for n in NOISE):
        return None
    for token in command.split()[:3]:
        if os.path.basename(token) in AGENT_KEYS:
            return os.path.basename(token)
    m = TOKEN_RE.search(command)
    return m[1] if m else None


def _ancestors(procs, pid, limit=12):
    chain, seen, current = [], set(), pid
    while current in procs and current not in seen and len(chain) < limit:
        seen.add(current)
        chain.append(current)
        current = procs[current]["ppid"]
    return chain


def _shell_of(procs, ancestors):
    """pid shell terdekat di rantai leluhur (untuk agen yang jalan di luar panel)."""
    for pid in ancestors:
        cmd = (procs.get(pid) or {}).get("command") or ""
        first = cmd.split()[0] if cmd.split() else ""
        # login shell muncul sebagai "-zsh"
        if os.path.basename(first).lstrip("-") in SHELLS:
            return pid
    return None


def known_agents():
    """Agen yang benar-benar terpasang di PATH server (tanpa menjalankan apa pun)."""
    found = []
    for agent in AGENTS:
        path = shutil.which(agent["bin"], path=ENV["PATH"])
        if path:
            found.append({"key": agent["key"], "bin": agent["bin"], "path": path})
    return found


def sessions_info(q=None):
    """Sesi AI + sesi terminal biasa + proses agen mandiri. Read-only."""
    with_preview = bool(q and q.get("preview") == "1")
    fresh = bool(q and q.get("fresh") == "1")  # задачи агентов: только что запущенная сессия должна быть видна сразу
    if not with_preview and not fresh and _cache["data"] and time.time() - _cache["t"] < CACHE_TTL:
        return _cache["data"]

    procs = _read_ps()
    snapshot = ps_snapshot()
    pty = {s["id"]: s for s in ptyterm.list_sessions()["sessions"]}

    agents = []
    for pid, p in procs.items():
        key = _agent_of(p["command"])
        if not key:
            continue
        agents.append({"pid": pid, "agent": key, "command": p["command"], "cpu": p["cpu"],
                       "mem_mb": round(p["rss"] / 1024, 1), "uptime": p["etime"],
                       "ancestors": _ancestors(procs, pid)})

    sessions, used_pids = [], set()
    for sid, s in sorted(pty.items(), key=lambda kv: int(kv[0])):
        root = str(s.get("pid"))
        mine = [a for a in agents if root in a["ancestors"]]
        used_pids |= {a["pid"] for a in mine}
        stats = pid_tree_stats([root], snapshot=snapshot).get(root, {})
        item = {"id": sid, "title": s.get("title"), "cwd": s.get("cwd"), "alive": s.get("alive"),
                "started": s.get("started"), "kind": "agent" if mine else "terminal",
                "agents": [{k: v for k, v in a.items() if k != "ancestors"} for a in mine],
                "cpu": stats.get("cpu", 0), "mem_mb": stats.get("mem_mb", 0),
                "uptime": stats.get("uptime"), "procs": stats.get("procs", 0)}
        if mine:
            item["agent"] = mine[0]["agent"]
        if with_preview:
            try:
                p = ptyterm.peek({"id": sid, "limit": 4000})
                item["preview"] = base64.b64decode(p["data"]).decode("utf-8", "replace")[-2000:]
            except Exception:  # noqa: BLE001
                item["preview"] = None
        sessions.append(item)

    # agen yang tidak terkait sesi PTY (dijalankan dari Terminal.app, launchd, dll.)
    standalone = []
    for a in agents:
        if a["pid"] in used_pids:
            continue
        standalone.append({"pid": a["pid"], "agent": a["agent"], "command": a["command"],
                           "cpu": a["cpu"], "mem_mb": a["mem_mb"], "uptime": a["uptime"],
                           "shell_pid": _shell_of(procs, a["ancestors"])})

    data = {
        "sessions": sessions,
        "standalone": standalone,
        "installed": known_agents(),
        "procs_available": bool(procs),
        "summary": {
            "sessions": len(sessions),
            "agent_sessions": len([s for s in sessions if s["kind"] == "agent"]),
            "standalone": len(standalone),
            "cpu": round(sum(s["cpu"] for s in sessions) + sum(a["cpu"] for a in standalone), 1),
            "mem_mb": round(sum(s["mem_mb"] for s in sessions) + sum(a["mem_mb"] for a in standalone), 1),
        },
        "readonly": True,
    }
    if not with_preview:
        _cache.update(t=time.time(), data=data)
    return data
