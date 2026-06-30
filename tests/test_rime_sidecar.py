from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import main
from rag_ime.core_client import FixtureCoreClient
from rag_ime.models import ModelPrediction
from rag_ime.rime_sidecar import (
    build_rime_sidecar_response,
    choose_semantic_query,
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


if __name__ == "__main__":
    unittest.main()
