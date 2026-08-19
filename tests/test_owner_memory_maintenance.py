from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Mapping

from rag_ime.owner_memory_maintenance import GatewayMemoryMaintenanceJobs, build_parser


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
