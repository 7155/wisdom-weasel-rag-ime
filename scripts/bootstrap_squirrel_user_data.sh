#!/usr/bin/env bash
set -euo pipefail

SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-/Library/Input Methods/Squirrel.app}"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
BACKUP_ENABLED="${RAG_IME_SQUIRREL_BOOTSTRAP_BACKUP:-1}"
EXPECTED_BUILD_FILES=(
  "build/default.yaml"
  "build/luna_pinyin.schema.yaml"
  "build/luna_pinyin.table.bin"
)

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" ]]
}

copy_missing_tree() {
  local src="$1"
  local dst="$2"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --ignore-existing "$src/" "$dst/"
  else
    # macOS ships rsync, but keep a conservative fallback for small test fixtures.
    (cd "$src" && find . -mindepth 1 -maxdepth 1 -exec cp -R -n {} "$dst/" \;)
  fi
}

fail_build_output() {
  local log="$1"
  local fatal_log
  fatal_log="$(grep -Ev "User notification authorization error: Notifications are not allowed for this application" "$log" || true)"
  if printf '%s\n' "$fatal_log" | grep -E "missing input schema|failed to save config|failed to save.*config|error:" >/dev/null 2>&1; then
    echo "Squirrel user data build reported errors:" >&2
    printf '%s\n' "$fatal_log" >&2
    exit 1
  fi
}

SHARED_SUPPORT="$SQUIRREL_APP/Contents/SharedSupport"
SQUIRREL_EXECUTABLE="$SQUIRREL_APP/Contents/MacOS/Squirrel"
PLUM_OUTPUT="$SQUIRREL_WORKDIR/plum/output"

if [[ ! -x "$SQUIRREL_EXECUTABLE" ]]; then
  echo "Squirrel executable not found: $SQUIRREL_EXECUTABLE" >&2
  exit 1
fi

if [[ ! -d "$SHARED_SUPPORT" ]]; then
  echo "Squirrel SharedSupport data not found: $SHARED_SUPPORT" >&2
  exit 1
fi

backup_path=""
if [[ -d "$RIME_USER_DIR" ]] && bool_true "$BACKUP_ENABLED"; then
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_path="$RIME_USER_DIR.rag-ime-before-bootstrap-$timestamp"
  cp -R "$RIME_USER_DIR" "$backup_path"
fi

mkdir -p "$RIME_USER_DIR"
copy_missing_tree "$SHARED_SUPPORT" "$RIME_USER_DIR"

if [[ -d "$PLUM_OUTPUT" ]]; then
  copy_missing_tree "$PLUM_OUTPUT" "$RIME_USER_DIR"
fi

build_log="$(mktemp "${TMPDIR:-/tmp}/rag-ime-squirrel-build.XXXXXX.log")"
reload_log="$(mktemp "${TMPDIR:-/tmp}/rag-ime-squirrel-reload.XXXXXX.log")"
trap 'rm -f "$build_log" "$reload_log"' EXIT

if ! (cd "$RIME_USER_DIR" && "$SQUIRREL_EXECUTABLE" --build >"$build_log" 2>&1); then
  echo "Squirrel user data build failed:" >&2
  cat "$build_log" >&2
  exit 1
fi
fail_build_output "$build_log"

if ! (cd "$RIME_USER_DIR" && "$SQUIRREL_EXECUTABLE" --reload >"$reload_log" 2>&1); then
  echo "Squirrel user data reload failed:" >&2
  cat "$reload_log" >&2
  exit 1
fi
fail_build_output "$reload_log"

for path in "${EXPECTED_BUILD_FILES[@]}"; do
  if [[ ! -f "$RIME_USER_DIR/$path" ]]; then
    echo "Squirrel user data build did not create expected file: $RIME_USER_DIR/$path" >&2
    exit 1
  fi
done

printf '[OK] bootstrapped Squirrel user Rime data: %s\n' "$RIME_USER_DIR"
if [[ -n "$backup_path" ]]; then
  printf '[OK] backed up previous Rime data: %s\n' "$backup_path"
fi
