from __future__ import annotations

import json
import math
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .agent_protocol import AgentEventEnvelope
from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


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
    {"queued", "running", "waiting", "completed", "failed", "cancelled", "info"}
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
_FILTER_KEYS = ("sessionId", "roomId", "traceId", "category", "status")


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
        event_id = _identifier(values.get("eventId")) or f"observation:{uuid.uuid4().hex}"
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
        metrics = _safe_object(values.get("metrics"))
        attributes = _safe_object(values.get("attributes"))
        refs = _safe_refs(values.get("refs"))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_observation_events(
                    event_id, trace_id, span_id, parent_span_id,
                    session_id, room_id, turn_id, run_id,
                    category, phase, name, status, summary,
                    created_at_ms, started_at_ms, ended_at_ms, duration_ms,
                    privacy_class, metrics_json, attributes_json, refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    _required_identifier(values.get("traceId"), fallback=f"trace:{event_id}"),
                    _required_identifier(values.get("spanId"), fallback=f"span:{event_id}"),
                    _identifier(values.get("parentSpanId")),
                    _identifier(values.get("sessionId")),
                    _identifier(values.get("roomId")),
                    _identifier(values.get("turnId")),
                    _identifier(values.get("runId")),
                    _choice(values.get("category"), OBSERVATION_CATEGORIES, "system"),
                    _bounded_label(values.get("phase"), fallback="observed"),
                    _bounded_label(values.get("name"), fallback="observation"),
                    _choice(values.get("status"), OBSERVATION_STATUSES, "info"),
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
            sequence = int(cursor.lastrowid)
            self._prune_locked(conn, now_ms=created_at_ms)
            row = conn.execute(
                "SELECT * FROM agent_observation_events WHERE sequence = ?",
                (sequence,),
            ).fetchone()
        if row is None:  # pragma: no cover - the insert and read share one transaction
            raise RuntimeError("observation event was not persisted")
        return _row_payload(row)

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
        self._projection_closed = threading.Event()
        self._projection_thread = threading.Thread(
            target=self._run_projection_worker,
            name="rag-ime-observation-projector",
            daemon=True,
        )
        self._projection_thread.start()

    def emit(self, **values: object) -> dict[str, object]:
        event = self.store.append(values)
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

    def flush(self, timeout_seconds: float = 2.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while self._projection_queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        return True

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
        status = "info"
        summary = "Agent 运行状态已更新"
        run_id = _identifier(payload.get("runId"))
        span_suffix = event.event_id
        refs: list[dict[str, str]] = [
            {"kind": "agent_event", "id": event.event_id, "label": event_type}
        ]
        attributes: dict[str, object] = {"sourceEventType": event_type}
        metrics: dict[str, object] = {}

        if event_type == "message_completed":
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
            status = "completed"
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
            metrics.update(
                pendingEventCount=_integer(payload.get("pendingEventCount"), default=0, minimum=0),
                pendingDraftCount=_integer(payload.get("pendingDraftCount"), default=0, minimum=0),
            )
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
            name=event_type,
            status=status,
            summary=summary,
            createdAtMs=event.created_at_ms,
            startedAtMs=event.created_at_ms,
            endedAtMs=event.created_at_ms if status in {"completed", "failed", "cancelled"} else None,
            durationMs=_optional_number(payload.get("durationMs")),
            privacyClass="redacted",
            metrics=metrics,
            attributes=attributes,
            refs=refs,
        )

    def observe_room_event(self, event: Mapping[str, object]) -> dict[str, object] | None:
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        if payload.get("sourceEventId"):
            return None
        room_id = _identifier(event.get("roomId"))
        if not room_id:
            return None
        event_type = _bounded_label(event.get("eventType"), fallback="room_event")
        turn_id = _identifier(event.get("turnId"))
        session_id = _identifier(event.get("sourceSessionId"))
        participant_id = _identifier(event.get("participantId"))
        category = "room"
        status = "info"
        summary = "Room 状态已更新"
        metrics: dict[str, object] = {}
        attributes: dict[str, object] = {"sourceEventType": event_type}
        refs: list[dict[str, str]] = [
            {"kind": "room_event", "id": _required_identifier(event.get("eventId")), "label": event_type}
        ]

        if event_type == "user_message":
            summary = "Room 收到用户消息"
            metrics["characterCount"] = _integer(
                payload.get("characterCount"),
                default=len(str(payload.get("text") or "")),
                minimum=0,
            )
            attributes["rawMessageStored"] = False
            status = "queued"
        elif event_type == "route_decision":
            summary = "Room 已完成参与者路由"
            target = _identifier(payload.get("targetParticipantId"))
            if target:
                refs.append({"kind": "participant", "id": target, "label": "目标参与者"})
            status = "completed"
        elif event_type == "participant_activity" and payload.get("activityKind") == "intercom":
            category = "intercom"
            message = payload.get("message") if isinstance(payload.get("message"), Mapping) else {}
            message_id = _identifier(message.get("id")) or _required_identifier(event.get("eventId"))
            phase = _bounded_label(payload.get("phase"), fallback="updated")
            message_status = _bounded_label(message.get("status"), fallback=phase)
            attributes.update(
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
            status = _intercom_status(message_status)
            summary = {
                "queued": "Agent 私信已进入队列",
                "running": "Agent 私信正在投递",
                "completed": "Agent 私信已送达",
                "failed": "Agent 私信投递失败",
                "cancelled": "Agent 私信已取消",
            }.get(status, "Agent 私信状态已更新")
        elif event_type in {"turn_completed", "turn_failed"}:
            status = "failed" if event_type == "turn_failed" else "completed"
            summary = "Room 回合执行失败" if status == "failed" else "Room 回合已完成"
        elif event_type == "participant_status":
            attributes["participantState"] = _bounded_label(payload.get("status"), fallback="updated")
            summary = "Room 参与者状态已更新"

        trace_id = (
            f"trace:room-turn:{turn_id}" if turn_id else f"trace:room:{room_id}"
        )
        span_id = (
            f"span:participant:{participant_id}:{event_type}"
            if participant_id
            else f"span:room:{_required_identifier(event.get('eventId'))}"
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
            parentSpanId=f"span:room-turn:{turn_id}" if turn_id else "",
            sessionId=session_id,
            roomId=room_id,
            turnId=turn_id,
            runId="",
            category=category,
            phase=_bounded_label(payload.get("phase"), fallback=event_type),
            name=event_type,
            status=status,
            summary=summary,
            createdAtMs=created_at_ms,
            startedAtMs=created_at_ms,
            endedAtMs=created_at_ms
            if status in {"completed", "failed", "cancelled"}
            else None,
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
        status = _active_rag_status(record.get("status"), phase)
        privacy = record.get("privacy") if isinstance(record.get("privacy"), Mapping) else {}
        request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
        retrieval = (
            record.get("retrieval") if isinstance(record.get("retrieval"), Mapping) else {}
        )
        generation = (
            record.get("generation") if isinstance(record.get("generation"), Mapping) else {}
        )
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
            "refs": [{"kind": "active_rag", "id": session_id, "label": "闪电联想"}],
        }
        if phase == "started":
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:context",
                parentSpanId="",
                category="context",
                phase=phase,
                name="active_rag_context",
                status="completed",
                summary="闪电联想已捕获上下文元数据",
                startedAtMs=timestamp_ms,
                metrics={
                    "selectedChars": _fingerprint_chars(request.get("selectedText")),
                    "contextChars": _fingerprint_chars(request.get("currentContext")),
                    "providedEvidenceCount": _integer(
                        request.get("providedEvidenceCount"), default=0, minimum=0
                    ),
                },
                durationMs=None,
                endedAtMs=timestamp_ms,
            )
        elif phase == "retrieval_complete":
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:retrieval",
                parentSpanId=f"span:active-rag:{session_id}:context",
                category="retrieval",
                phase=phase,
                name="active_rag_retrieval",
                status="completed",
                summary="闪电联想检索已完成",
                startedAtMs=timestamp_ms,
                metrics={
                    "evidenceCount": _integer(
                        retrieval.get("evidenceCount"), default=0, minimum=0
                    ),
                },
                durationMs=None,
                endedAtMs=timestamp_ms,
            )
        else:
            elapsed_ms = _optional_number(record.get("elapsedMs"))
            self.emit(
                **common,
                spanId=f"span:active-rag:{session_id}:generation",
                parentSpanId=f"span:active-rag:{session_id}:retrieval",
                category="runtime",
                phase=phase,
                name="active_rag_generation",
                status=status,
                summary=(
                    "闪电联想生成失败"
                    if status == "failed"
                    else "闪电联想生成已取消"
                    if status == "cancelled"
                    else "闪电联想生成已完成"
                    if status == "completed"
                    else "闪电联想正在生成"
                ),
                startedAtMs=max(0, timestamp_ms - int(elapsed_ms or 0)),
                metrics={
                    "candidateCount": _integer(
                        generation.get("candidateCount"), default=0, minimum=0
                    ),
                    "elapsedMs": _integer(
                        record.get("elapsedMs"), default=0, minimum=0
                    ),
                },
                durationMs=elapsed_ms,
                endedAtMs=timestamp_ms if status in {"completed", "failed", "cancelled"} else None,
            )

    def emit_memory_event(
        self,
        *,
        phase: str,
        status: str,
        summary: str,
        run_id: str = "",
        metrics: Mapping[str, object] | None = None,
        refs: Sequence[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        safe_run_id = _identifier(run_id)
        timestamp_ms = _now_ms()
        return self.emit(
            traceId=f"trace:memory:{safe_run_id or uuid.uuid4().hex}",
            spanId=f"span:memory:{safe_run_id or uuid.uuid4().hex}:{phase}",
            parentSpanId="",
            sessionId="",
            roomId="",
            turnId="",
            runId=safe_run_id,
            category="memory",
            phase=phase,
            name="memory_curation",
            status=status,
            summary=summary,
            createdAtMs=timestamp_ms,
            startedAtMs=timestamp_ms,
            endedAtMs=timestamp_ms
            if status in {"completed", "failed", "cancelled"}
            else None,
            privacyClass="metadata",
            metrics=dict(metrics or {}),
            attributes={"rawMemoryTextStored": False},
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
            # Agent, Room, and Active RAG paths must keep moving.
            return

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
            except Exception:
                # The projector is a non-authoritative diagnostic consumer.
                pass
            finally:
                self._projection_queue.task_done()


def _agent_projection_payload(event: AgentEventEnvelope) -> dict[str, object]:
    source = event.payload
    event_type = event.event_type
    payload: dict[str, object] = {}
    for key in ("runId", "durationMs"):
        if source.get(key) is not None:
            payload[key] = source[key]
    if event_type == "message_completed":
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
    elif event_type in {"approval_required", "approval_resolved", "user_input_required"}:
        for key in ("approvalId", "requestId", "requestKind", "riskLevel"):
            if source.get(key) is not None:
                payload[key] = _bounded_label(source.get(key))
    elif event_type.startswith("memory_"):
        payload.update(
            pendingEventCount=_integer(
                source.get("pendingEventCount"), default=0, minimum=0
            ),
            pendingDraftCount=_integer(
                source.get("pendingDraftCount"), default=0, minimum=0
            ),
            due=source.get("due") is True,
        )
    elif event_type in {"turn_completed", "turn_failed"}:
        payload.update(
            status=_bounded_label(source.get("status")),
            aborted=source.get("aborted") is True,
            messageCount=_integer(source.get("messageCount"), default=0, minimum=0),
        )
    elif source.get("isError") is not None:
        payload["isError"] = source.get("isError") is True
    return payload


def _room_projection_event(event: Mapping[str, object]) -> dict[str, object]:
    source = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    event_type = _bounded_label(event.get("eventType"), fallback="room_event")
    payload: dict[str, object] = {}
    for key in (
        "sourceEventId",
        "phase",
        "activityKind",
        "status",
        "targetParticipantId",
    ):
        if source.get(key) is not None:
            payload[key] = _bounded_label(source.get(key))
    if event_type == "user_message":
        payload["characterCount"] = len(str(source.get("text") or ""))
    if event_type == "participant_activity" and source.get("activityKind") == "intercom":
        message = source.get("message") if isinstance(source.get("message"), Mapping) else {}
        payload["message"] = {
            key: _bounded_label(message.get(key))
            for key in (
                "id",
                "kind",
                "sourceParticipantId",
                "targetParticipantId",
                "status",
                "replyTo",
            )
            if message.get(key) is not None
        }
    return {
        "eventId": _identifier(event.get("eventId")),
        "roomId": _identifier(event.get("roomId")),
        "turnId": _identifier(event.get("turnId")),
        "participantId": _identifier(event.get("participantId")),
        "sourceSessionId": _identifier(event.get("sourceSessionId")),
        "eventType": event_type,
        "createdAtMs": event.get("createdAtMs"),
        "payload": payload,
    }


def _active_rag_projection_record(record: Mapping[str, object]) -> dict[str, object]:
    privacy = record.get("privacy") if isinstance(record.get("privacy"), Mapping) else {}
    request = record.get("request") if isinstance(record.get("request"), Mapping) else {}
    retrieval = record.get("retrieval") if isinstance(record.get("retrieval"), Mapping) else {}
    generation = record.get("generation") if isinstance(record.get("generation"), Mapping) else {}
    return {
        "timestampMs": record.get("timestampMs"),
        "phase": _bounded_label(record.get("phase"), fallback="updated"),
        "sessionId": _identifier(record.get("sessionId")),
        "status": _bounded_label(record.get("status")),
        "elapsedMs": _optional_number(record.get("elapsedMs")),
        "privacy": {"rawTextIncluded": privacy.get("rawTextIncluded") is True},
        "request": {
            "frontAppBundleId": _bounded_label(request.get("frontAppBundleId")),
            "project": _bounded_label(request.get("project")),
            "app": _bounded_label(request.get("app")),
            "intent": _bounded_label(request.get("intent"), fallback="auto"),
            "selectedText": {"chars": _fingerprint_chars(request.get("selectedText"))},
            "currentContext": {"chars": _fingerprint_chars(request.get("currentContext"))},
            "providedEvidenceCount": _integer(
                request.get("providedEvidenceCount"), default=0, minimum=0
            ),
        },
        "retrieval": {
            "evidenceCount": _integer(
                retrieval.get("evidenceCount"), default=0, minimum=0
            )
        },
        "generation": {
            "candidateCount": _integer(
                generation.get("candidateCount"), default=0, minimum=0
            )
        },
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
        "metrics": _json_object(row["metrics_json"]),
        "attributes": _json_object(row["attributes_json"]),
        "refs": _json_array(row["refs_json"]),
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


def _safe_object(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        key = _bounded_label(raw_key)
        if not key or _sensitive_key(key):
            continue
        safe = _safe_value(raw_value, depth=0)
        if safe is not None:
            result[key] = safe
    return result


def _safe_value(value: object, *, depth: int) -> object | None:
    if depth > 3:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, Mapping):
        return {
            key: safe
            for raw_key, raw_value in list(value.items())[:32]
            if (key := _bounded_label(raw_key))
            and not _sensitive_key(key)
            and (safe := _safe_value(raw_value, depth=depth + 1)) is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            safe
            for item in list(value)[:32]
            if (safe := _safe_value(item, depth=depth + 1)) is not None
        ]
    return None


def _safe_refs(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, str]] = []
    for item in list(value)[:32]:
        if not isinstance(item, Mapping):
            continue
        kind = _bounded_label(item.get("kind"), fallback="reference")
        reference_id = _identifier(item.get("id"))
        if not reference_id:
            continue
        result.append(
            {
                "kind": kind,
                "id": reference_id,
                "label": _bounded_label(item.get("label")),
            }
        )
    return result


def _sensitive_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return normalized in _SENSITIVE_KEY_TOKENS or any(
        normalized.endswith(token) for token in _SENSITIVE_KEY_TOKENS
    )


def _fingerprint_chars(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    return _integer(value.get("chars"), default=0, minimum=0)


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
    return "running"


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
    return " ".join(str(value or "").split())[:240]


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
    if value is None:
        return None
    return _integer(value, default=0, minimum=0, maximum=9_223_372_036_854_775_807)


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return max(0.0, number) if math.isfinite(number) else None


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


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
