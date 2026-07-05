from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import ModelPrediction
from .pinyin_index import build_pinyin_metadata
from .text_utils import compact_whitespace


PREDICTION_REQUEST_NO_INPUT = "no_input_prediction"
PREDICTION_REQUEST_PINYIN_CONSTRAINED = "pinyin_constrained_prediction"
PREDICTION_REQUEST_RIME_REORDER = "rime_reorder"
PREDICTION_REQUEST_GENERIC = "generic_prediction"

OPENAI_CHAT_SYSTEM_PROMPT = (
    "你是一个本地中文输入法预测器。只输出候选词或短语, "
    "候选之间用单个空格分隔, 不要解释, 不要编号。"
)

OLLAMA_CHAT_SYSTEM_PROMPT = (
    "你是中文输入法续写候选预测器。只输出 JSON 字符串数组, "
    '例如 ["候选展示","RAG候选","历史上下文"], 不要重复当前输入, 不要解释。'
)

OLLAMA_STREAM_FIRST_SYSTEM_PROMPT = (
    "你是中文输入法续写候选预测器。只输出一个最可能接在当前输入后面的候选词或短语, "
    "不要重复当前输入, 不要 JSON, 不要编号, 不要解释, 输出后停止。"
)

MLX_STABLE_PREFIX = f"{OLLAMA_CHAT_SYSTEM_PROMPT}\n"
_LOW_VALUE_IME_CANDIDATES = {
    "啊",
    "阿",
    "测试",
    "测试流程",
    "分析",
    "分析问题",
    "验证",
    "并且",
    "但是",
    "呃",
    "嗯",
    "额",
    "或者",
    "基于",
    "根据",
    "生成",
    "假设",
    "接入",
    "记忆",
    "模型",
    "需要",
    "接下来",
    "输入法",
    "呐",
    "然后",
    "同时",
    "现在",
    "目前",
    "当前",
    "当前问题",
    "当前流程",
    "当前拼音或参考候选",
    "直接输出",
    "模型相关表达",
    "调试",
    "调试流程",
    "上屏",
    "上屏文字",
    "已上屏",
    "已上屏文本",
    "已上屏上下文",
    "下一步",
    "接龙",
    "把流程跑通",
    "接入本地",
    "接入本地记忆",
    "验证 LLM 候选",
    "验证LLM候选",
    "预测流程完成",
    "部署 RAG 组件",
    "部署RAG组件",
    "继续预测",
    "预测流程",
    "的",
    "了",
    "和",
    "是",
    "候选",
    "后文候选",
    "输入法候选",
    "模型候选",
    "记忆候选",
    "RAG候选",
    "LLM候选",
    "candidate",
    "candidates",
    "cand",
    "预测",
    "RAG",
    "rag",
    "LLM",
    "llm",
    "好的",
    "可以",
    "没问题",
    "候选如下",
    "以下是",
    "以下是候选",
    "给出候选",
}
_CONTINUATION_PREFERRED_LENGTHS = (2, 4, 6, 8, 12, 16, 20, 24)


class PredictionProvider(Protocol):
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        ...


@dataclass(frozen=True)
class OpenAICompatiblePredictionConfig:
    base_url: str
    model: str
    api_key: str = ""
    profile: str = "custom"
    prompt_mode: str = "chat"
    timeout_s: float = 0.8
    max_tokens: int = 12
    temperature: float = 0.2
    top_p: float = 0.9
    provider_name: str = "local-openai-compatible"
    extra_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None


@dataclass(frozen=True)
class OllamaPredictionConfig:
    base_url: str
    model: str
    profile: str = "custom"
    prompt_mode: str = "ollama-chat"
    timeout_s: float = 0.8
    max_tokens: int = 12
    temperature: float = 0.2
    top_p: float = 0.9
    provider_name: str = "local-ollama"
    extra_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None
    stream_first_candidate: bool = False


@dataclass(frozen=True)
class MlxPredictionConfig:
    base_url: str
    model: str
    profile: str = "custom"
    prompt_mode: str = "mlx-service"
    timeout_s: float = 0.8
    max_tokens: int = 24
    temperature: float = 0.15
    top_p: float = 0.85
    provider_name: str = "local-mlx"
    extra_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None
    stream_first_candidate: bool = False


@dataclass(frozen=True)
class PredictionBenchmarkCase:
    current_input: str
    recent_context: str = ""
    case_id: str = ""


@dataclass(frozen=True)
class PredictionProfileDefaults:
    prompt_mode: str = "chat"
    timeout_ms: float = 800
    max_tokens: int = 12
    temperature: float = 0.2
    top_p: float = 0.9
    disable_thinking: bool = False


@dataclass
class PredictionCooldownState:
    failure_count: int = 0
    skipped_count: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""
    last_failure_elapsed_ms: int = 0


class NullPredictionProvider:
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        _ = request_type, rime_candidates
        return []


class OpenAICompatiblePredictionProvider:
    """Fast local LLM prediction lane, inspired by Wisdom-Weasel's provider boundary.

    This provider intentionally asks for very short candidates and uses an
    aggressive timeout. A slow model must fail open so typing stays responsive.
    """

    def __init__(self, config: OpenAICompatiblePredictionConfig):
        self.config = config
        self.last_error = ""

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        resolved_request_type = normalize_prediction_request_type(request_type)
        rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
        max_items = max(1, min(10, int(max_candidates)))
        request_meta = _prediction_request_metadata(
            context=context,
            query=query,
            stable_prefix=_openai_stable_prefix_for_request(self.config.prompt_mode, resolved_request_type),
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        )
        self.last_error = ""
        started = time.perf_counter()
        raw_texts = self._complete(
            context=context,
            query=query,
            max_candidates=max_items,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_text = "\n".join(raw_texts)
        if resolved_request_type == PREDICTION_REQUEST_GENERIC:
            candidates = _parse_prediction_candidate_texts(raw_texts, max_candidates=max_items)
            candidates = _finalize_ime_prediction_candidates(candidates, query)
        else:
            candidates = parse_ime_prediction_candidates(
                raw_texts,
                max_candidates=max_items,
                current_input=query,
                recent_context=context,
                request_type=resolved_request_type,
                rime_candidates=rime_candidate_tuple,
            )
        return [
            ModelPrediction(
                text=item,
                rank=index,
                provider_name=self.config.provider_name,
                latency_ms=latency_ms,
                confidence=max(0.0, min(1.0, 1.0 - (index - 1) * 0.08)),
                        metadata={
                            "model": self.config.model,
                            "base_url": self.config.base_url,
                            "profile": self.config.profile,
                            "prompt_mode": _normalized_prompt_mode(self.config.prompt_mode),
                            "raw_text": raw_text,
                            "request_type": resolved_request_type,
                            "rime_candidates": list(rime_candidate_tuple),
                            "requestMeta": request_meta,
                            **build_pinyin_metadata(item),
                        },
                    )
            for index, item in enumerate(candidates, start=1)
        ]

    def _complete(
        self,
        *,
        context: str,
        query: str,
        max_candidates: int,
        request_type: str,
        rime_candidates: tuple[str, ...],
    ) -> list[str]:
        if _normalized_prompt_mode(self.config.prompt_mode) == "completion":
            return self._complete_with_prefix(
                context=context,
                query=query,
                max_candidates=max_candidates,
                request_type=request_type,
                rime_candidates=rime_candidates,
            )
        return self._complete_with_chat(
            context=context,
            query=query,
            max_candidates=max_candidates,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )

    def _complete_with_chat(
        self,
        *,
        context: str,
        query: str,
        max_candidates: int,
        request_type: str,
        rime_candidates: tuple[str, ...],
    ) -> list[str]:
        system_prompt = _openai_prediction_system_prompt(request_type)
        user_content = _openai_prediction_user_content(
            context=context,
            query=query,
            max_candidates=max_candidates,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )
        body = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "max_tokens": max(1, min(64, int(self.config.max_tokens))),
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "stream": False,
        }
        if self.config.extra_body:
            body.update(self.config.extra_body)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            self.last_error = _prediction_error_name(exc)
            return []
        return extract_openai_contents(payload)

    def _complete_with_prefix(
        self,
        *,
        context: str,
        query: str,
        max_candidates: int,
        request_type: str,
        rime_candidates: tuple[str, ...],
    ) -> list[str]:
        prefix = _openai_completion_prefix(
            context=context,
            query=query,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )
        if not prefix:
            return []
        body = {
            "model": self.config.model,
            "prompt": prefix,
            "max_tokens": max(1, min(64, int(self.config.max_tokens))),
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "stream": False,
            "n": max(1, min(10, int(max_candidates))),
        }
        if self.config.extra_body:
            body.update(self.config.extra_body)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/v1/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            self.last_error = _prediction_error_name(exc)
            return []
        return extract_openai_contents(payload)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers


class OllamaPredictionProvider:
    """Ollama-native prediction lane.

    Ollama's OpenAI-compatible endpoint can keep Qwen thinking output separate
    from normal content. The native chat API exposes `think: false`, which is a
    better fit for IME latency and candidate parsing.
    """

    def __init__(self, config: OllamaPredictionConfig):
        self.config = config
        self.last_error = ""

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        _ = request_type, rime_candidates
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        max_items = max(1, min(10, int(max_candidates)))
        stable_prefix = OLLAMA_STREAM_FIRST_SYSTEM_PROMPT if self.config.stream_first_candidate else OLLAMA_CHAT_SYSTEM_PROMPT
        request_meta = _prediction_request_metadata(
            context=context,
            query=query,
            stable_prefix=stable_prefix,
        )
        self.last_error = ""
        started = time.perf_counter()
        if self.config.stream_first_candidate:
            streamed = self._stream_first_candidate(context=context, query=query, max_candidates=max_items)
            if streamed:
                latency_ms = int((time.perf_counter() - started) * 1000)
                return [
                    ModelPrediction(
                        text=streamed["candidate"],
                        rank=1,
                        provider_name=self.config.provider_name,
                        latency_ms=latency_ms,
                        confidence=1.0,
                        metadata={
                            "model": self.config.model,
                            "base_url": self.config.base_url,
                            "profile": self.config.profile,
                            "prompt_mode": self.config.prompt_mode,
                            "raw_text": streamed["raw_text"],
                            "stream_first_candidate": True,
                            "first_candidate_ms": streamed["first_candidate_ms"],
                            "requestMeta": request_meta,
                            **build_pinyin_metadata(streamed["candidate"]),
                        },
                    )
                ]
        raw_texts = self._complete(context=context, query=query, max_candidates=max_items)
        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_text = "\n".join(raw_texts)
        candidates = _parse_prediction_candidate_texts(raw_texts, max_candidates=max_items)
        candidates = _finalize_ime_prediction_candidates(candidates, query)
        return [
            ModelPrediction(
                text=item,
                rank=index,
                provider_name=self.config.provider_name,
                latency_ms=latency_ms,
                confidence=max(0.0, min(1.0, 1.0 - (index - 1) * 0.08)),
                metadata={
                    "model": self.config.model,
                    "base_url": self.config.base_url,
                    "profile": self.config.profile,
                    "prompt_mode": self.config.prompt_mode,
                    "raw_text": raw_text,
                    "requestMeta": request_meta,
                    **build_pinyin_metadata(item),
                },
            )
            for index, item in enumerate(candidates, start=1)
        ]

    def _complete(self, *, context: str, query: str, max_candidates: int) -> list[str]:
        body = _ollama_chat_body(self.config, context=context, query=query, max_candidates=max_candidates, stream=False)
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            self.last_error = _prediction_error_name(exc)
            return []
        return extract_ollama_contents(payload)

    def _stream_first_candidate(self, *, context: str, query: str, max_candidates: int) -> dict[str, Any]:
        measured = _measure_ollama_stream_ttft(
            self.config,
            current_input=query,
            recent_context=context,
            max_candidates=max_candidates,
            keep_alive=-1,
            stop_after_first_candidate=True,
        )
        if not measured.get("ok"):
            self.last_error = str(measured.get("error") or "")
            return {}
        candidates = measured.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return {}
        first = str(candidates[0]).strip()
        if not first:
            return {}
        return {
            "candidate": first,
            "raw_text": str(measured.get("rawText") or ""),
            "first_candidate_ms": int(measured.get("firstCandidateMs") or measured.get("firstChunkMs") or 0),
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers


class MlxPredictionServiceProvider:
    """Client for the resident MLX-LM sidecar.

    The MLX path is intentionally separate from OpenAI-compatible chat. The
    service owns the loaded model and can stream first text immediately, while
    this client keeps the same fail-open PredictionProvider contract used by
    the IME sidecar.
    """

    def __init__(self, config: MlxPredictionConfig):
        self.config = config
        self.last_error = ""

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        resolved_request_type = normalize_prediction_request_type(request_type)
        rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
        max_items = max(1, min(10, int(max_candidates)))
        request_meta = _prediction_request_metadata(
            context=context,
            query=query,
            stable_prefix=MLX_STABLE_PREFIX,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        )
        self.last_error = ""
        started = time.perf_counter()
        if self.config.stream_first_candidate:
            streamed = self._stream_first_candidate(
                context=context,
                query=query,
                max_candidates=max_items,
                request_type=resolved_request_type,
                rime_candidates=rime_candidate_tuple,
            )
            if not streamed:
                return []
            streamed_candidates = _finalize_ime_prediction_candidates([streamed["candidate"]], query)
            if not streamed_candidates:
                return []
            streamed_candidate = streamed_candidates[0]
            latency_ms = int((time.perf_counter() - started) * 1000)
            return [
                ModelPrediction(
                    text=streamed_candidate,
                    rank=1,
                    provider_name=self.config.provider_name,
                    latency_ms=latency_ms,
                    confidence=1.0,
                    metadata={
                        "model": self.config.model,
                        "base_url": self.config.base_url,
                        "profile": self.config.profile,
                        "prompt_mode": self.config.prompt_mode,
                        "raw_text": streamed["raw_text"],
                        "stream_first_candidate": True,
                        "first_candidate_ms": streamed["first_candidate_ms"],
                        "prompt_cache": streamed.get("prompt_cache", {}),
                        "server_timing": streamed.get("server_timing", {}),
                        "request_type": resolved_request_type,
                        "rime_candidates": list(rime_candidate_tuple),
                        "requestMeta": request_meta,
                        **build_pinyin_metadata(streamed_candidate),
                    },
                )
            ]
        payload = self._predict_payload(
            context=context,
            query=query,
            max_candidates=max_items,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        )
        wall_ms = int((time.perf_counter() - started) * 1000)
        if not payload:
            return []
        latency_ms = _int_from_payload(payload.get("totalMs"), wall_ms)
        raw_texts = _mlx_raw_texts_from_payload(payload)
        payload_candidates = _candidate_parts_from_json_value(payload.get("candidates"))
        if payload_candidates:
            candidates = _finalize_ime_prediction_candidates(
                _parse_prediction_candidate_texts(payload_candidates, max_candidates=max_items),
                query,
            )[:max_items]
        else:
            candidates = parse_ime_prediction_candidates(
                raw_texts,
                max_candidates=max_items,
                current_input=query,
                recent_context=context,
                request_type=str(payload.get("requestType") or resolved_request_type),
                rime_candidates=rime_candidate_tuple,
            )
        return [
            ModelPrediction(
                text=item,
                rank=index,
                provider_name=self.config.provider_name,
                latency_ms=latency_ms,
                confidence=max(0.0, min(1.0, 1.0 - (index - 1) * 0.08)),
                metadata={
                    "model": self.config.model,
                    "base_url": self.config.base_url,
                    "profile": self.config.profile,
                    "prompt_mode": self.config.prompt_mode,
                    "raw_text": "\n".join(raw_texts),
                    "candidate_mode": str(payload.get("candidateMode") or ""),
                    "candidate_scores": payload.get("candidateScores", []),
                    "prompt_cache": payload.get("promptCache", {}),
                    "server_timing": payload.get("timing", {}),
                    "request_type": str(payload.get("requestType") or resolved_request_type),
                    "rime_candidates": list(rime_candidate_tuple),
                    "requestMeta": request_meta,
                    **build_pinyin_metadata(item),
                },
            )
            for index, item in enumerate(candidates, start=1)
        ]

    def _predict_payload(
        self,
        *,
        context: str,
        query: str,
        max_candidates: int,
        request_type: str,
        rime_candidates: tuple[str, ...],
    ) -> dict[str, Any]:
        body = _mlx_predict_body(
            self.config,
            context=context,
            query=query,
            max_candidates=max_candidates,
            stream=False,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/predict",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            self.last_error = _prediction_error_name(exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _stream_first_candidate(
        self,
        *,
        context: str,
        query: str,
        max_candidates: int,
        request_type: str,
        rime_candidates: tuple[str, ...],
    ) -> dict[str, Any]:
        measured = _measure_mlx_stream_ttft(
            self.config,
            current_input=query,
            recent_context=context,
            max_candidates=max_candidates,
            stop_after_first_candidate=True,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )
        if not measured.get("ok"):
            self.last_error = str(measured.get("error") or "")
            return {}
        candidates = measured.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return {}
        first = str(candidates[0]).strip()
        if not first:
            return {}
        return {
            "candidate": first,
            "raw_text": str(measured.get("rawText") or ""),
            "first_candidate_ms": int(measured.get("firstCandidateMs") or measured.get("firstChunkMs") or 0),
            "prompt_cache": measured.get("promptCache", {}),
            "server_timing": measured.get("serverTiming", {}),
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    def capability_probe(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/health",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(max(self.config.timeout_s, 0.05), 1.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            return {
                "ok": False,
                "error": _prediction_error_name(exc),
                "providerName": self.config.provider_name,
            }
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "error": "invalid_health_payload",
                "providerName": self.config.provider_name,
            }
        prompt_cache = payload.get("promptCache") if isinstance(payload.get("promptCache"), dict) else {}
        model_info = payload.get("modelInfo") if isinstance(payload.get("modelInfo"), dict) else {}
        health_capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
        capabilities = _prediction_provider_capabilities(self.config.provider_name)
        capabilities.update(
            {
                "streaming": bool(health_capabilities.get("streaming", capabilities["streaming"])),
                "residentModel": bool(payload.get("modelLoaded")),
                "promptCache": _prompt_cache_used_for_generation(prompt_cache),
                "textOnlyModel": bool(health_capabilities.get("textOnlyModel", model_info.get("textOnly", False))),
                "sequenceFork": bool(health_capabilities.get("sequenceFork")),
                "batchCandidates": bool(health_capabilities.get("batchCandidates")),
                "serverTiming": bool(health_capabilities.get("serverTiming", capabilities["serverTiming"])),
            }
        )
        return {
            "ok": bool(payload.get("ok")),
            "providerName": self.config.provider_name,
            "provider": payload.get("provider"),
            "model": payload.get("model"),
            "modelLoaded": bool(payload.get("modelLoaded")),
            "modelInfo": model_info,
            "promptCache": prompt_cache,
            "capabilities": capabilities,
        }


class CooldownPredictionProvider:
    """Circuit breaker for the IME model lane.

    The OpenAI-compatible provider already fails open, but a dead endpoint can
    still cost one timeout per composing refresh. This wrapper skips temporary
    repeat calls after transport failures; empty-but-successful generations are
    allowed to recover on the next request because small local models can be
    noisy without being down.
    """

    def __init__(
        self,
        delegate: PredictionProvider,
        *,
        cooldown_ms: int = 5000,
        failure_latency_ms: int = 250,
    ):
        self.delegate = delegate
        self.cooldown_ms = max(0, int(cooldown_ms))
        self.failure_latency_ms = max(1, int(failure_latency_ms))
        self._state = PredictionCooldownState()

    @property
    def config(self) -> Any:
        return getattr(self.delegate, "config", None)

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[ModelPrediction]:
        now = time.perf_counter()
        if self.cooldown_ms > 0 and now < self._state.cooldown_until:
            self._state.skipped_count += 1
            return []

        started = time.perf_counter()
        predictions = predict_with_optional_request_context(
            self.delegate,
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        delegate_error = str(getattr(self.delegate, "last_error", "") or "")
        failed_transport = bool(delegate_error)
        if failed_transport:
            self._state.failure_count += 1
            self._state.last_error = delegate_error
            self._state.last_failure_elapsed_ms = elapsed_ms
            if self.cooldown_ms > 0:
                self._state.cooldown_until = time.perf_counter() + self.cooldown_ms / 1000.0
        elif predictions:
            self._state.failure_count = 0
            self._state.last_error = ""
            self._state.last_failure_elapsed_ms = 0
            self._state.cooldown_until = 0.0
        return predictions

    def cooldown_status(self) -> dict[str, object]:
        now = time.perf_counter()
        remaining_ms = max(0, int((self._state.cooldown_until - now) * 1000))
        return {
            "enabled": self.cooldown_ms > 0,
            "cooldownMs": self.cooldown_ms,
            "failureLatencyMs": self.failure_latency_ms,
            "active": remaining_ms > 0,
            "remainingMs": remaining_ms,
            "failureCount": self._state.failure_count,
            "skippedCount": self._state.skipped_count,
            "lastError": self._state.last_error,
            "lastFailureElapsedMs": self._state.last_failure_elapsed_ms,
        }

    def capability_probe(self) -> dict[str, Any]:
        capability_probe = getattr(self.delegate, "capability_probe", None)
        if not callable(capability_probe):
            return {
                "ok": False,
                "error": "capability_probe_not_supported",
                "providerName": getattr(self.config, "provider_name", self.delegate.__class__.__name__),
            }
        return capability_probe()


def prediction_provider_from_env(env: dict[str, str] | None = None) -> PredictionProvider:
    source = _prediction_env_with_predictor_file(env)
    provider = (
        source.get("RAG_IME_PREDICTOR_PROVIDER", "").strip().lower()
        or source.get("RAG_IME_AI_PROVIDER", "").strip().lower()
    )
    base_url = _canonical_x1api_base_url(
        source.get("RAG_IME_PREDICTOR_BASE_URL", "").strip()
        or source.get("RAG_IME_AI_BASE_URL", "").strip()
        or source.get("X1API_BASE_URL", "").strip()
        or source.get("API_BASE_URL", "").strip()
    )
    model = (
        source.get("RAG_IME_PREDICTOR_MODEL", "").strip()
        or source.get("RAG_IME_AI_MODEL", "").strip()
        or source.get("X1API_MODEL", "").strip()
        or source.get("MODEL", "").strip()
        or source.get("RAG_IME_MLX_MODEL", "").strip()
    )
    if not provider and base_url and model:
        provider = "openai-compatible"
    if provider == "ollama" and not base_url:
        base_url = "http://127.0.0.1:11434"
    if provider in {"mlx", "mlx-lm", "mlx-service"} and not base_url:
        base_url = "http://127.0.0.1:8767"
    if provider not in ("openai", "openai-compatible", "ollama", "mlx", "mlx-lm", "mlx-service") or not base_url or not model:
        return NullPredictionProvider()
    profile = _normalized_predictor_profile(source.get("RAG_IME_PREDICTOR_PROFILE", "custom"))
    defaults = _prediction_profile_defaults(profile)
    if provider == "ollama":
        configured_provider: PredictionProvider = OllamaPredictionProvider(
            OllamaPredictionConfig(
                base_url=_ollama_base_url(base_url),
                model=model,
                profile=profile,
                timeout_s=_float_env(source, "RAG_IME_PREDICTOR_TIMEOUT_MS", defaults.timeout_ms) / 1000,
                max_tokens=int(_float_env(source, "RAG_IME_PREDICTOR_MAX_TOKENS", max(24, defaults.max_tokens))),
                temperature=_float_env(source, "RAG_IME_PREDICTOR_TEMPERATURE", defaults.temperature),
                top_p=_float_env(source, "RAG_IME_PREDICTOR_TOP_P", defaults.top_p),
                provider_name="local-ollama",
                extra_body=_json_object_env(source, "RAG_IME_PREDICTOR_EXTRA_BODY_JSON"),
                extra_headers=_json_string_map_env(source, "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON"),
                stream_first_candidate=_bool_env(source, "RAG_IME_PREDICTOR_STREAM_FIRST", default=False),
            )
        )
    elif provider in {"mlx", "mlx-lm", "mlx-service"}:
        configured_provider = MlxPredictionServiceProvider(
            MlxPredictionConfig(
                base_url=base_url.rstrip("/"),
                model=model,
                profile=profile,
                timeout_s=_float_env(source, "RAG_IME_PREDICTOR_TIMEOUT_MS", defaults.timeout_ms) / 1000,
                max_tokens=int(_float_env(source, "RAG_IME_PREDICTOR_MAX_TOKENS", max(24, defaults.max_tokens))),
                temperature=_float_env(source, "RAG_IME_PREDICTOR_TEMPERATURE", defaults.temperature),
                top_p=_float_env(source, "RAG_IME_PREDICTOR_TOP_P", defaults.top_p),
                provider_name="local-mlx",
                extra_body=_json_object_env(source, "RAG_IME_PREDICTOR_EXTRA_BODY_JSON"),
                extra_headers=_json_string_map_env(source, "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON"),
                stream_first_candidate=_bool_env(source, "RAG_IME_PREDICTOR_STREAM_FIRST", default=False),
            )
        )
    else:
        configured_provider = OpenAICompatiblePredictionProvider(
            OpenAICompatiblePredictionConfig(
            base_url=base_url,
            model=model,
            api_key=(
                source.get("RAG_IME_PREDICTOR_API_KEY", "").strip()
                or source.get("RAG_IME_AI_API_KEY", "").strip()
                or source.get("X1API_API_KEY", "").strip()
                or source.get("API_KEY", "").strip()
            ),
            profile=profile,
            prompt_mode=source.get("RAG_IME_PREDICTOR_PROMPT_MODE", defaults.prompt_mode).strip(),
            timeout_s=_float_env(source, "RAG_IME_PREDICTOR_TIMEOUT_MS", defaults.timeout_ms) / 1000,
            max_tokens=int(_float_env(source, "RAG_IME_PREDICTOR_MAX_TOKENS", defaults.max_tokens)),
            temperature=_float_env(source, "RAG_IME_PREDICTOR_TEMPERATURE", defaults.temperature),
            top_p=_float_env(source, "RAG_IME_PREDICTOR_TOP_P", defaults.top_p),
            provider_name="local-openai-compatible",
            extra_body=_prediction_extra_body_from_env(source, disable_thinking_default=defaults.disable_thinking),
            extra_headers=_json_string_map_env(source, "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON"),
            )
        )
    cooldown_ms = int(_non_negative_float_env(source, "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS", 5000))
    if cooldown_ms <= 0:
        return configured_provider
    return CooldownPredictionProvider(
        configured_provider,
        cooldown_ms=cooldown_ms,
        failure_latency_ms=int(_float_env(source, "RAG_IME_PREDICTOR_FAILURE_LATENCY_MS", 250)),
    )


def _prediction_env_with_predictor_file(env: dict[str, str] | None) -> dict[str, str]:
    source = dict(os.environ if env is None else env)
    env_path = (
        source.get("RAG_IME_PREDICTOR_ENV", "").strip()
        or source.get("RAG_IME_MODEL_ENV", "").strip()
        or source.get("RAG_IME_X1API_ENV", "").strip()
    )
    if not env_path:
        return source
    path = Path(env_path).expanduser()
    if not path.exists():
        return source
    file_values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        file_values[key.strip()] = value.strip().strip('"').strip("'")
    merged = {**file_values, **source}
    for key in ("RAG_IME_PREDICTOR_BASE_URL", "RAG_IME_AI_BASE_URL", "X1API_BASE_URL", "API_BASE_URL"):
        if merged.get(key):
            merged[key] = _canonical_x1api_base_url(str(merged[key]))
    return merged


def _canonical_x1api_base_url(value: str) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return ""
    parsed = urllib.parse.urlsplit(cleaned)
    netloc = parsed.netloc.lower()
    if netloc not in {"x1api.top", "x2app.top"}:
        return cleaned
    path = parsed.path.rstrip("/")
    if path == "/v1":
        path = ""
    return urllib.parse.urlunsplit((parsed.scheme or "https", "x1api.top", path, parsed.query, parsed.fragment))


def prediction_provider_status(provider: PredictionProvider, *, probe_capabilities: bool = False) -> dict[str, object]:
    config = getattr(provider, "config", None)
    configured = provider.__class__.__name__ != "NullPredictionProvider"
    if config is None:
        provider_name = provider.__class__.__name__
        return {
            "configured": configured,
            "providerName": provider_name,
            "providerProfile": "none",
            "promptMode": "none",
            "capabilities": _prediction_provider_capabilities(provider_name),
        }
    extra_body = getattr(config, "extra_body", None) or {}
    extra_headers = getattr(config, "extra_headers", None) or {}
    status = {
        "configured": configured,
        "providerName": getattr(config, "provider_name", "") or provider.__class__.__name__,
        "providerProfile": getattr(config, "profile", "") or "custom",
        "promptMode": _status_prompt_mode(str(getattr(config, "prompt_mode", ""))),
        "baseUrl": getattr(config, "base_url", ""),
        "model": getattr(config, "model", ""),
        "timeoutMs": int(float(getattr(config, "timeout_s", 0.0)) * 1000),
        "maxTokens": int(getattr(config, "max_tokens", 0)),
        "temperature": float(getattr(config, "temperature", 0.0)),
        "topP": float(getattr(config, "top_p", 0.0)),
        "extraBodyKeys": sorted(str(key) for key in extra_body.keys()) if isinstance(extra_body, dict) else [],
        "extraHeaderKeys": sorted(str(key) for key in extra_headers.keys()) if isinstance(extra_headers, dict) else [],
        "streamFirstCandidate": bool(getattr(config, "stream_first_candidate", False)),
    }
    status["capabilities"] = _prediction_provider_capabilities(str(status["providerName"]))
    if probe_capabilities:
        capability_probe = getattr(provider, "capability_probe", None)
        if callable(capability_probe):
            probe = capability_probe()
            if not isinstance(probe, dict):
                probe = {
                    "ok": False,
                    "error": "invalid_capability_probe_payload",
                    "providerName": status["providerName"],
                }
            status["capabilityProbe"] = probe
            probe_capabilities_payload = probe.get("capabilities") if isinstance(probe, dict) else None
            if bool(probe.get("ok")) and isinstance(probe_capabilities_payload, dict):
                merged = dict(status["capabilities"]) if isinstance(status["capabilities"], dict) else {}
                for key, value in probe_capabilities_payload.items():
                    if key in merged:
                        merged[key] = bool(value)
                status["capabilities"] = merged
                model_info = probe.get("modelInfo") if isinstance(probe.get("modelInfo"), dict) else None
                if model_info is not None:
                    status["modelInfo"] = model_info
            elif isinstance(status["capabilities"], dict):
                status["capabilities"] = {str(key): False for key in status["capabilities"]}
    cooldown_status = getattr(provider, "cooldown_status", None)
    if callable(cooldown_status):
        status["cooldown"] = cooldown_status()
    return status


def benchmark_prediction_provider(
    provider: PredictionProvider,
    cases: list[PredictionBenchmarkCase],
    *,
    max_candidates: int = 3,
    latency_budget_ms: int = 150,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    latencies: list[int] = []
    status = prediction_provider_status(provider)
    provider_name = str(status["providerName"])
    for case in cases:
        started = time.perf_counter()
        predictions = provider.predict(
            current_input=case.current_input,
            recent_context=case.recent_context,
            max_candidates=max_candidates,
        )
        wall_ms = int((time.perf_counter() - started) * 1000)
        prediction_latency = max((item.latency_ms for item in predictions), default=wall_ms)
        if predictions:
            provider_name = predictions[0].provider_name
        latency_ms = max(wall_ms, prediction_latency)
        latencies.append(latency_ms)
        results.append(
            {
                "currentInput": case.current_input,
                "candidateCount": len(predictions),
                "latencyMs": latency_ms,
                "wallMs": wall_ms,
                "overBudget": latency_ms > latency_budget_ms,
                "candidates": [item.text for item in predictions],
            }
        )
    sorted_latencies = sorted(latencies)
    p50 = sorted_latencies[len(sorted_latencies) // 2] if sorted_latencies else 0
    return {
        "schemaVersion": "rag-ime.predict-benchmark.v1",
        "providerName": provider_name,
        "providerProfile": _prediction_provider_profile(provider),
        "providerConfigured": bool(status["configured"]),
        "maxCandidates": max_candidates,
        "latencyBudgetMs": latency_budget_ms,
        "summary": {
            "caseCount": len(results),
            "p50LatencyMs": p50,
            "maxLatencyMs": max(latencies) if latencies else 0,
            "allWithinBudget": all(not item["overBudget"] for item in results),
            "totalCandidates": sum(int(item["candidateCount"]) for item in results),
            "hasCandidates": any(int(item["candidateCount"]) > 0 for item in results),
        },
        "cases": results,
    }


def doctor_prediction_provider(
    provider: PredictionProvider,
    *,
    sample_input: str = "RAG 输入法",
    recent_context: str = "",
    max_candidates: int = 3,
    latency_budget_ms: int = 150,
) -> dict[str, Any]:
    status = prediction_provider_status(provider)
    model_probe = _probe_openai_compatible_models(provider)
    benchmark = benchmark_prediction_provider(
        provider,
        [PredictionBenchmarkCase(current_input=sample_input, recent_context=recent_context)],
        max_candidates=max_candidates,
        latency_budget_ms=latency_budget_ms,
    )
    has_candidates = bool(benchmark["summary"]["hasCandidates"])
    within_budget = bool(benchmark["summary"]["allWithinBudget"])
    model_probe_ok = bool(model_probe["ok"])
    ready = bool(status["configured"]) and has_candidates and within_budget
    updated_status = prediction_provider_status(provider)
    checks = {
        "configured": bool(status["configured"]),
        "modelsEndpoint": model_probe,
        "prediction": {
            "ok": has_candidates and within_budget,
            "hasCandidates": has_candidates,
            "withinBudget": within_budget,
            "latencyMs": benchmark["summary"]["maxLatencyMs"],
            "candidateCount": benchmark["summary"]["totalCandidates"],
            "candidates": benchmark["cases"][0]["candidates"] if benchmark["cases"] else [],
        },
    }
    return {
        "schemaVersion": "rag-ime.predictor-doctor.v1",
        "ready": ready,
        "status": updated_status,
        "checks": checks,
        "summary": {
            "configured": bool(status["configured"]),
            "endpointReachable": model_probe_ok,
            "hasCandidates": has_candidates,
            "withinBudget": within_budget,
            "readyForSidecar": ready,
        },
        "nextActions": _prediction_doctor_next_actions(status=status, checks=checks),
    }


def benchmark_streaming_ttft_provider(
    provider: PredictionProvider,
    cases: list[PredictionBenchmarkCase],
    *,
    max_candidates: int = 3,
    repeat: int = 3,
    warmup_runs: int = 0,
    latency_budget_ms: int = 200,
    keep_alive: int | str | None = -1,
) -> dict[str, Any]:
    status = prediction_provider_status(provider)
    provider_name = str(status.get("providerName") or provider.__class__.__name__)
    config = getattr(provider, "config", None)
    provider_kind = str(getattr(config, "provider_name", "")) if config is not None else ""
    supported = provider_kind in {"local-ollama", "local-mlx"}
    if not supported:
        return {
            "schemaVersion": "rag-ime.predictor-ttft.v1",
            "providerName": provider_name,
            "providerProfile": _prediction_provider_profile(provider),
            "providerConfigured": bool(status.get("configured")),
            "supported": False,
            "reason": "streaming_ttft_currently_supports_native_ollama_or_mlx_only",
            "latencyBudgetMs": latency_budget_ms,
            "summary": {
                "caseCount": 0,
                "sampleCount": 0,
                "hasFirstChunk": False,
                "allWithinBudget": False,
            },
            "cases": [],
        }

    def measure_case(case: PredictionBenchmarkCase) -> dict[str, Any]:
        if provider_kind == "local-mlx":
            return _measure_mlx_stream_ttft(
                config,
                current_input=case.current_input,
                recent_context=case.recent_context,
                max_candidates=max_candidates,
                stop_after_first_candidate=True,
            )
        return _measure_ollama_stream_ttft(
            config,
            current_input=case.current_input,
            recent_context=case.recent_context,
            max_candidates=max_candidates,
            keep_alive=keep_alive,
            stop_after_first_candidate=True,
        )

    warmup_results: list[dict[str, Any]] = []
    warmup_count = max(0, int(warmup_runs))
    for warmup_index in range(1, warmup_count + 1):
        for case in cases:
            measured = measure_case(case)
            measured["currentInput"] = case.current_input
            if case.case_id:
                measured["caseId"] = case.case_id
            measured["warmupIndex"] = warmup_index
            warmup_results.append(measured)

    results: list[dict[str, Any]] = []
    first_chunk_latencies = []
    first_candidate_latencies = []
    total_latencies = []
    repeat_count = max(1, int(repeat))
    for repeat_index in range(1, repeat_count + 1):
        for case in cases:
            measured = measure_case(case)
            measured["currentInput"] = case.current_input
            if case.case_id:
                measured["caseId"] = case.case_id
            if repeat_count > 1:
                measured["repeatIndex"] = repeat_index
            first_ms = measured.get("firstChunkMs")
            if isinstance(first_ms, int):
                first_chunk_latencies.append(first_ms)
            first_candidate_ms = measured.get("firstCandidateMs")
            if isinstance(first_candidate_ms, int):
                first_candidate_latencies.append(first_candidate_ms)
            total_ms = measured.get("totalMs")
            if isinstance(total_ms, int):
                total_latencies.append(total_ms)
            measured["overBudget"] = not isinstance(first_candidate_ms, int) or first_candidate_ms > latency_budget_ms
            results.append(measured)
    first_chunk_missing_count = sum(1 for item in results if not isinstance(item.get("firstChunkMs"), int))
    first_candidate_missing_count = sum(1 for item in results if not isinstance(item.get("firstCandidateMs"), int))
    over_budget_count = sum(1 for item in results if bool(item.get("overBudget")))

    return {
        "schemaVersion": "rag-ime.predictor-ttft.v1",
        "providerName": provider_name,
        "providerProfile": _prediction_provider_profile(provider),
        "providerConfigured": bool(status.get("configured")),
        "supported": True,
        "latencyBudgetMs": latency_budget_ms,
        "maxCandidates": max_candidates,
        "repeat": {
            "requested": repeat_count,
            "baseCaseCount": len(cases),
            "effectiveCaseCount": len(results),
        },
        "warmup": _streaming_ttft_warmup_summary(warmup_results, requested_runs=warmup_count),
        "summary": {
            "caseCount": len(cases),
            "sampleCount": len(results),
            "hasFirstChunk": bool(first_chunk_latencies),
            "hasFirstCandidate": bool(first_candidate_latencies),
            "p50FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.50),
            "p95FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.95),
            "minFirstChunkMs": min(first_chunk_latencies) if first_chunk_latencies else 0,
            "maxFirstChunkMs": max(first_chunk_latencies) if first_chunk_latencies else 0,
            "p50FirstCandidateMs": _percentile_ms(first_candidate_latencies, 0.50),
            "p95FirstCandidateMs": _percentile_ms(first_candidate_latencies, 0.95),
            "minFirstCandidateMs": min(first_candidate_latencies) if first_candidate_latencies else 0,
            "maxFirstCandidateMs": max(first_candidate_latencies) if first_candidate_latencies else 0,
            "p50TotalMs": _percentile_ms(total_latencies, 0.50),
            "p95TotalMs": _percentile_ms(total_latencies, 0.95),
            "allWithinBudget": bool(results) and over_budget_count == 0,
            "overBudgetCount": over_budget_count,
            "firstChunkMissingCount": first_chunk_missing_count,
            "firstCandidateMissingCount": first_candidate_missing_count,
            "failureCount": sum(1 for item in results if not bool(item.get("ok"))),
            "candidateSampleCount": sum(1 for item in results if int(item.get("candidateCount") or 0) > 0),
        },
        "cases": results,
    }


def _streaming_ttft_warmup_summary(results: list[dict[str, Any]], *, requested_runs: int) -> dict[str, Any]:
    first_candidate_latencies = [
        int(item["firstCandidateMs"]) for item in results if isinstance(item.get("firstCandidateMs"), int)
    ]
    first_chunk_latencies = [int(item["firstChunkMs"]) for item in results if isinstance(item.get("firstChunkMs"), int)]
    return {
        "requestedRuns": requested_runs,
        "sampleCount": len(results),
        "hasFirstCandidate": bool(first_candidate_latencies),
        "p50FirstCandidateMs": _percentile_ms(first_candidate_latencies, 0.50),
        "p95FirstCandidateMs": _percentile_ms(first_candidate_latencies, 0.95),
        "p50FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.50),
        "p95FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.95),
        "firstCandidateMissingCount": sum(1 for item in results if not isinstance(item.get("firstCandidateMs"), int)),
        "failureCount": sum(1 for item in results if not bool(item.get("ok"))),
    }


def _measure_ollama_stream_ttft(
    config: Any,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    keep_alive: int | str | None,
    stop_after_first_candidate: bool = False,
) -> dict[str, Any]:
    query = compact_whitespace(current_input)
    context = compact_whitespace(recent_context)[-420:]
    body = _ollama_chat_body(config, context=context, query=query, max_candidates=max_candidates, stream=True)
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    request = urllib.request.Request(
        f"{str(getattr(config, 'base_url', '')).rstrip('/')}/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_headers_from_prediction_config(config),
        method="POST",
    )
    started = time.perf_counter()
    first_chunk_ms = None
    first_text = ""
    first_candidate_ms = None
    full_text = ""
    candidates: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=float(getattr(config, "timeout_s", 0.8))) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line.decode("utf-8"))
                text = extract_ollama_content_delta(payload)
                if text:
                    full_text += text
                    if first_chunk_ms is None:
                        first_chunk_ms = int((time.perf_counter() - started) * 1000)
                        first_text = text
                    if first_candidate_ms is None:
                        candidates = _parse_streaming_prediction_candidates(full_text, max_candidates=max_candidates)
                        candidates = _finalize_ime_prediction_candidates(candidates, query)
                        if candidates:
                            first_candidate_ms = int((time.perf_counter() - started) * 1000)
                            if stop_after_first_candidate:
                                break
                if payload.get("done"):
                    break
    except urllib.error.HTTPError as exc:
        error = f"http_{exc.code}"
        try:
            body_text = exc.read().decode("utf-8")
        except OSError:
            body_text = ""
        return {
            "ok": False,
            "error": error,
            "errorBody": body_text[:300],
            "firstChunkMs": first_chunk_ms,
            "totalMs": int((time.perf_counter() - started) * 1000),
            "candidateCount": 0,
            "candidates": [],
        }
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "error": _prediction_error_name(exc),
            "firstChunkMs": first_chunk_ms,
            "totalMs": int((time.perf_counter() - started) * 1000),
            "candidateCount": 0,
            "candidates": [],
        }
    total_ms = int((time.perf_counter() - started) * 1000)
    if not stop_after_first_candidate:
        candidates = _parse_prediction_candidate_texts([full_text], max_candidates=max_candidates)
        candidates = _finalize_ime_prediction_candidates(candidates, query)
    elif not candidates:
        candidates = _parse_prediction_candidate_texts([full_text], max_candidates=max_candidates)
        candidates = _finalize_ime_prediction_candidates(candidates, query)
    return {
        "ok": first_chunk_ms is not None,
        "firstChunkMs": first_chunk_ms,
        "firstCandidateMs": first_candidate_ms,
        "totalMs": total_ms,
        "firstText": first_text,
        "rawText": full_text,
        "candidateCount": len(candidates),
        "candidates": candidates,
    }


def _measure_mlx_stream_ttft(
    config: Any,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    stop_after_first_candidate: bool = False,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
) -> dict[str, Any]:
    query = compact_whitespace(current_input)
    context = compact_whitespace(recent_context)[-420:]
    body = _mlx_predict_body(
        config,
        context=context,
        query=query,
        max_candidates=max_candidates,
        stream=True,
        request_type=request_type,
        rime_candidates=rime_candidates,
    )
    if stop_after_first_candidate:
        body["streamFirstCandidate"] = True
        body["maxCandidates"] = 1
    request = urllib.request.Request(
        f"{str(getattr(config, 'base_url', '')).rstrip('/')}/predict-stream",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=_headers_from_prediction_config(config),
        method="POST",
    )
    started = time.perf_counter()
    first_chunk_ms = None
    first_text = ""
    first_candidate_ms = None
    full_text = ""
    final_candidates: list[str] = []
    prompt_cache: dict[str, Any] = {}
    server_timing: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(request, timeout=float(getattr(config, "timeout_s", 0.8))) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                payload = json.loads(raw_line.decode("utf-8"))
                text = _mlx_stream_text_delta(payload)
                if text:
                    full_text += text
                    if first_chunk_ms is None:
                        first_chunk_ms = int((time.perf_counter() - started) * 1000)
                        first_text = text
                    if first_candidate_ms is None:
                        final_candidates = _parse_streaming_prediction_candidates(full_text, max_candidates=max_candidates)
                        final_candidates = _finalize_ime_prediction_candidates(final_candidates, query)
                        if final_candidates:
                            first_candidate_ms = int((time.perf_counter() - started) * 1000)
                            if stop_after_first_candidate:
                                break
                if isinstance(payload.get("candidates"), list):
                    final_candidates = _candidate_parts_from_json_value(payload.get("candidates"))
                    final_candidates = _finalize_ime_prediction_candidates(final_candidates, query)
                    if final_candidates and first_candidate_ms is None:
                        first_candidate_ms = int((time.perf_counter() - started) * 1000)
                        if stop_after_first_candidate:
                            break
                if isinstance(payload.get("promptCache"), dict):
                    prompt_cache = dict(payload["promptCache"])
                if isinstance(payload.get("timing"), dict):
                    server_timing = dict(payload["timing"])
                if payload.get("done"):
                    break
    except urllib.error.HTTPError as exc:
        error = f"http_{exc.code}"
        try:
            body_text = exc.read().decode("utf-8")
        except OSError:
            body_text = ""
        return {
            "ok": False,
            "error": error,
            "errorBody": body_text[:300],
            "firstChunkMs": first_chunk_ms,
            "totalMs": int((time.perf_counter() - started) * 1000),
            "candidateCount": 0,
            "candidates": [],
        }
    except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "error": _prediction_error_name(exc),
            "firstChunkMs": first_chunk_ms,
            "totalMs": int((time.perf_counter() - started) * 1000),
            "candidateCount": 0,
            "candidates": [],
        }
    total_ms = int((time.perf_counter() - started) * 1000)
    candidates = final_candidates or _parse_prediction_candidate_texts([full_text], max_candidates=max_candidates)
    candidates = _parse_prediction_candidate_texts(candidates, max_candidates=max_candidates)
    candidates = _finalize_ime_prediction_candidates(candidates, query)
    return {
        "ok": first_chunk_ms is not None,
        "firstChunkMs": first_chunk_ms,
        "firstCandidateMs": first_candidate_ms,
        "totalMs": total_ms,
        "firstText": first_text,
        "rawText": full_text,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "promptCache": prompt_cache,
        "serverTiming": server_timing,
    }


def extract_openai_content(payload: dict[str, Any]) -> str:
    return "\n".join(extract_openai_contents(payload))


def extract_openai_contents(payload: dict[str, Any]) -> list[str]:
    results: list[str] = []
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                results.append(message["content"])
            elif isinstance(choice.get("text"), str):
                results.append(choice["text"])
        return results
    if isinstance(payload.get("content"), str):
        return [payload["content"]]
    if isinstance(payload.get("text"), str):
        return [payload["text"]]
    return []


def extract_ollama_contents(payload: dict[str, Any]) -> list[str]:
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return [message["content"]]
    if isinstance(payload.get("response"), str):
        return [payload["response"]]
    return extract_openai_contents(payload)


def extract_ollama_content_delta(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(payload.get("response"), str):
        return payload["response"]
    return extract_openai_content(payload)


def parse_prediction_candidates(text: str, *, max_candidates: int = 5) -> list[str]:
    return _parse_prediction_candidate_texts([text], max_candidates=max_candidates)


def parse_ime_prediction_candidates(
    text: str | list[str],
    *,
    max_candidates: int = 5,
    current_input: str = "",
    recent_context: str = "",
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] | list[str] = (),
) -> list[str]:
    texts = [text] if isinstance(text, str) else [str(item) for item in text if str(item).strip()]
    max_items = max(1, int(max_candidates))
    resolved_request_type = normalize_prediction_request_type(request_type)
    rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)

    if resolved_request_type == PREDICTION_REQUEST_RIME_REORDER and rime_candidate_tuple:
        reordered = _rime_reorder_candidates_from_texts(texts, rime_candidate_tuple, max_candidates=max_items)
        if reordered:
            return reordered

    candidates = _structured_prediction_candidate_texts(texts, max_candidates=max_items)
    if not candidates:
        candidates = _continuation_prediction_candidates_from_texts(
            texts,
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_items,
        )
    if not candidates:
        candidates = _parse_prediction_candidate_texts(texts, max_candidates=max_items)
    candidates = _expand_rime_concat_candidates(
        candidates,
        rime_candidate_tuple,
        max_candidates=max_items,
    )
    if recent_context:
        candidates = [trim_context_overlap(candidate, recent_context) for candidate in candidates]
    if resolved_request_type == PREDICTION_REQUEST_NO_INPUT:
        candidates = _filter_repeated_context_candidates(candidates, recent_context)
    allowed_ascii_candidates = rime_candidate_tuple if resolved_request_type == PREDICTION_REQUEST_PINYIN_CONSTRAINED else ()
    return _finalize_ime_prediction_candidates(
        candidates,
        current_input,
        allowed_ascii_candidates=allowed_ascii_candidates,
    )[:max_items]


def trim_context_overlap(candidate: str, recent_context: str) -> str:
    cand = compact_whitespace(candidate)
    ctx = compact_whitespace(recent_context)
    if not cand or not ctx:
        return cand
    tail = ctx[-40:]
    max_k = min(len(cand), len(tail), 16)
    for count in range(max_k, 1, -1):
        if tail.endswith(cand[:count]):
            return cand[count:].lstrip(" \t\r\n,，、:：;；。.!！?？")
    return cand


def _parse_prediction_candidate_texts(texts: list[str], *, max_candidates: int = 5) -> list[str]:
    max_items = max(1, int(max_candidates))
    seen: set[str] = set()
    candidates: list[str] = []
    for text in texts:
        for item in _candidate_parts_from_text(text):
            if not item or item in seen:
                continue
            if len(item) > 24:
                item = item[:24]
            seen.add(item)
            candidates.append(item)
            if len(candidates) >= max_items:
                return candidates
    return candidates


def _filter_repeated_input_candidates(candidates: list[str], current_input: str) -> list[str]:
    if _looks_like_candidate_list_input(current_input):
        return candidates
    input_norm = _candidate_repeat_norm(current_input)
    if not input_norm:
        return candidates
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_norm = _candidate_repeat_norm(candidate)
        if not candidate_norm:
            continue
        if candidate_norm == input_norm or candidate_norm in input_norm:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _filter_repeated_context_candidates(candidates: list[str], recent_context: str) -> list[str]:
    context_surface = compact_whitespace(recent_context)
    context_norm = _candidate_repeat_norm(recent_context)
    if not context_norm:
        return candidates
    context_chars = _cjk_counter(recent_context)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        surface = compact_whitespace(candidate)
        if context_surface and surface.startswith(context_surface):
            surface = surface[len(context_surface) :].lstrip(" \t\r\n,，、:：;；。.!！?？")
        candidate_norm = _candidate_repeat_norm(surface)
        if not candidate_norm:
            continue
        if len(candidate_norm) >= 2 and candidate_norm in context_norm:
            continue
        if _candidate_is_context_reorder(surface, context_chars):
            continue
        if surface in seen:
            continue
        seen.add(surface)
        result.append(surface)
    return result


def _candidate_is_context_reorder(candidate: str, context_chars: Counter[str]) -> bool:
    candidate_chars = _cjk_chars(candidate)
    if len(candidate_chars) < 4 or not context_chars:
        return False
    candidate_counter = Counter(candidate_chars)
    covered = sum(min(count, context_chars.get(char, 0)) for char, count in candidate_counter.items())
    return covered / max(1, len(candidate_chars)) >= 0.65


def _cjk_chars(text: str) -> list[str]:
    return re.findall(r"[\u3400-\u9fff]", text)


def _cjk_counter(text: str) -> Counter[str]:
    return Counter(_cjk_chars(text))


def _finalize_ime_prediction_candidates(
    candidates: list[str],
    current_input: str,
    *,
    allowed_ascii_candidates: tuple[str, ...] = (),
) -> list[str]:
    return _filter_low_value_ime_candidates(
        _filter_repeated_input_candidates(candidates, current_input),
        allowed_ascii_candidates=allowed_ascii_candidates,
    )


def _filter_low_value_ime_candidates(
    candidates: list[str],
    *,
    allowed_ascii_candidates: tuple[str, ...] = (),
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    allowed_ascii = {compact_whitespace(item).lower() for item in allowed_ascii_candidates if compact_whitespace(item)}
    for candidate in candidates:
        normalized = compact_whitespace(candidate)
        if not normalized:
            continue
        if "\ufffd" in normalized:
            continue
        if len(normalized) <= 1:
            continue
        is_allowed_ascii = normalized.lower() in allowed_ascii
        cjk_count = _cjk_char_count(normalized)
        if re.fullmatch(r"[A-Za-z0-9_./:\-\s]{1,24}", normalized) and not is_allowed_ascii:
            continue
        if cjk_count < 2 and not is_allowed_ascii:
            continue
        if normalized in _LOW_VALUE_IME_CANDIDATES:
            continue
        if _looks_like_meta_ime_candidate(normalized):
            continue
        if _looks_like_incomplete_ime_candidate(normalized):
            continue
        if any(normalized.startswith(prefix) for prefix in ("测试", "分析", "假设")) and _cjk_char_count(normalized) <= 6:
            continue
        if any(normalized.startswith(prefix) for prefix in ("当前", "目前", "现在")) and len(normalized) <= 5:
            continue
        if re.fullmatch(r"[嗯啊呃额]{1,4}", normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _looks_like_meta_ime_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if not normalized:
        return True
    meta_prefixes = (
        "你正在输入",
        "你正在尝试",
        "你正在使用",
        "你正在看",
        "你正在查看",
        "你当前正在",
        "您正在输入",
        "您正在尝试",
        "您正在使用",
        "您正在看",
        "您正在查看",
        "您当前正在",
        "用户正在输入",
        "用户正在尝试",
        "用户正在使用",
        "用户正在看",
        "用户正在查看",
        "正在输入一个",
        "正在查看",
        "正在看",
    )
    if normalized.startswith(meta_prefixes):
        return True
    meta_markers = (
        "已经上屏的文本",
        "上屏的文本",
        "作为输入法候选",
        "这是一个候选",
        "这个项目",
        "号项目",
    )
    return any(marker in normalized for marker in meta_markers)


def _looks_like_incomplete_ime_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if not normalized:
        return True
    cjk_count = _cjk_char_count(normalized)
    if cjk_count <= 5 and normalized.endswith(
        (
            "的",
            "得",
            "地",
            "了",
            "着",
            "过",
            "在",
            "和",
            "与",
            "及",
            "或",
            "把",
            "被",
            "将",
            "下",
            "上",
            "这个",
            "那个",
        )
    ):
        return True
    if cjk_count > 0 and re.search(r"[A-Za-z]{2,}$", normalized):
        return True
    if cjk_count <= 4 and normalized.startswith("将"):
        return True
    return False


def _cjk_char_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def _candidate_repeat_norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).lower()


def _looks_like_candidate_list_input(text: str) -> bool:
    parts = [part for part in re.split(r"[\s,，、;；|/]+", compact_whitespace(text)) if part]
    if len(parts) < 2:
        return False
    cjk_parts = sum(1 for part in parts if re.search(r"[\u3400-\u9fff]", part))
    return cjk_parts >= 2


def _looks_like_prompt_instruction(text: str) -> bool:
    lowered = compact_whitespace(text).lower()
    prompt_markers = (
        "已上屏上下文",
        "已上屏文本",
        "上屏文字",
        "请求类型",
        "模式说明",
        "当前拼音",
        "当前拼音或参考候选",
        "当前输入",
        "候选词",
        "输出要求",
        "输出",
        "json",
        "assistant",
        "system",
        "user",
        "/no_think",
    )
    return any(marker in lowered for marker in prompt_markers)


def _candidate_parts_from_text(text: str) -> list[str]:
    cleaned = _clean_prediction_output(text)
    if not cleaned:
        return []
    json_candidates = _candidate_parts_from_json_text(cleaned)
    if json_candidates:
        return json_candidates
    json_fragment_candidates = _candidate_parts_from_json_fragment(cleaned)
    if json_fragment_candidates:
        return json_fragment_candidates
    numbered_candidates = _numbered_candidate_parts_from_text(cleaned)
    if numbered_candidates:
        return numbered_candidates
    parts = re.split(r"[\s,，、;；|/]+", cleaned)
    candidates: list[str] = []
    for part in parts:
        item = re.sub(r"^\d+[.)、．]?", "", part)
        item = item.strip("。.!！?？:\"'“”‘’[]()（）")
        if not item:
            continue
        candidates.append(item)
    return candidates


def _numbered_candidate_parts_from_text(text: str) -> list[str]:
    candidates: list[str] = []
    pattern = re.compile(
        r"(?:^|[\s,，、;；|/:\n\r：])\d+[.)、．]\s*"
        r"(.+?)(?=(?:[\s,，、;；|/:\n\r：]\d+[.)、．])|$)"
    )
    for match in pattern.finditer(text):
        item = _normalize_prediction_candidate_text(match.group(1))
        if item:
            candidates.append(item)
    return candidates if len(candidates) >= 2 else []


def _structured_prediction_candidate_texts(texts: list[str], *, max_candidates: int) -> list[str]:
    max_items = max(1, int(max_candidates))
    candidates: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = _clean_prediction_output(text)
        if not cleaned:
            continue
        parts = _candidate_parts_from_json_text(cleaned) or _candidate_parts_from_json_fragment(cleaned)
        if not parts and _looks_like_candidate_list_output(cleaned):
            parts = _candidate_parts_from_text(cleaned)
        for part in parts:
            item = _normalize_prediction_candidate_text(part)
            if not item or item in seen:
                continue
            seen.add(item)
            candidates.append(item)
            if len(candidates) >= max_items:
                return candidates
    return candidates


def _looks_like_candidate_list_output(text: str) -> bool:
    if re.search(r"(?:^|[\s,，、;；|/:\n\r：])\d+[.)、．]", text):
        return True
    if not re.search(r"[\n\r;；|/]", text):
        return False
    parts = [part for part in re.split(r"[\s;；|/]+", text) if part]
    return len(parts) >= 2 and sum(1 for part in parts if _cjk_char_count(part) >= 2) >= 2


def _continuation_prediction_candidates_from_texts(
    texts: list[str],
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
) -> list[str]:
    max_items = max(1, int(max_candidates))
    candidates: list[str] = []
    seen: set[str] = set()
    for text in texts:
        cleaned = _remove_prediction_prompt_echo(_clean_prediction_output(text), current_input=current_input, recent_context=recent_context)
        spans = _continuation_candidate_spans(cleaned)
        if max_items == 1 and spans:
            spans = [max(spans, key=len)]
        for item in spans:
            if item in seen:
                continue
            seen.add(item)
            candidates.append(item)
            if len(candidates) >= max_items:
                return candidates
    return candidates


def _remove_prediction_prompt_echo(text: str, *, current_input: str, recent_context: str) -> str:
    cleaned = compact_whitespace(text)
    for prefix in (compact_whitespace(current_input), compact_whitespace(recent_context)[-120:]):
        if prefix and cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].lstrip(" \t\r\n,，、:：;；。.!！?？")
    context = compact_whitespace(recent_context)
    max_overlap = min(len(context), len(cleaned), 80)
    for size in range(max_overlap, 3, -1):
        if context[-size:] == cleaned[:size]:
            return cleaned[size:].lstrip(" \t\r\n,，、:：;；。.!！?？")
    return cleaned


def _continuation_candidate_spans(text: str) -> list[str]:
    cleaned = _normalize_prediction_candidate_text(text)
    if not cleaned:
        return []
    first_clause = _first_useful_continuation_clause(cleaned)
    if _cjk_char_count(first_clause) < 2:
        return []
    compacted = re.sub(r"\s+", "", first_clause)
    if len(compacted) < 2:
        return []
    if compacted in _LOW_VALUE_IME_CANDIDATES:
        return []

    spans: list[str] = []
    for length in _CONTINUATION_PREFERRED_LENGTHS:
        if len(compacted) >= length:
            spans.append(compacted[:length])
    spans.append(compacted[:24])
    result: list[str] = []
    seen: set[str] = set()
    for span in spans:
        item = _normalize_prediction_candidate_text(span)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _first_useful_continuation_clause(text: str) -> str:
    for clause in re.split(r"[，,。.!！?？；;\n\r]", text):
        item = _strip_leading_prediction_fillers(_normalize_prediction_candidate_text(clause))
        compacted = re.sub(r"\s+", "", item)
        if _cjk_char_count(compacted) < 2:
            continue
        if compacted in _LOW_VALUE_IME_CANDIDATES:
            continue
        if re.fullmatch(r"(?:候选|预测|建议)[:：]\s*[A-Za-z0-9_-]{0,8}", compacted):
            continue
        if _looks_like_prompt_instruction(compacted):
            continue
        return compacted
    return ""


def _strip_leading_prediction_fillers(text: str) -> str:
    result = text
    prefixes = (
        "好的",
        "好",
        "可以",
        "没问题",
        "以下是候选",
        "以下是",
        "候选如下",
        "给出候选",
        "候选：",
        "候选:",
        "预测：",
        "预测:",
        "建议：",
        "建议:",
        "基于",
        "根据",
        "上述分析",
        "上述",
        "我会",
        "我将",
        "我们会",
        "我们将",
        "我们开始",
        "我们来",
        "然后",
        "而且",
        "并且",
        "同时",
        "应该",
        "需要",
        "就是",
        "继续",
        "接下来",
        "开始整理",
    )
    for _ in range(4):
        stripped = False
        result = result.lstrip(" \t\r\n,，、:：;；。.!！?？")
        for prefix in prefixes:
            if result.startswith(prefix) and _cjk_char_count(result[len(prefix):]) >= 2:
                result = result[len(prefix):].lstrip(" \t\r\n,，、:：;；。.!！?？")
                stripped = True
                break
        if not stripped:
            break
    return result.lstrip("将要会能再")


def _normalize_prediction_candidate_text(text: str) -> str:
    item = compact_whitespace(str(text))
    item = re.sub(r"^\s*\d+[.)、．]?\s*", "", item)
    item = item.strip(" \t\r\n。.!！?？:\"'“”‘’[]()（）{}<>《》")
    return compact_whitespace(item)


def _expand_rime_concat_candidates(
    candidates: list[str],
    rime_candidates: tuple[str, ...],
    *,
    max_candidates: int,
) -> list[str]:
    if not rime_candidates:
        return candidates
    max_items = max(1, int(max_candidates))
    result: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        normalized = _normalize_prediction_candidate_text(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    for candidate in candidates:
        if len(result) >= max_items:
            break
        normalized = _normalize_prediction_candidate_text(candidate)
        if not normalized:
            continue
        compacted = re.sub(r"[\s/|,，、;；]+", "", normalized)
        matches = [item for item in rime_candidates if item and item in compacted]
        if len(matches) >= 2 and len(compacted) <= sum(len(item) for item in matches) + 2:
            for match in matches:
                add(match)
                if len(result) >= max_items:
                    break
            continue
        if "\ufffd" in normalized:
            continue
        add(normalized)
    return result


def _rime_reorder_candidates_from_texts(
    texts: list[str],
    rime_candidates: tuple[str, ...],
    *,
    max_candidates: int,
) -> list[str]:
    max_items = max(1, int(max_candidates))
    result: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if len(result) >= max_items:
            return
        if candidate and candidate not in seen:
            seen.add(candidate)
            result.append(candidate)

    for text in texts:
        cleaned = _clean_prediction_output(text)
        for token in _rime_reorder_tokens_from_text(cleaned):
            if token.isdigit():
                index = int(token) - 1
                if 0 <= index < len(rime_candidates):
                    add(rime_candidates[index])
                    continue
            if token in rime_candidates:
                add(token)
        for _position, candidate in sorted(
            (position, candidate)
            for candidate in rime_candidates
            if (position := cleaned.find(candidate)) >= 0
        ):
            add(candidate)
        if len(result) >= max_items:
            break
    return result


def _rime_reorder_tokens_from_text(text: str) -> list[str]:
    tokens: list[str] = []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        tokens.extend(_rime_reorder_tokens_from_json(parsed))
    tokens.extend(re.findall(r"\d+", text))
    tokens.extend(_candidate_parts_from_text(text))
    result: list[str] = []
    for token in tokens:
        item = compact_whitespace(str(token))
        if item.isdigit():
            result.append(item)
            continue
        normalized = _normalize_prediction_candidate_text(item)
        if normalized:
            result.append(normalized)
    return result


def _rime_reorder_tokens_from_json(value: Any) -> list[str]:
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_rime_reorder_tokens_from_json(item))
        return result
    if isinstance(value, dict):
        for key in ("candidates", "候选", "items", "predictions", "order"):
            if key in value:
                return _rime_reorder_tokens_from_json(value[key])
    return []


def _parse_streaming_prediction_candidates(text: str, *, max_candidates: int = 5) -> list[str]:
    cleaned = _clean_prediction_output(text)
    if not cleaned:
        return []
    json_candidates = _candidate_parts_from_json_text(cleaned)
    if json_candidates:
        return _parse_prediction_candidate_texts(json_candidates, max_candidates=max_candidates)

    # During JSON streaming the buffer often looks like '["候选一"' before the
    # closing array arrives. Only accept closed string elements; a bare '["'
    # or an unfinished token should not become an IME candidate.
    quoted = [match.strip() for match in re.findall(r'"([^"\n\r]{1,48})"', cleaned)]
    if quoted:
        return _parse_prediction_candidate_texts(quoted, max_candidates=max_candidates)

    if not any(mark in cleaned for mark in "[]{}\"") and _plain_streaming_candidate_ready(cleaned):
        return _parse_prediction_candidate_texts([cleaned], max_candidates=max_candidates)
    return []


def _plain_streaming_candidate_ready(text: str) -> bool:
    compacted = compact_whitespace(text)
    if not compacted:
        return False
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", compacted))
    visible_len = len(re.sub(r"\s+", "", compacted))
    if cjk_count >= 4:
        return True
    if cjk_count == 0:
        return visible_len >= 3
    return visible_len >= 4


def _clean_prediction_output(text: str) -> str:
    text = re.split(r"<\|(?:im_end|endoftext|im_start)\|>", text, maxsplit=1)[0]
    cleaned = re.sub(r"(?is)<think>.*?</think>", " ", text)
    cleaned = re.sub(r"(?is)<think>.*", " ", cleaned)
    cleaned = re.sub(r"(?is)<analysis>.*?</analysis>", " ", cleaned)
    cleaned = re.sub(r"(?is)<reasoning>.*?</reasoning>", " ", cleaned)
    cleaned = re.sub(r"<\|[^|]{1,64}\|>", " ", cleaned)
    cleaned = cleaned.replace("```json", " ").replace("```", " ")
    return compact_whitespace(cleaned)


def _candidate_parts_from_json_text(text: str) -> list[str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _candidate_parts_from_json_value(parsed)


def _candidate_parts_from_json_fragment(text: str) -> list[str]:
    match = re.search(r"\[[^\[\]]{1,512}\]", text, flags=re.DOTALL)
    if match:
        return _candidate_parts_from_json_text(match.group(0))

    # Small local Qwen models often return a useful but unfinished JSON array
    # before the IME timeout, for example:
    #   ["接入本地记忆","验证 LLM 候选","预测流程完成"
    # Treat closed string elements as candidates instead of falling through to
    # whitespace splitting, which would turn "验证 LLM 候选" into noisy tokens.
    if "[" not in text:
        return []
    quoted = [match.strip() for match in re.findall(r'"([^"\n\r]{1,48})"', text)]
    return [item for item in quoted if item]


def _candidate_parts_from_json_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_candidate_parts_from_json_value(item))
        return result
    if isinstance(value, dict):
        for key in ("candidates", "候选", "items", "predictions"):
            if key in value:
                return _candidate_parts_from_json_value(value[key])
    return []


def _normalized_prompt_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    return "completion" if normalized in {"completion", "base", "prefix"} else "chat"


def _openai_stable_prefix_for_request(prompt_mode: str, request_type: str) -> str:
    if _normalized_prompt_mode(prompt_mode) != "chat":
        return ""
    return _openai_prediction_system_prompt(request_type)


def _openai_prediction_system_prompt(request_type: str) -> str:
    resolved = normalize_prediction_request_type(request_type)
    if resolved == PREDICTION_REQUEST_PINYIN_CONSTRAINED:
        return (
            f"{OPENAI_CHAT_SYSTEM_PROMPT} 当前是拼音/前缀约束预测, "
            "候选必须匹配当前输入或来自 Rime 候选, 不要做自由聊天。"
        )
    if resolved == PREDICTION_REQUEST_RIME_REORDER:
        return (
            f"{OPENAI_CHAT_SYSTEM_PROMPT} 当前只允许重排给定 Rime 候选, "
            "不要创造新候选, 不要解释。"
        )
    if resolved == PREDICTION_REQUEST_NO_INPUT:
        return (
            f"{OPENAI_CHAT_SYSTEM_PROMPT} 当前没有正在编辑的拼音, "
            "只预测最可能接在已上屏上下文后面的短候选。"
        )
    return OPENAI_CHAT_SYSTEM_PROMPT


def _openai_prediction_user_content(
    *,
    context: str,
    query: str,
    max_candidates: int,
    request_type: str,
    rime_candidates: tuple[str, ...],
) -> str:
    resolved = normalize_prediction_request_type(request_type)
    rime_line = "、".join(normalized_rime_candidate_texts(rime_candidates))
    if resolved == PREDICTION_REQUEST_RIME_REORDER and rime_line:
        return (
            f"上下文: {context}\n"
            f"当前输入: {query}\n"
            f"Rime候选: {rime_line}\n"
            f"请只从 Rime候选 中选出并重排前 {max_candidates} 个, 用空格分隔。"
        )
    if resolved == PREDICTION_REQUEST_PINYIN_CONSTRAINED:
        return (
            f"上下文: {context}\n"
            f"当前拼音或前缀: {query}\n"
            f"Rime候选: {rime_line}\n"
            f"请预测 {max_candidates} 个能匹配当前拼音/前缀的短候选, 用空格分隔。"
        )
    if resolved == PREDICTION_REQUEST_NO_INPUT:
        return (
            f"已上屏上下文: {context}\n"
            f"请预测 {max_candidates} 个最可能接在上下文后面的短候选, 用空格分隔。"
        )
    return (
        f"上下文: {context}\n"
        f"当前输入: {query}\n"
        f"请预测 {max_candidates} 个最可能的短候选, 用空格分隔。"
    )


def _openai_completion_prefix(
    *,
    context: str,
    query: str,
    request_type: str,
    rime_candidates: tuple[str, ...],
) -> str:
    resolved = normalize_prediction_request_type(request_type)
    rime_tuple = normalized_rime_candidate_texts(rime_candidates)
    if resolved == PREDICTION_REQUEST_RIME_REORDER and rime_tuple:
        return compact_whitespace(f"按上下文重排候选: {' '.join(rime_tuple)}\n排序:")
    if resolved == PREDICTION_REQUEST_PINYIN_CONSTRAINED and rime_tuple:
        return compact_whitespace(f"{context}{query} 候选 {' '.join(rime_tuple)}")
    return compact_whitespace(f"{context}{query}")


def _status_prompt_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized in {"ollama-chat", "mlx-service"}:
        return normalized
    return _normalized_prompt_mode(normalized)


def _ollama_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3].rstrip("/")
    return normalized


def _ollama_chat_body(
    config: Any,
    *,
    context: str,
    query: str,
    max_candidates: int,
    stream: bool,
) -> dict[str, Any]:
    stream_first_prompt = bool(stream)
    system_prompt = OLLAMA_STREAM_FIRST_SYSTEM_PROMPT if stream_first_prompt else OLLAMA_CHAT_SYSTEM_PROMPT
    user_content = (
        f"上下文: {context}\n"
        f"当前输入: {query}\n"
        "只输出 1 个最可能接在当前输入后面的短候选, 不要重复当前输入。"
        if stream_first_prompt
        else (
            f"上下文: {context}\n"
            f"当前输入: {query}\n"
            f"输出 {max_candidates} 个最可能接在当前输入后面的短候选, 不要重复当前输入。"
        )
    )
    options = {
        "num_predict": max(1, min(64, int(getattr(config, "max_tokens", 12)))),
        "temperature": float(getattr(config, "temperature", 0.2)),
        "top_p": float(getattr(config, "top_p", 0.9)),
    }
    body: dict[str, Any] = {
        "model": str(getattr(config, "model", "")),
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "stream": stream,
        "think": False,
        "options": options,
    }
    extra_body = getattr(config, "extra_body", None)
    if isinstance(extra_body, dict) and extra_body:
        extra_body_copy = dict(extra_body)
        extra_options = extra_body_copy.pop("options", None)
        if isinstance(extra_options, dict):
            body["options"] = {**options, **extra_options}
        body.update(extra_body_copy)
    return body


def _mlx_predict_body(
    config: Any,
    *,
    context: str,
    query: str,
    max_candidates: int,
    stream: bool,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
) -> dict[str, Any]:
    resolved_request_type = normalize_prediction_request_type(request_type)
    rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
    body: dict[str, Any] = {
        "model": str(getattr(config, "model", "")),
        "currentInput": query,
        "recentContext": context,
        "requestType": resolved_request_type,
        "rimeCandidates": list(rime_candidate_tuple),
        "maxCandidates": max(1, min(10, int(max_candidates))),
        "maxTokens": max(1, min(64, int(getattr(config, "max_tokens", 8)))),
        "temperature": float(getattr(config, "temperature", 0.15)),
        "topP": float(getattr(config, "top_p", 0.85)),
        "stream": stream,
        "profile": str(getattr(config, "profile", "custom")),
        **_prediction_request_metadata(
            context=context,
            query=query,
            stable_prefix=MLX_STABLE_PREFIX,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        ),
    }
    extra_body = getattr(config, "extra_body", None)
    if isinstance(extra_body, dict) and extra_body:
        body.update(extra_body)
    return body


def _mlx_raw_texts_from_payload(payload: dict[str, Any]) -> list[str]:
    raw_texts: list[str] = []
    for key in ("rawText", "text", "content", "completion"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            raw_texts.append(value)
    if not raw_texts and isinstance(payload.get("candidates"), list):
        raw_texts.extend(str(item) for item in payload["candidates"] if isinstance(item, str))
    return raw_texts


def _mlx_stream_text_delta(payload: dict[str, Any]) -> str:
    for key in ("delta", "text", "content", "chunk"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _prediction_request_metadata(
    *,
    context: str,
    query: str,
    stable_prefix: str = "",
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
) -> dict[str, object]:
    resolved_request_type = normalize_prediction_request_type(request_type)
    rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
    return {
        "currentInputFingerprint": _short_hash(compact_whitespace(query)),
        "contextFingerprint": _short_hash(compact_whitespace(context)),
        "contextChars": len(compact_whitespace(context)),
        "stablePrefixHash": _short_hash(stable_prefix),
        "requestType": resolved_request_type,
        "rimeCandidateCount": len(rime_candidate_tuple),
        "rimeCandidatesFingerprint": _short_hash("\x1f".join(rime_candidate_tuple)),
    }


def normalize_prediction_request_type(value: object) -> str:
    text = compact_whitespace(str(value or "")).lower().replace("-", "_")
    if text in {
        PREDICTION_REQUEST_NO_INPUT,
        PREDICTION_REQUEST_PINYIN_CONSTRAINED,
        PREDICTION_REQUEST_RIME_REORDER,
    }:
        return text
    return PREDICTION_REQUEST_GENERIC


def normalized_rime_candidate_texts(values: tuple[str, ...] | list[str] | object) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = compact_whitespace(str(value or ""))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= 10:
            break
    return tuple(result)


def predict_with_optional_request_context(
    provider: PredictionProvider,
    *,
    current_input: str,
    recent_context: str = "",
    max_candidates: int = 5,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
) -> list[ModelPrediction]:
    try:
        signature = inspect.signature(provider.predict)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        parameters = signature.parameters
        has_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
        supports_context = has_kwargs or "request_type" in parameters or "rime_candidates" in parameters
        if supports_context:
            return provider.predict(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                request_type=normalize_prediction_request_type(request_type),
                rime_candidates=normalized_rime_candidate_texts(rime_candidates),
            )
    return provider.predict(
        current_input=current_input,
        recent_context=recent_context,
        max_candidates=max_candidates,
    )


def _short_hash(text: str) -> str:
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _int_from_payload(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _percentile_ms(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * max(0.0, min(1.0, percentile))))
    return ordered[index]


def _float_env(env: dict[str, str], name: str, fallback: float) -> float:
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def _non_negative_float_env(env: dict[str, str], name: str, fallback: float) -> float:
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return fallback
    return value if value >= 0 else fallback


def _json_object_env(env: dict[str, str], name: str) -> dict[str, Any]:
    raw = env.get(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _prediction_extra_body_from_env(env: dict[str, str], *, disable_thinking_default: bool = False) -> dict[str, Any]:
    extra_body = _json_object_env(env, "RAG_IME_PREDICTOR_EXTRA_BODY_JSON")
    if _bool_env(env, "RAG_IME_PREDICTOR_DISABLE_THINKING", default=disable_thinking_default):
        chat_template_kwargs = extra_body.get("chat_template_kwargs")
        if not isinstance(chat_template_kwargs, dict):
            chat_template_kwargs = {}
        extra_body = {
            **extra_body,
            "chat_template_kwargs": {
                **chat_template_kwargs,
                "enable_thinking": False,
            },
        }
    return extra_body


def _normalized_predictor_profile(profile: str) -> str:
    normalized = (profile or "custom").strip().lower()
    aliases = {
        "fast": "instant",
        "qwen-instant": "instant",
        "no-thinking": "instant",
        "nothinking": "instant",
        "base": "completion-instant",
        "prefix": "completion-instant",
        "completion": "completion-instant",
        "base-instant": "completion-instant",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"custom", "instant", "completion-instant"}:
        return normalized
    return "custom"


def _prediction_profile_defaults(profile: str) -> PredictionProfileDefaults:
    normalized = _normalized_predictor_profile(profile)
    if normalized == "instant":
        return PredictionProfileDefaults(
            prompt_mode="chat",
            timeout_ms=350,
            max_tokens=8,
            temperature=0.15,
            top_p=0.85,
            disable_thinking=True,
        )
    if normalized == "completion-instant":
        return PredictionProfileDefaults(
            prompt_mode="completion",
            timeout_ms=350,
            max_tokens=8,
            temperature=0.15,
            top_p=0.9,
            disable_thinking=False,
        )
    return PredictionProfileDefaults()


def _prediction_provider_profile(provider: PredictionProvider) -> str:
    config = getattr(provider, "config", None)
    profile = getattr(config, "profile", "")
    return profile if isinstance(profile, str) and profile else "none"


def _prediction_provider_capabilities(provider_name: str) -> dict[str, bool]:
    if provider_name == "local-mlx":
        return {
            "streaming": True,
            "residentModel": True,
            "promptCache": False,
            "textOnlyModel": False,
            "sequenceFork": False,
            "batchCandidates": True,
            "logitsTopK": True,
            "serverTiming": True,
        }
    if provider_name == "local-ollama":
        return {
            "streaming": True,
            "residentModel": True,
            "promptCache": False,
            "textOnlyModel": False,
            "sequenceFork": False,
            "batchCandidates": False,
            "logitsTopK": False,
            "serverTiming": True,
        }
    if provider_name == "local-openai-compatible":
        return {
            "streaming": False,
            "residentModel": False,
            "promptCache": False,
            "sequenceFork": False,
            "batchCandidates": False,
            "logitsTopK": False,
            "serverTiming": False,
        }
    return {
        "streaming": False,
        "residentModel": False,
        "promptCache": False,
        "textOnlyModel": False,
        "sequenceFork": False,
        "batchCandidates": False,
        "logitsTopK": False,
        "serverTiming": False,
    }


def _prompt_cache_used_for_generation(prompt_cache: dict[str, Any]) -> bool:
    return (
        bool(prompt_cache.get("enabled"))
        and bool(prompt_cache.get("prepared"))
        and bool(prompt_cache.get("cacheFileReady"))
        and bool(prompt_cache.get("usedForGeneration"))
    )


def _prediction_error_name(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if reason:
            return f"url_error:{reason}"
        return "url_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return exc.__class__.__name__


def _probe_openai_compatible_models(provider: PredictionProvider) -> dict[str, Any]:
    config = getattr(provider, "config", None)
    if config is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "not_configured",
            "modelIds": [],
            "configuredModelFound": False,
        }
    provider_name = str(getattr(config, "provider_name", ""))
    if provider_name == "local-ollama":
        url = f"{str(getattr(config, 'base_url', '')).rstrip('/')}/api/tags"
    else:
        url = f"{str(getattr(config, 'base_url', '')).rstrip('/')}/v1/models"
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        headers=_headers_from_prediction_config(config),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(getattr(config, "timeout_s", 0.8))) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status_code = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        return _prediction_probe_error(url=url, started=started, error=f"http_{exc.code}", status_code=exc.code)
    except TimeoutError:
        return _prediction_probe_error(url=url, started=started, error="timeout")
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return _prediction_probe_error(url=url, started=started, error=str(exc))

    model_ids = _model_ids_from_models_payload(payload)
    configured_model = str(getattr(config, "model", ""))
    return {
        "ok": True,
        "skipped": False,
        "url": url,
        "statusCode": status_code,
        "elapsedMs": int((time.perf_counter() - started) * 1000),
        "modelCount": len(model_ids),
        "modelIds": model_ids[:20],
        "configuredModel": configured_model,
        "configuredModelFound": configured_model in model_ids if model_ids else False,
    }


def _prediction_probe_error(
    *,
    url: str,
    started: float,
    error: str,
    status_code: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "skipped": False,
        "url": url,
        "elapsedMs": int((time.perf_counter() - started) * 1000),
        "error": error,
        "modelIds": [],
        "configuredModelFound": False,
    }
    if status_code is not None:
        payload["statusCode"] = status_code
    return payload


def _model_ids_from_models_payload(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        models = payload.get("models")
        if not isinstance(models, list):
            return []
        data = models
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            ids.append(item["name"])
        elif isinstance(item, dict) and isinstance(item.get("model"), str):
            ids.append(item["model"])
    return ids


def _headers_from_prediction_config(config: Any) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = getattr(config, "api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    extra_headers = getattr(config, "extra_headers", None)
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items()})
    return headers


def _prediction_doctor_next_actions(*, status: dict[str, object], checks: dict[str, Any]) -> list[str]:
    if not status.get("configured"):
        return [
            "Set RAG_IME_PREDICTOR_PROVIDER=openai-compatible, ollama, or mlx.",
            "Set RAG_IME_PREDICTOR_BASE_URL and RAG_IME_PREDICTOR_MODEL.",
            "Use RAG_IME_PREDICTOR_PROFILE=instant for the first Qwen-style test.",
        ]
    model_probe = checks["modelsEndpoint"]
    prediction = checks["prediction"]
    actions: list[str] = []
    if not model_probe.get("ok"):
        if prediction.get("hasCandidates"):
            actions.append("The prediction endpoint works, but /v1/models failed; verify the model id manually.")
        else:
            actions.append("Start the local or WSL OpenAI-compatible model server and verify /v1/models.")
    elif not model_probe.get("configuredModelFound") and model_probe.get("modelIds"):
        actions.append("Set RAG_IME_PREDICTOR_MODEL to one of the model ids returned by /v1/models.")
    if not prediction.get("hasCandidates"):
        actions.append("Run predict-benchmark with a simple case and inspect model output or parser cleanup.")
    if not prediction.get("withinBudget"):
        actions.append("Use a smaller/non-thinking model, reduce max tokens, or switch to completion-instant/KV-cache serving.")
    return actions or ["Run eval-prediction and eval-comparison before enabling model side candidates by default."]


def _json_string_map_env(env: dict[str, str], name: str) -> dict[str, str]:
    raw = _json_object_env(env, name)
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result


def _bool_env(env: dict[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default
