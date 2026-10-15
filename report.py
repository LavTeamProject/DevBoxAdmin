"""Отчёт о проблеме: текст для GitHub Issue. НИЧЕГО не отправляется автоматически — пользователь видит текст и сам нажимает «Submit new issue».
В отчёт попадают только версия, система и последние НЕУДАЧНЫЕ действия (имя действия, код, обрезанный результат); параметры, пути домашней папки,
токены и содержимое файлов не включаются."""
import os
import platform
import re

import audit
import setup
import version
from core import HOME

MAX_BODY = 6000  # URL нового issue ограничен; длиннее — пользователь копирует текст
_SECRETISH = re.compile(r"(?i)(token|secret|password|passwd|authorization|bearer)[=: ]+\S+")


def _clean(text):
    text = str(text or "").replace(HOME, "~")
    text = _SECRETISH.sub(lambda m: m.group(1) + "=***", text)
    return text[:160]


def build(q=None):
    rt = setup.runtime_info()
    failed = [e for e in audit.read({"result": "error", "limit": 8})["entries"]]
    lines = [f"**Panel:** {version.VERSION}", f"**macOS:** {platform.mac_ver()[0] or '?'} ({platform.machine()})",
             f"**Python:** {rt['version']} ({'bundled' if rt['bundled'] else 'system'})", "", "**What happened:**", "<!-- describe what you did and what you expected -->", "",
             "**Recent failed actions (no parameters included):**"]
    for e in failed:
        lines.append(f"- `{_clean(e.get('ts'))[:19]}` `{_clean(e.get('action'))}` by `{_clean(e.get('by'))}` — {_clean(e.get('result'))} (code {e.get('code')})")
    if not failed:
        lines.append("- none")
    body = "\n".join(lines)[:MAX_BODY]
    return {"repo": version.REPO_URL, "version": version.VERSION, "title": "Bug: ", "body": body,
            "home_hidden": os.path.basename(HOME) not in body}
