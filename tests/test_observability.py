from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.observability import ObservationHub


class ObservationHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-observation-")
        self.hub = ObservationHub(Path(self.temporary.name) / "rag-ime.sqlite")

    def tearDown(self) -> None:
        self.hub.close()
        self.temporary.cleanup()

    def test_agent_tool_projection_persists_metadata_without_args_or_results(self) -> None:
        self.hub.observe_agent_event(
            AgentEventEnvelope(
                event_id="session-1:1",
                session_id="session-1",
                turn_id="turn-1",
                sequence=1,
                created_at_ms=100,
                event_type="tool_finished",
                payload={
                    "toolCallId": "tool-call-1",
                    "toolName": "ime.memory",
                    "args": {"prompt": "DO_NOT_PERSIST", "eventIds": [1, 2]},
                    "result": {"content": "PRIVATE_RESULT", "count": 2},
                    "isError": False,
                },
                resume_token="session-1:1",
            ),
            room_id="room-1",
        )

        snapshot = self.hub.snapshot()

        self.assertEqual(snapshot["counts"]["total"], 1)
        event = snapshot["items"][0]
        self.assertEqual(event["category"], "tool")
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["roomId"], "room-1")
        self.assertEqual(event["metrics"]["argumentFieldCount"], 2)
        self.assertEqual(event["metrics"]["resultFieldCount"], 2)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("DO_NOT_PERSIST", serialized)
        self.assertNotIn("PRIVATE_RESULT", serialized)
        self.assertNotIn('"args"', serialized)
        self.assertNotIn('"result"', serialized)

    def test_room_intercom_projection_never_stores_private_message_content(self) -> None:
        self.hub.observe_room_event(
            {
                "eventId": "room-1:3",
                "roomId": "room-1",
                "turnId": "intercom-1",
                "participantId": "participant-a",
                "sourceSessionId": "session-a",
                "eventType": "participant_activity",
                "createdAtMs": 200,
                "payload": {
                    "activityKind": "intercom",
                    "phase": "delivered",
                    "message": {
                        "id": "intercom-1",
                        "kind": "ask",
                        "sourceParticipantId": "participant-a",
                        "targetParticipantId": "participant-b",
                        "status": "delivered",
                        "content": "PRIVATE_INTERCOM_BODY",
                    },
                },
            }
        )

        event = self.hub.snapshot()["items"][0]

        self.assertEqual(event["category"], "intercom")
        self.assertEqual(event["status"], "completed")
        self.assertEqual(event["attributes"]["rawMessageStored"], False)
        serialized = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("PRIVATE_INTERCOM_BODY", serialized)
        self.assertNotIn('"content"', serialized)

    def test_active_rag_projection_uses_fingerprint_counts_even_when_source_trace_has_text(self) -> None:
        record = {
            "timestampMs": 300,
            "sessionId": "active-rag-1",
            "status": "completed",
            "elapsedMs": 88,
            "privacy": {"rawTextIncluded": True},
            "request": {
                "frontAppBundleId": "com.example.editor",
                "intent": "rewrite",
                "selectedText": {"chars": 14, "text": "PRIVATE_SELECTION"},
                "currentContext": {"chars": 80, "text": "PRIVATE_CONTEXT"},
                "providedEvidenceCount": 2,
            },
            "retrieval": {
                "evidenceCount": 4,
                "evidence": [{"text": {"text": "PRIVATE_EVIDENCE"}}],
            },
            "model": {"request": {"messages": ["PRIVATE_PROMPT"]}},
            "generation": {
                "candidateCount": 1,
                "candidates": [{"text": {"text": "PRIVATE_CANDIDATE"}}],
            },
        }
        for phase in ("started", "retrieval_complete", "completed"):
            self.hub.observe_active_rag_record({**record, "phase": phase})

        snapshot = self.hub.snapshot({"traceId": "trace:active-rag:active-rag-1"})

        self.assertEqual(snapshot["counts"]["total"], 3)
        context = next(item for item in snapshot["items"] if item["category"] == "context")
        self.assertEqual(context["metrics"]["selectedChars"], 14)
        self.assertEqual(context["metrics"]["contextChars"], 80)
        self.assertEqual(context["attributes"]["rawTextStored"], False)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "PRIVATE_SELECTION",
            "PRIVATE_CONTEXT",
            "PRIVATE_EVIDENCE",
            "PRIVATE_PROMPT",
            "PRIVATE_CANDIDATE",
        ):
            self.assertNotIn(secret, serialized)

    def test_stale_active_rag_generation_is_reported_as_cancelled(self) -> None:
        self.hub.observe_active_rag_record(
            {
                "timestampMs": 350,
                "sessionId": "active-rag-stale",
                "status": "stale_dropped",
                "phase": "stale_dropped",
            }
        )

        event = self.hub.snapshot({"sessionId": "active-rag-stale"})["items"][0]

        self.assertEqual(event["status"], "cancelled")
        self.assertEqual(event["summary"], "闪电联想生成已取消")

    def test_snapshot_filters_and_sse_replay_use_global_resume_sequence(self) -> None:
        self.hub.emit_memory_event(
            phase="draft_ready",
            status="waiting",
            summary="记忆草案等待审阅",
            run_id="run-1",
        )
        self.hub.emit(
            traceId="trace:turn:1",
            spanId="span:turn:1",
            category="agent",
            phase="turn_completed",
            name="turn_completed",
            status="completed",
            summary="Agent 回合已完成",
            createdAtMs=400,
            privacyClass="metadata",
        )

        memory_snapshot = self.hub.snapshot({"category": "memory"})
        self.assertEqual(memory_snapshot["counts"]["total"], 1)
        self.assertEqual(memory_snapshot["items"][0]["runId"], "run-1")
        self.assertGreater(memory_snapshot["items"][0]["createdAtMs"], 1_000_000_000_000)

        stream = self.hub.subscribe(
            after_event_id="observation:1",
            filters={"category": "agent"},
            heartbeat_seconds=0.01,
        )
        self.assertEqual(next(stream), b": connected\n\n")
        replay = next(stream).decode("utf-8")
        stream.close()
        self.assertIn("event: observation", replay)
        self.assertIn('"category":"agent"', replay)
        self.assertIn("id: observation:2", replay)

    def test_invalid_or_expired_resume_token_requests_a_fresh_snapshot(self) -> None:
        self.hub.emit_memory_event(
            phase="draft_ready",
            status="waiting",
            summary="记忆草案等待审阅",
            run_id="run-2",
        )

        stream = self.hub.subscribe(
            after_event_id="not-an-observation-token",
            heartbeat_seconds=0.01,
        )
        self.assertEqual(next(stream), b": connected\n\n")
        required = next(stream).decode("utf-8")
        stream.close()

        self.assertIn("event: snapshot_required", required)
        self.assertIn('"eventType":"snapshot_required"', required)
        self.assertIn('"reason":"event_replay_gap"', required)

    def test_async_projection_queue_flushes_without_entering_primary_event_path(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-async:1",
                session_id="session-async",
                turn_id="turn-async",
                sequence=1,
                created_at_ms=500,
                event_type="status_changed",
                payload={"status": "analyzing"},
                resume_token="session-async:1",
            )
        )

        self.assertTrue(self.hub.flush())
        event = self.hub.snapshot({"sessionId": "session-async"})["items"][0]
        self.assertEqual(event["summary"], "Agent 正在分析")
        self.assertEqual(event["category"], "runtime")

    def test_async_ingress_discards_sensitive_payloads_before_projection(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-private:1",
                session_id="session-private",
                turn_id="turn-private",
                sequence=1,
                created_at_ms=600,
                event_type="tool_finished",
                payload={
                    "toolCallId": "tool-private",
                    "toolName": "workspace_shell",
                    "args": {"command": "PRIVATE_COMMAND"},
                    "result": {"content": "PRIVATE_RESULT"},
                },
                resume_token="session-private:1",
            )
        )
        self.hub.enqueue_room_event(
            {
                "eventId": "room-private:1",
                "roomId": "room-private",
                "eventType": "participant_activity",
                "createdAtMs": 601,
                "payload": {
                    "activityKind": "intercom",
                    "phase": "delivered",
                    "message": {
                        "id": "intercom-private",
                        "status": "delivered",
                        "content": "PRIVATE_INTERCOM",
                    },
                },
            }
        )
        self.hub.enqueue_active_rag_record(
            {
                "timestampMs": 602,
                "phase": "started",
                "sessionId": "active-rag-private",
                "request": {
                    "selectedText": {"chars": 12, "text": "PRIVATE_SELECTION"},
                    "currentContext": {"chars": 24, "text": "PRIVATE_CONTEXT"},
                },
            }
        )

        self.assertTrue(self.hub.flush())
        serialized = json.dumps(self.hub.snapshot(), ensure_ascii=False)
        for secret in (
            "PRIVATE_COMMAND",
            "PRIVATE_RESULT",
            "PRIVATE_INTERCOM",
            "PRIVATE_SELECTION",
            "PRIVATE_CONTEXT",
        ):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
