from __future__ import annotations

import unittest

from rag_ime.agent_event_projection import AgentEventProjectionService
from rag_ime.agent_protocol import AgentEventEnvelope


class _KernelWithoutBinding:
    mode = "kernel_only"

    @staticmethod
    def session_binding(_session_id: str) -> None:
        return None


class _Rooms:
    @staticmethod
    def participant_for_session(_session_id: str) -> dict[str, object]:
        return {"id": "participant:1", "roomId": "room:1"}


class _Observations:
    def __init__(self) -> None:
        self.count = 0

    def enqueue_agent_event(self, _event: object, *, room_id: str) -> None:
        self.count += 1
        if room_id != "room:1":
            raise AssertionError("participant Room was not preserved")


class _Sessions:
    def __init__(self) -> None:
        self.event_types: list[str] = []

    def record_runtime_event(self, **values: object) -> None:
        self.event_types.append(str(values["event_type"]))


class _ForbiddenLegacyTurns:
    @staticmethod
    def turn_for_event(_event: object) -> str:
        raise AssertionError("kernel event fell through to legacy Room mapping")


class AgentEventProjectionTests(unittest.TestCase):
    def test_transient_fragments_stay_out_of_durable_runtime_events(
        self,
    ) -> None:
        sessions = _Sessions()
        service = AgentEventProjectionService(
            sessions=sessions,
            room_kernel=_KernelWithoutBinding(),
            rooms=_Rooms(),
            agent_blocks=None,
            observations=_Observations(),
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
        )
        for sequence, event_type in enumerate(
            ("text_delta", "tool_progress", "turn_completed"),
            start=1,
        ):
            service.record(
                AgentEventEnvelope(
                    event_id=f"event:{sequence}",
                    session_id="session:1",
                    turn_id="turn:1",
                    sequence=sequence,
                    created_at_ms=sequence,
                    event_type=event_type,
                    payload={},
                    resume_token=f"event:{sequence}",
                )
            )

        self.assertEqual(sessions.event_types, ["turn_completed"])

    def test_trailing_private_delta_after_kernel_revoke_is_not_persisted_or_public(
        self,
    ) -> None:
        observations = _Observations()
        service = AgentEventProjectionService(
            sessions=None,
            room_kernel=_KernelWithoutBinding(),
            rooms=_Rooms(),
            agent_blocks=None,
            observations=observations,
            room_kernel_projection=None,
            room_events=None,
            public_timeline=None,  # type: ignore[arg-type]
            room_turns=_ForbiddenLegacyTurns(),
            append_recent_message=lambda *_args: None,
            record_assistant_evidence=lambda _event: {},
            notify_intercom=lambda: None,
        )
        event = AgentEventEnvelope(
            event_id="event:1",
            session_id="session:1",
            turn_id="private-turn:1",
            sequence=1,
            created_at_ms=1,
            event_type="text_delta",
            payload={"delta": "private tail"},
            resume_token="event:1",
        )

        service.mirror_to_room(event)

        self.assertEqual(observations.count, 0)


if __name__ == "__main__":
    unittest.main()
