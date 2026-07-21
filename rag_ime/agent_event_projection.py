from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .agent_blocks import bind_block_scope
from .agent_prompt_support import bounded_text
from .agent_protocol import AgentEventEnvelope
from .agent_room_public_timeline import RoomPublicTimelineProjector


class AgentEventProjectionService:
    """Persist private Agent events and project bounded Room events."""

    def __init__(
        self,
        *,
        sessions: Any,
        room_kernel: Any,
        rooms: Any,
        agent_blocks: Any,
        observations: Any,
        room_kernel_projection: Any,
        room_events: Any,
        public_timeline: RoomPublicTimelineProjector,
        room_turns: Any,
        append_recent_message: Callable[
            [str, Mapping[str, object]],
            None,
        ],
        record_assistant_evidence: Callable[
            [AgentEventEnvelope],
            Mapping[str, object],
        ],
        notify_intercom: Callable[[], None],
    ) -> None:
        self.sessions = sessions
        self.room_kernel = room_kernel
        self.rooms = rooms
        self.agent_blocks = agent_blocks
        self.observations = observations
        self.room_kernel_projection = room_kernel_projection
        self.room_events = room_events
        self.public_timeline = public_timeline
        self.room_turns = room_turns
        self.append_recent_message = append_recent_message
        self.record_assistant_evidence = (
            record_assistant_evidence
        )
        self.notify_intercom = notify_intercom

    def record(self, event: AgentEventEnvelope) -> None:
        self.sessions.record_runtime_event(
            event_id=event.event_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            sequence=event.sequence,
            event_type=event.event_type,
            created_at_ms=event.created_at_ms,
            redacted_summary=_event_summary(event),
            metrics=runtime_event_metrics(event),
        )
        if event.event_type != "message_completed":
            return
        message = event.payload.get("message")
        if isinstance(message, Mapping):
            self._bind_and_persist_blocks(event, message)
        self.record_assistant_evidence(event)

    def mirror_to_room(
        self,
        event: AgentEventEnvelope,
    ) -> None:
        if event.event_type in {
            "turn_completed",
            "turn_failed",
        }:
            self.notify_intercom()
        participant = self.rooms.participant_for_session(
            event.session_id
        )
        self.observations.enqueue_agent_event(
            event,
            room_id=(
                str(participant.get("roomId") or "")
                if participant is not None
                else ""
            ),
        )
        if participant is None:
            return
        binding = self.room_kernel.session_binding(
            event.session_id
        )
        if (
            self.room_kernel.mode in {
                "cohort",
                "kernel_only",
            }
            and binding is not None
        ):
            mapped_type, public_data = room_event_projection(event)
            if event.event_type == "message_completed":
                mapped_type = "participant_activity"
                public_data = {
                    "status": "draft_ready",
                    "summary": "正在整理正式 Post",
                }
            room_id = str(binding["roomId"])
            room = self.rooms.get(room_id)
            self.public_timeline.publish_runtime(
                event=event,
                binding=binding,
                participant=participant,
                event_type=mapped_type,
                public_data=public_data,
                topic_id=str(room.get("activeTopicId") or ""),
            )
            self.room_kernel_projection.sync_room(
                room_id,
                now_ms=event.created_at_ms,
            )
            return
        room_turn_id = self.room_turns.turn_for_event(
            event
        )
        if self.room_turns.is_cancelled(
            event.session_id,
            room_turn_id,
        ):
            return
        mapped_type, public_data = room_event_projection(
            event
        )
        dispatch_id = self.room_turns.dispatch_for_event(
            event
        )
        self.room_events.publish(
            room_id=str(participant["roomId"]),
            event_type=mapped_type,
            payload={
                "sourceEventId": event.event_id,
                "sourceEventType": event.event_type,
                "data": {
                    **public_data,
                    "rootId": room_turn_id,
                    **(
                        {"dispatchId": dispatch_id}
                        if dispatch_id
                        else {}
                    ),
                },
            },
            turn_id=room_turn_id,
            participant_id=str(participant["id"]),
            source_session_id=event.session_id,
            topic_id=self.room_turns.topic_for_turn(
                room_turn_id
            ),
            created_at_ms=event.created_at_ms,
        )
        if event.event_type in {
            "turn_completed",
            "turn_failed",
        }:
            self.room_turns.finish(
                event.session_id,
                event.turn_id,
                room_turn_id,
            )

    def _bind_and_persist_blocks(
        self,
        event: AgentEventEnvelope,
        message: Mapping[str, object],
    ) -> None:
        binding = self.room_kernel.session_binding(
            event.session_id
        )
        participant = self.rooms.participant_for_session(
            event.session_id,
            active_only=False,
        )
        kernel_room = (
            participant is not None
            and bool(
                self.room_kernel.root_ids(
                    str(participant.get("roomId") or "")
                )
            )
        )
        write_allowed = not kernel_room or (
            binding is not None
            and binding.get("state") == "running"
        )
        generation = (
            int(binding.get("generation") or 0)
            if binding
            else 0
        )
        bound_message = dict(message)
        bound_message["blocks"] = bind_block_scope(
            [
                block
                for block in message.get("blocks", [])
                if isinstance(block, Mapping)
            ],
            session_id=event.session_id,
            message_id=str(
                message.get("id") or event.event_id
            ),
            generation=generation,
        )
        event.payload["message"] = bound_message
        self.append_recent_message(
            event.session_id,
            bound_message,
        )
        if write_allowed and any(
            isinstance(block, Mapping)
            and block.get("schemaVersion")
            == "rag-ime.agent-block.v1"
            for block in bound_message.get("blocks", [])
        ):
            self.agent_blocks.persist_message(
                bound_message,
                root_id=(
                    str(binding.get("rootId") or "")
                    if binding
                    else ""
                ),
                task_id=(
                    str(binding.get("taskId") or "")
                    if binding
                    else ""
                ),
                invocation_id=(
                    str(binding.get("dispatchId") or "")
                    if binding
                    else ""
                ),
                generation=generation,
                created_at_ms=event.created_at_ms,
            )


def room_event_projection(
    event: AgentEventEnvelope,
) -> tuple[str, dict[str, object]]:
    payload = event.payload
    if event.event_type == "text_delta":
        return (
            "participant_delta",
            {
                "messageId": bounded_text(
                    payload.get("messageId"),
                    maximum=200,
                ),
                "blockId": bounded_text(
                    payload.get("blockId"),
                    maximum=240,
                ),
                "contentIndex": _signed_integer(
                    payload.get("contentIndex"),
                    default=0,
                ),
                "delta": str(
                    payload.get("delta") or ""
                )[:32_000],
            },
        )
    if event.event_type == "message_completed":
        message = _public_room_message(
            payload.get("message")
        )
        if message is not None:
            return "participant_message", {
                "message": message
            }
        return "participant_activity", {
            "status": "message_hidden",
            "summary": "已完成一项内部工具步骤",
        }
    if event.event_type == "turn_completed":
        return "turn_completed", _room_scalar_projection(
            payload,
            ("status", "summary"),
        )
    if event.event_type == "turn_failed":
        return "turn_failed", {
            "error": bounded_text(
                payload.get("error"),
                maximum=240,
            )
        }
    data = _room_scalar_projection(
        payload,
        (
            "status",
            "summary",
            "message",
            "label",
            "toolName",
            "displayName",
            "toolCallId",
            "callId",
            "approvalId",
            "requestId",
            "requestKind",
            "runId",
            "state",
            "riskLevel",
            "trigger",
            "sourceRole",
        ),
    )
    for flag in ("ok", "isError", "due"):
        if isinstance(payload.get(flag), bool):
            data[flag] = bool(payload[flag])
    if event.event_type in {
        "tool_started",
        "tool_progress",
        "tool_finished",
    }:
        summary, references = _room_tool_summary(payload)
        if summary:
            data["summary"] = summary
        data.update(references)
    return "participant_activity", data


def runtime_event_metrics(
    event: AgentEventEnvelope,
) -> dict[str, object]:
    payload = event.payload
    message = payload.get("message")
    message = message if isinstance(message, Mapping) else {}
    usage = message.get("usage")
    if not isinstance(usage, Mapping):
        usage = payload.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}

    def metric(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return max(0, int(value))
        return 0

    metrics: dict[str, object] = {}
    normalized_usage = {
        "inputTokens": metric("inputTokens", "input"),
        "outputTokens": metric("outputTokens", "output"),
        "cacheReadTokens": metric(
            "cacheReadTokens",
            "cacheRead",
        ),
        "cacheWriteTokens": metric(
            "cacheWriteTokens",
            "cacheWrite",
        ),
        "totalTokens": metric("totalTokens", "total"),
    }
    if not normalized_usage["totalTokens"]:
        normalized_usage["totalTokens"] = (
            normalized_usage["inputTokens"]
            + normalized_usage["outputTokens"]
        )
    if any(normalized_usage.values()):
        metrics["usage"] = normalized_usage
    if event.event_type == "tool_started":
        metrics["toolCalls"] = 1
    duration = payload.get("durationMs")
    if (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
    ):
        metrics["durationMs"] = max(0, int(duration))
    return metrics


def _event_summary(event: AgentEventEnvelope) -> str:
    return str(
        event.payload.get("status")
        or event.payload.get("error")
        or event.payload.get("toolName")
        or event.payload.get("label")
        or ""
    )


def _public_room_message(
    value: object,
) -> dict[str, object] | None:
    if (
        not isinstance(value, Mapping)
        or str(value.get("role") or "") != "assistant"
    ):
        return None
    raw_blocks = value.get("blocks")
    if not isinstance(raw_blocks, list):
        return None
    allowed = {
        "text",
        "code",
        "reasoning_summary",
        "progress",
        "citation",
        "image",
        "audio",
        "file",
        "sticker",
        "task_plan",
        "diff",
        "approval",
        "error",
        "card",
        "checklist",
        "table",
        "artifact",
        "reference",
        "status",
    }
    blocks = [
        dict(item)
        for item in raw_blocks
        if isinstance(item, Mapping)
        and item.get("type") in allowed
        and (
            item.get("schemaVersion")
            != "rag-ime.agent-block.v1"
            or str(item.get("visibility") or "")
            in {"room_post", "root_post"}
        )
    ]
    if not blocks:
        return None
    public = dict(value)
    public["blocks"] = blocks
    public["attachments"] = [
        str(item)[:240]
        for item in value.get("attachments", [])
        if isinstance(item, str)
    ][:16]
    public["citations"] = [
        str(item)[:240]
        for item in value.get("citations", [])
        if isinstance(item, str)
    ][:32]
    return public


def _room_scalar_projection(
    payload: Mapping[str, object],
    keys: tuple[str, ...],
) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        projected[key] = bounded_text(value, maximum=500)
    return projected


def _room_tool_summary(
    payload: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    raw_result = (
        payload.get("result")
        or payload.get("partialResult")
    )
    result = (
        raw_result
        if isinstance(raw_result, Mapping)
        else {}
    )
    details = (
        result.get("details")
        if isinstance(result.get("details"), Mapping)
        else {}
    )
    domain = (
        details.get("result")
        if isinstance(details.get("result"), Mapping)
        else {}
    )
    summary = bounded_text(
        domain.get("summary")
        or details.get("summary")
        or result.get("summary"),
        maximum=500,
    )
    references: dict[str, list[str]] = {
        "books": [],
        "groups": [],
        "tags": [],
        "recent": [],
    }
    items = (
        domain.get("items")
        if isinstance(domain.get("items"), list)
        else []
    )
    key_for_kind = {
        "book": "books",
        "group": "groups",
        "tag": "tags",
        "source": "recent",
    }
    for item in items[:24]:
        if not isinstance(item, Mapping):
            continue
        key = key_for_kind.get(
            str(item.get("kind") or "")
        )
        if not key:
            continue
        label = bounded_text(
            item.get("title")
            or item.get("label")
            or item.get("text"),
            maximum=80,
        )
        if label and label not in references[key]:
            references[key].append(label)
    return summary, {
        key: values[:6]
        for key, values in references.items()
        if values
    }


def _signed_integer(
    value: object,
    *,
    default: int,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
