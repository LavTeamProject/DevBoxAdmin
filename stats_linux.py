"""Статистика системы на Linux без root (Фаза 6, Л1): /proc, /sys, nvidia-smi. Те же формы ответов, что у macOS-версии в stats.py.
Чего нет на машине (температуры в ВМ, батарея на сервере, GPU) — None/пусто, это не ошибка."""
import glob
import os
import platform
import re
import subprocess
import time

import platform_info


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def _run(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---------------------------------------------------------------- CPU

def cpu_ticks():
    """[(user, system, idle, nice), ...] по ядрам (из /proc/stat; idle включает iowait)."""
    out = []
    for line in _read("/proc/stat").splitlines():
        if re.match(r"cpu\d+ ", line):
            f = [int(x) for x in line.split()[1:]]
            f += [0] * (8 - len(f))
            user, nice, system, idle, iowait, irq, softirq, steal = f[:8]
            out.append((user, system + irq + softirq + steal, idle + iowait, nice))
    return out


# ---------------------------------------------------------------- температуры

class TempSensors:
    """hwmon: имя датчика → список значений в °C. Группы CPU / SSD / Battery собирает summarize_temps."""
    def __init__(self):
        self.ok = bool(glob.glob("/sys/class/hwmon/hwmon*/temp*_input"))

    def read(self):
        res = {}
        for hw in glob.glob("/sys/class/hwmon/hwmon*"):
            chip = _read(os.path.join(hw, "name"))
            for f in glob.glob(os.path.join(hw, "temp*_input")):
                raw = _read(f)
                try:
                    v = int(raw) / 1000.0
                except ValueError:
                    continue
                if not 0 < v < 130:
                    continue
                label = _read(f[:-len("_input")] + "_label")
                res.setdefault(f"{chip}:{label}" if label else chip, []).append(v)
        return res


def summarize_temps(raw):
    groups = {"CPU / SoC": [], "SSD": [], "Battery": []}
    for name, values in raw.items():
        low = name.lower()
        if low.startswith(("coretemp", "k10temp", "cpu_thermal", "zenpower", "cpu-thermal", "soc_thermal", "bcm2835")):
            groups["CPU / SoC"] += values
        elif low.startswith("nvme") or "composite" in low:
            groups["SSD"] += values
        elif "battery" in low or low.startswith("bat"):
            groups["Battery"] += values
    out = {}
    for k, v in groups.items():
        if v:
            out[k] = {"avg": round(sum(v) / len(v), 1), "max": round(max(v), 1), "sensors": len(v)}
    return out


# ---------------------------------------------------------------- RAM

def memory():
    m = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        f = v.split()
        if f and f[0].isdigit():
            m[k] = int(f[0]) * (1024 if len(f) > 1 and f[1].lower() == "kb" else 1)
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    cached = m.get("Cached", 0) + m.get("Buffers", 0) + m.get("SReclaimable", 0)
    used = max(total - avail, 0)
    some = re.search(r"some avg10=([\d.]+)", _read("/proc/pressure/memory"))
    p = float(some[1]) if some else 0
    return {"total": total, "used": used, "app": used, "wired": 0, "compressed": 0, "cached": cached, "free": m.get("MemFree", 0),
            "swap_used": max(m.get("SwapTotal", 0) - m.get("SwapFree", 0), 0), "swap_total": m.get("SwapTotal", 0),
            "pressure": "critical" if p >= 40 else "warning" if p >= 10 else "normal",
            "percent": round(100 * used / total, 1) if total else 0}


# ---------------------------------------------------------------- GPU, батарея, сеть, диск

def gpu():
    if platform_info._has("nvidia-smi"):
        out = _run("nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used", "--format=csv,noheader,nounits")
        line = out.strip().splitlines()[0] if out.strip() else ""
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            return {"usage": int(parts[1]), "model": parts[0], "cores": None, "memory": int(parts[2]) * 1024 * 1024 if parts[2].isdigit() else 0}
    for f in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        v = _read(f)
        if v.isdigit():
            return {"usage": int(v), "model": _read(os.path.join(os.path.dirname(f), "product_name")) or "GPU", "cores": None, "memory": 0}
    return None


def battery():
    bats = sorted(glob.glob("/sys/class/power_supply/BAT*"))
    if not bats:
        return None
    b = bats[0]
    def num(n):
        try:
            return int(_read(os.path.join(b, n)) or 0)
        except ValueError:
            return 0
    cap = _read(os.path.join(b, "capacity"))
    status = _read(os.path.join(b, "status")).lower()
    # charge_* — мкА·ч (→ мА·ч); energy_* — мкВт·ч: в мА·ч пересчитываем по номинальному напряжению, если оно известно
    vdes = num("voltage_min_design") or num("voltage_now")
    if num("charge_full_design"):
        full, design = num("charge_full") / 1000, num("charge_full_design") / 1000
    elif num("energy_full_design") and vdes:
        full, design = num("energy_full") / vdes * 1000, num("energy_full_design") / vdes * 1000
    else:
        full = design = 0
    full, design = int(full), int(design)
    watts = num("power_now") / 1e6 if num("power_now") else abs(num("current_now") * num("voltage_now")) / 1e12
    ac = any(_read(os.path.join(p, "online")) == "1" for p in glob.glob("/sys/class/power_supply/A*"))
    return {"percent": int(cap) if cap.isdigit() else None, "state": status or "unknown", "remaining": None,
            "source": "AC" if ac else "Battery", "cycles": num("cycle_count") or None,
            "health": round(100 * full / design, 1) if design and full else None,
            "design_mah": design or None, "max_mah": full or None, "watts": round(watts, 1), "adapter_watts": None}


_SKIP_IF = re.compile(r"^(lo|docker\d*|veth.*|br-.*|virbr.*|tailscale.*|tun\d+|wg.*|cni.*|flannel.*|cali.*)$")


def net_bytes():
    rx = tx = 0
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        f = rest.split()
        if len(f) >= 9 and not _SKIP_IF.match(name.strip()) and not os.path.exists(f"/sys/class/net/{name.strip()}/master"):
            rx += int(f[0])
            tx += int(f[8])
    return rx, tx


_DISK = re.compile(r"^(sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")


def disk_io_bytes():
    r = w = 0
    for line in _read("/proc/diskstats").splitlines():
        f = line.split()
        if len(f) > 9 and _DISK.match(f[2]):
            r += int(f[5]) * 512
            w += int(f[9]) * 512
    return r, w


def disk_usage():
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total": total, "free": free, "used": total - free, "percent": round(100 * (total - free) / total, 1) if total else 0}


def top_processes(n=8):
    procs = []
    for line in _run("ps", "-eo", "pid=,pcpu=,rss=,comm=").splitlines():
        p = line.split(None, 3)
        if len(p) == 4 and p[0].isdigit():
            procs.append({"pid": int(p[0]), "cpu": float(p[1]), "mem": int(p[2]) * 1024, "name": p[3]})
    return {"cpu": sorted(procs, key=lambda x: -x["cpu"])[:n], "mem": sorted(procs, key=lambda x: -x["mem"])[:n], "count": len(procs)}


_static = None


def system_info():
    global _static
    if _static is None:
        rel = platform_info._os_release()
        cpu = next((ln.split(":", 1)[1].strip() for ln in _read("/proc/cpuinfo").splitlines() if ln.lower().startswith(("model name", "hardware"))), "")
        n = os.cpu_count() or 0
        _static = {"hostname": platform.node(), "model": _read("/sys/class/dmi/id/product_name") or "Linux",
                   "model_id": _read("/sys/class/dmi/id/product_version") or platform.machine(),
                   "chip": cpu or platform.machine(), "cores_p": n, "cores_e": 0,
                   "os_version": rel.get("PRETTY_NAME", "Linux"), "macos": "", "os_label": rel.get("PRETTY_NAME", "Linux"), "build": platform.release()}
    up = _read("/proc/uptime").split()
    return {**_static, "uptime": int(float(up[0])) if up else 0, "load": [round(x, 2) for x in os.getloadavg()]}
