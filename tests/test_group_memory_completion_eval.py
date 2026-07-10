from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("replay_prediction_burst", ROOT / "scripts" / "replay_prediction_burst.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GroupMemoryCompletionEvalTest(unittest.TestCase):
    def test_interview_replay_hard_gates(self) -> None:
        report = MODULE.replay_cases(MODULE.load_cases(ROOT / "docs" / "eval" / "group_memory_completion_cases.jsonl"))
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["metrics"]["commitCount"], 13)
        self.assertEqual(report["metrics"]["remoteDeepSeekAutoCallCount"], 0)
        self.assertEqual(report["metrics"]["crossGroupLeakCount"], 0)
        self.assertEqual(report["metrics"]["rawHistoryLeakCount"], 0)
        self.assertEqual(report["metrics"]["contextEchoCount"], 0)
        rapid = next(item for item in report["cases"] if item["caseId"] == "rapid-10-commits")
        self.assertLessEqual(rapid["metrics"]["predictorCallCount"], 1)
        direct = next(item for item in report["cases"] if item["caseId"] == "strong-memory-direct")
        self.assertEqual(direct["metrics"]["directMemoryHitCount"], 1)
        self.assertEqual(direct["metrics"]["predictorCallCount"], 0)


if __name__ == "__main__":
    unittest.main()
