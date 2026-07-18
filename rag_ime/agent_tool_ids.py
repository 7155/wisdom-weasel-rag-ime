from __future__ import annotations


ASSISTANT_CONTROL_TOOL_IDS = (
    "ime_overview",
    "ime_input",
    "ime_voice",
    "ime_planning",
    "ime_memory",
    "agent_role_book",
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

CONTROL_CENTER_TOOL_PROFILE = "control-center-v1"
READONLY_TOOL_PROFILE = "subagent-readonly-v1"
WORKER_TOOL_PROFILE = "subagent-worker-v1"
SURFACE_TOOL_PROFILE = "ime-surface-v1"
VOICE_REFINEMENT_TOOL_PROFILE = "voice-refinement-v1"
DANGEROUS_AUTO_APPROVE_TOOL_PROFILE = "control-center-auto-approve-v1"
DANGEROUS_MODE_CONFIRMATION = "AUTO_APPROVE_ALL"

SUPPORTED_AGENT_TOOL_PROFILES = frozenset(
    {
        CONTROL_CENTER_TOOL_PROFILE,
        READONLY_TOOL_PROFILE,
        WORKER_TOOL_PROFILE,
        SURFACE_TOOL_PROFILE,
        VOICE_REFINEMENT_TOOL_PROFILE,
        DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
    }
)
