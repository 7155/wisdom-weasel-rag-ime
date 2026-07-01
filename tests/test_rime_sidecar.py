from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import main
from rag_ime.core_client import FixtureCoreClient
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputSuggestion, ModelPrediction
from rag_ime.predictor import CooldownPredictionProvider, OpenAICompatiblePredictionConfig
from rag_ime.rime_sidecar import (
    build_rime_sidecar_response,
    choose_semantic_query,
    decide_side_candidate_refresh,
    parse_rime_context_payload,
)


class FakePredictionProvider:
    def __init__(self) -> None:
        self.last_current_input = ""
        self.last_recent_context = ""

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.last_current_input = current_input
        self.last_recent_context = recent_context
        return [
            ModelPrediction(
                text=f"{current_input}续写",
                rank=1,
                provider_name="fake-rime-model",
                latency_ms=9,
                confidence=0.88,
            )
        ][:max_candidates]


class MultiPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(text=f"{current_input}模型{i}", rank=i, provider_name="multi-model", latency_ms=8)
            for i in range(1, max_candidates + 1)
        ]


class FailingPredictionProvider:
    config = OpenAICompatiblePredictionConfig(
        base_url="http://127.0.0.1:9",
        model="Qwen3-0.6B",
        provider_name="failing-rime-model",
        profile="instant",
    )

    def __init__(self) -> None:
        self.calls = 0
        self.last_error = ""

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        self.last_error = "timeout"
        return []


class SlowPredictionProvider:
    def __init__(self, sleep_s: float = 0.1) -> None:
        self.sleep_s = sleep_s
        self.calls = 0

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        time.sleep(self.sleep_s)
        return [
            ModelPrediction(
                text=f"{current_input}慢模型",
                rank=1,
                provider_name="slow-model",
                latency_ms=int(self.sleep_s * 1000),
            )
        ]


class CapturingCore:
    def __init__(self) -> None:
        self.last_suggest_recent_context = ""

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", top_k: int = 5):
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="spy:1",
                surface_text="RAG 输入法本地记忆",
                suggestion_type="rag_candidate",
                source_event_id=1,
                evidence_preview="spy",
                confidence=0.9,
            )
        ][:top_k]

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        return "历史输入会进入模型预测 但不能污染 RAG 检索"


class SlowSuggestionCore(CapturingCore):
    def __init__(self, sleep_s: float = 0.1) -> None:
        super().__init__()
        self.sleep_s = sleep_s
        self.calls = 0

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", top_k: int = 5):
        self.calls += 1
        time.sleep(self.sleep_s)
        return super().suggest_for_input(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            top_k=top_k,
        )


class SlowHistoryCore(CapturingCore):
    def __init__(self, sleep_s: float = 0.1) -> None:
        super().__init__()
        self.sleep_s = sleep_s

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        time.sleep(self.sleep_s)
        return super().recent_input_context(project=project, limit=limit, max_chars=max_chars)


class RimeSidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.core = FixtureCoreClient()
        self.adapter = InputMethodAdapter(self.core)
        self.predictor = FakePredictionProvider()

    def test_semantic_query_uses_rime_candidates_not_dirty_raw_pinyin(self) -> None:
        snapshot = parse_rime_context_payload(
            {
                "sessionId": "s1",
                "requestSeq": 7,
                "rawInput": "jiubiruwopinshishur",
                "preedit": "jiubiruwopinshishur",
                "committedContext": "用户正在讨论输入法项目",
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "就比如", "comment": "Rime"},
                        {"label": "2", "text": "我平时输入", "comment": "Rime"},
                    ]
                },
            },
            default_project="wisdom-weasel-rag-ime",
        )
        semantic_query, basis = choose_semantic_query(snapshot)
        self.assertEqual(basis, "rimeCandidates")
        self.assertIn("就比如", semantic_query)
        self.assertNotIn("jiubiruwopinshishur", semantic_query)

    def test_response_merges_side_candidates_first_then_rime_fallback(self) -> None:
        payload = {
            "sessionId": "squirrel-1",
            "requestSeq": 42,
            "rawInput": "ragshurufa",
            "preedit": "ragshurufa",
            "committedContext": "RAG 输入法需要复用 Rime 词库",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                    {"label": "2", "text": "RAG 是", "comment": "rime"},
                ],
                "highlightedIndex": 0,
                "page": 0,
                "isLastPage": True,
            },
        }
        response = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        self.assertEqual(response["schemaVersion"], "rag-ime.rime-sidecar.v1")
        self.assertEqual(response["requestSeq"], 42)
        self.assertEqual(response["queryBasis"], "rimeCandidates")
        self.assertIn("RAG 输入法", self.predictor.last_current_input)
        display = response["displayCandidates"]
        self.assertEqual(display[0]["sourceType"], "model")
        self.assertEqual(display[0]["selectionAction"], "commit_side_candidate")
        self.assertEqual(display[0]["displayLayout"], "inline")
        self.assertEqual(display[0]["displayLane"], "model")
        self.assertEqual(display[1]["sourceType"], "rag")
        self.assertEqual(display[1]["selectionAction"], "commit_side_candidate")
        self.assertEqual(display[1]["displayLayout"], "block")
        self.assertEqual(display[1]["displayLane"], "memory")
        self.assertIsInstance(display[1]["sourceEventId"], int)
        self.assertEqual(display[2]["sourceType"], "rag")
        self.assertEqual(display[2]["selectionAction"], "commit_side_candidate")
        self.assertEqual(display[3]["sourceType"], "rime")
        self.assertEqual(display[3]["selectionAction"], "select_rime_candidate")
        self.assertEqual(display[3]["displayLayout"], "fallback")
        self.assertEqual(display[3]["displayLane"], "rime")
        self.assertEqual(display[3]["rimeIndex"], 0)
        self.assertEqual([item["label"] for item in display[:4]], ["1", "2", "3", "4"])
        self.assertEqual([item["selectionKey"] for item in display[:4]], ["1", "2", "3", "4"])
        self.assertEqual([item["selectionRank"] for item in display[:4]], [1, 2, 3, 4])
        self.assertFalse(response["mergePolicy"]["rimeFirst"])
        self.assertTrue(response["mergePolicy"]["sideFirst"])
        self.assertEqual(response["mergePolicy"]["fallbackOrder"], ["model", "rag", "rime"])
        self.assertTrue(response["modelLane"]["called"])
        self.assertFalse(response["modelLane"]["timedOut"])
        self.assertEqual(response["modelLane"]["predictionCount"], 1)
        self.assertEqual(response["modelLane"]["totalLatencyBudgetMs"], 150)

    def test_tenth_shared_candidate_uses_zero_key_with_rank_ten(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-zero-key",
                "requestSeq": 44,
                "maxVisibleCandidates": 10,
                "maxSideCandidates": 10,
                "rimeContext": {
                    "candidates": [
                        {"label": str(index + 1), "text": f"候选{index + 1}", "comment": "rime"}
                        for index in range(9)
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        display = response["displayCandidates"]
        self.assertEqual(len(display), 10)
        self.assertEqual(display[9]["sourceType"], "model")
        self.assertEqual(display[9]["label"], "0")
        self.assertEqual(display[9]["selectionKey"], "0")
        self.assertEqual(display[9]["selectionRank"], 10)

    def test_history_context_is_only_used_for_model_not_rag_retrieval(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-context-boundary",
                "requestSeq": 43,
                "committedContext": "当前正在写 RAG 输入法 sidecar",
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 2,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertIn("历史输入会进入模型预测", predictor.last_recent_context)
        self.assertIn("当前上下文: 当前正在写 RAG 输入法 sidecar", predictor.last_recent_context)
        self.assertEqual(core.last_suggest_recent_context, "当前正在写 RAG 输入法 sidecar")
        self.assertNotIn("历史输入会进入模型预测", core.last_suggest_recent_context)
        self.assertEqual(response["historyContext"], predictor.last_recent_context)
        history_meta = response["historyContextMeta"]
        self.assertEqual(history_meta["chars"], len(predictor.last_recent_context))
        self.assertEqual(len(history_meta["fingerprint"]), 16)
        self.assertTrue(history_meta["hasHistory"])
        self.assertTrue(history_meta["hasExplicitContext"])

    def test_zero_side_candidates_does_not_call_model(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-no-side",
                "requestSeq": 8,
                "maxSideCandidates": 0,
                "rimeContext": {"candidates": [{"label": "1", "text": "正常 Rime 候选"}]},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        self.assertEqual(self.predictor.last_current_input, "")
        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["ragCandidates"], [])
        self.assertEqual(len(response["displayCandidates"]), 1)
        self.assertEqual(response["displayCandidates"][0]["sourceType"], "rime")

    def test_max_side_candidates_is_global_across_model_and_rag(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-side-cap",
                "requestSeq": 9,
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 2,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        side_items = [item for item in response["displayCandidates"] if item["sourceType"] != "rime"]
        self.assertEqual(len(side_items), 2)
        self.assertEqual(side_items[0]["sourceType"], "model")
        self.assertEqual(side_items[1]["sourceType"], "rag")
        self.assertEqual(response["mergePolicy"]["maxModelSideCandidates"], 2)
        self.assertFalse(response["mergePolicy"]["ragKeepsRemainingSideSlots"])
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: stable Rime candidates")

    def test_model_predictions_can_fill_all_side_slots_before_rag_fallback(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-side-balance",
                "requestSeq": 10,
                "maxVisibleCandidates": 6,
                "maxSideCandidates": 3,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )
        side_items = [item for item in response["displayCandidates"] if item["sourceType"] != "rime"]
        self.assertEqual([item["sourceType"] for item in side_items], ["model", "model", "model"])
        self.assertEqual(len(response["modelPredictions"]), 3)

    def test_predictor_cooldown_skips_second_rime_refresh_but_keeps_rag(self) -> None:
        delegate = FailingPredictionProvider()
        predictor = CooldownPredictionProvider(delegate, cooldown_ms=1000, failure_latency_ms=1)
        payload = {
            "sessionId": "squirrel-model-down",
            "requestSeq": 1,
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 2,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                ]
            },
        }

        first = build_rime_sidecar_response(payload=payload, adapter=self.adapter, core=self.core, predictor=predictor)
        second = build_rime_sidecar_response(payload={**payload, "requestSeq": 2}, adapter=self.adapter, core=self.core, predictor=predictor)

        self.assertEqual(delegate.calls, 1)
        self.assertEqual(first["modelPredictions"], [])
        self.assertEqual(second["modelPredictions"], [])
        self.assertTrue(any(item["sourceType"] == "rag" for item in first["displayCandidates"]))
        self.assertTrue(any(item["sourceType"] == "rag" for item in second["displayCandidates"]))

    def test_model_lane_timeout_keeps_rag_candidates_responsive(self) -> None:
        slow_predictor = SlowPredictionProvider(sleep_s=0.12)
        started = time.perf_counter()
        try:
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-tight-budget",
                    "requestSeq": 77,
                    "latencyBudgetMs": 30,
                    "maxVisibleCandidates": 5,
                    "maxSideCandidates": 2,
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                        ]
                    },
                },
                adapter=self.adapter,
                core=self.core,
                predictor=slow_predictor,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        finally:
            time.sleep(0.14)

        self.assertLess(elapsed_ms, 100)
        self.assertEqual(slow_predictor.calls, 1)
        self.assertEqual(response["modelPredictions"], [])
        self.assertTrue(response["modelLane"]["called"])
        self.assertTrue(response["modelLane"]["timedOut"])
        self.assertEqual(response["modelLane"]["skippedReason"], "model lane exceeded latency budget")
        self.assertEqual(response["modelLane"]["predictionCount"], 0)
        self.assertTrue(any(item["sourceType"] == "rag" for item in response["displayCandidates"]))

    def test_rag_lane_timeout_does_not_block_parallel_model_lane(self) -> None:
        core = SlowSuggestionCore(sleep_s=0.12)
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        started = time.perf_counter()
        try:
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-slow-rag",
                    "requestSeq": 78,
                    "latencyBudgetMs": 30,
                    "maxVisibleCandidates": 5,
                    "maxSideCandidates": 2,
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                        ]
                    },
                },
                adapter=adapter,
                core=core,
                predictor=predictor,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        finally:
            time.sleep(0.14)

        self.assertLess(elapsed_ms, 100)
        self.assertEqual(core.calls, 1)
        self.assertEqual(predictor.last_current_input, "RAG 输入法")
        self.assertEqual(response["ragCandidates"], [])
        self.assertTrue(response["ragLane"]["called"])
        self.assertTrue(response["ragLane"]["timedOut"])
        self.assertEqual(response["ragLane"]["skippedReason"], "RAG lane exceeded latency budget")
        self.assertTrue(response["modelLane"]["called"])
        self.assertFalse(response["modelLane"]["timedOut"])
        self.assertEqual(response["modelLane"]["sideLaneMode"], "parallel")
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["model", "rime"])

    def test_slow_history_context_does_not_call_model_after_budget_timeout(self) -> None:
        core = SlowHistoryCore(sleep_s=0.12)
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        started = time.perf_counter()
        try:
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-slow-history",
                    "requestSeq": 79,
                    "latencyBudgetMs": 40,
                    "maxVisibleCandidates": 5,
                    "maxSideCandidates": 2,
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                        ]
                    },
                },
                adapter=adapter,
                core=core,
                predictor=predictor,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        finally:
            time.sleep(0.14)

        self.assertLess(elapsed_ms, 100)
        self.assertEqual(predictor.last_current_input, "")
        self.assertTrue(response["modelLane"]["called"])
        self.assertTrue(response["modelLane"]["timedOut"])
        self.assertEqual(response["modelPredictions"], [])
        self.assertTrue(any(item["sourceType"] == "rag" for item in response["displayCandidates"]))

    def test_rag_display_text_is_compressed_but_insert_text_is_full(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-sidecar-surface-") as tmp:
            core = LocalSqliteCoreClient(f"{tmp}/rag-ime.sqlite")
            core.initialize()
            adapter = InputMethodAdapter(core)
            adapter.commit_text(
                "背景说明这一句不是候选重点。\n"
                "- 候选面板只显示压缩标题，完整段落放 insert_text。\n"
                "- evidence preview 放到展开面板。",
                recent_context="RAG candidate surface compression",
                project="wisdom-weasel-rag-ime",
                tags=("structure",),
            )

            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-surface",
                    "requestSeq": 101,
                    "maxVisibleCandidates": 4,
                    "maxSideCandidates": 2,
                    "forceSideCandidates": True,
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "候选面板", "comment": "rime"},
                        ]
                    },
                },
                adapter=adapter,
                core=core,
                predictor=self.predictor,
            )

        rag_item = next(item for item in response["displayCandidates"] if item["sourceType"] == "rag")
        self.assertEqual(rag_item["text"], "候选面板只显示压缩标题，完整段落放 insert_text。")
        self.assertIn("背景说明这一句不是候选重点", rag_item["insertText"])
        self.assertIn("evidence preview 放到展开面板", rag_item["insertText"])

    def test_dirty_raw_pinyin_without_rime_candidates_skips_side_lanes(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-dirty-pinyin",
                "requestSeq": 11,
                "rawInput": "jiubiruwopinshishur",
                "preedit": "jiubiruwopinshishur",
                "maxVisibleCandidates": 6,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        self.assertEqual(self.predictor.last_current_input, "")
        self.assertFalse(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "skip: raw pinyin fallback")
        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["ragCandidates"], [])
        self.assertEqual(response["displayCandidates"], [])
        self.assertFalse(response["mergePolicy"]["sideCandidatesEnabled"])

    def test_dirty_raw_pinyin_can_use_recent_committed_context_fallback(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-recent-context-fallback",
                "requestSeq": 15,
                "rawInput": "asdioj",
                "preedit": "asdioj",
                "committedContext": "刚刚输入了 RAG 输入法的候选布局，需要继续预测下一句",
                "maxVisibleCandidates": 6,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: recent committed context fallback")
        self.assertIn("刚刚输入了", self.predictor.last_current_input)
        self.assertIn(response["displayCandidates"][0]["sourceType"], {"model", "rag"})

    def test_short_rime_candidate_skips_until_idle(self) -> None:
        snapshot = parse_rime_context_payload(
            {
                "sessionId": "squirrel-short",
                "requestSeq": 12,
                "rawInput": "s",
                "preedit": "s",
                "rimeContext": {"candidates": [{"label": "1", "text": "是", "comment": "rime"}]},
            },
            default_project="wisdom-weasel-rag-ime",
        )
        semantic_query, query_basis = choose_semantic_query(snapshot)
        decision = decide_side_candidate_refresh(
            snapshot=snapshot,
            semantic_query=semantic_query,
            query_basis=query_basis,
        )
        self.assertFalse(decision.should_refresh)
        self.assertEqual(decision.reason, "skip: Rime candidate signal too short")

    def test_force_side_candidates_refreshes_even_for_raw_fallback(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-force",
                "requestSeq": 13,
                "rawInput": "rag",
                "preedit": "rag",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 1,
                "rimeContext": {"candidates": []},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "force: explicit side candidate refresh")
        self.assertEqual(self.predictor.last_current_input, "rag")
        self.assertEqual(response["displayCandidates"][0]["sourceType"], "model")

    def test_cli_rime_suggest_json_reads_payload_file(self) -> None:
        payload = {
            "sessionId": "cli-s1",
            "requestSeq": 3,
            "committedContext": "本地记忆输入法",
            "rimeContext": {"candidates": [{"text": "本地记忆"}]},
            "maxVisibleCandidates": 3,
            "maxSideCandidates": 1,
        }
        stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            old_stdin = sys.stdin
            try:
                sys.stdin = stdin
                code = main(["--core-mode", "fixture", "rime-suggest-json"])
            finally:
                sys.stdin = old_stdin
        self.assertEqual(code, 0)
        response = json.loads(stdout.getvalue())
        self.assertEqual(response["schemaVersion"], "rag-ime.rime-sidecar.v1")
        self.assertEqual(response["sessionId"], "cli-s1")
        self.assertIn(response["displayCandidates"][0]["sourceType"], {"model", "rag"})

    def test_cli_rime_select_json_records_side_candidate_commit(self) -> None:
        payload = {
            "candidate": {
                "label": "3",
                "text": "统一选择写回",
                "insertText": "统一选择写回接口",
                "sourceType": "model",
                "selectionAction": "commit_side_candidate",
                "sourceIndex": 0,
            },
            "query": "选择写回",
            "recentContext": "Squirrel fallback",
            "preedit": "xuanze",
        }
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-") as tmp:
            db_path = f"{tmp}/select.sqlite"
            stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                old_stdin = sys.stdin
                try:
                    sys.stdin = stdin
                    code = main(["--db-path", db_path, "rime-select-json"])
                finally:
                    sys.stdin = old_stdin
            self.assertEqual(code, 0)
            response = json.loads(stdout.getvalue())
            self.assertEqual(response["schemaVersion"], "rag-ime.rime-selection.v1")
            self.assertEqual(response["insertText"], "统一选择写回接口")
            self.assertFalse(response["recordedAction"])
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT committed_text, candidate_rank, source FROM input_events WHERE committed_text = ?",
                    ("统一选择写回接口",),
                ).fetchone()
            self.assertEqual(row, ("统一选择写回接口", 3, "squirrel_rime_sidecar"))

    def test_cli_rime_select_json_maps_zero_label_to_rank_ten(self) -> None:
        payload = {
            "candidate": {
                "label": "0",
                "selectionKey": "0",
                "selectionRank": 10,
                "text": "第十个候选",
                "insertText": "第十个候选",
                "sourceType": "model",
                "selectionAction": "commit_side_candidate",
                "sourceIndex": 0,
            },
            "query": "第十个",
            "recentContext": "Squirrel shared labels",
            "preedit": "di",
        }
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-zero-") as tmp:
            db_path = f"{tmp}/select.sqlite"
            stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                old_stdin = sys.stdin
                try:
                    sys.stdin = stdin
                    code = main(["--db-path", db_path, "rime-select-json"])
                finally:
                    sys.stdin = old_stdin
            self.assertEqual(code, 0)
            response = json.loads(stdout.getvalue())
            self.assertEqual(response["schemaVersion"], "rag-ime.rime-selection.v1")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT committed_text, candidate_rank FROM input_events WHERE committed_text = ?",
                    ("第十个候选",),
                ).fetchone()
            self.assertEqual(row, ("第十个候选", 10))


if __name__ == "__main__":
    unittest.main()
