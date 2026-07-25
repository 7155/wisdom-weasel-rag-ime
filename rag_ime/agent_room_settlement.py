from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping

from .agent_room_acceptance import (
    AcceptanceAliasError,
    acceptance_alias_map,
    resolve_acceptance_aliases,
)
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_continuations import (
    RoomContinuationFactory,
    RoomContinuationProposalError,
)
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
from .agent_room_kernel_application import RoomKernelApplicationService
from .agent_room_kernel_contracts import (
    ROOM_COMMIT_SCHEMA_VERSION,
)
from .agent_room_quality_gate import (
    RoomQualityGateError,
    canonicalize_quality_gate,
)
from .agent_room_references import (
    ParticipantReferenceError,
    participant_ref_map,
    resolve_participant_ref,
)
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
        self.continuations = RoomContinuationFactory(
            rooms=rooms,
            kernel=kernel,
            capabilities=capabilities,
        )

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
            details = (
                replay.get("details")
                if isinstance(replay.get("details"), Mapping)
                else {}
            )
            reason = str(details.get("reason") or "missing_room_commit")
            return self._follow_up_result(
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason=reason,
                receipt=replay,
                follow_up_kind=_follow_up_kind(reason),
            )
        if invocation is None:
            return self._record_follow_up(
                room_id=room_id,
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason="missing_room_commit",
                follow_up_kind="continue",
            )

        try:
            commit = self._canonical_commit(
                manifest=manifest,
                invocation=invocation,
                now_ms=timestamp,
            )
        except RoomCommitProposalError as exc:
            return self._record_follow_up(
                room_id=room_id,
                settle_receipt=settle_receipt,
                settle_attempt=settle_attempt,
                reason=str(exc),
                follow_up_kind="repair_commit",
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

    def _record_follow_up(
        self,
        *,
        room_id: str,
        settle_receipt: Mapping[str, object],
        settle_attempt: int,
        reason: str,
        follow_up_kind: str,
    ) -> dict[str, object]:
        result = self.application.settle(
            room_id,
            {
                "settleReceipt": settle_receipt,
                "guardReason": _bounded(reason, 500),
            },
        )
        return self._follow_up_result(
            settle_receipt=settle_receipt,
            settle_attempt=settle_attempt,
            reason=reason,
            receipt=result["receipt"],
            follow_up_kind=follow_up_kind,
        )

    def _follow_up_result(
        self,
        *,
        settle_receipt: Mapping[str, object],
        settle_attempt: int,
        reason: str,
        receipt: Mapping[str, object],
        follow_up_kind: str,
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
        if follow_up_kind not in {"continue", "repair_commit"}:
            raise RuntimeError("Room settle follow-up kind is invalid")
        follow_up_key = str(receipt["receiptId"])
        return {
            "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
            "state": follow_up_kind,
            "dispatchId": settle_receipt["dispatchId"],
            "settleAttempt": settle_attempt,
            "reason": _bounded(reason, 500),
            "followUpKey": follow_up_key,
            "message": self._follow_up_instruction(
                dispatch_id=str(settle_receipt["dispatchId"]),
                reason=reason,
                follow_up_kind=follow_up_kind,
            ),
            "guardReceipt": dict(receipt),
        }

    def _follow_up_instruction(
        self,
        *,
        dispatch_id: str,
        reason: str,
        follow_up_kind: str,
    ) -> str:
        task = self.kernel.task(str(self.kernel.dispatch(dispatch_id)["taskId"]))
        aliases = list(
            acceptance_alias_map(
                task.get("acceptanceCriterionIds", [])
            )
        )
        allowed = json.dumps(aliases, ensure_ascii=False)
        commit_shape = (
            '{"decision":"deliver|handoff|wait|blocked","summary":"...",'
            '"evidence":[{"acceptance":"AC-1","refs":["<权威回执>"]}],'
            '"residualRisks":[]}'
        )
        if follow_up_kind == "continue":
            lead = (
                "当前受管任务还没有合法收工。一次模型回答结束不等于任务完成。"
                "先读取当前 Task，找出尚未满足的验收项；若仍有合法下一步，"
                "且该动作不同于已经失败的尝试、能够产生新证据，才继续使用"
                "已授权工具推进并核验证据。若没有这种合法新动作，立即选择 "
                "handoff、wait 或 blocked，而不是继续空转。"
            )
        else:
            lead = (
                "责任提交没有通过确定性校验："
                f"{_bounded(reason, 300)}。若任务本身仍未完成，先继续干活；"
                "若已经完成，只修正提交字段和证据，不要重做已通过的工作；"
                "若当前模型无法完成且没有合法新动作，改为 handoff、wait 或 "
                "blocked。"
            )
        return (
            '<managed-task-follow-up origin="room-kernel" '
            f'kind="{follow_up_kind}">'
            "这是 Kernel 生成的受管执行接续，不是用户提出了新需求。"
            f"{lead}"
            "handoff 必须说明建议接手的参与者或模型能力、已完成工作、失败证据"
            "和准确接手点；wait 要写明等待对象、信号与恢复条件，只有 "
            "waitingFor=user 时才向用户提出一个最小必要问题；blocked 必须写明"
            "缺口、已尝试替代路径和恢复条件。"
            "续作次数是硬预算，不得重复同一失败动作、提示或调用来消耗它。"
            "不要复述进度，也不要为了结束本轮而虚构等待、阻塞或完成。"
            "只有已经形成合法生命周期出口时，才调用 room_commit，明确选择 "
            "deliver、handoff、wait 或 blocked，并填写 summary、evidence 与 "
            f"residualRisks。公共形状是 {commit_shape}。"
            f"当前验收别名只有 {allowed}；不要填写数据库 criterionId，"
            "不要自报 pass 或 verdict。Kernel 会核对回执、计算覆盖与终态。"
            "handoff 还要填写 targetParticipantRef、nextTask、expectedOutput "
            "intent 与 acceptanceAliases；wait 要填写 waitingFor 和 resumeCondition；"
            "blocked 要填写 blocker、attemptedAlternatives 和 unlockCondition。"
            "不要只在自然语言里声称完成。"
            "</managed-task-follow-up>"
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
        summary = _required_text(arguments, "summary")
        dispatch = self.kernel.dispatch(str(manifest["dispatchId"]))
        task = self.kernel.task(str(dispatch["taskId"]))
        root = self.kernel.root(str(manifest["rootId"]))
        task_criteria = [
            str(item)
            for item in task.get("acceptanceCriterionIds", [])
            if str(item).strip()
        ]
        alias_map = acceptance_alias_map(task_criteria)
        accepted_evidence_by_criterion = (
            self.kernel.accepted_evidence_by_criterion(
                str(root["rootId"])
            )
        )
        requirement_context = self.application.requirements.dispatch_context(
            str(dispatch["dispatchId"])
        )
        try:
            canonical_gate = canonicalize_quality_gate(
                evidence_proposal=arguments.get("evidence"),
                residual_risks=arguments.get("residualRisks"),
                decision=decision,
                task_criteria=task_criteria,
                acceptance_aliases=alias_map,
                requirement_context=requirement_context,
                accepted_evidence_by_criterion=(
                    accepted_evidence_by_criterion
                ),
                runtime_evidence_refs=sorted(
                    self.capabilities.runtime_evidence_refs(
                        session_id=str(dispatch["targetSessionId"]),
                        dispatch_id=str(dispatch["dispatchId"]),
                    )
                ),
                root_id=str(root["rootId"]),
                task_id=str(dispatch["taskId"]),
                dispatch_id=str(dispatch["dispatchId"]),
                generation=int(dispatch["generation"]),
                invocation_receipt_id=str(invocation["receiptId"]),
                now_ms=now_ms,
            )
        except RoomQualityGateError as exc:
            raise RoomCommitProposalError(str(exc)) from exc
        quality_gate_receipt = canonical_gate.receipt
        evidence_refs = list(canonical_gate.evidence_refs)
        requirement_coverage = list(
            canonical_gate.requirement_coverage
        )
        commit_id = _stable_id(
            "room-commit",
            str(invocation["receiptId"]),
        )
        next_task = str(arguments.get("nextTask") or "").strip()
        public_content = str(
            arguments.get("publicSummary") or summary
        ).strip()
        if decision == "handoff" and next_task:
            public_content = f"{public_content}\n\n下一步：{next_task}"
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
        post_blocks = arguments.get("blocks")
        if post_blocks is not None:
            post_proposal["blocks"] = list(post_blocks)

        continuation: dict[str, object] = {
            "decision": {
                "deliver": "complete",
                "handoff": "dispatch",
                "wait": "wait",
                "blocked": "block",
            }[decision]
        }
        if decision == "handoff":
            next_task = _required_text(arguments, "nextTask")
            next_expected_output = _required_text(
                arguments,
                "expectedOutput",
            )
            room = self.rooms.get(str(root["roomId"]))
            participant_refs = participant_ref_map(
                room["participants"]
            )
            raw_aliases = arguments.get("acceptanceAliases")
            if not isinstance(raw_aliases, list):
                raise RoomCommitProposalError(
                    "handoff acceptanceAliases must be an array"
                )
            try:
                target_participant_id = resolve_participant_ref(
                    arguments.get("targetParticipantRef"),
                    participant_refs,
                )
                handoff_criteria = resolve_acceptance_aliases(
                    raw_aliases,
                    alias_map,
                    field_name="acceptanceAliases",
                )
                continuation.update(
                    self.continuations.build(
                        parent_dispatch=dispatch,
                        parent_task=task,
                        room_id=str(root["roomId"]),
                        target_participant_id=target_participant_id,
                        trigger_id=commit_id,
                        intent_kind=_required_text(arguments, "intent"),
                        objective=next_task,
                        expected_output=next_expected_output,
                        acceptance_criterion_ids=handoff_criteria,
                        context_evidence_refs=[
                            *(
                                ref
                                for refs in accepted_evidence_by_criterion.values()
                                for ref in refs
                            ),
                            *evidence_refs,
                        ],
                        kind="handoff",
                    )
                )
            except (
                AcceptanceAliasError,
                ParticipantReferenceError,
                RoomContinuationProposalError,
            ) as exc:
                raise RoomCommitProposalError(str(exc)) from exc
        elif decision == "wait":
            _required_text(arguments, "waitingFor")
            _required_text(arguments, "resumeCondition")
        elif decision == "blocked":
            _required_text(arguments, "blocker")
            attempted = arguments.get("attemptedAlternatives")
            if not isinstance(attempted, list) or not attempted:
                raise RoomCommitProposalError(
                    "blocked requires attemptedAlternatives"
                )
            _required_text(arguments, "unlockCondition")
        material = {
            "decision": decision,
            "summary": summary,
            "evidenceRefs": evidence_refs,
            "requirementCoverage": requirement_coverage,
            "qualityGateReceipt": quality_gate_receipt,
            "continuation": continuation,
        }
        commit = {
            "schemaVersion": ROOM_COMMIT_SCHEMA_VERSION,
            "commitId": commit_id,
            "dispatchId": dispatch["dispatchId"],
            "action": "post",
            "contentHash": f"sha256:{_sha256_json(material)}",
            "postProposal": post_proposal,
            "continuation": continuation,
            "qualityGateReceipt": quality_gate_receipt,
            "evidenceRefs": evidence_refs,
            "requirementCoverage": requirement_coverage,
            "createdAtMs": now_ms,
        }
        return commit


def _follow_up_kind(reason: str) -> str:
    return "continue" if reason == "missing_room_commit" else "repair_commit"


def _invocation_arguments(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    command = value.get("canonicalCommand")
    arguments = command.get("arguments") if isinstance(command, Mapping) else None
    return arguments if isinstance(arguments, Mapping) else {}


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
