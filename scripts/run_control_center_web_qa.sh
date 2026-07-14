#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/control-center-web"

cd "$ROOT"
python3 -m unittest \
  tests.test_native_control_bridge_contract \
  tests.test_control_center_web_host

pnpm --dir "$WEB" typecheck
pnpm --dir "$WEB" exec tsc -p e2e/tsconfig.json --pretty false
pnpm --dir "$WEB" test
pnpm --dir "$WEB" test:e2e
