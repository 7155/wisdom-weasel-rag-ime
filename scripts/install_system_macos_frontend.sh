#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${RAG_IME_MACOS_APP:-$ROOT/build/RagImeMac.app}"
SYSTEM_DIR="${RAG_IME_MACOS_SYSTEM_DIR:-/Library/Input Methods}"
SYSTEM_APP="$SYSTEM_DIR/RagImeMac.app"
USER_INPUT_METHODS_DIR="${RAG_IME_MACOS_USER_INPUT_METHODS_DIR:-$HOME/Library/Input Methods}"
USER_APP="$USER_INPUT_METHODS_DIR/RagImeMac.app"
USER_CONFIG_DIR="${RAG_IME_MACOS_CONFIG_DIR:-$HOME/Library/Application Support/RagImeMac}"
USER_CONFIG="$USER_CONFIG_DIR/bridge-config.json"
INPUT_SOURCE_ID="${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}"
BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
SELECT_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_SELECT:-1}"
PRUNE_USER_DUPLICATE="${RAG_IME_MACOS_PRUNE_USER_DUPLICATE:-1}"
ALLOW_NATIVE_HARNESS_INSTALL="${RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL:-0}"

bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if ! bool_true "$ALLOW_NATIVE_HARNESS_INSTALL"; then
  cat >&2 <<'EOF'
[STOP] RagImeMac is a debug harness, not the product input-method route.

Do not install this native harness into /Library/Input Methods as the main
Prediction-first RAG IME. The product route is the Rime/Squirrel
candidate-layer integration with Wanxiang/Rime as the pinyin anchor.

For one-off system-level harness debugging only, set:

  RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL=1 scripts/install_system_macos_frontend.sh
EOF
  exit 2
fi

if [[ ! -d "$APP_DIR" ]]; then
  "$ROOT/scripts/build_macos_frontend.sh" >/dev/null
fi

mkdir -p "$USER_CONFIG_DIR"
cp "$APP_DIR/Contents/Resources/bridge-config.json" "$USER_CONFIG"

if bool_true "$PRUNE_USER_DUPLICATE" && [[ -d "$USER_APP" ]]; then
  user_backup="$USER_APP.rag-ime-backup-$(date +%Y%m%d-%H%M%S)"
  mv "$USER_APP" "$user_backup"
  echo "backed up user duplicate app: $user_backup"
fi

quoted_app="$(printf '%q' "$APP_DIR")"
quoted_target="$(printf '%q' "$SYSTEM_APP")"
quoted_dir="$(printf '%q' "$SYSTEM_DIR")"
backup="$SYSTEM_APP.rag-ime-backup-$(date +%Y%m%d-%H%M%S)"
quoted_backup="$(printf '%q' "$backup")"
admin_script="
set -e
mkdir -p $quoted_dir
if [ -d $quoted_target ]; then
  mv $quoted_target $quoted_backup
fi
/usr/bin/ditto $quoted_app $quoted_target
/usr/sbin/chown -R root:wheel $quoted_target
/bin/chmod -R u+rwX,go+rX $quoted_target
/usr/bin/codesign --force --deep --sign - $quoted_target >/dev/null 2>&1 || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f -R $quoted_target >/dev/null 2>&1 || true
"

if [[ -w "$SYSTEM_DIR" ]]; then
  bash -c "$admin_script"
else
  osascript -e "do shell script $(python3 - <<'PY' "$admin_script"
import json
import sys
print(json.dumps(sys.argv[1]))
PY
) with administrator privileges"
fi

killall TextInputMenuAgent >/dev/null 2>&1 || true
killall SystemUIServer >/dev/null 2>&1 || true
killall cfprefsd >/dev/null 2>&1 || true
sleep 1
"$ROOT/scripts/refresh_macos_input_sources.sh" >/dev/null 2>&1 || true

echo "$SYSTEM_APP"
echo "$USER_CONFIG"
echo "input_source_id=$INPUT_SOURCE_ID"

if bool_true "$SELECT_INPUT_SOURCE"; then
  if RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID"; then
    echo "[OK] selected input source: $INPUT_SOURCE_ID"
  else
    RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/check_macos_input_source.sh" "$INPUT_SOURCE_ID" || true
    echo "[WARN] system app installed, but macOS did not switch to: $INPUT_SOURCE_ID" >&2
    echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME." >&2
  fi
fi
