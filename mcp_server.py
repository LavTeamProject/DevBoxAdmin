#!/usr/bin/env python3
"""MCP-сервер Service Admin (stdio, JSON-RPC 2.0) — тонкий мост между ИИ-агентом и шлюзом панели.

Агент запускает его сам: `python3 mcp_server.py --agent <id>` (команду и готовую конфигурацию показывает страница
«Подключение агентов»). Процесс ничего не делает с машиной: он читает секрет агента из
~/.service-admin/agents/<id>.token и пересылает вызовы по Unix-сокету панели (~/.service-admin/agent.sock).
Список инструментов и права определяет ПАНЕЛЬ. Если панель не запущена, процесс её НЕ запускает, а возвращает
понятную ошибку. Только стандартная библиотека. На stdout — только сообщения протокола; логи — в stderr.
"""
import argparse
import json
import os
import socket
import sys

SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "service-admin", "version": "1.0.0"}
INSTRUCTIONS = ("Access to this computer's setup state through the Service Admin panel. Use inspect_system and inspect_diagnostics first. "
                "Level L1 tools only read. At level L2/L3 you can PROPOSE a change (plan_changes); it runs only after a human approves it, "
                "once, and then you check it with verify_plan. Never ask the human to type an administrator password anywhere except in their own terminal.")
CONNECT_TIMEOUT = 5
CALL_TIMEOUT = 120
MAX_RESPONSE = 4 * 1024 * 1024


def home_dir():
    return os.environ.get("SERVICE_ADMIN_HOME") or os.path.join(os.path.expanduser("~"), ".service-admin")


class PanelError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def panel_call(agent_id, payload):
    """Отправить запрос шлюзу панели; вернуть result или бросить PanelError."""
    token_file = os.path.join(home_dir(), "agents", agent_id + ".token")
    try:
        with open(token_file) as f:
            token = f.read().strip()
    except OSError:
        raise PanelError("credential_missing", "Agent credential file not found: the agent was revoked or never registered. "
                                              "Register it again on the 'Agent connections' page of the panel.") from None
    path = os.path.join(home_dir(), "agent.sock")
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(CONNECT_TIMEOUT)
    try:
        s.connect(path)
    except OSError:
        raise PanelError("panel_unavailable", "The Service Admin panel is not running (agent socket is not reachable). "
                                              "Start the panel and try again; this process does not start it.") from None
    try:
        s.settimeout(CALL_TIMEOUT)
        s.sendall(json.dumps({"token": token, **payload}).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_RESPONSE:
                raise PanelError("too_large", "Panel response is too large")
    except OSError as e:
        raise PanelError("io_error", f"Communication with the panel failed: {e}") from None
    finally:
        s.close()
    try:
        resp = json.loads(buf)
    except ValueError:
        raise PanelError("bad_response", "The panel returned an invalid response") from None
    if not resp.get("ok"):
        err = resp.get("error") or {}
        raise PanelError(err.get("code", "failed"), err.get("message", "request failed"))
    return resp["result"]


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(agent_id, msg):
    """Обработать одно сообщение; ответ — через reply(). Уведомления (без id) ответа не получают."""
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    is_request = "id" in msg
    if not isinstance(method, str):
        if is_request:
            reply(msg_id, error={"code": -32600, "message": "Invalid Request"})
        return
    if method == "initialize":
        asked = params.get("protocolVersion")
        reply(msg_id, {"protocolVersion": asked if asked in SUPPORTED else SUPPORTED[0],
                       "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    elif method == "ping":
        reply(msg_id, {})
    elif method == "tools/list":
        try:
            reply(msg_id, panel_call(agent_id, {"op": "list_tools"}))
        except PanelError as e:
            reply(msg_id, error={"code": -32000, "message": e.message, "data": {"code": e.code}})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            reply(msg_id, error={"code": -32602, "message": "Invalid params: 'name' (string) and 'arguments' (object) are required"})
            return
        try:
            result = panel_call(agent_id, {"op": "call", "tool": name, "params": args})
            reply(msg_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                           "structuredContent": result, "isError": False})
        except PanelError as e:
            if e.code in ("unknown_tool", "invalid_params"):  # ошибка вызова — протокольная, не ошибка выполнения
                reply(msg_id, error={"code": -32602, "message": e.message, "data": {"code": e.code}})
            else:
                reply(msg_id, {"content": [{"type": "text", "text": f"{e.code}: {e.message}"}], "isError": True})
    elif is_request:
        reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})
    # неизвестное уведомление (notifications/initialized и т. п.) — игнорируем


def main():
    ap = argparse.ArgumentParser(description="Service Admin MCP server (stdio)")
    ap.add_argument("--agent", required=True, help="agent id from the Agent connections page")
    args = ap.parse_args()
    if not args.agent.replace("-", "").isalnum() or len(args.agent) > 20:
        sys.stderr.write("invalid agent id\n")
        return 2
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        if not isinstance(msg, dict):  # батчи (массивы) в stdio-транспорте MCP не используются
            reply(None, error={"code": -32600, "message": "Invalid Request: batches are not supported"})
            continue
        try:
            handle(args.agent, msg)
        except Exception as e:  # noqa: BLE001 - процесс не должен падать от одного сообщения
            sys.stderr.write(f"internal error: {e}\n")
            if "id" in msg:
                reply(msg.get("id"), error={"code": -32603, "message": "Internal error"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
