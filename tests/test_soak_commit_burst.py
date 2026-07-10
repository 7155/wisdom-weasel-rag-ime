from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_squirrel_soak_report import summarize_commit_burst


class SoakCommitBurstTest(unittest.TestCase):
    def test_summary_counts_coalescing_provider_and_remote_gate(self) -> None:
        events = [
            {"event": "prediction_trigger_dirty"},
            *({"event": "prediction_trigger_coalesced"} for _ in range(9)),
            {"event": "prediction_trigger_fired"},
            {"event": "prediction_provider_called", "remoteDeepSeekAutoCallCount": 0},
            {"event": "prediction_trigger_direct_memory_hit", "remoteDeepSeekAutoCallCount": 0},
        ]

        summary = summarize_commit_burst(events)

        self.assertEqual(summary["commitCount"], 10)
        self.assertEqual(summary["coalescedCount"], 9)
        self.assertEqual(summary["predictorCallCount"], 1)
        self.assertEqual(summary["directMemoryHitCount"], 1)
        self.assertEqual(summary["remoteDeepSeekAutoCallCount"], 0)
        self.assertTrue(summary["remoteDeepSeekAutoDisabled"])


if __name__ == "__main__":
    unittest.main()
