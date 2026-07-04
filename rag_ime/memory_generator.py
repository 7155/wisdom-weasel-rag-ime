from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .text_utils import compact_whitespace, truncate_text


@dataclass(frozen=True)
class VcpRebuildConfig:
    api_base_url: str
    api_key: str
    model: str
    upstream_wire_api: Literal["chat_completions", "responses"] = "chat_completions"
    request_timeout_seconds: float = 60.0
    model_reasoning_effort: str = ""
    disable_response_storage: bool = True
    env_path: Path | None = None


@dataclass(frozen=True)
class GeneratedMemoryItem:
    text: str
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    reason: str = ""
    source: str = ""


@dataclass(frozen=True)
class GeneratedMemoryReport:
    provider: str
    model: str
    elapsed_ms: int
    items: tuple[GeneratedMemoryItem, ...] = ()
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryGenerationError(RuntimeError):
    pass


class VcpRebuildMemoryGenerator:
    """A small AIMemo-style memory distiller backed by vcp-agent-rebuild config."""

    provider_name = "vcp-rebuild"

    def __init__(self, config: VcpRebuildConfig):
        if not config.api_key:
            raise MemoryGenerationError("VCP rebuild API_KEY is not configured")
        self.config = config

    @classmethod
    def from_env_path(cls, env_path: str | Path | None = None) -> "VcpRebuildMemoryGenerator":
        resolved = Path(env_path).expanduser() if env_path else default_vcp_rebuild_env_path()
        if resolved is None or not resolved.exists():
            raise MemoryGenerationError("vcp-agent-rebuild/backend/.env was not found")
        values = _read_env_file(resolved)
        config = VcpRebuildConfig(
            api_base_url=values.get("API_BASE_URL", "https://example.com/v1"),
            api_key=values.get("API_KEY", ""),
            model=values.get("MODEL", "gpt-5.5"),
            upstream_wire_api=_wire_api(values.get("UPSTREAM_WIRE_API", "chat_completions")),
            request_timeout_seconds=_float_value(values.get("REQUEST_TIMEOUT_SECONDS"), default=60.0),
            model_reasoning_effort=values.get("MODEL_REASONING_EFFORT", ""),
            disable_response_storage=_bool_value(values.get("DISABLE_RESPONSE_STORAGE"), default=True),
            env_path=resolved,
        )
        return cls(config)

    def generate(
        self,
        *,
        text: str,
        recent_context: str = "",
        project: str = "wisdom-weasel-rag-ime",
        max_items: int = 3,
    ) -> GeneratedMemoryReport:
        source_text = compact_whitespace(text)
        context = compact_whitespace(recent_context)
        if not source_text:
            return GeneratedMemoryReport(provider=self.provider_name, model=self.config.model, elapsed_ms=0)
        max_count = max(1, min(8, int(max_items)))
        messages = [
            {"role": "system", "content": _memory_generation_system_prompt(max_count=max_count)},
            {
                "role": "user",
                "content": (
                    f"项目: {project}\n"
                    f"近期上下文: {context or '无'}\n"
                    f"本次输入: {source_text}\n"
                    f"请生成最多 {max_count} 条长期记忆。"
                ),
            },
        ]
        started = time.perf_counter()
        response = self._call_model(messages=messages, max_tokens=700)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        raw_text = _extract_chat_text(response)
        items = tuple(_parse_generated_memory_items(raw_text, max_items=max_count))
        return GeneratedMemoryReport(
            provider=self.provider_name,
            model=self.config.model,
            elapsed_ms=elapsed_ms,
            items=items,
            raw_text=raw_text,
            metadata={
                "wireApi": self.config.upstream_wire_api,
                "envPath": str(self.config.env_path) if self.config.env_path else "",
                "itemCount": len(items),
            },
        )

    def _call_model(self, *, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        if self.config.upstream_wire_api == "responses":
            url = _build_openai_url(self.config.api_base_url, "/responses")
            payload: dict[str, Any] = {
                "model": self.config.model,
                "input": messages,
                "max_output_tokens": max_tokens,
            }
            if self.config.disable_response_storage:
                payload["store"] = False
            if self.config.model_reasoning_effort:
                payload["reasoning"] = {"effort": self.config.model_reasoning_effort}
        else:
            url = _build_openai_url(self.config.api_base_url, "/chat/completions")
            payload = {
                "model": self.config.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": max_tokens,
            }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            preview = exc.read(500).decode("utf-8", errors="replace")
            raise MemoryGenerationError(f"VCP memory generation HTTP {exc.code}: {preview}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise MemoryGenerationError(f"VCP memory generation failed: {exc}") from exc
        if not isinstance(parsed, dict):
            raise MemoryGenerationError("VCP memory generation returned non-object JSON")
        return parsed


def generated_memory_dedupe_tag(text: str) -> str:
    import hashlib

    digest = hashlib.sha1(compact_whitespace(text).encode("utf-8")).hexdigest()[:12]
    return f"vcp-memory:{digest}"


def generated_memory_context(source_text: str, recent_context: str, reason: str) -> str:
    parts = [
        "VCP AIMemo-style generated memory",
        f"reason: {compact_whitespace(reason)}" if reason else "",
        f"context: {compact_whitespace(recent_context)}" if recent_context else "",
        f"source: {compact_whitespace(source_text)[:240]}",
    ]
    return " | ".join(part for part in parts if part)


def default_vcp_rebuild_env_path() -> Path | None:
    env_override = os.environ.get("RAG_IME_VCP_REBUILD_ENV", "").strip()
    if env_override:
        return Path(env_override).expanduser()
    candidates: list[Path] = []
    cwd = Path.cwd()
    candidates.append(cwd / "vcp-agent-rebuild/backend/.env")
    for parent in (cwd, *cwd.parents):
        candidates.append(parent / "vcp-agent-rebuild/backend/.env")
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "vcp-agent-rebuild/backend/.env")
        candidates.append(parent.parent / "vcp-agent-rebuild/backend/.env")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _memory_generation_system_prompt(*, max_count: int) -> str:
    return (
        "你是一个输入法长期记忆蒸馏器，参考 VCP AIMemo 的思路："
        "只把原始输入压缩成稳定、可复用、可检索的长期记忆，不保存一次性抱怨、调试噪声或隐私。"
        "适合保存: 用户长期偏好、项目要求、明确决策、稳定工作流、常用术语/短语。"
        "不保存: 密码/API key/身份证/银行卡、临时情绪、报错堆栈、'不能用/没生效/展示不好' 这类瞬时反馈。"
        "每条记忆必须短、具体、可直接作为 RAG/输入法候选依据。"
        f"最多输出 {max_count} 条。只输出 JSON，不要 Markdown。"
        '格式: {"memories":[{"text":"...","tags":["preference"],"importance":0.8,"reason":"..."}]}'
    )


def _parse_generated_memory_items(raw_text: str, *, max_items: int = 3) -> list[GeneratedMemoryItem]:
    payload = _extract_json_object(raw_text)
    memories = payload.get("memories") if isinstance(payload, dict) else None
    if not isinstance(memories, list):
        return []
    items: list[GeneratedMemoryItem] = []
    for item in memories:
        if not isinstance(item, dict):
            continue
        text = compact_whitespace(str(item.get("text") or ""))
        if not _is_usable_generated_memory(text):
            continue
        tags = tuple(_safe_tag(tag) for tag in item.get("tags", []) if _safe_tag(tag))
        reason = truncate_text(compact_whitespace(str(item.get("reason") or "")), 120)
        importance = _float_value(item.get("importance"), default=0.5)
        items.append(
            GeneratedMemoryItem(
                text=truncate_text(text, 160),
                tags=tuple(dict.fromkeys(tags)),
                importance=max(0.0, min(1.0, importance)),
                reason=reason,
                source="vcp-aimemo",
            )
        )
        if len(items) >= max(0, int(max_items)):
            break
    return items


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _extract_chat_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return str(message["content"])
            if isinstance(first.get("text"), str):
                return str(first["text"])
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                parts.append(str(content["text"]))
    return "".join(parts)


def _is_usable_generated_memory(text: str) -> bool:
    if len(text) < 4:
        return False
    lowered = text.lower()
    blocked = (
        "api_key",
        "apikey",
        "password",
        "密码",
        "银行卡",
        "身份证",
        "不能用",
        "用不了",
        "没生效",
        "真实生效",
        "展示不好",
        "报错",
        "traceback",
        "brokenpipe",
    )
    return not any(token in lowered or token in text for token in blocked)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _build_openai_url(api_base_url: str, endpoint: str) -> str:
    base_url = api_base_url.rstrip("/")
    endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    base_path = urllib.parse.urlsplit(base_url).path.rstrip("/")
    if base_path.endswith("/v1"):
        return f"{base_url}{endpoint_path}"
    return f"{base_url}/v1{endpoint_path}"


def _safe_tag(value: object) -> str:
    tag = compact_whitespace(str(value)).lower().replace(" ", "-")
    tag = re.sub(r"[^a-z0-9_\-:\u4e00-\u9fff]+", "", tag)
    return tag[:40]


def _wire_api(value: str) -> Literal["chat_completions", "responses"]:
    normalized = value.strip().lower()
    return "responses" if normalized == "responses" else "chat_completions"


def _float_value(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_value(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default
