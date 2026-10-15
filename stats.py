"""Statistik sistem macOS (Apple Silicon) tanpa sudo & tanpa dependensi.

- CPU per core   : host_processor_info (Mach, via ctypes)
- Suhu           : sensor IOHIDEventSystem (IOKit, via ctypes)
- GPU            : ioreg IOAccelerator PerformanceStatistics
- RAM            : vm_stat + sysctl
- Battery & power : ioreg AppleSmartBattery + pmset
- Jaringan/disk  : netstat -ibn, ioreg IOBlockStorageDriver, statvfs

Sampler berjalan di background tiap INTERVAL detik selama dashboard dibuka
(berhenti sendiri kalau tidak ada request > IDLE_AFTER detik).
"""
import ctypes
import os
import platform
import plistlib
import re
import subprocess
import threading
import time
from collections import deque
from ctypes import byref, c_char_p, c_double, c_int32, c_int64, c_long, c_uint, c_void_p, POINTER

INTERVAL = 2.0
HISTORY = 150  # 5 menit
IDLE_AFTER = 60


def sh(*cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ioreg_plist(*args):
    try:
        out = subprocess.run(["ioreg", "-a", *args], capture_output=True, timeout=10).stdout
        return plistlib.loads(out) if out else []
    except Exception:  # noqa: BLE001
        return []


def sysctl(name):
    return sh("sysctl", "-n", name).strip()


# ---------------------------------------------------------------- CPU (Mach)

IS_LINUX = platform.system() == "Linux"
if not IS_LINUX:  # Mach/IOKit — только macOS; на Linux функции подменяются из stats_linux ниже
    _libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
    _libc.mach_host_self.restype = c_uint
    _libc.host_processor_info.argtypes = [c_uint, c_int32, POINTER(c_uint), POINTER(POINTER(c_int32)), POINTER(c_uint)]
    _libc.vm_deallocate.argtypes = [c_uint, ctypes.c_size_t, ctypes.c_size_t]
    _task_self = c_uint.in_dll(_libc, "mach_task_self_")


def cpu_ticks():
    """[(user, system, idle, nice), ...] per core."""
    count, info, info_cnt = c_uint(), POINTER(c_int32)(), c_uint()
    if _libc.host_processor_info(_libc.mach_host_self(), 2, byref(count), byref(info), byref(info_cnt)) != 0:
        return []
    ticks = [tuple(info[i * 4 + j] & 0xFFFFFFFF for j in range(4)) for i in range(count.value)]
    _libc.vm_deallocate(_task_self.value, ctypes.cast(info, c_void_p).value, info_cnt.value * 4)
    return ticks


def cpu_usage(prev, cur):
    cores = []
    for a, b in zip(prev, cur):
        d = [(y - x) & 0xFFFFFFFF for x, y in zip(a, b)]
        total = sum(d)
        cores.append(round(100 * (total - d[2]) / total, 1) if total else 0.0)
    return cores


# ---------------------------------------------------------------- Suhu (IOKit HID)

class TempSensors:
    def __init__(self):
        self.ok = False
        try:
            self._init()
            self.ok = True
        except Exception:  # noqa: BLE001
            pass

    def _init(self):
        cf = self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        io = self.io = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        cf.CFStringCreateWithCString.restype = c_void_p
        cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, ctypes.c_uint32]
        cf.CFNumberCreate.restype = c_void_p
        cf.CFNumberCreate.argtypes = [c_void_p, c_int32, c_void_p]
        cf.CFDictionaryCreate.restype = c_void_p
        cf.CFDictionaryCreate.argtypes = [c_void_p, c_void_p, c_void_p, c_long, c_void_p, c_void_p]
        cf.CFArrayGetCount.restype = c_long
        cf.CFArrayGetCount.argtypes = [c_void_p]
        cf.CFArrayGetValueAtIndex.restype = c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, ctypes.c_uint32]
        cf.CFRelease.argtypes = [c_void_p]
        io.IOHIDEventSystemClientCreate.restype = c_void_p
        io.IOHIDEventSystemClientCreate.argtypes = [c_void_p]
        io.IOHIDEventSystemClientSetMatching.argtypes = [c_void_p, c_void_p]
        io.IOHIDEventSystemClientCopyServices.restype = c_void_p
        io.IOHIDEventSystemClientCopyServices.argtypes = [c_void_p]
        io.IOHIDServiceClientCopyProperty.restype = c_void_p
        io.IOHIDServiceClientCopyProperty.argtypes = [c_void_p, c_void_p]
        io.IOHIDServiceClientCopyEvent.restype = c_void_p
        io.IOHIDServiceClientCopyEvent.argtypes = [c_void_p, c_int64, c_int32, c_int64]
        io.IOHIDEventGetFloatValue.restype = c_double
        io.IOHIDEventGetFloatValue.argtypes = [c_void_p, c_int32]

        def num(v):
            x = c_int32(v)
            return cf.CFNumberCreate(None, 3, byref(x))  # kCFNumberSInt32Type

        keys = (c_void_p * 2)(self._str("PrimaryUsagePage"), self._str("PrimaryUsage"))
        vals = (c_void_p * 2)(num(0xFF00), num(5))  # vendor page, temperature sensor
        kcb = c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")
        vcb = c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")
        match = cf.CFDictionaryCreate(None, keys, vals, 2, ctypes.addressof(kcb), ctypes.addressof(vcb))
        self.client = io.IOHIDEventSystemClientCreate(None)
        io.IOHIDEventSystemClientSetMatching(self.client, match)
        self.product = self._str("Product")

    def _str(self, s):
        return self.cf.CFStringCreateWithCString(None, s.encode(), 0x08000100)

    def read(self):
        """{nama sensor: [nilai, ...]}"""
        if not self.ok:
            return {}
        cf, io = self.cf, self.io
        services = io.IOHIDEventSystemClientCopyServices(self.client)
        if not services:
            return {}
        result = {}
        buf = ctypes.create_string_buffer(128)
        for i in range(cf.CFArrayGetCount(services)):
            svc = cf.CFArrayGetValueAtIndex(services, i)
            name_ref = io.IOHIDServiceClientCopyProperty(svc, self.product)
            name = ""
            if name_ref:
                if cf.CFStringGetCString(name_ref, buf, 128, 0x08000100):
                    name = buf.value.decode(errors="replace")
                cf.CFRelease(name_ref)
            event = io.IOHIDServiceClientCopyEvent(svc, 15, 0, 0)  # kIOHIDEventTypeTemperature
            if event:
                value = io.IOHIDEventGetFloatValue(event, 15 << 16)
                cf.CFRelease(event)
                if 0 < value < 130:  # buang sensor yang tidak valid (-21.9 dll)
                    result.setdefault(name, []).append(value)
        cf.CFRelease(services)
        return result


def summarize_temps(raw):
    groups = {"CPU / SoC": [], "SSD": [], "Battery": []}
    for name, values in raw.items():
        if re.match(r"PMU\d* tdie", name):
            groups["CPU / SoC"] += values
        elif "NAND" in name:
            groups["SSD"] += values
        elif "battery" in name.lower():
            groups["Battery"] += values
    out = {}
    for k, v in groups.items():
        if v:
            out[k] = {"avg": round(sum(v) / len(v), 1), "max": round(max(v), 1), "sensors": len(v)}
    return out


# ---------------------------------------------------------------- RAM

def memory():
    out = sh("vm_stat")
    page = int(re.search(r"page size of (\d+)", out)[1]) if "page size" in out else 16384
    v = {m[0].strip().strip('"'): int(m[1]) * page for m in re.findall(r"^(.+?):\s+(\d+)\.", out, re.M)}
    total = int(sysctl("hw.memsize") or 0)
    wired = v.get("Pages wired down", 0)
    compressed = v.get("Pages occupied by compressor", 0)
    app = max(v.get("Anonymous pages", 0) - v.get("Pages purgeable", 0), 0)
    cached = v.get("File-backed pages", 0) + v.get("Pages purgeable", 0)
    used = app + wired + compressed
    swap = re.findall(r"(\w+) = ([\d.]+)M", sysctl("vm.swapusage"))
    swap = {k: float(val) * 1024 * 1024 for k, val in swap}
    level = sysctl("kern.memorystatus_vm_pressure_level")
    return {
        "total": total, "used": used, "app": app, "wired": wired, "compressed": compressed,
        "cached": cached, "free": max(total - used - cached, 0),
        "swap_used": swap.get("used", 0), "swap_total": swap.get("total", 0),
        "pressure": {"1": "normal", "2": "warning", "4": "critical"}.get(level, "normal"),
        "percent": round(100 * used / total, 1) if total else 0,
    }


# ---------------------------------------------------------------- GPU, baterai, jaringan, disk

def gpu():
    for acc in ioreg_plist("-r", "-d", "1", "-c", "IOAccelerator"):
        stats = acc.get("PerformanceStatistics") or {}
        if "Device Utilization %" in stats:
            return {"usage": stats["Device Utilization %"], "model": acc.get("model"),
                    "cores": acc.get("gpu-core-count"), "memory": stats.get("In use system memory", 0)}
    return None


def battery():
    items = ioreg_plist("-r", "-n", "AppleSmartBattery")
    if not items:
        return None
    b = items[0]
    data = b.get("BatteryData") or {}
    design = data.get("DesignCapacity") or b.get("DesignCapacity")
    nominal = data.get("NominalChargeCapacity") or b.get("NominalChargeCapacity")
    pmset = sh("pmset", "-g", "batt")
    source = "AC" if "AC Power" in pmset else "Battery"
    m = re.search(r"(\d+)%;\s*([^;]+);\s*([^\s]+)", pmset)
    tel = b.get("PowerTelemetryData") or {}
    amps = b.get("InstantAmperage", b.get("Amperage", 0))
    amps = amps - (1 << 64) if amps >= 1 << 63 else amps  # unsigned -> signed
    if source == "AC" and tel.get("SystemPowerIn"):
        watts = tel["SystemPowerIn"] / 1000
    else:
        watts = abs(amps * b.get("Voltage", 0)) / 1e6
    return {
        "percent": int(m[1]) if m else b.get("CurrentCapacity"),
        "state": m[2].strip() if m else ("charging" if b.get("IsCharging") else "discharging"),
        "remaining": m[3] if m and ":" in m[3] else None,
        "source": source, "cycles": b.get("CycleCount"),
        "health": round(100 * nominal / design, 1) if design and nominal else None,
        "design_mah": design, "max_mah": nominal, "watts": round(watts, 1),
        "adapter_watts": (b.get("AdapterDetails") or {}).get("Watts") if source == "AC" else None,
    }


def net_bytes():
    rx = tx = 0
    for line in sh("netstat", "-ibn").splitlines()[1:]:
        p = line.split()
        if len(p) >= 11 and p[2].startswith("<Link#") and re.match(r"en\d", p[0]):
            rx += int(p[6])
            tx += int(p[9])
    return rx, tx


def disk_io_bytes():
    r = w = 0
    for d in ioreg_plist("-r", "-c", "IOBlockStorageDriver", "-d", "1"):
        st = d.get("Statistics") or {}
        r += st.get("Bytes (Read)", 0)
        w += st.get("Bytes (Write)", 0)
    return r, w


def disk_usage():
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total": total, "free": free, "used": total - free, "percent": round(100 * (total - free) / total, 1)}


def top_processes(n=8):
    procs = []
    for line in sh("ps", "-Acwwo", "pid=,pcpu=,rss=,comm=").splitlines():
        p = line.split(None, 3)
        if len(p) == 4:
            procs.append({"pid": int(p[0]), "cpu": float(p[1]), "mem": int(p[2]) * 1024, "name": p[3]})
    return {"cpu": sorted(procs, key=lambda x: -x["cpu"])[:n],
            "mem": sorted(procs, key=lambda x: -x["mem"])[:n], "count": len(procs)}


_static = None


def system_info():
    global _static
    if _static is None:
        hw = sh("system_profiler", "SPHardwareDataType", "-json", timeout=20)
        try:
            import json
            h = json.loads(hw)["SPHardwareDataType"][0]
        except Exception:  # noqa: BLE001
            h = {}
        _static = {
            "hostname": sh("scutil", "--get", "ComputerName").strip() or platform.node(),
            "model": h.get("machine_name", "Mac"), "model_id": h.get("machine_model", sysctl("hw.model")),
            "chip": h.get("chip_type", sysctl("machdep.cpu.brand_string")),
            "cores_p": int(sysctl("hw.perflevel0.logicalcpu") or 0),
            "cores_e": int(sysctl("hw.perflevel1.logicalcpu") or 0),
            "macos": sh("sw_vers", "-productVersion").strip(),
            "build": sh("sw_vers", "-buildVersion").strip(),
        }
        _static["os_label"] = "macOS " + _static["macos"]
    boot = int(re.search(r"sec = (\d+)", sysctl("kern.boottime"))[1])
    return {**_static, "uptime": int(time.time() - boot), "load": [round(x, 2) for x in os.getloadavg()]}


# ---------------------------------------------------------------- sampler

class Sampler:
    def __init__(self):
        self.temps = TempSensors()
        self.history = deque(maxlen=HISTORY)
        self.latest = {}
        self.last_request = 0
        self.lock = threading.Lock()
        self.thread = None

    def touch(self):
        self.last_request = time.time()
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def _loop(self):
        prev_cpu, prev_net, prev_disk, prev_t = cpu_ticks(), net_bytes(), disk_io_bytes(), time.time()
        while time.time() - self.last_request < IDLE_AFTER:
            time.sleep(INTERVAL)
            now = time.time()
            dt = now - prev_t
            cur_cpu, cur_net, cur_disk = cpu_ticks(), net_bytes(), disk_io_bytes()
            cores = cpu_usage(prev_cpu, cur_cpu)
            temps = summarize_temps(self.temps.read())
            mem = memory()
            g = gpu()
            sample = {
                "t": int(now * 1000),
                "cpu": round(sum(cores) / len(cores), 1) if cores else 0,
                "cores": cores,
                "mem": mem["percent"],
                "gpu": g["usage"] if g else None,
                "temp": temps.get("CPU / SoC", {}).get("avg"),
                "rx": max(0, (cur_net[0] - prev_net[0]) / dt), "tx": max(0, (cur_net[1] - prev_net[1]) / dt),
                "dr": max(0, (cur_disk[0] - prev_disk[0]) / dt), "dw": max(0, (cur_disk[1] - prev_disk[1]) / dt),
            }
            with self.lock:
                self.history.append(sample)
                self.latest = {"memory": mem, "gpu": g, "temps": temps}
            prev_cpu, prev_net, prev_disk, prev_t = cur_cpu, cur_net, cur_disk, now

    def snapshot(self, since=0):
        self.touch()
        with self.lock:
            hist = [s for s in self.history if s["t"] > since]
            latest = dict(self.latest)
        return {
            "system": system_info(), "history": hist, "interval": INTERVAL,
            "memory": latest.get("memory") or memory(), "gpu": latest.get("gpu"),
            "temps": latest.get("temps") or summarize_temps(self.temps.read()),
            "temps_available": self.temps.ok,
            "battery": battery(), "disk": disk_usage(), "processes": top_processes(),
        }


if IS_LINUX:  # Фаза 6, Л1: те же имена, реализация из /proc и /sys
    from stats_linux import (TempSensors, battery, cpu_ticks, disk_io_bytes, disk_usage, gpu, memory, net_bytes,  # noqa: E402,F401
                             summarize_temps, system_info, top_processes)

SAMPLER = Sampler()
