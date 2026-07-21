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


class _ForbiddenLegacyTurns:
    @staticmethod
    def turn_for_event(_event: object) -> str:
        raise AssertionError("kernel event fell through to legacy Room mapping")


class AgentEventProjectionTests(unittest.TestCase):
    def test_trailing_private_event_after_kernel_revoke_is_not_a_public_turn(self) -> None:
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

        self.assertEqual(observations.count, 1)


if __name__ == "__main__":
    unittest.main()
