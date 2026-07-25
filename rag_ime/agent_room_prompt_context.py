from __future__ import annotations

from collections.abc import Mapping, Sequence

from .agent_blocks import provider_block_projection


ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT = 12
ROOM_CONTEXT_HISTORY_CHAR_BUDGET = 3_600
ROOM_CONTEXT_PROMPT_CHAR_BUDGET = 24_000


def room_participant_prompt(
    room: Mapping[str, object],
    target: Mapping[str, object],
    message: str,
    *,
    recent_messages: Sequence[Mapping[str, object]] = (),
    omitted_message_count: int = 0,
    request_heading: str = "用户在 Room 中的请求",
    work_item: Mapping[str, object] | None = None,
) -> str:
    """Build a provider-only Room delta; never persist it as a user message."""

    participant_names: dict[str, str] = {}
    for value in room.get("participants", []):
        if (
            not isinstance(value, Mapping)
            or value.get("status") != "active"
        ):
            continue
        participant_id = _bounded_text(value.get("id"), maximum=240)
        participant_names[participant_id] = _bounded_text(
            value.get("displayName"),
            maximum=40,
        )
    role = (
        _bounded_text(target.get("collaborationRole"), maximum=40)
        or "implementer"
    )
    room_kind = (
        _bounded_text(room.get("roomKind"), maximum=40)
        or "collaboration"
    )
    active_topic = next(
        (
            value
            for value in room.get("topics", [])
            if isinstance(value, Mapping)
            and str(value.get("id") or "")
            == str(room.get("activeTopicId") or "")
        ),
        {},
    )
    topic_title = (
        _bounded_text(active_topic.get("title"), maximum=120)
        or "主话题"
    )
    topic_summary = _bounded_text(
        active_topic.get("summary"),
        maximum=600,
    )
    scenario_prompt = _bounded_text(
        room.get("scenarioPrompt"),
        maximum=800,
    )
    transcript_lines, transcript_budget_omitted = _bounded_transcript(
        recent_messages,
        participant_names,
    )
    target_id = str(target.get("id") or "")
    work_lines: list[str] = []
    for work in room.get("workItems", []):
        if not isinstance(work, Mapping):
            continue
        state = str(work.get("state") or "")
        if state not in {"queued", "active", "review", "blocked"}:
            continue
        if target_id not in {
            str(work.get("accountableParticipantId") or ""),
            str(work.get("currentOwnerParticipantId") or ""),
            str(work.get("offeredToParticipantId") or ""),
        }:
            continue
        relation = _work_relation(work, target_id)
        work_lines.append(
            f"- {relation}，{_work_state(state)}："
            f"{_bounded_text(work.get('objective'), maximum=320)}"
        )
        if len(work_lines) >= 4:
            break
    total_omitted = (
        max(0, omitted_message_count) + transcript_budget_omitted
    )
    transcript_note = (
        f"- 另有 {total_omitted} 条较早未读消息已越过本次上下文窗口；"
        "需要时查看话题摘要、公开产物或任务状态。"
        if total_omitted > 0
        else ""
    )
    work_item_lines: list[str] = []
    if work_item is not None:
        work_item_lines = [
            f"目标：{_bounded_text(work_item.get('objective'), maximum=1_000)}",
            (
                "预期产物："
                f"{_bounded_text(work_item.get('expectedOutput'), maximum=1_000)}"
            ),
            (
                "验收条件："
                f"{_acceptance_text(work_item.get('acceptanceCriteria'))}"
            ),
        ]
    sections = [
        "<room-context>",
        (
            f"Room：{_bounded_text(room.get('title'), maximum=120)}；"
            f"话题：{topic_title}；你本轮以 {role} 视角参与"
        ),
    ]
    if topic_summary:
        sections.append(f"话题摘要：{topic_summary}")
    if scenario_prompt:
        sections.append(f"Room 补充设定（不改变权限）：{scenario_prompt}")
    if transcript_lines or transcript_note:
        sections.extend(
            [
                "",
                "本次新增的公开对话：",
                *(transcript_lines or ["- 无"]),
            ]
        )
        if transcript_note:
            sections.append(transcript_note)
    if work_lines:
        sections.extend(["", "与你有关的未结责任：", *work_lines])
    if work_item_lines:
        sections.extend(["", "当前受管任务：", *work_item_lines])
    elif room_kind == "collaboration":
        sections.extend(
            [
                "",
                "当前阶段：需求对齐，尚未进入受管执行。",
                "普通闲聊直接回答。用户提出工作目标时，先确认范围、验收和禁区；"
                "缺口会改变结果时，若 requirement-alignment 已在 <loaded_skill> 中就"
                "直接遵循，否则精确加载；只有需要主动挑战重大产品或架构取舍时，"
                "才以同样规则使用 grill-me。",
                "能从源码、配置或运行状态查明的事实自行核对；一次只问一个真正需要"
                "用户决定的问题。用户确认前，不声称已经开工、分派或获得执行授权。",
            ]
        )
    if message:
        sections.extend(["", f"{request_heading}：", message])
    sections.append("</room-context>")
    return "\n".join(sections)[:ROOM_CONTEXT_PROMPT_CHAR_BUDGET]


def room_intercom_prompt(
    room: Mapping[str, object],
    target: Mapping[str, object],
    item: Mapping[str, object],
    *,
    source: Mapping[str, object],
    work: Mapping[str, object] | None,
) -> str:
    del room, target
    kind = str(item.get("kind") or "send")
    action = str(item.get("workAction") or "")
    return (
        f"你刚收到来自 {source.get('displayName')} 的 Room 协作消息。"
        + (
            f"它与当前任务“{_bounded_text(work.get('objective'), maximum=320)}”有关，"
            f"协作动作是 {_work_action(action)}。"
            if work is not None
            else ""
        )
        + (
            "这是需要答复的问题；请在判断后调用 room_post "
            "发布答复，不要只在私有 Session 中说已经回复。"
            if kind == "ask"
            else (
                "这是对先前问题的答复；将它作为当前任务输入继续，但消息本身不是"
                "验收 evidenceRef，关键事实仍需用可核对来源或成功工具回执验证。"
                if kind == "reply"
            else "仅在当前任务需要时使用，不必机械复述。"
            )
        )
    )


def _work_relation(work: Mapping[str, object], target_id: str) -> str:
    if str(work.get("offeredToParticipantId") or "") == target_id:
        return "待你接手"
    if str(work.get("currentOwnerParticipantId") or "") == target_id:
        return "由你推进"
    return "由你负责验收"


def _work_state(value: str) -> str:
    return {
        "queued": "等待开始",
        "active": "进行中",
        "review": "等待复核",
        "blocked": "已阻塞",
    }.get(value, "未结")


def _work_action(value: str) -> str:
    return {
        "assignment": "移交责任",
        "handoff": "移交责任",
        "collaborate": "并行协助",
        "review": "独立复核",
        "message": "补充信息",
    }.get(value, "补充信息")


def agent_message_text(message: Mapping[str, object]) -> str:
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        block_type = str(block.get("type") or "")
        if block_type not in {"text", "code"}:
            continue
        data = block.get("data")
        if not isinstance(data, Mapping):
            continue
        value = (
            data.get("text")
            if block_type == "text"
            else data.get("code")
        )
        text = " ".join(str(value or "").split())
        if text:
            parts.append(text)
    structured = [
        block
        for block in blocks
        if isinstance(block, Mapping)
        and str(block.get("type") or "") not in {"text", "code"}
        and block.get("schemaVersion") == "rag-ime.agent-block.v1"
    ]
    return provider_block_projection(
        "\n\n".join(parts),
        structured,
        maximum_bytes=32_000,
    )


def _context_line(
    event: Mapping[str, object],
    participant_names: Mapping[str, str],
) -> str:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return ""
    if event.get("eventType") == "user_message":
        text = _bounded_text(payload.get("text"), maximum=420)
        return f"用户：{text}" if text else ""
    if event.get("eventType") == "room_post":
        post = payload.get("post")
        if not isinstance(post, Mapping):
            return ""
        text = _bounded_text(post.get("content"), maximum=420)
        if not text:
            return ""
        speaker = (
            participant_names.get(str(event.get("participantId") or ""))
            or "Agent"
        )
        return f"{speaker}：{text}"
    if event.get("eventType") != "participant_message":
        return ""
    data = payload.get("data")
    projected = data if isinstance(data, Mapping) else payload
    message = projected.get("message")
    if not isinstance(message, Mapping):
        return ""
    text = agent_message_text(message).strip()
    if not text:
        return ""
    speaker = (
        participant_names.get(str(event.get("participantId") or ""))
        or "Agent"
    )
    return f"{speaker}：{_bounded_text(text, maximum=420)}"


def _bounded_transcript(
    recent_messages: Sequence[Mapping[str, object]],
    participant_names: Mapping[str, str],
) -> tuple[list[str], int]:
    selected_reversed: list[str] = []
    used = 0
    omitted = max(
        0,
        len(recent_messages) - ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT,
    )
    for event in reversed(
        recent_messages[-ROOM_CONTEXT_UNREAD_MESSAGE_LIMIT:]
    ):
        line = _context_line(event, participant_names)
        if not line:
            continue
        cost = len(line) + 1
        if used + cost > ROOM_CONTEXT_HISTORY_CHAR_BUDGET:
            omitted += 1
            continue
        selected_reversed.append(line)
        used += cost
    return list(reversed(selected_reversed)), omitted


def _acceptance_text(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "未设置"
    items = [
        _bounded_text(item, maximum=300)
        for item in value[:12]
        if _bounded_text(item, maximum=300)
    ]
    return "；".join(items) or "未设置"


def _bounded_text(value: object, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]
