#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
DB_PATH="${RAG_IME_DB_PATH:-$APP_SUPPORT_DIR/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
OUT_DIR="${RAG_IME_MEMORY_BOOK_MAINTENANCE_DIR:-$APP_SUPPORT_DIR/memory-book-runs}"
LOCK_DIR="${RAG_IME_MEMORY_BOOK_MAINTENANCE_LOCK_DIR:-$OUT_DIR/.maintenance.lock}"
SINCE_DAYS="${RAG_IME_MEMORY_BOOK_MAINTENANCE_SINCE_DAYS:-7}"
RECENT_LIMIT="${RAG_IME_MEMORY_BOOK_MAINTENANCE_RECENT_LIMIT:-120}"
APPLY="${RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY:-0}"
MODEL_ENV_PATH="${RAG_IME_DEEPSEEK_ENV:-${RAG_IME_MODEL_ENV:-}}"
TRIGGER="${RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER:-manual}"

detect_python() {
  local candidate
  for candidate in \
    "$ROOT/.venv/bin/python" \
    "$ROOT/.venv-mlx313/bin/python" \
    "/opt/homebrew/bin/python3" \
    "$(command -v python3 2>/dev/null || true)" \
    "/usr/local/bin/python3"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(detect_python || true)}"
if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found; set RAG_IME_PYTHON" >&2
  exit 1
fi

mkdir -p "$OUT_DIR" "$(dirname "$DB_PATH")"
mkdir -p "$(dirname "$LOCK_DIR")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  "$PYTHON_EXECUTABLE" - "$LOCK_DIR" <<'PY'
import json
import sys
from datetime import datetime, timezone

payload = {
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": True,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "applied": False,
    "skipped": True,
    "skipReason": "maintenance_lock_held",
    "lockDir": sys.argv[1],
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
  exit 0
fi
cleanup_lock() {
  rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}
trap cleanup_lock EXIT INT TERM

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
PLAN_PATH="$OUT_DIR/memory-book-$STAMP.json"
PREVIEW_LOG="$OUT_DIR/memory-book-$STAMP.preview.json"
VALIDATE_LOG="$OUT_DIR/memory-book-$STAMP.validate.json"
APPLY_LOG="$OUT_DIR/memory-book-$STAMP.apply.json"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export RAG_IME_DEEPSEEK_REASONING_EFFORT="${RAG_IME_DEEPSEEK_REASONING_EFFORT:-low}"
export RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS="${RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS:-2048}"

if [[ "$TRIGGER" != "manual" ]]; then
  set +e
  DUE_JSON="$($PYTHON_EXECUTABLE - "$DB_PATH" "$PROJECT" <<'PY'
import json
import sqlite3
import sys
import time

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import memory_compile_due

db_path, project = sys.argv[1:3]
core = LocalSqliteCoreClient(db_path)
core.initialize()
with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT MAX(created_at_ms) FROM input_events WHERE (? = '' OR project = ? OR project = '')",
        (project, project),
    ).fetchone()
    last_event_ms = int(row[0] or 0)
    current_ms = int(time.time() * 1000)
    due, reason, state = memory_compile_due(
        conn,
        project=project,
        idle_ms=max(0, current_ms - last_event_ms) if last_event_ms else 0,
        current_ms=current_ms,
    )
print(json.dumps({"due": due, "reason": reason, "state": state}, ensure_ascii=False))
raise SystemExit(0 if due else 3)
PY
)"
  DUE_STATUS=$?
  set -e
  if [[ "$DUE_STATUS" == "3" ]]; then
    "$PYTHON_EXECUTABLE" - "$DUE_JSON" <<'PY'
import json
import sys
from datetime import datetime, timezone

due = json.loads(sys.argv[1])
print(json.dumps({
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": True,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "applied": False,
    "skipped": True,
    "skipReason": due["reason"],
    "compileState": due["state"],
}, ensure_ascii=False, indent=2))
PY
    exit 0
  fi
  if [[ "$DUE_STATUS" != "0" ]]; then
    echo "$DUE_JSON" >&2
    exit "$DUE_STATUS"
  fi
fi

preview_cmd=(
  "$PYTHON_EXECUTABLE" -m rag_ime.cli
  --core-mode local
  --db-path "$DB_PATH"
  memory-book-preview
  --project "$PROJECT"
  --since-days "$SINCE_DAYS"
  --recent-limit "$RECENT_LIMIT"
  --output "$PLAN_PATH"
  --save-draft
)
if [[ -n "$MODEL_ENV_PATH" ]]; then
  preview_cmd+=(--model-env-path "$MODEL_ENV_PATH")
fi

"${preview_cmd[@]}" >"$PREVIEW_LOG"
"$PYTHON_EXECUTABLE" -m rag_ime.cli memory-book-validate --run "$PLAN_PATH" >"$VALIDATE_LOG"

applied=false
if [[ "$APPLY" == "1" || "$APPLY" == "true" || "$APPLY" == "TRUE" || "$APPLY" == "yes" ]]; then
  "$PYTHON_EXECUTABLE" -m rag_ime.cli \
    --core-mode local \
    --db-path "$DB_PATH" \
    memory-book-apply \
    --run "$PLAN_PATH" \
    --apply >"$APPLY_LOG"
  applied=true
fi

"$PYTHON_EXECUTABLE" - "$PLAN_PATH" "$PREVIEW_LOG" "$VALIDATE_LOG" "$APPLY_LOG" "$applied" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

plan_path, preview_path, validate_path, apply_path, applied = sys.argv[1:6]
payload = {
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": True,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "applied": applied == "true",
    "reviewRequired": applied != "true",
    "planPath": plan_path,
    "previewLog": preview_path,
    "validateLog": validate_path,
    "applyLog": apply_path if applied == "true" else "",
}
try:
    preview = json.loads(Path(preview_path).read_text(encoding="utf-8"))
    run = preview.get("run") if isinstance(preview.get("run"), dict) else {}
    payload["storedDraft"] = bool(preview.get("storedDraft"))
    payload["reusedDraft"] = bool(preview.get("reusedDraft"))
    payload["runId"] = str(run.get("runId") or "")
except Exception as exc:
    payload["ok"] = False
    payload["previewError"] = str(exc)
try:
    validate = json.loads(Path(validate_path).read_text(encoding="utf-8"))
    payload["validationOk"] = bool(validate.get("ok"))
except Exception as exc:
    payload["ok"] = False
    payload["validationOk"] = False
    payload["validationError"] = str(exc)
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
