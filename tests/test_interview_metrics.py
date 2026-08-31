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

    def test_rag_validation_receipt_recomputes_selection_without_opening_held_out(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "rag-validation.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schemaVersion": "paw.enterprise-rag-validation-receipt.v1",
                        "status": "evaluated_not_promoted",
                        "evaluationScope": "validation-only",
                        "heldOutEvaluated": False,
                        "objective": "ndcgAtK.10",
                        "decision": "candidate_selected_not_promoted",
                        "hardGates": {
                            "heldOutLabelsHiddenDuringSelection": True,
                            "qrelsNotPassedToRetriever": True,
                        },
                        "hashes": {
                            "rawFileSha256": "a" * 64,
                            "reportSha256": "b" * 64,
                            "selectionReceiptSha256": "c" * 64,
                            "validationSplitSha256": "d" * 64,
                            "winnerConfigSha256": "e" * 64,
                        },
                        "sample": {
                            "validationQueryCount": 16,
                            "candidateCount": 14,
                        },
                        "metrics": {
                            "lexicalFloor": {
                                "mrr": 0.6041666667,
                                "ndcgAt10": 0.6128006234,
                                "recallAt10": 0.671875,
                            },
                            "strongNaiveDense": {
                                "mrr": 0.6770833333,
                                "ndcgAt10": 0.6705101784,
                                "recallAt10": 0.7135416667,
                            },
                            "winner": {
                                "mrr": 0.8671875,
                                "ndcgAt10": 0.8872028252,
                                "recallAt10": 0.9553571429,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            metric = {
                "id": "metric.rag-validation",
                "status": "diagnostic",
                "values": {
                    "validationQueryCount": 16,
                    "candidateCount": 14,
                    "winnerConfigSha256": "e" * 64,
                    "lexicalFloor": {
                        "mrr": 0.604167,
                        "ndcgAt10": 0.612801,
                        "recallAt10": 0.671875,
                    },
                    "strongNaiveDense": {
                        "mrr": 0.677083,
                        "ndcgAt10": 0.67051,
                        "recallAt10": 0.713542,
                    },
                    "winner": {
                        "mrr": 0.867188,
                        "ndcgAt10": 0.887203,
                        "recallAt10": 0.955357,
                    },
                },
                "receiptCalculation": {
                    "kind": "rag_validation_selection",
                    "refs": ["rag-validation.json"],
                },
            }

            errors = validate_metric_receipt_calculation(metric, repo_root=root)

            self.assertEqual(errors, [])

            metric["status"] = "headline"
            errors = validate_metric_receipt_calculation(metric, repo_root=root)
            self.assertIn(
                "metric.rag-validation: validation-only receipt cannot support headline status",
                errors,
            )
            metric["status"] = "diagnostic"

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["heldOutEvaluated"] = True
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            errors = validate_metric_receipt_calculation(metric, repo_root=root)

        self.assertIn(
            "metric.rag-validation: validation receipt must not contain held-out evaluation",
            errors,
        )

    def test_rag_agent_reject_receipt_recomputes_recovery_and_cost_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "rag-agent-reject.json"
            receipt.write_text(
                json.dumps(
                    {
                        "schemaVersion": "paw.enterprise-rag-agent-validation-reject.v1",
                        "status": "rejected",
                        "evaluationScope": "validation-only",
                        "evaluationMode": "answer-only",
                        "heldOutEvaluated": False,
                        "decision": "reject",
                        "formalAcceptanceEligible": False,
                        "heldOutGateProduced": False,
                        "cleanupPassed": True,
                        "hashes": {
                            "rawFileSha256": "a" * 64,
                            "reportSha256": "b" * 64,
                            "promotionFileSha256": "c" * 64,
                            "promotionReceiptSha256": "d" * 64,
                            "runtimeContractSha256": "e" * 64,
                            "caseSetSha256": "f" * 64,
                        },
                        "sample": {"answerCaseCount": 4, "laneCount": 4},
                        "resume": {
                            "resumed": True,
                            "reusedLaneCount": 1,
                            "freshLaneCount": 3,
                            "reusedLanePercent": 25.0,
                            "interruptedAttemptCount": 1,
                            "retryAttemptCount": 1,
                            "recoveredOrphanCount": 1,
                            "blockedOrphanCount": 0,
                            "recoveryFailClosed": False,
                        },
                        "comparison": {
                            "fromLane": "baseline",
                            "toLane": "agentic",
                            "latencyMs": {
                                "baseline": 71141.445,
                                "agentic": 242624.393,
                                "increasePercent": 241.05,
                            },
                            "toolCalls": {
                                "baseline": 6,
                                "agentic": 11,
                                "increasePercent": 83.33,
                            },
                            "answerJudgeCorrectnessRate": {
                                "baseline": 0.5,
                                "agentic": 0.0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            metric = {
                "id": "metric.rag-agent-reject",
                "status": "diagnostic",
                "values": {
                    "answerCaseCount": 4,
                    "laneCount": 4,
                    "reusedLaneCount": 1,
                    "reusedLanePercent": 25.0,
                    "recoveredOrphanCount": 1,
                    "blockedOrphanCount": 0,
                    "baselineLatencyMs": 71141.445,
                    "agenticLatencyMs": 242624.393,
                    "agenticLatencyIncreasePercent": 241.05,
                    "baselineToolCalls": 6,
                    "agenticToolCalls": 11,
                    "agenticToolCallIncreasePercent": 83.33,
                    "baselineAnswerJudgeCorrectnessRate": 0.5,
                    "agenticAnswerJudgeCorrectnessRate": 0.0,
                    "decision": "reject",
                },
                "receiptCalculation": {
                    "kind": "rag_agent_validation_reject",
                    "refs": ["rag-agent-reject.json"],
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
