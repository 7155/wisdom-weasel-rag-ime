from __future__ import annotations

import codecs
import hashlib
import os
import selectors
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .agent_workspace import (
    PreparedWorkspaceCommand,
    SpawnedWorkspaceCommand,
    WorkspaceHarness,
)
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations, sqlite_connection
from .room_runtime_host_kill_gate import _process_identity, _signal_process_group


class AgentBackgroundJobError(RuntimeError):
    pass


EventPublisher = Callable[..., object]
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "orphaned"})
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})
_MAX_ACTIVE_JOBS_PER_SESSION = 8
_MAX_LOG_BYTES = 4 * 1024 * 1024
_LOG_TRIM_TRIGGER_BYTES = _MAX_LOG_BYTES + 512 * 1024
_MAX_LOG_READ_BYTES = 128 * 1024
_PROGRESS_INTERVAL_SECONDS = 0.75


@dataclass
class _LiveJob:
    launched: SpawnedWorkspaceCommand
    log_path: Path
    max_run_seconds: int
    thread: threading.Thread | None = None
    output_bytes: int = 0
    log_start_cursor: int = 0
    log_truncated: bool = False
    last_progress_at: float = 0.0
    last_persisted_at: float = 0.0


class AgentBackgroundJobService:
    """Authoritative, session-scoped owner for governed background commands."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        events: EventPublisher,
        workspace_harness: WorkspaceHarness | None = None,
        log_root: str | Path | None = None,
        execution_owner: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.events = events
        self.workspace_harness = workspace_harness or WorkspaceHarness()
        self.log_root = Path(log_root) if log_root is not None else self.db_path.parent / "BackgroundJobs"
        self.execution_owner = bool(execution_owner)
        self._lock = threading.RLock()
        self._live: dict[str, _LiveJob] = {}
        self._closed = False

    def initialize(self) -> None:
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            apply_database_migrations(conn)
            active_rows = (
                conn.execute(
                    """
                    SELECT *
                    FROM agent_background_jobs
                    WHERE status IN ('queued', 'running', 'cancelling')
                    ORDER BY created_at_ms, job_id
                    """
                ).fetchall()
                if self.execution_owner
                else []
            )
        for row in active_rows:
            recovery_error = self._recover_persisted_process_group(row)
            now_ms = _now_ms()
            with sqlite_connection(self.db_path, foreign_keys=True) as conn:
                if recovery_error:
                    existing_error = str(row["error"] or "").strip()
                    detail = f"background_job_recovery_failed: {recovery_error}"
                    conn.execute(
                        """
                        UPDATE agent_background_jobs
                        SET status = 'cancelling',
                            updated_at_ms = ?,
                            ended_at_ms = 0,
                            error = ?
                        WHERE job_id = ?
                          AND status IN ('queued', 'running', 'cancelling')
                        """,
                        (
                            now_ms,
                            (
                                f"{existing_error}; {detail}"
                                if existing_error
                                else detail
                            )[:500],
                            str(row["job_id"]),
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE agent_background_jobs
                        SET status = 'orphaned',
                            updated_at_ms = ?,
                            ended_at_ms = CASE
                                WHEN ended_at_ms = 0 THEN ?
                                ELSE ended_at_ms
                            END,
                            error = CASE
                                WHEN error = '' THEN
                                    '后台任务宿主异常退出，进程组已清理且无法重新接管'
                                ELSE error
                            END
                        WHERE job_id = ?
                          AND status IN ('queued', 'running', 'cancelling')
                        """,
                        (now_ms, now_ms, str(row["job_id"])),
                    )
        self._ensure_log_root()

    def _recover_persisted_process_group(
        self,
        row: Mapping[str, object],
    ) -> str:
        self._require_execution_owner()
        pid = int(row["pid"]) if row["pid"] is not None else 0
        process_group_id = (
            int(row["process_group_id"])
            if row["process_group_id"] is not None
            else 0
        )
        birth_token = str(row["process_birth_token"] or "")
        if pid <= 0 or process_group_id <= 0:
            return "persisted process identity is incomplete"
        if not _process_group_exists(process_group_id):
            return ""
        if not birth_token:
            return "persisted process birth token is unavailable"
        if process_group_id == os.getpgrp():
            return "persisted process group is the current owner group"
        observed = _process_identity(pid)
        expected = (process_group_id, birth_token)
        if observed != expected:
            return "persisted process identity no longer matches the live group"
        try:
            _signal_process_group(process_group_id)
        except (OSError, ProcessLookupError) as exc:
            if not _process_group_exists(process_group_id):
                return ""
            return f"process-group signal failed: {_public_error(exc)}"
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not _process_group_exists(process_group_id):
                return ""
            time.sleep(0.02)
        return "process group remained live after owner recovery signal"

    def start(
        self,
        session_id: str,
        prepared: PreparedWorkspaceCommand,
        *,
        label: object = "",
        approval_id: str = "",
        causal_metadata: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self._require_execution_owner()
        with self._lock:
            if self._closed:
                raise AgentBackgroundJobError("background job service is closed")
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_label = _job_label(label, prepared.command)
        job_id = f"bg_{uuid.uuid4().hex}"
        log_path = self._log_path(job_id)
        log_path.touch(mode=0o600, exist_ok=False)
        os.chmod(log_path, 0o600)
        now_ms = _now_ms()
        command_sha256 = hashlib.sha256(prepared.command.encode("utf-8")).hexdigest()
        try:
            with sqlite_connection(self.db_path, foreign_keys=True) as conn:
                conn.execute("BEGIN IMMEDIATE")
                causal = _job_causal_metadata(
                    conn,
                    session_id=session,
                    approval_id=str(approval_id or ""),
                    supplied=causal_metadata,
                )
                self._require_capacity(conn, session)
                self._require_live_causal_epoch(conn, session, causal)
                conn.execute(
                    """
                    INSERT INTO agent_background_jobs(
                        job_id,
                        session_id,
                        label,
                        status,
                        command,
                        command_sha256,
                        cwd,
                        network_allowed,
                        max_run_seconds,
                        log_path,
                        approval_id,
                        causal_plan_id,
                        causal_plan_revision,
                        causal_goal_id,
                        causal_goal_revision,
                        causal_turn_id,
                        room_bound,
                        created_at_ms,
                        updated_at_ms
                    ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        session,
                        normalized_label,
                        prepared.command,
                        command_sha256,
                        str(prepared.cwd),
                        int(prepared.allow_network),
                        prepared.timeout_seconds,
                        str(log_path),
                        str(approval_id or "")[:240],
                        causal["planId"],
                        causal["planRevision"],
                        causal["goalId"],
                        causal["goalRevision"],
                        causal["turnId"],
                        int(bool(causal["roomBound"])),
                        now_ms,
                        now_ms,
                    ),
                )
        except Exception:
            log_path.unlink(missing_ok=True)
            raise
        try:
            launched = self.workspace_harness.spawn_background(prepared)
        except Exception as exc:
            error = _public_error(exc)
            self._mark_launch_failed(job_id, error)
            job = self.status(session, job_id)["job"]
            try:
                self._publish("background_job_failed", job)
            except Exception:
                pass
            raise AgentBackgroundJobError(error) from exc

        live = _LiveJob(
            launched=launched,
            log_path=log_path,
            max_run_seconds=prepared.timeout_seconds,
        )
        identity = _process_identity(launched.process.pid)
        if identity is None:
            self._abort_launched_job(
                job_id,
                live,
                error="background job process identity is unavailable",
            )
            raise AgentBackgroundJobError(
                "background job process identity is unavailable"
            )
        process_group_id, process_birth_token = identity
        try:
            with self._lock:
                if self._closed:
                    raise AgentBackgroundJobError("background job service is closing")
                self._live[job_id] = live
            started_at_ms = _now_ms()
            with sqlite_connection(self.db_path, foreign_keys=True) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._require_live_causal_epoch(conn, session, causal)
                cursor = conn.execute(
                    """
                    UPDATE agent_background_jobs
                    SET status = 'running',
                        pid = ?,
                        process_group_id = ?,
                        process_birth_token = ?,
                        started_at_ms = ?,
                        updated_at_ms = ?
                    WHERE job_id = ? AND status = 'queued'
                    """,
                    (
                        launched.process.pid,
                        process_group_id,
                        process_birth_token,
                        started_at_ms,
                        started_at_ms,
                        job_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AgentBackgroundJobError(
                        "background job admission was cancelled before launch"
                    )
            job = self.status(session, job_id)["job"]
            self._publish("background_job_started", job)
            monitor = threading.Thread(
                target=self._monitor,
                args=(job_id,),
                name=f"rag-ime-background-job-{job_id[-8:]}",
                daemon=True,
            )
            live.thread = monitor
            monitor.start()
        except Exception as exc:
            error = _public_error(exc)
            self._abort_launched_job(job_id, live, error=error)
            try:
                job = self.status(session, job_id)["job"]
                self._publish("background_job_failed", job)
            except Exception:
                pass
            if isinstance(exc, AgentBackgroundJobError):
                raise
            raise AgentBackgroundJobError(error) from exc
        return {
            "schemaVersion": "rag-ime.agent-background-job-start-receipt.v1",
            "ok": True,
            "summary": f"后台任务《{normalized_label}》已启动",
            "job": job,
            "launchReceipt": {
                "jobId": job_id,
                "approvalId": str(approval_id or "")[:240],
                "commandSha256": command_sha256,
                "startedAtMs": started_at_ms,
            },
        }

    def list(
        self,
        session_id: str,
        *,
        limit: object = 50,
        status: object = "",
    ) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_limit = _bounded_int(limit, default=50, minimum=1, maximum=100)
        normalized_status = str(status or "").strip().lower()
        if normalized_status and normalized_status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
            raise AgentBackgroundJobError("unsupported background job status")
        where_status = " AND status = ?" if normalized_status else ""
        values: tuple[object, ...] = (
            (session, normalized_status, normalized_limit)
            if normalized_status
            else (session, normalized_limit)
        )
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM agent_background_jobs
                WHERE session_id = ?{where_status}
                ORDER BY
                    CASE status
                        WHEN 'running' THEN 0
                        WHEN 'cancelling' THEN 1
                        WHEN 'queued' THEN 2
                        ELSE 3
                    END,
                    updated_at_ms DESC,
                    created_at_ms DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
        items = [self._job_payload(row) for row in rows]
        return {
            "schemaVersion": "rag-ime.agent-background-job-list.v1",
            "ok": True,
            "sessionId": session,
            "items": items,
            "activeCount": sum(item["status"] in _ACTIVE_STATUSES for item in items),
        }

    def status(self, session_id: str, job_id: str) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_job_id = _job_id(job_id)
        row = self._row(session, normalized_job_id)
        return {
            "schemaVersion": "rag-ime.agent-background-job-status.v1",
            "ok": True,
            "job": self._job_payload(row),
        }

    def logs(
        self,
        session_id: str,
        job_id: str,
        *,
        cursor: object = 0,
        limit_bytes: object = 65_536,
    ) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_job_id = _job_id(job_id)
        row = self._row(session, normalized_job_id)
        requested_cursor = _bounded_int(cursor, default=0, minimum=0, maximum=2**63 - 1)
        normalized_limit = _bounded_int(
            limit_bytes,
            default=65_536,
            minimum=1,
            maximum=_MAX_LOG_READ_BYTES,
        )
        with self._lock:
            live = self._live.get(normalized_job_id)
            if live is None:
                row = self._row(session, normalized_job_id)
                start_cursor = int(row["log_start_cursor"] or 0)
            else:
                start_cursor = live.log_start_cursor
            path = self._safe_stored_log_path(
                str(row["log_path"] or ""),
                normalized_job_id,
            )
            actual_cursor = max(requested_cursor, start_cursor)
            byte_offset = max(0, actual_cursor - start_cursor)
            try:
                with path.open("rb") as handle:
                    handle.seek(byte_offset)
                    skipped_bytes = 0
                    first = handle.read(1)
                    while first and first[0] & 0xC0 == 0x80:
                        skipped_bytes += 1
                        first = handle.read(1)
                    actual_cursor += skipped_bytes
                    if first:
                        data = first + handle.read(normalized_limit - 1)
                        while True:
                            try:
                                decoded_text = data.decode("utf-8")
                                break
                            except UnicodeDecodeError as exc:
                                if exc.reason != "unexpected end of data":
                                    raise
                                continuation = handle.read(1)
                                if not continuation:
                                    raise
                                data += continuation
                    else:
                        data = b""
                        decoded_text = ""
                    has_more = bool(handle.read(1))
            except FileNotFoundError:
                data = b""
                decoded_text = ""
                has_more = False
        next_cursor = actual_cursor + len(data)
        return {
            "schemaVersion": "rag-ime.agent-background-job-log.v1",
            "ok": True,
            "jobId": normalized_job_id,
            "sessionId": session,
            "cursor": actual_cursor,
            "nextCursor": next_cursor,
            "logStartCursor": start_cursor,
            "truncatedBeforeCursor": requested_cursor < start_cursor,
            "hasMore": has_more,
            "text": decoded_text,
        }

    def cancel(
        self,
        session_id: str,
        job_id: str,
        *,
        reason: object = "user_requested",
    ) -> dict[str, object]:
        return self._cancel_owned(
            session_id,
            job_id,
            reason=reason,
            room_owner=False,
        )

    def cancel_room_owned(
        self,
        session_id: str,
        job_id: str,
        *,
        room_turn_id: str,
        reason: object = "room_root_cancelled",
    ) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_job_id = _job_id(job_id)
        root_id = _required_text(
            room_turn_id,
            field="roomTurnId",
            maximum=240,
        )
        row = self._row(session, normalized_job_id)
        if not bool(row["room_bound"]):
            raise AgentBackgroundJobError(
                "background job is not owned by a Room root"
            )
        if str(row["causal_turn_id"] or "") != root_id:
            raise AgentBackgroundJobError(
                "background job belongs to another Room root"
            )
        return self._cancel_owned(
            session,
            normalized_job_id,
            reason=reason,
            room_owner=True,
        )

    def cancel_room_root(
        self,
        session_id: str,
        *,
        room_turn_id: str,
        reason: object = "room_root_cancelled",
    ) -> list[dict[str, object]]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        root_id = _required_text(
            room_turn_id,
            field="roomTurnId",
            maximum=240,
        )
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            rows = conn.execute(
                """
                SELECT job_id
                FROM agent_background_jobs
                WHERE session_id = ?
                  AND room_bound = 1
                  AND causal_turn_id = ?
                  AND status IN ('queued', 'running', 'cancelling')
                ORDER BY created_at_ms, job_id
                """,
                (session, root_id),
            ).fetchall()
        if rows:
            self._require_execution_owner()
        return [
            self.cancel_room_owned(
                session,
                str(row[0]),
                room_turn_id=root_id,
                reason=reason,
            )
            for row in rows
        ]

    def cancel_room_root_all_sessions(
        self,
        *,
        room_turn_id: str,
        reason: object = "room_root_cancelled",
    ) -> list[dict[str, object]]:
        root_id = _required_text(
            room_turn_id,
            field="roomTurnId",
            maximum=240,
        )
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            rows = conn.execute(
                """
                SELECT session_id, job_id
                FROM agent_background_jobs
                WHERE room_bound = 1
                  AND causal_turn_id = ?
                  AND status IN ('queued', 'running', 'cancelling')
                ORDER BY created_at_ms, job_id
                """,
                (root_id,),
            ).fetchall()
        if rows:
            self._require_execution_owner()
        return [
            self.cancel_room_owned(
                str(row[0]),
                str(row[1]),
                room_turn_id=root_id,
                reason=reason,
            )
            for row in rows
        ]

    def _cancel_owned(
        self,
        session_id: str,
        job_id: str,
        *,
        reason: object,
        room_owner: bool,
    ) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_job_id = _job_id(job_id)
        normalized_reason = _bounded_text(reason, maximum=240) or "user_requested"
        before_row = self._row(session, normalized_job_id)
        before = self._job_payload(before_row)
        if bool(before_row["room_bound"]) and not room_owner:
            raise AgentBackgroundJobError(
                "Room-bound background jobs must be cancelled by the Room/Root owner"
            )
        if before["status"] in _TERMINAL_STATUSES:
            return {
                "schemaVersion": "rag-ime.agent-background-job-cancel-receipt.v1",
                "ok": True,
                "summary": "后台任务已经结束",
                "alreadyTerminal": True,
                "job": before,
            }
        self._require_execution_owner()
        requested_at_ms = _now_ms()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                """
                UPDATE agent_background_jobs
                SET status = 'cancelling',
                    cancel_requested_at_ms = ?,
                    updated_at_ms = ?,
                    error = ?
                WHERE job_id = ? AND session_id = ?
                  AND status IN ('queued', 'running')
                """,
                (
                    requested_at_ms,
                    requested_at_ms,
                    normalized_reason,
                    normalized_job_id,
                    session,
                ),
            )
        requested = self._job_payload(self._row(session, normalized_job_id))
        if requested["status"] in _TERMINAL_STATUSES:
            return {
                "schemaVersion": "rag-ime.agent-background-job-cancel-receipt.v1",
                "ok": True,
                "summary": "后台任务已经结束",
                "alreadyTerminal": True,
                "job": requested,
            }
        requested_at_ms = int(requested["cancelRequestedAtMs"])
        with self._lock:
            live = self._live.get(normalized_job_id)
        if live is not None:
            self.workspace_harness.terminate_background(live.launched)
            thread = live.thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        job = self.status(session, normalized_job_id)["job"]
        return {
            "schemaVersion": "rag-ime.agent-background-job-cancel-receipt.v1",
            "ok": True,
            "summary": (
                "后台任务已停止"
                if job["status"] == "cancelled"
                else "已请求停止后台任务"
            ),
            "alreadyTerminal": False,
            "job": job,
            "cancelReceipt": {
                "jobId": normalized_job_id,
                "requestedAtMs": requested_at_ms,
                "status": job["status"],
            },
        }

    def cancel_causal(
        self,
        session_id: str,
        *,
        request_id: str,
        scope_kind: str,
        scope_id: str,
        source_revision: int,
        reason: str,
    ) -> dict[str, object]:
        session = _required_text(session_id, field="sessionId", maximum=240)
        normalized_request_id = _required_text(
            request_id,
            field="requestId",
            maximum=240,
        )
        if scope_kind not in {"plan", "goal"}:
            raise AgentBackgroundJobError(
                "unsupported lifecycle cancellation scope"
            )
        causal_clause = (
            "causal_plan_id = ? AND causal_plan_revision = ?"
            if scope_kind == "plan"
            else "causal_goal_id = ?"
        )
        causal_values: tuple[object, ...] = (
            (scope_id, int(source_revision))
            if scope_kind == "plan"
            else (scope_id,)
        )
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            room_rows = conn.execute(
                f"""
                SELECT job_id
                FROM agent_background_jobs
                WHERE session_id = ? AND {causal_clause}
                  AND room_bound = 1
                  AND status IN ('queued', 'running', 'cancelling')
                ORDER BY created_at_ms, job_id
                """,
                (session, *causal_values),
            ).fetchall()
            rows = conn.execute(
                f"""
                SELECT job_id, status
                FROM agent_background_jobs
                WHERE session_id = ? AND room_bound = 0
                  AND (
                    ({causal_clause}
                     AND status IN ('queued', 'running', 'cancelling'))
                    OR lifecycle_cancel_request_id = ?
                  )
                ORDER BY created_at_ms, job_id
                """,
                (session, *causal_values, normalized_request_id),
            ).fetchall()
            active_ids = [
                str(row["job_id"])
                for row in rows
                if str(row["status"]) in _ACTIVE_STATUSES
            ]
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                conn.execute(
                    f"""
                    UPDATE agent_background_jobs
                    SET lifecycle_cancel_request_id = ?
                    WHERE session_id = ? AND job_id IN ({placeholders})
                      AND lifecycle_cancel_request_id IN ('', ?)
                    """,
                    (
                        normalized_request_id,
                        session,
                        *active_ids,
                        normalized_request_id,
                    ),
                )
        if active_ids:
            self._require_execution_owner()
        normalized_reason = _bounded_text(reason, maximum=240) or "lifecycle_cancelled"
        for job_id in active_ids:
            self.cancel(session, job_id, reason=normalized_reason)
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            cancelled_rows = conn.execute(
                """
                SELECT job_id, status
                FROM agent_background_jobs
                WHERE session_id = ? AND lifecycle_cancel_request_id = ?
                ORDER BY created_at_ms, job_id
                """,
                (session, normalized_request_id),
            ).fetchall()
        return {
            "schemaVersion": "rag-ime.agent-background-job-lifecycle-cancellation-summary.v1",
            "requestId": normalized_request_id,
            "sessionId": session,
            "scopeKind": scope_kind,
            "scopeId": scope_id,
            "sourceRevision": int(source_revision),
            "jobs": [
                {
                    "jobId": str(row["job_id"]),
                    "status": str(row["status"]),
                }
                for row in cancelled_rows
            ],
            "excludedRoomBoundJobIds": [
                str(row["job_id"])
                for row in room_rows
            ],
        }

    def cancel_session(self, session_id: str, *, reason: str) -> list[dict[str, object]]:
        active = self.list(session_id, limit=100)["items"]
        room_bound = [
            item
            for item in active
            if item["status"] in _ACTIVE_STATUSES
            and bool(item["causalMetadata"]["roomBound"])
        ]
        if room_bound:
            raise AgentBackgroundJobError(
                "Room-bound background jobs must be cancelled by the Room/Root owner"
            )
        if not self.execution_owner:
            if any(item["status"] in _ACTIVE_STATUSES for item in active):
                raise AgentBackgroundJobError(
                    "background jobs must be cancelled by the execution owner"
                )
            return []
        receipts: list[dict[str, object]] = []
        for item in active:
            if item["status"] not in _ACTIVE_STATUSES:
                continue
            receipts.append(self.cancel(session_id, str(item["jobId"]), reason=reason))
        return receipts

    def close(self) -> None:
        if not self.execution_owner:
            with self._lock:
                self._closed = True
            return
        with self._lock:
            if self._closed:
                return
            self._closed = True
            live_ids = list(self._live)
        for job_id in live_ids:
            try:
                row = self._row_for_job(job_id)
                self._cancel_owned(
                    str(row["session_id"]),
                    job_id,
                    reason="background_job_service_shutdown",
                    room_owner=True,
                )
            except Exception:
                continue

    def _monitor(self, job_id: str) -> None:
        with self._lock:
            live = self._live.get(job_id)
        if live is None:
            return
        process = live.launched.process
        output = process.stdout
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending_text = ""
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + live.max_run_seconds
        timed_out = False
        try:
            if output is not None:
                selector.register(output, selectors.EVENT_READ)
            while selector.get_map():
                if process.poll() is None and time.monotonic() >= deadline:
                    timed_out = True
                    self._request_timeout(job_id)
                    self._terminate_and_wait(live)
                events = selector.select(timeout=0.2)
                if not events and process.poll() is not None:
                    events = selector.select(timeout=0)
                    if not events:
                        break
                for key, _ in events:
                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    pending_text += decoder.decode(chunk)
                    pending_text = self._flush_complete_lines(live, pending_text)
                    self._persist_live_progress(job_id, live)
                if process.poll() is not None:
                    # A shell that exits must not leave an approved descendant
                    # running in the same process group with the log pipe open.
                    self._terminate_and_wait(live)
                    if not events:
                        break
            pending_text += decoder.decode(b"", final=True)
            if pending_text:
                self._append_redacted_text(live, pending_text)
            try:
                exit_code = process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._terminate_and_wait(live)
                exit_code = process.poll()
                if exit_code is None:
                    raise AgentBackgroundJobError(
                        "background job process group did not terminate"
                    )
            else:
                self._terminate_and_wait(live)
            self._persist_live_progress(job_id, live, force=True)
            row = self._row_for_job(job_id)
            cancelling = str(row["status"] or "") == "cancelling"
            if cancelling and not timed_out:
                status = "cancelled"
                event_type = "background_job_cancelled"
                error = str(row["error"] or "")
            elif timed_out:
                status = "failed"
                event_type = "background_job_failed"
                error = f"后台任务超过 {live.max_run_seconds} 秒运行上限"
            elif int(exit_code) == 0:
                status = "completed"
                event_type = "background_job_completed"
                error = ""
            else:
                status = "failed"
                event_type = "background_job_failed"
                error = f"后台任务退出码 {exit_code}"
            ended_at_ms = _now_ms()
            with sqlite_connection(self.db_path, foreign_keys=True) as conn:
                conn.execute(
                    """
                    UPDATE agent_background_jobs
                    SET status = ?,
                        exit_code = ?,
                        output_bytes = ?,
                        log_start_cursor = ?,
                        log_truncated = ?,
                        updated_at_ms = ?,
                        ended_at_ms = ?,
                        error = ?
                    WHERE job_id = ?
                    """,
                    (
                        status,
                        int(exit_code),
                        live.output_bytes,
                        live.log_start_cursor,
                        int(live.log_truncated),
                        ended_at_ms,
                        ended_at_ms,
                        error,
                        job_id,
                    ),
                )
            job = self._job_payload(self._row_for_job(job_id))
            try:
                self._publish(event_type, job)
            except Exception:
                pass
        except Exception as exc:
            error = _public_error(exc)
            self._terminate_and_wait(live)
            self._finalize_without_process(job_id, status="failed", error=error)
            try:
                job = self._job_payload(self._row_for_job(job_id))
                self._publish("background_job_failed", job)
            except Exception:
                pass
        finally:
            try:
                selector.close()
            except Exception:
                pass
            if output is not None:
                try:
                    output.close()
                except Exception:
                    pass
            try:
                live.launched.cleanup()
            except Exception:
                pass
            with self._lock:
                self._live.pop(job_id, None)

    def _flush_complete_lines(self, live: _LiveJob, text: str) -> str:
        last_newline = max(text.rfind("\n"), text.rfind("\r"))
        if last_newline >= 0:
            self._append_redacted_text(live, text[: last_newline + 1])
            text = text[last_newline + 1 :]
        if len(text) > 65_536:
            retain_from = len(text) - 1_024
            redacted = self.workspace_harness.redact_output(text)
            context_size = 1_024
            while retain_from > 0:
                redacted_suffix = self.workspace_harness.redact_output(text[retain_from:])
                if redacted.endswith(redacted_suffix):
                    prefix_length = len(redacted) - len(redacted_suffix)
                    self._append_redacted_text(live, redacted[:prefix_length])
                    return text[retain_from:]
                retain_from = max(0, retain_from - context_size)
                context_size *= 2
            return text
        return text

    def _append_redacted_text(self, live: _LiveJob, text: str) -> None:
        redacted = self.workspace_harness.redact_output(text)
        data = redacted.encode("utf-8")
        if not data:
            return
        with self._lock:
            current_size = live.log_path.stat().st_size if live.log_path.exists() else 0
            live.output_bytes += len(data)
            if current_size + len(data) > _LOG_TRIM_TRIGGER_BYTES:
                combined = live.log_path.read_bytes() + data
                tail = _valid_utf8_tail(combined[-_MAX_LOG_BYTES:])
                live.log_start_cursor = live.output_bytes - len(tail)
                live.log_truncated = True
                live.log_path.write_bytes(tail)
            else:
                with live.log_path.open("ab") as handle:
                    handle.write(data)

    def _persist_live_progress(self, job_id: str, live: _LiveJob, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - live.last_persisted_at < _PROGRESS_INTERVAL_SECONDS:
            return
        live.last_persisted_at = now
        now_ms = _now_ms()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                """
                UPDATE agent_background_jobs
                SET output_bytes = ?,
                    log_start_cursor = ?,
                    log_truncated = ?,
                    updated_at_ms = ?
                WHERE job_id = ?
                """,
                (
                    live.output_bytes,
                    live.log_start_cursor,
                    int(live.log_truncated),
                    now_ms,
                    job_id,
                ),
            )
        if live.output_bytes > 0 and (force or now - live.last_progress_at >= _PROGRESS_INTERVAL_SECONDS):
            live.last_progress_at = now
            job = self._job_payload(self._row_for_job(job_id))
            self._publish("background_job_progress", job)

    def _request_timeout(self, job_id: str) -> None:
        now_ms = _now_ms()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                """
                UPDATE agent_background_jobs
                SET status = 'cancelling',
                    cancel_requested_at_ms = ?,
                    updated_at_ms = ?,
                    error = 'background_job_timeout'
                WHERE job_id = ? AND status IN ('queued', 'running')
                """,
                (now_ms, now_ms, job_id),
            )

    def _mark_launch_failed(self, job_id: str, error: str) -> None:
        now_ms = _now_ms()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                """
                UPDATE agent_background_jobs
                SET status = 'failed', updated_at_ms = ?, ended_at_ms = ?, error = ?
                WHERE job_id = ?
                """,
                (now_ms, now_ms, error, job_id),
            )

    def _finalize_without_process(self, job_id: str, *, status: str, error: str) -> None:
        now_ms = _now_ms()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                """
                UPDATE agent_background_jobs
                SET status = ?, updated_at_ms = ?, ended_at_ms = ?, error = ?
                WHERE job_id = ? AND status NOT IN ('completed', 'failed', 'cancelled', 'orphaned')
                """,
                (status, now_ms, now_ms, error[:500], job_id),
            )

    def _terminate_and_wait(self, live: _LiveJob) -> None:
        process = live.launched.process
        try:
            self.workspace_harness.terminate_background(live.launched)
        except Exception:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=2.0)
            except Exception:
                pass
        except Exception:
            pass

    def _abort_launched_job(
        self,
        job_id: str,
        live: _LiveJob,
        *,
        error: str,
    ) -> None:
        self._terminate_and_wait(live)
        output = live.launched.process.stdout
        if output is not None:
            try:
                output.close()
            except Exception:
                pass
        try:
            live.launched.cleanup()
        except Exception:
            pass
        try:
            self._mark_launch_failed(job_id, error)
        except Exception:
            pass
        with self._lock:
            self._live.pop(job_id, None)

    @staticmethod
    def _require_live_causal_epoch(
        conn: sqlite3.Connection,
        session_id: str,
        causal: Mapping[str, object],
    ) -> None:
        if bool(causal["roomBound"]):
            return
        plan_id = str(causal["planId"] or "")
        plan_revision = int(causal["planRevision"] or 0)
        goal_id = str(causal["goalId"] or "")
        goal_revision = int(causal["goalRevision"] or 0)
        clauses: list[str] = []
        values: list[object] = [session_id]
        if plan_id and plan_revision > 0:
            clauses.append(
                "(scope_kind = 'plan' AND scope_id = ? AND source_revision = ?)"
            )
            values.extend((plan_id, plan_revision))
        if goal_id and goal_revision > 0:
            clauses.append(
                "(scope_kind = 'goal' AND scope_id = ? AND source_revision = ?)"
            )
            values.extend((goal_id, goal_revision))
        if not clauses:
            return
        cancelled = conn.execute(
            f"""
            SELECT 1
            FROM agent_lifecycle_cancellation_audits
            WHERE session_id = ? AND ({' OR '.join(clauses)})
            LIMIT 1
            """,
            tuple(values),
        ).fetchone()
        if cancelled is not None:
            raise AgentBackgroundJobError(
                "background job causal lifecycle was cancelled before launch"
            )

    def _require_capacity(
        self,
        conn: sqlite3.Connection,
        session_id: str,
    ) -> None:
        count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM agent_background_jobs
                WHERE session_id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (session_id,),
            ).fetchone()[0]
        )
        if count >= _MAX_ACTIVE_JOBS_PER_SESSION:
            raise AgentBackgroundJobError("a session may own at most 8 active background jobs")

    def _row(self, session_id: str, job_id: str) -> sqlite3.Row:
        row = self._row_for_job(job_id)
        if str(row["session_id"] or "") != session_id:
            raise AgentBackgroundJobError("background job is outside the current session")
        return row

    def _row_for_job(self, job_id: str) -> sqlite3.Row:
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                "SELECT * FROM agent_background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise AgentBackgroundJobError("background job was not found")
        return row

    def _job_payload(self, row: Mapping[str, object]) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-background-job.v1",
            "jobId": str(row["job_id"]),
            "sessionId": str(row["session_id"]),
            "label": str(row["label"]),
            "status": str(row["status"]),
            "command": str(row["command"]),
            "commandSha256": str(row["command_sha256"]),
            "cwd": str(row["cwd"]),
            "networkAllowed": bool(row["network_allowed"]),
            "maxRunSeconds": int(row["max_run_seconds"]),
            "pid": int(row["pid"]) if row["pid"] is not None else None,
            "createdAtMs": int(row["created_at_ms"]),
            "startedAtMs": int(row["started_at_ms"]),
            "updatedAtMs": int(row["updated_at_ms"]),
            "endedAtMs": int(row["ended_at_ms"]),
            "exitCode": int(row["exit_code"]) if row["exit_code"] is not None else None,
            "outputBytes": int(row["output_bytes"]),
            "logStartCursor": int(row["log_start_cursor"]),
            "logTruncated": bool(row["log_truncated"]),
            "cancelRequestedAtMs": int(row["cancel_requested_at_ms"]),
            "error": str(row["error"] or "")[:500],
            "approvalId": str(row["approval_id"] or "")[:240],
            "causalMetadata": {
                "planId": str(row["causal_plan_id"] or ""),
                "planRevision": int(row["causal_plan_revision"] or 0),
                "goalId": str(row["causal_goal_id"] or ""),
                "goalRevision": int(row["causal_goal_revision"] or 0),
                "turnId": str(row["causal_turn_id"] or ""),
                "roomBound": bool(row["room_bound"]),
            },
        }
        validate_contract(payload, "agent-background-job.v1.json")
        return payload

    def _require_execution_owner(self) -> None:
        if not self.execution_owner:
            raise AgentBackgroundJobError(
                "background job execution is owned by the Agent Gateway"
            )

    def _publish(self, event_type: str, job: Mapping[str, object]) -> None:
        self.events(
            str(job["sessionId"]),
            event_type,
            {
                "jobId": str(job["jobId"]),
                "status": str(job["status"]),
                "summary": _event_summary(event_type, job),
                "job": dict(job),
            },
            turn_id=f"background:{job['jobId']}",
        )

    def _ensure_log_root(self) -> None:
        if self.log_root.exists() and self.log_root.is_symlink():
            raise AgentBackgroundJobError("background job log directory cannot be a symlink")
        self.log_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.log_root, 0o700)

    def _log_path(self, job_id: str) -> Path:
        self._ensure_log_root()
        return self.log_root / f"{job_id}.log"

    def _safe_stored_log_path(self, value: str, job_id: str) -> Path:
        expected = self._log_path(job_id).resolve(strict=False)
        candidate = Path(value).resolve(strict=False)
        if candidate != expected or candidate.is_symlink():
            raise AgentBackgroundJobError("background job log path is invalid")
        return candidate


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(int(process_group_id), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _job_causal_metadata(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    approval_id: str,
    supplied: Mapping[str, object] | None,
) -> dict[str, object]:
    causal: dict[str, object] = {
        "planId": "",
        "planRevision": 0,
        "goalId": "",
        "goalRevision": 0,
        "turnId": "",
        "roomBound": False,
    }
    normalized_approval_id = str(approval_id or "").strip()
    inherited_room_bound = False
    if normalized_approval_id:
        row = conn.execute(
            """
            SELECT session_id, tool_name, operation, state,
                   causal_plan_id, causal_plan_revision, causal_goal_id,
                   causal_goal_revision, causal_turn_id, room_bound
            FROM agent_approvals
            WHERE approval_id = ?
            """,
            (normalized_approval_id,),
        ).fetchone()
        if row is None:
            raise AgentBackgroundJobError("background job approval was not found")
        if (
            str(row[0]) != session_id
            or str(row[1]) != "workspace_job"
            or str(row[2]) != "start"
        ):
            raise AgentBackgroundJobError(
                "background job approval does not authorize this launch"
            )
        if str(row[3]) != "approved":
            raise AgentBackgroundJobError(
                "background job approval is no longer approved"
            )
        causal = {
            "planId": str(row[4] or ""),
            "planRevision": int(row[5] or 0),
            "goalId": str(row[6] or ""),
            "goalRevision": int(row[7] or 0),
            "turnId": str(row[8] or ""),
            "roomBound": bool(row[9]),
        }
        inherited_room_bound = bool(causal["roomBound"])
    elif supplied is not None:
        for key in causal:
            if key in supplied:
                causal[key] = supplied[key]
    causal["planId"] = str(causal["planId"] or "").strip()[:240]
    causal["planRevision"] = max(0, int(causal["planRevision"] or 0))
    causal["goalId"] = str(causal["goalId"] or "").strip()[:240]
    causal["goalRevision"] = max(0, int(causal["goalRevision"] or 0))
    causal["turnId"] = str(causal["turnId"] or "").strip()[:240]
    causal["roomBound"] = inherited_room_bound or (
        bool(supplied.get("roomBound"))
        if supplied is not None and not normalized_approval_id
        else False
    )
    return causal


def _event_summary(event_type: str, job: Mapping[str, object]) -> str:
    label = str(job.get("label") or "后台任务")
    return {
        "background_job_started": f"后台任务《{label}》已启动",
        "background_job_progress": f"后台任务《{label}》产生了新日志",
        "background_job_completed": f"后台任务《{label}》已完成",
        "background_job_failed": f"后台任务《{label}》失败",
        "background_job_cancelled": f"后台任务《{label}》已停止",
    }.get(event_type, f"后台任务《{label}》已更新")


def _job_label(value: object, command: str) -> str:
    label = _bounded_text(value, maximum=120)
    if label:
        return label
    compact = " ".join(command.split())
    return (compact[:117] + "...") if len(compact) > 120 else compact


def _job_id(value: object) -> str:
    normalized = str(value or "").strip()
    if len(normalized) != 35 or not normalized.startswith("bg_"):
        raise AgentBackgroundJobError("background job id is invalid")
    suffix = normalized[3:]
    if any(character not in "0123456789abcdef" for character in suffix):
        raise AgentBackgroundJobError("background job id is invalid")
    return normalized


def _required_text(value: object, *, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise AgentBackgroundJobError(f"{field} is invalid")
    return normalized


def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        parsed = default
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
    return max(minimum, min(maximum, parsed))


def _valid_utf8_tail(value: bytes) -> bytes:
    tail = value
    while tail and 0x80 <= tail[0] <= 0xBF:
        tail = tail[1:]
    return tail


def _public_error(exc: BaseException) -> str:
    value = " ".join(str(exc).split())[:500]
    return value or type(exc).__name__


def _now_ms() -> int:
    return int(time.time() * 1_000)
