#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
SNIPPET_PATH="${RAG_IME_SQUIRREL_CONFIG_SNIPPET:-$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml}"
RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
CONFIG_PATH="${RAG_IME_SQUIRREL_CUSTOM_CONFIG:-$RIME_USER_DIR/squirrel.custom.yaml}"
if [[ -n "${RAG_IME_RIME_DEFAULT_CUSTOM_CONFIG:-}" ]]; then
  DEFAULT_CONFIG_PATH="$RAG_IME_RIME_DEFAULT_CUSTOM_CONFIG"
elif [[ -n "${RAG_IME_SQUIRREL_CUSTOM_CONFIG:-}" ]]; then
  DEFAULT_CONFIG_PATH="$(dirname "$CONFIG_PATH")/default.custom.yaml"
else
  DEFAULT_CONFIG_PATH="$RIME_USER_DIR/default.custom.yaml"
fi
DEFAULT_PRIMARY_SCHEMA="${RAG_IME_RIME_PRIMARY_SCHEMA:-luna_pinyin_simp}"
DEFAULT_FALLBACK_SCHEMAS="${RAG_IME_RIME_FALLBACK_SCHEMAS:-luna_pinyin,bopomofo,cangjie5,quick5,stroke,terra_pinyin}"
DEFAULT_PAGE_SIZE="${RAG_IME_RIME_PAGE_SIZE:-8}"
SQUIRREL_APP="${RAG_IME_SQUIRREL_APP:-$HOME/Library/Input Methods/Squirrel.app}"
DEPLOY="${RAG_IME_SQUIRREL_DEPLOY:-0}"
DEPLOY_WAIT_SECONDS="${RAG_IME_SQUIRREL_DEPLOY_WAIT_SECONDS:-20}"
DRY_RUN="${RAG_IME_SQUIRREL_CONFIG_DRY_RUN:-0}"
if [[ -n "${RAG_IME_DB_PATH:-}" ]]; then
  SETTINGS_DB_PATH="$RAG_IME_DB_PATH"
elif [[ -z "${RAG_IME_SQUIRREL_CONFIG_SNIPPET+x}" ]]; then
  SETTINGS_DB_PATH="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}/rag-ime.sqlite"
else
  SETTINGS_DB_PATH=""
fi

if [[ ! -f "$SNIPPET_PATH" ]]; then
  echo "RAG-IME Squirrel config snippet not found: $SNIPPET_PATH" >&2
  echo "Run scripts/prepare_squirrel_workspace.sh first." >&2
  exit 1
fi

if [[ "$DRY_RUN" != "1" && "$DRY_RUN" != "true" && "$DRY_RUN" != "TRUE" ]]; then
  mkdir -p "$(dirname "$CONFIG_PATH")"
  mkdir -p "$(dirname "$DEFAULT_CONFIG_PATH")"
fi

SNIPPET_PATH="$SNIPPET_PATH" \
CONFIG_PATH="$CONFIG_PATH" \
DEFAULT_CONFIG_PATH="$DEFAULT_CONFIG_PATH" \
DEFAULT_PRIMARY_SCHEMA="$DEFAULT_PRIMARY_SCHEMA" \
DEFAULT_FALLBACK_SCHEMAS="$DEFAULT_FALLBACK_SCHEMAS" \
DEFAULT_PAGE_SIZE="$DEFAULT_PAGE_SIZE" \
SETTINGS_DB_PATH="$SETTINGS_DB_PATH" \
DRY_RUN="$DRY_RUN" \
python3 - <<'PY'
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

start = "# >>> RAG-IME managed block"
end = "# <<< RAG-IME managed block"
default_start = "# >>> RAG-IME default managed block"
default_end = "# <<< RAG-IME default managed block"
app_options_start = "# >>> RAG-IME app options managed block"
app_options_end = "# <<< RAG-IME app options managed block"
snippet_path = Path(os.environ["SNIPPET_PATH"])
config_path = Path(os.environ["CONFIG_PATH"])
default_config_path = Path(os.environ["DEFAULT_CONFIG_PATH"])
dry_run = os.environ.get("DRY_RUN", "0").lower() in {"1", "true", "yes"}
primary_schema = os.environ["DEFAULT_PRIMARY_SCHEMA"].strip() or "luna_pinyin_simp"
fallback_schemas = [
    item.strip()
    for item in os.environ["DEFAULT_FALLBACK_SCHEMAS"].split(",")
    if item.strip()
]
try:
    page_size = int(os.environ["DEFAULT_PAGE_SIZE"])
except ValueError as exc:
    raise SystemExit("RAG_IME_RIME_PAGE_SIZE must be an integer") from exc
if not 1 <= page_size <= 10:
    raise SystemExit("RAG_IME_RIME_PAGE_SIZE must be between 1 and 10")

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

settings_db_path = Path(os.environ["SETTINGS_DB_PATH"]).expanduser() if os.environ.get("SETTINGS_DB_PATH") else None
if settings_db_path is not None and settings_db_path.is_file():
    try:
        with sqlite3.connect(f"file:{settings_db_path}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM management_settings WHERE key IN ('display', 'interaction')"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise SystemExit(f"unable to read input settings database: {exc}") from exc
        rows = []
    sections: dict[str, object] = {}
    for key, value_json in rows:
        try:
            payload = json.loads(value_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"invalid persisted input setting section: {key}") from exc
        if isinstance(payload, dict):
            sections[str(key)] = payload
    display = sections.get("display") if isinstance(sections.get("display"), dict) else {}
    interaction = sections.get("interaction") if isinstance(sections.get("interaction"), dict) else {}
    post_commit = interaction.get("postCommit") if isinstance(interaction.get("postCommit"), dict) else {}
    max_side_candidates = display.get("maxPostCommitCandidates")
    idle_trigger_ms = post_commit.get("idleTriggerMs")
    if isinstance(max_side_candidates, int) and not isinstance(max_side_candidates, bool) and 1 <= max_side_candidates <= 8:
        values["max_side_candidates"] = str(max_side_candidates)
    if isinstance(idle_trigger_ms, int) and not isinstance(idle_trigger_ms, bool) and 40 <= idle_trigger_ms <= 1000:
        values["post_commit_idle_ms"] = str(idle_trigger_ms)

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

def write_managed_patch(
    config_path: Path,
    managed_block: str,
    marker_start: str,
    marker_end: str,
    *,
    strip_defaults: bool = False,
    source_override: str | None = None,
) -> str:
    if source_override is not None:
        original = source_override
    elif config_path.exists():
        original = config_path.read_text(encoding="utf-8")
    else:
        original = ""

    source = strip_default_patch_keys(original) if strip_defaults and marker_start not in original else original

    if marker_start in source and marker_end in source:
        before, rest = source.split(marker_start, 1)
        _, after = rest.split(marker_end, 1)
        updated = before.rstrip() + "\n" + managed_block + after
    elif any(line.strip() == "patch:" for line in source.splitlines()):
        output_lines: list[str] = []
        inserted = False
        for line in source.splitlines():
            output_lines.append(line)
            if not inserted and line.strip() == "patch:":
                output_lines.append(managed_block)
                inserted = True
        updated = "\n".join(output_lines).rstrip() + "\n"
    else:
        prefix = source.rstrip()
        updated = (prefix + "\n\n" if prefix else "") + "patch:\n" + managed_block + "\n"

    if dry_run:
        return updated
    if config_path.exists():
        backup = config_path.with_suffix(config_path.suffix + ".rag-ime.bak")
        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    config_path.write_text(updated, encoding="utf-8")
    return str(config_path)

def strip_default_patch_keys(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        is_patch_level = line.startswith("  ") and not line.startswith("    ")
        if is_patch_level and stripped == "schema_list:":
            index += 1
            while index < len(lines):
                nested = lines[index]
                if nested.startswith("    ") or not nested.strip() or nested.lstrip().startswith("#"):
                    index += 1
                    continue
                break
            continue
        if is_patch_level and (stripped.startswith('"menu/page_size":') or stripped.startswith("menu/page_size:")):
            index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output).rstrip() + ("\n" if text.endswith("\n") else "")

def strip_managed_block(text: str, marker_start: str, marker_end: str) -> str:
    if marker_start not in text:
        return text
    before, rest = text.split(marker_start, 1)
    if marker_end not in rest:
        return text
    _, after = rest.split(marker_end, 1)
    return (before.rstrip() + "\n" + after.lstrip("\n")).rstrip() + "\n"

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
    "post_commit_idle_ms",
    "timeout_ms",
    "frontend_trace",
):
    if key in values:
        managed_lines.append(f'  "rag_ime/{key}": {render_value(values[key])}')
# Keep the patched input method in Chinese composition mode in product and
# developer surfaces. This is separate from macOS input-source selection: it
# prevents Squirrel's per-application ASCII memory from making a selected
# Squirrel source look as if it disappeared inside the native WebView host.
chinese_composition_apps = (
    "com.apple.Terminal",
    "com.googlecode.iterm2",
    "com.microsoft.VSCode",
    "com.apple.dt.Xcode",
    "com.openai.codex",
    "com.mitchellh.ghostty",
    "com.github.wez.wezterm",
    "com.microsoft.edgemac",
    "com.google.Chrome",
    "org.gnu.Emacs",
    "org.vim.MacVim",
    "com.rag-ime.control",
    "com.rag-ime.control.web-preview",
)
managed_lines.append(
    "  # Product surfaces enter Chinese composition by default; users can still toggle ASCII explicitly."
)
managed_lines.extend(
    f'  "app_options/{bundle_id}/ascii_mode": false'
    for bundle_id in chinese_composition_apps
)
managed_lines.append(end)
managed_block = "\n".join(managed_lines)

schemas: list[str] = []
for schema in [primary_schema, *fallback_schemas]:
    if schema not in schemas:
        schemas.append(schema)
default_lines = [
    default_start,
    f'  "menu/page_size": {page_size}',
    "  schema_list:",
]
default_lines.extend(f"    - schema: {schema}" for schema in schemas)
default_lines.append(default_end)
default_block = "\n".join(default_lines)

if dry_run:
    print("# squirrel.custom.yaml")
    original_config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    original_config = strip_managed_block(original_config, app_options_start, app_options_end)
    print(write_managed_patch(config_path, managed_block, start, end, source_override=original_config), end="")
    print("\n# default.custom.yaml")
    print(write_managed_patch(default_config_path, default_block, default_start, default_end, strip_defaults=True), end="")
else:
    original_config = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    original_config = strip_managed_block(original_config, app_options_start, app_options_end)
    print(write_managed_patch(config_path, managed_block, start, end, source_override=original_config))
    print(write_managed_patch(default_config_path, default_block, default_start, default_end, strip_defaults=True))
PY

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  exit 0
fi

if [[ "$DEPLOY" == "1" || "$DEPLOY" == "true" || "$DEPLOY" == "TRUE" ]]; then
  if [[ -x "$SQUIRREL_APP/Contents/MacOS/Squirrel" ]]; then
    # Squirrel resolves the user-data directory from its working directory for
    # command-line deploys. Running these from the repository can return zero
    # while leaving build/squirrel.yaml unchanged.
    (cd "$RIME_USER_DIR" && "$SQUIRREL_APP/Contents/MacOS/Squirrel" --build)
    (cd "$RIME_USER_DIR" && "$SQUIRREL_APP/Contents/MacOS/Squirrel" --reload)
    build_config="$RIME_USER_DIR/build/squirrel.yaml"
    build_default="$RIME_USER_DIR/build/default.yaml"
    deploy_ready=0
    for ((attempt = 0; attempt < DEPLOY_WAIT_SECONDS * 4; attempt++)); do
      if [[ -f "$build_config" && -f "$build_default" \
        && ! "$CONFIG_PATH" -nt "$build_config" \
        && ! "$DEFAULT_CONFIG_PATH" -nt "$build_default" ]]; then
        deploy_ready=1
        break
      fi
      sleep 0.25
    done
    if [[ "$deploy_ready" != "1" ]]; then
      echo "Squirrel reload did not compile the updated user config within ${DEPLOY_WAIT_SECONDS}s" >&2
      exit 1
    fi
    echo "deployed Squirrel config with: $SQUIRREL_APP"
  else
    echo "Squirrel app executable not found, skipped deploy: $SQUIRREL_APP" >&2
  fi
fi
