#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
SNIPPET_PATH="${RAG_IME_SQUIRREL_CONFIG_SNIPPET:-$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml}"
RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
CONFIG_PATH="${RAG_IME_SQUIRREL_CUSTOM_CONFIG:-$RIME_USER_DIR/squirrel.custom.yaml}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
DEPLOY="${RAG_IME_SQUIRREL_DEPLOY:-0}"
DRY_RUN="${RAG_IME_SQUIRREL_CONFIG_DRY_RUN:-0}"

if [[ ! -f "$SNIPPET_PATH" ]]; then
  echo "RAG-IME Squirrel config snippet not found: $SNIPPET_PATH" >&2
  echo "Run scripts/prepare_squirrel_workspace.sh first." >&2
  exit 1
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "true" && "$DRY_RUN" != "TRUE" ]]; then
  mkdir -p "$(dirname "$CONFIG_PATH")"
fi

SNIPPET_PATH="$SNIPPET_PATH" \
CONFIG_PATH="$CONFIG_PATH" \
DRY_RUN="$DRY_RUN" \
python3 - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

start = "# >>> RAG-IME managed block"
end = "# <<< RAG-IME managed block"
snippet_path = Path(os.environ["SNIPPET_PATH"])
config_path = Path(os.environ["CONFIG_PATH"])
dry_run = os.environ.get("DRY_RUN", "0").lower() in {"1", "true", "yes"}

values: dict[str, str] = {}
inside_rag_ime = False
for raw_line in snippet_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.rstrip()
    if not line or line.lstrip().startswith("#"):
        continue
    if line == "rag_ime:":
        inside_rag_ime = True
        continue
    if inside_rag_ime:
        if not line.startswith("  "):
            inside_rag_ime = False
            continue
        key, sep, value = line.strip().partition(":")
        if sep:
            values[key.strip()] = value.strip()

required = ("enabled", "sidecar_url", "repo_root", "db_path", "project")
missing = [key for key in required if key not in values]
if missing:
    raise SystemExit(f"config snippet is missing required rag_ime keys: {', '.join(missing)}")

def render_value(value: str) -> str:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered
    try:
        int(value)
        return value
    except ValueError:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

managed_lines = [start]
for key in (
    "enabled",
    "sidecar_url",
    "python",
    "repo_root",
    "db_path",
    "project",
    "max_visible_candidates",
    "max_side_candidates",
    "latency_budget_ms",
    "debounce_ms",
    "timeout_ms",
):
    if key in values:
        managed_lines.append(f'  "rag_ime/{key}": {render_value(values[key])}')
managed_lines.append(end)
managed_block = "\n".join(managed_lines)

if config_path.exists():
    original = config_path.read_text(encoding="utf-8")
else:
    original = ""

if start in original and end in original:
    before, rest = original.split(start, 1)
    _, after = rest.split(end, 1)
    updated = before.rstrip() + "\n" + managed_block + after
elif any(line.strip() == "patch:" for line in original.splitlines()):
    output_lines: list[str] = []
    inserted = False
    for line in original.splitlines():
        output_lines.append(line)
        if not inserted and line.strip() == "patch:":
            output_lines.append(managed_block)
            inserted = True
    updated = "\n".join(output_lines).rstrip() + "\n"
else:
    prefix = original.rstrip()
    updated = (prefix + "\n\n" if prefix else "") + "patch:\n" + managed_block + "\n"

if dry_run:
    print(updated, end="")
else:
    if config_path.exists():
        backup = config_path.with_suffix(config_path.suffix + ".rag-ime.bak")
        backup.write_text(original, encoding="utf-8")
    config_path.write_text(updated, encoding="utf-8")
    print(config_path)
PY

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  exit 0
fi

if [[ "$DEPLOY" == "1" || "$DEPLOY" == "true" || "$DEPLOY" == "TRUE" ]]; then
  if [[ -x "$SQUIRREL_APP/Contents/MacOS/Squirrel" ]]; then
    "$SQUIRREL_APP/Contents/MacOS/Squirrel" --reload
    echo "deployed Squirrel config with: $SQUIRREL_APP"
  else
    echo "Squirrel app executable not found, skipped deploy: $SQUIRREL_APP" >&2
  fi
fi
