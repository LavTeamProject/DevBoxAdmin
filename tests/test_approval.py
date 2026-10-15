"""Тесты канала подтверждения Linux (ADR-0001): корневой помощник и проверка решения в панели — без root, на временных каталогах."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import approval  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("sa_helper", os.path.join(ROOT, "linux", "service-admin-approve"))
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader("sa_helper", _loader))
_loader.exec_module(helper)


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.uid = os.getuid()
        self.reqdir = os.path.join(self.home, ".service-admin", "approvals")
        os.makedirs(self.reqdir)
        self.p = mock.patch.object(helper.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=self.home))
        self.p.start()
        self.addCleanup(self.p.stop)

    def _req(self, rid="plan-1", **over):
        r = {"id": rid, "uid": self.uid, "nonce": "ab" * 16, "expires": time.time() + 100, "text": "run docker stop x"}
        r.update(over)
        raw = json.dumps(r).encode()
        with open(os.path.join(self.reqdir, rid + ".req.json"), "wb") as f:
            f.write(raw)
        return raw

    def test_sanitize_strips_escapes_and_controls(self):
        t = helper.sanitize("ok\x1b[2J\x1b[31mred\x07bell\r\x00end\nline2")
        self.assertNotIn("\x1b", t)
        self.assertNotIn("\x07", t)
        self.assertNotIn("\r", t)
        self.assertIn("\nline2", t)

    def test_sanitize_strips_bidi_and_format_chars(self):
        t = helper.sanitize("a\u202eb\u200bc\u2028d")
        self.assertEqual(t, "a?b?c?d")

    def test_load_valid_request_and_digest(self):
        raw = self._req()
        r = helper.load_request(self.uid, "plan-1")
        self.assertEqual(r["digest"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(r["text"], "run docker stop x")

    def test_rejects_bad_id_symlink_expired_foreign(self):
        for bad in ("../x", "a/b", "", "x" * 65, "a b"):
            with self.assertRaises(SystemExit):
                helper.load_request(self.uid, bad)
        self._req("old", expires=time.time() - 5)
        with self.assertRaises(SystemExit):
            helper.load_request(self.uid, "old")
        self._req("real")
        os.symlink(os.path.join(self.reqdir, "real.req.json"), os.path.join(self.reqdir, "link.req.json"))
        with self.assertRaises(SystemExit):  # симлинк на последнем компоненте
            helper.load_request(self.uid, "link")
        self._req("other", uid=self.uid + 1)
        with self.assertRaises(SystemExit):
            helper.load_request(self.uid, "other")
        self._req("big", text="x" * 70000)
        with self.assertRaises(SystemExit):
            helper.load_request(self.uid, "big")

    def test_write_decision_requires_root_owned_dir(self):
        raw = self._req()
        req = helper.load_request(self.uid, "plan-1")
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, str(self.uid)))
        if os.getuid() != 0:  # каталог принадлежит нам, а не root → отказ
            with self.assertRaises(SystemExit):
                helper.write_decision(self.uid, req, "approve", dec_root=d)
        self.assertTrue(raw)


class VerifyDecisionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.uid = os.getuid()
        self.dir = os.path.join(self.root, str(self.uid))
        os.makedirs(self.dir)
        os.chmod(self.dir, 0o755)
        self.req = {"id": "plan-1", "uid": self.uid, "nonce": "cd" * 16, "expires": time.time() + 100}
        self.digest = "d" * 64
        p = mock.patch.object(approval, "_ROOT_UID", os.getuid())  # «root» в тесте — текущий пользователь
        p.start()
        self.addCleanup(p.stop)

    def _write(self, **over):
        data = {"id": "plan-1", "nonce": self.req["nonce"], "digest": self.digest, "decision": "approve", "uid": self.uid,
                "at": time.time(), "expires": self.req["expires"]}
        data.update(over)
        path = os.path.join(self.dir, f"plan-1.{self.req['nonce']}.dec.json")
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o644)
        return path

    def test_valid_decision(self):
        self._write()
        self.assertEqual(approval.verify_decision(self.req, self.digest, self.root), "approve")

    def test_wrong_digest_nonce_or_decision(self):
        self._write(digest="e" * 64)
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))
        self._write(decision="maybe")
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))
        self._write()
        self.assertIsNone(approval.verify_decision({**self.req, "nonce": "00" * 16}, self.digest, self.root))  # чужой nonce = нет файла

    def test_not_root_owned_or_writable_is_ignored(self):
        path = self._write()
        with mock.patch.object(approval, "_ROOT_UID", os.getuid() + 12345):  # владелец не root
            self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))
        os.chmod(path, 0o666)
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))
        os.chmod(path, 0o644)
        os.chmod(self.dir, 0o777)
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))

    def test_expired_decision_ignored(self):
        self._write(expires=time.time() - 60)
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))

    def test_symlink_decision_ignored(self):
        path = self._write()
        real = path + ".real"
        os.rename(path, real)
        os.symlink(real, path)
        self.assertIsNone(approval.verify_decision(self.req, self.digest, self.root))


class ChannelTest(unittest.TestCase):
    def test_no_channel_headless_without_helper_is_unavailable(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(approval.platform_info, "info", return_value={"gui": False}), \
                mock.patch.object(approval, "_helper_ready", return_value=False):
            self.assertIsNone(approval.channel()["name"])
            self.assertEqual(approval.ask("t", {"title": "", "approve": "", "reject": ""}, "en", "plan-1"), "unavailable")

    def test_passwordless_sudo_disables_root_helper(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(approval.platform_info, "info", return_value={"gui": False}), \
                mock.patch.object(approval, "_helper_ready", return_value=True), \
                mock.patch.object(approval, "_unsafe_reasons", return_value=["passwordless_sudo"]):
            ch = approval.channel()
            self.assertIsNone(ch["name"])
            self.assertEqual(ch["unsafe"], ["passwordless_sudo"])

    def test_gui_dialog_needs_graphical_session_and_absolute_tool(self):
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(approval.platform_info, "info", return_value={"gui": True}), \
                mock.patch.object(approval, "_abs_tool", return_value="/usr/bin/zenity"):
            self.assertEqual(approval.channel()["name"], "gui_dialog")


if __name__ == "__main__":
    unittest.main()


class PlanApproveFailClosedTest(unittest.TestCase):
    def test_no_channel_refuses_to_start_approval(self):
        import plans
        from core import ApiError
        plans.PLANS_FILE = os.path.join(tempfile.mkdtemp(), "plans.json")
        pl = {"id": "plan-x1", "agent_id": "a", "agent_name": "n", "operation": "snapshot.create", "params": {}, "level": "L2", "status": "pending",
              "expires": time.time() + 900, "digest": "d", "approval": None, "created": time.time(), "title": "t"}
        plans._save_plans([pl])
        with mock.patch.object(plans.approval, "channel", return_value={"name": None, "unsafe": ["passwordless_sudo"]}), \
                mock.patch.object(plans, "policy", return_value={"approval": "dialog"}):
            with self.assertRaises(ApiError) as cm:
                plans.approve({"id": "plan-x1"})
        self.assertEqual(cm.exception.code, "plan.no_approval_channel")
        self.assertEqual(plans._plans()[0]["status"], "pending")  # план остался нетронутым
