"""Тесты слоя «платформа»: запуск `python3 -m unittest discover -s tests` из корня репозитория (stdlib, без привилегий; годится для CI на любой ОС)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import platform_info  # noqa: E402

OS_RELEASE = 'PRETTY_NAME="Ubuntu 24.04.1 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n'


class PlatformTest(unittest.TestCase):
    def setUp(self):
        platform_info._CACHE.update(at=0.0, value=None)

    def test_os_release_parse(self):
        with tempfile.NamedTemporaryFile("w", suffix=".rel", delete=False) as f:
            f.write(OS_RELEASE)
        try:
            r = platform_info._os_release(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual((r["ID"], r["VERSION_ID"]), ("ubuntu", "24.04"))
        self.assertEqual(platform_info._os_release("/nonexistent/os-release"), {})

    def _linux(self, tools, display=True, systemd=True):
        return [mock.patch.object(sys, "platform", "linux"),
                mock.patch.object(platform_info, "_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04", "PRETTY_NAME": "Ubuntu 24.04"}),
                mock.patch.object(platform_info, "_has", side_effect=lambda *n: any(x in tools for x in n)),
                mock.patch.object(platform_info, "_has_sys", side_effect=lambda *n: any(x in tools for x in n)),
                mock.patch.object(platform_info, "_display", return_value=display),
                mock.patch.object(platform_info, "_systemd", return_value=systemd)]

    def _compute(self, patches):
        for p in patches:
            p.start()
        self.addCleanup(mock.patch.stopall)
        return platform_info.compute()

    def test_linux_desktop(self):
        r = self._compute(self._linux({"apt-get", "zenity", "pkexec", "sudo", "notify-send"}))
        c = r["capabilities"]
        self.assertEqual(r["os"], "linux")
        self.assertFalse(r["headless"])
        self.assertTrue(c["pkg.apt"] and c["service.systemd"] and c["approval.dialog"] and c["approval.sudo"] and c["elevation"])
        self.assertFalse(c["mobile.xcode"] or c["herd"] or c["orbstack"] or c["vm.driver"] or c["service.brew"])

    def test_linux_headless_has_no_gui_dialog(self):
        r = self._compute(self._linux({"apt-get", "zenity", "sudo"}, display=False))
        c = r["capabilities"]
        self.assertTrue(r["headless"])
        self.assertFalse(c["approval.dialog"])  # zenity есть, но экрана нет — диалог невозможен
        self.assertTrue(c["approval.sudo"])

    def test_macos(self):
        patches = [mock.patch.object(sys, "platform", "darwin"), mock.patch.object(platform_info, "_has", side_effect=lambda *n: True)]
        r = self._compute(patches)
        c = r["capabilities"]
        self.assertEqual(r["os"], "macos")
        self.assertTrue(c["mobile.xcode"] and c["herd"] and c["approval.dialog"] and c["vm.driver"])
        self.assertFalse(c["pkg.apt"] or c["service.systemd"])

    def test_info_is_cached(self):
        with mock.patch.object(platform_info, "compute", return_value={"capabilities": {}}) as m:
            platform_info.info()
            platform_info.info()
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class StatsLinuxTest(unittest.TestCase):
    """Разбор /proc и /sys — чистые функции от содержимого файлов."""
    def _with(self, files):
        import stats_linux
        return mock.patch.object(stats_linux, "_read", side_effect=lambda p, d="": files.get(p, d)), stats_linux

    def test_cpu_ticks(self):
        p, s = self._with({"/proc/stat": "cpu  1 2 3 4 5 6 7 8\ncpu0 100 10 50 800 20 1 2 3\ncpu1 5 0 5 90 0 0 0 0\nintr 1"})
        with p:
            self.assertEqual(s.cpu_ticks(), [(100, 50 + 1 + 2 + 3, 800 + 20, 10), (5, 5, 90, 0)])

    def test_memory(self):
        meminfo = "MemTotal:  8000 kB\nMemFree: 1000 kB\nMemAvailable: 6000 kB\nBuffers: 100 kB\nCached: 400 kB\nSReclaimable: 100 kB\nSwapTotal: 2000 kB\nSwapFree: 1500 kB\nHugePages_Total:  5\n"
        p, s = self._with({"/proc/meminfo": meminfo, "/proc/pressure/memory": "some avg10=12.00 avg60=0 avg300=0 total=1\n"})
        with p:
            m = s.memory()
        self.assertEqual((m["total"], m["used"], m["cached"], m["swap_used"]), (8000 * 1024, 2000 * 1024, 600 * 1024, 500 * 1024))
        self.assertEqual(m["pressure"], "warning")

    def test_diskstats_and_net(self):
        ds = "   8       0 sda 1 0 100 0 1 0 200 0 0 0 0\n   8       1 sda1 1 0 999 0 1 0 999 0 0 0 0\n 259 0 nvme0n1 1 0 10 0 1 0 20 0 0 0 0\n"
        nd = "Inter-|   Receive\n face |bytes\n    lo: 500 0 0 0 0 0 0 0 600 0 0 0 0 0 0 0\n  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
        p, s = self._with({"/proc/diskstats": ds, "/proc/net/dev": nd})
        with p:
            self.assertEqual(s.disk_io_bytes(), ((100 + 10) * 512, (200 + 20) * 512))
            self.assertEqual(s.net_bytes(), (1000, 2000))


class RouteGuardTest(unittest.TestCase):
    def setUp(self):
        platform_info._CACHE.update(at=0.0, value=None)

    def test_macos_only_routes_refused_on_linux(self):
        with mock.patch.object(platform_info, "has", side_effect=lambda cap: False):
            self.assertEqual(platform_info.route_missing("/api/herd"), "herd")
            self.assertEqual(platform_info.route_missing("/api/herd/logs"), "herd")
            self.assertEqual(platform_info.route_missing("/api/mobile"), "mobile.toolchain")
            self.assertEqual(platform_info.route_missing("/api/mobile/runtimes"), "mobile.xcode")
            self.assertEqual(platform_info.route_missing("/api/mobile/screenshot"), "mobile.xcode")
            self.assertEqual(platform_info.route_missing("/api/activity-monitor"), "os.macos")
            self.assertIsNone(platform_info.route_missing("/api/herdsomething-else-not-a-prefix"))
            self.assertIsNone(platform_info.route_missing("/api/services"))

    def test_routes_open_when_capability_present(self):
        with mock.patch.object(platform_info, "has", return_value=True):
            self.assertIsNone(platform_info.route_missing("/api/herd"))
