from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rag_ime.contracts.trace import (
    PREDICTION_TRACE_EVENT_NAMES,
    REQUIRED_TRACE_EVENT_NAMES,
    SOAK_REPORT_SCHEMA_VERSION,
    V1_FOREGROUND_METRIC_KEYS,
)


ROOT = Path(__file__).resolve().parents[1]


class TraceContractTests(unittest.TestCase):
    def test_v1_trace_contract_names_cover_foreground_acceptance_path(self) -> None:
        self.assertIn("panel_display_candidates", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("post_commit_prediction_applied", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("sidecar_response_dropped_stale", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("candidate_snapshot_selection_accepted", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("delete_context_resynced", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("app_switch_context_invalidated", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("focus_context_invalidated", REQUIRED_TRACE_EVENT_NAMES)
        self.assertIn("candidate_snapshot_progressive_replace", PREDICTION_TRACE_EVENT_NAMES)

    def test_soak_report_uses_trace_contract_schema_and_required_event_keys(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-trace-contract-") as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "squirrel.jsonl"
            report_path = tmp_path / "report.json"
            log_path.write_text("", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "scripts/check_squirrel_soak_report.py",
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--wait",
                    "0",
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-panel-displays",
                    "0",
                    "--min-side-commits",
                    "0",
                    "--min-post-commit-followups",
                    "0",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            report = json.loads(result.stdout)

        self.assertEqual(report["schemaVersion"], SOAK_REPORT_SCHEMA_VERSION)
        self.assertEqual(tuple(report["requiredTraceEvents"]), REQUIRED_TRACE_EVENT_NAMES)
        for key in V1_FOREGROUND_METRIC_KEYS:
            self.assertIn(key, report["v1Foreground"])


if __name__ == "__main__":
    unittest.main()
