from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Literal

from .anti_echo import candidate_echoes_text, candidate_has_keyword_echo, candidate_has_self_repetition, repeat_norm
from .deepseek_config import DeepSeekConfig
from .runtime_flags import assert_deepseek_scene_allowed
from .text_utils import compact_whitespace, truncate_text


DeepSeekCompletionScene = Literal["post_commit", "active_rag", "editor"]
_DIRECT_DEEPSEEK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class DeepSeekCompletionRequest:
    scene: DeepSeekCompletionScene
    current_context: str
    selected_text: str = ""
    evidence_pack: tuple[dict[str, object], ...] = ()
    context_packet: dict[str, object] | None = None
    max_candidates: int = 1
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
        self.urlopen = urlopen or _direct_deepseek_urlopen
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
            "max_tokens": min(_completion_token_budget(request), _configured_completion_token_cap(self.config, request)),
            "stream": bool(request.stream and self.config.stream),
        }
        if self.config.thinking:
            body["thinking"] = {"type": self.config.thinking}
        if self.config.reasoning_effort and self.config.thinking != "disabled":
            body["reasoning_effort"] = self.config.reasoning_effort
        started = time.perf_counter()
        seen: set[str] = set()
        content_buffer = ""
        reasoning_buffer = ""
        yielded_count = 0
        fallback_reason = "empty_remote_content"
        deadline = started + max(0.1, request.latency_budget_ms / 1000)
        for attempt_body in _completion_body_attempts(body):
            http_request = _build_completion_http_request(self.config, attempt_body)
            budget_elapsed = False
            try:
                with self.urlopen(http_request, timeout=max(0.1, request.latency_budget_ms / 1000)) as response:
                    for kind, delta in _iter_model_deltas(response):
                        if kind == "reasoning":
                            reasoning_buffer += delta
                            if time.perf_counter() >= deadline:
                                fallback_reason = "budget_elapsed"
                                budget_elapsed = True
                                break
                            continue
                        content_buffer += delta
                        content_buffer = content_buffer.replace("\\n", "\n").replace("\\r", "\r")
                        lines = content_buffer.splitlines(keepends=True)
                        content_buffer = ""
                        for line in lines:
                            if line.endswith("\n") or line.endswith("\r"):
                                for item in _candidates_from_text(line, request=request, seen=seen, started=started):
                                    yielded_count += 1
                                    yield item
                                    if yielded_count >= max(1, int(request.max_candidates)):
                                        return
                            else:
                                content_buffer = line
                        if time.perf_counter() >= deadline:
                            fallback_reason = "budget_elapsed"
                            budget_elapsed = True
                            break
                if budget_elapsed:
                    break
                break
            except urllib.error.HTTPError as exc:
                fallback_reason = _http_error_fallback_reason(exc)
                try:
                    exc.close()
                except Exception:
                    pass
                if attempt_body is not body:
                    break
                continue
            except (TimeoutError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
                fallback_reason = _exception_fallback_reason(exc)
                break
        if content_buffer:
            for item in _candidates_from_text(content_buffer, request=request, seen=seen, started=started):
                yielded_count += 1
                yield item
                if yielded_count >= max(1, int(request.max_candidates)):
                    return
        if yielded_count == 0 and _reasoning_fallback_enabled(request):
            for item in _candidates_from_reasoning(reasoning_buffer, request=request, seen=seen, started=started):
                yielded_count += 1
                yield item
                if yielded_count >= max(1, int(request.max_candidates)):
                    return
        if yielded_count == 0 and request.scene == "active_rag":
            for item in _candidates_from_request_fallback(
                request=request,
                seen=seen,
                started=started,
                fallback_reason=fallback_reason,
            ):
                yielded_count += 1
                yield item
                if yielded_count >= max(1, int(request.max_candidates)):
                    return


def fallback_deepseek_completion_candidates(
    request: DeepSeekCompletionRequest,
    *,
    fallback_reason: str = "visible_timeout",
) -> tuple[CompletionCandidateDelta, ...]:
    """Build a governed Active RAG candidate when the remote lane is unavailable."""
    return tuple(
        _candidates_from_request_fallback(
            request=request,
            seen=set(),
            started=time.perf_counter(),
            fallback_reason=fallback_reason,
        )
    )


def build_deepseek_completion_messages(request: DeepSeekCompletionRequest) -> list[dict[str, str]]:
    if request.scene == "active_rag":
        return _build_active_rag_completion_messages(request)
    evidence = _redacted_evidence_pack(request.evidence_pack)
    context_packet = _redacted_context_packet(request.context_packet)
    max_candidates = max(1, int(request.max_candidates))
    max_chars = max(4, int(request.max_chars))
    candidate_count_rule = (
        "只生成 1 个候选。"
        if max_candidates == 1
        else f"最多生成 {max_candidates} 个候选，按质量从高到低排列。"
    )
    return [
        {
            "role": "system",
            "content": (
                "你是输入法 Smart RAG 候选生成器。根据 ContextPacket 和 RAG evidence，生成可直接输入的短候选。"
                "优先级必须是 CurrentInput > OneRing > Timeline > Notebook。"
                f"{candidate_count_rule}"
                "只输出 JSON Lines，每行一个 JSON 对象，格式为 {\"candidate\":\"短候选\",\"role\":\"phrase\"}。"
                "不要解释。不要 Markdown。不要输出推理过程。"
                "这是低风险输入法候选补全任务，不需要高智商长推理；直接给候选。"
                "不要复读 currentContext、selectedText 或 evidencePack 里的原句。"
                f"不要输出“下一步”“接下来”“根据上述”“可以进行”等泛化词。每个候选 4~{max_chars} 个中文字。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scene": request.scene,
                    "currentContext": truncate_text(_redact_text(request.current_context), 240),
                    "selectedText": truncate_text(_redact_text(request.selected_text), 160),
                    "maxCandidates": max_candidates,
                    "maxChars": max_chars,
                    "contextPacket": context_packet,
                    "evidencePack": evidence,
                    "outputFormat": {"candidate": "短候选", "role": "phrase"},
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _build_active_rag_completion_messages(request: DeepSeekCompletionRequest) -> list[dict[str, str]]:
    evidence = _redacted_evidence_pack(request.evidence_pack)
    context_packet = _redacted_context_packet(request.context_packet)
    max_chars = max(4, int(request.max_chars))
    hints: list[str] = []
    for item in evidence[:6]:
        hints.extend(str(value) for value in item.get("surfaceHints", []) if compact_whitespace(str(value)))
        preview = compact_whitespace(str(item.get("preview") or ""))
        if preview:
            hints.append(preview)
        tags = item.get("tags")
        if isinstance(tags, list) and tags:
            hints.append(" ".join(str(tag) for tag in tags[:4]))
    return [
        {
            "role": "system",
            "content": (
                "你是 macOS 输入法的主动 RAG 预测器。你拿到光标上下文、最近输入、RAG 证据和 Notebook 记忆。"
                "任务是预测用户光标处最可能继续输入的一小段，只生成 1 个候选。"
                "如果 placement 是 insert_after_selection/append_at_cursor，就输出能接在 currentContext 后面的续写短语；"
                "如果 placement 是 replace_selection，才输出对 selectedText 的改写。"
                "第一句必须以“候选=”开头，等号后直接写候选内容。"
                "不要解释，不要总结，不要 Markdown，不要输出任务标题。"
                "候选必须具体、可直接插入；不要复述 selectedText/currentContext/Notebook 原句。"
                "优先使用 currentInput，其次用 oneRing/timeline/notebook/RAG evidence 补全语义。"
                "等号后的正文禁止出现“候选”“短语”“格式”“真实候选”“Notebook”“evidence”“oneRing”等提示词或字段名。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "currentContext": truncate_text(_redact_text(request.current_context), 300),
                    "selectedText": truncate_text(_redact_text(request.selected_text), 160),
                    "maxCandidates": max(1, int(request.max_candidates)),
                    "maxChars": max_chars,
                    "intent": _context_packet_string(context_packet, "intent") or request.scene,
                    "placement": _context_packet_string(context_packet, "placement") or "insert_after_selection",
                    "contextPacket": context_packet,
                    "evidenceHints": _unique_candidates([truncate_text(item, 80) for item in hints])[:12],
                    "task": (
                        f"写出光标处下一段 4 到 {max_chars} 个中文字正文。"
                        "正文要能直接接在当前输入后；"
                        "禁止写“下一步/接下来/可以继续/根据上述/候选/短语/格式/Notebook/evidence/oneRing”。"
                        "不要把 RAG 证据或 Notebook 标题原样显示。"
                        "只输出一行；行首固定为“候选=”，等号后直接写正文。"
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        },
    ]


def _context_packet_string(packet: dict[str, object], key: str) -> str:
    output_contract = packet.get("outputContract") if isinstance(packet, dict) else None
    if isinstance(output_contract, dict) and isinstance(output_contract.get(key), str):
        return compact_whitespace(str(output_contract.get(key)))
    current_input = packet.get("currentInput") if isinstance(packet, dict) else None
    if isinstance(current_input, dict) and isinstance(current_input.get(key), str):
        return compact_whitespace(str(current_input.get(key)))
    value = packet.get(key) if isinstance(packet, dict) else None
    return compact_whitespace(str(value)) if isinstance(value, str) else ""


def _assert_completion_scene_allowed(scene: str) -> None:
    if scene == "post_commit":
        assert_deepseek_scene_allowed("post_commit")
    elif scene == "active_rag":
        assert_deepseek_scene_allowed("active_rag")
    elif scene == "editor":
        assert_deepseek_scene_allowed("offline_compile")
    else:
        raise DeepSeekCompletionError(f"unknown DeepSeek completion scene: {scene}")


def _direct_deepseek_urlopen(request: urllib.request.Request, timeout: float | None = None):
    return _DIRECT_DEEPSEEK_OPENER.open(request, timeout=timeout)


def _build_completion_http_request(config: DeepSeekConfig, body: dict[str, object]) -> urllib.request.Request:
    return urllib.request.Request(
        f"{config.api_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
            "User-Agent": "rag-ime/1.0 deepseek-completion",
        },
        method="POST",
    )


def _completion_body_attempts(body: dict[str, object]) -> tuple[dict[str, object], ...]:
    if "reasoning_effort" not in body:
        return (body,)
    retry_body = dict(body)
    retry_body.pop("reasoning_effort", None)
    return (body, retry_body)


def _http_error_fallback_reason(exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        raw = exc.read(1024).decode("utf-8", errors="replace") if exc.fp else ""
        payload = json.loads(raw) if raw else None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                detail = compact_whitespace(str(error.get("code") or error.get("message") or ""))[:80]
    except Exception:
        detail = ""
    return f"http_{exc.code}{':' + detail if detail else ''}"


def _exception_fallback_reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return f"url_error:{type(exc.reason).__name__ if getattr(exc, 'reason', None) is not None else 'unknown'}"
    if isinstance(exc, json.JSONDecodeError):
        return "bad_json"
    return type(exc).__name__


def _iter_model_deltas(response) -> Iterator[tuple[str, str]]:
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
            reasoning = _chat_delta_reasoning_text(payload)
            if text:
                yield ("content", text)
            if reasoning:
                yield ("reasoning", reasoning)
        else:
            payload = _json_loads_or_none(stripped)
            if isinstance(payload, dict):
                content = _chat_completion_content_text(payload)
                reasoning = _chat_completion_reasoning_text(payload)
                if content:
                    yield ("content", content)
                if reasoning:
                    yield ("reasoning", reasoning)
            else:
                yield ("content", line)


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


def _chat_delta_reasoning_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("reasoning_content"), str):
        return str(delta["reasoning_content"])
    return ""


def _chat_completion_content_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return str(message["content"])
    return _chat_delta_text(payload)


def _chat_completion_reasoning_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("reasoning_content"), str):
        return str(message["reasoning_content"])
    return _chat_delta_reasoning_text(payload)


def _candidates_from_text(
    text: str,
    *,
    request: DeepSeekCompletionRequest,
    seen: set[str],
    started: float,
) -> Iterator[CompletionCandidateDelta]:
    for candidate in _parse_candidate_texts(text):
        if not _candidate_allowed(candidate, request=request, seen=seen):
            continue
        seen.add(candidate)
        yield CompletionCandidateDelta(
            text=candidate,
            insert_text=candidate,
            metadata={
                "scene": request.scene,
                "elapsedMs": int((time.perf_counter() - started) * 1000),
                "model": "deepseek_v4_flash",
                "parseMode": "content",
            },
        )


def _parse_candidate_line(line: str) -> str:
    candidates = _parse_candidate_texts(line)
    return candidates[0] if candidates else ""


def _parse_candidate_texts(text: str) -> list[str]:
    stripped = compact_whitespace(text)
    if not stripped:
        return []
    payload = _json_loads_or_none(_strip_markdown_fence(stripped))
    if payload is not None:
        return _candidate_texts_from_payload(payload)
    result: list[str] = []
    for line in stripped.splitlines():
        payload = _json_loads_or_none(_strip_markdown_fence(line))
        if payload is not None:
            result.extend(_candidate_texts_from_payload(payload))
    if result:
        return _unique_candidates(result)
    for payload in _json_values_in_text(stripped):
        result.extend(_candidate_texts_from_payload(payload))
    if result:
        return _unique_candidates(result)
    return _plain_candidate_texts(stripped)


def _plain_candidate_texts(text: str) -> list[str]:
    stripped = compact_whitespace(_strip_markdown_fence(text))
    if not stripped:
        return []
    match = re.match(r"^(?:候选|candidate|output|输出)\s*[=＝:：]\s*(?P<text>.+)$", stripped, flags=re.IGNORECASE)
    if match:
        stripped = compact_whitespace(match.group("text"))
    stripped = stripped.strip("\"'“”‘’").strip("。；;，, ")
    if not stripped or "\n" in stripped:
        return []
    if any(marker in stripped for marker in ("{", "}", "[", "]", "```")):
        return []
    return [stripped]


def _candidates_from_reasoning(
    reasoning: str,
    *,
    request: DeepSeekCompletionRequest,
    seen: set[str],
    started: float,
) -> Iterator[CompletionCandidateDelta]:
    for candidate in _candidate_texts_from_reasoning(reasoning):
        if not _candidate_allowed(candidate, request=request, seen=seen):
            continue
        seen.add(candidate)
        yield CompletionCandidateDelta(
            text=candidate,
            insert_text=candidate,
            metadata={
                "scene": request.scene,
                "elapsedMs": int((time.perf_counter() - started) * 1000),
                "model": "deepseek_v4_flash",
                "parseMode": "reasoning_fallback",
            },
        )


def _candidates_from_request_fallback(
    *,
    request: DeepSeekCompletionRequest,
    seen: set[str],
    started: float,
    fallback_reason: str = "empty_remote_content",
) -> Iterator[CompletionCandidateDelta]:
    limit = max(1, int(request.max_candidates))
    yielded = 0
    for candidate in _request_fallback_candidate_texts(request):
        if repeat_norm(candidate) == repeat_norm(request.selected_text):
            continue
        if not _candidate_allowed(candidate, request=request, seen=seen):
            continue
        seen.add(candidate)
        yielded += 1
        yield CompletionCandidateDelta(
            text=candidate,
            insert_text=candidate,
            metadata={
                "scene": request.scene,
                "elapsedMs": int((time.perf_counter() - started) * 1000),
                "model": "deepseek_v4_flash",
                "parseMode": "request_fallback",
                "fallbackReason": fallback_reason or "empty_remote_content",
            },
        )
        if yielded >= limit:
            break


def _request_fallback_candidate_texts(request: DeepSeekCompletionRequest) -> list[str]:
    max_chars = max(4, int(request.max_chars))
    selected = compact_whitespace(request.selected_text)
    request_text = compact_whitespace(" ".join([request.current_context, selected]))
    evidence_text = compact_whitespace(" ".join(_evidence_hint_texts(request.evidence_pack)))
    haystack = compact_whitespace(" ".join([request_text, evidence_text]))
    candidates: list[str] = []
    if "DeepSeek" in request_text and ("无输出" in request_text or "没输出" in request_text or "输出" in request_text):
        candidates.append("修复DeepSeek输出")
    if ("LLM" in request_text or "模型" in request_text) and (
        "无输出" in request_text or "没输出" in request_text or "输出" in request_text
    ):
        candidates.append("修复LLM输出")
    if ("LLM" in request_text or "模型" in request_text) and (
        "不显示" in request_text or "没显示" in request_text or "消失" in request_text
    ):
        candidates.append("修复LLM显示")
    if "RAG" in request_text and ("命中" in request_text or "检索" in request_text) and (
        "DeepSeek" in request_text or "DS" in request_text
    ):
        candidates.append("接入RAG上下文")
    if ("笔记本" in request_text or "Notebook" in request_text) and ("DeepSeek" in request_text or "DS" in request_text):
        candidates.append("接入记忆笔记本")
    if ("只有一个框" in request_text or "单框" in request_text) and ("候选" in request_text or "输出" in request_text):
        candidates.append("修复候选显示")
    if "记忆" in request_text and "笔记本" in request_text and ("初始化" in request_text or "整理" in request_text):
        candidates.append("初始化记忆笔记本")
    if "按钮" in request_text and "生成" in request_text and ("稳定" in request_text or "显示" in request_text):
        candidates.append("稳定生成按钮")
    if "DeepSeek" in request_text and "生成" in request_text and ("稳定" in request_text or "显示" in request_text):
        candidates.append("稳定DeepSeek生成")
    if "RAG" in request_text and "输入法" in request_text and ("面试" in request_text or "展示" in request_text):
        candidates.append("RAG 输入法面试展示主线")
    if "RAG" in request_text and "输入法" in request_text:
        candidates.append("RAG输入法优化")
    if selected:
        if selected.endswith("优化") and len(selected) > 2:
            candidates.append(f"{selected[:-2]}稳定化")
        for suffix in ("方案", "处理", "优化"):
            if not selected.endswith(suffix):
                candidates.append(f"{selected}{suffix}")
    return [item for item in _unique_candidates(candidates) if 2 <= len(item) <= max_chars]


def _evidence_hint_texts(evidence_pack: tuple[dict[str, object], ...]) -> list[str]:
    hints: list[str] = []
    for item in evidence_pack[:8]:
        for key in ("surfaceHints", "surface_hints", "tags"):
            raw_list = item.get(key)
            if isinstance(raw_list, (list, tuple)):
                hints.extend(compact_whitespace(str(value)) for value in raw_list if compact_whitespace(str(value)))
        for key in ("preview", "summary", "evidencePreview", "evidence_preview", "title"):
            value = compact_whitespace(str(item.get(key) or ""))
            if value:
                hints.append(value)
    return hints


def _candidate_texts_from_reasoning(reasoning: str) -> list[str]:
    text = compact_whitespace(reasoning)
    if not text:
        return []
    result: list[str] = []
    for payload in _json_values_in_text(text):
        result.extend(_candidate_texts_from_reasoning_payload(payload))
    result = [item for item in result if not _placeholder_candidate(item)]
    if result:
        return _unique_candidates(result)
    patterns = (
        r"(?:候选\s*[=＝]\s*)(?P<text>[^\"“”\n。；;，,]{2,40})",
        r"(?:我决定(?:生成|输出)|最终(?:选择|输出)|决定(?:生成|输出))\s*[\"“](?P<text>[^\"”]{2,40})[\"”]",
        r"(?:可能(?:的)?候选|候选(?:词)?|例如|比如|考虑用|考虑|可以是)[^\"“”]{0,24}[\"“](?P<text>[^\"”]{2,40})[\"”]",
        r"(?:候选(?:应该|可以)?(?:是|为|：|:)\s*[\"“]?)(?P<text>[^\"“”\n。；;，,]{2,40})",
        r"[\"“](?P<text>[^\"”]{2,40})[\"”]\s*(?:更好|符合|作为|是一个|本身|这个候选|是参考|比较合适)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = compact_whitespace(match.group("text"))
            if value and not _placeholder_candidate(value):
                result.append(value)
    return _unique_candidates(result)


def _placeholder_candidate(text: str) -> bool:
    value = compact_whitespace(text)
    return value in {
        "短候选",
        "候选",
        "短语",
        "比如",
        "例如",
        "phrase",
        "candidate",
        "短候选词",
        "候选=",
        "候选＝",
        "<候选内容>",
        "候选内容",
        "你生成的实际候选",
        "你的候选",
        "真实候选",
        "实际候选内容",
        "实际候选",
        "最终候选文本",
        "某个具体候选",
        "具体短语",
        "XXX",
        "xxx",
    }


def _generic_prompt_candidate(text: str) -> bool:
    value = compact_whitespace(text)
    if any(marker in value for marker in ("候选短语", "候选内容", "候选文本", "直接插入")):
        return True
    if value.count("候选") >= 2 or "候选的" in value:
        return True
    return value.startswith("的") and any(marker in value for marker in ("候选", "短语", "内容", "文本"))


def _candidate_texts_from_reasoning_payload(payload: object) -> list[str]:
    if isinstance(payload, list):
        result: list[str] = []
        for item in payload:
            if isinstance(item, (dict, list)):
                result.extend(_candidate_texts_from_reasoning_payload(item))
        return result
    if not isinstance(payload, dict):
        return []
    candidate_keys = ("candidate", "surfaceText", "surface_text", "text", "insertText", "insert_text")
    if "candidates" in payload or any(key in payload for key in candidate_keys):
        return _candidate_texts_from_payload(payload)
    return []


def _candidate_texts_from_payload(payload: object) -> list[str]:
    if isinstance(payload, str):
        return [compact_whitespace(payload)] if compact_whitespace(payload) else []
    if isinstance(payload, list):
        result: list[str] = []
        for item in payload:
            result.extend(_candidate_texts_from_payload(item))
        return result
    if not isinstance(payload, dict):
        return []
    result: list[str] = []
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for item in candidates:
            result.extend(_candidate_texts_from_payload(item))
    for key in ("candidate", "surfaceText", "surface_text", "text", "insertText", "insert_text"):
        value = compact_whitespace(str(payload.get(key) or ""))
        if value:
            result.append(value)
            break
    return result


def _json_loads_or_none(text: str) -> object | None:
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _json_values_in_text(text: str) -> list[object]:
    decoder = json.JSONDecoder()
    values: list[object] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] not in "[{":
            index += 1
        if index >= len(text):
            break
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        values.append(value)
        index += max(1, end)
    return values


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json|JSON|jsonl|JSONL)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _unique_candidates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = compact_whitespace(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _completion_token_budget(request: DeepSeekCompletionRequest) -> int:
    max_chars = max(4, int(request.max_chars))
    max_candidates = max(1, int(request.max_candidates))
    if request.scene == "editor":
        base = 80
        cap = 256
    elif request.scene == "active_rag":
        # Active RAG is explicit user-triggered generation. The current V4 Flash
        # gateway streams substantial reasoning_content before content, so this
        # lane needs a larger budget than the per-key/post-commit hot path.
        return 1024
    else:
        base = 16
        cap = 96
    per_candidate = max(24, min(64, max_chars * 2 + 12))
    return max(32, min(cap, base + max_candidates * per_candidate))


def _configured_completion_token_cap(config: DeepSeekConfig, request: DeepSeekCompletionRequest) -> int:
    if request.scene == "active_rag":
        return max(128, int(getattr(config, "active_rag_max_tokens", 1024) or 1024))
    return max(16, int(config.max_tokens))


def _reasoning_fallback_enabled(request: DeepSeekCompletionRequest) -> bool:
    return request.scene in {"active_rag", "post_commit"}


def _candidate_allowed(candidate: str, *, request: DeepSeekCompletionRequest, seen: set[str]) -> bool:
    text = compact_whitespace(candidate)
    if not text or text in seen:
        return False
    if len(text) < 2 or len(text) > max(4, int(request.max_chars)):
        return False
    if _placeholder_candidate(text):
        return False
    if _generic_prompt_candidate(text):
        return False
    if _has_unapproved_ascii_word(text):
        return False
    if text.isascii() and any(char.isalpha() for char in text):
        return False
    if _bad_reasoning_fragment(text):
        return False
    if candidate_has_self_repetition(text):
        return False
    if candidate_has_keyword_echo(text):
        return False
    lowered = text.lower()
    if any(marker in text for marker in ("selectedText", "currentContext", "evidenceHints", "maxCandidates", "maxChars")):
        return False
    if any(marker in text for marker in ("下一步", "接下来", "根据上述", "可以进行", "可以继续")):
        return False
    if "json" in lowered or "markdown" in lowered or "输入法候选生成器" in text:
        return False
    active_rag_allows_keyword_reuse = request.scene == "active_rag"
    context = compact_whitespace(f"{request.current_context} {request.selected_text}")
    if candidate_echoes_text(
        text,
        context,
        reject_tail=not active_rag_allows_keyword_reuse,
        reject_single_occurrence=not active_rag_allows_keyword_reuse,
    ):
        return False
    for item in request.evidence_pack:
        if _candidate_echoes_evidence_item(
            text,
            item,
            reject_tail=not active_rag_allows_keyword_reuse,
            reject_single_occurrence=not active_rag_allows_keyword_reuse,
        ):
            return False
    return True


def _bad_reasoning_fragment(text: str) -> bool:
    value = compact_whitespace(text)
    if not value:
        return True
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "notebook",
            "contextpacket",
            "currentinput",
            "onering",
            "timeline",
            "selectedtext",
            "outputcontract",
            "evidence",
            "surfacehint",
        )
    ):
        return True
    if re.search(r"[:：]\s*\d", value):
        return True
    if value.startswith(("-", "•", "*")):
        return True
    if any(marker in value for marker in ("。", "；", "用户", "主题", "所以", "因为", "意思是", "说明", "输入是")):
        return True
    if ("证据" in value or "笔记本" in value or "候选" in value) and ("有" in value and ("条" in value or "个" in value)):
        return True
    if value[0] in "，。；：、,.!?！？;:)]}）】":
        return True
    normalized = repeat_norm(value)
    if len(normalized) < 2:
        return True
    return normalized in {
        "所以",
        "但是",
        "因为",
        "因此",
        "然后",
        "这里",
        "我们",
        "这个",
        "也可以",
        "可以是",
    }


def _has_unapproved_ascii_word(text: str) -> bool:
    allowed = {"llm", "rag", "deepseek", "ds", "bm25", "kv", "api", "mlx", "tagmemo", "daily", "book"}
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text):
        if word.lower() not in allowed:
            return True
    return False


def _candidate_echoes_evidence_item(
    candidate: str,
    item: dict[str, object],
    *,
    reject_tail: bool = True,
    reject_single_occurrence: bool = True,
) -> bool:
    evidence_texts: list[str] = []
    for key in ("rawText", "raw_text", "text", "candidateText", "evidencePreview", "evidence_preview", "summary", "preview"):
        value = compact_whitespace(str(item.get(key) or ""))
        if value:
            evidence_texts.append(value)
    for key in ("surfaceHints", "surface_hints"):
        raw_list = item.get(key)
        if isinstance(raw_list, (list, tuple)):
            evidence_texts.extend(compact_whitespace(str(value)) for value in raw_list if compact_whitespace(str(value)))
    return any(
        candidate_echoes_text(candidate, text, reject_tail=reject_tail, reject_single_occurrence=reject_single_occurrence)
        for text in evidence_texts
    )


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


def _redacted_context_packet(packet: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(packet, dict):
        return {}
    return _redact_json_value(packet, max_depth=5)


def _redact_json_value(value: object, *, max_depth: int) -> object:
    if max_depth <= 0:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return truncate_text(_redact_text(value), 240)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_redact_json_value(item, max_depth=max_depth - 1) for item in value[:12]]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in list(value.items())[:32]:
            key_text = compact_whitespace(str(key))
            if key_text in {"rawText", "raw_text", "wholeValue", "whole_value"}:
                continue
            result[key_text] = _redact_json_value(item, max_depth=max_depth - 1)
        return result
    return truncate_text(_redact_text(str(value)), 120)


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
