"""Шлюз для ИИ-агентов (Фаза 4.0): реестр агентов, проверка прав и набор инструментов уровня L1 (только чтение).

Принципы (см. docs/roadmap.md, Фаза 4):
  * агенту выдаётся НЕ доступ к машине, а небольшой стабильный набор операций; произвольной команды и shell нет;
  * реестр — `~/.service-admin/agent-registry.json`; панель хранит только SHA-256 секрета, сам секрет лежит в файле
    `~/.service-admin/agents/<id>.token` (0600) и никогда не уходит в браузер, логи и argv;
  * уровень прав задаёт панель (сейчас только L1 — чтение), а не слова агента; отозванный/просроченный агент не проходит;
  * каждый вызов — в журнал аудита с идентичностью агента; частота ограничена; размер ответа ограничен;
  * честно: агент на том же Mac обычно имеет собственный Bash и может обойти этот API. Ценность шлюза — единый
    контракт, аудит и проверки; настоящая граница безопасности появится с очередью подтверждений (4.2+).
"""
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import socket
import threading
import time
from http import HTTPStatus

import audit
import core
import opschema
from core import DATA_DIR, ApiError

REG_FILE = os.path.join(DATA_DIR, "agent-registry.json")
TOKEN_DIR = os.path.join(DATA_DIR, "agents")
SOCKET_PATH = os.path.join(DATA_DIR, "agent.sock")
NAME_RE = re.compile(r"^\w[\w ._-]{0,39}$")
MAX_AGENTS = 20
RATE_PER_MIN = 60
MAX_RESULT_BYTES = 200_000
TOKEN_MAX = 200
LEVELS = {"L1": 1, "L2": 2, "L3": 3}
_LOCK = threading.Lock()
_CALLS = {}      # agent id -> [timestamps] (скользящее окно для лимита частоты)
_SEEN_FLUSH = {}  # agent id -> время последней записи last_seen на диск


# ---------------------------------------------------------------- реестр

def _load():
    try:
        with open(REG_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("agents", [])
    return data


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = REG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REG_FILE)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _public(a):
    return {k: a.get(k) for k in ("id", "name", "level", "created", "expires", "revoked", "last_seen", "calls", "auto_approve", "auto_run")}


def list_agents(q=None):
    from setup import runtime_info
    rt = runtime_info()
    py = rt["python"]
    mcp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    return {"agents": [_public(a) for a in _load()["agents"]], "socket": SOCKET_PATH,
            "socket_ready": os.path.exists(SOCKET_PATH), "levels": list(LEVELS),
            "mcp": {"python": py, "script": mcp}, "rate_per_min": RATE_PER_MIN}


def _snippets(agent_id, name):
    from setup import runtime_info
    py = runtime_info()["python"]
    mcp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    cmd = [py, mcp, "--agent", agent_id]
    quoted = " ".join(json.dumps(c) if " " in c else c for c in cmd)
    return {"claude_code": f"claude mcp add service-admin -- {quoted}",
            "json": json.dumps({"mcpServers": {"service-admin": {"command": cmd[0], "args": cmd[1:]}}}, indent=2, ensure_ascii=False)}


def register(body):
    """POST {name, expires_days?} → создаёт агента и файл секрета. Секрет в ответ НЕ возвращается."""
    name = (body.get("name") or "").strip()
    if not NAME_RE.match(name):
        raise ApiError("Имя агента: 1–40 символов (буквы, цифры, пробел, . _ -)", code="gw.name_invalid")
    level = body.get("level") or "L1"
    if level not in LEVELS:
        raise ApiError("Уровень агента: L1 (чтение), L2 (предлагать изменения) или L3 (ещё и операции CI — всегда с диалогом)", code="gw.level_invalid")
    days = body.get("expires_days")
    if days is not None and (not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365):
        raise ApiError("Срок действия: от 1 до 365 дней", code="gw.expires_invalid")
    with _LOCK:
        data = _load()
        active = [a for a in data["agents"] if not a.get("revoked")]
        if len(active) >= MAX_AGENTS:
            raise ApiError(f"Не более {MAX_AGENTS} активных агентов", HTTPStatus.CONFLICT, code="gw.too_many", max=MAX_AGENTS)
        if any(a["name"].lower() == name.lower() for a in active):
            raise ApiError("Агент с таким именем уже есть", HTTPStatus.CONFLICT, code="gw.name_exists")
        agent_id = "a" + secrets.token_hex(3)
        token = secrets.token_urlsafe(32)
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
        os.chmod(TOKEN_DIR, 0o700)
        fd = os.open(os.path.join(TOKEN_DIR, agent_id + ".token"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        data["agents"].append({"id": agent_id, "name": name, "level": level, "auto_approve": [], "auto_run": False, "created": time.time(), "last_seen": None, "calls": 0,
                               "expires": time.time() + days * 86400 if days else None, "revoked": False, "token_hash": _hash(token)})
        _save(data)
    return {"id": agent_id, "name": name, "token_file": os.path.join(TOKEN_DIR, agent_id + ".token"), **_snippets(agent_id, name)}


def revoke(body):
    """POST {id} — отозвать: секрет перестаёт приниматься, файл секрета удаляется."""
    with _LOCK:
        data = _load()
        a = next((x for x in data["agents"] if x["id"] == body.get("id")), None)
        if not a:
            raise ApiError("Агент не найден", HTTPStatus.NOT_FOUND, code="gw.not_found")
        a["revoked"] = True
        a["revoked_at"] = time.time()
        a["token_hash"] = None
        _save(data)
    try:
        os.unlink(os.path.join(TOKEN_DIR, a["id"] + ".token"))
    except OSError:
        pass
    audit.record("gateway:revoke", {"id": a["id"], "name": a["name"]}, "ok")
    return {"revoked": a["id"]}


def rotate(body):
    """POST {id} — заменить секрет агента: новый токен пишется в тот же файл (0600), старый перестаёт приниматься."""
    with _LOCK:
        data = _load()
        a = next((x for x in data["agents"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not a:
            raise ApiError("Агент не найден", HTTPStatus.NOT_FOUND, code="gw.not_found")
        token = secrets.token_urlsafe(32)
        path = os.path.join(TOKEN_DIR, a["id"] + ".token")
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
        tmp = path + ".new"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token + "\n")
        os.replace(tmp, path)
        a["token_hash"] = _hash(token)
        a["rotated_at"] = time.time()
        _save(data)
    audit.record("gateway:rotate", {"id": a["id"], "name": a["name"]}, "ok")
    return {"rotated": a["id"]}


def set_agent(body):
    """POST {id, level?, auto_approve?} — уровень агента и «не спрашивать» задаёт ЧЕЛОВЕК; всё пишется в аудит."""
    with _LOCK:
        data = _load()
        a = next((x for x in data["agents"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not a:
            raise ApiError("Агент не найден", HTTPStatus.NOT_FOUND, code="gw.not_found")
        before = {"level": a["level"], "auto_approve": a.get("auto_approve") or [], "auto_run": bool(a.get("auto_run"))}
        if "level" in body:
            if body["level"] not in LEVELS:
                raise ApiError("Уровень агента: L1 (чтение), L2 (предлагать изменения) или L3 (ещё и операции CI — всегда с диалогом)", code="gw.level_invalid")
            a["level"] = body["level"]
        if "auto_approve" in body:
            aa = body["auto_approve"]
            if not isinstance(aa, list) or any(x != "L2" for x in aa):
                raise ApiError("«Не спрашивать» можно включить только для уровня L2", code="gw.auto_invalid")
            a["auto_approve"] = sorted(set(aa))
        if "auto_run" in body:
            if not isinstance(body["auto_run"], bool):
                raise ApiError("auto_run: true или false", code="gw.auto_invalid")
            a["auto_run"] = body["auto_run"]
        if a["level"] in ("L1", "L3"):
            a["auto_approve"] = []  # L1: нечего одобрять; L3: «не спрашивать» запрещено — подтверждение человеком обязательно всегда
        if a["level"] == "L1":
            a["auto_run"] = False   # L1 запускать ничего не может
        _save(data)
        after = {"level": a["level"], "auto_approve": a["auto_approve"], "auto_run": bool(a.get("auto_run"))}
    audit.record("gateway:settings", {"id": a["id"], "name": a["name"], "before": before, "after": after}, "ok")
    return {"agent": _public(a)}


def authenticate(token):
    """Секрет → запись агента или None. Сравнение хешей за постоянное время."""
    if not isinstance(token, str) or not token or len(token) > TOKEN_MAX:
        return None
    h = _hash(token)
    now = time.time()
    with _LOCK:
        for a in _load()["agents"]:
            if a.get("revoked") or not a.get("token_hash"):
                continue
            if hmac.compare_digest(a["token_hash"], h):
                if a.get("expires") and a["expires"] < now:
                    return None
                return a
    return None


def _touch(agent):
    """last_seen/calls на диск — не чаще раза в 10 с на агента (не пишем реестр на каждый вызов)."""
    now = time.time()
    with _LOCK:
        data = _load()
        a = next((x for x in data["agents"] if x["id"] == agent["id"]), None)
        if not a:
            return
        a["calls"] = (a.get("calls") or 0) + 1
        a["last_seen"] = now
        if now - _SEEN_FLUSH.get(a["id"], 0) > 10:
            _save(data)
            _SEEN_FLUSH[a["id"]] = now


def _rate_ok(agent_id):
    now = time.time()
    with _LOCK:
        window = [t for t in _CALLS.get(agent_id, []) if now - t < 60]
        if len(window) >= RATE_PER_MIN:
            _CALLS[agent_id] = window
            return False
        window.append(now)
        _CALLS[agent_id] = window
    return True


# ---------------------------------------------------------------- инструменты (только чтение, текст для агента — по-английски)

def _gb(n):
    return round(n / 1e9, 1)


def t_inspect_system(p, agent=None):
    import setup
    from core import run
    import platform_info
    disk = shutil.disk_usage("/")
    if platform_info.is_macos():
        mem = run(["/usr/sbin/sysctl", "-n", "hw.memsize"], timeout=5)[1].strip()
        osinfo = {"macos": run(["/usr/bin/sw_vers", "-productVersion"], timeout=5)[1].strip()}
    else:  # Linux: данные из /proc и os-release
        with open("/proc/meminfo", encoding="utf-8") as f:
            kb = next((ln.split()[1] for ln in f if ln.startswith("MemTotal:")), "0")
        mem = str(int(kb) * 1024) if kb.isdigit() else ""
        osinfo = {"os": platform_info.info()["distro"]["name"]}
    st = setup.status()
    return {**osinfo, "arch": platform.machine(),
            "cpu_count": os.cpu_count(), "memory_gb": _gb(int(mem)) if mem.isdigit() else None,
            "disk": {"free_gb": _gb(disk.free), "total_gb": _gb(disk.total)},
            "panel": {"python": st["runtime"]["version"], "bundled_python": st["runtime"]["bundled"]},
            "prerequisites": {i["id"]: {"installed": i["installed"], "version": i.get("version"), "path": i.get("path")} for i in st["items"]},
            "setup_ready": st["ready"], "missing": st["missing"]}


def _can_execute(agent, op_id):
    """Может ли ЭТОТ агент предложить операцию: она в списке агентских, а уровень агента не ниже уровня операции."""
    import operations
    import plans
    if not agent or op_id not in plans.AGENT_OPS or op_id not in operations.OPS:
        return False
    return LEVELS.get(agent["level"], 0) >= LEVELS.get(operations.OPS[op_id]["level"], 99)


def _operations_summary(agent=None):
    import operations
    c = operations.catalog()
    return {"count": c["count"], "by_level": c["by_level"], "available_here": sum(1 for o in c["operations"] if o["available"]),
            "see": "list_operations / describe_operation",
            "executable_by_you": [o["id"] for o in c["operations"] if _can_execute(agent, o["id"])]}


def t_list_capabilities(p, agent=None):
    import profiles
    st = None
    try:
        import setup
        st = setup.status()
    except Exception:  # noqa: BLE001
        pass
    return {"agent": {"id": agent["id"], "name": agent["name"], "level": agent["level"]} if agent else None,
            "tools": [{"name": n, "level": d["level"], "read_only": d["level"] == "L1", "description": d["description"],
                       "available": bool(agent) and LEVELS.get(agent["level"], 0) >= LEVELS.get(d["level"], 9)} for n, d in TOOLS.items()],
            "limits": {"rate_per_minute": RATE_PER_MIN, "max_result_kb": MAX_RESULT_BYTES // 1000},
            "profiles": [pr["id"] for pr in profiles.PROFILES],
            "operations": _operations_summary(agent),
            "machine": {"command_line_tools": bool(st and st["items"][0]["installed"]), "homebrew": bool(st and st["items"][1]["installed"])},
            "can_propose_changes": bool(agent and LEVELS.get(agent["level"], 0) >= 2),
            "note": "Read tools need level L1. Proposing changes (plan_changes) needs level L2, which the user grants in the panel; every "
                    "change is executed only after the user approves it in the system approval dialog (or the approval helper on Linux)."}


def t_inspect_profile(p, agent=None):
    import profiles
    d = profiles.describe({"profile": p["profile"]})
    plan = profiles.plan({"profile": p["profile"], "scope": "all"})
    d["ready"] = all(i["installed"] for i in d["items"] if i["required"])
    d["missing_required"] = [i["id"] for i in d["items"] if i["required"] and not i["installed"]]
    d["plan_preview"] = {"would_install": [e["id"] for e in plan["items"] if e["action"] == "install"],
                         "blocked_by": plan["blocked"], "executable_by_agent": _can_execute(agent, "profile.install"),
                         "how": "plan_changes(operation='profile.install') -> human approval -> execute_plan"}
    return d


def t_list_operations(p, agent=None):
    import operations
    out = []
    for o in operations.catalog()["operations"]:
        if p.get("level") and o["level"] != p["level"]:
            continue
        if p.get("group") and o["group"] != p["group"]:
            continue
        out.append({"id": o["id"], "title": o["title"], "level": o["level"], "group": o["group"], "available": o["available"],
                    "unmet_requirements": [u["id"] for u in o["unmet"]], "summary": o["summary"]})
    import plans
    for o in out:
        o["executable_by_you"] = _can_execute(agent, o["id"])
    return {"operations": out, "count": len(out), "levels": operations.LEVEL_INFO, "agent_operations": [o for o in plans.AGENT_OPS if _can_execute(agent, o)],
            "note": "Only the operations in 'agent_operations' can be proposed by this agent (L2: local changes; L3 adds CI runner operations), and every change needs human "
                    "approval in the panel. All others are described for information only."}


def t_describe_operation(p, agent=None):
    import operations
    d = operations.describe(p["operation"])
    d["executable_by_agent"] = _can_execute(agent, p["operation"])
    return d


def t_inspect_diagnostics(p, agent=None):
    import setup
    from core import run
    issues = []
    st = setup.status()
    for i in st["items"]:
        if not i.get("informational") and not i["installed"]:
            issues.append({"id": f"{i['id']}_missing", "severity": "error", "summary": f"{i['id']} is not installed",
                           "suggestion": "Ask the user to open 'System setup' in the panel."})
    free = shutil.disk_usage("/").free
    if free < 10e9:
        issues.append({"id": "low_disk", "severity": "warning", "summary": f"Only {_gb(free)} GB free on the system disk",
                       "suggestion": "Free disk space before large installs or downloads."})
    try:
        import mobile
        x = mobile.xcode_info()
        if x["installs"] and not (x.get("first_launch") or {}).get("done"):
            issues.append({"id": "xcode_first_launch", "severity": "warning", "summary": "Xcode first launch has not been completed",
                           "suggestion": "Run 'Xcode first launch' in the Mobile page (needs the administrator password)."})
    except Exception:  # noqa: BLE001
        pass
    try:
        import dockerx
        e = dockerx.engine()
        if e["cli"] and not e["running"]:
            issues.append({"id": "docker_engine_down", "severity": "info", "summary": "Docker CLI is installed but the engine is not running",
                           "suggestion": "Start OrbStack or Docker Desktop."})
    except Exception:  # noqa: BLE001
        pass
    if core.has_clt():
        for key in ("user.name", "user.email"):
            code, out, _ = run(["git", "config", "--global", key], timeout=5)
            if code != 0 or not out.strip():
                issues.append({"id": f"git_{key.replace('.', '_')}_unset", "severity": "info", "summary": f"git {key} is not set",
                               "suggestion": "Commits will fail until the git identity is configured."})
    try:
        import backups
        b = backups.status()
        if b["last"] and b["last"]["status"] == "failed":
            issues.append({"id": "backup_failed", "severity": "warning", "summary": "The last backup failed",
                           "suggestion": "Open the Backups page in the panel."})
    except Exception:  # noqa: BLE001
        pass
    return {"issues": issues, "count": len(issues), "healthy": not any(i["severity"] == "error" for i in issues)}


def t_list_vms(p, agent=None):
    import vm
    return vm.overview()


def t_list_ci_sources(p, agent=None):
    """Источники CI (где живут репозитории): без токенов. Нужны, чтобы агент знал id источника и ВМ-основы."""
    import runners
    st = runners.status()
    return {"sources": [{"id": x["id"], "name": x["name"], "provider": x["provider"], "url": x["url"], "scope": x["scope"], "path": x["path"],
                         "auth": x["auth"], "has_token": x["has_token"]} for x in st["sources"]],
            "providers": [{"id": p_["id"], "files_installed": bool(p_["installed"])} for p_ in st["providers"]]}


def t_list_containers(p, agent=None):
    """Контейнеры ЛОКАЛЬНОГО движка Docker (имя, образ, состояние) + активный контекст. Только чтение."""
    import dockerx
    ci = dockerx.context_info()
    if ci["remote"]:
        return {"available": False, "reason": "the active Docker context is remote or unknown", "context": ci["name"]}
    if not dockerx.engine().get("running"):
        return {"available": False, "reason": "the Docker engine is not running", "context": ci["name"]}
    cs = dockerx.json_lines("ps", "-a")
    return {"available": True, "context": ci["name"],
            "containers": [{"name": c["Names"], "id": c["ID"][:12], "image": c["Image"], "state": c["State"], "status": c["Status"]} for c in cs][:200]}


def t_cancel_job(p, agent=None):
    """Остановить задачу, но ТОЛЬКО запущенную собственным планом этого агента."""
    import plans
    jid = p.get("job_id")
    if not isinstance(jid, str) or not jid:
        raise ApiError("job_id is required", HTTPStatus.BAD_REQUEST)
    mine = [x for x in plans._plans() if x["agent_id"] == agent["id"] and x.get("job") == jid and plans._status(x) == "executing"]  # noqa: SLF001
    if not mine:
        audit.record("agent:cancel_job", {"job": jid[:40]}, "denied", 0, extra={"agent": agent["name"], "agent_id": agent["id"]})
        raise ApiError("Only a running job started by one of your own plans can be cancelled", HTTPStatus.FORBIDDEN, code="plan.job_not_yours")
    core.cancel_job({"id": jid})
    audit.record("agent:cancel_job", {"job": jid, "plan": mine[0]["id"]}, "ok", 0, extra={"agent": agent["name"], "agent_id": agent["id"]})
    return {"cancelled": jid, "plan": mine[0]["id"]}


def t_get_job_status(p, agent=None):
    jid = p.get("job_id")
    if jid is None:
        jobs = core.list_jobs()["jobs"][:20]
        return {"jobs": [{"id": j["id"], "label": j["label"], "kind": j["kind"], "done": j["done"], "code": j["code"]} for j in jobs]}
    j = core.get_job(str(jid), 0)
    lines = j["lines"][-200:]
    return {"id": j["id"], "label": j["label"], "kind": j["kind"], "done": j["done"], "code": j["code"],
            "started": j["started"], "output_tail": lines, "output_truncated": len(j["lines"]) > len(lines)}


def t_list_projects(p, agent=None):
    """Проекты панели с их пресетами (какие команды test/build можно запустить через project.run)."""
    import projects
    presets = projects._read_registry_file().get("presets", {})  # noqa: SLF001
    out = []
    for it in projects.list_projects({})["projects"]:
        pre = presets.get(os.path.realpath(it["path"])) or {}
        out.append({"path": it["path"], "name": it["name"], "worktree": it["worktree"],
                    "runnable": [k for k in ("install", "lint", "test", "build") if pre.get(k)],
                    "preset": {k: pre.get(k, "") for k in ("install", "lint", "test", "build", "dev")}})
    return {"projects": out, "count": len(out),
            "note": "project.run accepts only kinds listed in 'runnable'; the user sets the commands on the project page."}


def t_inspect_project_versions(p, agent=None):
    """Какие версии языков просит проект (.nvmrc, package.json, .python-version, go.mod…) и что активно сейчас."""
    import project_versions
    r = project_versions.project_versions({"path": p["path"]})
    return {"path": r["path"], "requirements": r["items"],
            "note": "ok=false: the active version does not satisfy the project; 'formula' is the Homebrew formula to install with "
                    "plan_changes operation package.install. ok=null: cannot tell (e.g. lts/*)."}


def t_list_runtimes(p, agent=None):
    """Установленные языки (версия, источник, путь) и языки, которые можно поставить."""
    import runtimes
    d = runtimes.detect()
    return {"installed": [{k: l.get(k) for k in ("key", "name", "version", "source", "path", "formula")} for l in d["langs"]],
            "installable": [{k: a.get(k) for k in ("key", "name", "formula", "type")} for a in d.get("available", [])]}


def t_list_runs(p, agent=None):
    import runs
    q = {k: p[k] for k in ("project", "kind", "status") if p.get(k)}
    q["limit"] = p.get("limit") or 20
    r = runs.history(q)
    return {"runs": [{k: x.get(k) for k in ("id", "project", "kind", "command", "started", "duration", "code", "status", "job")} for x in r["runs"]],
            "total": r["total"]}


LOG_CHUNK = 50_000
SECRET_TOKENS = re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[ous]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{16,}|"
                           r"sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|npm_[A-Za-z0-9]{30,})")


def t_get_run_log(p, agent=None):
    """Полный лог запуска по частям: offset в байтах, до 50 КБ за вызов (с запасом под JSON), по границе символа UTF-8.
    Похожие на токены строки (GitHub, GitLab, npm, Slack, AWS, sk-…) маскируются."""
    import runs
    rid = p["run_id"]
    if not re.fullmatch(r"r[0-9a-f]{6}", rid):
        raise ApiError("Неверный id запуска", code="run.bad_id")
    path = os.path.join(runs.RUNS_DIR, rid + ".log")
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            start = min(int(p.get("offset") or 0), size)
            f.seek(start)
            chunk = f.read(LOG_CHUNK + 4)
    except OSError:
        raise ApiError("Лог не найден", HTTPStatus.NOT_FOUND, code="run.log_missing") from None
    lead = 0
    while lead < min(3, len(chunk)) and (chunk[lead] & 0xC0) == 0x80:    # offset попал внутрь символа — начинаем со следующего
        lead += 1
    chunk = chunk[lead:]
    if len(chunk) > LOG_CHUNK:
        end = LOG_CHUNK
        while end > 0 and (chunk[end] & 0xC0) == 0x80:                     # не режем символ посередине
            end -= 1
        chunk = chunk[:end]
    begin = start + lead
    text = SECRET_TOKENS.sub("<скрыто>", chunk.decode("utf-8", "replace"))
    return {"run_id": rid, "offset": begin, "next_offset": begin + len(chunk), "size": size, "eof": begin + len(chunk) >= size, "text": text}


def t_list_services(p, agent=None):
    """Установленные сервисы (веб-серверы, БД, кэш, прочие) с состоянием и занятые порты."""
    import navtree
    import ports
    try:
        listening = ports.listening({})
    except Exception:  # noqa: BLE001 — порты необязательны
        listening = {"ports": [], "available": False}
    return {"services": navtree.nav_services({"refresh": "1"})["groups"],
            "ports": [{k: x.get(k) for k in ("port", "addr", "cmd", "label", "local_only")} for x in listening.get("ports", [])]}


def _pid():
    return {"plan_id": {"type": "string", "pattern": "p[0-9a-f]{8}", "description": "Plan id returned by plan_changes"}}


def t_plan_changes(p, agent=None):
    import plans
    return plans.propose(agent, p["operation"], p.get("params") or {})


def t_get_plan(p, agent=None):
    import plans
    return plans.get(agent, p["plan_id"])


def t_execute_plan(p, agent=None):
    import plans
    return plans.execute(agent, p["plan_id"])


def t_cancel_plan(p, agent=None):
    import plans
    return plans.cancel(agent, p["plan_id"])


def t_verify_plan(p, agent=None):
    import plans
    return plans.verify(agent, p["plan_id"])


def _schema(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


def _profile_ids():
    import profiles
    return [p["id"] for p in profiles.PROFILES]


def _agent_ops():
    import plans
    return list(plans.AGENT_OPS)


_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False}

TOOLS = {
    "inspect_system": {"level": "L1", "fn": t_inspect_system, "schema": lambda: _schema({}),
                       "description": "Describe this computer: OS version (macOS or Linux), architecture, CPU/RAM, free disk, and whether the prerequisites "
                                      "(git, bundled Python; on macOS also Command Line Tools and Homebrew) are installed. Read-only."},
    "list_capabilities": {"level": "L1", "fn": t_list_capabilities, "schema": lambda: _schema({}),
                          "description": "List the tools available to this agent, their permission level, rate limits and the install profiles "
                                         "this machine supports. Read-only."},
    "inspect_profile": {"level": "L1", "fn": t_inspect_profile,
                        "schema": lambda: _schema({"profile": {"type": "string", "enum": _profile_ids(), "description": "Install profile id"}}, ["profile"]),
                        "description": "Show which tools of an install profile (base, ai, flutter, ios, backend) are installed, their versions, "
                                       "and what installing the missing ones would involve. Read-only; it does not install anything."},
    "inspect_diagnostics": {"level": "L1", "fn": t_inspect_diagnostics, "schema": lambda: _schema({}),
                            "description": "Collect known problems on this machine (missing prerequisites, low disk, Xcode not initialised, Docker "
                                           "engine down, git identity unset, failed backup) with a suggested next step for each. Read-only."},
    "list_operations": {"level": "L1", "fn": t_list_operations,
                        "schema": lambda: _schema({"level": {"type": "string", "enum": ["L1", "L2", "L3", "L4"]}, "group": {"type": "string", "maxLength": 30}}),
                        "description": "List the operations the panel can perform on this machine (installs, git, mobile toolchains, backups …) with "
                                       "their permission level and whether they are available here. Only operations with executable_by_you=true can be proposed with plan_changes; "
                                       "the rest are executed by the user in the panel."},
    "describe_operation": {"level": "L1", "fn": t_describe_operation,
                           "schema": lambda: _schema({"operation": {"type": "string", "pattern": "[a-z0-9_.]{3,40}"}}, ["operation"]),
                           "description": "Describe one operation precisely: parameter schema, permission level (with escalations), requirements and "
                                          "whether they are met, idempotency, how the result is verified and how to roll it back."},
    "plan_changes": {"level": "L2", "fn": t_plan_changes, "annotations": _WRITE,
                     "schema": lambda: _schema({"operation": {"type": "string", "enum": _agent_ops()},
                                                "params": {"type": "object", "additionalProperties": True, "description": "Parameters of the operation (see describe_operation)"}}, ["operation"]),
                     "description": "Propose a change. Nothing is executed: the panel validates the request and returns a plan with an id and an expiry; "
                                    "the user must approve it in the system approval dialog before execute_plan will run it. Only the operations listed in "
                                    "list_operations.agent_operations are allowed. Needs agent level L2."},
    "get_plan": {"level": "L2", "fn": t_get_plan, "schema": lambda: _schema(_pid(), ["plan_id"]),
                 "description": "Get the state of one of your plans: pending, awaiting_human, approved, rejected, expired, executing, done, failed, stale."},
    "execute_plan": {"level": "L2", "fn": t_execute_plan, "annotations": _WRITE, "schema": lambda: _schema(_pid(), ["plan_id"]),
                     "description": "Execute a plan that the user has approved. It runs once and only if the machine still matches what was approved "
                                    "(otherwise the plan is 'stale' and you must plan again). Returns a job id for long operations; poll get_job_status."},
    "cancel_plan": {"level": "L2", "fn": t_cancel_plan, "annotations": _WRITE, "schema": lambda: _schema(_pid(), ["plan_id"]),
                    "description": "Withdraw one of your plans that has not been executed."},
    "verify_plan": {"level": "L2", "fn": t_verify_plan, "schema": lambda: _schema(_pid(), ["plan_id"]),
                    "description": "After an executed plan has finished, check that the operation really achieved its goal (when the operation has an "
                                   "automatic check)."},
    "list_vms": {"level": "L1", "fn": t_list_vms, "schema": lambda: _schema({}),
                 "description": "List virtual machines known to the hypervisor driver (tart): name, state, disk size. Read-only; agents cannot "
                                "create, start, stop or delete VMs."},
    "list_ci_sources": {"level": "L1", "fn": t_list_ci_sources, "schema": lambda: _schema({}),
                        "description": "List the CI sources configured in the panel (provider, server address, scope, whether a token is stored; never the "
                                       "token) and whether the runner files are installed. Use with list_vms to choose arguments for runner.spawn or "
                                       "runner.selftest. Read-only."},
    "list_containers": {"level": "L1", "fn": t_list_containers, "schema": lambda: _schema({}),
                        "description": "List the containers of the LOCAL Docker engine (name, image, state) and the active Docker context. Read-only; "
                                       "unavailable when the context is remote. Use with plan_changes operation docker.container_control (start/stop/restart)."},
    "list_projects": {"level": "L1", "fn": t_list_projects, "schema": lambda: _schema({}),
                      "description": "List the projects known to the panel with their test/build preset commands (what project.run can execute). Read-only."},
    "inspect_project_versions": {"level": "L1", "fn": t_inspect_project_versions,
                                 "schema": lambda: _schema({"path": {"type": "string", "maxLength": 500, "description": "Project path from list_projects"}}, ["path"]),
                                 "description": "Show which language versions a project asks for (.nvmrc, package.json engines, .python-version, pyproject, "
                                                "go.mod, .tool-versions, composer.json…) compared with the active versions, and the Homebrew formula that would fit. "
                                                "Reads project files only; runs nothing."},
    "list_runtimes": {"level": "L1", "fn": t_list_runtimes, "schema": lambda: _schema({}),
                      "description": "List installed language runtimes (version, source, path) and the languages that can be installed. Read-only."},
    "list_runs": {"level": "L1", "fn": t_list_runs,
                  "schema": lambda: _schema({"project": {"type": "string", "maxLength": 500}, "kind": {"type": "string", "enum": ["install", "lint", "test", "build", "dev"]},
                                             "status": {"type": "string", "enum": ["ok", "failed", "timeout", "error"]},
                                             "limit": {"type": "integer", "minimum": 1, "maximum": 100}}),
                  "description": "History of project test/build runs, newest first: command, exit code, status, duration, run id. Read-only."},
    "get_run_log": {"level": "L1", "fn": t_get_run_log,
                    "schema": lambda: _schema({"run_id": {"type": "string", "pattern": "r[0-9a-f]{6}"}, "offset": {"type": "integer", "minimum": 0}}, ["run_id"]),
                    "description": "Read the FULL log of a test/build run in chunks of up to 50 KB (use next_offset until eof); token-like secrets are masked. Read-only."},
    "list_services": {"level": "L1", "fn": t_list_services, "schema": lambda: _schema({}),
                      "description": "List installed services (web servers, databases, cache/queues, others) with running state, and the listening TCP ports. Read-only."},
    "cancel_job": {"level": "L2", "fn": t_cancel_job, "annotations": _WRITE,
                   "schema": lambda: _schema({"job_id": {"type": "string", "description": "Job id returned by execute_plan"}}, ["job_id"]),
                   "description": "Stop a running job that was started by one of YOUR OWN plans (use the job id from execute_plan). Other jobs cannot be cancelled. "
                                  "A job stopped midway may leave partial results (for example a half-installed package)."},
    "get_job_status": {"level": "L1", "fn": t_get_job_status,
                       "schema": lambda: _schema({"job_id": {"type": "string", "description": "Job id; omit to list recent jobs"}}),
                       "description": "Return the status, exit code and the last 200 output lines of a background job started in the panel, "
                                      "or list recent jobs. Read-only."},
}


def tool_descriptors(agent=None):
    """Инструменты, доступные агенту: инструменты более высокого уровня ему не показываются (вызвать их всё равно нельзя)."""
    lvl = LEVELS.get(agent["level"], 0) if agent else 99
    return [{"name": n, "description": d["description"], "inputSchema": d["schema"](),
             "annotations": d.get("annotations", {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})}
            for n, d in TOOLS.items() if LEVELS[d["level"]] <= lvl]


def _validate_legacy(schema, params):
    """Минимальная проверка по схеме: объект, нужные поля, типы string, enum, без лишних полей."""
    if not isinstance(params, dict):
        return "params must be an object"
    props = schema["properties"]
    for k in params:
        if k not in props:
            return f"unknown parameter '{k}'"
    for k in schema["required"]:
        if k not in params:
            return f"missing parameter '{k}'"
    for k, v in params.items():
        spec = props[k]
        if spec.get("type") == "string" and (not isinstance(v, str) or len(v) > 200):
            return f"parameter '{k}' must be a string up to 200 characters"
        if "enum" in spec and v not in spec["enum"]:
            return f"parameter '{k}' must be one of {spec['enum']}"
    return None


# ---------------------------------------------------------------- обработка запроса (его же вызывает сокет)

def _err(code, message, params=None):
    e = {"code": code, "message": message}
    if params:
        e["params"] = params
    return {"ok": False, "error": e}


def handle(req):
    """req = {"token", "op": "list_tools"|"call", "tool"?, "params"?} → {"ok": bool, "result"|"error"}."""
    if not isinstance(req, dict):
        return _err("bad_request", "request must be a JSON object")
    agent = authenticate(req.get("token"))
    if not agent:
        return _err("unauthorized", "unknown, revoked or expired agent credential")
    if not _rate_ok(agent["id"]):
        audit.record("agent:rate_limited", {}, "error: rate limit", 0, extra={"agent": agent["name"], "agent_id": agent["id"]})
        return _err("rate_limited", f"more than {RATE_PER_MIN} calls per minute")
    _touch(agent)
    op = req.get("op")
    if op == "list_tools":
        return {"ok": True, "result": {"tools": tool_descriptors(agent)}}
    if op != "call":
        return _err("bad_request", "op must be 'list_tools' or 'call'")
    name, params = req.get("tool"), req.get("params") or {}
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if not tool:
        return _err("unknown_tool", f"unknown tool '{name}'")
    if LEVELS.get(agent["level"], 0) < LEVELS[tool["level"]]:
        audit.record(f"agent:{name}", params, f"error: forbidden (needs {tool['level']}, agent is {agent['level']})", 0,
                     extra={"agent": agent["name"], "agent_id": agent["id"]})
        return _err("forbidden", f"tool '{name}' needs level {tool['level']}")
    bad = opschema.validate(tool["schema"](), params)
    if bad:
        return _err("invalid_params", bad)
    t0 = time.time()
    audit.INITIATOR.set(f"agent:{agent['name']}")
    try:
        result = tool["fn"](params, agent)
        raw = json.dumps(result, ensure_ascii=False)
        if len(raw) > MAX_RESULT_BYTES:
            raise ValueError("result too large")
        outcome, resp = "ok", {"ok": True, "result": result}
    except ApiError as e:
        # точный код (plan.stale, plan.busy, ops.no_preset…): агент должен различать причины, а не видеть одно «failed»
        outcome, resp = f"error: {e}", _err(e.code or "failed", str(e), getattr(e, "params", None) or None)
    except Exception as e:  # noqa: BLE001
        outcome, resp = f"error: {e}", _err("internal", str(e)[:200])
    audit.record(f"agent:{name}", params, outcome, (time.time() - t0) * 1000, extra={"agent": agent["name"], "agent_id": agent["id"]})
    return resp


# ---------------------------------------------------------------- удалённое подключение (Фаза 8, шаг 1: SSH)
ID_RE = re.compile(r"^a[0-9a-f]{6}$")
PUBKEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com) [A-Za-z0-9+/=]{20,800}(?: [\w.@+-]{1,64})?$")


def _lan_hosts():
    """Имена/адреса, по которым эту машину можно найти. Пакеты не отправляются (UDP connect лишь выбирает маршрут)."""
    out = []
    name = socket.gethostname()
    if name:
        out.append(name)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [h for i, h in enumerate(out) if h and not h.startswith("127.") and h not in out[:i]]


def _ssh_listening():
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=1):
            return True
    except OSError:
        return False


def authorized_line(agent_id, public_key):
    """Строка для ~/.ssh/authorized_keys: ключ может ТОЛЬКО запустить мост MCP этого агента (без оболочки, пробросов портов и сокетов).
    Секрет агента остаётся на этой машине. → строка или ApiError."""
    from setup import runtime_info
    if not ID_RE.match(agent_id or ""):
        raise ApiError("Неверный id агента", code="gw.remote_id")
    key = " ".join((public_key or "").split())
    if not PUBKEY_RE.match(key):
        raise ApiError("Это не похоже на ОДНУ публичную строку ключа SSH (ssh-ed25519 AAAA… комментарий)", code="gw.remote_key")
    py = runtime_info()["python"]
    mcp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    cmd = f"{shlex.quote(py)} {shlex.quote(mcp)} --agent {agent_id}"
    if any(c in cmd for c in '"\\\n\r\0'):   # проверяем ИТОГОВУЮ строку: shlex.quote для пути с «'» даёт '"'"', а кавычка закрыла бы command="…"
        raise ApiError("Путь установки содержит недопустимые символы для authorized_keys", code="gw.remote_path")
    return f'command="{cmd}",restrict {key}'


def remote_info(q=None):
    """GET /api/agent-gateway/remote[?agent=<id>&key=<публичный ключ>] → типы удалённых подключений и готовые команды. Ничего не меняет."""
    import getpass
    q = q or {}
    user = getpass.getuser()
    hosts = _lan_hosts()
    ssh = {"user": user, "hosts": hosts, "listening": _ssh_listening(), "os": "macos" if platform.system() == "Darwin" else "linux"}
    agent_id = q.get("agent") or ""
    if agent_id:
        if not any(a["id"] == agent_id and not a.get("revoked") for a in _load()["agents"]):
            raise ApiError("Агент не найден", HTTPStatus.NOT_FOUND, code="gw.not_found")
        host = hosts[0] if hosts else "<адрес-сервера>"
        keyfile = f"~/.ssh/service-admin-{agent_id}"
        ssh["agent"] = agent_id
        ssh["steps"] = {"keygen": f"ssh-keygen -t ed25519 -N '' -f {keyfile}",
                        "claude": f"claude mcp add service-admin -- ssh -i {keyfile} -o IdentitiesOnly=yes -o BatchMode=yes {user}@{host}",
                        "json": json.dumps({"mcpServers": {"service-admin": {"command": "ssh", "args": ["-i", keyfile.replace("~", "$HOME"), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", f"{user}@{host}"]}}}, indent=2)}
        if q.get("key"):
            ssh["authorized_line"] = authorized_line(agent_id, q["key"])
    return {"types": [{"id": "ssh", "status": "available" if ssh["listening"] else "needs_sshd"},
                      {"id": "api", "status": "available"}, {"id": "telegram", "status": "available"}], "ssh": ssh}   # оба реализованы (ADR-0003), включаются в панели
