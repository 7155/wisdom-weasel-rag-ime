from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .agent_personas import AgentPersonaStore
from .agent_execution_policy import (
    FULL_TRUST_EXECUTION_MODE,
    PER_ACTION_EXECUTION_MODE,
    WORKSPACE_MANAGED_EXECUTION_MODE,
    canonical_tool_profile,
    unrestricted_workspace_policy_active,
)
from .agent_rooms import (
    AgentRoomEventHub,
    AgentRoomStore,
    normalize_collaboration_role,
)
from .agent_room_workspace_ledger import RoomWorkspaceLedgerStore
from .agent_sessions import (
    AgentSessionNotFound,
    AgentSessionStore,
)
from .agent_tool_ids import (
    CONTROL_CENTER_TOOL_PROFILE,
    DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
    FULL_ACCESS_TOOL_PROFILE,
)
from .room_permission_policy import (
    normalize_room_permission_policy,
    resolve_room_permission_policy,
)
from .agent_workspace_roots import system_wide_workspace_roots


@dataclass(frozen=True)
class RoomParticipantPolicy:
    """The canonical Session policy projected from a Room configuration."""

    mode: str
    execution_mode: str
    tool_profile_version: str
    grant_workspace_scope: bool
    project_context_enabled: bool
    pi_skills_enabled: bool | None
    codex_skills_enabled: bool | None
    workspace_roots: tuple[str, ...]

    @property
    def unrestricted(self) -> bool:
        return unrestricted_workspace_policy_active(
            {
                "toolProfileVersion": self.tool_profile_version,
                "executionMode": self.execution_mode,
            }
        )

    def create_fields(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "toolProfileVersion": self.tool_profile_version,
            "executionMode": self.execution_mode,
            "_internalWorkspaceScopeGrant": self.grant_workspace_scope,
            "projectContextEnabled": self.project_context_enabled,
            "piSkillsEnabled": bool(self.pi_skills_enabled),
            "codexSkillsEnabled": bool(self.codex_skills_enabled),
            "workspaceRoots": list(self.workspace_roots),
        }

    def runtime_kwargs(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "tool_profile_version": self.tool_profile_version,
            "execution_mode": self.execution_mode,
            "grant_workspace_scope": self.grant_workspace_scope,
            "allowed_tools": None,
            "project_context_enabled": self.project_context_enabled,
            "pi_skills_enabled": self.pi_skills_enabled,
            "codex_skills_enabled": self.codex_skills_enabled,
            "workspace_roots": list(self.workspace_roots),
        }


def project_room_participant_policy(
    room: Mapping[str, object],
    *,
    mode: str | None = None,
    execution_mode: str | None = None,
    permission_policy: Mapping[str, object] | None = None,
    workspace_roots: Iterable[object] | None = None,
) -> RoomParticipantPolicy:
    """Project one Room permission layer into the participant Session policy."""

    room_kind = str(room.get("roomKind") or "collaboration")
    participant_mode = mode or (
        "coordinator"
        if room_kind == "collaboration"
        else "assistant"
    )
    configured_policy = (
        permission_policy
        if permission_policy is not None
        else room.get("permissionPolicy")
    )
    normalized_policy = normalize_room_permission_policy(
        configured_policy,
        room_kind=room_kind,
        current=room,
        legacy_execution_mode=(
            room.get("executionMode")
            if configured_policy is None
            else None
        ),
    )
    if execution_mode is not None:
        normalized_policy = normalize_room_permission_policy(
            {
                **normalized_policy,
                "room": {"executionMode": execution_mode},
            },
            room_kind=room_kind,
        )
    effective_policy = resolve_room_permission_policy(normalized_policy)
    normalized_execution_mode = effective_policy["partner"]["executionMode"]
    if room_kind == "collaboration":
        if normalized_execution_mode == PER_ACTION_EXECUTION_MODE:
            profile = FULL_ACCESS_TOOL_PROFILE
        elif normalized_execution_mode == FULL_TRUST_EXECUTION_MODE:
            profile = DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
        else:
            profile = canonical_tool_profile(
                CONTROL_CENTER_TOOL_PROFILE,
                execution_mode=normalized_execution_mode,
            )
    else:
        profile = canonical_tool_profile(
            CONTROL_CENTER_TOOL_PROFILE,
            execution_mode=normalized_execution_mode,
        )
    projected = {
        "toolProfileVersion": profile,
        "executionMode": normalized_execution_mode,
    }
    unrestricted = unrestricted_workspace_policy_active(projected)
    raw_roots = [
        str(value).strip()
        for value in (
            room.get("workspaceRoots")
            if workspace_roots is None
            else workspace_roots
        )
        or []
        if str(value).strip()
    ]
    roots = (
        list(system_wide_workspace_roots(raw_roots))
        if unrestricted and participant_mode == "coordinator"
        else raw_roots
        if participant_mode == "coordinator"
        else []
    )
    return RoomParticipantPolicy(
        mode=participant_mode,
        execution_mode=normalized_execution_mode,
        tool_profile_version=profile,
        grant_workspace_scope=normalized_execution_mode
        in {
            WORKSPACE_MANAGED_EXECUTION_MODE,
            FULL_TRUST_EXECUTION_MODE,
        },
        project_context_enabled=bool(roots),
        pi_skills_enabled=True if unrestricted else None,
        codex_skills_enabled=True if unrestricted else None,
        workspace_roots=tuple(roots),
    )



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
        release_room_work: Callable[
            [str, str, str, str],
            list[dict[str, object]],
        ] | None = None,
        turn_lock: RLock,
        pending_turns: Mapping[str, str],
        user_priority_sessions: set[str],
    ) -> None:
        self.rooms = rooms
        self.sessions = sessions
        self.workspace_ledger = RoomWorkspaceLedgerStore(sessions.db_path)
        self.personas = personas
        self.events = events
        self.create_session = create_session
        self.runtime_status = runtime_status
        self.release_room_work = release_room_work
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
            active_session_ids = self.active_runtime_session_ids()
            for participant in room.get(
                "participants",
                [],
            ):
                if (
                    not isinstance(participant, Mapping)
                    or participant.get("status") != "active"
                ):
                    continue
                session_id = str(
                    participant.get("sessionId") or ""
                ).strip()
                try:
                    current = self.sessions.get(session_id)
                except AgentSessionNotFound:
                    current = None
                # A running Room Task may hold a narrower, isolated worktree
                # lease than the Room's base workspace.  Progress polling is
                # not allowed to replace that live authority with the default
                # participant policy.  Terminal settlement restores the base
                # policy through the workspace coordinator.
                if current is not None and self.session_is_busy(
                    session_id,
                    current,
                    active_session_ids=active_session_ids,
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
            or "implementer",
            assignable_only=True,
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
        actor_id = str(payload.get("actorParticipantId") or "").strip()
        released_work: list[dict[str, object]] = []
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
            if not actor_id and self.release_room_work is not None:
                actor_id = next(
                    (
                        str(value.get("id") or "")
                        for value in room.get("participants", [])
                        if isinstance(value, Mapping)
                        and str(value.get("status") or "") == "active"
                        and str(value.get("id") or "") != participant_id
                        and str(value.get("collaborationRole") or "") == "coordinator"
                    ),
                    "",
                )
                if not actor_id:
                    actor_id = next(
                        (
                            str(value.get("id") or "")
                            for value in room.get("participants", [])
                            if isinstance(value, Mapping)
                            and str(value.get("status") or "") == "active"
                            and str(value.get("id") or "") != participant_id
                        ),
                        "",
                    )
            if actor_id:
                actor = self.rooms.participant(actor_id)
                if (
                    str(actor.get("roomId") or "") != room_id
                    or str(actor.get("status") or "") != "active"
                ):
                    raise ValueError("actor must be an active participant in this Room")
                if actor_id == participant_id:
                    raise ValueError("actor cannot remove itself from this Room")
                if self.release_room_work is None:
                    raise ValueError("Room work release is unavailable")
                released_work = self.release_room_work(
                    room_id,
                    participant_id,
                    actor_id,
                    str(payload.get("reason") or ""),
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
            "releasedWorkItems": released_work,
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

        active_binding = self.workspace_ledger.active_binding_for_session(
            str(session["id"])
        )
        if active_binding is not None:
            expected_roots = [
                str(
                    Path(str(active_binding["workspaceRoot"]))
                    .expanduser()
                    .resolve(strict=False)
                )
            ]
            actual_roots = [
                str(Path(str(value)).expanduser().resolve(strict=False))
                for value in session.get("workspaceRoots") or []
                if str(value).strip()
            ]
            if actual_roots != expected_roots:
                raise RuntimeError(
                    "active isolated workspace binding does not match its Session lease"
                )
            return dict(session)

        policy = project_room_participant_policy(room)
        expected_roots = list(policy.workspace_roots)
        scope_required = (
            policy.unrestricted
            or policy.execution_mode
            in {
                WORKSPACE_MANAGED_EXECUTION_MODE,
                FULL_TRUST_EXECUTION_MODE,
            }
        )
        if (
            session.get("mode") == policy.mode
            and session.get("toolProfileVersion")
            == policy.tool_profile_version
            and session.get("executionMode") == policy.execution_mode
            and session.get("toolAllowlistMode") == "profile"
            and list(session.get("allowedTools") or []) == []
            and list(session.get("workspaceRoots") or [])
            == expected_roots
            and bool(session.get("projectContextEnabled"))
            == policy.project_context_enabled
            and (
                policy.pi_skills_enabled is None
                or session.get("piSkillsEnabled")
                == policy.pi_skills_enabled
            )
            and (
                policy.codex_skills_enabled is None
                or session.get("codexSkillsEnabled")
                == policy.codex_skills_enabled
            )
            and (
                not scope_required
                or session.get("workspaceScopeGranted") is True
            )
        ):
            return dict(session)
        return self.sessions.set_runtime_policy(
            str(session["id"]),
            **policy.runtime_kwargs(),
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
    policy = project_room_participant_policy(
        room,
        mode=mode,
    )
    return {
        "title": (
            f"{room['title']} · "
            f"{getattr(role, 'display_name')}"
        ),
        "_modelRoute": "roomCoordinator",
        "roleId": getattr(role, "role_id"),
        "roleVersion": getattr(role, "version"),
        **policy.create_fields(),
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
