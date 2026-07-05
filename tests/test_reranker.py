from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

from rag_ime.cli import main
from rag_ime.reranker import rerank_candidate_dicts


class RerankerTests(unittest.TestCase):
    def test_reranker_penalizes_echoes_and_duplicates_but_keeps_rime(self) -> None:
        ranked = rerank_candidate_dicts(
            [
                {"source": "rime", "text": "输入法", "confidence": 0.8},
                {"source": "model", "text": "继续预测", "confidence": 0.9},
                {"source": "rag", "text": "输入法", "confidence": 0.7},
                {"source": "memory", "text": "长期记忆候选", "acceptedCount": 3, "pinned": True},
            ],
            query="输入法",
            recent_context="用户刚刚输入 输入法",
            max_candidates=3,
        )

        self.assertTrue(any(item["source"] == "rime" for item in ranked))
        self.assertEqual(ranked[0]["text"], "长期记忆候选")
        echo_items = [item for item in ranked if item["text"] == "输入法"]
        self.assertTrue(all(item["oldInputEcho"] for item in echo_items))

    def test_reranker_preserves_rime_fallback_when_limited(self) -> None:
        ranked = rerank_candidate_dicts(
            [
                {"source": "memory", "text": "高频记忆", "acceptedCount": 10, "pinned": True},
                {"source": "model", "text": "模型预测", "confidence": 1.0},
                {"source": "rime", "text": "基础词库", "confidence": 0.1},
            ],
            max_candidates=2,
        )

        self.assertEqual(len(ranked), 2)
        self.assertTrue(any(item["source"] == "rime" and item["text"] == "基础词库" for item in ranked))

    def test_cli_rerank_demo_outputs_source_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-rerank-demo-") as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--db-path",
                        f"{tmp}/rerank.sqlite",
                        "rerank-demo",
                        "--query",
                        "输入法",
                        "--recent-context",
                        "用户刚刚输入 输入法",
                        "--candidate",
                        "rime:输入法",
                        "--candidate",
                        "model:继续预测",
                        "--candidate-json",
                        json.dumps({"source": "memory", "text": "长期记忆候选", "acceptedCount": 3}, ensure_ascii=False),
                    ]
                )

        report = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["schemaVersion"], "rag-ime.rerank-demo.v1")
        self.assertTrue(report["rimeFallbackPreserved"])
        self.assertEqual(report["sourceCounts"]["rime"], 1)
        self.assertIn("scoreBreakdown", report["candidates"][0])


if __name__ == "__main__":
    unittest.main()
