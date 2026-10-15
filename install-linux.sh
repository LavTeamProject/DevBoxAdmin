#!/bin/bash
# Установка Service Admin на Linux (Фаза 6, Л1): свой Python 3.12, systemd-служба пользователя, ярлык рабочего стола. Права root не нужны.
#   ./install-linux.sh            установить и запустить
# Служба работает и без входа в систему, если разрешён linger (loginctl enable-linger).
set -euo pipefail
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
say() { printf '\033[34m==>\033[0m %s\n' "$1"; }

[[ "$(uname -s)" == Linux ]] || { msg "Этот скрипт только для Linux (на macOS: ./install.sh)" "This script is for Linux only (on macOS: ./install.sh)"; exit 1; }
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ "$DIR$HOME" != *$'\n'* ]] || { msg "Путь установки не должен содержать перевод строки" "The install path must not contain a newline"; exit 1; }
UNIT_DIR="$HOME/.config/systemd/user"
USER_NAME="$(id -un)"
# значения для unit-файла: в кавычках аргументы ExecStart, '%' удваивается (спецификаторы systemd)
sd_esc() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; s=${s//%/%%}; printf '"%s"' "$s"; }
sd_pct() { printf '%s' "${1//%/%%}"; }
UNIT="service-admin.service"
LOGS="$HOME/.service-admin/logs"
PORT=8765

if [[ "${SA_SYSTEM_PYTHON:-}" == 1 ]]; then   # пакет .deb: системный Python 3.11+ (зависимость пакета), без загрузки своего
  PYTHON="$(command -v python3)" && "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || { msg "Нужен системный Python 3.11+" "A system Python 3.11+ is required"; exit 1; }
else
  say "$(msg "Готовлю встроенный Python панели…" "Preparing the panel's bundled Python…")"
  PYTHON="$("$DIR/fetch-python.sh")" || { msg "Не удалось подготовить встроенный Python" "Could not prepare the bundled Python"; exit 1; }
fi
[[ -x "$PYTHON" ]] || { echo "$(msg "Встроенный Python не найден:" "Bundled Python not found:") $PYTHON"; exit 1; }
mkdir -p -m 700 "$HOME/.service-admin" "$LOGS"; chmod 700 "$HOME/.service-admin"

HAVE_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  # у сессии ssh без входа на экран может не быть шины пользователя
  : "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"; export XDG_RUNTIME_DIR
  systemctl --user show-environment >/dev/null 2>&1 && HAVE_SYSTEMD=1
fi

if [[ "$HAVE_SYSTEMD" == 1 ]]; then
  say "$(msg "Устанавливаю службу systemd пользователя…" "Installing the systemd user service…")"
  mkdir -p "$UNIT_DIR"
  if [[ "$LOGS" == *[[:space:]%]* ]]; then LOGLINES=""; else LOGLINES="StandardOutput=append:$LOGS/server.log
StandardError=append:$LOGS/server.err"; fi   # путь с пробелом/% — журнал читайте через journalctl --user -u service-admin
  cat > "$UNIT_DIR/$UNIT" <<UNITEOF
[Unit]
Description=Service Admin (local web panel)

[Service]
ExecStart=$(sd_esc "$PYTHON") $(sd_esc "$DIR/server.py")
WorkingDirectory=$(sd_pct "$DIR")
Environment="PATH=$(sd_pct "$HOME")/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
Environment=LANG=C.UTF-8
Restart=always
RestartSec=5
$LOGLINES

[Install]
WantedBy=default.target
UNITEOF
  systemctl --user daemon-reload
  systemctl --user enable "$UNIT" >/dev/null 2>&1
  systemctl --user restart "$UNIT"
  if loginctl enable-linger "$USER_NAME" >/dev/null 2>&1; then
    say "$(msg "Служба будет стартовать при загрузке (linger включён)" "The service will start at boot (linger enabled)")"
  else
    msg "  Чтобы служба стартовала при загрузке без входа, выполните: sudo loginctl enable-linger $USER_NAME" "  To start the service at boot without a login, run: sudo loginctl enable-linger $USER_NAME"
  fi
else
  msg "systemd пользователя недоступен — запускаю сервер в фоне (после перезагрузки запустите его вручную)." "User systemd is not available — starting the server in the background (start it by hand after a reboot)."
  pkill -f -x "$PYTHON $DIR/server.py" 2>/dev/null || true
  (cd "$DIR" && setsid nohup "$PYTHON" "$DIR/server.py" </dev/null >"$LOGS/server.log" 2>"$LOGS/server.err" &)
fi

# ярлык в меню приложений (если есть графическая среда, он просто лежит без дела)
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/service-admin.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Service Admin
Comment=Local panel for the development environment
Exec=xdg-open http://127.0.0.1:$PORT
Icon=utilities-system-monitor
Terminal=false
Categories=Development;System;
DESK

for _ in $(seq 1 40); do curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/jobs" && break; sleep 0.25; done
if curl -fs -o /dev/null "http://127.0.0.1:$PORT/api/jobs"; then
  say "$(msg "Сервер работает:" "Server is running at") http://127.0.0.1:$PORT"
else
  msg "Сервер пока не отвечает. Лог:" "The server is not responding yet. Log:"; echo "  $LOGS/server.err"
fi
printf '\n\033[32m✓ %s\033[0m %s\n' "$(msg "Готово." "Done.")" "$(msg "Откройте" "Open") http://127.0.0.1:$PORT"
echo "  $(msg "Удаление:" "Uninstall:") $DIR/uninstall-linux.sh"
