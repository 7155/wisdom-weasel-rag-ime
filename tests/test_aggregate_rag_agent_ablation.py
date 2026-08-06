from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.aggregate_rag_agent_ablation import (
    _sha256_json,
    aggregate_reports,
)


class AggregateRagAgentAblationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_aggregates_disjoint_batches_with_weighted_deltas(self) -> None:
        first = self._write_report(
            "first.json",
            case_ids=["q-1", "q-2"],
            baseline_success=0.25,
            agentic_success=1.0,
        )
        second = self._write_report(
            "second.json",
            case_ids=["q-3", "q-4"],
            baseline_success=0.5,
            agentic_success=0.75,
        )

        report = aggregate_reports([first, second])

        self.assertTrue(report["passed"])
        self.assertEqual(2, report["batchCount"])
        self.assertEqual(4, report["caseCount"])
        lanes = {item["lane"]: item for item in report["lanes"]}
        self.assertAlmostEqual(
            (2 * 0.25 + 2 * 0.5) / 4,
            lanes["baseline"]["agentMetrics"]["agentSuccessRate"],
        )
        self.assertAlmostEqual(
            (2 * 1.0 + 2 * 0.75) / 4,
            lanes["agentic"]["agentMetrics"]["agentSuccessRate"],
        )
        comparison = report["comparisons"]["baselineToAgentic"]["agent"]
        self.assertGreater(comparison["agentSuccessRate"]["absoluteDelta"], 0)
        unsigned = {
            key: value
            for key, value in report.items()
            if key != "reportSha256"
        }
        self.assertEqual(_sha256_json(unsigned), report["reportSha256"])

    def test_rejects_overlapping_held_out_cases(self) -> None:
        first = self._write_report(
            "first.json",
            case_ids=["q-1", "q-2"],
        )
        second = self._write_report(
            "second.json",
            case_ids=["q-2", "q-3"],
        )

        with self.assertRaisesRegex(ValueError, "overlap"):
            aggregate_reports([first, second])

    def test_rejects_condition_drift_and_failed_batches(self) -> None:
        first = self._write_report("first.json", case_ids=["q-1"])
        drifted = self._write_report(
            "drifted.json",
            case_ids=["q-2"],
            model="different/model",
        )
        with self.assertRaisesRegex(ValueError, "conditions differ"):
            aggregate_reports([first, drifted])

        timeout_drifted = self._write_report(
            "timeout-drifted.json",
            case_ids=["q-4"],
            lane_timeout_seconds=720.0,
        )
        with self.assertRaisesRegex(ValueError, "conditions differ"):
            aggregate_reports([first, timeout_drifted])

        episode_size_drifted = self._write_report(
            "episode-size-drifted.json",
            case_ids=["q-6", "q-7"],
        )
        with self.assertRaisesRegex(ValueError, "conditions differ"):
            aggregate_reports([first, episode_size_drifted])

        skill_drifted = self._write_report(
            "skill-drifted.json",
            case_ids=["q-8"],
            skill_sha256="skill-v2",
        )
        with self.assertRaisesRegex(ValueError, "conditions differ"):
            aggregate_reports([first, skill_drifted])

        failed = self._write_report(
            "failed.json",
            case_ids=["q-5"],
            passed=False,
        )
        with self.assertRaisesRegex(ValueError, "did not pass"):
            aggregate_reports([first, failed])

    def _write_report(
        self,
        name: str,
        *,
        case_ids: list[str],
        baseline_success: float = 0.25,
        agentic_success: float = 1.0,
        model: str = "openai-codex/gpt-5.6-luna",
        lane_timeout_seconds: float = 600.0,
        skill_sha256: str = "skill-v1",
        passed: bool = True,
    ) -> Path:
        lane_success = {
            "baseline": baseline_success,
            "skill": min(1.0, baseline_success + 0.25),
            "tuned": min(1.0, agentic_success),
            "agentic": agentic_success,
        }
        lanes = []
        for index, lane in enumerate(("baseline", "skill", "tuned", "agentic")):
            success = lane_success[lane]
            lanes.append(
                {
                    "lane": lane,
                    "retrievalConfigSha256": (
                        "baseline-config" if index < 2 else "tuned-config"
                    ),
                    "hardGates": {"contract": True, "cleanup": True},
                    "costs": {
                        "latencyMs": float(100 + index * 10),
                        "tokens": float(1_000 + index * 100),
                        "toolCalls": float(5 + index),
                    },
                    "score": {
                        "agentMetrics": {
                            "agentSuccessRate": success,
                            "answerCharF1": success,
                            "citationRecall": success,
                        },
                        "retrievalMetrics": {
                            "metrics": {
                                "mrr": success,
                                "recallAtK": {"1": success, "10": success},
                                "ndcgAtK": {"1": success, "10": success},
                            }
                        },
                    },
                }
            )
        report = {
            "schemaVersion": "rag-ime.rag-agent-ablation-run.v1",
            "passed": passed,
            "localOnly": True,
            "uploaded": False,
            "cleanupPassed": True,
            "startedAtMs": 1_000,
            "completedAtMs": 2_000,
            "elapsedMs": 1_000,
            "sourcePreparedSha256": "prepared",
            "sourceRetrievalReportSha256": "retrieval",
            "defaultRetrievalConfigSha256": "baseline-config",
            "tunedRetrievalConfigSha256": "tuned-config",
            "dataset": {
                "sourceSha256": "dataset",
            },
            "embedding": {
                "fingerprint": "embedding",
            },
            "reranker": {
                "fingerprint": "reranker",
            },
            "conditions": {
                "benchmarkId": "benchmark",
                "model": model,
                "thinking": "max",
                "denominator": len(case_ids),
                "promptContractVersion": "rag-agent-case-scoped-citations-v6",
                "skillName": "rag-retrieval-optimization",
                "skillSha256": skill_sha256,
                "runtimeContractSha256": "runtime-contract-v1",
                "citationReferencePolicy": {
                    "scope": "benchmark-run-and-evaluation-case",
                    "format": "K{positiveInteger}",
                    "assignment": "first-observed-source-order",
                    "resolution": "exact-only",
                    "unknownReference": "hard-fail",
                },
                "answerEvaluationPolicy": {
                    "primaryTaskMetric": "answerJudgeCorrectnessRate",
                    "rawCharacterMetricsDiagnosticOnly": True,
                    "judgeModel": "openai-codex/gpt-5.6-luna",
                    "judgeThinking": "max",
                    "judgeContractVersion": "crud-rag-reference-correctness-v1",
                    "anonymousCandidates": True,
                    "referenceAnswerAccessAfterGeneration": True,
                    "retrievalQrelAccess": False,
                    "judgeFeedbackToAgent": False,
                    "metricBasedRetry": False,
                },
                "permissionSha256": "permissions",
                "runtimeRetryPolicy": {
                    "maximumAttemptsPerLane": 2,
                    "metricBasedSelection": False,
                },
                "laneTimeoutSeconds": lane_timeout_seconds,
                "agenticRetrievalPolicy": {
                    "childCount": 2,
                    "childTopK": 3,
                    "parentTopK": 10,
                    "maxSearchesPerCase": 3,
                },
            },
            "evaluation": {
                "caseCount": len(case_ids),
                "caseIds": case_ids,
                "selectionSeed": name,
            },
            "lanes": lanes,
        }
        report["reportSha256"] = _sha256_json(report)
        path = self.root / name
        path.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
