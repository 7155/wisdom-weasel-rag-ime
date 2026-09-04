from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.run_rag_agent_ablation import (
    _LUNA_PROMPT_ONLY_V4_PROFILE,
    _LUNA_PROMPT_ONLY_V5_PROFILE,
    _LUNA_PROMPT_ONLY_V5_RULE,
    _RUNTIME_CONTRACT_PATHS,
    _lane_prompt,
    _sha256_json,
    _validate_prompt_profile,
)


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = (
    ROOT
    / "eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-scope-grounded-v5-preflight-20260905.v1.json"
)


class EnterpriseRagLunaPromptV5Tests(unittest.TestCase):
    def _prompt(self, profile: str) -> str:
        return _lane_prompt(
            lane="agentic",
            run_id="",
            cases=[
                {
                    "evaluationCaseId": "opaque-evaluation-alias",
                    "queryId": "private-query-id",
                    "query": "What are the three primary components in Acme's system?",
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
            prompt_profile=profile,
        )

    def test_v5_is_one_generic_scope_and_enumeration_delta_over_v4(self) -> None:
        baseline = self._prompt(_LUNA_PROMPT_ONLY_V4_PROFILE)
        candidate = self._prompt(_LUNA_PROMPT_ONLY_V5_PROFILE)

        self.assertEqual(baseline, candidate.replace(_LUNA_PROMPT_ONLY_V5_RULE, ""))
        self.assertEqual(1, candidate.count(_LUNA_PROMPT_ONLY_V5_RULE))
        for required in (
            "范围一致性",
            "scope_mismatch",
            "明确数量",
            "逐项",
            "局部",
            "不得外推",
            "中性范围词",
            "证据不足",
        ):
            self.assertIn(required, _LUNA_PROMPT_ONLY_V5_RULE)

        self.assertIn("scope_mismatch", candidate)
        self.assertIn("none_direct", candidate)
        self.assertIn("safety-not-found", candidate)
        for forbidden in (
            "PRIVATE REFERENCE ANSWER",
            "PRIVATE GOLD FACT",
            "private-query-id",
            "case-01",
            "case-02",
            "qst_",
            "dsid_",
            "Redwood Inference",
            "Hosted API",
            "Dedicated reserved",
            "advanced observability retention",
            "premium SLA",
        ):
            self.assertNotIn(forbidden, _LUNA_PROMPT_ONLY_V5_RULE)

    def test_v5_remains_validation_development_only(self) -> None:
        _validate_prompt_profile(
            _LUNA_PROMPT_ONLY_V5_PROFILE,
            answer_only=True,
            evaluation_split="validation",
            development_only=True,
        )
        for context in (
            {"answer_only": False, "evaluation_split": "validation", "development_only": True},
            {"answer_only": True, "evaluation_split": "held_out", "development_only": True},
            {"answer_only": True, "evaluation_split": "validation", "development_only": False},
        ):
            with self.subTest(context=context), self.assertRaises(ValueError):
                _validate_prompt_profile(_LUNA_PROMPT_ONLY_V5_PROFILE, **context)

    def test_v5_preflight_freezes_one_prompt_delta_without_claiming_success(self) -> None:
        receipt = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
        claimed = receipt.pop("receiptSha256")

        self.assertEqual(claimed, _sha256_json(receipt))
        self.assertEqual("authorized-not-run", receipt["status"])
        self.assertEqual(0, receipt["executionPlan"]["providerCalls"])
        self.assertEqual(0, receipt["executionPlan"]["judgeCalls"])
        self.assertFalse(receipt["candidate"]["successObserved"])
        self.assertEqual("prompt", receipt["candidate"]["layer"])
        self.assertEqual(1, receipt["candidate"]["variableCount"])
        self.assertEqual(
            hashlib.sha256(_LUNA_PROMPT_ONLY_V5_RULE.encode("utf-8")).hexdigest(),
            receipt["candidate"]["ruleSha256"],
        )
        runtime_files = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in _RUNTIME_CONTRACT_PATHS
        }
        self.assertEqual(runtime_files, receipt["frozenInputs"]["runtimeContractFiles"])
        self.assertEqual(
            _sha256_json(runtime_files),
            receipt["frozenInputs"]["runtimeContractSha256"],
        )
        self.assertFalse(receipt["heldOutOpened"])
        self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        for forbidden in ('"facts"', '"quote"', "qst_", "dsid_", "x1top/"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
