#!/bin/bash
# Снимает службу и ярлык Service Admin на Linux. Данные в ~/.service-admin не удаляются.
set -uo pipefail
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
: "${XDG_RUNTIME_DIR:=/run/user/$(id -u)}"; export XDG_RUNTIME_DIR
if systemctl --user disable --now service-admin.service >/dev/null 2>&1; then echo "✓ $(msg "Служба остановлена" "Service stopped")"; fi
rm -f "$HOME/.config/systemd/user/service-admin.service" "$HOME/.local/share/applications/service-admin.desktop"
systemctl --user daemon-reload >/dev/null 2>&1 || true
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pkill -f -x "$HOME/.service-admin/runtime/python/bin/python3 $DIR/server.py" 2>/dev/null || true
msg "Данные сохранены в ~/.service-admin (удалите вручную, если не нужны)." "Data is kept in ~/.service-admin (delete it by hand if you do not need it)."
