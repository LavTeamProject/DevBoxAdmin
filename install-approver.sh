#!/bin/bash
# Установка корневого помощника подтверждения агентов (Linux, канал B из ADR-0001). Запускать человеку: sudo ./install-approver.sh <пользователь>
# Копирует помощник в /usr/local/libexec (root:root 0755), действие polkit (auth_admin) и создаёт /var/lib/service-admin/approvals/<uid> (root:root 0755).
set -euo pipefail
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
[[ "$(uname -s)" == Linux ]] || { msg "Только для Linux" "Linux only"; exit 1; }
[[ "$(id -u)" == 0 ]] || { msg "Запустите через sudo: sudo ./install-approver.sh <пользователь>" "Run with sudo: sudo ./install-approver.sh <user>"; exit 1; }
TARGET="${1:-${SUDO_USER:-}}"
[[ -n "$TARGET" && "$TARGET" != root ]] || { msg "Укажите обычного пользователя панели" "Give the panel's regular user"; exit 1; }
UID_T="$(id -u "$TARGET")"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Устанавливаем от root код, который потом решает «одобрено ли». Нельзя брать его из каталога, в который может писать пользователь панели (или агент).
p="$DIR/linux/service-admin-approve"
while [[ "$p" != "/" ]]; do
  if sudo -n -u "$TARGET" test -w "$p" 2>/dev/null; then
    msg "ОТКАЗ: $p доступен на запись пользователю $TARGET. Скопируйте проект в каталог, принадлежащий root (например: sudo cp -r <папка> /opt/service-admin-src), и запустите установщик оттуда." \
        "REFUSED: $p is writable by $TARGET. Copy the project into a root-owned directory (e.g. sudo cp -r <folder> /opt/service-admin-src) and run the installer from there."
    exit 1
  fi
  p="$(dirname "$p")"
done
command -v pkexec >/dev/null || msg "pkexec не найден: останется запасной путь через sudo (sudo apt-get install -y polkitd pkexec — для основного)" "pkexec not found: only the sudo fallback will work (sudo apt-get install -y polkitd pkexec for the main path)"
install -d -m 755 -o root -g root /usr/local/libexec /var/lib/service-admin /var/lib/service-admin/approvals
install -d -m 755 -o root -g root "/var/lib/service-admin/approvals/$UID_T"
install -m 755 -o root -g root "$DIR/linux/service-admin-approve" /usr/local/libexec/service-admin-approve
if [[ -d /usr/share/polkit-1/actions ]]; then install -m 644 -o root -g root "$DIR/linux/local.service-admin.approve.policy" /usr/share/polkit-1/actions/local.service-admin.approve.policy; fi
# запасной путь через sudo: пароль спрашивается КАЖДЫЙ раз (кэш sudo для этой команды отключён)
SUDOERS=/etc/sudoers.d/service-admin-approve
printf 'Defaults!/usr/local/libexec/service-admin-approve timestamp_timeout=0\n' > "$SUDOERS.tmp"
chmod 440 "$SUDOERS.tmp"
if command -v visudo >/dev/null && visudo -cf "$SUDOERS.tmp" >/dev/null; then mv "$SUDOERS.tmp" "$SUDOERS"; else rm -f "$SUDOERS.tmp"; msg "sudoers-файл не создан (visudo не прошёл)" "sudoers file not created (visudo failed)"; fi
msg "Готово. Одобрять планы агентов — в СВОЁМ терминале: pkexec /usr/local/libexec/service-admin-approve <id запроса> (или sudo, если нет polkit)" "Done. To approve agent plans, in YOUR OWN terminal: pkexec /usr/local/libexec/service-admin-approve <request id> (or sudo if there is no polkit)"
if sudo -n -u "$TARGET" sudo -n true 2>/dev/null; then
  msg "ВНИМАНИЕ: у $TARGET есть sudo без пароля — канал подтверждения будет отключён (агент мог бы одобрять сам). Уберите NOPASSWD." "WARNING: $TARGET has passwordless sudo — the approval channel stays disabled (an agent could approve by itself). Remove NOPASSWD."
fi
