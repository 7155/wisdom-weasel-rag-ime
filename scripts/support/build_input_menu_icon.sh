#!/usr/bin/env bash
set -euo pipefail

OUTPUT="${1:?usage: build_input_menu_icon.sh OUTPUT.png}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${RAG_IME_INPUT_MENU_ICON_SOURCE:-$ROOT/macos/Shared/Assets/CompanionStates/RagImeCompanionIdle.png}"
SIZE="${RAG_IME_INPUT_MENU_ICON_SIZE:-18}"

if [[ ! -f "$SOURCE" ]]; then
  echo "input menu icon source not found: $SOURCE" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"

# InputMethodKit uses the image's intrinsic point size when laying out the
# input-source menu. A 512 px application asset therefore creates a 512 pt
# menu row. Keep a dedicated, menu-sized raster instead of reusing app art.
sips -s format png -z "$SIZE" "$SIZE" "$SOURCE" --out "$OUTPUT" >/dev/null
