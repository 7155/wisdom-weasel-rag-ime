from __future__ import annotations

import json
import threading
import time
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

    def test_approval_events_are_idempotent_and_carry_tool_identity(self) -> None:
        hub = AgentEventHub()

        required = hub.publish(
            "session-a",
            "approval_required",
            {
                "approvalId": "approval-1",
                "toolCallId": "tool-call-1",
                "state": "pending",
            },
            turn_id="turn-1",
        )
        repeated_required = hub.publish(
            "session-a",
            "approval_required",
            {
                "approvalId": "approval-1",
                "toolCallId": "tool-call-1",
                "state": "pending",
            },
            turn_id="turn-1",
        )
        resolved = hub.publish(
            "session-a",
            "approval_resolved",
            {
                "approvalId": "approval-1",
                "toolCallId": "tool-call-1",
                "state": "rejected",
            },
            turn_id="turn-1",
        )
        repeated_resolved = hub.publish(
            "session-a",
            "approval_resolved",
            {
                "approvalId": "approval-1",
                "toolCallId": "tool-call-1",
                "state": "failed",
            },
            turn_id="turn-1",
        )

        self.assertIs(required, repeated_required)
        self.assertIs(resolved, repeated_resolved)
        self.assertEqual(required.payload["toolCallId"], "tool-call-1")
        self.assertEqual(resolved.payload["toolCallId"], "tool-call-1")
        self.assertEqual(
            [event.event_type for event in hub.replay("session-a")[0]],
            ["approval_required", "approval_resolved"],
        )

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
        recorded = []
        hub = AgentEventHub(replay_limit=32, event_recorder=recorded.append)
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
        self.assertEqual(len(recorded), 40)
        self.assertEqual(hub.replay("session-a", after_event_id="session-a:40"), ([], False))
        recovered = hub.publish("session-a", "status_changed", {"index": "recovered"})
        self.assertEqual(recovered.sequence, 41)
        self.assertEqual(len(recorded), 41)
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

    def test_durable_recorder_precedes_live_delivery_while_background_observers_drain_in_order(
        self,
    ) -> None:
        release_projection = threading.Event()
        recorded: list[str] = []
        projected: list[str] = []

        def record(event: object) -> None:
            recorded.append(event.event_id)

        def observe(event: object) -> None:
            release_projection.wait(2)
            projected.append(event.event_id)

        hub = AgentEventHub(
            event_recorder=record,
            event_observer=observe,
            background_projection=True,
        )
        stream = hub.subscribe("session-a")
        self.assertEqual(next(stream), b": connected\n\n")

        started_at = time.monotonic()
        first = hub.publish("session-a", "tool_started")
        second = hub.publish("session-a", "tool_finished")
        self.assertLess(time.monotonic() - started_at, 0.25)
        self.assertEqual(recorded, [first.event_id, second.event_id])
        self.assertEqual(_sse_payload(next(stream))["eventId"], first.event_id)
        self.assertEqual(_sse_payload(next(stream))["eventId"], second.event_id)
        self.assertEqual(projected, [])

        release_projection.set()
        self.assertTrue(hub.flush(timeout=2))
        self.assertEqual(projected, [first.event_id, second.event_id])
        self.assertTrue(hub.close(timeout=2))
        stream.close()

    def test_recorder_failure_never_reaches_replay_or_live_and_does_not_reuse_a_committed_id(
        self,
    ) -> None:
        durable_sequence = 0
        fail = True

        def record(event: object) -> None:
            nonlocal durable_sequence
            durable_sequence = event.sequence
            if fail:
                raise RuntimeError("durable recorder unavailable")

        hub = AgentEventHub(
            sequence_loader=lambda _session_id: durable_sequence,
            event_recorder=record,
        )
        stream = hub.subscribe("session-a")
        self.assertEqual(next(stream), b": connected\n\n")

        with self.assertRaisesRegex(RuntimeError, "durable recorder unavailable"):
            hub.publish("session-a", "tool_started")
        self.assertEqual(hub.replay("session-a"), ([], False))

        fail = False
        recovered = hub.publish("session-a", "tool_finished")
        self.assertEqual(recovered.sequence, 2)
        self.assertEqual(_sse_payload(next(stream))["eventId"], recovered.event_id)
        stream.close()

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
