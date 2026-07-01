from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class SquirrelFrontendTraceScriptTests(unittest.TestCase):
    def test_trace_check_passes_for_mixed_panel_and_side_commit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "candidates": [
                            {"label": "1", "sourceType": "model", "displayLayout": "inline", "displayLane": "model"},
                            {"label": "6", "sourceType": "rag", "displayLayout": "block", "displayLane": "memory"},
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_text_layout",
                        "timestampMs": 2,
                        "forcesHorizontalLayout": True,
                        "linear": True,
                        "vertical": False,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
                        "candidates": [
                            {"label": "1", "sourceType": "model", "displayLayout": "inline", "displayLane": "model"},
                            {"label": "6", "sourceType": "rag", "displayLayout": "block", "displayLane": "memory"},
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 3,
                        "candidate": {"label": "6", "sourceType": "rag", "displayLayout": "block"},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--require-mixed-panel",
                    "--require-side-commit",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["latestMixedPanel"]["candidateCounts"]["modelInline"], 5)
        self.assertEqual(report["latestMixedTextLayout"]["separators"][1], "  ")
        self.assertEqual(report["latestMixedTextLayout"]["separators"][5], "\n")
        self.assertEqual(report["latestSideCommit"]["candidate"]["label"], "6")

    def test_trace_check_fails_without_rag_block(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 5, "modelInline": 5, "ragBlock": 0, "rime": 0},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--require-mixed-panel",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestMixedPanel"])

    def test_trace_check_fails_when_model_inline_candidates_are_newline_separated(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_text_layout",
                        "timestampMs": 2,
                        "forcesHorizontalLayout": True,
                        "vertical": False,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "separators": ["", "\n", "\n", "\n", "\n", "\n", "\n", "\n"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--require-mixed-panel",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report["latestMixedPanel"])
        self.assertIsNone(report["latestMixedTextLayout"])

    def test_trace_check_clear_removes_log(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--clear",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertFalse(log_path.exists())

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["eventCount"], 0)


if __name__ == "__main__":
    unittest.main()
