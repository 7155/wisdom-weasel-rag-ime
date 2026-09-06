from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from scripts.eval_paw_execution_reliability import evaluate


class ExecutionReliabilityMetricsTests(unittest.TestCase):
    def test_fault_matrix_preserves_crash_point_and_counts_real_effects(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()):
            result = evaluate(Path(temporary), repeats=1)
        rows = {row["scenario"]: row for row in result["rows"]}
        self.assertEqual(result["passed"], 8)
        self.assertEqual(result["duplicateSideEffects"], 0)
        crash = rows["restart_before_execution"]
        self.assertEqual(crash["beforeRestartState"], "running")
        self.assertEqual(crash["state"], "interrupted")
        self.assertEqual(crash["adapterExecutions"], 0)
        self.assertEqual(rows["lost_ack_replay"]["sideEffects"], 1)
        self.assertEqual(rows["lost_ack_replay"]["adapterExecutions"], 1)
        for kind in ("cancel_running", "cancel_late_bind"):
            self.assertEqual(rows[kind]["abortHookCalls"], 1)
            self.assertTrue(rows[kind]["lateSuccessSuppressed"])
            self.assertGreater(rows[kind]["cancelToTerminalMs"], 0)
        self.assertEqual(result["cancelToTerminal"]["samples"], 3)
        self.assertEqual(result["restoreToReadback"]["samples"], 3)


if __name__ == "__main__":
    unittest.main()
