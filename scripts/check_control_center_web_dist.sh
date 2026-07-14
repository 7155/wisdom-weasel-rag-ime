#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${1:-$ROOT/control-center-web/dist}"
EXPECTED_TRANSPORT="${2:-native}"
EXPECTED_CHANNEL="${3:-production}"
MARKER="$DIST/rag-ime-control-web-build.json"

[[ -f "$DIST/index.html" ]] || {
  echo "missing control-center-web dist index: $DIST/index.html" >&2
  exit 1
}
[[ -f "$DIST/manifest.webmanifest" ]] || {
  echo "missing control-center-web manifest: $DIST/manifest.webmanifest" >&2
  exit 1
}
[[ -d "$DIST/assets" ]] || {
  echo "missing control-center-web assets: $DIST/assets" >&2
  exit 1
}
[[ -f "$MARKER" ]] || {
  echo "missing control-center-web build boundary marker: $MARKER" >&2
  exit 1
}

python3 - "$MARKER" "$EXPECTED_TRANSPORT" "$EXPECTED_CHANNEL" <<'PY'
import json
import sys

marker_path, expected_transport, expected_channel = sys.argv[1:]
with open(marker_path, encoding="utf-8") as handle:
    marker = json.load(handle)

if marker.get("schemaVersion") != "rag-ime.control-web-build.v1":
    raise SystemExit("control-center web build marker has the wrong schema")
if marker.get("transport") != expected_transport:
    raise SystemExit(
        f"control-center transport is {marker.get('transport')!r}, expected {expected_transport!r}"
    )
if marker.get("buildChannel") != expected_channel:
    raise SystemExit(
        f"control-center channel is {marker.get('buildChannel')!r}, expected {expected_channel!r}"
    )
if expected_transport == "native":
    if marker.get("nativeOnly") is not True:
        raise SystemExit("native control-center build is not marked native-only")
    if marker.get("forbiddenTransportModulesExcluded") is not True:
        raise SystemExit("native control-center build did not exclude mock/http modules")
PY

if [[ "$EXPECTED_TRANSPORT" == "native" ]]; then
  if grep -R -E -q \
    --include='*.html' --include='*.js' \
    'ControlTransportHttpError|No mock response registered for|mock-subscription-|http://127\.0\.0\.1:8766' \
    "$DIST"; then
    echo "native control-center dist contains a mock/http transport sentinel" >&2
    exit 1
  fi
  grep -q "connect-src 'self';" "$DIST/index.html" || {
    echo "native control-center CSP still permits a browser transport" >&2
    exit 1
  }
fi

echo "control center web dist boundary: PASS ($EXPECTED_CHANNEL/$EXPECTED_TRANSPORT)"
