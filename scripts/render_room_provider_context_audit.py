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


SCHEMA_VERSION = "wisdom-weasel.room-provider-context-audit.v1"
CONTEXT_TYPES = ("workflow_control", "room_context", "session_memory")
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


def _extract_context_blocks(prompt: str, context_type: str) -> list[str]:
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


def _usage(call: dict[str, Any]) -> dict[str, Any]:
    assistant = call.get("assistantMessage")
    if not isinstance(assistant, dict):
        return {}
    usage = assistant.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


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


def _secret_hits(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def render(report_path: Path, output_dir: Path) -> dict[str, Any]:
    report_path = report_path.expanduser().resolve(strict=True)
    report = _read_json(report_path)
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
    (output_dir / "raw").mkdir(parents=True)
    (output_dir / "transcripts").mkdir(parents=True)

    table_rows: list[str] = []
    room_context_sections: list[str] = ["# 模型实际看到的动态上下文", ""]
    prompt_files: list[str] = []
    call_files: list[str] = []
    tool_files: list[str] = []
    recovery_prompt_files: list[str] = []
    all_calls: list[tuple[int, int, dict[str, Any]]] = []
    prompt_stable_within_turn = True
    context_block_counts_valid = True
    agent_md_absent = True
    room_metadata_absent = True
    memory_book_title_echoes: list[str] = []

    for turn_number, (context, source_path) in enumerate(contexts, start=1):
        turn_id = str(context.get("turnId") or "")
        session_id = str(context.get("sessionId") or "")
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
        prompt_stable_within_turn = prompt_stable_within_turn and len(prompt_by_hash) == 1

        prompt_name = f"turn-{turn_number:02d}-system-prompt.md"
        prompt_path = output_dir / prompt_name
        prompt_lines = [
            f"# Turn {turn_number:02d} 完整系统提示词",
            "",
            f"- Session: `{session_id}`",
            f"- Turn: `{turn_id}`",
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
                f"## Turn {turn_number:02d}",
                "",
                f"- Session: `{session_id}`",
                f"- Turn: `{turn_id}`",
                f"- Calls: `{len(calls)}`",
                "",
            )
        )
        representative_prompt = next(iter(prompt_by_hash.values()), "")
        for context_type in CONTEXT_TYPES:
            blocks = _extract_context_blocks(representative_prompt, context_type)
            context_block_counts_valid = context_block_counts_valid and len(blocks) == 1
            room_context_sections.extend(
                (
                    f"### `{context_type}`",
                    "",
                    _markdown_code("\n\n".join(blocks) if blocks else "<missing>"),
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

    recovery_packets_valid = True
    raw_epochs = report.get("epochs")
    epochs = [item for item in raw_epochs if isinstance(item, dict)] if isinstance(raw_epochs, list) else []
    if compactions:
        recovery_packets_valid = len(epochs) == len(compactions)
    for epoch in epochs:
        index = int(epoch.get("index") or len(recovery_prompt_files) + 1)
        after = epoch.get("afterCompaction")
        current = after.get("currentProviderContext") if isinstance(after, dict) else None
        prompt = str(current.get("systemPrompt") or "") if isinstance(current, dict) else ""
        packet = _recovery_packet(prompt)
        recovery_packets_valid = recovery_packets_valid and _valid_recovery_packet(packet)
        name = f"compaction-{index:02d}-recovery-prompt.md"
        lines = [
            f"# 压缩 {index:02d} 后的完整 Provider 系统上下文",
            "",
            "这是压缩换代完成、下一任务尚未覆盖 Room Context 时，Pi 当前持有的精确系统上下文。",
            "",
            _markdown_code(prompt),
            "## 恢复包 JSON",
            "",
            _markdown_code(
                json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True)
                if packet is not None
                else "<invalid>",
                "json",
            ),
        ]
        (output_dir / name).write_text("\n".join(lines), encoding="utf-8")
        recovery_prompt_files.append(name)

    all_calls.sort(key=lambda item: _call_sort_key(item[2]))
    for position, (turn_number, call_index, call) in enumerate(all_calls):
        provider_context = call.get("providerContext")
        prompt = (
            str(provider_context.get("systemPrompt") or "")
            if isinstance(provider_context, dict)
            else ""
        )
        messages = provider_context.get("messages") if isinstance(provider_context, dict) else []
        usage = _usage(call)
        network_item = network[position] if position < len(network) else {}
        duration = (
            int(network_item.get("completedAtMs") or 0)
            - int(network_item.get("startedAtMs") or 0)
            if network_item
            else None
        )
        table_rows.append(
            "| {turn} | {call} | {prompt_bytes} | {messages} | {tools} | {cache} | {status} | {duration} | "
            "[{file}]({file}) |".format(
                turn=turn_number,
                call=call_index,
                prompt_bytes=len(prompt.encode("utf-8")),
                messages=len(messages) if isinstance(messages, list) else 0,
                tools=len(_tool_names(provider_context)),
                cache=int(usage.get("cacheRead") or 0),
                status=network_item.get("status", "-"),
                duration=_format_ms(duration),
                file=f"calls/turn-{turn_number:02d}-call-{call_index:03d}.json",
            )
        )

    exact_call_count_matches_network = not network or len(all_calls) == len(network)
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    audit_checks = {
        "reportChecksPassed": bool(checks) and all(value is True for value in checks.values()),
        "exactProviderCallsCaptured": exact_call_count_matches_network,
        "systemPromptStableWithinEachTurn": prompt_stable_within_turn,
        "contextBlocksExactlyOncePerTurn": context_block_counts_valid,
        "agentMdDefaultOff": agent_md_absent,
        "roomDynamicMetadataAbsent": room_metadata_absent,
        "memoryBookTitleEchoAbsent": not memory_book_title_echoes,
        "externalRequestsSucceeded": bool(network)
        and all(int(item.get("status") or 0) in range(200, 300) for item in network),
        "progressiveSkillToolDisclosure": (
            checks.get("skillToolDiscoveryProgressive") is True
            or checks.get("skillToolDiscoveryIsProgressive") is True
        ),
        "providerPrefixStable": (
            checks.get("providerPrefixStable") is True
            or checks.get("providerPrefixesStableWithinEpoch") is True
        ),
        "roomContextAbsentFromSessionTranscript": checks.get(
            "roomContextAbsentFromSessionTranscript"
        )
        is True,
        "oneExactRecoveryPacketPerCompaction": recovery_packets_valid,
    }

    metadata = {
        "schemaVersion": SCHEMA_VERSION,
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
        "promptFiles": prompt_files,
        "roomContextFile": "room-contexts.md",
        "callFiles": call_files,
        "toolFiles": tool_files,
        "recoveryPromptFiles": recovery_prompt_files,
        "transcriptFiles": transcript_files,
    }
    _write_json(output_dir / "audit.json", metadata)

    readme = [
        "# Room 真实 Provider 上下文审计",
        "",
        "这不是配置推断，而是 Pi 在每次 Provider 请求前记录的最终上下文。",
        "所有请求头和凭证均不进入这些文件；模型看到的系统提示词、消息、Tool schema、回执与 usage 保留原样。",
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
        "| Turn | Call | System bytes | Messages | Tools | Cache read | HTTP | Duration | Exact context |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        *table_rows,
        "",
        "## 直接查看",
        "",
        "- [动态 Room / Session 上下文](room-contexts.md)",
        "- [外网请求证据](external-network-audit.json)",
        "- [压缩记录](compaction-records.json)",
        *[
            f"- [压缩后完整恢复上下文 {index}]({name})"
            for index, name in enumerate(recovery_prompt_files, start=1)
        ],
        *[f"- [完整系统提示词 {index}]({name})" for index, name in enumerate(prompt_files, start=1)],
        "",
        "`calls/` 中每个 JSON 都包含该次请求的完整 `providerContext`、增量、模型回复、usage 与去除响应头后的交换记录。",
        "`raw/` 是 Pi 原始调试回执，`transcripts/` 是受管 Session JSONL。",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(readme), encoding="utf-8")

    secret_hits = {
        str(path.relative_to(output_dir)): _secret_hits(path)
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}
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
    print(_json_text(metadata), end="")
    return 0 if all(metadata["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
