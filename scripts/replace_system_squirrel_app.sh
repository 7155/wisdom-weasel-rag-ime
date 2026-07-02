#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_APP="${RAG_IME_SQUIRREL_SOURCE_APP:-$HOME/Library/Input Methods/Squirrel.app}"
TARGET_APP="${RAG_IME_SQUIRREL_SYSTEM_APP:-/Library/Input Methods/Squirrel.app}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
BACKUP_SUFFIX="${RAG_IME_SQUIRREL_BACKUP_SUFFIX:-rag-ime-backup-$(date +%Y%m%d-%H%M%S)}"
SELECT_INPUT_SOURCE_SCRIPT="${RAG_IME_SELECT_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/select_macos_input_source.sh}"
CHECK_INPUT_SOURCE_SCRIPT="${RAG_IME_CHECK_INPUT_SOURCE_SCRIPT:-$ROOT/scripts/check_macos_input_source.sh}"
DOCTOR_SCRIPT="${RAG_IME_DOCTOR_SCRIPT:-$ROOT/scripts/doctor_squirrel_integration.sh}"
RUN_DOCTOR="${RAG_IME_SQUIRREL_REPLACE_RUN_DOCTOR:-1}"
PREFLIGHT=0

usage() {
  cat <<'USAGE'
Usage: scripts/replace_system_squirrel_app.sh [--preflight]

Replaces the system Squirrel.app with the patched user-local Squirrel.app.

Options:
  --preflight  Print the current source/target patch status and next command
               without modifying /Library or invoking sudo.
  -h, --help   Show this help.
USAGE
}

has_current_rag_ime_frontend_patch() {
  local app="$1"
  local executable="$app/Contents/MacOS/Squirrel"
  [[ -x "$executable" ]] || return 1
  strings "$executable" 2>/dev/null | grep -Fq "rag-ime.squirrel-frontend-trace.v1" &&
    strings "$executable" 2>/dev/null | grep -Fq "rag-ime.foreground-trace.v2" &&
    strings "$executable" 2>/dev/null | grep -Fq "panel_text_layout" &&
    strings "$executable" 2>/dev/null | grep -Fq "sidecar_request_scheduled" &&
    strings "$executable" 2>/dev/null | grep -Fq "sidecar_empty_response_ignored"
}

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

canonical_path() {
  local path="$1"
  local dir
  dir="$(dirname "$path")"
  if [[ -d "$dir" ]]; then
    (cd "$dir" && printf '%s/%s\n' "$(pwd -P)" "$(basename "$path")")
  else
    printf '%s/%s\n' "$dir" "$(basename "$path")"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preflight|--dry-run)
      PREFLIGHT=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "patched source Squirrel.app not found: $SOURCE_APP" >&2
  echo "Build/install the patched user app first: scripts/build_patched_squirrel.sh install" >&2
  exit 1
fi

if [[ "$(canonical_path "$SOURCE_APP")" == "$(canonical_path "$TARGET_APP")" ]]; then
  echo "source and target Squirrel.app are the same path; nothing to replace: $SOURCE_APP" >&2
  exit 1
fi

if ! has_current_rag_ime_frontend_patch "$SOURCE_APP"; then
  echo "source Squirrel.app does not contain the current RAG-IME frontend patch: $SOURCE_APP" >&2
  exit 1
fi

if [[ "$PREFLIGHT" == "1" ]]; then
  target_exists=false
  target_patch=false
  replacement_required=true
  sudo_cached=false
  if [[ -d "$TARGET_APP" ]]; then
    target_exists=true
    if has_current_rag_ime_frontend_patch "$TARGET_APP"; then
      target_patch=true
      replacement_required=false
    fi
  fi
  if sudo -n true >/dev/null 2>&1; then
    sudo_cached=true
  fi

  echo "mode=preflight"
  echo "source_app=$SOURCE_APP"
  echo "source_patch=true"
  echo "target_app=$TARGET_APP"
  echo "target_exists=$target_exists"
  echo "target_patch=$target_patch"
  echo "replacement_required=$replacement_required"
  echo "input_source_id=$INPUT_SOURCE_ID"
  if input_source_status="$("$CHECK_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID" 2>&1)"; then
    echo "input_source_check_ok=true"
  else
    echo "input_source_check_ok=false"
  fi
  echo "input_source_status:"
  printf '%s\n' "$input_source_status" | sed 's/^/  /'
  echo "sudo_cached=$sudo_cached"
  if [[ "$replacement_required" == "true" ]]; then
    echo "next_command=scripts/replace_system_squirrel_app.sh"
  else
    echo "next_command=<none>"
  fi
  exit 0
fi

echo "source_app=$SOURCE_APP"
echo "target_app=$TARGET_APP"

if [[ -d "$TARGET_APP" ]]; then
  BACKUP_APP="$TARGET_APP.$BACKUP_SUFFIX"
  echo "backing up existing system Squirrel.app to: $BACKUP_APP"
  sudo mv "$TARGET_APP" "$BACKUP_APP"
fi

echo "installing patched Squirrel.app into system Input Methods"
sudo mkdir -p "$(dirname "$TARGET_APP")"
sudo ditto "$SOURCE_APP" "$TARGET_APP"
sudo chown -R root:wheel "$TARGET_APP"

if command -v codesign >/dev/null 2>&1; then
  sudo codesign --force --deep --sign - "$TARGET_APP"
fi

if ! has_current_rag_ime_frontend_patch "$TARGET_APP"; then
  echo "target Squirrel.app does not contain the current RAG-IME frontend patch after copy: $TARGET_APP" >&2
  exit 1
fi

pkill -x Squirrel >/dev/null 2>&1 || true

"$TARGET_APP/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
"$TARGET_APP/Contents/MacOS/Squirrel" --enable-input-source "$INPUT_SOURCE_ID" >/dev/null 2>&1 ||
  "$TARGET_APP/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 ||
  true

"$SELECT_INPUT_SOURCE_SCRIPT" "$INPUT_SOURCE_ID"
RAG_IME_SQUIRREL_APP="$TARGET_APP" "$CHECK_INPUT_SOURCE_SCRIPT" --require-selected "$INPUT_SOURCE_ID"

if bool_true "$RUN_DOCTOR"; then
  RAG_IME_SQUIRREL_APP="$TARGET_APP" \
    RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES="$SOURCE_APP:$TARGET_APP" \
    RAG_IME_DOCTOR_REQUIRE_TRYOUT=1 \
    RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE=0 \
    "$DOCTOR_SCRIPT"
fi

echo "installed patched system Squirrel.app"
