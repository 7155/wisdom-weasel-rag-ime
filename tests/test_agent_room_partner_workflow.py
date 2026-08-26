from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_room_partner_application import RoomPartnerApplicationService
from rag_ime.agent_room_partner_dispatch_store import AgentRoomPartnerDispatchStore
from rag_ime.agent_tools import _runtime_tool_parameter_schema
from rag_ime.agent_wake_scheduler import AgentWakeScheduleStore
from rag_ime.contracts.json_schema import ContractValidationError, validate_contract
from tests.test_agent_room_partner_application import _RoomEvents, _RoomWorkLedger


class RoomPartnerWorkflowAsyncContractTest(unittest.TestCase):
    """Focused coverage for the current durable async Partner contract."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        db_path = Path(self._temporary.name) / "agent.db"
        self.dispatches = AgentRoomPartnerDispatchStore(db_path)
        self.dispatches.initialize()
        self.wakes = AgentWakeScheduleStore(db_path)
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
        self.events = _RoomEvents()
        self.work = _RoomWorkLedger()
        self.phases: list[str] = []
        self.scheduler_notifications = 0
        self.review_payloads: list[tuple[str, dict[str, object]]] = []
        self.service = self._service()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _service(self) -> RoomPartnerApplicationService:
        participants = {
            str(self.source["id"]): self.source,
            str(self.target["id"]): self.target,
        }

        def accept(_session_id: str, payload: object) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.review_payloads.append(("accept", dict(payload)))
            item = self.work.items[str(payload["workId"])]
            item["state"] = "done"
            item["review"] = {
                "operabilityVerdict": payload["operabilityVerdict"],
                "requirementVerdict": payload["requirementVerdict"],
                "evidenceRefs": list(payload["evidenceRefs"]),
                "reason": payload["reason"],
                "reviewerParticipantId": self.source["id"],
                "reviewedAtMs": 1,
            }
            return {"work": dict(item)}

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
            room_events=self.events,
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
            notify_wake_scheduler=lambda: setattr(
                self, "scheduler_notifications", self.scheduler_notifications + 1
            ),
            dispatch_facilitator_wake=lambda *_args, **_kwargs: True,
            accept_room_work=accept,
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

    def test_delegate_work_is_active_and_idempotent_before_completion(self) -> None:
        work = self._register()
        duplicate = self.service._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id="tool:room-child:one",
            source=self.source,
            target=self.target,
            task="实现并验证 Room 变更",
            expected_output="可验收交付",
            acceptance_criteria=["提供运行证据"],
        )

        self.assertEqual(work["state"], "active")
        self.assertEqual(duplicate["id"], work["id"])
        self.assertEqual(len(self.work.items), 1)
        record = self.dispatches.get("room-child:one")
        self.assertEqual(record["status"], "dispatched")
        self.assertEqual(record["workItemId"], work["id"])
        self.assertEqual(self.phases, ["assigned"])

    def test_result_event_settles_dispatch_and_schedules_facilitator_wake(self) -> None:
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
        self.assertEqual(self.work.items[str(work["id"])]["state"], "review")
        self.assertEqual(
            self.work.items[str(work["id"])]["proposedOperabilityVerdict"],
            "failed",
        )
        self.assertEqual(record["wake"]["state"], "scheduled")
        wake = self.wakes.get(str(record["wake"]["scheduleId"]))
        self.assertEqual(wake["targetSessionId"], self.source["sessionId"])
        self.assertEqual(self.scheduler_notifications, 1)

        collected = self.service.execute(
            str(self.source["sessionId"]),
            {"op": "collect", "childDispatchId": "room-child:one"},
            tool_call_id="tool:collect",
        )
        self.assertEqual(collected["status"], "review")
        self.assertEqual(collected["workItem"]["state"], "review")

    def test_accept_records_independent_operability_and_requirement_verdicts(self) -> None:
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
        self.assertEqual(self.dispatches.get("room-child:one")["status"], "accepted")
        self.assertEqual(self.work.items[str(work["id"])]["state"], "done")
        self.assertEqual(
            self.review_payloads[0][1]["operabilityVerdict"],
            "passed",
        )
        self.assertEqual(
            self.review_payloads[0][1]["requirementVerdict"],
            "satisfied",
        )


class RoomPartnerSchemaTest(unittest.TestCase):
    def test_schema_allows_shared_fields_on_batch_and_rejects_unknown_fields(self) -> None:
        schema = _runtime_tool_parameter_schema(
            "room_partner",
            [
                "list",
                "delegate",
                "delegate_batch",
                "retry",
                "accept",
                "return",
                "collect",
                "wait",
                "post",
            ],
        )
        validate_contract(
            {
                "op": "delegate_batch",
                "phase": "并行实现",
                "targetParticipantId": "shared-context-is-allowed",
                "task": "共享上下文",
                "tasks": [
                    {
                        "targetParticipantId": "room-a:p2",
                        "task": "轨道一",
                        "expectedOutput": "结果一",
                        "acceptanceCriteria": ["标准一"],
                    },
                    {
                        "targetParticipantId": "room-a:p3",
                        "task": "轨道二",
                        "expectedOutput": "结果二",
                        "acceptanceCriteria": ["标准二"],
                    },
                ],
            },
            schema,
        )
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "op": "delegate_batch",
                    "phase": "并行实现",
                    "tasks": [],
                    "unknown": True,
                },
                schema,
            )

    def test_schema_requires_a_complete_delivery_contract(self) -> None:
        schema = _runtime_tool_parameter_schema("room_partner", ["delegate"])
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "op": "delegate",
                    "phase": "实现",
                    "targetParticipantId": "room-a:p2",
                    "task": "只有任务，没有交付合同",
                },
                schema,
            )
        validate_contract(
            {
                "op": "delegate",
                "phase": "实现",
                "targetParticipantId": "room-a:p2",
                "task": "核对调度链",
                "expectedOutput": "调用链与证据",
                "acceptanceCriteria": ["给出真实 dispatch 证据"],
            },
            schema,
        )


if __name__ == "__main__":
    unittest.main()
