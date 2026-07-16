from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from .agent_artifacts import AgentArtifactStore
from .agent_events import AgentEventHub
from .agent_protocol import AgentEventEnvelope
from .agent_runtime_driver import (
    AgentRuntimeDriver,
    AgentRuntimeError,
    CompactionObserver,
    RuntimeDriverContext,
    RuntimeDriverFactory,
)
from .agent_sessions import AgentSessionStore
from .agent_templates import AgentTemplate, agent_template, agent_template_catalog
from .agent_tool_ids import ASSISTANT_CONTROL_TOOL_IDS
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .pi_runtime import PiRuntimeConfig, PiRuntimeDriverFactory, PiRuntimeManager


_TERMINAL_STATES = frozenset({"completed", "failed", "aborted", "timed_out"})
_ACTIVE_STATES = frozenset({"queued", "running"})
_MAX_PARALLEL_RUNS = 2
_MAX_FORK_BYTES = 32 * 1024 * 1024
_SOFT_BUDGET_RATIO = 0.8
_DEFAULT_CANCELLATION_GRACE_MS = 2_000
_DEFAULT_SUBAGENT_SESSION_RETENTION_MS = 72 * 60 * 60 * 1_000
_DEFAULT_SUBAGENT_SESSION_GC_INTERVAL_MS = 15 * 60 * 1_000


class AgentDelegationStore:
    """Durable lifecycle index for bounded task subagents."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        artifacts: AgentArtifactStore | None = None,
    ):
        self.db_path = Path(db_path)
        self.artifacts = artifacts

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)
        if self.artifacts is not None:
            self.artifacts.initialize()
            self._sync_all_artifacts()

    def create_batch(
        self,
        *,
        parent_session_id: str,
        parent_run_id: str,
        context_mode: str,
        depth: int,
        max_depth: int,
        runs: Sequence[Mapping[str, object]],
        created_at_ms: int | None = None,
    ) -> dict[str, object]:
        values = [dict(item) for item in runs]
        if not 1 <= len(values) <= _MAX_PARALLEL_RUNS:
            raise ValueError("delegation requires one or two tasks")
        if context_mode not in {"fresh", "fork"}:
            raise ValueError("delegation contextMode must be fresh or fork")
        if not 1 <= depth <= max_depth <= 2:
            raise ValueError("delegation depth is outside the managed limit")
        now = _timestamp(created_at_ms)
        batch_id = f"subagent-batch:{uuid.uuid4()}"
        run_ids: list[str] = []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_subagent_batches(
                    id, parent_session_id, parent_run_id, context_mode, state,
                    depth, max_depth, created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    parent_session_id,
                    parent_run_id,
                    context_mode,
                    depth,
                    max_depth,
                    now,
                    now,
                ),
            )
            for ordinal, value in enumerate(values):
                run_id = f"subagent-run:{uuid.uuid4()}"
                run_ids.append(run_id)
                child_session_id = _required_text(value, "childSessionId")
                marked = conn.execute(
                    """
                    UPDATE agent_sessions
                    SET session_kind = 'subagent_runtime'
                    WHERE id = ?
                    """,
                    (child_session_id,),
                )
                if marked.rowcount != 1:
                    raise ValueError("delegated child session does not exist")
                conn.execute(
                    """
                    INSERT INTO agent_subagent_runs(
                        id, batch_id, child_session_id, template_id, template_version,
                        ordinal, task_text, state, max_turns, max_tool_calls,
                        max_total_tokens, max_duration_ms, max_output_chars,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        batch_id,
                        child_session_id,
                        _required_text(value, "templateId"),
                        _required_text(value, "templateVersion"),
                        ordinal,
                        _bounded_task(value.get("task")),
                        _bounded_int(value.get("maxTurns"), minimum=0, maximum=32),
                        _bounded_int(value.get("maxToolCalls"), minimum=0, maximum=64),
                        _bounded_int(value.get("maxTotalTokens"), minimum=256, maximum=262_144),
                        _bounded_int(value.get("maxDurationMs"), minimum=1_000, maximum=900_000),
                        _bounded_int(value.get("maxOutputChars"), minimum=256, maximum=100_000),
                        now,
                        now,
                    ),
                )
                self._append_event_conn(
                    conn,
                    run_id=run_id,
                    event_type="queued",
                    payload={"batchId": batch_id, "ordinal": ordinal},
                    created_at_ms=now,
                )
        for run_id in run_ids:
            self._sync_run_artifact(run_id)
        return self.get_batch(batch_id)

    def get_batch(self, batch_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_subagent_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            runs = conn.execute(
                "SELECT * FROM agent_subagent_runs WHERE batch_id = ? ORDER BY ordinal ASC",
                (batch_id,),
            ).fetchall()
        payload = _batch_payload(row, runs)
        if self.artifacts is not None:
            payload["runs"] = [self._decorate_run(run) for run in payload["runs"]]
            for run in payload["runs"]:
                validate_contract(run, "agent-subagent-run.v1.json")
            validate_contract(payload, "agent-subagent-batch.v1.json")
        return payload

    def get_run(self, run_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_subagent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._decorate_run(_run_payload(row))

    def run_for_child_session(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT r.*, b.parent_session_id, b.parent_run_id, b.context_mode,
                       b.depth, b.max_depth, b.abort_requested
                FROM agent_subagent_runs r
                JOIN agent_subagent_batches b ON b.id = r.batch_id
                WHERE r.child_session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        payload = _run_payload(row)
        payload.update(
            {
                "parentSessionId": str(row["parent_session_id"]),
                "parentRunId": str(row["parent_run_id"] or ""),
                "contextMode": str(row["context_mode"]),
                "depth": int(row["depth"]),
                "maxDepth": int(row["max_depth"]),
                "abortRequested": bool(row["abort_requested"]),
            }
        )
        return payload

    def list_batches(
        self,
        *,
        parent_session_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        bounded = max(1, min(int(limit), 200))
        with self._connect() as conn:
            if parent_session_id:
                rows = conn.execute(
                    """
                    SELECT id FROM agent_subagent_batches
                    WHERE parent_session_id = ? ORDER BY created_at_ms DESC LIMIT ?
                    """,
                    (parent_session_id, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM agent_subagent_batches ORDER BY created_at_ms DESC LIMIT ?",
                    (bounded,),
                ).fetchall()
        return [self.get_batch(str(row["id"])) for row in rows]

    def active_run_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM agent_subagent_runs WHERE state IN ('queued', 'running')"
            ).fetchone()
        return int(row[0] if row else 0)

    def terminal_child_sessions(
        self,
        *,
        completed_before_ms: int | None = None,
    ) -> list[tuple[str, str]]:
        clauses = ["state IN ('completed', 'failed', 'aborted', 'timed_out')"]
        values: list[object] = []
        if completed_before_ms is not None:
            clauses.append("COALESCE(completed_at_ms, updated_at_ms) <= ?")
            values.append(int(completed_before_ms))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, child_session_id
                FROM agent_subagent_runs
                WHERE {' AND '.join(clauses)}
                ORDER BY completed_at_ms, id
                """,  # noqa: S608 - clauses are fixed above.
                tuple(values),
            ).fetchall()
        return [(str(row["id"]), str(row["child_session_id"])) for row in rows]

    def start_run(self, run_id: str, *, started_at_ms: int | None = None) -> dict[str, object]:
        now = _timestamp(started_at_ms)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agent_subagent_runs
                SET state = 'running', started_at_ms = ?, updated_at_ms = ?
                WHERE id = ? AND state = 'queued'
                """,
                (now, now, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("delegated run is no longer queued")
            self._append_event_conn(
                conn,
                run_id=run_id,
                event_type="started",
                payload={},
                created_at_ms=now,
            )
            batch_id = str(
                conn.execute(
                    "SELECT batch_id FROM agent_subagent_runs WHERE id = ?", (run_id,)
                ).fetchone()[0]
            )
            self._refresh_batch_conn(conn, batch_id, updated_at_ms=now)
        self._sync_run_artifact(run_id)
        return self.get_run(run_id)

    def update_usage(
        self,
        run_id: str,
        *,
        turn_count: int,
        tool_count: int,
        total_tokens: int,
        summary: str = "",
        updated_at_ms: int | None = None,
    ) -> dict[str, object]:
        now = _timestamp(updated_at_ms)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_subagent_runs
                SET turn_count = ?, tool_count = ?, total_tokens = ?, updated_at_ms = ?
                WHERE id = ? AND state = 'running'
                """,
                (
                    max(0, int(turn_count)),
                    max(0, int(tool_count)),
                    max(0, int(total_tokens)),
                    now,
                    run_id,
                ),
            )
            if summary:
                self._append_event_conn(
                    conn,
                    run_id=run_id,
                    event_type="progress",
                    payload={"summary": _bounded_text(summary, maximum=240)},
                    created_at_ms=now,
                )
        self._sync_run_artifact(run_id)
        return self.get_run(run_id)

    def finish_run(
        self,
        run_id: str,
        *,
        state: str,
        result: Mapping[str, object] | None = None,
        error: str = "",
        turn_count: int = 0,
        tool_count: int = 0,
        total_tokens: int = 0,
        completed_at_ms: int | None = None,
    ) -> dict[str, object]:
        if state not in _TERMINAL_STATES:
            raise ValueError("delegated run terminal state is invalid")
        now = _timestamp(completed_at_ms)
        result_json = json.dumps(
            dict(result or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT batch_id, state FROM agent_subagent_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            if str(row["state"]) in _TERMINAL_STATES:
                return self.get_run(run_id)
            conn.execute(
                """
                UPDATE agent_subagent_runs
                SET state = ?, result_json = ?, error = ?, turn_count = ?,
                    tool_count = ?, total_tokens = ?, updated_at_ms = ?, completed_at_ms = ?
                WHERE id = ?
                """,
                (
                    state,
                    result_json,
                    _bounded_text(error, maximum=500),
                    max(0, int(turn_count)),
                    max(0, int(tool_count)),
                    max(0, int(total_tokens)),
                    now,
                    now,
                    run_id,
                ),
            )
            self._append_event_conn(
                conn,
                run_id=run_id,
                event_type=state,
                payload={"error": _bounded_text(error, maximum=240)} if error else {},
                created_at_ms=now,
            )
            self._refresh_batch_conn(conn, str(row["batch_id"]), updated_at_ms=now)
        self._sync_run_artifact(run_id)
        return self.get_run(run_id)

    def request_abort(self, identifier: str, *, requested_at_ms: int | None = None) -> list[str]:
        now = _timestamp(requested_at_ms)
        affected: list[str] = []
        with self._connect() as conn:
            batch = conn.execute(
                "SELECT id FROM agent_subagent_batches WHERE id = ?", (identifier,)
            ).fetchone()
            if batch is not None:
                batch_id = identifier
                rows = conn.execute(
                    "SELECT id, state FROM agent_subagent_runs WHERE batch_id = ?",
                    (batch_id,),
                ).fetchall()
            else:
                run = conn.execute(
                    "SELECT id, batch_id, state FROM agent_subagent_runs WHERE id = ?",
                    (identifier,),
                ).fetchone()
                if run is None:
                    raise KeyError(identifier)
                batch_id = str(run["batch_id"])
                rows = conn.execute(
                    "SELECT id, state FROM agent_subagent_runs WHERE batch_id = ?",
                    (batch_id,),
                ).fetchall()
            conn.execute(
                "UPDATE agent_subagent_batches SET abort_requested = 1, updated_at_ms = ? WHERE id = ?",
                (now, batch_id),
            )
            active: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                affected.append(run_id)
                state = str(row["state"])
                if state == "queued":
                    conn.execute(
                        """
                        UPDATE agent_subagent_runs
                        SET state = 'aborted', error = 'Stopped before launch',
                            updated_at_ms = ?, completed_at_ms = ?
                        WHERE id = ?
                        """,
                        (now, now, run_id),
                    )
                    self._append_event_conn(
                        conn,
                        run_id=run_id,
                        event_type="aborted",
                        payload={"reason": "user_stop"},
                        created_at_ms=now,
                    )
                elif state == "running":
                    active.append(run_id)
            self._refresh_batch_conn(conn, batch_id, updated_at_ms=now)
        for run_id in affected:
            self._sync_run_artifact(run_id)
        return active

    def append_budget_event(self, run_id: str, reason: str, *, phase: str) -> None:
        if phase not in {"soft", "hard"}:
            raise ValueError("delegated budget phase must be soft or hard")
        now = _timestamp(None)
        with self._connect() as conn:
            self._append_event_conn(
                conn,
                run_id=run_id,
                event_type="budget_exceeded",
                payload={
                    "phase": phase,
                    "reason": _bounded_text(reason, maximum=240),
                },
                created_at_ms=now,
            )
        self._sync_run_artifact(run_id)
        self.checkpoint_supervision(
            run_id,
            phase=phase,
            reason=reason,
            requested_at_ms=now if phase == "hard" else None,
        )

    def checkpoint_runtime_event(
        self,
        run_id: str,
        event: AgentEventEnvelope,
        checkpoint: Mapping[str, object],
    ) -> None:
        if self.artifacts is None:
            return
        self.artifacts.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=[
                {
                    "recordId": f"runtime:{event.event_id}",
                    "eventType": event.event_type,
                    "createdAtMs": event.created_at_ms,
                    "payload": _safe_runtime_artifact_payload(event),
                }
            ],
        )
        self.artifacts.checkpoint(
            owner_kind="subagent_run",
            owner_id=run_id,
            runtime_checkpoint=checkpoint,
            updated_at_ms=event.created_at_ms,
        )

    def checkpoint_supervision(
        self,
        run_id: str,
        *,
        phase: str,
        reason: str,
        requested_at_ms: int | None = None,
        grace_ms: int | None = None,
    ) -> None:
        if self.artifacts is None:
            return
        now = _timestamp(None)
        self.artifacts.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=[
                {
                    "recordId": f"supervision:{phase}:{now}",
                    "eventType": f"supervision_{phase}",
                    "createdAtMs": now,
                    "payload": {
                        "reason": _bounded_text(reason, maximum=240),
                        "graceMs": max(0, int(grace_ms or 0)),
                    },
                }
            ],
        )
        self.artifacts.checkpoint(
            owner_kind="subagent_run",
            owner_id=run_id,
            supervision={
                "phase": phase,
                "reason": _bounded_text(reason, maximum=240),
                "requestedAtMs": requested_at_ms,
                "graceMs": max(0, int(grace_ms or 0)),
            },
            updated_at_ms=now,
        )

    def reconcile_interrupted_runs(self) -> list[str]:
        """Recover safe queued work and project terminal artifact checkpoints."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, state FROM agent_subagent_runs WHERE state IN ('queued', 'running')"
            ).fetchall()
        relaunch: list[str] = []
        for row in rows:
            run_id = str(row["id"])
            state = str(row["state"])
            self._sync_run_artifact(run_id)
            if state == "queued":
                relaunch.append(run_id)
                continue

            snapshot = (
                self.artifacts.snapshot(owner_kind="subagent_run", owner_id=run_id)
                if self.artifacts is not None
                else None
            )
            checkpoint = (
                snapshot.get("runtimeCheckpoint")
                if isinstance(snapshot, Mapping)
                and isinstance(snapshot.get("runtimeCheckpoint"), Mapping)
                else {}
            )
            terminal_state = str(checkpoint.get("terminalState") or "")
            usage = checkpoint.get("usage") if isinstance(checkpoint.get("usage"), Mapping) else {}
            last_message = (
                dict(checkpoint["lastMessage"])
                if isinstance(checkpoint.get("lastMessage"), Mapping)
                else {}
            )
            if terminal_state == "completed" and last_message:
                run = self.get_run(run_id)
                result = {
                    "summary": _message_summary(
                        last_message,
                        int(run["budget"]["maxOutputChars"]),
                    ),
                    "message": last_message,
                    "childSessionId": run["childSessionId"],
                    "templateId": run["templateId"],
                    "recovered": True,
                }
                final_state = "completed"
                error = ""
            elif terminal_state in {"failed", "aborted", "timed_out"}:
                result = {}
                final_state = terminal_state
                error = _bounded_text(
                    checkpoint.get("error") or "Delegated runtime ended before projection",
                    maximum=500,
                )
            else:
                result = {}
                final_state = "failed"
                error = "Sidecar restarted before the delegated runtime reached a durable terminal checkpoint"

            self.finish_run(
                run_id,
                state=final_state,
                result=result,
                error=error,
                turn_count=max(0, int(usage.get("turnCount") or 0)),
                tool_count=max(0, int(usage.get("toolCount") or 0)),
                total_tokens=max(0, int(usage.get("totalTokens") or 0)),
            )
            if self.artifacts is not None:
                now = _timestamp(None)
                self.artifacts.append_records(
                    owner_kind="subagent_run",
                    owner_id=run_id,
                    records=[
                        {
                            "recordId": f"reconcile:{now}",
                            "eventType": "reconciled",
                            "createdAtMs": now,
                            "payload": {
                                "fromState": "running",
                                "toState": final_state,
                                "terminalCheckpoint": bool(terminal_state),
                            },
                        }
                    ],
                )
        return relaunch

    def _decorate_run(self, run: Mapping[str, object]) -> dict[str, object]:
        payload = dict(run)
        if self.artifacts is None:
            return payload
        payload["artifact"] = self.artifacts.reference(
            owner_kind="subagent_run",
            owner_id=str(payload["id"]),
        )
        snapshot = self.artifacts.snapshot(
            owner_kind="subagent_run",
            owner_id=str(payload["id"]),
        )
        supervision = (
            snapshot.get("supervision")
            if isinstance(snapshot, Mapping)
            and isinstance(snapshot.get("supervision"), Mapping)
            else {}
        )
        payload["supervision"] = {
            "phase": str(supervision.get("phase") or "none"),
            "reason": str(supervision.get("reason") or ""),
            "requestedAtMs": supervision.get("requestedAtMs"),
            "graceMs": max(0, int(supervision.get("graceMs") or 0)),
        }
        return payload

    def _sync_all_artifacts(self) -> None:
        if self.artifacts is None:
            return
        with self._connect() as conn:
            run_ids = [
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT r.id
                    FROM agent_subagent_runs r
                    LEFT JOIN agent_artifacts a
                      ON a.owner_kind = 'subagent_run'
                     AND a.owner_id = r.id
                     AND a.artifact_kind = 'lifecycle'
                    WHERE a.id IS NULL
                       OR a.updated_at_ms < r.updated_at_ms
                       OR r.state IN ('queued', 'running')
                    ORDER BY r.created_at_ms
                    """
                ).fetchall()
            ]
        for run_id in run_ids:
            self._sync_run_artifact(run_id)

    def _sync_run_artifact(self, run_id: str) -> None:
        if self.artifacts is None:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_subagent_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            event_rows = conn.execute(
                "SELECT * FROM agent_subagent_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        projection = _run_payload(row)
        records = [
            {
                "recordId": str(event["event_id"]),
                "sequence": int(event["sequence"]),
                "eventType": str(event["event_type"]),
                "createdAtMs": int(event["created_at_ms"]),
                "payload": _json_mapping(event["payload_json"]),
            }
            for event in event_rows
        ]
        self.artifacts.append_records(
            owner_kind="subagent_run",
            owner_id=run_id,
            records=records,
        )
        snapshot = self.artifacts.snapshot(
            owner_kind="subagent_run",
            owner_id=run_id,
        )
        previous_projection = (
            snapshot.get("projection")
            if isinstance(snapshot, Mapping)
            and isinstance(snapshot.get("projection"), Mapping)
            else None
        )
        if previous_projection != projection:
            self.artifacts.checkpoint(
                owner_kind="subagent_run",
                owner_id=run_id,
                projection=projection,
                updated_at_ms=int(projection["updatedAtMs"]),
            )

    def owns_session(self, session_id: str) -> bool:
        return self.run_for_child_session(session_id) is not None

    def _refresh_batch_conn(
        self,
        conn: sqlite3.Connection,
        batch_id: str,
        *,
        updated_at_ms: int,
    ) -> None:
        states = [
            str(row[0])
            for row in conn.execute(
                "SELECT state FROM agent_subagent_runs WHERE batch_id = ? ORDER BY ordinal",
                (batch_id,),
            ).fetchall()
        ]
        if any(state == "running" for state in states):
            state = "running"
        elif any(state == "queued" for state in states):
            state = "queued"
        elif states and all(item == "completed" for item in states):
            state = "completed"
        elif any(item == "timed_out" for item in states):
            state = "timed_out"
        elif any(item == "failed" for item in states):
            state = "failed"
        else:
            state = "aborted"
        completed_at = updated_at_ms if state in _TERMINAL_STATES else None
        conn.execute(
            """
            UPDATE agent_subagent_batches
            SET state = ?, updated_at_ms = ?, completed_at_ms = ? WHERE id = ?
            """,
            (state, updated_at_ms, completed_at, batch_id),
        )

    def _append_event_conn(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        event_type: str,
        payload: Mapping[str, object],
        created_at_ms: int,
    ) -> None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM agent_subagent_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        sequence = int(row[0] if row else 1)
        conn.execute(
            """
            INSERT INTO agent_subagent_events(
                event_id, run_id, sequence, event_type, created_at_ms, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"{run_id}:{sequence}",
                run_id,
                sequence,
                event_type,
                created_at_ms,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


@dataclass
class _ActiveDelegatedRun:
    runtime: AgentRuntimeDriver
    child_session_id: str
    terminal: threading.Event
    forced: threading.Event
    lock: threading.RLock
    cancellation_state: str = ""
    cancellation_reason: str = ""


class AgentDelegationCoordinator:
    """Product-owned adapter for fixed-catalog Pi child sessions."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        runtime_config: PiRuntimeConfig,
        sessions: AgentSessionStore,
        events: AgentEventHub,
        media_resolver: Callable[[str, str, str], str] | None = None,
        runtime_factory: Callable[..., PiRuntimeManager] | None = None,
        runtime_driver_factory: RuntimeDriverFactory | None = None,
        tool_gateway_token: str = "",
        compaction_observer: CompactionObserver | None = None,
        artifact_root: str | Path | None = None,
        cancellation_grace_ms: int = _DEFAULT_CANCELLATION_GRACE_MS,
        subagent_session_retention_ms: int | None = None,
        subagent_session_gc_interval_ms: int | None = None,
    ) -> None:
        self.artifacts = AgentArtifactStore(db_path, root=artifact_root)
        self.store = AgentDelegationStore(db_path, artifacts=self.artifacts)
        self.store.initialize()
        self.runtime_config = runtime_config
        self.sessions = sessions
        self.events = events
        self.media_resolver = media_resolver
        self._legacy_runtime_factory = runtime_factory
        self._runtime_driver_factory = runtime_driver_factory or PiRuntimeDriverFactory(
            runtime_config
        )
        self._tool_gateway_token = str(
            tool_gateway_token or runtime_config.tool_gateway_token
        )
        self._compaction_observer = compaction_observer
        self._cancellation_grace_ms = max(10, min(int(cancellation_grace_ms), 30_000))
        self._subagent_session_retention_ms = max(
            0,
            min(
                int(
                    subagent_session_retention_ms
                    if subagent_session_retention_ms is not None
                    else _subagent_session_retention_from_environment()
                ),
                30 * 24 * 60 * 60 * 1_000,
            ),
        )
        self._subagent_session_gc_interval_ms = max(
            0,
            min(
                int(
                    subagent_session_gc_interval_ms
                    if subagent_session_gc_interval_ms is not None
                    else _subagent_session_gc_interval_from_environment()
                ),
                24 * 60 * 60 * 1_000,
            ),
        )
        self._lock = threading.RLock()
        self._retirement_lock = threading.RLock()
        self._last_session_gc_monotonic = 0.0
        self._active_runs: dict[str, _ActiveDelegatedRun] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        recoverable = self.store.reconcile_interrupted_runs()
        self.collect_expired_sessions(force=True)
        if self.runtime_config.enabled:
            for run_id in recoverable:
                self._start_run_thread(run_id)

    def catalog(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.agent-template-list.v1",
            "ok": True,
            "maxParallel": _MAX_PARALLEL_RUNS,
            "maxDepth": 2,
            "items": agent_template_catalog(),
        }

    def delegate(self, parent_session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        parent = self.sessions.get(parent_session_id)
        parent_run = self.store.run_for_child_session(parent_session_id)
        if parent.get("status") == "archived" and parent_run is None:
            raise ValueError("archived sessions cannot delegate tasks")
        tasks = _delegation_tasks(payload)
        context_mode = str(payload.get("contextMode") or "fresh").strip()
        if context_mode not in {"fresh", "fork"}:
            raise ValueError("contextMode must be fresh or fork")
        parent_runtime_binding = self.sessions.runtime_binding(parent_session_id)
        native_forks = (
            _validated_native_fork_sessions(
                payload.get("_runtimeContext"),
                parent_runtime_binding=parent_runtime_binding,
                session_dir=self._runtime_driver_factory.session_root,
                agent_dir=self._runtime_driver_factory.working_root,
                expected_count=len(tasks),
            )
            if context_mode == "fork"
            else []
        )
        depth = int(parent_run.get("depth") or 0) + 1 if parent_run else 1
        parent_run_id = str(parent_run.get("id") or "") if parent_run else ""
        if depth > 2:
            raise ValueError("subagent maximum depth is 2")

        templates: list[AgentTemplate] = []
        for task in tasks:
            template = agent_template(task["agent"], task.get("version") or "1")
            if context_mode not in template.context_modes:
                raise ValueError(
                    f"agent template {template.template_id} does not support {context_mode} context"
                )
            templates.append(template)

        created_sessions: list[dict[str, object]] = []
        prepared_files: list[Path] = []
        with self._lock:
            if self._closed:
                raise ValueError("delegation runtime is closed")
            if self.store.active_run_count() + len(tasks) > _MAX_PARALLEL_RUNS:
                raise ValueError("at most two delegated tasks may run at once")
            try:
                for ordinal, (task, template) in enumerate(zip(tasks, templates, strict=True)):
                    parent_profile = str(parent.get("toolProfileVersion") or "control-center-v1")
                    child_profile = (
                        "subagent-readonly-v1"
                        if parent_profile == "subagent-readonly-v1"
                        else template.tool_profile_version
                    )
                    child = self.sessions.create(
                        title=f"{template.display_name} · {_bounded_text(task['task'], maximum=72)}",
                        mode="assistant",
                        role_id=str(parent.get("roleId") or "zhiyou-v1"),
                        role_version=str(parent.get("roleVersion") or "1"),
                        model_profile=str(parent.get("modelProfile") or "pi/default"),
                        tool_profile_version=child_profile,
                        session_kind="subagent_runtime",
                    )
                    if str(parent.get("toolAllowlistMode") or "profile") == "explicit":
                        parent_tools = {str(value) for value in parent.get("allowedTools") or []}
                        child = self.sessions.set_runtime_policy(
                            str(child["id"]),
                            mode="assistant",
                            tool_profile_version=child_profile,
                            allowed_tools=[
                                tool for tool in ASSISTANT_CONTROL_TOOL_IDS if tool in parent_tools
                            ],
                        )
                    if context_mode == "fork":
                        branch = native_forks[ordinal]
                        prepared_files.append(branch["path"])
                        child = self.sessions.bind_runtime_session(
                            str(child["id"]),
                            driver_id="managed-pi",
                            runtime_kind="pi_rpc",
                            external_session_id=str(branch["sessionId"]),
                            transcript_ref=str(branch["path"]),
                            branch_anchor=str(branch["parentLeafId"]),
                            binding_state="prepared",
                        )
                    created_sessions.append(child)

                run_specs = []
                for child, task, template in zip(created_sessions, tasks, templates, strict=True):
                    budget = template.budget
                    run_specs.append(
                        {
                            "childSessionId": child["id"],
                            "templateId": template.template_id,
                            "templateVersion": template.version,
                            "task": task["task"],
                            "maxTurns": budget.max_turns,
                            "maxToolCalls": budget.max_tool_calls,
                            "maxTotalTokens": budget.max_total_tokens,
                            "maxDurationMs": budget.max_duration_ms,
                            "maxOutputChars": budget.max_output_chars,
                        }
                    )
                batch = self.store.create_batch(
                    parent_session_id=parent_session_id,
                    parent_run_id=parent_run_id,
                    context_mode=context_mode,
                    depth=depth,
                    max_depth=2,
                    runs=run_specs,
                )
            except Exception:
                for child in reversed(created_sessions):
                    try:
                        self.sessions.delete(str(child["id"]))
                    except Exception:
                        pass
                for path in prepared_files:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                raise

            for run in batch["runs"]:
                self._start_run_thread(str(run["id"]))

        wait = payload.get("wait") is not False
        if wait:
            batch = self.wait(str(batch["id"]))
        return {
            "schemaVersion": "rag-ime.agent-delegation.v1",
            "ok": True,
            "accepted": True,
            "waited": wait,
            "batch": batch,
        }

    def status(self, parent_session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        identifier = str(payload.get("runId") or payload.get("batchId") or "").strip()
        if not identifier:
            return {
                "schemaVersion": "rag-ime.agent-delegation-status.v1",
                "ok": True,
                "items": self.store.list_batches(
                    parent_session_id=parent_session_id,
                    limit=_bounded_int(payload.get("limit") or 20, minimum=1, maximum=100),
                ),
            }
        try:
            batch = self.store.get_batch(identifier)
        except KeyError:
            run = self.store.get_run(identifier)
            batch = self.store.get_batch(str(run["batchId"]))
        _assert_batch_owner(batch, parent_session_id)
        return {
            "schemaVersion": "rag-ime.agent-delegation-status.v1",
            "ok": True,
            "batch": batch,
        }

    def inspect_artifact(
        self,
        parent_session_id: str,
        artifact_id: str,
        *,
        limit: int = 100,
    ) -> dict[str, object]:
        self.sessions.get(parent_session_id)
        reference = self.artifacts.reference_by_id(artifact_id)
        if str(reference.get("ownerKind") or "") != "subagent_run":
            raise ValueError("artifact is not a delegated run lifecycle")
        run = self.store.get_run(str(reference.get("ownerId") or ""))
        batch = self.store.get_batch(str(run["batchId"]))
        _assert_batch_owner(batch, parent_session_id)
        return self.artifacts.inspect(artifact_id, limit=limit)

    def abort(self, parent_session_id: str, payload: Mapping[str, object]) -> dict[str, object]:
        identifier = str(payload.get("runId") or payload.get("batchId") or "").strip()
        if not identifier:
            raise ValueError("runId or batchId is required")
        try:
            batch = self.store.get_batch(identifier)
        except KeyError:
            run = self.store.get_run(identifier)
            batch = self.store.get_batch(str(run["batchId"]))
        _assert_batch_owner(batch, parent_session_id)
        active = self.store.request_abort(identifier)
        for run_id in active:
            self._request_cancel(run_id, state="aborted", reason="Stopped by user")
        self.collect_expired_sessions(force=False)
        return {
            "schemaVersion": "rag-ime.agent-delegation-abort.v1",
            "ok": True,
            "batch": self.store.get_batch(str(batch["id"])),
        }

    def wait(self, batch_id: str) -> dict[str, object]:
        batch = self.store.get_batch(batch_id)
        maximum = max(
            int(run["budget"]["maxDurationMs"])
            for run in batch["runs"]
        )
        deadline = time.monotonic() + maximum / 1000.0 + 10.0
        while time.monotonic() < deadline:
            batch = self.store.get_batch(batch_id)
            if str(batch["state"]) in _TERMINAL_STATES:
                self.collect_expired_sessions(force=False)
                return self.store.get_batch(batch_id)
            time.sleep(0.025)
        self.store.request_abort(batch_id)
        for run in batch["runs"]:
            if str(run["state"]) in _ACTIVE_STATES:
                self._request_cancel(
                    str(run["id"]),
                    state="timed_out",
                    reason="Delegation wait deadline exceeded",
                )
        return self.store.get_batch(batch_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            active_runs = list(self._active_runs.values())
            threads = list(self._threads.values())
        for active in active_runs:
            try:
                active.runtime.stop()
            except Exception:
                pass
            active.forced.set()
        deadline = time.monotonic() + self._cancellation_grace_ms / 1000.0 + 1.0
        for thread in threads:
            if thread is threading.current_thread():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def reconfigure(self, config: PiRuntimeConfig) -> None:
        self.close()
        with self._lock:
            self.runtime_config = config
            self._runtime_driver_factory.reconfigure(config)
            self._tool_gateway_token = config.tool_gateway_token
            self._closed = False
        recoverable = self.store.reconcile_interrupted_runs()
        self.collect_expired_sessions(force=True)
        if config.enabled:
            for run_id in recoverable:
                self._start_run_thread(run_id)

    def refresh_runtime_factory(self) -> None:
        """Restart delegated-driver ownership after Kernel policy changes."""

        self.close()
        with self._lock:
            factory_config = getattr(self._runtime_driver_factory, "config", None)
            if isinstance(factory_config, PiRuntimeConfig):
                self.runtime_config = factory_config
                self._tool_gateway_token = factory_config.tool_gateway_token
            self._closed = False
        recoverable = self.store.reconcile_interrupted_runs()
        self.collect_expired_sessions(force=True)
        if self.runtime_config.enabled:
            for run_id in recoverable:
                self._start_run_thread(run_id)

    def owns_session(self, session_id: str) -> bool:
        return self.store.owns_session(session_id)

    def _start_run_thread(self, run_id: str) -> None:
        with self._lock:
            if self._closed or run_id in self._threads:
                return
            thread = threading.Thread(
                target=self._run_task,
                args=(run_id,),
                name=f"rag-ime-{run_id[-8:]}",
                daemon=True,
            )
            self._threads[run_id] = thread
            thread.start()

    def _run_task(self, run_id: str) -> None:
        try:
            run = self.store.start_run(run_id)
        except ValueError:
            with self._lock:
                self._threads.pop(run_id, None)
            return
        batch = self.store.get_batch(str(run["batchId"]))
        child_session_id = str(run["childSessionId"])
        parent_session_id = str(batch["parentSessionId"])
        terminal = threading.Event()
        forced = threading.Event()
        terminal_error = ""
        completed = False
        budget_reason = ""
        last_message: dict[str, object] = {}
        turn_count = 0
        total_tokens = 0
        output_chars = 0
        tool_ids: set[str] = set()
        update_lock = threading.RLock()
        soft_reasons: set[str] = set()
        hard_scheduled = False
        active_run: _ActiveDelegatedRun | None = None

        def usage_checkpoint() -> dict[str, object]:
            return {
                "usage": {
                    "turnCount": turn_count,
                    "toolCount": len(tool_ids),
                    "totalTokens": total_tokens,
                    "outputChars": output_chars,
                },
                "lastMessage": last_message,
            }

        def persist_runtime_event(
            event: AgentEventEnvelope,
            *,
            terminal_state: str = "",
            error: str = "",
        ) -> None:
            checkpoint = usage_checkpoint()
            if terminal_state:
                checkpoint.update(
                    {
                        "terminalState": terminal_state,
                        "error": _bounded_text(error, maximum=500),
                        "terminalAtMs": event.created_at_ms,
                    }
                )
            try:
                self.store.checkpoint_runtime_event(run_id, event, checkpoint)
            except Exception:
                # The primary DB projection still finishes the run. Startup
                # reconciliation will fail this run closed if the artifact is unusable.
                pass

        def schedule_hard_budget(reason: str, event: AgentEventEnvelope) -> None:
            nonlocal budget_reason, hard_scheduled
            with update_lock:
                if hard_scheduled:
                    return
                budget_reason = reason
                hard_scheduled = True
            self.store.append_budget_event(run_id, reason, phase="hard")
            persist_runtime_event(event)
            self._request_cancel(run_id, state="failed", reason=reason)

        def check_usage_budget(event: AgentEventEnvelope) -> None:
            budget = run["budget"]
            checks = (
                (turn_count, int(budget["maxTurns"]), "turn budget exceeded"),
                (len(tool_ids), int(budget["maxToolCalls"]), "tool-call budget exceeded"),
                (total_tokens, int(budget["maxTotalTokens"]), "token budget exceeded"),
                (output_chars, int(budget["maxOutputChars"]), "output budget exceeded"),
            )
            for current, maximum, reason in checks:
                # maxTurns/maxToolCalls use zero as an explicit unlimited
                # sentinel. Other safety budgets always remain positive.
                if maximum > 0 and current > maximum:
                    schedule_hard_budget(reason, event)
                    return
                if maximum <= 0:
                    continue
                threshold = max(1, int(maximum * _SOFT_BUDGET_RATIO + 0.999))
                if current >= threshold and reason not in soft_reasons:
                    soft_reasons.add(reason)
                    self.store.append_budget_event(run_id, reason, phase="soft")
                    persist_runtime_event(event)

        def observe(event: AgentEventEnvelope) -> None:
            nonlocal terminal_error, completed, last_message
            nonlocal turn_count, total_tokens, output_chars
            if event.session_id != child_session_id:
                return
            with update_lock:
                if event.event_type == "text_delta":
                    output_chars += len(str(event.payload.get("delta") or ""))
                elif event.event_type == "tool_started":
                    identity = str(
                        event.payload.get("toolCallId")
                        or event.payload.get("callId")
                        or event.event_id
                    )
                    tool_ids.add(identity)
                    persist_runtime_event(event)
                elif event.event_type == "message_completed":
                    message = event.payload.get("message")
                    if isinstance(message, Mapping) and str(message.get("role") or "") == "assistant":
                        turn_count += 1
                        last_message = dict(message)
                        usage = event.payload.get("usage")
                        if isinstance(usage, Mapping):
                            total_tokens += max(0, int(usage.get("totalTokens") or 0))
                        persist_runtime_event(event)
                elif event.event_type == "turn_completed":
                    completed = True
                    persist_runtime_event(event, terminal_state="completed")
                    terminal.set()
                elif event.event_type == "turn_failed":
                    terminal_error = _bounded_text(
                        event.payload.get("error") or "delegated Pi turn failed",
                        maximum=500,
                    )
                    cancellation_state = ""
                    cancellation_reason = ""
                    if active_run is not None:
                        with active_run.lock:
                            cancellation_state = active_run.cancellation_state
                            cancellation_reason = active_run.cancellation_reason
                    persist_runtime_event(
                        event,
                        terminal_state=cancellation_state or "failed",
                        error=cancellation_reason or terminal_error,
                    )
                    terminal.set()
                check_usage_budget(event)

        remove_observer = self.events.add_observer(observe)
        context = {
            "agentTemplateId": run["templateId"],
            "agentTemplateVersion": run["templateVersion"],
            "delegationDepth": batch["depth"],
            "toolProfileVersion": self.sessions.get(child_session_id)["toolProfileVersion"],
        }
        if self._legacy_runtime_factory is not None:
            runtime = self._legacy_runtime_factory(
                config=replace(self.runtime_config, idle_timeout_seconds=0),
                sessions=self.sessions,
                events=self.events,
                media_resolver=self.media_resolver,
                session_context_provider=lambda _session: context,
            )
        else:
            runtime = self._runtime_driver_factory.create(
                RuntimeDriverContext(
                    sessions=self.sessions,
                    events=self.events,
                    media_resolver=self.media_resolver,
                    tool_gateway_token=self._tool_gateway_token,
                    compaction_observer=self._compaction_observer,
                ),
                purpose="delegated",
                session_context_provider=lambda _session: context,
            )
        active_run = _ActiveDelegatedRun(
            runtime=runtime,
            child_session_id=child_session_id,
            terminal=terminal,
            forced=forced,
            lock=threading.RLock(),
        )
        with self._lock:
            self._active_runs[run_id] = active_run
        self._publish_parent_progress(parent_session_id, batch, run, "子 Agent 已开始")
        state = "failed"
        error = ""
        result: dict[str, object] = {}
        try:
            if self.store.get_batch(str(batch["id"]))["abortRequested"]:
                state = "aborted"
                error = "Stopped by user"
            else:
                runtime.prompt(child_session_id, _subagent_prompt(run, batch))
                duration_seconds = int(run["budget"]["maxDurationMs"]) / 1000.0
                started = time.monotonic()
                soft_deadline = started + duration_seconds * _SOFT_BUDGET_RATIO
                hard_deadline = started + duration_seconds
                duration_soft_emitted = False
                duration_hard_emitted = False
                while not terminal.wait(0.025) and not forced.is_set():
                    now = time.monotonic()
                    if not duration_soft_emitted and now >= soft_deadline:
                        duration_soft_emitted = True
                        self.store.append_budget_event(
                            run_id,
                            "duration budget approaching",
                            phase="soft",
                        )
                    if not duration_hard_emitted and now >= hard_deadline:
                        duration_hard_emitted = True
                        budget_reason = "duration budget exceeded"
                        self.store.append_budget_event(run_id, budget_reason, phase="hard")
                        self._request_cancel(
                            run_id,
                            state="timed_out",
                            reason=budget_reason,
                        )

                with active_run.lock:
                    cancellation_state = active_run.cancellation_state
                    cancellation_reason = active_run.cancellation_reason
                if cancellation_state:
                    state = cancellation_state
                    error = cancellation_reason
                elif self.store.get_batch(str(batch["id"]))["abortRequested"]:
                    state = "aborted"
                    error = "Stopped by user"
                elif budget_reason:
                    state = "failed"
                    error = budget_reason
                elif terminal_error:
                    state = "failed"
                    error = terminal_error
                elif completed:
                    state = "completed"
                    summary = _message_summary(
                        last_message,
                        int(run["budget"]["maxOutputChars"]),
                    )
                    result = {
                        "summary": summary,
                        "message": last_message,
                        "childSessionId": child_session_id,
                        "templateId": run["templateId"],
                    }
                else:
                    error = "delegated Pi turn ended without a terminal event"
        except Exception as exc:
            error = _bounded_text(exc, maximum=500)
            if isinstance(exc, AgentRuntimeError) and "stopped" in error.lower():
                state = "aborted"
        finally:
            remove_observer()
            terminal.set()
            try:
                runtime.stop()
            except Exception:
                pass
            with self._lock:
                self._active_runs.pop(run_id, None)
        try:
            final = self.store.finish_run(
                run_id,
                state=state,
                result=result,
                error=error,
                turn_count=turn_count,
                tool_count=len(tool_ids),
                total_tokens=total_tokens,
            )
            self._publish_parent_progress(
                parent_session_id,
                self.store.get_batch(str(batch["id"])),
                final,
                "子 Agent 已完成" if state == "completed" else "子 Agent 已停止",
            )
            self._record_retained_child_session(run_id, child_session_id)
            self.collect_expired_sessions(force=False)
        finally:
            with self._lock:
                self._threads.pop(run_id, None)

    def collect_expired_sessions(
        self,
        *,
        force: bool = True,
        now_ms: int | None = None,
    ) -> int:
        """Destroy expired child-runtime state while preserving run results and Artifacts."""

        monotonic_now = time.monotonic()
        with self._retirement_lock:
            elapsed_ms = (monotonic_now - self._last_session_gc_monotonic) * 1_000
            if (
                not force
                and self._last_session_gc_monotonic > 0
                and elapsed_ms < self._subagent_session_gc_interval_ms
            ):
                return 0
            self._last_session_gc_monotonic = monotonic_now
        current_ms = _timestamp(now_ms)
        cutoff_ms = current_ms - self._subagent_session_retention_ms
        retired_count = 0
        for run_id, child_session_id in self.store.terminal_child_sessions(
            completed_before_ms=cutoff_ms
        ):
            try:
                session = self.sessions.get(child_session_id)
            except KeyError:
                continue
            if self._retire_child_session(run_id, child_session_id):
                retired_count += 1
        return retired_count

    def _record_retained_child_session(self, run_id: str, child_session_id: str) -> None:
        try:
            run = self.store.get_run(run_id)
            completed_at_ms = int(run.get("completedAtMs") or run.get("updatedAtMs") or 0)
            retained_until_ms = completed_at_ms + self._subagent_session_retention_ms
            now = _timestamp(None)
            self.artifacts.append_records(
                owner_kind="subagent_run",
                owner_id=run_id,
                records=[
                    {
                        "recordId": f"runtime-retained:{now}",
                        "eventType": "runtime_retained",
                        "createdAtMs": now,
                        "payload": {
                            "childSessionId": child_session_id,
                            "retainedUntilMs": retained_until_ms,
                        },
                    }
                ],
            )
        except Exception:
            # The run result is already durable. Retention metadata is advisory.
            return

    def _retire_child_session(self, run_id: str, child_session_id: str) -> bool:
        with self._retirement_lock:
            try:
                session = self.sessions.get(child_session_id)
                binding = self.sessions.runtime_binding(child_session_id)
                managed_root = self._runtime_driver_factory.session_root.expanduser().resolve(
                    strict=False
                )
                paths = {
                    str(session.get("sessionFile") or "").strip(),
                    str(binding.get("transcriptRef") or "").strip()
                    if isinstance(binding, Mapping)
                    else "",
                }
                for raw_path in paths:
                    if not raw_path:
                        continue
                    candidate = Path(raw_path).expanduser()
                    path = candidate.resolve(strict=False)
                    if (
                        not candidate.is_symlink()
                        and _is_within(path, managed_root)
                        and path.is_file()
                    ):
                        path.unlink()
                destroyed = self.sessions.destroy_internal(child_session_id)
                now = _timestamp(None)
                self.artifacts.append_records(
                    owner_kind="subagent_run",
                    owner_id=run_id,
                    records=[
                        {
                            "recordId": f"runtime-retired:{now}",
                            "eventType": "runtime_retired",
                            "createdAtMs": now,
                            "payload": {
                                "childSessionId": child_session_id,
                                "status": "destroyed",
                                "previousStatus": destroyed["status"],
                            },
                        }
                    ],
                )
                return True
            except Exception:
                # The run projection and Artifact are already durable. A stale
                # internal runtime remains hidden and can be retired on restart.
                return False

    def _request_cancel(self, run_id: str, *, state: str, reason: str) -> None:
        if state not in {"failed", "aborted", "timed_out"}:
            raise ValueError("delegated cancellation terminal state is invalid")
        with self._lock:
            active = self._active_runs.get(run_id)
        if active is None:
            return
        with active.lock:
            if active.cancellation_state:
                return
            active.cancellation_state = state
            active.cancellation_reason = _bounded_text(reason, maximum=240)
        requested_at_ms = _timestamp(None)
        self.store.checkpoint_supervision(
            run_id,
            phase="hard",
            reason=reason,
            requested_at_ms=requested_at_ms,
            grace_ms=self._cancellation_grace_ms,
        )
        threading.Thread(
            target=self._cancel_active_run,
            args=(run_id, active),
            name=f"rag-ime-cancel-{run_id[-8:]}",
            daemon=True,
        ).start()

    def _cancel_active_run(self, run_id: str, active: _ActiveDelegatedRun) -> None:
        try:
            active.runtime.abort(active.child_session_id)
        except Exception:
            pass
        if active.terminal.wait(self._cancellation_grace_ms / 1000.0):
            return
        try:
            active.runtime.stop()
        except Exception:
            pass
        active.forced.set()
        self.store.checkpoint_supervision(
            run_id,
            phase="forced",
            reason=active.cancellation_reason or "Delegated runtime ignored cancellation",
            requested_at_ms=_timestamp(None),
            grace_ms=self._cancellation_grace_ms,
        )

    def _publish_parent_progress(
        self,
        parent_session_id: str,
        batch: Mapping[str, object],
        run: Mapping[str, object],
        summary: str,
    ) -> None:
        self.events.publish(
            parent_session_id,
            "tool_progress",
            {
                "toolName": "ime_agents",
                "toolCallId": f"subagent:{batch['id']}",
                "summary": summary,
                "batchId": batch["id"],
                "runId": run["id"],
                "agent": run["templateId"],
                "state": run["state"],
            },
        )


def _delegation_tasks(payload: Mapping[str, object]) -> list[dict[str, str]]:
    raw_tasks = payload.get("tasks")
    if raw_tasks is None:
        raw_tasks = [
            {
                "agent": payload.get("agent"),
                "version": payload.get("version") or "1",
                "task": payload.get("task"),
            }
        ]
    if not isinstance(raw_tasks, list) or not 1 <= len(raw_tasks) <= _MAX_PARALLEL_RUNS:
        raise ValueError("tasks must contain one or two delegated tasks")
    tasks: list[dict[str, str]] = []
    for value in raw_tasks:
        if not isinstance(value, Mapping):
            raise ValueError("each delegated task must be an object")
        tasks.append(
            {
                "agent": _bounded_text(value.get("agent"), maximum=40, required=True),
                "version": _bounded_text(value.get("version") or "1", maximum=12, required=True),
                "task": _bounded_task(value.get("task")),
            }
        )
    return tasks


def _validated_native_fork_sessions(
    runtime_context: object,
    *,
    parent_runtime_binding: Mapping[str, object] | None,
    session_dir: Path,
    agent_dir: Path,
    expected_count: int,
) -> list[dict[str, object]]:
    if not isinstance(runtime_context, Mapping):
        raise ValueError("fork context must be created by the active Pi runtime")
    if str(runtime_context.get("schemaVersion") or "") != "rag-ime.agent-runtime-context.v1":
        raise ValueError("fork runtime context version is unsupported")
    values = runtime_context.get("forkSessions")
    if not isinstance(values, list) or len(values) != expected_count:
        raise ValueError("fork runtime context does not match the delegated task count")

    root = session_dir.expanduser().resolve(strict=False)
    if not isinstance(parent_runtime_binding, Mapping):
        raise ValueError("fork context requires a persisted parent runtime binding")
    if (
        str(parent_runtime_binding.get("driverId") or "") != "managed-pi"
        or str(parent_runtime_binding.get("runtimeKind") or "") != "pi_rpc"
    ):
        raise ValueError("native Pi fork requires a managed Pi parent binding")
    expected_parent_value = str(parent_runtime_binding.get("transcriptRef") or "").strip()
    if not expected_parent_value:
        raise ValueError("fork context requires a persisted parent Pi session")
    expected_parent = Path(expected_parent_value).expanduser().resolve(strict=False)
    if not _managed_regular_file(expected_parent, root):
        raise ValueError("fork parent session is outside the managed session directory")
    parent_records = _read_session_records(expected_parent, label="fork parent session")
    parent_entry_ids = {
        str(record["id"])
        for record in parent_records
        if isinstance(record.get("id"), str) and record.get("id")
    }

    expected_cwd = agent_dir.expanduser().resolve(strict=False)
    seen_paths: set[Path] = set()
    seen_session_ids: set[str] = set()
    resolved: list[dict[str, object]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("fork runtime context contains an invalid session")
        parent_value = str(value.get("parentSessionFile") or "").strip()
        parent = Path(parent_value).expanduser().resolve(strict=False)
        if parent != expected_parent:
            raise ValueError("fork runtime context does not belong to the active parent session")
        parent_leaf_id = _bounded_text(value.get("parentLeafId"), maximum=128, required=True)
        if parent_leaf_id not in parent_entry_ids:
            raise ValueError("fork runtime context references an unknown parent branch leaf")

        session_file_value = str(value.get("sessionFile") or "").strip()
        session_file = Path(session_file_value).expanduser().resolve(strict=False)
        if session_file in seen_paths or not _managed_regular_file(session_file, root):
            raise ValueError("native fork session is duplicated or outside the managed directory")
        mode = session_file.stat().st_mode & 0o777
        if mode & 0o077:
            raise ValueError("native fork session permissions are broader than 0600")
        records = _read_session_records(session_file, label="native fork session")
        header = records[0]
        session_id = _bounded_text(value.get("sessionId"), maximum=128, required=True)
        if str(header.get("id") or "") != session_id:
            raise ValueError("native fork session id does not match its header")
        if session_id in seen_session_ids:
            raise ValueError("native fork session id is duplicated")
        header_parent = Path(str(header.get("parentSession") or "")).expanduser().resolve(
            strict=False
        )
        if header_parent != expected_parent:
            raise ValueError("native fork header does not reference the active parent session")
        header_cwd = Path(str(header.get("cwd") or "")).expanduser().resolve(strict=False)
        if header_cwd != expected_cwd:
            raise ValueError("native fork session has an unexpected runtime working directory")
        branch_entry_ids = {
            str(record["id"])
            for record in records
            if isinstance(record.get("id"), str) and record.get("id")
        }
        if parent_leaf_id not in branch_entry_ids:
            raise ValueError("native fork does not contain the requested parent branch")
        if any(_unsafe_fork_thinking(record) for record in records):
            raise ValueError("native fork still contains provider-bound thinking data")

        seen_paths.add(session_file)
        seen_session_ids.add(session_id)
        resolved.append(
            {
                "sessionId": session_id,
                "path": session_file,
                "parentLeafId": parent_leaf_id,
                "thinkingOverride": str(value.get("thinkingOverride") or ""),
            }
        )
    return resolved


def _managed_regular_file(path: Path, root: Path) -> bool:
    if not _is_within(path, root) or path.is_symlink() or not path.is_file():
        return False
    size = path.stat().st_size
    return 0 < size <= _MAX_FORK_BYTES


def _read_session_records(path: Path, *, label: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} has invalid JSONL at line {line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} contains a non-object record")
        records.append(value)
    if not records or records[0].get("type") != "session":
        raise ValueError(f"{label} is missing its header")
    return records


def _unsafe_fork_thinking(record: Mapping[str, object]) -> bool:
    if str(record.get("type") or "") != "message":
        return False
    message = record.get("message")
    if not isinstance(message, Mapping) or str(message.get("role") or "") != "assistant":
        return False
    provider = str(message.get("provider") or "").lower()
    api = str(message.get("api") or "").lower()
    model = str(message.get("model") or "").lower()
    anthropic = provider == "anthropic" or api == "anthropic-messages" or model.startswith(
        "anthropic/"
    )
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = str(block.get("type") or "")
        if block_type == "redacted_thinking":
            return True
        if block_type != "thinking" or not anthropic:
            continue
        signature = block.get("thinkingSignature") or block.get("signature")
        if block.get("redacted") is True or isinstance(signature, str) and signature:
            return True
    return False


def _subagent_prompt(run: Mapping[str, object], batch: Mapping[str, object]) -> str:
    return (
        "请完成下面这一项有界委派任务。只返回可交给主持会话使用的结果；"
        "不要把自己描述成长期群聊成员，也不要扩大工具或权限。\n\n"
        f"任务：\n{run['task']}\n\n"
        f"上下文模式：{batch['contextMode']}\n"
        f"委派深度：{batch['depth']}/{batch['maxDepth']}"
    )


def _message_summary(message: Mapping[str, object], maximum: int) -> str:
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping) or str(block.get("type") or "") not in {"text", "code"}:
            continue
        data = block.get("data")
        if not isinstance(data, Mapping):
            continue
        text = str(data.get("text") or data.get("code") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)[:maximum]


def _safe_runtime_artifact_payload(event: AgentEventEnvelope) -> dict[str, object]:
    if event.event_type == "text_delta":
        return {"characterCount": len(str(event.payload.get("delta") or ""))}
    if event.event_type == "tool_started":
        return {
            "toolName": str(event.payload.get("toolName") or "")[:120],
            "toolCallId": str(
                event.payload.get("toolCallId") or event.payload.get("callId") or ""
            )[:160],
        }
    if event.event_type == "message_completed":
        message = event.payload.get("message")
        usage = event.payload.get("usage")
        return {
            "messageId": str(message.get("id") or "")[:160]
            if isinstance(message, Mapping)
            else "",
            "role": str(message.get("role") or "")[:40]
            if isinstance(message, Mapping)
            else "",
            "usage": dict(usage) if isinstance(usage, Mapping) else {},
        }
    if event.event_type in {"turn_completed", "turn_failed"}:
        return {
            "status": str(event.payload.get("status") or "")[:80],
            "error": _bounded_text(event.payload.get("error"), maximum=240),
        }
    return {}


def _json_mapping(value: object) -> dict[str, object]:
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _assert_batch_owner(batch: Mapping[str, object], parent_session_id: str) -> None:
    if str(batch.get("parentSessionId") or "") != parent_session_id:
        raise ValueError("delegated run does not belong to this session")


def _batch_payload(row: sqlite3.Row, runs: Sequence[sqlite3.Row]) -> dict[str, object]:
    run_payloads = [_run_payload(item) for item in runs]
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-subagent-batch.v1",
        "id": str(row["id"]),
        "parentSessionId": str(row["parent_session_id"]),
        "parentRunId": str(row["parent_run_id"] or ""),
        "contextMode": str(row["context_mode"]),
        "state": str(row["state"]),
        "depth": int(row["depth"]),
        "maxDepth": int(row["max_depth"]),
        "abortRequested": bool(row["abort_requested"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None,
        "runs": run_payloads,
    }
    for run in run_payloads:
        validate_contract(run, "agent-subagent-run.v1.json")
    validate_contract(payload, "agent-subagent-batch.v1.json")
    return payload


def _run_payload(row: sqlite3.Row) -> dict[str, object]:
    result = json.loads(str(row["result_json"] or "{}"))
    payload: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-subagent-run.v1",
        "id": str(row["id"]),
        "batchId": str(row["batch_id"]),
        "childSessionId": str(row["child_session_id"]),
        "templateId": str(row["template_id"]),
        "templateVersion": str(row["template_version"]),
        "ordinal": int(row["ordinal"]),
        "task": str(row["task_text"]),
        "state": str(row["state"]),
        "budget": {
            "maxTurns": int(row["max_turns"]),
            "maxToolCalls": int(row["max_tool_calls"]),
            "maxTotalTokens": int(row["max_total_tokens"]),
            "maxDurationMs": int(row["max_duration_ms"]),
            "maxOutputChars": int(row["max_output_chars"]),
        },
        "usage": {
            "turnCount": int(row["turn_count"]),
            "toolCount": int(row["tool_count"]),
            "totalTokens": int(row["total_tokens"]),
        },
        "result": result if isinstance(result, dict) else {},
        "error": str(row["error"] or ""),
        "createdAtMs": int(row["created_at_ms"]),
        "startedAtMs": int(row["started_at_ms"]) if row["started_at_ms"] is not None else None,
        "updatedAtMs": int(row["updated_at_ms"]),
        "completedAtMs": int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None,
    }
    validate_contract(payload, "agent-subagent-run.v1.json")
    return payload


def _required_text(value: Mapping[str, object], key: str) -> str:
    return _bounded_text(value.get(key), maximum=240, required=True)


def _bounded_text(value: object, *, maximum: int, required: bool = False) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise ValueError("required delegation text is missing")
    return text[:maximum]


def _bounded_task(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("delegated task must not be empty")
    return text[:8_000]


def _bounded_int(value: object, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("delegation budget value is invalid") from exc
    if not minimum <= number <= maximum:
        raise ValueError("delegation budget value is outside the managed range")
    return number


def _subagent_session_retention_from_environment() -> int:
    return (
        _bounded_environment_int(
            "RAG_IME_SUBAGENT_SESSION_RETENTION_HOURS",
            default=72,
            minimum=1,
            maximum=30 * 24,
        )
        * 60
        * 60
        * 1_000
    )


def _subagent_session_gc_interval_from_environment() -> int:
    return (
        _bounded_environment_int(
            "RAG_IME_SUBAGENT_SESSION_GC_INTERVAL_SECONDS",
            default=15 * 60,
            minimum=60,
            maximum=24 * 60 * 60,
        )
        * 1_000
    )


def _bounded_environment_int(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _timestamp(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
