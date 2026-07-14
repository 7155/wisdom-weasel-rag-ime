from __future__ import annotations

from dataclasses import dataclass

from .contracts.json_schema import validate_contract


@dataclass(frozen=True)
class AgentTemplateBudget:
    max_depth: int = 2
    max_turns: int = 8
    max_tool_calls: int = 12
    max_total_tokens: int = 32_000
    max_duration_ms: int = 300_000
    max_output_chars: int = 12_000

    def to_payload(self) -> dict[str, int]:
        return {
            "maxDepth": self.max_depth,
            "maxTurns": self.max_turns,
            "maxToolCalls": self.max_tool_calls,
            "maxTotalTokens": self.max_total_tokens,
            "maxDurationMs": self.max_duration_ms,
            "maxOutputChars": self.max_output_chars,
        }


@dataclass(frozen=True)
class AgentTemplate:
    template_id: str
    version: str
    display_name: str
    summary: str
    prompt: str
    tool_profile_version: str
    capabilities: tuple[str, ...]
    context_modes: tuple[str, ...] = ("fresh", "fork")
    budget: AgentTemplateBudget = AgentTemplateBudget()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-template.v1",
            "templateId": self.template_id,
            "version": self.version,
            "displayName": self.display_name,
            "summary": self.summary,
            "contextModes": list(self.context_modes),
            "toolProfileVersion": self.tool_profile_version,
            "budget": self.budget.to_payload(),
            "capabilities": list(self.capabilities),
        }
        validate_contract(payload, "agent-template.v1.json")
        return payload


_READ_ONLY_BUDGET = AgentTemplateBudget(
    max_depth=2,
    max_turns=8,
    max_tool_calls=12,
    max_total_tokens=32_000,
    max_duration_ms=300_000,
    max_output_chars=12_000,
)

_WORKER_BUDGET = AgentTemplateBudget(
    max_depth=2,
    max_turns=12,
    max_tool_calls=20,
    max_total_tokens=48_000,
    max_duration_ms=420_000,
    max_output_chars=16_000,
)

_TEMPLATES = (
    AgentTemplate(
        template_id="researcher",
        version="1",
        display_name="研究员",
        summary="围绕一个问题检索本地知识、记忆与近期记录，形成证据化研究摘要。",
        prompt="""你是受限研究子 Agent。围绕任务拆出少量检索角度，优先调用本地知识和记忆工具核对事实，再返回简洁的发现、证据和缺口。不要执行写操作，不要声称访问了未提供的网页、文件或系统。""",
        tool_profile_version="subagent-readonly-v1",
        capabilities=("rag", "memory", "delegation"),
        budget=_READ_ONLY_BUDGET,
    ),
    AgentTemplate(
        template_id="planner",
        version="1",
        display_name="规划师",
        summary="把现有上下文和证据整理为有依赖、风险与验收条件的执行计划。",
        prompt="""你是规划子 Agent。先核对给定上下文和可用证据，然后给出小步、可验证、有依赖关系的计划。不要修改任何状态；不确定的事实必须标为缺口，不能用猜测补齐。""",
        tool_profile_version="subagent-readonly-v1",
        capabilities=("planning", "rag", "memory", "delegation"),
        budget=_READ_ONLY_BUDGET,
    ),
    AgentTemplate(
        template_id="worker",
        version="1",
        display_name="执行者",
        summary="在控制中心已有工具范围内推进明确任务，所有写入仍经过原生审批。",
        prompt="""你是执行子 Agent。只处理已经明确授权的任务，优先做最小正确动作并核对结果。你没有任意文件或 Shell 权限；任何设置、任务、记忆或运行时写操作都必须使用原生审批回执。""",
        tool_profile_version="subagent-worker-v1",
        capabilities=("control", "rag", "memory", "delegation"),
        budget=_WORKER_BUDGET,
    ),
    AgentTemplate(
        template_id="reviewer",
        version="1",
        display_name="审阅者",
        summary="独立检查结论、计划或执行结果，指出有证据的问题和剩余风险。",
        prompt="""你是只读审阅子 Agent。根据任务、上下文和工具证据检查正确性、遗漏、风险与验证强度。 findings 优先，只报告能由证据支持的问题；不要修改状态。""",
        tool_profile_version="subagent-readonly-v1",
        capabilities=("review", "rag", "memory", "delegation"),
        budget=_READ_ONLY_BUDGET,
    ),
    AgentTemplate(
        template_id="delegate",
        version="1",
        display_name="协作者",
        summary="处理不属于其他专门模板的有界只读任务，并把结果交回主持会话。",
        prompt="""你是通用受限协作子 Agent。聚焦用户交付的单一任务，按需核对本地证据并返回清晰结果。不要扩大范围、修改状态或把自己当成长期群聊成员。""",
        tool_profile_version="subagent-readonly-v1",
        capabilities=("rag", "memory", "delegation"),
        budget=_READ_ONLY_BUDGET,
    ),
)

_BY_ID = {(item.template_id, item.version): item for item in _TEMPLATES}


def agent_template(template_id: object, version: object = "1") -> AgentTemplate:
    key = (str(template_id or "").strip(), str(version or "1").strip())
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported agent template: {key[0] or '<empty>'}@{key[1] or '<empty>'}"
        ) from exc


def agent_template_catalog() -> list[dict[str, object]]:
    return [item.to_payload() for item in _TEMPLATES]
