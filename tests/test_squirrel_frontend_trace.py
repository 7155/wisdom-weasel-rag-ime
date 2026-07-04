from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class SquirrelFrontendTraceScriptTests(unittest.TestCase):
    def test_foreground_trace_wrapper_dry_run_reports_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-open",
                "--mixed-only",
                "--auto-type",
                "--auto-query",
                "xian zai",
                "--auto-key",
                "7",
                "--wait",
                "12",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("wait_seconds=12", result.stdout)
        self.assertIn("open_test_file=0", result.stdout)
        self.assertIn("require_side_commit=0", result.stdout)
        self.assertIn("require_mixed_panel=1", result.stdout)
        self.assertIn("require_side_panel=0", result.stdout)
        self.assertIn("auto_type=1", result.stdout)
        self.assertIn("auto_query=xian zai", result.stdout)
        self.assertIn("auto_key=7", result.stdout)
        self.assertIn("require_hitoolbox_enabled=0", result.stdout)
        self.assertIn("require_modern_prediction_session=1", result.stdout)
        self.assertIn("--require-mixed-panel", result.stdout)
        self.assertIn("--require-modern-prediction-session", result.stdout)
        self.assertNotIn("--require-side-commit", result.stdout)

    def test_foreground_trace_wrapper_can_require_side_panel_without_mixed_layout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--side-panel-only",
                "--auto-type",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_mixed_panel=0", result.stdout)
        self.assertIn("require_side_panel=1", result.stdout)
        self.assertIn("--require-side-panel", result.stdout)
        self.assertNotIn("--require-mixed-panel", result.stdout)

    def test_foreground_trace_wrapper_can_require_hitoolbox_when_requested(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--require-hitoolbox-enabled",
                "--no-modern-session",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_hitoolbox_enabled=1", result.stdout)
        self.assertIn("require_modern_prediction_session=0", result.stdout)
        self.assertNotIn("--require-modern-prediction-session", result.stdout)

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
                        "candidates": _mixed_side_first_candidates(),
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
                        "candidates": _mixed_side_first_candidates(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 3,
                        "key": "6",
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "selectionRank": 6,
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "displayLayout": "block",
                            "sessionFingerprint": "session-a",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 4,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "selectionRank": 6,
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "displayLayout": "block",
                            "sessionFingerprint": "session-a",
                        },
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
        self.assertEqual(report["latestValidSideCommit"]["candidate"]["selectionAction"], "commit_side_candidate")
        self.assertEqual(report["latestNumberKeyRoute"]["key"], "6")
        self.assertEqual(report["latestNumberKeySideCommit"]["key"], "6")
        self.assertEqual(report["latestNumberKeySideCommit"]["commit"]["candidate"]["label"], "6")
        self.assertEqual(report["latestNumberKeySideCommit"]["commit"]["candidate"]["sessionFingerprint"], "session-a")

    def test_trace_check_passes_for_rag_only_side_panel_and_side_commit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = [_side_candidate(label="1", source_type="rag", session_fingerprint="session-rag")]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 1,
                        "displayCount": 1,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "sessionFingerprint": "session-rag",
                            "expiresAfterMs": 8000,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 2,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 1, "rime": 0},
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 3,
                        "key": "1",
                        "candidate": candidates[0],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 4,
                        "candidate": candidates[0],
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
                    "--require-side-panel",
                    "--require-side-commit",
                    "--require-modern-prediction-session",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["latestSidePanel"]["candidateCounts"]["ragBlock"], 1)
        self.assertIsNone(report["latestMixedPanel"])
        self.assertEqual(report["latestNumberKeySideCommit"]["key"], "1")

    def test_trace_check_rejects_side_commit_from_older_panel_session(self) -> None:
        root = Path(__file__).resolve().parents[1]
        old_candidates = _mixed_side_first_candidates(session_fingerprint="old-session")
        fresh_candidates = _mixed_side_first_candidates(session_fingerprint="fresh-session")
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "candidates": old_candidates,
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
                        "candidates": old_candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 3,
                        "key": "6",
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "sessionFingerprint": "old-session",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 4,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "sessionFingerprint": "old-session",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 10,
                        "displayCount": 8,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "sessionFingerprint": "fresh-session",
                            "expiresAfterMs": 8000,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 11,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "candidates": fresh_candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_text_layout",
                        "timestampMs": 12,
                        "forcesHorizontalLayout": True,
                        "linear": True,
                        "vertical": False,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
                        "candidates": fresh_candidates,
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
                    "--require-modern-prediction-session",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["sideCommitBarrierTimestampMs"], 12)
        self.assertIsNone(report["latestNumberKeySideCommit"])
        self.assertEqual(report["latestHistoricalNumberKeySideCommit"]["key"], "6")

    def test_trace_check_requires_non_legacy_prediction_session(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 1,
                        "displayCount": 3,
                        "latencyBudgetMs": 1200,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "mixed_prediction_first",
                            "sessionFingerprint": "session-a",
                            "expiresAfterMs": 8000,
                        },
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
                    "--require-modern-prediction-session",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["latestModernPredictionSession"]["predictionSession"]["phase"], "post_commit")
        self.assertEqual(report["latestModernPredictionSession"]["predictionSession"]["expiresAfterMs"], 8000)

    def test_trace_check_rejects_legacy_prediction_session(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 1,
                        "displayCount": 3,
                        "predictionSession": {
                            "phase": "legacy",
                            "selectionScope": "",
                            "sessionFingerprint": "session-a",
                            "expiresAfterMs": 0,
                        },
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
                    "--require-modern-prediction-session",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertTrue(report["latestSidecarResponse"])
        self.assertIsNone(report["latestModernPredictionSession"])

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

    def test_trace_check_fails_when_rime_candidate_precedes_side_candidates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = _mixed_side_first_candidates()
        candidates[1] = {
            "label": "2",
            "selectionKey": "2",
            "selectionRank": 2,
            "sourceType": "rime",
            "selectionAction": "select_rime_candidate",
            "displayLayout": "fallback",
            "displayLane": "rime",
        }
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 4, "ragBlock": 3, "rime": 1},
                        "candidates": candidates,
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
                        "candidateCounts": {"total": 8, "modelInline": 4, "ragBlock": 3, "rime": 1},
                        "separators": ["", "  ", "  ", "  ", "\n", "\n", "\n", "\n"],
                        "candidates": candidates,
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
        self.assertIsNone(report["latestMixedPanel"])
        self.assertIsNone(report["latestMixedTextLayout"])

    def test_trace_check_fails_side_commit_without_number_key_route(self) -> None:
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
                        "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 3,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                        },
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
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report["latestSideCommit"])
        self.assertIsNone(report["latestNumberKeySideCommit"])

    def test_trace_check_fails_when_number_key_routes_to_rime_candidate(self) -> None:
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
                        "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 3,
                        "key": "6",
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rime",
                            "selectionAction": "select_rime_candidate",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 4,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rime",
                            "selectionAction": "select_rime_candidate",
                        },
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
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIsNone(report["latestValidSideCommit"])
        self.assertIsNone(report["latestNumberKeySideCommit"])

    def test_trace_check_fails_when_number_key_session_does_not_match_commit(self) -> None:
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
                        "candidates": _mixed_side_first_candidates(),
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
                        "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
                        "candidates": _mixed_side_first_candidates(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 3,
                        "key": "6",
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "sessionFingerprint": "old-session",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 4,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "sessionFingerprint": "new-session",
                        },
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
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report["latestSideCommit"])
        self.assertIsNone(report["latestNumberKeySideCommit"])

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


def _mixed_side_first_candidates(session_fingerprint: str = "") -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for index in range(5):
        label = str(index + 1)
        candidate = {
            "label": label,
            "selectionKey": label,
            "selectionRank": index + 1,
            "sourceType": "model",
            "selectionAction": "commit_side_candidate",
            "displayLayout": "inline",
            "displayLane": "model",
        }
        if session_fingerprint:
            candidate["sessionFingerprint"] = session_fingerprint
        candidates.append(candidate)
    for index in range(3):
        label = str(index + 6)
        candidate = {
            "label": label,
            "selectionKey": label,
            "selectionRank": index + 6,
            "sourceType": "rag",
            "selectionAction": "commit_side_candidate",
            "displayLayout": "block",
            "displayLane": "memory",
        }
        if session_fingerprint:
            candidate["sessionFingerprint"] = session_fingerprint
        candidates.append(candidate)
    return candidates


def _side_candidate(label: str, source_type: str, session_fingerprint: str) -> dict[str, object]:
    display_layout = "inline" if source_type == "model" else "block"
    display_lane = "model" if source_type == "model" else "memory"
    return {
        "label": label,
        "selectionKey": label,
        "selectionRank": int(label),
        "sourceType": source_type,
        "selectionAction": "commit_side_candidate",
        "displayLayout": display_layout,
        "displayLane": display_lane,
        "sessionFingerprint": session_fingerprint,
    }


if __name__ == "__main__":
    unittest.main()
