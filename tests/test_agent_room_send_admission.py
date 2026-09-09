from __future__ import annotations

import concurrent.futures
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_service import AgentService
from rag_ime.pi.config import PiRuntimeConfig


class RoomSendAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="paw-room-send-admission-")
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
        self.room = self.service.create_room({
            "title": "发送恢复",
            "workspaceRoots": [str(self.root)],
            "participants": [
                {"roleId": "companion-present-v1", "roleVersion": "1"},
                {"roleId": "companion-future-v1", "roleVersion": "1"},
            ],
        })["room"]
        self.target = self.room["participants"][0]
        self.session_id = str(self.target["sessionId"])

    def tearDown(self) -> None:
        self.service.close()
        self.tmp.cleanup()

    def send(self, client_message_id: str) -> dict[str, object]:
        return self.service.post_room_message(str(self.room["id"]), {
            "message": "是什么问题呀",
            "clientMessageId": client_message_id,
            "participantIds": [str(self.target["id"])],
        })

    def test_session_prewarm_memory_probe_does_not_reserve_room_send(self) -> None:
        probe_entered = threading.Event()
        release_probe = threading.Event()

        def probe(*_args: object, **_kwargs: object) -> dict[str, object]:
            probe_entered.set()
            self.assertTrue(release_probe.wait(timeout=5))
            return {"ok": True}

        with (
            patch.object(self.service.runtime, "ensure", return_value={"state": {"isIdle": True}}),
            patch.object(self.service, "_probe_memory_maintenance", side_effect=probe),
            patch.object(self.service, "prompt", return_value={"turnId": "turn:after-prewarm"}) as prompt,
            concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor,
        ):
            warmup = executor.submit(self.service.ensure_runtime, {"sessionId": self.session_id})
            try:
                self.assertTrue(probe_entered.wait(timeout=5))
                accepted = self.send("send-during-prewarm")
                self.assertTrue(accepted["accepted"])
                prompt.assert_called_once()
            finally:
                release_probe.set()
                warmup.result(timeout=5)

    def test_failed_availability_probe_releases_only_its_own_reservation(self) -> None:
        unrelated_session = str(self.room["participants"][1]["sessionId"])
        self.service.room_turns.hold_priority((unrelated_session,))
        baseline = self.service.rooms.get(str(self.room["id"]))["lastEventSequence"]
        with patch.object(
            self.service, "_room_target_idle",
            side_effect=sqlite3.OperationalError("unable to open database file"),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "unable to open database"):
                self.send("failed-read-before-dispatch")

        self.assertEqual(self.service.rooms.get(str(self.room["id"]))["lastEventSequence"], baseline)
        self.assertEqual(self.service.room_turns.user_priority_sessions, {unrelated_session})
        with patch.object(self.service, "prompt", return_value={"turnId": "turn:after-probe-error"}) as prompt:
            self.assertTrue(self.send("manual-send-after-probe-error")["accepted"])
            prompt.assert_called_once()

    def test_real_inflight_room_turn_stays_reserved_with_a_typed_rejection(self) -> None:
        self.service.room_turns.begin(self.session_id, "root:inflight", dispatch_id="dispatch:inflight")
        self.service.room_turns.accept(self.session_id, "turn:inflight", "root:inflight")
        baseline = self.service.rooms.get(str(self.room["id"]))["lastEventSequence"]
        with patch.object(self.service, "prompt") as prompt:
            with self.assertRaises(ValueError) as failure:
                self.send("rejected-real-busy")
            prompt.assert_not_called()
        payload = getattr(failure.exception, "response_payload", lambda: {})()
        self.assertEqual(payload.get("code"), "AGENT_COMMAND_FAILED")
        self.assertEqual(payload.get("commandReceipt"), {
            "state": "failed",
            "clientMessageId": "rejected-real-busy",
            "causeCode": "ROOM_PARTICIPANT_BUSY",
        })
        self.assertEqual(self.service.room_turns.active_turn(self.session_id), ("root:inflight", "dispatch:inflight"))
        self.assertEqual(self.service.rooms.get(str(self.room["id"]))["lastEventSequence"], baseline)

    def test_delivery_metadata_failure_keeps_accepted_pi_turn_and_replay_identity(self) -> None:
        for operation in ("advance_delivery_cursor", "commit_route"):
            with self.subTest(operation=operation):
                client_id = f"accepted-before-{operation}-failure"
                with patch.object(self.service, "prompt", return_value={"accepted": True, "turnId": f"turn:{operation}"}) as prompt, patch.object(
                    self.service.rooms, operation, side_effect=sqlite3.OperationalError("fixture metadata write failed"),
                ):
                    accepted = self.send(client_id)
                    replay = self.send(client_id)
                prompt.assert_called_once()
                self.assertTrue(accepted["accepted"])
                self.assertTrue(replay["idempotentReplay"])
                root_id = str(accepted["roomTurnId"])
                self.assertEqual(replay["roomTurnId"], root_id)
                self.assertEqual(self.service.room_turns.active_turn(self.session_id)[0], root_id)
                self.assertFalse(self.service.room_turns.user_priority_sessions)
                self.assertEqual(accepted["dispatches"][0]["projectionSync"], {"state": "pending", "failedOperations": [operation]})
                failures = self.service.rooms.list_events_for_turn(str(self.room["id"]), root_id, event_types=("turn_failed",))
                self.assertEqual(failures, [])
                # Only the later, actual Pi terminal may end this Room turn.
                self.service.events.publish(self.session_id, "turn_failed", {"error": "fixture Provider failure"}, turn_id=f"turn:{operation}")
                self.assertTrue(self.service.events.flush())
                self.assertEqual(self.service.room_turns.active_turn(self.session_id), ("", ""))
                failures = self.service.rooms.list_events_for_turn(str(self.room["id"]), root_id, event_types=("turn_failed",))
                self.assertEqual(len(failures), 1)

    def test_worker_exception_closes_room_turn_and_releases_admission(self) -> None:
        """An untyped dispatch failure must not strand the Room as running."""
        with patch.object(
            self.service.room_dispatch,
            "dispatch_target",
            side_effect=RuntimeError("worker crashed before dispatch receipt"),
        ):
            with self.assertRaisesRegex(RuntimeError, "worker crashed"):
                self.send("worker-exception-cleanup")

        self.assertEqual(self.service.room_turns.active_turn(self.session_id), ("", ""))
        self.assertNotIn(self.session_id, self.service.room_turns.user_priority_sessions)
        failed = [
            event for event in self.service.rooms.list_events(
                str(self.room["id"]), after_sequence=0, limit=500
            ) if event.get("eventType") == "turn_failed"
        ]
        self.assertTrue(failed)

    def test_worker_exception_preserves_another_accepted_dispatch(self) -> None:
        other = self.room["participants"][1]
        dispatch = self.service.room_dispatch.dispatch_target

        def dispatch_one(**kwargs):
            if kwargs["target"]["id"] == other["id"]:
                raise RuntimeError("one worker crashed before admission")
            return dispatch(**kwargs)

        with (
            patch.object(self.service, "prompt", return_value={"accepted": True, "turnId": "turn:still-running"}),
            patch.object(self.service.room_dispatch, "dispatch_target", side_effect=dispatch_one),
        ):
            response = self.service.post_room_message(str(self.room["id"]), {
                "message": "分别核对两个部分",
                "clientMessageId": "mixed-worker-outcome",
                "participantIds": [self.target["id"], other["id"]],
            })

        self.assertTrue(response["accepted"])
        root_id = str(response["roomTurnId"])
        self.assertEqual(self.service.room_turns.active_turn(self.session_id)[0], root_id)
        self.assertEqual(self.service.room_turns.active_turn(str(other["sessionId"])), ("", ""))
        self.assertFalse(self.service.room_turns.user_priority_sessions)
        self.assertEqual([item["accepted"] for item in response["dispatches"]], [True, False])
        failures = self.service.rooms.list_events_for_turn(
            str(self.room["id"]), root_id, event_types=("turn_failed",)
        )
        self.assertEqual([item["participantId"] for item in failures], [other["id"]])

    def test_worker_failure_releases_reservation_when_terminal_write_fails(self) -> None:
        publish = self.service.room_events.publish

        def fail_terminal(**kwargs):
            if kwargs["event_type"] == "turn_failed":
                raise sqlite3.OperationalError("terminal write unavailable")
            return publish(**kwargs)

        with (
            patch.object(self.service.room_dispatch, "dispatch_target", side_effect=RuntimeError("worker crash")),
            patch.object(self.service.room_events, "publish", side_effect=fail_terminal),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "terminal write unavailable"):
                self.send("worker-terminal-write-failure")

        self.assertFalse(self.service.room_turns.user_priority_sessions)
        self.assertEqual(self.service.room_turns.active_turn(self.session_id), ("", ""))


if __name__ == "__main__":
    unittest.main()
