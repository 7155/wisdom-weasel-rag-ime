from __future__ import annotations

import unittest
from threading import Event, Lock
from types import SimpleNamespace

from rag_ime.agent_room_partner_application import RoomPartnerApplicationService
from rag_ime.contracts.json_schema import validate_contract


class _RoomEvents:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []

    def publish(self, **values: object) -> dict[str, object]:
        self.published.append(dict(values))
        return dict(values)


class RoomPartnerApplicationTest(unittest.TestCase):
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
        both_started = Event()
        start_lock = Lock()
        started: list[str] = []

        def dispatch_target(**kwargs: object) -> dict[str, object]:
            target = kwargs["target"]
            assert isinstance(target, dict)
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
        self.assertEqual(result["status"], "completed")
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
            },
            tool_call_id="tool:delegate",
        )

        route = next(
            item for item in events.published
            if item["event_type"] == "route_decision"
        )
        self.assertEqual(route["payload"]["reason"], "partner_delegate")  # type: ignore[index]
        self.assertIs(route["payload"]["child"], True)  # type: ignore[index]

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
            sessions=SimpleNamespace(),
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
        )

        self.assertEqual(receipt["kind"], "result")
        self.assertEqual(len(events.published), 1)
        published = events.published[0]
        self.assertEqual(published["event_type"], "room_post")
        post = published["payload"]["post"]  # type: ignore[index]
        validate_contract(post, "room-post.v2.json")
        self.assertEqual(post["kind"], "result")
        self.assertEqual(post["publicationSource"], {
            "kind": "room_post",
            "ref": "tool:room-final",
        })


if __name__ == "__main__":
    unittest.main()
