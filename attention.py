"""Центр внимания (Фаза 10, U6): короткий список того, что требует действия. Только чтение.
Дёшево по умолчанию (планы на подтверждение, место на диске, токены агентов); `?deep=1` добавляет медленное — упавшие сервисы brew и устаревшие пакеты
(оба кэшируются, чтобы шапка не дёргала brew каждую минуту). Каждый пункт: {id, level: warn|info, count?, text-ключ i18n, href}."""
import shutil
import sys
import threading
import time

TTL_SERVICES = 120
TTL_OUTDATED = 600
LOW_DISK_FRAC = 0.10
LOW_DISK_BYTES = 10 * 1024 ** 3
EXPIRY_DAYS = 7
_cache = {}
_lock = threading.Lock()


def _cached(key, ttl, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    try:
        val = fn()
    except Exception:  # noqa: BLE001 — медленная проверка не должна ломать центр внимания
        val = None
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def _services_errors():
    import brewsvc
    return [s["name"] for s in brewsvc.list_services() if str(s.get("status")) == "error"]


def _outdated():
    import brewsvc
    from core import BREW, run
    code, out, _ = run([BREW, "outdated", "--quiet"], env=brewsvc.RO_ENV, timeout=60)
    return [l for l in out.split() if l] if code == 0 else None


def attention(q=None):
    q = q or {}
    deep = q.get("deep") == "1"
    items = []
    import plans
    pending = plans.list_plans()["pending"]
    if pending:
        items.append({"id": "plans", "level": "warn", "count": pending, "key": "attn.plans", "href": "#connect:approvals"})
    du = shutil.disk_usage("/")
    if du.free < LOW_DISK_BYTES or du.free / du.total < LOW_DISK_FRAC:
        items.append({"id": "disk", "level": "warn", "count": round(du.free / 1024 ** 3, 1), "key": "attn.disk", "href": "#dashboard"})
    import agent_gateway
    now = time.time()
    soon = [a for a in agent_gateway.list_agents()["agents"] if not a.get("revoked") and a.get("expires") and now < a["expires"] < now + EXPIRY_DAYS * 86400]
    if soon:
        items.append({"id": "tokens", "level": "info", "count": len(soon), "key": "attn.tokens", "href": "#connect:agents"})
    if deep and sys.platform == "darwin":
        bad = _cached("services", TTL_SERVICES, _services_errors)
        if bad:
            items.append({"id": "services", "level": "warn", "count": len(bad), "names": bad[:5], "key": "attn.services", "href": "#packages"})
        old = _cached("outdated", TTL_OUTDATED, _outdated)
        if old:
            items.append({"id": "outdated", "level": "info", "count": len(old), "key": "attn.outdated", "href": "#packages"})
    return {"items": items, "warn": sum(1 for i in items if i["level"] == "warn"), "deep": deep}
