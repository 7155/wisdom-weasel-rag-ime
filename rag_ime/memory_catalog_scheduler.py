from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from threading import RLock

from .db import apply_database_migrations
from .text_utils import compact_whitespace


CATALOG_CONSOLIDATION_SCHEMA_VERSION = "rag-ime.memory-catalog-consolidation.v1"
DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS = 7
MIN_CATALOG_CONSOLIDATION_CADENCE_DAYS = 1
MAX_CATALOG_CONSOLIDATION_CADENCE_DAYS = 365
CATALOG_CONSOLIDATION_RETRY_BASE_MS = 15 * 60 * 1_000
CATALOG_CONSOLIDATION_RETRY_MAX_MS = 24 * 60 * 60 * 1_000
CATALOG_CONSOLIDATION_LEASE_DURATION_MS = 3 * 60 * 60 * 1_000
MAX_CATALOG_CONSOLIDATION_ERROR_CHARS = 800
MAX_CATALOG_CONSOLIDATION_RESULT_BYTES = 12_000

CATALOG_CONSOLIDATION_LEASE_MS = CATALOG_CONSOLIDATION_LEASE_DURATION_MS


class MemoryCatalogConsolidationScheduler:
    """Persist admission, lease, and result state for the global catalog lane.

    Receipt rows are append-only.  A small mutable lease table is the SQLite
    compare-and-swap guard that allows exactly one worker to append the next
    transition for a project.  The in-process lock is only an optimization;
    correctness comes from ``BEGIN IMMEDIATE`` and the lease owner token.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock_ms: Callable[[], int] | None = None,
        lease_duration_ms: int = CATALOG_CONSOLIDATION_LEASE_DURATION_MS,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1_000))
        self._lease_duration_ms = max(1, int(lease_duration_ms))
        self._lock = RLock()
        self.initialize()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path, timeout=10)) as conn:
            apply_database_migrations(conn)
            conn.commit()

    def status(
        self,
        project: str,
        *,
        current_ms: int | None = None,
    ) -> dict[str, object]:
        normalized_project = _project(project)
        current = self._now(current_ms)
        with self._lock:
            with self._connect() as conn:
                return self._status_from_connection(
                    conn,
                    normalized_project,
                    current_ms=current,
                )

    latest_status = status

    def admit(
        self,
        project: str,
        *,
        manual: bool = False,
        enabled: bool = True,
        automatic_organization_enabled: bool = True,
        cadence_days: int = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
        current_ms: int | None = None,
    ) -> dict[str, object]:
        """Atomically admit one due project and return its opaque lease token.

        A running receipt can only be recovered after its persisted lease has
        expired.  Manual force bypasses cadence, but never bypasses a live
        lease or either execution gate.
        """

        normalized_project = _project(project)
        current = self._now(current_ms)
        cadence = _cadence_days(cadence_days)
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                previous = self._status_from_connection(
                    conn,
                    normalized_project,
                    current_ms=current,
                )
                if not enabled:
                    conn.commit()
                    return _decision(
                        normalized_project,
                        previous,
                        due=False,
                        admitted=False,
                        skipped=True,
                        reason="catalog_consolidation_disabled",
                    )
                if not automatic_organization_enabled:
                    conn.commit()
                    return _decision(
                        normalized_project,
                        previous,
                        due=False,
                        admitted=False,
                        skipped=True,
                        reason="automatic_organization_disabled",
                    )
                admission_status = _admission_status(
                    previous,
                    cadence_days=cadence,
                    current_ms=current,
                )


                if (
                    str(previous.get("state") or "") == "running"
                    and int(previous.get("leaseExpiresAtMs") or 0) > current
                ):
                    conn.commit()
                    return _decision(
                        normalized_project,
                        previous,
                        due=False,
                        admitted=False,
                        skipped=False,
                        reason="already_running",
                    )

                due = bool(manual) or bool(admission_status.get("due"))
                if not due:
                    conn.commit()
                    return _decision(
                        normalized_project,
                        admission_status,
                        due=False,
                        admitted=False,
                        skipped=False,
                        reason="not_due",
                    )

                attempt_count = int(previous.get("attemptCount") or 0) + 1
                retry_count = int(previous.get("retryCount") or 0)
                owner_token = _new_admission_token()
                lease_expires = current + self._lease_duration_ms
                receipt_id = _receipt_id()
                # An expired predecessor is deliberately replaced only inside
                # this write transaction.  A live predecessor never reaches
                # this branch.
                conn.execute(
                    "DELETE FROM memory_catalog_consolidation_leases WHERE project = ?",
                    (normalized_project,),
                )
                conn.execute(
                    """
                    INSERT INTO memory_catalog_consolidation_leases(
                        project, owner_token, receipt_id,
                        lease_expires_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_project,
                        owner_token,
                        receipt_id,
                        lease_expires,
                        current,
                    ),
                )
                self._insert_receipt(
                    conn,
                    receipt_id=receipt_id,
                    project=normalized_project,
                    state="running",
                    last_attempt_at_ms=current,
                    last_completion_at_ms=int(
                        previous.get("lastCompletionAtMs") or 0
                    ),
                    next_due_at_ms=lease_expires,
                    catalog_digest="",
                    curation_run_id=str(previous.get("curationRunId") or ""),
                    attempt_count=attempt_count,
                    retry_count=retry_count,
                    result={},
                    error="",
                    current_ms=current,
                    admission_token=owner_token,
                    lease_expires_at_ms=lease_expires,
                    last_successful_catalog_digest=str(
                        previous.get("lastSuccessfulCatalogDigest") or ""
                    ),
                    last_successful_catalog_committed_at_ms=int(
                        previous.get("lastSuccessfulCatalogCommittedAtMs") or 0
                    ),
                )
                conn.commit()
                status = self.status(normalized_project, current_ms=current)
                return _decision(
                    normalized_project,
                    status,
                    due=True,
                    admitted=True,
                    skipped=False,
                    reason="manual" if manual else _due_reason(admission_status),
                    admission_token=owner_token,
                )

    def record_digest(
        self,
        project: str,
        catalog_digest: str,
        *,
        admission_token: str | None = None,
        current_ms: int | None = None,
    ) -> dict[str, object]:
        """Append the digest observed by the live lease owner."""

        normalized_project = _project(project)
        current = self._now(current_ms)
        normalized_digest = _digest(catalog_digest)
        if not normalized_digest:
            raise ValueError("catalog consolidation digest must be non-empty")
        token = _required_token(admission_token)
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                previous = self._status_from_connection(
                    conn,
                    normalized_project,
                    current_ms=current,
                )
                lease = self._require_live_lease(
                    conn,
                    project=normalized_project,
                    previous=previous,
                    admission_token=token,
                    current_ms=current,
                )
                receipt_id = _receipt_id()
                lease_expires = current + self._lease_duration_ms
                self._extend_lease(
                    conn,
                    project=normalized_project,
                    owner_token=token,
                    previous_receipt_id=str(lease["receipt_id"]),
                    receipt_id=receipt_id,
                    lease_expires_at_ms=lease_expires,
                    current_ms=current,
                )
                self._insert_receipt(
                    conn,
                    receipt_id=receipt_id,
                    project=normalized_project,
                    state="running",
                    last_attempt_at_ms=int(
                        previous.get("lastAttemptAtMs") or current
                    ),
                    last_completion_at_ms=int(
                        previous.get("lastCompletionAtMs") or 0
                    ),
                    next_due_at_ms=lease_expires,
                    catalog_digest=normalized_digest,
                    curation_run_id=str(previous.get("curationRunId") or ""),
                    attempt_count=max(1, int(previous.get("attemptCount") or 0)),
                    retry_count=int(previous.get("retryCount") or 0),
                    result={},
                    error="",
                    current_ms=current,
                    admission_token=token,
                    lease_expires_at_ms=lease_expires,
                    last_successful_catalog_digest=str(
                        previous.get("lastSuccessfulCatalogDigest") or ""
                    ),
                    last_successful_catalog_committed_at_ms=int(
                        previous.get("lastSuccessfulCatalogCommittedAtMs") or 0
                    ),
                )
                conn.commit()
                return self.status(normalized_project, current_ms=current)

    def complete(
        self,
        project: str,
        *,
        catalog_digest: str,
        result: Mapping[str, object] | None = None,
        curation_run_id: str = "",
        ok: bool,
        error: str = "",
        cadence_days: int = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
        admission_token: str | None = None,
        current_ms: int | None = None,
    ) -> dict[str, object]:
        """Append a truthful terminal receipt owned by the live lease token."""

        normalized_project = _project(project)
        current = self._now(current_ms)
        cadence = _cadence_days(cadence_days)
        token = _required_token(admission_token)
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                previous = self._status_from_connection(
                    conn,
                    normalized_project,
                    current_ms=current,
                )
                lease = self._require_live_lease(
                    conn,
                    project=normalized_project,
                    previous=previous,
                    admission_token=token,
                    current_ms=current,
                )
                succeeded = bool(ok)
                previous_retry_count = int(previous.get("retryCount") or 0)
                retry_count = 0 if succeeded else previous_retry_count + 1
                next_due = (
                    current + cadence * 24 * 60 * 60 * 1_000
                    if succeeded
                    else current + _retry_backoff_ms(retry_count)
                )
                baseline_digest = str(
                    previous.get("lastSuccessfulCatalogDigest") or ""
                )
                baseline_committed_at = int(
                    previous.get("lastSuccessfulCatalogCommittedAtMs") or 0
                )
                submitted_digest = _digest(catalog_digest)
                if succeeded and not submitted_digest:
                    raise ValueError(
                        "successful catalog consolidation requires a committed digest"
                    )
                resolved_digest = submitted_digest if succeeded else baseline_digest
                resolved_run_id = _run_id(curation_run_id) or str(
                    previous.get("curationRunId") or ""
                )
                bounded_error = _error(error) if not succeeded else ""
                receipt_id = _receipt_id()
                deleted = conn.execute(
                    """
                    DELETE FROM memory_catalog_consolidation_leases
                    WHERE project = ? AND owner_token = ?
                      AND receipt_id = ? AND lease_expires_at_ms > ?
                    """,
                    (
                        normalized_project,
                        token,
                        str(lease["receipt_id"]),
                        current,
                    ),
                )
                if deleted.rowcount != 1:
                    raise RuntimeError(
                        "catalog consolidation lease changed before completion"
                    )
                self._insert_receipt(
                    conn,
                    receipt_id=receipt_id,
                    project=normalized_project,
                    state="completed" if succeeded else "failed",
                    last_attempt_at_ms=int(
                        previous.get("lastAttemptAtMs") or current
                    ),
                    last_completion_at_ms=current,
                    next_due_at_ms=next_due,
                    catalog_digest=resolved_digest,
                    curation_run_id=resolved_run_id,
                    attempt_count=max(1, int(previous.get("attemptCount") or 0)),
                    retry_count=retry_count,
                    result=_bounded_result(result or {}),
                    error=bounded_error,
                    current_ms=current,
                    admission_token=token,
                    lease_expires_at_ms=0,
                    last_successful_catalog_digest=(
                        submitted_digest if succeeded else baseline_digest
                    ),
                    last_successful_catalog_committed_at_ms=(
                        current if succeeded else baseline_committed_at
                    ),
                )
                conn.commit()
                return self.status(normalized_project, current_ms=current)

    def fail(
        self,
        project: str,
        *,
        admission_token: str | None = None,
        catalog_digest: str = "",
        result: Mapping[str, object] | None = None,
        curation_run_id: str = "",
        error: str = "",
        cadence_days: int = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS,
        current_ms: int | None = None,
    ) -> dict[str, object]:
        """Explicitly fail the current lease-owned catalog run."""

        return self.complete(
            project,
            catalog_digest=catalog_digest,
            result=result,
            curation_run_id=curation_run_id,
            ok=False,
            error=error,
            cadence_days=cadence_days,
            admission_token=admission_token,
            current_ms=current_ms,
        )

    def _insert_receipt(
        self,
        conn: sqlite3.Connection,
        *,
        receipt_id: str,
        project: str,
        state: str,
        last_attempt_at_ms: int,
        last_completion_at_ms: int,
        next_due_at_ms: int,
        catalog_digest: str,
        curation_run_id: str,
        attempt_count: int,
        retry_count: int,
        result: Mapping[str, object],
        error: str,
        current_ms: int,
        admission_token: str,
        lease_expires_at_ms: int,
        last_successful_catalog_digest: str,
        last_successful_catalog_committed_at_ms: int,
    ) -> None:
        result_payload = _bounded_result(result)
        conn.execute(
            """
            INSERT INTO memory_catalog_consolidation_receipts(
                receipt_id, project, state, last_attempt_at_ms,
                last_completion_at_ms, next_due_at_ms, catalog_digest,
                curation_run_id, attempt_count, retry_count, result_json,
                error, created_at_ms, updated_at_ms, admission_token,
                lease_expires_at_ms, last_successful_catalog_digest,
                last_successful_catalog_committed_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                project,
                state,
                max(0, int(last_attempt_at_ms)),
                max(0, int(last_completion_at_ms)),
                max(0, int(next_due_at_ms)),
                _digest(catalog_digest),
                _run_id(curation_run_id),
                max(0, int(attempt_count)),
                max(0, int(retry_count)),
                json.dumps(
                    result_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                _error(error),
                max(0, int(current_ms)),
                max(0, int(current_ms)),
                _token_for_storage(admission_token),
                max(0, int(lease_expires_at_ms)),
                _digest(last_successful_catalog_digest),
                max(0, int(last_successful_catalog_committed_at_ms)),
            ),
        )

    def _status_from_connection(
        self,
        conn: sqlite3.Connection,
        project: str,
        *,
        current_ms: int,
    ) -> dict[str, object]:
        row = conn.execute(
            """
            SELECT r.receipt_sequence, r.receipt_id, r.project, r.state,
                   r.last_attempt_at_ms, r.last_completion_at_ms,
                   r.next_due_at_ms, r.catalog_digest, r.curation_run_id,
                   r.attempt_count, r.retry_count, r.result_json, r.error,
                   r.created_at_ms, r.updated_at_ms,
                   r.admission_token, r.lease_expires_at_ms,
                   r.last_successful_catalog_digest,
                   r.last_successful_catalog_committed_at_ms,
                   l.owner_token AS live_owner_token,
                   l.receipt_id AS live_receipt_id,
                   l.lease_expires_at_ms AS live_lease_expires_at_ms
            FROM memory_catalog_consolidation_receipts r
            LEFT JOIN memory_catalog_consolidation_leases l
              ON l.project = r.project
            WHERE r.project = ?
            ORDER BY r.receipt_sequence DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()
        if row is None:
            return _empty_status(project, current_ms=current_ms)
        successful = conn.execute(
            """
            SELECT catalog_digest, last_completion_at_ms,
                   last_successful_catalog_digest,
                   last_successful_catalog_committed_at_ms
            FROM memory_catalog_consolidation_receipts
            WHERE project = ? AND state = 'completed'
              AND (
                  catalog_digest <> ''
                  OR last_successful_catalog_digest <> ''
              )
            ORDER BY receipt_sequence DESC
            LIMIT 1
            """,
            (project,),
        ).fetchone()
        return _status_from_row(
            row,
            current_ms=current_ms,
            successful_row=successful,
        )

    def _require_live_lease(
        self,
        conn: sqlite3.Connection,
        *,
        project: str,
        previous: Mapping[str, object],
        admission_token: str,
        current_ms: int,
    ) -> sqlite3.Row:
        if str(previous.get("state") or "") != "running":
            raise RuntimeError(
                "catalog consolidation transition requires a running admission"
            )
        lease = conn.execute(
            """
            SELECT project, owner_token, receipt_id, lease_expires_at_ms
            FROM memory_catalog_consolidation_leases
            WHERE project = ?
            """,
            (project,),
        ).fetchone()
        if (
            lease is None
            or str(lease["owner_token"] or "") != admission_token
            or str(lease["receipt_id"] or "")
            != str(previous.get("receiptId") or "")
            or int(lease["lease_expires_at_ms"] or 0) <= current_ms
        ):
            raise RuntimeError(
                "catalog consolidation admission token is not the live lease owner"
            )
        return lease

    def _extend_lease(
        self,
        conn: sqlite3.Connection,
        *,
        project: str,
        owner_token: str,
        previous_receipt_id: str,
        receipt_id: str,
        lease_expires_at_ms: int,
        current_ms: int,
    ) -> None:
        updated = conn.execute(
            """
            UPDATE memory_catalog_consolidation_leases
            SET receipt_id = ?, lease_expires_at_ms = ?, updated_at_ms = ?
            WHERE project = ? AND owner_token = ? AND receipt_id = ?
              AND lease_expires_at_ms > ?
            """,
            (
                receipt_id,
                lease_expires_at_ms,
                current_ms,
                project,
                owner_token,
                previous_receipt_id,
                current_ms,
            ),
        )
        if updated.rowcount != 1:
            raise RuntimeError(
                "catalog consolidation lease changed before digest recording"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self, value: int | None) -> int:
        return max(0, int(self._clock_ms() if value is None else value))



def _project(value: object) -> str:
    return compact_whitespace(str(value or ""))[:240]


def _digest(value: object) -> str:
    return compact_whitespace(str(value or ""))[:240]


def _run_id(value: object) -> str:
    return compact_whitespace(str(value or ""))[:240]


def _error(value: object) -> str:
    return compact_whitespace(str(value or ""))[:MAX_CATALOG_CONSOLIDATION_ERROR_CHARS]


def _cadence_days(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_CATALOG_CONSOLIDATION_CADENCE_DAYS
    return max(MIN_CATALOG_CONSOLIDATION_CADENCE_DAYS, min(MAX_CATALOG_CONSOLIDATION_CADENCE_DAYS, parsed))


def _retry_backoff_ms(retry_count: int) -> int:
    count = max(1, min(int(retry_count), 16))
    return min(CATALOG_CONSOLIDATION_RETRY_MAX_MS, CATALOG_CONSOLIDATION_RETRY_BASE_MS * (2 ** (count - 1)))


def _bounded_result(value: Mapping[str, object] | object) -> dict[str, object]:
    if isinstance(value, Mapping):
        candidate = dict(value)
    else:
        candidate = {"value": compact_whitespace(str(value or ""))[:MAX_CATALOG_CONSOLIDATION_ERROR_CHARS]}
    try:
        encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        encoded = json.dumps({"value": compact_whitespace(str(candidate))[:MAX_CATALOG_CONSOLIDATION_ERROR_CHARS]}, ensure_ascii=False)
    if len(encoded.encode("utf-8")) <= MAX_CATALOG_CONSOLIDATION_RESULT_BYTES:
        return candidate
    return {
        "schemaVersion": CATALOG_CONSOLIDATION_SCHEMA_VERSION,
        "truncated": True,
        "summary": compact_whitespace(encoded)[:MAX_CATALOG_CONSOLIDATION_ERROR_CHARS],
    }


def _empty_status(project: str, *, current_ms: int) -> dict[str, object]:
    return {
        "schemaVersion": CATALOG_CONSOLIDATION_SCHEMA_VERSION,
        "project": project,
        "receiptId": "",
        "state": "never",
        "lastAttemptAtMs": 0,
        "lastCompletionAtMs": 0,
        "nextDueAtMs": 0,
        "catalogDigest": "",
        "lastSuccessfulCatalogDigest": "",
        "lastSuccessfulCatalogCommittedAtMs": 0,
        "attemptCatalogDigest": "",
        "curationRunId": "",
        "attemptCount": 0,
        "retryCount": 0,
        "result": {},
        "error": "",
        "createdAtMs": 0,
        "updatedAtMs": 0,
        "leaseExpiresAtMs": 0,
        "due": True,
        "dueReason": "first_run",
        "observedAtMs": current_ms,
    }


def _status_from_row(
    row: sqlite3.Row,
    *,
    current_ms: int,
    successful_row: sqlite3.Row | None = None,
) -> dict[str, object]:
    try:
        decoded = json.loads(str(row["result_json"] or "{}"))
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    result = dict(decoded) if isinstance(decoded, Mapping) else {}
    state = str(row["state"] or "never")
    receipt_id = str(row["receipt_id"] or "")
    lease_receipt_id = str(row["live_receipt_id"] or "")
    lease_expires = (
        max(0, int(row["live_lease_expires_at_ms"] or 0))
        if state == "running" and lease_receipt_id == receipt_id
        else 0
    )
    if successful_row is not None:
        committed_digest = _digest(
            successful_row["last_successful_catalog_digest"]
            or successful_row["catalog_digest"]
        )
        committed_at = max(
            0,
            int(
                successful_row["last_successful_catalog_committed_at_ms"]
                or successful_row["last_completion_at_ms"]
                or 0
            ),
        )
    else:
        committed_digest = _digest(row["last_successful_catalog_digest"])
        committed_at = max(
            0,
            int(row["last_successful_catalog_committed_at_ms"] or 0),
        )
    next_due = max(0, int(row["next_due_at_ms"] or 0))
    if state == "running":
        due = lease_expires <= current_ms
    else:
        due = state == "never" or next_due <= current_ms
    due_reason = (
        "first_run"
        if state == "never"
        else "running"
        if state == "running" and not due
        else "lease_expired"
        if state == "running"
        else "retry_backoff"
        if state == "failed" and due
        else "scheduled"
        if state == "completed" and due
        else "not_due"
    )
    return {
        "schemaVersion": CATALOG_CONSOLIDATION_SCHEMA_VERSION,
        "project": str(row["project"] or ""),
        "receiptId": receipt_id,
        "state": state,
        "lastAttemptAtMs": max(0, int(row["last_attempt_at_ms"] or 0)),
        "lastCompletionAtMs": max(0, int(row["last_completion_at_ms"] or 0)),
        "nextDueAtMs": next_due,
        # ``catalogDigest`` is deliberately the last successful committed
        # digest.  A running attempt is exposed separately so it can never
        # qualify as the unchanged baseline.
        "catalogDigest": committed_digest,
        "lastSuccessfulCatalogDigest": committed_digest,
        "lastSuccessfulCatalogCommittedAtMs": committed_at,
        "attemptCatalogDigest": (
            _digest(row["catalog_digest"]) if state == "running" else ""
        ),
        "curationRunId": _run_id(row["curation_run_id"]),
        "attemptCount": max(0, int(row["attempt_count"] or 0)),
        "retryCount": max(0, int(row["retry_count"] or 0)),
        "result": result,
        "error": _error(row["error"]),
        "createdAtMs": max(0, int(row["created_at_ms"] or 0)),
        "updatedAtMs": max(0, int(row["updated_at_ms"] or 0)),
        "leaseExpiresAtMs": lease_expires,
        "due": due,
        "dueReason": due_reason,
        "observedAtMs": current_ms,
    }


def _due_reason(previous: Mapping[str, object]) -> str:
    state = str(previous.get("state") or "")
    if state == "failed":
        return "retry_backoff"
    if state == "completed":
        return "scheduled"
    if state == "running":
        return "lease_expired"
    return "first_run"


def _completed_due_at_ms(
    previous: Mapping[str, object],
    *,
    cadence_days: int,
) -> int:
    committed_at = max(
        0,
        int(previous.get("lastSuccessfulCatalogCommittedAtMs") or 0),
    )
    if not committed_at:
        committed_at = max(0, int(previous.get("lastCompletionAtMs") or 0))
    return committed_at + cadence_days * 24 * 60 * 60 * 1_000


def _admission_status(
    previous: Mapping[str, object],
    *,
    cadence_days: int,
    current_ms: int,
) -> dict[str, object]:
    if str(previous.get("state") or "") != "completed":
        return dict(previous)
    next_due = _completed_due_at_ms(previous, cadence_days=cadence_days)
    projected = dict(previous)
    projected["nextDueAtMs"] = next_due
    projected["due"] = next_due <= current_ms
    projected["dueReason"] = "scheduled" if next_due <= current_ms else "not_due"
    return projected



def _decision(
    project: str,
    status: Mapping[str, object],
    *,
    due: bool,
    admitted: bool,
    skipped: bool,
    reason: str,
    admission_token: str | None = None,
) -> dict[str, object]:
    decision: dict[str, object] = {
        "schemaVersion": CATALOG_CONSOLIDATION_SCHEMA_VERSION,
        "project": project,
        "due": bool(due),
        "admitted": bool(admitted),
        "skipped": bool(skipped),
        "reason": reason,
        "status": dict(status),
    }
    # Never put a token on skipped, duplicate, or not-due decisions.
    if admitted:
        token = _required_token(admission_token)
        decision["admissionToken"] = token
    return decision


def _receipt_id() -> str:
    return f"memory-catalog-consolidation:{uuid.uuid4()}"


def _new_admission_token() -> str:
    return secrets.token_urlsafe(32)


def _required_token(value: object) -> str:
    token = str(value or "").strip()
    if not token or len(token) > 240 or any(character.isspace() for character in token):
        raise RuntimeError(
            "catalog consolidation transition requires an admission token"
        )
    return token


def _token_for_storage(value: object) -> str:
    token = str(value or "").strip()
    return token[:240]
