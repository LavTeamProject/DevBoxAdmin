"""Запись в Git (Фаза 2.6): fetch/pull/push, ветки, stash, stage/commit, worktree, откат изменений.

`projects.py` остаётся ТОЛЬКО ЧТЕНИЕМ git; всё, что пишет в репозиторий, живёт здесь. Принципы:
  * проект — только из реестра сервера (`projects.resolve`); ветки, remote, stash и файлы проверяются по
    РЕАЛЬНОМУ состоянию репозитория, а не принимаются на веру из браузера;
  * команды — список аргументов без shell; пути всегда после `--`; имена веток не могут начинаться с `-`;
  * `push` никогда не `--force`; `pull` только `--ff-only`; ветку удаляет `-d` (только слитую), `-D` — с вводом имени;
  * разрушающие операции (откат изменений, удаление неотслеживаемых, `branch -D`) серверно требуют ввести
    имя проекта (`confirm`) — это обязательное «двойное» подтверждение, обойти его из UI/агента нельзя;
  * `worktree add` — только внутрь корня панели (`~/Worktrees/<repo>/<ветка>`);
  * исполнение — `core.start_steps` (job + лог + аудит); `build()` — чистая функция, ничего не запускает.
"""
import hashlib
import os
import re
import subprocess
import time
from http import HTTPStatus

import projects
from core import ENV, HOME, ApiError, has_clt, start_steps

WORKTREE_ROOT = os.path.join(HOME, "Worktrees")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,50}$")
MSG_MAX = 2000
STASH_MSG_MAX = 200
MAX_FILES = 200
# Никаких интерактивных запросов: без TTY git/ssh повисли бы навсегда на вводе пароля.
WRITE_ENV = dict(ENV, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", GIT_EDITOR="true", GIT_ASKPASS="/usr/bin/false",
                 SSH_ASKPASS="/usr/bin/false")


# ---------------------------------------------------------------- чтение состояния (для валидации)

def _git(path, *args, timeout=20):
    code, out = projects.git(path, *args, timeout=timeout)
    return code, out


def _lines(path, *args):
    code, out = _git(path, *args)
    return [ln for ln in out.splitlines() if ln.strip()] if code == 0 else []


def files_state(path):
    """Точный разбор `git status --porcelain=v1 -z`: [{xy, path}] (пути с пробелами и юникодом — верно)."""
    code, out = _git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", timeout=30)
    if code != 0:
        raise ApiError("Не удалось прочитать состояние репозитория", HTTPStatus.CONFLICT, code="git.state_read")
    parts, files, i = out.split("\0"), [], 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, p = e[:2], e[3:]
        if "R" in xy or "C" in xy:
            i += 1  # исходное имя при переименовании
        files.append({"xy": xy, "path": p})
    return files


def _branches(path):
    return _lines(path, "branch", "--format=%(refname:short)")


def _remote_branches(path):
    return _lines(path, "branch", "-r", "--format=%(refname:short)")


def _remotes(path):
    return _lines(path, "remote")


def _current(path):
    code, out = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    name = out.strip() if code == 0 else ""
    return None if name in ("", "HEAD") else name


def _upstream(path):
    code, out = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return out.strip() if code == 0 else None


def _check_branch_name(name):
    if not isinstance(name, str) or not BRANCH_RE.match(name) or ".." in name or name.endswith((".lock", "/", ".")):
        raise ApiError("Недопустимое имя ветки", code="git.bad_branch")
    code, _ = projects.git(HOME, "check-ref-format", "--branch", name)
    if code != 0:
        raise ApiError("Недопустимое имя ветки", code="git.bad_branch")
    return name


def _need_files(raw):
    if not isinstance(raw, list) or not raw or len(raw) > MAX_FILES or not all(isinstance(x, str) and x for x in raw):
        raise ApiError(f"Укажите от 1 до {MAX_FILES} файлов", code="git.files_range", max=MAX_FILES)
    return raw


def _typed_confirm(body, path, what):
    """Серверное «двойное подтверждение»: надо прислать имя проекта. UI просит ввести его вручную."""
    if body.get("confirm") != os.path.basename(path):
        raise ApiError(f"{what}: для подтверждения введите имя проекта «{os.path.basename(path)}»",
                       HTTPStatus.PRECONDITION_REQUIRED, code="git.confirm_name", what=what, name=os.path.basename(path))


def _step(title, path, *args):
    return (title, [projects.GIT, *args], {"cwd": path, "env": WRITE_ENV})


def _slug(branch):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "branch"


# ---------------------------------------------------------------- сборка операций (ничего не запускает)

def build(op, p, editors=None):
    """→ (подпись, kind, [шаги start_steps]). Проект и все идентификаторы проверяются по реальному состоянию."""
    if not has_clt():
        raise ApiError("Сначала нужны Command Line Tools — откройте «Подготовка системы»", HTTPStatus.CONFLICT, code="git.need_clt")
    path = projects.resolve(p.get("project"))
    name = os.path.basename(path)
    kind = "git:" + hashlib.sha1(path.encode()).hexdigest()[:10]  # одна операция за раз на репозиторий

    def label(s):
        return f"{name}: {s}"

    if op == "git.fetch":
        remote = p.get("remote")
        if remote:
            if remote not in _remotes(path):
                raise ApiError("Неизвестный remote", code="git.unknown_remote")
            return label(f"fetch {remote}"), kind, [_step(f"git fetch --prune {remote}", path, "fetch", "--prune", remote)]
        if not _remotes(path):
            raise ApiError("У репозитория нет remote", HTTPStatus.CONFLICT, code="git.no_remote")
        return label("fetch"), kind, [_step("git fetch --all --prune", path, "fetch", "--all", "--prune")]

    if op == "git.pull":
        if not _current(path):
            raise ApiError("Detached HEAD: pull невозможен", HTTPStatus.CONFLICT, code="git.detached_pull")
        if not _upstream(path):
            raise ApiError("У текущей ветки нет upstream", HTTPStatus.CONFLICT, code="git.no_upstream")
        return label("pull"), kind, [_step("git pull --ff-only", path, "pull", "--ff-only")]

    if op == "git.push":
        branch = _current(path)
        if not branch:
            raise ApiError("Detached HEAD: push невозможен", HTTPStatus.CONFLICT, code="git.detached_push")
        if _upstream(path):
            return label(f"push {branch}"), kind, [_step("git push", path, "push")]
        remote = p.get("remote") or ("origin" if "origin" in _remotes(path) else None)
        if not remote or remote not in _remotes(path):
            raise ApiError("Не указан remote для первого push", HTTPStatus.CONFLICT, code="git.push_need_remote")
        return label(f"push -u {remote} {branch}"), kind, [_step(f"git push -u {remote} {branch}", path, "push", "-u", remote, branch)]

    if op == "git.switch":
        branch = p.get("branch")
        known = set(_branches(path)) | {b.split("/", 1)[1] for b in _remote_branches(path) if "/" in b and not b.endswith("/HEAD")}
        if branch not in known:
            raise ApiError("Ветка не найдена", HTTPStatus.NOT_FOUND, code="git.branch_missing")
        return label(f"switch {branch}"), kind, [_step(f"git switch {branch}", path, "switch", branch)]

    if op == "git.branch_create":
        branch = _check_branch_name(p.get("name"))
        if branch in _branches(path):
            raise ApiError("Такая ветка уже есть", HTTPStatus.CONFLICT, code="git.branch_exists")
        start = p.get("start")
        args = ["switch", "-c", branch]
        if start:
            if start not in _branches(path) + _remote_branches(path):
                raise ApiError("Начальная ветка не найдена", HTTPStatus.NOT_FOUND, code="git.start_missing")
            args.append(start)
        return label(f"новая ветка {branch}"), kind, [_step("git " + " ".join(args), path, *args)]

    if op == "git.branch_delete":
        branch = p.get("branch")
        if branch not in _branches(path):
            raise ApiError("Ветка не найдена", HTTPStatus.NOT_FOUND, code="git.branch_missing")
        if branch == _current(path):
            raise ApiError("Нельзя удалить текущую ветку", HTTPStatus.CONFLICT, code="git.delete_current")
        if p.get("force"):
            _typed_confirm(p, path, "Принудительное удаление ветки")
        flag = "-D" if p.get("force") else "-d"
        return label(f"удалить ветку {branch}"), kind, [_step(f"git branch {flag} {branch}", path, "branch", flag, branch)]

    if op == "git.stash_push":
        if not files_state(path):
            raise ApiError("Нечего прятать: рабочая копия чистая", HTTPStatus.CONFLICT, code="git.stash_clean")
        msg = (p.get("message") or "").strip()
        if len(msg) > STASH_MSG_MAX or any(ord(c) < 32 for c in msg):
            raise ApiError("Слишком длинное или некорректное сообщение stash", code="git.stash_msg")
        args = ["stash", "push", "--include-untracked"] + (["-m", msg] if msg else [])
        return label("stash"), kind, [_step("git stash push --include-untracked", path, *args)]

    if op == "git.stash_pop":
        idx = p.get("index", 0)
        n = len(_lines(path, "stash", "list"))
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < n:
            raise ApiError("Такого stash нет", HTTPStatus.NOT_FOUND, code="git.stash_missing")
        return label(f"stash pop {idx}"), kind, [_step(f"git stash pop stash@{{{idx}}}", path, "stash", "pop", f"stash@{{{idx}}}")]

    if op in ("git.add", "git.unstage"):
        files = _need_files(p.get("files"))
        state = {f["path"]: f["xy"] for f in files_state(path)}
        for f in files:
            xy = state.get(f)
            if xy is None:
                raise ApiError(f"Файл без изменений или не найден: {f}", HTTPStatus.NOT_FOUND, code="git.file_unchanged", f=f)
            if op == "git.add" and xy[1] == " ":
                raise ApiError(f"Нечего добавлять в индекс: {f}", HTTPStatus.CONFLICT, code="git.nothing_to_stage", f=f)
            if op == "git.unstage" and (xy[0] in (" ", "?")):
                raise ApiError(f"Файл не в индексе: {f}", HTTPStatus.CONFLICT, code="git.not_staged", f=f)
        args = ["add", "--", *files] if op == "git.add" else ["restore", "--staged", "--", *files]
        return label(f"{'в индекс' if op == 'git.add' else 'убрать из индекса'}: {len(files)}"), kind, [
            _step("git " + " ".join(args[:2]), path, *args)]

    if op == "git.commit":
        msg = (p.get("message") or "").strip()
        if not msg or len(msg) > MSG_MAX or "\0" in msg:
            raise ApiError(f"Сообщение коммита: от 1 до {MSG_MAX} символов", code="git.commit_msg", max=MSG_MAX)
        staged = [f for f in files_state(path) if f["xy"][0] not in (" ", "?")]
        if not staged:
            raise ApiError("Индекс пуст: сначала добавьте файлы", HTTPStatus.CONFLICT, code="git.index_empty")
        return label(f"commit ({len(staged)} файл.)"), kind, [_step("git commit", path, "commit", "-m", msg)]

    if op == "git.discard":
        files = _need_files(p.get("files"))
        state = {f["path"]: f["xy"] for f in files_state(path)}
        for f in files:
            xy = state.get(f)
            if xy is None or xy[1] in (" ", "?"):
                raise ApiError(f"Нет неиндексированных изменений в файле: {f}", HTTPStatus.CONFLICT, code="git.no_unstaged", f=f)
        _typed_confirm(p, path, "Откат изменений")
        return label(f"откат изменений: {len(files)}"), kind, [_step("git restore --worktree", path, "restore", "--worktree", "--", *files)]

    if op == "git.clean":
        files = _need_files(p.get("files"))
        state = {f["path"]: f["xy"] for f in files_state(path)}
        for f in files:
            if state.get(f) != "??":
                raise ApiError(f"Файл не является неотслеживаемым: {f}", HTTPStatus.CONFLICT, code="git.not_untracked", f=f)
        _typed_confirm(p, path, "Удаление неотслеживаемых файлов")
        return label(f"удалить неотслеживаемые: {len(files)}"), kind, [_step("git clean -f", path, "clean", "-f", "--", *files)]

    if op == "git.worktree_add":
        branch = _check_branch_name(p.get("branch"))
        if branch in _branches(path):
            raise ApiError("Такая ветка уже есть", HTTPStatus.CONFLICT, code="git.branch_exists")
        base = p.get("base")
        if base and base not in _branches(path) + _remote_branches(path):
            raise ApiError("Базовая ветка не найдена", HTTPStatus.NOT_FOUND, code="git.base_missing")
        target = os.path.join(WORKTREE_ROOT, _slug(name), _slug(branch))
        if os.path.lexists(target):
            raise ApiError("Папка worktree уже существует", HTTPStatus.CONFLICT, code="git.wt_exists")
        real_root = os.path.realpath(WORKTREE_ROOT)
        if os.path.commonpath([os.path.realpath(os.path.dirname(target)), real_root]) != real_root:
            raise ApiError("Путь вне корня worktree", code="git.wt_outside")

        def mkdir(log):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            log(f"Корень worktree: {WORKTREE_ROOT}")

        def register(log):
            real = os.path.realpath(target)
            projects._cache["projects"][real] = {"path": real, "worktree": True}  # noqa: SLF001
            log(f"Worktree: {real}")

        add = [projects.GIT, "worktree", "add", "-b", branch, target] + ([base] if base else [])
        return label(f"worktree {branch}"), kind, [("Папка worktree", mkdir, {}),
                                                   (f"git worktree add -b {branch}", add, {"cwd": path, "env": WRITE_ENV}),
                                                   ("Регистрация", register, {})]

    if op == "git.worktree_remove":
        target = os.path.realpath(str(p.get("worktree") or ""))
        trees = {os.path.realpath(t["path"]): t for t in projects._worktrees(path)}  # noqa: SLF001
        real_root = os.path.realpath(WORKTREE_ROOT)
        if target not in trees or target == os.path.realpath(path):
            raise ApiError("Это не дополнительный worktree проекта", HTTPStatus.NOT_FOUND, code="git.wt_not_extra")
        if os.path.commonpath([target, real_root]) != real_root:
            raise ApiError("Удалять можно только worktree внутри корня панели (~/Worktrees)", code="git.wt_delete_scope")

        def unregister(log):
            projects._cache["projects"].pop(target, None)  # noqa: SLF001
        return label(f"удалить worktree {os.path.basename(target)}"), kind, [
            _step("git worktree remove (без --force)", path, "worktree", "remove", target), ("Реестр", unregister, {})]

    if op == "editor.open":
        editors = editors or {}
        ed = p.get("editor") or projects.presets_get(path).get("editor")
        if ed not in editors or not os.path.exists(f"/Applications/{editors[ed][1]}.app"):
            raise ApiError("Редактор не выбран или не установлен", HTTPStatus.CONFLICT, code="git.no_editor")
        return label(f"открыть в {editors[ed][0]}"), kind, [("open -a", ["/usr/bin/open", "-a", editors[ed][1], path], {})]

    raise ApiError("Неизвестная операция", code="git.unknown_op")


def run_op(body, editors=None):
    """POST /api/git/op {op, params} → {"job": id}."""
    op, params = body.get("op"), body.get("params") or {}
    if not isinstance(op, str) or not isinstance(params, dict):
        raise ApiError("Неверный запрос", code="git.bad_request")
    label, kind, steps = build(op, params, editors)
    return {"job": start_steps(label, steps, kind), "label": label}


# ---------------------------------------------------------------- проверка результата (после исполнения)

RECENT = 600  # секунд: «только что» для fetch / commit


def _check(name, ok, detail=""):
    return {"check": name, "ok": bool(ok), **({"detail": detail} if detail else {})}


def verify(op, p):
    """Проверить РЕЗУЛЬТАТ git-операции по состоянию репозитория (после исполнения). → {"ok": bool, "checks": [...]}.
    Ничего не меняет; параметры те же, что у операции. До исполнения большинство проверок честно возвращают ok=false."""
    path = projects.resolve(p.get("project"))
    checks = []
    if op == "git.fetch":
        fh = os.path.join(path, ".git", "FETCH_HEAD")
        fresh = os.path.isfile(fh) and time.time() - os.path.getmtime(fh) < RECENT
        checks.append(_check("fetch was run in the last 10 minutes", fresh))
    elif op == "git.pull":
        up = _upstream(path)
        code, _ = _git(path, "merge-base", "--is-ancestor", "@{u}", "HEAD") if up else (1, "")
        checks.append(_check("the branch contains its upstream", up and code == 0, up or "no upstream"))
        checks.append(_check("no unmerged files", not any(f["xy"] in ("UU", "AA", "DD", "AU", "UA", "DU", "UD") for f in files_state(path))))
    elif op == "git.push":
        up = _upstream(path)
        code, out = _git(path, "rev-list", "--count", "@{u}..HEAD") if up else (1, "")
        checks.append(_check("an upstream is set", up, up or ""))
        checks.append(_check("nothing left to push", up and code == 0 and out.strip() == "0", f"ahead by {out.strip()}" if up and code == 0 else ""))
    elif op == "git.switch":
        checks.append(_check("the branch is checked out", _current(path) == p.get("branch"), f"current: {_current(path)}"))
    elif op == "git.branch_create":
        checks.append(_check("the branch exists", p.get("name") in _branches(path)))
        checks.append(_check("the branch is checked out", _current(path) == p.get("name"), f"current: {_current(path)}"))
    elif op == "git.branch_delete":
        checks.append(_check("the branch is gone", p.get("branch") not in _branches(path)))
    elif op == "git.stash_push":
        checks.append(_check("the working tree is clean", not files_state(path)))
        checks.append(_check("a stash entry exists", len(_lines(path, "stash", "list")) > 0))
    elif op == "git.stash_pop":
        checks.append(_check("the changes are back in the working tree", bool(files_state(path))))
    elif op in ("git.add", "git.unstage"):
        state = {f["path"]: f["xy"] for f in files_state(path)}
        for f in _need_files(p.get("files")):
            xy = state.get(f)
            staged = bool(xy) and xy[0] not in (" ", "?")
            checks.append(_check(f"{f}: " + ("staged" if op == "git.add" else "not staged"), staged if op == "git.add" else not staged))
    elif op == "git.commit":
        code, out = _git(path, "log", "-1", "--format=%s%n%ct")
        subj, _, ts = out.strip().partition("\n")
        want = (p.get("message") or "").strip().splitlines()[0] if (p.get("message") or "").strip() else ""
        checks.append(_check("the last commit has this message", code == 0 and subj == want, subj[:80]))
        checks.append(_check("the commit is recent", code == 0 and ts.isdigit() and time.time() - int(ts) < RECENT))
    elif op == "git.discard":
        state = {f["path"]: f["xy"] for f in files_state(path)}
        for f in _need_files(p.get("files")):
            xy = state.get(f)
            checks.append(_check(f"{f}: no unstaged changes", xy is None or xy[1] == " "))
    elif op == "git.clean":
        for f in _need_files(p.get("files")):
            checks.append(_check(f"{f}: removed", not os.path.lexists(os.path.join(path, f))))
    elif op == "git.worktree_add":
        branch = p.get("branch") or ""
        target = os.path.join(WORKTREE_ROOT, _slug(os.path.basename(path)), _slug(branch))
        trees = {os.path.realpath(t["path"]) for t in projects._worktrees(path)}  # noqa: SLF001
        checks.append(_check("the branch exists", branch in _branches(path)))
        checks.append(_check("the worktree folder exists and is registered", os.path.isdir(target) and os.path.realpath(target) in trees))
    elif op == "git.worktree_remove":
        target = os.path.realpath(str(p.get("worktree") or ""))
        trees = {os.path.realpath(t["path"]) for t in projects._worktrees(path)}  # noqa: SLF001
        checks.append(_check("the worktree is no longer registered", target not in trees))
        checks.append(_check("the folder is gone", not os.path.lexists(target)))
    else:
        raise ApiError("This operation has no automatic verification", HTTPStatus.CONFLICT, code="ops.no_verify")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
