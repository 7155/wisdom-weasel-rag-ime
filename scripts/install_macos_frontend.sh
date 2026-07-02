#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${RAG_IME_MACOS_APP:-$ROOT/build/RagImeMac.app}"
TARGET_DIR="${RAG_IME_MACOS_TARGET_DIR:-$HOME/Library/Input Methods}"
TARGET_APP="$TARGET_DIR/RagImeMac.app"
CONFIG_DIR="${RAG_IME_MACOS_CONFIG_DIR:-$HOME/Library/Application Support/RagImeMac}"
USER_CONFIG="$CONFIG_DIR/bridge-config.json"
INPUT_SOURCE_ID="${RAG_IME_MACOS_INPUT_SOURCE_ID:-dev.local.inputmethod.RagImeMac.Hans}"
BUNDLE_ID="${RAG_IME_MACOS_BUNDLE_ID:-dev.local.inputmethod.RagImeMac}"
DRY_RUN="${RAG_IME_MACOS_INSTALL_DRY_RUN:-0}"
CHECK_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_CHECK:-1}"
REQUIRE_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_REQUIRE_INPUT_SOURCE:-0}"
SELECT_INPUT_SOURCE="${RAG_IME_MACOS_INSTALL_SELECT:-0}"
CLEAN_INSTALL="${RAG_IME_MACOS_INSTALL_CLEAN:-0}"
WAIT_SECONDS="${RAG_IME_MACOS_INSTALL_WAIT_SECONDS:-5}"
ALLOW_NATIVE_HARNESS_INSTALL="${RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL:-0}"
TMP_BASE="${TMPDIR:-/tmp}"
tmpdir="$(mktemp -d "$TMP_BASE/rag-ime-install-macos.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT
INPUT_SOURCE_STATUS_FILE="$tmpdir/input-source-status.txt"

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

if ! bool_true "$ALLOW_NATIVE_HARNESS_INSTALL"; then
  cat >&2 <<'EOF'
[STOP] RagImeMac is a debug harness, not the product input-method route.

The usable product route is the Rime/Squirrel candidate-layer integration:
Wanxiang/Rime owns pinyin composition; the Prediction-first sidecar injects
LLM/RAG/memory candidates into that structured candidate flow.

This native InputMethodKit app can still be installed for low-level bridge and
panel debugging, but it is not expected to appear reliably in macOS Input
Sources on every machine. To run this harness-only install anyway, set:

  RAG_IME_ALLOW_NATIVE_HARNESS_INSTALL=1 scripts/install_macos_frontend.sh
EOF
  exit 2
fi

wait_for_input_source() {
  local deadline now output status
  deadline=$((SECONDS + WAIT_SECONDS))
  while true; do
    set +e
    output="$(RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/check_macos_input_source.sh" "$INPUT_SOURCE_ID" 2>&1)"
    status=$?
    set -e
    if [[ "$output" != missing\ * ]]; then
      printf '%s\n' "$output"
      return 0
    fi
    now=$SECONDS
    if (( now >= deadline )); then
      printf '%s\n' "$output"
      return "$status"
    fi
    sleep 0.25
  done
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
  LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  if [[ -x "$LSREGISTER" ]]; then
    "$LSREGISTER" -f -R "$TARGET_APP" >/dev/null 2>&1 || true
  fi
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
  elif ! wait_for_input_source >"$INPUT_SOURCE_STATUS_FILE"; then
    cat "$INPUT_SOURCE_STATUS_FILE"
    echo "[WARN] input source is not visible to macOS yet: $INPUT_SOURCE_ID" >&2
    echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME." >&2
    if bool_true "$REQUIRE_INPUT_SOURCE"; then
      exit 2
    fi
  elif RAG_IME_INPUT_SOURCE_BUNDLE_ID="$BUNDLE_ID" "$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID"; then
    echo "[OK] selected input source: $INPUT_SOURCE_ID"
  else
    cat "$INPUT_SOURCE_STATUS_FILE"
    echo "[WARN] cannot select input source yet: $INPUT_SOURCE_ID" >&2
    echo "If thirdPartyEnabled=false above, macOS has not added RAG IME to the third-party input-source allow-list." >&2
    echo "Open System Settings -> Keyboard -> Input Sources, remove any stale RAG IME entry, then add RAG IME again." >&2
    if bool_true "$REQUIRE_INPUT_SOURCE"; then
      exit 2
    fi
  fi
elif bool_true "$CHECK_INPUT_SOURCE"; then
  if bool_true "$DRY_RUN"; then
    echo "dry-run: would check input source $INPUT_SOURCE_ID"
  elif wait_for_input_source >"$INPUT_SOURCE_STATUS_FILE"; then
    cat "$INPUT_SOURCE_STATUS_FILE"
    echo "[OK] input source is registered: $INPUT_SOURCE_ID"
  else
    cat "$INPUT_SOURCE_STATUS_FILE"
    echo "[WARN] input source is not registered yet: $INPUT_SOURCE_ID" >&2
    echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME." >&2
    if bool_true "$REQUIRE_INPUT_SOURCE"; then
      exit 2
    fi
  fi
else
  echo "Open System Settings -> Keyboard -> Input Sources, then add RAG IME."
fi
