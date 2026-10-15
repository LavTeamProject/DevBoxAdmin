"""Manajemen Docker lengkap: engine, statistik live, container (inspect, logs,
exec, run), compose (daftar, edit, up/down/pull/build, pembuat compose dari
template), image, volume, network, dan pembersihan disk."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

from core import DATA_DIR, ENV, HOME, ApiError, loads_or, output, run, start_job

DOCKER = shutil.which("docker", path=ENV["PATH"] + ":/usr/local/bin") or "/usr/local/bin/docker"
ORB = shutil.which("orb", path=ENV["PATH"] + ":/usr/local/bin")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$")
BACKUP_DIR = os.path.join(DATA_DIR, "backups", "compose")
SECRET_RE = re.compile(r"(PASS|SECRET|TOKEN|KEY|CREDENTIAL|PRIVATE)", re.I)


def docker(*args, timeout=30):
    return run([DOCKER, *args], timeout=timeout)


def json_lines(*args, timeout=30):
    code, out, err = docker(*args, "--format", "{{json .}}", timeout=timeout)
    if code != 0:
        raise ApiError(err.strip() or "docker завершился с ошибкой", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "docker.failed")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def labels_of(text):
    return dict(kv.split("=", 1) for kv in (text or "").split(",") if "=" in kv)


def size_bytes(text):
    """'1.5GB' / '213kB (virtual 171MB)' / '9.453MB' -> bytes."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?i?B)", text or "")
    if not m:
        return 0
    unit = {"B": 1, "kB": 1e3, "KB": 1e3, "KiB": 1024, "MB": 1e6, "MiB": 1024 ** 2, "GB": 1e9, "GiB": 1024 ** 3,
            "TB": 1e12, "TiB": 1024 ** 4}.get(m[2], 1)
    return int(float(m[1]) * unit)


# ---------------------------------------------------------------- ringkasan

def _compose_version():
    code, out, _ = run([DOCKER, "compose", "version", "--short"], timeout=5)
    return out.strip() if code == 0 and out.strip() else None  # плагина compose может не быть (docker.io на Linux)


def engine():
    info = {"cli": os.path.exists(DOCKER), "orbstack": bool(ORB), "running": False}
    if not info["cli"]:
        return info
    try:
        code, out, _ = docker("info", "--format", "{{json .}}", timeout=8)
    except subprocess.TimeoutExpired:
        return info
    if code != 0:
        return info
    d = json.loads(out)
    info.update(running=True, version=d.get("ServerVersion"), cpus=d.get("NCPU"), memory=d.get("MemTotal"),
                os=d.get("OperatingSystem"), kernel=d.get("KernelVersion"), driver=d.get("Driver"),
                name=d.get("Name"), containers=d.get("Containers"), running_count=d.get("ContainersRunning"),
                images=d.get("Images"), compose=_compose_version())
    return info


def overview(q):
    e = engine()
    if not e["running"]:
        return {"engine": e}
    with ThreadPoolExecutor(3) as pool:
        cf = pool.submit(json_lines, "ps", "-a", "--no-trunc")
        pf = pool.submit(lambda: loads_or(output([DOCKER, "compose", "ls", "-a", "--format", "json"]), []))
        cs, projects = cf.result(), pf.result()
    containers = []
    for c in cs:
        lb = labels_of(c.get("Labels"))
        containers.append({
            "id": c["ID"][:12], "name": c["Names"], "image": c["Image"], "state": c["State"], "status": c["Status"],
            "ports": c.get("Ports", ""), "created": c.get("RunningFor"), "networks": c.get("Networks", ""),
            "project": lb.get("com.docker.compose.project"), "service": lb.get("com.docker.compose.service"),
            "health": "healthy" if "(healthy)" in c["Status"] else "unhealthy" if "(unhealthy)" in c["Status"] else None,
        })
    for p in projects:
        p["files"] = [f for f in p.get("ConfigFiles", "").split(",") if f]
        p["dir"] = os.path.dirname(p["files"][0]) if p["files"] else None
        p["name"] = p.pop("Name")
        p["status"] = p.pop("Status", "")
    return {"engine": e, "containers": containers, "projects": projects}


def stats(q):
    """Satu sampel `docker stats` (angka mentah + bytes)."""
    rows = json_lines("stats", "--no-stream", "--no-trunc", timeout=20)
    out = []
    for r in rows:
        mem_used, _, mem_limit = (r.get("MemUsage") or "").partition(" / ")
        rx, _, tx = (r.get("NetIO") or "").partition(" / ")
        br, _, bw = (r.get("BlockIO") or "").partition(" / ")
        out.append({"id": r["ID"][:12], "name": r["Name"], "cpu": float((r.get("CPUPerc") or "0").rstrip("%") or 0),
                    "mem": size_bytes(mem_used), "mem_limit": size_bytes(mem_limit),
                    "mem_pct": float((r.get("MemPerc") or "0").rstrip("%") or 0),
                    "net_rx": size_bytes(rx), "net_tx": size_bytes(tx), "blk_r": size_bytes(br), "blk_w": size_bytes(bw),
                    "pids": int(r.get("PIDs") or 0)})
    return {"t": int(time.time() * 1000), "stats": out}


def disk(q):
    code, out, err = docker("system", "df", "-v", "--format", "json", timeout=60)
    if code != 0:
        raise ApiError(err.strip(), HTTPStatus.INTERNAL_SERVER_ERROR)
    d = json.loads(out)
    summary = {r["Type"]: r for r in json_lines("system", "df")}
    return {
        "summary": [{"type": t, "count": int(r.get("TotalCount") or 0), "active": int(r.get("Active") or 0),
                     "size": size_bytes(r.get("Size")), "reclaimable": size_bytes(r.get("Reclaimable"))}
                    for t, r in summary.items()],
        "images": [{"id": i["ID"].split(":")[-1][:12], "repo": i["Repository"], "tag": i["Tag"], "size": size_bytes(i["Size"]),
                    "containers": int(i.get("Containers") or 0), "created": i.get("CreatedSince")} for i in d.get("Images", [])],
        "volumes": [{"name": v["Name"], "size": size_bytes(v.get("Size")), "links": int(v.get("Links") or 0),
                     "project": labels_of(v.get("Labels")).get("com.docker.compose.project"), "driver": v.get("Driver")}
                    for v in d.get("Volumes", [])],
        "build_cache": sum(size_bytes(b.get("Size")) for b in d.get("BuildCache", [])),
    }


def networks(q):
    nets = json_lines("network", "ls")
    return {"networks": [{"id": n["ID"], "name": n["Name"], "driver": n["Driver"], "scope": n["Scope"],
                          "builtin": n["Name"] in ("bridge", "host", "none"),
                          "project": labels_of(n.get("Labels")).get("com.docker.compose.project")} for n in nets]}


# ---------------------------------------------------------------- container

def inspect(q):
    cid = q.get("id", "")
    if not ID_RE.match(cid):
        raise ApiError("Недопустимый id", code="docker.bad_id")
    code, out, err = docker("inspect", cid)
    if code != 0:
        raise ApiError(err.strip(), HTTPStatus.NOT_FOUND)
    c = json.loads(out)[0]
    cfg, hc, ns = c.get("Config", {}), c.get("HostConfig", {}), c.get("NetworkSettings", {})
    env = []
    for item in cfg.get("Env") or []:
        k, _, v = item.partition("=")
        env.append({"key": k, "value": v, "secret": bool(SECRET_RE.search(k))})
    ports = []
    for cport, binds in (ns.get("Ports") or {}).items():
        for b in binds or [{}]:
            ports.append({"container": cport, "host": f"{b.get('HostIp', '')}:{b['HostPort']}" if b.get("HostPort") else None})
    if not ports:  # container mati: pakai konfigurasi port binding
        for cport, binds in (hc.get("PortBindings") or {}).items():
            for b in binds or [{}]:
                ports.append({"container": cport, "host": b.get("HostPort")})
    return {
        "id": c["Id"][:12], "name": c["Name"].lstrip("/"), "image": cfg.get("Image"), "created": c.get("Created"),
        "state": c.get("State", {}), "command": " ".join((c.get("Path") and [c["Path"]] or []) + (c.get("Args") or [])),
        "workdir": cfg.get("WorkingDir"), "env": env, "ports": ports,
        "mounts": [{"type": m.get("Type"), "source": m.get("Source") or m.get("Name"), "dest": m.get("Destination"),
                    "rw": m.get("RW")} for m in c.get("Mounts", [])],
        "networks": [{"name": n, "ip": v.get("IPAddress"), "aliases": v.get("Aliases") or []}
                     for n, v in (ns.get("Networks") or {}).items()],
        "restart": (hc.get("RestartPolicy") or {}).get("Name"), "labels": cfg.get("Labels") or {},
        "health": (c.get("State", {}).get("Health") or {}).get("Status"),
    }


def logs(q):
    cid, tail_n = q.get("id", ""), int(q.get("tail", 300) or 300)
    if not ID_RE.match(cid):
        raise ApiError("Недопустимый id", code="docker.bad_id")
    _, out, err = docker("logs", "--tail", str(min(tail_n, 5000)), "--timestamps", cid, timeout=20)
    return {"log": out + err}


def project_logs(q):
    name = q.get("name", "")
    if not ID_RE.match(name):
        raise ApiError("Недопустимое имя", code="docker.bad_name")
    _, out, err = docker("compose", "-p", name, "logs", "--tail", "200", "--no-color", "--timestamps", timeout=30)
    return {"log": out + err}


def open_terminal(cid, shell):
    """Buka Terminal.app dengan `docker exec -it <id> <shell>`."""
    cmd = f"{DOCKER} exec -it {cid} {shell}"
    script = f'tell application "Terminal"\n activate\n do script "{cmd}"\nend tell'
    code, out, err = run(["osascript", "-e", script], timeout=20)
    if code != 0:
        raise ApiError(err.strip() or "Не удалось открыть Terminal", HTTPStatus.INTERNAL_SERVER_ERROR, code=None if err.strip() else "docker.terminal_failed")
    return {"ok": True}


def action(body):
    act, target = body.get("action"), str(body.get("target", ""))
    if act in ("engine-start", "engine-stop"):
        if not ORB:
            raise ApiError("OrbStack CLI (orb) не найден", code="docker.orb_missing")
        return {"job": start_job(f"orb {act[7:]}", [ORB, act[7:]], "docker")}
    prunes = {
        "image-prune": ["image", "prune", "-f"], "image-prune-all": ["image", "prune", "-af"],
        "container-prune": ["container", "prune", "-f"], "volume-prune": ["volume", "prune", "-f"],
        "network-prune": ["network", "prune", "-f"], "builder-prune": ["builder", "prune", "-f"],
        "system-prune": ["system", "prune", "-f"],
    }
    if act in prunes:
        return {"job": start_job("docker " + " ".join(prunes[act]), [DOCKER, *prunes[act]], "docker")}
    if not ID_RE.match(target):
        raise ApiError("Недопустимая цель", code="docker.bad_target")
    if act == "terminal":
        shell = body.get("shell") if body.get("shell") in ("sh", "bash", "zsh", "ash") else "sh"
        return open_terminal(target, shell)
    single = {  # perintah cepat, dijalankan langsung
        "start": ["start"], "stop": ["stop"], "restart": ["restart"], "pause": ["pause"], "unpause": ["unpause"],
        "kill": ["kill"], "rm": ["rm", "-f"], "image-rm": ["rmi"], "volume-rm": ["volume", "rm"],
        "network-rm": ["network", "rm"],
    }
    if act in single:
        return {"job": start_job(f"docker {' '.join(single[act])} {target}", [DOCKER, *single[act], target], "docker")}
    if act == "image-pull":
        return {"job": start_job(f"docker pull {target}", [DOCKER, "pull", target], "docker")}
    compose = {"compose-up": ["up", "-d"], "compose-start": ["start"], "compose-stop": ["stop"],
               "compose-restart": ["restart"], "compose-down": ["down"], "compose-down-v": ["down", "-v"],
               "compose-pull": ["pull"], "compose-build": ["build"], "compose-up-build": ["up", "-d", "--build"]}
    if act in compose:
        files = body.get("files") or []
        fargs = []
        for f in files:  # file compose harus benar-benar ada
            if not os.path.isfile(f):
                raise ApiError(f"Файл compose не найден: {f}", code="docker.compose_file_missing", file=f)
            fargs += ["-f", f]
        cmd = [DOCKER, "compose", "-p", target, *fargs, *compose[act]]
        return {"job": start_job(f"compose {target}: {' '.join(compose[act])}", cmd, "docker",
                                 cwd=os.path.dirname(files[0]) if files else None)}
    raise ApiError("Недопустимое действие", code="docker.bad_action")


PORT_RE = re.compile(r"^(\d{1,5}:)?\d{1,5}(:\d{1,5})?(/(tcp|udp))?$|^[\d.]+:\d{1,5}:\d{1,5}(/(tcp|udp))?$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def run_container(body):
    """docker run -d dari form."""
    image = str(body.get("image", "")).strip()
    if not ID_RE.match(image):
        raise ApiError("Недопустимое имя образа", code="docker.bad_image")
    cmd = [DOCKER, "run", "-d"]
    name = str(body.get("name", "")).strip()
    if name:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ApiError("Недопустимое имя контейнера", code="docker.bad_container_name")
        cmd += ["--name", name]
    for p in body.get("ports") or []:
        if not PORT_RE.match(p.strip()):
            raise ApiError(f"Недопустимый формат порта: {p} (пример 8080:80)", code="docker.bad_port", port=p)
        cmd += ["-p", p.strip()]
    for e in body.get("env") or []:
        k, _, v = e.partition("=")
        if not ENV_KEY_RE.match(k.strip()):
            raise ApiError(f"Недопустимое имя переменной окружения: {k}", code="docker.bad_env", name=k)
        cmd += ["-e", f"{k.strip()}={v}"]
    for v in body.get("volumes") or []:
        src, _, dest = v.partition(":")
        if not dest.startswith("/"):
            raise ApiError(f"Недопустимый формат тома: {v} (пример ./data:/data или имя_тома:/data)", code="docker.bad_volume", volume=v)
        src = os.path.expanduser(src)
        cmd += ["-v", f"{src}:{dest}"]
    restart = body.get("restart") or "no"
    if restart not in ("no", "always", "unless-stopped", "on-failure"):
        raise ApiError("Недопустимая политика перезапуска", code="docker.bad_restart")
    cmd += ["--restart", restart, image]
    extra = str(body.get("command") or "").strip()
    if extra:
        import shlex
        cmd += shlex.split(extra)
    return {"job": start_job(f"docker run {image}", cmd, "docker")}


def exec_cmd(body):
    """Console: jalankan satu perintah di dalam container (non-interaktif)."""
    cid, command = str(body.get("id", "")), str(body.get("command", "")).strip()
    workdir = str(body.get("workdir") or "").strip()
    if not ID_RE.match(cid) or not command:
        raise ApiError("Недопустимый контейнер или команда", code="docker.bad_exec")
    if len(command) > 4000:
        raise ApiError("Команда слишком длинная", code="docker.cmd_too_long")
    args = [DOCKER, "exec"]
    if workdir:
        if not workdir.startswith("/"):
            raise ApiError("Рабочая папка должна быть абсолютным путём", code="docker.workdir_not_abs")
        args += ["-w", workdir]
    # cetak folder kerja di akhir agar `cd` di console bisa diikuti
    script = f"{command}\n__rc=$?; printf '\\n__SA_PWD__%s' \"$(pwd)\"; exit $__rc"
    try:
        code, out, err = run(args + [cid, "sh", "-c", script], timeout=120)
    except subprocess.TimeoutExpired:
        raise ApiError("Команда превысила 120 секунд (для долгих процессов используйте интерактивный Terminal)", HTTPStatus.REQUEST_TIMEOUT, code="docker.exec_timeout")
    m = re.search(r"\n?__SA_PWD__(.*)$", out)
    pwd = m[1].strip() if m else workdir
    out = out[:m.start()] if m else out
    return {"code": code, "output": (out + err)[-100_000:], "pwd": pwd}


# ---------------------------------------------------------------- remote host (docker context)

def contexts(q):
    rows = json.loads("[" + ",".join(l for l in output([DOCKER, "context", "ls", "--format", "{{json .}}"]).splitlines()
                                      if l.startswith("{")) + "]")
    return {"contexts": [{"name": r["Name"], "current": r.get("Current", False), "endpoint": r.get("DockerEndpoint"),
                          "description": r.get("Description", ""), "error": r.get("Error", "")} for r in rows]}


def context_info():
    """Активный контекст Docker: {name, endpoint, remote}. remote=True, если движок НЕ на этом Mac (ssh://, tcp://, …); доступ к удалённому
    движку равен root на том хосте, поэтому операции каталога/агентов с ним не работают. Если определить нельзя — считаем удалённым (fail closed)."""
    host = ENV.get("DOCKER_HOST")
    name = ENV.get("DOCKER_CONTEXT")
    endpoint = host or ""
    if not endpoint:  # так же, как CLI: DOCKER_CONTEXT, иначе текущий контекст
        code, out, _ = docker("context", "inspect", *([name] if name else []), "--format", "{{.Name}}\t{{.Endpoints.docker.Host}}")
        if code == 0 and "\t" in out:
            name, endpoint = out.strip().split("\t", 1)
    return {"name": "DOCKER_HOST" if host else (name or "unknown"), "endpoint": endpoint, "remote": not endpoint.startswith("unix://")}


def require_local_context():
    ci = context_info()
    if ci["remote"]:
        raise ApiError("Docker context is remote or unknown: this operation works only with the local engine", HTTPStatus.CONFLICT,
                       code="docker.remote_context", name=str(ci["name"]), endpoint=str(ci["endpoint"])[:60])
    return ci


def container_names(host=None):
    """Имена и короткие id ВСЕХ контейнеров текущего (локального) движка."""
    out = set()
    for c in json_lines(*(["--host", host] if host else []), "ps", "-a", "--no-trunc"):
        out.update(c["Names"].split(","))
        out.add(c["ID"][:12])
        out.add(c["ID"])
    return out


def context_action(body):
    act, name = body.get("action"), str(body.get("name", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ApiError("Недопустимое имя context", code="docker.bad_context")
    if act == "create":
        host = str(body.get("host", "")).strip()
        if not re.fullmatch(r"(ssh://)?[A-Za-z0-9._-]+@[A-Za-z0-9._-]+(:\d+)?|tcp://[A-Za-z0-9._-]+:\d+", host):
            raise ApiError("Недопустимый хост (пример: ssh://root@203.0.113.10 или user@server.com)", code="docker.bad_host")
        if not host.startswith(("ssh://", "tcp://")):
            host = "ssh://" + host
        code, out, err = docker("context", "create", name, "--docker", f"host={host}",
                                "--description", str(body.get("description") or "")[:100])
    elif act == "use":
        code, out, err = docker("context", "use", name)
    elif act == "rm":
        code, out, err = docker("context", "rm", "-f", name)
    elif act == "test":
        code, out, err = docker("--context", name, "info", "--format", "{{.ServerVersion}} · {{.OperatingSystem}}", timeout=25)
    else:
        raise ApiError("Недопустимое действие", code="docker.bad_action")
    if code != 0:
        raise ApiError((err or out).strip() or "Ошибка", HTTPStatus.BAD_GATEWAY, code=None if (err or out).strip() else "docker.context_failed")
    return {"ok": True, "output": out.strip()}


# ---------------------------------------------------------------- compose file

def compose_files():
    projects = loads_or(output([DOCKER, "compose", "ls", "-a", "--format", "json"]), [])
    return {f for p in projects for f in p.get("ConfigFiles", "").split(",") if f}


def compose_read(q):
    path = q.get("path", "")
    if path not in compose_files():
        raise ApiError("Неизвестный файл compose", HTTPStatus.FORBIDDEN, code="docker.compose_unknown")
    with open(path, errors="replace") as f:
        return {"path": path, "content": f.read()}


def compose_validate_text(content, workdir):
    """Validasi YAML compose dengan `docker compose config -q` di folder tujuan."""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=workdir if os.path.isdir(workdir) else None,
                                     prefix=".compose-check-", delete=False) as t:
        t.write(content)
    try:
        code, out, err = docker("compose", "-f", t.name, "config", "-q", timeout=30)
    finally:
        os.unlink(t.name)
    msg = (out + err).replace(t.name, "compose.yaml").strip()
    return code == 0, msg or "OK"


def compose_validate(body):
    ok, msg = compose_validate_text(body.get("content", ""), os.path.expanduser(body.get("dir") or HOME))
    return {"ok": ok, "output": msg}


def compose_save(body):
    """Simpan compose: file lama (dari daftar project) atau file baru di folder pilihan."""
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError("Содержимое compose пусто", code="docker.compose_empty")
    if body.get("path"):
        path = body["path"]
        if path not in compose_files():
            raise ApiError("Неизвестный файл compose", HTTPStatus.FORBIDDEN, code="docker.compose_unknown")
    else:
        folder = os.path.realpath(os.path.expanduser(str(body.get("dir") or "")))
        name = str(body.get("project") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            raise ApiError("Имя проекта: только строчные буквы, цифры, - и _", code="docker.bad_project")
        if body.get("subfolder", True):
            folder = os.path.join(folder, name)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "compose.yaml")
        if os.path.exists(path) and not body.get("overwrite"):
            raise ApiError(f"{path} уже существует. Отметьте «перезаписать», чтобы заменить файл.", HTTPStatus.CONFLICT, code="docker.compose_exists", path=path)
    ok, msg = compose_validate_text(content, os.path.dirname(path))
    if not ok and not body.get("force"):
        raise ApiError(f"Compose некорректен, НЕ сохранён:\n{msg}", HTTPStatus.UNPROCESSABLE_ENTITY, code="docker.compose_invalid", detail=msg)
    if os.path.exists(path):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        shutil.copy2(path, os.path.join(BACKUP_DIR, re.sub(r"[^A-Za-z0-9._-]", "_", path.strip("/")) + time.strftime(".%Y%m%d-%H%M%S")))
    with open(path, "w") as f:
        f.write(content if content.endswith("\n") else content + "\n")
    result = {"ok": True, "path": path, "validation": msg}
    if body.get("up"):
        project = body.get("project") or os.path.basename(os.path.dirname(path))
        result["job"] = start_job(f"compose {project}: up -d", [DOCKER, "compose", "-p", project, "-f", path, "up", "-d"],
                                  "docker", cwd=os.path.dirname(path))
    return result


def ports_check(q):
    """Port host yang sudah dipakai proses lain (mis. MySQL Homebrew di 3306)."""
    ports = [p for p in (q.get("ports") or "").split(",") if p.isdigit()][:50]
    used = {}
    for p in ports:
        out = output(["lsof", "-nP", f"-iTCP:{p}", "-sTCP:LISTEN"], timeout=5)
        line = next((l for l in out.splitlines()[1:] if l.strip()), None)
        if line:
            used[p] = line.split()[0]
    return {"used": used}
