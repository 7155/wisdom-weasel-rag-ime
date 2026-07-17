from __future__ import annotations


ASSISTANT_CONTROL_TOOL_IDS = (
    "ime_overview",
    "ime_input",
    "ime_voice",
    "ime_planning",
    "ime_memory",
    "ime_knowledge",
    "ime_models",
    "ime_runtime",
    "ime_configuration",
    "ime_agents",
    "ime_browser",
    "agent_plan",
    "agent_schedule",
    "desktop_semantic",
)

COORDINATOR_TOOL_IDS = (
    "workspace_list",
    "workspace_read",
    "workspace_search",
    "workspace_patch",
    "workspace_shell",
)

CONTROL_TOOL_IDS = (*ASSISTANT_CONTROL_TOOL_IDS, *COORDINATOR_TOOL_IDS)
