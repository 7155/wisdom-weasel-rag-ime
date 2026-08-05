from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import re
from typing import Any

from .agent_blocks import bind_block_scope, validate_persisted_blocks
from .agent_prompt_support import bounded_text
from .agent_protocol import AgentBlock, AgentEventEnvelope
from .agent_room_kernel import kernel_owns_room_execution
from .agent_room_public_timeline import RoomPublicTimelineProjector
from .pi_runtime_public import (
    GROUPED_QUESTIONS_SCHEMA_VERSION,
    grouped_questions_from_wire,
    managed_media_content_url,
    public_code_tool_activity,
    public_file_name,
    public_tool_output_text,
    redact_mapping,
)
from .contracts.json_schema import validate_contract


_TRANSIENT_RUNTIME_EVENT_TYPES = frozenset(
    {
        "text_delta",
        "tool_progress",
    }
)

_ROOM_WORK_SUMMARY_VERSION = "room-work-summary.v1"
_ROOM_WORK_SUMMARY_BY_INTENT = {
    "align": ("alignment", "需求与交付边界梳理有新进展"),
    "review": ("review", "结果与验收条件复核有新进展"),
    "close": ("closure", "本轮结果整理有新进展"),
}
_ROOM_IMPLEMENTATION_INTENTS = frozenset(
    {
        "execute",
        "revise",
        "retry",
        "resume",
        "wake",
        "callback",
    }
)
_ROOM_PUBLIC_ACTIVITY_STATES = frozenset(
    {"queued", "running", "completed", "failed", "aborted"}
)


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
        record_runtime_failure: Callable[..., Mapping[str, object]]
        | None = None,
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
        self.record_runtime_failure = record_runtime_failure

    def record(self, event: AgentEventEnvelope) -> None:
        # Token and progress deltas already live in the bounded in-memory SSE
        # replay. Persisting each fragment makes the single Host event thread
        # wait on hundreds of SQLite transactions before agent_settled.
        if event.event_type not in _TRANSIENT_RUNTIME_EVENT_TYPES:
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
        if (
            isinstance(message, Mapping)
            and self._bind_and_persist_blocks(event, message)
        ):
            self.record_assistant_evidence(event)

    def mirror_to_room(
        self,
        event: AgentEventEnvelope,
    ) -> None:
        private_intercom_id = (
            self.room_turns.private_intercom_for_event(event)
        )
        if private_intercom_id:
            # The private Session transcript remains authoritative via
            # record(). A notification-only A2A turn must not wake another
            # Intercom delivery or create any public Room projection.
            if event.event_type in {
                "turn_completed",
                "turn_failed",
            }:
                self.room_turns.finish_private_intercom_event(
                    event
                )
            return
        if event.event_type in {
            "turn_completed",
            "turn_failed",
        }:
            self.notify_intercom()
        participant = self.rooms.participant_for_session(
            event.session_id
        )
        if event.event_type not in _TRANSIENT_RUNTIME_EVENT_TYPES:
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
        if event.event_type == "response_evidence":
            provenance_binding = getattr(
                self.room_kernel,
                "response_provenance_binding",
                None,
            )
            binding = (
                provenance_binding(
                    event.session_id,
                    event.turn_id,
                    str(event.payload.get("toolCallId") or ""),
                )
                if callable(provenance_binding)
                else None
            )
        else:
            binding = self.room_kernel.session_binding(
                event.session_id
            )
        registered_turn_for_event = getattr(
            self.room_turns,
            "registered_turn_for_event",
            None,
        )
        conversation_turn_id = (
            registered_turn_for_event(event)
            if callable(registered_turn_for_event)
            else ""
        )
        if kernel_owns_room_execution(self.room_kernel.mode) and binding is not None:
            runtime_turn_id = str(
                binding.get("runtimeTurnId") or ""
            )
            if not runtime_turn_id or event.turn_id != runtime_turn_id:
                return
            mapped_type, public_data = room_event_projection(
                event,
                room_intent_kind=str(binding.get("intentKind") or ""),
            )
            if event.event_type in {
                "message_completed",
                "response_evidence",
            }:
                mapped_type = "participant_activity"
                dispatch_id = str(binding["dispatchId"])
                if (
                    event.event_type == "message_completed"
                    and _completed_message_failed(event)
                ):
                    # Provider diagnostics stay private. The public Room only
                    # needs one coalesced lifecycle signal until turn_failed
                    # publishes the authoritative terminal state.
                    public_data = {
                        "status": "provider_error",
                        "summary": "模型响应中断，正在按运行策略处理",
                        "requestId": f"{dispatch_id}:provider",
                        "isError": True,
                    }
                elif event.event_type == "message_completed":
                    public_data = {
                        "status": "draft_ready",
                        "summary": "正在整理正式 Post",
                        "requestId": f"{dispatch_id}:provider",
                    }
                else:
                    public_data = {
                        "status": "recorded",
                        "summary": "本轮运行记录已更新",
                        "requestId": f"{dispatch_id}:provider",
                    }
                message = event.payload.get("message")
                usage = _public_token_usage(
                    (
                        message.get("usage")
                        if isinstance(message, Mapping)
                        else event.payload.get("usage")
                    )
                )
                response_post = self.room_kernel.post_for_dispatch(
                    dispatch_id
                )
                public_data["runtimeTurnId"] = event.turn_id
                usage_reported = (
                    event.payload.get("usageReported") is True
                )
                cache_usage_reported = (
                    event.payload.get("cacheUsageReported") is True
                )
                public_data["usageReported"] = usage_reported
                public_data["cacheUsageReported"] = (
                    cache_usage_reported
                    if usage_reported
                    else False
                )
                evidence_source = (
                    message
                    if isinstance(message, Mapping)
                    else event.payload
                )
                provider = bounded_text(
                    evidence_source.get("provider"),
                    maximum=80,
                )
                model = bounded_text(
                    evidence_source.get("model"),
                    maximum=160,
                )
                if provider:
                    public_data["provider"] = provider
                if model:
                    public_data["model"] = model
                if usage_reported and usage is not None:
                    public_data["usage"] = usage
                if response_post is not None:
                    public_data["responsePostId"] = str(
                        response_post.get("postId") or ""
                    )
            elif event.event_type == "turn_failed":
                dispatch_id = str(binding["dispatchId"])
                public_data = _public_turn_failure(
                    event,
                    dispatch_id=dispatch_id,
                )
            room_id = str(binding["roomId"])
            room = self.rooms.get(room_id)
            runtime_failure_receipt: Mapping[str, object] | None = None
            missing_commit = (
                event.event_type == "turn_completed"
                and str(binding.get("state") or "") == "running"
            )
            if (
                (
                    event.event_type == "turn_failed"
                    or missing_commit
                )
                and self.record_runtime_failure is not None
            ):
                runtime_failure_receipt = self.record_runtime_failure(
                    room_id=room_id,
                    dispatch_id=str(binding["dispatchId"]),
                    generation=int(binding["generation"]),
                    source_event_id=event.event_id,
                    runtime_turn_id=event.turn_id,
                    dispatch_attempt=int(binding["attempt"]),
                    created_at_ms=event.created_at_ms,
                    retryable=(
                        True
                        if missing_commit
                        else event.payload.get("retryable") is True
                    ),
                    had_tool_activity=(
                        event.payload.get("hadToolActivity") is not False
                    ),
                    reason_code=(
                        "room_commit_missing"
                        if missing_commit
                        else str(event.payload.get("reasonCode") or "")
                    ),
                )
                if (
                    runtime_failure_receipt.get("receiptKind")
                    == "runtime_retry_scheduled"
                ):
                    mapped_type = "participant_activity"
                    details = runtime_failure_receipt.get("details")
                    retry_at_ms = (
                        int(details.get("availableAtMs") or 0)
                        if isinstance(details, Mapping)
                        else 0
                    )
                    public_data = {
                        "status": "retry_wait",
                        "summary": (
                            "当前回合未形成权威提交，已进入有界恢复等待"
                            if missing_commit
                            else "模型连接中断，已进入有界重试等待"
                        ),
                        "requestId": (
                            f"{str(binding['dispatchId'])}:provider"
                        ),
                        "retryAttempt": (
                            int(details.get("attempt") or 0)
                            if isinstance(details, Mapping)
                            else 0
                        ),
                        **(
                            {
                                "retryAtMs": retry_at_ms,
                                "retryDelayMs": max(
                                    0,
                                    retry_at_ms - event.created_at_ms,
                                ),
                            }
                            if retry_at_ms
                            else {}
                        ),
                    }
                elif missing_commit:
                    mapped_type = "participant_activity"
                    public_data = {
                        "status": "blocked",
                        "summary": "当前回合未形成权威提交，任务已安全阻塞",
                        "requestId": (
                            f"{str(binding['dispatchId'])}:provider"
                        ),
                        "isError": True,
                    }
            self.public_timeline.publish_runtime(
                event=event,
                binding=binding,
                participant=participant,
                event_type=mapped_type,
                public_data=public_data,
                topic_id=str(room.get("activeTopicId") or ""),
                allow_after_terminal=(
                    event.event_type in {
                        "message_completed",
                        "response_evidence",
                    }
                    and str(binding.get("state") or "") == "committed"
                ),
            )
            if event.event_type not in _TRANSIENT_RUNTIME_EVENT_TYPES:
                self.room_kernel_projection.sync_room(
                    room_id,
                    now_ms=event.created_at_ms,
                )
            return
        if (
            kernel_owns_room_execution(self.room_kernel.mode)
            and not conversation_turn_id
        ):
            # A committed/revoked managed Dispatch may still emit trailing
            # private deltas. Only an explicitly registered conversation is
            # allowed to use the Session-backed public mapper.
            return
        room_turn_id = (
            conversation_turn_id
            or self.room_turns.turn_for_event(event)
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
    ) -> bool:
        binding = self.room_kernel.session_binding(
            event.session_id
        )
        managed_turn_lookup = getattr(
            self.room_kernel,
            "is_managed_runtime_turn",
            None,
        )
        managed_turn = (
            bool(
                managed_turn_lookup(
                    event.session_id,
                    event.turn_id,
                )
            )
            if callable(managed_turn_lookup)
            else (
                binding is not None
                and binding.get("runtimeTurnId") == event.turn_id
            )
        )
        active_exact_turn = (
            binding is not None
            and binding.get("state") == "running"
            and binding.get("runtimeTurnId") == event.turn_id
        )
        write_allowed = not managed_turn or active_exact_turn
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
        if write_allowed:
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
        return write_allowed


def room_event_projection(
    event: AgentEventEnvelope,
    *,
    room_intent_kind: str = "",
) -> tuple[str, dict[str, object]]:
    payload = event.payload
    if event.event_type == "text_delta":
        data: dict[str, object] = {
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
        }
        for flag in ("replaceBlock", "replaceContent"):
            if isinstance(payload.get(flag), bool):
                data[flag] = bool(payload[flag])
        return "participant_delta", data
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
        return "turn_failed", _public_turn_failure(event)
    if event.event_type == "reasoning_summary":
        # Provider reasoning summaries remain useful inside the participant's
        # private Session.  A Room, however, is an accountable public surface:
        # it may show that a bound work stage advanced, but it must not publish
        # Provider-authored headings, protocol vocabulary, or a list of
        # reasoning steps.  Derive this copy only from the authoritative
        # Dispatch intent so it cannot invent files, findings, or completion.
        summary_kind, summary = _public_room_work_summary(
            room_intent_kind
        )
        data: dict[str, object] = {}
        for field in ("status", "state"):
            value = str(payload.get(field) or "").strip()
            if value in _ROOM_PUBLIC_ACTIVITY_STATES:
                data[field] = value
        if payload.get("source") == "provider_reasoning_summary":
            # This machine provenance is intentionally retained for existing
            # clients; it is not user-facing copy and carries no Provider text.
            data["source"] = "provider_reasoning_summary"
        data.update(
            {
                "summary": summary,
                "publicSummaryVersion": _ROOM_WORK_SUMMARY_VERSION,
                "publicSummaryKind": summary_kind,
            }
        )
        return "participant_activity", data
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
            "retryOfToolCallId",
            "callId",
            "approvalId",
            "requestId",
            "requestKind",
            "runId",
            "state",
            "riskLevel",
            "trigger",
            "sourceRole",
            "toolId",
            "operation",
            "decisionMode",
        ),
    )
    for flag in ("ok", "isError", "due"):
        if isinstance(payload.get(flag), bool):
            data[flag] = bool(payload[flag])
    if event.event_type in {"approval_required", "approval_resolved"}:
        if isinstance(payload.get("automatic"), bool):
            data["automatic"] = bool(payload["automatic"])
        model_decision = payload.get("approvalModelDecision")
        if isinstance(model_decision, Mapping):
            public_decision = dict(model_decision)
            try:
                validate_contract(
                    public_decision,
                    "agent-approval-model-decision.v1.json",
                )
            except ValueError:
                pass
            else:
                data["approvalModelDecision"] = public_decision
    if event.event_type == "user_input_required":
        data.update(_room_user_input_disclosure(payload))
    if event.event_type in {
        "tool_started",
        "tool_progress",
        "tool_finished",
    }:
        summary, references = _room_tool_summary(payload)
        if summary:
            data["summary"] = summary
        data.update(references)
        data.update(
            _room_tool_disclosure(
                payload,
                event.event_type,
                session_id=event.session_id,
            )
        )
    return "participant_activity", data


def _public_room_work_summary(intent_kind: str) -> tuple[str, str]:
    normalized = str(intent_kind or "").strip().lower()
    selected = _ROOM_WORK_SUMMARY_BY_INTENT.get(normalized)
    if selected is not None:
        return selected
    if normalized in _ROOM_IMPLEMENTATION_INTENTS:
        return "implementation", "当前任务推进有新进展"
    return "general", "当前工作有新进展"


def _public_turn_failure(
    event: AgentEventEnvelope,
    *,
    dispatch_id: str = "",
) -> dict[str, object]:
    runtime_host_exit = (
        str(event.payload.get("failureKind") or "")
        == "runtime_host_exit"
    )
    kind = "runtime" if runtime_host_exit else "provider"
    return {
        "status": (
            "runtime_error"
            if runtime_host_exit
            else (
                "provider_error"
                if dispatch_id
                else "failed"
            )
        ),
        "summary": (
            "Agent 运行时中断，任务已暂停等待恢复"
            if runtime_host_exit
            else "模型响应失败，任务已暂停等待恢复"
        ),
        **(
            {"requestId": f"{dispatch_id}:{kind}"}
            if dispatch_id
            else {}
        ),
        "isError": True,
    }


def _completed_message_failed(
    event: AgentEventEnvelope,
) -> bool:
    message = event.payload.get("message")
    if not isinstance(message, Mapping):
        return False
    if str(message.get("status") or "").lower() == "failed":
        return True
    blocks = message.get("blocks")
    return isinstance(blocks, list) and any(
        isinstance(block, Mapping)
        and (
            str(block.get("status") or "").lower() == "failed"
            or str(block.get("type") or "").lower() == "error"
        )
        for block in blocks
    )


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
    if (
        event.event_type == "message_completed"
        and str(message.get("role") or "") == "user"
    ):
        client_message_id = str(
            payload.get("clientMessageId")
            or message.get("clientMessageId")
            or ""
        ).strip()[:200]
        if client_message_id:
            acceptance: dict[str, object] = {
                "clientMessageId": client_message_id,
                "messageId": str(
                    message.get("id") or ""
                ).strip()[:200],
                "turnId": str(event.turn_id).strip()[:200],
            }
            retry_of_client_message_id = str(
                payload.get("retryOfClientMessageId")
                or message.get("retryOfClientMessageId")
                or ""
            ).strip()[:200]
            if retry_of_client_message_id:
                acceptance["retryOfClientMessageId"] = (
                    retry_of_client_message_id
                )
            # This is deliberately content-free acceptance evidence. A
            # process can die after Pi accepted a prompt but before the
            # command receipt becomes terminal; these IDs let the next
            # process reconcile that receipt without executing it again.
            metrics["promptAcceptance"] = acceptance
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


def _public_token_usage(
    value: object,
) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    keys = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
    if not any(
        isinstance(value.get(key), (int, float))
        and not isinstance(value.get(key), bool)
        for key in keys
    ):
        return None
    return {
        key: max(0, _signed_integer(value.get(key), default=0))
        for key in keys
    }


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


_ROOM_TOOL_REQUEST_KEYS = (
    "fileName",
    "path",
    "root",
    "cwd",
    "op",
    "operation",
    "mode",
    "patternKind",
    "server",
    "label",
    "jobId",
    "status",
    "reason",
    "query",
    "pattern",
    "glob",
    "title",
    "newName",
    "offset",
    "limit",
    "context",
    "timeout",
    "line",
    "column",
    "timeoutMs",
    "timeoutSeconds",
    "cursor",
    "limitBytes",
    "command",
)

_ROOM_TOOL_RESULT_KEYS = (
    "outputPreview",
    "outputTruncated",
    "stdoutPreview",
    "stdoutTruncated",
    "stderrPreview",
    "stderrTruncated",
    "exitCode",
    "summary",
    "status",
    "message",
    "startLine",
    "endLine",
    "lineCount",
    "matchCount",
    "filesScanned",
    "additions",
    "deletions",
    "changedFiles",
    "decisionMode",
    "approvalModelDecision",
    "automatic",
)

_ROOM_TOOL_FILE_MIME_TYPES = frozenset(
    {
        "text/html",
        "text/markdown",
        "text/plain",
        "text/x-diff",
        "text/x-patch",
    }
)
_ROOM_TOOL_ARTIFACT_MAX_BYTES = 2 * 1024 * 1024


def _room_tool_agent_blocks_projection(
    value: object,
    *,
    session_id: str,
) -> list[dict[str, object]]:
    """Project only verified file/Diff descriptors from tool-owned blocks.

    Tool events carry blocks captured by ``AgentToolBlockBuffer`` after a
    successful tool result.  Revalidating their digest/source boundary here
    prevents an arbitrary event payload from turning into a Room file link.
    The Room copy deliberately omits provenance, refs and every unrecognized
    data field; managed file URLs are rebuilt from the verified identifiers.
    """

    try:
        trusted = validate_persisted_blocks(
            value,
            allowed_visibility=frozenset({"private_session"}),
        )
    except (TypeError, ValueError):
        return []

    projected: list[dict[str, object]] = []
    for raw in trusted[:8]:
        try:
            block = AgentBlock.from_payload(raw)
        except (TypeError, ValueError):
            continue
        source_ref = str(block.source.get("ref") or "").strip()
        if (
            block.status != "completed"
            or block.block_type not in {"file", "diff"}
            or str(block.source.get("kind") or "") != "pi_tool_result"
            or not source_ref.startswith(f"{session_id}:")
        ):
            continue
        if block.block_type == "file":
            data = block.data
            media_session_id = str(data.get("sessionId") or "").strip()
            file_name = public_file_name(str(data.get("fileName") or ""))
            mime_type = str(data.get("mimeType") or "").strip().lower()
            byte_size = data.get("byteSize")
            sha256 = str(data.get("sha256") or "").strip().lower()
            media_id = str(data.get("mediaId") or "").strip()
            if (
                media_session_id != session_id
                or not file_name
                or mime_type not in _ROOM_TOOL_FILE_MIME_TYPES
                or not isinstance(byte_size, int)
                or isinstance(byte_size, bool)
                or byte_size < 0
                or byte_size > _ROOM_TOOL_ARTIFACT_MAX_BYTES
                or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            ):
                continue
            projected.append(
                {
                    "schemaVersion": "rag-ime.agent-block.v1",
                    "id": bounded_text(block.block_id, maximum=160),
                    "type": "file",
                    "status": "completed",
                    "presentationKind": "file",
                    "data": {
                        "mediaId": media_id,
                        "sessionId": media_session_id,
                        "fileName": file_name,
                        "mimeType": mime_type,
                        "byteSize": byte_size,
                        "sha256": sha256,
                        "receiptUrl": managed_media_content_url(
                            media_session_id,
                            media_id,
                        ),
                    },
                }
            )
            continue

        data = block.data
        raw_name = str(
            data.get("fileName")
            or data.get("path")
            or data.get("title")
            or ""
        )
        file_name = public_file_name(raw_name)
        diff = public_tool_output_text(
            data.get("diff") or data.get("text"),
            maximum=6_000,
        )
        if not file_name or not diff:
            continue
        diff_data: dict[str, object] = {
            "fileName": file_name,
            "diff": diff,
        }
        for key in ("additions", "deletions"):
            count = data.get(key)
            if (
                isinstance(count, int)
                and not isinstance(count, bool)
                and 0 <= count <= 1_000_000
            ):
                diff_data[key] = count
        if data.get("truncated") is True:
            diff_data["truncated"] = True
        projected.append(
            {
                "schemaVersion": "rag-ime.agent-block.v1",
                "id": bounded_text(block.block_id, maximum=160),
                "type": "diff",
                "status": "completed",
                "presentationKind": "diff",
                "data": diff_data,
            }
        )
    return projected

_ROOM_TOOL_NAMES = frozenset(
    {
        "room_state",
        "room_define",
        "room_collaborate",
        "room_integrate",
        "room_post",
        "room_commit",
    }
)

_ROOM_REQUEST_TEXT_LIMITS = {
    "targetParticipantRef": 240,
    "childTaskId": 240,
    "workspacePolicy": 120,
    "intent": 120,
    "objective": 1_000,
    "expectedOutput": 1_000,
    "entrySurface": 1_000,
    "primaryInteraction": 2_000,
    "observableCompletion": 2_000,
    "kind": 120,
    "action": 120,
    "summary": 500,
    "decision": 80,
    "publicSummary": 1_000,
    "question": 500,
    "questionKind": 80,
    "resumeCondition": 1_000,
    "waitingFor": 120,
    "blocker": 1_000,
}

_ROOM_REQUEST_LIST_KEYS = frozenset(
    {
        "acceptance",
        "mentions",
    }
)

_ROOM_RESULT_KEYS_BY_TOOL = {
    "room_state": (
        "ok",
        "created",
        "evidenceRef",
        "unchanged",
        "stateRevision",
        "currentResponsibility",
        "acceptanceAliases",
        "participants",
        "recentPublicChanges",
        "pendingIntegrations",
        "canSettle",
        "pendingCancellationTargets",
        "summary",
        "status",
    ),
    "room_collaborate": (
        "accepted",
        "enqueued",
        "deduplicated",
        "childTaskId",
        "childDispatchId",
        "workspacePolicy",
        "targetParticipantRef",
        "currentResponsibilityContinues",
    ),
    "room_integrate": (
        "integrated",
        "idempotent",
        "noChanges",
        "childTaskId",
        "workspaceIntegrationRef",
    ),
    "room_post": (
        "published",
        "postRef",
        "deduplicated",
        "currentResponsibilityContinues",
    ),
    "room_commit": (
        "accepted",
        "executionPerformed",
        "settlementStaged",
        "terminalForModelTurn",
        "canonicalTool",
    ),
}

_ROOM_RESULT_BOOLEAN_KEYS = frozenset(
    {
        "ok",
        "created",
        "unchanged",
        "accepted",
        "enqueued",
        "deduplicated",
        "published",
        "integrated",
        "idempotent",
        "noChanges",
        "currentResponsibilityContinues",
        "executionPerformed",
        "settlementStaged",
        "terminalForModelTurn",
        "canSettle",
    }
)

_ROOM_RESULT_TEXT_LIMITS = {
    "evidenceRef": 240,
    "stateRevision": 160,
    "summary": 500,
    "status": 160,
    "childTaskId": 240,
    "childDispatchId": 240,
    "workspacePolicy": 120,
    "workspaceIntegrationRef": 240,
    "targetParticipantRef": 240,
    "postRef": 240,
    "canonicalTool": 120,
}


def _room_tool_request_projection(
    raw_args: Mapping[str, object],
    *,
    tool_name: str,
) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key, maximum in _ROOM_REQUEST_TEXT_LIMITS.items():
        if tool_name == "room_commit" and key == "summary":
            # room_commit.summary is explicitly private model-to-kernel data;
            # publicSummary owns what the user may inspect.
            continue
        value = raw_args.get(key)
        if not isinstance(value, str):
            continue
        text = _redacted_room_text(value, maximum=maximum)
        if text:
            projected[key] = text
    for key in _ROOM_REQUEST_LIST_KEYS:
        raw_values = raw_args.get(key)
        if not isinstance(raw_values, list):
            continue
        values = [
            text
            for value in raw_values[:32]
            if isinstance(value, str)
            and (text := _redacted_room_text(value, maximum=240))
        ]
        if values:
            projected[key] = values
    raw_options = raw_args.get("questionOptions")
    if isinstance(raw_options, list):
        options: list[dict[str, object]] = []
        for raw_option in raw_options[:5]:
            if not isinstance(raw_option, Mapping):
                continue
            value = _redacted_room_text(raw_option.get("value"), maximum=80)
            label = _redacted_room_text(raw_option.get("label"), maximum=120)
            description = _redacted_room_text(
                raw_option.get("description"),
                maximum=500,
            )
            if not value or not label or not description:
                continue
            options.append(
                {
                    "value": value,
                    "label": label,
                    "description": description,
                    **(
                        {"recommended": True}
                        if raw_option.get("recommended") is True
                        else {}
                    ),
                }
            )
        if options:
            projected["questionOptions"] = options
    return projected


def _room_tool_result_layers(
    value: object,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Mapping):
        return ()
    redacted = redact_mapping(value)
    layers: list[Mapping[str, object]] = []

    def visit(layer: Mapping[str, object], depth: int) -> None:
        if depth > 3:
            return
        layers.append(layer)
        for key in ("details", "result"):
            child = layer.get(key)
            if isinstance(child, Mapping):
                visit(child, depth + 1)

    visit(redacted, 0)
    return tuple(layers)


def _room_current_responsibility(
    value: object,
) -> dict[str, str] | str | None:
    if isinstance(value, Mapping):
        projected: dict[str, str] = {}
        for key, maximum in (
            ("objective", 1_000),
            ("expectedOutput", 1_000),
            ("state", 160),
            ("workspacePolicy", 120),
        ):
            text = _redacted_room_text(value.get(key), maximum=maximum)
            if text:
                projected[key] = text
        return projected or None
    text = _redacted_room_text(value, maximum=500)
    return text or None


def _room_acceptance_projection(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, object]] = []
    for item in value[:32]:
        if not isinstance(item, Mapping):
            continue
        statement = _redacted_room_text(item.get("statement"), maximum=1_000)
        if not statement:
            continue
        result.append(
            {
                "statement": statement,
                "verified": item.get("verified") is True,
            }
        )
    return result


def _room_participant_projection(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:16]:
        if not isinstance(item, Mapping):
            continue
        projected: dict[str, str] = {}
        for key, maximum in (
            ("displayName", 160),
            ("availability", 80),
            ("capabilitySummary", 320),
        ):
            text = _redacted_room_text(item.get(key), maximum=maximum)
            if text:
                projected[key] = text
        if projected.get("displayName"):
            result.append(projected)
    return result


def _room_recent_change_projection(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:8]:
        if not isinstance(item, Mapping):
            continue
        content = _redacted_room_text(item.get("content"), maximum=500)
        if not content:
            continue
        kind = _redacted_room_text(item.get("kind"), maximum=80)
        result.append({**({"kind": kind} if kind else {}), "content": content})
    return result


def _room_pending_integration_projection(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:16]:
        if not isinstance(item, Mapping):
            continue
        objective = _redacted_room_text(item.get("objective"), maximum=1_000)
        if objective:
            result.append({"objective": objective})
    return result


def _room_tool_result_projection(
    tool_name: str,
    raw_result: object,
) -> dict[str, object]:
    keys = _ROOM_RESULT_KEYS_BY_TOOL.get(
        str(tool_name or "").strip().lower()
    )
    if not keys:
        return {}
    layers = _room_tool_result_layers(raw_result)
    if not layers:
        return {}
    projected: dict[str, object] = {}
    for key in keys:
        value = next(
            (
                layer[key]
                for layer in layers
                if key in layer
            ),
            None,
        )
        if value is None:
            continue
        if key == "currentResponsibility":
            current = _room_current_responsibility(value)
            if current is not None:
                projected[key] = current
            continue
        if key == "acceptanceAliases":
            acceptance = _room_acceptance_projection(value)
            if acceptance:
                projected[key] = acceptance
            continue
        if key == "participants":
            participants = _room_participant_projection(value)
            if participants:
                projected[key] = participants
            continue
        if key == "recentPublicChanges":
            changes = _room_recent_change_projection(value)
            if changes:
                projected[key] = changes
            continue
        if key == "pendingIntegrations":
            integrations = _room_pending_integration_projection(value)
            if integrations:
                projected[key] = integrations
            continue
        if key == "pendingCancellationTargets":
            if isinstance(value, int) and not isinstance(value, bool):
                projected[key] = max(0, min(value, 1_000))
            continue
        if key in _ROOM_RESULT_BOOLEAN_KEYS:
            if isinstance(value, bool):
                projected[key] = value
            continue
        maximum = _ROOM_RESULT_TEXT_LIMITS.get(key)
        if maximum is None or not isinstance(value, str):
            continue
        text = _redacted_room_text(value, maximum=maximum)
        if text:
            projected[key] = text
    return projected


def _room_user_input_disclosure(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Expose only the bounded public question contract owned by the runtime."""

    method = bounded_text(payload.get("method"), maximum=40)
    if method not in {"select", "confirm", "input", "editor"}:
        method = ""
    request_kind = bounded_text(
        payload.get("requestKind"),
        maximum=120,
    ) or "user_input_required"
    disclosure: dict[str, object] = {"requestKind": request_kind}
    if method:
        disclosure["method"] = method
    for field, maximum in (
        ("title", 160),
        ("message", 500),
        ("placeholder", 500),
        ("prefill", 4_000),
        ("defaultValue", 4_000),
    ):
        if payload.get(field) is not None:
            disclosure[field] = bounded_text(
                payload.get(field),
                maximum=maximum,
            )
    if request_kind == "grouped_questions":
        raw_questions = payload.get("questions")
        if isinstance(raw_questions, list):
            try:
                questions = grouped_questions_from_wire(
                    json.dumps(
                        {
                            "schemaVersion": GROUPED_QUESTIONS_SCHEMA_VERSION,
                            "questions": raw_questions,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            except (TypeError, ValueError):
                questions = []
            if questions:
                disclosure["schemaVersion"] = GROUPED_QUESTIONS_SCHEMA_VERSION
                disclosure["questions"] = questions
    else:
        raw_options = payload.get("options")
        if isinstance(raw_options, list):
            disclosure["options"] = [
                option
                for value in raw_options[:100]
                if (
                    option := bounded_text(
                        value,
                        maximum=240,
                    )
                )
            ]
    timeout = payload.get("timeout")
    if (
        isinstance(timeout, (int, float))
        and not isinstance(timeout, bool)
    ):
        disclosure["timeout"] = max(0, int(timeout))
    for field, allowed in (
        (
            "resolutionState",
            frozenset({"resolved", "cancelled"}),
        ),
        (
            "resolutionSource",
            frozenset(
                {
                    "direct_user",
                    "user_cancelled",
                    "timeout",
                    "runtime_cancelled",
                }
            ),
        ),
    ):
        value = bounded_text(
            payload.get(field),
            maximum=40,
        )
        if value in allowed:
            disclosure[field] = value
    return disclosure


def _redacted_room_text(
    value: object,
    *,
    maximum: int,
) -> str:
    redacted = redact_mapping({"value": value}).get("value")
    return bounded_text(redacted, maximum=maximum)


def _room_tool_disclosure(
    payload: Mapping[str, object],
    event_type: str,
    *,
    session_id: str,
) -> dict[str, object]:
    raw_args = (
        payload.get("args")
        if isinstance(payload.get("args"), Mapping)
        else {}
    )
    raw_result = (
        payload.get("partialResult")
        if event_type == "tool_progress"
        else payload.get("result")
    )
    tool_name = str(payload.get("toolName") or "").strip().lower()
    is_room_tool = tool_name in _ROOM_TOOL_NAMES
    public_result = (
        dict(payload["publicResult"])
        if isinstance(payload.get("publicResult"), Mapping)
        else public_code_tool_activity(
            tool_name,
            raw_args,
            raw_result,
        )
    )
    if is_room_tool:
        arguments = _room_tool_request_projection(
            raw_args,
            tool_name=tool_name,
        )
    elif public_result:
        arguments = {
            key: public_result[key]
            for key in _ROOM_TOOL_REQUEST_KEYS
            if key in public_result
        }
    else:
        redacted_args = redact_mapping(raw_args)
        arguments = {
            key: redacted_args[key]
            for key in _ROOM_TOOL_REQUEST_KEYS
            if key in redacted_args and key != "context"
        }

    disclosure: dict[str, object] = {}
    bounded_arguments = _bounded_room_tool_value(arguments)
    if isinstance(bounded_arguments, Mapping) and bounded_arguments:
        disclosure["arguments"] = bounded_arguments

    if event_type in {"tool_progress", "tool_finished"}:
        if is_room_tool:
            result_source = _room_tool_result_projection(
                tool_name,
                raw_result,
            )
            if not result_source and public_result:
                result_source = _room_tool_result_projection(
                    tool_name,
                    public_result,
                )
        elif public_result:
            result_source = {
                key: public_result[key]
                for key in _ROOM_TOOL_RESULT_KEYS
                if key in public_result
            }
        else:
            redacted_result = (
                redact_mapping(raw_result)
                if isinstance(raw_result, Mapping)
                else {}
            )
            result_source = {
                key: redacted_result[key]
                for key in _ROOM_TOOL_RESULT_KEYS
                if key in redacted_result
            }
        bounded_result = _bounded_room_tool_value(result_source)
        if isinstance(bounded_result, Mapping) and bounded_result:
            disclosure["result"] = bounded_result
        if bool(payload.get("isError")):
            error = (
                _room_tool_error(public_result)
                or _room_tool_error(
                    redact_mapping(raw_result)
                    if isinstance(raw_result, Mapping)
                    else {},
                )
                or _redacted_room_text(
                    payload.get("error"),
                    maximum=1_000,
                )
            )
            if error:
                disclosure["error"] = error
    if event_type == "tool_finished" and not bool(payload.get("isError")):
        agent_blocks = _room_tool_agent_blocks_projection(
            payload.get("agentBlocks"),
            session_id=session_id,
        )
        if agent_blocks:
            disclosure["agentBlocks"] = agent_blocks
    return disclosure


def _bounded_room_tool_value(
    value: object,
    *,
    depth: int = 0,
) -> object:
    if depth >= 4:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            bounded_text(key, maximum=120): _bounded_room_tool_value(
                child,
                depth=depth + 1,
            )
            for key, child in list(value.items())[:32]
            if bounded_text(key, maximum=120)
        }
    if isinstance(value, list):
        return [
            _bounded_room_tool_value(item, depth=depth + 1)
            for item in value[:32]
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return bounded_text(value, maximum=2_000)


def _room_tool_error(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    for key in ("error", "errorMessage", "reason"):
        error = bounded_text(value.get(key), maximum=1_000)
        if error:
            return error
    for child in value.values():
        error = _room_tool_error(child)
        if error:
            return error
    return ""


def _room_tool_summary(
    payload: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    raw_result = (
        payload.get("result")
        or payload.get("partialResult")
        or payload.get("publicResult")
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
