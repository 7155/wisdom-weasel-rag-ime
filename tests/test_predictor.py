from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag_ime.predictor import (
    OpenAICompatiblePredictionConfig,
    OpenAICompatiblePredictionProvider,
    parse_prediction_candidates,
)


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    captured_payload: dict[str, object] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        _MockOpenAIHandler.captured_payload = json.loads(self.rfile.read(length).decode("utf-8"))
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
        messages = _MockOpenAIHandler.captured_payload["messages"]
        self.assertIn("只输出候选词", messages[0]["content"])
        self.assertLessEqual(_MockOpenAIHandler.captured_payload["max_tokens"], 8)


if __name__ == "__main__":
    unittest.main()
