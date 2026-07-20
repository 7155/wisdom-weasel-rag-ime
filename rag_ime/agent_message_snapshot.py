from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_protocol import AgentEventEnvelope


class AgentMessageSnapshotService:
    """Project one Session snapshot from Pi, durable rows, and live events."""

    def __init__(
        self,
        *,
        sessions: Any,
        runtime: Any,
        agent_blocks: Any,
        observations: Any,
        events: Any,
    ) -> None:
        self.sessions = sessions
        self.runtime = runtime
        self.agent_blocks = agent_blocks
        self.observations = observations
        self.events = events

    def messages(self, session_id: str) -> dict[str, object]:
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
        session = self._reconcile_session_status(
            session_id,
            session,
        )
        workflow = self.sessions.workflow_state(session_id)
        return {
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
            "plan": workflow["plan"],
            "goal": workflow["goal"],
            "actGate": workflow["actGate"],
        }

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
            live_events.append(
                AgentEventEnvelope(
                    event_id=event_id,
                    session_id=session_id,
                    turn_id=f"approval:{approval_id}",
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
    merged: list[dict[str, object]] = []
    for event in history:
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
