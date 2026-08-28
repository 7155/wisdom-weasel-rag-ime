from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock

from .agent_personas import AgentPersonaStore
from .agent_room_lifecycle import RoomLifecycleService
from .agent_room_participants import (
    RoomParticipantLifecycleService,
)
from .agent_room_resources import RoomResourceService
from .agent_rooms import AgentRoomEventHub, AgentRoomStore
from .agent_sessions import AgentSessionStore


class RoomManagementService:
    """Compatibility facade over bounded Room lifecycle services."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        sessions: AgentSessionStore,
        personas: AgentPersonaStore,
        events: AgentRoomEventHub,
        create_session: Callable[
            [Mapping[str, object]],
            dict[str, object],
        ],
        delete_session: Callable[
            [str],
            dict[str, object],
        ],
        runtime_status: Callable[
            [],
            Mapping[str, object],
        ],
        release_room_work: Callable[
            [str, str, str, str],
            list[dict[str, object]],
        ] | None = None,
        turn_lock: RLock,
        pending_turns: Mapping[str, str],
        user_priority_sessions: set[str],
    ) -> None:
        self.participants = RoomParticipantLifecycleService(
            rooms=rooms,
            sessions=sessions,
            personas=personas,
            events=events,
            create_session=create_session,
            runtime_status=runtime_status,
            release_room_work=release_room_work,
            turn_lock=turn_lock,
            pending_turns=pending_turns,
            user_priority_sessions=(
                user_priority_sessions
            ),
        )
        self.resources = RoomResourceService(
            rooms=rooms,
            events=events,
        )
        self.lifecycle = RoomLifecycleService(
            rooms=rooms,
            sessions=sessions,
            personas=personas,
            events=events,
            participants=self.participants,
            create_session=create_session,
            delete_session=delete_session,
        )

    def list_rooms(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.lifecycle.list_rooms(payload)

    def participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return self.participants.participant_sessions(room)

    def restore_participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> None:
        self.participants.restore_sessions(room)

    def get_room(self, room_id: str) -> dict[str, object]:
        return self.lifecycle.get_room(room_id)

    def snapshot(self, room_id: str) -> dict[str, object]:
        return self.lifecycle.snapshot(room_id)

    def history(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.lifecycle.history(room_id, payload)

    def topics(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.resources.topics(room_id, payload)

    def create_topic(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.resources.create_topic(
            room_id,
            payload,
        )

    def update_topic(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.resources.update_topic(
            room_id,
            payload,
        )

    def artifacts(
        self,
        room_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self.resources.artifacts(
            room_id,
            payload,
        )

    def add_artifact(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.resources.add_artifact(
            room_id,
            payload,
        )

    def update_artifact(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.resources.update_artifact(
            room_id,
            payload,
        )

    def update_room(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.lifecycle.update(room_id, payload)

    def add_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.participants.add(room_id, payload)

    def remove_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.participants.remove(room_id, payload)

    def update_participant_role(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.participants.update_role(room_id, payload)

    def delete_room(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.lifecycle.delete(room_id, payload)

    def create_room(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.lifecycle.create(payload)

    def _repair_participant_session(
        self,
        room: Mapping[str, object],
        participant: Mapping[str, object],
    ) -> dict[str, object]:
        return self.participants.repair_session(
            room,
            participant,
        )
