from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence

from .agent_personas import AgentPersonaStore
from .agent_role_book import AgentRoleBookStore
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_context import RoomContextLedgerStore
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel_contracts import (
    DEFAULT_RUNTIME_PROFILE_REVISION,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_POST_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_public_timeline import RoomPublicTimelineProjector
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_work import AgentRoomWorkStore
from .agent_rooms import AgentRoomStore
from .agent_sessions import AgentSessionStore
from .agent_session_mode_gate import AgentSessionModeGate


DEFAULT_ROOT_BUDGET = 32
DEFAULT_MAX_HOPS = 6
DEFAULT_MAX_DEPTH = 3


class RoomApplicationService:
    """Product-facing Room commands backed by the canonical Kernel.

    This layer owns user intent, deterministic identities, immutable requirement
    capture, routing, and atomic fan-out. Runtime delivery remains exclusively
    owned by ``RoomKernelWorker``.
    """

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        sessions: AgentSessionStore,
        personas: AgentPersonaStore,
        role_books: AgentRoleBookStore,
        work_items: AgentRoomWorkStore,
        kernel: RoomKernelStore,
        commands: KernelCommandBus,
        projection: RoomKernelProjection,
        context: RoomContextLedgerStore,
        requirements: RequirementGovernanceStore,
        capabilities: RoomCapabilityManifestStore,
        public_timeline: RoomPublicTimelineProjector,
        session_mode_gate: AgentSessionModeGate,
        wake_worker: Callable[[], None],
        restore_participant_sessions: Callable[[Mapping[str, object]], None],
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.rooms = rooms
        self.sessions = sessions
        self.personas = personas
        self.role_books = role_books
        self.work_items = work_items
        self.kernel = kernel
        self.commands = commands
        self.projection = projection
        self.context = context
        self.requirements = requirements
        self.capabilities = capabilities
        self.public_timeline = public_timeline
        self.session_mode_gate = session_mode_gate
        self.wake_worker = wake_worker
        self.restore_participant_sessions = restore_participant_sessions
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def post_message(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        active_session_ids = [
            str(value["sessionId"])
            for value in room.get("participants", [])
            if (
                isinstance(value, Mapping)
                and value.get("status") == "active"
                and str(value.get("sessionId") or "").strip()
            )
        ]
        with self.session_mode_gate.claim_room(active_session_ids):
            return self._post_message_claimed(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
            )

    def _post_message_claimed(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
    ) -> dict[str, object]:
        if self.kernel.mode not in {"cohort", "kernel_only"}:
            raise RoomKernelFenceError("canonical Room ingress requires a managed Kernel")
        if not work_item_id:
            raise RoomKernelFenceError(
                "managed Room execution requires a confirmed WorkItem"
            )

        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        work_item, authoritative_participant_id = self._work_item_owner(
            room_id,
            work_item_id,
        )
        decisions = self.rooms.plan_routes(
            room_id,
            message,
            requested_participant_ids=requested_participant_ids,
            profiles=self._routing_profiles(room),
            authoritative_participant_id=authoritative_participant_id,
        )
        if work_item is not None:
            for decision in decisions:
                decision["workItemId"] = work_item_id
                decision["workItemState"] = str(work_item["state"])

        targets = [
            self.rooms.participant(str(decision["targetParticipantId"]))
            for decision in decisions
        ]
        self._assert_targets_available(targets)
        timestamp = self.clock_ms()
        identity = _message_identity(room_id, client_message_id)
        root_id = f"room-root:{identity}"
        task_id = f"room-task:{identity}"
        anchor_id = f"requirement-anchor:{identity}"
        post_id = f"room-post:user:{identity}"
        owner_participant_id = _root_owner(room, targets)
        requirement_item_id = (
            f"work-item:{work_item['id']}:revision:{work_item['revision']}"
            if work_item is not None
            else f"requirement:{identity}"
        )
        task_objective = (
            str(work_item.get("objective") or "").strip()
            if work_item is not None
            else message
        )
        task_expected_output = (
            str(work_item.get("expectedOutput") or "").strip()
            if work_item is not None
            else ""
        )
        if not task_expected_output:
            task_expected_output = (
                "以可验证的 Room Post、结构化交接、等待或阻塞之一完成本轮任务。"
            )
        acceptance_criteria = _work_item_acceptance_criteria(
            identity,
            work_item,
        )
        acceptance_ids = tuple(
            criterion_id for criterion_id, _statement in acceptance_criteria
        )
        original_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
        anchor_ref = f"{anchor_id}@sha256:{original_digest}"
        root = {
            "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
            "rootId": root_id,
            "roomId": room_id,
            "generation": 0,
            "state": "running",
            "owner": owner_participant_id,
            "requirementAnchorRef": anchor_ref,
            "createdByActorRef": "user:local",
            "terminalReceiptId": None,
            "activeProfileRef": "standard-room",
            "budgetPolicyRef": "room-budget:interactive-v1",
            "createdAtMs": timestamp,
        }
        task = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": task_id,
            "rootId": root_id,
            "parentTaskId": None,
            "ownerParticipantId": owner_participant_id,
            "assigneeParticipantId": (
                str(targets[0]["id"]) if len(targets) == 1 else None
            ),
            "objective": task_objective,
            "expectedOutput": task_expected_output,
            "requirementItemIds": [requirement_item_id],
            "acceptanceCriterionIds": list(acceptance_ids),
            "revision": 0,
            "state": "active",
        }
        created = self.commands.create_root_task(
            root,
            task,
            budget=DEFAULT_ROOT_BUDGET,
            max_hops=DEFAULT_MAX_HOPS,
            max_depth=DEFAULT_MAX_DEPTH,
            acceptance_criteria=acceptance_ids,
            now_ms=timestamp,
        )

        work_claimed = False
        timeline_events: list[dict[str, object]] = []
        previous_accepted_turn_id = ""
        try:
            anchor, _ = self.requirements.append_anchor(
                anchor_id=anchor_id,
                root_id=root_id,
                original_content=message,
                created_by="user:local",
                provenance={
                    "surface": "room",
                    "roomId": room_id,
                    "clientMessageId": client_message_id,
                },
                created_at_ms=timestamp,
            )
            requirement_catalog, _ = self.requirements.revise_catalog(
                catalog_revision_id=(
                    f"requirement-catalog:{identity}:1"
                ),
                root_id=root_id,
                expected_current_revision=0,
                anchor_refs=[anchor_id],
                items=[
                    {
                        "itemId": requirement_item_id,
                        "kind": "explicit_user_requirement",
                        "statement": message,
                        "origin": "room_user_message",
                        "state": "active",
                        "sourceSpans": [
                            {
                                "anchorId": anchor_id,
                                "startByte": 0,
                                "endByte": len(
                                    message.encode("utf-8")
                                ),
                            }
                        ],
                        "confirmation": "captured_from_user",
                    }
                ],
                acceptance_criteria=[
                    {
                        "criterionId": criterion_id,
                        "itemId": requirement_item_id,
                        "acceptanceCriterionFullNameZh": (
                            f"用户验收条件 {ordinal + 1}"
                        ),
                        "criterionKind": "user_journey",
                        "expectedReceiptTypes": ["evidence"],
                        "statement": statement,
                    }
                    for ordinal, (
                        criterion_id,
                        statement,
                    ) in enumerate(acceptance_criteria)
                ],
                change_reason="从本次 Room 用户请求建立初始需求目录",
                provenance={
                    "surface": "room",
                    "clientMessageId": client_message_id,
                    "derivedCatalog": True,
                    "originalBytesRemainInAnchor": True,
                },
                created_by="room-ingress",
                created_at_ms=timestamp,
            )
            self.context.append_entry(
                root_id=root_id,
                room_id=room_id,
                generation=0,
                entry_kind="requirement_anchor",
                source_ref=anchor_id,
                dedupe_key=f"requirement-anchor:{anchor_id}",
                content=message,
                created_at_ms=timestamp,
            )
            if work_item is not None:
                self.context.append_entry(
                    root_id=root_id,
                    room_id=room_id,
                    generation=0,
                    entry_kind="work_item",
                    source_ref=str(work_item["id"]),
                    dedupe_key=(
                        f"work-item:{work_item['id']}:revision:"
                        f"{work_item['revision']}"
                    ),
                    content=_work_item_context(
                        work_item,
                        acceptance_criteria=acceptance_criteria,
                    ),
                    created_at_ms=timestamp,
                )
            user_post = {
                "schemaVersion": ROOM_POST_SCHEMA_VERSION,
                "postId": post_id,
                "roomId": room_id,
                "rootId": root_id,
                "generation": 0,
                "taskId": task_id,
                "authorActorRef": "user:local",
                "kind": "request",
                "visibility": "room",
                "content": message,
                "idempotencyKey": f"user-message:{identity}",
                "publicationSource": {
                    "kind": "user",
                    "ref": client_message_id or root_id,
                },
                "createdAtMs": timestamp,
            }
            self.projection.publish_post(user_post)
            self.context.publish_post(user_post)

            if work_item is not None:
                previous_accepted_turn_id = str(
                    work_item.get("acceptedTurnId") or ""
                )
                work_item = self.work_items.claim_dispatch(
                    str(work_item["id"]),
                    room_id=room_id,
                    owner_participant_id=str(targets[0]["id"]),
                    assignment_key=str(work_item["assignmentKey"]),
                    previous_accepted_turn_id=previous_accepted_turn_id,
                    room_turn_id=root_id,
                )
                work_claimed = True

            envelopes = [
                self._dispatch_envelope(
                    identity=identity,
                    root_id=root_id,
                    task_id=task_id,
                    post_id=post_id,
                    target=target,
                    ordinal=ordinal,
                )
                for ordinal, target in enumerate(targets)
            ]
            queued = self.commands.dispatch_many(envelopes, now_ms=timestamp)
            dispatch_results = []
            for decision, target, (dispatch, was_created) in zip(
                decisions,
                targets,
                queued,
                strict=True,
            ):
                decision.update(
                    rootId=root_id,
                    taskId=task_id,
                    dispatchId=dispatch["dispatchId"],
                    targetSessionId=target["sessionId"],
                )
                self.rooms.commit_route(room_id, decision, updated_at_ms=timestamp)
                dispatch_results.append(
                    {
                        "participantId": target["id"],
                        "sessionId": target["sessionId"],
                        "dispatchId": dispatch["dispatchId"],
                        "accepted": True,
                        "state": "queued",
                        "created": was_created,
                        "sessionTurnId": "",
                        "error": "",
                    }
                )
            timeline_events = self.public_timeline.publish_ingress(
                room=room,
                post=user_post,
                client_message_id=client_message_id,
                route_decisions=decisions,
                dispatches=dispatch_results,
            )
        except Exception as exc:
            if work_claimed and work_item is not None:
                try:
                    work_item = self.work_items.fail_dispatch(
                        str(work_item["id"]),
                        room_id=room_id,
                        actor_participant_id=str(targets[0]["id"]),
                        room_turn_id=root_id,
                        previous_accepted_turn_id=previous_accepted_turn_id,
                        reason=_public_error(exc),
                    )
                except Exception:
                    pass
            try:
                self.commands.cancel_root(root_id)
            except Exception:
                pass
            raise

        self.projection.sync_room(room_id, now_ms=timestamp)
        self.wake_worker()
        primary = 0
        response: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": targets[primary],
            "participants": targets,
            "routeDecision": decisions[primary],
            "routeDecisions": decisions,
            "dispatches": dispatch_results,
            "topicId": str(room.get("activeTopicId") or ""),
            "sessionTurnId": "",
            "root": created["root"],
            "task": created["task"],
            "post": user_post,
            "requirementAnchor": anchor,
            "requirementCatalog": requirement_catalog,
            "timelineEvents": timeline_events,
        }
        if work_item is not None:
            response["workItem"] = work_item
        return response

    def _work_item_owner(
        self,
        room_id: str,
        work_item_id: str,
    ) -> tuple[dict[str, object] | None, str]:
        if not work_item_id:
            raise RoomKernelFenceError(
                "managed Room execution requires a confirmed WorkItem"
            )
        return self.work_items.authoritative_owner(work_item_id, room_id=room_id)

    def _routing_profiles(
        self,
        room: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        profiles: dict[str, dict[str, object]] = {}
        for value in room.get("participants", []):
            if not isinstance(value, Mapping) or value.get("status") != "active":
                continue
            role = self.personas.resolve(
                value.get("roleId"),
                value.get("roleVersion") or "1",
            )
            session = self.sessions.get(str(value["sessionId"]))
            revision_id = str(session.get("roleBookRevisionId") or "")
            profile: Mapping[str, object] = {}
            if revision_id:
                try:
                    profile = self.role_books.routing_profile(
                        role.role_id,
                        role.version,
                        revision_id,
                    )
                except (ValueError, RuntimeError):
                    profile = {}
            capabilities = _texts(profile.get("capabilities"))
            recent_work = _texts(profile.get("recentWork"))
            profiles[str(value["id"])] = {
                "tagline": role.tagline,
                "summary": " ".join(
                    (role.summary, *capabilities[:4], *recent_work[:3])
                ),
                "traits": list(role.traits),
                "routingTags": [
                    *role.traits,
                    *capabilities[:8],
                    *recent_work[:4],
                ],
                # No revision means zero Role Book contribution. Do not inject a
                # warning paragraph merely to explain that nothing was loaded.
                "roleBookRevisionId": revision_id,
            }
        return profiles

    def _assert_targets_available(
        self,
        targets: Sequence[Mapping[str, object]],
    ) -> None:
        session_ids = [str(target["sessionId"]) for target in targets]
        if len(session_ids) != len(set(session_ids)):
            raise RoomKernelFenceError(
                "Room routing produced duplicate participant Sessions"
            )
        for target, session_id in zip(targets, session_ids, strict=True):
            if target.get("status") != "active":
                raise ValueError("selected Room participant is no longer active")
            binding = self.kernel.session_binding(session_id)
            session = self.sessions.get(session_id)
            if binding is not None or str(session.get("status") or "") not in {
                "idle",
            }:
                raise ValueError(
                    f"{target.get('displayName') or 'selected Room participant'} "
                    "is currently busy"
                )

    def _dispatch_envelope(
        self,
        *,
        identity: str,
        root_id: str,
        task_id: str,
        post_id: str,
        target: Mapping[str, object],
        ordinal: int,
    ) -> dict[str, object]:
        participant_id = str(target["id"])
        session_id = str(target["sessionId"])
        dispatch_identity = _stable_digest(identity, participant_id, str(ordinal))
        capability_epoch = self._next_capability_epoch(session_id)
        return {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": f"room-dispatch:{dispatch_identity}",
            "rootId": root_id,
            "taskId": task_id,
            "parentDispatchId": None,
            "generation": 0,
            "hopCount": 0,
            "depth": 0,
            "budgetCost": 1,
            "targetSessionId": session_id,
            "targetParticipantId": participant_id,
            "triggerId": post_id,
            "intentKind": "execute",
            "idempotencyKey": (
                f"room-message:{identity}:participant:{participant_id}"
            ),
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": (
                f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                f"{target.get('roleId')}@{target.get('roleVersion') or '1'}"
            ),
            "state": "pending",
        }

    def _next_capability_epoch(self, session_id: str) -> int:
        latest = self.capabilities.runtime_binding(session_id, active_only=False)
        if latest is None:
            return 1
        if latest.get("state") in {"active", "prepared"}:
            raise RoomKernelFenceError(
                "Room participant still has an active capability binding"
            )
        # Revocation advances the stored epoch and thereby publishes the next
        # safe generation. Reuse that fenced value rather than incrementing
        # twice and creating unexplained gaps.
        return max(1, int(latest.get("capabilityEpoch") or 0))


def _message_identity(room_id: str, client_message_id: str) -> str:
    nonce = client_message_id or f"server:{uuid.uuid4()}"
    return _stable_digest(room_id, nonce)


def _stable_digest(*values: str) -> str:
    encoded = "\0".join(values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _root_owner(
    room: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
) -> str:
    moderator_id = str(room.get("moderatorParticipantId") or "")
    active_ids = {
        str(value.get("id") or "")
        for value in room.get("participants", [])
        if isinstance(value, Mapping) and value.get("status") == "active"
    }
    if moderator_id in active_ids:
        return moderator_id
    return str(targets[0]["id"])


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        text
        for item in value
        if (text := " ".join(str(item or "").split()))
    )


def _public_error(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _work_item_acceptance_criteria(
    identity: str,
    work_item: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    if work_item is None:
        return ()
    raw = work_item.get("acceptanceCriteria")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    criteria: list[tuple[str, str]] = []
    for ordinal, value in enumerate(raw):
        statement = " ".join(str(value or "").split())
        if not statement:
            continue
        criterion_id = (
            f"acceptance:{identity}:{ordinal}:"
            f"{_stable_digest(statement)}"
        )
        criteria.append((criterion_id, statement[:1_000]))
    return tuple(criteria)


def _work_item_context(
    work_item: Mapping[str, object],
    *,
    acceptance_criteria: Sequence[tuple[str, str]],
) -> str:
    return json.dumps(
        {
            "schemaVersion": "wisdom-weasel.room-work-item-context.v1",
            "authority": "task-only",
            "doesNotChange": [
                "identity",
                "toolPermissions",
                "approvalPolicy",
                "safetyPolicy",
            ],
            "workItemId": str(work_item.get("id") or ""),
            "revision": int(work_item.get("revision") or 0),
            "objective": str(work_item.get("objective") or "")[:4_000],
            "expectedOutput": str(
                work_item.get("expectedOutput") or ""
            )[:2_000],
            "acceptanceCriteria": [
                {"criterionId": criterion_id, "statement": statement}
                for criterion_id, statement in acceptance_criteria
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
