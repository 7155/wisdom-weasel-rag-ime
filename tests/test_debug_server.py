from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.request import Request, urlopen

from rag_ime.core_client import FixtureCoreClient
from rag_ime.debug_server import DebugImeService, DebugRequestHandler, DebugServerConfig
from rag_ime.models import ModelPrediction
from rag_ime.predictor import OllamaPredictionConfig, OllamaPredictionProvider


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


class BlockingPredictionProvider:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.calls = 0

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking test predictor was not released")
        return [
            ModelPrediction(
                text=f"{current_input}阻塞候选",
                rank=1,
                provider_name="blocking-model",
                latency_ms=25,
                confidence=0.9,
            )
        ][:max_candidates]


class MockOllamaStreamingHandler(BaseHTTPRequestHandler):
    captured_payloads: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        MockOllamaStreamingHandler.captured_payloads.append(payload)
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


class VectorAwareFixtureCore(FixtureCoreClient):
    def __init__(self) -> None:
        super().__init__()
        self.vector_revision = 1

    def vector_index_stats(self) -> dict[str, object]:
        return {
            "enabled": True,
            "providerFingerprint": "test-vector:v1",
            "totalVectors": self.vector_revision,
            "activeProviderVectors": self.vector_revision,
            "candidateLimit": 8,
            "weight": 1.0,
        }


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
        self.assertTrue(health["suggestionCache"]["enabled"])
        self.assertEqual(health["suggestionCache"]["hits"], 0)
        self.assertFalse(health["vectorStats"]["enabled"])
        self.assertFalse(health["predictor"]["configured"])
        self.assertEqual(health["predictor"]["providerName"], "NullPredictionProvider")
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

    def test_predictor_ttfc_probe_uses_streaming_provider(self) -> None:
        MockOllamaStreamingHandler.captured_payloads = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), MockOllamaStreamingHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.service.predictor = OllamaPredictionProvider(
                OllamaPredictionConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="qwen3.5:0.8b-mlx",
                    profile="instant",
                    timeout_s=1.0,
                )
            )
            report = self.service.predictor_ttfc(
                {
                    "cases": [
                        {
                            "id": "debug-case",
                            "currentInput": "RAG 输入法",
                            "recentContext": "用户正在调试模型首候选",
                        }
                    ],
                    "repeat": 1,
                    "latencyBudgetMs": 200,
                }
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(report["schemaVersion"], "rag-ime.debug-predictor-ttfc.v1")
        self.assertEqual(report["repeat"]["effectiveCaseCount"], 1)
        benchmark = report["benchmark"]
        self.assertTrue(benchmark["supported"])
        self.assertTrue(benchmark["summary"]["hasFirstCandidate"])
        self.assertEqual(benchmark["cases"][0]["caseId"], "debug-case")
        self.assertEqual(benchmark["cases"][0]["candidates"][0], "本地记忆")
        self.assertTrue(MockOllamaStreamingHandler.captured_payloads[0]["stream"])
        self.assertFalse(MockOllamaStreamingHandler.captured_payloads[0]["think"])

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
        self.assertEqual(payload["displayCandidates"][0]["selectionAction"], "commit_side_candidate")
        self.assertEqual(payload["displayCandidates"][0]["displayLayout"], "inline")
        self.assertEqual(payload["displayCandidates"][1]["selectionAction"], "commit_side_candidate")
        self.assertEqual(payload["displayCandidates"][1]["displayLayout"], "block")
        self.assertEqual(payload["displayCandidates"][2]["selectionAction"], "select_rime_candidate")
        self.assertEqual(payload["displayCandidates"][2]["displayLayout"], "fallback")
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

    def test_rime_suggest_dedupes_in_flight_equivalent_payloads(self) -> None:
        predictor = BlockingPredictionProvider()
        self.service.predictor = predictor
        payload = {
            "sessionId": "inflight-a",
            "requestSeq": 61,
            "rawInput": "ragshurufa",
            "preedit": "ragshurufa",
            "committedContext": "用户正在写 RAG 输入法",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 2,
            "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
        }
        second_payload = dict(payload)
        second_payload["sessionId"] = "inflight-b"
        second_payload["requestSeq"] = 62

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(self.service.rime_suggest, payload)
            self.assertTrue(predictor.entered.wait(timeout=2))
            second_future = pool.submit(self.service.rime_suggest, second_payload)
            self._wait_for_inflight_hits(expected=1)
            predictor.release.set()
            first = first_future.result(timeout=2)
            second = second_future.result(timeout=2)

        self.assertEqual(predictor.calls, 1)
        self.assertFalse(first["cache"]["hit"])
        self.assertFalse(first["cache"]["inFlightHit"])
        self.assertFalse(second["cache"]["hit"])
        self.assertTrue(second["cache"]["inFlightHit"])
        self.assertEqual(second["sessionId"], "inflight-b")
        self.assertEqual(second["requestSeq"], 62)
        self.assertEqual(self.service.health()["rimeSuggestCache"]["inFlightHits"], 1)

    def test_rime_suggest_cache_key_includes_vector_index_state(self) -> None:
        predictor = FakePredictionProvider()
        core = VectorAwareFixtureCore()
        service = DebugImeService(
            DebugServerConfig(
                core=core,
                predictor=predictor,
                seed_if_empty=False,
                project="wisdom-weasel-rag-ime",
            )
        )
        payload = {
            "sessionId": "cache-vector-a",
            "requestSeq": 51,
            "rawInput": "ragshurufa",
            "preedit": "ragshurufa",
            "committedContext": "用户正在写 RAG 输入法",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 2,
            "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
        }

        first = service.rime_suggest(payload)
        second_payload = dict(payload)
        second_payload["requestSeq"] = 52
        second = service.rime_suggest(second_payload)
        core.vector_revision += 1
        third_payload = dict(payload)
        third_payload["requestSeq"] = 53
        third = service.rime_suggest(third_payload)

        self.assertEqual(predictor.calls, 2)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertFalse(third["cache"]["hit"])
        self.assertEqual(service.health()["vectorStats"]["activeProviderVectors"], 2)

    def test_rime_suggest_cache_ignores_raw_pinyin_when_semantic_query_is_stable(self) -> None:
        predictor = FakePredictionProvider()
        self.service.predictor = predictor
        payload = {
            "sessionId": "cache-raw-a",
            "requestSeq": 41,
            "rawInput": "ragshuru",
            "preedit": "ragshuru",
            "committedContext": "用户正在写 RAG 输入法",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 2,
            "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
        }
        first = self.service.rime_suggest(payload)
        second_payload = dict(payload)
        second_payload["sessionId"] = "cache-raw-b"
        second_payload["requestSeq"] = 42
        second_payload["rawInput"] = "ragshurufa"
        second_payload["preedit"] = "ragshurufa"
        second = self.service.rime_suggest(second_payload)

        self.assertEqual(predictor.calls, 1)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(second["rawInput"], "ragshurufa")
        self.assertEqual(second["preedit"], "ragshurufa")
        self.assertEqual(second["semanticQuery"], "RAG 输入法")
        self.assertEqual(second["queryBasis"], "rimeCandidates")

    def test_cache_probe_reports_warm_suggestion_and_rime_hits(self) -> None:
        report = self.service.cache_probe(
            {
                "currentInput": "RAG 输入法",
                "recentContext": "用户正在调试缓存命中",
                "repeat": 3,
                "topK": 3,
            }
        )

        self.assertEqual(report["schemaVersion"], "rag-ime.debug-cache-probe.v1")
        self.assertEqual(report["repeat"], 3)
        self.assertEqual(report["expectedWarmHits"], 2)
        self.assertGreaterEqual(report["suggestionCache"]["hitsDelta"], 2)
        self.assertGreaterEqual(report["rimeSuggestCache"]["hitsDelta"], 2)
        self.assertTrue(report["summary"]["suggestionCachePassed"])
        self.assertTrue(report["summary"]["rimeCachePassed"])
        self.assertEqual(len(report["samples"]["rimeSuggest"]), 3)
        self.assertFalse(report["samples"]["rimeSuggest"][0]["hit"])
        self.assertTrue(report["samples"]["rimeSuggest"][1]["hit"])
        self.assertTrue(report["samples"]["suggest"][0]["topSuggestions"])

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

    def test_rime_select_records_commit_and_rag_action(self) -> None:
        before_actions = self.service.core.action_count()
        response = self.service.rime_suggest(
            {
                "sessionId": "select-rag",
                "requestSeq": 31,
                "rawInput": "ragshurufa",
                "preedit": "ragshurufa",
                "committedContext": "用户正在写 RAG 输入法",
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 2,
                "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
            }
        )
        rag_candidate = next(item for item in response["displayCandidates"] if item["sourceType"] == "rag")
        selection = self.service.rime_select(
            {
                "candidate": rag_candidate,
                "query": response["semanticQuery"],
                "recentContext": response["committedContext"],
                "preedit": response["preedit"],
                "project": response["project"],
            }
        )
        self.assertEqual(selection["schemaVersion"], "rag-ime.rime-selection.v1")
        self.assertTrue(selection["ok"])
        self.assertTrue(str(selection["eventId"]).startswith("event:"))
        self.assertTrue(selection["recordedAction"])
        self.assertEqual(selection["action"]["schemaVersion"], "rag-ime.action.v1")
        self.assertEqual(selection["action"]["actionType"], "accepted")
        self.assertEqual(self.service.core.action_count(), before_actions + 1)

    def test_rime_select_records_model_candidate_without_memory_action(self) -> None:
        before_actions = self.service.core.action_count()
        selection = self.service.rime_select(
            {
                "candidate": {
                    "label": "2",
                    "text": "模型短候选",
                    "insertText": "模型短候选",
                    "sourceType": "model",
                    "selectionAction": "commit_side_candidate",
                    "sourceIndex": 0,
                },
                "query": "模型",
                "recentContext": "用户正在测试 side candidate",
                "preedit": "moxing",
            }
        )
        self.assertTrue(str(selection["eventId"]).startswith("event:"))
        self.assertFalse(selection["recordedAction"])
        self.assertIsNone(selection["action"])
        self.assertEqual(self.service.core.action_count(), before_actions)

    def test_rime_select_dry_run_does_not_record_model_candidate(self) -> None:
        before_events = self.service.core.event_count()
        before_actions = self.service.core.action_count()
        selection = self.service.rime_select(
            {
                "dryRun": True,
                "candidate": {
                    "label": "2",
                    "text": "doctor side candidate",
                    "insertText": "doctor side candidate",
                    "sourceType": "model",
                    "selectionAction": "commit_side_candidate",
                    "sourceIndex": 0,
                },
                "query": "doctor",
                "recentContext": "Squirrel tryout readiness probe",
                "preedit": "doctor",
            }
        )
        self.assertEqual(selection["schemaVersion"], "rag-ime.rime-selection.v1")
        self.assertTrue(selection["dryRun"])
        self.assertEqual(selection["eventId"], "")
        self.assertFalse(selection["recordedAction"])
        self.assertEqual(self.service.core.event_count(), before_events)
        self.assertEqual(self.service.core.action_count(), before_actions)

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
            select_url = f"http://127.0.0.1:{server.server_port}/rime-select"
            select_request = Request(
                select_url,
                data=json.dumps(
                    {
                        "candidate": {
                            "label": "2",
                            "text": "HTTP side candidate",
                            "insertText": "HTTP side candidate",
                            "sourceType": "model",
                            "selectionAction": "commit_side_candidate",
                            "sourceIndex": 0,
                        },
                        "query": "HTTP",
                        "recentContext": "root path",
                        "preedit": "http",
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(select_request, timeout=5) as response:
                selection = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(payload["schemaVersion"], "rag-ime.rime-sidecar.v1")
        self.assertEqual(payload["sessionId"], "http-root")
        self.assertEqual(selection["schemaVersion"], "rag-ime.rime-selection.v1")
        self.assertTrue(str(selection["eventId"]).startswith("event:"))

    def test_http_debug_server_exposes_predictor_ttfc_probe(self) -> None:
        MockOllamaStreamingHandler.captured_payloads = []
        model_server = ThreadingHTTPServer(("127.0.0.1", 0), MockOllamaStreamingHandler)
        model_thread = Thread(target=model_server.serve_forever, daemon=True)
        model_thread.start()

        class Handler(DebugRequestHandler):
            pass

        self.service.predictor = OllamaPredictionProvider(
            OllamaPredictionConfig(
                base_url=f"http://127.0.0.1:{model_server.server_port}",
                model="qwen3.5:0.8b-mlx",
                profile="instant",
                timeout_s=1.0,
            )
        )
        Handler.service = self.service
        Handler.static_dir = Path("debug")
        debug_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        debug_thread = Thread(target=debug_server.serve_forever, daemon=True)
        debug_thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{debug_server.server_port}/api/predictor-ttfc",
                data=json.dumps(
                    {
                        "currentInput": "Squirrel 候选",
                        "recentContext": "HTTP debug probe",
                        "repeat": 1,
                        "latencyBudgetMs": 200,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            debug_server.shutdown()
            debug_thread.join(timeout=2)
            debug_server.server_close()
            model_server.shutdown()
            model_thread.join(timeout=2)
            model_server.server_close()

        self.assertEqual(payload["schemaVersion"], "rag-ime.debug-predictor-ttfc.v1")
        self.assertEqual(payload["benchmark"]["providerName"], "local-ollama")
        self.assertTrue(payload["benchmark"]["summary"]["hasFirstCandidate"])
        self.assertEqual(MockOllamaStreamingHandler.captured_payloads[0]["model"], "qwen3.5:0.8b-mlx")

    def test_http_debug_server_exposes_cache_probe(self) -> None:
        class Handler(DebugRequestHandler):
            pass

        Handler.service = self.service
        Handler.static_dir = Path("debug")
        debug_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        debug_thread = Thread(target=debug_server.serve_forever, daemon=True)
        debug_thread.start()
        try:
            request = Request(
                f"http://127.0.0.1:{debug_server.server_port}/api/cache-probe",
                data=json.dumps(
                    {
                        "currentInput": "缓存命中",
                        "recentContext": "HTTP debug cache probe",
                        "repeat": 3,
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            debug_server.shutdown()
            debug_thread.join(timeout=2)
            debug_server.server_close()

        self.assertEqual(payload["schemaVersion"], "rag-ime.debug-cache-probe.v1")
        self.assertGreaterEqual(payload["summary"]["rimeCacheHitDelta"], 2)
        self.assertIn("suggestionCache", payload)

    def test_cli_cache_probe_runs_without_debug_server(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-cli-cache-probe-") as tmp:
            db_path = Path(tmp) / "rag-ime.sqlite"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rag_ime.cli",
                    "--db-path",
                    str(db_path),
                    "seed-demo",
                    "--reset",
                ],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rag_ime.cli",
                    "--db-path",
                    str(db_path),
                    "cache-probe",
                    "RAG 输入法",
                    "--recent-context",
                    "CLI cache probe",
                    "--repeat",
                    "3",
                    "--rime-candidate",
                    "RAG 输入法",
                ],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schemaVersion"], "rag-ime.debug-cache-probe.v1")
        self.assertEqual(payload["repeat"], 3)
        self.assertGreaterEqual(payload["suggestionCache"]["hitsDelta"], 2)
        self.assertGreaterEqual(payload["rimeSuggestCache"]["hitsDelta"], 2)
        self.assertTrue(payload["summary"]["suggestionCachePassed"])
        self.assertTrue(payload["summary"]["rimeCachePassed"])

    def test_input_source_status_parses_check_script_output(self) -> None:
        script = Path(self.tmp.name) / "check-input-source.sh"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "input-source.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=False,
                input_source_check_script=script,
            )
        )

        status = service.input_source_status()

        self.assertEqual(status["schemaVersion"], "rag-ime.debug-input-source.v1")
        self.assertTrue(status["ok"])
        self.assertFalse(status["typingReady"])
        self.assertEqual(status["id"], "im.rime.inputmethod.Squirrel.Hans")
        self.assertEqual(status["name"], "Squirrel - Simplified")
        self.assertTrue(status["enabled"])
        self.assertTrue(status["selectable"])
        self.assertTrue(status["hitoolboxEnabled"])
        self.assertEqual(status["current"], "com.apple.keylayout.ABC")
        self.assertEqual(status["readinessState"], "switch")
        self.assertEqual(status["nextAction"], "select Squirrel from the macOS input menu")
        self.assertEqual(status["manualAction"], "macOS input menu -> Squirrel - Simplified")
        self.assertEqual(status["verificationCommand"], "scripts/wait_squirrel_typing_ready.sh")
        self.assertEqual(
            [item["name"] for item in status["readinessChecks"]],
            ["tis-visible", "third-party-list", "selected"],
        )

    def test_http_debug_server_exposes_input_source_status(self) -> None:
        script = Path(self.tmp.name) / "check-input-source.sh"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=true current=im.rime.inputmethod.Squirrel.Hans hitoolboxEnabled=true'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "input-source-http.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=False,
                input_source_check_script=script,
            )
        )

        class Handler(DebugRequestHandler):
            pass

        Handler.service = service
        Handler.static_dir = Path("debug")
        debug_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        debug_thread = Thread(target=debug_server.serve_forever, daemon=True)
        debug_thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{debug_server.server_port}/api/input-source", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            debug_server.shutdown()
            debug_thread.join(timeout=2)
            debug_server.server_close()

        self.assertEqual(payload["schemaVersion"], "rag-ime.debug-input-source.v1")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["typingReady"])
        self.assertTrue(payload["selected"])
        self.assertEqual(payload["readinessState"], "ready")
        self.assertEqual(payload["nextAction"], "start typing with Squirrel")
        self.assertEqual(payload["manualAction"], "type in a foreground macOS text field")
        self.assertEqual(payload["verificationCommand"], "scripts/wait_squirrel_typing_ready.sh")

    def test_input_source_status_marks_missing_source_as_install_needed(self) -> None:
        script = Path(self.tmp.name) / "check-input-source-missing.sh"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=false selectable=false selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false'",
                    "exit 1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "input-source-missing.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=False,
                input_source_check_script=script,
            )
        )

        status = service.input_source_status()

        self.assertFalse(status["ok"])
        self.assertFalse(status["typingReady"])
        self.assertEqual(status["readinessState"], "install")
        self.assertEqual(status["nextAction"], "add Squirrel in System Settings, then wait for the add gate")
        self.assertEqual(
            status["manualAction"],
            "System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> Squirrel - Simplified",
        )
        self.assertEqual(status["helperCommand"], "scripts/open_squirrel_input_source_settings.sh --wait")
        self.assertEqual(status["verificationCommand"], "scripts/wait_squirrel_input_source_added.sh")

    def test_input_source_status_marks_missing_third_party_registration_as_install_needed(self) -> None:
        script = Path(self.tmp.name) / "check-input-source-third-party-missing.sh"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                    "exit 1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "input-source-third-party-missing.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=False,
                input_source_check_script=script,
            )
        )

        status = service.input_source_status()

        self.assertFalse(status["ok"])
        self.assertFalse(status["typingReady"])
        self.assertTrue(status["enabled"])
        self.assertTrue(status["selectable"])
        self.assertFalse(status["hitoolboxEnabled"])
        self.assertFalse(status["thirdPartyEnabled"])
        self.assertEqual(status["readinessState"], "install")
        self.assertEqual(status["nextAction"], "add Squirrel in System Settings, then wait for the add gate")
        self.assertEqual(status["helperCommand"], "scripts/open_squirrel_input_source_settings.sh --wait")
        self.assertEqual(status["verificationCommand"], "scripts/wait_squirrel_input_source_added.sh")
        third_party_check = next(item for item in status["readinessChecks"] if item["name"] == "third-party-list")
        self.assertFalse(third_party_check["passed"])
        self.assertFalse(third_party_check["thirdPartyEnabled"])

    def test_input_source_status_uses_branded_rag_ime_manual_action(self) -> None:
        script = Path(self.tmp.name) / "check-input-source-rag-ime-third-party-missing.sh"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "echo 'id=im.rag-ime.inputmethod.RagIme.Hans name=RAG-IME - Simplified enabled=true selectable=true selected=false current=im.rime.inputmethod.Squirrel.Hans hitoolboxEnabled=false thirdPartyEnabled=false'",
                    "exit 1",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        service = DebugImeService(
            DebugServerConfig(
                db_path=Path(self.tmp.name) / "input-source-rag-ime-missing.sqlite",
                static_dir=Path("debug"),
                seed_if_empty=False,
                input_source_id="im.rag-ime.inputmethod.RagIme.Hans",
                input_source_check_script=script,
            )
        )

        status = service.input_source_status()

        self.assertFalse(status["ok"])
        self.assertEqual(status["readinessState"], "install")
        self.assertEqual(status["nextAction"], "add RAG-IME in System Settings, then wait for the add gate")
        self.assertEqual(
            status["manualAction"],
            "System Settings -> Keyboard -> Input Sources -> Add -> Chinese, Simplified -> RAG-IME - Simplified",
        )
        self.assertEqual(status["expectedInputSourceId"], "im.rag-ime.inputmethod.RagIme.Hans")

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

    def _wait_for_inflight_hits(self, *, expected: int) -> None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if self.service.health()["rimeSuggestCache"]["inFlightHits"] >= expected:
                return
            time.sleep(0.01)
        self.fail(f"timed out waiting for {expected} in-flight cache hit(s)")


if __name__ == "__main__":
    unittest.main()
