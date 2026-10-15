"""Службы и приложения Homebrew: `brew services` (список, действия, журнал) и пакеты (список, поиск, действия).

Вынесено из server.py: страницы и агенты вызывают одни и те же функции (изменения пакетов исполняет `operations.run_package`).
Только стандартная библиотека; команды — списком аргументов, без shell.
"""
import json
import sys
from http import HTTPStatus

import aptsvc
import operations
import systemdsvc
from core import BREW, PKG_RE, ApiError, loads_or, pid_tree_stats, run, tail


SERVICE_ACTIONS = {"start", "stop", "restart", "run", "kill"}


def list_services():
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return systemdsvc.list_services()
    code, out, err = run([BREW, "services", "info", "--all", "--json"])
    if code != 0:
        raise ApiError(err.strip() or "Ошибка brew services", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.brew_services_failed")
    services = loads_or(out, [])  # без единого сервиса brew печатает пустой вывод, а не []
    stats = process_stats([str(s["pid"]) for s in services if s.get("pid")])
    for s in services:
        s.update(stats.get(str(s.get("pid")), {}))
    return services


def process_stats(pids):
    """CPU %, memori (MB) dan uptime per service, termasuk child process
    (mis. mysqld_safe -> mysqld)."""
    return pid_tree_stats(pids)


def known_service(name):
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return systemdsvc.known_service(name)
    svc = next((s for s in list_services() if s["name"] == name), None)
    if not svc:
        raise ApiError("Неизвестный сервис", HTTPStatus.NOT_FOUND, code="srv.service_unknown")
    return svc


def service_action(body):
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return systemdsvc.service_action(body)
    name, action = body.get("name", ""), body.get("action", "")
    if action not in SERVICE_ACTIONS:
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    known_service(name)
    code, out, err = run([BREW, "services", action, name], timeout=120)
    if code != 0:
        raise ApiError((out + err).strip() or "Ошибка", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if (out + err).strip() else "srv.failed")
    return {"ok": True, "output": (out + err).strip()}


def service_logs(q):
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return systemdsvc.service_logs(q)
    svc = known_service(q.get("name", ""))
    same = svc.get("error_log_path") == svc.get("log_path")
    return {"log": tail(svc.get("log_path")),
            "error_log": None if same else tail(svc.get("error_log_path")),
            "log_path": svc.get("log_path"), "error_log_path": svc.get("error_log_path")}


def list_apps():
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return aptsvc.list_apps()
    code, out, err = run([BREW, "info", "--json=v2", "--installed"], timeout=120)
    if code != 0:
        raise ApiError(err.strip() or "Ошибка brew info", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.brew_info_failed")
    data = json.loads(out)
    formulae = [{
        "name": f["name"], "type": "formula", "desc": f.get("desc") or "",
        "version": ", ".join(i["version"] for i in f.get("installed", [])),
        "latest": (f.get("versions") or {}).get("stable"),
        "outdated": bool(f.get("outdated")), "pinned": bool(f.get("pinned")),
        "on_request": any(i.get("installed_on_request") for i in f.get("installed", [])),
        "service": bool(f.get("service")), "homepage": f.get("homepage"),
    } for f in data.get("formulae", [])]
    casks = [{
        "name": c["token"], "type": "cask", "desc": c.get("desc") or ", ".join(c.get("name") or []),
        "version": c.get("installed") or "", "latest": c.get("version"),
        "outdated": bool(c.get("outdated")), "pinned": False, "on_request": True,
        "service": False, "homepage": c.get("homepage"),
    } for c in data.get("casks", [])]
    return {"apps": formulae + casks}


def search_apps(q):
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return aptsvc.search_apps(q)
    term = q.get("q", "").strip()
    if not PKG_RE.match(term):
        raise ApiError("Недопустимый поисковый запрос", code="srv.query_invalid")
    results = []
    for kind, flag in (("formula", "--formula"), ("cask", "--cask")):
        _, out, _ = run([BREW, "search", flag, term], timeout=60)
        for line in out.splitlines():
            name = line.strip().rstrip(" ✔")
            if name and not name.startswith("==>") and PKG_RE.match(name):
                results.append({"name": name, "type": kind, "installed": line.strip().endswith("✔")})
    return {"results": results[:100]}


def app_action(body):
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return aptsvc.app_action(body)
    name, kind, action = body.get("name", ""), body.get("type"), body.get("action")
    if action == "upgrade-all":
        return operations.run_upgrade_all()
    if not PKG_RE.match(name) or kind not in ("formula", "cask"):
        raise ApiError("Недопустимое имя пакета", code="srv.pkg_invalid")
    if action not in ("install", "uninstall", "upgrade", "reinstall"):
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    return operations.run_package(action, kind, name)  # единая реализация: тот же код исполняют и агенты (4.2+)
