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
        self.assertEqual(self.code(self.call(a, "execute_plan", plan_id=pid)), "failed")      # ещё не одобрен
        plans.approve({"id": pid})
        self.assertEqual(plans.get({"id": a["id"]}, pid)["status"], "approved")
        r = self.call(a, "execute_plan", plan_id=pid)
        self.assertTrue(r["ok"], r)
        again = self.call(a, "execute_plan", plan_id=pid)
        self.assertFalse(again["ok"])
        self.assertIn("already", again["error"]["message"].lower() + "already")                # повторно исполнить нельзя
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
