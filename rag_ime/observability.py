from __future__ import annotations

import hashlib
import json
import math
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .agent_protocol import AgentEventEnvelope
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .pi_runtime_values import redact_runtime_text


OBSERVATION_CATEGORIES = frozenset(
    {
        "context",
        "retrieval",
        "memory",
        "tool",
        "agent",
        "room",
        "intercom",
        "approval",
        "runtime",
        "system",
    }
)
OBSERVATION_STATUSES = frozenset(
    {"queued", "running", "waiting", "completed", "failed", "cancelled", "expired", "info"}
)
_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "arg",
        "args",
        "chainofthought",
        "completion",
        "content",
        "conversation",
        "delta",
        "input",
        "message",
        "messages",
        "output",
        "preedit",
        "prompt",
        "query",
        "reasoning",
        "requestbody",
        "response",
        "result",
        "selectedtext",
        "systemprompt",
        "text",
        "transcript",
    }
)
_FILTER_KEYS = ("sessionId", "roomId", "traceId", "runId", "category", "status")

# ObservationStore is a public journal boundary.  Keep this projection local
# to the journal instead of recursively copying producer dictionaries: the
# latter makes an otherwise harmless direct ``hub.emit`` call a metadata
# exfiltration path.  These keys mirror the real Session/Room/RAG/Memory
# producers; unknown keys are intentionally unavailable in public records.
_PUBLIC_METRIC_NUMBER_KEYS = frozenset(
    {
        "argumentFieldCount",
        "attachmentCount",
        "axActualCharCount",
        "axActualNodeCount",
        "axCharacterCount",
        "axEffectiveCharCount",
        "axEffectiveNodeCount",
        "axNodeCount",
        "axRequestedCharCount",
        "axRequestedNodeCount",
        "blockCount",
        "cacheHitPercent",
        "cacheReadTokens",
        "cacheWriteTokens",
        "candidateCount",
        "characterCount",
        "compactAtTokens",
        "compactionCount",
        "contextChars",
        "contextEffectiveTokens",
        "contextPercent",
        "contextRequestedTokens",
        "contextTokens",
        "contextWindowTokens",
        "count",
        "currentContextChars",
        "currentRequestChars",
        "elapsedMs",
        "estimatedTokensAfter",
        "evidenceCount",
        "eventCount",
        "firstTokenMs",
        "inputTokens",
        "latencyBudgetMs",
        "maxItems",
        "messageCount",
        "modelElapsedMs",
        "omittedCount",
        "outputTokens",
        "pendingDraftCount",
        "pendingEventCount",
        "providedEvidenceCount",
        "ragElapsedMs",
        "recentInputActualChars",
        "recentInputActualCount",
        "recentInputEffectiveChars",
        "recentInputEffectiveCount",
        "recentInputRequestedChars",
        "recentInputRequestedCount",
        "recentCompleteInputCount",
        "recentConversationCount",
        "remainingTokens",
        "resultFieldCount",
        "selectedChars",
        "selectedCount",
        "tokensBefore",
        "tokensUntilCompact",
        "totalTokens",
        "usedChars",
        "changeCount",
    }
)
_PUBLIC_METRIC_BOOLEAN_KEYS = frozenset(
    {
        "axTruncated",
        "contextTruncated",
        "isError",
        "recentInputTruncated",
        "reused",
    }
)
_PUBLIC_ATTRIBUTE_BOOLEAN_KEYS = frozenset(
    {
        "due",
        "embeddingFallback",
        "failureRecorded",
        "invalidResumeToken",
        "isCompacting",
        "modelActiveGeneration",
        "modelCalled",
        "modelStaleDropped",
        "modelTimedOut",
        "modelWaitingForLatest",
        "parentUnavailable",
        "ragActiveGeneration",
        "ragCalled",
        "ragStaleDropped",
        "ragTimedOut",
        "ragWaitingForLatest",
        "rawKnowledgeTextStored",
        "rawMemoryTextStored",
        "rawMessageStored",
        "rawReasoningStored",
        "rawResultStored",
        "rawTextStored",
        "sourceRawTextIncluded",
        "terminalDerivedFromDispatches",
        "terminalDerivedFromMaintenancePhase",
        "willRetry",
    }
)
_PUBLIC_ATTRIBUTE_INTEGER_KEYS = frozenset(
    {
        "frontendRevision",
        "modelPredictionCount",
        "modelSuggestionCount",
        "ragPredictionCount",
        "ragSuggestionCount",
        "requestSeq",
        "resultCount",
        "selectionEpoch",
        "terminalDispatchCount",
        "visibleCandidateCount",
        "workItemRevision",
    }
)
_PUBLIC_ATTRIBUTE_FINGERPRINT_KEYS = frozenset(
    {"answerFingerprint", "inputFingerprint"}
)
_PUBLIC_REASON_VALUES = frozenset({"threshold", "event_replay_gap"})
_INPUT_GENERATION_CONTEXT_REASON_VALUES = frozenset(
    {
        "ax_timeout",
        "budget_exhausted",
        "no_accessibility_nodes",
        "no_eligible_inputs",
        "no_recent_input",
        "not_captured",
        "provider_unavailable",
        "redacted",
        "unsupported",
    }
)
_PUBLIC_ATTRIBUTE_IDENTIFIER_KEYS = frozenset(
    {
        "action",
        "acceptedTurnId",
        "activityKind",
        "attemptId",
        "app",
        "caseId",
        "commandId",
        "deviceId",
        "evidenceStage",
        "failureKind",
        "failureReason",
        "frontAppBundleId",
        "intent",
        "intercomKind",
        "knowledgeBaseId",
        "lifecycleAuthority",
        "memoryId",
        "maintenanceJobId",
        "model",
        "axUnavailableReason",
        "parentUnavailableReason",
        "participantState",
        "phase",
        "postKind",
        "producerKind",
        "project",
        "recentInputUnavailableReason",
        "provider",
        "ownerRunId",
        "receiptId",
        "requestKind",
        "retrievalMode",
        "riskLevel",
        "role",
        "roomEventType",
        "runtimeState",
        "sourceEventType",
        "sourceKind",
        "targetParticipantId",
        "terminalPhaseStatus",
        "traceContext",
        "thinkingLevel",
        "toolName",
        "trigger",
        "workState",
        "workItemId",
        "sourceTurnId",
    }
)
_PUBLIC_EVIDENCE_SCORE_KEYS = frozenset(
    {
        "accepted",
        "bm25",
        "confidence",
        "contradiction",
        "coverage",
        "dense",
        "downranked",
        "freshness",
        "groundedness",
        "lexical",
        "ndcg",
        "pinned",
        "recall",
        "relevance",
        "rerank",
        "rrf",
        "score",
        "semantic",
        "skipped",
        "stalePenalty",
        "tag",
        "vector",
    }
)
_PUBLIC_REFERENCE_LABELS = frozenset(
    {
        "Agent 私信",
        "Knowledge 检索",
        "Room 行星",
        "Session 记忆召回",
        "公开消息",
        "关联任务",
        "来源分派",
        "任务分派",
        "工具调用",
        "执行尝试",
        "目标参与者",
        "子任务分派",
        "应用回执",
        "权威任务",
        "知识证据",
        "记忆整理",
        "闪电联想",
        "输入生成",
    }
)
_PUBLIC_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}\Z")
_PUBLIC_LONG_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}\Z")
_PUBLIC_SOURCE_SCHEME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]{0,31}\Z")
_PUBLIC_SOURCE_AUTHORITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PUBLIC_SOURCE_PATH_PATTERN = re.compile(
    r"[A-Za-z0-9_.~!$&'()*+,;=:@%:-]+(?:/[A-Za-z0-9_.~!$&'()*+,;=:@%:-]+)*\Z"
)
_PUBLIC_MIME_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}\Z"
)
_PUBLIC_SHA256_PATTERN = re.compile(r"[a-f0-9]{64}\Z")


class ObservationConflict(RuntimeError):
    """A stable observation event identity was rebound to different content."""


class ObservationStore:
    """Durable metadata-only trace journal shared by the Agent Gateway surfaces."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        retention_limit: int = 10_000,
        retention_days: int = 30,
    ) -> None:
        self.db_path = Path(db_path)
        self.retention_limit = max(1_000, int(retention_limit))
        self.retention_days = max(1, int(retention_days))

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def append(self, values: Mapping[str, object]) -> dict[str, object]:
        event, _ = self.append_with_status(values)
        return event

    def append_with_status(
        self,
        values: Mapping[str, object],
    ) -> tuple[dict[str, object], bool]:
        explicit_event_id = bool(_identifier(values.get("eventId")))
        event_id = _identifier(values.get("eventId")) or f"observation:{uuid.uuid4().hex}"
        trace_id = _required_identifier(values.get("traceId"), fallback=f"trace:{event_id}")
        span_id = _required_identifier(values.get("spanId"), fallback=f"span:{event_id}")
        category = _choice(values.get("category"), OBSERVATION_CATEGORIES, "system")
        name = _bounded_label(values.get("name"), fallback="observation")
        status = _choice(values.get("status"), OBSERVATION_STATUSES, "info")
        input_generation_terminal = _is_input_generation_terminal(
            trace_id=trace_id,
            span_id=span_id,
            category=category,
            name=name,
            status=status,
        )
        created_at_ms = _integer(
            values.get("createdAtMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        started_at_ms = _integer(
            values.get("startedAtMs"),
            default=created_at_ms,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        ended_at_ms = _optional_integer(values.get("endedAtMs"))
        duration_ms = _optional_number(values.get("durationMs"))
        metrics = _safe_metrics(values.get("metrics"))
        attributes = _safe_attributes(values.get("attributes"))
        refs = _safe_refs(values.get("refs"))
        persisted_columns = (
            "event_id", "trace_id", "span_id", "parent_span_id",
            "session_id", "room_id", "turn_id", "run_id",
            "category", "phase", "name", "status", "summary",
            "created_at_ms", "started_at_ms", "ended_at_ms", "duration_ms",
            "privacy_class", "metrics_json", "attributes_json", "refs_json",
        )
        persisted = (
            event_id,
            trace_id,
            span_id,
            _identifier(values.get("parentSpanId")),
            _identifier(values.get("sessionId")),
            _identifier(values.get("roomId")),
            _identifier(values.get("turnId")),
            _identifier(values.get("runId")),
            category,
            _bounded_label(values.get("phase"), fallback="observed"),
            name,
            status,
            _bounded_summary(values.get("summary")),
            created_at_ms,
            started_at_ms,
            ended_at_ms,
            duration_ms,
            _choice(
                values.get("privacyClass"),
                frozenset({"metadata", "redacted", "owner_local"}),
                "metadata",
            ),
            _json(metrics),
            _json(attributes),
            _json(refs),
        )
        with self._connect() as conn:
            # SQLite serializes writers once an IMMEDIATE transaction starts.
            # Taking that write fence before checking this span makes the
            # terminal decision durable even when two projector callers race.
            if input_generation_terminal:
                conn.execute("BEGIN IMMEDIATE")
            if explicit_event_id:
                existing = conn.execute(
                    "SELECT * FROM agent_observation_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    existing_persisted = _canonical_persisted_row(
                        existing,
                        persisted_columns,
                    )
                    if existing_persisted != persisted:
                        raise ObservationConflict(
                            f"observation event {event_id!r} was rebound to different persisted fields"
                        )
                    return _row_payload(existing), False
            if input_generation_terminal:
                existing_terminal = conn.execute(
                    """
                    SELECT event_id, status
                    FROM agent_observation_events
                    WHERE trace_id = ?
                      AND span_id = ?
                      AND category = 'runtime'
                      AND name = 'input.generation'
                      AND status IN ('completed', 'failed', 'cancelled')
                    ORDER BY sequence
                    LIMIT 1
                    """,
                    (trace_id, span_id),
                ).fetchone()
                if existing_terminal is not None:
                    raise ObservationConflict(
                        "input-generation terminal fence already settled "
                        f"as {str(existing_terminal['status'])!r} by "
                        f"{str(existing_terminal['event_id'])!r}"
                    )
            cursor = conn.execute(
                """
                INSERT INTO agent_observation_events(
                    event_id, trace_id, span_id, parent_span_id,
                    session_id, room_id, turn_id, run_id,
                    category, phase, name, status, summary,
                    created_at_ms, started_at_ms, ended_at_ms, duration_ms,
                    privacy_class, metrics_json, attributes_json, refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (
                    event_id,
                    trace_id,
                    span_id,
                    _identifier(values.get("parentSpanId")),
                    _identifier(values.get("sessionId")),
                    _identifier(values.get("roomId")),
                    _identifier(values.get("turnId")),
                    _identifier(values.get("runId")),
                    category,
                    _bounded_label(values.get("phase"), fallback="observed"),
                    name,
                    status,
                    _bounded_summary(values.get("summary")),
                    created_at_ms,
                    started_at_ms,
                    ended_at_ms,
                    duration_ms,
                    _choice(
                        values.get("privacyClass"),
                        frozenset({"metadata", "redacted", "owner_local"}),
                        "metadata",
                    ),
                    _json(metrics),
                    _json(attributes),
                    _json(refs),
                ),
            )
            inserted = cursor.rowcount == 1
            row = conn.execute(
                "SELECT * FROM agent_observation_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if explicit_event_id and not inserted and row is not None:
                existing_persisted = _canonical_persisted_row(row, persisted_columns)
                if existing_persisted != persisted:
                    raise ObservationConflict(
                        f"observation event {event_id!r} was rebound to different persisted fields"
                    )
            if inserted:
                self._prune_locked(conn, now_ms=created_at_ms)
        if row is None:  # pragma: no cover - the insert and read share one transaction
            raise RuntimeError("observation event was not persisted")
        return _row_payload(row), inserted

    def snapshot(
        self,
        *,
        limit: int = 200,
        before_sequence: int = 0,
        filters: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        safe_filters = _normalize_filters(filters)
        bounded_limit = max(1, min(int(limit), 500))
        where, values = _filter_clause(safe_filters)
        if before_sequence > 0:
            where.append("sequence < ?")
            values.append(int(before_sequence))
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM agent_observation_events
                {predicate}
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (*values, bounded_limit + 1),
            ).fetchall()
            bounds = conn.execute(
                "SELECT COALESCE(MIN(sequence), 0), COALESCE(MAX(sequence), 0) "
                "FROM agent_observation_events"
            ).fetchone()
        truncated = len(rows) > bounded_limit
        items = [_row_payload(row) for row in rows[:bounded_limit]]
        first_sequence = int(bounds[0] if bounds else 0)
        last_sequence = int(bounds[1] if bounds else 0)
        by_category: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for item in items:
            category = str(item["category"])
            status = str(item["status"])
            by_category[category] = by_category.get(category, 0) + 1
            by_status[status] = by_status.get(status, 0) + 1
        payload = {
            "schemaVersion": "rag-ime.observation-snapshot.v1",
            "generatedAtMs": _now_ms(),
            "firstSequence": first_sequence,
            "lastSequence": last_sequence,
            "resumeToken": _resume_token(last_sequence),
            "truncated": truncated,
            "filters": safe_filters,
            "counts": {
                "total": len(items),
                "byCategory": by_category,
                "byStatus": by_status,
            },
            "items": items,
        }
        validate_contract(payload, "observation-snapshot.v1.json")
        return payload

    def list_after(
        self,
        after_sequence: int,
        *,
        filters: Mapping[str, object] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        safe_filters = _normalize_filters(filters)
        where, values = _filter_clause(safe_filters)
        where.append("sequence > ?")
        values.append(max(0, int(after_sequence)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM agent_observation_events
                WHERE {' AND '.join(where)}
                ORDER BY sequence
                LIMIT ?
                """,
                (*values, max(1, min(int(limit), 2_000))),
            ).fetchall()
        return [_row_payload(row) for row in rows]

    def bounds(self) -> tuple[int, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MIN(sequence), 0), COALESCE(MAX(sequence), 0) "
                "FROM agent_observation_events"
            ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def _prune_locked(self, conn: sqlite3.Connection, *, now_ms: int) -> None:
        cutoff = max(0, now_ms - self.retention_days * 86_400_000)
        conn.execute(
            "DELETE FROM agent_observation_events WHERE created_at_ms < ?",
            (cutoff,),
        )
        conn.execute(
            """
            DELETE FROM agent_observation_events
            WHERE sequence <= (
                SELECT COALESCE(MAX(sequence), 0) - ?
                FROM agent_observation_events
            )
            """,
            (self.retention_limit,),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
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


def _active_rag_stage_timing(
    record: Mapping[str, object],
    stage: str,
    *,
    timestamp_ms: int,
) -> tuple[int, int | None, int | None]:
    """Read explicit producer timing without deriving it from session elapsed.

    ``elapsedMs`` is a useful progress metric but is measured from request
    capture.  Treat it as unrelated to stage lifecycle.  If a producer does
    not provide a complete, self-consistent timing triple, the common Trace
    span remains explicitly unmeasured.
    """

    stage_timings = record.get("stageTiming")
    timing = stage_timings.get(stage) if isinstance(stage_timings, Mapping) else None
    if not isinstance(timing, Mapping):
        return timestamp_ms, None, None
    started = _optional_stage_timing_integer(timing.get("startedAtMs"))
    if started is None:
        return timestamp_ms, None, None
    ended = _optional_stage_timing_integer(timing.get("endedAtMs"))
    duration = _optional_stage_timing_integer(timing.get("durationMs"))
    if (
        ended is None
        or duration is None
        or ended < started
        or ended - started != duration
    ):
        return started, None, None
    return started, ended, duration


class ObservationHub:
    """Passive projection, durable replay, and live fan-out for runtime traces."""

    def __init__(self, db_path: str | Path) -> None:
        self.store = ObservationStore(db_path)
        self.store.initialize()
        self._lock = threading.RLock()
        self._subscribers: dict[
            int,
            tuple[queue.Queue[dict[str, object]], dict[str, str]],
        ] = {}
        self._next_subscriber_id = 1
        self._projection_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=2_048)
        self._projection_health_lock = threading.Lock()
        self._projection_dropped_count = 0
        self._projection_error_count = 0
        self._projection_last_drop: dict[str, object] | None = None
        self._projection_last_failure: dict[str, object] | None = None
        self._projection_failure_receipts: deque[dict[str, object]] = deque(maxlen=32)
        self._projection_closed = threading.Event()
        self._projection_thread = threading.Thread(
            target=self._run_projection_worker,
            name="rag-ime-observation-projector",
            daemon=True,
        )
        self._projection_thread.start()

    def emit(self, **values: object) -> dict[str, object]:
        event, inserted = self.store.append_with_status(values)
        if not inserted:
            return event
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for subscriber, filters in subscribers:
            if not _matches_filters(event, filters):
                continue
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(event)
                except (queue.Empty, queue.Full):
                    pass
        return event

    def snapshot(self, payload: Mapping[str, object] | None = None) -> dict[str, object]:
        values = dict(payload or {})
        return self.store.snapshot(
            limit=_integer(values.get("limit"), default=200, minimum=1, maximum=500),
            before_sequence=_integer(
                values.get("beforeSequence"),
                default=0,
                minimum=0,
                maximum=9_223_372_036_854_775_807,
            ),
            filters=values,
        )

    def enqueue_agent_event(
        self,
        event: AgentEventEnvelope,
        *,
        room_id: str = "",
    ) -> None:
        projected = AgentEventEnvelope(
            event_id=event.event_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            sequence=event.sequence,
            created_at_ms=event.created_at_ms,
            event_type=event.event_type,
            payload=_agent_projection_payload(event),
            resume_token=event.resume_token,
        )
        self._enqueue_projection("agent", (projected, _identifier(room_id)))

    def enqueue_room_event(self, event: Mapping[str, object]) -> None:
        self._enqueue_projection("room", _room_projection_event(event))

    def enqueue_active_rag_record(self, record: Mapping[str, object]) -> None:
        self._enqueue_projection("active_rag", _active_rag_projection_record(record))

    def enqueue_input_generation_record(self, record: Mapping[str, object]) -> None:
        self._enqueue_projection(
            "input_generation",
            _input_generation_projection_record(record),
        )

    def enqueue_memory_recall_record(self, record: Mapping[str, object]) -> None:
        self._enqueue_projection("memory_recall", _memory_recall_projection_record(record))

    def enqueue_knowledge_retrieval_record(self, record: Mapping[str, object]) -> None:
        self._enqueue_projection(
            "knowledge_retrieval",
            _knowledge_retrieval_projection_record(record),
        )

    def enqueue_browser_record(self, record: Mapping[str, object]) -> None:
        self._enqueue_projection("browser", _browser_projection_record(record))

    def flush(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while self._projection_queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        # A task can be marked done after its projection raised.  Keep that
        # failure visible to callers instead of claiming a clean flush.
        with self._projection_health_lock:
            return (
                self._projection_dropped_count == 0
                and self._projection_error_count == 0
            )

    def projection_health(self) -> dict[str, object]:
        """Return bounded health evidence for the non-authoritative projector.

        The primary Agent/Room path remains fail-open and non-blocking.  This
        endpoint makes that trade-off observable: queue overflow is counted,
        projector exceptions receive durable failure observations when the
        journal is available, and callers can refuse to treat a flush as
        lossless after either condition.
        """

        with self._projection_health_lock:
            dropped_count = self._projection_dropped_count
            error_count = self._projection_error_count
            last_drop = dict(self._projection_last_drop or {}) or None
            last_failure = dict(self._projection_last_failure or {}) or None
            failures = [dict(item) for item in self._projection_failure_receipts]
        return {
            "schemaVersion": "rag-ime.observation-projection-health.v1",
            "healthy": dropped_count == 0 and error_count == 0,
            "queueCapacity": self._projection_queue.maxsize,
            "pendingCount": self._projection_queue.unfinished_tasks,
            "droppedCount": dropped_count,
            "errorCount": error_count,
            "lastDrop": last_drop,
            "lastFailure": last_failure,
            "recentFailures": failures,
        }

    def close(self) -> None:
        if self._projection_closed.is_set():
            return
        self._projection_closed.set()
        self._enqueue_projection("close", None, force=True)
        self._projection_thread.join(timeout=2.0)

    def subscribe(
        self,
        *,
        after_event_id: str = "",
        filters: Mapping[str, object] | None = None,
        heartbeat_seconds: float = 10.0,
    ) -> Iterator[bytes]:
        safe_filters = _normalize_filters(filters)
        after_sequence = _observation_sequence(after_event_id)
        subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=256)
        with self._lock:
            first_sequence, last_sequence = self.store.bounds()
            gap = bool(
                after_event_id
                and (
                    after_sequence is None
                    or after_sequence > last_sequence
                    or (first_sequence > 0 and after_sequence < first_sequence - 1)
                )
            )
            replay = (
                []
                if gap
                else self.store.list_after(after_sequence or 0, filters=safe_filters)
            )
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers[subscriber_id] = (subscriber, safe_filters)
        delivered_sequence = after_sequence or 0
        try:
            yield b": connected\n\n"
            if gap:
                yield _event_sse(_snapshot_required_event(last_sequence, after_event_id))
            else:
                for event in replay:
                    delivered_sequence = max(delivered_sequence, int(event["sequence"]))
                    yield _event_sse(event)
            while True:
                try:
                    event = subscriber.get(timeout=heartbeat_seconds)
                    if int(event["sequence"]) <= delivered_sequence:
                        continue
                    delivered_sequence = int(event["sequence"])
                    yield _event_sse(event)
                except queue.Empty:
                    yield b": heartbeat\n\n"
        finally:
            with self._lock:
                self._subscribers.pop(subscriber_id, None)

    def observe_agent_event(
        self,
        event: AgentEventEnvelope,
        *,
        room_id: str = "",
    ) -> dict[str, object] | None:
        if event.event_type in {"text_delta", "heartbeat", "snapshot", "snapshot_required"}:
            return None
        payload = event.payload
        event_type = event.event_type
        category = "agent"
        observation_name = event_type
        status = "info"
        summary = "Agent 运行状态已更新"
        run_id = _identifier(payload.get("runId"))
        span_suffix = event.event_id
        refs: list[dict[str, str]] = [
            {"kind": "agent_event", "id": event.event_id, "label": event_type}
        ]
        attributes: dict[str, object] = {"sourceEventType": event_type}
        metrics: dict[str, object] = {}
        started_at_ms = event.created_at_ms

        telemetry = _telemetry_projection(payload.get("telemetry"))
        _apply_agent_telemetry_observation(
            telemetry,
            attributes=attributes,
            metrics=metrics,
        )

        if event_type in {"provider_request_completed", "provider_request_failed"}:
            observation_name = "provider.request"
            request_id = _identifier(payload.get("requestId")) or event.event_id
            span_suffix = f"provider:{request_id}"
            refs.append(
                {"kind": "provider_request", "id": request_id, "label": "Provider 请求"}
            )
            provider = _bounded_label(payload.get("provider"))
            model = _bounded_label(payload.get("model"))
            if provider:
                attributes["provider"] = provider
            if model:
                attributes["model"] = model
            started = _optional_integer(payload.get("startedAtMs"))
            if started is not None and started <= event.created_at_ms:
                started_at_ms = started
            usage = payload.get("usage")
            if isinstance(usage, Mapping):
                _apply_usage_metrics(usage, metrics)
            status = (
                "failed"
                if event_type == "provider_request_failed"
                else "completed"
            )
            summary = (
                "Provider 请求失败"
                if status == "failed"
                else "Provider 请求已完成"
            )
        elif event_type == "message_completed":
            message = payload.get("message") if isinstance(payload.get("message"), Mapping) else {}
            role = _bounded_label(
                payload.get("role") or message.get("role"),
                fallback="assistant",
            )
            summary = "用户消息已进入会话" if role == "user" else "Agent 消息已完成"
            attributes["role"] = role
            blocks = (
                message.get("blocks")
                if isinstance(message.get("blocks"), Sequence)
                and not isinstance(message.get("blocks"), (str, bytes, bytearray))
                else ()
            )
            attachments = (
                message.get("attachments")
                if isinstance(message.get("attachments"), Sequence)
                and not isinstance(message.get("attachments"), (str, bytes, bytearray))
                else ()
            )
            metrics.update(
                blockCount=_integer(
                    payload.get("blockCount"),
                    default=len(blocks),
                    minimum=0,
                ),
                attachmentCount=_integer(
                    payload.get("attachmentCount"),
                    default=len(attachments),
                    minimum=0,
                ),
            )
            provider = _bounded_label(payload.get("provider") or message.get("provider"))
            model = _bounded_label(payload.get("model") or message.get("model"))
            if provider:
                attributes["provider"] = provider
            if model:
                attributes["model"] = model
            usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else message.get("usage")
            if isinstance(usage, Mapping):
                _apply_usage_metrics(usage, metrics)
            status = "completed"
        elif event_type in {"compaction_started", "compaction_completed"}:
            category = "context"
            reason = _bounded_label(payload.get("reason"), fallback="threshold")
            attributes["reason"] = reason
            if event_type == "compaction_started":
                status = "running"
                summary = "上下文压缩已开始"
            else:
                failed = payload.get("isError") is True
                aborted = payload.get("aborted") is True
                status = "failed" if failed else "cancelled" if aborted else "completed"
                summary = {
                    "failed": "上下文压缩未完成",
                    "cancelled": "上下文压缩已取消",
                    "completed": "上下文压缩已完成",
                }[status]
                tokens_before = _optional_integer(payload.get("tokensBefore"))
                if tokens_before is not None:
                    metrics["tokensBefore"] = tokens_before
                estimated_tokens_after = _optional_integer(
                    payload.get("estimatedTokensAfter")
                )
                if estimated_tokens_after is not None:
                    metrics["estimatedTokensAfter"] = estimated_tokens_after
                attributes["willRetry"] = payload.get("willRetry") is True
        elif event_type == "reasoning_summary":
            summary = "Agent 已更新公开推理摘要"
            status = "running"
            attributes["rawReasoningStored"] = False
        elif event_type == "status_changed":
            runtime_state = _bounded_label(payload.get("status"), fallback="updated")
            attributes["runtimeState"] = runtime_state
            status = (
                "running"
                if runtime_state in {"busy", "analyzing", "aborting", "starting"}
                else "info"
            )
            summary = {
                "analyzing": "Agent 正在分析",
                "busy": "Agent 正在运行",
                "aborting": "Agent 正在停止当前回合",
                "ready": "Agent 已就绪",
            }.get(runtime_state, "Agent 运行状态已更新")
            category = "runtime"
        elif event_type in {"tool_started", "tool_progress", "tool_finished"}:
            category = "tool"
            tool_name = _bounded_label(payload.get("toolName"), fallback="tool")
            tool_call_id = _identifier(payload.get("toolCallId")) or event.event_id
            span_suffix = f"tool:{tool_call_id}"
            refs.append({"kind": "tool_call", "id": tool_call_id, "label": tool_name})
            attributes["toolName"] = tool_name
            metrics["argumentFieldCount"] = _integer(
                payload.get("argumentFieldCount"),
                default=_mapping_size(payload.get("args")),
                minimum=0,
            )
            result = payload.get("result") or payload.get("partialResult")
            metrics["resultFieldCount"] = _integer(
                payload.get("resultFieldCount"),
                default=_mapping_size(result),
                minimum=0,
            )
            metrics["isError"] = payload.get("isError") is True
            status = {
                "tool_started": "running",
                "tool_progress": "running",
                "tool_finished": "failed" if payload.get("isError") is True else "completed",
            }[event_type]
            summary = {
                "tool_started": f"{tool_name} 已开始",
                "tool_progress": f"{tool_name} 正在执行",
                "tool_finished": f"{tool_name} 执行失败"
                if status == "failed"
                else f"{tool_name} 已完成",
            }[event_type]
            knowledge_activity = (
                payload.get("knowledgeActivity")
                if isinstance(payload.get("knowledgeActivity"), Mapping)
                else {}
            )
            if (
                tool_name == "knowledge"
                and knowledge_activity.get("activityKind") == "knowledge_retrieval"
                and knowledge_activity.get("operation") == "search"
            ):
                category = "retrieval"
                observation_name = "knowledge.retrieval"
                attributes.update(
                    sourceKind="knowledge",
                    activityKind="knowledge_retrieval",
                    evidenceStage="retrieval_output",
                )
                for key in ("knowledgeBaseId", "retrievalMode"):
                    if knowledge_activity.get(key):
                        attributes[key] = knowledge_activity[key]
                trace_evidence = _safe_trace_evidence(
                    knowledge_activity.get("traceEvidence")
                )
                attributes["traceEvidence"] = trace_evidence
                evidence_count = _optional_integer(
                    knowledge_activity.get("evidenceCount")
                )
                if evidence_count is not None:
                    metrics["evidenceCount"] = evidence_count
                refs.extend(
                    {
                        "kind": "retrieval_evidence",
                        "id": str(item["evidenceId"]),
                        "label": "检索证据",
                    }
                    for item in trace_evidence
                )
                summary = {
                    "tool_started": "Knowledge 检索已开始",
                    "tool_progress": "Knowledge 正在检索",
                    "tool_finished": "Knowledge 检索失败"
                    if status == "failed"
                    else "Knowledge 检索已完成",
                }[event_type]
        elif event_type in {"approval_required", "approval_resolved", "user_input_required"}:
            request_kind = _bounded_label(payload.get("requestKind"), fallback="approval")
            category = "memory" if request_kind == "memory_review" else "approval"
            approval_id = (
                _identifier(payload.get("approvalId"))
                or _identifier(payload.get("requestId"))
                or event.event_id
            )
            span_suffix = f"approval:{approval_id}"
            refs.append({"kind": "approval", "id": approval_id, "label": request_kind})
            attributes["requestKind"] = request_kind
            if payload.get("riskLevel"):
                attributes["riskLevel"] = _bounded_label(payload.get("riskLevel"))
            status = "waiting" if event_type != "approval_resolved" else "completed"
            summary = (
                "记忆草案等待审阅"
                if request_kind == "memory_review"
                else "运行步骤等待用户确认"
                if status == "waiting"
                else "用户确认已处理"
            )
        elif event_type.startswith("memory_"):
            category = "memory"
            status = "info"
            summary = (
                "记忆整理状态已更新"
                if event_type == "memory_maintenance_updated"
                else "记忆检查点已保存"
            )
            pending_event_count = _optional_integer(payload.get("pendingEventCount"))
            if pending_event_count is not None:
                metrics["pendingEventCount"] = pending_event_count
            pending_draft_count = _optional_integer(payload.get("pendingDraftCount"))
            if pending_draft_count is not None:
                metrics["pendingDraftCount"] = pending_draft_count
            attributes["due"] = payload.get("due") is True
            if run_id:
                refs.append({"kind": "memory_run", "id": run_id, "label": "记忆整理"})
        elif event_type in {"turn_completed", "turn_failed"}:
            terminal_state = _bounded_label(payload.get("status"), fallback="")
            status = (
                "failed"
                if event_type == "turn_failed"
                else "cancelled"
                if terminal_state == "aborted" or payload.get("aborted") is True
                else "completed"
            )
            summary = {
                "failed": "Agent 回合执行失败",
                "cancelled": "Agent 回合已取消",
                "completed": "Agent 回合已完成",
            }[status]
            if status == "failed":
                failure_kind = _safe_public_token(payload.get("failureKind"))
                failure_reason = _safe_public_token(
                    payload.get("reason") or payload.get("reasonCode")
                )
                if failure_kind:
                    attributes["failureKind"] = failure_kind
                if failure_reason:
                    attributes["failureReason"] = failure_reason
                failure_detail = _public_failure_detail(payload.get("error"))
                if failure_detail:
                    summary = f"Agent 回合失败：{failure_detail}"
            metrics["messageCount"] = _integer(
                payload.get("messageCount"), default=0, minimum=0
            )
        else:
            status = "failed" if payload.get("isError") is True else "info"

        trace_id = (
            f"trace:turn:{event.turn_id}"
            if event.turn_id
            else f"trace:session:{event.session_id}"
        )
        span_id = (
            f"span:turn:{event.turn_id}"
            if event_type in {"turn_completed", "turn_failed"} and event.turn_id
            else f"span:{span_suffix}"
        )
        parent_span_id = (
            ""
            if not event.turn_id or span_id == f"span:turn:{event.turn_id}"
            else f"span:turn:{event.turn_id}"
        )
        return self.emit(
            traceId=trace_id,
            spanId=span_id,
            parentSpanId=parent_span_id,
            sessionId=event.session_id,
            roomId=room_id,
            turnId=event.turn_id,
            runId=run_id,
            category=category,
            phase=event_type,
            name=observation_name,
            status=status,
            summary=summary,
            createdAtMs=event.created_at_ms,
            startedAtMs=started_at_ms,
            endedAtMs=event.created_at_ms if status in {"completed", "failed", "cancelled"} else None,
            durationMs=_optional_number(payload.get("durationMs")),
            privacyClass="redacted",
            metrics=metrics,
            attributes=attributes,
            refs=refs,
        )

    def observe_room_event(self, event: Mapping[str, object]) -> dict[str, object] | None:
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        event_type = _bounded_label(event.get("eventType"), fallback="room_event")
        if event_type == "participant_delta":
            # Token fragments belong to the Session stream.  They would drown
            # the Room workflow trace without adding a stable operation span.
            return None
        room_id = _identifier(event.get("roomId"))
        if not room_id:
            return None
        event_id = _required_identifier(event.get("eventId"))
        turn_id = _identifier(event.get("turnId"))
        session_id = _identifier(event.get("sourceSessionId"))
        participant_id = _identifier(event.get("participantId"))
        source_event_id = _identifier(payload.get("sourceEventId"))
        source_event_type = _bounded_label(payload.get("sourceEventType"))
        category = "room"
        status = "info"
        summary = "Room 状态已更新"
        metrics: dict[str, object] = {}
        attributes: dict[str, object] = {
            "roomEventType": event_type,
            "rawMessageStored": False,
        }
        for identity_key in (
            "workItemId",
            "caseId",
            "acceptedTurnId",
            "sourceTurnId",
        ):
            identity_value = _room_identity_value(payload, identity_key)
            if identity_value:
                attributes[identity_key] = identity_value
        if source_event_type:
            attributes["sourceEventType"] = source_event_type
        refs: list[dict[str, str]] = [
            {"kind": "room_event", "id": event_id, "label": event_type}
        ]
        if source_event_id:
            refs.append(
                {"kind": "agent_event", "id": source_event_id, "label": source_event_type}
            )
        if participant_id:
            refs.append(
                {"kind": "participant", "id": participant_id, "label": "Room 行星"}
            )

        root_span_id = f"span:room-turn:{turn_id}" if turn_id else ""
        span_id = f"span:room-event:{event_id}"
        parent_span_id = root_span_id
        name = "room.event"
        phase = _bounded_label(payload.get("phase"), fallback=event_type)

        if event_type == "user_message":
            summary = "Room 收到用户消息"
            character_count_value = payload.get("characterCount")
            if character_count_value is None:
                raw_text = payload.get("text")
                if isinstance(raw_text, str):
                    character_count_value = len(raw_text)
            character_count = _optional_integer(character_count_value)
            if character_count is not None:
                metrics["characterCount"] = character_count
            span_id = root_span_id or span_id
            parent_span_id = ""
            name = "room.turn"
            phase = "started"
            status = "running"
        elif event_type == "route_decision":
            summary = "Room 已分派参与者"
            dispatch_id = _identifier(payload.get("dispatchId"))
            parent_dispatch_id = _identifier(payload.get("parentDispatchId"))
            if dispatch_id:
                span_id = f"span:room-dispatch:{dispatch_id}"
                refs.append({"kind": "dispatch", "id": dispatch_id, "label": "任务分派"})
            if parent_dispatch_id and parent_dispatch_id != dispatch_id:
                parent_span_id = f"span:room-dispatch:{parent_dispatch_id}"
                refs.append(
                    {"kind": "dispatch", "id": parent_dispatch_id, "label": "上游分派"}
                )
            name = "room.dispatch"
            phase = "queued"
            target = _identifier(payload.get("targetParticipantId"))
            if target:
                refs.append({"kind": "participant", "id": target, "label": "目标参与者"})
            status = "queued"
        elif event_type == "participant_activity" and payload.get("activityKind") == "intercom":
            category = "intercom"
            message = payload.get("message") if isinstance(payload.get("message"), Mapping) else {}
            message_id = _identifier(message.get("id")) or event_id
            span_id = f"span:room-intercom:{message_id}"
            name = "room.intercom"
            phase = _bounded_label(payload.get("phase"), fallback="updated")
            message_status = _bounded_label(message.get("status"), fallback=phase)
            attributes.update(
                activityKind="intercom",
                phase=phase,
                intercomKind=_bounded_label(message.get("kind"), fallback="send"),
                rawMessageStored=False,
            )
            refs.append({"kind": "intercom", "id": message_id, "label": "Agent 私信"})
            for kind, key in (
                ("participant", "sourceParticipantId"),
                ("participant", "targetParticipantId"),
                ("intercom", "replyTo"),
            ):
                reference = _identifier(message.get(key))
                if reference:
                    refs.append({"kind": kind, "id": reference, "label": key})
            work_item_id = _identifier(message.get("workItemId"))
            if work_item_id:
                refs.append({"kind": "work_item", "id": work_item_id, "label": "关联任务"})
            status = _intercom_status(message_status)
            summary = {
                "queued": "Agent 私信已进入队列",
                "running": "Agent 私信正在投递",
                "completed": "Agent 私信已送达",
                "failed": "Agent 私信投递失败",
                "cancelled": "Agent 私信已取消",
            }.get(status, "Agent 私信状态已更新")
        elif event_type == "participant_activity" and payload.get("activityKind") == "child":
            dispatch_id = (
                _identifier(payload.get("childDispatchId"))
                or _identifier(payload.get("dispatchId"))
                or _identifier(payload.get("attemptId"))
                or event_id
            )
            parent_dispatch_id = _identifier(payload.get("parentDispatchId"))
            span_id = f"span:room-dispatch:{dispatch_id}"
            if parent_dispatch_id and parent_dispatch_id != dispatch_id:
                parent_span_id = f"span:room-dispatch:{parent_dispatch_id}"
            name = "room.child_dispatch"
            status = _room_status_from_phase(
                phase,
                payload.get("status"),
                default="running",
            )
            summary = {
                "completed": "子行星任务已完成",
                "failed": "子行星任务失败",
                "cancelled": "子行星任务已取消",
                "running": "子行星任务正在执行",
            }.get(status, "子行星任务已更新")
            attributes["activityKind"] = "child"
            refs.append({"kind": "dispatch", "id": dispatch_id, "label": "子任务分派"})
            work_item_id = _identifier(payload.get("workItemId"))
            if work_item_id:
                refs.append({"kind": "work_item", "id": work_item_id, "label": "关联任务"})
        elif event_type == "participant_activity" and payload.get("activityKind") == "work":
            work = payload.get("work") if isinstance(payload.get("work"), Mapping) else {}
            work_item_id = _identifier(payload.get("workItemId")) or _identifier(work.get("id"))
            revision_value = payload.get("workItemRevision")
            if revision_value is None:
                revision_value = work.get("revision")
            revision = _optional_integer(revision_value)
            if work_item_id:
                span_id = (
                    f"span:room-work:{work_item_id}:r{revision}"
                    if revision is not None
                    else f"span:room-work:{work_item_id}"
                )
                refs.append({"kind": "work_item", "id": work_item_id, "label": "权威任务"})
            dispatch_id = _identifier(payload.get("dispatchId"))
            if dispatch_id and dispatch_id != turn_id:
                parent_span_id = f"span:room-dispatch:{dispatch_id}"
                refs.append({"kind": "dispatch", "id": dispatch_id, "label": "执行尝试"})
            name = "room.work"
            status = _room_status_from_phase(phase, work.get("state"), default="running")
            summary = {
                "completed": "Room 任务已验收",
                "failed": "Room 任务失败",
                "cancelled": "Room 任务已取消",
                "waiting": "Room 任务等待处理",
                "queued": "Room 任务等待领取",
                "running": "Room 任务正在推进",
            }.get(status, "Room 任务已更新")
            attributes.update(
                activityKind="work",
                workState=_bounded_label(work.get("state")),
            )
            work_evidence = _safe_trace_evidence(payload.get("workTraceEvidence"))
            if not work_evidence:
                # Direct callers still pass the authoritative WorkItem.  The
                # async projection path pre-hashes refs into
                # ``workTraceEvidence`` so owner-local paths never enter the
                # Observation queue.
                work_evidence = _room_work_trace_evidence(work)
            if work_evidence:
                # WorkItem refs may be owner-local paths or URLs.  The Room
                # source keeps those original values; the public journal
                # carries only a safe opaque token or a deterministic digest.
                attributes.update(
                    evidenceStage="work_review",
                    traceEvidence=work_evidence,
                )
                metrics["evidenceCount"] = len(work_evidence)
            if revision is not None:
                attributes["workItemRevision"] = revision
        elif event_type in {"turn_completed", "turn_failed"}:
            dispatch_id = _identifier(payload.get("dispatchId"))
            if dispatch_id:
                span_id = f"span:room-dispatch:{dispatch_id}"
                refs.append({"kind": "dispatch", "id": dispatch_id, "label": "任务分派"})
            elif participant_id and turn_id:
                span_id = f"span:room-participant-turn:{turn_id}:{participant_id}"
            name = "room.dispatch"
            status = _room_status_from_phase(
                event_type,
                payload.get("status"),
                default="failed" if event_type == "turn_failed" else "completed",
            )
            summary = (
                "Room 分派执行失败"
                if status == "failed"
                else "Room 分派已取消"
                if status == "cancelled"
                else "Room 分派已完成"
            )
        elif event_type == "room_post":
            post = payload.get("post") if isinstance(payload.get("post"), Mapping) else {}
            post_id = _identifier(post.get("postId")) or event_id
            span_id = f"span:room-post:{post_id}"
            name = "room.post"
            phase = _bounded_label(post.get("kind"), fallback="published")
            status = "completed"
            summary = "Room 回执已发布"
            attributes["postKind"] = phase
            refs.append({"kind": "room_post", "id": post_id, "label": phase})
            dispatch_id = _identifier(post.get("dispatchId"))
            if dispatch_id:
                parent_span_id = f"span:room-dispatch:{dispatch_id}"
                refs.append({"kind": "dispatch", "id": dispatch_id, "label": "来源分派"})
            work_item_id = _identifier(post.get("workItemId"))
            if work_item_id:
                refs.append({"kind": "work_item", "id": work_item_id, "label": "关联任务"})
        elif event_type == "participant_message":
            message_id = _identifier(payload.get("messageId")) or source_event_id or event_id
            span_id = f"span:room-message:{message_id}"
            name = "room.participant_message"
            status = "completed"
            summary = "行星已发布消息"
            refs.append({"kind": "agent_message", "id": message_id, "label": "公开消息"})
        elif event_type == "participant_status":
            attributes["participantState"] = _bounded_label(payload.get("status"), fallback="updated")
            summary = "Room 参与者状态已更新"
        elif event_type == "participant_activity":
            tool_call_id = _identifier(payload.get("toolCallId"))
            if tool_call_id:
                span_id = f"span:room-tool:{tool_call_id}"
                refs.append({"kind": "tool_call", "id": tool_call_id, "label": "工具调用"})
                name = "room.tool"
            elif source_event_id:
                span_id = f"span:room-agent-event:{source_event_id}"
                name = "room.participant_activity"
            status = _room_status_from_phase(
                source_event_type or phase,
                payload.get("status"),
                default="info",
            )
            summary = "行星执行状态已更新"

        trace_id = (
            f"trace:room-turn:{turn_id}" if turn_id else f"trace:room:{room_id}"
        )
        created_at_ms = _integer(
            event.get("createdAtMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        return self.emit(
            traceId=trace_id,
            spanId=span_id,
            parentSpanId=(
                "" if not parent_span_id or parent_span_id == span_id else parent_span_id
            ),
            sessionId=session_id,
            roomId=room_id,
            turnId=turn_id,
            runId="",
            category=category,
            phase=phase,
            name=name,
            status=status,
            summary=summary,
            createdAtMs=created_at_ms,
            startedAtMs=created_at_ms,
            endedAtMs=created_at_ms
            if status in {"completed", "failed", "cancelled"}
            else None,
            durationMs=_optional_number(payload.get("durationMs")),
            privacyClass="redacted",
            metrics=metrics,
            attributes=attributes,
            refs=refs,
        )

    def observe_active_rag_record(self, record: Mapping[str, object]) -> None:
        session_id = _identifier(record.get("sessionId"))
        if not session_id:
            return
        timestamp_ms = _integer(
            record.get("timestampMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        phase = _bounded_label(record.get("phase"), fallback="updated")
        status = _active_rag_status(
            record.get("traceStatus", record.get("status")),
            phase,
        )
        stage_status = _safe_active_rag_stage_status(record.get("stageStatus"))
        terminal_stage = _safe_public_token(record.get("terminalStage"))
        privacy = record.get("privacy") if isinstance(record.get("privacy"), Mapping) else {}
        request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
        retrieval = (
            record.get("retrieval") if isinstance(record.get("retrieval"), Mapping) else {}
        )
        generation = (
            record.get("generation") if isinstance(record.get("generation"), Mapping) else {}
        )
        trace_evidence = _safe_trace_evidence(retrieval.get("traceEvidence"))
        context_started_at_ms, context_ended_at_ms, context_duration_ms = _active_rag_stage_timing(
            record,
            "context",
            timestamp_ms=timestamp_ms,
        )
        retrieval_started_at_ms, retrieval_ended_at_ms, retrieval_duration_ms = _active_rag_stage_timing(
            record,
            "retrieval",
            timestamp_ms=timestamp_ms,
        )
        generation_started_at_ms, generation_ended_at_ms, generation_duration_ms = _active_rag_stage_timing(
            record,
            "generation",
            timestamp_ms=timestamp_ms,
        )
        evidence_refs = [
            {
                "kind": "retrieval_evidence",
                "id": item["evidenceId"],
                "label": item["sourceLane"],
            }
            for item in trace_evidence
        ]
        trace_id = f"trace:active-rag:{session_id}"
        common = {
            "traceId": trace_id,
            "sessionId": session_id,
            "roomId": "",
            "turnId": "",
            "runId": session_id,
            "createdAtMs": timestamp_ms,
            "privacyClass": "redacted",
            "attributes": {
                "frontAppBundleId": _bounded_label(request.get("frontAppBundleId")),
                "project": _bounded_label(request.get("project")),
                "app": _bounded_label(request.get("app")),
                "intent": _bounded_label(request.get("intent"), fallback="auto"),
                "rawTextStored": False,
                "sourceRawTextIncluded": privacy.get("rawTextIncluded") is True,
            },
            "refs": [
                {"kind": "active_rag", "id": session_id, "label": "闪电联想"},
                *evidence_refs,
            ],
        }
        if phase == "retrieval_complete":
            common["attributes"]["evidenceStage"] = "retrieval_output"
            common["attributes"]["traceEvidence"] = trace_evidence
        if phase == "started" or (
            terminal_stage == "context"
            and phase in {"cancelled", "stale_dropped", "failed"}
        ):
            context_metrics: dict[str, object] = {}
            selected_chars = _fingerprint_chars(request.get("selectedText"))
            if selected_chars is not None:
                context_metrics["selectedChars"] = selected_chars
            context_chars = _fingerprint_chars(request.get("currentContext"))
            if context_chars is not None:
                context_metrics["contextChars"] = context_chars
            provided_evidence_count = _optional_integer(
                request.get("providedEvidenceCount")
            )
            if provided_evidence_count is not None:
                context_metrics["providedEvidenceCount"] = provided_evidence_count
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:context",
                parentSpanId="",
                category="context",
                phase=phase,
                name="active_rag_context",
                status=stage_status.get("context", "completed" if phase == "started" else status),
                summary=(
                    "闪电联想上下文已取消"
                    if stage_status.get("context") == "cancelled"
                    else "闪电联想已捕获上下文元数据"
                ),
                startedAtMs=context_started_at_ms,
                metrics=context_metrics,
                durationMs=context_duration_ms,
                endedAtMs=context_ended_at_ms,
            )
        elif phase == "retrieval_complete" or terminal_stage == "retrieval":
            retrieval_metrics: dict[str, object] = {}
            evidence_count = _optional_integer(retrieval.get("evidenceCount"))
            if evidence_count is not None:
                retrieval_metrics["evidenceCount"] = evidence_count
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:retrieval",
                parentSpanId=f"span:active-rag:{session_id}:context",
                category="retrieval",
                phase=phase,
                name="active_rag_retrieval",
                status=stage_status.get(
                    "retrieval",
                    "completed" if phase == "retrieval_complete" else status,
                ),
                summary=(
                    "闪电联想检索失败"
                    if stage_status.get("retrieval") == "failed"
                    else "闪电联想检索已取消"
                    if stage_status.get("retrieval") == "cancelled"
                    else "闪电联想检索已完成"
                ),
                startedAtMs=retrieval_started_at_ms,
                metrics=retrieval_metrics,
                durationMs=retrieval_duration_ms,
                endedAtMs=retrieval_ended_at_ms,
            )
        else:
            elapsed_ms = _optional_number(record.get("elapsedMs"))
            generation_metrics: dict[str, object] = {}
            candidate_count = _optional_integer(generation.get("candidateCount"))
            if candidate_count is not None:
                generation_metrics["candidateCount"] = candidate_count
            if elapsed_ms is not None:
                generation_metrics["elapsedMs"] = elapsed_ms
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:generation",
                parentSpanId=f"span:active-rag:{session_id}:retrieval",
                category="runtime",
                phase=phase,
                name="active_rag_generation",
                status=stage_status.get("generation", status),
                summary=(
                    "闪电联想生成失败"
                    if status == "failed"
                    else "闪电联想生成已取消"
                    if status == "cancelled"
                    else "闪电联想生成已完成"
                    if status == "completed"
                    else "闪电联想正在生成"
                ),
                startedAtMs=generation_started_at_ms,
                metrics=generation_metrics,
                durationMs=generation_duration_ms,
                endedAtMs=generation_ended_at_ms,
            )


    def observe_input_generation_record(
        self,
        record: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one stateless foreground generation transition as metadata."""

        safe = _input_generation_projection_record(record)
        trace_id = _safe_public_token(safe.get("traceId"))
        request_id = _safe_public_token(safe.get("requestId"))
        phase = _safe_public_token(safe.get("phase"))
        status = _safe_public_token(safe.get("status"))
        expected_status = {
            "started": "running",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(phase)
        if (
            not trace_id.startswith("trace:input-generation:")
            or not request_id
            or status != expected_status
        ):
            return None
        timestamp_ms = _integer(
            safe.get("timestampMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        started_at_ms = _integer(
            safe.get("startedAtMs"),
            default=timestamp_ms,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        terminal = status in {"completed", "failed", "cancelled"}
        ended_at_ms = _optional_integer(safe.get("endedAtMs")) if terminal else None
        duration_ms = _optional_number(safe.get("durationMs")) if terminal else None
        request = safe.get("request") if isinstance(safe.get("request"), Mapping) else {}
        generation = (
            safe.get("generation") if isinstance(safe.get("generation"), Mapping) else {}
        )
        context_metrics = (
            request.get("contextMetrics")
            if isinstance(request.get("contextMetrics"), Mapping)
            else {}
        )
        metrics: dict[str, object] = {}
        for key in (
            "currentRequestChars",
            "currentContextChars",
            "selectedChars",
            "latencyBudgetMs",
        ):
            value = _optional_integer(request.get(key))
            if value is not None:
                metrics[key] = value
        for key in (
            "recentInputActualCount",
            "recentInputActualChars",
            "recentInputRequestedCount",
            "recentInputEffectiveCount",
            "recentInputRequestedChars",
            "recentInputEffectiveChars",
            "axNodeCount",
            "axCharacterCount",
            "axRequestedNodeCount",
            "axEffectiveNodeCount",
            "axActualNodeCount",
            "axRequestedCharCount",
            "axEffectiveCharCount",
            "axActualCharCount",
            "contextRequestedTokens",
            "contextEffectiveTokens",
        ):
            value = _optional_integer(context_metrics.get(key))
            if value is not None:
                metrics[key] = value
        for key in ("recentInputTruncated", "axTruncated", "contextTruncated"):
            value = context_metrics.get(key)
            if isinstance(value, bool):
                metrics[key] = value
        context_reason_attributes = {
            key: context_metrics[key]
            for key in (
                "recentInputUnavailableReason",
                "axUnavailableReason",
                "contextUnavailableReason",
            )
            if context_metrics.get(key) in _INPUT_GENERATION_CONTEXT_REASON_VALUES
        }
        for key in (
            "elapsedMs",
            "firstTokenMs",
            "inputTokens",
            "outputTokens",
            "totalTokens",
            "cacheReadTokens",
            "cacheWriteTokens",
        ):
            value = _optional_integer(generation.get(key))
            if value is not None:
                metrics[key] = value
        privacy = safe.get("privacy") if isinstance(safe.get("privacy"), Mapping) else {}
        attributes: dict[str, object] = {
            "sourceKind": "input_generation",
            "lifecycleAuthority": "agent_surface_runtime",
            "frontAppBundleId": _safe_public_token(request.get("frontAppBundleId")),
            "provider": _safe_public_token(
                generation.get("effectiveProvider") or request.get("requestedProvider")
            ),
            "model": _safe_public_token(
                generation.get("effectiveModel") or request.get("requestedModel")
            ),
            "thinkingLevel": _safe_public_token(
                generation.get("effectiveThinkingLevel")
                or request.get("requestedThinkingLevel")
            ),
            "rawTextStored": False,
            "sourceRawTextIncluded": privacy.get("rawTextIncluded") is True,
            **context_reason_attributes,
        }
        input_fingerprint = request.get("inputFingerprint")
        if isinstance(input_fingerprint, str) and re.fullmatch(
            r"sha256:[0-9a-f]{64}", input_fingerprint
        ):
            attributes["inputFingerprint"] = input_fingerprint
        failure_reason = _safe_public_token(generation.get("failureReason"))
        if failure_reason:
            attributes["failureReason"] = failure_reason
        return self.emit(
            eventId=f"observation:input-generation:{request_id}:{phase}",
            traceId=trace_id,
            spanId=_input_generation_span_id(request_id),
            parentSpanId="",
            sessionId="",
            roomId="",
            turnId="",
            runId=request_id,
            category="runtime",
            phase=f"generation_{phase}",
            name="input.generation",
            status=status,
            summary=(
                "输入生成已完成"
                if status == "completed"
                else "输入生成失败"
                if status == "failed"
                else "输入生成已取消"
                if status == "cancelled"
                else "输入生成正在运行"
            ),
            createdAtMs=timestamp_ms,
            startedAtMs=started_at_ms,
            endedAtMs=ended_at_ms,
            durationMs=duration_ms,
            privacyClass="redacted",
            metrics=metrics,
            attributes=attributes,
            refs=[{
                "kind": "input_generation",
                "id": _input_generation_ref_id(request_id),
                "label": "输入生成",
            }],
        )

    def observe_memory_recall_record(
        self,
        record: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one Session-memory lifecycle receipt as a common trace."""

        safe = _memory_recall_projection_record(record)
        recall_id = _identifier(safe.get("recallId"))
        session_id = _identifier(safe.get("sessionId"))
        if not recall_id or not session_id:
            return None
        timestamp_ms = _integer(
            safe.get("generatedAtMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        metrics = safe.get("metrics") if isinstance(safe.get("metrics"), Mapping) else {}
        source_attributes = (
            safe.get("attributes")
            if isinstance(safe.get("attributes"), Mapping)
            else {}
        )
        status = (
            str(safe.get("status"))
            if safe.get("status") in {"completed", "failed"}
            else "completed"
        )
        phase = "recall_failed" if status == "failed" else "recall_completed"
        failure_reason = _safe_public_token(safe.get("failureReason"))
        trace_evidence = _safe_trace_evidence(safe.get("traceEvidence"))
        refs = [
            {"kind": "memory_recall", "id": recall_id, "label": "Session 记忆召回"},
            *(
                {
                    "kind": "memory_evidence",
                    "id": str(item["evidenceId"]),
                    "label": str(item.get("sourceLane") or ""),
                }
                for item in trace_evidence
            ),
        ]
        return self.emit(
            eventId=f"observation:memory-recall:{recall_id}:{phase}",
            traceId=f"trace:memory-recall:{recall_id}",
            spanId=f"span:memory-recall:{recall_id}",
            parentSpanId="",
            sessionId=session_id,
            roomId="",
            turnId=_identifier(safe.get("turnId")),
            runId=recall_id,
            category="memory",
            phase=phase,
            name="memory.recall",
            status=status,
            summary=(
                "Session 记忆召回失败"
                if status == "failed"
                else "Session 记忆召回已完成"
            ),
            createdAtMs=timestamp_ms,
            startedAtMs=timestamp_ms,
            endedAtMs=timestamp_ms,
            durationMs=None,
            privacyClass="redacted",
            metrics=metrics,
            attributes={
                "trigger": _bounded_label(safe.get("trigger")),
                "embeddingFallback": source_attributes.get("embeddingFallback") is True,
                "failureRecorded": status == "failed",
                "evidenceStage": "memory_recall",
                "traceEvidence": trace_evidence,
                "rawMemoryTextStored": False,
                **(
                    {"failureReason": failure_reason}
                    if status == "failed" and failure_reason
                    else {}
                ),
            },
            refs=refs,
        )

    def observe_knowledge_retrieval_record(
        self,
        record: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one authorized Knowledge search as metadata-only retrieval."""

        safe = _knowledge_retrieval_projection_record(record)
        receipt_id = _identifier(safe.get("retrievalReceiptId"))
        session_id = _identifier(safe.get("sessionId"))
        if not receipt_id or not session_id:
            return None
        timestamp_ms = _integer(
            safe.get("timestampMs"),
            default=_now_ms(),
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        retrieval = safe.get("retrieval") if isinstance(safe.get("retrieval"), Mapping) else {}
        trace_evidence = _safe_trace_evidence(retrieval.get("traceEvidence"))
        refs = [
            {"kind": "knowledge_retrieval", "id": receipt_id, "label": "Knowledge 检索"},
            *(
                {
                    "kind": "knowledge_evidence",
                    "id": str(item["evidenceId"]),
                    "label": str(item.get("sourceLane") or ""),
                }
                for item in trace_evidence
            ),
        ]
        evidence_count = _optional_integer(retrieval.get("evidenceCount"))
        metrics = {"evidenceCount": evidence_count} if evidence_count is not None else {}
        return self.emit(
            eventId=f"observation:knowledge-retrieval:{receipt_id}:retrieval_complete",
            traceId=f"trace:knowledge-retrieval:{receipt_id}",
            spanId=f"span:knowledge-retrieval:{receipt_id}",
            parentSpanId="",
            sessionId=session_id,
            roomId=_identifier(safe.get("roomId")),
            turnId="",
            runId=receipt_id,
            category="retrieval",
            phase="retrieval_complete",
            name="knowledge.retrieval",
            status="completed",
            summary="Knowledge 检索已完成",
            createdAtMs=timestamp_ms,
            startedAtMs=timestamp_ms,
            endedAtMs=timestamp_ms,
            durationMs=None,
            privacyClass="redacted",
            metrics=metrics,
            attributes={
                "sourceKind": "knowledge",
                "evidenceStage": "retrieval_output",
                "traceEvidence": trace_evidence,
                "rawKnowledgeTextStored": False,
            },
            refs=refs,
        )

    def observe_browser_record(
        self,
        record: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one Browser command lifecycle transition without page data."""

        safe = _browser_projection_record(record)
        command_id = _identifier(safe.get("commandId"))
        action = _bounded_label(safe.get("action"))
        raw_status = _bounded_label(safe.get("status"))
        if not command_id or not action or raw_status not in {
            "queued", "claimed", "completed", "failed", "cancelled"
        }:
            return None
        status = "running" if raw_status == "claimed" else raw_status
        started_at_ms = _integer(safe.get("createdAtMs"), default=0, minimum=0)
        completed_at_ms = _optional_integer(safe.get("completedAtMs"))
        duration_ms = _optional_number(safe.get("durationMs"))
        event_at_ms = (
            completed_at_ms
            if completed_at_ms is not None
            else _optional_integer(safe.get("claimedAtMs"))
            if raw_status == "claimed"
            else started_at_ms
        )
        session_id = _identifier(safe.get("sessionId"))
        device_id = _identifier(safe.get("deviceId"))
        return self.emit(
            eventId=f"observation:browser:{command_id}:{raw_status}",
            traceId=f"trace:browser:command:{command_id}",
            spanId=f"span:browser:command:{command_id}",
            parentSpanId="",
            sessionId=session_id,
            roomId="",
            turnId="",
            runId=command_id,
            category="runtime",
            phase=f"command_{raw_status}",
            name=f"browser.command.{action}",
            status=status,
            summary=(
                "浏览器操作已完成"
                if raw_status == "completed"
                else "浏览器操作失败"
                if raw_status == "failed"
                else "浏览器操作已取消"
                if raw_status == "cancelled"
                else "浏览器正在执行操作"
                if raw_status == "claimed"
                else "浏览器操作已排队"
            ),
            createdAtMs=event_at_ms,
            startedAtMs=started_at_ms,
            endedAtMs=completed_at_ms if raw_status in {"completed", "failed", "cancelled"} else None,
            durationMs=duration_ms if raw_status in {"completed", "failed", "cancelled"} else None,
            privacyClass="metadata",
            metrics={},
            attributes={
                "sourceKind": "browser_control",
                "commandId": command_id,
                "action": action,
                "deviceId": device_id,
                "failureRecorded": safe.get("failureRecorded") is True,
                "rawResultStored": False,
            },
            refs=[{"kind": "browser_command", "id": command_id, "label": action}],
        )

    def emit_memory_event(
        self,
        *,
        phase: str,
        status: str,
        summary: str,
        run_id: str,
        attempt_id: str = "",
        metrics: Mapping[str, object] | None = None,
        refs: Sequence[Mapping[str, object]] | None = None,
        trace_id: str = "",
        maintenance_job_id: str = "",
        parent_span_id: str = "",
    ) -> dict[str, object]:
        safe_run_id = _identifier(run_id)
        if not safe_run_id:
            raise ValueError("run_id is required for memory maintenance observations")
        safe_phase = _bounded_label(phase, fallback="updated")
        safe_attempt_id = _identifier(attempt_id) or safe_run_id
        safe_trace_id = _identifier(trace_id) or f"trace:memory:{safe_run_id}"
        safe_maintenance_job_id = _identifier(maintenance_job_id)
        # Keep the historical owner-run span IDs when no Gateway context is
        # supplied.  A Gateway-owned maintenance run deliberately uses the
        # same trace as its job while retaining the owner run in runId and in
        # structured attributes, so the two identities cannot be confused.
        span_prefix = f"span:memory:{safe_run_id}"
        if safe_attempt_id != safe_run_id:
            span_prefix += f":attempt:{safe_attempt_id}"
        safe_parent_span_id = (
            _identifier(parent_span_id)
            if safe_phase == "started"
            else f"{span_prefix}:started"
        )
        timestamp_ms = _now_ms()
        attributes = {
            "rawMemoryTextStored": False,
            **(
                {"attemptId": safe_attempt_id}
                if safe_attempt_id != safe_run_id
                else {}
            ),
            **(
                {
                    "maintenanceJobId": safe_maintenance_job_id,
                    "ownerRunId": safe_run_id,
                    "traceContext": "gateway_memory_maintenance",
                }
                if safe_maintenance_job_id
                else {}
            ),
        }
        return self.emit(
            traceId=safe_trace_id,
            spanId=f"{span_prefix}:{safe_phase}",
            parentSpanId=safe_parent_span_id,
            sessionId="",
            roomId="",
            turnId="",
            runId=safe_run_id,
            category="memory",
            phase=safe_phase,
            name="memory_curation",
            status=status,
            summary=summary,
            createdAtMs=timestamp_ms,
            startedAtMs=timestamp_ms,
            # Current maintenance producers expose point observations, not
            # measured operation bounds. A terminal status is not evidence of
            # an end timestamp, so timing remains explicitly unavailable.
            endedAtMs=None,
            privacyClass="metadata",
            metrics=dict(metrics or {}),
            attributes=attributes,
            refs=list(refs or ()),
        )

    def _enqueue_projection(self, kind: str, value: object, *, force: bool = False) -> None:
        if self._projection_closed.is_set() and not force:
            return
        try:
            if force:
                self._projection_queue.put((kind, value), timeout=1.0)
            else:
                self._projection_queue.put_nowait((kind, value))
        except queue.Full:
            # Observation backpressure is intentionally fail-open. The primary
            # Agent, Room, and Active RAG paths must keep moving.  Do not turn
            # the overflow path into a blocking database write; retain a
            # bounded health receipt instead.
            with self._projection_health_lock:
                self._projection_dropped_count += 1
                self._projection_last_drop = {
                    "kind": kind,
                    "reason": "queue_full",
                    "createdAtMs": _now_ms(),
                }

    def _run_projection_worker(self) -> None:
        while True:
            kind, value = self._projection_queue.get()
            try:
                if kind == "close":
                    return
                if kind == "agent" and isinstance(value, tuple) and len(value) == 2:
                    event, room_id = value
                    if isinstance(event, AgentEventEnvelope):
                        self.observe_agent_event(event, room_id=str(room_id))
                elif kind == "room" and isinstance(value, Mapping):
                    self.observe_room_event(value)
                elif kind == "active_rag" and isinstance(value, Mapping):
                    self.observe_active_rag_record(value)
                elif kind == "input_generation" and isinstance(value, Mapping):
                    self.observe_input_generation_record(value)
                elif kind == "memory_recall" and isinstance(value, Mapping):
                    self.observe_memory_recall_record(value)
                elif kind == "knowledge_retrieval" and isinstance(value, Mapping):
                    self.observe_knowledge_retrieval_record(value)
                elif kind == "browser" and isinstance(value, Mapping):
                    self.observe_browser_record(value)
            except Exception as exc:
                # The projector is a non-authoritative diagnostic consumer,
                # but a silent failure makes Trace itself impossible to debug.
                # Record a metadata-only failure receipt from this worker so
                # the foreground producer still never waits on the journal.
                self._record_projection_failure(kind, exc)
            finally:
                self._projection_queue.task_done()

    def _record_projection_failure(self, kind: str, error: Exception) -> None:
        receipt_id = f"projection-failure:{uuid.uuid4().hex}"
        failure = {
            "receiptId": receipt_id,
            "kind": kind,
            "reason": "projection_exception",
            "errorType": type(error).__name__,
            "createdAtMs": _now_ms(),
            "persisted": False,
        }
        with self._projection_health_lock:
            self._projection_error_count += 1
            self._projection_last_failure = dict(failure)
            self._projection_failure_receipts.append(dict(failure))
        try:
            self.store.append(
                {
                    "eventId": f"observation:{receipt_id}",
                    "traceId": "trace:observation-projection",
                    "spanId": f"span:{receipt_id}",
                    "category": "system",
                    "phase": "projection_failure",
                    "name": "observation_projection",
                    "status": "failed",
                    "summary": "Trace 投影失败",
                    "createdAtMs": int(failure["createdAtMs"]),
                    "startedAtMs": int(failure["createdAtMs"]),
                    "endedAtMs": int(failure["createdAtMs"]),
                    "privacyClass": "metadata",
                    "metrics": {"eventCount": 1},
                    "attributes": {
                        "action": "projection_failure",
                        "failureKind": "projection_exception",
                        "producerKind": kind,
                        "receiptId": receipt_id,
                    },
                    "refs": [
                        {
                            "kind": "projection_failure",
                            "id": receipt_id,
                            "label": kind,
                        }
                    ],
                }
            )
        except Exception:
            # Health remains useful even if the journal itself is unavailable.
            return
        with self._projection_health_lock:
            self._projection_last_failure["persisted"] = True  # type: ignore[index]
            self._projection_failure_receipts[-1]["persisted"] = True


def _agent_projection_payload(event: AgentEventEnvelope) -> dict[str, object]:
    source = event.payload
    event_type = event.event_type
    payload: dict[str, object] = {}
    for key in ("runId", "durationMs"):
        if source.get(key) is not None:
            payload[key] = source[key]
    if event_type in {"provider_request_completed", "provider_request_failed"}:
        request_id = _identifier(source.get("requestId"))
        if request_id:
            payload["requestId"] = request_id
        payload["status"] = (
            "failed"
            if event_type == "provider_request_failed"
            else "completed"
        )
        for key, maximum in (("provider", 80), ("model", 160)):
            value = _bounded_label(source.get(key))
            if value:
                payload[key] = value[:maximum]
        started_at_ms = _optional_integer(source.get("startedAtMs"))
        if started_at_ms is not None:
            payload["startedAtMs"] = started_at_ms
        usage = source.get("usage")
        if isinstance(usage, Mapping):
            payload["usage"] = _usage_projection(usage)
    elif event_type == "message_completed":
        message = source.get("message") if isinstance(source.get("message"), Mapping) else {}
        blocks = message.get("blocks")
        attachments = message.get("attachments")
        payload.update(
            role=_bounded_label(message.get("role"), fallback="assistant"),
            blockCount=(
                len(blocks)
                if isinstance(blocks, Sequence)
                and not isinstance(blocks, (str, bytes, bytearray))
                else 0
            ),
            attachmentCount=(
                len(attachments)
                if isinstance(attachments, Sequence)
                and not isinstance(attachments, (str, bytes, bytearray))
                else 0
            ),
        )
        provider = _bounded_label(message.get("provider") or source.get("provider"))
        model = _bounded_label(message.get("model") or source.get("model"))
        usage = message.get("usage") if isinstance(message.get("usage"), Mapping) else source.get("usage")
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if isinstance(usage, Mapping):
            payload["usage"] = _usage_projection(usage)
    elif event_type in {"compaction_started", "compaction_completed"}:
        payload.update(
            reason=_bounded_label(source.get("reason"), fallback="threshold"),
            aborted=source.get("aborted") is True,
            willRetry=source.get("willRetry") is True,
            isError=bool(source.get("error")),
        )
        tokens_before = _optional_integer(source.get("tokensBefore"))
        if tokens_before is not None:
            payload["tokensBefore"] = tokens_before
        estimated_tokens_after = _optional_integer(source.get("estimatedTokensAfter"))
        if estimated_tokens_after is not None:
            payload["estimatedTokensAfter"] = estimated_tokens_after
    elif event_type == "status_changed":
        payload["status"] = _bounded_label(source.get("status"), fallback="updated")
    elif event_type in {"tool_started", "tool_progress", "tool_finished"}:
        payload.update(
            toolCallId=_identifier(source.get("toolCallId")),
            toolName=_bounded_label(source.get("toolName"), fallback="tool"),
            argumentFieldCount=_mapping_size(source.get("args")),
            resultFieldCount=_mapping_size(
                source.get("result") or source.get("partialResult")
            ),
            isError=source.get("isError") is True,
        )
        knowledge_activity = _knowledge_tool_projection(source.get("publicResult"))
        if knowledge_activity:
            payload["knowledgeActivity"] = knowledge_activity
    elif event_type in {"approval_required", "approval_resolved", "user_input_required"}:
        for key in ("approvalId", "requestId", "requestKind", "riskLevel"):
            if source.get(key) is not None:
                payload[key] = _bounded_label(source.get(key))
    elif event_type.startswith("memory_"):
        payload["due"] = source.get("due") is True
        pending_event_count = _optional_integer(source.get("pendingEventCount"))
        if pending_event_count is not None:
            payload["pendingEventCount"] = pending_event_count
        pending_draft_count = _optional_integer(source.get("pendingDraftCount"))
        if pending_draft_count is not None:
            payload["pendingDraftCount"] = pending_draft_count
    elif event_type in {"turn_completed", "turn_failed"}:
        payload.update(
            status=_bounded_label(source.get("status")),
            aborted=source.get("aborted") is True,
            messageCount=_integer(source.get("messageCount"), default=0, minimum=0),
        )
        if event_type == "turn_failed":
            failure_kind = _safe_public_token(source.get("failureKind"))
            failure_reason = _safe_public_token(
                source.get("reason") or source.get("reasonCode")
            )
            failure_detail = _public_failure_detail(source.get("error"), maximum=500)
            next_step = _public_failure_detail(source.get("nextStep"), maximum=300)
            if failure_kind:
                payload["failureKind"] = failure_kind
            if failure_reason:
                payload["reason"] = failure_reason
            if failure_detail:
                payload["error"] = failure_detail
            if next_step:
                payload["nextStep"] = next_step
    elif source.get("isError") is not None:
        payload["isError"] = source.get("isError") is True
    telemetry = _telemetry_projection(source.get("telemetry"))
    if telemetry:
        payload["telemetry"] = telemetry
    return payload


def _knowledge_tool_projection(value: object) -> dict[str, object]:
    """Whitelist the metadata-only Knowledge receipt from either Pi protocol."""

    if not isinstance(value, Mapping):
        return {}
    if value.get("activityKind") != "knowledge_retrieval" or value.get("operation") != "search":
        return {}
    result: dict[str, object] = {
        "activityKind": "knowledge_retrieval",
        "operation": "search",
        "evidenceStage": "retrieval_output",
        "traceEvidence": _safe_trace_evidence(value.get("traceEvidence")),
    }
    kb_id = _safe_public_token(value.get("kbId"))
    if kb_id:
        result["knowledgeBaseId"] = kb_id
    retrieval_mode = _safe_public_token(value.get("retrievalMode"))
    if retrieval_mode:
        result["retrievalMode"] = retrieval_mode
    evidence_count = _optional_integer(value.get("evidenceCount"))
    if evidence_count is not None:
        result["evidenceCount"] = evidence_count
    return result


def _telemetry_projection(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    model = value.get("model") if isinstance(value.get("model"), Mapping) else {}
    public_model = {
        key: label
        for key in ("provider", "id", "name")
        if (label := _bounded_label(model.get(key)))
    }
    if public_model:
        result["model"] = public_model

    context = value.get("context") if isinstance(value.get("context"), Mapping) else {}
    public_context: dict[str, object] = {}
    for key in (
        "tokens",
        "contextWindow",
        "remainingTokens",
        "compactAtTokens",
        "tokensUntilCompact",
    ):
        number = _optional_integer(context.get(key))
        if number is not None:
            public_context[key] = number
    percent = _optional_number(context.get("percent"))
    if percent is not None:
        public_context["percent"] = min(percent, 100.0)
    if public_context:
        result["context"] = public_context

    latest_usage = value.get("latestUsage")
    if isinstance(latest_usage, Mapping):
        result["latestUsage"] = _usage_projection(latest_usage)
    cache_hit = _optional_number(value.get("latestCacheHitPercent"))
    if cache_hit is not None:
        result["latestCacheHitPercent"] = min(cache_hit, 100.0)
    result["isCompacting"] = value.get("isCompacting") is True
    compaction_count = _optional_integer(value.get("compactionCount"))
    if compaction_count is not None:
        result["compactionCount"] = compaction_count
    return result


def _usage_projection(value: Mapping[object, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
        number = _optional_integer(value.get(key))
        if number is not None:
            result[key] = number
    return result


def _apply_agent_telemetry_observation(
    telemetry: Mapping[str, object],
    *,
    attributes: dict[str, object],
    metrics: dict[str, object],
) -> None:
    if not telemetry:
        return
    model = telemetry.get("model") if isinstance(telemetry.get("model"), Mapping) else {}
    for source_key, target_key in (
        ("provider", "provider"),
        ("id", "model"),
        ("name", "modelName"),
    ):
        label = _bounded_label(model.get(source_key))
        if label:
            attributes[target_key] = label

    context = telemetry.get("context") if isinstance(telemetry.get("context"), Mapping) else {}
    for source_key, target_key in (
        ("tokens", "contextTokens"),
        ("contextWindow", "contextWindowTokens"),
        ("percent", "contextPercent"),
        ("remainingTokens", "remainingTokens"),
        ("compactAtTokens", "compactAtTokens"),
        ("tokensUntilCompact", "tokensUntilCompact"),
    ):
        if context.get(source_key) is not None:
            metrics[target_key] = context[source_key]

    latest_usage = telemetry.get("latestUsage")
    if isinstance(latest_usage, Mapping):
        _apply_usage_metrics(latest_usage, metrics)
    if telemetry.get("latestCacheHitPercent") is not None:
        metrics["cacheHitPercent"] = telemetry["latestCacheHitPercent"]
    compaction_count = _optional_integer(telemetry.get("compactionCount"))
    if compaction_count is not None:
        metrics["compactionCount"] = compaction_count
    attributes["isCompacting"] = telemetry.get("isCompacting") is True


def _apply_usage_metrics(
    usage: Mapping[object, object],
    metrics: dict[str, object],
) -> None:
    for source_key, target_key in (
        ("input", "inputTokens"),
        ("output", "outputTokens"),
        ("cacheRead", "cacheReadTokens"),
        ("cacheWrite", "cacheWriteTokens"),
        ("totalTokens", "totalTokens"),
    ):
        number = _optional_integer(usage.get(source_key))
        if number is not None:
            metrics[target_key] = number


def _room_identity_value(payload: Mapping[str, object], key: str) -> str:
    """Return one unambiguous Room identity from bounded public payload maps."""

    values: set[str] = set()
    for name, container in (
        ("payload", payload),
        *((name, payload.get(name)) for name in ("message", "work", "post", "receipt")),
    ):
        if not isinstance(container, Mapping):
            continue
        value = _identifier(container.get(key))
        if not value and key == "workItemId" and name == "work":
            value = _identifier(container.get("id"))
        if value:
            values.add(value)
    return next(iter(values)) if len(values) == 1 else ""


def _room_work_trace_evidence(work: Mapping[str, object]) -> list[dict[str, object]]:
    """Project only already-public WorkItem refs into the common Trace.

    Local paths and URLs are owner-local data, not public evidence identities.
    They are omitted instead of being copied or replaced with a derived token.
    """

    result: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for source_kind, key in (
        ("room_artifact_ref", "artifactRefs"),
        ("room_evidence_ref", "evidenceRefs"),
    ):
        values = work.get(key)
        if not isinstance(values, Sequence) or isinstance(
            values, (str, bytes, bytearray)
        ):
            continue
        for raw_value in values:
            if not isinstance(raw_value, str):
                continue
            value = raw_value.strip()
            safe_ref = _safe_public_token(value)
            evidence_id = f"{source_kind}:{safe_ref}"
            identity = (source_kind, safe_ref)
            if (
                not safe_ref
                or "/" in safe_ref
                or len(evidence_id) > 160
                or identity in seen
            ):
                continue
            seen.add(identity)
            result.append(
                {
                    "evidenceId": evidence_id,
                    "sourceKind": source_kind,
                    "sourceRef": safe_ref,
                    "sourceLane": "room_work_item",
                    "disposition": "included",
                    "scores": {},
                    "rankBefore": None,
                    "rankAfter": None,
                    "omissionReason": "",
                }
            )
    return result


def _room_projection_token(value: object, *, fallback: str = "") -> str:
    """Keep only one opaque Room identity before the async queue boundary."""

    token = _safe_public_token(value)
    # ``_safe_public_token`` also serves a few public identifier fields that
    # legitimately contain slash-separated names.  Room wire identities do
    # not; rejecting slashes here prevents relative paths from entering the
    # process-local projection queue.
    return token if token and "/" not in token else fallback


def _room_projection_event(event: Mapping[str, object]) -> dict[str, object]:
    source = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    event_type = _room_projection_token(event.get("eventType"), fallback="room_event")
    data = source.get("data") if isinstance(source.get("data"), Mapping) else source
    payload: dict[str, object] = {}
    for key in (
        "phase",
        "activityKind",
        "status",
        "targetParticipantId",
        "parentParticipantId",
        "rootId",
        "dispatchId",
        "parentDispatchId",
        "childDispatchId",
        "toolCallId",
        "workItemId",
        "attemptId",
        "requestKind",
        "toolName",
        "messageId",
        "blockId",
        "caseId",
        "acceptedTurnId",
        "sourceTurnId",
    ):
        if data.get(key) is not None:
            payload[key] = _room_projection_token(data.get(key))
    for key in ("workItemId", "caseId", "acceptedTurnId", "sourceTurnId"):
        if key not in payload and source.get(key) is not None:
            payload[key] = _room_projection_token(source.get(key))
    work_item_revision = _optional_integer(data.get("workItemRevision"))
    if work_item_revision is not None:
        payload["workItemRevision"] = work_item_revision
    duration_ms = _optional_number(data.get("durationMs"))
    if duration_ms is not None:
        payload["durationMs"] = duration_ms
    source_event_id = _room_projection_token(source.get("sourceEventId"))
    if source_event_id:
        payload["sourceEventId"] = source_event_id
        payload["sourceEventType"] = _room_projection_token(source.get("sourceEventType"))
    if event_type == "user_message":
        character_count = source.get("characterCount")
        if character_count is None and data is not source:
            character_count = data.get("characterCount")
        if character_count is None:
            raw_text = source.get("text")
            if raw_text is None and data is not source:
                raw_text = data.get("text")
            if isinstance(raw_text, str):
                character_count = len(raw_text)
        safe_character_count = _optional_integer(character_count)
        if safe_character_count is not None:
            payload["characterCount"] = safe_character_count
    if event_type == "participant_activity" and data.get("activityKind") == "intercom":
        message = data.get("message") if isinstance(data.get("message"), Mapping) else {}
        payload["message"] = {
            key: _room_projection_token(message.get(key))
            for key in (
                "id",
                "kind",
                "sourceParticipantId",
                "targetParticipantId",
                "status",
                "replyTo",
                "workItemId",
                "workAction",
                "acceptedTurnId",
                "caseId",
                "sourceTurnId",
            )
            if message.get(key) is not None
        }
    if event_type == "participant_activity" and data.get("activityKind") == "work":
        work = data.get("work") if isinstance(data.get("work"), Mapping) else {}
        payload["work"] = {
            key: _room_projection_token(work.get(key))
            for key in (
                "id",
                "state",
                "currentOwnerParticipantId",
                "accountableParticipantId",
                "offeredToParticipantId",
                "acceptedTurnId",
                "workItemId",
                "caseId",
                "sourceTurnId",
            )
            if work.get(key) is not None
        }
        work_revision = _optional_integer(work.get("revision"))
        if work_revision is not None:
            payload["work"]["revision"] = work_revision
        work_evidence = _room_work_trace_evidence(work)
        if work_evidence:
            # Preserve review evidence across the async projection boundary,
            # but never retain the WorkItem's raw local path or URL refs.
            payload["workTraceEvidence"] = work_evidence
    if event_type == "room_post":
        post = data.get("post") if isinstance(data.get("post"), Mapping) else {}
        payload["post"] = {
            key: _room_projection_token(post.get(key))
            for key in (
                "postId",
                "rootId",
                "dispatchId",
                "authorActorRef",
                "kind",
                "workItemId",
                "caseId",
                "acceptedTurnId",
                "sourceTurnId",
            )
            if post.get(key) is not None
        }
    if event_type == "room_post":
        receipt = data.get("receipt") if isinstance(data.get("receipt"), Mapping) else {}
        if receipt:
            payload["receipt"] = {
                key: _room_projection_token(receipt.get(key))
                for key in (
                    "workItemId",
                    "caseId",
                    "acceptedTurnId",
                    "sourceTurnId",
                )
                if receipt.get(key) is not None
            }
    if event_type == "participant_message":
        message = data.get("message") if isinstance(data.get("message"), Mapping) else {}
        payload["messageId"] = _room_projection_token(message.get("id"))
    return {
        "eventId": _room_projection_token(event.get("eventId")),
        "roomId": _room_projection_token(event.get("roomId")),
        "turnId": _room_projection_token(event.get("turnId")),
        "participantId": _room_projection_token(event.get("participantId")),
        "sourceSessionId": _room_projection_token(event.get("sourceSessionId")),
        "eventType": event_type,
        "createdAtMs": _optional_integer(event.get("createdAtMs")),
        "payload": payload,
    }


def _active_rag_projection_record(record: Mapping[str, object]) -> dict[str, object]:
    privacy = record.get("privacy") if isinstance(record.get("privacy"), Mapping) else {}
    request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
    retrieval = record.get("retrieval") if isinstance(record.get("retrieval"), Mapping) else {}
    generation = record.get("generation") if isinstance(record.get("generation"), Mapping) else {}
    stage_timing = _safe_active_rag_stage_timing(record.get("stageTiming"))
    stage_status = _safe_active_rag_stage_status(record.get("stageStatus"))
    trace_evidence = _safe_trace_evidence(retrieval.get("traceEvidence"))
    retrieval_payload: dict[str, object] = {}
    evidence_count = _optional_integer(retrieval.get("evidenceCount"))
    if evidence_count is not None:
        retrieval_payload["evidenceCount"] = evidence_count
    if retrieval.get("evidenceStage") == "retrieval_output":
        retrieval_payload.update(
            evidenceStage="retrieval_output",
            traceEvidence=trace_evidence,
        )
    request_payload: dict[str, object] = {
        "frontAppBundleId": _bounded_label(request.get("frontAppBundleId")),
        "project": _bounded_label(request.get("project")),
        "app": _bounded_label(request.get("app")),
        "intent": _bounded_label(request.get("intent"), fallback="auto"),
    }
    selected_chars = _fingerprint_chars(request.get("selectedText"))
    if selected_chars is not None:
        request_payload["selectedText"] = {"chars": selected_chars}
    context_chars = _fingerprint_chars(request.get("currentContext"))
    if context_chars is not None:
        request_payload["currentContext"] = {"chars": context_chars}
    provided_evidence_count = _optional_integer(request.get("providedEvidenceCount"))
    if provided_evidence_count is not None:
        request_payload["providedEvidenceCount"] = provided_evidence_count
    generation_payload: dict[str, object] = {}
    candidate_count = _optional_integer(generation.get("candidateCount"))
    if candidate_count is not None:
        generation_payload["candidateCount"] = candidate_count
    projected = {
        "timestampMs": record.get("timestampMs"),
        "phase": _bounded_label(record.get("phase"), fallback="updated"),
        "sessionId": _identifier(record.get("sessionId")),
        "status": _bounded_label(record.get("status")),
        "elapsedMs": _optional_number(record.get("elapsedMs")),
        "privacy": {"rawTextIncluded": privacy.get("rawTextIncluded") is True},
        "request": request_payload,
        "retrieval": retrieval_payload,
        "generation": generation_payload,
    }
    trace_status = _safe_public_token(record.get("traceStatus"))
    if trace_status in {"running", "completed", "failed", "cancelled"}:
        projected["traceStatus"] = trace_status
    terminal_stage = _safe_public_token(record.get("terminalStage"))
    if terminal_stage in {"context", "retrieval", "generation"}:
        projected["terminalStage"] = terminal_stage
    if stage_status:
        projected["stageStatus"] = stage_status
    if stage_timing:
        projected["stageTiming"] = stage_timing
    return projected


def _safe_active_rag_stage_status(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for stage in ("context", "retrieval", "generation"):
        status = _safe_public_token(value.get(stage))
        if status in {"running", "completed", "failed", "cancelled"}:
            result[stage] = status
    return result


def _safe_active_rag_stage_timing(value: object) -> dict[str, dict[str, int]]:
    """Whitelist explicit Active RAG stage timing before async projection."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, dict[str, int]] = {}
    for stage in ("context", "retrieval", "generation"):
        timing = value.get(stage)
        if not isinstance(timing, Mapping):
            continue
        started = _optional_stage_timing_integer(timing.get("startedAtMs"))
        if started is None or started < 0:
            continue
        item = {"startedAtMs": started}
        ended = _optional_stage_timing_integer(timing.get("endedAtMs"))
        duration = _optional_stage_timing_integer(timing.get("durationMs"))
        if (
            ended is not None
            and duration is not None
            and ended >= started
            and duration >= 0
            and ended - started == duration
        ):
            item.update({"endedAtMs": ended, "durationMs": duration})
        result[stage] = item
    return result


def _input_generation_projection_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    """Whitelist stateless generation metadata before async journaling."""

    request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
    context = (
        request.get("contextMetrics")
        if isinstance(request.get("contextMetrics"), Mapping)
        else {}
    )
    generation = (
        record.get("generation")
        if isinstance(record.get("generation"), Mapping)
        else {}
    )
    privacy = record.get("privacy") if isinstance(record.get("privacy"), Mapping) else {}
    request_payload: dict[str, object] = {}
    for key in (
        "frontAppBundleId",
        "requestedProvider",
        "requestedModel",
        "requestedThinkingLevel",
    ):
        value = _safe_public_token(request.get(key))
        if value:
            request_payload[key] = value
    input_fingerprint = request.get("inputFingerprint")
    if isinstance(input_fingerprint, str) and re.fullmatch(
        r"sha256:[0-9a-f]{64}", input_fingerprint
    ):
        request_payload["inputFingerprint"] = input_fingerprint
    for key in (
        "currentRequestChars",
        "currentContextChars",
        "selectedChars",
        "latencyBudgetMs",
    ):
        value = _optional_integer(request.get(key))
        if value is not None:
            request_payload[key] = value
    context_payload: dict[str, object] = {}
    for key in (
        "recentInputActualCount",
        "recentInputActualChars",
        "recentInputRequestedCount",
        "recentInputEffectiveCount",
        "recentInputRequestedChars",
        "recentInputEffectiveChars",
        "axNodeCount",
        "axCharacterCount",
        "axRequestedNodeCount",
        "axEffectiveNodeCount",
        "axActualNodeCount",
        "axRequestedCharCount",
        "axEffectiveCharCount",
        "axActualCharCount",
        "contextRequestedTokens",
        "contextEffectiveTokens",
    ):
        value = _optional_integer(context.get(key))
        if value is not None:
            context_payload[key] = value
    for key in ("recentInputTruncated", "axTruncated", "contextTruncated"):
        value = context.get(key)
        if isinstance(value, bool):
            context_payload[key] = value
    for key in (
        "recentInputUnavailableReason",
        "axUnavailableReason",
        "contextUnavailableReason",
    ):
        value = context.get(key)
        if value in _INPUT_GENERATION_CONTEXT_REASON_VALUES:
            context_payload[key] = value
    if context_payload:
        request_payload["contextMetrics"] = context_payload

    generation_payload: dict[str, object] = {}
    for key in (
        "effectiveProvider",
        "effectiveModel",
        "effectiveThinkingLevel",
        "failureReason",
    ):
        value = _safe_public_token(generation.get(key))
        if value:
            generation_payload[key] = value
    if isinstance(generation.get("ok"), bool):
        generation_payload["ok"] = generation["ok"]
    if isinstance(generation.get("cancelled"), bool):
        generation_payload["cancelled"] = generation["cancelled"]
    for key in (
        "elapsedMs",
        "firstTokenMs",
        "inputTokens",
        "outputTokens",
        "totalTokens",
        "cacheReadTokens",
        "cacheWriteTokens",
    ):
        value = _optional_integer(generation.get(key))
        if value is not None:
            generation_payload[key] = value
    return {
        "traceId": _safe_public_token(record.get("traceId")),
        "requestId": _safe_public_token(record.get("requestId")),
        "phase": _safe_public_token(record.get("phase")),
        "status": _safe_public_token(record.get("status")),
        "timestampMs": _optional_integer(record.get("timestampMs")),
        "startedAtMs": _optional_integer(record.get("startedAtMs")),
        "endedAtMs": _optional_integer(record.get("endedAtMs")),
        "durationMs": _optional_number(record.get("durationMs")),
        "request": request_payload,
        "generation": generation_payload,
        "privacy": {"rawTextIncluded": privacy.get("rawTextIncluded") is True},
    }


def _input_generation_span_id(request_id: str) -> str:
    """Keep the input-generation span within the common identifier grammar.

    Short public request identities remain inspectable.  At the maximum legal
    request length, the readable prefix would exceed the 160-character Trace
    contract, so use a deterministic SHA-256 identity instead.  The digest is
    collision-resistant and avoids truncating two distinct request attempts to
    the same span.
    """

    readable = f"span:input-generation:{request_id}"
    if len(readable) <= 160:
        return readable
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"span:input-generation:sha256:{digest}"


def _input_generation_ref_id(request_id: str) -> str:
    """Bound the evidence identity after the public kind prefix is added."""

    if len(f"input_generation:{request_id}") <= 160:
        return request_id
    return f"sha256:{hashlib.sha256(request_id.encode('utf-8')).hexdigest()}"


def _is_input_generation_terminal(
    *,
    trace_id: str,
    span_id: str,
    category: str,
    name: str,
    status: str,
) -> bool:
    """Identify the one lifecycle whose terminal result must be fenced."""

    return (
        trace_id.startswith("trace:input-generation:")
        and span_id.startswith("span:input-generation:")
        and category == "runtime"
        and name == "input.generation"
        and status in {"completed", "failed", "cancelled"}
    )


def _memory_recall_projection_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    """Whitelist a producer receipt before it enters the async journal."""

    metrics = record.get("metrics") if isinstance(record.get("metrics"), Mapping) else {}
    attributes = (
        record.get("attributes")
        if isinstance(record.get("attributes"), Mapping)
        else {}
    )
    raw_status = record.get("status")
    status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in {"completed", "failed"}
        else "completed"
    )
    public_metrics: dict[str, int] = {}
    for key in (
        "selectedCount",
        "omittedCount",
        "recentCompleteInputCount",
        "recentConversationCount",
        "usedChars",
        "maxItems",
    ):
        number = _optional_integer(metrics.get(key))
        if number is not None:
            public_metrics[key] = number
    projected = {
        "recallId": _identifier(record.get("recallId")),
        "sessionId": _identifier(record.get("sessionId")),
        "trigger": _bounded_label(record.get("trigger")),
        "generatedAtMs": _optional_integer(record.get("generatedAtMs")),
        "status": status,
        "failureReason": _safe_public_token(record.get("failureReason")),
        "metrics": public_metrics,
        "attributes": {
            "embeddingFallback": attributes.get("embeddingFallback") is True,
            "failureRecorded": attributes.get("failureRecorded") is True,
            "evidenceStage": "memory_recall",
        },
        "traceEvidence": _safe_trace_evidence(record.get("traceEvidence")),
    }
    turn_id = _identifier(record.get("turnId"))
    if turn_id:
        projected["turnId"] = turn_id
    return projected


def _knowledge_retrieval_projection_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    """Whitelist authorized Knowledge retrieval metadata before journaling."""

    retrieval = record.get("retrieval") if isinstance(record.get("retrieval"), Mapping) else {}
    retrieval_payload: dict[str, object] = {
        "traceEvidence": _safe_trace_evidence(
            retrieval.get("traceEvidence")
        ),
    }
    evidence_count = _optional_integer(retrieval.get("evidenceCount"))
    if evidence_count is not None:
        retrieval_payload["evidenceCount"] = evidence_count
    return {
        "retrievalReceiptId": _identifier(record.get("retrievalReceiptId")),
        "sessionId": _identifier(record.get("sessionId")),
        "roomId": _identifier(record.get("roomId")),
        "timestampMs": _integer(
            record.get("timestampMs"),
            default=0,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        ),
        "sourceKind": "knowledge",
        "evidenceStage": "retrieval_output",
        "retrieval": retrieval_payload,
    }


def _browser_projection_record(record: Mapping[str, object]) -> dict[str, object]:
    """Whitelist Browser command metadata before it enters the journal."""

    return {
        "commandId": _identifier(record.get("commandId")),
        "deviceId": _identifier(record.get("deviceId")),
        "sessionId": _identifier(record.get("sessionId")),
        "action": _bounded_label(record.get("action")),
        "status": _bounded_label(record.get("status")),
        "createdAtMs": _integer(
            record.get("createdAtMs"),
            default=0,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        ),
        "claimedAtMs": _optional_integer(record.get("claimedAtMs")),
        "completedAtMs": _optional_integer(record.get("completedAtMs")),
        "durationMs": _optional_number(record.get("durationMs")),
        "failureRecorded": record.get("failureRecorded") is True,
    }


def _row_payload(row: sqlite3.Row) -> dict[str, object]:
    sequence = int(row["sequence"])
    payload = {
        "schemaVersion": "rag-ime.observation-event.v1",
        "eventType": "observation",
        "eventId": str(row["event_id"]),
        "sequence": sequence,
        "resumeToken": _resume_token(sequence),
        "traceId": str(row["trace_id"]),
        "spanId": str(row["span_id"]),
        "parentSpanId": str(row["parent_span_id"]),
        "sessionId": str(row["session_id"]),
        "roomId": str(row["room_id"]),
        "turnId": str(row["turn_id"]),
        "runId": str(row["run_id"]),
        "category": str(row["category"]),
        "phase": str(row["phase"]),
        "name": str(row["name"]),
        "status": str(row["status"]),
        "summary": str(row["summary"]),
        "createdAtMs": int(row["created_at_ms"]),
        "startedAtMs": int(row["started_at_ms"]),
        "endedAtMs": int(row["ended_at_ms"]) if row["ended_at_ms"] is not None else None,
        "durationMs": float(row["duration_ms"]) if row["duration_ms"] is not None else None,
        "privacyClass": str(row["privacy_class"]),
        # Re-project on read as well as write.  This keeps legacy rows and a
        # manually altered local journal from becoming a public bypass.
        "metrics": _safe_metrics(_json_object(row["metrics_json"])),
        "attributes": _safe_attributes(_json_object(row["attributes_json"])),
        "refs": _safe_refs(_json_array(row["refs_json"])),
    }
    validate_contract(payload, "observation-event.v1.json")
    return payload


def _snapshot_required_event(last_sequence: int, after_event_id: str) -> dict[str, object]:
    created_at_ms = _now_ms()
    payload = {
        "schemaVersion": "rag-ime.observation-event.v1",
        "eventType": "snapshot_required",
        "eventId": f"observation:snapshot-required:{uuid.uuid4().hex}",
        "sequence": max(0, int(last_sequence)),
        "resumeToken": _resume_token(max(0, int(last_sequence))),
        "traceId": "trace:observation:system",
        "spanId": f"span:observation:snapshot:{uuid.uuid4().hex}",
        "parentSpanId": "",
        "sessionId": "",
        "roomId": "",
        "turnId": "",
        "runId": "",
        "category": "system",
        "phase": "snapshot_required",
        "name": "observation_replay_gap",
        "status": "waiting",
        "summary": "观察事件已超出重放窗口，需要重新读取快照",
        "createdAtMs": created_at_ms,
        "startedAtMs": created_at_ms,
        "endedAtMs": created_at_ms,
        "durationMs": 0,
        "privacyClass": "metadata",
        "metrics": {},
        "attributes": {
            "reason": "event_replay_gap",
            "invalidResumeToken": bool(after_event_id),
        },
        "refs": [],
    }
    validate_contract(payload, "observation-event.v1.json")
    return payload


def _event_sse(event: Mapping[str, object]) -> bytes:
    body = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))
    return (
        f"id: {event['resumeToken']}\n"
        f"event: {event['eventType']}\n"
        f"data: {body}\n\n"
    ).encode("utf-8")


def _normalize_filters(values: Mapping[str, object] | None) -> dict[str, str]:
    source = dict(values or {})
    filters: dict[str, str] = {}
    for key in _FILTER_KEYS:
        value = _identifier(source.get(key))
        if not value:
            continue
        if key == "category" and value not in OBSERVATION_CATEGORIES:
            raise ValueError(f"unknown observation category: {value}")
        if key == "status" and value not in OBSERVATION_STATUSES:
            raise ValueError(f"unknown observation status: {value}")
        filters[key] = value
    return filters


def _filter_clause(filters: Mapping[str, str]) -> tuple[list[str], list[object]]:
    columns = {
        "sessionId": "session_id",
        "roomId": "room_id",
        "traceId": "trace_id",
        "runId": "run_id",
        "category": "category",
        "status": "status",
    }
    where: list[str] = []
    values: list[object] = []
    for key, value in filters.items():
        column = columns[key]
        where.append(f"{column} = ?")
        values.append(value)
    return where, values


def _matches_filters(event: Mapping[str, object], filters: Mapping[str, str]) -> bool:
    return all(str(event.get(key) or "") == value for key, value in filters.items())


def _safe_metrics(value: object) -> dict[str, int | float | bool]:
    """Project journal metrics to known non-negative scalar channels."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int | float | bool] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        if not isinstance(raw_key, str):
            continue
        if raw_key in _PUBLIC_METRIC_BOOLEAN_KEYS:
            if isinstance(raw_value, bool):
                result[raw_key] = raw_value
            continue
        if raw_key not in _PUBLIC_METRIC_NUMBER_KEYS:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        if not math.isfinite(float(raw_value)) or float(raw_value) < 0:
            continue
        result[raw_key] = raw_value
    return result


def _safe_attributes(value: object) -> dict[str, object]:
    """Project journal attributes to typed identifiers and validated channels."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        if not isinstance(raw_key, str):
            continue
        if raw_key == "traceEvidence":
            if isinstance(raw_value, Sequence) and not isinstance(
                raw_value, (str, bytes, bytearray)
            ):
                result[raw_key] = _safe_trace_evidence(raw_value)
            continue
        if raw_key == "artifactRefs":
            if isinstance(raw_value, Sequence) and not isinstance(
                raw_value, (str, bytes, bytearray)
            ):
                result[raw_key] = _safe_artifact_refs(raw_value)
            continue
        if raw_key in _PUBLIC_ATTRIBUTE_BOOLEAN_KEYS:
            if isinstance(raw_value, bool):
                result[raw_key] = raw_value
            continue
        if raw_key in _PUBLIC_ATTRIBUTE_INTEGER_KEYS:
            if (
                isinstance(raw_value, int)
                and not isinstance(raw_value, bool)
                and raw_value >= 0
            ):
                result[raw_key] = raw_value
            continue
        if raw_key in _PUBLIC_ATTRIBUTE_FINGERPRINT_KEYS:
            if isinstance(raw_value, str) and re.fullmatch(
                r"sha256:[0-9a-f]{64}", raw_value
            ):
                result[raw_key] = raw_value
            continue
        if raw_key == "reason":
            if isinstance(raw_value, str) and raw_value in _PUBLIC_REASON_VALUES:
                result[raw_key] = raw_value
            continue
        if raw_key not in _PUBLIC_ATTRIBUTE_IDENTIFIER_KEYS:
            continue
        safe_value = _safe_public_token(raw_value)
        if safe_value:
            result[raw_key] = safe_value
    return result


def _safe_refs(value: object) -> list[dict[str, str]]:
    """Project generic refs without allowing URLs, paths, or free-form labels."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, str]] = []
    for item in list(value)[:32]:
        if not isinstance(item, Mapping):
            continue
        raw_kind = item.get("kind")
        if raw_kind in (None, ""):
            kind = "reference"
        else:
            kind = _safe_public_token(raw_kind)
            if not kind:
                continue
        reference_id = _safe_public_token(item.get("id"))
        if not reference_id:
            continue
        result.append(
            {
                "kind": kind,
                "id": reference_id,
                "label": _safe_public_label(item.get("label")),
            }
        )
    return result


def _safe_artifact_refs(value: object) -> list[dict[str, object]]:
    """Project artifact refs to their typed, non-content public shape."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, object]] = []
    for raw in list(value)[:32]:
        if not isinstance(raw, Mapping):
            continue
        artifact_id = _safe_public_token(raw.get("artifactId"))
        kind = _safe_public_token(raw.get("kind"))
        media_type = raw.get("mediaType")
        sha256 = raw.get("sha256")
        byte_size = raw.get("byteSize")
        record_count = raw.get("recordCount")
        if (
            not artifact_id
            or not kind
            or not isinstance(media_type, str)
            or not _PUBLIC_MIME_PATTERN.fullmatch(media_type)
            or not isinstance(sha256, str)
            or not _PUBLIC_SHA256_PATTERN.fullmatch(sha256)
            or not _safe_non_negative_int(byte_size)
            or not _safe_non_negative_int(record_count)
        ):
            continue
        result.append(
            {
                "artifactId": artifact_id,
                "kind": kind,
                "mediaType": media_type,
                "sha256": sha256,
                "byteSize": byte_size,
                "recordCount": record_count,
            }
        )
    return result


def _safe_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_public_token(value: object, *, maximum: int = 160) -> str:
    """Accept one opaque identifier, never a URL/path or sentence."""

    if not isinstance(value, str) or not value or len(value) > maximum:
        return ""
    if value != value.strip() or any(char.isspace() for char in value):
        return ""
    pattern = _PUBLIC_LONG_TOKEN_PATTERN if maximum > 160 else _PUBLIC_TOKEN_PATTERN
    if not pattern.fullmatch(value):
        return ""
    if (
        "://" in value
        or any(char in value for char in ("?", "#", "@", "\\"))
        or value.startswith(("/", "~"))
        or re.match(r"^[A-Za-z]:[/\\]", value)
        or (
            ":" in value
            and value.split(":", 1)[0].lower() in {"file", "http", "https"}
        )
        or any(segment in {".", ".."} for segment in value.split("/"))
    ):
        return ""
    return value


def _safe_public_label(value: object) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        return ""
    if value in _PUBLIC_REFERENCE_LABELS:
        return value
    return _safe_public_token(value, maximum=96)


def _safe_source_ref(value: object) -> str:
    """Allow opaque refs and knowledge/fixture URIs, not web/file URLs."""

    if not isinstance(value, str) or not value or len(value) > 512:
        return ""
    if value != value.strip() or any(char.isspace() for char in value):
        return ""
    if any(char in value for char in ("?", "#", "@", "\\")):
        return ""
    if value.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[/\\]", value):
        return ""
    if "://" not in value:
        if (
            ":" in value
            and value.split(":", 1)[0].lower() in {"file", "http", "https"}
        ):
            return ""
        return _safe_public_token(value, maximum=512)
    if value.count("://") != 1:
        return ""
    scheme, remainder = value.split("://", 1)
    if scheme.lower() not in {"knowledge", "fixture"}:
        return ""
    if not _PUBLIC_SOURCE_SCHEME_PATTERN.fullmatch(scheme) or not remainder:
        return ""
    authority, separator, path = remainder.partition("/")
    if not _PUBLIC_SOURCE_AUTHORITY_PATTERN.fullmatch(authority):
        return ""
    if separator:
        if not path or not _PUBLIC_SOURCE_PATH_PATTERN.fullmatch(path):
            return ""
        if any(segment in {".", ".."} for segment in path.split("/")):
            return ""
    return value


def _sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return normalized in _SENSITIVE_KEY_TOKENS or any(
        normalized.endswith(token) for token in _SENSITIVE_KEY_TOKENS
    )


def _fingerprint_chars(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    return _optional_integer(value.get("chars"))


def _active_rag_status(value: object, phase: str) -> str:
    state = _bounded_label(value).lower()
    if state in {"failed", "error"} or phase == "failed":
        return "failed"
    if state in {"cancelled", "canceled", "stale_dropped"} or phase in {
        "cancelled",
        "stale_dropped",
    }:
        return "cancelled"
    if state in {"completed", "ready"} or phase in {"completed", "ready"}:
        return "completed"
    if phase in {"visible_timeout", "stream_partial"}:
        return "running"
    return "running"


def _safe_trace_evidence(value: object) -> list[dict[str, object]]:
    """Whitelist typed retrieval receipt metadata before it enters the journal."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, object]] = []
    # A Room WorkItem can carry 16 artifact refs and 24 evidence refs.  Keep a
    # single bound above that source contract so the journal never silently
    # drops the tail of one valid submission.
    for raw in list(value)[:64]:
        if not isinstance(raw, Mapping):
            continue
        evidence_id = _safe_public_token(raw.get("evidenceId"))
        source_ref = _safe_source_ref(raw.get("sourceRef"))
        if not evidence_id or not source_ref:
            continue
        scores: dict[str, float] = {}
        raw_scores = raw.get("scores") if isinstance(raw.get("scores"), Mapping) else {}
        for raw_key, raw_value in list(raw_scores.items())[:16]:
            key = raw_key if isinstance(raw_key, str) else ""
            score = _bounded_trace_score(raw_value)
            if (
                key in _PUBLIC_EVIDENCE_SCORE_KEYS
                and not _sensitive_key(key)
                and score is not None
            ):
                scores[key] = round(score, 6)
        rank_before = _positive_exact_rank(raw.get("rankBefore"))
        rank_after = _positive_exact_rank(raw.get("rankAfter"))
        raw_source_kind = raw.get("sourceKind")
        source_kind = (
            "unknown"
            if raw_source_kind in (None, "")
            else _safe_public_token(raw_source_kind)
        )
        if not source_kind:
            continue
        raw_source_lane = raw.get("sourceLane")
        source_lane = (
            ""
            if raw_source_lane in (None, "")
            else _safe_public_token(raw_source_lane)
        )
        if raw_source_lane not in (None, "") and not source_lane:
            continue
        raw_disposition = raw.get("disposition")
        if raw_disposition in (None, ""):
            disposition = "included"
        elif isinstance(raw_disposition, str) and raw_disposition in {
            "included",
            "omitted",
            "filtered",
            "redacted",
        }:
            disposition = raw_disposition
        else:
            continue
        raw_omission_reason = raw.get("omissionReason")
        omission_reason = (
            ""
            if raw_omission_reason in (None, "")
            else _safe_public_token(raw_omission_reason)
        )
        if raw_omission_reason not in (None, "") and not omission_reason:
            continue
        if disposition == "included" and omission_reason:
            continue
        if disposition != "included" and not omission_reason:
            continue
        result.append(
            {
                "evidenceId": evidence_id,
                "sourceKind": source_kind,
                "sourceRef": source_ref,
                "sourceLane": source_lane,
                "disposition": disposition,
                "scores": scores,
                "rankBefore": rank_before,
                "rankAfter": rank_after,
                "omissionReason": omission_reason,
            }
        )
    return result


def _intercom_status(value: str) -> str:
    return {
        "queued": "queued",
        "delivering": "running",
        "delivered": "completed",
        "replied": "completed",
        "failed": "failed",
        "stale": "failed",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }.get(value.lower(), "info")


def _room_status_from_phase(
    phase: object,
    state: object,
    *,
    default: str,
) -> str:
    """Map public Room lifecycle labels without inventing a terminal state."""

    labels = {
        _bounded_label(phase).lower(),
        _bounded_label(state).lower(),
    }
    labels.discard("")
    if labels & {
        "failed",
        "error",
        "dispatch_failed",
        "assignment_failed",
        "turn_failed",
    }:
        return "failed"
    if labels & {"aborted", "cancelled", "canceled", "timed_out"}:
        return "cancelled"
    if labels & {
        "completed",
        "done",
        "accepted",
        "delivered",
        "turn_completed",
        "tool_finished",
    }:
        return "completed"
    if labels & {"blocked", "escalated", "review", "submitted", "waiting"}:
        return "waiting"
    if labels & {"queued", "assigned", "offered"}:
        return "queued"
    if labels & {"started", "running", "active", "claimed", "returned"}:
        return "running"
    return default if default in OBSERVATION_STATUSES else "info"


def _observation_sequence(value: str) -> int | None:
    if not value:
        return 0
    match = re.fullmatch(r"observation:(\d+)", str(value).strip())
    return int(match.group(1)) if match else None


def _resume_token(sequence: int) -> str:
    return f"observation:{max(0, int(sequence))}"


def _mapping_size(value: object) -> int:
    return len(value) if isinstance(value, Mapping) else 0


def _choice(value: object, allowed: frozenset[str], fallback: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else fallback


def _bounded_label(value: object, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return (text[:160] or fallback)[:160]


def _bounded_summary(value: object) -> str:
    """Normalize the explicitly public producer summary channel.

    Summaries are product-authored public copy; unlike metrics, attributes,
    and refs they are not passed through heuristic prose redaction.
    """

    return " ".join(str(value or "").split())[:240]


def _public_failure_detail(value: object, *, maximum: int = 240) -> str:
    """Keep a bounded, redacted runtime failure useful to diagnostics."""

    if value in (None, ""):
        return ""
    return redact_runtime_text(str(value))[:maximum]


def _identifier(value: object) -> str:
    text = str(value or "").strip()
    if not text or any(ord(char) < 32 for char in text):
        return ""
    return text[:240]


def _required_identifier(value: object, fallback: str = "") -> str:
    return _identifier(value) or fallback or f"id:{uuid.uuid4().hex}"


def _integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int = 2_147_483_647,
) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def _optional_integer(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0, min(number, 9_223_372_036_854_775_807))


def _optional_stage_timing_integer(value: object) -> int | None:
    """Accept only JSON integers for public lifecycle timing.

    Generic metadata counters intentionally coerce numeric input for backwards
    compatibility.  Stage timestamps and durations are measurement evidence,
    so a JSON float (including ``30.0``) is unavailable rather than silently
    truncated into a different timing claim.
    """

    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 0:
        return None
    return min(value, 9_223_372_036_854_775_807)


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, number) if math.isfinite(number) else None


def _bounded_trace_score(value: object) -> float | None:
    """Preserve signed retrieval scores while rejecting non-finite values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return max(-1_000_000.0, min(1_000_000.0, number))


def _positive_exact_rank(value: object) -> int | None:
    """Accept integral JSON numbers only; a fractional rank is unavailable."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 1 or not number.is_integer():
        return None
    return int(number)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


_JSON_PERSISTED_COLUMNS = frozenset(
    {"metrics_json", "attributes_json", "refs_json"}
)


def _canonical_json_text(value: object) -> str:
    """Normalize persisted JSON for replay comparison without rewriting rows."""

    raw = str(value)
    try:
        parsed = json.loads(raw)
        return json.dumps(
            parsed,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return raw


def _canonical_persisted_row(
    row: sqlite3.Row,
    columns: Sequence[str],
) -> tuple[object, ...]:
    return tuple(
        _canonical_json_text(row[column])
        if column in _JSON_PERSISTED_COLUMNS
        else row[column]
        for column in columns
    )


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_array(value: object) -> list[object]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _now_ms() -> int:
    return int(time.time() * 1000)
