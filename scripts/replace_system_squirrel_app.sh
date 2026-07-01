#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_APP="${RAG_IME_SQUIRREL_SOURCE_APP:-$HOME/Library/Input Methods/Squirrel.app}"
TARGET_APP="${RAG_IME_SQUIRREL_SYSTEM_APP:-/Library/Input Methods/Squirrel.app}"
INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-im.rime.inputmethod.Squirrel.Hans}"
BACKUP_SUFFIX="${RAG_IME_SQUIRREL_BACKUP_SUFFIX:-rag-ime-backup-$(date +%Y%m%d-%H%M%S)}"

has_mixed_layout_patch() {
  local app="$1"
  local executable="$app/Contents/MacOS/Squirrel"
  [[ -x "$executable" ]] || return 1
  strings "$executable" 2>/dev/null | grep -Fq "rag-ime.squirrel-frontend-trace.v1" &&
    strings "$executable" 2>/dev/null | grep -Fq "panel_text_layout"
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

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "patched source Squirrel.app not found: $SOURCE_APP" >&2
  echo "Build/install the patched user app first: scripts/build_patched_squirrel.sh install" >&2
  exit 1
fi

if [[ "$(canonical_path "$SOURCE_APP")" == "$(canonical_path "$TARGET_APP")" ]]; then
  echo "source and target Squirrel.app are the same path; nothing to replace: $SOURCE_APP" >&2
  exit 1
fi

if ! has_mixed_layout_patch "$SOURCE_APP"; then
  echo "source Squirrel.app does not contain the RAG-IME mixed-layout patch: $SOURCE_APP" >&2
  exit 1
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

pkill -x Squirrel >/dev/null 2>&1 || true

"$TARGET_APP/Contents/MacOS/Squirrel" --register-input-source >/dev/null 2>&1 || true
"$TARGET_APP/Contents/MacOS/Squirrel" --enable-input-source "$INPUT_SOURCE_ID" >/dev/null 2>&1 ||
  "$TARGET_APP/Contents/MacOS/Squirrel" --enable-input-source >/dev/null 2>&1 ||
  true

"$ROOT/scripts/select_macos_input_source.sh" "$INPUT_SOURCE_ID"
RAG_IME_SQUIRREL_APP="$TARGET_APP" "$ROOT/scripts/check_macos_input_source.sh" --require-selected "$INPUT_SOURCE_ID"

echo "installed patched system Squirrel.app"
