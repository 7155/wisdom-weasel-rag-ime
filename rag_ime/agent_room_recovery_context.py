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

    requirements = _mapping(source.get("requirements"))
    original = _unique_texts(
        _mapping(item).get("text")
        for item in _mappings(requirements.get("original"))[:8]
    )
    directory = _unique_texts(
        _mapping(item).get("statement")
        for item in _mappings(requirements.get("items"))[:32]
        if bounded_text(_mapping(item).get("statement"), maximum=1_500)
        not in original
    )
    task = _mapping(source.get("task"))
    task_state = bounded_text(task.get("state"), maximum=40)
    covered = {
        bounded_text(value, maximum=240)
        for value in covered_criterion_ids
        if bounded_text(value, maximum=240)
    }
    acceptance = _unique_records(
        (
            _compact_mapping(
                {
                    "criterionId": bounded_text(
                        item.get("criterionId"), maximum=240
                    ),
                    "statement": bounded_text(
                        item.get("statement"), maximum=1_000
                    ),
                    "covered": bounded_text(
                        item.get("criterionId"), maximum=240
                    ) in covered,
                    "proofVerified": item.get("passed") is True,
                    "passed": (
                        item.get("passed") is True
                        or (
                            task_state == "completed"
                            and bounded_text(
                                item.get("criterionId"), maximum=240
                            ) in covered
                        )
                    ),
                }
            )
            for item in _mappings(
                _mapping(source.get("acceptance")).get("criteria")
            )[:32]
        ),
        key="criterionId",
        fallback_key="statement",
    )
    blockers_source = _mapping(source.get("blockers"))
    blockers = _unique_records(
        (
            {
                "kind": bounded_text(item.get("kind"), maximum=80),
                "statement": bounded_text(item.get("statement"), maximum=1_000),
            }
            for item in _mappings(blockers_source.get("obstacles"))[:32]
        ),
        key="statement",
    )
    continuation = _mapping(source.get("continuation"))
    packet: dict[str, object] = {
        "originalRequirements": original,
        "requirementDirectory": directory,
        "currentTask": {
            "objective": bounded_text(task.get("objective"), maximum=4_000),
            "expectedOutput": bounded_text(task.get("expectedOutput"), maximum=2_000),
            "state": task_state,
        },
        "acceptance": acceptance,
        "blockers": blockers,
        "handoff": _compact_mapping(
            {
                "intentKind": _recovery_intent(task_state, continuation),
            }
        ),
    }
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
