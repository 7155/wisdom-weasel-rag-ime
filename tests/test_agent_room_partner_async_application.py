from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_room_partner_application import RoomPartnerApplicationService
from rag_ime.agent_room_partner_dispatch_store import (
    AgentRoomPartnerDispatchStore,
)
from rag_ime.agent_wake_scheduler import AgentWakeScheduleStore
from tests.test_agent_room_partner_application import _RoomEvents, _RoomWorkLedger


class RoomPartnerAsyncApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temporary.name) / "agent.db"
        self.dispatches = AgentRoomPartnerDispatchStore(self.db_path)
        self.dispatches.initialize()
        self.wakes = AgentWakeScheduleStore(self.db_path)
        self.wakes.initialize()
        self.source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "session:lead",
            "displayName": "Facilitator",
            "status": "active",
        }
        self.target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "session:partner",
            "displayName": "Partner",
            "status": "active",
        }
        self.room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [self.source, self.target],
        }
        self.work = _RoomWorkLedger()
        self.phases: list[str] = []
        self.scheduler_notifications = 0
        self.review_payloads: list[tuple[str, dict[str, object]]] = []
        self.facilitator_wakes: list[tuple[dict[str, object], dict[str, object]]] = []
        self.service = self._service()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _service(self) -> RoomPartnerApplicationService:
        participants = {
            str(self.source["id"]): self.source,
            str(self.target["id"]): self.target,
        }

        def notify() -> None:
            self.scheduler_notifications += 1

        def accept(_session_id: str, payload: object) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.review_payloads.append(("accept", dict(payload)))
            item = self.work.items[str(payload["workId"])]
            item["state"] = "done"
            return {"work": dict(item)}

        def return_for_revision(
            _session_id: str,
            payload: object,
        ) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.review_payloads.append(("return", dict(payload)))
            item = self.work.items[str(payload["workId"])]
            item["state"] = "active"
            return {"work": dict(item)}

        def dispatch_facilitator_wake(
            claim: object,
            dispatch: object,
        ) -> bool:
            assert isinstance(claim, dict)
            assert isinstance(dispatch, dict)
            self.facilitator_wakes.append((dict(claim), dict(dispatch)))
            return True

        return RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda session_id, **_kwargs: (
                    self.source
                    if session_id == self.source["sessionId"]
                    else self.target
                ),
                participant=lambda participant_id: participants[participant_id],
                get=lambda _room_id: self.room,
                list_events=lambda *_args, **_kwargs: [],
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=_RoomEvents(),
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=self.work,
            publish_room_work_activity=lambda _work, **kwargs: self.phases.append(
                str(kwargs["phase"])
            ),
            work_document_for_authority=lambda _kind, _identifier: {
                "documentId": "workdoc:one",
                "documentRevision": 2,
            },
            dispatch_store=self.dispatches,
            wake_schedules=self.wakes,
            notify_wake_scheduler=notify,
            dispatch_facilitator_wake=dispatch_facilitator_wake,
            accept_room_work=accept,
            return_room_work=return_for_revision,
        )

    def _register(self, child_dispatch_id: str = "room-child:one") -> dict[str, object]:
        work = self.service._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id=f"tool:{child_dispatch_id}",
            source=self.source,
            target=self.target,
            task="实现并验证 Room 变更",
            expected_output="可验收交付",
            acceptance_criteria=["提供运行证据"],
        )
        self.dispatches.register(
            child_dispatch_id=child_dispatch_id,
            room_id="room-a",
            root_id="root-a",
            parent_dispatch_id="dispatch-a",
            tool_call_id=f"tool:{child_dispatch_id}",
            source_participant_id=str(self.source["id"]),
            source_session_id=str(self.source["sessionId"]),
            target_participant_id=str(self.target["id"]),
            target_session_id=str(self.target["sessionId"]),
            work_item_id=str(work["id"]),
        )
        self.dispatches.mark_dispatched(child_dispatch_id)
        return work

    def test_work_result_submits_then_schedules_durable_facilitator_wake(self) -> None:
        work = self._register()

        self.service.observe_room_event(
            {
                "roomId": "room-a",
                "turnId": "root-a",
                "eventType": "room_post",
                "payload": {
                    "post": {
                        "postId": "room-post:one",
                        "rootId": "root-a",
                        "dispatchId": "room-child:one",
                        "authorActorRef": self.target["id"],
                        "kind": "work_result",
                        "content": "实现和回归证据已交付",
                        "workResult": {
                            "proposedOperabilityVerdict": "failed",
                            "proposedRequirementVerdict": "unverified",
                        },
                    }
                },
            }
        )

        record = self.dispatches.get("room-child:one")
        self.assertEqual(record["status"], "review")
        submitted_item = self.work.items[str(work["id"])]
        self.assertEqual(submitted_item["state"], "review")
        self.assertEqual(
            submitted_item["proposedOperabilityVerdict"],
            "failed",
        )
        self.assertEqual(
            submitted_item["proposedRequirementVerdict"],
            "unverified",
        )
        self.assertEqual(self.phases, ["assigned", "submitted"])
        self.assertEqual(record["wake"]["state"], "scheduled")
        wake = self.wakes.get(str(record["wake"]["scheduleId"]))
        self.assertEqual(wake["metadata"]["childDispatchId"], "room-child:one")
        self.assertEqual(wake["targetSessionId"], self.source["sessionId"])
        self.assertEqual(self.scheduler_notifications, 1)

        collected = self.service.execute(
            str(self.source["sessionId"]),
            {"op": "collect", "childDispatchId": "room-child:one"},
            tool_call_id="tool:collect",
        )
        self.assertEqual(collected["status"], "review")
        self.assertEqual(collected["workItem"]["state"], "review")

    def test_accept_maps_public_work_item_id_and_records_explicit_review(self) -> None:
        work = self._register()
        self.dispatches.settle(
            "room-child:one",
            status="review",
            result="已交付",
            completion_source="room_post",
        )

        receipt = self.service.execute(
            str(self.source["sessionId"]),
            {
                "op": "accept",
                "workItemId": work["id"],
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "satisfied",
                "evidenceRefs": ["test:green", "workdoc:one@2"],
                "reason": "真实路径与需求验收均通过。",
            },
            tool_call_id="tool:accept",
        )

        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(
            self.review_payloads,
            [
                (
                    "accept",
                    {
                        "workId": work["id"],
                        "expectedRevision": 0,
                        "operabilityVerdict": "passed",
                        "requirementVerdict": "satisfied",
                        "evidenceRefs": ["test:green", "workdoc:one@2"],
                        "reason": "真实路径与需求验收均通过。",
                    },
                )
            ],
        )
        self.assertEqual(self.dispatches.get("room-child:one")["status"], "accepted")

    def test_replay_cannot_rebind_same_tool_call_to_changed_task(self) -> None:
        self._register()

        with self.assertRaisesRegex(ValueError, "idempotency key"):
            self.service.execute(
                str(self.source["sessionId"]),
                {
                    "op": "delegate",
                    "targetParticipantId": self.target["id"],
                    "task": "篡改后的另一个任务",
                    "expectedOutput": "不同产物",
                    "acceptanceCriteria": ["不同验收条件"],
                },
                tool_call_id="tool:room-child:one",
            )

    def test_cancelled_root_rejects_an_already_claimed_stale_wake(self) -> None:
        self._register()
        settled = self.dispatches.settle(
            "room-child:one",
            status="review",
            result="已交付",
            completion_source="room_post",
        )
        self.service._schedule_completion_wake(settled)
        claim = self.wakes.claim_due(now_ms=10**15)[0]

        self.service.cancel_root(
            room_id="room-a",
            root_id="root-a",
            reason="用户已停止 Root",
        )
        self.service.dispatch_wake(claim)

        self.assertEqual(self.facilitator_wakes, [])
        record = self.dispatches.get("room-child:one")
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(record["wake"]["state"], "cancelled")
        self.assertEqual(self.wakes.get(str(claim["id"]))["status"], "cancelled")

    def test_explicit_review_cancels_a_wake_that_has_not_fired(self) -> None:
        work = self._register()
        settled = self.dispatches.settle(
            "room-child:one",
            status="review",
            result="已交付",
            completion_source="room_post",
        )
        self.service._schedule_completion_wake(settled)
        schedule_id = str(
            self.dispatches.get("room-child:one")["wake"]["scheduleId"]
        )

        self.service.execute(
            str(self.source["sessionId"]),
            {
                "op": "accept",
                "workItemId": work["id"],
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "satisfied",
                "evidenceRefs": ["test:green"],
                "reason": "真实路径与需求验收均通过。",
            },
            tool_call_id="tool:accept-before-wake",
        )

        record = self.dispatches.get("room-child:one")
        self.assertEqual(record["status"], "accepted")
        self.assertEqual(record["wake"]["state"], "cancelled")
        self.assertEqual(self.wakes.get(schedule_id)["status"], "cancelled")

    def test_root_cancellation_fences_dispatch_and_pending_wake(self) -> None:
        self._register()
        settled = self.dispatches.settle(
            "room-child:one",
            status="review",
            result="已交付",
            completion_source="room_post",
        )
        self.service._schedule_completion_wake(settled)
        schedule_id = str(
            self.dispatches.get("room-child:one")["wake"]["scheduleId"]
        )

        self.service.cancel_root(
            room_id="room-a",
            root_id="root-a",
            reason="用户停止 Room root",
        )

        self.assertEqual(self.dispatches.get("room-child:one")["status"], "cancelled")
        self.assertEqual(self.wakes.get(schedule_id)["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
