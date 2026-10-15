#!/bin/zsh
# Язык сообщений: русский по умолчанию, английский при SA_LANG=en или LANG=en*
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then print -r -- "$2"; else print -r -- "$1"; fi; }
# Lepas Service Admin.app dan server otomatis. Data di ~/.service-admin (backup, state, shim) tidak dihapus.
set -uo pipefail
LABEL="local.service-admin"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && print "✓ $(msg "Автозапуск сервера остановлен" "Server auto-start stopped")"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
for app in "/Applications/Service Admin.app" "$HOME/Applications/Service Admin.app"; do
  [[ -d "$app" ]] && rm -rf "$app" && print "✓ $app $(msg "удалено" "removed")"
done
print "$(msg "Данные сохранены в ~/.service-admin (удалите вручную, если не нужны)." "Data is kept in ~/.service-admin (delete it by hand if you do not need it).")"
print "$(msg "Запуск вручную в любой момент:" "Run by hand at any time:") python3 ${0:A:h}/server.py"
