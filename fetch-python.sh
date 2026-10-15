#!/bin/zsh
# Unduh CPython standalone (python-build-standalone) ke ~/.service-admin/runtime/python/.
# Hanya memakai alat yang ada di macOS bersih: curl, tar, shasum, grep, sed, uname.
# Mencetak path interpreter ke stdout; semua pesan lain ke stderr.
#
# Pemakaian:  PY="$(./fetch-python.sh)"
#   SA_RUNTIME_DIR  lokasi tujuan (default ~/.service-admin/runtime) - untuk uji, jangan ke HOME asli
#   SA_PY_SERIES    seri Python (default 3.12)
set -euo pipefail
# Язык сообщений: русский по умолчанию, английский при SA_LANG=en или LANG=en*
msg() { if [[ "${SA_LANG:-${LANG:-ru}}" == en* ]]; then print -r -- "$2"; else print -r -- "$1"; fi; }

RUNTIME="${SA_RUNTIME_DIR:-$HOME/.service-admin/runtime}"
SERIES="${SA_PY_SERIES:-3.12}"
REPO="astral-sh/python-build-standalone"
PY="$RUNTIME/python/bin/python3"

log() { print -r -- "==> $1" >&2; }
die() { print -r -- "fetch-python: $1" >&2; exit 1; }

# Sudah ada dan versinya cocok: tidak mengunduh ulang (idempoten).
if [[ -x "$PY" ]] && "$PY" -c "import sys; sys.exit(0 if sys.version_info[:2] == tuple(map(int, '$SERIES'.split('.'))) else 1)" 2>/dev/null; then
  log "$(msg "Встроенный Python $SERIES уже есть" "Bundled Python $SERIES is already installed")"
  print -r -- "$PY"
  exit 0
fi

case "$(uname -m)" in
  arm64)  ARCH="aarch64" ;;
  x86_64) ARCH="x86_64" ;;
  *) die "$(msg "архитектура не поддерживается:" "unsupported architecture:") $(uname -m)" ;;
esac

log "$(msg "Ищу последний релиз python-build-standalone…" "Looking for the latest python-build-standalone release…")"
API="$(curl -fsSL --retry 3 "https://api.github.com/repos/$REPO/releases/latest")" \
  || die "$(msg "не удалось связаться с GitHub API" "cannot reach the GitHub API")"
# Tanpa Python/jq di mesin bersih: ambil URL aset dengan grep. sort -V memilih patch tertinggi seri itu.
URL="$(print -r -- "$API" \
  | grep -o "https://[^\"]*cpython-${SERIES//./\\.}\.[0-9]*\(+\|%2B\)[0-9]*-${ARCH}-apple-darwin-install_only\.tar\.gz" \
  | sort -uV | tail -1)" || true
[[ -n "$URL" ]] || die "$(msg "в последнем релизе нет cpython-$SERIES для $ARCH" "the latest release has no cpython-$SERIES for $ARCH")"
SUMS_URL="${URL%/*}/SHA256SUMS"
NAME="${URL##*/}"
NAME="${NAME//\%2B/+}"   # GitHub meng-encode "+" jadi %2B di URL; SHA256SUMS memakai "+"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/sa-python.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

log "$(msg "Скачиваю" "Downloading") $NAME…"
curl -fL --retry 3 --progress-bar -o "$TMP/$NAME" "$URL" || die "$(msg "скачивание не удалось" "download failed")"

# Verifikasi checksum dari rilis yang sama. Tanpa cocok = berhenti, jangan dipasang.
log "$(msg "Проверяю контрольную сумму…" "Verifying the checksum…")"
curl -fsSL --retry 3 -o "$TMP/SHA256SUMS" "$SUMS_URL" || die "$(msg "не удалось скачать SHA256SUMS" "cannot download SHA256SUMS")"
EXPECT="$(grep -F "$NAME" "$TMP/SHA256SUMS" | awk '{print $1}' | head -1)"
[[ -n "$EXPECT" ]] || die "$(msg "в SHA256SUMS нет суммы для" "SHA256SUMS has no checksum for") $NAME"
ACTUAL="$(shasum -a 256 "$TMP/$NAME" | awk '{print $1}')"
[[ "$EXPECT" == "$ACTUAL" ]] || die "$(msg "контрольная сумма не совпала (ожидалась" "checksum mismatch (expected") $EXPECT, $(msg "получена" "got") $ACTUAL)"

# Ekstrak ke folder sementara dulu, lalu tukar: kegagalan di tengah tidak merusak runtime lama.
log "$(msg "Распаковываю…" "Extracting…")"
mkdir -p "$RUNTIME"
tar -xzf "$TMP/$NAME" -C "$TMP" || die "$(msg "распаковка не удалась" "extraction failed")"
[[ -x "$TMP/python/bin/python3" ]] || die "$(msg "в архиве нет python/bin/python3" "the archive has no python/bin/python3")"
"$TMP/python/bin/python3" -c "import tomllib, ssl, sqlite3" 2>/dev/null || die "$(msg "скачанный интерпретатор не прошёл проверку импорта" "the downloaded interpreter failed the import check")"
rm -rf "$RUNTIME/python"
mv "$TMP/python" "$RUNTIME/python"

log "Python $("$PY" -V 2>&1 | awk '{print $2}') $(msg "установлен в" "installed in") $RUNTIME/python"
print -r -- "$PY"
