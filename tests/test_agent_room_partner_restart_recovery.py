from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from rag_ime.agent_command_receipts import AgentCommandReceiptStore
from rag_ime.agent_event_projection import AgentEventProjectionService
from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.rooms.partner_application import RoomPartnerApplicationService
from rag_ime.rooms.partner_dispatch_store import (
    AgentRoomPartnerDispatchStore,
)
from rag_ime.rooms.session_dispatch import RoomSessionDispatchService
from rag_ime.rooms.turn_registry import RoomTurnRegistry
from rag_ime.agent_sessions import AgentSessionStore
from rag_ime.agent_wake_scheduler import AgentWakeScheduleStore
from rag_ime.contracts.json_schema import validate_contract
from tests.test_agent_room_partner_application import _RoomEvents, _RoomWorkLedger


class _RecoverySessions:
    def __init__(self) -> None:
        self.acceptance: dict[tuple[str, str], dict[str, object]] = {}
        self.terminals: dict[tuple[str, str], dict[str, object]] = {}
        self.acceptance_queries: list[tuple[str, str]] = []
        self.terminal_queries: list[tuple[str, str]] = []

    def prompt_acceptance_evidence(
        self,
        session_id: str,
        client_message_id: str,
    ) -> dict[str, object] | None:
        key = (session_id, client_message_id)
        self.acceptance_queries.append(key)
        return self.acceptance.get(key)

    def runtime_turn_terminal_event(
        self,
        session_id: str,
        turn_id: str,
    ) -> dict[str, object] | None:
        key = (session_id, turn_id)
        self.terminal_queries.append(key)
        return self.terminals.get(key)


class AgentRoomPartnerRestartRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="rag-ime-room-partner-restart-"
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
        self.room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "moderatorParticipantId": self.source["id"],
            "participants": [self.source, self.target],
        }
        self.sessions = _RecoverySessions()
        self.events = _RoomEvents()
        self.work = _RoomWorkLedger()
        participants = {
            str(self.source["id"]): self.source,
            str(self.target["id"]): self.target,
        }
        self.application = RoomPartnerApplicationService(
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
            sessions=self.sessions,
            room_events=self.events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=self.work,
            publish_room_work_activity=lambda *_args, **_kwargs: None,
            work_document_for_authority=lambda _kind, _identifier: {
                "documentId": "workdoc:one",
                "documentRevision": 2,
            },
            dispatch_store=self.dispatches,
            wake_schedules=self.wakes,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _register_prepared(
        self,
        *,
        child_dispatch_id: str,
        now_ms: int | None = None,
    ) -> dict[str, object]:
        work = self.application._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id=f"tool:{child_dispatch_id}",
            source=self.source,
            target=self.target,
            task="实现并验证 Room 重启恢复",
            expected_output="可验收恢复证据",
            acceptance_criteria=["恢复同一 Root 的终态投影"],
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
            now_ms=now_ms,
        )
        return work

    def _failed_facilitator_completion_wake(
        self,
        *,
        child_dispatch_id: str,
        error: str,
        turn_id: str = "turn:facilitator-wake",
    ) -> tuple[dict[str, object], dict[str, object]]:
        self._register_prepared(child_dispatch_id=child_dispatch_id)
        self.dispatches.mark_dispatched(child_dispatch_id)
        settled = self.dispatches.settle(
            child_dispatch_id,
            status="review",
            result="伙伴交付和验证证据",
            completion_source="room_post",
        )
        self.application._schedule_completion_wake(settled)
        claim = self.wakes.claim_due(now_ms=10**15)[0]
        self.wakes.accept(
            str(claim["runId"]),
            session_id=str(self.source["sessionId"]),
            turn_id=turn_id,
        )
        generation = int(settled["wake"]["generation"])
        self.dispatches.mark_wake(
            child_dispatch_id,
            generation=generation,
            state="delivered",
            schedule_id=str(claim["id"]),
        )
        self.dispatches.record_review(child_dispatch_id, accepted=True)
        self.wakes.fail_dispatch(str(claim["runId"]), error=error)
        self.sessions.terminals[(str(self.source["sessionId"]), turn_id)] = {
            "eventId": f"event:{turn_id}",
            "sessionId": str(self.source["sessionId"]),
            "turnId": turn_id,
            "sequence": 10,
            "eventType": "turn_failed",
            "createdAtMs": 200,
            "status": error,
        }
        return claim, self.dispatches.get(child_dispatch_id)

    def _complete_current_wake_without_result(
        self,
        child_dispatch_id: str,
        *,
        turn_id: str,
    ) -> SimpleNamespace:
        claim = self.wakes.claim_due(now_ms=10**15)[0]
        self.wakes.accept(
            str(claim["runId"]),
            session_id=str(self.source["sessionId"]),
            turn_id=turn_id,
        )
        generation = int(claim["metadata"]["generation"])
        self.dispatches.mark_wake(
            child_dispatch_id,
            generation=generation,
            state="delivered",
            schedule_id=str(claim["id"]),
        )
        terminal = SimpleNamespace(
            event_id=f"event:{turn_id}",
            session_id=str(self.source["sessionId"]),
            turn_id=turn_id,
            event_type="turn_completed",
            created_at_ms=500 + generation,
            payload={},
        )
        self.assertIs(self.wakes.finish_event(terminal), True)
        self.application.observe_wake_terminal_event(
            terminal,
            self.wakes.get(str(claim["id"])),
        )
        return terminal

    def _make_root_work_explicitly_accepted(self, work_id: str) -> None:
        item = self.work.items[work_id]
        item["state"] = "done"
        item["resultSummary"] = "实现、测试与浏览器运行边界已记录。"
        item["evidenceRefs"] = ["docs/TESTING.md", "browser-run:wildcube"]
        item["review"] = {
            "operabilityVerdict": "passed",
            "requirementVerdict": "satisfied",
            "evidenceRefs": ["test:npm", "browser-run:wildcube"],
            "reason": "",
            "reviewerParticipantId": str(self.source["id"]),
            "reviewedAtMs": 500,
        }

    def test_partner_prompt_uses_child_dispatch_id_as_stable_client_message_id(
        self,
    ) -> None:
        prompt_payloads: list[dict[str, object]] = []

        def prompt(
            _session_id: str,
            payload: dict[str, object],
        ) -> dict[str, object]:
            prompt_payloads.append(dict(payload))
            return {"accepted": True, "turnId": "turn:partner"}

        host = SimpleNamespace(
            _context_source_token=object(),
            prompt=prompt,
            _accept_room_turn=lambda *_args: None,
            _cancel_room_turn=lambda *_args: None,
            rooms=SimpleNamespace(
                advance_delivery_cursor=lambda *_args, **_kwargs: None,
                commit_route=lambda *_args, **_kwargs: None,
            ),
            room_turns=SimpleNamespace(
                release_priority_session=lambda *_args: None,
                cancel=lambda *_args: None,
            ),
            room_events=_RoomEvents(),
        )
        host.room_turns.cancel = host._cancel_room_turn
        dispatch = RoomSessionDispatchService(
            rooms=host.rooms, room_work=None, room_events=host.room_events,
            room_turns=host.room_turns, room_partner_dispatches=None,
            context_source_token=host._context_source_token,
            restore_participant_sessions=lambda _: None,
            guard_session_route=lambda *_: None, recover_faulted_session=lambda _: None,
            resume_goal_if_paused=lambda _: None, target_idle=lambda *_: True,
            record_room_evidence=lambda **_: {}, accept_turn=host._accept_room_turn,
            prompt=host.prompt,
            build_participant_prompt=lambda *_args, **_kwargs: "Room context",
            resolve_attachments=lambda *_args, **_kwargs: [],
        )

        result = dispatch.dispatch_target(
            room=self.room,
            target=self.target,
            decision={
                "dispatchId": "room-child:stable",
                "child": True,
            },
            message="执行重启恢复测试",
            room_turn_id="root-a",
            topic_id="topic-a",
            unread={"items": [], "omittedCount": 0, "throughSequence": 0},
            work_item=None,
            attachment_ids=(),
        )

        self.assertIs(result["accepted"], True)
        self.assertEqual(
            prompt_payloads[0]["clientMessageId"],
            "room-child:stable",
        )

    def test_cancelled_prompt_admission_projects_aborted_child_dispatch(
        self,
    ) -> None:
        cancelled_turns: list[tuple[object, ...]] = []
        accepted_turns: list[tuple[object, ...]] = []
        host = SimpleNamespace(
            _context_source_token=object(),
            prompt=lambda *_args, **_kwargs: {
                "accepted": False,
                "cancelled": True,
                "admissionCancelled": True,
                "turnId": "",
            },
            _accept_room_turn=lambda *args: accepted_turns.append(args),
            _cancel_room_turn=lambda *args: cancelled_turns.append(args),
            rooms=SimpleNamespace(
                advance_delivery_cursor=lambda *_args, **_kwargs: self.fail(
                    "cancelled dispatch must not advance delivery"
                ),
                commit_route=lambda *_args, **_kwargs: self.fail(
                    "cancelled dispatch must not commit its route"
                ),
            ),
            room_turns=SimpleNamespace(
                release_priority_session=lambda *_args: None,
                cancel=lambda *_args: None,
            ),
            room_events=_RoomEvents(),
        )
        host.room_turns.cancel = host._cancel_room_turn
        dispatch = RoomSessionDispatchService(
            rooms=host.rooms, room_work=None, room_events=host.room_events,
            room_turns=host.room_turns, room_partner_dispatches=None,
            context_source_token=host._context_source_token,
            restore_participant_sessions=lambda _: None,
            guard_session_route=lambda *_: None, recover_faulted_session=lambda _: None,
            resume_goal_if_paused=lambda _: None, target_idle=lambda *_: True,
            record_room_evidence=lambda **_: {}, accept_turn=host._accept_room_turn,
            prompt=host.prompt,
            build_participant_prompt=lambda *_args, **_kwargs: "Room context",
            resolve_attachments=lambda *_args, **_kwargs: [],
        )

        result = dispatch.dispatch_target(
            room=self.room,
            target=self.target,
            decision={
                "dispatchId": "room-child:cancelled-admission",
                "child": True,
            },
            message="执行取消语义测试",
            room_turn_id="root-a",
            topic_id="topic-a",
            unread={"items": [], "omittedCount": 0, "throughSequence": 0},
            work_item=None,
            attachment_ids=(),
        )

        self.assertIs(result["accepted"], False)
        self.assertIs(result["cancelled"], True)
        self.assertEqual(result["status"], "cancelled")
        self.assertIn("cancelled", str(result["error"]).lower())
        self.assertNotIn("without a turnId", str(result["error"]))
        self.assertNotIn("_exception", result)
        self.assertEqual(accepted_turns, [])
        self.assertEqual(cancelled_turns, [("session:partner", "root-a")])
        terminal = host.room_events.published[-1]
        self.assertEqual(terminal["event_type"], "participant_activity")
        self.assertEqual(terminal["payload"]["phase"], "aborted")
        self.assertEqual(terminal["payload"]["status"], "dispatch_cancelled")

    def test_rejected_prompt_is_not_reported_as_missing_accepted_turn(
        self,
    ) -> None:
        host = SimpleNamespace(
            _context_source_token=object(),
            prompt=lambda *_args, **_kwargs: {
                "accepted": False,
                "cancelled": False,
                "turnId": "",
                "error": "Runtime rejected this prompt",
            },
            _accept_room_turn=lambda *_args: self.fail(
                "rejected dispatch must not be accepted"
            ),
            _cancel_room_turn=lambda *_args: None,
            rooms=SimpleNamespace(
                advance_delivery_cursor=lambda *_args, **_kwargs: self.fail(
                    "rejected dispatch must not advance delivery"
                ),
                commit_route=lambda *_args, **_kwargs: self.fail(
                    "rejected dispatch must not commit its route"
                ),
            ),
            room_turns=SimpleNamespace(
                release_priority_session=lambda *_args: None,
                cancel=lambda *_args: None,
            ),
            room_events=_RoomEvents(),
        )
        host.room_turns.cancel = host._cancel_room_turn
        dispatch = RoomSessionDispatchService(
            rooms=host.rooms, room_work=None, room_events=host.room_events,
            room_turns=host.room_turns, room_partner_dispatches=None,
            context_source_token=host._context_source_token,
            restore_participant_sessions=lambda _: None,
            guard_session_route=lambda *_: None, recover_faulted_session=lambda _: None,
            resume_goal_if_paused=lambda _: None, target_idle=lambda *_: True,
            record_room_evidence=lambda **_: {}, accept_turn=host._accept_room_turn,
            prompt=host.prompt,
            build_participant_prompt=lambda *_args, **_kwargs: "Room context",
            resolve_attachments=lambda *_args, **_kwargs: [],
        )

        result = dispatch.dispatch_target(
            room=self.room,
            target=self.target,
            decision={"dispatchId": "room-child:rejected", "child": True},
            message="执行拒绝语义测试",
            room_turn_id="root-a",
            topic_id="topic-a",
            unread={"items": [], "omittedCount": 0, "throughSequence": 0},
            work_item=None,
            attachment_ids=(),
        )

        self.assertIs(result["accepted"], False)
        self.assertIs(result["cancelled"], False)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"], "Runtime rejected this prompt")
        self.assertNotIn("_exception", result)
        terminal = host.room_events.published[-1]
        self.assertEqual(terminal["payload"]["phase"], "failed")
        self.assertEqual(terminal["payload"]["status"], "dispatch_rejected")

    def test_accepted_prompt_without_turn_id_remains_an_invariant_failure(
        self,
    ) -> None:
        host = SimpleNamespace(
            _context_source_token=object(),
            prompt=lambda *_args, **_kwargs: {
                "accepted": True,
                "cancelled": False,
                "turnId": "",
            },
            _accept_room_turn=lambda *_args: self.fail(
                "turn-less acceptance must not reach the Room registry"
            ),
            _cancel_room_turn=lambda *_args: None,
            rooms=SimpleNamespace(
                advance_delivery_cursor=lambda *_args, **_kwargs: None,
                commit_route=lambda *_args, **_kwargs: None,
            ),
            room_turns=SimpleNamespace(
                release_priority_session=lambda *_args: None,
                cancel=lambda *_args: None,
            ),
            room_events=_RoomEvents(),
        )
        host.room_turns.cancel = host._cancel_room_turn
        dispatch = RoomSessionDispatchService(
            rooms=host.rooms, room_work=None, room_events=host.room_events,
            room_turns=host.room_turns, room_partner_dispatches=None,
            context_source_token=host._context_source_token,
            restore_participant_sessions=lambda _: None,
            guard_session_route=lambda *_: None, recover_faulted_session=lambda _: None,
            resume_goal_if_paused=lambda _: None, target_idle=lambda *_: True,
            record_room_evidence=lambda **_: {}, accept_turn=host._accept_room_turn,
            prompt=host.prompt,
            build_participant_prompt=lambda *_args, **_kwargs: "Room context",
            resolve_attachments=lambda *_args, **_kwargs: [],
        )

        result = dispatch.dispatch_target(
            room=self.room,
            target=self.target,
            decision={"dispatchId": "room-child:broken", "child": True},
            message="执行接纳不变量测试",
            room_turn_id="root-a",
            topic_id="topic-a",
            unread={"items": [], "omittedCount": 0, "throughSequence": 0},
            work_item=None,
            attachment_ids=(),
        )

        self.assertIs(result["accepted"], False)
        self.assertEqual(result["status"], "failed")
        self.assertIn("accepted a Room dispatch without a turnId", result["error"])
        self.assertIsInstance(result["_exception"], RuntimeError)
        terminal = host.room_events.published[-1]
        self.assertEqual(terminal["payload"]["phase"], "failed")
        self.assertEqual(terminal["payload"]["status"], "dispatch_failed")

    def test_dispatch_ledger_persists_target_session_turn_id(self) -> None:
        self._register_prepared(child_dispatch_id="room-child:persist-turn")
        self.dispatches.mark_dispatched(
            "room-child:persist-turn",
            target_session_turn_id="turn:partner-persisted",
        )

        reopened = AgentRoomPartnerDispatchStore(self.db_path)
        reopened.initialize()
        restored = reopened.get("room-child:persist-turn")

        self.assertEqual(restored["status"], "dispatched")
        self.assertEqual(
            restored["targetSessionTurnId"],
            "turn:partner-persisted",
        )

    def test_reconcile_repairs_missing_room_terminal_from_session_evidence(
        self,
    ) -> None:
        child_dispatch_id = "room-child:accepted-before-restart"
        work = self._register_prepared(child_dispatch_id=child_dispatch_id)
        acceptance_key = (str(self.target["sessionId"]), child_dispatch_id)
        self.sessions.acceptance[acceptance_key] = {
            "eventId": "event:prompt-accepted",
            "turnId": "turn:partner-completed",
            "messageId": "message:partner-task",
            "clientMessageId": child_dispatch_id,
            "createdAtMs": 100,
        }
        terminal_key = (
            str(self.target["sessionId"]),
            "turn:partner-completed",
        )
        self.sessions.terminals[terminal_key] = {
            "eventId": "event:turn-completed",
            "sessionId": str(self.target["sessionId"]),
            "turnId": "turn:partner-completed",
            "sequence": 7,
            "eventType": "turn_completed",
            "createdAtMs": 200,
        }

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["targetSessionTurnId"], "turn:partner-completed")
        self.assertEqual(recovered["status"], "review")
        self.assertEqual(self.work.items[str(work["id"])]["state"], "review")
        self.assertEqual(self.sessions.acceptance_queries, [acceptance_key])
        self.assertEqual(self.sessions.terminal_queries, [terminal_key])
        recovered_events = [
            event
            for event in self.events.published
            if event.get("event_type") == "participant_activity"
            and event.get("turn_id") == "root-a"
        ]
        self.assertEqual(len(recovered_events), 1)
        payload = recovered_events[0]["payload"]
        self.assertEqual(payload["activityKind"], "child")
        self.assertEqual(payload["phase"], "completed")
        self.assertEqual(payload["childDispatchId"], child_dispatch_id)

    def test_reconcile_restores_runtime_terminal_after_work_result_already_settled(self) -> None:
        child_id = "room-child:submitted-before-terminal"
        self._register_prepared(child_dispatch_id=child_id)
        self.dispatches.mark_dispatched(child_id, target_session_turn_id="turn:submitted")
        settled = self.dispatches.settle(
            child_id, status="review", result="已交付的真实成果",
            completion_source="room_post", post_id="post:work-result",
        )
        # Publishing a WorkResult ends the review lifecycle before Pi ends its
        # model turn. A restart may lose only the later Room execution receipt.
        self.application.reconcile()
        self.assertEqual(self.events.published, [])
        self.sessions.terminals[(str(self.target["sessionId"]), "turn:submitted")] = {
            "eventId": "event:submitted-terminal", "turnId": "turn:submitted",
            "eventType": "turn_completed", "createdAtMs": 200,
        }
        self.application.reconcile()
        self.application.reconcile()
        recovered = [event for event in self.events.published
                     if event.get("event_type") == "participant_activity"]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["payload"]["phase"], "completed")
        self.assertEqual(recovered[0]["payload"]["dispatchId"], child_id)
        self.assertEqual(recovered[0]["payload"]["sourceRuntimeEventId"], "event:submitted-terminal")
        record = self.dispatches.get(child_id)
        self.assertEqual(record["status"], "review")
        self.assertEqual(record["result"], "已交付的真实成果")
        self.assertEqual(record["wake"]["generation"], settled["wake"]["generation"])

    def test_live_and_recovered_child_terminal_publish_once_in_either_order(self) -> None:
        for live_first in (True, False):
            with self.subTest(live_first=live_first):
                child_id = f"room-child:live-recovery:{live_first}"
                turn_id = f"turn:live-recovery:{live_first}"
                session_id = str(self.target["sessionId"])
                self._register_prepared(child_dispatch_id=child_id)
                self.dispatches.mark_dispatched(child_id, target_session_turn_id=turn_id)
                settled = self.dispatches.settle(
                    child_id, status="review", result="已交付的真实成果",
                    completion_source="room_post", post_id=f"post:{child_id}",
                )
                registry = RoomTurnRegistry()
                registry.begin(session_id, "root-a", "topic-a", dispatch_id=child_id, child=True)
                registry.accept(session_id, turn_id, "root-a")
                projector = AgentEventProjectionService(
                    sessions=self.sessions, rooms=self.application.rooms,
                    agent_blocks=None,
                    observations=SimpleNamespace(enqueue_agent_event=lambda *_a, **_kw: None),
                    room_events=self.events, room_turns=registry,
                    append_recent_message=lambda *_a: None,
                    record_assistant_evidence=lambda *_a: {},
                    notify_intercom=lambda: None,
                )
                terminal = AgentEventEnvelope(
                    event_id=f"event:{turn_id}", session_id=session_id, turn_id=turn_id,
                    sequence=10, created_at_ms=200, event_type="turn_completed",
                    payload={"status": "completed", "summary": "真实成果"},
                    resume_token=f"event:{turn_id}",
                )
                self.sessions.terminals[(session_id, turn_id)] = {
                    "eventId": terminal.event_id, "turnId": turn_id,
                    "eventType": "turn_completed", "createdAtMs": 200,
                }
                if live_first:
                    projector.mirror_to_room(terminal)
                self.application.reconcile()
                if not live_first:
                    projector.mirror_to_room(terminal)
                self.application.reconcile()
                events = [
                    event for event in self.events.published
                    if event["payload"].get("sourceEventId") == terminal.event_id
                    or event["payload"].get("sourceRuntimeEventId") == terminal.event_id
                ]
                self.assertEqual(len(events), 1)
                record = self.dispatches.get(child_id)
                self.assertEqual(record["status"], "review")
                self.assertEqual(record["result"], "已交付的真实成果")
                self.assertEqual(record["wake"]["generation"], settled["wake"]["generation"])

    def test_reconcile_pages_past_settled_history_without_starving_inflight(self) -> None:
        child_id = "room-child:old-inflight"
        session_id = str(self.target["sessionId"])
        self._register_prepared(child_dispatch_id=child_id, now_ms=1)
        self.dispatches.mark_dispatched(child_id, target_session_turn_id="turn:old-inflight")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE agent_room_partner_dispatches SET updated_at_ms = 1 WHERE child_dispatch_id = ?",
                (child_id,),
            )
            # More submitted results than one recovery page. Some sort before
            # the in-flight dispatch and some after it, all with newer dates.
            for index in range(501):
                prefix = "a" if index < 250 else "z"
                submitted_id = f"room-child:{prefix}:submitted:{index:03d}"
                turn_id = f"turn:submitted:{index}"
                conn.execute(
                    """
                    INSERT INTO agent_room_partner_dispatches(
                        child_dispatch_id, room_id, root_id, parent_dispatch_id,
                        tool_call_id, source_participant_id, source_session_id,
                        target_participant_id, target_session_id, target_session_turn_id,
                        work_item_id, status, result_text, completion_source,
                        created_at_ms, updated_at_ms
                    )
                    SELECT ?, room_id, root_id, parent_dispatch_id, ?,
                           source_participant_id, source_session_id,
                           target_participant_id, target_session_id, ?, work_item_id,
                           'review', '已交付的历史成果', 'room_post', ?, ?
                    FROM agent_room_partner_dispatches WHERE child_dispatch_id = ?
                    """,
                    (submitted_id, f"tool:{submitted_id}", turn_id, index + 10, index + 10, child_id),
                )
                self.sessions.terminals[(session_id, turn_id)] = {
                    "eventId": f"event:{turn_id}", "turnId": turn_id,
                    "eventType": "turn_completed", "createdAtMs": 200,
                }
        self.sessions.terminals[(session_id, "turn:old-inflight")] = {
            "eventId": "event:old-inflight", "turnId": "turn:old-inflight",
            "eventType": "turn_completed", "createdAtMs": 200,
        }

        self.application.reconcile()
        self.assertEqual(self.dispatches.get(child_id)["status"], "review")
        self.assertEqual(len(self.events.published), 502)
        self.assertEqual(len(self.sessions.terminal_queries), 502)
        self.application.reconcile()
        self.assertEqual(len(self.events.published), 502)

    def test_reconcile_uses_targeted_turn_events_when_store_supports_them(
        self,
    ) -> None:
        child_dispatch_id = "room-child:targeted-recovery"
        self._register_prepared(child_dispatch_id=child_dispatch_id)
        self.dispatches.mark_dispatched(child_dispatch_id)
        targeted_queries: list[tuple[object, ...]] = []

        def list_events_for_turn(
            room_id: str,
            turn_id: str,
            **options: object,
        ) -> list[dict[str, object]]:
            targeted_queries.append((room_id, turn_id, options))
            return [
                {
                    "turnId": turn_id,
                    "eventType": "participant_activity",
                    "payload": {
                        "activityKind": "child",
                        "phase": "completed",
                        "childDispatchId": child_dispatch_id,
                        "summary": "recovered without scanning unrelated events",
                    },
                }
            ]

        self.application.rooms.list_events_for_turn = list_events_for_turn
        self.application.rooms.list_events = lambda *_args, **_kwargs: self.fail(
            "targeted recovery must not scan the retained Room timeline"
        )

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["status"], "review")
        self.assertEqual(len(targeted_queries), 1)
        self.assertEqual(targeted_queries[0][0:2], ("room-a", "root-a"))
        self.assertEqual(
            targeted_queries[0][2]["event_types"],
            ("room_post", "participant_message", "participant_activity"),
        )

    def test_reconcile_prefers_expected_dispatch_event_lookup(self) -> None:
        child_dispatch_id = "room-child:dispatch-targeted-recovery"
        self._register_prepared(child_dispatch_id=child_dispatch_id)
        self.dispatches.mark_dispatched(child_dispatch_id)
        dispatch_queries: list[tuple[object, ...]] = []

        def list_recovery_events_for_dispatches(
            room_id: str,
            turn_id: str,
            **options: object,
        ) -> list[dict[str, object]]:
            dispatch_queries.append((room_id, turn_id, options))
            return [
                {
                    "turnId": turn_id,
                    "eventType": "participant_activity",
                    "payload": {
                        "activityKind": "child",
                        "phase": "completed",
                        "childDispatchId": child_dispatch_id,
                        "summary": "recovered from exact dispatch lookup",
                    },
                }
            ]

        self.application.rooms.list_recovery_events_for_dispatches = (
            list_recovery_events_for_dispatches
        )
        self.application.rooms.list_events_for_turn = (
            lambda *_args, **_kwargs: self.fail(
                "dispatch-targeted recovery must precede turn-wide lookup"
            )
        )
        self.application.rooms.list_events = lambda *_args, **_kwargs: self.fail(
            "dispatch-targeted recovery must not scan the Room timeline"
        )

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["status"], "review")
        self.assertEqual(len(dispatch_queries), 1)
        self.assertEqual(dispatch_queries[0][0:2], ("room-a", "root-a"))
        self.assertEqual(
            dispatch_queries[0][2]["dispatch_ids"],
            (child_dispatch_id,),
        )

    def test_reconcile_retires_stale_prepared_without_acceptance_evidence(
        self,
    ) -> None:
        child_dispatch_id = "room-child:never-accepted"
        self._register_prepared(
            child_dispatch_id=child_dispatch_id,
            now_ms=1,
        )

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertNotIn(recovered["status"], {"prepared", "dispatched"})
        self.assertNotIn(
            child_dispatch_id,
            {
                str(record["childDispatchId"])
                for record in self.dispatches.inflight()
            },
        )
        self.assertEqual(
            self.sessions.acceptance_queries,
            [(str(self.target["sessionId"]), child_dispatch_id)],
        )

    def test_reconcile_prefers_earliest_durable_command_receipt(self) -> None:
        child_dispatch_id = "room-child:receipt-before-event"
        self._register_prepared(child_dispatch_id=child_dispatch_id)
        receipts = AgentCommandReceiptStore(self.db_path)
        receipts.initialize()
        payload = {"message": "Partner task", "attachments": []}
        claim = receipts.begin(
            command_scope="session_prompt",
            scope_id=str(self.target["sessionId"]),
            client_message_id=child_dispatch_id,
            payload=payload,
        )
        receipts.record_acceptance_evidence(
            claim,
            command_scope="session_prompt",
            scope_id=str(self.target["sessionId"]),
            client_message_id=child_dispatch_id,
            accepted={"turnId": "turn:receipt-window"},
        )
        self.application.command_acceptance_evidence = (
            lambda session_id, client_message_id: (
                receipts.acceptance_evidence_for_exact_command(
                    command_scope="session_prompt",
                    scope_id=session_id,
                    client_message_id=client_message_id,
                )
            )
        )

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["status"], "dispatched")
        self.assertEqual(
            recovered["targetSessionTurnId"],
            "turn:receipt-window",
        )
        self.assertEqual(self.sessions.acceptance_queries, [])

    def test_reconcile_preserves_aborted_terminal_disposition(self) -> None:
        child_dispatch_id = "room-child:aborted-before-room-projection"
        sessions = AgentSessionStore(self.db_path)
        sessions.initialize()
        partner_session = sessions.create(title="Partner recovery")
        self.target["sessionId"] = str(partner_session["id"])
        work = self._register_prepared(child_dispatch_id=child_dispatch_id)
        self.dispatches.mark_dispatched(
            child_dispatch_id,
            target_session_turn_id="turn:partner-aborted",
        )
        sessions.record_runtime_event(
            event_id="event:partner-aborted",
            session_id=str(self.target["sessionId"]),
            turn_id="turn:partner-aborted",
            sequence=1,
            event_type="turn_completed",
            created_at_ms=100,
            redacted_summary="aborted",
        )
        self.application.sessions = sessions

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["status"], "aborted")
        self.assertEqual(self.work.items[str(work["id"])]["state"], "failed")

    def test_reconcile_requeues_one_recoverable_facilitator_host_failure(
        self,
    ) -> None:
        child_dispatch_id = "room-child:recoverable-facilitator"
        old_claim, delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error=(
                "invalid Pi Runtime Host JSONL: Unterminated string starting at "
                "line 1 column 79673"
            ),
        )
        old_runs = self.wakes.runs(str(old_claim["id"]))

        self.application.reconcile()

        recovered = self.dispatches.get(child_dispatch_id)
        self.assertEqual(recovered["status"], "accepted")
        self.assertEqual(recovered["rootId"], delivered["rootId"])
        self.assertEqual(
            recovered["sourceSessionId"],
            delivered["sourceSessionId"],
        )
        self.assertEqual(recovered["wake"]["generation"], 2)
        self.assertEqual(recovered["wake"]["state"], "scheduled")
        self.assertEqual(
            recovered["wake"]["scheduleId"],
            f"room-wake:{child_dispatch_id}:2",
        )
        new_schedule = self.wakes.get(str(recovered["wake"]["scheduleId"]))
        self.assertEqual(new_schedule["targetSessionId"], self.source["sessionId"])
        self.assertEqual(new_schedule["metadata"]["rootId"], "root-a")
        self.assertEqual(new_schedule["metadata"]["generation"], 2)
        self.assertEqual(self.wakes.runs(str(old_claim["id"])), old_runs)

        self.application.reconcile()
        replay = self.dispatches.get(child_dispatch_id)
        self.assertEqual(replay["wake"]["generation"], 2)
        self.assertEqual(replay["wake"]["scheduleId"], new_schedule["id"])

        retry_claim = self.wakes.claim_due(now_ms=10**15)[0]
        retry_turn_id = "turn:facilitator-wake-retry"
        self.wakes.accept(
            str(retry_claim["runId"]),
            session_id=str(self.source["sessionId"]),
            turn_id=retry_turn_id,
        )
        self.dispatches.mark_wake(
            child_dispatch_id,
            generation=2,
            state="delivered",
            schedule_id=str(retry_claim["id"]),
        )
        retry_error = "Pi Runtime Host exited with code 70"
        self.wakes.fail_dispatch(str(retry_claim["runId"]), error=retry_error)
        self.sessions.terminals[
            (str(self.source["sessionId"]), retry_turn_id)
        ] = {
            "eventId": "event:facilitator-wake-retry",
            "sessionId": str(self.source["sessionId"]),
            "turnId": retry_turn_id,
            "sequence": 20,
            "eventType": "turn_failed",
            "createdAtMs": 300,
            "status": retry_error,
        }

        self.application.reconcile()

        exhausted = self.dispatches.get(child_dispatch_id)
        self.assertEqual(exhausted["wake"]["generation"], 2)
        self.assertEqual(exhausted["wake"]["state"], "failed")
        self.assertEqual(exhausted["wake"]["scheduleId"], retry_claim["id"])
        self.assertIn("exited with code 70", exhausted["error"])

    def test_reconcile_does_not_requeue_non_host_facilitator_failure(self) -> None:
        child_dispatch_id = "room-child:provider-failure"
        old_claim, delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Provider rejected the Facilitator request",
        )

        self.application.reconcile()

        converged = self.dispatches.get(child_dispatch_id)
        self.assertEqual(converged["wake"]["generation"], 1)
        self.assertEqual(converged["wake"]["state"], "failed")
        self.assertEqual(converged["wake"]["scheduleId"], old_claim["id"])
        self.assertIn("Provider rejected", converged["error"])
        self.assertEqual(self.wakes.get(str(old_claim["id"]))["status"], "failed")

    def test_reconcile_repairs_one_legacy_stale_cancel_after_host_retry(self) -> None:
        child_dispatch_id = "room-child:legacy-stale-cancel"
        old_claim, _delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Pi Runtime Host exited with code 70",
        )

        self.application.reconcile()
        generation_two = self.dispatches.get(child_dispatch_id)
        self.assertEqual(generation_two["wake"]["generation"], 2)
        retry_claim = self.wakes.claim_due(now_ms=10**15)[0]
        self.wakes.cancel_for_root(
            str(retry_claim["id"]),
            reason="Stale Room Partner completion wake",
        )

        self.application.reconcile()

        repaired = self.dispatches.get(child_dispatch_id)
        self.assertEqual(repaired["status"], "accepted")
        self.assertEqual(repaired["rootId"], "root-a")
        self.assertEqual(repaired["wake"]["generation"], 3)
        self.assertEqual(repaired["wake"]["state"], "scheduled")
        self.assertEqual(
            repaired["wake"]["scheduleId"],
            f"room-wake:{child_dispatch_id}:3",
        )
        repaired_schedule = self.wakes.get(repaired["wake"]["scheduleId"])
        self.assertEqual(repaired_schedule["metadata"]["generation"], 3)
        self.assertEqual(repaired_schedule["metadata"]["rootId"], "root-a")
        self.assertEqual(self.wakes.get(str(old_claim["id"]))["status"], "failed")
        self.assertEqual(
            self.wakes.get(str(retry_claim["id"]))["status"],
            "cancelled",
        )

        third_claim = self.wakes.claim_due(now_ms=10**15)[0]
        self.wakes.cancel_for_root(
            str(third_claim["id"]),
            reason="Stale Room Partner completion wake",
        )
        self.application.reconcile()
        exhausted = self.dispatches.get(child_dispatch_id)
        self.assertEqual(exhausted["wake"]["generation"], 3)
        self.assertEqual(exhausted["wake"]["state"], "cancelled")

    def test_completed_wake_without_typed_result_requeues_once(self) -> None:
        child_dispatch_id = "room-child:missing-typed-result"
        first_claim, _delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Pi Runtime Host exited with code 70",
        )
        self.application.reconcile()
        second_claim = self.wakes.claim_due(now_ms=10**15)[0]
        second_turn_id = "turn:completed-without-result"
        self.wakes.accept(
            str(second_claim["runId"]),
            session_id=str(self.source["sessionId"]),
            turn_id=second_turn_id,
        )
        self.dispatches.mark_wake(
            child_dispatch_id,
            generation=2,
            state="delivered",
            schedule_id=str(second_claim["id"]),
        )
        terminal = SimpleNamespace(
            event_id="event:completed-without-result",
            session_id=str(self.source["sessionId"]),
            turn_id=second_turn_id,
            event_type="turn_completed",
            created_at_ms=400,
            payload={},
        )
        self.assertIs(self.wakes.finish_event(terminal), True)

        self.application.observe_wake_terminal_event(
            terminal,
            self.wakes.get(str(second_claim["id"])),
        )

        repaired = self.dispatches.get(child_dispatch_id)
        self.assertEqual(repaired["status"], "accepted")
        self.assertEqual(repaired["wake"]["generation"], 3)
        self.assertEqual(repaired["wake"]["state"], "scheduled")
        self.assertEqual(
            repaired["wake"]["scheduleId"],
            f"room-wake:{child_dispatch_id}:3",
        )
        self.assertEqual(self.wakes.get(str(first_claim["id"]))["status"], "failed")
        self.assertEqual(self.wakes.get(str(second_claim["id"]))["status"], "completed")

    def test_completed_wake_with_typed_result_does_not_requeue(self) -> None:
        child_dispatch_id = "room-child:typed-result-present"
        self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Pi Runtime Host exited with code 70",
        )
        self.application.reconcile()
        claim = self.wakes.claim_due(now_ms=10**15)[0]
        turn_id = "turn:completed-with-result"
        self.wakes.accept(
            str(claim["runId"]),
            session_id=str(self.source["sessionId"]),
            turn_id=turn_id,
        )
        self.dispatches.mark_wake(
            child_dispatch_id,
            generation=2,
            state="delivered",
            schedule_id=str(claim["id"]),
        )
        self.application.rooms.list_events = lambda *_args, **_kwargs: [
            {
                "turnId": "root-a",
                "eventType": "room_post",
                "payload": {"post": {"kind": "result"}},
            }
        ]
        terminal = SimpleNamespace(
            event_id="event:completed-with-result",
            session_id=str(self.source["sessionId"]),
            turn_id=turn_id,
            event_type="turn_completed",
            created_at_ms=500,
            payload={},
        )
        self.assertIs(self.wakes.finish_event(terminal), True)

        self.application.observe_wake_terminal_event(
            terminal,
            self.wakes.get(str(claim["id"])),
        )

        settled = self.dispatches.get(child_dispatch_id)
        self.assertEqual(settled["wake"]["generation"], 2)
        self.assertEqual(settled["wake"]["state"], "delivered")
        self.assertEqual(settled["wake"]["scheduleId"], claim["id"])

    def test_typed_result_cancels_queued_failed_partner_wake_before_dispatch(self) -> None:
        child_dispatch_id = "room-child:failed-after-root-result"
        self._register_prepared(child_dispatch_id=child_dispatch_id)
        self.dispatches.mark_dispatched(child_dispatch_id)
        settled = self.dispatches.settle(
            child_dispatch_id,
            status="failed",
            result="Partner Tool loop stopped",
            completion_source="session_terminal",
        )
        self.application._schedule_completion_wake(settled)
        self.events.publish_projection(
            projection_key="room-terminal-result:room-a:root-a",
            room_id="room-a",
            event_type="room_post",
            payload={"post": {"kind": "result"}},
            turn_id="root-a",
            participant_id=self.source["id"],
            source_session_id=self.source["sessionId"],
            topic_id="topic-a",
        )
        dispatched: list[str] = []
        self.application.dispatch_facilitator_wake = (
            lambda _claim, _record: dispatched.append("called") or True
        )
        claim = self.wakes.claim_due(now_ms=10**15)[0]

        self.application.dispatch_wake(claim)

        self.assertEqual(dispatched, [])
        self.assertEqual(self.wakes.get(str(claim["id"]))["status"], "cancelled")
        self.assertEqual(
            self.dispatches.get(child_dispatch_id)["wake"]["state"],
            "cancelled",
        )

    def test_exhausted_completed_wake_projects_one_result_from_accepted_work(
        self,
    ) -> None:
        child_dispatch_id = "room-child:terminal-result-projection"
        _claim, delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Pi Runtime Host exited with code 70",
        )
        self._make_root_work_explicitly_accepted(str(delivered["workItemId"]))
        sibling_dispatch_id = "room-child:terminal-result-sibling"
        sibling_work = self._register_prepared(
            child_dispatch_id=sibling_dispatch_id,
        )
        self.dispatches.mark_dispatched(sibling_dispatch_id)
        sibling = self.dispatches.settle(
            sibling_dispatch_id,
            status="review",
            result="第二条伙伴工作已提交",
            completion_source="room_post",
        )
        sibling_generation = int(sibling["wake"]["generation"])
        sibling_schedule_id = (
            f"room-wake:{sibling_dispatch_id}:{sibling_generation}"
        )
        self.dispatches.mark_wake(
            sibling_dispatch_id,
            generation=sibling_generation,
            state="delivered",
            schedule_id=sibling_schedule_id,
        )
        self.dispatches.record_review(sibling_dispatch_id, accepted=True)
        self.dispatches.mark_wake(
            sibling_dispatch_id,
            generation=sibling_generation,
            state="failed",
            schedule_id=sibling_schedule_id,
            error=(
                "Facilitator turn completed without room_partner "
                "post(kind=result)"
            ),
        )
        self._make_root_work_explicitly_accepted(str(sibling_work["id"]))
        self.application.reconcile()
        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:missing-result-2",
        )
        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:missing-result-3",
        )

        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:missing-result-4",
        )
        self.application.reconcile()

        projected = [
            event
            for event in self.events.published
            if event.get("event_type") == "room_post"
        ]
        self.assertEqual(len(projected), 1)
        payload = projected[0]["payload"]
        post = payload["post"]  # type: ignore[index]
        self.assertEqual(post["kind"], "result")
        self.assertEqual(post["authorActorRef"], self.source["id"])
        self.assertEqual(
            post["publicationSource"]["ref"],  # type: ignore[index]
            f"room-wake:{child_dispatch_id}:4",
        )
        self.assertEqual(
            post["publicationSource"]["kind"],  # type: ignore[index]
            "runtime_projection",
        )
        self.assertEqual(
            payload["terminalProjection"]["basis"],  # type: ignore[index]
            "explicit_dual_axis_work_reviews",
        )
        self.assertIn("Runtime 根据持久化验收账本投影", post["content"])
        self.assertIn("运行可操作性 passed", post["content"])
        validate_contract(post, "room-post.v2.json")
        settled = self.dispatches.get(child_dispatch_id)
        self.assertEqual(settled["wake"]["generation"], 4)
        self.assertEqual(settled["wake"]["state"], "delivered")
        self.assertEqual(settled["error"], "")
        self.assertEqual(
            self.work.items[str(delivered["workItemId"])]["state"],
            "done",
        )
        sibling_settled = self.dispatches.get(sibling_dispatch_id)
        self.assertEqual(sibling_settled["wake"]["state"], "delivered")
        self.assertEqual(sibling_settled["error"], "")
        self.assertEqual(
            self.work.items[str(sibling_work["id"])]["state"],
            "done",
        )

    def test_exhausted_completed_wake_without_review_evidence_stays_failed(
        self,
    ) -> None:
        child_dispatch_id = "room-child:terminal-result-ineligible"
        _claim, _delivered = self._failed_facilitator_completion_wake(
            child_dispatch_id=child_dispatch_id,
            error="Pi Runtime Host exited with code 70",
        )
        self.application.reconcile()
        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:ineligible-2",
        )
        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:ineligible-3",
        )
        self._complete_current_wake_without_result(
            child_dispatch_id,
            turn_id="turn:ineligible-4",
        )

        projected = [
            event
            for event in self.events.published
            if event.get("event_type") == "room_post"
        ]
        self.assertEqual(projected, [])
        settled = self.dispatches.get(child_dispatch_id)
        self.assertEqual(settled["wake"]["state"], "failed")
        self.assertIn("without room_partner post", settled["error"])


if __name__ == "__main__":
    unittest.main()
