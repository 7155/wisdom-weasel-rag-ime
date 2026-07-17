from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.request import Request, urlopen

from rag_ime.debug_server import DebugImeService, DebugRequestHandler


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
