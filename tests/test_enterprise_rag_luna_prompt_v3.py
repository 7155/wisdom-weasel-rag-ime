from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.run_rag_agent_ablation import (
    _LUNA_PROMPT_ONLY_V3_PROFILE,
    _LUNA_PROMPT_ONLY_V3_RULE,
    _lane_prompt,
    _validate_prompt_profile,
)


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = (
    ROOT
    / "eval"
    / "interview-metrics"
    / "runs"
    / "enterprise-rag-luna-max-prompt-only-v3-preflight-20260904.v1.json"
)


class EnterpriseRagLunaPromptV3Tests(unittest.TestCase):
    def _prompt(self, *, prompt_profile: str = "incumbent") -> str:
        return _lane_prompt(
            lane="tuned",
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

    def test_v3_is_one_generic_prompt_block_and_never_discloses_gold(self) -> None:
        incumbent = self._prompt()
        candidate = self._prompt(prompt_profile=_LUNA_PROMPT_ONLY_V3_PROFILE)

        self.assertEqual(incumbent, candidate.replace(_LUNA_PROMPT_ONLY_V3_RULE, ""))
        self.assertEqual(1, candidate.count(_LUNA_PROMPT_ONLY_V3_RULE))
        self.assertNotIn("PRIVATE REFERENCE ANSWER", candidate)
        self.assertNotIn("PRIVATE GOLD FACT", candidate)
        self.assertNotIn("private-query-id", candidate)
        for case_specific_token in (
            "case-01",
            "qst_",
            "dsid_",
            "attention/kernel",
            "quantization-friendly",
            "hosted",
            "Dedicated",
        ):
            self.assertNotIn(case_specific_token, _LUNA_PROMPT_ONLY_V3_RULE)
        self.assertIn("citationRef", _LUNA_PROMPT_ONLY_V3_RULE)
        self.assertIn("answer=\u8bc1\u636e\u4e0d\u8db3", _LUNA_PROMPT_ONLY_V3_RULE)

    def test_v3_is_fail_closed_to_answer_only_validation_development(self) -> None:
        _validate_prompt_profile(
            _LUNA_PROMPT_ONLY_V3_PROFILE,
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
                _validate_prompt_profile(_LUNA_PROMPT_ONLY_V3_PROFILE, **context)
        with self.assertRaises(ValueError):
            _validate_prompt_profile(
                "unknown-profile",
                answer_only=True,
                evaluation_split="validation",
                development_only=True,
            )

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
        self.assertEqual("prepared-not-run", receipt["status"])
        self.assertEqual("post-validation-calibrated", receipt["calibrationLabel"])
        self.assertFalse(receipt["unbiasedPromotionClaimAllowed"])
        self.assertFalse(receipt["heldOutOpened"])
        self.assertEqual(0, receipt["execution"]["providerCalls"])
        self.assertEqual(0, receipt["execution"]["judgeCalls"])
        self.assertFalse(receipt["execution"]["candidateRunExecuted"])
        self.assertEqual(_LUNA_PROMPT_ONLY_V3_PROFILE, receipt["candidate"]["profile"])
        self.assertEqual(
            hashlib.sha256(_LUNA_PROMPT_ONLY_V3_RULE.encode("utf-8")).hexdigest(),
            receipt["candidate"]["ruleSha256"],
        )
        serialized = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        for private_token in (
            '"facts"',
            '"quote"',
            '"answers"',
            "qst_",
            "dsid_",
            "PRIVATE GOLD",
        ):
            self.assertNotIn(private_token, serialized)


if __name__ == "__main__":
    unittest.main()
