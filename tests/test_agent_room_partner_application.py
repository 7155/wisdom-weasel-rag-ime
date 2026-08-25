from __future__ import annotations

import unittest
from threading import Event, Lock
from types import SimpleNamespace

from rag_ime.agent_room_partner_application import (
    RoomPartnerApplicationService,
    _partner_task_message,
)
from rag_ime.contracts.json_schema import validate_contract


class _RoomEvents:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []
        self.projections: dict[str, dict[str, object]] = {}

    def publish(self, **values: object) -> dict[str, object]:
        self.published.append(dict(values))
        return dict(values)

    def publish_projection(
        self,
        *,
        projection_key: str,
        **values: object,
    ) -> dict[str, object]:
        projected = dict(values)
        existing = self.projections.get(projection_key)
        if existing is not None:
            if existing != projected:
                raise ValueError("Room projection key was rebound")
            return dict(existing)
        self.projections[projection_key] = projected
        self.published.append(projected)
        return dict(projected)

    def has_projection(self, projection_key: str) -> bool:
        return projection_key in self.projections


class _RoomWorkLedger:
    def __init__(self) -> None:
        self._lock = Lock()
        self.items: dict[str, dict[str, object]] = {}

    def create(self, **values: object) -> dict[str, object]:
        with self._lock:
            client_id = str(values["client_message_id"])
            for existing in self.items.values():
                if existing["clientMessageId"] == client_id:
                    return dict(existing)
            work_id = f"room-work:{len(self.items) + 1}"
            item = {
                "id": work_id,
                "roomId": values["room_id"],
                "rootTurnId": values["root_turn_id"],
                "topicId": values["topic_id"],
                "objective": values["objective"],
                "expectedOutput": values["expected_output"],
                "acceptanceCriteria": list(values["acceptance_criteria"]),
                "currentOwnerParticipantId": values["current_owner_participant_id"],
                "createdByParticipantId": values["created_by_participant_id"],
                "accountableParticipantId": values["accountable_participant_id"],
                "clientMessageId": client_id,
                "assignmentKey": f"assignment:{work_id}",
                "acceptedTurnId": "",
                "state": "active",
                "resultSummary": "",
                "evidenceRefs": [],
                "review": {
                    "operabilityVerdict": "",
                    "requirementVerdict": "",
                    "evidenceRefs": [],
                    "reason": "",
                    "reviewerParticipantId": "",
                    "reviewedAtMs": None,
                },
            }
            self.items[work_id] = item
            return dict(item)

    def list(self, **values: object) -> list[dict[str, object]]:
        states = set(values.get("states") or ())
        with self._lock:
            return [
                dict(item)
                for item in self.items.values()
                if not states or item["state"] in states
            ]

    def list_for_root(
        self,
        *,
        room_id: str,
        root_turn_id: str,
    ) -> list[dict[str, object]]:
        with self._lock:
            return [
                dict(item)
                for item in self.items.values()
                if item["roomId"] == room_id
                and item["rootTurnId"] == root_turn_id
            ]

    def get(self, work_id: str, **_values: object) -> dict[str, object]:
        with self._lock:
            return dict(self.items[work_id])

    def claim_dispatch(self, work_id: str, **values: object) -> dict[str, object]:
        with self._lock:
            self.items[work_id]["acceptedTurnId"] = values["room_turn_id"]
            return dict(self.items[work_id])

    def fail_dispatch(self, work_id: str, **values: object) -> dict[str, object]:
        with self._lock:
            self.items[work_id]["acceptedTurnId"] = values[
                "previous_accepted_turn_id"
            ]
            return dict(self.items[work_id])

    def submit(self, _session_id: str, payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        with self._lock:
            item = self.items[str(payload["workId"])]
            item["state"] = "review"
            item["resultSummary"] = payload["resultSummary"]
            item["evidenceRefs"] = list(payload["evidenceRefs"])
            item["proposedOperabilityVerdict"] = str(
                payload.get("proposedOperabilityVerdict") or ""
            )
            item["proposedRequirementVerdict"] = str(
                payload.get("proposedRequirementVerdict") or ""
            )
            return dict(item)

    def accept(self, _session_id: str, payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        with self._lock:
            item = self.items[str(payload["workId"])]
            item["state"] = "done"
            item["review"] = {
                "operabilityVerdict": payload.get("operabilityVerdict", ""),
                "requirementVerdict": payload.get("requirementVerdict", ""),
                "evidenceRefs": list(payload.get("evidenceRefs") or []),
                "reason": "",
                "reviewerParticipantId": "room-a:p1",
                "reviewedAtMs": 1,
            }
            return dict(item)

    def escalate(self, _session_id: str, payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        with self._lock:
            item = self.items[str(payload["workId"])]
            item["state"] = "failed"
            return dict(item)

    def block(self, _session_id: str, payload: object) -> dict[str, object]:
        assert isinstance(payload, dict)
        with self._lock:
            item = self.items[str(payload["workId"])]
            item["state"] = "blocked"
            item["blocker"] = {
                "reason": payload["reason"],
                "nextStep": payload["nextStep"],
            }
            return dict(item)


class RoomPartnerApplicationTest(unittest.TestCase):
    def test_partner_task_brief_exposes_conditional_private_agent_choice(self) -> None:
        message = _partner_task_message(
            source={"displayName": "澄·远"},
            task="实现多个互不重叠的游戏子系统",
            expected_output="可运行实现与验证证据",
            acceptance_criteria=["真实路径通过", "需求语义满足"],
        )

        self.assertIn("至少两个独立、非重叠", message)
        self.assertIn("agents", message)
        self.assertIn("一次批量", message)
        self.assertIn("父 Agent 保留自己的工作线", message)
        self.assertIn("否则当前 Session 直接完成", message)
        self.assertIn("产物真实存在后再派发", message)
        self.assertIn("不要让审核者和生产者在同一波", message)
        self.assertNotIn("Luna", message)
        self.assertNotIn("GPT-5", message)

    def test_peer_ask_and_reply_preserve_direct_participant_identity(self) -> None:
        source = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·今",
            "status": "active",
        }
        target = {
            "id": "room-a:p3",
            "roomId": "room-a",
            "sessionId": "room-a:s3",
            "displayName": "澄·初",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        calls: list[tuple[str, dict[str, object]]] = []

        def send_room_intercom(session_id: str, payload: object) -> dict[str, object]:
            assert isinstance(payload, dict)
            calls.append((session_id, dict(payload)))
            return {
                "id": "message:ask" if payload["kind"] == "ask" else "message:reply",
                "sourceParticipantId": source["id"],
                "targetParticipantId": target["id"],
                **payload,
            }

        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: source,
                get=lambda _room_id: room,
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("", ""),
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
            send_room_intercom=send_room_intercom,
            list_room_intercom=lambda _session_id: [],
        )

        ask = service.execute(
            str(source["sessionId"]),
            {
                "op": "peer_ask",
                "targetParticipantId": target["id"],
                "content": "请直接核对接口边界",
            },
            tool_call_id="tool:peer-ask",
        )
        reply = service.execute(
            str(source["sessionId"]),
            {
                "op": "peer_reply",
                "replyTo": "message:ask",
                "content": "边界已核对",
            },
            tool_call_id="tool:peer-reply",
        )

        self.assertEqual(
            calls,
            [
                (
                    source["sessionId"],
                    {
                        "kind": "ask",
                        "content": "请直接核对接口边界",
                        "clientMessageId": "tool:peer-ask",
                        "targetParticipantId": target["id"],
                    },
                ),
                (
                    source["sessionId"],
                    {
                        "kind": "reply",
                        "content": "边界已核对",
                        "clientMessageId": "tool:peer-reply",
                        "replyTo": "message:ask",
                    },
                ),
            ],
        )
        self.assertEqual(ask["operation"], "peer_ask")
        self.assertEqual(reply["operation"], "peer_reply")
        self.assertEqual(ask["rootId"], "")

    def test_delegate_batch_starts_independent_partners_before_waiting(self) -> None:
        source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·远",
            "status": "active",
        }
        targets = [
            {
                "id": "room-a:p2",
                "roomId": "room-a",
                "sessionId": "room-a:s2",
                "displayName": "澄·今",
                "status": "active",
            },
            {
                "id": "room-a:p3",
                "roomId": "room-a",
                "sessionId": "room-a:s3",
                "displayName": "澄·初",
                "status": "active",
            },
        ]
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [source, *targets],
        }
        by_participant = {str(item["id"]): item for item in targets}
        by_session = {str(item["sessionId"]): item for item in targets}
        events = _RoomEvents()
        ledger = _RoomWorkLedger()
        both_started = Event()
        start_lock = Lock()
        started: list[str] = []
        dispatched_work: list[dict[str, object]] = []

        def dispatch_target(**kwargs: object) -> dict[str, object]:
            target = kwargs["target"]
            assert isinstance(target, dict)
            work_item = kwargs["work_item"]
            assert isinstance(work_item, dict)
            dispatched_work.append(dict(work_item))
            with start_lock:
                started.append(str(target["id"]))
                if len(started) == 2:
                    both_started.set()
            if not both_started.wait(timeout=1):
                raise AssertionError("Room batch dispatch ran serially")
            return {
                "accepted": True,
                "sessionTurnId": f"turn:{target['id']}",
            }

        rooms = SimpleNamespace(
            participant_for_session=lambda session_id, **_kwargs: (
                source if session_id == source["sessionId"] else by_session[session_id]
            ),
            get=lambda _room_id: room,
            participant=lambda participant_id: by_participant[participant_id],
            plan_routes=lambda *_args, **kwargs: [{
                "reason": "explicit_invite",
                "targetDisplayName": by_participant[
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
        )
        service = RoomPartnerApplicationService(
            rooms=rooms,
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
                turn_targets=lambda *_args, **_kwargs: [],
                hold_priority_if_idle=lambda *_args, **_kwargs: None,
                release_priority_session=lambda *_args, **_kwargs: None,
                is_cancelled=lambda *_args, **_kwargs: False,
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(dispatch_target=dispatch_target),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=ledger,
            publish_room_work_activity=lambda *_args, **_kwargs: None,
        )
        service._wait_for_child = lambda **kwargs: {  # type: ignore[method-assign]
            "schemaVersion": "rag-ime.room-partner-result.v1",
            "operation": "delegate",
            "childDispatchId": kwargs["child_dispatch_id"],
            "participantId": kwargs["target"]["id"],
            "status": "completed",
            "result": "done",
        }

        result = service.execute(
            str(source["sessionId"]),
            {
                "op": "delegate_batch",
                "phase": "并行调查",
                "tasks": [
                    {
                        "targetParticipantId": targets[0]["id"],
                        "task": "核对运行时契约",
                        "expectedOutput": "契约证据",
                        "acceptanceCriteria": ["给出调用链"],
                    },
                    {
                        "targetParticipantId": targets[1]["id"],
                        "task": "核对前端投影",
                        "expectedOutput": "投影证据",
                        "acceptanceCriteria": ["给出事件字段"],
                    },
                ],
            },
            tool_call_id="tool:delegate-batch",
        )

        self.assertCountEqual(started, [targets[0]["id"], targets[1]["id"]])
        self.assertEqual(result["operation"], "delegate_batch")
        self.assertEqual(result["phase"], "并行调查")
        self.assertEqual(result["parallelism"], 2)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["accepted"], 2)
        self.assertTrue(str(result["waveId"]).startswith("room-wave:"))
        self.assertEqual(
            [item["participantId"] for item in result["results"]],
            [targets[0]["id"], targets[1]["id"]],
        )
        routes = [
            item["payload"]
            for item in events.published
            if item["event_type"] == "route_decision"
        ]
        self.assertEqual(
            {str(route["waveId"]) for route in routes},
            {str(result["waveId"])},
        )
        self.assertEqual(
            sorted(int(route["parallelIndex"]) for route in routes),
            [0, 1],
        )
        self.assertTrue(all(route["parallelSize"] == 2 for route in routes))
        self.assertEqual(len(ledger.items), 2)
        self.assertEqual(len(dispatched_work), 2)
        self.assertEqual(
            {str(item["currentOwnerParticipantId"]) for item in ledger.items.values()},
            {str(item["id"]) for item in targets},
        )
        self.assertTrue(all(item["rootTurnId"] == "root-a" for item in ledger.items.values()))
        self.assertTrue(all(route.get("workItemId") for route in routes))

    def test_delegate_projects_child_route_as_partner_delegation(self) -> None:
        source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·远",
            "status": "active",
        }
        target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·今",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        events = _RoomEvents()
        rooms = SimpleNamespace(
            participant_for_session=lambda session_id, **_kwargs: (
                source if session_id == source["sessionId"] else target
            ),
            get=lambda _room_id: room,
            participant=lambda _participant_id: target,
            plan_routes=lambda *_args, **_kwargs: [{
                "reason": "explicit_invite",
                "targetDisplayName": target["displayName"],
                "targetParticipantId": target["id"],
            }],
            unread_public_messages=lambda *_args, **_kwargs: [],
            list_events=lambda *_args, **_kwargs: [],
        )
        service = RoomPartnerApplicationService(
            rooms=rooms,
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
                turn_targets=lambda *_args, **_kwargs: [],
                hold_priority_if_idle=lambda *_args, **_kwargs: None,
                release_priority_session=lambda *_args, **_kwargs: None,
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(
                dispatch_target=lambda **_kwargs: {"accepted": True},
            ),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
        )
        service._wait_for_child = lambda **_kwargs: {"status": "completed"}  # type: ignore[method-assign]

        service.execute(
            str(source["sessionId"]),
            {
                "op": "delegate",
                "targetParticipantId": target["id"],
                "task": "只读核对职责边界",
                "expectedOutput": "边界证据",
                "acceptanceCriteria": ["给出调用链"],
            },
            tool_call_id="tool:delegate",
        )

        route = next(
            item for item in events.published
            if item["event_type"] == "route_decision"
        )
        self.assertEqual(route["payload"]["reason"], "partner_delegate")  # type: ignore[index]
        self.assertIs(route["payload"]["child"], True)  # type: ignore[index]

    def test_cancelled_child_admission_releases_work_without_marking_it_failed(
        self,
    ) -> None:
        source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "Facilitator",
            "status": "active",
        }
        target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "Partner",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        ledger = _RoomWorkLedger()
        work_phases: list[str] = []
        rooms = SimpleNamespace(
            participant_for_session=lambda session_id, **_kwargs: (
                source if session_id == source["sessionId"] else target
            ),
            get=lambda _room_id: room,
            participant=lambda _participant_id: target,
            plan_routes=lambda *_args, **_kwargs: [{
                "reason": "partner_delegate",
                "targetDisplayName": target["displayName"],
                "targetParticipantId": target["id"],
            }],
            unread_public_messages=lambda *_args, **_kwargs: {
                "items": [],
                "omittedCount": 0,
                "throughSequence": 0,
            },
            list_events=lambda *_args, **_kwargs: [],
        )
        service = RoomPartnerApplicationService(
            rooms=rooms,
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
                turn_targets=lambda *_args, **_kwargs: [],
                hold_priority_if_idle=lambda *_args, **_kwargs: None,
                release_priority_session=lambda *_args, **_kwargs: None,
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=_RoomEvents(),
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(
                dispatch_target=lambda **_kwargs: {
                    "accepted": False,
                    "cancelled": True,
                    "status": "cancelled",
                    "error": "Pi Runtime cancelled the Room dispatch before admission",
                },
            ),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=ledger,
            publish_room_work_activity=lambda _work, **kwargs: work_phases.append(
                str(kwargs["phase"])
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "cancelled.*before admission"):
            service.execute(
                str(source["sessionId"]),
                {
                    "op": "delegate",
                    "targetParticipantId": target["id"],
                    "task": "执行取消语义测试",
                    "expectedOutput": "保持真实 WorkItem 状态",
                    "acceptanceCriteria": ["取消不误报失败"],
                },
                tool_call_id="tool:cancelled-admission",
            )

        work = next(iter(ledger.items.values()))
        self.assertEqual(work["state"], "active")
        self.assertEqual(work["acceptedTurnId"], "")
        self.assertEqual(work_phases, ["assigned", "aborted"])

    def test_completed_work_stays_in_review_until_facilitator_decides(self) -> None:
        source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·远",
            "status": "active",
        }
        target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·今",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        events = _RoomEvents()
        ledger = _RoomWorkLedger()
        published_phases: list[str] = []
        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: source,
                get=lambda _room_id: room,
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=ledger,
            publish_room_work_activity=lambda _work, **kwargs: published_phases.append(
                str(kwargs["phase"])
            ),
        )
        work = service._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id="tool:delegate",
            source=source,
            target=target,
            task="核对契约",
            expected_output="契约证据",
            acceptance_criteria=["给出调用链"],
        )

        submitted = service._settle_delegated_work(
            work,
            phase="completed",
            result="已核对调用链",
            child_dispatch_id="room-child:1",
            source=source,
            target=target,
        )

        self.assertEqual(submitted["state"], "review")  # type: ignore[index]
        self.assertEqual(submitted["evidenceRefs"], ["room-child:1"])  # type: ignore[index]
        receipt = service.execute(
            str(source["sessionId"]),
            {"op": "post", "kind": "result", "content": "Root 已汇合"},
            tool_call_id="tool:post",
        )
        self.assertEqual(ledger.items[str(work["id"])]["state"], "review")
        self.assertEqual(receipt["settledWorkItems"], [])
        self.assertEqual(published_phases, ["assigned", "submitted"])

    def test_completed_work_blocks_until_its_document_has_opening_and_final_updates(self) -> None:
        source = {
            "id": "room-a:p1", "roomId": "room-a", "sessionId": "room-a:s1",
            "displayName": "澄·远", "status": "active",
        }
        target = {
            "id": "room-a:p2", "roomId": "room-a", "sessionId": "room-a:s2",
            "displayName": "澄·今", "status": "active",
        }
        room = {
            "id": "room-a", "status": "active", "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        ledger = _RoomWorkLedger()
        published_phases: list[str] = []
        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: source,
                get=lambda _room_id: room,
            ),
            room_turns=SimpleNamespace(active_turn=lambda _session_id: ("root-a", "dispatch-a")),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=_RoomEvents(),
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
            room_work=ledger,
            publish_room_work_activity=lambda _work, **kwargs: published_phases.append(
                str(kwargs["phase"])
            ),
            work_document_for_authority=lambda _kind, _identifier: {
                "documentId": "workdoc:1",
                "documentRevision": 1,
            },
        )
        work = service._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id="tool:delegate-doc",
            source=source,
            target=target,
            task="实现工作流",
            expected_output="可验证实现",
            acceptance_criteria=["同步工作文档"],
        )

        blocked = service._settle_delegated_work(
            work,
            phase="completed",
            result="代码已完成但文档未同步",
            child_dispatch_id="room-child:doc",
            source=source,
            target=target,
        )

        self.assertEqual(blocked["state"], "blocked")  # type: ignore[index]
        self.assertIn("WorkDocument", blocked["blocker"]["reason"])  # type: ignore[index]
        self.assertEqual(published_phases, ["assigned", "blocked"])

    def test_work_result_delivery_submits_without_automatic_acceptance(self) -> None:
        source = {
            "id": "room-a:p1", "roomId": "room-a", "sessionId": "room-a:s1",
            "displayName": "澄·远", "status": "active",
        }
        target = {
            "id": "room-a:p2", "roomId": "room-a", "sessionId": "room-a:s2",
            "displayName": "澄·今", "status": "active",
        }
        room = {
            "id": "room-a", "status": "active", "activeTopicId": "topic-a",
            "participants": [source, target],
        }
        ledger = _RoomWorkLedger()
        published_phases: list[str] = []
        child_dispatch_id = "room-child:work-result"
        post_id = "room-post:work-result"
        work_result_event = {
            "eventType": "room_post",
            "payload": {
                "post": {
                    "postId": post_id,
                    "rootId": "root-a",
                    "dispatchId": child_dispatch_id,
                    "authorActorRef": target["id"],
                    "kind": "work_result",
                    "content": "文档和实现均已交付",
                },
            },
        }
        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: source,
                get=lambda _room_id: room,
                list_events=lambda *_args, **_kwargs: [work_result_event],
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
                is_cancelled=lambda *_args, **_kwargs: False,
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
            room_work=ledger,
            publish_room_work_activity=lambda _work, **kwargs: published_phases.append(
                str(kwargs["phase"])
            ),
            work_document_for_authority=lambda _kind, _identifier: {
                "documentId": "workdoc:1",
                "documentRevision": 2,
            },
        )
        work = service._create_delegated_work(
            room_id="room-a",
            root_id="root-a",
            topic_id="topic-a",
            tool_call_id="tool:delegate-work-result",
            source=source,
            target=target,
            task="实现工作流",
            expected_output="可验证实现",
            acceptance_criteria=["同步工作文档"],
        )

        result = service._settle_delegated_work(
            work,
            phase="completed",
            result="文档和实现均已交付",
            child_dispatch_id=child_dispatch_id,
            source=source,
            target=target,
        )

        self.assertEqual(result["state"], "review")  # type: ignore[index]
        self.assertEqual(result["resultSummary"], "文档和实现均已交付")  # type: ignore[index]
        self.assertEqual(published_phases, ["assigned", "submitted"])

    def test_work_result_post_requires_structured_proposed_verdicts(self) -> None:
        participant = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·今",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
        }
        events = _RoomEvents()
        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: participant,
                get=lambda _room_id: room,
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-b"),
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(),
            room_events=events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
        )

        with self.assertRaisesRegex(
            ValueError,
            "proposedOperabilityVerdict",
        ):
            service.execute(
                "room-a:s2",
                {
                    "op": "post",
                    "kind": "work_result",
                    "content": "交付完成，但缺少结构化提交判定。",
                },
                tool_call_id="tool:work-result-missing",
            )
        self.assertEqual(events.published, [])

        receipt = service.execute(
            "room-a:s2",
            {
                "op": "post",
                "kind": "work_result",
                "content": "浏览器执行 FAILED，两轴 UNVERIFIED。",
                "proposedOperabilityVerdict": "failed",
                "proposedRequirementVerdict": "unverified",
            },
            tool_call_id="tool:work-result-honest",
        )

        self.assertEqual(receipt["kind"], "work_result")
        post = events.published[0]["payload"]["post"]  # type: ignore[index]
        validate_contract(post, "room-post.v2.json")
        self.assertEqual(
            post["workResult"],
            {
                "proposedOperabilityVerdict": "failed",
                "proposedRequirementVerdict": "unverified",
            },
        )

    def test_post_publishes_one_valid_typed_room_post(self) -> None:
        participant = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·远",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "activeTopicId": "topic-a",
        }
        events = _RoomEvents()
        service = RoomPartnerApplicationService(
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: participant,
                get=lambda _room_id: room,
            ),
            room_turns=SimpleNamespace(
                active_turn=lambda _session_id: ("root-a", "dispatch-a"),
            ),
            runtime_status=lambda: {},
            sessions=SimpleNamespace(
                latest_runtime_turn_id=lambda _session_id: "turn:facilitator-final",
            ),
            room_events=events,
            room_target_idle=lambda *_args, **_kwargs: True,
            begin_room_turn=lambda *_args, **_kwargs: None,
            room_dispatch=SimpleNamespace(),
            cancel_room_turn=lambda *_args, **_kwargs: None,
            abort_session=lambda *_args, **_kwargs: {},
            room_topic_for_turn=lambda _root_id: "topic-a",
        )

        receipt = service.execute(
            "room-a:s1",
            {
                "op": "post",
                "kind": "result",
                "content": "最终结果已生成，并附带交互式 HTML。",
            },
            tool_call_id="tool:room-final",
            source_loop_id="pi:message:assistant:final",
        )

        self.assertEqual(receipt["kind"], "result")
        self.assertEqual(len(events.published), 1)
        published = events.published[0]
        self.assertEqual(published["event_type"], "room_post")
        self.assertEqual(
            published["payload"]["sourceTurnId"],  # type: ignore[index]
            "turn:facilitator-final",
        )
        self.assertEqual(
            published["payload"]["sourceLoopId"],  # type: ignore[index]
            "pi:message:assistant:final",
        )
        post = published["payload"]["post"]  # type: ignore[index]
        validate_contract(post, "room-post.v2.json")
        self.assertEqual(post["kind"], "result")
        self.assertEqual(post["publicationSource"], {
            "kind": "room_post",
            "ref": "tool:room-final",
        })
        self.assertTrue(
            events.has_projection("room-terminal-result:room-a:root-a")
        )
        replay = service.execute(
            "room-a:s1",
            {
                "op": "post",
                "kind": "result",
                "content": "不应形成第二个 Room 终态。",
            },
            tool_call_id="tool:room-final-replay",
        )
        self.assertIs(replay["published"], False)
        self.assertEqual(len(events.published), 1)


if __name__ == "__main__":
    unittest.main()
