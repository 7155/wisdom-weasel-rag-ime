from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from rag_ime.management_service import ManagementService
from rag_ime.runtime_config import RuntimeConfigResolver
from rag_ime.settings_store import ManagementSettingsStore


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLifecycleControlPlaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-runtime-lifecycle-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.project = "wisdom-weasel-rag-ime"
        self.settings_store = ManagementSettingsStore(self.db_path)
        self.settings_store.initialize()
        resolver = RuntimeConfigResolver(self.settings_store, environ={})
        self.management = ManagementService(
            db_path=self.db_path,
            project=self.project,
            repo_root=ROOT,
            settings_store=self.settings_store,
            health_provider=lambda: {"ok": True},
            input_source_provider=lambda: {},
            predictor_provider=lambda: {},
            runtime_config_provider=resolver.resolve,
        )

    def tearDown(self) -> None:
        self.management.close()
        self.tmp.cleanup()

    def _terminal_job(self, job_id: str) -> dict[str, object]:
        for _ in range(100):
            response = self.management.runtime_job(job_id)
            job = response["job"]
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.01)
        self.fail(f"runtime job did not reach terminal state: {job_id}")

    def test_pause_and_resume_only_toggle_live_post_commit_setting(self) -> None:
        with patch("rag_ime.management_service.subprocess.run") as run_process:
            stopped = self.management.start_runtime_action({"action": "stop_ai"})
            stopped_job = self._terminal_job(str(stopped["jobId"]))

            self.assertEqual(stopped_job["status"], "succeeded")
            self.assertTrue(stopped_job["result"]["aiPaused"])
            self.assertFalse(
                self.settings_store.get_settings(include_sensitive=True)["interaction"]["postCommit"]["enabled"]
            )
            self.assertTrue(self.management.health_provider()["ok"])

            resumed = self.management.start_runtime_action({"action": "resume_ai"})
            resumed_job = self._terminal_job(str(resumed["jobId"]))

            self.assertEqual(resumed_job["status"], "succeeded")
            self.assertFalse(resumed_job["result"]["aiPaused"])
            self.assertTrue(
                self.settings_store.get_settings(include_sensitive=True)["interaction"]["postCommit"]["enabled"]
            )
            run_process.assert_not_called()

    def test_sidecar_owned_restart_is_terminal_external_supervisor_job(self) -> None:
        response = self.management.start_runtime_action({"action": "restart_sidecar"})
        job = response["job"]

        self.assertEqual(job["status"], "external-supervisor-required")
        self.assertEqual(job["result"]["code"], "external-supervisor-required")
        self.assertIn("external supervisor", job["error"])
        self.assertEqual(
            self.management.runtime_job(str(response["jobId"]))["job"]["status"],
            "external-supervisor-required",
        )

    def test_diagnostics_action_preview_binds_revision_payload_and_command_before_job_start(self) -> None:
        revision = self.management.revision().runtime_revision
        preview = self.management.runtime_action_preview(
            {"action": "restart_sidecar", "expectedRuntimeRevision": revision}
        )

        self.assertTrue(preview["ok"])
        self.assertEqual(preview["pathId"], "diagnostics.action.start")
        self.assertTrue(str(preview["payloadSha256"]).startswith("sha256:"))
        self.assertTrue(str(preview["commandSha256"]).startswith("sha256:"))
        self.assertTrue(preview["externalSupervisorRequired"])

        started = self.management.runtime_action_start(
            {
                "action": "restart_sidecar",
                "expectedRuntimeRevision": revision,
                "previewToken": preview["previewToken"],
                "payloadSha256": preview["payloadSha256"],
                "commandSha256": preview["commandSha256"],
                "confirmText": "apply",
            }
        )
        job_id = str(started["result"]["jobId"])
        job = self.management.runtime_job(job_id)["job"]

        self.assertEqual(job["status"], "external-supervisor-required")
        self.assertNotIn("externalCommand", job["result"])
        self.assertEqual(job["result"]["externalAction"]["receiptId"], job_id)
        self.assertEqual(job["result"]["externalAction"]["payloadSha256"], preview["payloadSha256"])
        self.assertEqual(job["result"]["externalAction"]["commandSha256"], preview["commandSha256"])

    def test_diagnostics_action_rejects_command_tampering_and_consumed_preview_replay(self) -> None:
        revision = self.management.revision().runtime_revision
        preview = self.management.runtime_action_preview(
            {"action": "open_accessibility_settings", "expectedRuntimeRevision": revision}
        )
        request = {
            "action": "open_accessibility_settings",
            "expectedRuntimeRevision": revision,
            "previewToken": preview["previewToken"],
            "payloadSha256": preview["payloadSha256"],
            "commandSha256": "sha256:" + "0" * 64,
            "confirmText": "apply",
        }

        tampered = self.management.runtime_action_start(request)
        self.assertFalse(tampered["ok"])
        self.assertEqual(tampered["errorCode"], "command_hash_mismatch")

        request["commandSha256"] = preview["commandSha256"]
        applied = self.management.runtime_action_start(request)
        replayed = self.management.runtime_action_start(request)
        self.assertTrue(applied["ok"])
        self.assertFalse(replayed["ok"])
        self.assertEqual(replayed["errorCode"], "preview_already_used")

    def test_runtime_helpers_resolve_from_explicit_source_root(self) -> None:
        source_root = Path(self.tmp.name) / "source-checkout"
        scripts = source_root / "scripts"
        scripts.mkdir(parents=True)
        redeploy = scripts / "install_squirrel_rag_config.sh"
        repair = scripts / "repair_rag_ime_launch_agents.sh"
        refresh = scripts / "refresh_squirrel_input_source_registration.sh"
        redeploy.write_text("#!/bin/bash\n", encoding="utf-8")
        repair.write_text("#!/bin/bash\n", encoding="utf-8")
        refresh.write_text("#!/bin/bash\n", encoding="utf-8")

        with patch.dict(os.environ, {"RAG_IME_SOURCE_ROOT": str(source_root)}, clear=False):
            command = self.management._command_for_action("redeploy_rime")
            register_command = self.management._command_for_action("register_input_source")
            response = self.management.start_runtime_action({"action": "repair_launch_agents"})

        self.assertEqual(command, ["/bin/bash", str(redeploy)])
        self.assertEqual(register_command, ["/bin/bash", str(refresh)])
        self.assertEqual(response["job"]["status"], "external-supervisor-required")
        self.assertEqual(response["job"]["result"]["externalCommand"], ["/bin/bash", str(repair)])

    def test_supervised_repair_preserves_frontend_and_product_profile(self) -> None:
        helper = (ROOT / "scripts" / "repair_rag_ime_launch_agents.sh").read_text(encoding="utf-8")

        self.assertIn("RAG_IME_ENABLE_FRONTEND_ON_RESTART=1", helper)
        self.assertIn("RAG_IME_SKIP_INPUT_SOURCE_READINESS=1", helper)
        self.assertIn('RAG_IME_RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-foreground-rag-proof}"', helper)
        self.assertIn('exec "$ROOT/scripts/restart_rag_ime_runtime.sh"', helper)

    def test_failed_process_job_preserves_exit_stdout_and_stderr(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["launchctl"],
            returncode=7,
            stdout="repair output",
            stderr="repair failed",
        )
        with patch("rag_ime.management_service.subprocess.run", return_value=completed):
            response = self.management.start_runtime_action({"action": "restart_predictor"})
            job = self._terminal_job(str(response["jobId"]))

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["result"]["exitCode"], 7)
        self.assertEqual(job["result"]["stdout"], "repair output")
        self.assertEqual(job["result"]["stderr"], "repair failed")
        self.assertEqual(job["error"], "repair failed")

    def test_terminal_status_is_not_visible_before_final_audit_completes(self) -> None:
        audit_started = threading.Event()
        release_audit = threading.Event()
        original_audit = self.management._audit

        def delayed_audit(*args: object, **kwargs: object) -> int:
            if args and args[0] == "runtime_action_finished":
                audit_started.set()
                self.assertTrue(release_audit.wait(timeout=2))
            return original_audit(*args, **kwargs)

        completed = subprocess.CompletedProcess(args=["launchctl"], returncode=0, stdout="ok", stderr="")
        try:
            with (
                patch.object(self.management, "_audit", side_effect=delayed_audit),
                patch("rag_ime.management_service.subprocess.run", return_value=completed),
            ):
                response = self.management.start_runtime_action({"action": "restart_predictor"})
                self.assertTrue(audit_started.wait(timeout=2))
                pending = self.management.runtime_job(str(response["jobId"]))["job"]
                self.assertEqual(pending["status"], "running")
                release_audit.set()
                job = self._terminal_job(str(response["jobId"]))
        finally:
            release_audit.set()

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["result"]["stdout"], "ok")

    def test_overview_requires_real_component_evidence(self) -> None:
        management = self.management
        management.health_provider = lambda: {"ok": True}
        management.input_source_provider = lambda: {
            "selected": True,
            "inputSourceId": "im.rime.inputmethod.Squirrel.Hans",
            "current": "com.apple.keylayout.ABC",
        }
        management.predictor_provider = lambda: {
            "ok": True,
            "predictor": {"configured": True},
        }
        management.last_prediction_provider = lambda: {"contextSource": "accessibility", "createdAtMs": int(time.time() * 1000)}

        unavailable = management.overview()["components"]

        self.assertFalse(unavailable["inputMethod"]["ok"])
        self.assertFalse(unavailable["predictor"]["ok"])
        self.assertFalse(unavailable["foregroundContext"]["ok"])
        self.assertFalse(unavailable["memoryCompiler"]["ok"])

        now_ms = int(time.time() * 1000)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO memory_compile_state(
                  project, last_compiled_event_id, last_run_ms,
                  pending_event_count, last_bundle_hash
                ) VALUES (?, 0, ?, 0, ?)
                """,
                (self.project, now_ms, "sha256:compiler-proof"),
            )
        expected_id = "im.rime.inputmethod.Squirrel.Hans"
        management.input_source_provider = lambda: {
            "inputSourceId": expected_id,
            "current": expected_id,
        }
        management.predictor_provider = lambda: {
            "ok": True,
            "predictor": {
                "configured": True,
                "capabilityProbe": {"ok": True},
            },
        }
        management.last_prediction_provider = lambda: {
            "requestId": "foreground-proof",
            "foregroundContext": {
                "source": "accessibility",
                "capturedAtMs": now_ms,
                "applied": True,
                "commitTextMatched": True,
            },
        }

        healthy = management.overview()["components"]

        self.assertTrue(healthy["inputMethod"]["ok"])
        self.assertTrue(healthy["predictor"]["ok"])
        self.assertTrue(healthy["foregroundContext"]["ok"])
        self.assertTrue(healthy["memoryCompiler"]["ok"])

        management.last_prediction_provider = lambda: {
            "requestId": "foreground-short",
            "foregroundContext": {
                "source": "text_input_client",
                "capturedAtMs": now_ms,
                "applied": True,
                "commitTextMatched": True,
                "selectedTextChars": 0,
                "surroundingBeforeChars": 4,
                "surroundingAfterChars": 0,
            },
        }
        degraded = management.overview()["components"]["foregroundContext"]

        self.assertTrue(degraded["ok"])
        self.assertEqual(degraded["status"], "degraded")
        self.assertIn("仅采集 4 字", degraded["detail"])


class SettingsValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-setting-validation-")
        self.db_path = Path(self.tmp.name) / "settings.sqlite"
        self.store = ManagementSettingsStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_transport_metadata_is_not_persisted_as_settings(self) -> None:
        result = self.store.update_settings(
            {
                "interaction.postCommit.enabled": False,
                "updatedBy": "native-control-center",
                "confirmText": "not-a-setting",
                "schemaVersion": "transport-only",
            },
            updated_by="native-control-center",
        )

        self.assertEqual(result.changed_keys, ("interaction.postCommit.enabled",))
        self.assertNotIn("updatedBy", result.settings)
        self.assertNotIn("confirmText", result.settings)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            keys = {str(row[0]) for row in conn.execute("SELECT key FROM management_settings")}
        self.assertEqual(keys, {"interaction"})

    def test_legacy_transport_metadata_rows_are_purged_on_initialize(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO management_settings(key, value_json, updated_at_ms, updated_by) VALUES (?, ?, 1, 'legacy')",
                ("updatedBy", '"native-control-center"'),
            )

        reopened = ManagementSettingsStore(self.db_path)
        reopened.initialize()

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            keys = {str(row[0]) for row in conn.execute("SELECT key FROM management_settings")}
        self.assertNotIn("updatedBy", keys)

    def test_unknown_keys_wrong_types_and_invalid_enums_are_rejected(self) -> None:
        invalid_updates = (
            {"updatedByUnexpected": "value"},
            {"interaction.postCommit.enabled": "true"},
            {"interaction.postCommit.minDeltaChars": True},
            {"interaction.postCommit.numberKeys": "steal_every_key"},
        )
        for update in invalid_updates:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.store.update_settings(update)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM management_settings").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM management_audit_log").fetchone()[0], 0)

    def test_integral_json_number_and_supported_sensitive_token_are_accepted(self) -> None:
        result = self.store.update_settings(
            {
                "interaction.postCommit.minDeltaChars": 3.0,
                "managementSecurity.token": "local-secret",
            }
        )

        self.assertEqual(result.settings["interaction"]["postCommit"]["minDeltaChars"], 3)
        self.assertEqual(result.settings["managementSecurity"]["token"], "<redacted>")
        sensitive = self.store.get_settings(include_sensitive=True)
        self.assertEqual(sensitive["managementSecurity"]["token"], "local-secret")


class WebControlRuntimeBoundaryTests(unittest.TestCase):
    def test_web_control_center_uses_hash_bound_diagnostics_actions_not_raw_runtime_commands(self) -> None:
        route_policy = (ROOT / "macos" / "RagImeControlWebHost" / "NativeRoutePolicy.swift").read_text(
            encoding="utf-8"
        )
        diagnostics = (ROOT / "control-center-web" / "src" / "features" / "diagnostics" / "index.tsx").read_text(
            encoding="utf-8"
        )

        self.assertIn('"diagnostics.runtime": route("GET", "/api/runtime/status"', route_policy)
        self.assertIn('"diagnostics.action.preview"', route_policy)
        self.assertIn('"diagnostics.action.start"', route_policy)
        self.assertIn('"diagnostics.action.job"', route_policy)
        self.assertNotIn('"runtime.action"', route_policy)
        self.assertNotIn("externalCommand", diagnostics)
        self.assertIn("DiagnosticsRuntimeWorkflow", diagnostics)


if __name__ == "__main__":
    unittest.main()
