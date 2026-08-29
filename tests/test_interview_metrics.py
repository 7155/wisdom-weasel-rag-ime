from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.check_interview_metrics import validate_interview_metrics


class InterviewMetricsLedgerTests(unittest.TestCase):
    def test_repository_ledger_is_valid_and_keeps_non_green_runs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger_path = root / "eval" / "interview-metrics" / "evidence-ledger.v1.json"
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))

        errors = validate_interview_metrics(payload, repo_root=root)

        self.assertEqual(errors, [])
        run_outcomes = {run["outcome"] for run in payload["runs"]}
        self.assertIn("failed", run_outcomes)
        self.assertIn("interrupted", run_outcomes)
        self.assertGreaterEqual(len(payload["metrics"]), 8)
        self.assertTrue(any(item["domain"] == "memory" for item in payload["datasets"]))
        self.assertTrue(any(item["domain"] == "knowledge" for item in payload["datasets"]))

    def test_claimable_metric_requires_sample_command_and_claim_boundaries(self) -> None:
        payload = {
            "schemaVersion": "paw.interview-metrics-ledger.v1",
            "sourceRevision": "abc",
            "evidenceLevels": ["E1", "E2", "E3", "E4", "E5", "E6"],
            "metrics": [
                {
                    "id": "metric.bad",
                    "domain": "knowledge",
                    "status": "headline",
                    "evidenceLevel": "E3",
                    "measurementKind": "deterministic",
                    "values": {"mrr": 0.9},
                    "sample": {},
                    "reproduction": {"command": ""},
                    "evidenceRefs": [],
                    "claim": {"allowed": "", "forbidden": ""},
                    "limitations": [],
                }
            ],
            "runs": [],
            "datasets": [],
        }

        errors = validate_interview_metrics(payload)

        self.assertIn("metric.bad: sample.count must be a positive integer", errors)
        self.assertIn("metric.bad: reproduction.command is required", errors)
        self.assertIn("metric.bad: evidenceRefs must be non-empty", errors)
        self.assertIn("metric.bad: claim.allowed is required", errors)
        self.assertIn("metric.bad: claim.forbidden is required", errors)

    def test_ai_estimate_cannot_be_labeled_deterministic(self) -> None:
        payload = {
            "schemaVersion": "paw.interview-metrics-ledger.v1",
            "sourceRevision": "abc",
            "evidenceLevels": ["E1", "E2", "E3", "E4", "E5", "E6"],
            "metrics": [
                {
                    "id": "metric.judge",
                    "domain": "trace-eval",
                    "status": "diagnostic",
                    "evidenceLevel": "E2",
                    "measurementKind": "ai_estimate",
                    "values": {"quality": 0.8},
                    "sample": {"count": 10, "unit": "traces"},
                    "reproduction": {"command": "manual judge"},
                    "evidenceRefs": ["https://example.invalid/judge"],
                    "claim": {"allowed": "Judge estimate", "forbidden": "ground truth"},
                    "limitations": ["model-dependent"],
                    "reportedAs": "deterministic",
                }
            ],
            "runs": [],
            "datasets": [],
        }

        errors = validate_interview_metrics(payload)

        self.assertIn(
            "metric.judge: ai_estimate must not be reportedAs deterministic",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
