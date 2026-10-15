"""Виртуальные машины (Фаза 5): интерфейс драйвера и драйвер tart.

Чтение: list / status. Изменения (Шаг 2) — `build()` чистая функция, исполнение через `core.start_steps` (job + аудит):
  vm.clone (L2)  локальная копия существующей ВМ (APFS clone, дёшево);
  vm.pull (L3)   скачать образ ТОЛЬКО из ghcr.io/cirruslabs/ (десятки ГБ), подтверждение — имя новой ВМ;
  vm.start (L2)  tart run --no-graphics, без общих папок хоста; vm.stop (L2);
  vm.snapshot (L2)  копия остановленной ВМ `<начало имени>-snap-<хеш имени>-<время>` (в tart нет снимков — это клон);
  vm.delete (L4)  только остановленную, подтверждение — её точное имя;
  vm.restore (L4)  вернуть остановленную ВМ к «снимку» `<имя>-snap-…`: копия снимка → удаление ВМ → переименование копии; подтверждение — имя ВМ;
  vm.prepare_runner (L2)  положить файлы раннера (runners.py) внутрь ОСТАНОВЛЕННОЙ ВМ-основы по SSH (учётка образа cirruslabs
                          admin/admin, ВМ в NAT-сети; нужен sshpass на хосте), сверить sha256 и снова остановить. НЕ регистрирует.
Агентам эти операции НЕ открыты (нет в plans.AGENT_OPS). Имена проверяются regex и реестром tart; без shell.
"""
import hashlib
import os
import re
import secrets
import shutil
import subprocess
import time
from http import HTTPStatus

import core
from core import ApiError, loads_or, run

TART_DIRS = (os.path.join(core.HOME, ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin")


class Driver:
    name = "base"
    READ = ("list", "status")  # что драйвер умеет СЕЙЧАС; остальное — не реализовано

    def available(self):
        raise NotImplementedError

    def list(self):
        raise NotImplementedError

    def ip(self, name):
        raise NotImplementedError

    def status(self, name):
        for vm in self.list():
            if vm["name"] == name:
                return vm
        raise ApiError("VM not found", HTTPStatus.NOT_FOUND, code="vm.not_found")


class TartDriver(Driver):
    name = "tart"

    def binary(self):
        return shutil.which("tart", path=os.pathsep.join(TART_DIRS + (os.environ.get("PATH", ""),)))

    def available(self):
        return bool(self.binary())

    def ip(self, name):
        """IP гостя: по DHCP-аренде tart; под softnet аренды ведёт сам softnet — тогда по ARP-таблице."""
        for resolver in ("dhcp", "arp"):
            code, out, _ = run([self.binary(), "ip", "--wait", "5", "--resolver", resolver, name], timeout=15)
            if code == 0 and re.match(r"^[0-9.]{7,15}$", out.strip()):
                return out.strip()
        raise RuntimeError("the VM has no IP address yet")

    def list(self):
        exe = self.binary()
        if not exe:
            raise FileNotFoundError("tart")
        code, out, err = run([exe, "list", "--format", "json"], timeout=20)
        if code != 0:
            raise ApiError(err.strip()[:200] or "tart list failed", HTTPStatus.BAD_GATEWAY, code=None if err.strip() else "vm.list_failed")
        rows = loads_or(out, None)
        if not isinstance(rows, list):
            raise ApiError("tart returned unexpected output", HTTPStatus.BAD_GATEWAY, code="vm.bad_output")
        return [{"name": r.get("Name", ""), "source": r.get("Source", ""), "state": r.get("State", "unknown"),
                 "running": bool(r.get("Running")), "disk_gb": r.get("Disk"), "size_gb": r.get("Size"),
                 "accessed": r.get("Accessed")} for r in rows if isinstance(r, dict)]


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
IMAGE_RE = re.compile(r"^ghcr\.io/cirruslabs/[a-z0-9][a-z0-9._-]{0,60}(:[A-Za-z0-9._-]{1,40})?$")
LOG_DIR = os.path.join(core.DATA_DIR, "vm-logs")
DRIVERS = {"tart": TartDriver()}


def driver(name="tart"):
    d = DRIVERS.get(name)
    if not d:
        raise ApiError("Unknown VM driver", HTTPStatus.BAD_REQUEST, code="vm.driver")
    return d


def overview(q=None):
    """GET /api/vms — доступные драйверы и их ВМ. Только чтение."""
    out = []
    for name, d in DRIVERS.items():
        item = {"driver": name, "available": d.available(), "can": list(d.READ), "vms": []}
        if item["available"]:
            try:
                item["vms"] = d.list()
                locals_ = [v["name"] for v in item["vms"] if v["source"] == "local"]
                for v in item["vms"]:
                    v["snapshot_of"] = snapshot_of(v["name"], locals_) if v["source"] == "local" else None
            except ApiError as e:
                item["error"] = str(e)
        out.append(item)
    return {"drivers": out}


# ---------------------------------------------------------------- изменения

def _bad(msg, code, status=HTTPStatus.BAD_REQUEST, **params):
    return ApiError(msg, status, code=code, **params)


def _local(d, name):
    """ВМ из локального хранилища tart (не образ OCI), иначе ошибка."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _bad("Invalid VM name", "vm.bad_name")
    for v in d.list():
        if v["name"] == name and v["source"] == "local":
            return v
    raise _bad("VM not found", "vm.not_found", HTTPStatus.NOT_FOUND)


def _free_name(d, name):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _bad("Invalid VM name: 1-40 characters (letters, digits, . _ -)", "vm.bad_name")
    if any(v["name"] == name for v in d.list()):
        raise _bad("A VM with this name already exists", "vm.exists", HTTPStatus.CONFLICT)


SNAP_RE = re.compile(r"^(?P<prefix>.{1,12})-snap-(?P<h>[0-9a-f]{6})-(?P<ts>\d{8}-\d{6})$")


def snapshot_name(name, ts=None):
    """`<первые 12 символов>-snap-<хеш полного имени>-<время>` ≤ 40 символов. Хеш полного имени не даёт приписать снимок ДРУГОЙ ВМ
    с тем же началом имени (иначе откат подменил бы данные чужой ВМ)."""
    h = hashlib.sha1(name.encode()).hexdigest()[:6]
    return f"{name[:12]}-snap-{h}-{ts or time.strftime('%Y%m%d-%H%M%S')}"


def snapshot_of(snap, names):
    """Имя ВМ, которой принадлежит снимок `snap` (или None): среди `names` есть ВМ с таким хешем и началом имени."""
    m = SNAP_RE.match(snap or "")
    if not m:
        return None
    for n in names:
        if n != snap and n[:12] == m["prefix"] and hashlib.sha1(n.encode()).hexdigest()[:6] == m["h"]:
            return n
    return None


GUEST_USER = "admin"
GUEST_DIR = "runner"   # ~/runner в госте
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=10", "-o", "PubkeyAuthentication=no"]


def _sshpass():
    return shutil.which("sshpass", path=os.pathsep.join(TART_DIRS + (os.environ.get("PATH", ""),)))


def _guest(ip, *remote, stdin=None, timeout=120):
    """Команда в госте через ssh (пароль — в окружении, не в argv). Возвращает (код, вывод).
    Код 255 (обрыв соединения сразу после загрузки гостя) повторяется до 3 раз — только для команд без stdin."""
    env = dict(core.ENV, SSHPASS="admin")
    cmd = [_sshpass(), "-e", "ssh", *SSH_OPTS, f"{GUEST_USER}@{ip}", *remote]
    for attempt in range(3):
        p = subprocess.run(cmd, stdin=stdin if stdin is not None else subprocess.DEVNULL, capture_output=True, env=env, timeout=timeout)
        if p.returncode != 255 or stdin is not None:
            break
        time.sleep(2)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip()


def _file_hashes(path):
    """{относительный путь: sha256} для обычных файлов (ссылки пропускаются, как у `find -type f` в госте)."""
    out = {}
    for root, _, files in os.walk(path):
        for f in files:
            full = os.path.join(root, f)
            if os.path.islink(full):
                continue
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[os.path.relpath(full, path)] = h.hexdigest()
    return out


def _stream_tar_to_guest(src, ip):
    """tar на хосте → ssh → tar в госте, потоком (без загрузки дерева в память); проверяются оба кода возврата."""
    env = dict(core.ENV, SSHPASS="admin")
    tar = subprocess.Popen(["/usr/bin/tar", "-C", src, "-cf", "-", "."], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        ssh = subprocess.run([_sshpass(), "-e", "ssh", *SSH_OPTS, f"{GUEST_USER}@{ip}", f"tar -xf - -C ~/{GUEST_DIR}"], stdin=tar.stdout,
                             capture_output=True, env=env, timeout=600)
    finally:
        tar.stdout.close()
        try:
            tar_err = tar.communicate(timeout=30)[1]
        except subprocess.TimeoutExpired:
            tar.kill()
            tar_err = b""
    if tar.returncode or ssh.returncode:
        raise RuntimeError("copy failed: " + ((ssh.stderr + tar_err).decode("utf-8", "replace").strip()[:200] or f"tar={tar.returncode} ssh={ssh.returncode}"))


def _stop_vm(exe, name, log, ip=None):
    """Остановить ВМ и убедиться, что она остановилась; ошибка остановки не должна скрывать исходную ошибку.
    С известным ip сначала штатное выключение гостя (sync + shutdown): жёсткая остановка теряла свежезаписанные файлы."""
    if ip:
        try:
            _guest(ip, "sync; sudo -n /sbin/shutdown -h now", timeout=20)
        except Exception:  # noqa: BLE001 - ssh обрывается вместе с гостем
            pass
        for _ in range(30):
            try:
                if not driver().status(name)["running"]:
                    return
            except Exception:  # noqa: BLE001
                break
            time.sleep(1)
    for attempt in range(2):
        try:
            subprocess.run([exe, "stop", name, "--timeout", "30"], capture_output=True, timeout=90)
        except Exception as e:  # noqa: BLE001
            log(f"stop attempt {attempt + 1} failed: {e}")
        try:
            if not driver().status(name)["running"]:
                return
        except Exception:  # noqa: BLE001
            pass
    log(f"WARNING: could not confirm that the VM '{name}' is stopped; stop it by hand")


def _prepare_runner(exe, name, provider_id):
    import runners
    prov = runners.provider(provider_id)
    inst = prov.installed()
    if not inst:
        raise _bad("Install the runner files of this provider first", "vm.runner_missing", HTTPStatus.CONFLICT)
    src = inst[-1]["path"]

    def step(log):
        d = driver()
        if d.status(name)["running"]:  # между постановкой job и запуском ВМ кто-то мог её включить — чужую ВМ не трогаем
            raise RuntimeError("the VM is running now; stop it first (it was not started by this job)")
        hashes = _file_hashes(src)
        count = len(hashes)
        ip = None
        log(f"runner {inst[-1]['version']}: {count} files")
        try:
            _start_detached(exe, name)(log)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:  # ждём IP и SSH не дольше 2 минут
                try:
                    ip = ip or d.ip(name)
                    if _guest(ip, "true", timeout=15)[0] == 0:
                        break
                except Exception:  # noqa: BLE001 - ip ещё нет / ssh не отвечает
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("the VM did not accept SSH in 2 minutes (is SSH enabled and the guest password 'admin'?)")
            code, out = _guest(ip, f"rm -rf ~/{GUEST_DIR} && mkdir -p ~/{GUEST_DIR}")
            if code:
                raise RuntimeError("cannot prepare the guest folder: " + out[:200])
            log("copying files into the VM…")
            _stream_tar_to_guest(src, ip)
            # сверка: sha256 КАЖДОГО файла (shasum из macOS), список сравнивается с хостовым
            code, out = _guest(ip, f"cd ~/{GUEST_DIR} && find . -type f -exec shasum -a 256 {{}} +", timeout=600)
            if code:
                raise RuntimeError("verification failed: " + out[:200])
            guest = {}
            for line in out.splitlines():
                digest, _, rel = line.partition("  ")
                guest[rel[2:] if rel.startswith("./") else rel] = digest
            if guest != hashes:
                bad = sorted(set(guest) ^ set(hashes) | {k for k in guest if k in hashes and guest[k] != hashes[k]})
                raise RuntimeError(f"verification failed: {len(bad)} file(s) differ, e.g. {bad[:3]}")
            log(f"verified: all {count} files match by sha256; the runner is NOT registered")
        finally:
            log("stopping the VM…")
            _stop_vm(exe, name, log, ip)
    return step


def softnet_ready():
    """softnet найден и имеет права root (SUID) — иначе `tart run --net-softnet` не запустится."""
    exe = shutil.which("softnet", path=os.pathsep.join(TART_DIRS + (os.environ.get("PATH", ""),)))
    if not exe:
        return False
    st = os.stat(exe)
    return st.st_uid == 0 and bool(st.st_mode & 0o4000)


def _start_detached(exe, name, extra=()):
    def step(log):
        os.makedirs(LOG_DIR, mode=0o700, exist_ok=True)
        with open(os.path.join(LOG_DIR, name + ".log"), "ab") as logf:
            subprocess.Popen([exe, "run", "--no-graphics", *extra, name], stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                             start_new_session=True, env=core.ENV)
        for _ in range(60):  # до 30 с ждём, что tart отметит ВМ запущенной
            time.sleep(0.5)
            if driver().status(name)["running"]:
                log(f"{name}: running")
                return
        raise RuntimeError("the VM did not reach the running state in 30 s; see " + os.path.join(LOG_DIR, name + ".log"))
    return step


def _restore_swap(exe, name, tmp):
    def step(log):
        d = driver()
        if d.status(name)["running"]:  # ВМ могли запустить между проверкой и этим шагом
            subprocess.run([exe, "delete", tmp], capture_output=True, timeout=120)
            raise RuntimeError(f"the VM '{name}' was started meanwhile; the restore was cancelled and nothing was changed")
        r = subprocess.run([exe, "delete", name], capture_output=True, timeout=300)
        if r.returncode:
            subprocess.run([exe, "delete", tmp], capture_output=True, timeout=120)
            raise RuntimeError("could not delete the current VM; the restore was cancelled and nothing was changed")
        log(f"deleted the current VM '{name}'")
    return step


def _restore_rename(exe, name, tmp):
    def step(log):
        r = subprocess.run([exe, "rename", tmp, name], capture_output=True, timeout=120)
        if r.returncode:
            raise RuntimeError(f"rename failed: the restored copy is kept as '{tmp}'; finish by hand: tart rename {tmp} {name}")
        log(f"restored '{name}' from the snapshot")
    return step


def build(op, params):
    """(label, kind, steps) — ничего не запускает. Все проверки состояния здесь."""
    d = driver()
    exe = d.binary()
    if not exe:
        raise FileNotFoundError("tart")
    if not isinstance(params, dict):
        raise _bad("Bad request", "vm.bad_name")
    if op == "vm.prepare_runner":
        import runners
        runners.provider(params.get("provider"))
        v = _local(d, params.get("name"))
        if v["running"]:
            raise _bad("Stop the VM first", "vm.running", HTTPStatus.CONFLICT)
        if not _sshpass():
            raise _bad("sshpass is required on the host to reach the VM", "vm.no_sshpass", HTTPStatus.CONFLICT)
        return (f"VM {v['name']}: put {params['provider']} runner files inside", "vm",
                [("copy and verify", _prepare_runner(exe, v["name"], params["provider"]), {})])
    if op == "vm.clone":
        _local(d, params.get("source"))
        _free_name(d, params.get("name"))
        return (f"VM clone {params['source']} → {params['name']}", "vm",
                [("tart clone", [exe, "clone", params["source"], params["name"]], {})])
    if op == "vm.pull":
        image = params.get("image")
        if not isinstance(image, str) or not IMAGE_RE.match(image):
            raise _bad("Only images from ghcr.io/cirruslabs/ are allowed", "vm.bad_image")
        _free_name(d, params.get("name"))
        if params.get("confirm") != params["name"]:
            raise _bad("Type the new VM name to confirm the download", "vm.confirm")
        if shutil.disk_usage("/").free < 60e9:
            raise _bad("At least 60 GB of free disk space is needed for an image", "vm.disk", HTTPStatus.CONFLICT)
        return (f"VM pull {image} → {params['name']}", "vm", [("tart clone (download)", [exe, "clone", image, params["name"]], {})])
    name = params.get("name")
    v = _local(d, name)
    if op == "vm.start":
        if v["running"]:
            raise _bad("The VM is already running", "vm.running", HTTPStatus.CONFLICT)
        return (f"VM start {name}", "vm", [("tart run --no-graphics", _start_detached(exe, name), {})])
    if op == "vm.stop":
        if not v["running"]:
            raise _bad("The VM is not running", "vm.not_running", HTTPStatus.CONFLICT)
        return (f"VM stop {name}", "vm", [("tart stop", [exe, "stop", name], {})])
    if op in ("vm.snapshot", "vm.delete") and v["running"]:
        raise _bad("Stop the VM first", "vm.running", HTTPStatus.CONFLICT)
    if op == "vm.snapshot":
        snap = snapshot_name(name)
        return (f"VM snapshot {name} → {snap}", "vm", [("tart clone (snapshot)", [exe, "clone", name, snap], {})])
    if op == "vm.restore":
        snap = params.get("snapshot")
        sv = _local(d, snap)
        m = SNAP_RE.match(snap)
        if not m or m["prefix"] != name[:12] or m["h"] != hashlib.sha1(name.encode()).hexdigest()[:6]:
            raise _bad("The snapshot does not belong to this VM", "vm.bad_snapshot")
        if v["running"] or sv["running"]:
            raise _bad("Stop the VM first", "vm.running", HTTPStatus.CONFLICT)
        if params.get("confirm") != name:
            raise _bad("Type the exact VM name to confirm the restore", "vm.confirm")
        tmp = f"{name[:12]}-restoring-{secrets.token_hex(4)}"
        return (f"VM restore {name} ← {snap}", "vm",
                [("tart clone (copy of the snapshot)", [exe, "clone", snap, tmp], {}),
                 ("tart delete (current VM)", _restore_swap(exe, name, tmp), {}),
                 ("tart rename", _restore_rename(exe, name, tmp), {})])
    if op == "vm.delete":
        if params.get("confirm") != name:
            raise _bad("Type the exact VM name to confirm deletion", "vm.confirm")
        return (f"VM delete {name}", "vm", [("tart delete", [exe, "delete", name], {})])
    raise _bad("Unknown VM operation", "vm.unknown_op")


def run_op(body):
    """POST /api/vms/op {op, params} → {"job": id}."""
    op, params = body.get("op"), body.get("params") or {}
    if not isinstance(op, str):
        raise _bad("Bad request", "vm.unknown_op")
    label, kind, steps = build(op, params)
    return {"job": core.start_steps(label, steps, kind), "label": label}
