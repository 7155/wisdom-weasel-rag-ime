#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/control-center-web"
PNPM="$ROOT/scripts/run_control_center_pnpm.sh"

cd "$ROOT"
python3 -m unittest \
  tests.test_native_control_bridge_contract \
  tests.test_control_center_web_host

"$PNPM" typecheck
"$PNPM" exec tsc -p e2e/tsconfig.json --pretty false
"$PNPM" test
"$PNPM" test:e2e
