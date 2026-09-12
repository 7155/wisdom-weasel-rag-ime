"""Leased, resumable *projection* jobs using the existing maintenance journal.

Only daily-report and retrieval-projection refreshes are replayed. This module
never retries a model call, governance apply, or an operation of unknown effect.
The host/CLI calls run_one periodically; no hidden background thread is started.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from .common import (LifecycleError, canonical_json, connect, digest, identifier,
                     load_json, now_ms, require_schema, row_dicts, transaction)
from .daily import snapshot

RETRY_DELAYS_MS = (15 * 60_000, 60 * 60_000)
OPERATIONS = frozenset({"daily_report", "retrieval_projection"})


class LostLease(RuntimeError):
    pass


def failure_code(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, HTTPError):
        return ("provider_temporary", True) if exc.code in {429, 500, 502, 503, 504} else ("provider_rejected", False)
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "transport_temporary", True
    if isinstance(exc, sqlite3.OperationalError) and any(x in str(exc).lower() for x in ("locked", "busy")):
        return "database_busy", True
    if isinstance(exc, LifecycleError):
        return "invalid_or_stale_input", False
    if isinstance(exc, PermissionError):
        return "permission_denied", False
    return "refresh_failed", False


def _build_input(conn: sqlite3.Connection, request: Mapping[str, Any]) -> dict[str, Any]:
    if request["operation"] == "daily_report":
        value = snapshot(conn, project=request["project"], day=request["date"], timezone=request["timezone"])
        return {"inputDigest": value["inputDigest"], "sourceCursor": value["sourceCursor"]}
    # The owning rebuild is global; freeze every available canonical input,
    # not just Atom text. Tags, deletes and books can change an index too.
    dependencies = (
        "input_events", "memory_state", "memory_items", "memory_atoms", "memory_books",
        "memory_aliases", "memory_item_tags", "memory_atom_tags", "memory_tags",
        "memory_tombstones", "agent_memory_evidence", "memory_evidence_input_event_links",
        "memory_relations", "memory_relation_sources", "memory_entities",
    )
    available = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    hasher = hashlib.sha256()
    counts = {}
    for table in dependencies:
        if table not in available:
            continue
        info = list(conn.execute(f"PRAGMA table_info({table})"))
        names = [row[1] for row in info]
        primary = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]] or names
        order = ','.join('"' + key.replace('"', '""') + '"' for key in primary)
        hasher.update(canonical_json([table, names]).encode())
        count = 0
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
            hasher.update(b"\n")
            hasher.update(canonical_json(list(row)).encode())
            count += 1
        counts[table] = count
    return {"inputDigest": hasher.hexdigest(), "sourceCursor": {"tableRowCounts": counts}}


def _execute(conn: sqlite3.Connection, request: Mapping[str, Any]) -> dict[str, Any]:
    if request["operation"] == "daily_report":
        # Validation/materialization readiness only. Reports are generated on
        # read so private text is never copied into durable job receipts.
        return {"ok": True, "reportReady": True}
    from ..retrieval_docs import rebuild_retrieval_docs
    report = rebuild_retrieval_docs(conn, project="")
    return {"ok": True, "retrievalDocCount": int(report.get("docCount") or 0)}


class RefreshJobs:
    def __init__(self, db_path: str | Path, *, clock: Callable[[], int] = now_ms,
                 build_input: Callable[..., dict[str, Any]] = _build_input,
                 execute: Callable[..., dict[str, Any]] = _execute, lease_ms: int = 120_000) -> None:
        self.db_path = Path(db_path)
        self.clock = clock
        self.build_input = build_input
        self.execute = execute
        if not 1000 <= lease_ms <= 3_600_000:
            raise LifecycleError("invalid_lease_duration")
        self.lease_ms = lease_ms

    def submit(self, *, operation: str, project: str, day: str = "", timezone: str = "UTC", scheduled: bool = False) -> dict[str, Any]:
        if scheduled and operation != "daily_report":
            raise LifecycleError("only_daily_reports_are_scheduled")
        if operation not in OPERATIONS:
            raise LifecycleError("unsupported_refresh_operation")
        identifier(project, field="project", allow_empty=True)
        request = {"operation": operation, "project": project, "date": day, "timezone": timezone,
                   "lifecycleConsumer": True, "scheduledDaily": scheduled}
        with connect(self.db_path) as conn, transaction(conn):
            require_schema(conn)
            schedule_key = digest([project, day, timezone]) if scheduled else None
            if schedule_key:
                existing = conn.execute("SELECT job_id FROM memory_refresh_checkpoints WHERE schedule_key=?", (schedule_key,)).fetchone()
                if existing:
                    return {**self._status(conn, existing[0]), "reused": True}
            frozen = self.build_input(conn, request)
            batch_id = digest([request, frozen["inputDigest"]])
            job_id = "memory-refresh:" + batch_id
            existing = conn.execute("SELECT 1 FROM memory_refresh_checkpoints WHERE job_id=?", (job_id,)).fetchone()
            if existing:
                return {**self._status(conn, job_id), "reused": True}
            at = self.clock()
            conn.execute("""INSERT INTO memory_maintenance_jobs(job_id,state,request_json,result_json,
                progress_json,error,created_at_ms,updated_at_ms,completed_at_ms) VALUES (?,'queued',?,'{}','{}','',?,?,0)""",
                (job_id, canonical_json(request), at, at))
            conn.execute("""INSERT INTO memory_refresh_checkpoints(job_id,operation,batch_id,input_digest,
                source_cursor_json,next_attempt_at_ms,created_at_ms,updated_at_ms,schedule_key) VALUES (?,?,?,?,?,?,?,?,?)""",
                (job_id, operation, batch_id, frozen["inputDigest"], canonical_json(frozen["sourceCursor"]), at, at, at, schedule_key))
            return {**self._status(conn, job_id), "reused": False}

    def status(self, job_id: str) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            return self._status(conn, identifier(job_id))

    def _status(self, conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
        rows = row_dicts(conn.execute("""SELECT j.*,c.batch_id,c.input_digest,c.source_cursor_json,
            c.attempts,c.consecutive_failures,c.next_attempt_at_ms,c.last_error_code,c.last_success_at_ms
            FROM memory_maintenance_jobs j JOIN memory_refresh_checkpoints c USING(job_id) WHERE j.job_id=?""", (job_id,)))
        if not rows:
            raise LifecycleError("refresh_job_not_found")
        row = rows[0]
        try:
            current = self.build_input(conn, load_json(row["request_json"]))
            source_changed = current["inputDigest"] != row["input_digest"]
        except Exception:
            source_changed = None
        return {"schemaVersion": "paw.memory-refresh-job.v1", "ok": True, "jobId": job_id,
            "state": row["state"], "request": load_json(row["request_json"]),
            "batchId": row["batch_id"], "inputDigest": row["input_digest"],
            "sourceCursor": load_json(row["source_cursor_json"]), "attemptCount": row["attempts"],
            "consecutiveFailures": row["consecutive_failures"], "nextAttemptAtMs": row["next_attempt_at_ms"],
            "lastErrorCode": row["last_error_code"], "lastSuccessAtMs": row["last_success_at_ms"],
            "result": load_json(row["result_json"]), "mayContinue": row["state"] in {"paused", "retry_wait"},
            "requiresRefresh": row["state"] == "stale" or source_changed is True,
            "freshness": {"sourceChanged": source_changed, "lastSuccessAtMs": row["last_success_at_ms"]}}

    def claim(self) -> dict[str, Any] | None:
        with connect(self.db_path) as conn, transaction(conn):
            at = self.clock()
            # A crashed attempt counts toward the same finite retry budget.
            expired = row_dicts(conn.execute("""SELECT c.job_id,c.consecutive_failures FROM memory_refresh_checkpoints c
                JOIN memory_maintenance_jobs j USING(job_id) WHERE j.state='running' AND c.lease_expires_at_ms<=?""", (at,)))
            for row in expired:
                self._fail_locked(conn, row["job_id"], "worker_interrupted", True, at)
            rows = row_dicts(conn.execute("""SELECT j.job_id,j.request_json,c.input_digest,c.source_cursor_json
                FROM memory_refresh_checkpoints c JOIN memory_maintenance_jobs j USING(job_id)
                WHERE j.state IN ('queued','retry_wait') AND c.next_attempt_at_ms<=?
                ORDER BY c.next_attempt_at_ms,c.created_at_ms,c.job_id LIMIT 1""", (at,)))
            if not rows:
                return None
            row = rows[0]
            token = uuid.uuid4().hex
            conn.execute("UPDATE memory_maintenance_jobs SET state='running',updated_at_ms=?,completed_at_ms=0 WHERE job_id=?", (at, row["job_id"]))
            conn.execute("""UPDATE memory_refresh_checkpoints SET attempts=attempts+1,lease_token=?,lease_expires_at_ms=?,updated_at_ms=?
                WHERE job_id=?""", (token, at + self.lease_ms, at, row["job_id"]))
            return {"jobId": row["job_id"], "leaseToken": token, "request": load_json(row["request_json"]),
                    "inputDigest": row["input_digest"], "sourceCursor": load_json(row["source_cursor_json"])}

    def run_one(self) -> dict[str, Any] | None:
        claim = self.claim()
        if claim is None:
            return None
        return self.run_claim(claim)

    def run_claim(self, claim: Mapping[str, Any]) -> dict[str, Any]:
        job_id = claim["jobId"]
        try:
            # Projection writes, input validation and fenced completion are one
            # SQLite transaction. No network/model call is allowed in this path.
            with connect(self.db_path) as conn, transaction(conn):
                self._assert_lease(conn, claim, check_expiry=True)
                request = load_json(conn.execute("SELECT request_json FROM memory_maintenance_jobs WHERE job_id=?", (job_id,)).fetchone()[0])
                frozen = conn.execute("SELECT input_digest FROM memory_refresh_checkpoints WHERE job_id=?", (job_id,)).fetchone()[0]
                current = self.build_input(conn, request)
                if current["inputDigest"] != frozen:
                    conn.execute("UPDATE memory_maintenance_jobs SET state='stale',error='source_revision_changed',updated_at_ms=? WHERE job_id=?", (self.clock(), job_id))
                    conn.execute("UPDATE memory_refresh_checkpoints SET lease_token='',lease_expires_at_ms=0,next_attempt_at_ms=0,last_error_code='source_revision_changed',updated_at_ms=? WHERE job_id=?", (self.clock(), job_id))
                else:
                    result = self.execute(conn, request)
                    if result.get("ok") is not True:
                        raise LifecycleError("refresh_returned_failure")
                    # Persist only bounded, content-free acknowledgements.
                    receipt = {k: result[k] for k in ("ok", "reportReady", "retrievalDocCount") if k in result}
                    for key, value in receipt.items():
                        if key in {"ok", "reportReady"} and type(value) is not bool or key == "retrievalDocCount" and type(value) is not int:
                            raise LifecycleError("invalid_refresh_receipt")
                    self._assert_lease(conn, claim, check_expiry=False)
                    at = self.clock()
                    conn.execute("UPDATE memory_maintenance_jobs SET state='completed',result_json=?,error='',updated_at_ms=?,completed_at_ms=? WHERE job_id=?", (canonical_json(receipt), at, at, job_id))
                    conn.execute("UPDATE memory_refresh_checkpoints SET lease_token='',lease_expires_at_ms=0,next_attempt_at_ms=0,last_error_code='',last_success_at_ms=?,updated_at_ms=? WHERE job_id=?", (at, at, job_id))
        except LostLease:
            raise
        except Exception as exc:
            code, retryable = failure_code(exc)
            with connect(self.db_path) as conn, transaction(conn):
                self._assert_lease(conn, claim, check_expiry=False)
                self._fail_locked(conn, job_id, code, retryable, self.clock())
        return self.status(job_id)

    def _assert_lease(self, conn: sqlite3.Connection, claim: Mapping[str, Any], *, check_expiry: bool) -> None:
        row = conn.execute("""SELECT j.state,c.lease_token,c.lease_expires_at_ms FROM memory_maintenance_jobs j
            JOIN memory_refresh_checkpoints c USING(job_id) WHERE j.job_id=?""", (claim["jobId"],)).fetchone()
        # A token, not a process-local mutex or just a timestamp, fences late workers.
        if not row or row[0] != "running" or row[1] != claim["leaseToken"] or (check_expiry and row[2] <= self.clock()):
            raise LostLease("refresh_lease_lost")
        # A SQLite writer cannot be overtaken while its transaction is active.
        # Completion remains fenced by the token if computation spans expiry.

    @staticmethod
    def _fail_locked(conn: sqlite3.Connection, job_id: str, code: str, retryable: bool, at: int) -> None:
        failures = int(conn.execute("SELECT consecutive_failures FROM memory_refresh_checkpoints WHERE job_id=?", (job_id,)).fetchone()[0]) + 1
        retry = retryable and failures <= len(RETRY_DELAYS_MS)
        state = "retry_wait" if retry else "paused"
        next_at = at + RETRY_DELAYS_MS[failures - 1] if retry else 0
        conn.execute("UPDATE memory_maintenance_jobs SET state=?,error=?,updated_at_ms=?,completed_at_ms=? WHERE job_id=?", (state, code, at, 0 if retry else at, job_id))
        conn.execute("""UPDATE memory_refresh_checkpoints SET consecutive_failures=?,next_attempt_at_ms=?,
            lease_token='',lease_expires_at_ms=0,last_error_code=?,updated_at_ms=? WHERE job_id=?""", (failures, next_at, code, at, job_id))

    def continue_job(self, job_id: str) -> dict[str, Any]:
        """Explicitly resume the SAME batch. Never silently read a new batch."""
        with connect(self.db_path) as conn, transaction(conn):
            status = self._status(conn, job_id)
            if status["state"] not in {"paused", "retry_wait"}:
                raise LifecycleError("job_cannot_continue")
            current = self.build_input(conn, status["request"])
            if current["inputDigest"] != status["inputDigest"]:
                raise LifecycleError("frozen_input_changed_refresh_required")
            at = self.clock()
            conn.execute("UPDATE memory_maintenance_jobs SET state='queued',updated_at_ms=?,completed_at_ms=0 WHERE job_id=?", (at, job_id))
            conn.execute("UPDATE memory_refresh_checkpoints SET consecutive_failures=0,next_attempt_at_ms=?,updated_at_ms=? WHERE job_id=?", (at, at, job_id))
            return self._status(conn, job_id)


class RefreshWorker:
    """Small process-owned consumer for the durable refresh queue.

    ``RefreshJobs`` deliberately owns leases and retry state, while this class
    only provides liveness.  A crashed worker can be replaced by another
    Gateway process; no in-memory job state is authoritative.
    """

    def __init__(self, jobs: RefreshJobs, *, poll_interval_s: float = 1.0) -> None:
        if not 0.05 <= float(poll_interval_s) <= 60.0:
            raise LifecycleError("invalid_refresh_worker_interval")
        self.jobs = jobs
        self.poll_interval_s = float(poll_interval_s)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="paw-memory-refresh-worker",
                daemon=True,
            )
            self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, *, timeout_s: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout_s)))
        with self._lock:
            if thread is self._thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.jobs.run_one()
            except LostLease:
                # Another worker fenced this attempt.  Continue polling; the
                # durable state is already the source of truth.
                pass
            except Exception:
                # RefreshJobs records operation failures itself.  An
                # unexpected queue/SQLite error must not kill the consumer or
                # create a tight retry loop; the next tick can recover it.
                time.sleep(min(self.poll_interval_s, 1.0))
            self._wake.wait(timeout=self.poll_interval_s)
            self._wake.clear()
