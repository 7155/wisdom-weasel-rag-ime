from __future__ import annotations

import unittest

from rag_ime.rag_benchmark import (
    build_ablation_report,
    compute_retrieval_metrics,
    select_validation_config,
    validate_dataset_manifest,
)


class RagBenchmarkManifestTests(unittest.TestCase):
    def test_manifest_binds_one_system_and_rejects_split_leakage(self) -> None:
        manifest = {
            "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
            "benchmarkId": "public-example-v1",
            "system": "knowledge",
            "tool": "knowledge",
            "sourceUrl": "https://example.org/public-benchmark",
            "version": "2026-08-04",
            "sourceSha256": "a" * 64,
            "licenseReference": "https://example.org/public-benchmark/license",
            "corpusIncluded": False,
            "splits": {
                "train": ["q-1"],
                "validation": ["q-2", "q-3"],
                "held_out": ["q-4"],
            },
        }

        normalized = validate_dataset_manifest(manifest)

        self.assertEqual("knowledge", normalized["system"])
        self.assertEqual("knowledge", normalized["tool"])
        self.assertEqual(
            {"train", "validation", "held_out"},
            set(normalized["splitHashes"]),
        )
        self.assertEqual(2, normalized["splitCounts"]["validation"])

        leaked = {
            **manifest,
            "splits": {
                **manifest["splits"],
                "held_out": ["q-3", "q-4"],
            },
        }
        with self.assertRaisesRegex(ValueError, "split leakage"):
            validate_dataset_manifest(leaked)

        wrong_tool = {**manifest, "tool": "memory"}
        with self.assertRaisesRegex(ValueError, "must use the knowledge Tool"):
            validate_dataset_manifest(wrong_tool)


class RagBenchmarkMetricTests(unittest.TestCase):
    def test_rank_metrics_use_qrels_and_reject_duplicate_results(self) -> None:
        report = compute_retrieval_metrics(
            [
                {
                    "queryId": "q-1",
                    "relevant": {"chunk-a": 3.0, "chunk-b": 1.0},
                    "retrieved": ["chunk-x", "chunk-b", "chunk-a"],
                },
                {
                    "queryId": "q-2",
                    "relevant": {"chunk-c": 1.0},
                    "retrieved": ["chunk-c", "chunk-z"],
                },
            ],
            k_values=(1, 3),
        )

        self.assertEqual(2, report["queryCount"])
        self.assertAlmostEqual(0.5, report["metrics"]["recallAtK"]["1"])
        self.assertAlmostEqual(1.0, report["metrics"]["recallAtK"]["3"])
        self.assertAlmostEqual(0.75, report["metrics"]["mrr"])
        self.assertAlmostEqual(0.5, report["metrics"]["ndcgAtK"]["1"])
        self.assertAlmostEqual(
            0.7706701468217607,
            report["metrics"]["ndcgAtK"]["3"],
        )

        with self.assertRaisesRegex(ValueError, "duplicate retrieved IDs"):
            compute_retrieval_metrics(
                [
                    {
                        "queryId": "q-duplicate",
                        "relevant": {"chunk-a": 1.0},
                        "retrieved": ["chunk-a", "chunk-a"],
                    }
                ],
                k_values=(1,),
            )


class RagBenchmarkAblationTests(unittest.TestCase):
    def test_four_lanes_are_comparable_and_hard_gated(self) -> None:
        conditions = {
            "model": "openai-codex/gpt-5.6-luna",
            "thinking": "max",
            "datasetSplitSha256": "b" * 64,
            "permissionSha256": "c" * 64,
            "denominator": 20,
        }
        gates = {
            "splitIntegrity": True,
            "scopeBoundary": True,
            "citationResolution": True,
            "abstention": True,
            "crossSystemLeakage": True,
        }
        default_config = "d" * 64
        tuned_config = "e" * 64
        lanes = [
            {
                "lane": "baseline",
                "features": {"skill": False, "offlineTuned": False, "agentic": False},
                "conditions": conditions,
                "retrievalConfigSha256": default_config,
                "metrics": {"mrr": 0.4, "recallAt10": 0.5},
                "costs": {"latencyMs": 100.0, "tokens": 1_000.0, "toolCalls": 20.0},
                "hardGates": gates,
            },
            {
                "lane": "skill",
                "features": {"skill": True, "offlineTuned": False, "agentic": False},
                "conditions": conditions,
                "retrievalConfigSha256": default_config,
                "metrics": {"mrr": 0.5, "recallAt10": 0.6},
                "costs": {"latencyMs": 105.0, "tokens": 1_050.0, "toolCalls": 20.0},
                "hardGates": gates,
            },
            {
                "lane": "tuned",
                "features": {"skill": True, "offlineTuned": True, "agentic": False},
                "conditions": conditions,
                "retrievalConfigSha256": tuned_config,
                "metrics": {"mrr": 0.7, "recallAt10": 0.8},
                "costs": {"latencyMs": 110.0, "tokens": 1_100.0, "toolCalls": 20.0},
                "hardGates": gates,
            },
            {
                "lane": "agentic",
                "features": {
                    "skill": True,
                    "offlineTuned": True,
                    "agentic": True,
                    "subagents": True,
                    "maxRetrievalRounds": 3,
                },
                "conditions": conditions,
                "retrievalConfigSha256": tuned_config,
                "metrics": {"mrr": 0.8, "recallAt10": 0.9},
                "costs": {"latencyMs": 260.0, "tokens": 2_800.0, "toolCalls": 58.0},
                "hardGates": gates,
            },
        ]

        report = build_ablation_report(
            metric_namespace="knowledge",
            lanes=lanes,
            required_hard_gates=tuple(gates),
        )

        self.assertTrue(report["accepted"])
        self.assertEqual("accepted", report["acceptanceReceipt"]["status"])
        self.assertEqual(64, len(report["reportSha256"]))
        self.assertEqual(
            {
                "baseline": 0.4,
                "optimized": 0.8,
                "absoluteDelta": 0.4,
                "relativeDelta": 1.0,
            },
            report["comparison"]["metrics"]["mrr"],
        )
        self.assertEqual(
            160.0,
            report["comparison"]["costs"]["latencyMs"]["absoluteDelta"],
        )

        mismatched = [dict(lane) for lane in lanes]
        mismatched[-1] = {
            **mismatched[-1],
            "conditions": {**conditions, "permissionSha256": "f" * 64},
        }
        with self.assertRaisesRegex(
            ValueError,
            "same model, data, permissions, and denominator",
        ):
            build_ablation_report(
                metric_namespace="knowledge",
                lanes=mismatched,
                required_hard_gates=tuple(gates),
            )

        failed = [dict(lane) for lane in lanes]
        failed[-1] = {
            **failed[-1],
            "hardGates": {**gates, "citationResolution": False},
        }
        rejected = build_ablation_report(
            metric_namespace="knowledge",
            lanes=failed,
            required_hard_gates=tuple(gates),
        )
        self.assertFalse(rejected["accepted"])
        self.assertEqual("rejected", rejected["acceptanceReceipt"]["status"])
        self.assertEqual(
            ["agentic:citationResolution"],
            rejected["failedHardGates"],
        )


class RagBenchmarkTuningTests(unittest.TestCase):
    def test_tuning_only_exposes_validation_queries_and_freezes_winner(self) -> None:
        manifest = validate_dataset_manifest(
            {
                "schemaVersion": "rag-ime.rag-benchmark-dataset.v1",
                "benchmarkId": "sealed-tuning-v1",
                "system": "knowledge",
                "tool": "knowledge",
                "sourceUrl": "https://example.org/sealed-tuning",
                "version": "v1",
                "sourceSha256": "a" * 64,
                "licenseReference": "https://example.org/license",
                "corpusIncluded": False,
                "splits": {
                    "train": ["q-train"],
                    "validation": ["q-dev-1", "q-dev-2"],
                    "held_out": ["q-secret"],
                },
            }
        )
        validation_cases = [
            {
                "system": "knowledge",
                "queryId": "q-dev-1",
                "query": "alpha",
                "split": "validation",
                "slice": "one-doc",
                "relevant": {"doc-a": 1.0},
            },
            {
                "system": "knowledge",
                "queryId": "q-dev-2",
                "query": "beta",
                "split": "validation",
                "slice": "two-doc",
                "relevant": {"doc-b": 1.0},
            },
        ]
        observed: list[tuple[str, int]] = []

        def retrieve(query: dict[str, object], config: dict[str, object]) -> list[str]:
            self.assertEqual({"queryId", "system", "text"}, set(query))
            self.assertNotEqual("q-secret", query["queryId"])
            top_k = int(config["topK"])
            observed.append((str(query["queryId"]), top_k))
            relevant = "doc-a" if query["queryId"] == "q-dev-1" else "doc-b"
            return ["distractor", relevant][:top_k]

        report = select_validation_config(
            manifest=manifest,
            validation_cases=validation_cases,
            candidate_configs=[{"topK": 1}, {"topK": 2}],
            retrieve=retrieve,
            objective="ndcgAtK.2",
            k_values=(1, 2),
        )

        self.assertEqual({"topK": 2}, report["winner"]["config"])
        self.assertEqual("validation", report["selectionSplit"])
        self.assertFalse(report["heldOutLabelsObserved"])
        self.assertEqual(1, report["winner"]["validation"]["perSlice"]["one-doc"]["queryCount"])
        self.assertEqual(1, report["winner"]["validation"]["perSlice"]["two-doc"]["queryCount"])
        self.assertEqual(4, len(observed))
        self.assertEqual(64, len(report["selectionReceiptSha256"]))

        with self.assertRaisesRegex(ValueError, "validation cases only"):
            select_validation_config(
                manifest=manifest,
                validation_cases=[
                    *validation_cases,
                    {
                        "system": "knowledge",
                        "queryId": "q-secret",
                        "query": "secret",
                        "split": "held_out",
                        "relevant": {"doc-secret": 1.0},
                    },
                ],
                candidate_configs=[{"topK": 2}],
                retrieve=retrieve,
                objective="mrr",
                k_values=(1, 2),
            )


if __name__ == "__main__":
    unittest.main()
