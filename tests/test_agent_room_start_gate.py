from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_room_start_gate import AgentRoomStartGateStore
from rag_ime.agent_service import AgentService
from rag_ime.pi_runtime import PiRuntimeConfig

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AgentRoomStartGateStoreTests(unittest.TestCase):
    def test_claim_is_durable_and_replays_same_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRoomStartGateStore(Path(directory) / "agent.sqlite")
            store.initialize()

            first = store.claim(
                room_id="room:one",
                objective_text="修复 trace",
                client_message_id="client:one",
                target_participant_ids=["participant:one"],
                work_item_id="work:one",
                now_ms=100,
            )
            replay = store.claim(
                room_id="room:one",
                objective_text="修复 trace",
                client_message_id="client:one",
                target_participant_ids=["participant:one"],
                work_item_id="work:one",
                now_ms=200,
            )

            self.assertEqual(first["status"], "pending")
            self.assertEqual(replay["status"], "pending")
            self.assertTrue(replay["idempotentReplay"])
            self.assertEqual(replay["gateId"], first["gateId"])


class AgentRoomStartGateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-room-start-gate-")
        root = Path(self.tmp.name)
        self.service = AgentService(
            db_path=root / "rag-ime.sqlite",
            runtime_config=PiRuntimeConfig(
                enabled=False,
                executable=None,
                agent_dir=root / "agent-config",
                session_dir=root / "sessions",
                logs_dir=root / "logs",
            ),
        )
        self.root = root

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def test_first_executable_room_message_dispatches_without_second_confirmation(self) -> None:
        room = self.service.create_room(
            {
                "title": "Trace 修复",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participant = room["participants"][0]
        work = self.service.room_work.create(
            room_id=str(room["id"]),
            objective="修复 trace",
            expected_output="通过测试",
            acceptance_criteria=["测试通过"],
            current_owner_participant_id=str(participant["id"]),
            created_by_participant_id=str(participant["id"]),
            client_message_id="work:one",
            topic_id=str(room["activeTopicId"]),
            state="active",
        )

        with patch.object(
            self.service,
            "prompt",
            return_value={"turnId": "turn:direct"},
        ) as prompt:
            response = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "请修复 trace",
                    "workItemId": work["id"],
                    "clientMessageId": "client:one",
                },
            )
            replay = self.service.post_room_message(
                str(room["id"]),
                {
                    "message": "请修复 trace",
                    "workItemId": work["id"],
                    "clientMessageId": "client:one",
                },
            )

        self.assertTrue(response["accepted"])
        self.assertEqual(response["phase"], "execution")
        self.assertNotIn("startConfirmation", response)
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["roomTurnId"], response["roomTurnId"])
        prompt.assert_called_once()
        self.assertIsNone(self.service.room_start_gates.get(str(room["id"])))
        snapshot = self.service.room_snapshot(str(room["id"]))
        self.assertIsNone(snapshot["room"]["startGate"])
        self.assertFalse(
            any(
                event["eventType"] == "room_start_confirmation_required"
                for event in snapshot["events"]
            )
        )

    def test_legacy_confirmation_dispatches_original_task_and_is_idempotent(self) -> None:
        room = self.service.create_room(
            {
                "title": "确认后执行",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participant = room["participants"][0]
        work = self.service.room_work.create(
            room_id=str(room["id"]), objective="执行原任务", expected_output="结果",
            acceptance_criteria=["结果"], current_owner_participant_id=str(participant["id"]),
            created_by_participant_id=str(participant["id"]), client_message_id="work:two",
            topic_id=str(room["activeTopicId"]), state="active",
        )
        media = self.service.import_media(
            room_id=str(room["id"]),
            data=PNG_1X1,
            mime_type="image/png",
            file_name="start-gate.png",
        )["media"]
        pending = self.service.room_start_gates.claim(
            room_id=str(room["id"]),
            objective_text="原任务",
            client_message_id="client:two",
            target_participant_ids=[str(participant["id"])],
            work_item_id=str(work["id"]),
            attachment_ids=[str(media["mediaId"])],
            retry_of_root_id="",
        )
        with (
            patch.object(
                self.service.runtime,
                "model_catalog",
                return_value={"selected": {"supportsImages": True}},
            ),
            patch.object(self.service, "prompt", return_value={"turnId": "turn:confirmed"}) as prompt,
        ):
            confirmed = self.service.confirm_room_start(
                str(room["id"]), {"gateId": pending["gateId"], "decision": "confirm"},
            )
            replay = self.service.confirm_room_start(
                str(room["id"]), {"gateId": pending["gateId"], "decision": "confirm"},
            )
        self.assertTrue(confirmed["accepted"])
        self.assertEqual(confirmed["phase"], "execution")
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay["roomTurnId"], confirmed["roomTurnId"])
        self.assertEqual(prompt.call_args.args[1]["attachments"], [media["mediaId"]])
        prompt.assert_called_once()

    def test_confirmed_legacy_gate_does_not_block_a_later_work_item(self) -> None:
        room = self.service.create_room(
            {
                "title": "确认一次后继续执行",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        participant = room["participants"][0]
        second_participant = room["participants"][1]
        first_work = self.service.room_work.create(
            room_id=str(room["id"]), objective="执行第一个任务", expected_output="结果一",
            acceptance_criteria=["结果一"], current_owner_participant_id=str(participant["id"]),
            created_by_participant_id=str(participant["id"]), client_message_id="work:first",
            topic_id=str(room["activeTopicId"]), state="active",
        )
        second_work = self.service.room_work.create(
            room_id=str(room["id"]), objective="执行第二个任务", expected_output="结果二",
            acceptance_criteria=["结果二"], current_owner_participant_id=str(second_participant["id"]),
            created_by_participant_id=str(participant["id"]), client_message_id="work:second",
            topic_id=str(room["activeTopicId"]), state="active",
        )
        pending = self.service.room_start_gates.claim(
            room_id=str(room["id"]),
            objective_text="执行第一个任务",
            client_message_id="client:first",
            target_participant_ids=[str(participant["id"])],
            work_item_id=str(first_work["id"]),
            attachment_ids=[],
            retry_of_root_id="",
        )
        with patch.object(
            self.service,
            "prompt",
            side_effect=[{"turnId": "turn:first"}, {"turnId": "turn:second"}],
        ) as prompt:
            first = self.service.confirm_room_start(
                str(room["id"]),
                {"gateId": pending["gateId"], "decision": "confirm"},
            )
            second = self.service.post_room_message(
                str(room["id"]),
                {"message": "第二个任务", "workItemId": second_work["id"], "clientMessageId": "client:second"},
            )

        self.assertTrue(first["accepted"])
        self.assertTrue(second["accepted"])
        self.assertEqual(second["phase"], "execution")
        self.assertNotIn("startConfirmation", second)
        self.assertEqual(prompt.call_count, 2)

    def test_conversation_only_room_message_does_not_create_gate(self) -> None:
        room = self.service.create_room(
            {
                "title": "只聊天",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {"roleId": "companion-present-v1", "roleVersion": "1"},
                    {"roleId": "companion-future-v1", "roleVersion": "1"},
                ],
            }
        )["room"]
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:chat"}):
            response = self.service.post_room_message(
                str(room["id"]),
                {"message": "聊聊今天的安排", "clientMessageId": "client:chat"},
            )
        self.assertTrue(response["accepted"])
        self.assertIsNone(self.service.room_start_gates.get(str(room["id"])))


if __name__ == "__main__":
    unittest.main()
