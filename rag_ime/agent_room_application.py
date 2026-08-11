from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping, Sequence

from .agent_definitions import canonical_collaboration_role_id
from .agent_personas import AgentPersonaStore
from .agent_role_book import AgentRoleBookStore
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_context import RoomContextLedgerStore
from .agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    kernel_owns_room_execution,
)
from .agent_room_kernel_contracts import (
    DEFAULT_RUNTIME_PROFILE_REVISION,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_POST_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_public_timeline import (
    RoomPublicTimelineProjector,
    canonical_room_alignment_content,
    public_room_post_payload,
)
from .agent_room_references import (
    ParticipantReferenceError,
    participant_ref_map,
    resolve_participant_ref,
)
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
        resolve_attachments: Callable[
            [str, Sequence[str], Sequence[str]], list[dict[str, object]]
        ],
        deliver_steer: Callable[[str, str, str], Mapping[str, object]] | None = None,
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
        self.resolve_attachments = resolve_attachments
        self.deliver_steer = deliver_steer
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def post_message(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str] = (),
        answer_to_post_id: str = "",
        answer_to_root_id: str = "",
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
                attachment_ids=attachment_ids,
                answer_to_post_id=answer_to_post_id,
                answer_to_root_id=answer_to_root_id,
            )

    def start_execution(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Apply the typed one-shot start action after real clarification."""

        action = str(payload.get("action") or "").strip()
        root_id = str(payload.get("rootId") or "").strip()
        client_action_id = str(payload.get("clientActionId") or "").strip()
        if action != "start_execution" or not root_id or not client_action_id:
            raise ValueError(
                "start execution requires action=start_execution, rootId, and clientActionId"
            )
        room = self.rooms.get(room_id)
        root = self.kernel.root(root_id)
        if root.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "typed start Root does not belong to this Room"
            )
        facilitator = self.rooms.participant(
            str(root["facilitatorParticipantId"])
        )
        if (
            facilitator.get("roomId") != room_id
            or facilitator.get("status") != "active"
        ):
            raise RoomKernelFenceError(
                "typed start Facilitator is no longer active"
            )
        timestamp = self.clock_ms()
        identity = _stable_digest(root_id, client_action_id, "typed-start")
        post_id = f"room-post:user:{identity}"
        started = self.kernel.start_defined_execution(
            root_id=root_id,
            client_action_id=client_action_id,
            user_post_id=post_id,
            now_ms=timestamp,
        )
        receipt_details = started["receipt"].get("details")
        if not isinstance(receipt_details, Mapping):
            raise RoomKernelFenceError("typed start receipt has no details")
        timestamp = int(started["receipt"]["createdAtMs"])
        post_id = str(receipt_details.get("userPostId") or post_id)
        effective_client_action_id = str(
            receipt_details.get("clientActionId") or client_action_id
        )
        chronology_after_post_id = str(
            receipt_details.get("chronologyAfterPostId") or ""
        )
        dispatch = started["dispatch"]
        task = self.kernel.task(str(dispatch["taskId"]))
        user_post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": post_id,
            "roomId": room_id,
            "rootId": root_id,
            "generation": int(root["generation"]),
            "taskId": str(dispatch["taskId"]),
            "authorActorRef": "user:local",
            "kind": "request",
            "visibility": "room",
            "content": "开始行动",
            "idempotencyKey": (
                f"typed-start:{root_id}:{effective_client_action_id}"
            ),
            "publicationSource": {
                "kind": "user",
                "ref": effective_client_action_id,
            },
            "createdAtMs": timestamp,
        }
        dispatch_result = _queued_dispatch_result(
            facilitator,
            dispatch,
            was_created=bool(started["created"]),
            phase="execution",
        )
        route_decision = {
            "routingPolicy": "typed_start_action",
            "reason": "用户确认开始已对齐的行动",
            "targetParticipantId": str(facilitator["id"]),
            "phase": "execution",
            "rootId": root_id,
            "taskId": str(task["taskId"]),
            "dispatchId": str(dispatch["dispatchId"]),
            "targetSessionId": str(facilitator["sessionId"]),
            "dependsOnDispatchIds": list(
                dispatch.get("dependsOnDispatchIds") or []
            ),
        }
        timeline_events: list[dict[str, object]] = []
        projection_pending = False
        try:
            timeline_events = self.public_timeline.publish_ingress(
                room=room,
                post=user_post,
                client_message_id=effective_client_action_id,
                route_decisions=[route_decision],
                dispatches=[dispatch_result],
                chronology_after_post_id=chronology_after_post_id,
            )
            existing_post = next(
                (
                    item
                    for item in self.projection.snapshot(room_id)["posts"]
                    if str(item.get("postId") or "") == post_id
                ),
                None,
            )
            if existing_post is not None:
                user_post = dict(existing_post)
            else:
                user_event = next(
                    (
                        event
                        for event in timeline_events
                        if event.get("eventType") == "user_message"
                        and isinstance(event.get("payload"), Mapping)
                        and str(event["payload"].get("postId") or "") == post_id
                    ),
                    None,
                )
                if user_event is None:
                    raise RoomKernelFenceError(
                        "typed start has no authoritative Room event order"
                    )
                event_sequence = int(user_event["sequence"])
                user_post["chronology"] = {
                    "schemaVersion": "wisdom-weasel.room-post-chronology.v1",
                    "roomEventId": str(user_event["eventId"]),
                    "roomEventSequence": event_sequence,
                    "createdAtMs": timestamp,
                    "afterPostId": chronology_after_post_id or None,
                    "orderKey": f"room-event:{event_sequence:020d}",
                }
                self.projection.publish_post(user_post)
            self.context.publish_post(user_post)
            self.projection.sync_room(room_id, now_ms=timestamp)
        except Exception:
            # The Kernel start transaction is already durable.  A read-model or
            # timeline failure is recoverable state, never a rejected command.
            projection_pending = True
        finally:
            if started["created"]:
                try:
                    self.wake_worker()
                except Exception:
                    projection_pending = True
        return {
            "schemaVersion": "rag-ime.room-start-execution.v1",
            "ok": True,
            "accepted": True,
            "created": bool(started["created"]),
            "roomId": room_id,
            "rootId": root_id,
            "taskId": str(task["taskId"]),
            "post": user_post,
            "dispatch": dispatch_result,
            "routeDecision": route_decision,
            "intake": started["intake"],
            "receipt": started["receipt"],
            "timelineEvents": timeline_events,
            "projectionPending": projection_pending,
            "recoveryState": "recovering" if projection_pending else "synced",
        }

    def steer_participant(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Deliver one user supplement to one exact running Room turn.

        This is intentionally neither a new Root nor a new Task.  Every
        identity in the request is checked again against the current Kernel
        binding immediately before the existing Pi ``steer`` delivery.
        """

        action = str(payload.get("action") or "").strip()
        root_id = str(payload.get("rootId") or "").strip()
        participant_id = str(payload.get("participantId") or "").strip()
        client_action_id = str(payload.get("clientActionId") or "").strip()
        message = str(payload.get("message") or "").strip()
        raw_generation = payload.get("expectedGeneration")
        if isinstance(raw_generation, bool):
            raw_generation = None
        try:
            expected_generation = int(raw_generation)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "participant steer requires a non-negative expectedGeneration"
            ) from exc
        if (
            action != "steer_participant"
            or not root_id
            or not participant_id
            or not client_action_id
            or not message
            or expected_generation < 0
        ):
            raise ValueError(
                "participant steer requires action=steer_participant, rootId, "
                "expectedGeneration, participantId, clientActionId, and message"
            )
        if len(client_action_id) > 128 or len(message) > 8_000:
            raise ValueError("participant steer action or message is too long")
        if self.deliver_steer is None:
            raise RuntimeError("participant steer delivery is not configured")

        room = self.rooms.get(room_id)
        if room.get("status") != "active":
            raise RoomKernelFenceError("participant steer requires an active Room")
        root = self.kernel.root(root_id)
        if root.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "participant steer Root does not belong to this Room"
            )
        if root.get("state") != "running":
            raise RoomKernelFenceError("participant steer Root is terminal or inactive")
        if int(root.get("generation", -1)) != expected_generation:
            raise RoomKernelFenceError("participant steer generation is stale")
        participant = self.rooms.participant(participant_id)
        session_id = str(participant.get("sessionId") or "").strip()
        if (
            participant.get("roomId") != room_id
            or participant.get("status") != "active"
            or not session_id
        ):
            raise RoomKernelFenceError(
                "participant steer participant is not active in this Room"
            )
        targets = self.kernel.active_runtime_targets(
            room_id=room_id,
            root_id=root_id,
            participant_id=participant_id,
        )
        if len(targets) != 1:
            raise RoomKernelFenceError(
                "participant steer requires exactly one running target"
            )
        target = targets[0]
        if (
            target.get("sessionId") != session_id
            or int(target.get("generation", -1)) != expected_generation
            or target.get("participantId") != participant_id
            or target.get("taskState") != "active"
            or target.get("currentOwnerParticipantId") != participant_id
        ):
            raise RoomKernelFenceError(
                "participant steer target no longer matches current Room ownership"
            )
        task = self.kernel.task(str(target["taskId"]))
        if (
            task.get("rootId") != root_id
            or task.get("state") != "active"
            or task.get("currentOwnerParticipantId") != participant_id
        ):
            raise RoomKernelFenceError("participant steer Task is no longer active")
        session = self.sessions.get(session_id)
        runtime_turn_id = str(target["runtimeTurnId"])
        if session.get("status") == "archived":
            raise RoomKernelFenceError("participant steer Session is archived")
        if self.sessions.runtime_turn_terminal_event(session_id, runtime_turn_id):
            raise RoomKernelFenceError("participant steer runtime turn is terminal")
        if self.sessions.latest_runtime_turn_id(session_id) != runtime_turn_id:
            raise RoomKernelFenceError("participant steer runtime turn is stale")

        delivered = dict(self.deliver_steer(session_id, message, client_action_id))
        if (
            not delivered.get("accepted")
            or str(delivered.get("turnId") or "") != runtime_turn_id
        ):
            raise RoomKernelFenceError(
                "participant steer was not accepted by the bound runtime turn"
            )
        return {
            "schemaVersion": "rag-ime.room-participant-steer.v1",
            "ok": True,
            "accepted": True,
            "roomId": room_id,
            "rootId": root_id,
            "expectedGeneration": expected_generation,
            "participantId": participant_id,
            "sessionId": session_id,
            "taskId": str(target["taskId"]),
            "dispatchId": str(target["dispatchId"]),
            "runtimeTurnId": runtime_turn_id,
            "clientActionId": client_action_id,
            "delivery": delivered,
        }

    def define_room(
        self,
        room_id: str,
        *,
        dispatch_id: str,
        invocation_receipt_id: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        """Atomically finalize alignment into one governed root WorkItem."""

        room = self.rooms.get(room_id)
        dispatch = self.kernel.dispatch(dispatch_id)
        root = self.kernel.root(str(dispatch["rootId"]))
        prior_definition = self.kernel.definition_fence(
            root_id=str(dispatch["rootId"]),
            dispatch_id=dispatch_id,
            invocation_receipt_id=invocation_receipt_id,
        )
        if (
            root.get("roomId") != room_id
            or dispatch.get("rootId") != root.get("rootId")
            or (
                prior_definition is None
                and not self.kernel.dispatch_is_active_alignment(dispatch_id)
            )
        ):
            raise RoomKernelFenceError(
                "room_define Dispatch does not belong to this Room alignment"
            )
        participant_refs = participant_ref_map(room["participants"])
        implementation_ref = str(
            arguments.get("implementationParticipantRef") or ""
        ).strip()
        implementation_id = str(root["facilitatorParticipantId"])
        if implementation_ref:
            try:
                implementation_id = resolve_participant_ref(
                    implementation_ref,
                    participant_refs,
                )
            except ParticipantReferenceError:
                implementation_id = implementation_ref
                if not any(
                    isinstance(item, Mapping)
                    and str(item.get("id") or "") == implementation_id
                    and item.get("status") == "active"
                    for item in room.get("participants", [])
                ):
                    raise
        target = self.rooms.participant(implementation_id)
        if (
            target.get("roomId") != room_id
            or target.get("status") != "active"
            or not str(target.get("sessionId") or "").strip()
        ):
            raise RoomKernelFenceError(
                "room_define implementation participant is not active"
            )
        objective = str(arguments.get("objective") or "").strip()
        expected_output = str(arguments.get("expectedOutput") or "").strip()
        raw_requirements = arguments.get("requirements")
        raw_criteria = arguments.get("acceptanceCriteria")
        if not objective or not expected_output:
            raise ValueError("room_define objective and expectedOutput are required")
        if (
            not isinstance(raw_requirements, Sequence)
            or isinstance(raw_requirements, (str, bytes))
            or not 1 <= len(raw_requirements) <= 8
        ):
            raise ValueError("room_define requirements must contain 1-8 items")
        if (
            not isinstance(raw_criteria, Sequence)
            or isinstance(raw_criteria, (str, bytes))
            or not 1 <= len(raw_criteria) <= 16
        ):
            raise ValueError(
                "room_define acceptanceCriteria must contain 1-16 items"
            )
        requirements = [
            " ".join(str(item or "").split())
            for item in raw_requirements
        ]
        if any(not item for item in requirements):
            raise ValueError("room_define requirements must not be empty")
        criteria_input: list[dict[str, object]] = []
        for value in raw_criteria:
            if isinstance(value, Mapping):
                statement = " ".join(
                    str(value.get("statement") or "").split()
                )
                criterion_kind = str(value.get("kind") or "requirement")
                full_name = str(
                    value.get("fullNameZh") or ""
                ).strip() or ""
                receipt_types = value.get("expectedReceiptTypes")
            else:
                statement = " ".join(str(value or "").split())
                criterion_kind = "requirement"
                full_name = ""
                receipt_types = None
            if not statement:
                raise ValueError("room_define acceptance criterion is empty")
            if criterion_kind not in {"requirement", "user_journey"}:
                raise ValueError("room_define acceptance criterion kind is invalid")
            normalized_receipt_types = [
                str(item).strip()
                for item in (
                    receipt_types
                    if isinstance(receipt_types, Sequence)
                    and not isinstance(receipt_types, (str, bytes))
                    else ["evidence"]
                )
                if str(item).strip()
            ]
            if not normalized_receipt_types or any(
                item not in {"test", "build", "install", "browser", "evidence"}
                for item in normalized_receipt_types
            ):
                raise ValueError(
                    "room_define acceptance criterion receipt types are invalid"
                )
            if not full_name:
                full_name = f"验收条件 {len(criteria_input) + 1}"
            if not any("\u4e00" <= char <= "\u9fff" for char in full_name):
                raise ValueError(
                    "room_define acceptance criterion fullNameZh must contain Chinese"
                )
            criteria_input.append(
                {
                    "statement": statement,
                    "criterionKind": criterion_kind,
                    "acceptanceCriterionFullNameZh": full_name,
                    "expectedReceiptTypes": list(
                        dict.fromkeys(normalized_receipt_types)
                    ),
                }
            )

        fence_id = f"room-definition-fence:{_stable_digest(invocation_receipt_id)}"
        alignment_post_id = (
            "room-post:alignment:"
            f"{_stable_digest(str(root['rootId']), 'defined-alignment')}"
        )
        alignment_idempotency_key = (
            f"room-define-alignment:{root['rootId']}"
        )
        prior_fence = prior_definition
        if prior_fence is not None:
            replay = {
                "schemaVersion": "rag-ime.room-define.v1",
                "ok": True,
                "created": False,
                **{
                    key: value
                    for key, value in prior_fence.items()
                    if key not in {"receipt"}
                },
                "definitionReceipt": prior_fence["receipt"],
                "idempotentReplay": True,
            }
            alignment_post = self.context.post_by_idempotency(
                room_id=room_id,
                idempotency_key=alignment_idempotency_key,
            )
            if alignment_post is not None:
                replay["alignmentPost"] = public_room_post_payload(
                    alignment_post
                )
            return replay
        if self.kernel.definition_fence(
            root_id=str(root["rootId"]),
            dispatch_id=dispatch_id,
        ) is not None:
            raise RoomKernelFenceError(
                "Root already has a different room_define fence"
            )

        context = self.requirements.dispatch_context(dispatch_id)
        if not isinstance(context, Mapping) or not isinstance(
            context.get("catalog"),
            Mapping,
        ):
            raise RoomKernelFenceError(
                "room_define requires the alignment RequirementCatalog"
            )
        current_catalog_id = str(
            context["catalog"].get("catalogRevisionId") or ""
        )
        current_catalog = self.requirements.catalog_revision(current_catalog_id)
        current_revision = int(current_catalog["revision"])
        existing_items = [
            dict(item)
            for item in current_catalog.get("items", [])
            if isinstance(item, Mapping)
        ]
        derived_item_ids: list[str] = []
        for ordinal, statement in enumerate(requirements):
            item_id = (
                f"requirement:{_stable_digest(str(root['rootId']), invocation_receipt_id, str(ordinal), statement)}"
            )
            derived_item_ids.append(item_id)
            existing_items.append(
                {
                    "itemId": item_id,
                    "kind": "agent_inferred_requirement",
                    "statement": statement,
                    "origin": "room_define",
                    "state": "active",
                    "sourceSpans": [],
                    "supersedes": [],
                    "ambiguity": "",
                    "confirmation": "derived_from_alignment",
                }
            )
        criterion_ids: list[str] = []
        final_criteria: list[dict[str, object]] = []
        for ordinal, item in enumerate(criteria_input):
            criterion_id = (
                f"criterion:{_stable_digest(str(root['rootId']), invocation_receipt_id, str(ordinal), str(item['statement']))}"
            )
            criterion_ids.append(criterion_id)
            final_criteria.append(
                {
                    "criterionId": criterion_id,
                    "itemId": derived_item_ids[
                        min(ordinal, len(derived_item_ids) - 1)
                    ],
                    "acceptanceCriterionFullNameZh": item[
                        "acceptanceCriterionFullNameZh"
                    ],
                    "criterionKind": item["criterionKind"],
                    "expectedReceiptTypes": item["expectedReceiptTypes"],
                    "statement": item["statement"],
                }
            )
        final_catalog_id = (
            f"requirement-catalog:{_stable_digest(str(root['rootId']), invocation_receipt_id)}"
        )
        work_id = (
            f"room-work:{_stable_digest(str(root['rootId']), invocation_receipt_id)}"
        )
        aliases = {
            f"AC-{ordinal + 1}": criterion_id
            for ordinal, criterion_id in enumerate(criterion_ids)
        }
        task = self.kernel.task(str(dispatch["taskId"]))
        task_payload = {
            **task,
            "workItemId": work_id,
            "objective": objective,
            "expectedOutput": expected_output,
            "requirementItemIds": [
                str(item["itemId"])
                for item in existing_items
                if str(item.get("itemId") or "").strip()
            ],
            "acceptanceCriterionIds": criterion_ids,
            "contextEvidenceRefs": [
                *[
                    str(value)
                    for value in task.get("contextEvidenceRefs") or []
                    if str(value).strip()
                ],
                fence_id,
            ],
            "revision": int(task.get("revision") or 0) + 1,
            "state": "active",
        }
        timestamp = self.clock_ms()
        facilitator = self.rooms.participant(
            str(root["facilitatorParticipantId"])
        )
        if (
            facilitator.get("roomId") != room_id
            or facilitator.get("status") != "active"
            or str(facilitator.get("sessionId") or "")
            != str(dispatch["targetSessionId"])
        ):
            raise RoomKernelFenceError(
                "room_define Facilitator Session is no longer active"
            )
        execute_dispatch_id = (
            f"room-dispatch:{_stable_digest(str(root['rootId']), invocation_receipt_id, 'execute')}"
        )
        execute_dispatch = {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": execute_dispatch_id,
            "rootId": str(root["rootId"]),
            "taskId": str(task_payload["taskId"]),
            "parentDispatchId": dispatch_id,
            "generation": int(dispatch["generation"]),
            "hopCount": int(dispatch["hopCount"]) + 1,
            "depth": int(dispatch["depth"]),
            "budgetCost": 1,
            "targetSessionId": str(facilitator["sessionId"]),
            "targetParticipantId": str(facilitator["id"]),
            "triggerId": fence_id,
            "intentKind": "execute",
            "idempotencyKey": f"room-define-execute:{root['rootId']}",
            "attempt": 0,
            "capabilityEpoch": int(dispatch["capabilityEpoch"]) + 1,
            "runtimeProfileRevision": str(
                dispatch["runtimeProfileRevision"]
            ),
            "dependsOnDispatchIds": [dispatch_id],
            "attachmentIds": list(dispatch.get("attachmentIds") or []),
            "state": "pending",
        }
        alignment_post: dict[str, object] | None = None
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            catalog, _ = self.requirements.revise_catalog_in_transaction(
                transaction,
                catalog_revision_id=final_catalog_id,
                root_id=str(root["rootId"]),
                expected_current_revision=current_revision,
                anchor_refs=current_catalog["anchorRefs"],
                items=existing_items,
                acceptance_criteria=final_criteria,
                change_reason="对齐完成后建立最终实现需求与验收目录",
                provenance={
                    "derivedFrom": [current_catalog_id],
                    "definitionInvocationReceiptId": invocation_receipt_id,
                    "contextFenceId": fence_id,
                },
                created_by="room-define",
                created_at_ms=timestamp,
            )
            work_item, _ = self.work_items.create_root_in_transaction(
                transaction,
                work_id=work_id,
                room_id=room_id,
                objective=objective,
                expected_output=expected_output,
                current_owner_participant_id=str(
                    root["facilitatorParticipantId"]
                ),
                created_by_participant_id=str(root["facilitatorParticipantId"]),
                client_message_id=f"room-define:{invocation_receipt_id}",
                acceptance_criteria=[
                    str(item["statement"]) for item in final_criteria
                ],
                created_at_ms=timestamp,
                root_turn_id=str(root["rootId"]),
            )
            independent_review_required = bool(
                root.get("independentReviewRequired")
            )
            details = {
                "operation": "room_define",
                "dispatchId": dispatch_id,
                "invocationReceiptId": invocation_receipt_id,
                "definitionFenceId": fence_id,
                "catalogRevisionId": catalog["catalogRevisionId"],
                "catalogRevision": catalog["revision"],
                "anchorRefs": list(catalog["anchorRefs"]),
                "requirementItemIds": list(task_payload["requirementItemIds"]),
                "acceptanceCriterionIds": criterion_ids,
                "acceptanceAliases": aliases,
                "implementationParticipantId": implementation_id,
                "implementationParticipantRef": implementation_ref,
                "workItemId": work_item["id"],
                "independentReviewRequired": independent_review_required,
            }
            intake_before_definition = self.kernel.intake_state(
                str(root["rootId"]),
                conn=transaction,
            )
            alignment_post = {
                "schemaVersion": ROOM_POST_SCHEMA_VERSION,
                "postId": alignment_post_id,
                "roomId": room_id,
                "rootId": str(root["rootId"]),
                "generation": int(root["generation"]),
                "taskId": str(task_payload["taskId"]),
                "dispatchId": dispatch_id,
                "authorActorRef": str(root["facilitatorParticipantId"]),
                "kind": "alignment",
                "visibility": "room",
                "content": canonical_room_alignment_content(
                    objective=objective,
                    expected_output=expected_output,
                ),
                "idempotencyKey": alignment_idempotency_key,
                "publicationSource": {
                    "kind": "room_post",
                    "ref": fence_id,
                },
                "createdAtMs": timestamp,
            }
            self.projection.publish_post_in_transaction(
                transaction,
                alignment_post,
            )
            self.context.publish_post_in_transaction(
                transaction,
                alignment_post,
            )
            revised = self.kernel.revise_definition_in_transaction(
                transaction,
                root_id=str(root["rootId"]),
                dispatch_id=dispatch_id,
                invocation_receipt_id=invocation_receipt_id,
                task_payload=task_payload,
                acceptance_criteria=criterion_ids,
                independent_review_required=independent_review_required,
                execute_dispatch_payload=execute_dispatch,
                details=details,
                now_ms=timestamp,
            )
            if bool(alignment_post) != bool(
                revised["receipt"]["details"].get("requiresStartAction")
            ):
                raise RoomKernelFenceError(
                    "room_define alignment publication disagrees with intake state"
                )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        response = {
            "schemaVersion": "rag-ime.room-define.v1",
            "ok": True,
            "created": True,
            "rootId": str(root["rootId"]),
            "taskId": str(task_payload["taskId"]),
            "dispatchId": dispatch_id,
            "definitionFenceId": fence_id,
            "definitionReceipt": revised["receipt"],
            "requirementCatalog": catalog,
            "acceptanceAliases": aliases,
            "implementationParticipant": target,
            "implementationParticipantRef": implementation_ref,
            "workItem": work_item,
            "contextFence": {
                "definitionReceiptId": revised["receipt"]["receiptId"],
                "definitionFenceId": fence_id,
                "catalogRevisionId": catalog["catalogRevisionId"],
                "taskRevision": task_payload["revision"],
                "dispatchId": dispatch_id,
            },
            "intake": revised["intake"],
            "executionDispatch": revised["dispatch"],
            "requiresStartAction": bool(
                revised["receipt"]["details"].get("requiresStartAction")
            ),
            "next": (
                "await_typed_start_action"
                if revised["receipt"]["details"].get("requiresStartAction")
                else "room_collaborate_with_bounded_implementation_lanes"
            ),
        }
        if alignment_post is not None:
            response["alignmentPost"] = alignment_post
        self.projection.sync_room(room_id, now_ms=timestamp)
        return response
    def _replay_post_response(
        self,
        room_id: str,
        *,
        client_message_id: str,
        post: Mapping[str, object],
    ) -> dict[str, object]:
        """Rebuild the durable ingress result without creating new state."""

        room = self.rooms.get(room_id)
        root_id = str(post.get("rootId") or "")
        task_id = str(post.get("taskId") or "")
        root = self.kernel.root(root_id)
        alignment_dispatches = self.kernel.requirement_alignment_dispatches(root_id)
        alignment_results: list[dict[str, object]] = []
        for dispatch in alignment_dispatches:
            target = self.rooms.participant(
                str(dispatch["targetParticipantId"])
            )
            alignment_results.append(
                _queued_dispatch_result(
                    target,
                    dispatch,
                    was_created=False,
                    phase="alignment",
                    alignment_ordinal=(
                        int(dispatch["alignmentOrdinal"])
                        if dispatch.get("alignmentOrdinal") is not None
                        else None
                    ),
                )
            )
        candidate_root_id = f"room-root:{_message_identity(room_id, client_message_id)}"
        resumed = root_id != candidate_root_id
        dispatch_results: list[dict[str, object]] = []
        route_decisions: list[dict[str, object]] = []
        if resumed and alignment_dispatches:
            alignment = alignment_dispatches[0]
            target = self.rooms.participant(
                str(alignment["targetParticipantId"])
            )
            resume_identity = _message_identity(room_id, client_message_id)
            resume_id = (
                "room-dispatch:"
                + _stable_digest(
                    resume_identity,
                    "resume",
                    str(target["id"]),
                    "0",
                )
            )
            try:
                resume_dispatch = self.kernel.dispatch(resume_id)
            except KeyError:
                resume_dispatch = None
            if resume_dispatch is not None:
                dispatch_results.append(
                    _queued_dispatch_result(
                        target,
                        resume_dispatch,
                        was_created=False,
                        phase="resume",
                    )
                )
            route_decisions.append(
                {
                    "routingPolicy": "resume_wait",
                    "reason": "用户回答澄清问题",
                    "targetParticipantId": str(target["id"]),
                    "phase": "resume",
                    "rootId": root_id,
                    "taskId": task_id,
                    "dispatchId": resume_id,
                }
            )
        else:
            route_decisions = [
                {
                    "routingPolicy": "requirement_alignment",
                    "reason": "重复提交已复用原始需求对齐派发",
                    "targetParticipantId": str(
                        dispatch["targetParticipantId"]
                    ),
                    "phase": "alignment",
                    "alignmentOrdinal": int(
                        dispatch.get("alignmentOrdinal") or 0
                    ),
                    "rootId": root_id,
                    "taskId": task_id,
                    "dispatchId": str(dispatch["dispatchId"]),
                }
                for dispatch in alignment_dispatches
            ]
        participant = (
            self.rooms.participant(
                str(
                    (
                        alignment_dispatches[0]
                        if alignment_dispatches
                        else {"targetParticipantId": root["facilitatorParticipantId"]}
                    )["targetParticipantId"]
                )
            )
            if alignment_dispatches
            else self.rooms.participant(str(root["facilitatorParticipantId"]))
        )
        timeline_dispatches = dispatch_results if resumed else alignment_results
        timeline_events = self.public_timeline.publish_ingress(
            room=room,
            post=post,
            client_message_id=client_message_id,
            route_decisions=route_decisions,
            dispatches=timeline_dispatches,
        )
        self.projection.sync_room(
            room_id,
            now_ms=int(post.get("createdAtMs") or self.clock_ms()),
        )
        if timeline_events and timeline_dispatches:
            self.wake_worker()
        return {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "resumed": resumed,
            "idempotentReplay": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": participant,
            "participants": [participant],
            "routeDecision": route_decisions[0] if route_decisions else {},
            "routeDecisions": route_decisions,
            "dispatches": dispatch_results,
            "alignmentDispatches": alignment_results,
            "topicId": str(room.get("activeTopicId") or ""),
            "sessionTurnId": "",
            "post": dict(post),
            "timelineEvents": timeline_events,
        }

    def _resume_pending_user_wait(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        attachment_ids: Sequence[str],
        pending: Mapping[str, object],
    ) -> dict[str, object]:
        """Append one answer and resume the waiting participant once."""

        root_id = str(pending["rootId"])
        task_id = str(pending["taskId"])
        parent_dispatch_id = str(pending["parentDispatchId"])
        participant_id = str(pending["targetParticipantId"])
        room = self.rooms.get(room_id)
        target = self.rooms.participant(participant_id)
        if (
            target.get("roomId") != room_id
            or target.get("status") != "active"
        ):
            raise RoomKernelFenceError(
                "pending user wait participant is no longer active"
            )
        identity = _message_identity(room_id, client_message_id)
        anchor_id = f"requirement-anchor:{identity}"
        post_id = f"room-post:user:{identity}"
        timestamp = self.clock_ms()
        answer_display_text = message
        pending_payload = pending.get("payload")
        if isinstance(pending_payload, Mapping):
            question_options = pending_payload.get("questionOptions")
            if isinstance(question_options, list):
                for option in question_options:
                    if (
                        isinstance(option, Mapping)
                        and str(option.get("value") or "") == message
                    ):
                        answer_display_text = (
                            str(option.get("label") or "").strip() or message
                        )
                        break
        context = self.requirements.dispatch_context(parent_dispatch_id)
        binding = context.get("binding") if isinstance(context, Mapping) else {}
        current_catalog_id = str(
            binding.get("catalogRevisionId") or ""
            if isinstance(binding, Mapping)
            else ""
        )
        if not current_catalog_id and isinstance(context, Mapping):
            catalog_value = context.get("catalog")
            if isinstance(catalog_value, Mapping):
                current_catalog_id = str(
                    catalog_value.get("catalogRevisionId") or ""
                )
        if not current_catalog_id:
            raise RoomKernelFenceError(
                "pending user wait has no RequirementCatalog"
            )
        current_catalog = self.requirements.catalog_revision(current_catalog_id)
        answer_item_id = (
            f"requirement:{_stable_digest(root_id, identity, 'answer')}"
        )
        answer_anchor_provenance = {
            "surface": "room",
            "roomId": room_id,
            "clientMessageId": client_message_id,
            "answerToContinuationId": str(pending["continuationId"]),
        }
        answer_item = {
            "itemId": answer_item_id,
            "kind": "explicit_user_requirement",
            "statement": message,
            "origin": "room_user_answer",
            "state": "active",
            "sourceSpans": [
                {
                    "anchorId": anchor_id,
                    "startByte": 0,
                    "endByte": len(message.encode("utf-8")),
                }
            ],
            "confirmation": "captured_from_user",
        }
        answer_catalog_id = (
            f"requirement-catalog:{_stable_digest(root_id, identity, 'answer-catalog')}"
        )
        user_post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": post_id,
            "roomId": room_id,
            "rootId": root_id,
            "generation": int(pending["generation"]),
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
        target_session_id = str(target["sessionId"])
        resume_dispatch = self._dispatch_envelope(
            identity=identity,
            root_id=root_id,
            task_id=task_id,
            post_id=post_id,
            target=target,
            ordinal=0,
            intent_kind="resume",
            capability_epoch=self._next_capability_epoch(target_session_id),
            depends_on_dispatch_ids=[],
            alignment_ordinal=None,
            attachment_ids=attachment_ids,
        )
        resume_dispatch.update(
            {
                "parentDispatchId": parent_dispatch_id,
                "generation": int(pending["generation"]),
                "hopCount": int(pending.get("parentHopCount") or 0) + 1,
                "depth": int(pending.get("parentDepth") or 0),
            }
        )
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            answer_anchor, _ = self.requirements.append_anchor_in_transaction(
                transaction,
                anchor_id=anchor_id,
                root_id=root_id,
                original_content=message,
                created_by="user:local",
                provenance=answer_anchor_provenance,
                created_at_ms=timestamp,
            )
            requirement_catalog, _ = (
                self.requirements.revise_catalog_in_transaction(
                    transaction,
                    catalog_revision_id=answer_catalog_id,
                    root_id=root_id,
                    expected_current_revision=int(current_catalog["revision"]),
                    anchor_refs=[
                        *[
                            str(value)
                            for value in current_catalog.get("anchorRefs", [])
                        ],
                        anchor_id,
                    ],
                    items=[
                        *[
                            dict(item)
                            for item in current_catalog.get("items", [])
                            if isinstance(item, Mapping)
                        ],
                        answer_item,
                    ],
                    acceptance_criteria=[
                        dict(item)
                        for item in current_catalog.get(
                            "acceptanceCriteria",
                            [],
                        )
                        if isinstance(item, Mapping)
                    ],
                    change_reason="用户回答澄清问题并恢复原对齐任务",
                    provenance={
                        "surface": "room",
                        "answerAnchorId": anchor_id,
                        "continuationId": str(pending["continuationId"]),
                    },
                    created_by="room-ingress",
                    created_at_ms=timestamp,
                )
            )
            self.projection.publish_post_in_transaction(
                transaction,
                user_post,
            )
            self.context.publish_post_in_transaction(
                transaction,
                user_post,
            )
            self.context.append_entry_in_transaction(
                transaction,
                root_id=root_id,
                room_id=room_id,
                generation=int(pending["generation"]),
                entry_kind="requirement_anchor",
                source_ref=anchor_id,
                dedupe_key=f"requirement-anchor:{anchor_id}",
                content=message,
                created_at_ms=timestamp,
            )
            resumed = self.kernel.resume_user_wait_in_transaction(
                transaction,
                continuation_id=str(pending["continuationId"]),
                dispatch_payload=resume_dispatch,
                question_post_id=str(pending["questionPostId"]),
                answer_root_id=root_id,
                answer_post_id=post_id,
                answer_anchor_id=anchor_id,
                now_ms=timestamp,
            )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        dispatch = resumed["dispatch"]
        dispatch_result = _queued_dispatch_result(
            target,
            dispatch,
            was_created=True,
            phase="resume",
        )
        route_decision = {
            "routingPolicy": "resume_wait",
            "reason": "用户回答澄清问题",
            "targetParticipantId": participant_id,
            "phase": "resume",
            "rootId": root_id,
            "taskId": task_id,
            "dispatchId": dispatch["dispatchId"],
        }
        timeline_events = self.public_timeline.publish_ingress(
            room=room,
            post=user_post,
            client_message_id=client_message_id,
            route_decisions=[route_decision],
            dispatches=[dispatch_result],
            answer_to_post_id=str(pending["questionPostId"]),
            answer_display_text=answer_display_text,
        )
        self.projection.sync_room(room_id, now_ms=timestamp)
        self.wake_worker()
        return {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "resumed": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": target,
            "participants": [target],
            "routeDecision": route_decision,
            "routeDecisions": [route_decision],
            "dispatches": [dispatch_result],
            "alignmentDispatches": [],
            "topicId": str(room.get("activeTopicId") or ""),
            "sessionTurnId": "",
            "post": user_post,
            "requirementAnchor": answer_anchor,
            "requirementCatalog": requirement_catalog,
            "timelineEvents": timeline_events,
            "resumeReceipt": resumed["receipt"],
            "continuationId": str(pending["continuationId"]),
        }


    def _post_message_claimed(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str],
        answer_to_post_id: str,
        answer_to_root_id: str,
    ) -> dict[str, object]:
        if not kernel_owns_room_execution(self.kernel.mode):
            raise RoomKernelFenceError("canonical Room ingress requires a managed Kernel")

        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        replay_identity = _message_identity(room_id, client_message_id)
        replay_post = self.context.post_by_idempotency(
            room_id=room_id,
            idempotency_key=f"user-message:{replay_identity}",
        )
        if replay_post is not None:
            return self._replay_post_response(
                room_id,
                client_message_id=client_message_id,
                post=replay_post,
            )
        if answer_to_post_id or answer_to_root_id:
            if not answer_to_post_id or not answer_to_root_id:
                raise ValueError(
                    "Room clarification answers require question and Root identity"
                )
            if str(work_item_id or "").strip():
                raise ValueError(
                    "Room clarification answers cannot be rebound to a WorkItem"
                )
            pending_user_wait = self.kernel.pending_user_wait(
                room_id,
                root_id=answer_to_root_id,
                question_post_id=answer_to_post_id,
            )
            if pending_user_wait is None:
                raise RoomKernelFenceError(
                    "clarification answer does not match an active question and Root"
                )
            return self._resume_pending_user_wait(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                attachment_ids=attachment_ids,
                pending=pending_user_wait,
            )
        timestamp = self.clock_ms()
        identity = _message_identity(room_id, client_message_id)
        root_id = f"room-root:{identity}"
        task_id = f"room-task:{identity}"
        anchor_id = f"requirement-anchor:{identity}"
        post_id = f"room-post:user:{identity}"
        managed_work = bool(str(work_item_id or "").strip())
        work_item: dict[str, object] | None = None
        authoritative_participant_id = ""
        if managed_work:
            work_item, authoritative_participant_id = self._work_item_owner(
                room_id,
                work_item_id,
            )
        active_participants = [
            value
            for value in room.get("participants", [])
            if isinstance(value, Mapping) and value.get("status") == "active"
        ]
        if not active_participants:
            raise RoomKernelFenceError(
                "managed Room execution requires an active participant"
            )
        implementation_participants = [
            participant
            for participant in active_participants
            if canonical_collaboration_role_id(
                participant.get("collaborationRole")
            )
            != "reviewer"
        ]
        if not implementation_participants:
            raise RoomKernelFenceError(
                "managed Room execution requires a non-Reviewer participant"
            )
        preferred_facilitator = _opening_facilitator(
            room,
            active_participants,
            requested_participant_ids=requested_participant_ids,
            managed_work=managed_work,
        )
        requested_participant_ids = (
            (authoritative_participant_id,)
            if managed_work and authoritative_participant_id
            else (preferred_facilitator,)
        )
        decisions = self.rooms.plan_routes(
            room_id,
            message,
            requested_participant_ids=requested_participant_ids,
            profiles=self._routing_profiles(room),
            authoritative_participant_id=authoritative_participant_id,
            conversation_only=not managed_work,
        )
        targets = [
            self.rooms.participant(str(decision["targetParticipantId"]))
            for decision in decisions
        ]
        if not targets:
            raise RoomKernelFenceError(
                "managed Room execution requires an active response participant"
            )
        alignment_targets = [
            self.rooms.participant(preferred_facilitator)
        ]
        attachment_receipts = self.resolve_attachments(
            room_id,
            [str(target["sessionId"]) for target in targets],
            attachment_ids,
        )
        if work_item is not None:
            for decision in decisions:
                decision["workItemId"] = work_item_id
                decision["workItemState"] = str(work_item["state"])
        facilitator_participant_id = preferred_facilitator
        task_owner_participant_id = str(targets[0]["id"])
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
        work_acceptance_criteria = _work_item_acceptance_criteria(
            identity,
            work_item,
        )
        alignment_acceptance_criteria = _alignment_acceptance_criteria(
            identity,
            alignment_targets,
        )
        acceptance_criteria = (
            *work_acceptance_criteria,
            *alignment_acceptance_criteria,
        )
        work_acceptance_ids = tuple(
            criterion_id
            for criterion_id, _statement in work_acceptance_criteria
        )
        acceptance_ids = tuple(
            criterion_id for criterion_id, _statement in acceptance_criteria
        )
        # Roster composition is not review policy.  A later explicit Reviewer
        # handoff records the authoritative policy receipt and flips this flag.
        independent_review_required = False
        original_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
        anchor_ref = f"{anchor_id}@sha256:{original_digest}"
        root = {
            "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
            "rootId": root_id,
            "roomId": room_id,
            "generation": 0,
            "state": "running",
            "facilitatorParticipantId": facilitator_participant_id,
            "reporterParticipantId": facilitator_participant_id,
            "reporterSelectionReceiptId": None,
            "requirementAnchorRef": anchor_ref,
            "createdByActorRef": "user:local",
            "terminalReceiptId": None,
            "activeProfileRef": "standard-room",
            "budgetPolicyRef": "room-budget:interactive-v1",
            "independentReviewRequired": independent_review_required,
            "createdAtMs": timestamp,
        }
        base_task = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": task_id,
            "rootId": root_id,
            "parentTaskId": None,
            "taskKind": "work",
            "currentOwnerParticipantId": task_owner_participant_id,
            "ownershipRevision": 0,
            "ownershipReceiptId": None,
            "invitationId": None,
            "reviewState": "not_required",
            "reviewOfTaskIds": [],
            "reviewAuthorParticipantIds": [],
            "contextEvidenceRefs": [],
            "objective": task_objective,
            "expectedOutput": task_expected_output,
            "requirementItemIds": [requirement_item_id],
            "acceptanceCriterionIds": [
                criterion_id
                for criterion_id, _statement in (
                    alignment_acceptance_criteria
                    if not managed_work
                    else work_acceptance_criteria
                )
            ],
            "revision": 0,
            "state": "active",
        }
        if managed_work:
            base_task["workItemId"] = work_item_id
        else:
            # An ordinary user message uses this base Task as the alignment
            # Task itself. Keep the same conditional define/wait contract as
            # managed-work alignment children so the two ingress paths cannot
            # drift into different product behavior.
            base_task = _alignment_task(
                base_task,
                task_id=task_id,
                target=alignment_targets[0],
                message=message,
                criterion_id=alignment_acceptance_criteria[0][0],
                ordinal=0,
                total=len(alignment_targets),
            )
        task = base_task
        created = self.commands.create_root_task(
            root,
            task,
            budget=DEFAULT_ROOT_BUDGET,
            max_hops=DEFAULT_MAX_HOPS,
            max_depth=DEFAULT_MAX_DEPTH,
            acceptance_criteria=acceptance_ids,
            now_ms=timestamp,
        )
        target_task_ids = [task_id]
        alignment_task_ids: list[str] = []
        if not managed_work:
            alignment_task_ids.append(task_id)
        else:
            for ordinal, (
                target,
                (criterion_id, _statement),
            ) in enumerate(
                zip(
                    alignment_targets,
                    alignment_acceptance_criteria,
                    strict=True,
                )
            ):
                alignment_task_id = f"{task_id}:alignment:{ordinal}"
                self.commands.create_task(
                    _alignment_task(
                        base_task,
                        task_id=alignment_task_id,
                        target=target,
                        message=message,
                        criterion_id=criterion_id,
                        ordinal=ordinal,
                        total=len(alignment_targets),
                    ),
                    now_ms=timestamp,
                )
                alignment_task_ids.append(alignment_task_id)

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
                    ) in enumerate(
                        work_acceptance_criteria
                        if managed_work
                        else alignment_acceptance_criteria
                    )
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
                        acceptance_criteria=work_acceptance_criteria,
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
            if attachment_receipts:
                user_post["attachments"] = attachment_receipts
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

            next_epoch_by_session = {
                str(target["sessionId"]): self._next_capability_epoch(
                    str(target["sessionId"])
                )
                for target in (*alignment_targets, *targets)
            }
            alignment_envelopes: list[dict[str, object]] = []
            alignment_decisions: list[dict[str, object]] = []
            for ordinal, (target, alignment_task_id) in enumerate(
                zip(
                    alignment_targets,
                    alignment_task_ids,
                    strict=True,
                )
            ):
                session_id = str(target["sessionId"])
                envelope = self._dispatch_envelope(
                    identity=identity,
                    root_id=root_id,
                    task_id=alignment_task_id,
                    post_id=post_id,
                    target=target,
                    ordinal=ordinal,
                    intent_kind="align",
                    capability_epoch=next_epoch_by_session[session_id],
                    depends_on_dispatch_ids=[],
                    alignment_ordinal=ordinal,
                    attachment_ids=attachment_ids,
                )
                next_epoch_by_session[session_id] += 1
                alignment_envelopes.append(envelope)
                alignment_decisions.append(
                    {
                        "routingPolicy": "requirement_alignment",
                        "reason": (
                            f"需求对齐并行确认 {ordinal + 1}/"
                            f"{len(alignment_targets)}"
                        ),
                        "targetParticipantId": target["id"],
                        "phase": "alignment",
                        "alignmentOrdinal": ordinal,
                    }
                )
            alignment_dispatch_ids = [
                str(envelope["dispatchId"])
                for envelope in alignment_envelopes
            ]
            execution_envelopes: list[dict[str, object]] = []
            if managed_work:
                for ordinal, (target, target_task_id) in enumerate(
                    zip(targets, target_task_ids, strict=True)
                ):
                    session_id = str(target["sessionId"])
                    envelope = self._dispatch_envelope(
                        identity=identity,
                        root_id=root_id,
                        task_id=target_task_id,
                        post_id=post_id,
                        target=target,
                        ordinal=ordinal,
                        intent_kind="execute",
                        capability_epoch=next_epoch_by_session[session_id],
                        depends_on_dispatch_ids=alignment_dispatch_ids,
                        alignment_ordinal=None,
                        attachment_ids=attachment_ids,
                    )
                    next_epoch_by_session[session_id] += 1
                    execution_envelopes.append(envelope)
                    decisions[ordinal]["phase"] = "execution"
            envelopes = [*alignment_envelopes, *execution_envelopes]
            queued = self.commands.dispatch_many(
                envelopes,
                now_ms=timestamp,
            )
            alignment_queued = queued[: len(alignment_envelopes)]
            execution_queued = queued[len(alignment_envelopes) :]
            alignment_dispatch_results: list[dict[str, object]] = []
            for decision, target, target_task_id, (
                dispatch,
                was_created,
            ) in zip(
                alignment_decisions,
                alignment_targets,
                alignment_task_ids,
                alignment_queued,
                strict=True,
            ):
                decision.update(
                    rootId=root_id,
                    taskId=target_task_id,
                    dispatchId=dispatch["dispatchId"],
                    targetSessionId=target["sessionId"],
                    dependsOnDispatchIds=list(
                        dispatch.get("dependsOnDispatchIds") or []
                    ),
                )
                alignment_dispatch_results.append(
                    _queued_dispatch_result(
                        target,
                        dispatch,
                        was_created=was_created,
                        phase="alignment",
                        alignment_ordinal=int(
                            dispatch["alignmentOrdinal"]
                        ),
                    )
                )
            execution_dispatch_results: list[dict[str, object]] = []
            if managed_work:
                for decision, target, target_task_id, (
                    dispatch,
                    was_created,
                ) in zip(
                    decisions,
                    targets,
                    target_task_ids,
                    execution_queued,
                    strict=True,
                ):
                    decision.update(
                        rootId=root_id,
                        taskId=target_task_id,
                        dispatchId=dispatch["dispatchId"],
                        targetSessionId=target["sessionId"],
                        dependsOnDispatchIds=list(
                            dispatch.get("dependsOnDispatchIds") or []
                        ),
                    )
                    self.rooms.commit_route(
                        room_id,
                        decision,
                        updated_at_ms=timestamp,
                    )
                    execution_dispatch_results.append(
                        _queued_dispatch_result(
                            target,
                            dispatch,
                            was_created=was_created,
                            phase="execution",
                        )
                    )
            all_dispatch_results = [
                *alignment_dispatch_results,
                *execution_dispatch_results,
            ]
            public_route_decisions = (
                [*alignment_decisions, *decisions]
                if managed_work
                else alignment_decisions
            )
            timeline_events = self.public_timeline.publish_ingress(
                room=room,
                post=user_post,
                client_message_id=client_message_id,
                route_decisions=public_route_decisions,
                dispatches=all_dispatch_results,
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
            "routeDecision": public_route_decisions[primary],
            "routeDecisions": public_route_decisions,
            "dispatches": execution_dispatch_results,
            "alignmentDispatches": alignment_dispatch_results,
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
            session_status = str(session.get("status") or "")
            if binding is not None or session_status not in {
                "idle",
                "faulted",
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
        intent_kind: str,
        capability_epoch: int,
        depends_on_dispatch_ids: Sequence[str],
        alignment_ordinal: int | None,
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        participant_id = str(target["id"])
        session_id = str(target["sessionId"])
        dispatch_identity = _stable_digest(
            identity,
            intent_kind,
            participant_id,
            str(ordinal),
        )
        payload: dict[str, object] = {
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
            "intentKind": intent_kind,
            "idempotencyKey": (
                f"room-message:{identity}:{intent_kind}:{ordinal}:"
                f"participant:{participant_id}"
            ),
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": (
                f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                f"{target.get('roleId')}@{target.get('roleVersion') or '1'}"
            ),
            "dependsOnDispatchIds": list(depends_on_dispatch_ids),
            "attachmentIds": list(attachment_ids),
            "state": "pending",
        }
        if alignment_ordinal is not None:
            payload["alignmentOrdinal"] = alignment_ordinal
        return payload

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


def _queued_dispatch_result(
    target: Mapping[str, object],
    dispatch: Mapping[str, object],
    *,
    was_created: bool,
    phase: str,
    alignment_ordinal: int | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "participantId": target["id"],
        "sessionId": target["sessionId"],
        "dispatchId": dispatch["dispatchId"],
        "accepted": True,
        "state": "queued",
        "created": was_created,
        "sessionTurnId": "",
        "error": "",
        "phase": phase,
        "dependsOnDispatchIds": list(
            dispatch.get("dependsOnDispatchIds") or []
        ),
    }
    if alignment_ordinal is not None:
        result["alignmentOrdinal"] = alignment_ordinal
    return result


def _message_identity(room_id: str, client_message_id: str) -> str:
    nonce = client_message_id or f"server:{uuid.uuid4()}"
    return _stable_digest(room_id, nonce)


def _stable_digest(*values: str) -> str:
    encoded = "\0".join(values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _root_facilitator(
    room: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
) -> str:
    active_participants = [
        value
        for value in room.get("participants", [])
        if isinstance(value, Mapping) and value.get("status") == "active"
    ]
    moderator_id = str(room.get("moderatorParticipantId") or "")
    coordinator_ids = [
        str(value.get("id") or "")
        for value in active_participants
        if canonical_collaboration_role_id(value.get("collaborationRole"))
        == "coordinator"
    ]
    if moderator_id in coordinator_ids:
        return moderator_id
    if coordinator_ids:
        return coordinator_ids[0]
    non_reviewer_ids = [
        str(value.get("id") or "")
        for value in active_participants
        if canonical_collaboration_role_id(value.get("collaborationRole"))
        != "reviewer"
    ]
    if moderator_id in non_reviewer_ids:
        return moderator_id
    target_ids = {
        str(value.get("id") or "")
        for value in targets
        if canonical_collaboration_role_id(value.get("collaborationRole"))
        != "reviewer"
    }
    for participant_id in non_reviewer_ids:
        if participant_id in target_ids:
            return participant_id
    raise RoomKernelFenceError(
        "managed Room execution requires a non-Reviewer Facilitator"
    )


def _opening_facilitator(
    room: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
    *,
    requested_participant_ids: Sequence[str],
    managed_work: bool,
) -> str:
    """Resolve the immutable initial Facilitator for a newly-created Root.

    One explicit opening mention may override the default.  Managed WorkItems
    keep their authoritative owner and later messages never call this helper,
    so a mention cannot transfer ownership after Root creation.
    """

    if not managed_work:
        requested = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in requested_participant_ids
                if str(value).strip()
            )
        )
        if len(requested) == 1:
            requested_id = requested[0]
            for participant in room.get("participants", []):
                if (
                    isinstance(participant, Mapping)
                    and str(participant.get("id") or "") == requested_id
                    and participant.get("status") == "active"
                    and canonical_collaboration_role_id(
                        participant.get("collaborationRole")
                    )
                    != "reviewer"
                ):
                    return requested_id
    return _root_facilitator(room, targets)


def _alignment_acceptance_criteria(
    identity: str,
    targets: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    criteria: list[tuple[str, str]] = []
    for ordinal, target in enumerate(targets):
        participant_id = str(target.get("id") or "")
        display_name = (
            " ".join(str(target.get("displayName") or "").split())
            or f"伙伴 {ordinal + 1}"
        )
        statement = (
            f"{display_name} 已读取原始请求并判断是否存在会改变实现的实质歧义；"
            "完整请求直接定义目标、交付、验收和禁区，有歧义时一次只询问一个"
            "必要问题；完成定义前不得开始执行。"
        )
        criteria.append(
            (
                "acceptance:"
                f"{identity}:alignment:{ordinal}:"
                f"{_stable_digest(participant_id, statement)}",
                statement,
            )
        )
    return tuple(criteria)


def _alignment_task(
    base_task: Mapping[str, object],
    *,
    task_id: str,
    target: Mapping[str, object],
    message: str,
    criterion_id: str,
    ordinal: int,
    total: int,
) -> dict[str, object]:
    display_name = (
        " ".join(str(target.get("displayName") or "").split())
        or f"伙伴 {ordinal + 1}"
    )
    return {
        **base_task,
        "taskId": task_id,
        "parentTaskId": None,
        "currentOwnerParticipantId": str(target["id"]),
        "objective": (
            f"需求对齐由 Root Facilitator {display_name} 先完成。"
            "当前只判断和收束需求，不搜索、不改文件、不运行实现任务。"
            "先调用 room_state 读取原始请求和当前工作卡片，再判断是否存在会改变"
            "实现的实质歧义。请求完整时不要索要确认，也不要发布单独的确认消息；"
            "直接用 room_define 一次写入目标、交付物、需求、可观察验收条件和禁区。"
            "有实质歧义时用 room_commit wait 一次只提出一个最小必要问题；每个"
            "用户回答按时间进入对话，问题全部收束后再调用 room_define。只有这条"
            "澄清路径会询问用户是否开始行动。不得把计划或执行结果冒充需求定义。"
            "如果原始请求明确要求开始前展示分工，room_define 的 expectedOutput 必须"
            "逐位写明伙伴姓名、完整用户功能、阻塞依赖和波次；这只是公开计划预览，"
            "不得因此提前分派、读写文件或运行命令。"
            f" 原始请求：{message[:2_000]}"
        )[:4_000],
        "expectedOutput": (
            "一个已定义的可执行目标；仅在确有歧义时出现按时间追加的问题、回答、"
            "对齐摘要和开始行动。用户要求时还要包含开始行动前的公开分工预览，"
            "明确每位伙伴的纵向结果、依赖和波次。定义后由 Facilitator 先执行，"
            "并只把真正独立的工作通过 room_collaborate 分配给伙伴。"
        ),
        "acceptanceCriterionIds": [criterion_id],
        "revision": 0,
        "state": "active",
    }


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
