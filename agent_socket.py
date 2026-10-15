"""Unix-сокет для MCP-процессов агентов (Фаза 4.0): ~/.service-admin/agent.sock, права 0600, папка 0700.

Сетевого порта нет. Через сокет доступен ТОЛЬКО шлюз агентов (`agent_gateway.handle`), а не HTTP API панели.
Протокол: одна строка JSON-запроса → одна строка JSON-ответа, одно соединение на запрос; размер запроса ограничен.
Запрос — {"token", "op": "list_tools"|"call", "tool"?, "params"?} (см. agent_gateway.handle).
"""
import json
import os
import socket
import socketserver
import threading

import agent_gateway
from core import DATA_DIR

MAX_REQUEST = 64 * 1024
READ_TIMEOUT = 10
MAX_PATH = 100  # sun_path на macOS — 104 байта


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(READ_TIMEOUT)
        try:
            line = self.rfile.readline(MAX_REQUEST + 1)
        except (socket.timeout, OSError):
            return
        if len(line) > MAX_REQUEST:
            resp = agent_gateway._err("too_large", f"request larger than {MAX_REQUEST} bytes")  # noqa: SLF001
        else:
            try:
                resp = agent_gateway.handle(json.loads(line))
            except ValueError:
                resp = agent_gateway._err("bad_request", "invalid JSON")  # noqa: SLF001
            except Exception as e:  # noqa: BLE001 - сокет не должен падать от одного запроса
                resp = agent_gateway._err("internal", str(e)[:200])  # noqa: SLF001
        try:
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode() + b"\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _stale(path):
    """Сокет-файл остался от прежнего запуска: живой ли кто-то на нём?"""
    probe = socket.socket(socket.AF_UNIX)
    probe.settimeout(1)
    try:
        probe.connect(path)
        return False
    except OSError:
        return True
    finally:
        probe.close()


def start(path=None):
    """Запустить сервер сокета в фоновом потоке. Возвращает (server, error): error — строка, если запуск не удался."""
    path = path or agent_gateway.SOCKET_PATH
    if len(path.encode()) > MAX_PATH:
        return None, f"socket path too long ({len(path.encode())} > {MAX_PATH} bytes)"
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    if os.path.exists(path):
        if not _stale(path):
            return None, "another panel instance already listens on the agent socket"
        os.unlink(path)
    old = os.umask(0o177)  # сокет создаётся сразу с 0600
    try:
        server = _Server(path, _Handler)
    except OSError as e:
        return None, str(e)
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, None
