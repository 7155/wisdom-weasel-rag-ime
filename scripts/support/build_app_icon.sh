#!/usr/bin/env bash
set -euo pipefail

OUTPUT="${1:?usage: build_app_icon.sh OUTPUT.icns}"
TMP_BASE="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "$TMP_BASE/rag-ime-app-icon.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

PPM="$WORK/RagImeIcon.ppm"
ICONSET="$WORK/RagImeIcon.iconset"

python3 - "$PPM" <<'PY'
import math
import sys

path = sys.argv[1]
size = 1024
with open(path, "wb") as handle:
    handle.write(f"P6\n{size} {size}\n255\n".encode("ascii"))
    for y in range(size):
        for x in range(size):
            dx = x - size / 2
            dy = y - size / 2
            radius = math.sqrt(dx * dx + dy * dy)
            if radius > size * 0.47:
                handle.write(bytes((0, 0, 0)))
                continue
            teal = int(118 + 88 * (1 - y / size))
            blue = int(150 + 86 * (x / size))
            in_mark = (
                (0.23 <= x / size <= 0.34 and 0.24 <= y / size <= 0.74)
                or (0.34 <= x / size <= 0.62 and 0.24 <= y / size <= 0.35)
                or (0.34 <= x / size <= 0.62 and 0.46 <= y / size <= 0.57)
                or (0.59 <= x / size <= 0.70 and 0.35 <= y / size <= 0.47)
                or (
                    0.50 <= x / size <= 0.72
                    and 0.57 <= y / size <= 0.74
                    and abs(((y / size) - 0.57) - ((x / size) - 0.50)) <= 0.08
                )
            )
            handle.write(bytes((245, 250, 252) if in_mark else (18, teal, blue)))
PY

mkdir -p "$ICONSET" "$(dirname "$OUTPUT")"
for size in 16 32 128 256 512; do
  sips -s format png -z "$size" "$size" "$PPM" \
    --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  retina=$((size * 2))
  sips -s format png -z "$retina" "$retina" "$PPM" \
    --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$OUTPUT"
