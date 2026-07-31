from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence

from .agent_prompt_support import bounded_text


ROOM_COMPACTION_RECOVERY_MAX_BYTES = 64 * 1024


def room_compaction_recovery_context(
    task_context: str,
    *,
    skill_receipt: Mapping[str, object] | None = None,
    tool_receipt: Mapping[str, object] | None = None,
    covered_criterion_ids: Sequence[str] = (),
) -> str:
    """Project one bounded recovery packet for a new Provider context epoch."""

    try:
        source = json.loads(task_context)
    except json.JSONDecodeError as exc:
        raise ValueError("Room task context is not valid JSON") from exc
    if not isinstance(source, Mapping):
        raise ValueError("Room task context must be an object")

    task = _mapping(source.get("task"))
    task_state = bounded_text(task.get("state"), maximum=40)
    terminal = task_state in {"completed", "failed", "cancelled"}
    covered = {
        bounded_text(value, maximum=240)
        for value in covered_criterion_ids
        if bounded_text(value, maximum=240)
    }
    pending_acceptance: list[dict[str, object]] = []
    seen_criteria: set[str] = set()
    for index, item in enumerate(
        _mappings(_mapping(source.get("acceptance")).get("criteria"))[:32],
        start=1,
    ):
        criterion_id = bounded_text(item.get("criterionId"), maximum=240)
        statement = bounded_text(item.get("statement"), maximum=1_000)
        identity = criterion_id or statement
        if (
            terminal
            or not identity
            or identity in seen_criteria
            or criterion_id in covered
        ):
            continue
        seen_criteria.add(identity)
        evidence_refs = _criterion_evidence_refs(item)
        pending_acceptance.append(
            _compact_mapping(
                {
                    # Keep the alias aligned with the complete Kernel criterion
                    # order. Filtering first would silently renumber AC-2 to AC-1.
                    "alias": f"AC-{index}",
                    "statement": statement,
                    "evidenceRefs": evidence_refs,
                }
            )
        )
    blockers_source = _mapping(source.get("blockers"))
    blockers = _unique_records(
        (
            _compact_mapping(
                {
                    "referenceId": bounded_text(
                        item.get("obstacleId"), maximum=240
                    ),
                    "kind": bounded_text(item.get("kind"), maximum=80),
                    "statement": bounded_text(
                        item.get("statement"), maximum=1_000
                    ),
                }
            )
            for item in _mappings(blockers_source.get("obstacles"))[:32]
        ),
        key="statement",
    )
    continuation = _mapping(source.get("continuation"))
    projection_ref = _compact_mapping(
        {
            "rootId": bounded_text(source.get("rootId"), maximum=240),
            "taskId": bounded_text(task.get("taskId"), maximum=240),
            "dispatchId": bounded_text(source.get("dispatchId"), maximum=240),
            "taskRevision": (
                int(task.get("revision"))
                if isinstance(task.get("revision"), int)
                and not isinstance(task.get("revision"), bool)
                else None
            ),
            "generation": (
                int(source.get("generation"))
                if isinstance(source.get("generation"), int)
                and not isinstance(source.get("generation"), bool)
                else None
            ),
        }
    )
    next_action = (
        _compact_mapping(
            {
                "intentKind": _recovery_intent(task_state, continuation),
                "acceptanceAlias": (
                    pending_acceptance[0].get("alias")
                    if pending_acceptance
                    else None
                ),
                "blockerRef": (
                    blockers[0].get("referenceId")
                    if blockers
                    else None
                ),
            }
        )
        if not terminal
        else {}
    )
    packet: dict[str, object] = {
        "authoritativeProjectionRef": projection_ref,
        "pendingAcceptance": pending_acceptance,
        "blockers": blockers,
    }
    if next_action:
        packet["nextAction"] = next_action
    evidence_refs = _unique_texts(
        _string_values(source.get("sharedEvidenceRefs"))
    )
    if evidence_refs:
        packet["evidenceRefs"] = evidence_refs
    if skill_receipt is not None:
        packet["skillReceipt"] = _compact_mapping(
            {
                "skillId": bounded_text(
                    skill_receipt.get("skillId"), maximum=240
                ),
                "restoredFromReceiptId": bounded_text(
                    skill_receipt.get("restoredFromReceiptId"),
                    maximum=240,
                ),
            }
        )
    if tool_receipt is not None:
        packet["toolReceipt"] = {
            "items": [
                _compact_mapping(
                    {
                        "name": bounded_text(item.get("name"), maximum=240),
                        "receiptId": bounded_text(
                            item.get("receiptId"), maximum=240
                        ),
                    }
                )
                for item in _mappings(tool_receipt.get("items"))[:64]
            ]
        }
    rendered = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(rendered.encode("utf-8")) > ROOM_COMPACTION_RECOVERY_MAX_BYTES:
        raise ValueError("Room compaction recovery exceeds the bounded context budget")
    return rendered


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _unique_texts(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = bounded_text(value, maximum=4_000)
        if text and text not in result:
            result.append(text)
    return result


def _string_values(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [
        bounded_text(item, maximum=500)
        for item in value
        if bounded_text(item, maximum=500)
    ]


def _criterion_evidence_refs(
    criterion: Mapping[str, object],
) -> list[str]:
    refs = _string_values(criterion.get("acceptedEvidenceRefs"))
    for proof in _mappings(criterion.get("proofs"))[:16]:
        refs.extend(
            value
            for value in (
                bounded_text(proof.get("receiptId"), maximum=240),
                bounded_text(proof.get("sourceCommit"), maximum=240),
            )
            if value
        )
    return _unique_texts(refs)


def _unique_records(
    values: Iterable[Mapping[str, object]],
    *,
    key: str,
    fallback_key: str | None = None,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for value in values:
        identity = bounded_text(value.get(key), maximum=1_000)
        if not identity and fallback_key is not None:
            identity = bounded_text(value.get(fallback_key), maximum=1_000)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(dict(value))
    return result


def _compact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "")
    }


def _recovery_intent(
    task_state: str,
    continuation: Mapping[str, object],
) -> object:
    return {
        "completed": "complete",
        "blocked": "blocked",
        "waiting": "wait",
    }.get(task_state, continuation.get("intentKind"))
