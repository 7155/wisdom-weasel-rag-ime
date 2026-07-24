from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from .agent_room_kernel_contracts import (
    ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
    validate_kernel_contract,
)


class RoomQualityGateError(ValueError):
    """A quality proposal cannot become an authoritative Kernel receipt."""


def canonicalize_quality_gate(
    *,
    proposal: object,
    decision: str,
    root_id: str,
    task_id: str,
    dispatch_id: str,
    generation: int,
    task_criteria: Sequence[str],
    evidence_refs: Sequence[str],
    requirement_coverage: Sequence[str],
    invocation_receipt_id: str,
    now_ms: int,
) -> dict[str, object]:
    if not isinstance(proposal, Mapping):
        raise RoomQualityGateError(
            "room_commit requires a structured qualityGate"
        )
    if proposal.get("originalRequestChecked") is not True:
        raise RoomQualityGateError(
            "qualityGate.originalRequestChecked must be true"
        )
    verdict = str(proposal.get("verdict") or "").strip()
    if verdict not in {"ready_to_deliver", "not_ready"}:
        raise RoomQualityGateError("qualityGate.verdict is invalid")
    raw_items = proposal.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > 64:
        raise RoomQualityGateError(
            "qualityGate.items must be an array with at most 64 items"
        )

    canonical_criteria = [str(item) for item in task_criteria if str(item)]
    allowed_criteria = set(canonical_criteria)
    aggregate_evidence = set(evidence_refs)
    seen: set[str] = set()
    items: list[dict[str, object]] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            raise RoomQualityGateError(
                f"qualityGate.items[{index}] must be an object"
            )
        criterion_id = str(raw_item.get("criterionId") or "").strip()
        if criterion_id not in allowed_criteria:
            raise RoomQualityGateError(
                "qualityGate contains a criterion outside the current Task"
            )
        if criterion_id in seen:
            raise RoomQualityGateError(
                "qualityGate contains a duplicate criterionId"
            )
        seen.add(criterion_id)
        status = str(raw_item.get("status") or "").strip()
        if status not in {"pass", "fail", "not_verified"}:
            raise RoomQualityGateError(
                f"qualityGate.items[{index}].status is invalid"
            )
        item_evidence = _string_list(
            raw_item.get("evidenceRefs"),
            f"qualityGate.items[{index}].evidenceRefs",
            maximum=64,
        )
        if status == "pass" and not item_evidence:
            raise RoomQualityGateError(
                "every qualityGate pass item requires fresh evidence"
            )
        if not set(item_evidence).issubset(aggregate_evidence):
            raise RoomQualityGateError(
                "qualityGate item evidence must also appear in evidenceRefs"
            )
        items.append(
            {
                "criterionId": criterion_id,
                "status": status,
                "evidenceRefs": item_evidence,
            }
        )

    if seen != allowed_criteria:
        raise RoomQualityGateError(
            "qualityGate must cover every acceptance criterion of the current Task"
        )
    pass_criteria = {
        str(item["criterionId"])
        for item in items
        if item["status"] == "pass"
    }
    if pass_criteria != set(requirement_coverage):
        raise RoomQualityGateError(
            "requirementCoverage must exactly match qualityGate pass items"
        )
    all_passed = len(pass_criteria) == len(canonical_criteria)
    if verdict == "ready_to_deliver" and not all_passed:
        raise RoomQualityGateError(
            "ready_to_deliver requires every qualityGate item to pass"
        )
    if decision == "deliver" and verdict != "ready_to_deliver":
        raise RoomQualityGateError(
            "deliver requires qualityGate verdict ready_to_deliver"
        )
    if decision in {"wait", "blocked"} and verdict != "not_ready":
        raise RoomQualityGateError(
            f"{decision} requires qualityGate verdict not_ready"
        )

    receipt = {
        "schemaVersion": ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
        "receiptId": _stable_id(
            "room-quality-gate",
            invocation_receipt_id,
        ),
        "rootId": root_id,
        "taskId": task_id,
        "dispatchId": dispatch_id,
        "generation": generation,
        "originalRequestChecked": True,
        "verdict": verdict,
        "items": items,
        "residualRisks": _string_list(
            proposal.get("residualRisks"),
            "qualityGate.residualRisks",
            maximum=32,
        ),
        "createdAtMs": now_ms,
    }
    validate_kernel_contract("roomQualityGateReceipt", receipt)
    return receipt


def validate_quality_gate_receipt(
    receipt: object,
    *,
    decision: str,
    root_id: str,
    task_id: str,
    dispatch_id: str,
    generation: int,
    task_criteria: Sequence[str],
    evidence_refs: Sequence[str],
    requirement_coverage: Sequence[str],
) -> None:
    if not isinstance(receipt, Mapping):
        raise RoomQualityGateError(
            "RoomCommit requires an authoritative qualityGateReceipt"
        )
    validate_kernel_contract("roomQualityGateReceipt", receipt)
    identity = {
        "rootId": root_id,
        "taskId": task_id,
        "dispatchId": dispatch_id,
        "generation": generation,
    }
    for key, expected in identity.items():
        if receipt.get(key) != expected:
            raise RoomQualityGateError(
                f"qualityGateReceipt {key} does not match the committing Dispatch"
            )
    if receipt.get("originalRequestChecked") is not True:
        raise RoomQualityGateError(
            "qualityGateReceipt did not confirm the immutable original request"
        )
    items = receipt.get("items")
    assert isinstance(items, Sequence)
    item_criteria = [str(item["criterionId"]) for item in items]
    if len(item_criteria) != len(set(item_criteria)):
        raise RoomQualityGateError(
            "qualityGateReceipt contains duplicate criterionId values"
        )
    if set(item_criteria) != set(task_criteria):
        raise RoomQualityGateError(
            "qualityGateReceipt does not cover the current Task criteria"
        )
    pass_items = [
        item
        for item in items
        if isinstance(item, Mapping) and item.get("status") == "pass"
    ]
    pass_criteria = {str(item["criterionId"]) for item in pass_items}
    if pass_criteria != set(requirement_coverage):
        raise RoomQualityGateError(
            "RoomCommit coverage differs from its qualityGateReceipt"
        )
    aggregate_evidence = set(evidence_refs)
    for item in pass_items:
        refs = item.get("evidenceRefs")
        if (
            not isinstance(refs, Sequence)
            or isinstance(refs, (str, bytes, bytearray))
            or not refs
            or not set(str(value) for value in refs).issubset(
                aggregate_evidence
            )
        ):
            raise RoomQualityGateError(
                "qualityGateReceipt pass item lacks committed evidence"
            )
    verdict = receipt.get("verdict")
    if verdict == "ready_to_deliver" and len(pass_items) != len(task_criteria):
        raise RoomQualityGateError(
            "ready_to_deliver receipt contains a non-passing criterion"
        )
    if decision == "complete" and verdict != "ready_to_deliver":
        raise RoomQualityGateError(
            "complete continuation requires a ready_to_deliver receipt"
        )
    if decision in {"wait", "block"} and verdict != "not_ready":
        raise RoomQualityGateError(
            f"{decision} continuation requires a not_ready receipt"
        )


def _string_list(value: object, name: str, *, maximum: int) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise RoomQualityGateError(
            f"{name} must be an array with at most {maximum} items"
        )
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            raise RoomQualityGateError(f"{name} contains an empty item")
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:40]}"
