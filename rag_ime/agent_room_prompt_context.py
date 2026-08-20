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
    work_documents: Sequence[Mapping[str, object]] = (),
    work_document_authorities: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    """Build a provider-only Room delta; never persist it as a user message."""

    participant_names: dict[str, str] = {}
    participant_sessions: dict[str, str] = {}
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
        participant_sessions[participant_id] = _bounded_text(
            value.get("sessionId"),
            maximum=320,
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
    room_work_items = [
        value
        for value in room.get("workItems", [])
        if isinstance(value, Mapping)
        and str(value.get("state") or "")
        in {"queued", "active", "review", "blocked"}
    ]
    related_work_items: list[Mapping[str, object]] = []
    work_lines: list[str] = []
    for work in room_work_items:
        if not isinstance(work, Mapping):
            continue
        state = str(work.get("state") or "")
        if target_id not in {
            str(work.get("accountableParticipantId") or ""),
            str(work.get("currentOwnerParticipantId") or ""),
            str(work.get("offeredToParticipantId") or ""),
        }:
            continue
        related_work_items.append(work)
        relation = _work_relation(work, target_id)
        work_id = _bounded_text(work.get("id"), maximum=240)
        work_lines.append(
            f"- WorkItem {work_id} · {relation}，{_work_state(state)}："
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
        work_item_id = _bounded_text(work_item.get("id"), maximum=240)
        work_authority = (work_document_authorities or {}).get(
            f"room_work_item:{work_item_id}",
            {},
        )
        work_item_lines = [
            f"WorkItem：{work_item_id}",
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
        if work_authority:
            work_item_lines.append(
                "文档绑定（使用这里的权威回执，不要猜 WorkItem revision）："
                "authorityKind=room_work_item；"
                f"authorityId={work_item_id}；"
                "authorityRevision="
                f"{int(work_authority.get('authorityRevision') or 0)}；"
                "transitionReceiptId="
                f"{_bounded_text(work_authority.get('transitionReceiptId'), maximum=240)}"
            )
    document_by_authority = {
        _bounded_text(document.get("authorityKey"), maximum=520): document
        for document in work_documents
        if isinstance(document, Mapping)
        and _bounded_text(document.get("authorityKey"), maximum=520)
    }
    room_document_lines: list[str] = []
    related_ids = {
        str(value.get("id") or "") for value in related_work_items
    }
    for work in room_work_items[:12]:
        work_id = _bounded_text(work.get("id"), maximum=240)
        if not work_id:
            continue
        authority_key = f"room_work_item:{work_id}"
        authority = (work_document_authorities or {}).get(authority_key, {})
        authority_revision = authority.get("authorityRevision")
        authority_binding = (
            "authorityKind=room_work_item、"
            f"authorityId={work_id}、"
            f"authorityRevision={int(authority_revision)}"
            if isinstance(authority_revision, int)
            else "先从当前工作卡片核对 authorityRevision"
        )
        document = document_by_authority.get(authority_key)
        if document is None:
            if work_id in related_ids:
                room_document_lines.append(
                    f"- [你负责] WorkItem {work_id} 尚未登记活动文档；"
                    f"先用 work_documents list 查 authorityKey={authority_key}；"
                    "这是当前 WorkItem 的第一步：在 Room 工作区 docs/ 下创建 Markdown，"
                    f"workspace_write.workDocument 必须原样使用 {authority_binding}。"
                    "成功回执会给出 workDocumentRegistration.document.path；"
                    "后续 read/write 立即改用该规范路径，不再沿用首次请求路径，也不要重猜 revision。"
                )
            continue
        owner_id = (
            _bounded_text(work.get("currentOwnerParticipantId"), maximum=240)
            or _bounded_text(work.get("accountableParticipantId"), maximum=240)
            or _bounded_text(work.get("offeredToParticipantId"), maximum=240)
        )
        owner_name = participant_names.get(owner_id, "未分配伙伴")
        owner_session = participant_sessions.get(owner_id, "")
        scope = "你负责" if work_id in related_ids else "Room 共享"
        room_document_lines.append(
            f"- [{scope}] WorkItem {work_id} → "
            f"{_bounded_text(document.get('path'), maximum=1_000)}；"
            f"documentId={_bounded_text(document.get('documentId'), maximum=240)}；"
            f"authorityRevision={int(document.get('authorityRevision') or 0)}；"
            f"标题={_bounded_text(document.get('title'), maximum=240) or '未命名工作文档'}；"
            f"负责人=@{owner_name}；Session={owner_session or '未绑定'}"
        )
        if work_id in related_ids:
            room_document_lines.append(
                "  交付规则：先在该文档写目标、范围与计划；工作中持续更新；"
                "结束前再写结果、证据、改动文件、验证和剩余风险，并重新绑定登记。"
            )
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
    if room_document_lines:
        sections.extend(
            [
                "",
                "Room 正在工作的文档索引：",
                *room_document_lines,
                (
                    "读取规则：先用 work_documents list/get 核对 documentId、authorityKey "
                    "和当前哈希，再用 workspace_read 读取上面给出的 path。优先读取标记为"
                    "“你负责”的文档；需要别的伙伴上下文时直接 @ 对方，不要扫描或继承无关"
                    "Session 的整段对话。"
                ),
                (
                    "完成门槛：Room WorkItem 只有在负责文档已登记且至少形成一次后续内容修订"
                    "（documentRevision >= 2）后才会自动验收；这不是人工审阅。"
                ),
            ]
        )
    if room_kind == "collaboration":
        if role == "coordinator":
            sections.extend(
                [
                    "",
                    "当前职责：Room Facilitator。普通闲聊或一个连贯动作直接处理；"
                    "当请求包含多个可独立验收步骤、需要不同专长，或并行处理能明显推进时，"
                    "先用 skill_load 加载 facilitate-room，再按该 Skill 判断是否调用 "
                    "room_partner list/delegate/delegate_batch；同一阶段多条独立轨道"
                    "必须用一次 delegate_batch 才能称为并行，不要为了凑伙伴数量机械委派。",
                    "Room 内所有 participant 都是平等 peer。需要澄清、同步或求助时，"
                    "直接使用 room_partner peer_list/peer_send/peer_ask/peer_reply 与目标伙伴通信；"
                    "消息由 source Session 直接投递到 target Session。Facilitator 只负责最终 Root 汇合，"
                    "不得复制、改写或转发伙伴原话来模拟互相 @。",
                    "delegate/delegate_batch 返回 partial、blocked 或 timed_out 时，先逐项读取回执；"
                    "不得重新分派已经 completed 或已有 work_result 的 WorkItem，只恢复明确未完成的轨道。",
                ]
            )
        else:
            sections.extend(
                [
                    "",
                    "Room 协作规则：所有 participant 都是平等 peer。需要另一位伙伴的信息或回应时，"
                    "直接使用 room_partner peer_list/peer_send/peer_ask/peer_reply；不要等待 Facilitator 中转，"
                    "也不要把自己当成上级。Facilitator 只负责最终 Root 汇合。",
                    "只有所有验收条件满足且负责的 WorkDocument 已完成收尾同步后，才调用一次 "
                    "room_partner post(kind=work_result)；该结构化交付会结束当前 WorkItem，"
                    "不要把进度或尚未满足的条件伪装成 work_result。",
                ]
            )
        sections.extend(
            [
                "",
                "当前尚未形成结构化 WorkItem；这不代表当前请求是普通闲聊。",
                "先判断用户请求是对话还是执行任务。普通闲聊直接回答；明确、可安全执行"
                "或只读核对的请求直接开始。若一个执行请求包含两个以上可独立验收的组成部分，"
                "Facilitator 在输出实现结果前必须先加载 facilitate-room，并根据真实 delegate/"
                "delegate_batch 回执建立 WorkItem；决定不委派时必须明确说明不能独立验收或并行无收益。"
                "不要让用户先填写额外表格或回复固定开工口令。只有 Facilitator/Reporter "
                "在缺少且会改变结果的用户选择时，才加载 alignment-and-decision，再用原生 ask "
                "一次提出一到四个必要问题并给出二到五个唯一选项；前置依赖改变后续问题时"
                "才分开问。Room partner 把缺口和恢复条件在公开回复中交给 Facilitator；"
                "nested child 通过子 Agent 结果事件返回 blocker。能从源码、配置或"
                "运行状态查明的事实自行核对。不要另起一套重复的目标、计划或伙伴任务流程。",
                "Pi 接受一个 Session 回合只表示运行已进入同一 Tool loop，不代表模型必然完成；"
                "只有可核对的 Tool 回执、WorkItem 验收和最终 Root 汇合才能作为成功证据。",
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
    return "由你负责汇合"


def _work_state(value: str) -> str:
    return {
        "queued": "等待开始",
        "active": "进行中",
        "review": "等待汇合",
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
