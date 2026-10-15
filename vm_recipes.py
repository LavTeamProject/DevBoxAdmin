"""Рецепты подготовки ВМ-основы (Fase 5): пустой образ + «поставить нужное» одной кнопкой, вместо хранения больших готовых образов.
Рецепт запускается на ОСТАНОВЛЕННОЙ локальной ВМ: ВМ стартует, ждём SSH (учётка образа cirruslabs `admin`), выполняем шаги, ВМ ВСЕГДА останавливается.
Рецепты, которые тянут файлы из интернета, скачивают их НА ХОСТЕ (с проверкой sha256) и заливают в гость потоком — у гостя интернета может не быть (VPN на хосте).
Только то, что можно поставить без человека. Xcode/Flutter/Android Studio требуют Apple ID/лицензий и здесь сознательно НЕ автоматизируются (см. docs/roadmap.md, «Осознанные исключения»)."""
import hashlib
import json
import os
import platform
import re
import sys
import urllib.request

import core
import vm
from core import DATA_DIR

NODE_DIR = "/usr/local/lib/nodejs"
RECIPES_MAC = {
    "node": {"title": "Node.js LTS (official tarball, sha256-checked on the host)", "internet": "host"},
    "clt": {"title": "Command Line Tools (git, compilers) via softwareupdate", "internet": "guest"},
}
RECIPES_LINUX = {
    "node": {"title": "Node.js LTS (official tarball, sha256-checked on the host)", "internet": "host"},
    "build": {"title": "Build tools (build-essential, git, curl) via apt", "internet": "guest"},
}
RECIPES = RECIPES_MAC if sys.platform == "darwin" else RECIPES_LINUX
INTERNET_RECIPES = {"build"}   # доверенные пакеты apt: гость QEMU получает выход в интернет (и видит loopback хоста!) только здесь


def _node_plat():
    """Платформа гостя (= хоста) в имени архива Node.js."""
    if sys.platform == "darwin":
        return "darwin-arm64"
    return "linux-arm64" if platform.machine().lower() in ("aarch64", "arm64") else "linux-x64"
_VER = re.compile(r"^v\d{1,3}\.\d{1,3}\.\d{1,3}$")
_UA = {"User-Agent": "service-admin"}


def catalog():
    return [{"id": k, **v} for k, v in RECIPES.items()]


def _get(url, limit=400_000_000):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - адреса зашиты в рецепте (https://nodejs.org)
        data = r.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("download is larger than expected")
    return data


def _node_tarball(log):
    """Скачать на хост Node LTS для darwin-arm64 и сверить sha256 → путь к файлу и версия."""
    idx = json.loads(_get("https://nodejs.org/dist/index.json", 5_000_000))
    ver = next((x["version"] for x in idx if x.get("lts")), None)
    if not ver or not _VER.match(ver):
        raise RuntimeError("cannot determine the Node.js LTS version")
    name = f"node-{ver}-{_node_plat()}.tar.xz"
    cache = os.path.join(DATA_DIR, "downloads")
    os.makedirs(cache, mode=0o700, exist_ok=True)
    path = os.path.join(cache, name)
    sums = _get(f"https://nodejs.org/dist/{ver}/SHASUMS256.txt", 200_000).decode()
    want = next((ln.split()[0] for ln in sums.splitlines() if ln.endswith("  " + name)), None)
    if not want:
        raise RuntimeError("no checksum for " + name)

    def digest(file):
        h = hashlib.sha256()
        with open(file, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    if not (os.path.exists(path) and digest(path) == want):
        log(f"downloading {name}…")
        part, size = path + ".part", 0
        try:
            req = urllib.request.Request(f"https://nodejs.org/dist/{ver}/{name}", headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:  # noqa: S310
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    size += len(chunk)
                    if size > 400_000_000:
                        raise RuntimeError("download is larger than expected")
                    f.write(chunk)
            if digest(part) != want:  # неверный файл не получает окончательного имени
                raise RuntimeError("sha256 mismatch for " + name)
            os.replace(part, path)
        finally:
            if os.path.exists(part):
                os.unlink(part)
    log(f"{name}: sha256 verified")
    return path, ver, name


def _node(ip, log):
    path, ver, name = _node_tarball(log)
    code, out = vm._guest(ip, f"sudo -n mkdir -p {NODE_DIR} && sudo -n rm -rf {NODE_DIR}/node-{ver}-{_node_plat()}", timeout=60)
    if code:
        raise RuntimeError("cannot prepare the guest folder: " + out[:200])
    log("copying into the VM…")
    with open(path, "rb") as f:
        code, out = vm._guest(ip, f"sudo -n tar -xJf - -C {NODE_DIR}", stdin=f, timeout=900)
    if code:
        raise RuntimeError("unpack failed: " + out[:200])
    link = f"for b in node npm npx; do sudo -n ln -sf {NODE_DIR}/node-{ver}-{_node_plat()}/bin/$b /usr/local/bin/$b; done"
    code, out = vm._guest(ip, f"sudo -n mkdir -p /usr/local/bin && {link} && /usr/local/bin/node --version", timeout=60)
    if code or out.strip().splitlines()[-1:] != [ver]:
        raise RuntimeError("verification failed: " + out[:200])
    log(f"verified in the guest: node {ver}")


_CLT = r'''
set -eo pipefail
curl -sS -m 15 -o /dev/null -I https://swscan.apple.com || { echo "NO_INTERNET"; exit 3; }
sudo -n touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
trap 'sudo -n rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress' EXIT
label=$(softwareupdate -l 2>&1 | sed -n 's/^\* Label: \(Command Line Tools.*\)$/\1/p' | tail -1)
[ -n "$label" ] || { echo "NO_LABEL"; exit 4; }
echo "installing: $label"
sudo -n softwareupdate -i "$label" --verbose 2>&1 | tail -5
xcode-select -p
'''


def _clt(ip, log):
    code, out = vm._guest(ip, "bash", "-c", "'" + _CLT.replace("'", "'\\''") + "'", timeout=3600)
    if "NO_INTERNET" in out:
        raise RuntimeError("the guest has no internet access (a VPN with a default route on the host blocks it); turn the VPN off and retry")
    if "NO_LABEL" in out:
        raise RuntimeError("softwareupdate lists no Command Line Tools package")
    if code:
        raise RuntimeError("installation failed: " + out[-300:])
    log(out[-300:])


def _build(ip, log):
    code, out = vm._guest(ip, "sudo -n env DEBIAN_FRONTEND=noninteractive sh -c 'apt-get update -qq && apt-get install -y -qq build-essential git curl' 2>&1 | tail -3; "
                              "gcc --version | head -1; git --version", timeout=3600)
    if "gcc" not in out or "git version" not in out:
        raise RuntimeError("installation failed: " + out[-300:])
    log(out[-200:])


def step(exe, name, recipe):
    """Шаг для start_steps: старт ВМ → ждём SSH → рецепт → остановка (всегда)."""
    import time
    fn = {"node": _node, "clt": _clt, "build": _build}[recipe]

    def run(log):
        d = vm.driver()
        if d.status(name)["running"]:
            raise RuntimeError("the VM is running now; stop it first (it was not started by this job)")
        ip = None
        try:
            vm._start_detached(exe, name, {"internet": True} if recipe in INTERNET_RECIPES and d.name == "qemu" else ())(log)
            ip = vm.wait_ssh(d, name)
            fn(ip, log)
        finally:
            log("stopping the VM…")
            vm._stop_vm(exe, name, log, ip)
    return run
