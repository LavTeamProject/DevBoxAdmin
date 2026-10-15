#!/usr/bin/env python3
"""CLI Service Admin — запасной интерфейс для агентов без MCP.

Своей логики не содержит: каждая команда = один вызов инструмента шлюза панели по Unix-сокету
(те же права, лимиты и аудит, что у MCP). Секрет агента — ~/.service-admin/agents/<id>.token.
Вывод — JSON в stdout; ошибки — в stderr, код выхода 1 (панель недоступна — 2).
Только стандартная библиотека.
"""
import argparse
import json
import sys

import mcp_server as m


def call(agent, tool, params=None):
    return m.panel_call(agent, {"op": "call", "tool": tool, "params": params or {}})


def parse_params(items):
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or not k:
            raise SystemExit(f"параметр должен быть key=value: {it}")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="service-admin", description=__doc__.split("\n")[0])
    ap.add_argument("--agent", required=True, help="id агента со страницы «Подключение агентов»")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="состояние Mac + найденные проблемы")
    sub.add_parser("tools", help="инструменты, доступные этому агенту")
    sub.add_parser("vms", help="виртуальные машины (только чтение)")
    sub.add_parser("operations", help="каталог операций")
    p = sub.add_parser("describe", help="описание одной операции"); p.add_argument("operation")
    p = sub.add_parser("plan", help="--profile ID: что даст установка профиля (только чтение); --op ID: предложить изменение")
    p.add_argument("--profile"); p.add_argument("--op"); p.add_argument("--param", action="append", metavar="key=value")
    for name in ("get", "execute", "cancel", "verify"):
        p = sub.add_parser(name, help=f"{name} plan"); p.add_argument("plan_id")
    j = sub.add_parser("job", help="job inspect [ID]").add_subparsers(dest="jcmd", required=True)
    p = j.add_parser("inspect"); p.add_argument("job_id", nargs="?")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        res = {"system": call(a.agent, "inspect_system"), "diagnostics": call(a.agent, "inspect_diagnostics")}
    elif a.cmd == "tools":
        res = call(a.agent, "list_capabilities")
    elif a.cmd == "vms":
        res = call(a.agent, "list_vms")
    elif a.cmd == "operations":
        res = call(a.agent, "list_operations")
    elif a.cmd == "describe":
        res = call(a.agent, "describe_operation", {"operation": a.operation})
    elif a.cmd == "plan":
        if bool(a.profile) == bool(a.op):
            ap.error("нужен ровно один из --profile / --op")
        res = (call(a.agent, "inspect_profile", {"profile": a.profile}) if a.profile
               else call(a.agent, "plan_changes", {"operation": a.op, "params": parse_params(a.param)}))
    elif a.cmd in ("get", "execute", "cancel", "verify"):
        res = call(a.agent, {"get": "get_plan", "execute": "execute_plan", "cancel": "cancel_plan", "verify": "verify_plan"}[a.cmd],
                   {"plan_id": a.plan_id})
    else:
        res = call(a.agent, "get_job_status", {"job_id": a.job_id} if a.job_id else {})
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except m.PanelError as e:
        print(f"service-admin: {e.code}: {e.message}", file=sys.stderr)
        sys.exit(2 if e.code in ("panel_unavailable", "credential_missing") else 1)
