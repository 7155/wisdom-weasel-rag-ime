from __future__ import annotations

from collections.abc import Mapping

from rag_ime.rooms.store import AgentRoomEventHub, AgentRoomStore


class RoomResourceService:
    """Own Room topic and shared-artifact mutations."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        events: AgentRoomEventHub,
    ) -> None:
        self.rooms = rooms
        self.events = events

    def topics(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        values = payload or {}
        return {
            "schemaVersion": "rag-ime.agent-room-topics.v1",
            "ok": True,
            "items": self.rooms.list_topics(
                room_id,
                include_archived=_bool(
                    values.get("includeArchived")
                ),
            ),
        }

    def create_topic(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        topic = self.rooms.create_topic(
            room_id,
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
        )
        room = self.rooms.get(room_id)
        event = self.events.publish(
            room_id=room_id,
            event_type="topic_changed",
            payload={"action": "created", "topic": topic},
            topic_id=str(topic["id"]),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-topic-create.v1"
            ),
            "ok": True,
            "topic": topic,
            "room": room,
            "event": event,
        }

    def update_topic(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        topic_id = str(
            payload.get("topicId") or ""
        ).strip()
        if not topic_id:
            raise ValueError("topicId must not be empty")
        values = {
            key: value
            for key, value in payload.items()
            if key != "topicId"
        }
        topic = self.rooms.update_topic(
            room_id,
            topic_id,
            values,
        )
        room = self.rooms.get(room_id)
        event = self.events.publish(
            room_id=room_id,
            event_type="topic_changed",
            payload={
                "action": (
                    "activated"
                    if _bool(values.get("activate"))
                    else "archived"
                    if _bool(values.get("archived"))
                    else "updated"
                ),
                "topic": topic,
            },
            topic_id=topic_id,
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-topic-update.v1"
            ),
            "ok": True,
            "topic": topic,
            "room": room,
            "event": event,
        }

    def artifacts(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        values = payload or {}
        return {
            "schemaVersion": "rag-ime.agent-room-artifacts.v1",
            "ok": True,
            "items": self.rooms.list_artifacts(
                room_id,
                include_archived=_bool(
                    values.get("includeArchived")
                ),
                topic_id=str(values.get("topicId") or ""),
                limit=_integer(
                    values.get("limit"),
                    default=100,
                    minimum=1,
                    maximum=200,
                ),
            ),
        }

    def add_artifact(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        artifact = self.rooms.add_artifact(
            room_id,
            path=str(payload.get("path") or ""),
            display_name=str(
                payload.get("displayName") or ""
            ),
            topic_id=str(payload.get("topicId") or ""),
            media_type=str(
                payload.get("mediaType") or ""
            ),
            created_by_participant_id=str(
                payload.get("participantId") or ""
            ),
        )
        event = self.events.publish(
            room_id=room_id,
            event_type="artifact_changed",
            payload={"action": "added", "artifact": artifact},
            topic_id=str(artifact["topicId"]),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-artifact-add.v1"
            ),
            "ok": True,
            "artifact": artifact,
            "room": self.rooms.get(room_id),
            "event": event,
        }

    def update_artifact(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        artifact_id = str(
            payload.get("artifactId") or ""
        ).strip()
        if not artifact_id:
            raise ValueError("artifactId must not be empty")
        artifact = self.rooms.archive_artifact(
            room_id,
            artifact_id,
            archived=_bool(payload.get("archived")),
        )
        event = self.events.publish(
            room_id=room_id,
            event_type="artifact_changed",
            payload={
                "action": (
                    "archived"
                    if artifact["status"] == "archived"
                    else "restored"
                ),
                "artifact": artifact,
            },
            topic_id=str(artifact["topicId"]),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-artifact-update.v1"
            ),
            "ok": True,
            "artifact": artifact,
            "room": self.rooms.get(room_id),
            "event": event,
        }


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
