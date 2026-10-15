"""Раннер по требованию (Фаза 5, шаг 5): одноразовая ВМ → ephemeral-раннер → одно задание → ВМ удаляется.

Цикл (всё в одном job, любая ошибка ведёт к удалению ВМ):
  1. клон остановленной ВМ-основы (в ней уже лежат файлы раннера — `vm.prepare_runner`) под именем ci-<случайное>;
  2. запуск, ожидание SSH (дедлайн 2 мин);
  3. токен регистрации источника передаётся В ГОСТЬ через stdin в файл 0600 (не argv, не вывод job, не аудит);
  4. в госте: регистрация с `--ephemeral` и ОДНО задание, блокирующий вызов с лимитом времени;
  5. вывод построчно в job с вырезанным токеном; токен-файл в госте удаляется сразу после чтения;
  6. всегда: остановка и удаление клона.
Это L3: регистрация даёт внешнему серверу CI право присылать код в ВМ. Код задания исполняется ТОЛЬКО внутри гостя (NAT-сеть:
гость видит интернет и локальную сеть — ограничивать её надо отдельно). Агентам не открыто. Незанятый ephemeral-раннер, у которого
ВМ удалена по таймауту, может остаться «офлайн» в списке раннеров сервера — его убирают на стороне сервера (GitHub делает это сам).
"""
import os
import re
import secrets
import shlex
import socket
import signal
import subprocess
import threading
import time
from http import HTTPStatus
from urllib.parse import urlsplit

import ci_api
import core
import runners
import vm
from core import ApiError, start_steps

LABEL_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,60}$")
MAX_LABELS = 5
DEFAULT_MINUTES = 60
MAX_MINUTES = 240
TOKEN_FILE = ".ci-token"


def scrub(text, secret):
    """Вырезать секрет из строки вывода."""
    if secret and len(secret) >= 8:
        text = text.replace(secret, "***")
    return text


def guest_command(provider_id, source, name, labels):
    """Команда для sh в госте. Токен читается из файла и сразу удаляется; сама команда токена не содержит."""
    d = vm.GUEST_DIR
    read_tok = f'export PATH=/usr/local/bin:$PATH; T=$(cat ~/{TOKEN_FILE}); rm -f ~/{TOKEN_FILE}; cd ~/{d} || exit 1; '
    lab = ",".join(labels)
    url = source["url"]
    if provider_id == "gitea":
        return (read_tok + f'./gitea-runner register --no-interactive --ephemeral --instance {shlex.quote(url)} --token "$T" '
                f'--name {shlex.quote(name)} --labels {shlex.quote(lab)} && unset T && exec ./gitea-runner daemon --once')
    if provider_id == "github":
        target = url + ("" if source["scope"] == "instance" else "/" + source["path"])
        return (read_tok + f'./config.sh --unattended --ephemeral --replace --url {shlex.quote(target)} --token "$T" '
                f'--name {shlex.quote(name)}' + (f' --labels {shlex.quote(lab)}' if lab else '') + ' && unset T && exec ./run.sh')
    raise ApiError("Unknown CI provider", HTTPStatus.BAD_REQUEST, code="runner.provider")


def _stream_guest(ip, command, secret, log, minutes, scrubbed=None):
    """ssh: токен уходит в файл гостя через stdin; затем основная команда, вывод построчно (с вырезанным токеном); по дедлайну процесс убивается."""
    env = dict(core.ENV, SSHPASS="admin")
    for attempt in range(3):  # сразу после загрузки гостя ssh иногда рвёт первое соединение — повторяем
        w = subprocess.run([vm._sshpass(), "-e", "ssh", *vm.SSH_OPTS, f"{vm.GUEST_USER}@{ip}", f"umask 077; cat > ~/{TOKEN_FILE}"],
                           input=(secret + "\n").encode(), capture_output=True, env=env, timeout=30)
        if w.returncode == 0:
            break
        time.sleep(3)
    else:
        raise RuntimeError("cannot hand the token to the VM")
    p = subprocess.Popen([vm._sshpass(), "-e", "ssh", *vm.SSH_OPTS, f"{vm.GUEST_USER}@{ip}", "sh", "-c", shlex.quote(command)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, bufsize=1,
                         start_new_session=True)
    timed_out = threading.Event()

    def kill_group():
        timed_out.set()
        try:
            os.killpg(p.pid, signal.SIGKILL)  # sshpass и его ssh — вся группа, иначе ssh удерживает pipe
        except OSError:
            pass
    timer = threading.Timer(minutes * 60, kill_group)
    timer.start()
    try:
        for line in p.stdout:
            text = line.rstrip("\n")
            for sec in (scrubbed or [secret]):
                text = scrub(text, sec)
            log(text)
        rc = p.wait()
    finally:
        timer.cancel()
        if p.poll() is None:
            kill_group()
    if timed_out.is_set():
        raise RuntimeError(f"time limit of {minutes} min reached; the VM is being deleted")
    if rc:
        raise RuntimeError(f"the runner exited with code {rc}")


def net_args(source, isolate):
    """Аргументы tart для сетевой изоляции гостя (softnet): наружу и в интернет можно, в частные сети — нет, кроме сервера CI.
    Адрес сервера — хоть IP, хоть имя: имя резолвится на хосте, разрешаются ВСЕ его IPv4-адреса (/32)."""
    if not isolate:
        return []
    u = urlsplit(source["url"])
    host = u.hostname
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80), socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        raise RuntimeError(f"cannot resolve the CI server host '{host}' for the network allow-list") from None
    ips = sorted({i[4][0] for i in infos})
    return ["--net-softnet", "--net-softnet-allow=" + ",".join(f"{ip}/32" for ip in ips)]


def _preflight(ip, source):
    """Гость должен достучаться до сервера CI — иначе ждать задание бессмысленно (DNS в госте, сеть, изоляция)."""
    code, out = vm._guest(ip, f"curl -s -m 12 -o /dev/null -w '%{{http_code}}' {shlex.quote(source['url'] + '/')}", timeout=30)
    if code != 0 or out.strip() in ("", "000"):
        raise RuntimeError(f"the guest cannot reach the CI server {source['url']} (DNS or network); with network isolation the "
                           "server must be reachable at an address that the host resolves — check the address or isolate=false")


def _spawn(base, source, labels, minutes, isolate):
    def step(log):
        d = vm.driver()
        exe = d.binary()
        if d.status(base)["running"]:
            raise RuntimeError("the base VM is running now; stop it first")
        stored = runners.read_token(source["id"])
        if not stored:
            raise RuntimeError("the source has no stored token")
        api = None
        secret = stored
        if source.get("auth", "registration") == "api":  # токен доступа → свежий регистрационный токен
            api = ci_api.client(source, stored)
            try:
                secret = api.registration_token()
            except ci_api.CIError as e:
                raise RuntimeError("cannot get a registration token: " + e.message) from None
        scrubbed = [x for x in (stored, secret) if x]
        clone = "ci-" + secrets.token_hex(4)
        extra = net_args(source, isolate)
        log("network isolation (softnet): ON — the guest can reach the internet and the CI server only" if extra
            else "WARNING: network isolation is OFF — the guest can reach your local network")
        log(f"cloning {base} → {clone}")
        try:
            cl = subprocess.run([exe, "clone", base, clone], capture_output=True, timeout=300)
            if cl.returncode:
                raise RuntimeError("tart clone failed: " + cl.stderr.decode("utf-8", "replace").strip()[:200])
            if d.status(base)["running"]:  # основу включили во время копирования — копия могла получиться неконсистентной
                raise RuntimeError("the base VM was started during cloning; try again")
            vm._start_detached(exe, clone, extra)(log)
            deadline = time.monotonic() + 120
            ip = None
            while time.monotonic() < deadline:
                try:
                    ip = ip or d.ip(clone)
                    if vm._guest(ip, "true", timeout=15)[0] == 0:
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("the VM did not accept SSH in 2 minutes")
            _preflight(ip, source)
            log("the guest can reach the CI server")
            log(f"registering ephemeral runner '{clone}' on {source['url']} and waiting for one job (up to {minutes} min)…")
            _stream_guest(ip, guest_command(source["provider"], source, clone, labels), secret, log, minutes, scrubbed)
            log("job finished")
        finally:
            log(f"deleting {clone}…")
            try:
                exists = any(v["name"] == clone for v in d.list())
            except Exception:  # noqa: BLE001
                exists = True
            if exists:  # клон мог не создаться совсем, а мог остаться недокопированным
                vm._stop_vm(exe, clone, log)  # клон удаляется — штатное выключение не нужно
                r = subprocess.run([exe, "delete", clone], capture_output=True, timeout=60)
                log("VM deleted" if r.returncode == 0 else f"WARNING: could not delete {clone}; remove it by hand")
            else:
                log("no clone to delete")
            if api:  # брошенный раннер (задание не пришло) не должен висеть «офлайн» на сервере CI
                try:
                    for rn in api.list_runners():
                        if rn["name"] == clone:
                            api.delete_runner(rn["id"])
                            log(f"removed the leftover runner '{clone}' from the CI server")
                except ci_api.CIError as e:
                    log(f"WARNING: could not remove runner '{clone}' from the CI server: {e.message}")
    return step


def _validate(body):
    """POST /api/runners/spawn {source, vm, labels?, minutes?, confirm} → {"job": id}."""
    d = vm.driver()
    if not d.available() or not vm._sshpass():
        raise ApiError("tart and sshpass are required", HTTPStatus.CONFLICT, code="vm.no_sshpass")
    src = next((s for s in runners._load()["sources"] if s["id"] == body.get("source")), None)  # noqa: SLF001
    if not src:
        raise ApiError("Source not found", HTTPStatus.NOT_FOUND, code="runner.source_missing")
    if body.get("confirm") != src["name"]:
        raise ApiError("Type the source name to confirm", code="runner.confirm")
    if not runners.read_token(src["id"]):
        raise ApiError("The source has no stored token", HTTPStatus.CONFLICT, code="runner.no_token")
    base = body.get("vm")
    v = vm._local(d, base)  # noqa: SLF001
    if v["running"]:
        raise ApiError("Stop the VM first", HTTPStatus.CONFLICT, code="vm.running")
    if base.startswith("ci-"):
        raise ApiError("Use a base VM, not a disposable ci-* clone", code="runner.bad_base")
    labels = body.get("labels") or ([] if src["provider"] == "github" else ["macos:host"])
    if (not isinstance(labels, list) or len(labels) > MAX_LABELS or not all(isinstance(x, str) and LABEL_RE.match(x) for x in labels)
            or (src["provider"] == "gitea" and not labels)):
        raise ApiError("Labels: up to 5 items like macos:host", code="runner.bad_labels")
    minutes = body.get("minutes", DEFAULT_MINUTES)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        raise ApiError(f"Time limit: 1-{MAX_MINUTES} minutes", code="runner.bad_minutes", max=MAX_MINUTES)
    if not runners.provider(src["provider"]).installed():
        raise ApiError("Install the runner files of this provider first", HTTPStatus.CONFLICT, code="vm.runner_missing")
    isolate = body.get("isolate", "auto")
    if isolate not in (True, False, "auto"):
        raise ApiError("isolate must be true, false or auto", code="runner.bad_isolate")
    ready = vm.softnet_ready()
    if isolate is True and not ready:
        raise ApiError("Network isolation needs softnet with root rights", HTTPStatus.CONFLICT, code="runner.no_softnet")
    isolate = ready if isolate == "auto" else isolate
    return src, labels, minutes, isolate, base


def start(body):
    """POST /api/runners/spawn {source, vm, labels?, minutes?, isolate?, confirm} → {"job": id}."""
    src, labels, minutes, isolate, base = _validate(body)
    label = f"On-demand runner ({src['name']})"
    return {"job": start_steps(label, [("clone, register, run one job, delete", _spawn(base, src, labels, minutes, isolate), {})], "runner-spawn")}


# ---------------------------------------------------------------- самотест: всё через панель

WORKFLOWS = {
    "gitea": (".gitea/workflows/selftest.yaml", "macos"),
    "github": (".github/workflows/selftest.yml", "[self-hosted, macOS]"),
}


def _workflow(provider_id):
    path, runs_on = WORKFLOWS[provider_id]
    return path, f"""name: selftest
on: [push]
jobs:
  hello:
    runs-on: {runs_on}
    steps:
      - run: |
          uname -a
          echo "node=$(node --version 2>&1) git=$(git --version 2>&1)"
          echo selftest-ok
"""


def _selftest(base, source, minutes, isolate):
    def step(log):
        stored = runners.read_token(source["id"])
        if source.get("auth", "registration") != "api" or not stored:
            raise RuntimeError("the self-test needs a source with an access token (auth=api)")
        api = ci_api.client(source, stored)
        created = None
        try:
            full, branch = api.create_repo("ci-selftest-" + secrets.token_hex(3))
            created = full  # только репозиторий, созданный самим самотестом, удаляется в finally
            log(f"created the test repository {full}")
            path, text = _workflow(source["provider"])
            sha = api.put_file(full, path, text, "selftest workflow", branch)
            log(f"pushed {path} to {full} (commit {sha[:8]}): a workflow run is queued")
            _spawn(base, source, [] if source["provider"] == "github" else ["macos:host"], minutes, isolate)(log)
            end = time.monotonic() + 120
            run = None
            while time.monotonic() < end:  # ищем запуск именно для НАШЕГО коммита
                run = api.run_for_commit(full, sha)
                if run and run["status"] in ("completed", "success", "failure", "cancelled", "skipped"):
                    break
                time.sleep(4)
            log(f"workflow run for commit {sha[:8]}: {run}")
            if not run or not (run.get("conclusion") == "success" or run.get("status") == "success"):
                raise RuntimeError(f"the workflow did not succeed: {run}")
            log("SELFTEST PASSED: the runner started in a disposable VM, ran the workflow and was removed")
        except ci_api.CIError as e:
            raise RuntimeError("CI server: " + e.message) from None
        finally:
            if created:
                try:
                    api.delete_repo(created)
                    log(f"deleted the test repository {created}")
                except ci_api.CIError as e:
                    log(f"NOTE: the test repository {created} was left ({e.message}); delete it by hand")
    return step


def _direct_summary(kind, body):
    import plans
    s = runners.get_source(body.get("source")) if isinstance(body.get("source"), str) else None
    name = s["name"] if s else "?"
    url = s["url"] if s else "?"
    ru = f"Запустить «{kind}»: источник «{name}» ({url}), ВМ-основа «{body.get('vm')}», до {body.get('minutes', DEFAULT_MINUTES)} мин. Код из workflow будет выполнен в ВМ."
    en = f"Run \"{kind}\": source \"{name}\" ({url}), base VM \"{body.get('vm')}\", up to {body.get('minutes', DEFAULT_MINUTES)} min. Workflow code will run in the VM."
    return {"ru": ru, "en": en}


def _gate(kind, body):
    """Прямой вызов HTTP (кнопка в панели ИЛИ терминал агента): после проверок — обязательный системный диалог."""
    import plans
    if plans.confirm_direct(_direct_summary(kind, body)) != "approve":
        raise ApiError("The action was not approved in the system dialog", HTTPStatus.FORBIDDEN, code="plan.dialog_denied")


def start_http(body):
    _validate(body)
    _gate("on-demand runner", body)
    return start(body)


def selftest_http(body):
    _validate(dict(body, labels=None))
    _gate("CI self-test", body)
    return selftest(body)


def selftest(body):
    """POST /api/runners/selftest {source, vm, minutes?, confirm} → {"job": id}. Создаёт репозиторий, кладёт workflow, запускает раннер по
    требованию, проверяет результат и убирает за собой."""
    src, _labels, minutes, isolate, base = _validate(dict(body, labels=None))  # те же проверки, что у runner.spawn
    if src.get("auth", "registration") != "api":
        raise ApiError("The self-test needs a source with an access token", HTTPStatus.CONFLICT, code="runner.need_api_auth")
    if src["scope"] == "repo":  # в настоящий репозиторий пользователя самотест ничего не коммитит
        raise ApiError("The self-test creates its own test repository, so it needs a source of scope 'instance' or 'org'",
                       HTTPStatus.CONFLICT, code="runner.selftest_scope")
    label = f"CI self-test ({src['name']})"
    return {"job": start_steps(label, [("repo, workflow, runner, check, cleanup", _selftest(base, src, minutes, isolate), {})], "runner-spawn")}
