from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from .agent_events import AgentEventHub
from .agent_protocol import AgentEventEnvelope
from .agent_runtime_driver import (
    AgentRuntimeDriver,
    AgentRuntimeError,
    RuntimeDriverContext,
    RuntimeDriverFactory,
)
from .agent_sessions import AgentSessionStore
from .agent_templates import AgentTemplate, agent_template, agent_template_catalog
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .pi_runtime import PiRuntimeConfig, PiRuntimeDriverFactory, PiRuntimeManager


_TERMINAL_STATES = frozenset({"completed", "failed", "aborted", "timed_out"})
_ACTIVE_STATES = frozenset({"queued", "running"})
_MAX_PARALLEL_RUNS = 2
_MAX_FORK_BYTES = 32 * 1024 * 1024


class AgentDelegationStore:
    """Durable lifecycle index for bounded task subagents."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)
            now = _timestamp(None)
            interrupted = conn.execute(
                "SELECT id FROM agent_subagent_runs WHERE state IN ('queued', 'running')"
            ).fetchall()
            for row in interrupted:
                run_id = str(row["id"])
                conn.execute(
                    """
                    UPDATE agent_subagent_runs
                    SET state = 'failed', error = ?, updated_at_ms = ?, completed_at_ms = ?
                    WHERE id = ?
                    """,
                    ("Sidecar restarted before the delegated task completed", now, now, run_id),
                )
                self._append_event_conn(
                    conn,
                    run_id=run_id,
                    event_type="failed",
                    payload={"reason": "sidecar_restarted"},
                    created_at_ms=now,
                )
            batch_ids = {
                str(row["batch_id"])
                for row in conn.execute(
                    "SELECT DISTINCT batch_id FROM agent_subagent_runs WHERE completed_at_ms = ?",
                    (now,),
                ).fetchall()
            }
            for batch_id in batch_ids:
                self._refresh_batch_conn(conn, batch_id, updated_at_ms=now)

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
                        _required_text(value, "childSessionId"),
                        _required_text(value, "templateId"),
                        _required_text(value, "templateVersion"),
                        ordinal,
                        _bounded_task(value.get("task")),
                        _bounded_int(value.get("maxTurns"), minimum=1, maximum=32),
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
        return _batch_payload(row, runs)

    def get_run(self, run_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_subagent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run_payload(row)

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
        return self.get_run(run_id)

    def request_abort(self, identifier: str, *, requested_at_ms: int | None = None) -> list[str]:
        now = _timestamp(requested_at_ms)
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
        return active

    def append_budget_event(self, run_id: str, reason: str) -> None:
        with self._connect() as conn:
            self._append_event_conn(
                conn,
                run_id=run_id,
                event_type="budget_exceeded",
                payload={"reason": _bounded_text(reason, maximum=240)},
                created_at_ms=_timestamp(None),
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
    ) -> None:
        self.store = AgentDelegationStore(db_path)
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
        self._lock = threading.RLock()
        self._active_runtimes: dict[str, AgentRuntimeDriver] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False

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
        if parent.get("status") == "archived":
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
        parent_run = self.store.run_for_child_session(parent_session_id)
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
                    child = self.sessions.create(
                        title=f"{template.display_name} · {_bounded_text(task['task'], maximum=72)}",
                        mode="assistant",
                        role_id=str(parent.get("roleId") or "zhiyou-v1"),
                        role_version=str(parent.get("roleVersion") or "1"),
                        model_profile=str(parent.get("modelProfile") or "pi/default"),
                        tool_profile_version=template.tool_profile_version,
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
                run_id = str(run["id"])
                thread = threading.Thread(
                    target=self._run_task,
                    args=(run_id,),
                    name=f"rag-ime-{run_id[-8:]}",
                    daemon=True,
                )
                self._threads[run_id] = thread
                thread.start()

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
            self._abort_runtime(run_id)
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
                return batch
            time.sleep(0.025)
        self.store.request_abort(batch_id)
        for run in batch["runs"]:
            if str(run["state"]) in _ACTIVE_STATES:
                self._abort_runtime(str(run["id"]))
        return self.store.get_batch(batch_id)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            runtimes = list(self._active_runtimes.values())
        for runtime in runtimes:
            try:
                runtime.stop()
            except Exception:
                pass

    def reconfigure(self, config: PiRuntimeConfig) -> None:
        self.close()
        with self._lock:
            self.runtime_config = config
            self._runtime_driver_factory.reconfigure(config)
            self._tool_gateway_token = config.tool_gateway_token
            self._closed = False

    def refresh_runtime_factory(self) -> None:
        """Restart delegated-driver ownership after Kernel policy changes."""

        self.close()
        with self._lock:
            factory_config = getattr(self._runtime_driver_factory, "config", None)
            if isinstance(factory_config, PiRuntimeConfig):
                self.runtime_config = factory_config
                self._tool_gateway_token = factory_config.tool_gateway_token
            self._closed = False

    def owns_session(self, session_id: str) -> bool:
        return self.store.owns_session(session_id)

    def _run_task(self, run_id: str) -> None:
        run = self.store.start_run(run_id)
        batch = self.store.get_batch(str(run["batchId"]))
        child_session_id = str(run["childSessionId"])
        parent_session_id = str(batch["parentSessionId"])
        terminal = threading.Event()
        terminal_error = ""
        completed = False
        budget_reason = ""
        last_message: dict[str, object] = {}
        turn_count = 0
        total_tokens = 0
        output_chars = 0
        tool_ids: set[str] = set()
        update_lock = threading.RLock()
        abort_scheduled = False

        def schedule_budget_abort(reason: str) -> None:
            nonlocal budget_reason, abort_scheduled
            with update_lock:
                if abort_scheduled:
                    return
                budget_reason = reason
                abort_scheduled = True
                self.store.append_budget_event(run_id, reason)
            threading.Thread(
                target=self._abort_runtime,
                args=(run_id,),
                name=f"rag-ime-budget-stop-{run_id[-8:]}",
                daemon=True,
            ).start()

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
                elif event.event_type == "message_completed":
                    message = event.payload.get("message")
                    if isinstance(message, Mapping) and str(message.get("role") or "") == "assistant":
                        turn_count += 1
                        last_message = dict(message)
                        usage = event.payload.get("usage")
                        if isinstance(usage, Mapping):
                            total_tokens += max(0, int(usage.get("totalTokens") or 0))
                elif event.event_type == "turn_completed":
                    completed = True
                    terminal.set()
                elif event.event_type == "turn_failed":
                    terminal_error = _bounded_text(
                        event.payload.get("error") or "delegated Pi turn failed",
                        maximum=500,
                    )
                    terminal.set()

                budget = run["budget"]
                if turn_count > int(budget["maxTurns"]):
                    schedule_budget_abort("turn budget exceeded")
                elif len(tool_ids) > int(budget["maxToolCalls"]):
                    schedule_budget_abort("tool-call budget exceeded")
                elif total_tokens > int(budget["maxTotalTokens"]):
                    schedule_budget_abort("token budget exceeded")
                elif output_chars > int(budget["maxOutputChars"]):
                    schedule_budget_abort("output budget exceeded")

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
                ),
                purpose="delegated",
                session_context_provider=lambda _session: context,
            )
        with self._lock:
            self._active_runtimes[run_id] = runtime
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
                if not terminal.wait(duration_seconds):
                    budget_reason = "duration budget exceeded"
                    self.store.append_budget_event(run_id, budget_reason)
                    try:
                        runtime.abort(child_session_id)
                    except Exception:
                        runtime.stop()
                    state = "timed_out"
                    error = budget_reason
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
            try:
                runtime.stop()
            except Exception:
                pass
            with self._lock:
                self._active_runtimes.pop(run_id, None)
                self._threads.pop(run_id, None)

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

    def _abort_runtime(self, run_id: str) -> None:
        with self._lock:
            runtime = self._active_runtimes.get(run_id)
        if runtime is None:
            return
        run = self.store.get_run(run_id)
        try:
            runtime.abort(str(run["childSessionId"]))
        except Exception:
            try:
                runtime.stop()
            except Exception:
                pass

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


def _timestamp(value: int | None) -> int:
    return int(value if value is not None else time.time() * 1000)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
