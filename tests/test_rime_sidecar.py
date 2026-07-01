from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import main
from rag_ime.core_client import FixtureCoreClient
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import ModelPrediction
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

    def test_response_merges_rime_first_then_side_candidates(self) -> None:
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
        self.assertEqual(display[0]["sourceType"], "rime")
        self.assertEqual(display[0]["selectionAction"], "select_rime_candidate")
        self.assertEqual(display[0]["rimeIndex"], 0)
        self.assertEqual(display[1]["sourceType"], "rime")
        self.assertEqual(display[2]["sourceType"], "model")
        self.assertEqual(display[2]["selectionAction"], "commit_side_candidate")
        self.assertEqual(display[3]["sourceType"], "rag")
        self.assertEqual(display[3]["selectionAction"], "commit_side_candidate")
        self.assertIsInstance(display[3]["sourceEventId"], int)
        self.assertEqual([item["label"] for item in display[:4]], ["1", "2", "3", "4"])

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
        self.assertEqual(response["mergePolicy"]["maxModelSideCandidates"], 1)
        self.assertTrue(response["mergePolicy"]["ragKeepsRemainingSideSlots"])
        self.assertTrue(response["triggerDecision"]["shouldRefresh"])
        self.assertEqual(response["triggerDecision"]["reason"], "refresh: stable Rime candidates")

    def test_model_predictions_cannot_consume_all_side_slots(self) -> None:
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
                "committedContext": "用户正在讨论 RAG 输入法如何复用 Rime",
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
        self.assertEqual(response["triggerDecision"]["reason"], "skip: composing without stable Rime candidate")
        self.assertEqual(response["modelPredictions"], [])
        self.assertEqual(response["ragCandidates"], [])
        self.assertEqual(response["displayCandidates"], [])
        self.assertFalse(response["mergePolicy"]["sideCandidatesEnabled"])

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
        self.assertEqual(response["displayCandidates"][0]["sourceType"], "rime")

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


if __name__ == "__main__":
    unittest.main()
