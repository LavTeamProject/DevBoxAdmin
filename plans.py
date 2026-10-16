"""Планы и подтверждения для ИИ-агентов (Фазы 4.2 + 4.4): `plan_changes → одобрение человеком → execute_plan → verify`.

Что гарантируется:
  * агент ПРЕДЛАГАЕТ операцию (`propose`) — ничего не меняется; план получает `plan_id`, хеш плана и срок жизни (15 минут);
  * исполнить можно ТОЛЬКО одобренный план, один раз, и ровно то, что одобрено: перед исполнением план пересобирается
    заново, и если хеш не совпал (состояние машины или проект изменились) — отказ `plan_stale`, нужен новый план;
  * одобрение — решение человека. По умолчанию это СИСТЕМНЫЙ диалог macOS (имя агента, операция, параметры; кнопка по
    умолчанию — «Отклонить», таймаут = отказ): агент с терминалом может сам вызвать HTTP-эндпоинт панели, но нажать
    системный диалог без прав доступности не может. Режим «кнопка в панели» слабее и включается явно (запись в аудит);
  * агентам доступен ТОЛЬКО короткий список операций (`AGENT_OPS`): безопасные L2 и, для агентов уровня L3, операции CI-раннеров
    (`AGENT_OPS_L3`) — для них подтверждение человеком в системном диалоге ОБЯЗАТЕЛЬНО, «не спрашивать» невозможно; L4 агентам не открыты;
  * ограничения: не более 5 ожидающих планов и 10 исполнений в час на агента; уровень агента (L1/L2) задаёт человек;
    «не спрашивать» (`auto_approve`) — только явной настройкой для агента и уровня, с записью в аудит;
  * весь жизненный цикл — в журнале аудита с идентичностью агента.
"""
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
from http import HTTPStatus

import approval
import audit
import operations
import core
from core import DATA_DIR, JOBS, ApiError

PLANS_FILE = os.path.join(DATA_DIR, "plans.json")
POLICY_FILE = os.path.join(DATA_DIR, "agent-policy.json")
OSASCRIPT = approval.OSASCRIPT  # совместимость; подмена в тестах — approval.OSASCRIPT
TTL = 15 * 60
MAX_PENDING = 5
MAX_EXEC_PER_HOUR = 10
ESCALATE_WINDOW = 3600
MAX_SAME_FAILS = 2      # одинаковый план провалился/отклонён столько раз — дальше решает человек
MAX_FAILS_PER_WINDOW = 4  # всего неудач агента за окно
DIALOG_SECONDS = approval.DIALOG_SECONDS
KEEP_PLANS = 200
AGENT_OPS_L3 = ("runner.spawn", "runner.selftest")  # внешние действия CI: только агентам уровня L3 и ТОЛЬКО через диалог
AGENT_OPS = ("snapshot.create", "backup.run", "profile.install", "package.install", "project.run", "docker.container_control",
             # ревью 2026-10, шаг 4 (docs/roadmap.md): версии языков, сервисы для тестов, compose без down
             "lang.select", "python.install", "service.start", "service.stop", "service.restart", "docker.compose_control", *AGENT_OPS_L3)
MAX_L3_PER_HOUR = 3
MAX_L3_PROPOSALS = 6    # предложений L3 в час на агента: иначе поток диалогов утомляет человека
MAX_PLAN_SECONDS = 30 * 60    # одна задача агента (кроме L3: у раннеров свои сроки) не живёт дольше — иначе её останавливает сервер
MAX_CYCLE_SECONDS = 45 * 60   # суммарное время задач одного агента за час: дальше «цикл исправлений» стоит, решает человек
SNAPSHOT_OPS = ("package.install", "profile.install")  # меняют состав инструментов: до исполнения снимок, после — сравнение в verify
WATCH_POLL = 2
SETUP_GRACE = 300             # столько ждём появления job (снимок «до» ограничен 60 с)
MAX_AUTO_SNAPSHOTS = 20       # автоснимки «до» хранятся скользящим окном, чтобы не занять место под снимки пользователя
APPROVAL_MODES = ("dialog", "panel")
_LOCK = threading.RLock()


# ---------------------------------------------------------------- хранение

def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _plans():
    return _load(PLANS_FILE, {"plans": []})["plans"]


def _save_plans(plans):
    plans.sort(key=lambda p: p["created"])
    _write(PLANS_FILE, {"plans": plans[-KEEP_PLANS:]})


def _update(plan_id, **changes):
    with _LOCK:
        plans = _plans()
        for p in plans:
            if p["id"] == plan_id:
                p.update(changes)
                _save_plans(plans)
                return p
    return None


def policy():
    p = _load(POLICY_FILE, {})
    return {"approval": p.get("approval") if p.get("approval") in APPROVAL_MODES else "dialog"}


def _status(p):
    """Производный статус: истечение срока и исход job считаются лениво."""
    st = p["status"]
    if st in ("pending", "awaiting_human", "approved") and time.time() > p["expires"]:
        return "expired"
    if st == "executing":
        if p.get("error") == "timeout" and p.get("finished_at"):
            return "failed"
        if not p.get("job"):  # окно между пометкой «исполняется» и появлением job (снимок «до», запуск)
            return "executing" if time.time() - (p.get("executed_at") or 0) < SETUP_GRACE else "failed"
        job = JOBS.get(p.get("job"))
        if job and job["done"]:
            return "done" if job["code"] == 0 else "failed"
        if not job:
            return "failed"  # панель перезапускалась: job пропала, исход неизвестен — считаем неудачей (не «зависшим»)
    return st


def public(p):
    out = {k: p.get(k) for k in ("id", "agent_id", "agent_name", "operation", "title", "params", "level", "created", "expires",
                                 "approval", "job", "executed_at", "error", "view", "noop")}
    out["status"] = _status(p)
    out["digest"] = (p.get("digest") or "")[:12]
    return out


def _audit(event, p, result="ok", **extra):
    try:
        audit.record(f"plan:{event}", {"plan": p["id"], "operation": p["operation"]}, result, 0,
                     extra={"agent": p["agent_name"], "agent_id": p["agent_id"], **extra})
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- предложение

def _digest(op_id, params):
    pl = operations.plan(op_id, params)
    core = {"op": op_id, "params": params, "level": pl["level"], "executable": pl["executable"],
            "unmet": [u["id"] for u in pl["unmet_requirements"]], "plan": pl.get("plan")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest(), pl


def _red_run(p):
    """Тест/сборка проекта отработали и вернули ненулевой код (красные тесты). Это нормальный шаг цикла
    «исправил → перезапустил», а не сбой панели: в эскалацию не считаем. Таймаут (124), отмена (143),
    «не запустилось» (-1/127) и потерянная задача — считаем."""
    if p.get("operation") != "project.run" or _status(p) != "failed":
        return False
    job = JOBS.get(p.get("job"))
    return bool(job and job["done"] and job["code"] not in (None, -1, 124, 127, 143) and job["code"] > 0)


def _escalation(plans, agent, op_id, params):
    """Границы цикла «диагностика → исправление»: повторяющаяся ошибка или много неудач → стоп и эскалация человеку."""
    now = time.time()
    bad = [x for x in plans if x["agent_id"] == agent["id"] and now - x["created"] < ESCALATE_WINDOW
           and _status(x) in ("failed", "stale", "rejected") and not _red_run(x)]
    same = [x for x in bad if x["operation"] == op_id and x["params"] == params]
    if len(same) >= MAX_SAME_FAILS:
        return "same", len(same)
    if len([x for x in bad if _status(x) != "rejected"]) >= MAX_FAILS_PER_WINDOW:
        return "many", len(bad)
    return None, 0


def propose(agent, op_id, params):
    """Агент предлагает операцию. Ничего не исполняется."""
    if op_id not in AGENT_OPS:
        raise ApiError("This operation is not available to agents", HTTPStatus.FORBIDDEN, code="plan.op_not_allowed", op=str(op_id)[:40])
    op = operations.validate_params(op_id, params)
    level = operations.effective_level(op, params)
    if operations.LEVELS[level] > {"L1": 1, "L2": 2, "L3": 3}.get(agent["level"], 0):
        raise ApiError(f"Agent level {agent['level']} is below the operation level {level}", HTTPStatus.FORBIDDEN,
                       code="plan.level", level=level, agent_level=agent["level"])
    digest, pl = _digest(op_id, params)
    if not pl["executable"]:
        raise ApiError("Requirements are not met: " + "; ".join(u["summary"] for u in pl["unmet_requirements"]), HTTPStatus.CONFLICT,
                       code="plan.requirements", unmet=", ".join(u["id"] for u in pl["unmet_requirements"]))
    now = time.time()
    with _LOCK:
        plans = _plans()
        why, n = _escalation(plans, agent, op_id, params)
        if why:
            audit.record("plan:escalate", {"operation": op_id}, f"error: {why}", 0, extra={"agent": agent["name"], "agent_id": agent["id"]})
            raise ApiError("Stop: this keeps failing or being rejected. Do not retry; report the problem to the user and wait for their decision",
                           HTTPStatus.TOO_MANY_REQUESTS, code="plan.escalate", count=n)
        if level == "L3" and len([x for x in plans if x["agent_id"] == agent["id"] and x["level"] == "L3" and now - x["created"] < 3600]) >= MAX_L3_PROPOSALS:
            raise ApiError(f"Too many CI proposals this hour (max {MAX_L3_PROPOSALS})", HTTPStatus.TOO_MANY_REQUESTS, code="plan.rate_l3", max=MAX_L3_PROPOSALS)
        mine = [p for p in plans if p["agent_id"] == agent["id"] and _status(p) in ("pending", "awaiting_human", "approved")]
        if len(mine) >= MAX_PENDING:
            raise ApiError(f"Too many open plans (max {MAX_PENDING}); cancel or finish some first", HTTPStatus.CONFLICT,
                           code="plan.too_many", max=MAX_PENDING)
        noop = (pl.get("plan") or {}).get("will_change") is False
        plan = {"id": "p" + secrets.token_hex(4), "agent_id": agent["id"], "agent_name": agent["name"], "operation": op_id,
                "title": op["title"], "params": params, "level": level, "created": now, "expires": now + TTL,
                "digest": digest, "view": pl.get("plan"), "status": "noop" if noop else "pending", "noop": noop,
                "approval": None, "job": None, "executed_at": None, "error": None}
        if not noop and level == "L2" and agent.get("level") == "L2" and "L2" in (agent.get("auto_approve") or []):  # L3/L4 — никогда
            plan["status"] = "approved"
            plan["approval"] = {"by": "auto", "at": now, "mode": "auto"}
        plans.append(plan)
        _save_plans(plans)
    _audit("propose", plan, "auto-approved" if plan["status"] == "approved" else plan["status"], level=level)
    return public(plan)


def _own(agent, plan_id):
    p = next((x for x in _plans() if x["id"] == plan_id), None)
    if not p or p["agent_id"] != agent["id"]:
        raise ApiError("Plan not found", HTTPStatus.NOT_FOUND, code="plan.not_found")
    return p


def get(agent, plan_id):
    return public(_own(agent, plan_id))


def cancel(agent, plan_id):
    p = _own(agent, plan_id)
    if _status(p) not in ("pending", "awaiting_human", "approved"):
        raise ApiError("The plan can no longer be cancelled", HTTPStatus.CONFLICT, code="plan.not_cancellable")
    _update(plan_id, status="cancelled")
    _audit("cancel", p)
    return public(_own(agent, plan_id))


# ---------------------------------------------------------------- одобрение (человек)

def _ui_lang():
    """Язык системного диалога — по языку macOS (ru по умолчанию)."""
    try:
        out = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=5).stdout
        return "en" if '"en' in out.split(",")[0] or out.strip().startswith("(\n    en") else "ru"
    except (OSError, subprocess.TimeoutExpired):
        return "ru"


DIALOG_TEXT = {
    "ru": {"title": "Service Admin — подтверждение", "reject": "Отклонить", "approve": "Одобрить",
           "head": "Агент «{agent}» просит выполнить операцию.", "params": "Параметры", "what": "Что произойдёт", "until": "Действует до {t}.",
           "foot": "Если вы не запрашивали это — нажмите «Отклонить».",
           "l3": "ВНИМАНИЕ, уровень L3: действие затрагивает внешний сервер CI и запускает код в виртуальной машине.",
           "direct_foot": "Это запрос к панели напрямую (не от ИИ-агента через шлюз). Если вы не нажимали кнопку в панели — «Отклонить»."},
    "en": {"title": "Service Admin — approval", "reject": "Reject", "approve": "Approve",
           "head": "The agent “{agent}” asks to run an operation.", "params": "Parameters", "what": "What will happen", "until": "Valid until {t}.",
           "foot": "If you did not ask for this, click “Reject”.",
           "l3": "WARNING, level L3: this touches an external CI server and runs code in a virtual machine.",
           "direct_foot": "This is a direct request to the panel (not from an AI agent through the gateway). If you did not click a button in the panel, click “Reject”."},
}


DIRECT_TEXT_POLICY = {"ru": "Включить слабый режим одобрения «кнопка в панели»? Тогда планы агентов (кроме L3) будут одобряться кнопкой без этого диалога.",
                      "en": "Switch to the weaker approval mode “button in the panel”? Agent plans (except L3) would then be approved by a button without this dialog."}


def confirm_direct(summary):
    """Диалог для прямого вызова HTTP-API панели (не из плана агента): → "approve" | "reject" | "unavailable".
    summary — строка или {"ru":…, "en":…}. Агент с собственным терминалом может вызвать HTTP-маршрут; диалог — единственное, чего он не нажмёт."""
    lang = _ui_lang()
    text = summary[lang] if isinstance(summary, dict) else str(summary)
    d = DIALOG_TEXT[lang]
    return _ask(text + "\n\n" + d["direct_foot"], lang)


PARAM_ORDER = ["source", "vm", "labels", "minutes", "isolate", "name", "type", "project", "kind"]


def ordered_params(p):
    """Параметры плана в порядке «важное — первым» (не зависит от агента): их видит человек и в диалоге, и в сообщении оператору."""
    ordered = {k: p["params"][k] for k in PARAM_ORDER if k in p["params"]}
    ordered.update({k: v for k, v in p["params"].items() if k not in ordered})
    return json.dumps(ordered, ensure_ascii=False)


def _dialog_text(p, lang="ru"):
    d = DIALOG_TEXT[lang]
    view = p.get("view") or {}
    what = view.get("would_run") or ", ".join(view.get("to_install") or []) or view.get("writes") or ""
    params = ordered_params(p)
    warn = d["l3"] + "\n\n" if p.get("level") == "L3" else ""
    return (warn + d["head"].format(agent=p["agent_name"]) + f"\n\n{p['title']}  ({p['operation']}, {p['level']})\n{d['params']}: {params[:700]}\n"
            + (f"{d['what']}: {what[:200]}\n" if what else "")
            + "\n" + d["until"].format(t=time.strftime("%H:%M", time.localtime(p["expires"]))) + " " + d["foot"])


def ask_human(p):
    """→ "approve" | "reject" | "unavailable". Системный диалог macOS для плана агента."""
    lang = _ui_lang()
    return _ask(_dialog_text(p, lang), lang, p["id"])


def _ask(text, lang, rid=None):
    """Спрашивает человека через канал подтверждения платформы (approval.py): диалог macOS / zenity / корневой помощник Linux.
    → "approve" | "reject" | "unavailable"; кнопка по умолчанию — «Отклонить»."""
    return approval.ask(text, DIALOG_TEXT[lang], lang, rid or "direct-" + secrets.token_hex(6))


def _decide(plan_id, decision, by):
    with _LOCK:   # проверка статуса и запись решения — атомарно (иначе «одобрить» из диалога затёрло бы параллельное отклонение в панели)
        _decide_locked(plan_id, decision, by)


def _decide_locked(plan_id, decision, by):
    p = next((x for x in _plans() if x["id"] == plan_id), None)
    if not p or _status(p) != "awaiting_human":
        return
    if decision == "approve":
        _update(plan_id, status="approved", approval={"by": by, "at": time.time(), "mode": by})
        _audit("approve", p, "ok", by="panel" if by == "panel" else "user:dialog", approved_via=by)
    elif decision == "reject":
        _update(plan_id, status="rejected", approval={"by": by, "at": time.time(), "mode": by})
        _audit("reject", p, "ok", by="panel" if by == "panel" else "user:dialog", approved_via=by)
    else:
        _update(plan_id, status="pending", error="dialog_unavailable")
        _audit("approve", p, "error: dialog unavailable")


def approve(body):
    """POST /api/plans/approve {id} — запрос одобрения. В режиме «dialog» запускает системный диалог и возвращается сразу."""
    p0 = next((x for x in _plans() if x["id"] == body.get("id")), None)
    ch = approval.channel() if (p0 and (policy()["approval"] != "panel" or p0["level"] == "L3")) else None   # проверка канала может быть долгой — до блокировки
    with _LOCK:   # проверка статуса и его смена — атомарно: удалённое решение оператора не должно «проскочить» между ними
        p = next((x for x in _plans() if x["id"] == body.get("id")), None)
        if not p:
            raise ApiError("План не найден", HTTPStatus.NOT_FOUND, code="plan.not_found")
        if _status(p) != "pending":
            raise ApiError("План не ожидает подтверждения", HTTPStatus.CONFLICT, code="plan.not_pending")
        if ch is not None and ch["name"] is None:  # нет канала → fail closed, человека не спросить
            raise ApiError("No approval channel is available on this system (no dialog and no safe root helper); the plan cannot be approved",
                           HTTPStatus.CONFLICT, code="plan.no_approval_channel", unsafe=",".join(ch.get("unsafe") or []))
        if policy()["approval"] == "panel" and p["level"] != "L3":  # L3 — ВСЕГДА системный диалог, режим «кнопка в панели» на него не действует
            _update(p["id"], status="awaiting_human")
            _decide(p["id"], "approve", "panel")
        else:
            _update(p["id"], status="awaiting_human", error=None)
            core.spawn(lambda: _decide(p["id"], ask_human(p), "dialog"))
    return public(next(x for x in _plans() if x["id"] == p["id"]))


def reject(body):
    with _LOCK:
        p = next((x for x in _plans() if x["id"] == body.get("id")), None)
        if not p:
            raise ApiError("План не найден", HTTPStatus.NOT_FOUND, code="plan.not_found")
        if _status(p) not in ("pending", "awaiting_human", "approved"):
            raise ApiError("План уже не ожидает решения", HTTPStatus.CONFLICT, code="plan.not_pending")
        _update(p["id"], status="rejected", approval={"by": "panel", "at": time.time(), "mode": "panel"})
    _audit("reject", p, "ok", by="panel")
    return public(next(x for x in _plans() if x["id"] == p["id"]))


# ---------------------------------------------------------------- удалённое решение оператора (Фаза 8, ADR-0003)

def _remote_target(plan_id):
    p = next((x for x in _plans() if x["id"] == plan_id), None)
    if not p:
        raise ApiError("Plan not found", HTTPStatus.NOT_FOUND, code="plan.not_found")
    if _status(p) != "pending":
        raise ApiError("The plan is not waiting for a decision", HTTPStatus.CONFLICT, code="plan.not_pending")
    return p


def approve_remote(operator, plan_id, digest):
    """Одобрение оператором через удалённый API/бота. Только L2 и только с эхом хеша плана; L3 — исключительно системный диалог.
    Токен/TOTP/право `approve`/глобальную настройку проверяет вызывающий слой (remote_api)."""
    with _LOCK:
        p = _remote_target(plan_id)
        if p["level"] != "L2" or p.get("noop"):
            raise ApiError("Only an L2 plan can be approved remotely; L3 needs the system dialog on the machine with the panel",
                           HTTPStatus.FORBIDDEN, code="plan.remote_level", level=p["level"])
        if not isinstance(digest, str) or len(digest) < 12 or not hmac.compare_digest((p.get("digest") or "")[:len(digest)], digest):
            raise ApiError("The plan hash does not match what you saw; fetch the plan again", HTTPStatus.CONFLICT, code="plan.digest_mismatch")
        by = "operator:" + operator["name"]
        _update(plan_id, status="approved", approval={"by": by, "at": time.time(), "mode": "remote"}, error=None)
    _audit("approve", p, "ok", by=by, approved_via="remote")
    return public(next(x for x in _plans() if x["id"] == plan_id))


def reject_remote(operator, plan_id):
    with _LOCK:
        p = _remote_target(plan_id)
        by = "operator:" + operator["name"]
        _update(plan_id, status="rejected", approval={"by": by, "at": time.time(), "mode": "remote"})
    _audit("reject", p, "ok", by=by, approved_via="remote")
    return public(next(x for x in _plans() if x["id"] == plan_id))


def list_plans(q=None):
    plans = sorted(_plans(), key=lambda p: -p["created"])[:50]
    pub = [public(p) for p in plans]
    return {"plans": pub, "pending": sum(1 for p in pub if p["status"] == "pending"), "policy": policy(), "ttl_seconds": TTL,
            "agent_ops": list(AGENT_OPS)}


def set_policy(body):
    mode = body.get("approval")
    if mode not in APPROVAL_MODES:
        raise ApiError("Режим одобрения: dialog | panel", code="plan.mode_invalid")
    if mode == "panel" and policy()["approval"] != "panel":  # ослабление защиты подтверждается человеком в системном диалоге
        if confirm_direct(DIRECT_TEXT_POLICY) != "approve":
            raise ApiError("Switching to the weaker approval mode was not confirmed in the system dialog", HTTPStatus.FORBIDDEN, code="plan.dialog_denied")
    _write(POLICY_FILE, {**_load(POLICY_FILE, {}), "approval": mode})
    audit.record("plan:policy", {"approval": mode}, "ok", 0)
    return {"policy": policy()}


# ---------------------------------------------------------------- исполнение и проверка

def execute(agent, plan_id):
    """Исполнить ОДОБРЕННЫЙ план — один раз и только если он всё ещё актуален."""
    p = _own(agent, plan_id)
    st = _status(p)
    if st != "approved":
        code = {"pending": "plan.not_approved", "awaiting_human": "plan.not_approved", "rejected": "plan.rejected", "expired": "plan.expired",
                "executing": "plan.already_executed", "done": "plan.already_executed", "failed": "plan.already_executed",
                "cancelled": "plan.cancelled", "stale": "plan.stale", "noop": "plan.noop"}.get(st, "plan.not_approved")
        raise ApiError(f"The plan is {st}; it cannot be executed", HTTPStatus.CONFLICT, code=code, state=st)
    now = time.time()
    with _LOCK:
        p = _own(agent, plan_id)
        if _status(p) != "approved":  # второй параллельный execute того же плана
            raise ApiError("The plan is not approved or was already executed", HTTPStatus.CONFLICT, code="plan.already_executed", state=_status(p))
        if any(x["agent_id"] == agent["id"] and x["id"] != plan_id and _status(x) == "executing" for x in _plans()):
            raise ApiError("Another plan of this agent is still running; wait for it to finish", HTTPStatus.CONFLICT, code="plan.busy")
        recent = [x for x in _plans() if x["agent_id"] == agent["id"] and x.get("executed_at") and now - x["executed_at"] < 3600]
        if len(recent) >= MAX_EXEC_PER_HOUR:
            raise ApiError(f"Too many executions this hour (max {MAX_EXEC_PER_HOUR})", HTTPStatus.TOO_MANY_REQUESTS,
                           code="plan.rate", max=MAX_EXEC_PER_HOUR)
        spent = sum(((x.get("finished_at") or (now if x.get("job") in JOBS and not JOBS[x["job"]]["done"] else x["executed_at"])) - x["executed_at"]) for x in recent)
        if spent >= MAX_CYCLE_SECONDS:
            _audit("cycle_budget", p, "error: time budget of the cycle is exhausted")
            raise ApiError("The agent has used its job-time budget for this hour; stop and report to the user", HTTPStatus.TOO_MANY_REQUESTS,
                           code="plan.cycle_budget", minutes=MAX_CYCLE_SECONDS // 60)
        if p["level"] == "L3" and len([x for x in recent if x["level"] == "L3"]) >= MAX_L3_PER_HOUR:
            raise ApiError(f"Too many CI operations this hour (max {MAX_L3_PER_HOUR})", HTTPStatus.TOO_MANY_REQUESTS, code="plan.rate_l3", max=MAX_L3_PER_HOUR)
        spent_before = spent
        digest, pl = _digest(p["operation"], p["params"])
        if digest != p["digest"] or not pl["executable"]:
            _update(plan_id, status="stale", error="state_changed")
            _audit("stale", p, "error: plan is stale")
            raise ApiError("The machine or project changed since the plan was approved; ask for a new plan", HTTPStatus.CONFLICT,
                           code="plan.stale")
        if p["level"] == "L3" and (p.get("approval") or {}).get("mode") != "dialog":
            _update(plan_id, status="rejected", error="l3_without_dialog")
            _audit("reject", p, "error: L3 plan without a dialog approval")
            raise ApiError("An L3 plan can only run after approval in the system dialog", HTTPStatus.CONFLICT, code="plan.not_approved", state="l3_without_dialog")
        _update(plan_id, status="executing", executed_at=now)  # помечаем ДО запуска: повторно исполнить нельзя
    if p["operation"] in SNAPSHOT_OPS:
        _snapshot_before(plan_id, p)
    try:
        r = operations.execute(p["operation"], p["params"])
    except Exception as e:  # noqa: BLE001
        _update(plan_id, status="failed", error=str(e)[:200])
        _audit("execute", p, f"error: {e}")
        raise
    if r.get("job"):
        _update(plan_id, job=r["job"])
        left = max(60, MAX_CYCLE_SECONDS - spent_before)
        core.spawn(_watch, plan_id, r["job"], None if p["level"] == "L3" else min(MAX_PLAN_SECONDS, left))
    else:
        _update(plan_id, status="done", result=r.get("result"))
    _audit("execute", p, "ok", job=r.get("job"))
    return {"plan": public(_own(agent, plan_id)), "job": r.get("job"), "result": r.get("result")}


def _snapshot_before(plan_id, p):
    """Снимок «до» для сравнения в verify (не дольше 60 с; сбор не удался — идём без него). Автоснимки хранятся скользящим окном."""
    box = {}

    def work():
        try:
            import snapshots
            for old in [x["id"] for x in snapshots.list_snapshots()["snapshots"] if (x.get("label") or "").startswith("plan ")][:-MAX_AUTO_SNAPSHOTS + 1]:
                snapshots.delete({"id": old})
            box["id"] = snapshots.create({"label": f"plan {plan_id[:8]} before"})["id"]
        except Exception as e:  # noqa: BLE001
            box["err"] = str(e)[:100]

    box["t"] = t = core.spawn(work)
    t.join(60)
    if box.get("id"):
        _update(plan_id, snapshot_before=box["id"])
    else:
        _audit("snapshot_skipped", p, f"error: {box.get('err', 'timeout')}")


def _watch(plan_id, job_id, limit):
    """Следит за задачей плана: фиксирует время окончания (для бюджета цикла) и один раз останавливает задачу, прожившую дольше limit секунд."""
    started, stopped = time.time(), False
    while True:
        job = JOBS.get(job_id)
        if not job or job["done"]:
            if stopped:
                _update(plan_id, finished_at=time.time(), error="timeout")
            else:
                _update(plan_id, finished_at=time.time())
            return
        if limit and not stopped and time.time() - started > limit:
            stopped = True
            try:
                core.cancel_job({"id": job_id})
            except Exception:  # noqa: BLE001
                pass
            p = _update(plan_id, error="timeout")
            if p:
                _audit("timeout", p, f"error: the job exceeded {int(limit) // 60} min and was stopped")
        time.sleep(WATCH_POLL)


def _snapshot_diff(plan):
    """Сравнение снимка «до» с текущим состоянием: что реально изменилось на машине."""
    sid = plan.get("snapshot_before")
    if not sid:
        return None
    try:
        import snapshots
        d = snapshots.diff({"a": sid, "b": "current"})
        secs = [{"section": x["id"], "added": [i["key"] for i in x["added"]][:30], "removed": [i["key"] for i in x["removed"]][:30],
                 "changed": [i["key"] for i in x["changed"]][:30]} for x in d["sections"]]
        return {"before": sid, "total_changes": d["total"], "sections": secs[:15], "complete": d.get("note") != "incomplete"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:150]}


def verify(agent, plan_id):
    p = _own(agent, plan_id)
    st = _status(p)
    if st in ("approved", "pending", "awaiting_human"):
        raise ApiError("The plan has not been executed yet", HTTPStatus.CONFLICT, code="plan.not_executed")
    if st == "executing":
        raise ApiError("The operation is still running", HTTPStatus.CONFLICT, code="plan.running")
    if st not in ("done", "failed"):
        raise ApiError("Nothing to verify", HTTPStatus.CONFLICT, code="plan.not_executed")
    out = {"plan": public(p), "executed_ok": st == "done"}
    sd = _snapshot_diff(p)
    if sd is not None:
        out["snapshot_diff"] = sd
    try:
        out["verification"] = operations.verify(p["operation"], p["params"])
    except ApiError as e:
        out["verification"] = {"ok": None, "note": str(e)}
    return out
