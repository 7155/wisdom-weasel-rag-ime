from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from .agent_tool_ids import (
    CONTROL_CENTER_TOOL_PROFILE,
    DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
    READONLY_TOOL_PROFILE,
)


READ_ONLY_EXECUTION_MODE = "read_only"
PER_ACTION_EXECUTION_MODE = "per_action"
WORKSPACE_MANAGED_EXECUTION_MODE = "workspace_managed"
FULL_TRUST_EXECUTION_MODE = "full_trust"

SUPPORTED_EXECUTION_MODES = frozenset(
    {
        READ_ONLY_EXECUTION_MODE,
        PER_ACTION_EXECUTION_MODE,
        WORKSPACE_MANAGED_EXECUTION_MODE,
        FULL_TRUST_EXECUTION_MODE,
    }
)

WORKSPACE_SCOPE_CONFIRMATION = "APPROVE_WORKSPACE_SCOPE"

APPROVAL_DENY = "deny"
APPROVAL_ASK = "ask"
APPROVAL_AUTO = "auto"
APPROVAL_MODEL = "model"

_WORKSPACE_EFFECTS = frozenset(
    {
        ("workspace_edit", "apply"),
        ("workspace_patch", "apply"),
        ("workspace_lsp", "rename"),
        ("workspace_lsp", "code_action_apply"),
        ("workspace_shell", "run"),
        ("workspace_job", "start"),
        ("workspace_job", "cancel"),
        ("workspace_write", "apply"),
        # These are the native Pi names projected by the coordinator adapter.
        # They remain hard-fenced if a stale or alternate adapter reaches the
        # policy helper before translating to a product Tool.
        ("edit", "apply"),
        ("write", "apply"),
        ("apply_patch", "apply"),
        ("bash", "run"),
    }
)

# Room read-only work may inspect an authorized workspace, but it must never
# mutate it, start or cancel a background job, run a command, or apply an LSP
# edit. Keep this predicate shared by manifest disclosure and both execution
# paths so a stale workspace-managed grant cannot widen the live policy.
READ_ONLY_BLOCKED_EFFECTS = _WORKSPACE_EFFECTS


def read_only_blocks_effect(tool: object, operation: object) -> bool:
    return (str(tool), str(operation)) in READ_ONLY_BLOCKED_EFFECTS


def read_only_policy_active(session: Mapping[str, object]) -> bool:
    return (
        str(session.get("executionMode") or "").strip().lower()
        == READ_ONLY_EXECUTION_MODE
        or str(session.get("toolProfileVersion") or "").strip()
        == READONLY_TOOL_PROFILE
    )

# Full automation is model-arbitrated, never policy auto-approval. Product
# runtime replacement and whole-product restore stay human-gated in other
# execution modes; Luna Max judges them only after explicit full automation is
# enabled. The model cannot create workspace scope or bypass hard fences.
_ALWAYS_MANUAL_EFFECTS = frozenset(
    {
        ("runtime", "restart_sidecar"),
        ("runtime", "restart_predictor"),
        ("runtime", "redeploy_rime"),
        ("configuration", "restore_apply"),
    }
)

# Full automation may skip the model only for a command whose concrete
# hash-bound preview proves that it remains an ordinary, in-scope command.
# The workspace harness remains the authoritative executor-side hard fence.
_SAFE_FULL_AUTO_EFFECT = ("workspace_shell", "run")
_SAFE_FULL_AUTO_TEXT_EFFECTS = frozenset(
    {
        ("workspace_edit", "apply"),
        ("workspace_patch", "apply"),
        ("workspace_write", "apply"),
    }
)
_DESTRUCTIVE_PREVIEW = re.compile(
    r"(?i)(?:\brm\s+[^\n]*(?:-[^\n]*r|--recursive)|"
    r"\bgit\s+(?:reset\s+--hard|clean\s+-[^\n]*f)|"
    r"\b(?:drop|truncate)\s+(?:table|database)\b|"
    r"\bdelete\s+from\b|\b(?:dd|mkfs|shred)\b)"
)
_SENSITIVE_PREVIEW = re.compile(
    r"(?i)(?:\.env(?:\.[^/\s]*)?|\.git-credentials|\.netrc|"
    r"auth\.json|credentials\.json|id_(?:rsa|ed25519)|"
    r"[^/\s]+\.(?:pem|key|p12|pfx|sqlite3?|db))"
)
_NETWORK_PREVIEW = re.compile(
    r"(?i)(?:\b(?:curl|wget|ssh|scp|sftp|rsync|ftp|telnet|ncat|nc)\b|"
    r"https?://)"
)


def normalize_execution_mode(
    value: object,
    *,
    tool_profile_version: object = "",
    default: str = PER_ACTION_EXECUTION_MODE,
) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        profile = str(tool_profile_version or "").strip()
        if profile == READONLY_TOOL_PROFILE:
            return READ_ONLY_EXECUTION_MODE
        if profile == DANGEROUS_AUTO_APPROVE_TOOL_PROFILE:
            return FULL_TRUST_EXECUTION_MODE
        normalized = default
    if normalized not in SUPPORTED_EXECUTION_MODES:
        raise ValueError("unsupported Agent execution mode")
    return normalized


def canonical_tool_profile(
    tool_profile_version: object,
    *,
    execution_mode: str,
) -> str:
    profile = str(tool_profile_version or CONTROL_CENTER_TOOL_PROFILE).strip()
    if execution_mode == READ_ONLY_EXECUTION_MODE:
        return READONLY_TOOL_PROFILE
    if profile in {
        READONLY_TOOL_PROFILE,
        DANGEROUS_AUTO_APPROVE_TOOL_PROFILE,
    }:
        return CONTROL_CENTER_TOOL_PROFILE
    return profile


def workspace_scope_sha256(workspace_roots: Sequence[object]) -> str:
    roots = sorted({str(value).strip() for value in workspace_roots if str(value).strip()})
    if not roots:
        return ""
    return hashlib.sha256(
        json.dumps(
            roots,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def workspace_scope_is_granted(session: Mapping[str, object]) -> bool:
    expected = workspace_scope_sha256(
        list(session.get("workspaceRoots") or [])
    )
    return bool(
        expected
        and expected
        == str(session.get("workspaceScopeSha256") or "")
        and int(session.get("workspaceScopeGrantedAtMs") or 0) > 0
    )
def _preview_mapping(
    preview: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object]:
    if not isinstance(preview, Mapping):
        return {}
    value = preview.get(key)
    return value if isinstance(value, Mapping) else {}


def _strict_preview_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}

def _path_is_within_workspace_scope(
    path_value: object,
    workspace_roots: Sequence[object],
) -> bool:
    candidate_text = str(path_value or "").strip()
    if not candidate_text:
        return False
    try:
        candidate = Path(candidate_text).expanduser().resolve(strict=False)
        roots = tuple(
            Path(str(root).strip()).expanduser().resolve(strict=False)
            for root in workspace_roots
            if str(root).strip()
        )
    except (OSError, RuntimeError, ValueError):
        return False
    return any(candidate == root or root in candidate.parents for root in roots)


def _safe_full_auto_command(
    session: Mapping[str, object],
    preview: Mapping[str, object] | None,
    *,
    risk_level: object,
) -> bool:
    """Return whether a prepared command can bypass redundant model review."""

    if str(risk_level or "").strip().upper() == "R3":
        return False
    action = _preview_mapping(preview, "actionPayload")
    base_state = _preview_mapping(preview, "baseState")
    command = " ".join(str(action.get("command") or "").split())
    if not command or not base_state:
        return False
    workspace_roots = list(session.get("workspaceRoots") or [])
    expected_scope = workspace_scope_sha256(workspace_roots)
    cwd = str(action.get("cwd") or "").strip()
    preview_scope = str(
        base_state.get("workspaceRootsSha256")
        or base_state.get("workspaceRootSha256")
        or ""
    ).strip().lower()
    if (
        not expected_scope
        or preview_scope != expected_scope
        or not _path_is_within_workspace_scope(cwd, workspace_roots)
        or _strict_preview_bool(action.get("allowNetwork"))
        or _DESTRUCTIVE_PREVIEW.search(command)
        or _SENSITIVE_PREVIEW.search(command)
        or _NETWORK_PREVIEW.search(command)
    ):
        return False
    return True


def safe_full_auto_command(
    session: Mapping[str, object],
    preview: Mapping[str, object] | None,
    *,
    risk_level: object = "",
) -> bool:
    """Public policy predicate shared by runtime approval owners."""

    return _safe_full_auto_command(
        session,
        preview,
        risk_level=risk_level,
    )


def _safe_full_auto_text_change(
    session: Mapping[str, object],
    preview: Mapping[str, object] | None,
    *,
    risk_level: object,
) -> bool:
    """Return whether a prepared text mutation stays inside the granted scope.

    The workspace harness has already resolved symlinks, rejected sensitive or
    non-text targets, bounded the payload, and produced a hash-bound preview.
    This policy check independently verifies the trust-boundary facts needed to
    skip a redundant model decision; apply-time revalidation remains owned by
    the harness.
    """

    if str(risk_level or "").strip().upper() == "R3":
        return False
    action = _preview_mapping(preview, "actionPayload")
    base_state = _preview_mapping(preview, "baseState")
    path = str(action.get("path") or "").strip()
    workspace_roots = list(session.get("workspaceRoots") or [])
    expected_scope = workspace_scope_sha256(workspace_roots)
    preview_scope = str(
        base_state.get("workspaceRootsSha256")
        or base_state.get("workspaceRootSha256")
        or ""
    ).strip().lower()
    return bool(
        path
        and expected_scope
        and preview_scope == expected_scope
        and _path_is_within_workspace_scope(path, workspace_roots)
        and not _SENSITIVE_PREVIEW.search(path)
    )





def approval_strategy(
    session: Mapping[str, object],
    *,
    tool: str,
    operation: str,
    preview: Mapping[str, object] | None = None,
    risk_level: object = "",
) -> str:
    mode = normalize_execution_mode(
        session.get("executionMode"),
        tool_profile_version=session.get("toolProfileVersion"),
    )
    effect = (str(tool), str(operation))
    if mode == READ_ONLY_EXECUTION_MODE:
        return APPROVAL_DENY
    if mode == PER_ACTION_EXECUTION_MODE:
        return APPROVAL_ASK
    if mode == FULL_TRUST_EXECUTION_MODE:
        if effect in _WORKSPACE_EFFECTS and not workspace_scope_is_granted(session):
            return APPROVAL_DENY
        if (
            effect == _SAFE_FULL_AUTO_EFFECT
            and safe_full_auto_command(
                session,
                preview,
                risk_level=risk_level,
            )
        ):
            return APPROVAL_AUTO
        if (
            effect in _SAFE_FULL_AUTO_TEXT_EFFECTS
            and _safe_full_auto_text_change(
                session,
                preview,
                risk_level=risk_level,
            )
        ):
            return APPROVAL_AUTO
        return APPROVAL_MODEL
    if effect in _ALWAYS_MANUAL_EFFECTS:
        return APPROVAL_ASK
    if mode == WORKSPACE_MANAGED_EXECUTION_MODE:
        return (
            APPROVAL_AUTO
            if effect in _WORKSPACE_EFFECTS and workspace_scope_is_granted(session)
            else APPROVAL_ASK
        )
    return APPROVAL_ASK


def execution_mode_label(mode: object) -> str:
    return {
        READ_ONLY_EXECUTION_MODE: "只读",
        PER_ACTION_EXECUTION_MODE: "每次确认",
        WORKSPACE_MANAGED_EXECUTION_MODE: "工作区托管",
        FULL_TRUST_EXECUTION_MODE: "全自动",
    }[normalize_execution_mode(mode)]


def execution_policy_prompt(session: Mapping[str, object]) -> str:
    mode = normalize_execution_mode(
        session.get("executionMode"),
        tool_profile_version=session.get("toolProfileVersion"),
    )
    scope_granted = workspace_scope_is_granted(session)
    guidance = {
        READ_ONLY_EXECUTION_MODE: (
            "本轮是只读模式。可以直接查看、检索和分析；\n"
            "文件写入、Shell 和其他外部改变不会执行。"
        ),
        PER_ACTION_EXECUTION_MODE: (
            "本轮是每次确认模式。查看、检索和分析可以直接进行；\n"
            "每次文件写入、Shell 或外部改变前等待原生批准。"
        ),
        WORKSPACE_MANAGED_EXECUTION_MODE: (
            (
                "本轮是工作区托管模式。已批准工作区内的文件修改和受控 Shell 可以直接完成；\n"
                "越出范围或触发危险系统动作时再请求确认。"
            )
            if scope_granted
            else (
                "本轮选择工作区托管，但工作区范围尚未确认。查看、检索和分析可以直接进行；\n"
                "第一次写入或 Shell 等待一次原生范围批准，之后范围内自动，越界再问。"
            )
        ),
        FULL_TRUST_EXECUTION_MODE: (
            (
                "本轮是全自动模式。无需审批的查看和检索可以直接进行；\n"
                "已授权工作区内的普通文本修改和不含破坏性、敏感或网络效果的受控命令，"
                "由确定性策略和哈希边界直接放行，不重复请求裁决。\n"
                "只有跨出工作区、接触敏感信息、产生网络或系统影响等仍需判断的高风险操作，"
                "才交给独立的 Luna Max。它只接收明确用户请求、当前任务、结构化操作预览和"
                "既有裁决，不接收本 Agent 的输出或推理。\n"
                "Luna 拒绝或判定失败时原操作不执行；读取回执后改用范围更小、只读或可逆方案，"
                "不要原样重试，也不要转为人工审批。"
            )
            if scope_granted
            else (
                "本轮选择全自动，但工作区边界尚未确认。查看、检索和分析可以直接进行；\n"
                "工作区变更会失败关闭；其他待审批操作仍由 Luna Max 根据用户请求、当前任务和"
                "结构化审批历史判定，不接收本 Agent 的输出或推理。"
            )
        ),
    }[mode]
    return (
        f'<execution-mode mode="{mode}">\n'
        f"{guidance}\n\n"
        "范围和哈希硬边界始终有效；取消、审计和迟到写入保护始终有效；删库、灾难性破坏和敏感数据外传由代码硬阻止。\n"
        "</execution-mode>"
    )
