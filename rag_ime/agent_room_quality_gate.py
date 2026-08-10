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
    prune_unverifiable_refs: bool = False,
    prefer_accepted_evidence: bool = False,
) -> CanonicalQualityGate:
    if not isinstance(evidence_proposal, list) or len(evidence_proposal) > 64:
        raise RoomQualityGateError(
            "room_commit.evidence 必须是数组，且最多包含 64 项"
        )
    if not isinstance(requirement_context, Mapping):
        raise RoomQualityGateError(
            "当前工作缺少已确认的原始需求，暂时无法检查是否完成"
        )
    originals = requirement_context.get("originalRequirements")
    if not isinstance(originals, list) or not originals:
        raise RoomQualityGateError(
            "当前工作没有保留用户的原始请求，暂时无法检查是否完成"
        )

    canonical_criteria = [str(item) for item in task_criteria if str(item)]
    if set(acceptance_aliases.values()) != set(canonical_criteria):
        raise RoomQualityGateError(
            "验收短名与当前工作卡片不一致，请重新读取 room_state"
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
    accepted_refs_by_criterion: dict[str, set[str]] = {
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
        accepted_refs = {
            str(value)
            for value in raw_refs
            if str(value or "").strip()
        }
        accepted_refs_by_criterion[criterion_id].update(accepted_refs)
        authoritative_refs[criterion_id].update(accepted_refs)
    runtime_refs = {
        str(value)
        for value in runtime_evidence_refs
        if str(value or "").strip()
    }
    for refs in authoritative_refs.values():
        refs.update(runtime_refs)

    submitted: dict[str, list[str]] = {}
    aliases_with_misassigned_refs: list[str] = []
    unknown_ref_positions_by_alias: dict[str, list[int]] = {}
    for index, raw_item in enumerate(evidence_proposal):
        if not isinstance(raw_item, Mapping):
            raise RoomQualityGateError(
                f"room_commit.evidence 的第 {index + 1} 项必须是对象"
            )
        alias = str(raw_item.get("acceptance") or "").strip().upper()
        criterion_id = acceptance_aliases.get(alias)
        if criterion_id is None:
            raise RoomQualityGateError(
                "room_commit.evidence 包含当前工作卡片之外的验收短名"
            )
        if criterion_id in submitted:
            raise RoomQualityGateError(
                "room_commit.evidence 重复填写了同一个验收短名"
            )
        item_evidence = _string_list(
            raw_item.get("refs"),
            f"room_commit.evidence[{index}].refs",
            maximum=64,
        )
        if not item_evidence:
            raise RoomQualityGateError(
                "每个提交的验收项都至少需要一个 evidenceRef"
            )
        if (
            prefer_accepted_evidence
            and accepted_refs_by_criterion[criterion_id]
        ):
            # Final aggregation is not a second evidence-producing step.
            # Once the Kernel already owns criterion-bound accepted proof,
            # use those exact refs instead of asking the model to transcribe
            # long opaque receipt IDs from room_state without alteration.
            item_evidence = sorted(
                accepted_refs_by_criterion[criterion_id]
            )
        if prune_unverifiable_refs:
            verified_item_evidence = [
                evidence_ref
                for evidence_ref in item_evidence
                if evidence_ref in authoritative_refs[criterion_id]
            ]
            # Independent review is allowed to ignore stale transcript refs
            # only when the same criterion still has direct, current proof.
            # A proposal with no verifiable proof remains fail-closed.
            # A handoff is a continuation, not a delivery verdict.  Stale
            # transcript refs must not prevent the next owner from doing the
            # requested review; drop them and leave the criterion unverified.
            # Final delivery remains fail-closed when no current proof exists.
            if verified_item_evidence or decision == "handoff":
                item_evidence = verified_item_evidence
        unknown_refs = set(item_evidence) - authoritative_refs[criterion_id]
        misassigned_refs = {
            evidence_ref
            for evidence_ref in unknown_refs
            if any(
                evidence_ref in other_refs
                for other_criterion_id, other_refs in authoritative_refs.items()
                if other_criterion_id != criterion_id
            )
        }
        if misassigned_refs:
            aliases_with_misassigned_refs.append(alias)
        remaining_unknown_refs = unknown_refs - misassigned_refs
        if remaining_unknown_refs:
            unknown_ref_positions_by_alias[alias] = [
                ref_index + 1
                for ref_index, evidence_ref in enumerate(item_evidence)
                if evidence_ref in remaining_unknown_refs
            ]
        submitted[criterion_id] = item_evidence
    if aliases_with_misassigned_refs:
        affected = ", ".join(aliases_with_misassigned_refs[:12])
        remainder = len(aliases_with_misassigned_refs) - 12
        if remainder > 0:
            affected = f"{affected} (+{remainder} more)"
        raise RoomQualityGateError(
            f"{affected} 包含了只属于其他验收项的 evidenceRef；"
            f"请从 {affected} 删除这些引用，只保留 room_state 中该验收项的 "
            "evidenceRefs 或直接支持该项的本次成功工具结果；"
            "不要把多个 AC 的 refs 合并到一项"
        )
    if unknown_ref_positions_by_alias:
        aliases_with_unknown_refs = list(unknown_ref_positions_by_alias)
        affected = ", ".join(aliases_with_unknown_refs[:12])
        remainder = len(aliases_with_unknown_refs) - 12
        if remainder > 0:
            affected = f"{affected} (+{remainder} more)"
        positions = "；".join(
            f"{alias} 的 refs 第 "
            f"{', '.join(str(index) for index in indexes)} 项"
            for alias, indexes in list(
                unknown_ref_positions_by_alias.items()
            )[:12]
        )
        raise RoomQualityGateError(
            f"{affected} 使用了无法核实的 evidenceRef（{positions}）；"
            "删除这些位置的旧引用，不要在新引用旁继续保留它们。"
            "只保留当前 Dispatch 中直接支持该项的最小成功工具结果，"
            "或最新 room_state 里该验收项已有的 evidenceRefs"
        )

    aliases_by_criterion = {
        criterion_id: alias
        for alias, criterion_id in acceptance_aliases.items()
    }
    runtime_ref_criteria: dict[str, set[str]] = {}
    for criterion_id, refs in submitted.items():
        for evidence_ref in refs:
            if evidence_ref in runtime_refs:
                runtime_ref_criteria.setdefault(evidence_ref, set()).add(
                    criterion_id
                )
    # A current ``room_state`` receipt is useful for locating Kernel-owned
    # evidence, but it is not itself three different proofs.  When the model
    # repeats that one receipt across criteria that already have exact,
    # criterion-bound accepted evidence, canonicalize to the accepted refs
    # instead of making opaque ID transcription a second source of truth.
    # Ordinary unaccepted tool results keep the one-result/one-criterion rule.
    for criteria in runtime_ref_criteria.values():
        if len(criteria) <= 1:
            continue
        for criterion_id in criteria:
            accepted_refs = accepted_refs_by_criterion.get(criterion_id, set())
            if accepted_refs:
                submitted[criterion_id] = sorted(accepted_refs)
    runtime_ref_criteria = {}
    for criterion_id, refs in submitted.items():
        for evidence_ref in refs:
            if evidence_ref in runtime_refs:
                runtime_ref_criteria.setdefault(evidence_ref, set()).add(
                    criterion_id
                )
    reused_runtime_criteria = {
        criterion_id
        for criteria in runtime_ref_criteria.values()
        if len(criteria) > 1
        for criterion_id in criteria
    }
    if reused_runtime_criteria:
        affected = ", ".join(
            sorted(
                aliases_by_criterion[criterion_id]
                for criterion_id in reused_runtime_criteria
            )
        )
        raise RoomQualityGateError(
            f"{affected} 重复使用了同一个普通工具结果；"
            "每次成功工具执行只能直接证明一个验收项。"
            "请逐项运行对应验证，或使用已经与验收项绑定的正式验证回执"
        )

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
    # Evidence completeness and lifecycle continuation are independent. A local
    # work card can satisfy every acceptance criterion and still need a
    # user-owned decision before the Root may continue. `wait` preserves that
    # completed evidence while the Kernel records the explicit resume signal.
    # `blocked`, by contrast, claims the current card cannot complete and is
    # contradictory once every criterion has passed.
    # An empty acceptance set is not a completed task. This prevents legacy or
    # malformed Tasks from passing the delivery gate by vacuous truth.
    all_passed = bool(canonical_criteria) and (
        len(requirement_coverage) == len(canonical_criteria)
    )
    verdict = "ready_to_deliver" if all_passed else "not_ready"
    if decision == "deliver" and not all_passed:
        raise RoomQualityGateError(
            "deliver 要求当前工作卡片的每个验收项都有成功工具结果支持"
        )
    if decision == "blocked" and all_passed:
        raise RoomQualityGateError(
            "所有验收项都已验证，不能选择 blocked；请使用 deliver、handoff 或 wait"
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
    if decision == "block" and verdict != "not_ready":
        raise RoomQualityGateError(
            "block continuation requires a not_ready receipt"
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
