from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_maintenance_settings import MemoryMaintenanceSettings


class ActivityTimelineControlApiTests(unittest.TestCase):
    def test_service_uses_server_owned_actor_and_explicit_confirmation(self) -> None:
        store = Mock()
        store.approve.return_value = {"timelineId": "timeline:1"}
        store.reject.return_value = {"timelineId": "timeline:2"}
        service = object.__new__(DebugImeService)
        service.config = SimpleNamespace(project="project-a")
        service.activity_timelines = store

        approved = service.activity_timeline_approve(
            {
                "timelineId": "timeline:1",
                "expectedSourceEventHash": "hash-1",
                "confirmText": "approve",
                "approvedBy": "untrusted-client",
            }
        )
        self.assertEqual(approved["decision"], "accepted")
        store.approve.assert_called_once_with(
            "timeline:1",
            expected_source_event_hash="hash-1",
            approved_by="control-center-user",
            confirm_text="approve",
        )

        with self.assertRaisesRegex(ValueError, "confirmText"):
            service.activity_timeline_reject(
                {
                    "timelineId": "timeline:2",
                    "reason": "not useful",
                    "confirmText": "yes",
                }
            )
        rejected = service.activity_timeline_reject(
            {
                "timelineId": "timeline:2",
                "reason": "not useful",
                "confirmText": "reject",
            }
        )
        self.assertEqual(rejected["decision"], "rejected")
        store.reject.assert_called_once_with(
            "timeline:2",
            reason="not useful",
            rejected_by="control-center-user",
        )

        store.calendar.return_value = {"month": "2026-07", "days": []}
        calendar = service.activity_timeline_calendar({"month": "2026-07"})
        self.assertEqual(calendar["month"], "2026-07")
        store.calendar.assert_called_once_with("2026-07")

    def test_build_is_a_gateway_owned_background_organization_job(self) -> None:
        jobs = Mock()
        jobs.trigger.return_value = {
            "ok": True,
            "jobId": "memory-maintenance:timeline",
            "state": "queued",
        }
        service = object.__new__(DebugImeService)
        service.config = SimpleNamespace(
            project="project-a",
            server_name="agent gateway",
        )
        service._agent_runtime_execution_owner = True
        service.memory_maintenance_jobs = jobs

        result = service.activity_timeline_build({"date": "2026-07-17"})

        self.assertEqual(result["state"], "queued")
        jobs.trigger.assert_called_once_with(
            {
                "project": "project-a",
                "manual": True,
                "maxSources": 1,
                "timelineOnly": True,
                "timelineDate": "2026-07-17",
                "timelineThroughDate": "",
            }
        )

        jobs.reset_mock()
        jobs.trigger.return_value = {
            "ok": True,
            "jobId": "memory-maintenance:catch-up",
            "state": "queued",
        }
        service.activity_timeline_build(
            {"date": "2026-08-12", "throughToday": True}
        )
        jobs.trigger.assert_called_once_with(
            {
                "project": "project-a",
                "manual": True,
                "maxSources": 1,
                "timelineOnly": True,
                "timelineDate": "",
                "timelineThroughDate": "2026-08-12",
            }
        )

        service.config = SimpleNamespace(
            project="project-a",
            server_name="sidecar server",
        )
        with self.assertRaisesRegex(ValueError, "Agent Gateway"):
            service.activity_timeline_build({"date": "2026-07-17"})

        service.config = SimpleNamespace(
            project="project-a",
            server_name="agent gateway",
        )
        jobs.trigger.return_value = {
            "ok": True,
            "jobId": "memory-maintenance:existing",
            "state": "running",
            "reused": True,
        }
        with self.assertRaisesRegex(RuntimeError, "Another Memory organization job"):
            service.activity_timeline_build({"date": "2026-07-17"})

    def test_build_preserves_selected_range_in_gateway_job(self) -> None:
        service = object.__new__(DebugImeService)
        service.config = SimpleNamespace(project="project-a", server_name="agent gateway")
        service._agent_runtime_execution_owner = True
        service.memory_maintenance_jobs = Mock()
        service.memory_maintenance_jobs.trigger.return_value = {
            "ok": True, "jobId": "memory-maintenance:month", "state": "queued",
        }

        service.activity_timeline_build({
            "date": "2026-08-12", "throughToday": True, "rangeStartDate": "2026-08-01",
        })

        service.memory_maintenance_jobs.trigger.assert_called_once_with({
            "project": "project-a", "manual": True, "maxSources": 1,
            "timelineOnly": True, "timelineDate": "",
            "timelineThroughDate": "2026-08-12", "timelineStartDate": "2026-08-01",
        })

    def test_build_rejects_invalid_range_before_admitting_a_job(self) -> None:
        service = object.__new__(DebugImeService)
        service.config = SimpleNamespace(project="project-a", server_name="agent gateway")
        service._agent_runtime_execution_owner = True
        service.memory_maintenance_jobs = Mock()
        service.memory_maintenance_jobs.trigger.return_value = {"ok": True, "state": "queued"}

        for body in (
            {"date": "2026-08-12", "throughToday": True, "rangeStartDate": "2026-08-13"},
            {"date": "2026-08-12", "throughToday": True, "rangeStartDate": "2026-02-30"},
            {"date": "2026-08-32", "throughToday": True, "rangeStartDate": "2026-08-01"},
            {"date": "2026-08-12", "rangeStartDate": "2026-08-01"},
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                service.activity_timeline_build(body)
        service.memory_maintenance_jobs.trigger.assert_not_called()

    def test_gateway_worker_passes_selected_range_to_activity_runner(self) -> None:
        service = object.__new__(DebugImeService)
        service.config = SimpleNamespace(project="project-a")
        service.core = object.__new__(LocalSqliteCoreClient)
        service.core.db_path = Path("unused-memory-range-fixture.sqlite")
        service.agent = SimpleNamespace(runtime=object())
        progress = Mock()
        with (
            patch("rag_ime.debug_server.MemoryMaintenanceSettings.load", return_value=MemoryMaintenanceSettings()),
            patch("rag_ime.debug_server.build_governed_memory_model_executor"),
            patch("rag_ime.debug_server.ManagedPiMemoryOrganizer"),
            patch("rag_ime.debug_server.PersonalContextMaintenanceRunner") as runner_class,
        ):
            runner_class.return_value.build_activity_timelines_through.return_value = {"ok": True}
            service._execute_gateway_memory_maintenance({
                "project": "project-a", "manual": True, "timelineOnly": True,
                "timelineThroughDate": "2026-08-12", "timelineStartDate": "2026-08-01",
                "_progressCallback": progress,
            })
            runner_class.return_value.build_activity_timelines_through.assert_called_once_with(
                "2026-08-12", start_date="2026-08-01", progress=progress,
            )

    def test_http_routes_expose_review_build_approve_and_reject(self) -> None:
        service = _TimelineHandlerService()

        class Handler(DebugRequestHandler):
            pass

        Handler.service = service
        Handler.static_dir = Path(".")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(
                f"{base}/api/memory/activity-timeline?date=2026-07-17",
                timeout=5,
            ) as response:
                review = json.load(response)
            self.assertEqual(review["operation"], "review")

            with urlopen(
                f"{base}/api/memory/activity-timeline/calendar?month=2026-07",
                timeout=5,
            ) as response:
                calendar = json.load(response)
            self.assertEqual(calendar["operation"], "calendar")

            for action, payload in (
                ("build", {"date": "2026-07-17"}),
                (
                    "approve",
                    {
                        "timelineId": "timeline:1",
                        "expectedSourceEventHash": "hash-1",
                        "confirmText": "approve",
                    },
                ),
                (
                    "reject",
                    {
                        "timelineId": "timeline:2",
                        "reason": "not useful",
                        "confirmText": "reject",
                    },
                ),
            ):
                request = Request(
                    f"{base}/api/memory/activity-timeline/{action}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    result = json.load(response)
                self.assertEqual(result["operation"], action)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class _TimelineHandlerService:
    def management_security_settings(self) -> dict[str, object]:
        return {
            "postRequiresJson": True,
            "sameOriginOnly": True,
            "requireToken": False,
        }

    def activity_timeline_review(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {"ok": True, "operation": "review", "payload": payload}

    def activity_timeline_build(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {"ok": True, "operation": "build", "payload": payload}

    def activity_timeline_calendar(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {"ok": True, "operation": "calendar", "payload": payload}

    def activity_timeline_approve(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {"ok": True, "operation": "approve", "payload": payload}

    def activity_timeline_reject(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return {"ok": True, "operation": "reject", "payload": payload}


if __name__ == "__main__":
    unittest.main()
