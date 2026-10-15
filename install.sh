#!/bin/zsh
# Pasang Service Admin agar mudah dibuka:
#   1. Server otomatis jalan saat login (LaunchAgent, dinyalakan ulang kalau berhenti)
#   2. "Service Admin.app" di /Applications: peluncur yang membuka dashboard di browser
#      (Spotlight, Launchpad, atau Dock)
#
# Pemakaian:  ./install.sh            (build + pasang + buka aplikasi)
#             ./install.sh --no-open  (tanpa membuka aplikasi di akhir)
set -euo pipefail
# Язык сообщений: русский по умолчанию, английский при SA_LANG=en или LANG=en*
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then print -r -- "$2"; else print -r -- "$1"; fi; }

DIR="${0:A:h}"
APP_NAME="Service Admin"
APP_DIR="/Applications/$APP_NAME.app"
[[ -w /Applications ]] || APP_DIR="$HOME/Applications/$APP_NAME.app"
LABEL="local.service-admin"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/.service-admin/logs"
BUILD="$DIR/build"

say() { print -P "%F{blue}==>%f $1"; }

# Python bawaan panel (bukan Python sistem): di macOS bersih tidak ada Python 3.11+.
say "$(msg "Готовлю встроенный Python панели…" "Preparing the panel's bundled Python…")"
PYTHON="$("$DIR/fetch-python.sh")" || { print "$(msg "Не удалось подготовить встроенный Python" "Could not prepare the bundled Python")"; exit 1; }
[[ -x "$PYTHON" ]] || { print "$(msg "Встроенный Python не найден:" "Bundled Python not found:") $PYTHON"; exit 1; }

# ---------------------------------------------------------------- 1. build aplikasi
# Peluncur = applet AppleScript yang dikompilasi /usr/bin/osacompile (bagian dari macOS, tanpa
# Command Line Tools / swiftc). Ikon (macapp/AppIcon.icns) sudah jadi di repo; dibuat ulang dengan
# macapp/makeicon.swift hanya bila desainnya berubah.
say "$(msg "Собираю приложение-лаунчер (osacompile)…" "Building the launcher app (osacompile)…")"
rm -rf "$BUILD" && mkdir -p "$BUILD"
BUNDLE="$BUILD/$APP_NAME.app"
/usr/bin/osacompile -o "$BUNDLE" "$DIR/macapp/launcher.applescript"
# osacompile menaruh Assets.car + CFBundleIconName yang menimpa ikon kita; buang, pakai ikon sendiri.
rm -f "$BUNDLE/Contents/Resources/Assets.car"
cp "$DIR/macapp/AppIcon.icns" "$BUNDLE/Contents/Resources/applet.icns"
# /usr/bin/git di macOS bersih hanyalah stub yang membuka dialog Apple "Install Command Line Tools"
# di tengah instalasi. Panggil git hanya bila CLT memang sudah terpasang.
VERSION=dev
if xcode-select -p >/dev/null 2>&1; then
  VERSION="$(git -C "$DIR" rev-parse --short HEAD 2>/dev/null || echo dev)"
fi
PB=/usr/libexec/PlistBuddy
INFO="$BUNDLE/Contents/Info.plist"
$PB -c "Delete :CFBundleIconName" "$INFO" 2>/dev/null || true
$PB -c "Set :CFBundleName $APP_NAME" "$INFO"
$PB -c "Add :CFBundleDisplayName string $APP_NAME" "$INFO"
$PB -c "Add :CFBundleIdentifier string local.service-admin.app" "$INFO"
$PB -c "Add :CFBundleShortVersionString string 1.0" "$INFO"
$PB -c "Add :CFBundleVersion string $VERSION" "$INFO"
$PB -c "Add :LSMinimumSystemVersion string 13.0" "$INFO"
$PB -c "Add :LSApplicationCategoryType string public.app-category.developer-tools" "$INFO"
$PB -c "Add :LSUIElement bool true" "$INFO"   # tanpa ikon Dock yang tertinggal
$PB -c "Add :SAProjectDir string $DIR" "$INFO"
$PB -c "Add :SAPython string $PYTHON" "$INFO"
codesign --force --deep --sign - "$BUNDLE" 2>/dev/null   # tanda tangan ad-hoc agar tidak dianggap rusak

say "$(msg "Устанавливаю приложение в" "Installing the app to") $APP_DIR…"
osascript -e "quit app \"$APP_NAME\"" 2>/dev/null || true   # tutup versi lama yang sedang terbuka
mkdir -p "${APP_DIR:h}"
rm -rf "$APP_DIR"
cp -R "$BUNDLE" "$APP_DIR"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DIR" 2>/dev/null || true

# ---------------------------------------------------------------- 2. server otomatis (LaunchAgent)
say "$(msg "Устанавливаю автозапуск сервера при входе…" "Installing the server auto-start at login…")"
mkdir -p "$LOGS" "${PLIST:h}"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PYTHON</string><string>$DIR/server.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>LANG</key><string>en_US.UTF-8</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOGS/server.log</string>
  <key>StandardErrorPath</key><string>$LOGS/server.err</string>
</dict></plist>
EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
# server yang dijalankan manual di port 8765 dihentikan supaya LaunchAgent bisa memakai port itu
if pids=$(lsof -ti tcp:8765 -sTCP:LISTEN 2>/dev/null) && [[ -n "$pids" ]]; then
  say "$(msg "Останавливаю сервер, запущенный вручную (PID $pids)…" "Stopping the manually started server (PID $pids)…")"
  kill $=pids 2>/dev/null || true
  sleep 1
fi
launchctl bootstrap "gui/$UID" "$PLIST"

for i in {1..40}; do
  curl -fs -o /dev/null "http://127.0.0.1:8765/api/jobs" && break
  sleep 0.25
done
if curl -fs -o /dev/null "http://127.0.0.1:8765/api/jobs"; then
  say "$(msg "Сервер работает:" "Server is running at") http://127.0.0.1:8765"
else
  print -P "%F{yellow}$(msg "Сервер пока не отвечает." "The server is not responding yet.")%f $(msg "Если появится диалог «Python хочет получить доступ к папке «Документы»», нажмите «Разрешить»" "If a dialog \"Python would like to access the Documents folder\" appears, click Allow")"
  print   "  $(msg "(или Системные настройки → Конфиденциальность и безопасность → Файлы и папки → Python → Документы)." "(or System Settings → Privacy & Security → Files & Folders → Python → Documents).")"
  print   "  $(msg "Сервер продолжит сам после выдачи разрешения. Лог:" "The server continues by itself once permission is granted. Log:") $LOGS/server.err"
fi

print -P "\n%F{green}✓ $(msg "Готово." "Done.")%f $(msg "Откройте" "Open") %B$APP_NAME%b $(msg "через Spotlight (⌘Пробел), Launchpad или Dock." "from Spotlight (⌘Space), Launchpad or the Dock.")"
print   "  $(msg "Удаление:" "Uninstall:") $DIR/uninstall.sh"
[[ "${1:-}" == "--no-open" ]] || open "$APP_DIR"   # membuka dashboard di browser
