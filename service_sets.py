"""Наборы сервисов и группы запуска (Фаза 10): «запустить всё» для связки сервисов поверх `brew services`.

Готовые наборы (Laravel, Node, Python) + свои группы пользователя (в `state.json`). Действия: запустить / остановить / перезапустить все сервисы набора,
поставить недостающие. Исполняются задачей (`start_steps`: видно ход и журнал, пишется в аудит), команды — списком аргументов, имена проверяются.
Только macOS (Homebrew); на Linux сервисы — systemd, наборов пока нет."""
import os
import re
import secrets
import sys
from http import HTTPStatus

from core import BREW, BREW_PREFIX, PKG_RE, ApiError, load_state, save_state, start_steps

PRESETS = [
    {"id": "laravel", "members": ["nginx", "php", "mysql", "redis", "mailpit"]},
    {"id": "node", "members": ["postgresql@17", "redis", "mailpit"]},
    {"id": "python", "members": ["postgresql@17", "redis", "rabbitmq"]},
]
NAME_RE = re.compile(r"^[^\x00-\x1f<>]{1,40}$")
MAX_GROUPS, MAX_MEMBERS = 20, 20
ACTIONS = ("start", "stop", "restart", "install")
KIND = "svcgroup"


def _installed():
    try:
        return set(os.listdir(os.path.join(BREW_PREFIX, "Cellar")))
    except OSError:
        return set()


def _services():
    """{имя: запущен ли} из brew services или None, если узнать нельзя."""
    try:
        import brewsvc
        return {s["name"]: bool(s.get("running")) for s in brewsvc.list_services()}
    except Exception:  # noqa: BLE001
        return None


def _groups():
    g = load_state().get("service_groups")
    return g if isinstance(g, list) else []


def list_sets(q=None):
    """GET /api/service-sets → готовые наборы и свои группы со статусом каждого сервиса."""
    if sys.platform != "darwin":
        return {"supported": False, "sets": []}
    inst, running = _installed(), _services()
    out = []
    for kind, items in (("preset", PRESETS), ("user", _groups())):
        for s in items:
            members = [{"name": m, "installed": m.split("/")[-1] in inst, "running": (running or {}).get(m.split("/")[-1])} for m in s["members"]]
            out.append({"id": s["id"], "kind": kind, "name": s.get("name"), "members": members,
                        "running": sum(1 for m in members if m["running"]), "installed": sum(1 for m in members if m["installed"]), "total": len(members)})
    return {"supported": True, "sets": out}


def _find(set_id):
    s = next((x for x in PRESETS + _groups() if x["id"] == set_id), None)
    if not s:
        raise ApiError("Набор не найден", HTTPStatus.NOT_FOUND, code="sets.not_found")
    return s


def _label(s):
    return s.get("name") or s["id"]


def run_action(body):
    """POST /api/service-sets/action {id, action: start|stop|restart|install} → {"job"}. Не установленные сервисы пропускаются (кроме install)."""
    if sys.platform != "darwin":
        raise ApiError("Наборы сервисов доступны только на macOS (Homebrew)", HTTPStatus.CONFLICT, code="platform.unsupported")
    action = body.get("action")
    if action not in ACTIONS:
        raise ApiError("Действие: start, stop, restart или install", code="sets.action_invalid")
    s = _find(str(body.get("id", "")))
    inst = _installed()
    steps = []
    for m in s["members"]:
        if not PKG_RE.match(m):
            continue
        short = m.split("/")[-1]
        if action == "install":
            if short not in inst:
                steps.append((f"brew install {m}", [BREW, "install", "--formula", m], {}))
        elif short in inst:
            steps.append((f"brew services {action} {short}", [BREW, "services", action, short], {"optional": True}))   # один упавший сервис не должен останавливать остальные
    if not steps:
        raise ApiError("Нечего делать: все сервисы набора уже в нужном состоянии или не установлены", HTTPStatus.CONFLICT, code="sets.nothing_to_do")
    return {"job": start_steps(f"{action}: {_label(s)}", steps, KIND)}


def create_group(body):
    """POST {name, members:[имена сервисов]} — своя группа запуска (хранится в state.json)."""
    name = str(body.get("name", "")).strip()
    members = body.get("members")
    if not NAME_RE.match(name):
        raise ApiError("Название группы: 1–40 символов", code="sets.name_invalid")
    if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS or any(not isinstance(m, str) or not PKG_RE.match(m) for m in members):
        raise ApiError(f"Состав группы: от 1 до {MAX_MEMBERS} сервисов (имена Homebrew)", code="sets.members_invalid", max=MAX_MEMBERS)
    groups = _groups()
    if len(groups) >= MAX_GROUPS:
        raise ApiError(f"Не более {MAX_GROUPS} своих групп", HTTPStatus.CONFLICT, code="sets.too_many", max=MAX_GROUPS)
    if any(g["name"].lower() == name.lower() for g in groups):
        raise ApiError("Группа с таким названием уже есть", HTTPStatus.CONFLICT, code="sets.name_exists")
    g = {"id": "g" + secrets.token_hex(3), "name": name, "members": list(dict.fromkeys(members))}
    save_state(service_groups=groups + [g])
    return {"group": g}


def delete_group(body):
    groups = _groups()
    gid = str(body.get("id", ""))
    if not any(g["id"] == gid for g in groups):
        raise ApiError("Группа не найдена", HTTPStatus.NOT_FOUND, code="sets.not_found")
    save_state(service_groups=[g for g in groups if g["id"] != gid])
    return {"deleted": gid}
