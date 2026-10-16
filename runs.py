"""Автоматизация проекта (Фаза 2.8): кнопки test/build из пресета, история запусков, запуск GitHub Actions.

Принципы:
  * запускается ТОЛЬКО команда из пресета проекта (2.3), прошедшая `projects.runnable_argv` (список разрешённых
    инструментов + ./скрипты проекта) — и при сохранении, и здесь, при запуске; произвольной команды из формы нет;
  * запуск — список аргументов без shell, cwd = проект, свой process group, жёсткий таймаут (по истечении
    убивается вся группа), вывод в лог job и в файл истории;
  * история — `~/.service-admin/runs.jsonl` + `runs/<id>.log` (0600), хранится не более MAX_RUNS последних;
  * GitHub Actions: workflow и ветка проверяются по `gh workflow list` / `git branch`; запуск — действие во
    внешней системе, поэтому серверно требует ввести имя проекта (как откат изменений в gitops).
"""
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import threading
import time
from http import HTTPStatus

import gitops
import projects
from core import DATA_DIR, ENV, ApiError, StepFailed, project_env, start_steps

RUNS_DIR = os.path.join(DATA_DIR, "runs")
INDEX = os.path.join(DATA_DIR, "runs.jsonl")
KINDS = ("install", "lint", "test", "build")   # конечные запуски (лимит RUN_TIMEOUT)
DEV = "dev"                                   # dev-сервер: без лимита, до остановки
RUN_TIMEOUT = 30 * 60
MAX_RUNS = 300
LOG_MAX = 5 * 1024 * 1024
LOG_READ_MAX = 300_000
_LOCK = threading.Lock()


# ---------------------------------------------------------------- история

def _record(entry):
    with _LOCK:
        os.makedirs(RUNS_DIR, mode=0o700, exist_ok=True)
        fd = os.open(INDEX, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _prune()


def _all():
    try:
        with open(INDEX, encoding="utf-8") as f:
            rows = []
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows
    except OSError:
        return []


def _prune():
    rows = _all()
    if len(rows) <= MAX_RUNS:
        return
    keep, drop = rows[-MAX_RUNS:], rows[:-MAX_RUNS]
    for r in drop:
        try:
            os.unlink(os.path.join(RUNS_DIR, r["id"] + ".log"))
        except OSError:
            pass
    tmp = INDEX + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in keep:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, INDEX)


def history(q=None):
    """GET /api/runs?project=&kind=&status=&limit= — новые первыми."""
    q = q or {}
    rows = _all()
    if q.get("project"):
        real = projects._canon(os.path.realpath(q["project"]))  # noqa: SLF001
        rows = [r for r in rows if r.get("project") == real]
    if q.get("kind") in KINDS + (DEV,):
        rows = [r for r in rows if r.get("kind") == q["kind"]]
    if q.get("status") in ("ok", "failed", "timeout", "error", "stopped"):
        rows = [r for r in rows if r.get("status") == q["status"]]
    try:
        limit = max(1, min(int(q.get("limit") or 50), 300))
    except ValueError:
        limit = 50
    return {"runs": rows[::-1][:limit], "total": len(rows)}


def run_log(q):
    rid = q.get("id") or ""
    if not (len(rid) == 7 and rid[0] == "r" and all(c in "0123456789abcdef" for c in rid[1:])):
        raise ApiError("Неверный id запуска", code="run.bad_id")
    try:
        with open(os.path.join(RUNS_DIR, rid + ".log"), "rb") as f:
            data = f.read()
    except OSError:
        raise ApiError("Лог не найден", HTTPStatus.NOT_FOUND, code="run.log_missing") from None
    text = data[-LOG_READ_MAX:].decode("utf-8", "replace")
    return {"id": rid, "log": text, "truncated": len(data) > LOG_READ_MAX}


# ---------------------------------------------------------------- запуск test/build

def _runner(run_id, project, kind, command, argv, job_ref, timeout=RUN_TIMEOUT):
    def step(log):
        t0 = time.time()
        os.makedirs(RUNS_DIR, mode=0o700, exist_ok=True)
        status, code, written = "error", None, 0
        logf = os.open(os.path.join(RUNS_DIR, run_id + ".log"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            env = project_env()           # интерактивная оболочка — до 20 с; отмену в это время проверяем ниже
            if getattr(log, "cancelled", lambda: False)():
                status = "stopped"
                raise StepFailed(143)
            proc = subprocess.Popen(argv, cwd=project, env=env, text=True, bufsize=1, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            if hasattr(log, "attach"):
                log.attach(proc)          # «Остановить» и отмена плана агентом убивают группу процессов теста
            if kind == DEV:
                _dev_pidfile(project, proc.pid, argv[0])   # переживает перезапуск панели: сервер можно найти и остановить
            timed_out = {"v": False}

            def watchdog():
                if proc.poll() is None:
                    timed_out["v"] = True
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            timer = threading.Timer(timeout, watchdog) if timeout else None
            if timer:
                timer.start()
            try:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    log(line)
                    if written < LOG_MAX:
                        chunk = (line + "\n").encode()
                        written += os.write(logf, chunk)
                code = proc.wait()
            finally:
                if timer:
                    timer.cancel()
            stopped = getattr(log, "cancelled", lambda: False)()
            status = "timeout" if timed_out["v"] else ("ok" if code == 0 else "stopped" if stopped else "failed")
            if timed_out["v"]:
                log(f"⏱ Превышен лимит {timeout // 60} мин — процесс остановлен.")
        except StepFailed:
            pass
        except Exception as e:  # noqa: BLE001
            log(f"ERROR: {e}")
            os.write(logf, f"ERROR: {e}\n".encode())
        finally:
            os.close(logf)
            if kind == DEV:
                _dev_pidfile(project, None)
            _record({"id": run_id, "project": project, "name": os.path.basename(project), "kind": kind,
                     "command": command, "started": t0, "duration": round(time.time() - t0, 1), "code": code,
                     "status": status, "job": job_ref.get("job")})
        if status != "ok":
            # настоящий код выхода (тест упал = 1, таймаут = 124, остановлен = 143, не запустилось = 127), а не обобщённый -1
            rc = 124 if status == "timeout" else 143 if status == "stopped" else (code if code not in (None, 0) else 127)
            log(f"{kind}: {status} (exit {rc})")
            raise StepFailed(rc)
    return step


def _dev_key(project):
    return hashlib.sha1(project.encode()).hexdigest()[:10]


def _dev_pidfile(project, pid, exe=None):
    """Файл runs/dev-<ключ>.json: pid группы dev-сервера и его команда. None — удалить (сервер завершился)."""
    path = os.path.join(RUNS_DIR, f"dev-{_dev_key(project)}.json")
    if pid is None:
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"pid": pid, "exe": os.path.basename(exe or ""), "started": time.time()}, f)


def _dev_orphan(project):
    """dev-сервер, запущенный до перезапуска панели: pid из файла, если процесс жив и это та же команда (защита от чужого pid)."""
    try:
        with open(os.path.join(RUNS_DIR, f"dev-{_dev_key(project)}.json")) as f:
            d = json.load(f)
        pid = int(d["pid"])
        os.kill(pid, 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    return pid if d.get("exe") and d["exe"] in out else None


def dev_status(q):
    """GET /api/runs/dev?project= → запущен ли dev-сервер проекта (job, либо «осиротевший» процесс после перезапуска панели)."""
    from core import JOBS
    project = projects.resolve(q.get("project"))
    kind = "dev:" + _dev_key(project)
    job = next((j for j in sorted(JOBS.values(), key=lambda j: -j["started"]) if j["kind"] == kind and not j["done"]), None)
    if job:
        return {"running": True, "job": job["id"]}
    pid = _dev_orphan(project)
    return {"running": bool(pid), "job": None, "orphan": bool(pid)}


def dev_stop(body):
    """POST /api/runs/dev-stop {project}: остановить dev-сервер проекта — задачу панели или процесс, оставшийся после перезапуска."""
    from core import cancel_job
    project = projects.resolve(body.get("project"))
    st = dev_status({"project": project})
    if st["job"]:
        return cancel_job({"id": st["job"]})
    pid = _dev_orphan(project)
    if not pid:
        return {"ok": True, "note": "not running"}
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    _dev_pidfile(project, None)
    return {"ok": True}


def start(body):
    """POST /api/runs/start {project, kind: test|build} → job. Команда — только из пресета проекта."""
    project = projects.resolve(body.get("project"))
    kind = body.get("kind")
    if kind not in KINDS and kind != DEV:
        raise ApiError("Тип запуска: install | lint | test | build | dev", code="run.bad_kind")
    command = projects.presets_get(project).get(kind) or ""
    if not command:
        raise ApiError(f"В пресете проекта не задана команда {kind}", HTTPStatus.CONFLICT, code="run.no_cmd", kind=kind)
    argv = projects.runnable_argv(project, command)  # повторная проверка: файл пресетов могли подправить руками
    run_id = "r" + secrets.token_hex(3)
    job_ref = {}
    label = f"{os.path.basename(project)}: {kind} ({command})"
    key = hashlib.sha1(project.encode()).hexdigest()[:10]
    # dev-сервер живёт отдельно от test/build (тесты можно гонять при запущенном сервере) и без лимита времени
    job = start_steps(label, [(command, _runner(run_id, project, kind, command, argv, job_ref, None if kind == DEV else RUN_TIMEOUT), {})],
                      ("dev:" if kind == DEV else "run:") + key)
    job_ref["job"] = job
    return {"job": job, "run": run_id, "label": label}


# ---------------------------------------------------------------- GitHub Actions

def _github(path):
    if not projects.GH:
        raise ApiError("GitHub CLI (gh) не установлен — поставьте его в профиле «Фундамент»", HTTPStatus.CONFLICT, code="run.no_gh")
    _, remote = projects._remote(path)  # noqa: SLF001
    if not remote or "github.com" not in remote:
        raise ApiError("Remote проекта — не GitHub", HTTPStatus.CONFLICT, code="run.not_github")
    return remote


GH_ENV = dict(ENV, GH_PROMPT_DISABLED="1", NO_COLOR="1", GH_NO_UPDATE_NOTIFIER="1")


def _workflow_list(path):
    from core import run
    code, out, err = run([projects.GH, "workflow", "list", "--json", "id,name,path,state"], timeout=30, cwd=path, env=GH_ENV)
    if code != 0:
        raise ApiError("gh не смог получить список workflow: " + (err.strip().splitlines() or ["ошибка"])[-1], HTTPStatus.CONFLICT, code="run.gh_list", detail=(err.strip().splitlines() or ["ошибка"])[-1])
    try:
        return json.loads(out or "[]")
    except ValueError:
        raise ApiError("Неожиданный ответ gh", HTTPStatus.INTERNAL_SERVER_ERROR, code="run.gh_bad_reply") from None


def workflows(q):
    """GET /api/gh/workflows?project= — workflow репозитория + ветки, на которых их можно запустить."""
    path = projects.resolve(q.get("project"))
    remote = _github(path)
    wf = [w for w in _workflow_list(path) if w.get("state") == "active"]
    refs = gitops._branches(path)  # noqa: SLF001
    cur = gitops._current(path)  # noqa: SLF001
    return {"remote": remote, "workflows": wf, "branches": refs, "current": cur}


INPUT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,40}$")
MAX_INPUTS = 10


def _inputs(raw):
    """Параметры workflow_dispatch: {имя: строка}. Значения передаются отдельными аргументами `-f k=v` (без shell)."""
    if raw in (None, "", {}):
        return {}
    if not isinstance(raw, dict) or len(raw) > MAX_INPUTS:
        raise ApiError("Параметры workflow: не более 10 пар имя=значение", code="run.bad_input")
    out = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not INPUT_KEY_RE.match(k) or not isinstance(v, (str, int, float, bool)):
            raise ApiError("Неверное имя или значение параметра workflow", code="run.bad_input")
        v = str(v) if not isinstance(v, bool) else ("true" if v else "false")
        if len(v) > 200 or "\n" in v or "\r" in v or "\0" in v:
            raise ApiError("Значение параметра: до 200 символов, одна строка", code="run.bad_input")
        out[k] = v
    return out


def _recent_runs(path, limit=10):
    from core import run
    code, out, err = run([projects.GH, "run", "list", "--limit", str(limit), "--json",
                          "databaseId,displayTitle,status,conclusion,workflowName,headBranch,createdAt"], timeout=30, cwd=path, env=GH_ENV)
    if code != 0:
        d = (err.strip().splitlines() or ["ошибка"])[-1]
        raise ApiError("gh не смог получить запуски: " + d, HTTPStatus.CONFLICT, code="run.gh_list", detail=d)
    try:
        items = json.loads(out or "[]")
    except ValueError:
        raise ApiError("Неожиданный ответ gh", HTTPStatus.INTERNAL_SERVER_ERROR, code="run.gh_bad_reply") from None
    return [x for x in items if isinstance(x, dict)]


def gh_runs(q):
    """GET /api/gh/runs?project= — последние запуски Actions (для отмены/повтора)."""
    path = projects.resolve(q.get("project"))
    _github(path)
    return {"runs": _recent_runs(path)}


def _run_target(body, what):
    path = projects.resolve(body.get("project"))
    _github(path)
    rid = body.get("run_id")
    rid = str(rid) if isinstance(rid, (int, str)) and not isinstance(rid, bool) else ""
    if not re.fullmatch(r"\d{1,20}", rid):
        raise ApiError("Неверный номер запуска", code="run.bad_run_id")
    run_item = next((r for r in _recent_runs(path, 30) if str(r.get("databaseId")) == rid), None)
    if not run_item:
        raise ApiError("Запуск не найден среди последних", HTTPStatus.NOT_FOUND, code="run.run_missing")
    gitops._typed_confirm(body, path, what)  # noqa: SLF001
    return path, rid, run_item


def run_cancel(body):
    """POST /api/gh/run_cancel {project, run_id, confirm} → job (`gh run cancel`). Только идущий запуск."""
    path, rid, item = _run_target(body, "Отмена запуска GitHub Actions")
    if item.get("status") == "completed":
        raise ApiError("Запуск уже завершён", HTTPStatus.CONFLICT, code="run.already_done")
    steps = [(f"gh run cancel {rid}", [projects.GH, "run", "cancel", rid], {"cwd": path, "env": GH_ENV})]
    return {"job": start_steps(f"{os.path.basename(path)}: отмена запуска {rid}", steps, "gh:" + hashlib.sha1(path.encode()).hexdigest()[:10])}


def run_rerun(body):
    """POST /api/gh/run_rerun {project, run_id, failed_only?, confirm} → job (`gh run rerun [--failed]`). Только завершённый запуск."""
    path, rid, item = _run_target(body, "Повтор запуска GitHub Actions")
    if item.get("status") != "completed":
        raise ApiError("Запуск ещё идёт — дождитесь завершения или отмените", HTTPStatus.CONFLICT, code="run.not_done")
    argv = [projects.GH, "run", "rerun", rid] + (["--failed"] if body.get("failed_only") is True else [])
    steps = [(" ".join(argv[1:]), argv, {"cwd": path, "env": GH_ENV})]
    return {"job": start_steps(f"{os.path.basename(path)}: повтор запуска {rid}", steps, "gh:" + hashlib.sha1(path.encode()).hexdigest()[:10])}


def workflow_run(body):
    """POST /api/gh/workflow_run {project, workflow: id, ref?, confirm} → job (`gh workflow run`)."""
    path = projects.resolve(body.get("project"))
    _github(path)
    wf_id = str(body.get("workflow") or "")
    wf = next((w for w in _workflow_list(path) if str(w.get("id")) == wf_id and w.get("state") == "active"), None)
    if not wf:
        raise ApiError("Workflow не найден среди активных", HTTPStatus.NOT_FOUND, code="run.wf_missing")
    ref = body.get("ref") or gitops._current(path)  # noqa: SLF001
    if ref not in gitops._branches(path):  # noqa: SLF001
        raise ApiError("Ветка не найдена локально", HTTPStatus.NOT_FOUND, code="run.branch_local")
    inputs = _inputs(body.get("inputs"))
    gitops._typed_confirm(body, path, "Запуск GitHub Actions")  # noqa: SLF001 - действие во внешней системе
    argv = [projects.GH, "workflow", "run", wf_id, "--ref", ref]
    for k, v in inputs.items():
        argv += ["-f", f"{k}={v}"]
    steps = [(f"gh workflow run {wf['name']} --ref {ref}" + "".join(f" -f {k}=…" for k in inputs), argv, {"cwd": path, "env": GH_ENV})]
    kind = "gh:" + hashlib.sha1(path.encode()).hexdigest()[:10]
    return {"job": start_steps(f"{os.path.basename(path)}: Actions {wf['name']} @ {ref}", steps, kind)}
