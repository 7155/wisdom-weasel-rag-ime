#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
DB_PATH="${RAG_IME_DB_PATH:-$APP_SUPPORT_DIR/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
OUT_DIR="${RAG_IME_MEMORY_BOOK_MAINTENANCE_DIR:-$APP_SUPPORT_DIR/memory-book-runs}"
LOCK_DIR="${RAG_IME_MEMORY_BOOK_MAINTENANCE_LOCK_DIR:-$OUT_DIR/.maintenance.lock}"
LOCK_OWNER_FILE="$LOCK_DIR/owner.pid"
STALE_LOCK_SECONDS="${RAG_IME_MEMORY_BOOK_MAINTENANCE_STALE_LOCK_SECONDS:-21600}"
SINCE_DAYS="${RAG_IME_MEMORY_BOOK_MAINTENANCE_SINCE_DAYS:-7}"
RECENT_LIMIT="${RAG_IME_MEMORY_BOOK_MAINTENANCE_RECENT_LIMIT:-48}"
APPLY="${RAG_IME_MEMORY_BOOK_MAINTENANCE_APPLY:-0}"
LEGACY_MAINTENANCE="${RAG_IME_LEGACY_MEMORY_BOOK_MAINTENANCE:-0}"
PERSONAL_CONTEXT_ENABLED="${RAG_IME_PERSONAL_CONTEXT_MAINTENANCE_ENABLED:-1}"
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

lock_is_stale() {
  "$PYTHON_EXECUTABLE" - "$LOCK_DIR" "$LOCK_OWNER_FILE" "$STALE_LOCK_SECONDS" <<'PY'
import os
import sys
import time
from pathlib import Path

lock_dir = Path(sys.argv[1])
owner_file = Path(sys.argv[2])
try:
    stale_after = max(300, int(sys.argv[3]))
    age = max(0.0, time.time() - lock_dir.stat().st_mtime)
except (OSError, ValueError):
    raise SystemExit(1)

# An abandoned lock must not disable daily curation forever, including after
# reboot/PID reuse. A healthy run is bounded far below this timeout.
if age >= stale_after:
    raise SystemExit(0)
try:
    owner_pid = int(owner_file.read_text(encoding="utf-8").strip())
except (OSError, ValueError):
    raise SystemExit(1)
try:
    os.kill(owner_pid, 0)
except ProcessLookupError:
    raise SystemExit(0)
except (PermissionError, OSError):
    raise SystemExit(1)
raise SystemExit(1)
PY
}

write_lock_owner() {
  printf '%s\n' "$$" >"$LOCK_OWNER_FILE"
}

acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    write_lock_owner
    return 0
  fi
  if ! lock_is_stale; then
    return 1
  fi

  local stale_lock_dir="${LOCK_DIR}.stale.$$.${RANDOM}"
  if mv "$LOCK_DIR" "$stale_lock_dir" 2>/dev/null; then
    rm -f "$stale_lock_dir/owner.pid"
    rmdir "$stale_lock_dir" >/dev/null 2>&1 || true
  fi
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    write_lock_owner
    return 0
  fi
  return 1
}

if ! acquire_lock; then
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
  local owner_pid=""
  if [[ -f "$LOCK_OWNER_FILE" ]]; then
    owner_pid="$(<"$LOCK_OWNER_FILE")"
  fi
  if [[ "$owner_pid" == "$$" ]]; then
    rm -f "$LOCK_OWNER_FILE"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup_lock EXIT INT TERM

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
PLAN_PATH="$OUT_DIR/memory-book-$STAMP.json"
PREVIEW_LOG="$OUT_DIR/memory-book-$STAMP.preview.json"
VALIDATE_LOG="$OUT_DIR/memory-book-$STAMP.validate.json"
APPLY_LOG="$OUT_DIR/memory-book-$STAMP.apply.json"
OWNER_CURATION_LOG="$OUT_DIR/owner-memory-$STAMP.json"
PERSONAL_CONTEXT_LOG="$OUT_DIR/personal-context-$STAMP.json"

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
export RAG_IME_DEEPSEEK_REASONING_EFFORT="${RAG_IME_DEEPSEEK_REASONING_EFFORT:-low}"
export RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS="${RAG_IME_DEEPSEEK_MEMORY_BOOK_MAX_TOKENS:-2048}"

# Personal Context is deterministic and role-scoped. It produces reviewable
# User Memory, Role Book and Activity Timeline drafts independently of the
# model-backed owner curator below.
PERSONAL_CONTEXT_STATUS=0
if [[ "$PERSONAL_CONTEXT_ENABLED" == "1" || "$PERSONAL_CONTEXT_ENABLED" == "true" || "$PERSONAL_CONTEXT_ENABLED" == "TRUE" || "$PERSONAL_CONTEXT_ENABLED" == "yes" ]]; then
  set +e
  "$PYTHON_EXECUTABLE" -m rag_ime.cli \
    --core-mode local \
    --db-path "$DB_PATH" \
    personal-context-maintenance-run \
    --project "$PROJECT" \
    --report-path "$PERSONAL_CONTEXT_LOG" >/dev/null
  PERSONAL_CONTEXT_STATUS=$?
  set -e
else
  "$PYTHON_EXECUTABLE" - "$PERSONAL_CONTEXT_LOG" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.personal-context-maintenance-run.v1",
            "ok": True,
            "skipped": True,
            "reason": "personal_context_maintenance_disabled",
            "targets": [],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
fi
if [[ ! -s "$PERSONAL_CONTEXT_LOG" ]]; then
  "$PYTHON_EXECUTABLE" - "$PERSONAL_CONTEXT_LOG" "$PERSONAL_CONTEXT_STATUS" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "schemaVersion": "rag-ime.personal-context-maintenance-run.v1",
            "ok": False,
            "error": "personal_context_maintenance_process_failed",
            "exitCode": int(sys.argv[2]),
            "targets": [],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
fi

owner_cmd=(
  "$PYTHON_EXECUTABLE" -m rag_ime.owner_memory_maintenance
  --db-path "$DB_PATH"
  --project "$PROJECT"
  --max-sources "$RECENT_LIMIT"
)
if [[ "$TRIGGER" == "manual" ]]; then
  owner_cmd+=(--manual)
fi
if [[ -n "$MODEL_ENV_PATH" ]]; then
  owner_cmd+=(--model-env-path "$MODEL_ENV_PATH")
fi
set +e
"${owner_cmd[@]}" >"$OWNER_CURATION_LOG"
OWNER_CURATION_STATUS=$?
set -e

# Owner-scoped curation is the authoritative default. The former global
# compiler remains available only as an explicit compatibility lane because
# running both organizers creates duplicate drafts and bypasses owner/source
# governance.
if [[ "$LEGACY_MAINTENANCE" != "1" && "$LEGACY_MAINTENANCE" != "true" && "$LEGACY_MAINTENANCE" != "TRUE" && "$LEGACY_MAINTENANCE" != "yes" ]]; then
  set +e
  "$PYTHON_EXECUTABLE" - "$OWNER_CURATION_LOG" "$OWNER_CURATION_STATUS" "$PERSONAL_CONTEXT_LOG" "$PERSONAL_CONTEXT_STATUS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

owner_path = Path(sys.argv[1])
owner_status = int(sys.argv[2])
personal_context_path = Path(sys.argv[3])
personal_context_status = int(sys.argv[4])
try:
    owner_curation = json.loads(owner_path.read_text(encoding="utf-8"))
except Exception as exc:
    owner_curation = {"ok": False, "error": str(exc)}
try:
    personal_context = json.loads(personal_context_path.read_text(encoding="utf-8"))
except Exception as exc:
    personal_context = {"ok": False, "error": str(exc), "targets": []}
results = [
    item
    for item in owner_curation.get("results", [])
    if isinstance(item, dict)
]
status = (
    owner_curation.get("status")
    if isinstance(owner_curation.get("status"), dict)
    else {}
)
scopes = [
    item
    for item in status.get("scopes", [])
    if isinstance(item, dict)
]
payload = {
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": owner_status == 0 and bool(owner_curation.get("ok")),
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "mode": "owner_scoped",
    "applied": False,
    "reviewRequired": any(bool(item.get("reviewRequired")) for item in results),
    "skipped": int(owner_curation.get("ranScopeCount") or 0) == 0,
    "skipReason": (
        ",".join(
            sorted(
                {
                    str(item.get("dueReason") or "not_due")
                    for item in scopes
                }
            )
        )
        if int(owner_curation.get("ranScopeCount") or 0) == 0
        else ""
    ),
    "ownerCurationLog": str(owner_path),
    "ownerCuration": owner_curation,
    "personalContextLog": str(personal_context_path),
    "personalContextMaintenance": personal_context,
    "personalContextMaintenanceExitCode": personal_context_status,
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if payload["ok"] else 1)
PY
  OWNER_ONLY_STATUS=$?
  set -e
  exit "$OWNER_ONLY_STATUS"
fi

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
    "$PYTHON_EXECUTABLE" - "$DUE_JSON" "$OWNER_CURATION_LOG" "$OWNER_CURATION_STATUS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

due = json.loads(sys.argv[1])
owner_path = Path(sys.argv[2])
owner_status = int(sys.argv[3])
try:
    owner_curation = json.loads(owner_path.read_text(encoding="utf-8"))
except Exception as exc:
    owner_curation = {"ok": False, "error": str(exc)}
payload = {
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": owner_status == 0 and bool(owner_curation.get("ok")),
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "applied": False,
    "skipped": True,
    "skipReason": due["reason"],
    "compileState": due["state"],
    "ownerCurationLog": str(owner_path),
    "ownerCuration": owner_curation,
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if payload["ok"] else 1)
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

"$PYTHON_EXECUTABLE" - "$PLAN_PATH" "$PREVIEW_LOG" "$VALIDATE_LOG" "$APPLY_LOG" "$applied" "$OWNER_CURATION_LOG" "$OWNER_CURATION_STATUS" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

plan_path, preview_path, validate_path, apply_path, applied, owner_path, owner_status = sys.argv[1:8]
payload = {
    "schemaVersion": "rag-ime.memory-book-maintenance.v1",
    "ok": True,
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "applied": applied == "true",
    "reviewRequired": False,
    "planPath": plan_path,
    "previewLog": preview_path,
    "validateLog": validate_path,
    "applyLog": apply_path if applied == "true" else "",
    "ownerCurationLog": owner_path,
}
try:
    owner_curation = json.loads(Path(owner_path).read_text(encoding="utf-8"))
    payload["ownerCuration"] = owner_curation
    if int(owner_status) != 0 or not owner_curation.get("ok"):
        payload["ok"] = False
except Exception as exc:
    payload["ok"] = False
    payload["ownerCuration"] = {"ok": False, "error": str(exc)}
try:
    preview = json.loads(Path(preview_path).read_text(encoding="utf-8"))
    run = preview.get("run") if isinstance(preview.get("run"), dict) else {}
    payload["storedDraft"] = bool(preview.get("storedDraft"))
    payload["reviewRequired"] = payload["storedDraft"] and applied != "true"
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
raise SystemExit(0 if payload["ok"] else 1)
PY
