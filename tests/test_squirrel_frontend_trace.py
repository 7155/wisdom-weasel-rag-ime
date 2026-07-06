from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class SquirrelFrontendTraceScriptTests(unittest.TestCase):
    def test_soak_wrapper_dry_run_reports_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-open",
                "--side-panel-only",
                "--no-auto-type",
                "--require-delete-resync",
                "--auto-query",
                "xian zai",
                "--auto-key",
                "7",
                "--wait",
                "15",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("report_path=/tmp/rag-ime-squirrel-soak-report.json", result.stdout)
        self.assertIn("wait_seconds=15", result.stdout)
        self.assertIn("open_test_file=0", result.stdout)
        self.assertIn("auto_type=0", result.stdout)
        self.assertIn("auto_query=xian zai", result.stdout)
        self.assertIn("auto_key=7", result.stdout)
        self.assertIn("require_mixed_panel=0", result.stdout)
        self.assertIn("require_side_panel=1", result.stdout)
        self.assertIn("require_side_commit=1", result.stdout)
        self.assertIn("require_commit_observed=1", result.stdout)
        self.assertIn("require_post_commit_followup=1", result.stdout)
        self.assertIn("require_delete_resync=1", result.stdout)
        self.assertIn("min_side_commits=1", result.stdout)
        self.assertIn("require_balanced_quota=1", result.stdout)
        self.assertIn("--require-side-panel", result.stdout)
        self.assertIn("--require-side-commit", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-post-commit-followup", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)
        self.assertIn("--require-balanced-quota", result.stdout)
        self.assertNotIn("--require-mixed-panel", result.stdout)

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
                "--auto-char-delay",
                "0.08",
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
        self.assertIn("require_post_commit_followup=0", result.stdout)
        self.assertIn("require_mixed_panel=1", result.stdout)
        self.assertIn("require_side_panel=0", result.stdout)
        self.assertIn("auto_type=1", result.stdout)
        self.assertIn("require_commit_observed=1", result.stdout)
        self.assertIn("require_delete_resync=0", result.stdout)
        self.assertIn("auto_query=xian zai", result.stdout)
        self.assertIn("auto_key=7", result.stdout)
        self.assertIn("auto_char_delay=0.08", result.stdout)
        self.assertIn("require_hitoolbox_enabled=0", result.stdout)
        self.assertIn("require_modern_prediction_session=1", result.stdout)
        self.assertIn("require_balanced_quota=1", result.stdout)
        self.assertIn("--require-mixed-panel", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-modern-prediction-session", result.stdout)
        self.assertIn("--require-balanced-quota", result.stdout)
        self.assertNotIn("--require-delete-resync", result.stdout)
        self.assertNotIn("--require-side-commit", result.stdout)
        self.assertNotIn("--require-post-commit-followup", result.stdout)

    def test_foreground_trace_wrapper_can_require_delete_resync(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--mixed-only",
                "--require-delete-resync",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_delete_resync=1", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)

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
        self.assertIn("require_post_commit_followup=1", result.stdout)
        self.assertIn("require_commit_observed=1", result.stdout)
        self.assertIn("--require-side-panel", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-post-commit-followup", result.stdout)
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
        self.assertIn("require_balanced_quota=1", result.stdout)
        self.assertNotIn("--require-modern-prediction-session", result.stdout)

    def test_foreground_trace_wrapper_can_disable_balanced_quota_for_legacy_trace_debugging(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-balanced-quota",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_balanced_quota=0", result.stdout)
        self.assertNotIn("--require-balanced-quota", result.stdout)

    def test_trace_check_can_require_delete_resync(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-delete-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "display_invalidated_by_input_change",
                        "timestampMs": 10,
                        "reason": "delete_key",
                        "keyCode": 51,
                        "inputGeneration": 8,
                        "frontendRevision": 12,
                        "selectionEpoch": 13,
                        "previousDisplayCount": 5,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "committed_context_resynced_after_delete",
                        "timestampMs": 11,
                        "keyCode": 51,
                        "inputGeneration": 8,
                        "frontendRevision": 12,
                        "selectionEpoch": 13,
                        "committedContextHash": "sha256:abc",
                        "committedContextChars": 7,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 12,
                        "inputGeneration": 9,
                        "frontendRevision": 13,
                        "selectionEpoch": 14,
                        "committedContextHash": "sha256:abc",
                        "committedContextChars": 7,
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
                    "--require-delete-resync",
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["required"]["deleteResync"], True)
        self.assertEqual(report["latestDeleteResync"]["invalidation"]["inputGeneration"], 8)
        self.assertEqual(report["latestDeleteResync"]["resync"]["committedContextHash"], "sha256:abc")
        self.assertEqual(report["latestPostDeleteContextUse"]["use"]["event"], "sidecar_request_scheduled")
        self.assertEqual(report["latestPostDeleteContextUse"]["use"]["committedContextHash"], "sha256:abc")
        self.assertEqual(report["postDeleteContextViolations"], [])

    def test_trace_check_fails_when_delete_resync_required_but_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-delete-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "display_invalidated_by_input_change",
                        "timestampMs": 10,
                        "reason": "delete_key",
                        "keyCode": 117,
                        "inputGeneration": 9,
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
                    "--require-delete-resync",
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestDeleteResync"])

    def test_trace_check_fails_when_post_delete_request_uses_old_context_hash(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-delete-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "display_invalidated_by_input_change",
                        "timestampMs": 10,
                        "reason": "delete_key",
                        "keyCode": 51,
                        "inputGeneration": 8,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "committed_context_resynced_after_delete",
                        "timestampMs": 11,
                        "keyCode": 51,
                        "inputGeneration": 8,
                        "committedContextHash": "sha256:new",
                        "committedContextChars": 7,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 12,
                        "inputGeneration": 9,
                        "committedContextHash": "sha256:old",
                        "committedContextChars": 11,
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
                    "--require-delete-resync",
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestPostDeleteContextUse"])
        self.assertEqual(report["postDeleteContextViolations"][0]["reason"], "post_delete_context_hash_mismatch")

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
                            "text": "继续预测",
                            "insertText": "继续预测",
                            "selectionAction": "commit_side_candidate",
                            "displayLayout": "block",
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
                            "sessionFingerprint": "session-a",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "commit_observed",
                        "timestampMs": 4,
                        "committedText": "继续预测",
                        "committedContextChars": 18,
                        "selectionKey": "6",
                        "sessionFingerprint": "session-a",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 5,
                        "candidate": {
                            "label": "6",
                            "selectionKey": "6",
                            "selectionRank": 6,
                            "sourceType": "rag",
                            "text": "继续预测",
                            "insertText": "继续预测",
                            "selectionAction": "commit_side_candidate",
                            "displayLayout": "block",
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
                            "sessionFingerprint": "session-a",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_continuation_scheduled",
                        "timestampMs": 6,
                        "committedText": "继续预测",
                        "committedContextChars": 18,
                        "sourceType": "rag",
                        "selectionKey": "6",
                        "sessionFingerprint": "session-a",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 7,
                        "rawInput": "",
                        "preedit": "",
                        "commitTextPreview": "继续预测",
                        "committedContextChars": 18,
                        "candidateCount": 0,
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
                    "--require-commit-observed",
                    "--require-post-commit-followup",
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
        self.assertEqual(report["latestCommitObserved"]["selectionKey"], "6")
        self.assertEqual(report["latestNumberKeySideCommit"]["commit"]["candidate"]["label"], "6")
        self.assertEqual(report["latestNumberKeySideCommit"]["commit"]["candidate"]["sessionFingerprint"], "session-a")
        self.assertEqual(report["latestPostCommitFollowup"]["request"]["commitTextPreview"], "继续预测")
        self.assertEqual(report["latestPostCommitFollowup"]["request"]["committedContextChars"], 18)

    def test_trace_check_passes_for_rag_only_side_panel_and_side_commit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = [_side_candidate(label="1", source_type="rag", session_fingerprint="session-rag")]
        candidates[0]["text"] = "继续写"
        candidates[0]["insertText"] = "继续写"
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
                        "event": "commit_observed",
                        "timestampMs": 4,
                        "committedText": "继续写",
                        "committedContextChars": 12,
                        "selectionKey": "1",
                        "sessionFingerprint": "session-rag",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 5,
                        "candidate": candidates[0],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_continuation_scheduled",
                        "timestampMs": 6,
                        "committedText": "继续写",
                        "committedContextChars": 12,
                        "sourceType": "rag",
                        "selectionKey": "1",
                        "sessionFingerprint": "session-rag",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 7,
                        "rawInput": "",
                        "preedit": "",
                        "commitTextPreview": "继续写",
                        "committedContextChars": 12,
                        "candidateCount": 0,
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
                    "--require-commit-observed",
                    "--require-post-commit-followup",
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
        self.assertEqual(report["latestCommitObserved"]["selectionKey"], "1")
        self.assertEqual(report["latestNumberKeySideCommit"]["key"], "1")
        self.assertEqual(report["latestPostCommitFollowup"]["request"]["rawInput"], "")

    def test_trace_check_fails_when_side_commit_has_no_post_commit_followup(self) -> None:
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
                        "candidates": _mixed_side_first_candidates(session_fingerprint="session-a"),
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
                        "candidates": _mixed_side_first_candidates(session_fingerprint="session-a"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                    "--require-post-commit-followup",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestPostCommitFollowup"])

    def test_trace_check_rejects_followup_without_commit_preview(self) -> None:
        root = Path(__file__).resolve().parents[1]
        selected_candidate = {
            "label": "6",
            "selectionKey": "6",
            "selectionRank": 6,
            "sourceType": "model",
            "text": "继续预测",
            "insertText": "继续预测",
            "selectionAction": "commit_side_candidate",
            "displayLayout": "inline",
            "badge": _source_badge("model"),
            "colorToken": _source_color_token("model"),
            "sessionFingerprint": "session-a",
        }
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                        "candidates": _mixed_side_first_candidates(session_fingerprint="session-a"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 2,
                        "key": "6",
                        "candidate": selected_candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 3,
                        "candidate": selected_candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "commit_observed",
                        "timestampMs": 4,
                        "committedText": "继续预测",
                        "committedContextChars": 18,
                        "selectionKey": "6",
                        "sessionFingerprint": "session-a",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "post_commit_prediction_scheduled",
                        "timestampMs": 5,
                        "selectionKey": "6",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 6,
                        "rawInput": "",
                        "preedit": "",
                        "committedContextChars": 18,
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
                    "--require-commit-observed",
                    "--require-post-commit-followup",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestPostCommitFollowup"])

    def test_trace_check_fails_when_commit_observed_is_required_but_missing(self) -> None:
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
                        "candidates": _mixed_side_first_candidates(session_fingerprint="session-a"),
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
                        "candidates": _mixed_side_first_candidates(session_fingerprint="session-a"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                            "sourceType": "rag",
                            "selectionAction": "commit_side_candidate",
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                    "--require-commit-observed",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestCommitObserved"])

    def test_soak_report_passes_for_valid_trace(self) -> None:
        root = Path(__file__).resolve().parents[1]
        candidates = _balanced_quota_candidates(session_fingerprint="session-a")
        selected_candidate = dict(candidates[2])
        selected_candidate["text"] = "继续预测"
        selected_candidate["insertText"] = "继续预测"
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 1,
                        "frontendRevision": 4,
                        "selectionEpoch": 9,
                        "panelSessionId": "panel-a",
                        "compositionHash": "sha256:aaaa",
                        "committedContextHash": "sha256:bbbb",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_response_received",
                        "timestampMs": 6,
                        "frontendRevision": 4,
                        "selectionEpoch": 9,
                        "panelSessionId": "panel-a",
                        "compositionHash": "sha256:aaaa",
                        "committedContextHash": "sha256:bbbb",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 8,
                        "responseAgeMs": 42,
                        "displayCount": 5,
                        "frontendRevision": 4,
                        "selectionEpoch": 9,
                        "panelSessionId": "panel-a",
                        "compositionHash": "sha256:aaaa",
                        "committedContextHash": "sha256:bbbb",
                        "requestFrontendRevision": 4,
                        "responseFrontendRevision": 4,
                        "liveFrontendRevision": 4,
                        "requestSelectionEpoch": 9,
                        "responseSelectionEpoch": 9,
                        "liveSelectionEpoch": 9,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "sessionFingerprint": "session-a",
                            "expiresAfterMs": 8000,
                            "frontendRevision": 4,
                            "selectionEpoch": 9,
                            "panelSessionId": "panel-a",
                            "compositionHash": "sha256:aaaa",
                            "committedContextHash": "sha256:bbbb",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 9,
                        "forcesHorizontalLayout": True,
                        "frontendRevision": 4,
                        "selectionEpoch": 9,
                        "panelSessionId": "panel-a",
                        "compositionHash": "sha256:aaaa",
                        "committedContextHash": "sha256:bbbb",
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "snapshotId": "snap:soak",
                            "expiresAfterMs": 8000,
                        },
                        "candidateCounts": {"total": 5, "modelInline": 2, "ragBlock": 2, "rime": 1},
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "prediction_snapshot_created",
                        "timestampMs": 10,
                        "fields": {
                            "snapshotId": "snap:soak",
                            "visibleCandidateCount": 5,
                            "sourceSummary": {"model": 2, "rag": 1, "memory": 1, "rime": 1},
                            "action": "fresh",
                            "reason": "visible_candidates",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "prediction_panel_soft_hold",
                        "timestampMs": 11,
                        "fields": {
                            "snapshotId": "snap:soak",
                            "visibleCandidateCount": 5,
                            "sourceSummary": {"model": 2, "rag": 1, "memory": 1, "rime": 1},
                            "action": "soft_hold",
                            "reason": "model timeout; last-good valid",
                            "modelTimedOut": True,
                            "ragTimedOut": False,
                            "holdoverHit": True,
                            "reusedLastGood": True,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "prediction_empty_lane_did_not_clear_panel",
                        "timestampMs": 12,
                        "fields": {
                            "snapshotId": "snap:soak",
                            "visibleCandidateCount": 5,
                            "action": "soft_hold",
                            "reason": "rag empty; model still visible",
                            "modelTimedOut": False,
                            "ragTimedOut": False,
                            "holdoverHit": False,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "prediction_lane_timeout_with_holdover",
                        "timestampMs": 13,
                        "fields": {
                            "snapshotId": "snap:soak",
                            "visibleCandidateCount": 5,
                            "action": "soft_hold",
                            "reason": "model timeout; reused last-good snapshot",
                            "modelTimedOut": True,
                            "ragTimedOut": False,
                            "holdoverHit": True,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_text_layout",
                        "timestampMs": 14,
                        "forcesHorizontalLayout": True,
                        "linear": True,
                        "vertical": False,
                        "frontendRevision": 4,
                        "selectionEpoch": 9,
                        "panelSessionId": "panel-a",
                        "compositionHash": "sha256:aaaa",
                        "committedContextHash": "sha256:bbbb",
                        "candidateCounts": {"total": 5, "modelInline": 2, "ragBlock": 2, "rime": 1},
                        "separators": ["", "  ", "\n", "\n", "\n"],
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "option_number_route",
                        "timestampMs": 15,
                        "key": "3",
                        "route": "option_number",
                        "ordinal": 3,
                        "candidate": selected_candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "commit_observed",
                        "timestampMs": 16,
                        "committedText": "继续预测",
                        "committedContextChars": 24,
                        "selectionKey": "3",
                        "sessionFingerprint": "session-a",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 17,
                        "candidate": selected_candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "post_commit_prediction_scheduled",
                        "timestampMs": 18,
                        "selectionKey": "3",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 22,
                        "rawInput": "",
                        "preedit": "",
                        "commitTextPreview": selected_candidate["insertText"],
                        "committedContextChars": 24,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "display_invalidated_by_input_change",
                        "timestampMs": 24,
                        "reason": "delete_key",
                        "keyCode": 51,
                        "inputGeneration": 10,
                        "frontendRevision": 5,
                        "selectionEpoch": 10,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "committed_context_resynced_after_delete",
                        "timestampMs": 25,
                        "keyCode": 51,
                        "inputGeneration": 10,
                        "frontendRevision": 5,
                        "selectionEpoch": 10,
                        "committedContextHash": "sha256:cccc",
                        "committedContextChars": 18,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 26,
                        "rawInput": "xin",
                        "preedit": "xin",
                        "inputGeneration": 11,
                        "frontendRevision": 6,
                        "selectionEpoch": 11,
                        "committedContextHash": "sha256:cccc",
                        "committedContextChars": 18,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--require-mixed-panel",
                    "--require-side-commit",
                    "--require-commit-observed",
                    "--require-post-commit-followup",
                    "--require-delete-resync",
                    "--require-modern-prediction-session",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

            persisted = json.loads(report_path.read_text(encoding="utf-8"))

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["schemaVersion"], "rag-ime.squirrel-soak-report.v1")
        self.assertEqual(report["metrics"]["pairedSideCommitCount"], 1)
        self.assertTrue(report["metrics"]["deleteResyncObserved"])
        self.assertTrue(report["metrics"]["postDeleteContextUseObserved"])
        self.assertEqual(report["latency"]["responseAgeMs"]["p50"], 42)
        self.assertEqual(report["latency"]["responseReceivedToAppliedMs"]["max"], 2)
        self.assertEqual(report["latency"]["postCommitFollowupMs"]["max"], 5)
        self.assertEqual(report["predictionStability"]["visibleSnapshots"], 1)
        self.assertEqual(report["predictionStability"]["flickerCount"], 0)
        self.assertEqual(report["predictionStability"]["softHoldCount"], 1)
        self.assertGreaterEqual(report["predictionStability"]["lastGoodReuseCount"], 1)
        self.assertEqual(report["predictionStability"]["staleSelectionApplied"], 0)
        self.assertEqual(report["laneStability"]["modelTimeouts"], 1)
        self.assertEqual(report["laneStability"]["modelTimeoutsWithHoldover"], 1)
        self.assertEqual(report["laneStability"]["ragEmptyCount"], 1)
        self.assertEqual(report["laneStability"]["ragEmptyClearedPanelCount"], 0)
        self.assertEqual(report["displayQuality"]["sourceBadgeMissingCount"], 0)
        self.assertEqual(report["displayQuality"]["modelOccupiedAllSlotsViolation"], 0)
        self.assertEqual(report["displayQuality"]["longCandidateViolation"], 0)
        self.assertEqual(report["displayQuality"]["postCommitNumberKeyViolation"], 0)
        self.assertTrue(persisted["passed"])

    def test_soak_report_fails_on_stale_applied_response(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 1,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "sidecar_response_applied",
                        "timestampMs": 2,
                        "responseAgeMs": 99,
                        "requestFrontendRevision": 3,
                        "responseFrontendRevision": 3,
                        "liveFrontendRevision": 4,
                        "requestSelectionEpoch": 6,
                        "responseSelectionEpoch": 6,
                        "liveSelectionEpoch": 7,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "expiresAfterMs": 9000,
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--require-modern-prediction-session",
                    "--manual-required",
                    "Accessibility typing failed",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["manualRequired"], ["Accessibility typing failed"])
        self.assertEqual(report["violations"][0]["type"], "stale_applied_response")
        self.assertIn("requestFrontendRevision!=liveFrontendRevision", report["violations"][0]["mismatches"])

    def test_soak_report_fails_display_quality_violations(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-display-quality-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidates = [
                _side_candidate(label=str(index), source_type="model", session_fingerprint="session-a")
                for index in range(1, 5)
            ]
            candidates[0].pop("badge", None)
            candidates[0].pop("colorToken", None)
            candidates[0]["text"] = "这个候选文本非常非常非常非常非常非常非常非常长不应该直接塞进候选栏"
            for candidate in candidates:
                candidate["snapshotId"] = "snap:post-commit"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "predictionSession": {
                            "phase": "post_commit",
                            "selectionScope": "prediction",
                            "snapshotId": "snap:post-commit",
                            "expiresAfterMs": 8000,
                        },
                        "candidateCounts": {"total": 4, "modelInline": 4, "ragBlock": 0, "rime": 0},
                        "candidates": candidates,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 2,
                        "key": "1",
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
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
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertGreater(report["displayQuality"]["sourceBadgeMissingCount"], 0)
        self.assertEqual(report["displayQuality"]["modelOccupiedAllSlotsViolation"], 1)
        self.assertEqual(report["displayQuality"]["longCandidateViolation"], 1)
        self.assertEqual(report["displayQuality"]["postCommitNumberKeyViolation"], 1)
        violation_types = {item["type"] for item in report["violations"]}
        self.assertIn("source_badge_missing", violation_types)
        self.assertIn("model_occupied_all_slots", violation_types)
        self.assertIn("long_candidate", violation_types)
        self.assertIn("post_commit_number_key", violation_types)

    def test_soak_report_fails_min_visible_violation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-min-visible-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "prediction_panel_soft_hide",
                        "timestampMs": 1,
                        "fields": {
                            "snapshotId": "snap:min-visible",
                            "minVisibleRemainingMs": 400,
                            "reason": "soft hide before minimum visible duration",
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
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
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["predictionStability"]["minVisibleViolationCount"], 1)
        self.assertFalse(report["thresholdResults"]["minVisibleViolations"])
        self.assertIn("min_visible_threshold", {item["type"] for item in report["violations"]})

    def test_soak_report_counts_continuous_chain_depth(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-chain-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(_chain_trace_events(depth=3), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
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
                    "--min-chain-depth",
                    "3",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["thresholds"]["minChainDepth"], 3)
        self.assertTrue(report["thresholdResults"]["chainDepth"])
        self.assertEqual(report["chain"]["validSideCommitCount"], 3)
        self.assertEqual(report["chain"]["chainedCommitCount"], 3)
        self.assertEqual(report["chain"]["maxChainDepth"], 3)
        self.assertEqual(report["chain"]["chainSuccessRate"], 1.0)

    def test_soak_report_fails_when_chain_depth_is_too_low(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-chain-low-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(_chain_trace_events(depth=2), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
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
                    "--min-chain-depth",
                    "3",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertFalse(report["thresholdResults"]["chainDepth"])
        self.assertEqual(report["chain"]["maxChainDepth"], 2)
        self.assertIn("chain_depth_threshold", {item["type"] for item in report["violations"]})

    def test_soak_report_counts_option_number_side_selection_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-option-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidate = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "option_number_route",
                        "timestampMs": 2,
                        "key": "1",
                        "route": "option_number",
                        "ordinal": 1,
                        "candidate": candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": candidate},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--require-side-commit",
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-panel-displays",
                    "1",
                    "--min-side-commits",
                    "1",
                    "--min-post-commit-followups",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["numberKeyRouteCount"], 0)
        self.assertEqual(report["metrics"]["sideSelectionRouteCount"], 1)
        self.assertEqual(report["metrics"]["pairedSideCommitCount"], 1)
        self.assertEqual(report["metrics"]["pairedSideSelectionCommitCount"], 1)

    def test_trace_check_reports_sidecar_drop_reason_and_live_input(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_response_dropped",
                        "timestampMs": 10,
                        "reason": "response_too_late_for_foreground",
                        "requestRawInput": "woxiang",
                        "responseRawInput": "woxiang",
                        "currentRawInput": "woxiang",
                        "requestPreedit": "wo xiang",
                        "responsePreedit": "wo xiang",
                        "displayCount": 8,
                        "responseAgeMs": 1376,
                        "inputGeneration": 3,
                        "liveInputGeneration": 3,
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
                    "--print-last",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        event = report["lastEvents"][0]
        self.assertEqual(event["reason"], "response_too_late_for_foreground")
        self.assertEqual(event["currentRawInput"], "woxiang")
        self.assertEqual(event["responseAgeMs"], 1376)
        self.assertEqual(event["inputGeneration"], 3)
        self.assertEqual(event["liveInputGeneration"], 3)

    def test_trace_check_reports_frontend_transaction_stale_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_response_dropped_stale",
                        "timestampMs": 10,
                        "reason": "frontend_revision_mismatch",
                        "requestSeq": 7,
                        "requestFrontendRevision": 3,
                        "responseFrontendRevision": 3,
                        "liveFrontendRevision": 4,
                        "requestSelectionEpoch": 2,
                        "responseSelectionEpoch": 2,
                        "liveSelectionEpoch": 3,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "stale_candidate_selection_rejected",
                        "timestampMs": 11,
                        "reason": "candidate_transaction_mismatch",
                        "key": "2",
                        "frontendRevision": 4,
                        "selectionEpoch": 3,
                        "panelSessionId": "panel-new",
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
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["latestStaleResponseDrop"]["reason"], "frontend_revision_mismatch")
        self.assertEqual(report["latestStaleResponseDrop"]["liveFrontendRevision"], 4)
        self.assertEqual(report["latestStaleSelectionRejected"]["reason"], "candidate_transaction_mismatch")

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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
            events = [
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
                {
                    "event": "prediction_snapshot_created",
                    "timestampMs": 2,
                    "snapshotId": "snap:trace",
                    "visibleCandidateCount": 3,
                    "sourceSummary": {"model": 2, "rag": 1},
                    "action": "fresh",
                    "shouldShow": True,
                },
            ]
            log_path.write_text(
                "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
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
        self.assertEqual(report["latestPredictionTraceEvents"][-1]["event"], "prediction_snapshot_created")
        self.assertEqual(report["latestPredictionTraceEvents"][-1]["snapshotId"], "snap:trace")
        self.assertEqual(report["latestPredictionTraceEvents"][-1]["visibleCandidateCount"], 3)

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

    def test_trace_check_can_require_balanced_candidate_quota(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-quota-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": True,
                        "candidateCounts": {"total": 5, "modelInline": 2, "ragBlock": 2, "rime": 1},
                        "candidates": _balanced_quota_candidates(),
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
                    "--require-balanced-quota",
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["required"]["balancedQuota"], True)
        self.assertEqual(report["latestBalancedCandidatePanel"]["candidateCounts"]["modelInline"], 2)
        self.assertEqual(report["candidateQuotaViolations"], [])

    def test_trace_check_rejects_model_overrun_when_rag_is_visible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-quota-") as tmp:
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
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--require-balanced-quota",
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["latestBalancedCandidatePanel"])
        self.assertEqual(
            report["candidateQuotaViolations"][0]["reason"],
            "model_candidates_exceed_quota_when_rag_or_memory_visible",
        )

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
            "badge": _source_badge("rime"),
            "colorToken": _source_color_token("rime"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                            "badge": _source_badge("rime"),
                            "colorToken": _source_color_token("rime"),
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
                            "badge": _source_badge("rime"),
                            "colorToken": _source_color_token("rime"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
                            "badge": _source_badge("rag"),
                            "colorToken": _source_color_token("rag"),
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
        self.assertIsNone(report["latestSideSelectionCommit"])

    def test_trace_check_accepts_option_number_side_selection_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-option-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            candidate = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "option_number_route",
                        "timestampMs": 2,
                        "key": "1",
                        "route": "option_number",
                        "ordinal": 1,
                        "candidate": candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": candidate},
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
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertIsNone(report["latestNumberKeySideCommit"])
        self.assertEqual(report["latestSideSelectionRoute"]["event"], "option_number_route")
        self.assertEqual(report["latestSideSelectionCommit"]["routeEvent"], "option_number_route")
        self.assertEqual(report["latestSideSelectionCommit"]["key"], "1")

    def test_trace_check_accepts_tab_top_prediction_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-tab-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            candidate = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            candidate["candidateOrdinal"] = 1
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "tab_key_route",
                        "timestampMs": 2,
                        "key": "tab",
                        "route": "tab",
                        "ordinal": 1,
                        "candidate": candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": candidate},
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
                    "--print-last",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertIsNone(report["latestNumberKeySideCommit"])
        self.assertEqual(report["latestSideSelectionRoute"]["event"], "tab_key_route")
        self.assertEqual(report["latestSideSelectionCommit"]["routeEvent"], "tab_key_route")
        self.assertEqual(report["latestSideSelectionCommit"]["key"], "tab")

    def test_trace_check_rejects_number_key_commit_with_selection_epoch_mismatch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            route_candidate = _side_candidate(label="6", source_type="rag", session_fingerprint="session-a")
            route_candidate.update(
                {
                    "frontendRevision": 4,
                    "selectionEpoch": 8,
                    "panelSessionId": "panel-a",
                    "compositionHash": "sha256:composition",
                    "committedContextHash": "sha256:context",
                }
            )
            commit_candidate = dict(route_candidate)
            commit_candidate["selectionEpoch"] = 9
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 1, "rime": 0},
                        "candidates": [route_candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "number_key_route", "timestampMs": 2, "key": "6", "candidate": route_candidate},
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": commit_candidate},
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
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report["latestValidSideCommit"])
        self.assertIsNone(report["latestNumberKeySideCommit"])

    def test_trace_check_rejects_number_key_commit_with_snapshot_mismatch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            route_candidate = _side_candidate(label="6", source_type="rag", session_fingerprint="session-a")
            route_candidate.update(
                {
                    "snapshotId": "snap:visible",
                    "candidateStableId": "rag:visible",
                    "candidateOrdinal": 1,
                    "hardContextAnchor": "sha256:hard",
                    "queryAnchor": "sha256:query",
                    "displayAnchor": "sha256:display",
                }
            )
            commit_candidate = dict(route_candidate)
            commit_candidate["snapshotId"] = "snap:stale"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "forcesHorizontalLayout": False,
                        "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 1, "rime": 0},
                        "candidates": [route_candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "number_key_route", "timestampMs": 2, "key": "6", "candidate": route_candidate},
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": commit_candidate},
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
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report["latestValidSideCommit"])
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
            "badge": _source_badge("model"),
            "colorToken": _source_color_token("model"),
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
            "badge": _source_badge("rag"),
            "colorToken": _source_color_token("rag"),
        }
        if session_fingerprint:
            candidate["sessionFingerprint"] = session_fingerprint
        candidates.append(candidate)
    return candidates


def _balanced_quota_candidates(session_fingerprint: str = "") -> list[dict[str, object]]:
    candidates = [
        _side_candidate("1", "model", session_fingerprint),
        _side_candidate("2", "model", session_fingerprint),
        _side_candidate("3", "rag", session_fingerprint),
        _side_candidate("4", "memory", session_fingerprint),
        {
            "label": "5",
            "selectionKey": "5",
            "selectionRank": 5,
            "sourceType": "rime",
            "selectionAction": "select_rime_candidate",
            "displayLayout": "fallback",
            "displayLane": "rime",
            "badge": _source_badge("rime"),
            "colorToken": _source_color_token("rime"),
        },
    ]
    if session_fingerprint:
        candidates[-1]["sessionFingerprint"] = session_fingerprint
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
        "badge": _source_badge(source_type),
        "colorToken": _source_color_token(source_type),
        "sessionFingerprint": session_fingerprint,
    }


def _chain_trace_events(depth: int) -> str:
    lines: list[str] = []
    for index in range(depth):
        candidate = _side_candidate(label="1", source_type="model", session_fingerprint=f"session-{index}")
        candidate["text"] = f"连续候选{index}"
        candidate["insertText"] = f"连续候选{index}"
        timestamp = index * 10
        lines.append(
            json.dumps(
                {"event": "side_candidate_commit", "timestampMs": timestamp + 1, "candidate": candidate},
                ensure_ascii=False,
            )
        )
        lines.append(
            json.dumps(
                {
                    "event": "commit_observed",
                    "timestampMs": timestamp + 2,
                    "committedText": candidate["insertText"],
                    "committedContextChars": 12 + index,
                    "sessionFingerprint": candidate["sessionFingerprint"],
                },
                ensure_ascii=False,
            )
        )
        lines.append(
            json.dumps(
                {
                    "event": "post_commit_prediction_scheduled",
                    "timestampMs": timestamp + 3,
                    "selectionKey": candidate["selectionKey"],
                },
                ensure_ascii=False,
            )
        )
        lines.append(
            json.dumps(
                {
                    "event": "sidecar_request_scheduled",
                    "timestampMs": timestamp + 4,
                    "rawInput": "",
                    "preedit": "",
                    "commitTextPreview": candidate["insertText"],
                    "committedContextChars": 12 + index,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines) + "\n"


def _source_badge(source_type: str) -> str:
    return {
        "rime": "词",
        "model": "模",
        "rag": "查",
        "memory": "忆",
        "raw_english": "input",
    }[source_type]


def _source_color_token(source_type: str) -> str:
    return {
        "rime": "rimeOrange",
        "model": "modelBlue",
        "rag": "ragTeal",
        "memory": "memoryPurple",
        "raw_english": "rawGray",
    }[source_type]


if __name__ == "__main__":
    unittest.main()
