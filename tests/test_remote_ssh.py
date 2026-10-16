# -*- coding: utf-8 -*-
"""Фаза 8, шаг 1: строка authorized_keys для удалённого агента по SSH. Ключ должен уметь ТОЛЬКО запустить мост MCP своего агента."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import agent_gateway as gw  # noqa: E402
import core  # noqa: E402

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEexamplekeyexamplekeyexamplekey1234"


class RemoteSsh(unittest.TestCase):
    def test_line_has_forced_command_and_restrict(self):
        line = gw.authorized_line("a1b2c3d", KEY + " me@laptop")
        self.assertTrue(line.startswith('command="'))
        self.assertIn("mcp_server.py", line)
        self.assertIn(" --agent a1b2c3d\",restrict ssh-ed25519 ", line)
        self.assertNotIn("\n", line)
        self.assertNotIn("port-forwarding", line)       # пробросы запрещены: restrict без исключений

    def test_rejects_anything_but_one_plain_public_key(self):
        for bad in ("", "   ", KEY + "\n" + KEY, 'command="id" ' + KEY, "no-pty " + KEY, "ssh-ed25519 AAAA", "ssh-dss AAAAB3NzaC1kc3MAAACBAexamplexxxxxxxx",
                    KEY + ' ";touch /tmp/x', "-----BEGIN OPENSSH PRIVATE KEY-----"):
            with self.assertRaises(core.ApiError, msg=repr(bad)) as c:
                gw.authorized_line("a1b2c3d", bad)
            self.assertEqual(c.exception.code, "gw.remote_key")

    def test_rejects_bad_agent_id(self):
        for bad in ("", "../x", "a1b2c3", "a1b2c3d;id", "A1B2C3D"):
            with self.assertRaises(core.ApiError):
                gw.authorized_line(bad, KEY)

    def test_rejects_quote_in_install_path(self):
        with mock.patch("setup.runtime_info", return_value={"python": '/opt/py"x/bin/python3'}):
            with self.assertRaises(core.ApiError) as c:
                gw.authorized_line("a1b2c3d", KEY)
        self.assertEqual(c.exception.code, "gw.remote_path")

    def test_single_quote_in_install_path_is_refused_not_emitted_broken(self):
        with mock.patch("setup.runtime_info", return_value={"python": "/opt/it's/bin/python3"}):
            with self.assertRaises(core.ApiError) as c:
                gw.authorized_line("a1b2c3d", KEY)
        self.assertEqual(c.exception.code, "gw.remote_path")

    def test_remote_info_types_and_unknown_agent(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.object(gw, "REG_FILE", os.path.join(tmp, "r.json")), mock.patch.object(gw, "_ssh_listening", return_value=True):
            r = gw.remote_info({})
            self.assertEqual([t["id"] for t in r["types"]], ["ssh", "api", "telegram"])
            self.assertEqual(r["types"][0]["status"], "available")
            self.assertEqual(r["types"][1]["status"], "available")   # удалённый API и Telegram реализованы
            with self.assertRaises(core.ApiError):
                gw.remote_info({"agent": "a1b2c3d"})


if __name__ == "__main__":
    unittest.main()
