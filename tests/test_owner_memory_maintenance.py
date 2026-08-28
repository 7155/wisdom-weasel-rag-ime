from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Mapping
from unittest.mock import patch

from rag_ime.owner_memory_maintenance import (
    GatewayMemoryMaintenanceJobs,
    build_parser,
    run_gateway_memory_maintenance,
)


class GatewayMemoryMaintenanceJobsTests(unittest.TestCase):
    def test_cli_defaults_to_continuity_batch_and_clamps_only_at_hard_limit(self) -> None:
        self.assertEqual(build_parser().parse_args([]).max_sources, 1_000)
        self.assertEqual(
            build_parser().parse_args(["--max-sources", "1500"]).max_sources,
            1_500,
        )

    def test_overlapping_triggers_reuse_the_one_gateway_job(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[dict[str, object]] = []

        def execute(payload: Mapping[str, object]) -> dict[str, object]:
            values = dict(payload)
            progress = values.pop("_progressCallback")
            self.assertTrue(callable(progress))
            progress({"completedDayCount": 1, "totalDayCount": 2})
            calls.append(values)
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True, "ranScopeCount": 1}

        jobs = GatewayMemoryMaintenanceJobs(execute)
        first = jobs.trigger({"project": "project-a"})
        self.assertTrue(started.wait(timeout=2))
        second = jobs.trigger({"project": "project-b"})

        self.assertEqual(second["jobId"], first["jobId"])
        self.assertTrue(second["reused"])
        self.assertEqual(second["progress"]["completedDayCount"], 1)
        self.assertEqual(calls, [{"project": "project-a"}])
        release.set()
        terminal = self._wait_for_terminal(jobs, str(first["jobId"]))
        self.assertEqual(terminal["state"], "completed")
        self.assertTrue(terminal["result"]["ok"])

    def test_timeline_job_reports_its_scope_as_soon_as_it_starts(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def execute(_payload: Mapping[str, object]) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True}

        jobs = GatewayMemoryMaintenanceJobs(execute)
        single = jobs.trigger(
            {
                "timelineOnly": True,
                "timelineDate": "2026-08-11",
                "timelineThroughDate": "",
            }
        )
        self.assertTrue(started.wait(timeout=2))

        running = jobs.status(str(single["jobId"]))
        self.assertEqual(running["state"], "running")
        self.assertEqual(
            running["progress"],
            {
                "phase": "activity_timeline_single",
                "currentDate": "2026-08-11",
                "totalDayCount": 1,
                "completedDayCount": 0,
            },
        )

        release.set()
        self._wait_for_terminal(jobs, str(single["jobId"]))

    def test_background_timeline_status_is_available_without_a_job_id(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def execute(_payload: Mapping[str, object]) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True}

        jobs = GatewayMemoryMaintenanceJobs(execute)
        # The installed LaunchAgent leaves project blank so the Gateway can
        # resolve its configured default project at execution time.
        jobs.trigger({"project": "", "manual": False})
        self.assertTrue(started.wait(timeout=2))

        running = jobs.activity_timeline_status(project="project-a")

        self.assertEqual(running["mode"], "automatic_catch_up")
        self.assertEqual(running["state"], "running")
        self.assertEqual(running["progress"]["phase"], "memory_maintenance")
        self.assertNotIn("request", running)
        release.set()
        self._wait_for_terminal(jobs, str(running["jobId"]))

    def test_failed_manual_catch_up_remains_visible_after_refresh(self) -> None:
        jobs = GatewayMemoryMaintenanceJobs(
            lambda _payload: {
                "ok": False,
                "pendingDayCount": 4,
                "completedDayCount": 1,
                "remainingDayCount": 3,
                "failedDate": "2026-08-08",
                "error": "model request failed",
            }
        )
        started = jobs.trigger(
            {
                "project": "project-a",
                "timelineOnly": True,
                "timelineDate": "",
                "timelineThroughDate": "2026-08-12",
            }
        )
        self._wait_for_terminal(jobs, str(started["jobId"]))

        failed = jobs.activity_timeline_status(project="project-a")

        self.assertEqual(failed["mode"], "manual_catch_up")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["result"]["failedDate"], "2026-08-08")
        self.assertEqual(failed["result"]["remainingDayCount"], 3)
        self.assertEqual(failed["error"], "model request failed")

    def test_semantic_verification_warning_keeps_job_completed_and_traceable(self) -> None:
        jobs = GatewayMemoryMaintenanceJobs(
            lambda _payload: {
                "ok": True,
                "status": "draft",
                "autoPublished": False,
                "semanticOrganization": {
                    "status": "warning",
                    "reviewRequired": True,
                    "error": "Activity organization did not pass independent semantic verification",
                    "verification": {"verdict": "reject"},
                    "receipt": {
                        "verifierRequest": {
                            "traceId": "trace:activity-repair-verifier",
                        },
                    },
                },
            }
        )
        started = jobs.trigger(
            {
                "project": "project-a",
                "timelineOnly": True,
                "timelineDate": "2026-08-12",
                "timelineThroughDate": "",
            }
        )
        self._wait_for_terminal(jobs, str(started["jobId"]))

        status = jobs.activity_timeline_status(project="project-a")

        self.assertEqual(status["state"], "completed")
        self.assertTrue(status["ok"])
        self.assertEqual(status["error"], "")
        self.assertEqual(status["result"]["semanticOrganization"]["status"], "warning")
        self.assertEqual(
            status["result"]["semanticOrganization"]["error"],
            "Activity organization did not pass independent semantic verification",
        )
        self.assertEqual(
            status["result"]["semanticOrganization"]["receipt"]["verifierRequest"]["traceId"],
            "trace:activity-repair-verifier",
        )

    def test_failed_execution_is_observable_and_close_stops_admission(self) -> None:
        def fail(_payload: Mapping[str, object]) -> dict[str, object]:
            raise RuntimeError("provider down")

        jobs = GatewayMemoryMaintenanceJobs(fail)
        started = jobs.trigger({})
        terminal = self._wait_for_terminal(jobs, str(started["jobId"]))

        self.assertEqual(terminal["state"], "failed")
        self.assertFalse(terminal["ok"])
        self.assertEqual(terminal["error"], "provider down")
        jobs.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            jobs.trigger({})

    def test_missing_job_returns_truthful_expired_recovery_payload(self) -> None:
        jobs = GatewayMemoryMaintenanceJobs(lambda _payload: {"ok": True})

        status = jobs.status("memory-maintenance:after-gateway-restart")

        self.assertFalse(status["ok"])
        self.assertEqual(status["state"], "expired")
        self.assertEqual(
            status["errorCode"],
            "memory_maintenance_job_expired",
        )
        self.assertIn("Gateway restarted", status["error"])
        self.assertEqual(status["result"], {})
        self.assertEqual(status["progress"], {})
        self.assertEqual(
            status["recovery"],
            {
                "recoverable": False,
                "retryable": True,
                "action": "trigger_new_job",
                "reason": "process_local_job_registry_lost",
            },
        )

    def test_gateway_client_stops_polling_when_the_job_expires_after_restart(self) -> None:
        expired = {
            "schemaVersion": "rag-ime.gateway-memory-maintenance-job.v1",
            "ok": False,
            "jobId": "memory-maintenance:after-gateway-restart",
            "state": "expired",
            "errorCode": "memory_maintenance_job_expired",
            "error": "Gateway restarted before this process-local Memory maintenance job could be read; the old job cannot be recovered.",
            "recovery": {
                "recoverable": False,
                "retryable": True,
                "action": "trigger_new_job",
                "reason": "process_local_job_registry_lost",
            },
        }
        with (
            patch(
                "rag_ime.owner_memory_maintenance._request_json",
                side_effect=[
                    {"jobId": expired["jobId"], "state": "queued"},
                    expired,
                ],
            ) as request_json,
            patch("rag_ime.owner_memory_maintenance.time.sleep") as sleep,
        ):
            result = run_gateway_memory_maintenance(
                "http://127.0.0.1:18768",
                {"manual": True},
                timeout_seconds=1,
                poll_interval=0.01,
            )

        self.assertEqual(result, expired)
        self.assertEqual(request_json.call_count, 2)
        sleep.assert_called_once()

    @staticmethod
    def _wait_for_terminal(
        jobs: GatewayMemoryMaintenanceJobs,
        job_id: str,
    ) -> dict[str, object]:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = jobs.status(job_id)
            if current["state"] in {"completed", "failed"}:
                return current
            time.sleep(0.01)
        raise AssertionError("gateway job did not become terminal")


if __name__ == "__main__":
    unittest.main()
