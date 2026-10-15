"""Команды от имени администратора на Linux (Фаза 6, Л3). Панель никогда не принимает и не хранит пароль:
  • есть графическая сессия и pkexec → задача `pkexec …` (системное окно polkit спрашивает пароль);
  • иначе → {"terminal": "sudo …"}: интерфейс открывает команду в терминале панели, пароль вводит человек в нём.
Только команды, собранные сервером из проверенных значений (имена пакетов/служб проходят регулярные выражения до вызова)."""
import os
import shlex

import platform_info
from core import start_steps

SYSTEM_BIN = ("/usr/bin", "/usr/sbin", "/bin", "/sbin")
PKEXEC = "/usr/bin/pkexec"


def _abs(cmd):
    """Полный путь программы из системных каталогов: polkit показывает человеку именно его (а не обобщённый `env`), PATH пользователя не используется."""
    if os.path.isabs(cmd):
        return cmd
    for d in SYSTEM_BIN:
        p = os.path.join(d, cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return cmd


def admin_argv(argv):
    return [_abs(argv[0]), *argv[1:]]


def run_admin(label, argv, kind="pkg", title=None):
    """→ {"job": id} или {"terminal": "sudo …"}. argv собирает сервер из проверенных значений."""
    argv = admin_argv(argv)
    if platform_info.has("elevation.gui") and os.path.isfile(PKEXEC):   # pkexec — только из системного каталога (не через PATH пользователя: подмена = кража пароля)
        return {"job": start_steps(label, [(title or label, [PKEXEC, *argv], {})], kind)}
    # Без экрана: команда ПОКАЗЫВАЕТСЯ человеку и выполняется в ЕГО терминале. В терминал панели её не печатаем: PTY панели доступен тому же пользователю (агенту),
    # а билет sudo привязан к терминалу. `-k` — не оставлять билет.
    return {"terminal": "/usr/bin/sudo -k -- " + " ".join(shlex.quote(a) for a in argv)}
