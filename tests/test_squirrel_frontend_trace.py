from __future__ import annotations

import json
import os
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
        self.assertIn("min_backspaces=1", result.stdout)
        self.assertIn("min_app_switches=1", result.stdout)
        self.assertIn("min_side_commits=1", result.stdout)
        self.assertIn("require_balanced_quota=1", result.stdout)
        self.assertIn("--min-backspaces 1", result.stdout)
        self.assertIn("--min-app-switches 1", result.stdout)
        self.assertIn("--require-side-panel", result.stdout)
        self.assertIn("--require-side-commit", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-post-commit-followup", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)
        self.assertIn("--require-balanced-quota", result.stdout)
        self.assertNotIn("--require-mixed-panel", result.stdout)

    def test_soak_wrapper_requires_delete_resync_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-open",
                "--no-auto-type",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_delete_resync=1", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)

    def test_soak_wrapper_can_disable_delete_resync_for_debug(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-open",
                "--no-auto-type",
                "--no-delete-resync",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_delete_resync=0", result.stdout)
        self.assertNotIn("--require-delete-resync", result.stdout)

    def test_soak_wrapper_non_dry_run_writes_delete_resync_manual_step(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-soak-wrapper-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            select_script = tmp_path / "select-input-source.sh"
            open_script = tmp_path / "fake-open.sh"
            soak_script = tmp_path / "fake-soak.py"
            test_file = tmp_path / "foreground-soak.txt"
            check_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            select_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            open_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            soak_script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            for script in (check_script, select_script, open_script, soak_script):
                script.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_SELECT_INPUT_SOURCE_SCRIPT": str(select_script),
                    "RAG_IME_OPEN_COMMAND": str(open_script),
                    "RAG_IME_SOAK_CHECK_SCRIPT": str(soak_script),
                    "RAG_IME_FOREGROUND_SOAK_TEST_FILE": str(test_file),
                    "RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG": str(tmp_path / "squirrel-frontend.jsonl"),
                }
            )

            subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                    "--no-auto-type",
                    "--wait",
                    "0",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

            manual_text = test_file.read_text(encoding="utf-8")

        self.assertIn("Press Backspace/Delete", manual_text)
        self.assertIn("updated foreground context", manual_text)

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

    def test_foreground_trace_wrapper_can_run_v1_soak_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--side-panel-only",
                "--report-path",
                "/tmp/rag-ime-custom-v1-soak.json",
                "--require-rime-composition-ok",
                "--require-post-commit-visible",
                "--require-source-badges",
                "--require-post-commit-key-policy",
                "--require-delete-resync",
                "--require-app-switch-stale-drop",
                "--require-followup-after-select",
                "--max-first-visible-ms",
                "500",
                "--max-stale-apply-count",
                "0",
                "--max-context-echo-count",
                "0",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("gate_mode=v1-soak", result.stdout)
        self.assertIn("soak_report_path=/tmp/rag-ime-custom-v1-soak.json", result.stdout)
        self.assertIn("require_rime_composition_ok=1", result.stdout)
        self.assertIn("require_post_commit_visible=1", result.stdout)
        self.assertIn("require_source_badges=1", result.stdout)
        self.assertIn("require_post_commit_key_policy=1", result.stdout)
        self.assertIn("require_delete_resync=1", result.stdout)
        self.assertIn("require_app_switch_stale_drop=1", result.stdout)
        self.assertIn("require_followup_after_select=1", result.stdout)
        self.assertIn("max_first_visible_ms=500", result.stdout)
        self.assertIn("max_stale_apply_count=0", result.stdout)
        self.assertIn("max_context_echo_count=0", result.stdout)
        self.assertIn("scripts/check_squirrel_soak_report.py", result.stdout)
        self.assertIn("--require-rime-composition-ok", result.stdout)
        self.assertIn("--require-post-commit-visible", result.stdout)
        self.assertIn("--require-source-badges", result.stdout)
        self.assertIn("--require-post-commit-key-policy", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)
        self.assertIn("--require-app-switch-stale-drop", result.stdout)
        self.assertIn("--require-followup-after-select", result.stdout)
        self.assertIn("--max-first-visible-ms 500", result.stdout)
        self.assertIn("--max-stale-apply-count 0", result.stdout)
        self.assertIn("--max-context-echo-count 0", result.stdout)

    def test_foreground_trace_wrapper_can_require_active_rag_lifecycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "verify_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--active-rag-proof",
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_active_rag_action_button=1", result.stdout)
        self.assertIn("require_post_commit_pending_status=1", result.stdout)
        self.assertIn("require_prediction_status_visible=1", result.stdout)
        self.assertIn("require_active_rag_thinking=1", result.stdout)
        self.assertIn("require_active_rag_ready=1", result.stdout)
        self.assertIn("require_side_commit=0", result.stdout)
        self.assertIn("require_post_commit_followup=0", result.stdout)
        self.assertIn("require_modern_prediction_session=0", result.stdout)
        self.assertIn("auto_key=ctrl-period", result.stdout)
        self.assertIn("--require-active-rag-action-button", result.stdout)
        self.assertIn("--require-post-commit-pending-status", result.stdout)
        self.assertIn("--require-prediction-status-visible", result.stdout)
        self.assertIn("--require-active-rag-thinking", result.stdout)
        self.assertIn("--require-active-rag-ready", result.stdout)

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

    def test_trace_check_rejects_raw_text_when_trace_text_is_disabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-privacy-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "committed_context_resynced_after_delete",
                        "timestampMs": 11,
                        "traceIncludesText": False,
                        "committedContextHash": "sha256:abc",
                        "committedContextChars": 7,
                        "committedContextSuffix": "用户刚才输入的真实内容",
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
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["tracePrivacyViolations"][0]["field"], "committedContextSuffix")
        self.assertEqual(report["tracePrivacyViolations"][0]["reason"], "raw_text_in_default_trace")

    def test_trace_check_accepts_hashed_text_when_trace_text_is_disabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-privacy-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "committed_context_resynced_after_delete",
                        "timestampMs": 11,
                        "traceIncludesText": False,
                        "committedContextHash": "sha256:abc",
                        "committedContextChars": 7,
                        "committedContextSuffix": {
                            "chars": 7,
                            "hash": "sha256:abc",
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
        self.assertEqual(report["tracePrivacyViolations"], [])

    def test_trace_check_can_require_active_rag_lifecycle(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            anchor = {
                "selectedTextHash": "sha256:selected",
                "selectedTextChars": 18,
                "frontendRevision": 12,
                "selectionEpoch": 34,
                "panelSessionId": "panel-active",
                "frontAppBundleId": "app.active",
                "traceIncludesText": False,
            }
            status_candidate = _status_candidate()
            status_candidate["text"] = {"hash": "sha256:status", "chars": 6}
            ready_candidate = {
                **_side_candidate("1", "rag", "active-session"),
                "text": {"hash": "sha256:candidate", "chars": 8},
                "insertText": {"hash": "sha256:candidate", "chars": 8},
                "candidateStableId": "active-rag:candidate",
                "candidateOrdinal": 1,
                "snapshotId": "active-snapshot",
            }
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 5,
                        "committedContextHash": "sha256:committed",
                        "compositionHash": "sha256:e3b0c44298fc1c14",
                        "candidates": [
                            {
                                "label": "",
                                "selectionKey": "",
                                "selectionRank": 0,
                                "candidateOrdinal": 0,
                                "sourceType": "action",
                                "selectionAction": "start_active_rag_from_context",
                                "displayLane": "active_rag",
                                "committedContextHash": "sha256:committed",
                                "compositionHash": "sha256:e3b0c44298fc1c14",
                                "text": "DeepSeek 生成",
                                "metadata": {"buttonRole": "active_rag_generate"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        **anchor,
                        "event": "active_rag_thinking_displayed",
                        "timestampMs": 10,
                        "candidates": [status_candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        **anchor,
                        "event": "panel_display_candidates",
                        "timestampMs": 20,
                        "uiMode": "active_rag_assist",
                        "candidates": [ready_candidate],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        **anchor,
                        "event": "active_rag_candidate_committed",
                        "timestampMs": 30,
                        "candidate": ready_candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        **anchor,
                        "event": "active_rag_response_dropped_stale",
                        "timestampMs": 40,
                        "reason": "selection_epoch_mismatch",
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
                    "--require-active-rag-action-button",
                    "--require-post-commit-pending-status",
                    "--require-active-rag-thinking",
                    "--require-active-rag-ready",
                    "--require-active-rag-commit",
                    "--require-active-rag-stale-drop-check",
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
        self.assertEqual(report["required"]["activeRagActionButton"], True)
        self.assertEqual(report["required"]["postCommitPendingStatus"], True)
        self.assertEqual(report["latestActiveRagActionButton"]["committedContextHash"], "sha256:committed")
        self.assertEqual(report["latestPostCommitPendingStatus"]["committedContextHash"], "sha256:committed")
        self.assertEqual(report["required"]["activeRagThinking"], True)
        self.assertEqual(report["latestActiveRagReady"]["uiMode"], "active_rag_assist")
        self.assertEqual(report["latestActiveRagCommit"]["event"], "active_rag_candidate_committed")
        self.assertEqual(report["activeRagTraceViolations"], [])

    def test_trace_check_rejects_raw_selected_text_when_trace_text_is_disabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-active-rag-trace-privacy-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "active_rag_thinking_displayed",
                        "timestampMs": 10,
                        "traceIncludesText": False,
                        "selectedText": "用户显式选中的完整原文",
                        "selectedTextHash": "sha256:selected",
                        "selectedTextChars": 12,
                        "frontendRevision": 1,
                        "selectionEpoch": 2,
                        "panelSessionId": "panel-active",
                        "frontAppBundleId": "app.active",
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
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertEqual(report["tracePrivacyViolations"][0]["field"], "selectedText")

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
                        "event": "candidate_snapshot_selection_accepted",
                        "timestampMs": 15,
                        "fields": {
                            "snapshotId": "snap:soak",
                            "index": 2,
                            "selectionEpoch": 9,
                            "panelSessionId": "panel-a",
                            "candidate": selected_candidate,
                        },
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
                        "event": "candidate_snapshot_selection_rejected_stale",
                        "timestampMs": 23,
                        "fields": {
                            "snapshotId": "snap:old",
                            "reason": "candidate_transaction_mismatch",
                            "selectionEpoch": 8,
                            "panelSessionId": "panel-old",
                        },
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
                    "--require-snapshot-selection-trace",
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
        self.assertTrue(report["required"]["snapshotSelectionTrace"])
        self.assertTrue(report["thresholdResults"]["snapshotSelectionTrace"])
        self.assertEqual(report["latency"]["responseAgeMs"]["p50"], 42)
        self.assertEqual(report["latency"]["responseReceivedToAppliedMs"]["max"], 2)
        self.assertEqual(report["latency"]["postCommitFollowupMs"]["max"], 5)
        self.assertEqual(report["predictionStability"]["visibleSnapshots"], 1)
        self.assertEqual(report["predictionStability"]["flickerCount"], 0)
        self.assertEqual(report["predictionStability"]["softHoldCount"], 1)
        self.assertGreaterEqual(report["predictionStability"]["lastGoodReuseCount"], 1)
        self.assertEqual(report["predictionStability"]["snapshotSelectionAccepted"], 1)
        self.assertEqual(report["predictionStability"]["snapshotSelectionRejectedStale"], 1)
        self.assertEqual(report["predictionStability"]["staleSelectionApplied"], 0)
        self.assertEqual(report["selectionQuality"]["snapshotSelectionAcceptedCount"], 1)
        self.assertEqual(report["selectionQuality"]["snapshotSelectionRejectedStaleCount"], 1)
        self.assertEqual(report["selectionQuality"]["sideCommitWithoutAcceptedSnapshotSelectionCount"], 0)
        self.assertEqual(report["laneStability"]["modelTimeouts"], 1)
        self.assertEqual(report["laneStability"]["modelTimeoutsWithHoldover"], 1)
        self.assertEqual(report["laneStability"]["ragEmptyCount"], 1)
        self.assertEqual(report["laneStability"]["ragEmptyClearedPanelCount"], 0)
        self.assertEqual(report["displayQuality"]["sourceBadgeMissingCount"], 0)
        self.assertEqual(report["displayQuality"]["modelOccupiedAllSlotsViolation"], 0)
        self.assertEqual(report["displayQuality"]["longCandidateViolation"], 0)
        self.assertEqual(report["displayQuality"]["postCommitNumberKeyViolation"], 0)
        self.assertEqual(report["displayQuality"]["snapshotOrdinalDriftViolation"], 0)
        self.assertTrue(persisted["passed"])

    def test_soak_report_fails_with_input_source_selection_report_failure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-input-source-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            selection_path = Path(tmp) / "selection.json"
            log_path.write_text("", encoding="utf-8")
            selection_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.macos-input-source-selection.v1",
                        "ok": False,
                        "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                        "failureKind": "tis-select-failed",
                        "tisSelectStatus": -50,
                        "source": {
                            "current": "com.bytedance.inputmethod.doubaoime.pinyin",
                            "selected": False,
                            "thirdPartyEnabled": False,
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
                    "--input-source-selection-report",
                    str(selection_path),
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

        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["passed"])
        self.assertFalse(report["thresholdResults"]["inputSourceSelection"])
        self.assertEqual(report["inputSourceSelection"]["tisSelectStatus"], -50)
        self.assertEqual(report["inputSourceSelection"]["source"]["thirdPartyEnabled"], False)
        self.assertEqual(report["violations"][0]["type"], "input_source_selection_failed")
        self.assertEqual(report["violations"][0]["current"], "com.bytedance.inputmethod.doubaoime.pinyin")

    def test_soak_report_can_require_foreground_backspace_and_app_switch_counts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-coverage-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            events = [
                {
                    "event": "sidecar_request_scheduled",
                    "timestampMs": 1000,
                    "frontAppBundleId": "com.apple.TextEdit",
                    "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                },
                {
                    "event": "display_invalidated_by_input_change",
                    "timestampMs": 1400,
                    "reason": "delete_key",
                    "keyCode": 51,
                },
                {
                    "event": "committed_context_resynced_after_delete",
                    "timestampMs": 1500,
                    "keyCode": 51,
                },
                {
                    "event": "frontend_transaction_invalidated",
                    "timestampMs": 1800,
                    "reason": "front_app_changed",
                },
                {
                    "event": "sidecar_request_scheduled",
                    "timestampMs": 2500,
                    "frontAppBundleId": "com.apple.Notes",
                    "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
                },
            ]
            log_path.write_text(
                "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
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
                    "--min-duration-sec",
                    "1",
                    "--min-backspaces",
                    "1",
                    "--min-app-switches",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["thresholdResults"]["durationSec"])
        self.assertTrue(report["thresholdResults"]["backspaces"])
        self.assertTrue(report["thresholdResults"]["appSwitches"])
        self.assertEqual(report["foregroundCoverage"]["backspaceCount"], 1)
        self.assertEqual(report["foregroundCoverage"]["deleteResyncCount"], 1)
        self.assertGreaterEqual(report["foregroundCoverage"]["appSwitchCount"], 1)
        self.assertGreaterEqual(report["foregroundCoverage"]["durationSec"], 1)

    def test_soak_report_can_require_snapshot_selection_trace_for_side_commits(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-selection-trace-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "report.json"
            candidate = _side_candidate("6", "rag", "session-a")
            log_path.write_text(
                json.dumps(
                    {
                        "event": "number_key_route",
                        "timestampMs": 1,
                        "key": "6",
                        "candidate": candidate,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "side_candidate_commit",
                        "timestampMs": 2,
                        "candidate": candidate,
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
                    "--min-post-commit-followups",
                    "0",
                    "--require-side-commit",
                    "--require-snapshot-selection-trace",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["thresholdResults"]["snapshotSelectionTrace"])
        self.assertEqual(report["selectionQuality"]["pairedSideCommitCount"], 1)
        self.assertEqual(report["selectionQuality"]["snapshotSelectionAcceptedCount"], 0)
        self.assertEqual(report["selectionQuality"]["sideCommitWithoutAcceptedSnapshotSelectionCount"], 1)
        self.assertEqual(report["violations"][0]["type"], "snapshot_selection_trace_missing")

    def test_soak_report_surfaces_trace_privacy_violations(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-privacy-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak.json"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "sidecar_request_scheduled",
                        "timestampMs": 10,
                        "traceIncludesText": False,
                        "rawInput": "zhen shi shu ru",
                        "committedContextHash": "sha256:aaaa",
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
        self.assertEqual(report["violations"][0]["type"], "trace_privacy_violation")
        self.assertEqual(report["violations"][0]["field"], "rawInput")

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

    def test_soak_report_can_require_foreground_multi_model_candidate_panel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-model-multi-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidates = _balanced_quota_candidates(session_fingerprint="session-a")
            for candidate in candidates:
                candidate["snapshotId"] = "snap:model-multi"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {
                            "phase": "composition",
                            "selectionScope": "mixed",
                            "snapshotId": "snap:model-multi",
                        },
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-side-commits",
                    "0",
                    "--min-post-commit-followups",
                    "0",
                    "--min-model-candidates-per-panel",
                    "2",
                    "--min-model-multi-candidate-panels",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["thresholdResults"]["modelMultiCandidatePanels"])
        self.assertEqual(report["thresholds"]["minModelCandidatesPerPanel"], 2)
        self.assertEqual(report["thresholds"]["minModelMultiCandidatePanels"], 1)
        self.assertEqual(report["displayQuality"]["modelCandidatePanelCount"], 1)
        self.assertEqual(report["displayQuality"]["multiModelCandidatePanelCount"], 1)
        self.assertEqual(report["displayQuality"]["maxModelCandidateCountInPanel"], 2)

    def test_soak_report_fails_when_foreground_model_panel_has_only_one_candidate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-model-single-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidates = [
                _side_candidate("1", "model", "session-a"),
                {
                    "label": "2",
                    "selectionKey": "2",
                    "selectionRank": 2,
                    "sourceType": "rime",
                    "selectionAction": "select_rime_candidate",
                    "displayLayout": "fallback",
                    "displayLane": "rime",
                    "badge": _source_badge("rime"),
                    "colorToken": _source_color_token("rime"),
                },
            ]
            for candidate in candidates:
                candidate["snapshotId"] = "snap:model-single"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {
                            "phase": "composition",
                            "selectionScope": "mixed",
                            "snapshotId": "snap:model-single",
                        },
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-side-commits",
                    "0",
                    "--min-post-commit-followups",
                    "0",
                    "--min-model-candidates-per-panel",
                    "2",
                    "--min-model-multi-candidate-panels",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertFalse(report["thresholdResults"]["modelMultiCandidatePanels"])
        self.assertEqual(report["displayQuality"]["modelCandidatePanelCount"], 1)
        self.assertEqual(report["displayQuality"]["multiModelCandidatePanelCount"], 0)
        self.assertEqual(report["displayQuality"]["maxModelCandidateCountInPanel"], 1)
        violation_types = {item["type"] for item in report["violations"]}
        self.assertIn("model_multi_candidate_panel_threshold", violation_types)

    def test_soak_report_can_require_source_triplet_panel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-source-triplet-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidates = _balanced_quota_candidates(session_fingerprint="session-a")
            for candidate in candidates:
                candidate["snapshotId"] = "snap:source-triplet"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {
                            "phase": "composition",
                            "selectionScope": "mixed",
                            "snapshotId": "snap:source-triplet",
                        },
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-side-commits",
                    "0",
                    "--min-post-commit-followups",
                    "0",
                    "--min-source-triplet-panels",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["thresholdResults"]["sourceTripletPanels"])
        self.assertEqual(report["thresholds"]["minSourceTripletPanels"], 1)
        self.assertEqual(report["displayQuality"]["sourceTripletPanelCount"], 1)
        self.assertEqual(report["displayQuality"]["maxSourceFamilyCountInPanel"], 3)

    def test_soak_report_can_require_v1_foreground_acceptance_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-v1-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            events = _v1_foreground_acceptance_events()
            log_path.write_text(
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
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
                    "--require-rime-composition-ok",
                    "--require-post-commit-visible",
                    "--require-source-badges",
                    "--require-post-commit-key-policy",
                    "--require-app-switch-stale-drop",
                    "--require-followup-after-select",
                    "--max-first-visible-ms",
                    "500",
                    "--max-stale-apply-count",
                    "0",
                    "--max-context-echo-count",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["v1Foreground"]["rimeCompositionOk"])
        self.assertTrue(report["v1Foreground"]["postCommitVisible"])
        self.assertTrue(report["v1Foreground"]["postCommitKeyPolicyOk"])
        self.assertTrue(report["v1Foreground"]["appSwitchStaleDropOk"])
        self.assertTrue(report["v1Foreground"]["followupAfterSelectOk"])
        self.assertLessEqual(report["v1Foreground"]["firstPostCommitVisibleMs"], 500)
        self.assertEqual(report["v1Foreground"]["firstUsefulCandidateMs"], report["v1Foreground"]["firstVisibleMs"])
        self.assertEqual(report["v1Foreground"]["modelCandidateCount"], 1)
        self.assertEqual(report["v1Foreground"]["ragMemoryCandidateCount"], 2)
        self.assertEqual(report["v1Foreground"]["rimeCandidateCount"], 1)
        self.assertEqual(report["v1Foreground"]["sourceBadgeCoverage"]["coverageRate"], 1.0)
        self.assertEqual(report["v1Foreground"]["contextEchoCount"], 0)
        self.assertEqual(report["v1Foreground"]["pendingPanelClearCount"], 0)
        self.assertEqual(report["v1Foreground"]["followupRestartCount"], 0)
        self.assertEqual(report["v1Foreground"]["staleAppliedCount"], 0)
        self.assertEqual(report["v1Foreground"]["selectionAcceptedCount"], 1)
        self.assertTrue(report["v1Foreground"]["deleteResyncObserved"])
        self.assertTrue(report["v1Foreground"]["appSwitchInvalidationObserved"])
        self.assertTrue(report["requiredTraceEvents"]["sidecar_response_received"]["observed"])
        self.assertTrue(report["requiredTraceEvents"]["sidecar_progressive_followup_sent"]["observed"])
        self.assertTrue(report["requiredTraceEvents"]["sidecar_progressive_followup_skipped"]["observed"])
        self.assertTrue(report["requiredTraceEvents"]["delete_context_resynced"]["observed"])
        self.assertTrue(report["requiredTraceEvents"]["app_switch_context_invalidated"]["observed"])
        self.assertTrue(report["thresholdResults"]["firstVisibleMs"])
        self.assertTrue(report["thresholdResults"]["contextEchoCount"])

    def test_soak_report_accepts_overlay_as_the_post_commit_prediction_surface(self) -> None:
        root = Path(__file__).resolve().parents[1]
        events = _v1_foreground_acceptance_events()
        post_commit_panel = next(
            event
            for event in events
            if event.get("event") == "panel_display_candidates"
            and event.get("uiMode") == "post_commit_prediction"
        )
        overlay_candidates = []
        for index, candidate in enumerate(post_commit_panel["candidates"], start=1):
            overlay_candidates.append(
                {
                    "sourceType": candidate["sourceType"],
                    "sourceBadge": candidate.get("sourceBadge") or candidate.get("badge"),
                    "colorToken": candidate["colorToken"],
                    "candidateOrdinal": candidate.get("candidateOrdinal") or candidate.get("selectionRank") or index,
                    "candidateStableId": candidate.get("candidateStableId") or f"overlay:{index}",
                    "snapshotId": "snap:v1",
                    "selectionAction": "commit_side_candidate",
                    "isStatus": False,
                    "textHash": f"sha256:{candidate.get('candidateStableId') or index}",
                    "textChars": len(candidate["text"]),
                }
            )
        events.remove(post_commit_panel)
        events.append(
            {
                "event": "assistant_overlay_candidate_visible",
                "timestampMs": 240,
                "phase": "post_commit",
                "uiMode": "post_commit_prediction",
                "snapshotId": "snap:v1",
                "keyPolicy": {
                    "numberKeys": "pass_through",
                    "tab": "accept_top_prediction",
                    "optionNumber": "select_prediction_by_ordinal",
                },
                "candidates": overlay_candidates,
            }
        )
        for event in events:
            if event.get("event") == "tab_key_route":
                event["overlay"] = True
        events.sort(key=lambda item: int(item.get("timestampMs") or 0))

        with tempfile.TemporaryDirectory(prefix="rag-ime-overlay-soak-v1-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            log_path.write_text(
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
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
                    "--require-rime-composition-ok",
                    "--require-assistant-overlay-post-commit",
                    "--require-assistant-overlay-key-policy",
                    "--require-post-commit-visible",
                    "--require-source-badges",
                    "--require-followup-after-select",
                    "--max-first-visible-ms",
                    "500",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue(report["v1Foreground"]["postCommitVisible"])
        self.assertEqual(report["v1Foreground"]["modelCandidateCount"], 1)
        self.assertEqual(report["v1Foreground"]["ragMemoryCandidateCount"], 2)
        self.assertEqual(report["v1Foreground"]["sourceBadgeCoverage"]["coverageRate"], 1.0)
        self.assertTrue(report["thresholdResults"]["assistantOverlayPostCommit"])
        self.assertTrue(report["thresholdResults"]["assistantOverlayKeyPolicy"])

    def test_soak_report_fails_v1_gate_when_post_commit_candidate_echoes_context(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-v1-echo-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            events = _v1_foreground_acceptance_events()
            for event in events:
                if event.get("event") != "panel_display_candidates" or event.get("uiMode") != "post_commit_prediction":
                    continue
                candidates = event.get("candidates")
                self.assertIsInstance(candidates, list)
                candidates[0]["text"] = "整理输入法项目"
                candidates[0]["insertText"] = "整理输入法项目"
            log_path.write_text(
                "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
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
                    "--max-context-echo-count",
                    "0",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["passed"])
        self.assertFalse(report["thresholdResults"]["contextEchoCount"])
        self.assertEqual(report["violations"][-1]["type"], "context_echo_threshold")
        self.assertEqual(report["v1Foreground"]["contextEchoCount"], 1)

    def test_soak_report_fails_source_triplet_when_rime_lane_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-source-triplet-missing-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidates = _balanced_quota_candidates(session_fingerprint="session-a")[:-1]
            for candidate in candidates:
                candidate["snapshotId"] = "snap:source-triplet-missing"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {
                            "phase": "composition",
                            "selectionScope": "mixed",
                            "snapshotId": "snap:source-triplet-missing",
                        },
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
                    str(root / "scripts" / "check_squirrel_soak_report.py"),
                    "--log-path",
                    str(log_path),
                    "--report-path",
                    str(report_path),
                    "--min-sidecar-requests",
                    "0",
                    "--min-sidecar-applied",
                    "0",
                    "--min-side-commits",
                    "0",
                    "--min-post-commit-followups",
                    "0",
                    "--min-source-triplet-panels",
                    "1",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertFalse(report["passed"])
        self.assertFalse(report["thresholdResults"]["sourceTripletPanels"])
        self.assertEqual(report["displayQuality"]["sourceTripletPanelCount"], 0)
        self.assertEqual(report["displayQuality"]["maxSourceFamilyCountInPanel"], 2)
        violation_types = {item["type"] for item in report["violations"]}
        self.assertIn("source_triplet_panel_threshold", violation_types)

    def test_soak_report_allows_progressive_append_without_ordinal_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-progressive-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            first = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            first.update({"snapshotId": "snap:append", "candidateStableId": "model:first", "candidateOrdinal": 1, "text": "继续"})
            second = _side_candidate(label="2", source_type="rag", session_fingerprint="session-a")
            second.update({"snapshotId": "snap:append", "candidateStableId": "rag:second", "candidateOrdinal": 2, "text": "继续写"})
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {"snapshotId": "snap:append", "phase": "post_commit", "selectionScope": "prediction"},
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [first],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "candidate_snapshot_progressive_append",
                        "timestampMs": 2,
                        "fields": {
                            "snapshotId": "snap:append",
                            "previousSnapshotId": "snap:append",
                            "preservedOrdinalCount": 1,
                            "appendedCandidateCount": 1,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 3,
                        "predictionSession": {"snapshotId": "snap:append", "phase": "post_commit", "selectionScope": "prediction"},
                        "candidateCounts": {"total": 2, "modelInline": 1, "ragBlock": 1, "rime": 0},
                        "candidates": [first, second],
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
                check=True,
            )

        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["displayQuality"]["progressiveAppendCount"], 1)
        self.assertEqual(report["displayQuality"]["snapshotOrdinalDriftViolation"], 0)

    def test_soak_report_fails_when_snapshot_reuses_ordinal_for_different_candidate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-ordinal-drift-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            first = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            first.update({"snapshotId": "snap:drift", "candidateStableId": "model:first", "candidateOrdinal": 1, "text": "继续"})
            changed = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            changed.update({"snapshotId": "snap:drift", "candidateStableId": "model:changed", "candidateOrdinal": 1, "text": "换了"})
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "predictionSession": {"snapshotId": "snap:drift"},
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [first],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 2,
                        "predictionSession": {"snapshotId": "snap:drift"},
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [changed],
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
        self.assertEqual(report["displayQuality"]["snapshotOrdinalDriftViolation"], 1)
        self.assertIn("snapshot_ordinal_drift", {item["type"] for item in report["violations"]})

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

    def test_soak_report_fails_post_commit_request_after_observe_timeout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-commit-timeout-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidate = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            candidate["text"] = "连续候选"
            candidate["insertText"] = "连续候选"
            log_path.write_text(
                "\n".join(
                    json.dumps(event, ensure_ascii=False)
                    for event in [
                        {"event": "side_candidate_commit", "timestampMs": 1, "candidate": candidate},
                        {
                            "event": "commit_observe_timeout",
                            "timestampMs": 2,
                            "reason": "committed_context_not_observed",
                        },
                        {
                            "event": "post_commit_prediction_scheduled",
                            "timestampMs": 3,
                            "selectionKey": "1",
                        },
                        {
                            "event": "sidecar_request_scheduled",
                            "timestampMs": 4,
                            "rawInput": "",
                            "preedit": "",
                            "commitTextPreview": "连续候选",
                            "committedContextChars": 12,
                            "committedContextHash": "sha256:aftertimeout",
                        },
                    ]
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
        self.assertEqual(report["metrics"]["postCommitFollowupCount"], 0)
        self.assertEqual(report["metrics"]["postCommitBarrierViolationCount"], 1)
        violation = report["violations"][0]
        self.assertEqual(violation["type"], "post_commit_after_cancel")
        self.assertEqual(violation["cancelEvent"], "commit_observe_timeout")

    def test_soak_report_fails_post_commit_request_after_delete_invalidation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-soak-delete-cancel-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            report_path = Path(tmp) / "soak-report.json"
            candidate = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            candidate["text"] = "删除前候选"
            candidate["insertText"] = "删除前候选"
            log_path.write_text(
                "\n".join(
                    json.dumps(event, ensure_ascii=False)
                    for event in [
                        {"event": "side_candidate_commit", "timestampMs": 1, "candidate": candidate},
                        {
                            "event": "display_invalidated_by_input_change",
                            "timestampMs": 2,
                            "reason": "delete_key",
                            "keyCode": 51,
                        },
                        {
                            "event": "sidecar_request_scheduled",
                            "timestampMs": 3,
                            "rawInput": "",
                            "preedit": "",
                            "commitTextPreview": "删除前候选",
                            "committedContextChars": 9,
                            "committedContextHash": "sha256:staleafterdelete",
                        },
                    ]
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
        self.assertEqual(report["metrics"]["postCommitFollowupCount"], 0)
        self.assertEqual(report["metrics"]["postCommitBarrierViolationCount"], 1)
        violation = report["violations"][0]
        self.assertEqual(violation["type"], "post_commit_after_cancel")
        self.assertEqual(violation["cancelEvent"], "display_invalidated_by_input_change")
        self.assertEqual(violation["cancelReason"], "delete_key")

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

    def test_trace_check_can_require_post_commit_prediction_ux_v1(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-ux-v1-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            rime_candidate = {
                "label": "1",
                "selectionKey": "1",
                "selectionRank": 1,
                "candidateOrdinal": 1,
                "candidateStableId": "rime:出现",
                "sourceType": "rime",
                "selectionAction": "select_rime_candidate",
                "displayLayout": "fallback",
                "displayLane": "rime",
                "badge": _source_badge("rime"),
                "colorToken": _source_color_token("rime"),
            }
            status = _status_candidate()
            first_prediction = _side_candidate(label="1", source_type="rag", session_fingerprint="session-a")
            first_prediction.update(
                {
                    "snapshotId": "snap:post",
                    "candidateStableId": "rag:first",
                    "candidateOrdinal": 1,
                    "text": "候选稳定性",
                }
            )
            second_prediction = _side_candidate(label="2", source_type="model", session_fingerprint="session-a")
            second_prediction.update(
                {
                    "snapshotId": "snap:post",
                    "candidateStableId": "model:second",
                    "candidateOrdinal": 2,
                    "text": "可以继续预测",
                }
            )
            events = [
                {
                    "event": "sidecar_response_applied",
                    "timestampMs": 1,
                    "uiMode": "composition_rime",
                    "predictionSession": {"phase": "anchor_composing", "inputMode": "anchor_composing"},
                },
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 2,
                    "uiMode": "composition_rime",
                    "rawInput": "chuxian",
                    "preedit": "chuxian",
                    "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 0, "rime": 1},
                    "candidates": [rime_candidate],
                },
                {
                    "event": "sidecar_response_applied",
                    "timestampMs": 3,
                    "uiMode": "post_commit_pending",
                    "laneStatus": {"rag": {"state": "pending"}, "model": {"state": "pending"}},
                    "predictionSession": {"phase": "post_commit", "selectionScope": "prediction", "expiresAfterMs": 9000},
                    "candidates": [status],
                },
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 4,
                    "uiMode": "post_commit_pending",
                    "predictionSession": {"phase": "post_commit", "selectionScope": "prediction", "snapshotId": "snap:post"},
                    "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 0, "rime": 0},
                    "candidates": [status],
                },
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 5,
                    "uiMode": "post_commit_prediction",
                    "predictionSession": {"phase": "post_commit", "selectionScope": "prediction", "snapshotId": "snap:post"},
                    "candidateCounts": {"total": 2, "modelInline": 0, "ragBlock": 1, "rime": 0},
                    "candidates": [status, first_prediction],
                },
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 6,
                    "uiMode": "post_commit_prediction",
                    "predictionSession": {"phase": "post_commit", "selectionScope": "prediction", "snapshotId": "snap:post"},
                    "candidateCounts": {"total": 3, "modelInline": 1, "ragBlock": 1, "rime": 0},
                    "candidates": [status, first_prediction, second_prediction],
                },
            ]
            log_path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--require-rime-composition-mode",
                    "--require-post-commit-pending-status",
                    "--require-prediction-status-visible",
                    "--require-source-badges",
                    "--max-renumber-rate",
                    "0",
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
        self.assertEqual(report["required"]["rimeCompositionMode"], True)
        self.assertEqual(report["latestRimeCompositionMode"]["uiMode"], "composition_rime")
        self.assertEqual(report["latestPostCommitPendingStatus"]["uiMode"], "post_commit_pending")
        self.assertEqual(report["latestPredictionStatusVisible"]["candidates"][0]["sourceType"], "status")
        self.assertEqual(report["candidateRenumber"]["renumberRate"], 0.0)

    def test_trace_check_rejects_renumber_when_strict_append_only_required(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-renumber-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            first = _side_candidate(label="1", source_type="rag", session_fingerprint="session-a")
            first.update({"snapshotId": "snap:renumber", "candidateStableId": "rag:first", "candidateOrdinal": 1})
            changed = _side_candidate(label="1", source_type="model", session_fingerprint="session-a")
            changed.update({"snapshotId": "snap:renumber", "candidateStableId": "model:changed", "candidateOrdinal": 1})
            events = [
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 1,
                    "predictionSession": {"phase": "post_commit", "snapshotId": "snap:renumber"},
                    "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 1, "rime": 0},
                    "candidates": [first],
                },
                {
                    "event": "panel_display_candidates",
                    "timestampMs": 2,
                    "predictionSession": {"phase": "post_commit", "snapshotId": "snap:renumber"},
                    "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                    "candidates": [changed],
                },
            ]
            log_path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(root / "scripts" / "check_squirrel_frontend_trace.py"),
                    "--log-path",
                    str(log_path),
                    "--max-renumber-rate",
                    "0",
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
        self.assertEqual(report["candidateRenumber"]["violationCount"], 1)
        self.assertEqual(
            report["candidateRenumberViolations"][0]["reason"],
            "candidate_ordinal_reused_for_different_stable_id",
        )

    def test_trace_check_rejects_status_only_panel_as_side_panel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-status-only-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "uiMode": "post_commit_pending",
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [_status_candidate()],
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
        self.assertIsNone(report["latestSidePanel"])

    def test_trace_check_rejects_side_panel_without_candidate_details(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-no-candidates-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "uiMode": "post_commit_prediction",
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
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
        self.assertIsNone(report["latestSidePanel"])

    def test_trace_check_rejects_status_only_panel_as_source_badge_proof(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-status-badge-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "uiMode": "post_commit_pending",
                        "candidateCounts": {"total": 1, "modelInline": 0, "ragBlock": 0, "rime": 0},
                        "candidates": [_status_candidate()],
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
                    "--require-source-badges",
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
        self.assertIsNone(report["latestSourceBadgePanel"])

    def test_trace_check_rejects_status_candidate_as_side_commit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        status = _status_candidate()
        status.update({"label": "1", "selectionKey": "1", "selectionAction": "commit_side_candidate"})
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-trace-status-commit-") as tmp:
            log_path = Path(tmp) / "trace.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "event": "panel_display_candidates",
                        "timestampMs": 1,
                        "uiMode": "post_commit_prediction",
                        "candidateCounts": {"total": 1, "modelInline": 1, "ragBlock": 0, "rime": 0},
                        "candidates": [status],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "tab_key_route", "timestampMs": 2, "key": "tab", "candidate": status},
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {"event": "side_candidate_commit", "timestampMs": 3, "candidate": status},
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
                    "--require-side-commit",
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
        self.assertIsNone(report["latestValidSideCommit"])
        self.assertIsNone(report["latestSideSelectionCommit"])

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


def _status_candidate() -> dict[str, object]:
    return {
        "label": "",
        "selectionKey": "",
        "selectionRank": 0,
        "candidateOrdinal": 0,
        "sourceType": "status",
        "selectionAction": "none",
        "displayLayout": "status_row",
        "displayLane": "post_commit_status",
        "badge": _source_badge("status"),
        "colorToken": _source_color_token("status"),
        "isSelectable": False,
        "isStatus": True,
        "text": "查忆处理中…",
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


def _v1_foreground_acceptance_events() -> list[dict[str, object]]:
    commit_candidate = _side_candidate("1", "model", "session-v1")
    commit_candidate["text"] = "候选质量通过"
    commit_candidate["insertText"] = "候选质量通过"
    commit_candidate["snapshotId"] = "snap:v1"
    post_commit_candidates = [
        dict(commit_candidate),
        _side_candidate("2", "rag", "session-v1"),
        _side_candidate("3", "memory", "session-v1"),
    ]
    post_commit_candidates[0]["text"] = "后续候选优化"
    post_commit_candidates[0]["insertText"] = "后续候选优化"
    post_commit_candidates[1]["text"] = "记忆整理完成"
    post_commit_candidates[1]["insertText"] = "记忆整理完成"
    post_commit_candidates[1]["snapshotId"] = "snap:v1"
    post_commit_candidates[2]["text"] = "前台链路可验收"
    post_commit_candidates[2]["insertText"] = "前台链路可验收"
    post_commit_candidates[2]["snapshotId"] = "snap:v1"
    rime_candidate = {
        "label": "1",
        "selectionKey": "1",
        "selectionRank": 1,
        "sourceType": "rime",
        "selectionAction": "select_rime_candidate",
        "displayLayout": "fallback",
        "displayLane": "rime",
        "badge": _source_badge("rime"),
        "colorToken": _source_color_token("rime"),
        "text": "shu",
    }
    return [
        {
            "event": "rime_composition_started",
            "timestampMs": 5,
            "rawInput": "shu",
            "preedit": "shu",
        },
        {
            "event": "sidecar_request_scheduled",
            "timestampMs": 10,
            "rawInput": "shu",
            "preedit": "shu",
        },
        {
            "event": "rime_composition_candidates_visible",
            "timestampMs": 18,
        },
        {
            "event": "panel_display_candidates",
            "timestampMs": 20,
            "rawInput": "shu",
            "preedit": "shu",
            "candidates": [rime_candidate],
        },
        {"event": "sidecar_response_received", "timestampMs": 35},
        {
            "event": "sidecar_response_applied",
            "timestampMs": 40,
            "responseAgeMs": 20,
            "requestFrontendRevision": 1,
            "responseFrontendRevision": 1,
            "liveFrontendRevision": 1,
            "requestSelectionEpoch": 1,
            "responseSelectionEpoch": 1,
            "liveSelectionEpoch": 1,
        },
        {
            "event": "candidate_snapshot_selection_accepted",
            "timestampMs": 70,
            "fields": {"snapshotId": "snap:v1"},
        },
        {
            "event": "tab_key_route",
            "timestampMs": 75,
            "key": "tab",
            "candidate": commit_candidate,
        },
        {"event": "side_candidate_commit", "timestampMs": 80, "candidate": commit_candidate},
        {
            "event": "side_candidate_feedback_recorded",
            "timestampMs": 82,
            "ok": True,
            "eventId": "event:v1",
            "recordedActionCount": 1,
            "candidate": commit_candidate,
        },
        {"event": "side_candidate_commit_observed", "timestampMs": 85, "candidate": commit_candidate},
        {
            "event": "commit_observed",
            "timestampMs": 100,
            "committedText": "候选质量通过",
            "committedContextChars": 12,
        },
        {"event": "post_commit_prediction_scheduled", "timestampMs": 120},
        {
            "event": "panel_display_candidates",
            "timestampMs": 240,
            "uiMode": "post_commit_prediction",
            "committedContext": "整理输入法项目",
            "commitTextPreview": "候选质量通过",
            "predictionSession": {
                "phase": "post_commit",
                "selectionScope": "prediction",
                "snapshotId": "snap:v1",
            },
            "candidates": post_commit_candidates,
        },
        {
            "event": "post_commit_prediction_applied",
            "timestampMs": 245,
            "uiMode": "post_commit_prediction",
        },
        {"event": "sidecar_progressive_followup_sent", "timestampMs": 250},
        {
            "event": "sidecar_request_scheduled",
            "timestampMs": 260,
            "rawInput": "",
            "preedit": "",
            "commitTextPreview": "候选质量通过",
            "committedContextChars": 12,
            "progressiveFollowUp": True,
        },
        {"event": "sidecar_progressive_followup_skipped", "timestampMs": 270, "reason": "already_current"},
        {"event": "committed_context_resynced_after_delete", "timestampMs": 290},
        {
            "event": "frontend_transaction_invalidated",
            "timestampMs": 300,
            "reason": "app_switch",
        },
        {
            "event": "frontend_transaction_invalidated",
            "timestampMs": 310,
            "reason": "focus_lost",
        },
        {"event": "sidecar_response_dropped_stale", "timestampMs": 320},
    ]


def _source_badge(source_type: str) -> str:
    return {
        "rime": "词",
        "model": "模",
        "rag": "查",
        "memory": "忆",
        "raw_english": "input",
        "status": "查忆",
    }[source_type]


def _source_color_token(source_type: str) -> str:
    return {
        "rime": "rimeOrange",
        "model": "modelBlue",
        "rag": "ragTeal",
        "memory": "memoryPurple",
        "raw_english": "rawGray",
        "status": "statusGray",
    }[source_type]


if __name__ == "__main__":
    unittest.main()
