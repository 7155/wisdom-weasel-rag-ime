from __future__ import annotations

from .adapter import InputMethodAdapter
from .models import AgentContextInjection


def build_first_run_injection(
    adapter: InputMethodAdapter,
    *,
    project: str = "wisdom-weasel-rag-ime",
    query: str = "当前项目背景 用户偏好 最近决策 禁止事项 推荐下一步",
    top_k: int = 5,
) -> AgentContextInjection:
    """Build the local project memory block for an agent first run."""

    return adapter.agent_context(project=project, query=query, top_k=top_k)
