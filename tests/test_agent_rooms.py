from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_rooms import AgentRoomEventHub, AgentRoomStore
from rag_ime.agent_service import AgentService
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.pi_runtime import PiRuntimeConfig


class AgentRoomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-rooms-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.store = AgentRoomStore(self.db_path, room_dir=self.root / "rooms")
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_room_owns_independent_participant_sessions_and_jsonl_timeline(self) -> None:
        room = self.store.create(
            title="  方案   讨论  ",
            routing_policy="manual_mentions",
            participants=[
                self._participant("zhiyou-v1", "智鼬"),
                self._participant("hermes-v1", "Hermes"),
                self._participant("vcp-v1", "VCP"),
            ],
            created_at_ms=10,
        )

        self.assertEqual(room["title"], "方案 讨论")
        self.assertEqual(room["routingPolicy"], "manual_mentions")
        self.assertEqual(len(room["participants"]), 3)
        self.assertEqual(len({item["sessionId"] for item in room["participants"]}), 3)
        target = self.store.route_target(str(room["id"]), "@Hermes 先检查当前状态")
        self.assertEqual(target["roleId"], "hermes-v1")
        with self.assertRaisesRegex(ValueError, "must mention"):
            self.store.route_target(str(room["id"]), "先检查当前状态")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.store.route_target(str(room["id"]), "@智鼬 和 @VCP 一起回答")

        event = self.store.append_event(
            room_id=str(room["id"]),
            event_type="user_message",
            payload={"text": "@Hermes 先检查当前状态"},
            turn_id="room-turn:1",
            participant_id=str(target["id"]),
            created_at_ms=20,
        )
        self.assertEqual(event["sequence"], 1)
        self.assertEqual(self.store.get(str(room["id"]))["lastEventSequence"], 1)

        room_files = list((self.root / "rooms").glob("*.jsonl"))
        self.assertEqual(len(room_files), 1)
        stored = json.loads(room_files[0].read_text(encoding="utf-8").strip())
        self.assertEqual(stored["eventId"], event["eventId"])
        self.assertEqual(stat.S_IMODE(room_files[0].stat().st_mode), 0o600)

    def test_moderator_routes_unaddressed_message_and_sse_replays_once(self) -> None:
        room = self.store.create(
            title="主持讨论",
            routing_policy="moderator",
            participants=[
                self._participant("zhiyou-v1", "智鼬"),
                self._participant("vcp-v1", "VCP"),
            ],
            moderator_ordinal=1,
            created_at_ms=100,
        )
        target = self.store.route_target(str(room["id"]), "请先整理线索")
        self.assertEqual(target["displayName"], "VCP")
        self.assertEqual(room["moderatorParticipantId"], target["id"])

        hub = AgentRoomEventHub(self.store)
        first = hub.publish(
            room_id=str(room["id"]),
            event_type="route_decision",
            payload={"reason": "moderator_default"},
            participant_id=str(target["id"]),
            source_session_id=str(target["sessionId"]),
            turn_id="room-turn:2",
            created_at_ms=110,
        )
        stream = hub.subscribe(str(room["id"]), heartbeat_seconds=0.01)
        self.assertEqual(next(stream), b": connected\n\n")
        replay = next(stream)
        self.assertIn(b"event: route_decision", replay)
        self.assertIn(str(first["eventId"]).encode("utf-8"), replay)
        stream.close()

        resumed = hub.subscribe(str(room["id"]), after_event_id=str(first["eventId"]), heartbeat_seconds=0.01)
        self.assertEqual(next(resumed), b": connected\n\n")
        self.assertEqual(next(resumed), b": heartbeat\n\n")
        resumed.close()

        gap = hub.subscribe(str(room["id"]), after_event_id=f"{room['id']}:999", heartbeat_seconds=0.01)
        self.assertEqual(next(gap), b": connected\n\n")
        snapshot_required = next(gap)
        self.assertIn(b"event: snapshot_required", snapshot_required)
        self.assertIn(b"room_event_replay_gap", snapshot_required)
        gap.close()

    def test_room_limits_and_participant_session_ownership_fail_closed(self) -> None:
        participants = [
            self._participant("zhiyou-v1", "智鼬"),
            self._participant("hermes-v1", "Hermes"),
        ]
        self.store.create(
            title="第一个房间",
            routing_policy="manual_mentions",
            participants=participants,
        )
        with self.assertRaisesRegex(Exception, "UNIQUE constraint failed"):
            self.store.create(
                title="重复会话",
                routing_policy="manual_mentions",
                participants=participants,
            )
        with self.assertRaisesRegex(ValueError, "between 2 and 4"):
            self.store.create(
                title="人数过少",
                routing_policy="manual_mentions",
                participants=[self._participant("vcp-v1", "VCP")],
            )

    def _participant(self, role_id: str, display_name: str) -> dict[str, str]:
        session = self.sessions.create(
            title=f"{display_name} room session",
            role_id=role_id,
            role_version="1",
        )
        return {
            "sessionId": str(session["id"]),
            "roleId": role_id,
            "roleVersion": "1",
            "displayName": display_name,
        }


class AgentRoomServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-agent-room-service-")
        self.root = Path(self.tmp.name)
        self.service = AgentService(
            db_path=self.root / "rag-ime.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=self.root / "agent-config",
                session_dir=self.root / "sessions",
                logs_dir=self.root / "logs",
            ),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def test_service_creates_fresh_sessions_routes_one_speaker_and_mirrors_events(self) -> None:
        created = self.service.create_room(
            {
                "title": "产品讨论",
                "routingPolicy": "manual_mentions",
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                    {"roleId": "vcp-v1", "roleVersion": "1"},
                ],
            }
        )
        room = created["room"]
        self.assertEqual(room["lastEventSequence"], 1)
        self.assertEqual(len(room["participants"]), 3)
        hermes = next(item for item in room["participants"] if item["roleId"] == "hermes-v1")

        with patch.object(self.service, "prompt", return_value={"turnId": "turn:hermes"}) as prompt:
            accepted = self.service.post_room_message(
                str(room["id"]),
                {"message": "@Hermes 请先诊断状态"},
            )
        prompt.assert_called_once_with(str(hermes["sessionId"]), {"message": "@Hermes 请先诊断状态"})
        self.assertEqual(accepted["participant"]["id"], hermes["id"])

        self.service.events.publish(
            str(hermes["sessionId"]),
            "text_delta",
            {"delta": "正在检查"},
            turn_id="turn:hermes",
            created_at_ms=200,
        )
        events = self.service.rooms.list_events(str(room["id"]))
        self.assertEqual(
            [item["eventType"] for item in events],
            ["participant_status", "user_message", "route_decision", "participant_delta"],
        )
        self.assertEqual(events[-1]["participantId"], hermes["id"])
        self.assertEqual(events[-1]["sourceSessionId"], hermes["sessionId"])

        with self.assertRaisesRegex(ValueError, "cannot be deleted directly"):
            self.service.delete_session(str(hermes["sessionId"]))
        self.assertEqual(len(self.service.list_rooms()["items"]), 1)

    def test_room_rejects_duplicate_roles_and_archives_without_deleting_sessions(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be unique"):
            self.service.create_room(
                {
                    "title": "重复角色",
                    "participants": [
                        {"roleId": "vcp-v1", "roleVersion": "1"},
                        {"roleId": "vcp-v1", "roleVersion": "1"},
                    ],
                }
            )
        self.assertEqual(self.service.list_sessions()["items"], [])

        created = self.service.create_room(
            {
                "title": "主持房间",
                "routingPolicy": "moderator",
                "moderatorRoleId": "vcp-v1",
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "vcp-v1", "roleVersion": "1"},
                ],
            }
        )
        room_id = str(created["room"]["id"])
        updated = self.service.update_room(room_id, {"archived": True})
        self.assertEqual(updated["room"]["status"], "archived")
        self.assertEqual(self.service.list_rooms()["items"], [])
        self.assertEqual(len(self.service.list_rooms({"includeArchived": True})["items"]), 1)
        self.assertEqual(len(self.service.list_sessions()["items"]), 2)
        archived_member = updated["room"]["participants"][0]
        with self.assertRaisesRegex(ValueError, "cannot be deleted directly"):
            self.service.delete_session(str(archived_member["sessionId"]))

    def test_room_projection_keeps_public_output_but_drops_private_tool_payloads(self) -> None:
        room = self.service.create_room(
            {
                "title": "安全投影",
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        hermes = next(item for item in room["participants"] if item["roleId"] == "hermes-v1")
        session_id = str(hermes["sessionId"])

        self.service.events.publish(
            session_id,
            "tool_finished",
            {
                "toolCallId": "tool:secret",
                "toolName": "ime_memory",
                "args": {"apiKey": "never-copy-this"},
                "result": {
                    "details": {
                        "result": {
                            "summary": "查询到一份可公开摘要",
                            "items": [
                                {"kind": "book", "title": "输入法项目"},
                                {"kind": "tag", "title": "Pi"},
                            ],
                        }
                    }
                },
                "isError": False,
            },
            turn_id="turn:safe",
        )
        projected = self.service.rooms.list_events(str(room["id"]))[-1]
        serialized = json.dumps(projected, ensure_ascii=False)
        self.assertEqual(projected["eventType"], "participant_activity")
        self.assertIn("查询到一份可公开摘要", serialized)
        self.assertIn("输入法项目", serialized)
        self.assertNotIn("never-copy-this", serialized)
        self.assertNotIn('"args"', serialized)
        self.assertNotIn('"result"', serialized)

        self.service.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "message:public",
                    "sessionId": session_id,
                    "turnId": "turn:safe",
                    "role": "assistant",
                    "status": "completed",
                    "blocks": [
                        {
                            "id": "text:1",
                            "type": "text",
                            "status": "completed",
                            "presentationKind": "markdown",
                            "data": {"text": "这是可以进入群聊的回答"},
                        },
                        {
                            "id": "tool:1",
                            "type": "tool_call",
                            "status": "completed",
                            "presentationKind": "tool_call",
                            "data": {"arguments": {"token": "private-token"}},
                        },
                    ],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 10,
                    "completedAtMs": 11,
                }
            },
            turn_id="turn:safe",
        )
        public_message = self.service.rooms.list_events(str(room["id"]))[-1]
        serialized = json.dumps(public_message, ensure_ascii=False)
        self.assertEqual(public_message["eventType"], "participant_message")
        self.assertIn("这是可以进入群聊的回答", serialized)
        self.assertNotIn("private-token", serialized)
        self.assertNotIn("tool_call", serialized)

        self.service.events.publish(
            session_id,
            "message_completed",
            {
                "message": {
                    "schemaVersion": "rag-ime.agent-message.v1",
                    "id": "message:tool-only",
                    "sessionId": session_id,
                    "turnId": "turn:safe",
                    "role": "tool",
                    "status": "completed",
                    "blocks": [
                        {
                            "id": "tool-result:1",
                            "type": "tool_result",
                            "status": "completed",
                            "presentationKind": "tool_result",
                            "data": {"secret": "tool-result-secret"},
                        }
                    ],
                    "attachments": [],
                    "citations": [],
                    "createdAtMs": 12,
                    "completedAtMs": 13,
                }
            },
            turn_id="turn:safe",
        )
        hidden_tool_message = self.service.rooms.list_events(str(room["id"]))[-1]
        serialized = json.dumps(hidden_tool_message, ensure_ascii=False)
        self.assertEqual(hidden_tool_message["eventType"], "participant_activity")
        self.assertIn("内部工具步骤", serialized)
        self.assertNotIn("tool-result-secret", serialized)


if __name__ == "__main__":
    unittest.main()
