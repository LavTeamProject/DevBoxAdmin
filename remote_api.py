"""Удалённый API панели для клиентов (Фаза 8, ADR-0003): агенты (`/agent/v1`) и операторы (`/operator/v1`).

Отдельный слушатель, ВЫКЛЮЧЕН по умолчанию; HTTP-API панели на 127.0.0.1 и сокет агентов не меняются. Адрес задаёт пользователь;
не-loopback адрес требует TLS и список разрешённых адресов (иначе не стартует). Токены — в реестрах шлюза (агенты) и `operators.py`.
Оператору доступны только чтение и одобрение/отклонение планов L2 (одобрение — токен с `approve` + TOTP + эхо хеша плана + глобальная
настройка); L3 удалённо одобрить нельзя. Всё, что ослабляет защиту (включить доступ, не-loopback адрес, удалённое одобрение, оператор
с правом `approve`), подтверждается человеком в системном диалоге на машине с панелью.
"""
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import agent_gateway
import audit
import operators
from core import DATA_DIR, ApiError

SETTINGS_FILE = os.path.join(DATA_DIR, "remote.json")
TLS_DIR = os.path.join(DATA_DIR, "remote-tls")
DEFAULTS = {"enabled": False, "bind": "127.0.0.1", "port": 8766, "tls": False, "allow": [], "remote_approval": False}
MAX_BODY = 64 * 1024
CONN_TIMEOUT = 15
MAX_CONNECTIONS = 32
REQUEST_DEADLINE = 30     # секунд на весь запрос целиком (заголовки + тело)
FAIL_LIMIT = 10          # неудачных проверок токена с одного адреса…
FAIL_WINDOW = 60         # …за это число секунд → блок
BLOCK_SECONDS = 300
OP_RATE_PER_MIN = 120
MAX_ALLOW = 50
_LOCK = threading.Lock()
SETTINGS_LOCK = threading.RLock()   # чтение-изменение-запись remote.json (диалог длится до 110 с: после него файл перечитывается)
_FAILS = {}              # ip -> [timestamps]
_BLOCKED = {}            # ip -> until
_OPCALLS = {}            # operator id -> [timestamps]
_STATE = {"server": None, "error": None, "addr": None}
_SLOTS = threading.BoundedSemaphore(MAX_CONNECTIONS)
_AUDIT_AT = {}           # ограничение частоты записей об отказах


# ---------------------------------------------------------------- настройки

def settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    out = dict(DEFAULTS)
    out.update({k: s[k] for k in DEFAULTS if k in s and type(s[k]) is type(DEFAULTS[k])})
    out["telegram"] = {"enabled": bool((s.get("telegram") or {}).get("enabled"))}
    return out


def update_settings(fn):
    """Атомарно: перечитать файл, изменить ТОЛЬКО свои ключи функцией fn(dict) и записать. Так устаревшая копия не затирает чужие свежие изменения."""
    with SETTINGS_LOCK:
        cur = settings()
        s = {k: cur[k] for k in DEFAULTS}
        s["telegram"] = {"enabled": cur["telegram"]["enabled"]}
        fn(s)
        _write(s)
        return s


def _write(s):
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SETTINGS_FILE)


def _is_loopback(addr):
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


MIN_PREFIX = {4: 8, 6: 32}   # шире — это «весь интернет»: 0.0.0.0/0, ::/0, 1.0.0.0/4 и т. п.


def _networks(allow):
    out = []
    for a in allow:
        try:
            n = ipaddress.ip_network(a, strict=False)
        except ValueError:
            raise ApiError(f"Неверный адрес или сеть в списке разрешённых: {str(a)[:40]}", code="remote.allow_invalid") from None
        if n.prefixlen < MIN_PREFIX[n.version]:
            raise ApiError(f"Сеть {n} слишком широкая (допустимо не шире /{MIN_PREFIX[4]} для IPv4)", code="remote.allow_wide", net=str(n))
        out.append(n)
    return out


def validate(s):
    """→ s или ApiError. Не-loopback адрес без TLS и без списка разрешённых адресов — запрещён."""
    try:
        ip = ipaddress.ip_address(s["bind"])
    except ValueError:
        raise ApiError("Адрес должен быть IP-адресом (например 127.0.0.1 или адрес в LAN)", code="remote.bind_invalid") from None
    if isinstance(s["port"], bool) or not 1024 <= s["port"] <= 65535 or s["port"] == 8765:
        raise ApiError("Порт: от 1024 до 65535 (не 8765 — он занят панелью)", code="remote.port_invalid")
    if len(s["allow"]) > MAX_ALLOW:
        raise ApiError(f"В списке разрешённых не более {MAX_ALLOW} записей", code="remote.allow_invalid")
    _networks(s["allow"])
    if not ip.is_loopback:
        if not s["tls"]:
            raise ApiError("Вне localhost нужен TLS: включите шифрование", code="remote.tls_required")
        if not s["allow"]:
            raise ApiError("Вне localhost нужен список разрешённых адресов (например 192.168.1.0/24)", code="remote.allow_required")
    return s


def _confirm(ru, en):
    """Ослабляющие защиту действия подтверждает человек в системном диалоге (как режим «кнопка в панели»). Нет канала — отказ."""
    import plans
    if plans.confirm_direct({"ru": ru, "en": en}) != "approve":
        raise ApiError("Действие не подтверждено в системном диалоге на машине с панелью", HTTPStatus.FORBIDDEN, code="remote.dialog_denied")


def _weaker(cur, new):
    """Что в переходе cur → new ослабляет защиту → [(ru, en, id)]. Диалог показывает это человеку, после диалога проверка повторяется на свежем состоянии."""
    w = []
    if new["enabled"] and not cur["enabled"]:
        w.append(("включить удалённый доступ к панели", "turn on remote access to the panel", "enable"))
    if new["enabled"] and not _is_loopback(new["bind"]) and (cur["bind"] != new["bind"] or not cur["enabled"]):
        w.append((f"принимать подключения из сети (адрес {new['bind']})", f"accept connections from the network (address {new['bind']})", "network"))
    if new["remote_approval"] and not cur["remote_approval"]:
        w.append(("разрешить операторам одобрять планы удалённо", "let operators approve plans remotely", "approval"))
    if new["enabled"] and not _is_loopback(new["bind"]) and (w or new["allow"] != cur["allow"]):   # итоговый список адресов человек видит в диалоге всегда
        w.append((f"разрешённые адреса: {', '.join(new['allow'])}; TLS: {'да' if new['tls'] else 'нет'}",
                  f"allowed addresses: {', '.join(new['allow'])}; TLS: {'yes' if new['tls'] else 'no'}", "allow"))
    return w


def set_settings(body):
    """POST /api/remote/settings {enabled?, bind?, port?, tls?, allow?, remote_approval?} (только localhost-API панели)."""
    cur = settings()
    changes = {}
    for k in DEFAULTS:
        if k in body:
            if type(body[k]) is not type(DEFAULTS[k]):
                raise ApiError(f"Неверный тип параметра {k}", code="remote.type_invalid", name=k)
            changes[k] = body[k]
    if "allow" in changes:
        changes["allow"] = [str(a).strip() for a in changes["allow"] if str(a).strip()]
    new = {**cur, **changes}
    validate(new)
    weaker = _weaker(cur, new)
    if weaker:
        _confirm("Service Admin: " + "; ".join(w[0] for w in weaker) + ".", "Service Admin: " + "; ".join(w[1] for w in weaker) + ".")
    shown = {w[2] for w in weaker}
    done = {}

    def _apply(s):   # на СВЕЖЕМ состоянии (диалог мог длиться минуты): пишем только то, что просили, и повторно проверяем «ослабление»
        fresh = {k: s[k] for k in DEFAULTS}
        merged = {**fresh, **changes}
        validate(merged)
        extra = {w[2] for w in _weaker(fresh, merged)} - shown
        if extra:
            raise ApiError("Настройки изменились, пока было открыто окно подтверждения; повторите действие", HTTPStatus.CONFLICT, code="remote.state_changed")
        s.update(changes)
        done.update(merged)
    update_settings(_apply)
    audit.record("remote:settings", {"before": {k: cur[k] for k in DEFAULTS}, "after": {k: done[k] for k in DEFAULTS}}, "ok")
    apply()
    return status()


# ---------------------------------------------------------------- TLS

def _fingerprint(path):
    import ssl as _ssl
    with open(path, encoding="ascii") as f:
        der = _ssl.PEM_cert_to_DER_cert(f.read())
    return hashlib.sha256(der).hexdigest()


def ensure_cert():
    """Самоподписанный сертификат RSA-2048 (openssl; ECDSA не берём: старый LibreSSL в системном Python macOS его не согласует) в ~/.service-admin/remote-tls (0600). → (cert, key)."""
    cert, key = os.path.join(TLS_DIR, "cert.pem"), os.path.join(TLS_DIR, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    exe = shutil.which("openssl")
    if not exe:
        raise ApiError("Для TLS нужен openssl (не найден)", HTTPStatus.CONFLICT, code="remote.openssl_missing")
    os.makedirs(TLS_DIR, mode=0o700, exist_ok=True)
    old = os.umask(0o177)
    try:
        r = subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825",
                            "-subj", "/CN=service-admin", "-keyout", key, "-out", cert], capture_output=True, timeout=60)
    finally:
        os.umask(old)
    if r.returncode != 0 or not os.path.exists(cert):
        raise ApiError("Не удалось создать сертификат TLS", HTTPStatus.CONFLICT, code="remote.cert_failed")
    os.chmod(key, 0o600)
    return cert, key


# ---------------------------------------------------------------- защита от перебора

def _allowed_ip(ip, s):
    if _is_loopback(ip):
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in _networks(s["allow"]))


def _blocked(ip, now=None):
    now = now if now is not None else time.time()
    with _LOCK:
        until = _BLOCKED.get(ip)
        if until and until > now:
            return True
        _BLOCKED.pop(ip, None)
        return False


def _fail(ip, now=None):
    now = now if now is not None else time.time()
    with _LOCK:
        lst = [t for t in _FAILS.get(ip, []) if now - t < FAIL_WINDOW] + [now]
        _FAILS[ip] = lst
        if len(lst) >= FAIL_LIMIT and not _is_loopback(ip):   # за обратным прокси все клиенты — 127.0.0.1: блок по адресу отключил бы всех, защищают энтропия токена и блок TOTP
            _BLOCKED[ip] = now + BLOCK_SECONDS
            _FAILS.pop(ip, None)
        if len(_FAILS) > 5000:   # память не растёт бесконечно при переборе с множества адресов
            _FAILS.clear()


def _rate_ok(key, limit=OP_RATE_PER_MIN, now=None):
    now = now if now is not None else time.time()
    with _LOCK:
        lst = [t for t in _OPCALLS.get(key, []) if now - t < 60]
        if len(lst) >= limit:
            _OPCALLS[key] = lst
            return False
        lst.append(now)
        _OPCALLS[key] = lst
        return True


def _audit_limited(action, params, result, key):
    now = time.time()
    with _LOCK:
        if now - _AUDIT_AT.get((action, key), 0) < 30:
            return
        _AUDIT_AT[(action, key)] = now
        if len(_AUDIT_AT) > 5000:
            _AUDIT_AT.clear()
    audit.record(action, params, result)


# ---------------------------------------------------------------- обработка запросов (чистые функции — их же вызывают тесты)

def _bearer(headers):
    h = headers.get("Authorization") or ""
    return h[7:].strip() if h[:7].lower() == "bearer " else None


def _err(status, code, message):
    return status, {"ok": False, "error": {"code": code, "message": message}}


def _gw_status(resp):
    if resp.get("ok"):
        return HTTPStatus.OK
    return {"unauthorized": 401, "forbidden": 403, "rate_limited": 429, "invalid_params": 400, "bad_request": 400, "unknown_tool": 404,
            "too_large": 413}.get((resp.get("error") or {}).get("code"), 200)


def handle_agent(method, path, token, body):
    """→ (status, json). Токен агента проверяет сам шлюз (тот же код, что и для сокета)."""
    if method == "GET" and path == "/agent/v1/tools":
        resp = agent_gateway.handle({"token": token, "op": "list_tools"})
    elif method == "POST" and path == "/agent/v1/call":
        if not isinstance(body, dict) or not isinstance(body.get("tool"), str):
            return _err(400, "bad_request", "body must be {\"tool\": string, \"params\": object}")
        resp = agent_gateway.handle({"token": token, "op": "call", "tool": body["tool"], "params": body.get("params") or {}})
    else:
        return _err(404, "not_found", "unknown endpoint")
    return _gw_status(resp), resp


def handle_operator(method, path, query, operator, body):
    """→ (status, json). `operator` уже проверен по токену; здесь права, TOTP, эхо хеша и глобальная настройка."""
    import plans
    scopes = operator.get("scopes") or []
    if not _rate_ok("op:" + operator["id"]):
        return _err(429, "rate_limited", f"more than {OP_RATE_PER_MIN} requests per minute")
    if "read" not in scopes and "approve" not in scopes:
        return _err(403, "forbidden", "the operator has no rights")
    try:
        if method == "GET" and path == "/operator/v1/status":
            pl = plans.list_plans()
            return 200, {"ok": True, "result": {"operator": operator["name"], "scopes": scopes, "pending": pl["pending"],
                                                "remote_approval": settings()["remote_approval"],
                                                "agents": len([a for a in agent_gateway._load()["agents"] if not a.get("revoked")])}}  # noqa: SLF001
        if method == "GET" and path == "/operator/v1/plans":
            return 200, {"ok": True, "result": {"plans": plans.list_plans()["plans"], "remote_approval": settings()["remote_approval"]}}
        if method == "GET" and path == "/operator/v1/audit":
            q = {k: v[0] for k, v in query.items()}
            lim = str(q.get("limit") or "50")
            q["limit"] = str(min(int(lim), 200)) if lim.isascii() and lim.isdecimal() else "50"
            return 200, {"ok": True, "result": audit.read(q)}
        if method == "POST" and path == "/operator/v1/plans/reject":
            if "approve" not in scopes:
                return _err(403, "forbidden", "needs the approve right")
            if not isinstance(body, dict) or not isinstance(body.get("id"), str):
                return _err(400, "bad_request", "body must be {\"id\": string}")
            return 200, {"ok": True, "result": plans.reject_remote(operator, body["id"])}
        if method == "POST" and path == "/operator/v1/plans/approve":
            if "approve" not in scopes:
                return _err(403, "forbidden", "needs the approve right")
            if not settings()["remote_approval"]:
                return _err(403, "remote_approval_off", "remote approval is switched off in the panel settings")
            if not isinstance(body, dict) or not isinstance(body.get("id"), str) or not isinstance(body.get("digest"), str):
                return _err(400, "bad_request", "body must be {\"id\", \"digest\", \"totp\"}")
            if operators.is_locked(operator["id"]):
                return _err(403, "totp_locked", "approval is locked after repeated wrong codes; unlock the operator in the panel")
            if not operators.verify_totp(operator["id"], body.get("totp")):
                _audit_limited("remote:approve", {"operator": operator["name"], "plan": body["id"][:12]}, "error: bad or reused TOTP code", operator["id"])
                return _err(403, "totp_invalid", "the TOTP code is wrong or was already used")
            return 200, {"ok": True, "result": plans.approve_remote(operator, body["id"], body["digest"])}
    except ApiError as e:
        return _err(int(e.status), e.code or "failed", str(e))
    return _err(404, "not_found", "unknown endpoint")


# ---------------------------------------------------------------- HTTP-слушатель

class _Handler(BaseHTTPRequestHandler):
    server_version = "ServiceAdminRemote"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    timeout = CONN_TIMEOUT

    def setup(self):
        super().setup()
        # общий срок на весь запрос: «капельная» отправка (slowloris) не держит поток дольше REQUEST_DEADLINE
        self._deadline = threading.Timer(REQUEST_DEADLINE, self._abort)
        self._deadline.daemon = True
        self._deadline.start()

    def _abort(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self._deadline.cancel()
        self._deadline = None        # разрываем цикл handler ↔ Timer, иначе сокет освобождает только сборщик циклов
        super().finish()

    def log_message(self, *a):  # noqa: D401 — журнал ведёт аудит, а не stderr
        pass

    def _send(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _serve(self, method):
        try:
            self._route(method)
        except Exception as e:  # noqa: BLE001 — один запрос не должен ронять слушатель
            audit.record("remote:error", {"path": self.path[:80]}, f"error: {str(e)[:120]}")
            self._send(500, {"ok": False, "error": {"code": "internal", "message": "internal error"}})

    def _route(self, method):
        ip = self.client_address[0]
        s = settings()
        if not _allowed_ip(ip, s):
            _audit_limited("remote:denied", {"ip": ip}, "error: address not allowed", ip)
            return self._send(403, {"ok": False, "error": {"code": "forbidden", "message": "address not allowed"}})
        if _blocked(ip):
            return self._send(429, {"ok": False, "error": {"code": "blocked", "message": "too many failed attempts; wait a few minutes"}})
        u = urlparse(self.path)
        body = None
        if method == "POST":
            ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._send(413, {"ok": False, "error": {"code": "too_large", "message": f"body larger than {MAX_BODY} bytes"}})
            if ct != "application/json":
                return self._send(415, {"ok": False, "error": {"code": "bad_request", "message": "Content-Type must be application/json"}})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"ok": False, "error": {"code": "bad_request", "message": "invalid JSON"}})
        if self._deadline is not None:
            self._deadline.cancel()   # запрос принят целиком; долгая работа инструмента не должна обрываться этим сроком
        token = _bearer(self.headers)
        if u.path.startswith("/agent/v1/"):
            agent = agent_gateway.authenticate(token) if token else None
            if not agent:
                _fail(ip)
                _audit_limited("remote:auth_failed", {"ip": ip, "path": u.path}, "error: unknown agent token", ip)
                return self._send(401, {"ok": False, "error": {"code": "unauthorized", "message": "unknown, revoked or expired agent credential"}})
            status, obj = handle_agent(method, u.path, token, body)
            who = "agent:" + agent["name"]
        elif u.path.startswith("/operator/v1/"):
            op = operators.authenticate(token) if token else None
            if not op:
                _fail(ip)
                _audit_limited("remote:auth_failed", {"ip": ip, "path": u.path}, "error: unknown operator token", ip)
                return self._send(401, {"ok": False, "error": {"code": "unauthorized", "message": "unknown, revoked or expired operator credential"}})
            operators.touch(op["id"])
            audit.INITIATOR.set("operator:" + op["name"])
            status, obj = handle_operator(method, u.path, parse_qs(u.query), op, body)
            who = "operator:" + op["name"]
        else:
            return self._send(404, {"ok": False, "error": {"code": "not_found", "message": "unknown endpoint"}})
        if method == "POST" or status >= 400:
            audit.record("remote:request", {"ip": ip, "path": u.path, "status": int(status)}, "ok" if status < 400 else f"error: {status}", extra={"by": who})
        self._send(status, obj)

    def do_GET(self):  # noqa: N802
        self._serve("GET")

    def do_POST(self):  # noqa: N802
        self._serve("POST")


class _Server(ThreadingHTTPServer):
    """Ограничения ДО разбора запроса: адрес по списку, число соединений; TLS-рукопожатие — в рабочем потоке с таймаутом
    (иначе одно «молчащее» TCP-соединение блокирует accept() и всех остальных)."""
    daemon_threads = True
    request_queue_size = 32
    ssl_ctx = None
    _held = None

    def verify_request(self, request, client_address):
        try:
            if not _allowed_ip(client_address[0], settings()):
                _audit_limited("remote:denied", {"ip": client_address[0]}, "error: address not allowed", client_address[0])
                return False
        except Exception:  # noqa: BLE001 — исключение здесь убило бы serve_forever; при сомнении соединение закрываем
            return False
        if not _SLOTS.acquire(blocking=False):
            return False
        with _LOCK:
            if self._held is None:
                self._held = set()
            self._held.add(id(request))   # слот освободим в shutdown_request (у сокета нельзя завести свой атрибут)
        return True

    def finish_request(self, request, client_address):
        request.settimeout(CONN_TIMEOUT)
        conn = self.ssl_ctx.wrap_socket(request, server_side=True) if self.ssl_ctx is not None else request
        try:
            super().finish_request(conn, client_address)
        finally:
            if conn is not request:   # wrap_socket отсоединяет дескриптор исходного сокета: закрывать надо обёрнутый
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                conn.close()

    def shutdown_request(self, request):
        with _LOCK:
            held = self._held is not None and id(request) in self._held
            if held:
                self._held.discard(id(request))
        if held:
            _SLOTS.release()
        super().shutdown_request(request)

    def handle_error(self, request, client_address):   # обрыв/ошибка TLS чужого клиента — не повод писать трассировку в журнал панели
        pass


# ---------------------------------------------------------------- запуск / остановка

def stop():
    srv = _STATE.get("server")
    if srv:
        try:
            srv.shutdown()
            srv.server_close()
        except OSError:
            pass
    _STATE.update(server=None, addr=None)


def apply():
    """Привести слушатель в соответствие с настройками (вызывается при старте панели и при смене настроек)."""
    stop()
    _STATE["error"] = None
    s = settings()
    if not s["enabled"]:
        return
    try:
        validate(s)
        srv = _Server((s["bind"], s["port"]), _Handler)
        if s["tls"]:
            cert, key = ensure_cert()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(cert, key)
            srv.ssl_ctx = ctx
    except ApiError as e:
        _STATE["error"] = e.code or str(e)
        return
    except OSError as e:
        _STATE["error"] = f"bind: {e}"
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _STATE.update(server=srv, addr=f"{s['bind']}:{srv.server_address[1]}")


# ---------------------------------------------------------------- состояние и выдача токена (панель, localhost)

def status(q=None):
    s = settings()
    fp = None
    cert = os.path.join(TLS_DIR, "cert.pem")
    if s["tls"] and os.path.exists(cert):
        try:
            fp = _fingerprint(cert)
        except (OSError, ValueError):
            fp = None
    return {"settings": s, "running": bool(_STATE.get("server")), "address": _STATE.get("addr"), "error": _STATE.get("error"),
            "tls_fingerprint": fp, "scheme": "https" if s["tls"] else "http", "limits": {"body": MAX_BODY, "fail_limit": FAIL_LIMIT, "op_rate": OP_RATE_PER_MIN}}


def issue_agent_token(body):
    """POST {id} — ротация секрета агента с выдачей нового токена ОДИН раз (для клиента на другой машине). Старый токен перестаёт действовать."""
    aid = body.get("id")
    if not isinstance(aid, str) or not re.fullmatch(r"a[0-9a-f]{6}", aid):
        raise ApiError("Неверный id агента", code="gw.remote_id")
    ag = next((a for a in agent_gateway._load()["agents"] if a["id"] == aid and not a.get("revoked")), None)  # noqa: SLF001
    if not ag:
        raise ApiError("Агент не найден", HTTPStatus.NOT_FOUND, code="gw.not_found")
    # токен возвращается вызывающему и открывает инструменты агента его уровня (L2 — предлагать изменения, L3 — операции CI): без человека не выдаём
    _confirm(f"Service Admin: выдать НОВЫЙ токен агента «{ag['name']}» (уровень {ag['level']}); прежний перестанет работать.",
             f"Service Admin: issue a NEW token for the agent “{ag['name']}” (level {ag['level']}); the old one stops working.")
    agent_gateway.rotate({"id": aid})
    with open(os.path.join(agent_gateway.TOKEN_DIR, aid + ".token"), encoding="utf-8") as f:
        return {"id": aid, "token": f.read().strip()}


# ---------------------------------------------------------------- операторы: изменения, дающие право одобрять, подтверждает человек (диалог)

def _op_text(name, ru, en):
    return (f"Service Admin: оператор «{name}»: {ru}.", f"Service Admin: operator “{name}”: {en}.")


def op_create(body):
    scopes = body.get("scopes") or []
    chat = body.get("telegram_chat_id")
    if "approve" in scopes or chat:   # право одобрять или привязка чата (по Telegram достаточно чата и кода) — человек видит и то и другое
        _confirm(*_op_text(str(body.get("name") or "")[:40], f"создать (права: {', '.join(scopes) or 'read'}; Telegram-чат: {chat or '—'}); токен и секрет TOTP получит вызывающий",
                           f"create (rights: {', '.join(scopes) or 'read'}; Telegram chat: {chat or '—'}); the caller receives the token and the TOTP secret"))
    return operators.create(body)


def _find_op(oid):
    return next((x for x in operators._load()["operators"] if x["id"] == oid and not x.get("revoked")), None)  # noqa: SLF001


def op_rotate(body):
    """Ротация отдаёт новый токен и секрет TOTP вызывающему — всегда через диалог (иначе HTTP-агент забрал бы чужие учётные данные)."""
    o = _find_op(body.get("id"))
    if o:
        _confirm(*_op_text(o["name"], "выдать НОВЫЕ токен и секрет TOTP (прежние перестанут работать)", "issue a NEW token and TOTP secret (the old ones stop working)"))
    return operators.rotate(body)


def op_unlock(body):
    """Снятие блокировки TOTP возвращает возможность подбирать код: с токеном оператора и локальным HTTP-агентом это было бы обходом — через диалог."""
    o = _find_op(body.get("id"))
    if o:
        _confirm(*_op_text(o["name"], "снять блокировку одобрения (после неверных кодов TOTP)", "lift the approval lock (after wrong TOTP codes)"))
    return operators.unlock(body)


def op_set(body):
    """Права и привязка чата: любая привязка/смена Telegram-чата и любое изменение прав у оператора, который имеет или получит право одобрять, — через диалог.
    Состояние, показанное в диалоге, проверяется под блокировкой при записи (между диалогом и записью оператор не должен измениться)."""
    o = _find_op(body.get("id"))
    expect = None
    if o:
        old = o.get("scopes", [])
        new = body.get("scopes", old)
        new = new if isinstance(new, list) else []
        chat_changed = "telegram_chat_id" in body and (body.get("telegram_chat_id") or None) != o.get("telegram_chat_id")
        scopes_changed = "scopes" in body and sorted(set(new)) != sorted(set(old))
        if chat_changed or (scopes_changed and ("approve" in old or "approve" in new)):
            parts = []
            if scopes_changed:
                grant = "approve" in new and "approve" not in old
                parts.append((f"права: {', '.join(sorted(set(new))) or '—'}" + ("; будут выданы НОВЫЕ токен и секрет TOTP; Telegram-чат: " + str(body.get("telegram_chat_id", o.get("telegram_chat_id")) or "—") if grant else ""),
                              f"rights: {', '.join(sorted(set(new))) or '—'}" + ("; a NEW token and TOTP secret will be issued; Telegram chat: " + str(body.get("telegram_chat_id", o.get("telegram_chat_id")) or "—") if grant else "")))
            if chat_changed:
                parts.append((f"привязать Telegram-чат {body.get('telegram_chat_id') or '—'}", f"bind Telegram chat {body.get('telegram_chat_id') or '—'}"))
            _confirm(*_op_text(o["name"], "; ".join(p[0] for p in parts), "; ".join(p[1] for p in parts)))
            expect = {"scopes": sorted(old), "telegram_chat_id": o.get("telegram_chat_id")}
    return operators.set_operator(body, expect=expect)


def agent_set(body):
    """POST /api/agent-gateway/settings: повышение уровня агента и «не спрашивать» (auto_approve) — через системное окно, как и режим «кнопка в панели»:
    без этого локальный HTTP-клиент создал бы самоодобряющего агента без участия человека. Понижение уровня и отключение — без окна."""
    ag = next((a for a in agent_gateway._load()["agents"] if a["id"] == body.get("id") and not a.get("revoked")), None)  # noqa: SLF001
    if ag:
        rank = agent_gateway.LEVELS
        new_level = body.get("level", ag["level"])
        raises = new_level in rank and rank[new_level] > rank.get(ag["level"], 0)
        auto = body.get("auto_approve")
        gains_auto = isinstance(auto, list) and "L2" in auto and "L2" not in (ag.get("auto_approve") or [])
        gains_run = body.get("auto_run") is True and not ag.get("auto_run")
        if raises or gains_auto or gains_run:
            what_ru = ([f"поднять уровень до {new_level}"] if raises else []) + (["включить «не спрашивать» для планов L2"] if gains_auto else []) \
                + (["запускать тесты, линтер, сборку и установку зависимостей проекта без подтверждения"] if gains_run else [])
            what_en = ([f"raise the level to {new_level}"] if raises else []) + (["turn on “don't ask” for L2 plans"] if gains_auto else []) \
                + (["run project tests, lint, build and dependency install without approval"] if gains_run else [])
            _confirm(f"Service Admin: агент «{ag['name']}»: {'; '.join(what_ru)}.", f"Service Admin: agent “{ag['name']}”: {'; '.join(what_en)}.")
    return agent_gateway.set_agent(body)
