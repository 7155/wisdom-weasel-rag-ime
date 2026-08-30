from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_interview_metrics import (
    validate_interview_metrics,
    validate_metric_receipt_calculation,
)


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

    def test_workspace_speedup_receipts_reject_a_drifted_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = []
            for name, files, speedup in (
                ("workspace-1000-a.json", 1_000, 2.2),
                ("workspace-1000-b.json", 1_000, 3.0),
                ("workspace-5000-a.json", 5_000, 4.1),
                ("workspace-5000-b.json", 5_000, 7.2),
            ):
                path = root / name
                path.write_text(
                    json.dumps(
                        {
                            "schemaVersion": "paw.workspace-tool-benchmark.v1",
                            "case": {
                                "files": files,
                                "corpusSha256": f"corpus-{files}",
                            },
                            "parity": True,
                            "p95Speedup": speedup,
                            "backends": [
                                {
                                    "result": {
                                        "checksumSha256": f"result-{files}",
                                    }
                                },
                                {
                                    "result": {
                                        "checksumSha256": f"result-{files}",
                                    }
                                },
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                receipts.append(name)
            metric = {
                "id": "metric.workspace",
                "values": {
                    "files1000": {
                        "runCount": 2,
                        "p95SpeedupMin": 2.14,
                        "p95SpeedupMax": 3.0,
                        "checksumParity": True,
                    },
                    "files5000": {
                        "runCount": 2,
                        "p95SpeedupMin": 4.1,
                        "p95SpeedupMax": 7.2,
                        "checksumParity": True,
                    },
                },
                "receiptCalculation": {
                    "kind": "workspace_speedup_range",
                    "refs": receipts,
                },
            }

            errors = validate_metric_receipt_calculation(metric, repo_root=root)

        self.assertIn(
            "metric.workspace: files1000.p95SpeedupMin must equal receipt-derived 2.2, got 2.14",
            errors,
        )

    def test_context_cache_receipt_recomputes_uncached_input_reduction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "cache.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.pi-context-cache-canary.v1",
                        "status": "passed_not_installed",
                        "stableTurns": [
                            {"inputTokens": 10_647, "cacheReadTokens": 0},
                            {"inputTokens": 941, "cacheReadTokens": 9_728},
                            {"inputTokens": 963, "cacheReadTokens": 9_728},
                        ],
                        "changedPrefixControl": {
                            "inputTokens": 10_650,
                            "cacheReadTokens": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            metric = {
                "id": "metric.cache",
                "values": {
                    "stableTurns": 3,
                    "warmHitTurns": 2,
                    "coldInputTokens": 10_647,
                    "warmInputTokensMin": 941,
                    "warmInputTokensMax": 963,
                    "stableCacheReadTokens": 9_728,
                    "uncachedInputReductionPercentMin": 90.96,
                    "uncachedInputReductionPercentMax": 91.16,
                    "changedPrefixControlCacheReadTokens": 0,
                },
                "receiptCalculation": {
                    "kind": "pi_context_cache",
                    "refs": ["cache.json"],
                },
            }

            errors = validate_metric_receipt_calculation(metric, repo_root=root)

        self.assertEqual(errors, [])

    def test_receipt_calculation_cannot_be_an_empty_silent_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            errors = validate_metric_receipt_calculation(
                {
                    "id": "metric.empty",
                    "values": {},
                    "receiptCalculation": {},
                },
                repo_root=Path(temporary),
            )

        self.assertEqual(
            errors,
            ["metric.empty: receiptCalculation must be a non-empty object"],
        )


if __name__ == "__main__":
    unittest.main()
