from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping

from .agent_blocks import normalize_trusted_agent_blocks
from .agent_room_capabilities import (
    RoomCapabilityManifestStore,
    ToolAuthorizationError,
)
from .agent_room_context import RoomContextLedgerStore
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel_contracts import validate_kernel_contract
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_learning_governance import RoomLearningGovernanceStore
from .agent_room_peer_review import RoomPeerReviewStore
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
        wake_worker: Callable[[], None],
        revoke_session: Callable[[str, int], None],
        artifact_hash_provider: Callable[[str], str] | None = None,
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
        self.wake_worker = wake_worker
        self.revoke_session = revoke_session
        self.artifact_hash_provider = artifact_hash_provider

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

    def execute_capability_tool(
        self,
        session_id: str,
        tool_name: str,
        args: Mapping[str, object],
        *,
        tool_call_id: str,
        load_receipt_id: str,
    ) -> dict[str, object] | None:
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
        invocation, created = self.capabilities.authorize_runtime_invocation(
            session_id=session_id,
            receipt_id=f"invoke:{tool_call_id}",
            invocation_key=tool_call_id,
            load_receipt_id=load_receipt_id,
            tool_name=tool_name,
            arguments=dict(args),
            created_at_ms=int(time.time() * 1000),
        )
        canonical = str(invocation["canonicalCommand"]["tool"])
        if canonical == "room_state":
            result = self.snapshot(str(live["roomId"]))
        else:
            result = {
                "accepted": True,
                "executionPerformed": False,
                "canonicalTool": canonical,
                "invocationReceiptId": invocation["receiptId"],
                "next": "agent_settled_then_room_commit",
            }
        return {
            "ok": True,
            "created": created,
            "result": result,
            "invocationReceipt": invocation,
        }

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
        if receipt.get("details", {}).get("childDispatchId"):
            self.wake_worker()
        post = proposal
        if post is not None and receipt.get("status") == "applied":
            post, _ = self.context.publish_post(post)
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
        return {
            "receipt": receipt,
            "deliveryGateObservation": observation,
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
    invocation_blocks = None
    if invocation_receipt_id:
        invocation = capabilities.invocation_receipt(
            invocation_receipt_id
        )
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if isinstance(arguments, Mapping):
            invocation_blocks = arguments.get("blocks")
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
