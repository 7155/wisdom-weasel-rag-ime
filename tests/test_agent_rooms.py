from __future__ import annotations

import json
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_context_runtime import RUNTIME_PROMPT_ENVELOPE_PREFIX
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
                self._participant("companion-present-v1", "智鼬"),
                self._participant("companion-firstlight-v1", "Hermes"),
                self._participant("companion-future-v1", "VCP"),
            ],
            created_at_ms=10,
        )

        self.assertEqual(room["title"], "方案 讨论")
        self.assertEqual(room["routingPolicy"], "manual_mentions")
        self.assertEqual(len(room["participants"]), 3)
        self.assertEqual(len({item["sessionId"] for item in room["participants"]}), 3)
        target = self.store.route_target(str(room["id"]), "@Hermes 先检查当前状态")
        self.assertEqual(target["roleId"], "companion-firstlight-v1")
        fallback = self.store.route_target(str(room["id"]), "先检查当前状态")
        self.assertEqual(fallback["roleId"], "companion-present-v1")
        fan_out = self.store.plan_routes(
            str(room["id"]), "@智鼬 和 @VCP 一起回答"
        )
        self.assertEqual(
            [decision["targetDisplayName"] for decision in fan_out],
            ["智鼬", "VCP"],
        )
        self.assertTrue(
            all(
                decision["selectedParticipantIds"]
                == [room["participants"][0]["id"], room["participants"][2]["id"]]
                for decision in fan_out
            )
        )

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

    def test_room_never_persists_or_projects_retired_builtin_role_ids(
        self,
    ) -> None:
        room = self.store.create(
            title="身份迁移",
            routing_policy="natural",
            participants=[
                self._participant("vcp-v1", "未来"),
                self._participant("zhiyou-v1", "此刻"),
            ],
        )

        self.assertEqual(
            [item["roleId"] for item in room["participants"]],
            ["companion-future-v1", "companion-present-v1"],
        )
        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute(
                """
                SELECT role_id
                FROM agent_room_participants
                WHERE room_id = ?
                ORDER BY ordinal
                """,
                (room["id"],),
            ).fetchall()
        self.assertEqual(
            stored,
            [
                ("companion-future-v1",),
                ("companion-present-v1",),
            ],
        )

    def test_moderator_routes_unaddressed_message_and_sse_replays_once(self) -> None:
        room = self.store.create(
            title="主持讨论",
            routing_policy="moderator",
            participants=[
                self._participant("companion-present-v1", "智鼬"),
                self._participant("companion-future-v1", "VCP"),
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

    def test_public_projection_receipt_deduplicates_fanout_and_rejects_rebinding(self) -> None:
        room = self.store.create(
            title="公开投影去重",
            routing_policy="natural",
            participants=[
                self._participant("companion-present-v1", "智鼬·此刻"),
                self._participant("companion-firstlight-v1", "智鼬·初识"),
            ],
            created_at_ms=100,
        )
        room_id = str(room["id"])
        hub = AgentRoomEventHub(self.store)
        observed: list[dict[str, object]] = []
        hub.add_observer(lambda event: observed.append(dict(event)))
        values = {
            "room_id": room_id,
            "event_type": "user_message",
            "payload": {"messageId": "post:user:1", "text": "只显示一次"},
            "turn_id": "root:1",
            "created_at_ms": 110,
        }

        first = hub.publish_projection(projection_key="room-post:post:user:1", **values)
        replay = hub.publish_projection(projection_key="room-post:post:user:1", **values)

        self.assertIsNotNone(first)
        self.assertEqual(replay, first)
        self.assertEqual(len(observed), 1)
        self.assertEqual(
            [event["eventType"] for event in self.store.list_events(room_id)],
            ["user_message"],
        )
        with self.assertRaisesRegex(ValueError, "projection key was rebound"):
            hub.publish_projection(
                projection_key="room-post:post:user:1",
                **{
                    **values,
                    "payload": {
                        "messageId": "post:user:1",
                        "text": "偷偷改写",
                    },
                },
            )

    def test_route_target_uses_exact_longest_mention_and_rejects_real_ambiguity(self) -> None:
        room = self.store.create(
            title="时间线讨论",
            routing_policy="manual_mentions",
            participants=[
                self._participant("companion-present-v1", "智鼬"),
                self._participant("zhiyou-sol-v1", "智鼬·未来"),
            ],
        )
        room_id = str(room["id"])

        current = self.store.route_target(room_id, "@智鼬 检查当前状态")
        future = self.store.route_target(room_id, "@智鼬·未来 做长期规划")

        self.assertEqual(current["roleId"], "companion-present-v1")
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
                self._participant("companion-present-v1", "智鼬"),
                self._participant("companion-firstlight-v1", "Hermes"),
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

    def test_participant_public_cursor_prevents_reinjecting_old_room_messages(self) -> None:
        room = self.store.create(
            title="游标房间",
            routing_policy="moderator",
            participants=[
                self._participant("companion-present-v1", "智鼬"),
                self._participant("companion-firstlight-v1", "Hermes"),
            ],
        )
        participant_id = str(room["participants"][1]["id"])
        room_id = str(room["id"])
        topic_id = str(room["activeTopicId"])
        for sequence in range(3):
            self.store.append_event(
                room_id=room_id,
                event_type="user_message",
                payload={"text": f"消息 {sequence}"},
                turn_id=f"turn:{sequence}",
                topic_id=topic_id,
            )

        unread = self.store.unread_public_messages(
            room_id,
            participant_id,
            topic_id=topic_id,
            limit=2,
        )
        self.assertEqual(unread["omittedCount"], 1)
        self.assertEqual(
            [item["payload"]["text"] for item in unread["items"]],
            ["消息 1", "消息 2"],
        )
        self.store.advance_delivery_cursor(
            room_id,
            participant_id,
            topic_id=topic_id,
            through_sequence=int(unread["throughSequence"]),
        )
        self.store.append_event(
            room_id=room_id,
            event_type="user_message",
            payload={"text": "新消息"},
            turn_id="turn:new",
            topic_id=topic_id,
        )

        next_unread = self.store.unread_public_messages(
            room_id,
            participant_id,
            topic_id=topic_id,
        )
        self.assertEqual(
            [item["payload"]["text"] for item in next_unread["items"]],
            ["新消息"],
        )

    def test_joining_participant_starts_at_current_room_watermark(self) -> None:
        room = self.store.create(
            title="长期协作",
            routing_policy="manual_mentions",
            participants=[
                self._participant("companion-present-v1", "智鼬·此刻"),
                self._participant("companion-firstlight-v1", "智鼬·初识"),
            ],
        )
        room_id = str(room["id"])
        topic_id = str(room["activeTopicId"])
        for sequence in range(30):
            self.store.append_event(
                room_id=room_id,
                event_type="user_message",
                payload={"text": f"加入前的消息 {sequence}"},
                turn_id=f"turn:old:{sequence}",
                topic_id=topic_id,
            )
        session = self.sessions.create(
            title="智鼬·未来 room session",
            role_id="companion-future-v1",
            role_version="1",
        )

        participant = self.store.add_participant(
            room_id,
            session_id=str(session["id"]),
            role_id="companion-future-v1",
            role_version="1",
            display_name="智鼬·未来",
        )

        unread = self.store.unread_public_messages(
            room_id,
            str(participant["id"]),
            topic_id=topic_id,
        )
        self.assertEqual(unread["items"], [])
        self.assertEqual(unread["omittedCount"], 0)
        self.store.append_event(
            room_id=room_id,
            event_type="user_message",
            payload={"text": "加入后的第一条消息"},
            turn_id="turn:new",
            topic_id=topic_id,
        )
        next_unread = self.store.unread_public_messages(
            room_id,
            str(participant["id"]),
            topic_id=topic_id,
        )
        self.assertEqual(
            [item["payload"]["text"] for item in next_unread["items"]],
            ["加入后的第一条消息"],
        )

    def test_empty_room_snapshot_has_zero_cursor(self) -> None:
        room = self.store.create(
            title="空房间",
            routing_policy="manual_mentions",
            participants=[
                self._participant("companion-present-v1", "智鼬"),
                self._participant("companion-firstlight-v1", "Hermes"),
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
            self._participant("companion-present-v1", "智鼬"),
            self._participant("companion-firstlight-v1", "Hermes"),
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
                participants=[self._participant("companion-future-v1", "VCP")],
            )

    def test_sequential_and_natural_routing_are_structured_and_deterministic(self) -> None:
        room = self.store.create(
            title="轮流讨论",
            room_kind="roleplay",
            routing_policy="sequential",
            participants=[
                self._participant("companion-present-v1", "此刻"),
                self._participant("companion-firstlight-v1", "初识"),
                self._participant("companion-future-v1", "未来"),
            ],
        )
        room_id = str(room["id"])
        first = self.store.plan_route(room_id, "先说说看")
        self.assertEqual(first["reason"], "sequential")
        self.assertEqual(first["selectedParticipantIds"], [room["participants"][0]["id"]])
        self.store.commit_route(room_id, first)
        second = self.store.plan_route(room_id, "继续")
        self.assertEqual(second["selectedParticipantIds"], [room["participants"][1]["id"]])

        updated = self.store.update_config(
            room_id,
            {"routingPolicy": "natural", "routingConfig": {"naturalJitter": 0}},
        )
        profiles = {
            str(updated["participants"][0]["id"]): {"traits": ["执行", "实现"]},
            str(updated["participants"][1]["id"]): {"traits": ["调研", "证据"]},
            str(updated["participants"][2]["id"]): {"traits": ["规划", "协调"]},
        }
        decision = self.store.plan_route(room_id, "请调研证据", profiles=profiles)
        self.assertEqual(decision["reason"], "descriptor_match")
        self.assertEqual(decision["targetDisplayName"], "初识")
        self.assertEqual(decision["schemaVersion"], "rag-ime.room-route-decision.v1")
        self.assertTrue(decision["candidates"][0]["signals"])
        with self.assertRaisesRegex(ValueError, "cannot be changed"):
            self.store.update_config(room_id, {"roomKind": "collaboration"})

    def test_topics_and_artifacts_are_incremental_and_workspace_scoped(self) -> None:
        room = self.store.create(
            title="资料讨论",
            routing_policy="moderator",
            workspace_roots=[str(self.root)],
            participants=[
                self._participant("companion-present-v1", "此刻"),
                self._participant("companion-future-v1", "未来"),
            ],
        )
        room_id = str(room["id"])
        original_topic = str(room["activeTopicId"])
        topic = self.store.create_topic(room_id, title="发布风险", summary="核对上线边界")
        activated = self.store.update_topic(room_id, str(topic["id"]), {"activate": True})
        self.assertEqual(activated["title"], "发布风险")
        self.assertEqual(self.store.get(room_id)["activeTopicId"], topic["id"])
        archived = self.store.update_topic(room_id, original_topic, {"archived": True})
        self.assertEqual(archived["status"], "archived")

        artifact_path = self.root / "report.md"
        artifact_path.write_text("# report\n", encoding="utf-8")
        artifact = self.store.add_artifact(
            room_id,
            path=str(artifact_path),
            topic_id=str(topic["id"]),
            display_name="风险报告",
            media_type="text/markdown",
        )
        self.assertEqual(artifact["path"], str(artifact_path.resolve()))
        self.assertEqual(
            self.store.list_artifacts(room_id, topic_id=str(topic["id"]))[0]["displayName"],
            "风险报告",
        )
        outside = Path(tempfile.gettempdir()) / "rag-ime-outside-room-artifact.txt"
        outside.write_text("outside", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        with self.assertRaisesRegex(ValueError, "authorized workspace"):
            self.store.add_artifact(room_id, path=str(outside))

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
                        {"roleId": "companion-present-v1", "roleVersion": "1"},
                        {"roleId": "companion-future-v1", "roleVersion": "1"},
                    ],
                }
            )
        self.assertEqual(self.service.list_sessions()["items"], [])

    def test_existing_room_can_add_future_without_replaying_old_history(self) -> None:
        room = self.service.create_room(
            {
                "title": "长期项目 Room",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        for sequence in range(40):
            self.service.rooms.append_event(
                room_id=str(room["id"]),
                event_type="user_message",
                payload={"text": f"不可重放的旧消息 {sequence} " + "旧" * 500},
                turn_id=f"turn:old:{sequence}",
                topic_id=str(room["activeTopicId"]),
            )

        added = self.service.add_room_participant(
            str(room["id"]),
            {"roleId": "companion-future-v1", "roleVersion": "1"},
        )
        future = added["participant"]
        self.assertEqual(future["displayName"], "智鼬·未来")
        self.assertEqual(len([p for p in added["room"]["participants"] if p["status"] == "active"]), 3)

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:future:first"},
        ) as prompt:
            self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "@智鼬·未来 请从现在开始接手规划",
                    "participantIds": [str(future["id"])],
                },
            )

        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(
            prompt_payload["message"],
            "@智鼬·未来 请从现在开始接手规划",
        )
        rendered = prompt_payload["_transientContext"]
        self.assertNotIn("不可重放的旧消息", rendered)
        self.assertLessEqual(len(rendered), 24_000)

    def test_existing_member_room_context_is_bounded_by_count_and_characters(self) -> None:
        room = self.service.create_room(
            {
                "title": "上下文预算 Room",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        target = room["participants"][0]
        for sequence in range(30):
            self.service.rooms.append_event(
                room_id=str(room["id"]),
                event_type="user_message",
                payload={"text": f"历史编号-{sequence:02d}-" + "长" * 700},
                turn_id=f"turn:history:{sequence}",
                topic_id=str(room["activeTopicId"]),
            )

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:bounded"},
        ) as prompt:
            self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "@智鼬·此刻 继续当前任务",
                    "participantIds": [str(target["id"])],
                },
            )

        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(prompt_payload["message"], "@智鼬·此刻 继续当前任务")
        rendered = prompt_payload["_transientContext"]
        self.assertLessEqual(len(rendered), 24_000)
        self.assertIn("历史编号-29", rendered)
        self.assertNotIn("历史编号-00", rendered)
        self.assertIn("较早未读消息已越过本次上下文窗口", rendered)

    def test_room_rejects_oversized_message_instead_of_silently_truncating_it(self) -> None:
        room = self.service.create_room(
            {
                "title": "消息边界 Room",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        target = room["participants"][0]

        with self.assertRaisesRegex(ValueError, "must not exceed 8000"):
            self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "@智鼬·此刻 " + "超" * 8_000,
                    "participantIds": [str(target["id"])],
                },
            )

        events = self.service.rooms.list_events(str(room["id"]))
        self.assertFalse(any(value["eventType"] == "user_message" for value in events))

    def test_active_room_repairs_a_missing_participant_session(self) -> None:
        room = self.service.create_room(
            {
                "title": "旧 Room Session 修复",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participant = room["participants"][0]
        old_session_id = str(participant["sessionId"])
        # Simulate a legacy/manual database mutation that bypassed FK checks.
        with sqlite3.connect(self.service.sessions.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("DELETE FROM agent_sessions WHERE id = ?", (old_session_id,))

        snapshot = self.service.room_snapshot(str(room["id"]))
        repaired = next(
            value
            for value in snapshot["room"]["participants"]
            if value["id"] == participant["id"]
        )
        self.assertNotEqual(repaired["sessionId"], old_session_id)
        repaired_session = self.service.sessions.get(str(repaired["sessionId"]))
        self.assertEqual(repaired_session["roleId"], participant["roleId"])
        self.assertEqual(repaired_session["status"], "idle")

    def test_active_room_restores_legacy_archived_participant_sessions(self) -> None:
        room = self.service.create_room(
            {
                "title": "旧 Room 归档修复",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        session_id = str(room["participants"][0]["sessionId"])
        self.service.sessions.archive(session_id, archived=True)

        self.service.room_snapshot(str(room["id"]))

        self.assertEqual(self.service.sessions.get(session_id)["status"], "idle")

    def test_removed_member_is_archived_and_not_restored_by_room_snapshot(self) -> None:
        room = self.service.create_room(
            {
                "title": "成员生命周期",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        future = next(value for value in room["participants"] if value["roleId"] == "companion-future-v1")

        removed = self.service.remove_room_participant(
            str(room["id"]),
            {"participantId": future["id"]},
        )
        self.assertEqual(removed["participant"]["status"], "removed")
        self.assertEqual(self.service.sessions.get(str(future["sessionId"]))["status"], "archived")
        snapshot = self.service.room_snapshot(str(room["id"]))
        self.assertTrue(snapshot["ok"])
        self.assertEqual(self.service.sessions.get(str(future["sessionId"]))["status"], "archived")
        self.assertEqual(
            [value["roleId"] for value in snapshot["room"]["participants"] if value["status"] == "active"],
            ["companion-present-v1", "companion-firstlight-v1"],
        )

    def test_removing_member_clears_inactive_routing_pointers(self) -> None:
        room = self.service.create_room(
            {
                "title": "路由指针生命周期",
                "routingPolicy": "moderator",
                "moderatorRoleId": "companion-future-v1",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        future = next(value for value in room["participants"] if value["roleId"] == "companion-future-v1")
        self.service.update_room(
            str(room["id"]),
            {
                "routingPolicy": "natural",
                "routingConfig": {
                    "naturalJitter": 0.04,
                    "fallbackParticipantId": future["id"],
                },
            },
        )

        removed = self.service.remove_room_participant(
            str(room["id"]),
            {"participantId": future["id"]},
        )

        self.assertEqual(removed["room"]["moderatorParticipantId"], "")
        self.assertEqual(removed["room"]["routingConfig"]["fallbackParticipantId"], "")
        with self.assertRaisesRegex(ValueError, "requires an active moderator"):
            self.service.update_room(
                str(room["id"]),
                {"routingPolicy": "moderator"},
            )

    def test_permanent_room_delete_requires_archive_and_exact_title(self) -> None:
        room = self.service.create_room(
            {
                "title": "可永久删除 Room",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        room_id = str(room["id"])
        session_ids = [str(value["sessionId"]) for value in room["participants"]]
        with self.assertRaisesRegex(ValueError, "archive the Room"):
            self.service.delete_room(room_id, {"confirmTitle": room["title"]})
        self.service.update_room(room_id, {"archived": True})
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.service.delete_room(room_id, {"confirmTitle": "写错了"})

        deleted = self.service.delete_room(room_id, {"confirmTitle": room["title"]})

        self.assertEqual(deleted["deletedSessionIds"], session_ids)
        self.assertEqual(self.service.list_rooms({"includeArchived": True})["items"], [])
        self.assertEqual(self.service.list_sessions({"includeArchived": True, "includeInternal": True})["items"], [])

    def test_permanent_room_delete_tolerates_a_legacy_missing_session(self) -> None:
        room = self.service.create_room(
            {
                "title": "缺失 Session 的旧 Room",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        room_id = str(room["id"])
        missing_session_id = str(room["participants"][0]["sessionId"])
        self.service.update_room(room_id, {"archived": True})
        with sqlite3.connect(self.service.sessions.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "DELETE FROM agent_sessions WHERE id = ?",
                (missing_session_id,),
            )

        deleted = self.service.delete_room(
            room_id,
            {"confirmTitle": room["title"]},
        )

        missing_cleanup = next(
            item
            for item in deleted["sessionCleanup"]
            if item["sessionId"] == missing_session_id
        )
        self.assertTrue(missing_cleanup["alreadyMissing"])
        self.assertEqual(
            self.service.list_rooms({"includeArchived": True})["items"],
            [],
        )

    def test_natural_room_uses_pinned_role_book_as_advisory_profile(self) -> None:
        role = self.service.personas.resolve("companion-firstlight-v1", "1")
        self.service.role_books.ensure_seeded(
            role.role_id,
            role.version,
            role.display_name,
            role.summary,
            role.version,
        )
        draft = self.service.role_books.propose_revision(
            "companion-firstlight-v1",
            "1",
            {
                "capabilities": [
                    {
                        "itemId": "capability:timeseries",
                        "text": "时序数据库性能",
                        "provenance": {
                            "sourceType": "work-receipt",
                            "sourceId": "work:timeseries",
                            "observedAtMs": 100,
                        },
                        "evidenceIds": ["receipt:timeseries"],
                    }
                ]
            },
        )
        active = self.service.role_books.activate_revision(draft["revisionId"])
        room = self.service.create_room(
            {
                "title": "自然路由",
                "routingPolicy": "natural",
                "routingConfig": {"naturalJitter": 0},
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        hermes = next(
            item for item in room["participants"] if item["roleId"] == "companion-firstlight-v1"
        )
        self.assertEqual(
            self.service.sessions.get(str(hermes["sessionId"]))[
                "roleBookRevisionId"
            ],
            active["revisionId"],
        )

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:role-book"},
        ):
            accepted = self.service.post_room_message(
                str(room["id"]),
                {"message": "时序数据库性能"},
            )

        self.assertEqual(accepted["participant"]["id"], hermes["id"])
        self.assertEqual(accepted["routeDecision"]["reason"], "descriptor_match")
        evidence = self.service.memory_evidence.list(
            role_id="companion-firstlight-v1",
            session_id=str(hermes["sessionId"]),
        )
        self.assertEqual(evidence[0]["sourceKind"], "room_event")
        self.assertFalse(evidence[0]["metadata"]["accepted"])

    def test_active_work_item_owner_overrides_role_book_and_explicit_conflicts(self) -> None:
        role = self.service.personas.resolve("companion-firstlight-v1", "1")
        self.service.role_books.ensure_seeded(
            role.role_id,
            role.version,
            role.display_name,
            role.summary,
            role.version,
        )
        draft = self.service.role_books.propose_revision(
            "companion-firstlight-v1",
            "1",
            {
                "capabilities": [
                    {
                        "itemId": "capability:timeseries-authority",
                        "text": "时序数据库性能专项负责人",
                        "provenance": {
                            "sourceType": "work-receipt",
                            "sourceId": "work:timeseries-authority",
                            "observedAtMs": 100,
                        },
                        "evidenceIds": ["receipt:timeseries-authority"],
                    }
                ]
            },
        )
        self.service.role_books.activate_revision(draft["revisionId"])
        room = self.service.create_room(
            {
                "title": "WorkItem 权威路由",
                "routingPolicy": "natural",
                "routingConfig": {"naturalJitter": 0},
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        hermes = next(
            item for item in room["participants"] if item["roleId"] == "companion-firstlight-v1"
        )
        vcp = next(
            item for item in room["participants"] if item["roleId"] == "companion-future-v1"
        )
        work_item = self.service.room_work.create(
            room_id=str(room["id"]),
            objective="完成时序数据库性能诊断",
            expected_output="给出诊断报告",
            current_owner_participant_id=str(vcp["id"]),
            created_by_participant_id=str(vcp["id"]),
            client_message_id="work-item-authority-1",
            topic_id=str(room["activeTopicId"]),
            state="active",
        )

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:work-vcp"},
        ):
            routed = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "请处理时序数据库性能问题",
                    "workItemId": work_item["id"],
                },
            )

        self.assertEqual(routed["participant"]["id"], vcp["id"])
        self.assertEqual(routed["routeDecision"]["reason"], "work_item_owner")
        self.assertEqual(routed["workItem"]["id"], work_item["id"])

        with self.assertRaisesRegex(ValueError, "conflicts with the WorkItem"):
            self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "请处理时序数据库性能问题",
                    "participantIds": [str(hermes["id"])],
                    "workItemId": work_item["id"],
                },
            )

        reassigned = self.service.room_work.reassign(
            str(work_item["id"]),
            actor_participant_id=str(vcp["id"]),
            current_owner_participant_id=str(hermes["id"]),
            reason="VCP 正式移交给 Hermes",
        )
        self.assertEqual(
            reassigned["currentOwnerParticipantId"],
            hermes["id"],
        )
        work_events = self.service.room_work.list_events(str(work_item["id"]))
        self.assertEqual(
            [event["eventType"] for event in work_events],
            ["assigned", "accepted", "assigned"],
        )
        self.assertEqual(
            work_events[-1]["payload"]["previousOwnerParticipantId"],
            vcp["id"],
        )
        self.assertEqual(
            work_events[-1]["payload"]["currentOwnerParticipantId"],
            hermes["id"],
        )

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:work-hermes"},
        ):
            accepted = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "请处理时序数据库性能问题",
                    "participantIds": [str(hermes["id"])],
                    "workItemId": work_item["id"],
                },
            )

        self.assertEqual(accepted["participant"]["id"], hermes["id"])
        self.assertEqual(
            accepted["workItem"]["currentOwnerParticipantId"],
            hermes["id"],
        )

    def test_service_creates_fresh_sessions_routes_one_speaker_and_mirrors_events(self) -> None:
        created = self.service.create_room(
            {
                "title": "产品讨论",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )
        room = created["room"]
        self.assertEqual(room["workspaceRoots"], [str(self.root.resolve())])
        self.assertEqual(room["lastEventSequence"], 1)
        self.assertEqual(len(room["participants"]), 3)
        hermes = next(item for item in room["participants"] if item["roleId"] == "companion-firstlight-v1")
        current = next(item for item in room["participants"] if item["roleId"] == "companion-present-v1")
        future = next(item for item in room["participants"] if item["roleId"] == "companion-future-v1")
        self.assertEqual(hermes["collaborationRole"], "researcher")
        self.assertEqual(current["collaborationRole"], "executor")
        self.assertEqual(future["collaborationRole"], "coordinator")
        hermes_session = self.service.sessions.get(str(hermes["sessionId"]))
        current_session = self.service.sessions.get(str(current["sessionId"]))
        future_session = self.service.sessions.get(str(future["sessionId"]))
        self.assertEqual(hermes_session["mode"], "coordinator")
        self.assertEqual(hermes_session["toolProfileVersion"], "control-center-v1")
        self.assertEqual(current_session["toolProfileVersion"], "control-center-v1")
        self.assertEqual(future_session["modelProfile"], "gpt/gpt-5.6-sol")
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
            replay = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "@智鼬·初识 请先诊断状态",
                    "clientMessageId": "room-client-1",
                },
            )
        prompt.assert_called_once()
        self.assertEqual(prompt.call_args.args[0], str(hermes["sessionId"]))
        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(prompt_payload["message"], "@智鼬·初识 请先诊断状态")
        room_context = prompt_payload["_transientContext"]
        self.assertIn('visibility="provider-only"', room_context)
        self.assertIn("当前岗位：researcher", room_context)
        self.assertNotIn(str(self.root.resolve()), room_context)
        self.assertNotIn("@智鼬·初识 请先诊断状态", room_context)
        self.assertEqual(accepted["participant"]["id"], hermes["id"])
        self.assertEqual(accepted["clientMessageId"], "room-client-1")
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["roomTurnId"], accepted["roomTurnId"])

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

    def test_multi_mentions_share_one_root_but_keep_independent_dispatches(self) -> None:
        room = self.service.create_room(
            {
                "title": "双 Agent 核对",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        current, firstlight, _future = room["participants"]
        turns = {
            str(current["sessionId"]): "turn:multi:current",
            str(firstlight["sessionId"]): "turn:multi:firstlight",
        }

        def accept(session_id: str, _payload: dict[str, object]) -> dict[str, object]:
            return {"turnId": turns[session_id]}

        with patch.object(self.service, "prompt", side_effect=accept) as prompt:
            accepted = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": (
                        f"@{current['displayName']} @{firstlight['displayName']} "
                        "分别核对实现和证据"
                    ),
                    "clientMessageId": "room-multi-1",
                },
            )

        self.assertTrue(accepted["accepted"])
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(
            {item["participantId"] for item in accepted["dispatches"]},
            {current["id"], firstlight["id"]},
        )
        self.assertEqual(
            len({item["dispatchId"] for item in accepted["dispatches"]}),
            2,
        )
        root_id = str(accepted["roomTurnId"])
        initial_events = self.service.rooms.list_events(str(room["id"]))
        self.assertEqual(
            [event["eventType"] for event in initial_events],
            ["participant_status", "user_message", "route_decision", "route_decision"],
        )
        self.assertEqual(
            initial_events[1]["payload"]["targetParticipantIds"],
            [current["id"], firstlight["id"]],
        )
        self.assertEqual(
            {event["turnId"] for event in initial_events[1:]},
            {root_id},
        )
        route_dispatches = {
            event["participantId"]: event["payload"]["dispatchId"]
            for event in initial_events
            if event["eventType"] == "route_decision"
        }
        self.assertEqual(len(set(route_dispatches.values())), 2)

        self.service.events.publish(
            str(current["sessionId"]),
            "turn_completed",
            {"status": "completed"},
            turn_id=turns[str(current["sessionId"])],
            created_at_ms=200,
        )
        self.assertEqual(
            self.service._room_topic_for_turn(root_id),
            room["activeTopicId"],
        )
        self.service.events.publish(
            str(firstlight["sessionId"]),
            "text_delta",
            {"delta": "证据已核对"},
            turn_id=turns[str(firstlight["sessionId"])],
            created_at_ms=205,
        )
        self.service.events.publish(
            str(firstlight["sessionId"]),
            "turn_completed",
            {"status": "completed"},
            turn_id=turns[str(firstlight["sessionId"])],
            created_at_ms=210,
        )

        mirrored = self.service.rooms.list_events(str(room["id"]))[-3:]
        self.assertEqual(
            [event["eventType"] for event in mirrored],
            ["turn_completed", "participant_delta", "turn_completed"],
        )
        for event in mirrored:
            data = event["payload"]["data"]
            self.assertEqual(data["rootId"], root_id)
            self.assertEqual(
                data["dispatchId"],
                route_dispatches[event["participantId"]],
            )
        self.assertEqual(self.service._room_topic_for_turn(root_id), "")

    def test_root_abort_cancels_all_participants_and_fences_late_room_events(self) -> None:
        room = self.service.create_room(
            {
                "title": "整轮停止",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        first, second = room["participants"]
        turns = {
            str(first["sessionId"]): "turn:abort:first",
            str(second["sessionId"]): "turn:abort:second",
        }

        with patch.object(
            self.service,
            "prompt",
            side_effect=lambda session_id, _payload: {"turnId": turns[session_id]},
        ):
            accepted = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": (
                        f"@{first['displayName']} @{second['displayName']} "
                        "并行检查后统一交付"
                    ),
                    "clientMessageId": "room-root-abort-message",
                },
            )

        def typed_abort(session_id: str) -> dict[str, object]:
            return {
                "schemaVersion": "rag-ime.agent-abort.v1",
                "ok": True,
                "sessionId": session_id,
                "runtimeReceipt": {
                    "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
                    "sessionId": session_id,
                    "turnId": turns[session_id],
                    "cancelledDecisionIds": [],
                    "cancelledUIRequestIds": [],
                    "lifecycle": {
                        "schemaVersion": "pi.agent-abort-receipt.v1",
                        "scopeId": session_id,
                        "generation": 1,
                        "reason": "user_abort",
                        "cancelledContinuationIds": [
                            f"continuation:{session_id}"
                        ],
                        "cancelledOperationIds": [
                            f"provider:{session_id}",
                            f"tool:{session_id}",
                        ],
                        "failedOperationIds": [],
                        "operations": [
                            {
                                "operationId": f"provider:{session_id}",
                                "kind": "provider",
                            },
                            {
                                "operationId": f"tool:{session_id}",
                                "kind": "tool",
                            },
                        ],
                        "pendingOperations": [],
                        "drained": True,
                        "idle": True,
                    },
                },
            }

        with patch.object(self.service, "abort", side_effect=typed_abort) as abort:
            receipt = self.service.abort_room_turn(
                str(room["id"]),
                {
                    "roomTurnId": accepted["roomTurnId"],
                    "clientRequestId": "room-root-abort-1",
                },
            )
            replay = self.service.abort_room_turn(
                str(room["id"]),
                {
                    "roomTurnId": accepted["roomTurnId"],
                    "clientRequestId": "room-root-abort-1",
                },
            )

        self.assertEqual(
            {call.args[0] for call in abort.call_args_list},
            {str(first["sessionId"]), str(second["sessionId"])},
        )
        self.assertEqual(receipt["status"], "terminated")
        self.assertEqual(receipt["pendingTargets"], [])
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(
            replay["cancellationReceiptId"],
            receipt["cancellationReceiptId"],
        )

        events_before_late = self.service.rooms.list_events(str(room["id"]))
        terminal = [
            event
            for event in events_before_late
            if event["eventType"] == "turn_completed"
        ]
        self.assertEqual(
            {event["participantId"] for event in terminal},
            {first["id"], second["id"]},
        )
        self.assertTrue(
            all(event["payload"]["status"] == "aborted" for event in terminal)
        )

        self.service.events.publish(
            str(first["sessionId"]),
            "text_delta",
            {"delta": "不应重新出现在 Room"},
            turn_id=turns[str(first["sessionId"])],
            created_at_ms=999,
        )
        self.service.events.publish(
            str(first["sessionId"]),
            "turn_completed",
            {"status": "completed"},
            turn_id=turns[str(first["sessionId"])],
            created_at_ms=1000,
        )
        self.assertEqual(
            self.service.rooms.list_events(str(room["id"])),
            events_before_late,
        )

    def test_root_abort_never_marks_final_while_a_runtime_surface_is_unverified(self) -> None:
        room = self.service.create_room(
            {
                "title": "停止未确认",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participant = room["participants"][0]
        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:abort:pending"},
        ):
            accepted = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": f"@{participant['displayName']} 执行长任务",
                    "clientMessageId": "room-root-abort-pending-message",
                },
            )
        unverified = {
            "schemaVersion": "rag-ime.agent-abort.v1",
            "ok": True,
            "sessionId": str(participant["sessionId"]),
            "runtimeReceipt": {
                "schemaVersion": "rag-ime.pi-session-abort-receipt.v1",
                "sessionId": str(participant["sessionId"]),
                "turnId": "turn:abort:pending",
                "lifecycle": {
                    "schemaVersion": "pi.agent-abort-receipt.v1",
                    "scopeId": str(participant["sessionId"]),
                    "generation": 1,
                    "reason": "user_abort",
                    "cancelledContinuationIds": [],
                    "cancelledOperationIds": [],
                    "failedOperationIds": [],
                    "operations": [
                        {"operationId": "provider:pending", "kind": "provider"},
                    ],
                    "pendingOperations": [
                        {"operationId": "provider:pending", "kind": "provider"},
                    ],
                    "drained": False,
                    "idle": False,
                },
            },
        }

        with patch.object(self.service, "abort", return_value=unverified):
            receipt = self.service.abort_room_turn(
                str(room["id"]),
                {
                    "roomTurnId": accepted["roomTurnId"],
                    "clientRequestId": "room-root-abort-pending-1",
                },
            )

        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["status"], "cancellation_pending")
        self.assertIn("provider", receipt["pendingTargets"])
        self.assertIn("session", receipt["pendingTargets"])
        turn_events = [
            event
            for event in self.service.rooms.list_events(str(room["id"]))
            if event["turnId"] == accepted["roomTurnId"]
        ]
        self.assertFalse(
            any(event["eventType"] == "turn_completed" for event in turn_events)
        )
        self.assertEqual(
            turn_events[-1]["payload"]["status"],
            "cancellation_pending",
        )

    def test_room_input_stays_a_user_message_and_room_delta_is_provider_only(self) -> None:
        created = self.service.create_room(
            {
                "title": "Provider-only Room",
                "routingPolicy": "manual_mentions",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        target = created["participants"][0]
        first_text = "@智鼬·此刻 检查增量上下文"
        with patch.object(
            self.service.runtime,
            "prompt",
            return_value={
                "accepted": True,
                "turnId": "turn:provider-only:1",
                "piEntryId": "entry:provider-only:1",
                "response": {"success": True},
            },
        ) as runtime_prompt:
            accepted = self.service.post_room_message(
                str(created["id"]),
                {
                    "message": first_text,
                    "participantIds": [str(target["id"])],
                },
            )

        runtime_message = runtime_prompt.call_args.args[1]
        envelope = json.loads(
            runtime_message.removeprefix(RUNTIME_PROMPT_ENVELOPE_PREFIX)
        )
        self.assertEqual(envelope["message"], first_text)
        self.assertIn("<room-turn-context", envelope["transientContext"])
        self.assertIn('mode="incremental"', envelope["transientContext"])
        self.assertNotIn(first_text, envelope["transientContext"])
        self.assertNotIn("受管 Room 上下文", runtime_message)

        session_events, _ = self.service.events.replay(str(target["sessionId"]))
        user_messages = [
            event.payload["message"]
            for event in session_events
            if event.event_type == "message_completed"
            and isinstance(event.payload.get("message"), dict)
            and event.payload["message"].get("role") == "user"
        ]
        self.assertEqual(len(user_messages), 1)
        self.assertEqual(
            user_messages[0]["blocks"][0]["data"]["text"],
            first_text,
        )
        self.assertNotIn(
            "room-turn-context",
            json.dumps(user_messages[0], ensure_ascii=False),
        )

        self.service.events.publish(
            str(target["sessionId"]),
            "turn_completed",
            {"status": "completed"},
            turn_id=str(accepted["sessionTurnId"]),
        )

    def test_room_user_priority_is_released_when_turn_preparation_fails(self) -> None:
        created = self.service.create_room(
            {
                "title": "异常恢复",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )
        room = created["room"]
        target = room["participants"][0]
        with patch.object(
            self.service.room_events,
            "publish",
            side_effect=RuntimeError("event store unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "event store unavailable"):
                self.service.post_room_message(
                    str(room["id"]),
                    {
                        "message": f"@{target['displayName']} 请检查状态",
                        "participantIds": [str(target["id"])],
                    },
                )
        self.assertNotIn(
            str(target["sessionId"]),
            self.service._room_user_priority_sessions,
        )

    def test_room_rejects_duplicate_roles_and_archives_without_deleting_sessions(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be unique"):
            self.service.create_room(
                {
                    "title": "重复角色",
                    "workspaceRoots": [str(self.root)],
                    "participants": [
                        {"roleId": "companion-future-v1", "roleVersion": "1"},
                        {"roleId": "companion-future-v1", "roleVersion": "1"},
                    ],
                }
            )
        self.assertEqual(self.service.list_sessions()["items"], [])

        created = self.service.create_room(
            {
                "title": "主持房间",
                "routingPolicy": "moderator",
                "moderatorRoleId": "companion-future-v1",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )
        future = next(
            item for item in created["room"]["participants"] if item["roleId"] == "companion-future-v1"
        )
        self.assertEqual(future["collaborationRole"], "coordinator")
        room_id = str(created["room"]["id"])
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:future"}) as prompt:
            accepted = self.service.post_room_message(
                room_id,
                {"message": "请协调大家检查当前项目"},
            )
        self.assertEqual(accepted["participant"]["id"], future["id"])
        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(prompt_payload["message"], "请协调大家检查当前项目")
        moderator_context = prompt_payload["_transientContext"]
        self.assertIn("当前岗位：coordinator", moderator_context)
        self.assertNotIn("ime_agents.room_ask", moderator_context)
        self.assertNotIn("role=researcher", moderator_context)
        self.assertNotIn("role=executor", moderator_context)

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
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-firstlight-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        hermes = next(item for item in room["participants"] if item["roleId"] == "companion-firstlight-v1")
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

    def test_roleplay_room_uses_invites_scenario_and_topic_scoped_recent_context(self) -> None:
        created = self.service.create_room(
            {
                "title": "深夜茶话会",
                "roomKind": "roleplay",
                "description": "两个角色聊近况",
                "scenarioPrompt": "场景在安静的茶室，交流要克制自然。",
                "routingPolicy": "invite_only",
                "workspaceRoots": [],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )
        room = created["room"]
        self.assertEqual(room["roomKind"], "roleplay")
        self.assertEqual(room["workspaceRoots"], [])
        self.assertTrue(all(
            self.service.sessions.get(str(item["sessionId"]))["mode"] == "assistant"
            for item in room["participants"]
        ))
        current, future = room["participants"]
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:first"}):
            first = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "今天有点累",
                    "participantIds": [str(current["id"])],
                },
            )
        self.assertEqual(first["routeDecision"]["reason"], "explicit_invite")
        self.service.rooms.append_event(
            room_id=str(room["id"]),
            event_type="participant_message",
            payload={
                "data": {
                    "message": {
                        "role": "assistant",
                        "blocks": [
                            {
                                "type": "text",
                                "data": {"text": "先坐一会儿，慢慢说。"},
                            }
                        ],
                    }
                }
            },
            participant_id=str(current["id"]),
            topic_id=str(room["activeTopicId"]),
        )
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:second"}) as prompt:
            second = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "你怎么看？",
                    "participantIds": [str(future["id"])],
                },
            )
        self.assertEqual(second["participant"]["id"], future["id"])
        prompt_payload = prompt.call_args.args[1]
        self.assertEqual(prompt_payload["message"], "你怎么看？")
        materialized = prompt_payload["_transientContext"]
        self.assertIn("安静的茶室", materialized)
        self.assertIn("今天有点累", materialized)
        self.assertIn("先坐一会儿，慢慢说", materialized)
        self.assertNotIn("受管 Room 上下文", materialized)
        self.assertNotIn("[此刻的发言]", materialized)


if __name__ == "__main__":
    unittest.main()
