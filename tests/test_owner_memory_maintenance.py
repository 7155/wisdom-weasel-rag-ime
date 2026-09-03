from __future__ import annotations

import threading
import tempfile
import time
import unittest
import json
import sqlite3
from contextlib import closing
from collections.abc import Mapping
from pathlib import Path
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
            trace_context = values.pop("_memoryTraceContext")
            self.assertTrue(str(trace_context["maintenanceJobId"]).startswith("memory-maintenance:"))
            self.assertEqual(
                trace_context["traceId"],
                f"trace:memory:{trace_context['maintenanceJobId']}",
            )
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

    def test_latest_status_exposes_the_real_background_job_without_a_job_id(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def execute(_payload: Mapping[str, object]) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return {"ok": True, "blob": "x" * 100_000}

        jobs = GatewayMemoryMaintenanceJobs(execute)
        created = jobs.trigger({"project": "project-a", "manual": False})
        self.assertTrue(started.wait(timeout=2))

        latest = jobs.latest_status(project="project-a")

        self.assertEqual(latest["jobId"], created["jobId"])
        self.assertEqual(latest["state"], "running")
        self.assertNotIn("request", latest)
        release.set()
        terminal = self._wait_for_terminal(jobs, str(created["jobId"]))
        self.assertEqual(len(terminal["result"]["blob"]), 100_000)
        latest_terminal = jobs.latest_status(project="project-a")
        self.assertEqual(latest_terminal["result"], {})
        self.assertEqual(latest_terminal["sourceCursor"], {})
        self.assertEqual(latest_terminal["sourceInputRefs"], [])

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

    def test_job_status_survives_gateway_restart_with_trace_and_source_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "paw.sqlite"
            events: list[dict[str, object]] = []

            def execute(_payload: Mapping[str, object]) -> dict[str, object]:
                return {
                    "ok": False,
                    "error": "memory model request failed",
                    "results": [{
                        "runId": "memory_book_owner_1",
                        "sourceCursor": {"fromSourceId": "source-1", "toSourceId": "source-2"},
                    }],
                }

            first = GatewayMemoryMaintenanceJobs(
                execute,
                db_path=db_path,
                event_publisher=events.append,
            )
            started = first.trigger({"project": "project-a", "manual": True})
            terminal = self._wait_for_terminal(first, str(started["jobId"]))

            self.assertEqual(terminal["state"], "failed")
            self.assertEqual(terminal["traceId"], f"trace:memory:{started['jobId']}")
            self.assertEqual(terminal["runId"], started["jobId"])
            self.assertEqual(
                terminal["sourceCursor"],
                {"fromSourceId": "source-1", "toSourceId": "source-2"},
            )
            self.assertEqual([event["phase"] for event in events], ["started", "failed"])

            restarted = GatewayMemoryMaintenanceJobs(lambda _payload: {"ok": True}, db_path=db_path)
            recovered = restarted.status(str(started["jobId"]))
            self.assertEqual(recovered["state"], "failed")
            self.assertEqual(recovered["error"], "memory model request failed")
            self.assertEqual(recovered["result"], terminal["result"])
            self.assertEqual(recovered["traceId"], terminal["traceId"])
            self.assertEqual(recovered["sourceCursor"], terminal["sourceCursor"])

    def test_restart_expiry_publishes_terminal_trace_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "paw.sqlite"
            job_id = "memory-maintenance:running-before-restart"
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE memory_maintenance_jobs (
                            job_id TEXT PRIMARY KEY,
                            state TEXT NOT NULL,
                            request_json TEXT NOT NULL,
                            result_json TEXT NOT NULL,
                            progress_json TEXT NOT NULL,
                            error TEXT NOT NULL DEFAULT '',
                            created_at_ms INTEGER NOT NULL,
                            updated_at_ms INTEGER NOT NULL,
                            completed_at_ms INTEGER NOT NULL DEFAULT 0
                        )
                        """,
                    )
                    conn.execute(
                        """
                        INSERT INTO memory_maintenance_jobs(
                            job_id, state, request_json, result_json, progress_json,
                            error, created_at_ms, updated_at_ms, completed_at_ms
                        ) VALUES (?, 'running', '{}', '{}', ?, '', 1, 2, 0)
                        """,
                        (job_id, json.dumps({"phase": "memory_maintenance"})),
                    )

            events: list[dict[str, object]] = []
            restarted = GatewayMemoryMaintenanceJobs(
                lambda _payload: {"ok": True},
                db_path=db_path,
                event_publisher=events.append,
            )
            status = restarted.status(job_id)

            self.assertEqual(status["state"], "expired")
            self.assertEqual(status["errorCode"], "memory_maintenance_job_expired")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["phase"], "expired")
            self.assertEqual(events[0]["status"], "expired")
            self.assertEqual(events[0]["traceId"], f"trace:memory:{job_id}")
            self.assertEqual(events[0]["runId"], job_id)

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
