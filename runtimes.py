"""Deteksi & manajemen bahasa pemrograman selain PHP/Node:
Python, Go, Rust, Java, Ruby (+ info untuk bahasa lain yang terdeteksi).

Pilih versi default memakai shim di ~/.service-admin/bin (Python/Go/Ruby)
atau variabel env di ~/.service-admin/env.zsh (JAVA_HOME)."""
import glob
import json
import os
import plistlib
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

from core import has_clt as core_has_clt
from core import (BREW_PREFIX, ENV, HOME, PKG_RE, SHIM_DIR, ApiError, load_state, output, run, save_state,
                  set_env, set_shims, shell_probe, start_job)

# key, nama, perintah yang dicek, argumen versi
LANGS = [
    ("php", "PHP", "php", ["-r", "echo PHP_VERSION;"]),
    ("node", "Node.js", "node", ["-v"]),
    ("python", "Python", "python3", ["--version"]),
    ("go", "Go", "go", ["version"]),
    ("rust", "Rust", "rustc", ["--version"]),
    ("java", "Java", "java", ["-version"]),
    ("ruby", "Ruby", "ruby", ["-v"]),
    ("deno", "Deno", "deno", ["--version"]),
    ("bun", "Bun", "bun", ["--version"]),
    ("dotnet", ".NET", "dotnet", ["--version"]),
    ("dart", "Dart", "dart", ["--version"]),
    ("flutter", "Flutter", "flutter", ["--version"]),
    ("swift", "Swift", "swift", ["--version"]),
    ("kotlin", "Kotlin", "kotlin", ["-version"]),
    ("scala", "Scala", "scala", ["-version"]),
    ("elixir", "Elixir", "elixir", ["--version"]),
    ("erlang", "Erlang", "erl", ["-noshell", "-eval", 'io:format("~s",[erlang:system_info(otp_release)]),halt().']),
    ("zig", "Zig", "zig", ["version"]),
    ("haskell", "Haskell", "ghc", ["--numeric-version"]),
    ("ocaml", "OCaml", "ocaml", ["-version"]),
    ("julia", "Julia", "julia", ["--version"]),
    ("r", "R", "R", ["--version"]),
    ("crystal", "Crystal", "crystal", ["--version"]),
    ("nim", "Nim", "nim", ["--version"]),
    ("lua", "Lua", "lua", ["-v"]),
    ("perl", "Perl", "perl", ["-e", "print $^V"]),
]
MANAGED = {"python", "go", "rust", "java", "ruby"}
# formula/cask Homebrew untuk bahasa yang belum terinstall (Swift butuh Xcode, jadi tidak ada di sini)
INSTALL = {"php": ("php", "formula"), "node": ("node", "formula"), "python": ("python", "formula"), "go": ("go", "formula"),
           "rust": ("rustup", "formula"), "java": ("openjdk", "formula"), "ruby": ("ruby", "formula"),
           "deno": ("deno", "formula"), "bun": ("bun", "formula"), "dotnet": ("dotnet-sdk", "cask"),
           "dart": ("dart-sdk", "formula"), "kotlin": ("kotlin", "formula"), "scala": ("scala", "formula"),
           "elixir": ("elixir", "formula"), "erlang": ("erlang", "formula"), "zig": ("zig", "formula"),
           "haskell": ("ghc", "formula"), "ocaml": ("ocaml", "formula"), "julia": ("julia", "formula"),
           "r": ("r", "formula"), "crystal": ("crystal", "formula"), "nim": ("nim", "formula"),
           "lua": ("lua", "formula"), "perl": ("perl", "formula")}
BUILTIN = {"php", "node"}  # punya halaman sendiri di server.py
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+@/-]*$")
_cache = {"t": 0, "data": None}


def has_clt():
    """/usr/bin/python3, swift, dll. hanyalah stub yang memunculkan dialog install
    Xcode CLT kalau CLT belum ada — jangan dipanggil dalam kondisi itu."""
    return core_has_clt()


def version_of(path, args):
    out = output([path, *args], timeout=15)
    m = re.search(r"\d+\.\d+(\.\d+)*", out)
    return m[0] if m else None


def source_of(path):
    real = os.path.realpath(path or "")
    rules = [(SHIM_DIR, "Service Admin"), (f"{HOME}/Library/Application Support/Herd", "Herd"), (f"{BREW_PREFIX}/", "Homebrew"), (f"{HOME}/.cargo", "rustup"),
             ("/usr/local/go", "go.dev installer"), (f"{HOME}/.pyenv", "pyenv"), (f"{HOME}/.rbenv", "rbenv"),
             (f"{HOME}/.rvm", "rvm"), ("/Library/Frameworks/Python.framework", "python.org"),
             (f"{HOME}/.local/share/uv", "uv"), (f"{HOME}/sdk/go", "golang.org/dl"),
             ("/Library/Java/JavaVirtualMachines", "Зарегистрированный JDK"), ("/Applications/Xcode", "Xcode"),
             ("/Library/Developer/CommandLineTools", "Xcode CLT"), ("/usr/bin/", "macOS"),
             ("/System/", "macOS"), (f"{HOME}/.deno", "deno"), (f"{HOME}/.bun", "bun")]
    for prefix, label in rules:
        if path and path.startswith(prefix) or real.startswith(prefix):
            return label
    return "другое"


def brew_formula(path):
    m = re.search(r"/Cellar/([^/]+)/", os.path.realpath(path or ""))
    return m[1] if m else None


def detect(force=False):
    """Bahasa yang terinstall + versi yang dipakai terminal baru."""
    if not force and _cache["data"] and time.time() - _cache["t"] < 60:
        return _cache["data"]
    probe = shell_probe([cmd for _, _, cmd, _ in LANGS])
    clt = has_clt()
    found = []
    for key, name, cmd, args in LANGS:
        path = probe.get(cmd)
        if not path or not path.startswith("/"):
            continue
        if path.startswith("/usr/bin/") and not clt and key in ("python", "swift", "ruby"):
            continue
        found.append((key, name, path, args))
    with ThreadPoolExecutor(8) as pool:
        versions = list(pool.map(lambda f: version_of(f[2], f[3]), found))
    data = []
    for (key, name, path, _), ver in zip(found, versions):
        if key == "java" and not ver:
            continue  # /usr/bin/java tanpa JDK terpasang
        data.append({"key": key, "name": name, "path": path, "version": ver, "source": source_of(path),
                     "managed": key in MANAGED, "builtin": key in BUILTIN, "formula": brew_formula(path)})
    found_keys = {d["key"] for d in data}
    available = [{"key": k, "name": n, "formula": INSTALL[k][0], "type": INSTALL[k][1]}
                 for k, n, _, _ in LANGS if k not in found_keys and k in INSTALL]
    state = load_state()
    for d in data:  # versi default diatur lewat Service Admin?
        d["overridden"] = bool((state.get("shims") or {}).get(d["key"])) or bool((state.get("env") or {}).get(d["key"])) \
            or (d["key"] == "php" and bool(state.get("php")))
    _cache.update(t=time.time(), data={"langs": data, "available": available})
    return _cache["data"]


_tools = {}


def tools(*names):
    """Path absolut perintah seperti yang dilihat terminal (PATH server bisa
    lebih sempit, mis. saat jalan dari LaunchAgent). Cache 60 detik."""
    missing = [n for n in names if n not in _tools or time.time() - _tools[n][0] > 60]
    if missing:
        probe = shell_probe(missing)
        for n in missing:
            _tools[n] = (time.time(), probe.get(n) or None)
    return [_tools[n][1] for n in names]


def env_for(path):
    """ENV dengan folder `path` di depan PATH (agar cargo menemukan rustc, dst)."""
    return dict(ENV, PATH=os.path.dirname(path) + ":" + ENV["PATH"]) if path else ENV


def need(name):
    path = tools(name)[0]
    if not path:
        raise ApiError(f"`{name}` не найден", HTTPStatus.NOT_FOUND, code="lang.tool_not_found", name=name)
    return path


def active(cmd):
    """(path, versi) yang dipakai terminal baru untuk satu perintah."""
    probe = shell_probe([cmd])
    path = probe.get(cmd) or None
    return path, probe


def uniq(items, key="real"):
    seen, out = set(), []
    for it in items:
        if it[key] not in seen:
            seen.add(it[key])
            out.append(it)
    return out


def select_shims(lang, installs, choice, names_for):
    """Set default via shim; choice 'default' = hapus override."""
    if choice in (None, "", "default"):
        set_shims(lang, {})
        save_state(**{f"{lang}_default": None})
    else:
        target = next((i for i in installs if i["id"] == choice), None)
        if not target:
            raise ApiError("неизвестная версия", HTTPStatus.NOT_FOUND, code="lang.version_unknown")
        set_shims(lang, names_for(target))
        save_state(**{f"{lang}_default": choice})
    _cache["data"] = None
    return {"ok": True}


def link_bin(bindir, prefixes, aliases=None):
    """{nama: path} untuk semua executable di bindir yang diawali prefixes."""
    m = {}
    for f in sorted(os.listdir(bindir)) if os.path.isdir(bindir) else []:
        p = os.path.join(bindir, f)
        if f.startswith(prefixes) and os.access(p, os.X_OK) and not os.path.isdir(p):
            m[f] = p
    for alias, src in (aliases or {}).items():
        if src in m and alias not in m:
            m[alias] = m[src]
    return m


# ---------------------------------------------------------------- Python

def python_installs():
    items = []
    for d in sorted(glob.glob("/Library/Frameworks/Python.framework/Versions/[0-9]*")):
        items.append({"id": f"pyorg:{os.path.basename(d)}", "source": "python.org", "bin": f"{d}/bin/python3"})
    for d in sorted(glob.glob(f"{BREW_PREFIX}/opt/python@3*")):
        items.append({"id": f"brew:{os.path.basename(d)}", "source": "Homebrew", "bin": f"{d}/bin/python3"})
    for d in sorted(glob.glob(f"{HOME}/.pyenv/versions/*")):
        items.append({"id": f"pyenv:{os.path.basename(d)}", "source": "pyenv", "bin": f"{d}/bin/python3"})
    for d in sorted(glob.glob(f"{HOME}/.local/share/uv/python/*")):
        items.append({"id": f"uv:{os.path.basename(d)}", "source": "uv", "bin": f"{d}/bin/python3"})
    if os.path.exists("/usr/bin/python3") and has_clt():
        items.append({"id": "system", "source": "macOS / Xcode CLT", "bin": "/usr/bin/python3"})
    items = [i for i in items if os.path.exists(i["bin"])]
    for i in items:
        i["real"] = os.path.realpath(i["bin"])
    items = uniq(items)
    with ThreadPoolExecutor(6) as pool:
        for i, v in zip(items, pool.map(lambda i: version_of(i["bin"], ["--version"]), items)):
            i["version"] = v
    return items


def python_names(target):
    bindir = os.path.dirname(target["bin"])
    if target["id"] == "system":
        return {"python3": "/usr/bin/python3", "python": "/usr/bin/python3",
                "pip3": "/usr/bin/pip3", "pip": "/usr/bin/pip3"}
    return link_bin(bindir, ("python3", "pip3", "pydoc3", "idle3"), {"python": "python3", "pip": "pip3"})


def python_info(q):
    installs = python_installs()
    path, _ = active("python3")
    ver = version_of(path, ["--version"]) if path else None
    info = {"key": "python", "name": "Python", "installs": installs, "selectable": True,
            "selected": load_state().get("python_default") if os.path.islink(os.path.join(SHIM_DIR, "python3")) else None,
            "active": {"path": path, "version": ver, "source": source_of(path)}}
    # pipx (aplikasi CLI Python terisolasi)
    pipx_path, *extra = tools("pipx", "uv", "poetry", "pyenv", "conda")
    pipx = output([pipx_path, "list", "--json"], timeout=30, env=env_for(pipx_path)) if pipx_path else ""
    try:
        venvs = json.loads(pipx)["venvs"]
        info["pipx"] = [{"name": k, "version": v["metadata"]["main_package"]["package_version"],
                         "apps": v["metadata"]["main_package"].get("apps", [])} for k, v in venvs.items()]
    except (ValueError, KeyError, TypeError):
        info["pipx"] = None
    if path:
        code, out, _ = run([path, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"], timeout=60)
        try:
            info["packages"] = json.loads(out) if code == 0 else None
        except ValueError:
            info["packages"] = None
        stdlib = output([path, "-c", "import sysconfig;print(sysconfig.get_path('stdlib'))"])
        info["externally_managed"] = os.path.exists(os.path.join(stdlib, "EXTERNALLY-MANAGED"))
    # python.org: sertifikat SSL belum dipasang -> HTTPS dari Python gagal
    info["cert_fix"] = []
    for i in installs:
        if i["source"] == "python.org":
            ver = i["id"].split(":")[1]
            cafile = f"/Library/Frameworks/Python.framework/Versions/{ver}/etc/openssl/cert.pem"
            cmd = f"/Applications/Python {ver}/Install Certificates.command"
            if not os.path.exists(cafile) and os.path.exists(cmd):
                info["cert_fix"].append(ver)
    info["tools"] = [[n, version_of(p, ["--version"]), p]
                     for n, p in zip(("pipx", "uv", "poetry", "pyenv", "conda"), [pipx_path, *extra]) if p]
    return info


def python_action(body):
    action, name = body.get("action"), str(body.get("name", ""))
    if action == "select":
        return select_shims("python", python_installs(), body.get("id"), python_names)
    if action == "cert-fix":
        ver = str(body.get("version", ""))
        if not re.fullmatch(r"\d+\.\d+", ver):
            raise ApiError("недопустимая версия", code="lang.version_invalid")
        cmd = f"/Applications/Python {ver}/Install Certificates.command"
        return {"job": start_job(f"Установка SSL-сертификатов Python {ver}", ["/bin/sh", cmd], "python")}
    if action == "pipx-upgrade-all":
        pipx = need("pipx")
        return {"job": start_job("pipx upgrade-all", [pipx, "upgrade-all"], "python", env=env_for(pipx))}
    if action in ("pipx-install", "pipx-upgrade", "pipx-uninstall"):
        if not PKG_RE.match(name):
            raise ApiError("недопустимое имя пакета", code="lang.package_name_invalid")
        pipx, sub = need("pipx"), action.split("-")[1]
        return {"job": start_job(f"pipx {sub} {name}", [pipx, sub, name], "python", env=env_for(pipx))}
    raise ApiError("недопустимое действие", code="lang.action_invalid")


# ---------------------------------------------------------------- Go

def go_installs():
    items = [{"id": "godev", "source": "go.dev installer", "bin": "/usr/local/go/bin/go"},
             {"id": "brew", "source": "Homebrew", "bin": f"{BREW_PREFIX}/opt/go/bin/go"}]
    items += [{"id": f"sdk:{os.path.basename(d)}", "source": "golang.org/dl", "bin": f"{d}/bin/go"}
              for d in sorted(glob.glob(f"{HOME}/sdk/go*"))]
    items = [i for i in items if os.path.exists(i["bin"])]
    for i in items:
        i["real"] = os.path.realpath(i["bin"])
        i["version"] = version_of(i["bin"], ["version"])
    return uniq(items)


def dir_size(path):
    if not path or not os.path.isdir(path):
        return None
    out = output(["du", "-sk", path], timeout=30)
    m = re.match(r"(\d+)", out)
    return int(m[1]) * 1024 if m else None


_latest_go = {"t": 0, "v": None}


def latest_go():
    if time.time() - _latest_go["t"] > 3600:
        out = output(["curl", "-fsSL", "--max-time", "5", "https://go.dev/VERSION?m=text"], timeout=8)
        m = re.match(r"go(\d+\.\d+(\.\d+)?)", out)
        _latest_go.update(t=time.time(), v=m[1] if m else None)
    return _latest_go["v"]


def go_info(q):
    installs = go_installs()
    path, _ = active("go")
    info = {"key": "go", "name": "Go", "installs": installs, "selectable": len(installs) > 1,
            "selected": load_state().get("go_default") if os.path.islink(os.path.join(SHIM_DIR, "go")) else None,
            "active": {"path": path, "version": version_of(path, ["version"]) if path else None,
                       "source": source_of(path)}}
    if not path:
        return info
    try:
        env = json.loads(output([path, "env", "-json"]))
    except ValueError:
        env = {}
    info["env"] = {k: env.get(k) for k in ("GOROOT", "GOPATH", "GOBIN", "GOMODCACHE", "GOCACHE", "GOPROXY", "GOOS", "GOARCH")}
    bindir = env.get("GOBIN") or os.path.join(env.get("GOPATH") or f"{HOME}/go", "bin")
    info["bindir"] = bindir
    info["tools"] = sorted(os.listdir(bindir)) if os.path.isdir(bindir) else []
    with ThreadPoolExecutor(3) as pool:
        mod, build, latest = pool.submit(dir_size, env.get("GOMODCACHE")), pool.submit(dir_size, env.get("GOCACHE")), pool.submit(latest_go)
        info["caches"] = {"modcache": mod.result(), "buildcache": build.result()}
        info["latest"] = latest.result()
    return info


def go_action(body):
    action, name = body.get("action"), str(body.get("name", "")).strip()
    if action == "select":
        return select_shims("go", go_installs(), body.get("id"),
                            lambda t: link_bin(os.path.dirname(t["bin"]), ("go", "gofmt")))
    info_path = active("go")[0]
    if not info_path:
        raise ApiError("Go не найден", code="lang.go_not_found")
    if action == "install-tool":
        if not NAME_RE.match(name):
            raise ApiError("недопустимый путь модуля (пример: golang.org/x/tools/gopls@latest)", code="lang.module_path_invalid")
        pkg = name if "@" in name else name + "@latest"
        return {"job": start_job(f"go install {pkg}", [info_path, "install", pkg], "go", env=env_for(info_path))}
    if action == "remove-tool":
        bindir = go_info({}).get("bindir")
        target = os.path.join(bindir, name)
        if not NAME_RE.match(name) or "/" in name or not os.path.isfile(target):
            raise ApiError("инструмент не найден", HTTPStatus.NOT_FOUND, code="lang.tool_missing")
        os.remove(target)
        return {"ok": True}
    if action in ("clean-modcache", "clean-cache"):
        return {"job": start_job(f"go clean -{action[6:]}", [info_path, "clean", f"-{action[6:]}"], "go", env=env_for(info_path))}
    raise ApiError("недопустимое действие", code="lang.action_invalid")


# ---------------------------------------------------------------- Rust (rustup)

def rust_info(q):
    path, _ = active("rustc")
    info = {"key": "rust", "name": "Rust", "installs": [], "selectable": False,
            "active": {"path": path, "version": version_of(path, ["--version"]) if path else None,
                       "source": source_of(path)}}
    rustup, cargo = tools("rustup", "cargo")
    info["rustup"] = bool(rustup)
    if rustup:
        env = env_for(rustup)
        with ThreadPoolExecutor(5) as pool:
            f = {k: pool.submit(output, [rustup, *a], env=env) for k, a in {
                "toolchains": ["toolchain", "list"], "active": ["show", "active-toolchain"],
                "targets": ["target", "list", "--installed"], "components": ["component", "list", "--installed"],
                "version": ["--version"]}.items()}
            r = {k: v.result() for k, v in f.items()}
        info["toolchains"] = [{"name": line.split()[0], "default": "default" in line, "active": "active" in line}
                              for line in r["toolchains"].splitlines() if line.strip()]
        info["active_toolchain"] = r["active"].split()[0] if r["active"] else None
        info["targets"] = [t for t in r["targets"].splitlines() if t.strip()]
        info["components"] = [c for c in r["components"].splitlines() if c.strip()]
        info["rustup_version"] = version_of(rustup, ["--version"])
    if cargo:
        listing = output([cargo, "install", "--list"], env=env_for(cargo))
        info["crates"] = [{"name": m[1], "version": m[2]}
                          for m in re.finditer(r"^(\S+) v(\S+?):?$", listing, re.M)]
        info["registry_size"] = dir_size(f"{HOME}/.cargo/registry")
    return info


def rust_action(body):
    action, name = body.get("action"), str(body.get("name", "")).strip()
    rustup = need("rustup")
    env = env_for(rustup)
    if action == "update":
        return {"job": start_job("rustup update", [rustup, "update"], "rust", env=env)}
    if action == "check":
        return {"job": start_job("rustup check", [rustup, "check"], "rust", env=env)}
    if not NAME_RE.match(name):
        raise ApiError("недопустимое имя", code="lang.name_invalid")
    cmds = {
        "toolchain-install": [rustup, "toolchain", "install", name],
        "toolchain-uninstall": [rustup, "toolchain", "uninstall", name],
        "target-add": [rustup, "target", "add", name],
        "target-remove": [rustup, "target", "remove", name],
        "component-add": [rustup, "component", "add", name],
        "crate-install": [os.path.join(os.path.dirname(rustup), "cargo"), "install", name],
        "crate-uninstall": [os.path.join(os.path.dirname(rustup), "cargo"), "uninstall", name],
    }
    if action == "default":
        code, out, err = run([rustup, "default", name], timeout=60, env=env)
        if code != 0:
            raise ApiError((out + err).strip(), HTTPStatus.INTERNAL_SERVER_ERROR)
        _cache["data"] = None
        return {"ok": True, "output": (out + err).strip()}
    if action not in cmds:
        raise ApiError("недопустимое действие", code="lang.action_invalid")
    label = " ".join([os.path.basename(cmds[action][0]), *cmds[action][1:]])
    return {"job": start_job(label, cmds[action], "rust", env=env)}


# ---------------------------------------------------------------- Java

def jdk_version(home):
    try:
        with open(os.path.join(home, "release")) as f:
            m = re.search(r'JAVA_VERSION="([^"]+)"', f.read())
            return m[1] if m else None
    except OSError:
        return None


def java_installs():
    items = []
    try:
        out = subprocess.run(["/usr/libexec/java_home", "-X"], capture_output=True, timeout=10).stdout
        for j in plistlib.loads(out) if out else []:
            items.append({"id": j["JVMHomePath"], "home": j["JVMHomePath"], "version": j.get("JVMVersion"),
                          "source": j.get("JVMVendor") or "JDK", "registered": True})
    except Exception:  # noqa: BLE001
        pass
    for home in sorted(glob.glob(f"{BREW_PREFIX}/opt/openjdk*/libexec/openjdk.jdk/Contents/Home")):
        items.append({"id": home, "home": home, "version": jdk_version(home), "source": "Homebrew",
                      "registered": False})
    for i in items:
        i["real"] = os.path.realpath(i["home"])
        i["bin"] = os.path.join(i["home"], "bin/java")
    # kalau keg Homebrew sudah di-symlink ke /Library/Java, pakai entri yang terdaftar
    return uniq(items)


def java_info(q):
    installs = java_installs()
    probe = shell_probe(["java", "gradle", "mvn"])
    java_home = probe.get("ENV_JAVA_HOME") or None
    selected = (load_state().get("env", {}).get("java") or {}).get("JAVA_HOME")
    if java_home:
        ver = jdk_version(java_home)
    else:
        default_home = output(["/usr/libexec/java_home"], timeout=10)
        ver = jdk_version(default_home) if default_home.startswith("/") else None
        java_home = default_home if default_home.startswith("/") else None
    info = {"key": "java", "name": "Java", "installs": installs, "selectable": True,
            "selected": next((i["id"] for i in installs if i["home"] == selected), None),
            "active": {"path": java_home, "version": ver, "source": "JAVA_HOME" if probe.get("ENV_JAVA_HOME") else "macOS по умолчанию"},
            "build_tools": [[n, version_of(probe[n], ["--version"])] for n in ("gradle", "mvn") if probe.get(n)]}
    return info


def java_action(body):
    if body.get("action") != "select":
        raise ApiError("недопустимое действие", code="lang.action_invalid")
    choice = body.get("id")
    if choice in (None, "", "default"):
        set_env("java", {})
    else:
        target = next((i for i in java_installs() if i["id"] == choice), None)
        if not target:
            raise ApiError("неизвестный JDK", HTTPStatus.NOT_FOUND, code="lang.jdk_unknown")
        set_env("java", {"JAVA_HOME": target["home"]})
    _cache["data"] = None
    return {"ok": True}


# ---------------------------------------------------------------- Ruby

def ruby_installs():
    items = []
    if os.path.exists("/usr/bin/ruby"):
        items.append({"id": "system", "source": "macOS (встроенный)", "bin": "/usr/bin/ruby"})
    for d in sorted(glob.glob(f"{BREW_PREFIX}/opt/ruby*")):
        items.append({"id": f"brew:{os.path.basename(d)}", "source": "Homebrew", "bin": f"{d}/bin/ruby"})
    for base, src in ((f"{HOME}/.rbenv/versions", "rbenv"), (f"{HOME}/.rvm/rubies", "rvm")):
        for d in sorted(glob.glob(f"{base}/*")):
            items.append({"id": f"{src}:{os.path.basename(d)}", "source": src, "bin": f"{d}/bin/ruby"})
    items = [i for i in items if os.path.exists(i["bin"])]
    for i in items:
        i["real"] = os.path.realpath(i["bin"])
        i["version"] = version_of(i["bin"], ["-v"])
    return uniq(items)


def ruby_info(q):
    installs = ruby_installs()
    path, _ = active("ruby")
    info = {"key": "ruby", "name": "Ruby", "installs": installs, "selectable": len(installs) > 1,
            "selected": load_state().get("ruby_default") if os.path.islink(os.path.join(SHIM_DIR, "ruby")) else None,
            "active": {"path": path, "version": version_of(path, ["-v"]) if path else None, "source": source_of(path)}}
    if path:
        gem = os.path.join(os.path.dirname(os.path.realpath(path)), "gem")
        out = output([gem, "list", "--local"], timeout=30)
        info["gems"] = [{"name": m[1], "version": m[2]} for m in re.finditer(r"^(\S+) \((.+)\)$", out, re.M)]
        info["system_ruby"] = path == "/usr/bin/ruby"
    return info


def ruby_action(body):
    if body.get("action") != "select":
        raise ApiError("недопустимое действие", code="lang.action_invalid")
    return select_shims("ruby", ruby_installs(), body.get("id"),
                        lambda t: link_bin(os.path.dirname(t["bin"]), ("ruby", "gem", "irb", "bundle", "rake", "erb")))


# ---------------------------------------------------------------- generik & routing

def generic_info(key):
    lang = next((l for l in detect()["langs"] if l["key"] == key), None)
    if not lang:
        raise ApiError("язык не обнаружен", HTTPStatus.NOT_FOUND, code="lang.not_detected")
    return {"key": key, "name": lang["name"], "installs": [], "selectable": False,
            "active": {"path": lang["path"], "version": lang["version"], "source": lang["source"]},
            "formula": lang["formula"]}


INFO = {"python": python_info, "go": go_info, "rust": rust_info, "java": java_info, "ruby": ruby_info}
ACTIONS = {"python": python_action, "go": go_action, "rust": rust_action, "java": java_action, "ruby": ruby_action}


def lang_info(q):
    key = q.get("key", "")
    return INFO[key](q) if key in INFO else generic_info(key)


def lang_action(body):
    key = body.get("key", "")
    if key not in ACTIONS:
        raise ApiError("для этого языка пока нет действий", code="lang.no_actions")
    return ACTIONS[key](body)
