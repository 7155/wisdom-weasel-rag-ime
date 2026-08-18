from __future__ import annotations

import threading
import unittest
from collections.abc import Mapping
from types import SimpleNamespace

from rag_ime.agent_room_partner_workflow import RoomPartnerApplicationService
from rag_ime.agent_tools import _runtime_tool_parameter_schema
from rag_ime.contracts.json_schema import (
    ContractValidationError,
    validate_contract,
)


class _RoomEvents:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    def publish(self, **values: object) -> dict[str, object]:
        snapshot = dict(values)
        self.published.append(snapshot)
        return snapshot


class _RoomWork:
    def __init__(
        self,
        *,
        source: Mapping[str, object],
        targets: list[Mapping[str, object]],
    ) -> None:
        self._source = dict(source)
        self._targets = {
            str(target["id"]): dict(target)
            for target in targets
        }
        self._items: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()
        self.assign_count = 0

    def assign(
        self,
        source_session_id: str,
        payload: Mapping[str, object],
        *,
        root_turn_id: str = "",
        topic_id: str = "",
    ) -> tuple[dict[str, object], bool]:
        self.assert_source(source_session_id)
        client_message_id = str(payload["clientMessageId"])
        with self._lock:
            for existing in self._items.values():
                if existing["clientMessageId"] == client_message_id:
                    return dict(existing), False
            self.assign_count += 1
            target_id = str(payload["targetParticipantId"])
            work_id = f"room-work:{self.assign_count}"
            work = {
                "id": work_id,
                "roomId": str(self._source["roomId"]),
                "topicId": topic_id,
                "rootTurnId": root_turn_id,
                "rootWorkId": work_id,
                "parentWorkId": str(payload.get("parentWorkId") or ""),
                "objective": str(payload["objective"]),
                "expectedOutput": str(payload["expectedOutput"]),
                "acceptanceCriteria": list(payload["acceptanceCriteria"]),
                "accountableParticipantId": str(self._source["id"]),
                "currentOwnerParticipantId": str(self._source["id"]),
                "offeredToParticipantId": target_id,
                "createdByParticipantId": str(self._source["id"]),
                "clientMessageId": client_message_id,
                "assignmentKey": f"assignment:{work_id}",
                "state": "queued",
                "depth": 1,
                "revision": 0,
                "resultSummary": "",
                "artifactRefs": [],
                "evidenceRefs": [],
                "blocker": {},
                "acceptedTurnId": "",
            }
            self._items[work_id] = work
            return dict(work), True

    def get(self, work_id: str, *, room_id: str = "") -> dict[str, object]:
        with self._lock:
            work = dict(self._items[work_id])
        if room_id and work["roomId"] != room_id:
            raise ValueError("work item does not belong to this room")
        return work

    def list(
        self,
        *,
        room_id: str,
        states: tuple[str, ...] = (),
        owner_participant_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        with self._lock:
            values = [
                dict(work)
                for work in self._items.values()
                if work["roomId"] == room_id
            ]
        if states:
            values = [item for item in values if item["state"] in states]
        if owner_participant_id:
            values = [
                item
                for item in values
                if item["currentOwnerParticipantId"] == owner_participant_id
            ]
        return values[:limit]

    def accept_assignment(
        self,
        work_id: str,
        *,
        target_participant_id: str,
        accepted_turn_id: str,
    ) -> dict[str, object]:
        with self._lock:
            work = self._items[work_id]
            if work["state"] == "active":
                return dict(work)
            if work["state"] != "queued":
                raise ValueError("Room assignment is no longer queued")
            if work["offeredToParticipantId"] != target_participant_id:
                raise ValueError("only the offered participant may accept")
            work.update(
                {
                    "state": "active",
                    "currentOwnerParticipantId": target_participant_id,
                    "offeredToParticipantId": "",
                    "acceptedTurnId": accepted_turn_id,
                }
            )
            return dict(work)

    def claim_dispatch(
        self,
        work_id: str,
        *,
        room_id: str,
        owner_participant_id: str,
        assignment_key: str,
        previous_accepted_turn_id: str,
        room_turn_id: str,
    ) -> dict[str, object]:
        with self._lock:
            work = self._items[work_id]
            if work["roomId"] != room_id:
                raise ValueError("work item does not belong to this room")
            if work["state"] != "active":
                raise ValueError("only active work may be dispatched")
            if (
                work["currentOwnerParticipantId"] != owner_participant_id
                or work["assignmentKey"] != assignment_key
                or work["acceptedTurnId"] != previous_accepted_turn_id
            ):
                raise ValueError("WorkItem assignment changed before dispatch")
            work["acceptedTurnId"] = room_turn_id
            return dict(work)

    def fail_assignment(
        self,
        work_id: str,
        *,
        actor_participant_id: str,
        reason: str,
    ) -> dict[str, object]:
        del actor_participant_id
        with self._lock:
            work = self._items[work_id]
            work.update(
                {
                    "state": "failed",
                    "blocker": {"phase": "assignment", "reason": reason},
                }
            )
            return dict(work)

    def fail_dispatch(
        self,
        work_id: str,
        *,
        room_id: str,
        actor_participant_id: str,
        room_turn_id: str,
        previous_accepted_turn_id: str,
        reason: str,
    ) -> dict[str, object]:
        del room_id, actor_participant_id, room_turn_id
        with self._lock:
            work = self._items[work_id]
            work["acceptedTurnId"] = previous_accepted_turn_id
            work["blocker"] = {"phase": "dispatch", "reason": reason}
            return dict(work)

    def submit(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        target_id = self.target_for_session(session_id)
        with self._lock:
            work = self._items[str(payload["workId"])]
            if work["currentOwnerParticipantId"] != target_id:
                raise ValueError("only the current owner may submit")
            if work["state"] not in {"active", "blocked"}:
                raise ValueError("only active or blocked work may be submitted")
            work.update(
                {
                    "state": "review",
                    "resultSummary": str(payload["resultSummary"]),
                    "artifactRefs": list(payload.get("artifactRefs") or []),
                    "evidenceRefs": list(payload.get("evidenceRefs") or []),
                    "blocker": {},
                }
            )
            return dict(work)

    def accept(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.assert_source(session_id)
        with self._lock:
            work = self._items[str(payload["workId"])]
            if work["state"] != "review":
                raise ValueError("Room work must be in review")
            work["state"] = "done"
            return dict(work)

    def return_for_revision(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        self.assert_source(session_id)
        with self._lock:
            work = self._items[str(payload["workId"])]
            target_id = self.target_id_for_work(work)
            if work["state"] != "review":
                raise ValueError("Room work must be in review")
            work.update(
                {
                    "state": "active",
                    "currentOwnerParticipantId": target_id,
                    "revision": int(work["revision"]) + 1,
                    "blocker": {"reviewFeedback": str(payload["reason"])},
                }
            )
            return dict(work)

    def reviewer_participant_id(self, work_id: str) -> str:
        del work_id
        return str(self._source["id"])

    def escalate(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        target_id = self.target_for_session(session_id)
        with self._lock:
            work = self._items[str(payload["workId"])]
            if work["currentOwnerParticipantId"] != target_id:
                raise ValueError("only the current owner may escalate")
            work.update(
                {
                    "state": "failed",
                    "blocker": {
                        "reason": str(payload["reason"]),
                        "nextStep": str(payload["nextStep"]),
                    },
                }
            )
            return dict(work)

    def seed_dependency(self, *, state: str) -> str:
        with self._lock:
            work_id = f"room-work:dependency:{len(self._items) + 1}"
            self._items[work_id] = {
                "id": work_id,
                "roomId": str(self._source["roomId"]),
                "topicId": "topic-a",
                "rootTurnId": "root-a",
                "rootWorkId": work_id,
                "parentWorkId": "",
                "objective": "依赖任务",
                "expectedOutput": "已验收证据",
                "acceptanceCriteria": ["已通过验收"],
                "accountableParticipantId": str(self._source["id"]),
                "currentOwnerParticipantId": str(self._source["id"]),
                "offeredToParticipantId": "",
                "createdByParticipantId": str(self._source["id"]),
                "clientMessageId": f"dependency:{work_id}",
                "assignmentKey": f"assignment:{work_id}",
                "state": state,
                "depth": 1,
                "revision": 0,
                "resultSummary": "",
                "artifactRefs": [],
                "evidenceRefs": [],
                "blocker": {},
                "acceptedTurnId": "",
            }
            return work_id

    def assert_source(self, session_id: str) -> None:
        if session_id != self._source["sessionId"]:
            raise ValueError("only the accountable reviewer may change the work")

    def target_for_session(self, session_id: str) -> str:
        for participant_id, target in self._targets.items():
            if target["sessionId"] == session_id:
                return participant_id
        raise ValueError("unknown Partner Session")

    def target_id_for_work(self, work: Mapping[str, object]) -> str:
        accepted_turn_id = str(work.get("acceptedTurnId") or "")
        for participant_id, target in self._targets.items():
            if participant_id in accepted_turn_id or len(self._targets) == 1:
                return participant_id
        return next(iter(self._targets))


class RoomPartnerWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·远",
            "collaborationRole": "coordinator",
            "status": "active",
        }
        self.target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·今",
            "collaborationRole": "implementer",
            "status": "active",
        }
        self.room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "moderatorParticipantId": self.source["id"],
            "participants": [self.source, self.target],
        }
        self.events = _RoomEvents()
        self.room_work = _RoomWork(source=self.source, targets=[self.target])
        self.dispatched_work: list[Mapping[str, object] | None] = []
        self.work_activity: list[tuple[str, str]] = []

        def dispatch_target(**kwargs: object) -> dict[str, object]:
            work_item = kwargs.get("work_item")
            self.dispatched_work.append(
                dict(work_item) if isinstance(work_item, Mapping) else None
            )
            decision = kwargs["decision"]
            assert isinstance(decision, Mapping)
            return {
                "accepted": True,
                "sessionTurnId": "pi-turn:partner",
                "dispatchId": str(decision["dispatchId"]),
            }

        participants = {
            str(self.source["id"]): self.source,
            str(self.target["id"]): self.target,
        }
        sessions = {
            str(self.source["sessionId"]): self.source,
            str(self.target["sessionId"]): self.target,
        }
        self.service = RoomPartnerApplicationService(
            room_work=self.room_work,
            publish_room_work_activity=lambda work, *, phase, actor: (
                self.work_activity.append((str(work["id"]), str(phase)))
            ),
            rooms=SimpleNamespace(
                participant_for_session=lambda session_id, **_kwargs: sessions[session_id],
                get=lambda _room_id: self.room,
                participant=lambda participant_id: participants[participant_id],
                plan_routes=lambda *_args, **kwargs: [{
                    "reason": "explicit_invite",
                    "targetDisplayName": participants[
                        kwargs["requested_participant_ids"][0]
                    ]["displayName"],
                    "targetParticipantId": kwargs["requested_participant_ids"][0],
                }],
                unread_public_messages=lambda *_args, **_kwargs: {
                    "items": [],
                    "omittedCount": 0,
                    "throughSequence": 0,
                },
                list_events=lambda *_args, **_kwargs: [],
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-root"),
                turn_targets=lambda *_args, **_kwargs: [],
                hold_priority_if_idle=lambda *_args, **_kwargs: None,
                release_priority_session=lambda *_args, **_kwargs: None,
                is_cancelled=lambda *_args, **_kwargs: False,
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=self.events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(dispatch_target=dispatch_target),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
        )
        self.service._wait_for_child = lambda **kwargs: {  # type: ignore[method-assign]
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "delegate",
            "roomId": "room-a",
            "rootId": "root-a",
            "childDispatchId": kwargs["child_dispatch_id"],
            "participantId": self.target["id"],
            "status": "completed",
            "result": "已核对调用链并返回证据。",
        }

    def delegate(self) -> dict[str, object]:
        return self.service.execute(
            str(self.source["sessionId"]),
            {
                "op": "delegate",
                "phase": "实现",
                "targetParticipantId": self.target["id"],
                "task": "核对 Room 调度链",
                "expectedOutput": "调用链与证据",
                "acceptanceCriteria": ["给出真实 dispatch 证据"],
            },
            tool_call_id="tool:delegate",
        )

    def test_delegate_binds_real_session_to_work_item_and_stops_at_review(self) -> None:
        result = self.delegate()

        work_id = str(result["workItemId"])
        work = self.room_work.get(work_id, room_id="room-a")
        self.assertEqual(work["state"], "review")
        self.assertEqual(result["contractStatus"], "pending_review")
        self.assertIs(result["requiresAcceptance"], True)
        self.assertEqual(self.room_work.assign_count, 1)
        self.assertEqual(self.dispatched_work[0]["id"], work_id)  # type: ignore[index]
        authority_events = [
            item
            for item in self.events.published
            if item["event_type"] in {"route_decision", "participant_activity"}
        ]
        self.assertTrue(authority_events)
        self.assertTrue(all(
            item["payload"].get("workItemId") == work_id  # type: ignore[union-attr]
            for item in authority_events
        ))
        self.assertIn((work_id, "assigned"), self.work_activity)
        self.assertIn((work_id, "accepted"), self.work_activity)
        self.assertIn((work_id, "submitted"), self.work_activity)

    def test_root_final_is_blocked_until_explicit_acceptance(self) -> None:
        delegated = self.delegate()
        work_id = str(delegated["workItemId"])

        with self.assertRaisesRegex(ValueError, "blocked until all formal WorkItems"):
            self.service.execute(
                str(self.source["sessionId"]),
                {"op": "post", "kind": "result", "content": "尚未验收的最终答复"},
                tool_call_id="tool:premature-final",
            )

        accepted = self.service.execute(
            str(self.source["sessionId"]),
            {"op": "accept", "workItemId": work_id},
            tool_call_id="tool:accept",
        )
        self.assertEqual(accepted["contractStatus"], "accepted")
        self.assertEqual(self.room_work.get(work_id)["state"], "done")

        final = self.service.execute(
            str(self.source["sessionId"]),
            {"op": "post", "kind": "result", "content": "已验收后的唯一最终答复"},
            tool_call_id="tool:final",
        )
        self.assertIs(final["published"], True)

    def test_return_and_resume_reuse_the_same_work_item(self) -> None:
        delegated = self.delegate()
        work_id = str(delegated["workItemId"])

        returned = self.service.execute(
            str(self.source["sessionId"]),
            {
                "op": "return",
                "workItemId": work_id,
                "reason": "缺少恢复路径证据",
            },
            tool_call_id="tool:return",
        )
        self.assertEqual(returned["contractStatus"], "revision_required")
        self.assertEqual(self.room_work.get(work_id)["state"], "active")

        resumed = self.service.execute(
            str(self.source["sessionId"]),
            {
                "op": "resume",
                "workItemId": work_id,
                "phase": "返修",
            },
            tool_call_id="tool:resume",
        )
        self.assertEqual(resumed["workItemId"], work_id)
        self.assertEqual(resumed["contractStatus"], "pending_review")
        self.assertEqual(self.room_work.assign_count, 1)
        self.assertEqual(self.room_work.get(work_id)["revision"], 1)

    def test_unaccepted_dependency_blocks_next_phase(self) -> None:
        dependency_id = self.room_work.seed_dependency(state="review")

        with self.assertRaisesRegex(ValueError, "dependencies are not accepted"):
            self.service.execute(
                str(self.source["sessionId"]),
                {
                    "op": "delegate",
                    "phase": "集成",
                    "targetParticipantId": self.target["id"],
                    "task": "集成上一阶段结果",
                    "expectedOutput": "集成结果",
                    "acceptanceCriteria": ["依赖已经通过验收"],
                    "dependsOnWorkItemIds": [dependency_id],
                },
                tool_call_id="tool:dependent",
            )
        self.assertEqual(self.room_work.assign_count, 0)


class RoomPartnerSchemaTest(unittest.TestCase):
    def test_schema_rejects_single_and_batch_fields_in_one_call(self) -> None:
        schema = _runtime_tool_parameter_schema("room_partner")
        with self.assertRaises(ContractValidationError):
            validate_contract(
                {
                    "op": "delegate_batch",
                    "phase": "并行实现",
                    "targetParticipantId": "room-a:p2",
                    "task": "非法单任务字段",
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

    def test_schema_requires_a_complete_delivery_contract(self) -> None:
        schema = _runtime_tool_parameter_schema("room_partner")
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
