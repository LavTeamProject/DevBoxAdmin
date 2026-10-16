"""Поиск пакетов Homebrew: по имени и по описанию, с описанием и версией из `brew info --json=v2`."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import brewsvc  # noqa: E402


def fake_run(cmd, timeout=60, cwd=None, env=None):
    if cmd[1] == "search":
        kind, desc = cmd[2], "--desc" in cmd
        if kind == "--formula":
            return 0, ("==> Formulae\njq: Lightweight JSON processor\n" if desc else "==> Formulae\njq ✔\njo\n"), ""
        return 0, "", ""
    if cmd[1] == "info":
        return 0, json.dumps({"formulae": [{"name": "jq", "desc": "JSON processor", "versions": {"stable": "1.8.2"}},
                                           {"name": "jo", "desc": "JSON output from a shell", "versions": {"stable": "1.9"}}], "casks": []}), ""
    if cmd[1] == "list":
        return 0, "jq\n", ""
    return 1, "", ""


class Search(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(brewsvc, "run", side_effect=fake_run), mock.patch.object(brewsvc.sys, "platform", "darwin")):
            p.start()
            self.addCleanup(p.stop)

    def test_by_name_adds_desc_and_version(self):
        r = {x["name"]: x for x in brewsvc.search_apps({"q": "jq"})["results"]}
        self.assertEqual((r["jq"]["installed"], r["jq"]["version"], r["jo"]["desc"]), (True, "1.8.2", "JSON output from a shell"))

    def test_by_description(self):
        r = brewsvc.search_apps({"q": "json processor", "desc": "1"})["results"]
        self.assertEqual([(x["name"], x["installed"]) for x in r], [("jq", True)])
        self.assertEqual(r[0]["desc"], "Lightweight JSON processor")

    def test_query_validation(self):
        for bad in ({"q": "a;b"}, {"q": "x", "desc": "1"}, {"q": "rm -rf /"}, {"q": "--eval-all", "desc": "1"}, {"q": "-x y", "desc": "1"}):
            with self.assertRaises(brewsvc.ApiError):
                brewsvc.search_apps(bad)


if __name__ == "__main__":
    unittest.main()
