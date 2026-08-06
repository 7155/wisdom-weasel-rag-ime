from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from urllib.parse import quote

from .agent_blocks import normalize_trusted_agent_blocks
from .agent_definitions import canonical_collaboration_role_id
from .agent_room_capabilities import (
    ROOM_PUBLIC_TOOLS,
    RoomCapabilityManifestStore,
    ToolAuthorizationError,
)
from .agent_room_acceptance import (
    AcceptanceAliasError,
    acceptance_alias_map,
    acceptance_cards,
    resolve_acceptance_aliases,
)
from .agent_room_context import RoomContextLedgerStore
from .agent_room_continuations import (
    RoomContinuationFactory,
    RoomContinuationProposalError,
)
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel import kernel_owns_room_execution
from .agent_room_kernel_contracts import (
    DEFAULT_RUNTIME_PROFILE_REVISION,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    KERNEL_COMMAND_SCHEMA_VERSION,
    validate_kernel_contract,
)
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_room_peer_review import RoomPeerReviewStore
from .agent_room_public_timeline import (
    RoomPublicTimelineProjector,
    public_room_report_content,
)
from .agent_room_references import (
    ParticipantReferenceError,
    participant_ref_map,
    ref_for_participant,
    resolve_participant_ref,
)
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_workspaces import RoomWorkspaceCoordinator, RoomWorkspaceError
from .agent_rooms import AgentRoomStore


class RoomKernelApplicationService:
    """Authorized product commands over the canonical Room Kernel."""

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        kernel: RoomKernelStore,
        commands: KernelCommandBus,
        projection: RoomKernelProjection,
        capabilities: RoomCapabilityManifestStore,
        context: RoomContextLedgerStore,
        requirements: RequirementGovernanceStore,
        peer_review: RoomPeerReviewStore,
        learning: RoomLearningGovernanceStore,
        public_timeline: RoomPublicTimelineProjector,
        wake_worker: Callable[[], None],
        revoke_session: Callable[[str, int], None],
        define_room: Callable[..., dict[str, object]] | None = None,
        artifact_hash_provider: Callable[[str], str] | None = None,
        media_receipt_provider: Callable[[str, str], Mapping[str, object]] | None = None,
        workspaces: RoomWorkspaceCoordinator | None = None,
        root_child_quiescence: Callable[
            [str, int, str], Mapping[str, object]
        ] | None = None,
        cancel_root_children: Callable[
            [str, int, str, str], Mapping[str, object]
        ] | None = None,
        root_state_observer: Callable[
            [Mapping[str, object]], object
        ] | None = None,
    ) -> None:
        self.rooms = rooms
        self.kernel = kernel
        self.commands = commands
        self.projection = projection
        self.capabilities = capabilities
        self.context = context
        self.requirements = requirements
        self.peer_review = peer_review
        self.learning = learning
        self.public_timeline = public_timeline
        self.wake_worker = wake_worker
        self.define_room = define_room
        self.artifact_hash_provider = artifact_hash_provider
        self.workspaces = workspaces
        self.revoke_session = revoke_session
        self.root_child_quiescence = root_child_quiescence or (
            lambda root_id, generation, dispatch_id: {
                "schemaVersion": "rag-ime.root-child-quiescence.v1",
                "owner": "roomRoot",
                "rootId": root_id,
                "generation": generation,
                "dispatchId": dispatch_id,
                "state": "unknown",
                "quiescent": False,
                "pendingCount": 1,
                "unknownCount": 1,
                "counts": {"queued": 0, "running": 0, "cancelling": 0, "total": 0},
                "pendingTargets": [
                    {
                        "targetKind": "roomChildOwner",
                        "targetId": "child-quiescence-owner-unavailable",
                        "state": "unknown",
                    }
                ],
                "errors": ["Room child quiescence owner is unavailable"],
            }
        )
        self.cancel_root_children = cancel_root_children or (
            lambda root_id, generation, reason, request_id: {
                "schemaVersion": "rag-ime.root-child-cancellation.v1",
                "owner": "roomRoot",
                "rootId": root_id,
                "generation": generation,
                "requestId": request_id,
                "state": "unknown",
                "pendingTargets": [
                    {
                        "targetKind": "roomChildOwner",
                        "targetId": "child-cancellation-owner-unavailable",
                        "state": "unknown",
                    }
                ],
                "receipts": [],
            }
        )
        self.root_state_observer = root_state_observer or (
            lambda _root: None
        )
        self.media_receipt_provider = media_receipt_provider
        self.continuations = RoomContinuationFactory(
            rooms=rooms,
            kernel=kernel,
            capabilities=capabilities,
            revoke_session=revoke_session,
        )

    def snapshot(self, room_id: str) -> dict[str, object]:
        self.rooms.get(room_id)
        self.projection.sync_room(room_id)
        snapshot = self.projection.snapshot(room_id)
        snapshot["requirementsByRootId"] = {
            root_id: self.peer_review.read_projection(root_id)
            for root_id in self.kernel.root_ids(room_id)
        }
        snapshot["cancellationSurfaces"] = (
            self.kernel.cancellation_surface_projection(room_id)
        )
        snapshot["pendingTargets"] = [
            item
            for item in snapshot["cancellationSurfaces"]
            if item["state"] in {"requested", "acknowledged", "unknown"}
        ]
        material = {
            key: value
            for key, value in snapshot.items()
            if key != "snapshotHash"
        }
        encoded = json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        snapshot["snapshotHash"] = (
            f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        )
        return snapshot

    def record_runtime_failure(
        self,
        *,
        room_id: str,
        dispatch_id: str,
        generation: int,
        source_event_id: str,
        runtime_turn_id: str,
        dispatch_attempt: int,
        created_at_ms: int,
        retryable: bool = False,
        had_tool_activity: bool = True,
        reason_code: str = "",
    ) -> dict[str, object]:
        """Bridge a private Pi turn failure into the canonical Kernel once."""

        room = self.rooms.get(room_id)
        dispatch = self.kernel.dispatch(dispatch_id)
        root = self.kernel.root(str(dispatch["rootId"]))
        if (
            root.get("roomId") != room_id
            or int(dispatch.get("generation", -1)) != int(generation)
        ):
            raise RoomKernelFenceError(
                "runtime failure does not match the Room Dispatch"
            )
        receipt = self.kernel.record_runtime_failure(
            dispatch_id,
            generation=generation,
            source_event_id=source_event_id,
            runtime_turn_id=runtime_turn_id,
            dispatch_attempt=dispatch_attempt,
            now_ms=created_at_ms,
            retryable=retryable,
            had_tool_activity=had_tool_activity,
            reason_code=reason_code,
        )
        retry_scheduled = (
            receipt.get("receiptKind")
            == "runtime_retry_scheduled"
            and receipt.get("status") == "applied"
        )
        fresh_recovery: dict[str, object] | None = None
        if receipt.get("status") == "applied" and not retry_scheduled:
            self.revoke_session(
                str(dispatch["targetSessionId"]),
                created_at_ms,
            )
            retained_task = self._retain_isolated_task(
                self.kernel.task(str(dispatch["taskId"])),
                state="failed",
                reason=(
                    "Room runtime failed without a safe automatic retry: "
                    + str(reason_code or "runtime_turn_failed")
                ),
                actor_ref="system:room-runtime",
                now_ms=created_at_ms,
            )
            if _allows_fresh_runtime_recovery(
                retryable=retryable,
                reason_code=reason_code,
            ):
                command = _fresh_runtime_recovery_command(
                    room_id=room_id,
                    root_id=str(root["rootId"]),
                    generation=int(root["generation"]),
                    dispatch_id=dispatch_id,
                    source_event_id=source_event_id,
                    created_at_ms=created_at_ms,
                )
                rebound: dict[str, object] | None = None
                try:
                    if retained_task is not None:
                        rebound = self._rebind_retained_runtime_workspace(
                            room=room,
                            dispatch=dispatch,
                            task=retained_task,
                            reason=(
                                "automatic Room runtime recovery after "
                                + str(reason_code or "runtime_turn_failed")
                            ),
                            now_ms=created_at_ms,
                        )
                    control_result = self.commands.control(command)
                    if rebound is not None:
                        self.kernel.record_workspace_lifecycle(
                            str(dispatch["taskId"]),
                            operation="retry",
                            workspace_result=rebound,
                            now_ms=created_at_ms,
                        )
                except (RoomKernelFenceError, RoomWorkspaceError) as exc:
                    if rebound is not None:
                        self._rollback_runtime_workspace_rebind(
                            room=room,
                            task_id=str(dispatch["taskId"]),
                            reason=str(exc),
                            now_ms=created_at_ms,
                        )
                    receipt = {
                        **receipt,
                        "recoveryBlockedReason": str(exc)[:240],
                    }
                else:
                    kernel_receipt = control_result.get("kernelReceipt")
                    if isinstance(kernel_receipt, Mapping):
                        fresh_recovery = dict(kernel_receipt)
                        receipt = {
                            **receipt,
                            "recoveryReceipt": fresh_recovery,
                        }
        self.projection.sync_room(room_id)
        self.root_state_observer(
            self.kernel.root(str(dispatch["rootId"]))
        )
        if retry_scheduled or (
            fresh_recovery is not None
            and fresh_recovery.get("status") == "applied"
        ):
            self.wake_worker()
        return receipt

    def _rebind_retained_runtime_workspace(
        self,
        *,
        room: Mapping[str, object],
        dispatch: Mapping[str, object],
        task: Mapping[str, object],
        reason: str,
        now_ms: int,
    ) -> dict[str, object]:
        if self.workspaces is None:
            raise RoomWorkspaceError(
                "isolated workspace recovery has no workspace coordinator"
            )
        target_participant_id = str(
            dispatch.get("targetParticipantId") or ""
        )
        participants = {
            str(value.get("id") or ""): value
            for value in room.get("participants") or []
            if isinstance(value, Mapping) and value.get("status") == "active"
        }
        target = participants.get(target_participant_id)
        if target is None:
            raise RoomWorkspaceError(
                "automatic workspace recovery target is not active"
            )
        target_session_id = str(target.get("sessionId") or "").strip()
        target_ref = ref_for_participant(
            target_participant_id,
            participant_ref_map(room.get("participants") or []),
        )
        if not target_session_id or not target_ref:
            raise RoomWorkspaceError(
                "automatic workspace recovery target has no active Session reference"
            )
        rebound = self.workspaces.retry_retained(
            binding_id=str(task.get("workspaceBindingId") or ""),
            participant_id=target_participant_id,
            participant_ref=target_ref,
            session_id=target_session_id,
            reason=reason,
            now_ms=now_ms,
        )
        return {**rebound, "targetParticipantRef": target_ref}

    def _rollback_runtime_workspace_rebind(
        self,
        *,
        room: Mapping[str, object],
        task_id: str,
        reason: str,
        now_ms: int,
    ) -> None:
        if self.workspaces is None:
            return
        task = self.kernel.task(task_id)
        retained = self.workspaces.retain_task(
            task,
            state="failed",
            reason=(
                "automatic runtime recovery could not enqueue its bounded work: "
                + reason
            ),
            actor_ref="system:room-runtime-recovery",
            now_ms=now_ms,
        )
        self.kernel.record_workspace_lifecycle(
            task_id,
            operation="retain",
            workspace_result=retained,
            now_ms=now_ms,
        )
        self.workspaces.restore(
            session_id=str(
                next(
                    (
                        value.get("sessionId")
                        for value in room.get("participants") or []
                        if isinstance(value, Mapping)
                        and value.get("id")
                        == task.get("currentOwnerParticipantId")
                    ),
                    "",
                )
                or ""
            ),
            base_roots=[
                str(value)
                for value in room.get("workspaceRoots") or []
                if str(value).strip()
            ],
            restore_policy=(
                task.get("workspaceRestorePolicy")
                if isinstance(task.get("workspaceRestorePolicy"), Mapping)
                else None
            ),
        )

    def _retain_isolated_task(
        self,
        task: Mapping[str, object],
        *,
        state: str,
        reason: str,
        actor_ref: str,
        now_ms: int,
    ) -> dict[str, object] | None:
        if (
            self.workspaces is None
            or task.get("workspacePolicy") != "isolated_writable"
        ):
            return None
        try:
            retained = self.workspaces.retain_task(
                task,
                state=state,
                reason=reason,
                actor_ref=actor_ref,
                now_ms=now_ms,
            )
            return self.kernel.record_workspace_lifecycle(
                str(task["taskId"]),
                operation="retain",
                workspace_result=retained,
                now_ms=now_ms,
            )
        except RoomWorkspaceError as exc:
            raise RoomKernelFenceError(str(exc)) from exc

    def reconcile_workspace_retention(
        self,
        *,
        room_id: str,
        root_id: str = "",
        reason: str = "Room Task ended before workspace integration",
        now_ms: int | None = None,
    ) -> list[dict[str, object]]:
        """Retain interrupted isolated Tasks after any cancellation surface."""

        timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
        self.projection.sync_room(room_id, now_ms=timestamp)
        snapshot = self.projection.snapshot(room_id)
        projected: list[dict[str, object]] = []
        state_map = {
            "blocked": "blocked",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        for task in snapshot.get("tasks") or []:
            if not isinstance(task, Mapping):
                continue
            task_state = str(task.get("state") or "")
            if (
                task.get("workspacePolicy") != "isolated_writable"
                or task_state not in state_map
                or (root_id and task.get("rootId") != root_id)
            ):
                continue
            value = self._retain_isolated_task(
                task,
                state=state_map[task_state],
                reason=reason,
                actor_ref="system:room-cancellation",
                now_ms=timestamp,
            )
            if value is not None:
                projected.append(value)
        if projected:
            self.projection.sync_room(room_id, now_ms=timestamp)
        return projected

    def tool_state(
        self,
        room_id: str,
        *,
        root_id: str,
        dispatch_id: str,
    ) -> dict[str, object]:
        """Return the bounded model-facing state needed to finish one Dispatch."""

        snapshot = self.snapshot(room_id)
        dispatch = next(
            (
                item
                for item in snapshot["dispatches"]
                if item.get("dispatchId") == dispatch_id
                and item.get("rootId") == root_id
            ),
            None,
        )
        if not isinstance(dispatch, Mapping):
            raise RoomKernelFenceError(
                "Room state projection lost its active Dispatch"
            )
        root = next(
            (
                item
                for item in snapshot["roots"]
                if item.get("rootId") == root_id
            ),
            None,
        )
        task = next(
            (
                item
                for item in snapshot["tasks"]
                if item.get("taskId") == dispatch.get("taskId")
            ),
            None,
        )
        if not isinstance(root, Mapping) or not isinstance(task, Mapping):
            raise RoomKernelFenceError(
                "Room state projection lost its Root or Task"
            )
        room = self.rooms.get(room_id)
        participant_refs = participant_ref_map(room["participants"])
        running_participants = {
            str(item.get("targetParticipantId") or "")
            for item in snapshot["dispatches"]
            if isinstance(item, Mapping)
            and item.get("rootId") == root_id
            and item.get("state") in {"queued", "running"}
        }
        participants = []
        for item in room["participants"]:
            if not isinstance(item, Mapping) or item.get("status") != "active":
                continue
            participant_id = str(item["id"])
            is_current = participant_id == str(
                dispatch["targetParticipantId"]
            )
            participants.append(
                {
                    "participantRef": ref_for_participant(
                        participant_id,
                        participant_refs,
                    ),
                    "displayName": str(item["displayName"]),
                    "availability": (
                        "current"
                        if is_current
                        else "busy"
                        if participant_id in running_participants
                        else "available"
                    ),
                    "capabilitySummary": str(
                        item.get("collaborationRole") or "collaborator"
                    ),
                }
            )
        pending_targets = [
            {
                "dispatchId": str(item.get("dispatchId") or ""),
                "state": str(item.get("state") or ""),
            }
            for item in snapshot["pendingTargets"]
            if isinstance(item, Mapping) and item.get("rootId") == root_id
        ]
        recent_changes = [
            {
                "kind": str(post.get("kind") or ""),
                "content": " ".join(
                    str(post.get("content") or "").split()
                )[:320],
                "authorParticipantRef": ref_for_participant(
                    post.get("authorActorRef"),
                    participant_refs,
                ),
            }
            for post in self.context.recent_posts(root_id, limit=5)
        ]
        definition_fence = self.kernel.definition_fence(
            root_id=root_id,
            dispatch_id=dispatch_id,
        )
        if isinstance(definition_fence, Mapping):
            definition_receipt = definition_fence.get("receipt")
            fence_context = {
                key: value
                for key, value in definition_fence.items()
                if key != "receipt"
            }
            if isinstance(definition_receipt, Mapping):
                fence_context["definitionReceiptId"] = str(
                    definition_receipt.get("receiptId") or ""
                )
            requirement_context = self.requirements.dispatch_context(
                dispatch_id,
                catalog_revision_id=str(
                    definition_fence.get("catalogRevisionId") or ""
                ),
                context_fence=fence_context,
            )
        else:
            requirement_context = self.requirements.dispatch_context(
                dispatch_id
            )
        acceptance = acceptance_cards(
            task.get("acceptanceCriterionIds") or [],
            requirement_context,
            accepted_evidence_by_criterion=(
                self.kernel.accepted_evidence_by_criterion(root_id)
            ),
        )
        pending_integrations = [
            {
                "childTaskId": str(candidate.get("taskId") or ""),
                "objective": str(candidate.get("objective") or ""),
                "ownerParticipantRef": ref_for_participant(
                    candidate.get("currentOwnerParticipantId"),
                    participant_refs,
                ),
            }
            for candidate in snapshot["tasks"]
            if isinstance(candidate, Mapping)
            and candidate.get("rootId") == root_id
            and candidate.get("workspacePolicy") == "isolated_writable"
            and candidate.get("workspaceIntegrationState") == "pending"
            and candidate.get("state") == "completed"
        ]
        routing_policy = str(room.get("routingPolicy") or "natural")
        facilitator_id = str(root.get("facilitatorParticipantId") or "")
        eligible_peer_refs: list[str] = []
        reviewer_refs: list[str] = []
        for candidate in room.get("participants", ()):
            if (
                not isinstance(candidate, Mapping)
                or candidate.get("status") != "active"
            ):
                continue
            candidate_id = str(candidate.get("id") or "")
            candidate_ref = ref_for_participant(
                candidate_id,
                participant_refs,
            )
            if candidate_id != facilitator_id:
                eligible_peer_refs.append(candidate_ref)
                reviewer_refs.append(candidate_ref)
        peer_children = [
            child
            for child in self.kernel.collaboration_children(root_id)
            if str(child.get("targetParticipantId") or "")
            != facilitator_id
            and str(child.get("intentKind") or "")
            in {"execute", "revise"}
            and str(child.get("state") or "")
            not in {"cancelled", "failed"}
        ]
        definition = self.kernel.definition_fence(root_id=root_id)
        definition_receipt = (
            definition.get("receipt")
            if isinstance(definition, Mapping)
            and isinstance(definition.get("receipt"), Mapping)
            else {}
        )
        definition_details = (
            definition_receipt.get("details")
            if isinstance(definition_receipt, Mapping)
            and isinstance(definition_receipt.get("details"), Mapping)
            else {}
        )
        execution_plan = (
            definition_details.get("executionPlan")
            if isinstance(definition_details, Mapping)
            and isinstance(definition_details.get("executionPlan"), Mapping)
            else {}
        )
        planned_feature_tasks = [
            dict(item)
            for item in execution_plan.get("featureTasks", [])
            if isinstance(item, Mapping)
        ] if isinstance(execution_plan, Mapping) else []
        planned_peer_ids: set[str] = set()
        for planned_task in planned_feature_tasks:
            try:
                planned_id = resolve_participant_ref(
                    planned_task.get("participantRef"),
                    participant_refs,
                )
            except ParticipantReferenceError:
                planned_id = str(planned_task.get("participantRef") or "")
            if planned_id and planned_id != facilitator_id:
                planned_peer_ids.add(planned_id)
        peer_work_required = bool(planned_peer_ids)
        # Reviewer presence is roster capacity, not review policy.  The
        # Facilitator owns the risk decision at room_define and the Root keeps
        # its durable, receipted answer.  Showing an inferred requirement here
        # while settlement reads the Root would give the model and the gate two
        # different truths.
        review_required = bool(root.get("independentReviewRequired"))
        execution_policy = {
            "routingPolicy": routing_policy,
            "facilitatorOwnsIntegration": (
                str(dispatch.get("targetParticipantId") or "")
                == facilitator_id
            ),
            "peerWorkRequired": peer_work_required,
            "minimumPeerWorkItems": len(planned_peer_ids),
            "assignedPeerWorkItems": len(peer_children),
            "eligiblePeerParticipantRefs": eligible_peer_refs,
            "independentReviewRequired": review_required,
            "reviewerParticipantRefs": reviewer_refs,
            "approvedFeatureTasks": planned_feature_tasks,
            "nextAction": (
                "assign_independent_peer_work"
                if peer_work_required and not peer_children
                else "integrate_completed_peer_work"
                if pending_integrations
                else "continue_owned_work"
            ),
        }
        model_state = {
            "schemaVersion": "wisdom-weasel.room-state-tool.v1",
            "mode": "managed",
            "currentResponsibility": {
                "objective": str(task.get("objective") or ""),
                "expectedOutput": str(task.get("expectedOutput") or ""),
                "state": str(dispatch.get("state") or ""),
                "workspacePolicy": task.get("workspacePolicy"),
            },
            "acceptanceAliases": acceptance,
            "canSettle": (
                root.get("state") == "running"
                and dispatch.get("state") == "running"
            ),
            "participants": participants,
            "executionPolicy": execution_policy,
            "recentPublicChanges": recent_changes,
            "pendingIntegrations": pending_integrations,
            "reviewContext": (
                {
                    "reviewOfTaskIds": list(task.get("reviewOfTaskIds") or []),
                    "authorParticipantRefs": [
                        ref_for_participant(value, participant_refs)
                        for value in task.get("reviewAuthorParticipantIds") or []
                    ],
                }
                if task.get("taskKind") == "review"
                else None
            ),
            "pendingCancellationTargets": len(pending_targets),
        }
        revision_material = {
            **model_state,
            "routing": {
                "rootId": root["rootId"],
                "taskId": task["taskId"],
                "dispatchId": dispatch["dispatchId"],
                "generation": root["generation"],
                "participantRefs": participant_refs,
            },
        }
        revision = hashlib.sha256(
            json.dumps(
                revision_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        model_state["stateRevision"] = f"sha256:{revision}"
        return model_state

    def assert_read_only_workspace_unchanged(
        self,
        task: Mapping[str, object],
    ) -> None:
        if task.get("workspacePolicy") != "read_only":
            return
        expected = str(task.get("workspaceSnapshotSha256") or "").strip()
        if not expected or self.workspaces is None:
            raise RoomKernelFenceError(
                "read_only review is missing a mandatory Git workspace snapshot"
            )
        observed = self.workspaces.task_snapshot_digest(task)
        if not observed or observed != expected:
            raise RoomKernelFenceError(
                "read_only Room work changed the reviewed workspace; "
                "discard those writes and start a fresh independent review"
            )

    def execute_capability_tool(
        self,
        session_id: str,
        tool_name: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        load_receipt_id: str,
    ) -> dict[str, object] | None:
        authorized = self._authorize_capability_invocation(
            session_id,
            tool_name,
            args,
            tool_call_id=tool_call_id,
            load_receipt_id=load_receipt_id,
        )
        if authorized is None:
            return None
        live, invocation, created = authorized
        canonical = str(invocation["canonicalCommand"]["tool"])
        if canonical not in ROOM_PUBLIC_TOOLS:
            raise ToolAuthorizationError(
                "product Tools must execute through the product Tool gateway"
            )
        execution_receipt = None
        if canonical == "room_state":
            result = self.tool_state(
                str(live["roomId"]),
                root_id=str(live["rootId"]),
                dispatch_id=str(live["dispatchId"]),
            )
            state_revision = str(result.get("stateRevision") or "")
            revision_hash = state_revision.removeprefix("sha256:")
            prior = self.capabilities.latest_runtime_execution(
                session_id=session_id,
                dispatch_id=str(live["dispatchId"]),
                tool_name="room_state",
                exclude_invocation_receipt_id=str(invocation["receiptId"]),
            )
            result["unchanged"] = bool(
                prior is not None
                and prior.get("resultHash") == revision_hash
            )
            execution_receipt, _ = self.capabilities.record_runtime_execution(
                session_id=session_id,
                invocation_receipt_id=str(invocation["receiptId"]),
                status="applied",
                result_hash=revision_hash,
                created_at_ms=int(time.time() * 1000),
            )
            result = {
                "evidenceRef": str(
                    execution_receipt["executionReceiptId"]
                ),
                **result,
            }
        elif canonical == "room_collaborate":
            result, execution_receipt = self._execute_collaboration(
                session_id=session_id,
                live=live,
                invocation=invocation,
            )
        elif canonical == "room_integrate":
            result, execution_receipt = self._execute_integration(
                session_id=session_id,
                live=live,
                invocation=invocation,
            )
        elif canonical == "room_post":
            result, execution_receipt = self._execute_post(
                session_id=session_id,
                live=live,
                invocation=invocation,
            )
        elif canonical == "room_define":
            result, execution_receipt = self._execute_define(
                session_id=session_id,
                live=live,
                invocation=invocation,
            )
        else:
            result = {
                "accepted": True,
                "executionPerformed": False,
                "settlementStaged": True,
                "terminalForModelTurn": True,
                "canonicalTool": canonical,
                "invocationReceiptId": invocation["receiptId"],
                "next": "end_model_turn_for_before_agent_settle",
                "modelInstruction": (
                    "room_commit 已被受管层持久暂存。现在立即结束本轮；"
                    "不要再调用 room_state、room_post、room_commit 或其他工具，"
                    "before_agent_settle 会执行唯一提交。"
                ),

            }
        response = {
            "ok": True,
            "created": created,
            "result": result,
            "invocationReceipt": invocation,
        }
        if execution_receipt is not None:
            response["executionReceipt"] = execution_receipt
        return response
    def _execute_define(
        self,
        *,
        session_id: str,
        live: Mapping[str, object],
        invocation: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        if self.define_room is None:
            raise RoomKernelFenceError("room_define is not wired to Room intake")
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if not isinstance(arguments, Mapping):
            raise RoomKernelFenceError(
                "room_define invocation has no canonical arguments"
            )
        invocation_receipt_id = str(invocation["receiptId"])
        result = self.define_room(
            str(live["roomId"]),
            dispatch_id=str(live["dispatchId"]),
            invocation_receipt_id=invocation_receipt_id,
            arguments=arguments,
        )
        alignment_post = result.get("alignmentPost")
        if isinstance(alignment_post, Mapping):
            room = self.rooms.get(str(live["roomId"]))
            self.public_timeline.publish_post(
                alignment_post,
                participant_id=str(alignment_post["authorActorRef"]),
                source_session_id=session_id,
                topic_id=str(room.get("activeTopicId") or ""),
            )
        result = {
            **result,
            "executionPerformed": True,
            "terminalForModelTurn": True,
            "next": (
                "await_typed_start_action"
                if result.get("requiresStartAction") is True
                else "end_model_turn_for_execute_dispatch"
            ),
            "modelInstruction": (
                "需求定义已持久化，旧对齐能力已封存。现在立即结束本轮；"
                "不要继续调用任何工具。"
            ),
        }
        completed_at_ms = int(time.time() * 1000)
        result_hash = hashlib.sha256(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        execution_receipt, _ = self.capabilities.record_runtime_execution(
            session_id=session_id,
            invocation_receipt_id=invocation_receipt_id,
            status="applied",
            result_hash=result_hash,
            created_at_ms=completed_at_ms,
        )
        # Preserve the room_define execution receipt before revoking the old
        # alignment capability.  Only after that fence is durable may the new
        # ExecuteDispatch become visible to the worker.
        self.revoke_session(session_id, completed_at_ms)
        if isinstance(result.get("executionDispatch"), Mapping):
            self.wake_worker()
        return result, execution_receipt

    def _execute_post(
        self,
        *,
        session_id: str,
        live: Mapping[str, object],
        invocation: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if not isinstance(arguments, Mapping):
            raise RoomKernelFenceError(
                "Room Post invocation has no canonical arguments"
            )
        kind = str(arguments.get("kind") or "").strip()
        if kind == "question":
            raise RoomKernelFenceError(
                "需要用户回答的问题必须用 room_commit(decision=wait) 发布并结束本轮；"
                "room_post 只能发布非终态进展"
            )
        dispatch = self.kernel.dispatch(str(live["dispatchId"]))
        root = self.kernel.root(str(live["rootId"]))
        room = self.rooms.get(str(live["roomId"]))
        refs = participant_ref_map(room["participants"])
        raw_mentions = arguments.get("mentions") or []
        if not isinstance(raw_mentions, list):
            raise RoomKernelFenceError("Room Post mentions must be an array")
        try:
            mentions = [
                resolve_participant_ref(value, refs)
                for value in raw_mentions
            ]
        except ParticipantReferenceError as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        receipt_id = str(invocation["receiptId"])
        post_id = _stable_id("room-post", receipt_id)
        now_ms = int(time.time() * 1000)
        try:
            public_content = public_room_report_content(
                arguments.get("content"),
                field_name="room_post.content",
            )
        except ValueError as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        post: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": post_id,
            "roomId": root["roomId"],
            "rootId": root["rootId"],
            "generation": root["generation"],
            "taskId": dispatch["taskId"],
            "dispatchId": dispatch["dispatchId"],
            "authorActorRef": dispatch["targetParticipantId"],
            "kind": kind,
            "visibility": "room",
            "content": public_content,
            "mentions": list(dict.fromkeys(mentions)),
            "idempotencyKey": post_id,
            "publicationSource": {
                "kind": "room_post",
                "ref": receipt_id,
            },
            "createdAtMs": now_ms,
        }
        if arguments.get("blocks") is not None:
            post["blocks"] = list(
                normalize_trusted_agent_blocks(
                    arguments["blocks"],
                    source_kind="room_post",
                    source_ref=receipt_id,
                    visibility="room_post",
                    generation=int(root["generation"]),
                )
            )
        published, created = self.context.publish_post(post)
        self.public_timeline.publish_post(
            published,
            participant_id=str(dispatch["targetParticipantId"]),
            source_session_id=str(dispatch["targetSessionId"]),
            topic_id=str(room.get("activeTopicId") or ""),
        )
        result = {
            "published": True,
            "postRef": post_id,
            "deduplicated": not created,
            "currentResponsibilityContinues": True,
        }
        execution_receipt, _ = self.capabilities.record_runtime_execution(
            session_id=session_id,
            invocation_receipt_id=receipt_id,
            status="applied",
            result_hash=hashlib.sha256(
                json.dumps(
                    published,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            created_at_ms=now_ms,
        )
        return result, execution_receipt
    def prepare_review_handoff_task(
        self,
        *,
        parent_dispatch: Mapping[str, object],
        parent_task: Mapping[str, object],
        target_participant_id: str,
        evidence_refs: Sequence[str],
        child_task: Mapping[str, object],
        pending_parent_task: Mapping[str, object],
        now_ms: int,
        parent_commit_id: str,
    ) -> dict[str, object]:
        """Bind one post-integration Reviewer Task to the authoritative workspace."""

        root = self.kernel.root(str(parent_dispatch["rootId"]))
        facilitator_id = str(root.get("facilitatorParticipantId") or "")
        caller_id = str(parent_dispatch.get("targetParticipantId") or "")
        if caller_id != facilitator_id:
            raise RoomKernelFenceError(
                "only the Root Facilitator may request final independent review"
            )
        room = self.rooms.get(str(root["roomId"]))
        target = next(
            (
                item
                for item in room.get("participants", ())
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == target_participant_id
                and item.get("status") == "active"
            ),
            None,
        )
        if target is None or not str(target.get("sessionId") or "").strip():
            raise RoomKernelFenceError(
                "final independent review target has no active Session"
            )
        children = self.kernel.collaboration_children(str(root["rootId"]))
        active_states = {"pending", "leased", "running", "waiting"}
        if any(
            str(dispatch.get("intentKind") or "") == "review"
            and str(dispatch.get("state") or "") in active_states
            for dispatch in children
        ):
            raise RoomKernelFenceError(
                "an independent review is already active; wait for it"
            )
        review_task_ids = [str(parent_task["taskId"])]
        review_author_ids = {facilitator_id}
        for dispatch in children:
            intent = str(dispatch.get("intentKind") or "")
            if intent not in {"execute", "revise"}:
                continue
            task = self.kernel.task(str(dispatch["taskId"]))
            if str(dispatch.get("state") or "") != "committed" or (
                dispatch.get("resultPublic") is not True
            ):
                raise RoomKernelFenceError(
                    "all implementation and inspection Tasks must publish results "
                    "before final review"
                )
            policy = str(task.get("workspacePolicy") or "")
            review_task_ids.append(str(task["taskId"]))
            review_author_ids.add(str(task["currentOwnerParticipantId"]))
            if (
                policy == "isolated_writable"
                and task.get("workspaceIntegrationState") != "applied"
            ):
                raise RoomKernelFenceError(
                    "all isolated writable Tasks must be integrated before review"
                )
        if target_participant_id in review_author_ids:
            raise RoomKernelFenceError(
                "final Reviewer must not have authored or integrated the deliverable"
            )
        evidence_tools = self.capabilities.runtime_evidence_tools(
            session_id=str(parent_dispatch["targetSessionId"]),
            dispatch_id=str(parent_dispatch["dispatchId"]),
        )
        normalized_evidence = {
            str(value)
            for value in evidence_refs
            if str(value or "").strip()
        }
        if not any(
            evidence_tools.get(ref)
            in {"workspace_read", "workspace_search", "workspace_shell"}
            for ref in normalized_evidence
        ):
            raise RoomKernelFenceError(
                "final review requires fresh Facilitator evidence from the integrated workspace"
            )

        base_roots = [
            str(value)
            for value in room.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if self.workspaces is None:
            raise RoomKernelFenceError(
                "final independent review requires a workspace identity coordinator"
            )
        try:
            prepared_workspace = self.workspaces.prepare(
                root_id=str(root["rootId"]),
                task_id=str(child_task["taskId"]),
                target_session_id=str(target["sessionId"]),
                base_roots=base_roots,
                policy="read_only",
            )
        except RoomWorkspaceError as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        prepared = {
            **dict(child_task),
            "reviewOfTaskIds": list(dict.fromkeys(review_task_ids)),
            "reviewAuthorParticipantIds": sorted(review_author_ids),
            "reviewState": "required",
            "reviewEvidenceNotBeforeMs": max(0, int(now_ms)),
            "reviewRound": 1,
            "reviewFindings": [],
            **prepared_workspace,
        }
        prepared["reviewTargetRevision"] = self.kernel.review_target_revision(
            root_id=str(root["rootId"]),
            task_ids=review_task_ids,
            pending_commit_ids={
                str(parent_task["taskId"]): parent_commit_id
            },
            pending_task_snapshots={
                str(parent_task["taskId"]): pending_parent_task
            },
            review_snapshot=prepared,
        )
        validate_kernel_contract("roomTask", prepared)
        return prepared

    def prepare_revision_handoff_task(
        self,
        *,
        parent_dispatch: Mapping[str, object],
        parent_task: Mapping[str, object],
        target_participant_id: str,
        child_task: Mapping[str, object],
        review_findings: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        """Return an independent review finding to the Root Facilitator."""

        root = self.kernel.root(str(parent_dispatch["rootId"]))
        if str(parent_task.get("taskKind") or "") != "review":
            raise RoomKernelFenceError(
                "managed revision handoff requires an active Reviewer Task"
            )
        room = self.rooms.get(str(root["roomId"]))
        caller_id = str(parent_dispatch.get("targetParticipantId") or "")
        caller = next(
            (
                item
                for item in room.get("participants", ())
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == caller_id
                and item.get("status") == "active"
            ),
            None,
        )
        if caller is None or caller_id != str(
            parent_task.get("currentOwnerParticipantId") or ""
        ):
            raise RoomKernelFenceError(
                "only the active Reviewer may return a revision handoff"
            )
        facilitator_id = str(root.get("facilitatorParticipantId") or "")
        if target_participant_id != facilitator_id:
            raise RoomKernelFenceError(
                "Reviewer revisions must return to the Root Facilitator"
            )
        target = next(
            (
                item
                for item in room.get("participants", ())
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == target_participant_id
                and item.get("status") == "active"
            ),
            None,
        )
        if target is None or not str(target.get("sessionId") or "").strip():
            raise RoomKernelFenceError(
                "revision Facilitator has no active Session"
            )
        base_roots = [
            str(value)
            for value in room.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if self.workspaces is None:
            prepared_workspace: dict[str, object] = {
                "workspacePolicy": "shared_single_writer",
                "workspaceRoot": base_roots[0] if base_roots else ".",
                "workspaceBaseRoot": base_roots[0] if base_roots else ".",
                "workspaceIntegrationState": "not_required",
            }
        else:
            try:
                prepared_workspace = self.workspaces.prepare(
                    root_id=str(root["rootId"]),
                    task_id=str(child_task["taskId"]),
                    target_session_id=str(target["sessionId"]),
                    base_roots=base_roots,
                    policy="shared_single_writer",
                )
            except RoomWorkspaceError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
        prepared = {
            **dict(child_task),
            "reviewOfTaskIds": list(
                parent_task.get("reviewOfTaskIds") or []
            ),
            "reviewAuthorParticipantIds": list(
                parent_task.get("reviewAuthorParticipantIds") or []
            ),
            "reviewTargetRevision": str(
                parent_task.get("reviewTargetRevision") or ""
            ),
            "reviewRound": int(parent_task.get("reviewRound") or 1),
            "reviewFindings": [dict(item) for item in review_findings],
            "reviewState": "not_required",
            **prepared_workspace,
        }
        validate_kernel_contract("roomTask", prepared)
        return prepared

    def _execute_collaboration(
        self,
        *,
        session_id: str,
        live: Mapping[str, object],
        invocation: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        invocation_receipt_id = str(invocation["receiptId"])
        parent_dispatch_id = str(live["dispatchId"])
        self._assert_room_collaboration_authority(live)
        parent = self.kernel.dispatch(parent_dispatch_id)
        parent_task = self.kernel.task(str(parent["taskId"]))
        root = self.kernel.root(str(parent["rootId"]))
        room = self.rooms.get(str(live["roomId"]))
        prior_execution = self.capabilities.execution_receipt(
            invocation_receipt_id
        )
        prior_kernel = self.kernel.collaboration_receipt(
            parent_dispatch_id=parent_dispatch_id,
            invocation_receipt_id=invocation_receipt_id,
        )
        if prior_kernel is not None:
            result = _collaboration_tool_result(invocation, prior_kernel)
            child_task_id = str(result.get("childTaskId") or "")
            try:
                child_task = self.kernel.task(child_task_id)
            except (KeyError, ValueError):
                child_task = {}
            if (
                self.workspaces is not None
                and child_task.get("workspacePolicy") == "isolated_writable"
                and child_task.get("workspaceLifecycleState")
                in {"reserved", "materialized", "retry_bound"}
            ):
                child_dispatch_id = str(
                    result.get("childDispatchId") or ""
                )
                try:
                    workspace_started = self.workspaces.record_work_started(
                        child_task,
                        dispatch_id=child_dispatch_id,
                        actor_ref=str(
                            child_task.get("currentOwnerParticipantId") or ""
                        ),
                        now_ms=int(time.time() * 1000),
                    )
                    child_task = self.kernel.record_workspace_work_started(
                        child_task_id,
                        lifecycle=workspace_started,
                        dispatch_id=child_dispatch_id,
                        now_ms=int(time.time() * 1000),
                    )
                except RoomWorkspaceError as exc:
                    raise RoomKernelFenceError(str(exc)) from exc
            result["workspaceRoot"] = child_task.get("workspaceRoot")
            if prior_execution is None:
                prior_execution, _ = self.capabilities.record_runtime_execution(
                    session_id=session_id,
                    invocation_receipt_id=invocation_receipt_id,
                    status="applied",
                    result_hash=hashlib.sha256(
                        json.dumps(
                            result,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    created_at_ms=int(time.time() * 1000),
                )
            return result, prior_execution
        if prior_execution is not None:
            raise RoomKernelFenceError(
                "Room collaboration execution has no canonical Kernel receipt"
            )

        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if not isinstance(arguments, Mapping):
            raise RoomKernelFenceError(
                "Room collaboration invocation has no canonical arguments"
            )
        raw_acceptance = arguments.get("acceptance") or []
        if not isinstance(raw_acceptance, list):
            raise RoomKernelFenceError(
                "Room collaboration acceptance must be an array"
            )
        participant_refs = participant_ref_map(room["participants"])
        alias_map = acceptance_alias_map(
            parent_task.get("acceptanceCriterionIds") or []
        )
        try:
            target_participant_id = resolve_participant_ref(
                arguments.get("targetParticipantRef"),
                participant_refs,
            )
            criteria = resolve_acceptance_aliases(
                raw_acceptance,
                alias_map,
            )
        except (AcceptanceAliasError, ParticipantReferenceError) as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        target = next(
            (
                item
                for item in room.get("participants", ())
                if isinstance(item, Mapping)
                and str(item.get("id") or "") == target_participant_id
            ),
            None,
        )
        if target is None or not str(target.get("sessionId") or "").strip():
            raise RoomKernelFenceError(
                "Room collaboration target has no active Session"
            )
        evidence_refs = arguments.get("evidenceRefs") or []
        if not isinstance(evidence_refs, list):
            raise RoomKernelFenceError(
                "Room collaboration evidenceRefs must be an array"
            )
        normalized_evidence = [
            str(value)
            for value in evidence_refs
            if str(value or "").strip()
        ]
        intent = str(arguments.get("intent") or "execute")
        workspace_policy = str(arguments.get("workspacePolicy") or "")
        if workspace_policy not in {
            "read_only",
            "shared_single_writer",
            "isolated_writable",
        }:
            raise RoomKernelFenceError(
                "Room collaboration requires an explicit workspacePolicy"
            )
        if workspace_policy == "shared_single_writer":
            raise RoomKernelFenceError(
                "room_collaborate keeps the parent active; writable child work "
                "must use isolated_writable"
            )
        if intent == "review":
            raise RoomKernelFenceError(
                "final independent review uses room_commit handoff after integration, "
                "not room_collaborate"
            )
        if intent == "revise" and workspace_policy == "read_only":
            raise RoomKernelFenceError(
                "revision work requires a writable workspace policy"
            )

        children = self.kernel.collaboration_children(str(root["rootId"]))
        child_records = [
            (child, self.kernel.task(str(child["taskId"])))
            for child in children
        ]
        active_states = {"pending", "leased", "running", "waiting"}
        if any(
            str(child.get("targetParticipantId") or "")
            == target_participant_id
            and str(child.get("intentKind") or "") == intent
            and str(child.get("state") or "") in active_states
            for child, _task in child_records
        ):
            raise RoomKernelFenceError(
                "the selected participant already has active matching Room work; wait for it"
            )
        if workspace_policy == "shared_single_writer" and any(
            str(child.get("state") or "") in active_states
            and str(task.get("workspacePolicy") or "")
            == "shared_single_writer"
            for child, task in child_records
        ):
            raise RoomKernelFenceError(
                "another shared_single_writer Task is active; wait or use isolated_writable"
            )

        objective = str(arguments.get("objective") or "")
        trigger_id = _stable_id(
            "room-collaboration",
            parent_dispatch_id,
            target_participant_id,
            " ".join(objective.split()),
        )
        now_ms = int(time.time() * 1000)
        try:
            continuation = self.continuations.build(
                parent_dispatch=parent,
                parent_task=parent_task,
                room_id=str(live["roomId"]),
                target_participant_id=target_participant_id,
                trigger_id=trigger_id,
                intent_kind=intent,
                objective=objective,
                expected_output=str(arguments.get("expectedOutput") or ""),
                acceptance_criterion_ids=criteria,
                context_evidence_refs=normalized_evidence,
                kind="collaboration",
                now_ms=now_ms,
            )
        except RoomContinuationProposalError as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        child_task = dict(continuation["childTask"])
        prepared_workspace: dict[str, object]
        base_roots = [
            str(value)
            for value in room.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if self.workspaces is None:
            if workspace_policy in {"read_only", "isolated_writable"}:
                raise RoomKernelFenceError(
                    "Room workspace identity coordinator is unavailable"
                )
            prepared_workspace = {
                "workspacePolicy": workspace_policy,
                "workspaceRoot": base_roots[0] if base_roots else ".",
                "workspaceBaseRoot": base_roots[0] if base_roots else ".",
                "workspaceIntegrationState": "not_required",
                "workspaceIntegrationRef": None,
            }
        else:
            try:
                definition = self.kernel.definition_fence(
                    root_id=str(root["rootId"])
                ) or {}
                prepared_workspace = self.workspaces.prepare(
                    root_id=str(root["rootId"]),
                    task_id=str(child_task["taskId"]),
                    target_session_id=str(target["sessionId"]),
                    base_roots=base_roots,
                    policy=workspace_policy,
                    room_id=str(room["id"]),
                    work_item_id=str(
                        definition.get("workItemId") or child_task["taskId"]
                    ),
                    dispatch_id=str(
                        continuation["childDispatch"]["dispatchId"]
                    ),
                    requirement_revision=str(
                        definition.get("catalogRevisionId") or ""
                    ),
                    acceptance_aliases=[
                        str(value)
                        for value in raw_acceptance
                        if str(value).strip()
                    ],
                    participant_id=target_participant_id,
                    creation_reason=(
                        "Facilitator assigned bounded Room work: "
                        + " ".join(objective.split())[:500]
                    ),
                    now_ms=now_ms,
                )
            except RoomWorkspaceError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
        child_task.update(prepared_workspace)
        try:
            kernel_receipt = self.kernel.enqueue_collaboration(
                parent_dispatch_id=parent_dispatch_id,
                child_task=child_task,
                child_dispatch=continuation["childDispatch"],
                generation=int(live["generation"]),
                invocation_receipt_id=invocation_receipt_id,
                now_ms=now_ms,
            )
        except BaseException:
            if self.workspaces is not None:
                self.workspaces.discard(prepared_workspace)
                self.workspaces.restore(
                    session_id=str(target["sessionId"]),
                    base_roots=base_roots,
                    restore_policy=(
                        prepared_workspace.get("workspaceRestorePolicy")
                        if isinstance(
                            prepared_workspace.get("workspaceRestorePolicy"),
                            Mapping,
                        )
                        else None
                    ),
                )
            raise
        if (
            self.workspaces is not None
            and child_task.get("workspacePolicy") == "isolated_writable"
        ):
            try:
                workspace_started = self.workspaces.record_work_started(
                    child_task,
                    dispatch_id=str(
                        continuation["childDispatch"]["dispatchId"]
                    ),
                    actor_ref=target_participant_id,
                    now_ms=now_ms,
                )
                self.kernel.record_workspace_work_started(
                    str(child_task["taskId"]),
                    lifecycle=workspace_started,
                    dispatch_id=str(
                        continuation["childDispatch"]["dispatchId"]
                    ),
                    now_ms=now_ms,
                )
            except RoomWorkspaceError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
        result = {
            **_collaboration_tool_result(invocation, kernel_receipt),
            "workspacePolicy": workspace_policy,
            "workspaceRoot": prepared_workspace.get("workspaceRoot"),
        }
        execution_receipt, _ = self.capabilities.record_runtime_execution(
            session_id=session_id,
            invocation_receipt_id=invocation_receipt_id,
            status="applied",
            result_hash=hashlib.sha256(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            created_at_ms=now_ms,
        )
        self.wake_worker()
        return result, execution_receipt

    def _execute_integration(
        self,
        *,
        session_id: str,
        live: Mapping[str, object],
        invocation: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object] | None]:
        if self.workspaces is None:
            raise RoomKernelFenceError(
                "Room workspace integration coordinator is unavailable"
            )
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if not isinstance(arguments, Mapping):
            raise RoomKernelFenceError(
                "Room integration invocation has no canonical arguments"
            )
        action = str(arguments.get("action") or "integrate").strip()
        if action not in {"integrate", "retry", "abandon"}:
            raise RoomKernelFenceError(
                "Room workspace action must be integrate, retry, or abandon"
            )
        task_id = str(arguments.get("childTaskId") or "").strip()
        task = self.kernel.task(task_id)
        root = self.kernel.root(str(live["rootId"]))
        dispatch = self.kernel.dispatch(str(live["dispatchId"]))
        if (
            task.get("rootId") != root.get("rootId")
            or str(dispatch.get("targetParticipantId") or "")
            != str(root.get("facilitatorParticipantId") or "")
            or task.get("workspacePolicy") != "isolated_writable"
        ):
            raise RoomKernelFenceError(
                "only the Root Facilitator may act on its isolated child worktree"
            )
        invocation_receipt_id = str(invocation["receiptId"])
        prior = self.capabilities.execution_receipt(invocation_receipt_id)
        now_ms = int(time.time() * 1000)
        room = self.rooms.get(str(live["roomId"]))
        integration_authority: Mapping[str, object] | None = None
        if action == "integrate":
            integration_authority = self.kernel.workspace_integration_authority(
                task_id
            )
            authority_status = str(
                integration_authority.get("status") or "invalid"
            )
            if authority_status not in {
                "ready",
                "accepted",
                "pending_cleanup",
            }:
                raise RoomKernelFenceError(
                    "Room workspace has no valid canonical integration authority"
                )
        if prior is not None:
            if action == "integrate" and authority_status == "accepted":
                return {
                    "action": "integrate",
                    "childTaskId": task_id,
                    "integrated": True,
                    "integrationRef": integration_authority.get(
                        "integrationRef"
                    ),
                    "workspaceLifecycleState": task.get(
                        "workspaceLifecycleState"
                    ),
                    "cleanupState": task.get("workspaceCleanupState"),
                    "attentionRequired": bool(
                        task.get("workspaceAttentionRequired")
                    ),
                    "idempotent": True,
                }, prior
            if action == "integrate" and authority_status == "pending_cleanup":
                pass
            if action == "retry":
                recovered = self.kernel.recover_workspace_retry(
                    parent_dispatch_id=str(dispatch["dispatchId"]),
                    task_id=task_id,
                    retry_dispatch=None,
                    invocation_receipt_id=invocation_receipt_id,
                )
                if recovered is None:
                    raise RoomKernelFenceError(
                        "Room workspace retry receipt lost its canonical Kernel outcome"
                    )
                details = recovered["receipt"].get("details")
                if not isinstance(details, Mapping):
                    raise RoomKernelFenceError(
                        "Room workspace retry receipt has no canonical details"
                    )
                return {
                    "action": "retry",
                    "childTaskId": task_id,
                    "retryScheduled": True,
                    "workspaceLifecycleState": recovered["task"].get(
                        "workspaceLifecycleState"
                    ),
                    "attentionRequired": False,
                    "targetParticipantRef": details.get(
                        "targetParticipantRef"
                    ),
                }, prior
            if (
                action == "abandon"
                and task.get("workspaceLifecycleState")
                in {"abandoned", "cleanup_failed"}
            ):
                cleanup_state = str(
                    task.get("workspaceCleanupState") or ""
                )
                return {
                    "action": "abandon",
                    "childTaskId": task_id,
                    "abandoned": True,
                    "abandonmentAuthorized": True,
                    "physicalCleanupCompleted": cleanup_state
                    in {"cleaned", "missing"},
                    "workspaceLifecycleState": task.get(
                        "workspaceLifecycleState"
                    ),
                    "cleanupState": cleanup_state,
                    "attentionRequired": bool(
                        task.get("workspaceAttentionRequired")
                    ),
                }, prior
            if action != "integrate" or authority_status != "pending_cleanup":
                raise RoomKernelFenceError(
                    "Room workspace replay has no matching canonical Task state"
                )

        if action == "retry":
            reason = str(arguments.get("reason") or "").strip()
            if not reason:
                raise RoomKernelFenceError(
                    "workspace retry requires a reason"
                )
            participants = {
                str(value.get("id") or ""): value
                for value in room.get("participants") or []
                if isinstance(value, Mapping)
                and value.get("status") == "active"
            }
            target_participant_id = str(
                task.get("currentOwnerParticipantId") or ""
            )
            target_ref = str(
                arguments.get("targetParticipantRef") or ""
            ).strip()
            if target_ref:
                try:
                    target_participant_id = resolve_participant_ref(
                        target_ref,
                        participant_ref_map(room["participants"]),
                    )
                except ParticipantReferenceError as exc:
                    raise RoomKernelFenceError(str(exc)) from exc
            target = participants.get(target_participant_id)
            if target is None or not str(target.get("sessionId") or "").strip():
                raise RoomKernelFenceError(
                    "workspace retry target has no active Room Session"
                )
            target_session_id = str(target["sessionId"])
            resolved_target_ref = ref_for_participant(
                target_participant_id,
                participant_ref_map(room["participants"]),
            )
            if not resolved_target_ref:
                raise RoomKernelFenceError(
                    "workspace retry target has no active participant reference"
                )
            retry_dispatch = {
                "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
                "dispatchId": _stable_id(
                    "room-workspace-retry-dispatch",
                    invocation_receipt_id,
                    task_id,
                ),
                "rootId": root["rootId"],
                "taskId": task_id,
                "parentDispatchId": dispatch["dispatchId"],
                "generation": root["generation"],
                "hopCount": int(dispatch["hopCount"]) + 1,
                "depth": int(dispatch["depth"]) + 1,
                "budgetCost": 1,
                "targetSessionId": target_session_id,
                "targetParticipantId": target_participant_id,
                "triggerId": invocation_receipt_id,
                "intentKind": "retry",
                "idempotencyKey": _stable_id(
                    "room-workspace-retry",
                    invocation_receipt_id,
                    task_id,
                ),
                "attempt": 0,
                "capabilityEpoch": int(dispatch["capabilityEpoch"]),
                "runtimeProfileRevision": (
                    f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                    f"{target.get('roleId')}@"
                    f"{target.get('roleVersion') or '1'}"
                ),
                "state": "pending",
            }
            try:
                retried = self.kernel.recover_workspace_retry(
                    parent_dispatch_id=str(dispatch["dispatchId"]),
                    task_id=task_id,
                    retry_dispatch=retry_dispatch,
                    invocation_receipt_id=invocation_receipt_id,
                )
                if retried is None:
                    rebound = self.workspaces.retry_retained(
                        binding_id=str(task.get("workspaceBindingId") or ""),
                        participant_id=target_participant_id,
                        participant_ref=resolved_target_ref,
                        session_id=target_session_id,
                        reason=reason,
                        now_ms=now_ms,
                    )
                    rebound = {
                        **rebound,
                        "targetParticipantRef": resolved_target_ref,
                    }
                    retried = self.kernel.enqueue_workspace_retry(
                        parent_dispatch_id=str(dispatch["dispatchId"]),
                        task_id=task_id,
                        retry_dispatch=retry_dispatch,
                        workspace_result=rebound,
                        invocation_receipt_id=invocation_receipt_id,
                        now_ms=now_ms,
                    )
            except (RoomWorkspaceError, RoomKernelFenceError) as exc:
                try:
                    retained = self.workspaces.retain_task(
                        task,
                        state="failed",
                        reason=(
                            "workspace retry could not enqueue its bounded work: "
                            + str(exc)
                        ),
                        actor_ref=str(root["facilitatorParticipantId"]),
                        now_ms=now_ms,
                    )
                    self.kernel.record_workspace_lifecycle(
                        task_id,
                        operation="retain",
                        workspace_result=retained,
                        now_ms=now_ms,
                    )
                finally:
                    self.workspaces.restore(
                        session_id=target_session_id,
                        base_roots=[
                            str(value)
                            for value in room.get("workspaceRoots") or []
                            if str(value).strip()
                        ],
                        restore_policy=(
                            task.get("workspaceRestorePolicy")
                            if isinstance(
                                task.get("workspaceRestorePolicy"), Mapping
                            )
                            else None
                        ),
                    )
                raise RoomKernelFenceError(str(exc)) from exc
            result = {
                "action": "retry",
                "childTaskId": task_id,
                "retryScheduled": True,
                "workspaceLifecycleState": retried["task"].get(
                    "workspaceLifecycleState"
                ),
                "attentionRequired": False,
                "targetParticipantRef": ref_for_participant(
                    target_participant_id,
                    participant_ref_map(room["participants"]),
                ),
            }
            self.wake_worker()
        elif action == "abandon":
            reason = str(arguments.get("reason") or "").strip()
            raw_acceptance = arguments.get("acceptance")
            if not reason or not isinstance(raw_acceptance, list):
                raise RoomKernelFenceError(
                    "workspace abandonment requires reason and acceptance aliases"
                )
            try:
                criteria = resolve_acceptance_aliases(
                    raw_acceptance,
                    acceptance_alias_map(
                        task.get("acceptanceCriterionIds") or []
                    ),
                    field_name="acceptance",
                )
            except AcceptanceAliasError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
            if not criteria:
                raise RoomKernelFenceError(
                    "workspace abandonment requires acceptance aliases"
                )
            try:
                abandoned = self.workspaces.abandon_retained(
                    binding_id=str(task.get("workspaceBindingId") or ""),
                    reason=reason,
                    acceptance_aliases=criteria,
                    actor_ref=str(root["facilitatorParticipantId"]),
                    now_ms=now_ms,
                )
                projected = self.kernel.record_workspace_lifecycle(
                    task_id,
                    operation="abandon",
                    workspace_result=abandoned,
                    now_ms=now_ms,
                )
            except RoomWorkspaceError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
            owner = next(
                (
                    value
                    for value in room.get("participants") or []
                    if isinstance(value, Mapping)
                    and value.get("id")
                    == task.get("currentOwnerParticipantId")
                ),
                None,
            )
            if isinstance(owner, Mapping) and str(
                owner.get("sessionId") or ""
            ).strip():
                self.workspaces.restore(
                    session_id=str(owner["sessionId"]),
                    base_roots=[
                        str(value)
                        for value in room.get("workspaceRoots") or []
                        if str(value).strip()
                    ],
                    restore_policy=(
                        task.get("workspaceRestorePolicy")
                        if isinstance(
                            task.get("workspaceRestorePolicy"), Mapping
                        )
                        else None
                    ),
                )
            result = {
                "action": "abandon",
                "childTaskId": task_id,
                "abandoned": True,
                "abandonmentAuthorized": bool(
                    abandoned.get("abandonmentAuthorized")
                ),
                "physicalCleanupCompleted": bool(
                    abandoned.get("physicalCleanupCompleted")
                ),
                "workspaceLifecycleState": projected.get(
                    "workspaceLifecycleState"
                ),
                "cleanupState": projected.get("workspaceCleanupState"),
                "attentionRequired": bool(
                    projected.get("workspaceAttentionRequired")
                ),
            }
        else:
            assert integration_authority is not None
            authority_status = str(
                integration_authority.get("status") or "invalid"
            )
            canonical_integration_ref = str(
                integration_authority.get("integrationRef") or ""
            ).strip()
            integration_ref = (
                canonical_integration_ref
                if authority_status in {"accepted", "pending_cleanup"}
                else _stable_id(
                    "room-workspace-integration",
                    invocation_receipt_id,
                    task_id,
                )
            )
            if authority_status == "accepted":
                result = {
                    "action": "integrate",
                    "childTaskId": task_id,
                    "integrated": True,
                    "integrationRef": integration_ref,
                    "workspaceLifecycleState": task.get(
                        "workspaceLifecycleState"
                    ),
                    "cleanupState": task.get("workspaceCleanupState"),
                    "attentionRequired": bool(
                        task.get("workspaceAttentionRequired")
                    ),
                    "idempotent": True,
                }
            else:
                try:
                    integrated = self.workspaces.integrate(
                        task,
                        integration_ref=integration_ref,
                        actor_ref=str(root["facilitatorParticipantId"]),
                        now_ms=now_ms,
                    )
                except RoomWorkspaceError as exc:
                    binding_id = str(task.get("workspaceBindingId") or "").strip()
                    if binding_id:
                        try:
                            retained = self.workspaces.ledger.binding(binding_id)
                        except Exception:
                            retained = {}
                        self.kernel.record_workspace_integration_failure(
                            task_id,
                            integration_ref=integration_ref,
                            workspace_result={
                                "integrated": False,
                                "workspaceBindingId": binding_id,
                                "workspaceLifecycleState": str(
                                    retained.get("workspaceLifecycleState")
                                    or task.get("workspaceLifecycleState")
                                    or "retained"
                                ),
                                "cleanupState": str(
                                    retained.get("cleanupState")
                                    or task.get("workspaceCleanupState")
                                    or "retained"
                                ),
                                "reason": str(exc)[:2_000],
                                "attentionRequired": True,
                            },
                            now_ms=now_ms,
                        )
                    raise RoomKernelFenceError(str(exc)) from exc
                self.kernel.record_workspace_integration(
                    task_id,
                    integration_ref=integration_ref,
                    workspace_result=integrated,
                    now_ms=now_ms,
                )
                result = {
                    **integrated,
                    "action": "integrate",
                    "childTaskId": task_id,
                    "integrationRef": (
                        integration_ref
                        if integrated.get("integrated") is True
                        else None
                    ),
                }
            if (
                result.get("integrated") is True
                and str(result.get("cleanupState") or "")
                not in {"cleaned", "missing"}
            ):
                return result, None
        execution_receipt, _ = self.capabilities.record_runtime_execution(
            session_id=session_id,
            invocation_receipt_id=invocation_receipt_id,
            status="applied",
            result_hash=hashlib.sha256(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            created_at_ms=now_ms,
        )
        return result, execution_receipt

    def authorize_product_tool(
        self,
        session_id: str,
        tool_name: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        load_receipt_id: str,
    ) -> dict[str, object] | None:
        authorized = self._authorize_capability_invocation(
            session_id,
            tool_name,
            args,
            tool_call_id=tool_call_id,
            load_receipt_id=load_receipt_id,
        )
        if authorized is None:
            return None
        _live, invocation, created = authorized
        canonical = str(invocation["canonicalCommand"]["tool"])
        if canonical in ROOM_PUBLIC_TOOLS:
            raise ToolAuthorizationError(
                "canonical Room Tools must execute through Room Kernel"
            )
        existing_execution = self.capabilities.execution_receipt(
            str(invocation["receiptId"])
        )
        if existing_execution is not None:
            raise ToolAuthorizationError(
                "Room product Tool invocation already has a terminal "
                "execution receipt; reuse its evidence instead of executing "
                f"again ({existing_execution['executionReceiptId']})"
            )
        replay = self.capabilities.failed_command_replay(
            session_id=session_id,
            dispatch_id=str(_live["dispatchId"]),
            invocation_receipt_id=str(invocation["receiptId"]),
        )
        if replay is not None:
            prior_receipt_id = str(
                replay.get("executionReceiptId") or ""
            )
            reason = {
                "reason": "duplicate_failed_invocation",
                "priorExecutionReceiptId": prior_receipt_id,
                "retryable": False,
            }
            self.capabilities.record_runtime_execution(
                session_id=session_id,
                invocation_receipt_id=str(invocation["receiptId"]),
                status="rejected",
                result_hash=hashlib.sha256(
                    json.dumps(
                        reason,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                created_at_ms=int(time.time() * 1000),
            )
            raise ToolAuthorizationError(
                "duplicate failed Room Tool command blocked; inspect the "
                "previous failure or produce new successful Tool evidence "
                f"before retrying ({prior_receipt_id})"
            )
        return {
            "ok": True,
            "created": created,
            "invocationReceipt": invocation,
        }

    def record_product_tool_execution(
        self,
        session_id: str,
        invocation_receipt_id: str,
        *,
        status: str,
        result_hash: str,
    ) -> dict[str, object]:
        self._active_capability_binding(session_id)
        receipt, created = self.capabilities.record_runtime_execution(
            session_id=session_id,
            invocation_receipt_id=invocation_receipt_id,
            status=status,
            result_hash=result_hash,
            created_at_ms=int(time.time() * 1000),
        )
        return {"ok": True, "created": created, "executionReceipt": receipt}

    def validate_product_tool_approval(
        self,
        session_id: str,
        invocation_receipt_id: str,
        *,
        tool_name: str,
    ) -> dict[str, object]:
        try:
            active = self._active_capability_binding(session_id)
        except ToolAuthorizationError as exc:
            raise RoomKernelFenceError(
                "Room approval lost its active Dispatch capability"
            ) from exc
        manifest, binding, _live = active or ({}, {}, {})
        if not manifest or not binding:
            raise RoomKernelFenceError(
                "Room approval lost its active Dispatch capability"
            )
        invocation = self.capabilities.invocation_receipt(
            invocation_receipt_id
        )
        command = invocation.get("canonicalCommand")
        if not isinstance(command, Mapping):
            raise RoomKernelFenceError(
                "Room approval invocation has no canonical command"
            )
        if (
            invocation.get("manifestId") != binding.get("manifestId")
            or invocation.get("manifestHash") != binding.get("manifestHash")
            or str(command.get("tool") or "") != str(tool_name or "")
        ):
            raise RoomKernelFenceError(
                "Room approval no longer matches its Dispatch capability"
            )
        if self.capabilities.execution_receipt(invocation_receipt_id) is not None:
            raise RoomKernelFenceError(
                "Room approval invocation already has a terminal execution receipt"
            )
        return dict(invocation)

    def _assert_room_collaboration_authority(
        self,
        live: Mapping[str, object],
    ) -> None:
        dispatch = self.kernel.dispatch(str(live["dispatchId"]))
        root = self.kernel.root(str(live["rootId"]))
        caller_id = str(dispatch.get("targetParticipantId") or "").strip()
        authorized_ids = {
            str(root.get(key) or "").strip()
            for key in ("facilitatorParticipantId", "reporterParticipantId")
            if str(root.get(key) or "").strip()
        }
        if caller_id not in authorized_ids:
            raise RoomKernelFenceError(
                "only the Root Facilitator or Reporter may request Room collaboration"
            )

    def _authorize_capability_invocation(
        self,
        session_id: str,
        tool_name: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        load_receipt_id: str,
    ) -> tuple[dict[str, object], dict[str, object], bool] | None:
        active = self._active_capability_binding(session_id)
        if active is None:
            return None
        _manifest, _binding, live = active
        if tool_name == "room_collaborate":
            self._assert_room_collaboration_authority(live)
        verified_args = _verified_room_media_args(
            session_id=session_id,
            tool_name=tool_name,
            args=args,
            receipt_provider=self.media_receipt_provider,
        )
        invocation, created = self.capabilities.authorize_runtime_invocation(
            session_id=session_id,
            receipt_id=f"invoke:{tool_call_id}",
            invocation_key=tool_call_id,
            load_receipt_id=load_receipt_id,
            tool_name=tool_name,
            arguments=verified_args,
            created_at_ms=int(time.time() * 1000),
        )
        return dict(live), invocation, created

    def _active_capability_binding(
        self,
        session_id: str,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]] | None:
        bound = self.capabilities.manifest_for_runtime(session_id)
        if bound is None:
            if (
                self.capabilities.runtime_binding(
                    session_id,
                    active_only=False,
                )
                is not None
            ):
                raise ToolAuthorizationError(
                    "Session Room Capability Manifest is not active"
                )
            return None
        manifest, binding = bound
        live = self.kernel.session_binding(session_id)
        if (
            live is None
            or live.get("dispatchId") != manifest.get("dispatchId")
            or live.get("rootId") != manifest.get("rootId")
            or int(live.get("generation", -1))
            != int(manifest.get("generation", -2))
            or int(binding["capabilityEpoch"])
            != int(manifest["capabilityEpoch"])
        ):
            raise RoomKernelFenceError(
                "Room tool invocation lost its Dispatch or capability fence"
            )
        return dict(manifest), dict(binding), dict(live)

    def create_root(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.rooms.get(room_id)
        root = payload.get("rootExecution")
        task = payload.get("task")
        if (
            not isinstance(root, Mapping)
            or not isinstance(task, Mapping)
            or root.get("roomId") != room_id
            or task.get("rootId") != root.get("rootId")
        ):
            raise RoomKernelFenceError(
                "Root/Task creation payload does not match path Room"
            )
        created = self.commands.create_root_task(
            root,
            task,
            budget=int(payload.get("budget") or 1),
            max_hops=int(payload.get("maxHops") or 1),
            max_depth=int(payload.get("maxDepth") or 1),
            acceptance_criteria=tuple(
                str(item)
                for item in payload.get("acceptanceCriteria") or ()
            ),
            now_ms=int(
                root.get("createdAtMs") or int(time.time() * 1000)
            ),
        )
        self.projection.sync_room(room_id)
        return created



    def dispatch(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        root = self.kernel.root(str(payload.get("rootId") or ""))
        if root.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "Dispatch Root belongs to another Room"
            )
        dispatch, created = self.commands.dispatch(
            payload,
            now_ms=int(time.time() * 1000),
        )
        self.wake_worker()
        self.projection.sync_room(room_id)
        self.root_state_observer(
            self.kernel.root(str(dispatch["rootId"]))
        )
        return {"dispatch": dispatch, "created": created}

    def _assert_root_children_quiescent(
        self,
        *,
        root_id: str,
        generation: int,
        dispatch_id: str = "",
    ) -> dict[str, object]:
        result = self.root_child_quiescence(
            root_id,
            int(generation),
            dispatch_id,
        )
        if not isinstance(result, Mapping) or result.get("quiescent") is not True:
            raise RoomKernelFenceError(
                "Room Root has active or unknown causal children"
            )
        return dict(result)

    def cancel_root(
        self,
        room_id: str,
        root_id: str,
    ) -> dict[str, object]:
        root = self.kernel.root(root_id)
        if root.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "Cancel Root belongs to another Room"
            )
        generation = int(root.get("generation") or 0)
        request_id = f"room-root-cancel:{root_id}:{generation}"
        child_cancellation = self.cancel_root_children(
            root_id,
            generation,
            "Room Root cancelled",
            request_id,
        )
        result = self.commands.cancel_root(root_id)
        self.reconcile_workspace_retention(
            room_id=room_id,
            root_id=root_id,
            reason="Room Root was cancelled before isolated worktree integration",
        )
        self.projection.sync_room(room_id)
        projected_root = self.kernel.root(root_id)
        self.root_state_observer(projected_root)
        surfaces = self.kernel.cancellation_surface_projection(room_id)
        root_surfaces = [
            item
            for item in surfaces
            if str(item.get("rootId") or root_id) == root_id
        ]
        pending = [
            item
            for item in root_surfaces
            if item.get("state")
            in {"requested", "acknowledged", "unknown"}
        ]
        child_pending = (
            child_cancellation.get("pendingTargets")
            if isinstance(child_cancellation, Mapping)
            else []
        )
        if isinstance(child_pending, list):
            pending.extend(
                item for item in child_pending if isinstance(item, Mapping)
            )
        kernel_receipt = result["kernelReceipt"]
        if not pending:
            terminal_root = projected_root
            self.public_timeline.publish_terminal(
                room_id=room_id,
                root_id=root_id,
                generation=int(terminal_root["generation"]),
                state=str(terminal_root["state"]),
                receipt_id=str(
                    terminal_root.get("terminalReceiptId") or ""
                ),
                created_at_ms=int(
                    terminal_root.get("updatedAtMs")
                    or int(time.time() * 1000)
                ),
            )
        return {
            "schemaVersion": "rag-ime.agent-room-abort.v1",
            "ok": not pending,
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "status": (
                "terminated" if not pending else "cancellation_pending"
            ),
            "childCancellation": child_cancellation,
            "cancellationReceiptId": str(
                kernel_receipt.get("receiptId") or ""
            ),
            "surfaces": {
                str(item.get("surface") or ""): item
                for item in root_surfaces
                if str(item.get("surface") or "")
            },
            "pendingTargets": pending,
            "kernelReceipt": kernel_receipt,
            "sessionReceipts": list(result["runtimeReceipts"]),
        }

    def settle(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.rooms.get(room_id)
        settle = payload.get("settleReceipt")
        commit = payload.get("commit")
        if not isinstance(settle, Mapping):
            raise ValueError("settleReceipt is required")
        if (
            settle.get("eventKind") != "agent_settled"
            or settle.get("status") != "settled"
        ):
            raise RoomKernelFenceError(
                "only an agent_settled receipt can bridge a RoomCommit"
            )
        validate_kernel_contract("roomSettleReceipt", settle)
        dispatch_id = str(
            commit.get("dispatchId")
            if isinstance(commit, Mapping)
            else settle.get("dispatchId") or ""
        )
        dispatch = self.kernel.dispatch(dispatch_id)
        root = self.kernel.root(str(dispatch["rootId"]))
        if (
            root.get("roomId") != room_id
            or settle.get("dispatchId") != dispatch.get("dispatchId")
            or settle.get("sessionId") != dispatch.get("targetSessionId")
            or int(settle.get("generation", -1))
            != int(dispatch["generation"])
            or int(settle.get("generation", -1))
            != int(root["generation"])
            or int(settle.get("capabilityEpoch", -1))
            != int(dispatch["capabilityEpoch"])
        ):
            raise RoomKernelFenceError(
                "settle receipt does not match Dispatch fences"
            )
        if not isinstance(commit, Mapping):
            timestamp = int(
                settle.get("createdAtMs") or int(time.time() * 1000)
            )
            guard_reason = str(
                payload.get("guardReason") or "missing_room_commit"
            )
            # Settlement validation is staged: peer review, evidence shape,
            # lifecycle state, and the public summary can each become
            # actionable only after the preceding repair. Match the product's
            # bounded Goal settlement budget so those independent repairs get
            # a turn without allowing an unbounded continuation loop.
            max_attempts = 5
            receipt = self.kernel.record_uncommitted_settle(
                dispatch_id,
                generation=int(settle["generation"]),
                runtime_turn_id=str(
                    payload.get("runtimeTurnId") or ""
                ),
                dispatch_attempt=int(
                    payload.get("dispatchAttempt", -1)
                ),
                now_ms=timestamp,
                settle_receipt_id=str(
                    settle.get("settleReceiptId") or ""
                ),
                reason=guard_reason,
                max_attempts=max_attempts,
                resource_usage=(
                    settle.get("resourceUsage")
                    if isinstance(settle.get("resourceUsage"), Mapping)
                    else None
                ),
            )
            if receipt["receiptKind"] == "settle_blocked":
                self.revoke_session(str(settle["sessionId"]), timestamp)
                self._retain_isolated_task(
                    self.kernel.task(str(dispatch["taskId"])),
                    state="failed",
                    reason=(
                        "Room settlement exhausted its repair budget: "
                        + guard_reason
                    ),
                    actor_ref="system:room-settlement",
                    now_ms=timestamp,
                )
            self.projection.sync_room(room_id)
            return {
                "schemaVersion": "wisdom-weasel.room-settle-guard.v1",
                "receipt": receipt,
                "retryRequired": (
                    receipt["receiptKind"] == "settle_retry_required"
                ),
                "blocked": receipt["receiptKind"] == "settle_blocked",
            }
        validate_kernel_contract("roomCommit", commit)
        invocation_receipt_id = str(
            payload.get("invocationReceiptId") or ""
        ).strip()
        runtime_capability = self.capabilities.manifest_for_runtime(
            str(settle["sessionId"])
        )
        if runtime_capability is not None and not invocation_receipt_id:
            raise RoomKernelFenceError(
                "governed Room settle requires the originating invocation receipt"
            )
        if dispatch.get("state") != "running" and not (
            dispatch.get("state") == "committed"
            and invocation_receipt_id
        ):
            raise RoomKernelFenceError(
                "only a running Dispatch can settle"
            )
        guard_pin = self.learning.execution_pin(
            str(dispatch["dispatchId"])
        )
        if guard_pin is not None and dispatch.get("state") == "running":
            self.learning.accept_writeback(
                dispatch_id=str(dispatch["dispatchId"]),
                guard_epoch=int(guard_pin["guardEpoch"]),
                config_hash=str(guard_pin["configHash"]),
            )
        proposal = _validated_post_proposal(
            room_id=room_id,
            root=root,
            dispatch=dispatch,
            commit=commit,
            capabilities=self.capabilities,
            invocation_receipt_id=invocation_receipt_id,
        )
        workspace_delivery: dict[str, object] | None = None
        continuation = commit.get("continuation")
        settling_task = self.kernel.task(str(dispatch["taskId"]))
        if (
            isinstance(continuation, Mapping)
            and continuation.get("decision") == "complete"
            and settling_task.get("parentTaskId")
            and settling_task.get("workspacePolicy") == "isolated_writable"
        ):
            if self.workspaces is None:
                raise RoomKernelFenceError(
                    "isolated Worker delivery has no workspace coordinator"
                )
            post_payload = commit.get("postProposal")
            attachment_values = (
                post_payload.get("attachments")
                if isinstance(post_payload, Mapping)
                else None
            )
            artifacts = [
                str(
                    item.get("receiptId")
                    or item.get("attachmentId")
                    or item.get("mediaId")
                    or item.get("id")
                    or ""
                )
                for item in (
                    attachment_values
                    if isinstance(attachment_values, list)
                    else []
                )
                if isinstance(item, Mapping)
                and str(
                    item.get("receiptId")
                    or item.get("attachmentId")
                    or item.get("mediaId")
                    or item.get("id")
                    or ""
                ).strip()
            ]
            quality_gate = commit.get("qualityGateReceipt")
            residual_risks = (
                quality_gate.get("residualRisks")
                if isinstance(quality_gate, Mapping)
                else []
            )
            try:
                workspace_delivery = self.workspaces.record_delivery(
                    settling_task,
                    artifacts=artifacts,
                    verification_refs=[
                        str(value)
                        for value in commit.get("evidenceRefs") or []
                        if str(value).strip()
                    ],
                    verification_results=[
                        {
                            "label": f"验收项 {index + 1}",
                            "result": str(item.get("status") or "not_verified"),
                            "source": "quality_gate",
                        }
                        for index, item in enumerate(
                            quality_gate.get("items") or []
                            if isinstance(quality_gate, Mapping)
                            else []
                        )
                        if isinstance(item, Mapping)
                    ],
                    residual_risks=[
                        str(value)
                        for value in (
                            residual_risks
                            if isinstance(residual_risks, list)
                            else []
                        )
                        if str(value).strip()
                    ],
                    result_summary=str(
                        commit.get("publicSummary")
                        or commit.get("summary")
                        or ""
                    ),
                    actor_ref=str(dispatch["targetParticipantId"]),
                    now_ms=int(commit.get("createdAtMs") or 0),
                )
                self.kernel.record_workspace_delivery(
                    str(dispatch["taskId"]),
                    delivery=workspace_delivery,
                    now_ms=int(commit.get("createdAtMs") or 0),
                )
            except RoomWorkspaceError as exc:
                raise RoomKernelFenceError(str(exc)) from exc
        receipt = self.commands.commit(
            commit,
            generation=int(settle["generation"]),
            now_ms=int(
                commit.get("createdAtMs") or int(time.time() * 1000)
            ),
            post_proposal=proposal,
            invocation_receipt_id=invocation_receipt_id,
            resource_usage=(
                settle.get("resourceUsage")
                if isinstance(settle.get("resourceUsage"), Mapping)
                else None
            ),
        )
        post_invocation_receipt_id = str(
            commit.get("postInvocationReceiptId") or ""
        )
        if (
            post_invocation_receipt_id
            and receipt.get("status") == "applied"
            and proposal is not None
        ):
            self.capabilities.record_runtime_execution(
                session_id=str(settle["sessionId"]),
                invocation_receipt_id=post_invocation_receipt_id,
                status="applied",
                result_hash=hashlib.sha256(
                    json.dumps(
                        proposal,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                created_at_ms=int(commit.get("createdAtMs") or 0),
            )
        post = proposal
        if post is not None and receipt.get("status") == "applied":
            post, _ = self.context.publish_post(post)
            room = self.rooms.get(room_id)
            self.public_timeline.publish_post(
                post,
                participant_id=str(dispatch["targetParticipantId"]),
                source_session_id=str(dispatch["targetSessionId"]),
                topic_id=str(room.get("activeTopicId") or ""),
            )
        execution_receipt = (
            self.capabilities.execution_receipt(invocation_receipt_id)
            if invocation_receipt_id
            else None
        )
        receipt_details = receipt.get("details")
        if (
            receipt.get("status") == "applied"
            and isinstance(receipt_details, Mapping)
            and receipt_details.get("settleDecision") == "block"
        ):
            self._retain_isolated_task(
                self.kernel.task(str(dispatch["taskId"])),
                state="blocked",
                reason="Room worker reported a blocked isolated workspace",
                actor_ref=str(dispatch["targetParticipantId"]),
                now_ms=int(commit.get("createdAtMs") or 0),
            )
        ownership_transfer = False
        transfer_task: Mapping[str, object] | None = None
        transfer_target_session_id = ""
        if (
            receipt.get("status") == "applied"
            and isinstance(receipt_details, Mapping)
            and str(receipt_details.get("transferredTaskId") or "").strip()
        ):
            transfer_task = self.kernel.task(
                str(receipt_details["transferredTaskId"])
            )
            if transfer_task.get("workspacePolicy") == "isolated_writable":
                child_dispatch_id = str(
                    receipt_details.get("childDispatchId") or ""
                ).strip()
                if not child_dispatch_id or self.workspaces is None:
                    raise RoomKernelFenceError(
                        "isolated ownership handoff has no workspace coordinator"
                    )
                child_dispatch = self.kernel.dispatch(child_dispatch_id)
                transfer_target_session_id = str(
                    child_dispatch["targetSessionId"]
                )
                ownership_transfer = True
        if (
            receipt.get("status") == "applied"
            and (runtime_capability is not None or ownership_transfer)
        ):
            self.revoke_session(
                str(settle["sessionId"]),
                int(commit.get("createdAtMs") or 0),
            )
        if ownership_transfer and transfer_task is not None:
            try:
                self.workspaces.transfer_isolated_ownership(
                    task=transfer_task,
                    source_session_id=str(settle["sessionId"]),
                    target_session_id=transfer_target_session_id,
                    base_roots=[
                        str(value)
                        for value in self.rooms.get(room_id).get("workspaceRoots") or []
                        if str(value).strip()
                    ],
                )
            except RoomWorkspaceError as exc:
                self.revoke_session(
                    transfer_target_session_id,
                    int(commit.get("createdAtMs") or 0),
                )
                raise RoomKernelFenceError(str(exc)) from exc
        if (
            receipt.get("status") == "applied"
            and isinstance(receipt_details, Mapping)
            and receipt_details.get("settleDecision") == "complete"
            and self.workspaces is not None
        ):
            settled_task = self.kernel.task(str(dispatch["taskId"]))
            if settled_task.get("parentTaskId") or self.kernel.is_report_dispatch(
                str(dispatch["dispatchId"])
            ):
                settled_room = self.rooms.get(room_id)
                self.workspaces.restore(
                    session_id=str(dispatch["targetSessionId"]),
                    base_roots=[
                        str(value)
                        for value in settled_room.get("workspaceRoots") or []
                        if str(value).strip()
                    ],
                    restore_policy=(
                        settled_task.get("workspaceRestorePolicy")
                        if isinstance(
                            settled_task.get("workspaceRestorePolicy"),
                            Mapping,
                        )
                        else None
                    ),
                )
        if guard_pin is not None and receipt.get("status") == "applied":
            self.learning.complete_writeback(
                dispatch_id=str(dispatch["dispatchId"]),
                now_ms=int(
                    commit.get("createdAtMs")
                    or int(time.time() * 1000)
                ),
            )
        self.projection.sync_room(room_id)
        self.root_state_observer(
            self.kernel.root(str(root["rootId"]))
        )
        if receipt.get("status") == "applied":
            # A child Dispatch may depend on this Commit's public Room fact.
            # Wake only after the context ledger and UI projection can both
            # expose that fact; waking earlier races the closer's next prompt.
            self.wake_worker()
        if _receipt_completes_root_candidate(receipt):
            # Reuse the canonical finalization authority. Parallel commits stay
            # running until the last active Dispatch makes the Root quiescent.
            # Enforced environments still fail closed in finalize_root when an
            # independent delivery preview is absent or invalid.
            self.finalize(
                str(root["rootId"]),
                now_ms=int(
                    commit.get("createdAtMs")
                    or int(time.time() * 1000)
                ),
            )
        result: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-settle-result.v1",
            "receipt": receipt,
            "post": post,
        }
        if execution_receipt is not None:
            result["executionReceipt"] = execution_receipt
        validate_kernel_contract("roomSettleResult", result)
        return result

    def finalize(
        self,
        root_id: str,
        *,
        catalog_revision_id: str = "",
        target_commit: str = "",
        blind_review_status: str = "unavailable",
        delivery_gate_preview_receipt_id: str = "",
        now_ms: int | None = None,
    ) -> dict[str, object]:
        timestamp = int(
            now_ms if now_ms is not None else time.time() * 1000
        )
        root_before = self.kernel.root(root_id)
        child_quiescence = self._assert_root_children_quiescent(
            root_id=root_id,
            generation=int(root_before.get("generation") or 0),
        )
        observation = None
        if catalog_revision_id:
            observation = self.requirements.observe_delivery_gate(
                gate_receipt_id=(
                    f"delivery-gate:{root_id}:{catalog_revision_id}"
                ),
                root_id=root_id,
                catalog_revision_id=catalog_revision_id,
                target_commit=target_commit or "working-tree",
                blind_review_status=blind_review_status,
                created_at_ms=timestamp,
            )
        report: dict[str, object] | None = None
        if kernel_owns_room_execution(self.kernel.mode) and str(
            root_before.get("state") or ""
        ) not in {"completed", "cancelled", "failed"}:
            readiness = self.kernel.report_readiness(root_id)
            existing = readiness.get("existing")
            if isinstance(existing, Mapping):
                report = dict(existing)
            elif readiness.get("ready") is True:
                room = self.rooms.get(str(root_before["roomId"]))
                reporter_id = str(
                    root_before.get("reporterParticipantId")
                    or root_before.get("facilitatorParticipantId")
                    or ""
                ).strip()
                reporter = next(
                    (
                        item
                        for item in room.get("participants", ())
                        if isinstance(item, Mapping)
                        and str(item.get("id") or "") == reporter_id
                        and item.get("status") == "active"
                        and str(item.get("sessionId") or "").strip()
                    ),
                    None,
                )
                if reporter is None:
                    raise RoomKernelFenceError(
                        "Root Reporter has no active Session for final reporting"
                    )
                if self.workspaces is None:
                    raise RoomKernelFenceError(
                        "ReportDispatch requires a read-only workspace coordinator"
                    )
                definition = self.kernel.definition_fence(root_id=root_id) or {}
                try:
                    report_workspace = self.workspaces.prepare(
                        root_id=root_id,
                        task_id=f"report:{root_id}",
                        target_session_id=str(reporter["sessionId"]),
                        base_roots=[
                            str(value)
                            for value in room.get("workspaceRoots") or []
                            if str(value).strip()
                        ],
                        policy="read_only",
                        room_id=str(room["id"]),
                        work_item_id=str(
                            definition.get("workItemId") or f"report:{root_id}"
                        ),
                        dispatch_id=f"report:{root_id}",
                        requirement_revision=str(
                            definition.get("catalogRevisionId") or ""
                        ),
                        acceptance_aliases=[
                            str(value)
                            for value in definition.get("acceptanceAliases") or []
                            if str(value).strip()
                        ],
                        participant_id=reporter_id,
                        creation_reason="Root work is verified and ready for one final report",
                        now_ms=timestamp,
                    )
                except RoomWorkspaceError as exc:
                    raise RoomKernelFenceError(str(exc)) from exc
                report = self.kernel.ensure_report_dispatch(
                    root_id,
                    reporter_participant_id=reporter_id,
                    reporter_session_id=str(reporter["sessionId"]),
                    workspace=report_workspace,
                    now_ms=timestamp,
                )
            else:
                # Persist the exact fail-closed reason without preparing or
                # rebinding the Reporter Session before the work is ready.
                report = self.kernel.ensure_report_dispatch(
                    root_id,
                    reporter_participant_id=str(
                        root_before.get("reporterParticipantId")
                        or root_before.get("facilitatorParticipantId")
                        or ""
                    ),
                    reporter_session_id="not-ready",
                    workspace={},
                    now_ms=timestamp,
                )
            if report.get("readyForTerminal") is not True:
                root_pending = self.kernel.root(root_id)
                self.projection.sync_room(
                    str(root_pending["roomId"]),
                    now_ms=timestamp,
                )
                self.root_state_observer(root_pending)
                dispatch = report.get("dispatch")
                if isinstance(dispatch, Mapping) and str(
                    dispatch.get("state") or ""
                ) in {"pending", "retry_wait", "timer_wait"}:
                    self.wake_worker()
                return {
                    "receipt": report["receipt"],
                    "deliveryGateObservation": observation,
                    "childQuiescence": child_quiescence,
                    "reportDispatch": dispatch,
                    "reportCreated": bool(report.get("created")),
                }
        preview = None
        if self.kernel.enforce_test_delivery_gate:
            if not delivery_gate_preview_receipt_id:
                preview = {
                    "rootId": root_id,
                    "generation": int(
                        self.kernel.root(root_id)["generation"]
                    ),
                    "environment": "room-v2-test",
                    "mode": "room_v2_test_enforce_preview",
                    "terminalAllowed": False,
                    "valid": False,
                    "validationReasons": [
                        "delivery_gate_preview_missing"
                    ],
                }
            else:
                artifact_hash = (
                    self.artifact_hash_provider(root_id)
                    if self.artifact_hash_provider is not None
                    else ""
                )
                preview = (
                    self.peer_review.validate_delivery_gate_preview(
                        delivery_gate_preview_receipt_id,
                        current_artifact_hash=artifact_hash,
                    )
                )
        receipt = self.commands.finalize(
            root_id,
            now_ms=timestamp,
            delivery_gate_preview=preview,
        )
        root = self.kernel.root(root_id)
        self.projection.sync_room(
            str(root["roomId"]),
            now_ms=timestamp,
        )
        self.root_state_observer(root)
        if str(root.get("state") or "") in {
            "completed",
            "cancelled",
            "failed",
        }:
            self.public_timeline.publish_terminal(
                room_id=str(root["roomId"]),
                root_id=root_id,
                generation=int(root["generation"]),
                state=str(root["state"]),
                receipt_id=str(root.get("terminalReceiptId") or ""),
                created_at_ms=timestamp,
            )
        return {
            "receipt": receipt,
            "deliveryGateObservation": observation,
            "childQuiescence": child_quiescence,
            "reportDispatch": (
                report.get("dispatch")
                if isinstance(report, Mapping)
                else None
            ),
            "reportCreated": False,
        }


def _verified_room_media_args(
    *,
    session_id: str,
    tool_name: str,
    args: Mapping[str, object],
    receipt_provider: Callable[[str, str], Mapping[str, object]] | None,
) -> dict[str, object]:
    """Verify opaque file blocks before they enter an authorized Room command."""

    result = dict(args)
    if tool_name not in {"room_post", "room_commit"} or "blocks" not in result:
        return result
    blocks = result.get("blocks")
    if not isinstance(blocks, list):
        return result
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "file":
            continue
        data = block.get("data")
        if not isinstance(data, Mapping) or receipt_provider is None:
            raise RoomKernelFenceError("Room file block has no managed media authority")
        media_id = str(data.get("mediaId") or "")
        declared_session_id = str(data.get("sessionId") or "")
        if declared_session_id != session_id:
            raise RoomKernelFenceError("Room file block belongs to another Session")
        try:
            receipt = receipt_provider(media_id, session_id)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise RoomKernelFenceError("Room file block receipt is unavailable") from exc
        expected = {
            "fileName": str(receipt.get("fileName") or ""),
            "mimeType": str(receipt.get("mimeType") or ""),
            "byteSize": int(receipt.get("byteSize") or 0),
            "sha256": str(receipt.get("sha256") or ""),
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise RoomKernelFenceError(
                "Room file block differs from its managed media receipt"
            )
        expected_url = (
            f"/api/agent/media/{quote(media_id, safe='')}/content"
            f"?sessionId={quote(session_id, safe='')}"
        )
        if data.get("receiptUrl") != expected_url:
            raise RoomKernelFenceError("Room file block content URL is not canonical")
    return result


def _receipt_completes_root_candidate(receipt: Mapping[str, object]) -> bool:
    details = receipt.get("details")
    return (
        receipt.get("status") == "applied"
        and isinstance(details, Mapping)
        and details.get("settleDecision") == "complete"
    )


def _collaboration_tool_result(
    invocation: Mapping[str, object],
    kernel_receipt: Mapping[str, object],
) -> dict[str, object]:
    details = kernel_receipt.get("details")
    if not isinstance(details, Mapping):
        raise RoomKernelFenceError(
            "Room collaboration Kernel receipt has no child identity"
        )
    command = invocation.get("canonicalCommand")
    arguments = (
        command.get("arguments")
        if isinstance(command, Mapping)
        else {}
    )
    deduplicated = (
        kernel_receipt.get("receiptKind") == "duplicate"
        or kernel_receipt.get("status") == "noop"
    )
    return {
        "accepted": True,
        # `accepted` describes the canonical command; `enqueued` describes the
        # Kernel side effect. An equivalent invocation can be accepted as an
        # idempotent no-op without creating a second Dispatch.
        "enqueued": not deduplicated,
        "deduplicated": deduplicated,
        "childTaskId": str(details.get("childTaskId") or ""),
        "childDispatchId": str(details.get("childDispatchId") or ""),
        "workspacePolicy": (
            arguments.get("workspacePolicy")
            if isinstance(arguments, Mapping)
            else None
        ),
        "targetParticipantRef": (
            arguments.get("targetParticipantRef")
            if isinstance(arguments, Mapping)
            else None
        ),
        "currentResponsibilityContinues": True,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:40]}"


def _allows_fresh_runtime_recovery(
    *,
    retryable: bool,
    reason_code: str,
) -> bool:
    """Allow a bounded continuation without replaying a side-effectful turn."""

    normalized = str(reason_code or "").strip().lower()
    if normalized in {
        "provider_auth_failure",
        "provider_cancelled",
        "user_cancelled",
        "permission_required",
        "credentials_required",
    }:
        return False
    return bool(retryable) or normalized in {
        "runtime_host_exit",
        "room_commit_missing",
        "tool_activity_observed",
        "provider_contract_failure",
        "provider_failure_unclassified",
    }


def _fresh_runtime_recovery_command(
    *,
    room_id: str,
    root_id: str,
    generation: int,
    dispatch_id: str,
    source_event_id: str,
    created_at_ms: int,
) -> dict[str, object]:
    command_id = _stable_id(
        "room-command-runtime-recovery",
        root_id,
        dispatch_id,
        source_event_id,
    )
    return {
        "schemaVersion": KERNEL_COMMAND_SCHEMA_VERSION,
        "commandId": command_id,
        "rootId": root_id,
        "roomId": room_id,
        "commandKind": "retry_root",
        "targetKind": "root",
        "targetId": root_id,
        "sourceKind": "system_runtime_recovery",
        "sourceId": source_event_id,
        "idempotencyKey": command_id,
        "generation": int(generation),
        "payload": {
            "failedDispatchId": dispatch_id,
            "recoveryMode": "fresh_dispatch",
        },
        "createdAtMs": int(created_at_ms),
    }


def _validated_post_proposal(
    *,
    room_id: str,
    root: Mapping[str, object],
    dispatch: Mapping[str, object],
    commit: Mapping[str, object],
    capabilities: RoomCapabilityManifestStore,
    invocation_receipt_id: str,
) -> dict[str, object] | None:
    proposal = commit.get("postProposal")
    if commit.get("action") != "post":
        if proposal is not None:
            raise RoomKernelFenceError(
                "non-post Commit cannot publish a RoomPost"
            )
        return None
    if not isinstance(proposal, Mapping):
        raise RoomKernelFenceError(
            "post action requires an explicit RoomPost proposal"
        )
    normalized = dict(proposal)
    source_invocation_receipt_id = str(
        commit.get("postInvocationReceiptId") or invocation_receipt_id
    )
    invocation_blocks = None
    if source_invocation_receipt_id:
        invocation = capabilities.invocation_receipt(
            source_invocation_receipt_id
        )
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if isinstance(arguments, Mapping):
            invocation_blocks = arguments.get("blocks")
        if commit.get("postInvocationReceiptId") and (
            not isinstance(command, Mapping)
            or command.get("tool") != "room_post"
            or command.get("dispatchId") != dispatch.get("dispatchId")
            or command.get("rootId") != root.get("rootId")
            or int(command.get("generation", -1)) != int(root["generation"])
        ):
            raise RoomKernelFenceError(
                "RoomPost staging invocation does not match the settled Dispatch"
            )
    if normalized.get("blocks") is not None and invocation_blocks is None:
        raise RoomKernelFenceError(
            "RoomPost blocks must originate from the authorized structured tool input"
        )
    if invocation_blocks is not None:
        normalized["blocks"] = list(
            normalize_trusted_agent_blocks(
                invocation_blocks,
                source_kind="room_commit",
                source_ref=str(commit.get("commitId") or ""),
                visibility=(
                    "room_post"
                    if normalized.get("visibility") == "room"
                    else "root_post"
                ),
                generation=int(root["generation"]),
            )
        )
    validate_kernel_contract("roomPost", normalized)
    if (
        normalized.get("roomId") != room_id
        or normalized.get("rootId") != root.get("rootId")
        or normalized.get("dispatchId")
        != dispatch.get("dispatchId")
        or int(normalized.get("generation", -1))
        != int(root["generation"])
        or normalized.get("publicationSource")
        != {
            "kind": "room_commit",
            "ref": commit.get("commitId"),
        }
    ):
        raise RoomKernelFenceError(
            "RoomPost proposal does not match the settled Commit"
        )
    return normalized
