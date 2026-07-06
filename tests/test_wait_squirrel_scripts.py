from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class WaitSquirrelScriptsTests(unittest.TestCase):
    def test_soak_foreground_dry_run_requires_continuous_chain_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--chain-repeats",
                "7",
                "--auto-key",
                "4",
                "--report-path",
                "/tmp/custom-rag-ime-soak-report.json",
            ],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("chain_repeats=7", result.stdout)
        self.assertIn("min_chain_depth=7", result.stdout)
        self.assertIn("require_snapshot_selection_trace=1", result.stdout)
        self.assertIn("select_report_path=/tmp/custom-rag-ime-soak-report.input-source-selection.json", result.stdout)
        self.assertIn("--min-chain-depth 7", result.stdout)
        self.assertIn("--require-snapshot-selection-trace", result.stdout)
        self.assertIn("--report-path /tmp/custom-rag-ime-soak-report.json", result.stdout)

    def test_soak_foreground_dry_run_disables_chain_requirement_without_followup(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-followup",
            ],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("min_post_commit_followups=0", result.stdout)
        self.assertIn("min_chain_depth=0", result.stdout)
        self.assertIn("--min-chain-depth 0", result.stdout)

    def test_soak_foreground_dry_run_can_disable_snapshot_selection_trace_requirement(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                str(root / "scripts" / "soak_squirrel_foreground_trace.sh"),
                "--dry-run",
                "--no-snapshot-selection-trace",
            ],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("require_snapshot_selection_trace=0", result.stdout)
        self.assertNotIn("--require-snapshot-selection-trace", result.stdout)

    def test_prepare_foreground_check_waits_for_typing_when_source_needs_switch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-switch-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            audit_script = tmp_path / "audit.sh"
            open_script = tmp_path / "open.sh"
            wait_typing_script = tmp_path / "wait-typing.sh"
            wait_log = tmp_path / "wait-typing.log"
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"switch","nextAction":"select Squirrel from the macOS input menu"},"launchServices":{"duplicatePathCount":0}}',
                        "JSON",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            open_script.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
            wait_typing_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo wait-typing > {wait_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            audit_script.chmod(0o755)
            open_script.chmod(0o755)
            wait_typing_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                    "RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT": str(open_script),
                    "RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT": str(wait_typing_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            wait_log_exists = wait_log.exists()

        self.assertIn("readiness_state=switch", result.stdout)
        self.assertIn("waiting for selected input source", result.stdout)
        self.assertTrue(wait_log_exists)

    def test_prepare_foreground_check_opens_settings_when_third_party_source_is_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-add-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            audit_script = tmp_path / "audit.sh"
            open_script = tmp_path / "open.sh"
            wait_typing_script = tmp_path / "wait-typing.sh"
            open_log = tmp_path / "open.log"
            wait_log = tmp_path / "wait-typing.log"
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"third-party-missing","nextAction":"add Squirrel in System Settings"},"launchServices":{"duplicatePathCount":1,"matchingRecords":[{"path":"/Users/me/Library/Input Methods/Squirrel.app"},{"path":"/Users/me/Desktop/backup/Squirrel.app"}]}}',
                        "JSON",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            open_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"printf '%s\\n' \"$@\" > {open_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            wait_typing_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo wait-typing > {wait_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            audit_script.chmod(0o755)
            open_script.chmod(0o755)
            wait_typing_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                    "RAG_IME_OPEN_INPUT_SOURCE_SETTINGS_SCRIPT": str(open_script),
                    "RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT": str(wait_typing_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            open_args = open_log.read_text(encoding="utf-8").strip()
            wait_log_exists = wait_log.exists()

        self.assertIn("readiness_state=third-party-missing", result.stdout)
        self.assertIn("duplicate_squirrel_app_paths=1", result.stdout)
        self.assertIn("matching_squirrel_app_path=/Users/me/Desktop/backup/Squirrel.app", result.stdout)
        self.assertIn("duplicate_cleanup_hint=scripts/prepare_squirrel_foreground_check.sh --refresh-registration", result.stdout)
        self.assertIn("duplicate_quarantine_hint=RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS=1 scripts/refresh_squirrel_input_source_registration.sh", result.stdout)
        self.assertIn("third_party_allow_list_missing=1", result.stdout)
        self.assertIn("command_line_repair_hint=scripts/enable_squirrel_hitoolbox_input_source.sh", result.stdout)
        self.assertIn("command_line_repair_report_hint=scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json", result.stdout)
        self.assertIn("manual_add_hint=scripts/open_squirrel_input_source_settings.sh --wait", result.stdout)
        self.assertEqual(open_args, "--wait")
        self.assertTrue(wait_log_exists)

    def test_prepare_foreground_check_can_refresh_registration_before_audit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-refresh-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            call_log = tmp_path / "calls.log"
            refresh_script = tmp_path / "refresh.sh"
            audit_script = tmp_path / "audit.sh"
            wait_typing_script = tmp_path / "wait-typing.sh"
            refresh_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo refresh >> {call_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo audit >> {call_log}",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"ready","nextAction":"type in a foreground text field"},"launchServices":{"duplicatePathCount":0,"matchingRecords":[]}}',
                        "JSON",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            wait_typing_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo wait-typing >> {call_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            refresh_script.chmod(0o755)
            audit_script.chmod(0o755)
            wait_typing_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--refresh-registration",
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_REFRESH_SQUIRREL_INPUT_SOURCE_REGISTRATION_SCRIPT": str(refresh_script),
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                    "RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT": str(wait_typing_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            calls = call_log.read_text(encoding="utf-8").splitlines()

        self.assertIn("refreshing LaunchServices/Squirrel input-source registration", result.stdout)
        self.assertEqual(calls, ["refresh", "audit", "wait-typing"])

    def test_prepare_foreground_check_continues_audit_when_refresh_fails(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-refresh-fail-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            call_log = tmp_path / "calls.log"
            refresh_script = tmp_path / "refresh.sh"
            audit_script = tmp_path / "audit.sh"
            refresh_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo refresh >> {call_log}",
                        "exit 7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo audit >> {call_log}",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"ready","nextAction":"type in a foreground text field"},"launchServices":{"duplicatePathCount":0,"matchingRecords":[]}}',
                        "JSON",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            refresh_script.chmod(0o755)
            audit_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--refresh-registration",
                    "--no-wait-typing",
                    "--report-path",
                    str(report_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_REFRESH_SQUIRREL_INPUT_SOURCE_REGISTRATION_SCRIPT": str(refresh_script),
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            calls = call_log.read_text(encoding="utf-8").splitlines()

        self.assertIn("refresh_registration_exit_code=7", result.stdout)
        self.assertIn("readiness_state=ready", result.stdout)
        self.assertEqual(calls, ["refresh", "audit"])

    def test_prepare_foreground_check_does_not_claim_ready_when_manual_flow_is_skipped(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-pending-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            summary_path = tmp_path / "foreground-readiness.json"
            audit_script = tmp_path / "audit.sh"
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"third-party-missing","nextAction":"add Squirrel in System Settings"},"launchServices":{"duplicatePathCount":0}}',
                        "JSON",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            audit_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--report-path",
                    str(report_path),
                    "--summary-path",
                    str(summary_path),
                    "--no-open",
                    "--no-wait-typing",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                },
                text=True,
                capture_output=True,
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 1)
        self.assertIn("readiness_state=third-party-missing", result.stdout)
        self.assertIn(f"readiness_summary={summary_path}", result.stdout)
        self.assertIn("duplicate_squirrel_app_paths=0", result.stdout)
        self.assertIn("third_party_allow_list_missing=1", result.stdout)
        self.assertIn("manual_add_hint=scripts/open_squirrel_input_source_settings.sh --wait", result.stdout)
        self.assertIn("foreground trace verification is still pending", result.stdout)
        self.assertNotIn("ready for foreground trace verification", result.stdout)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["exitCode"], 1)
        self.assertEqual(summary["readinessState"], "third-party-missing")
        self.assertFalse(summary["foregroundReady"])
        self.assertIn("scripts/open_squirrel_input_source_settings.sh --wait", summary["commands"])
        self.assertIn(
            "scripts/enable_squirrel_hitoolbox_input_source.sh --dry-run --report-path /tmp/rag-ime-squirrel-repair-dryrun.json",
            summary["commands"],
        )
        self.assertTrue(any("System Settings" in item for item in summary["manualRequired"]))

    def test_prepare_foreground_check_summary_reports_ready_next_trace_command(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-prepare-foreground-summary-ready-") as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "audit.json"
            summary_path = tmp_path / "foreground-readiness.json"
            audit_script = tmp_path / "audit.sh"
            wait_typing_script = tmp_path / "wait-typing.sh"
            audit_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --report-path) report=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$report\" <<'JSON'",
                        '{"readiness":{"state":"ready","nextAction":"type in a foreground text field"},"launchServices":{"duplicatePathCount":0,"matchingRecords":[]}}',
                        "JSON",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            wait_typing_script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            audit_script.chmod(0o755)
            wait_typing_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "prepare_squirrel_foreground_check.sh"),
                    "--report-path",
                    str(report_path),
                    "--summary-path",
                    str(summary_path),
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_AUDIT_SQUIRREL_INPUT_SOURCE_SCRIPT": str(audit_script),
                    "RAG_IME_WAIT_SQUIRREL_TYPING_READY_SCRIPT": str(wait_typing_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertIn("ready for foreground trace verification", result.stdout)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["readinessState"], "ready")
        self.assertTrue(summary["foregroundReady"])
        self.assertEqual(summary["manualRequired"], [])
        self.assertIn("scripts/verify_squirrel_foreground_trace.sh", summary["commands"])

    def test_open_settings_helper_skips_open_when_source_is_already_added(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-open-source-added-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            open_script = tmp_path / "open-should-not-run.sh"
            open_log = tmp_path / "open.log"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true thirdPartyEnabled=true'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            open_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"echo unexpected > {open_log}",
                        "exit 7",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)
            open_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "open_squirrel_input_source_settings.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_OPEN_COMMAND": str(open_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("already fully added", result.stdout)
        self.assertFalse(open_log.exists())

    def test_open_settings_helper_opens_keyboard_settings_when_source_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-open-source-missing-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            open_script = tmp_path / "fake-open.sh"
            open_log = tmp_path / "open.log"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            open_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"printf '%s\\n' \"$1\" > {open_log}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)
            open_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "open_squirrel_input_source_settings.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_OPEN_COMMAND": str(open_script),
                },
                check=True,
                text=True,
                capture_output=True,
            )

            opened_url = open_log.read_text(encoding="utf-8").strip()

        self.assertIn("Manual Add flow", result.stdout)
        self.assertIn("scripts/wait_squirrel_input_source_added.sh", result.stdout)
        self.assertEqual(opened_url, "x-apple.systempreferences:com.apple.Keyboard-Settings.extension")

    def test_open_settings_helper_uses_branded_input_source_name(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-open-branded-source-") as tmp:
            tmp_path = Path(tmp)
            check_script = tmp_path / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rag-ime.inputmethod.RagIme.Hans name=RAG-IME - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                [
                    "bash",
                    str(root / "scripts" / "open_squirrel_input_source_settings.sh"),
                    "--no-open",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_SQUIRREL_INPUT_SOURCE_ID": "im.rag-ime.inputmethod.RagIme.Hans",
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("RAG-IME is not fully added", result.stdout)
        self.assertIn("Chinese, Simplified -> RAG-IME - Simplified", result.stdout)

    def test_wait_input_source_added_succeeds_when_strict_check_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-source-") as tmp:
            check_script = Path(tmp) / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=true thirdPartyEnabled=true'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "wait_squirrel_input_source_added.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS": "1",
                },
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("input-source-added:", result.stdout)
        self.assertIn("thirdPartyEnabled=true", result.stdout)

    def test_wait_input_source_added_timeout_points_to_settings_helper(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-source-timeout-") as tmp:
            check_script = Path(tmp) / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "wait_squirrel_input_source_added.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_INPUT_SOURCE_ADDED_TIMEOUT_SECONDS": "1",
                    "RAG_IME_INPUT_SOURCE_ADDED_POLL_SECONDS": "1",
                },
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("thirdPartyEnabled=false", result.stderr)
        self.assertIn("open_squirrel_input_source_settings.sh --wait", result.stderr)

    def test_wait_typing_ready_fails_fast_when_squirrel_is_not_fully_added(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wait-typing-") as tmp:
            check_script = Path(tmp) / "check-input-source.sh"
            check_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false current=com.apple.keylayout.ABC hitoolboxEnabled=false thirdPartyEnabled=false'",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            check_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(root / "scripts" / "wait_squirrel_typing_ready.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_CHECK_INPUT_SOURCE_SCRIPT": str(check_script),
                    "RAG_IME_TYPING_READY_TIMEOUT_SECONDS": "1",
                },
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not fully added", result.stderr)
        self.assertIn("thirdPartyEnabled=false", result.stderr)
        self.assertIn("open_squirrel_input_source_settings.sh --wait", result.stderr)
        self.assertIn("wait_squirrel_input_source_added.sh", result.stderr)


if __name__ == "__main__":
    unittest.main()
