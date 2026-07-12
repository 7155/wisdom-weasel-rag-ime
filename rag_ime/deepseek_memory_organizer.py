from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from .deepseek_config import DeepSeekConfig
from .deepseek_completion import _direct_deepseek_urlopen
from .memory_generator import _extract_json_object
from .text_utils import compact_whitespace


MEMORY_BOOK_COMPILE_SCHEMA_VERSION = "rag-ime.memory-book-compile.v1"
_RIME_PINYIN_RE = re.compile(r"^[a-zv]+(?: [a-zv]+)*$")


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
        text = _chat_completion_text(response)
        extracted = _extract_json_object(text)
        payload = extracted if isinstance(extracted, dict) else json.loads(extracted)
        if not isinstance(payload, dict):
            raise DeepSeekMemoryOrganizerError("DeepSeek memory book response was not a JSON object")
        payload.setdefault("schemaVersion", MEMORY_BOOK_COMPILE_SCHEMA_VERSION)
        payload.setdefault("dailyBooks", [])
        payload.setdefault("topicBooks", [])
        payload.setdefault("memoryAtoms", [])
        payload.setdefault("tagEdges", [])
        payload.setdefault("phraseCandidates", [])
        payload.setdefault("negativePhrases", [])
        payload.setdefault("supersedes", [])
        payload.setdefault("warnings", [])
        if not isinstance(payload["warnings"], list):
            payload["warnings"] = []
        self._repair_phrase_candidate_pinyin(payload=payload, project=project)
        payload["provider"] = self.provider_name
        payload["model"] = self.config.model
        payload["elapsedMs"] = int((time.perf_counter() - started) * 1000)
        return payload

    def _repair_phrase_candidate_pinyin(self, *, payload: dict[str, object], project: str) -> None:
        raw_candidates = payload.get("phraseCandidates")
        if not isinstance(raw_candidates, list):
            payload["phraseCandidates"] = []
            return
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)]
        payload["phraseCandidates"] = candidates
        missing_texts = list(
            dict.fromkeys(
                compact_whitespace(str(item.get("text") or ""))
                for item in candidates
                if compact_whitespace(str(item.get("text") or ""))
                and not _normalized_rime_pinyin(item.get("pinyin"))
            )
        )[:32]
        if not missing_texts:
            return

        messages = [
            {
                "role": "system",
                "content": (
                    "你只负责给输入法短语补全普通话拼音。只输出 JSON 对象，格式为 "
                    '{"items":[{"text":"原文","pinyin":"xiao xie wu sheng diao"}]}。'
                    "text 必须逐字等于输入列表，pinyin 只能是小写无声调字母，音节用单空格分隔。"
                    "无法确认时省略该项，不要解释、不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"project": project, "texts": missing_texts},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        warnings = payload["warnings"]
        assert isinstance(warnings, list)
        try:
            response = self._call_chat_completions(messages=messages, max_tokens=512)
            text = _chat_completion_text(response)
            extracted = _extract_json_object(text)
            repaired_payload = extracted if isinstance(extracted, dict) else json.loads(extracted)
        except (DeepSeekMemoryOrganizerError, json.JSONDecodeError, TypeError, ValueError):
            warnings.append("phrase_pinyin_repair_failed")
            return

        repaired_items = repaired_payload.get("items") if isinstance(repaired_payload, dict) else None
        if not isinstance(repaired_items, list) and isinstance(repaired_payload, dict):
            repaired_items = repaired_payload.get("phraseCandidates")
        mapping: dict[str, str] = {}
        for item in repaired_items if isinstance(repaired_items, list) else []:
            if not isinstance(item, dict):
                continue
            item_text = compact_whitespace(str(item.get("text") or ""))
            pinyin = _normalized_rime_pinyin(item.get("pinyin"))
            if item_text in missing_texts and pinyin:
                mapping[item_text] = pinyin

        repaired_count = 0
        for item in candidates:
            item_text = compact_whitespace(str(item.get("text") or ""))
            if _normalized_rime_pinyin(item.get("pinyin")):
                continue
            pinyin = mapping.get(item_text, "")
            if pinyin:
                item["pinyin"] = pinyin
                repaired_count += 1
        if repaired_count:
            warnings.append(f"phrase_pinyin_repaired:{repaired_count}")
        remaining = sum(not _normalized_rime_pinyin(item.get("pinyin")) for item in candidates)
        if remaining:
            warnings.append(f"phrase_pinyin_missing:{remaining}")

    def _call_chat_completions(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": (
                max(128, min(1024, int(max_tokens)))
                if max_tokens is not None
                else max(512, min(4096, int(self.config.memory_book_max_tokens)))
            ),
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


def _normalized_rime_pinyin(value: object) -> str:
    pinyin = " ".join(compact_whitespace(str(value or "")).lower().split())
    return pinyin if _RIME_PINYIN_RE.fullmatch(pinyin) else ""


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
        你是 RAG 输入法的离线记忆整理器。你必须把原始输入历史整理成 dailyBooks、topicBooks、
        Memory Atom、Tag Edge 和短 phraseCandidate。只输出 JSON 对象，schemaVersion 必须是
        rag-ime.memory-book-compile.v1。sourceEventIds/evidenceEventIds 必须来自输入 bundle 的 eventId，
        且不能为空。Group 只能使用 bundle.legalContextGroupIds 中的值，不能自行分类或编造。
        dailyBooks 只记录按时间发生的近期变化；topicBooks 用于长期、跨时间的语义主题，例如项目、研究方向、
        模型训练偏好、工作习惯和稳定目标。每个 topicBook 必须包含 bookType="topic"、稳定的英文或拼音 bookKey、
        bookId="book:topic:<bookKey>"、清晰的中文 title、80 到 300 字 summary、tags、queryExpansions、
        sourceEventIds、confidence 和 qualityScore。相同主题应复用 bundle.existingBooks 中已有的 bookId/bookKey，
        更新摘要而不是按日期新建重复主题；一次最多输出 8 个高置信主题，不要把单句临时请求提升为长期主题。
        surfaceHints 和 phraseCandidates 必须是 2 到 18 个中文字符或短术语。每个 phraseCandidate
        必须包含 text、pinyin、tags、weight、sourceEventIds；pinyin 使用小写无声调拼音，音节之间用单个空格，
        例如 {"text":"表情包","pinyin":"biao qing bao"}。不确定拼音时不要输出该词库候选。
        canonicalText 只用于检索证据，不能直接作为输入法候选；directCandidateAllowed 默认 false。
        同时输出 negativePhrases 和 supersedes 数组。不要输出 secret、路径、邮箱、API key、
        长历史原句、标题式候选、元话语、解释文字或 Markdown。
        """
    )
