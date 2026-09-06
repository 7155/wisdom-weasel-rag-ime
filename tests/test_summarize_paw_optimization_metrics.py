from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PawOptimizationMetricsSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts import summarize_paw_optimization_metrics as exporter

        cls.exporter = exporter
        cls.experiments = json.loads(
            (ROOT / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        cls.ledger = json.loads(
            (ROOT / "eval/interview-metrics/evidence-ledger.v1.json").read_text(
                encoding="utf-8"
            )
        )

    def project(self, experiments=None, ledger=None):
        return self.exporter.project(
            experiments or self.experiments,
            ledger or self.ledger,
            repo_root=ROOT,
        )

    def by_key(self, result, key):
        return next(row for row in result["scenarios"] if row["key"] == key)

    def test_current_rows_use_real_success_denominators_and_costs(self):
        result = self.project()
        self.assertEqual(
            {row["key"] for row in result["scenarios"]},
            {"enterpriseops", "enterprise_rag", "cloudops", "memory"},
        )

        ops = self.by_key(result, "enterpriseops")
        self.assertEqual(ops["candidate"]["taskPass"], {"passed": 3, "total": 3})
        self.assertEqual(ops["candidate"]["costUsd"], "0.07291692")
        self.assertEqual(ops["candidate"]["costPerSuccessfulTaskUsd"], "0.02430564")
        self.assertEqual(
            ops["candidate"]["costSource"],
            "runtimeCostReceipt.reportedCostUsd.total",
        )
        self.assertEqual(ops["candidate"]["executionFailureSignalCount"], 0)
        self.assertIsNone(ops["candidate"]["severeBusinessErrorCount"])
        self.assertEqual(ops["candidate"]["elapsedMs"], 574319.984)

        rag = self.by_key(result, "enterprise_rag")
        self.assertEqual(rag["candidate"]["taskPass"], {"passed": 4, "total": 4})
        self.assertEqual(rag["candidate"]["costPerSuccessfulTaskUsd"], "0.0257344")
        self.assertIsNone(rag["candidate"]["elapsedMs"])
        self.assertTrue(rag["validationBoundary"]["candidateAware"])
        self.assertNotIn(
            "data-agent.enterpriseops-csm.validation.20260901",
            rag["ledgerMetricIds"],
        )

        cloud = self.by_key(result, "cloudops")
        self.assertIsNone(cloud["candidate"]["taskPass"])
        self.assertEqual(cloud["candidate"]["caPass"], {"passed": 12, "total": 12})
        self.assertEqual(cloud["candidate"]["caPassUnit"], "cause_identification_case")
        self.assertEqual(cloud["candidate"]["caPassRubric"], "CA")
        self.assertIsNone(cloud["candidate"]["costPerSuccessfulTaskUsd"])
        self.assertEqual(cloud["candidate"]["costPerSuccessfulCaseUsd"], "0.02301085333333333333333333333")
        self.assertEqual(cloud["candidate"]["executionFailureSignalCount"], 0)
        self.assertIsNone(cloud["candidate"]["severeBusinessErrorCount"])
        model_only = cloud["stages"][1]
        self.assertIsNone(model_only["taskPass"])
        self.assertEqual(model_only["caPass"], {"passed": 11, "total": 12})
        self.assertEqual(model_only["caPassRubric"], "CA")

    def test_memory_keeps_lifecycle_unit_separate_from_fixture_count(self):
        memory = self.by_key(self.project(), "memory")
        self.assertEqual(memory["candidate"]["lifecyclePass"], {"passed": 1, "total": 1})
        self.assertEqual(memory["candidate"]["fixtureCaseCount"], 5)
        self.assertIsNone(memory["candidate"]["costPerSuccessfulTaskUsd"])
        self.assertEqual(memory["candidate"]["costPerSuccessfulLifecycleUsd"], "0.0071846")
        self.assertEqual(
            memory["candidate"]["costSource"],
            "runtimeCostReceipt.perModel.reportedCostUsd.total",
        )
        self.assertEqual(memory["candidate"]["executionFailureSignalCount"], 0)
        self.assertIsNone(memory["candidate"]["severeBusinessErrorCount"])

    def test_rag_distinguishes_frozen_judgments_from_rerun_calls(self):
        rag = self.by_key(self.project(), "enterprise_rag")
        self.assertEqual(rag["judge"]["runtimeCalls"], 0)
        self.assertEqual(rag["judge"]["retainedJudgmentCount"], 24)
        self.assertEqual(
            [stage["judge"]["retainedJudgmentCount"] for stage in rag["stages"]],
            [8, 8, 8],
        )
        self.assertTrue(rag["judge"]["offlineRescore"])

    def test_failed_candidates_are_retained_and_optimizer_cost_stays_unknown(self):
        result = self.project()
        cloud = self.by_key(result, "cloudops")
        failed_ids = {item["experimentId"] for item in cloud["optimizationInvestment"]["failedAttempts"]}
        self.assertIn("cloudops.alert-first-luna-model-only-r1.v1", failed_ids)
        self.assertIn("cloudops.evidence-search.v2", failed_ids)
        self.assertGreaterEqual(cloud["optimizationInvestment"]["candidateRecordCount"], 5)
        self.assertIsNone(cloud["optimizationInvestment"]["optimizerCostUsd"])
        self.assertIsNone(cloud["optimizationInvestment"]["observedEvaluationCostUsd"])
        self.assertEqual(cloud["optimizationInvestment"]["observedEvaluationCostStatus"], "incomplete")
        self.assertEqual(cloud["breakEven"]["status"], "unknown")
        self.assertIsNone(cloud["breakEven"]["reuseCount"])

    def test_missing_cost_or_task_counts_are_unknown_instead_of_zero(self):
        document = copy.deepcopy(self.experiments)
        target = next(
            item
            for item in document["experiments"]
            if item["id"] == "cloudops.luna-owner-mechanism-prompt-r5.v1"
        )
        target["candidate"]["metrics"].pop("apiCostUsd")
        target["candidate"]["metrics"].pop("toolCalls")
        target["candidate"]["metrics"].pop("failedToolCalls")
        result = self.project(document)
        cloud = self.by_key(result, "cloudops")
        # The raw Runtime cost receipt is still available, so the exporter is
        # expected to recover the amount rather than turn an omitted ledger
        # field into an unknown.
        self.assertEqual(cloud["candidate"]["costUsd"], "0.27613024")
        self.assertIsNone(cloud["candidate"]["costPerSuccessfulTaskUsd"])
        self.assertEqual(cloud["candidate"]["costPerSuccessfulCaseUsd"], "0.02301085333333333333333333333")
        self.assertEqual(cloud["candidate"]["executionFailureSignalCount"], 0)
        self.assertIsNone(cloud["candidate"]["severeBusinessErrorCount"])
        self.assertNotIn("apiCostUsd", " ".join(cloud["candidate"]["unknowns"]))
        self.assertIsNone(self.exporter._cost({}, []))


if __name__ == "__main__":
    unittest.main()
