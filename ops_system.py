# -*- coding: utf-8 -*-
"""Каталог операций над системой: службы Homebrew, PHP/Herd/Node, языки, Docker, файлы конфигурации (Фаза 4.1, вынос из server.py).

Каждая операция описана ОДИН раз (уровень прав, параметры, условия, проверка) и исполняется теми же функциями модулей, которые вызывает страница
(`brewsvc`, `herdphp`, `svc`, `runtimes`, `dockerx`, `files`): отдельной «логики для агентов» нет. Агентам эти операции НЕ открыты
(их нет в `plans.AGENT_OPS`): здесь они только описаны — для каталога, `plan`/`describe` и будущей политики.
Уровни: L2 — ограниченные обратимые изменения; L3 — административные/затрагивающие данные или внешний мир; L4 — разрушающие.
"""
import os
import sys
from http import HTTPStatus

import brewsvc
import dockerx
import files
import herdphp
import opschema
from core import ApiError
import runtimes
import svc
from operations import REQUIREMENTS, _register

REQUIREMENTS.update({
    "herd": (lambda: os.path.exists(herdphp.HERD), "Laravel Herd must be installed"),
    "nvm": (lambda: bool(herdphp.NVM_SH), "nvm must be installed"),
    "docker": (lambda: os.path.exists(dockerx.DOCKER), "The Docker CLI must be installed"),
})

NAME = {"type": "string", "pattern": r"[A-Za-z0-9@._+-]{1,100}", "description": "Package / service name"}
HERD_VER = {"type": "string", "pattern": r"\d+\.\d+", "description": "PHP version like 8.4"}
NODE_VER = {"type": "string", "pattern": r"(v?\d+(\.\d+){0,2}|lts/[a-z*]+|node|system)", "maxLength": 40}
TARGET = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,199}$", "description": "container / image / volume / network / compose project"}
FREE = {"type": "object", "additionalProperties": True}


def _wrap(r):
    """Ответ функции модуля → форма каталога: {"job": id} или {"done": True, "result": …}.
    Команда «для терминала» (Linux без графической сессии) агенту не отдаётся и успехом не считается — это отказ, ничего не выполнено."""
    if isinstance(r, dict) and "terminal" in r and "job" not in r:
        raise ApiError("An administrator terminal is needed for this command; it was not run", code="platform.needs_terminal", command=r["terminal"])
    return r if isinstance(r, dict) and "job" in r else {"done": True, "result": r}


def _reg(op_id, title, summary, level, group, params, execute, requires=(), idempotent=False, rollback=None, verify=None, escalations=(),
         verify_fn=None, result="job", plan=None):
    base_plan = plan or (lambda p: {"will_change": True})
    run_fn = execute
    if group == "docker" and op_id != "docker.context":  # любые Docker-операции каталога — только с ЛОКАЛЬНЫМ движком
        def run_fn(p, _e=execute):  # noqa: E306,F811
            dockerx.require_local_context()
            return _e(p)

        def base_plan(p, _p=base_plan):  # noqa: E306
            ci = dockerx.require_local_context()
            return {**_p(p), "context": ci["name"], "would_run": f"context '{ci['name']}' (local engine)"}
    _register(op_id, title, summary, level, group, params, requires=tuple(requires), idempotent=idempotent, rollback=rollback, verify=verify,
              escalations=tuple(escalations), plan=base_plan, execute=lambda p: _wrap(run_fn(p)), verify_fn=verify_fn, result=result)


# ---------------------------------------------------------------- службы Homebrew

def _svc_state(name):
    return next((s for s in brewsvc.list_services() if s["name"] == name), None)


_SVC_REQ = ("systemd",) if sys.platform != "darwin" else ("homebrew",)


def _svc_plan(want_running):
    def plan(p):
        s = _svc_state(p["name"])
        if not s:
            return {"will_change": False, "note": "unknown service"}
        if sys.platform != "darwin" and s.get("scope") == "system":
            import platform_info
            if not platform_info.has("elevation.gui"):  # системная служба = права администратора: агентам без графической сессии (polkit) путь закрыт
                raise ApiError("Administrator rights are needed for a system service: a graphical session with polkit (pkexec) is required",
                               code="platform.needs_admin_gui")
        running = bool(s.get("running"))
        return {"will_change": running != want_running, "current": "running" if running else "stopped"}
    return plan


def _svc_verify(want_running):
    def verify(p):
        s = _svc_state(p["name"])
        ok = bool(s) and bool(s.get("running")) == want_running
        return {"ok": ok, "running": bool(s and s.get("running"))}
    return verify


for _act, _lvl, _run in (("start", "L2", True), ("stop", "L2", False), ("restart", "L2", True)):
    _reg(f"service.{_act}", f"{_act.capitalize()} a {'' if sys.platform != 'darwin' else 'Homebrew '}service", (f"systemctl {_act} <name>" if sys.platform != "darwin" else f"brew services {_act} <name>"), _lvl, "service", opschema.obj({"name": NAME}, ["name"]),
         lambda p, a=_act: brewsvc.service_action({"name": p["name"], "action": a}), requires=_SVC_REQ, idempotent=_act != "restart",
         rollback="the opposite action", verify="the service state matches the action", plan=_svc_plan(_run), verify_fn=_svc_verify(_run), result="immediate")
_reg("service.kill", ("Kill a service" if sys.platform != "darwin" else "Kill a Homebrew service"), ("systemctl kill <name>: stops the service forcibly" if sys.platform != "darwin" else "brew services kill <name>: stops the service forcibly"), "L3", "service", opschema.obj({"name": NAME}, ["name"]),
     lambda p: brewsvc.service_action({"name": p["name"], "action": "kill"}), requires=_SVC_REQ, rollback="service.start", result="immediate",
     plan=_svc_plan(False))
_reg("service.install", "Install a service package", "Install a Homebrew formula that provides a service", "L2", "service",
     opschema.obj({"formula": NAME}, ["formula"]), lambda p: svc.service_install({"formula": p["formula"]}), requires=(("apt", "admin_rights", "disk_10gb") if sys.platform != "darwin" else ("homebrew", "disk_10gb")),
     idempotent=True, rollback="service.uninstall", verify="the formula appears among installed packages")
_reg("service.uninstall", "Uninstall a service package", "Stop the service and `brew uninstall` it", "L3", "service", opschema.obj({"name": NAME}, ["name"]),
     lambda p: svc.service_uninstall({"name": p["name"]}, brewsvc.known_service), requires=(("apt", "admin_rights") if sys.platform != "darwin" else ("homebrew",)),
     rollback="service.install (data of the service may be lost)")
_reg("service.config_save", "Save a service config file", "Write a registered service config file (validated, backed up first, optional restart)", "L3", "service",
     opschema.obj({"name": NAME, "path": {"type": "string", "maxLength": 400}, "content": {"type": "string", "maxLength": 1_000_000},
                   "restart": {"type": "boolean"}, "force": {"type": "boolean"}}, ["name", "path", "content"]),
     lambda p: svc.config_save(p), rollback="restore the backup in ~/.service-admin/backups", result="immediate")

# ---------------------------------------------------------------- PHP / Herd / Node / языки

_reg("php.select", "Select the default PHP", "Point the `php` shim to a Homebrew PHP or a Herd PHP (or reset with id=default)", "L2", "php",
     opschema.obj({"id": {"type": "string", "maxLength": 80, "description": "id from the PHP page, or 'default'"}}, ["id"]),
     lambda p: herdphp.php_select({"id": p["id"]}), idempotent=True, rollback="php.select with the previous id", result="immediate")
for _a in ("install", "update"):
    _reg(f"herd.php_{_a}", f"Herd: {_a} a PHP version", f"herd php:{_a} <version>", "L2", "php", opschema.obj({"version": HERD_VER}, ["version"]),
         lambda p, a=_a: herdphp.herd_action({"action": a, "version": p["version"]}), requires=("herd", "disk_10gb"), idempotent=True)
_reg("herd.site", "Herd: change a site", "Link/unlink/proxy a site, switch its PHP, open or restart it", "L3", "php",
     opschema.obj({"action": {"type": "string", "maxLength": 30}, "name": {"type": "string", "maxLength": 100}, "path": {"type": "string", "maxLength": 400},
                   "php": {"type": "string", "maxLength": 20}, "host": {"type": "string", "maxLength": 200}, "secure": {"type": "boolean"}}, ["action"]),
     lambda p: herdphp.herd_site_action(p), requires=("herd",), result="immediate")
_reg("herd.new", "Herd: create a Laravel project", "Create a new Laravel app (composer + options) in a chosen folder and link it to Herd", "L3", "php", FREE,
     lambda p: herdphp.herd_new(p), requires=("herd", "disk_10gb"), rollback="delete the project folder and `herd unlink`")
_reg("node.default", "Set the default Node.js", "nvm alias default <version>", "L2", "node", opschema.obj({"version": NODE_VER}, ["version"]),
     lambda p: herdphp.node_action({"action": "default", "version": p["version"]}), requires=("nvm",), idempotent=True, result="immediate")
_reg("node.install", "Install a Node.js version", "nvm install <version>", "L2", "node", opschema.obj({"version": NODE_VER}, ["version"]),
     lambda p: herdphp.node_action({"action": "install", "version": p["version"]}), requires=("nvm", "disk_5gb"), idempotent=True, rollback="node.uninstall")
_reg("node.uninstall", "Uninstall a Node.js version", "nvm uninstall <version>", "L3", "node", opschema.obj({"version": NODE_VER}, ["version"]),
     lambda p: herdphp.node_action({"action": "uninstall", "version": p["version"]}), requires=("nvm",), rollback="node.install")
_reg("lang.action", "Language runtime action", "Actions of the Languages page: select/default version, install/update, pipx and Go tools, cache cleaning, certificate fix (Python, Go, Rust, Java, Ruby)", "L2", "lang",
     opschema.obj({"key": {"type": "string", "enum": sorted(runtimes.ACTIONS)}, "action": {"type": "string", "maxLength": 40},
                   "id": {"type": "string", "maxLength": 200}, "name": {"type": "string", "maxLength": 200}, "version": {"type": "string", "maxLength": 40},
                   "via": {"type": "string", "enum": ["uv", "brew"]}}, ["key", "action"]),
     lambda p: runtimes.lang_action(p), requires=("homebrew",),
     escalations=[{"when": {"action": a}, "level": "L3"} for a in ("pipx-uninstall", "remove-tool", "clean-modcache", "clean-cache", "cert-fix", "npm-uninstall", "gem-uninstall", "pip-uninstall")])

# Узкие операции для агентов (ревью 2026-10, шаг 4): выбор основной версии языка и установка Python — без широкого lang.action
# (в нём есть удаление версий и pip-uninstall). Всё — план + подтверждение человеком, как и прочие операции агента.
SELECT_KEYS = ("node", "python", "go", "java", "ruby", "php")


def _selected(key):
    if key == "php":
        return herdphp.php_info().get("selected")
    return runtimes.INFO[key]({}).get("selected")


def _install_ids(key):
    if key == "php":
        return [v["id"] for v in herdphp.php_info().get("versions", [])]
    return [i["id"] for i in runtimes.INFO[key]({}).get("installs") or []]


def _lang_select_plan(p):
    ids = _install_ids(p["key"])
    if p["id"] not in ids:
        raise ApiError("Unknown install id for this language; use list_runtimes or the language page", HTTPStatus.NOT_FOUND,
                       code="lang.unknown_install", key=p["key"], known=", ".join(ids[:20]))
    cur = _selected(p["key"])
    return {"will_change": cur != p["id"], "current": cur, "would_run": f"make {p['id']} the default {p['key']} (~/.service-admin/bin)"}


def _lang_select_exec(p):
    if p["key"] == "php":
        return {"done": True, "result": herdphp.php_select({"id": p["id"]})}
    return {"done": True, "result": runtimes.lang_action({"key": p["key"], "action": "select", "id": p["id"]})}


_register("lang.select", "Make an installed language version the default",
          "Point the shims in ~/.service-admin/bin (or JAVA_HOME) to an INSTALLED version of Node, Python, Go, Java, Ruby or PHP. "
          "Install the version first (package.install node@22 / openjdk@21, python.install); install ids come from list_runtimes / the language page.",
          "L2", "lang", opschema.obj({"key": {"type": "string", "enum": list(SELECT_KEYS)}, "id": {"type": "string", "maxLength": 200}}, ["key", "id"]),
          idempotent=True, rollback="lang.select with the previous id (see 'current' in the plan)", verify="the language page shows the id as the default",
          plan=_lang_select_plan, execute=_lang_select_exec, verify_fn=lambda p: {"ok": _selected(p["key"]) == p["id"], "selected": _selected(p["key"])},
          result="immediate")
_register("python.install", "Install a Python version", "uv python install X.Y (no admin rights) or brew install python@X.Y", "L2", "lang",
          opschema.obj({"version": {"type": "string", "enum": list(runtimes.PY_VERSIONS)}, "via": {"type": "string", "enum": ["uv", "brew"]}}, ["version", "via"]),
          requires=("homebrew", "disk_5gb"), idempotent=True, rollback="uninstall that Python on the Python page",
          verify="the version appears among Python installs",
          plan=lambda p: {"will_change": True, "would_run": f"uv python install {p['version']}" if p["via"] == "uv" else f"brew install python@{p['version']}"},
          execute=lambda p: _wrap(runtimes.python_install({"version": p["version"], "via": p["via"]})))

# ---------------------------------------------------------------- Docker

_reg("docker.engine_start", "Start the Docker engine (OrbStack)", "orb start", "L2", "docker", opschema.obj(), lambda p: dockerx.action({"action": "engine-start"}),
     requires=("docker",), idempotent=True)
_reg("docker.engine_stop", "Stop the Docker engine (OrbStack)", "orb stop: all containers stop", "L3", "docker", opschema.obj(),
     lambda p: dockerx.action({"action": "engine-stop"}), requires=("docker",), rollback="docker.engine_start")
_reg("docker.container", "Container / image / volume / network action", "start, stop, restart, pause, unpause, kill, rm (force), image-pull, image-rm, volume-rm, network-rm", "L3", "docker",
     opschema.obj({"action": {"type": "string", "enum": ["start", "stop", "restart", "pause", "unpause", "kill", "rm", "image-pull", "image-rm", "volume-rm", "network-rm"]},
                   "target": TARGET}, ["action", "target"]),
     lambda p: dockerx.action({"action": p["action"], "target": p["target"]}), requires=("docker",),
     escalations=[{"when": {"action": a}, "level": "L4"} for a in ("rm", "kill", "image-rm", "volume-rm", "network-rm")])
def _container_control_plan(p):
    ci = dockerx.require_local_context()
    known = p["target"] in dockerx.container_names(ci["endpoint"])
    return {"will_change": known, "context": ci["name"], "would_run": f"docker {p['action']} {p['target']} (context '{ci['name']}', local engine)",
            **({} if known else {"note": "unknown container"})}


def _container_control_exec(p):
    ci = dockerx.require_local_context()  # движок закрепляем явно: контекст не может смениться между проверкой и запуском
    if p["target"] not in dockerx.container_names(ci["endpoint"]):
        raise dockerx.ApiError("Unknown container", 404, code="docker.bad_target")
    return {"job": dockerx.start_job(f"docker {p['action']} {p['target']}", [dockerx.DOCKER, "--host", ci["endpoint"], p["action"], p["target"]], "docker")}


def _container_control_verify(p):
    dockerx.require_local_context()
    code, out, _ = dockerx.docker("--host", dockerx.require_local_context()["endpoint"], "inspect", "--format", "{{.State.Running}}", p["target"])
    running = code == 0 and out.strip() == "true"
    want = p["action"] in ("start", "restart")
    return {"ok": running == want, "checks": [{"check": "the container is " + ("running" if want else "stopped"), "ok": running == want, "detail": f"running={running}"}]}


_register("docker.container_control", "Start, stop or restart a container", "docker start|stop|restart <container> on the LOCAL engine only; never rm/kill/prune/exec", "L2", "docker",
          opschema.obj({"action": {"type": "string", "enum": ["start", "stop", "restart"]}, "target": TARGET}, ["action", "target"]),
          requires=("docker",), idempotent=True, rollback="the opposite action", verify="the container state matches the action",
          plan=_container_control_plan, execute=lambda p: _wrap(_container_control_exec(p)), verify_fn=_container_control_verify)
_reg("docker.prune", "Prune unused Docker data", "docker <kind> prune: images, containers, volumes, networks, build cache or everything", "L4", "docker",
     opschema.obj({"what": {"type": "string", "enum": ["image-prune", "image-prune-all", "container-prune", "volume-prune", "network-prune", "builder-prune", "system-prune"]}}, ["what"]),
     lambda p: dockerx.action({"action": p["what"]}), requires=("docker",), rollback="none: deleted data is gone")
def _compose_control_plan(p):
    files = dockerx.compose_project(p["target"])
    if files is None:
        raise ApiError("Unknown compose project; only projects listed by `docker compose ls` can be controlled", HTTPStatus.NOT_FOUND,
                       code="docker.compose_unknown_project", target=p["target"])
    return {"will_change": True, "would_run": f"docker compose -p {p['target']} {p['action'].replace('compose-', '')}",
            "files": files, "files_sha256": dockerx.files_digest(files)}


def _compose_control_exec(p):
    files = dockerx.compose_project(p["target"])
    if files is None:
        raise ApiError("Unknown compose project", HTTPStatus.NOT_FOUND, code="docker.compose_unknown_project", target=p["target"])
    return dockerx.action({"action": p["action"], "target": p["target"], "files": files})


_reg("docker.compose_control", "Bring a Docker Compose project up, stop or restart it",
     "up -d / up --build / start / stop / restart / pull / build of a compose project already known to Docker (docker compose ls) on the LOCAL "
     "engine, using its own registered compose files. Never down: containers, networks and volumes stay.",
     "L2", "docker", opschema.obj({"action": {"type": "string", "enum": ["compose-up", "compose-up-build", "compose-start", "compose-stop", "compose-restart", "compose-pull", "compose-build"]},
                                   "target": TARGET}, ["action", "target"]),
     _compose_control_exec, requires=("docker",), plan=_compose_control_plan,
     idempotent=True, rollback="the opposite action (stop ↔ start/up)", verify="docker compose ps of the project")
_reg("docker.compose", "Docker Compose project action", "up, start, stop, restart, down, down -v (also removes volumes), pull, build, up --build", "L3", "docker",
     opschema.obj({"action": {"type": "string", "enum": ["compose-up", "compose-start", "compose-stop", "compose-restart", "compose-down", "compose-down-v", "compose-pull", "compose-build", "compose-up-build"]},
                   "target": TARGET, "files": {"type": "array", "items": {"type": "string", "maxLength": 400}, "maxItems": 10}}, ["action", "target"]),
     lambda p: dockerx.action({"action": p["action"], "target": p["target"], "files": p.get("files") or []}), requires=("docker",),
     escalations=[{"when": {"action": "compose-down-v"}, "level": "L4"}])
_reg("docker.run", "Run a container", "docker run -d from a form (image, name, ports, env, volumes, command)", "L3", "docker", FREE,
     lambda p: dockerx.run_container(p), requires=("docker",), rollback="docker.container rm")
_reg("docker.exec", "Run a command in a container", "One non-interactive command inside a running container", "L4", "docker",
     opschema.obj({"id": TARGET, "command": {"type": "string", "maxLength": 1000}, "workdir": {"type": "string", "maxLength": 300}}, ["id", "command"]),
     lambda p: dockerx.exec_cmd(p), requires=("docker",), rollback="none", result="immediate")
_reg("docker.context", "Docker context action", "Create/use/remove a Docker context (a remote Docker host = root on that host; it also changes the target of every Docker operation)", "L4", "docker",
     opschema.obj({"action": {"type": "string", "maxLength": 20}, "name": {"type": "string", "maxLength": 80}, "host": {"type": "string", "maxLength": 300},
                   "description": {"type": "string", "maxLength": 200}}, ["action"]),
     lambda p: dockerx.context_action(p), requires=("docker",), result="immediate")
_reg("docker.compose_save", "Save a Docker Compose file", "Validate and write a compose file (backed up first), optionally bring it up", "L3", "docker", FREE,
     lambda p: dockerx.compose_save(p), requires=("docker",), rollback="restore the backup", result="immediate")

# ---------------------------------------------------------------- файлы конфигурации

_reg("files.save", "Save a registered config file", "Write a file from the registry (zsh, ssh, git, php.ini, .env …): validated, backed up (20 versions), rolled back on failure", "L3", "files",
     opschema.obj({"id": {"type": "string", "maxLength": 120}, "content": {"type": "string", "maxLength": 2_000_000}, "force": {"type": "boolean"}}, ["id", "content"]),
     lambda p: files.save_file(p), rollback="restore the backup from ~/.service-admin/backups", result="immediate")
_reg("files.resolver", "Create a macOS resolver file", "New file in /etc/resolver (administrator password dialog)", "L3", "files",
     opschema.obj({"domain": {"type": "string", "maxLength": 100}, "nameserver": {"type": "string", "maxLength": 60}}, ["domain", "nameserver"]),
     lambda p: files.create_resolver(p), rollback="delete the file in /etc/resolver (administrator)", result="immediate")
_reg("files.ssh_generate", "Generate an SSH key", "ssh-keygen ed25519 in ~/.ssh (optionally added to the agent); the passphrase is never logged", "L3", "files",
     opschema.obj({"name": {"type": "string", "maxLength": 60}, "comment": {"type": "string", "maxLength": 100}, "passphrase": {"type": "string", "maxLength": 200},
                   "add_agent": {"type": "boolean"}}, ["name"]),
     lambda p: files.ssh_generate(p), rollback="delete the key files", result="immediate")
