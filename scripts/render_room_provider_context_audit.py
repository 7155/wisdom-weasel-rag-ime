#!/usr/bin/env python3
"""Render exact, credential-free Provider context evidence for a Room canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "wisdom-weasel.dialogue-provider-context-audit.v2"
FORBIDDEN_ROOM_METADATA = (
    "schemaVersion",
    "catalogRevision",
    "generation",
    "sha256",
)
SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(
        r"(?:authorization|x-api-key|api[_-]?key)"
        r"[\"']?\s*[:=]\s*[\"']?(?!\[credential omitted\])"
        r"[A-Za-z0-9._~+/=-]{12,}",
        re.IGNORECASE,
    ),
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"expected object at {path}:{line_number}")
        values.append(value)
    return values


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(value), encoding="utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_bytes(value: object) -> int:
    return len(_canonical_json(value).encode("utf-8"))


def _json_sha256(value: object) -> str:
    return _sha256_text(_canonical_json(value))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [
            text
            for item in value
            for text in _strings(item)
        ]
    if isinstance(value, dict):
        return [
            text
            for item in value.values()
            for text in _strings(item)
        ]
    return []


def _provider_object_summary(provider_context: object) -> dict[str, Any]:
    if not isinstance(provider_context, dict):
        return {
            "systemPrompt": {},
            "messages": [],
            "tools": [],
            "totalJsonBytes": 0,
        }
    prompt = str(provider_context.get("systemPrompt") or "")
    raw_messages = provider_context.get("messages")
    messages = (
        [item for item in raw_messages if isinstance(item, dict)]
        if isinstance(raw_messages, list)
        else []
    )
    raw_tools = provider_context.get("tools")
    tools = (
        [item for item in raw_tools if isinstance(item, dict)]
        if isinstance(raw_tools, list)
        else []
    )
    message_summaries = [
        {
            "index": index,
            "role": str(message.get("role") or ""),
            "contentChars": sum(
                len(text) for text in _strings(message.get("content"))
            ),
            "contentUtf8Bytes": sum(
                len(text.encode("utf-8"))
                for text in _strings(message.get("content"))
            ),
            "jsonBytes": _json_bytes(message),
            "sha256": _json_sha256(message),
        }
        for index, message in enumerate(messages)
    ]
    tool_summaries = [
        {
            "index": index,
            "name": str(tool.get("name") or ""),
            "descriptionUtf8Bytes": len(
                str(tool.get("description") or "").encode("utf-8")
            ),
            "schemaJsonBytes": _json_bytes(
                tool.get("parameters")
                if isinstance(tool.get("parameters"), dict)
                else {}
            ),
            "jsonBytes": _json_bytes(tool),
            "sha256": _json_sha256(tool),
        }
        for index, tool in enumerate(tools)
    ]
    return {
        "systemPrompt": {
            "chars": len(prompt),
            "utf8Bytes": len(prompt.encode("utf-8")),
            "sha256": _sha256_text(prompt),
        },
        "messages": message_summaries,
        "messagesJsonBytes": _json_bytes(messages),
        "messagesContentUtf8Bytes": sum(
            int(item["contentUtf8Bytes"]) for item in message_summaries
        ),
        "tools": tool_summaries,
        "toolsJsonBytes": _json_bytes(tools),
        "totalJsonBytes": _json_bytes(provider_context),
        "sha256": _json_sha256(provider_context),
    }


def _tool_execution_summary(execution: dict[str, Any]) -> dict[str, Any]:
    result = execution.get("result")
    result_record = result if isinstance(result, dict) else {}
    blocks = result_record.get("content")
    block_list = blocks if isinstance(blocks, list) else []
    model_text = "".join(
        str(block.get("text") or "")
        for block in block_list
        if isinstance(block, dict)
        and block.get("type") == "text"
    )
    details = (
        result_record.get("details")
        if isinstance(result_record.get("details"), dict)
        else {}
    )
    summary: dict[str, Any] = {
        "toolCallId": str(execution.get("toolCallId") or ""),
        "toolName": str(execution.get("toolName") or ""),
        "status": str(execution.get("status") or ""),
        "isError": execution.get("isError") is True,
        "args": (
            execution.get("args")
            if isinstance(execution.get("args"), dict)
            else {}
        ),
        "argsJsonBytes": _json_bytes(execution.get("args") or {}),
        "argsSha256": _json_sha256(execution.get("args") or {}),
        "resultJsonBytes": _json_bytes(result),
        "fullAuditResultJsonBytes": _json_bytes(result),
        "resultSha256": _json_sha256(result),
        "modelVisibleTextBytes": len(model_text.encode("utf-8")),
        "modelVisibleTextSha256": _sha256_text(model_text),
        "durationMs": max(
            0,
            int(execution.get("endedAtMs") or 0)
            - int(execution.get("startedAtMs") or 0),
        ),
    }
    if summary["toolName"] == "workspace_read" and isinstance(details, dict):
        try:
            parsed_model_receipt = json.loads(model_text)
        except json.JSONDecodeError:
            parsed_model_receipt = None
        model_receipt = (
            parsed_model_receipt
            if isinstance(parsed_model_receipt, dict)
            else {}
        )
        receipt_keys = (
            "offset",
            "offsetUnit",
            "byteSize",
            "requestedLimitBytes",
            "contentLimitBytes",
            "lineLimit",
            "modelResultLimitBytes",
            "contentChars",
            "contentBytes",
            "contentLines",
            "truncated",
            "truncatedBy",
            "modelResultBounded",
            "nextOffset",
        )
        summary["workspaceRead"] = {
            key: details.get(key)
            for key in receipt_keys
        }
        summary["workspaceReadModelReceipt"] = {
            key: model_receipt.get(key)
            for key in receipt_keys
        }
        summary["workspaceReadModelJsonValid"] = bool(model_receipt)
        summary["workspaceReadModelReceiptMatchesDetails"] = (
            bool(model_receipt)
            and all(
                model_receipt.get(key) == details.get(key)
                for key in receipt_keys
            )
            and model_receipt.get("content") == details.get("content")
        )
    return summary


def _safe_file_part(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "")).strip("-")
    return normalized[:80] or "unknown"


def _extract_context_blocks(prompt: str, context_type: str) -> list[str]:
    if context_type in {"workflow_state", "workflow_control"}:
        return re.findall(
            r"<workflow-state\b[^>]*>.*?</workflow-state>",
            prompt,
            re.DOTALL,
        )
    pattern = re.compile(
        rf'<rag-ime-context\s+type="{re.escape(context_type)}">.*?'
        r"</rag-ime-context>",
        re.DOTALL,
    )
    return pattern.findall(prompt)


def _recovery_packet(prompt: str) -> dict[str, Any] | None:
    pattern = re.compile(
        r'<rag-ime-context\s+type="room_context">\s*(.*?)\s*'
        r"</rag-ime-context>",
        re.DOTALL,
    )
    matches = pattern.findall(prompt)
    if len(matches) != 1:
        return None
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _valid_recovery_packet(packet: dict[str, Any] | None) -> bool:
    if packet is None:
        return False
    skill = packet.get("skillReceipt")
    tools = packet.get("toolReceipt")
    items = tools.get("items") if isinstance(tools, dict) else None
    return (
        isinstance(packet.get("originalRequirements"), list)
        and bool(packet["originalRequirements"])
        and isinstance(packet.get("currentTask"), dict)
        and bool(packet["currentTask"].get("objective"))
        and isinstance(packet.get("acceptance"), list)
        and bool(packet["acceptance"])
        and isinstance(packet.get("blockers"), list)
        and isinstance(packet.get("handoff"), dict)
        and isinstance(skill, dict)
        and bool(skill.get("restoredFromReceiptId"))
        and isinstance(items, list)
        and bool(items)
        and all(
            isinstance(item, dict)
            and bool(item.get("name"))
            and bool(item.get("receiptId"))
            for item in items
        )
    )


def _safe_provider_exchanges(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        safe.append({key: entry for key, entry in item.items() if key != "headers"})
    return safe


def _tool_names(provider_context: object) -> list[str]:
    if not isinstance(provider_context, dict):
        return []
    tools = provider_context.get("tools")
    if not isinstance(tools, list):
        return []
    return [
        str(tool["name"])
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    ]


def _provider_wire_payload(call: dict[str, Any]) -> dict[str, Any] | None:
    exchanges = call.get("providerExchanges")
    if not isinstance(exchanges, list):
        return None
    for exchange in reversed(exchanges):
        if not isinstance(exchange, dict):
            continue
        payload = exchange.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


def _wire_system_prompt(call: dict[str, Any]) -> str | None:
    payload = _provider_wire_payload(call)
    if not isinstance(payload, dict):
        return None
    for field in ("input", "messages"):
        items = payload.get(field)
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("role") not in {"developer", "system"}
            ):
                continue
            content = item.get("content")
            return content if isinstance(content, str) else None
    return None


def _wire_tool_names(call: dict[str, Any]) -> list[str] | None:
    """Collect Tool schemas from both Responses API disclosure locations."""

    payload = _provider_wire_payload(call)
    if payload is None:
        return None
    names: list[str] = []

    def append_tools(value: object) -> None:
        if not isinstance(value, list):
            return
        for tool in value:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            function = tool.get("function")
            if not isinstance(name, str) and isinstance(function, dict):
                name = function.get("name")
            if not isinstance(name, str):
                continue
            if name not in names:
                names.append(name)

    append_tools(payload.get("tools"))
    inputs = payload.get("input")
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, dict) and item.get("type") == "tool_search_output":
                append_tools(item.get("tools"))
    return names


def _usage(call: dict[str, Any]) -> dict[str, Any]:
    assistant = call.get("assistantMessage")
    if not isinstance(assistant, dict):
        return {}
    usage = assistant.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "".join(
        str(item.get("text") or "")
        for item in value
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _skill_load_calls(call: dict[str, Any]) -> list[dict[str, Any]]:
    assistant = call.get("assistantMessage")
    content = assistant.get("content") if isinstance(assistant, dict) else None
    if not isinstance(content, list):
        return []
    return [
        item
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "toolCall"
        and item.get("name") == "skill_load"
    ]


def _skill_load_context_epoch_evidence(
    calls: list[tuple[int, int, dict[str, Any]]],
    recovery_prompts: list[str],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Prove skill_load is append-only until compaction creates a new epoch."""

    ordered = sorted(calls, key=lambda item: _call_sort_key(item[2]))
    evidence: list[dict[str, Any]] = []
    for position, (turn_number, call_index, call) in enumerate(ordered):
        tool_calls = _skill_load_calls(call)
        if not tool_calls:
            continue
        next_item = ordered[position + 1] if position + 1 < len(ordered) else None
        for tool_call in tool_calls:
            tool_call_id = str(tool_call.get("id") or "")
            skill_name = str(
                (
                    tool_call.get("arguments")
                    if isinstance(tool_call.get("arguments"), dict)
                    else {}
                ).get("name")
                or ""
            )
            next_turn_number = next_item[0] if next_item is not None else 0
            next_call_index = next_item[1] if next_item is not None else 0
            next_call = next_item[2] if next_item is not None else {}
            before_context = (
                call.get("providerContext")
                if isinstance(call.get("providerContext"), dict)
                else {}
            )
            after_context = (
                next_call.get("providerContext")
                if isinstance(next_call.get("providerContext"), dict)
                else {}
            )
            before_prompt = str(before_context.get("systemPrompt") or "")
            after_prompt = str(after_context.get("systemPrompt") or "")
            messages = (
                after_context.get("messages")
                if isinstance(after_context.get("messages"), list)
                else []
            )
            matching_results = [
                message
                for message in messages
                if isinstance(message, dict)
                and message.get("role") == "toolResult"
                and message.get("toolName") == "skill_load"
                and str(message.get("toolCallId") or "") == tool_call_id
            ]
            result_text = (
                _content_text(matching_results[-1].get("content"))
                if matching_results
                else ""
            )
            expected_open = (
                f'<loaded_skill name="{skill_name}" revision="sha256:'
            )
            prompt_bytes_unchanged = (
                next_item is not None
                and next_turn_number == turn_number
                and before_prompt.encode("utf-8") == after_prompt.encode("utf-8")
            )
            valid_tool_result = (
                bool(skill_name)
                and len(matching_results) == 1
                and result_text.startswith(expected_open)
                and result_text.endswith("</loaded_skill>")
            )
            restore_counts = [
                prompt.count(result_text)
                for prompt in recovery_prompts
                if result_text
            ]
            evidence.append(
                {
                    "turn": turn_number,
                    "callIndex": call_index,
                    "nextTurn": next_turn_number,
                    "nextCallIndex": next_call_index,
                    "toolCallId": tool_call_id,
                    "skillName": skill_name,
                    "promptBeforeUtf8Bytes": len(before_prompt.encode("utf-8")),
                    "promptAfterUtf8Bytes": len(after_prompt.encode("utf-8")),
                    "promptBeforeSha256": _sha256_text(before_prompt),
                    "promptAfterSha256": _sha256_text(after_prompt),
                    "promptBytesUnchanged": prompt_bytes_unchanged,
                    "toolResultUtf8Bytes": len(result_text.encode("utf-8")),
                    "toolResultSha256": (
                        _sha256_text(result_text) if result_text else ""
                    ),
                    "validLoadedSkillToolResult": valid_tool_result,
                    "toolResultAbsentFromCurrentEpochPrompt": (
                        bool(result_text) and result_text not in after_prompt
                    ),
                    "recoveryPromptExactOccurrenceCounts": restore_counts,
                }
            )

    append_only = bool(evidence) and all(
        item["promptBytesUnchanged"] is True
        and item["validLoadedSkillToolResult"] is True
        and item["toolResultAbsentFromCurrentEpochPrompt"] is True
        for item in evidence
    )
    restored_after_compaction = bool(evidence) and bool(recovery_prompts) and all(
        sum(item["recoveryPromptExactOccurrenceCounts"]) == 1
        for item in evidence
    )
    return evidence, append_only, restored_after_compaction


def _call_sort_key(call: dict[str, Any]) -> tuple[int, int]:
    return (int(call.get("capturedAtMs") or 0), int(call.get("index") or 0))


def _context_sort_key(context: dict[str, Any]) -> tuple[int, str]:
    return (int(context.get("capturedAtMs") or 0), str(context.get("turnId") or ""))


def _markdown_code(value: str, language: str = "text") -> str:
    fence = "````" if "```" in value else "```"
    return f"{fence}{language}\n{value}\n{fence}\n"


def _format_ms(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value / 1000:.3f}s"


def _memory_book_title_echoes(block: str) -> list[str]:
    lines = block.splitlines()
    echoes: list[str] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("#### "):
            continue
        title = line.removeprefix("#### ").strip()
        for candidate in lines[index + 1 :]:
            body = candidate.strip()
            if not body:
                continue
            if body.startswith(("#", "- ")):
                break
            if title and body.startswith(title):
                echoes.append(title)
            break
    return echoes


def _workflow_control_contradictions(
    prompts: list[str],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    unapproved_markers = (
        "计划尚未批准",
        "计划尚未获得用户批准",
    )
    for prompt_index, prompt in enumerate(prompts, start=1):
        for block_index, block in enumerate(
            _extract_context_blocks(prompt, "workflow_state"),
            start=1,
        ):
            status = (
                "completed"
                if "计划：全部完成" in block
                or re.search(r"计划：\s*(\d+)/\1\s*项完成", block)
                else ""
            )
            approval_marker = next(
                (marker for marker in unapproved_markers if marker in block),
                "",
            )
            if status and approval_marker:
                findings.append(
                    {
                        "promptIndex": prompt_index,
                        "blockIndex": block_index,
                        "planStatus": status,
                        "contradictoryMarker": approval_marker,
                    }
                )
    return findings


def _secret_hits(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def render(report_path: Path, output_dir: Path) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve(strict=True)
    report = _read_json(report_path)
    report_schema = str(report.get("schemaVersion") or "")
    surface = (
        "agent"
        if "agent-session-dialogue" in report_schema
        else "room"
    )
    audited_context_types = (
        "workflow_state",
        "room_context",
        "session_memory",
    )
    continuity = (
        report.get("sessionContinuity")
        if isinstance(report.get("sessionContinuity"), dict)
        else {}
    )
    continuity_acceptance = (
        continuity.get("accepted")
        if isinstance(continuity.get("accepted"), dict)
        else {}
    )
    ordinary_turn_ids = {
        str(continuity_acceptance.get("turnId") or "")
    } - {""}
    execution = report.get("execution")
    if not isinstance(execution, dict):
        raise ValueError("report.execution is required")
    state_value = execution.get("state")
    if not isinstance(state_value, str) or state_value == "ephemeral":
        raise ValueError("report must retain an execution.state directory")
    state = Path(state_value).expanduser().resolve(strict=True)
    context_root = state / "context-inspection"
    context_paths = sorted(context_root.glob("**/*.json"))
    if not context_paths:
        raise ValueError(f"no Provider context receipts under {context_root}")

    contexts = [(_read_json(path), path) for path in context_paths]
    contexts.sort(key=lambda item: _context_sort_key(item[0]))
    network_path = state / "external-network-audit.jsonl"
    network = _read_jsonl(network_path) if network_path.is_file() else []
    network.sort(key=lambda item: int(item.get("startedAtMs") or 0))

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "calls").mkdir(parents=True)
    (output_dir / "objects").mkdir(parents=True)
    (output_dir / "raw").mkdir(parents=True)
    (output_dir / "tool-executions").mkdir(parents=True)
    (output_dir / "transcripts").mkdir(parents=True)

    table_rows: list[str] = []
    room_context_sections: list[str] = ["# 模型实际看到的动态上下文", ""]
    prompt_files: list[str] = []
    call_files: list[str] = []
    object_files: list[str] = []
    tool_files: list[str] = []
    tool_execution_files: list[str] = []
    provider_object_summaries: list[dict[str, Any]] = []
    tool_execution_summaries: list[dict[str, Any]] = []
    recovery_prompt_files: list[str] = []
    all_calls: list[tuple[int, int, dict[str, Any]]] = []
    prompt_stable_within_turn = True
    context_block_counts_valid = True
    agent_md_absent = True
    room_metadata_absent = True
    memory_book_title_echoes: list[str] = []
    audited_prompts: list[str] = []

    for turn_number, (context, source_path) in enumerate(contexts, start=1):
        turn_id = str(context.get("turnId") or "")
        session_id = str(context.get("sessionId") or "")
        lifecycle = (
            context.get("lifecycle")
            if isinstance(context.get("lifecycle"), dict)
            else None
        )
        phase_label = (
            f"Lifecycle: {lifecycle.get('kind', 'unknown')}"
            if lifecycle is not None
            else f"Turn {turn_number:02d}"
        )
        raw_calls = context.get("modelCalls")
        calls = [item for item in raw_calls if isinstance(item, dict)] if isinstance(raw_calls, list) else []
        calls.sort(key=_call_sort_key)
        raw_name = f"turn-{turn_number:02d}-{turn_id}.json"
        shutil.copy2(source_path, output_dir / "raw" / raw_name)

        prompt_by_hash: dict[str, str] = {}
        call_prompt_hashes: list[tuple[int, str]] = []
        for call in calls:
            provider_context = call.get("providerContext")
            prompt = (
                str(provider_context.get("systemPrompt") or "")
                if isinstance(provider_context, dict)
                else ""
            )
            prompt_hash = _sha256_text(prompt)
            prompt_by_hash.setdefault(prompt_hash, prompt)
            call_prompt_hashes.append((int(call.get("index") or 0), prompt_hash))
            audited_prompts.append(prompt)
        if calls:
            prompt_stable_within_turn = (
                prompt_stable_within_turn and len(prompt_by_hash) == 1
            )

        prompt_name = f"turn-{turn_number:02d}-system-prompt.md"
        prompt_path = output_dir / prompt_name
        prompt_lines = [
            f"# {phase_label} 完整系统提示词",
            "",
            f"- Session: `{session_id}`",
            f"- Turn: `{turn_id}`",
            *(
                [
                    f"- Lifecycle status: `{lifecycle.get('status', '')}`",
                    f"- Lifecycle reason: `{lifecycle.get('reason', '')}`",
                ]
                if lifecycle is not None
                else []
            ),
            f"- Provider calls: `{len(calls)}`",
            f"- Unique prompt hashes: `{len(prompt_by_hash)}`",
            "",
        ]
        for prompt_index, (prompt_hash, prompt) in enumerate(prompt_by_hash.items(), start=1):
            mapped_calls = [str(index) for index, value in call_prompt_hashes if value == prompt_hash]
            prompt_lines.extend(
                (
                    f"## Prompt {prompt_index}",
                    "",
                    f"- SHA-256: `{prompt_hash}`",
                    f"- Calls: `{', '.join(mapped_calls)}`",
                    f"- UTF-8 bytes: `{len(prompt.encode('utf-8'))}`",
                    "",
                    _markdown_code(prompt),
                )
            )
        prompt_path.write_text("\n".join(prompt_lines), encoding="utf-8")
        prompt_files.append(prompt_name)

        room_context_sections.extend(
            (
                f"## {phase_label}",
                "",
                f"- Session: `{session_id}`",
                f"- Turn: `{turn_id}`",
                f"- Calls: `{len(calls)}`",
                "",
            )
        )
        representative_prompt = next(iter(prompt_by_hash.values()), "")
        if lifecycle is not None:
            room_context_sections.extend(
                (
                    "### 生命周期专用 Provider 上下文",
                    "",
                    "压缩不伪装成用户 Turn；它使用独立摘要 Prompt，完整对象见对应 `objects/`。",
                    "",
                )
            )
        else:
            expected_context_counts = {
                "workflow_state": 1,
                "room_context": (
                    1
                    if surface == "room" and turn_id not in ordinary_turn_ids
                    else 0
                ),
                "session_memory": 1,
            }
            for context_type in audited_context_types:
                blocks = _extract_context_blocks(representative_prompt, context_type)
                expected_count = expected_context_counts[context_type]
                context_block_counts_valid = (
                    context_block_counts_valid
                    and len(blocks) == expected_count
                )
                room_context_sections.extend(
                    (
                        f"### `{context_type}`",
                        "",
                        _markdown_code(
                            "\n\n".join(blocks)
                            if blocks
                            else (
                                "<not injected: ordinary Agent turn>"
                                if expected_count == 0
                                else "<missing>"
                            )
                        ),
                    )
                )
                if context_type == "room_context":
                    room_metadata_absent = room_metadata_absent and not any(
                        marker in block for block in blocks for marker in FORBIDDEN_ROOM_METADATA
                    )
                elif context_type == "session_memory":
                    memory_book_title_echoes.extend(
                        title
                        for block in blocks
                        for title in _memory_book_title_echoes(block)
                    )
            agent_md_absent = agent_md_absent and "<project_context>" not in representative_prompt

        tools = context.get("toolExecutions")
        tool_list = [item for item in tools if isinstance(item, dict)] if isinstance(tools, list) else []
        tool_name = f"turn-{turn_number:02d}-tool-executions.json"
        _write_json(
            output_dir / tool_name,
            {
                "schemaVersion": SCHEMA_VERSION,
                "sessionId": session_id,
                "turnId": turn_id,
                "toolExecutions": tool_list,
                "toolBatches": context.get("toolBatches") or [],
            },
        )
        tool_files.append(tool_name)
        for execution_index, tool_execution in enumerate(tool_list, start=1):
            execution_name = (
                f"turn-{turn_number:02d}-execution-{execution_index:03d}-"
                f"{_safe_file_part(tool_execution.get('toolName'))}.json"
            )
            summary = _tool_execution_summary(tool_execution)
            _write_json(
                output_dir / "tool-executions" / execution_name,
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "executionIndex": execution_index,
                    "summary": summary,
                    "execution": tool_execution,
                },
            )
            tool_execution_files.append(
                f"tool-executions/{execution_name}"
            )
            tool_execution_summaries.append(
                {
                    "turn": turn_number,
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "executionIndex": execution_index,
                    "file": f"tool-executions/{execution_name}",
                    **summary,
                }
            )

        request_receipts = {
            int(item.get("index") or 0): item
            for item in (context.get("providerRequestReceipts") or [])
            if isinstance(item, dict)
        }
        cache_evidence = {
            int(item.get("requestIndex") or 0): item
            for item in (context.get("cacheEvidence") or [])
            if isinstance(item, dict)
        }
        for call in calls:
            call_index = int(call.get("index") or 0)
            provider_context = call.get("providerContext")
            call_name = f"turn-{turn_number:02d}-call-{call_index:03d}.json"
            object_dir_name = (
                f"turn-{turn_number:02d}-call-{call_index:03d}"
            )
            object_dir = output_dir / "objects" / object_dir_name
            object_dir.mkdir(parents=True, exist_ok=True)
            context_record = (
                provider_context
                if isinstance(provider_context, dict)
                else {}
            )
            exact_prompt = str(context_record.get("systemPrompt") or "")
            exact_messages = (
                context_record.get("messages")
                if isinstance(context_record.get("messages"), list)
                else []
            )
            exact_tools = (
                context_record.get("tools")
                if isinstance(context_record.get("tools"), list)
                else []
            )
            object_summary = _provider_object_summary(context_record)
            object_summary.update(
                {
                    "turn": turn_number,
                    "sessionId": session_id,
                    "turnId": turn_id,
                    "callIndex": call_index,
                    "contextDelta": call.get("contextDelta"),
                    "files": {
                        "systemPrompt": (
                            f"objects/{object_dir_name}/system-prompt.txt"
                        ),
                        "messages": (
                            f"objects/{object_dir_name}/messages.json"
                        ),
                        "tools": f"objects/{object_dir_name}/tools.json",
                    },
                }
            )
            (object_dir / "system-prompt.txt").write_text(
                exact_prompt,
                encoding="utf-8",
            )
            _write_json(object_dir / "messages.json", exact_messages)
            _write_json(object_dir / "tools.json", exact_tools)
            _write_json(object_dir / "summary.json", object_summary)
            object_files.extend(
                [
                    f"objects/{object_dir_name}/system-prompt.txt",
                    f"objects/{object_dir_name}/messages.json",
                    f"objects/{object_dir_name}/tools.json",
                    f"objects/{object_dir_name}/summary.json",
                ]
            )
            provider_object_summaries.append(object_summary)
            assistant = call.get("assistantMessage")
            safe_call = {
                "schemaVersion": SCHEMA_VERSION,
                "sourceReceipt": str(source_path),
                "sessionId": session_id,
                "turnId": turn_id,
                "callIndex": call_index,
                "runtimeTurnIndex": call.get("runtimeTurnIndex"),
                "capturedAtMs": call.get("capturedAtMs"),
                "completedAtMs": call.get("completedAtMs"),
                "providerContext": provider_context,
                "contextDelta": call.get("contextDelta"),
                "assistantMessage": assistant,
                "providerExchanges": _safe_provider_exchanges(call.get("providerExchanges")),
                "providerRequestReceipt": request_receipts.get(call_index),
                "cacheEvidence": cache_evidence.get(call_index),
                "contextViews": {
                    "providerContext": "normalized effective context",
                    "providerExchanges[].payload": "exact credential-free wire request",
                },
            }
            _write_json(output_dir / "calls" / call_name, safe_call)
            call_files.append(f"calls/{call_name}")
            all_calls.append((turn_number, call_index, call))

    (output_dir / "room-contexts.md").write_text(
        "\n".join(room_context_sections),
        encoding="utf-8",
    )
    _write_json(output_dir / "external-network-audit.json", network)

    transcript_entries: list[dict[str, Any]] = []
    transcript_files: list[str] = []
    session_root = state / "app-support" / "Agent" / "sessions"
    for source_path in sorted(session_root.glob("*.jsonl")):
        name = source_path.name
        target = output_dir / "transcripts" / name
        shutil.copy2(source_path, target)
        transcript_files.append(f"transcripts/{name}")
        transcript_entries.extend(_read_jsonl(source_path))
    compactions = [item for item in transcript_entries if item.get("type") == "compaction"]
    _write_json(output_dir / "compaction-records.json", compactions)

    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    recovery_packets_valid = True
    recovery_prompts: list[str] = []
    if surface == "agent":
        after = report.get("afterCompaction")
        current = (
            after.get("currentProviderContext")
            if isinstance(after, dict)
            else None
        )
        prompt = (
            str(current.get("systemPrompt") or "")
            if isinstance(current, dict)
            else ""
        )
        audited_prompts.append(prompt)
        recovery_prompts.append(prompt)
        recovery_packets_valid = (
            checks.get("compactionRecoveryValid") is True
            and len(compactions) == 1
            and prompt.count("## 压缩恢复包（本 epoch 唯一）") == 1
        )
        name = "compaction-01-recovery-prompt.md"
        lines = [
            "# 压缩 01 后的完整 Provider 系统上下文",
            "",
            "这是普通 Agent 压缩换代后，Pi 当前持有的精确系统上下文。",
            "",
            _markdown_code(prompt),
        ]
        (output_dir / name).write_text("\n".join(lines), encoding="utf-8")
        recovery_prompt_files.append(name)
    else:
        recovery_entries: list[tuple[str, dict[str, Any], bool]] = []
        room_compaction = report.get("compaction")
        if isinstance(room_compaction, dict):
            for member, raw_entry in sorted(room_compaction.items()):
                if not isinstance(raw_entry, dict):
                    continue
                after = raw_entry.get("after")
                if not isinstance(after, dict):
                    continue
                recovery_entries.append(
                    (
                        str(member),
                        after,
                        raw_entry.get("passed") is True,
                    )
                )
        else:
            raw_epochs = report.get("epochs")
            epochs = (
                [item for item in raw_epochs if isinstance(item, dict)]
                if isinstance(raw_epochs, list)
                else []
            )
            for epoch in epochs:
                after = epoch.get("afterCompaction")
                if not isinstance(after, dict):
                    continue
                recovery_entries.append(
                    (
                        str(epoch.get("index") or len(recovery_entries) + 1),
                        after,
                        True,
                    )
                )
        if compactions:
            recovery_packets_valid = len(recovery_entries) == len(compactions)
        for index, (member, after, entry_passed) in enumerate(
            recovery_entries,
            start=1,
        ):
            current = (
                after.get("currentProviderContext")
                if isinstance(after, dict)
                else None
            )
            prompt = (
                str(current.get("systemPrompt") or "")
                if isinstance(current, dict)
                else ""
            )
            audited_prompts.append(prompt)
            recovery_prompts.append(prompt)
            packet = _recovery_packet(prompt)
            recovery_packets_valid = (
                recovery_packets_valid
                and entry_passed
                and _valid_recovery_packet(packet)
            )
            name = f"compaction-{index:02d}-recovery-prompt.md"
            lines = [
                f"# 压缩 {index:02d} 后的完整 Provider 系统上下文",
                "",
                f"- Room member: `{member}`",
                "",
                "这是该成员压缩换代后，Pi 当前持有的精确系统上下文。",
                "",
                _markdown_code(prompt),
                "## 恢复包 JSON",
                "",
                _markdown_code(
                    json.dumps(
                        packet,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    if packet is not None
                    else "<invalid>",
                    "json",
                ),
            ]
            (output_dir / name).write_text(
                "\n".join(lines),
                encoding="utf-8",
            )
            recovery_prompt_files.append(name)

    all_calls.sort(key=lambda item: _call_sort_key(item[2]))
    wire_evidence_required = (
        str(execution.get("providerMode") or "") != "deterministic"
    )
    exact_wire_payloads_captured = True
    normalized_prompts_match_wire = True
    effective_tools_match_wire = True
    for position, (turn_number, call_index, call) in enumerate(all_calls):
        provider_context = call.get("providerContext")
        prompt = (
            str(provider_context.get("systemPrompt") or "")
            if isinstance(provider_context, dict)
            else ""
        )
        messages = provider_context.get("messages") if isinstance(provider_context, dict) else []
        object_summary = _provider_object_summary(provider_context)
        usage = _usage(call)
        wire_prompt = _wire_system_prompt(call)
        wire_tools = _wire_tool_names(call)
        if wire_evidence_required:
            exact_wire_payloads_captured = (
                exact_wire_payloads_captured
                and _provider_wire_payload(call) is not None
            )
            normalized_prompts_match_wire = (
                normalized_prompts_match_wire
                and wire_prompt is not None
                and wire_prompt == prompt
            )
            effective_tools_match_wire = (
                effective_tools_match_wire
                and wire_tools is not None
                and set(wire_tools) == set(_tool_names(provider_context))
            )
        network_item = network[position] if position < len(network) else {}
        duration = (
            int(network_item.get("completedAtMs") or 0)
            - int(network_item.get("startedAtMs") or 0)
            if network_item
            else None
        )
        table_rows.append(
            "| {turn} | {call} | {prompt_bytes} | {message_count} | {message_bytes} | "
            "{tool_count} | {tool_bytes} | {cache} | {status} | {duration} | "
            "[{file}]({file}) |".format(
                turn=turn_number,
                call=call_index,
                prompt_bytes=len(prompt.encode("utf-8")),
                message_count=len(messages) if isinstance(messages, list) else 0,
                message_bytes=int(
                    object_summary.get("messagesContentUtf8Bytes") or 0
                ),
                tool_count=len(_tool_names(provider_context)),
                tool_bytes=int(object_summary.get("toolsJsonBytes") or 0),
                cache=int(usage.get("cacheRead") or 0),
                status=network_item.get("status", "-"),
                duration=_format_ms(duration),
                file=f"calls/turn-{turn_number:02d}-call-{call_index:03d}.json",
            )
        )

    exact_call_count_matches_network = (
        not wire_evidence_required
        or len(all_calls) == len(network)
    )
    read_summaries = [
        item
        for item in tool_execution_summaries
        if item["toolName"] == "workspace_read"
        and item["isError"] is False
    ]
    read_receipts_complete = bool(read_summaries) and all(
        isinstance(item.get("workspaceRead"), dict)
        and item.get("workspaceReadModelJsonValid") is True
        and item.get("workspaceReadModelReceiptMatchesDetails") is True
        for item in read_summaries
    )
    read_results_bounded = read_receipts_complete and all(
        int((item["workspaceRead"] or {}).get("contentBytes") or 0)
        <= 50 * 1024
        and int((item["workspaceRead"] or {}).get("contentLines") or 0)
        <= 2_000
        and int(item.get("modelVisibleTextBytes") or 0)
        <= 50 * 1024
        for item in read_summaries
    )
    read_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in read_summaries:
        args = item.get("args")
        path = str(args.get("path") or "") if isinstance(args, dict) else ""
        read_groups.setdefault((str(item.get("sessionId") or ""), path), []).append(item)
    read_continuations_exact = True
    for group in read_groups.values():
        final_receipt = group[-1].get("workspaceRead")
        if (
            isinstance(final_receipt, dict)
            and final_receipt.get("truncated") is True
        ):
            read_continuations_exact = False
        for current, following in zip(group[:-1], group[1:], strict=True):
            receipt = current.get("workspaceRead")
            following_args = following.get("args")
            if (
                isinstance(receipt, dict)
                and receipt.get("truncated") is True
                and (
                    not isinstance(following_args, dict)
                    or following_args.get("offset")
                    != receipt.get("nextOffset")
                )
            ):
                read_continuations_exact = False
        for item in group:
            receipt = item.get("workspaceRead")
            args = item.get("args")
            if not isinstance(receipt, dict) or not isinstance(args, dict):
                read_continuations_exact = False
                continue
            if (
                int(receipt.get("nextOffset") or 0)
                - int(args.get("offset") or 0)
                != int(receipt.get("contentBytes") or 0)
            ):
                read_continuations_exact = False
    before_compaction = (
        report.get("beforeCompaction")
        if isinstance(report.get("beforeCompaction"), dict)
        else {}
    )
    prompt_checks = (
        report.get("promptChecks")
        if isinstance(report.get("promptChecks"), dict)
        else {}
    )
    transcript_isolation = (
        report.get("transcriptIsolation")
        if isinstance(report.get("transcriptIsolation"), dict)
        else {}
    )
    progressive_disclosure = (
        before_compaction.get("progressiveDiscovery") is True
        if surface == "agent"
        else prompt_checks.get("progressiveDiscovery") is True
    )
    provider_prefix = before_compaction.get("providerPrefix")
    provider_prefix_stable = (
        (
            checks.get("providerPrefixStable") is True
            or (
                isinstance(provider_prefix, dict)
                and provider_prefix.get("passed") is True
            )
        )
        if surface == "agent"
        else prompt_checks.get("providerPrefixStable") is True
    )
    session_transcripts_private = (
        checks.get("noRoomRuntimeSurface") is True
        if surface == "agent"
        else transcript_isolation.get("passed") is True
    )
    (
        skill_load_epoch_evidence,
        skill_load_append_only,
        loaded_skills_restored_after_compaction,
    ) = _skill_load_context_epoch_evidence(all_calls, recovery_prompts)
    workflow_control_contradictions = _workflow_control_contradictions(
        audited_prompts
    )
    audit_checks = {
        "reportChecksPassed": bool(checks) and all(value is True for value in checks.values()),
        "exactProviderCallsCaptured": exact_call_count_matches_network,
        "wireEvidenceRequiredOrExplicitlyDeterministic": (
            wire_evidence_required
            or str(execution.get("providerMode") or "") == "deterministic"
        ),
        "exactWirePayloadsCaptured": (
            not wire_evidence_required
            or exact_wire_payloads_captured
        ),
        "normalizedPromptMatchesWire": (
            not wire_evidence_required
            or normalized_prompts_match_wire
        ),
        "effectiveToolSetMatchesWireDisclosure": (
            not wire_evidence_required
            or effective_tools_match_wire
        ),
        "systemPromptStableWithinEachTurn": prompt_stable_within_turn,
        "contextBlocksExactlyOncePerTurn": context_block_counts_valid,
        "agentMdDefaultOff": agent_md_absent,
        "roomDynamicMetadataAbsent": (
            surface == "agent"
            or room_metadata_absent
        ),
        "memoryBookTitleEchoAbsent": not memory_book_title_echoes,
        "workflowControlSemanticallyConsistent": (
            not workflow_control_contradictions
        ),
        "externalRequestsSucceeded": (
            not wire_evidence_required
            or (
                bool(network)
                and all(
                    int(item.get("status") or 0) in range(200, 300)
                    for item in network
                )
            )
        ),
        "modelVisibleToolResultsBounded": all(
            int(item.get("modelVisibleTextBytes") or 0)
            <= 50 * 1024
            for item in tool_execution_summaries
        ),
        "workspaceReadReceiptsComplete": read_receipts_complete,
        "workspaceReadResultsBounded": read_results_bounded,
        "workspaceReadContinuationsExact": read_continuations_exact,
        "progressiveSkillToolDisclosure": progressive_disclosure,
        "providerPrefixStable": provider_prefix_stable,
        "roomContextAbsentFromSessionTranscript": session_transcripts_private,
        "oneExactRecoveryPacketPerCompaction": recovery_packets_valid,
    }
    if surface == "agent":
        audit_checks.update(
            {
                "skillLoadAppendsOnlyToolResultInCurrentEpoch": (
                    skill_load_append_only
                ),
                "loadedSkillBodiesRestoredExactlyAfterCompaction": (
                    loaded_skills_restored_after_compaction
                ),
            }
        )

    metadata = {
        "schemaVersion": SCHEMA_VERSION,
        "surface": surface,
        "sourceReport": str(report_path),
        "state": str(state),
        "provider": execution.get("provider"),
        "model": execution.get("model"),
        "providerEndpoint": execution.get("providerEndpoint"),
        "scenario": execution.get("scenario"),
        "turnCount": len(contexts),
        "providerCallCount": len(all_calls),
        "externalRequestCount": len(network),
        "toolExecutionCount": sum(
            len(context.get("toolExecutions") or []) for context, _ in contexts
        ),
        "compactionCount": len(compactions),
        "checks": audit_checks,
        "memoryBookTitleEchoes": sorted(set(memory_book_title_echoes)),
        "workflowControlContradictions": workflow_control_contradictions,
        "promptFiles": prompt_files,
        "roomContextFile": "room-contexts.md",
        "callFiles": call_files,
        "objectFiles": object_files,
        "providerObjectSummaries": provider_object_summaries,
        "toolFiles": tool_files,
        "toolExecutionFiles": tool_execution_files,
        "toolExecutionSummaries": tool_execution_summaries,
        "recoveryPromptFiles": recovery_prompt_files,
        "transcriptFiles": transcript_files,
        "skillLoadContextEpochEvidence": skill_load_epoch_evidence,
    }
    _write_json(
        output_dir / "context-epoch-invariants.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "surface": surface,
            "invariant": (
                "Within one Context Epoch, skill_load must not modify any "
                "existing systemPrompt byte; it may only append a Tool Result. "
                "Exact loaded Skill bodies may enter systemPrompt only after "
                "compaction creates the next Context Epoch."
            ),
            "skillLoadEvidence": skill_load_epoch_evidence,
            "skillLoadAppendsOnlyToolResultInCurrentEpoch": (
                skill_load_append_only if surface == "agent" else None
            ),
            "loadedSkillBodiesRestoredExactlyAfterCompaction": (
                loaded_skills_restored_after_compaction
                if surface == "agent"
                else None
            ),
        },
    )
    _write_json(output_dir / "audit.json", metadata)

    readme = [
        f"# {'普通 Agent' if surface == 'agent' else '三成员 Room'} Provider 上下文审计",
        "",
        "这不是配置推断，而是 Pi 在每次 Provider 请求前记录的最终上下文。",
        "每个调用同时保留两种视图：`providerContext` 是合并动态 Tool schema 后的有效上下文；",
        "`objects/` 把每次请求的 `systemPrompt`、`messages`、`tools` 分成三个原始对象；",
        "`providerExchanges[].payload` 是去除请求头和凭证后的原始 Provider wire request。",
        "确定性 Provider 没有外网 wire payload，因此只证明真实 Pi Agent Loop/Tool Loop 上下文，不冒充真实 KV cache。",
        "",
        "## 执行身份",
        "",
        f"- Provider: `{execution.get('provider', '')}`",
        f"- Model: `{execution.get('model', '')}`",
        f"- Endpoint: `{execution.get('providerEndpoint', '')}`",
        f"- Scenario: `{execution.get('scenario', '')}`",
        f"- Provider calls: `{len(all_calls)}`",
        f"- External HTTPS requests: `{len(network)}`",
        f"- Tool executions: `{metadata['toolExecutionCount']}`",
        f"- Compactions: `{len(compactions)}`",
        "",
        "## 自动检查",
        "",
        *[
            f"- {'PASS' if value else 'FAIL'} `{name}`"
            for name, value in audit_checks.items()
        ],
        "",
        "## 每次 Provider 调用",
        "",
        "| Turn | Call | System B | Messages | Message content B | Tools | Tools B | Cache read | HTTP | Duration | Exact context |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        *table_rows,
        "",
        "## 直接查看",
        "",
        "- [动态 Room / Session 上下文](room-contexts.md)",
        "- [外网请求证据](external-network-audit.json)",
        "- [压缩记录](compaction-records.json)",
        "- [Context Epoch 字节不变量](context-epoch-invariants.json)",
        "- [逐调用对象与字节/hash 清单](audit.json)",
        *[
            f"- [压缩后完整恢复上下文 {index}]({name})"
            for index, name in enumerate(recovery_prompt_files, start=1)
        ],
        *[f"- [完整系统提示词 {index}]({name})" for index, name in enumerate(prompt_files, start=1)],
        "",
        "`calls/` 中每个 JSON 都包含该次请求的归一化有效 `providerContext`、增量、模型回复、usage 与去除响应头后的原始 wire payload。",
        "`objects/turn-*/` 中分别保存完整 `system-prompt.txt`、`messages.json`、`tools.json` 和对象级字节/hash 摘要。",
        "`tool-executions/` 中每个文件保存一次完整 Tool 参数、结果、失败状态、耗时和模型可见字节数；workspace_read 另列 offset/nextOffset/字符/字节/行/截断。",
        "Tool `details` 只供界面与审计保留；Provider 适配器只发送 ToolResult 的模型可见 `content`，表中的 Message content B 不把审计副本冒充模型上下文。",
        "动态 Tool schema 可能位于顶层 `tools` 或历史 `tool_search_output`；有效工具集会合并两处并与 wire payload 自动对账。",
        "`raw/` 是 Pi 原始调试回执，`transcripts/` 是受管 Session JSONL。",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")

    secret_hits = {
        str(path.relative_to(output_dir)): _secret_hits(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".txt"}
    }
    secret_hits = {path: hits for path, hits in secret_hits.items() if hits}
    metadata["checks"]["credentialLeakAbsent"] = not secret_hits
    metadata["credentialLeakFindings"] = secret_hits
    _write_json(output_dir / "audit.json", metadata)
    if secret_hits:
        raise RuntimeError(f"credential-like values found: {secret_hits}")
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render exact Provider contexts from a retained Room canary state"
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = render(args.report, args.output_dir)
    print(
        _json_text(
            {
                "outputDir": str(args.output_dir.resolve()),
                "provider": metadata.get("provider"),
                "model": metadata.get("model"),
                "providerCallCount": metadata.get("providerCallCount"),
                "toolExecutionCount": metadata.get("toolExecutionCount"),
                "compactionCount": metadata.get("compactionCount"),
                "checks": metadata.get("checks"),
            }
        ),
        end="",
    )
    return 0 if all(metadata["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
