from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentLabShowcaseExportTests(unittest.TestCase):
    def setUp(self):
        from scripts import export_agent_lab_showcase as exporter
        self.exporter = exporter
        self.source = ROOT / "eval/interview-metrics/agent-experiments.v1.json"
        self.document = json.loads(self.source.read_text())

    def export(self, document=None):
        return self.exporter.project(document or self.document, repo_root=ROOT)

    def test_current_four_experiments_keep_exact_metrics_and_real_stage_counts(self):
        result = self.export()
        self.assertEqual(len(result["experiments"]), 4)
        by_id = {e["id"]: e for e in result["experiments"]}
        ops = by_id["enterpriseops-csm.luna-prompt-adaptation-r7.v1"]
        self.assertEqual([s["decision"] for s in ops["stages"]], ["baseline", "reject", "keep"])
        self.assertEqual(ops["candidate"]["metrics"]["apiCostUsd"], 0.07291692)
        memory = by_id["memory.maintenance-pi-model-only-20260905-r3.v1"]
        self.assertEqual(len(memory["stages"]), 2)
        self.assertFalse(memory["promptAdaptationNeeded"])
        self.assertEqual(memory["candidate"]["metrics"]["durableCaseCount"], 4)
        self.assertEqual(memory["candidate"]["metrics"]["retrievalPassed"], 1)
        self.assertEqual(memory["candidate"]["metrics"]["currentAtomCount"], 6)
        self.assertEqual(memory["candidate"]["metrics"]["requestCount"], 2)
        self.assertEqual(memory["candidate"]["metrics"]["apiCostUsd"], 0.0071846)
        self.assertEqual(memory["baseline"]["metrics"]["apiCostUsd"], 0.163425)
        self.assertEqual(memory["costAuthority"], "runtime_cost_reconciled_estimate")
        self.assertTrue(memory["validationBoundary"]["syntheticFixture"])
        self.assertTrue(memory["validationBoundary"]["currentRuntimeValidation"])
        self.assertFalse(memory["validationBoundary"]["oldCliPairReproduced"])

    def test_rag_exposes_candidate_aware_boundary_and_rejects(self):
        rag = next(e for e in self.export()["experiments"] if e["key"] == "rag")
        self.assertEqual([s["metrics"]["exactCitationFactsCovered"] for s in rag["stages"]], [7, 8, 9])
        self.assertEqual([s["decision"] for s in rag["stages"]], ["reject", "reject", "keep"])
        self.assertTrue(rag["validationBoundary"]["candidateAware"])
        self.assertFalse(rag["validationBoundary"]["unbiasedPromotionClaimAllowed"])
        self.assertFalse(rag["providerBillAvailable"])

    def test_unknown_fields_and_raw_examples_never_cross_projection(self):
        document = copy.deepcopy(self.document)
        secret = "PRIVATE_SENTINEL_/Users/private/gold-answer.txt"
        for e in document["experiments"]:
            e["privateTranscript"] = secret
            e["baseline"]["outputExamples"] = [{"question": secret, "gold": secret}]
            e["candidate"]["metrics"]["rawAnswer"] = secret
            for stage in e.get("comparison", {}).get("stageChain", []):
                stage["privateGold"] = secret
        result = json.dumps(self.export(document))
        self.assertNotIn(secret, result)
        self.assertNotIn("outputExamples", result)
        self.assertNotIn("evidenceRefs", result)

    def test_public_prose_and_numbers_reject_private_paths_or_nonfinite_values(self):
        for field, value in [("businessProblem", "/Users/private/task.txt"), ("businessProblem", "C:\\Users\\private\\task.txt")]:
            document = copy.deepcopy(self.document)
            target = next(e for e in document["experiments"] if e["id"] == self.exporter.EXPERIMENTS[0][1])
            target[field] = value
            with self.assertRaises(ValueError):
                self.export(document)
        document = copy.deepcopy(self.document)
        target = next(e for e in document["experiments"] if e["id"] == self.exporter.EXPERIMENTS[0][1])
        target["candidate"]["metrics"]["apiCostUsd"] = float("nan")
        with self.assertRaises(ValueError):
            self.export(document)

    def test_missing_or_superseded_current_experiment_is_not_silently_replaced(self):
        document = copy.deepcopy(self.document)
        document["experiments"] = [e for e in document["experiments"] if e["id"] != self.exporter.EXPERIMENTS[0][1]]
        with self.assertRaises(ValueError):
            self.export(document)
        document = copy.deepcopy(self.document)
        next(e for e in document["experiments"] if e["id"] == self.exporter.EXPERIMENTS[0][1])["projectionState"] = "superseded"
        with self.assertRaises(ValueError):
            self.export(document)

    def test_projection_is_deterministic_and_receipts_are_content_bound(self):
        first = self.export()
        self.assertEqual(first, self.export())
        self.assertFalse(first["multiAgentMatchedBenefitMeasured"])
        for e in first["experiments"]:
            self.assertGreater(len(e["evidence"]), 0)
            for receipt in e["evidence"]:
                self.assertEqual(set(receipt), {"file", "sha256"})
                self.assertNotIn("/", receipt["file"])
                self.assertRegex(receipt["sha256"], r"^[0-9a-f]{64}$")

    def test_conflicting_stage_and_headline_cost_cannot_be_exported(self):
        document = copy.deepcopy(self.document)
        target = next(e for e in document["experiments"] if e["id"] == self.exporter.EXPERIMENTS[0][1])
        target["comparison"]["stageChain"][-1]["costUsd"] = 0.01
        with self.assertRaises(ValueError):
            self.export(document)


if __name__ == "__main__":
    unittest.main()
