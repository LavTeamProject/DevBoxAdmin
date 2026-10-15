"""Клиенты API систем CI (Gitea/Forgejo, GitHub): всё, что панель делает на сервере CI от имени пользователя.

Пользователь один раз создаёт ТОКЕН ДОСТУПА (API token) на сервере CI; панель хранит его в файле 0600 (runners.py) и сама:
  • получает свежий регистрационный токен раннера (его не нужно копировать руками, он нигде не хранится);
  • находит и удаляет брошенные раннеры (`ci-…`) — без этого они остаются «офлайн» на сервере;
  • для самотеста создаёт репозиторий, кладёт workflow и читает результат запуска.
Токен доступа и регистрационные токены НЕ попадают в ответы API панели, аудит и вывод job: ошибки сервера CI пересказываются
без заголовков и тела запроса. Только стандартная библиотека; адрес берётся из реестра источников (runners.normalize_url).
Права токена: Gitea — `write:admin` (область instance) / `write:organization` (org) / `write:repository` (repo) + `write:repository`
для самотеста; GitHub — `repo` (+ `admin:org` для org).
"""
import base64
import json
import re
import urllib.error
import urllib.request
from http import HTTPStatus

from core import ApiError

TIMEOUT = 25
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
UA = "service-admin"


class CIError(Exception):
    """Ошибка обращения к серверу CI (без секретов в тексте)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редиректы запрещены: urllib пересылал бы заголовок Authorization на другой хост."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ARG002
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _field(d, key, kind=str):
    """Поле ответа сервера CI с проверкой формы: чужой/неожиданный ответ — CIError, а не KeyError."""
    v = d.get(key) if isinstance(d, dict) else None
    if not isinstance(v, kind):
        raise CIError(0, "the CI server returned an unexpected response")
    return v


def _request(method, url, token, scheme, body=None):
    headers = {"User-Agent": UA, "Accept": "application/json", "Authorization": f"{scheme} {token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:  # noqa: S310 - адрес из реестра источников
            raw = r.read(2_000_000)
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise CIError(e.code, "the server redirected the request; use the final address of the CI server (https://…) as the source address") from None
        raise CIError(e.code, {401: "the access token was rejected (wrong or expired)", 403: "the access token lacks the required scope",
                               404: "not found (check the address, path and token scope)"}.get(e.code, f"the server answered HTTP {e.code}")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CIError(0, f"cannot reach the CI server ({type(e).__name__})") from None
    except ValueError:
        raise CIError(0, "the CI server returned an unexpected response") from None


class Gitea:
    id = "gitea"

    def __init__(self, source, token):
        self.s, self.t = source, token
        self.base = source["url"] + "/api/v1"

    def _r(self, method, path, body=None):
        return _request(method, self.base + path, self.t, "token", body)

    def _runner_base(self):
        sc, p = self.s["scope"], self.s["path"]
        return {"instance": "/admin/actions/runners", "org": f"/orgs/{p}/actions/runners", "repo": f"/repos/{p}/actions/runners"}[sc]

    def registration_token(self):
        base = self._runner_base()
        try:
            return _field(self._r("GET", base + "/registration-token"), "token")
        except CIError as e:
            if e.status not in (404, 405):
                raise
        return _field(self._r("POST", base + "/registration-token"), "token")  # старые версии

    def list_runners(self):
        out = []
        for page in range(1, 21):  # постранично, до 1000 раннеров
            d = self._r("GET", f"{self._runner_base()}{self._page(page)}")
            items = d.get("runners") if isinstance(d, dict) else d
            if not isinstance(items, list):
                raise CIError(0, "the CI server returned an unexpected response")
            out += [{"id": x.get("id"), "name": x.get("name"), "status": x.get("status")} for x in items if isinstance(x, dict)]
            if len(items) < 50:
                break
        return out

    @staticmethod
    def _page(page):
        return f"?page={page}&limit=50"

    def delete_runner(self, runner_id):
        self._r("DELETE", f"{self._runner_base()}/{int(runner_id)}")

    def whoami(self):
        return _field(self._r("GET", "/user"), "login")

    def create_repo(self, name):
        """→ (full_name, default_branch)."""
        sc, p = self.s["scope"], self.s["path"]
        path = f"/orgs/{p}/repos" if sc == "org" else "/user/repos"
        d = self._r("POST", path, {"name": name, "private": True, "auto_init": True, "default_branch": "main"})
        return _field(d, "full_name"), (d.get("default_branch") if isinstance(d.get("default_branch"), str) else "main")

    def delete_repo(self, full):
        self._r("DELETE", f"/repos/{full}")

    def put_file(self, full, path, text, message, branch="main"):
        """→ sha коммита."""
        d = self._r("POST", f"/repos/{full}/contents/{path}", {"content": base64.b64encode(text.encode()).decode(), "message": message, "branch": branch})
        return _field(_field(d, "commit", dict), "sha")

    def run_for_commit(self, full, sha):
        """Запуск workflow именно для этого коммита (не «последний в репозитории»); None, если ещё нет."""
        d = self._r("GET", f"/repos/{full}/actions/runs?{self._runs_query()}")
        for r in (d.get("workflow_runs") or []) if isinstance(d, dict) else []:
            if isinstance(r, dict) and r.get("head_sha") == sha:
                return {"status": r.get("status"), "conclusion": r.get("conclusion")}
        return None

    @staticmethod
    def _runs_query():
        return "limit=30"


class GitHub(Gitea):
    id = "github"

    def __init__(self, source, token):
        self.s, self.t = source, token
        host = source["url"]
        self.base = "https://api.github.com" if host in ("https://github.com", "http://github.com") else host + "/api/v3"

    def _r(self, method, path, body=None):
        return _request(method, self.base + path, self.t, "Bearer", body)

    def _runner_base(self):
        sc, p = self.s["scope"], self.s["path"]
        return {"instance": "/enterprises", "org": f"/orgs/{p}/actions/runners", "repo": f"/repos/{p}/actions/runners"}[sc]

    def registration_token(self):
        if self.s["scope"] == "instance":
            raise CIError(400, "GitHub has no instance-wide runners here: use an organization or a repository")
        return _field(self._r("POST", self._runner_base() + "/registration-token"), "token")

    @staticmethod
    def _page(page):
        return f"?per_page=100&page={page}"

    def whoami(self):
        return _field(self._r("GET", "/user"), "login")

    def create_repo(self, name):
        sc, p = self.s["scope"], self.s["path"]
        path = f"/orgs/{p}/repos" if sc == "org" else "/user/repos"
        d = self._r("POST", path, {"name": name, "private": True, "auto_init": True})
        return _field(d, "full_name"), (d.get("default_branch") if isinstance(d.get("default_branch"), str) else "main")

    def put_file(self, full, path, text, message, branch="main"):
        d = self._r("PUT", f"/repos/{full}/contents/{path}", {"content": base64.b64encode(text.encode()).decode(), "message": message, "branch": branch})
        return _field(_field(d, "commit", dict), "sha")

    @staticmethod
    def _runs_query():
        return "per_page=30"


def client(source, token):
    return {"gitea": Gitea, "github": GitHub}[source["provider"]](source, token)


def friendly(e):
    """CIError → ApiError (с кодом для перевода)."""
    return ApiError(f"CI server: {e.message}", HTTPStatus.BAD_GATEWAY, code="runner.ci_error", detail=e.message)
