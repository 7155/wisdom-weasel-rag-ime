from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .agent_room_kernel_contracts import (
    ROOM_QUALITY_GATE_RECEIPT_SCHEMA_VERSION,
    validate_kernel_contract,
)


class RoomQualityGateError(ValueError):
    """A quality proposal cannot become an authoritative Kernel receipt."""


@dataclass(frozen=True)
class CanonicalQualityGate:
    receipt: dict[str, object]
    evidence_refs: tuple[str, ...]
    requirement_coverage: tuple[str, ...]


def canonicalize_quality_gate(
    *,
    evidence_proposal: object,
    residual_risks: object,
    decision: str,
    root_id: str,
    task_id: str,
    dispatch_id: str,
    generation: int,
    task_criteria: Sequence[str],
    acceptance_aliases: Mapping[str, str],
    requirement_context: Mapping[str, object] | None,
    accepted_evidence_by_criterion: Mapping[
        str, Sequence[object]
    ] | None,
    runtime_evidence_refs: Sequence[str],
    invocation_receipt_id: str,
    now_ms: int,
) -> CanonicalQualityGate:
    if not isinstance(evidence_proposal, list) or len(evidence_proposal) > 64:
        raise RoomQualityGateError(
            "room_commit.evidence must be an array with at most 64 items"
        )
    if not isinstance(requirement_context, Mapping):
        raise RoomQualityGateError(
            "current Dispatch has no frozen requirement observation"
        )
    originals = requirement_context.get("originalRequirements")
    if not isinstance(originals, list) or not originals:
        raise RoomQualityGateError(
            "current Dispatch did not preserve the original request"
        )

    canonical_criteria = [str(item) for item in task_criteria if str(item)]
    if set(acceptance_aliases.values()) != set(canonical_criteria):
        raise RoomQualityGateError(
            "acceptance alias map does not match the current Task"
        )
    catalog = requirement_context.get("catalog")
    raw_criteria = (
        catalog.get("acceptanceCriteria")
        if isinstance(catalog, Mapping)
        else []
    )
    authoritative_refs: dict[str, set[str]] = {
        criterion_id: set()
        for criterion_id in canonical_criteria
    }
    for criterion in raw_criteria or []:
        if not isinstance(criterion, Mapping):
            continue
        criterion_id = str(criterion.get("criterionId") or "").strip()
        if criterion_id not in authoritative_refs:
            continue
        for proof in criterion.get("proofs") or []:
            if (
                isinstance(proof, Mapping)
                and int(proof.get("exitStatus") or 0) == 0
                and str(proof.get("receiptId") or "").strip()
            ):
                authoritative_refs[criterion_id].add(
                    str(proof["receiptId"])
                )
    for criterion_id, raw_refs in (
        accepted_evidence_by_criterion or {}
    ).items():
        if criterion_id not in authoritative_refs:
            continue
        authoritative_refs[criterion_id].update(
            str(value)
            for value in raw_refs
            if str(value or "").strip()
        )
    runtime_refs = {
        str(value)
        for value in runtime_evidence_refs
        if str(value or "").strip()
    }
    for refs in authoritative_refs.values():
        refs.update(runtime_refs)

    submitted: dict[str, list[str]] = {}
    for index, raw_item in enumerate(evidence_proposal):
        if not isinstance(raw_item, Mapping):
            raise RoomQualityGateError(
                f"room_commit.evidence[{index}] must be an object"
            )
        alias = str(raw_item.get("acceptance") or "").strip().upper()
        criterion_id = acceptance_aliases.get(alias)
        if criterion_id is None:
            raise RoomQualityGateError(
                "room_commit.evidence contains an AC alias outside the current Task"
            )
        if criterion_id in submitted:
            raise RoomQualityGateError(
                "room_commit.evidence contains a duplicate AC alias"
            )
        item_evidence = _string_list(
            raw_item.get("refs"),
            f"room_commit.evidence[{index}].refs",
            maximum=64,
        )
        if not item_evidence:
            raise RoomQualityGateError(
                "every submitted AC requires at least one evidence ref"
            )
        unknown_refs = set(item_evidence) - authoritative_refs[criterion_id]
        if unknown_refs:
            raise RoomQualityGateError(
                "submitted evidence is not an authoritative successful receipt "
                "for its AC alias"
            )
        submitted[criterion_id] = item_evidence

    items: list[dict[str, object]] = []
    evidence_refs: list[str] = []
    requirement_coverage: list[str] = []
    for criterion_id in canonical_criteria:
        refs = submitted.get(criterion_id, [])
        if refs:
            requirement_coverage.append(criterion_id)
            evidence_refs.extend(refs)
        items.append(
            {
                "criterionId": criterion_id,
                "status": "pass" if refs else "not_verified",
                "evidenceRefs": refs,
            }
        )
    evidence_refs = list(dict.fromkeys(evidence_refs))
    # An empty acceptance set is not a completed task. This prevents legacy or
    # malformed Tasks from passing the delivery gate by vacuous truth.
    all_passed = bool(canonical_criteria) and (
        len(requirement_coverage) == len(canonical_criteria)
    )
    verdict = "ready_to_deliver" if all_passed else "not_ready"
    if decision == "deliver" and not all_passed:
        raise RoomQualityGateError(
            "deliver requires an authoritative successful receipt for every AC"
        )
    if decision in {"wait", "blocked"} and all_passed:
        raise RoomQualityGateError(
            f"{decision} is invalid after every AC is verified; use deliver or handoff"
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
            residual_risks,
            "room_commit.residualRisks",
            maximum=32,
        ),
        "createdAtMs": now_ms,
    }
    validate_kernel_contract("roomQualityGateReceipt", receipt)
    return CanonicalQualityGate(
        receipt=receipt,
        evidence_refs=tuple(evidence_refs),
        requirement_coverage=tuple(requirement_coverage),
    )


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
