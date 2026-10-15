#!/bin/bash
# Установка одной командой (нужны только curl и tar из macOS):
#   curl -fsSL https://raw.githubusercontent.com/LavTeamProject/DevBoxAdmin/main/get.sh | bash
# Скачивает исходники в ~/.service-admin/app и запускает install.sh оттуда. Повторный запуск = обновление (данные ~/.service-admin не трогаются).
# Переменные: SA_REF=<тег|коммит|ветка> (по умолчанию main), SA_SHA256=<сумма архива> (если задана — проверяется),
#             SA_SRC_URL=<адрес архива> (для проверок), SA_NO_INSTALL=1 (только скачать и распаковать), SA_LANG=ru|en.
set -euo pipefail
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
die() { printf '%s\n' "get.sh: $1" >&2; exit 1; }

REPO="LavTeamProject/DevBoxAdmin"
REF="${SA_REF:-main}"
REF_RE='^[A-Za-z0-9._/-]{1,100}$'
[[ "$REF" =~ $REF_RE && "$REF" != *..* ]] || die "$(msg "недопустимый SA_REF" "invalid SA_REF")"
URL="${SA_SRC_URL:-https://codeload.github.com/$REPO/tar.gz/$REF}"
ROOT="$HOME/.service-admin"
APP="$ROOT/app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf '%s\n' "==> $(msg "Скачиваю Service Admin ($REF)…" "Downloading Service Admin ($REF)…")"
curl -fsSL --retry 3 -o "$TMP/src.tar.gz" "$URL" || die "$(msg "скачивание не удалось (нет интернета или VPN?)" "download failed (no internet, or a VPN in the way?)")"
if [[ -n "${SA_SHA256:-}" ]]; then
  if command -v sha256sum >/dev/null 2>&1; then got="$(sha256sum "$TMP/src.tar.gz" | cut -d' ' -f1)"; else got="$(shasum -a 256 "$TMP/src.tar.gz" | cut -d' ' -f1)"; fi
  [[ "$got" == "$SA_SHA256" ]] || die "$(msg "контрольная сумма не совпала — установка остановлена" "checksum mismatch — installation stopped")"
  printf '%s\n' "==> sha256 OK"
fi

mkdir -p "$TMP/x"
# в архиве не должно быть абсолютных путей и «..»
if tar -tzf "$TMP/src.tar.gz" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then die "$(msg "небезопасный архив" "unsafe archive")"; fi
tar -xzf "$TMP/src.tar.gz" -C "$TMP/x" --strip-components=1
[[ -x "$TMP/x/install.sh" && -x "$TMP/x/install-linux.sh" && -f "$TMP/x/server.py" ]] || die "$(msg "в архиве нет install.sh/install-linux.sh/server.py" "install.sh/install-linux.sh/server.py not found in the archive")"

mkdir -p "$ROOT"
rm -rf "$APP.old"
[[ -d "$APP" ]] && mv "$APP" "$APP.old"
mv "$TMP/x" "$APP"
rm -rf "$APP.old"
printf '%s\n' "==> $(msg "Исходники: $APP" "Sources: $APP")"

[[ "${SA_NO_INSTALL:-}" == 1 ]] && exit 0
cd "$APP"
if [[ "$(uname -s)" == Linux ]]; then exec ./install-linux.sh; else exec ./install.sh; fi
