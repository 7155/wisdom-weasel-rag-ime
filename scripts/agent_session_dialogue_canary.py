#!/usr/bin/env python3
"""Run one real ordinary Agent Session through tools, approvals and compaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from room_context_epoch_canary import (
    JsonRequester,
    _provider_session_memory_blocks,
    _session_memory_blocks,
    encoded,
    progressive_discovery_check,
    provider_prefix_evidence,
    provider_prompt_governance_evidence,
    request_json,
)
from room_project_task_canary import (
    MISSING_READ_PATH,
    TEST_COMMAND,
    _approved_project_source,
    _independent_project_verification,
)


SCHEMA_VERSION = "wisdom-weasel.agent-session-dialogue-canary.v1"
TASK_MARKER = "AGENT-SESSION-RESILIENCE"
FINAL_MARKER = "AGENT-SESSION-CANARY-OK"
RECOVERY_MARKER = "AGENT-SESSION-RECOVERY-OK"
READ_BOUNDARY_PATH = "read-boundary.txt"
READ_BOUNDARY_SOURCE = "".join(
    f'第{index:04d}行 "quoted" \\\\ path 澄数据\n'
    for index in range(4_200)
)
EXPECTED_SKILL = "implementation-execution"
EXPECTED_TOOLS = {
    "ls",
    "grep",
    "read",
    "edit",
    "bash",
    "todo",
}
EXPECTED_TODO_TOOL = "todo"
FORBIDDEN_ROOM_MARKERS = (
    '<rag-ime-context type="room_context">',
    "<room-prompt-plan",
    "wisdom-weasel.room-binding.v2",
    "wisdom-weasel.room-dispatch-envelope.v2",
)
FORBIDDEN_MEMORY_METADATA = (
    "相关度",
    "relevance",
    "score=",
    "distance=",
    "embedding",
    "source_event_id",
    "memory_atom_id",
)


class AgentProjectPolicyRejection(RuntimeError):
    """The proposed action is well formed but outside this canary's approval."""


def agent_approval_identity(
    approval: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, str]:
    if approval.get("state") != "pending":
        raise RuntimeError("Agent project approval is no longer pending")
    if str(approval.get("sessionId") or "") != session_id:
        raise RuntimeError("Agent project approval belongs to another Session")
    payload_sha256 = str(approval.get("payloadSha256") or "")
    if len(payload_sha256) != 64:
        raise RuntimeError("Agent project approval payload hash is invalid")
    preview = approval.get("preview")
    if not isinstance(preview, dict):
        raise RuntimeError("Agent project approval has no structured preview")
    action = preview.get("actionPayload")
    base_state = preview.get("baseState")
    if not isinstance(action, dict) or not isinstance(base_state, dict):
        raise RuntimeError("Agent project approval is not hash-bound to an action")
    return {
        "approvalId": str(approval.get("approvalId") or ""),
        "toolId": str(approval.get("toolId") or ""),
        "payloadSha256": payload_sha256,
    }


def validate_agent_project_approval(
    approval: dict[str, Any],
    *,
    session_id: str,
    workspace: Path,
) -> dict[str, Any]:
    identity = agent_approval_identity(approval, session_id=session_id)
    preview = approval.get("preview")
    assert isinstance(preview, dict)
    action = preview.get("actionPayload")
    base_state = preview.get("baseState")
    assert isinstance(action, dict) and isinstance(base_state, dict)
    tool_id = identity["toolId"]
    resolved_workspace = workspace.resolve(strict=True)
    if tool_id in {"workspace_patch", "workspace_edit"}:
        target = Path(str(action.get("path") or "")).resolve(strict=True)
        if target != resolved_workspace / "calculator.py":
            raise AgentProjectPolicyRejection(
                "Agent project attempted to edit an unexpected file"
            )
        current_source = target.read_text(encoding="utf-8")
        if tool_id == "workspace_patch":
            old_text = action.get("oldText")
            new_text = action.get("newText")
            candidate_source = (
                current_source.replace(old_text, new_text, 1)
                if isinstance(old_text, str)
                and isinstance(new_text, str)
                and current_source.count(old_text) == 1
                else ""
            )
            shape_valid = action.get("expectedOccurrences") == 1
        else:
            edits = action.get("edits")
            expected_revision = f"sha256:{hashlib.sha256(target.read_bytes()).hexdigest()}"
            if str(action.get("resourceRevision") or "") != expected_revision:
                raise AgentProjectPolicyRejection("Agent project edit snapshot is stale")
            candidate_source = current_source
            shape_valid = isinstance(edits, list) and 1 <= len(edits) <= 64
            if shape_valid:
                replacements: list[tuple[int, int, str]] = []
                for raw_edit in edits:
                    if not isinstance(raw_edit, dict):
                        shape_valid = False
                        break
                    old_text = raw_edit.get("oldText")
                    new_text = raw_edit.get("newText")
                    if (
                        not isinstance(old_text, str)
                        or not old_text
                        or not isinstance(new_text, str)
                        or current_source.count(old_text) != 1
                    ):
                        shape_valid = False
                        break
                    start = current_source.index(old_text)
                    replacements.append(
                        (start, start + len(old_text), new_text)
                    )
                ordered = sorted(replacements)
                if any(
                    current[0] < previous[1]
                    for previous, current in zip(
                        ordered, ordered[1:], strict=False
                    )
                ):
                    shape_valid = False
                if shape_valid:
                    for start, end, new_text in reversed(ordered):
                        candidate_source = (
                            f"{candidate_source[:start]}"
                            f"{new_text}{candidate_source[end:]}"
                        )
        if not shape_valid or not _approved_project_source(candidate_source):
            raise AgentProjectPolicyRejection(
                "Agent project edit is outside the approved implementation shape"
            )
    elif tool_id == "workspace_shell":
        cwd = Path(str(action.get("cwd") or "")).resolve(strict=True)
        timeout_seconds = action.get("timeoutSeconds")
        if (
            cwd != resolved_workspace
            or action.get("command") != TEST_COMMAND
            or action.get("allowNetwork") is not False
            or not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 120
        ):
            raise AgentProjectPolicyRejection(
                "Agent project attempted an unexpected command"
            )
    else:
        raise AgentProjectPolicyRejection(
            f"Agent project requested an unexpected approval: {tool_id}"
        )
    return identity


def approve_pending_agent_actions(
    base_url: str,
    *,
    requester: JsonRequester,
    session_id: str,
    workspace: Path,
    decided_ids: set[str],
) -> list[dict[str, Any]]:
    listed = requester(
        base_url,
        "GET",
        f"/api/agent/approvals?sessionId={encoded(session_id)}&state=pending&limit=20",
        timeout=10,
    )
    decisions: list[dict[str, Any]] = []
    for raw in listed.get("items") or []:
        if not isinstance(raw, dict):
            continue
        approval_id = str(raw.get("approvalId") or "")
        if not approval_id or approval_id in decided_ids:
            continue
        identity = agent_approval_identity(raw, session_id=session_id)
        try:
            expected = validate_agent_project_approval(
                raw,
                session_id=session_id,
                workspace=workspace,
            )
        except AgentProjectPolicyRejection as error:
            rejection_started = time.monotonic()
            while True:
                rejected = requester(
                    base_url,
                    "POST",
                    f"/api/agent/approvals/{encoded(approval_id)}/decision",
                    {
                        "decision": "reject",
                        "payloadSha256": identity["payloadSha256"],
                    },
                    timeout=30,
                )
                final = rejected.get("approval")
                if (
                    isinstance(final, dict)
                    and final.get("state") == "rejected"
                    and rejected.get("runtimeNotified") is True
                ):
                    break
                if time.monotonic() - rejection_started >= 2.0:
                    raise RuntimeError(
                        "Pi did not receive rejected Agent approval"
                    )
                time.sleep(0.02)
            decided_ids.add(approval_id)
            decisions.append(
                {
                    **identity,
                    "decision": "reject",
                    "state": "rejected",
                    "runtimeNotified": True,
                    "mutationApplied": False,
                    "exitCode": None,
                    "timedOut": False,
                    "rejectionReason": str(error),
                    "runtimeRegistrationWaitMs": max(
                        0,
                        int((time.monotonic() - rejection_started) * 1_000),
                    ),
                }
            )
            continue
        registration_started = time.monotonic()
        while True:
            try:
                decided = requester(
                    base_url,
                    "POST",
                    f"/api/agent/approvals/{encoded(approval_id)}/decision",
                    {
                        "decision": "approve",
                        "payloadSha256": expected["payloadSha256"],
                    },
                    timeout=30,
                )
                break
            except RuntimeError as error:
                if (
                    "approval is no longer active in Pi" not in str(error)
                    or time.monotonic() - registration_started >= 2.0
                ):
                    raise
                time.sleep(0.02)
        final = decided.get("approval")
        allowed_states = (
            {"failed", "applied"}
            if expected["toolId"] == "workspace_shell"
            else {"applied"}
        )
        if not isinstance(final, dict) or final.get("state") not in allowed_states:
            raise RuntimeError(f"Agent project approval did not finish: {approval_id}")
        if decided.get("runtimeNotified") is not True:
            raise RuntimeError(f"Pi did not receive Agent approval result: {approval_id}")
        if str(decided.get("runtimeWarning") or ""):
            raise RuntimeError(str(decided["runtimeWarning"]))
        receipt = final.get("receipt") if isinstance(final.get("receipt"), dict) else {}
        decided_ids.add(approval_id)
        decisions.append(
            {
                **expected,
                "decision": "approve",
                "state": str(final.get("state") or ""),
                "runtimeNotified": True,
                "mutationApplied": receipt.get("mutationApplied") is True,
                "exitCode": receipt.get("exitCode"),
                "timedOut": receipt.get("timedOut") is True,
                "runtimeRegistrationWaitMs": max(
                    0,
                    int((time.monotonic() - registration_started) * 1_000),
                ),
            }
        )
    return decisions


def _assistant_texts(snapshot: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        blocks = item.get("blocks")
        if isinstance(blocks, list):
            parts = [
                str(block.get("data", {}).get("text") or "")
                for block in blocks
                if isinstance(block, dict)
                and isinstance(block.get("data"), dict)
                and block.get("type") == "text"
            ]
            if any(parts):
                texts.append("\n".join(parts))
                continue
        content = item.get("content")
        if isinstance(content, list):
            texts.append(
                "\n".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            )
    return [text for text in texts if text]


def _assistant_message_receipts(snapshot: dict[str, Any]) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for item in snapshot.get("items") or []:
        if not isinstance(item, dict) or item.get("role") != "assistant":
            continue
        blocks = [
            dict(block)
            for block in item.get("blocks") or []
            if isinstance(block, dict)
        ]
        receipts.append(
            {
                "messageId": str(item.get("messageId") or item.get("id") or ""),
                "turnId": str(item.get("turnId") or ""),
                "blockTypes": [str(block.get("type") or "") for block in blocks],
                "contentSha256": hashlib.sha256(
                    json.dumps(
                        blocks,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )
    return receipts


def _assistant_failures(snapshot: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for item in snapshot.get("items") or []:
        if (
            not isinstance(item, dict)
            or item.get("role") != "assistant"
            or item.get("status") != "failed"
        ):
            continue
        messages = [
            str(block.get("data", {}).get("message") or "").strip()
            for block in item.get("blocks") or []
            if isinstance(block, dict)
            and block.get("type") == "error"
            and isinstance(block.get("data"), dict)
        ]
        failures.append(next((value for value in messages if value), "模型请求失败，请重试"))
    return failures


def wait_for_agent_turn(
    base_url: str,
    *,
    requester: JsonRequester,
    session_id: str,
    workspace: Path,
    timeout: float,
    expected_marker: str,
    approve_actions: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + timeout
    decisions: list[dict[str, Any]] = []
    decided_ids: set[str] = set()
    minimum_assistant_count = 1
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if approve_actions:
            decisions.extend(
                approve_pending_agent_actions(
                    base_url,
                    requester=requester,
                    session_id=session_id,
                    workspace=workspace,
                    decided_ids=decided_ids,
                )
            )
        snapshot = requester(
            base_url,
            "GET",
            f"/api/agent/sessions/{encoded(session_id)}/messages",
            timeout=15,
        )
        texts = _assistant_texts(snapshot)
        failures = _assistant_failures(snapshot)
        last = {
            "status": str(snapshot.get("status") or ""),
            "assistantTexts": texts,
            "assistantMessages": _assistant_message_receipts(snapshot),
            "assistantFailures": failures,
            "messageCount": len(snapshot.get("items") or []),
            "liveEventCount": len(snapshot.get("liveEvents") or []),
            "messageQueue": snapshot.get("messageQueue") or {},
        }
        if (
            last["status"] == "idle"
            and len(texts) >= minimum_assistant_count
            and texts
            and expected_marker in texts[-1]
        ):
            return last, decisions
        if last["status"] == "idle" and failures:
            raise RuntimeError(
                "Agent Session failed before producing the expected result: "
                + failures[-1]
            )
        time.sleep(0.1)
    raise TimeoutError(f"Agent Session did not settle: {last}")


def _debug_context(
    base_url: str,
    session_id: str,
    *,
    requester: JsonRequester,
    timeout: float,
    turn_id: str = "",
) -> dict[str, Any]:
    path = f"/api/agent/sessions/{encoded(session_id)}/debug-context"
    if turn_id:
        path = f"{path}?turnId={encoded(turn_id)}"
    debug = requester(
        base_url,
        "GET",
        path,
        timeout=timeout,
    )
    context = debug.get("context") if isinstance(debug.get("context"), dict) else {}
    receipts = context.get("providerRequestReceipts") or []
    cache_reads = [
        int((item.get("usage") or {}).get("cacheRead") or 0)
        for item in receipts
        if isinstance(item, dict)
    ]
    prompts = [
        str(provider_context.get("systemPrompt") or "")
        for provider_context in (
            call.get("providerContext") or {}
            for call in context.get("modelCalls") or []
            if isinstance(call, dict)
        )
        if isinstance(provider_context, dict)
    ]
    provider_contexts = [
        call.get("providerContext") or {}
        for call in context.get("modelCalls") or []
        if isinstance(call, dict) and isinstance(call.get("providerContext"), dict)
    ]
    memory_blocks = list(
        dict.fromkeys(
            [
                *_provider_session_memory_blocks(
                    context.get("providerRequests") or []
                ),
                *_session_memory_blocks(provider_contexts),
            ]
        )
    )
    governance = provider_prompt_governance_evidence(context)
    executions = [
        {
            "toolCallId": str(item.get("toolCallId") or ""),
            "toolName": str(item.get("toolName") or ""),
            "args": item.get("args") if isinstance(item.get("args"), dict) else {},
            "status": str(item.get("status") or ""),
            "isError": item.get("isError") is True,
            "result": item.get("result"),
            "resultSha256": hashlib.sha256(
                json.dumps(
                    item.get("result"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }
        for item in context.get("toolExecutions") or []
        if isinstance(item, dict)
    ]
    current_provider = (
        debug.get("currentProviderContext")
        if isinstance(debug.get("currentProviderContext"), dict)
        else {}
    )
    current_prompt = str(current_provider.get("systemPrompt") or "")
    return {
        "turnId": str(debug.get("turnId") or ""),
        "model": context.get("model") or {},
        "modelCallCount": len(context.get("modelCalls") or []),
        "cacheReads": cache_reads,
        "positiveCacheRead": any(value > 0 for value in cache_reads),
        "providerPrefix": provider_prefix_evidence(context),
        "promptGovernance": governance,
        "progressiveDiscovery": progressive_discovery_check([governance]),
        "systemPromptChecks": {
            "roleBookExactlyOnce": bool(prompts)
            and all(prompt.count("<agent-profile>") == 1 for prompt in prompts),
            "noUnpinnedRoleFallback": all(
                "revision_not_pinned" not in prompt for prompt in prompts
            ),
            "agentMdDefaultOff": all("<project_context>" not in prompt for prompt in prompts),
            "noRoomAuthority": all(
                not any(marker in prompt for marker in FORBIDDEN_ROOM_MARKERS)
                for prompt in prompts
            ),
            "currentNoRoomRecovery": not any(
                marker in current_prompt for marker in FORBIDDEN_ROOM_MARKERS
            ),
        },
        "memory": {
            "blocks": memory_blocks,
            "usefulProjectPreference": any(
                "代码任务" in block and "测试" in block and "交付" in block
                for block in memory_blocks
            ),
            "forbiddenMetadata": sorted(
                {
                    token
                    for block in memory_blocks
                    for token in FORBIDDEN_MEMORY_METADATA
                    if token in block
                }
            ),
        },
        "toolExecutions": executions,
        "loadedSkillReceipts": context.get("loadedSkillReceipts") or [],
        "activeTools": context.get("activeTools") or [],
        "currentProviderContext": current_provider,
        "transcript": debug.get("transcript") or {},
    }


def _aggregate_debug_contexts(
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Combine every runtime turn that belongs to one logical Agent task."""

    if not contexts:
        raise ValueError("at least one debug context is required")
    last = contexts[-1]
    governance = [item["promptGovernance"] for item in contexts]
    governance_keys = (
        "catalogBlocksExactlyOnceEveryCall",
        "routingCardFieldContractEveryCall",
        "routingCardContentCompleteEveryCall",
    )
    prompt_governance = dict(last["promptGovernance"])
    for key in governance_keys:
        prompt_governance[key] = all(
            item.get(key) is True for item in governance
        )
    prompt_governance["turns"] = [
        {
            "turnId": item["turnId"],
            "evidence": item["promptGovernance"],
        }
        for item in contexts
    ]
    system_prompt_keys = set().union(
        *(item["systemPromptChecks"].keys() for item in contexts)
    )
    memory_blocks = list(
        dict.fromkeys(
            block
            for item in contexts
            for block in item["memory"]["blocks"]
        )
    )
    cache_reads = [
        value for item in contexts for value in item["cacheReads"]
    ]
    return {
        "turnId": str(last["turnId"]),
        "turnIds": [str(item["turnId"]) for item in contexts],
        "turns": contexts,
        "model": last["model"],
        "modelCallCount": sum(
            int(item["modelCallCount"]) for item in contexts
        ),
        "cacheReads": cache_reads,
        "positiveCacheRead": any(value > 0 for value in cache_reads),
        "providerPrefix": {
            "schemaVersion": (
                "wisdom-weasel.multi-turn-provider-prefix-evidence.v1"
            ),
            "passed": all(
                item["providerPrefix"]["passed"] is True
                for item in contexts
            ),
            "turns": [
                {
                    "turnId": item["turnId"],
                    "evidence": item["providerPrefix"],
                }
                for item in contexts
            ],
        },
        "promptGovernance": prompt_governance,
        "progressiveDiscovery": progressive_discovery_check(governance),
        "systemPromptChecks": {
            key: all(
                item["systemPromptChecks"].get(key) is True
                for item in contexts
            )
            for key in system_prompt_keys
        },
        "memory": {
            "blocks": memory_blocks,
            "usefulProjectPreference": any(
                item["memory"]["usefulProjectPreference"] is True
                for item in contexts
            ),
            "forbiddenMetadata": sorted(
                {
                    token
                    for item in contexts
                    for token in item["memory"]["forbiddenMetadata"]
                }
            ),
        },
        "toolExecutions": [
            execution
            for item in contexts
            for execution in item["toolExecutions"]
        ],
        "loadedSkillReceipts": [
            receipt
            for item in contexts
            for receipt in item["loadedSkillReceipts"]
        ],
        "activeTools": list(
            dict.fromkeys(
                str(tool)
                for item in contexts
                for tool in item["activeTools"]
            )
        ),
        "currentProviderContext": last["currentProviderContext"],
        "transcript": last["transcript"],
    }


def _native_read_result(
    execution: dict[str, Any],
) -> dict[str, Any] | None:
    result = execution.get("result")
    if not isinstance(result, dict):
        return None
    details = result.get("details")
    content_blocks = result.get("content")
    if not isinstance(details, dict) or not isinstance(content_blocks, list):
        return None
    content = details.get("content")
    required = ("startLine", "endLine", "truncated", "size")
    if not isinstance(content, str) or any(
        key not in details for key in required
    ):
        return None
    model_text = "".join(
        str(block.get("text") or "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    start_line = details.get("startLine")
    end_line = details.get("endLine")
    next_line = details.get("nextLineOffset")
    if (
        not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or not isinstance(end_line, int)
        or isinstance(end_line, bool)
        or (
            next_line is not None
            and (
                not isinstance(next_line, int)
                or isinstance(next_line, bool)
            )
        )
    ):
        return None
    continuation_note = (
        f"\n\n[Showing lines {start_line}-{end_line}. "
        f"Continue with offset={next_line}.]"
        if next_line is not None
        else ""
    )
    if model_text != f"{content}{continuation_note}":
        return None
    return {
        "contentBytes": len(content.encode("utf-8")),
        "contentLines": max(0, end_line - start_line + 1),
        "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "modelContent": content,
        "modelResultBytes": len(model_text.encode("utf-8")),
        "modelResultExact": True,
        "startLine": start_line,
        "endLine": end_line,
        "nextLineOffset": next_line,
        "byteSize": int(details["size"]),
        "truncated": details["truncated"] is True,
    }


def _tool_checks(evidence: dict[str, Any], workspace: Path) -> dict[str, bool]:
    executions = evidence["toolExecutions"]
    by_name = {
        name: [item for item in executions if item["toolName"] == name]
        for name in {
            *(item["toolName"] for item in executions),
            *EXPECTED_TOOLS,
            "skill_load",
            "tool_load",
            "tool_search",
        }
    }
    reads = by_name["read"]
    read_paths = [str(item["args"].get("path") or "") for item in reads]
    resolved_read_paths = [
        str(
            (Path(path) if Path(path).is_absolute() else workspace / path)
            .resolve(strict=False)
        )
        for path in read_paths
    ]
    expected_reads = {
        str((workspace / "calculator.py").resolve(strict=False)),
        str((workspace / "test_calculator.py").resolve(strict=False)),
    }
    boundary_path = str(
        (workspace / READ_BOUNDARY_PATH).resolve(strict=False)
    )
    boundary_reads = [
        item
        for item, path in zip(reads, resolved_read_paths, strict=True)
        if path == boundary_path
    ]
    boundary_receipts = [
        _native_read_result(item) for item in boundary_reads
    ]
    tool_load_names: list[str] = []
    for item in by_name["tool_load"]:
        name = str(item["args"].get("name") or "")
        if name:
            tool_load_names.append(name)
        names = item["args"].get("names")
        if isinstance(names, list):
            tool_load_names.extend(str(value) for value in names)
    skill_names = [
        str(item["args"].get("name") or "") for item in by_name["skill_load"]
    ]
    canonical_missing_reads = [
        item
        for item, path in zip(reads, resolved_read_paths, strict=True)
        if path == str((workspace / MISSING_READ_PATH).resolve(strict=False))
    ]
    valid_project_reads = [
        (item, path)
        for item, path in zip(reads, resolved_read_paths, strict=True)
        if path in expected_reads
    ]
    valid_lists = [
        item for item in by_name["ls"]
    ]
    valid_searches = [
        item for item in by_name["grep"]
    ]
    legacy_names = {
        "workspace_list",
        "workspace_search",
        "workspace_read",
        "workspace_patch",
        "workspace_edit",
        "workspace_write",
        "workspace_shell",
    }
    active_tools = {str(value) for value in evidence.get("activeTools") or []}
    return {
        "skillLoadedExactlyOnce": skill_names.count(EXPECTED_SKILL) == 1,
        "nativeToolsResidentFromFirstCall": EXPECTED_TOOLS <= active_tools,
        "todoUsesResidentCanonicalTool": (
            EXPECTED_TODO_TOOL in active_tools
            and EXPECTED_TODO_TOOL not in tool_load_names
        ),
        "todoLifecycleObserved": (
            [str(item["args"].get("op") or "") for item in by_name["todo"]]
            == [
                "init",
                "start",
                "done",
                "start",
                "done",
                "start",
                "checkpoint",
                "done",
            ]
        ),
        "nativeToolsNeverSearchedOrLoaded": (
            not by_name["tool_search"]
            and not (set(tool_load_names) & (EXPECTED_TOOLS | legacy_names))
        ),
        "missingReadFailedOnce": len(canonical_missing_reads) == 1
        and canonical_missing_reads[0]["isError"] is True,
        "projectFilesReadWithBoundedVerification": (
            2 <= len(valid_project_reads) <= 3
            and sum(
                path == str((workspace / "calculator.py").resolve(strict=False))
                for _, path in valid_project_reads
            )
            in {1, 2}
            and sum(
                path
                == str((workspace / "test_calculator.py").resolve(strict=False))
                for _, path in valid_project_reads
            )
            == 1
            and all(item["isError"] is False for item, _ in valid_project_reads)
        ),
        "boundaryReadUsesPiBudget": len(boundary_reads) >= 5
        and all(item["isError"] is False for item in boundary_reads)
        and all(
            item["args"].get("limit") == 1_000
            for item in boundary_reads
        )
        and all(receipt is not None for receipt in boundary_receipts)
        and all(
            receipt is not None
            and int(receipt["contentBytes"]) <= 50 * 1024
            and int(receipt["contentLines"]) <= 1_000
            and int(receipt["modelResultBytes"]) <= 50 * 1024
            and int(receipt["startLine"])
            == int(item["args"].get("offset") or 1)
            for receipt, item in zip(
                boundary_receipts,
                boundary_reads,
                strict=True,
            )
        ),
        "boundaryReadContinuationExact": bool(boundary_receipts)
        and (boundary_reads[0]["args"].get("offset") or 1) == 1
        and all(
            current is not None
            and next_item["args"].get("offset")
            == current["nextLineOffset"]
            for current, next_item in zip(
                boundary_receipts[:-1],
                boundary_reads[1:],
                strict=True,
            )
        )
        and boundary_receipts[-1] is not None
        and boundary_receipts[-1]["truncated"] is False
        and boundary_receipts[-1]["nextLineOffset"] is None,
        "boundaryReadModelPayloadExact": bool(boundary_receipts)
        and all(
            receipt is not None
            and receipt["modelResultExact"] is True
            for receipt in boundary_receipts
        )
        and "".join(
            str(receipt["modelContent"])
            for receipt in boundary_receipts
            if receipt is not None
        )
        == (workspace / READ_BOUNDARY_PATH).read_text(encoding="utf-8"),
        "listAndSearchAppliedOnceWithBoundedRepair": len(valid_lists) == 1
        and valid_lists[0]["args"].get("path") == "."
        and valid_lists[0]["isError"] is False
        and len(valid_searches) == 1
        and valid_searches[0]["args"].get("path") == "."
        and valid_searches[0]["args"].get("pattern") == "ROOM_PROJECT_TASK"
        and valid_searches[0]["isError"] is False,
        "editOnce": 1 <= len(by_name["edit"]) <= 2
        and sum(
            item["isError"] is False for item in by_name["edit"]
        )
        == 1,
        "bashTwice": len(by_name["bash"]) == 2,
        "noRoomOrDelegationCalls": not any(
            item["toolName"].startswith("room_")
            or item["toolName"] == "agents"
            for item in executions
        ),
    }


def _compaction_record_count(session_dir: Path, transcript_sha256: str) -> int:
    for path in sorted(session_dir.glob("*.jsonl")):
        if hashlib.sha256(path.read_bytes()).hexdigest() != transcript_sha256:
            continue
        return sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            if isinstance((item := _json_object(line)), dict)
            and item.get("type") == "compaction"
        )
    return 0


def _json_object(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def agent_session_task_message(workspace: Path) -> str:
    """Build the real coding turn without naming hidden gateway targets."""

    return (
        f"{TASK_MARKER}：这是普通单 Agent Session，不是 Room，也不要委派或 @ 任何人。"
        f"先用 skill_load 精确加载 {EXPECTED_SKILL}。"
        "read、ls、grep、edit、bash 已作为本轮常驻原生工具提供，直接调用；"
        "不得把它们交给 tool_search 或 tool_load。"
        f"第一步只用 read 读取不存在的 {workspace / MISSING_READ_PATH} 一次；"
        "确认失败后不得同参数重试。随后用 ls(path='.') 查看目录、"
        "grep(path='.', pattern='ROOM_PROJECT_TASK') 搜索标记，再以相对路径"
        "各读取一次 calculator.py 与 test_calculator.py。"
        "随后用 read(path='read-boundary.txt', offset=1, limit=1000) 分段读取；"
        "每次严格使用上一次结果提示的 offset 续读，直到不再返回续读提示，"
        "不得重复同一 offset，也不得用 bash 绕过读取上限。"
        f"任何写入或 bash 前，直接使用本轮常驻的 {EXPECTED_TODO_TOOL} 工具，"
        "先 init 建立覆盖基线测试、精确修改和回归测试的分阶段 Todo，再 start 基线测试任务；"
        "Todo 只跟踪当前执行进度，不构成权限；显式用户请求与原生动作审批仍是执行依据。"
        f"随后用 bash(command={TEST_COMMAND!r}, timeout=120) 运行基线测试；"
        "等待原生批准，确认修改前测试非零退出且不要把失败说成成功。"
        "再用 edit 只修改 calculator.py：在一个 edits 数组中做精确替换，"
        "实现 normalize_scores；空列表返回 []，非空时只计算一次 "
        "minimum = min(values)，再返回每个 value - minimum；等待原生批准。"
        f"随后复用 bash 再运行同一命令 {TEST_COMMAND!r} 并等待批准，必须退出码 0。"
        "每一步取得回执后都要用 todo done 完成当前任务并 start 下一项；"
        "所有 Todo 项和验收均完成后，再输出最终回答。"
        f"最终回答以 {FINAL_MARKER} 开头，列出失败、修复、通过测试和剩余风险。"
        f"等待原生动作批准时不得输出 {FINAL_MARKER}，它只代表全部验收真的完成。"
        "不要调用任何 room_*、agents 或其他无关产品 Tool。"
    )


def run(
    args: argparse.Namespace,
    *,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    stamp = int(time.time() * 1_000)
    workspace = args.workspace.expanduser().resolve(strict=True)
    created = requester(
        args.base_url,
        "POST",
        "/api/agent/sessions",
        {
            "title": f"Agent Session dialogue canary {stamp}",
            "mode": "coordinator",
            "roleId": "companion-present-v1",
            "roleVersion": "1",
            "toolProfileVersion": "control-center-v1",
            "workspaceRoots": [str(workspace)],
            "modelProfile": f"{args.model_provider}/{args.model_id}",
            "_internalModelOverride": True,
        },
    )
    session = created["session"]
    session_id = str(session["id"])
    control = requester(
        args.base_url,
        "POST",
        "/api/agent/sessions",
        {
            "title": f"Agent Session isolation control {stamp}",
            "mode": "assistant",
            "roleId": "companion-future-v1",
            "roleVersion": "1",
            "toolProfileVersion": "subagent-readonly-v1",
        },
    )["session"]
    control_session_id = str(control["id"])
    requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/model",
        {"provider": args.model_provider, "modelId": args.model_id},
    )
    requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/thinking",
        {"level": args.thinking_level},
    )
    message = agent_session_task_message(workspace)
    prompt_payload = {
        "message": message,
        "clientMessageId": f"agent-session-canary-{stamp}",
        "delivery": "prompt",
    }
    accepted = requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/prompt",
        prompt_payload,
        timeout=30,
    )
    replay = requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/prompt",
        prompt_payload,
        timeout=30,
    )
    settled, approvals = wait_for_agent_turn(
        args.base_url,
        requester=requester,
        session_id=session_id,
        workspace=workspace,
        timeout=args.turn_timeout,
        expected_marker=FINAL_MARKER,
        approve_actions=True,
    )
    task_turn_ids = [str(accepted.get("turnId") or "")]
    before = _aggregate_debug_contexts(
        [
            _debug_context(
                args.base_url,
                session_id,
                requester=requester,
                timeout=args.turn_timeout,
                turn_id=turn_id,
            )
            for turn_id in task_turn_ids
        ]
    )
    control_snapshot = requester(
        args.base_url,
        "GET",
        f"/api/agent/sessions/{encoded(control_session_id)}/messages",
        timeout=15,
    )
    compacted = requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/compact",
        {
            "instructions": (
                f"保留原始任务标记 {TASK_MARKER}、失败与修复、测试验收、"
                "已加载 Skill/Tool 能力和当前完成状态；只形成一份有界摘要。"
            )
        },
        timeout=args.turn_timeout,
    )
    recovery_payload = {
        "message": (
            f"压缩恢复检查：不要调用工具。依据现有上下文确认原始任务 {TASK_MARKER} "
            f"已经完成，并只回答以 {RECOVERY_MARKER} 开头的一句话。"
        ),
        "clientMessageId": f"agent-session-recovery-{stamp}",
        "delivery": "prompt",
    }
    recovery_accepted = requester(
        args.base_url,
        "POST",
        f"/api/agent/sessions/{encoded(session_id)}/prompt",
        recovery_payload,
        timeout=30,
    )
    recovered, recovery_approvals = wait_for_agent_turn(
        args.base_url,
        requester=requester,
        session_id=session_id,
        workspace=workspace,
        timeout=args.turn_timeout,
        expected_marker=RECOVERY_MARKER,
        approve_actions=False,
    )
    after = _debug_context(
        args.base_url,
        session_id,
        requester=requester,
        timeout=args.turn_timeout,
        turn_id=str(recovery_accepted.get("turnId") or ""),
    )
    tool_checks = _tool_checks(before, workspace)
    workflow_after = requester(
        args.base_url,
        "GET",
        f"/api/agent/sessions/{encoded(session_id)}/workflow",
        timeout=15,
    )
    todo_after = (
        workflow_after.get("todo")
        if isinstance(workflow_after.get("todo"), dict)
        else {}
    )
    todo_counts = (
        todo_after.get("counts")
        if isinstance(todo_after.get("counts"), dict)
        else {}
    )
    approved_actions = [
        item for item in approvals if item.get("decision") == "approve"
    ]
    rejected_actions = [
        item for item in approvals if item.get("decision") == "reject"
    ]
    approval_states = [item["state"] for item in approved_actions]
    approval_tools = [item["toolId"] for item in approved_actions]
    compact_result = compacted.get("result") or {}
    compact_summary = str(compact_result.get("summary") or "")
    compaction_count = _compaction_record_count(
        args.pi_session_dir,
        str(after["transcript"].get("sha256") or ""),
    )
    final_source = (workspace / "calculator.py").read_text(encoding="utf-8")
    independent = _independent_project_verification(workspace)
    current_after = after["currentProviderContext"]
    current_after_text = json.dumps(current_after, ensure_ascii=False, sort_keys=True)
    checks = {
        "idempotentPromptIngress": replay.get("idempotentReplay") is True
        and replay.get("turnId") == accepted.get("turnId"),
        "ordinarySessionSettled": settled["status"] == "idle"
        and sum(FINAL_MARKER in text for text in settled["assistantTexts"]) == 1,
        "toolFailureRecovered": all(tool_checks.values()),
        "nativeApprovalsExact": approval_tools
        == ["workspace_shell", "workspace_edit", "workspace_shell"]
        and approval_states == ["failed", "applied", "applied"]
        and all(item["runtimeNotified"] for item in approved_actions)
        and len(rejected_actions) <= 1
        and all(
            item["toolId"] == "workspace_edit"
            and item["state"] == "rejected"
            and item["runtimeNotified"] is True
            for item in rejected_actions
        )
        and int(todo_counts.get("total") or 0) >= 3
        and int(todo_counts.get("completed") or 0)
        == int(todo_counts.get("total") or 0)
        and int(todo_counts.get("inProgress") or 0) == 0,
        "projectImplementationApproved": _approved_project_source(final_source),
        "independentTestsPass": independent["exitCode"] == 0,
        "promptAndRoleBookValid": all(before["systemPromptChecks"].values())
        and before["promptGovernance"]["catalogBlocksExactlyOnceEveryCall"] is True
        and before["promptGovernance"]["routingCardFieldContractEveryCall"] is True
        and before["promptGovernance"]["routingCardContentCompleteEveryCall"] is True
        and before["progressiveDiscovery"] is True,
        "boundedUsefulRag": before["memory"]["usefulProjectPreference"] is True
        and not before["memory"]["forbiddenMetadata"],
        "providerPrefixStable": before["providerPrefix"]["passed"] is True,
        "crossSessionIsolation": not control_snapshot.get("items")
        and FINAL_MARKER not in json.dumps(control_snapshot, ensure_ascii=False),
        "compactionAppliedOnce": compact_result.get("contextRefreshApplied") is True
        and compaction_count == 1,
        "compactionRecoveryValid": recovered["status"] == "idle"
        and sum(RECOVERY_MARKER in text for text in recovered["assistantTexts"]) == 1
        and not recovery_approvals
        and TASK_MARKER in compact_summary
        and TASK_MARKER in current_after_text
        and "继续执行上述原始需求。" not in current_after_text
        and "## 当前 Todo" not in current_after_text
        and all(after["systemPromptChecks"].values())
        and set(EXPECTED_TOOLS) <= {
            str(value) for value in after["activeTools"]
        },
        "noRoomRuntimeSurface": all(before["systemPromptChecks"].values())
        and all(after["systemPromptChecks"].values())
        and not any(
            item["toolName"].startswith("room_")
            for item in before["toolExecutions"] + after["toolExecutions"]
        ),
        "recoveryTurnAccepted": recovery_accepted.get("accepted") is True,
    }
    if bool(getattr(args, "require_cache_evidence", True)):
        checks["realProviderKvCacheObserved"] = (
            before["positiveCacheRead"] is True
        )
    else:
        checks["deterministicCacheEvidenceNotClaimed"] = (
            before["positiveCacheRead"] is False
            and after["positiveCacheRead"] is False
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sessionId": session_id,
        "controlSessionId": control_session_id,
        "accepted": accepted,
        "idempotentReplay": replay,
        "settled": settled,
        "recovered": recovered,
        "approvals": approvals,
        "todo": todo_after,
        "toolChecks": tool_checks,
        "beforeCompaction": before,
        "compaction": {
            "response": compact_result,
            "transcriptRecordCount": compaction_count,
        },
        "afterCompaction": after,
        "project": {
            "sourceSha256": hashlib.sha256(final_source.encode("utf-8")).hexdigest(),
            "independentVerification": independent,
        },
        "checks": checks,
    }
