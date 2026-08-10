#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${CLICKY_APP_PATH:-$HOME/Applications/Clicky.app}"
case "$APP" in
  /*) ;;
  *)
    printf 'Clicky bundle destination must be absolute: %s\n' "$APP" >&2
    exit 2
    ;;
esac
APP_PARENT="$(dirname "$APP")"
SWIFT_BIN="${SWIFT_BIN:-$HOME/.swiftly/bin/swift}"
if [[ ! -x "$SWIFT_BIN" ]]; then
  SWIFT_BIN="$(command -v swift)"
fi

if [[ ! -d "$APP_PARENT" ]]; then
  printf 'Clicky bundle parent must already exist: %s\n' "$APP_PARENT" >&2
  exit 2
fi
cd "$ROOT"
/usr/bin/python3 -c 'import sys; from pathlib import Path; from scripts.atomic_replace_app import _validate_path; _validate_path(Path(sys.argv[1]), must_exist=False)' "$APP"

STAGE_ROOT="$(mktemp -d "$APP_PARENT/.Clicky.install.XXXXXX")"
chmod 700 "$STAGE_ROOT"
STAGED_APP="$STAGE_ROOT/Clicky.app"
KEEP_STAGE=0
REPLACEMENT_STARTED=0
COMMITTED=0

cleanup() {
  if [[ "$KEEP_STAGE" -eq 1 ]]; then
    printf 'Preserved Clicky rollback evidence at %s\n' "$STAGE_ROOT" >&2
  else
    rm -rf "$STAGE_ROOT"
  fi
}

preserve_on_failure() {
  status="$1"
  trap - ERR INT TERM
  if [[ "$REPLACEMENT_STARTED" -eq 1 && "$COMMITTED" -eq 0 ]]; then
    KEEP_STAGE=1
  fi
  exit "$status"
}

trap cleanup EXIT
trap 'preserve_on_failure $?' ERR
trap 'preserve_on_failure 130' INT
trap 'preserve_on_failure 143' TERM

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

REPLACEMENT_STARTED=1
set +e
/usr/bin/python3 "$ROOT/scripts/atomic_replace_app.py" "$STAGED_APP" "$APP"
replace_status=$?
set -e
if [[ "$replace_status" -ne 0 ]]; then
  KEEP_STAGE=1
  exit "$replace_status"
fi
COMMITTED=1
trap - ERR INT TERM
printf 'Installed %s\n' "$APP"
