"""Порты: кто слушает какой TCP-порт (Фаза 10). Только чтение — без «убить процесс». Через `lsof` (macOS/Linux); имя команды, не командная строка (в ней бывают секреты)."""
import shutil

from core import output

WELL_KNOWN = {80: "HTTP", 443: "HTTPS", 3000: "dev server", 3306: "MySQL", 5000: "dev server", 5173: "Vite", 5432: "PostgreSQL", 5672: "RabbitMQ", 6379: "Redis",
              8000: "dev server", 8025: "Mailpit (интерфейс)", 8080: "HTTP alt", 8765: "Service Admin", 9000: "MinIO", 11211: "Memcached", 27017: "MongoDB", 1025: "Mailpit (SMTP)"}


def parse_lsof(text):
    """Вывод `lsof -F pcLn` → [{port, addr, pid, cmd, user}], без повторов (IPv4/IPv6 одного сокета схлопываются)."""
    rows, cur, seen = [], {}, set()
    for line in text.splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            cur = {"pid": int(val) if val.isdigit() else None}
        elif tag == "c":
            cur["cmd"] = val
        elif tag == "L":
            cur["user"] = val
        elif tag == "n" and ":" in val:
            addr, _, port = val.rpartition(":")
            if not port.isdigit():
                continue
            key = (cur.get("pid"), int(port))
            if key in seen:
                continue
            seen.add(key)
            rows.append({"port": int(port), "addr": addr.strip("[]") or "*", "pid": cur.get("pid"), "cmd": cur.get("cmd", "?"), "user": cur.get("user", "")})
    rows.sort(key=lambda r: (r["port"], r["pid"] or 0))
    for r in rows:
        r["label"] = "AirPlay (macOS)" if r["cmd"] == "ControlCenter" and r["port"] in (5000, 7000) else WELL_KNOWN.get(r["port"])
        r["local_only"] = r["addr"] in ("127.0.0.1", "::1", "localhost")
    return rows


def listening(q=None):
    """GET /api/ports → {ports: [{port, addr, pid, cmd, user, label, local_only}], available}."""
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    out = output([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pcLn"], timeout=20)
    return {"ports": parse_lsof(out), "available": bool(out) or shutil.which("lsof") is not None}
