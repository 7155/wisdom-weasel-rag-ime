from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiScenario:
    scenario_id: str
    title: str
    recent_context: str
    current_input: str
    project: str = "wisdom-weasel-rag-ime"


SCENARIOS: tuple[UiScenario, ...] = (
    UiScenario(
        scenario_id="interview-project-intro",
        title="写面试项目介绍",
        recent_context="这个输入法项目不是普通 RAG 问答, 它把用户输入过程变成记忆治理入口",
        current_input="我这个项目的亮点是",
    ),
    UiScenario(
        scenario_id="technical-plan",
        title="写技术方案",
        recent_context="MVP 先 local-first, 不接云端 GPT, 先验证检索和排序",
        current_input="SQLite 和 FTS5 第一版",
    ),
    UiScenario(
        scenario_id="project-term-agent-hook",
        title="输入项目专有名词/固定表达",
        recent_context="RAG 输入法后续要和 coding agent 的首次运行上下文对齐",
        current_input="Agent 首次运行",
    ),
)


def get_scenario(scenario_id: str) -> UiScenario:
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    known = ", ".join(scenario.scenario_id for scenario in SCENARIOS)
    raise KeyError(f"unknown scenario_id: {scenario_id}. known: {known}")
