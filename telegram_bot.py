"""Telegram-бот оператора (Фаза 8, ADR-0003). Бот ВЛАДЕЛЬЦА: он сам создаёт его у @BotFather и вставляет токен в панель.

Бот опрашивает Telegram исходящим HTTPS (getUpdates); входящий порт не нужен. Принимает только личные чаты, `chat_id` которых привязан к
оператору в панели. Команды: /status, /plans, /approve <id> <хеш> <код>, /reject <id>. Одобрение — только планы L2, с одноразовым TOTP-кодом
оператора, эхом хеша плана и при включённой настройке «удаленное одобрение» (то же самое проверяет и удалённый API). В сообщениях —
краткое описание плана и id, без секретов. Токен бота — файл 0600 в каталоге данных; в журнал и ответы он не попадает.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus

import audit
import operators
import remote_api
from core import DATA_DIR, ApiError

API = "https://api.telegram.org"          # подменяется в тестах
TOKEN_FILE = os.path.join(DATA_DIR, "telegram-bot.token")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram.offset")
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")
POLL_SECONDS = 25
NOTIFY_EVERY = 5
MAX_TEXT = 3500
_RUN = {"stop": threading.Event()}   # у каждого запуска СВОЁ событие: старые потоки не «оживают», когда запускается новый
_THREADS = []
_STATE = {"username": None, "error": None, "running": False}
_NOTIFIED = set()
_STRANGERS = {}


def _token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        return t if TOKEN_RE.match(t) else None
    except OSError:
        return None


def _call(token, method, params=None, timeout=35):
    """Вызов Bot API. Токен лежит только в URL запроса и никогда не возвращается/не пишется в журнал."""
    req = urllib.request.Request(f"{API}/bot{token}/{method}", json.dumps(params or {}).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"ok": False, "description": f"HTTP {e.code}"}


def _send(token, chat_id, text):
    try:
        _call(token, "sendMessage", {"chat_id": chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": True}, timeout=20)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- команды (чистые функции: текст → ответ; тестируются без сети)

def _plan_line(p):
    left = max(0, int((p["expires"] - time.time()) // 60))
    return f"{p['id']} · {p['agent_name']} · {p['operation']} ({p['level']}) · осталось {left} мин\nпараметры: {plans_params(p)[:500]}"


def plans_params(p):
    import plans
    return plans.ordered_params(p)


def handle_text(op, text):
    """op — запись оператора (по chat_id). → строка ответа."""
    import plans
    parts = (text or "").strip().split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    scopes = op.get("scopes") or []
    if cmd in ("/start", "/help"):
        return ("Service Admin. Команды:\n/status — состояние\n/plans — ожидающие планы\n"
                "/approve <id> <хеш> <код> — одобрить (L2; код — из приложения-аутентификатора)\n/reject <id> — отклонить")
    if cmd == "/status":
        pl = plans.list_plans()
        return f"Ожидают решения: {pl['pending']}. Удалённое одобрение: {'включено' if remote_api.settings()['remote_approval'] else 'выключено'}."
    if cmd == "/plans":
        pend = [p for p in plans.list_plans()["plans"] if p["status"] == "pending"]
        if not pend:
            return "Ожидающих планов нет."
        return "\n".join(_plan_line(p) + f"\nхеш: {p['digest']}" for p in pend)
    if cmd in ("/approve", "/reject"):
        if "approve" not in scopes:
            return "У вас нет права одобрять."
        try:
            if cmd == "/reject":
                if len(parts) != 2:
                    return "Формат: /reject <id>"
                r = plans.reject_remote(op, parts[1])
                return f"Отклонён: {r['id']}"
            if len(parts) != 4:
                return "Формат: /approve <id> <хеш> <код>"
            if not remote_api.settings()["remote_approval"]:
                return "Удалённое одобрение выключено в настройках панели."
            if operators.is_locked(op["id"]):
                return "Одобрение заблокировано после неверных кодов; снимите блокировку у оператора в панели."
            if not operators.verify_totp(op["id"], parts[3]):
                audit.record("remote:approve", {"operator": op["name"], "plan": parts[1][:12], "via": "telegram"}, "error: bad or reused TOTP code")
                return "Код неверен или уже использован."
            r = plans.approve_remote(op, parts[1], parts[2])
            return f"Одобрен: {r['id']}. Агент может исполнять план."
        except ApiError as e:
            return f"Отказ: {e}"
    return "Неизвестная команда. /help"


def _handle_update(token, upd):
    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or not isinstance(chat.get("id"), int):
        return
    op = operators.by_chat(chat["id"])
    if not op or "read" not in (op.get("scopes") or []) and "approve" not in (op.get("scopes") or []):
        now = time.time()
        if now - _STRANGERS.get(chat["id"], 0) > 3600:      # на чужие чаты отвечаем один раз в час и ничего не раскрываем
            if len(_STRANGERS) > 1000:
                _STRANGERS.clear()
            _STRANGERS[chat["id"]] = now
            audit.record("telegram:unknown_chat", {"chat_id": chat["id"]}, "error: chat is not bound to an operator")
            _send(token, chat["id"], f"Этот чат не привязан к оператору. Ваш chat_id: {chat['id']} — укажите его в панели у оператора.")
        return
    operators.touch(op["id"])
    audit.INITIATOR.set("operator:" + op["name"])
    _send(token, chat["id"], handle_text(op, msg.get("text") or ""))


def notify_new_plans(token):
    """Сообщить операторам с правом approve о новых планах, ожидающих решения."""
    import plans
    for p in plans.list_plans()["plans"]:
        if p["status"] != "pending" or p["id"] in _NOTIFIED:
            continue
        _NOTIFIED.add(p["id"])
        view = p.get("view") or {}
        what = view.get("would_run") or ", ".join(view.get("to_install") or []) or view.get("writes") or ""
        if p["level"] == "L3":
            tail = "Уровень L3: одобрить можно только системным окном на машине с панелью."
        elif remote_api.settings()["remote_approval"]:
            tail = f"Одобрить: /approve {p['id']} {p['digest']} <код>\nОтклонить: /reject {p['id']}"
        else:
            tail = "Удалённое одобрение выключено; решение — в панели."
        text = f"Новый план от агента «{p['agent_name']}»\n{p['title']} ({p['operation']}, {p['level']})\nпараметры: {plans_params(p)[:500]}\n{what[:200]}\n{tail}"
        for o in operators._load()["operators"]:  # noqa: SLF001
            if not o.get("revoked") and o.get("telegram_chat_id") and "approve" in (o.get("scopes") or []):
                _send(token, o["telegram_chat_id"], text)
    if len(_NOTIFIED) > 1000:
        _NOTIFIED.clear()


# ---------------------------------------------------------------- потоки

def _still_enabled(token):
    return remote_api.settings()["telegram"]["enabled"] and _token() == token


def _load_offset():
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return max(0, int(f.read().strip()))
    except (OSError, ValueError):
        return 0


def _save_offset(offset):
    try:
        old = os.umask(0o177)
        try:
            with open(OFFSET_FILE, "w", encoding="utf-8") as f:
                f.write(str(offset))
        finally:
            os.umask(old)
    except OSError:
        pass


def _poll_loop(token, stop):
    offset = _load_offset()   # подтверждённые сообщения не проигрываются заново после перезапуска панели/бота
    while not stop.is_set():
        try:
            r = _call(token, "getUpdates", {"offset": offset, "timeout": POLL_SECONDS, "allowed_updates": ["message"]}, timeout=POLL_SECONDS + 10)
            if stop.is_set() or not _still_enabled(token):   # выключили бота или сменили токен, пока шёл долгий опрос: сообщения не обрабатываем
                return
            if not r.get("ok"):
                _STATE["error"] = (r.get("description") or "error")[:100]
                stop.wait(10)
                continue
            _STATE["error"] = None
            for upd in r.get("result", []):
                offset = max(offset, upd.get("update_id", 0) + 1)
                _save_offset(offset)
                try:
                    _handle_update(token, upd)
                except Exception as e:  # noqa: BLE001 — одно сообщение не должно останавливать бота
                    audit.record("telegram:error", {}, f"error: {str(e)[:100]}")
        except Exception as e:  # noqa: BLE001 — сеть, обрыв чтения (http.client.HTTPException), любой сбой: поток не умирает молча
            _STATE["error"] = f"network: {str(e)[:80]}"
            stop.wait(10)


def _notify_loop(token, stop):
    while not stop.wait(NOTIFY_EVERY):
        if not _still_enabled(token):
            return
        try:
            notify_new_plans(token)
        except Exception as e:  # noqa: BLE001
            _STATE["error"] = f"notify: {str(e)[:80]}"


def stop():
    _RUN["stop"].set()            # старые потоки видят СВОЁ событие и завершаются; новый запуск получит новое
    _THREADS.clear()
    _STATE["running"] = False


def apply():
    """Запустить/остановить бота по настройкам (старт панели, смена настроек)."""
    stop()
    _RUN["stop"] = ev = threading.Event()
    token = _token()
    if not (remote_api.settings()["telegram"]["enabled"] and token):
        return
    try:  # уже существующие ожидающие планы не пересылаем при каждом запуске
        import plans
        _NOTIFIED.update(p["id"] for p in plans.list_plans()["plans"] if p["status"] == "pending")
    except Exception:  # noqa: BLE001
        pass
    for fn in (_poll_loop, _notify_loop):
        t = threading.Thread(target=fn, args=(token, ev), daemon=True)
        t.start()
        _THREADS.append(t)
    _STATE["running"] = True


# ---------------------------------------------------------------- управление из панели (localhost)

def status(q=None):
    return {"enabled": remote_api.settings()["telegram"]["enabled"], "token_set": bool(_token()), "running": _STATE["running"],
            "username": _STATE["username"], "error": _STATE["error"]}


def set_settings(body):
    """POST {token?, enabled?}. Включение бота и смена его токена подтверждаются человеком в системном диалоге: иначе локальный агент мог бы
    подставить своего бота и привязать свой чат к оператору."""
    changed = []
    if "token" in body and body["token"]:
        if not isinstance(body["token"], str) or not TOKEN_RE.match(body["token"].strip()):
            raise ApiError("Это не похоже на токен бота (123456:ABC…)", code="tg.token_invalid")
        changed.append("token")
    cur = remote_api.settings()
    enabled = body.get("enabled", cur["telegram"]["enabled"])
    if not isinstance(enabled, bool):
        raise ApiError("enabled — true или false", code="tg.enabled_invalid")
    if enabled and not cur["telegram"]["enabled"]:
        changed.append("enable")
    if changed:
        remote_api._confirm("Service Admin: включить Telegram-бота / сменить его токен. Через бота операторы смогут смотреть состояние и одобрять планы.",  # noqa: SLF001
                            "Service Admin: turn on the Telegram bot / change its token. Operators will be able to view state and approve plans through it.")
    if "token" in changed:
        old = os.umask(0o177)
        try:
            fd = os.open(TOKEN_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body["token"].strip() + "\n")
            os.replace(TOKEN_FILE + ".tmp", TOKEN_FILE)
        finally:
            os.umask(old)
    remote_api.update_settings(lambda s: s["telegram"].update(enabled=enabled if "enabled" in body else s["telegram"]["enabled"]))   # перечитывание ПОСЛЕ диалога: чужие свежие изменения не затираются
    audit.record("telegram:settings", {"enabled": enabled, "token_changed": "token" in changed}, "ok")
    apply()
    return status()


def check(body=None):
    """POST — проверить токен вызовом getMe (имя бота нужно, чтобы владелец убедился, что токен тот)."""
    token = _token()
    if not token:
        raise ApiError("Токен бота не задан", HTTPStatus.CONFLICT, code="tg.no_token")
    try:
        r = _call(token, "getMe", timeout=20)
    except (OSError, ValueError):
        raise ApiError("Не удалось связаться с Telegram", HTTPStatus.BAD_GATEWAY, code="tg.unreachable") from None
    if not r.get("ok"):
        raise ApiError("Telegram не принял токен", HTTPStatus.BAD_REQUEST, code="tg.token_rejected")
    _STATE["username"] = (r.get("result") or {}).get("username")
    return status()
