#!/usr/bin/env bash
# Shared identity for an already verified installer payload. Source builds keep
# using Git; binary installs never need Git, Xcode, pnpm or a system Python.
paw_prebuilt_identity() {
  [[ -n "${PAW_BINARY_PAYLOAD:-}" ]] || return 1
  [[ "$ROOT" == "$PAW_BINARY_PAYLOAD/source" ]] || {
    echo "binary payload does not own this installer source" >&2; exit 1;
  }
  SOURCE_COMMIT="$(python3 - "$PAW_BINARY_PAYLOAD/installer-manifest.json" <<'PY'
import json, re, sys
m = json.load(open(sys.argv[1]))
c = m.get('productSourceCommit', '')
if m.get('schemaVersion') != 'paw.binary-installer.v1' or not re.fullmatch(r'[0-9a-f]{40}', c):
    raise SystemExit('invalid binary installer manifest')
print(c)
PY
  )"
  SOURCE_BRANCH=main
  SOURCE_DIRTY=false
}
