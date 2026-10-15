"""Задачи ИИ-агентов (Фаза 2.7): «новая задача» = worktree + агент в PTY, остановка/перезапуск, дифф задачи.

`agents.py` остаётся ТОЛЬКО мониторингом; всё, что запускает/останавливает агента, живёт здесь. Принципы:
  * агент — только из установленных (`agents.known_agents()`), команда — абсолютный путь через shlex.quote,
    БЕЗ флагов вроде «пропустить подтверждения»; описание задачи в агента автоматически НЕ вставляется
    (только отдельным явным действием «отправить в сессию»);
  * worktree создаётся через gitops (только внутрь ~/Worktrees), проект — из реестра;
  * реестр задач — `~/.service-admin/agents.json` (атомарная запись, 0600); PTY-сессии живут в памяти панели,
    поэтому после перезапуска панели задача «остановлена» и её можно перезапустить в том же worktree;
  * статус «занят / простаивает» — ЭВРИСТИКА (вывод в последние секунды / CPU), а не API агента; так и подписано;
  * дифф задачи — worktree относительно коммита, на котором задача началась (`base_sha`), только чтение.
"""
import json
import os
import re
import secrets
import shlex
import threading
import time
from http import HTTPStatus

import agents
import gitops
import projects
import ptyterm
from core import DATA_DIR, JOBS, ApiError, start_steps

TASKS_FILE = os.path.join(DATA_DIR, "agents.json")
TITLE_MAX = 80
DESC_MAX = 4000
SEND_MAX = 4000
BUSY_SECONDS = 3.0   # вывод за последние N секунд = «занят»
DIFF_MAX = 300_000
_LOCK = threading.Lock()


# ---------------------------------------------------------------- реестр

def _load():
    try:
        with open(TASKS_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"tasks": []}
    data.setdefault("tasks", [])
    return data


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = TASKS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TASKS_FILE)


def _update(task_id, **changes):
    with _LOCK:
        data = _load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t.update(changes)
                _save(data)
                return t
    return None


def _find(task_id):
    t = next((t for t in _load()["tasks"] if t["id"] == task_id), None)
    if not t:
        raise ApiError("Задача не найдена", HTTPStatus.NOT_FOUND, code="task.missing")
    return t


def _slug(text, limit=30):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return s or "task"


# ---------------------------------------------------------------- состояние

def _live(task, sessions):
    """Производное состояние задачи (не хранится): creating | failed | stopped | shell | busy | idle."""
    phase = task.get("phase")
    if phase == "creating":
        job = JOBS.get(task.get("job"))
        if job and not job["done"]:
            return {"state": "creating", "session": None}
        return {"state": "failed", "session": None}  # job закончился/пропал, а запуска не было
    if phase == "failed":
        return {"state": "failed", "session": None}
    sid = task.get("session")
    pty = ptyterm.SESSIONS.get(str(sid)) if sid else None
    if not pty or not pty["alive"]:
        return {"state": "stopped", "session": None}
    info = sessions.get(str(sid)) or {}
    if not info.get("agents"):
        return {"state": "shell", "session": sid}  # агент завершился, оболочка осталась
    busy = (time.time() - (pty.get("last") or 0) < BUSY_SECONDS) or info.get("cpu", 0) > 5
    return {"state": "busy" if busy else "idle", "session": sid, "cpu": info.get("cpu", 0), "heuristic": True}


def list_tasks(q=None):
    try:
        sessions = {s["id"]: s for s in agents.sessions_info({"fresh": "1"})["sessions"]}
    except Exception:  # noqa: BLE001 - без ps мониторинг пуст, но список задач нужен
        sessions = {}
    out = []
    for t in sorted(_load()["tasks"], key=lambda x: x.get("created", 0), reverse=True):
        item = {k: t.get(k) for k in ("id", "title", "agent", "project", "branch", "worktree", "created", "restarts", "description", "merged")}
        item["worktree_exists"] = bool(t.get("worktree") and os.path.isdir(t["worktree"]))
        item.update(_live(t, sessions))
        out.append(item)
    return {"tasks": out, "installed": [a["key"] for a in agents.known_agents()],
            "heuristic_note": "busy/idle — эвристика по выводу и CPU, а не статус от агента"}


# ---------------------------------------------------------------- запуск агента в PTY

def _agent_path(key):
    hit = next((a for a in agents.known_agents() if a["key"] == key), None)
    if not hit:
        raise ApiError("Агент не установлен", HTTPStatus.CONFLICT, code="task.no_agent")
    return hit["path"]


def _launch(task):
    """Новая PTY-сессия в worktree задачи; возвращает id сессии. Только список установленных агентов."""
    wt = task.get("worktree")
    if not wt or not os.path.isdir(wt):
        raise RuntimeError("Папка worktree не найдена")
    path = _agent_path(task["agent"])
    r = ptyterm.new_session({"cwd": wt, "command": shlex.quote(path), "cols": 120, "rows": 32})
    return r["id"]


def create(body):
    """POST {project, agent, title, description?, branch?} → job: worktree → запуск агента."""
    project = projects.resolve(body.get("project"))
    agent = body.get("agent")
    _agent_path(agent)  # установлен ли
    title = (body.get("title") or "").strip()
    desc = (body.get("description") or "").strip()
    if not title or len(title) > TITLE_MAX or any(ord(c) < 32 for c in title):
        raise ApiError(f"Название задачи: от 1 до {TITLE_MAX} символов", code="task.title", max=TITLE_MAX)
    if len(desc) > DESC_MAX:
        raise ApiError(f"Описание: не более {DESC_MAX} символов", code="task.desc", max=DESC_MAX)
    task_id = "t" + secrets.token_hex(3)
    branch = body.get("branch") or f"agent/{_slug(title)}-{task_id[1:5]}"
    label, kind, wt_steps = gitops.build("git.worktree_add", {"project": project, "branch": branch}, None)
    worktree = os.path.join(gitops.WORKTREE_ROOT, gitops._slug(os.path.basename(project)), gitops._slug(branch))  # noqa: SLF001
    task = {"id": task_id, "title": title, "description": desc, "agent": agent, "project": project, "branch": branch,
            "worktree": worktree, "created": time.time(), "restarts": 0, "phase": "creating", "session": None, "base_sha": None}

    def record_base(log):
        code, out = projects.git(project, "rev-parse", "HEAD")
        if code != 0:
            raise RuntimeError("Не удалось определить базовый коммит")
        _update(task_id, base_sha=out.strip())
        log(f"База задачи: {out.strip()[:10]}")

    def launch(log):
        sid = _launch(_find(task_id))
        _update(task_id, session=sid, phase="ready")
        log(f"Агент {agent} запущен в сессии #{sid} (вкладка «Терминал»)")

    with _LOCK:
        data = _load()
        data["tasks"].append(task)
        _save(data)
    steps = [("Запись базы", record_base, {})] + wt_steps + [(f"Запуск агента {agent}", launch, {})]
    try:
        job = start_steps(f"Задача: {title}", steps, kind)
    except ApiError:
        with _LOCK:  # job не стартовал (например, занят репозиторий) — не оставляем «висящую» задачу
            data = _load()
            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
            _save(data)
        raise
    _update(task_id, job=job)
    return {"id": task_id, "job": job, "branch": branch, "worktree": worktree}


def start(body):
    """Запустить/перезапустить агента в том же worktree (если сессия не жива)."""
    t = _find(body.get("id"))
    if t.get("phase") != "ready":
        raise ApiError("Задача не готова: worktree не был создан", HTTPStatus.CONFLICT, code="task.no_worktree")
    pty = ptyterm.SESSIONS.get(str(t.get("session")))
    if pty and pty["alive"]:
        raise ApiError("Сессия уже запущена", HTTPStatus.CONFLICT, code="task.session_running")
    try:
        sid = _launch(t)
    except RuntimeError as e:
        raise ApiError(str(e), HTTPStatus.CONFLICT) from None
    _update(t["id"], session=sid, restarts=(t.get("restarts") or 0) + 1)
    return {"id": t["id"], "session": sid}


def stop(body):
    t = _find(body.get("id"))
    pty = ptyterm.SESSIONS.get(str(t.get("session")))
    if not pty:
        raise ApiError("Сессия не запущена", HTTPStatus.CONFLICT, code="task.session_not_running")
    ptyterm.kill({"id": t["session"]})
    return {"id": t["id"], "stopped": True}


def send(body):
    """Явное действие пользователя: отправить текст в сессию агента (как ввод с клавиатуры) + Enter."""
    t = _find(body.get("id"))
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > SEND_MAX:
        raise ApiError(f"Текст: от 1 до {SEND_MAX} символов", code="task.text_len", max=SEND_MAX)
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise ApiError("Управляющие символы в тексте не допускаются", code="task.ctrl_chars")
    pty = ptyterm.SESSIONS.get(str(t.get("session")))
    if not pty or not pty["alive"]:
        raise ApiError("Сессия не запущена", HTTPStatus.CONFLICT, code="task.session_not_running")
    ptyterm.write({"id": t["session"], "data": text + "\r"})
    return {"sent": len(text)}


def remove(body):
    """Убрать задачу из реестра; remove_worktree=true — ещё `git worktree remove` (без --force) job-ом."""
    t = _find(body.get("id"))
    pty = ptyterm.SESSIONS.get(str(t.get("session")))
    if pty and pty["alive"]:
        raise ApiError("Сначала остановите сессию агента", HTTPStatus.CONFLICT, code="task.stop_first")

    def drop():
        with _LOCK:
            data = _load()
            data["tasks"] = [x for x in data["tasks"] if x["id"] != t["id"]]
            _save(data)

    if body.get("remove_worktree") and t.get("worktree") and os.path.isdir(t["worktree"]):
        label, kind, steps = gitops.build("git.worktree_remove", {"project": t["project"], "worktree": t["worktree"]}, None)
        steps.append(("Реестр задач", lambda log: drop(), {}))
        return {"job": start_steps(f"Удалить задачу: {t['title']}", steps, kind)}
    drop()
    return {"removed": t["id"]}


# ---------------------------------------------------------------- изменения задачи (только чтение)

def _need_worktree(t):
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt) or not t.get("base_sha"):
        raise ApiError("Worktree задачи недоступен", HTTPStatus.CONFLICT, code="task.wt_unavailable")
    return wt, t["base_sha"]


def changes(q):
    """Что изменил агент относительно базы задачи: файлы (vs base), неотслеженные, коммиты."""
    t = _find(q.get("id"))
    wt, base = _need_worktree(t)
    code, out = projects.git(wt, "diff", "--name-status", "--no-renames", base, timeout=20)
    files = []
    for line in (out.splitlines() if code == 0 else []):
        parts = line.split("\t", 1)
        if len(parts) == 2:
            files.append({"status": parts[0], "path": parts[1]})
    untracked = [ln for ln in projects.git(wt, "ls-files", "--others", "--exclude-standard")[1].splitlines() if ln][:200]
    commits = [ln for ln in projects.git(wt, "log", "--format=%h %s", f"{base}..HEAD")[1].splitlines() if ln][:50]
    target = gitops._current(t["project"])  # noqa: SLF001
    # Предсказание конфликта БЕЗ изменения чего-либо: `git merge-tree --write-tree` (git >= 2.38) только пишет объекты.
    conflicts = None
    if target:
        code, out = projects.git(t["project"], "merge-tree", "--write-tree", target, t["branch"], timeout=30)
        conflicts = True if code == 1 else (False if code == 0 else None)
    return {"id": t["id"], "branch": t["branch"], "base": base[:10], "files": files, "untracked": untracked, "commits": commits,
            "target": target, "conflicts": conflicts, "merged": bool(t.get("merged"))}


def diff(q):
    """Унифицированный дифф одного файла относительно базы задачи (с лимитом размера)."""
    t = _find(q.get("id"))
    wt, base = _need_worktree(t)
    ch = changes({"id": t["id"]})
    path = q.get("file")
    if path not in {f["path"] for f in ch["files"]}:
        raise ApiError("Файл не входит в изменения задачи", HTTPStatus.NOT_FOUND, code="task.file_not_in_diff")
    code, out = projects.git(wt, "diff", "--no-renames", base, "--", path, timeout=30)
    if code != 0:
        raise ApiError("Не удалось получить дифф", HTTPStatus.CONFLICT, code="task.diff_failed")
    return {"file": path, "diff": out[:DIFF_MAX], "truncated": len(out) > DIFF_MAX}


# ---------------------------------------------------------------- слияние ветки задачи (локально, без push)

def merge(body):
    """POST {id} → job: `git merge --no-ff` ветки задачи в ТЕКУЩУЮ ветку основного checkout.

    Условия (иначе отказ): задача готова, сессия агента остановлена, worktree задачи без незакоммиченных изменений,
    основной checkout чист и стоит на именованной ветке, у ветки задачи есть новые коммиты. Конфликт → сразу
    `git merge --abort` (основной checkout остаётся как был), job завершается ошибкой. Push не делается.
    """
    t = _find(body.get("id"))
    if t.get("phase") != "ready":
        raise ApiError("Задача не готова", HTTPStatus.CONFLICT, code="task.not_ready")
    pty = ptyterm.SESSIONS.get(str(t.get("session")))
    if pty and pty["alive"]:
        raise ApiError("Сначала остановите сессию агента", HTTPStatus.CONFLICT, code="task.stop_first")
    wt, base = _need_worktree(t)
    if gitops.files_state(wt):
        raise ApiError("В worktree задачи есть незакоммиченные изменения — закоммитьте или откатите их", HTTPStatus.CONFLICT,
                       code="task.worktree_dirty")
    project = projects.resolve(t["project"])
    target = gitops._current(project)  # noqa: SLF001
    if not target:
        raise ApiError("Основной checkout в состоянии detached HEAD", HTTPStatus.CONFLICT, code="task.detached")
    if gitops.files_state(project):
        raise ApiError("В основном checkout есть незакоммиченные изменения — слияние отклонено", HTTPStatus.CONFLICT,
                       code="task.main_dirty")
    n = len([ln for ln in projects.git(project, "log", "--format=%h", f"{target}..{t['branch']}")[1].splitlines() if ln])
    if n == 0:
        raise ApiError("В ветке задачи нет новых коммитов для слияния", HTTPStatus.CONFLICT, code="task.nothing_to_merge")
    title = "".join(c for c in t["title"] if ord(c) >= 32)[:80]
    msg = f"Merge branch '{t['branch']}' (agent task: {title})"

    def do_merge(log):
        import subprocess
        def git_run(*args):
            return subprocess.run([projects.GIT, *args], cwd=project, env=gitops.WRITE_ENV, capture_output=True, text=True)
        r = git_run("merge", "--no-ff", "-m", msg, t["branch"])
        for line in (r.stdout + r.stderr).splitlines():
            log(line)
        if r.returncode != 0:
            ab = git_run("merge", "--abort")
            log("Слияние отменено (merge --abort): основной checkout не изменён." if ab.returncode == 0
                else "⚠️ merge --abort не удался — проверьте состояние репозитория вручную.")
            raise RuntimeError("конфликт слияния" if "CONFLICT" in (r.stdout + r.stderr) else "git merge завершился с ошибкой")
        _update(t["id"], merged=True, merged_at=time.time())
        log(f"Ветка {t['branch']} слита в {target} ({n} коммит.). Push не выполнялся.")

    kind = "git:" + __import__("hashlib").sha1(project.encode()).hexdigest()[:10]
    return {"job": start_steps(f"{os.path.basename(project)}: merge {t['branch']} → {target}", [("git merge --no-ff", do_merge, {})], kind),
            "target": target, "commits": n}
