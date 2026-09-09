from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.rooms.partner_dispatch_store import (
    AgentRoomPartnerDispatchStore,
)
from rag_ime.agent_wake_scheduler import AgentWakeScheduleStore


class AgentRoomPartnerDispatchStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temporary.name) / "agent.db"
        self.store = AgentRoomPartnerDispatchStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_register_is_idempotent_and_terminal_state_is_collectable(self) -> None:
        values = {
            "child_dispatch_id": "room-child:one",
            "room_id": "room-a",
            "root_id": "room-root:a",
            "parent_dispatch_id": "room-dispatch:parent",
            "tool_call_id": "tool:delegate",
            "source_participant_id": "room-a:p1",
            "source_session_id": "session:lead",
            "target_participant_id": "room-a:p2",
            "target_session_id": "session:partner",
            "work_item_id": "room-work:one",
        }
        first = self.store.register(**values)
        replay = self.store.register(**values)

        self.assertEqual(first["childDispatchId"], replay["childDispatchId"])
        self.assertEqual(replay["status"], "prepared")

        self.store.mark_dispatched("room-child:one")
        settled = self.store.settle(
            "room-child:one",
            status="review",
            result="伙伴交付摘要",
            completion_source="room_post",
            post_id="room-post:one",
        )

        self.assertEqual(settled["status"], "review")
        self.assertEqual(settled["workItemId"], "room-work:one")
        self.assertEqual(settled["result"], "伙伴交付摘要")
        self.assertEqual(
            self.store.wait("room-child:one", timeout_seconds=0.01)["status"],
            "review",
        )

    def test_cancelled_admission_does_not_schedule_a_completion_wake(self) -> None:
        self.store.register(
            child_dispatch_id="room-child:cancelled-admission",
            room_id="room-a",
            root_id="room-root:a",
            parent_dispatch_id="room-dispatch:parent",
            tool_call_id="tool:cancelled-admission",
            source_participant_id="room-a:p1",
            source_session_id="session:lead",
            target_participant_id="room-a:p2",
            target_session_id="session:partner",
            work_item_id="room-work:cancelled-admission",
        )

        cancelled = self.store.settle(
            "room-child:cancelled-admission",
            status="cancelled",
            result="",
            completion_source="dispatch_cancelled",
            error="Pi Runtime cancelled the Room dispatch before admission",
        )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["wake"]["state"], "cancelled")
        self.assertEqual(self.store.pending_wakes(), [])

    def test_room_wake_is_deterministic_and_carries_private_metadata(self) -> None:
        schedules = AgentWakeScheduleStore(self.db_path)
        schedules.initialize()

        first = schedules.create_room_wake(
            schedule_id="room-wake:room-child:one:1",
            target_session_id="session:lead",
            created_by_session_id="session:partner",
            title="伙伴交付待验收",
            instruction="检查 WorkItem 并进行双轴验收。",
            metadata={
                "kind": "room_partner_completion",
                "childDispatchId": "room-child:one",
                "generation": 1,
            },
            now_ms=1_000,
        )
        replay = schedules.create_room_wake(
            schedule_id="room-wake:room-child:one:1",
            target_session_id="session:lead",
            created_by_session_id="session:partner",
            title="伙伴交付待验收",
            instruction="检查 WorkItem 并进行双轴验收。",
            metadata={
                "kind": "room_partner_completion",
                "childDispatchId": "room-child:one",
                "generation": 1,
            },
            now_ms=1_000,
        )

        self.assertEqual(first["id"], replay["id"])
        self.assertEqual(
            replay["metadata"],
            {
                "kind": "room_partner_completion",
                "childDispatchId": "room-child:one",
                "generation": 1,
            },
        )
        claims = schedules.claim_due(now_ms=1_000)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["metadata"]["childDispatchId"], "room-child:one")

    def test_late_terminal_event_cannot_reopen_an_explicitly_reviewed_dispatch(
        self,
    ) -> None:
        self.store.register(
            child_dispatch_id="room-child:reviewed",
            room_id="room-a",
            root_id="room-root:a",
            parent_dispatch_id="room-dispatch:parent",
            tool_call_id="tool:reviewed",
            source_participant_id="room-a:p1",
            source_session_id="session:lead",
            target_participant_id="room-a:p2",
            target_session_id="session:partner",
            work_item_id="room-work:reviewed",
        )
        self.store.mark_dispatched("room-child:reviewed")
        submitted = self.store.settle(
            "room-child:reviewed",
            status="review",
            result="first delivery",
            completion_source="room_post",
        )
        generation = submitted["wake"]["generation"]
        self.store.record_review("room-child:reviewed", accepted=True)

        replayed = self.store.settle(
            "room-child:reviewed",
            status="review",
            result="late duplicate delivery",
            completion_source="session_terminal",
        )

        self.assertEqual(replayed["status"], "accepted")
        self.assertEqual(replayed["result"], "first delivery")
        self.assertEqual(replayed["wake"]["generation"], generation)

    def test_requeue_delivered_accepted_wake_is_atomic_and_bounded(self) -> None:
        self.store.register(
            child_dispatch_id="room-child:recoverable",
            room_id="room-a",
            root_id="room-root:a",
            parent_dispatch_id="room-dispatch:parent",
            tool_call_id="tool:recoverable",
            source_participant_id="room-a:p1",
            source_session_id="session:lead",
            target_participant_id="room-a:p2",
            target_session_id="session:partner",
            work_item_id="room-work:recoverable",
        )
        self.store.mark_dispatched("room-child:recoverable")
        submitted = self.store.settle(
            "room-child:recoverable",
            status="review",
            result="delivery",
            completion_source="room_post",
        )
        generation = int(submitted["wake"]["generation"])
        self.store.mark_wake(
            "room-child:recoverable",
            generation=generation,
            state="delivered",
            schedule_id=f"room-wake:room-child:recoverable:{generation}",
        )
        self.store.record_review("room-child:recoverable", accepted=True)

        requeued = self.store.requeue_delivered_wake(
            "room-child:recoverable",
            generation=generation,
            expected_schedule_id=f"room-wake:room-child:recoverable:{generation}",
            max_generation=2,
        )
        replay = self.store.requeue_delivered_wake(
            "room-child:recoverable",
            generation=generation,
            expected_schedule_id=f"room-wake:room-child:recoverable:{generation}",
            max_generation=2,
        )

        self.assertEqual(requeued["status"], "accepted")
        self.assertEqual(requeued["rootId"], "room-root:a")
        self.assertEqual(requeued["sourceSessionId"], "session:lead")
        self.assertEqual(requeued["wake"]["generation"], 2)
        self.assertEqual(requeued["wake"]["state"], "pending")
        self.assertEqual(requeued["wake"]["scheduleId"], "")
        self.assertEqual(replay["wake"]["generation"], 2)
        self.assertEqual(replay["wake"]["state"], "pending")

    def test_requeue_delivered_review_wake_preserves_review_status(self) -> None:
        self.store.register(
            child_dispatch_id="room-child:review-recovery",
            room_id="room-a",
            root_id="room-root:a",
            parent_dispatch_id="room-dispatch:parent",
            tool_call_id="tool:review-recovery",
            source_participant_id="room-a:p1",
            source_session_id="session:lead",
            target_participant_id="room-a:p2",
            target_session_id="session:partner",
            work_item_id="room-work:review-recovery",
        )
        self.store.mark_dispatched("room-child:review-recovery")
        submitted = self.store.settle(
            "room-child:review-recovery",
            status="review",
            result="delivery",
            completion_source="room_post",
        )
        generation = int(submitted["wake"]["generation"])
        self.store.mark_wake(
            "room-child:review-recovery",
            generation=generation,
            state="scheduled",
            schedule_id=f"room-wake:room-child:review-recovery:{generation}",
        )

        stale = self.store.requeue_delivered_wake(
            "room-child:review-recovery",
            generation=generation,
            expected_schedule_id="room-wake:stale:1",
            max_generation=2,
        )

        requeued = self.store.requeue_delivered_wake(
            "room-child:review-recovery",
            generation=generation,
            expected_schedule_id=f"room-wake:room-child:review-recovery:{generation}",
            max_generation=2,
        )

        self.assertEqual(stale["wake"]["generation"], 1)
        self.assertEqual(stale["wake"]["state"], "scheduled")
        self.assertEqual(requeued["status"], "review")
        self.assertEqual(requeued["wake"]["generation"], 2)
        self.assertEqual(requeued["wake"]["state"], "pending")

    def test_terminal_result_candidate_can_settle_exact_missing_result_failure(
        self,
    ) -> None:
        child_dispatch_id = "room-child:terminal-projection"
        self.store.register(
            child_dispatch_id=child_dispatch_id,
            room_id="room-a",
            root_id="room-root:a",
            parent_dispatch_id="room-dispatch:parent",
            tool_call_id="tool:terminal-projection",
            source_participant_id="room-a:p1",
            source_session_id="session:lead",
            target_participant_id="room-a:p2",
            target_session_id="session:partner",
            work_item_id="room-work:terminal-projection",
        )
        self.store.mark_dispatched(child_dispatch_id)
        submitted = self.store.settle(
            child_dispatch_id,
            status="review",
            result="delivery",
            completion_source="room_post",
        )
        generation = int(submitted["wake"]["generation"])
        schedule_id = f"room-wake:{child_dispatch_id}:{generation}"
        self.store.mark_wake(
            child_dispatch_id,
            generation=generation,
            state="delivered",
            schedule_id=schedule_id,
        )
        self.store.record_review(child_dispatch_id, accepted=True)
        missing_result_error = (
            "Facilitator turn completed without room_partner post(kind=result)"
        )
        self.store.mark_wake(
            child_dispatch_id,
            generation=generation,
            state="failed",
            schedule_id=schedule_id,
            error=missing_result_error,
        )

        candidates = self.store.terminal_result_candidates()
        settled = self.store.settle_terminal_projection(
            child_dispatch_id,
            generation=generation,
            expected_schedule_id=schedule_id,
            expected_error=missing_result_error,
        )
        replay = self.store.settle_terminal_projection(
            child_dispatch_id,
            generation=generation,
            expected_schedule_id=schedule_id,
            expected_error=missing_result_error,
        )

        self.assertEqual(
            [item["childDispatchId"] for item in candidates],
            [child_dispatch_id],
        )
        self.assertEqual(settled["status"], "accepted")
        self.assertEqual(settled["wake"]["state"], "delivered")
        self.assertEqual(settled["error"], "")
        self.assertEqual(replay, settled)


if __name__ == "__main__":
    unittest.main()
