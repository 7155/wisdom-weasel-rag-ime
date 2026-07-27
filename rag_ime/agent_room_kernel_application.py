from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from urllib.parse import quote

from .agent_blocks import normalize_trusted_agent_blocks
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
from .agent_room_kernel_contracts import validate_kernel_contract
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_room_peer_review import RoomPeerReviewStore
from .agent_room_public_timeline import RoomPublicTimelineProjector
from .agent_room_references import (
    ParticipantReferenceError,
    participant_ref_map,
    ref_for_participant,
    resolve_participant_ref,
)
from .agent_room_requirements import RequirementGovernanceStore
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
        artifact_hash_provider: Callable[[str], str] | None = None,
        media_receipt_provider: Callable[[str, str], Mapping[str, object]] | None = None,
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
        self.revoke_session = revoke_session
        self.artifact_hash_provider = artifact_hash_provider
        self.media_receipt_provider = media_receipt_provider
        self.continuations = RoomContinuationFactory(
            rooms=rooms,
            kernel=kernel,
            capabilities=capabilities,
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
        created_at_ms: int,
    ) -> dict[str, object]:
        """Bridge a private Pi turn failure into the canonical Kernel once."""

        self.rooms.get(room_id)
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
            now_ms=created_at_ms,
        )
        if receipt.get("status") == "applied":
            self.revoke_session(
                str(dispatch["targetSessionId"]),
                created_at_ms,
            )
        self.projection.sync_room(room_id)
        return receipt

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
        acceptance = acceptance_cards(
            task.get("acceptanceCriterionIds") or [],
            self.requirements.dispatch_context(dispatch_id),
            accepted_evidence_by_criterion=(
                self.kernel.accepted_evidence_by_criterion(root_id)
            ),
        )
        model_state = {
            "schemaVersion": "wisdom-weasel.room-state-tool.v1",
            "mode": "managed",
            "currentResponsibility": {
                "objective": str(task.get("objective") or ""),
                "expectedOutput": str(task.get("expectedOutput") or ""),
                "state": str(dispatch.get("state") or ""),
            },
            "acceptanceAliases": acceptance,
            "canSettle": (
                root.get("state") == "running"
                and dispatch.get("state") == "running"
            ),
            "participants": participants,
            "recentPublicChanges": recent_changes,
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
        elif canonical == "room_post":
            result, execution_receipt = self._execute_post(
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
        post: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": post_id,
            "roomId": root["roomId"],
            "rootId": root["rootId"],
            "generation": root["generation"],
            "taskId": dispatch["taskId"],
            "dispatchId": dispatch["dispatchId"],
            "authorActorRef": dispatch["targetParticipantId"],
            "kind": str(arguments.get("kind") or ""),
            "visibility": "room",
            "content": str(arguments.get("content") or "").strip(),
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

    def _execute_collaboration(
        self,
        *,
        session_id: str,
        live: Mapping[str, object],
        invocation: Mapping[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        invocation_receipt_id = str(invocation["receiptId"])
        parent_dispatch_id = str(live["dispatchId"])
        prior_execution = self.capabilities.execution_receipt(
            invocation_receipt_id
        )
        prior_kernel = self.kernel.collaboration_receipt(
            parent_dispatch_id=parent_dispatch_id,
            invocation_receipt_id=invocation_receipt_id,
        )
        if prior_kernel is not None:
            result = _collaboration_tool_result(invocation, prior_kernel)
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
        parent = self.kernel.dispatch(parent_dispatch_id)
        parent_task = self.kernel.task(str(parent["taskId"]))
        room = self.rooms.get(str(live["roomId"]))
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
        evidence_refs = arguments.get("evidenceRefs") or []
        if not isinstance(evidence_refs, list):
            raise RoomKernelFenceError(
                "Room collaboration evidenceRefs must be an array"
            )
        objective = str(arguments.get("objective") or "")
        trigger_id = _stable_id(
            "room-collaboration",
            parent_dispatch_id,
            target_participant_id,
            " ".join(objective.split()),
        )
        try:
            continuation = self.continuations.build(
                parent_dispatch=parent,
                parent_task=parent_task,
                room_id=str(live["roomId"]),
                target_participant_id=target_participant_id,
                trigger_id=trigger_id,
                intent_kind=str(arguments.get("intent") or "execute"),
                objective=objective,
                expected_output=str(arguments.get("expectedOutput") or ""),
                acceptance_criterion_ids=criteria,
                context_evidence_refs=[
                    str(value)
                    for value in evidence_refs
                    if str(value or "").strip()
                ],
                kind="collaboration",
            )
        except RoomContinuationProposalError as exc:
            raise RoomKernelFenceError(str(exc)) from exc
        now_ms = int(time.time() * 1000)
        kernel_receipt = self.kernel.enqueue_collaboration(
            parent_dispatch_id=parent_dispatch_id,
            child_task=continuation["childTask"],
            child_dispatch=continuation["childDispatch"],
            generation=int(live["generation"]),
            invocation_receipt_id=invocation_receipt_id,
            now_ms=now_ms,
        )
        result = _collaboration_tool_result(invocation, kernel_receipt)
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
        return {"dispatch": dispatch, "created": created}

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
        result = self.commands.cancel_root(root_id)
        self.projection.sync_room(room_id)
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
        kernel_receipt = result["kernelReceipt"]
        if not pending:
            terminal_root = self.kernel.root(root_id)
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
            receipt = self.kernel.record_uncommitted_settle(
                dispatch_id,
                generation=int(settle["generation"]),
                now_ms=timestamp,
                settle_receipt_id=str(
                    settle.get("settleReceiptId") or ""
                ),
                reason=str(
                    payload.get("guardReason") or "missing_room_commit"
                ),
                resource_usage=(
                    settle.get("resourceUsage")
                    if isinstance(settle.get("resourceUsage"), Mapping)
                    else None
                ),
            )
            if receipt["receiptKind"] == "settle_blocked":
                self.revoke_session(str(settle["sessionId"]), timestamp)
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
        if (
            runtime_capability is not None
            and receipt.get("status") == "applied"
        ):
            self.revoke_session(
                str(settle["sessionId"]),
                int(commit.get("createdAtMs") or 0),
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
    return {
        "accepted": True,
        "enqueued": True,
        "deduplicated": (
            kernel_receipt.get("receiptKind") == "duplicate"
            or kernel_receipt.get("status") == "noop"
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
