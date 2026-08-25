from __future__ import annotations

import unittest
from threading import RLock
from types import SimpleNamespace

from rag_ime.agent_room_intercom_application import (
    RoomIntercomApplicationService,
)


class _ContextRuntime:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    def enqueue(self, **payload: object) -> None:
        self.enqueued.append(dict(payload))


class RoomIntercomApplicationTests(unittest.TestCase):
    def _service(
        self,
        *,
        active_root: str,
    ) -> tuple[
        RoomIntercomApplicationService,
        _ContextRuntime,
        list[dict[str, object]],
    ]:
        source = {
            "id": "room-a:p1",
            "roomId": "room-a",
            "sessionId": "room-a:s1",
            "displayName": "澄·今",
            "status": "active",
        }
        target = {
            "id": "room-a:p2",
            "roomId": "room-a",
            "sessionId": "room-a:s2",
            "displayName": "澄·瞬",
            "status": "active",
        }
        room = {
            "id": "room-a",
            "status": "active",
            "participants": [source, target],
        }
        context = _ContextRuntime()
        deliveries: list[dict[str, object]] = []

        def deliver(
            session_id: str,
            message: str,
            **kwargs: object,
        ) -> tuple[dict[str, object], str, int]:
            deliveries.append(
                {
                    "sessionId": session_id,
                    "message": message,
                    **kwargs,
                }
            )
            return {"turnId": "turn:target"}, "trace:1", 0

        service = RoomIntercomApplicationService(
            sessions=SimpleNamespace(
                get=lambda _session_id: {"status": "active"},
                runtime_binding=lambda _session_id: {"generation": 1},
            ),
            rooms=SimpleNamespace(
                participant_for_session=lambda *_args, **_kwargs: target,
                participant=lambda participant_id: (
                    source if participant_id == source["id"] else target
                ),
                get=lambda _room_id: room,
            ),
            room_work=SimpleNamespace(),
            context_runtime=context,
            room_events=SimpleNamespace(),
            room_turns=SimpleNamespace(
                active_turn=lambda session_id: (
                    (active_root, "room-child:1")
                    if session_id == target["sessionId"]
                    else ("", "")
                ),
            ),
            runtime_provider=lambda: SimpleNamespace(
                runtime_status=lambda: {
                    "status": "busy",
                    "capabilities": {"multiSession": True},
                    "activeSessionIds": [target["sessionId"]],
                }
            ),
            user_priority_sessions=set(),
            turn_lock=RLock(),
            guard_room_session_route=lambda *_args: None,
            runtime_prompt_with_context=deliver,
            room_intercom_prompt=lambda *_args, **_kwargs: "direct peer ask",
            room_participant_prompt=lambda *_args, **_kwargs: "room context",
            publish_room_work_activity=lambda *_args, **_kwargs: None,
        )
        return service, context, deliveries

    def test_active_room_participant_receives_peer_message_as_steer(self) -> None:
        service, context, deliveries = self._service(active_root="root-a")
        item = {
            "id": "room-message:1",
            "roomId": "room-a",
            "kind": "ask",
            "status": "delivering",
            "sourceParticipantId": "room-a:p1",
            "targetParticipantId": "room-a:p2",
            "sourceSessionId": "room-a:s1",
            "targetSessionId": "room-a:s2",
            "content": "请直接确认文件范围",
        }

        self.assertTrue(service.target_idle("room-a:s2"))
        receipt = service.deliver(item)

        self.assertEqual(receipt["delivery"], "steer")
        self.assertEqual(context.enqueued, [])
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["delivery"], "steer")
        self.assertEqual(deliveries[0]["client_message_id"], "room-message:1")
        self.assertEqual(deliveries[0]["transient_context"], "room context")

    def test_unrelated_active_session_remains_busy(self) -> None:
        service, _context, _deliveries = self._service(active_root="")

        self.assertFalse(service.target_idle("room-a:s2"))


if __name__ == "__main__":
    unittest.main()
