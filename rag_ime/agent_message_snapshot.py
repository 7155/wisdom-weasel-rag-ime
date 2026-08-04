from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeAlias

from .agent_protocol import AgentEventEnvelope
from .contracts.json_schema import validate_contract

RoomPublicMessageProvider: TypeAlias = Callable[
    [str],
    Mapping[str, object] | None,
]

_ROOM_CONTEXT_OPEN = "<room-context>"
_ROOM_CONTEXT_CLOSE = "</room-context>"
_TRANSIENT_CONTEXT_PREFIX = "RAG_IME_TRANSIENT_CONTEXT_V1\n"


class AgentMessageSnapshotService:
    """Project one Session snapshot from Pi, durable rows, and live events."""

    def __init__(
        self,
        *,
        sessions: Any,
        runtime_provider: Callable[[], Any],
        workflow_projector: Callable[[str], Mapping[str, object]],
        agent_blocks: Any,
        observations: Any,
        events: Any,
        background_jobs: Any,
        room_public_messages: RoomPublicMessageProvider,
    ) -> None:
        self.sessions = sessions
        self._runtime_provider = runtime_provider
        self._workflow_projector = workflow_projector
        self.agent_blocks = agent_blocks
        self.observations = observations
        self.events = events
        self.background_jobs = background_jobs
        self._room_public_messages = room_public_messages

    @property
    def runtime(self) -> Any:
        """Resolve the current interactive Runtime after policy replacement."""

        return self._runtime_provider()

    def messages(
        self,
        session_id: str,
        *,
        event_limit: int | None = None,
        before_event_id: str = "",
        turn_limit: int | None = None,
        before_message_id: str = "",
    ) -> dict[str, object]:
        session = self.sessions.get(session_id)
        last_sequence = self.sessions.max_event_sequence(session_id)
        snapshot_provider = getattr(
            self.runtime,
            "session_snapshot",
            None,
        )
        runtime_snapshot = (
            snapshot_provider(session_id)
            if callable(snapshot_provider)
            else None
        )
        messages = (
            list(runtime_snapshot.get("messages") or [])
            if isinstance(runtime_snapshot, Mapping)
            else self.runtime.messages(session_id)
        )
        messages = self.agent_blocks.hydrate_messages(
            session_id,
            [
                message
                for message in messages
                if isinstance(message, Mapping)
            ],
        )
        room_projection = self._room_public_messages(session_id)
        if room_projection is not None:
            messages = _project_room_public_messages(
                session_id=session_id,
                private_messages=messages,
                projection=room_projection,
            )
        total_messages = len(messages)
        history_page: dict[str, object] = {}
        if turn_limit is not None:
            messages, message_page = _message_turn_page(
                messages,
                limit=turn_limit,
                before_message_id=before_message_id,
            )
            history_page.update(message_page)
        telemetry = _mapping_field(runtime_snapshot, "telemetry")
        message_queue = _mapping_field(
            runtime_snapshot,
            "messageQueue",
        )
        tool_history_events = (
            list(runtime_snapshot.get("toolHistoryEvents") or [])
            if isinstance(runtime_snapshot, Mapping)
            else []
        )
        try:
            observation_snapshot = self.observations.snapshot(
                {
                    "sessionId": session_id,
                    "category": "tool",
                    "limit": 500,
                }
            )
        except Exception:
            observed_tool_events: list[object] = []
        else:
            observed_tool_events = list(
                observation_snapshot.get("items") or []
            )
        tool_history_events = _apply_observed_times(
            tool_history_events,
            observed_tool_events,
        )
        replayed, _gap = self.events.replay(session_id)
        replay_events = [
            event.to_payload()
            for event in replayed
            if event.sequence <= last_sequence
        ]
        live_events = _merge_tool_events(
            tool_history_events,
            replay_events,
        )
        self._append_pending_approvals(
            session_id=session_id,
            live_events=live_events,
            last_sequence=last_sequence,
        )
        self._append_pending_ui_requests(
            session_id=session_id,
            live_events=live_events,
            last_sequence=last_sequence,
        )
        if event_limit is not None:
            live_events, event_page = _live_event_page(
                live_events,
                limit=event_limit,
                before_event_id=before_event_id,
            )
            history_page.update(event_page)
        session = self._reconcile_session_status(
            session_id,
            session,
        )
        # Runtime Host message counts describe Provider-loop entries (including
        # tool calls), not the human transcript.  Reconcile only after the
        # visible private and Room-public branches have been projected, so a
        # Session cannot open as an apparently empty conversation.
        if int(session.get("messageCount") or 0) != total_messages:
            session = self.sessions.set_status(
                session_id,
                str(session.get("status") or "idle"),
                message_count=total_messages,
            )
        workflow = self._workflow_projector(session_id)
        background_jobs = self.background_jobs.list(
            session_id,
            limit=100,
        )
        lifecycle_cancellation_audits = (
            self.sessions.lifecycle_cancellation_audits(
                session_id,
                limit=20,
            )
        )
        response: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-message-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": messages,
            "status": str(session.get("status") or "idle"),
            "liveEvents": live_events,
            "lastSequence": last_sequence,
            "resumeToken": (
                f"{session_id}:{last_sequence}"
                if last_sequence
                else ""
            ),
            "telemetry": telemetry,
            "messageQueue": message_queue,
            "todo": workflow["todo"],
            "goal": workflow["goal"],
            "actGate": workflow["actGate"],
            "backgroundJobs": list(background_jobs.get("items") or []),
            "lifecycleCancellationAudits": lifecycle_cancellation_audits,
        }
        if history_page:
            response["historyPage"] = history_page
        return response

    def _append_pending_approvals(
        self,
        *,
        session_id: str,
        live_events: list[dict[str, object]],
        last_sequence: int,
    ) -> None:
        visible_ids = {
            str(event.get("payload", {}).get("approvalId") or "")
            for event in live_events
            if event.get("eventType") == "approval_required"
            and isinstance(event.get("payload"), Mapping)
        }
        approvals = self.sessions.list_approvals(
            session_id=session_id,
            state="pending",
            limit=100,
        )
        for approval in reversed(approvals):
            approval_id = str(approval.get("approvalId") or "")
            if not approval_id or approval_id in visible_ids:
                continue
            event_id = f"{session_id}:snapshot:{approval_id}"
            causal = approval.get("causalMetadata")
            causal_turn_id = (
                str(causal.get("turnId") or "").strip()
                if isinstance(causal, Mapping)
                else ""
            )
            live_events.append(
                AgentEventEnvelope(
                    event_id=event_id,
                    session_id=session_id,
                    turn_id=causal_turn_id or f"approval:{approval_id}",
                    sequence=max(1, last_sequence),
                    created_at_ms=int(
                        approval.get("requestedAtMs") or 0
                    ),
                    event_type="approval_required",
                    payload={
                        **approval,
                        "toolName": str(
                            approval.get("toolId") or ""
                        ),
                        "summary": str(
                            approval.get("operation")
                            or "需要批准的工具操作"
                        ),
                    },
                    resume_token=event_id,
                ).to_payload()
            )

    def _append_pending_ui_requests(
        self,
        *,
        session_id: str,
        live_events: list[dict[str, object]],
        last_sequence: int,
    ) -> None:
        pending_provider = getattr(self.runtime, "pending_ui_requests", None)
        if not callable(pending_provider):
            return
        visible_ids = {
            str(event.get("payload", {}).get("requestId") or "")
            for event in live_events
            if event.get("eventType") == "user_input_required"
            and isinstance(event.get("payload"), Mapping)
        }
        for pending in pending_provider(session_id):
            if not isinstance(pending, Mapping):
                continue
            request_id = str(pending.get("requestId") or "")
            if not request_id or request_id in visible_ids:
                continue
            turn_id = str(pending.get("turnId") or f"ui:{request_id}")
            created_at_ms = int(pending.get("createdAtMs") or 0)
            payload = {
                key: value
                for key, value in pending.items()
                if key not in {"turnId", "createdAtMs"}
            }
            event_id = f"{session_id}:snapshot:ui:{request_id}"
            live_events.append(
                AgentEventEnvelope(
                    event_id=event_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    sequence=max(1, last_sequence),
                    created_at_ms=created_at_ms,
                    event_type="user_input_required",
                    payload=payload,
                    resume_token=event_id,
                ).to_payload()
            )

    def _reconcile_session_status(
        self,
        session_id: str,
        session: Mapping[str, object],
    ) -> dict[str, object]:
        persisted_status = str(session.get("status") or "idle")
        if persisted_status not in {"active", "busy"}:
            return dict(session)
        runtime_status = self.runtime.runtime_status()
        busy_session_ids = {
            str(value)
            for value in runtime_status.get("activeSessionIds") or []
            if str(value)
        }
        active_session_id = str(
            runtime_status.get("activeSessionId") or ""
        )
        if (
            runtime_status.get("status") == "busy"
            and active_session_id
        ):
            busy_session_ids.add(active_session_id)
        effective_status = (
            "busy"
            if session_id in busy_session_ids
            else "idle"
        )
        if effective_status == persisted_status:
            return dict(session)
        return self.sessions.set_status(
            session_id,
            effective_status,
        )


def _project_room_public_messages(
    *,
    session_id: str,
    private_messages: Sequence[Mapping[str, object]],
    projection: Mapping[str, object],
) -> list[dict[str, object]]:
    participant_id = str(projection.get("participantId") or "")
    projected: list[
        tuple[int, int, int, str, dict[str, object]]
    ] = []
    for index, message in enumerate(private_messages):
        if _is_managed_room_bootstrap(message):
            continue
        value = dict(message)
        projected.append(
            (
                _message_created_at_ms(value),
                1,
                index,
                str(value.get("id") or ""),
                value,
            )
        )

    raw_events = projection.get("events")
    events = (
        raw_events
        if isinstance(raw_events, Sequence)
        and not isinstance(raw_events, (str, bytes))
        else ()
    )
    seen_event_ids: set[str] = set()
    seen_post_ids: set[str] = set()
    ordered_events = sorted(
        (
            event
            for event in events
            if isinstance(event, Mapping)
        ),
        key=_room_event_order,
    )
    for event in ordered_events:
        event_type = str(event.get("eventType") or "")
        event_id = str(event.get("eventId") or "")
        payload = event.get("payload")
        if not event_id or not isinstance(payload, Mapping):
            continue
        created_at_ms = _message_created_at_ms(event)
        sequence = _integer(
            event.get("sequence"),
            default=0,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        turn_id = str(event.get("turnId") or "")
        if event_type == "user_message":
            if event_id in seen_event_ids:
                continue
            text = str(payload.get("text") or "").strip()
            if not text:
                continue
            seen_event_ids.add(event_id)
            message = _room_text_message(
                session_id=session_id,
                message_id=f"room-event:{event_id}",
                turn_id=turn_id,
                role="user",
                text=text,
                created_at_ms=created_at_ms,
                source_kind="room_event",
                source_ref=event_id,
            )
            projected.append(
                (
                    created_at_ms,
                    0,
                    sequence,
                    event_id,
                    message,
                )
            )
            continue
        if (
            event_type != "room_post"
            or str(event.get("participantId") or "") != participant_id
        ):
            continue
        post = payload.get("post")
        if not isinstance(post, Mapping):
            continue
        post_id = str(post.get("postId") or "")
        text = str(post.get("content") or "").strip()
        if not post_id or not text or post_id in seen_post_ids:
            continue
        seen_post_ids.add(post_id)
        message = _room_text_message(
            session_id=session_id,
            message_id=f"room-post:{post_id}",
            turn_id=turn_id,
            role="assistant",
            text=text,
            created_at_ms=created_at_ms,
            source_kind="room_post",
            source_ref=post_id,
        )
        projected.append(
            (
                created_at_ms,
                2,
                sequence,
                post_id,
                message,
            )
        )
    projected.sort(key=lambda item: item[:4])
    return [item[4] for item in projected]


def _room_event_order(
    event: Mapping[str, object],
) -> tuple[int, int, str]:
    return (
        _integer(
            event.get("sequence"),
            default=0,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        ),
        _message_created_at_ms(event),
        str(event.get("eventId") or ""),
    )


def _message_created_at_ms(value: Mapping[str, object]) -> int:
    return _integer(
        value.get("createdAtMs"),
        default=0,
        minimum=0,
        maximum=9_223_372_036_854_775_807,
    )


def _is_managed_room_bootstrap(
    message: Mapping[str, object],
) -> bool:
    if str(message.get("role") or "") != "user":
        return False
    blocks = message.get("blocks")
    if not isinstance(blocks, Sequence) or isinstance(
        blocks,
        (str, bytes),
    ):
        return False
    text_parts: list[str] = []
    for block in blocks:
        if (
            not isinstance(block, Mapping)
            or str(block.get("type") or "") != "text"
        ):
            continue
        data = block.get("data")
        if not isinstance(data, Mapping):
            continue
        text_parts.append(str(data.get("text") or ""))
    text = "\n".join(text_parts).strip()
    return (
        text.startswith(_ROOM_CONTEXT_OPEN)
        and text.endswith(_ROOM_CONTEXT_CLOSE)
    ) or (
        text.startswith(_TRANSIENT_CONTEXT_PREFIX)
        and _ROOM_CONTEXT_OPEN in text
        and _ROOM_CONTEXT_CLOSE in text
    )


def _room_text_message(
    *,
    session_id: str,
    message_id: str,
    turn_id: str,
    role: str,
    text: str,
    created_at_ms: int,
    source_kind: str,
    source_ref: str,
) -> dict[str, object]:
    message: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-message.v1",
        "id": message_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "role": role,
        "status": "completed",
        "blocks": [
            {
                "id": f"{message_id}:text",
                "type": "text",
                "status": "completed",
                "presentationKind": "markdown",
                "data": {"text": text},
                "source": {
                    "kind": source_kind,
                    "ref": source_ref,
                },
                "visibility": "room_post",
            }
        ],
        "attachments": [],
        "citations": [],
        "createdAtMs": created_at_ms,
        "completedAtMs": created_at_ms,
    }
    validate_contract(message, "agent-message.v1.json")
    return message


def _mapping_field(
    value: object,
    key: str,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    field = value.get(key)
    return dict(field) if isinstance(field, Mapping) else None


def _merge_tool_events(
    tool_history_events: Sequence[object],
    replay_events: Sequence[object],
) -> list[dict[str, object]]:
    history = [
        dict(item)
        for item in tool_history_events
        if isinstance(item, Mapping)
    ]
    replay = [
        dict(item)
        for item in replay_events
        if isinstance(item, Mapping)
    ]
    history_types = _tool_event_types(history)
    replay_types = _tool_event_types(replay)
    stale_replay_ids = {
        tool_call_id
        for tool_call_id, event_types in history_types.items()
        if "tool_finished" in event_types
        and "tool_finished"
        not in replay_types.get(tool_call_id, set())
    }
    replay_reasoning_ids = {
        identity
        for event in replay
        for identity in [_reasoning_event_identity(event)]
        if identity
    }
    merged: list[dict[str, object]] = []
    for event in history:
        reasoning_id = _reasoning_event_identity(event)
        if reasoning_id and reasoning_id in replay_reasoning_ids:
            continue
        tool_call_id, event_type = _tool_event_identity(event)
        if (
            tool_call_id
            and tool_call_id not in stale_replay_ids
            and event_type
            in replay_types.get(tool_call_id, set())
        ):
            continue
        merged.append(event)
    for event in replay:
        tool_call_id, _event_type = _tool_event_identity(event)
        if tool_call_id and tool_call_id in stale_replay_ids:
            continue
        merged.append(event)
    return merged


def _live_event_page(
    events: Sequence[Mapping[str, object]],
    *,
    limit: int,
    before_event_id: str = "",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return one stable, newest-first navigation window over live history.

    The public event order remains unchanged.  A caller asks for the events
    immediately before the first event it already owns, so new tail events do
    not move the older-page boundary while the conversation is still active.
    Unknown cursors fail closed to the newest page rather than returning an
    arbitrary or empty history window.
    """

    normalized = [dict(event) for event in events]
    bounded_limit = max(1, min(int(limit), 500))
    end = len(normalized)
    cursor = str(before_event_id or "").strip()
    if cursor:
        for index, event in enumerate(normalized):
            if str(event.get("eventId") or "") == cursor:
                end = index
                break
    start = max(0, end - bounded_limit)
    items = normalized[start:end]
    first_event_id = str(items[0].get("eventId") or "") if items else ""
    return items, {
        "eventLimit": bounded_limit,
        "eventStart": start,
        "eventEnd": end,
        "totalLiveEvents": len(normalized),
        "hasOlderLiveEvents": start > 0,
        "olderBeforeEventId": first_event_id if start > 0 else "",
    }


def _message_turn_page(
    messages: Sequence[Mapping[str, object]],
    *,
    limit: int,
    before_message_id: str = "",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return complete conversation turns immediately before a stable message."""

    normalized = [dict(message) for message in messages]
    bounded_limit = max(1, min(int(limit), 200))
    end = len(normalized)
    cursor = str(before_message_id or "").strip()
    if cursor:
        for index, message in enumerate(normalized):
            if str(message.get("id") or "") == cursor:
                end = index
                break
    start = end
    seen_turns: set[str] = set()
    while start > 0:
        message = normalized[start - 1]
        identity = str(message.get("turnId") or message.get("id") or start - 1)
        if identity not in seen_turns and len(seen_turns) >= bounded_limit:
            break
        seen_turns.add(identity)
        start -= 1
    items = normalized[start:end]
    first_message_id = str(items[0].get("id") or "") if items else ""
    return items, {
        "turnLimit": bounded_limit,
        "messageStart": start,
        "messageEnd": end,
        "totalMessages": len(normalized),
        "hasOlderMessages": start > 0,
        "olderBeforeMessageId": first_message_id if start > 0 else "",
    }


def _apply_observed_times(
    tool_history_events: Sequence[object],
    observations: Sequence[object],
) -> list[dict[str, object]]:
    observed_times: dict[tuple[str, str], list[int]] = {}
    for value in observations:
        observation = (
            value if isinstance(value, Mapping) else {}
        )
        event_type = str(
            observation.get("phase")
            or observation.get("name")
            or ""
        )
        if event_type not in {
            "tool_started",
            "tool_progress",
            "tool_finished",
        }:
            continue
        tool_call_id = _observation_tool_call_id(observation)
        created_at_ms = _integer(
            observation.get("createdAtMs"),
            default=0,
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        if not tool_call_id or created_at_ms <= 0:
            continue
        observed_times.setdefault(
            (tool_call_id, event_type),
            [],
        ).append(created_at_ms)
    queues = {
        key: deque(sorted(values))
        for key, values in observed_times.items()
    }
    corrected: list[dict[str, object]] = []
    for value in tool_history_events:
        event = dict(value) if isinstance(value, Mapping) else {}
        tool_call_id, event_type = _tool_event_identity(event)
        timestamps = queues.get((tool_call_id, event_type))
        if timestamps:
            event["createdAtMs"] = timestamps.popleft()
        corrected.append(event)
    return corrected


def _observation_tool_call_id(
    observation: Mapping[str, object],
) -> str:
    refs = observation.get("refs")
    if not isinstance(refs, list):
        return ""
    for value in refs:
        ref = value if isinstance(value, Mapping) else {}
        if ref.get("kind") == "tool_call":
            return str(ref.get("id") or "")
    return ""


def _tool_event_types(
    events: Sequence[Mapping[str, object]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for event in events:
        tool_call_id, event_type = _tool_event_identity(event)
        if tool_call_id and event_type:
            result.setdefault(tool_call_id, set()).add(event_type)
    return result


def _reasoning_event_identity(event: Mapping[str, object]) -> str:
    if str(event.get("eventType") or "") != "reasoning_summary":
        return ""
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("requestId") or "")


def _tool_event_identity(
    event: Mapping[str, object],
) -> tuple[str, str]:
    event_type = str(event.get("eventType") or "")
    if event_type not in {
        "tool_started",
        "tool_progress",
        "tool_finished",
    }:
        return "", ""
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return "", ""
    return str(payload.get("toolCallId") or ""), event_type


def _integer(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
