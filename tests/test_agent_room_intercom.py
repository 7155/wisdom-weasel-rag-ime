from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from rag_ime.agent_room_intercom import AgentRoomIntercomRouter, AgentRoomIntercomStore
from rag_ime.agent_rooms import AgentRoomStore
from rag_ime.agent_sessions import AgentSessionStore


class AgentRoomIntercomTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-intercom-")
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "rag-ime.sqlite"
        self.sessions = AgentSessionStore(self.db_path)
        self.sessions.initialize()
        self.first = self.sessions.create(title="研究员")
        self.second = self.sessions.create(title="审阅员")
        self.rooms = AgentRoomStore(self.db_path, room_dir=self.root / "rooms")
        self.rooms.initialize()
        self.room = self.rooms.create(
            title="架构复核",
            routing_policy="manual_mentions",
            participants=[
                {
                    "sessionId": self.first["id"],
                    "roleId": "researcher",
                    "roleVersion": "1",
                    "displayName": "研究员",
                },
                {
                    "sessionId": self.second["id"],
                    "roleId": "reviewer",
                    "roleVersion": "1",
                    "displayName": "审阅员",
                },
            ],
        )
        self.first_participant = self.room["participants"][0]
        self.second_participant = self.room["participants"][1]
        self.store = AgentRoomIntercomStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_send_is_idempotent_and_client_id_reuse_fails_closed(self) -> None:
        payload = {
            "kind": "send",
            "targetParticipantId": self.second_participant["id"],
            "clientMessageId": "turn-1-send-1",
            "content": "请核对 Artifact 所有权。",
        }

        first, created = self._enqueue(str(self.first["id"]), payload)
        repeated, repeated_created = self._enqueue(str(self.first["id"]), payload)

        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(repeated["id"], first["id"])
        with self.assertRaisesRegex(ValueError, "different room message"):
            self._enqueue(
                str(self.first["id"]),
                {**payload, "content": "偷偷换一条内容"},
            )

    def test_ask_reply_correlation_is_one_to_one_and_directional(self) -> None:
        ask, _ = self._enqueue(
            str(self.first["id"]),
            {
                "kind": "ask",
                "targetParticipantId": self.second_participant["id"],
                "clientMessageId": "ask-1",
                "content": "这个边界是否足够严格？",
            },
        )
        self.store.claim(str(ask["id"]))
        self.store.mark_delivered(str(ask["id"]), accepted_turn_id="turn:ask")

        with self.assertRaisesRegex(ValueError, "addressed participant"):
            self._enqueue(
                str(self.first["id"]),
                {
                    "kind": "reply",
                    "clientMessageId": "wrong-reply",
                    "replyTo": ask["id"],
                    "content": "自己回答自己",
                },
            )

        reply, _ = self._enqueue(
            str(self.second["id"]),
            {
                "kind": "reply",
                "clientMessageId": "reply-1",
                "replyTo": ask["id"],
                "content": "足够严格，所有权由 Kernel 校验。",
            },
        )
        self.assertEqual(reply["targetParticipantId"], self.first_participant["id"])
        self.store.claim(str(reply["id"]))
        self.store.mark_delivered(str(reply["id"]), accepted_turn_id="turn:reply")
        self.assertEqual(self.store.get(str(ask["id"]))["status"], "replied")

        with self.assertRaisesRegex(ValueError, "already has a reply"):
            self._enqueue(
                str(self.second["id"]),
                {
                    "kind": "reply",
                    "clientMessageId": "reply-2",
                    "replyTo": ask["id"],
                    "content": "第二份冲突回复",
                },
            )

    def test_restart_fails_unknown_delivering_outcome_instead_of_replaying(self) -> None:
        message, _ = self._enqueue(
            str(self.first["id"]),
            {
                "kind": "send",
                "targetParticipantId": self.second_participant["id"],
                "clientMessageId": "crash-1",
                "content": "已经开始投递但结果未知",
            },
        )
        self.store.claim(str(message["id"]))

        restarted = AgentRoomIntercomStore(self.db_path)
        recovered = restarted.initialize()

        self.assertEqual(recovered, 1)
        failed = restarted.get(str(message["id"]))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("outcome unknown", failed["error"])

    def test_router_waits_for_idle_then_delivers_and_audits(self) -> None:
        idle = {str(self.second["id"]): False}
        generations = {str(self.first["id"]): 1, str(self.second["id"]): 1}
        delivered: list[dict[str, object]] = []
        audits: list[tuple[str, str]] = []
        router = AgentRoomIntercomRouter(
            self.store,
            generation_provider=lambda session_id: generations[session_id],
            idle_probe=lambda session_id: idle.get(session_id, True),
            delivery_handler=lambda item: delivered.append(dict(item)) or {"turnId": "turn:1"},
            audit_publisher=lambda item, phase: audits.append((str(item["id"]), phase)),
        )
        try:
            item = router.enqueue(
                str(self.first["id"]),
                {
                    "kind": "send",
                    "targetParticipantId": self.second_participant["id"],
                    "clientMessageId": "idle-gate-1",
                    "content": "等你空闲后再处理",
                },
            )
            time.sleep(0.08)
            self.assertEqual(self.store.get(str(item["id"]))["status"], "queued")
            self.assertEqual(delivered, [])

            idle[str(self.second["id"])] = True
            router.notify()
            final = self._wait_for_status(str(item["id"]), "delivered")

            self.assertEqual(final["acceptedTurnId"], "turn:1")
            self.assertEqual(len(delivered), 1)
            self.assertIn((str(item["id"]), "queued"), audits)
            self.assertIn((str(item["id"]), "delivered"), audits)
        finally:
            router.close()

    def test_router_marks_generation_mismatch_stale_without_delivery(self) -> None:
        idle = {str(self.second["id"]): False}
        generations = {str(self.first["id"]): 3, str(self.second["id"]): 7}
        delivered: list[dict[str, object]] = []
        router = AgentRoomIntercomRouter(
            self.store,
            generation_provider=lambda session_id: generations[session_id],
            idle_probe=lambda session_id: idle.get(session_id, True),
            delivery_handler=lambda item: delivered.append(dict(item)) or {"turnId": "unexpected"},
            audit_publisher=lambda _item, _phase: None,
        )
        try:
            item = router.enqueue(
                str(self.first["id"]),
                {
                    "kind": "send",
                    "targetParticipantId": self.second_participant["id"],
                    "clientMessageId": "generation-1",
                    "content": "旧运行时不应收到这条消息",
                },
            )
            generations[str(self.second["id"])] = 8
            idle[str(self.second["id"])] = True
            router.notify()

            final = self._wait_for_status(str(item["id"]), "stale")

            self.assertIn("generation changed", final["error"])
            self.assertEqual(delivered, [])
        finally:
            router.close()

    def _enqueue(self, source_session_id: str, payload: dict[str, object]):
        route = self.store.resolve_route(source_session_id, payload)
        return self.store.enqueue(
            source_session_id,
            payload,
            source_generation=1,
            target_generation=1,
            expected_target_participant_id=str(route["target"]["id"]),
        )

    def _wait_for_status(
        self,
        message_id: str,
        expected: str,
        *,
        timeout: float = 2.0,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.store.get(message_id)
            if item["status"] == expected:
                return item
            time.sleep(0.01)
        self.fail(f"message {message_id} did not reach {expected}")


if __name__ == "__main__":
    unittest.main()
