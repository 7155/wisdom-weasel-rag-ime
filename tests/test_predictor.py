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


if __name__ == "__main__":
    unittest.main()
