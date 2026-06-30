from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .models import ModelPrediction
from .text_utils import compact_whitespace


class PredictionProvider(Protocol):
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
    ) -> list[ModelPrediction]:
        ...


@dataclass(frozen=True)
class OpenAICompatiblePredictionConfig:
    base_url: str
    model: str
    api_key: str = ""
    prompt_mode: str = "chat"
    timeout_s: float = 0.8
    max_tokens: int = 12
    temperature: float = 0.2
    top_p: float = 0.9
    provider_name: str = "local-openai-compatible"
    extra_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None


@dataclass(frozen=True)
class PredictionBenchmarkCase:
    current_input: str
    recent_context: str = ""


class NullPredictionProvider:
    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
    ) -> list[ModelPrediction]:
        return []


class OpenAICompatiblePredictionProvider:
    """Fast local LLM prediction lane, inspired by Wisdom-Weasel's provider boundary.

    This provider intentionally asks for very short candidates and uses an
    aggressive timeout. A slow model must fail open so typing stays responsive.
    """

    def __init__(self, config: OpenAICompatiblePredictionConfig):
        self.config = config

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
    ) -> list[ModelPrediction]:
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        max_items = max(1, min(10, int(max_candidates)))
        started = time.perf_counter()
        raw_texts = self._complete(context=context, query=query, max_candidates=max_items)
        latency_ms = int((time.perf_counter() - started) * 1000)
        raw_text = "\n".join(raw_texts)
        candidates = _parse_prediction_candidate_texts(raw_texts, max_candidates=max_items)
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
                    "prompt_mode": _normalized_prompt_mode(self.config.prompt_mode),
                    "raw_text": raw_text,
                },
            )
            for index, item in enumerate(candidates, start=1)
        ]

    def _complete(self, *, context: str, query: str, max_candidates: int) -> list[str]:
        if _normalized_prompt_mode(self.config.prompt_mode) == "completion":
            return self._complete_with_prefix(context=context, query=query, max_candidates=max_candidates)
        return self._complete_with_chat(context=context, query=query, max_candidates=max_candidates)

    def _complete_with_chat(self, *, context: str, query: str, max_candidates: int) -> list[str]:
        body = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个本地中文输入法预测器。只输出候选词或短语, "
                        "候选之间用单个空格分隔, 不要解释, 不要编号。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"上下文: {context}\n"
                        f"当前输入: {query}\n"
                        f"请预测 {max_candidates} 个最可能的短候选:"
                    ),
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
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError):
            return []
        return extract_openai_contents(payload)

    def _complete_with_prefix(self, *, context: str, query: str, max_candidates: int) -> list[str]:
        prefix = compact_whitespace(f"{context}{query}")
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
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError):
            return []
        return extract_openai_contents(payload)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers


def prediction_provider_from_env(env: dict[str, str] | None = None) -> PredictionProvider:
    source = env or os.environ
    provider = source.get("RAG_IME_PREDICTOR_PROVIDER", "").strip().lower()
    base_url = source.get("RAG_IME_PREDICTOR_BASE_URL", "").strip()
    model = source.get("RAG_IME_PREDICTOR_MODEL", "").strip()
    if provider not in ("openai", "openai-compatible") or not base_url or not model:
        return NullPredictionProvider()
    return OpenAICompatiblePredictionProvider(
        OpenAICompatiblePredictionConfig(
            base_url=base_url,
            model=model,
            api_key=source.get("RAG_IME_PREDICTOR_API_KEY", "").strip(),
            prompt_mode=source.get("RAG_IME_PREDICTOR_PROMPT_MODE", "chat").strip(),
            timeout_s=_float_env(source, "RAG_IME_PREDICTOR_TIMEOUT_MS", 800) / 1000,
            max_tokens=int(_float_env(source, "RAG_IME_PREDICTOR_MAX_TOKENS", 12)),
            temperature=_float_env(source, "RAG_IME_PREDICTOR_TEMPERATURE", 0.2),
            top_p=_float_env(source, "RAG_IME_PREDICTOR_TOP_P", 0.9),
            provider_name="local-openai-compatible",
            extra_body=_json_object_env(source, "RAG_IME_PREDICTOR_EXTRA_BODY_JSON"),
            extra_headers=_json_string_map_env(source, "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON"),
        )
    )


def benchmark_prediction_provider(
    provider: PredictionProvider,
    cases: list[PredictionBenchmarkCase],
    *,
    max_candidates: int = 3,
    latency_budget_ms: int = 150,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    latencies: list[int] = []
    provider_name = provider.__class__.__name__
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
        "providerConfigured": provider_name != "NullPredictionProvider",
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


def parse_prediction_candidates(text: str, *, max_candidates: int = 5) -> list[str]:
    return _parse_prediction_candidate_texts([text], max_candidates=max_candidates)


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


def _candidate_parts_from_text(text: str) -> list[str]:
    cleaned = _clean_prediction_output(text)
    if not cleaned:
        return []
    json_candidates = _candidate_parts_from_json_text(cleaned)
    if json_candidates:
        return json_candidates
    parts = re.split(r"[\s,，、;；|/]+", cleaned)
    candidates: list[str] = []
    for part in parts:
        item = re.sub(r"^\d+[.)、．]?", "", part)
        item = item.strip("。.!！?？:\"'“”‘’[]()（）")
        if not item:
            continue
        candidates.append(item)
    return candidates


def _clean_prediction_output(text: str) -> str:
    cleaned = re.sub(r"(?is)<think>.*?</think>", " ", text)
    cleaned = re.sub(r"(?is)<think>.*", " ", cleaned)
    cleaned = re.sub(r"(?is)<analysis>.*?</analysis>", " ", cleaned)
    cleaned = re.sub(r"(?is)<reasoning>.*?</reasoning>", " ", cleaned)
    cleaned = cleaned.replace("```json", " ").replace("```", " ")
    return compact_whitespace(cleaned)


def _candidate_parts_from_json_text(text: str) -> list[str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _candidate_parts_from_json_value(parsed)


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


def _float_env(env: dict[str, str], name: str, fallback: float) -> float:
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def _json_object_env(env: dict[str, str], name: str) -> dict[str, Any]:
    raw = env.get(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_string_map_env(env: dict[str, str], name: str) -> dict[str, str]:
    raw = _json_object_env(env, name)
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result
