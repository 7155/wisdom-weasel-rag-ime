from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from rag_ime.agent_rooms import AgentRoomStore
from rag_ime.agent_service import AgentService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.pi_runtime import PiRuntimeConfig


class AgentListPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-list-pagination-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "agent.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.rooms = AgentRoomStore(self.db_path, room_dir=self.root / "rooms")
        self.rooms.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_session_keyset_cursor_is_stable_for_equal_update_times(self) -> None:
        created = [
            self.sessions.create(title=f"session-{index}", created_at_ms=100)
            for index in range(3)
        ]
        expected = [
            str(item["id"])
            for item in sorted(
                created,
                key=lambda item: (int(item["updatedAtMs"]), str(item["id"])),
                reverse=True,
            )
        ]

        first = self.sessions.list_page(limit=2)
        self.assertEqual([item["id"] for item in first["items"]], expected[:2])
        self.assertTrue(first["hasMore"])
        self.assertEqual(first["nextBeforeUpdatedAtMs"], 100)
        self.assertEqual(first["nextBeforeId"], expected[1])
        self.assertEqual(
            first["nextCursor"],
            {"beforeUpdatedAtMs": 100, "beforeId": expected[1]},
        )
        # A keyset cursor is only active when both components are present;
        # incomplete cursors consistently fall back to the first page.
        self.assertEqual(
            [
                item["id"]
                for item in self.sessions.list_page(
                    limit=2, before_updated_at_ms=100
                )["items"]
            ],
            expected[:2],
        )
        self.assertEqual(
            [
                item["id"]
                for item in self.sessions.list_page(
                    limit=2, before_id=expected[1]
                )["items"]
            ],
            expected[:2],
        )

        second = self.sessions.list_page(
            limit=2,
            before_updated_at_ms=first["nextBeforeUpdatedAtMs"],
            before_id=first["nextBeforeId"],
        )
        self.assertEqual([item["id"] for item in second["items"]], expected[2:])
        self.assertFalse(second["hasMore"])
        self.assertIsNone(second["nextBeforeUpdatedAtMs"])
        self.assertIsNone(second["nextBeforeId"])

        # Existing internal callers still receive the old array-shaped result.
        self.assertEqual(
            [item["id"] for item in self.sessions.list(limit=2)],
            expected[:2],
        )

    def test_room_keyset_cursor_is_stable_for_equal_update_times(self) -> None:
        created: list[dict[str, object]] = []
        for index in range(3):
            participants = []
            for suffix, role_id, name in (
                ("a", "companion-present-v1", "A"),
                ("b", "companion-future-v1", "B"),
            ):
                session = self.sessions.create(
                    title=f"room-{index}-{suffix}", created_at_ms=100
                )
                participants.append(
                    {
                        "sessionId": session["id"],
                        "roleId": role_id,
                        "roleVersion": "1",
                        "displayName": name,
                    }
                )
            created.append(
                self.rooms.create(
                    title=f"room-{index}",
                    routing_policy="parallel",
                    participants=participants,
                    created_at_ms=100,
                )
            )
        expected = [
            str(item["id"])
            for item in sorted(
                created,
                key=lambda item: (int(item["updatedAtMs"]), str(item["id"])),
                reverse=True,
            )
        ]

        first = self.rooms.list_page(limit=2)
        self.assertEqual([item["id"] for item in first["items"]], expected[:2])
        self.assertTrue(first["hasMore"])
        second = self.rooms.list_page(
            limit=2,
            before_updated_at_ms=first["nextBeforeUpdatedAtMs"],
            before_id=first["nextBeforeId"],
        )
        self.assertEqual([item["id"] for item in second["items"]], expected[2:])
        self.assertFalse(second["hasMore"])
        self.assertEqual(
            [item["id"] for item in self.rooms.list(limit=2)],
            expected[:2],
        )

    def test_application_list_responses_expose_cursor_metadata(self) -> None:
        service = AgentService(
            db_path=self.db_path,
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
        )
        try:
            created = [
                service.sessions.create(title=f"app-{index}", created_at_ms=100)
                for index in range(3)
            ]
            first = service.list_sessions({"limit": 2})
            self.assertTrue(first["hasMore"])
            second = service.list_sessions(
                {
                    "limit": 2,
                    "beforeUpdatedAtMs": first["nextBeforeUpdatedAtMs"],
                    "beforeId": first["nextBeforeId"],
                }
            )
            self.assertEqual(
                [item["id"] for item in first["items"] + second["items"]],
                [
                    str(item["id"])
                    for item in sorted(
                        created,
                        key=lambda item: (int(item["updatedAtMs"]), str(item["id"])),
                        reverse=True,
                    )
                ],
            )
            self.assertFalse(second["hasMore"])
        finally:
            service.close()

    def test_debug_server_forwards_both_cursor_query_fields(self) -> None:
        class FakeAgent:
            def __init__(self) -> None:
                self.session_payload: dict[str, object] | None = None
                self.room_payload: dict[str, object] | None = None

            def list_sessions(self, payload: dict[str, object]) -> dict[str, object]:
                self.session_payload = payload
                return {"schemaVersion": "rag-ime.agent-session-list.v1", "ok": True, "items": []}

            def list_rooms(self, payload: dict[str, object]) -> dict[str, object]:
                self.room_payload = payload
                return {"schemaVersion": "rag-ime.agent-room-list.v1", "ok": True, "items": []}

        class FakeService:
            def __init__(self) -> None:
                self.agent = FakeAgent()

        fake = FakeService()

        class Handler(DebugRequestHandler):
            pass

        Handler.service = fake  # type: ignore[assignment]
        Handler.static_dir = self.root
        original_authorize = Handler._authorize_gateway_request
        Handler._authorize_gateway_request = lambda self, method, parsed: True  # type: ignore[method-assign]
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            query = urlencode(
                {
                    "limit": 2,
                    "beforeUpdatedAtMs": 100,
                    "beforeId": "session:cursor",
                }
            )
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/agent/sessions?{query}",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, HTTPStatus.OK)
                json.loads(response.read().decode("utf-8"))
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/agent/rooms?{query}",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, HTTPStatus.OK)
                json.loads(response.read().decode("utf-8"))
        finally:
            Handler._authorize_gateway_request = original_authorize  # type: ignore[method-assign]
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertIsNotNone(fake.agent.session_payload)
        self.assertEqual(fake.agent.session_payload["beforeUpdatedAtMs"], "100")
        self.assertEqual(fake.agent.session_payload["beforeId"], "session:cursor")
        self.assertIsNotNone(fake.agent.room_payload)
        self.assertEqual(fake.agent.room_payload["beforeUpdatedAtMs"], "100")
        self.assertEqual(fake.agent.room_payload["beforeId"], "session:cursor")


if __name__ == "__main__":
    unittest.main()
