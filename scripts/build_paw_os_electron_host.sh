#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"
ELECTRON_APP="$WEB/node_modules/electron/dist/Electron.app"
ELECTRON_INSTALLER="$WEB/node_modules/electron/install.js"
ACTION="${1:-build}"

case "$ACTION" in
  build|install-preview)
    APP="$ROOT/build/RagImeControlElectronPreview.app"
    INSTALL_DEST="$HOME/Applications/RagImeControlWebPreview.app"
    EXECUTABLE="RagImeControlWebPreview"
    BUNDLE_ID="com.rag-ime.control.web-preview"
    DISPLAY_NAME="PAW Preview"
    CHANNEL="preview"
    FRONTEND_CHANNEL="preview"
    ;;
  build-release|install-release)
    APP="$ROOT/build/RagImeControlElectron.app"
    INSTALL_DEST="$HOME/Applications/RagImeControl.app"
    EXECUTABLE="RagImeControl"
    BUNDLE_ID="com.rag-ime.control"
    DISPLAY_NAME="PAW"
    CHANNEL="release"
    FRONTEND_CHANNEL="production"
    ;;
  *)
    echo "usage: $0 [build|install-preview|build-release|install-release]" >&2
    exit 2
    ;;
esac

if [[ ! -d "$ELECTRON_APP" ]]; then
  [[ -f "$ELECTRON_INSTALLER" ]] || {
    echo "Electron package is unavailable; run pnpm install in control-center-web" >&2
    exit 1
  }
  echo "Hydrating the pinned Electron runtime..." >&2
  node "$ELECTRON_INSTALLER"
fi
[[ -d "$ELECTRON_APP" ]] || {
  echo "Electron runtime hydration did not produce Electron.app" >&2
  exit 1
}

SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
SOURCE_BRANCH="$(git -C "$ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
SOURCE_DIRTY="false"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=all)" ]]; then
  SOURCE_DIRTY="true"
fi
if [[ "$CHANNEL" == "release" \
  && "$SOURCE_DIRTY" == "true" \
  && ! ( "$ACTION" == "install-release" \
    && "${RAG_IME_ALLOW_DIRTY_INSTALL:-0}" == "1" ) ]]; then
  echo "refusing formal Electron release build from dirty source" >&2
  exit 1
fi

if [[ "$ACTION" == "install-release" ]]; then
  if [[ "$SOURCE_BRANCH" != "main" ]]; then
    echo "refusing formal app installation from non-main source: ${SOURCE_BRANCH:-detached HEAD}" >&2
    exit 1
  fi
  if [[ "$SOURCE_DIRTY" == "true" ]]; then
    if [[ "${RAG_IME_ALLOW_DIRTY_INSTALL:-0}" != "1" ]]; then
      echo "refusing formal app installation from dirty main source" >&2
      exit 1
    fi
    echo "Development install: allowing explicitly requested dirty main source." >&2
  fi
  curl --silent --show-error --fail --max-time 5 \
    -H 'Origin: http://127.0.0.1:8766' \
    -H 'Content-Type: application/json' \
    --data '{}' \
    http://127.0.0.1:8766/api/browser/managed/stop >/dev/null 2>&1 || true
fi

RAG_IME_CONTROL_TRANSPORT=http \
RAG_IME_CONTROL_BUILD_CHANNEL="$FRONTEND_CHANNEL" \
  "$ROOT/scripts/build_control_center_web.sh" >/dev/null
DIST_TREE_DIGEST="$(python3 - "$ROOT" "$WEB/dist" <<'PY'
import sys
from pathlib import Path

root, dist = sys.argv[1:]
sys.path.insert(0, root)
from rag_ime.release_staging import content_tree_digest

print(content_tree_digest(Path(dist), excluded_paths=("rag-ime-control-web-build.json",)))
PY
)"
"$ROOT/scripts/check_control_center_web_dist.sh" \
  "$WEB/dist" http "$FRONTEND_CHANNEL" "$SOURCE_COMMIT" "$DIST_TREE_DIGEST" >/dev/null

rm -rf "$APP"
ditto "$ELECTRON_APP" "$APP"
CONTENTS="$APP/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
rm -f "$RESOURCES/default_app.asar"
/usr/libexec/PlistBuddy -c 'Delete :ElectronAsarIntegrity' "$CONTENTS/Info.plist" 2>/dev/null || true
mv "$MACOS/Electron" "$MACOS/$EXECUTABLE"
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable $EXECUTABLE" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $DISPLAY_NAME" "$CONTENTS/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $DISPLAY_NAME" "$CONTENTS/Info.plist"

mkdir -p "$RESOURCES/app/electron" "$RESOURCES/app/dist"
ditto "$WEB/electron" "$RESOURCES/app/electron"
ditto "$WEB/dist" "$RESOURCES/app/dist"
python3 - "$RESOURCES/app/package.json" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(json.dumps({
    "name": "personal-agent-workbench",
    "private": True,
    "type": "module",
    "main": "electron/main.mjs",
}, indent=2) + "\n", encoding="utf-8")
PY

python3 - "$RESOURCES/rag-ime-control-web-build-marker.json" "$BUNDLE_ID" "$CHANNEL" "$FRONTEND_CHANNEL" "$SOURCE_COMMIT" "$SOURCE_DIRTY" "$DIST_TREE_DIGEST" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target, bundle_id, channel, frontend_channel, commit, dirty, dist_digest = sys.argv[1:]
provenance = {
    "sourceCommit": commit,
    "sourceDirty": dirty == "true",
    "frontendProduct": "paw-os",
    "bundleId": bundle_id,
    "frontendTransport": "http",
    "browserHost": "electron-webview",
    "browserControl": "ego-browser",
    "browserTransport": "cdp",
    "browserPartition": "persist:paw-browser",
    "sameOriginControlProxy": True,
    "distTreeDigest": dist_digest,
}
Path(target).write_text(json.dumps({
    "schemaVersion": "rag-ime.control-build-marker.v1",
    "bundleId": bundle_id,
    "gitCommit": commit,
    "gitDirty": dirty == "true",
    "sourceCommit": commit,
    "sourceDirty": dirty == "true",
    "builtAt": datetime.now(timezone.utc).isoformat(),
    "ui": "control-center-web",
    "channel": channel,
    "frontendTransport": "http",
    "frontendBuildChannel": frontend_channel,
    "forbiddenTransportModulesExcluded": True,
    "browserHost": "electron-webview",
    "browserControl": "ego-browser",
    "browserTransport": "cdp",
    "browserPartition": "persist:paw-browser",
    "sameOriginControlProxy": True,
    "frontendProduct": "paw-os",
    "distTreeDigest": dist_digest,
    "provenance": provenance,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

[[ ! -d "$RESOURCES/app/node_modules" ]] || {
  echo "node_modules must not enter the PAWOS app resources" >&2
  exit 1
}
[[ -f "$RESOURCES/app/dist/index.html" \
  && -f "$RESOURCES/app/electron/main.mjs" \
  && -f "$RESOURCES/app/electron/preload.cjs" ]] || {
  echo "PAWOS Electron host resources are incomplete" >&2
  exit 1
}
codesign --force --deep --sign - "$APP" >/dev/null
codesign --verify --deep --strict "$APP"

verify_release_provenance() {
  local candidate="$1"
  RAG_IME_CONTROL_APP="$candidate" \
  RAG_IME_CONTROL_EXPECTED_COMMIT="$SOURCE_COMMIT" \
  RAG_IME_CONTROL_SKIP_LIVE=1 \
    "$ROOT/scripts/check_control_center_footprint.sh" >/dev/null
}

if [[ "$CHANNEL" == "release" ]]; then
  verify_release_provenance "$APP"
fi

if [[ "$ACTION" == install-* ]]; then
  LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
  INSTALLED_EXECUTABLE="$INSTALL_DEST/Contents/MacOS/$EXECUTABLE"
  INSTALLED_PID="$(pgrep -f "^${INSTALLED_EXECUTABLE}$" | head -n 1 || true)"
  [[ -z "$INSTALLED_PID" ]] || kill -TERM "$INSTALLED_PID" 2>/dev/null || true
  for _ in {1..25}; do
    [[ -z "$INSTALLED_PID" ]] || ! kill -0 "$INSTALLED_PID" 2>/dev/null || {
      sleep 0.2
      continue
    }
    break
  done
  [[ -z "$INSTALLED_PID" ]] || ! kill -0 "$INSTALLED_PID" 2>/dev/null || kill -KILL "$INSTALLED_PID" 2>/dev/null || true
  mkdir -p "$HOME/Applications"
  rm -rf "$INSTALL_DEST"
  ditto "$APP" "$INSTALL_DEST"
  codesign --verify --deep --strict "$INSTALL_DEST"
  if [[ "$CHANNEL" == "release" ]]; then
    verify_release_provenance "$INSTALL_DEST"
  fi
  "$LSREGISTER" -f "$INSTALL_DEST" >/dev/null
  echo "$INSTALL_DEST"
else
  echo "$APP"
fi
