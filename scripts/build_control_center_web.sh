#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"

if [[ "${RAG_IME_SKIP_WEB_INSTALL:-0}" != "1" ]]; then
  CI=true pnpm --dir "$WEB" install --frozen-lockfile
fi

node "$ROOT/scripts/generate_control_center_contracts.mjs" --check
pnpm --dir "$WEB" typecheck
pnpm --dir "$WEB" test
pnpm --dir "$WEB" build

[[ -f "$WEB/dist/index.html" ]] || {
  echo "missing control-center-web/dist/index.html" >&2
  exit 1
}
[[ -f "$WEB/dist/manifest.webmanifest" ]] || {
  echo "missing control-center-web/dist/manifest.webmanifest" >&2
  exit 1
}

echo "$WEB/dist"
