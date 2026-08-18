from __future__ import annotations

import unittest
from collections.abc import Mapping
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


class _AuthorityWork:
    def __init__(
        self,
        source: Mapping[str, object],
        targets: list[Mapping[str, object]],
    ) -> None:
        self.source = dict(source)
        self.targets = {str(item["id"]): dict(item) for item in targets}
        self.items: dict[str, dict[str, object]] = {}
        self.lock = Lock()

    def require_dependencies_done(
        self,
        _room_id: str,
        work_ids: tuple[str, ...],
    ) -> list[dict[str, object]]:
        if work_ids:
            raise AssertionError("this fixture has no dependencies")
        return []

    def assign(
        self,
        _session_id: str,
        payload: Mapping[str, object],
        *,
        root_turn_id: str,
        topic_id: str,
    ) -> tuple[dict[str, object], bool]:
        with self.lock:
            for item in self.items.values():
                if item["clientMessageId"] == payload["clientMessageId"]:
                    return dict(item), False
            work_id = f"room-work:{len(self.items) + 1}"
            item = {
                "id": work_id,
                "roomId": str(self.source["roomId"]),
                "rootTurnId": root_turn_id,
                "topicId": topic_id,
                "clientMessageId": str(payload["clientMessageId"]),
                "objective": str(payload["objective"]),
                "expectedOutput": str(payload["expectedOutput"]),
                "acceptanceCriteria": list(payload["acceptanceCriteria"]),
                "currentOwnerParticipantId": str(self.source["id"]),
                "offeredToParticipantId": str(payload["targetParticipantId"]),
                "assignmentKey": f"assignment:{work_id}",
                "acceptedTurnId": "",
                "revision": 0,
                "state": "queued",
            }
            self.items[work_id] = item
            return dict(item), True

    def get(self, work_id: str, *, room_id: str = "") -> dict[str, object]:
        with self.lock:
            item = dict(self.items[work_id])
        if room_id and item["roomId"] != room_id:
            raise ValueError("wrong Room")
        return item

    def list(self, *, room_id: str, limit: int = 100, **_kwargs: object) -> list[dict[str, object]]:
        with self.lock:
            return [
                dict(item)
                for item in self.items.values()
                if item["roomId"] == room_id
            ][:limit]

    def accept_assignment(
        self,
        work_id: str,
        *,
        target_participant_id: str,
        accepted_turn_id: str,
    ) -> dict[str, object]:
        with self.lock:
            item = self.items[work_id]
            item["state"] = "active"
            item["currentOwnerParticipantId"] = target_participant_id
            item["offeredToParticipantId"] = ""
            item["acceptedTurnId"] = accepted_turn_id
            return dict(item)

    def submit_attempt(
        self,
        session_id: str,
        payload: Mapping[str, object],
        *,
        attempt_id: str,
        expected_revision: int,
    ) -> dict[str, object]:
        with self.lock:
            item = self.items[str(payload["workId"])]
            target = self.targets[str(item["currentOwnerParticipantId"])]
            if (
                target["sessionId"] != session_id
                or item["acceptedTurnId"] != attempt_id
                or item["revision"] != expected_revision
            ):
                raise ValueError("stale attempt")
            item["state"] = "review"
            item["resultSummary"] = str(payload["resultSummary"])
            return dict(item)

    def open_for_root(
        self,
        *,
        room_id: str,
        root_turn_id: str,
    ) -> list[dict[str, object]]:
        return [
            item
            for item in self.list(room_id=room_id)
            if item["rootTurnId"] == root_turn_id
            and item["state"] in {"queued", "active", "review", "blocked"}
        ]


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
            room_work=_AuthorityWork(source, targets),
            publish_room_work_activity=lambda *_args, **_kwargs: None,
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
            room_work=_AuthorityWork(source, [target]),
            publish_room_work_activity=lambda *_args, **_kwargs: None,
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
        service._wait_for_child = lambda **_kwargs: {  # type: ignore[method-assign]
            "status": "completed",
            "result": "done",
        }

        service.execute(
            str(source["sessionId"]),
            {
                "op": "delegate",
                "phase": "调查",
                "targetParticipantId": target["id"],
                "task": "只读核对职责边界",
                "expectedOutput": "职责边界证据",
                "acceptanceCriteria": ["给出真实调用链"],
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
            "moderatorParticipantId": participant["id"],
        }
        events = _RoomEvents()
        service = RoomPartnerApplicationService(
            room_work=_AuthorityWork(participant, []),
            publish_room_work_activity=lambda *_args, **_kwargs: None,
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
