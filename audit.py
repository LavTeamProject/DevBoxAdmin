"""Jejak audit: setiap aksi yang mengubah sesuatu ditulis ke ~/.service-admin/audit.log (JSONL).

Dibutuhkan sebelum panel boleh memasang apa pun: tanpa ini tidak ada cara menjawab
"apa yang barusan dijalankan panel di mesin ini?". Halaman Audit (filter) menyusul di 2.2;
modul ini hanya MENULIS. Tidak pernah menyimpan rahasia: kunci bernama password/token/secret/
key/env dan isi file (content) disamarkan; URL dengan kredensial dibersihkan.
"""
import contextvars
import json
import os
import re
import threading
import time

from core import DATA_DIR

LOG = os.path.join(DATA_DIR, "audit.log")
MAX_BYTES = 2 * 1024 * 1024
KEEP = 3  # audit.log + audit.log.1 .. .2
_LOCK = threading.Lock()

SECRET_KEY = re.compile(r"pass|token|secret|key|auth|cookie|credential|env", re.I)
BULK_KEY = {"content", "text", "data", "input"}  # isi file / ketikan terminal: cukup panjangnya
URL_CRED = re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@")


def sanitize(value, key="", depth=0):
    if SECRET_KEY.search(key):
        return "***"
    if key in BULK_KEY and isinstance(value, str):
        return f"<{len(value)} chars>"
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {str(k): sanitize(v, str(k), depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, key, depth + 1) for v in value[:20]]
    if isinstance(value, str):
        value = URL_CRED.sub(r"\1***@", value)
        return value if len(value) <= 300 else value[:300] + "…"
    return value


def _rotate():
    for i in range(KEEP - 1, 0, -1):
        src = LOG if i == 1 else f"{LOG}.{i - 1}"
        if os.path.exists(src):
            os.replace(src, f"{LOG}.{i}")


INITIATOR = contextvars.ContextVar("initiator", default=None)  # кто инициировал: "panel" | "agent:<имя>" | "system:<что>"


def current_initiator():
    return INITIATOR.get()


def record(action, params=None, result="ok", duration_ms=0, code=None, extra=None):
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "action": action,
             "params": sanitize(params or {}), "result": str(result)[:200],
             "ms": int(duration_ms), "code": code}
    if extra:
        entry.update(sanitize(extra))
    if not entry.get("by"):  # явное by, затем агент из extra, затем контекст запроса, иначе — система
        entry["by"] = f"agent:{entry['agent']}" if entry.get("agent") else (INITIATOR.get() or "system")
    line = json.dumps(entry, ensure_ascii=False)
    with _LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_BYTES:
            _rotate()
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------- baca (halaman Audit)

def _files_oldest_first():
    return [f for f in [f"{LOG}.{i}" for i in range(KEEP - 1, 0, -1)] + [LOG] if os.path.exists(f)]


def read(q=None):
    """Entri audit terbaru dulu, dengan filter. Parameter (semua opsional):
    action (substring, tanpa huruf besar/kecil), result=ok|error, date_from / date_to (YYYY-MM-DD),
    limit (default 200, maks 1000), offset. Baris rusak dilewati, bukan error."""
    q = q or {}
    action = (q.get("action") or "").lower()
    result = q.get("result") or ""
    d_from, d_to = q.get("date_from") or "", q.get("date_to") or ""
    by = q.get("by") or ""
    try:
        limit = max(1, min(int(q.get("limit") or 200), 1000))
        offset = max(0, int(q.get("offset") or 0))
    except ValueError:
        limit, offset = 200, 0
    matched, actions, initiators = [], set(), set()
    with _LOCK:
        paths = _files_oldest_first()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(e, dict):
                        continue
                    if not isinstance(e.get("by"), str) or not e["by"]:  # старые/битые записи: агент по полю agent, остальное — панель
                        e["by"] = f"agent:{e['agent']}" if isinstance(e.get("agent"), str) and e["agent"] else "panel"
                    initiators.add(e["by"])
                    actions.add(e.get("action", ""))
                    day = str(e.get("ts", ""))[:10]
                    failed = e.get("result") not in ("ok", "done") or (e.get("code") not in (None, 0, 200))
                    if action and action not in str(e.get("action", "")).lower():
                        continue
                    if result == "ok" and failed or result == "error" and not failed:
                        continue
                    if by and (e["by"] != by and not (by == "agent" and e["by"].startswith("agent:"))):
                        continue
                    if d_from and day < d_from or d_to and day > d_to:
                        continue
                    e["failed"] = failed
                    matched.append(e)
        except OSError:
            continue
    matched.reverse()
    return {"entries": matched[offset:offset + limit], "total": len(matched),
            "actions": sorted(a for a in actions if a), "initiators": sorted(initiators), "limit": limit, "offset": offset}
