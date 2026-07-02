#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${RAG_IME_MACOS_APP:-$ROOT/build/RagImeMac.app}"
TARGET_DIR="${RAG_IME_MACOS_TARGET_DIR:-$HOME/Library/Input Methods}"
TARGET_APP="$TARGET_DIR/RagImeMac.app"
CONFIG_DIR="${RAG_IME_MACOS_CONFIG_DIR:-$HOME/Library/Application Support/RagImeMac}"
USER_CONFIG="$CONFIG_DIR/bridge-config.json"
INPUT_SOURCE_ID="${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac}"
BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
DRY_RUN="${RAG_IME_MACOS_INSTALL_DRY_RUN:-0}"
CHECK_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_CHECK:-1}"
REQUIRE_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_REQUIRE_INPUT_SOURCE:-0}"
SELECT_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_SELECT:-0}"
CLEAN_INSTALL="${RAG_IME_MACOS_INSTALL_CLEAN:-0}"

while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --check)
      CHECK_INPUT_SOURCE=1
      shift
      ;;
    --no-check)
      CHECK_INPUT_SOURCE=0
      shift
      ;;
    --require-input-source)
      CHECK_INPUT_SOURCE=1
      REQUIRE_INPUT_SOURCE=1
      shift
      ;;
    --select)
      CHECK_INPUT_SOURCE=1
      SELECT_INPUT_SOURCE=1
      shift
      ;;
    --clean)
      CLEAN_INSTALL=1
      shift
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 64
      ;;
  esac
done

bool_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ! -d "$APP_DIR" ]]; then
  "$ROOT/scripts/build_macos_frontend.sh" >/dev/null
fi

if bool_true "$DRY_RUN"; then
  echo "dry-run: would install $APP_DIR -> $TARGET_APP"
else
  mkdir -p "$TARGET_DIR"
  if bool_true "$CLEAN_INSTALL"; then
    rm -rf "$TARGET_APP"
  fi
  /usr/bin/ditto "$APP_DIR" "$TARGET_APP"
fi

if bool_true "$DRY_RUN"; then
  echo "dry-run: would sync bridge config -> $USER_CONFIG"
else
  mkdir -p "$CONFIG_DIR"
  if [[ -f "$USER_CONFIG" ]]; then
    cp "$USER_CONFIG" "$USER_CONFIG.bak"
  fi
  cp "$TARGET_APP/Contents/Resources/bridge-config.json" "$USER_CONFIG"
fi

echo "$TARGET_APP"
echo "$USER_CONFIG"
echo "input_source_id=$INPUT_SOURCE_ID"

if bool_true "$SELECT_INPUT_SOURCE"; then
  if bool_true "$DRY_RUN"; then
    echo "dry-run: would select input source $INPUT_SOURCE_ID"
  elif RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID"; then
    echo "[OK] selected input source: $INPUT_SOURCE_ID"
  else
    echo "[WARN] cannot select input source yet: $INPUT_SOURCE_ID" >&2
    echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME." >&2
    if bool_true "$REQUIRE_INPUT_SOURCE"; then
      exit 2
    fi
  fi
elif bool_true "$CHECK_INPUT_SOURCE"; then
  if bool_true "$DRY_RUN"; then
    echo "dry-run: would check input source $INPUT_SOURCE_ID"
  elif RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/check_macos_input_source.sh" "$INPUT_SOURCE_ID"; then
    echo "[OK] input source is registered: $INPUT_SOURCE_ID"
  else
    echo "[WARN] input source is not registered yet: $INPUT_SOURCE_ID" >&2
    echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME." >&2
    if bool_true "$REQUIRE_INPUT_SOURCE"; then
      exit 2
    fi
  fi
else
  echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME."
fi
