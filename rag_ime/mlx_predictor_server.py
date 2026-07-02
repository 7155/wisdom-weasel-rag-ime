from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

from .predictor import parse_prediction_candidates
from .text_utils import compact_whitespace


SYSTEM_PROMPT = (
    "你是 Prediction-first 中文输入法的本地续写模型。任务是根据用户已经上屏的上下文, "
    "输出可以直接接在光标后的中文短语或短句。"
    '只返回 JSON 字符串数组, 例如 ["把流程跑通","接入本地记忆","验证 LLM 候选"], '
    "不要解释, 不要编号, 不要输出拼音, 不要输出<think>。"
    "不要输出泛词或传统词库噪声: 根据、基于、和、测试、分析、假设、或者、现在、目前、当前、然后。"
)

LOGITS_SYSTEM_PROMPT = (
    "你是 Prediction-first 中文输入法的本地续写模型。根据用户已经上屏的上下文, "
    "直接给出最可能接在光标后的中文短语。不要解释, 不要编号, 不要 JSON, 不要拼音。"
    "不要输出泛词: 根据、基于、和、测试、分析、假设、或者、现在、目前、当前、然后。"
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LOW_VALUE_LOGITS_CANDIDATES = {
    "测试",
    "测试流程",
    "分析",
    "分析问题",
    "并且",
    "但是",
    "或者",
    "基于",
    "根据",
    "生成",
    "假设",
    "然后",
    "现在",
    "目前",
    "当前",
    "当前问题",
    "当前流程",
    "的",
    "了",
    "和",
    "是",
}


@dataclass(frozen=True)
class MlxPredictorServerConfig:
    host: str = "127.0.0.1"
    port: int = 8767
    model: str = ""
    max_tokens: int = 8
    temperature: float = 0.15
    top_p: float = 0.85
    prompt_cache: bool = False
    prompt_cache_max_kv_size: int = 0


class MlxLmEngine:
    """Resident MLX-LM engine for the IME model lane.

    This module intentionally imports MLX-LM lazily so the rest of RAG-IME can
    run on machines where MLX is not installed. The loaded process owns model
    memory; the IME talks to it over a tiny local HTTP protocol.
    """

    def __init__(
        self,
        model_id: str,
        *,
        enable_prompt_cache: bool = False,
        prompt_cache_max_kv_size: int = 0,
    ):
        if not model_id:
            raise RuntimeError("MLX predictor requires --model or RAG_IME_MLX_MODEL")
        try:
            from mlx_lm import load  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local Mac setup
            raise RuntimeError("Install mlx-lm before running mlx-predictor-server") from exc

        self.model_id = model_id
        self.model_info = _inspect_local_mlx_model(model_id)
        self.model, self.tokenizer = load(model_id)
        self._prompt_cache = _PromptCacheState(
            enabled=bool(enable_prompt_cache),
            stable_prefix=self._stable_prompt_prefix(),
            max_kv_size=max(0, int(prompt_cache_max_kv_size)),
        )
        if self._prompt_cache.enabled:
            self._prepare_prompt_cache()

    def health(self) -> dict[str, Any]:
        prompt_cache = self.prompt_cache_status()
        return {
            "ok": True,
            "provider": "mlx-lm",
            "model": self.model_id,
            "modelLoaded": True,
            "modelInfo": self.model_info,
            "promptCache": prompt_cache,
            "capabilities": {
                "streaming": True,
                "residentModel": True,
                "promptCache": _prompt_cache_used_for_generation(prompt_cache),
                "textOnlyModel": bool(self.model_info.get("textOnly")),
                "sequenceFork": False,
                "batchCandidates": True,
                "logitsTopK": True,
                "serverTiming": True,
            },
        }

    def prompt_cache_status(self) -> dict[str, Any]:
        return self._prompt_cache.to_payload()

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        logits_candidates = self.predict_next_token_logits(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            request_metadata=request_metadata,
        )
        if _logits_candidates_are_ime_quality(logits_candidates["candidates"], max_candidates=max_candidates):
            total_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "model": self.model_id,
                "rawText": " ".join(logits_candidates["candidates"]),
                "candidates": logits_candidates["candidates"],
                "candidateScores": logits_candidates["candidateScores"],
                "candidateMode": "next-token-logits",
                "totalMs": total_ms,
                "promptCache": self.prompt_cache_status(),
                "timing": {
                    "candidateMode": "next-token-logits",
                    "logitsMs": logits_candidates["elapsedMs"],
                    "fallbackJson": False,
                },
                "requestMeta": dict(request_metadata or {}),
            }

        raw_text = "".join(
            self.stream_text(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                request_metadata=request_metadata,
            )
        )
        total_ms = int((time.perf_counter() - started) * 1000)
        candidates = parse_prediction_candidates(raw_text, max_candidates=max_candidates)
        return {
            "ok": True,
            "model": self.model_id,
            "rawText": raw_text,
            "candidates": candidates,
            "candidateMode": "json-generation",
            "totalMs": total_ms,
            "promptCache": self.prompt_cache_status(),
            "timing": {
                "candidateMode": "json-generation",
                "logitsMs": logits_candidates.get("elapsedMs", 0),
                "fallbackJson": True,
                "fallbackReason": logits_candidates.get("qualityReason") or "logits_candidates_not_phrase_quality",
            },
            "requestMeta": dict(request_metadata or {}),
        }

    def predict_next_token_logits(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = request_metadata
        started = time.perf_counter()
        try:
            from mlx_lm.generate import generate_step  # type: ignore
            import mlx.core as mx  # type: ignore

            prompt = self._build_logits_prompt(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
            )
            tokens = self.tokenizer.encode(prompt)
            token, logprobs = next(generate_step(mx.array(tokens), self.model, max_tokens=1))
            candidate_scores = self._candidate_scores_from_logprobs(
                logprobs,
                max_candidates=max_candidates,
                scan_limit=max(64, max_candidates * 24),
            )
            return {
                "candidates": [item["text"] for item in candidate_scores],
                "candidateScores": candidate_scores,
                "sampledTokenId": _token_to_int(token),
                "elapsedMs": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
            return {
                "candidates": [],
                "candidateScores": [],
                "error": exc.__class__.__name__,
                "elapsedMs": int((time.perf_counter() - started) * 1000),
            }

    def _candidate_scores_from_logprobs(
        self,
        logprobs: Any,
        *,
        max_candidates: int,
        scan_limit: int,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for token_id in _top_logprob_indices(logprobs, limit=max(1, int(scan_limit))):
            text = _normalize_logits_candidate_text(self.tokenizer.decode([int(token_id)]))
            if not text or text in seen:
                continue
            if text in _LOW_VALUE_LOGITS_CANDIDATES:
                continue
            if len(text) > 8 or not _CJK_RE.search(text):
                continue
            seen.add(text)
            logprob = _logprob_at(logprobs, int(token_id))
            item: dict[str, Any] = {
                "text": text,
                "tokenId": int(token_id),
            }
            if logprob is not None:
                item["logprob"] = logprob
                item["probability"] = max(0.0, min(1.0, math.exp(max(-60.0, min(0.0, logprob)))))
            result.append(item)
            if len(result) >= max(1, min(10, int(max_candidates))):
                break
        return result

    def stream_text(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request_metadata: dict[str, Any] | None = None,
    ) -> Iterable[str]:
        _ = request_metadata
        prompt = self._build_prompt(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
        )
        if self._prompt_cache.ready_for_generation():
            try:
                for text in self._stream_text_with_prompt_cache(
                    current_input=current_input,
                    recent_context=recent_context,
                    max_candidates=max_candidates,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                ):
                    yield text
                return
            except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
                self._prompt_cache.miss_count += 1
                self._prompt_cache.error = f"cached_generation:{exc.__class__.__name__}"

        if self._prompt_cache.enabled:
            self._prompt_cache.miss_count += 1
        for text in self._stream_text_with_generate_step(
            prompt=prompt,
            max_tokens=max(1, min(64, int(max_tokens))),
            temperature=float(temperature),
            top_p=float(top_p),
        ):
            yield text

    def _stream_text_with_prompt_cache(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> Iterable[str]:
        from mlx_lm.generate import generate_step  # type: ignore
        from mlx_lm.models.cache import load_prompt_cache  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
        import mlx.core as mx  # type: ignore

        cache = load_prompt_cache(str(self._prompt_cache.cache_file))
        dynamic_prompt = self._dynamic_prompt_suffix(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
        )
        self._prompt_cache.used_for_generation = True
        self._prompt_cache.hit_count += 1
        self._prompt_cache.error = ""
        for text in self._stream_text_with_generate_step(
            prompt=dynamic_prompt,
            max_tokens=max(1, min(64, int(max_tokens))),
            temperature=float(temperature),
            top_p=float(top_p),
            prompt_cache=cache,
        ):
            yield text

    def _stream_text_with_generate_step(
        self,
        *,
        prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        prompt_cache: Any | None = None,
    ) -> Iterable[str]:
        from mlx_lm.generate import generate_step  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
        import mlx.core as mx  # type: ignore

        tokens = self.tokenizer.encode(prompt)
        sampler = make_sampler(temp=max(0.0, float(temperature)), top_p=max(0.0, float(top_p)))
        emitted = ""
        generated_tokens: list[int] = []
        for token, _logprobs in generate_step(
            mx.array(tokens),
            self.model,
            max_tokens=max(1, min(64, int(max_tokens))),
            prompt_cache=prompt_cache,
            sampler=sampler,
        ):
            token_id = _token_to_int(token)
            generated_tokens.append(token_id)
            decoded = self.tokenizer.decode(generated_tokens)
            if isinstance(decoded, bytes):
                decoded = decoded.decode("utf-8", errors="ignore")
            if not isinstance(decoded, str):
                decoded = str(decoded)
            delta = decoded[len(emitted) :]
            emitted = decoded
            if delta:
                yield delta

    def _stable_prompt_prefix(self) -> str:
        return f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n"

    def _dynamic_prompt_suffix(self, *, current_input: str, recent_context: str, max_candidates: int) -> str:
        return (
            f"{_build_mlx_dynamic_prompt(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates)}"
            "\n/no_think"
            "<|im_end|>\n<|im_start|>assistant\n"
        )

    def _build_prompt(self, *, current_input: str, recent_context: str, max_candidates: int) -> str:
        return (
            f"{self._stable_prompt_prefix()}"
            f"{self._dynamic_prompt_suffix(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates)}"
        )

    def _build_logits_prompt(self, *, current_input: str, recent_context: str, max_candidates: int) -> str:
        return (
            f"<|im_start|>system\n{LOGITS_SYSTEM_PROMPT}<|im_end|>\n"
            "<|im_start|>user\n"
            f"上下文: {recent_context}\n"
            f"当前输入: {current_input}\n"
            f"给出 {max_candidates} 个候选中最可能的第一个候选, 直接从候选文本开始。"
            "\n/no_think"
            "<|im_end|>\n<|im_start|>assistant\n"
        )

    def _prepare_prompt_cache(self) -> None:
        started = time.perf_counter()
        try:
            from mlx_lm.generate import generate_step  # type: ignore
            from mlx_lm.models.cache import make_prompt_cache, save_prompt_cache  # type: ignore
            import mlx.core as mx  # type: ignore

            tokens = self.tokenizer.encode(self._prompt_cache.stable_prefix)
            self._prompt_cache.stable_prefix_tokens = len(tokens)
            kwargs: dict[str, Any] = {}
            if self._prompt_cache.max_kv_size > 0:
                kwargs["max_kv_size"] = self._prompt_cache.max_kv_size
            cache = make_prompt_cache(self.model, **kwargs)
            for _ in generate_step(mx.array(tokens), self.model, max_tokens=1, prompt_cache=cache):
                break
            handle = tempfile.NamedTemporaryFile(prefix="rag-ime-mlx-prefix-", suffix=".safetensors", delete=False)
            handle.close()
            save_prompt_cache(
                handle.name,
                cache,
                metadata={
                    "model": self.model_id,
                    "stablePrefixHash": self._prompt_cache.stable_prefix_hash(),
                },
            )
            self._prompt_cache.cache_file = handle.name
            self._prompt_cache.prepared = True
            self._prompt_cache.error = ""
        except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
            self._prompt_cache.prepared = False
            self._prompt_cache.error = exc.__class__.__name__
        finally:
            self._prompt_cache.prepare_ms = int((time.perf_counter() - started) * 1000)


def make_mlx_predictor_handler(engine: MlxLmEngine):
    class MlxPredictorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path == "/health":
                self._send_json(engine.health())
                return
            if self.path == "/v1/models":
                self._send_json({"data": [{"id": engine.model_id, "owned_by": "local-mlx"}]})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path not in {"/predict", "/predict-stream"}:
                self.send_error(404)
                return
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                self.send_error(400, "invalid JSON")
                return
            request = _normalize_prediction_request(payload, default_model=engine.model_id)
            if self.path == "/predict-stream":
                self._send_stream(engine, request)
                return
            result = engine.predict(**request)
            self._send_json(result)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}

        def _send_stream(self, engine: MlxLmEngine, request: dict[str, Any]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.end_headers()
            started = time.perf_counter()
            raw_text = ""
            for text in engine.stream_text(**request):
                raw_text += text
                self._write_json_line({"delta": text, "elapsedMs": int((time.perf_counter() - started) * 1000)})
            candidates = parse_prediction_candidates(raw_text, max_candidates=int(request["max_candidates"]))
            self._write_json_line(
                {
                    "done": True,
                    "rawText": raw_text,
                    "candidates": candidates,
                    "totalMs": int((time.perf_counter() - started) * 1000),
                    "promptCache": engine.prompt_cache_status(),
                    "requestMeta": dict(request.get("request_metadata") or {}),
                }
            )

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_json_line(self, payload: dict[str, Any]) -> None:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            self.wfile.flush()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return MlxPredictorHandler


def serve_mlx_predictor(config: MlxPredictorServerConfig) -> None:
    engine = MlxLmEngine(
        config.model,
        enable_prompt_cache=config.prompt_cache,
        prompt_cache_max_kv_size=config.prompt_cache_max_kv_size,
    )
    server = ThreadingHTTPServer((config.host, config.port), make_mlx_predictor_handler(engine))
    print(
        json.dumps(
            {
                "schemaVersion": "rag-ime.mlx-predictor-server.v1",
                "listening": f"http://{config.host}:{config.port}",
                "model": config.model,
                "maxTokens": config.max_tokens,
                "promptCache": engine.prompt_cache_status(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _normalize_prediction_request(payload: dict[str, Any], *, default_model: str) -> dict[str, Any]:
    _ = str(payload.get("model") or default_model)
    return {
        "current_input": compact_whitespace(str(payload.get("currentInput") or "")),
        "recent_context": compact_whitespace(str(payload.get("recentContext") or ""))[-420:],
        "max_candidates": max(1, min(10, _int_payload(payload.get("maxCandidates"), 3))),
        "max_tokens": max(1, min(64, _int_payload(payload.get("maxTokens"), 8))),
        "temperature": _float_payload(payload.get("temperature"), 0.15),
        "top_p": _float_payload(payload.get("topP"), 0.85),
        "request_metadata": _request_metadata_from_payload(payload),
    }


def _inspect_local_mlx_model(model_id: str) -> dict[str, Any]:
    path = Path(model_id).expanduser()
    info: dict[str, Any] = {
        "modelId": model_id,
        "localPath": path.exists(),
        "textOnly": False,
        "hasVisionConfig": False,
        "configPresent": False,
        "modelFileCount": 0,
        "diskBytes": 0,
    }
    if not path.exists():
        info["reason"] = "non_local_model_id"
        return info

    model_dir = path if path.is_dir() else path.parent
    info["modelDir"] = str(model_dir)
    model_files = sorted(model_dir.glob("*.safetensors"))
    info["modelFileCount"] = len(model_files)
    info["diskBytes"] = sum(file.stat().st_size for file in model_files if file.is_file())

    config_path = model_dir / "config.json"
    if not config_path.exists():
        info["reason"] = "missing_config_json"
        return info

    info["configPresent"] = True
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        info["reason"] = f"invalid_config_json:{exc.__class__.__name__}"
        return info

    text_config = config.get("text_config") if isinstance(config.get("text_config"), dict) else {}
    source = text_config if text_config else config
    has_vision_config = isinstance(config.get("vision_config"), dict)
    info.update(
        {
            "architecture": _first_string(config.get("architectures")),
            "modelType": str(config.get("model_type") or source.get("model_type") or ""),
            "textModelType": str(text_config.get("model_type") or ""),
            "hasVisionConfig": has_vision_config,
            "textOnly": not has_vision_config,
            "vocabSize": _optional_int(source.get("vocab_size")),
            "hiddenSize": _optional_int(source.get("hidden_size")),
            "numHiddenLayers": _optional_int(source.get("num_hidden_layers")),
            "intermediateSize": _optional_int(source.get("intermediate_size")),
            "numAttentionHeads": _optional_int(source.get("num_attention_heads")),
            "numKeyValueHeads": _optional_int(source.get("num_key_value_heads")),
            "quantization": _quantization_summary(config),
        }
    )
    return info


def _first_string(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _quantization_summary(config: dict[str, Any]) -> dict[str, Any]:
    quantization = config.get("quantization")
    if not isinstance(quantization, dict):
        quantization = config.get("quantization_config")
    if not isinstance(quantization, dict):
        return {}
    return {
        key: value
        for key, value in quantization.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _build_mlx_prompt(*, current_input: str, recent_context: str, max_candidates: int) -> str:
    return (
        f"{_stable_prompt_prefix()}"
        f"{_build_mlx_dynamic_prompt(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates)}"
    )


def _stable_prompt_prefix() -> str:
    return f"{SYSTEM_PROMPT}\n"


def _build_mlx_dynamic_prompt(*, current_input: str, recent_context: str, max_candidates: int) -> str:
    return (
        f"已上屏上下文: {recent_context}\n"
        f"当前拼音或参考候选: {current_input}\n"
        "要求:\n"
        "- 输出能直接接在已上屏上下文后面的候选, 每个 2 到 16 个汉字为主。\n"
        "- 当前输入如果是拼音、英文串或 Rime 候选列表, 只把它当作约束, 不要复述这些词。\n"
        "- 候选要像用户下一步真的会输入的内容, 优先项目、输入法、RAG、记忆、调试、模型相关表达。\n"
        "- 不要输出单字、语气词、连接词、泛词、重复词。\n"
        f"输出 {max_candidates} 个候选 JSON 数组。"
    )


def _request_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("currentInputFingerprint", "contextFingerprint", "contextChars", "stablePrefixHash"):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


@dataclass
class _PromptCacheState:
    enabled: bool
    stable_prefix: str
    max_kv_size: int = 0
    cache_file: str = ""
    prepared: bool = False
    stable_prefix_tokens: int = 0
    prepare_ms: int = 0
    used_for_generation: bool = False
    hit_count: int = 0
    miss_count: int = 0
    error: str = ""

    def stable_prefix_hash(self) -> str:
        return hashlib.sha256(self.stable_prefix.encode("utf-8")).hexdigest()[:16]

    def ready_for_generation(self) -> bool:
        return self.enabled and self.prepared and bool(self.cache_file) and os.path.exists(self.cache_file)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "enabled": self.enabled,
            "prepared": self.prepared,
            "usedForGeneration": self.used_for_generation,
            "stablePrefixHash": self.stable_prefix_hash(),
            "stablePrefixTokens": self.stable_prefix_tokens,
            "prepareMs": self.prepare_ms,
            "maxKvSize": self.max_kv_size,
            "cacheFileReady": bool(self.cache_file) and os.path.exists(self.cache_file),
            "hits": self.hit_count,
            "misses": self.miss_count,
        }
        if self.error:
            payload["error"] = self.error
        if self.enabled and self.prepared and not self.used_for_generation:
            payload["reason"] = "prepared_only_streaming_generation_not_cached_yet"
        elif not self.enabled:
            payload["reason"] = "disabled"
        return payload


def _token_to_int(token: object) -> int:
    item = getattr(token, "item", None)
    if callable(item):
        return int(item())
    return int(token)  # type: ignore[arg-type]


def _top_logprob_indices(logprobs: Any, *, limit: int) -> list[int]:
    if isinstance(logprobs, (list, tuple)):
        return sorted(range(len(logprobs)), key=lambda index: float(logprobs[index]), reverse=True)[:limit]
    try:
        import mlx.core as mx  # type: ignore

        order = mx.argsort(-logprobs)[:limit]
        return [int(item) for item in _array_to_list(order)]
    except Exception:
        return []


def _logprob_at(logprobs: Any, token_id: int) -> float | None:
    try:
        if isinstance(logprobs, (list, tuple)):
            return float(logprobs[token_id])
        value = logprobs[token_id]
        item = getattr(value, "item", None)
        return float(item() if callable(item) else value)
    except Exception:
        return None


def _array_to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        result = tolist()
        return result if isinstance(result, list) else [result]
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalize_logits_candidate_text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = compact_whitespace(str(value))
    text = text.strip(" \t\r\n\"'`[]{}(),，。！？:：;；、|")
    text = text.replace("<0x0A>", "").replace("<|endoftext|>", "")
    if "<|" in text or "�" in text:
        return ""
    return text


def _logits_candidates_are_ime_quality(candidates: Any, *, max_candidates: int) -> bool:
    if not isinstance(candidates, list):
        return False
    texts = [compact_whitespace(str(item)) for item in candidates if compact_whitespace(str(item))]
    if not texts:
        return False
    if len(texts) < max(3, min(5, int(max_candidates))):
        return False
    phrase_like = [
        text
        for text in texts
        if len(text) >= 3
        and not _is_low_value_logits_candidate(text)
        and not re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", text)
    ]
    if len(phrase_like) < max(3, min(5, int(max_candidates))):
        return False
    single_char_count = sum(1 for text in phrase_like if len(text) == 1)
    if single_char_count > len(phrase_like) // 2:
        return False
    return True


def _is_low_value_logits_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if normalized in _LOW_VALUE_LOGITS_CANDIDATES:
        return True
    if any(normalized.startswith(prefix) for prefix in ("测试", "分析")) and len(normalized) <= 4:
        return True
    if any(normalized.startswith(prefix) for prefix in ("当前", "目前", "现在")) and len(normalized) <= 5:
        return True
    return False


def _prompt_cache_used_for_generation(prompt_cache: dict[str, Any]) -> bool:
    return (
        bool(prompt_cache.get("enabled"))
        and bool(prompt_cache.get("prepared"))
        and bool(prompt_cache.get("cacheFileReady"))
        and bool(prompt_cache.get("usedForGeneration"))
    )


def _int_payload(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _float_payload(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-ime-mlx-predictor-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--top-p", type=float, default=0.85)
    parser.add_argument("--prompt-cache", action="store_true", help="Prepare the stable system-prompt cache at startup")
    parser.add_argument("--prompt-cache-max-kv-size", type=int, default=0)
    args = parser.parse_args(argv)
    serve_mlx_predictor(
        MlxPredictorServerConfig(
            host=args.host,
            port=args.port,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            prompt_cache=args.prompt_cache,
            prompt_cache_max_kv_size=args.prompt_cache_max_kv_size,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
