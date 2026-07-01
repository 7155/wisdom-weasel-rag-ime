from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from rag_ime.cli import main
from rag_ime.predictor import (
    CooldownPredictionProvider,
    MlxPredictionServiceProvider,
    OllamaPredictionProvider,
    OpenAICompatiblePredictionConfig,
    OpenAICompatiblePredictionProvider,
    PredictionBenchmarkCase,
    benchmark_prediction_provider,
    doctor_prediction_provider,
    parse_prediction_candidates,
    prediction_provider_from_env,
    prediction_provider_status,
)


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}
    captured_headers: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps(
            {"data": [{"id": "Qwen3-0.6B"}, {"id": "Qwen3-1.7B"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOpenAIHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        _MockOpenAIHandler.captured_headers = {key: value for key, value in self.headers.items()}
        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "本地记忆 输入法候选 RAG上下文 本地记忆",
                        }
                    }
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps(
            {"models": [{"name": "qwen3.5:0.8b"}, {"name": "qwen2.5:0.5b"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOllamaHandler.captured_path = self.path
        _MockOllamaHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "本地记忆 输入法候选 RAG候选",
                },
                "done": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []
    captured_payloads: list[dict[str, object]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/api/tags":
            self.send_error(404)
            return
        body = json.dumps(
            {"models": [{"name": "qwen3.5:0.8b"}, {"name": "qwen3.5:2b"}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockOllamaMatrixHandler.seen_models.append(model)
        _MockOllamaMatrixHandler.captured_payloads.append(payload)
        content = '["本地记忆","输入法候选"]' if model == "qwen3.5:0.8b" else '["无关候选"]'
        body = json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "done": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaStreamingHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOllamaStreamingHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        chunks = [
            {"message": {"role": "assistant", "content": '["本地记忆"'}},
            {"message": {"role": "assistant", "content": ',"输入法候选"]'}, "done": True},
        ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaStreamingMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []
    captured_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockOllamaStreamingMatrixHandler.seen_models.append(model)
        _MockOllamaStreamingMatrixHandler.captured_payloads.append(payload)
        if model == "qwen3.5:0.8b-mlx":
            chunks = [
                {"message": {"role": "assistant", "content": '["本地记忆"'}},
                {"message": {"role": "assistant", "content": ',"输入法候选"]'}, "done": True},
            ]
        else:
            chunks = [
                {"message": {"role": "assistant", "content": '["'}, "done": True},
            ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaEmptyStreamingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        body = json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode("utf-8") + b"\n"
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockOllamaUnparsedStreamingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        chunks = [
            {"message": {"role": "assistant", "content": '["'}},
            {"message": {"role": "assistant", "content": ""}, "done": True},
        ]
        body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockMlxHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "mlx-qwen3.5-0.8b"}]}, ensure_ascii=False).encode("utf-8")
        elif self.path == "/health":
            body = json.dumps(
                {
                    "ok": True,
                    "provider": "mlx-lm",
                    "model": "mlx-qwen3.5-0.8b",
                    "modelLoaded": True,
                },
                ensure_ascii=False,
            ).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockMlxHandler.captured_path = self.path
        _MockMlxHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/predict-stream":
            chunks = [
                {"delta": '["本地记忆"'},
                {"delta": ',"输入法候选"]'},
                {"done": True, "candidates": ["本地记忆", "输入法候选"], "totalMs": 19},
            ]
            body = b"".join(json.dumps(item, ensure_ascii=False).encode("utf-8") + b"\n" for item in chunks)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            return
        if self.path != "/predict":
            self.send_error(404)
            return
        body = json.dumps(
            {
                "ok": True,
                "candidates": ["本地记忆", "输入法候选", "RAG上下文"],
                "rawText": '["本地记忆","输入法候选","RAG上下文"]',
                "totalMs": 17,
                "promptCache": {"enabled": False},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockCompletionHandler(BaseHTTPRequestHandler):
    captured_path = ""
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockCompletionHandler.captured_path = self.path
        _MockCompletionHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(
            {
                "choices": [
                    {"text": "<think>分析过程不应该进入候选</think>\n本地记忆"},
                    {"text": "输入法候选"},
                    {"text": "RAG上下文"},
                ]
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class _MockModelMatrixHandler(BaseHTTPRequestHandler):
    seen_models: list[str] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        model = str(payload.get("model") or "")
        _MockModelMatrixHandler.seen_models.append(model)
        content = "本地记忆 输入法候选" if model == "qwen3.5:0.8b" else "无关候选"
        body = json.dumps(
            {"choices": [{"message": {"content": content}}]},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class PredictionProviderTests(unittest.TestCase):
    def test_parse_prediction_candidates_deduplicates_and_limits(self) -> None:
        parsed = parse_prediction_candidates("1. 本地记忆  本地记忆，RAG候选 / 输出法; 这是一个非常非常非常长的候选短语", max_candidates=3)
        self.assertEqual(parsed, ["本地记忆", "RAG候选", "输出法"])

    def test_parse_prediction_candidates_strips_thinking_and_json(self) -> None:
        parsed = parse_prediction_candidates(
            '<think>先分析一下</think> ["本地记忆", "RAG候选", "输入法候选"]',
            max_candidates=3,
        )
        self.assertEqual(parsed, ["本地记忆", "RAG候选", "输入法候选"])

    def test_openai_compatible_provider_returns_short_ranked_predictions(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="Qwen3-0.6B",
                    timeout_s=1.0,
                    max_tokens=8,
                    provider_name="mock-qwen",
                    extra_body={"seed": 7, "chat_template_kwargs": {"enable_thinking": False}},
                    extra_headers={"X-RAG-IME-Test": "extra-header"},
                )
            )
            predictions = provider.predict(
                current_input="rag",
                recent_context="输入法需要本地记忆和候选预测",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.assertEqual([item.text for item in predictions], ["本地记忆", "输入法候选", "RAG上下文"])
        self.assertEqual(predictions[0].provider_name, "mock-qwen")
        self.assertGreaterEqual(predictions[0].latency_ms, 0)
        self.assertEqual(_MockOpenAIHandler.captured_payload["model"], "Qwen3-0.6B")
        self.assertEqual(_MockOpenAIHandler.captured_payload["seed"], 7)
        self.assertEqual(_MockOpenAIHandler.captured_payload["chat_template_kwargs"], {"enable_thinking": False})
        captured_headers = {key.lower(): value for key, value in _MockOpenAIHandler.captured_headers.items()}
        self.assertEqual(captured_headers["x-rag-ime-test"], "extra-header")
        messages = _MockOpenAIHandler.captured_payload["messages"]
        self.assertIn("只输出候选词", messages[0]["content"])
        self.assertLessEqual(_MockOpenAIHandler.captured_payload["max_tokens"], 8)
        self.assertEqual(predictions[0].metadata["profile"], "custom")

    def test_completion_prompt_mode_uses_prefix_completion_endpoint(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockCompletionHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatiblePredictionProvider(
                OpenAICompatiblePredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="qwen-base",
                    prompt_mode="completion",
                    timeout_s=1.0,
                    max_tokens=4,
                    provider_name="mock-completion",
                )
            )
            predictions = provider.predict(
                current_input="输入法",
                recent_context="本地记忆",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        self.assertEqual([item.text for item in predictions], ["本地记忆", "输入法候选", "RAG上下文"])
        self.assertEqual(_MockCompletionHandler.captured_path, "/v1/completions")
        self.assertEqual(_MockCompletionHandler.captured_payload["model"], "qwen-base")
        self.assertEqual(_MockCompletionHandler.captured_payload["prompt"], "本地记忆输入法")
        self.assertEqual(_MockCompletionHandler.captured_payload["n"], 3)
        self.assertNotIn("messages", _MockCompletionHandler.captured_payload)
        self.assertEqual(predictions[0].metadata["prompt_mode"], "completion")

    def test_env_can_disable_qwen_thinking_without_hand_written_json(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_DISABLE_THINKING": "1",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7,"chat_template_kwargs":{"foo":"bar"}}',
            }
        )

        self.assertIsInstance(provider, CooldownPredictionProvider)
        config = provider.config
        self.assertEqual(
            config.extra_body,
            {
                "seed": 7,
                "chat_template_kwargs": {
                    "foo": "bar",
                    "enable_thinking": False,
                },
            },
        )

    def test_instant_profile_sets_fast_no_thinking_defaults(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7}',
            }
        )

        self.assertIsInstance(provider, CooldownPredictionProvider)
        config = provider.config
        self.assertEqual(config.profile, "instant")
        self.assertEqual(config.prompt_mode, "chat")
        self.assertEqual(config.timeout_s, 0.35)
        self.assertEqual(config.max_tokens, 8)
        self.assertEqual(config.temperature, 0.15)
        self.assertEqual(config.top_p, 0.85)
        self.assertEqual(
            config.extra_body,
            {
                "seed": 7,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )

    def test_prediction_provider_status_reports_configured_model_lane(self) -> None:
        null_status = prediction_provider_status(prediction_provider_from_env({}))
        self.assertFalse(null_status["configured"])
        self.assertEqual(null_status["providerName"], "NullPredictionProvider")

        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_EXTRA_BODY_JSON": '{"seed":7}',
            }
        )
        status = prediction_provider_status(provider)

        self.assertTrue(status["configured"])
        self.assertEqual(status["providerName"], "local-openai-compatible")
        self.assertEqual(status["providerProfile"], "instant")
        self.assertEqual(status["promptMode"], "chat")
        self.assertEqual(status["baseUrl"], "http://127.0.0.1:8000")
        self.assertEqual(status["model"], "Qwen3-0.6B")
        self.assertEqual(status["timeoutMs"], 350)
        self.assertIn("chat_template_kwargs", status["extraBodyKeys"])
        self.assertIn("seed", status["extraBodyKeys"])
        self.assertFalse(status["capabilities"]["streaming"])
        self.assertTrue(status["cooldown"]["enabled"])

    def test_env_can_disable_prediction_failure_cooldown(self) -> None:
        provider = prediction_provider_from_env(
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
            }
        )

        self.assertIsInstance(provider, OpenAICompatiblePredictionProvider)

    def test_ollama_provider_uses_native_chat_with_thinking_disabled(self) -> None:
        _MockOllamaHandler.captured_path = ""
        _MockOllamaHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            self.assertIsInstance(provider, OllamaPredictionProvider)
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockOllamaHandler.captured_path, "/api/chat")
        self.assertFalse(_MockOllamaHandler.captured_payload["think"])
        self.assertEqual(_MockOllamaHandler.captured_payload["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockOllamaHandler.captured_payload["options"]["num_predict"], 24)
        self.assertEqual(predictions[0].text, "本地记忆")
        self.assertEqual(predictions[0].provider_name, "local-ollama")

    def test_ollama_provider_can_return_first_streamed_candidate(self) -> None:
        _MockOllamaStreamingHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b-mlx",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual([item.text for item in predictions], ["本地记忆"])
        self.assertTrue(_MockOllamaStreamingHandler.captured_payload["stream"])
        self.assertEqual(_MockOllamaStreamingHandler.captured_payload["keep_alive"], -1)
        self.assertTrue(predictions[0].metadata["stream_first_candidate"])
        self.assertIsInstance(predictions[0].metadata["first_candidate_ms"], int)
        status = prediction_provider_status(provider)
        self.assertTrue(status["streamFirstCandidate"])

    def test_mlx_provider_uses_resident_prediction_service(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            self.assertIsInstance(provider, MlxPredictionServiceProvider)
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockMlxHandler.captured_path, "/predict")
        self.assertEqual(_MockMlxHandler.captured_payload["model"], "mlx-qwen3.5-0.8b")
        self.assertEqual(_MockMlxHandler.captured_payload["maxCandidates"], 3)
        self.assertEqual(_MockMlxHandler.captured_payload["maxTokens"], 8)
        self.assertEqual([item.text for item in predictions], ["本地记忆", "输入法候选", "RAG上下文"])
        self.assertEqual(predictions[0].provider_name, "local-mlx")
        self.assertEqual(predictions[0].latency_ms, 17)
        self.assertEqual(predictions[0].metadata["prompt_cache"], {"enabled": False})
        status = prediction_provider_status(provider)
        self.assertTrue(status["capabilities"]["streaming"])
        self.assertTrue(status["capabilities"]["residentModel"])
        self.assertFalse(status["capabilities"]["promptCache"])
        self.assertFalse(status["capabilities"]["sequenceFork"])

    def test_mlx_provider_can_return_first_streamed_candidate(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = prediction_provider_from_env(
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                    "RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS": "0",
                }
            )
            predictions = provider.predict(
                current_input="RAG 输入法",
                recent_context="用户正在写本地记忆输入法",
                max_candidates=3,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(_MockMlxHandler.captured_path, "/predict-stream")
        self.assertTrue(_MockMlxHandler.captured_payload["stream"])
        self.assertEqual([item.text for item in predictions], ["本地记忆"])
        self.assertTrue(predictions[0].metadata["stream_first_candidate"])
        self.assertIsInstance(predictions[0].metadata["first_candidate_ms"], int)
        status = prediction_provider_status(provider)
        self.assertTrue(status["streamFirstCandidate"])

    def test_prediction_cooldown_skips_repeat_failures(self) -> None:
        class FailingProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="failing-provider",
                profile="instant",
            )

            def __init__(self) -> None:
                self.calls = 0
                self.last_error = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.calls += 1
                self.last_error = "timeout"
                return []

        delegate = FailingProvider()
        provider = CooldownPredictionProvider(delegate, cooldown_ms=1000, failure_latency_ms=1)

        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(provider.predict(current_input="RAG 输入法"), [])
        self.assertEqual(delegate.calls, 1)
        status = prediction_provider_status(provider)
        self.assertTrue(status["cooldown"]["active"])
        self.assertEqual(status["cooldown"]["failureCount"], 1)
        self.assertEqual(status["cooldown"]["skippedCount"], 1)
        self.assertEqual(status["cooldown"]["lastError"], "timeout")

    def test_predictor_doctor_reports_cooldown_after_failed_probe(self) -> None:
        class FailingProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="doctor-failing-provider",
                profile="instant",
            )

            def __init__(self) -> None:
                self.last_error = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.last_error = "timeout"
                return []

        provider = CooldownPredictionProvider(FailingProvider(), cooldown_ms=1000, failure_latency_ms=1)
        report = doctor_prediction_provider(provider, latency_budget_ms=1000)

        self.assertFalse(report["ready"])
        self.assertTrue(report["status"]["cooldown"]["active"])
        self.assertEqual(report["status"]["cooldown"]["lastError"], "timeout")

    def test_cli_predictor_status_reports_env_configuration(self) -> None:
        stdout = io.StringIO()
        with patch.dict(
            os.environ,
            {
                "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8000",
                "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
            },
            clear=False,
        ):
            with redirect_stdout(stdout):
                code = main(["--core-mode", "fixture", "predictor-status"])

        self.assertEqual(code, 0)
        status = json.loads(stdout.getvalue())
        self.assertTrue(status["configured"])
        self.assertEqual(status["providerProfile"], "instant")
        self.assertEqual(status["model"], "Qwen3-0.6B")

    def test_predictor_doctor_reports_unconfigured_lane(self) -> None:
        report = doctor_prediction_provider(prediction_provider_from_env({}))

        self.assertEqual(report["schemaVersion"], "rag-ime.predictor-doctor.v1")
        self.assertFalse(report["ready"])
        self.assertFalse(report["summary"]["endpointReachable"])
        self.assertFalse(report["status"]["configured"])
        self.assertEqual(report["checks"]["modelsEndpoint"]["reason"], "not_configured")
        self.assertFalse(report["checks"]["prediction"]["hasCandidates"])
        self.assertIn("RAG_IME_PREDICTOR_PROVIDER", report["nextActions"][0])

    def test_cli_predictor_doctor_checks_models_and_short_prediction(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-doctor",
                            "--case",
                            "RAG 输入法",
                            "--latency-budget-ms",
                            "1000",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ready"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["ok"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["configuredModelFound"])
        self.assertEqual(report["checks"]["modelsEndpoint"]["modelCount"], 2)
        self.assertTrue(report["checks"]["prediction"]["hasCandidates"])
        self.assertEqual(report["checks"]["prediction"]["candidates"][0], "本地记忆")
        self.assertIn("localRunners", report)

    def test_cli_predictor_doctor_checks_ollama_tags_and_short_prediction(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-doctor",
                            "--case",
                            "RAG 输入法",
                            "--latency-budget-ms",
                            "1000",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"]["providerName"], "local-ollama")
        self.assertEqual(report["status"]["promptMode"], "ollama-chat")
        self.assertTrue(report["checks"]["modelsEndpoint"]["ok"])
        self.assertTrue(report["checks"]["modelsEndpoint"]["configuredModelFound"])
        self.assertEqual(report["checks"]["prediction"]["candidates"][0], "本地记忆")

    def test_prediction_benchmark_reports_latency_budget(self) -> None:
        class FakeProvider:
            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                return [
                    type(
                        "Prediction",
                        (),
                        {
                            "text": f"{current_input}候选",
                            "latency_ms": 12,
                            "provider_name": "fake-fast",
                        },
                    )()
                ][:max_candidates]

        report = benchmark_prediction_provider(
            FakeProvider(),
            [PredictionBenchmarkCase(current_input="RAG 输入法")],
            max_candidates=2,
            latency_budget_ms=50,
        )
        self.assertEqual(report["schemaVersion"], "rag-ime.predict-benchmark.v1")
        self.assertEqual(report["providerName"], "fake-fast")
        self.assertEqual(report["providerProfile"], "none")
        self.assertTrue(report["providerConfigured"])
        self.assertEqual(report["summary"]["caseCount"], 1)
        self.assertTrue(report["summary"]["allWithinBudget"])
        self.assertTrue(report["summary"]["hasCandidates"])
        self.assertEqual(report["cases"][0]["candidates"], ["RAG 输入法候选"])

    def test_prediction_benchmark_uses_configured_name_without_candidates(self) -> None:
        class EmptyConfiguredProvider:
            config = OpenAICompatiblePredictionConfig(
                base_url="http://127.0.0.1:9",
                model="Qwen3-0.6B",
                provider_name="configured-empty",
                profile="instant",
            )

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                return []

        report = benchmark_prediction_provider(
            EmptyConfiguredProvider(),
            [PredictionBenchmarkCase(current_input="RAG 输入法")],
            max_candidates=2,
            latency_budget_ms=50,
        )

        self.assertEqual(report["providerName"], "configured-empty")
        self.assertEqual(report["providerProfile"], "instant")
        self.assertTrue(report["providerConfigured"])
        self.assertFalse(report["summary"]["hasCandidates"])

    def test_cli_eval_prediction_reports_quality_and_latency(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-prediction-eval-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(
                    os.environ,
                    {
                        "RAG_IME_PREDICTOR_PROVIDER": "openai-compatible",
                        "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "RAG_IME_PREDICTOR_MODEL": "Qwen3-0.6B",
                        "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                    },
                    clear=False,
                ):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/prediction.sqlite",
                                "eval-prediction",
                                "--cases-file",
                                cases_file,
                                "--max-candidates",
                                "3",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.codex-history-eval.v1")
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["metrics"]["top1Accuracy"], 1.0)
        self.assertEqual(report["prediction"]["providerName"], "local-openai-compatible")
        self.assertTrue(report["prediction"]["providerConfigured"])
        self.assertEqual(report["prediction"]["maxCandidates"], 3)
        self.assertEqual(report["prediction"]["overBudgetCount"], 0)
        self.assertEqual(report["prediction"]["totalCandidates"], 3)
        self.assertEqual(report["latency"]["caseCount"], 1)
        self.assertEqual(report["cases"][0]["topSurfaces"][0], "本地记忆")

    def test_cli_eval_model_matrix_compares_qwen_tags(self) -> None:
        _MockModelMatrixHandler.seen_models = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockModelMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-model-matrix-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(os.environ, {"RAG_IME_PREDICTOR_TIMEOUT_MS": "1000"}, clear=False):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/matrix.sqlite",
                                "eval-model-matrix",
                                "--cases-file",
                                cases_file,
                                "--base-url",
                                f"http://127.0.0.1:{server.server_port}",
                                "--models",
                                "qwen3.5:0.8b,qwen3.5:2b",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.model-matrix-eval.v1")
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertEqual(report["models"][0]["passed"], 1)
        self.assertEqual(report["models"][1]["passed"], 0)
        self.assertNotIn("cases", report["models"][0])
        self.assertEqual(report["models"][1]["failedCaseIds"], ["local-memory-prediction"])
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockModelMatrixHandler.seen_models, ["qwen3.5:0.8b", "qwen3.5:2b"])

    def test_cli_eval_model_matrix_can_use_native_ollama_provider(self) -> None:
        _MockOllamaMatrixHandler.seen_models = []
        _MockOllamaMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-ollama-matrix-") as tmp:
                cases_file = f"{tmp}/cases.jsonl"
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "local-memory-prediction",
                                "query": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                                "expectedTerms": ["本地记忆"],
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with patch.dict(os.environ, {"RAG_IME_PREDICTOR_TIMEOUT_MS": "1000"}, clear=False):
                    with redirect_stdout(stdout):
                        code = main(
                            [
                                "--db-path",
                                f"{tmp}/matrix.sqlite",
                                "eval-model-matrix",
                                "--cases-file",
                                cases_file,
                                "--provider",
                                "ollama",
                                "--base-url",
                                f"http://127.0.0.1:{server.server_port}/v1",
                                "--models",
                                "qwen3.5:0.8b,qwen3.5:2b",
                                "--latency-budget-ms",
                                "1000",
                            ]
                        )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.model-matrix-eval.v1")
        self.assertEqual(report["provider"], "ollama")
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertEqual(report["models"][0]["passed"], 1)
        self.assertEqual(report["models"][1]["passed"], 0)
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b")
        self.assertEqual(_MockOllamaMatrixHandler.seen_models, ["qwen3.5:0.8b", "qwen3.5:2b"])
        self.assertTrue(all(payload["think"] is False for payload in _MockOllamaMatrixHandler.captured_payloads))

    def test_cli_predictor_ttft_measures_streaming_first_chunk(self) -> None:
        _MockOllamaStreamingHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--recent-context",
                            "用户正在写本地记忆输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.predictor-ttft.v1")
        self.assertTrue(report["supported"])
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertTrue(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["cases"][0]["candidateCount"], 2)
        self.assertEqual(report["cases"][0]["candidates"][0], "本地记忆")
        self.assertIsInstance(report["cases"][0]["firstChunkMs"], int)
        self.assertIsInstance(report["cases"][0]["firstCandidateMs"], int)
        self.assertIsInstance(report["summary"]["p50FirstCandidateMs"], int)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 0)
        self.assertTrue(_MockOllamaStreamingHandler.captured_payload["stream"])
        self.assertFalse(_MockOllamaStreamingHandler.captured_payload["think"])
        self.assertEqual(_MockOllamaStreamingHandler.captured_payload["keep_alive"], -1)

    def test_cli_bench_ime_ttfc_runs_streaming_model_matrix_from_cases_file(self) -> None:
        _MockOllamaStreamingMatrixHandler.seen_models = []
        _MockOllamaStreamingMatrixHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaStreamingMatrixHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-ttfc-cases-") as tmp:
                cases_file = os.path.join(tmp, "ime-ttfc-cases.jsonl")
                with open(cases_file, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "id": "short-context",
                                "currentInput": "RAG 输入法",
                                "recentContext": "用户正在写本地记忆输入法",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    handle.write(
                        json.dumps(
                            {
                                "id": "no-expected-terms",
                                "query": "Squirrel 候选",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "bench-ime-ttfc",
                            "--cases-file",
                            cases_file,
                            "--provider",
                            "ollama",
                            "--base-url",
                            f"http://127.0.0.1:{server.server_port}",
                            "--models",
                            "qwen3.5:0.8b-mlx,qwen3.5:2b-mlx",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                            "--include-cases",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["schemaVersion"], "rag-ime.ime-ttfc-benchmark.v1")
        self.assertEqual(report["repeat"]["baseCaseCount"], 2)
        self.assertEqual(report["repeat"]["effectiveCaseCount"], 2)
        self.assertEqual([item["model"] for item in report["models"]], ["qwen3.5:0.8b-mlx", "qwen3.5:2b-mlx"])
        self.assertEqual(report["winner"]["model"], "qwen3.5:0.8b-mlx")
        self.assertTrue(report["models"][0]["summary"]["hasFirstCandidate"])
        self.assertEqual(report["models"][0]["cases"][0]["caseId"], "short-context")
        self.assertEqual(report["models"][0]["cases"][1]["caseId"], "no-expected-terms")
        self.assertEqual(
            _MockOllamaStreamingMatrixHandler.seen_models,
            ["qwen3.5:0.8b-mlx", "qwen3.5:0.8b-mlx", "qwen3.5:2b-mlx", "qwen3.5:2b-mlx"],
        )
        self.assertTrue(all(payload["stream"] for payload in _MockOllamaStreamingMatrixHandler.captured_payloads))
        self.assertTrue(all(payload["think"] is False for payload in _MockOllamaStreamingMatrixHandler.captured_payloads))

    def test_cli_predictor_ttft_counts_missing_first_chunk_as_over_budget(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaEmptyStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["summary"]["hasFirstChunk"])
        self.assertFalse(report["summary"]["allWithinBudget"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 1)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 1)
        self.assertEqual(report["summary"]["failureCount"], 1)
        self.assertEqual(report["summary"]["overBudgetCount"], 1)
        self.assertTrue(report["cases"][0]["overBudget"])

    def test_cli_predictor_ttft_uses_first_parsed_candidate_for_budget(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllamaUnparsedStreamingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertFalse(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 0)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 1)
        self.assertEqual(report["summary"]["overBudgetCount"], 1)
        self.assertTrue(report["cases"][0]["overBudget"])

    def test_cli_predictor_ttft_supports_mlx_streaming_service(self) -> None:
        _MockMlxHandler.captured_path = ""
        _MockMlxHandler.captured_payload = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _MockMlxHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            stdout = io.StringIO()
            with patch.dict(
                os.environ,
                {
                    "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                    "RAG_IME_PREDICTOR_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "RAG_IME_PREDICTOR_MODEL": "mlx-qwen3.5-0.8b",
                    "RAG_IME_PREDICTOR_PROFILE": "instant",
                    "RAG_IME_PREDICTOR_TIMEOUT_MS": "1000",
                },
                clear=False,
            ):
                with redirect_stdout(stdout):
                    code = main(
                        [
                            "--core-mode",
                            "fixture",
                            "predictor-ttft",
                            "--case",
                            "RAG 输入法",
                            "--repeat",
                            "1",
                            "--latency-budget-ms",
                            "200",
                        ]
                    )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["supported"])
        self.assertEqual(report["providerName"], "local-mlx")
        self.assertTrue(report["summary"]["hasFirstChunk"])
        self.assertTrue(report["summary"]["hasFirstCandidate"])
        self.assertEqual(report["summary"]["firstChunkMissingCount"], 0)
        self.assertEqual(report["summary"]["firstCandidateMissingCount"], 0)
        self.assertEqual(report["cases"][0]["candidateCount"], 2)
        self.assertEqual(report["cases"][0]["candidates"][0], "本地记忆")
        self.assertEqual(_MockMlxHandler.captured_path, "/predict-stream")
        self.assertTrue(_MockMlxHandler.captured_payload["stream"])


if __name__ == "__main__":
    unittest.main()
