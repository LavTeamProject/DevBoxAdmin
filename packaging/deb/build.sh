#!/bin/bash
# Сборка пакета .deb (arch: all): исходники в /opt/service-admin (владелец root — безопасный источник для install-approver.sh),
# команды /usr/bin/service-admin и /usr/bin/service-admin-setup. Нужен dpkg-deb.   Использование: packaging/deb/build.sh [версия]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-$(python3 -c "import re;print(re.search(r'VERSION = \"([^\"]+)\"', open('$ROOT/version.py').read())[1])")}"
OUT="${OUT:-$ROOT/build}"
PKG="$OUT/pkg"
rm -rf "$PKG" && mkdir -p "$PKG/opt" "$PKG/usr/bin" "$PKG/DEBIAN" "$PKG/usr/share/doc/service-admin"
mkdir -p "$PKG/opt/service-admin"
( cd "$ROOT" && tar --exclude=.git --exclude=.github --exclude=build --exclude=__pycache__ --exclude=.DS_Store --exclude=tests --exclude='docs/screenshots' \
    --exclude='manuals/img' --exclude=macapp --exclude=install.sh --exclude=uninstall.sh -cf - . ) | tar -xf - -C "$PKG/opt/service-admin"
chmod -R go-w "$PKG/opt/service-admin"; chmod 755 "$PKG/opt/service-admin"/*.sh "$PKG/opt/service-admin/service-admin" "$PKG/opt/service-admin/linux/service-admin-approve" 2>/dev/null || true
cat > "$PKG/usr/bin/service-admin-setup" <<'SETUP'
#!/bin/sh
# Устанавливает службу Service Admin для ТЕКУЩЕГО пользователя (systemd user) на системном Python из пакета.
SA_SYSTEM_PYTHON=1 exec /opt/service-admin/install-linux.sh "$@"
SETUP
chmod 755 "$PKG/usr/bin/service-admin-setup"
ln -s /opt/service-admin/service-admin "$PKG/usr/bin/service-admin"
cat > "$PKG/DEBIAN/control" <<CTRL
Package: service-admin
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.11), curl, tar, openssh-client
Recommends: sshpass, qemu-utils, polkitd | policykit-1, zenity | kdialog
Maintainer: Service Admin <noreply@example.com>
Homepage: https://github.com/LavTeamProject/DevBoxAdmin
Description: local web panel for the development environment
 Service Admin is a local web panel (127.0.0.1 only) that prepares and manages a dev machine and lets AI agents work
 on it only through plans that a human approves. After installing, each user runs: service-admin-setup
CTRL
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
echo "Service Admin installed. For your user run:  service-admin-setup   (opens http://127.0.0.1:8765)"
echo "Agent approval without a screen: sudo /opt/service-admin/install-approver.sh <user>; then approve in your own terminal: pkexec /usr/local/libexec/service-admin-approve <request id>"
exit 0
POST
chmod 755 "$PKG/DEBIAN/postinst"
cp "$ROOT/LICENSE" "$PKG/usr/share/doc/service-admin/copyright"
mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/service-admin_${VERSION}_all.deb" >/dev/null
echo "$OUT/service-admin_${VERSION}_all.deb"
