# -*- coding: utf-8 -*-
"""Дерево боковой панели (Фаза 10, меню в стиле FlyEnv): установленные сервисы по группам с состоянием «запущен / остановлен».
Только чтение; список сервисов дорогой (`brew services info --all`), поэтому кэшируется на 20 с."""
import re
import sys
import threading
import time

TTL = 20
_cache = {"t": 0.0, "data": None}
_lock = threading.Lock()

GROUPS = (   # (id, шаблон имени)
    ("web", re.compile(r"^(nginx|httpd|apache2?|caddy|php(@[\d.]+)?(-fpm)?|php[\d.]+-fpm|tomcat\d*|traefik|lighttpd|frankenphp)$")),
    ("db", re.compile(r"^(mysql(@[\d.]+)?|mariadb(@[\d.]+)?|postgresql(@\d+)?|mongodb(-community)?(@[\d.]+)?|mongod|neo4j|influxdb|clickhouse|cassandra|couchdb)$")),
    ("cache", re.compile(r"^(redis(-server)?|valkey|memcached|rabbitmq(-server)?|kafka|nats-server|mosquitto)$")),
)
OTHER_LINUX = re.compile(r"^(dnsmasq|cloudflared|grafana(-server)?|prometheus|ollama|mailpit|minio|meilisearch|etcd|docker|containerd|elasticsearch|opensearch)$")


def group_of(name, linux=False):
    """Группа сервиса по имени: web | db | cache | other | None (на Linux системные юниты вроде dbus не показываем)."""
    base = name.split("/")[-1]
    for gid, rx in GROUPS:
        if rx.match(base):
            return gid
    if linux:
        return "other" if OTHER_LINUX.match(base) else None
    return "other"


def _services():
    import brewsvc
    return brewsvc.list_services()


def nav_services(q=None):
    """GET /api/nav-services → {"groups": {"web": [{name, running, status}], "db": …, "cache": …, "other": …}}."""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["t"] < TTL and not (q or {}).get("refresh"):
            return _cache["data"]
    linux = sys.platform != "darwin"
    groups = {"web": [], "db": [], "cache": [], "other": []}
    try:
        items = _services()
    except Exception:  # noqa: BLE001 — нет brew/systemd: меню просто без сервисов
        items = []
    for s in items:
        g = group_of(s.get("name", ""), linux)
        if g:
            groups[g].append({"name": s["name"], "running": bool(s.get("running")), "status": str(s.get("status") or "")})
    for g in groups.values():
        g.sort(key=lambda x: x["name"])
    data = {"groups": groups}
    with _lock:
        _cache.update(t=time.time(), data=data)
    return data


def invalidate():
    with _lock:
        _cache["data"] = None
