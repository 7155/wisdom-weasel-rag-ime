#!/usr/bin/env bash
set -euo pipefail

OUTPUT="${1:?usage: build_app_icon.sh OUTPUT.icns}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${RAG_IME_ICON_SOURCE:-$ROOT/assets/brand/rag-ime-icon.png}"
TMP_BASE="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "$TMP_BASE/rag-ime-app-icon.XXXXXX")"
if [[ "${RAG_IME_KEEP_ICON_WORK:-0}" == "1" ]]; then
  echo "icon workdir: $WORK" >&2
else
  trap 'rm -rf "$WORK"' EXIT
fi

ICONSET="$WORK/RagImeIcon.iconset"
MASTER="$WORK/RagImeIcon-1024.png"
mkdir -p "$ICONSET" "$(dirname "$OUTPUT")"

case "${SOURCE##*.}" in
  png|PNG)
    sips -s format png -z 1024 1024 "$SOURCE" --out "$MASTER" >/dev/null
    ;;
  svg|SVG)
    if ! command -v rsvg-convert >/dev/null 2>&1; then
      echo "rsvg-convert is required to build an SVG RAG-IME icon" >&2
      exit 1
    fi
    rsvg-convert --width 1024 --height 1024 --keep-aspect-ratio "$SOURCE" --output "$MASTER"
    ;;
  *)
    echo "unsupported RAG-IME icon source: $SOURCE" >&2
    exit 1
    ;;
esac

for size in 16 32 128 256 512; do
  sips -s format png -z "$size" "$size" "$MASTER" \
    --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  retina=$((size * 2))
  sips -s format png -z "$retina" "$retina" "$MASTER" \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done

# The macOS 27 beta currently rejects otherwise valid legacy iconsets. Use the
# standard multi-resolution TIFF fallback there while preserving iconutil on
# released systems.
if ! iconutil -c icns "$ICONSET" -o "$OUTPUT" 2>/dev/null; then
  TIFFS="$WORK/tiffs"
  mkdir -p "$TIFFS"
  unique=(
    icon_16x16.png
    icon_32x32.png
    icon_32x32@2x.png
    icon_128x128.png
    icon_128x128@2x.png
    icon_256x256@2x.png
    icon_512x512@2x.png
  )
  for name in "${unique[@]}"; do
    sips -s format tiff "$ICONSET/$name" --out "$TIFFS/${name%.png}.tiff" >/dev/null
  done
  tiffutil -cat "$TIFFS"/*.tiff -out "$WORK/RagImeIcon.tiff" >/dev/null 2>&1
  # tiff2icns on current macOS mis-parses output paths containing spaces.
  # Create inside the temporary directory, then copy to the app bundle.
  tiff2icns "$WORK/RagImeIcon.tiff" "$WORK/RagImeIcon.icns"
  cp "$WORK/RagImeIcon.icns" "$OUTPUT"
fi
