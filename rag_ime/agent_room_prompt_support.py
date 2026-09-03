from __future__ import annotations

from collections.abc import Mapping, Sequence

from .agent_blocks import provider_block_projection


ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT = 12
ROOM_CONTEXT_HISTORY_CHAR_BUDGET = 3_600
ROOM_CONTEXT_PROMPT_CHAR_BUDGET = 12_000


def agent_message_text(message: Mapping[str, object]) -> str:
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    structured: list[Mapping[str, object]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        kind = str(block.get("type") or "")
        data = block.get("data")
        if kind in {"text", "code"} and isinstance(data, Mapping):
            value = data.get("text") if kind == "text" else data.get("code")
            text = " ".join(str(value or "").split())
            if text:
                parts.append(text)
        elif block.get("schemaVersion") == "rag-ime.agent-block.v1":
            structured.append(block)
    return provider_block_projection("\n\n".join(parts), structured, maximum_bytes=32_000)


def _budgeted_prompt(
    opening: Sequence[str],
    context: Sequence[str],
    tail: Sequence[str],
    heading: str,
    message: str,
) -> str:
    request = ["", f"{heading}：", message] if message else []
    ending = [*tail, *request, "</room-context>"]
    full = "\n".join([*opening, *context, *ending])
    if len(full) <= ROOM_CONTEXT_PROMPT_CHAR_BUDGET:
        return full
    if message:
        fixed = "\n".join([*opening, *tail, "", f"{heading}：", "</room-context>"])
        bounded = _head_tail(
            message,
            max(0, ROOM_CONTEXT_PROMPT_CHAR_BUDGET - len(fixed) - 1),
        )
        ending = [*tail, "", f"{heading}：", bounded, "</room-context>"]
    selected: list[str] = []
    for section in context:
        candidate = "\n".join([*opening, *selected, section, *ending])
        if len(candidate) > ROOM_CONTEXT_PROMPT_CHAR_BUDGET:
            break
        selected.append(section)
    notice = "[部分 Room 状态因提示词预算省略]"
    if len("\n".join([*opening, *selected, notice, *ending])) <= ROOM_CONTEXT_PROMPT_CHAR_BUDGET:
        selected.append(notice)
    return "\n".join([*opening, *selected, *ending])


def _document_rows(
    work_items: Sequence[Mapping[str, object]],
    related: Sequence[Mapping[str, object]],
    documents: Sequence[Mapping[str, object]],
    authorities: Mapping[str, Mapping[str, object]],
    names: Mapping[str, str],
    sessions: Mapping[str, str],
) -> list[str]:
    by_authority = {
        _text(item.get("authorityKey"), 520): item
        for item in documents
        if isinstance(item, Mapping) and _text(item.get("authorityKey"), 520)
    }
    related_ids = {str(item.get("id") or "") for item in related}
    rows: list[str] = []
    for work in work_items:
        work_id = _text(work.get("id"), 240)
        document = by_authority.get(f"room_work_item:{work_id}")
        if not work_id or document is None:
            continue
        owner = _text(work.get("currentOwnerParticipantId"), 240) or _text(
            work.get("accountableParticipantId"), 240
        )
        authority = authorities.get(f"room_work_item:{work_id}", {})
        revision = authority.get("authorityRevision")
        if not isinstance(revision, int):
            revision = _integer(document.get("authorityRevision"))
        rows.append(
            f"- [{'你负责' if work_id in related_ids else 'Room 共享'}] {work_id} → "
            f"{_text(document.get('path'), 800)}；"
            f"documentId={_text(document.get('documentId'), 240)}；"
            f"authorityRevision={revision}；负责人=@{names.get(owner, '未分配伙伴')}；"
            f"Session={sessions.get(owner) or '未绑定'}"
        )
        if len(rows) >= 6:
            break
    return rows


def _bounded_transcript(
    events: Sequence[Mapping[str, object]],
    names: Mapping[str, str],
) -> tuple[list[str], int]:
    chosen: list[str] = []
    used = 0
    omitted = max(0, len(events) - ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT)
    for event in reversed(events[-ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT:]):
        line = _event_line(event, names)
        if not line:
            continue
        if used + len(line) + 1 > ROOM_CONTEXT_HISTORY_CHAR_BUDGET:
            omitted += 1
            continue
        chosen.append(line)
        used += len(line) + 1
    return list(reversed(chosen)), omitted


def _event_line(event: Mapping[str, object], names: Mapping[str, str]) -> str:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    event_type = event.get("eventType")
    if event_type == "user_message":
        text = _text(payload.get("text"), 420)
        return f"用户：{text}" if text else ""
    if event_type == "room_post":
        post = payload.get("post")
        text = _text(post.get("content"), 420) if isinstance(post, Mapping) else ""
    elif event_type == "participant_message":
        projected = payload.get("data")
        projected = projected if isinstance(projected, Mapping) else payload
        raw = projected.get("message")
        text = _text(agent_message_text(raw), 420) if isinstance(raw, Mapping) else ""
    else:
        return ""
    speaker = names.get(str(event.get("participantId") or "")) or "Agent"
    return f"{speaker}：{text}" if text else ""


def _operation_hint(work: Mapping[str, object]) -> str:
    recommended = work.get("recommendedOperation")
    if isinstance(recommended, Mapping):
        operation = _text(recommended.get("op"), 80)
        if operation:
            revision = recommended.get("expectedRevision")
            suffix = f"，expectedRevision={_integer(revision)}" if revision is not None else ""
            return f"recommendedOperation={operation}{suffix}"
    if isinstance(recommended, str) and recommended.strip():
        return f"recommendedOperation={_text(recommended, 120)}"
    allowed = work.get("allowedOperations")
    if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)):
        values = [_text(item, 60) for item in allowed[:8] if _text(item, 60)]
        if values:
            return "allowedOperations=" + ",".join(values)
    return ""


def _head_tail(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    if maximum <= 0:
        return ""
    notice = "\n[用户请求中段因提示词预算省略]\n"
    if maximum <= len(notice):
        return value[-maximum:]
    remaining = maximum - len(notice)
    head = remaining // 2
    return value[:head] + notice + value[-(remaining - head) :]


def _related_to(work: Mapping[str, object], participant_id: str) -> bool:
    return bool(participant_id) and participant_id in {
        str(work.get("accountableParticipantId") or ""),
        str(work.get("currentOwnerParticipantId") or ""),
        str(work.get("offeredToParticipantId") or ""),
    }


def _relation(work: Mapping[str, object], participant_id: str) -> str:
    if str(work.get("offeredToParticipantId") or "") == participant_id:
        return "待你接手"
    if str(work.get("currentOwnerParticipantId") or "") == participant_id:
        return "由你推进"
    return "由你负责汇合"


def _work_state(value: object) -> str:
    return {
        "queued": "等待开始",
        "active": "进行中",
        "review": "等待验收",
        "blocked": "已阻塞",
        "done": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    }.get(str(value or ""), "未结")


def _work_action(value: str) -> str:
    return {
        "assignment": "移交责任",
        "handoff": "移交责任",
        "collaborate": "并行协助",
        "review": "独立复核",
        "message": "补充信息",
    }.get(value, "补充信息")


def _acceptance(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "未设置"
    items = [_text(item, 300) for item in value[:12] if _text(item, 300)]
    return "；".join(items) or "未设置"


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _text(value: object, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]
