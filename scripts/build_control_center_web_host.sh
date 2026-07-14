#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"
SRC="$ROOT/macos/RagImeControlWebHost"
APP="$ROOT/build/RagImeControlWebPreview.app"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ACTION="${1:-build}"

if [[ "$ACTION" != "build" && "$ACTION" != "install-preview" ]]; then
  echo "usage: $0 [build|install-preview]" >&2
  exit 2
fi

if [[ "${RAG_IME_SKIP_WEB_BUILD:-0}" != "1" ]]; then
  CI=true pnpm --dir "$WEB" install --frozen-lockfile
  pnpm --dir "$WEB" typecheck
  pnpm --dir "$WEB" test
  pnpm --dir "$WEB" build
fi

[[ -f "$WEB/dist/index.html" ]] || {
  echo "missing control-center-web/dist/index.html" >&2
  exit 1
}

rm -rf "$APP"
mkdir -p "$MACOS" "$RESOURCES/control-center-web"
cp "$SRC/Info.plist" "$CONTENTS/Info.plist"
ditto "$WEB/dist" "$RESOURCES/control-center-web"

swift_files=()
while IFS= read -r file; do swift_files+=("$file"); done < <(find "$SRC" -type f -name '*.swift' | sort)

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/tmp/rag-ime-control-web-clang-cache}" \
SWIFT_MODULECACHE_PATH="${SWIFT_MODULECACHE_PATH:-/tmp/rag-ime-control-web-swift-cache}" \
xcrun swiftc \
  -O \
  -swift-version 5 \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -framework UniformTypeIdentifiers \
  -framework WebKit \
  "${swift_files[@]}" \
  -o "$MACOS/RagImeControlWebPreview"

python3 - "$RESOURCES/rag-ime-control-web-build-marker.json" "$ROOT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
root = Path(sys.argv[2])
commit = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
).stdout.strip()
target.write_text(json.dumps({
    "bundleId": "com.rag-ime.control.web-preview",
    "gitCommit": commit,
    "ui": "control-center-web",
    "nativeBridgeVersion": 1,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

codesign --force --deep --sign - "$APP" >/dev/null
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$CONTENTS/Info.plist")"
[[ "$bundle_id" == "com.rag-ime.control.web-preview" ]] || {
  echo "unexpected preview bundle id: $bundle_id" >&2
  exit 1
}

otool -L "$MACOS/RagImeControlWebPreview" | grep -q '/WebKit.framework/' || {
  echo "preview host must link WebKit" >&2
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

if [[ "$ACTION" == "install-preview" ]]; then
  DEST="$HOME/Applications/RagImeControlWebPreview.app"
  mkdir -p "$HOME/Applications"
  rm -rf "$DEST"
  ditto "$APP" "$DEST"
  codesign --verify --deep --strict "$DEST"
  echo "$DEST"
else
  echo "$APP"
fi
