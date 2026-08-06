from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from .agent_room_acceptance import (
    AcceptanceAliasError,
    acceptance_alias_map,
    resolve_acceptance_aliases,
)
from .agent_definitions import (
    canonical_collaboration_role_id,
    collaboration_role,
)
from .agent_room_capabilities import (
    REVIEW_FINDING_BLOCKING_CATEGORIES,
    REVIEW_FINDING_CATEGORY_SET,
    REVIEW_FINDING_GOVERNANCE_INVARIANTS,
    REVIEW_FINDING_RE_REVIEW_EXCEPTION_CATEGORIES,
    RoomCapabilityManifestStore,
    canonical_review_finding_fingerprint,
)
from .agent_room_continuations import (
    RoomContinuationFactory,
    RoomContinuationProposalError,
)
from .agent_room_kernel import RoomKernelFenceError, RoomKernelStore
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
    ref_for_participant,
    resolve_participant_ref,
)
from .agent_room_public_timeline import (
    assert_public_room_report_claims,
    public_room_report_content,
)
from .agent_rooms import AgentRoomStore

_RE_REVIEW_BLOCKING_EXCEPTION_CATEGORIES = (
    REVIEW_FINDING_RE_REVIEW_EXCEPTION_CATEGORIES
)

class RoomCommitProposalError(ValueError):
    """The model's proposal is repairable without weakening Kernel fences."""


class _RoomCommitParticipantWait(RoomCommitProposalError):
    """A final-delivery proposal must first wait for one active peer Dispatch."""

    def __init__(self, *, participant_id: str, dispatch_id: str) -> None:
        super().__init__("active participant work must finish before delivery")
        self.participant_id = participant_id
        self.dispatch_id = dispatch_id


def _active_peer_wait_target(
    children: Sequence[Mapping[str, object]],
    *,
    facilitator_id: str,
) -> Mapping[str, object] | None:
    for child in children:
        participant_id = str(child.get("targetParticipantId") or "")
        if (
            not participant_id
            or participant_id == facilitator_id
            or child.get("resultPublic") is True
            or str(child.get("intentKind") or "") not in {"execute", "revise"}
            or str(child.get("state") or "")
            in {"committed", "failed", "cancelled", "stale"}
        ):
            continue
        if str(child.get("dispatchId") or ""):
            return child
    return None


class RequirementContextSource(Protocol):
    """The frozen requirement snapshot for one Dispatch."""

    def dispatch_context(self, dispatch_id: str) -> dict[str, object] | None:
        ...


class SettlementApplication(Protocol):
    """What settlement needs from the layer above it — and nothing more.

    Settlement previously imported `RoomKernelApplicationService` outright,
    which pointed a domain module at the application layer for two calls and
    dragged the whole application import graph into every settlement test. The
    surface is narrow enough to state directly, so it is stated here: the
    concrete service still satisfies it structurally, and a test or a second
    application implementation can now substitute a stub without constructing
    the real service.
    """

    requirements: RequirementContextSource

    def revoke_session(
        self,
        session_id: str,
        now_ms: int,
    ) -> None:
        ...
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
        ...

    def prepare_revision_handoff_task(
        self,
        *,
        parent_dispatch: Mapping[str, object],
        parent_task: Mapping[str, object],
        target_participant_id: str,
        child_task: Mapping[str, object],
        review_findings: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        ...

    def assert_read_only_workspace_unchanged(
        self,
        task: Mapping[str, object],
    ) -> None:
        ...


    def settle(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        ...


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
        application: SettlementApplication,
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
            revoke_session=application.revoke_session,
        )

    def settle(self, payload: Mapping[str, object]) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        dispatch_id = _required_text(payload, "dispatchId")
        root_id = _required_text(payload, "rootId")
        generation = _non_negative_int(payload, "generation")
        capability_epoch = _non_negative_int(payload, "capabilityEpoch")
        settle_scope_id = _required_text(payload, "settleScopeId")
        settle_attempt = _positive_int(payload, "settleAttempt")
        runtime_turn_id = _required_text(payload, "runtimeTurnId")
        dispatch_attempt = _non_negative_int(
            payload,
            "dispatchAttempt",
        )

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

        definition = self.kernel.definition_fence(
            root_id=root_id,
            dispatch_id=dispatch_id,
        )
        if definition is not None:
            dispatch = self.kernel.dispatch(dispatch_id)
            define_invocation = self.capabilities.latest_runtime_invocation(
                session_id=session_id,
                dispatch_id=dispatch_id,
                tool_name="room_define",
            )
            define_execution = (
                self.capabilities.execution_receipt(
                    str(define_invocation["receiptId"])
                )
                if define_invocation is not None
                else None
            )
            if dispatch.get("state") != "committed" or define_execution is None:
                raise RoomKernelFenceError(
                    "room_define fence is missing its committed execution receipt"
                )
            return {
                "schemaVersion": "wisdom-weasel.room-settle-lifecycle-result.v1",
                "state": "committed",
                "dispatchId": dispatch_id,
                "settleAttempt": settle_attempt,
                "executionReceipt": define_execution,
                "definitionReceipt": definition["receipt"],
                "replayed": True,
            }

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
                runtime_turn_id=runtime_turn_id,
                dispatch_attempt=dispatch_attempt,
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
                runtime_turn_id=runtime_turn_id,
                dispatch_attempt=dispatch_attempt,
                reason=str(exc),
                follow_up_kind="repair_commit",
            )

        result = self.application.settle(
            room_id,
            {
                "settleReceipt": settle_receipt,
                "commit": commit,
                "invocationReceiptId": invocation["receiptId"],
                "runtimeTurnId": runtime_turn_id,
                "dispatchAttempt": dispatch_attempt,
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
        runtime_turn_id: str,
        dispatch_attempt: int,
        reason: str,
        follow_up_kind: str,
    ) -> dict[str, object]:
        result = self.application.settle(
            room_id,
            {
                "settleReceipt": settle_receipt,
                "guardReason": _bounded(reason, 500),
                "runtimeTurnId": runtime_turn_id,
                "dispatchAttempt": dispatch_attempt,
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
                "这部分工作还没有正确结束。一次回答结束不等于工作完成。"
                "先用 room_state 查看当前工作卡片和尚未满足的验收项；如果还有"
                "不同于已失败尝试、并且能产生新结果的下一步，就继续使用已给出的"
                "工具推进和验证。若没有这种新动作，立即选择 handoff、wait 或 "
                "blocked，不要原地重复。"
            )
        else:
            lead = (
                "本次结束请求没有通过检查："
                f"{_bounded(reason, 300)}。如果工作仍未完成，先继续动手；"
                "如果已经完成，只修正提交字段和证据，不要重做已验证的内容；"
                "如果自己无法继续且没有新的合法动作，改为 handoff、wait 或 "
                "blocked。"
            )
        return (
            '<room-work-follow-up source="system" '
            f'kind="{follow_up_kind}">'
            "这是系统要求补齐本轮工作，不是用户提出了新需求。"
            f"{lead}"
            "handoff 要说明建议接手的伙伴或所需能力、已经完成什么、失败证据和"
            "准确接手点；wait 要写清等待谁、等待什么信号、何时继续，只有 "
            "waitingFor=user 时才向用户提出一个最小必要问题；blocked 要写清"
            "卡点、已经试过的替代办法和恢复条件。"
            "可继续次数有限，不得重复同一失败动作、提示或调用来消耗次数。"
            "不要复述进度，也不要为了结束本轮而虚构等待、阻塞或完成。"
            "只有已经形成清楚的结束方式时，才调用 room_commit，选择 "
            "deliver、handoff、wait 或 blocked，并填写 summary、evidence 与 "
            f"residualRisks。提交结构示例：{commit_shape}。"
            f"当前可用的验收短名只有 {allowed}；AC-1 表示工作卡片中的第一项"
            "验收。不要填写内部 criterionId，也不要自行填写 pass 或 verdict；"
            "服务端会核对实际结果并判断是否可以结束。"
            "handoff 还要填写 targetParticipantRef、nextTask、expectedOutput、"
            "intent 与 acceptanceAliases；wait 要填写 waitingFor 和 "
            "resumeCondition，等待伙伴时还要从 room_state 原样复制 "
            "waitingForParticipantRef；blocked 要填写 blocker、"
            "attemptedAlternatives 和 unlockCondition。"
            "不要只在自然语言里声称完成。"
            "</room-work-follow-up>"
        )

    def _assert_decision_allowed(
        self,
        decision: str,
        dispatch: Mapping[str, object],
    ) -> None:
        """Make `allowedCommitDecisions` a fence instead of catalog prose.

        The manifest declares which lifecycle exits a work lens may take. In
        particular, an independent Reviewer cannot hand its verdict to another
        author. Enforce that declaration instead of treating it as catalog prose.
        """

        participant_id = str(dispatch.get("targetParticipantId") or "")
        if not participant_id:
            return
        try:
            participant = self.rooms.participant(participant_id)
        except KeyError:
            return
        role_id = canonical_collaboration_role_id(
            participant.get("collaborationRole")
        )
        try:
            role = collaboration_role(role_id)
        except ValueError:
            return
        if decision not in role.allowed_commit_decisions:
            allowed = "、".join(role.allowed_commit_decisions)
            raise RoomCommitProposalError(
                f"{role.display_name} 不能以 {decision} 收工；本岗位可用的出口是 {allowed}"
            )

    def _is_report_dispatch(self, dispatch_id: str) -> bool:
        """Fail closed when an injected Kernel adapter lacks report support."""

        checker = getattr(self.kernel, "is_report_dispatch", None)
        if not callable(checker):
            return False
        return bool(checker(dispatch_id))

    def _assert_managed_collaboration_ready(
        self,
        *,
        decision: str,
        handoff_intent: str = "",
        root: Mapping[str, object],
        task: Mapping[str, object],
        dispatch: Mapping[str, object],
    ) -> None:
        if self._is_report_dispatch(str(dispatch.get("dispatchId") or "")):
            # The report lane is created only after the Kernel has re-derived
            # worker delivery, integration, review, and quiescence fences. It
            # does not mutate the reviewed artifact, so re-running the
            # pre-report Facilitator gate would make the report Task itself
            # appear as a post-review artifact change.
            return
        is_final_delivery = decision == "deliver"
        is_review_handoff = (
            decision == "handoff" and handoff_intent == "review"
        )
        if (
            not (is_final_delivery or is_review_handoff)
            or str(dispatch.get("intentKind") or "") == "align"
            or task.get("parentTaskId")
            or str(dispatch.get("targetParticipantId") or "")
            != str(root.get("facilitatorParticipantId") or "")
        ):
            return
        room = self.rooms.get(str(root["roomId"]))
        managed_work = next(
            (
                value
                for value in room.get("workItems", ())
                if isinstance(value, Mapping)
                and str(value.get("rootTurnId") or "")
                == str(root["rootId"])
                and str(value.get("clientMessageId") or "").startswith(
                    "managed-room-ingress:"
                )
            ),
            None,
        )
        routing_policy = str(room.get("routingPolicy") or "natural")
        required_peer_count = 0
        if managed_work is not None:
            managed_client_id = str(
                managed_work.get("clientMessageId") or ""
            )
            parts = managed_client_id.split(":", 4)
            required_peer_count = -1
            try:
                if (
                    len(parts) == 5
                    and parts[:2] == ["managed-room-ingress", "v2"]
                ):
                    routing_policy = parts[2]
                    required_peer_count = int(parts[3])
                elif (
                    len(parts) == 4
                    and parts[:2] == ["managed-room-ingress", "v1"]
                ):
                    routing_policy = "natural"
                    required_peer_count = int(parts[2])
            except ValueError:
                required_peer_count = -1
            if required_peer_count < 0:
                raise RoomCommitProposalError(
                    "Room 协作信息不完整，当前工作无法安全结束"
                )
        elif routing_policy == "parallel":
            facilitator_id = str(
                root.get("facilitatorParticipantId") or ""
            )
            eligible_peers = [
                participant
                for participant in room.get("participants", ())
                if isinstance(participant, Mapping)
                and participant.get("status") == "active"
                and str(participant.get("id") or "") != facilitator_id
                and canonical_collaboration_role_id(
                    participant.get("collaborationRole")
                ) != "reviewer"
            ]
            required_peer_count = 1 if eligible_peers else 0
        facilitator_id = str(
            root.get("facilitatorParticipantId") or ""
        )
        managed_children: list[dict[str, object]] = []
        if routing_policy == "parallel":
            managed_children = self.kernel.collaboration_children(
                str(root["rootId"])
            )
            public_peer_ids = {
                str(child.get("targetParticipantId") or "")
                for child in managed_children
                if child.get("resultPublic") is True
                and str(child.get("intentKind") or "") == "execute"
                and str(child.get("targetParticipantId") or "")
                != facilitator_id
            }
            if len(public_peer_ids) < required_peer_count:
                waiting_child = _active_peer_wait_target(
                    managed_children,
                    facilitator_id=facilitator_id,
                )
                if waiting_child is not None:
                    raise _RoomCommitParticipantWait(
                        participant_id=str(
                            waiting_child["targetParticipantId"]
                        ),
                        dispatch_id=str(waiting_child["dispatchId"]),
                    )
                raise RoomCommitProposalError(
                    "Facilitator 尚未通过 room_collaborate 收齐隔离并行结果；"
                    "先拆分可独立工作并等待伙伴公开结果，再完成串行集成。"
                    f"需要 {required_peer_count} 位，已公开 "
                    f"{len(public_peer_ids)} 位"
                )
        elif required_peer_count:
            managed_children = self.kernel.collaboration_children(
                str(root["rootId"])
            )
            public_participant_ids = {
                str(child.get("targetParticipantId") or "")
                for child in managed_children
                if child.get("resultPublic") is True
                and str(child.get("targetParticipantId") or "")
                != facilitator_id
            }
            if len(public_participant_ids) < required_peer_count:
                waiting_child = _active_peer_wait_target(
                    managed_children,
                    facilitator_id=facilitator_id,
                )
                if waiting_child is not None:
                    raise _RoomCommitParticipantWait(
                        participant_id=str(
                            waiting_child["targetParticipantId"]
                        ),
                        dispatch_id=str(waiting_child["dispatchId"]),
                    )
                raise RoomCommitProposalError(
                    "其他伙伴的公开结果尚未到齐；先邀请缺少的伙伴继续工作，"
                    "再选择等待，结果到齐后才能发布最终回复。"
                    f"需要 {required_peer_count} 位，已公开 "
                    f"{len(public_participant_ids)} 位"
                )
        children = managed_children or self.kernel.collaboration_children(
            str(root["rootId"])
        )
        records = [
            (child, self.kernel.task(str(child["taskId"])))
            for child in children
        ]
        unfinished_work = [
            child_task
            for child, child_task in records
            if str(child.get("intentKind") or "") in {"execute", "revise"}
            and child_task.get("state") != "completed"
        ]
        if unfinished_work:
            waiting_child = _active_peer_wait_target(
                children,
                facilitator_id=facilitator_id,
            )
            if waiting_child is not None:
                raise _RoomCommitParticipantWait(
                    participant_id=str(waiting_child["targetParticipantId"]),
                    dispatch_id=str(waiting_child["dispatchId"]),
                )
            raise RoomCommitProposalError(
                "仍有实现或检查子任务没有完成；先等待其公开工作结果，"
                "不要提前发布最终回复"
            )
        pending_integrations = [
            child_task
            for _child, child_task in records
            if child_task.get("workspacePolicy") == "isolated_writable"
            and child_task.get("workspaceIntegrationState") != "applied"
        ]
        if pending_integrations:
            raise RoomCommitProposalError(
                "仍有独立 worktree 尚未合入；先用 room_integrate 完成集成和验证"
            )
        if is_review_handoff:
            # Starting the review must cross the same peer-result and
            # integration fences as final delivery, but cannot require an
            # already accepted review.
            return
        latest_attempts = self.kernel.latest_review_attempts(
            str(root["rootId"])
        )
        independent_review_required = root.get("independentReviewRequired")
        if not isinstance(independent_review_required, bool):
            raise RoomCommitProposalError(
                "Root independent review policy is missing or invalid; "
                "completion is blocked"
            )
        if not latest_attempts:
            if independent_review_required:
                raise RoomCommitProposalError(
                    "集成后必须先用 room_commit handoff 把完整结果交给 Reviewer "
                    "独立复核，不能直接发布最终回复"
                )
            return
        for latest_attempt in latest_attempts:
            latest_review = latest_attempt.get("dispatch")
            review_task = latest_attempt.get("payload")
            if not isinstance(latest_review, Mapping):
                latest_review = {}
            if not isinstance(review_task, Mapping):
                review_task = {}
            review_task = {
                **dict(review_task),
                "state": str(latest_attempt.get("taskState") or ""),
            }
            if (
                latest_attempt.get("resultPublic") is not True
                or review_task.get("state") != "completed"
                or review_task.get("reviewState")
                not in {"accepted", "accepted_with_notes"}
            ):
                raise RoomCommitProposalError(
                    "最新独立复核尚未通过；按复核意见修正并发起新的独立复核"
                )
            reviewer_id = str(
                latest_review.get("targetParticipantId") or ""
            )
            authors = {
                str(value)
                for value in review_task.get(
                    "reviewAuthorParticipantIds",
                    (),
                )
                if str(value).strip()
            }
            if not authors or reviewer_id in authors:
                raise RoomCommitProposalError(
                    "最新复核没有独立作者边界，不能作为最终交付依据"
                )
            required_review_task_ids = {
                str(task.get("taskId") or ""),
                *(
                    str(child_task.get("taskId") or "")
                    for child, child_task in records
                    if str(child.get("intentKind") or "")
                    in {"execute", "revise"}
                ),
            }
            required_review_task_ids.discard("")
            reviewed_task_ids = {
                str(value)
                for value in review_task.get("reviewOfTaskIds", ())
                if str(value or "").strip()
            }
            missing_review_task_ids = sorted(
                required_review_task_ids - reviewed_task_ids
            )
            if missing_review_task_ids:
                raise RoomCommitProposalError(
                    "最新独立复核没有覆盖当轮全部实现与修正结果；"
                    "请基于完整集成结果重新复核"
                )
            self.application.assert_read_only_workspace_unchanged(
                review_task
            )
            expected_revision = str(
                review_task.get("reviewTargetRevision") or ""
            )
            current_revision = self.kernel.review_target_revision(
                root_id=str(root["rootId"]),
                task_ids=[
                    str(value)
                    for value in review_task.get("reviewOfTaskIds", ())
                    if str(value or "").strip()
                ],
                review_snapshot=review_task,
            )
            if (
                not expected_revision
                or current_revision != expected_revision
            ):
                raise RoomCommitProposalError(
                    "最新独立复核已过期；交付内容变更后必须重新复核"
                )
            unresolved_findings = [
                finding
                for finding in review_task.get("reviewFindings", ())
                if isinstance(finding, Mapping)
                and (
                    (
                        finding.get("gateEffect") == "blocking"
                        and finding.get("state")
                        in {"open", "contested", "escalated"}
                    )
                    or (
                        finding.get("gateEffect") == "advisory"
                        and finding.get("state") == "open"
                    )
                )
            ]
            if unresolved_findings:
                raise RoomCommitProposalError(
                    "最新独立复核仍有未明确处置的 Review Finding"
                )

    def _assert_review_evidence_ready(
        self,
        *,
        decision: str,
        root: Mapping[str, object],
        task: Mapping[str, object],
        dispatch: Mapping[str, object],
        evidence_refs: Sequence[str],
    ) -> None:
        if self._is_report_dispatch(str(dispatch.get("dispatchId") or "")):
            return
        if (
            decision != "deliver"
            or task.get("parentTaskId")
            or str(dispatch.get("targetParticipantId") or "")
            != str(root.get("facilitatorParticipantId") or "")
        ):
            return
        latest_attempt = self.kernel.latest_review_attempt(
            str(root["rootId"])
        )
        if latest_attempt is None:
            return
        latest_review = latest_attempt.get("dispatch")
        review_task = latest_attempt.get("payload")
        review_commit = latest_attempt.get("commit")
        if not isinstance(latest_review, Mapping):
            latest_review = {}
        if not isinstance(review_task, Mapping):
            review_task = {}
        review_task = {
            **dict(review_task),
            "state": str(latest_attempt.get("taskState") or ""),
        }
        if not isinstance(review_commit, Mapping):
            review_commit = None
        gate = (
            review_commit.get("qualityGateReceipt")
            if isinstance(review_commit, Mapping)
            else None
        )
        review_evidence = {
            str(ref)
            for item in (
                gate.get("items", ())
                if isinstance(gate, Mapping)
                else ()
            )
            if isinstance(item, Mapping) and item.get("status") == "pass"
            for ref in item.get("evidenceRefs", ())
            if str(ref).strip()
        }
        binding = (
            review_commit.get("reviewEvidenceBinding")
            if isinstance(review_commit, Mapping)
            else None
        )
        bound_evidence = {
            str(ref)
            for ref in (
                binding.get("evidenceRefs", ())
                if isinstance(binding, Mapping)
                else ()
            )
            if str(ref).strip()
        }
        expected_binding = (
            isinstance(binding, Mapping)
            and binding.get("reviewTargetRevision")
            == review_task.get("reviewTargetRevision")
            and binding.get("taskId") == review_task.get("taskId")
            and binding.get("dispatchId") == latest_review.get("dispatchId")
            and int(binding.get("notBeforeMs") or -1)
            == int(review_task.get("reviewEvidenceNotBeforeMs") or 0)
            and bound_evidence == review_evidence
        )
        if not expected_binding:
            raise RoomCommitProposalError(
                "最新独立复核的 evidence 未绑定到当前 reviewTargetRevision"
            )
        if not bound_evidence.intersection(evidence_refs):
            raise RoomCommitProposalError(
                "最终回复必须直接引用最新独立复核的成功 evidenceRef"
            )

    def _canonical_review_findings(
        self,
        *,
        value: object,
        task: Mapping[str, object],
        root: Mapping[str, object],
        decision: str,
        acceptance_aliases: Mapping[str, str],
        evidence_refs: Sequence[str],
        runtime_evidence_refs: set[str],
    ) -> list[dict[str, object]]:
        is_review = str(task.get("taskKind") or "") == "review"
        if not is_review:
            if value is not None:
                raise RoomCommitProposalError(
                    "reviewFindings is only valid for a Reviewer Task"
                )
            return []
        if value is None:
            prior_blockers = any(
                isinstance(item, Mapping)
                and item.get("gateEffect") == "blocking"
                and item.get("state") in {"open", "contested", "escalated"}
                for item in task.get("reviewFindings", ())
            )
            if decision == "wait" and not prior_blockers:
                return []
            raise RoomCommitProposalError(
                "Reviewer completion requires the complete reviewFindings array"
            )
        if not isinstance(value, list):
            raise RoomCommitProposalError("reviewFindings must be an array")
        if len(value) > 64:
            raise RoomCommitProposalError(
                "reviewFindings may contain at most 64 findings"
            )
        target_revision = str(task.get("reviewTargetRevision") or "")
        if not target_revision:
            raise RoomCommitProposalError(
                "Reviewer Task is missing reviewTargetRevision"
            )
        room = self.rooms.get(str(root["roomId"]))
        participant_refs = participant_ref_map(room["participants"])
        previous_findings = [
            item
            for item in task.get("reviewFindings", ())
            if isinstance(item, Mapping)
        ]
        previous = {
            str(item.get("findingId") or ""): item
            for item in previous_findings
        }
        previous_blocking_scopes = {
            _review_scope_key(item.get("scope"))
            for item in previous_findings
            if item.get("gateEffect") == "blocking"
        }
        previous_blocking_scopes.discard(None)
        previous_blocking = {
            str(item.get("findingId") or ""): item
            for item in previous_findings
            if item.get("gateEffect") == "blocking"
            and item.get("state") in {"open", "contested", "escalated"}
            and str(item.get("findingId") or "").strip()
        }
        review_round = max(1, int(task.get("reviewRound") or 1))
        selected_evidence = set(evidence_refs)
        findings: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        seen_fingerprints: set[str] = set()
        for index, raw in enumerate(value):
            if not isinstance(raw, Mapping):
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}] must be an object"
                )

            def text(key: str, *, limit: int = 2000) -> str:
                candidate = str(raw.get(key) or "").strip()
                if not candidate or len(candidate) > limit:
                    raise RoomCommitProposalError(
                        f"reviewFindings[{index}].{key} is invalid"
                    )
                return candidate

            finding_id = text("findingId", limit=160)
            if finding_id in seen_ids:
                raise RoomCommitProposalError(
                    "reviewFindings findingId values must be unique"
                )
            seen_ids.add(finding_id)
            gate_effect = text("gateEffect", limit=16)
            impact = text("impact", limit=16)
            category = text("category", limit=32)
            if category not in REVIEW_FINDING_CATEGORY_SET:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].category is invalid"
                )
            state = text("state", limit=32)
            if gate_effect not in {"blocking", "advisory"}:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].gateEffect is invalid"
                )
            if impact not in {"critical", "high", "normal"}:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].impact is invalid"
                )
            if state not in {
                "open",
                "resolved",
                "dismissed",
                "accepted_risk",
            }:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].state is invalid"
                )
            late_scope_downgraded = False
            scope_input = raw.get("scope")
            if not isinstance(scope_input, Mapping):
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].scope must be an object"
                )
            if scope_input.get("acceptance") is not None:
                try:
                    resolved = resolve_acceptance_aliases(
                        [scope_input["acceptance"]],
                        acceptance_aliases,
                        field_name=f"reviewFindings[{index}].scope.acceptance",
                    )
                except AcceptanceAliasError as exc:
                    raise RoomCommitProposalError(str(exc)) from exc
                scope = {"criterionId": resolved[0]}
            else:
                invariant_id = str(
                    scope_input.get("invariantId") or ""
                ).strip()
                if not invariant_id:
                    raise RoomCommitProposalError(
                        f"reviewFindings[{index}].scope requires acceptance "
                        "or invariantId"
                    )
                scope = {"invariantId": invariant_id}
            observation = text("observation")
            expected = text("expected")
            user_impact = text("userImpact")
            finding_evidence = _string_list(
                raw.get("evidenceRefs"),
                f"reviewFindings[{index}].evidenceRefs",
            )
            if not finding_evidence:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}].evidenceRefs must not be empty"
                )
            if not set(finding_evidence).issubset(runtime_evidence_refs):
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}] cites stale or foreign evidence"
                )
            if not set(finding_evidence).issubset(selected_evidence):
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}] evidence must also appear in "
                    "room_commit evidence"
                )
            reproduction = _string_list(
                raw.get("reproduction"),
                f"reviewFindings[{index}].reproduction",
            )
            fingerprint = canonical_review_finding_fingerprint(
                category=category,
                scope=scope,
                observation=observation,
                expected=expected,
                user_impact=user_impact,
            )
            if fingerprint in seen_fingerprints:
                raise RoomCommitProposalError(
                    "reviewFindings contains duplicate finding content"
                )
            seen_fingerprints.add(fingerprint)
            prior = previous.get(finding_id)
            same_finding = (
                isinstance(prior, Mapping)
                and prior.get("fingerprint") == fingerprint
            )
            prior_blocking = previous_blocking.get(finding_id)
            if review_round > 1 and prior_blocking is not None:
                prior_fingerprint = str(
                    prior_blocking.get("fingerprint") or ""
                )
                if prior_fingerprint != fingerprint:
                    raise RoomCommitProposalError(
                        "re-review must preserve each Blocking Finding "
                        "findingId and fingerprint"
                    )
                if gate_effect != "blocking":
                    raise RoomCommitProposalError(
                        "a prior Blocking Finding cannot be downgraded"
                    )
            first_seen_revision = (
                str(prior.get("firstSeenRevision"))
                if same_finding
                else target_revision
            )
            failed_rechecks = (
                int(prior.get("failedRechecks") or 0)
                if same_finding
                else 0
            )
            prior_state = str(prior.get("state") or "") if same_finding else ""
            response = prior.get("response") if same_finding else None
            if (
                review_round > 1
                and prior_blocking is not None
                and prior_state == "contested"
                and state == "open"
            ):
                state = "contested"
            if (
                review_round > 1
                and gate_effect == "blocking"
                and not (
                    same_finding
                    or _review_scope_key(scope) in previous_blocking_scopes
                    or _re_review_exception_category(category)
                )
            ):
                gate_effect = "advisory"
                impact = "normal"
                late_scope_downgraded = True
            if gate_effect == "blocking":
                if impact not in {"critical", "high"}:
                    raise RoomCommitProposalError(
                        "Blocking Finding requires critical/high impact"
                    )
                if category not in REVIEW_FINDING_BLOCKING_CATEGORIES:
                    raise RoomCommitProposalError(
                        f"reviewFindings[{index}].category is not admissible "
                        "as blocking"
                    )
                invariant_id = str(scope.get("invariantId") or "").strip()
                if (
                    invariant_id
                    and invariant_id
                    not in REVIEW_FINDING_GOVERNANCE_INVARIANTS
                ):
                    raise RoomCommitProposalError(
                        f"reviewFindings[{index}].scope.invariantId is not "
                        "a governed invariant"
                    )
            if gate_effect == "advisory" and impact != "normal":
                raise RoomCommitProposalError(
                    "critical/high findings must be blocking"
                )
            if state == "accepted_risk" and gate_effect != "advisory":
                raise RoomCommitProposalError(
                    "a blocking finding cannot be accepted as risk by Reviewer"
                )
            if gate_effect == "blocking" and state == "resolved":
                if (
                    not same_finding
                    or not isinstance(response, Mapping)
                    or response.get("action") != "fixed"
                    or first_seen_revision == target_revision
                ):
                    raise RoomCommitProposalError(
                        "a resolved Blocking Finding requires verified fix "
                        "lineage from an earlier review revision"
                    )
            if gate_effect == "blocking" and state == "dismissed":
                resolver = getattr(
                    getattr(self, "kernel", None),
                    "independent_finding_resolution",
                    None,
                )
                resolution = (
                    resolver(
                        root_id=str(root.get("rootId") or ""),
                        review_target_revision=target_revision,
                        finding_id=finding_id,
                    )
                    if callable(resolver)
                    and str(root.get("rootId") or "").strip()
                    else None
                )
                if not isinstance(resolution, Mapping):
                    raise RoomCommitProposalError(
                        "a dismissed Blocking Finding requires an exact "
                        "independent arbiter resolution"
                    )
            if (
                same_finding
                and prior_state in {"open", "contested"}
                and state == "open"
            ):
                failed_rechecks += 1
            if isinstance(response, Mapping) and response.get("action") == "contest":
                if state == "open":
                    state = "contested"
            if failed_rechecks >= 2 and state in {"open", "contested"}:
                state = "escalated"
                failed_rechecks = 2
            disposition = str(
                raw.get("dispositionRationale") or ""
            ).strip()
            if late_scope_downgraded and not disposition:
                disposition = (
                    "后续复核新发现且不属于允许阻塞范围；"
                    "已转为 Advisory/Backlog，不阻止当前 Root"
                )
            if state in {"dismissed", "accepted_risk"} and not disposition:
                raise RoomCommitProposalError(
                    f"reviewFindings[{index}] requires dispositionRationale"
                )
            owner_id: str | None = None
            if raw.get("ownerParticipantRef") is not None:
                try:
                    owner_id = resolve_participant_ref(
                        raw.get("ownerParticipantRef"),
                        participant_refs,
                    )
                except ParticipantReferenceError as exc:
                    raise RoomCommitProposalError(str(exc)) from exc
            if (
                owner_id is None
                and same_finding
                and str(prior.get("ownerParticipantId") or "").strip()
            ):
                owner_id = str(prior["ownerParticipantId"])
            findings.append(
                {
                    "findingId": finding_id,
                    "fingerprint": fingerprint,
                    "gateEffect": gate_effect,
                    "impact": impact,
                    "category": category,
                    "scope": scope,
                    "observation": observation,
                    "expected": expected,
                    "userImpact": user_impact,
                    "evidenceRefs": finding_evidence,
                    "reproduction": reproduction,
                    "state": state,
                    "dispositionRationale": disposition or None,
                    "ownerParticipantId": owner_id,
                    "firstSeenRevision": first_seen_revision,
                    "lastCheckedRevision": target_revision,
                    "failedRechecks": failed_rechecks,
                    "response": dict(response)
                    if isinstance(response, Mapping)
                    else None,
                }
            )
        if review_round > 1:
            missing_prior = set(previous_blocking) - seen_ids
            if missing_prior:
                raise RoomCommitProposalError(
                    "re-review must include every prior open Blocking Finding "
                    "exactly once: "
                    + ", ".join(sorted(missing_prior))
                )
        blockers = [
            finding
            for finding in findings
            if finding["gateEffect"] == "blocking"
            and finding["state"] in {"open", "contested", "escalated"}
        ]
        escalated = [
            finding for finding in blockers if finding["state"] == "escalated"
        ]
        open_advisories = [
            finding
            for finding in findings
            if finding["gateEffect"] == "advisory"
            and finding["state"] == "open"
        ]
        if decision == "deliver" and blockers:
            raise RoomCommitProposalError(
                "Reviewer cannot deliver with an open Blocking Finding"
            )
        if decision == "deliver" and open_advisories:
            raise RoomCommitProposalError(
                "Reviewer cannot deliver with an open Advisory Finding; "
                "record an explicit disposition first"
            )
        if decision == "handoff" and not blockers:
            raise RoomCommitProposalError(
                "Reviewer revision handoff requires an open Blocking Finding"
            )
        if escalated and decision != "blocked":
            raise RoomCommitProposalError(
                "a finding that failed two rechecks must be escalated as blocked"
            )
        return findings

    def _canonical_review_finding_responses(
        self,
        *,
        value: object,
        task: Mapping[str, object],
        dispatch: Mapping[str, object],
        evidence_refs: Sequence[str],
        runtime_evidence_refs: set[str],
        now_ms: int,
    ) -> list[dict[str, object]]:
        findings = [
            finding
            for finding in task.get("reviewFindings", ())
            if isinstance(finding, Mapping)
        ]
        if value is None:
            if findings and str(dispatch.get("intentKind") or "") == "revise":
                blockers = [
                    finding
                    for finding in findings
                    if finding.get("gateEffect") == "blocking"
                    and finding.get("state") in {"open", "contested"}
                ]
                if blockers:
                    raise RoomCommitProposalError(
                        "revision completion requires a response to every "
                        "open Blocking Finding"
                    )
            return []
        if str(dispatch.get("intentKind") or "") != "revise" or not findings:
            raise RoomCommitProposalError(
                "reviewFindingResponses is only valid for a Reviewer revision Task"
            )
        if not isinstance(value, list):
            raise RoomCommitProposalError(
                "reviewFindingResponses must be an array"
            )
        open_findings = {
            str(finding.get("findingId") or ""): finding
            for finding in findings
            if finding.get("gateEffect") == "blocking"
            and finding.get("state") in {"open", "contested"}
        }
        selected_evidence = set(evidence_refs)
        responses: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw in enumerate(value):
            if not isinstance(raw, Mapping):
                raise RoomCommitProposalError(
                    f"reviewFindingResponses[{index}] must be an object"
                )
            finding_id = str(raw.get("findingId") or "").strip()
            action = str(raw.get("action") or "").strip()
            rationale = str(raw.get("rationale") or "").strip()
            if (
                finding_id not in open_findings
                or finding_id in seen
                or action not in {"fixed", "contest"}
                or not rationale
            ):
                raise RoomCommitProposalError(
                    f"reviewFindingResponses[{index}] is invalid"
                )
            prior_response = open_findings[finding_id].get("response")
            if (
                action == "contest"
                and isinstance(prior_response, Mapping)
                and prior_response.get("action") == "contest"
            ):
                raise RoomCommitProposalError(
                    "each finding may be contested only once"
                )
            refs = _string_list(
                raw.get("evidenceRefs"),
                f"reviewFindingResponses[{index}].evidenceRefs",
            )
            if not set(refs).issubset(runtime_evidence_refs):
                raise RoomCommitProposalError(
                    f"reviewFindingResponses[{index}] cites stale or foreign evidence"
                )
            if not set(refs).issubset(selected_evidence):
                raise RoomCommitProposalError(
                    f"reviewFindingResponses[{index}] evidence must also appear "
                    "in room_commit evidence"
                )
            seen.add(finding_id)
            responses.append(
                {
                    "findingId": finding_id,
                    "action": action,
                    "rationale": rationale,
                    "evidenceRefs": refs,
                    "participantId": str(dispatch["targetParticipantId"]),
                    "createdAtMs": now_ms,
                }
            )
        if seen != set(open_findings):
            raise RoomCommitProposalError(
                "revision completion must respond exactly once to every "
                "open Blocking Finding"
            )
        return responses

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
        self._assert_decision_allowed(decision, dispatch)
        task = self.kernel.task(str(dispatch["taskId"]))
        root = self.kernel.root(str(manifest["rootId"]))
        is_report_dispatch = self._is_report_dispatch(
            str(dispatch["dispatchId"])
        )
        handoff_intent = str(arguments.get("intent") or "").strip()
        if decision == "handoff" and task.get("taskKind") == "review":
            if handoff_intent != "revise":
                raise RoomCommitProposalError(
                    "Reviewer handoff must use intent=revise and return findings "
                    "to the Root Facilitator"
                )
            room = self.rooms.get(str(root["roomId"]))
            caller = next(
                (
                    participant
                    for participant in room.get("participants", ())
                    if isinstance(participant, Mapping)
                    and str(participant.get("id") or "")
                    == str(dispatch.get("targetParticipantId") or "")
                    and participant.get("status") == "active"
                ),
                None,
            )
            if caller is None or str(dispatch.get("targetParticipantId") or "") != str(
                task.get("currentOwnerParticipantId") or ""
            ):
                raise RoomCommitProposalError(
                    "only the active Reviewer may return a revision handoff"
                )
            participant_refs = participant_ref_map(room["participants"])
            try:
                handoff_target_id = resolve_participant_ref(
                    arguments.get("targetParticipantRef"),
                    participant_refs,
                )
            except ParticipantReferenceError as exc:
                raise RoomCommitProposalError(str(exc)) from exc
            if handoff_target_id != str(
                root.get("facilitatorParticipantId") or ""
            ):
                raise RoomCommitProposalError(
                    "Reviewer revisions must return to the Root Facilitator"
                )
        elif decision == "handoff" and handoff_intent == "revise":
            raise RoomCommitProposalError(
                "intent=revise is reserved for an active Reviewer Task"
            )
        if decision in {"deliver", "handoff", "blocked"}:
            self.application.assert_read_only_workspace_unchanged(task)
        if decision == "deliver" and is_report_dispatch:
            reporter_id = str(
                root.get("reporterParticipantId")
                or root.get("facilitatorParticipantId")
                or ""
            )
            if str(dispatch.get("targetParticipantId") or "") != reporter_id:
                raise RoomCommitProposalError(
                    "only the Root Reporter may publish the final Room summary"
                )
        elif str(dispatch.get("intentKind") or "") == "close":
            raise RoomCommitProposalError(
                "only the canonical ReportDispatch may use the closure lane"
            )
        if (
            str(dispatch.get("intentKind") or "") == "align"
            and decision not in {"deliver", "wait"}
        ):
            raise RoomCommitProposalError(
                "需求对齐只能确认需求或等待用户澄清"
            )
        if (
            decision == "wait"
            and str(arguments.get("waitingFor") or "").strip() == "user"
            and str(dispatch.get("targetParticipantId") or "")
            != str(root.get("facilitatorParticipantId") or "")
        ):
            raise RoomCommitProposalError(
                "only the Root Facilitator may wait for user input; "
                "return the blocker to the Facilitator instead"
            )
        try:
            self._assert_managed_collaboration_ready(
                decision=decision,
                handoff_intent=handoff_intent,
                root=root,
                task=task,
                dispatch=dispatch,
            )
        except _RoomCommitParticipantWait as waiting:
            room = self.rooms.get(str(root["roomId"]))
            participant_refs = participant_ref_map(room["participants"])
            target_ref = ref_for_participant(
                waiting.participant_id,
                participant_refs,
            )
            if target_ref is None:
                raise RoomCommitProposalError(
                    "等待中的伙伴无法映射到当前 Room，不能安全继续"
                ) from waiting
            decision = "wait"
            summary = "等待并行伙伴完成当前工作后继续整合"
            arguments = {
                **dict(arguments),
                "decision": decision,
                "summary": summary,
                "publicSummary": (
                    "还有伙伴正在完成这项工作，结果回来后会继续整合。"
                ),
                "evidence": [],
                "residualRisks": ["伙伴任务尚未公开交付"],
                "waitingFor": "participant",
                "waitingForParticipantRef": target_ref,
                "resumeCondition": "该伙伴已公开当前任务的交付结果",
            }
        task_criteria = [
            str(item)
            for item in task.get("acceptanceCriterionIds", [])
            if str(item).strip()
        ]
        alias_map = acceptance_alias_map(task_criteria)
        is_review_task = str(task.get("taskKind") or "") == "review"
        if is_review_task:
            expected_revision = str(task.get("reviewTargetRevision") or "")
            current_revision = self.kernel.review_target_revision(
                root_id=str(root["rootId"]),
                task_ids=[
                    str(value)
                    for value in task.get("reviewOfTaskIds", ())
                    if str(value or "").strip()
                ],
                review_snapshot=task,
            )
            if not expected_revision or current_revision != expected_revision:
                raise RoomCommitProposalError(
                    "Reviewer target changed; discard stale findings and re-review"
                )
            accepted_evidence_by_criterion: dict[str, list[str]] = {}
        else:
            accepted_evidence_by_criterion = (
                self.kernel.accepted_evidence_by_criterion(
                    str(root["rootId"])
                )
            )
        review_evidence_not_before_ms = (
            int(task.get("reviewEvidenceNotBeforeMs") or 0)
            if is_review_task
            else 0
        )
        runtime_evidence_not_before_ms = (
            max(
                review_evidence_not_before_ms,
                int(dispatch.get("createdAtMs") or 0),
            )
            + 1
            if is_review_task
            else 0
        )
        runtime_evidence_refs = self.capabilities.runtime_evidence_refs(
            session_id=str(dispatch["targetSessionId"]),
            root_id=str(root["rootId"]),
            task_id=str(dispatch["taskId"]),
            dispatch_id=str(dispatch["dispatchId"]),
            generation=int(dispatch["generation"]),
            capability_epoch=int(dispatch["capabilityEpoch"]),
            not_before_ms=runtime_evidence_not_before_ms,
        )
        definition_fence = self.kernel.definition_fence(
            root_id=str(root["rootId"]),
            dispatch_id=str(dispatch["dispatchId"]),
        )
        if isinstance(definition_fence, Mapping):
            definition_receipt = definition_fence.get("receipt")
            context_fence = {
                key: value
                for key, value in definition_fence.items()
                if key != "receipt"
            }
            if isinstance(definition_receipt, Mapping):
                context_fence["definitionReceiptId"] = str(
                    definition_receipt.get("receiptId") or ""
                )
            requirement_context = self.application.requirements.dispatch_context(
                str(dispatch["dispatchId"]),
                catalog_revision_id=str(
                    definition_fence.get("catalogRevisionId") or ""
                ),
                context_fence=context_fence,
            )
        else:
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
                runtime_evidence_refs=sorted(runtime_evidence_refs),
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
        if (
            decision == "handoff"
            and task.get("parentTaskId")
            and task.get("taskKind") != "review"
            and task.get("workspacePolicy") == "isolated_writable"
            and task.get("workspaceIntegrationState") == "pending"
            and quality_gate_receipt.get("verdict") == "ready_to_deliver"
        ):
            raise RoomCommitProposalError(
                "已完成的独立 worktree 子任务必须用 deliver 返回 Facilitator；"
                "只有 deliver 会完成当前子任务并允许父任务随后调用 room_integrate，"
                "不要用 handoff 创建无法集成的下一阶段"
            )
        requirement_coverage = list(
            canonical_gate.requirement_coverage
        )
        review_evidence_binding: dict[str, object] | None = None
        if is_review_task:
            binding_material = {
                "reviewTargetRevision": str(task["reviewTargetRevision"]),
                "taskId": str(task["taskId"]),
                "dispatchId": str(dispatch["dispatchId"]),
                "evidenceRefs": sorted(evidence_refs),
                "notBeforeMs": review_evidence_not_before_ms,
            }
            review_evidence_binding = {
                "schemaVersion": "wisdom-weasel.review-evidence-binding.v1",
                "bindingId": (
                    "review-evidence-binding:"
                    + _sha256_json(binding_material)
                ),
                **binding_material,
            }
        review_findings = self._canonical_review_findings(
            value=arguments.get("reviewFindings"),
            task=task,
            root=root,
            decision=decision,
            acceptance_aliases=alias_map,
            evidence_refs=evidence_refs,
            runtime_evidence_refs=runtime_evidence_refs,
        )
        review_finding_responses = (
            self._canonical_review_finding_responses(
                value=arguments.get("reviewFindingResponses"),
                task=task,
                dispatch=dispatch,
                evidence_refs=evidence_refs,
                runtime_evidence_refs=runtime_evidence_refs,
                now_ms=now_ms,
            )
        )
        self._assert_review_evidence_ready(
            decision=decision,
            root=root,
            task=task,
            dispatch=dispatch,
            evidence_refs=evidence_refs,
        )
        commit_id = _stable_id(
            "room-commit",
            str(invocation["receiptId"]),
        )
        question_options = _canonical_question_options(
            arguments.get("questionOptions"),
            decision=decision,
            waiting_for=str(arguments.get("waitingFor") or "").strip(),
            question=arguments.get("question"),
            question_kind=arguments.get("questionKind"),
        )
        try:
            public_content = public_room_report_content(
                arguments.get("publicSummary"),
                field_name="publicSummary",
            )
        except ValueError as exc:
            raise RoomCommitProposalError(str(exc)) from exc
        try:
            assert_public_room_report_claims(
                public_content,
                field_name="publicSummary",
                decision=decision,
                all_criteria_verified=(
                    quality_gate_receipt.get("verdict") == "ready_to_deliver"
                ),
            )
        except ValueError as exc:
            raise RoomCommitProposalError(str(exc)) from exc
        post_id = _stable_id("room-post", commit_id)
        post_kind = {
            "deliver": "result",
            "handoff": "handoff",
            "wait": "wait",
            "blocked": "blocked",
        }[decision]
        if (
            str(dispatch.get("intentKind") or "") == "align"
            and decision == "deliver"
        ):
            post_kind = "alignment"
        elif (
            decision == "deliver"
            and not task.get("parentTaskId")
            and not is_report_dispatch
        ):
            # Root execution/resume lanes may publish an integration result,
            # but only ReportDispatch owns the one final `result` post.
            post_kind = "work_result"
        elif decision == "deliver" and task.get("parentTaskId"):
            post_kind = (
                "review_result"
                if task.get("taskKind") == "review"
                else "work_result"
            )
        post_proposal: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-post.v2",
            "postId": post_id,
            "roomId": root["roomId"],
            "rootId": root["rootId"],
            "generation": root["generation"],
            "taskId": dispatch["taskId"],
            "dispatchId": dispatch["dispatchId"],
            "authorActorRef": dispatch["targetParticipantId"],
            "kind": post_kind,
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
        if (
            decision == "wait"
            and str(arguments.get("waitingFor") or "").strip() == "user"
            and isinstance(arguments.get("question"), str)
            and str(arguments.get("question") or "").strip()
        ):
            post_proposal["question"] = {
                "prompt": _required_text(arguments, "question"),
                # An explicitly unbounded Room question keeps an empty options
                # array so the public wire shape remains stable.
                "options": [
                    dict(option) for option in (question_options or [])
                ],
            }


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
                intent = _required_text(arguments, "intent")
                built = self.continuations.build(
                    parent_dispatch=dispatch,
                    parent_task=task,
                    room_id=str(root["roomId"]),
                    target_participant_id=target_participant_id,
                    trigger_id=commit_id,
                    intent_kind=intent,
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
                    now_ms=now_ms,
                )
                post_proposal["mentions"] = [target_participant_id]
                if intent == "review":
                    built["childTask"] = (
                        self.application.prepare_review_handoff_task(
                            parent_dispatch=dispatch,
                            parent_task=task,
                            target_participant_id=target_participant_id,
                            evidence_refs=built["childTask"][
                                "contextEvidenceRefs"
                            ],
                            child_task=built["childTask"],
                            pending_parent_task={
                                **self.kernel.project_task_result_payload(
                                    task,
                                    result_kind="dispatch",
                                    post_proposal=post_proposal,
                                    quality_gate_receipt=(
                                        quality_gate_receipt
                                    ),
                                    evidence_refs=evidence_refs,
                                    now_ms=now_ms,
                                ),
                                "state": "waiting",
                            },
                            parent_commit_id=commit_id,
                            now_ms=now_ms,
                        )
                    )
                    built.update(
                        {
                            "waitingFor": "participant",
                            "waitingForParticipantId": target_participant_id,
                            "waitingForDispatchId": built["childDispatch"][
                                "dispatchId"
                            ],
                            "resumeCondition": (
                                "独立 Reviewer 已公开复核结论并提交验收证据"
                            ),
                        }
                    )
                elif (
                    intent == "revise"
                    and str(task.get("taskKind") or "") == "review"
                ):
                    built["childTask"] = (
                        self.application.prepare_revision_handoff_task(
                            parent_dispatch=dispatch,
                            parent_task=task,
                            target_participant_id=target_participant_id,
                            child_task=built["childTask"],
                            review_findings=review_findings,
                        )
                    )
                    built.update(
                        {
                            "waitingFor": "participant",
                            "waitingForParticipantId": target_participant_id,
                            "waitingForDispatchId": built["childDispatch"][
                                "dispatchId"
                            ],
                            "resumeCondition": (
                                "Facilitator 已按复核证据完成修正并公开新的验证结果"
                            ),
                        }
                    )
                continuation.update(built)
            except (
                AcceptanceAliasError,
                ParticipantReferenceError,
                RoomContinuationProposalError,
                RoomKernelFenceError,
            ) as exc:
                raise RoomCommitProposalError(str(exc)) from exc
        elif decision == "wait":
            waiting_for = _required_text(arguments, "waitingFor")
            continuation.update(
                {
                    "waitingFor": waiting_for,
                    "resumeCondition": _required_text(
                        arguments,
                        "resumeCondition",
                    ),
                }
            )
            question = str(arguments.get("question") or "").strip()
            if question:
                continuation["question"] = question
                if waiting_for == "user" and question_options:
                    continuation["questionOptions"] = [
                        dict(option) for option in question_options
                    ]
            if waiting_for == "participant":
                room = self.rooms.get(str(root["roomId"]))
                participant_refs = participant_ref_map(
                    room["participants"]
                )
                try:
                    waiting_participant_id = resolve_participant_ref(
                        arguments.get("waitingForParticipantRef"),
                        participant_refs,
                    )
                    if (
                        waiting_participant_id
                        == dispatch["targetParticipantId"]
                    ):
                        raise RoomCommitProposalError(
                            "wait target must differ from the current participant"
                        )
                    waiting_dispatch = (
                        self.kernel.wait_target_dispatch(
                            root_id=str(root["rootId"]),
                            participant_id=waiting_participant_id,
                            generation=int(root["generation"]),
                            exclude_dispatch_id=str(
                                dispatch["dispatchId"]
                            ),
                        )
                    )
                except (
                    ParticipantReferenceError,
                    RoomKernelFenceError,
                ) as exc:
                    raise RoomCommitProposalError(str(exc)) from exc
                continuation.update(
                    {
                        "waitingForParticipantId": (
                            waiting_participant_id
                        ),
                        "waitingForDispatchId": waiting_dispatch[
                            "dispatchId"
                        ],
                    }
                )
                post_proposal["mentions"] = [waiting_participant_id]
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
            "reviewFindings": review_findings,
            "reviewFindingResponses": review_finding_responses,
            "reviewEvidenceBinding": review_evidence_binding,
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
            "reviewFindings": review_findings,
            "reviewFindingResponses": review_finding_responses,
            "createdAtMs": now_ms,
        }
        if review_evidence_binding is not None:
            commit["reviewEvidenceBinding"] = review_evidence_binding
        return commit


def _review_scope_key(value: object) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    criterion_id = str(value.get("criterionId") or "").strip()
    if criterion_id:
        return ("criterion", criterion_id)
    invariant_id = str(value.get("invariantId") or "").strip()
    if invariant_id:
        return ("invariant", invariant_id)
    return None


def _re_review_exception_category(value: object) -> bool:
    normalized = (
        "_".join(str(value or "").strip().casefold().replace("-", "_").split())
    )
    return normalized in _RE_REVIEW_BLOCKING_EXCEPTION_CATEGORIES


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


def _canonical_question_options(
    value: object,
    *,
    decision: str,
    waiting_for: str,
    question: object,
    question_kind: object,
    require_bounded: bool = False,
) -> list[dict[str, object]] | None:
    normalized_question = (
        question.strip() if isinstance(question, str) else ""
    )
    if not normalized_question:
        if value is not None:
            raise RoomCommitProposalError(
                "questionOptions requires a non-empty question"
            )
        if question_kind is not None:
            raise RoomCommitProposalError(
                "questionKind requires a non-empty question"
            )
        return None
    if decision != "wait" or waiting_for != "user":
        raise RoomCommitProposalError(
            "question is only valid for wait-for-user"
        )
    if not isinstance(question_kind, str):
        raise RoomCommitProposalError(
            "questionKind must be bounded or unbounded"
        )
    normalized_kind = question_kind.strip()
    if normalized_kind not in {"bounded", "unbounded"}:
        raise RoomCommitProposalError(
            "questionKind must be bounded or unbounded"
        )
    if require_bounded and normalized_kind != "bounded":
        raise RoomCommitProposalError(
            "alignment questions must be bounded and include between 2 and 5 "
            "questionOptions; the interface supplies Other for custom text"
        )
    if normalized_kind == "unbounded":
        if value is not None:
            raise RoomCommitProposalError(
                "unbounded questions must omit questionOptions"
            )
        return None
    if value is None:
        raise RoomCommitProposalError(
            "bounded questions require between 2 and 5 questionOptions"
        )
    if not isinstance(value, list):
        raise RoomCommitProposalError("questionOptions must be an array")
    if len(value) not in {2, 3, 4, 5}:
        raise RoomCommitProposalError(
            "questionOptions must contain between 2 and 5 options"
        )

    allowed = frozenset(
        {"value", "label", "description", "recommended"}
    )
    normalized: list[dict[str, object]] = []
    seen_values: set[str] = set()
    recommended_count = 0
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise RoomCommitProposalError(
                f"questionOptions[{index}] must be an object"
            )
        unsupported = set(item) - allowed
        if unsupported:
            raise RoomCommitProposalError(
                f"questionOptions[{index}] contains unsupported fields"
            )
        raw_value = item.get("value")
        raw_label = item.get("label")
        if not isinstance(raw_value, str):
            raise RoomCommitProposalError(
                f"questionOptions[{index}].value must be a string"
            )
        if not isinstance(raw_label, str):
            raise RoomCommitProposalError(
                f"questionOptions[{index}].label must be a string"
            )
        option_value = " ".join(raw_value.split())
        label = " ".join(raw_label.split())
        if not option_value or len(option_value) > 80:
            raise RoomCommitProposalError(
                f"questionOptions[{index}].value must contain 1-80 characters"
            )
        if not label or len(label) > 120:
            raise RoomCommitProposalError(
                f"questionOptions[{index}].label must contain 1-120 characters"
            )
        if option_value in seen_values:
            raise RoomCommitProposalError(
                "questionOptions values must be unique after normalization"
            )
        seen_values.add(option_value)
        raw_description = item.get("description")
        if not isinstance(raw_description, str):
            raise RoomCommitProposalError(
                f"questionOptions[{index}].description must be a string"
            )
        description = " ".join(raw_description.split())
        if not description or len(description) > 500:
            raise RoomCommitProposalError(
                f"questionOptions[{index}].description must contain "
                "1-500 characters"
            )
        if description == label:
            raise RoomCommitProposalError(
                f"questionOptions[{index}].description must explain the "
                "choice instead of repeating its label"
            )
        option: dict[str, object] = {
            "value": option_value,
            "label": label,
            "description": description,
        }
        if "recommended" in item:
            recommended = item["recommended"]
            if not isinstance(recommended, bool):
                raise RoomCommitProposalError(
                    f"questionOptions[{index}].recommended must be a boolean"
                )
            option["recommended"] = recommended
            if recommended:
                recommended_count += 1
                if recommended_count > 1:
                    raise RoomCommitProposalError(
                        "questionOptions allows at most one recommended option"
                    )
        normalized.append(option)
    return normalized


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
