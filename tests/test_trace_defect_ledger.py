from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "eval" / "interview-metrics" / "trace-defect-ledger.v1.json"


class TraceDefectLedgerTests(unittest.TestCase):
    def test_summary_is_recomputed_from_unique_issue_rows(self) -> None:
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))
        defects = payload["defects"]
        ids = [item["id"] for item in defects]
        headline = [item for item in defects if item["headlineEligible"]]
        source_only = [item for item in defects if item["evidenceClass"] == "source_test_only"]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(11, len(headline))
        self.assertEqual(
            3,
            sum(item["evidenceClass"] == "main_repository_validation" for item in headline),
        )
        self.assertEqual(
            8,
            sum(item["evidenceClass"] == "source_local_candidate" for item in headline),
        )
        self.assertEqual(5, len(source_only))
        self.assertEqual(11, payload["summary"]["closedLoopDefects"])
        self.assertEqual(5, payload["summary"]["additionalSourceTestOnlyRepairs"])

    def test_skill_workflow_and_tool_counts_are_not_derived_from_attempts_or_tests(self) -> None:
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))

        self.assertTrue(payload["countingPolicy"]["attemptsAreNotDefects"])
        self.assertTrue(payload["countingPolicy"]["testsAreNotDefects"])
        self.assertTrue(payload["countingPolicy"]["overlappingCategoriesMayNotBeSummed"])
        self.assertEqual(3, len(payload["skillIssues"]))
        self.assertEqual(2, sum(item["status"] == "structurally_fixed" for item in payload["skillIssues"]))
        self.assertEqual(1, sum(item["status"] == "diagnosed_only" for item in payload["skillIssues"]))
        self.assertEqual(6, len(payload["workflowImprovements"]))
        self.assertEqual(9, len(payload["toolRuntimeContractImprovements"]))

    def test_every_counted_defect_has_existing_evidence(self) -> None:
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))

        for defect in payload["defects"]:
            self.assertTrue(defect["evidenceRefs"], defect["id"])
            for reference in defect["evidenceRefs"]:
                self.assertTrue((ROOT / reference).exists(), f"{defect['id']}: {reference}")


if __name__ == "__main__":
    unittest.main()
