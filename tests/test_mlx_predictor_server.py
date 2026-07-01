from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from rag_ime.mlx_predictor_server import _PromptCacheState, make_mlx_predictor_handler


class _FakeMlxEngine:
    model_id = "fake-mlx-qwen"

    def __init__(self) -> None:
        self.prompt_cache = _PromptCacheState(
            enabled=True,
            prepared=True,
            stable_prefix="stable system prompt",
            stable_prefix_tokens=5,
            prepare_ms=7,
        )

    def health(self):
        return {
            "ok": True,
            "provider": "mlx-lm",
            "model": self.model_id,
            "modelLoaded": True,
            "promptCache": self.prompt_cache_status(),
        }

    def prompt_cache_status(self):
        return self.prompt_cache.to_payload()

    def predict(self, **kwargs):
        return {
            "ok": True,
            "rawText": '["本地记忆","输入法候选"]',
            "candidates": ["本地记忆", "输入法候选"],
            "totalMs": 12,
            "promptCache": self.prompt_cache_status(),
        }

    def stream_text(self, **kwargs):
        yield '["本地记忆"'
        yield ',"输入法候选"]'


class MlxPredictorServerTests(unittest.TestCase):
    def test_health_reports_prepared_prompt_cache_without_claiming_generation_use(self) -> None:
        server, thread = _start_fake_server()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            _stop_server(server, thread)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["promptCache"]["enabled"])
        self.assertTrue(payload["promptCache"]["prepared"])
        self.assertFalse(payload["promptCache"]["usedForGeneration"])
        self.assertEqual(payload["promptCache"]["stablePrefixTokens"], 5)
        self.assertEqual(payload["promptCache"]["reason"], "prepared_only_streaming_generation_not_cached_yet")

    def test_predict_stream_includes_prompt_cache_status_on_done_event(self) -> None:
        server, thread = _start_fake_server()
        try:
            body = json.dumps(
                {
                    "model": "fake-mlx-qwen",
                    "currentInput": "RAG 输入法",
                    "recentContext": "本地记忆",
                    "maxCandidates": 2,
                    "maxTokens": 8,
                    "stream": True,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/predict-stream",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                events = [json.loads(line.decode("utf-8")) for line in response if line.strip()]
        finally:
            _stop_server(server, thread)

        self.assertEqual(events[0]["delta"], '["本地记忆"')
        self.assertTrue(events[-1]["done"])
        self.assertEqual(events[-1]["candidates"], ["本地记忆", "输入法候选"])
        self.assertTrue(events[-1]["promptCache"]["prepared"])
        self.assertFalse(events[-1]["promptCache"]["usedForGeneration"])


def _start_fake_server():
    handler = make_mlx_predictor_handler(_FakeMlxEngine())
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


if __name__ == "__main__":
    unittest.main()
