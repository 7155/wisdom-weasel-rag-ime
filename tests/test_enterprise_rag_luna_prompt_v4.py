from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.run_rag_agent_ablation import (
    _LUNA_PROMPT_ONLY_V4_PROFILE,
    _LUNA_PROMPT_ONLY_V4_RULE,
    _lane_prompt,
    _sha256_json,
    _validate_prompt_profile,
)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "runs"
    / "enterprise-rag-answer-evidence-three-stage-preflight-20260904.v4.json"
)
SUPERSEDED_RECEIPT = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "runs"
    / "enterprise-rag-answer-evidence-three-stage-preflight-20260904.v3.json"
)
VALIDATION_RECEIPT = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "runs"
    / "enterprise-rag-answer-evidence-three-stage-validation-20260904.v1.json"
)
AUTH_VALIDATION_RECEIPT = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "runs"
    / "enterprise-rag-answer-evidence-three-stage-validation-20260904.v2.json"
)


class EnterpriseRagLunaPromptV4Tests(unittest.TestCase):
    def _prompt(
        self,
        *,
        lane: str = "agentic",
        prompt_profile: str = "incumbent",
    ) -> str:
        return _lane_prompt(
            lane=lane,
            run_id="",
            cases=[
                {
                    "evaluationCaseId": "opaque-evaluation-alias",
                    "queryId": "private-query-id",
                    "query": "Which requested values are directly supported?",
                    "answer": "PRIVATE REFERENCE ANSWER",
                    "answerFacts": ["PRIVATE GOLD FACT"],
                }
            ],
            retrieval_config={
                "mode": "hybrid",
                "topK": 10,
                "threshold": 0.0,
                "rerankEnabled": True,
                "rerankCandidateDepth": 40,
            },
            evaluation_mode="answer-only",
            evaluation_split="validation",
            prompt_profile=prompt_profile,
        )

    def test_v4_is_one_generic_coverage_balancing_block(self) -> None:
        for lane in ("baseline", "skill", "tuned", "agentic"):
            with self.subTest(lane=lane):
                incumbent = self._prompt(lane=lane)
                candidate = self._prompt(
                    lane=lane,
                    prompt_profile=_LUNA_PROMPT_ONLY_V4_PROFILE,
                )
                self.assertEqual(
                    incumbent,
                    candidate.replace(_LUNA_PROMPT_ONLY_V4_RULE, ""),
                )
                self.assertEqual(1, candidate.count(_LUNA_PROMPT_ONLY_V4_RULE))

        candidate = self._prompt(prompt_profile=_LUNA_PROMPT_ONLY_V4_PROFILE)
        self.assertIn("原子缺口", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("父 Agent 独立校验", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("每个 partial_direct", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("第二条", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("none_direct", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("safety", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("不得猜测", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("citationRef", _LUNA_PROMPT_ONLY_V4_RULE)
        self.assertIn("answer=证据不足", _LUNA_PROMPT_ONLY_V4_RULE)

        self.assertNotIn("PRIVATE REFERENCE ANSWER", candidate)
        self.assertNotIn("PRIVATE GOLD FACT", candidate)
        self.assertNotIn("private-query-id", candidate)
        for forbidden in (
            "case-01",
            "case-02",
            "qst_",
            "dsid_",
            "qrel",
            "Gold",
            "attention/kernel",
            "quantization-friendly",
            "hosted",
            "Dedicated",
        ):
            self.assertNotIn(forbidden, _LUNA_PROMPT_ONLY_V4_RULE)

    def test_v4_is_fail_closed_to_answer_only_validation_development(self) -> None:
        _validate_prompt_profile(
            _LUNA_PROMPT_ONLY_V4_PROFILE,
            answer_only=True,
            evaluation_split="validation",
            development_only=True,
        )
        invalid_contexts = (
            {"answer_only": False, "evaluation_split": "validation", "development_only": True},
            {"answer_only": True, "evaluation_split": "held_out", "development_only": True},
            {"answer_only": True, "evaluation_split": "validation", "development_only": False},
        )
        for context in invalid_contexts:
            with self.subTest(context=context), self.assertRaises(ValueError):
                _validate_prompt_profile(_LUNA_PROMPT_ONLY_V4_PROFILE, **context)

    def test_preflight_receipt_is_self_hashed_public_safe_and_not_a_result(self) -> None:
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        claimed = receipt.pop("receiptSha256")
        canonical = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(hashlib.sha256(canonical).hexdigest(), claimed)
        self.assertEqual(
            "paw.enterprise-rag-answer-evidence-three-stage-preflight.v4",
            receipt["schemaVersion"],
        )
        self.assertEqual(
            str(SUPERSEDED_RECEIPT.relative_to(ROOT)),
            receipt["supersedes"]["path"],
        )
        self.assertEqual(
            hashlib.sha256(SUPERSEDED_RECEIPT.read_bytes()).hexdigest(),
            receipt["supersedes"]["fileSha256"],
        )
        self.assertEqual(
            json.loads(SUPERSEDED_RECEIPT.read_text(encoding="utf-8"))[
                "receiptSha256"
            ],
            receipt["supersedes"]["receiptSha256"],
        )
        self.assertEqual("authorized-not-run", receipt["status"])
        self.assertEqual(0, receipt["executionPlan"]["providerCalls"])
        self.assertEqual(0, receipt["executionPlan"]["judgeCalls"])
        self.assertEqual(0, receipt["executionPlan"]["costReceiptsGenerated"])
        self.assertTrue(receipt["executionPlan"]["runAuthorized"])
        self.assertFalse(receipt["candidate"]["successObserved"])
        self.assertEqual(
            hashlib.sha256(_LUNA_PROMPT_ONLY_V4_RULE.encode("utf-8")).hexdigest(),
            receipt["candidate"]["ruleSha256"],
        )
        self.assertEqual(
            _sha256_json(
                receipt["frozenInputs"]["runtimeContractFiles"]
            ),
            receipt["frozenInputs"]["runtimeContractSha256"],
        )
        self.assertEqual(
            receipt["harnessRepair"]["runnerSha256"],
            receipt["frozenInputs"]["runnerSha256"],
        )
        self.assertEqual(
            receipt["harnessRepair"]["gatewaySha256"],
            receipt["frozenInputs"]["runtimeContractFiles"][
                "rag_ime/rag_benchmark_agent.py"
            ],
        )
        factor_table = receipt["factorTable"]
        self.assertEqual(
            [
                "openai-codex/gpt-5.6-sol",
                "openai-codex/gpt-5.6-luna",
                "openai-codex/gpt-5.6-luna",
            ],
            [stage["model"] for stage in factor_table],
        )
        self.assertEqual(
            factor_table[0]["lanePromptSha256ByLane"],
            factor_table[1]["lanePromptSha256ByLane"],
        )
        self.assertNotEqual(
            factor_table[1]["lanePromptSha256ByLane"],
            factor_table[2]["lanePromptSha256ByLane"],
        )
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        for private_token in (
            '"facts"',
            '"quote"',
            '"answers"',
            "qst_",
            "dsid_",
            "PRIVATE GOLD",
            "x1top/",
        ):
            self.assertNotIn(private_token, serialized)

    def test_stage_one_metal_failure_stops_the_historical_three_stage_run(self) -> None:
        receipt = json.loads(VALIDATION_RECEIPT.read_text(encoding="utf-8"))
        claimed = receipt.pop("receiptSha256")
        canonical = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(hashlib.sha256(canonical).hexdigest(), claimed)
        self.assertEqual("invalid-stopped-at-stage-1", receipt["status"])
        self.assertFalse(receipt["heldOutOpened"])
        self.assertEqual(
            ["invalid-infrastructure", "not-started", "not-started"],
            [stage["status"] for stage in receipt["stages"]],
        )
        stage_one = receipt["stages"][0]
        self.assertEqual(0, stage_one["observations"]["providerRequestCount"])
        self.assertEqual(0, stage_one["observations"]["toolCallCount"])
        self.assertFalse(stage_one["cost"]["providerBillAvailable"])
        self.assertFalse(stage_one["cost"]["providerBillClaimAllowed"])
        self.assertTrue(
            receipt["postFailureHarnessRepair"][
                "executedRunContractSupersededAfterAbort"
            ]
        )
        self.assertNotEqual(
            receipt["preflight"]["runtimeContractSha256AtExecution"],
            receipt["postFailureHarnessRepair"]["runtimeContractSha256"],
        )
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        for private_token in ('"facts"', '"quote"', '"answers"', "qst_", "dsid_"):
            self.assertNotIn(private_token, serialized)

    def test_stale_oauth_snapshot_is_invalid_and_current_login_probe_is_separate(self) -> None:
        receipt = json.loads(AUTH_VALIDATION_RECEIPT.read_text(encoding="utf-8"))
        claimed = receipt.pop("receiptSha256")
        canonical = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        self.assertEqual(hashlib.sha256(canonical).hexdigest(), claimed)
        self.assertEqual("invalid-stopped-at-stage-1", receipt["status"])
        self.assertEqual(
            "openai-codex-oauth-refresh-token-reused",
            receipt["stages"][0]["failure"]["classification"],
        )
        self.assertEqual(0, receipt["stages"][0]["observations"]["providerRequestCount"])
        self.assertFalse(receipt["stages"][0]["quality"]["comparisonUseAllowed"])
        self.assertEqual(
            ["invalid-infrastructure", "not-started", "not-started"],
            [stage["status"] for stage in receipt["stages"]],
        )
        self.assertTrue(receipt["providerConnectivityProbe"]["accepted"])
        self.assertTrue(receipt["providerConnectivityProbe"]["notPartOfEvaluation"])
        historical_preflight = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(
            historical_preflight["frozenInputs"]["runnerSha256"],
            receipt["postFailureHarnessRepair"]["runnerSha256"],
        )
        self.assertEqual(
            historical_preflight["frozenInputs"]["runtimeContractSha256"],
            receipt["postFailureHarnessRepair"]["runtimeContractSha256"],
        )
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        for private_token in (
            '"access"',
            '"refresh"',
            '"accountId"',
            '"facts"',
            '"quote"',
            "qst_",
            "dsid_",
        ):
            self.assertNotIn(private_token, serialized)


if __name__ == "__main__":
    unittest.main()
