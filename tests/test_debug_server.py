from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from rag_ime.core_client import FixtureCoreClient
from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.models import ModelPrediction


class FakePredictionProvider:
    def __init__(self) -> None:
        self.last_current_input = ""
        self.last_recent_context = ""
        self.calls = 0

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        self.last_current_input = current_input
        self.last_recent_context = recent_context
        return [
            ModelPrediction(
                text=f"{current_input}候选",
                rank=1,
                provider_name="fake-model",
                latency_ms=7,
                confidence=0.9,
            )
        ][:max_candidates]


class DebugImeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-debug-test-")
        self.service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "rag-ime.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=True,
            )
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health_and_seed_use_local_sqlite(self) -> None:
        health = self.service.health()
        self.assertTrue(health["ok"])
        self.assertGreaterEqual(health["eventCount"], 1)
        self.assertEqual(health["rimeSuggestCache"]["ttlMs"], 400)
        self.assertEqual(health["rimeSuggestCache"]["hits"], 0)
        seeded = self.service.seed()
        self.assertTrue(seeded["ok"])
        self.assertGreaterEqual(seeded["seeded"], 1)

    def test_suggest_returns_native_frontend_payload(self) -> None:
        predictor = FakePredictionProvider()
        self.service.predictor = predictor
        payload = self.service.suggest(
            {
                "currentInput": "SQLite 和 FTS5 第一版",
                "recentContext": "MVP 先 local-first",
                "topK": 3,
            }
        )
        self.assertEqual(payload["schemaVersion"], "rag-ime.suggestions.v1")
        self.assertEqual(payload["currentInput"], "SQLite 和 FTS5 第一版")
        self.assertEqual(payload["modelPredictions"][0]["providerName"], "fake-model")
        self.assertIn("MVP 先 local-first", predictor.last_recent_context)
        self.assertGreaterEqual(len(payload["suggestions"]), 1)
        first = payload["suggestions"][0]
        self.assertIn("surfaceText", first)
        self.assertIn("memoryId", first)
        self.assertIn("evidencePreview", first)

    def test_model_prediction_context_includes_committed_history(self) -> None:
        predictor = FakePredictionProvider()
        self.service.predictor = predictor
        self.service.commit(
            {
                "text": "历史输入会进入模型预测",
                "recentContext": "用户刚刚写过 RAG 输入法",
                "preedit": "lishi",
                "tags": ["history"],
            }
        )
        payload = self.service.suggest({"currentInput": "继续", "recentContext": "当前正在续写", "topK": 2})
        self.assertIn("历史输入会进入模型预测", predictor.last_recent_context)
        self.assertIn("当前正在续写", predictor.last_recent_context)
        self.assertIn("historyContext", payload)
        self.assertIn("历史输入会进入模型预测", payload["historyContext"])

    def test_rime_suggest_endpoint_uses_rime_candidates_for_side_query(self) -> None:
        predictor = FakePredictionProvider()
        self.service.predictor = predictor
        payload = self.service.rime_suggest(
            {
                "sessionId": "debug-rime",
                "requestSeq": 11,
                "rawInput": "jiubiruwopinshishur",
                "preedit": "jiubiruwopinshishur",
                "committedContext": "用户正在写输入法设计",
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 2,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "就比如", "comment": "rime"},
                        {"label": "2", "text": "我平时输入", "comment": "rime"},
                    ]
                },
            }
        )
        self.assertEqual(payload["schemaVersion"], "rag-ime.rime-sidecar.v1")
        self.assertEqual(payload["queryBasis"], "rimeCandidates")
        self.assertIn("就比如", predictor.last_current_input)
        self.assertNotIn("jiubiruwopinshishur", predictor.last_current_input)
        self.assertEqual(payload["displayCandidates"][0]["selectionAction"], "select_rime_candidate")
        self.assertEqual(payload["displayCandidates"][2]["selectionAction"], "commit_side_candidate")
        self.assertFalse(payload["cache"]["hit"])

    def test_rime_suggest_cache_hits_repeated_equivalent_payloads(self) -> None:
        predictor = FakePredictionProvider()
        self.service.predictor = predictor
        payload = {
            "sessionId": "cache-a",
            "requestSeq": 21,
            "rawInput": "ragshurufa",
            "preedit": "ragshurufa",
            "committedContext": "用户正在写 RAG 输入法",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 2,
            "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
        }
        first = self.service.rime_suggest(payload)
        second_payload = dict(payload)
        second_payload["requestSeq"] = 22
        second_payload["sessionId"] = "cache-b"
        second = self.service.rime_suggest(second_payload)
        self.assertEqual(predictor.calls, 1)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(second["requestSeq"], 22)
        self.assertEqual(second["sessionId"], "cache-b")

        self.service.commit({"text": "cache invalidation commit"})
        third_payload = dict(payload)
        third_payload["requestSeq"] = 23
        third = self.service.rime_suggest(third_payload)
        self.assertFalse(third["cache"]["hit"])
        self.assertEqual(predictor.calls, 2)

    def test_commit_and_action_are_wired_for_debug_page(self) -> None:
        suggestion = self.service.suggest({"currentInput": "FTS5", "topK": 1})["suggestions"][0]
        action = self.service.action(
            {
                "actionType": "pin",
                "memoryId": suggestion["memoryId"],
                "suggestionId": suggestion["suggestionId"],
                "sourceEventId": suggestion["sourceEventId"],
                "query": "FTS5",
                "surfaceText": suggestion["surfaceText"],
            }
        )
        self.assertEqual(action["schemaVersion"], "rag-ime.action.v1")
        self.assertEqual(action["actionType"], "pin")
        committed = self.service.commit(
            {
                "text": "输入法调试页接受了一条候选",
                "recentContext": "debug page",
                "preedit": "debug",
                "candidateRank": 1,
                "tags": ["debug"],
            }
        )
        self.assertTrue(committed["ok"])
        self.assertTrue(str(committed["eventId"]).startswith("event:"))

    def test_commit_endpoint_accepts_squirrel_source(self) -> None:
        committed = self.service.commit(
            {
                "text": "Squirrel HTTP sidecar commit",
                "source": "squirrel_rime_sidecar",
                "tags": ["squirrel"],
            }
        )
        self.assertTrue(committed["ok"])
        with sqlite3.connect(self.service.config.db_path) as conn:
            source = conn.execute(
                "SELECT source FROM input_events WHERE committed_text = ?",
                ("Squirrel HTTP sidecar commit",),
            ).fetchone()[0]
        self.assertEqual(source, "squirrel_rime_sidecar")

    def test_http_sidecar_accepts_root_paths(self) -> None:
        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/rime-suggest"
            request = Request(
                url,
                data=json.dumps(
                    {
                        "sessionId": "http-root",
                        "requestSeq": 1,
                        "maxVisibleCandidates": 3,
                        "maxSideCandidates": 1,
                        "rimeContext": {"candidates": [{"label": "1", "text": "本地记忆"}]},
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(payload["schemaVersion"], "rag-ime.rime-sidecar.v1")
        self.assertEqual(payload["sessionId"], "http-root")

    def test_rejects_empty_commit_and_bad_action(self) -> None:
        with self.assertRaises(ValueError):
            self.service.commit({"text": " "})
        with self.assertRaises(ValueError):
            self.service.action({"actionType": "unknown", "memoryId": "event:1"})

    def test_debug_service_can_use_injected_shared_core_adapter(self) -> None:
        service = DebugImeService(
            DebugServerConfig(
                core=FixtureCoreClient(),
                seed_if_empty=False,
                project="wisdom-weasel-rag-ime",
            )
        )
        health = service.health()
        self.assertEqual(health["coreMode"], "json")
        self.assertIsNone(health["eventCount"])
        payload = service.suggest({"currentInput": "local-first 记忆", "topK": 2})
        self.assertEqual(payload["schemaVersion"], "rag-ime.suggestions.v1")
        self.assertGreaterEqual(len(payload["suggestions"]), 1)


if __name__ == "__main__":
    unittest.main()
