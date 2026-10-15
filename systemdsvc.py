"""Службы systemd на Linux (Фаза 6, Л3): те же формы ответов, что у `brew services` (страница «Службы»).
Службы пользователя управляются напрямую; системные — через elevate.run_admin (окно polkit или `sudo` в терминале)."""
import re
from http import HTTPStatus

import elevate
from core import ApiError, pid_tree_stats, run, tail

UNIT_RE = re.compile(r"^[A-Za-z0-9:_.@-]{1,120}$")
ACTIONS = {"start", "stop", "restart", "run", "kill"}


def _scope_list(user):
    cmd = ["systemctl"] + (["--user"] if user else []) + ["list-units", "--type=service", "--all", "--no-legend", "--plain", "--no-pager"]
    out = run(cmd, timeout=20)[1]
    res = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service") and parts[1] != "not-found":
            unit, load, active, sub = parts[:4]
            status = {"active": "started", "failed": "error"}.get(active, "none")
            res.append({"name": unit[:-8], "unit": unit, "status": status, "running": status == "started", "sub": sub, "scope": "user" if user else "system",
                        "description": parts[4].strip() if len(parts) > 4 else "", "user": None, "file": None,
                        "log_path": None, "error_log_path": None})
    return res


def _main_pids(items, user):
    if not items:
        return {}
    # одним вызовом: show по нескольким юнитам печатает блоки через пустую строку
    cmd = ["systemctl"] + (["--user"] if user else []) + ["show", "-p", "Id", "-p", "MainPID", "--no-pager"] + [i["unit"] for i in items[:300]]
    out = run(cmd, timeout=30)[1]
    pids, cur = {}, {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if cur.get("Id"):
                pids[cur["Id"]] = cur.get("MainPID", "0")
            cur = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            cur[k] = v
    return pids


def list_services():
    items = _scope_list(True) + _scope_list(False)
    seen, uniq = set(), []
    for it in items:  # одно имя в обеих областях — показываем пользовательскую
        if it["name"] not in seen:
            seen.add(it["name"])
            uniq.append(it)
    live = [i for i in uniq if i["status"] == "started"]
    pids = {**_main_pids([i for i in live if i["scope"] == "user"], True), **_main_pids([i for i in live if i["scope"] == "system"], False)}
    ids = [str(p) for p in {pids.get(i["unit"]) for i in live} if p and p != "0"]
    stats = pid_tree_stats(ids) if ids else {}
    for i in uniq:
        pid = pids.get(i["unit"])
        if i["status"] == "started" and pid and pid != "0":
            i["pid"] = int(pid)
            i.update(stats.get(str(pid), {}))
    return uniq


def known_service(name):
    if not UNIT_RE.match(name or ""):
        raise ApiError("Неизвестный сервис", HTTPStatus.NOT_FOUND, code="srv.service_unknown")
    svc = next((s for s in list_services() if s["name"] == name), None)
    if not svc:
        raise ApiError("Неизвестный сервис", HTTPStatus.NOT_FOUND, code="srv.service_unknown")
    return svc


def service_action(body):
    name, action = body.get("name", ""), body.get("action", "")
    if action not in ACTIONS:
        raise ApiError("Недопустимое действие", code="srv.action_invalid")
    svc = known_service(name)
    verb = {"run": "start"}.get(action, action)
    if verb == "kill":
        argv = ["systemctl"] + (["--user"] if svc["scope"] == "user" else []) + ["kill", svc["unit"]]
    else:
        argv = ["systemctl"] + (["--user"] if svc["scope"] == "user" else []) + [verb, svc["unit"]]
    if svc["scope"] == "user":
        code, out, err = run(argv, timeout=60)
        if code != 0:
            raise ApiError((out + err).strip() or "Ошибка", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if (out + err).strip() else "srv.failed")
        return {"ok": True, "output": (out + err).strip()}
    return elevate.run_admin(f"systemctl {verb} {svc['unit']}", argv, kind="service")


def service_logs(q):
    svc = known_service(q.get("name", ""))
    cmd = ["journalctl", "--user-unit" if svc["scope"] == "user" else "-u", svc["unit"], "-n", "300", "--no-pager", "-o", "short-iso"]
    code, out, err = run(cmd, timeout=20)
    return {"log": out if code == 0 else (err or ""), "error_log": None, "log_path": f"journalctl {svc['unit']}", "error_log_path": None}
