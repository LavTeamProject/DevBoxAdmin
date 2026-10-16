import os
import tempfile
import unittest

import sites


class Hosts(unittest.TestCase):
    def test_custom_only(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("127.0.0.1 localhost\n255.255.255.255 broadcasthost\n::1 localhost\n# c\n127.0.0.1 app.test api.test # x\n")
        try:
            self.assertEqual(sites.hosts_entries(f.name), [{"ip": "127.0.0.1", "names": ["app.test", "api.test"]}])
        finally:
            os.unlink(f.name)

    def test_missing_file(self):
        self.assertEqual(sites.hosts_entries("/nonexistent/hosts"), [])


class Info(unittest.TestCase):
    def test_shape(self):
        d = sites.sites_info()
        self.assertEqual({p["id"] for p in d["parts"]}, {"dnsmasq", "mkcert", "nginx", "caddy"})
        for k in ("hosts", "herd", "mkcert_ca", "cloudflared"):
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()


class Dnsmasq(unittest.TestCase):
    def test_rule_detection(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.conf")
            open(p, "w").write("# c\naddress=/test/127.0.0.1\n")
            q = os.path.join(d, "b.conf")
            open(q, "w").write("address=/example.com/1.2.3.4\n")
            self.assertTrue(sites.dnsmasq_rule([q, p]))
            self.assertFalse(sites.dnsmasq_rule([q, "/nonexistent"]))


class SystemdState(unittest.TestCase):
    def test_active_parsing(self):
        from unittest import mock
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="active\n")):
            self.assertTrue(sites._systemd_active("nginx"))
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="inactive\n")):
            self.assertFalse(sites._systemd_active("nginx"))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertIsNone(sites._systemd_active("nginx"))
