# -*- coding: utf-8 -*-
"""Управление Python и пакетами Homebrew: разбор зависимостей («можно удалить»), защиты при удалении версий, удаление папок uv-Python."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import brewsvc  # noqa: E402
import core  # noqa: E402
import runtimes  # noqa: E402


def formula(name, on_request=False, deps=(), version="1.0"):
    return {"name": name, "desc": name, "installed": [{"version": version, "installed_on_request": on_request,
                                                      "runtime_dependencies": [{"full_name": d} for d in deps]}], "versions": {"stable": version}}


class BuildApps(unittest.TestCase):
    def test_origin_used_by_removable_and_summary(self):
        data = {"formulae": [formula("app", True, ["lib", "tls"]), formula("lib", False, ["tls"]), formula("tls"), formula("orphan"), formula("old-orphan", False, ["orphan"])],
                "casks": []}
        r = brewsvc.build_apps(data, {"tls": 2048, "orphan": 1024, "old-orphan": 512})
        by = {a["name"]: a for a in r["apps"]}
        self.assertTrue(by["app"]["on_request"] and not by["app"]["removable"])
        self.assertEqual(by["tls"]["used_by"], ["app", "lib"])
        self.assertFalse(by["tls"]["removable"])                           # нужен вручную поставленному пакету
        self.assertTrue(by["orphan"]["removable"] and by["old-orphan"]["removable"])      # цепочка зависимостей, на которую никто не опирается
        self.assertEqual(by["tls"]["size_mb"], 2.0)
        s = r["summary"]
        self.assertEqual((s["formulae"], s["manual"], s["deps"], s["removable"]), (5, 1, 4, 2))
        self.assertEqual(s["removable_mb"], 1.5)

    def test_tap_names_and_cask_dependencies(self):
        data = {"formulae": [formula("lib", False), formula("x", True, ["homebrew/core/lib"])],
                "casks": [{"token": "fancy", "name": ["Fancy"], "installed": "1", "depends_on": {"formula": ["lib2"]}}]}
        data["formulae"].append(formula("lib2", False))
        r = brewsvc.build_apps(data, {})
        by = {a["name"]: a for a in r["apps"]}
        self.assertEqual(by["lib"]["used_by"], ["x"])
        self.assertFalse(by["lib2"]["removable"])                          # нужен приложению (cask)
        self.assertEqual(by["fancy"]["type"], "cask")
        self.assertIsNone(by["lib"]["size_mb"])

    def test_self_dependency_and_unknown_deps_are_ignored(self):
        data = {"formulae": [formula("a", True, ["a", "ghost"])], "casks": []}
        r = brewsvc.build_apps(data, {})
        self.assertEqual(r["apps"][0]["deps"], [])

    def test_read_only_brew_calls_never_auto_update(self):
        self.assertEqual(brewsvc.RO_ENV["HOMEBREW_NO_AUTO_UPDATE"], "1")
        self.assertNotIn("HOMEBREW_NO_AUTO_UPDATE", core.ENV)              # установка и обновление работают как раньше


class PythonGuards(unittest.TestCase):
    def installs(self, *items):
        base = {"real": "/x", "bin": "/x/bin/python3", "version": "3.12.1"}
        return [{**base, **i} for i in items]

    def test_install_validates_version_and_method(self):
        for body in ({"version": "2.7", "via": "brew"}, {"version": "3.12; rm", "via": "brew"}, {"version": "3.12", "via": "pip"}, {}):
            with self.assertRaises(core.ApiError):
                runtimes.python_install(body)
        with mock.patch.object(runtimes, "start_job", return_value="1") as sj:
            runtimes.python_install({"version": "3.12", "via": "brew"})
        self.assertEqual(sj.call_args[0][1], [runtimes.BREW, "install", "--formula", "python@3.12"])
        with mock.patch.object(runtimes, "uv_path", return_value="/u/uv"), mock.patch.object(runtimes, "start_job", return_value="1") as sj:
            runtimes.python_install({"version": "3.13", "via": "uv"})
        self.assertEqual(sj.call_args[0][1], ["/u/uv", "python", "install", "3.13"])
        with mock.patch.object(runtimes, "uv_path", return_value=None), self.assertRaises(core.ApiError) as c:
            runtimes.python_install({"version": "3.13", "via": "uv"})
        self.assertEqual(c.exception.code, "lang.tool_not_found")

    def test_uninstall_guards(self):
        inst = self.installs({"id": "system", "source": "macOS / Xcode CLT"}, {"id": "pyorg:3.12", "source": "python.org"},
                             {"id": "brew:python@3.12", "source": "Homebrew", "real": "/b/3.12"}, {"id": "brew:python@3.11", "source": "Homebrew", "real": "/b/3.11"})
        with mock.patch.object(runtimes, "python_installs", return_value=inst):
            for ident, code in (("system", "lang.uninstall_unsupported"), ("pyorg:3.12", "lang.uninstall_unsupported"), ("zzz", "lang.version_unknown")):
                with self.assertRaises(core.ApiError, msg=ident) as c:
                    runtimes.python_uninstall({"id": ident})
                self.assertEqual(c.exception.code, code)
            with mock.patch.object(runtimes, "load_state", return_value={"python_default": "brew:python@3.11"}), self.assertRaises(core.ApiError) as c:
                runtimes.python_uninstall({"id": "brew:python@3.11"})
            self.assertEqual(c.exception.code, "lang.uninstall_default")
            with mock.patch.object(os.path, "realpath", side_effect=lambda p: "/b/3.12" if p == sys.executable else p), self.assertRaises(core.ApiError) as c:
                runtimes.python_uninstall({"id": "brew:python@3.12"})
            self.assertEqual(c.exception.code, "lang.uninstall_panel")        # на этой версии работает сама панель
            with mock.patch.object(runtimes, "start_job", return_value="1") as sj:
                runtimes.python_uninstall({"id": "brew:python@3.11"})
            self.assertEqual(sj.call_args[0][1], [runtimes.BREW, "uninstall", "--formula", "python@3.11"])

    def test_pip_actions_validate_and_respect_pep668(self):
        for body in ({"action": "pip-install", "name": "a;b"}, {"action": "pip-install", "name": "../x"}, {"action": "pip-uninstall", "name": "pip"}, {"action": "pip-uninstall", "name": "Setuptools"}):
            with mock.patch.object(runtimes, "python_installs", return_value=[]), mock.patch.object(runtimes, "active", return_value=("/p/python3", {})), \
                    mock.patch.object(runtimes, "_externally_managed", return_value=False), self.assertRaises(core.ApiError, msg=str(body)):
                runtimes.python_pip(body)
        with mock.patch.object(runtimes, "python_installs", return_value=[]), mock.patch.object(runtimes, "active", return_value=("/p/python3", {})), \
                mock.patch.object(runtimes, "_externally_managed", return_value=True), self.assertRaises(core.ApiError) as c:
            runtimes.python_pip({"action": "pip-install", "name": "requests"})
        self.assertEqual(c.exception.code, "lang.externally_managed")
        with mock.patch.object(runtimes, "python_installs", return_value=[]), mock.patch.object(runtimes, "active", return_value=("/p/python3", {})), \
                mock.patch.object(runtimes, "_externally_managed", return_value=False), mock.patch.object(runtimes, "start_job", return_value="1") as sj:
            runtimes.python_pip({"action": "pip-uninstall", "name": "requests"})
        self.assertEqual(sj.call_args[0][1], ["/p/python3", "-m", "pip", "uninstall", "-y", "requests"])

    def test_uv_directories_are_removed_only_inside_the_uv_root(self):
        root = tempfile.mkdtemp()
        outside = tempfile.mkdtemp()
        real = os.path.join(root, "cpython-3.13.15-macos-aarch64-none")
        os.makedirs(os.path.join(real, "bin"))
        open(os.path.join(real, "bin", "python3"), "w").close()
        os.symlink(real, os.path.join(root, "cpython-3.13-macos-aarch64-none"))
        other = os.path.join(root, "cpython-3.12.1-macos-aarch64-none")
        os.makedirs(os.path.join(other, "bin"))
        alias_bin = os.path.join(root, "cpython-3.13-macos-aarch64-none", "bin", "python3")
        self.assertEqual(len(runtimes.uv_python_dirs(alias_bin, root)), 2)
        logs = []
        runtimes._remove_uv_python(alias_bin, root)(logs.append)
        self.assertEqual(sorted(os.listdir(root)), ["cpython-3.12.1-macos-aarch64-none"])          # чужая версия цела
        evil = os.path.join(outside, "bin")
        os.makedirs(evil)
        self.assertEqual(runtimes.uv_python_dirs(os.path.join(evil, "python3"), root), [])        # вне каталога uv — не трогаем
        with self.assertRaises(RuntimeError):
            runtimes._remove_uv_python(os.path.join(evil, "python3"), root)(logs.append)
        self.assertTrue(os.path.isdir(evil))


if __name__ == "__main__":
    unittest.main()
