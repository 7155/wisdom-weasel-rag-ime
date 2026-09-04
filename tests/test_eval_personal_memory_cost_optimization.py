from __future__ import annotations

import json
import unittest

from scripts.eval_personal_memory_luna import (
    _codex_jsonl_usage,
    _memory_cost_optimization_comparison,
)


class PersonalMemoryCostOptimizationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
