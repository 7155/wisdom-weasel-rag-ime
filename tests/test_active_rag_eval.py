from __future__ import annotations

import unittest
from pathlib import Path

from rag_ime.active_rag_eval import run_active_rag_eval


class ActiveRagEvalTests(unittest.TestCase):
    def test_active_rag_eval_gate_passes_with_seeded_cases(self) -> None:
        report = run_active_rag_eval(
            cases_file=Path("docs/eval/active_rag_cases.jsonl"),
            project="wisdom-weasel-rag-ime",
            repeat=1,
            max_candidates=5,
            ready_budget_ms=3000,
        )

        self.assertTrue(report["gatePassed"], report)
        self.assertEqual(report["failedCount"], 0)
        self.assertGreaterEqual(report["passedCount"], 3)


if __name__ == "__main__":
    unittest.main()
