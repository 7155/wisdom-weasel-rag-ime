from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping

from .agent_room_application import DEFAULT_RUNTIME_PROFILE_REVISION
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel_application import RoomKernelApplicationService
from .agent_room_kernel_contracts import DISPATCH_ENVELOPE_SCHEMA_VERSION
from .agent_rooms import AgentRoomStore


class RoomCommitProposalError(ValueError):
    """The model's proposal is repairable without weakening Kernel fences."""


class RoomSettleLifecycleService:
    """Turn one Pi settle candidate into a governed Room continuation.

    Pi owns the actual agent lifecycle. This service owns the product-side
    translation from a model proposal to canonical IDs, fences, Post and child
    Dispatch records. The model never supplies those authoritative fields.
    """

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        kernel: RoomKernelStore,
        capabilities: RoomCapabilityManifestStore,
        application: RoomKernelApplicationService,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.rooms = rooms
        self.kernel = kernel
        self.capabilities = capabilities
        self.application = application
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def settle(self, payload: Mapping[str, object]) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        dispatch_id = _required_text(payload, "dispatchId")
        root_id = _required_text(payload, "rootId")
        generation = _non_negative_int(payload, "generation")
        capability_epoch = _non_negative_int(payload, "capabilityEpoch")
        settle_scope_id = _required_text(payload, "settleScopeId")
        settle_attempt = _positive_int(payload, "settleAttempt")

        bound = self.capabilities.manifest_for_runtime(
            session_id,
            active_only=False,
        )
        if bound is None:
            raise RoomKernelFenceError(
                "Room settle Session has no governed Capability Manifest"
            )
        manifest, binding = bound
        if (
            manifest.get("dispatchId") != dispatch_id
            or manifest.get("rootId") != root_id
            or int(manifest.get("generation", -1)) != generation
            or int(manifest.get("capabilityEpoch", -1))
            != capability_epoch
        ):
            raise RoomKernelFenceError(
                "Room settle candidate lost its Dispatch or capability fence"
            )

        invocation = self.capabilities.latest_runtime_invocation(
            session_id=session_id,
            dispatch_id=dispatch_id,
            tool_name="room_commit",
        )
        if invocation is not None:
            execution = self.capabilities.execution_receipt(
                str(invocation["receiptId"])
            )
            if execution is not None:
                return {
                    "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
                    "state": "committed",
                    "dispatchId": dispatch_id,
                    "settleAttempt": settle_attempt,
                    "executionReceipt": execution,
                    "replayed": True,
                }
        timestamp = self.clock_ms()
        settle_receipt_id = _stable_id(
            "room-settle",
            dispatch_id,
            settle_scope_id,
            str(settle_attempt),
        )
        settle_receipt = {
            "schemaVersion": "wisdom-weasel.room-settle-receipt.v1",
            "settleReceiptId": settle_receipt_id,
            "eventKind": "agent_settled",
            "status": "settled",
            "dispatchId": dispatch_id,
            "sessionId": session_id,
            "generation": generation,
            "capabilityEpoch": capability_epoch,
            "resourceUsage": _resource_usage(payload.get("resourceUsage")),
            "createdAtMs": timestamp,
        }
        room_id = str(manifest["roomId"])
        if binding.get("state") != "active":
            replay = self.kernel.settle_attempt_receipt(
                settle_receipt_id,
                dispatch_id=dispatch_id,
            )
            if replay is None:
                raise RoomKernelFenceError(
                    "Room settle capability is no longer active"
                )
            return self._repair_result(
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason=str(
                    (
                        replay.get("details")
                        if isinstance(replay.get("details"), Mapping)
                        else {}
                    ).get("reason")
                    or "missing_room_commit"
                ),
                receipt=replay,
            )
        if invocation is None:
            return self._record_repair(
                room_id=room_id,
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason="missing_room_commit",
            )

        try:
            commit = self._canonical_commit(
                manifest=manifest,
                invocation=invocation,
                now_ms=timestamp,
            )
        except RoomCommitProposalError as exc:
            return self._record_repair(
                room_id=room_id,
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason=str(exc),
            )

        result = self.application.settle(
            room_id,
            {
                "settleReceipt": settle_receipt,
                "commit": commit,
                "invocationReceiptId": invocation["receiptId"],
            },
        )
        return {
            "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
            "state": "committed",
            "dispatchId": dispatch_id,
            "settleAttempt": settle_attempt,
            "settleResult": result,
            "replayed": False,
        }

    def _record_repair(
        self,
        *,
        room_id: str,
        settle_receipt: Mapping[str, object],
        settle_attempt: int,
        reason: str,
    ) -> dict[str, object]:
        result = self.application.settle(
            room_id,
            {
                "settleReceipt": settle_receipt,
                "guardReason": _bounded(reason, 500),
            },
        )
        return self._repair_result(
            settle_receipt=settle_receipt,
            settle_attempt=settle_attempt,
            reason=reason,
            receipt=result["receipt"],
        )

    def _repair_result(
        self,
        *,
        settle_receipt: Mapping[str, object],
        settle_attempt: int,
        reason: str,
        receipt: Mapping[str, object],
    ) -> dict[str, object]:
        if receipt.get("receiptKind") == "settle_blocked":
            return {
                "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
                "state": "blocked",
                "dispatchId": settle_receipt["dispatchId"],
                "settleAttempt": settle_attempt,
                "reason": _bounded(reason, 500),
                "guardReceipt": dict(receipt),
            }
        return {
            "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
            "state": "repair",
            "dispatchId": settle_receipt["dispatchId"],
            "settleAttempt": settle_attempt,
            "reason": _bounded(reason, 500),
            "repairKey": str(receipt["receiptId"]),
            "message": self._repair_instruction(
                dispatch_id=str(settle_receipt["dispatchId"]),
                reason=reason,
            ),
            "guardReceipt": dict(receipt),
        }

    def _repair_instruction(self, *, dispatch_id: str, reason: str) -> str:
        task = self.kernel.task(str(self.kernel.dispatch(dispatch_id)["taskId"]))
        criterion_ids = [
            str(item)
            for item in task.get("acceptanceCriterionIds", [])
            if str(item).strip()
        ]
        allowed = json.dumps(criterion_ids, ensure_ascii=False)
        return (
            "收工检查未通过："
            f"{_bounded(reason, 300)}。请重新调用 room_commit，明确选择 "
            "deliver、handoff、wait 或 blocked，并填写 result、evidenceRefs 与 "
            "requirementCoverage。requirementCoverage 只能使用当前 Task 的 "
            f"acceptanceCriterionIds={allowed}；不得填写 requirementItemIds；"
            "没有验收条件时必须传空数组。handoff 还要填写 "
            "targetParticipantId 和 nextTask。不要只在自然语言里声称完成。"
        )

    def _canonical_commit(
        self,
        *,
        manifest: Mapping[str, object],
        invocation: Mapping[str, object],
        now_ms: int,
    ) -> dict[str, object]:
        command = invocation.get("canonicalCommand")
        arguments = (
            command.get("arguments")
            if isinstance(command, Mapping)
            else None
        )
        if not isinstance(arguments, Mapping):
            raise RoomCommitProposalError("room_commit arguments are missing")
        decision = _required_text(arguments, "decision")
        if decision not in {"deliver", "handoff", "wait", "blocked"}:
            raise RoomCommitProposalError("room_commit decision is invalid")
        result = _required_text(arguments, "result")
        evidence_refs = _string_list(arguments.get("evidenceRefs"), "evidenceRefs")
        requirement_coverage = _string_list(
            arguments.get("requirementCoverage"),
            "requirementCoverage",
        )
        dispatch = self.kernel.dispatch(str(manifest["dispatchId"]))
        task = self.kernel.task(str(dispatch["taskId"]))
        root = self.kernel.root(str(manifest["rootId"]))
        task_criteria = {
            str(item)
            for item in task.get("acceptanceCriterionIds", [])
            if str(item).strip()
        }
        unknown_coverage = sorted(set(requirement_coverage) - task_criteria)
        if unknown_coverage:
            raise RoomCommitProposalError(
                "requirementCoverage contains criteria outside the current Task"
            )
        if decision == "deliver":
            missing_coverage = sorted(task_criteria - set(requirement_coverage))
            if missing_coverage:
                raise RoomCommitProposalError(
                    "deliver must cover every acceptance criterion of the current Task"
                )
            if not evidence_refs:
                raise RoomCommitProposalError("deliver requires at least one evidenceRef")
        commit_id = _stable_id(
            "room-commit",
            str(invocation["receiptId"]),
        )
        next_task = str(arguments.get("nextTask") or "").strip()
        public_content = result
        if decision == "handoff" and next_task:
            public_content = f"{result}\n\n下一步：{next_task}"
        post_id = _stable_id("room-post", commit_id)
        post_proposal: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": post_id,
            "roomId": root["roomId"],
            "rootId": root["rootId"],
            "generation": root["generation"],
            "taskId": dispatch["taskId"],
            "dispatchId": dispatch["dispatchId"],
            "authorActorRef": dispatch["targetParticipantId"],
            "kind": {
                "deliver": "result",
                "handoff": "handoff",
                "wait": "wait",
                "blocked": "blocked",
            }[decision],
            "visibility": "room",
            "content": public_content,
            "idempotencyKey": post_id,
            "publicationSource": {
                "kind": "room_commit",
                "ref": commit_id,
            },
            "createdAtMs": now_ms,
        }
        if arguments.get("blocks") is not None:
            post_proposal["blocks"] = list(arguments["blocks"])

        continuation: dict[str, object] = {
            "decision": {
                "deliver": "complete",
                "handoff": "dispatch",
                "wait": "wait",
                "blocked": "block",
            }[decision]
        }
        if decision == "handoff":
            continuation["childDispatch"] = self._child_dispatch(
                parent=dispatch,
                room_id=str(root["roomId"]),
                target_participant_id=_required_text(
                    arguments,
                    "targetParticipantId",
                ),
                commit_id=commit_id,
            )
        material = {
            "decision": decision,
            "result": result,
            "evidenceRefs": evidence_refs,
            "requirementCoverage": requirement_coverage,
            "continuation": continuation,
        }
        return {
            "schemaVersion": "wisdom-weasel.room-commit.v2",
            "commitId": commit_id,
            "dispatchId": dispatch["dispatchId"],
            "action": "post",
            "contentHash": f"sha256:{_sha256_json(material)}",
            "postProposal": post_proposal,
            "continuation": continuation,
            "evidenceRefs": evidence_refs,
            "requirementCoverage": requirement_coverage,
            "createdAtMs": now_ms,
        }

    def _child_dispatch(
        self,
        *,
        parent: Mapping[str, object],
        room_id: str,
        target_participant_id: str,
        commit_id: str,
    ) -> dict[str, object]:
        target = self.rooms.participant(target_participant_id)
        if target.get("roomId") != room_id or target.get("status") != "active":
            raise RoomCommitProposalError(
                "handoff target is not an active participant in this Room"
            )
        if target.get("id") == parent.get("targetParticipantId"):
            raise RoomCommitProposalError(
                "handoff target must differ from the current owner"
            )
        session_id = str(target.get("sessionId") or "").strip()
        if not session_id or self.kernel.session_binding(session_id) is not None:
            raise RoomCommitProposalError("handoff target is currently busy")
        previous = self.capabilities.runtime_binding(
            session_id,
            active_only=False,
        )
        if previous is not None and previous.get("state") in {
            "active",
            "prepared",
        }:
            raise RoomCommitProposalError("handoff target capability is still active")
        capability_epoch = (
            max(1, int(previous.get("capabilityEpoch") or 0) + 1)
            if previous is not None
            else 1
        )
        child_id = _stable_id(
            "room-dispatch",
            commit_id,
            target_participant_id,
        )
        return {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": child_id,
            "rootId": parent["rootId"],
            "taskId": parent["taskId"],
            "parentDispatchId": parent["dispatchId"],
            "generation": parent["generation"],
            "hopCount": int(parent["hopCount"]) + 1,
            "depth": int(parent["depth"]),
            "budgetCost": 1,
            "targetSessionId": session_id,
            "targetParticipantId": target_participant_id,
            "triggerId": commit_id,
            "intentKind": "resume",
            "idempotencyKey": f"room-handoff:{commit_id}:{target_participant_id}",
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": (
                f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                f"{target.get('roleId')}@{target.get('roleVersion') or '1'}"
            ),
            "state": "pending",
        }


def _resource_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    allowed = (
        "inputTokens",
        "outputTokens",
        "toolCalls",
        "toolCost",
        "retryCount",
        "repairCount",
    )
    result: dict[str, int] = {}
    for key in allowed:
        raw = value.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"resourceUsage.{key} must be non-negative")
        result[key] = raw
    return result


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list):
        raise RoomCommitProposalError(f"{name} must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for item in value[:64]:
        text = str(item or "").strip()
        if not text:
            raise RoomCommitProposalError(f"{name} contains an empty item")
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:40]}"


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _non_negative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _positive_int(payload: Mapping[str, object], key: str) -> int:
    value = _non_negative_int(payload, key)
    if value < 1:
        raise ValueError(f"{key} must be positive")
    return value


def _bounded(value: object, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]
