from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .agent_protocol import AgentEventEnvelope
from .agent_rooms import AgentRoomEventHub


_ROOM_POST_PUBLIC_FIELDS = (
    "schemaVersion",
    "postId",
    "roomId",
    "rootId",
    "generation",
    "taskId",
    "dispatchId",
    "authorActorRef",
    "kind",
    "visibility",
    "content",
    "blocks",
    "idempotencyKey",
    "publicationSource",
    "createdAtMs",
)


class RoomPublicTimelineProjector:
    """Project canonical Room work into one replayable public timeline.

    The Kernel remains the sole execution owner. This class only owns the
    user-facing read model: accepted input, routing, bounded live progress,
    explicit RoomPost publication, and terminal state.
    """

    def __init__(
        self,
        events: AgentRoomEventHub,
        *,
        root_is_terminal: Callable[[str], bool] | None = None,
    ) -> None:
        self.events = events
        self.root_is_terminal = root_is_terminal

    def publish_ingress(
        self,
        *,
        room: Mapping[str, object],
        post: Mapping[str, object],
        client_message_id: str,
        route_decisions: Sequence[Mapping[str, object]],
        dispatches: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        room_id = str(post["roomId"])
        root_id = str(post["rootId"])
        topic_id = str(room.get("activeTopicId") or "")
        projected: list[dict[str, object]] = []
        user_event = self.events.publish_projection(
            projection_key=f"room-post:{post['postId']}",
            room_id=room_id,
            event_type="user_message",
            payload={
                "messageId": str(post["postId"]),
                "clientMessageId": client_message_id,
                "text": str(post["content"]),
                "rootId": root_id,
                "postId": str(post["postId"]),
            },
            turn_id=root_id,
            topic_id=topic_id,
            created_at_ms=int(post["createdAtMs"]),
        )
        if user_event is not None:
            projected.append(user_event)

        participants = {
            str(value.get("id") or ""): value
            for value in room.get("participants", [])
            if isinstance(value, Mapping)
        }
        for decision, dispatch in zip(
            route_decisions,
            dispatches,
            strict=True,
        ):
            participant_id = str(dispatch.get("participantId") or "")
            participant = participants.get(participant_id, {})
            display_name = str(
                participant.get("displayName") or "协作成员"
            )
            dispatch_id = str(dispatch.get("dispatchId") or "")
            event = self.events.publish_projection(
                projection_key=f"room-dispatch:{dispatch_id}:accepted",
                room_id=room_id,
                event_type="route_decision",
                payload={
                    "rootId": root_id,
                    "taskId": str(decision.get("taskId") or ""),
                    "dispatchId": dispatch_id,
                    "targetParticipantId": participant_id,
                    "status": "queued",
                    "reason": str(decision.get("reason") or "")[:160],
                    "summary": f"{display_name} 已接手",
                },
                turn_id=root_id,
                participant_id=participant_id or None,
                source_session_id=str(dispatch.get("sessionId") or ""),
                topic_id=topic_id,
                created_at_ms=int(post["createdAtMs"]),
            )
            if event is not None:
                projected.append(event)
        return projected

    def publish_runtime(
        self,
        *,
        event: AgentEventEnvelope,
        binding: Mapping[str, object],
        participant: Mapping[str, object],
        event_type: str,
        public_data: Mapping[str, object],
        topic_id: str = "",
    ) -> dict[str, object] | None:
        root_id = str(binding["rootId"])
        if self._after_root_terminal(root_id):
            return None
        dispatch_id = str(binding["dispatchId"])
        data = {
            **dict(public_data),
            "rootId": root_id,
            "dispatchId": dispatch_id,
        }
        return self.events.publish_projection(
            projection_key=f"room-runtime:{event.event_id}",
            room_id=str(binding["roomId"]),
            event_type=event_type,
            payload={
                "sourceEventId": event.event_id,
                "sourceEventType": event.event_type,
                "data": data,
            },
            turn_id=root_id,
            participant_id=str(participant["id"]),
            source_session_id=event.session_id,
            topic_id=topic_id,
            created_at_ms=event.created_at_ms,
        )

    def publish_post(
        self,
        post: Mapping[str, object],
        *,
        participant_id: str,
        source_session_id: str,
        topic_id: str = "",
    ) -> dict[str, object] | None:
        if self._after_root_terminal(str(post["rootId"])):
            return None
        public_post = {
            field: post[field]
            for field in _ROOM_POST_PUBLIC_FIELDS
            if field in post
        }
        return self.events.publish_projection(
            projection_key=f"room-post:{post['postId']}",
            room_id=str(post["roomId"]),
            event_type="room_post",
            # Context storage enriches a post with hashes and its journal
            # entry. Those are private evidence, not part of RoomPostV2.
            payload={"post": public_post},
            turn_id=str(post["rootId"]),
            participant_id=participant_id or None,
            source_session_id=source_session_id,
            topic_id=topic_id,
            created_at_ms=int(post["createdAtMs"]),
        )

    def _after_root_terminal(self, root_id: str) -> bool:
        return bool(
            self.root_is_terminal is not None
            and self.root_is_terminal(root_id)
        )

    def publish_terminal(
        self,
        *,
        room_id: str,
        root_id: str,
        generation: int,
        state: str,
        receipt_id: str,
        created_at_ms: int,
    ) -> dict[str, object] | None:
        normalized_state = (
            "aborted"
            if state == "cancelled"
            else "failed"
            if state == "failed"
            else "completed"
        )
        event_type = (
            "turn_failed" if normalized_state == "failed" else "turn_completed"
        )
        return self.events.publish_projection(
            projection_key=(
                f"room-root:{root_id}:generation:{generation}:terminal:{receipt_id or state}"
            ),
            room_id=room_id,
            event_type=event_type,
            payload={
                "rootId": root_id,
                "generation": generation,
                "status": normalized_state,
                "receiptId": receipt_id,
            },
            turn_id=root_id,
            created_at_ms=created_at_ms,
        )

    def sync_terminal_root(
        self,
        root: Mapping[str, object],
    ) -> dict[str, object] | None:
        state = str(root.get("state") or "")
        if state not in {
            "completed",
            "cancelled",
            "failed",
        }:
            return None
        return self.publish_terminal(
            room_id=str(root["roomId"]),
            root_id=str(root["rootId"]),
            generation=int(root["generation"]),
            state=state,
            receipt_id=str(root.get("terminalReceiptId") or ""),
            created_at_ms=int(root.get("updatedAtMs") or 0),
        )
