from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.agent_room_partner_application import RoomPartnerApplicationService
from rag_ime.agent_room_partner_dispatch_store import (
    AgentRoomPartnerDispatchStore,
)
from rag_ime.agent_wake_scheduler import AgentWakeScheduleStore
from tests.test_agent_room_partner_application import _RoomEvents, _RoomWorkLedger


class _RevisionWorkLedger(_RoomWorkLedger):
    def create(self, **values: object) -> dict[str, object]:
        created = super().create(**values)
        with self._lock:
            item = self.items[str(created["id"])]
            item.setdefault("revision", 0)
            return dict(item)

    def get(self, work_id: str, **values: object) -> dict[str, object]:
        item = super().get(work_id, **values)
        room_id = str(values.get("room_id") or "")
        if room_id and str(item["roomId"]) != room_id:
            raise ValueError("WorkItem does not belong to the current Room")
        return item

    def retry(
        self,
        work_id: str,
        *,
        actor_participant_id: str,
        current_owner_participant_id: str,
        expected_revision: int,
        reason: str,
    ) -> dict[str, object]:
        del reason
        with self._lock:
            item = self.items[work_id]
            if item["state"] not in {"blocked", "failed"}:
                raise ValueError("only blocked or failed work may be retried")
            if item["accountableParticipantId"] != actor_participant_id:
                raise ValueError("only the accountable participant may retry work")
            if int(item.get("revision") or 0) != expected_revision:
                raise ValueError("Room work revision changed; refresh before retry")
            item["state"] = "active"
            item["revision"] = expected_revision + 1
            item["currentOwnerParticipantId"] = current_owner_participant_id
            item["assignmentKey"] = f"assignment:{work_id}:retry:{item['revision']}"
            item["acceptedTurnId"] = ""
            item["resultSummary"] = ""
            item["evidenceRefs"] = []
            return dict(item)


class AgentRoomPartnerRevisionLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-partner-revision-"
        )
        self.db_path = Path(self._temporary.name) / "agent.sqlite"
        self.dispatches = AgentRoomPartnerDispatchStore(self.db_path)
        self.dispatches.initialize()
        self.wakes = AgentWakeScheduleStore(self.db_path)
        self.wakes.initialize()
        self.source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "session:facilitator",
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
        self.other_facilitator = {
            "id": "room-a:p3",
            "roomId": "room-a",
            "sessionId": "session:other-facilitator",
            "displayName": "Other Facilitator",
            "status": "active",
        }
        self.other_room_facilitator = {
            "id": "room-b:p1",
            "roomId": "room-b",
            "sessionId": "session:other-room-facilitator",
            "displayName": "Other Room Facilitator",
            "status": "active",
        }
        self.other_room_target = {
            "id": "room-b:p2",
            "roomId": "room-b",
            "sessionId": "session:other-room-partner",
            "displayName": "Other Room Partner",
            "status": "active",
        }
        self.room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [
                self.source,
                self.target,
                self.other_facilitator,
            ],
        }
        self.other_room = {
            "id": "room-b",
            "status": "active",
            "activeTopicId": "topic-b",
            "participants": [
                self.other_room_facilitator,
                self.other_room_target,
            ],
        }
        self.active_root_id = "root-a"
        self.work = _RevisionWorkLedger()
        self.room_events = _RoomEvents()
        self.partner_dispatches: list[dict[str, object]] = []
        self.facilitator_turns: list[str] = []
        self.review_payloads: list[tuple[str, dict[str, object]]] = []
        self.session_statuses = {
            str(self.source["sessionId"]): "idle",
            str(self.target["sessionId"]): "idle",
            str(self.other_facilitator["sessionId"]): "idle",
            str(self.other_room_facilitator["sessionId"]): "idle",
            str(self.other_room_target["sessionId"]): "idle",
        }
        self.recovered_sessions: list[str] = []
        participants = {
            str(self.source["id"]): self.source,
            str(self.target["id"]): self.target,
            str(self.other_facilitator["id"]): self.other_facilitator,
            str(self.other_room_facilitator["id"]): self.other_room_facilitator,
            str(self.other_room_target["id"]): self.other_room_target,
        }
        participants_by_session = {
            str(value["sessionId"]): value
            for value in participants.values()
        }
        rooms = {
            "room-a": self.room,
            "room-b": self.other_room,
        }

        def dispatch_target(**kwargs: object) -> dict[str, object]:
            self.partner_dispatches.append(dict(kwargs))
            return {
                "accepted": True,
                "sessionTurnId": f"turn:partner:{len(self.partner_dispatches)}",
            }

        def dispatch_facilitator_wake(
            claim: object,
            _dispatch: object,
        ) -> bool:
            assert isinstance(claim, dict)
            turn_id = f"turn:facilitator:{len(self.facilitator_turns) + 1}"
            self.facilitator_turns.append(turn_id)
            self.wakes.accept(
                str(claim["runId"]),
                session_id=str(self.source["sessionId"]),
                turn_id=turn_id,
            )
            return True

        def return_for_revision(
            _session_id: str,
            payload: object,
        ) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.review_payloads.append(("return", dict(payload)))
            item = self.work.items[str(payload["workId"])]
            item["state"] = "active"
            item["revision"] = int(item.get("revision") or 0) + 1
            item["reviewReason"] = str(payload.get("reason") or "")
            return {"work": dict(item)}

        def accept(
            _session_id: str,
            payload: object,
        ) -> dict[str, object]:
            assert isinstance(payload, dict)
            self.review_payloads.append(("accept", dict(payload)))
            item = self.work.items[str(payload["workId"])]
            item["state"] = "done"
            return {"work": dict(item)}

        def recover_faulted_session(session_id: str) -> None:
            self.recovered_sessions.append(session_id)
            self.session_statuses[session_id] = "idle"

        self.application = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda session_id, **_kwargs: (
                    participants_by_session.get(session_id)
                ),
                participant=lambda participant_id: participants[participant_id],
                get=lambda room_id: rooms[room_id],
                plan_routes=lambda *_args, **_kwargs: [
                    {
                        "reason": "explicit_invite",
                        "targetDisplayName": self.target["displayName"],
                        "targetParticipantId": self.target["id"],
                    }
                ],
                unread_public_messages=lambda *_args, **_kwargs: {
                    "items": [],
                    "omittedCount": 0,
                    "throughSequence": 0,
                },
                list_events=lambda *_args, **_kwargs: [],
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: (
                    self.active_root_id,
                    f"dispatch:{self.active_root_id}",
                ),
                turn_targets=lambda *_args, **_kwargs: [],
                hold_priority_if_idle=lambda *_args, **_kwargs: None,
                release_priority_session=lambda *_args, **_kwargs: None,
                is_cancelled=lambda *_args, **_kwargs: False,
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(
                get=lambda session_id: {
                    "id": session_id,
                    "status": self.session_statuses[session_id],
                },
            ),
            room_events=self.room_events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(dispatch_target=dispatch_target),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=self.work,
            publish_room_work_activity=lambda *_args, **_kwargs: None,
            work_document_for_authority=lambda _kind, _identifier: {
                "documentId": "workdoc:revision-loop",
                "documentRevision": 2,
            },
            dispatch_store=self.dispatches,
            wake_schedules=self.wakes,
            dispatch_facilitator_wake=dispatch_facilitator_wake,
            accept_room_work=accept,
            return_room_work=return_for_revision,
            recover_faulted_session=recover_faulted_session,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _delegate(
        self,
        *,
        tool_call_id: str,
        work_item_id: str = "",
    ) -> dict[str, object]:
        return self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "delegate",
                "targetParticipantId": self.target["id"],
                "task": "修复并验证同一个 Room WorkItem",
                "expectedOutput": "同一 WorkItem 的修订交付",
                "acceptanceCriteria": ["修订后双轴验收通过"],
                **({"workItemId": work_item_id} if work_item_id else {}),
            },
            tool_call_id=tool_call_id,
        )

    def _submit_partner_result(
        self,
        *,
        child_dispatch_id: str,
        post_id: str,
        content: str,
    ) -> None:
        self.application.observe_room_event(
            {
                "roomId": "room-a",
                "turnId": "root-a",
                "eventType": "room_post",
                "payload": {
                    "post": {
                        "postId": post_id,
                        "rootId": "root-a",
                        "dispatchId": child_dispatch_id,
                        "authorActorRef": self.target["id"],
                        "kind": "work_result",
                        "content": content,
                    }
                },
            }
        )

    def _deliver_wake(self) -> dict[str, object]:
        claims = self.wakes.claim_due(now_ms=10**15)
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.application.dispatch_wake(claim)
        return claim

    def _finish_facilitator_wake(self, claim: dict[str, object]) -> None:
        turn_id = self.facilitator_turns[-1]
        self.assertTrue(
            self.wakes.finish_event(
                AgentEventEnvelope(
                    event_id=f"event:{turn_id}",
                    session_id=str(self.source["sessionId"]),
                    turn_id=turn_id,
                    sequence=len(self.facilitator_turns),
                    created_at_ms=10**15 + len(self.facilitator_turns),
                    event_type="turn_completed",
                    payload={},
                    resume_token=str(len(self.facilitator_turns)),
                )
            )
        )
        self.assertEqual(
            self.wakes.get(str(claim["id"]))["status"],
            "completed",
        )

    def _return_work_for_revision(self, *, tool_call_id: str) -> dict[str, object]:
        delegated = self._delegate(tool_call_id=tool_call_id)
        work_item_id = str(delegated["workItemId"])
        self._submit_partner_result(
            child_dispatch_id=str(delegated["childDispatchId"]),
            post_id=f"room-post:{tool_call_id}",
            content="首轮交付需要修订",
        )
        self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "return",
                "workItemId": work_item_id,
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "not_satisfied",
                "evidenceRefs": [f"test:{tool_call_id}"],
                "reason": "修订后重新派发",
            },
            tool_call_id=f"{tool_call_id}:return",
        )
        return delegated

    def test_returned_work_revises_and_resubmits_before_final_accept(self) -> None:
        first = self._delegate(tool_call_id="tool:revision-loop:1")
        original_work_item_id = str(first["workItemId"])
        first_dispatch_id = str(first["childDispatchId"])
        self._submit_partner_result(
            child_dispatch_id=first_dispatch_id,
            post_id="room-post:first",
            content="首轮实现已交付，但验收发现恢复证据不足",
        )
        self.assertEqual(self.dispatches.get(first_dispatch_id)["status"], "review")
        first_wake = self._deliver_wake()

        returned = self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "return",
                "workItemId": original_work_item_id,
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "not_satisfied",
                "evidenceRefs": ["test:first-round"],
                "reason": "补齐重启恢复证据后再次提交",
            },
            tool_call_id="tool:return-for-revision",
        )
        self.assertEqual(returned["status"], "returned")
        self.assertEqual(returned["workItem"]["state"], "active")
        self.assertEqual(returned["workItem"]["revision"], 1)
        self._finish_facilitator_wake(first_wake)

        revised = self._delegate(
            tool_call_id="tool:revision-loop:2",
            work_item_id=original_work_item_id,
        )
        second_dispatch_id = str(revised["childDispatchId"])
        self._submit_partner_result(
            child_dispatch_id=second_dispatch_id,
            post_id="room-post:second",
            content="已按反馈补齐恢复证据并再次提交",
        )
        self.assertEqual(
            self.dispatches.get(second_dispatch_id)["status"],
            "review",
        )
        second_wake = self._deliver_wake()

        accepted = self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "accept",
                "workItemId": str(revised["workItemId"]),
                "expectedRevision": 1,
                "operabilityVerdict": "passed",
                "requirementVerdict": "satisfied",
                "evidenceRefs": ["test:revision-green", "workdoc:revision-loop@2"],
            },
            tool_call_id="tool:accept-revision",
        )
        self._finish_facilitator_wake(second_wake)

        self.assertEqual(len(self.partner_dispatches), 2)
        self.assertEqual(len(self.facilitator_turns), 2)
        self.assertNotEqual(first_dispatch_id, second_dispatch_id)
        self.assertEqual(
            revised["workItemId"],
            original_work_item_id,
            "revision delegate created a new WorkItem instead of reusing the returned item",
        )
        self.assertEqual(len(self.work.items), 1)
        final_work = self.work.items[original_work_item_id]
        self.assertEqual(final_work["revision"], 1)
        self.assertEqual(final_work["state"], "done")
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(
            self.dispatches.get(second_dispatch_id)["status"],
            "accepted",
        )

    def test_same_facilitator_collects_and_accepts_prior_root_work(self) -> None:
        delegated = self._delegate(tool_call_id="tool:prior-root")
        work_item_id = str(delegated["workItemId"])
        child_dispatch_id = str(delegated["childDispatchId"])
        self._submit_partner_result(
            child_dispatch_id=child_dispatch_id,
            post_id="room-post:prior-root",
            content="旧 Root 的交付已完成并等待验收",
        )
        self.active_root_id = "root-b"

        collected = self.application.execute(
            str(self.source["sessionId"]),
            {"op": "collect", "workItemId": work_item_id},
            tool_call_id="tool:collect-prior-root",
        )
        accepted = self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "accept",
                "workItemId": work_item_id,
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "satisfied",
                "evidenceRefs": ["test:prior-root-green"],
            },
            tool_call_id="tool:accept-prior-root",
        )

        self.assertEqual(collected["rootId"], "root-a")
        self.assertEqual(accepted["rootId"], "root-a")
        self.assertEqual(accepted["workItem"]["rootTurnId"], "root-a")
        self.assertEqual(accepted["childDispatchId"], child_dispatch_id)
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(
            self.dispatches.get(child_dispatch_id)["rootId"],
            "root-a",
        )
        self.assertEqual(
            self.review_payloads,
            [("accept", {
                "workId": work_item_id,
                "expectedRevision": 0,
                "operabilityVerdict": "passed",
                "requirementVerdict": "satisfied",
                "evidenceRefs": ["test:prior-root-green"],
            })],
        )

    def test_prior_root_review_rejects_other_facilitator_and_room(self) -> None:
        delegated = self._delegate(tool_call_id="tool:prior-root-owner-fence")
        work_item_id = str(delegated["workItemId"])
        child_dispatch_id = str(delegated["childDispatchId"])
        self._submit_partner_result(
            child_dispatch_id=child_dispatch_id,
            post_id="room-post:prior-root-owner-fence",
            content="旧 Root 的交付只能由原负责 Facilitator 验收",
        )
        self.active_root_id = "root-b"
        payload = {
            "op": "accept",
            "workItemId": work_item_id,
            "expectedRevision": 0,
            "operabilityVerdict": "passed",
            "requirementVerdict": "satisfied",
            "evidenceRefs": ["test:must-not-accept"],
        }

        for session_id in (
            self.other_facilitator["sessionId"],
            self.other_room_facilitator["sessionId"],
        ):
            with self.subTest(session_id=session_id):
                with self.assertRaisesRegex(
                    ValueError,
                    "only the accountable Facilitator",
                ):
                    self.application.execute(
                        str(session_id),
                        payload,
                        tool_call_id=f"tool:forbidden:{session_id}",
                    )

        self.assertEqual(self.review_payloads, [])
        self.assertEqual(
            self.dispatches.get(child_dispatch_id)["status"],
            "review",
        )
        self.assertEqual(self.work.items[work_item_id]["state"], "review")

    def test_returned_work_redelegates_under_new_root_without_rebinding_work(self) -> None:
        first = self._return_work_for_revision(tool_call_id="tool:cross-root-revision")
        work_item_id = str(first["workItemId"])
        first_dispatch_id = str(first["childDispatchId"])
        original_contract = dict(self.work.items[work_item_id])
        self.active_root_id = "root-b"

        revised = self._delegate(
            tool_call_id="tool:cross-root-revision:second",
            work_item_id=work_item_id,
        )
        second_dispatch_id = str(revised["childDispatchId"])

        self.assertEqual(revised["rootId"], "root-b")
        self.assertEqual(revised["workItemId"], work_item_id)
        self.assertNotEqual(second_dispatch_id, first_dispatch_id)
        self.assertEqual(revised["dispatch"]["rootId"], "root-b")
        self.assertEqual(revised["workItem"]["rootTurnId"], "root-a")
        self.assertEqual(revised["workItem"]["acceptedTurnId"], "root-b")
        for key in ("objective", "expectedOutput", "acceptanceCriteria"):
            self.assertEqual(revised["workItem"][key], original_contract[key])
        self.assertEqual(self.dispatches.get(first_dispatch_id)["status"], "returned")
        self.assertEqual(self.dispatches.get(second_dispatch_id)["rootId"], "root-b")

    def test_failed_partner_dispatch_retries_same_work_with_new_owner(self) -> None:
        first = self._delegate(tool_call_id="tool:failed-retry:first")
        work_item_id = str(first["workItemId"])
        first_dispatch_id = str(first["childDispatchId"])
        original = dict(self.work.items[work_item_id])
        self.application.observe_room_event(
            {
                "roomId": "room-a",
                "turnId": "root-a",
                "eventType": "participant_activity",
                "payload": {
                    "activityKind": "child",
                    "phase": "failed",
                    "childDispatchId": first_dispatch_id,
                    "summary": "Partner Tool loop stopped without a result",
                },
            }
        )
        self.assertEqual(self.work.items[work_item_id]["state"], "failed")

        retried = self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "retry",
                "workItemId": work_item_id,
                "targetParticipantId": self.other_facilitator["id"],
                "expectedRevision": 0,
                "reason": "原 Partner Tool loop 无进展，改由空闲伙伴继续同一合同",
            },
            tool_call_id="tool:failed-retry:second",
        )

        self.assertEqual(retried["workItemId"], work_item_id)
        self.assertNotEqual(retried["childDispatchId"], first_dispatch_id)
        self.assertEqual(retried["workItem"]["state"], "active")
        self.assertEqual(retried["workItem"]["revision"], 1)
        self.assertEqual(
            retried["workItem"]["currentOwnerParticipantId"],
            self.other_facilitator["id"],
        )
        for key in ("objective", "expectedOutput", "acceptanceCriteria"):
            self.assertEqual(retried["workItem"][key], original[key])
        self.assertEqual(self.dispatches.get(first_dispatch_id)["status"], "failed")
        self.assertEqual(
            self.dispatches.get(str(retried["childDispatchId"]))["status"],
            "dispatched",
        )

    def test_retry_recovers_faulted_same_partner_before_priority_and_dispatch(
        self,
    ) -> None:
        first = self._delegate(tool_call_id="tool:faulted-same-partner:first")
        work_item_id = str(first["workItemId"])
        first_dispatch_id = str(first["childDispatchId"])
        self.application.observe_room_event(
            {
                "roomId": "room-a",
                "turnId": "root-a",
                "eventType": "participant_activity",
                "payload": {
                    "activityKind": "child",
                    "phase": "failed",
                    "childDispatchId": first_dispatch_id,
                    "summary": "shared Runtime Host interrupted the Partner turn",
                },
            }
        )
        self.session_statuses[str(self.target["sessionId"])] = "faulted"
        ordering: list[str] = []

        def recover(session_id: str) -> None:
            ordering.append("recover")
            self.recovered_sessions.append(session_id)
            self.session_statuses[session_id] = "idle"

        def hold_priority(*_args: object, **_kwargs: object) -> None:
            self.assertEqual(
                self.session_statuses[str(self.target["sessionId"])],
                "idle",
            )
            ordering.append("priority")

        def room_target_idle(*_args: object, **_kwargs: object) -> bool:
            self.assertEqual(
                self.session_statuses[str(self.target["sessionId"])],
                "idle",
            )
            ordering.append("idle")
            return True

        original_dispatch = self.application.room_dispatch.dispatch_target

        def dispatch_target(**kwargs: object) -> dict[str, object]:
            self.assertEqual(
                self.session_statuses[str(self.target["sessionId"])],
                "idle",
            )
            ordering.append("dispatch")
            return original_dispatch(**kwargs)

        self.application.recover_faulted_session = recover
        self.application.room_turns.hold_priority_if_idle = hold_priority
        self.application.room_target_idle = room_target_idle
        self.application.room_dispatch.dispatch_target = dispatch_target

        retried = self.application.execute(
            str(self.source["sessionId"]),
            {
                "op": "retry",
                "workItemId": work_item_id,
                "targetParticipantId": self.target["id"],
                "expectedRevision": 0,
                "reason": "恢复同一 Partner Session 并继续同一 WorkItem",
            },
            tool_call_id="tool:faulted-same-partner:retry",
        )

        self.assertEqual(
            ordering,
            ["recover", "priority", "idle", "dispatch"],
        )
        self.assertEqual(
            self.recovered_sessions,
            [str(self.target["sessionId"])],
        )
        self.assertEqual(retried["workItemId"], work_item_id)
        self.assertEqual(retried["workItem"]["revision"], 1)
        self.assertEqual(len(self.work.items), 1)
        self.assertNotEqual(retried["childDispatchId"], first_dispatch_id)
        self.assertEqual(
            retried["dispatch"]["targetSessionId"],
            self.target["sessionId"],
        )

    def test_plain_delegate_does_not_recover_faulted_partner_session(self) -> None:
        self.session_statuses[str(self.target["sessionId"])] = "faulted"

        delegated = self._delegate(tool_call_id="tool:plain-faulted-delegate")

        self.assertEqual(delegated["participantId"], self.target["id"])
        self.assertEqual(self.recovered_sessions, [])

    def test_cross_root_revision_delegate_keeps_owner_room_and_contract_fences(self) -> None:
        first = self._return_work_for_revision(tool_call_id="tool:revision-fences")
        work_item_id = str(first["workItemId"])
        self.active_root_id = "root-b"
        base = {
            "op": "delegate",
            "targetParticipantId": self.target["id"],
            "task": "修复并验证同一个 Room WorkItem",
            "expectedOutput": "同一 WorkItem 的修订交付",
            "acceptanceCriteria": ["修订后双轴验收通过"],
            "workItemId": work_item_id,
        }

        rejected = (
            (
                self.other_facilitator["sessionId"],
                base,
                "other-source",
            ),
            (
                self.source["sessionId"],
                {**base, "targetParticipantId": self.other_facilitator["id"]},
                "other-target",
            ),
            (
                self.other_room_facilitator["sessionId"],
                {
                    **base,
                    "targetParticipantId": self.other_room_target["id"],
                },
                "other-room",
            ),
            (
                self.source["sessionId"],
                {**base, "task": "changed task"},
                "changed-task",
            ),
            (
                self.source["sessionId"],
                {**base, "expectedOutput": "changed output"},
                "changed-output",
            ),
            (
                self.source["sessionId"],
                {**base, "acceptanceCriteria": ["changed criterion"]},
                "changed-criteria",
            ),
        )
        for session_id, payload, case in rejected:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    self.application.execute(
                        str(session_id),
                        payload,
                        tool_call_id=f"tool:reject:{case}",
                    )

        self.work.items[work_item_id]["state"] = "done"
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.application.execute(
                str(self.source["sessionId"]),
                base,
                tool_call_id="tool:reject:terminal",
            )

        self.assertEqual(len(self.partner_dispatches), 1)
        self.assertEqual(len(self.dispatches.inflight()), 0)


if __name__ == "__main__":
    unittest.main()
