from __future__ import annotations

from collections.abc import Mapping
import sqlite3
from typing import Any, Protocol

from .agent_execution_policy import APPROVAL_AUTO, APPROVAL_MODEL, approval_strategy
from .agent_external_approval import ExternalApprovalFinalizer
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
    approval_model: Any
    _process_id_provider: Any

    def _record_tool_receipt_evidence_safely(
        self,
        approval: Mapping[str, object],
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
        session_id = str(payload.get("sessionId") or "").strip()
        requested_state = str(payload.get("state") or "").strip()
        requested_limit = _integer(
            payload.get("limit"),
            default=100,
            minimum=1,
            maximum=500,
        )
        recent = self.host.sessions.list_approvals(
            session_id=session_id,
            limit=500,
        )
        self._reconcile_runtime_terminal_approvals(recent)
        items = (
            recent[:requested_limit]
            if not requested_state
            else self.host.sessions.list_approvals(
                session_id=session_id,
                state=requested_state,
                limit=requested_limit,
            )
        )
        return {
            "schemaVersion": "rag-ime.agent-approval-list.v1",
            "ok": True,
            "sessionId": session_id,
            "items": items,
        }

    def _reconcile_runtime_terminal_approvals(
        self,
        approvals: list[Mapping[str, object]],
    ) -> None:
        """Deliver durable approval terminal states to a waiting Pi Tool call."""

        for approval in approvals:
            state = str(approval.get("state") or "")
            if state not in {
                "applied",
                "external_pending",
                "rejected",
                "expired",
                "stale",
                "failed",
            }:
                continue
            session_id = str(approval.get("sessionId") or "")
            approval_id = str(approval.get("approvalId") or "")
            if not self.host.runtime.has_pending_approval(
                session_id,
                approval_id,
            ):
                continue
            if state in {"applied", "external_pending"}:
                self.finish_decision(approval, pending_in_pi=True)
            else:
                self.finish_terminal(approval, pending_in_pi=True)

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
            recovery = self._recover_applied_memory_review(
                session_id,
                run_id,
            )
            if recovery is None:
                raise ValueError("review is no longer active in Pi")
            return {
                "schemaVersion": "rag-ime.agent-review-decision.v1",
                "ok": True,
                "sessionId": session_id,
                "runId": run_id,
                "decision": decision,
                # The exact recovered turn was retired and Pi was confirmed
                # idle. This is terminal runtime recovery, not a normal
                # review.resolve delivery.
                "runtimeNotified": True,
                "recovered": True,
                "recoveryAction": "retire_recovered_turn",
                "recoveryReceipt": recovery,
            }
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

    def _recover_applied_memory_review(
        self,
        session_id: str,
        run_id: str,
    ) -> dict[str, object] | None:
        """Retire one lost review turn only after durable identity checks.

        ``pending_reviews`` is an in-memory Host map. It can disappear when
        the Python process or Host is recreated even though the cleanup run is
        already applied and the durable runtime event still identifies the
        waiting turn. Recovery must never turn a newer turn into an abort, so
        the current Host control state is compared with the exact event turn
        before the existing Runtime retirement protocol is invoked.
        """

        if self._memory_cleanup_run_status(run_id) != "applied":
            return None
        candidate_turn_ids = self._memory_review_turn_ids(
            session_id,
            run_id,
        )
        if not candidate_turn_ids:
            return None
        ensure = getattr(self.host.runtime, "ensure", None)
        retire = getattr(
            self.host.runtime,
            "retire_recovered_turn",
            None,
        )
        if not callable(ensure) or not callable(retire):
            # Older Runtime drivers have no exact-turn retirement contract;
            # refusing here is safer than falling back to a broad abort.
            return None
        ensured = ensure(session_id)
        state = ensured.get("state") if isinstance(ensured, Mapping) else None
        state = state if isinstance(state, Mapping) else {}
        active_turn = state.get("activeTurn")
        active_turn = active_turn if isinstance(active_turn, Mapping) else {}
        active_turn_id = str(active_turn.get("turnId") or "").strip()
        if (
            state.get("isIdle") is not True
            or active_turn_id not in candidate_turn_ids
        ):
            raise ValueError(
                "Pi Runtime active turn does not match the expected recovered turn"
            )
        receipt = retire(session_id, active_turn_id)
        return dict(receipt) if isinstance(receipt, Mapping) else {}

    def _memory_cleanup_run_status(self, run_id: str) -> str:
        """Read only the durable status gate needed for stale review repair."""

        db_path = getattr(self.host.sessions, "db_path", None)
        if db_path is None:
            return ""
        try:
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM memory_cleanup_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
        except sqlite3.Error:
            # Preserve the existing API error if the status store cannot be
            # read; this path must not guess that a review is recoverable.
            return ""
        return str(row[0] or "") if row is not None else ""

    def _memory_review_turn_ids(
        self,
        session_id: str,
        run_id: str,
    ) -> list[str]:
        """Collect live and durable exact turn identities for one review."""

        candidates: list[str] = []
        try:
            replayed, _gap = self.host.events.replay(session_id)
        except Exception:
            replayed = []
        for event in replayed:
            if (
                getattr(event, "event_type", "") != "user_input_required"
                or str(getattr(event, "turn_id", "") or "").strip() == ""
            ):
                continue
            event_payload = getattr(event, "payload", {})
            if not isinstance(event_payload, Mapping):
                continue
            if (
                str(event_payload.get("requestKind") or "")
                != "memory_review"
                or str(event_payload.get("runId") or "") != run_id
            ):
                continue
            candidates.append(str(event.turn_id).strip())

        durable_lookup = getattr(
            self.host.sessions,
            "runtime_review_request_turn_ids",
            None,
        )
        if callable(durable_lookup):
            try:
                durable = durable_lookup(session_id, run_id)
            except Exception:
                durable = []
            if isinstance(durable, (list, tuple)):
                candidates.extend(str(value).strip() for value in durable)

        unique: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

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
            and current.get("toolId") == "memory"
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
        runtime_warning = ""
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
                    **_approval_event_identity(final),
                },
                turn_id=_approval_turn_id(final),
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
        try:
            return self._auto_approve_pending(approval)
        except Exception as exc:
            return self._fail_automatic_approval(approval, exc)

    def _auto_approve_pending(
        self,
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        approval_id = str(approval.get("approvalId") or "")
        current = self.host.sessions.get_approval(approval_id)
        session_id = str(current.get("sessionId") or "")
        session = self.host.sessions.get(session_id)
        strategy = approval_strategy(
            session,
            tool=str(current.get("toolId") or ""),
            operation=str(current.get("operation") or ""),
            preview=(
                current.get("preview")
                if isinstance(current.get("preview"), Mapping)
                else None
            ),
            risk_level=current.get("riskLevel"),
        )
        if current.get("state") != "pending":
            return self._automatic_terminal_result(current)
        if str(approval.get("payloadSha256") or "") != str(
            current.get("payloadSha256") or ""
        ):
            raise ValueError(
                "unattended approval payload no longer matches its preview"
            )

        model_decision: Mapping[str, object] | None = None
        approved = True
        if strategy == APPROVAL_MODEL:
            model_decision = self.host.approval_model.decide(
                current,
                session,
            )
            approved = model_decision.get("decision") == "approve"
            decided_by = (
                "approval-model:"
                + str(model_decision.get("receiptId") or "")
            )
        else:
            decided_by = (
                "execution-policy:"
                + str(session.get("executionMode") or "per_action")
            )

        if approved and self.host._approval_executor is None:
            raise ValueError("approval executor is unavailable")
        try:
            decided = self.host.sessions.decide_approval(
                approval_id,
                approved=approved,
                payload_sha256=str(current["payloadSha256"]),
                decided_by=decided_by,
            )
        except ValueError:
            terminal = self.host.sessions.get_approval(approval_id)
            if terminal.get("state") not in {"expired", "stale"}:
                raise
            decision_result = self.finish_terminal(
                terminal,
                pending_in_pi=self.host.runtime.has_pending_approval(
                    session_id,
                    approval_id,
                ),
            )
            result = self._automatic_terminal_result(terminal)
            result["runtimeNotified"] = bool(
                decision_result.get("runtimeNotified")
            )
            result["runtimeWarning"] = str(
                decision_result.get("runtimeWarning") or ""
            )
            if model_decision is not None:
                result["decisionMode"] = "model"
                result["modelDecided"] = True
                result["approvalModelDecision"] = dict(model_decision)
            return result
        final = self.execute_approved(decided) if approved else dict(decided)
        memory_checkpoint = (
            self.checkpoint_applied(final)
            if approved
            else {}
        )
        event_payload: dict[str, object] = {
            "approvalId": approval_id,
            "state": str(final.get("state") or "failed"),
            "automatic": True,
            "decisionMode": (
                "model"
                if model_decision is not None
                else "policy"
            ),
        }
        event_payload.update(_approval_event_identity(final))
        if model_decision is not None:
            event_payload["approvalModelDecision"] = dict(model_decision)
        self.host.events.publish(
            session_id,
            "approval_resolved",
            event_payload,
            turn_id=_approval_turn_id(final),
        )
        receipt = (
            final.get("receipt")
            if isinstance(final.get("receipt"), Mapping)
            else {}
        )
        summary = str(
            receipt.get("summary")
            or (
                model_decision.get("rationaleSummary")
                if model_decision is not None
                else ""
            )
            or (
                "Luna Max 已拒绝这次操作"
                if model_decision is not None and not approved
                else "自动批准的操作未返回摘要"
            )
        )
        result: dict[str, object] = {
            "summary": summary,
            "approvalRequired": False,
            "autoApproved": approved,
            "approvalId": approval_id,
            "approval": final,
            "receipt": dict(receipt),
            "memoryCheckpoint": memory_checkpoint,
            "decisionMode": (
                "model"
                if model_decision is not None
                else "policy"
            ),
        }
        if model_decision is not None:
            result["modelDecided"] = True
            result["approvalModelDecision"] = dict(model_decision)
            if model_decision.get("status") == "failed_closed":
                result["failureCode"] = str(
                    model_decision.get("failureCode") or ""
                )
        result["terminal"] = True
        result["retryable"] = False
        result["terminalReason"] = summary
        return result

    def _fail_automatic_approval(
        self,
        approval: Mapping[str, object],
        error: Exception,
    ) -> dict[str, object]:
        """Close an unattended approval when its bridge fails.

        The Pi Tool call is synchronous, so an exception between preview
        creation and the automatic decision otherwise leaves a durable
        ``pending`` approval with no human owner.  That orphan is projected as
        an endlessly running Room activity.  Convert the exact approval to a
        terminal state and return an ordinary terminal Tool result instead.
        """

        approval_id = str(approval.get("approvalId") or "")
        current = self.host.sessions.get_approval(approval_id)
        state = str(current.get("state") or "")
        if state == "pending":
            try:
                current = self.host.sessions.decide_approval(
                    approval_id,
                    approved=False,
                    payload_sha256=str(current.get("payloadSha256") or ""),
                    decided_by="automatic-approval-bridge",
                )
            except ValueError:
                current = self.host.sessions.get_approval(approval_id)
        elif state == "approved":
            receipt = _failed_receipt(
                current,
                summary="自动审批执行失败，原操作没有执行",
                reason="automatic_approval_bridge_failed",
                error=error,
            )
            try:
                current = self.host.sessions.complete_approval(
                    approval_id,
                    state="failed",
                    receipt=receipt,
                )
            except ValueError:
                current = self.host.sessions.get_approval(approval_id)

        terminal_state = str(current.get("state") or "failed")
        summary = "自动审批执行失败，原操作没有执行"
        event_payload: dict[str, object] = {
            "approvalId": approval_id,
            "state": terminal_state,
            "automatic": True,
            "decisionMode": "policy",
            "error": _public_error(error),
            **_approval_event_identity(current),
        }
        self.host.events.publish(
            str(current.get("sessionId") or approval.get("sessionId") or ""),
            "approval_resolved",
            event_payload,
            turn_id=_approval_turn_id(current),
        )
        return {
            "summary": summary,
            "approvalRequired": False,
            "autoApproved": False,
            "approvalId": approval_id,
            "approval": dict(current),
            "receipt": {},
            "memoryCheckpoint": {},
            "decisionMode": "policy",
            "terminal": True,
            "retryable": False,
            "terminalReason": summary,
            "failureCode": "automatic_approval_bridge_failed",
        }

    @staticmethod
    def _automatic_terminal_result(
        approval: Mapping[str, object],
    ) -> dict[str, object]:
        state = str(approval.get("state") or "stale")
        receipt = (
            approval.get("receipt")
            if isinstance(approval.get("receipt"), Mapping)
            else {}
        )
        summary = str(receipt.get("summary") or "").strip()
        if not summary:
            summary = {
                "rejected": "这次操作已被审批终止，未执行。",
                "stale": "这次审批已取消，未执行。",
                "expired": "这次审批已过期，未执行。",
                "failed": "这次操作已失败，未执行。",
                "applied": "这次操作已完成。",
                "external_pending": "这次操作已批准，等待外部监督器完成。",
            }.get(state, "这次审批已结束，未执行。")
        model_owned = str(approval.get("decidedBy") or "").startswith(
            "approval-model:"
        )
        result: dict[str, object] = {
            "summary": summary,
            "approvalRequired": False,
            "autoApproved": state in {"applied", "external_pending"},
            "approvalId": str(approval.get("approvalId") or ""),
            "approval": dict(approval),
            "receipt": dict(receipt),
            "decisionMode": "model" if model_owned else "policy",
            "terminal": state not in {"pending", "approved"},
            "retryable": False,
            "terminalReason": summary,
        }
        if model_owned:
            result["modelDecided"] = True
        return result

    def cancel_pending_for_session(
        self,
        session_id: str,
        *,
        reason: str = "user_abort",
        turn_id: str = "",
    ) -> dict[str, object]:
        summary = self.host.sessions.cancel_pending_approvals(
            session_id,
            reason=reason,
            turn_id=turn_id,
        )
        cancelled_ids = [
            str(value)
            for value in summary.get("cancelledApprovalIds") or []
            if str(value).strip()
        ]
        for approval_id in cancelled_ids:
            final = self.host.sessions.get_approval(approval_id)
            self.host.events.publish(
                session_id,
                "approval_resolved",
                {
                    "approvalId": approval_id,
                    "state": str(final.get("state") or "stale"),
                    "cancelled": True,
                    "reason": reason,
                    **_approval_event_identity(final),
                },
                turn_id=_approval_turn_id(final) or str(turn_id or ""),
            )
        return {
            **dict(summary),
            "cancelledApprovalCount": len(cancelled_ids),
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
        runtime_warning = ""
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
                {
                    "approvalId": approval_id,
                    "state": state,
                    **_approval_event_identity(approval),
                },
                turn_id=_approval_turn_id(approval),
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

def _approval_event_identity(
    approval: Mapping[str, object],
) -> dict[str, object]:
    tool_call_id = str(approval.get("toolCallId") or "").strip()
    return {"toolCallId": tool_call_id} if tool_call_id else {}


def _approval_turn_id(approval: Mapping[str, object]) -> str:
    causal = approval.get("causalMetadata")
    if not isinstance(causal, Mapping):
        return ""
    return str(causal.get("turnId") or "").strip()


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
