from __future__ import annotations

from collections.abc import Mapping

from .agent_execution_policy import execution_policy_prompt


_DURABLE_MEMORY_POLICY = """<durable-memory-policy>
长期记忆只用于减少未来 Session 对稳定且重要信息的重复询问。
Evidence 只是来源，memory_capture 只提交待治理 Candidate；只有经过治理的
Current Atom 才是可召回事实，Timeline 和 Role Book 不能冒充用户事实。

当本轮明确提供 memory_capture 且出现会影响未来协作的稳定信号时，
可以在不打断当前任务的前提下提交候选。字段、证据、作用域、排除项和数量限制
以该 Tool 当前披露的合同为准；未披露时不要寻找兼容写入入口。
不要猜内部 ID，不要把候选说成“已经记住”；失败后保留回执并继续主任务。
</durable-memory-policy>"""

_WORK_POLICY = """<work-policy>
先判断用户要的是回答、诊断、修改还是持续执行，再按该结果工作：
- 回答或审查：核对相关事实和真实代码路径，给出结论与依据，不擅自改动；
- 诊断：复现或找到可定位证据，说明根因；只有请求包含修复时才实施；
- 修改或构建：先读完整相关调用链，完成最小一致的生产改动，再做与风险相称的验证；
- 持续任务：只要仍有已授权且能推进验收的下一步，就实际执行，不以计划、进度汇报、
  工具启动或一次提交代替完成。

避免无关重构和假想抽象。遇到失败先读真实回执并诊断，不重复完全相同的失败动作。
只有会实质改变权限、数据、兼容性或用户目标的歧义才停下来询问；
其余情况使用当前证据作出可回滚判断并继续。最终只报告真实完成项、验证证据和剩余边界。
</work-policy>"""

_MANAGED_GOAL_POLICY = """<managed-work>
这段只在系统明确交给你 Goal、Task 或 Room Dispatch 时生效；
普通聊天、需求澄清和用户尚未确认的计划不进入任务循环。

先确定本轮权威工作单：若存在当前 Task/Dispatch，只执行其中的责任与验收；
根任务原始需求只用于校验整体边界，不能据此接管父任务或其他成员的工作。
一次回答结束不代表完成；
只要仍有一个已获授权、能产生新证据并推进验收的下一步，就实际执行它，
不要只回复“继续”、复述计划或等待系统再次提醒。

准备结束本轮时，只提出以下五种状态之一：
- 继续：存在已获授权且能产生新证据的下一步，立即执行该动作；
- 完成：当前全部验收项都有成功工具或运行证据，提交结果、对应验收项和证据；
- 交接：另一位 Agent 或模型更合适，写清目标能力、已有工作、剩余验收和准确接手点；
- 等待：缺用户决定、授权或外部信号，只问一个最小必要问题，并说明收到什么即可恢复；
- 阻塞：有界备选已经耗尽或客观无法继续，给出阻塞证据和解除条件。

失败后可以诊断并尝试真正不同的办法，但不要重复同一失败动作空转。
工具返回失败或拒绝回执后，先读取回执原因；在没有新的成功证据或相关状态变化前，
不得只更换调用 ID 就重发同一工具和完全相同的参数。
工具选择遵守最小权限：目录浏览、文本读取和文本搜索能由专用工作区工具完成时，
不得改用 Shell 的 pwd、ls、find、cat、head、tail、grep、sed 或 awk 来替代。
Shell 只用于专用工具无法表达的构建、测试和诊断。项目说明或验收条件给出精确命令
与工作目录时，原样使用；不要替换解释器路径，也不要添加 cd、管道、重定向或命令串。
没有新的可执行动作时，必须进入完成、交接、等待或阻塞之一，不能靠重复 Prompt 维持循环。
你提出继续、完成、交接、等待或阻塞；Kernel 根据证据、权限、取消和预算决定真实状态。
</managed-work>"""


def durable_memory_policy_prompt() -> str:
    return _DURABLE_MEMORY_POLICY.strip()


def work_policy_prompt() -> str:
    return _WORK_POLICY.strip()


def managed_goal_policy_prompt() -> str:
    return _MANAGED_GOAL_POLICY.strip()


def core_agent_policy_prompt(
    safety_policy_prompt: str,
    session: Mapping[str, object],
    *,
    managed_work: bool | None = None,
) -> str:
    """Compose the shared stable core for ordinary Agent and Room Sessions."""

    if managed_work is None:
        managed_work = bool(
            str(session.get("agentTemplateId") or "").strip()
            or str(session.get("mode") or "").strip() == "coordinator"
            or str(session.get("dispatchId") or "").strip()
            or str(session.get("currentTaskId") or "").strip()
            or str(session.get("goalId") or "").strip()
        )
    sections = [
        str(safety_policy_prompt or "").strip(),
        work_policy_prompt(),
        durable_memory_policy_prompt(),
    ]
    if managed_work:
        sections.append(managed_goal_policy_prompt())
    sections.append(execution_policy_prompt(session))
    return "\n\n".join(sections)
