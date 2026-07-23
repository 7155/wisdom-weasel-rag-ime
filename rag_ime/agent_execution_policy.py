from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

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

_WORKSPACE_EFFECTS = frozenset(
    {
        ("workspace_patch", "apply"),
        ("workspace_shell", "run"),
    }
)

# Full trust removes routine approval interruptions, not the last human gate for
# process restarts, OS-level actions, or a whole-product configuration restore.
_ALWAYS_MANUAL_EFFECTS = frozenset(
    {
        ("ime_runtime", "restart_sidecar"),
        ("ime_runtime", "restart_predictor"),
        ("ime_runtime", "redeploy_rime"),
        ("ime_configuration", "restore_apply"),
        ("desktop_semantic", "act"),
    }
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


def approval_strategy(
    session: Mapping[str, object],
    *,
    tool: str,
    operation: str,
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
    if effect in _ALWAYS_MANUAL_EFFECTS:
        return APPROVAL_ASK
    if mode == WORKSPACE_MANAGED_EXECUTION_MODE:
        return (
            APPROVAL_AUTO
            if effect in _WORKSPACE_EFFECTS and workspace_scope_is_granted(session)
            else APPROVAL_ASK
        )
    if mode == FULL_TRUST_EXECUTION_MODE:
        if effect in _WORKSPACE_EFFECTS and not workspace_scope_is_granted(session):
            return APPROVAL_ASK
        return APPROVAL_AUTO
    return APPROVAL_ASK


def execution_mode_label(mode: object) -> str:
    return {
        READ_ONLY_EXECUTION_MODE: "只读",
        PER_ACTION_EXECUTION_MODE: "每次确认",
        WORKSPACE_MANAGED_EXECUTION_MODE: "工作区托管",
        FULL_TRUST_EXECUTION_MODE: "完全信任",
    }[normalize_execution_mode(mode)]


def execution_policy_prompt(session: Mapping[str, object]) -> str:
    mode = normalize_execution_mode(
        session.get("executionMode"),
        tool_profile_version=session.get("toolProfileVersion"),
    )
    guidance = {
        READ_ONLY_EXECUTION_MODE: (
            "只读操作自动执行；所有外部写入和 Shell 均被运行时拒绝。"
        ),
        PER_ACTION_EXECUTION_MODE: (
            "只读操作自动执行；每项外部写入和 Shell 都必须等待原生批准。"
        ),
        WORKSPACE_MANAGED_EXECUTION_MODE: (
            "已批准工作区范围内的文件写入和受控 Shell 自动执行；"
            "越过范围时必须请求扩展授权。"
        ),
        FULL_TRUST_EXECUTION_MODE: (
            "符合策略的操作自动执行；运行时重启、系统级动作和整库恢复仍保留人工门禁。"
        ),
    }[mode]
    return (
        f"执行权限：{execution_mode_label(mode)}。{guidance}"
        "任何模式都不得越过工作区、取消栅栏、审计、哈希复验和危险命令禁区。"
    )
