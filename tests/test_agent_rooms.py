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

    def test_route_target_uses_exact_longest_mention_and_rejects_real_ambiguity(self) -> None:
        room = self.store.create(
            title="时间线讨论",
            routing_policy="manual_mentions",
            participants=[
                self._participant("zhiyou-v1", "智鼬"),
                self._participant("zhiyou-sol-v1", "智鼬·未来"),
            ],
        )
        room_id = str(room["id"])

        current = self.store.route_target(room_id, "@智鼬 检查当前状态")
        future = self.store.route_target(room_id, "@智鼬·未来 做长期规划")

        self.assertEqual(current["roleId"], "zhiyou-v1")
        self.assertEqual(future["roleId"], "zhiyou-sol-v1")

        ambiguous = self.store.create(
            title="重名讨论",
            routing_policy="manual_mentions",
            participants=[
                self._participant("custom-a", "同名角色"),
                self._participant("custom-b", "同名角色"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.store.route_target(str(ambiguous["id"]), "@同名角色 请回答")

    def test_snapshot_returns_atomic_room_metadata_and_retained_event_window(self) -> None:
        room = self.store.create(
            title="快照房间",
            routing_policy="moderator",
            participants=[
                self._participant("zhiyou-v1", "智鼬"),
                self._participant("hermes-v1", "Hermes"),
            ],
            created_at_ms=1,
        )
        room_id = str(room["id"])
        for sequence in range(1, 103):
            self.store.append_event(
                room_id=room_id,
                event_type="participant_status",
                payload={"status": f"step-{sequence}"},
                created_at_ms=sequence + 1,
                retain_per_room=100,
            )

        snapshot = self.store.snapshot(room_id)

        self.assertEqual(snapshot["schemaVersion"], "rag-ime.agent-room-snapshot.v1")
        self.assertEqual(snapshot["room"]["lastEventSequence"], 102)
        self.assertEqual(len(snapshot["room"]["participants"]), 2)
        self.assertEqual(snapshot["firstSequence"], 3)
        self.assertEqual(snapshot["lastSequence"], 102)
        self.assertEqual(snapshot["resumeToken"], f"{room_id}:102")
        self.assertTrue(snapshot["truncated"])
        self.assertEqual(
            [event["sequence"] for event in snapshot["events"]],
            list(range(3, 103)),
        )

    def test_empty_room_snapshot_has_zero_cursor(self) -> None:
        room = self.store.create(
            title="空房间",
            routing_policy="manual_mentions",
            participants=[
                self._participant("zhiyou-v1", "智鼬"),
                self._participant("hermes-v1", "Hermes"),
            ],
        )

        snapshot = self.store.snapshot(str(room["id"]))

        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["firstSequence"], 0)
        self.assertEqual(snapshot["lastSequence"], 0)
        self.assertEqual(snapshot["resumeToken"], "")
        self.assertFalse(snapshot["truncated"])

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

    def test_room_requires_a_workspace_before_participant_sessions_are_created(self) -> None:
        with self.assertRaisesRegex(ValueError, "authorized workspace"):
            self.service.create_room(
                {
                    "title": "没有项目的协作",
                    "workspaceRoots": [],
                    "participants": [
                        {"roleId": "zhiyou-v1", "roleVersion": "1"},
                        {"roleId": "vcp-v1", "roleVersion": "1"},
                    ],
                }
            )
        self.assertEqual(self.service.list_sessions()["items"], [])

    def test_service_creates_fresh_sessions_routes_one_speaker_and_mirrors_events(self) -> None:
        self.service.personas.set_runtime_defaults(
            "vcp-v1",
            "1",
            model_profile="openai/gpt-5.4",
            thinking_level="max",
        )
        created = self.service.create_room(
            {
                "title": "产品讨论",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                    {"roleId": "vcp-v1", "roleVersion": "1"},
                ],
            }
        )
        room = created["room"]
        self.assertEqual(room["workspaceRoots"], [str(self.root.resolve())])
        self.assertEqual(room["lastEventSequence"], 1)
        self.assertEqual(len(room["participants"]), 3)
        hermes = next(item for item in room["participants"] if item["roleId"] == "hermes-v1")
        current = next(item for item in room["participants"] if item["roleId"] == "zhiyou-v1")
        future = next(item for item in room["participants"] if item["roleId"] == "vcp-v1")
        self.assertEqual(hermes["collaborationRole"], "researcher")
        self.assertEqual(current["collaborationRole"], "executor")
        self.assertEqual(future["collaborationRole"], "executor")
        hermes_session = self.service.sessions.get(str(hermes["sessionId"]))
        current_session = self.service.sessions.get(str(current["sessionId"]))
        future_session = self.service.sessions.get(str(future["sessionId"]))
        self.assertEqual(hermes_session["mode"], "coordinator")
        self.assertEqual(hermes_session["toolProfileVersion"], "subagent-readonly-v1")
        self.assertEqual(current_session["toolProfileVersion"], "control-center-v1")
        self.assertEqual(future_session["modelProfile"], "openai/gpt-5.4")
        self.assertEqual(future_session["thinkingLevel"], "max")
        self.assertEqual(future_session["workspaceRoots"], [str(self.root.resolve())])

        with patch.object(self.service, "prompt", return_value={"turnId": "turn:hermes"}) as prompt:
            accepted = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "@智鼬·初识 请先诊断状态",
                    "clientMessageId": "room-client-1",
                },
            )
        prompt.assert_called_once()
        self.assertEqual(prompt.call_args.args[0], str(hermes["sessionId"]))
        room_prompt = prompt.call_args.args[1]["message"]
        self.assertIn("你是只读调研者", room_prompt)
        self.assertIn(str(self.root.resolve()), room_prompt)
        self.assertIn("@智鼬·初识 请先诊断状态", room_prompt)
        self.assertEqual(accepted["participant"]["id"], hermes["id"])
        self.assertEqual(accepted["clientMessageId"], "room-client-1")

        self.service.events.publish(
            str(hermes["sessionId"]),
            "text_delta",
            {"delta": "正在检查"},
            turn_id="turn:hermes",
            created_at_ms=200,
        )
        self.service.events.publish(
            str(hermes["sessionId"]),
            "turn_completed",
            {"status": "completed"},
            turn_id="turn:hermes",
            created_at_ms=210,
        )
        events = self.service.rooms.list_events(str(room["id"]))
        self.assertEqual(
            [item["eventType"] for item in events],
            [
                "participant_status",
                "user_message",
                "route_decision",
                "participant_delta",
                "turn_completed",
            ],
        )
        self.assertEqual(events[-2]["participantId"], hermes["id"])
        self.assertEqual(events[-2]["sourceSessionId"], hermes["sessionId"])
        self.assertEqual(events[1]["payload"]["clientMessageId"], "room-client-1")
        self.assertNotEqual(accepted["roomTurnId"], accepted["sessionTurnId"])
        self.assertEqual(
            {item["turnId"] for item in events[1:]},
            {accepted["roomTurnId"]},
        )

        snapshot = self.service.room_snapshot(str(room["id"]))
        self.assertEqual(snapshot["lastSequence"], events[-1]["sequence"])
        self.assertEqual(snapshot["resumeToken"], events[-1]["resumeToken"])
        self.assertEqual(snapshot["room"]["id"], room["id"])

        policy = self.service.update_session(
            str(hermes["sessionId"]),
            {
                "mode": "assistant",
                "toolProfileVersion": "subagent-readonly-v1",
                "allowedTools": ["ime_overview", "ime_memory"],
            },
        )["session"]
        self.assertEqual(policy["toolProfileVersion"], "subagent-readonly-v1")
        self.assertEqual(policy["allowedTools"], ["ime_overview", "ime_memory"])

        with self.assertRaisesRegex(ValueError, "cannot be deleted directly"):
            self.service.delete_session(str(hermes["sessionId"]))
        self.assertEqual(len(self.service.list_rooms()["items"]), 1)

    def test_room_rejects_duplicate_roles_and_archives_without_deleting_sessions(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be unique"):
            self.service.create_room(
                {
                    "title": "重复角色",
                    "workspaceRoots": [str(self.root)],
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
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "zhiyou-v1", "roleVersion": "1"},
                    {"roleId": "hermes-v1", "roleVersion": "1"},
                    {"roleId": "vcp-v1", "roleVersion": "1"},
                ],
            }
        )
        future = next(
            item for item in created["room"]["participants"] if item["roleId"] == "vcp-v1"
        )
        self.assertEqual(future["collaborationRole"], "coordinator")
        room_id = str(created["room"]["id"])
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:future"}) as prompt:
            accepted = self.service.post_room_message(
                room_id,
                {"message": "请协调大家检查当前项目"},
            )
        self.assertEqual(accepted["participant"]["id"], future["id"])
        moderator_prompt = prompt.call_args.args[1]["message"]
        self.assertIn("你是本轮调控者", moderator_prompt)
        self.assertIn("ime_agents.room_ask", moderator_prompt)
        self.assertIn("role=researcher", moderator_prompt)
        self.assertIn("role=executor", moderator_prompt)

        updated = self.service.update_room(room_id, {"archived": True})
        self.assertEqual(updated["room"]["status"], "archived")
        self.assertEqual(self.service.list_rooms()["items"], [])
        self.assertEqual(len(self.service.list_rooms({"includeArchived": True})["items"]), 1)
        self.assertEqual(len(self.service.list_sessions()["items"]), 3)
        archived_member = updated["room"]["participants"][0]
        with self.assertRaisesRegex(ValueError, "cannot be deleted directly"):
            self.service.delete_session(str(archived_member["sessionId"]))

    def test_room_projection_keeps_public_output_but_drops_private_tool_payloads(self) -> None:
        room = self.service.create_room(
            {
                "title": "安全投影",
                "workspaceRoots": [str(self.root)],
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
