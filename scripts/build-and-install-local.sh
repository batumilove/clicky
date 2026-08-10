#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${CLICKY_APP_PATH:-$HOME/Applications/Clicky.app}"
APP_PARENT="$(dirname "$APP")"
SWIFT_BIN="${SWIFT_BIN:-$HOME/.swiftly/bin/swift}"
if [[ ! -x "$SWIFT_BIN" ]]; then
  SWIFT_BIN="$(command -v swift)"
fi

mkdir -p "$APP_PARENT"
STAGE_ROOT="$(mktemp -d "$APP_PARENT/.Clicky.install.XXXXXX")"
chmod 700 "$STAGE_ROOT"
STAGED_APP="$STAGE_ROOT/Clicky.app"
BACKUP_APP="$STAGE_ROOT/Clicky.previous.app"
SWAPPED=0
NEW_INSTALLED=0

atomic_swap() {
  /usr/bin/python3 - "$1" "$2" <<'PY'
import ctypes
import os
import sys

AT_FDCWD = -2
RENAME_SWAP = 0x00000002
left, right = map(os.fsencode, sys.argv[1:3])
libc = ctypes.CDLL(None, use_errno=True)
renameatx_np = libc.renameatx_np
renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
renameatx_np.restype = ctypes.c_int
if renameatx_np(AT_FDCWD, left, AT_FDCWD, right, RENAME_SWAP) != 0:
    err = ctypes.get_errno()
    raise OSError(err, os.strerror(err))
PY
}

cleanup() {
  rm -rf "$STAGE_ROOT"
}

rollback() {
  status="$1"
  trap - ERR INT TERM
  set +e
  if [[ "$SWAPPED" -eq 1 ]]; then
    if [[ -e "$BACKUP_APP" ]]; then
      atomic_swap "$BACKUP_APP" "$APP"
      rm -rf "$BACKUP_APP"
    elif [[ -e "$STAGED_APP" ]]; then
      atomic_swap "$STAGED_APP" "$APP"
    fi
  elif [[ "$NEW_INSTALLED" -eq 1 ]]; then
    rm -rf "$APP"
  fi
  exit "$status"
}

trap cleanup EXIT
trap 'rollback $?' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM

cd "$ROOT"
"$SWIFT_BIN" build -c release --product Clicky --disable-sandbox

mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources" "$STAGED_APP/Contents/Frameworks"
cp "$ROOT/.build/release/Clicky" "$STAGED_APP/Contents/MacOS/Clicky"
chmod +x "$STAGED_APP/Contents/MacOS/Clicky"
cp "$ROOT/leanring-buddy/Info.plist" "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleExecutable Clicky' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleExecutable string Clicky' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier so.clicky.gpt55.local' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string so.clicky.gpt55.local' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName Clicky' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleName string Clicky' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Clicky' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleDisplayName string Clicky' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 0.1-gpt55' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleShortVersionString string 0.1-gpt55' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleVersion 1' "$STAGED_APP/Contents/Info.plist" 2>/dev/null || /usr/libexec/PlistBuddy -c 'Add :CFBundleVersion string 1' "$STAGED_APP/Contents/Info.plist"

RESOURCE_BUNDLE="$(find "$ROOT/.build/arm64-apple-macosx/release" -maxdepth 1 -type d -name 'ClickyCheck_ClickyCheck.bundle' -print -quit)"
if [[ -n "$RESOURCE_BUNDLE" ]]; then
  cp -R "$RESOURCE_BUNDLE" "$STAGED_APP/Contents/Resources/"
fi
SPARKLE_FRAMEWORK="$(find "$ROOT/.build/arm64-apple-macosx/release" -maxdepth 1 -type d -name 'Sparkle.framework' -print -quit)"
if [[ -n "$SPARKLE_FRAMEWORK" ]]; then
  cp -R "$SPARKLE_FRAMEWORK" "$STAGED_APP/Contents/Frameworks/"
fi

# SwiftPM's executable may only contain @loader_path; an app bundle needs this
# rpath so @rpath/Sparkle.framework resolves from Contents/Frameworks.
install_name_tool -add_rpath '@executable_path/../Frameworks' "$STAGED_APP/Contents/MacOS/Clicky" 2>/dev/null || true
codesign --force --deep --sign - "$STAGED_APP"
codesign --verify --deep --strict --verbose=2 "$STAGED_APP" >/dev/null
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$STAGED_APP/Contents/Info.plist")" == "so.clicky.gpt55.local" ]]

if [[ -e "$APP" ]]; then
  atomic_swap "$STAGED_APP" "$APP"
  SWAPPED=1
  mv "$STAGED_APP" "$BACKUP_APP"
else
  mv "$STAGED_APP" "$APP"
  NEW_INSTALLED=1
fi

codesign --verify --deep --strict --verbose=2 "$APP" >/dev/null
[[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist")" == "so.clicky.gpt55.local" ]]

rm -rf "$BACKUP_APP"
SWAPPED=0
NEW_INSTALLED=0
trap - ERR INT TERM
printf 'Installed %s\n' "$APP"
