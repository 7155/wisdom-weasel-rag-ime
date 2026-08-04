#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/control-center-web"
PACKAGE_JSON="$WEB/package.json"

PNPM_SPEC="$(python3 - "$PACKAGE_JSON" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(str(payload.get("packageManager") or "").strip())
PY
)"
if [[ ! "$PNPM_SPEC" =~ ^pnpm@[0-9]+\.[0-9]+\.[0-9]+([+-][A-Za-z0-9._-]+)?$ ]]; then
  echo "control-center-web/package.json must pin packageManager to pnpm@<version>" >&2
  exit 2
fi

cd "$WEB"

if command -v corepack >/dev/null 2>&1; then
  exec corepack "$PNPM_SPEC" "$@"
fi

PNPM_BIN="$(command -v pnpm 2>/dev/null || true)"
if [[ -z "$PNPM_BIN" ]]; then
  echo "Corepack and pnpm are unavailable" >&2
  exit 1
fi
EXPECTED_VERSION="${PNPM_SPEC#pnpm@}"
EXPECTED_VERSION="${EXPECTED_VERSION%%+*}"
ACTUAL_VERSION="$("$PNPM_BIN" --version)"
if [[ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]]; then
  echo "pnpm $EXPECTED_VERSION is required; found $ACTUAL_VERSION" >&2
  exit 1
fi
exec "$PNPM_BIN" "$@"
