from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Protocol


_PROJECTION_KIND = "graphiti"
_MAX_REPLAY_IDS = 500
_DELETE_OPERATIONS = {"delete", "remove", "tombstone"}


class ProjectionAdapterUnavailable(RuntimeError):
    """Raised when an optional projection backend is not installed or configured."""


@dataclass(frozen=True)
class ProjectionApplyResult:
    external_id: str = ""


class ProjectionAdapter(Protocol):
    """Idempotent graph projection boundary.

    Implementations must treat ``(aggregate_type, aggregate_id, revision)`` as
    an idempotency key. A worker can replay an item when it crashes after the
    external write but before updating SQLite.
    """

    def apply(
        self,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        revision: int,
        payload: dict[str, object],
    ) -> ProjectionApplyResult | str | None: ...


class NullProjectionAdapter:
    """Safe default when Graphiti is not installed.

    The module deliberately never imports Graphiti. Applications that do not
    configure a real adapter keep using SQLite retrieval normally; if this
    adapter is run explicitly, the outbox item is retried/dead-lettered rather
    than falsely marked as projected.
    """

    def apply(
        self,
        *,
        operation: str,
        aggregate_type: str,
        aggregate_id: str,
        revision: int,
        payload: dict[str, object],
    ) -> ProjectionApplyResult:
        del operation, aggregate_type, aggregate_id, revision, payload
        raise ProjectionAdapterUnavailable("Graphiti projection adapter is not configured")


@dataclass(frozen=True)
class ProjectionRunReport:
    recovered: int = 0
    claimed: int = 0
    applied: int = 0
    superseded: int = 0
    failed: int = 0
    dead: int = 0

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.memory-graph-projection-run.v1",
            "projectionKind": _PROJECTION_KIND,
            "recovered": self.recovered,
            "claimed": self.claimed,
            "applied": self.applied,
            "superseded": self.superseded,
            "failed": self.failed,
            "dead": self.dead,
        }


@dataclass(frozen=True)
class _OutboxTask:
    outbox_id: int
    aggregate_type: str
    aggregate_id: str
    operation: str
    revision: int
    payload_json: str
    attempts: int


class GraphProjectionWorker:
    """Bounded, failure-isolated consumer for the optional Graphiti projection.

    The checkpoint is an observability high-water mark, not a consumption
    cursor. Claiming always consults per-row state, so an earlier failed row is
    never hidden merely because a later row completed.
    """

    def __init__(
        self,
        db_path: str | Path,
        adapter: ProjectionAdapter,
        *,
        batch_size: int = 32,
        max_attempts: int = 5,
        base_backoff_ms: int = 1_000,
        max_backoff_ms: int = 60_000,
        processing_timeout_ms: int = 5 * 60_000,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.adapter = adapter
        self.batch_size = max(1, min(256, int(batch_size)))
        self.max_attempts = max(1, int(max_attempts))
        self.base_backoff_ms = max(0, int(base_backoff_ms))
        self.max_backoff_ms = max(self.base_backoff_ms, int(max_backoff_ms))
        self.processing_timeout_ms = max(1, int(processing_timeout_ms))
        self._clock = clock or _now_ms

    def run_once(self, *, now_ms: int | None = None) -> ProjectionRunReport:
        """Process at most ``batch_size`` items and contain adapter failures."""

        # Source deletion is tracked in SQLite, then converted into graph delete
        # revisions incrementally. This keeps the optional projection current
        # without putting Graphiti on the canonical retrieval path.
        from .memory_graph import MemoryGraphStore

        MemoryGraphStore(self.db_path).drain_dirty_sources(limit=self.batch_size * 4)
        now = self._clock() if now_ms is None else int(now_ms)
        recovered = self.recover_stuck(now_ms=now)
        tasks = self._claim(now_ms=now)
        applied = superseded = failed = dead = 0
        for task in tasks:
            if task.revision < self._latest_known_revision(task):
                self._mark_superseded(task, now_ms=now)
                superseded += 1
                continue
            try:
                payload = json.loads(task.payload_json)
                if not isinstance(payload, dict):
                    raise ValueError("projection payload_json must contain a JSON object")
                result = self.adapter.apply(
                    operation=task.operation,
                    aggregate_type=task.aggregate_type,
                    aggregate_id=task.aggregate_id,
                    revision=task.revision,
                    payload=payload,
                )
                self._mark_applied(task, result=result, now_ms=now)
                applied += 1
            except Exception as exc:  # Adapter failures must not escape into retrieval.
                state = self._mark_failed(task, error=exc, now_ms=now)
                if state == "dead":
                    dead += 1
                else:
                    failed += 1
        return ProjectionRunReport(
            recovered=recovered,
            claimed=len(tasks),
            applied=applied,
            superseded=superseded,
            failed=failed,
            dead=dead,
        )

    def recover_stuck(self, *, now_ms: int | None = None) -> int:
        """Return expired processing leases to retry/dead state in a bounded batch."""

        now = self._clock() if now_ms is None else int(now_ms)
        stale_before = now - self.processing_timeout_ms
        recovery_limit = self.batch_size * 4
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT outbox_id, attempts
                FROM memory_projection_outbox
                WHERE projection_kind = ?
                  AND state = 'processing'
                  AND updated_at_ms <= ?
                ORDER BY outbox_id
                LIMIT ?
                """,
                (_PROJECTION_KIND, stale_before, recovery_limit),
            ).fetchall()
            for row in rows:
                next_attempts = int(row["attempts"]) + 1
                state = "dead" if next_attempts >= self.max_attempts else "failed"
                conn.execute(
                    """
                    UPDATE memory_projection_outbox
                    SET state = ?, attempts = ?, available_at_ms = ?, updated_at_ms = ?,
                        last_error = 'processing lease expired'
                    WHERE outbox_id = ? AND projection_kind = ? AND state = 'processing'
                    """,
                    (state, next_attempts, now, now, int(row["outbox_id"]), _PROJECTION_KIND),
                )
        return len(rows)

    def replay(self, *, outbox_ids: Iterable[int], now_ms: int | None = None) -> int:
        """Explicitly requeue selected graph items without deleting their audit rows."""

        ids = tuple(sorted({int(item) for item in outbox_ids if int(item) > 0}))
        if not ids:
            return 0
        if len(ids) > _MAX_REPLAY_IDS:
            raise ValueError(f"replay accepts at most {_MAX_REPLAY_IDS} outbox ids")
        now = self._clock() if now_ms is None else int(now_ms)
        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE memory_projection_outbox
                SET state = 'pending', attempts = 0, available_at_ms = ?,
                    updated_at_ms = ?, processed_at_ms = NULL, last_error = NULL
                WHERE projection_kind = ?
                  AND outbox_id IN ({placeholders})
                  AND state IN ('applied', 'failed', 'dead')
                """,
                (now, now, _PROJECTION_KIND, *ids),
            )
        return int(cursor.rowcount)

    def _claim(self, *, now_ms: int) -> tuple[_OutboxTask, ...]:
        claimed: list[_OutboxTask] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    """
                    SELECT outbox_id, aggregate_type, aggregate_id, operation,
                           revision, payload_json, attempts
                    FROM memory_projection_outbox
                    WHERE projection_kind = ?
                      AND state IN ('pending', 'failed')
                      AND attempts < ?
                      AND available_at_ms <= ?
                    ORDER BY outbox_id
                    LIMIT ?
                    """,
                    (_PROJECTION_KIND, self.max_attempts, now_ms, self.batch_size),
                ).fetchall()
                for row in rows:
                    cursor = conn.execute(
                        """
                        UPDATE memory_projection_outbox
                        SET state = 'processing', updated_at_ms = ?
                        WHERE outbox_id = ? AND projection_kind = ?
                          AND state IN ('pending', 'failed')
                        """,
                        (now_ms, int(row["outbox_id"]), _PROJECTION_KIND),
                    )
                    if cursor.rowcount != 1:
                        continue
                    claimed.append(
                        _OutboxTask(
                            outbox_id=int(row["outbox_id"]),
                            aggregate_type=str(row["aggregate_type"]),
                            aggregate_id=str(row["aggregate_id"]),
                            operation=str(row["operation"]),
                            revision=int(row["revision"]),
                            payload_json=str(row["payload_json"]),
                            attempts=int(row["attempts"]),
                        )
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return tuple(claimed)

    def _mark_applied(
        self,
        task: _OutboxTask,
        *,
        result: ProjectionApplyResult | str | None,
        now_ms: int,
    ) -> None:
        external_id = _external_id(result) or task.aggregate_id
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    """
                    UPDATE memory_projection_outbox
                    SET state = 'applied', processed_at_ms = ?, updated_at_ms = ?,
                        last_error = NULL
                    WHERE outbox_id = ? AND projection_kind = ? AND state = 'processing'
                    """,
                    (now_ms, now_ms, task.outbox_id, _PROJECTION_KIND),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return
                self._advance_checkpoint(conn, outbox_id=task.outbox_id, now_ms=now_ms)
                if task.operation.strip().lower() in _DELETE_OPERATIONS:
                    conn.execute(
                        """
                        DELETE FROM memory_graph_projection_map
                        WHERE projection_kind = ?
                          AND aggregate_type = ?
                          AND aggregate_id = ?
                          AND revision <= ?
                        """,
                        (
                            _PROJECTION_KIND,
                            task.aggregate_type,
                            task.aggregate_id,
                            task.revision,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO memory_graph_projection_map(
                            projection_kind, aggregate_type, aggregate_id,
                            external_id, revision, updated_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(projection_kind, aggregate_type, aggregate_id) DO UPDATE SET
                            external_id = excluded.external_id,
                            revision = excluded.revision,
                            updated_at_ms = excluded.updated_at_ms
                        WHERE excluded.revision >= memory_graph_projection_map.revision
                        """,
                        (
                            _PROJECTION_KIND,
                            task.aggregate_type,
                            task.aggregate_id,
                            external_id,
                            task.revision,
                            now_ms,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _latest_known_revision(self, task: _OutboxTask) -> int:
        """Read the canonical projection high revision before external effects.

        Outbox history remains authoritative even after a delete removes the
        live mapping, preventing an explicitly replayed stale upsert from
        resurrecting a newer tombstone.
        """

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(revision)
                FROM (
                    SELECT revision
                    FROM memory_graph_projection_map
                    WHERE projection_kind = ?
                      AND aggregate_type = ?
                      AND aggregate_id = ?
                    UNION ALL
                    SELECT revision
                    FROM memory_projection_outbox
                    WHERE projection_kind = ?
                      AND aggregate_type = ?
                      AND aggregate_id = ?
                )
                """,
                (
                    _PROJECTION_KIND,
                    task.aggregate_type,
                    task.aggregate_id,
                    _PROJECTION_KIND,
                    task.aggregate_type,
                    task.aggregate_id,
                ),
            ).fetchone()
        return int(row[0] or task.revision)

    def _mark_superseded(self, task: _OutboxTask, *, now_ms: int) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    """
                    UPDATE memory_projection_outbox
                    SET state = 'applied', processed_at_ms = ?, updated_at_ms = ?,
                        last_error = NULL
                    WHERE outbox_id = ? AND projection_kind = ? AND state = 'processing'
                    """,
                    (now_ms, now_ms, task.outbox_id, _PROJECTION_KIND),
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return
                self._advance_checkpoint(conn, outbox_id=task.outbox_id, now_ms=now_ms)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _advance_checkpoint(
        conn: sqlite3.Connection,
        *,
        outbox_id: int,
        now_ms: int,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_projection_checkpoints(
                projection_kind, last_outbox_id, updated_at_ms
            ) VALUES (?, ?, ?)
            ON CONFLICT(projection_kind) DO UPDATE SET
                last_outbox_id = MAX(
                    memory_projection_checkpoints.last_outbox_id,
                    excluded.last_outbox_id
                ),
                updated_at_ms = excluded.updated_at_ms
            """,
            (_PROJECTION_KIND, outbox_id, now_ms),
        )

    def _mark_failed(self, task: _OutboxTask, *, error: Exception, now_ms: int) -> str:
        next_attempts = task.attempts + 1
        state = "dead" if next_attempts >= self.max_attempts else "failed"
        available_at_ms = now_ms
        if state == "failed":
            exponent = min(next_attempts - 1, 30)
            available_at_ms += min(self.max_backoff_ms, self.base_backoff_ms * (2**exponent))
        message = " ".join(str(error).split()).strip() or error.__class__.__name__
        message = message[:1_000]
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE memory_projection_outbox
                SET state = ?, attempts = ?, available_at_ms = ?, updated_at_ms = ?,
                    last_error = ?
                WHERE outbox_id = ? AND projection_kind = ? AND state = 'processing'
                """,
                (
                    state,
                    next_attempts,
                    available_at_ms,
                    now_ms,
                    message,
                    task.outbox_id,
                    _PROJECTION_KIND,
                ),
            )
        return state

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            if conn.in_transaction:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()


def _external_id(result: ProjectionApplyResult | str | None) -> str:
    if isinstance(result, ProjectionApplyResult):
        return result.external_id.strip()
    if isinstance(result, str):
        return result.strip()
    return ""


def _now_ms() -> int:
    return int(time.time() * 1_000)
