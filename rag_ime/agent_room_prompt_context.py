from __future__ import annotations

from collections.abc import Mapping, Sequence

from .agent_blocks import provider_block_projection
from .agent_definitions import collaboration_role


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
    try:
        role_label = collaboration_role(role).display_name
    except ValueError:
        role_label = "协作伙伴"
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
            f"话题：{topic_title}；你本轮从“{role_label}”的角度参与"
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
        sections.extend(["", "与你有关的未完成工作：", *work_lines])
    if work_item_lines:
        sections.extend(["", "当前工作卡片：", *work_item_lines])
    elif room_kind == "collaboration":
        sections.extend(
            [
                "",
                "当前阶段：普通对话，或还没有需要执行的工作。",
                "普通闲聊直接回答。明确、可安全执行或只读核对的请求直接开始，"
                "不要让用户先填写额外表格或回复固定开工口令。只有 Facilitator/Reporter "
                "在缺少且会改变结果的用户选择时，才加载 alignment-and-decision，再用原生 ask "
                "一次提出一到四个必要问题并给出二到五个唯一选项；前置依赖改变后续问题时"
                "才分开问。Room partner 把缺口和恢复条件在公开回复中交给 Facilitator；"
                "nested child 通过子 Agent 结果事件返回 blocker。能从源码、配置或"
                "运行状态查明的事实自行核对。不要另起一套重复的目标、计划或伙伴任务流程。",
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
    private_notice = (
        kind == "send"
        and work is None
        and not action
        and not str(item.get("replyTo") or "").strip()
    )
    return (
        f"你刚收到伙伴 {source.get('displayName')} 发来的协作消息。"
        + (
            f"这条消息与当前工作“{_bounded_text(work.get('objective'), maximum=320)}”"
            f"有关，对方希望你{_work_action(action)}。"
            if work is not None
            else ""
        )
        + (
            "这是一条只供你参考的内部消息。结合它继续手上的工作；不要把同样内容"
            "公开重复，也不要新建消息或任务来回复“收到、谢谢、辛苦了”等礼貌回声。"
            "如果不需要采取行动，直接结束这一轮。"
            if private_notice
            else (
            "对方需要你的答复。判断后在 Room 中直接回复结论，"
                "不要只在私下说已经回复。"
                if kind == "ask"
                else (
                    "这是对先前问题的答复。把它作为当前工作的输入继续，但这条消息"
                    "本身不能证明验收已经通过；关键事实仍要用可核对来源或成功工具结果"
                    "验证。"
                    if kind == "reply"
                    else "只在当前工作需要时使用，不必机械复述。"
                )
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
