#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"
SRC="$ROOT/macos/RagImeControlWebHost"
SHARED="$ROOT/macos/Shared"
ACTION="${1:-build}"

case "$ACTION" in
  build|install-preview)
    APP="$ROOT/build/RagImeControlWebPreview.app"
    EXECUTABLE="RagImeControlWebPreview"
    BUNDLE_ID="com.rag-ime.control.web-preview"
    DISPLAY_NAME="智鼬 Web Preview"
    INSTALL_DEST="$HOME/Applications/RagImeControlWebPreview.app"
    CHANNEL="preview"
    FRONTEND_CHANNEL="preview"
    ;;
  build-release|install-release)
    APP="$ROOT/build/RagImeControl.app"
    EXECUTABLE="RagImeControl"
    BUNDLE_ID="com.rag-ime.control"
    DISPLAY_NAME="智鼬"
    INSTALL_DEST="$HOME/Applications/RagImeControl.app"
    CHANNEL="release"
    FRONTEND_CHANNEL="production"
    ;;
  *)
    echo "usage: $0 [build|install-preview|build-release|install-release]" >&2
    exit 2
    ;;
esac

CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
USE_VERIFIED_WEB_DIST="${RAG_IME_USE_VERIFIED_WEB_DIST:-0}"

if [[ "$FRONTEND_CHANNEL" == "production" && "${RAG_IME_SKIP_WEB_BUILD:-0}" == "1" ]]; then
  echo "release builds cannot reuse a pre-existing control-center dist" >&2
  exit 2
fi

if [[ "$USE_VERIFIED_WEB_DIST" != "0" && "$USE_VERIFIED_WEB_DIST" != "1" ]]; then
  echo "RAG_IME_USE_VERIFIED_WEB_DIST must be 0 or 1" >&2
  exit 2
fi

if [[ "$USE_VERIFIED_WEB_DIST" == "0" && "${RAG_IME_SKIP_WEB_BUILD:-0}" != "1" ]]; then
  RAG_IME_CONTROL_TRANSPORT=native \
  RAG_IME_CONTROL_BUILD_CHANNEL="$FRONTEND_CHANNEL" \
    "$ROOT/scripts/build_control_center_web.sh" >/dev/null
fi

[[ -f "$WEB/dist/index.html" ]] || {
  echo "missing control-center-web/dist/index.html" >&2
  exit 1
}
"$ROOT/scripts/check_control_center_web_dist.sh" \
  "$WEB/dist" native "$FRONTEND_CHANNEL" "$SOURCE_COMMIT" >/dev/null

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES/control-center-web"
cp "$SRC/Info.plist" "$CONTENTS/Info.plist"
ditto "$WEB/dist" "$RESOURCES/control-center-web"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $DISPLAY_NAME" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable $EXECUTABLE" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $EXECUTABLE" "$CONTENTS/Info.plist"

swift_files=()
while IFS= read -r file; do swift_files+=("$file"); done < <(find "$SRC" -type f -name '*.swift' | sort)
swift_files+=(
  "$SHARED/VoiceAgentStatus.swift"
  "$SHARED/VoiceKeychainStore.swift"
)

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/tmp/rag-ime-control-web-clang-cache}" \
SWIFT_MODULECACHE_PATH="${SWIFT_MODULECACHE_PATH:-/tmp/rag-ime-control-web-swift-cache}" \
xcrun swiftc \
  -O \
  -swift-version 5 \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework Security \
  -framework UniformTypeIdentifiers \
  -framework WebKit \
  "${swift_files[@]}" \
  -o "$MACOS/$EXECUTABLE"

python3 - "$RESOURCES/rag-ime-control-web-build-marker.json" "$ROOT" "$BUNDLE_ID" "$CHANNEL" "$FRONTEND_CHANNEL" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
root = Path(sys.argv[2])
bundle_id = sys.argv[3]
channel = sys.argv[4]
frontend_channel = sys.argv[5]
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
).stdout.strip()
target.write_text(json.dumps({
    "bundleId": bundle_id,
    "gitCommit": commit,
    "ui": "control-center-web",
    "channel": channel,
    "frontendTransport": "native",
    "frontendBuildChannel": frontend_channel,
    "forbiddenTransportModulesExcluded": True,
    "nativeBridgeVersion": 1,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

"$ROOT/scripts/support/build_app_icon.sh" "$RESOURCES/RagImeIcon.icns"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIconFile string RagImeIcon' "$CONTENTS/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIconFile RagImeIcon' "$CONTENTS/Info.plist"

codesign --force --deep --sign - "$APP" >/dev/null
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$CONTENTS/Info.plist")"
[[ "$bundle_id" == "$BUNDLE_ID" ]] || {
  echo "unexpected bundle id: $bundle_id" >&2
  exit 1
}

otool -L "$MACOS/$EXECUTABLE" | grep -q '/WebKit.framework/' || {
  echo "web host must link WebKit" >&2
  exit 1
}
[[ ! -d "$RESOURCES/control-center-web/node_modules" ]] || {
  echo "node_modules must not enter the app bundle" >&2
  exit 1
}
if grep -R -q "unsafe-eval" "$RESOURCES/control-center-web"; then
  echo "control-center bundle CSP must not allow unsafe-eval" >&2
  exit 1
fi
"$ROOT/scripts/check_control_center_web_dist.sh" \
  "$RESOURCES/control-center-web" native "$FRONTEND_CHANNEL" "$SOURCE_COMMIT" >/dev/null

if [[ "$ACTION" == "install-preview" || "$ACTION" == "install-release" ]]; then
  DEST="$INSTALL_DEST"
  LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  PROCESS_PATTERN="/Contents/MacOS/$EXECUTABLE([[:space:]]|$)"
  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    pgrep -f "$PROCESS_PATTERN" >/dev/null 2>&1 || break
    sleep 0.1
  done
  if pgrep -f "$PROCESS_PATTERN" >/dev/null 2>&1; then
    pkill -TERM -f "$PROCESS_PATTERN" >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
      pgrep -f "$PROCESS_PATTERN" >/dev/null 2>&1 || break
      sleep 0.1
    done
  fi
  if pgrep -f "$PROCESS_PATTERN" >/dev/null 2>&1; then
    echo "unable to stop the existing $EXECUTABLE before installation" >&2
    exit 1
  fi
  while IFS= read -r registered_app; do
    [[ -n "$registered_app" && "$registered_app" != "$DEST" ]] || continue
    "$LSREGISTER" -u "$registered_app" >/dev/null 2>&1 || true
  done < <(mdfind "kMDItemCFBundleIdentifier == '$BUNDLE_ID'" 2>/dev/null || true)
  mkdir -p "$HOME/Applications"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  codesign --verify --deep --strict "$DEST"
  otool -L "$DEST/Contents/MacOS/$EXECUTABLE" | grep -q '/WebKit.framework/'
  "$ROOT/scripts/check_control_center_web_dist.sh" \
    "$DEST/Contents/Resources/control-center-web" native "$FRONTEND_CHANNEL" "$SOURCE_COMMIT" >/dev/null
  python3 - "$DEST/Contents/Resources/rag-ime-control-web-build-marker.json" "$BUNDLE_ID" "$CHANNEL" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    marker = json.load(handle)
if marker.get("bundleId") != sys.argv[2]:
    raise SystemExit("installed Web control center has the wrong bundle id")
if marker.get("ui") != "control-center-web" or marker.get("channel") != sys.argv[3]:
    raise SystemExit("installed app is not the requested Web control center channel")
if marker.get("frontendTransport") != "native":
    raise SystemExit("installed Web control center is not using the native bridge")
PY
  "$LSREGISTER" -f "$DEST" >/dev/null
  echo "$DEST"
else
  echo "$APP"
fi
