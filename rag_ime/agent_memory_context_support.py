from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .agent_blocks import provider_block_projection
from .agent_prompt_support import bounded_text


def task_aware_recall_query(
    user_text: object,
    task_objective: object,
) -> str:
    user = bounded_text(user_text, maximum=6_000)
    # Recalled @ text is searchable evidence, never routing authority.
    user = re.sub(
        r"(^|\s)@[\w.\-\u4e00-\u9fff]+(?=\s|$)",
        " ",
        user,
    ).strip()
    objective = bounded_text(
        task_objective,
        maximum=3_000,
    )
    if not objective:
        return user
    if objective in user:
        return bounded_text(user, maximum=8_000)
    return bounded_text(
        f"{user}\n任务目标：{objective}",
        maximum=8_000,
    )


def room_recall_fence(
    binding: Mapping[str, object] | None,
) -> tuple[object, ...]:
    if binding is None:
        return ()
    return (
        str(binding.get("manifestId") or ""),
        str(binding.get("manifestHash") or ""),
        int(binding.get("capabilityEpoch") or 0),
        str(binding.get("state") or ""),
    )


def recall_messages(
    value: object,
    *,
    first_user_maximum: int = 1_200,
) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, object]] = []
    preserved_original_requirement = False
    for item in value:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = recall_message_body(item)
        if not text:
            continue
        maximum = (
            max(1_200, min(int(first_user_maximum), 4_000))
            if role == "user" and not preserved_original_requirement
            else 1_200
        )
        result.append({"role": role, "text": text[:maximum]})
        if role == "user" and not preserved_original_requirement:
            preserved_original_requirement = True
    if len(result) <= 8:
        return result
    first_user = next(
        (item for item in result if item["role"] == "user"),
        None,
    )
    tail = result[-7:]
    if first_user is None or first_user in tail:
        return result[-8:]
    return [first_user, *tail]


def recall_message_body(
    message: Mapping[str, object],
) -> str:
    direct = " ".join(str(message.get("text") or "").split())
    if direct:
        return direct
    content = message.get("content")
    if isinstance(content, str):
        return " ".join(content.split())
    if not isinstance(content, (list, tuple)):
        content = message.get("blocks")
    if not isinstance(content, (list, tuple)):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if str(block.get("type") or "").lower() not in {
            "text",
            "output_text",
        }:
            continue
        data = (
            block.get("data")
            if isinstance(block.get("data"), Mapping)
            else {}
        )
        text = " ".join(
            str(
                block.get("text") or data.get("text") or ""
            ).split()
        )
        if text:
            parts.append(text)
    structured = [
        block
        for block in content
        if isinstance(block, Mapping)
        and str(block.get("type") or "").lower()
        not in {"text", "output_text"}
        and block.get("schemaVersion")
        == "rag-ime.agent-block.v1"
    ]
    return provider_block_projection(
        "\n".join(parts),
        structured,
        maximum_bytes=1_200,
    )


def recall_message_text(
    messages: Sequence[Mapping[str, object]],
) -> str:
    return "\n".join(
        f"{str(item.get('role') or '')}: "
        f"{str(item.get('text') or '')}"
        for item in messages[-8:]
        if str(item.get("text") or "").strip()
    )[:6_000]


def last_user_recall_text(
    messages: Sequence[Mapping[str, object]],
) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "") == "user":
            return bounded_text(
                item.get("text"),
                maximum=4_000,
            )
    return ""


def last_assistant_recall_text(
    messages: Sequence[Mapping[str, object]],
) -> str:
    for item in reversed(messages):
        if str(item.get("role") or "") == "assistant":
            return bounded_text(
                item.get("text"),
                maximum=4_000,
            )
    return ""


def compaction_summary(
    result: Mapping[str, object],
) -> str:
    direct = bounded_text(
        result.get("summary"),
        maximum=8_000,
    )
    if direct:
        return direct
    nested = result.get("result")
    if isinstance(nested, Mapping):
        return bounded_text(
            nested.get("summary"),
            maximum=8_000,
        )
    return ""
