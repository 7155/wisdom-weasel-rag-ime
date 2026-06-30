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
    OpenAICompatiblePredictionConfig,
    OpenAICompatiblePredictionProvider,
    PredictionBenchmarkCase,
    benchmark_prediction_provider,
    parse_prediction_candidates,
)


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}
    captured_headers: dict[str, str] = {}

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


class PredictionProviderTests(unittest.TestCase):
    def test_parse_prediction_candidates_deduplicates_and_limits(self) -> None:
        parsed = parse_prediction_candidates("1. 本地记忆  本地记忆，RAG候选 / 输出法; 这是一个非常非常非常长的候选短语", max_candidates=3)
        self.assertEqual(parsed, ["本地记忆", "RAG候选", "输出法"])

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
        self.assertTrue(report["providerConfigured"])
        self.assertEqual(report["summary"]["caseCount"], 1)
        self.assertTrue(report["summary"]["allWithinBudget"])
        self.assertTrue(report["summary"]["hasCandidates"])
        self.assertEqual(report["cases"][0]["candidates"], ["RAG 输入法候选"])

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


if __name__ == "__main__":
    unittest.main()
