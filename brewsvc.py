"""Службы и приложения Homebrew: `brew services` (список, действия, журнал) и пакеты (список, поиск, действия).

Вынесено из server.py: страницы и агенты вызывают одни и те же функции (изменения пакетов исполняет `operations.run_package`).
Только стандартная библиотека; команды — списком аргументов, без shell.
"""
import glob
import json
import os
import sys
from http import HTTPStatus

import aptsvc
import operations
import systemdsvc
from core import BREW, BREW_PREFIX, ENV, PKG_RE, ApiError, loads_or, pid_tree_stats, run, start_job, tail


SERVICE_ACTIONS = {"start", "stop", "restart", "run", "kill"}
# Команды ЧТЕНИЯ не должны запускать авто-обновление Homebrew (оно скачивает индексы и на медленном канале держит страницу минутами)
RO_ENV = dict(ENV, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_ANALYTICS="1")


def list_services():
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return systemdsvc.list_services()
    code, out, err = run([BREW, "services", "info", "--all", "--json"], env=RO_ENV)
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


def _short(name):
    return str(name).split("/")[-1]


def build_apps(data, sizes_kb=None):
    """Данные `brew info --json=v2 --installed` → список пакетов с происхождением (вручную / зависимость), «кто использует», размером
    и признаком «можно удалить» (то же множество, что снимет `brew autoremove`: не поставлено вручную и не нужно ни одному нужному пакету)."""
    sizes_kb = sizes_kb or {}
    forms = data.get("formulae", [])
    names = {f["name"] for f in forms}
    deps = {}
    for f in forms:
        d = set()
        for inst in f.get("installed", []):
            for rd in inst.get("runtime_dependencies") or []:
                n = _short(rd.get("full_name") or "")
                if n in names and n != f["name"]:
                    d.add(n)
        deps[f["name"]] = sorted(d)
    used_by = {n: [] for n in names}
    for n, ds in deps.items():
        for d in ds:
            used_by[d].append(n)
    on_req = {f["name"]: any(i.get("installed_on_request") for i in f.get("installed", [])) for f in forms}
    roots = {n for n, v in on_req.items() if v}
    for c in data.get("casks", []):                         # формулы, нужные установленным приложениям, удалять нельзя
        for d in ((c.get("depends_on") or {}).get("formula") or []):
            if _short(d) in names:
                roots.add(_short(d))
    needed, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n in needed:
            continue
        needed.add(n)
        stack.extend(deps.get(n, []))
    formulae = [{
        "name": f["name"], "type": "formula", "desc": f.get("desc") or "",
        "version": ", ".join(i["version"] for i in f.get("installed", [])),
        "latest": (f.get("versions") or {}).get("stable"),
        "outdated": bool(f.get("outdated")), "pinned": bool(f.get("pinned")),
        "on_request": on_req[f["name"]], "service": bool(f.get("service")), "homepage": f.get("homepage"),
        "used_by": sorted(used_by[f["name"]]), "deps": deps[f["name"]], "removable": f["name"] not in needed,
        "size_mb": round(sizes_kb[f["name"]] / 1024, 1) if f["name"] in sizes_kb else None,
    } for f in forms]
    casks = [{
        "name": c["token"], "type": "cask", "desc": c.get("desc") or ", ".join(c.get("name") or []),
        "version": c.get("installed") or "", "latest": c.get("version"),
        "outdated": bool(c.get("outdated")), "pinned": False, "on_request": True,
        "service": False, "homepage": c.get("homepage"), "used_by": [], "deps": [], "removable": False, "size_mb": None,
    } for c in data.get("casks", [])]
    rem = [a for a in formulae if a["removable"]]
    summary = {"formulae": len(formulae), "manual": sum(1 for a in formulae if a["on_request"]), "deps": sum(1 for a in formulae if not a["on_request"]),
               "casks": len(casks), "removable": len(rem), "removable_mb": round(sum(a["size_mb"] or 0 for a in rem), 1),
               "total_mb": round(sum(a["size_mb"] or 0 for a in formulae), 1)}
    return {"apps": formulae + casks, "summary": summary}


def _cellar_sizes():
    """Размер каждой установленной формулы в Cellar (КБ), одним вызовом du."""
    dirs = sorted(glob.glob(os.path.join(BREW_PREFIX, "Cellar", "*")))
    if not dirs:
        return {}
    try:
        code, out, _ = run(["/usr/bin/du", "-sk", *dirs], timeout=60)
    except Exception:  # noqa: BLE001 — размер — украшение, страница не должна из-за него падать
        return {}
    sizes = {}
    for line in out.splitlines():
        kb, _, path = line.partition("\t")
        if kb.isdigit():
            sizes[os.path.basename(path)] = int(kb)
    return sizes


def list_apps():
    if sys.platform != "darwin":  # Linux: systemd / apt (Фаза 6, Л3)
        return aptsvc.list_apps()
    code, out, err = run([BREW, "info", "--json=v2", "--installed"], timeout=120, env=RO_ENV)
    if code != 0:
        raise ApiError(err.strip() or "Ошибка brew info", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "srv.brew_info_failed")
    return build_apps(json.loads(out), _cellar_sizes())


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
    if action == "autoremove":      # убрать зависимости, которые больше никому не нужны (список видит человек на странице до нажатия)
        return {"job": start_job("brew autoremove", [BREW, "autoremove"], "brew")}
    if action == "cleanup":         # старые версии и кэш загрузок
        return {"job": start_job("brew cleanup", [BREW, "cleanup"], "brew")}
    if not PKG_RE.match(name) or kind not in ("formula", "cask"):
        raise ApiError("Недопустимое имя пакета", code="srv.pkg_invalid")
    if action not in ("install", "uninstall", "upgrade", "reinstall"):
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    return operations.run_package(action, kind, name)  # единая реализация: тот же код исполняют и агенты (4.2+)
