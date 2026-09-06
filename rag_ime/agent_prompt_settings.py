"""User-owned prompt additions; Pi still owns the Session and compaction loop."""
from __future__ import annotations

from collections.abc import Mapping

MAX_PROMPT_CHARS = 8_000
DEFAULT_COMPACTION_INSTRUCTIONS = """保留 Pi 要求的摘要结构，只生成接续摘要，不继续任务、不调用工具，也不为了压缩而写文档。

保留当前目标、最新用户纠正、适用范围与验收条件；区分整个任务和当前 Agent 的责任。
已经核对并落盘的稳定规则、决定和结果，用准确的文档路径、章节或稳定 ID 加一句用途索引；已有 revision 时保留它，不复制整份 docs，不虚构未读取的文档。
当接续所需信息以文档索引代替正文时，在摘要的 Next Steps 中明确告知接续 Agent 应先读取的文档、章节及用途，以恢复当前需求、约束或证据；已充分保留的信息不重复读取，不要求重读全部 docs。涉及多个 worktree 时，保留当前绑定工作区的准确路径；关键反馈有稳定 ID 或 revision 时一并保留，不猜测缺失标识。
完整保留尚未落盘的重要决定、限制、未完成项、阻塞条件、进行中的工具或子任务，以及唯一明确的下一步。文档缺失、不可读或是否已更新不确定时，保留接续所需的事实，不只留下路径。
保留已完成动作的关键回执、失败尝试和不确定的执行结果；不要把计划当已实施、把待验收当通过，也不要重放已完成或结果不明的写入。
文档与摘要只保存语义和上次观察；运行状态、权限、WorkItem revision 和当前文件状态在继续前按需从 Runtime / 工作区核对。最新用户纠正优先，已完成、取消或被替代的工作不重新激活。
保持简短，删除重复叙述、原始工具输出和无关历史。不要新造目标、补写指标或猜测缺失证据。"""


def default_prompt_settings() -> dict[str, str]:
    return {"systemInstructions": "", "compactionInstructions": DEFAULT_COMPACTION_INSTRUCTIONS}


def prompt_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if len(value) > MAX_PROMPT_CHARS:
        raise ValueError(f"{field} must contain at most {MAX_PROMPT_CHARS} characters")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        raise ValueError(f"{field} contains unsupported control characters")
    return value


def normalize_prompt_settings(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"systemInstructions", "compactionInstructions"}:
        raise ValueError("agent prompt settings fields are invalid")
    return {name: prompt_text(value[name], field=f"prompts.{name}") for name in ("systemInstructions", "compactionInstructions")}


def prompt_settings_catalog() -> dict[str, object]:
    from .agent_core_policy import base_agent_safety_policy_prompt, core_agent_policy_prompt
    from .agent_templates import progressive_capability_policy

    return {
        "schemaVersion": "rag-ime.agent-prompt-policy.v1",
        "appliesTo": "new_sessions",
        "maxCharacters": MAX_PROMPT_CHARS,
        "defaults": default_prompt_settings(),
        "builtInSystemPrompt": "\n\n".join((core_agent_policy_prompt(base_agent_safety_policy_prompt(), {}), progressive_capability_policy())),
        "compactionOwner": "pi",
    }
