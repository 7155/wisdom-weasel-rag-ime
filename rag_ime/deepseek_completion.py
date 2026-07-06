from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Literal

from .deepseek_config import DeepSeekConfig
from .runtime_flags import assert_deepseek_scene_allowed
from .text_utils import compact_whitespace, truncate_text


DeepSeekCompletionScene = Literal["post_commit", "active_rag", "editor"]


@dataclass(frozen=True)
class DeepSeekCompletionRequest:
    scene: DeepSeekCompletionScene
    current_context: str
    selected_text: str = ""
    evidence_pack: tuple[dict[str, object], ...] = ()
    max_candidates: int = 5
    max_chars: int = 24
    stream: bool = True
    latency_budget_ms: int = 2500


@dataclass(frozen=True)
class CompletionCandidateDelta:
    text: str
    insert_text: str
    source_type: str = "model"
    source_lane: str = "deepseek_v4_flash"
    done: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class DeepSeekCompletionError(RuntimeError):
    pass


Urlopen = Callable[..., Any]


class DeepSeekV4FlashCompletionProvider:
    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        urlopen: Urlopen | None = None,
        enforce_runtime_flags: bool = True,
    ):
        self.config = config
        self.urlopen = urlopen or urllib.request.urlopen
        self.enforce_runtime_flags = bool(enforce_runtime_flags)

    def stream_candidates(self, request: DeepSeekCompletionRequest) -> Iterator[CompletionCandidateDelta]:
        if self.enforce_runtime_flags:
            _assert_completion_scene_allowed(request.scene)
        if not self.config.api_key:
            raise DeepSeekCompletionError("DeepSeek API key is required for completion streaming")
        body = {
            "model": self.config.model,
            "messages": build_deepseek_completion_messages(request),
            "temperature": 0.2,
            "max_tokens": max(128, min(2048, int(request.max_candidates) * 96)),
            "stream": bool(request.stream),
        }
        http_request = urllib.request.Request(
            f"{self.config.api_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
                "User-Agent": "rag-ime/1.0 deepseek-completion",
            },
            method="POST",
        )
        started = time.perf_counter()
        seen: set[str] = set()
        buffer = ""
        try:
            with self.urlopen(http_request, timeout=max(0.1, request.latency_budget_ms / 1000)) as response:
                for delta in _iter_text_deltas(response):
                    buffer += delta
                    buffer = buffer.replace("\\n", "\n").replace("\\r", "\r")
                    lines = buffer.splitlines(keepends=True)
                    buffer = ""
                    for line in lines:
                        if line.endswith("\n") or line.endswith("\r"):
                            yield from _candidate_from_line(
                                line,
                                request=request,
                                seen=seen,
                                started=started,
                            )
                        else:
                            buffer = line
                if buffer:
                    yield from _candidate_from_line(buffer, request=request, seen=seen, started=started)
        except (TimeoutError, urllib.error.URLError, OSError, json.JSONDecodeError):
            return


def build_deepseek_completion_messages(request: DeepSeekCompletionRequest) -> list[dict[str, str]]:
    evidence = _redacted_evidence_pack(request.evidence_pack)
    return [
        {
            "role": "system",
            "content": (
                "你是输入法候选生成器。根据当前上下文和 RAG evidence pack，生成 3~5 个可直接输入的短候选。"
                "只输出 JSON Lines，每行一个 JSON 对象。不要解释。不要 Markdown。不要输出历史原句。"
                "不要输出“下一步”“接下来”“根据上述”“可以进行”等泛化词。每个候选 4~24 个中文字。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scene": request.scene,
                    "currentContext": truncate_text(_redact_text(request.current_context), 240),
                    "selectedText": truncate_text(_redact_text(request.selected_text), 160),
                    "maxCandidates": max(1, int(request.max_candidates)),
                    "maxChars": max(4, int(request.max_chars)),
                    "evidencePack": evidence,
                    "outputFormat": {"candidate": "短候选", "role": "phrase"},
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _assert_completion_scene_allowed(scene: str) -> None:
    if scene == "post_commit":
        assert_deepseek_scene_allowed("post_commit")
    elif scene == "active_rag":
        assert_deepseek_scene_allowed("active_rag")
    elif scene == "editor":
        assert_deepseek_scene_allowed("offline_compile")
    else:
        raise DeepSeekCompletionError(f"unknown DeepSeek completion scene: {scene}")


def _iter_text_deltas(response) -> Iterator[str]:
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data:"):
            data = stripped[5:].strip()
            if data == "[DONE]":
                break
            payload = json.loads(data)
            text = _chat_delta_text(payload)
            if text:
                yield text
        else:
            yield line


def _chat_delta_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return str(delta["content"])
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return str(message["content"])
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _candidate_from_line(
    line: str,
    *,
    request: DeepSeekCompletionRequest,
    seen: set[str],
    started: float,
) -> Iterator[CompletionCandidateDelta]:
    candidate = _parse_candidate_line(line)
    if not _candidate_allowed(candidate, request=request, seen=seen):
        return
    seen.add(candidate)
    yield CompletionCandidateDelta(
        text=candidate,
        insert_text=candidate,
        metadata={
            "scene": request.scene,
            "elapsedMs": int((time.perf_counter() - started) * 1000),
            "model": "deepseek_v4_flash",
        },
    )


def _parse_candidate_line(line: str) -> str:
    stripped = compact_whitespace(line)
    if stripped.endswith("\\n") or stripped.endswith("\\r"):
        stripped = stripped[:-2].strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return compact_whitespace(str(payload.get("candidate") or payload.get("text") or ""))


def _candidate_allowed(candidate: str, *, request: DeepSeekCompletionRequest, seen: set[str]) -> bool:
    text = compact_whitespace(candidate)
    if not text or text in seen:
        return False
    if len(text) < 2 or len(text) > max(4, int(request.max_chars)):
        return False
    lowered = text.lower()
    if any(marker in text for marker in ("下一步", "接下来", "根据上述", "可以进行", "可以继续")):
        return False
    if "json" in lowered or "markdown" in lowered or "输入法候选生成器" in text:
        return False
    context = compact_whitespace(f"{request.current_context} {request.selected_text}")
    if len(text) > 6 and text in context:
        return False
    for item in request.evidence_pack:
        raw = compact_whitespace(str(item.get("rawText") or item.get("raw_text") or item.get("text") or ""))
        if len(text) > 6 and raw and text in raw:
            return False
    return True


def _redacted_evidence_pack(evidence_pack: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in evidence_pack[:12]:
        result.append(
            {
                "sourceType": compact_whitespace(str(item.get("sourceType") or item.get("source_type") or "")),
                "title": truncate_text(_redact_text(str(item.get("title") or "")), 80),
                "surfaceHints": _short_list(item.get("surfaceHints") or item.get("surface_hints")),
                "tags": _short_list(item.get("tags")),
                "preview": truncate_text(
                    _redact_text(str(item.get("evidencePreview") or item.get("evidence_preview") or item.get("summary") or "")),
                    120,
                ),
            }
        )
    return result


def _short_list(raw: object) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [truncate_text(_redact_text(str(item)), 32) for item in raw[:8] if compact_whitespace(str(item))]


_SECRET_RE = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{24,})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PATH_RE = re.compile(r"(/Users/|/Volumes/|/var/folders/|[A-Za-z]:\\)[^\s，。；;]+")


def _redact_text(text: str) -> str:
    value = compact_whitespace(text)
    value = _SECRET_RE.sub("[REDACTED_SECRET]", value)
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _PATH_RE.sub("[REDACTED_PATH]", value)
    return value
