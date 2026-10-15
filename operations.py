"""Единый слой операций (Фаза 4.1): декларативный каталог всего, что панель умеет менять, — независимо от того, кто
вызывает (страница, MCP-агент, позже CLI). Каталог — ОДИН источник правды о том, что делает операция, какого уровня
прав она требует, при каких условиях доступна, идемпотентна ли, как проверить результат и как откатить.

Уровни прав:
  L1  только чтение;
  L2  ограниченные обратимые изменения: установка пакетов, git внутри зарегистрированных проектов, данные панели;
  L3  административные или внешние: пароль администратора, удалённые системы (push, CI), удаление ПО, юридические действия;
  L4  разрушающие и необратимые: откат/удаление данных, стирание симулятора, принудительное удаление ветки.

Что здесь есть сейчас (4.1): каталог, проверка параметров и требований, плановая часть (`plan`, ничего не меняет),
исполнение и проверка результата пакетных операций (вынесены из server.py). Исполнение агентами, `plan_id`, очередь
подтверждений — следующие пункты (4.2, 4.4): агентам операции пока доступны только как ОПИСАНИЕ.
"""
import os
import shutil
import threading
import time
from http import HTTPStatus

import opschema
from core import BREW, PKG_RE, ApiError, has_clt, run, start_job

LEVELS = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
LEVEL_INFO = {
    "L1": "read-only",
    "L2": "limited, reversible changes: package installs, git inside registered projects, panel data",
    "L3": "administrative or outward-facing: admin password, remote systems, removal of software, legal acceptance",
    "L4": "destructive or irreversible: discarding or deleting data, erasing a simulator, force-deleting a branch",
}


# ---------------------------------------------------------------- требования (условия, при которых операция доступна)

_REQ_CACHE = {}
_REQ_LOCK = threading.Lock()


def _cached(key, fn, ttl=15):
    with _REQ_LOCK:
        hit = _REQ_CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _REQ_LOCK:
        _REQ_CACHE[key] = (time.time(), value)
    return value


def _homebrew():
    return any(os.path.exists(p) for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"))


def _xcode():
    import mobile
    return bool(mobile.xcode_info()["installs"])


def _flutter():
    import mobile
    return bool((mobile.flutter_info().get("sdk") or {}).get("path"))


def _tool(name):
    import mobile
    return bool(mobile._which(name))  # noqa: SLF001


def _android():
    import mobile
    return bool(mobile.android_info().get("sdkmanager"))


def _gh():
    import projects
    return bool(projects.GH)


REQUIREMENTS = {
    "homebrew": (_homebrew, "Homebrew must be installed"),
    "clt": (has_clt, "Xcode Command Line Tools must be installed"),
    "disk_5gb": (lambda: shutil.disk_usage("/").free > 5e9, "At least 5 GB of free disk space"),
    "disk_10gb": (lambda: shutil.disk_usage("/").free > 10e9, "At least 10 GB of free disk space"),
    "xcode": (lambda: _cached("xcode", _xcode), "Full Xcode must be installed"),
    "flutter": (lambda: _cached("flutter", _flutter), "A Flutter SDK must be installed"),
    "fvm": (lambda: _cached("fvm", lambda: _tool("fvm")), "FVM must be installed"),
    "cocoapods": (lambda: _cached("pod", lambda: _tool("pod")), "CocoaPods must be installed"),
    "android_sdk": (lambda: _cached("android", _android), "The Android SDK command-line tools must be installed"),
    "gh": (_gh, "GitHub CLI (gh) must be installed"),
    "tart": (lambda: __import__("vm").driver().available(), "tart (VM hypervisor driver) must be installed"),
}


def unmet(requires):
    out = []
    for r in requires:
        ok, hint = REQUIREMENTS[r]
        try:
            good = bool(ok())
        except Exception:  # noqa: BLE001 - не смогли проверить = считаем не выполненным
            good = False
        if not good:
            out.append({"id": r, "summary": hint})
    return out


# ---------------------------------------------------------------- каталог

OPS = {}


def _register(op_id, title, summary, level, group, params=None, requires=(), idempotent=False, rollback=None, verify=None,
              escalations=(), via="module", plan=None, execute=None, verify_fn=None, result="job"):
    if op_id in OPS:
        raise ValueError(f"duplicate operation {op_id}")
    OPS[op_id] = {"id": op_id, "title": title, "summary": summary, "level": level, "group": group,
                  "params": params or opschema.obj(), "requires": list(requires), "idempotent": idempotent,
                  "rollback": rollback, "verify": verify, "escalations": list(escalations), "via": via,
                  "result": result, "_plan": plan, "_execute": execute, "_verify": verify_fn}


def _project():
    return {"type": "string", "description": "Path of a project registered in the panel (Projects page)"}


def _files():
    return {"type": "array", "items": {"type": "string", "maxLength": 400}, "minItems": 1, "maxItems": 200,
            "description": "File paths inside the project, taken from its git status"}


def _confirm():
    return {"type": "string", "maxLength": 100, "description": "The project folder name, typed to confirm a destructive action"}


# -- пакеты Homebrew (вынесены из server.py: страница и агенты исполняют одно и то же)

def _pkg_schema():
    return opschema.obj({"name": {"type": "string", "pattern": PKG_RE.pattern, "maxLength": 100, "description": "Homebrew formula or cask name"},
                         "type": {"type": "string", "enum": ["formula", "cask"]}}, ["name", "type"])


def package_state(kind, name):
    """{installed, version} через `brew list` — быстрая проверка состояния до/после."""
    code, out, _ = run([BREW, "list", f"--{kind}", "--versions", name], timeout=60)
    line = out.strip().splitlines()[0] if code == 0 and out.strip() else ""
    parts = line.split()
    return {"installed": code == 0 and bool(parts), "version": " ".join(parts[1:]) or None}


def run_package(action, kind, name):
    """Единственное место, где собирается и запускается `brew <action> --<kind> <name>` (job kind «brew»)."""
    return {"job": start_job(f"brew {action} {name}", [BREW, action, f"--{kind}", name], "brew")}


def run_upgrade_all():
    return {"job": start_job("brew upgrade (все)", [BREW, "upgrade"], "brew")}


def _package_plan(action):
    def plan(p):
        st = package_state(p["type"], p["name"])
        skip = (action == "install" and st["installed"]) or (action == "uninstall" and not st["installed"])
        return {"state_before": st, "would_run": f"brew {action} --{p['type']} {p['name']}", "will_change": not skip,
                "noop_reason": ("already installed" if action == "install" else "not installed") if skip else None}
    return plan


def _package_verify(action):
    def verify(p):
        st = package_state(p["type"], p["name"])
        ok = (not st["installed"]) if action == "uninstall" else st["installed"]
        return {"ok": ok, "state": st}
    return verify


for _action, _title, _level, _summary in (
        ("install", "Install a Homebrew package", "L2", "Install one Homebrew formula or cask."),
        ("upgrade", "Upgrade a Homebrew package", "L2", "Upgrade one installed Homebrew formula or cask."),
        ("reinstall", "Reinstall a Homebrew package", "L2", "Reinstall one Homebrew formula or cask."),
        ("uninstall", "Uninstall a Homebrew package", "L3", "Remove one Homebrew formula or cask (its data folders are left alone).")):
    _register(f"package.{_action}", _title, _summary, _level, "package", _pkg_schema(), requires=("homebrew", "clt"),
              idempotent=_action in ("install", "uninstall"),
              rollback={"install": "package.uninstall", "uninstall": "package.install", "upgrade": None, "reinstall": None}[_action],
              verify=f"brew list shows the package {'absent' if _action == 'uninstall' else 'installed'}",
              plan=_package_plan(_action),
              execute=(lambda a: lambda p: run_package(a, p["type"], p["name"]))(_action),
              verify_fn=_package_verify(_action))
_register("package.upgrade_all", "Upgrade all Homebrew packages", "Run `brew upgrade` for every outdated package.", "L2", "package",
          requires=("homebrew", "clt"), idempotent=True, verify="no outdated packages remain",
          plan=lambda p: {"would_run": "brew upgrade", "will_change": True}, execute=lambda p: run_upgrade_all())


# -- профили установки (profiles.py), снимки, копии, запуски

def _profile_ids():
    import profiles
    return [p["id"] for p in profiles.PROFILES]


def _profile_schema():
    return opschema.obj({"profile": {"type": "string", "enum": _profile_ids()},
                         "scope": {"type": "string", "enum": ["required", "all"], "description": "Which missing items to install"},
                         "items": {"type": "array", "items": {"type": "string", "pattern": r"[a-z0-9-]{1,30}"}, "maxItems": 30,
                                   "description": "Specific item ids (overrides scope)"}}, ["profile"])


def _profile_plan(p):
    import profiles
    q = {"profile": p["profile"], "scope": p.get("scope") or "required", "items": ",".join(p.get("items") or [])}
    pl = profiles.plan(q)
    return {"will_change": pl["to_install"] > 0, "to_install": [e["id"] for e in pl["items"] if e["action"] == "install"],
            "skipped_installed": [e["id"] for e in pl["items"] if e["action"] == "skip"],
            "not_installable_here": [e["id"] for e in pl["items"] if e["action"] in ("setup", "manual", "later")], "blocked_by": pl["blocked"]}


def _profile_verify(p):
    import profiles
    q = {"profile": p["profile"], "scope": p.get("scope") or "required", "items": ",".join(p.get("items") or [])}
    left = [e["id"] for e in profiles.plan(q)["items"] if e["action"] == "install"]
    return {"ok": not left, "still_missing": left}


_register("profile.install", "Install an install profile", "Install the missing Homebrew-based tools of a profile (skips what is installed).", "L2",
          "profile", _profile_schema(), requires=("homebrew", "clt", "disk_10gb"), idempotent=True,
          rollback="package.uninstall for each installed item", verify="the profile plan shows nothing left to install",
          plan=_profile_plan, execute=lambda p: __import__("profiles").install(
              {"profile": p["profile"], "scope": p.get("scope") or "required", "items": p.get("items") or []}), verify_fn=_profile_verify)
_register("snapshot.create", "Take an environment snapshot", "Record installed packages, runtimes, Xcode, Flutter/Android and profile status into a snapshot file.",
          "L2", "snapshot", opschema.obj({"label": {"type": "string", "maxLength": 80}}), idempotent=False,
          rollback="delete the snapshot in the panel", verify="the snapshot file exists",
          plan=lambda p: {"will_change": True, "writes": "~/.service-admin/snapshots/<time>.json"},
          execute=lambda p: {"done": True, "result": __import__("snapshots").create({"label": p.get("label", "")})}, result="immediate")
_register("backup.run", "Run a backup now", "Back up repositories (git bundle), configured folders and panel data to the configured destination.", "L2",
          "backup", idempotent=True, verify="every copy is verified right after creation; see the last run in the panel",
          plan=lambda p: {"will_change": True, "writes": "the configured backup destination"}, execute=lambda p: __import__("backups").start({}))
def _project_run_plan(p):
    import projects
    path = projects.resolve(p["project"])
    cmd = projects.presets_get(path).get(p["kind"]) or ""
    if not cmd:
        raise ApiError(f"The project preset has no {p['kind']} command", HTTPStatus.CONFLICT, code="ops.no_preset", kind=p["kind"])
    projects.runnable_argv(path, cmd)  # тот же допуск, что и при запуске
    return {"will_change": True, "would_run": cmd, "cwd": path}


_register("project.run", "Run a project's test or build command", "Run the test/build command stored in the project's preset (allowlisted tools, 30 min limit).", "L2",
          "project", opschema.obj({"project": _project(), "kind": {"type": "string", "enum": ["test", "build"]}}, ["project", "kind"]),
          verify="exit code and history entry in the Runs page",
          plan=_project_run_plan, execute=lambda p: __import__("runs").start(p))


_register("github.workflow_run", "Dispatch a GitHub Actions workflow", "Start a workflow_dispatch run on a branch of the project's GitHub repository.", "L3", "project",
          opschema.obj({"project": _project(), "workflow": {"type": "string", "pattern": r"\d{1,12}"}, "ref": {"type": "string", "maxLength": 100},
                        "inputs": {"type": "object", "additionalProperties": True, "description": "workflow_dispatch inputs: up to 10 name=value pairs"},
                        "confirm": _confirm()}, ["project", "workflow", "confirm"]),
          requires=("gh",), verify="the run appears in the project's GitHub runs list",
          plan=lambda p: {"will_change": True, "outward": "starts CI on GitHub (possibly billable minutes or a deploy)"},
          execute=lambda p: __import__("runs").workflow_run(p))
_register("github.run_cancel", "Cancel a running GitHub Actions run", "Cancel a run that is still in progress (`gh run cancel`); the project name is typed to confirm.", "L3", "project",
          opschema.obj({"project": _project(), "run_id": {"type": "string", "pattern": r"\d{1,20}"}, "confirm": _confirm()}, ["project", "run_id", "confirm"]),
          requires=("gh",), verify="the run shows as cancelled in the project's GitHub runs list",
          plan=lambda p: {"will_change": True, "outward": "cancels a CI run on GitHub"},
          execute=lambda p: __import__("runs").run_cancel(p))
_register("github.run_rerun", "Re-run a finished GitHub Actions run", "Re-run a completed run, optionally only its failed jobs (`gh run rerun`); the project name is typed to confirm.", "L3", "project",
          opschema.obj({"project": _project(), "run_id": {"type": "string", "pattern": r"\d{1,20}"}, "failed_only": {"type": "boolean"}, "confirm": _confirm()},
                       ["project", "run_id", "confirm"]),
          requires=("gh",), verify="a new attempt of the run appears in the project's GitHub runs list",
          plan=lambda p: {"will_change": True, "outward": "starts CI on GitHub again (possibly billable minutes or a deploy)"},
          execute=lambda p: __import__("runs").run_rerun(p))


# -- git (gitops.py): описание; исполнение — gitops.run_op

_GIT = [  # id, level, title, summary, params, escalations, requires-extra
    ("git.fetch", "L2", "Fetch from remotes", "git fetch --prune", {"remote": {"type": "string", "maxLength": 50}}, [], []),
    ("git.pull", "L2", "Pull (fast-forward only)", "git pull --ff-only; refuses on divergence", {}, [], []),
    ("git.push", "L3", "Push the current branch", "git push (never --force); first push sets upstream", {"remote": {"type": "string", "maxLength": 50}}, [], []),
    ("git.switch", "L2", "Switch branch", "git switch to a local or remote branch", {"branch": {"type": "string", "maxLength": 100}}, [], []),
    ("git.branch_create", "L2", "Create and switch to a branch", "git switch -c", {"name": {"type": "string", "maxLength": 100}, "start": {"type": "string", "maxLength": 100}}, [], []),
    ("git.branch_delete", "L3", "Delete a branch", "git branch -d (merged only); with force, -D after typed confirmation",
     {"branch": {"type": "string", "maxLength": 100}, "force": {"type": "boolean"}, "confirm": _confirm()}, [{"when": {"force": True}, "level": "L4"}], []),
    ("git.stash_push", "L2", "Stash changes", "git stash push --include-untracked", {"message": {"type": "string", "maxLength": 200}}, [], []),
    ("git.stash_pop", "L2", "Apply and drop a stash", "git stash pop", {"index": {"type": "integer", "minimum": 0, "maximum": 99}}, [], []),
    ("git.add", "L2", "Stage files", "git add -- <files>", {"files": _files()}, [], []),
    ("git.unstage", "L2", "Unstage files", "git restore --staged -- <files>", {"files": _files()}, [], []),
    ("git.commit", "L2", "Commit the staged files", "git commit -m <message>; only what is staged", {"message": {"type": "string", "maxLength": 2000, "minLength": 1}}, [], []),
    ("git.discard", "L4", "Discard working-tree changes", "git restore --worktree; requires the project name typed as confirmation",
     {"files": _files(), "confirm": _confirm()}, [], []),
    ("git.clean", "L4", "Delete untracked files", "git clean -f; requires the project name typed as confirmation", {"files": _files(), "confirm": _confirm()}, [], []),
    ("git.worktree_add", "L2", "Create a worktree on a new branch", "git worktree add under ~/Worktrees", {"branch": {"type": "string", "maxLength": 100}, "base": {"type": "string", "maxLength": 100}}, [], []),
    ("git.worktree_remove", "L3", "Remove a worktree", "git worktree remove (never --force), only inside ~/Worktrees", {"worktree": {"type": "string", "maxLength": 400}}, [], []),
]
for _id, _lvl, _title, _sum, _props, _esc, _req in _GIT:
    _register(_id, _title, _sum, _lvl, "git", opschema.obj({"project": _project(), **_props}, ["project", *[k for k, v in _props.items() if k in ("branch", "name", "files", "message", "index", "worktree")]]),
              requires=("clt", *_req), escalations=_esc, via="gitops",
              verify="git status / git log / branches reflect the change (see the verify result: a list of checks)",
              execute=lambda p, _i=_id: __import__("gitops").run_op({"op": _i, "params": p}),
              verify_fn=lambda p, _i=_id: __import__("gitops").verify(_i, p))

# -- мобильные тулчейны (mobile_ops.py)

_MOB = [  # id, level, title, summary, props, required, requires, escalations
    ("xcode.select", "L3", "Switch the active Xcode", "xcode-select -s (administrator password)", {"path": {"type": "string", "maxLength": 400}}, ["path"], ["xcode"]),
    ("xcode.first_launch", "L3", "Xcode first launch", "xcodebuild -runFirstLaunch (administrator password)", {}, [], ["xcode"]),
    ("xcode.download_platform", "L3", "Download a simulator platform", "xcodebuild -downloadPlatform (several GB)", {"platform": {"type": "string", "enum": ["iOS", "watchOS", "tvOS", "visionOS"]}}, [], ["xcode", "disk_10gb"]),
    ("sim.boot", "L2", "Boot a simulator", "simctl boot", {"udid": {"type": "string", "maxLength": 40}}, ["udid"], ["xcode"]),
    ("sim.shutdown", "L2", "Shut down a simulator", "simctl shutdown", {"udid": {"type": "string", "maxLength": 40}}, ["udid"], ["xcode"]),
    ("sim.erase", "L4", "Erase a simulator", "simctl erase: deletes all data and apps of the simulator", {"udid": {"type": "string", "maxLength": 40}}, ["udid"], ["xcode"]),
    ("sim.runtime_delete", "L4", "Delete a simulator runtime", "simctl runtime delete: removes a simulator runtime (several GB); the runtime name (e.g. iOS-27-1) is typed to confirm",
     {"runtime": {"type": "string", "pattern": r"[0-9A-Fa-f-]{36}"}, "confirm": {"type": "string", "maxLength": 60}}, ["runtime", "confirm"], ["xcode"]),
    ("sim.screenshot", "L2", "Screenshot of a booted simulator", "Writes a PNG into ~/.service-admin/screenshots", {"udid": {"type": "string", "maxLength": 40}}, ["udid"], ["xcode"]),
    ("flutter.doctor", "L2", "flutter doctor", "Diagnose the Flutter toolchain", {}, [], ["clt", "flutter"]),
    ("flutter.pub_get", "L2", "flutter pub get", "Fetch dependencies of a Flutter project", {"project": _project()}, ["project"], ["clt", "flutter"]),
    ("flutter.analyze", "L2", "flutter analyze", "Static analysis of a Flutter project", {"project": _project()}, ["project"], ["clt", "flutter"]),
    ("flutter.test", "L2", "flutter test", "Run the tests of a Flutter project", {"project": _project()}, ["project"], ["clt", "flutter"]),
    ("flutter.build_apk", "L2", "flutter build apk", "Build an Android APK", {"project": _project()}, ["project"], ["clt", "flutter"]),
    ("flutter.channel", "L3", "Switch the Flutter channel", "flutter channel + flutter upgrade: changes the SDK", {"channel": {"type": "string", "enum": ["stable", "beta", "master"]}}, ["channel"], ["clt", "flutter"]),
    ("fvm.install", "L2", "fvm install", "Install a Flutter version with FVM", {"version": {"type": "string", "maxLength": 40}}, ["version"], ["clt", "fvm"]),
    ("fvm.use", "L2", "fvm use", "Pin a Flutter version in a project", {"project": _project(), "version": {"type": "string", "maxLength": 40}}, ["project", "version"], ["clt", "fvm"]),
    ("pod.install", "L2", "pod install", "Install CocoaPods dependencies of a project", {"project": _project()}, ["project"], ["clt", "cocoapods"]),
    ("android.licenses", "L3", "Accept Android SDK licences", "sdkmanager --licenses: a legal acceptance on the user's behalf", {}, [], ["android_sdk"]),
    ("android.install", "L3", "Install an Android SDK package", "sdkmanager <package>; licences are accepted automatically", {"package": {"type": "string", "pattern": r"[a-z0-9_.;-]{3,120}", "maxLength": 120}}, ["package"], ["android_sdk"]),
]
for _id, _lvl, _title, _sum, _props, _req_params, _req in _MOB:
    _register(_id, _title, _sum, _lvl, _id.split(".")[0], opschema.obj(_props, _req_params), requires=tuple(_req), via="mobile_ops",
              verify="the toolchain state matches the operation (see the verify result: a list of checks)" if _id in __import__("mobile_ops").VERIFIABLE
              else "none: diagnostic only, the result is the job's exit code and log",
              execute=lambda p, _i=_id: __import__("mobile_ops").run_op({"op": _i, "params": p}),
              verify_fn=(lambda p, _i=_id: __import__("mobile_ops").verify(_i, p)) if _id in __import__("mobile_ops").VERIFIABLE else None)


# ---------------------------------------------------------------- публичный API слоя

def describe(op_id, with_status=True):
    op = OPS.get(op_id)
    if not op:
        raise ApiError("Unknown operation", HTTPStatus.NOT_FOUND, code="ops.unknown", id=str(op_id)[:60])
    d = {k: v for k, v in op.items() if not k.startswith("_")}
    d["can_plan"] = bool(op["_plan"])
    d["has_verify"] = bool(op["_verify"])
    if with_status:
        d["unmet"] = unmet(op["requires"])
        d["available"] = not d["unmet"]
    return d


def catalog(q=None):
    """GET /api/operations — весь каталог с доступностью на ЭТОЙ машине."""
    ops = [describe(i) for i in OPS]
    by_level = {}
    for o in ops:
        by_level[o["level"]] = by_level.get(o["level"], 0) + 1
    return {"levels": LEVEL_INFO, "count": len(ops), "by_level": by_level, "operations": ops}


def validate_params(op_id, params):
    op = OPS.get(op_id)
    if not op:
        raise ApiError("Unknown operation", HTTPStatus.NOT_FOUND, code="ops.unknown", id=str(op_id)[:60])
    err = opschema.validate(op["params"], params)
    if err:
        raise ApiError(err, code="ops.invalid_params", detail=err)
    return op


def effective_level(op, params):
    """Уровень вызова с учётом эскалаций (например, branch_delete с force — L4)."""
    lvl = op["level"]
    for e in op.get("escalations", []):
        if all(params.get(k) == v for k, v in e["when"].items()) and LEVELS[e["level"]] > LEVELS[lvl]:
            lvl = e["level"]
    return lvl


def plan(op_id, params):
    """Что произойдёт, если выполнить операцию — НИЧЕГО не меняя: проверка параметров, требований и состояния."""
    op = validate_params(op_id, params)
    missing = unmet(op["requires"])
    out = {"operation": op_id, "level": effective_level(op, params), "params": params, "unmet_requirements": missing,
           "executable": not missing, "idempotent": op["idempotent"], "rollback": op["rollback"], "verify": op["verify"]}
    if op["_plan"] and not missing:
        out["plan"] = op["_plan"](params)
    elif op["via"] in ("gitops", "mobile_ops") and not missing:
        # build() обоих модулей — чистая функция: собирает команды и ничего не запускает
        if op["via"] == "gitops":
            import gitops
            label, _, steps = gitops.build(op_id, params, None)
        else:
            import mobile_ops
            label, _, steps = mobile_ops.build(op_id, params)
        out["plan"] = {"will_change": True, "label": label, "steps": [st[0] for st in steps]}
    return out


def verify(op_id, params):
    """Проверить результат ПОСЛЕ выполнения (если у операции есть автоматическая проверка)."""
    op = validate_params(op_id, params)
    if not op["_verify"]:
        raise ApiError("This operation has no automatic verification", HTTPStatus.CONFLICT, code="ops.no_verify")
    return op["_verify"](params)


def execute(op_id, params):
    """Выполнить операцию: параметры → требования → исполнитель. Возвращает {"job": id} или {"done": True, "result": …}.
    Правила авторизации (уровни, подтверждение человеком) накладывает вызывающий слой — для агентов это 4.2/4.4."""
    op = validate_params(op_id, params)
    missing = unmet(op["requires"])
    if missing:
        raise ApiError("Requirements are not met: " + "; ".join(m["summary"] for m in missing), HTTPStatus.CONFLICT,
                       code="ops.requirements", unmet=", ".join(m["id"] for m in missing))
    return op["_execute"](params)


def _runner_plan(p, outward):
    """Описание для плана/диалога: имя источника, адрес сервера CI, ВМ-основа (id источника сам по себе ничего не говорит человеку)."""
    import runners
    s = runners.get_source(p["source"])
    return {"will_change": True, "outward": outward,
            "would_run": (f"source '{s['name']}' ({s['provider']}, {s['url']}), base VM '{p['vm']}', labels {p.get('labels') or 'default'}, "
                          f"isolate {p.get('isolate', 'auto')}, wait {p.get('minutes', 60)} min")}


# -- виртуальные машины (vm.py): агентам НЕ открыты (нет в plans.AGENT_OPS)

_VMN = {"type": "string", "pattern": r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", "maxLength": 40}
_VM = [  # id, level, title, summary, props, required
    ("vm.clone", "L2", "Clone a VM", "Local copy of an existing VM (cheap APFS clone)", {"source": _VMN, "name": _VMN}, ["source", "name"]),
    ("vm.pull", "L3", "Download a VM image", "Download a macOS image from ghcr.io/cirruslabs/ (tens of GB); the new VM name is typed to confirm",
     {"image": {"type": "string", "maxLength": 120}, "name": _VMN, "confirm": _confirm()}, ["image", "name", "confirm"]),
    ("vm.start", "L2", "Start a VM", "tart run --no-graphics; no host folders are shared", {"name": _VMN}, ["name"]),
    ("vm.stop", "L2", "Stop a VM", "tart stop", {"name": _VMN}, ["name"]),
    ("vm.snapshot", "L2", "Snapshot a VM", "Copy of a stopped VM named <name>-snap-<time> (tart has no snapshots; this is a clone)", {"name": _VMN}, ["name"]),
    ("vm.prepare_runner", "L2", "Put CI runner files into a VM", "Copy the installed runner files into a STOPPED base VM over SSH (guest account admin, NAT network) and verify them; the runner is not registered",
     {"name": _VMN, "provider": {"type": "string", "enum": ["github", "gitea"]}}, ["name", "provider"]),
    ("vm.restore", "L4", "Restore a VM from a snapshot", "Replace a STOPPED VM by a copy of its snapshot <name>-snap-<time>: everything done in the VM since is lost; the exact VM name is typed to confirm",
     {"name": _VMN, "snapshot": _VMN, "confirm": _confirm()}, ["name", "snapshot", "confirm"]),
    ("vm.delete", "L4", "Delete a VM", "tart delete: the VM and its disk are gone; the exact VM name is typed to confirm", {"name": _VMN, "confirm": _confirm()}, ["name", "confirm"]),
]
for _id, _lvl, _title, _sum, _props, _req_params in _VM:
    _register(_id, _title, _sum, _lvl, "vm", opschema.obj(_props, _req_params), requires=("tart",),
              verify="the VM list shows the new state",
              plan=lambda p, _i=_id: {"will_change": True, "label": __import__("vm").build(_i, p)[0]},
              execute=lambda p, _i=_id: __import__("vm").run_op({"op": _i, "params": p}))

_register("runner.install", "Install CI runner files", "Download the official runner of a CI provider (GitHub or Gitea/Forgejo), verify its sha256 and unpack it. It is NOT registered or started.",
          "L2", "runner", opschema.obj({"provider": {"type": "string", "enum": ["github", "gitea"]}}, ["provider"]), idempotent=True, requires=("disk_5gb",),
          verify="the runner folder exists in ~/.service-admin/runners/<provider>/<version>", rollback="delete that folder",
          plan=lambda p: {"will_change": True, "writes": "~/.service-admin/runners/<provider>/<version>", "downloads": "the official runner release (5-130 MB)"},
          execute=lambda p: __import__("runners").install(p))

_register("runner.spawn", "Run an on-demand CI runner in a disposable VM", "Clone a prepared base VM, register an EPHEMERAL runner of a stored source (the CI server may then send code to that VM), wait for one job, delete the VM.",
          "L3", "runner", opschema.obj({"source": {"type": "string", "pattern": r"s[0-9a-f]{6}"}, "vm": _VMN,
                                        "labels": {"type": "array", "items": {"type": "string", "maxLength": 60}, "maxItems": 5},
                                        "minutes": {"type": "integer", "minimum": 1, "maximum": 240}, "isolate": {"enum": [True, False, "auto"]}, "confirm": _confirm()}, ["source", "vm", "confirm"]),
          requires=("tart",), verify="the job result is visible on the CI server; the ci-* VM no longer exists",
          rollback="none needed: the VM is deleted at the end; an unused runner may stay listed as offline on the CI server",
          plan=lambda p: _runner_plan(p, "registers a runner on the CI server and lets it run workflow code inside a disposable VM"),
          execute=lambda p: __import__("runner_spawn").start(p))

_register("runner.selftest", "Self-test a CI source end to end", "Create a test repository on the CI server, push a workflow, run an on-demand runner in a disposable VM, check the result and clean up. Needs a source with an access token (instance or org scope).",
          "L3", "runner", opschema.obj({"source": {"type": "string", "pattern": r"s[0-9a-f]{6}"}, "vm": _VMN,
                                        "minutes": {"type": "integer", "minimum": 1, "maximum": 240}, "isolate": {"enum": [True, False, "auto"]},
                                        "confirm": _confirm()}, ["source", "vm", "confirm"]),
          requires=("tart",), verify="the log ends with SELFTEST PASSED; the test repository and the ci-* VM are gone",
          rollback="none needed: the test repository and the VM are removed at the end",
          plan=lambda p: _runner_plan(p, "creates and deletes a repository on the CI server and runs workflow code in a disposable VM"),
          execute=lambda p: __import__("runner_spawn").selftest(p))


# Операции над системой (службы, PHP/Herd/Node, Docker, файлы) — отдельным модулем, регистрируются в этот же каталог
import ops_system  # noqa: E402,F401
