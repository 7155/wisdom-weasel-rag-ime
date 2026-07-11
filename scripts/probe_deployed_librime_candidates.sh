#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
INPUT_METHOD_APP="${RAG_IME_SQUIRREL_INSTALLED_APP:-$HOME/Library/Input Methods/Squirrel.app}"
HEADER_DIR="${RAG_IME_LIBRIME_HEADER_DIR:-$SQUIRREL_WORKDIR/librime/dist/include}"
LIBRARY_DIR="${RAG_IME_LIBRIME_LIBRARY_DIR:-$INPUT_METHOD_APP/Contents/Frameworks}"
SHARED_DATA_DIR="${RAG_IME_RIME_SHARED_DATA_DIR:-$INPUT_METHOD_APP/Contents/SharedSupport}"
USER_DATA_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
EXPECT_FIRST="${RAG_IME_RIME_EXPECT_FIRST_CANDIDATE-用}"
CLANG="${RAG_IME_CLANG:-$(command -v clang || true)}"
INPUTS=("$@")

if [[ ${#INPUTS[@]} -eq 0 ]]; then
  INPUTS=(yon yong)
fi

if [[ -z "$CLANG" ]]; then
  echo "clang is required for the deployed librime probe" >&2
  exit 1
fi
if [[ ! -f "$HEADER_DIR/rime_api.h" ]]; then
  echo "librime headers not found: $HEADER_DIR" >&2
  echo "Run scripts/prepare_squirrel_workspace.sh first or set RAG_IME_LIBRIME_HEADER_DIR." >&2
  exit 1
fi
if [[ ! -f "$LIBRARY_DIR/librime.1.dylib" ]]; then
  echo "installed librime not found: $LIBRARY_DIR/librime.1.dylib" >&2
  exit 1
fi
if [[ ! -d "$SHARED_DATA_DIR" || ! -d "$USER_DATA_DIR" ]]; then
  echo "deployed Rime data directories are missing" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/rag-ime-librime-probe.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT
PROBE="$TMP_DIR/rime_candidate_probe"

"$CLANG" \
  -std=c11 \
  -Wall \
  -Wextra \
  -Werror \
  "$ROOT/scripts/support/rime_candidate_probe.c" \
  -I"$HEADER_DIR" \
  -L"$LIBRARY_DIR" \
  -lrime.1 \
  -o "$PROBE"

OUTPUT="$(
  DYLD_LIBRARY_PATH="$LIBRARY_DIR${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}" \
    "$PROBE" "$SHARED_DATA_DIR" "$USER_DATA_DIR" "${INPUTS[@]}"
)"
printf '%s\n' "$OUTPUT"

if [[ -n "$EXPECT_FIRST" ]]; then
  while IFS=$'\t' read -r input first _; do
    if [[ "$first" != "$EXPECT_FIRST" ]]; then
      echo "unexpected first candidate for $input: ${first:-<empty>} (expected $EXPECT_FIRST)" >&2
      exit 1
    fi
  done <<< "$OUTPUT"
fi

printf '[OK] deployed librime candidate probe passed for %s input(s)\n' "${#INPUTS[@]}"
