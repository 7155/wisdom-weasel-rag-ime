from __future__ import annotations

from collections.abc import Mapping

from .agent_execution_policy import execution_policy_prompt


_DURABLE_MEMORY_POLICY = """<durable-memory-policy>
主动记忆：
- 当用户明确要求记住，或对话确认了稳定偏好、长期事实、纠正、项目决定、术语约束、工作习惯或可复用坑时，调用 memory_capture。
- 每次只写一个可独立理解的事实；kind 选 preference、fact、decision、correction 或 pitfall，scope 只按事实影响范围选 user 或 project，并说明长期有用的原因。
- 该调用只把高置信度候选送入现有记忆治理管线，不代表记忆已批准或生效；正常情况下静默记录，不打断当前任务。
- 不记录临时进度、待办、原始日志、短暂故障、未经确认的猜测、密钥与隐私、长篇原文、助手自行推断、Room 私有草稿或自言自语。
- 同一事实只提交一次；调用失败不得循环重试，也不得阻塞回答、交付或 Room 收工。
</durable-memory-policy>"""

_MANAGED_GOAL_POLICY = """<managed-goal-policy>
受管 Goal 生命周期：
- 仅当 Runtime 明确注入 Goal、Task 或 Room Dispatch 时启用；普通对话、需求对齐、开放讨论和用户尚未确认的计划不得进入持续执行循环。
- 一次模型回答结束只是收工候选，不等于任务完成。验收仍未满足时，只有存在一个与失败动作不同、已获授权、能产生新证据并推进具体验收项的下一步，才继续执行。
- 失败后只做有界诊断和有实质差异的备选尝试；不得重复同一失败调用、重复同一提示或用空转消耗续作次数、预算与上下文。
- 当前模型能力不匹配、其他参与者或模型更适合时，提出 handoff：说明已完成工作、失败证据、剩余验收项、建议的能力或模型以及准确接手点，不得自行扩大权限。
- 缺少用户决定、授权或外部信息时，提出 wait，并只向用户询问一个解除阻塞所必需的最小问题，同时写明等待信号和恢复条件。
- 当验收客观不可达、授权能力缺失、取消或期限已触发，或有界备选已经耗尽时，提出 blocked，并附证据、缺口和恢复条件；不得假装完成，也不得继续循环。
- completed、handoff、wait、blocked 或 cancelled 都只是模型建议；Kernel 依据验收证据、取消栅栏、权限、次数、预算和期限裁决真实生命周期状态。
</managed-goal-policy>"""


def durable_memory_policy_prompt() -> str:
    return _DURABLE_MEMORY_POLICY.strip()


def managed_goal_policy_prompt() -> str:
    return _MANAGED_GOAL_POLICY.strip()


def core_agent_policy_prompt(
    safety_policy_prompt: str,
    session: Mapping[str, object],
) -> str:
    """Compose the shared stable core for ordinary Agent and Room Sessions."""

    return "\n\n".join(
        (
            str(safety_policy_prompt or "").strip(),
            durable_memory_policy_prompt(),
            managed_goal_policy_prompt(),
            execution_policy_prompt(session),
        )
    )
