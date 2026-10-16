# -*- coding: utf-8 -*-
"""Контрактные тесты шлюза агентов (Фаза 7, слой A): «скриптовый агент» без LLM.

Агент здесь — обычный вызов `agent_gateway.handle(...)` (то же, что делает сокет для MCP-процесса) со своим секретом.
Данные панели — во временной папке; системные диалоги и исполнение операций подменены, окружение (brew/apt/tart) не нужно.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import agent_gateway as gw  # noqa: E402
import approval  # noqa: E402
import audit  # noqa: E402
import core  # noqa: E402
import operations  # noqa: E402
import plans  # noqa: E402


def _view(digest="d1"):
    return (digest, {"level": "L2", "executable": True, "unmet_requirements": [], "plan": {"will_change": True}})


class Contract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for p in [
            mock.patch.object(core, "DATA_DIR", self.tmp),
            mock.patch.object(audit, "LOG", os.path.join(self.tmp, "audit.log")),
            mock.patch.object(gw, "REG_FILE", os.path.join(self.tmp, "agent-registry.json")),
            mock.patch.object(gw, "TOKEN_DIR", os.path.join(self.tmp, "agents")),
            mock.patch.object(plans, "PLANS_FILE", os.path.join(self.tmp, "plans.json")),
            mock.patch.object(plans, "POLICY_FILE", os.path.join(self.tmp, "agent-policy.json")),
            mock.patch.object(plans.core, "spawn", lambda f, *a: f(*a)),          # «фоновый» диалог выполняем сразу
            mock.patch.object(approval, "channel", lambda: {"name": "dialog", "unsafe": []}),
            mock.patch.object(operations, "execute", lambda op, p: {"done": True, "result": {"op": op}}),
            mock.patch.object(operations, "verify", lambda op, p: {"ok": True}),
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.digest = "d1"
        self.level_of_view = "L2"
        p = mock.patch.object(plans, "_digest", lambda op, params: (self.digest, {"level": self.level_of_view, "executable": True,
                                                                                    "unmet_requirements": [], "plan": {"will_change": True}}))
        p.start()
        self.addCleanup(p.stop)
        self.dialog = "approve"
        self.dialogs = 0
        p = mock.patch.object(plans, "ask_human", self._ask)
        p.start()
        self.addCleanup(p.stop)
        gw._CALLS.clear()

    def _ask(self, plan):
        self.dialogs += 1
        return self.dialog

    # ---- помощники «агента»
    def agent(self, name, level="L2"):
        r = gw.register({"name": name, "level": level})
        with open(r["token_file"]) as f:
            token = f.read().strip()
        return {"id": r["id"], "token": token}

    def call(self, a, tool, **params):
        return gw.handle({"token": a["token"], "op": "call", "tool": tool, "params": params})

    def tools(self, a):
        return {t["name"] for t in gw.handle({"token": a["token"], "op": "list_tools"})["result"]["tools"]}

    def code(self, resp):
        self.assertFalse(resp["ok"], resp)
        return resp["error"]["code"]

    def plan_code(self, fn):
        try:
            fn()
        except core.ApiError as e:
            return e.code
        self.fail("ApiError was expected")

    def audit_text(self):
        try:
            with open(audit.LOG, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def propose(self, a, op="snapshot.create", **params):
        r = self.call(a, "plan_changes", operation=op, params=params)
        self.assertTrue(r["ok"], r)
        return r["result"]["id"]

    # ---- уровни и инструменты
    def test_l1_sees_no_write_tools_and_cannot_call_them(self):
        a = self.agent("reader", "L1")
        names = self.tools(a)
        self.assertIn("inspect_system", names)
        self.assertFalse({"plan_changes", "execute_plan", "cancel_plan", "verify_plan"} & names)
        self.assertEqual(self.code(self.call(a, "plan_changes", operation="snapshot.create", params={})), "forbidden")
        self.assertIn("forbidden", self.audit_text())

    def test_no_shell_like_tools_exist_at_any_level(self):
        for lvl in ("L1", "L2", "L3"):
            names = self.tools(self.agent("a-" + lvl, lvl))
            self.assertFalse([n for n in names if "shell" in n or "exec_cmd" in n or n in ("run_command", "sudo")], names)

    def test_unknown_tool_and_bad_params_rejected(self):
        a = self.agent("x")
        self.assertEqual(self.code(self.call(a, "execute_shell", cmd="id")), "unknown_tool")
        self.assertEqual(self.code(self.call(a, "plan_changes", operation="snapshot.create", params={}, extra=1)), "invalid_params")

    # ---- допустимые операции
    def test_operation_outside_agent_list_is_refused(self):
        a = self.agent("x")
        r = self.call(a, "plan_changes", operation="files.write_hosts", params={})
        self.assertIn(self.code(r), ("invalid_params", "failed"))   # схема инструмента перечисляет только агентские операции
        for op in ("service.stop", "package.uninstall", "git.push"):
            self.assertFalse(self.call(a, "plan_changes", operation=op, params={})["ok"])

    def test_l2_agent_cannot_propose_l3_operation(self):
        a = self.agent("x", "L2")
        self.level_of_view = "L3"
        r = self.call(a, "plan_changes", operation="runner.selftest", params={"source": "s123456", "vm": "base", "confirm": "x"})
        self.assertFalse(r["ok"])

    # ---- жизненный цикл плана
    def test_execute_requires_approval_and_runs_once(self):
        a = self.agent("x")
        pid = self.propose(a)
        self.assertEqual(self.code(self.call(a, "execute_plan", plan_id=pid)), "plan.not_approved")   # ещё не одобрен: точный код, не «failed»
        plans.approve({"id": pid})
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "approved")
        r = self.call(a, "execute_plan", plan_id=pid)
        self.assertTrue(r["ok"], r)
        again = self.call(a, "execute_plan", plan_id=pid)
        self.assertFalse(again["ok"])
        self.assertIn(again["error"]["code"], ("plan.already_executed", "plan.not_approved"))   # повторно исполнить нельзя
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "done")
        self.assertTrue(self.call(a, "verify_plan", plan_id=pid)["ok"])

    def test_plan_codes(self):
        a = self.agent("x")
        ag = {"id": a["id"], "name": "x", "level": "L2"}
        pid = self.propose(a)
        self.assertEqual(self.plan_code(lambda: plans.execute(ag, pid)), "plan.not_approved")
        plans.approve({"id": pid})
        plans.execute(ag, pid)
        self.assertEqual(self.plan_code(lambda: plans.execute(ag, pid)), "plan.already_executed")
        self.assertEqual(self.plan_code(lambda: plans.propose(ag, "files.write_hosts", {})), "plan.op_not_allowed")

    def test_stale_plan_is_not_executed(self):
        a = self.agent("x")
        ag = {"id": a["id"], "name": "x", "level": "L2"}
        pid = self.propose(a)
        plans.approve({"id": pid})
        self.digest = "changed"                      # машина изменилась после одобрения
        self.assertEqual(self.plan_code(lambda: plans.execute(ag, pid)), "plan.stale")
        self.assertEqual(plans.get(ag, pid)["status"], "stale")

    def test_rejected_and_cancelled_plans_cannot_run(self):
        a = self.agent("x")
        ag = {"id": a["id"], "name": "x", "level": "L2"}
        self.dialog = "reject"
        pid = self.propose(a)
        plans.approve({"id": pid})
        self.assertEqual(plans.get(ag, pid)["status"], "rejected")
        self.assertEqual(self.plan_code(lambda: plans.execute(ag, pid)), "plan.rejected")
        self.dialog = "approve"
        p2 = self.propose(a, label="b")
        self.call(a, "cancel_plan", plan_id=p2)
        self.assertEqual(self.plan_code(lambda: plans.execute(ag, p2)), "plan.cancelled")

    def test_foreign_plan_is_not_accessible(self):
        a, b = self.agent("a"), self.agent("b")
        pid = self.propose(a)
        for tool in ("get_plan", "cancel_plan", "execute_plan", "verify_plan"):
            self.assertFalse(self.call(b, tool, plan_id=pid)["ok"], tool)
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "pending")

    def test_auto_approve_only_for_l2_and_set_by_human(self):
        a = self.agent("x", "L2")
        gw.set_agent({"id": a["id"], "auto_approve": ["L2"]})
        pid = self.propose(a)
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "approved")
        self.assertEqual(self.dialogs, 0)
        l3 = self.agent("y", "L3")
        gw.set_agent({"id": l3["id"], "auto_approve": ["L2"]})
        self.assertEqual([x for x in gw._load()["agents"] if x["id"] == l3["id"]][0]["auto_approve"], [])
        with self.assertRaises(core.ApiError):
            gw.set_agent({"id": a["id"], "auto_approve": ["L3"]})

    def test_l3_plan_always_needs_dialog(self):
        a = self.agent("ci", "L3")
        ag = {"id": a["id"], "name": "ci", "level": "L3"}
        self.level_of_view = "L3"
        with mock.patch.object(plans.operations, "effective_level", lambda op, p: "L3"):
            pid = self.propose(a, op="runner.selftest", source="s123456", vm="base", confirm="x")
            with mock.patch.object(plans, "policy", lambda: {"approval": "panel"}):    # слабый режим на L3 не действует
                plans.approve({"id": pid})
            self.assertEqual(self.dialogs, 1)
            # подделанное «одобрение кнопкой» не даёт исполнить L3
            plans._update(pid, status="approved", approval={"by": "panel", "at": 0, "mode": "panel"})
            self.assertEqual(self.plan_code(lambda: plans.execute(ag, pid)), "plan.not_approved")

    def test_weaker_approval_mode_requires_dialog(self):
        self.dialog = "reject"
        with self.assertRaises(core.ApiError) as c:
            plans.set_policy({"approval": "panel"})
        self.assertEqual(c.exception.code, "plan.dialog_denied")
        self.assertEqual(plans.policy()["approval"], "dialog")
        self.dialog = "approve"
        with mock.patch.object(plans, "confirm_direct", lambda t: "approve"):
            plans.set_policy({"approval": "panel"})
        self.assertEqual(plans.policy()["approval"], "panel")

    def test_no_approval_channel_fails_closed(self):
        a = self.agent("x")
        pid = self.propose(a)
        with mock.patch.object(approval, "channel", lambda: {"name": None, "unsafe": ["sudo_nopasswd"]}):
            self.assertEqual(self.plan_code(lambda: plans.approve({"id": pid})), "plan.no_approval_channel")
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "pending")

    # ---- пределы и эскалация
    def test_repeated_failures_escalate_to_human(self):
        a = self.agent("x")
        ag = {"id": a["id"], "name": "x", "level": "L2"}
        for _ in range(plans.MAX_SAME_FAILS):
            self.dialog = "reject"
            pid = self.propose(a)
            plans.approve({"id": pid})
        self.assertEqual(self.plan_code(lambda: plans.propose(ag, "snapshot.create", {})), "plan.escalate")
        self.assertIn("escalate", self.audit_text())

    def test_open_plan_limit(self):
        a = self.agent("x")
        for i in range(plans.MAX_PENDING):
            self.propose(a, label=f"l{i}")
        r = self.call(a, "plan_changes", operation="snapshot.create", params={"label": "more"})
        self.assertFalse(r["ok"])

    def test_rate_limit(self):
        a = self.agent("x", "L1")
        with mock.patch.object(gw, "RATE_PER_MIN", 3):
            res = [self.call(a, "list_operations") for _ in range(5)]
        self.assertTrue(res[0]["ok"])
        self.assertEqual(self.code(res[-1]), "rate_limited")

    # ---- секреты и учётные данные
    def test_secret_values_not_in_audit(self):
        a = self.agent("x")
        self.call(a, "plan_changes", operation="snapshot.create", params={"label": "ok", "token": "SUPERSECRET-123"})
        self.call(a, "list_operations", password="SUPERSECRET-123")
        txt = self.audit_text()
        self.assertNotIn("SUPERSECRET-123", txt)
        self.assertNotIn(a["token"], txt)

    def test_token_only_hashed_in_registry_and_file_is_private(self):
        a = self.agent("x")
        with open(gw.REG_FILE, encoding="utf-8") as f:
            self.assertNotIn(a["token"], f.read())
        self.assertEqual(os.stat(os.path.join(gw.TOKEN_DIR, a["id"] + ".token")).st_mode & 0o777, 0o600)

    def test_revoked_rotated_expired_and_bad_tokens(self):
        a = self.agent("x")
        self.assertTrue(self.call(a, "list_operations")["ok"])
        old = dict(a)
        gw.rotate({"id": a["id"]})
        self.assertEqual(self.code(self.call(old, "list_operations")), "unauthorized")
        with open(os.path.join(gw.TOKEN_DIR, a["id"] + ".token")) as f:
            fresh = {"id": a["id"], "token": f.read().strip()}
        self.assertTrue(self.call(fresh, "list_operations")["ok"])
        gw.revoke({"id": a["id"]})
        self.assertEqual(self.code(self.call(fresh, "list_operations")), "unauthorized")
        for tok in ("", None, "x" * 500, 123, "../../etc/passwd"):
            self.assertEqual(self.code(gw.handle({"token": tok, "op": "list_tools"})), "unauthorized")
        self.assertEqual(self.code(gw.handle([1])), "bad_request")
        e = self.agent("e")
        reg = gw._load()
        reg["agents"][-1]["expires"] = 1
        gw._save(reg)
        self.assertEqual(self.code(self.call(e, "list_operations")), "unauthorized")

    def test_audit_identifies_agent(self):
        a = self.agent("named-agent")
        self.call(a, "list_operations")
        lines = [json.loads(x) for x in self.audit_text().splitlines() if x.strip()]
        self.assertTrue(any("named-agent" in json.dumps(x, ensure_ascii=False) for x in lines))


class McpBridge(unittest.TestCase):
    """mcp_server.py как настоящий подпроцесс (stdio JSON-RPC) → Unix-сокет → шлюз."""

    def test_stdio_roundtrip_and_level_filtering(self):
        import subprocess
        import agent_socket
        home = tempfile.mkdtemp(dir="/tmp")
        with mock.patch.object(core, "DATA_DIR", home), mock.patch.object(audit, "LOG", os.path.join(home, "audit.log")), \
                mock.patch.object(gw, "REG_FILE", os.path.join(home, "agent-registry.json")), mock.patch.object(gw, "TOKEN_DIR", os.path.join(home, "agents")):
            r = gw.register({"name": "mcp-l1", "level": "L1"})
            server, err = agent_socket.start(os.path.join(home, "agent.sock"))
            self.assertIsNone(err)
            self.addCleanup(server.shutdown)
            msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "plan_changes", "arguments": {"operation": "snapshot.create", "params": {}}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "execute_shell", "arguments": {}}}]
            out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mcp_server.py"), "--agent", r["id"]],
                                 input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=60,
                                 env={**os.environ, "SERVICE_ADMIN_HOME": home}).stdout
        by_id = {m["id"]: m for m in map(json.loads, out.splitlines())}
        self.assertIn("instructions", by_id[1]["result"])
        names = {t["name"] for t in by_id[2]["result"]["tools"]}
        self.assertIn("inspect_system", names)
        self.assertNotIn("plan_changes", names)
        self.assertTrue(by_id[3]["result"]["isError"])               # L1 не может предлагать изменения
        self.assertEqual(by_id[4]["error"]["code"], -32602)          # execute_shell не существует


if __name__ == "__main__":
    unittest.main()


class ReadTools(unittest.TestCase):
    """L1-инструменты для цикла «проект → версии → запуск → лог» (только чтение). Окружение и помощники — как в Contract."""
    setUp, _ask, agent, call, tools, code = Contract.setUp, Contract._ask, Contract.agent, Contract.call, Contract.tools, Contract.code
    def test_new_read_tools_listed_for_l1(self):
        a = self.agent("r", "L1")
        self.assertTrue({"list_projects", "inspect_project_versions", "list_runtimes", "list_runs", "get_run_log", "list_services"} <= self.tools(a))

    def test_run_log_in_chunks_and_bad_id(self):
        import runs
        a = self.agent("r", "L1")
        rd = os.path.join(self.tmp, "runs")
        os.makedirs(rd)
        with open(os.path.join(rd, "rabc123.log"), "w") as f:
            f.write("x" * 75_000)
        with open(os.path.join(rd, "rdef456.log"), "w", encoding="utf-8") as f:
            f.write("я" * 30_000 + " token ghp_abcdefghijklmnopqrstuvwxyz0123 end")      # 2 байта на букву
        with mock.patch.object(runs, "RUNS_DIR", rd):
            r1 = self.call(a, "get_run_log", run_id="rabc123")["result"]
            self.assertEqual((r1["offset"], r1["next_offset"], r1["eof"]), (0, 50_000, False))
            r2 = self.call(a, "get_run_log", run_id="rabc123", offset=r1["next_offset"])["result"]
            self.assertTrue(r2["eof"])
            self.assertEqual(len(r2["text"]), 25_000)
            c1 = self.call(a, "get_run_log", run_id="rdef456")["result"]
            self.assertNotIn("\ufffd", c1["text"])                                   # кириллица не режется посередине
            c2 = self.call(a, "get_run_log", run_id="rdef456", offset=c1["next_offset"])["result"]
            self.assertNotIn("\ufffd", c2["text"])
            self.assertIn("<скрыто>", c2["text"])
            self.assertNotIn("ghp_abc", c2["text"])
            odd = self.call(a, "get_run_log", run_id="rdef456", offset=1)["result"]   # offset внутри символа
            self.assertNotIn("\ufffd", odd["text"][:5])
            self.assertEqual(self.code(self.call(a, "get_run_log", run_id="r999999")), "run.log_missing")
        self.assertEqual(self.code(self.call(a, "get_run_log", run_id="../etc")), "invalid_params")

    def test_list_projects_shows_runnable_kinds(self):
        import projects
        a = self.agent("r", "L1")
        with mock.patch.object(projects, "list_projects", return_value={"projects": [{"path": "/p/app", "name": "app", "worktree": False}]}), \
             mock.patch.object(projects, "_read_registry_file", return_value={"presets": {"/p/app": {"test": "npm test", "build": ""}}}), \
             mock.patch("os.path.realpath", side_effect=lambda x: x):
            r = self.call(a, "list_projects")["result"]
        self.assertEqual(r["projects"][0]["runnable"], ["test"])

    def test_error_codes_are_precise(self):
        a = self.agent("r", "L1")
        r = self.call(a, "inspect_project_versions", path="/definitely/not/registered")
        self.assertEqual(self.code(r), "proj.unknown")


class NewAgentOps(unittest.TestCase):
    """Шаг 4 ревью: узкие операции агента. Широкие и разрушительные — по-прежнему закрыты."""
    def test_agent_ops_include_new_and_exclude_destructive(self):
        for op in ("lang.select", "python.install", "service.start", "service.stop", "service.restart", "docker.compose_control"):
            self.assertIn(op, plans.AGENT_OPS)
            self.assertEqual(operations.OPS[op]["level"], "L2", op)
        for op in ("lang.action", "docker.compose", "service.uninstall", "package.uninstall", "service.kill"):
            self.assertNotIn(op, plans.AGENT_OPS)

    def test_compose_control_has_no_down(self):
        enum = operations.OPS["docker.compose_control"]["params"]["properties"]["action"]["enum"]
        self.assertFalse([a for a in enum if "down" in a])

    def test_lang_select_rejects_unknown_install(self):
        import ops_system
        with mock.patch.object(ops_system, "_install_ids", return_value=["brew:node@20"]):
            with self.assertRaises(core.ApiError) as cm:
                ops_system._lang_select_plan({"key": "node", "id": "brew:node@99"})
        self.assertEqual(cm.exception.code, "lang.unknown_install")

    def test_lang_action_accepts_via(self):
        import opschema
        self.assertIsNone(opschema.validate(operations.OPS["lang.action"]["params"], {"key": "python", "action": "install", "version": "3.12", "via": "uv"}))   # via разрешён


class AutoRun(unittest.TestCase):
    """Переключатель «тесты без подтверждения»: только project.run (install/lint/test/build), для L2 и L3; остальное — с подтверждением."""
    setUp, _ask, agent, call, tools, code = Contract.setUp, Contract._ask, Contract.agent, Contract.call, Contract.tools, Contract.code

    def _propose(self, a, op, params):
        r = self.call(a, "plan_changes", operation=op, params=params)
        self.assertTrue(r["ok"], r)
        return r["result"]

    def test_l3_agent_runs_tests_without_dialog_but_not_installs(self):
        a = self.agent("ci", "L3")
        gw.set_agent({"id": a["id"], "auto_run": True})
        with mock.patch("projects.resolve", side_effect=lambda x: x):
            for kind in ("test", "lint", "build", "install"):
                p = self._propose(a, "project.run", {"project": "/p", "kind": kind})
                self.assertEqual((p["status"], p["approval"]["mode"]), ("approved", "auto_run"), kind)
                self.call(a, "cancel_plan", plan_id=p["id"])
        p = self._propose(a, "package.install", {"name": "jq", "type": "formula"})
        self.assertEqual(p["status"], "pending")                       # пакеты — по-прежнему с подтверждением

    def test_off_by_default_and_l1_cannot_have_it(self):
        a = self.agent("x", "L2")
        with mock.patch("projects.resolve", side_effect=lambda x: x):
            self.assertEqual(self._propose(a, "project.run", {"project": "/p", "kind": "test"})["status"], "pending")
        b = self.agent("y", "L1")
        self.assertFalse(gw.set_agent({"id": b["id"], "auto_run": True})["agent"]["auto_run"])

    def test_enabling_needs_human_confirmation(self):
        import remote_api
        a = self.agent("z", "L2")
        with mock.patch.object(remote_api, "_confirm", side_effect=core.ApiError("refused", code="remote.not_confirmed")) as conf:
            with self.assertRaises(core.ApiError):
                remote_api.agent_set({"id": a["id"], "auto_run": True})
            conf.assert_called_once()
        self.assertFalse([x for x in gw._load()["agents"] if x["id"] == a["id"]][0].get("auto_run"))
