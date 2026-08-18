from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start: str,
    end: str,
    replacement: str,
    *,
    label: str,
) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


def patch_agent_service() -> None:
    path = "rag_ime/agent_service.py"
    text = read(path)
    text = replace_once(
        text,
        "from .agent_room_partner_application import (\n"
        "    RoomPartnerApplicationService,\n"
        ")",
        "from .agent_room_partner_workflow import (\n"
        "    RoomPartnerApplicationService,\n"
        ")",
        label="agent_service authoritative Room import",
    )
    text = replace_once(
        text,
        "        self.room_partner_application = RoomPartnerApplicationService(\n"
        "            rooms=self.rooms,",
        "        self.room_partner_application = RoomPartnerApplicationService(\n"
        "            room_work=self.room_work,\n"
        "            publish_room_work_activity=self._publish_room_work_activity,\n"
        "            rooms=self.rooms,",
        label="agent_service Room workflow dependencies",
    )
    write(path, text)


def patch_room_work_parallel_limit() -> None:
    path = "rag_ime/agent_room_work.py"
    text = read(path)
    text = replace_once(
        text,
        "            parallel_limit = (\n"
        "                2 if str(source[\"collaboration_role\"]) == \"coordinator\" else 1\n"
        "            )",
        "            # room_partner supports a single real wave of up to three\n"
        "            # independent Partner Sessions. The authority ledger must\n"
        "            # admit the same fan-out instead of failing the third lane.\n"
        "            parallel_limit = (\n"
        "                3 if str(source[\"collaboration_role\"]) == \"coordinator\" else 1\n"
        "            )",
        label="Room WorkItem parallel limit",
    )
    write(path, text)


def patch_agent_tools() -> None:
    path = "rag_ime/agent_tools.py"
    text = read(path)
    spec = '''    {
        "id": "room_partner",
        "domain": "agents",
        "displayName": "Room 伙伴工作流",
        "description": "查看伙伴与正式 WorkItem；按阶段委派一个任务或并行波次；对回传证据显式验收、返修和续跑；发布公开进展与 Root 最终结果",
        "when": (
            "当前 Session 正在 Room 中主持任务，且需要另一位正式伙伴独立处理有界子任务",
            "同一阶段有 2–3 个无依赖、不重叠的工作轨道，需要真实并行启动",
            "伙伴已回传证据，需要验收、返修或继续返修 WorkItem",
        ),
        "notFor": (
            "普通 Session 的临时微型子 Agent，或主伙伴自己即可完成的单步工作",
            "写入范围重叠，或依赖 WorkItem 尚未通过验收的任务",
        ),
        "input": "list；带阶段、目标伙伴、交付合同和依赖的委派；同阶段 2–3 个任务；WorkItem 验收/返修/续跑；或公开进展/最终结果",
        "output": "伙伴与 WorkItem 状态、带 workItemId/waveId 的运行回执、待验收合同、验收结论，或类型明确的公开回执",
        "does": "PAW 创建 WorkItem、校验依赖和验收；Pi 仍执行普通 Partner Session。delegate_batch 先并发启动整个波次再等待，回传只进入 review，Root 最终答复会被未闭环 WorkItem 阻止。",
        "operations": (
            "list",
            "delegate",
            "delegate_batch",
            "accept",
            "return",
            "resume",
            "post",
        ),
        # Availability is still Room-bound below. Once available, this is the
        # only formal Partner workflow primitive and must be callable directly.
        "alwaysAvailable": True,
        "resultPresentation": "tool_result",
    },
'''
    text = replace_between(
        text,
        '    {\n        "id": "room_partner",',
        '    {\n        "id": "browser",',
        spec,
        label="room_partner tool specification",
    )
    schema = '''    "room_partner": {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op"],
                "properties": {"op": {"const": "list"}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "op",
                    "phase",
                    "targetParticipantId",
                    "task",
                    "expectedOutput",
                    "acceptanceCriteria",
                ],
                "properties": {
                    "op": {"const": "delegate"},
                    "phase": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                    },
                    "targetParticipantId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                        "description": "必须原样使用 list 返回的 participantId。",
                    },
                    "task": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8_000,
                    },
                    "expectedOutput": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1_200,
                    },
                    "acceptanceCriteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 320,
                        },
                    },
                    "dependsOnWorkItemIds": {
                        "type": "array",
                        "maxItems": 8,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 240,
                        },
                    },
                    "parentWorkItemId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                    "timeoutSeconds": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 300,
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "phase", "tasks"],
                "properties": {
                    "op": {"const": "delegate_batch"},
                    "phase": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                    },
                    "timeoutSeconds": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 300,
                    },
                    "tasks": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 3,
                        "description": "必须互不依赖且目标伙伴不重复的同阶段任务。",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "targetParticipantId",
                                "task",
                                "expectedOutput",
                                "acceptanceCriteria",
                            ],
                            "properties": {
                                "targetParticipantId": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 240,
                                    "description": "必须原样使用 list 返回的 participantId。",
                                },
                                "task": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 8_000,
                                },
                                "expectedOutput": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 1_200,
                                },
                                "acceptanceCriteria": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 8,
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 320,
                                    },
                                },
                                "dependsOnWorkItemIds": {
                                    "type": "array",
                                    "maxItems": 8,
                                    "uniqueItems": True,
                                    "items": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 240,
                                    },
                                },
                                "parentWorkItemId": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 240,
                                },
                            },
                        },
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "workItemId"],
                "properties": {
                    "op": {"const": "accept"},
                    "workItemId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "workItemId", "reason"],
                "properties": {
                    "op": {"const": "return"},
                    "workItemId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                    "reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2_000,
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "workItemId", "phase"],
                "properties": {
                    "op": {"const": "resume"},
                    "workItemId": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 240,
                    },
                    "phase": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 120,
                    },
                    "timeoutSeconds": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 300,
                    },
                },
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "content"],
                "properties": {
                    "op": {"const": "post"},
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8_000,
                    },
                    "kind": {
                        "type": "string",
                        "enum": [
                            "progress",
                            "result",
                            "work_result",
                            "review_result",
                            "handoff",
                            "wait",
                            "blocked",
                        ],
                    },
                },
            },
        ],
    },
'''
    text = replace_between(
        text,
        '    "room_partner": {',
        '    "planning": {',
        schema,
        label="room_partner runtime schema",
    )
    write(path, text)


def patch_room_projection() -> None:
    path = "control-center-web/src/features/rooms/runtime/room-execution-lanes.ts"
    text = read(path)
    text = replace_once(
        text,
        "  phaseName: string;\n  parallelIndex?: number;",
        "  phaseName: string;\n  workItemId: string;\n  parallelIndex?: number;",
        label="RoomExecutionLane workItemId field",
    )
    text = replace_once(
        text,
        " * Explicit WorkItems are optional in the light Room architecture. The task\n"
        " * view must therefore derive its primary state from the same Room event\n"
        " * projection as the conversation timeline instead of presenting an active\n"
        " * collaboration as empty.",
        " * Conversation-only Room turns may have no WorkItem, but every formal\n"
        " * room_partner delegation carries a durable workItemId. The task view still\n"
        " * derives runtime state from the ordered Room event projection and joins the\n"
        " * exact authority record instead of guessing by partner identity.",
        label="Room execution authority comment",
    )
    text = replace_once(
        text,
        "      waveId: textValue(activity.payload.waveId),\n"
        "      phaseName: textValue(activity.payload.phaseName),",
        "      waveId: textValue(activity.payload.waveId),\n"
        "      phaseName: textValue(activity.payload.phaseName),\n"
        "      workItemId: textValue(activity.payload.workItemId),",
        label="Room lane initial workItemId",
    )
    text = replace_once(
        text,
        "    lane.phaseName ||= textValue(activity.payload.phaseName);\n"
        "    lane.parallelIndex ??= numberValue(activity.payload.parallelIndex);",
        "    lane.phaseName ||= textValue(activity.payload.phaseName);\n"
        "    lane.workItemId ||= textValue(activity.payload.workItemId);\n"
        "    lane.parallelIndex ??= numberValue(activity.payload.parallelIndex);",
        label="Room lane accumulated workItemId",
    )
    missing_pattern = "      phaseName: '',\n      participantId:"
    missing_count = text.count(missing_pattern)
    if missing_count < 2:
        raise RuntimeError(
            f"Room lane fallback workItemId: expected at least two matches, found {missing_count}"
        )
    text = text.replace(
        missing_pattern,
        "      phaseName: '',\n      workItemId: '',\n      participantId:",
    )
    write(path, text)

    path = "control-center-web/src/features/rooms/RoomTaskGraph.tsx"
    text = read(path)
    old = (
        "      const availableWorkItems = partner.workItems.filter((item) => !usedWorkItemIds.has(item.id));\n"
        "      const workItem = availableWorkItems.length === 1 ? availableWorkItems[0] : undefined;\n"
        "      if (workItem) usedWorkItemIds.add(workItem.id);"
    )
    new = (
        "      const exactWorkItem = lane.workItemId\n"
        "        ? partner.workItems.find((item) => item.id === lane.workItemId)\n"
        "        : undefined;\n"
        "      const availableWorkItems = partner.workItems.filter((item) => !usedWorkItemIds.has(item.id));\n"
        "      const workItem = exactWorkItem\n"
        "        ?? (availableWorkItems.length === 1 ? availableWorkItems[0] : undefined);\n"
        "      if (workItem) usedWorkItemIds.add(workItem.id);"
    )
    text = replace_once(
        text,
        old,
        new,
        label="Room graph exact WorkItem join",
    )
    write(path, text)


def patch_architecture() -> None:
    path = "ARCHITECTURE.md"
    text = read(path)
    text = replace_once(
        text,
        "Room path\n  user Room message -> coordinator Pi Session\n"
        "  -> optional room_partner -> partner Pi Session\n"
        "  -> optional agents -> private Tool Agent Session\n"
        "  -> child/partner event result -> coordinator integration\n"
        "  -> one coordinator final + Root terminal event",
        "Room path\n  user Room message -> coordinator Pi Session\n"
        "  -> formal room_partner -> PAW WorkItem + Pi partner Session\n"
        "  -> optional agents -> private Tool Agent Session\n"
        "  -> Partner evidence -> WorkItem review -> accept/return\n"
        "  -> one coordinator final after authoritative WorkItems close\n"
        "  -> Root terminal event",
        label="Architecture Room path",
    )
    text = replace_once(
        text,
        "  -> optional room_partner dispatch\n"
        "     -> partner participant's Pi Session",
        "  -> formal room_partner dispatch\n"
        "     -> durable WorkItem assignment + dependency gate\n"
        "     -> partner participant's Pi Session",
        label="Architecture light Room dispatch",
    )
    text = replace_once(
        text,
        "     -> partner terminal event back to the same Root\n"
        "  -> coordinator integrates the returned evidence\n"
        "  -> one coordinator final + one Root terminal event",
        "     -> partner terminal event back to the same Root\n"
        "     -> WorkItem enters review; return is not acceptance\n"
        "  -> coordinator accepts or returns the evidence\n"
        "  -> one coordinator final only after open WorkItems close\n"
        "  -> one Root terminal event",
        label="Architecture Room review chain",
    )
    text = replace_once(
        text,
        "Pi continues to own transcript persistence, model and Tool loops, context\n"
        "compaction, Steer, Stop, and Session recovery. Room adds only the collaboration\n"
        "facts that Pi does not own: Room and participant identity, topic, explicit\n"
        "dispatches, ordered public events, cancellation fan-out, and one terminal Root.",
        "Pi continues to own transcript persistence, model and Tool loops, context\n"
        "compaction, Steer, Stop, and Session recovery. Room adds only the collaboration\n"
        "facts that Pi does not own: Room and participant identity, topic, WorkItems,\n"
        "dependency gates, explicit dispatches, review decisions, ordered public events,\n"
        "cancellation fan-out, and one terminal Root.",
        label="Architecture ownership boundary",
    )
    text = replace_once(
        text,
        "- **Optional reviewer:** either a Partner or Tool Agent selected by the\n"
        "  coordinator when risk warrants it. Review is not a mandatory Kernel gate.",
        "- **Reviewer:** the accountable Room participant for a formal WorkItem. A\n"
        "  Partner Session return supplies evidence but never closes the WorkItem; the\n"
        "  reviewer explicitly accepts or returns it. Independent review remains a\n"
        "  risk-based workflow choice rather than a second Kernel.",
        label="Architecture reviewer boundary",
    )
    text = replace_once(
        text,
        "The Control Center conversation and task views reduce the same ordered Room\n"
        "snapshot/SSE stream. The task view projects real public Roots and their\n"
        "participants/tool steps; explicit `workItems` are optional additive records.\n"
        "It must not show an empty task page while a Root is running, and it must not\n"
        "infer a running Root from an unrelated participant Session.",
        "The Control Center conversation and task views reduce the same ordered Room\n"
        "snapshot/SSE stream. Conversation-only turns may have no WorkItem, but every\n"
        "formal `room_partner` delegation publishes an exact `workItemId`. The task view\n"
        "joins that authority record to the real dispatch/wave events and never guesses\n"
        "parallelism or acceptance from partner count. It must not show an empty task\n"
        "page while a Root is running, and it must not infer a running Root from an\n"
        "unrelated participant Session.",
        label="Architecture public WorkItem projection",
    )
    text = replace_once(
        text,
        "| Light Room | `rag_ime/agent_rooms.py`, `rag_ime/agent_room_turn_registry.py`, Room methods in `agent_service.py` | Room identity, participants, topics, explicit dispatch mapping, public event order, cancellation fan-out, one Root terminal | Pi loop, document quality gates, mandatory review |",
        "| Room workflow | `rag_ime/agent_rooms.py`, `rag_ime/agent_room_turn_registry.py`, `rag_ime/agent_room_partner_workflow.py`, `rag_ime/agent_room_work.py` | Room identity, participants, phases, dependencies, WorkItems, explicit dispatch mapping, review, public event order, cancellation fan-out, one Root terminal | Pi loop, private Session transcript, Tool loop, model cancellation |",
        label="Architecture owner table",
    )
    write(path, text)


def main() -> None:
    patch_agent_service()
    patch_room_work_parallel_limit()
    patch_agent_tools()
    patch_room_projection()
    patch_architecture()
    print("authoritative Room workflow patch applied")


if __name__ == "__main__":
    main()
