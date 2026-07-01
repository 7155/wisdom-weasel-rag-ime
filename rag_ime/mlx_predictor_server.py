from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable

from .predictor import parse_prediction_candidates
from .text_utils import compact_whitespace


SYSTEM_PROMPT = (
    "你是中文输入法候选预测器。只输出 JSON 字符串数组, "
    '例如 ["本地记忆输入法","RAG候选","历史上下文"], 不要解释。'
)


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
            from mlx_lm import load, stream_generate  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local Mac setup
            raise RuntimeError("Install mlx-lm before running mlx-predictor-server") from exc

        self.model_id = model_id
        self._stream_generate = stream_generate
        self.model, self.tokenizer = load(model_id)
        self._prompt_cache = _PromptCacheState(
            enabled=bool(enable_prompt_cache),
            stable_prefix=_stable_prompt_prefix(),
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
            "promptCache": prompt_cache,
            "capabilities": {
                "streaming": True,
                "residentModel": True,
                "promptCache": _prompt_cache_used_for_generation(prompt_cache),
                "sequenceFork": False,
                "batchCandidates": False,
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
    ) -> dict[str, Any]:
        started = time.perf_counter()
        raw_text = "".join(
            self.stream_text(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        )
        total_ms = int((time.perf_counter() - started) * 1000)
        candidates = parse_prediction_candidates(raw_text, max_candidates=max_candidates)
        return {
            "ok": True,
            "model": self.model_id,
            "rawText": raw_text,
            "candidates": candidates,
            "totalMs": total_ms,
            "promptCache": self.prompt_cache_status(),
        }

    def stream_text(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> Iterable[str]:
        prompt = _build_mlx_prompt(
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
        for response in self._stream_generate(
            self.model,
            self.tokenizer,
            prompt,
            max_tokens=max(1, min(64, int(max_tokens))),
            temperature=float(temperature),
            top_p=float(top_p),
        ):
            text = getattr(response, "text", "")
            if isinstance(text, str) and text:
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
        dynamic_prompt = _build_mlx_dynamic_prompt(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
        )
        tokens = self.tokenizer.encode(dynamic_prompt)
        sampler = make_sampler(temp=float(temperature), top_p=float(top_p))
        emitted = ""
        generated_tokens: list[int] = []
        self._prompt_cache.used_for_generation = True
        self._prompt_cache.hit_count += 1
        self._prompt_cache.error = ""
        for token, _logprobs in generate_step(
            mx.array(tokens),
            self.model,
            max_tokens=max(1, min(64, int(max_tokens))),
            prompt_cache=cache,
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
        f"上下文: {recent_context}\n"
        f"当前输入: {current_input}\n"
        f"输出 {max_candidates} 个最可能的短候选。"
    )


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
