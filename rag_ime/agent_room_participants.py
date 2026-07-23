from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock

from .agent_personas import AgentPersonaStore
from .agent_execution_policy import (
    FULL_TRUST_EXECUTION_MODE,
    PER_ACTION_EXECUTION_MODE,
    WORKSPACE_MANAGED_EXECUTION_MODE,
    canonical_tool_profile,
    normalize_execution_mode,
)
from .agent_rooms import (
    AgentRoomEventHub,
    AgentRoomStore,
    normalize_collaboration_role,
)
from .agent_sessions import (
    AgentSessionNotFound,
    AgentSessionStore,
)
from .agent_tool_ids import CONTROL_CENTER_TOOL_PROFILE


class RoomParticipantLifecycleService:
    """Own the Room participant and private Session lifecycle."""

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
        runtime_status: Callable[
            [],
            Mapping[str, object],
        ],
        turn_lock: RLock,
        pending_turns: Mapping[str, str],
        user_priority_sessions: set[str],
    ) -> None:
        self.rooms = rooms
        self.sessions = sessions
        self.personas = personas
        self.events = events
        self.create_session = create_session
        self.runtime_status = runtime_status
        self.turn_lock = turn_lock
        self.pending_turns = pending_turns
        self.user_priority_sessions = (
            user_priority_sessions
        )

    def participant_sessions(
        self,
        room: Mapping[str, object],
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for participant in room.get("participants", []):
            if (
                not isinstance(participant, Mapping)
                or participant.get("status") != "active"
            ):
                continue
            session_id = str(
                participant.get("sessionId") or ""
            ).strip()
            if not session_id:
                continue
            try:
                result.append(self.sessions.get(session_id))
            except AgentSessionNotFound:
                if room.get("status") == "active":
                    raise
        return result

    def restore_sessions(
        self,
        room: Mapping[str, object],
    ) -> None:
        """Repair Rooms created before Session lifecycle coupling."""

        if room.get("status") != "active":
            return
        with self.turn_lock:
            for participant in room.get(
                "participants",
                [],
            ):
                if (
                    not isinstance(participant, Mapping)
                    or participant.get("status") != "active"
                ):
                    continue
                session = self.repair_session(
                    room,
                    participant,
                )
                if session.get("status") == "archived":
                    self.sessions.archive(
                        str(session["id"]),
                        archived=False,
                    )

    def add(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        if room.get("status") != "active":
            raise ValueError("agent room is archived")
        role = self.personas.resolve_active(
            payload.get("roleId"),
            payload.get("roleVersion") or "1",
        )
        required_mode = (
            "coordinator"
            if room.get(
                "roomKind",
                "collaboration",
            )
            == "collaboration"
            else "assistant"
        )
        if required_mode not in role.selectable_modes:
            raise ValueError(
                f"role {role.role_id}@{role.version} "
                "cannot join this room kind"
            )
        collaboration_role = normalize_collaboration_role(
            payload.get("collaborationRole")
            or "implementer"
        )
        session = self.create_session(
            _session_payload(
                room,
                role,
                mode=required_mode,
            )
        )["session"]
        try:
            participant = self.rooms.add_participant(
                room_id,
                session_id=str(session["id"]),
                role_id=role.role_id,
                role_version=role.version,
                display_name=role.display_name,
                collaboration_role=collaboration_role,
            )
        except Exception:
            self.sessions.delete(str(session["id"]))
            raise
        event = self.events.publish(
            room_id=room_id,
            event_type="participant_status",
            payload={
                "status": "participant_joined",
                "participantId": participant["id"],
                "displayName": participant["displayName"],
                "roleId": participant["roleId"],
                "joinSequence": room.get(
                    "lastEventSequence",
                    0,
                ),
            },
            participant_id=str(participant["id"]),
            source_session_id=str(
                participant["sessionId"]
            ),
            topic_id=str(
                room.get("activeTopicId") or ""
            ),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-participant-add.v1"
            ),
            "ok": True,
            "participant": participant,
            "room": self.rooms.get(room_id),
            "event": event,
        }

    def remove(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.restore_sessions(room)
        participant_id = _required_text(
            payload,
            "participantId",
        )
        participant = self.rooms.participant(
            participant_id
        )
        if participant.get("roomId") != room_id:
            raise ValueError(
                "participant does not belong to this Room"
            )
        session_id = str(
            participant.get("sessionId") or ""
        )
        session = self.sessions.get(session_id)
        active_session_ids = (
            self.active_runtime_session_ids()
        )
        with self.turn_lock:
            if self.session_is_busy(
                session_id,
                session,
                active_session_ids=active_session_ids,
            ):
                raise ValueError(
                    "wait for this participant's active "
                    "Room turn to finish"
                )
            self.sessions.archive(
                session_id,
                archived=True,
            )
            try:
                removed = self.rooms.remove_participant(
                    room_id,
                    participant_id,
                )
            except Exception:
                self.sessions.archive(
                    session_id,
                    archived=False,
                )
                raise
        room = self.rooms.get(room_id)
        event = self.events.publish(
            room_id=room_id,
            event_type="participant_status",
            payload={
                "status": "participant_removed",
                "participantId": participant_id,
                "displayName": removed["displayName"],
                "roleId": removed["roleId"],
            },
            participant_id=participant_id,
            source_session_id=session_id,
            topic_id=str(
                room.get("activeTopicId") or ""
            ),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-participant-remove.v1"
            ),
            "ok": True,
            "participant": removed,
            "room": self.rooms.get(room_id),
            "event": event,
        }

    def update_role(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.restore_sessions(room)
        participant_id = _required_text(
            payload,
            "participantId",
        )
        collaboration_role = _required_text(
            payload,
            "collaborationRole",
        )
        participant = self.rooms.participant(
            participant_id
        )
        if participant.get("roomId") != room_id:
            raise ValueError(
                "participant does not belong to this Room"
            )
        session_id = str(
            participant.get("sessionId") or ""
        )
        session = self.sessions.get(session_id)
        active_session_ids = (
            self.active_runtime_session_ids()
        )
        with self.turn_lock:
            if self.session_is_busy(
                session_id,
                session,
                active_session_ids=active_session_ids,
            ):
                raise ValueError(
                    "wait for this participant's active "
                    "Room turn to finish"
                )
            updated = self.rooms.update_participant_role(
                room_id,
                participant_id,
                collaboration_role,
            )
        room = self.rooms.get(room_id)
        event = self.events.publish(
            room_id=room_id,
            event_type="room_config_changed",
            payload={
                "status": "participant_role_updated",
                "participantId": participant_id,
                "displayName": updated["displayName"],
                "previousCollaborationRole": (
                    participant.get("collaborationRole")
                ),
                "collaborationRole": updated[
                    "collaborationRole"
                ],
            },
            participant_id=participant_id,
            source_session_id=session_id,
            topic_id=str(
                room.get("activeTopicId") or ""
            ),
        )
        return {
            "schemaVersion": (
                "rag-ime.agent-room-participant-update.v1"
            ),
            "ok": True,
            "participant": updated,
            "room": self.rooms.get(room_id),
            "event": event,
        }

    def repair_session(
        self,
        room: Mapping[str, object],
        participant: Mapping[str, object],
    ) -> dict[str, object]:
        old_session_id = str(
            participant.get("sessionId") or ""
        ).strip()
        try:
            session = self.sessions.get(old_session_id)
        except AgentSessionNotFound:
            session = None
        if session is not None:
            return self._ensure_working_policy(room, session)
        role = self.personas.resolve(
            participant.get("roleId"),
            participant.get("roleVersion") or "1",
        )
        mode = (
            "coordinator"
            if room.get(
                "roomKind",
                "collaboration",
            )
            == "collaboration"
            else "assistant"
        )
        created = self.create_session(
            _session_payload(room, role, mode=mode)
        )["session"]
        try:
            self.rooms.rebind_participant_session(
                str(room["id"]),
                str(participant["id"]),
                expected_session_id=old_session_id,
                session_id=str(created["id"]),
            )
        except Exception:
            self.sessions.delete(str(created["id"]))
            raise
        return created

    def _ensure_working_policy(
        self,
        room: Mapping[str, object],
        session: Mapping[str, object],
    ) -> dict[str, object]:
        """Keep Room responsibility separate from Agent capability."""

        mode = (
            "coordinator"
            if room.get("roomKind", "collaboration")
            == "collaboration"
            else "assistant"
        )
        workspace_roots = (
            list(room.get("workspaceRoots") or [])
            if mode == "coordinator"
            else []
        )
        execution_mode = normalize_execution_mode(
            room.get("executionMode"),
            default=(
                WORKSPACE_MANAGED_EXECUTION_MODE
                if room.get("roomKind", "collaboration") == "collaboration"
                else PER_ACTION_EXECUTION_MODE
            ),
        )
        tool_profile = canonical_tool_profile(
            session.get("toolProfileVersion"),
            execution_mode=execution_mode,
        )
        if (
            session.get("mode") == mode
            and session.get("toolProfileVersion")
            == tool_profile
            and session.get("executionMode") == execution_mode
            and session.get("toolAllowlistMode") == "profile"
            and list(session.get("workspaceRoots") or [])
            == workspace_roots
            and (
                execution_mode
                not in {
                    WORKSPACE_MANAGED_EXECUTION_MODE,
                    FULL_TRUST_EXECUTION_MODE,
                }
                or session.get("workspaceScopeGranted") is True
            )
        ):
            return dict(session)
        return self.sessions.set_runtime_policy(
            str(session["id"]),
            mode=mode,
            tool_profile_version=tool_profile,
            execution_mode=execution_mode,
            grant_workspace_scope=execution_mode
            in {
                WORKSPACE_MANAGED_EXECUTION_MODE,
                FULL_TRUST_EXECUTION_MODE,
            },
            allowed_tools=None,
            workspace_roots=workspace_roots,
        )

    def active_runtime_session_ids(self) -> set[str]:
        return {
            str(value)
            for value in self.runtime_status().get(
                "activeSessionIds",
                [],
            )
            if str(value or "").strip()
        }

    def session_is_busy(
        self,
        session_id: str,
        session: Mapping[str, object],
        *,
        active_session_ids: set[str],
    ) -> bool:
        return (
            session.get("status") == "busy"
            or session_id in active_session_ids
            or session_id in self.pending_turns
            or session_id in self.user_priority_sessions
        )


def _session_payload(
    room: Mapping[str, object],
    role: object,
    *,
    mode: str,
) -> dict[str, object]:
    execution_mode = normalize_execution_mode(
        room.get("executionMode"),
        default=(
            WORKSPACE_MANAGED_EXECUTION_MODE
            if room.get("roomKind", "collaboration") == "collaboration"
            else PER_ACTION_EXECUTION_MODE
        ),
    )
    return {
        "title": (
            f"{room['title']} · "
            f"{getattr(role, 'display_name')}"
        ),
        "mode": mode,
        "roleId": getattr(role, "role_id"),
        "roleVersion": getattr(role, "version"),
        "toolProfileVersion": canonical_tool_profile(
            CONTROL_CENTER_TOOL_PROFILE,
            execution_mode=execution_mode,
        ),
        "executionMode": execution_mode,
        "_internalWorkspaceScopeGrant": execution_mode
        in {
            WORKSPACE_MANAGED_EXECUTION_MODE,
            FULL_TRUST_EXECUTION_MODE,
        },
        "workspaceRoots": list(
            room.get("workspaceRoots") or []
        ),
    }


def _required_text(
    payload: Mapping[str, object],
    key: str,
) -> str:
    value = " ".join(
        str(payload.get(key) or "").split()
    )
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value
