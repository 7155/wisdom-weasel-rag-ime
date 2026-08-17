from __future__ import annotations

import unittest
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
