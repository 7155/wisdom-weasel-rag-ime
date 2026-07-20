from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .agent_room_intercom import AgentRoomTargetBusy


class RoomIntercomApplicationService:
    """Own busy checks, delivery, and public Intercom audit events."""

    def __init__(
        self,
        *,
        sessions: Any,
        rooms: Any,
        room_work: Any,
        context_runtime: Any,
        room_events: Any,
        runtime_provider: Callable[[], Any],
        user_priority_sessions: set[str],
        turn_lock: Any,
        guard_legacy_room_route: Callable[[str, str], None],
        runtime_prompt_with_context: Callable[..., tuple],
        room_intercom_prompt: Callable[..., str],
        room_participant_prompt: Callable[..., str],
        publish_room_work_activity: Callable[..., None],
    ) -> None:
        self.sessions = sessions
        self.rooms = rooms
        self.room_work = room_work
        self.context_runtime = context_runtime
        self.room_events = room_events
        self._runtime_provider = runtime_provider
        self.user_priority_sessions = user_priority_sessions
        self.turn_lock = turn_lock
        self.guard_legacy_room_route = (
            guard_legacy_room_route
        )
        self.runtime_prompt_with_context = (
            runtime_prompt_with_context
        )
        self.room_intercom_prompt = room_intercom_prompt
        self.room_participant_prompt = (
            room_participant_prompt
        )
        self.publish_room_work_activity = (
            publish_room_work_activity
        )

    @property
    def runtime(self) -> Any:
        return self._runtime_provider()

    def runtime_generation(self, session_id: str) -> int:
        session = self.sessions.get(session_id)
        if str(session.get("status") or "") in {
            "archived",
            "faulted",
        }:
            raise ValueError(
                "room participant session is unavailable"
            )
        binding = self.sessions.runtime_binding(session_id)
        return (
            max(0, int(binding.get("generation") or 0))
            if binding
            else 0
        )

    def target_idle(
        self,
        session_id: str,
        *,
        allow_user_priority: bool = False,
    ) -> bool:
        if not allow_user_priority:
            with self.turn_lock:
                if session_id in self.user_priority_sessions:
                    return False
        session = self.sessions.get(session_id)
        if str(session.get("status") or "") not in {
            "idle",
            "active",
        }:
            return False
        runtime_status = self.runtime.runtime_status()
        if str(runtime_status.get("status") or "") == "starting":
            return False
        capabilities = (
            runtime_status.get("capabilities")
            if isinstance(
                runtime_status.get("capabilities"),
                Mapping,
            )
            else {}
        )
        if not _bool(capabilities.get("multiSession")):
            return (
                str(runtime_status.get("status") or "")
                != "busy"
            )
        active_session_ids = {
            str(value)
            for value in runtime_status.get(
                "activeSessionIds",
                [],
            )
            if str(value or "").strip()
        }
        if session_id in active_session_ids:
            return False
        participant = self.rooms.participant_for_session(
            session_id,
            active_only=False,
        )
        if participant is None:
            return False
        room = self.rooms.get(str(participant["roomId"]))
        room_session_ids = {
            str(value.get("sessionId") or "")
            for value in room.get("participants", [])
            if isinstance(value, Mapping)
            and str(value.get("status") or "") == "active"
        }
        return len(
            active_session_ids & room_session_ids
        ) < 4

    def deliver(
        self,
        item: Mapping[str, object],
    ) -> Mapping[str, object]:
        target_session_id = str(
            item.get("targetSessionId") or ""
        )
        self.guard_legacy_room_route(
            "intercom.delivery",
            target_session_id,
        )
        if not self.target_idle(target_session_id):
            raise AgentRoomTargetBusy(
                "target participant is not idle"
            )
        source = self.rooms.participant(
            str(item.get("sourceParticipantId") or "")
        )
        target = self.rooms.participant(
            str(item.get("targetParticipantId") or "")
        )
        room = self.rooms.get(
            str(
                item.get("roomId")
                or target.get("roomId")
                or ""
            )
        )
        work_item_id = str(
            item.get("workItemId") or ""
        )
        work = (
            self.room_work.get(work_item_id)
            if work_item_id
            else None
        )
        kind = str(item.get("kind") or "send")
        self.context_runtime.enqueue(
            session_id=target_session_id,
            source_kind="room_intercom",
            source_id=str(item.get("id") or ""),
            lane="room",
            lifecycle="turn",
            dedupe_key=f"room:{item.get('id')}",
            title=(
                f"来自 {source.get('displayName')} "
                "的房间协作消息"
            ),
            summary=f"{kind} · 房间协作消息",
            payload={
                "messageId": str(item.get("id") or ""),
                "kind": kind,
                "sourceParticipantId": str(
                    source.get("id") or ""
                ),
                "sourceDisplayName": str(
                    source.get("displayName") or ""
                ),
                "targetParticipantId": str(
                    target.get("id") or ""
                ),
                "replyTo": str(
                    item.get("replyTo") or ""
                ),
                "workItemId": work_item_id,
                "workAction": str(
                    item.get("workAction") or ""
                ),
                "content": str(item.get("content") or ""),
            },
        )
        accepted, trace_id, delivered = (
            self.runtime_prompt_with_context(
                target_session_id,
                self.room_intercom_prompt(
                    room,
                    target,
                    item,
                    source=source,
                    work=work,
                ),
                source_kind="room",
                transient_context=(
                    self.room_participant_prompt(
                        room,
                        target,
                        "",
                    )
                ),
            )
        )
        return {
            **accepted,
            "contextTraceId": trace_id,
            "contextItemsDelivered": delivered,
        }

    def publish_audit(
        self,
        item: Mapping[str, object],
        phase: str,
    ) -> None:
        work_item_id = str(
            item.get("workItemId") or ""
        )
        work_action = str(item.get("workAction") or "")
        if work_item_id and work_action == "assignment":
            self._settle_assignment(
                item,
                phase=phase,
                work_item_id=work_item_id,
            )
        self.room_events.publish(
            room_id=str(item.get("roomId") or ""),
            event_type="participant_activity",
            payload={
                "activityKind": "intercom",
                "phase": phase,
                "message": {
                    "id": str(item.get("id") or ""),
                    "kind": str(
                        item.get("kind") or ""
                    ),
                    "sourceParticipantId": str(
                        item.get(
                            "sourceParticipantId"
                        )
                        or ""
                    ),
                    "targetParticipantId": str(
                        item.get(
                            "targetParticipantId"
                        )
                        or ""
                    ),
                    "replyTo": str(
                        item.get("replyTo") or ""
                    ),
                    "workItemId": work_item_id,
                    "workAction": work_action,
                    "status": str(
                        item.get("status") or ""
                    ),
                    "content": str(
                        item.get("content") or ""
                    )[:4_000],
                    "acceptedTurnId": str(
                        item.get("acceptedTurnId") or ""
                    ),
                    "error": str(
                        item.get("error") or ""
                    )[:500],
                },
            },
            turn_id=str(
                item.get("acceptedTurnId")
                or item.get("id")
                or ""
            ),
            participant_id=str(
                item.get("sourceParticipantId") or ""
            ),
            source_session_id=str(
                item.get("sourceSessionId") or ""
            ),
        )

    def _settle_assignment(
        self,
        item: Mapping[str, object],
        *,
        phase: str,
        work_item_id: str,
    ) -> None:
        if phase == "delivered":
            work = self.room_work.accept_assignment(
                work_item_id,
                target_participant_id=str(
                    item.get("targetParticipantId") or ""
                ),
                accepted_turn_id=str(
                    item.get("acceptedTurnId") or ""
                ),
            )
            actor_id = str(
                item.get("targetParticipantId") or ""
            )
            activity_phase = "accepted"
        elif phase in {"failed", "stale"}:
            work = self.room_work.fail_assignment(
                work_item_id,
                actor_participant_id=str(
                    item.get("sourceParticipantId") or ""
                ),
                reason=str(item.get("error") or phase),
            )
            actor_id = str(
                item.get("sourceParticipantId") or ""
            )
            activity_phase = "assignment_failed"
        else:
            return
        actor = self.rooms.participant(actor_id)
        self.publish_room_work_activity(
            work,
            phase=activity_phase,
            actor=actor,
        )
def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
