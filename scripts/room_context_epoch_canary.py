#!/usr/bin/env python3
"""Run a bounded real-Provider Room context epoch canary.

The script exercises the public Control API only. Exact Provider context is kept
only in an explicit local audit report so prompt and compaction semantics can be
reviewed rather than inferred from configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Protocol


_SESSION_MEMORY_OPEN = '<rag-ime-context type="session_memory">'
_SESSION_MEMORY_CLOSE = "</rag-ime-context>"
_LIFECYCLE_HOOK_OPEN = '<rag-ime-context type="lifecycle_hook"'
_MANAGED_ROOM_AUTHORITY = "当前受管 Room Dispatch 已授权执行"
_CONFLICTING_ROOM_WORKFLOW_TEXT = (
    "计划尚未批准",
    "先创建执行计划并提交审阅",
    "不得执行写操作",
)
_ROUTING_CARD_FIELDS = frozenset(
    {"name", "when", "notFor", "input", "output", "does"}
)
_SKILL_CATALOG_TAG = "available_skills"
_PRODUCT_TOOL_CATALOG_TAG = "available_product_tools"
_SKILL_FAMILY_TAG = "skill_capability_families"
_PRODUCT_TOOL_FAMILY_TAG = "product_tool_capability_families"
_MAX_STAGE_CARD_COUNT = 4
_ROOM_BOOTSTRAP_TOOL_NAMES = frozenset(
    {"room_state", "room_post", "room_commit"}
)
_FORBIDDEN_MEMORY_METADATA = (
    "相关度：",
    "相关度:",
    "命中通道",
    "检索解释",
    "sourceId",
    "source_id",
    "recallId",
    "score=",
    "score：",
    "sha256:",
)
_DEFAULT_WORKLOAD_FILES = (
    "rag_ime/agent_service.py",
    "rag_ime/agent_room_kernel.py",
)
_LEARN_A_WORKLOAD_FILES = tuple(
    f"wisdom-weasel-rag-ime/{path}" for path in _DEFAULT_WORKLOAD_FILES
)


class JsonRequester(Protocol):
    def __call__(
        self,
        base_url: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 130,
    ) -> dict[str, Any]: ...


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 130,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed ({error.code}): {body}") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} {path} returned a non-object response")
    return result


def encoded(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def resolve_workload_files(
    workspace: Path,
    configured: list[Path] | None = None,
) -> tuple[Path, Path]:
    root = workspace.expanduser().resolve(strict=True)
    values: tuple[Path, ...]
    if configured:
        values = tuple(configured)
    elif all((root / value).is_file() for value in _DEFAULT_WORKLOAD_FILES):
        values = tuple(Path(value) for value in _DEFAULT_WORKLOAD_FILES)
    elif all((root / value).is_file() for value in _LEARN_A_WORKLOAD_FILES):
        values = tuple(Path(value) for value in _LEARN_A_WORKLOAD_FILES)
    else:
        raise RuntimeError(
            "Cannot find the two default Room compaction workload files; "
            "pass --workload-file twice"
        )
    if len(values) != 2:
        raise RuntimeError("Room compaction canary requires exactly two workload files")
    resolved: list[Path] = []
    for value in values:
        candidate = value.expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        path = candidate.resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                f"Room compaction workload file is outside the workspace: {path}"
            ) from error
        if not path.is_file():
            raise RuntimeError(f"Room compaction workload is not a file: {path}")
        resolved.append(path)
    if resolved[0] == resolved[1]:
        raise RuntimeError("Room compaction workload files must be distinct")
    return resolved[0], resolved[1]


def accepted_root_id(response: dict[str, Any]) -> str:
    root_id = str(response.get("rootId") or "")
    if not root_id.startswith("room-root:"):
        schema = str(response.get("schemaVersion") or "unknown")
        raise RuntimeError(
            "Room V2 is not active: message acceptance returned "
            f"schema={schema!r}, rootId={root_id!r}"
        )
    return root_id


def wait_for_terminal_dispatch(
    base_url: str,
    room_id: str,
    root_id: str,
    *,
    timeout: float,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = requester(
            base_url,
            "GET",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
            timeout=10,
        )
        roots = [item for item in snapshot.get("roots", []) if item.get("rootId") == root_id]
        dispatches = [
            item for item in snapshot.get("dispatches", []) if item.get("rootId") == root_id
        ]
        root = roots[0] if roots else {}
        last = {
            "rootState": root.get("state"),
            "dispatchStates": [item.get("state") for item in dispatches],
            "dispatchIds": [item.get("dispatchId") for item in dispatches],
        }
        if dispatches and all(
            state in {"committed", "blocked", "failed", "cancelled"}
            for state in last["dispatchStates"]
        ):
            if any(state != "committed" for state in last["dispatchStates"]):
                raise RuntimeError(
                    f"Room Root {root_id} terminated without a committed delivery: {last}"
                )
            return last
        time.sleep(0.5)
    raise TimeoutError(f"Room Root {root_id} did not settle: {last}")


def cancel_root(
    base_url: str,
    room_id: str,
    root_id: str,
    *,
    requester: JsonRequester = request_json,
    timeout: float = 70,
) -> dict[str, Any]:
    snapshot = requester(
        base_url,
        "GET",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
        timeout=min(timeout, 10),
    )
    roots = [
        item
        for item in snapshot.get("roots") or []
        if isinstance(item, dict) and item.get("rootId") == root_id
    ]
    if len(roots) != 1:
        raise RuntimeError(f"Room Root {root_id} is missing during canary cleanup")
    root = roots[0]
    state = str(root.get("state") or "")
    generation = int(root.get("generation", -1))
    if generation < 0:
        raise RuntimeError(f"Room Root {root_id} has no valid cleanup generation")
    if state in {"cancelled", "cancelled_with_unknowns", "completed", "failed"}:
        return {
            "schemaVersion": "wisdom-weasel.room-canary-cleanup.v1",
            "status": "already_terminal",
            "rootId": root_id,
            "rootState": state,
            "generation": generation,
        }
    now_ms = int(time.time() * 1000)
    response = requester(
        base_url,
        "POST",
        f"/api/agent/rooms/{encoded(room_id)}/kernel/commands",
        {
            "schemaVersion": "wisdom-weasel.room-kernel-command.v1",
            "commandId": f"command:canary-cleanup:{now_ms}",
            "rootId": root_id,
            "roomId": room_id,
            "commandKind": "cancel_root",
            "targetKind": "root",
            "targetId": root_id,
            "sourceKind": "control_center",
            "sourceId": "room-context-epoch-canary",
            "idempotencyKey": f"canary-cleanup:{root_id}",
            "generation": generation,
            "payload": {},
            "createdAtMs": now_ms,
        },
        timeout=timeout,
    )
    return {
        "schemaVersion": "wisdom-weasel.room-canary-cleanup.v1",
        "status": "cancel_requested",
        "rootId": root_id,
        "rootState": state,
        "generation": generation,
        "response": response,
    }


def cancel_root_after_failure(
    base_url: str,
    room_id: str,
    root_id: str,
    failure: BaseException,
    *,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    """Best-effort cleanup that never replaces the canary's primary failure."""

    try:
        return cancel_root(
            base_url,
            room_id,
            root_id,
            requester=requester,
        )
    except BaseException as cleanup_error:
        failure.add_note(
            "Room canary cleanup also failed: "
            f"{type(cleanup_error).__name__}: {cleanup_error}"
        )
        return {
            "schemaVersion": "wisdom-weasel.room-canary-cleanup.v1",
            "status": "cleanup_failed",
            "rootId": root_id,
            "error": f"{type(cleanup_error).__name__}: {cleanup_error}",
        }


def _json_bytes(value: object, *, sort_keys: bool = False) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_json_items(values: list[object]) -> list[str]:
    return [_sha256(_json_bytes(value, sort_keys=True)) for value in values]


def _runtime_delta_consistent(call: dict[str, Any]) -> bool:
    delta = call["contextDelta"]
    prefix_bytes = delta["prefixBytes"]
    current_bytes = delta["currentBytes"]
    delta_bytes = delta["deltaBytes"]
    duplicate_bytes = delta["duplicateBytes"]
    if not all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (prefix_bytes, current_bytes, delta_bytes, duplicate_bytes)
    ):
        return False
    return (
        0 <= prefix_bytes <= current_bytes
        and duplicate_bytes == prefix_bytes
        and delta_bytes == current_bytes - prefix_bytes
        and isinstance(delta["prefixSha256"], str)
        and len(delta["prefixSha256"]) == 64
    )


def provider_prefix_evidence(context: dict[str, Any]) -> dict[str, Any]:
    """Return content-free proof that Provider context only appends within a turn."""

    raw_calls = context.get("modelCalls")
    model_calls = raw_calls if isinstance(raw_calls, list) else []
    calls: list[dict[str, Any]] = []
    message_payloads: list[bytes] = []
    for position, raw_call in enumerate(model_calls, start=1):
        if not isinstance(raw_call, dict):
            continue
        provider_context = raw_call.get("providerContext")
        delta = raw_call.get("contextDelta")
        if not isinstance(provider_context, dict) or not isinstance(delta, dict):
            continue
        system_prompt = provider_context.get("systemPrompt")
        messages = provider_context.get("messages")
        tools = provider_context.get("tools")
        if (
            not isinstance(system_prompt, str)
            or not isinstance(messages, list)
            or not isinstance(tools, list)
        ):
            continue
        system_prompt_bytes = system_prompt.encode("utf-8")
        message_bytes = _json_bytes(messages)
        tool_bytes = _json_bytes(tools)
        message_payloads.append(message_bytes)
        calls.append(
            {
                "index": raw_call.get("index", position),
                "systemPromptBytes": len(system_prompt_bytes),
                "systemPromptSha256": _sha256(system_prompt_bytes),
                "messageCount": len(messages),
                "messageBytes": len(message_bytes),
                "messageSha256": _sha256(message_bytes),
                "messageHashes": _hash_json_items(messages),
                "toolCount": len(tools),
                "toolBytes": len(tool_bytes),
                "toolSha256": _sha256(tool_bytes),
                "toolHashes": _hash_json_items(tools),
                "contextDelta": {
                    "baseCallIndex": delta.get("baseCallIndex"),
                    "commonPrefixMessages": delta.get("commonPrefixMessages"),
                    "removedMessageCount": delta.get("removedMessageCount"),
                    "addedMessageCount": delta.get("addedMessageCount"),
                    "prefixBytes": delta.get("prefixBytes"),
                    "prefixSha256": delta.get("prefixSha256"),
                    "currentBytes": delta.get("currentBytes"),
                    "deltaBytes": delta.get("deltaBytes"),
                    "duplicateBytes": delta.get("duplicateBytes"),
                },
            }
        )

    transitions: list[dict[str, Any]] = []
    for offset in range(1, len(calls)):
        previous = calls[offset - 1]
        current = calls[offset]
        previous_bytes = message_payloads[offset - 1]
        current_bytes = message_payloads[offset]
        delta = current["contextDelta"]
        expected_prefix = previous_bytes[:-1]
        message_hashes = current["messageHashes"]
        tool_hashes = current["toolHashes"]
        transitions.append(
            {
                "fromCallIndex": previous["index"],
                "toCallIndex": current["index"],
                "messageHistoryAppendOnly": (
                    message_hashes[: previous["messageCount"]]
                    == previous["messageHashes"]
                    and current["messageCount"] >= previous["messageCount"]
                    and delta["commonPrefixMessages"] == previous["messageCount"]
                    and delta["removedMessageCount"] == 0
                    and delta["addedMessageCount"]
                    == current["messageCount"] - previous["messageCount"]
                ),
                "toolSchemasAppendOnly": (
                    tool_hashes[: previous["toolCount"]] == previous["toolHashes"]
                    and current["toolCount"] >= previous["toolCount"]
                ),
                "messageBytePrefixPreserved": (
                    current_bytes.startswith(expected_prefix)
                ),
                "runtimeMessageBytePrefixPreserved": (
                    isinstance(previous["contextDelta"]["currentBytes"], int)
                    and delta["prefixBytes"]
                    == (
                        previous["contextDelta"]["currentBytes"]
                        if current["messageHashes"]
                        == previous["messageHashes"]
                        else previous["contextDelta"]["currentBytes"] - 1
                    )
                ),
                "providerPrefixBytes": len(expected_prefix),
                "providerPrefixSha256": _sha256(expected_prefix),
            }
        )

    checks = {
        "allModelCallsCaptured": bool(model_calls) and len(calls) == len(model_calls),
        "multipleModelCallsCompared": len(calls) >= 2,
        "stableSystemPrompt": bool(calls)
        and len(
            {
                (call["systemPromptBytes"], call["systemPromptSha256"])
                for call in calls
            }
        )
        == 1,
        "messageHistoryAppendOnly": bool(transitions)
        and all(item["messageHistoryAppendOnly"] for item in transitions),
        "toolSchemasAppendOnly": bool(transitions)
        and all(item["toolSchemasAppendOnly"] for item in transitions),
        "messageBytePrefixPreserved": bool(transitions)
        and all(item["messageBytePrefixPreserved"] for item in transitions),
        "runtimeMessageBytePrefixPreserved": bool(transitions)
        and all(
            item["runtimeMessageBytePrefixPreserved"] for item in transitions
        ),
        "runtimeDeltaConsistent": bool(calls)
        and all(_runtime_delta_consistent(call) for call in calls),
    }
    return {
        "schemaVersion": "wisdom-weasel.provider-prefix-evidence.v1",
        "modelCallCount": len(model_calls),
        "capturedCallCount": len(calls),
        "passed": all(checks.values()),
        "checks": checks,
        "calls": calls,
        "transitions": transitions,
    }


def provider_room_post_visibility(
    context: dict[str, Any],
    markers: Mapping[str, str] | None,
) -> dict[str, dict[str, object]]:
    """Report which captured Provider calls saw named public Room Posts."""

    normalized = {
        str(name): str(marker)
        for name, marker in (markers or {}).items()
        if str(name) and str(marker)
    }
    seen: dict[str, list[object]] = {
        name: [] for name in normalized
    }
    raw_calls = context.get("modelCalls")
    model_calls = raw_calls if isinstance(raw_calls, list) else []
    for position, call in enumerate(model_calls, start=1):
        if not isinstance(call, dict):
            continue
        provider_context = call.get("providerContext")
        if not isinstance(provider_context, dict):
            continue
        prompt = provider_context.get("systemPrompt")
        if not isinstance(prompt, str):
            continue
        post_facts = _room_fact_contents(prompt, "room_post")
        call_index = call.get("index", position)
        for name, marker in normalized.items():
            if any(fact.startswith(marker) for fact in post_facts):
                seen[name].append(call_index)
    return {
        name: {
            "seen": bool(call_indexes),
            "callIndexes": call_indexes,
        }
        for name, call_indexes in seen.items()
    }


def _routing_catalog_evidence(prompt: str, tag: str) -> dict[str, Any]:
    opening = f"<{tag}"
    closing = f"</{tag}>"
    block_count = prompt.count(opening)
    start = prompt.find(opening)
    if start < 0:
        return {
            "blockCount": block_count,
            "cardCount": 0,
            "invalidCardCount": 0,
            "truncatedValueCount": 0,
            "names": set(),
        }
    content_start = prompt.find(">", start)
    end = prompt.find(closing, content_start + 1)
    if content_start < 0 or end < 0:
        return {
            "blockCount": block_count,
            "cardCount": 0,
            "invalidCardCount": 1,
            "truncatedValueCount": 0,
            "names": set(),
        }

    cards: list[dict[str, Any]] = []
    invalid_count = 0
    for raw_line in prompt[content_start + 1 : end].splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            card = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(card, dict) or set(card) != _ROUTING_CARD_FIELDS:
            invalid_count += 1
            continue
        if (
            not isinstance(card.get("name"), str)
            or not isinstance(card.get("when"), list)
            or not all(isinstance(item, str) for item in card["when"])
            or not isinstance(card.get("notFor"), list)
            or not all(isinstance(item, str) for item in card["notFor"])
            or not all(
                isinstance(card.get(field), str)
                for field in ("input", "output", "does")
            )
        ):
            invalid_count += 1
            continue
        cards.append(card)
    truncated_value_count = sum(
        value.rstrip().endswith(("...", "…"))
        for card in cards
        for value in (
            *card["when"],
            *card["notFor"],
            card["input"],
            card["output"],
            card["does"],
        )
    )
    return {
        "blockCount": block_count,
        "cardCount": len(cards),
        "invalidCardCount": invalid_count,
        "truncatedValueCount": truncated_value_count,
        "names": {str(card["name"]) for card in cards},
    }


def _tag_block_count(prompt: str, tag: str) -> int:
    return prompt.count(f"<{tag}")


def _loaded_skill_names(prompt: str) -> set[str]:
    opening = '<loaded_skill name="'
    names: set[str] = set()
    cursor = 0
    while True:
        start = prompt.find(opening, cursor)
        if start < 0:
            return names
        name_start = start + len(opening)
        name_end = prompt.find('"', name_start)
        if name_end < 0:
            return names
        name = prompt[name_start:name_end].strip()
        if name:
            names.add(name)
        cursor = name_end + 1


def _loaded_tool_result_names(messages: list[Any]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") != "toolResult"
            or message.get("toolName") != "tool_load"
        ):
            continue
        details = message.get("details")
        if not isinstance(details, dict):
            continue
        tool = details.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            names.add(str(tool["name"]))
        tools = details.get("tools")
        if isinstance(tools, list):
            names.update(
                str(item["name"])
                for item in tools
                if isinstance(item, dict)
                and isinstance(item.get("name"), str)
            )
    return names


def _loaded_skill_result_names(messages: list[Any]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") != "toolResult"
            or message.get("toolName") != "skill_load"
        ):
            continue
        details = message.get("details")
        if isinstance(details, dict) and isinstance(details.get("name"), str):
            names.add(str(details["name"]))
    return names


def _room_fact_contents(prompt: str, kind: str) -> list[str]:
    opening = f'<room-fact kind="{kind}">'
    closing = "</room-fact>"
    contents: list[str] = []
    cursor = 0
    while True:
        start = prompt.find(opening, cursor)
        if start < 0:
            return contents
        body_start = start + len(opening)
        end = prompt.find(closing, body_start)
        if end < 0:
            return contents
        contents.append(html.unescape(prompt[body_start:end]).strip())
        cursor = end + len(closing)


def _requirement_projection_evidence(prompt: str) -> dict[str, Any]:
    public_posts = {
        value for value in _room_fact_contents(prompt, "room_post") if value
    }
    dispatch_facts = _room_fact_contents(prompt, "dispatch_state")
    original_count = 0
    duplicate_room_post_count = 0
    duplicate_catalog_statement_count = 0
    catalog_original_reference_count = 0
    invalid_dispatch_fact_count = 0
    forbidden_dispatch_metadata: set[str] = set()
    for raw in dispatch_facts:
        forbidden_dispatch_metadata.update(
            token
            for token in (
                "schemaVersion",
                "catalogRevision",
                "generation",
                "sha256",
                "participantId",
                "dispatchId",
                "taskId",
                "rootId",
            )
            if token in raw
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            human = _human_dispatch_requirement_projection(raw)
            if human is None:
                invalid_dispatch_fact_count += 1
                continue
            original_texts, supplements = human
            original_count += len(original_texts)
            duplicate_room_post_count += len(
                public_posts & original_texts
            )
            duplicate_catalog_statement_count += len(
                original_texts & supplements
            )
            # The human projection renders the original once and deliberately
            # elides its catalog reference instead of exposing statementSource.
            catalog_original_reference_count += len(original_texts)
            continue
        if not isinstance(payload, dict):
            invalid_dispatch_fact_count += 1
            continue
        requirements = payload.get("requirements")
        if not isinstance(requirements, dict):
            invalid_dispatch_fact_count += 1
            continue
        originals = requirements.get("original")
        items = requirements.get("items")
        original_texts = {
            str(item.get("text") or "").strip()
            for item in originals or []
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        }
        original_count += len(original_texts)
        duplicate_room_post_count += len(public_posts & original_texts)
        for item in items or []:
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement") or "").strip()
            if statement and statement in original_texts:
                duplicate_catalog_statement_count += 1
            source = str(item.get("statementSource") or "").strip()
            if source.startswith("original[") and source.endswith("]"):
                catalog_original_reference_count += 1
    return {
        "dispatchFactCount": len(dispatch_facts),
        "invalidDispatchFactCount": invalid_dispatch_fact_count,
        "originalRequirementCount": original_count,
        "duplicateOriginalRoomPostCount": duplicate_room_post_count,
        "duplicateOriginalCatalogStatementCount": (
            duplicate_catalog_statement_count
        ),
        "catalogOriginalReferenceCount": catalog_original_reference_count,
        "forbiddenDispatchMetadata": sorted(
            forbidden_dispatch_metadata
        ),
        "deduplicated": (
            bool(dispatch_facts)
            and original_count > 0
            and invalid_dispatch_fact_count == 0
            and duplicate_room_post_count == 0
            and duplicate_catalog_statement_count == 0
        ),
    }


def _human_dispatch_requirement_projection(
    value: str,
) -> tuple[set[str], set[str]] | None:
    if not value.startswith("## Room 任务"):
        return None
    section_markers = {
        "原始需求（不可改写）：",
        "当前任务：",
        "补充要求：",
        "验收条件 acceptance.criteria（提交时原样使用 criterionId）：",
        "当前阻塞：",
    }
    current = ""
    originals: set[str] = set()
    supplements: set[str] = set()
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line in section_markers:
            current = line
            continue
        if not line.startswith("- "):
            continue
        text = line[2:].strip()
        if current == "原始需求（不可改写）：" and text:
            originals.add(text)
        elif current == "补充要求：" and text:
            supplements.add(text)
    return originals, supplements


def provider_prompt_governance_evidence(
    context: dict[str, Any],
    governed_tool_names: set[str] | None = None,
) -> dict[str, Any]:
    """Return content-free evidence for the managed Room prompt owners."""

    raw_calls = context.get("modelCalls")
    model_calls = raw_calls if isinstance(raw_calls, list) else []
    prompts: list[str] = []
    provider_tool_names: list[set[str]] = []
    provider_messages: list[list[Any]] = []
    for call in model_calls:
        if not isinstance(call, dict):
            continue
        provider_context = call.get("providerContext")
        if not isinstance(provider_context, dict):
            continue
        prompt = provider_context.get("systemPrompt")
        tools = provider_context.get("tools")
        if not isinstance(prompt, str) or not isinstance(tools, list):
            continue
        prompts.append(prompt)
        messages = provider_context.get("messages")
        provider_messages.append(messages if isinstance(messages, list) else [])
        provider_tool_names.append(
            {
                str(tool.get("name"))
                for tool in tools
                if isinstance(tool, dict) and isinstance(tool.get("name"), str)
            }
        )
    conflicting = sorted(
        {
            marker
            for prompt in prompts
            for marker in _CONFLICTING_ROOM_WORKFLOW_TEXT
            if marker in prompt
        }
    )
    skill_catalogs = [
        _routing_catalog_evidence(prompt, _SKILL_CATALOG_TAG)
        for prompt in prompts
    ]
    product_tool_catalogs = [
        _routing_catalog_evidence(prompt, _PRODUCT_TOOL_CATALOG_TAG)
        for prompt in prompts
    ]
    skill_family_block_counts = [
        _tag_block_count(prompt, _SKILL_FAMILY_TAG) for prompt in prompts
    ]
    product_tool_family_block_counts = [
        _tag_block_count(prompt, _PRODUCT_TOOL_FAMILY_TAG)
        for prompt in prompts
    ]
    governed_tool_set = set(governed_tool_names or ())
    loaded_tool_result_names = [
        _loaded_tool_result_names(messages)
        for messages in provider_messages
    ]
    loaded_skill_result_names = [
        _loaded_skill_result_names(messages)
        for messages in provider_messages
    ]
    loaded_skill_names = [
        _loaded_skill_names(prompt)
        | {
            name
            for text in _walk_strings(messages)
            for name in _loaded_skill_names(text)
        }
        for prompt, messages in zip(
            prompts,
            provider_messages,
            strict=True,
        )
    ]
    raw_active_deferred_tool_overlaps = [
        active_names & catalog["names"]
        for active_names, catalog in zip(
            provider_tool_names,
            product_tool_catalogs,
            strict=True,
        )
    ]
    active_deferred_tool_overlaps = [
        raw_overlap - loaded_names - governed_tool_set
        for raw_overlap, loaded_names in zip(
            raw_active_deferred_tool_overlaps,
            loaded_tool_result_names,
            strict=True,
        )
    ]
    historical_activated_tool_cards = [
        raw_overlap & (loaded_names | governed_tool_set)
        for raw_overlap, loaded_names in zip(
            raw_active_deferred_tool_overlaps,
            loaded_tool_result_names,
            strict=True,
        )
    ]
    raw_loaded_deferred_skill_overlaps = [
        loaded_names & catalog["names"]
        for loaded_names, catalog in zip(
            loaded_skill_names,
            skill_catalogs,
            strict=True,
        )
    ]
    loaded_deferred_skill_overlaps = [
        raw_overlap - receipt_names
        for raw_overlap, receipt_names in zip(
            raw_loaded_deferred_skill_overlaps,
            loaded_skill_result_names,
            strict=True,
        )
    ]
    historical_loaded_skill_cards = [
        raw_overlap & receipt_names
        for raw_overlap, receipt_names in zip(
            raw_loaded_deferred_skill_overlaps,
            loaded_skill_result_names,
            strict=True,
        )
    ]
    requirement_projections = [
        _requirement_projection_evidence(prompt) for prompt in prompts
    ]
    first_product_tool_names = (
        product_tool_catalogs[0]["names"] if product_tool_catalogs else set()
    )
    known_product_tool_names = (
        first_product_tool_names
        | governed_tool_set
        | set(_ROOM_BOOTSTRAP_TOOL_NAMES)
    )
    initial_provider_tools = (
        provider_tool_names[0] if provider_tool_names else set()
    )
    initial_product_tools = (
        initial_provider_tools & known_product_tool_names
    )
    first_provider_messages: list[Any] = []
    if model_calls:
        first_provider_context = model_calls[0].get("providerContext")
        if isinstance(first_provider_context, dict):
            candidate_messages = first_provider_context.get("messages")
            if isinstance(candidate_messages, list):
                first_provider_messages = candidate_messages
    loaded_before_first_capture = {
        str(details["tool"]["name"])
        for message in first_provider_messages
        if isinstance(message, dict)
        and message.get("role") == "toolResult"
        and message.get("toolName") == "tool_load"
        and isinstance((details := message.get("details")), dict)
        and details.get("disclosed") is True
        and isinstance(details.get("tool"), dict)
        and isinstance(details["tool"].get("name"), str)
    }
    governed_before_first_capture = (
        governed_tool_set & initial_product_tools
    )
    proven_initial_product_tools = (
        loaded_before_first_capture | governed_before_first_capture
    )
    unprovenanced_initial_product_tools = (
        initial_product_tools - proven_initial_product_tools
    )
    initial_product_schemas_have_load_receipts = (
        not unprovenanced_initial_product_tools
    )
    return {
        "schemaVersion": "wisdom-weasel.provider-prompt-governance-evidence.v1",
        "modelCallCount": len(model_calls),
        "capturedPromptCount": len(prompts),
        "managedRoomAuthorityEveryCall": bool(prompts)
        and all(_MANAGED_ROOM_AUTHORITY in prompt for prompt in prompts),
        "conflictingWorkflowMarkers": conflicting,
        "lifecycleHookBlockCount": sum(
            prompt.count(_LIFECYCLE_HOOK_OPEN) for prompt in prompts
        ),
        "volatileCurrentTimeCount": sum(
            prompt.count("current_time=") for prompt in prompts
        ),
        "projectContextBlockCount": sum(
            prompt.count("<project_context>") for prompt in prompts
        ),
        "roomContextOmissionAuditBlockCount": sum(
            prompt.count("wisdom-weasel.room-context-omission.v1")
            for prompt in prompts
        ),
        "roomFactFramingValidEveryCall": bool(prompts)
        and all(
            prompt.count("<room-fact ") == prompt.count("</room-fact>")
            for prompt in prompts
        ),
        "originalRequirementProjectionDeduplicatedEveryCall": bool(prompts)
        and all(
            item["deduplicated"] for item in requirement_projections
        ),
        "duplicateOriginalRoomPostCount": sum(
            int(item["duplicateOriginalRoomPostCount"])
            for item in requirement_projections
        ),
        "duplicateOriginalCatalogStatementCount": sum(
            int(item["duplicateOriginalCatalogStatementCount"])
            for item in requirement_projections
        ),
        "catalogOriginalReferenceCount": sum(
            int(item["catalogOriginalReferenceCount"])
            for item in requirement_projections
        ),
        "forbiddenDispatchMetadata": sorted(
            {
                token
                for item in requirement_projections
                for token in item["forbiddenDispatchMetadata"]
            }
        ),
        "catalogBlocksExactlyOnceEveryCall": bool(prompts)
        and all(
            skill["blockCount"] == 1 and product_tool["blockCount"] == 1
            for skill, product_tool in zip(
                skill_catalogs,
                product_tool_catalogs,
                strict=True,
            )
        ),
        "routingCardFieldContractEveryCall": bool(prompts)
        and all(
            skill["invalidCardCount"] == 0
            and product_tool["invalidCardCount"] == 0
            and skill["cardCount"] <= _MAX_STAGE_CARD_COUNT
            and product_tool["cardCount"] <= _MAX_STAGE_CARD_COUNT
            for skill, product_tool in zip(
                skill_catalogs,
                product_tool_catalogs,
                strict=True,
            )
        ),
        "capabilityFamilyIndexesExactlyOnceEveryCall": bool(prompts)
        and all(
            skill_count == 1 and tool_count == 1
            for skill_count, tool_count in zip(
                skill_family_block_counts,
                product_tool_family_block_counts,
                strict=True,
            )
        ),
        "stageCardsBoundedEveryCall": bool(prompts)
        and all(
            skill["cardCount"] <= _MAX_STAGE_CARD_COUNT
            and product_tool["cardCount"] <= _MAX_STAGE_CARD_COUNT
            for skill, product_tool in zip(
                skill_catalogs,
                product_tool_catalogs,
                strict=True,
            )
        ),
        "activeDeferredMutuallyExclusiveEveryCall": bool(prompts)
        and all(not names for names in active_deferred_tool_overlaps)
        and all(not names for names in loaded_deferred_skill_overlaps),
        "activeDeferredToolOverlapNames": sorted(
            {
                name
                for names in active_deferred_tool_overlaps
                for name in names
            }
        ),
        "loadedDeferredSkillOverlapNames": sorted(
            {
                name
                for names in loaded_deferred_skill_overlaps
                for name in names
            }
        ),
        "historicalActivatedToolCardNames": sorted(
            {
                name
                for names in historical_activated_tool_cards
                for name in names
            }
        ),
        "historicalLoadedSkillCardNames": sorted(
            {
                name
                for names in historical_loaded_skill_cards
                for name in names
            }
        ),
        "routingCardContentCompleteEveryCall": bool(prompts)
        and all(
            skill["truncatedValueCount"] == 0
            and product_tool["truncatedValueCount"] == 0
            for skill, product_tool in zip(
                skill_catalogs,
                product_tool_catalogs,
                strict=True,
            )
        ),
        "skillRoutingCardCount": sum(
            int(catalog["cardCount"]) for catalog in skill_catalogs
        ),
        "productToolRoutingCardCount": sum(
            int(catalog["cardCount"]) for catalog in product_tool_catalogs
        ),
        "invalidRoutingCardCount": sum(
            int(catalog["invalidCardCount"])
            for catalog in (*skill_catalogs, *product_tool_catalogs)
        ),
        "truncatedRoutingCardValueCount": sum(
            int(catalog["truncatedValueCount"])
            for catalog in (*skill_catalogs, *product_tool_catalogs)
        ),
        "initialProductSchemaCount": len(
            initial_product_tools
        ),
        "initialProductSchemaNames": sorted(initial_product_tools),
        "stableRoomBootstrapSchemasExact": (
            initial_product_tools == _ROOM_BOOTSTRAP_TOOL_NAMES
        ),
        "initialProductSchemasDeferred": bool(prompts)
        and not (
            initial_product_tools - set(_ROOM_BOOTSTRAP_TOOL_NAMES)
        ),
        "loadedProductSchemasBeforeFirstCapture": sorted(
            loaded_before_first_capture & initial_product_tools
        ),
        "governedProductSchemasBeforeFirstCapture": sorted(
            governed_before_first_capture
        ),
        "unprovenancedInitialProductSchemaNames": sorted(
            unprovenanced_initial_product_tools
        ),
        "initialProductSchemasHaveLoadReceipts": bool(prompts)
        and bool(first_product_tool_names)
        and initial_product_schemas_have_load_receipts,
        "progressiveProductSchemasValid": bool(prompts)
        and bool(first_product_tool_names)
        and initial_product_schemas_have_load_receipts
        and not unprovenanced_initial_product_tools,
    }


def progressive_discovery_check(
    prompt_evidence: list[dict[str, Any]],
    recovered_tool_names: list[set[str]] | None = None,
) -> bool:
    """Verify visible schemas have a model load or exact governed recovery."""

    if not prompt_evidence:
        return False
    recovered = recovered_tool_names or [set() for _ in prompt_evidence]
    if len(recovered) != len(prompt_evidence):
        return False
    # Native approvals may suspend and resume the same Session in a new Pi
    # process. The first captured call of that process can therefore already
    # contain schemas disclosed before suspension. Managed Room bootstrap tools
    # are also disclosed before the first model call. Provenance, not capture
    # timing, is the invariant: every visible product schema must be backed by
    # an earlier model-visible tool_load or an exact governed load receipt.
    return all(
        set(item.get("initialProductSchemaNames") or [])
        <= (
            set(item.get("loadedProductSchemasBeforeFirstCapture") or [])
            | set(item.get("governedProductSchemasBeforeFirstCapture") or [])
            | recovered[index]
        )
        and item.get("catalogBlocksExactlyOnceEveryCall") is True
        and item.get("routingCardFieldContractEveryCall") is True
        and (
            item.get("managedRoomAuthorityEveryCall") is not True
            or (
                item.get(
                    "capabilityFamilyIndexesExactlyOnceEveryCall"
                )
                is True
                and item.get("stageCardsBoundedEveryCall") is True
                and item.get(
                    "activeDeferredMutuallyExclusiveEveryCall"
                )
                is True
            )
        )
        and item.get("routingCardContentCompleteEveryCall") is True
        and item.get("invalidRoutingCardCount") == 0
        and item.get("truncatedRoutingCardValueCount") == 0
        for index, item in enumerate(prompt_evidence)
    )


def debug_evidence(
    base_url: str,
    session_id: str,
    *,
    requester: JsonRequester = request_json,
    timeout: float = 15,
    text_markers: Mapping[str, str] | None = None,
    turn_id: str = "",
    governed_tool_receipts: list[Mapping[str, object]] | None = None,
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
    context = debug.get("context") or {}
    current_provider_context = debug.get("currentProviderContext") or {}
    projection = context.get("contextProjection") or {}
    journal = (
        projection.get("providerContextJournal")
        if isinstance(
            projection.get("providerContextJournal"),
            dict,
        )
        else current_provider_context.get(
            "providerContextJournal"
        )
    ) or {}
    cache_reads = [
        int((call.get("usage") or {}).get("cacheRead") or 0)
        for call in context.get("providerRequestReceipts", [])
        if isinstance(call, dict)
    ]
    provider_usage_reported = any(
        sum(
            int(usage.get(key) or 0)
            for key in (
                "input",
                "output",
                "cacheRead",
                "cacheWrite",
                "totalTokens",
            )
        )
        > 0
        for call in context.get("providerRequestReceipts", [])
        if isinstance(call, dict)
        for usage in [call.get("usage")]
        if isinstance(usage, dict)
    )
    tool_names = [
        str(item.get("toolName") or item.get("name") or "")
        for item in context.get("toolExecutions", [])
        if isinstance(item, dict)
    ]
    memory_blocks = _provider_session_memory_blocks(
        context.get("providerRequests") or []
    )
    memory_blocks.extend(
        _session_memory_blocks(
            [
                call.get("providerContext")
                for call in context.get("modelCalls") or []
                if isinstance(call, dict)
            ]
        )
    )
    memory_blocks = list(dict.fromkeys(memory_blocks))
    snapshot = requester(
        base_url,
        "GET",
        f"/api/agent/sessions/{encoded(session_id)}/messages",
        timeout=timeout,
    )
    message_queue = snapshot.get("messageQueue") or {}
    transcript = debug.get("transcript") or {}
    first_model_capture_ms = min(
        (
            int(call.get("capturedAtMs") or 0)
            for call in context.get("modelCalls", [])
            if isinstance(call, Mapping)
            and int(call.get("capturedAtMs") or 0) > 0
        ),
        default=0,
    )
    governed_tool_names = {
        str(item.get("toolName") or "")
        for item in governed_tool_receipts or []
        if str(item.get("toolName") or "").strip()
        and first_model_capture_ms > 0
        and int(item.get("createdAtMs") or 0) <= first_model_capture_ms
    }
    return {
        "turnId": debug.get("turnId"),
        "currentProviderContext": current_provider_context,
        "recoveryPacket": _recovery_packet_evidence(current_provider_context),
        "journal": {
            "epoch": journal.get("epoch"),
            "reason": journal.get("epochReason"),
            "entryCount": journal.get("entryCount"),
            "hashes": journal.get("contentHashes") or [],
        },
        "cacheReads": cache_reads,
        "positiveCacheRead": any(value > 0 for value in cache_reads),
        "providerUsageReported": provider_usage_reported,
        "modelCallCount": len(context.get("modelCalls", [])),
        "providerPrefix": provider_prefix_evidence(context),
        "providerRoomPostVisibility": provider_room_post_visibility(
            context,
            text_markers,
        ),
        "promptGovernance": provider_prompt_governance_evidence(
            context,
            governed_tool_names,
        ),
        "toolNames": tool_names,
        "roomCommitCalls": sum(name == "room_commit" for name in tool_names),
        "pendingContinuations": len(message_queue.get("steering") or [])
        + len(message_queue.get("followUp") or []),
        "sessionMemory": {
            "blockCount": len(memory_blocks),
            "nonEmptyBlockCount": sum(
                "## Session 记忆" in block for block in memory_blocks
            ),
            "blockSha256s": [
                hashlib.sha256(block.encode("utf-8")).hexdigest()
                for block in memory_blocks
            ],
            "blocks": memory_blocks,
            "forbiddenMetadata": sorted(
                {
                    token
                    for block in memory_blocks
                    for token in _FORBIDDEN_MEMORY_METADATA
                    if token in block
                }
            ),
            "assistantConversationBlockCount": sum(
                "## 最近对话" in block or "**Agent**" in block
                for block in memory_blocks
            ),
        },
        "transcript": {
            "sha256": transcript.get("sha256"),
            "bytes": transcript.get("bytes"),
            "lineCount": transcript.get("lineCount"),
            "contentIncluded": transcript.get("contentIncluded"),
        },
    }


def _recovery_packet_evidence(
    current_provider_context: object,
) -> dict[str, Any]:
    current = (
        current_provider_context
        if isinstance(current_provider_context, dict)
        else {}
    )
    prompt = str(current.get("systemPrompt") or "")
    opening = '<rag-ime-context type="room_context">'
    closing = "</rag-ime-context>"
    if prompt.count(opening) != 1 or prompt.count(closing) < 1:
        return {"valid": False, "roomContextCount": prompt.count(opening)}
    start = prompt.index(opening) + len(opening)
    end = prompt.find(closing, start)
    if end < 0:
        return {"valid": False, "roomContextCount": 1}
    try:
        packet = json.loads(prompt[start:end].strip())
    except json.JSONDecodeError:
        return {"valid": False, "roomContextCount": 1}
    if not isinstance(packet, dict):
        return {"valid": False, "roomContextCount": 1}
    acceptance = [
        item for item in packet.get("acceptance") or []
        if isinstance(item, dict)
    ]
    tools = packet.get("toolReceipt")
    tool_items = [
        item for item in tools.get("items") or []
        if isinstance(item, dict)
    ] if isinstance(tools, dict) else []
    skill = packet.get("skillReceipt")
    task = packet.get("currentTask")
    handoff = packet.get("handoff")
    return {
        "valid": True,
        "roomContextCount": 1,
        "originalRequirementCount": len(
            packet.get("originalRequirements") or []
        ),
        "acceptanceCount": len(acceptance),
        "acceptancePassedCount": sum(
            item.get("passed") is True for item in acceptance
        ),
        "acceptanceCoveredCount": sum(
            item.get("covered") is True for item in acceptance
        ),
        "acceptanceProofVerifiedCount": sum(
            item.get("proofVerified") is True for item in acceptance
        ),
        "blockerCount": len(packet.get("blockers") or []),
        "taskState": str(task.get("state") or "")
        if isinstance(task, dict)
        else "",
        "handoffIntent": str(handoff.get("intentKind") or "")
        if isinstance(handoff, dict)
        else "",
        "skillReceiptId": str(skill.get("restoredFromReceiptId") or "")
        if isinstance(skill, dict)
        else "",
        "toolReceiptNames": sorted(
            str(item.get("name") or "")
            for item in tool_items
            if str(item.get("name") or "").strip()
        ),
        "toolReceiptIds": sorted(
            str(item.get("receiptId") or "")
            for item in tool_items
            if str(item.get("receiptId") or "").strip()
        ),
    }


def _provider_session_memory_blocks(
    provider_requests: list[object],
) -> list[str]:
    payloads: list[object] = []
    for request in provider_requests:
        if not isinstance(request, dict):
            continue
        payload = request.get("payload")
        if not isinstance(payload, dict):
            continue
        payloads.append(payload.get("input"))
    return _session_memory_blocks(payloads)


def _session_memory_blocks(values: list[object]) -> list[str]:
    blocks: list[str] = []
    for value in values:
        for content in _walk_strings(value):
            cursor = 0
            while True:
                start = content.find(_SESSION_MEMORY_OPEN, cursor)
                if start < 0:
                    break
                body_start = start + len(_SESSION_MEMORY_OPEN)
                end = content.find(_SESSION_MEMORY_CLOSE, body_start)
                if end < 0:
                    break
                blocks.append(content[body_start:end].strip())
                cursor = end + len(_SESSION_MEMORY_CLOSE)
    return blocks


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _walk_strings(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _walk_strings(item)]
    return []


def transcript_evidence(
    session_dir: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    transcript_path = _find_transcript(session_dir, expected_sha256)
    user_messages: list[str] = []
    compactions: list[dict[str, Any]] = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if isinstance(entry, dict) and entry.get("type") == "compaction":
            compactions.append(entry)
            continue
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        user_messages.extend(_walk_strings(message.get("content")))
    forbidden_envelopes = (
        "<room-turn-context",
        "<room-projection",
        "wisdom-weasel.room-task-context.v1",
    )
    return {
        "sha256": expected_sha256,
        "userMessageCount": len(user_messages),
        "privateTriggerCount": sum(
            message.startswith("执行当前受管 Room 任务") for message in user_messages
        ),
        "repairContinuationCount": sum(
            message.startswith(
                (
                    '<managed-task-follow-up origin="room-kernel" kind="repair_commit">',
                    "收工检查未通过：",
                )
            )
            for message in user_messages
        ),
        "roomEnvelopeCount": sum(
            token in message
            for message in user_messages
            for token in forbidden_envelopes
        ),
        "publicCanaryPostCount": sum("CANARY-" in message for message in user_messages),
        "compactionCount": len(compactions),
        "extensionCompactionCount": sum(
            entry.get("fromHook") is True for entry in compactions
        ),
        "roomRecoveryPointerCount": sum(
            'type="room_context"' in str(entry.get("summary") or "")
            for entry in compactions
        ),
        "compactionTaskFactLeakCount": sum(
            any(
                token in str(entry.get("summary") or "")
                for token in (
                    "CANARY-",
                    "Original Request",
                    "原始需求：",
                    "当前任务：",
                    "criterionId",
                    "workspace_read",
                )
            )
            for entry in compactions
        ),
    }


def _find_transcript(session_dir: Path, expected_sha256: str) -> Path:
    for path in sorted(session_dir.glob("*.jsonl")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == expected_sha256:
            return path
    raise RuntimeError(
        f"No Pi transcript under {session_dir} matches sha256 {expected_sha256}"
    )


def latest_transition(db_path: Path, session_id: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT source_ref, from_epoch, to_epoch, epoch_reason, evidence_json
            FROM room_v2_session_context_epoch_transitions
            WHERE session_id = ?
            ORDER BY created_at_ms DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if row is not None:
            evidence = json.loads(row[4])
            receipt_ids = [
                str(value)
                for value in evidence.get("toolReceiptIds") or []
                if str(value).strip()
            ]
            if receipt_ids:
                placeholders = ",".join("?" for _ in receipt_ids)
                tool_rows = connection.execute(
                    f"""SELECT receipt_id, tool_name
                        FROM room_v2_tool_disclosure_receipts
                        WHERE receipt_id IN ({placeholders})""",
                    receipt_ids,
                ).fetchall()
            else:
                tool_rows = []
    if row is None:
        raise RuntimeError(f"No Product context transition for {session_id}")
    evidence = json.loads(row[4])
    hashes = [
        str(value)
        for value in (
            evidence.get("roomProviderEntryHash"),
            evidence.get("sessionProviderEntryHash"),
        )
        if str(value or "").strip()
    ]
    return {
        "source": row[0],
        "from": row[1],
        "to": row[2],
        "reason": row[3],
        "recovery": {
            "originalRequirements": evidence.get("originalRequirementCount"),
            "currentTask": evidence.get("currentTaskPresent"),
            "acceptance": evidence.get("acceptanceCount"),
            "blockers": evidence.get("blockerCount"),
            "handoff": evidence.get("handoffPresent"),
            "skillReceiptId": str(evidence.get("skillReceiptId") or ""),
            "toolReceiptIds": [
                str(value)
                for value in evidence.get("toolReceiptIds") or []
                if str(value).strip()
            ],
            "toolReceiptNames": sorted(
                {str(value[1]) for value in tool_rows if str(value[1]).strip()}
            ),
            "providerHashes": hashes,
        },
    }


def tool_receipt_evidence(
    db_path: Path,
    *,
    session_id: str,
    dispatch_ids: list[str],
    tool_name: str,
) -> dict[str, Any]:
    identifiers = [str(value) for value in dispatch_ids if str(value).strip()]
    if not identifiers:
        raise RuntimeError("Room Tool receipt audit requires a Dispatch id")
    placeholders = ",".join("?" for _ in identifiers)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT invocation.receipt_id, invocation.load_receipt_id,
                   disclosure.schema_hash, execution.execution_receipt_id,
                   execution.status, execution.result_hash
            FROM room_v2_tool_invocation_receipts invocation
            JOIN room_v2_capability_manifests manifest
              ON manifest.manifest_id = invocation.manifest_id
             AND manifest.manifest_hash = invocation.manifest_hash
            JOIN room_v2_capability_runtime_bindings binding
              ON binding.manifest_id = manifest.manifest_id
             AND binding.session_id = ?
            JOIN room_v2_tool_disclosure_receipts disclosure
              ON disclosure.receipt_id = invocation.load_receipt_id
             AND disclosure.receipt_kind = 'load'
             AND disclosure.tool_name = invocation.canonical_tool_name
            LEFT JOIN room_v2_tool_execution_receipts execution
              ON execution.invocation_receipt_id = invocation.receipt_id
            WHERE manifest.dispatch_id IN ({placeholders})
              AND invocation.canonical_tool_name = ?
            ORDER BY invocation.created_at_ms, invocation.receipt_id
            """,
            (session_id, *identifiers, tool_name),
        ).fetchall()
    items = [
        {
            "invocationReceiptId": str(row[0]),
            "loadReceiptId": str(row[1]),
            "schemaHash": str(row[2]),
            "executionReceiptId": str(row[3] or ""),
            "status": str(row[4] or ""),
            "resultHash": str(row[5] or ""),
        }
        for row in rows
    ]
    return {
        "toolName": tool_name,
        "loadReceiptIds": sorted({item["loadReceiptId"] for item in items}),
        "invocationCount": len(items),
        "appliedExecutionCount": sum(
            item["status"] == "applied" and len(item["resultHash"]) == 64
            for item in items
        ),
        "items": items,
    }


def run(
    args: argparse.Namespace,
    *,
    requester: JsonRequester = request_json,
) -> dict[str, Any]:
    stamp = int(time.time() * 1000)
    epoch_count = int(getattr(args, "epochs", 3) or 3)
    if not 1 <= epoch_count <= 3:
        raise RuntimeError("Room context epoch canary supports one to three tasks")
    workspace = args.workspace.expanduser().resolve(strict=True)
    workload_files = resolve_workload_files(
        workspace,
        list(args.workload_file or []),
    )
    workload_metadata = [
        {
            "path": str(path.relative_to(workspace)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in workload_files
    ]
    participant_roles = list(
        getattr(args, "participant_roles", None)
        or (
            {"roleId": "companion-future-v1", "roleVersion": "1"},
            {"roleId": "companion-present-v1", "roleVersion": "1"},
        )
    )
    if len(participant_roles) != 2 or not all(
        isinstance(item, dict)
        and str(item.get("roleId") or "").strip()
        and str(item.get("roleVersion") or "").strip()
        for item in participant_roles
    ):
        raise RuntimeError("Room context epoch canary requires exactly two role references")
    created = requester(
        args.base_url,
        "POST",
        "/api/agent/rooms",
        {
            "title": f"Context epoch canary {stamp}",
            "routingPolicy": "manual_mentions",
            "workspaceRoots": [str(workspace)],
            "participants": participant_roles,
        },
    )
    room = created["room"]
    target = room["participants"][1]
    room_id = str(room["id"])
    session_id = str(target["sessionId"])
    model_provider = str(getattr(args, "model_provider", "") or "")
    model_id = str(getattr(args, "model_id", "") or "")
    if model_provider and model_id:
        requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/model",
            {"provider": model_provider, "modelId": model_id},
        )
    thinking_level = str(getattr(args, "thinking_level", "") or "").strip()
    if thinking_level:
        requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/thinking",
            {"level": thinking_level},
        )

    epochs: list[dict[str, Any]] = []
    for index in range(1, epoch_count + 1):
        work = requester(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/work-items",
            {
                "currentOwnerParticipantId": target["id"],
                "createdByParticipantId": room["participants"][0]["id"],
                "clientMessageId": f"epoch-canary-work-{stamp}-{index}",
                "objective": (
                    f"完成第 {index} 个独立压缩任务：精确加载 workspace_read，"
                    "读取两份真实源码后提交有界结果"
                ),
                "expectedOutput": (
                    f"恰好读取两份指定文件，只公开 CANARY-{index}-OK，"
                    "不复制文件内容，然后提交责任并结束本轮"
                ),
                "acceptanceCriteria": [
                    "只精确加载一次 workspace_read，并分别读取两份指定文件，limit 均为 65536",
                    f"公开回复只包含 CANARY-{index}-OK 和简短读取完成说明，不复制源码",
                    "责任提交覆盖全部验收条件，通过收工检查后结束模型回合",
                ],
                "state": "active",
            },
        )["workItem"]
        accepted = requester(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/messages",
            {
                "message": (
                    f"@{target['displayName']} 执行当前结构化任务。先精确加载 workspace_read；"
                    f"只调用两次，分别读取 {workload_files[0]} 和 {workload_files[1]}，"
                    "两次 limit 都设为 65536。不要公开复制源码，也不要调用 room_state。"
                    f"完成后只发布 CANARY-{index}-OK 和一句读取完成说明并提交责任；"
                    "若收工检查要求修复，只修复一次。"
                ),
                "clientMessageId": f"epoch-canary-message-{stamp}-{index}",
                "workItemId": work["id"],
            },
        )
        root_id = accepted_root_id(accepted)
        try:
            settled = wait_for_terminal_dispatch(
                args.base_url,
                room_id,
                root_id,
                timeout=args.turn_timeout,
                requester=requester,
            )
        except BaseException as failure:
            cancel_root_after_failure(
                args.base_url,
                room_id,
                root_id,
                failure,
                requester=requester,
            )
            raise
        finalized = requester(
            args.base_url,
            "POST",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/finalize",
            {"rootId": root_id},
            timeout=args.turn_timeout,
        )
        terminal_receipt = finalized.get("receipt")
        if (
            not isinstance(terminal_receipt, dict)
            or terminal_receipt.get("receiptKind") != "terminal"
            or terminal_receipt.get("status") != "applied"
            or not isinstance(terminal_receipt.get("details"), dict)
            or terminal_receipt["details"].get("acceptanceSatisfied") is not True
        ):
            raise RuntimeError(
                f"Room Root {root_id} did not finalize canonically: {finalized}"
            )
        terminal_snapshot = requester(
            args.base_url,
            "GET",
            f"/api/agent/rooms/{encoded(room_id)}/kernel/snapshot",
            timeout=args.turn_timeout,
        )
        terminal_roots = [
            item
            for item in terminal_snapshot.get("roots") or []
            if isinstance(item, dict) and item.get("rootId") == root_id
        ]
        if (
            len(terminal_roots) != 1
            or terminal_roots[0].get("state") != "completed"
            or not terminal_roots[0].get("terminalReceiptId")
        ):
            raise RuntimeError(
                f"Room Root {root_id} has no durable completed state"
            )
        workload_receipts = tool_receipt_evidence(
            args.db_path,
            session_id=session_id,
            dispatch_ids=[str(value) for value in settled["dispatchIds"]],
            tool_name="workspace_read",
        )
        before = debug_evidence(
            args.base_url,
            session_id,
            requester=requester,
            timeout=args.turn_timeout,
        )
        compacted = requester(
            args.base_url,
            "POST",
            f"/api/agent/sessions/{encoded(session_id)}/compact",
            {"instructions": f"Epoch canary {index}: preserve only the bounded recovery packet."},
            timeout=args.turn_timeout,
        )
        compact_result = compacted.get("result") or {}
        after = debug_evidence(
            args.base_url,
            session_id,
            requester=requester,
            timeout=args.turn_timeout,
        )
        transition = latest_transition(args.db_path, session_id)
        transition_hashes = transition["recovery"]["providerHashes"]
        journal_hashes = after["journal"]["hashes"]
        epochs.append(
            {
                "index": index,
                "rootId": root_id,
                "dispatch": settled,
                "terminal": {
                    "receiptId": terminal_receipt.get("receiptId"),
                    "status": terminal_receipt.get("status"),
                    "acceptanceSatisfied": terminal_receipt["details"].get(
                        "acceptanceSatisfied"
                    ),
                    "rootState": terminal_roots[0].get("state"),
                    "terminalReceiptId": terminal_roots[0].get(
                        "terminalReceiptId"
                    ),
                },
                "workspaceRead": workload_receipts,
                "beforeCompaction": before,
                "compaction": {
                    "entryId": compact_result.get("compactionEntryId"),
                    "epochBefore": compact_result.get("contextEpochBefore"),
                    "epochAfter": compact_result.get("contextEpochAfter"),
                    "refreshApplied": compact_result.get("contextRefreshApplied"),
                },
                "afterCompaction": after,
                "productTransition": transition,
                "hashesMatch": transition_hashes == journal_hashes,
            }
        )

    final_transcript = None
    if args.pi_session_dir is not None:
        expected_transcript_sha = str(
            epochs[-1]["afterCompaction"]["transcript"]["sha256"] or ""
        )
        if not expected_transcript_sha:
            raise RuntimeError("Pi debug context did not expose a transcript receipt")
        final_transcript = transcript_evidence(
            args.pi_session_dir,
            expected_transcript_sha,
        )

    expected_after = [index * 2 for index in range(1, epoch_count + 1)]
    actual_after = [item["afterCompaction"]["journal"]["epoch"] for item in epochs]
    checks = {
        "epochSequence": actual_after == expected_after,
        "allHashesMatch": all(item["hashesMatch"] for item in epochs),
        "oneRecoveryPacketPerEpoch": all(
            item["afterCompaction"]["journal"]["entryCount"] == 2 for item in epochs
        ),
        "allCompactionsApplied": all(
            item["compaction"]["refreshApplied"] is True for item in epochs
        ),
        "allRootsCanonicallyFinalized": all(
            item["terminal"]["status"] == "applied"
            and item["terminal"]["acceptanceSatisfied"] is True
            and item["terminal"]["rootState"] == "completed"
            and item["terminal"]["receiptId"]
            == item["terminal"]["terminalReceiptId"]
            for item in epochs
        ),
        "completedAcceptanceRecovered": all(
            item["afterCompaction"]["recoveryPacket"]["valid"] is True
            and item["afterCompaction"]["recoveryPacket"][
                "originalRequirementCount"
            ]
            == 1
            and item["afterCompaction"]["recoveryPacket"][
                "acceptanceCount"
            ]
            == item["afterCompaction"]["recoveryPacket"][
                "acceptancePassedCount"
            ]
            == item["afterCompaction"]["recoveryPacket"][
                "acceptanceCoveredCount"
            ]
            and item["afterCompaction"]["recoveryPacket"]["taskState"]
            == "completed"
            and item["afterCompaction"]["recoveryPacket"][
                "handoffIntent"
            ]
            == "complete"
            for item in epochs
        ),
        "boundedRoomCommitCalls": all(
            1 <= item["beforeCompaction"]["roomCommitCalls"] <= 2 for item in epochs
        ),
        "workspaceReadWorkloadExact": all(
            item["workspaceRead"]["invocationCount"] == 2
            and item["workspaceRead"]["appliedExecutionCount"] == 2
            and len(item["workspaceRead"]["loadReceiptIds"]) == 1
            for item in epochs
        ),
        "workspaceReadReceiptsRecovered": all(
            set(item["workspaceRead"]["loadReceiptIds"])
            <= set(item["productTransition"]["recovery"]["toolReceiptIds"])
            for item in epochs
        ),
        "exactSkillReceiptRecovered": all(
            bool(item["productTransition"]["recovery"]["skillReceiptId"])
            for item in epochs
        ),
        "settlementQueuesDrained": all(
            item["beforeCompaction"]["pendingContinuations"] == 0 for item in epochs
        ),
        "roomMemoryIsBounded": all(
            item["beforeCompaction"]["sessionMemory"]["blockCount"] > 0
            and not item["beforeCompaction"]["sessionMemory"]["forbiddenMetadata"]
            and item["beforeCompaction"]["sessionMemory"][
                "assistantConversationBlockCount"
            ]
            == 0
            for item in epochs
        ),
        "providerPrefixesStableWithinEpoch": all(
            item["beforeCompaction"]["providerPrefix"]["passed"] for item in epochs
        ),
        "managedRoomWorkflowAuthorityClear": all(
            item["beforeCompaction"]["promptGovernance"][
                "managedRoomAuthorityEveryCall"
            ]
            and not item["beforeCompaction"]["promptGovernance"][
                "conflictingWorkflowMarkers"
            ]
            for item in epochs
        ),
        "singleManagedRoomRecoveryOwner": all(
            item["beforeCompaction"]["promptGovernance"][
                "lifecycleHookBlockCount"
            ]
            == 0
            for item in epochs
        ),
        "cacheStableManagedPromptControls": all(
            item["beforeCompaction"]["promptGovernance"][
                "volatileCurrentTimeCount"
            ]
            == 0
            for item in epochs
        ),
        "agentMdDefaultOff": all(
            item["beforeCompaction"]["promptGovernance"][
                "projectContextBlockCount"
            ]
            == 0
            for item in epochs
        ),
        "roomContextProjectionIsDeduplicated": all(
            item["beforeCompaction"]["promptGovernance"][
                "originalRequirementProjectionDeduplicatedEveryCall"
            ]
            and item["beforeCompaction"]["promptGovernance"][
                "roomContextOmissionAuditBlockCount"
            ]
            == 0
            and item["beforeCompaction"]["promptGovernance"][
                "roomFactFramingValidEveryCall"
            ]
            and not item["beforeCompaction"]["promptGovernance"][
                "forbiddenDispatchMetadata"
            ]
            for item in epochs
        ),
        "skillToolDiscoveryIsProgressive": progressive_discovery_check(
            [
                item["beforeCompaction"]["promptGovernance"]
                for item in epochs
            ],
            [
                set()
                if index == 0
                else set(
                    epochs[index - 1]["productTransition"]["recovery"].get(
                        "toolReceiptNames", []
                    )
                )
                for index in range(len(epochs))
            ],
        ),
    }
    if bool(getattr(args, "require_cache_evidence", True)):
        checks["realProviderKvCacheObserved"] = any(
            item["beforeCompaction"]["positiveCacheRead"] for item in epochs
        )
    else:
        checks["deterministicCacheEvidenceNotClaimed"] = all(
            not item["beforeCompaction"]["positiveCacheRead"] for item in epochs
        )
    if final_transcript is not None:
        checks["roomContextAbsentFromSessionTranscript"] = (
            final_transcript["roomEnvelopeCount"] == 0
            and final_transcript["publicCanaryPostCount"] == 0
            and final_transcript["privateTriggerCount"] == epoch_count
        )
        checks["piCompactionStoresOnlyRoomRecoveryPointer"] = (
            final_transcript["compactionCount"] == epoch_count
            and final_transcript["extensionCompactionCount"] == epoch_count
            and final_transcript["roomRecoveryPointerCount"] == epoch_count
            and final_transcript["compactionTaskFactLeakCount"] == 0
        )

    return {
        "schemaVersion": "wisdom-weasel.room-context-epoch-canary.v1",
        "roomId": room_id,
        "sessionId": session_id,
        "workloadFiles": workload_metadata,
        "epochs": epochs,
        "transcript": final_transcript,
        "observations": {
            "expectedAfterCompaction": expected_after,
            "actualAfterCompaction": actual_after,
        },
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18768")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--workload-file",
        type=Path,
        action="append",
        help="Relative or absolute workspace file; pass exactly twice",
    )
    parser.add_argument("--pi-session-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--turn-timeout", type=float, default=240)
    parser.add_argument("--epochs", type=int, choices=(1, 2, 3), default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run(args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"ok": all(report["checks"].values()), "output": str(args.output), "checks": report["checks"]}, ensure_ascii=False, indent=2))
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
