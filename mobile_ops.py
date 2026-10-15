"""Действия над мобильными тулчейнами (Фаза 2.5): Xcode, симуляторы, Flutter/FVM, CocoaPods, Android.

`mobile.py` остаётся ТОЛЬКО ЧТЕНИЕМ; всё, что меняет систему, живёт здесь. Принципы:
  * браузер называет операцию и идентификатор из реестра сервера (Xcode из списка установленных,
    UDID из `simctl list`, проект из реестра/скана) — никогда произвольный путь или команду;
  * `build()` — чистая функция: из операции и параметров делает (подпись, kind, шаги) и НИЧЕГО не
    запускает; это позволяет проверять собираемые команды сухим прогоном;
  * исполнение — `core.start_steps` (job + лог + аудит); админские действия — через диалог пароля
    macOS (`osascript ... with administrator privileges`), панель пароль не видит и не хранит.
"""
import base64
import json
import os
import re
import shlex
import subprocess
import time
from http import HTTPStatus

import mobile
import projects
from core import DATA_DIR, ENV, HOME, ApiError, has_clt, loads_or, run, start_steps

SHOT_DIR = os.path.join(DATA_DIR, "screenshots")
SHOT_RE = re.compile(r"^[0-9A-F]{8}-\d{8}-\d{6}\.png$")
UDID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
FLUTTER_VER_RE = re.compile(r"^(stable|beta|dev|master|\d+\.\d+(\.\d+)?(\.\d+)?(-[A-Za-z0-9.]+)?)$")
SDK_PKG_RE = re.compile(r"^[a-z0-9_.;-]{3,120}$")
CHANNELS = ("stable", "beta", "master")
ADMIN_TIMEOUT = 1800
# kind = какие операции взаимоисключаются (одна за раз): xcode-* меняют общие системные настройки.
KIND = {"xcode": "mobile-xcode", "sim": "mobile-sim", "flutter": "mobile-flutter", "fvm": "mobile-flutter",
        "pod": "mobile-pods", "android": "mobile-android"}


# ---------------------------------------------------------------- вспомогательные

def _admin(argv, prompt):
    """Шаг, который выполняет argv от имени администратора через системный диалог пароля."""
    cmd = " ".join(shlex.quote(a) for a in argv)
    script = f"do shell script {json.dumps(cmd)} with administrator privileges with prompt {json.dumps(prompt)}"

    def step(log):
        log("Откроется системный диалог пароля администратора macOS…")
        code, out, err = run(["/usr/bin/osascript", "-e", script], timeout=ADMIN_TIMEOUT)
        for line in (out or "").splitlines():
            log(line)
        if code != 0:
            raise RuntimeError("отменено: пароль администратора не введён" if "-128" in err or "canceled" in err.lower()
                               else (err.strip() or f"exit {code}"))
    return step


def _stream(argv, cwd=None, env=None, stdin_text=None):
    """Шаг: запустить argv, строки вывода — в лог job; stdin_text подаётся на ввод (например «y» для лицензий)."""
    def step(log):
        proc = subprocess.Popen(argv, cwd=cwd, env=env or ENV, text=True, bufsize=1,
                                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if stdin_text:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:
                pass
        for line in proc.stdout:
            log(line.rstrip("\n"))
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"exit {rc}")
    return step


def _need_tools():
    if not has_clt():
        raise ApiError("Сначала нужны Command Line Tools — откройте «Подготовка системы»", HTTPStatus.CONFLICT, code="mob.need_clt")


def _flutter_bin(project=None):
    """flutter проекта (закреплённый FVM), иначе активный SDK."""
    if project:
        pinned = os.path.join(project, ".fvm", "flutter_sdk", "bin", "flutter")
        if os.path.isfile(pinned):
            return pinned
    sdk = (mobile.flutter_info().get("sdk") or {}).get("path")
    flutter = os.path.join(sdk, "bin", "flutter") if sdk else None
    if not flutter or not os.path.isfile(flutter):
        raise ApiError("Flutter SDK не найден", HTTPStatus.CONFLICT, code="mob.no_flutter")
    return flutter


def _flutter_project(raw):
    """Проект должен быть известен серверу (скан Flutter-проектов или реестр) и содержать pubspec.yaml."""
    if not raw:
        raise ApiError("Не указан проект", code="mob.no_project")
    real = projects._canon(os.path.realpath(os.path.expanduser(str(raw))))  # noqa: SLF001
    known = {projects._canon(os.path.realpath(p["path"])) for p in mobile.flutter_projects(limit=200)}  # noqa: SLF001
    known |= projects.known_projects()
    if real not in known or not os.path.isfile(os.path.join(real, "pubspec.yaml")):
        raise ApiError("Проект не найден среди известных Flutter-проектов", HTTPStatus.NOT_FOUND, code="mob.project_unknown")
    return real


def _device(udid):
    if not isinstance(udid, str) or not UDID_RE.match(udid):
        raise ApiError("Неверный UDID симулятора", code="mob.bad_udid")
    dev = next((d for d in mobile.xcode_info()["devices"] if d["udid"] == udid), None)
    if not dev:
        raise ApiError("Симулятор не найден", HTTPStatus.NOT_FOUND, code="mob.sim_missing")
    return dev


UUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")


def _runtime_list():
    """`simctl runtime list -j` → {uuid: описание} только для того, что simctl считает удаляемым."""
    code, out, err = run(["/usr/bin/xcrun", "simctl", "runtime", "list", "-j"], timeout=30)
    if code != 0:
        raise ApiError("simctl не смог получить рантаймы", HTTPStatus.CONFLICT, code="mob.rt_list", detail=(err.strip().splitlines() or ["ошибка"])[-1][:120])
    data = loads_or(out, None)
    if not isinstance(data, dict):
        raise ApiError("Неожиданный ответ simctl", HTTPStatus.INTERNAL_SERVER_ERROR, code="bad_output")
    res = {}
    for key, rt in data.items():
        if isinstance(rt, dict) and UUID_RE.match(str(rt.get("identifier") or key)) and rt.get("deletable") is True:
            rid = str(rt.get("runtimeIdentifier") or "")
            res[str(rt.get("identifier") or key).upper()] = {
                "uuid": str(rt.get("identifier") or key).upper(), "runtime_id": rid, "short": rid.split("SimRuntime.")[-1],
                "version": rt.get("version"), "kind": rt.get("kind"), "state": rt.get("state"),
                "size_bytes": rt.get("sizeBytes") if isinstance(rt.get("sizeBytes"), int) else None}
    return res


def runtimes_deletable(q=None):
    """GET /api/mobile/runtimes — рантаймы симуляторов, которые можно удалить (освободить место). Только чтение."""
    _need_tools()
    return {"runtimes": sorted(_runtime_list().values(), key=lambda r: (r["short"]))}


def _xcode_install(path):
    inst = next((i for i in mobile.xcode_info()["installs"] if i["path"] == path), None)
    if not inst:
        raise ApiError("Такой Xcode не найден среди установленных", HTTPStatus.NOT_FOUND, code="mob.xcode_missing")
    return inst


def _android():
    a = mobile.android_info()
    if not a.get("sdkmanager") or not a.get("sdk_path"):
        raise ApiError("sdkmanager не найден: сначала установите Android SDK (профиль Flutter)", HTTPStatus.CONFLICT, code="mob.no_sdkmanager")
    return a


# ---------------------------------------------------------------- сборка операций (ничего не запускает)

def build(op, p):
    """→ (подпись job, kind, [шаги start_steps]). Валидирует параметры по реестру сервера."""
    group = op.split(".")[0]
    if group not in KIND:
        raise ApiError("Неизвестная операция", code="mob.unknown_op")
    kind = KIND[group]
    if group != "android":
        _need_tools()  # /usr/bin/xcrun, git, pod... без CLT — заглушки Apple с диалогом

    if op == "xcode.select":
        inst = _xcode_install(p.get("path"))
        dev_dir = os.path.join(inst["path"], "Contents", "Developer")
        def verify(log):
            now = run(["/usr/bin/xcode-select", "-p"], timeout=5)[1].strip()
            log(f"xcode-select -p → {now}")
            if now != dev_dir:
                raise RuntimeError("активный Xcode не изменился")
        return (f"Xcode {inst['version']}: сделать активным", kind,
                [("xcode-select -s (администратор)", _admin(["/usr/bin/xcode-select", "-s", dev_dir],
                                                            "Service Admin: сменить активный Xcode"), {}),
                 ("Проверка", verify, {})])

    if op == "xcode.first_launch":
        info = mobile.xcode_info()
        xb = mobile._which("xcodebuild")  # noqa: SLF001
        if not info["installs"] or not xb:
            raise ApiError("Полный Xcode не установлен", HTTPStatus.CONFLICT, code="mob.no_xcode")
        if (info.get("first_launch") or {}).get("done"):
            raise ApiError("Первый запуск Xcode уже выполнен", HTTPStatus.CONFLICT, code="mob.xcode_first_done")
        def verify(log):
            code = run([xb, "-checkFirstLaunchStatus"], timeout=20)[0]
            log("первый запуск завершён" if code == 0 else "первый запуск всё ещё не завершён")
            if code != 0:
                raise RuntimeError("-checkFirstLaunchStatus != 0")
        return ("Xcode: первый запуск", kind,
                [("xcodebuild -runFirstLaunch (администратор)", _admin([xb, "-runFirstLaunch"],
                                                                       "Service Admin: первый запуск Xcode"), {}),
                 ("Проверка", verify, {})])

    if op == "xcode.download_platform":
        xb = mobile._which("xcodebuild")  # noqa: SLF001
        platform = p.get("platform") or "iOS"
        if platform not in ("iOS", "watchOS", "tvOS", "visionOS"):
            raise ApiError("Неизвестная платформа", code="mob.unknown_platform")
        if not xb:
            raise ApiError("Полный Xcode не установлен", HTTPStatus.CONFLICT, code="mob.no_xcode")
        return (f"Рантайм симулятора {platform}", kind,
                [(f"xcodebuild -downloadPlatform {platform} (несколько ГБ)", [xb, "-downloadPlatform", platform], {})])

    if op in ("sim.boot", "sim.shutdown", "sim.erase"):
        dev = _device(p.get("udid"))
        action = op.split(".")[1]
        need = {"boot": "Shutdown", "shutdown": "Booted", "erase": "Shutdown"}[action]
        if dev["state"] != need:
            raise ApiError(f"Симулятор в состоянии {dev['state']}: для «{action}» нужно {need}", HTTPStatus.CONFLICT, code="mob.sim_state", state=dev['state'], action=action, need=need)
        return (f"Симулятор {dev['name']}: {action}", kind,
                [(f"simctl {action}", ["/usr/bin/xcrun", "simctl", action, dev["udid"]], {})])

    if op == "sim.runtime_delete":
        uuid = p.get("runtime")
        if not isinstance(uuid, str) or not UUID_RE.match(uuid):
            raise ApiError("Неверный идентификатор рантайма", code="mob.bad_runtime")
        rt = _runtime_list().get(uuid.upper())
        if not rt:
            raise ApiError("Рантайм не найден или его нельзя удалить", HTTPStatus.NOT_FOUND, code="mob.runtime_missing")
        if p.get("confirm") != rt["short"]:
            raise ApiError("Введите название рантайма для подтверждения", code="mob.rt_confirm", name=rt["short"])
        busy = [dv["name"] for dv in mobile.xcode_info()["devices"] if dv.get("runtime_id") == rt["runtime_id"] and dv.get("state") == "Booted"]
        if busy:
            raise ApiError("Есть запущенные симуляторы этого рантайма — остановите их", HTTPStatus.CONFLICT, code="mob.rt_busy", names=", ".join(busy)[:80])
        return (f"Удалить рантайм {rt['short']}", kind,
                [("simctl runtime delete", ["/usr/bin/xcrun", "simctl", "runtime", "delete", rt["uuid"]], {})])

    if op == "sim.screenshot":
        dev = _device(p.get("udid"))
        if dev["state"] != "Booted":
            raise ApiError("Симулятор не запущен", HTTPStatus.CONFLICT, code="mob.sim_not_running")
        name = f"{dev['udid'][:8]}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        path = os.path.join(SHOT_DIR, name)
        def shot(log):
            os.makedirs(SHOT_DIR, mode=0o700, exist_ok=True)
            code, _, err = run(["/usr/bin/xcrun", "simctl", "io", dev["udid"], "screenshot", path], timeout=60)
            if code != 0:
                raise RuntimeError(err.strip() or f"exit {code}")
            log(f"Скриншот: {name}")
        return (f"Скриншот {dev['name']}", kind, [("simctl io screenshot", shot, {})])

    if op == "flutter.doctor":
        return ("flutter doctor", kind, [("flutter doctor", [_flutter_bin(), "doctor"], {})])

    if op in ("flutter.pub_get", "flutter.analyze", "flutter.test", "flutter.build_apk"):
        proj = _flutter_project(p.get("project"))
        flutter = _flutter_bin(proj)
        argv = {"flutter.pub_get": ["pub", "get"], "flutter.analyze": ["analyze"], "flutter.test": ["test"],
                "flutter.build_apk": ["build", "apk"]}[op]
        return (f"{os.path.basename(proj)}: flutter {' '.join(argv)}", kind,
                [(f"flutter {' '.join(argv)}", [flutter, *argv], {"cwd": proj})])

    if op == "flutter.channel":
        ch = p.get("channel")
        if ch not in CHANNELS:
            raise ApiError("Канал: stable | beta | master", code="mob.bad_channel")
        flutter = _flutter_bin()
        return (f"Flutter: канал {ch}", kind, [(f"flutter channel {ch}", [flutter, "channel", ch], {}),
                                              ("flutter upgrade", [flutter, "upgrade"], {})])

    if op in ("fvm.install", "fvm.use"):
        fvm = mobile._which("fvm")  # noqa: SLF001
        if not fvm:
            raise ApiError("FVM не установлен (профиль Flutter)", HTTPStatus.CONFLICT, code="mob.no_fvm")
        ver = p.get("version")
        if not isinstance(ver, str) or not FLUTTER_VER_RE.match(ver):
            raise ApiError("Неверная версия Flutter", code="mob.bad_flutter_version")
        if op == "fvm.install":
            return (f"FVM: install {ver}", kind, [(f"fvm install {ver}", [fvm, "install", ver], {})])
        proj = _flutter_project(p.get("project"))
        return (f"{os.path.basename(proj)}: fvm use {ver}", kind, [(f"fvm use {ver}", [fvm, "use", ver, "--force"], {"cwd": proj})])

    if op == "pod.install":
        proj = _flutter_project(p.get("project"))
        pod = mobile._which("pod")  # noqa: SLF001
        ios = os.path.join(proj, "ios")
        cwd = ios if os.path.isfile(os.path.join(ios, "Podfile")) else proj
        if not pod or not os.path.isfile(os.path.join(cwd, "Podfile")):
            raise ApiError("CocoaPods не установлен или нет Podfile", HTTPStatus.CONFLICT, code="mob.no_pods")
        return (f"{os.path.basename(proj)}: pod install", kind, [("pod install", [pod, "install"], {"cwd": cwd})])

    if op == "android.licenses":
        a = _android()
        return ("Android: принять лицензии", kind,
                [("sdkmanager --licenses", _stream([a["sdkmanager"], f"--sdk_root={a['sdk_path']}", "--licenses"],
                                                   stdin_text="y\n" * 60), {})])

    if op == "android.install":
        a = _android()
        pkg = p.get("package")
        if not isinstance(pkg, str) or not SDK_PKG_RE.match(pkg):
            raise ApiError("Неверный идентификатор пакета SDK (пример: platforms;android-35)", code="mob.bad_sdk_pkg")
        return (f"Android SDK: {pkg}", kind,
                [(f"sdkmanager {pkg}", _stream([a["sdkmanager"], f"--sdk_root={a['sdk_path']}", pkg],
                                               stdin_text="y\n" * 60), {})])

    raise ApiError("Неизвестная операция", code="mob.unknown_op")


# ---------------------------------------------------------------- API

# ---------------------------------------------------------------- проверка результата (после исполнения)

RECENT = 600  # секунд: «только что»
VERIFIABLE = ("xcode.select", "xcode.first_launch", "xcode.download_platform", "sim.boot", "sim.shutdown", "sim.erase", "sim.screenshot",
              "sim.runtime_delete", "flutter.pub_get", "flutter.build_apk", "flutter.channel", "fvm.install", "fvm.use", "pod.install",
              "android.licenses", "android.install")
# Без автоматической проверки сознательно: flutter.doctor / analyze / test — это диагностика, результат — код завершения job и его журнал.


def _chk(name, ok, detail=""):
    return {"check": name, "ok": bool(ok), **({"detail": str(detail)[:120]} if detail else {})}


def _recent(path):
    try:
        return time.time() - os.path.getmtime(path) < RECENT
    except OSError:
        return False


def _fresh_info():
    mobile._cache.update(t=0.0, data=None)  # noqa: SLF001 - после действия состояние надо читать заново
    return mobile.xcode_info()


def verify(op, p):
    """Проверить РЕЗУЛЬТАТ мобильной операции по состоянию системы (после исполнения). → {"ok": bool, "checks": [...]}. Ничего не меняет.
    До исполнения проверки честно возвращают ok=false (если состояние ещё не достигнуто)."""
    if op not in VERIFIABLE:
        raise ApiError("This operation has no automatic verification", HTTPStatus.CONFLICT, code="ops.no_verify")
    checks = []
    if op == "xcode.select":
        inst = _xcode_install(p.get("path"))
        now = run(["/usr/bin/xcode-select", "-p"], timeout=5)[1].strip()
        want = os.path.join(inst["path"], "Contents", "Developer")
        checks.append(_chk("the active Xcode is the chosen one", now == want, now))
    elif op == "xcode.first_launch":
        xb = mobile._which("xcodebuild")  # noqa: SLF001
        code = run([xb, "-checkFirstLaunchStatus"], timeout=20)[0] if xb else 1
        checks.append(_chk("Xcode first launch is complete", code == 0))
    elif op == "xcode.download_platform":
        platform = p.get("platform") or "iOS"
        info = _fresh_info()
        checks.append(_chk(f"a {platform} simulator runtime is installed", any(r.get("platform") == platform for r in info["runtimes"])))
    elif op in ("sim.boot", "sim.shutdown", "sim.erase"):
        _fresh_info()
        dev = _device(p.get("udid"))
        want = "Booted" if op == "sim.boot" else "Shutdown"
        checks.append(_chk(f"the simulator is {want}", dev["state"] == want, dev["state"]))
        if op == "sim.erase":
            checks.append(_chk("note: the erased data itself cannot be checked, only that the device exists and is shut down", True))
    elif op == "sim.screenshot":
        prefix = str(p.get("udid") or "")[:8]
        try:
            files = sorted(f for f in os.listdir(SHOT_DIR) if f.startswith(prefix) and SHOT_RE.match(f))
        except OSError:
            files = []
        last = os.path.join(SHOT_DIR, files[-1]) if files else None
        png = False
        if last:
            with open(last, "rb") as f:
                png = f.read(8) == b"\x89PNG\r\n\x1a\n"
        checks.append(_chk("a fresh non-empty PNG exists", bool(last) and png and os.path.getsize(last) > 0 and _recent(last), files[-1] if files else "no file"))
    elif op == "sim.runtime_delete":
        uuid = str(p.get("runtime") or "").upper()
        checks.append(_chk("the runtime is no longer listed", uuid not in _runtime_list()))
    elif op == "flutter.pub_get":
        proj = _flutter_project(p.get("project"))
        checks.append(_chk("pubspec.lock was updated", _recent(os.path.join(proj, "pubspec.lock"))))
        checks.append(_chk(".dart_tool/package_config.json exists", os.path.isfile(os.path.join(proj, ".dart_tool", "package_config.json"))))
    elif op == "flutter.build_apk":
        proj = _flutter_project(p.get("project"))
        apk = os.path.join(proj, "build", "app", "outputs", "flutter-apk", "app-release.apk")
        checks.append(_chk("a fresh app-release.apk exists", os.path.isfile(apk) and os.path.getsize(apk) > 0 and _recent(apk)))
    elif op == "flutter.channel":
        sdk = mobile.flutter_info().get("sdk") or {}
        checks.append(_chk("the SDK is on the chosen channel", sdk.get("channel") == p.get("channel"), sdk.get("channel")))
    elif op == "fvm.install":
        checks.append(_chk("the version is installed in FVM", p.get("version") in mobile._fvm_info()["versions"]))  # noqa: SLF001
    elif op == "fvm.use":
        proj = _flutter_project(p.get("project"))
        pinned = ""
        for rel, key in ((".fvmrc", "flutter"), (os.path.join(".fvm", "fvm_config.json"), "flutterSdkVersion")):
            d = mobile._read_json(os.path.join(proj, rel))  # noqa: SLF001
            if isinstance(d, dict) and d.get(key):
                pinned = str(d[key])
                break
        checks.append(_chk("the project is pinned to this Flutter version", pinned == p.get("version"), pinned))
    elif op == "pod.install":
        proj = _flutter_project(p.get("project"))
        ios = os.path.join(proj, "ios")
        base = ios if os.path.isfile(os.path.join(ios, "Podfile")) else proj
        checks.append(_chk("Podfile.lock was updated", _recent(os.path.join(base, "Podfile.lock"))))
        checks.append(_chk("the Pods folder exists", os.path.isdir(os.path.join(base, "Pods"))))
    elif op == "android.licenses":
        root = mobile._android_sdk_root()  # noqa: SLF001
        lic = os.path.join(root, "licenses") if root else ""
        checks.append(_chk("licence files exist", bool(root) and os.path.isdir(lic) and any(os.scandir(lic)), lic))
    elif op == "android.install":
        root = mobile._android_sdk_root()  # noqa: SLF001
        pkg = str(p.get("package") or "")
        target = os.path.join(root, *pkg.split(";")) if root and SDK_PKG_RE.match(pkg) else ""
        checks.append(_chk("the package folder exists in the SDK", bool(target) and os.path.isdir(target), target))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def run_op(body):
    """POST /api/mobile/op {op, params} → {"job": id}."""
    op, params = body.get("op"), body.get("params") or {}
    if not isinstance(op, str) or not isinstance(params, dict):
        raise ApiError("Неверный запрос", code="mob.bad_request")
    label, kind, steps = build(op, params)
    mobile._cache.update(t=0.0, data=None)  # noqa: SLF001 - после действия состояние надо читать заново
    return {"job": start_steps(label, steps, kind), "label": label}


def screenshot(q):
    """GET /api/mobile/screenshot?name=… → base64 PNG (только из папки скриншотов панели)."""
    name = q.get("name") or ""
    if not name:  # без имени — список (новые первыми)
        try:
            files = sorted((f for f in os.listdir(SHOT_DIR) if SHOT_RE.match(f)), reverse=True)[:20]
        except OSError:
            files = []
        return {"files": files}
    if not SHOT_RE.match(name):
        raise ApiError("Неверное имя файла", code="mob.bad_filename")
    try:
        with open(os.path.join(SHOT_DIR, name), "rb") as f:
            return {"name": name, "png_base64": base64.b64encode(f.read()).decode()}
    except OSError:
        raise ApiError("Скриншот не найден", HTTPStatus.NOT_FOUND, code="mob.shot_missing") from None
