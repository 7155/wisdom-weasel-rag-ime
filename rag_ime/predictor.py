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


@dataclass(frozen=True)
class PredictionBenchmarkCase:
    current_input: str
    recent_context: str = ""


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
    ) -> list[ModelPrediction]:
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
    ) -> list[ModelPrediction]:
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        max_items = max(1, min(10, int(max_candidates)))
        self.last_error = ""
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
                    "profile": self.config.profile,
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
        except (TimeoutError, urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            self.last_error = _prediction_error_name(exc)
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
    ) -> list[ModelPrediction]:
        query = compact_whitespace(current_input)
        context = compact_whitespace(recent_context)[-420:]
        if not query and not context:
            return []
        max_items = max(1, min(10, int(max_candidates)))
        self.last_error = ""
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
                    "profile": self.config.profile,
                    "prompt_mode": self.config.prompt_mode,
                    "raw_text": raw_text,
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers


class CooldownPredictionProvider:
    """Circuit breaker for the IME model lane.

    The OpenAI-compatible provider already fails open, but a dead endpoint can
    still cost one timeout per composing refresh. This wrapper skips temporary
    repeat calls after transport failures or slow empty responses.
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
    ) -> list[ModelPrediction]:
        now = time.perf_counter()
        if self.cooldown_ms > 0 and now < self._state.cooldown_until:
            self._state.skipped_count += 1
            return []

        started = time.perf_counter()
        predictions = self.delegate.predict(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        delegate_error = str(getattr(self.delegate, "last_error", "") or "")
        failed_transport = bool(delegate_error)
        slow_empty = not predictions and elapsed_ms >= self.failure_latency_ms
        if failed_transport or slow_empty:
            self._state.failure_count += 1
            self._state.last_error = delegate_error or "slow_empty_prediction"
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


def prediction_provider_from_env(env: dict[str, str] | None = None) -> PredictionProvider:
    source = env or os.environ
    provider = source.get("RAG_IME_PREDICTOR_PROVIDER", "").strip().lower()
    base_url = source.get("RAG_IME_PREDICTOR_BASE_URL", "").strip()
    model = source.get("RAG_IME_PREDICTOR_MODEL", "").strip()
    if provider == "ollama" and not base_url:
        base_url = "http://127.0.0.1:11434"
    if provider not in ("openai", "openai-compatible", "ollama") or not base_url or not model:
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
            )
        )
    else:
        configured_provider = OpenAICompatiblePredictionProvider(
            OpenAICompatiblePredictionConfig(
            base_url=base_url,
            model=model,
            api_key=source.get("RAG_IME_PREDICTOR_API_KEY", "").strip(),
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


def prediction_provider_status(provider: PredictionProvider) -> dict[str, object]:
    config = getattr(provider, "config", None)
    configured = provider.__class__.__name__ != "NullPredictionProvider"
    if config is None:
        return {
            "configured": configured,
            "providerName": provider.__class__.__name__,
            "providerProfile": "none",
            "promptMode": "none",
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
    }
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
    latency_budget_ms: int = 200,
    keep_alive: int | str | None = -1,
) -> dict[str, Any]:
    status = prediction_provider_status(provider)
    provider_name = str(status.get("providerName") or provider.__class__.__name__)
    config = getattr(provider, "config", None)
    supported = bool(config is not None and getattr(config, "provider_name", "") == "local-ollama")
    if not supported:
        return {
            "schemaVersion": "rag-ime.predictor-ttft.v1",
            "providerName": provider_name,
            "providerProfile": _prediction_provider_profile(provider),
            "providerConfigured": bool(status.get("configured")),
            "supported": False,
            "reason": "streaming_ttft_currently_supports_native_ollama_only",
            "latencyBudgetMs": latency_budget_ms,
            "summary": {
                "caseCount": 0,
                "sampleCount": 0,
                "hasFirstChunk": False,
                "allWithinBudget": False,
            },
            "cases": [],
        }

    results: list[dict[str, Any]] = []
    first_chunk_latencies = []
    total_latencies = []
    repeat_count = max(1, int(repeat))
    for repeat_index in range(1, repeat_count + 1):
        for case in cases:
            measured = _measure_ollama_stream_ttft(
                config,
                current_input=case.current_input,
                recent_context=case.recent_context,
                max_candidates=max_candidates,
                keep_alive=keep_alive,
            )
            measured["currentInput"] = case.current_input
            if repeat_count > 1:
                measured["repeatIndex"] = repeat_index
            first_ms = measured.get("firstChunkMs")
            if isinstance(first_ms, int):
                first_chunk_latencies.append(first_ms)
            total_ms = measured.get("totalMs")
            if isinstance(total_ms, int):
                total_latencies.append(total_ms)
            measured["overBudget"] = not isinstance(first_ms, int) or first_ms > latency_budget_ms
            results.append(measured)
    first_chunk_missing_count = sum(1 for item in results if not isinstance(item.get("firstChunkMs"), int))
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
        "summary": {
            "caseCount": len(cases),
            "sampleCount": len(results),
            "hasFirstChunk": bool(first_chunk_latencies),
            "p50FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.50),
            "p95FirstChunkMs": _percentile_ms(first_chunk_latencies, 0.95),
            "minFirstChunkMs": min(first_chunk_latencies) if first_chunk_latencies else 0,
            "maxFirstChunkMs": max(first_chunk_latencies) if first_chunk_latencies else 0,
            "p50TotalMs": _percentile_ms(total_latencies, 0.50),
            "p95TotalMs": _percentile_ms(total_latencies, 0.95),
            "allWithinBudget": bool(results) and over_budget_count == 0,
            "overBudgetCount": over_budget_count,
            "firstChunkMissingCount": first_chunk_missing_count,
            "failureCount": sum(1 for item in results if not bool(item.get("ok"))),
            "candidateSampleCount": sum(1 for item in results if int(item.get("candidateCount") or 0) > 0),
        },
        "cases": results,
    }


def _measure_ollama_stream_ttft(
    config: Any,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    keep_alive: int | str | None,
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
    full_text = ""
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
    candidates = _parse_prediction_candidate_texts([full_text], max_candidates=max_candidates)
    return {
        "ok": first_chunk_ms is not None,
        "firstChunkMs": first_chunk_ms,
        "totalMs": total_ms,
        "firstText": first_text,
        "rawText": full_text,
        "candidateCount": len(candidates),
        "candidates": candidates,
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


def _status_prompt_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized == "ollama-chat":
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
                "content": (
                    "你是中文输入法候选预测器。只输出 JSON 字符串数组, "
                    '例如 ["本地记忆输入法","RAG候选","历史上下文"], 不要解释。'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"上下文: {context}\n"
                    f"当前输入: {query}\n"
                    f"输出 {max_candidates} 个最可能的短候选。"
                ),
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
            "Set RAG_IME_PREDICTOR_PROVIDER=openai-compatible or ollama.",
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
