# -*- coding: utf-8 -*-
"""Каталог профилей (Фаза 10, U4a): каждый инструмент описан один раз, у профилей есть роли, у сервисов — признак «запущено», состояния пунктов."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import profiles  # noqa: E402


class Catalog(unittest.TestCase):
    def test_ids_unique(self):
        for plist in (profiles.PROFILES_MAC, profiles.PROFILES_LINUX):
            ids = [p["id"] for p in plist]
            self.assertEqual(len(ids), len(set(ids)))
            for p in plist:
                self.assertEqual(len({i["id"] for i in p["items"]}), len(p["items"]), f"duplicate item in {p['id']}")

    def test_each_tool_is_defined_once_profiles_only_override_required(self):
        by_id = {}
        for p in profiles.PROFILES_MAC:
            for i in p["items"]:
                base = {k: v for k, v in i.items() if k != "required"}
                self.assertEqual(by_id.setdefault(i["id"], base), base, f"{i['id']} differs between profiles")
        for iid, item in profiles.ITEMS.items():          # общий каталог = то, что реально используется профилями
            self.assertTrue(any(i["id"] == iid for p in profiles.PROFILES_MAC for i in p["items"]), f"unused item {iid}")

    def test_new_stacks_cover_what_a_backend_and_web_developer_needs(self):
        by = {p["id"]: {i["id"]: i for i in p["items"]} for p in profiles.PROFILES_MAC}
        for pid, need in (("backend-php", {"php", "composer", "herd", "mysql", "redis", "docker", "node"}),
                          ("backend-node", {"node", "pnpm", "postgresql", "redis", "docker"}),
                          ("backend-python", {"python", "uv", "pipx", "postgresql", "docker"}),
                          ("backend-go", {"go", "postgresql", "redis", "docker"}),
                          ("web", {"node", "pnpm", "yarn", "git", "chrome"})):
            self.assertTrue(need <= set(by[pid]), (pid, need - set(by[pid])))
        self.assertTrue(by["backend-php"]["php"]["required"] and by["backend-php"]["composer"]["required"])
        self.assertTrue(by["web"]["node"]["required"])
        # одна политика Node: Homebrew (versioned formula), одинаково везде
        self.assertEqual({p["items"][[i["id"] for i in p["items"]].index("node")]["pkg"] for p in profiles.PROFILES_MAC if any(i["id"] == "node" for i in p["items"])}, {"node@22"})

    def test_detection_specs_are_shared_so_each_tool_is_probed_once(self):
        specs = profiles._unique_specs()
        total = sum(len(p["items"]) for p in profiles.PROFILES_MAC)
        self.assertLess(len(specs), total)                 # общие инструменты (gh, git, node…) проверяются один раз

    def fake_catalog(self, installed, running):
        results = lambda spec: {"installed": spec[1] in installed if spec[0] == "cmd" else False, "version": "1"}
        with mock.patch.object(profiles, "_detect", side_effect=results), mock.patch.object(profiles, "_services_running", return_value=running), \
                mock.patch.object(profiles, "PROFILES", profiles.PROFILES_MAC), mock.patch.dict(profiles._cache, {"t": 0.0, "data": None}):
            return profiles.catalog({"refresh": "1"})

    def test_running_is_reported_only_for_installed_services(self):
        d = self.fake_catalog({"psql", "redis-server"}, {"postgresql@17": True, "redis": False, "mysql": False})
        items = {i["id"]: i for p in d["profiles"] if p["id"] == "backend" for i in p["items"]}
        self.assertTrue(items["postgresql"]["running"])
        self.assertIs(items["redis"]["running"], False)
        self.assertIsNone(items["mysql"]["running"])       # не установлен — «запущено» не определено
        self.assertEqual(items["mysql"]["service"], "mysql")

    def test_running_unknown_when_services_cannot_be_read(self):
        d = self.fake_catalog({"psql"}, None)
        items = {i["id"]: i for p in d["profiles"] if p["id"] == "backend" for i in p["items"]}
        self.assertIsNone(items["postgresql"]["running"])

    def test_item_states_are_exposed(self):
        d = self.fake_catalog(set(), {})
        prof = {p["id"]: p for p in d["profiles"]}
        flutter = {i["id"]: i for i in prof["flutter"]["items"]}
        self.assertTrue(flutter["android-sdk"]["consent"])            # лицензии Android SDK — согласие человека
        self.assertEqual(flutter["android-studio"]["install"], "manual")
        ios = {i["id"]: i for i in prof["ios"]["items"]}
        self.assertEqual((ios["xcode"]["install"], ios["runtimes"]["install"], ios["clt"]["install"]), ("manual", "later", "setup"))
        self.assertIn("php", prof["backend-php"]["missing_required"])

    def test_plan_for_a_new_stack_only_lists_missing_required_items(self):
        d = self.fake_catalog({"php"}, {})
        with mock.patch.object(profiles, "catalog", return_value=d), mock.patch.object(profiles, "_brew_bin", return_value="/x/brew"):
            p = profiles.plan({"profile": "backend-php", "scope": "required"})
        self.assertEqual([i["id"] for i in p["items"] if i["action"] == "install"], ["composer"])


if __name__ == "__main__":
    unittest.main()
