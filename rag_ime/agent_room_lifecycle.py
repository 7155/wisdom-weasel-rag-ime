from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .agent_personas import AgentPersonaStore
from .agent_roles import PersonaManifest
from .agent_room_participants import (
    RoomParticipantLifecycleService,
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


@dataclass(frozen=True)
class RoomParticipantPlan:
    persona: PersonaManifest
    collaboration_role: str


@dataclass(frozen=True)
class RoomCreationPlan:
    room_kind: str
    title: str
    routing_policy: str
    moderator_ordinal: int
    workspace_roots: tuple[str, ...]
    participants: tuple[RoomParticipantPlan, ...]


class RoomLifecycleService:
    """Own Room creation, configuration, archival, and deletion."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        sessions: AgentSessionStore,
        personas: AgentPersonaStore,
        events: AgentRoomEventHub,
        participants: RoomParticipantLifecycleService,
        create_session: Callable[
            [Mapping[str, object]],
            dict[str, object],
        ],
        delete_session: Callable[
            [str],
            dict[str, object],
        ],
    ) -> None:
        self.rooms = rooms
        self.sessions = sessions
        self.personas = personas
        self.events = events
        self.participants = participants
        self.create_session = create_session
        self.delete_session = delete_session

    def list_rooms(
        self,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        value = dict(payload or {})
        return {
            "schemaVersion": "rag-ime.agent-room-list.v1",
            "ok": True,
            "items": self.rooms.list(
                include_archived=_bool(
                    value.get("includeArchived")
                ),
                limit=_integer(
                    value.get("limit"),
                    default=100,
                    minimum=1,
                    maximum=200,
                ),
            ),
        }

    def get_room(self, room_id: str) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.participants.restore_sessions(room)
        return {
            "schemaVersion": "rag-ime.agent-room-get.v1",
            "ok": True,
            "room": self.rooms.get(room_id),
        }

    def snapshot(self, room_id: str) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.participants.restore_sessions(room)
        return self.rooms.snapshot(room_id)

    def update(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        if not payload:
            raise ValueError(
                "agent room update requires at least one field"
            )
        if "archived" in payload and len(payload) > 1:
            raise ValueError(
                "archive state must be updated separately "
                "from room configuration"
            )
        if set(payload) == {"archived"}:
            archived = _bool(payload.get("archived"))
            room = self.rooms.archive(
                room_id,
                archived=archived,
            )
            if not archived:
                self.participants.restore_sessions(room)
            event = self.events.publish(
                room_id=room_id,
                event_type="participant_status",
                payload={
                    "status": (
                        "room_archived"
                        if room["status"] == "archived"
                        else "room_restored"
                    )
                },
            )
        else:
            room = self.rooms.update_config(
                room_id,
                payload,
            )
            event = self.events.publish(
                room_id=room_id,
                event_type="room_config_changed",
                payload={
                    "status": "room_config_updated",
                    "changedFields": sorted(payload),
                    "configRevision": room[
                        "configRevision"
                    ],
                    "routingPolicy": room[
                        "routingPolicy"
                    ],
                    "roomKind": room["roomKind"],
                },
                topic_id=str(
                    room.get("activeTopicId") or ""
                ),
            )
        return {
            "schemaVersion": "rag-ime.agent-room-update.v1",
            "ok": True,
            "room": self.rooms.get(room_id),
            "event": event,
        }

    def create(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        plan = self._creation_plan(payload)
        created_session_ids: list[str] = []
        participants: list[dict[str, object]] = []
        try:
            for participant_plan in plan.participants:
                role = participant_plan.persona
                session = self.create_session(
                    _participant_session_payload(
                        plan,
                        role,
                    )
                )["session"]
                created_session_ids.append(
                    str(session["id"])
                )
                participants.append(
                    {
                        "sessionId": session["id"],
                        "roleId": role.role_id,
                        "roleVersion": role.version,
                        "displayName": role.display_name,
                        "collaborationRole": (
                            participant_plan.collaboration_role
                        ),
                    }
                )
            room = self.rooms.create(
                title=plan.title,
                routing_policy=plan.routing_policy,
                participants=participants,
                workspace_roots=list(
                    plan.workspace_roots
                ),
                moderator_ordinal=(
                    plan.moderator_ordinal
                ),
                room_kind=plan.room_kind,
                avatar=str(
                    payload.get("avatar") or "members"
                ),
                description=str(
                    payload.get("description") or ""
                ),
                scenario_prompt=str(
                    payload.get("scenarioPrompt") or ""
                ),
                routing_config=(
                    payload.get("routingConfig")
                    if isinstance(
                        payload.get("routingConfig"),
                        Mapping,
                    )
                    else None
                ),
            )
        except Exception:
            for session_id in reversed(
                created_session_ids
            ):
                try:
                    self.sessions.delete(session_id)
                except Exception:
                    pass
            raise

        event = self.events.publish(
            room_id=str(room["id"]),
            event_type="participant_status",
            payload={
                "status": "room_created",
                "routingPolicy": plan.routing_policy,
                "roomKind": plan.room_kind,
                "participants": [
                    {
                        "participantId": item["id"],
                        "displayName": item[
                            "displayName"
                        ],
                        "roleId": item["roleId"],
                        "collaborationRole": item[
                            "collaborationRole"
                        ],
                    }
                    for item in room["participants"]
                    if isinstance(item, Mapping)
                ],
            },
        )
        return {
            "schemaVersion": "rag-ime.agent-room-create.v1",
            "ok": True,
            "room": self.rooms.get(str(room["id"])),
            "event": event,
        }

    def delete(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        if str(payload.get("confirmTitle") or "") != str(
            room.get("title") or ""
        ):
            raise ValueError(
                "confirmTitle must exactly match the Room title"
            )
        active_session_ids = (
            self.participants.active_runtime_session_ids()
        )
        with self.participants.turn_lock:
            for session in (
                self.participants.participant_sessions(
                    room
                )
            ):
                session_id = str(
                    session.get("id") or ""
                )
                if self.participants.session_is_busy(
                    session_id,
                    session,
                    active_session_ids=active_session_ids,
                ):
                    raise ValueError(
                        "wait for all Room participant turns "
                        "to finish before deleting it"
                    )
            deleted = self.rooms.delete(room_id)
        cleanup: list[dict[str, object]] = []
        for session_id in deleted["sessionIds"]:
            try:
                cleanup.append(
                    self.delete_session(str(session_id))
                )
            except AgentSessionNotFound:
                cleanup.append(
                    {
                        "schemaVersion": (
                            "rag-ime.agent-session-delete.v1"
                        ),
                        "ok": True,
                        "sessionId": str(session_id),
                        "alreadyMissing": True,
                        "sessionFileDeleted": False,
                        "mediaFilesDeleted": 0,
                    }
                )
        return {
            "schemaVersion": "rag-ime.agent-room-delete.v1",
            "ok": True,
            "roomId": room_id,
            "deletedSessionIds": list(
                deleted["sessionIds"]
            ),
            "sessionCleanup": cleanup,
        }

    def _creation_plan(
        self,
        payload: Mapping[str, object],
    ) -> RoomCreationPlan:
        room_kind = str(
            payload.get("roomKind") or "collaboration"
        ).strip().lower()
        if room_kind not in {
            "collaboration",
            "roleplay",
        }:
            raise ValueError(
                "roomKind must be collaboration or roleplay"
            )
        raw_participants = payload.get("participants")
        if not isinstance(raw_participants, list):
            raise ValueError(
                "room participants must be an array"
            )
        if not 2 <= len(raw_participants) <= 4:
            raise ValueError(
                "agent room requires between 2 and 4 "
                "participants"
            )
        workspace_roots = _workspace_roots(
            payload,
            room_kind=room_kind,
        )
        routing_policy = str(
            payload.get("routingPolicy") or "natural"
        )
        requested_moderator_role_id = str(
            payload.get("moderatorRoleId") or ""
        ).strip()
        participants = self._participant_plans(
            raw_participants,
            room_kind=room_kind,
            coordinator_role_id=(
                requested_moderator_role_id
                if routing_policy == "moderator"
                else ""
            ),
        )
        roles = tuple(
            item.persona for item in participants
        )
        moderator_ordinal = _moderator_ordinal(
            roles,
            routing_policy=routing_policy,
            requested_role_id=requested_moderator_role_id,
        )
        return RoomCreationPlan(
            room_kind=room_kind,
            title=" ".join(
                str(
                    payload.get("title") or "新群聊"
                ).split()
            )[:120],
            routing_policy=routing_policy,
            moderator_ordinal=moderator_ordinal,
            workspace_roots=workspace_roots,
            participants=participants,
        )

    def _participant_plans(
        self,
        raw_participants: list[object],
        *,
        room_kind: str,
        coordinator_role_id: str,
    ) -> tuple[RoomParticipantPlan, ...]:
        participants: list[RoomParticipantPlan] = []
        seen: set[tuple[str, str]] = set()
        required_mode = (
            "coordinator"
            if room_kind == "collaboration"
            else "assistant"
        )
        for index, raw in enumerate(raw_participants):
            if not isinstance(raw, Mapping):
                raise ValueError(
                    "each room participant must be an object"
                )
            role = self.personas.resolve_active(
                raw.get("roleId"),
                raw.get("roleVersion") or "1",
            )
            if required_mode not in role.selectable_modes:
                raise ValueError(
                    f"role {role.role_id}@{role.version} "
                    "cannot join this room kind"
                )
            key = (role.role_id, role.version)
            if key in seen:
                raise ValueError(
                    "room participant roles must be unique "
                    "in the first room version"
                )
            seen.add(key)
            default_role = (
                "coordinator"
                if room_kind == "collaboration"
                and (
                    role.role_id == coordinator_role_id
                    or not coordinator_role_id
                    and index == 0
                )
                else "implementer"
            )
            participants.append(
                RoomParticipantPlan(
                    persona=role,
                    collaboration_role=(
                        normalize_collaboration_role(
                            raw.get("collaborationRole")
                            or default_role
                        )
                    ),
                )
            )
        return tuple(participants)


def _workspace_roots(
    payload: Mapping[str, object],
    *,
    room_kind: str,
) -> tuple[str, ...]:
    raw = payload.get("workspaceRoots")
    if not isinstance(raw, list):
        raise ValueError("workspaceRoots must be an array")
    roots = tuple(
        str(value or "").strip()
        for value in raw
        if str(value or "").strip()
    )
    if room_kind == "collaboration" and not roots:
        raise ValueError(
            "agent room requires an authorized workspace"
        )
    if len(roots) > 4:
        raise ValueError(
            "agent room accepts at most four workspace roots"
        )
    return roots


def _moderator_ordinal(
    roles: tuple[PersonaManifest, ...],
    *,
    routing_policy: str,
    requested_role_id: str,
) -> int:
    if routing_policy != "moderator":
        return 0
    moderator_role_id = requested_role_id or next(
        (
            role.role_id
            for role in roles
            if role.role_id == "companion-future-v1"
        ),
        roles[0].role_id,
    )
    matches = [
        index
        for index, role in enumerate(roles)
        if role.role_id == moderator_role_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "moderatorRoleId must identify one room "
            "participant"
        )
    return matches[0]


def _participant_session_payload(
    plan: RoomCreationPlan,
    role: PersonaManifest,
) -> dict[str, object]:
    return {
        "title": f"{plan.title} · {role.display_name}",
        "mode": (
            "coordinator"
            if plan.room_kind == "collaboration"
            else "assistant"
        ),
        "roleId": role.role_id,
        "roleVersion": role.version,
        "toolProfileVersion": (
            role.defaults.tool_profile_version
        ),
        "workspaceRoots": list(plan.workspace_roots),
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
