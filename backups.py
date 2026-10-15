"""Резервные копии (Фаза 3): `git bundle` по каждому репозиторию + архивы папок данных + расписание + восстановление.

Куда: ЛОКАЛЬНАЯ папка или внешний диск (по умолчанию ~/Backups/Service Admin; путь настраивается). Облака нет —
это решение владельца для первой версии. Принципы:
  * место назначения — только внутри домашней папки или на /Volumes/…; не сама домашняя папка, не `~/.service-admin`,
    не `Library` и не внутри копируемой папки; создаётся с правами 0700, файлы 0600;
  * источники — зарегистрированные проекты (git bundle --all, пропускается, если ссылки не менялись) и папки данных,
    которые пользователь добавил сам (внутри домашней папки, без скрытых и Library) + данные самой панели
    (без `runtime/`, `tmp/`, `screenshots/`); на папку — лимит размера;
  * хранится не более `keep` последних копий каждого источника; каждая копия сразу проверяется
    (`git bundle verify` / чтение архива);
  * ВОССТАНОВЛЕНИЕ НИКОГДА НЕ ПЕРЕЗАПИСЫВАЕТ оригиналы: bundle клонируется, архив распаковывается в новую папку
    `~/Restored/<имя>-<время>`; перед распаковкой записи архива проверяются на `..` и абсолютные пути;
  * расписание — поток внутри панели (проверка раз в 5 минут): копия делается, когда с прошлой попытки прошёл
    интервал; после неудачи повтор не чаще раза в час; пропущенное из-за сна Mac наверстывается при пробуждении.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from http import HTTPStatus

import projects
from core import DATA_DIR, ENV, HOME, ApiError, notify, start_steps

CONFIG_FILE = os.path.join(DATA_DIR, "backup.json")
HISTORY_FILE = os.path.join(DATA_DIR, "backup-history.jsonl")
RESTORE_ROOT = os.path.join(HOME, "Restored")
DEFAULT_DEST = os.path.join(HOME, "Backups", "Service Admin")
INTERVALS = (6, 12, 24, 72, 168)
MAX_FOLDERS = 20
MAX_FOLDER_KB = 20 * 1024 * 1024  # 20 ГБ на папку
HISTORY_MAX = 200
GIT_TIMEOUT = 600
RETRY_AFTER_FAIL = 3600
PANEL_EXCLUDES = ("runtime", "tmp", "screenshots", "worktrees")
KIND_DIRS = {"repo": "repos", "folder": "folders", "panel": "panel"}
_LOCK = threading.Lock()
HOME_REAL = os.path.realpath(HOME)


# ---------------------------------------------------------------- настройки

DEFAULTS = {"dest": DEFAULT_DEST, "enabled": False, "interval_hours": 24, "keep": 5,
            "repos": True, "panel_data": True, "folders": []}


def _load_config():
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    return cfg


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _inside(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False


def check_dest(raw):
    """Допустимое место назначения → абсолютный путь (папка может ещё не существовать)."""
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError("Укажите папку для копий", code="bk.dest_missing")
    dest = os.path.abspath(os.path.expanduser(raw.strip()))
    real = os.path.realpath(dest)
    in_home = _inside(real, HOME_REAL) and real != HOME_REAL
    on_volume = real.startswith("/Volumes/") and len(real.split("/")) > 3
    if not (in_home or on_volume):
        raise ApiError("Папка для копий должна быть внутри домашней папки или на внешнем диске (/Volumes/…)",
                       code="bk.dest_outside")
    rel = os.path.relpath(real, HOME_REAL) if in_home else ""
    if in_home and (rel.split(os.sep)[0] in ("Library", ".service-admin") or _inside(real, DATA_DIR)):
        raise ApiError("Нельзя хранить копии в Library или в папке данных панели", code="bk.dest_forbidden")
    return dest


def check_folder(raw):
    """Папка данных для копирования: существует, внутри дома, не скрытая и не Library."""
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError("Укажите папку", code="bk.folder_missing")
    real = projects._canon(os.path.realpath(os.path.expanduser(raw.strip())))  # noqa: SLF001
    if not os.path.isdir(real):
        raise ApiError("Папка не найдена", HTTPStatus.NOT_FOUND, code="bk.folder_not_found")
    rel = os.path.relpath(real, HOME_REAL)
    if rel == "." or rel.startswith(".."):
        raise ApiError("Папка должна лежать внутри домашней папки (не сама домашняя)", code="bk.folder_outside")
    parts = rel.split(os.sep)
    if parts[0] == "Library" or any(p.startswith(".") for p in parts):
        raise ApiError("Скрытые папки и Library копировать нельзя", code="bk.folder_hidden")
    return real


def get_config(q=None):
    cfg = _load_config()
    return {"config": cfg, "intervals": list(INTERVALS)}


def set_config(body):
    cur = _load_config()
    cfg = dict(cur)
    if "dest" in body:
        cfg["dest"] = check_dest(body["dest"])
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    if "interval_hours" in body:
        if body["interval_hours"] not in INTERVALS:
            raise ApiError(f"Интервал: одно из {list(INTERVALS)} часов", code="bk.interval", values=str(list(INTERVALS)))
        cfg["interval_hours"] = body["interval_hours"]
    if "keep" in body:
        if not isinstance(body["keep"], int) or isinstance(body["keep"], bool) or not 1 <= body["keep"] <= 30:
            raise ApiError("Хранить от 1 до 30 копий", code="bk.keep")
        cfg["keep"] = body["keep"]
    for k in ("repos", "panel_data"):
        if k in body:
            cfg[k] = bool(body[k])
    if "folders" in body:
        raw = body["folders"]
        if not isinstance(raw, list) or len(raw) > MAX_FOLDERS:
            raise ApiError(f"Не более {MAX_FOLDERS} папок", code="bk.folders_count", max=MAX_FOLDERS)
        cfg["folders"] = list(dict.fromkeys(check_folder(x) for x in raw))
    for f in cfg["folders"]:  # место назначения не может лежать внутри копируемой папки
        if _inside(cfg["dest"], f):
            raise ApiError("Папка для копий не может находиться внутри копируемой папки", code="bk.dest_in_source")
    _write_json(CONFIG_FILE, cfg)
    return {"config": cfg}


# ---------------------------------------------------------------- история

def _history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            rows = []
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows
    except OSError:
        return []


def _record(entry):
    with _LOCK:
        rows = _history() + [entry]
        if len(rows) > HISTORY_MAX:
            rows = rows[-HISTORY_MAX:]
        tmp = HISTORY_FILE + ".tmp"
        os.makedirs(DATA_DIR, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)


def _slug(name):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "item"
    return s[:40]


def _item_key(kind, path):
    return f"{_slug(os.path.basename(path.rstrip('/')) or kind)}-{hashlib.sha1(path.encode()).hexdigest()[:6]}"


# ---------------------------------------------------------------- создание копий

def _ts():
    return time.strftime("%Y%m%d-%H%M%S")


def _prune(item_dir, suffix, keep):
    files = sorted((f for f in os.listdir(item_dir) if f.endswith(suffix)), reverse=True)
    for old in files[keep:]:
        try:
            os.unlink(os.path.join(item_dir, old))
        except OSError:
            pass


def _refs_fingerprint(repo):
    r = subprocess.run([projects.GIT, "for-each-ref", "--format=%(refname) %(objectname)"], cwd=repo, env=ENV,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return hashlib.sha1(r.stdout.encode()).hexdigest()


def _backup_repo(repo, dest, keep):
    key = _item_key("repo", repo)
    item_dir = os.path.join(dest, KIND_DIRS["repo"], key)
    name = os.path.basename(repo)
    fp = _refs_fingerprint(repo)
    if fp is None:
        return {"kind": "repo", "name": name, "status": "skipped", "message": "empty"}  # нет коммитов
    os.makedirs(item_dir, mode=0o700, exist_ok=True)
    marker = os.path.join(item_dir, ".refs")
    try:
        if open(marker).read() == fp and any(f.endswith(".bundle") for f in os.listdir(item_dir)):
            return {"kind": "repo", "name": name, "status": "unchanged", "message": ""}
    except OSError:
        pass
    out = os.path.join(item_dir, _ts() + ".bundle")
    r = subprocess.run([projects.GIT, "bundle", "create", out, "--all"], cwd=repo, env=ENV,
                       capture_output=True, text=True, timeout=GIT_TIMEOUT)
    if r.returncode != 0:
        _unlink(out)
        return {"kind": "repo", "name": name, "status": "failed", "message": (r.stderr.strip().splitlines() or ["git bundle"])[-1]}
    ok, level, msg = _verify_bundle(out, item_dir)
    if not ok:
        _unlink(out)
        return {"kind": "repo", "name": name, "status": "failed", "message": "verify: " + msg}
    os.chmod(out, 0o600)
    with open(marker, "w") as f:
        f.write(fp)
    _prune(item_dir, ".bundle", keep)
    return {"kind": "repo", "name": name, "status": "ok", "file": os.path.relpath(out, dest), "size": os.path.getsize(out),
            "verified": True, "verify_level": level}


DEEP_VERIFY_MAX = 500 * 1024 * 1024  # крупнее — облегчённая проверка (клонировать гигабайты на каждую копию слишком дорого)


def _verify_bundle(bundle, work_dir):
    """→ (ok, level, message). `git bundle verify` проверяет заголовок и пререквизиты, но НЕ весь pack —
    усечённый bundle он пропускает. Поэтому до DEEP_VERIFY_MAX bundle клонируется во временный bare-репозиторий
    и проходит fsck; крупнее — облегчённая проверка, и об этом честно сообщается (level="light")."""
    light = subprocess.run([projects.GIT, "bundle", "verify", bundle], env=ENV, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    if light.returncode != 0:
        return False, "light", (light.stderr.strip().splitlines() or ["bundle verify"])[-1]
    if os.path.getsize(bundle) > DEEP_VERIFY_MAX:
        return True, "light", ""
    tmp = os.path.join(work_dir, f".verify-{os.getpid()}-{int(time.time() * 1000)}")
    try:
        os.makedirs(tmp, mode=0o700)
        r = subprocess.run([projects.GIT, "clone", "--bare", "-q", bundle, os.path.join(tmp, "r.git")], env=dict(ENV, GIT_TERMINAL_PROMPT="0"),
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
        if r.returncode != 0:
            return False, "deep", (r.stderr.strip().splitlines() or ["clone"])[-1]
        f = subprocess.run([projects.GIT, "fsck", "--connectivity-only", "--no-progress"], cwd=os.path.join(tmp, "r.git"), env=ENV,
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
        if f.returncode != 0:
            return False, "deep", (f.stderr.strip().splitlines() or ["fsck"])[-1]
        return True, "deep", ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _du_kb(path):
    r = subprocess.run(["/usr/bin/du", "-sk", path], capture_output=True, text=True, timeout=120)
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def _backup_dir(kind, src, dest, keep, excludes=()):
    key = _item_key(kind, src)
    name = os.path.basename(src.rstrip("/")) or kind
    if not os.path.isdir(src):
        return {"kind": kind, "name": name, "status": "failed", "message": "missing"}
    kb = _du_kb(src)
    if kb > MAX_FOLDER_KB:
        return {"kind": kind, "name": name, "status": "failed", "message": f"too_big:{kb // 1024 // 1024}"}
    item_dir = os.path.join(dest, KIND_DIRS[kind], key)
    os.makedirs(item_dir, mode=0o700, exist_ok=True)
    out = os.path.join(item_dir, _ts() + ".tar.gz")
    cmd = ["/usr/bin/tar", "-czf", out]
    for ex in excludes:
        cmd += ["--exclude", ex]
    cmd += ["-C", os.path.dirname(src), os.path.basename(src)]
    r = subprocess.run(cmd, env=dict(ENV, COPYFILE_DISABLE="1"), capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        _unlink(out)
        return {"kind": kind, "name": name, "status": "failed", "message": (r.stderr.strip().splitlines() or ["tar"])[-1]}
    v = subprocess.run(["/usr/bin/tar", "-tzf", out], capture_output=True, text=True, timeout=3600)
    if v.returncode != 0:
        _unlink(out)
        return {"kind": kind, "name": name, "status": "failed", "message": "verify: archive unreadable"}
    os.chmod(out, 0o600)
    _prune(item_dir, ".tar.gz", keep)
    return {"kind": kind, "name": name, "status": "ok", "file": os.path.relpath(out, dest), "size": os.path.getsize(out), "verified": True}


def _sources(cfg):
    out = []
    if cfg["repos"]:
        try:
            repos = [p["path"] for p in projects.list_projects({})["projects"] if not p.get("worktree")]  # linked worktree — тот же репозиторий
        except Exception:  # noqa: BLE001
            repos = []
        out += [("repo", r) for r in repos]
    if cfg["panel_data"]:
        out.append(("panel", DATA_DIR))
    out += [("folder", f) for f in cfg["folders"]]
    return out


def run_backup(log=lambda s: None, trigger="manual"):
    """Выполнить копию по настройкам. Возвращает запись истории; исключений не бросает (ошибки — в записи)."""
    cfg = _load_config()
    t0 = time.time()
    entry = {"id": "b" + _ts(), "started": t0, "trigger": trigger, "dest": cfg["dest"], "items": [], "status": "failed", "duration": 0}
    try:
        dest = check_dest(cfg["dest"])
        if dest.startswith("/Volumes/") and not os.path.isdir("/".join(dest.split("/")[:3])):
            raise OSError("volume_missing")
        os.makedirs(dest, mode=0o700, exist_ok=True)
        os.chmod(dest, 0o700)
    except (ApiError, OSError) as e:
        entry["message"] = "volume_missing" if "volume_missing" in str(e) else "dest_unavailable"
        entry["duration"] = round(time.time() - t0, 1)
        _record(entry)
        log(f"✖ Место назначения недоступно: {cfg['dest']}")
        return entry
    for kind, src in _sources(cfg):
        label = os.path.basename(src.rstrip("/")) or kind
        log(f"▶ {kind}: {label}")
        try:
            if kind == "repo":
                item = _backup_repo(src, dest, cfg["keep"])
            else:
                item = _backup_dir(kind, src, dest, cfg["keep"], PANEL_EXCLUDES if kind == "panel" else ())
        except subprocess.TimeoutExpired:
            item = {"kind": kind, "name": label, "status": "failed", "message": "timeout"}
        except Exception as e:  # noqa: BLE001
            item = {"kind": kind, "name": label, "status": "failed", "message": str(e)[:120]}
        entry["items"].append(item)
        log(f"   {item['status']}" + (f" — {item['message']}" if item.get("message") else ""))
    bad = [i for i in entry["items"] if i["status"] == "failed"]
    good = [i for i in entry["items"] if i["status"] in ("ok", "unchanged")]
    entry["status"] = "ok" if not bad else ("partial" if good else "failed")
    entry["duration"] = round(time.time() - t0, 1)
    _record(entry)
    return entry


def start(body=None, trigger="manual"):
    """POST /api/backups/run → job. trigger="schedule" — запуск планировщика."""
    cfg = _load_config()
    check_dest(cfg["dest"])

    def step(log):
        e = run_backup(log, trigger)
        if e["status"] != "ok":
            if trigger == "schedule":
                _notify_failure(e["status"])
            raise RuntimeError(f"копия: {e['status']}")
    return {"job": start_steps("Резервная копия", [("Копирование", step, {})], "backup")}


# ---------------------------------------------------------------- состояние и поиск копий

def _artifacts(dest):
    """Копии, реально лежащие на диске: {kind, key, files[{file,size,mtime}]}. Работает и без истории."""
    out = []
    for kind, sub in KIND_DIRS.items():
        base = os.path.join(dest, sub)
        if not os.path.isdir(base):
            continue
        for key in sorted(os.listdir(base)):
            d = os.path.join(base, key)
            if not os.path.isdir(d):
                continue
            files = []
            for f in sorted(os.listdir(d), reverse=True):
                if f.endswith((".bundle", ".tar.gz")):
                    st = os.stat(os.path.join(d, f))
                    files.append({"file": f"{sub}/{key}/{f}", "size": st.st_size, "mtime": st.st_mtime})
            if files:
                out.append({"kind": kind, "key": key, "files": files})
    return out


def status(q=None):
    cfg = _load_config()
    hist = _history()
    last = hist[-1] if hist else None
    last_ok = next((h for h in reversed(hist) if h["status"] in ("ok", "partial")), None)
    dest_ok = os.path.isdir(cfg["dest"])
    nxt = None
    if cfg["enabled"]:
        base = (last or {}).get("started")
        nxt = (base + cfg["interval_hours"] * 3600) if base else time.time()
        if last and last["status"] == "failed":
            nxt = max(nxt, last["started"] + RETRY_AFTER_FAIL)
    return {"config": cfg, "intervals": list(INTERVALS), "dest_exists": dest_ok, "last": last, "last_ok": last_ok,
            "next_due": nxt, "history": hist[-15:][::-1], "artifacts": _artifacts(cfg["dest"]) if dest_ok else [],
            "restore_root": RESTORE_ROOT}


# ---------------------------------------------------------------- проверка и восстановление

def _artifact_path(rel):
    cfg = _load_config()
    if not isinstance(rel, str) or ".." in rel.split("/") or rel.startswith("/"):
        raise ApiError("Неверный путь копии", code="bk.bad_artifact")
    full = os.path.realpath(os.path.join(cfg["dest"], rel))
    if not _inside(full, cfg["dest"]) or not os.path.isfile(full) or not rel.endswith((".bundle", ".tar.gz")) \
            or rel.split("/")[0] not in KIND_DIRS.values():
        raise ApiError("Копия не найдена", HTTPStatus.NOT_FOUND, code="bk.artifact_not_found")
    return full


def verify(body):
    """POST {file} — проверить одну копию (bundle verify / чтение архива)."""
    full = _artifact_path(body.get("file"))
    if full.endswith(".bundle"):
        ok, level, m = _verify_bundle(full, os.path.dirname(full))
        return {"file": body["file"], "ok": ok, "level": level, "message": m}
    else:
        r = subprocess.run(["/usr/bin/tar", "-tzf", full], capture_output=True, text=True, timeout=3600)
        ok, msg = r.returncode == 0, [] if r.returncode == 0 else (r.stderr.strip().splitlines()[-1:] or [""])
    return {"file": body["file"], "ok": ok, "level": "archive", "message": msg[0] if msg else ""}


def _safe_members(archive):
    r = subprocess.run(["/usr/bin/tar", "-tzf", archive], capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise ApiError("Архив повреждён", HTTPStatus.CONFLICT, code="bk.archive_corrupt")
    for name in r.stdout.splitlines():
        parts = name.split("/")
        if name.startswith("/") or ".." in parts:
            raise ApiError("В архиве небезопасные пути — восстановление отклонено", HTTPStatus.CONFLICT, code="bk.archive_unsafe")


def restore(body):
    """POST {file} → job: восстановить копию в НОВУЮ папку ~/Restored/<имя>-<время>; оригиналы не трогаются."""
    full = _artifact_path(body.get("file"))
    key = body["file"].split("/")[1]
    target = os.path.join(RESTORE_ROOT, f"{key}-{_ts()}")
    if full.endswith(".tar.gz"):
        _safe_members(full)

    def step(log):
        os.makedirs(RESTORE_ROOT, mode=0o700, exist_ok=True)
        if full.endswith(".bundle"):
            r = subprocess.run([projects.GIT, "clone", full, target], env=dict(ENV, GIT_TERMINAL_PROMPT="0"),
                               capture_output=True, text=True, timeout=GIT_TIMEOUT)
        else:
            os.makedirs(target, mode=0o700)
            r = subprocess.run(["/usr/bin/tar", "-xzf", full, "-C", target], capture_output=True, text=True, timeout=3600)
        for line in (r.stdout + r.stderr).splitlines()[-10:]:
            log(line)
        if r.returncode != 0:
            raise RuntimeError("восстановление не удалось")
        log(f"Восстановлено в: {target}")
    return {"job": start_steps(f"Восстановление: {key}", [("Восстановление", step, {})], "backup-restore"), "target": target}


# ---------------------------------------------------------------- расписание

def due(now=None, cfg=None, hist=None):
    """Пора ли делать копию по расписанию (чистая функция — проверяется без ожидания)."""
    now = now or time.time()
    cfg = cfg or _load_config()
    hist = _history() if hist is None else hist
    if not cfg["enabled"]:
        return False
    if not hist:
        return True
    last = hist[-1]
    wait = cfg["interval_hours"] * 3600
    if last["status"] == "failed":
        wait = max(RETRY_AFTER_FAIL, min(wait, RETRY_AFTER_FAIL))
    return now - last["started"] >= wait


_NOTIFIED = {"t": 0.0}
_NOTIFY_LOCK = threading.Lock()
NOTIFY_EVERY = 6 * 3600
NOTIFY_TEXT = {
    "ru": {"title": "Резервная копия не сделана", "failed": "Плановая копия завершилась с ошибкой. Откройте «Резервные копии» в Service Admin.",
           "partial": "Плановая копия сделана не полностью. Откройте «Резервные копии» в Service Admin.",
           "dest": "Папка назначения недоступна (диск отключён?). Плановая копия не запущена."},
    "en": {"title": "Backup was not made", "failed": "The scheduled backup failed. Open Backups in Service Admin.",
           "partial": "The scheduled backup is incomplete. Open Backups in Service Admin.",
           "dest": "The destination folder is unavailable (disk unplugged?). The scheduled backup did not start."},
}


def _notify_failure(kind, now=None):
    """Уведомление о сбое плановой копии (не чаще раза в 6 часов, чтобы не спамить каждые 5 минут)."""
    now = now or time.time()
    with _NOTIFY_LOCK:
        if now - _NOTIFIED["t"] < NOTIFY_EVERY:
            return False
        _NOTIFIED["t"] = now
    try:
        import plans
        lang = plans._ui_lang()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        lang = "ru"
    d = NOTIFY_TEXT.get(lang, NOTIFY_TEXT["ru"])
    return notify(d["title"], d.get(kind, d["failed"]))


def _scheduler_loop(period=300):
    import audit
    audit.INITIATOR.set("system:scheduler")
    while True:
        time.sleep(period)
        try:
            from core import JOBS
            if any(j["kind"] == "backup" and not j["done"] for j in JOBS.values()):
                continue
            if due():
                start(None, "schedule")
        except ApiError as e:  # назначение недоступно (диск отключён и т. п.) — копия НЕ запустилась; сообщаем, но не чаще раза в 6 часов
            if str(getattr(e, "code", "")).startswith("bk.dest"):
                _notify_failure("dest")
        except Exception:  # noqa: BLE001 - планировщик не должен падать
            pass


def start_scheduler():
    threading.Thread(target=_scheduler_loop, daemon=True).start()
