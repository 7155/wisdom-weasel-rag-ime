from __future__ import annotations

import unittest

from rag_ime.rag_retrieval_experiment import (
    deterministic_query_plan,
    evaluate_retrieval_configuration,
    reciprocal_rank_fusion,
)


class RagRetrievalExperimentTests(unittest.TestCase):
    def test_evaluation_keeps_qrels_out_of_retriever_and_reports_slices(self) -> None:
        observed_queries: list[dict[str, object]] = []
        observed_configs: list[dict[str, object]] = []

        def retrieve(
            query: dict[str, object],
            config: dict[str, object],
        ) -> list[str]:
            observed_queries.append(query)
            observed_configs.append(config)
            self.assertEqual({"queryId", "system", "text"}, set(query))
            return ["doc-noise", "doc-a", "doc-a"]

        report = evaluate_retrieval_configuration(
            cases=[
                {
                    "queryId": "q-1",
                    "system": "knowledge",
                    "split": "held_out",
                    "slice": "basic",
                    "query": "Where is alpha?",
                    "relevant": {"doc-a": 1.0},
                    "retrievalEvaluable": True,
                },
                {
                    "queryId": "q-abstain",
                    "system": "knowledge",
                    "split": "held_out",
                    "slice": "info_not_found",
                    "query": "Missing information",
                    "relevant": {},
                    "retrievalEvaluable": False,
                },
            ],
            config={"mode": "hybrid", "topK": 10},
            retrieve=retrieve,
            k_values=(1, 2),
        )

        self.assertEqual(1, report["metrics"]["queryCount"])
        self.assertEqual(0.5, report["metrics"]["metrics"]["mrr"])
        self.assertEqual(1.0, report["metrics"]["metrics"]["recallAtK"]["2"])
        self.assertEqual(1, report["perSlice"]["basic"]["queryCount"])
        self.assertEqual(1, report["costs"]["retrievalCalls"])
        self.assertEqual(0, report["costs"]["plannerCalls"])
        self.assertEqual(1, len(observed_queries))
        self.assertEqual({"mode": "hybrid", "topK": 10}, observed_configs[0])
        self.assertEqual(
            ["doc-noise", "doc-a"],
            report["privateCases"][0]["fusedRetrieved"],
        )
        self.assertEqual(64, len(report["receiptSha256"]))

    def test_multi_query_planner_is_bounded_and_rrf_fuses_rankings(self) -> None:
        rankings = {
            "原始复杂问题。第一条证据是什么？第二条证据是什么？": [
                "doc-noise",
                "doc-a",
            ],
            "第一条证据是什么": ["doc-a", "doc-noise"],
            "第二条证据是什么": ["doc-b", "doc-noise"],
        }

        def retrieve(
            query: dict[str, object],
            _config: dict[str, object],
        ) -> list[str]:
            return rankings[str(query["text"])]

        report = evaluate_retrieval_configuration(
            cases=[
                {
                    "queryId": "q-multi",
                    "system": "knowledge",
                    "split": "held_out",
                    "slice": "completeness",
                    "query": "原始复杂问题。第一条证据是什么？第二条证据是什么？",
                    "relevant": {"doc-a": 1.0, "doc-b": 1.0},
                }
            ],
            config={"mode": "hybrid"},
            retrieve=retrieve,
            query_planner=deterministic_query_plan,
            max_queries_per_case=3,
            fusion_rrf_k=1,
            k_values=(1, 3),
        )

        self.assertEqual(3, report["costs"]["retrievalCalls"])
        self.assertEqual(1, report["costs"]["plannerCalls"])
        self.assertEqual(3, report["privateCases"][0]["plannedQueryCount"])
        self.assertEqual(1.0, report["metrics"]["metrics"]["recallAtK"]["3"])

    def test_rrf_is_deterministic_and_validates_inputs(self) -> None:
        self.assertEqual(
            ["b", "a", "c"],
            reciprocal_rank_fusion(
                [["a", "b", "a"], ["b", "c"]],
                rrf_k=1,
                limit=3,
            ),
        )
        with self.assertRaisesRegex(ValueError, "rankings"):
            reciprocal_rank_fusion([])
        with self.assertRaisesRegex(ValueError, "rrf_k"):
            reciprocal_rank_fusion([["a"]], rrf_k=0)


if __name__ == "__main__":
    unittest.main()
