# -*- coding: utf-8 -*-
"""Наборы сервисов, группы запуска и порты (Фаза 10): разбор lsof, статусы наборов, шаги действий, защита ввода и хранения."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import core  # noqa: E402
import ports  # noqa: E402
import service_sets as ss  # noqa: E402

LSOF = """p100
cpostgres
Lme
n127.0.0.1:5432
n[::1]:5432
p200
cnginx
Lroot
n*:80
n*:443
p300
cControlCenter
Lme
n*:5000
p400
cweird
Lme
nnot-a-port
"""


class Ports(unittest.TestCase):
    def test_parse_lsof_dedupes_labels_and_flags_network_listeners(self):
        rows = ports.parse_lsof(LSOF)
        self.assertEqual([(r["port"], r["cmd"]) for r in rows], [(80, "nginx"), (443, "nginx"), (5000, "ControlCenter"), (5432, "postgres")])
        by = {r["port"]: r for r in rows}
        self.assertTrue(by[5432]["local_only"] and not by[80]["local_only"])
        self.assertEqual(by[5432]["label"], "PostgreSQL")
        self.assertEqual(by[5000]["label"], "AirPlay (macOS)")          # не «dev server»
        self.assertEqual(sum(1 for r in rows if r["port"] == 5432), 1)  # IPv4+IPv6 одного процесса схлопнуты


class Sets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for p in [mock.patch.object(core, "STATE_FILE", os.path.join(self.tmp, "state.json")), mock.patch.object(core, "DATA_DIR", self.tmp),
                  mock.patch.object(ss.sys, "platform", "darwin")]:
            p.start()
            self.addCleanup(p.stop)

    def listing(self, installed, running):
        with mock.patch.object(ss, "_installed", return_value=set(installed)), mock.patch.object(ss, "_services", return_value=running):
            return ss.list_sets()

    def test_status_of_presets(self):
        d = self.listing({"nginx", "mysql", "redis"}, {"nginx": True, "mysql": False, "redis": True})
        laravel = next(s for s in d["sets"] if s["id"] == "laravel")
        self.assertEqual((laravel["installed"], laravel["running"], laravel["total"]), (3, 2, 5))
        php = next(m for m in laravel["members"] if m["name"] == "php")
        self.assertFalse(php["installed"])

    def test_start_skips_missing_services_and_install_only_adds_missing(self):
        calls = []
        with mock.patch.object(ss, "_installed", return_value={"nginx", "redis"}), mock.patch.object(ss, "start_steps", side_effect=lambda label, steps, kind: calls.append((label, steps, kind)) or "7"):
            self.assertEqual(ss.run_action({"id": "laravel", "action": "start"}), {"job": "7"})
            ss.run_action({"id": "laravel", "action": "install"})
        start_cmds = [s[1] for s in calls[0][1]]
        self.assertEqual(start_cmds, [[ss.BREW, "services", "start", "nginx"], [ss.BREW, "services", "start", "redis"]])
        self.assertTrue(all(s[2].get("optional") for s in calls[0][1]))        # один упавший сервис не останавливает остальные
        self.assertEqual([s[1][-1] for s in calls[1][1]], ["php", "mysql", "mailpit"])
        self.assertEqual(calls[0][2], "svcgroup")

    def test_nothing_to_do_and_bad_input(self):
        with mock.patch.object(ss, "_installed", return_value=set()):
            with self.assertRaises(core.ApiError) as c:
                ss.run_action({"id": "node", "action": "start"})
            self.assertEqual(c.exception.code, "sets.nothing_to_do")
        for body in ({"id": "laravel", "action": "rm -rf"}, {"id": "nope", "action": "start"}, {}):
            with self.assertRaises(core.ApiError):
                ss.run_action(body)

    def test_user_groups_validation_and_storage(self):
        g = ss.create_group({"name": "Проект Shop", "members": ["nginx", "mysql", "nginx"]})["group"]
        self.assertEqual(g["members"], ["nginx", "mysql"])                      # без повторов
        for body in ({"name": "", "members": ["a"]}, {"name": "x", "members": []}, {"name": "x", "members": ["a;b"]}, {"name": "x", "members": "nginx"},
                     {"name": "x", "members": ["../etc"]}, {"name": "проект shop", "members": ["a"]}, {"name": "x" * 41, "members": ["a"]}):
            with self.assertRaises(core.ApiError, msg=str(body)):
                ss.create_group(body)
        self.assertEqual([x["id"] for x in ss._groups()], [g["id"]])
        ss.delete_group({"id": g["id"]})
        self.assertEqual(ss._groups(), [])
        with self.assertRaises(core.ApiError):
            ss.delete_group({"id": "g000000"})

    def test_group_limit_and_linux(self):
        for i in range(ss.MAX_GROUPS):
            ss.create_group({"name": f"g{i}", "members": ["redis"]})
        with self.assertRaises(core.ApiError) as c:
            ss.create_group({"name": "one more", "members": ["redis"]})
        self.assertEqual(c.exception.code, "sets.too_many")
        with mock.patch.object(ss.sys, "platform", "linux"):
            self.assertEqual(ss.list_sets(), {"supported": False, "sets": []})
            with self.assertRaises(core.ApiError):
                ss.run_action({"id": "laravel", "action": "start"})


if __name__ == "__main__":
    unittest.main()
