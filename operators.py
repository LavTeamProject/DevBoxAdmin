"""Операторы панели (Фаза 8, ADR-0003): люди-администраторы, которые удалённо смотрят состояние и одобряют планы L2.

Оператор отличается от агента: у него свой реестр и токен (`sao_…`), права `read` / `approve`, второй фактор TOTP (RFC 6238, только stdlib)
и, по желанию, привязанный Telegram `chat_id`. В реестре — только SHA-256 токена; токен и секрет TOTP показываются один раз при создании.
Агент удалённо одобрить ничего не может: его токен не принимается операторскими эндпоинтами, а TOTP-секрета оператора у него нет.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from http import HTTPStatus

import audit
from core import DATA_DIR, ApiError

OPERATORS_FILE = os.path.join(DATA_DIR, "operators.json")
NAME_RE = re.compile(r"^[A-Za-z\u0410-\u044f\u0401\u04510-9][A-Za-z\u0410-\u044f\u0401\u04510-9 ._-]{0,39}$")   # латиница ИЛИ кириллица, цифры, пробел . _ -
LATIN, CYRILLIC = re.compile(r"[A-Za-z]"), re.compile(r"[\u0410-\u044f\u0401\u0451]")


def _check_name(name):
    """Имя — латиница или кириллица, но не смесь в одном имени: «Аlice» с кириллической «А» выглядела бы как «Alice» в диалогах подтверждения."""
    if not NAME_RE.match(name) or (LATIN.search(name) and CYRILLIC.search(name)):
        raise ApiError("Имя оператора: 1–40 символов, буквы только латинские ИЛИ только русские (не вперемешку), цифры, пробел, . _ -", code="op.name_invalid")
SCOPES = ("read", "approve")
MAX_OPERATORS = 20
TOKEN_PREFIX = "sao_"
TOKEN_MAX = 200
TOTP_STEP = 30
TOTP_WINDOW = 1          # допускаем соседние 30-секундные шаги (часы клиента)
TOTP_MAX_FAILS = 5       # подряд неверных кодов → оператор блокируется для одобрения; снять блок может только человек в панели
_LOCK = threading.Lock()


def _load():
    try:
        with open(OPERATORS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d.get("operators"), list) else {"operators": []}
    except (OSError, ValueError, AttributeError):
        return {"operators": []}


def _save(data):
    os.makedirs(os.path.dirname(OPERATORS_FILE), mode=0o700, exist_ok=True)
    tmp = OPERATORS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OPERATORS_FILE)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public(o):
    """Что можно отдать в панель: без хеша токена и без секрета TOTP."""
    out = {k: o.get(k) for k in ("id", "name", "scopes", "telegram_chat_id", "created", "last_seen", "expires", "revoked")}
    out["totp_locked"] = bool(o.get("totp_locked"))
    return out


def list_operators(q=None):
    return {"operators": [public(o) for o in _load()["operators"]], "scopes": list(SCOPES)}


# ---------------------------------------------------------------- TOTP (RFC 6238)

def _hotp(secret, counter):
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000)


def totp_now(secret_b32, at=None):
    """Для тестов и проверки: текущий код по секрету base32."""
    key = base64.b32decode(secret_b32)
    return _hotp(key, int((at if at is not None else time.time()) // TOTP_STEP))


def verify_totp(operator_id, code, now=None):
    """True, если код верен и ещё не использовался (одноразовость: шаг строго больше последнего принятого).
    После TOTP_MAX_FAILS неверных кодов подряд оператор блокируется (`totp_locked`) — иначе 6 цифр подбираются за дни; снимает блок человек в панели."""
    code = str(code or "").strip()
    now = now if now is not None else time.time()
    with _LOCK:
        data = _load()
        o = next((x for x in data["operators"] if x["id"] == operator_id and not x.get("revoked")), None)
        if not o or o.get("totp_locked"):
            return False
        key = base64.b32decode(o["totp_secret"])
        cur = int(now // TOTP_STEP)
        last = o.get("totp_last", 0)
        ok_step, replay = None, False
        if re.fullmatch(r"\d{6}", code):
            for step in range(cur - TOTP_WINDOW, cur + TOTP_WINDOW + 1):
                if hmac.compare_digest(_hotp(key, step), code):
                    if step > last:
                        ok_step = step
                    else:
                        replay = True   # верный, но уже использованный код (повтор клиента, повторная доставка) — отказ, но не «подбор»
        if ok_step is None and replay:
            return False
        if ok_step is None:
            o["totp_fails"] = o.get("totp_fails", 0) + 1
            if o["totp_fails"] >= TOTP_MAX_FAILS:
                o["totp_locked"] = True
            _save(data)
            if o.get("totp_locked"):
                audit.record("operator:totp_locked", {"id": o["id"], "name": o["name"]}, "error: too many wrong TOTP codes; unlock it in the panel")
            return False
        o["totp_last"], o["totp_fails"] = ok_step, 0
        _save(data)
        return True


def is_locked(operator_id):
    o = next((x for x in _load()["operators"] if x["id"] == operator_id and not x.get("revoked")), None)
    return bool(o and o.get("totp_locked"))


def unlock(body):
    """POST {id} — человек снимает блокировку TOTP в панели (это не ослабление защиты, диалог не нужен)."""
    with _LOCK:
        data = _load()
        o = next((x for x in data["operators"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not o:
            raise ApiError("Оператор не найден", HTTPStatus.NOT_FOUND, code="op.not_found")
        o["totp_locked"], o["totp_fails"] = False, 0
        _save(data)
    audit.record("operator:unlock", {"id": o["id"], "name": o["name"]}, "ok")
    return {"operator": public(o)}


# ---------------------------------------------------------------- управление (из панели, на localhost)

def _check_scopes(scopes):
    if not isinstance(scopes, list) or not scopes or any(s not in SCOPES for s in scopes):
        raise ApiError("Права оператора: read и/или approve", code="op.scopes_invalid")
    return sorted(set(scopes))


def _check_chat(chat):
    if chat in (None, "", 0):
        return None
    if isinstance(chat, bool) or not isinstance(chat, (int, str)) or not re.fullmatch(r"\d{1,15}", str(chat)):
        raise ApiError("chat_id Telegram — число (личный чат)", code="op.chat_invalid")
    return int(chat)


def create(body):
    """POST {name, scopes?, expires_days?, telegram_chat_id?} → оператор. Токен и секрет TOTP возвращаются ОДИН раз."""
    name = (body.get("name") or "").strip()
    _check_name(name)
    scopes = _check_scopes(body.get("scopes", ["read"]))
    days = body.get("expires_days")
    if days is not None and (not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365):
        raise ApiError("Срок действия: от 1 до 365 дней", code="op.expires_invalid")
    chat = _check_chat(body.get("telegram_chat_id"))
    with _LOCK:
        data = _load()
        active = [o for o in data["operators"] if not o.get("revoked")]
        if len(active) >= MAX_OPERATORS:
            raise ApiError(f"Не более {MAX_OPERATORS} активных операторов", HTTPStatus.CONFLICT, code="op.too_many", max=MAX_OPERATORS)
        if any(o["name"].lower() == name.lower() for o in active):
            raise ApiError("Оператор с таким именем уже есть", HTTPStatus.CONFLICT, code="op.name_exists")
        if chat and any(o.get("telegram_chat_id") == chat for o in active):
            raise ApiError("Этот Telegram-чат уже привязан к другому оператору", HTTPStatus.CONFLICT, code="op.chat_exists")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        secret = base64.b32encode(secrets.token_bytes(20)).decode()
        o = {"id": "o" + secrets.token_hex(3), "name": name, "scopes": scopes, "telegram_chat_id": chat, "created": time.time(), "last_seen": None,
             "expires": time.time() + days * 86400 if days else None, "revoked": False, "token_hash": _hash(token), "totp_secret": secret, "totp_last": 0}
        data["operators"].append(o)
        _save(data)
    audit.record("operator:create", {"id": o["id"], "name": name, "scopes": scopes}, "ok")
    uri = f"otpauth://totp/Service%20Admin:{name.replace(' ', '%20')}?secret={secret}&issuer=Service%20Admin&digits=6&period={TOTP_STEP}"
    return {"operator": public(o), "token": token, "totp_secret": secret, "totp_uri": uri}


def rotate(body):
    """POST {id} — новый токен и новый секрет TOTP (старые перестают действовать). Возвращаются один раз."""
    with _LOCK:
        data = _load()
        o = next((x for x in data["operators"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not o:
            raise ApiError("Оператор не найден", HTTPStatus.NOT_FOUND, code="op.not_found")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        o["token_hash"] = _hash(token)
        o["totp_secret"] = base64.b32encode(secrets.token_bytes(20)).decode()
        o["totp_last"], o["totp_fails"], o["totp_locked"] = 0, 0, False
        _save(data)
    audit.record("operator:rotate", {"id": o["id"], "name": o["name"]}, "ok")
    return {"operator": public(o), "token": token, "totp_secret": o["totp_secret"]}


def revoke(body):
    with _LOCK:
        data = _load()
        o = next((x for x in data["operators"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not o:
            raise ApiError("Оператор не найден", HTTPStatus.NOT_FOUND, code="op.not_found")
        o["revoked"], o["token_hash"], o["totp_secret"] = True, None, ""
        _save(data)
    audit.record("operator:revoke", {"id": o["id"], "name": o["name"]}, "ok")
    return {"revoked": o["id"]}


def set_operator(body, expect=None):
    """POST {id, scopes?, telegram_chat_id?} — права и привязка Telegram задаёт человек в панели; пишется в аудит.
    expect — состояние, показанное человеку в диалоге: если запись изменилась между диалогом и записью, отказ (нельзя «досыпать» чат в окне диалога)."""
    with _LOCK:
        data = _load()
        o = next((x for x in data["operators"] if x["id"] == body.get("id") and not x.get("revoked")), None)
        if not o:
            raise ApiError("Оператор не найден", HTTPStatus.NOT_FOUND, code="op.not_found")
        if expect is not None and (sorted(o.get("scopes", [])) != expect["scopes"] or o.get("telegram_chat_id") != expect["telegram_chat_id"]):
            raise ApiError("Оператор изменился, пока было открыто окно подтверждения; повторите действие", HTTPStatus.CONFLICT, code="op.changed")
        before = {"scopes": o["scopes"], "telegram_chat_id": o.get("telegram_chat_id")}
        issued = None
        if "scopes" in body:
            o["scopes"] = _check_scopes(body["scopes"])
            if "approve" in o["scopes"] and "approve" not in before["scopes"]:   # право одобрять выдаётся вместе с НОВЫМИ токеном и секретом TOTP
                token = TOKEN_PREFIX + secrets.token_urlsafe(32)
                o["token_hash"] = _hash(token)
                o["totp_secret"] = base64.b32encode(secrets.token_bytes(20)).decode()
                o["totp_last"], o["totp_fails"], o["totp_locked"] = 0, 0, False
                issued = {"token": token, "totp_secret": o["totp_secret"]}
        if "telegram_chat_id" in body:
            chat = _check_chat(body["telegram_chat_id"])
            if chat and any(x.get("telegram_chat_id") == chat and x["id"] != o["id"] and not x.get("revoked") for x in data["operators"]):
                raise ApiError("Этот Telegram-чат уже привязан к другому оператору", HTTPStatus.CONFLICT, code="op.chat_exists")
            o["telegram_chat_id"] = chat
        _save(data)
    audit.record("operator:settings", {"id": o["id"], "name": o["name"], "before": before,
                                       "after": {"scopes": o["scopes"], "telegram_chat_id": o.get("telegram_chat_id")}, "credentials_reissued": bool(issued)}, "ok")
    return {"operator": public(o), **(issued or {})}


# ---------------------------------------------------------------- проверка токена (удалённый API)

def authenticate(token):
    """Токен → запись оператора или None. Сравнение хешей за постоянное время; отозванные и просроченные не принимаются."""
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > TOKEN_MAX:
        return None
    h = _hash(token)
    now = time.time()
    found = None
    for o in _load()["operators"]:
        if o.get("revoked") or not o.get("token_hash"):
            continue
        if hmac.compare_digest(o["token_hash"], h):
            found = o
    if not found or (found.get("expires") and found["expires"] < now):
        return None
    return found


def by_chat(chat_id):
    """Оператор, к которому привязан Telegram-чат (личный), или None."""
    now = time.time()
    for o in _load()["operators"]:
        if not o.get("revoked") and o.get("telegram_chat_id") == chat_id and not (o.get("expires") and o["expires"] < now):
            return o
    return None


def touch(operator_id):
    with _LOCK:
        data = _load()
        for o in data["operators"]:
            if o["id"] == operator_id:
                if not o.get("last_seen") or time.time() - o["last_seen"] > 60:
                    o["last_seen"] = time.time()
                    _save(data)
                return

