from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag_ime.agent_room_application import RoomApplicationService
from rag_ime.agent_service import AgentService
from rag_ime.pi_runtime import PiRuntimeConfig


class RoomParticipantSteerTests(unittest.TestCase):
    def test_steer_binds_one_current_target_and_rejects_stale_or_ambiguous_targets(self) -> None:
        room_id = "room:running-steer"
        root_id = "root:running-steer"
        participant = {"id": "participant:worker", "roomId": room_id, "status": "active", "sessionId": "session:worker"}
        target = {"roomId": room_id, "rootId": root_id, "taskId": "task:worker", "dispatchId": "dispatch:worker", "participantId": participant["id"], "sessionId": participant["sessionId"], "generation": 4, "taskState": "active", "currentOwnerParticipantId": participant["id"], "runtimeTurnId": "turn:worker"}
        kernel = Mock()
        kernel.root.return_value = {"rootId": root_id, "roomId": room_id, "generation": 4, "state": "running"}
        kernel.active_runtime_targets.return_value = [target]
        kernel.task.return_value = {"taskId": target["taskId"], "rootId": root_id, "state": "active", "currentOwnerParticipantId": participant["id"]}
        rooms = Mock()
        rooms.get.return_value = {"id": room_id, "status": "active"}
        rooms.participant.return_value = participant
        sessions = Mock()
        sessions.get.return_value = {"id": participant["sessionId"], "status": "busy"}
        sessions.runtime_turn_terminal_event.return_value = None
        sessions.latest_runtime_turn_id.return_value = target["runtimeTurnId"]
        deliver = Mock(return_value={"accepted": True, "queued": True, "turnId": target["runtimeTurnId"]})
        service = RoomApplicationService(rooms=rooms, sessions=sessions, personas=Mock(), role_books=Mock(), work_items=Mock(), kernel=kernel, commands=Mock(), projection=Mock(), context=Mock(), requirements=Mock(), capabilities=Mock(), public_timeline=Mock(), session_mode_gate=Mock(), wake_worker=Mock(), restore_participant_sessions=Mock(), resolve_attachments=Mock(), deliver_steer=deliver)
        payload = {"action": "steer_participant", "rootId": root_id, "expectedGeneration": 4, "participantId": participant["id"], "clientActionId": "action:steer", "message": "补充验收。"}

        response = service.steer_participant(room_id, payload)

        self.assertEqual(response["runtimeTurnId"], target["runtimeTurnId"])
        deliver.assert_called_once_with(participant["sessionId"], payload["message"], payload["clientActionId"])
        for targets, terminal, latest, error in (
            ([], None, target["runtimeTurnId"], "exactly one running target"),
            ([target, dict(target)], None, target["runtimeTurnId"], "exactly one running target"),
            ([target], {"eventType": "turn_completed"}, target["runtimeTurnId"], "runtime turn is terminal"),
            ([target], None, "turn:other", "runtime turn is stale"),
        ):
            kernel.active_runtime_targets.return_value = targets
            sessions.runtime_turn_terminal_event.return_value = terminal
            sessions.latest_runtime_turn_id.return_value = latest
            with self.subTest(error=error), self.assertRaisesRegex(Exception, error):
                service.steer_participant(room_id, payload)
        kernel.active_runtime_targets.return_value = [target]
        sessions.runtime_turn_terminal_event.return_value = None
        sessions.latest_runtime_turn_id.return_value = target["runtimeTurnId"]
        rooms.participant.return_value = {**participant, "roomId": "room:other"}
        with self.assertRaisesRegex(Exception, "not active in this Room"):
            service.steer_participant(room_id, payload)

    def test_service_receipt_replays_the_same_client_action_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = AgentService(db_path=root / "test.sqlite", runtime_config=PiRuntimeConfig(enabled=False, executable=None, agent_dir=root / "agent", session_dir=root / "sessions", logs_dir=root / "logs"))
            self.addCleanup(service.close)
            payload = {"action": "steer_participant", "rootId": "root:1", "expectedGeneration": 1, "participantId": "participant:1", "clientActionId": "action:once", "message": "补充验收。"}
            accepted = {"schemaVersion": "rag-ime.room-participant-steer.v1", "ok": True, "accepted": True, "roomId": "room:1", "rootId": "root:1", "runtimeTurnId": "turn:1"}
            with patch.object(service.room_application, "steer_participant", return_value=accepted) as steer:
                first = service.steer_room_participant("room:1", payload)
                replay = service.steer_room_participant("room:1", payload)
            steer.assert_called_once_with("room:1", payload)
            self.assertEqual(first["controlReceipt"]["state"], "accepted")
            self.assertTrue(replay["idempotentReplay"])


if __name__ == "__main__":
    unittest.main()
