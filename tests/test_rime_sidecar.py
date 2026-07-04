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
from rag_ime.models import InputEvent, InputSuggestion, MemoryAction, ModelPrediction
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
    record_rime_side_candidate_selection,
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


class ContextEchoPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text="今天继续使用输入",
                rank=1,
                provider_name="echo-model",
                latency_ms=8,
                confidence=0.86,
            )
        ][:max_candidates]


class CleanPostCommitPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text="我们开始",
                rank=1,
                provider_name="clean-model",
                latency_ms=8,
                confidence=0.9,
            )
        ][:max_candidates]


class MetaPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text="你正在输入一个已经上屏的文本",
                rank=1,
                provider_name="meta-model",
                latency_ms=8,
                confidence=0.9,
            ),
            ModelPrediction(
                text="继续调整真实候选",
                rank=2,
                provider_name="meta-model",
                latency_ms=8,
                confidence=0.86,
            ),
        ][:max_candidates]


class EmptyPredictionProvider:
    def __init__(self) -> None:
        self.last_current_input = ""
        self.last_recent_context = ""

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.last_current_input = current_input
        self.last_recent_context = recent_context
        return []


class CapturingRequestPredictionProvider:
    def __init__(self) -> None:
        self.last_request_type = ""
        self.last_rime_candidates: tuple[str, ...] = ()
        self.last_current_input = ""
        self.last_recent_context = ""

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        max_candidates: int = 5,
        request_type: str = "",
        rime_candidates: tuple[str, ...] = (),
    ):
        self.last_current_input = current_input
        self.last_recent_context = recent_context
        self.last_request_type = request_type
        self.last_rime_candidates = rime_candidates
        return [
            ModelPrediction(
                text="设计一个候选展示方式",
                rank=1,
                provider_name="capture-model",
                latency_ms=6,
                confidence=0.91,
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


class OffPrefixPredictionProvider:
    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        return [
            ModelPrediction(
                text="写一篇关于智能语音助手的研究背景",
                rank=1,
                provider_name="qwen-mlx",
                latency_ms=12,
                confidence=0.82,
            ),
            ModelPrediction(
                text="帮我写一下研究背景和意义",
                rank=2,
                provider_name="qwen-mlx",
                latency_ms=12,
                confidence=0.78,
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


class EmptyPredictionProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.last_current_input = ""
        self.last_recent_context = ""

    def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
        self.calls += 1
        self.last_current_input = current_input
        self.last_recent_context = recent_context
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
        self.last_suggest_current_input = ""
        self.last_suggest_recent_context = ""
        self.last_suggest_app = ""

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
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


class ContextRepeatingCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="repeat:1",
                surface_text="RAG 输入法本地记忆",
                suggestion_type="rag_candidate",
                source_event_id=1,
                evidence_preview="same as current context",
                confidence=0.9,
                metadata={"tags": [], "state": {}},
            ),
            InputSuggestion(
                suggestion_id="repeat:2",
                surface_text="上下文窗口治理",
                suggestion_type="rag_candidate",
                source_event_id=2,
                evidence_preview="new memory",
                confidence=0.8,
                metadata={"tags": [], "state": {"accepted_count": 3}},
            ),
        ][:top_k]


class HistoryRepeatingCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="history:1",
                surface_text="历史输入会进入模型预测",
                suggestion_type="rag_candidate",
                source_event_id=1,
                evidence_preview="raw recent history echo",
                confidence=0.9,
                metadata={"tags": [], "state": {}},
            ),
            InputSuggestion(
                suggestion_id="history:2",
                surface_text="长期记忆候选保留",
                suggestion_type="rag_candidate",
                source_event_id=2,
                evidence_preview="durable memory",
                confidence=0.8,
                metadata={"tags": ["generated-memory"], "state": {}},
            ),
        ][:top_k]


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


class PostCommitSurfaceSuggestionCore(CapturingCore):
    def __init__(self, surface_text: str = "设计一个候选展示方式") -> None:
        super().__init__()
        self.surface_text = surface_text

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        self.last_suggest_app = app
        return [
            InputSuggestion(
                suggestion_id="post-commit:surface",
                surface_text=self.surface_text,
                suggestion_type="phrase",
                source_event_id=41,
                evidence_preview="用户之前写过这个可提交短语",
                confidence=0.92,
                metadata={
                    "source_type": "rag",
                    "insert_text": self.surface_text,
                    "reason": "test-post-commit-surface",
                },
            )
        ][:top_k]


class LongRawHistorySuggestionCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="sug-event:9001",
                surface_text="然后我还有个需求，就是目前我正在做另一个输入法，就是你也可以看到那个项目的具体要求。",
                suggestion_type="sentence",
                source_event_id=9001,
                evidence_preview="old raw input event",
                confidence=0.99,
                metadata={
                    "source_type": "rag",
                    "source_ref": "input_event:9001",
                    "state": {"project_input_frequency": 5, "effective_frequency": 5},
                },
            ),
            InputSuggestion(
                suggestion_id="phrase:1",
                surface_text="整理项目进度",
                suggestion_type="phrase",
                source_event_id=9002,
                evidence_preview="compiled short phrase",
                confidence=0.9,
                metadata={"source_type": "rag", "source_ref": "input_event:9002"},
            ),
            InputSuggestion(
                suggestion_id="sug-event:9003",
                surface_text="先不碰win，我正在配置",
                suggestion_type="phrase",
                source_event_id=9003,
                evidence_preview="short raw input event with punctuation",
                confidence=0.88,
                metadata={
                    "source_type": "rag",
                    "source_ref": "input_event:9003",
                    "state": {"project_input_frequency": 5, "effective_frequency": 5},
                },
            ),
        ][:top_k]


class ComplaintSuggestionCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="complaint:1",
                surface_text="不然这个输入法，和传统输入法没区别",
                suggestion_type="sentence",
                source_event_id=51,
                evidence_preview="old complaint",
                confidence=0.95,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="complaint:2",
                surface_text="我输入法切成豆包，就是因为你这个输入法没办法输入啊。",
                suggestion_type="sentence",
                source_event_id=52,
                evidence_preview="old complaint",
                confidence=0.94,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="complaint:3",
                surface_text="然后我的问题你没有记录呀。",
                suggestion_type="sentence",
                source_event_id=54,
                evidence_preview="old complaint",
                confidence=0.94,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="transition:1",
                surface_text="接下来",
                suggestion_type="phrase",
                source_event_id=56,
                evidence_preview="low value transition",
                confidence=0.93,
                metadata={"source_type": "memory"},
            ),
            InputSuggestion(
                suggestion_id="complaint:4",
                surface_text="需要真实生效",
                suggestion_type="phrase",
                source_event_id=59,
                evidence_preview="accepted user complaint",
                confidence=0.93,
                metadata={
                    "source_type": "rag",
                    "state": {
                        "accepted_count": 1,
                        "rawSignals": {"acceptedCount": 1},
                    },
                },
            ),
            InputSuggestion(
                suggestion_id="meta:1",
                surface_text="你正在输入一个已经上屏的文本",
                suggestion_type="phrase",
                source_event_id=57,
                evidence_preview="model meta output stored by mistake",
                confidence=0.92,
                metadata={"source_type": "memory"},
            ),
            InputSuggestion(
                suggestion_id="meta:2",
                surface_text="你正在看Felix的3322号项目吗",
                suggestion_type="phrase",
                source_event_id=58,
                evidence_preview="model meta output stored by mistake",
                confidence=0.92,
                metadata={"source_type": "memory"},
            ),
            InputSuggestion(
                suggestion_id="clean:1",
                surface_text="候选应该预测用户接下来想表达的短语",
                suggestion_type="phrase",
                source_event_id=55,
                evidence_preview="clean memory",
                confidence=0.9,
                metadata={"source_type": "memory"},
            ),
        ][:top_k]


class AcceptedPostCommitSuggestionCore(PostCommitSurfaceSuggestionCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        suggestions = super().suggest_for_input(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=top_k,
        )
        return [
            InputSuggestion(
                suggestion_id=item.suggestion_id,
                surface_text=item.surface_text,
                suggestion_type=item.suggestion_type,
                source_event_id=item.source_event_id,
                evidence_preview=item.evidence_preview,
                confidence=item.confidence,
                metadata={
                    **dict(item.metadata),
                    "state": {"accepted_count": 1, "input_frequency": 1},
                },
            )
            for item in suggestions
        ]


class GeneratedAcceptedSuggestionCore(CapturingCore):
    def __init__(self, *, accepted_count: int) -> None:
        super().__init__()
        self.accepted_count = accepted_count

    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="generated:model-once",
                surface_text="接入真实记忆候选",
                suggestion_type="phrase",
                source_event_id=61,
                evidence_preview="generated model candidate selected from sidecar",
                confidence=0.94,
                metadata={
                    "source_type": "rag",
                    "tags": ["squirrel", "rime-sidecar", "sidecar-selected", "source:model"],
                    "state": {
                        "accepted_count": self.accepted_count,
                        "event_accepted_count": self.accepted_count,
                        "input_frequency": self.accepted_count,
                        "effective_frequency": self.accepted_count,
                        "rawSignals": {
                            "acceptedCount": self.accepted_count,
                            "inputFrequency": self.accepted_count,
                            "effectiveFrequency": self.accepted_count,
                        },
                    },
                },
            )
        ][:top_k]


class DirtySuggestionCore(CapturingCore):
    def suggest_for_input(self, *, current_input: str, recent_context: str = "", project: str = "", app: str = "", top_k: int = 5):
        self.last_suggest_current_input = current_input
        self.last_suggest_recent_context = recent_context
        return [
            InputSuggestion(
                suggestion_id="dirty:prompt",
                surface_text="接入本地记忆",
                suggestion_type="phrase",
                source_event_id=1,
                evidence_preview="old prompt example leak",
                confidence=0.99,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="dirty:uuid",
                surface_text="019f1228-34de-74b3-a627-c546f091e87e这个会话，继续调试",
                suggestion_type="sentence",
                source_event_id=2,
                evidence_preview="session id should not be an IME candidate",
                confidence=0.98,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="dirty:assistant-history",
                surface_text="但即便无意义串，也不应该被 Rime 泛词占满。",
                suggestion_type="paragraph",
                source_event_id=4,
                evidence_preview="[445] assistant: 模型本身对“阿斯顿…”这种无语义测试串只会复读泛词。",
                confidence=0.97,
                metadata={"source_type": "rag"},
            ),
            InputSuggestion(
                suggestion_id="clean:1",
                surface_text="候选应该预测用户接下来想表达的短语",
                suggestion_type="sentence",
                source_event_id=3,
                evidence_preview="clean memory",
                confidence=0.9,
                metadata={"source_type": "memory"},
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

    def test_model_lane_receives_pinyin_constrained_request_context(self) -> None:
        predictor = CapturingRequestPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-request-type",
                "requestSeq": 46,
                "rawInput": "sj",
                "preedit": "sj",
                "committedContext": "我想",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 4,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "设计", "comment": "rime"},
                        {"label": "2", "text": "手机", "comment": "rime"},
                    ]
                },
            },
            adapter=self.adapter,
            core=self.core,
            predictor=predictor,
        )

        self.assertEqual(predictor.last_request_type, "pinyin_constrained_prediction")
        self.assertEqual(predictor.last_current_input, "sj")
        self.assertEqual(predictor.last_recent_context, "我想")
        self.assertEqual(predictor.last_rime_candidates, ("设计", "手机"))
        self.assertEqual(response["modelLane"]["contextMode"], "explicit-pinyin-constrained")
        self.assertEqual(response["modelLane"]["requestType"], "pinyin_constrained_prediction")
        self.assertEqual(response["modelLane"]["rimeCandidateCount"], 2)
        self.assertEqual(response["ragLane"]["queryInput"], "sj")

    def test_low_information_rime_candidates_skip_side_lanes_even_when_forced(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = CapturingRequestPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-low-info-rime",
                "requestSeq": 462,
                "rawInput": "de",
                "preedit": "de",
                "committedContext": "预测感觉随机，无 LLM",
                "forceSideCandidates": True,
                "predictionFirstMerge": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 6,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "的", "comment": "wanxiang"},
                        {"label": "2", "text": "得", "comment": "wanxiang"},
                        {"label": "3", "text": "地", "comment": "wanxiang"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertEqual(response["queryBasis"], "rimeCandidates")
        self.assertEqual(response["triggerDecision"]["reason"], "skip: low-information Rime candidates")
        self.assertFalse(response["triggerDecision"]["shouldRefresh"])
        self.assertFalse(response["ragLane"]["called"])
        self.assertFalse(response["modelLane"]["called"])
        self.assertEqual(core.last_suggest_current_input, "")
        self.assertEqual(predictor.last_current_input, "")
        self.assertEqual([item["text"] for item in response["displayCandidates"]], ["得", "地"])
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["rime", "rime"])
        self.assertFalse(response["predictionFirst"]["policy"]["candidatePoolActive"])

    def test_rag_prompt_leaks_and_session_ids_are_filtered_from_display(self) -> None:
        core = DirtySuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-dirty-rag-filter",
                "requestSeq": 463,
                "commitTextPreview": "输入法预测",
                "committedContext": "这个输入法预测感觉随机，需要真实候选",
                "forceSideCandidates": True,
                "predictionFirstMerge": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 6,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        self.assertEqual(response["ragLane"]["filteredSuggestionCount"], 3)
        self.assertEqual([item["surfaceText"] for item in response["ragCandidates"]], ["候选应该预测用户接下来想表达的短语"])
        display_texts = [item["text"] for item in response["displayCandidates"]]
        self.assertIn("候选应该预测用户接下来想表达的短语", display_texts)
        self.assertNotIn("019f1228-34de-74b3-a627-c546f091e87e这个会话，继续调试", display_texts)
        self.assertNotIn("接入本地记忆", display_texts)
        self.assertNotIn("但即便无意义串，也不应该被 Rime 泛词占满。", display_texts)

    def test_post_commit_model_lane_uses_clean_screen_context_not_history_wrapper(self) -> None:
        predictor = CapturingRequestPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-model-context",
                "requestSeq": 461,
                "rawInput": "",
                "preedit": "",
                "commitTextPreview": "输入法什么时候可以",
                "committedContext": "你好，输入法什么时候可以完成改正。现在候选词不像 LLM 输出。",
                "forceSideCandidates": True,
                "latencyBudgetMs": 650,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 4,
                "rimeContext": {"candidates": []},
            },
            adapter=self.adapter,
            core=self.core,
            predictor=predictor,
        )

        self.assertEqual(predictor.last_request_type, "no_input_prediction")
        self.assertEqual(predictor.last_current_input, "输入法什么时候可以")
        self.assertEqual(predictor.last_recent_context, "你好，输入法什么时候可以完成改正。现在候选词不像 LLM 输出。")
        self.assertNotIn("历史参考", predictor.last_recent_context)
        self.assertEqual(response["modelLane"]["contextMode"], "explicit-post-commit")
        self.assertEqual(response["modelLane"]["predictionCount"], 1)

    def test_model_lane_filters_off_prefix_pinyin_predictions(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-off-prefix-model",
                "requestSeq": 47,
                "rawInput": "sj",
                "preedit": "sj",
                "committedContext": "我想",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "手机", "comment": "rime"},
                        {"label": "2", "text": "世界", "comment": "rime"},
                    ]
                },
            },
            adapter=InputMethodAdapter(EmptySuggestionCore()),
            core=EmptySuggestionCore(),
            predictor=OffPrefixPredictionProvider(),
        )

        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["modelLane"]["predictionCount"], 0)
        self.assertEqual(response["modelLane"]["skippedReason"], "model predictions did not match pinyin prefix")
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["rime", "rime"])

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
        self.assertGreaterEqual(len(rag_items), 3)
        self.assertFalse(rime_items)
        self.assertTrue(all(item["displayLayout"] == "inline" for item in model_items))
        self.assertTrue(all(item["displayLane"] == "model" for item in model_items))
        self.assertTrue(all(item["displayLayout"] == "block" for item in rag_items))
        self.assertTrue(all(item["displayLane"] == "memory" for item in rag_items))
        self.assertEqual(response["mergePolicy"]["fallbackOrder"], ["model", "rag", "rime"])
        self.assertEqual(response["modelLane"]["requestedMaxCandidates"], 5)

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
                "latencyBudgetMs": 800,
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

        self.assertEqual(predictor.last_recent_context, "当前正在写 RAG 输入法 sidecar")
        self.assertEqual(core.last_suggest_recent_context, "当前正在写 RAG 输入法 sidecar")
        self.assertNotIn("历史输入会进入模型预测", core.last_suggest_recent_context)
        self.assertEqual(response["historyContext"], predictor.last_recent_context)
        history_meta = response["historyContextMeta"]
        self.assertEqual(history_meta["chars"], len(predictor.last_recent_context))
        self.assertEqual(len(history_meta["fingerprint"]), 16)
        self.assertFalse(history_meta["hasHistory"])
        self.assertTrue(history_meta["hasExplicitContext"])
        self.assertEqual(response["modelLane"]["contextMode"], "explicit-post-commit")

    def test_model_predictions_repeating_history_context_are_filtered(self) -> None:
        class RepeatingHistoryPredictionProvider:
            def __init__(self) -> None:
                self.last_recent_context = ""

            def predict(self, *, current_input: str, recent_context: str = "", max_candidates: int = 5):
                self.last_recent_context = recent_context
                return [
                    ModelPrediction(text="当前正在写 RAG 输入法 sidecar", rank=1, provider_name="local-mlx", latency_ms=10),
                    ModelPrediction(text="把输入法流程跑通", rank=2, provider_name="local-mlx", latency_ms=10),
                    ModelPrediction(text="已上屏上下文: 当前正在写", rank=3, provider_name="local-mlx", latency_ms=10),
                ][:max_candidates]

        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = RepeatingHistoryPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-filter-stale-history",
                "requestSeq": 45,
                "committedContext": "当前正在写 RAG 输入法 sidecar",
                "latencyBudgetMs": 800,
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": [{"label": "1", "text": "RAG 输入法", "comment": "rime"}]},
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertEqual(predictor.last_recent_context, "当前正在写 RAG 输入法 sidecar")
        self.assertEqual([item["text"] for item in response["modelPredictions"]], ["把输入法流程跑通"])

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
                "latencyBudgetMs": 800,
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

    def test_rag_candidates_do_not_repeat_current_committed_context(self) -> None:
        core = ContextRepeatingCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-rag-repeat-current-context",
                "requestSeq": 47,
                "committedContext": "RAG 输入法本地记忆",
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 3,
                "latencyBudgetMs": 800,
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        rag_surfaces = [item["surfaceText"] for item in response["ragCandidates"]]
        display_surfaces = [item["text"] for item in response["displayCandidates"]]
        self.assertNotIn("RAG 输入法本地记忆", rag_surfaces)
        self.assertNotIn("RAG 输入法本地记忆", display_surfaces)
        self.assertIn("上下文窗口治理", rag_surfaces)
        self.assertEqual(response["ragLane"]["filteredSuggestionCount"], 1)

    def test_rag_candidates_do_not_echo_model_history_reference_without_durable_signal(self) -> None:
        core = HistoryRepeatingCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-rag-repeat-history-context",
                "requestSeq": 48,
                "rawInput": "rag",
                "preedit": "rag",
                "maxVisibleCandidates": 4,
                "maxSideCandidates": 3,
                "latencyBudgetMs": 800,
                "rimeContext": {
                    "candidates": [
                        {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                    ]
                },
            },
            adapter=adapter,
            core=core,
            predictor=FakePredictionProvider(),
        )

        rag_surfaces = [item["surfaceText"] for item in response["ragCandidates"]]
        self.assertNotIn("历史输入会进入模型预测", rag_surfaces)
        self.assertIn("长期记忆候选保留", rag_surfaces)
        self.assertEqual(response["ragLane"]["filteredSuggestionCount"], 1)
        self.assertIn("历史参考", response["historyContext"])

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
        self.assertEqual([item["sourceType"] for item in side_items], ["model", "model", "rag"])
        self.assertEqual(side_items[0]["displayLayout"], "inline")
        self.assertEqual(side_items[1]["displayLayout"], "inline")
        self.assertEqual(side_items[2]["displayLayout"], "block")
        self.assertEqual(len(response["modelPredictions"]), 3)
        self.assertEqual(response["modelLane"]["requestedMaxCandidates"], 3)

    def test_eight_slot_panel_uses_horizontal_model_lane_and_vertical_memory_rows(self) -> None:
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-mixed-layout",
                "requestSeq": 11,
                "rawInput": "erqi",
                "preedit": "erqi",
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
        self.assertEqual(
            [item["sourceType"] for item in display],
            ["model", "model", "rag", "model", "model", "rime", "rime", "rime"],
        )
        self.assertEqual([item["displayLayout"] for item in display[:5]], ["inline", "inline", "block", "inline", "inline"])
        self.assertEqual([item["displayLane"] for item in display[:5]], ["model", "model", "memory", "model", "model"])
        self.assertTrue(all(item["displayLayout"] == "fallback" for item in display[5:8]))
        self.assertTrue(all(item["displayLane"] == "rime" for item in display[5:8]))
        self.assertEqual(response["mergePolicy"]["ragBlockReserve"], 3)
        self.assertTrue(response["mergePolicy"]["ragKeepsRemainingSideSlots"])
        self.assertEqual(response["modelLane"]["requestedMaxCandidates"], 5)

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
        self.assertEqual(response["triggerDecision"]["reason"], "skip: raw ascii passthrough")
        self.assertEqual(self.predictor.last_current_input, "")
        first = response["displayCandidates"][0]
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "model_prediction")
        self.assertEqual(first["selectionAction"], "commit_side_candidate")
        self.assertEqual(len(response["displayCandidates"]), 1)

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
        self.assertEqual(response["triggerDecision"]["reason"], "skip: raw ascii passthrough")
        self.assertEqual(first["sourceType"], "raw_english")
        self.assertEqual(first["insertText"], "git status")
        self.assertEqual(first["selectionAction"], "commit_side_candidate")
        self.assertEqual(len(response["displayCandidates"]), 1)

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
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 0)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 0)
        self.assertEqual(len(response["displayCandidates"]), 1)
        self.assertEqual(response["predictionSession"]["phase"], "raw_passthrough")

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
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 0)
        self.assertEqual(len(response["displayCandidates"]), 1)
        self.assertEqual(response["predictionSession"]["phase"], "raw_passthrough")

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
        self.assertEqual(response["modelLane"]["predictionCount"], 5)
        self.assertEqual(response["modelLane"]["requestedMaxCandidates"], 5)
        self.assertEqual([item["sourceType"] for item in display[:6]], ["model", "model", "rag", "model", "model", "model"])
        rag_count = sum(1 for item in display if item["sourceType"] == "rag")
        self.assertGreaterEqual(rag_count, 1)
        self.assertEqual([item["sourceType"] for item in display[-2:]], ["rime", "rime"])

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
            ["设计输入法状态机", "设计一个候选展示方式", "手机", "世界"],
        )
        self.assertEqual(
            [item["sourceType"] for item in display],
            ["model", "rag", "rime", "rime"],
        )
        self.assertEqual([item["displayLane"] for item in display], ["model", "memory", "wanxiang", "wanxiang"])
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 2)
        self.assertEqual(response["predictionFirst"]["policy"]["prefixMatchedSideInserted"], 2)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 2)
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangReserve"], 2)
        self.assertTrue(response["predictionFirst"]["policy"]["rimeCompositionOwnedByRime"])
        self.assertEqual(response["predictionSession"]["phase"], "prefix_constrained")
        self.assertTrue(response["predictionSession"]["predictionPanelVisible"])
        self.assertFalse(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertEqual(response["predictionSession"]["selectionScope"], "mixed_prediction_first")
        self.assertEqual(response["predictionSession"]["expiresAfterMs"], 2600)

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
        self.assertEqual([item["sourceType"] for item in display], ["model", "memory", "rime", "rime"])
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 2)

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
        self.assertEqual(response["predictionFirst"]["policy"]["wanxiangFallbackCount"], 1)
        self.assertFalse(any(item["metadata"].get("fallback") == "recent_context" for item in display))
        self.assertEqual([item["sourceType"] for item in display], ["model", "rime"])
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
        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["model"])
        self.assertEqual(response["predictionFirst"]["policy"]["sideInserted"], 1)
        self.assertEqual(response["ragLane"]["postCommitQualityFilteredCount"], 1)
        self.assertFalse(response["predictionFirst"]["policy"]["rimeCompositionOwnedByRime"])

    def test_prediction_first_post_commit_filters_weak_rag_when_model_exists(self) -> None:
        core = PostCommitSurfaceSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-weak-rag",
                "requestSeq": 58,
                "committedContext": "今天我们继续调输入法",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        self.assertEqual([item["sourceType"] for item in response["displayCandidates"]], ["model"])
        self.assertEqual(response["ragCandidates"], [])
        self.assertEqual(response["ragLane"]["postCommitQualityFilteredCount"], 1)

    def test_prediction_first_filters_meta_model_descriptions(self) -> None:
        core = PostCommitSurfaceSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-meta-model",
                "requestSeq": 61,
                "committedContext": "我输入依旧没有 LLM 和 RAG",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=MetaPredictionProvider(),
        )

        display_texts = [item["text"] for item in response["displayCandidates"]]
        self.assertIn("继续调整真实候选", display_texts)
        self.assertNotIn("你正在输入一个已经上屏的文本", display_texts)

    def test_prediction_first_filters_old_complaint_fragments_from_rag(self) -> None:
        core = ComplaintSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-complaint-rag",
                "requestSeq": 62,
                "commitTextPreview": "输入法预测",
                "committedContext": "这个输入法预测感觉随机，需要真实候选",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 6,
                "maxSideCandidates": 6,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        display_texts = [item["text"] for item in response["displayCandidates"]]
        self.assertIn("候选应该预测用户接下来想表达的短语", display_texts)
        self.assertNotIn("不然这个输入法，和传统输入法没区别", display_texts)
        self.assertNotIn("我输入法切成豆包，就是因为你这个输入法没办法输入啊。", display_texts)
        self.assertNotIn("然后我的问题你没有记录呀。", display_texts)
        self.assertNotIn("接下来", display_texts)
        self.assertNotIn("需要真实生效", display_texts)
        self.assertNotIn("你正在输入一个已经上屏的文本", display_texts)
        self.assertNotIn("你正在看Felix的3322号项目吗", display_texts)

    def test_prediction_first_post_commit_keeps_semantically_matched_rag(self) -> None:
        core = PostCommitSurfaceSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-strong-rag",
                "requestSeq": 59,
                "committedContext": "我想设计一个候选展示方式",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        self.assertIn("rag", [item["sourceType"] for item in response["displayCandidates"]])
        self.assertEqual(response["ragCandidates"][0]["surfaceText"], "设计一个候选展示方式")

    def test_prediction_first_filters_long_uncompiled_raw_history_from_rag(self) -> None:
        core = LongRawHistorySuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-long-raw-history",
                "requestSeq": 65,
                "committedContext": "我正在整理项目文档，包括进度和问题",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=CleanPostCommitPredictionProvider(),
        )

        display_texts = [item["text"] for item in response["displayCandidates"]]
        self.assertNotIn("然后我还有个需求，就是目前我正在做另一个输入法，就是你也可以看到那个项目的具体要求。", display_texts)
        self.assertNotIn("先不碰win，我正在配置", display_texts)
        self.assertIn("整理项目进度", display_texts)
        self.assertEqual(response["ragLane"]["filteredSuggestionCount"], 2)

    def test_prediction_first_post_commit_keeps_accepted_memory_even_without_overlap(self) -> None:
        core = AcceptedPostCommitSuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-accepted-memory",
                "requestSeq": 60,
                "committedContext": "今天我们继续调输入法",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=FakePredictionProvider(),
        )

        self.assertIn("rag", [item["sourceType"] for item in response["displayCandidates"]])
        self.assertEqual(response["ragCandidates"][0]["surfaceText"], "设计一个候选展示方式")

    def test_prediction_first_post_commit_filters_once_accepted_generated_side_memory(self) -> None:
        core = GeneratedAcceptedSuggestionCore(accepted_count=1)
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-generated-once",
                "requestSeq": 63,
                "committedContext": "Felix3322 Wisdom-Weasel 的输入法候选实现需要参考",
                "commitTextPreview": "参考 Wisdom-Weasel",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=FakePredictionProvider(),
        )

        self.assertEqual(response["ragCandidates"], [])
        self.assertNotIn("接入真实记忆候选", [item["text"] for item in response["displayCandidates"]])

    def test_prediction_first_post_commit_keeps_repeated_generated_side_memory(self) -> None:
        core = GeneratedAcceptedSuggestionCore(accepted_count=3)
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-generated-repeated",
                "requestSeq": 64,
                "committedContext": "Felix3322 Wisdom-Weasel 的输入法候选实现需要参考",
                "commitTextPreview": "参考 Wisdom-Weasel",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=FakePredictionProvider(),
        )

        self.assertIn("接入真实记忆候选", [item["text"] for item in response["displayCandidates"]])
        self.assertEqual(response["ragCandidates"][0]["surfaceText"], "接入真实记忆候选")

    def test_prediction_first_post_commit_filters_context_echo_model_prediction(self) -> None:
        core = EmptySuggestionCore()
        adapter = InputMethodAdapter(core)
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-post-commit-echo-model",
                "requestSeq": 61,
                "committedContext": "今天我们继续调输入法",
                "predictionFirstMerge": True,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 3,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=ContextEchoPredictionProvider(),
        )

        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["modelLane"]["filteredPredictionCount"], 1)
        self.assertEqual(response["displayCandidates"], [])
        self.assertEqual(response["predictionSession"]["phase"], "hidden")

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
        session_fingerprint = response["predictionSession"]["sessionFingerprint"]
        self.assertEqual(len(session_fingerprint), 16)
        self.assertEqual(response["predictionSession"]["requestSeq"], 53)
        self.assertEqual(response["predictionSession"]["expiresAfterMs"], 8000)
        self.assertEqual(response["predictionFirst"]["policy"]["candidatePoolSessionFingerprint"], session_fingerprint)
        for item in response["displayCandidates"]:
            self.assertEqual(item["metadata"]["sessionFingerprint"], session_fingerprint)
            self.assertEqual(item["metadata"]["requestSeq"], 53)

    def test_prediction_first_short_committed_context_skips_even_when_forced(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-short-post-commit",
                "requestSeq": 531,
                "frontendBuild": "rag-ime.foreground-trace.v2",
                "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
                "rawInput": "",
                "preedit": "",
                "idleMs": 80,
                "committedContext": "阿斯顿",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertEqual(response["queryBasis"], "committedContext")
        self.assertEqual(response["triggerDecision"]["reason"], "skip: low-information committed context")
        self.assertFalse(response["triggerDecision"]["shouldRefresh"])
        self.assertFalse(response["ragLane"]["called"])
        self.assertFalse(response["modelLane"]["called"])
        self.assertEqual(response["displayCandidates"], [])
        self.assertEqual(predictor.last_current_input, "")
        self.assertEqual(core.last_suggest_current_input, "")
        self.assertEqual(response["predictionSession"]["phase"], "hidden")
        self.assertTrue(response["predictionSession"]["shouldClearPredictionPanel"])

    def test_prediction_first_post_commit_suppresses_rag_only_when_model_empty(self) -> None:
        core = CapturingCore()
        adapter = InputMethodAdapter(core)
        predictor = EmptyPredictionProvider()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-rag-only-post-commit",
                "requestSeq": 532,
                "frontendBuild": "rag-ime.foreground-trace.v2",
                "schemaVersion": "rag-ime.squirrel-frontend-trace.v1",
                "rawInput": "",
                "preedit": "",
                "idleMs": 80,
                "committedContext": "阿斯顿 但即便无意义串，也不应该被 Rime 泛词占满。 撒旦 继续 现在用不了",
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 5,
                "rimeContext": {"candidates": []},
            },
            adapter=adapter,
            core=core,
            predictor=predictor,
        )

        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["ragCandidates"], [])
        self.assertEqual(response["ragLane"]["postCommitQualityFilteredCount"], 1)
        self.assertEqual(response["displayCandidates"], [])
        self.assertEqual(response["predictionSession"]["phase"], "hidden")
        self.assertTrue(response["predictionSession"]["shouldClearPredictionPanel"])
        self.assertEqual(predictor.last_current_input, response["semanticQuery"])
        self.assertEqual(core.last_suggest_current_input, response["semanticQuery"])

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
                "idleMs": 9000,
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
            payload={**live_payload, "requestSeq": 2, "idleMs": 9000},
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
            predictor=PrefixConstrainedPredictionProvider(),
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

    def test_busy_model_lane_does_not_reuse_nearby_post_commit_holdover_after_context_extension(self) -> None:
        payload = {
            "sessionId": "squirrel-model-holdover-context-prime",
            "requestSeq": 1,
            "committedContext": "我们正在修输入法候选真实生效",
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "forceSideCandidates": True,
            "rimeContext": {"candidates": []},
        }
        primed = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=CapturingRequestPredictionProvider(),
        )
        self.assertEqual(primed["modelPredictions"][0]["text"], "设计一个候选展示方式")

        blocking_predictor = BlockingPredictionProvider()
        worker = Thread(
            target=build_rime_sidecar_response,
            kwargs={
                "payload": {**payload, "sessionId": "squirrel-model-holdover-context-block", "requestSeq": 2},
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
                payload={
                    **payload,
                    "sessionId": "squirrel-model-holdover-context-extended",
                    "requestSeq": 3,
                    "committedContext": "我们正在修输入法候选真实生效以及记忆",
                },
                adapter=self.adapter,
                core=self.core,
                predictor=MultiPredictionProvider(),
            )
        finally:
            blocking_predictor.release.set()
            worker.join(timeout=2)

        self.assertEqual(busy_response["modelPredictions"], [])
        self.assertFalse(busy_response["modelLane"]["holdoverHit"])
        self.assertIn("model lane already running", busy_response["modelLane"]["skippedReason"])
        self.assertFalse(any(item["sourceType"] == "model" for item in busy_response["displayCandidates"]))

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
                    {"label": "1", "text": "手机", "comment": "rime"},
                ]
            },
        }
        primed = build_rime_sidecar_response(
            payload=payload,
            adapter=self.adapter,
            core=self.core,
            predictor=PrefixConstrainedPredictionProvider(),
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

    def test_progressive_response_returns_rag_before_slow_model_then_followup_uses_holdover(self) -> None:
        slow_predictor = SlowPredictionProvider(sleep_s=0.28)
        payload = {
            "sessionId": "squirrel-progressive-rag-first",
            "requestSeq": 88,
            "latencyBudgetMs": 1200,
            "forceSideCandidates": True,
            "maxVisibleCandidates": 5,
            "maxSideCandidates": 3,
            "committedContext": "我看是能 LLM 和 RAG 输出，就是展示不好，可以一个一个蹦出来",
            "rimeContext": {
                "candidates": [
                    {"label": "1", "text": "RAG 输入法", "comment": "rime"},
                ]
            },
        }
        with patch.dict("os.environ", {"RAG_IME_PROGRESSIVE_FIRST_RESPONSE_MS": "120"}):
            started = time.perf_counter()
            response = build_rime_sidecar_response(
                payload=payload,
                adapter=self.adapter,
                core=self.core,
                predictor=slow_predictor,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)

        self.assertLess(elapsed_ms, 900)
        self.assertTrue(any(item["sourceType"] == "rag" for item in response["displayCandidates"]))
        self.assertEqual(response["modelPredictions"], [])
        self.assertTrue(response["progressive"]["enabled"])
        self.assertTrue(response["progressive"]["partial"])
        self.assertTrue(response["progressive"]["shouldFollowUp"])
        self.assertIn("model", response["progressive"]["pendingLanes"])
        self.assertEqual(response["modelLane"]["skippedReason"], "model lane pending after progressive first response")

        self.assertTrue(wait_for_model_prediction_lane_idle(timeout_s=1.0))
        with patch.dict("os.environ", {"RAG_IME_PROGRESSIVE_FIRST_RESPONSE_MS": "120"}):
            followup = build_rime_sidecar_response(
                payload={**payload, "requestSeq": 89},
                adapter=self.adapter,
                core=self.core,
                predictor=slow_predictor,
            )

        self.assertTrue(followup["modelPredictions"])
        self.assertFalse(followup["progressive"]["shouldFollowUp"])
        self.assertEqual(followup["displayCandidates"][0]["sourceType"], "model")

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
                    "forceSideCandidates": True,
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

    def test_realtime_model_lane_uses_explicit_context_without_waiting_for_slow_history(self) -> None:
        core = SlowHistoryCore(sleep_s=0.12)
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        started = time.perf_counter()
        try:
            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-slow-history",
                    "requestSeq": 79,
                    "latencyBudgetMs": 300,
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
        self.assertEqual(predictor.last_current_input, "RAG 输入法")
        self.assertTrue(response["modelLane"]["called"])
        self.assertFalse(response["modelLane"]["timedOut"])
        self.assertEqual(response["modelLane"]["contextMode"], "explicit-realtime")
        self.assertEqual(predictor.last_recent_context, "")
        self.assertTrue(response["modelPredictions"])
        self.assertTrue(any(item["sourceType"] == "model" for item in response["displayCandidates"]))

    def test_realtime_rag_lane_keeps_mid_budget_memory_candidates(self) -> None:
        core = SlowSuggestionCore(sleep_s=0.15)
        adapter = InputMethodAdapter(core)
        predictor = FakePredictionProvider()
        started = time.perf_counter()
        response = build_rime_sidecar_response(
            payload={
                "sessionId": "squirrel-mid-budget-rag",
                "requestSeq": 80,
                "latencyBudgetMs": 350,
                "forceSideCandidates": True,
                "maxVisibleCandidates": 5,
                "maxSideCandidates": 2,
                "committedContext": "我想做一个本地记忆 RAG 输入法",
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

        self.assertLess(elapsed_ms, 350)
        self.assertEqual(core.calls, 1)
        self.assertTrue(response["ragLane"]["called"])
        self.assertFalse(response["ragLane"]["timedOut"])
        self.assertGreaterEqual(response["ragLane"]["latencyBudgetMs"], 300)
        self.assertTrue(any(item["sourceType"] == "rag" for item in response["displayCandidates"]))
        self.assertTrue(any(item["sourceType"] == "model" for item in response["displayCandidates"]))

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

    def test_rag_display_candidate_exposes_alpha_style_score_breakdown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-sidecar-score-") as tmp:
            core = LocalSqliteCoreClient(f"{tmp}/rag-ime.sqlite")
            core.initialize()
            adapter = InputMethodAdapter(core)
            memory_id = adapter.commit_text(
                "设计一个候选展示方式",
                recent_context="Prediction-first RAG IME 需要解释候选排序",
                project="wisdom-weasel-rag-ime",
                tags=("rag", "memory"),
            )
            adapter.commit_text(
                "普通候选展示",
                recent_context="无关输入法调试",
                project="wisdom-weasel-rag-ime",
            )
            core.apply_action(
                MemoryAction(
                    action_id=None,
                    created_at_ms=0,
                    memory_id=memory_id,
                    action_type="accepted",
                    query="候选展示方式",
                )
            )

            response = build_rime_sidecar_response(
                payload={
                    "sessionId": "squirrel-score-breakdown",
                    "requestSeq": 102,
                    "maxVisibleCandidates": 4,
                    "maxSideCandidates": 2,
                    "forceSideCandidates": True,
                    "committedContext": "我想设计一个",
                    "preedit": "zs",
                    "rimeContext": {
                        "candidates": [
                            {"label": "1", "text": "候选", "comment": "rime"},
                        ]
                    },
                },
                adapter=adapter,
                core=core,
                predictor=self.predictor,
            )

        rag_item = next(item for item in response["displayCandidates"] if item["sourceType"] == "rag")
        breakdown = rag_item["metadata"]["score_breakdown"]
        self.assertEqual(breakdown["schemaVersion"], "rag-ime.score-breakdown.v1")
        self.assertIn("fts5", breakdown["components"])
        self.assertEqual(breakdown["components"]["accepted"], 0.6)
        self.assertEqual(breakdown["rawSignals"]["acceptedCount"], 1)
        self.assertIn("weights", breakdown)

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

    def test_dirty_raw_pinyin_without_rime_candidate_refreshes_from_committed_context(self) -> None:
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
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: committed context fallback")
        self.assertEqual(response["queryBasis"], "committedContext")
        self.assertNotIn("asdioj", self.predictor.last_current_input)
        self.assertIn("候选布局", self.predictor.last_current_input)
        self.assertGreaterEqual(len(response["modelPredictions"]), 1)
        self.assertGreaterEqual(len(response["displayCandidates"]), 1)

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
        self.assertEqual(decision.reason, "skip: low-information Rime candidates")

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
            self.assertTrue(response["recordedCommitAction"])
            self.assertEqual(response["commitAction"]["actionType"], "accepted")
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT e.committed_text, e.candidate_rank, e.source, s.accepted_count
                    FROM input_events e
                    JOIN memory_state s ON s.event_id = e.id
                    WHERE e.committed_text = ?
                    """,
                    ("统一选择写回接口",),
                ).fetchone()
            self.assertEqual(row, ("统一选择写回接口", 3, "squirrel_rime_sidecar", 1))

    def test_rime_select_model_candidate_feedback_changes_future_memory_ranking(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-model-feedback-") as tmp:
            db_path = f"{tmp}/select-model.sqlite"
            core = LocalSqliteCoreClient(db_path)
            adapter = InputMethodAdapter(core)
            adapter.commit_text("普通模型候选", recent_context="模型 候选 反馈", source="fixture")
            response = record_rime_side_candidate_selection(
                payload={
                    "candidate": {
                        "label": "2",
                        "selectionKey": "2",
                        "selectionRank": 2,
                        "text": "模型短候选",
                        "insertText": "模型短候选",
                        "sourceType": "model",
                        "selectionAction": "commit_side_candidate",
                        "sourceIndex": 0,
                    },
                    "query": "模型 候选 反馈",
                    "recentContext": "用户选择模型候选",
                    "preedit": "moxing",
                },
                adapter=adapter,
                core=core,
            )
            suggestions = core.suggest_for_input(current_input="模型 候选 反馈", top_k=2)

        self.assertFalse(response["recordedAction"])
        self.assertTrue(response["recordedCommitAction"])
        self.assertEqual(response["commitAction"]["memoryId"], response["eventId"])
        self.assertEqual(response["commitAction"]["actionType"], "accepted")
        self.assertEqual(response["recordedActionCount"], 1)
        self.assertEqual(suggestions[0].surface_text, "模型短候选")
        self.assertIn("accepted:1", suggestions[0].metadata["reason"])

    def test_rime_select_records_skipped_higher_memory_feedback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-feedback-") as tmp:
            db_path = f"{tmp}/select.sqlite"
            core = LocalSqliteCoreClient(db_path)
            adapter = InputMethodAdapter(core)
            skipped_event_id = int(
                adapter.commit_text(
                    "把 RAG 候选做成可选择的输入片段",
                    recent_context="反馈测试",
                    source="fixture",
                ).split(":", 1)[-1]
            )
            selected_event_id = int(
                adapter.commit_text(
                    "补齐 selection feedback",
                    recent_context="反馈测试",
                    source="fixture",
                ).split(":", 1)[-1]
            )
            shown_candidates = [
                {
                    "label": "1",
                    "selectionKey": "1",
                    "selectionRank": 1,
                    "text": "把 RAG 候选做成可选择的输入片段",
                    "insertText": "把 RAG 候选做成可选择的输入片段",
                    "sourceType": "rag",
                    "suggestionId": "sug-skip",
                    "memoryId": f"event:{skipped_event_id}",
                    "sourceEventId": skipped_event_id,
                },
                {
                    "label": "2",
                    "selectionKey": "2",
                    "selectionRank": 2,
                    "text": "补齐 selection feedback",
                    "insertText": "补齐 selection feedback",
                    "sourceType": "memory",
                    "suggestionId": "sug-accept",
                    "memoryId": f"event:{selected_event_id}",
                    "sourceEventId": selected_event_id,
                },
            ]

            response = record_rime_side_candidate_selection(
                payload={
                    "candidate": shown_candidates[1],
                    "shownCandidates": shown_candidates,
                    "query": "selection feedback",
                    "recentContext": "用户选择第二个候选",
                    "preedit": "selection",
                },
                adapter=adapter,
                core=core,
            )

            self.assertTrue(response["recordedAction"])
            self.assertEqual(response["recordedActionCount"], 2)
            self.assertEqual(response["action"]["actionType"], "accepted")
            self.assertEqual(response["skippedActionCount"], 1)
            self.assertEqual(response["skippedActions"][0]["actionType"], "skipped")
            self.assertEqual(response["skippedActions"][0]["memoryId"], f"event:{skipped_event_id}")
            with sqlite3.connect(db_path) as conn:
                actions = conn.execute(
                    """
                    SELECT memory_id, action_type, suggestion_id
                    FROM memory_actions
                    ORDER BY id
                    """
                ).fetchall()
            self.assertEqual(
                actions,
                [
                    (f"event:{selected_event_id}", "accepted", "sug-accept"),
                    (f"event:{skipped_event_id}", "skipped", "sug-skip"),
                ],
            )

    def test_rime_select_feedback_changes_future_memory_ranking(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-select-rerank-") as tmp:
            db_path = f"{tmp}/select-rerank.sqlite"
            project = "wisdom-weasel-rag-ime"
            query = "selection feedback 输入法 候选"
            core = LocalSqliteCoreClient(db_path)
            adapter = InputMethodAdapter(core)
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=1_900_000_000_000,
                    source="fixture",
                    committed_text="补齐 selection feedback",
                    recent_context=query,
                    project=project,
                    tags=("phrase-memory",),
                )
            )
            core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=1_900_000_001_000,
                    source="fixture",
                    committed_text="把 RAG 候选做成可选择的输入片段",
                    recent_context=query,
                    project=project,
                    tags=("phrase-memory",),
                )
            )
            before = core.suggest_for_input(current_input=query, project=project, top_k=2)
            selected_before = before[1]
            skipped_before = before[0]
            selected_id_from_suggestion = selected_before.source_event_id
            skipped_id_from_suggestion = skipped_before.source_event_id
            shown_candidates = [
                _shown_candidate_from_suggestion(skipped_before, label="1"),
                _shown_candidate_from_suggestion(selected_before, label="2"),
            ]
            response = record_rime_side_candidate_selection(
                payload={
                    "candidate": shown_candidates[1],
                    "shownCandidates": shown_candidates,
                    "query": query,
                    "recentContext": "用户选择第二个候选",
                    "project": project,
                },
                adapter=adapter,
                core=core,
            )
            after = core.suggest_for_input(current_input=query, project=project, top_k=2)

            self.assertEqual(response["recordedActionCount"], 2)
            self.assertEqual(response["skippedActionCount"], 1)
            self.assertEqual(after[0].surface_text, selected_before.surface_text)
            self.assertIn("accepted:1", after[0].metadata["reason"])
            with sqlite3.connect(db_path) as conn:
                state = {
                    row[0]: (row[1], row[2])
                    for row in conn.execute(
                        """
                        SELECT e.id, s.accepted_count, s.skipped_count
                        FROM input_events e
                        JOIN memory_state s ON s.event_id = e.id
                        WHERE e.id IN (?, ?)
                        """,
                        (selected_id_from_suggestion, skipped_id_from_suggestion),
                    )
                }
            self.assertEqual(state[selected_id_from_suggestion], (1, 0))
            self.assertEqual(state[skipped_id_from_suggestion], (0, 1))

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


def _shown_candidate_from_suggestion(suggestion: InputSuggestion, *, label: str) -> dict[str, object]:
    return {
        "label": label,
        "selectionKey": label,
        "selectionRank": int(label),
        "text": suggestion.surface_text,
        "insertText": suggestion.metadata.get("insert_text") or suggestion.surface_text,
        "sourceType": "memory",
        "suggestionId": suggestion.suggestion_id,
        "memoryId": suggestion.metadata["memory_id"],
        "sourceEventId": suggestion.source_event_id,
    }


if __name__ == "__main__":
    unittest.main()
