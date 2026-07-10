from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .deepseek_config import DeepSeekConfig
from .deepseek_completion import _direct_deepseek_urlopen
from .memory_generator import _extract_json_object
from .text_utils import compact_whitespace


MEMORY_BOOK_COMPILE_SCHEMA_VERSION = "rag-ime.memory-book-compile.v1"


class DeepSeekMemoryOrganizerError(RuntimeError):
    pass


class DeepSeekMemoryOrganizer:
    def __init__(self, config: DeepSeekConfig, *, urlopen: Callable[..., Any] | None = None):
        self.config = config
        self.urlopen = urlopen or _direct_deepseek_urlopen

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def compile_memory_book(self, *, bundle: dict[str, object], project: str) -> dict[str, object]:
        if not self.config.api_key:
            raise DeepSeekMemoryOrganizerError("DeepSeek API key is required for memory-book-preview")
        messages = [
            {"role": "system", "content": _memory_book_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"项目: {project}\n"
                    "请只输出 JSON 对象，不要 Markdown。\n"
                    f"历史输入 bundle:\n{json.dumps(bundle, ensure_ascii=False, sort_keys=True)}"
                ),
            },
        ]
        started = time.perf_counter()
        response = self._call_chat_completions(messages=messages)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        text = _chat_completion_text(response)
        extracted = _extract_json_object(text)
        payload = extracted if isinstance(extracted, dict) else json.loads(extracted)
        if not isinstance(payload, dict):
            raise DeepSeekMemoryOrganizerError("DeepSeek memory book response was not a JSON object")
        payload.setdefault("schemaVersion", MEMORY_BOOK_COMPILE_SCHEMA_VERSION)
        payload.setdefault("dailyBooks", [])
        payload.setdefault("memoryAtoms", [])
        payload.setdefault("tagEdges", [])
        payload.setdefault("phraseCandidates", [])
        payload.setdefault("negativePhrases", [])
        payload.setdefault("supersedes", [])
        payload.setdefault("warnings", [])
        payload["provider"] = self.provider_name
        payload["model"] = self.config.model
        payload["elapsedMs"] = elapsed_ms
        return payload

    def _call_chat_completions(self, *, messages: list[dict[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": max(512, min(4096, int(self.config.memory_book_max_tokens))),
            "stream": False,
        }
        if self.config.json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.config.thinking:
            body["thinking"] = {"type": self.config.thinking}
        if self.config.reasoning_effort and self.config.thinking != "disabled":
            body["reasoning_effort"] = self.config.reasoning_effort
        request = urllib.request.Request(
            f"{self.config.api_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "rag-ime/1.0 curl-compatible",
            },
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            raise DeepSeekMemoryOrganizerError(f"DeepSeek memory book request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise DeepSeekMemoryOrganizerError("DeepSeek memory book response payload was not an object")
        return payload


def _chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _memory_book_system_prompt() -> str:
    return compact_whitespace(
        """
        你是 RAG 输入法的离线记忆整理器。你必须把原始输入历史整理成 Memory Book、Memory Atom、
        Tag Edge 和短 phraseCandidate。只输出 JSON 对象，schemaVersion 必须是
        rag-ime.memory-book-compile.v1。sourceEventIds/evidenceEventIds 必须来自输入 bundle 的 eventId，
        且不能为空。Group 只能使用 bundle.legalContextGroupIds 中的值，不能自行分类或编造。
        surfaceHints 和 phraseCandidates 必须是 2 到 18 个中文字符或短术语。
        canonicalText 只用于检索证据，不能直接作为输入法候选；directCandidateAllowed 默认 false。
        同时输出 negativePhrases 和 supersedes 数组。不要输出 secret、路径、邮箱、API key、
        长历史原句、标题式候选、元话语、解释文字或 Markdown。
        """
    )
