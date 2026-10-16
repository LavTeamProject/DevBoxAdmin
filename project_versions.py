"""Версии инструментов, которые просит проект (Фаза 10): читаем файлы проекта (только чтение) и сравниваем с активными версиями на машине.

Источники: .nvmrc, .node-version, package.json (engines.node, volta.node), .python-version, pyproject.toml (requires-python), .ruby-version,
.php-version, composer.json (require.php), go.mod, .java-version, .sdkmanrc, .tool-versions (asdf/mise). Менеджера версий не нужно: если подходящая версия есть
в Homebrew как версионная формула (node@20, python@3.12…), панель предлагает её поставить. Файлы читаются только внутри папки проекта (без выхода по ссылкам), до 64 КБ."""
import json
import os
import re

MAX_FILE = 64 * 1024
VER_RE = re.compile(r"\d+(?:\.\d+)*")
NAMES = {"node": "Node.js", "python": "Python", "ruby": "Ruby", "php": "PHP", "go": "Go", "java": "Java"}
TOOL_KEYS = {"nodejs": "node", "node": "node", "python": "python", "ruby": "ruby", "php": "php", "golang": "go", "go": "go", "java": "java"}
UNKNOWN_WORDS = ("lts", "latest", "stable", "current", "system", "node", "*")
FIX_PAGE = {"node": "#node", "python": "#lang-python", "ruby": "#lang-ruby", "php": "#php", "go": "#lang-go", "java": "#lang-java"}


def _read(root, name):
    path = os.path.join(root, name)
    try:
        real = os.path.realpath(path)
        if not (real == os.path.join(os.path.realpath(root), name) or real.startswith(os.path.realpath(root) + os.sep)) or not os.path.isfile(real):
            return None
        with open(real, encoding="utf-8", errors="replace") as f:
            return f.read(MAX_FILE)
    except OSError:
        return None


def _tuple(s):
    m = VER_RE.search(s or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def requirements(root):
    """Папка проекта → [{lang, wanted, source}] (желаемые версии из файлов проекта)."""
    out = []

    def add(lang, wanted, source):
        wanted = (wanted or "").strip().strip("\"'")
        if wanted:
            out.append({"lang": lang, "wanted": wanted, "source": source})
    for fn, lang in ((".nvmrc", "node"), (".node-version", "node"), (".python-version", "python"), (".ruby-version", "ruby"), (".php-version", "php"), (".java-version", "java")):
        txt = _read(root, fn)
        if txt and txt.strip():
            add(lang, txt.strip().splitlines()[0], fn)
    txt = _read(root, ".tool-versions")
    for line in (txt or "").splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 2 and parts[0] in TOOL_KEYS:
            add(TOOL_KEYS[parts[0]], parts[1], ".tool-versions")
    txt = _read(root, "package.json")
    if txt:
        try:
            pj = json.loads(txt)
            add("node", ((pj.get("volta") or {}).get("node")) or ((pj.get("engines") or {}).get("node")), "package.json")
        except (ValueError, AttributeError):
            pass
    txt = _read(root, "composer.json")
    if txt:
        try:
            cj = json.loads(txt)
            add("php", (cj.get("require") or {}).get("php"), "composer.json")
        except (ValueError, AttributeError):
            pass
    txt = _read(root, "pyproject.toml")
    m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', txt or "")
    if m:
        add("python", m.group(1), "pyproject.toml")
    m = re.search(r"^go\s+(\d[\d.]*)", _read(root, "go.mod") or "", re.M)
    if m:
        add("go", m.group(1), "go.mod")
    m = re.search(r"^java\s*=\s*([\w.\-]+)", _read(root, ".sdkmanrc") or "", re.M)
    if m:
        add("java", m.group(1), ".sdkmanrc")
    seen, uniq = set(), []
    for r in out:                                   # один и тот же язык из нескольких файлов — показываем все, но без повторов
        k = (r["lang"], r["wanted"], r["source"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return uniq


def _cmp(a, b):
    n = max(len(a), len(b))
    a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def satisfies(active, spec):
    """active — версия «26.3.1», spec — «20», «>=18», «^8.2», «~3.11», «18.x», «20 || 22», «>=3.9,<3.13». → True / False / None (не разобрать)."""
    act = _tuple(active)
    spec = (spec or "").strip().lstrip("v")
    if act is None or not spec or any(w == spec.lower() or spec.lower().startswith(w + "/") for w in UNKNOWN_WORDS):
        return None
    results = []
    for alt in spec.split("||"):
        ok = True
        found = False
        for comp in re.split(r"[,\s]+", alt.strip()):
            m = re.match(r"^(>=|<=|>|<|\^|~|=)?\s*v?(\d+(?:\.(?:\d+|x|\*))*)(?:\.x|\.\*)?$", comp)
            if not m:
                if comp:
                    ok = None
                continue
            found = True
            op, ver = m.group(1) or "=", tuple(int(x) for x in re.findall(r"\d+", m.group(2)))
            if op == "=":
                good = act[:len(ver)] == ver
            elif op == ">=":
                good = _cmp(act, ver) >= 0
            elif op == ">":
                good = _cmp(act, ver) > 0
            elif op == "<=":
                good = _cmp(act[:len(ver)], ver) <= 0
            elif op == "<":
                good = _cmp(act[:len(ver)], ver) < 0
            elif op == "^":
                upper = (ver[0] + 1,) if ver[0] > 0 else ((0, ver[1] + 1) if len(ver) > 1 else (0, 1))
                good = _cmp(act, ver) >= 0 and _cmp(act, upper) < 0
            else:   # ~
                upper = (ver[0], (ver[1] if len(ver) > 1 else 0) + 1)
                good = _cmp(act, ver) >= 0 and _cmp(act, upper) < 0
            ok = ok and good if ok is not None else None
        results.append(ok if found else None)
    if any(r is True for r in results):
        return True
    return None if any(r is None for r in results) else False


def formula_for(lang, wanted):
    """Версионная формула Homebrew под просимую версию: node@20, python@3.12, go@1.22, php@8.3, ruby@3.3, openjdk@21 (или None)."""
    t = _tuple(re.sub(r"^[^\d]*", "", wanted))
    if not t:
        return None
    return {"node": f"node@{t[0]}", "java": f"openjdk@{t[0]}"}.get(lang) or (f"{ {'python': 'python', 'go': 'go', 'ruby': 'ruby', 'php': 'php'}[lang] }@{t[0]}.{t[1]}" if lang in ("python", "go", "ruby", "php") and len(t) > 1 else None)


def project_versions(q):
    """GET /api/projects/versions?path=… → что просит проект, что активно сейчас, подходит ли и какую формулу поставить."""
    import projects
    import runtimes
    path = projects.resolve(q.get("path"))
    active = {l["key"]: l["version"] for l in runtimes.detect()["langs"]}
    names, have = (runtimes._brew_formulae(), runtimes._brew_installed_names()) if os.path.exists(runtimes.BREW) else ([], set())  # noqa: SLF001
    items = []
    for r in requirements(path):
        lang = r["lang"]
        ok = satisfies(active.get(lang), r["wanted"])
        formula = formula_for(lang, r["wanted"]) if ok is not True else None
        items.append({**r, "name": NAMES[lang], "active": active.get(lang), "ok": ok, "page": FIX_PAGE[lang],
                      "formula": formula if formula in names else None, "formula_installed": bool(formula and formula in have)})
    return {"path": path, "items": items}
