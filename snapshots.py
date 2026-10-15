"""Снимки окружения: что стоит на машине сейчас — и что изменилось с прошлого раза.

Снимок = один JSON в ~/.service-admin/snapshots/<ГГГГММДД-ЧЧММСС>.json (0600). Собирается теми же
детекторами, что и страницы Фазы 1 (brew, runtimes, mobile, profiles, setup); ничего не меняет в
системе, пишет только свой файл. Два снимка (или снимок и «сейчас») сравниваются: добавлено / убрано /
изменено по каждому разделу.

Что НЕ попадает в снимок: содержимое файлов, переменные окружения, пароли, токены.
"""
import json
import os
import platform
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import mobile
import platform_info
import profiles
import runtimes
import setup
from core import DATA_DIR, ENV, ApiError, run

SNAP_DIR = os.path.join(DATA_DIR, "snapshots")
SCHEMA = 1
ID_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
MAX_SNAPSHOTS = 200
LABEL_MAX = 80
BREW_TIMEOUT = 90


def _brew():
    return setup._brew_path()  # noqa: SLF001 - один источник правды о том, где brew


def _brew_lines(brew, *args, timeout=BREW_TIMEOUT):
    try:
        code, out, _ = run([brew, *args], timeout=timeout)
    except Exception:  # noqa: BLE001 - таймаут/ошибка запуска: раздел просто неполный
        return None
    return out if code == 0 else None


def _versions(text):
    """`brew list --versions`: «name 1.2 1.3» → {name: «1.2 1.3»}."""
    res = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if parts:
            res[parts[0]] = " ".join(parts[1:])
    return res


def _collect_brew():
    brew = _brew()
    if not brew:
        return {"available": False}
    with ThreadPoolExecutor(max_workers=4) as pool:
        f = pool.submit(_brew_lines, brew, "list", "--formula", "--versions")
        c = pool.submit(_brew_lines, brew, "list", "--cask", "--versions")
        t = pool.submit(_brew_lines, brew, "tap")
        b = pool.submit(_brew_lines, brew, "bundle", "dump", "--file=-")
        formulae, casks, taps, bundle = f.result(), c.result(), t.result(), b.result()
    return {"available": True, "formulae": _versions(formulae), "casks": _versions(casks),
            "taps": sorted((taps or "").split()), "brewfile": bundle or "",
            "complete": None not in (formulae, casks, taps, bundle)}


def _collect_apt():
    """Linux: вручную установленные пакеты apt и их версии (dpkg-query). На macOS — {"available": False}."""
    import platform_info
    if not platform_info.has("pkg.apt"):
        return {"available": False}
    try:
        manual = set(run(["apt-mark", "showmanual"], timeout=30)[1].split())
        out = run(["dpkg-query", "-W", "-f", "${Package}\\t${Version}\\n"], timeout=30)[1]
    except Exception:  # noqa: BLE001
        return {"available": True, "manual": {}, "complete": False}
    vers = {}
    for line in out.splitlines():
        name, _, ver = line.partition("\t")
        if name in manual:
            vers[name] = ver
    return {"available": True, "manual": vers, "complete": bool(vers)}


def _collect_runtimes():
    try:
        langs = runtimes.detect(True)["langs"]
    except Exception:  # noqa: BLE001
        return []
    return [{"key": l["key"], "name": l["name"], "version": l.get("version"), "source": l.get("source"),
             "path": l.get("path")} for l in langs]


def _collect_mobile():
    out = {}
    try:
        x = mobile.xcode_info()
        out["xcode"] = {
            "installs": [{"version": i.get("version"), "build": i.get("build"), "path": i.get("path")}
                         for i in x.get("installs", [])],
            "active": (x.get("active") or {}).get("version"),
            "selected_path": x.get("selected_path"),
            "clt": bool((x.get("clt") or {}).get("installed")),
            "first_launch_done": (x.get("first_launch") or {}).get("done"),
            "runtimes": [{"name": r.get("name"), "available": r.get("available")} for r in x.get("runtimes", [])],
        }
    except Exception:  # noqa: BLE001
        out["xcode"] = None
    try:
        m = mobile.mobile_info({})
        sdk = (m.get("flutter") or {}).get("sdk") or {}
        out["flutter"] = {"version": sdk.get("version"), "channel": sdk.get("channel"), "dart": sdk.get("dart")} if sdk else None
        a = m.get("android") or {}
        out["android"] = {"sdk_path": a.get("sdk_path"), "platforms": a.get("platforms", []),
                          "build_tools": a.get("build_tools", []), "ndk": a.get("ndk", [])} if a.get("sdk_path") else None
    except Exception:  # noqa: BLE001
        out["flutter"] = out["android"] = None
    return out


def _collect_profiles():
    res = {}
    for p in profiles.catalog({"refresh": "1"})["profiles"]:
        res[p["id"]] = {i["id"]: {"installed": i["installed"], "version": i.get("version")} for i in p["items"]}
    return res


def _macos():
    if sys.platform != "darwin":
        return platform_info._os_release().get("PRETTY_NAME")  # noqa: SLF001
    try:
        return run(["/usr/bin/sw_vers", "-productVersion"], timeout=5)[1].strip()
    except Exception:  # noqa: BLE001
        return None


def collect(label=""):
    """Собрать снимок «как сейчас» (не сохраняя)."""
    label = (label or "").strip()
    if len(label) > LABEL_MAX or any(ord(ch) < 32 for ch in label):
        raise ApiError(f"Подпись: до {LABEL_MAX} символов, без управляющих", HTTPStatus.BAD_REQUEST, code="snap.label", max=LABEL_MAX)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        brew_f = pool.submit(_collect_brew)
        rt_f = pool.submit(_collect_runtimes)
        mob_f = pool.submit(_collect_mobile)
        prof_f = pool.submit(_collect_profiles)
        brew, rts, mob, prof = brew_f.result(), rt_f.result(), mob_f.result(), prof_f.result()
    rt = setup.runtime_info()
    return {"schema": SCHEMA, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": label,
            "system": {"macos": _macos(), "arch": platform.machine()},
            "panel": {"python": rt["version"], "bundled": rt["bundled"]},
            "brew": brew, "apt": _collect_apt(), "runtimes": rts, **mob, "profiles": prof,
            "setup": {k: v for k, v in setup.status().items() if k in ("ready", "missing")},
            "took_ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- хранение

def _check_id(snap_id):
    if not isinstance(snap_id, str) or not ID_RE.match(snap_id):
        raise ApiError("Неверный id снимка", HTTPStatus.BAD_REQUEST, code="snap.bad_id")
    return snap_id


def _path(snap_id):
    return os.path.join(SNAP_DIR, _check_id(snap_id) + ".json")


def _ids():
    try:
        names = os.listdir(SNAP_DIR)
    except OSError:
        return []
    return sorted((n[:-5] for n in names if n.endswith(".json") and ID_RE.match(n[:-5])), reverse=True)


def create(body):
    if len(_ids()) >= MAX_SNAPSHOTS:
        raise ApiError(f"Достигнут предел {MAX_SNAPSHOTS} снимков — удалите старые", HTTPStatus.CONFLICT, code="snap.limit", max=MAX_SNAPSHOTS)
    snap = collect(body.get("label", ""))
    base = time.strftime("%Y%m%d-%H%M%S")
    snap_id, n = base, 1
    while os.path.exists(_path(snap_id)):
        n += 1
        snap_id = f"{base}-{n}"
    snap["id"] = snap_id
    os.makedirs(SNAP_DIR, mode=0o700, exist_ok=True)
    tmp = _path(snap_id) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(snap_id))  # атомарно: недописанного снимка не бывает
    return {"id": snap_id, "snapshot": _summary(snap)}


def _summary(snap):
    brew = snap.get("brew") or {}
    return {"id": snap.get("id"), "created": snap.get("created"), "label": snap.get("label", ""),
            "counts": {"formulae": len(brew.get("formulae", {})), "casks": len(brew.get("casks", {})),
                       "apt": len((snap.get("apt") or {}).get("manual", {})),
                       "runtimes": len(snap.get("runtimes", [])),
                       "xcode": len(((snap.get("xcode") or {}).get("installs")) or [])},
            "brew_available": bool(brew.get("available")), "complete": brew.get("complete")}


def _load(snap_id):
    try:
        with open(_path(snap_id), encoding="utf-8") as f:
            snap = json.load(f)
    except OSError:
        raise ApiError("Снимок не найден", HTTPStatus.NOT_FOUND, code="snap.missing") from None
    except ValueError:
        raise ApiError("Снимок повреждён", HTTPStatus.INTERNAL_SERVER_ERROR, code="snap.corrupt") from None
    snap.setdefault("id", snap_id)
    return snap


def list_snapshots(q=None):
    out = []
    for sid in _ids():
        try:
            out.append(_summary(_load(sid)))
        except ApiError:
            out.append({"id": sid, "created": None, "label": "", "broken": True, "counts": {}})
    return {"snapshots": out}


def get(q):
    return _load(q.get("id"))


def delete(body):
    sid = _check_id(body.get("id"))
    if not os.path.exists(_path(sid)):
        raise ApiError("Снимок не найден", HTTPStatus.NOT_FOUND, code="snap.missing")
    os.unlink(_path(sid))
    return {"deleted": sid}


# ---------------------------------------------------------------- сравнение

def facts(snap):
    """Снимок → {раздел: {ключ: значение}} — общий вид для сравнения."""
    f = {}
    brew = snap.get("brew") or {}
    f["brew.formula"] = dict(brew.get("formulae", {}))
    f["brew.cask"] = dict(brew.get("casks", {}))
    f["brew.tap"] = {t: "" for t in brew.get("taps", [])}
    f["apt.manual"] = dict((snap.get("apt") or {}).get("manual", {}))
    f["runtime"] = {r["key"]: f'{r.get("version") or "?"} · {r.get("source") or "?"}' for r in snap.get("runtimes", [])}
    x = snap.get("xcode") or {}
    f["xcode"] = {f'Xcode {i.get("version")}': i.get("build") or "" for i in x.get("installs", [])}
    if x:
        f["xcode"]["active"] = str(x.get("active"))
        f["xcode"]["clt"] = "yes" if x.get("clt") else "no"
        f["xcode"]["first_launch"] = str(x.get("first_launch_done"))
    f["xcode.runtime"] = {r["name"]: "available" if r.get("available") else "unavailable" for r in x.get("runtimes", [])}
    fl = snap.get("flutter") or {}
    f["flutter"] = {k: str(v) for k, v in fl.items() if v}
    an = snap.get("android") or {}
    f["android"] = {f"{k}:{v}": "" for k in ("platforms", "build_tools", "ndk") for v in an.get(k, [])}
    for pid, items in (snap.get("profiles") or {}).items():
        f[f"profile.{pid}"] = {iid: (v.get("version") or "installed") if v.get("installed") else "missing"
                               for iid, v in items.items()}
    f["system"] = {"macos": str((snap.get("system") or {}).get("macos")), "arch": str((snap.get("system") or {}).get("arch"))}
    return f


def diff_facts(a, b):
    sections = []
    for sec in sorted(set(a) | set(b)):
        fa, fb = a.get(sec, {}), b.get(sec, {})
        added = [{"key": k, "to": fb[k]} for k in sorted(set(fb) - set(fa))]
        removed = [{"key": k, "from": fa[k]} for k in sorted(set(fa) - set(fb))]
        changed = [{"key": k, "from": fa[k], "to": fb[k]} for k in sorted(set(fa) & set(fb)) if fa[k] != fb[k]]
        if added or removed or changed:
            sections.append({"id": sec, "added": added, "removed": removed, "changed": changed})
    return sections


def _resolve(ref):
    """id снимка или «current» (собрать прямо сейчас, не сохраняя)."""
    if ref == "current":
        snap = collect()
        snap["id"] = "current"
        return snap
    return _load(ref)


def diff(q):
    a, b = _resolve(q.get("a")), _resolve(q.get("b"))
    sections = diff_facts(facts(a), facts(b))
    brew_note = None
    if (a.get("brew") or {}).get("complete") is False or (b.get("brew") or {}).get("complete") is False:
        brew_note = "incomplete"  # brew не ответил за таймаут — различия по brew могут быть неполными
    return {"a": {"id": a["id"], "created": a.get("created"), "label": a.get("label", "")},
            "b": {"id": b["id"], "created": b.get("created"), "label": b.get("label", "")},
            "sections": sections, "total": sum(len(s["added"]) + len(s["removed"]) + len(s["changed"]) for s in sections),
            "note": brew_note}
