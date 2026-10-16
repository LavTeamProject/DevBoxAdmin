# -*- coding: utf-8 -*-
"""Версии из Homebrew (Фаза 10, U3): список версионных формул, установки Node/Go, признак «можно удалить»."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import core  # noqa: E402
import runtimes  # noqa: E402

NAMES = ["node", "node@18", "node@20", "node@22", "node@24", "nodenv", "go", "go@1.22", "go@1.25", "openjdk", "openjdk@8", "openjdk@21", "ruby@3.3", "php@8.4"]


class Versions(unittest.TestCase):
    def listing(self, key, installed):
        with mock.patch.object(runtimes, "_brew_formulae", return_value=NAMES), mock.patch.object(runtimes, "_brew_installed_names", return_value=set(installed)), \
                mock.patch.object(runtimes.sys, "platform", "darwin"):
            return runtimes.brew_versions({"key": key})

    def test_latest_first_then_versions_by_number_descending(self):
        v = self.listing("node", {"node@20"})
        self.assertEqual([r["formula"] for r in v["available"]], ["node", "node@24", "node@22", "node@20", "node@18"])
        self.assertTrue(v["available"][0]["latest"])
        self.assertEqual([r["formula"] for r in v["available"] if r["installed"]], ["node@20"])

    def test_similar_names_are_not_versions(self):
        self.assertNotIn("nodenv", [r["formula"] for r in self.listing("node", set())["available"]])
        self.assertEqual([r["version"] for r in self.listing("go", set())["available"]], ["latest", "1.25", "1.22"])     # 1.25 > 1.22 численно, не строкой
        self.assertEqual([r["formula"] for r in self.listing("java", set())["available"]], ["openjdk", "openjdk@21", "openjdk@8"])

    def test_unknown_language_and_linux(self):
        with self.assertRaises(core.ApiError):
            runtimes.brew_versions({"key": "cobol"})
        with mock.patch.object(runtimes.sys, "platform", "linux"):
            self.assertEqual(runtimes.brew_versions({"key": "node"}), {"key": "node", "supported": False, "available": []})

    def test_formula_name_from_install_path(self):
        pre = runtimes.BREW_PREFIX
        self.assertEqual(runtimes.brew_formula_of({"real": f"{pre}/Cellar/node@22/22.1.0/bin/node", "bin": f"{pre}/opt/node@22/bin/node"}), "node@22")
        self.assertEqual(runtimes.brew_formula_of({"bin": f"{pre}/opt/go/bin/go"}), "go")
        self.assertEqual(runtimes.brew_formula_of({"home": f"{pre}/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"}), "openjdk@21")
        self.assertIsNone(runtimes.brew_formula_of({"bin": "/usr/bin/ruby"}))
        self.assertIsNone(runtimes.brew_formula_of({"bin": f"{os.path.expanduser('~')}/.nvm/versions/node/v20/bin/node"}))

    def test_removable_excludes_default_nvm_and_panel_python(self):
        pre = runtimes.BREW_PREFIX
        info = {"selected": "brew:node@22", "installs": [
            {"id": "brew:node@22", "source": "Homebrew", "bin": f"{pre}/opt/node@22/bin/node", "real": "/a"},
            {"id": "brew:node", "source": "Homebrew", "bin": f"{pre}/opt/node/bin/node", "real": "/b"},
            {"id": "nvm:v20", "source": "nvm", "bin": "/home/x/.nvm/versions/node/v20/bin/node", "real": "/c"},
            {"id": "brew:node@20", "source": "Homebrew", "bin": f"{pre}/opt/node@20/bin/node", "real": os.path.realpath(sys.executable)}]}
        runtimes._mark_removable(info)
        by = {i["id"]: i for i in info["installs"]}
        self.assertFalse(by["brew:node@22"]["removable"])          # выбрана по умолчанию
        self.assertTrue(by["brew:node"]["removable"])
        self.assertFalse(by["nvm:v20"]["removable"])               # не Homebrew: панель не удаляет
        self.assertFalse(by["brew:node@20"]["removable"])          # на ней работает панель

    def test_node_and_go_installs_see_versioned_formulae(self):
        pre = tempfile.mkdtemp()
        for d in ("node", "node@22", "go@1.25"):
            os.makedirs(os.path.join(pre, "opt", d, "bin"))
            open(os.path.join(pre, "opt", d, "bin", "go" if d.startswith("go") else "node"), "w").close()
            os.chmod(os.path.join(pre, "opt", d, "bin", "go" if d.startswith("go") else "node"), 0o755)
        with mock.patch.object(runtimes, "BREW_PREFIX", pre), mock.patch.object(runtimes, "HOME", tempfile.mkdtemp()), mock.patch.object(runtimes, "version_of", return_value="1"):
            self.assertEqual([i["id"] for i in runtimes.node_installs()], ["brew:node", "brew:node@22"])
            self.assertIn("brew:go@1.25", [i["id"] for i in runtimes.go_installs()])

    def test_formula_family_for_service_pages(self):
        names = ["postgresql@14", "postgresql@17", "postgresql@9", "postgresql-client", "mysql", "mysql@8.0", "mysql@8.4", "mysql-client"]
        with mock.patch.object(runtimes, "_brew_formulae", return_value=names), mock.patch.object(runtimes, "_brew_installed_names", return_value={"mysql@8.4"}), \
                mock.patch.object(runtimes.sys, "platform", "darwin"):
            pg = runtimes.formula_versions({"name": "postgresql@17"})
            my = runtimes.formula_versions({"name": "mysql"})
        self.assertEqual([r["formula"] for r in pg["available"]], ["postgresql@17", "postgresql@14", "postgresql@9"])   # базовой формулы нет — «последней» нет
        self.assertEqual([r["formula"] for r in my["available"]], ["mysql", "mysql@8.4", "mysql@8.0"])
        self.assertEqual([r["formula"] for r in my["available"] if r["installed"]], ["mysql@8.4"])
        for bad in ("", "a b", "x;rm", "../x"):
            with self.assertRaises(core.ApiError):
                runtimes.formula_versions({"name": bad})

    def test_node_can_only_select(self):
        with self.assertRaises(core.ApiError):
            runtimes.node_action({"action": "install"})


if __name__ == "__main__":
    unittest.main()


class UninstallBlocker(unittest.TestCase):
    def test_selected_and_panel_python_blocked(self):
        import runtimes
        st = {"node_default": "brew:node@20", "php": "brew:php@8.3",
              "env": {"java": {"JAVA_HOME": runtimes.BREW_PREFIX + "/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"}}}
        with mock.patch.object(runtimes, "load_state", return_value=st), mock.patch.object(runtimes, "panel_formula", return_value="python@3.12"):
            self.assertEqual(runtimes.uninstall_blocker("node@20"), "node")
            self.assertEqual(runtimes.uninstall_blocker("php@8.3"), "php")
            self.assertEqual(runtimes.uninstall_blocker("openjdk@17"), "java")
            self.assertEqual(runtimes.uninstall_blocker("python@3.12"), "python")      # на нём работает панель
            self.assertIsNone(runtimes.uninstall_blocker("node@22"))

    def test_go_plain_brew_id_and_registered_jdk(self):
        import runtimes
        cellar = runtimes.BREW_PREFIX + "/Cellar/openjdk@21/21.0.1/libexec/openjdk.jdk/Contents/Home"
        st = {"go_default": "brew", "env": {"java": {"JAVA_HOME": "/Library/Java/JavaVirtualMachines/openjdk-21.jdk/Contents/Home"}}}
        with mock.patch.object(runtimes, "load_state", return_value=st), mock.patch.object(runtimes, "panel_formula", return_value=None), \
             mock.patch("os.path.realpath", side_effect=lambda x: cellar if x.startswith("/Library/Java") else x):
            self.assertEqual(runtimes.uninstall_blocker("go"), "go")
            self.assertEqual(runtimes.uninstall_blocker("openjdk@21"), "java")

    def test_versions_card_marks_default(self):
        import runtimes
        with mock.patch.object(runtimes, "_brew_formulae", return_value=["node", "node@22", "node@20"]), \
             mock.patch.object(runtimes, "_brew_installed_names", return_value={"node@20", "node@22"}), \
             mock.patch.object(runtimes, "selected_formula", return_value="node@20"), mock.patch.object(runtimes, "panel_formula", return_value=None), \
             mock.patch.object(runtimes.sys, "platform", "darwin"):
            rows = {r["formula"]: r["default"] for r in runtimes.brew_versions({"key": "node"})["available"]}
        self.assertEqual(rows, {"node": False, "node@22": False, "node@20": True})


class ToolsCache(unittest.TestCase):
    def test_miss_is_not_cached_long(self):
        import time
        runtimes._tools["zz-new-tool"] = (time.time() - 5, None)
        with mock.patch.object(runtimes, "shell_probe", return_value={"zz-new-tool": "/x/zz"}) as p:
            self.assertEqual(runtimes.tools("zz-new-tool"), ["/x/zz"])
            self.assertEqual(p.call_count, 1)
        runtimes._tools.pop("zz-new-tool", None)
