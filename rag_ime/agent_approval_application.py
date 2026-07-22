from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from .agent_external_approval import ExternalApprovalFinalizer
from .agent_tool_ids import DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
from .external_actions import (
    PORTABLE_RESTORE_ACTION,
    materialize_portable_restore_plan,
)


_RECOVERABLE_GOVERNED_MEMORY_OPERATIONS = frozenset(
    {
        "remember_apply",
        "correct_apply",
        "forget_apply",
        "governance_rollback",
    }
)


class ApprovalHost(Protocol):
    sessions: Any
    runtime: Any
    events: Any
    memory_sources: Any
    _approval_executor: Any
    _process_id_provider: Any

    def _record_tool_receipt_evidence_safely(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]: ...

    def record_room_product_tool_execution(
        self,
        session_id: str,
        invocation_receipt_id: str,
        *,
        status: str,
        result_hash: str,
    ) -> dict[str, object]: ...


class AgentApprovalApplicationService:
    """Own approval decisions, execution receipts, and external finalization."""

    def __init__(self, host: ApprovalHost) -> None:
        self.host = host
        self.external = ExternalApprovalFinalizer(host)

    def list_approvals(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        return {
            "schemaVersion": "rag-ime.agent-approval-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": self.host.sessions.list_approvals(
                session_id=session_id,
                state=str(payload.get("state") or "").strip(),
                limit=_integer(
                    payload.get("limit"),
                    default=100,
                    minimum=1,
                    maximum=500,
                ),
            ),
        }

    def resolve_review(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        run_id = _required_text(payload, "runId")
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"reviewed", "deferred"}:
            raise ValueError("decision must be reviewed or deferred")
        if not self.host.runtime.has_pending_review(session_id, run_id):
            raise ValueError("review is no longer active in Pi")
        self.host.runtime.resolve_review(
            session_id,
            run_id,
            reviewed=decision == "reviewed",
        )
        return {
            "schemaVersion": "rag-ime.agent-review-decision.v1",
            "ok": True,
            "sessionId": session_id,
            "runId": run_id,
            "decision": decision,
            "runtimeNotified": True,
        }

    def decide_approval(
        self,
        approval_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        current = self.host.sessions.get_approval(approval_id)
        session_id = str(current["sessionId"])
        approved = decision == "approve"
        pending_in_pi = self.host.runtime.has_pending_approval(
            session_id,
            approval_id,
        )
        current_state = str(current.get("state") or "")
        if (
            current_state == "approved"
            and approved
            and current.get("toolId") == "ime_memory"
            and current.get("operation")
            in _RECOVERABLE_GOVERNED_MEMORY_OPERATIONS
        ):
            self._require_current_payload(current, payload)
            executor = self.host._approval_executor
            if executor is None:
                raise ValueError("approval executor is unavailable")
            try:
                receipt = dict(executor(current))
            except Exception as exc:
                receipt = _failed_receipt(
                    current,
                    summary="操作恢复未完成",
                    reason="recovery_failed",
                    error=exc,
                )
            final = self.host.sessions.complete_approval(
                approval_id,
                state=(
                    "applied"
                    if receipt.get("mutationApplied") is True
                    else "failed"
                ),
                receipt=receipt,
            )
            return self.finish_decision(
                final,
                pending_in_pi=pending_in_pi,
            )
        if current_state != "pending":
            return self.finish_terminal(
                current,
                pending_in_pi=pending_in_pi,
            )
        if approved and not pending_in_pi:
            raise ValueError("approval is no longer active in Pi")
        payload_sha256 = _required_text(payload, "payloadSha256")
        if payload_sha256 != str(current.get("payloadSha256") or ""):
            try:
                self.host.sessions.decide_approval(
                    approval_id,
                    approved=approved,
                    payload_sha256=payload_sha256,
                    decided_by="native-control-center",
                )
            except ValueError:
                terminal = self.host.sessions.get_approval(approval_id)
                if terminal.get("state") not in {"expired", "stale"}:
                    raise
                return self.finish_terminal(
                    terminal,
                    pending_in_pi=pending_in_pi,
                )
        if approved and self.host._approval_executor is None:
            raise ValueError("approval executor is unavailable")
        try:
            decided = self.host.sessions.decide_approval(
                approval_id,
                approved=approved,
                payload_sha256=payload_sha256,
                decided_by="native-control-center",
            )
        except ValueError:
            terminal = self.host.sessions.get_approval(approval_id)
            if terminal.get("state") not in {"expired", "stale"}:
                raise
            return self.finish_terminal(
                terminal,
                pending_in_pi=pending_in_pi,
            )
        final = (
            self.execute_approved(decided)
            if approved
            else decided
        )
        return self.finish_decision(
            final,
            pending_in_pi=pending_in_pi,
        )

    def finish_decision(
        self,
        approval: Mapping[str, object],
        *,
        pending_in_pi: bool,
    ) -> dict[str, object]:
        final = dict(approval)
        approval_id = str(final.get("approvalId") or "")
        session_id = str(final.get("sessionId") or "")
        runtime_notified = False
        runtime_warning = self._seal_room_terminal_approval(final)
        memory_checkpoint = self.checkpoint_applied(final)
        memory_evidence: dict[str, object] = {}
        if final.get("state") == "applied":
            memory_evidence = (
                self.host._record_tool_receipt_evidence_safely(final)
            )
        if pending_in_pi:
            resolution_state = str(
                final.get("state") or "rejected"
            )
            try:
                self.host.runtime.resolve_approval(
                    session_id,
                    approval_id,
                    approved=resolution_state
                    in {"applied", "external_pending"},
                    resolution_state=resolution_state,
                )
                runtime_notified = True
            except Exception:
                runtime_warning = _append_warning(
                    runtime_warning,
                    "Pi 会话未收到审批结果，请刷新该对话",
                )
        else:
            self.host.events.publish(
                session_id,
                "approval_resolved",
                {
                    "approvalId": approval_id,
                    "state": str(
                        final.get("state") or "rejected"
                    ),
                },
            )
        return {
            "schemaVersion": "rag-ime.agent-approval-decision.v1",
            "ok": True,
            "approval": final,
            "runtimeNotified": runtime_notified,
            "runtimeWarning": runtime_warning,
            "memoryCheckpoint": memory_checkpoint,
            "memoryEvidence": memory_evidence,
        }

    def auto_approve_pending(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        approval_id = str(approval.get("approvalId") or "")
        current = self.host.sessions.get_approval(approval_id)
        session_id = str(current.get("sessionId") or "")
        session = self.host.sessions.get(session_id)
        if (
            session.get("toolProfileVersion")
            != DANGEROUS_AUTO_APPROVE_TOOL_PROFILE
        ):
            raise ValueError(
                "automatic approval is not enabled for this session"
            )
        if current.get("state") != "pending":
            raise ValueError("automatic approval is no longer pending")
        if str(approval.get("payloadSha256") or "") != str(
            current.get("payloadSha256") or ""
        ):
            raise ValueError(
                "automatic approval payload no longer matches its preview"
            )
        if self.host._approval_executor is None:
            raise ValueError("approval executor is unavailable")
        decided = self.host.sessions.decide_approval(
            approval_id,
            approved=True,
            payload_sha256=str(current["payloadSha256"]),
            decided_by="dangerous-auto-approve",
        )
        final = self.execute_approved(decided)
        memory_checkpoint = self.checkpoint_applied(final)
        self.host.events.publish(
            session_id,
            "approval_resolved",
            {
                "approvalId": approval_id,
                "state": str(final.get("state") or "failed"),
                "automatic": True,
            },
        )
        receipt = (
            final.get("receipt")
            if isinstance(final.get("receipt"), Mapping)
            else {}
        )
        return {
            "summary": str(
                receipt.get("summary")
                or "自动批准的操作未返回摘要"
            ),
            "approvalRequired": False,
            "autoApproved": True,
            "approvalId": approval_id,
            "approval": final,
            "receipt": dict(receipt),
            "memoryCheckpoint": memory_checkpoint,
        }

    def execute_approved(
        self,
        decided: Mapping[str, object],
    ) -> dict[str, object]:
        approval_id = str(decided.get("approvalId") or "")
        session_id = str(decided.get("sessionId") or "")
        try:
            executor = self.host._approval_executor
            assert executor is not None
            receipt = dict(executor(decided))
        except Exception as exc:
            receipt = _failed_receipt(
                decided,
                summary="操作未执行",
                reason="execution_failed",
                error=exc,
            )
        external_action_pending = (
            receipt.get("externalActionPending") is True
        )
        if external_action_pending:
            origin_process_id = int(self.host._process_id_provider())
            receipt["originProcessId"] = origin_process_id
            if receipt.get("externalAction") == PORTABLE_RESTORE_ACTION:
                try:
                    receipt = materialize_portable_restore_plan(
                        approval=decided,
                        session=self.host.sessions.get(session_id),
                        pending_receipt=receipt,
                        origin_process_id=origin_process_id,
                    )
                except Exception as exc:
                    receipt = _failed_receipt(
                        decided,
                        summary=(
                            "外部恢复计划未创建，数据库没有发生变化"
                        ),
                        reason="external_plan_failed",
                        error=exc,
                    )
                    receipt["externalActionPending"] = False
                    external_action_pending = False
        return self.host.sessions.complete_approval(
            approval_id,
            state=(
                "external_pending"
                if external_action_pending
                else "applied"
                if receipt.get("mutationApplied") is True
                else "failed"
            ),
            receipt=receipt,
        )

    def checkpoint_applied(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        if approval.get("state") != "applied":
            return {}
        session_id = str(approval.get("sessionId") or "")
        try:
            checkpoint = self.host.memory_sources.checkpoint_tool_receipt(
                approval
            )
        except Exception as exc:
            checkpoint = {
                "schemaVersion": "rag-ime.agent-memory-checkpoint.v1",
                "ok": False,
                "stored": False,
                "status": "checkpoint_failed",
                "error": _public_error(exc),
            }
        if checkpoint.get("stored") is True:
            self.host.events.publish(
                session_id,
                "memory_checkpointed",
                {
                    "sourceRole": "tool_receipt",
                    "status": "checkpointed",
                    "summary": (
                        "已应用工具回执已保存为记忆来源，等待异步整理"
                    ),
                },
            )
        return dict(checkpoint)

    def finish_terminal(
        self,
        approval: Mapping[str, object],
        *,
        pending_in_pi: bool,
    ) -> dict[str, object]:
        approval_id = str(approval.get("approvalId") or "")
        session_id = str(approval.get("sessionId") or "")
        state = str(approval.get("state") or "stale")
        runtime_notified = False
        runtime_warning = self._seal_room_terminal_approval(approval)
        if pending_in_pi:
            try:
                self.host.runtime.resolve_approval(
                    session_id,
                    approval_id,
                    approved=False,
                    resolution_state=state,
                )
                runtime_notified = True
            except Exception:
                runtime_warning = _append_warning(
                    runtime_warning,
                    "Pi 会话未收到审批终态，请刷新该对话",
                )
        else:
            self.host.events.publish(
                session_id,
                "approval_resolved",
                {"approvalId": approval_id, "state": state},
            )
        return {
            "schemaVersion": "rag-ime.agent-approval-decision.v1",
            "ok": True,
            "approval": dict(approval),
            "runtimeNotified": runtime_notified,
            "runtimeWarning": runtime_warning,
            "memoryCheckpoint": {},
        }

    def finalize_external(
        self,
        approval_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self.external.finalize(approval_id, payload)

    def approval_result(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = _required_text(payload, "sessionId")
        approval_id = _required_text(payload, "approvalId")
        approval = self.host.sessions.get_approval(approval_id)
        if approval.get("sessionId") != session_id:
            raise ValueError(
                "approval does not belong to this session"
            )
        return {
            "schemaVersion": "rag-ime.agent-approval-result.v1",
            "ok": True,
            "approval": approval,
        }

    @staticmethod
    def _require_current_payload(
        approval: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> None:
        if _required_text(payload, "payloadSha256") != str(
            approval.get("payloadSha256") or ""
        ):
            raise ValueError("approval payload is stale")

    def _seal_room_terminal_approval(
        self,
        approval: Mapping[str, object],
    ) -> str:
        invocation_receipt_id = _room_invocation_receipt_id(approval)
        state = str(approval.get("state") or "")
        if not invocation_receipt_id or state not in {
            "rejected",
            "expired",
            "stale",
        }:
            return ""
        status = "rejected" if state == "rejected" else "cancelled"
        identity = {
            "approvalId": str(approval.get("approvalId") or ""),
            "invocationReceiptId": invocation_receipt_id,
            "state": state,
        }
        result_hash = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        try:
            self.host.record_room_product_tool_execution(
                str(approval.get("sessionId") or ""),
                invocation_receipt_id,
                status=status,
                result_hash=result_hash,
            )
        except Exception as exc:
            return (
                "Room 工具审批终态未写入，请停止或刷新 Room："
                + _public_error(exc)
            )
        return ""

def _failed_receipt(
    approval: Mapping[str, object],
    *,
    summary: str,
    reason: str,
    error: BaseException,
) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-operation-receipt.v1",
        "mutationApplied": False,
        "approvalId": str(approval.get("approvalId") or ""),
        "toolId": str(approval.get("toolId") or ""),
        "operation": str(approval.get("operation") or ""),
        "summary": summary,
        "reason": reason,
        "error": _public_error(error),
    }


def _room_invocation_receipt_id(
    approval: Mapping[str, object],
) -> str:
    preview = approval.get("preview")
    if not isinstance(preview, Mapping):
        return ""
    base_state = preview.get("baseState")
    if not isinstance(base_state, Mapping):
        return ""
    return " ".join(
        str(base_state.get("roomInvocationReceiptId") or "").split()
    )[:240]


def _append_warning(current: str, addition: str) -> str:
    return "；".join(value for value in (current, addition) if value)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = " ".join(str(payload.get(key) or "").split())
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _public_error(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


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
