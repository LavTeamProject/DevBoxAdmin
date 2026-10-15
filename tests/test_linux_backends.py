"""Тесты Linux-бэкендов Л3 (apt, systemd, профили): разбор вывода инструментов на подставных данных — без root и без apt/systemd."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import aptsvc  # noqa: E402
import elevate  # noqa: E402
import systemdsvc  # noqa: E402
from core import ApiError  # noqa: E402

UNITS = """ssh.service loaded active running OpenBSD Secure Shell server
cron.service loaded active running Regular background program processing daemon
broken.service loaded failed failed A broken thing
ghost.service not-found inactive dead ghost.service
nginx.service loaded inactive dead A high performance web server
"""


class SystemdTest(unittest.TestCase):
    def test_parse_units(self):
        with mock.patch.object(systemdsvc, "run", return_value=(0, UNITS, "")):
            items = systemdsvc._scope_list(False)
        names = {i["name"]: i["status"] for i in items}
        self.assertEqual(names, {"ssh": "started", "cron": "started", "broken": "error", "nginx": "none"})  # not-found пропущен
        self.assertEqual(items[0]["scope"], "system")

    def test_unit_name_validation(self):
        for bad in ("../x", "a b", "", "x;y", "a" * 200):
            with self.assertRaises(ApiError):
                systemdsvc.known_service(bad)

    def test_system_service_action_needs_elevation(self):
        svc = {"name": "nginx", "unit": "nginx.service", "scope": "system", "status": "none"}
        with mock.patch.object(systemdsvc, "known_service", return_value=svc), \
                mock.patch.object(systemdsvc.elevate, "run_admin", return_value={"terminal": "sudo systemctl restart nginx.service"}) as ra:
            r = systemdsvc.service_action({"name": "nginx", "action": "restart"})
        self.assertIn("terminal", r)
        self.assertEqual(ra.call_args[0][1], ["systemctl", "restart", "nginx.service"])

    def test_bad_action_rejected(self):
        with self.assertRaises(ApiError):
            systemdsvc.service_action({"name": "ssh", "action": "mask"})


class AptTest(unittest.TestCase):
    def test_package_name_validation(self):
        for bad in ("Foo", "a b", "a;rm", "-y", "", "x" * 120):
            with self.assertRaises(ApiError):
                aptsvc.app_action({"name": bad, "action": "install"})

    def test_unknown_package_not_installed(self):
        with mock.patch.object(aptsvc, "run", return_value=(100, "", "E: No packages found")):
            with self.assertRaises(ApiError) as cm:
                aptsvc.app_action({"name": "nosuchpkg", "action": "install"})
        self.assertEqual(cm.exception.code, "srv.pkg_unknown")

    def test_install_goes_through_elevation_with_fixed_argv(self):
        with mock.patch.object(aptsvc, "run", return_value=(0, "ok", "")), \
                mock.patch.object(aptsvc.elevate, "run_admin", return_value={"job": 1}) as ra:
            aptsvc.app_action({"name": "htop", "action": "install"})
        self.assertEqual(ra.call_args[0][1], ["apt-get", "install", "-y", "htop"])

    def test_headless_returns_quoted_terminal_command(self):
        with mock.patch.object(elevate.platform_info, "has", return_value=False), mock.patch.object(elevate, "_abs", side_effect=lambda c: c):
            r = elevate.run_admin("x", ["apt-get", "install", "-y", "htop"])
        # sudo — по абсолютному пути и с -k (без билета); команду выполняет человек в своём терминале
        self.assertEqual(r, {"terminal": "/usr/bin/sudo -k -- apt-get install -y htop"})

    def test_gui_elevation_uses_absolute_pkexec(self):
        with mock.patch.object(elevate.platform_info, "has", return_value=True), mock.patch.object(elevate.os.path, "isfile", return_value=True), \
                mock.patch.object(elevate, "start_steps", return_value=7) as st:
            r = elevate.run_admin("x", ["/usr/bin/apt-get", "update"])
        self.assertEqual(r, {"job": 7})
        self.assertEqual(st.call_args[0][1][0][1][0], "/usr/bin/pkexec")

    def test_admin_argv_uses_absolute_path_not_env(self):
        argv = elevate.admin_argv(["ls", "-l"])  # ls есть в системных каталогах и на macOS, и на Linux
        self.assertTrue(argv[0].startswith("/"))
        self.assertNotIn("env", argv[0].split("/")[-1:])

    def test_upgradable_parse(self):
        out = "Listing...\nhtop/noble-updates 3.3.0-4 arm64 [upgradable from: 3.2.2-2]\n"
        with mock.patch.object(aptsvc, "run", return_value=(0, out, "")):
            self.assertEqual(aptsvc._upgradable(), {"htop": "3.3.0-4"})


if __name__ == "__main__":
    unittest.main()
