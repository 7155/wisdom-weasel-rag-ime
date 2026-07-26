"""Pi message shaping and public projection shared by both protocols.

The second tranche out of `pi_runtime`'s privates. `pi_runtime_v2` imported
these from v1, which made v1 the owner of logic that describes the Pi wire
format and what may be shown publicly -- concerns neither protocol version
owns alone.

Everything here is a pure function of its arguments: message identity and
visibility, assistant preview and error extraction, redaction, and the public
projections for usage, models, retry status, fork candidates, tool activity
and confirmation values. Names and bodies are unchanged, so Provider payloads,
event ordering and abort behaviour are untouched.

`_pi_message_payload` and the media URL builder it uses now live here too, so
`pi_runtime_v2` imports no private name from `pi_runtime` at all.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from .agent_blocks import (
    extract_completed_agent_blocks,
    normalize_trusted_agent_blocks,
)
from .agent_protocol import AgentBlock, AgentMessage, normalize_agent_block

from .pi_runtime_values import (
    PiRuntimeError,
    _integer,
    _mapping,
    _redact_runtime_text,
)


_APPROVAL_TITLE_PREFIX = "RAG-IME-APPROVAL:"


_REVIEW_TITLE_PREFIX = "RAG-IME-REVIEW:"


def _visible_message_text(role: str, text: str) -> str:
    if role != "user":
        return text
    tagged = re.search(
        r"<(?:agent|rag-ime)-user-query>\s*(.*?)\s*</(?:agent|rag-ime)-user-query>",
        text,
        flags=re.DOTALL,
    )
    if tagged:
        return tagged.group(1).strip()
    legacy_prefix = "请在当前连续会话中处理这个输入法深度查找任务。"
    marker = "\n用户问题：\n"
    if text.startswith(legacy_prefix) and marker in text:
        question = text.split(marker, 1)[1].split("\n\n本地时间：", 1)[0].strip()
        if question:
            return question
    return text


def _public_file_name(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    file_name = normalized.rsplit("/", 1)[-1].strip()
    if not file_name or len(file_name) > 240 or any(ord(character) < 32 for character in file_name):
        return ""
    if re.search(r"token|secret|password|api.?key|authorization|cookie", file_name, re.IGNORECASE):
        return ""
    return file_name


def _supported_thinking_levels(raw: Mapping[str, object]) -> list[str]:
    if not bool(raw.get("reasoning")):
        return ["off"]
    explicit = raw.get("thinkingLevels")
    if isinstance(explicit, list):
        allowed = {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
        levels = [str(level) for level in explicit if str(level) in allowed]
        return list(dict.fromkeys(levels)) or ["off"]
    mapping = _mapping(raw.get("thinkingLevelMap"))
    levels: list[str] = []
    for level in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
        mapped = mapping.get(level)
        if mapped is None and level in mapping:
            continue
        if level in {"xhigh", "max"} and level not in mapping:
            continue
        levels.append(level)
    return levels or ["off"]


def _safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_runtime_text(str(value))[:2000]


def _last_assistant_error(messages: list[object]) -> str:
    for item in reversed(messages):
        message = _mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        if str(message.get("stopReason") or "").lower() != "error" and not message.get("errorMessage"):
            return ""
        return _redact_runtime_text(str(message.get("errorMessage") or "模型请求失败，请重试"))
    return ""


def _last_assistant_preview(messages: list[object]) -> str:
    for item in reversed(messages):
        message = _mapping(item)
        if str(message.get("role") or "") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return " ".join(content.split())[:240]
        if isinstance(content, list):
            text = " ".join(
                str(_mapping(block).get("text") or "")
                for block in content
                if str(_mapping(block).get("type") or "") == "text"
            )
            return " ".join(text.split())[:240]
    return ""


def _pi_message_id(raw: Mapping[str, object], turn_id: str) -> str:
    value = str(raw.get("id") or "").strip()
    if value:
        return value
    timestamp = _integer(raw.get("timestamp"))
    role = str(raw.get("role") or "assistant").lower()
    if timestamp:
        return f"pi:message:{role}:{timestamp}"
    serialized = json.dumps(raw.get("content"), ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]
    return f"pi:message:{role}:{digest}"


def _pi_message_is_public(raw: Mapping[str, object]) -> bool:
    """Keep Pi's loop protocol out of the human conversation transcript."""

    role = str(raw.get("role") or "assistant").lower()
    if role == "user":
        return True
    if role != "assistant":
        return False
    content = raw.get("content")
    if not isinstance(content, list):
        return bool(str(content or "").strip()) or bool(raw.get("errorMessage"))
    for item in content:
        value = _mapping(item)
        if str(value.get("type") or "") in {"toolCall", "tool_call"}:
            return False
    return any(
        str(_mapping(item).get("type") or "") in {"text", "image"}
        for item in content
    ) or bool(raw.get("errorMessage"))


def _public_usage(value: object) -> dict[str, int]:
    message = _mapping(value)
    usage = _mapping(message.get("usage"))
    input_tokens = _integer(usage.get("input"))
    output_tokens = _integer(usage.get("output"))
    cache_read = _integer(usage.get("cacheRead"))
    cache_write = _integer(usage.get("cacheWrite"))
    total = _integer(usage.get("totalTokens"))
    if total <= 0:
        total = input_tokens + output_tokens + cache_read + cache_write
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": total,
    }


def _provider_retry_status(
    payload: Mapping[str, object],
    *,
    started: bool,
) -> dict[str, object]:
    """Project retry progress without leaking raw Provider diagnostics."""

    attempt = max(1, _integer(payload.get("attempt")))
    maximum = max(attempt, _integer(payload.get("maxAttempts")))
    if started:
        return {
            "status": "retrying",
            "phase": "provider_retry",
            "activityState": "running",
            "summary": f"模型连接暂时失败，正在自动重试（{attempt}/{maximum}）",
            "attempt": attempt,
            "maxAttempts": maximum,
            "delayMs": max(0, _integer(payload.get("delayMs"))),
        }
    success = payload.get("success") is True
    return {
        "status": "analyzing" if success else "working",
        "phase": "provider_retry",
        "activityState": "completed" if success else "failed",
        "summary": (
            "模型连接已恢复，继续处理"
            if success
            else "自动重试未恢复，正在结束本轮"
        ),
        "attempt": attempt,
        "maxAttempts": maximum,
        "success": success,
    }


def _ui_confirmation_value(value: object) -> bool:
    normalized = str(value or "").strip().lower()
    affirmative = (
        "yes",
        "y",
        "true",
        "confirm",
        "confirmed",
        "allow",
        "approve",
        "是",
        "确认",
        "同意",
        "允许",
        "批准",
        "保留",
    )
    negative = (
        "no",
        "n",
        "false",
        "cancel",
        "deny",
        "reject",
        "否",
        "取消",
        "不同意",
        "拒绝",
        "不允许",
        "删除",
    )
    if any(normalized == item or normalized.startswith(f"{item}，") or normalized.startswith(f"{item},") for item in affirmative):
        return True
    if any(normalized == item or normalized.startswith(f"{item}，") or normalized.startswith(f"{item},") for item in negative):
        return False
    raise PiRuntimeError("confirm UI response must explicitly approve or reject the request")


def _public_fork_candidate_text(value: object, *, role: str = "user") -> str:
    """Return a public transcript preview without leaking injected context."""

    normalized = " ".join(str(value or "").split())[:8000]
    visible = (
        " ".join(_visible_message_text("user", normalized).split())[:8000]
        if role == "user"
        else normalized
    )
    if any(
        marker in visible
        for marker in (
            "<agent-deep-search-context",
            "<agent-user-query",
            "<rag-ime-deep-search-context",
            "<rag-ime-user-query",
        )
    ):
        return ""
    return visible


def _public_code_tool_activity(tool_name: str, args: Mapping[str, object]) -> dict[str, object]:
    normalized_tool = str(tool_name or "").strip().lower()
    file_tools = {
        "read", "read_file", "workspace_read",
        "write", "write_file", "workspace_write_file",
        "edit", "edit_file", "workspace_edit_file",
    }
    if normalized_tool not in file_tools:
        return {}
    raw_path = str(args.get("relativePath") or args.get("fileName") or args.get("file_path") or args.get("path") or "")
    file_name = _public_file_name(raw_path)
    result: dict[str, object] = {}
    if file_name:
        result["fileName"] = file_name
    if normalized_tool in {"write", "write_file", "workspace_write_file"}:
        content = args.get("content")
        if isinstance(content, str) and content:
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            lines = normalized.split("\n")
            while lines and not lines[-1]:
                lines.pop()
            line_count = max(1, len(lines))
            result.update({"lineCount": line_count, "additions": line_count})
            if file_name:
                result["summary"] = f"{file_name} +{line_count}"
    return result


def _public_pi_model(raw: Mapping[str, object]) -> dict[str, object]:
    provider = str(raw.get("provider") or "").strip()
    model_id = str(raw.get("id") or "").strip()
    if not provider or not model_id:
        return {}
    inputs = raw.get("input") if isinstance(raw.get("input"), list) else []
    return {
        "provider": provider[:80],
        "id": model_id[:160],
        "name": str(raw.get("name") or model_id).strip()[:160] or model_id[:160],
        "api": str(raw.get("api") or "").strip()[:80],
        "reasoning": bool(raw.get("reasoning")),
        "thinkingLevels": _supported_thinking_levels(raw),
        "supportsImages": "image" in {str(item) for item in inputs},
        "contextWindow": _integer(raw.get("contextWindow")),
        "maxTokens": _integer(raw.get("maxTokens")),
    }


def _redact_mapping(value: Mapping[str, object], *, depth: int = 0) -> dict[str, object]:
    if depth >= 4:
        return {"truncated": True}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:64]:
        key = str(raw_key)[:120]
        if re.search(r"token|secret|password|api.?key|authorization|cookie", key, re.IGNORECASE):
            result[key] = "[REDACTED_SECRET]"
        elif isinstance(raw_value, Mapping):
            result[key] = _redact_mapping(raw_value, depth=depth + 1)
        elif isinstance(raw_value, list):
            result[key] = [
                _redact_mapping(item, depth=depth + 1) if isinstance(item, Mapping) else _safe_scalar(item)
                for item in raw_value[:64]
            ]
        else:
            result[key] = _safe_scalar(raw_value)
    return result


def _managed_media_content_url(session_id: str, media_id: str) -> str:
    return (
        f"/api/agent/media/{quote(str(media_id), safe='')}/content"
        f"?sessionId={quote(str(session_id), safe='')}"
    )


def _pi_message_payload(
    raw: Mapping[str, object],
    *,
    session_id: str,
    turn_id: str,
    media_resolver: Callable[[str, str, str], str] | None = None,
    message_id: str | None = None,
    trusted_blocks: object = None,
) -> AgentMessage:
    role = str(raw.get("role") or "assistant")
    if role not in {"user", "assistant", "tool", "system"}:
        role = "tool" if role.lower().startswith("tool") else "assistant"
    content = raw.get("content")
    resolved_message_id = message_id or _pi_message_id(raw, turn_id)
    fallback_blocks_enabled = trusted_blocks is None
    blocks: list[AgentBlock] = []
    blocks.extend(
        AgentBlock.from_payload(item)
        for item in normalize_trusted_agent_blocks(
            trusted_blocks,
            source_kind="pi_runtime_event",
            source_ref=f"{session_id}:{resolved_message_id}",
        )
    )
    attachments: list[str] = []
    if isinstance(content, str):
        visible_content = _visible_message_text(role, content)
        extracted = (
            extract_completed_agent_blocks(
                visible_content,
                source_kind="pi_session_message",
                source_ref=f"{session_id}:{resolved_message_id}",
            )
            if role == "assistant"
            else None
        )
        if extracted is not None:
            visible_content = extracted.text
            if fallback_blocks_enabled:
                blocks.extend(AgentBlock.from_payload(item) for item in extracted.blocks)
        if visible_content:
            blocks.append(
                normalize_agent_block(
                    {
                        "id": f"{turn_id}:text:0",
                        "type": "text",
                        "status": "completed",
                        "presentationKind": "markdown",
                        "data": {"text": visible_content},
                    }
                )
            )
    elif isinstance(content, list):
        for index, item in enumerate(content):
            value = _mapping(item)
            content_type = str(value.get("type") or "unknown")
            if content_type == "text":
                visible_content = _visible_message_text(role, str(value.get("text") or ""))
                extracted = (
                    extract_completed_agent_blocks(
                        visible_content,
                        source_kind="pi_session_message",
                        source_ref=f"{session_id}:{resolved_message_id}",
                    )
                    if role == "assistant"
                    else None
                )
                if extracted is not None:
                    visible_content = extracted.text
                    if fallback_blocks_enabled:
                        blocks.extend(AgentBlock.from_payload(item) for item in extracted.blocks)
                if visible_content:
                    blocks.append(
                        normalize_agent_block(
                            {
                                "id": f"{turn_id}:text:{index}",
                                "type": "text",
                                "status": "completed",
                                "presentationKind": "markdown",
                                "data": {"text": visible_content},
                            }
                        )
                    )
            elif content_type == "image" and media_resolver is not None:
                media_id = media_resolver(
                    session_id,
                    str(value.get("mimeType") or ""),
                    str(value.get("data") or ""),
                )
                if media_id:
                    attachments.append(media_id)
                    receipt_url = _managed_media_content_url(session_id, media_id)
                    blocks.append(
                        normalize_agent_block(
                            {
                                "id": f"{turn_id}:image:{index}",
                                "type": "image",
                                "status": "completed",
                                "presentationKind": "image",
                                "data": {
                                    "mediaId": media_id,
                                    "receiptUrl": receipt_url,
                                },
                            }
                        )
                    )
            elif content_type in {"thinking", "redacted_thinking"}:
                continue
            elif content_type in {"toolCall", "tool_call"}:
                blocks.append(
                    normalize_agent_block(
                        {
                            "id": str(value.get("id") or f"{turn_id}:tool:{index}"),
                            "type": "tool_call",
                            "status": "completed",
                            "presentationKind": "tool_call",
                            "data": {
                                "toolCallId": str(value.get("id") or ""),
                                "toolName": str(value.get("name") or value.get("toolName") or ""),
                                "arguments": _redact_mapping(_mapping(value.get("arguments"))),
                            },
                        }
                    )
                )
    error_message = _redact_runtime_text(str(raw.get("errorMessage") or "").strip())
    failed = str(raw.get("stopReason") or "").lower() == "error" or bool(error_message)
    if failed:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:error:0",
                    "type": "error",
                    "status": "failed",
                    "presentationKind": "error",
                    "data": {"message": error_message or "模型请求失败，请重试"},
                }
            )
        )
    if not blocks:
        blocks.append(
            normalize_agent_block(
                {
                    "id": f"{turn_id}:progress:0",
                    "type": "progress",
                    "status": "completed",
                    "presentationKind": "progress",
                    "data": {"label": "本轮没有可展示正文"},
                }
            )
        )
    created_at = _integer(raw.get("timestamp")) or int(time.time() * 1000)
    return AgentMessage(
        message_id=resolved_message_id,
        session_id=session_id,
        turn_id=turn_id,
        role=role,
        status="failed" if failed else "completed",
        blocks=tuple(blocks),
        attachments=tuple(dict.fromkeys(attachments)),
        created_at_ms=created_at,
        completed_at_ms=created_at,
        provider=str(raw.get("provider") or "").strip()[:80],
        model=str(raw.get("responseModel") or raw.get("model") or "").strip()[:160],
        usage=_public_usage(raw) if role == "assistant" else None,
    )
