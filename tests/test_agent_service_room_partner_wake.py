from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_command_receipts import AgentCommandReceiptFailed
from rag_ime.agent_service import AgentService
from rag_ime.pi_runtime import PiRuntimeConfig


class AgentServiceRoomPartnerWakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-partner-wake-"
        )
        self.root = Path(self._temporary.name)
        self.service = AgentService(
            db_path=self.root / "agent.sqlite",
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
        self._temporary.cleanup()

    def _room_completion_claim(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        room = self.service.create_room(
            {
                "title": "异步交付验收",
                "workspaceRoots": [str(self.root)],
                "participants": [
                    {
                        "roleId": "companion-present-v1",
                        "roleVersion": "1",
                    },
                    {
                        "roleId": "companion-firstlight-v1",
                        "roleVersion": "1",
                    },
                ],
            }
        )["room"]
        facilitator, partner = room["participants"]
        child_dispatch_id = "room-child:wake-continuation"
        root_id = "room-root:wake-continuation"
        work_item_id = "room-work:wake-continuation"
        self.service.room_partner_dispatches.register(
            child_dispatch_id=child_dispatch_id,
            room_id=str(room["id"]),
            root_id=root_id,
            parent_dispatch_id="room-dispatch:facilitator",
            tool_call_id="tool:delegate",
            source_participant_id=str(facilitator["id"]),
            source_session_id=str(facilitator["sessionId"]),
            target_participant_id=str(partner["id"]),
            target_session_id=str(partner["sessionId"]),
            work_item_id=work_item_id,
        )
        self.service.room_partner_dispatches.mark_dispatched(child_dispatch_id)
        settled = self.service.room_partner_dispatches.settle(
            child_dispatch_id,
            status="review",
            result="伙伴已交付实现与测试证据",
            completion_source="room_post",
        )
        generation = int(settled["wake"]["generation"])
        schedule_id = f"room-wake:{child_dispatch_id}:{generation}"
        self.service.wake_schedules.create_room_wake(
            schedule_id=schedule_id,
            target_session_id=str(facilitator["sessionId"]),
            created_by_session_id=str(partner["sessionId"]),
            title="伙伴交付待验收",
            instruction="读取交付并继续同一 Room Root。",
            metadata={
                "kind": "room_partner_completion",
                "childDispatchId": child_dispatch_id,
                "generation": generation,
                "roomId": str(room["id"]),
                "rootId": root_id,
                "workItemId": work_item_id,
            },
        )
        self.service.room_partner_dispatches.mark_wake(
            child_dispatch_id,
            generation=generation,
            state="scheduled",
            schedule_id=schedule_id,
        )
        claims = self.service.wake_schedules.claim_due(
            now_ms=int(time.time() * 1000) + 1_000
        )
        self.assertEqual(len(claims), 1)
        return claims[0], facilitator, settled

    def test_busy_facilitator_defers_room_completion_on_shared_wake_ledger(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        self.service.sessions.set_status(facilitator_session_id, "busy")

        with (
            patch.object(self.service.wake_application, "dispatch") as generic_wake,
            patch.object(self.service, "prompt") as prompt,
        ):
            self.service._dispatch_wake_claim(claim)

        generic_wake.assert_not_called()
        prompt.assert_not_called()
        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "scheduled")
        self.assertEqual(schedule["latestRun"]["state"], "deferred")
        self.assertEqual(schedule["runCount"], 0)
        self.assertEqual(
            self.service.room_partner_dispatches.get(
                str(dispatch["childDispatchId"])
            )["wake"]["state"],
            "scheduled",
        )
        self.assertEqual(
            self.service.list_context_items(facilitator_session_id)["items"],
            [],
        )

    def test_typed_pi_busy_rejection_defers_room_completion_wake(
        self,
    ) -> None:
        claim, _facilitator, dispatch = self._room_completion_claim()

        with patch.object(
            self.service,
            "prompt",
            side_effect=AgentCommandReceiptFailed(
                "The Agent command failed before acceptance",
                client_message_id=str(claim["runId"]),
                cause_code="SESSION_BUSY",
            ),
        ):
            self.service.wake_scheduler._dispatch_safely(claim)

        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "scheduled")
        self.assertEqual(schedule["runCount"], 0)
        self.assertEqual(schedule["latestRun"]["state"], "deferred")
        self.assertEqual(
            schedule["latestRun"]["result"]["causeCode"],
            "SESSION_BUSY",
        )
        projected = self.service.room_partner_dispatches.get(
            str(dispatch["childDispatchId"])
        )
        self.assertEqual(projected["wake"]["state"], "scheduled")

    def test_competing_room_wake_priority_reservation_defers_before_prompt(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        self.service.room_turns.hold_priority((facilitator_session_id,))
        try:
            with patch.object(self.service, "prompt") as prompt:
                self.service._dispatch_wake_claim(claim)
        finally:
            self.service.room_turns.release_priority_session(
                facilitator_session_id
            )

        prompt.assert_not_called()
        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "scheduled")
        self.assertEqual(schedule["runCount"], 0)
        self.assertEqual(schedule["latestRun"]["state"], "deferred")
        self.assertEqual(
            schedule["latestRun"]["result"]["causeCode"],
            "AGENT_TURN_CONFLICT",
        )
        projected = self.service.room_partner_dispatches.get(
            str(dispatch["childDispatchId"])
        )
        self.assertEqual(projected["wake"]["state"], "scheduled")

    def test_faulted_facilitator_recovers_once_before_room_completion_wake(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        self.service.sessions.set_status(facilitator_session_id, "faulted")

        def recover(session_id: str) -> dict[str, object]:
            self.assertEqual(session_id, facilitator_session_id)
            self.service.sessions.set_status(session_id, "idle")
            return {"reused": True}

        with (
            patch.object(
                self.service.runtime,
                "ensure",
                side_effect=recover,
            ) as ensure,
            patch.object(
                self.service,
                "prompt",
                return_value={"accepted": True, "turnId": "turn:recovered-wake"},
            ) as prompt,
        ):
            self.service._dispatch_wake_claim(claim)

        ensure.assert_called_once_with(facilitator_session_id)
        prompt.assert_called_once()
        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "running")
        self.assertEqual(schedule["latestRun"]["state"], "accepted")
        self.assertEqual(
            self.service.room_partner_dispatches.get(
                str(dispatch["childDispatchId"])
            )["wake"]["state"],
            "delivered",
        )

    def test_faulted_room_session_retires_exact_recovered_idle_turn(self) -> None:
        _claim, facilitator, _dispatch = self._room_completion_claim()
        session_id = str(facilitator["sessionId"])
        interrupted_turn_id = "turn:interrupted-before-host-restart"
        self.service.sessions.set_status(session_id, "faulted")

        def ensure(recovered_session_id: str) -> dict[str, object]:
            self.assertEqual(recovered_session_id, session_id)
            self.service.sessions.set_status(session_id, "idle")
            return {
                "state": {
                    "schemaVersion": "rag-ime.pi-session-control-state.v1",
                    "sessionId": session_id,
                    "isIdle": True,
                    "activeTurn": {"turnId": interrupted_turn_id},
                },
                "reused": False,
            }

        with (
            patch.object(self.service.runtime, "ensure", side_effect=ensure),
            patch.object(
                self.service.runtime,
                "retire_recovered_turn",
                create=True,
                return_value={"retired": True},
            ) as retire_recovered_turn,
        ):
            self.service._recover_faulted_room_session(session_id)

        retire_recovered_turn.assert_called_once_with(
            session_id,
            interrupted_turn_id,
        )
        self.assertEqual(self.service.sessions.get(session_id)["status"], "idle")

    def test_faulted_facilitator_recovery_failure_converges_without_defer_loop(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        self.service.sessions.set_status(facilitator_session_id, "faulted")

        with patch.object(
            self.service.runtime,
            "ensure",
            side_effect=RuntimeError("Pi recovery remained unavailable"),
        ) as ensure:
            self.service.wake_scheduler._dispatch_safely(claim)

        ensure.assert_called_once_with(facilitator_session_id)
        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "failed")
        self.assertEqual(schedule["latestRun"]["state"], "failed")
        self.assertNotEqual(schedule["latestRun"]["state"], "deferred")
        failed_dispatch = self.service.room_partner_dispatches.get(
            str(dispatch["childDispatchId"])
        )
        self.assertEqual(failed_dispatch["wake"]["state"], "failed")
        self.assertIn("recovery remained unavailable", failed_dispatch["error"])

    def test_idle_facilitator_continues_same_root_and_failed_turn_stays_failed(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        root_id = str(dispatch["rootId"])
        child_dispatch_id = str(dispatch["childDispatchId"])

        with (
            patch.object(self.service.wake_application, "dispatch") as generic_wake,
            patch.object(
                self.service,
                "prompt",
                return_value={"accepted": True, "turnId": "turn:room-wake"},
            ) as prompt,
        ):
            self.service._dispatch_wake_claim(claim)

        generic_wake.assert_not_called()
        prompt.assert_called_once()
        self.assertEqual(prompt.call_args.args[0], facilitator_session_id)
        self.assertEqual(prompt.call_args.args[1]["_contextSource"], "room")
        self.assertEqual(prompt.call_args.args[1]["clientMessageId"], claim["runId"])
        self.assertEqual(
            self.service.room_turns.active_turn(facilitator_session_id),
            (
                root_id,
                "room-wake-dispatch:"
                f"{child_dispatch_id}:{dispatch['wake']['generation']}",
            ),
        )

        context_items = self.service.list_context_items(facilitator_session_id)[
            "items"
        ]
        self.assertEqual(len(context_items), 1)
        self.assertEqual(
            context_items[0]["sourceKind"],
            "room_partner_completion",
        )
        self.assertEqual(context_items[0]["sourceId"], claim["runId"])
        self.assertEqual(context_items[0]["lane"], "room")
        running = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["latestRun"]["state"], "accepted")
        self.assertEqual(
            self.service.room_partner_dispatches.get(child_dispatch_id)["wake"][
                "state"
            ],
            "delivered",
        )

        self.service.events.publish(
            facilitator_session_id,
            "turn_failed",
            {"error": "Facilitator 验收回合失败"},
            turn_id="turn:room-wake",
        )
        self.assertTrue(self.service.events.flush())

        failed = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["latestRun"]["state"], "failed")
        self.assertNotEqual(failed["status"], "completed")
        failed_dispatch = self.service.room_partner_dispatches.get(
            child_dispatch_id
        )
        self.assertEqual(failed_dispatch["status"], "review")
        self.assertNotEqual(failed_dispatch["status"], "accepted")
        room_events = self.service.rooms.list_events(str(dispatch["roomId"]))
        mirrored_terminal = [
            event
            for event in room_events
            if event["turnId"] == root_id
            and event["eventType"] == "turn_failed"
        ]
        self.assertEqual(len(mirrored_terminal), 1)
        self.assertEqual(
            mirrored_terminal[0]["payload"]["data"]["rootId"],
            root_id,
        )
        self.assertEqual(
            mirrored_terminal[0]["payload"]["data"]["status"],
            "failed",
        )

    def test_runtime_host_failure_requeues_same_root_after_wake_run_settles(
        self,
    ) -> None:
        claim, facilitator, dispatch = self._room_completion_claim()
        facilitator_session_id = str(facilitator["sessionId"])
        child_dispatch_id = str(dispatch["childDispatchId"])
        old_schedule_id = str(claim["id"])

        with patch.object(
            self.service,
            "prompt",
            return_value={"accepted": True, "turnId": "turn:host-exit"},
        ):
            self.service._dispatch_wake_claim(claim)

        self.service.room_partner_dispatches.record_review(
            child_dispatch_id,
            accepted=True,
        )

        old_runs_before = self.service.wake_schedules.runs(old_schedule_id)
        self.assertEqual(old_runs_before[0]["state"], "accepted")

        self.service.events.publish(
            facilitator_session_id,
            "turn_failed",
            {
                "error": "invalid Pi Runtime Host JSONL: partial protocol record",
                "failureKind": "runtime_host_exit",
                "exitCode": 1,
            },
            turn_id="turn:host-exit",
        )
        self.assertTrue(self.service.events.flush())

        old_schedule = self.service.get_wake_schedule(old_schedule_id)
        self.assertEqual(old_schedule["status"], "failed")
        self.assertEqual(old_schedule["latestRun"]["state"], "failed")
        self.assertEqual(
            old_schedule["latestRun"]["result"]["failureKind"],
            "runtime_host_exit",
        )
        recovered = self.service.room_partner_dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["rootId"], dispatch["rootId"])
        self.assertEqual(recovered["sourceSessionId"], facilitator_session_id)
        self.assertEqual(recovered["status"], "accepted")
        self.assertEqual(recovered["wake"]["generation"], 2)
        self.assertEqual(recovered["wake"]["state"], "scheduled")
        self.assertEqual(
            recovered["wake"]["scheduleId"],
            f"room-wake:{child_dispatch_id}:2",
        )
        self.assertEqual(
            self.service.wake_schedules.runs(old_schedule_id)[0]["id"],
            old_runs_before[0]["id"],
        )
        next_claim = self.service.wake_schedules.claim_due(
            now_ms=int(time.time() * 1000) + 1_000,
        )[0]
        with patch.object(
            self.service.room_partner_application,
            "dispatch_facilitator_wake",
            return_value=True,
        ) as dispatch_retry:
            self.service.room_partner_application.dispatch_wake(next_claim)
        dispatch_retry.assert_called_once()
        delivered = self.service.room_partner_dispatches.get(child_dispatch_id)
        self.assertEqual(delivered["status"], "accepted")
        self.assertEqual(delivered["wake"]["generation"], 2)
        self.assertEqual(delivered["wake"]["state"], "delivered")
        second_schedule = self.service.get_wake_schedule(
            str(delivered["wake"]["scheduleId"])
        )
        self.assertIn("不要重复 accept", second_schedule["instruction"])
        self.assertIn("post(kind=result)", second_schedule["instruction"])

    def test_failed_room_wake_converges_schedule_and_dispatch_ledgers(
        self,
    ) -> None:
        claim, _facilitator, dispatch = self._room_completion_claim()
        child_dispatch_id = str(dispatch["childDispatchId"])

        with patch.object(
            self.service,
            "prompt",
            side_effect=RuntimeError("Pi acceptance remained unproven"),
        ):
            self.service.wake_scheduler._dispatch_safely(claim)

        schedule = self.service.get_wake_schedule(str(claim["id"]))
        self.assertEqual(schedule["status"], "failed")
        self.assertEqual(schedule["latestRun"]["state"], "failed")
        self.assertIn("unproven", schedule["lastError"])

        failed_dispatch = self.service.room_partner_dispatches.get(
            child_dispatch_id
        )
        self.assertEqual(failed_dispatch["status"], "review")
        self.assertEqual(failed_dispatch["wake"]["state"], "failed")
        self.assertEqual(failed_dispatch["wake"]["scheduleId"], claim["id"])
        self.assertIn("unproven", failed_dispatch["error"])

    def test_restart_reconcile_repairs_legacy_failed_wake_projection(
        self,
    ) -> None:
        claim, _facilitator, dispatch = self._room_completion_claim()
        child_dispatch_id = str(dispatch["childDispatchId"])
        self.service.wake_schedules.fail_dispatch(
            str(claim["runId"]),
            error="legacy Gateway lost Pi acceptance",
        )

        before = self.service.room_partner_dispatches.get(child_dispatch_id)
        self.assertEqual(before["wake"]["state"], "scheduled")

        self.service.room_partner_application.reconcile()

        after = self.service.room_partner_dispatches.get(child_dispatch_id)
        self.assertEqual(after["wake"]["state"], "failed")
        self.assertEqual(after["wake"]["scheduleId"], claim["id"])
        self.assertIn("legacy Gateway", after["error"])


if __name__ == "__main__":
    unittest.main()
