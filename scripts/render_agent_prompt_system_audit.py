#!/usr/bin/env python3
"""Render a reviewable inventory of every Agent-facing prompt surface.

This source audit records the exact stable prompt text, representative dynamic
projections, Skill bodies, Tool manifests, and prompt-producing symbols. When
deterministic Provider-object audits exist, it links their evidence without
misrepresenting them as external Provider or real KV-cache proof.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _canonical_repository(root: Path) -> Path | None:
    """The repository that owns `root`'s Git metadata, or None.

    A physical worktree's paths are relative to wherever the worktree was
    created, but Git's common directory always belongs to the canonical
    checkout. Returns None when Git is missing, errors, or the answer is
    unusable, so callers can preserve their historical path behaviour
    instead of failing at import.
    """

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common_dir = result.stdout.strip()
    if result.returncode != 0 or not common_dir:
        return None
    repository = Path(common_dir).parent
    return repository if repository.is_dir() else None


def _sibling_repository_root(root: Path) -> Path:
    """Directory holding the sibling audit repositories.

    The siblings live next to the canonical checkout, so `root.parent` is
    only correct when `root` IS the canonical checkout. In a physical Git
    worktree (`<siblings>/<repo>/.worktrees/<name>` or any other location),
    `root.parent` points somewhere else entirely, which is what produced the
    `exists: False` audit failures.
    """

    repository = _canonical_repository(root)
    return repository.parent if repository is not None else root.parent


def _configured_sibling_repository_root(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve sibling repositories, with an explicit standalone-clone override.

    Release/acceptance clones can live away from the product's sibling source
    repositories, so Git's common directory cannot discover Pi, Cat Cafe, or
    VCPToolBox.  The opt-in override keeps that boundary explicit and absolute;
    without it, the historical canonical-checkout/worktree resolution remains
    unchanged and missing references still fail closed in the audit.
    """

    environment = os.environ if environ is None else environ
    configured = str(environment.get("RAG_IME_AUDIT_SIBLING_ROOT") or "").strip()
    if not configured:
        return _sibling_repository_root(root)
    override = Path(configured).expanduser()
    if not override.is_absolute():
        raise ValueError("RAG_IME_AUDIT_SIBLING_ROOT must be an absolute path")
    return override


def _deterministic_evidence_root(root: Path) -> Path:
    """Where the machine-local deterministic Provider evidence lives.

    The evidence directory is gitignored, so a physical worktree normally has
    only the tracked audit report. Prefer a worktree-local directory only when
    it contains captured Provider evidence; otherwise use the canonical
    checkout's capture. This keeps source-only worktrees portable without
    silently dropping runtime prompt ledger entries.
    """

    relative = Path("docs") / "agent" / "audits" / "agent-prompt-system-current"
    scenario_directories = (
        "provider-agent-deterministic",
        "provider-room-deterministic",
    )

    def has_provider_evidence(directory: Path) -> bool:
        for scenario in scenario_directories:
            scenario_root = directory / scenario
            if (scenario_root / "audit.json").is_file():
                return True
            calls_root = scenario_root / "calls"
            if calls_root.is_dir() and next(calls_root.glob("*.json"), None) is not None:
                return True
        return False

    local = root / relative
    if has_provider_evidence(local):
        return local
    repository = _canonical_repository(root)
    canonical = repository / relative if repository is not None else None
    if canonical is not None and has_provider_evidence(canonical):
        return canonical
    return local


def _configured_deterministic_evidence_root(
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve ignored runtime evidence for a standalone acceptance clone."""

    environment = os.environ if environ is None else environ
    configured = str(environment.get("RAG_IME_AUDIT_EVIDENCE_ROOT") or "").strip()
    if not configured:
        return _deterministic_evidence_root(root)
    override = Path(configured).expanduser()
    if not override.is_absolute():
        raise ValueError("RAG_IME_AUDIT_EVIDENCE_ROOT must be an absolute path")
    return override


_SIBLING_ROOT = _configured_sibling_repository_root(ROOT)
DEFAULT_PI_ROOT = _SIBLING_ROOT / "pi-rag-ime-runtime"
DEFAULT_CAFE_ROOT = _SIBLING_ROOT / "clowder-ai"
DEFAULT_VCP_ROOT = _SIBLING_ROOT / "VCPToolBox"
DETERMINISTIC_EVIDENCE_ROOT = _configured_deterministic_evidence_root(ROOT)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_prompt_audit_html import render_audit_html  # noqa: E402
from rag_ime.agent_approval_model import (  # noqa: E402
    APPROVAL_MODEL_PROMPT_VERSION,
    _arbiter_prompt,
    _model_input,
)
from rag_ime.agent_core_policy import (  # noqa: E402
    core_agent_policy_prompt,
    durable_memory_policy_prompt,
    managed_goal_policy_prompt,
    todo_policy_prompt,
    work_policy_prompt,
)
from rag_ime.agent_definitions import (  # noqa: E402
    collaboration_profile,
    collaboration_profile_catalog,
    collaboration_role,
    collaboration_role_catalog,
)
from rag_ime.agent_delegation import _subagent_prompt  # noqa: E402
from rag_ime.agent_execution_policy import (  # noqa: E402
    execution_policy_prompt,
    workspace_scope_sha256,
)
from rag_ime.agent_prompt_plans import (  # noqa: E402
    PROMPT_LAYER_SPECS,
    PromptLayer,
    _compile_layers,
    _provider_layer_prompt,
    compose_persona_layer,
)
from rag_ime.agent_role_book import compile_role_book_prompt  # noqa: E402
from rag_ime.agent_roles import agent_role, agent_role_catalog  # noqa: E402
from rag_ime.agent_room_capabilities import (  # noqa: E402
    ROOM_PUBLIC_TOOLS,
    room_runtime_registry,
)
from rag_ime.agent_room_kernel_worker import _default_dispatch_message  # noqa: E402
from rag_ime.agent_room_prompt_context import (  # noqa: E402
    room_intercom_prompt,
    room_participant_prompt,
)
from rag_ime.agent_room_runtime_coordinator import (  # noqa: E402
    _profile_overlay_prompt,
)
from rag_ime.agent_room_recovery_context import (  # noqa: E402
    room_compaction_recovery_context,
)
from rag_ime.agent_room_settlement import RoomSettleLifecycleService  # noqa: E402
from rag_ime.agent_templates import (  # noqa: E402
    agent_template,
    agent_template_catalog,
    progressive_capability_policy,
)
from rag_ime.agent_prompt_support import deep_search_prompt  # noqa: E402
from rag_ime.agent_surface_runtime import (  # noqa: E402
    _one_shot_surface_message,
    _voice_refinement_prompt,
)
from rag_ime.agent_tools import ControlToolGateway  # noqa: E402
from rag_ime.deepseek_completion import (  # noqa: E402
    DeepSeekCompletionRequest,
    build_deepseek_completion_messages,
)
from rag_ime.deepseek_config import DeepSeekConfig  # noqa: E402
from rag_ime.deepseek_memory_organizer import (  # noqa: E402
    DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION,
    _memory_book_recovery_prompt,
    _memory_book_system_prompt,
    _memory_curation_recovery_prompt,
    _memory_curation_system_prompt,
    _owner_memory_recovery_prompt,
    _owner_memory_system_prompt,
    _phrase_pinyin_repair_system_prompt,
    _role_book_curation_system_prompt,
)
from rag_ime.knowledge_library.graph_extractors import (  # noqa: E402
    OpenAICompatibleGraphExtractor,
)
from rag_ime.knowledge_workbench import (  # noqa: E402
    KnowledgeWorkbenchRequest,
    build_knowledge_workbench_messages,
)
from rag_ime.memory_generator import (  # noqa: E402
    _core_optimization_system_prompt,
    _memory_generation_system_prompt,
)
from rag_ime.historical_memory_curation import (  # noqa: E402
    DEFAULT_HISTORICAL_CURATION_INSTRUCTION,
)
from rag_ime.mlx_predictor_server import (  # noqa: E402
    _build_base_completion_prompt,
    _build_mlx_prompt,
    _build_no_input_space_list_prompt,
)
from rag_ime.pi_runtime import (  # noqa: E402
    PiRuntimeConfig,
    _IME_SURFACE_SYSTEM_PROMPT,
    _VOICE_REFINEMENT_SYSTEM_PROMPT,
    _session_mode_prompt,
)
from rag_ime.predictor import (  # noqa: E402
    PREDICTION_REQUEST_ACTIVE_RAG,
    PREDICTION_REQUEST_GENERIC,
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_RIME_REORDER,
    _openai_prediction_system_prompt,
    build_selected_text_rag_prompt,
)


SCHEMA_VERSION = "wisdom-weasel.agent-prompt-system-audit.v1"

PI_RUNTIME_PROMPT_PRODUCERS = {
    "coding-agent.skills": (
        "packages/coding-agent/src/core/skills.ts::formatSkillsForPrompt"
    ),
    "runtime.product-tools": (
        "packages/rag-ime-runtime-host/src/discovery-tools.ts::"
        "formatBackendToolRouteCatalog"
    ),
    "runtime.workflow": (
        "packages/rag-ime-runtime-host/src/workflow-control.ts::"
        "replaceWorkflowBlock"
    ),
    "runtime.provider-context": (
        "packages/rag-ime-runtime-host/src/provider-context-journal.ts::"
        "ProviderContextJournal"
    ),
    "runtime.manual-skill-load": (
        "packages/rag-ime-runtime-host/src/discovery-tools.ts::loadSkill"
    ),
    "runtime.compaction-skill-restore": (
        "packages/rag-ime-runtime-host/src/discovery-tools.ts::"
        "createDiscoveryToolsExtension.session_compact"
    ),
    "runtime.required-room-skill": (
        "packages/rag-ime-runtime-host/src/pi-session.ts::"
        "systemPromptOverride"
    ),
}

PROMPT_TITLE_OVERRIDES = {
    "agent.core.safety": "Agent 安全与权限硬边界",
    "agent.approval.model-arbiter-example": "Luna Max 无人值守审批裁决 Prompt 示例",
    "agent.core.work": "普通 Agent 请求分类与交付闭环",
    "agent.core.durable-memory": "长期记忆稳定治理边界",
    "agent.core.managed-work": "Goal、Task 与受管工作闭环",
    "agent.capabilities.progressive": "Skill 与 Tool 渐进披露协议",
    "agent.session.coordinator": "普通协调 Session 边界",
    "agent.session.assistant-zero": "普通 Assistant Session：零附加模式 Prompt",
    "agent.session.template-selected-zero": "已选模板 Session：零附加协调 Prompt",
    "agent.role-book.unpinned": "未固定 Role Book：零注入",
    "agent.role-book.pinned-example": "已固定 Role Book 示例",
    "agent.execution.workspace_managed.granted": "执行权限：工作区托管（范围已批准）",
    "agent.execution.full_trust.granted": "执行权限：完全信任（边界已批准）",
    "agent.composed.assistant-example": "普通 Agent 最终稳定 Prompt 示例",
    "agent.composed.coordinator-example": "协调 Agent 最终稳定 Prompt 示例",
    "room.dynamic.alignment-and-decision": "Room 执行前对齐与决策上下文",
    "room.dynamic.managed-task": "Room 当前受管任务上下文",
    "room.dynamic.intercom-question": "Room 成员间受管提问",
    "room.dynamic.intercom-reply": "Room 成员间受管答复",
    "room.dynamic.intercom-notice": "Room 成员间补充信息",
    "room.profile.guard-example": "已审核 Room Guard 叠加示例",
    "room.dispatch.trigger": "Kernel 启动或续作 Dispatch",
    "room.settle.continue": "收工前继续执行提示",
    "room.settle.repair": "非法提交修复提示",
    "room.compaction.recovery-example": "Room 压缩恢复包示例",
    "agent.delegation.subagent-example": "普通 Agent 子 Session 委派示例",
    "room.composed.stable-prefix-example": "Room 最终稳定 Prompt 前缀示例",
    "pi.runtime.skill-catalog.agent-example": "Pi 普通 Agent Skill 能力索引实测",
    "pi.runtime.skill-catalog.room-example": "Pi Room Skill 能力索引实测",
    "pi.runtime.tool-catalog.agent-example": "Pi 普通 Agent Tool 能力索引实测",
    "pi.runtime.tool-catalog.room-example": "Pi Room Tool 能力索引实测",
    "pi.runtime.workflow.agent-example": "Pi 普通 Agent Workflow 实测",
    "pi.runtime.workflow.room-example": "Pi Room Workflow 实测",
    "pi.runtime.session-memory.agent-example": "Pi 普通 Agent Session Memory 实测",
    "pi.runtime.room-context.room-example": "Pi Room 动态上下文实测",
    "pi.runtime.skill-load.tool-result.agent-example": "skill_load 当前 Epoch Tool Result 实测",
    "pi.runtime.skill-load.compaction-restore.agent-example": "压缩换代后 Skill 正文恢复实测",
    "pi.runtime.required-skill.room-example": "Room 必需 Skill 稳定前缀实测",
    "memory.default-instruction": "记忆整理默认任务说明",
    "memory.atom-curation": "原子记忆候选整理",
    "memory.atom-curation-recovery": "原子记忆整理恢复",
    "memory.book-compile": "Memory Book 编译",
    "memory.book-compile-recovery": "Memory Book 编译恢复",
    "memory.owner-curation": "用户画像记忆整理",
    "memory.owner-curation-recovery": "用户画像记忆整理恢复",
    "memory.role-book-curation": "Role Book 候选整理",
    "memory.phrase-pinyin-repair": "记忆短语拼音修复",
    "memory.historical-curation": "历史记忆迁移整理",
    "memory.legacy-distillation": "旧版记忆蒸馏兼容 Prompt",
    "memory.legacy-core-optimization": "旧版本地核心优化兼容 Prompt",
    "surface.ime-continuation": "旧 Active RAG Session System Prompt（兼容）",
    "surface.ime-continuation.request-example": "Active RAG Pi 单次请求示例",
    "surface.voice-refinement": "语音输入文本精修",
    "surface.voice-refinement.request-example": "语音输入精修请求示例",
    "surface.deepseek-post-commit.system": "输入法提交后 DeepSeek 候选系统 Prompt",
    "surface.deepseek-post-commit.user-example": "输入法提交后 DeepSeek 候选请求示例",
    "surface.deepseek-active-rag.system": "DeepSeek Active RAG 兼容系统 Prompt",
    "surface.deepseek-active-rag.user-example": "DeepSeek Active RAG 兼容请求示例",
    "surface.knowledge-workbench.system": "个人知识工作台系统 Prompt",
    "surface.knowledge-workbench.user-example": "个人知识工作台请求示例",
    "surface.knowledge-graph.system": "知识图谱抽取系统 Prompt",
    "surface.predictor.system_prompt": "本地 MLX 候选生成",
    "surface.predictor.stream_first_system_prompt": "本地 MLX 首候选流式生成",
    "surface.predictor.space_list_system_prompt": "本地 MLX 空输入候选生成",
    "surface.predictor.logits_system_prompt": "本地 MLX Logits 约束生成",
    "surface.predictor.openai_chat_system_prompt": "OpenAI 兼容预测器 Prompt",
    "surface.predictor.ollama_chat_system_prompt": "Ollama 兼容预测器 Prompt",
    "surface.predictor.ollama_stream_first_system_prompt": "Ollama 首候选兼容 Prompt",
    "surface.deep-search-example": "显式深度检索消息示例",
    "surface.selected-text-rag-example": "选中文本 RAG 消息示例",
    "surface.predictor.mlx-generic-example": "本地 MLX 请求体示例",
    "surface.predictor.mlx-no-input-example": "本地 MLX 空输入请求体示例",
    "surface.predictor.openai-generic_prediction": "OpenAI 兼容通用预测变体",
    "surface.predictor.openai-pinyin_constrained_prediction": "OpenAI 兼容拼音约束变体",
    "surface.predictor.openai-rime_reorder": "OpenAI 兼容 Rime 重排变体",
    "surface.predictor.openai-no_input_prediction": "OpenAI 兼容空输入变体",
    "surface.predictor.openai-active_rag": "OpenAI 兼容 Active RAG 变体",
}

MODEL_REQUEST_ROUTE_SPECS: tuple[dict[str, object], ...] = (
    {
        "id": "agent-session",
        "title": "普通 Agent Session",
        "sourceRoot": "pi",
        "sourcePath": "packages/rag-ime-runtime-host/src/pi-session.ts::PiSession",
        "reachability": "production",
        "owner": "Pi Runtime Host / AgentSession",
        "model": "当前 Session 选定的 Pi provider/model",
        "thinking": "当前 Session thinkingLevel；由所选模型能力约束",
        "transport": "Pi Provider adapter：systemPrompt + messages + active tool schemas",
        "systemInstruction": "present",
        "tools": "渐进披露；只发送当前已激活 schema",
        "promptIds": [
            "agent.composed.assistant-example",
            "agent.composed.coordinator-example",
            "pi.runtime.workflow.agent-example",
            "pi.runtime.session-memory.agent-example",
        ],
        "notes": "普通 Agent 与子 Session 共用此生命周期；是否协调由 Session/template 决定。",
    },
    {
        "id": "approval-model-arbiter",
        "title": "完全自动审批裁决",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/agent_approval_model.py::ApprovalModelArbiter.decide",
        "reachability": "production-conditional",
        "owner": "AgentService / ApprovalModelArbiter",
        "model": "openai-codex/gpt-5.6-luna（固定，不继承当前 Session）",
        "thinking": "固定 max",
        "transport": "Pi 无会话 completion.once：用户请求、当前任务、结构化审批历史、操作预览与决策协议；无 tools",
        "systemInstruction": "user-message instruction",
        "tools": "none",
        "promptIds": [
            "agent.approval.model-arbiter-example",
        ],
        "notes": (
            "仅在 full_trust 的待审批路径调用；Session 历史按 Session 隔离，Room 历史按 Room "
            "共享，且不包含主 Agent 输出。模型拒绝、超时、取消、协议错误和运行时错误均 "
            "fail closed，不执行原操作。"
        ),
    },
    {
        "id": "agent-deep-search",
        "title": "显式记忆深度检索",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/agent_prompt_application.py::AgentPromptApplication.deep_search",
        "reachability": "production-conditional",
        "owner": "AgentPromptApplication / ordinary Pi Agent Session",
        "model": "当前 Assistant Session 模型；没有可复用 Session 时使用默认模型档案",
        "thinking": "沿用目标 Agent Session 的 thinkingLevel",
        "transport": "普通 Pi Agent systemPrompt + 一条有界检索 user message + 当前已激活 tools",
        "systemInstruction": "present",
        "tools": "普通 Agent 常驻与渐进披露 Tool；写操作仍按 Session 权限审批",
        "promptIds": [
            "agent.composed.assistant-example",
            "surface.deep-search-example",
        ],
        "notes": (
            "显式入口复用当前 Assistant Session，或创建每日“记忆检索”Session；"
            "内部证据包不会作为用户可见历史或 fork 标题泄露。"
        ),
    },
    {
        "id": "room-participant",
        "title": "Room 成员 Session",
        "sourceRoot": "pi",
        "sourcePath": "packages/rag-ime-runtime-host/src/pi-session.ts::PiSession",
        "reachability": "production",
        "owner": "Room Kernel + Pi Runtime Host / AgentSession",
        "model": "每个成员 Session 选定的 Pi provider/model",
        "thinking": "每个成员自己的 thinkingLevel；Kernel 不伪造模型能力",
        "transport": "Pi Provider adapter：稳定 Room 前缀 + append-only Room context + messages + active tools",
        "systemInstruction": "present",
        "tools": "room_state、room_post、room_commit 常驻；其余按需披露",
        "promptIds": [
            "room.composed.stable-prefix-example",
            "room.dynamic.managed-task",
            "pi.runtime.room-context.room-example",
            "pi.runtime.required-skill.room-example",
        ],
        "notes": "任务终态由 Kernel 裁决；模型只提交当前验收别名与成功证据引用。",
    },
    {
        "id": "active-rag-pi",
        "title": "显式 Active RAG 文字生成",
        "sourceRoot": "pi",
        "sourcePath": "packages/rag-ime-runtime-host/src/runtime-host.ts::completion.once",
        "reachability": "production",
        "owner": "AgentSurfaceRuntime / Pi stateless completion",
        "model": "activeRag.quickModel，默认 deepseek/deepseek-v4-flash",
        "thinking": (
            "activeRag.quickThinkingLevel，缺省 high；Pi Host 接受完整思考等级，"
            "并按实际模型 thinkingLevels 再校验"
        ),
        "transport": (
            "Pi 无会话 completion.once：一条包含指令前缀和 JSON 数据的 user message；"
            "无 systemPrompt、无 tools"
        ),
        "systemInstruction": "none",
        "tools": "none",
        "promptIds": [
            "surface.ime-continuation.request-example",
        ],
        "notes": (
            "这是用户显式触发的辅助面，不继承普通 Agent/Room 历史。"
            "surface.ime-continuation 是 user message 内的指令前缀，不是 system role；"
            "思考等级只在所选模型明确支持时才发送。"
        ),
    },
    {
        "id": "voice-refinement-pi",
        "title": "语音输入第三遍校对",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/agent_surface_runtime.py::AgentSurfaceRuntime.refine_voice",
        "reachability": "production",
        "owner": "AgentSurfaceRuntime internal Session",
        "model": "Pi 默认模型档案",
        "thinking": "固定 off",
        "transport": "隔离的内部 Pi Session：专用 systemPrompt + user transcript，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "surface.voice-refinement",
            "surface.voice-refinement.request-example",
        ],
        "notes": "只校对文字，不回答转写内容，也不产生语音输出。",
    },
    {
        "id": "minimind-hot",
        "title": "MiniMind 0.1B / 100M Hot 续写",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/mlx_predictor_server.py::_build_base_completion_prompt",
        "reachability": "production-current",
        "owner": "MLX Predictor base-completion lane",
        "model": "本地 minimind-ime-100m-user-daily-core-v1",
        "thinking": "无思考协议",
        "transport": "原始 completion prefix；最多 360 字符",
        "systemInstruction": "none",
        "tools": "none",
        "promptIds": [],
        "requestExampleLabel": "原始 completion prefix（模型输入，不是 Prompt 指令）",
        "requestExample": _build_base_completion_prompt(
            current_input="继续检查上下文",
            recent_context="Agent Prompt 已进入逐段复核",
        ),
        "notes": (
            "当前模型没有 Prompt：没有 chat template、System Prompt、user/assistant "
            "包装、思考协议或工具。这里只把去重、截断后的前台上下文与当前输入"
            "拼成最多 360 字符的原始续写前缀；旧 MLX 指令模板不属于此路由。"
        ),
    },
    {
        "id": "deepseek-post-commit",
        "title": "提交后 DeepSeek 远程候选",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/rime_sidecar.py::_predict_deepseek_post_commit_candidates",
        "reachability": "production-conditional",
        "owner": "Rime post-commit side lane / DeepSeekV4FlashCompletionProvider",
        "model": "DeepSeek V4 direct Chat Completions",
        "thinking": "读取 DeepSeek 配置；当前缺省 disabled",
        "transport": "Chat Completions：system + bounded JSON user message，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "surface.deepseek-post-commit.system",
            "surface.deepseek-post-commit.user-example",
        ],
        "notes": "仅在 post-commit 远程侧路开启且仍有候选槽位时运行。",
    },
    {
        "id": "knowledge-workbench",
        "title": "个人知识工作台",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/knowledge_workbench.py::DeepSeekKnowledgeProvider.generate",
        "reachability": "production-conditional",
        "owner": "DeepSeekKnowledgeProvider",
        "model": "DeepSeek V4 knowledge model",
        "thinking": "读取 DeepSeek 配置；当前缺省 disabled",
        "transport": "Chat Completions：system + bounded evidence user message，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "surface.knowledge-workbench.system",
            "surface.knowledge-workbench.user-example",
        ],
        "notes": "仅由知识工作台显式请求触发，不进入普通 Agent/Room 稳定前缀。",
    },
    {
        "id": "knowledge-graph-model",
        "title": "知识图谱模型抽取",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/knowledge_library/graph_extractors.py::OpenAICompatibleGraphExtractor.extract",
        "reachability": "production-optional",
        "owner": "OpenAICompatibleGraphExtractor",
        "model": "配置的 DeepSeek V4 knowledge model",
        "thinking": "读取 DeepSeek 配置；当前缺省 disabled",
        "transport": "Chat Completions JSON mode：system + chunks JSON，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": ["surface.knowledge-graph.system"],
        "notes": "graph extractor mode=model 时使用；默认 deterministic 模式不调用模型。",
    },
    {
        "id": "memory-governance",
        "title": "记忆候选与 Book 治理",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/deepseek_memory_organizer.py::DeepSeekMemoryOrganizer",
        "reachability": "production-background",
        "owner": "DeepSeekMemoryOrganizer",
        "model": "DeepSeek V4 governance model",
        "thinking": "每次治理请求强制 enabled",
        "transport": "Chat Completions JSON mode：精确 system contract + bounded evidence user message",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "memory.atom-curation",
            "memory.atom-curation-recovery",
            "memory.book-compile",
            "memory.book-compile-recovery",
            "memory.owner-curation",
            "memory.owner-curation-recovery",
            "memory.role-book-curation",
            "memory.phrase-pinyin-repair",
        ],
        "notes": "低频后台治理；只产出可审阅候选或草稿，不把模型输出直接当用户事实。",
    },
    {
        "id": "openai-compatible-predictor",
        "title": "OpenAI 兼容输入候选",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/predictor.py::OpenAICompatiblePredictionProvider.predict",
        "reachability": "production-configurable",
        "owner": "OpenAICompatiblePredictionProvider",
        "model": "配置的即时预测模型",
        "thinking": "逐键低延迟路径通常禁用",
        "transport": "Chat Completions：request-type system + compact user payload，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "surface.predictor.openai_chat_system_prompt",
            "surface.predictor.openai-generic_prediction",
            "surface.predictor.openai-pinyin_constrained_prediction",
            "surface.predictor.openai-rime_reorder",
            "surface.predictor.openai-no_input_prediction",
            "surface.predictor.openai-active_rag",
        ],
        "notes": "只有设置把 predictor 切到 OpenAI-compatible 时使用；不是当前 MiniMind Hot。",
    },
    {
        "id": "ollama-predictor",
        "title": "Ollama 兼容输入候选",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/predictor.py::OllamaPredictionProvider.predict",
        "reachability": "production-configurable",
        "owner": "OllamaPredictionProvider",
        "model": "配置的本地 Ollama 模型",
        "thinking": "显式 think=false",
        "transport": "Ollama chat：system + user prompt，无 tools",
        "systemInstruction": "present",
        "tools": "none",
        "promptIds": [
            "surface.predictor.ollama_chat_system_prompt",
            "surface.predictor.ollama_stream_first_system_prompt",
        ],
        "notes": "只有设置把 predictor 切到 Ollama 时使用。",
    },
    {
        "id": "mlx-chat-compatibility",
        "title": "旧 MLX Chat/Instruction 兼容路由",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/mlx_predictor_server.py::_build_mlx_prompt",
        "reachability": "compatibility",
        "owner": "MLX Predictor chat/instruction profile",
        "model": "带 chat template 的本地 Qwen 类模型",
        "thinking": "显式非思考 assistant prefix",
        "transport": "ChatML/instruction prompt string，无 tools",
        "systemInstruction": "present-compatibility",
        "tools": "none",
        "promptIds": [
            "surface.predictor.system_prompt",
            "surface.predictor.stream_first_system_prompt",
            "surface.predictor.space_list_system_prompt",
            "surface.predictor.logits_system_prompt",
            "surface.predictor.mlx-generic-example",
            "surface.predictor.mlx-no-input-example",
        ],
        "notes": "保留给非 base-completion 模型；当前 MiniMind 0.1B 不接收这些文本。",
    },
    {
        "id": "direct-active-rag-preview",
        "title": "Direct DeepSeek Active RAG 兼容预览",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/debug_server.py::DebugImeService.deepseek_completion_preview",
        "reachability": "debug-compatibility",
        "owner": "DeepSeekV4FlashCompletionProvider preview",
        "model": "DeepSeek V4 direct Chat Completions",
        "thinking": "读取 DeepSeek 配置",
        "transport": "Chat Completions：system + user message，无 tools",
        "systemInstruction": "present-compatibility",
        "tools": "none",
        "promptIds": [
            "surface.deepseek-active-rag.system",
            "surface.deepseek-active-rag.user-example",
        ],
        "notes": "正式 8766/8768 Active RAG 已改走 Pi completion.once；此路由只用于预览和兼容诊断。",
    },
    {
        "id": "legacy-memory-generator",
        "title": "旧版记忆编译兼容路由",
        "sourceRoot": "product",
        "sourcePath": "rag_ime/memory_generator.py::VcpRebuildMemoryGenerator",
        "reachability": "operator-compatibility",
        "owner": "VcpRebuildMemoryGenerator",
        "model": "CLI/Debug 配置的 OpenAI-compatible model",
        "thinking": "由兼容配置决定，不保证开启",
        "transport": "Responses 或 Chat Completions：system + user evidence，无 tools",
        "systemInstruction": "present-compatibility",
        "tools": "none",
        "promptIds": [
            "memory.legacy-distillation",
            "memory.legacy-core-optimization",
        ],
        "notes": "不属于新的后台 DeepSeekMemoryOrganizer 主路径。",
    },
)

EXECUTION_TITLES = {
    "read_only": "执行权限：只读",
    "per_action": "执行权限：每次确认",
    "workspace_managed": "执行权限：工作区托管",
    "full_trust": "执行权限：完全信任",
}


def _prompt_title(prompt_id: str, producer: str) -> str:
    if prompt_id in PROMPT_TITLE_OVERRIDES:
        return PROMPT_TITLE_OVERRIDES[prompt_id]
    if prompt_id.startswith("agent.execution."):
        return EXECUTION_TITLES.get(prompt_id.rsplit(".", 1)[-1], prompt_id)
    return producer.replace("_", " ").strip() or prompt_id


def _prompt_metadata_defaults(
    prompt_id: str,
    category: str,
    status: str,
) -> dict[str, str]:
    if category == "pi-runtime-evidence":
        room_evidence = ".room-" in prompt_id or prompt_id.endswith(".room-example")
        return {
            "display_group": "runtime-evidence",
            "runtime_scope": "room" if room_evidence else "agent",
            "reachability": "evidence",
            "owner": "Pi Runtime Provider projection",
            "model_route": "确定性 Provider 对象快照",
            "thinking_requirement": "沿用被审计 Session；此记录本身不发起模型调用",
        }
    if category == "approval-arbitration":
        return {
            "display_group": "approval-arbitration",
            "runtime_scope": "agent",
            "reachability": "conditional",
            "owner": "AgentService / ApprovalModelArbiter",
            "model_route": "固定 openai-codex/gpt-5.6-luna",
            "thinking_requirement": "固定 max；无 tools；单次无会话裁决",
        }
    if category == "memory-governance":
        compatibility = status.startswith("legacy")
        historical = prompt_id == "memory.historical-curation"
        pinyin_repair = prompt_id == "memory.phrase-pinyin-repair"
        if compatibility:
            return {
                "display_group": "compatibility-history",
                "runtime_scope": "memory-governance",
                "reachability": "operator-only",
                "owner": "VcpRebuildMemoryGenerator compatibility route",
                "model_route": "CLI/Debug 选择的 OpenAI-compatible model",
                "thinking_requirement": "可配置；当前兼容默认不保证开启思考",
            }
        return {
            "display_group": "memory-governance",
            "runtime_scope": "memory-governance",
            "reachability": "operator-only" if historical else "background",
            "owner": (
                "DeepSeekMemoryOrganizer phrase repair"
                if pinyin_repair
                else "HistoricalMemoryCuration / injected OwnerMemoryOrganizer"
                if historical
                else "DeepSeekMemoryOrganizer"
            ),
            "model_route": (
                "调用方注入的 OwnerMemoryOrganizer；正式路径为 DeepSeek V4"
                if historical
                else "DeepSeek V4 governance model"
            ),
            "thinking_requirement": "治理任务强制 thinking=enabled",
        }
    if category == "auxiliary-surface":
        representative = status == "representative"
        if prompt_id == "surface.ime-continuation":
            owner = "PiRuntime legacy ime-surface-v1 Session profile"
            model_route = "operator-created compatibility Session"
            thinking = "compatibility only; not used by current Active RAG"
        elif prompt_id.startswith("surface.ime-continuation"):
            owner = "AgentSurfaceRuntime / Pi complete_once"
            model_route = "activeRag.quickModel（默认 deepseek/deepseek-v4-flash）"
            thinking = (
                "activeRag.quickThinkingLevel；缺省 high，Pi Host 接受完整等级并按"
                "所选模型能力校验"
            )
        elif prompt_id.startswith("surface.voice-refinement"):
            owner = "AgentSurfaceRuntime voice refinement"
            model_route = "Pi 默认模型档案的内部无工具 Session"
            thinking = "固定 off；任务只允许保守校对"
        elif prompt_id.startswith("surface.deepseek-post-commit"):
            owner = "Rime post-commit side lane / DeepSeekV4FlashCompletionProvider"
            model_route = "DeepSeek V4 direct Chat Completions"
            thinking = "读取 DeepSeek 配置；默认 disabled 的低延迟候选路径"
        elif prompt_id.startswith("surface.deepseek-active-rag"):
            owner = "DeepSeekV4FlashCompletionProvider compatibility preview"
            model_route = "DeepSeek V4 direct Chat Completions"
            thinking = (
                "兼容预览读取 DeepSeek 配置；正式 Active RAG 走 Pi 并按"
                "所选模型的 thinkingLevels 校验"
            )
        elif prompt_id.startswith("surface.knowledge-workbench"):
            owner = "DeepSeekKnowledgeProvider"
            model_route = "DeepSeek V4 knowledge model"
            thinking = "读取 DeepSeek 配置；当前默认可能为 disabled，需复核"
        elif prompt_id.startswith("surface.knowledge-graph"):
            owner = "OpenAICompatibleGraphExtractor"
            model_route = "DeepSeek V4 knowledge model"
            thinking = "读取 DeepSeek 配置；JSON 抽取以确定性和证据约束为主"
        elif prompt_id.startswith("surface.deep-search"):
            owner = "AgentPromptApplication / ordinary Pi Agent Session"
            model_route = "当前 Assistant Session 或默认模型档案"
            thinking = "沿用目标 Agent Session 的 thinkingLevel"
        elif prompt_id.startswith("surface.predictor.minimind"):
            owner = "MiniMind base-completion Hot lane"
            model_route = "本地 MiniMind IME 0.1B / 100M base checkpoint"
            thinking = "无 System Prompt、无思考协议；只做原始文本续写"
        elif prompt_id.startswith("surface.predictor.mlx"):
            owner = "Local MLX chat compatibility lane"
            model_route = "本地 Qwen chat/instruction profile；不是当前 MiniMind Hot"
            thinking = "显式非思考 assistant 前缀；兼容路径"
        elif prompt_id.startswith("surface.predictor.ollama"):
            owner = "Ollama-compatible predictor"
            model_route = "配置的本地 Ollama 模型"
            thinking = "显式 think=false；逐键低延迟路径"
        elif prompt_id.startswith("surface.predictor.openai"):
            owner = "OpenAI-compatible predictor"
            model_route = "配置的即时预测模型"
            thinking = "通常禁用；逐键低延迟路径"
        else:
            owner = "Auxiliary surface runtime"
            model_route = "由辅助面运行配置选择"
            thinking = "由辅助面运行配置决定"
        compatibility = status == "compatibility"
        return {
            "display_group": (
                "representative"
                if representative
                else "auxiliary-compatibility"
                if compatibility
                else "auxiliary-production"
            ),
            "runtime_scope": "auxiliary-surface",
            "reachability": (
                "representative"
                if representative
                else "compatibility"
                if compatibility
                else "conditional"
            ),
            "owner": owner,
            "model_route": model_route,
            "thinking_requirement": thinking,
        }

    representative = status == "representative"
    room_category = category.startswith("room-") or prompt_id.startswith("room.")
    if prompt_id.startswith("agent.core.") or category == "skill-tool":
        runtime_scope = "agent-room"
    elif room_category:
        runtime_scope = "room"
    else:
        runtime_scope = "agent"
    owners = {
        "ordinary-agent": "Agent Core policy",
        "skill-tool": "Pi capability projection",
        "role-memory": "Role Book compiler",
        "persona": "Persona compiler",
        "agent-template": "Agent template compiler",
        "room-stable": "Room PromptPlan compiler",
        "room-dynamic": "Room Kernel context compiler",
        "room-lifecycle": "Room settlement lifecycle",
        "room-recovery": "Room compaction recovery",
        "delegation": "Agent delegation lifecycle",
        "composed-provider-prompt": "Pi final prompt composer",
    }
    return {
        "display_group": (
            "representative" if representative else "agent-room-production"
        ),
        "runtime_scope": runtime_scope,
        "reachability": (
            "representative"
            if representative
            else "conditional"
            if status in {"conditional", "variant", "zero-byte"}
            else "production"
        ),
        "owner": owners.get(category, "Agent Runtime"),
        "model_route": "当前 Session 选定模型",
        "thinking_requirement": "当前 Session 的模型与推理设置",
    }

# A symbol may own model-visible instructions, assemble them, validate them, or
# merely transport a user message. Every discovered symbol must be classified
# so a new prompt producer cannot silently bypass this audit.
PROMPT_SYMBOL_CLASSIFICATION = {
    "activity_timeline_curation.py::ACTIVITY_ORGANIZATION_CONTRACT_REPAIR_PROMPT_VERSION": "prompt-version",
    "activity_timeline_curation.py::ACTIVITY_ORGANIZATION_PROMPT_VERSION": "prompt-version",
    "activity_timeline_curation.py::ACTIVITY_ORGANIZATION_REPAIR_PROMPT_VERSION": "prompt-version",
    "activity_timeline_curation.py::ACTIVITY_ORGANIZATION_VERIFIER_PROMPT_VERSION": "prompt-version",
    "activity_timeline_curation.py::build_activity_organization_contract_repair_prompt": "background-prompt",
    "activity_timeline_curation.py::build_activity_organization_prompt": "background-prompt",
    "activity_timeline_curation.py::build_activity_organization_repair_prompt": "background-prompt",
    "activity_timeline_curation.py::build_activity_organization_verifier_prompt": "background-prompt",
    "agent_approval_model.py::APPROVAL_MODEL_PROMPT_VERSION": "prompt-version",
    "agent_approval_model.py::_arbiter_prompt": "dynamic-prompt",
    "agent_approval_model.py::_model_input": "bounded-prompt-input",
    "agent_context_runtime.py::RUNTIME_PROMPT_ENVELOPE_PREFIX": "transport-envelope",
    "agent_context_runtime.py::compose_runtime_prompt": "transport-assembler",
    "agent_core_policy.py::core_agent_policy_prompt": "stable-assembler",
    "agent_core_policy.py::durable_memory_policy_prompt": "stable-prompt",
    "agent_core_policy.py::managed_goal_policy_prompt": "stable-prompt",
    "agent_core_policy.py::todo_policy_prompt": "stable-prompt",
    "agent_core_policy.py::work_policy_prompt": "stable-prompt",
    "agent_definitions.py::_MANAGED_ROOM_LIFECYCLE_PROMPT": "stable-prompt",
    "agent_delegation.py::_subagent_prompt": "dynamic-prompt",
    "agent_execution_policy.py::execution_policy_prompt": "dynamic-prompt",
    "agent_prompt_plans.py::_provider_layer_prompt": "stable-assembler",
    "agent_prompt_support.py::deep_search_prompt": "auxiliary-surface-prompt",
    "agent_prompt_support.py::prompt_delivery": "transport-validator",
    "agent_prompt_support.py::prompt_user_message_payload": "message-assembler",
    "agent_role_book.py::ROLE_BOOK_PROMPT_PREFIX": "conditional-prompt",
    "agent_role_book.py::_reject_prompt_injection": "content-validator",
    "agent_role_book.py::compile_role_book_prompt": "conditional-prompt",
    "agent_room_prompt_context.py::room_intercom_prompt": "dynamic-prompt",
    "agent_room_prompt_context.py::room_participant_prompt": "dynamic-prompt",
    "agent_room_runtime_coordinator.py::_profile_overlay_prompt": "conditional-prompt",
    "agent_room_runtime_coordinator.py::_prompt_layers": "stable-assembler",
    "agent_surface_runtime.py::_voice_refinement_prompt": "auxiliary-surface-prompt",
    "context_views.py::build_model_prompt_view": "auxiliary-input-projection",
    "deepseek_completion.py::_generic_prompt_candidate": "auxiliary-output-filter",
    "deepseek_memory_organizer.py::DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION": "background-prompt",
    "deepseek_memory_organizer.py::_memory_book_recovery_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_memory_book_system_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_memory_curation_recovery_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_memory_curation_semantic_repair_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_memory_curation_system_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_memory_curation_verifier_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_owner_memory_recovery_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_owner_memory_system_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_phrase_pinyin_repair_system_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_role_book_curation_system_prompt": "background-prompt",
    "deepseek_memory_organizer.py::_semantic_curation_prompt_bundle": "bounded-prompt-input",
    "historical_memory_curation.py::ATOM_FIRST_HISTORICAL_INSTRUCTION": "background-prompt",
    "historical_memory_curation.py::DEFAULT_HISTORICAL_CURATION_INSTRUCTION": "background-prompt",
    "memory_model_executor.py::_session_prompt": "background-prompt",
    "memory_generator.py::_core_optimization_system_prompt": "background-prompt",
    "memory_generator.py::_memory_generation_system_prompt": "background-prompt",
    "mlx_predictor_server.py::LOGITS_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "mlx_predictor_server.py::SPACE_LIST_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "mlx_predictor_server.py::STREAM_FIRST_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "mlx_predictor_server.py::SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "mlx_predictor_server.py::_build_base_completion_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_imev1_dynamic_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_mlx_dynamic_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_mlx_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_no_input_space_list_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_seeded_replay_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_build_seeded_sequence_fork_base_prompt": "auxiliary-prompt-assembler",
    "mlx_predictor_server.py::_estimate_prompt_tokens": "auxiliary-telemetry",
    "mlx_predictor_server.py::_looks_like_prompt_instruction": "auxiliary-output-filter",
    "mlx_predictor_server.py::_prompt_cache_used_for_generation": "auxiliary-cache-telemetry",
    "mlx_predictor_server.py::_request_type_prompt_instruction": "auxiliary-prompt-fragment",
    "mlx_predictor_server.py::_rime_candidates_prompt_line": "auxiliary-prompt-fragment",
    "mlx_predictor_server.py::_seeded_prompt_replay_candidate_scores": "auxiliary-ranking-helper",
    "mlx_predictor_server.py::_stable_prompt_prefix": "auxiliary-stable-prefix",
    "pi_runtime.py::_IME_SURFACE_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "pi_runtime.py::_MEMORY_CURATION_SYSTEM_PROMPT": "background-prompt",
    "pi_runtime.py::_VOICE_REFINEMENT_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "pi_runtime.py::_empty_role_book_prompt": "zero-byte-provider",
    "pi_runtime.py::_render_session_prompt": "stable-assembler",
    "pi_runtime.py::_session_mode_prompt": "conditional-prompt",
    "predictor.py::OLLAMA_CHAT_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "predictor.py::OLLAMA_STREAM_FIRST_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "predictor.py::OPENAI_CHAT_SYSTEM_PROMPT": "auxiliary-surface-prompt",
    "predictor.py::_looks_like_prompt_instruction": "auxiliary-output-filter",
    "predictor.py::_normalized_prompt_mode": "auxiliary-route-selector",
    "predictor.py::_openai_prediction_system_prompt": "auxiliary-prompt-assembler",
    "predictor.py::_prompt_cache_used_for_generation": "auxiliary-cache-telemetry",
    "predictor.py::_remove_prediction_prompt_echo": "auxiliary-output-filter",
    "predictor.py::_status_prompt_mode": "auxiliary-route-selector",
    "predictor.py::build_selected_text_rag_prompt": "auxiliary-prompt-assembler",
    "personal_memory_curation.py::_atom_prompt": "background-prompt",
    "personal_memory_curation.py::_evidence_prompt": "background-prompt",
    "personal_memory_curation.py::_verifier_prompt": "background-prompt",
    "personal_memory_luna_evaluation.py::_evaluation_prompt": "evaluation-prompt",
    "real_memory_rag_evaluation.py::build_real_memory_query_prompt": "evaluation-prompt",
    "rime_sidecar.py::_looks_like_model_prompt_echo": "auxiliary-output-filter",
    "rime_sidecar.py::_looks_like_prompt_example_leak": "auxiliary-output-filter",
    "room_effect_eval.py::_prompt_contract_errors": "test-contract-validator",
    "suggestion_compiler.py::_looks_like_short_instruction_surface": "auxiliary-output-filter",
}


@dataclass(frozen=True)
class PromptRecord:
    prompt_id: str
    category: str
    source_path: str
    producer: str
    injection_phase: str
    condition: str
    model_visible: bool
    status: str
    content: str
    notes: str = ""

    def payload(self) -> dict[str, object]:
        data = asdict(self)
        encoded = self.content.encode("utf-8")
        data.update(
            _prompt_metadata_defaults(
                self.prompt_id,
                self.category,
                self.status,
            )
        )
        data.update(
            {
                "title": _prompt_title(self.prompt_id, self.producer),
                "chars": len(self.content),
                "utf8Bytes": len(encoded),
                "estimatedTokens": (len(encoded) + 3) // 4,
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
        return data


def _record(
    prompt_id: str,
    category: str,
    source_path: str,
    producer: str,
    injection_phase: str,
    condition: str,
    content: str,
    *,
    model_visible: bool = True,
    status: str = "active",
    notes: str = "",
) -> PromptRecord:
    return PromptRecord(
        prompt_id=prompt_id,
        category=category,
        source_path=source_path,
        producer=producer,
        injection_phase=injection_phase,
        condition=condition,
        model_visible=model_visible,
        status=status,
        content=str(content),
        notes=notes,
    )


def _sample_role_book() -> str:
    evidence = {
        "provenance": {
            "sourceType": "session_digest",
            "sourceId": "session-sample",
            "observedAtMs": 1,
        },
        "evidenceIds": ["evidence-1"],
    }
    return compile_role_book_prompt(
        {
            "status": "active",
            "roleId": "companion-present-v1",
            "roleVersion": "1",
            "sections": {
                "personality": [
                    {
                        "text": "用户希望先给结论，再给必要证据。",
                        **evidence,
                    }
                ],
                "capabilities": [
                    {
                        "text": "已验证能够在受控工作区完成代码修改和测试。",
                        **evidence,
                    }
                ],
                "recentWork": [],
                "lessonsAndLimits": [
                    {
                        "text": "涉及外部发布前必须保留人工确认。",
                        **evidence,
                    }
                ],
                "activeCommitments": [],
            },
        }
    )


def _granted_workspace_session(mode: str) -> dict[str, object]:
    roots = ["/workspace/project"]
    return {
        "executionMode": mode,
        "toolProfileVersion": "control-center-v1",
        "workspaceRoots": roots,
        "workspaceScopeSha256": workspace_scope_sha256(roots),
        "workspaceScopeGrantedAtMs": 1,
    }


def _ordinary_prompt_records() -> list[PromptRecord]:
    present = agent_role("companion-present-v1", "1")
    records = [
        _record(
            "agent.core.safety",
            "ordinary-agent",
            "rag_ime/agent_roles.py",
            "PersonaManifest.safety_policy_prompt",
            "stable system prefix",
            "every ordinary Agent and Room Session",
            present.safety_policy_prompt,
        ),
        _record(
            "agent.core.work",
            "ordinary-agent",
            "rag_ime/agent_core_policy.py",
            "work_policy_prompt",
            "stable system prefix",
            "every ordinary Agent and Room Session",
            work_policy_prompt(),
        ),
        _record(
            "agent.core.todo",
            "ordinary-agent",
            "rag_ime/agent_core_policy.py",
            "todo_policy_prompt",
            "stable system prefix",
            "every ordinary Agent and Room Session",
            todo_policy_prompt(),
        ),
        _record(
            "agent.core.durable-memory",
            "ordinary-agent",
            "rag_ime/agent_core_policy.py",
            "durable_memory_policy_prompt",
            "stable system prefix",
            "every ordinary Agent and Room Session",
            durable_memory_policy_prompt(),
        ),
        _record(
            "agent.core.managed-work",
            "ordinary-agent",
            "rag_ime/agent_core_policy.py",
            "managed_goal_policy_prompt",
            "stable system prefix",
            "only an explicit Agent template, coordinator task, Goal, Task, or Room Dispatch",
            managed_goal_policy_prompt(),
        ),
        _record(
            "agent.capabilities.progressive",
            "skill-tool",
            "rag_ime/agent_templates.py",
            "progressive_capability_policy",
            "stable system prefix",
            "Pi protocol v2 Agent and Room Sessions",
            progressive_capability_policy(),
        ),
        _record(
            "agent.session.coordinator",
            "ordinary-agent",
            "rag_ime/pi_runtime.py",
            "_session_mode_prompt",
            "stable system prefix",
            "ordinary coordinator Session without an Agent template",
            _session_mode_prompt({"mode": "coordinator"}, ""),
            status="conditional",
        ),
        _record(
            "agent.session.assistant-zero",
            "ordinary-agent",
            "rag_ime/pi_runtime.py",
            "_session_mode_prompt",
            "stable system prefix",
            "ordinary Session mode is assistant rather than coordinator",
            _session_mode_prompt({"mode": "assistant"}, ""),
            status="zero-byte",
            notes="Assistant mode adds no placeholder or redundant mode narration.",
        ),
        _record(
            "agent.session.template-selected-zero",
            "ordinary-agent",
            "rag_ime/pi_runtime.py",
            "_session_mode_prompt",
            "stable system prefix",
            "an explicit Agent template is selected, even if Session mode is coordinator",
            _session_mode_prompt({"mode": "coordinator"}, "planner"),
            status="zero-byte",
            notes="The selected template owns the work method, so coordinator narration is not duplicated.",
        ),
        _record(
            "agent.role-book.unpinned",
            "role-memory",
            "rag_ime/pi_runtime.py",
            "_empty_role_book_prompt",
            "persona layer",
            "Role Book revision is absent or not safely pinned",
            "",
            status="zero-byte",
            notes="The model receives no placeholder, warning, or revision_not_pinned text.",
        ),
        _record(
            "agent.role-book.pinned-example",
            "role-memory",
            "rag_ime/agent_role_book.py",
            "compile_role_book_prompt",
            "persona layer",
            "an active/superseded/rolled-back revision is pinned and passes provenance checks",
            _sample_role_book(),
            status="conditional",
        ),
    ]
    records.append(
        _record(
            "agent.approval.model-arbiter-example",
            "approval-arbitration",
            "rag_ime/agent_approval_model.py",
            "_arbiter_prompt",
            "isolated stateless user message",
            "executionMode=full_trust and one immutable approval preview is pending",
            _arbiter_prompt(
                _model_input(
                    {
                        "approvalId": "approval:example",
                        "sessionId": "session:example",
                        "toolName": "workspace_shell",
                        "operation": "run",
                        "riskLevel": "R2",
                        "payloadSha256": "a" * 64,
                        "preview": {
                            "title": "运行工作区命令",
                            "summary": "清理当前工作区内的构建目录",
                            "actionPayload": {
                                "cwd": "/workspace/project",
                                "command": "rm -rf build",
                            },
                        },
                    },
                    {
                        **_granted_workspace_session("full_trust"),
                        "id": "session:example",
                    },
                    context={
                        "contextAvailable": True,
                        "contextKind": "session",
                        "contextId": "session:example",
                        "userRequests": [
                            {
                                "role": "user",
                                "text": "清理构建产物后继续验证。",
                            }
                        ],
                        "currentTask": {
                            "kind": "agent_workflow",
                            "activeUserRequest": "清理构建产物后继续验证。",
                        },
                        "actor": {"sessionId": "session:example"},
                    },
                    history=[
                        {
                            "approvalId": "approval:earlier",
                            "decision": "approve",
                            "status": "decided",
                            "tool": "workspace_shell",
                            "operation": "run",
                            "reasonCodes": ["bounded_operation"],
                            "rationaleSummary": "此前的受限验证命令可执行。",
                        }
                    ],
                )
            ),
            status="representative",
            notes=(
                "The complete bounded input is hash-audited before this call. User requests and "
                "structured decision history are included; primary-Agent messages are excluded. "
                "The model returns strict JSON only; the immutable receipt is payload-hash-bound."
            ),
        )
    )
    for mode in ("read_only", "per_action", "workspace_managed", "full_trust"):
        records.append(
            _record(
                f"agent.execution.{mode}",
                "ordinary-agent",
                "rag_ime/agent_execution_policy.py",
                "execution_policy_prompt",
                "stable system prefix",
                f"Session executionMode={mode}",
                execution_policy_prompt(
                    {
                        "executionMode": mode,
                        "toolProfileVersion": "control-center-v1",
                    }
                ),
                status="variant",
                notes=(
                    "This is the pre-approval branch."
                    if mode in {"workspace_managed", "full_trust"}
                    else ""
                ),
            )
        )
        if mode in {"workspace_managed", "full_trust"}:
            records.append(
                _record(
                    f"agent.execution.{mode}.granted",
                    "ordinary-agent",
                    "rag_ime/agent_execution_policy.py",
                    "execution_policy_prompt",
                    "stable system prefix",
                    f"Session executionMode={mode} and the exact workspace root set has one valid scope grant",
                    execution_policy_prompt(_granted_workspace_session(mode)),
                    status="variant",
                    notes="The grant is bound to the normalized workspace-root digest and grant time; no credential enters the Prompt.",
                )
            )
    for item in agent_role_catalog():
        manifest = agent_role(item["roleId"], item["version"])
        records.append(
            _record(
                f"agent.persona.{manifest.role_id}",
                "persona",
                "rag_ime/agent_roles.py",
                f"agent_role({manifest.role_id}@{manifest.version})",
                "stable persona layer",
                "selected Persona",
                manifest.persona_prompt,
                status="variant",
            )
        )
    for item in agent_template_catalog():
        manifest = agent_template(item["templateId"], item["version"])
        records.append(
            _record(
                f"agent.template.{manifest.template_id}",
                "agent-template",
                "rag_ime/agent_templates.py",
                f"agent_template({manifest.template_id}@{manifest.version})",
                "stable Agent template layer",
                "the Agent template is explicitly selected",
                manifest.prompt,
                status="variant",
                notes=(
                    "This body is for an explicitly selected ordinary Agent/subagent template. "
                    "Room work uses the collaboration-role layer; its template layer reuses only "
                    "the shared progressive-capability policy."
                ),
            )
        )

    config = PiRuntimeConfig(
        enabled=True,
        executable=None,
        agent_dir=ROOT,
        session_dir=ROOT,
        logs_dir=ROOT,
        protocol_version="2",
    )
    assistant_session = {
        "roleId": "companion-present-v1",
        "roleVersion": "1",
        "mode": "assistant",
        "executionMode": "per_action",
        "toolProfileVersion": "control-center-v1",
    }
    coordinator_session = {
        **assistant_session,
        "roleId": "companion-future-v1",
        "mode": "coordinator",
        **_granted_workspace_session("workspace_managed"),
    }
    records.extend(
        (
            _record(
                "agent.composed.assistant-example",
                "composed-provider-prompt",
                "rag_ime/pi_runtime.py",
                "PiRuntimeConfig.system_prompt_for_session",
                "final stable system prompt",
                "ordinary assistant example, no Role Book and no task template",
                config.system_prompt_for_session(assistant_session),
                status="representative",
            ),
            _record(
                "agent.composed.coordinator-example",
                "composed-provider-prompt",
                "rag_ime/pi_runtime.py",
                "PiRuntimeConfig.system_prompt_for_session",
                "final stable system prompt",
                "ordinary coordinator example, no Room binding",
                config.system_prompt_for_session(coordinator_session),
                status="representative",
            ),
        )
    )
    return records


def _room_samples() -> tuple[dict[str, object], dict[str, object]]:
    participant = {
        "id": "participant-builder",
        "displayName": "构筑者",
        "status": "active",
        "collaborationRole": "implementer",
    }
    room = {
        "id": "room-sample",
        "title": "Prompt 生产验收",
        "roomKind": "collaboration",
        "activeTopicId": "topic-main",
        "topics": [
            {
                "id": "topic-main",
                "title": "主任务",
                "summary": "先对齐需求，再由三位成员完成实现、测试和独立复核。",
            }
        ],
        "participants": [
            participant,
            {
                "id": "participant-reviewer",
                "displayName": "审阅者",
                "status": "active",
                "collaborationRole": "reviewer",
            },
        ],
        "workItems": [],
    }
    return room, participant


class _SettlementKernelFixture:
    def dispatch(self, _dispatch_id: str) -> dict[str, object]:
        return {"taskId": "task-sample"}

    def task(self, _task_id: str) -> dict[str, object]:
        return {"acceptanceCriterionIds": ["criterion-a", "criterion-b"]}


def _settle_follow_up(kind: str) -> str:
    service = object.__new__(RoomSettleLifecycleService)
    service.kernel = _SettlementKernelFixture()  # type: ignore[attr-defined]
    return service._follow_up_instruction(  # noqa: SLF001
        dispatch_id="dispatch-sample",
        reason="missing_room_commit",
        follow_up_kind=kind,
    )


def _room_recovery_sample() -> str:
    task_context = json.dumps(
        {
            "task": {
                "objective": "实现并验证一个有界改动",
                "expectedOutput": "代码、测试和审阅回执",
                "state": "active",
            },
            "requirements": {
                "original": [{"text": "原始需求必须永久保留"}],
                "items": [{"statement": "Room 收工必须由 Kernel 裁决"}],
            },
            "acceptance": {
                "criteria": [
                    {
                        "criterionId": "criterion-a",
                        "statement": "测试通过",
                        "passed": True,
                    },
                    {
                        "criterionId": "criterion-b",
                        "statement": "独立复核通过",
                        "passed": False,
                    },
                ]
            },
            "blockers": {
                "obstacles": [
                    {"kind": "external", "statement": "等待上游测试环境"}
                ]
            },
            "continuation": {"intentKind": "review"},
        },
        ensure_ascii=False,
    )
    return room_compaction_recovery_context(
        task_context,
        skill_receipt={
            "skillId": "quality-gate",
            "restoredFromReceiptId": "skill-receipt-1",
        },
        tool_receipt={
            "items": [
                {"name": "workspace_read", "receiptId": "tool-receipt-1"},
                {"name": "room_commit", "receiptId": "tool-receipt-2"},
            ]
        },
        covered_criterion_ids=("criterion-a",),
    )


def _room_prompt_records() -> list[PromptRecord]:
    room, participant = _room_samples()
    records: list[PromptRecord] = []
    for item in collaboration_role_catalog():
        manifest = collaboration_role(item["roleId"], item["version"])
        records.append(
            _record(
                f"room.role.{manifest.role_id}",
                "room-stable",
                "rag_ime/agent_definitions.py",
                f"collaboration_role({manifest.role_id}@{manifest.version})",
                "PromptPlan layer 3",
                "participant collaboration role",
                manifest.system_prompt,
                status="variant",
            )
        )
    for item in collaboration_profile_catalog():
        manifest = collaboration_profile(item["profileId"], item["version"])
        records.append(
            _record(
                f"room.profile.{manifest.profile_id}",
                "room-stable",
                "rag_ime/agent_definitions.py",
                f"collaboration_profile({manifest.profile_id}@{manifest.version})",
                "PromptPlan layer 5",
                "pinned Room profile; standard-room is an intentional zero-byte overlay",
                manifest.system_prompt,
                status="zero-byte" if not manifest.system_prompt else "variant",
            )
        )

    records.extend(
        (
            _record(
                "room.dynamic.alignment-and-decision",
                "room-dynamic",
                "rag_ime/agent_room_prompt_context.py",
                "room_participant_prompt",
                "append-only Room delta",
                "a collaboration Room has no managed WorkItem yet",
                room_participant_prompt(
                    room,
                    participant,
                    "请把这个需求整理清楚，确认后再开始实现。",
                ),
                status="representative",
            ),
            _record(
                "room.dynamic.managed-task",
                "room-dynamic",
                "rag_ime/agent_room_prompt_context.py",
                "room_participant_prompt",
                "append-only Room delta",
                "the participant owns a managed WorkItem",
                room_participant_prompt(
                    room,
                    participant,
                    "执行当前受管任务。",
                    work_item={
                        "objective": "修复 Prompt 重复注入",
                        "expectedOutput": "代码和回归测试",
                        "acceptanceCriteria": ["Prompt 只出现一次", "测试通过"],
                    },
                ),
                status="representative",
            ),
            _record(
                "room.dynamic.intercom-question",
                "room-dynamic",
                "rag_ime/agent_room_prompt_context.py",
                "room_intercom_prompt",
                "private target Session input",
                "another participant uses governed Room ask",
                room_intercom_prompt(
                    room,
                    participant,
                    {"kind": "ask", "workAction": "review"},
                    source={"displayName": "审阅者"},
                    work={"objective": "检查 Prompt 所有权"},
                ),
                status="representative",
            ),
            _record(
                "room.dynamic.intercom-reply",
                "room-dynamic",
                "rag_ime/agent_room_prompt_context.py",
                "room_intercom_prompt",
                "private target Session input",
                "another participant answers a governed Room question",
                room_intercom_prompt(
                    room,
                    participant,
                    {"kind": "reply", "workAction": "collaborate"},
                    source={"displayName": "研究员"},
                    work={"objective": "核对 Prompt 所有权"},
                ),
                status="representative",
            ),
            _record(
                "room.dynamic.intercom-notice",
                "room-dynamic",
                "rag_ime/agent_room_prompt_context.py",
                "room_intercom_prompt",
                "private target Session input",
                "another participant sends non-question supplementary information",
                room_intercom_prompt(
                    room,
                    participant,
                    {"kind": "send", "workAction": "message"},
                    source={"displayName": "实施者"},
                    work=None,
                ),
                status="representative",
            ),
            _record(
                "room.profile.guard-example",
                "room-stable",
                "rag_ime/agent_room_runtime_coordinator.py",
                "_profile_overlay_prompt",
                "PromptPlan layer 5",
                "a reviewed Room Guard is pinned and its deterministic condition/action overlay is active",
                _profile_overlay_prompt(
                    collaboration_profile("standard-room", "1"),
                    {
                        "condition": {
                            "event": "room_commit",
                            "decision": "deliver",
                        },
                        "action": {
                            "requireGate": "peer-review-required",
                        },
                    },
                ),
                status="conditional",
                notes="Guard 物化只能进一步收紧行为，不会授予任何新能力。",
            ),
            _record(
                "room.dispatch.trigger",
                "room-dynamic",
                "rag_ime/agent_room_kernel_worker.py",
                "_default_dispatch_message",
                "private dispatch trigger",
                "Kernel starts or resumes one governed Dispatch",
                _default_dispatch_message({}),
            ),
            _record(
                "room.settle.continue",
                "room-lifecycle",
                "rag_ime/agent_room_settlement.py",
                "RoomSettleLifecycleService._follow_up_instruction",
                "one bounded follow-up turn",
                "the model settled without a legal room_commit and a distinct next action remains",
                _settle_follow_up("continue"),
                status="conditional",
            ),
            _record(
                "room.settle.repair",
                "room-lifecycle",
                "rag_ime/agent_room_settlement.py",
                "RoomSettleLifecycleService._follow_up_instruction",
                "one bounded follow-up turn",
                "room_commit failed deterministic validation",
                _settle_follow_up("repair_commit"),
                status="conditional",
            ),
            _record(
                "room.compaction.recovery-example",
                "room-recovery",
                "rag_ime/agent_room_recovery_context.py",
                "room_compaction_recovery_context",
                "new Provider context epoch",
                "one managed Room compaction occurred",
                _room_recovery_sample(),
                status="representative",
            ),
            _record(
                "agent.delegation.subagent-example",
                "delegation",
                "rag_ime/agent_delegation.py",
                "_subagent_prompt",
                "new bounded child Session",
                "ordinary Agent delegation, not Room collaboration",
                _subagent_prompt(
                    {
                        "task": "只读核对一个明确接口并返回证据",
                        "expectedOutput": "接口边界、证据引用和未决风险",
                        "acceptanceCriteria": [
                            "结论区分已观察事实与推断",
                            "引用真实回执且不宣称父任务已验收",
                        ],
                        "outputSchema": {
                            "type": "object",
                            "required": ["claims", "evidence", "uncertainties"],
                        },
                    },
                    {"contextMode": "fresh", "depth": 1, "maxDepth": 2},
                ),
                status="representative",
            ),
        )
    )

    persona = agent_role("companion-future-v1", "1")
    core = core_agent_policy_prompt(
        persona.safety_policy_prompt,
        _granted_workspace_session("workspace_managed"),
    )
    layers = (
        PromptLayer(
            "core_rails",
            "pi-core-safety",
            "pi-core-safety:v2",
            core,
            ("safety", "authorization", "durable-memory"),
        ),
        PromptLayer(
            "persona",
            "persona-compiler",
            f"persona:{persona.role_id}@{persona.version}",
            compose_persona_layer(persona.persona_prompt, ""),
            ("identity", "role-memory"),
        ),
        PromptLayer(
            "collaboration_role",
            "collaboration-role-compiler",
            "collaboration-role:coordinator@1",
            collaboration_role("coordinator", "1").system_prompt,
            ("collaboration-duty",),
        ),
        PromptLayer(
            "agent_template_policy",
            "template-capability-compiler",
            "agent-template:planner@1",
            agent_template("planner", "1").room_runtime_prompt,
            ("tool-policy", "skill-policy"),
        ),
        PromptLayer(
            "room_profile_overlay",
            "profile-room-kernel-compiler",
            "profile:standard-room@1",
            "",
            ("room-overlay",),
            "profile-not-selected",
        ),
        PromptLayer(
            "provider_dynamic_facts",
            "room-context-compiler",
            "journal:sample",
            "",
            ("dynamic-facts",),
        ),
    )
    compiled, _omitted, _audit, _stable = _compile_layers(layers)
    records.append(
        _record(
            "room.composed.stable-prefix-example",
            "composed-provider-prompt",
            "rag_ime/agent_prompt_plans.py",
            "_provider_layer_prompt",
            "Room PromptPlan stable prefix",
            "representative coordinator participant before dynamic Room facts",
            _provider_layer_prompt(compiled),
            status="representative",
            notes=f"Layer order: {list(PROMPT_LAYER_SPECS)}",
        )
    )
    return records


def _memory_prompt_records() -> list[PromptRecord]:
    prompts = (
        (
            "memory.default-instruction",
            "DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION",
            DEFAULT_MEMORY_ORGANIZATION_INSTRUCTION,
        ),
        ("memory.atom-curation", "_memory_curation_system_prompt", _memory_curation_system_prompt()),
        (
            "memory.atom-curation-recovery",
            "_memory_curation_recovery_prompt",
            _memory_curation_recovery_prompt(),
        ),
        ("memory.book-compile", "_memory_book_system_prompt", _memory_book_system_prompt()),
        (
            "memory.book-compile-recovery",
            "_memory_book_recovery_prompt",
            _memory_book_recovery_prompt(),
        ),
        ("memory.owner-curation", "_owner_memory_system_prompt", _owner_memory_system_prompt()),
        (
            "memory.owner-curation-recovery",
            "_owner_memory_recovery_prompt",
            _owner_memory_recovery_prompt(),
        ),
        (
            "memory.role-book-curation",
            "_role_book_curation_system_prompt",
            _role_book_curation_system_prompt(),
        ),
        (
            "memory.phrase-pinyin-repair",
            "_phrase_pinyin_repair_system_prompt",
            _phrase_pinyin_repair_system_prompt(),
        ),
    )
    records = [
        _record(
            prompt_id,
            "memory-governance",
            "rag_ime/deepseek_memory_organizer.py",
            producer,
            "separate offline Provider request",
            "explicit/manual or governed background memory curation",
            content,
            status="background",
        )
        for prompt_id, producer, content in prompts
    ]
    records.extend(
        (
            _record(
                "memory.historical-curation",
                "memory-governance",
                "rag_ime/historical_memory_curation.py",
                "DEFAULT_HISTORICAL_CURATION_INSTRUCTION",
                "separate offline Provider request",
                "an operator runs a complete historical migration against a disposable database",
                DEFAULT_HISTORICAL_CURATION_INSTRUCTION,
                status="background",
            ),
            _record(
                "memory.legacy-distillation",
                "memory-governance",
                "rag_ime/memory_generator.py",
                "_memory_generation_system_prompt",
                "separate offline Provider request",
                "legacy VcpRebuild generator compatibility route",
                _memory_generation_system_prompt(max_count=3),
                status="legacy-background",
            ),
            _record(
                "memory.legacy-core-optimization",
                "memory-governance",
                "rag_ime/memory_generator.py",
                "_core_optimization_system_prompt",
                "separate offline Provider request",
                "legacy local-core optimization preview route",
                _core_optimization_system_prompt(
                    max_memories=3,
                    max_lexicon_phrases=4,
                    max_hide_suggestions=5,
                ),
                status="legacy-background",
            ),
        )
    )
    return records


def _source_string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""


def _auxiliary_prompt_records() -> list[PromptRecord]:
    pi_surface_message, _ = _one_shot_surface_message(
        {
            "currentContext": "正在逐段检查 Agent Prompt 与上下文。",
            "selectedText": "Prompt 与上下文",
            "contextPacket": {
                "outputContract": {"placement": "insert_after_selection"},
                "windowContext": {
                    "source": "accessibility",
                    "text": "当前窗口正在展示 Prompt 审查页。",
                },
            },
            "evidencePack": [
                {
                    "sourceId": "memory-sample",
                    "sourceLane": "memory",
                    "text": "项目以 Agent 为核心，输入法只是证据来源之一。",
                }
            ],
        },
        current_request="继续检查下一段生产 Prompt。",
    )
    deepseek_post_commit_messages = build_deepseek_completion_messages(
        DeepSeekCompletionRequest(
            scene="post_commit",
            current_context="Agent Prompt 已进入逐段复核",
            context_packet={
                "currentInput": {"committedTail": "Agent Prompt 已进入逐段复核"},
                "surfaceHints": ["继续检查上下文"],
            },
            evidence_pack=(
                {
                    "sourceId": "memory-sample",
                    "sourceType": "memory",
                    "text": "项目以 Agent 为核心，输入法只是候选证据来源之一。",
                },
            ),
            max_candidates=3,
            max_chars=24,
        )
    )
    deepseek_active_rag_messages = build_deepseek_completion_messages(
        DeepSeekCompletionRequest(
            scene="active_rag",
            current_context="正在逐段检查 Agent Prompt 与上下文。",
            selected_text="Prompt 与上下文",
            context_packet={
                "outputContract": {"placement": "insert_after_selection"},
                "intent": "answer",
            },
            max_chars=120,
        )
    )
    knowledge_messages = build_knowledge_workbench_messages(
        KnowledgeWorkbenchRequest(
            question="当前 Agent 记忆系统的稳定边界是什么？",
            mode="knowledge_answer",
            context="正在复核 Prompt、Skill、Tool 与真实 Provider 对象。",
        ),
        evidence=(
            {
                "sourceId": "memory-sample",
                "sourceLane": "memory",
                "title": "产品边界",
                "text": "项目以 Agent 为核心，输入法只是候选证据来源之一。",
                "tags": ["agent", "memory"],
                "score": 1.0,
            },
        ),
    )
    graph_prompt = OpenAICompatibleGraphExtractor(
        DeepSeekConfig(),
    )._system_prompt()
    records = [
        _record(
            "surface.ime-continuation",
            "auxiliary-surface",
            "rag_ime/pi_runtime.py",
            "_IME_SURFACE_SYSTEM_PROMPT",
            "legacy ime-surface-v1 Session system prompt",
            "only if an operator explicitly reopens the retired Session profile",
            _IME_SURFACE_SYSTEM_PROMPT,
            status="compatibility",
            notes=(
                "The current Active RAG path does not create an ime-surface-v1 "
                "Session and does not send this system Prompt."
            ),
        ),
        _record(
            "surface.ime-continuation.request-example",
            "auxiliary-surface",
            "rag_ime/agent_surface_runtime.py",
            "_one_shot_surface_message",
            "separate stateless Pi user message",
            "representative explicit Active RAG generation with bounded AX context",
            pi_surface_message,
            status="representative",
            notes=(
                "This is the complete production model input: one user message "
                "with an instruction prefix and bounded JSON data, no system "
                "role, tools, Session history, images, or cache retention."
            ),
        ),
        _record(
            "surface.voice-refinement",
            "auxiliary-surface",
            "rag_ime/pi_runtime.py",
            "_VOICE_REFINEMENT_SYSTEM_PROMPT",
            "separate stateless Pi request",
            "third-pass voice transcript cleanup",
            _VOICE_REFINEMENT_SYSTEM_PROMPT,
            status="auxiliary",
        ),
        _record(
            "surface.voice-refinement.request-example",
            "auxiliary-surface",
            "rag_ime/agent_surface_runtime.py",
            "_voice_refinement_prompt",
            "separate internal no-tool Pi user message",
            "representative third-pass transcript cleanup",
            _voice_refinement_prompt(
                "嗯我们继续检查这个 Agent 提示词。",
                hotwords=["Agent", "Prompt"],
            ),
            status="representative",
        ),
        _record(
            "surface.deepseek-post-commit.system",
            "auxiliary-surface",
            "rag_ime/deepseek_completion.py",
            "build_deepseek_completion_messages",
            "separate direct DeepSeek post-commit side lane",
            "post-commit remote side candidate is enabled and a candidate slot remains",
            deepseek_post_commit_messages[0]["content"],
            status="auxiliary",
            notes=(
                "This is a production-conditional input-method side lane. "
                "It is not the ordinary Agent or Room identity."
            ),
        ),
        _record(
            "surface.deepseek-post-commit.user-example",
            "auxiliary-surface",
            "rag_ime/deepseek_completion.py",
            "build_deepseek_completion_messages",
            "separate direct DeepSeek post-commit side lane",
            "representative bounded context packet and memory evidence",
            deepseek_post_commit_messages[1]["content"],
            status="representative",
        ),
        _record(
            "surface.deepseek-active-rag.system",
            "auxiliary-surface",
            "rag_ime/deepseek_completion.py",
            "_build_active_rag_completion_messages",
            "separate direct DeepSeek compatibility preview",
            "debug preview or compatibility caller bypasses the production Pi surface",
            deepseek_active_rag_messages[0]["content"],
            status="compatibility",
            notes="The installed Agent Gateway production route uses Pi complete_once instead.",
        ),
        _record(
            "surface.deepseek-active-rag.user-example",
            "auxiliary-surface",
            "rag_ime/deepseek_completion.py",
            "_build_active_rag_completion_messages",
            "separate direct DeepSeek compatibility preview",
            "representative debug preview request",
            deepseek_active_rag_messages[1]["content"],
            status="representative",
        ),
        _record(
            "surface.knowledge-workbench.system",
            "auxiliary-surface",
            "rag_ime/knowledge_workbench.py",
            "build_knowledge_workbench_messages",
            "separate explicit knowledge Provider request",
            "user opens the knowledge workbench for recall, answer, or long-form writing",
            knowledge_messages[0]["content"],
            status="auxiliary",
        ),
        _record(
            "surface.knowledge-workbench.user-example",
            "auxiliary-surface",
            "rag_ime/knowledge_workbench.py",
            "build_knowledge_workbench_messages",
            "separate explicit knowledge Provider request",
            "representative knowledge-answer request with bounded evidence",
            knowledge_messages[1]["content"],
            status="representative",
        ),
        _record(
            "surface.knowledge-graph.system",
            "auxiliary-surface",
            "rag_ime/knowledge_library/graph_extractors.py",
            "OpenAICompatibleGraphExtractor._system_prompt",
            "separate offline knowledge graph Provider request",
            "knowledge graph extractor mode=model",
            graph_prompt,
            status="auxiliary",
        ),
    ]
    for filename, names in (
        (
            "rag_ime/mlx_predictor_server.py",
            (
                "SYSTEM_PROMPT",
                "STREAM_FIRST_SYSTEM_PROMPT",
                "SPACE_LIST_SYSTEM_PROMPT",
                "LOGITS_SYSTEM_PROMPT",
            ),
        ),
        (
            "rag_ime/predictor.py",
            (
                "OPENAI_CHAT_SYSTEM_PROMPT",
                "OLLAMA_CHAT_SYSTEM_PROMPT",
                "OLLAMA_STREAM_FIRST_SYSTEM_PROMPT",
            ),
        ),
    ):
        for name in names:
            content = _source_string_constant(ROOT / filename, name)
            if not content:
                continue
            records.append(
                _record(
                    f"surface.predictor.{name.lower()}",
                    "auxiliary-surface",
                    filename,
                    name,
                    "separate prediction request",
                    (
                        "MLX chat/instruction compatibility profile; not the current MiniMind Hot route"
                        if filename == "rag_ime/mlx_predictor_server.py"
                        else "local or remote input-method candidate generation"
                    ),
                    content,
                    status=(
                        "compatibility"
                        if filename == "rag_ime/mlx_predictor_server.py"
                        else "auxiliary"
                    ),
                    notes=(
                        "MiniMind 0.1B/100M base completion does not receive this text."
                        if filename == "rag_ime/mlx_predictor_server.py"
                        else "Kept outside ordinary Agent and Room prompts."
                    ),
                )
            )
    deep_search, _ = deep_search_prompt(
        {
            "context": "正在检查 Agent 的记忆触发与 Room 上下文。",
            "contextSource": "foreground_selection",
            "evidence": [
                {
                    "sourceType": "memory",
                    "title": "已确认的产品边界",
                    "memoryId": "memory-sample",
                    "evidencePreview": "项目以 Agent 为核心，输入法只是候选证据来源之一。",
                }
            ],
        },
        question="核对当前 Agent 记忆策略。",
    )
    records.extend(
        (
            _record(
                "surface.deep-search-example",
                "auxiliary-surface",
                "rag_ime/agent_prompt_support.py",
                "deep_search_prompt",
                "separate explicit Agent user message",
                "the user invokes deep search from the input surface",
                deep_search,
                status="auxiliary",
                notes=(
                    "This is a user-message payload for an explicit surface action, "
                    "not an Agent identity layer."
                ),
            ),
            _record(
                "surface.selected-text-rag-example",
                "auxiliary-surface",
                "rag_ime/predictor.py",
                "build_selected_text_rag_prompt",
                "separate prediction request",
                "the user explicitly asks for selected-text RAG candidates",
                build_selected_text_rag_prompt(
                    selected_text="Agent 记忆系统需要可追溯治理",
                    evidence_items=("输入法只提供候选证据",),
                    intent="rewrite",
                    max_candidates=3,
                ),
                status="auxiliary",
            ),
            _record(
                "surface.predictor.mlx-generic-example",
                "auxiliary-surface",
                "rag_ime/mlx_predictor_server.py",
                "_build_mlx_prompt",
                "separate local prediction request",
                "representative generic input-method continuation",
                _build_mlx_prompt(
                    current_input="jiyi",
                    recent_context="Agent 会在合适的时候记录",
                    max_candidates=3,
                    request_type=PREDICTION_REQUEST_GENERIC,
                    rime_candidates=("记忆", "建议"),
                ),
                status="compatibility",
                notes=(
                    "Representative Qwen/chat MLX payload. The current MiniMind "
                    "Hot path uses raw base completion instead."
                ),
            ),
            _record(
                "surface.predictor.mlx-no-input-example",
                "auxiliary-surface",
                "rag_ime/mlx_predictor_server.py",
                "_build_no_input_space_list_prompt",
                "separate local prediction request",
                "representative post-commit continuation with no active composition",
                _build_no_input_space_list_prompt(
                    recent_context="Agent 已经完成当前任务",
                    max_candidates=3,
                ),
                status="compatibility",
                notes=(
                    "Representative Qwen/chat MLX no-input payload. The current "
                    "MiniMind Hot path has no system Prompt."
                ),
            ),
        )
    )
    for request_type in (
        PREDICTION_REQUEST_GENERIC,
        PREDICTION_REQUEST_PINYIN_CONSTRAINED,
        PREDICTION_REQUEST_RIME_REORDER,
        PREDICTION_REQUEST_NO_INPUT,
        PREDICTION_REQUEST_ACTIVE_RAG,
    ):
        records.append(
            _record(
                f"surface.predictor.openai-{request_type}",
                "auxiliary-surface",
                "rag_ime/predictor.py",
                "_openai_prediction_system_prompt",
                "separate remote prediction request",
                f"requestType={request_type}",
                _openai_prediction_system_prompt(request_type),
                status="auxiliary",
            )
        )
    return records


def _tool_payloads() -> dict[str, object]:
    session = {
        "id": "agent:prompt-audit",
        "mode": "coordinator",
        "executionMode": "workspace_managed",
        "workspaceScopeGranted": True,
        "toolProfileVersion": "control-center-v1",
        "toolAllowlistMode": "profile",
        "allowedTools": [],
    }
    gateway = ControlToolGateway(
        sessions={str(session["id"]): session},  # type: ignore[arg-type]
        management=object(),  # type: ignore[arg-type]
        core=object(),
        project="wisdom-weasel-rag-ime",
    )
    product = [dict(item) for item in gateway.runtime_manifests(session)]
    room_registry = room_runtime_registry()
    room = [
        {
            "name": name,
            **{
                key: value
                for key, value in room_registry[name].items()
                if key
                in {
                    "description",
                    "when",
                    "notFor",
                    "input",
                    "output",
                    "does",
                    "risk",
                    "operation",
                    "inputSchema",
                }
            },
            "bootstrap": name in {"room_state", "room_post", "room_commit"},
            "deferred": name == "room_collaborate",
        }
        for name in ROOM_PUBLIC_TOOLS
    ]
    return {
        "productTools": product,
        "roomTools": room,
        "modelVisibleMemoryCapture": {
            "name": "memory_capture",
            "source": "pi-rag-ime-runtime/packages/rag-ime-runtime-host/src/memory-capture-tool.ts",
            "projectionTarget": {"name": "memory", "operation": "capture"},
            "note": (
                "The Product manifest keeps the backend capture branch for authorization; "
                "Pi removes that branch from memory's public schema and exposes this "
                "single runtime-owned Tool instead."
            ),
        },
    }


def _skill_payloads() -> dict[str, object]:
    skills: list[dict[str, object]] = []
    for path in sorted((ROOT / "integrations/pi/skills").glob("*/SKILL.md")):
        content = path.read_text(encoding="utf-8")
        encoded = content.encode("utf-8")
        skills.append(
            {
                "name": path.parent.name,
                "path": str(path.relative_to(ROOT)),
                "chars": len(content),
                "utf8Bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "content": content,
            }
        )
    cards_path = ROOT / "integrations/pi/skill-routing-cards.json"
    policy_path = ROOT / "integrations/pi/room-skill-policy.json"
    return {
        "skills": skills,
        "routingCards": json.loads(cards_path.read_text(encoding="utf-8")),
        "roomSkillPolicy": json.loads(policy_path.read_text(encoding="utf-8")),
    }


def discovered_prompt_symbols(root: Path = ROOT) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted((root / "rag_ime").glob("*.py")):
        filename = path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = f"{filename}::{node.name}"
                normalized_name = node.name.lower()
                if (
                    "prompt" in normalized_name
                    or "instruction" in normalized_name
                    or PROMPT_SYMBOL_CLASSIFICATION.get(symbol) == "bounded-prompt-input"
                ):
                    result[symbol] = "function"
                continue
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            is_string = isinstance(value, ast.Constant) and isinstance(value.value, str)
            if not is_string:
                continue
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and (
                        "prompt" in target.id.lower()
                        or "instruction" in target.id.lower()
                    )
                ):
                    result[f"{filename}::{target.id}"] = "constant"
    return result


def unclassified_prompt_symbols(root: Path = ROOT) -> list[str]:
    return sorted(set(discovered_prompt_symbols(root)) - set(PROMPT_SYMBOL_CLASSIFICATION))


def _git_revision(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            timeout=2,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _source_snapshot(
    *,
    snapshot_id: str,
    label: str,
    project: str,
    root: Path,
    relative_path: str,
    source_kind: str,
    start_line: int = 1,
    end_line: int | None = None,
    expected_text: Iterable[str] = (),
) -> dict[str, object]:
    path = root / relative_path
    if not path.is_file():
        return {
            "id": snapshot_id,
            "label": label,
            "project": project,
            "path": relative_path,
            "sourceKind": source_kind,
            "exists": False,
            "content": "",
        }
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    final_line = len(lines) if end_line is None else min(end_line, len(lines))
    if start_line < 1 or start_line > final_line:
        raise ValueError(f"invalid source selection for {relative_path}: {start_line}-{final_line}")
    content = "".join(lines[start_line - 1 : final_line])
    for expected in expected_text:
        if expected not in content:
            raise ValueError(
                f"source selection for {relative_path}:{start_line}-{final_line} "
                f"no longer contains {expected!r}"
            )
    encoded = content.encode("utf-8")
    return {
        "id": snapshot_id,
        "label": label,
        "project": project,
        "path": relative_path,
        "sourceKind": source_kind,
        "exists": True,
        "lineStart": start_line,
        "lineEnd": final_line,
        "totalLines": len(lines),
        "selection": f"L{start_line}-L{final_line}",
        "content": content,
        "chars": len(content),
        "utf8Bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _reference_comparison(cafe_root: Path, vcp_root: Path) -> dict[str, object]:
    references = [
        {
            "project": "Cafe",
            "path": "packages/api/src/domains/cats/services/context/SystemPromptBuilder.ts",
            "mechanism": "static identity layers plus per-invocation context and prompt capture",
            "decision": "adopt layered ownership and X-ray",
            "excerpt": "static layers + per-invocation context + prompt capture",
        },
        {
            "project": "Cafe",
            "path": "assets/prompt-templates/l5-mcp-tools-index.md",
            "mechanism": "short tool-family index, detailed specs deferred",
            "decision": "adopt compact route cards and exact schema loading",
            "excerpt": "工具未暴露时：先用 tool_search 精确搜工具名加载",
        },
        {
            "project": "Cafe",
            "path": "assets/prompt-templates/l6-capability-wakeup.md",
            "mechanism": "positive trigger maps hesitation to an exact Skill or Tool",
            "decision": "adopt positive wake-up rules",
            "excerpt": "记一下 / 以后这样 / 别再这样 -> propose_profile_update",
        },
        {
            "project": "Cafe",
            "path": "cat-cafe-skills/refs/shared-rules.md",
            "mechanism": "durable knowledge is extracted and reviewed instead of silently promoted",
            "decision": "adopt candidate memory plus governance; reject giant shared world prompt",
            "excerpt": "阶段进度给下棒可见 -> 更新工作流告示牌",
        },
        {
            "project": "VCP",
            "path": "Agent/Aemeath.txt",
            "mechanism": "positive diary trigger after a valuable topic; update the same event",
            "decision": "adopt positive trigger and same-fact dedupe; reject direct free-form durable write",
            "excerpt": "产生有价值的话题或新知识时主动记录；同一件事更新同一日记",
        },
        {
            "project": "VCP",
            "path": "Plugin/AgentAssistant/AgentAssistant.js",
            "mechanism": "delegation heartbeat waits for free-form completion markers",
            "decision": "reject unbounded heartbeat; Kernel owns evidence and continuation budgets",
            "excerpt": "任务仍在进行中，请继续；完成时输出 TaskComplete",
        },
    ]
    roots = {"Cafe": cafe_root, "VCP": vcp_root}
    for item in references:
        path = roots[str(item["project"])] / str(item["path"])
        item["exists"] = path.is_file()
    snapshots = [
        _source_snapshot(
            snapshot_id="cafe.identity",
            label="角色身份短层",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/s1-identity.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("NAME_LABEL", "ROLE_DESCRIPTION", "PERSONALITY"),
        ),
        _source_snapshot(
            snapshot_id="cafe.restrictions",
            label="角色硬限制短层",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/s2-restrictions.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("硬限制", "push back"),
        ),
        _source_snapshot(
            snapshot_id="cafe.prompt-builder.static-dynamic",
            label="静态身份与每轮动态上下文分层",
            project="Cafe",
            root=cafe_root,
            relative_path="packages/api/src/domains/cats/services/context/SystemPromptBuilder.ts",
            source_kind="最终源码",
            start_line=437,
            end_line=518,
            expected_text=("buildStaticIdentity", "buildInvocationContext"),
        ),
        _source_snapshot(
            snapshot_id="cafe.prompt-builder.compose",
            label="最终 System Prompt 组合入口",
            project="Cafe",
            root=cafe_root,
            relative_path="packages/api/src/domains/cats/services/context/SystemPromptBuilder.ts",
            source_kind="最终源码",
            start_line=623,
            end_line=645,
            expected_text=("buildSystemPrompt", "parts.join"),
        ),
        _source_snapshot(
            snapshot_id="cafe.tool-index",
            label="常驻短 Tool 索引",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/l5-mcp-tools-index.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("工具未暴露时", "tool_search"),
        ),
        _source_snapshot(
            snapshot_id="cafe.capability-wakeup",
            label="正向能力唤醒规则",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/l6-capability-wakeup.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("propose_profile_update", "完整集"),
        ),
        _source_snapshot(
            snapshot_id="cafe.cross-cat-handoff",
            label="跨 Agent 交接 Skill",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/cross-cat-handoff/SKILL.md",
            source_kind="按需 Skill",
            expected_text=("Use when", "Not for", "What", "Why", "Next"),
        ),
        _source_snapshot(
            snapshot_id="cafe.quality-gate",
            label="任务质量门 Skill",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/quality-gate/SKILL.md",
            source_kind="按需 Skill",
            expected_text=("Quality Gate", "验证命令输出"),
        ),
        _source_snapshot(
            snapshot_id="cafe.requirement-interview",
            label="需求采访与 Design Gate",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/feat-lifecycle/SKILL.md",
            source_kind="按需 Skill",
            start_line=137,
            end_line=177,
            expected_text=("采访式（默认）", "Design Gate", "User Journey"),
        ),
        _source_snapshot(
            snapshot_id="cafe.routing-handoff",
            label="下一棒路由决策树",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/l3-routing-rules.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("接球先问", "下一棒传球决策树", "review 完"),
        ),
        _source_snapshot(
            snapshot_id="cafe.review-law",
            label="跨个体 Review 硬规则",
            project="Cafe",
            root=cafe_root,
            relative_path="assets/prompt-templates/l4-iron-laws.md",
            source_kind="运行时 Prompt 模板",
            expected_text=("Review 必须跨个体", "自己的代码由别人 review"),
        ),
        _source_snapshot(
            snapshot_id="cafe.review-roster",
            label="Reviewer 动态匹配与降级",
            project="Cafe",
            root=cafe_root,
            relative_path="packages/api/src/domains/cats/services/context/SystemPromptBuilder.ts",
            source_kind="最终源码",
            start_line=522,
            end_line=620,
            expected_text=("buildReviewerSection", "Skip self", "crossFamily"),
        ),
        _source_snapshot(
            snapshot_id="cafe.fresh-context-review",
            label="预扫发现与正式裁决分离",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/fresh-context-review/SKILL.md",
            source_kind="按需 Skill",
            start_line=19,
            end_line=31,
            expected_text=("FINDING GENERATOR", "not an approval authority"),
        ),
        _source_snapshot(
            snapshot_id="cafe.request-review",
            label="正式 Review 前置条件与匹配规则",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/request-review/SKILL.md",
            source_kind="按需 Skill",
            start_line=24,
            end_line=46,
            expected_text=("原始需求可引用", "Reviewer 匹配规则", "不能 review 自己"),
        ),
        _source_snapshot(
            snapshot_id="cafe.context-self-management",
            label="压缩、续作与 Session 交接判断",
            project="Cafe",
            root=cafe_root,
            relative_path="cat-cafe-skills/context-self-management/SKILL.md",
            source_kind="按需 Skill",
            start_line=1,
            end_line=43,
            expected_text=("context_management_hint", "五件套", "2×2 决策矩阵"),
        ),
        _source_snapshot(
            snapshot_id="vcp.agent-persona",
            label="角色行为、语气与持久记忆声明",
            project="VCP",
            root=vcp_root,
            relative_path="Agent/Aemeath.txt",
            source_kind="Agent Prompt 模板",
            start_line=135,
            end_line=176,
            expected_text=("你的行为准则", "你的说话风格", "拥有持久记忆"),
        ),
        _source_snapshot(
            snapshot_id="vcp.agent-memory",
            label="角色主动日记与去重规则",
            project="VCP",
            root=vcp_root,
            relative_path="Agent/Aemeath.txt",
            source_kind="Agent Prompt 模板",
            start_line=177,
            end_line=220,
            expected_text=("DailyNote", "不要盲目记日记", "同一件事写同一个日记"),
        ),
        _source_snapshot(
            snapshot_id="vcp.agent-environment",
            label="环境与 Tool 列表拼接入口",
            project="VCP",
            root=vcp_root,
            relative_path="Agent/Aemeath.txt",
            source_kind="Agent Prompt 模板",
            start_line=218,
            end_line=221,
            expected_text=("TarSysPrompt", "VarToolList"),
        ),
        _source_snapshot(
            snapshot_id="vcp.delegation-prompt",
            label="异步任务完成与失败标记",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/AgentAssistant/AgentAssistant.js",
            source_kind="最终源码内置 Prompt",
            start_line=163,
            end_line=170,
            expected_text=("TaskComplete", "TaskFailed", "HEARTBEAT"),
        ),
        _source_snapshot(
            snapshot_id="vcp.delegation-loop",
            label="异步委托循环与停止条件",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/AgentAssistant/AgentAssistant.js",
            source_kind="最终源码",
            start_line=817,
            end_line=942,
            expected_text=("DELEGATION_MAX_ROUNDS", "DELEGATION_TIMEOUT", "TaskComplete"),
        ),
        _source_snapshot(
            snapshot_id="vcp.temporary-tools",
            label="单次临时 Tool 注入",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/AgentAssistant/AgentAssistant.js",
            source_kind="最终源码内置 Prompt",
            start_line=470,
            end_line=498,
            expected_text=("临时工具组注入", "本次通讯"),
        ),
        _source_snapshot(
            snapshot_id="vcp.toolbox-fold",
            label="长尾 Tool 动态折叠实现",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/ToolBoxFoldMemo/toolbox-fold.js",
            source_kind="最终源码",
            expected_text=("vcp_dynamic_fold", "toolbox_block_similarity"),
        ),
        _source_snapshot(
            snapshot_id="vcp.agent-assistant-manifest",
            label="直接委托 Agent 的 Tool 说明（对照：无需求确认门）",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/AgentAssistant/plugin-manifest.json",
            source_kind="Plugin Tool 描述",
            start_line=1,
            end_line=32,
            expected_text=("AgentAssistant", "temporary_contact", "task_delegation"),
        ),
        _source_snapshot(
            snapshot_id="vcp.context-folding",
            label="语义折叠摘要 Prompt",
            project="VCP",
            root=vcp_root,
            relative_path="Plugin/ContextFoldingV2/ContextFoldingV2.js",
            source_kind="最终源码内置 Prompt",
            start_line=502,
            end_line=543,
            expected_text=("VCP上下文语义折叠", "summarySystemPrompt", "内容已截断"),
        ),
        _source_snapshot(
            snapshot_id="vcp.toolbox-index",
            label="Tool 分层内容示例",
            project="VCP",
            root=vcp_root,
            relative_path="TVStxt/MemoToolBox.txt",
            source_kind="运行时 Tool 文档",
            expected_text=("vcp_fold", "LightMemo"),
        ),
    ]
    comparison_cases = [
        {
            "id": "identity-and-rails",
            "title": "Agent 身份、人格与硬边界",
            "question": "怎样让角色有辨识度，又不把安全、权限、记忆和任务流程塞进人格？",
            "status": "实现完成，待用户审定",
            "localPromptIds": [
                "agent.core.safety",
                "agent.persona.companion-present-v1",
            ],
            "localSkillNames": [],
            "upstreamSnapshotIds": [
                "cafe.identity",
                "cafe.restrictions",
                "vcp.agent-persona",
            ],
            "decision": "保留 Cafe 式短身份层与独立硬限制层；只吸收 VCP 的角色鲜活度，不复制把世界观、用户关系、持久记忆声明和工具入口混成一个长 Persona 的做法。",
            "whyBetter": "身份只回答“我是谁、怎样表达”，安全与权限有唯一 owner，记忆触发另归 Durable Memory Policy；这样普通 Agent、Room 和子 Agent 可以共享治理而不共享人设。",
            "residualRisk": "Persona 文案仍需用户逐段确认语气；任何提到“拥有全部用户输入”或“已经记住”的句子都应判为越权。",
        },
        {
            "id": "prompt-layering",
            "title": "固定 Prompt 与每轮上下文如何分层",
            "question": "哪些内容保持稳定以利于缓存，哪些内容只能在当前调用增量追加？",
            "status": "结构与缓存不变量已验证",
            "localPromptIds": [
                "agent.composed.assistant-example",
                "room.composed.stable-prefix-example",
            ],
            "localSkillNames": [],
            "upstreamSnapshotIds": [
                "cafe.prompt-builder.static-dynamic",
                "cafe.prompt-builder.compose",
                "vcp.agent-environment",
            ],
            "decision": "采用 Cafe 的静态/动态 owner 分层与可观察组合；不采用 VCP 把系统信息和 Tool 列表集中拼在角色模板尾部的弱类型边界。",
            "whyBetter": "稳定身份、安全、能力规则保持缓存前缀；Room 事实、当前责任和本轮输入只按顺序追加，既能追责，也不会把临时状态写回 Persona。",
            "residualRisk": "真实 Provider KV cache 仍必须在 Prompt 冻结后实测；对象顺序正确不能单独证明上游实际命中。",
        },
        {
            "id": "alignment-and-decision",
            "title": "对齐、追问、方案决策与执行门",
            "question": "用户只给目标时，什么时候追问、追问到什么程度、何时才允许创建执行任务？",
            "status": "实现完成，待用户审定",
            "localPromptIds": ["room.dynamic.alignment-and-decision"],
            "localSkillNames": ["alignment-and-decision"],
            "upstreamSnapshotIds": [
                "cafe.requirement-interview",
                "vcp.agent-assistant-manifest",
            ],
            "decision": "采用单一 alignment-and-decision：先查事实、一次只问一个关键问题、冻结需求后再收敛方案；只有用户明确要求时才把直接确认的决定写入术语表、ADR 或决策文档。",
            "whyBetter": "一个受管技能同时覆盖范围、验收、重大方案取舍和可选持久记录，避免四个入口重复提问；需求与方案仍由内部阶段门隔离，确认不会创建任务或授予实施权限，Kernel 继续独占执行状态。",
            "residualRisk": "当前追问质量仍依赖 Skill 文案；需要用模糊需求、已明确需求和用户拒绝继续澄清三类对话验收。",
        },
        {
            "id": "progressive-disclosure",
            "title": "Skill / Tool 渐进披露",
            "question": "模型如何先知道能力存在，又不在首轮加载全部正文与 schema？",
            "status": "实现与缓存不变量已验证",
            "localPromptIds": ["agent.capabilities.progressive"],
            "localSkillNames": [],
            "upstreamSnapshotIds": [
                "cafe.tool-index",
                "cafe.capability-wakeup",
                "vcp.toolbox-fold",
                "vcp.toolbox-index",
                "vcp.temporary-tools",
            ],
            "decision": "采用 Cafe 的短索引和正向触发、VCP 的分层发现思想；本项目用结构化 search/load 回执渐进披露，且同一 Context Epoch 的 skill_load 只追加 Tool Result，绝不回写已有 systemPrompt 字节。",
            "whyBetter": "一个 skill_load 调用一份 Skill 是接口边界，不是整项任务只能用一份；同一模型轮次可并列加载最多两份互补 Skill，Tool 则可按同一步一次加载 1 至 4 个精确 schema。Runtime 检索结果可排除已加载项，但稳定家族索引到新 Epoch 前保持原字节。",
            "residualRisk": "必须实测重复 search/load 被 Runtime 拒绝、systemPrompt 前缀逐字不变，以及压缩后只在新 Epoch 精确恢复一份已加载正文。",
        },
        {
            "id": "durable-memory",
            "title": "主动记忆何时触发、如何去重",
            "question": "哪些用户信息值得长期保留，模型能否直接修改权威记忆？",
            "status": "实现完成，待用户审定",
            "localPromptIds": [
                "agent.core.durable-memory",
                "memory.default-instruction",
            ],
            "localSkillNames": ["memory-curation"],
            "upstreamSnapshotIds": [
                "cafe.capability-wakeup",
                "vcp.agent-memory",
            ],
            "decision": "采用 Cafe/VCP 的正向触发与同一事实更新思想；本项目先写结构化候选，再由现有记忆治理链审阅、合并和提升，避免自由文本直接成为权威事实。",
            "whyBetter": "稳定 Prompt 只解释 Evidence、Candidate、Current Atom、Topic Book、Timeline 与 Role Book 的边界；完整去重、冲突和组织流程留在 memory-curation Skill，模型不能猜内部 ID。",
            "residualRisk": "触发规则要继续用普通闲聊、泛泛表扬、临时进度、纠正和项目决定做误触发/漏触发测试；正式记忆仍不能由模型一次调用直接生效。",
        },
        {
            "id": "review-separation",
            "title": "Reviewer 是模板、Room 岗位还是质量门",
            "question": "什么时候需要 reviewer，谁来选 reviewer，审查结论能否真正阻止错误交付？",
            "status": "实现完成，待用户审定",
            "localPromptIds": [
                "agent.template.reviewer",
                "room.role.reviewer",
                "room.profile.evidence-review",
            ],
            "localSkillNames": ["independent-review", "quality-gate"],
            "upstreamSnapshotIds": [
                "cafe.review-law",
                "cafe.review-roster",
                "cafe.fresh-context-review",
                "cafe.request-review",
                "vcp.agent-assistant-manifest",
            ],
            "decision": "保留两个不同作用域：agent.template.reviewer 是普通子 Agent 的只读任务模板，room.role.reviewer 是 Room 当前 Dispatch 的工作视角；真正需要独立放行时由 evidence-review Profile 与 Kernel peer-review gate 要求不同 Session，不能只靠角色自称。",
            "whyBetter": "吸收 Cafe 的跨个体、跨模型族优先、预扫与正式 verdict 分离；吸收 VCP 按任务选择合适 Agent 的灵活性，但由结构化 reviewer 资格、原始需求、证据覆盖和 Kernel 回执约束结果。",
            "residualRisk": "标准 Room 不应为每个低风险任务强制审查；UI 和审计必须把“子 Agent 模板”和“Room 工作岗位”标清，避免同名 reviewer 被误解成重复注入。",
        },
        {
            "id": "task-settlement",
            "title": "任务循环、验收与停止",
            "question": "模型自称完成后谁裁决？未完成、无进展或无法完成时怎样退出？",
            "status": "实现完成，待用户审定",
            "localPromptIds": [
                "agent.core.managed-work",
                "room.dynamic.managed-task",
                "room.settle.continue",
                "room.settle.repair",
            ],
            "localSkillNames": [
                "implementation-execution",
                "quality-gate",
            ],
            "upstreamSnapshotIds": [
                "cafe.quality-gate",
                "vcp.delegation-prompt",
                "vcp.delegation-loop",
            ],
            "decision": "吸收 Cafe 的证据化质量门和 VCP 的完成/失败/轮数/超时出口；最终由本项目 Kernel 根据结构化验收回执、无进展预算、取消栅栏与深度限制裁决，而不是仅匹配自由文本标记。",
            "whyBetter": "模型只提出继续、完成、交接、等待或阻塞，Kernel 核对当前 Task 的 AC 别名和成功 evidenceRef；重复失败不会因为一句“继续”获得无限轮次。",
            "residualRisk": "复杂任务仍需验证模型在能力不足时会正确 handoff/wait/blocked，而不是伪造 AC、重复调用或提前 deliver。",
        },
        {
            "id": "collaboration-handoff",
            "title": "多 Agent 提问、交接与继续执行",
            "question": "中途询问、正确移交和完成后的责任边界怎样写进 Prompt？",
            "status": "实现完成，待用户审定",
            "localPromptIds": [
                "room.dynamic.alignment-and-decision",
                "room.dynamic.intercom-question",
                "room.dispatch.trigger",
                "agent.delegation.subagent-example",
            ],
            "localSkillNames": ["structured-handoff"],
            "upstreamSnapshotIds": [
                "cafe.cross-cat-handoff",
                "cafe.routing-handoff",
                "vcp.temporary-tools",
                "vcp.delegation-prompt",
                "vcp.agent-assistant-manifest",
            ],
            "decision": "采用 Cafe 的 What/Why/Tradeoff/Open/Next 交接完整性和 VCP 的单次能力注入；路由、任务归属、继续条件与取消仍由 Room Kernel 的结构化状态机负责。",
            "whyBetter": "Agent 可以在自己的任务中间向另一成员提问并继续工作，也可以用 room_commit.handoff 明确移交；普通对话文本中的 @ 不承担数据库路由真相。",
            "residualRisk": "仍要用“询问后继续、A 交给 B、B 再交回 A、取消中途到达”四条真实链验证去重、深度和取消传播。",
        },
        {
            "id": "compaction-recovery",
            "title": "压缩后的恢复包与上下文换代",
            "question": "压缩后怎样一次补回原始需求、当前任务、验收、阻塞、交接和精确能力回执？",
            "status": "实现与单次恢复已验证",
            "localPromptIds": ["room.compaction.recovery-example"],
            "localSkillNames": ["structured-handoff"],
            "upstreamSnapshotIds": [
                "cafe.context-self-management",
                "vcp.context-folding",
            ],
            "decision": "采用 Cafe 对“继续、压缩、冲刺到断点、换 Session”的显式判断和 VCP 的有界摘要思想；本项目每个新 context epoch 只注入一份结构化恢复包，不在同一上下文连续补三遍。",
            "whyBetter": "原始需求保持不可变来源，当前任务与 AC 可修订，Skill/Tool 只恢复精确回执；这比自由文本一句话摘要更能防止交接和验收条件遗忘。",
            "residualRisk": "恢复包正确不等于缓存命中；还需实测 epoch 切换前后 stable prefix、一次恢复、Tool 顺序只追加及真实 Provider cache usage。",
        },
    ]
    return {
        "references": references,
        "projectRevisions": {
            "Product": _git_revision(ROOT),
            "Cafe": _git_revision(cafe_root),
            "VCP": _git_revision(vcp_root),
        },
        "sourceSnapshots": snapshots,
        "comparisonCases": comparison_cases,
        "summary": {
            "adopt": [
                "Cafe layered prompt ownership and inspectable segments",
                "Cafe short capability index with progressive disclosure",
                "VCP positive memory trigger and same-event update",
                "this Product's deterministic Kernel settle and recovery fences",
            ],
            "reject": [
                "one giant persona/tool/shared-rules prompt",
                "free-form diary text as authoritative memory",
                "heartbeat loops without evidence, depth, cancellation, and no-progress gates",
            ],
        },
    }


def _deterministic_provider_evidence(
    *,
    evidence_root: Path = DETERMINISTIC_EVIDENCE_ROOT,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for scenario, label, directory in (
        ("agent-session", "普通 Agent", "provider-agent-deterministic"),
        ("project-collaboration", "三成员 Room", "provider-room-deterministic"),
    ):
        audit_path = evidence_root / directory / "audit.json"
        item: dict[str, object] = {
            "scenario": scenario,
            "label": label,
            "directory": directory,
            "auditPath": f"{directory}/audit.json",
            "reviewPath": f"{directory}/README.md",
            "available": audit_path.is_file(),
        }
        if not audit_path.is_file():
            evidence.append(item)
            continue
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        checks = payload.get("checks")
        check_values = list(checks.values()) if isinstance(checks, Mapping) else []
        item.update(
            {
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "providerCallCount": payload.get("providerCallCount", 0),
                "toolExecutionCount": payload.get("toolExecutionCount", 0),
                "compactionCount": payload.get("compactionCount", 0),
                "externalRequestCount": payload.get("externalRequestCount", 0),
                "allChecksPassed": bool(check_values)
                and all(value is True for value in check_values),
            }
        )
        evidence.append(item)
    return evidence


def _deterministic_calls(
    directory: str,
    *,
    evidence_root: Path = DETERMINISTIC_EVIDENCE_ROOT,
) -> list[dict[str, object]]:
    calls_dir = evidence_root / directory / "calls"
    if not calls_dir.is_dir():
        return []
    calls = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(calls_dir.glob("*.json"))
    ]
    return sorted(
        (item for item in calls if isinstance(item, dict)),
        key=lambda item: (
            int(item.get("capturedAtMs") or 0),
            int(item.get("callIndex") or 0),
        ),
    )


def _provider_prompt(call: Mapping[str, object]) -> str:
    context = call.get("providerContext")
    if not isinstance(context, Mapping):
        return ""
    return str(context.get("systemPrompt") or "")


def _xml_block(text: str, tag: str) -> str:
    match = re.search(
        rf"<{re.escape(tag)}\b[^>]*>.*?</{re.escape(tag)}>",
        text,
        re.DOTALL,
    )
    return match.group(0) if match is not None else ""


def _skill_catalog_projection(prompt: str) -> str:
    family_position = prompt.find("<skill_capability_families")
    end_marker = "</available_skills>"
    end_position = prompt.find(end_marker, family_position)
    if family_position < 0 or end_position < 0:
        return ""
    prelude = "The following capability-family index is stable for this context epoch"
    start_position = prompt.rfind(prelude, 0, family_position)
    if start_position < 0:
        start_position = family_position
    return prompt[start_position : end_position + len(end_marker)]


def _tool_catalog_projection(prompt: str) -> str:
    start_position = prompt.find("<product_tool_capability_families")
    end_marker = "</available_product_tools>"
    end_position = prompt.find(end_marker, start_position)
    if start_position < 0 or end_position < 0:
        return ""
    return prompt[start_position : end_position + len(end_marker)]


def _tool_result_text(call: Mapping[str, object], tool_name: str) -> str:
    context = call.get("providerContext")
    messages = context.get("messages") if isinstance(context, Mapping) else None
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if (
            not isinstance(message, Mapping)
            or message.get("role") != "toolResult"
            or message.get("toolName") != tool_name
        ):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "text"
        )
    return ""


def _pi_runtime_prompt_records(
    *,
    evidence_root: Path = DETERMINISTIC_EVIDENCE_ROOT,
) -> list[PromptRecord]:
    agent_calls = _deterministic_calls(
        "provider-agent-deterministic",
        evidence_root=evidence_root,
    )
    room_calls = _deterministic_calls(
        "provider-room-deterministic",
        evidence_root=evidence_root,
    )
    if not agent_calls and not room_calls:
        return []

    records: list[PromptRecord] = []
    runtime_note = (
        "来自确定性 Pi Agent Loop 的精确 Provider 对象；证明实际组装，"
        "不冒充外部 Provider wire 或真实 KV cache。"
    )

    def append_projection(
        *,
        prompt_id: str,
        source_path: str,
        producer: str,
        phase: str,
        condition: str,
        content: str,
        notes: str = runtime_note,
    ) -> None:
        if not content:
            raise ValueError(f"missing Pi Runtime projection evidence: {prompt_id}")
        records.append(
            _record(
                prompt_id,
                "pi-runtime-evidence",
                source_path,
                producer,
                phase,
                condition,
                content,
                status="runtime-evidence",
                notes=notes,
            )
        )

    if agent_calls:
        agent_prompt = _provider_prompt(agent_calls[0])
        append_projection(
            prompt_id="pi.runtime.skill-catalog.agent-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/coding-agent/src/core/skills.ts"
            ),
            producer="formatSkillsForPrompt",
            phase="initial stable prefix / runtime evidence",
            condition="普通 Agent 首次 Provider 请求",
            content=_skill_catalog_projection(agent_prompt),
        )
        append_projection(
            prompt_id="pi.runtime.tool-catalog.agent-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/discovery-tools.ts"
            ),
            producer="formatBackendToolRouteCatalog",
            phase="initial stable prefix / runtime evidence",
            condition="普通 Agent 首次 Provider 请求",
            content=_tool_catalog_projection(agent_prompt),
        )
        append_projection(
            prompt_id="pi.runtime.workflow.agent-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/workflow-control.ts"
            ),
            producer="replaceWorkflowBlock",
            phase="current epoch managed context / runtime evidence",
            condition="普通 Agent 首次 Provider 请求",
            content=_xml_block(agent_prompt, "workflow-state"),
        )
        append_projection(
            prompt_id="pi.runtime.session-memory.agent-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/provider-context-journal.ts"
            ),
            producer="ProviderContextJournal",
            phase="current epoch append-only context / runtime evidence",
            condition="普通 Agent 首次 Provider 请求",
            content=_xml_block(agent_prompt, "rag-ime-context"),
        )

        loaded_result = next(
            (
                result
                for call in agent_calls
                if (result := _tool_result_text(call, "skill_load"))
            ),
            "",
        )
        append_projection(
            prompt_id="pi.runtime.skill-load.tool-result.agent-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/discovery-tools.ts"
            ),
            producer="loadSkill",
            phase="current epoch Tool Result only / runtime evidence",
            condition="skill_load 成功后下一次模型请求",
            content=loaded_result,
            notes=(
                f"{runtime_note} 同一 Epoch 的 systemPrompt 前后字节和 SHA-256 "
                "必须完全相同。"
            ),
        )
        restored = next(
            (
                loaded_result
                for call in agent_calls
                if loaded_result
                and loaded_result in _provider_prompt(call)
            ),
            "",
        )
        if restored != loaded_result:
            raise ValueError(
                "loaded Skill Tool Result was not restored byte-for-byte "
                "after compaction"
            )
        append_projection(
            prompt_id=(
                "pi.runtime.skill-load.compaction-restore.agent-example"
            ),
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/discovery-tools.ts"
            ),
            producer="createDiscoveryToolsExtension.session_compact",
            phase="next epoch stable prefix / runtime evidence",
            condition="压缩成功并创建新 Context Epoch",
            content=restored,
            notes=(
                f"{runtime_note} 内容与上一 Epoch 的 skill_load Tool Result "
                "逐字节相同。"
            ),
        )

    if room_calls:
        room_prompt = _provider_prompt(room_calls[0])
        append_projection(
            prompt_id="pi.runtime.skill-catalog.room-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/coding-agent/src/core/skills.ts"
            ),
            producer="formatSkillsForPrompt",
            phase="initial stable prefix / runtime evidence",
            condition="三成员 Room 成员首次 Provider 请求",
            content=_skill_catalog_projection(room_prompt),
        )
        append_projection(
            prompt_id="pi.runtime.tool-catalog.room-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/discovery-tools.ts"
            ),
            producer="formatBackendToolRouteCatalog",
            phase="initial stable prefix / runtime evidence",
            condition="三成员 Room 成员首次 Provider 请求",
            content=_tool_catalog_projection(room_prompt),
        )
        append_projection(
            prompt_id="pi.runtime.workflow.room-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/workflow-control.ts"
            ),
            producer="replaceWorkflowBlock",
            phase="current epoch managed context / runtime evidence",
            condition="三成员 Room 成员首次 Provider 请求",
            content=_xml_block(room_prompt, "workflow-state"),
        )
        room_context_match = re.search(
            r'<rag-ime-context type="room_context">.*?</rag-ime-context>',
            room_prompt,
            re.DOTALL,
        )
        append_projection(
            prompt_id="pi.runtime.room-context.room-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/provider-context-journal.ts"
            ),
            producer="ProviderContextJournal",
            phase="current epoch append-only Room context / runtime evidence",
            condition="三成员 Room 成员首次 Provider 请求",
            content=(
                room_context_match.group(0)
                if room_context_match is not None
                else ""
            ),
        )
        required_skill = _xml_block(room_prompt, "loaded_skill")
        append_projection(
            prompt_id="pi.runtime.required-skill.room-example",
            source_path=(
                "../pi-rag-ime-runtime/packages/rag-ime-runtime-host/"
                "src/pi-session.ts"
            ),
            producer="systemPromptOverride",
            phase="before AgentSession creation / stable prefix",
            condition="Room 阶段策略固定一个必需 Skill",
            content=required_skill,
        )

    return records


def _model_request_routes(
    records: Iterable[PromptRecord],
    *,
    pi_root: Path,
) -> list[dict[str, object]]:
    prompt_ids = {record.prompt_id for record in records}
    routes: list[dict[str, object]] = []
    for raw in MODEL_REQUEST_ROUTE_SPECS:
        route = dict(raw)
        source_root = str(route.pop("sourceRoot"))
        source_path = str(route["sourcePath"])
        source_file = source_path.split("::", 1)[0]
        root = pi_root if source_root == "pi" else ROOT
        referenced_prompts = [str(value) for value in route.get("promptIds", [])]
        route["sourceRoot"] = source_root
        route["sourceExists"] = (root / source_file).is_file()
        route["missingPromptIds"] = [
            prompt_id
            for prompt_id in referenced_prompts
            if prompt_id not in prompt_ids
        ]
        routes.append(route)
    return routes


def build_audit(
    *,
    pi_root: Path = DEFAULT_PI_ROOT,
    cafe_root: Path = DEFAULT_CAFE_ROOT,
    vcp_root: Path = DEFAULT_VCP_ROOT,
    evidence_root: Path = DETERMINISTIC_EVIDENCE_ROOT,
) -> dict[str, object]:
    records = (
        _ordinary_prompt_records()
        + _room_prompt_records()
        + _memory_prompt_records()
        + _auxiliary_prompt_records()
        + _pi_runtime_prompt_records(evidence_root=evidence_root)
    )
    unclassified = unclassified_prompt_symbols(ROOT)
    deterministic_evidence = _deterministic_provider_evidence(
        evidence_root=evidence_root,
    )
    deterministic_passed = bool(deterministic_evidence) and all(
        item.get("available") is True and item.get("allChecksPassed") is True
        for item in deterministic_evidence
    )
    model_request_routes = _model_request_routes(records, pi_root=pi_root)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "productRoot": str(ROOT),
        "piRoot": str(pi_root),
        "deterministicEvidenceRoot": str(evidence_root),
        "promptRecords": [record.payload() for record in records],
        "promptSymbolInventory": {
            "discovered": discovered_prompt_symbols(ROOT),
            "classification": dict(sorted(PROMPT_SYMBOL_CLASSIFICATION.items())),
            "unclassified": unclassified,
        },
        "piRuntimePromptProducerInventory": {
            name: {
                "source": source,
                "exists": (
                    pi_root / source.split("::", 1)[0]
                ).is_file(),
            }
            for name, source in PI_RUNTIME_PROMPT_PRODUCERS.items()
        },
        "modelRequestRoutes": model_request_routes,
        "tools": _tool_payloads(),
        "skills": _skill_payloads(),
        "references": _reference_comparison(cafe_root, vcp_root),
        "deterministicEvidence": deterministic_evidence,
        "findings": [
            {
                "status": "fixed",
                "issue": "普通 Agent 模板曾继承 Room 协作职责",
                "result": "普通 Session mode 与 Room PromptPlan 已由不同生产者负责",
            },
            {
                "status": "fixed",
                "issue": "离线记忆 Prompt 曾把产品描述成输入法",
                "result": "记忆治理已改为 Agent-first；输入法只是证据与词库来源之一",
            },
            {
                "status": "fixed",
                "issue": "记忆候选捕获曾有两条模型可见语义路径",
                "result": "memory_capture 是唯一公开捕获 Tool；memory.capture 只作为隐藏投影目标",
            },
            {
                "status": "fixed",
                "issue": "Tool 能力家族曾把多数 ime_* Tool 错归为输入法",
                "result": "现在按 Agent、记忆、知识、浏览器、插件、语音、输入和系统职责分别披露",
            },
            {
                "status": "fixed",
                "issue": "Room 压缩恢复包曾暴露数据库验收 ID 和相互矛盾的状态布尔值",
                "result": (
                    "模型现在只看到 AC-1 等公开别名，以及 verified、"
                    "evidence_available、pending 三种可解释状态"
                ),
            },
            {
                "status": "fixed",
                "issue": "标准 Room 曾把空的 Profile layer 标签写入最终 systemPrompt",
                "result": (
                    "PromptPlan 仍审计 omitted layer，但 Provider Prompt 对零字节层"
                    "执行字面 no-op；非空审核 Profile 仍按固定顺序注入"
                ),
            },
            {
                "status": "intentional",
                "issue": "IME、语音和预测器 Prompt 仍会提到输入法",
                "result": "它们是隔离的无状态辅助面，不会成为普通 Agent 或 Room 身份",
            },
            {
                "status": "verified",
                "issue": "当前 MiniMind 0.1B / 100M Hot 模型是否有 System Prompt",
                "result": (
                    "没有；当前 base-completion 路由只发送最多 360 字符的原始续写前缀，"
                    "旧 MLX Chat/Instruction 模板已单列为兼容路径"
                ),
            },
            {
                "status": "fixed",
                "issue": "Active RAG 单次生成的思考强度配置是否能被 Pi Host 接受",
                "result": (
                    "已对齐：Pi completion.once 接受完整思考等级并按模型能力校验；"
                    "该路由仍没有 system role，指令位于单条 user message 前缀"
                ),
            },
            {
                "status": (
                    "deterministic-passed"
                    if deterministic_passed
                    else "deterministic-evidence-missing"
                ),
                "issue": "最终 Pi Agent Loop 的 systemPrompt、messages、tools 与 Tool 回执",
                "result": (
                    "普通 Agent 与三成员 Room 的逐调用对象审计已全部通过"
                    if deterministic_passed
                    else "需要重新生成普通 Agent 与三成员 Room 的确定性对象审计"
                ),
            },
            {
                "status": "requires-live-evidence",
                "issue": "确定性对象审计不能证明外部 Provider 真实 wire 行为与 KV cache 命中",
                "result": "Prompt 冻结后仍需用真实 Provider 各跑一次 Agent 与三成员 Room 验收",
            },
        ],
    }


def _markdown_records(records: Iterable[Mapping[str, object]]) -> str:
    lines = ["# Prompt 原文总账", ""]
    current = ""
    for record in records:
        category = str(record["category"])
        if category != current:
            current = category
            lines.extend((f"## {category}", ""))
        lines.extend(
            (
                f"### `{record['prompt_id']}`",
                "",
                f"- 来源: `{record['source_path']}::{record['producer']}`",
                f"- 注入: {record['injection_phase']}",
                f"- 条件: {record['condition']}",
                f"- 状态: `{record['status']}`",
                f"- 模型可见: `{str(record['model_visible']).lower()}`",
                f"- 大小: {record['chars']} chars / {record['utf8Bytes']} bytes / "
                f"约 {record['estimatedTokens']} tokens",
                f"- SHA-256: `{record['sha256']}`",
            )
        )
        if record.get("notes"):
            lines.append(f"- 备注: {record['notes']}")
        lines.extend(("", "```text", str(record["content"]), "```", ""))
    return "\n".join(lines)


def _markdown_skills(skills: Mapping[str, object]) -> str:
    lines = ["# Skill 总账", ""]
    for item in skills["skills"]:  # type: ignore[index]
        lines.extend(
            (
                f"## `{item['name']}`",
                "",
                f"- 来源: `{item['path']}`",
                f"- 大小: {item['chars']} chars / {item['utf8Bytes']} bytes",
                f"- SHA-256: `{item['sha256']}`",
                "",
                "```markdown",
                str(item["content"]),
                "```",
                "",
            )
        )
    lines.extend(
        (
            "## 路由卡与阶段策略",
            "",
            "```json",
            json.dumps(
                {
                    "routingCards": skills["routingCards"],
                    "roomSkillPolicy": skills["roomSkillPolicy"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
        )
    )
    return "\n".join(lines)


def _markdown_references(value: Mapping[str, object]) -> str:
    lines = ["# Cafe / VCP 对照", ""]
    for item in value["references"]:  # type: ignore[index]
        lines.extend(
            (
                f"## {item['project']}: `{item['path']}`",
                "",
                f"- 本地源码存在: `{str(item['exists']).lower()}`",
                f"- 原提示词摘录: `{item['excerpt']}`",
                f"- 机制: {item['mechanism']}",
                f"- 本项目决定: {item['decision']}",
                "",
            )
        )
    summary = value["summary"]  # type: ignore[index]
    lines.extend(("## 采用", "", *[f"- {item}" for item in summary["adopt"]], ""))
    lines.extend(("## 不采用", "", *[f"- {item}" for item in summary["reject"]], ""))
    return "\n".join(lines)


def _markdown_review(
    audit: Mapping[str, object],
    *,
    output: Path,
) -> str:
    records = audit["promptRecords"]
    assert isinstance(records, list)
    categories: dict[str, dict[str, int]] = {}
    for record in records:
        category = str(record["category"])
        bucket = categories.setdefault(
            category,
            {"count": 0, "utf8Bytes": 0, "modelVisible": 0},
        )
        bucket["count"] += 1
        bucket["utf8Bytes"] += int(record["utf8Bytes"])
        bucket["modelVisible"] += int(bool(record["model_visible"]))

    lines = [
        "# Prompt 最终复核导览",
        "",
        "这份文件是给人逐段检查的入口；原文、Tool schema 和 Skill 正文仍以各自总账为准。",
        "",
        "## 真实组合路径",
        "",
        "```text",
        "普通 Agent",
        "  Core safety + 主动记忆 + 受管工作合同",
        "  -> Persona (+ 已固定 Role Book，未固定时 0 字节)",
        "  -> Session mode / Agent template",
        "  -> Skill/Tool 能力家族与当前阶段精确卡片",
        "  -> Workflow + Session memory + messages + active Tool schemas",
        "",
        "Room participant",
        "  同一套 Agent core + Persona + Room work lens",
        "  -> 当前 Task/Dispatch + 原始需求只读边界",
        "  -> Room sealed journal + 本轮增量 + 一次性压缩恢复包",
        "  -> messages + active Tool schemas",
        "```",
        "",
        "## 总账规模",
        "",
        "| 类别 | 段数 | 模型可见 | UTF-8 bytes |",
        "| --- | ---: | ---: | ---: |",
    ]
    for category, item in sorted(categories.items()):
        lines.append(
            f"| `{category}` | {item['count']} | {item['modelVisible']} | {item['utf8Bytes']} |"
        )

    lines.extend(
        (
            "",
            "## 逐层结论",
            "",
            "| 层 | 当前决定 | 复核重点 |",
            "| --- | --- | --- |",
            "| Core safety | 保留，唯一安全规则 owner | 权限、取消、凭证和迟到写入边界 |",
            "| 主动记忆 | 保留候选式写入 | `memory_capture` 是唯一公开捕获入口；模型输出不能自证用户事实 |",
            "| 受管工作 | 只在显式 Goal/Task/Dispatch 下激活 | 未完成要继续，有界无进展后交接、换模型或问用户 |",
            "| Persona / Role Book | 保留个性，画像必须固定版本 | 未固定时不注入任何状态垃圾文本 |",
            "| Skill / Tool | 短索引常驻，正文/schema 渐进披露 | 已激活与待披露互斥；同一步可加载 1-4 个 Tool |",
            "| Room 生命周期 | Kernel 裁决，模型提供结构化回执 | 子任务只执行当前 Dispatch，不把 Root 全部步骤据为己有 |",
            "| 压缩恢复 | 每次压缩只补 1 份恢复包 | 原始需求、当前任务、验收、阻塞、交接和精确 Skill/Tool 回执各一次 |",
            "| 后台记忆治理 | 与聊天 Prompt 分离 | 负责候选整理、去重、审阅和持久化，不冒充对话身份 |",
            "| 输入法 / 语音预测 | 仅辅助面 | 可以提供输入证据，不再定义 Agent 产品身份 |",
            "",
            "## 确定性 Provider 对象证据",
            "",
            "这些数据来自真实 Pi Agent Loop/Tool Loop 的归一化请求对象，不是只看配置；",
            "确定性 Provider 没有外网请求，因此不能冒充真实 KV cache 证据。",
            "",
            "| 场景 | Provider 调用 | Tool 执行 | 压缩 | 检查 | 入口 |",
            "| --- | ---: | ---: | ---: | --- | --- |",
        )
    )
    evidence = audit["deterministicEvidence"]
    assert isinstance(evidence, list)
    for item in evidence:
        status = (
            "PASS"
            if item.get("available") is True and item.get("allChecksPassed") is True
            else "MISSING/FAIL"
        )
        review_path = Path(str(audit["deterministicEvidenceRoot"])) / str(
            item["reviewPath"]
        )
        try:
            review_link = os.path.relpath(review_path, start=output)
        except ValueError:
            review_link = str(review_path)
        lines.append(
            f"| {item['label']} | {item.get('providerCallCount', '-')} | "
            f"{item.get('toolExecutionCount', '-')} | {item.get('compactionCount', '-')} | "
            f"`{status}` | [{item['reviewPath']}](<{review_link}>) |"
        )

    lines.extend(
        (
            "",
            "## 仍需真实 Provider 证明",
            "",
            "- 外部 Provider 收到的 wire payload 与归一化对象一致。",
            "- 同一 context epoch 的稳定前缀真实产生 cache read；Tool 只追加、不重排。",
            "- 真实模型能按当前 Task 的验收别名提交，不被 Root 原始需求带偏。",
            "",
            "## 建议检查顺序",
            "",
            "1. 先打开 [`index.html`](index.html)，按 Prompt / Skill / Tool / Provider 上下文 / 跨项目对比逐段检查。",
            "2. 在 Provider 上下文中分别选择普通 Agent 与三成员 Room，逐调用查看完整对象、`systemPrompt`、`messages`、`tools`、模型回复和 Tool 回执。",
            "3. 在跨项目对比中并排检查本项目最终原文、Cafe 最终源码/运行时模板与 VCP 最终源码/运行时模板。",
            "4. `prompts.md`、`skills.md`、`tools.json` 与 `manifest.json` 继续作为可 diff、可脚本校验的原始总账。",
            "",
            "## 命名边界",
            "",
            "少数内部 ID 仍保留 `rag-ime` / `ime_*` 以兼容数据库、HTTP 和 Pi 协议；",
            "它们是传输标识，不是产品身份，也不会让普通 Agent/Room 自称输入法。",
            "",
        )
    )
    return "\n".join(lines)


def render_audit(audit: Mapping[str, object], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (output / "manifest.json").write_text(manifest, encoding="utf-8")
    records = audit["promptRecords"]
    assert isinstance(records, list)
    (output / "prompts.md").write_text(
        _markdown_records(records),
        encoding="utf-8",
    )
    skills = audit["skills"]
    assert isinstance(skills, Mapping)
    (output / "skills.md").write_text(
        _markdown_skills(skills),
        encoding="utf-8",
    )
    tools = audit["tools"]
    (output / "tools.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    references = audit["references"]
    assert isinstance(references, Mapping)
    (output / "reference-comparison.md").write_text(
        _markdown_references(references),
        encoding="utf-8",
    )
    (output / "review.md").write_text(
        _markdown_review(audit, output=output),
        encoding="utf-8",
    )
    findings = audit["findings"]
    symbols = audit["promptSymbolInventory"]
    readme = [
        "# Agent Prompt System Audit",
        "",
        "这是一份源码生成的 Prompt 总账。它区分固定提示词、动态上下文、",
        "后台记忆治理、Skill/Tool 披露和输入法/语音辅助面；不把源码检查冒充真实 Provider 验收。",
        "人工复核优先打开 `index.html`；Markdown/JSON 保留给 diff、归档与自动校验。",
        "",
        "## 组合顺序",
        "",
        "```text",
        "普通 Agent",
        "  Core Rails -> Persona (+ pinned Role Book) -> Session mode/template",
        "  -> Skill/Tool short catalog -> Workflow/Lifecycle/Memory context -> messages",
        "",
        "Room participant",
        "  PromptPlan layers 1..5 (stable)",
        "  -> sealed Room projection -> pending Room delta",
        "  -> workflow/recovery context -> messages -> active Tool schemas",
        "```",
        "",
        "## 文件",
        "",
        "- `prompts.md`: 每段实际 Prompt 原文、来源、条件、大小和哈希",
        "- `skills.md`: 当前本项目 Skill 正文、路由卡和 Room 阶段策略",
        "- `tools.json`: Product/Room Tool 路由字段、schema 与 runtime projection",
        "- `reference-comparison.md`: Cafe/VCP 采用与拒绝项",
        "- `review.md`: 按最终组装路径逐层检查的人工复核导览",
        "- `manifest.json`: 机器可读总账",
        "- `index.html`: 可搜索、筛选、折叠的 Prompt 与 Provider 上下文复核台",
        "",
        "## 当前结论",
        "",
        *[
            f"- `{item['status']}` {item['issue']}: {item['result']}"
            for item in findings  # type: ignore[union-attr]
        ],
        "",
        "## 未分类 Prompt 生产者",
        "",
        "```json",
        json.dumps(symbols["unclassified"], ensure_ascii=False, indent=2),  # type: ignore[index]
        "```",
        "",
    ]
    (output / "README.md").write_text("\n".join(readme), encoding="utf-8")
    render_audit_html(
        audit,
        output=output / "index.html",
        audit_root=Path(str(audit["deterministicEvidenceRoot"])),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/agent/audits/agent-prompt-system-current",
    )
    parser.add_argument("--pi-root", type=Path, default=DEFAULT_PI_ROOT)
    parser.add_argument("--cafe-root", type=Path, default=DEFAULT_CAFE_ROOT)
    parser.add_argument("--vcp-root", type=Path, default=DEFAULT_VCP_ROOT)
    args = parser.parse_args()
    audit = build_audit(
        pi_root=args.pi_root,
        cafe_root=args.cafe_root,
        vcp_root=args.vcp_root,
    )
    unclassified = audit["promptSymbolInventory"]["unclassified"]  # type: ignore[index]
    if unclassified:
        raise SystemExit(
            "unclassified prompt-producing symbols: "
            + ", ".join(str(item) for item in unclassified)
        )
    render_audit(audit, args.output)
    print(
        json.dumps(
            {
                "schemaVersion": audit["schemaVersion"],
                "output": str(args.output),
                "promptCount": len(audit["promptRecords"]),  # type: ignore[arg-type]
                "skillCount": len(audit["skills"]["skills"]),  # type: ignore[index]
                "productToolCount": len(audit["tools"]["productTools"]),  # type: ignore[index]
                "roomToolCount": len(audit["tools"]["roomTools"]),  # type: ignore[index]
                "unclassifiedPromptSymbols": unclassified,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
