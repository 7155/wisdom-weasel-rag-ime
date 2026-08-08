from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from .external_actions import (
    PORTABLE_RESTORE_ACTION,
    load_external_action_result,
)


class ExternalApprovalHost(Protocol):
    sessions: Any
    events: Any
    memory_sources: Any
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


class ExternalApprovalFinalizer:
    """Verify supervisor receipts and close external approval operations."""

    def __init__(self, host: ExternalApprovalHost) -> None:
        self.host = host

    def finalize(
        self,
        approval_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        current = self.host.sessions.get_approval(approval_id)
        if current.get("state") != "external_pending":
            raise ValueError(
                "approval is not waiting for an external supervisor"
            )
        if _required_text(payload, "payloadSha256") != str(
            current.get("payloadSha256") or ""
        ):
            raise ValueError("external approval payload is stale")
        action = self._validate_action(current, payload)
        pending_receipt = current.get("receipt")
        if not isinstance(pending_receipt, Mapping):
            raise ValueError(
                "external approval receipt is missing its pending marker"
            )
        command = self._validate_command(
            pending_receipt,
            payload,
            action=action,
        )
        del command
        succeeded = _bool(payload.get("succeeded"))
        timed_out = _bool(payload.get("timedOut"))
        exit_code = _signed_integer(
            payload.get("exitCode"),
            default=-1,
        )
        origin_process_id = _integer(
            pending_receipt.get("originProcessId"),
            default=0,
            minimum=0,
            maximum=2_147_483_647,
        )
        current_process_id = int(self.host._process_id_provider())
        restore_result = self._restore_result(
            pending_receipt,
            action=action,
            succeeded=succeeded,
        )
        if succeeded:
            self._validate_success(
                action=action,
                timed_out=timed_out,
                exit_code=exit_code,
                origin_process_id=origin_process_id,
                current_process_id=current_process_id,
                restore_result=restore_result,
            )
        final_receipt = _final_receipt(
            pending_receipt=pending_receipt,
            payload=payload,
            action=action,
            succeeded=succeeded,
            timed_out=timed_out,
            exit_code=exit_code,
            current_process_id=current_process_id,
            restore_result=restore_result,
        )
        final = self.host.sessions.finalize_external_approval(
            approval_id,
            state="applied" if succeeded else "failed",
            receipt=final_receipt,
        )
        runtime_warning = self._seal_room_external_execution(
            final,
            result_hash=_sha256_json(final_receipt),
        )
        memory_checkpoint: dict[str, object] = {}
        memory_evidence: dict[str, object] = {}
        if succeeded:
            try:
                memory_checkpoint = (
                    self.host.memory_sources.checkpoint_tool_receipt(
                        final
                    )
                )
            except Exception as exc:
                memory_checkpoint = {
                    "schemaVersion": (
                        "rag-ime.agent-memory-checkpoint.v1"
                    ),
                    "ok": False,
                    "stored": False,
                    "status": "checkpoint_failed",
                    "error": _public_error(exc),
                }
            memory_evidence = (
                self.host._record_tool_receipt_evidence_safely(final)
            )
        self.host.events.publish(
            str(final.get("sessionId") or ""),
            "approval_resolved",
            {
                "approvalId": approval_id,
                "state": str(final.get("state") or "failed"),
                "externalFinalized": True,
                "summary": str(
                    final_receipt.get("summary") or ""
                ),
                **_approval_event_identity(final),
            },
            turn_id=_approval_turn_id(final),
        )
        return {
            "schemaVersion": "rag-ime.agent-approval-decision.v1",
            "ok": True,
            "approval": final,
            "runtimeNotified": False,
            "runtimeWarning": runtime_warning,
            "memoryCheckpoint": memory_checkpoint,
            "memoryEvidence": memory_evidence,
        }

    def _seal_room_external_execution(
        self,
        approval: Mapping[str, object],
        *,
        result_hash: str,
    ) -> str:
        invocation_receipt_id = _room_invocation_receipt_id(approval)
        if not invocation_receipt_id:
            return ""
        try:
            self.host.record_room_product_tool_execution(
                str(approval.get("sessionId") or ""),
                invocation_receipt_id,
                status=(
                    "applied"
                    if approval.get("state") == "applied"
                    else "failed"
                ),
                result_hash=result_hash,
            )
        except Exception as exc:
            return (
                "Room 外部工具终态未写入，请停止或刷新 Room："
                + _public_error(exc)
            )
        return ""

    @staticmethod
    def _validate_action(
        approval: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> str:
        supported_action = {
            ("runtime", "restart_sidecar"): "restart_sidecar",
            ("configuration", "restore_apply"): (
                PORTABLE_RESTORE_ACTION
            ),
        }.get(
            (
                str(approval.get("toolId") or ""),
                str(approval.get("operation") or ""),
            )
        )
        if supported_action is None:
            raise ValueError("external approval action is not supported")
        pending_receipt = approval.get("receipt")
        if (
            not isinstance(pending_receipt, Mapping)
            or pending_receipt.get("externalActionPending") is not True
        ):
            raise ValueError(
                "external approval receipt is missing its pending marker"
            )
        action = _required_text(payload, "externalAction")
        if (
            action != supported_action
            or action
            != str(pending_receipt.get("externalAction") or "")
        ):
            raise ValueError(
                "external supervisor action does not match the approved receipt"
            )
        return action

    @staticmethod
    def _validate_command(
        pending_receipt: Mapping[str, object],
        payload: Mapping[str, object],
        *,
        action: str,
    ) -> list[str]:
        del action
        command = pending_receipt.get("externalCommand")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) for item in command)
        ):
            raise ValueError(
                "external supervisor command receipt is invalid"
            )
        command_sha256 = _required_text(
            payload,
            "externalCommandSha256",
        )
        if (
            command_sha256
            != str(
                pending_receipt.get("externalCommandSha256") or ""
            )
            or command_sha256 != _sha256_json(command)
        ):
            raise ValueError(
                "external supervisor command receipt is stale"
            )
        return command

    @staticmethod
    def _restore_result(
        pending_receipt: Mapping[str, object],
        *,
        action: str,
        succeeded: bool,
    ) -> dict[str, object]:
        if action != PORTABLE_RESTORE_ACTION:
            return {}
        plan_id = str(
            pending_receipt.get("externalPlanId") or ""
        )
        plan_sha256 = str(
            pending_receipt.get("externalPlanSha256") or ""
        )
        if not plan_id or len(plan_sha256) != 64:
            raise ValueError(
                "external restore receipt is missing its durable plan identity"
            )
        try:
            return load_external_action_result(
                plan_id=plan_id,
                plan_sha256=plan_sha256,
            )
        except Exception:
            if succeeded:
                raise
            return {}

    @staticmethod
    def _validate_success(
        *,
        action: str,
        timed_out: bool,
        exit_code: int,
        origin_process_id: int,
        current_process_id: int,
        restore_result: Mapping[str, object],
    ) -> None:
        if timed_out or exit_code != 0:
            raise ValueError(
                "successful external action requires exitCode 0 without timeout"
            )
        if (
            origin_process_id <= 0
            or current_process_id == origin_process_id
        ):
            raise ValueError(
                "external action must be finalized by the new Sidecar process"
            )
        if action == PORTABLE_RESTORE_ACTION and (
            restore_result.get("ok") is not True
            or restore_result.get("restoreApplied") is not True
            or restore_result.get("restartRequested") is not True
        ):
            raise ValueError(
                "external restore result does not prove a completed restore and restart"
            )


def _final_receipt(
    *,
    pending_receipt: Mapping[str, object],
    payload: Mapping[str, object],
    action: str,
    succeeded: bool,
    timed_out: bool,
    exit_code: int,
    current_process_id: int,
    restore_result: Mapping[str, object],
) -> dict[str, object]:
    restore_applied = restore_result.get("restoreApplied") is True
    mutation_applied = succeeded or restore_applied
    if action == PORTABLE_RESTORE_ACTION:
        success_summary = (
            "便携备份已由原生监督器恢复，并由新 Sidecar 确认"
        )
        failure_summary = (
            "数据库已恢复，但 Sidecar 重启或最终确认没有完成"
            if restore_applied
            else "便携备份恢复没有完成，当前数据库未被确认替换"
        )
    else:
        success_summary = (
            "Sidecar 已由控制中心外部监督器重启，并由新进程确认"
        )
        failure_summary = (
            "Sidecar 外部重启没有完成，未确认运行时变更"
        )
    receipt = dict(pending_receipt)
    receipt.update(
        {
            "mutationApplied": mutation_applied,
            "externalActionPending": False,
            "summary": (
                success_summary if succeeded else failure_summary
            ),
            "status": (
                "succeeded"
                if succeeded
                else "timed_out"
                if timed_out
                else "failed"
            ),
            "exitCode": exit_code,
            "timedOut": timed_out,
            "finalProcessId": current_process_id,
            "undoAvailable": False,
        }
    )
    if action == PORTABLE_RESTORE_ACTION and restore_result:
        receipt.update(
            {
                "databaseCounts": (
                    restore_result.get("databaseCounts")
                    if isinstance(
                        restore_result.get("databaseCounts"),
                        Mapping,
                    )
                    else {}
                ),
                "providerMetadataRestored": [
                    str(value)
                    for value in restore_result.get(
                        "providerMetadataRestored",
                        [],
                    )
                ],
                "rollbackFileName": _bounded_text(
                    restore_result.get("rollbackFileName"),
                    maximum=240,
                ),
                "secretsChanged": (
                    restore_result.get("secretsChanged") is True
                ),
                "restartRequested": (
                    restore_result.get("restartRequested") is True
                ),
            }
        )
    receipt.pop("error", None)
    if not succeeded:
        receipt["reason"] = "external_supervisor_failed"
        receipt["error"] = _bounded_text(
            payload.get("error")
            or restore_result.get("error")
            or "外部监督器未能完成已批准的操作",
            maximum=240,
        )
    return receipt


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


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = " ".join(str(payload.get(key) or "").split())
    if not value:
        raise ValueError(f"{key} must not be empty")
    return value


def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _public_error(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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


def _signed_integer(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
