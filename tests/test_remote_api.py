# -*- coding: utf-8 -*-
"""Фаза 8 (ADR-0003): удалённый API, операторы, TOTP, Telegram-бот. Данные — во временной папке; системные диалоги подменены;
слушатель поднимается на свободном порту loopback."""
import base64
import http.server
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import agent_gateway as gw  # noqa: E402
import approval  # noqa: E402
import audit  # noqa: E402
import core  # noqa: E402
import operators as ops  # noqa: E402
import plans  # noqa: E402
import remote_api  # noqa: E402
import telegram_bot  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in [
            mock.patch.object(core, "DATA_DIR", self.tmp),
            mock.patch.object(audit, "LOG", os.path.join(self.tmp, "audit.log")),
            mock.patch.object(gw, "REG_FILE", os.path.join(self.tmp, "agent-registry.json")),
            mock.patch.object(gw, "TOKEN_DIR", os.path.join(self.tmp, "agents")),
            mock.patch.object(plans, "PLANS_FILE", os.path.join(self.tmp, "plans.json")),
            mock.patch.object(plans, "POLICY_FILE", os.path.join(self.tmp, "agent-policy.json")),
            mock.patch.object(ops, "OPERATORS_FILE", os.path.join(self.tmp, "operators.json")),
            mock.patch.object(remote_api, "SETTINGS_FILE", os.path.join(self.tmp, "remote.json")),
            mock.patch.object(remote_api, "DATA_DIR", self.tmp),
            mock.patch.object(remote_api, "TLS_DIR", os.path.join(self.tmp, "tls")),
            mock.patch.object(telegram_bot, "TOKEN_FILE", os.path.join(self.tmp, "telegram-bot.token")),
            mock.patch.object(telegram_bot, "OFFSET_FILE", os.path.join(self.tmp, "telegram.offset")),
            mock.patch.object(telegram_bot, "DATA_DIR", self.tmp),
            mock.patch.object(approval, "channel", lambda: {"name": "dialog", "unsafe": []}),
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.dialog = "approve"
        self.dialogs = []
        p = mock.patch.object(plans, "confirm_direct", lambda summary: (self.dialogs.append(summary), self.dialog)[1])
        p.start()
        self.addCleanup(p.stop)
        remote_api._FAILS.clear()
        remote_api._BLOCKED.clear()
        remote_api._OPCALLS.clear()
        remote_api._AUDIT_AT.clear()
        self.addCleanup(remote_api.stop)

    def audit_text(self):
        try:
            return open(audit.LOG, encoding="utf-8").read()
        except OSError:
            return ""

    def agent(self, name="bot", level="L2"):
        r = gw.register({"name": name, "level": level})
        return {"id": r["id"], "name": name, "level": level, "token": open(r["token_file"]).read().strip()}

    def operator(self, name="alice", scopes=("read", "approve"), **kw):
        r = ops.create({"name": name, "scopes": list(scopes), **kw})
        return r["operator"], r["token"], r["totp_secret"]

    def plan(self, agent, level="L2", status="pending"):
        p = {"id": "p" + os.urandom(4).hex(), "agent_id": agent["id"], "agent_name": agent["name"], "operation": "snapshot.create", "title": "Snapshot",
             "params": {}, "level": level, "created": time.time(), "expires": time.time() + 600, "digest": "ab" * 32, "view": {"writes": "x"},
             "status": status, "noop": False, "approval": None, "job": None, "executed_at": None, "error": None}
        plans._save_plans(plans._plans() + [p])
        return p


class Totp(Base):
    def test_rfc6238_vector(self):
        key = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(ops.totp_now(key, 59), "287082")            # RFC 6238, шаг 1, 6 цифр
        self.assertEqual(ops.totp_now(key, 1111111109), "081804")
        self.assertEqual(ops.totp_now(key, 20000000000), "353130")

    def test_code_is_single_use_and_window_limited(self):
        op, _, secret = self.operator()
        now = 1_700_000_000
        code = ops.totp_now(secret, now)
        self.assertTrue(ops.verify_totp(op["id"], code, now))
        self.assertFalse(ops.verify_totp(op["id"], code, now))                  # повтор
        self.assertFalse(ops.verify_totp(op["id"], code, now + 5))
        self.assertFalse(ops.verify_totp(op["id"], ops.totp_now(secret, now - 300), now))   # старый код
        self.assertTrue(ops.verify_totp(op["id"], ops.totp_now(secret, now + 30), now + 30))
        for bad in ("", None, "12345", "1234567", "abcdef", " 123456 x"):
            self.assertFalse(ops.verify_totp(op["id"], bad, now + 90))

    def test_revoked_operator_has_no_totp(self):
        op, _, secret = self.operator()
        ops.revoke({"id": op["id"]})
        self.assertFalse(ops.verify_totp(op["id"], ops.totp_now(secret), time.time()))


class Operators(Base):
    def test_token_hashed_prefixed_shown_once_and_file_private(self):
        op, token, secret = self.operator()
        self.assertTrue(token.startswith("sao_") and len(token) > 40)
        raw = open(ops.OPERATORS_FILE).read()
        self.assertNotIn(token, raw)
        self.assertEqual(os.stat(ops.OPERATORS_FILE).st_mode & 0o777, 0o600)
        pub = ops.list_operators()
        self.assertNotIn("token_hash", json.dumps(pub))
        self.assertNotIn(secret, json.dumps(pub))
        self.assertEqual(ops.authenticate(token)["id"], op["id"])

    def test_authenticate_rejects_bad_revoked_expired_and_agent_tokens(self):
        op, token, _ = self.operator()
        agent = self.agent()
        for bad in (None, "", "sao_", "x" * 300, agent["token"], token + "x", token[:-1], 5):
            self.assertIsNone(ops.authenticate(bad))
        o2, t2, _ = self.operator("bob")
        reg = ops._load()
        [x for x in reg["operators"] if x["id"] == o2["id"]][0]["expires"] = 1
        ops._save(reg)
        self.assertIsNone(ops.authenticate(t2))
        ops.revoke({"id": op["id"]})
        self.assertIsNone(ops.authenticate(token))

    def test_rotate_invalidates_old_token_and_secret(self):
        op, token, secret = self.operator()
        r = ops.rotate({"id": op["id"]})
        self.assertIsNone(ops.authenticate(token))
        self.assertIsNotNone(ops.authenticate(r["token"]))
        self.assertNotEqual(secret, r["totp_secret"])

    def test_validation_and_uniqueness(self):
        self.operator("alice", telegram_chat_id=111)
        for body in ({"name": ""}, {"name": "x" * 50}, {"name": "ok", "scopes": ["root"]}, {"name": "ok", "scopes": []}, {"name": "ok", "expires_days": 0},
                     {"name": "ok", "telegram_chat_id": "abc"}, {"name": "ALICE"}, {"name": "ok2", "telegram_chat_id": 111}):
            with self.assertRaises(core.ApiError, msg=str(body)):
                ops.create(body)


    def test_totp_lockout_after_repeated_failures_and_unlock_only_by_human(self):
        op, token, secret = self.operator()
        now = 1_700_000_000
        for i in range(ops.TOTP_MAX_FAILS):
            self.assertFalse(ops.verify_totp(op["id"], "%06d" % i, now + i))
        self.assertTrue(ops.list_operators()["operators"][0]["totp_locked"])
        self.assertFalse(ops.verify_totp(op["id"], ops.totp_now(secret, now + 60), now + 60))      # верный код после блокировки — тоже отказ
        self.assertIn("operator:totp_locked", self.audit_text())
        ops.unlock({"id": op["id"]})
        self.assertTrue(ops.verify_totp(op["id"], ops.totp_now(secret, now + 90), now + 90))
        for i in range(ops.TOTP_MAX_FAILS - 1):                                                     # успешный код обнуляет счётчик неудач
            ops.verify_totp(op["id"], "000000", now + 120 + i)
        self.assertTrue(ops.verify_totp(op["id"], ops.totp_now(secret, now + 150), now + 150))
        r = ops.rotate({"id": op["id"]})
        self.assertFalse(ops.list_operators()["operators"][0]["totp_locked"])
        self.assertTrue(r["token"])

    def test_replayed_valid_code_is_not_counted_as_guessing(self):
        op, _, secret = self.operator()
        now = 1_700_000_000
        code = ops.totp_now(secret, now)
        self.assertTrue(ops.verify_totp(op["id"], code, now))
        for _ in range(ops.TOTP_MAX_FAILS * 2):
            self.assertFalse(ops.verify_totp(op["id"], code, now))          # повтор клиента / повторная доставка
        self.assertFalse(ops.is_locked(op["id"]))

    def test_concurrent_use_of_one_code_succeeds_once(self):
        op, _, secret = self.operator()
        now = 1_700_000_000
        code = ops.totp_now(secret, now)
        res = []
        threads = [threading.Thread(target=lambda: res.append(ops.verify_totp(op["id"], code, now))) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(res.count(True), 1)

    def test_names_are_ascii_only(self):
        for bad in ("\u0410lice", "Al\u0456ce", "\u200balice", "al\nice"):
            with self.assertRaises(core.ApiError, msg=repr(bad)):
                ops.create({"name": bad})

    def test_granting_approve_reissues_credentials(self):
        op, token, secret = self.operator("viewer", scopes=("read",))
        r = ops.set_operator({"id": op["id"], "scopes": ["read", "approve"]})
        self.assertIn("token", r)
        self.assertIsNone(ops.authenticate(token))                       # прежние данные больше не действуют
        self.assertIsNotNone(ops.authenticate(r["token"]))
        self.assertNotEqual(r["totp_secret"], secret)
        r2 = ops.set_operator({"id": op["id"], "telegram_chat_id": 55})
        self.assertNotIn("token", r2)

    def test_agent_registry_does_not_accept_operator_token(self):
        _, token, _ = self.operator()
        self.assertIsNone(gw.authenticate(token))


class Settings(Base):
    def test_defaults_off_and_loopback(self):
        s = remote_api.settings()
        self.assertFalse(s["enabled"])
        self.assertEqual(s["bind"], "127.0.0.1")
        self.assertFalse(s["remote_approval"])

    def test_non_loopback_needs_tls_and_allow_list(self):
        base = dict(remote_api.DEFAULTS, bind="192.168.1.5", allow=["192.168.1.0/24"], tls=True)
        remote_api.validate(dict(base))
        for bad in (dict(base, tls=False), dict(base, allow=[]), dict(base, bind="not-an-ip"), dict(base, port=80), dict(base, port=8765), dict(base, allow=["x"])):
            with self.assertRaises(core.ApiError, msg=str(bad)):
                remote_api.validate(bad)

    def test_weakening_needs_dialog_and_denied_leaves_settings(self):
        self.dialog = "reject"
        with self.assertRaises(core.ApiError) as c:
            remote_api.set_settings({"enabled": True, "port": free_port()})
        self.assertEqual(c.exception.code, "remote.dialog_denied")
        self.assertFalse(remote_api.settings()["enabled"])
        self.dialog = "approve"
        remote_api.set_settings({"enabled": True, "port": free_port()})
        self.assertTrue(remote_api.settings()["enabled"])
        self.assertTrue(self.dialogs)
        n = len(self.dialogs)
        remote_api.set_settings({"enabled": False})           # выключение — без диалога
        self.assertEqual(len(self.dialogs), n)
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.set_settings({"remote_approval": True})
        self.assertFalse(remote_api.settings()["remote_approval"])

    def test_no_dialog_channel_fails_closed(self):
        self.dialog = "unavailable"
        with self.assertRaises(core.ApiError):
            remote_api.set_settings({"enabled": True, "port": free_port()})
        with self.assertRaises(core.ApiError):
            remote_api.op_create({"name": "boss", "scopes": ["read", "approve"]})
        self.assertEqual(ops.list_operators()["operators"], [])


    def test_approver_downgrade_rotate_and_rebind_all_need_the_dialog(self):
        self.dialog = "approve"
        o = remote_api.op_create({"name": "boss", "scopes": ["read", "approve"]})["operator"]
        self.dialog = "reject"
        for body in ({"id": o["id"], "scopes": ["read"]}, {"id": o["id"], "telegram_chat_id": 999}, {"id": o["id"], "scopes": ["read"], "telegram_chat_id": 999}):
            with self.assertRaises(core.ApiError, msg=str(body)) as c:
                remote_api.op_set(body)
            self.assertEqual(c.exception.code, "remote.dialog_denied")
        with self.assertRaises(core.ApiError):
            remote_api.op_rotate({"id": o["id"]})
        cur = [x for x in ops.list_operators()["operators"] if x["id"] == o["id"]][0]
        self.assertEqual((cur["scopes"], cur["telegram_chat_id"]), (["approve", "read"], None))
        v = remote_api.op_create({"name": "viewer", "scopes": ["read"]})["operator"]
        with self.assertRaises(core.ApiError):
            remote_api.op_rotate({"id": v["id"]})                         # даже read-only: новые учётные данные уходят вызывающему
        n = len(self.dialogs)
        self.dialog = "approve"
        remote_api.op_set({"id": o["id"], "telegram_chat_id": 999})
        self.assertIn("999", json.dumps(self.dialogs[n:], ensure_ascii=False))     # диалог называет действие

    def test_allow_list_rejects_whole_internet_prefixes_and_dialog_lists_it(self):
        base = dict(remote_api.DEFAULTS, bind="192.168.1.5", tls=True)
        for bad in (["0.0.0.0/0"], ["::/0"], ["10.0.0.0/7"], ["1.0.0.0/4"]):
            with self.assertRaises(core.ApiError, msg=str(bad)):
                remote_api.validate(dict(base, allow=bad))
        remote_api.validate(dict(base, allow=["10.0.0.0/8", "192.168.1.0/24", "2001:db8::/32"]))
        remote_api.set_settings({"enabled": True, "bind": "192.168.1.5", "port": free_port(), "tls": True, "allow": ["192.168.1.0/24"]})
        self.assertIn("192.168.1.0/24", json.dumps(self.dialogs, ensure_ascii=False))
        self.dialogs.clear()
        remote_api.set_settings({"port": free_port()})                    # итог остаётся «открыт наружу»: список адресов снова виден в диалоге? нет — ничего не ослаблено
        self.assertEqual(self.dialogs, [])

    def test_settings_written_after_a_dialog_do_not_overwrite_newer_changes(self):
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": True})
        good = "123456789:" + "A" * 35

        def human_changes_settings_while_dialog_is_open(summary):
            remote_api.update_settings(lambda s: s.update(remote_approval=False))     # человек выключил удалённое одобрение, пока открыт диалог
            return "approve"
        with mock.patch.object(plans, "confirm_direct", human_changes_settings_while_dialog_is_open), mock.patch.object(telegram_bot, "apply"):
            telegram_bot.set_settings({"token": good, "enabled": True})
        s = remote_api.settings()
        self.assertTrue(s["telegram"]["enabled"])
        self.assertFalse(s["remote_approval"])                             # не воскрешено устаревшей копией


    def test_agent_level_and_auto_approve_need_the_dialog(self):
        a = self.agent("dev", "L1")
        self.dialog = "reject"
        for body in ({"id": a["id"], "level": "L2"}, {"id": a["id"], "level": "L3"}):
            with self.assertRaises(core.ApiError, msg=str(body)) as c:
                remote_api.agent_set(body)
            self.assertEqual(c.exception.code, "remote.dialog_denied")
        self.assertEqual([x for x in gw._load()["agents"] if x["id"] == a["id"]][0]["level"], "L1")
        self.dialog = "approve"
        remote_api.agent_set({"id": a["id"], "level": "L2"})
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.agent_set({"id": a["id"], "auto_approve": ["L2"]})        # самоодобряющий агент — только через окно
        self.assertEqual([x for x in gw._load()["agents"] if x["id"] == a["id"]][0]["auto_approve"], [])
        remote_api.agent_set({"id": a["id"], "level": "L1"})                     # понижение — без окна
        self.assertEqual([x for x in gw._load()["agents"] if x["id"] == a["id"]][0]["level"], "L1")

    def test_unlock_needs_the_dialog(self):
        op, _, _ = self.operator()
        reg = ops._load()
        reg["operators"][0]["totp_locked"] = True
        ops._save(reg)
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.op_unlock({"id": op["id"]})
        self.assertTrue(ops.is_locked(op["id"]))
        self.dialog = "approve"
        remote_api.op_unlock({"id": op["id"]})
        self.assertFalse(ops.is_locked(op["id"]))

    def test_operator_changed_between_dialog_and_write_is_refused(self):
        o = remote_api.op_create({"name": "viewer", "scopes": ["read"]})["operator"]

        def sneaky(summary):                       # пока человек читает окно, чат привязывают в обход (тот же вызов набора операций без окна невозможен — меняем файл)
            reg = ops._load()
            [x for x in reg["operators"] if x["id"] == o["id"]][0]["telegram_chat_id"] = 31337
            ops._save(reg)
            return "approve"
        with mock.patch.object(plans, "confirm_direct", sneaky):
            with self.assertRaises(core.ApiError) as c:
                remote_api.op_set({"id": o["id"], "scopes": ["read", "approve"]})
        self.assertEqual(c.exception.code, "op.changed")
        self.assertEqual(ops.list_operators()["operators"][0]["scopes"], ["read"])

    def test_stale_remote_settings_do_not_overwrite_newer_ones(self):
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": False})

        def human_enables_approval_meanwhile(summary):
            remote_api.update_settings(lambda s: s.update(remote_approval=True))
            return "approve"
        with mock.patch.object(plans, "confirm_direct", human_enables_approval_meanwhile):
            remote_api.set_settings({"enabled": True, "port": free_port()})
        s = remote_api.settings()
        self.assertTrue(s["enabled"] and s["remote_approval"])
        # человек выключил «одобрение» пока шёл диалог другого действия — устаревшая копия его не воскрешает
        remote_api._write({**remote_api.DEFAULTS, "enabled": True, "remote_approval": True, "port": free_port()})

        def human_disables_approval(summary):
            remote_api.update_settings(lambda s: s.update(remote_approval=False))
            return "approve"
        with mock.patch.object(plans, "confirm_direct", human_disables_approval):
            remote_api.set_settings({"tls": True, "bind": "192.168.1.5", "allow": ["192.168.1.0/24"]})
        self.assertFalse(remote_api.settings()["remote_approval"])

    def test_issuing_a_token_for_an_l3_agent_needs_the_dialog(self):
        a3 = self.agent("ci", "L3")
        a2 = self.agent("dev", "L2")
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.issue_agent_token({"id": a3["id"]})
        self.assertEqual(open(os.path.join(gw.TOKEN_DIR, a3["id"] + ".token")).read().strip(), a3["token"])   # токен не изменён
        with self.assertRaises(core.ApiError):
            remote_api.issue_agent_token({"id": a2["id"]})                 # любой уровень: токен возвращается вызывающему
        self.dialog = "approve"
        r = remote_api.issue_agent_token({"id": a2["id"]})
        self.assertNotEqual(r["token"], a2["token"])

    def test_operator_with_approve_needs_dialog_read_only_does_not(self):
        remote_api.op_create({"name": "viewer", "scopes": ["read"]})
        self.assertEqual(self.dialogs, [])
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.op_create({"name": "boss", "scopes": ["read", "approve"]})
        self.dialog = "approve"
        o = remote_api.op_create({"name": "boss", "scopes": ["read", "approve"]})["operator"]
        v = [x for x in ops.list_operators()["operators"] if x["name"] == "viewer"][0]
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            remote_api.op_set({"id": v["id"], "scopes": ["read", "approve"]})            # получить право approve — через диалог
        with self.assertRaises(core.ApiError):
            remote_api.op_set({"id": o["id"], "telegram_chat_id": 777})                  # привязать чужой чат к approve-оператору — через диалог
        with self.assertRaises(core.ApiError):
            remote_api.op_rotate({"id": o["id"]})
        with self.assertRaises(core.ApiError):
            remote_api.op_set({"id": v["id"], "telegram_chat_id": 5})                    # привязка чата — всегда через диалог (по Telegram хватает чата и кода)
        self.assertIsNone(ops.by_chat(5))
        self.dialog = "approve"
        remote_api.op_set({"id": v["id"], "telegram_chat_id": 5})
        self.assertEqual(ops.by_chat(5)["id"], v["id"])


class Handlers(Base):
    def setUp(self):
        super().setUp()
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": True})
        self.agent_rec = self.agent()
        self.op, self.token, self.secret = self.operator()
        self.opr = ops.authenticate(self.token)

    def approve(self, pid, digest, totp=None, operator=None):
        return remote_api.handle_operator("POST", "/operator/v1/plans/approve", {}, operator or self.opr,
                                          {"id": pid, "digest": digest, "totp": totp if totp is not None else ops.totp_now(self.secret)})

    def test_successful_remote_approval_is_recorded(self):
        p = self.plan(self.agent_rec)
        status, r = self.approve(p["id"], p["digest"][:12])
        self.assertEqual(status, 200, r)
        self.assertEqual(r["result"]["status"], "approved")
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["approval"]["by"], "operator:alice")
        self.assertIn("operator:alice", self.audit_text())

    def test_each_precondition_is_enforced(self):
        p = self.plan(self.agent_rec)
        st, r = self.approve(p["id"], p["digest"][:12], totp="000000")
        self.assertEqual((st, r["error"]["code"]), (403, "totp_invalid"))
        st, r = self.approve(p["id"], "deadbeef0000")                           # TOTP верен, хеш — не тот
        self.assertEqual((st, r["error"]["code"]), (409, "plan.digest_mismatch"))
        # TOTP «сгорел» на неудачной попытке с неверным хешем — это нормально: нужен новый код
        st, r = remote_api.handle_operator("POST", "/operator/v1/plans/approve", {}, self.opr, {"id": p["id"], "digest": "short", "totp": ops.totp_now(self.secret, time.time() + 30)})
        self.assertEqual(st, 409)
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["status"], "pending")

    def test_locked_operator_gets_a_distinct_answer(self):
        p = self.plan(self.agent_rec)
        for i in range(ops.TOTP_MAX_FAILS):
            self.approve(p["id"], p["digest"][:12], totp="00000%d" % i)
        st, r = self.approve(p["id"], p["digest"][:12], totp=ops.totp_now(self.secret))
        self.assertEqual((st, r["error"]["code"]), (403, "totp_locked"))
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["status"], "pending")

    def test_l3_cannot_be_approved_remotely(self):
        p = self.plan(self.agent_rec, level="L3")
        st, r = self.approve(p["id"], p["digest"][:12])
        self.assertEqual((st, r["error"]["code"]), (403, "plan.remote_level"))
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["status"], "pending")

    def test_switch_off_by_default_and_read_only_operator(self):
        p = self.plan(self.agent_rec)
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": False})
        st, r = self.approve(p["id"], p["digest"][:12])
        self.assertEqual((st, r["error"]["code"]), (403, "remote_approval_off"))
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": True})
        ro, tok, sec = self.operator("viewer", scopes=("read",))
        st, r = self.approve(p["id"], p["digest"][:12], totp=ops.totp_now(sec), operator=ops.authenticate(tok))
        self.assertEqual((st, r["error"]["code"]), (403, "forbidden"))
        st, _ = remote_api.handle_operator("GET", "/operator/v1/plans", {}, ops.authenticate(tok), None)
        self.assertEqual(st, 200)

    def test_plan_already_decided_cannot_be_approved_again(self):
        p = self.plan(self.agent_rec, status="rejected")
        st, r = self.approve(p["id"], p["digest"][:12])
        self.assertEqual((st, r["error"]["code"]), (409, "plan.not_pending"))
        st, r = self.approve("pdeadbeef", "ab" * 6, totp=ops.totp_now(self.secret, time.time() + 30))
        self.assertEqual(st, 404)

    def test_reject_and_reads(self):
        p = self.plan(self.agent_rec)
        st, r = remote_api.handle_operator("POST", "/operator/v1/plans/reject", {}, self.opr, {"id": p["id"]})
        self.assertEqual((st, r["result"]["status"]), (200, "rejected"))
        for path in ("/operator/v1/status", "/operator/v1/plans", "/operator/v1/audit"):
            self.assertEqual(remote_api.handle_operator("GET", path, {}, self.opr, None)[0], 200, path)
        self.assertEqual(remote_api.handle_operator("GET", "/operator/v1/nope", {}, self.opr, None)[0], 404)
        for method, path in (("POST", "/operator/v1/run"), ("POST", "/operator/v1/settings"), ("POST", "/operator/v1/operators/create")):
            self.assertEqual(remote_api.handle_operator(method, path, {}, self.opr, {})[0], 404)   # операторских действий кроме чтения/решений нет

    def test_agent_cannot_use_operator_surface_even_with_a_valid_token(self):
        # токен агента не операторский: authenticate() его не принимает (см. Operators), а шлюз агента не знает операторских инструментов
        names = {t["name"] for t in gw.handle({"token": self.agent_rec["token"], "op": "list_tools"})["result"]["tools"]}
        self.assertFalse([n for n in names if "approve" in n or "operator" in n])


class Http(Base):
    def setUp(self):
        super().setUp()
        self.port = free_port()
        self.agent_rec = self.agent()
        self.op, self.token, self.secret = self.operator()
        remote_api._write({**remote_api.DEFAULTS, "enabled": True, "port": self.port, "remote_approval": True})
        remote_api.apply()
        self.assertTrue(remote_api.status()["running"], remote_api.status())

    def req(self, method, path, token=None, body=None, ctype="application/json", raw=None, ctx=None, scheme="http"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": ctype} if data is not None else {}
        if token:
            h["Authorization"] = "Bearer " + token
        r = urllib.request.Request(f"{scheme}://127.0.0.1:{self.port}{path}", data, h, method=method)
        try:
            with urllib.request.urlopen(r, timeout=10, context=ctx) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_agent_endpoints(self):
        st, r = self.req("GET", "/agent/v1/tools", self.agent_rec["token"])
        self.assertEqual(st, 200)
        self.assertIn("inspect_system", {t["name"] for t in r["result"]["tools"]})
        st, r = self.req("POST", "/agent/v1/call", self.agent_rec["token"], {"tool": "list_operations", "params": {}})
        self.assertEqual((st, r["ok"]), (200, True))
        st, r = self.req("POST", "/agent/v1/call", self.agent_rec["token"], {"tool": "execute_shell", "params": {}})
        self.assertEqual(st, 404)
        st, _ = self.req("POST", "/agent/v1/call", self.agent_rec["token"], {"params": {}})
        self.assertEqual(st, 400)

    def test_tokens_are_not_interchangeable(self):
        self.assertEqual(self.req("GET", "/operator/v1/status", self.agent_rec["token"])[0], 401)
        self.assertEqual(self.req("GET", "/agent/v1/tools", self.token)[0], 401)
        self.assertEqual(self.req("GET", "/operator/v1/status")[0], 401)
        self.assertEqual(self.req("GET", "/operator/v1/status", "sao_wrong")[0], 401)
        self.assertEqual(self.req("GET", "/operator/v1/status", self.token)[0], 200)

    def test_operator_flow_over_http(self):
        p = Base.plan(self, self.agent_rec)
        st, r = self.req("GET", "/operator/v1/plans", self.token)
        self.assertEqual(st, 200)
        shown = [x for x in r["result"]["plans"] if x["id"] == p["id"]][0]
        st, r = self.req("POST", "/operator/v1/plans/approve", self.token, {"id": p["id"], "digest": shown["digest"], "totp": ops.totp_now(self.secret)})
        self.assertEqual((st, r["result"]["status"]), (200, "approved"), r)
        st, r = self.req("POST", "/operator/v1/plans/approve", self.token, {"id": p["id"], "digest": shown["digest"], "totp": ops.totp_now(self.secret)})
        self.assertNotEqual(st, 200)                       # повтор: и TOTP использован, и план уже не ожидает

    def test_limits_and_strict_input(self):
        self.assertEqual(self.req("POST", "/agent/v1/call", self.agent_rec["token"], raw=b"{" * 10, ctype="application/json")[0], 400)
        self.assertEqual(self.req("POST", "/agent/v1/call", self.agent_rec["token"], raw=b"{}", ctype="text/plain")[0], 415)
        self.assertEqual(self.req("POST", "/agent/v1/call", self.agent_rec["token"], raw=b"x" * (remote_api.MAX_BODY + 1))[0], 413)
        self.assertEqual(self.req("GET", "/nope", self.token)[0], 404)
        self.assertEqual(self.req("GET", "/operator/v1/../../api/platform", self.token)[0], 404)

    def test_failed_auth_blocks_a_remote_address_but_never_loopback(self):
        ip = "203.0.113.7"
        for _ in range(remote_api.FAIL_LIMIT):
            remote_api._fail(ip)
        self.assertTrue(remote_api._blocked(ip))
        self.assertTrue(remote_api._blocked(ip, now=time.time() + remote_api.BLOCK_SECONDS - 5))
        self.assertFalse(remote_api._blocked(ip, now=time.time() + remote_api.BLOCK_SECONDS + 5))
        # loopback — это обратный прокси/туннель: блок по адресу отключил бы всех клиентов разом
        for _ in range(remote_api.FAIL_LIMIT * 2):
            self.req("GET", "/operator/v1/status", "sao_guess")
        self.assertFalse(remote_api._blocked("127.0.0.1"))
        self.assertEqual(self.req("GET", "/operator/v1/status", self.token)[0], 200)
        self.assertIn("remote:auth_failed", self.audit_text())
        self.assertLess(self.audit_text().count("remote:auth_failed"), 5)       # записи об отказах ограничены по частоте

    def test_address_outside_allow_list_is_dropped_before_parsing(self):
        with mock.patch.object(remote_api, "_allowed_ip", lambda ip, s: False):
            with self.assertRaises((urllib.error.URLError, OSError)):
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/operator/v1/status", timeout=5)
        self.assertIn("address not allowed", self.audit_text())

    def test_idle_connection_does_not_block_the_listener(self):
        idle = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(idle.close)
        t0 = time.time()
        self.assertEqual(self.req("GET", "/operator/v1/status", self.token)[0], 200)
        self.assertLess(time.time() - t0, 5)

    def test_slow_request_is_cut_by_the_overall_deadline(self):
        remote_api.stop()
        with mock.patch.object(remote_api, "REQUEST_DEADLINE", 1):
            remote_api.apply()
            c = socket.create_connection(("127.0.0.1", self.port))
            self.addCleanup(c.close)
            c.sendall(b"GET /operator/v1/status HTTP/1.0\r\nX-A: ")      # заголовки не заканчиваются
            c.settimeout(6)
            time.sleep(1.5)
            try:
                data = c.recv(100)
            except OSError:
                data = b""
        self.assertEqual(data, b"")                                       # сервер закрыл соединение, поток освобождён
        self.assertEqual(self.req("GET", "/operator/v1/status", self.token)[0], 200)

    def test_audit_limit_with_unicode_digits_is_not_a_500(self):
        self.assertEqual(self.req("GET", "/operator/v1/audit?limit=%C2%B2", self.token)[0], 200)
        self.assertEqual(self.req("GET", "/operator/v1/audit?limit=abc", self.token)[0], 200)

    def test_no_secrets_in_audit_and_requests_audited(self):
        self.req("POST", "/agent/v1/call", self.agent_rec["token"], {"tool": "list_operations", "params": {"password": "TOPSECRET-1"}})
        text = self.audit_text()
        self.assertNotIn(self.agent_rec["token"], text)
        self.assertNotIn(self.token, text)
        self.assertNotIn("TOPSECRET-1", text)
        self.assertIn("remote:request", text)

    def test_disabled_by_settings(self):
        remote_api.set_settings({"enabled": False})
        self.assertFalse(remote_api.status()["running"])
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/operator/v1/status", timeout=3)

    def _tls_up(self):
        remote_api._write({**remote_api.DEFAULTS, "enabled": True, "port": self.port, "tls": True})
        remote_api.apply()
        self.assertTrue(remote_api.status()["running"], remote_api.status())
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required")
    def test_tls_connection_is_closed_after_the_response_and_slots_are_released(self):
        ctx = self._tls_up()
        for _ in range(8):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw, ctx.wrap_socket(raw) as s:
                s.sendall(f"GET /operator/v1/status HTTP/1.0\r\nAuthorization: Bearer {self.token}\r\n\r\n".encode())
                s.settimeout(3)
                data = b""
                while True:                                  # клиент читает до EOF: сервер ОБЯЗАН закрыть соединение сам, без сборщика мусора
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                self.assertIn(b"200", data.split(b"\r\n")[0])
        for _ in range(50):
            if remote_api._SLOTS._value == remote_api.MAX_CONNECTIONS:
                break
            time.sleep(0.1)
        self.assertEqual(remote_api._SLOTS._value, remote_api.MAX_CONNECTIONS)      # слоты вернулись

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required")
    def test_silent_tcp_connection_does_not_freeze_the_tls_listener(self):
        ctx = self._tls_up()
        idle = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(idle.close)
        t0 = time.time()
        st, _ = self.req("GET", "/operator/v1/status", self.token, ctx=ctx, scheme="https")
        self.assertEqual(st, 200)
        self.assertLess(time.time() - t0, 5)

    def test_deadline_covers_receiving_only_not_a_long_tool_call(self):
        remote_api.stop()
        with mock.patch.object(remote_api, "REQUEST_DEADLINE", 1):
            remote_api.apply()
            real = remote_api.handle_agent

            def slow(*a, **k):
                time.sleep(2)                                # дольше срока на приём: ответ всё равно должен дойти
                return real(*a, **k)
            with mock.patch.object(remote_api, "handle_agent", slow):
                st, r = self.req("GET", "/agent/v1/tools", self.agent_rec["token"])
        self.assertEqual(st, 200)

    def test_exception_in_verify_request_does_not_kill_the_listener(self):
        with mock.patch.object(remote_api, "_allowed_ip", side_effect=RuntimeError("boom")):
            with self.assertRaises((urllib.error.URLError, OSError)):
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/operator/v1/status", timeout=3)
        self.assertEqual(self.req("GET", "/operator/v1/status", self.token)[0], 200)      # слушатель жив

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required")
    def test_tls_and_fingerprint(self):
        remote_api._write({**remote_api.DEFAULTS, "enabled": True, "port": self.port, "tls": True})
        remote_api.apply()
        self.assertTrue(remote_api.status()["running"], remote_api.status())
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        st, _ = self.req("GET", "/operator/v1/status", self.token, ctx=ctx, scheme="https")
        self.assertEqual(st, 200)
        fp = remote_api.status()["tls_fingerprint"]
        with socket.create_connection(("127.0.0.1", self.port)) as raw, ctx.wrap_socket(raw) as s:
            import hashlib
            self.assertEqual(hashlib.sha256(s.getpeercert(True)).hexdigest(), fp)
        self.assertEqual(os.stat(os.path.join(self.tmp, "tls", "key.pem")).st_mode & 0o777, 0o600)
        with self.assertRaises((urllib.error.URLError, OSError)):          # открытый HTTP на TLS-порту не работает
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/operator/v1/status", timeout=3)

    @unittest.skipUnless(shutil.which("openssl"), "openssl is required")
    def test_example_client_pins_the_certificate(self):
        import subprocess
        remote_api._write({**remote_api.DEFAULTS, "enabled": True, "port": self.port, "tls": True})
        remote_api.apply()
        fp = remote_api.status()["tls_fingerprint"]
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "remote_client.py")
        env = {**os.environ, "SA_URL": f"https://127.0.0.1:{self.port}", "SA_TOKEN": self.token}
        ok = subprocess.run([sys.executable, script, "plans"], env={**env, "SA_FINGERPRINT": fp}, capture_output=True, text=True, timeout=60)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["ok"])
        bad = subprocess.run([sys.executable, script, "plans"], env={**env, "SA_FINGERPRINT": "0" * 64}, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("mismatch", bad.stderr + bad.stdout)
        self.assertNotIn(self.token, bad.stdout + bad.stderr)
        none = subprocess.run([sys.executable, script, "plans"], env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(none.returncode, 0)                       # без закрепления отпечатка клиент молчит и токен не отправляет


class Telegram(Base):
    def setUp(self):
        super().setUp()
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": True})
        self.agent_rec = self.agent()
        self.op, self.token, self.secret = self.operator(telegram_chat_id=4242)
        self.sent = []
        p = mock.patch.object(telegram_bot, "_send", lambda token, chat, text: self.sent.append((chat, text)))
        p.start()
        self.addCleanup(p.stop)
        telegram_bot._NOTIFIED.clear()
        telegram_bot._STRANGERS.clear()

    def msg(self, chat, text, ctype="private"):
        telegram_bot._handle_update("T", {"update_id": 1, "message": {"chat": {"id": chat, "type": ctype}, "text": text}})

    def test_unknown_and_group_chats_are_ignored_and_answered_once(self):
        self.msg(999, "/plans")
        self.msg(999, "/plans")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("не привязан", self.sent[0][1])
        self.msg(4242, "/status", ctype="group")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("telegram:unknown_chat", self.audit_text())

    def test_status_plans_and_approve_with_totp(self):
        p = self.plan(self.agent_rec)
        self.msg(4242, "/plans")
        self.assertIn(p["id"], self.sent[-1][1])
        self.msg(4242, f"/approve {p['id']} {p['digest'][:12]}")                 # без кода
        self.assertIn("Формат", self.sent[-1][1])
        self.msg(4242, f"/approve {p['id']} {p['digest'][:12]} 000000")
        self.assertIn("неверен", self.sent[-1][1])
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["status"], "pending")
        self.msg(4242, f"/approve {p['id']} {p['digest'][:12]} {ops.totp_now(self.secret)}")
        self.assertIn("Одобрен", self.sent[-1][1])
        self.assertEqual([x for x in plans._plans() if x["id"] == p["id"]][0]["approval"]["by"], "operator:alice")

    def test_read_only_operator_cannot_approve_and_l3_is_refused(self):
        ro, tok, sec = self.operator("viewer", scopes=("read",), telegram_chat_id=777)
        p = self.plan(self.agent_rec)
        self.msg(777, f"/approve {p['id']} {p['digest'][:12]} {ops.totp_now(sec)}")
        self.assertIn("нет права", self.sent[-1][1])
        p3 = self.plan(self.agent_rec, level="L3")
        self.msg(4242, f"/approve {p3['id']} {p3['digest'][:12]} {ops.totp_now(self.secret)}")
        self.assertIn("L3", self.sent[-1][1])

    def test_remote_approval_switch_off(self):
        remote_api._write({**remote_api.DEFAULTS, "remote_approval": False})
        p = self.plan(self.agent_rec)
        self.msg(4242, f"/approve {p['id']} {p['digest'][:12]} {ops.totp_now(self.secret)}")
        self.assertIn("выключено", self.sent[-1][1])

    def test_notifications_go_only_to_approvers_once(self):
        ro, tok, sec = self.operator("viewer", scopes=("read",), telegram_chat_id=777)
        p = self.plan(self.agent_rec)
        telegram_bot.notify_new_plans("T")
        telegram_bot.notify_new_plans("T")
        self.assertEqual([c for c, _ in self.sent], [4242])
        self.assertIn(f"/approve {p['id']}", self.sent[0][1])
        self.assertNotIn(self.token, self.sent[0][1])
        self.sent.clear()
        p3 = self.plan(self.agent_rec, level="L3")
        telegram_bot.notify_new_plans("T")
        self.assertIn("системным окном", self.sent[0][1])
        self.assertNotIn(f"/approve {p3['id']}", self.sent[0][1])


    def test_disabled_bot_does_not_handle_messages_and_stops(self):
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers["Content-Length"]))
                calls.append(self.path.split("/")[-1])
                raw = json.dumps({"ok": True, "result": [{"update_id": 9, "message": {"chat": {"id": 4242, "type": "private"}, "text": "/status"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        tok = "123456789:" + "A" * 35
        open(telegram_bot.TOKEN_FILE, "w").write(tok + "\n")
        remote_api._write({**remote_api.DEFAULTS, "telegram": {"enabled": False}})       # владелец выключил бота, пока шёл долгий опрос
        with mock.patch.object(telegram_bot, "API", f"http://127.0.0.1:{srv.server_address[1]}"):
            th = threading.Thread(target=telegram_bot._poll_loop, args=(tok, threading.Event()), daemon=True)
            th.start()
            th.join(timeout=10)
        self.assertFalse(th.is_alive())                                                    # поток завершился сам
        self.assertEqual(self.sent, [])                                                    # и сообщение не обработано
        # перезапуск: у старых потоков своё событие, новое им не «оживает»
        telegram_bot.apply()
        first = telegram_bot._RUN["stop"]
        telegram_bot.apply()
        self.assertTrue(first.is_set())
        self.assertIsNot(telegram_bot._RUN["stop"], first)
        telegram_bot.stop()

    def test_offset_is_persisted_and_locked_operator_is_told(self):
        telegram_bot._save_offset(77)
        self.assertEqual(telegram_bot._load_offset(), 77)
        self.assertEqual(os.stat(telegram_bot.OFFSET_FILE).st_mode & 0o777, 0o600)
        reg = ops._load()
        [x for x in reg["operators"] if x["id"] == self.op["id"]][0]["totp_locked"] = True
        ops._save(reg)
        p = self.plan(self.agent_rec)
        self.msg(4242, f"/approve {p['id']} {p['digest'][:12]} {ops.totp_now(self.secret)}")
        self.assertIn("заблокировано", self.sent[-1][1])

    def test_notification_and_plans_show_the_parameters(self):
        p = self.plan(self.agent_rec)
        plans._update(p["id"], params={"label": "after-hours snapshot"})
        telegram_bot.notify_new_plans("T")
        self.assertIn("after-hours snapshot", self.sent[-1][1])
        self.msg(4242, "/plans")
        self.assertIn("after-hours snapshot", self.sent[-1][1])

    def test_settings_need_dialog_and_token_is_private(self):
        good = "123456789:" + "A" * 35
        self.dialog = "reject"
        with self.assertRaises(core.ApiError):
            telegram_bot.set_settings({"token": good, "enabled": True})
        self.assertFalse(os.path.exists(telegram_bot.TOKEN_FILE))
        self.dialog = "approve"
        with mock.patch.object(telegram_bot, "apply"):
            telegram_bot.set_settings({"token": good, "enabled": True})
        self.assertEqual(os.stat(telegram_bot.TOKEN_FILE).st_mode & 0o777, 0o600)
        self.assertNotIn(good, json.dumps(telegram_bot.status()))
        self.assertNotIn(good, self.audit_text())
        with self.assertRaises(core.ApiError):
            telegram_bot.set_settings({"token": "not-a-token"})

    def test_bot_against_a_fake_telegram_server(self):
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path.split("/")[-1], body))
                out = {"ok": True, "result": {"username": "mybot"}}
                if self.path.endswith("getUpdates"):
                    out = {"ok": True, "result": [{"update_id": 5, "message": {"chat": {"id": 4242, "type": "private"}, "text": "/status"}}] if len(calls) == 1 else []}
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        with mock.patch.object(telegram_bot, "API", f"http://127.0.0.1:{srv.server_address[1]}"):
            r = telegram_bot._call("123456789:" + "A" * 35, "getMe", timeout=5)
            self.assertTrue(r["ok"])
            self.assertEqual(calls[0][0], "getMe")
            # настоящий цикл опроса: getUpdates → команда оператора → sendMessage со ответом, смещение растёт, чужие данные не нужны
            calls.clear()
            self.sent.clear()
            stop = threading.Event()
            open(telegram_bot.TOKEN_FILE, "w").write("123456789:" + "A" * 35 + "\n")
            remote_api._write({**remote_api.DEFAULTS, "telegram": {"enabled": True}})
            th = threading.Thread(target=telegram_bot._poll_loop, args=("123456789:" + "A" * 35, stop), daemon=True)
            th.start()
            for _ in range(50):
                if self.sent:
                    break
                time.sleep(0.1)
            stop.set()
            th.join(timeout=5)
            self.assertTrue(self.sent and self.sent[0][0] == 4242 and "Ожидают решения" in self.sent[0][1], self.sent)
            self.assertEqual(calls[0][0], "getUpdates")
            self.assertEqual(calls[0][1]["allowed_updates"], ["message"])


if __name__ == "__main__":
    unittest.main()
