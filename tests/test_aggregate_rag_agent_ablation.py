from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.aggregate_rag_agent_ablation import _sha256_json, aggregate_reports


class AggregateRagAgentAblationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_aggregates_disjoint_answer_only_validation_batches_by_metric_denominator(
        self,
    ) -> None:
        first = self._write_report(
            "first.json",
            case_ids=["q-1", "q-2", "q-3"],
            denominators={
                "answerableCitationCases": 2,
                "highLevelCases": 2,
                "infoNotFoundCases": 1,
                "protocolCases": 3,
                "highLevelFacts": 4,
                "citationFacts": 2,
            },
            baseline_metrics=self._metrics(fact=0.5, support=0.5, abstention=1.0),
            agentic_metrics=self._metrics(fact=1.0, support=1.0, abstention=1.0),
        )
        second = self._write_report(
            "second.json",
            case_ids=["q-4", "q-5", "q-6"],
            denominators={
                "answerableCitationCases": 1,
                "highLevelCases": 1,
                "infoNotFoundCases": 2,
                "protocolCases": 3,
                "highLevelFacts": 1,
                "citationFacts": 3,
            },
            baseline_metrics=self._metrics(
                fact=1.0,
                citation_fact=0.0,
                support=0.0,
                abstention=0.5,
            ),
            agentic_metrics=self._metrics(fact=1.0, support=1.0, abstention=1.0),
        )

        report = aggregate_reports([first, second])

        self.assertTrue(report["passed"])
        self.assertTrue(report["scoreEligible"])
        self.assertFalse(report["formalAcceptanceEligible"])
        self.assertFalse(report["formalAcceptancePassed"])
        self.assertEqual("answer-only", report["mode"])
        self.assertEqual("validation", report["split"])
        self.assertEqual(2, report["batchCount"])
        self.assertEqual(6, report["caseCount"])
        lanes = {item["lane"]: item for item in report["lanes"]}
        baseline = lanes["baseline"]
        self.assertAlmostEqual(3 / 5, baseline["agentMetrics"]["highLevelFactCoverage"])
        self.assertAlmostEqual(1 / 5, baseline["agentMetrics"]["citationFactCoverage"])
        self.assertAlmostEqual(
            1 / 3,
            baseline["agentMetrics"]["answerableCitationSupportRate"],
        )
        self.assertAlmostEqual(
            2 / 3,
            baseline["agentMetrics"]["infoNotFoundAbstentionRecall"],
        )
        self.assertEqual(
            {
                "answerableCitationCases": 3,
                "highLevelCases": 3,
                "infoNotFoundCases": 3,
                "protocolCases": 6,
                "highLevelFacts": 5,
                "citationFacts": 5,
            },
            baseline["metricDenominators"],
        )
        self.assertTrue(baseline["retrievalMetrics"]["notApplicable"])
        self.assertTrue(baseline["knowledgeMetrics"]["notApplicable"])
        self.assertTrue(
            report["comparisons"]["baselineToAgentic"]["knowledge"][
                "notApplicable"
            ]
        )
        self.assertTrue(report["retrievalAblation"]["notApplicable"])
        self.assertTrue(report["knowledgeAblation"]["notApplicable"])
        comparison = report["comparisons"]["baselineToAgentic"]["agent"]
        self.assertGreater(
            comparison["answerableCitationSupportRate"]["absoluteDelta"], 0
        )
        unsigned = {
            key: value for key, value in report.items() if key != "reportSha256"
        }
        self.assertEqual(_sha256_json(unsigned), report["reportSha256"])

    def test_zero_info_not_found_denominator_is_not_treated_as_one(self) -> None:
        no_abstention_denominator = {
            "answerableCitationCases": 2,
            "highLevelCases": 2,
            "infoNotFoundCases": 0,
            "protocolCases": 2,
            "highLevelFacts": 2,
            "citationFacts": 2,
        }
        first = self._write_report(
            "first.json",
            case_ids=["q-1", "q-2"],
            denominators=no_abstention_denominator,
            baseline_metrics=self._metrics(fact=0.5, support=0.5, abstention=0.0),
        )
        second = self._write_report(
            "second.json",
            case_ids=["q-3", "q-4"],
            denominators={
                "answerableCitationCases": 1,
                "highLevelCases": 1,
                "infoNotFoundCases": 1,
                "protocolCases": 2,
                "highLevelFacts": 1,
                "citationFacts": 1,
            },
            baseline_metrics=self._metrics(fact=1.0, support=1.0, abstention=0.5),
        )

        report = aggregate_reports([first, second])

        baseline = next(item for item in report["lanes"] if item["lane"] == "baseline")
        self.assertEqual(1, baseline["metricDenominators"]["infoNotFoundCases"])
        self.assertEqual(
            0.5, baseline["agentMetrics"]["infoNotFoundAbstentionRecall"]
        )

    def test_all_zero_metric_denominators_emit_noncomparable_agent_metric(self) -> None:
        denominators = {
            "answerableCitationCases": 2,
            "highLevelCases": 2,
            "infoNotFoundCases": 0,
            "protocolCases": 2,
            "highLevelFacts": 2,
            "citationFacts": 2,
        }
        first = self._write_report(
            "first.json", case_ids=["q-1", "q-2"], denominators=denominators
        )
        second = self._write_report(
            "second.json", case_ids=["q-3", "q-4"], denominators=denominators
        )

        report = aggregate_reports([first, second])

        baseline = next(item for item in report["lanes"] if item["lane"] == "baseline")
        self.assertIsNone(baseline["agentMetrics"]["infoNotFoundAbstentionRecall"])
        self.assertTrue(
            report["comparisons"]["baselineToAgentic"]["agent"][
                "infoNotFoundAbstentionRecall"
            ]["notApplicable"]
        )

    def test_rejects_overlapping_validation_cases(self) -> None:
        first = self._write_report("first.json", case_ids=["q-1", "q-2"])
        second = self._write_report("second.json", case_ids=["q-2", "q-3"])

        with self.assertRaisesRegex(ValueError, "overlap"):
            aggregate_reports([first, second])

    def test_rejects_formal_or_held_out_reports(self) -> None:
        first = self._write_report("first.json", case_ids=["q-1", "q-2"])
        held_out = self._write_report(
            "held-out.json", case_ids=["q-3", "q-4"], split="held_out"
        )
        with self.assertRaisesRegex(ValueError, "answer-only validation"):
            aggregate_reports([first, held_out])

        formal = self._write_report(
            "formal.json", case_ids=["q-3", "q-4"], formal=True
        )
        with self.assertRaisesRegex(ValueError, "formal"):
            aggregate_reports([first, formal])

    def test_rejects_condition_identity_and_failed_batch_drift(self) -> None:
        first = self._write_report("first.json", case_ids=["q-1", "q-2"])
        changes = (
            ("model", "different/model"),
            ("prompt_config_sha256", "prompt-v2"),
            ("answer_case_set_sha256", "answer-suite-v2"),
            ("runtime_revision", "runtime-v2"),
            ("default_config_sha256", "default-config-v2"),
        )
        for index, (key, value) in enumerate(changes, start=1):
            with self.subTest(key=key):
                drifted = self._write_report(
                    f"drifted-{index}.json",
                    case_ids=["q-3", "q-4"],
                    **{key: value},
                )
                with self.assertRaisesRegex(ValueError, "conditions differ"):
                    aggregate_reports([first, drifted])

        failed = self._write_report(
            "failed.json", case_ids=["q-3", "q-4"], passed=False
        )
        with self.assertRaisesRegex(ValueError, "did not pass"):
            aggregate_reports([first, failed])

    def test_rejects_lane_metric_denominator_drift(self) -> None:
        first = self._write_report("first.json", case_ids=["q-1", "q-2"])
        drifted = self._write_report(
            "drifted.json",
            case_ids=["q-3", "q-4"],
            denominator_drift_lane="agentic",
        )

        with self.assertRaisesRegex(ValueError, "denominators differ"):
            aggregate_reports([first, drifted])

    @staticmethod
    def _metrics(
        *,
        fact: float,
        support: float,
        abstention: float,
        citation_fact: float | None = None,
    ) -> dict[str, float]:
        return {
            "highLevelFactCoverage": fact,
            "citationFactCoverage": (
                fact if citation_fact is None else citation_fact
            ),
            "answerableCitationSupportRate": support,
            "citationSuccessRate": support,
            "infoNotFoundAbstentionRecall": abstention,
        }

    def _write_report(
        self,
        name: str,
        *,
        case_ids: list[str],
        denominators: dict[str, int] | None = None,
        baseline_metrics: dict[str, float] | None = None,
        agentic_metrics: dict[str, float] | None = None,
        model: str = "openai-codex/gpt-5.6-sol",
        prompt_config_sha256: str = "prompt-v1",
        answer_case_set_sha256: str = "answer-suite-v1",
        runtime_revision: str = "runtime-v1",
        default_config_sha256: str = "default-config-v1",
        split: str = "validation",
        formal: bool = False,
        passed: bool = True,
        denominator_drift_lane: str = "",
    ) -> Path:
        if denominators is None:
            denominators = {
                "answerableCitationCases": len(case_ids) - 1,
                "highLevelCases": len(case_ids) - 1,
                "infoNotFoundCases": 1,
                "protocolCases": len(case_ids),
                "highLevelFacts": len(case_ids) - 1,
                "citationFacts": len(case_ids) - 1,
            }
        baseline_metrics = baseline_metrics or self._metrics(
            fact=0.5, support=0.5, abstention=1.0
        )
        agentic_metrics = agentic_metrics or self._metrics(
            fact=1.0, support=1.0, abstention=1.0
        )
        selected_case_set_sha256 = _sha256_json(
            [{"queryId": case_id} for case_id in case_ids]
        )
        manifest_sha256 = _sha256_json(
            {
                "answerCaseSetSha256": answer_case_set_sha256,
                "selectedCaseSetSha256": selected_case_set_sha256,
            }
        )
        pi_runtime = {
            "sourceAccess": "explicit-verified-payload-v1",
            "sourceRevision": runtime_revision,
        }
        agent_config = {
            "modelRouteIdentitySha256": "model-routes-v1",
            "settingsSha256": "agent-settings-v1",
        }
        lane_metrics = {
            "baseline": baseline_metrics,
            "skill": baseline_metrics,
            "tuned": agentic_metrics,
            "agentic": agentic_metrics,
        }
        lanes = []
        for lane in ("baseline", "skill", "tuned", "agentic"):
            lane_denominators = dict(denominators)
            if lane == denominator_drift_lane:
                lane_denominators["highLevelFacts"] += 1
            lanes.append(
                {
                    "lane": lane,
                    "retrievalConfigSha256": (
                        default_config_sha256
                        if lane in {"baseline", "skill"}
                        else "tuned-config-v1"
                    ),
                    "hardGates": {"contract": True, "cleanup": True},
                    "costs": {
                        "elapsedMs": 100.0,
                        "inputTokens": 1_000.0,
                        "outputTokens": 100.0,
                        "toolCalls": 5.0,
                    },
                    "score": {
                        "schemaVersion": "rag-ime.rag-answer-only-lane-score.v1",
                        "caseCount": len(case_ids),
                        "agentMetrics": dict(lane_metrics[lane]),
                        "metricDenominators": lane_denominators,
                        "answerCases": [],
                    },
                }
            )
        conditions = {
            "benchmarkId": "benchmark-v1",
            "model": model,
            "thinking": "max",
            "laneTimeoutSeconds": 600.0,
            "datasetSplitSha256": _sha256_json(case_ids),
            "caseIdsSha256": _sha256_json(case_ids),
            "permissionSha256": "permissions-v1",
            "denominator": len(case_ids),
            "evaluationMode": "answer-only",
            "evaluationSplit": split,
            "promptConfigSha256": prompt_config_sha256,
            "answerCaseManifestSha256": manifest_sha256,
            "answerCaseSetSha256": answer_case_set_sha256,
            "selectedAnswerCaseSetSha256": selected_case_set_sha256,
            "promptContractVersion": "rag-agent-case-scoped-citations-v6",
            "skillName": "rag-retrieval-optimization",
            "skillSha256": "skill-v1",
            "piRuntime": pi_runtime,
            "agentConfig": agent_config,
            "toolTransport": "sse",
            "calibrationProfile": "none",
            "citationReferencePolicy": {"resolution": "exact-only"},
            "runtimeContractSha256": "runtime-contract-v1",
            "runtimeRetryPolicy": {"maximumAttemptsPerLane": 2},
            "agenticRetrievalPolicy": {"maxSearchesPerCase": 2},
            "answerEvaluationPolicy": {"metricBasedRetry": False},
        }
        report = {
            "schemaVersion": "rag-ime.rag-agent-ablation-run.v1",
            "passed": passed,
            "formalAcceptanceEligible": formal,
            "formalAcceptancePassed": formal,
            "acceptanceStatus": (
                "formal-held-out-accepted"
                if formal
                else "validation-accepted-not-formal"
            ),
            "localOnly": True,
            "uploaded": False,
            "cleanupPassed": True,
            "startedAtMs": 1_000,
            "completedAtMs": 2_000,
            "elapsedMs": 1_000,
            "sourcePreparedSha256": "prepared-v1",
            "sourceRetrievalReportSha256": "retrieval-report-v1",
            "sourceAnswerCasesSha256": "answer-cases-v1",
            "defaultRetrievalConfigSha256": default_config_sha256,
            "tunedRetrievalConfigSha256": "tuned-config-v1",
            "dataset": {"benchmarkId": "benchmark-v1", "sourceSha256": "dataset-v1"},
            "answerCaseManifest": {
                "manifestSha256": manifest_sha256,
                "answerCaseSetSha256": answer_case_set_sha256,
                "selectedCaseSetSha256": selected_case_set_sha256,
            },
            "embedding": {"fingerprint": "embedding-v1"},
            "reranker": {"fingerprint": "reranker-v1"},
            "conditions": conditions,
            "agentConfig": agent_config,
            "evaluation": {
                "mode": "answer-only",
                "split": split,
                "caseCount": len(case_ids),
                "caseIds": case_ids,
                "caseIdsSha256": _sha256_json(case_ids),
                "caseSetSha256": selected_case_set_sha256,
                "answerCaseManifestSha256": manifest_sha256,
                "answerCaseSetSha256": answer_case_set_sha256,
                "promptConfigSha256": prompt_config_sha256,
                "formalAcceptanceEligible": formal,
                "selectionSeed": "fixed-seed",
            },
            "knowledgeAblation": {
                "accepted": True,
                "notApplicable": True,
                "reason": "answer-only cases have no retrieval qrels denominator",
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
