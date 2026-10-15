"""Укрепление после финального ревью Linux: проверка владельца соединения (/proc/net/tcp), запрет подтверждений в терминале панели."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import server  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("sa_helper2", os.path.join(ROOT, "linux", "service-admin-approve"))
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader("sa_helper2", _loader))
_loader.exec_module(helper)

TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:2243 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 11111 1 0000000000000000 100 0 0 10 0
   1: 0100007F:C350 0100007F:2243 01 00000000:00000000 00:00000000 00000000  1001        0 22222 1 0000000000000000 20 4 30 10 -1
   2: 0100007F:C351 0100007F:2243 01 00000000:00000000 00:00000000 00000000  1000        0 33333 1 0000000000000000 20 4 30 10 -1
"""


class PeerUidTest(unittest.TestCase):
    def _file(self, text):
        f = tempfile.NamedTemporaryFile("w", delete=False)
        f.write(text)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_finds_owner_of_client_socket(self):
        p = self._file(TCP)
        self.assertEqual(server.peer_uid(0xC350, 0x2243, p), 1001)   # другой пользователь
        self.assertEqual(server.peer_uid(0xC351, 0x2243, p), 1000)

    def test_unknown_connection_fails_closed(self):
        self.assertIsNone(server.peer_uid(1234, 0x2243, self._file(TCP)))
        self.assertIsNone(server.peer_uid(1, 2, "/nonexistent/file"))


class PanelTerminalTest(unittest.TestCase):
    def test_detects_panel_server_among_ancestors(self):
        procs = {10: ["/usr/bin/bash"], 11: ["/usr/bin/python3", "/opt/service-admin/server.py", "--port", "8765"]}
        with mock.patch.object(os, "getppid", return_value=42):   # в контейнере родитель может быть PID 1
            self.assertFalse(helper.in_panel_terminal(read=lambda pid: procs.get(10)))
            self.assertTrue(helper.in_panel_terminal(read=lambda pid: procs.get(11)))


if __name__ == "__main__":
    unittest.main()
