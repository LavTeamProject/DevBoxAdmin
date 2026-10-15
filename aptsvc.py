"""Пакеты apt на Linux (Фаза 6, Л3): те же формы ответов, что у brewsvc (страница «Пакеты»). Изменения — через elevate.run_admin."""
import re
from http import HTTPStatus

import elevate
from core import PKG_RE, ApiError, run

APT_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,99}$")


def _manual():
    return set(run(["apt-mark", "showmanual"], timeout=30)[1].split())


def _upgradable():
    out = run(["apt", "list", "--upgradable"], timeout=30)[1]
    res = {}
    for line in out.splitlines():
        m = re.match(r"^([^/\s]+)/\S+\s+(\S+)\s", line)
        if m:
            res[m[1]] = m[2]
    return res


def list_apps():
    manual = _manual()
    upg = _upgradable()
    out = run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${binary:Summary}\n"], timeout=30)[1]
    apps = []
    for line in out.splitlines():
        name, _, rest = line.partition("\t")
        ver, _, desc = rest.partition("\t")
        if name in manual:
            apps.append({"name": name, "type": "formula", "desc": desc, "version": ver, "latest": upg.get(name, ver), "outdated": name in upg,
                         "pinned": False, "on_request": True, "service": False, "homepage": None})
    return {"apps": sorted(apps, key=lambda a: a["name"])}


def search_apps(q):
    term = q.get("q", "").strip()
    if not PKG_RE.match(term):
        raise ApiError("Недопустимый поисковый запрос", code="srv.query_invalid")
    names = [n for n in run(["apt-cache", "search", "--names-only", term], timeout=30)[1].splitlines()]
    installed = set(run(["dpkg-query", "-W", "-f", "${Package}\n"], timeout=30)[1].split())
    out = []
    for line in names[:100]:
        n = line.split(" - ", 1)[0].strip()
        if APT_NAME.match(n):
            out.append({"name": n, "type": "formula", "installed": n in installed})
    return {"results": out}


ACTIONS = {"install": ["install", "-y"], "uninstall": ["remove", "-y"], "upgrade": ["install", "--only-upgrade", "-y"],
           "reinstall": ["install", "--reinstall", "-y"]}


def app_action(body):
    name, action = body.get("name", ""), body.get("action")
    if action == "upgrade-all":
        return elevate.run_admin("apt upgrade", ["apt-get", "upgrade", "-y"])
    if not APT_NAME.match(name):
        raise ApiError("Недопустимое имя пакета", code="srv.pkg_invalid")
    if action not in ACTIONS:
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    if action != "uninstall" and run(["apt-cache", "show", "--no-all-versions", name], timeout=20)[0] != 0:
        raise ApiError("Пакет не найден в индексах apt (возможно, нужен `sudo apt-get update`)", HTTPStatus.NOT_FOUND, code="srv.pkg_unknown")
    return elevate.run_admin(f"apt {action} {name}", ["apt-get", *ACTIONS[action], name])
