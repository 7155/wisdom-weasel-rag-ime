from __future__ import annotations

import unittest

from rag_ime.agent_event_projection import AgentEventProjectionService, room_event_projection
from rag_ime.agent_protocol import AgentEventEnvelope


class _Sessions:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    def record_runtime_event(self, **values: object) -> None:
        self.event_types.append(str(values["event_type"]))


class _Rooms:
    def participant_for_session(self, _session_id: str) -> dict[str, object]:
        return {"id": "participant:1", "roomId": "room:1"}


class _Observations:
    def enqueue_agent_event(self, _event: object, *, room_id: str) -> None:
        if room_id != "room:1":
            raise AssertionError(room_id)


class _RoomEvents:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def publish(self, **values: object) -> None:
        self.items.append(dict(values))


class _Turns:
    def __init__(self, *, child: bool = False) -> None:
        self.child = child

    def private_intercom_for_event(self, _event: object) -> str:
        return ""

    def registered_turn_for_event(self, _event: object) -> str:
        return "room-turn:1"

    def turn_for_event(self, _event: object) -> str:
        return "room-turn:1"

    def is_cancelled(self, _session_id: str, _turn_id: str) -> bool:
        return False

    def dispatch_for_event(self, _event: object) -> str:
        return "room-child:1" if self.child else ""

    def child_for_event(self, _event: object) -> bool:
        return self.child

    def topic_for_turn(self, _turn_id: str) -> str:
        return "topic:1"

    def finish(self, *_args: object) -> None:
        return None


class AgentEventProjectionTests(unittest.TestCase):
    def _service(
        self,
        *,
        child: bool = False,
    ) -> tuple[AgentEventProjectionService, _Sessions, _RoomEvents]:
        sessions = _Sessions()
        room_events = _RoomEvents()
        return (
            AgentEventProjectionService(
                sessions=sessions,
                rooms=_Rooms(),
                agent_blocks=None,
                observations=_Observations(),
                room_events=room_events,
                room_turns=_Turns(child=child),
                append_recent_message=lambda *_args: None,
                record_assistant_evidence=lambda _event: {},
                notify_intercom=lambda: None,
            ),
            sessions,
            room_events,
        )

    def test_transient_fragments_stay_out_of_durable_runtime_events(self) -> None:
        service, sessions, _room_events = self._service()
        for sequence, event_type in enumerate(("text_delta", "tool_progress", "turn_completed"), start=1):
            service.record(AgentEventEnvelope(
                event_id=f"event:{sequence}",
                session_id="session:1",
                turn_id="turn:1",
                sequence=sequence,
                created_at_ms=sequence,
                event_type=event_type,
                payload={},
                resume_token=f"event:{sequence}",
            ))
        self.assertEqual(sessions.event_types, ["turn_completed"])

    def test_room_projection_uses_the_public_session_event_stream(self) -> None:
        service, _sessions, room_events = self._service()
        event = AgentEventEnvelope(
            event_id="event:1",
            session_id="session:1",
            turn_id="turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="text_delta",
            payload={"messageId": "message:1", "delta": "你好"},
            resume_token="event:1",
        )
        service.mirror_to_room(event)
        self.assertEqual(room_events.items[0]["event_type"], "participant_delta")
        self.assertEqual(room_events.items[0]["turn_id"], "room-turn:1")

    def test_tool_failure_maps_to_a_terminal_public_activity(self) -> None:
        event = AgentEventEnvelope(
            event_id="event:tool",
            session_id="session:1",
            turn_id="turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="tool_finished",
            payload={"toolName": "read", "isError": True, "status": "failed"},
            resume_token="event:tool",
        )
        event_type, payload = room_event_projection(event)
        self.assertEqual(event_type, "participant_activity")
        self.assertTrue(payload["isError"])
        self.assertEqual(payload["status"], "failed")

    def test_child_session_terminal_is_activity_not_second_room_final(self) -> None:
        service, _sessions, room_events = self._service(child=True)
        service.mirror_to_room(AgentEventEnvelope(
            event_id="event:child-terminal",
            session_id="session:1",
            turn_id="turn:child",
            sequence=7,
            created_at_ms=7,
            event_type="turn_completed",
            payload={"status": "completed", "summary": "child done"},
            resume_token="event:child-terminal",
        ))
        self.assertEqual(len(room_events.items), 1)
        self.assertEqual(room_events.items[0]["event_type"], "participant_activity")
        data = room_events.items[0]["payload"]["data"]
        self.assertEqual(data["activityKind"], "child")
        self.assertEqual(data["phase"], "completed")
        self.assertEqual(data["dispatchId"], "room-child:1")

    def test_room_partner_public_tool_result_is_bounded(self) -> None:
        event_type, payload = room_event_projection(AgentEventEnvelope(
            event_id="event:partner-tool",
            session_id="session:1",
            turn_id="turn:1",
            sequence=8,
            created_at_ms=8,
            event_type="tool_finished",
            payload={
                "toolName": "room_partner",
                "args": {
                    "op": "delegate",
                    "targetParticipantId": "participant:2",
                    "task": "inspect",
                    "timeoutSeconds": 30,
                },
                "result": {
                    "ok": True,
                    "result": {
                        "operation": "delegate",
                        "status": "completed",
                        "result": "X" * 10_000,
                    },
                },
                "status": "completed",
            },
            resume_token="event:partner-tool",
        ))
        self.assertEqual(event_type, "participant_activity")
        self.assertEqual(payload["arguments"]["timeoutSeconds"], 30)
        self.assertEqual(len(payload["result"]["result"]), 500)


if __name__ == "__main__":
    unittest.main()
