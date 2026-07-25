from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


TEMPLATE_PATH = Path(__file__).with_name("templates") / "agent-prompt-audit.html"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _context_calls(directory: Path) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    for path in sorted((directory / "calls").glob("*.json")):
        raw = _read_json(path)
        if not isinstance(raw, Mapping):
            continue
        provider_context = raw.get("providerContext")
        if not isinstance(provider_context, Mapping):
            provider_context = {}
        messages = provider_context.get("messages")
        if not isinstance(messages, list):
            messages = []
        tools = provider_context.get("tools")
        if not isinstance(tools, list):
            tools = []
        calls.append(
            {
                "file": path.name,
                "runtimeTurnIndex": raw.get("runtimeTurnIndex"),
                "callIndex": raw.get("callIndex"),
                "turnId": raw.get("turnId"),
                "sessionId": raw.get("sessionId"),
                "capturedAtMs": raw.get("capturedAtMs"),
                "completedAtMs": raw.get("completedAtMs"),
                "systemPrompt": provider_context.get("systemPrompt", ""),
                "messages": messages,
                "tools": tools,
                "providerContext": dict(provider_context),
                "assistantMessage": raw.get("assistantMessage"),
                "contextDelta": raw.get("contextDelta"),
                "cacheEvidence": raw.get("cacheEvidence"),
                "providerRequestReceipt": raw.get("providerRequestReceipt"),
                "receipts": {
                    "cacheEvidence": raw.get("cacheEvidence"),
                    "providerRequestReceipt": raw.get("providerRequestReceipt"),
                    "capturedAtMs": raw.get("capturedAtMs"),
                    "completedAtMs": raw.get("completedAtMs"),
                },
            }
        )
    return calls


def _tool_executions(directory: Path) -> list[dict[str, object]]:
    executions: list[dict[str, object]] = []
    for path in sorted((directory / "tool-executions").glob("*.json")):
        raw = _read_json(path)
        if not isinstance(raw, Mapping):
            continue
        executions.append({"file": path.name, **dict(raw)})
    return executions


def _context_scenario(
    audit_root: Path,
    *,
    key: str,
    label: str,
    directory_name: str,
) -> dict[str, object]:
    directory = audit_root / directory_name
    audit_path = directory / "audit.json"
    if not audit_path.is_file():
        return {
            "key": key,
            "label": label,
            "available": False,
            "calls": [],
            "toolExecutions": [],
        }
    audit = _read_json(audit_path)
    if not isinstance(audit, Mapping):
        audit = {}
    return {
        "key": key,
        "label": label,
        "available": True,
        "summary": dict(audit),
        "calls": _context_calls(directory),
        "toolExecutions": _tool_executions(directory),
    }


def build_html_payload(
    audit: Mapping[str, object],
    *,
    audit_root: Path,
) -> dict[str, object]:
    return {
        "schemaVersion": audit["schemaVersion"],
        "promptRecords": audit["promptRecords"],
        "modelRequestRoutes": audit["modelRequestRoutes"],
        "skills": audit["skills"],
        "tools": audit["tools"],
        "references": audit["references"],
        "findings": audit["findings"],
        "promptSymbolInventory": audit["promptSymbolInventory"],
        "deterministicEvidence": audit["deterministicEvidence"],
        "contexts": [
            _context_scenario(
                audit_root,
                key="agent",
                label="普通 Agent",
                directory_name="provider-agent-deterministic",
            ),
            _context_scenario(
                audit_root,
                key="room",
                label="三成员 Room",
                directory_name="provider-room-deterministic",
            ),
        ],
    }


def render_audit_html(
    audit: Mapping[str, object],
    *,
    output: Path,
    audit_root: Path,
) -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    placeholder = "__AGENT_PROMPT_AUDIT_DATA__"
    if template.count(placeholder) != 1:
        raise ValueError("audit HTML template must contain exactly one data placeholder")
    payload = json.dumps(
        build_html_payload(audit, audit_root=audit_root),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    rendered = template.replace(placeholder, payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
