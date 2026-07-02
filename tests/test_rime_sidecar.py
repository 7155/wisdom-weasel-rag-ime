from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import main
from rag_ime.core_client import FixtureCoreClient
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputSuggestion, ModelPrediction
from rag_ime.predictor import CooldownPredictionProvider, OpenAICompatiblePredictionConfig
from rag_ime.rime_sidecar import (
    build_rime_sidecar_response,
    choose_semantic_query,
    clear_model_prediction_holdover_cache,
    clear_prediction_manager_cache,
    decide_side_candidate_refresh,
    merge_display_candidates,
    parse_rime_context_payload,
    recent_context_memory_suggestions,
    wait_for_model_prediction_lane_idle,
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


class PrefixConstrainedPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text="设计输入法状态机",
                rank=1,
                provider_name="qwen-mlx",
                latency_ms=12,
                confidence=0.82,
                metadata={"initials": "sjsrfztj"},
            ),
            ModelPrediction(
                text="把这个项目整理成面试亮点",
                rank=2,
                provider_name="qwen-mlx",
                latency_ms=12,
                confidence=0.9,
                metadata={"initials": "bzgxmzlmsld"},
            ),
        ][:max_candidates]


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


class BlockingPredictionProvider:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.calls = 0

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("blocking predictor was not released")
        return [
            ModelPrediction(
                text="阻塞后候选",
                rank=1,
                provider_name="blocking-model",
                latency_ms=250,
                confidence=0.9,
            )
        ][:max_candidates]


class CapturingCore:
    def __init__(self) -> None:
        self.last_suggest_recent_context = ""
        self.last_suggest_app = ""

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_recent_context = recent_context
        self.last_suggest_app = app
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


class EmptySuggestionCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_recent_context = recent_context
        self.last_suggest_app = app
        return []


class PrefixSuggestionCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        return [
            InputSuggestion(
                suggestion_id="prefix:1",
                surface_text="设计一个候选展示方式",
                suggestion_type="rag",
                source_event_id=1,
                evidence_preview="用户之前讨论过候选展示方式",
                confidence=0.94,
                metadata={
                    "insert_text": "设计一个候选展示方式",
                    "source_type": "rag",
                    "initials": "sjygxhzsfs",
                },
            ),
            InputSuggestion(
                suggestion_id="prefix:2",
                surface_text="把本地记忆注入 Agent 首次运行上下文",
                suggestion_type="rag",
                source_event_id=2,
                evidence_preview="不匹配 sj，应被 prefix 过滤",
                confidence=0.99,
                metadata={"source_type": "rag", "initials": "bbdjy zr agent scyx sxw"},
            ),
        ][:top_k]


class SlowSuggestionCore(CapturingCore):
    def __init__(self, sleep_s: float = 0.1) -> None:
        super().__init__()
        self.sleep_s = sleep_s
        self.calls = 0

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
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
        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=1.0))
        clear_model_prediction_holdover_cache()
        clear_prediction_manager_cache()
        self.core = FixtureCoreClient()
        self.adapter = InputMethodAdapter(self.core)
        self.predictor = FakePredictionProvider()

    def tearDown(self) -> None:
        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=1.0))
        clear_model_prediction_holdover_cache()
        clear_prediction_manager_cache()

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
        self.assertEqual(response["modelLane"]["totalLatencyBudgetMs"], 300)

    def test_layout_contract_keeps_model_inline_and_sentence_candidates_block(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-layout-contract",
                "requestSeq": 45,
                "committedContext": "正在验证 LLM 横向短候选和 RAG 句子纵向候选",
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "forceSideCandidates": True,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "而且", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        display = response["displayCandidates"]
        model_items = [item for item in display if item["sourceType"] == "model"]
        rag_items = [item for item in display if item["sourceType"] == "rag"]
        rime_items = [item for item in display if item["sourceType"] == "rime"]
        self.assertEqual(len(model_items), 5)
        self.assertEqual(len(rag_items), 3)
        self.assertEqual(rime_items, [])
        self.assertTrue(all(item["displayLayout"] == "inline" for item in model_items))
        self.assertTrue(all(item["displayLane"] == "model" for item in model_items))
        self.assertTrue(all(item["displayLayout"] == "block" for item in rag_items))
        self.assertTrue(all(item["displayLane"] == "memory" for item in rag_items))
        self.assertEqual(response["mergePolicy"]["fallbackOrder"], ["model", "rag", "rime"])

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
        self.assertIn(display[9]["sourceType"], {"model", "rag"})
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

    def test_frontmost_app_payload_reaches_rag_retrieval(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-app-context",
                "requestSeq": 44,
                "frontmostApp": "com.openai.codex",
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

        self.assertEqual(core.last_suggest_app, "com.openai.codex")
        self.assertEqual(response["rimeContext"]["app"], "com.openai.codex")

    def test_model_history_context_uses_low_latency_context_cap(self) -> None:
        class LongHistoryCore(CapturingCore):
            def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
                return "很长的历史输入上下文" * 40

        core = LongHistoryCore()
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_MODEL_CONTEXT_EVENTS": "2",
                "RAG_IME_MODEL_CONTEXT_CHARS": "48",
            },
        ):
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-model-context-cap",
                    "requestSeq": 46,
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

        self.assertLessEqual(len(predictor.last_recent_context), 48)
        self.assertEqual(response["historyContext"], predictor.last_recent_context)
        self.assertEqual(core.last_suggest_recent_context, "当前正在写 RAG 输入法 sidecar")
        self.assertNotIn("很长的历史输入上下文" * 3, predictor.last_recent_context)

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
        self.assertEqual(response["mergePolicy"]["ragBlockReserve"], 1)
        self.assertTrue(response["mergePolicy"]["ragKeepsRemainingSideSlots"])
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: stable Rime candidates")

    def test_model_predictions_keep_block_rows_for_rag_when_available(self) -> None:
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
        self.assertEqual([item["sourceType"] for item in side_items], ["model", "rag", "rag"])
        self.assertEqual(side_items[0]["displayLayout"], "inline")
        self.assertEqual(side_items[1]["displayLayout"], "block")
        self.assertEqual(len(response["modelPredictions"]), 3)

    def test_eight_slot_panel_uses_horizontal_model_lane_and_vertical_memory_rows(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-mixed-layout",
                "requestSeq": 11,
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "而且", "comment": "rime"},
                        {"label": "2", "text": "而去", "comment": "rime"},
                        {"label": "3", "text": "二期", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        display = response["displayCandidates"]
        self.assertEqual(len(display), 8)
        self.assertEqual([item["label"] for item in display], ["1", "2", "3", "4", "5", "6", "7", "8"])
        self.assertEqual([item["sourceType"] for item in display[:5]], ["model"] * 5)
        self.assertEqual([item["displayLayout"] for item in display[:5]], ["inline"] * 5)
        self.assertEqual([item["displayLane"] for item in display[:5]], ["model"] * 5)
        self.assertEqual([item["sourceType"] for item in display[5:]], ["rag", "rag", "rag"])
        self.assertEqual([item["displayLayout"] for item in display[5:]], ["block", "block", "block"])
        self.assertEqual([item["displayLane"] for item in display[5:]], ["memory", "memory", "memory"])
        self.assertFalse(any(item["sourceType"] == "rime" for item in display))
        self.assertEqual(response["mergePolicy"]["ragBlockReserve"], 3)
        self.assertTrue(response["mergePolicy"]["ragKeepsRemainingSideSlots"])

    def test_display_merge_deduplicates_sources_and_fills_later_candidates(self) -> None:
        snapshot = parse_rime_context_payload(
            {
                "sessionId": "squirrel-dedupe",
                "requestSeq": 1,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "推荐", "comment": "rime"},
                        {"label": "2", "text": "让", "comment": "rime"},
                    ]
                },
            },
            default_project="wisdom-weasel-rag-ime",
        )
        display = merge_display_candidates(
            snapshot=snapshot,
            model_predictions=[
                ModelPrediction(text="推荐", rank=1, provider_name="model", latency_ms=8),
                ModelPrediction(text="推荐", rank=2, provider_name="model", latency_ms=8),
                ModelPrediction(text="生成", rank=3, provider_name="model", latency_ms=8),
            ],
            suggestions=[
                InputSuggestion(
                    suggestion_id="sug-1",
                    surface_text="重复句子",
                    suggestion_type="memory",
                    source_event_id=1,
                    evidence_preview="first",
                    confidence=0.9,
                ),
                InputSuggestion(
                    suggestion_id="sug-2",
                    surface_text="重复句子",
                    suggestion_type="memory",
                    source_event_id=2,
                    evidence_preview="duplicate",
                    confidence=0.8,
                ),
                InputSuggestion(
                    suggestion_id="sug-3",
                    surface_text="新的句子",
                    suggestion_type="memory",
                    source_event_id=3,
                    evidence_preview="new",
                    confidence=0.7,
                ),
            ],
        )

        self.assertEqual([item.text for item in display], ["推荐", "生成", "重复句子", "新的句子", "让"])
        self.assertEqual([item.source_type for item in display], ["model", "model", "rag", "rag", "rime"])

    def test_code_like_raw_input_gets_commit_candidate(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-raw-english",
                "requestSeq": 1,
                "rawInput": "model_prediction",
                "preedit": "model_prediction",
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {"candidates": []},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )

        self.assertEqual(response["queryBasis"], "rawSemanticInput")
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: semantic raw input")
        self.assertEqual(self.predictor.last_current_input, "model_prediction")
        first = response["displayCandidates"][0]
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "model_prediction")
        self.assertEqual(first["selectionAction"], "commit_side_candidate")

    def test_shell_command_raw_input_stays_first_candidate(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-shell-command",
                "requestSeq": 2,
                "rawInput": "git status",
                "preedit": "git status",
                "committedContext": "正在写 Codex 输入法调试记录",
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "给他", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        first = response["displayCandidates"][0]
        self.assertEqual(response["queryBasis"], "rawSemanticInput")
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: semantic raw input")
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "git status")
        self.assertEqual(first["selectionAction"], "commit_side_candidate")
        self.assertTrue(any(item["sourceType"] == "model" for item in response["displayCandidates"][1:]))

    def test_prediction_first_code_like_anchor_keeps_raw_commit_first(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-code",
                "requestSeq": 3,
                "rawInput": "model_prediction",
                "preedit": "model_prediction",
                "predictionFirstMerge": True,
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "某地", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        first = response["displayCandidates"][0]
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "model_prediction")
        self.assertEqual(response["predictionFirst"]["policy"]["rawCommitInserted"], 1)
        self.assertEqual(response["displayCandidates"][1]["sourceType"], "rime")

    def test_prediction_first_patched_frontend_keeps_raw_command_first_with_context(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-command",
                "requestSeq": 33,
                "rawInput": "git status",
                "preedit": "git status",
                "committedContext": "正在调试 Prediction-first RAG 输入法",
                "frontendBuild": "rag-ime.foreground-trace.v2",
                "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "给他", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        first = response["displayCandidates"][0]
        self.assertTrue(response["predictionFirst"]["enabled"])
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "git status")
        self.assertEqual(response["predictionFirst"]["policy"]["rawCommitInserted"], 1)
        self.assertTrue(any(item["sourceType"] == "model" for item in response["displayCandidates"][1:]))

    def test_short_technical_raw_input_refreshes_llm_and_rag_before_rime_noise(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-raw-rag",
                "requestSeq": 1,
                "rawInput": "rag",
                "preedit": "rag",
                "committedContext": "我正在做本地 RAG 输入法，需要根据历史输入预测候选。",
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "让", "comment": "rime"},
                        {"label": "2", "text": "人", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )

        display = response["displayCandidates"]
        self.assertEqual(response["queryBasis"], "rawSemanticInput")
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: semantic raw input")
        self.assertEqual(response["modelLane"]["predictionCount"], 8)
        self.assertEqual([item["sourceType"] for item in display[:5]], ["model"] * 5)
        self.assertEqual([item["sourceType"] for item in display[5:]], ["rag", "rag", "rag"])
        self.assertFalse(any(item["sourceType"] == "rime" for item in display))

    def test_plain_lowercase_pinyin_does_not_get_raw_english_candidate(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-plain-pinyin",
                "requestSeq": 1,
                "rawInput": "shuoyihenduoshihou",
                "preedit": "shuoyihenduoshihou",
                "maxVisibleCandidates": 8,
                "maxSideCandidates": 8,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "说一很多时候", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=self.predictor,
        )

        self.assertTrue(response["displayCandidates"])
        self.assertNotEqual(response["displayCandidates"][0]["sourceType"], "raw_english")

    def test_prediction_first_merge_prefix_keeps_llm_rag_before_wanxiang_fallback(self) -> None:
        core = PrefixSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-prefix",
                "requestSeq": 51,
                "rawInput": "sj",
                "preedit": "sj",
                "committedContext": "我想",
                "predictionFirstMerge": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "手机", "comment": "wanxiang"},
                        {"label": "2", "text": "世界", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=PrefixConstrainedPredictionProvider(),
        )

        self.assertTrue(response["predictionFirst"]["enabled"])
        self.assertEqual(response["predictionFirst"]["mode"], "prefix_constrained_composing")
        self.assertEqual(response["predictionFirst"]["pinyinPrefix"], "sj")
        display = response["displayCandidates"]
        self.assertEqual(
            [item["text"] for item in display],
            ["设计输入法状态机", "设计一个候选展示方式"],
        )
        self.assertEqual(
            [item["sourceType"] for item in display],
            ["model", "rag"],
        )
        self.assertEqual([item["displayLane"] for item in display], ["model", "memory"])
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 2)
        self.assertEqual(response["predictionFirst"]["policy"]["prefixMatchedSideInserted"], 2)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 0)
        self.assertTrue(response["predictionFirst"]["policy"]["rimeCompositionOwnedByRime"])
        self.assertEqual(response["predictionSession"]["phase"], "prefix_constrained")
        self.assertTrue(response["predictionSession"]["predictionPanelVisible"])
        self.assertFalse(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertEqual(response["predictionSession"]["selectionScope"], "mixed_prediction_first")

    def test_prediction_first_prefix_uses_compiled_memory_pinyin_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-prefix-memory-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            core.initialize()
            adapter = InputMethodAdapter(core)
            adapter.commit_text(
                "设计一个候选展示方式",
                recent_context="Prediction-first RAG IME 继续输入 sj 时约束个人历史短语",
                tags=("phrase-memory",),
            )
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-prediction-first-prefix-memory",
                    "requestSeq": 53,
                    "rawInput": "sj",
                    "preedit": "sj",
                    "committedContext": "我想",
                    "predictionFirstMerge": True,
                    "maxVisibleCandidates": 5,
                    "maxSideCandidates": 3,
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "手机", "comment": "wanxiang"},
                            {"label": "2", "text": "世界", "comment": "wanxiang"},
                        ]
                    },
                },
                adapter=adapter,
                core=core,
                predictor=PrefixConstrainedPredictionProvider(),
            )

        display = response["displayCandidates"]
        self.assertEqual(display[0]["text"], "设计输入法状态机")
        self.assertEqual(display[0]["sourceType"], "model")
        self.assertEqual(display[1]["text"], "设计一个候选展示方式")
        self.assertEqual(display[1]["sourceType"], "memory")
        self.assertEqual(display[1]["displayLane"], "memory")
        self.assertEqual(display[1]["metadata"]["initials"], "sjyghxzsfs")
        self.assertEqual([item["sourceType"] for item in display], ["model", "memory"])

    def test_prediction_first_prefix_without_match_returns_to_wanxiang_fallback(self) -> None:
        core = PrefixSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-prefix-no-match",
                "requestSeq": 55,
                "rawInput": "ni",
                "preedit": "ni",
                "committedContext": "我想",
                "predictionFirstMerge": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "你", "comment": "wanxiang"},
                        {"label": "2", "text": "呢", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=PrefixConstrainedPredictionProvider(),
        )

        self.assertEqual(response["predictionFirst"]["mode"], "prefix_constrained_composing")
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 0)
        self.assertEqual(response["predictionFirst"]["policy"]["prefixMatchedSideInserted"], 0)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 2)
        self.assertEqual([item["text"] for item in response["displayCandidates"]], ["你", "呢"])
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["rime", "rime"])
        self.assertFalse(response["predictionSession"]["predictionPanelVisible"])
        self.assertTrue(response["predictionSession"]["shouldClearPredictionPanel"])

    def test_prediction_first_prefix_does_not_turn_recent_context_into_memory_candidates(self) -> None:
        core = EmptySuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-recent-memory-prefix",
                "requestSeq": 54,
                "rawInput": "sj",
                "preedit": "sj",
                "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "手机", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=PrefixConstrainedPredictionProvider(),
        )

        display = response["displayCandidates"]
        self.assertGreater(response["predictionFirst"]["policy"]["prefixMatchedSideInserted"], 0)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 0)
        self.assertFalse(any(item["metadata"].get("fallback") == "recent_context" for item in display))
        self.assertEqual([item["sourceType"] for item in display], ["model"])
        self.assertNotIn("recentContextFallbackCount", response["ragLane"])

    def test_prediction_first_post_commit_uses_commit_preview_as_prediction_anchor(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-post-commit",
                "requestSeq": 52,
                "commitTextPreview": "我想",
                "committedContext": "用户刚刚上屏了 我想",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertTrue(response["predictionFirst"]["enabled"])
        self.assertEqual(response["predictionFirst"]["mode"], "post_commit_predicting")
        self.assertEqual(response["queryBasis"], "commitTextPreview")
        self.assertEqual(response["semanticQuery"], "我想")
        self.assertEqual(response["triggerDecision"]["reason"], "force: explicit side candidate refresh")
        self.assertEqual(predictor.last_current_input, "我想")
        self.assertEqual(core.last_suggest_recent_context, "用户刚刚上屏了 我想")
        self.assertEqual(response["modelPredictions"][0]["text"], "我想续写")
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["rag", "model"])
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 2)
        self.assertFalse(response["predictionFirst"]["policy"]["rimeCompositionOwnedByRime"])

    def test_prediction_first_post_commit_refreshes_without_idle_delay(self) -> None:
        core = EmptySuggestionCore()
        adapter = InputMethodAdapter(core)
        predictor = PrefixConstrainedPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-post-commit-fast",
                "requestSeq": 53,
                "frontendBuild": "rag-ime.foreground-trace.v2",
                "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
                "rawInput": "",
                "preedit": "",
                "idleMs": 80,
                "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
                "forceSideCandidates": False,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertTrue(response["predictionFirst"]["enabled"])
        self.assertEqual(response["predictionFirst"]["mode"], "post_commit_predicting")
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: post-commit continuation")
        self.assertFalse(response["predictionFirst"]["policy"]["rimeCompositionOwnedByRime"])
        self.assertGreater(response["predictionFirst"]["policy"]["sideInserted"], 0)
        self.assertTrue(response["predictionFirst"]["policy"]["candidatePoolActive"])
        self.assertFalse(response["predictionFirst"]["policy"]["candidatePoolReused"])
        self.assertFalse(any(item["sourceType"] == "rime" for item in response["displayCandidates"]))

    def test_prediction_first_post_commit_clears_stale_empty_panel(self) -> None:
        core = EmptySuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-prediction-first-post-commit-stale",
                "requestSeq": 54,
                "frontendBuild": "rag-ime.foreground-trace.v2",
                "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
                "rawInput": "",
                "preedit": "",
                "idleMs": 1500,
                "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=PrefixConstrainedPredictionProvider(),
        )

        self.assertEqual(response["triggerDecision"]["reason"], "skip: stale post-commit continuation")
        self.assertFalse(response["triggerDecision"]["shouldRefresh"])
        self.assertFalse(response["predictionFirst"]["policy"]["panelVisible"])
        self.assertTrue(response["predictionFirst"]["policy"]["hideWhenEmpty"])
        self.assertTrue(response["predictionFirst"]["policy"]["sessionBound"])
        self.assertEqual(response["predictionSession"]["phase"], "hidden")
        self.assertFalse(response["predictionSession"]["candidatePanelVisible"])
        self.assertFalse(response["predictionSession"]["predictionPanelVisible"])
        self.assertTrue(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertEqual(response["predictionSession"]["selectionScope"], "none")
        self.assertEqual(response["displayCandidates"], [])
        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["ragCandidates"], [])

    def test_prediction_first_stale_post_commit_drops_prior_manager_pool(self) -> None:
        core = EmptySuggestionCore()
        adapter = InputMethodAdapter(core)
        predictor = PrefixConstrainedPredictionProvider()
        session_id = "squirrel-prediction-first-stale-after-live"
        live_payload = {
            "sessionId": session_id,
            "requestSeq": 1,
            "frontendBuild": "rag-ime.foreground-trace.v2",
            "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
            "rawInput": "",
            "preedit": "",
            "idleMs": 80,
            "committedContext": "我想设计一个候选展示方式，做一个预测优先的 RAG 输入法",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 5,
            "rimeContext": {"candidates": []},
        }
        live = build_rime_sidecar_response(
            payload=live_payload,
            adapter=adapter,
            core=core,
            predictor=predictor,
        )
        self.assertEqual(live["predictionSession"]["phase"], "post_commit")
        self.assertTrue(live["predictionFirst"]["policy"]["candidatePoolActive"])

        stale = build_rime_sidecar_response(
            payload={**live_payload, "requestSeq": 2, "idleMs": 1500},
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertEqual(stale["triggerDecision"]["reason"], "skip: stale post-commit continuation")
        self.assertEqual(stale["predictionSession"]["phase"], "hidden")
        self.assertTrue(stale["predictionSession"]["shouldClearPredictionPanel"])
        self.assertEqual(stale["displayCandidates"], [])
        self.assertFalse(stale["predictionFirst"]["policy"]["candidatePoolActive"])
        self.assertFalse(stale["predictionFirst"]["policy"]["candidatePoolReused"])

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
        self.assertEqual(first["modelLane"]["skippedReason"], "error: timeout")
        self.assertEqual(second["modelLane"]["skippedReason"], "error: timeout")
        self.assertTrue(any(item["sourceType"] == "rag" for item in first["displayCandidates"]))
        self.assertTrue(any(item["sourceType"] == "rag" for item in second["displayCandidates"]))

    def test_busy_model_lane_reuses_short_model_holdover_for_horizontal_row(self) -> None:
        payload = {
            "sessionId": "squirrel-model-holdover-prime",
            "requestSeq": 1,
            "committedContext": "用户刚刚写完一段关于 RAG 输入法布局的中文上下文",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "forceSideCandidates": True,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                ]
            },
        }
        primed = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )
        self.assertTrue(primed["modelPredictions"])

        blocking_predictor = BlockingPredictionProvider()
        blocking_payload = {**payload, "sessionId": "squirrel-model-holdover-block", "requestSeq": 2}
        worker = Thread(
            target=build_rime_sidecar_response,
            kwargs={
                "payload": blocking_payload,
                "adapter": self.adapter,
                "core": self.core,
                "predictor": blocking_predictor,
            },
            daemon=True,
        )
        worker.start()
        self.assertTrue(blocking_predictor.entered.wait(timeout=2))
        try:
            busy_response = build_rime_sidecar_response(
                payload={**payload, "sessionId": "squirrel-model-holdover-busy", "requestSeq": 3},
                adapter=self.adapter,
                core=self.core,
                predictor=MultiPredictionProvider(),
            )
        finally:
            blocking_predictor.release.set()
            worker.join(timeout=2)

        self.assertTrue(busy_response["modelPredictions"])
        self.assertFalse(busy_response["modelLane"]["called"])
        self.assertTrue(busy_response["modelLane"]["holdoverHit"])
        self.assertIn("reused recent model holdover", busy_response["modelLane"]["skippedReason"])
        self.assertEqual(busy_response["displayCandidates"][0]["sourceType"], "model")
        self.assertEqual(busy_response["displayCandidates"][0]["displayLayout"], "inline")

    def test_busy_model_lane_does_not_reuse_holdover_after_prefix_changes(self) -> None:
        payload = {
            "sessionId": "squirrel-model-holdover-prefix-prime",
            "requestSeq": 1,
            "rawInput": "sj",
            "preedit": "sj",
            "committedContext": "用户刚刚写完一段关于 RAG 输入法布局的中文上下文",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "forceSideCandidates": True,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "设计输入法状态机", "comment": "rime"},
                ]
            },
        }
        primed = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )
        self.assertTrue(primed["modelPredictions"])

        blocking_predictor = BlockingPredictionProvider()
        worker = Thread(
            target=build_rime_sidecar_response,
            kwargs={
                "payload": {**payload, "sessionId": "squirrel-model-holdover-prefix-block", "requestSeq": 2},
                "adapter": self.adapter,
                "core": self.core,
                "predictor": blocking_predictor,
            },
            daemon=True,
        )
        worker.start()
        self.assertTrue(blocking_predictor.entered.wait(timeout=2))
        try:
            changed_prefix_response = build_rime_sidecar_response(
                payload={
                    **payload,
                    "sessionId": "squirrel-model-holdover-prefix-change",
                    "requestSeq": 3,
                    "rawInput": "sja",
                    "preedit": "sja",
                },
                adapter=self.adapter,
                core=self.core,
                predictor=MultiPredictionProvider(),
            )
        finally:
            blocking_predictor.release.set()
            worker.join(timeout=2)

        self.assertEqual(changed_prefix_response["modelPredictions"], [])
        self.assertFalse(changed_prefix_response["modelLane"]["holdoverHit"])
        self.assertEqual(changed_prefix_response["modelLane"]["skippedReason"], "model lane already running")

    def test_model_lane_timeout_reuses_holdover_for_horizontal_row(self) -> None:
        payload = {
            "sessionId": "squirrel-model-timeout-holdover-prime",
            "requestSeq": 1,
            "committedContext": "用户刚刚写完一段关于 RAG 输入法布局的中文上下文",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "forceSideCandidates": True,
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                ]
            },
        }
        primed = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=MultiPredictionProvider(),
        )
        self.assertTrue(primed["modelPredictions"])

        slow_predictor = SlowPredictionProvider(sleep_s=0.12)
        started = time.perf_counter()
        try:
            timeout_response = build_rime_sidecar_response(
                payload={
                    **payload,
                    "sessionId": "squirrel-model-timeout-holdover",
                    "requestSeq": 2,
                    "latencyBudgetMs": 30,
                },
                adapter=self.adapter,
                core=self.core,
                predictor=slow_predictor,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
        finally:
            self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=1.0))

        self.assertLess(elapsed_ms, 100)
        self.assertEqual(slow_predictor.calls, 1)
        self.assertTrue(timeout_response["modelPredictions"])
        self.assertTrue(timeout_response["modelLane"]["called"])
        self.assertTrue(timeout_response["modelLane"]["timedOut"])
        self.assertTrue(timeout_response["modelLane"]["holdoverHit"])
        self.assertIn("reused recent model holdover", timeout_response["modelLane"]["skippedReason"])
        self.assertEqual(timeout_response["displayCandidates"][0]["sourceType"], "model")
        self.assertEqual(timeout_response["displayCandidates"][0]["displayLayout"], "inline")

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
        self.assertIn("exceeded latency budget", response["modelLane"]["skippedReason"])
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
        self.assertIn("exceeded latency budget", response["ragLane"]["skippedReason"])
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

    def test_rag_display_text_is_compressed_and_insert_text_is_short_candidate(self) -> None:
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
        self.assertEqual(rag_item["insertText"], rag_item["text"])
        self.assertIn("背景说明这一句不是候选重点", rag_item["metadata"]["preview_text"])
        self.assertIn("背景说明这一句不是候选重点", rag_item["expandedEvidence"])

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

    def test_recent_context_fallback_cleans_repeated_noise_tail(self) -> None:
        suggestions = recent_context_memory_suggestions(
            recent_context="接入本地记忆 接入本地记忆 法 撒旦",
            current_input="",
            top_k=4,
        )
        texts = [item.surface_text for item in suggestions]
        self.assertEqual(texts, ["接入本地记忆"])

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

    def test_cli_rime_select_json_dry_run_does_not_write_database(self) -> None:
        payload = {
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
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-dry-run-") as tmp:
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
            self.assertTrue(response["dryRun"])
            self.assertEqual(response["eventId"], "")
            self.assertFalse(response["recordedAction"])
            with sqlite3.connect(db_path) as conn:
                has_events_table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'input_events'"
                ).fetchone()
                row = (
                    conn.execute(
                        "SELECT committed_text FROM input_events WHERE committed_text = ?",
                        ("doctor side candidate",),
                    ).fetchone()
                    if has_events_table
                    else None
                )
            self.assertIsNone(row)

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
