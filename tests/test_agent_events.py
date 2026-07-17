from __future__ import annotations

import json
import unittest

from rag_ime.agent_events import AgentEventHub


class AgentEventHubTests(unittest.TestCase):
    def test_sequences_are_per_session_and_replay_is_idempotent(self) -> None:
        recorded = []
        hub = AgentEventHub(event_recorder=recorded.append)

        first = hub.publish("session-a", "status_changed", {"status": "busy"}, turn_id="turn-1")
        second = hub.publish("session-a", "text_delta", {"delta": "你好"}, turn_id="turn-1")
        other = hub.publish("session-b", "status_changed", {"status": "idle"})

        self.assertEqual((first.sequence, second.sequence, other.sequence), (1, 2, 1))
        replay, gap = hub.replay("session-a", after_event_id=first.event_id)
        self.assertFalse(gap)
        self.assertEqual([item.event_id for item in replay], [second.event_id])
        self.assertEqual(len(recorded), 3)

    def test_subscribe_replays_then_streams_live_event(self) -> None:
        hub = AgentEventHub()
        first = hub.publish("session-a", "status_changed", {"status": "busy"})
        stream = hub.subscribe("session-a", after_event_id="")

        self.assertEqual(next(stream), b": connected\n\n")
        replay = _sse_payload(next(stream))
        self.assertEqual(replay["eventId"], first.event_id)
        self.assertEqual(hub.subscriber_count("session-a"), 1)

        live = hub.publish("session-a", "turn_completed", {"ok": True})
        self.assertEqual(_sse_payload(next(stream))["eventId"], live.event_id)
        stream.close()
        self.assertEqual(hub.subscriber_count(), 0)

    def test_replay_gap_emits_snapshot_required(self) -> None:
        hub = AgentEventHub(replay_limit=32)
        for index in range(40):
            hub.publish("session-a", "status_changed", {"index": index})

        replay, gap = hub.replay("session-a", after_event_id="session-a:1")
        self.assertTrue(gap)
        self.assertEqual(replay, [])

        stream = hub.subscribe("session-a", after_event_id="session-a:1")
        self.assertEqual(next(stream), b": connected\n\n")
        control = _sse_payload(next(stream))
        self.assertEqual(control["eventType"], "snapshot_required")
        self.assertEqual(control["payload"]["reason"], "event_replay_gap")
        stream.close()

    def test_invalid_or_future_resume_token_requires_snapshot(self) -> None:
        hub = AgentEventHub(sequence_loader=lambda _session: 7)
        for token in ("other:7", "session-a:not-an-int", "session-a:8"):
            with self.subTest(token=token):
                replay, gap = hub.replay("session-a", after_event_id=token)
                self.assertEqual(replay, [])
                self.assertTrue(gap)

    def test_secondary_event_observer_cannot_break_primary_session_stream(self) -> None:
        observed = []
        hub = AgentEventHub(event_observer=observed.append)
        event = hub.publish("session-a", "status_changed", {"status": "busy"})
        self.assertEqual(observed, [event])

        failing = AgentEventHub(event_observer=lambda _event: (_ for _ in ()).throw(RuntimeError("room down")))
        published = failing.publish("session-a", "status_changed", {"status": "busy"})
        self.assertEqual(published.sequence, 1)

    def test_projection_invalidation_discards_old_replay_and_refreshes_live_subscribers(self) -> None:
        recorded = []
        hub = AgentEventHub(event_recorder=recorded.append)
        old = hub.publish("session-a", "message_completed", {"message": {"id": "old"}})
        stream = hub.subscribe("session-a")
        self.assertEqual(next(stream), b": connected\n\n")
        self.assertEqual(_sse_payload(next(stream))["eventId"], old.event_id)

        invalidation = hub.invalidate_projection("session-a")
        control = _sse_payload(next(stream))
        self.assertEqual(control["eventId"], invalidation.event_id)
        self.assertEqual(control["eventType"], "snapshot_required")
        self.assertEqual(control["payload"]["reason"], "session_rewritten")

        current = hub.publish("session-a", "message_completed", {"message": {"id": "new"}})
        replay, gap = hub.replay("session-a")
        self.assertFalse(gap)
        self.assertEqual([event.event_id for event in replay], [current.event_id])
        self.assertEqual(recorded, [old, invalidation, current])
        stream.close()


def _sse_payload(chunk: bytes) -> dict[str, object]:
    data_line = next(line for line in chunk.decode("utf-8").splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    unittest.main()
