from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import export_memory_pi_trial_pair as exporter


ROOT = Path(__file__).resolve().parents[1]
REF = "eval/interview-metrics/runs/memory-pi-current-pair-20260905.r3.json"
EXPERIMENT_ID = "memory.maintenance-pi-model-only-20260905-r3.v1"


class MemoryPiTrialPairEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads((ROOT / REF).read_text())

    def sources(self):
        """Synthetic producer inputs; never read the retained private run directory."""
        rows = []
        for label in ("baseline", "candidate"):
            side = self.receipt[label]
            rows.append({"label": label, "model": side["model"], "job": {
                "jobId": side["trialId"], "publicSpec": copy.deepcopy(side["publicSpec"]),
                "state": "completed", "error": "", "cancelRequested": False,
                "createdAtMs": side["createdAtMs"], "updatedAtMs": side["completedAtMs"],
                "sessions": [{"sessionId": f"{label}-{i}", "turnId": f"turn-{i}"} for i in range(2)],
                "result": {"status": "completed", "qualityVerdict": "pass", "caseCount": 5,
                    "metrics": copy.deepcopy(side["metrics"]),
                    "signals": {key: False for key in ("personalMemoryQualityMeasured",
                        "heldOutEvaluated", "productionMutationPerformed", "installedAcceptanceEvaluated")},
                    "cost": {"estimatedCostUsd": float(side["estimatedCostUsd"]),
                             "available": True, "requestCount": 2},
                    "evidence": {"reportRef": side["reportRef"]}}}})
        catalog = self.receipt["pricingCatalog"]
        return {"pair-receipts.json": {"receipts": rows},
            "baseline-receipt.json": rows[0], "candidate-receipt.json": rows[1],
            "reconciled-runtime-cost.json": copy.deepcopy(self.receipt["runtimeCostReceipt"]),
            "source-hashes.json": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                   for name in exporter.CODE_FILES},
            "model-catalog-pricing.json": {"source": catalog["source"],
                "sourceSha256": catalog["sourceSha256"], "gpt": {"models": [
                    {"id": m["id"], "provider": m["provider"], "cost": m["cost"]}
                    for m in catalog["models"]]}}}

    def export(self, sources):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename, value in sources.items():
                (root / filename).write_text(json.dumps(value))
            return exporter.build_receipt(root)

    def test_export_preserves_counts_hashes_and_cost_without_exporting_session_bodies(self):
        sources = self.sources()
        sources["candidate-receipt.json"]["job"]["privateTranscript"] = "PRIVATE_SENTINEL"
        sources["model-catalog-pricing.json"]["credential"] = "PRIVATE_SENTINEL"
        result = self.export(sources)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        self.assertNotIn("sessionId", json.dumps(result))
        self.assertEqual(len(result["sourceFiles"]), 6)
        self.assertEqual(result["runtimeCostReceipt"]["aggregate"]["requestCount"], 4)
        self.assertEqual(result["candidate"]["metrics"]["curation"]["currentAtomCount"], 6)
        self.assertEqual(result["baseline"]["estimatedCostUsd"], "0.163425")
        self.assertEqual(result["candidate"]["estimatedCostUsd"], "0.0071846")
        self.assertFalse(result["boundaries"]["oldCliPairReproduced"])

    def test_different_prompt_is_not_exported_as_model_only(self):
        sources = self.sources()
        sources["candidate-receipt.json"]["job"]["publicSpec"]["promptContract"] = "concise-json-v1"
        with self.assertRaisesRegex(ValueError, "controls differ"):
            self.export(sources)

    def test_incomplete_requests_or_different_cost_cannot_be_exported(self):
        for mutation in ("cost", "turn"):
            with self.subTest(mutation=mutation):
                sources = self.sources()
                job = sources["candidate-receipt.json"]["job"]
                if mutation == "cost":
                    job["result"]["cost"]["estimatedCostUsd"] = 0.001
                else:
                    job["sessions"].pop()
                with self.assertRaisesRegex(ValueError, "cost totals differ|request or usage"):
                    self.export(sources)

    def test_source_drift_cannot_silently_rebind_fixture_hash(self):
        sources = self.sources()
        sources["source-hashes.json"][exporter.CODE_FILES[0]] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.export(sources)

    def test_current_ledger_preserves_the_pi_receipt_and_the_separate_cli_pair(self):
        ledger = json.loads((ROOT / "eval/interview-metrics/agent-experiments.v1.json").read_text())
        rows = {e["id"]: e for e in ledger["experiments"]}
        current = rows[EXPERIMENT_ID]
        for label in ("baseline", "candidate"):
            self.assertEqual(current[label]["evidenceRefs"], [REF])
            self.assertEqual(current[label]["metrics"]["apiCostUsd"], float(self.receipt[label]["estimatedCostUsd"]))
            self.assertEqual(current[label]["metrics"]["requestCount"], self.receipt[label]["runtimeRequestCount"])
            self.assertEqual(current[label]["metrics"]["currentAtomCount"], self.receipt[label]["metrics"]["curation"]["currentAtomCount"])
        self.assertEqual(current["dataset"]["manifestSha256"], self.receipt["fixture"]["sha256"])
        old = rows["memory.maintenance-luna-model-only-r1.v1"]
        self.assertEqual(old["baseline"]["metrics"]["apiCostUsd"], 0.269115)
        self.assertEqual(old["candidate"]["metrics"]["apiCostUsd"], 0.0107502)
        self.assertIn("concise-json-v1", old["frozenControls"][0]["value"])
        self.assertNotEqual(current["dataset"]["manifestSha256"], old["dataset"]["manifestSha256"])


if __name__ == "__main__":
    unittest.main()
