#!/usr/bin/env python3
"""Service Admin — dashboard lokal untuk mengelola Mac dev environment:
brew services, aplikasi Homebrew, Docker, Herd, bahasa pemrograman
(PHP, Node.js, Python, Go, Rust, Java, Ruby, ...), statistik sistem, dan konfigurasi zsh.

Jalankan:  python3 server.py  [--port 8765]
Lalu buka: http://127.0.0.1:8765

Hanya bind ke 127.0.0.1, tanpa dependensi eksternal (stdlib saja).
"""
import argparse
import json
import os
import sys
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import agent_gateway
import agent_socket
import operators
import remote_api
import telegram_bot
import agent_tasks
import agents
import audit
import backups
import brewsvc
import dockerx
import files
import gitops
import herdphp
import mobile
import mobile_ops
import operations
import plans
import profiles
import projects
import ptyterm
import runner_spawn
import runners
import runs
import runtimes
import platform_info
import report
import setup
import snapshots
import stats
import svc
import uihelpers
import vm
from core import ApiError, cancel_job, get_job, list_jobs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


# ---------------------------------------------------------------- services


# ---------------------------------------------------------------- apps (Homebrew)


# ---------------------------------------------------------------- PHP


# ---------------------------------------------------------------- Node.js (nvm)


# ---------------------------------------------------------------- Herd (situs, HTTPS, proxy)


# ---------------------------------------------------------------- Herd: aplikasi Laravel baru


# ---------------------------------------------------------------- zsh config


# ---------------------------------------------------------------- terminal


# ---------------------------------------------------------------- sidebar


# ---------------------------------------------------------------- HTTP

GET_ROUTES = {
    "/api/runtime": setup.runtime_info,
    "/api/platform": platform_info.report,
    "/api/report": report.build,
    "/api/setup": setup.status,
    "/api/audit": audit.read,
    "/api/operations": operations.catalog,
    "/api/plans": plans.list_plans,
    "/api/agent-gateway": agent_gateway.list_agents,
    "/api/agent-gateway/remote": agent_gateway.remote_info,
    "/api/remote": remote_api.status,
    "/api/operators": operators.list_operators,
    "/api/telegram": telegram_bot.status,
    "/api/backups": backups.status,
    "/api/vms": vm.overview,
    "/api/runners": runners.status,
    "/api/runs": runs.history,
    "/api/runs/log": runs.run_log,
    "/api/gh/workflows": runs.workflows,
    "/api/gh/runs": runs.gh_runs,
    "/api/agents/tasks": agent_tasks.list_tasks,
    "/api/agents/task/changes": agent_tasks.changes,
    "/api/agents/task/diff": agent_tasks.diff,
    "/api/profiles/plan": profiles.plan,
    "/api/mobile/screenshot": mobile_ops.screenshot,
    "/api/snapshots": snapshots.list_snapshots,
    "/api/snapshots/get": snapshots.get,
    "/api/snapshots/diff": snapshots.diff,
    "/api/stats": lambda q: stats.SAMPLER.snapshot(int(q.get("since", 0) or 0)),
    "/api/services": lambda q: {"services": brewsvc.list_services()},
    "/api/services/catalog": svc.catalog,
    "/api/recommend": svc.recommendations,
    "/api/services/detail": lambda q: svc.service_detail(q, brewsvc.known_service),
    "/api/services/config": svc.config_read,
    "/api/cloudflared": svc.cf_info,
    "/api/logs": brewsvc.service_logs,
    "/api/apps": lambda q: brewsvc.list_apps(),
    "/api/apps/search": brewsvc.search_apps,
    "/api/php": lambda q: herdphp.php_info(),
    "/api/node": lambda q: herdphp.node_info(),
    "/api/node/remote": lambda q: herdphp.node_remote(),
    "/api/runtimes": uihelpers.nav_info,
    "/api/lang": runtimes.lang_info,
    "/api/herd": lambda q: herdphp.herd_info(),
    "/api/herd/logs": herdphp.herd_logs,
    "/api/herd/suggest": herdphp.herd_suggest,
    "/api/herd/new-options": herdphp.herd_new_options,
    "/api/docker": dockerx.overview,
    "/api/docker/stats": dockerx.stats,
    "/api/docker/disk": dockerx.disk,
    "/api/docker/networks": dockerx.networks,
    "/api/docker/inspect": dockerx.inspect,
    "/api/docker/logs": dockerx.logs,
    "/api/docker/project-logs": dockerx.project_logs,
    "/api/docker/compose": dockerx.compose_read,
    "/api/docker/ports": dockerx.ports_check,
    "/api/docker/contexts": dockerx.contexts,
    "/api/files": files.list_files,
    "/api/files/read": uihelpers.file_read,
    "/api/files/backup": files.read_backup,
    "/api/ssh/keys": files.ssh_keys,
    "/api/git/identity": files.git_identity,
    "/api/jobs": list_jobs,
    "/api/terminal/apps": uihelpers.terminal_apps,
    "/api/pty/read": ptyterm.read,
    "/api/pty/list": ptyterm.list_sessions,
    "/api/pty/peek": ptyterm.peek,
    "/api/profiles": profiles.catalog,
    "/api/mobile": mobile.mobile_info,
    "/api/mobile/runtimes": mobile_ops.runtimes_deletable,
    "/api/mobile/flutter/projects": lambda q: {"projects": mobile.flutter_projects()},
    "/api/projects": projects.list_projects,
    "/api/projects/scan": projects.scan,
    "/api/projects/summary": projects.project_summary,
    "/api/projects/detail": uihelpers.project_detail_w,
    "/api/projects/diff": projects.project_diff,
    "/api/projects/diffstat": projects.project_diffstat,
    "/api/projects/editors": lambda q: {"editors": herdphp.installed_editors()},
    "/api/projects/github": projects.github_info,
    "/api/agents": agents.sessions_info,
    "/api/job": lambda q: get_job(q.get("id", ""), int(q.get("offset", 0) or 0)),
}
POST_ROUTES = {
    "/api/action": brewsvc.service_action,
    "/api/terminal/open": uihelpers.open_in_terminal,
    "/api/setup/install": setup.install,
    "/api/profiles/install": profiles.install,
    "/api/mobile/op": mobile_ops.run_op,
    "/api/agent-gateway/register": agent_gateway.register,
    "/api/agent-gateway/revoke": agent_gateway.revoke,
    "/api/agent-gateway/rotate": agent_gateway.rotate,
    "/api/agent-gateway/settings": remote_api.agent_set,
    "/api/remote/settings": remote_api.set_settings,
    "/api/remote/agent-token": remote_api.issue_agent_token,
    "/api/operators/create": remote_api.op_create,
    "/api/operators/rotate": remote_api.op_rotate,
    "/api/operators/revoke": operators.revoke,
    "/api/operators/unlock": remote_api.op_unlock,
    "/api/operators/settings": remote_api.op_set,
    "/api/telegram/settings": telegram_bot.set_settings,
    "/api/telegram/check": telegram_bot.check,
    "/api/plans/approve": plans.approve,
    "/api/plans/reject": plans.reject,
    "/api/plans/policy": plans.set_policy,
    "/api/backups/config": backups.set_config,
    "/api/backups/run": backups.start,
    "/api/vms/op": vm.run_op,
    "/api/vms/install-deps": vm.install_deps,
    "/api/runners/install": runners.install,
    "/api/runners/spawn": runner_spawn.start_http,
    "/api/runners/selftest": runner_spawn.selftest_http,
    "/api/runners/source/test": runners.test_source,
    "/api/runners/source/add": runners.add_source,
    "/api/runners/source/remove": runners.remove_source,
    "/api/backups/verify": backups.verify,
    "/api/backups/restore": backups.restore,
    "/api/runs/start": runs.start,
    "/api/gh/workflow_run": runs.workflow_run,
    "/api/gh/run_cancel": runs.run_cancel,
    "/api/gh/run_rerun": runs.run_rerun,
    "/api/agents/task/create": agent_tasks.create,
    "/api/agents/task/start": agent_tasks.start,
    "/api/agents/task/stop": agent_tasks.stop,
    "/api/agents/task/send": agent_tasks.send,
    "/api/agents/task/remove": agent_tasks.remove,
    "/api/agents/task/merge": agent_tasks.merge,
    "/api/git/op": lambda b: gitops.run_op(b, herdphp.EDITORS),
    "/api/projects/add": projects.registry_add,
    "/api/projects/remove": projects.registry_remove,
    "/api/projects/preset": lambda b: projects.preset_set(b, set(herdphp.EDITORS)),
    "/api/snapshots/create": snapshots.create,
    "/api/snapshots/delete": snapshots.delete,
    "/api/pty/new": ptyterm.new_session,
    "/api/pty/write": ptyterm.write,
    "/api/pty/resize": ptyterm.resize,
    "/api/pty/kill": ptyterm.kill,
    "/api/activity-monitor": uihelpers.open_activity_monitor,
    "/api/job/cancel": cancel_job,
    "/api/services/config": svc.config_save,
    "/api/services/validate": svc.config_validate,
    "/api/services/install": svc.service_install,
    "/api/services/uninstall": lambda b: svc.service_uninstall(b, brewsvc.known_service),
    "/api/cloudflared": svc.cf_action,
    "/api/apps/action": brewsvc.app_action,
    "/api/php/select": herdphp.php_select,
    "/api/php/herd": herdphp.herd_action,
    "/api/herd/action": herdphp.herd_site_action,
    "/api/pick-folder": herdphp.pick_folder,
    "/api/herd/new": herdphp.herd_new,
    "/api/lang/action": runtimes.lang_action,
    "/api/docker/action": dockerx.action,
    "/api/docker/run": dockerx.run_container,
    "/api/docker/exec": dockerx.exec_cmd,
    "/api/docker/context": dockerx.context_action,
    "/api/docker/compose/validate": dockerx.compose_validate,
    "/api/docker/compose/save": dockerx.compose_save,
    "/api/node/action": herdphp.node_action,
    "/api/files/save": files.save_file,
    "/api/files/validate": files.validate_file,
    "/api/files/resolver": files.create_resolver,
    "/api/ssh/generate": files.ssh_generate,
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # jangan spam terminal tiap polling

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")  # selalu ambil JS/CSS terbaru
        super().end_headers()

    # keamanan dasar: hanya localhost, tolak DNS rebinding & CSRF
    def _peer_ok(self):
        """Linux: к API допускается только тот же пользователь (uid владельца соединения из /proc/net/tcp). На многопользовательском сервере
        иначе любой локальный аккаунт (www-data, CI) получил бы терминал и админ-действия панели. Не удалось определить — отказ."""
        if not sys.platform.startswith("linux"):
            return True
        return peer_uid(self.client_address[1], self.server.server_address[1]) == os.getuid()

    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS

    def _json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # Ketikan terminal (/api/pty/write) bisa berisi password: tidak pernah dicatat; resize terlalu berisik.
    NO_AUDIT = {"/api/pty/write", "/api/pty/resize"}

    def _dispatch(self, handler, arg, audit_path=None):
        t0, status, err, job = time.time(), HTTPStatus.OK, None, None
        audit.INITIATOR.set("panel")
        try:
            res = handler(arg)
            job = res.get("job") if isinstance(res, dict) else None
            return self._json(res)
        except ApiError as e:
            status, err = e.status, str(e)
            return self._json({"error": err, "code": e.code, "params": e.params}, e.status)
        except FileNotFoundError as e:
            # внешний инструмент (brew, docker, git …) не установлен — это не «внутренняя ошибка»
            tool = os.path.basename(str(e.filename or "")) or "?"
            status, err = HTTPStatus.CONFLICT, f"tool_missing: {tool}"
            return self._json({"error": f"Не найден инструмент «{tool}»", "code": "tool_missing", "params": {"tool": tool}}, status)
        except json.JSONDecodeError as e:
            # внешний инструмент вернул не JSON (не запущен, нет плагина, пустой вывод) — не поломка панели
            status, err = HTTPStatus.BAD_GATEWAY, f"bad_output: {e}"
            return self._json({"error": "Инструмент вернул неожиданный ответ — возможно, он не запущен или не установлен",
                               "code": "bad_output", "params": {}}, status)
        except Exception as e:  # noqa: BLE001
            status, err = HTTPStatus.INTERNAL_SERVER_ERROR, str(e)
            return self._json({"error": err, "code": "internal", "params": {"detail": err}}, status)
        finally:
            if audit_path and audit_path not in self.NO_AUDIT:
                try:
                    audit.record(audit_path, arg, "ok" if status == HTTPStatus.OK else f"error: {err}",
                                 (time.time() - t0) * 1000, code=int(status), extra={"by": "panel", **({"job": job} if job else {})})
                except Exception:  # noqa: BLE001 - audit tidak boleh menjatuhkan request
                    pass

    def do_GET(self):
        if not self._peer_ok():
            return self._json({"error": "Доступ только для владельца панели", "code": "srv.peer_forbidden"}, HTTPStatus.FORBIDDEN)
        if not self._host_ok():
            return self._json({"error": "Хост не разрешён", "code": "srv.host_forbidden"}, HTTPStatus.FORBIDDEN)
        url = urlparse(self.path)
        if url.path in GET_ROUTES:
            if platform_info.route_missing(url.path):
                return self._json({"error": "Эта возможность недоступна на этой системе", "code": "platform.unsupported", "params": {}}, HTTPStatus.CONFLICT)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            return self._dispatch(GET_ROUTES[url.path], q)
        return super().do_GET()

    def do_POST(self):
        if not self._peer_ok():
            return self._json({"error": "Доступ только для владельца панели", "code": "srv.peer_forbidden"}, HTTPStatus.FORBIDDEN)
        if not self._host_ok() or self.headers.get("X-Requested-With") != "service-admin":
            return self._json({"error": "Запрос отклонён", "code": "srv.request_rejected"}, HTTPStatus.FORBIDDEN)
        url = urlparse(self.path)
        if url.path not in POST_ROUTES:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        if platform_info.route_missing(url.path):
            return self._json({"error": "Эта возможность недоступна на этой системе", "code": "platform.unsupported", "params": {}}, HTTPStatus.CONFLICT)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "Некорректный JSON", "code": "srv.json_invalid"}, HTTPStatus.BAD_REQUEST)
        return self._dispatch(POST_ROUTES[url.path], body, audit_path=url.path)


def peer_uid(client_port, server_port, path="/proc/net/tcp"):
    """uid процесса-владельца клиентского сокета loopback-соединения → int или None."""
    want_local, want_rem = f"0100007F:{client_port:04X}", f"0100007F:{server_port:04X}"
    try:
        with open(path, encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) > 7 and p[1] == want_local and p[2] == want_rem:
                    return int(p[7])
    except (OSError, ValueError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Service Admin")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Service Admin jalan di http://127.0.0.1:{args.port}  (Ctrl+C untuk berhenti)")
    backups.start_scheduler()
    _, sock_err = agent_socket.start()
    if sock_err:
        print(f"agent socket disabled: {sock_err}")
    remote_api.apply()
    telegram_bot.apply()
    if remote_api.status()["error"]:
        print(f"remote access disabled: {remote_api.status()['error']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")


if __name__ == "__main__":
    main()
