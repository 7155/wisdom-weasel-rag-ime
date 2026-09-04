from __future__ import annotations

import json
import unittest

from scripts.eval_personal_memory_luna import (
    _memory_model_only_comparison,
    _memory_model_only_preflight,
    _codex_jsonl_usage,
    _memory_cost_optimization_comparison,
    build_parser,
)


class PersonalMemoryCostOptimizationTests(unittest.TestCase):
    @staticmethod
    def _model_only_report(model: str) -> dict[str, object]:
        return {
            "schemaVersion": "paw.memory-maintenance-validation-receipt.v1",
            "runId": f"memory:{model}",
            "status": "passed",
            "evaluationScope": "validation-only",
            "provider": "openai-codex",
            "model": model,
            "thinking": "max",
            "transport": "codex_cli_ephemeral",
            "contextProfile": "full-json-v1",
            "promptContract": "concise-json-v1",
            "metrics": {
                "fixture": {
                    "caseCount": 5,
                    "durableCaseCount": 4,
                    "nonMemoryCaseCount": 1,
                    "allStored": True,
                    "allCandidateEvidence": True,
                },
                "curation": {
                    "ok": True,
                    "sourceCount": 5,
                    "modelDecisionCount": 5,
                    "currentAtomCount": 7,
                    "governedCurrentAtomCount": 7,
                    "legalLineageCurrentAtomCount": 7,
                    "bookProjectionInSync": True,
                },
                "retrieval": {
                    "caseCount": 5,
                    "durableCaseCount": 4,
                    "passed": True,
                    "allCasesPassed": True,
                    "vectorCoverage": 1.0,
                },
                "recovery": {
                    "rollbackPassed": True,
                    "replayPassed": True,
                    "replayRagPassed": True,
                    "replayAtomSetStable": True,
                },
            },
            "hardGates": {
                "privateShadow": True,
                "sourceShadowUnchanged": True,
                "rollbackVerified": True,
                "replayVerified": True,
                "productionDatabaseOpened": False,
                "productionMutationPerformed": False,
            },
            "evidence": {"syntheticFixtureSha256": "a" * 64},
            "modelRequests": [
                {
                    "phase": "atom-first-curation",
                    "model": model,
                    "thinking": "max",
                    "exitCode": 0,
                    "isolated": False,
                    "resumed": False,
                    "contextProfile": "full-json-v1",
                    "frozenInputSha256": "b" * 64,
                    "semanticPacketSha256": "c" * 64,
                    "sourcePacketChars": 1_944,
                    "projectedPacketChars": 1_944,
                    "schemaSha256": "d" * 64,
                },
                {
                    "phase": "atom-first-verifier",
                    "model": model,
                    "thinking": "max",
                    "exitCode": 0,
                    "isolated": True,
                    "resumed": False,
                    "contextProfile": "full-json-v1",
                    "frozenInputSha256": "b" * 64,
                    "semanticPacketSha256": ("e" if model == "gpt-5.6-sol" else "f") * 64,
                    "sourcePacketChars": 3_745,
                    "projectedPacketChars": 3_745,
                    "schemaSha256": "1" * 64,
                },
            ],
        }

    def test_codex_jsonl_usage_projects_uncached_cached_and_output(self) -> None:
        stdout = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 120,
                            "cached_input_tokens": 80,
                            "cache_write_input_tokens": 0,
                            "output_tokens": 12,
                        },
                    }
                ),
            )
        )

        self.assertEqual(
            {
                "available": True,
                "inputTokens": 120,
                "uncachedInputTokens": 40,
                "cachedInputTokens": 80,
                "cacheWriteInputTokens": 0,
                "outputTokens": 12,
            },
            _codex_jsonl_usage(stdout),
        )
        self.assertEqual({"available": False}, _codex_jsonl_usage("not-json"))

    def test_memory_cost_comparison_fails_closed_on_quality_or_usage_regression(self) -> None:
        gates = {
            "metrics": {
                "fixture": {"caseCount": 5, "durableCaseCount": 4, "nonMemoryCaseCount": 1, "allStored": True, "allCandidateEvidence": True},
                "curation": {
                    "ok": True,
                    "sourceCount": 5,
                    "modelDecisionCount": 5,
                    "currentAtomCount": 6,
                    "governedCurrentAtomCount": 6,
                    "legalLineageCurrentAtomCount": 6,
                    "bookProjectionInSync": True,
                },
                "retrieval": {"caseCount": 5, "durableCaseCount": 4, "passed": True, "allCasesPassed": True, "vectorCoverage": 1.0},
                "recovery": {"rollbackPassed": True, "replayPassed": True, "replayRagPassed": True, "replayAtomSetStable": True},
            },
            "hardGates": {"privateShadow": True, "sourceShadowUnchanged": True, "rollbackVerified": True, "replayVerified": True, "productionDatabaseOpened": False, "productionMutationPerformed": False},
        }
        baseline = {
            **gates,
            "model": "gpt-5.6-sol",
            "status": "passed",
            "thinking": "max",
            "evaluationScope": "validation-only",
            "contextProfile": "full-json-v1",
            "evidence": {"syntheticFixtureSha256": "a" * 64},
            "usage": {"available": True, "uncachedInputTokens": 100, "cachedInputTokens": 20, "outputTokens": 30},
        }
        candidate = {
            **baseline,
            "contextProfile": "compact-json-v1",
            "usage": {"available": True, "uncachedInputTokens": 90, "cachedInputTokens": 20, "outputTokens": 30},
        }

        self.assertEqual(
            "keep",
            _memory_cost_optimization_comparison(baseline, candidate)["decision"],
        )
        prompt_candidate = {
            **baseline,
            "promptContract": "concise-json-v1",
            "usage": {"available": True, "uncachedInputTokens": 95, "cachedInputTokens": 20, "outputTokens": 25},
        }
        prompt_comparison = _memory_cost_optimization_comparison(
            baseline,
            prompt_candidate,
        )
        self.assertEqual("keep", prompt_comparison["decision"])
        self.assertEqual("concise_json_prompt_contract", prompt_comparison["singleVariable"])
        two_factor_candidate = {
            **prompt_candidate,
            "contextProfile": "compact-json-v1",
        }
        self.assertEqual(
            "reject",
            _memory_cost_optimization_comparison(baseline, two_factor_candidate)["decision"],
        )
        regressed = {
            **candidate,
            "metrics": {**candidate["metrics"], "retrieval": {**candidate["metrics"]["retrieval"], "allCasesPassed": False}},
        }
        self.assertEqual(
            "reject",
            _memory_cost_optimization_comparison(baseline, regressed)["decision"],
        )
        missing = {**candidate, "usage": {"available": False}}
        self.assertEqual(
            "reject",
            _memory_cost_optimization_comparison(baseline, missing)["decision"],
        )

    def test_model_only_lane_freezes_selected_sol_contract_and_changes_only_model(self) -> None:
        baseline = self._model_only_report("gpt-5.6-sol")
        candidate = self._model_only_report("gpt-5.6-luna")

        preflight = _memory_model_only_preflight(
            baseline,
            model="gpt-5.6-luna",
            context_profile="full-json-v1",
            prompt_contract="concise-json-v1",
        )
        comparison = _memory_model_only_comparison(baseline, candidate)

        self.assertTrue(preflight["passed"], preflight)
        self.assertEqual("no_prompt_adaptation", comparison["decision"])
        self.assertTrue(comparison["singleFactorGatePassed"])
        self.assertFalse(comparison["promptAdaptationNeeded"])
        factors = {item["name"]: item for item in comparison["factorTable"]}
        self.assertEqual("changed", factors["model"]["mode"])
        self.assertTrue(factors["model"]["passed"])
        self.assertTrue(factors["promptContract"]["passed"])
        hashes = {item["name"]: item for item in comparison["hashTable"]}
        self.assertTrue(hashes["contractFingerprint"]["matched"])
        self.assertTrue(hashes["curationSemanticPacket"]["matched"])
        self.assertNotIn("verifierSemanticPacket", hashes)

        drifted = {
            **candidate,
            "promptContract": "standard-v1",
        }
        rejected = _memory_model_only_comparison(baseline, drifted)
        self.assertEqual("invalid_model_only_lane", rejected["decision"])
        self.assertFalse(rejected["singleFactorGatePassed"])
        self.assertFalse(rejected["promptAdaptationNeeded"])

    def test_model_only_quality_failure_allows_one_prompt_adaptation_stage(self) -> None:
        baseline = self._model_only_report("gpt-5.6-sol")
        candidate = self._model_only_report("gpt-5.6-luna")
        candidate = {
            **candidate,
            "status": "iterate",
            "metrics": {
                **candidate["metrics"],
                "retrieval": {
                    **candidate["metrics"]["retrieval"],
                    "allCasesPassed": False,
                },
            },
        }

        comparison = _memory_model_only_comparison(baseline, candidate)

        self.assertEqual("adapt_prompt", comparison["decision"])
        self.assertTrue(comparison["singleFactorGatePassed"])
        self.assertTrue(comparison["operabilityGatePassed"])
        self.assertFalse(comparison["qualityGatePassed"])
        self.assertTrue(comparison["promptAdaptationNeeded"])
        self.assertEqual(
            "one_general_prompt_contract",
            comparison["allowedNextStage"],
        )

    def test_model_only_recovery_failure_is_not_mislabeled_as_prompt_failure(self) -> None:
        baseline = self._model_only_report("gpt-5.6-sol")
        candidate = self._model_only_report("gpt-5.6-luna")
        candidate = {
            **candidate,
            "status": "iterate",
            "metrics": {
                **candidate["metrics"],
                "retrieval": {
                    **candidate["metrics"]["retrieval"],
                    "vectorCoverage": 0.0,
                },
                "recovery": {
                    **candidate["metrics"]["recovery"],
                    "replayPassed": False,
                },
            },
            "hardGates": {
                **candidate["hardGates"],
                "replayVerified": False,
            },
        }

        comparison = _memory_model_only_comparison(baseline, candidate)

        self.assertEqual("repair_evaluation_harness", comparison["decision"])
        self.assertTrue(comparison["semanticQualityGatePassed"])
        self.assertFalse(comparison["recoveryGatePassed"])
        self.assertFalse(comparison["promptAdaptationNeeded"])
        self.assertEqual("evaluation_harness", comparison["failureOwner"])

    def test_parser_exposes_explicit_model_only_sol_baseline(self) -> None:
        args = build_parser().parse_args(
            [
                "--shadow-db",
                "/tmp/shadow.sqlite",
                "--private-dir",
                "/tmp/private",
                "--model-only-baseline-report",
                "/tmp/selected-sol.json",
            ]
        )

        self.assertEqual("/tmp/selected-sol.json", str(args.model_only_baseline_report))


if __name__ == "__main__":
    unittest.main()
