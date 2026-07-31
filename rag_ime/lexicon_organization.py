from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Callable, Mapping

from .db import apply_database_migrations
from .rime_lexicon_review import review_rime_lexicon
from .settings_store import ManagementSettingsStore
from .text_utils import compact_whitespace

SCHEMA_VERSION = "rag-ime.lexicon-organization-status.v1"
OWNER = "maintenance_poll"
DECODER_OWNER = "rime"
DEFAULT_RUNS_PER_DAY = 2
MAX_RUNS_PER_DAY = 6
MAX_CANDIDATES_PER_RUN = 200
_MAX_RECEIPTS_PER_PROJECT = 32
_RUNNING_LEASE_MS = 60 * 60 * 1000
_PATH_RE = re.compile(r"(?:/Users/[^/\s]+|/Volumes/[^/\s]+|/private/var|/var/folders)(?:/[^\s,;:]*)?")
_SECRET_RE = re.compile(r"(?i)(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")


def lexicon_organization_settings(db_path: str | Path) -> dict[str, object]:
    settings = ManagementSettingsStore(db_path).get_settings(include_sensitive=True)
    raw = settings.get("lexiconOrganization")
    section = raw if isinstance(raw, Mapping) else {}
    return {
        "enabled": bool(section.get("enabled", True)),
        "runsPerDay": _bounded_int(
            section.get("runsPerDay"),
            default=DEFAULT_RUNS_PER_DAY,
            minimum=1,
            maximum=MAX_RUNS_PER_DAY,
        ),
    }


def lexicon_organization_status(
    db_path: str | Path,
    *,
    project: str = "",
    current_ms: int | None = None,
) -> dict[str, object]:
    timestamp = int(time.time() * 1000) if current_ms is None else max(0, int(current_ms))
    config = lexicon_organization_settings(db_path)
    interval_ms = max(60_000, 86_400_000 // int(config["runsPerDay"]))
    with closing(_connect(db_path)) as conn:
        _recover_interrupted_run(conn, project=project, current_ms=timestamp)
        latest = conn.execute(
            """
            SELECT * FROM lexicon_organization_runs
            WHERE project = ?
            ORDER BY started_at_ms DESC, run_id DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()
        last_success = conn.execute(
            """
            SELECT completed_at_ms FROM lexicon_organization_runs
            WHERE project = ? AND status = 'succeeded'
            ORDER BY completed_at_ms DESC, run_id DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()
    last_run = _run_payload(latest)
    last_run_at_ms = int(last_run.get("completedAtMs") or last_run.get("startedAtMs") or 0)
    next_run_at_ms = (
        None
        if not bool(config["enabled"])
        else timestamp
        if last_run_at_ms <= 0
        else last_run_at_ms + interval_ms
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "owner": OWNER,
        "decoderOwner": DECODER_OWNER,
        "enabled": bool(config["enabled"]),
        "runsPerDay": int(config["runsPerDay"]),
        "intervalMs": interval_ms,
        "candidateLimit": MAX_CANDIDATES_PER_RUN,
        "lastRunAtMs": last_run_at_ms,
        "lastSucceededAtMs": int(last_success["completed_at_ms"] or 0) if last_success else 0,
        "nextRunAtMs": next_run_at_ms,
        "due": bool(config["enabled"]) and next_run_at_ms is not None and timestamp >= next_run_at_ms,
        "lastRun": last_run,
        "privacy": {
            "localOnly": True,
            "storesRawCandidateText": False,
            "storesCandidateDigestOnly": True,
        },
    }


def run_due_lexicon_organization(
    db_path: str | Path,
    *,
    project: str = "",
    force: bool = False,
    current_ms: int | None = None,
    review: Callable[..., dict[str, object]] = review_rime_lexicon,
) -> dict[str, object]:
    timestamp = int(time.time() * 1000) if current_ms is None else max(0, int(current_ms))
    before = lexicon_organization_status(db_path, project=project, current_ms=timestamp)
    if not before["enabled"]:
        return {**before, "ran": False, "skipReason": "disabled"}
    if not force and not before["due"]:
        return {**before, "ran": False, "skipReason": "not_due"}

    run_id = f"lexorg_{timestamp}_{uuid.uuid4().hex[:12]}"
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO lexicon_organization_runs(
                run_id, project, status, started_at_ms
            ) VALUES (?, ?, 'running', ?)
            """,
            (run_id, project, timestamp),
        )
    try:
        result = review(
            db_path,
            project=project,
            limit=MAX_CANDIDATES_PER_RUN,
            rime_user_dir=None,
        )
        if result.get("ok") is not True:
            raise RuntimeError(compact_whitespace(str(result.get("reason") or result.get("error") or "review_failed")))
        completed_at_ms = max(timestamp, int(time.time() * 1000) if current_ms is None else timestamp)
        candidate_count = _bounded_int(
            result.get("entryCount"), default=0, minimum=0, maximum=MAX_CANDIDATES_PER_RUN
        )
        filtered_count = _bounded_int(
            result.get("filteredEntryCount"), default=0, minimum=0, maximum=1_000_000
        )
        review_digest = hashlib.sha256(
            compact_whitespace(str(result.get("reviewToken") or "")).encode("utf-8")
        ).hexdigest()
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(
                """
                UPDATE lexicon_organization_runs
                SET status = 'succeeded', completed_at_ms = ?, candidate_count = ?,
                    filtered_entry_count = ?, review_token_sha256 = ?
                WHERE run_id = ?
                """,
                (completed_at_ms, candidate_count, filtered_count, review_digest, run_id),
            )
            _prune_receipts(conn, project=project)
    except Exception as exc:
        completed_at_ms = max(timestamp, int(time.time() * 1000) if current_ms is None else timestamp)
        error_code, error_text = _safe_error(exc)
        with closing(_connect(db_path)) as conn, conn:
            conn.execute(
                """
                UPDATE lexicon_organization_runs
                SET status = 'failed', completed_at_ms = ?, error_code = ?, error_text = ?
                WHERE run_id = ?
                """,
                (completed_at_ms, error_code, error_text, run_id),
            )
            _prune_receipts(conn, project=project)

    after = lexicon_organization_status(db_path, project=project, current_ms=completed_at_ms)
    return {
        **after,
        "ran": True,
        "skipReason": "",
        "ok": str(dict(after.get("lastRun") or {}).get("status") or "") == "succeeded",
    }


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    apply_database_migrations(conn)
    return conn


def _recover_interrupted_run(conn: sqlite3.Connection, *, project: str, current_ms: int) -> None:
    cutoff = current_ms - _RUNNING_LEASE_MS
    with conn:
        conn.execute(
            """
            UPDATE lexicon_organization_runs
            SET status = 'failed', completed_at_ms = ?,
                error_code = 'interrupted_run',
                error_text = '上次本机词库整理未写入完成回执。'
            WHERE project = ? AND status = 'running' AND started_at_ms <= ?
            """,
            (current_ms, project, cutoff),
        )


def _prune_receipts(conn: sqlite3.Connection, *, project: str) -> None:
    conn.execute(
        """
        DELETE FROM lexicon_organization_runs
        WHERE project = ? AND run_id NOT IN (
            SELECT run_id FROM lexicon_organization_runs
            WHERE project = ?
            ORDER BY started_at_ms DESC, run_id DESC
            LIMIT ?
        )
        """,
        (project, project, _MAX_RECEIPTS_PER_PROJECT),
    )


def _run_payload(row: sqlite3.Row | None) -> dict[str, object]:
    if row is None:
        return {}
    return {
        "runId": str(row["run_id"]),
        "status": str(row["status"]),
        "startedAtMs": int(row["started_at_ms"] or 0),
        "completedAtMs": int(row["completed_at_ms"] or 0),
        "candidateCount": int(row["candidate_count"] or 0),
        "filteredEntryCount": int(row["filtered_entry_count"] or 0),
        "candidateDigest": str(row["review_token_sha256"] or ""),
        "errorCode": str(row["error_code"] or ""),
        "error": str(row["error_text"] or ""),
    }


def _safe_error(exc: Exception) -> tuple[str, str]:
    code = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()[:80] or "organization_error"
    message = compact_whitespace(str(exc)) or "本机词库整理失败。"
    message = _PATH_RE.sub("[LOCAL_PATH]", message)
    message = _SECRET_RE.sub("[REDACTED_SECRET]", message)
    return code, message[:240]


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
