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
