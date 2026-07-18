from __future__ import annotations

import unittest

from rag_ime.agent_routes import (
    agent_approval_route,
    agent_artifact_route,
    agent_context_item_route,
    agent_context_trace_route,
    agent_media_route,
    agent_room_route,
    agent_room_work_route,
    agent_session_route,
    agent_wake_schedule_route,
)


class AgentRouteTests(unittest.TestCase):
    def test_session_routes_are_strict_and_url_decoded(self) -> None:
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent%3A123/messages"),
            ("agent:123", "messages"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/prompt"),
            ("agent:123", "prompt"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/forks"),
            ("agent:123", "forks"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123"),
            ("agent:123", ""),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/models"),
            ("agent:123", "models"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/commands"),
            ("agent:123", "commands"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/model"),
            ("agent:123", "model"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/thinking"),
            ("agent:123", "thinking"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/intercom"),
            ("agent:123", "intercom"),
        )
        self.assertEqual(
            agent_session_route("/api/agent/sessions/agent:123/review"),
            ("agent:123", "review"),
        )

    def test_unknown_or_nested_routes_do_not_fall_through(self) -> None:
        for path in (
            "/api/agent/sessions",
            "/api/agent/sessions/",
            "/api/agent/sessions/agent:123/unknown",
            "/api/agent/sessions/agent:123/messages/extra",
            "/api/not-agent/sessions/agent:123/messages",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_session_route(path), ("", ""))

    def test_context_routes_are_strict_and_url_decoded(self) -> None:
        self.assertEqual(
            agent_context_item_route("/api/agent/sessions/agent%3A123/context-items"),
            ("agent:123", "", "list"),
        )
        self.assertEqual(
            agent_context_item_route(
                "/api/agent/sessions/agent%3A123/context-items/context-item%3A456/ack"
            ),
            ("agent:123", "context-item:456", "ack"),
        )
        self.assertEqual(
            agent_context_trace_route("/api/agent/sessions/agent%3A123/context-traces"),
            ("agent:123", ""),
        )
        self.assertEqual(
            agent_context_trace_route(
                "/api/agent/sessions/agent%3A123/context-traces/context-trace%3A456"
            ),
            ("agent:123", "context-trace:456"),
        )
        for path in (
            "/api/agent/sessions/agent:123/context-items/item:1",
            "/api/agent/sessions/agent:123/context-items/item:1/delete",
            "/api/agent/sessions/agent:123/context-traces/trace:1/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_context_item_route(path), ("", "", ""))
                self.assertEqual(agent_context_trace_route(path), ("", ""))

    def test_approval_routes_are_strict_and_url_decoded(self) -> None:
        self.assertEqual(
            agent_approval_route("/api/agent/approvals/approval%3A123/decision"),
            ("approval:123", "decision"),
        )
        self.assertEqual(
            agent_approval_route("/api/agent/approvals/approval%3A123/external-result"),
            ("approval:123", "external-result"),
        )
        self.assertEqual(
            agent_approval_route("/api/agent/approvals/approval:123"),
            ("approval:123", ""),
        )
        for path in (
            "/api/agent/approvals",
            "/api/agent/approvals/approval:123/unknown",
            "/api/agent/approvals/approval:123/decision/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_approval_route(path), ("", ""))

    def test_media_routes_only_expose_receipt_or_content(self) -> None:
        self.assertEqual(
            agent_media_route("/api/agent/media/media_abc123456789/receipt"),
            ("media_abc123456789", "receipt"),
        )
        self.assertEqual(
            agent_media_route("/api/agent/media/media_abc123456789/content"),
            ("media_abc123456789", "content"),
        )
        self.assertEqual(
            agent_media_route("/api/agent/media/media_abc123456789"),
            ("media_abc123456789", "receipt"),
        )
        for path in (
            "/api/agent/media",
            "/api/agent/media/media_abc123456789/open",
            "/api/agent/media/media_abc123456789/content/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_media_route(path), ("", ""))

    def test_room_routes_are_strict_and_participant_aware(self) -> None:
        self.assertEqual(
            agent_room_route("/api/agent/rooms/room%3A123/events"),
            ("room:123", "events"),
        )
        self.assertEqual(
            agent_room_route("/api/agent/rooms/room:123/messages"),
            ("room:123", "messages"),
        )
        self.assertEqual(
            agent_room_route("/api/agent/rooms/room%3A123/snapshot"),
            ("room:123", "snapshot"),
        )
        self.assertEqual(agent_room_route("/api/agent/rooms/room:123"), ("room:123", ""))
        for path in (
            "/api/agent/rooms",
            "/api/agent/rooms/room:123/unknown",
            "/api/agent/rooms/room:123/events/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_room_route(path), ("", ""))

    def test_room_work_routes_are_strict_and_url_decoded(self) -> None:
        self.assertEqual(
            agent_room_work_route(
                "/api/agent/rooms/room%3A123/work-items"
            ),
            ("room:123", "", "collection"),
        )
        self.assertEqual(
            agent_room_work_route(
                "/api/agent/rooms/room%3A123/work-items/work%3A456"
            ),
            ("room:123", "work:456", "get"),
        )
        self.assertEqual(
            agent_room_work_route(
                "/api/agent/rooms/room%3A123/work-items/work%3A456/reassign"
            ),
            ("room:123", "work:456", "reassign"),
        )
        for path in (
            "/api/agent/rooms/room:123/work-items//reassign",
            "/api/agent/rooms/room:123/work-items/work:456/unknown",
            "/api/agent/rooms/room:123/work-items/work:456/extra/path",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_room_work_route(path), ("", "", ""))

    def test_artifact_route_accepts_one_opaque_identifier_only(self) -> None:
        self.assertEqual(
            agent_artifact_route("/api/agent/artifacts/artifact%3Aabc123"),
            "artifact:abc123",
        )
        for path in (
            "/api/agent/artifacts",
            "/api/agent/artifacts/",
            "/api/agent/artifacts/artifact:abc/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_artifact_route(path), "")

    def test_wake_schedule_routes_are_strict_and_url_decoded(self) -> None:
        self.assertEqual(
            agent_wake_schedule_route("/api/agent/wake-schedules/wake%3A123/runs"),
            ("wake:123", "runs"),
        )
        self.assertEqual(
            agent_wake_schedule_route("/api/agent/wake-schedules/wake%3A123/action"),
            ("wake:123", "action"),
        )
        self.assertEqual(
            agent_wake_schedule_route("/api/agent/wake-schedules/wake%3A123"),
            ("wake:123", ""),
        )
        for path in (
            "/api/agent/wake-schedules",
            "/api/agent/wake-schedules/wake:123/unknown",
            "/api/agent/wake-schedules/wake:123/runs/extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(agent_wake_schedule_route(path), ("", ""))


if __name__ == "__main__":
    unittest.main()
