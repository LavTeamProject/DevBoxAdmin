"""Тесты драйвера QEMU (ADR-0002) на подставном qemu-img: хранилище, клоны, копии, зависимые ВМ, переименование — без qemu и без root."""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vm  # noqa: E402
import vm_qemu  # noqa: E402

FAKE_QEMU_IMG = """#!/bin/sh
# подставной qemu-img: create [-f qcow2 -b BACK -F qcow2] FILE [SIZE] / convert -O qcow2 SRC DST
case "$1" in
  create) for last; do :; done; f="$last"; case "$last" in *G) eval f=\\${$(($#-1))};; esac; : > "$f";;
  convert) src=$4; dst=$5; cp "$src" "$dst";;
esac
"""


class QemuDriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bindir = os.path.join(self.tmp, "bin")
        os.makedirs(bindir)
        p = os.path.join(bindir, "qemu-img")
        with open(p, "w") as f:
            f.write(FAKE_QEMU_IMG)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        for patch in (mock.patch.object(vm_qemu, "ROOT", os.path.join(self.tmp, "vms")), mock.patch.object(vm_qemu, "IMAGES", os.path.join(self.tmp, "img")),
                      mock.patch.object(vm_qemu, "_tool", side_effect=lambda n: p if n == "qemu-img" else None)):
            patch.start()
            self.addCleanup(patch.stop)
        os.makedirs(vm_qemu.ROOT)
        self.d = vm_qemu.QemuDriver()

    def _base(self, name="base"):
        os.makedirs(self.d._dir(name), mode=0o700)
        open(self.d._disk(name), "w").close()
        for f, content in (("id_ed25519", "PRIVATE"), ("hostkey.pub", "ssh-ed25519 AAAAHOSTKEY comment")):
            with open(os.path.join(self.d._dir(name), f), "w") as fh:
                fh.write(content)
        self.d._save(name, {"name": name, "arch": "x86_64", "cpus": 2, "mem_mb": 1024, "disk_gb": 10, "ssh_port": 2222, "user": "sa",
                            "backing": None, "created": 0})

    def test_list_and_status(self):
        self._base()
        rows = self.d.list()
        self.assertEqual([(r["name"], r["source"], r["running"]) for r in rows], [("base", "local", False)])
        self.assertEqual(self.d.status("base")["state"], "stopped")

    def test_clone_records_backing_and_blocks_base_delete(self):
        self._base()
        self.d.clone("base", "ci-1")
        self.assertEqual(self.d._meta("ci-1")["backing"], "base")
        self.assertEqual(self.d.dependents("base"), ["ci-1"])
        with self.assertRaises(RuntimeError):
            self.d.delete("base")
        self.assertTrue(self.d.delete("ci-1"))
        self.assertTrue(self.d.delete("base"))

    def test_copy_is_independent(self):
        self._base()
        self.d.copy("base", "snap1")
        self.assertIsNone(self.d._meta("snap1")["backing"])
        self.assertEqual(self.d.dependents("base"), [])
        self.assertNotEqual(self.d._meta("snap1")["ssh_port"], 0)

    def test_rename_refused_for_base_with_clones(self):
        self._base()
        self.d.clone("base", "c1")
        with self.assertRaises(RuntimeError):
            self.d.rename("base", "other")
        self.d.delete("c1")
        self.d.rename("base", "other")
        self.assertEqual(self.d._meta("other")["name"], "other")

    def test_ip_registers_key_auth_with_pinned_host_key(self):
        self._base()
        self.assertEqual(self.d.ip("base"), "127.0.0.1:2222")
        user, pw, k = vm.CREDS["127.0.0.1:2222"]
        self.assertEqual((user, pw), ("sa", None))
        self.assertEqual(open(k["known_hosts"]).read().strip(), "sa-base ssh-ed25519 AAAAHOSTKEY")
        prefix, env = vm.ssh_cmd("127.0.0.1:2222")
        joined = " ".join(prefix)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertIn("PasswordAuthentication=no", joined)
        self.assertIn("HostKeyAlias=sa-base", joined)
        self.assertNotIn("SSHPASS", env)

    def test_clone_copies_keys(self):
        self._base()
        self.d.clone("base", "c1")
        self.assertTrue(os.path.exists(os.path.join(self.d._dir("c1"), "id_ed25519")))
        self.assertTrue(os.path.exists(os.path.join(self.d._dir("c1"), "hostkey.pub")))

    def test_bad_names_rejected(self):
        for bad in ("../x", "a b", "", "x" * 41):
            with self.assertRaises(ApiErrorType):
                self.d._dir(bad)

    def test_argv_isolation_and_seed(self):
        self._base()
        with mock.patch.object(vm_qemu, "arch", return_value="x86_64"), mock.patch.object(self.d, "system_binary", return_value="/usr/bin/qemu-system-x86_64"):
            cmd = self.d._argv("base", {"restrict": True, "fwd": {"ip": "203.0.113.5", "port": 443, "host": "git.example.com"}})
        net = cmd[cmd.index("-netdev") + 1]
        self.assertIn("restrict=on", net)
        self.assertIn("guestfwd=tcp:10.0.2.100:443-cmd:", net)
        self.assertIn("-serial", cmd)
        self.assertEqual(cmd[cmd.index("-serial") + 1], "none")  # журнал консоли гостя без лимита роста не пишем
        self.assertIn("vm_relay.py", net)
        self.assertTrue(net.endswith("203.0.113.5 443"))
        self.assertIn("hostfwd=tcp:127.0.0.1:2222-:22", net)
        with mock.patch.object(vm_qemu, "arch", return_value="x86_64"), mock.patch.object(self.d, "system_binary", return_value="/usr/bin/qemu-system-x86_64"):
            cmd2 = self.d._argv("base", {"seed_url": "http://10.0.2.2:5000/"})
        self.assertIn("restrict=on", cmd2[cmd2.index("-netdev") + 1])   # restrict ВСЕГДА, если не заказан явный internet
        self.assertIn("type=1,serial=ds=nocloud-net;s=http://10.0.2.2:5000/", cmd2)
        with mock.patch.object(vm_qemu, "arch", return_value="x86_64"), mock.patch.object(self.d, "system_binary", return_value="/usr/bin/qemu-system-x86_64"):
            cmd3 = self.d._argv("base", {"internet": True})
        self.assertNotIn("restrict=on", cmd3[cmd3.index("-netdev") + 1])

    def test_comma_in_path_is_doubled(self):
        self.assertEqual(vm_qemu._q("/a,b/c"), "/a,,b/c")


ApiErrorType = vm_qemu.ApiError

if __name__ == "__main__":
    unittest.main()
