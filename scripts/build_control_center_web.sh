#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"
CONTROL_TRANSPORT="${RAG_IME_CONTROL_TRANSPORT:-mock}"
BUILD_CHANNEL="${RAG_IME_CONTROL_BUILD_CHANNEL:-preview}"

[[ "$CONTROL_TRANSPORT" == "mock" || "$CONTROL_TRANSPORT" == "http" || "$CONTROL_TRANSPORT" == "native" ]] || {
  echo "RAG_IME_CONTROL_TRANSPORT must be mock, http, or native" >&2
  exit 2
}
[[ "$BUILD_CHANNEL" == "preview" || "$BUILD_CHANNEL" == "production" ]] || {
  echo "RAG_IME_CONTROL_BUILD_CHANNEL must be preview or production" >&2
  exit 2
}
if [[ "$BUILD_CHANNEL" == "production" && "$CONTROL_TRANSPORT" != "native" ]]; then
  echo "production control-center builds require native transport" >&2
  exit 2
fi

if [[ "${RAG_IME_SKIP_WEB_INSTALL:-0}" != "1" ]]; then
  CI=true pnpm --dir "$WEB" install --frozen-lockfile
fi

node "$ROOT/scripts/generate_control_center_contracts.mjs" --check
pnpm --dir "$WEB" typecheck
pnpm --dir "$WEB" test
VITE_CONTROL_TRANSPORT="$CONTROL_TRANSPORT" \
VITE_BUILD_CHANNEL="$BUILD_CHANNEL" \
  pnpm --dir "$WEB" build

[[ -f "$WEB/dist/index.html" ]] || {
  echo "missing control-center-web/dist/index.html" >&2
  exit 1
}
[[ -f "$WEB/dist/manifest.webmanifest" ]] || {
  echo "missing control-center-web/dist/manifest.webmanifest" >&2
  exit 1
}
if grep -R -E -q 'unsafe-eval|new Function|require\("|eval\(' "$WEB/dist"; then
  echo "control-center bundle contains runtime code generation or unresolved CommonJS" >&2
  exit 1
fi
"$ROOT/scripts/check_control_center_web_dist.sh" \
  "$WEB/dist" "$CONTROL_TRANSPORT" "$BUILD_CHANNEL" >/dev/null

echo "$WEB/dist"
