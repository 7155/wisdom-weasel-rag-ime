from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.session_recall_effect_eval import evaluate_file
from rag_ime.session_recall_policy import session_recall_policy


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "eval/session-recall/session-recall-fixtures.v1.json"
RECEIPT = ROOT / "eval/session-recall/session-recall-effect-receipt.v1.json"


class SessionRecallEffectEvalTests(unittest.TestCase):
    def test_checked_in_receipt_is_reproducible_and_selects_80_20(self) -> None:
        expected = json.loads(RECEIPT.read_text(encoding="utf-8"))
        actual = evaluate_file(FIXTURES)

        self.assertEqual(actual, expected)
        validate_contract(actual, "session-recall-effect-receipt.v1.json")
        self.assertEqual(actual["selected"]["queryWeight"], 0.8)
        self.assertEqual(actual["selected"]["summaryWeight"], 0.2)
        chosen = next(
            item
            for item in actual["candidateWeights"]
            if item["summaryWeight"] == 0.2
        )
        self.assertEqual(chosen["metrics"]["crossScopeLeak"], 0)
        self.assertEqual(chosen["metrics"]["wrongOldTopic"], 0)
        self.assertEqual(chosen["metrics"]["irrelevantInjection"], 0)
        self.assertEqual(chosen["metrics"]["compactionForgettingRecovery"], 2)

    def test_runtime_policy_is_bound_to_effect_receipt(self) -> None:
        policy = session_recall_policy()
        receipt_hash = hashlib.sha256(RECEIPT.read_bytes()).hexdigest()

        self.assertEqual(policy.start_summary_weight, 0.0)
        self.assertEqual(policy.compaction_summary_weight, 0.2)
        self.assertEqual(policy.receipt_sha256, receipt_hash)


if __name__ == "__main__":
    unittest.main()
