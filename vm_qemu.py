# -*- coding: utf-8 -*-
"""Драйвер ВМ для Linux: QEMU напрямую, без root и без демона (ADR-0002, Фаза 6, Л4).
Хранилище: ~/.service-admin/vms/<имя>/{disk.qcow2, meta.json (0600: порт и пароль гостя), qemu.pid, qmp.sock, qemu.log}; образы — vm-images/.
Клон = qcow2 поверх неизменяемой основы; снимок/восстановление = полная копия. SSH — проброс на 127.0.0.1:<порт>.
Изоляция (`isolation`): гость без интернета и локальной сети, достижим только сервер CI (restrict=on + guestfwd -cmd: реле на один адрес)."""
import contextlib
import fcntl
import hashlib
import http.server
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http import HTTPStatus
from urllib.parse import urlsplit

import core
import vm
from core import DATA_DIR, ApiError

ROOT = os.path.join(DATA_DIR, "vms")
IMAGES = os.path.join(DATA_DIR, "vm-images")
FWD_IP = "10.0.2.100"            # адрес, на котором гость видит сервер CI
EFI_CANDIDATES = ("/usr/share/qemu-efi-aarch64/QEMU_EFI.fd", "/usr/share/AAVMF/AAVMF_CODE.fd")
CLOUD = {"aarch64": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img",
         "x86_64": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"}
DEFAULT_CPUS, DEFAULT_MEM_MB, DEFAULT_DISK_GB = 2, 4096, 20


def arch():
    return "aarch64" if platform.machine().lower() in ("aarch64", "arm64") else "x86_64"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _q(path):
    """Запятая в значении опции QEMU удваивается (иначе путь с запятой дописал бы чужие под-опции)."""
    return str(path).replace(",", ",,")


@contextlib.contextmanager
def _lock(name):
    """Блокировка ВМ на время проверки+действия (clone/delete/rename/start): задачи «runner» и «vm» не сериализуются ядром задач."""
    os.makedirs(ROOT, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(ROOT, f".lock-{name}"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _tool(name):
    return shutil.which(name, path=core.ENV["PATH"] + ":/usr/sbin:/usr/local/bin")


class QemuDriver(vm.Driver):
    name = "qemu"
    shutdown_cmd = "sync; sudo -n /sbin/shutdown -h now || sudo -n systemctl poweroff"

    @property
    def boot_timeout(self):  # без KVM загрузка в разы дольше
        return 180 if self.accel() == "kvm" else 1800

    @property
    def ssh_probe_timeout(self):
        return 30 if self.accel() == "kvm" else 120

    # ---------------------------------------------------------------- наличие
    def binary(self):
        return _tool("qemu-img")

    def system_binary(self):
        return _tool(f"qemu-system-{arch()}")

    def available(self):
        return bool(self.binary() and self.system_binary())

    def missing_packages(self):
        out = []
        if not self.binary():
            out.append("qemu-utils")
        if not self.system_binary():
            out.append("qemu-system-arm" if arch() == "aarch64" else "qemu-system-x86")
        if arch() == "aarch64" and not any(os.path.exists(p) for p in EFI_CANDIDATES):
            out.append("qemu-efi-aarch64")
        return out

    def accel(self):
        return "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg"

    # ---------------------------------------------------------------- хранилище
    def _dir(self, name):
        if not vm.NAME_RE.match(name or ""):
            raise ApiError("Invalid VM name", HTTPStatus.BAD_REQUEST, code="vm.bad_name")
        return os.path.join(ROOT, name)

    def _meta(self, name):
        try:
            with open(os.path.join(self._dir(name), "meta.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            raise ApiError("VM not found", HTTPStatus.NOT_FOUND, code="vm.not_found") from None

    def _save(self, name, meta):
        d = self._dir(name)
        os.makedirs(d, mode=0o700, exist_ok=True)
        tmp = os.path.join(d, "meta.json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        os.replace(tmp, os.path.join(d, "meta.json"))

    def _disk(self, name):
        return os.path.join(self._dir(name), "disk.qcow2")

    def _pid(self, name):
        """pid работающего qemu этой ВМ или None (pid-файл проверяется по командной строке процесса)."""
        try:
            with open(os.path.join(self._dir(name), "qemu.pid"), encoding="utf-8") as f:
                pid = int(f.read().strip())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "replace")
            return pid if self._disk(name) in cmd else None
        except (OSError, ValueError, ApiError):
            return None

    def dependents(self, name):
        out = []
        for n in self._names():
            try:
                if self._meta(n).get("backing") == name:
                    out.append(n)
            except ApiError:
                pass
        return out

    def _names(self):
        try:
            return sorted(n for n in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, n, "meta.json")))
        except OSError:
            return []

    # ---------------------------------------------------------------- Driver
    def list(self):
        rows = []
        for n in self._names():
            try:
                m = self._meta(n)
                disk = self._disk(n)
                st = os.stat(disk)
                running = self._pid(n) is not None
                rows.append({"name": n, "source": "local", "state": "running" if running else "stopped", "running": running,
                             "disk_gb": m.get("disk_gb"), "size_gb": round(st.st_blocks * 512 / 1e9, 1), "accessed": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
            except (OSError, ApiError):
                continue
        try:
            for f in sorted(os.listdir(IMAGES)):
                if f.endswith(".img"):
                    rows.append({"name": f, "source": "image", "state": "stopped", "running": False, "disk_gb": None,
                                 "size_gb": round(os.path.getsize(os.path.join(IMAGES, f)) / 1e9, 1), "accessed": ""})
        except OSError:
            pass
        return rows

    def ip(self, name):
        """Адрес гостя 127.0.0.1:порт. Вход — по ключу ВМ, ключ хоста гостя закреплён (known_hosts ВМ, StrictHostKeyChecking=yes)."""
        m = self._meta(name)
        addr = f"127.0.0.1:{m['ssh_port']}"
        d = self._dir(name)
        pub = open(os.path.join(d, "hostkey.pub"), encoding="utf-8").read().split()
        alias = f"sa-{name}"
        kh = os.path.join(d, "known_hosts")
        with open(kh, "w", encoding="utf-8") as f:
            f.write(f"{alias} {pub[0]} {pub[1]}\n")
        vm.CREDS[addr] = (m["user"], None, {"key": os.path.join(d, "id_ed25519"), "known_hosts": kh, "alias": alias})
        return addr

    def _keys_from(self, src, dst):
        for f in ("id_ed25519", "hostkey.pub"):
            shutil.copy2(os.path.join(self._dir(src), f), os.path.join(self._dir(dst), f))
            os.chmod(os.path.join(self._dir(dst), f), 0o600)

    def clone(self, src, dst):
        """Клон = qcow2 поверх диска `src` (src должен быть остановлен и остаётся неизменяемым, пока есть клоны)."""
        with _lock(src):
            if self._pid(src):
                raise RuntimeError("the source VM is running; stop it first")
            m = self._meta(src)
            qimg = self.binary()
            os.makedirs(self._dir(dst), mode=0o700, exist_ok=False)
            try:
                r = subprocess.run([qimg, "create", "-f", "qcow2", "-b", os.path.realpath(self._disk(src)), "-F", "qcow2", self._disk(dst)],
                                   capture_output=True, timeout=60)
                if r.returncode:
                    raise RuntimeError("qemu-img create failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])
                self._keys_from(src, dst)
                self._save(dst, dict(m, name=dst, backing=src, ssh_port=_free_port(), created=time.time()))
            except Exception:
                shutil.rmtree(self._dir(dst), ignore_errors=True)
                raise

    def copy_step(self, src, dst):
        return lambda log: self.copy(src, dst)

    def copy(self, src, dst):
        """Полная независимая копия (снимок/восстановление): cp --reflink=auto, затем сглаживание ссылки на основу."""
        with _lock(src):
            if self._pid(src):
                raise RuntimeError("the source VM is running; stop it first")
            m = self._meta(src)
            os.makedirs(self._dir(dst), mode=0o700, exist_ok=False)
            try:
                tmp = self._disk(dst) + ".part"
                r = subprocess.run([self.binary(), "convert", "-O", "qcow2", self._disk(src), tmp], capture_output=True, timeout=3600)  # сглаживает цепочку
                if r.returncode:
                    raise RuntimeError("qemu-img convert failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])
                os.replace(tmp, self._disk(dst))
                self._keys_from(src, dst)
                self._save(dst, dict(m, name=dst, backing=None, ssh_port=_free_port(), created=time.time()))
            except Exception:
                shutil.rmtree(self._dir(dst), ignore_errors=True)
                raise

    def delete(self, name):
        with _lock(name):
            if self._pid(name):
                raise RuntimeError("the VM is running; stop it first")
            deps = self.dependents(name)
            if deps:
                raise RuntimeError("the VM is the base of other VMs (" + ", ".join(deps[:5]) + "); delete them first")
            try:
                port = self._meta(name).get("ssh_port")
                vm.CREDS.pop(f"127.0.0.1:{port}", None)
            except ApiError:
                pass
            shutil.rmtree(self._dir(name), ignore_errors=False)
        return True

    def rename(self, a, b):
        with _lock(a):
            if self.dependents(a):
                raise RuntimeError("cannot rename a base that has clones")
            os.rename(self._dir(a), self._dir(b))
        m = self._meta(b)
        m["name"] = b
        self._save(b, m)

    def hard_stop(self, name):
        """QMP system_powerdown → ожидание → quit → SIGTERM → SIGKILL."""
        pid = self._pid(name)
        if not pid:
            return
        sock = os.path.join(self._dir(name), "qmp.sock")
        try:
            s = socket.socket(socket.AF_UNIX)
            s.settimeout(3)
            s.connect(sock)
            s.recv(4096)
            s.sendall(b'{"execute":"qmp_capabilities"}\n')
            s.recv(4096)
            s.sendall(b'{"execute":"quit"}\n')
            s.close()
        except OSError:
            pass
        for sig in (None, signal.SIGTERM, signal.SIGKILL):
            if sig:
                if self._pid(name) != pid:  # процесс уже завершился (pid мог быть переиспользован) — чужому сигнал не шлём
                    return
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    return
            for _ in range(20):
                if not self._pid(name):
                    return
                time.sleep(0.25)

    def isolation(self, source):
        """Аргумент start_step: гость не видит ни интернет, ни локальную сеть, только сервер CI (guestfwd на FWD_IP:порт)."""
        u = urlsplit(source["url"])
        port = u.port or (443 if u.scheme == "https" else 80)
        try:
            ip = sorted({i[4][0] for i in socket.getaddrinfo(u.hostname, port, socket.AF_INET, socket.SOCK_STREAM)})[0]
        except OSError:
            raise RuntimeError(f"cannot resolve the CI server host '{u.hostname}'") from None
        return {"restrict": True, "fwd": {"ip": ip, "port": port, "host": u.hostname}}

    # ---------------------------------------------------------------- запуск
    def _fwd_arg(self, f):
        """guestfwd на ОДИН заранее заданный адрес через реле (гость назначение выбрать не может)."""
        relay = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vm_relay.py'))} {f['ip']} {f['port']}"
        return f"guestfwd=tcp:{FWD_IP}:{f['port']}-cmd:{relay.replace(',', ',,')}"

    def _argv(self, name, extra):
        m = self._meta(name)
        d = self._dir(name)
        a = arch()
        accel = self.accel()
        cpu = "host" if accel == "kvm" else "max"
        extra = extra or {}
        # ВСЕГДА restrict=on: без него гость видит loopback хоста (10.0.2.2 → 127.0.0.1) и может ходить в API панели. Выход в интернет — только по явному
        # extra["internet"] и только для доверенных операций (рецепт build); код чужих workflow так не запускается никогда.
        net = f"user,id=n0,hostfwd=tcp:127.0.0.1:{m['ssh_port']}-:22" + ("" if extra.get("internet") else ",restrict=on")
        for key in ("fwd", "seed_fwd"):
            if extra.get(key):
                net += "," + self._fwd_arg(extra[key])
        serial = ["-serial", "file:" + _q(os.path.join(d, "qemu.log"))] if extra.get("debug_log") else ["-serial", "none"]  # журнал без лимита роста — только для сборки основы
        cmd = [self.system_binary(), "-name", f"sa-{name}", "-accel", accel, "-cpu", cpu, "-smp", str(m.get("cpus", DEFAULT_CPUS)),
               "-m", str(m.get("mem_mb", DEFAULT_MEM_MB)), "-display", "none", *serial,
               "-drive", f"file={_q(self._disk(name))},if=virtio,format=qcow2", "-device", "virtio-rng-pci",
               "-qmp", f"unix:{_q(os.path.join(d, 'qmp.sock'))},server,nowait", "-pidfile", os.path.join(d, "qemu.pid"), "-daemonize"]
        if a == "aarch64":
            efi = next((p for p in EFI_CANDIDATES if os.path.exists(p)), None)
            if not efi:
                raise RuntimeError("UEFI firmware not found: install qemu-efi-aarch64")
            cmd += ["-machine", "virt", "-bios", efi]
        else:
            cmd += ["-machine", "q35"]
        cmd += ["-netdev", net, "-device", "virtio-net-pci,netdev=n0"]
        if extra.get("seed_url"):
            cmd += ["-smbios", f"type=1,serial=ds=nocloud-net;s={extra['seed_url']}"]
        return cmd

    def start_step(self, name, extra=()):
        def step(log):
            with _lock(name):
                if self._pid(name):
                    raise RuntimeError("the VM is already running")
                if self.dependents(name):
                    raise RuntimeError("the VM is the base of other VMs; starting it would corrupt them")
                if not self.available():
                    raise RuntimeError("QEMU is not installed: " + ", ".join(self.missing_packages()))
                m = self._meta(name)
                try:
                    with socket.socket() as s:
                        s.bind(("127.0.0.1", m["ssh_port"]))
                except OSError:
                    m["ssh_port"] = _free_port()
                    self._save(name, m)
                if self.accel() == "tcg":
                    log("WARNING: /dev/kvm is not accessible — software emulation (TCG) is very slow; add your user to the 'kvm' group for real use")
                for stale in ("qmp.sock", "qemu.pid"):
                    try:
                        os.unlink(os.path.join(self._dir(name), stale))
                    except OSError:
                        pass
                r = subprocess.run(self._argv(name, extra if isinstance(extra, dict) else {}), capture_output=True, timeout=60)
                if r.returncode:
                    raise RuntimeError("qemu failed to start: " + r.stderr.decode("utf-8", "replace").strip()[:300])
                for _ in range(40):
                    if self._pid(name):
                        log(f"{name}: running ({self.accel()})")
                        return
                    time.sleep(0.25)
                raise RuntimeError("the VM did not reach the running state")
        return step

    # ---------------------------------------------------------------- создание основы
    def _keygen(self, path):
        kg = _tool("ssh-keygen")
        if not kg:
            raise RuntimeError("ssh-keygen is required (package openssh-client)")
        r = subprocess.run([kg, "-q", "-t", "ed25519", "-N", "", "-C", "service-admin", "-f", path], capture_output=True, timeout=30)
        if r.returncode:
            raise RuntimeError("ssh-keygen failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])

    def create_base_step(self, name, size_gb=DEFAULT_DISK_GB, cpus=DEFAULT_CPUS, mem_mb=DEFAULT_MEM_MB):
        """Основа из официального облачного образа Ubuntu: загрузка + sha256, диск, ключи (вход по ключу ВМ, ключ хоста гостя закреплён), первая загрузка
        с cloud-init (nocloud-net через реле, без выхода в сеть), ожидание SSH, выключение."""
        def step(log):
            if not self.available():
                raise RuntimeError("QEMU is not installed: " + ", ".join(self.missing_packages()))
            url = CLOUD[arch()]
            img = self._fetch_image(url, log)
            os.makedirs(self._dir(name), mode=0o700, exist_ok=False)
            srv = None
            try:
                d = self._dir(name)
                r = subprocess.run([self.binary(), "create", "-f", "qcow2", "-b", img, "-F", "qcow2", self._disk(name), f"{size_gb}G"],
                                   capture_output=True, timeout=60)
                if r.returncode:
                    raise RuntimeError("qemu-img create failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])
                self._keygen(os.path.join(d, "id_ed25519"))
                self._keygen(os.path.join(d, "hostkey"))
                meta = {"name": name, "arch": arch(), "cpus": cpus, "mem_mb": mem_mb, "disk_gb": size_gb, "ssh_port": _free_port(),
                        "user": "sa", "backing": None, "base_image": os.path.basename(img), "created": time.time()}
                self._save(name, meta)
                srv, seed_port, token = _seed_server(name, open(os.path.join(d, "id_ed25519.pub"), encoding="utf-8").read().strip(),
                                                     open(os.path.join(d, "hostkey"), encoding="utf-8").read(), open(os.path.join(d, "hostkey.pub"), encoding="utf-8").read().strip())
                try:
                    self.start_step(name, {"restrict": True, "seed_fwd": {"ip": "127.0.0.1", "port": seed_port},
                                           "seed_url": f"http://{FWD_IP}:{seed_port}/{token}/", "debug_log": True})(log)
                    log("first boot: cloud-init configures the guest (this takes minutes; very long without KVM)…")
                    ip = self.ip(name)
                    deadline = time.monotonic() + (900 if self.accel() == "kvm" else 3600)
                    while time.monotonic() < deadline:
                        try:
                            if vm._guest(ip, "cloud-init status --wait >/dev/null 2>&1; test -f /var/lib/cloud/instance/boot-finished", timeout=self.ssh_probe_timeout + 60)[0] == 0:
                                break
                        except Exception:  # noqa: BLE001 - гость ещё грузится
                            pass
                        time.sleep(10)
                    else:
                        raise RuntimeError("the guest did not finish cloud-init in time; see " + os.path.join(d, "qemu.log"))
                finally:
                    srv.shutdown()
                    srv.server_close()
                vm._stop_vm(None, name, log, self.ip(name))
                try:
                    os.unlink(os.path.join(d, "hostkey"))  # закрытый ключ хоста гостя на стороне хоста больше не нужен
                except OSError:
                    pass
                log(f"base VM '{name}' is ready (user sa, key-based SSH, the guest host key is pinned)")
            except Exception:
                try:
                    self.hard_stop(name)
                except Exception:  # noqa: BLE001
                    pass
                shutil.rmtree(self._dir(name), ignore_errors=True)
                raise
        return step

    def _fetch_image(self, url, log):
        os.makedirs(IMAGES, mode=0o700, exist_ok=True)
        fname = url.rsplit("/", 1)[1]
        sums = urllib.request.urlopen(url.rsplit("/", 1)[0] + "/SHA256SUMS", timeout=60).read().decode()  # noqa: S310
        want = next((ln.split()[0] for ln in sums.splitlines() if ln.rstrip().endswith("*" + fname) or ln.rstrip().endswith(" " + fname)), None)
        if not want or not re.fullmatch(r"[0-9a-f]{64}", want):
            raise RuntimeError("no checksum for " + fname)
        path = os.path.join(IMAGES, f"{want[:16]}-{fname}")  # имя по содержимому: образ никогда не заменяется на месте (на него ссылаются основы и клоны)

        def digest(p):
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()
        if os.path.exists(path) and digest(path) == want:
            log(f"{fname}: already downloaded, sha256 verified")
            return path
        log(f"downloading {fname}…")
        part = path + ".part"
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:  # noqa: S310
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    f.write(chunk)
            if digest(part) != want:
                raise RuntimeError("sha256 mismatch for " + fname)
            os.replace(part, path)
        finally:
            if os.path.exists(part):
                os.unlink(part)
        log(f"{fname}: sha256 verified")
        return path


def _seed_server(name, client_pub, host_priv, host_pub):
    """Крошечный HTTP-сервер на 127.0.0.1 только на время первой загрузки; адрес содержит случайный токен (другие локальные пользователи его не знают).
    Гость ходит к нему через guestfwd (10.0.2.100), не через loopback хоста. В cloud-init только ОТКРЫТЫЙ ключ клиента и ключ хоста гостя — паролей нет."""
    token = secrets.token_urlsafe(16)
    priv = "\n".join("      " + ln for ln in host_priv.strip().splitlines())
    user_data = ("#cloud-config\nusers:\n  - name: sa\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    shell: /bin/bash\n    lock_passwd: true\n"
                 f"    ssh_authorized_keys:\n      - {client_pub}\n"
                 "ssh_pwauth: false\ndisable_root: true\n"
                 f"ssh_keys:\n  ed25519_private: |\n{priv}\n  ed25519_public: {host_pub}\npackage_update: false\n").encode()
    meta_data = f"instance-id: sa-{name}-{secrets.token_hex(4)}\nlocal-hostname: {name}\n".encode()
    files = {f"/{token}/user-data": user_data, f"/{token}/meta-data": meta_data, f"/{token}/vendor-data": b"#cloud-config\n{}\n"}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path.split("?")[0])
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            if body is not None:
                self.wfile.write(body)

        def log_message(self, *a):  # noqa: D102
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], token
