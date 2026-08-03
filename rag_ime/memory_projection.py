from __future__ import annotations

import json
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable

from .db.migration_runner import DEFAULT_MIGRATIONS_DIR
from .embeddings import EmbeddingProvider
from .memory_ingest import normalize_text
from .text_utils import compact_whitespace, now_ms


RETRIEVAL_DOCS_PROJECTION = "retrieval_docs"
RETRIEVAL_VECTORS_PROJECTION = "retrieval_vectors"
MEMORY_PROJECTION_SCHEMA_VERSION = "rag-ime.memory-projection.v1"
DEFAULT_PROCESSING_LEASE_MS = 5 * 60 * 1000

ConnectionFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]


class MemoryProjectionWorker:
    """Poll durable projection events outside the foreground write/query path."""

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        projection_kinds: tuple[str, ...] = (),
        poll_interval_s: float = 1.0,
        max_events: int = 32,
        max_attempts: int = 5,
        processing_lease_ms: int = DEFAULT_PROCESSING_LEASE_MS,
    ) -> None:
        self.connection_factory = connection_factory
        self.embedding_provider = embedding_provider
        self.projection_kinds = tuple(
            dict.fromkeys(
                compact_whitespace(value)
                for value in projection_kinds
                if compact_whitespace(value)
            )
        )
        self.poll_interval_s = max(0.05, float(poll_interval_s))
        self.max_events = max(1, int(max_events))
        self.max_attempts = max(1, int(max_attempts))
        self.processing_lease_ms = max(1_000, int(processing_lease_ms))
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._last_report: dict[str, object] = {}
        self._last_error = ""
        self._last_run_at_ms = 0

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(
                target=self._run,
                name="memory-projection-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout_s: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout_s)))

    def run_once(self) -> dict[str, object]:
        try:
            with self.connection_factory() as conn:
                report = process_memory_projection_outbox(
                    conn,
                    embedding_provider=self.embedding_provider,
                    projection_kinds=self.projection_kinds,
                    max_events=self.max_events,
                    max_attempts=self.max_attempts,
                    processing_lease_ms=self.processing_lease_ms,
                )
        except Exception as exc:  # pragma: no cover - last-resort daemon guard
            error = f"{exc.__class__.__name__}: {exc}"[:1000]
            with self._lock:
                self._last_error = error
                self._last_run_at_ms = now_ms()
            return {
                "schemaVersion": MEMORY_PROJECTION_SCHEMA_VERSION,
                "ok": False,
                "error": error,
            }
        with self._lock:
            self._last_report = report
            self._last_error = ""
            self._last_run_at_ms = now_ms()
        return {"ok": True, **report}

    def status(self) -> dict[str, object]:
        with self._lock:
            thread = self._thread
            return {
                "schemaVersion": MEMORY_PROJECTION_SCHEMA_VERSION,
                "running": bool(thread and thread.is_alive() and not self._stop.is_set()),
                "projectionKinds": list(self.projection_kinds),
                "lastRunAtMs": self._last_run_at_ms,
                "lastError": self._last_error,
                "lastReport": dict(self._last_report),
            }

    def _run(self) -> None:
        self.run_once()
        while not self._stop.wait(self.poll_interval_s):
            self.run_once()


def enqueue_memory_projection(
    conn: sqlite3.Connection,
    *,
    projection_kind: str,
    aggregate_type: str,
    aggregate_id: str,
    operation: str,
    project: str = "",
    revision: int | None = None,
    payload: dict[str, object] | None = None,
    available_at_ms: int | None = None,
) -> int:
    """Append one idempotent event in the caller's source-write transaction."""

    kind = compact_whitespace(projection_kind)
    if not kind:
        raise ValueError("projection_kind must not be empty")
    aggregate = compact_whitespace(aggregate_type) or "project"
    aggregate_key = compact_whitespace(aggregate_id) or "default"
    resolved_operation = compact_whitespace(operation) or "upsert"
    timestamp = now_ms()
    if revision is None:
        row = conn.execute(
            """
            SELECT MAX(revision)
            FROM memory_projection_outbox
            WHERE projection_kind = ? AND aggregate_type = ? AND aggregate_id = ?
            """,
            (kind, aggregate, aggregate_key),
        ).fetchone()
        resolved_revision = max(timestamp, int(row[0] or 0) + 1)
    else:
        resolved_revision = max(1, int(revision))
    event_payload = {
        "schemaVersion": MEMORY_PROJECTION_SCHEMA_VERSION,
        "project": compact_whitespace(project),
        **dict(payload or {}),
    }
    conn.execute(
        """
        INSERT INTO memory_projection_outbox(
            projection_kind, aggregate_type, aggregate_id, operation, revision,
            payload_json, state, attempts, available_at_ms, created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
        ON CONFLICT(
            projection_kind, aggregate_type, aggregate_id, operation, revision
        ) DO NOTHING
        """,
        (
            kind,
            aggregate,
            aggregate_key,
            resolved_operation,
            resolved_revision,
            json.dumps(event_payload, ensure_ascii=False, sort_keys=True),
            timestamp if available_at_ms is None else max(0, int(available_at_ms)),
            timestamp,
            timestamp,
        ),
    )
    row = conn.execute(
        """
        SELECT outbox_id
        FROM memory_projection_outbox
        WHERE projection_kind = ? AND aggregate_type = ? AND aggregate_id = ?
          AND operation = ? AND revision = ?
        """,
        (kind, aggregate, aggregate_key, resolved_operation, resolved_revision),
    ).fetchone()
    if row is None:  # pragma: no cover - protected by the unique key
        raise RuntimeError("projection event was not persisted")
    return int(row[0])


def process_memory_projection_outbox(
    conn: sqlite3.Connection,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    projection_kinds: tuple[str, ...] = (),
    max_events: int = 32,
    max_attempts: int = 5,
    processing_lease_ms: int = DEFAULT_PROCESSING_LEASE_MS,
    current_ms: int | None = None,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    preverified_schema: bool = False,
) -> dict[str, object]:
    """Claim and materialize a bounded batch with retry and lease recovery.

    This function owns transaction boundaries so a claim survives a worker
    crash. Call it on a worker-dedicated connection, never inside a source
    transaction. Source code only calls :func:`enqueue_memory_projection`.
    """

    timestamp = now_ms() if current_ms is None else max(0, int(current_ms))
    attempt_limit = max(1, int(max_attempts))
    kinds = tuple(
        dict.fromkeys(
            compact_whitespace(value)
            for value in projection_kinds
            if compact_whitespace(value)
        )
    )
    recovered, recovered_dead = _recover_expired_leases(
        conn,
        timestamp=timestamp,
        max_attempts=attempt_limit,
        lease_ms=max(1_000, int(processing_lease_ms)),
        projection_kinds=kinds,
    )
    conn.commit()
    _enqueue_vector_catchup_if_needed(
        conn,
        embedding_provider=embedding_provider,
        timestamp=timestamp,
    )
    conn.commit()

    applied: list[int] = []
    failed: list[int] = []
    dead: list[int] = list(recovered_dead)
    results: list[dict[str, object]] = []
    for _ in range(max(1, int(max_events))):
        row = _next_ready_event(conn, timestamp=timestamp, projection_kinds=kinds)
        if row is None:
            break
        outbox_id = int(row["outbox_id"])
        attempts = int(row["attempts"] or 0) + 1
        claimed = conn.execute(
            """
            UPDATE memory_projection_outbox
            SET state = 'processing', attempts = ?, updated_at_ms = ?, last_error = NULL
            WHERE outbox_id = ?
              AND state IN ('pending', 'failed')
              AND available_at_ms <= ?
            """,
            (attempts, timestamp, outbox_id, timestamp),
        )
        if claimed.rowcount != 1:
            conn.rollback()
            continue
        # Persist the lease before materialization. A process death can now be
        # recovered instead of making the event disappear.
        conn.commit()
        try:
            result = _materialize_event(
                conn,
                row=row,
                embedding_provider=embedding_provider,
                timestamp=timestamp,
                migrations_dir=migrations_dir,
                preverified_schema=preverified_schema,
            )
            conn.execute(
                """
                UPDATE memory_projection_outbox
                SET state = 'applied', processed_at_ms = ?, updated_at_ms = ?,
                    last_error = ?
                WHERE outbox_id = ? AND state = 'processing'
                """,
                (
                    timestamp,
                    timestamp,
                    compact_whitespace(str(result.get("skippedReason") or "")) or None,
                    outbox_id,
                ),
            )
            _advance_checkpoint(
                conn,
                projection_kind=str(row["projection_kind"]),
                timestamp=timestamp,
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            terminal = attempts >= attempt_limit
            next_state = "dead" if terminal else "failed"
            retry_at = timestamp if terminal else timestamp + _retry_delay_ms(attempts)
            conn.execute(
                """
                UPDATE memory_projection_outbox
                SET state = ?, available_at_ms = ?, processed_at_ms = ?,
                    updated_at_ms = ?, last_error = ?
                WHERE outbox_id = ? AND state = 'processing'
                """,
                (
                    next_state,
                    retry_at,
                    timestamp if terminal else None,
                    timestamp,
                    f"{exc.__class__.__name__}: {exc}"[:1000],
                    outbox_id,
                ),
            )
            conn.commit()
            (dead if terminal else failed).append(outbox_id)
            continue
        applied.append(outbox_id)
        results.append({"outboxId": outbox_id, **result})

    freshness = memory_projection_freshness(
        conn,
        provider_fingerprint=str(getattr(embedding_provider, "fingerprint", "") or ""),
        current_ms=timestamp,
        processing_lease_ms=processing_lease_ms,
    )
    return {
        "schemaVersion": MEMORY_PROJECTION_SCHEMA_VERSION,
        "processed": len(applied) + len(failed) + len(dead),
        "recovered": recovered,
        "applied": applied,
        "failed": failed,
        "dead": dead,
        "results": results,
        "freshness": freshness,
    }


def memory_projection_freshness(
    conn: sqlite3.Connection,
    *,
    provider_fingerprint: str = "",
    current_ms: int | None = None,
    processing_lease_ms: int = DEFAULT_PROCESSING_LEASE_MS,
) -> dict[str, object]:
    timestamp = now_ms() if current_ms is None else max(0, int(current_ms))
    states = {
        state: 0
        for state in ("pending", "processing", "applied", "failed", "dead")
    }
    states.update(
        {
            str(row["state"]): int(row["count"] or 0)
            for row in conn.execute(
                "SELECT state, COUNT(*) AS count FROM memory_projection_outbox GROUP BY state"
            ).fetchall()
        }
    )
    oldest_ready = conn.execute(
        """
        SELECT MIN(created_at_ms)
        FROM memory_projection_outbox
        WHERE state IN ('pending', 'failed', 'processing')
        """
    ).fetchone()[0]
    ready_backlog = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_projection_outbox
            WHERE state IN ('pending', 'failed') AND available_at_ms <= ?
            """,
            (timestamp,),
        ).fetchone()[0]
    )
    expired_leases = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_projection_outbox
            WHERE state = 'processing' AND updated_at_ms < ?
            """,
            (timestamp - max(1_000, int(processing_lease_ms)),),
        ).fetchone()[0]
    )
    source_count = (
        _max_value(
            conn,
            "SELECT COUNT(*) FROM memory_items "
            "WHERE status IN ('active', 'approved') AND privacy_class != 'sensitive'",
        )
        + _max_value(conn, "SELECT COUNT(*) FROM memory_atoms WHERE status IN ('active', 'approved')")
        + _max_value(
            conn,
            "SELECT COUNT(*) FROM memory_books WHERE status IN ('active', 'approved', 'archived')",
        )
    )
    source_updated_at = max(
        _max_value(
            conn,
            "SELECT MAX(updated_at_ms) FROM memory_items "
            "WHERE status IN ('active', 'approved') AND privacy_class != 'sensitive'",
        ),
        _max_value(
            conn,
            "SELECT MAX(updated_at_ms) FROM memory_atoms WHERE status IN ('active', 'approved')",
        ),
        _max_value(
            conn,
            "SELECT MAX(updated_at_ms) FROM memory_books "
            "WHERE status IN ('active', 'approved', 'archived')",
        ),
    )
    docs_updated_at = _max_value(conn, "SELECT MAX(updated_at_ms) FROM memory_retrieval_docs")
    docs_total = _max_value(
        conn,
        "SELECT COUNT(*) FROM memory_retrieval_docs WHERE status = 'active'",
    )
    fingerprint = compact_whitespace(provider_fingerprint)
    provider_enabled = bool(fingerprint and fingerprint != "none")
    vector_total = 0
    stale_vectors = 0
    missing_vectors = 0
    if provider_enabled:
        vector_row = conn.execute(
            """
            SELECT
                COUNT(v.doc_id) AS vector_count,
                SUM(CASE WHEN v.doc_id IS NULL THEN 1 ELSE 0 END) AS missing_count,
                SUM(
                    CASE
                        WHEN v.doc_id IS NOT NULL AND (
                            v.source_revision != d.source_revision
                            OR v.projection_version != d.projection_version
                        )
                        THEN 1 ELSE 0
                    END
                ) AS stale_count
            FROM memory_retrieval_docs d
            LEFT JOIN memory_retrieval_doc_vectors v
              ON v.doc_id = d.doc_id AND v.provider_fingerprint = ?
            WHERE d.status = 'active'
            """,
            (fingerprint,),
        ).fetchone()
        vector_total = int(vector_row["vector_count"] or 0)
        missing_vectors = int(vector_row["missing_count"] or 0)
        stale_vectors = int(vector_row["stale_count"] or 0)
    checkpoints = {
        str(row["projection_kind"]): {
            "lastOutboxId": int(row["last_outbox_id"] or 0),
            "updatedAtMs": int(row["updated_at_ms"] or 0),
        }
        for row in conn.execute(
            "SELECT projection_kind, last_outbox_id, updated_at_ms "
            "FROM memory_projection_checkpoints"
        ).fetchall()
    }
    latest_outbox = {
        str(row["projection_kind"]): int(row["last_outbox_id"] or 0)
        for row in conn.execute(
            "SELECT projection_kind, MAX(outbox_id) AS last_outbox_id "
            "FROM memory_projection_outbox GROUP BY projection_kind"
        ).fetchall()
    }
    checkpoint_lag = {
        kind: max(
            0,
            outbox_id
            - int(dict(checkpoints.get(kind) or {}).get("lastOutboxId") or 0),
        )
        for kind, outbox_id in latest_outbox.items()
    }
    checkpoint_caught_up = all(value == 0 for value in checkpoint_lag.values())
    projection_initialized = source_count == 0 or bool(latest_outbox)
    backlog = sum(states[state] for state in ("pending", "failed", "processing"))
    vector_coverage = (vector_total / docs_total) if docs_total else 1.0
    vector_fresh = not provider_enabled or (
        missing_vectors == 0 and stale_vectors == 0
    )
    return {
        "schemaVersion": MEMORY_PROJECTION_SCHEMA_VERSION,
        "states": states,
        "backlog": backlog,
        "readyBacklog": ready_backlog,
        "dead": states["dead"],
        "expiredProcessingLeases": expired_leases,
        "oldestPendingAgeMs": (
            max(0, timestamp - int(oldest_ready or timestamp)) if oldest_ready else 0
        ),
        "sourceDocuments": source_count,
        "sourceUpdatedAtMs": source_updated_at,
        "retrievalDocsUpdatedAtMs": docs_updated_at,
        "projectionLagMs": (
            max(0, source_updated_at - docs_updated_at) if source_updated_at else 0
        ),
        "retrievalDocuments": docs_total,
        "providerFingerprint": fingerprint,
        "vectorDocuments": vector_total,
        "missingVectors": missing_vectors,
        "staleVectors": stale_vectors,
        "vectorCoverage": round(vector_coverage, 6),
        "checkpoints": checkpoints,
        "latestOutboxIds": latest_outbox,
        "checkpointLag": checkpoint_lag,
        "checkpointCaughtUp": checkpoint_caught_up,
        "projectionInitialized": projection_initialized,
        "fresh": (
            projection_initialized
            and backlog == 0
            and states["dead"] == 0
            and checkpoint_caught_up
            and vector_fresh
        ),
    }


def _next_ready_event(
    conn: sqlite3.Connection,
    *,
    timestamp: int,
    projection_kinds: tuple[str, ...],
) -> sqlite3.Row | None:
    kind_sql = ""
    params: list[object] = [timestamp]
    if projection_kinds:
        kind_sql = f" AND projection_kind IN ({', '.join('?' for _ in projection_kinds)})"
        params.extend(projection_kinds)
    return conn.execute(
        f"""
        SELECT *
        FROM memory_projection_outbox
        WHERE state IN ('pending', 'failed') AND available_at_ms <= ?
          {kind_sql}
        ORDER BY outbox_id ASC
        LIMIT 1
        """,
        params,
    ).fetchone()


def _enqueue_vector_catchup_if_needed(
    conn: sqlite3.Connection,
    *,
    embedding_provider: EmbeddingProvider | None,
    timestamp: int,
) -> int | None:
    fingerprint = compact_whitespace(
        str(getattr(embedding_provider, "fingerprint", "") or "")
    )
    if not fingerprint or fingerprint == "none":
        return None
    missing_or_stale = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_retrieval_docs d
            LEFT JOIN memory_retrieval_doc_vectors v
              ON v.doc_id = d.doc_id AND v.provider_fingerprint = ?
            WHERE d.status = 'active'
              AND (
                  v.doc_id IS NULL
                  OR v.source_revision != d.source_revision
                  OR v.projection_version != d.projection_version
              )
            """,
            (fingerprint,),
        ).fetchone()[0]
    )
    if missing_or_stale == 0:
        return None
    existing = conn.execute(
        """
        SELECT outbox_id, state
        FROM memory_projection_outbox
        WHERE projection_kind = ?
        ORDER BY outbox_id DESC
        LIMIT 1
        """,
        (RETRIEVAL_VECTORS_PROJECTION,),
    ).fetchone()
    if existing is not None and str(existing["state"]) in {
        "pending",
        "processing",
        "failed",
        "dead",
    }:
        return int(existing[0])
    return enqueue_memory_projection(
        conn,
        projection_kind=RETRIEVAL_VECTORS_PROJECTION,
        aggregate_type="embedding_provider",
        aggregate_id=fingerprint,
        operation="catch_up",
        revision=None,
        payload={
            "reason": "provider_enabled_or_vector_stale",
            "missingOrStaleDocuments": missing_or_stale,
        },
        available_at_ms=timestamp,
    )


def _recover_expired_leases(
    conn: sqlite3.Connection,
    *,
    timestamp: int,
    max_attempts: int,
    lease_ms: int,
    projection_kinds: tuple[str, ...],
) -> tuple[list[int], list[int]]:
    kind_sql = ""
    params: list[object] = [timestamp - lease_ms]
    if projection_kinds:
        kind_sql = f" AND projection_kind IN ({', '.join('?' for _ in projection_kinds)})"
        params.extend(projection_kinds)
    rows = conn.execute(
        f"""
        SELECT outbox_id, attempts
        FROM memory_projection_outbox
        WHERE state = 'processing' AND updated_at_ms < ?
          {kind_sql}
        ORDER BY outbox_id
        """,
        params,
    ).fetchall()
    recovered: list[int] = []
    dead: list[int] = []
    for row in rows:
        outbox_id = int(row["outbox_id"])
        terminal = int(row["attempts"] or 0) >= max_attempts
        conn.execute(
            """
            UPDATE memory_projection_outbox
            SET state = ?, available_at_ms = ?, processed_at_ms = ?,
                updated_at_ms = ?, last_error = 'processing lease expired'
            WHERE outbox_id = ? AND state = 'processing'
            """,
            (
                "dead" if terminal else "failed",
                timestamp,
                timestamp if terminal else None,
                timestamp,
                outbox_id,
            ),
        )
        (dead if terminal else recovered).append(outbox_id)
    return recovered, dead


def _advance_checkpoint(
    conn: sqlite3.Connection,
    *,
    projection_kind: str,
    timestamp: int,
) -> None:
    current_row = conn.execute(
        "SELECT last_outbox_id FROM memory_projection_checkpoints WHERE projection_kind = ?",
        (projection_kind,),
    ).fetchone()
    checkpoint = int(current_row[0] or 0) if current_row is not None else 0
    rows = conn.execute(
        """
        SELECT outbox_id, state
        FROM memory_projection_outbox
        WHERE projection_kind = ? AND outbox_id > ?
        ORDER BY outbox_id ASC
        """,
        (projection_kind, checkpoint),
    ).fetchall()
    for row in rows:
        if str(row["state"]) != "applied":
            break
        checkpoint = int(row["outbox_id"])
    if checkpoint <= 0:
        return
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
        (projection_kind, checkpoint, timestamp),
    )


def _materialize_event(
    conn: sqlite3.Connection,
    *,
    row: sqlite3.Row,
    embedding_provider: EmbeddingProvider | None,
    timestamp: int,
    migrations_dir: str | Path,
    preverified_schema: bool,
) -> dict[str, object]:
    payload = _json_object(row["payload_json"])
    project = compact_whitespace(str(payload.get("project") or ""))
    projection_kind = str(row["projection_kind"])
    if projection_kind == RETRIEVAL_DOCS_PROJECTION:
        from .retrieval_docs import rebuild_retrieval_docs

        source_refs = _retrieval_source_refs_for_event(
            conn,
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            payload=payload,
        )
        report = rebuild_retrieval_docs(
            conn,
            project=project,
            include_phrases=True,
            include_legacy_items=False,
            source_refs=source_refs,
            migrations_dir=migrations_dir,
            preverified_schema=preverified_schema,
        )
        vector_outbox_id = enqueue_memory_projection(
            conn,
            projection_kind=RETRIEVAL_VECTORS_PROJECTION,
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            operation=str(row["operation"]),
            project=project,
            revision=int(row["revision"]),
            payload={
                "sourceOutboxId": int(row["outbox_id"]),
                "docIds": sorted(
                    {
                        *[str(value) for value in report.get("changedDocIds") or []],
                        *[str(value) for value in report.get("removedDocIds") or []],
                    }
                ),
            },
            available_at_ms=timestamp,
        )
        return {
            "projectionKind": projection_kind,
            "project": project,
            "documents": report,
            "vectorOutboxId": vector_outbox_id,
        }
    if projection_kind == RETRIEVAL_VECTORS_PROJECTION:
        fingerprint = str(getattr(embedding_provider, "fingerprint", "") or "")
        if embedding_provider is None or not fingerprint or fingerprint == "none":
            return {
                "projectionKind": projection_kind,
                "project": project,
                "skippedReason": "embedding_provider_disabled",
            }
        from .retrieval_vector_index import rebuild_retrieval_doc_vectors

        payload_doc_ids = payload.get("docIds")
        doc_ids = (
            [str(value) for value in payload_doc_ids if value]
            if isinstance(payload_doc_ids, list)
            else None
        )
        report = rebuild_retrieval_doc_vectors(
            conn,
            embedding_provider,
            project=project,
            doc_ids=doc_ids,
        )
        return {
            "projectionKind": projection_kind,
            "project": project,
            "vectors": report,
        }
    raise ValueError(f"unsupported projection kind: {projection_kind}")


def _retrieval_source_refs_for_event(
    conn: sqlite3.Connection,
    *,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, object],
) -> tuple[tuple[str, str], ...] | None:
    explicit = payload.get("sourceRefs")
    if isinstance(explicit, list):
        refs = {
            (
                compact_whitespace(str(item.get("sourceType") or "")).lower(),
                compact_whitespace(str(item.get("sourceId") or "")),
            )
            for item in explicit
            if isinstance(item, dict)
        }
        return tuple(sorted(ref for ref in refs if all(ref)))

    normalized_type = compact_whitespace(aggregate_type).lower()
    normalized_id = compact_whitespace(aggregate_id)
    direct_types = {
        "memory_atom": ("atom",),
        "memory_book": ("book",),
        "daily_activity_timeline": ("timeline",),
        # A memory item may switch between a direct phrase and a governed
        # non-retrievable item, so target both projections for deletion/upsert.
        "memory_item": ("phrase", "item"),
    }
    if normalized_type in direct_types and normalized_id:
        return tuple(
            (source_type, normalized_id)
            for source_type in direct_types[normalized_type]
        )
    if normalized_type == "input_event" and normalized_id.isdigit():
        return _source_refs_for_input_event(conn, int(normalized_id))
    if normalized_type == "memory_book_run" and normalized_id:
        return _source_refs_for_memory_book_run(conn, normalized_id)
    # Project-wide catalog replacement and explicit rebuild operations remain
    # repair tools. Normal single-source and automatic curation events above
    # never rewrite unrelated Retrieval Docs.
    return None


def _source_refs_for_input_event(
    conn: sqlite3.Connection,
    event_id: int,
) -> tuple[tuple[str, str], ...]:
    refs = {
        (
            compact_whitespace(str(row["source_type"])).lower(),
            compact_whitespace(str(row["source_id"])),
        )
        for row in conn.execute(
            """
            SELECT source_type, source_id
            FROM memory_source_event_links
            WHERE event_id = ?
            """,
            (max(0, int(event_id)),),
        ).fetchall()
    }
    for row in conn.execute(
        """
        SELECT memory_id, kind
        FROM memory_items
        WHERE source_event_id = ?
        """,
        (max(0, int(event_id)),),
    ).fetchall():
        refs.add(
            (
                "phrase" if str(row["kind"] or "") == "phrase" else "item",
                compact_whitespace(str(row["memory_id"] or "")),
            )
        )
    return tuple(sorted(ref for ref in refs if all(ref)))


def _source_refs_for_memory_book_run(
    conn: sqlite3.Connection,
    run_id: str,
) -> tuple[tuple[str, str], ...] | None:
    refs: set[tuple[str, str]] = set()
    rows = conn.execute(
        """
        SELECT op, payload_json, rollback_json
        FROM memory_cleanup_diffs
        WHERE run_id = ?
        ORDER BY id
        """,
        (run_id,),
    ).fetchall()
    for row in rows:
        op = compact_whitespace(str(row["op"] or ""))
        payload = _json_object(row["payload_json"])
        rollback = _json_object(row["rollback_json"])
        if op == "upsert_memory_atom":
            _add_ref(refs, "atom", payload.get("atomId"))
            for value in rollback.get("autoSuperseded") or []:
                if isinstance(value, dict):
                    _add_ref(refs, "atom", value.get("id"))
            for value in rollback.get("autoSupersededBooks") or []:
                if isinstance(value, dict):
                    _add_ref(refs, "book", value.get("book_id"))
            _add_dependency_invalidation_refs(refs, rollback)
        elif op == "upsert_memory_book":
            _add_ref(refs, "book", payload.get("bookId"))
        elif op == "add_phrase_candidate":
            _add_ref(refs, "phrase", payload.get("memoryId"))
            _add_ref(refs, "item", payload.get("memoryId"))
        elif op == "supersede_memory":
            for key in ("oldId", "newId"):
                for source_type in ("atom", "phrase", "item"):
                    _add_ref(refs, source_type, payload.get(key))
            _add_dependency_invalidation_refs(refs, rollback)
        elif op == "retract_memory_atom":
            _add_ref(refs, "atom", payload.get("targetAtomId"))
            for value in rollback.get("books") or []:
                if isinstance(value, dict):
                    _add_ref(refs, "book", value.get("book_id"))
            _add_dependency_invalidation_refs(refs, rollback)
        elif op == "merge_semantic_tag":
            refs.update(
                _source_refs_for_tag_names(
                    conn,
                    (
                        str(payload.get("source") or ""),
                        str(payload.get("target") or ""),
                    ),
                )
            )
            for value in rollback.get("bookTags") or []:
                if isinstance(value, dict):
                    _add_ref(refs, "book", value.get("book_id"))
        elif op == "upsert_semantic_tag":
            refs.update(
                _source_refs_for_tag_names(
                    conn,
                    (
                        str(payload.get("name") or ""),
                        str(
                            dict(rollback.get("previous") or {}).get("tag")
                            or ""
                        ),
                    ),
                )
            )
            refs.update(
                _source_refs_for_tag_ids(
                    conn,
                    (rollback.get("pkValue"),),
                )
            )
        elif op in {
            "upsert_semantic_group",
            "upsert_tag_edge",
            "add_negative_phrase",
        }:
            continue
        else:
            # Unknown/legacy diff kinds are handled only by an explicit full
            # rebuild instead of risking a partial catalog projection.
            return None
    return tuple(sorted(refs))


def _source_refs_for_tag_names(
    conn: sqlite3.Connection,
    names: tuple[str, ...],
) -> set[tuple[str, str]]:
    normalized_names = {
        normalize_text(value)
        for value in names
        if normalize_text(value)
    }
    if not normalized_names:
        return set()
    placeholders = ",".join("?" for _ in normalized_names)
    tag_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM memory_tags WHERE normalized_tag IN ({placeholders})",
            tuple(sorted(normalized_names)),
        ).fetchall()
    ]
    if not tag_ids:
        return set()
    refs = _source_refs_for_tag_ids(conn, tag_ids)
    target_names = tuple(
        compact_whitespace(value) for value in names if compact_whitespace(value)
    )
    if target_names:
        name_placeholders = ",".join("?" for _ in target_names)
        for row in conn.execute(
            f"""
            SELECT DISTINCT book.book_id
            FROM memory_books AS book
            JOIN json_each(
                CASE WHEN json_valid(book.tags_json) THEN book.tags_json ELSE '[]' END
            ) AS tag
            WHERE CAST(tag.value AS TEXT) IN ({name_placeholders})
            """,
            target_names,
        ).fetchall():
            _add_ref(refs, "book", row["book_id"])
    return refs


def _source_refs_for_tag_ids(
    conn: sqlite3.Connection,
    tag_ids: tuple[object, ...] | list[int],
) -> set[tuple[str, str]]:
    normalized_ids = tuple(
        dict.fromkeys(
            int(value)
            for value in tag_ids
            if str(value or "").strip().isdigit() and int(value) > 0
        )
    )
    if not normalized_ids:
        return set()
    tag_placeholders = ",".join("?" for _ in normalized_ids)
    refs: set[tuple[str, str]] = set()
    for row in conn.execute(
        f"""
        SELECT memory_atom_id
        FROM memory_atom_tags
        WHERE CAST(tag_id AS INTEGER) IN ({tag_placeholders})
        """,
        normalized_ids,
    ).fetchall():
        _add_ref(refs, "atom", row["memory_atom_id"])
    for row in conn.execute(
        f"""
        SELECT item.memory_id, item.kind
        FROM memory_item_tags AS item_tag
        JOIN memory_items AS item ON item.id = item_tag.memory_item_id
        WHERE item_tag.tag_id IN ({tag_placeholders})
        """,
        normalized_ids,
    ).fetchall():
        _add_ref(
            refs,
            "phrase" if str(row["kind"] or "") == "phrase" else "item",
            row["memory_id"],
        )
    return refs


def _add_dependency_invalidation_refs(
    refs: set[tuple[str, str]],
    rollback: dict[str, object],
) -> None:
    invalidation = rollback.get("dependencyInvalidation")
    if not isinstance(invalidation, dict):
        return
    for value in invalidation.get("oldAtomIds") or []:
        _add_ref(refs, "atom", value)
    _add_ref(refs, "atom", invalidation.get("newAtomId"))
    for key in ("staleBookIds", "rebuiltBookIds"):
        for value in invalidation.get(key) or []:
            _add_ref(refs, "book", value)
    for value in invalidation.get("suppressedPhraseIds") or []:
        _add_ref(refs, "phrase", value)
        _add_ref(refs, "item", value)
    for value in invalidation.get("previousBooks") or []:
        if isinstance(value, dict):
            _add_ref(refs, "book", value.get("bookId"))
    for value in invalidation.get("previousPhrases") or []:
        if isinstance(value, dict):
            _add_ref(refs, "phrase", value.get("phraseId"))
            _add_ref(refs, "item", value.get("phraseId"))


def _add_ref(
    refs: set[tuple[str, str]],
    source_type: str,
    source_id: object,
) -> None:
    normalized_type = compact_whitespace(source_type).lower()
    normalized_id = compact_whitespace(str(source_id or ""))
    if normalized_type and normalized_id:
        refs.add((normalized_type, normalized_id))


def _retry_delay_ms(attempts: int) -> int:
    return min(5 * 60 * 1000, 1000 * (2 ** max(0, min(8, attempts - 1))))


def _json_object(raw: Any) -> dict[str, object]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _max_value(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0] or 0) if row is not None else 0
