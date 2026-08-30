from __future__ import annotations

import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.observability import ObservationConflict, ObservationHub
from rag_ime.trace_adapters import envelope_from_observations


class ObservationHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-observation-")
        self.hub = ObservationHub(Path(self.temporary.name) / "rag-ime.sqlite")

    def tearDown(self) -> None:
        self.hub.close()
        self.temporary.cleanup()

    def test_explicit_event_id_exact_replay_is_idempotent_at_store_and_hub(self) -> None:
        values = {
            "eventId": "observation:exact-replay-store",
            "traceId": "trace:exact-replay",
            "spanId": "span:exact-replay",
            "category": "agent",
            "phase": "completed",
            "name": "exact_replay",
            "status": "completed",
            "summary": "stable event",
            "createdAtMs": 10,
            "startedAtMs": 10,
            "endedAtMs": 10,
            "durationMs": 0,
            "privacyClass": "metadata",
            "metrics": {"count": 1},
            "attributes": {"stable": True},
            "refs": [],
        }

        first = self.hub.store.append(values)
        second = self.hub.store.append(dict(values))
        self.assertEqual(first, second)
        self.assertEqual(self.hub.snapshot()["counts"]["total"], 1)

        hub_values = {**values, "eventId": "observation:exact-replay-hub"}
        subscriber = queue.Queue()
        with self.hub._lock:
            subscriber_id = self.hub._next_subscriber_id
            self.hub._next_subscriber_id += 1
            self.hub._subscribers[subscriber_id] = (subscriber, {})
        try:
            emitted = self.hub.emit(**hub_values)
            replayed = self.hub.emit(**dict(hub_values))
            self.assertEqual(emitted, replayed)
            self.assertEqual(subscriber.get_nowait(), emitted)
            with self.assertRaises(queue.Empty):
                subscriber.get_nowait()
            self.assertEqual(self.hub.snapshot()["counts"]["total"], 2)
        finally:
            with self.hub._lock:
                self.hub._subscribers.pop(subscriber_id, None)

    def test_explicit_event_id_replay_ignores_json_key_order_in_legacy_rows(self) -> None:
        values = {
            "eventId": "observation:legacy-json-order",
            "traceId": "trace:legacy-json-order",
            "spanId": "span:legacy-json-order",
            "category": "agent",
            "phase": "completed",
            "name": "legacy_json_order",
            "status": "completed",
            "summary": "stable event",
            "createdAtMs": 12,
            "startedAtMs": 12,
            "endedAtMs": 12,
            "durationMs": 0,
            "privacyClass": "metadata",
            "metrics": {"eventCount": 2, "count": 1},
            "attributes": {"project": "sgg", "app": "paw"},
            "refs": [],
        }

        first = self.hub.store.append(values)
        with self.hub.store._connect() as conn:
            conn.execute(
                """
                UPDATE agent_observation_events
                SET metrics_json = ?, attributes_json = ?
                WHERE event_id = ?
                """,
                (
                    '{"count":1,"eventCount":2}',
                    '{"app":"paw","project":"sgg"}',
                    values["eventId"],
                ),
            )

        replay = self.hub.store.append(
            {
                **values,
                "metrics": {"count": 1, "eventCount": 2},
                "attributes": {"app": "paw", "project": "sgg"},
            }
        )
        self.assertEqual(first, replay)

    def test_explicit_event_id_rebound_to_different_persisted_fields_fails(self) -> None:
        values = {
            "eventId": "observation:identity-rebound",
            "traceId": "trace:identity-rebound",
            "spanId": "span:identity-rebound",
            "category": "agent",
            "phase": "completed",
            "name": "identity_rebound",
            "status": "completed",
            "summary": "stable event",
            "createdAtMs": 11,
            "startedAtMs": 11,
            "endedAtMs": 11,
            "durationMs": 0,
            "privacyClass": "metadata",
            "metrics": {},
            "attributes": {},
            "refs": [],
        }
        self.hub.store.append(values)

        with self.assertRaisesRegex(ObservationConflict, "different persisted fields"):
            self.hub.store.append({**values, "status": "failed"})
        with self.assertRaisesRegex(ObservationConflict, "different persisted fields"):
            self.hub.emit(**{**values, "status": "failed"})

    def test_direct_emit_public_projection_blocks_private_metadata_in_snapshot_and_trace(self) -> None:
        valid_artifact = {
            "artifactId": "artifact:public-eval",
            "kind": "eval",
            "mediaType": "application/json",
            "sha256": "a" * 64,
            "byteSize": 12,
            "recordCount": 1,
        }
        valid_evidence = {
            "evidenceId": "claim:public-1",
            "sourceKind": "knowledge",
            "sourceRef": "knowledge://sales/revenue",
            "sourceLane": "participant_private",
            "disposition": "included",
            "scores": {"score": 0.0, "confidence": -0.25},
            "rankBefore": 2,
            "rankAfter": 1,
            "omissionReason": "",
            "text": "PRIVATE_TRACE_TEXT",
        }
        self.hub.emit(
            eventId="observation:direct-public-boundary",
            traceId="trace:direct-public-boundary",
            spanId="span:direct-public-boundary",
            category="retrieval",
            phase="retrieval_output",
            name="direct_public_boundary",
            status="completed",
            summary="公开摘要",
            createdAtMs=10,
            startedAtMs=10,
            endedAtMs=10,
            durationMs=0,
            privacyClass="metadata",
            metrics={
                "evidenceCount": 1,
                "result": "PRIVATE_RESULT",
                "privateMetric": "PRIVATE_METRIC",
                "url": "https://PRIVATE_URL",
                "nested": {"sentinel": "PRIVATE_NESTED"},
            },
            attributes={
                "sourceKind": "knowledge",
                "evidenceStage": "retrieval_output",
                "targetParticipantId": "participant:one",
                "prompt": "PRIVATE_PROMPT",
                "path": "/PRIVATE_PATH",
                "privateAttribute": "PRIVATE_ATTRIBUTE",
                "traceEvidence": [
                    valid_evidence,
                    {
                        **valid_evidence,
                        "evidenceId": "claim:private-http",
                        "sourceRef": "https://PRIVATE_EVIDENCE_URL",
                    },
                    {
                        **valid_evidence,
                        "evidenceId": "claim:private-path",
                        "sourceRef": "/PRIVATE_EVIDENCE_PATH",
                    },
                    {
                        **valid_evidence,
                        "evidenceId": "claim:private-scheme",
                        "sourceRef": "custom://PRIVATE_EVIDENCE_SCHEME",
                    },
                ],
                "artifactRefs": [
                    valid_artifact,
                    {
                        **valid_artifact,
                        "artifactId": "artifact:https://PRIVATE_ARTIFACT_URL",
                    },
                ],
            },
            refs=[
                {
                    "kind": "private",
                    "id": "https://PRIVATE_REF_URL",
                    "label": "https://PRIVATE_REF_LABEL",
                },
                {"kind": "private", "id": "/PRIVATE_REF_PATH", "label": "/PRIVATE_REF_PATH"},
            ],
        )

        snapshot = self.hub.snapshot({"traceId": "trace:direct-public-boundary"})
        event = snapshot["items"][0]
        serialized = json.dumps(snapshot, ensure_ascii=False)

        self.assertEqual(event["summary"], "公开摘要")
        self.assertEqual(event["attributes"]["targetParticipantId"], "participant:one")
        self.assertEqual(len(event["attributes"]["traceEvidence"]), 1)
        self.assertEqual(len(event["attributes"]["artifactRefs"]), 1)
        for secret in (
            "PRIVATE_RESULT",
            "PRIVATE_METRIC",
            "PRIVATE_NESTED",
            "PRIVATE_URL",
            "PRIVATE_PROMPT",
            "PRIVATE_PATH",
            "PRIVATE_ATTRIBUTE",
            "PRIVATE_TRACE_TEXT",
            "PRIVATE_EVIDENCE_URL",
            "PRIVATE_EVIDENCE_PATH",
            "PRIVATE_EVIDENCE_SCHEME",
            "PRIVATE_ARTIFACT_URL",
            "PRIVATE_REF_URL",
            "PRIVATE_REF_PATH",
            "PRIVATE_REF_LABEL",
        ):
            self.assertNotIn(secret, serialized)

        trace = envelope_from_observations(snapshot["items"]).to_dict()
        trace_serialized = json.dumps(trace, ensure_ascii=False)
        for secret in (
            "PRIVATE_RESULT",
            "PRIVATE_METRIC",
            "PRIVATE_NESTED",
            "PRIVATE_URL",
            "PRIVATE_PROMPT",
            "PRIVATE_PATH",
            "PRIVATE_ATTRIBUTE",
            "PRIVATE_TRACE_TEXT",
            "PRIVATE_EVIDENCE_URL",
            "PRIVATE_EVIDENCE_PATH",
            "PRIVATE_EVIDENCE_SCHEME",
            "PRIVATE_ARTIFACT_URL",
            "PRIVATE_REF_URL",
            "PRIVATE_REF_PATH",
            "PRIVATE_REF_LABEL",
        ):
            self.assertNotIn(secret, trace_serialized)
        self.assertEqual(trace["evidence"][0]["sourceRef"], "knowledge://sales/revenue")
        self.assertEqual(trace["artifacts"][0]["artifactId"], "artifact:public-eval")

    def test_direct_emit_preserves_valid_typed_evidence_and_artifact_refs(self) -> None:
        artifact = {
            "artifactId": "artifact:fixture-eval",
            "kind": "eval",
            "mediaType": "application/json",
            "sha256": "b" * 64,
            "byteSize": 0,
            "recordCount": 0,
        }
        evidence = {
            "evidenceId": "memory:7",
            "sourceKind": "memory",
            "sourceRef": "fixture://memory/sgg/policy",
            "sourceLane": "bm25_raw",
            "disposition": "included",
            "scores": {"score": -0.5, "confidence": 0.0},
            "rankBefore": 3,
            "rankAfter": 1,
            "omissionReason": "",
        }
        self.hub.emit(
            eventId="observation:direct-valid-special-channels",
            traceId="trace:direct-valid-special-channels",
            spanId="span:direct-valid-special-channels",
            category="retrieval",
            phase="retrieval_output",
            name="direct_valid_special_channels",
            status="completed",
            summary="合法公开事件",
            createdAtMs=20,
            startedAtMs=20,
            endedAtMs=20,
            durationMs=0,
            metrics={
                "evidenceCount": 0,
                "count": 0,
                "eventCount": 2,
                "changeCount": 1,
                "reused": False,
            },
            attributes={
                "app": "paw",
                "evidenceStage": "retrieval_output",
                "project": "sgg",
                "traceEvidence": [evidence],
                "artifactRefs": [artifact],
            },
            refs=[],
        )

        event = self.hub.snapshot({"traceId": "trace:direct-valid-special-channels"})["items"][0]
        trace = envelope_from_observations([event]).to_dict()

        self.assertEqual(
            event["metrics"],
            {
                "evidenceCount": 0,
                "count": 0,
                "eventCount": 2,
                "changeCount": 1,
                "reused": False,
            },
        )
        self.assertEqual(event["attributes"]["traceEvidence"], [evidence])
        self.assertEqual(event["attributes"]["artifactRefs"], [artifact])
        self.assertEqual(trace["evidence"][0]["sourceRef"], "fixture://memory/sgg/policy")
        self.assertEqual(trace["evidence"][0]["scores"], {"score": -0.5, "confidence": 0.0})
        self.assertEqual(trace["artifacts"][0], artifact)
        span = trace["spans"][0]
        self.assertEqual(
            span["metrics"],
            {
                "evidenceCount": 0,
                "count": 0,
                "eventCount": 2,
                "changeCount": 1,
                "reused": False,
            },
        )
        self.assertEqual(span["attributes"]["app"], "paw")
        self.assertEqual(span["attributes"]["project"], "sgg")

    def test_public_reason_is_closed_to_known_tokens(self) -> None:
        for index, reason in enumerate(("threshold", "event_replay_gap", "PRIVATE_REASON")):
            event = self.hub.emit(
                eventId=f"observation:reason:{index}",
                traceId="trace:reason-boundary",
                spanId=f"span:reason:{index}",
                category="context",
                phase="observed",
                name="reason_boundary",
                status="info",
                summary="公开状态",
                createdAtMs=40 + index,
                attributes={"reason": reason},
            )
            if reason in {"threshold", "event_replay_gap"}:
                self.assertEqual(event["attributes"]["reason"], reason)
            else:
                self.assertNotIn("reason", event["attributes"])
                self.assertNotIn(reason, json.dumps(event, ensure_ascii=False))

    def test_snapshot_reprojects_legacy_journal_metadata_before_publication(self) -> None:
        event = self.hub.emit(
            eventId="observation:legacy-public-boundary",
            traceId="trace:legacy-public-boundary",
            spanId="span:legacy-public-boundary",
            category="system",
            phase="legacy",
            name="legacy_public_boundary",
            status="info",
            summary="公开摘要",
            createdAtMs=30,
            startedAtMs=30,
            privacyClass="metadata",
        )
        with self.hub.store._connect() as conn:
            conn.execute(
                """
                UPDATE agent_observation_events
                SET metrics_json = ?, attributes_json = ?, refs_json = ?
                WHERE event_id = ?
                """,
                (
                    json.dumps({"result": "PRIVATE_LEGACY_RESULT"}),
                    json.dumps(
                        {
                            "prompt": "PRIVATE_LEGACY_PROMPT",
                            "traceEvidence": [
                                {
                                    "evidenceId": "legacy:private",
                                    "sourceKind": "knowledge",
                                    "sourceRef": "https://PRIVATE_LEGACY_URL",
                                }
                            ],
                        }
                    ),
                    json.dumps(
                        [
                            {
                                "kind": "legacy",
                                "id": "/PRIVATE_LEGACY_PATH",
                                "label": "PRIVATE_LEGACY_LABEL",
                            }
                        ]
                    ),
                    event["eventId"],
                ),
            )

        snapshot = self.hub.snapshot({"traceId": "trace:legacy-public-boundary"})
        public_event = snapshot["items"][0]
        serialized = json.dumps(public_event, ensure_ascii=False)

        self.assertEqual(public_event["metrics"], {})
        self.assertEqual(public_event["attributes"], {"traceEvidence": []})
        self.assertEqual(public_event["refs"], [])
        for secret in (
            "PRIVATE_LEGACY_RESULT",
            "PRIVATE_LEGACY_PROMPT",
            "PRIVATE_LEGACY_URL",
            "PRIVATE_LEGACY_PATH",
            "PRIVATE_LEGACY_LABEL",
        ):
            self.assertNotIn(secret, serialized)

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

    def test_browser_lifecycle_enters_common_trace_without_page_or_failure_text(self) -> None:
        base = {
            "commandId": "bcmd_trace_1",
            "deviceId": "chrome-test",
            "sessionId": "session-browser",
            "action": "navigate",
            "createdAtMs": 100,
            "claimedAtMs": None,
            "completedAtMs": None,
            "durationMs": None,
            "failureRecorded": False,
            "url": "https://private.example/account",
            "result": {"markdown": "PRIVATE_PAGE"},
            "failureReason": "PRIVATE_FAILURE",
        }
        self.hub.enqueue_browser_record({**base, "status": "queued"})
        self.hub.enqueue_browser_record({**base, "status": "claimed", "claimedAtMs": 110})
        self.hub.enqueue_browser_record({
            **base,
            "status": "completed",
            "claimedAtMs": 110,
            "completedAtMs": 125,
            "durationMs": 25,
        })
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"traceId": "trace:browser:command:bcmd_trace_1"})
        self.assertEqual(snapshot["counts"]["total"], 3)
        trace = envelope_from_observations(snapshot["items"]).to_dict()
        self.assertEqual(trace["sourceKind"], "browser_control")
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["spans"][0]["durationMs"], 25)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("private.example", serialized)
        self.assertNotIn("PRIVATE_PAGE", serialized)
        self.assertNotIn("PRIVATE_FAILURE", serialized)

    def test_agent_model_context_and_cache_telemetry_survives_without_raw_prompts(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-telemetry:1",
                session_id="session-telemetry",
                turn_id="turn-telemetry",
                sequence=1,
                created_at_ms=150,
                event_type="message_completed",
                payload={
                    "message": {
                        "role": "assistant",
                        "provider": "openai",
                        "model": "gpt-test",
                        "usage": {
                            "input": 120,
                            "output": 30,
                            "cacheRead": 80,
                            "cacheWrite": 5,
                            "totalTokens": 235,
                        },
                        "blocks": [{"text": "PRIVATE_ASSISTANT_BODY"}],
                    },
                    "telemetry": {
                        "model": {
                            "provider": "openai",
                            "id": "gpt-test",
                            "name": "GPT Test",
                        },
                        "context": {
                            "tokens": 4_000,
                            "contextWindow": 16_000,
                            "percent": 25,
                            "remainingTokens": 12_000,
                            "compactAtTokens": 14_000,
                            "tokensUntilCompact": 10_000,
                        },
                        "latestUsage": {
                            "input": 120,
                            "output": 30,
                            "cacheRead": 80,
                            "cacheWrite": 5,
                            "totalTokens": 235,
                        },
                        "latestCacheHitPercent": 39.02,
                        "isCompacting": False,
                        "compactionCount": 2,
                        "providerRequest": {"prompt": "PRIVATE_PROVIDER_PROMPT"},
                    },
                },
                resume_token="session-telemetry:1",
            )
        )
        self.assertTrue(self.hub.flush())

        event = self.hub.snapshot({"sessionId": "session-telemetry"})["items"][0]

        self.assertEqual(event["attributes"]["provider"], "openai")
        self.assertEqual(event["attributes"]["model"], "gpt-test")
        self.assertEqual(event["metrics"]["contextTokens"], 4_000)
        self.assertEqual(event["metrics"]["contextWindowTokens"], 16_000)
        self.assertEqual(event["metrics"]["inputTokens"], 120)
        self.assertEqual(event["metrics"]["cacheReadTokens"], 80)
        self.assertAlmostEqual(event["metrics"]["cacheHitPercent"], 39.02)
        self.assertEqual(event["metrics"]["compactionCount"], 2)
        serialized = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("PRIVATE_ASSISTANT_BODY", serialized)
        self.assertNotIn("PRIVATE_PROVIDER_PROMPT", serialized)
        self.assertNotIn("providerRequest", serialized)

    def test_provider_request_receipt_is_a_metadata_only_common_trace_span(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-provider-trace:1",
                session_id="session-provider-trace",
                turn_id="turn-provider-trace",
                sequence=1,
                created_at_ms=200,
                event_type="provider_request_completed",
                payload={
                    "requestId": "turn-provider-trace:provider:assistant-1",
                    "provider": "openai",
                    "model": "gpt-test",
                    "startedAtMs": 100,
                    "durationMs": 100,
                    "usage": {"input": 12, "output": 4, "totalTokens": 16},
                    "prompt": "PRIVATE_PROVIDER_PROMPT",
                    "completion": "PRIVATE_PROVIDER_COMPLETION",
                },
                resume_token="session-provider-trace:1",
            )
        )
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-provider-trace:2",
                session_id="session-provider-trace",
                turn_id="turn-provider-trace",
                sequence=2,
                created_at_ms=350,
                event_type="provider_request_failed",
                payload={
                    "requestId": "turn-provider-trace:provider:assistant-2",
                    "provider": "openai",
                    "model": "gpt-test",
                    "startedAtMs": 300,
                    "durationMs": 50,
                    "error": "PRIVATE_PROVIDER_ERROR",
                },
                resume_token="session-provider-trace:2",
            )
        )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"sessionId": "session-provider-trace"})
        self.assertEqual(snapshot["counts"]["total"], 2)
        self.assertEqual(
            [item["name"] for item in snapshot["items"]],
            ["provider.request", "provider.request"],
        )
        completed = next(
            item for item in snapshot["items"] if item["status"] == "completed"
        )
        self.assertEqual(
            {item["status"] for item in snapshot["items"]},
            {"completed", "failed"},
        )
        self.assertEqual(completed["durationMs"], 100)
        self.assertEqual(completed["metrics"]["totalTokens"], 16)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("PRIVATE_PROVIDER_PROMPT", serialized)
        self.assertNotIn("PRIVATE_PROVIDER_COMPLETION", serialized)
        self.assertNotIn("PRIVATE_PROVIDER_ERROR", serialized)

    def test_compaction_projection_reports_context_transition_without_error_text(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-compaction:1",
                session_id="session-compaction",
                turn_id="turn-compaction",
                sequence=1,
                created_at_ms=175,
                event_type="compaction_completed",
                payload={
                    "reason": "threshold",
                    "tokensBefore": 14_200,
                    "estimatedTokensAfter": 3_200,
                    "error": "PRIVATE_RUNTIME_ERROR",
                    "willRetry": True,
                },
                resume_token="session-compaction:1",
            )
        )
        self.assertTrue(self.hub.flush())

        event = self.hub.snapshot({"sessionId": "session-compaction"})["items"][0]

        self.assertEqual(event["category"], "context")
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["metrics"]["tokensBefore"], 14_200)
        self.assertEqual(event["metrics"]["estimatedTokensAfter"], 3_200)
        self.assertEqual(event["attributes"]["willRetry"], True)
        self.assertNotIn("PRIVATE_RUNTIME_ERROR", json.dumps(event, ensure_ascii=False))

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

    def test_room_work_intercom_child_and_receipt_preserve_safe_work_item_id(self) -> None:
        events = (
            {
                "eventId": "room-correlation:work",
                "roomId": "room-correlation",
                "turnId": "room-turn:work",
                "eventType": "participant_activity",
                "createdAtMs": 1,
                "payload": {
                    "activityKind": "work",
                    "phase": "started",
                    "workItemId": "work:direct",
                    "work": {"id": "work:direct", "state": "active"},
                },
            },
            {
                "eventId": "room-correlation:intercom",
                "roomId": "room-correlation",
                "turnId": "room-turn:intercom",
                "eventType": "participant_activity",
                "createdAtMs": 2,
                "payload": {
                    "activityKind": "intercom",
                    "phase": "delivered",
                    "message": {
                        "id": "intercom:one",
                        "status": "delivered",
                        "workItemId": "work:nested",
                    },
                },
            },
            {
                "eventId": "room-correlation:child",
                "roomId": "room-correlation",
                "turnId": "room-turn:child",
                "eventType": "participant_activity",
                "createdAtMs": 3,
                "payload": {
                    "activityKind": "child",
                    "phase": "started",
                    "childDispatchId": "dispatch:child",
                    "workItemId": "work:child",
                },
            },
            {
                "eventId": "room-correlation:receipt",
                "roomId": "room-correlation",
                "turnId": "room-turn:receipt",
                "eventType": "room_post",
                "createdAtMs": 4,
                "payload": {
                    "post": {
                        "postId": "post:one",
                        "kind": "receipt",
                        "workItemId": "work:receipt",
                    }
                },
            },
        )

        projected = [self.hub.observe_room_event(event) for event in events]

        self.assertEqual(
            [event["attributes"]["workItemId"] for event in projected if event],
            ["work:direct", "work:nested", "work:child", "work:receipt"],
        )

    def test_room_trace_keeps_one_root_and_distinct_planet_dispatch_lifecycles(self) -> None:
        self.hub.enqueue_room_event(
            {
                "eventId": "room-trace:1",
                "roomId": "room-trace",
                "turnId": "turn-root",
                "eventType": "user_message",
                "createdAtMs": 100,
                "payload": {"text": "PRIVATE_ROOM_REQUEST"},
            }
        )
        for sequence, participant_id, dispatch_id in (
            (2, "planet-a", "dispatch-a"),
            (3, "planet-b", "dispatch-b"),
        ):
            self.hub.enqueue_room_event(
                {
                    "eventId": f"room-trace:{sequence}",
                    "roomId": "room-trace",
                    "turnId": "turn-root",
                    "participantId": participant_id,
                    "sourceSessionId": f"session-{participant_id}",
                    "eventType": "route_decision",
                    "createdAtMs": 100 + sequence,
                    "payload": {
                        "dispatchId": dispatch_id,
                        "targetParticipantId": participant_id,
                    },
                }
            )
            self.hub.enqueue_room_event(
                {
                    "eventId": f"room-trace:{sequence + 10}",
                    "roomId": "room-trace",
                    "turnId": "turn-root",
                    "participantId": participant_id,
                    "sourceSessionId": f"session-{participant_id}",
                    "eventType": "turn_completed",
                    "createdAtMs": 120 + sequence,
                    "payload": {
                        "sourceEventId": f"session-{participant_id}:terminal",
                        "sourceEventType": "turn_completed",
                        "data": {
                            "status": "completed",
                            "dispatchId": dispatch_id,
                            "summary": "PRIVATE_AGENT_SUMMARY",
                        },
                    },
                }
            )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"traceId": "trace:room-turn:turn-root"})
        canonical = envelope_from_observations(snapshot["items"]).to_dict()
        spans = {item["spanId"]: item for item in canonical["spans"]}

        self.assertEqual(
            set(spans),
            {
                "span:room-turn:turn-root",
                "span:room-dispatch:dispatch-a",
                "span:room-dispatch:dispatch-b",
            },
        )
        self.assertEqual(canonical["status"], "completed")
        self.assertEqual(spans["span:room-turn:turn-root"]["status"], "completed")
        self.assertFalse(spans["span:room-turn:turn-root"]["recorded"])
        self.assertEqual(
            spans["span:room-turn:turn-root"]["unavailableReason"],
            "duration_not_recorded",
        )
        self.assertTrue(
            spans["span:room-turn:turn-root"]["attributes"][
                "terminalDerivedFromDispatches"
            ]
        )
        self.assertEqual(
            spans["span:room-turn:turn-root"]["attributes"][
                "terminalDispatchCount"
            ],
            2,
        )
        for dispatch_id in ("dispatch-a", "dispatch-b"):
            dispatch = spans[f"span:room-dispatch:{dispatch_id}"]
            self.assertEqual(dispatch["status"], "completed")
            self.assertEqual(dispatch["parentSpanId"], "span:room-turn:turn-root")
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("PRIVATE_ROOM_REQUEST", serialized)
        self.assertNotIn("PRIVATE_AGENT_SUMMARY", serialized)

    def test_room_child_and_work_lifecycles_fold_by_real_dispatch_and_work_identity(self) -> None:
        events = [
            {
                "eventId": "gravity:1",
                "roomId": "gravity",
                "turnId": "root",
                "eventType": "user_message",
                "createdAtMs": 200,
                "payload": {"text": "PRIVATE_ROOT"},
            },
            {
                "eventId": "gravity:2",
                "roomId": "gravity",
                "turnId": "root",
                "participantId": "planet-parent",
                "eventType": "route_decision",
                "createdAtMs": 201,
                "payload": {"dispatchId": "dispatch-parent"},
            },
            {
                "eventId": "gravity:3",
                "roomId": "gravity",
                "turnId": "root",
                "participantId": "planet-parent",
                "eventType": "participant_activity",
                "createdAtMs": 202,
                "payload": {
                    "activityKind": "child",
                    "phase": "started",
                    "childDispatchId": "dispatch-child",
                    "parentDispatchId": "dispatch-parent",
                    "workItemId": "work-one",
                    "task": "PRIVATE_CHILD_TASK",
                },
            },
            {
                "eventId": "gravity:4",
                "roomId": "gravity",
                "turnId": "root",
                "participantId": "planet-child",
                "eventType": "participant_activity",
                "createdAtMs": 210,
                "payload": {
                    "sourceEventId": "session-child:terminal",
                    "sourceEventType": "turn_completed",
                    "data": {
                        "activityKind": "child",
                        "phase": "completed",
                        "status": "completed",
                        "dispatchId": "dispatch-child",
                        "parentDispatchId": "dispatch-parent",
                        "workItemId": "work-one",
                        "summary": "PRIVATE_CHILD_RESULT",
                    },
                },
            },
            {
                "eventId": "gravity:5",
                "roomId": "gravity",
                "turnId": "root",
                "participantId": "planet-child",
                "eventType": "participant_activity",
                "createdAtMs": 211,
                "payload": {
                    "activityKind": "work",
                    "phase": "submitted",
                    "workItemId": "work-one",
                    "workItemRevision": 2,
                    "dispatchId": "dispatch-child",
                    "work": {
                        "id": "work-one",
                        "revision": 2,
                        "state": "review",
                        "objective": "PRIVATE_WORK_OBJECTIVE",
                        "resultSummary": "PRIVATE_WORK_RESULT",
                        "artifactRefs": ["docs/PRIVATE_ROOM_ARTIFACT.md"],
                        "evidenceRefs": [
                            "trace:room-review-evidence",
                            "https://private.example/review/PRIVATE_ROOM_URL",
                        ],
                    },
                },
            },
            {
                "eventId": "gravity:6",
                "roomId": "gravity",
                "turnId": "root",
                "participantId": "planet-reviewer",
                "eventType": "participant_activity",
                "createdAtMs": 220,
                "payload": {
                    "activityKind": "work",
                    "phase": "completed",
                    "workItemId": "work-one",
                    "workItemRevision": 2,
                    "dispatchId": "dispatch-child",
                    "work": {
                        "id": "work-one",
                        "revision": 2,
                        "state": "done",
                        "artifactRefs": ["docs/PRIVATE_ROOM_ARTIFACT.md"],
                        "evidenceRefs": [
                            "trace:room-review-evidence",
                            "https://private.example/review/PRIVATE_ROOM_URL",
                        ],
                    },
                },
            },
        ]
        for event in events:
            self.hub.enqueue_room_event(event)
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"traceId": "trace:room-turn:root"})
        canonical = envelope_from_observations(snapshot["items"]).to_dict()
        spans = {item["spanId"]: item for item in canonical["spans"]}

        child = spans["span:room-dispatch:dispatch-child"]
        self.assertEqual(child["status"], "completed")
        self.assertEqual(child["parentSpanId"], "span:room-dispatch:dispatch-parent")
        work = spans["span:room-work:work-one:r2"]
        self.assertEqual(work["status"], "completed")
        self.assertEqual(work["parentSpanId"], "span:room-dispatch:dispatch-child")
        self.assertEqual(work["metrics"]["evidenceCount"], 1)
        self.assertEqual(work["attributes"]["evidenceStage"], "work_review")
        self.assertEqual(len(canonical["evidence"]), 1)
        review = canonical["evidence"][0]
        self.assertEqual(review["sourceKind"], "room_evidence_ref")
        self.assertEqual(review["sourceRef"], "trace:room-review-evidence")
        self.assertTrue(
            all(item["evidenceStage"] == "work_review" for item in canonical["evidence"])
        )
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "PRIVATE_ROOT",
            "PRIVATE_CHILD_TASK",
            "PRIVATE_CHILD_RESULT",
            "PRIVATE_WORK_OBJECTIVE",
            "PRIVATE_WORK_RESULT",
            "PRIVATE_ROOM_ARTIFACT",
            "PRIVATE_ROOM_URL",
        ):
            self.assertNotIn(secret, serialized)

    def test_room_work_revision_distinguishes_missing_from_explicit_zero(self) -> None:
        base = {
            "roomId": "room-revision",
            "turnId": "turn-revision",
            "participantId": "planet-revision",
            "eventType": "participant_activity",
            "payload": {
                "activityKind": "work",
                "phase": "started",
                "workItemId": "work-revision",
                "work": {"id": "work-revision", "state": "running"},
            },
        }

        missing = self.hub.observe_room_event({
            **base,
            "eventId": "room-revision:missing",
            "createdAtMs": 230,
        })
        explicit_zero = self.hub.observe_room_event({
            **base,
            "eventId": "room-revision:zero",
            "createdAtMs": 231,
            "payload": {
                **base["payload"],
                "workItemId": "work-revision-zero",
                "workItemRevision": 0,
                "work": {"id": "work-revision-zero", "revision": 0, "state": "running"},
            },
        })

        self.assertIsNotNone(missing)
        self.assertIsNotNone(explicit_zero)
        assert missing is not None
        assert explicit_zero is not None
        self.assertEqual(missing["spanId"], "span:room-work:work-revision")
        self.assertNotIn("workItemRevision", missing["attributes"])
        self.assertEqual(explicit_zero["spanId"], "span:room-work:work-revision-zero:r0")
        self.assertEqual(explicit_zero["attributes"]["workItemRevision"], 0)

    def test_active_rag_missing_counts_are_unavailable_but_explicit_zero_is_preserved(self) -> None:
        phases = ("started", "retrieval_complete", "completed")
        for session_id, record in (
            (
                "active-rag-counts-missing",
                {
                    "timestampMs": 320,
                    "sessionId": "active-rag-counts-missing",
                    "status": "completed",
                    "request": {},
                    "retrieval": {},
                    "generation": {},
                },
            ),
            (
                "active-rag-counts-zero",
                {
                    "timestampMs": 321,
                    "sessionId": "active-rag-counts-zero",
                    "status": "completed",
                    "elapsedMs": 0,
                    "request": {
                        "selectedText": {"chars": 0},
                        "currentContext": {"chars": 0},
                        "providedEvidenceCount": 0,
                    },
                    "retrieval": {"evidenceCount": 0},
                    "generation": {"candidateCount": 0},
                },
            ),
        ):
            for phase in phases:
                self.hub.enqueue_active_rag_record({**record, "phase": phase})

        self.assertTrue(self.hub.flush())

        missing = self.hub.snapshot({"sessionId": "active-rag-counts-missing"})["items"]
        missing_by_name = {item["name"]: item for item in missing}
        self.assertNotIn("selectedChars", missing_by_name["active_rag_context"]["metrics"])
        self.assertNotIn("contextChars", missing_by_name["active_rag_context"]["metrics"])
        self.assertNotIn("providedEvidenceCount", missing_by_name["active_rag_context"]["metrics"])
        self.assertNotIn("evidenceCount", missing_by_name["active_rag_retrieval"]["metrics"])
        self.assertNotIn("candidateCount", missing_by_name["active_rag_generation"]["metrics"])
        self.assertNotIn("elapsedMs", missing_by_name["active_rag_generation"]["metrics"])

        explicit_zero = self.hub.snapshot({"sessionId": "active-rag-counts-zero"})["items"]
        zero_by_name = {item["name"]: item for item in explicit_zero}
        self.assertEqual(zero_by_name["active_rag_context"]["metrics"]["selectedChars"], 0)
        self.assertEqual(zero_by_name["active_rag_context"]["metrics"]["contextChars"], 0)
        self.assertEqual(zero_by_name["active_rag_context"]["metrics"]["providedEvidenceCount"], 0)
        self.assertEqual(zero_by_name["active_rag_retrieval"]["metrics"]["evidenceCount"], 0)
        self.assertEqual(zero_by_name["active_rag_generation"]["metrics"]["candidateCount"], 0)
        self.assertEqual(zero_by_name["active_rag_generation"]["metrics"]["elapsedMs"], 0)

    def test_memory_recall_missing_counts_are_unavailable_but_explicit_zero_is_preserved(self) -> None:
        for recall_id, metrics in (
            ("session-memory-counts-missing", {}),
            (
                "session-memory-counts-zero",
                {
                    "selectedCount": 0,
                    "omittedCount": 0,
                    "recentCompleteInputCount": 0,
                    "recentConversationCount": 0,
                    "usedChars": 0,
                    "maxItems": 0,
                },
            ),
        ):
            self.hub.enqueue_memory_recall_record(
                {
                    "recallId": f"session-memory-recall:{recall_id}",
                    "sessionId": recall_id,
                    "metrics": metrics,
                }
            )

        self.assertTrue(self.hub.flush())

        missing = self.hub.snapshot({"sessionId": "session-memory-counts-missing"})["items"][0]
        self.assertEqual(missing["metrics"], {})
        self.assertGreater(missing["createdAtMs"], 1_000_000_000_000)

        explicit_zero = self.hub.snapshot({"sessionId": "session-memory-counts-zero"})["items"][0]
        self.assertEqual(
            explicit_zero["metrics"],
            {
                "selectedCount": 0,
                "omittedCount": 0,
                "recentCompleteInputCount": 0,
                "recentConversationCount": 0,
                "usedChars": 0,
                "maxItems": 0,
            },
        )

    def test_agent_compaction_metrics_and_memory_pending_counts_distinguish_missing_from_zero(self) -> None:
        for event_id, session_id, event_type, payload in (
            (
                "session-compaction-counts:missing",
                "session-compaction-counts-missing",
                "compaction_completed",
                {"reason": "threshold"},
            ),
            (
                "session-compaction-counts:zero",
                "session-compaction-counts-zero",
                "compaction_completed",
                {"reason": "threshold", "tokensBefore": 0, "estimatedTokensAfter": 0},
            ),
            (
                "session-memory-counts:missing",
                "session-memory-pending-missing",
                "memory_maintenance_updated",
                {},
            ),
            (
                "session-memory-counts:zero",
                "session-memory-pending-zero",
                "memory_maintenance_updated",
                {"pendingEventCount": 0, "pendingDraftCount": 0},
            ),
        ):
            self.hub.enqueue_agent_event(
                AgentEventEnvelope(
                    event_id=event_id,
                    session_id=session_id,
                    turn_id=f"turn-{session_id}",
                    sequence=1,
                    created_at_ms=330,
                    event_type=event_type,
                    payload=payload,
                    resume_token=event_id,
                )
            )

        self.assertTrue(self.hub.flush())

        compaction_missing = self.hub.snapshot({"sessionId": "session-compaction-counts-missing"})["items"][0]
        self.assertNotIn("tokensBefore", compaction_missing["metrics"])
        self.assertNotIn("estimatedTokensAfter", compaction_missing["metrics"])
        compaction_zero = self.hub.snapshot({"sessionId": "session-compaction-counts-zero"})["items"][0]
        self.assertEqual(compaction_zero["metrics"]["tokensBefore"], 0)
        self.assertEqual(compaction_zero["metrics"]["estimatedTokensAfter"], 0)

        memory_missing = self.hub.snapshot({"sessionId": "session-memory-pending-missing"})["items"][0]
        self.assertNotIn("pendingEventCount", memory_missing["metrics"])
        self.assertNotIn("pendingDraftCount", memory_missing["metrics"])
        memory_zero = self.hub.snapshot({"sessionId": "session-memory-pending-zero"})["items"][0]
        self.assertEqual(memory_zero["metrics"]["pendingEventCount"], 0)
        self.assertEqual(memory_zero["metrics"]["pendingDraftCount"], 0)

    def test_knowledge_evidence_count_distinguishes_missing_from_explicit_zero(self) -> None:
        self.hub.enqueue_knowledge_retrieval_record(
            {
                "retrievalReceiptId": "retrieval:knowledge-counts-missing",
                "sessionId": "session-knowledge-counts-missing",
                "timestampMs": 740,
                "retrieval": {},
            }
        )
        self.hub.enqueue_knowledge_retrieval_record(
            {
                "retrievalReceiptId": "retrieval:knowledge-counts-zero",
                "sessionId": "session-knowledge-counts-zero",
                "timestampMs": 741,
                "retrieval": {"evidenceCount": 0},
            }
        )
        self.assertTrue(self.hub.flush())

        missing = self.hub.snapshot({"sessionId": "session-knowledge-counts-missing"})["items"][0]
        self.assertNotIn("evidenceCount", missing["metrics"])
        explicit_zero = self.hub.snapshot({"sessionId": "session-knowledge-counts-zero"})["items"][0]
        self.assertEqual(explicit_zero["metrics"]["evidenceCount"], 0)

    def test_room_user_message_character_count_uses_present_text_and_omits_missing(self) -> None:
        missing = self.hub.observe_room_event(
            {
                "eventId": "room-character-count:missing",
                "roomId": "room-character-count",
                "turnId": "turn-character-count-missing",
                "eventType": "user_message",
                "createdAtMs": 750,
                "payload": {},
            }
        )
        explicit_zero = self.hub.observe_room_event(
            {
                "eventId": "room-character-count:zero",
                "roomId": "room-character-count",
                "turnId": "turn-character-count-zero",
                "eventType": "user_message",
                "createdAtMs": 751,
                "payload": {"characterCount": 0},
            }
        )
        self.hub.enqueue_room_event(
            {
                "eventId": "room-character-count:text",
                "roomId": "room-character-count",
                "turnId": "turn-character-count-text",
                "eventType": "user_message",
                "createdAtMs": 752,
                "payload": {"text": "中文"},
            }
        )
        self.assertTrue(self.hub.flush())

        self.assertIsNotNone(missing)
        self.assertIsNotNone(explicit_zero)
        assert missing is not None
        assert explicit_zero is not None
        self.assertNotIn("characterCount", missing["metrics"])
        self.assertEqual(explicit_zero["metrics"]["characterCount"], 0)
        derived = self.hub.snapshot({"turnId": "turn-character-count-text"})["items"][0]
        self.assertEqual(derived["metrics"]["characterCount"], 2)

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
                "evidenceStage": "retrieval_output",
                "traceEvidence": [
                    {
                        "evidenceId": "hit:memory-7",
                        "sourceKind": "memory",
                        "sourceRef": "memory:7",
                        "sourceLane": "bm25_raw",
                        "disposition": "included",
                        "scores": {"score": -0.91234567, "confidence": 0.81},
                        "rankBefore": 3.5,
                        "rankAfter": 1,
                        "omissionReason": "",
                        "text": "PRIVATE_TRACE_TEXT",
                        "preview": "PRIVATE_TRACE_PREVIEW",
                        "prompt": "PRIVATE_TRACE_PROMPT",
                        "tags": ["PRIVATE_TRACE_TAG"],
                    }
                ],
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
        retrieval = next(item for item in snapshot["items"] if item["category"] == "retrieval")
        descriptor = retrieval["attributes"]["traceEvidence"][0]
        self.assertEqual(descriptor["evidenceId"], "hit:memory-7")
        self.assertEqual(descriptor["sourceLane"], "bm25_raw")
        self.assertIsNone(descriptor.get("rankBefore"))
        self.assertEqual(descriptor["rankAfter"], 1)
        self.assertAlmostEqual(descriptor["scores"]["score"], -0.912346, places=6)
        for key in ("text", "preview", "prompt", "result", "reasoning", "tags"):
            self.assertNotIn(key, descriptor)
        self.assertEqual(retrieval["refs"][1]["kind"], "retrieval_evidence")
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "PRIVATE_SELECTION",
            "PRIVATE_CONTEXT",
            "PRIVATE_EVIDENCE",
            "PRIVATE_PROMPT",
            "PRIVATE_CANDIDATE",
            "PRIVATE_TRACE_TEXT",
            "PRIVATE_TRACE_PREVIEW",
            "PRIVATE_TRACE_PROMPT",
            "PRIVATE_TRACE_TAG",
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

    def test_active_rag_generation_does_not_derive_start_from_session_elapsed(self) -> None:
        self.hub.observe_active_rag_record(
            {
                "timestampMs": 1_500,
                "sessionId": "active-rag-timing-unavailable",
                "status": "completed",
                "phase": "completed",
                # This is the session-wide elapsed metric, not generation
                # lifecycle evidence. It must never become the generation
                # span's start/end pair.
                "elapsedMs": 1_000,
                "generation": {"candidateCount": 1},
            }
        )

        event = self.hub.snapshot({"sessionId": "active-rag-timing-unavailable"})["items"][0]

        self.assertEqual(event["startedAtMs"], 1_500)
        self.assertIsNone(event["endedAtMs"])
        self.assertIsNone(event["durationMs"])

    def test_active_rag_generation_uses_explicit_stage_timing(self) -> None:
        self.hub.observe_active_rag_record(
            {
                "timestampMs": 1_500,
                "sessionId": "active-rag-explicit-timing",
                "status": "completed",
                "phase": "completed",
                "elapsedMs": 1_000,
                "stageTiming": {
                    "generation": {
                        "startedAtMs": 1_200,
                        "endedAtMs": 1_500,
                        "durationMs": 300,
                    },
                },
                "generation": {"candidateCount": 1},
            }
        )

        event = self.hub.snapshot({"sessionId": "active-rag-explicit-timing"})["items"][0]

        self.assertEqual(event["startedAtMs"], 1_200)
        self.assertEqual(event["endedAtMs"], 1_500)
        self.assertEqual(event["durationMs"], 300)

    def test_memory_recall_projection_emits_common_evidence_without_memory_text(self) -> None:
        memory_record = {
            "recallId": "session-memory-recall:one",
            "sessionId": "session-memory",
            "trigger": "first_user_prompt",
            "generatedAtMs": 375,
            "metrics": {
                "selectedCount": 1,
                "omittedCount": 2,
                "recentCompleteInputCount": 3,
                "recentConversationCount": 4,
                "usedChars": 500,
                "maxItems": 12,
            },
            "attributes": {
                "embeddingFallback": True,
                "evidenceStage": "memory_recall",
                "query": "PRIVATE_MEMORY_QUERY",
            },
            "traceEvidence": [
                {
                    "evidenceId": "memory:one",
                    "sourceKind": "memory",
                    "sourceRef": "memory:one",
                    "sourceLane": "bm25_raw",
                    "disposition": "included",
                    "scores": {
                        "bm25": -0.75,
                        "confidence": 0.0,
                        "prompt": 999,
                        "nan": float("nan"),
                    },
                    "rankBefore": 1.5,
                    "rankAfter": 1,
                    "omissionReason": "",
                    "text": "PRIVATE_MEMORY_TEXT",
                }
            ],
            "recentConversation": ["PRIVATE_CONVERSATION"],
        }
        self.hub.enqueue_memory_recall_record(memory_record)
        self.hub.enqueue_memory_recall_record(dict(memory_record))
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"sessionId": "session-memory"})

        self.assertEqual(snapshot["counts"]["total"], 1)
        event = snapshot["items"][0]
        self.assertEqual(event["traceId"], "trace:memory-recall:session-memory-recall:one")
        self.assertEqual(event["name"], "memory.recall")
        self.assertEqual(event["status"], "completed")
        self.assertIsNone(event["durationMs"])
        self.assertEqual(event["metrics"]["selectedCount"], 1)
        descriptor = event["attributes"]["traceEvidence"][0]
        self.assertEqual(descriptor["sourceKind"], "memory")
        self.assertEqual(descriptor["sourceLane"], "bm25_raw")
        self.assertEqual(descriptor["scores"], {"bm25": -0.75, "confidence": 0.0})
        self.assertIsNone(descriptor.get("rankBefore"))
        self.assertEqual(descriptor["rankAfter"], 1)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "PRIVATE_MEMORY_QUERY",
            "PRIVATE_MEMORY_TEXT",
            "PRIVATE_CONVERSATION",
            '"prompt"',
        ):
            self.assertNotIn(secret, serialized)

    def test_failed_memory_recall_is_terminal_without_fabricating_evidence(self) -> None:
        self.hub.enqueue_memory_recall_record(
            {
                "recallId": "session-memory-recall:failed",
                "sessionId": "session-memory-failed",
                "trigger": "turn_start",
                "generatedAtMs": 400,
                "status": "failed",
                "failureReason": "RuntimeError",
                "metrics": {},
                "attributes": {
                    "failureRecorded": True,
                },
                "traceEvidence": [],
                "error": "PRIVATE MEMORY FAILURE",
            }
        )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"sessionId": "session-memory-failed"})
        self.assertEqual(snapshot["counts"]["total"], 1)
        event = snapshot["items"][0]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["phase"], "recall_failed")
        self.assertEqual(event["attributes"]["failureReason"], "RuntimeError")
        self.assertTrue(event["attributes"]["failureRecorded"])
        self.assertEqual(event["attributes"]["traceEvidence"], [])
        self.assertEqual(event["refs"], [
            {
                "kind": "memory_recall",
                "id": "session-memory-recall:failed",
                "label": "Session 记忆召回",
            }
        ])
        trace = envelope_from_observations(snapshot["items"]).to_dict()
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["evidence"], [])
        self.assertFalse(trace["spans"][0]["recorded"])
        self.assertNotIn("PRIVATE MEMORY FAILURE", json.dumps(snapshot, ensure_ascii=False))

    def test_turn_failure_trace_keeps_public_runtime_reason_for_diagnosis(self) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="event:turn-failure-reason",
                session_id="session:turn-failure-reason",
                turn_id="turn:turn-failure-reason",
                sequence=1,
                created_at_ms=401,
                event_type="turn_failed",
                payload={
                    "error": "write failed: permission denied for /Users/private/project/result.md",
                    "failureKind": "provider_failure",
                    "reasonCode": "provider_contract_failure",
                    "nextStep": "检查工具参数和工作区权限后重试。",
                },
                resume_token="event:turn-failure-reason",
            )
        )
        self.assertTrue(self.hub.flush())

        event = self.hub.snapshot({"sessionId": "session:turn-failure-reason"})["items"][0]

        self.assertEqual(
            event["summary"],
            "Agent 回合失败：write failed: permission denied for [REDACTED_PATH]",
        )
        self.assertEqual(event["attributes"]["failureKind"], "provider_failure")
        self.assertEqual(
            event["attributes"]["failureReason"],
            "provider_contract_failure",
        )
        trace = envelope_from_observations([event]).to_dict()
        self.assertEqual(trace["spans"][0]["attributes"]["failureKind"], "provider_failure")
        self.assertEqual(
            trace["spans"][0]["attributes"]["failureReason"],
            "provider_contract_failure",
        )
        serialized = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("/Users/private", serialized)

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

        run_snapshot = self.hub.snapshot({"runId": "run-1"})
        self.assertEqual(run_snapshot["counts"]["total"], 1)
        self.assertEqual(run_snapshot["items"][0]["runId"], "run-1")

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

    def test_knowledge_retrieval_projection_persists_signed_scores_without_query_or_text(self) -> None:
        knowledge_record = {
            "retrievalReceiptId": "retrieval:knowledge:1",
            "sessionId": "session:knowledge",
            "roomId": "room:knowledge",
            "timestampMs": 700,
            "sourceKind": "knowledge",
            "evidenceStage": "retrieval_output",
            "query": "PRIVATE_QUERY",
            "retrieval": {
                "evidenceCount": 1,
                "traceEvidence": [
                    {
                        "evidenceId": "claim:1",
                        "sourceKind": "knowledge",
                        "sourceRef": "claim:1",
                        "sourceLane": "participant_private",
                        "disposition": "included",
                        "scores": {"score": -0.25, "confidence": 0.0, "prompt": 99},
                        "rankAfter": 1,
                        "text": "PRIVATE_TEXT",
                    }
                ],
            },
        }
        self.hub.enqueue_knowledge_retrieval_record(knowledge_record)
        self.hub.enqueue_knowledge_retrieval_record(dict(knowledge_record))
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"sessionId": "session:knowledge"})
        self.assertEqual(snapshot["counts"]["total"], 1)
        event = snapshot["items"][0]
        self.assertEqual(event["category"], "retrieval")
        self.assertEqual(event["name"], "knowledge.retrieval")
        self.assertEqual(event["attributes"]["sourceKind"], "knowledge")
        descriptor = event["attributes"]["traceEvidence"][0]
        self.assertEqual(descriptor["scores"], {"score": -0.25, "confidence": 0.0})
        self.assertEqual(descriptor["rankAfter"], 1)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        for forbidden in ("PRIVATE_QUERY", "PRIVATE_TEXT", "prompt", "query"):
            self.assertNotIn(forbidden, serialized)

    def test_knowledge_distinct_retrieval_receipts_remain_distinct(self) -> None:
        for receipt_id in ("retrieval:knowledge:a", "retrieval:knowledge:b"):
            self.hub.enqueue_knowledge_retrieval_record(
                {
                    "retrievalReceiptId": receipt_id,
                    "sessionId": "session:knowledge-distinct",
                    "timestampMs": 701,
                    "retrieval": {"evidenceCount": 0, "traceEvidence": []},
                }
            )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"sessionId": "session:knowledge-distinct"})
        self.assertEqual(snapshot["counts"]["total"], 2)
        self.assertEqual(
            {item["runId"] for item in snapshot["items"]},
            {"retrieval:knowledge:a", "retrieval:knowledge:b"},
        )

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

    def test_memory_maintenance_trace_keeps_run_identity_and_unavailable_timing(self) -> None:
        for phase, status in (
            ("started", "completed"),
            ("draft_ready", "waiting"),
            ("applied", "completed"),
        ):
            self.hub.emit_memory_event(
                phase=phase,
                status=status,
                summary=f"maintenance {phase}",
                run_id="memory-book-run-1",
            )

        observations = self.hub.snapshot({"category": "memory"})["items"]
        self.assertEqual({item["traceId"] for item in observations}, {"trace:memory:memory-book-run-1"})
        self.assertEqual(
            {item["spanId"] for item in observations},
            {
                "span:memory:memory-book-run-1:started",
                "span:memory:memory-book-run-1:draft_ready",
                "span:memory:memory-book-run-1:applied",
            },
        )
        by_phase = {item["phase"]: item for item in observations}
        self.assertEqual(by_phase["started"]["parentSpanId"], "")
        self.assertTrue(
            all(
                by_phase[phase]["parentSpanId"]
                == "span:memory:memory-book-run-1:started"
                for phase in ("draft_ready", "applied")
            )
        )
        self.assertTrue(all(item["endedAtMs"] is None for item in observations))
        self.assertTrue(all(item["durationMs"] is None for item in observations))
        self.assertTrue(all(item["attributes"] == {"rawMemoryTextStored": False} for item in observations))

        envelope = envelope_from_observations(observations)
        self.assertEqual(envelope.status, "completed")
        spans = {span.span_id: span for span in envelope.spans}
        self.assertIsNone(spans["span:memory:memory-book-run-1:started"].parent_span_id)
        self.assertEqual(
            spans["span:memory:memory-book-run-1:draft_ready"].parent_span_id,
            "span:memory:memory-book-run-1:started",
        )
        self.assertEqual(
            spans["span:memory:memory-book-run-1:applied"].parent_span_id,
            "span:memory:memory-book-run-1:started",
        )
        self.assertTrue(all(not span.recorded for span in envelope.spans))

    def test_memory_maintenance_trace_requires_stable_run_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id is required"):
            self.hub.emit_memory_event(
                phase="draft_ready",
                status="waiting",
                summary="missing identity",
                run_id="",
            )

    def test_memory_maintenance_owner_run_can_be_nested_in_gateway_trace(self) -> None:
        event = self.hub.emit_memory_event(
            phase="started",
            status="completed",
            summary="owner curation started",
            run_id="owner-run-1",
            trace_id="trace:memory:memory-maintenance:job-1",
            maintenance_job_id="memory-maintenance:job-1",
            parent_span_id="span:memory:memory-maintenance:job-1:started",
        )

        self.assertEqual(event["traceId"], "trace:memory:memory-maintenance:job-1")
        self.assertEqual(event["runId"], "owner-run-1")
        self.assertEqual(
            event["parentSpanId"],
            "span:memory:memory-maintenance:job-1:started",
        )
        self.assertEqual(
            event["attributes"]["maintenanceJobId"],
            "memory-maintenance:job-1",
        )
        self.assertEqual(event["attributes"]["ownerRunId"], "owner-run-1")
        self.assertEqual(
            event["attributes"]["traceContext"],
            "gateway_memory_maintenance",
        )

    def test_memory_maintenance_retry_keeps_one_trace_without_timing_inflation(self) -> None:
        for phase, status in (
            ("started", "completed"),
            ("draft_ready", "waiting"),
            ("draft_ready", "failed"),
            ("draft_ready", "waiting"),
            ("applied", "completed"),
        ):
            self.hub.emit_memory_event(
                phase=phase,
                status=status,
                summary=f"maintenance {phase} {status}",
                run_id="memory-book-retry-1",
            )

        observations = sorted(
            self.hub.snapshot({"category": "memory"})["items"],
            key=lambda item: int(item["sequence"]),
        )
        self.assertEqual(
            [item["status"] for item in observations],
            ["completed", "waiting", "failed", "waiting", "completed"],
        )
        self.assertEqual({item["traceId"] for item in observations}, {"trace:memory:memory-book-retry-1"})
        self.assertTrue(all(item["durationMs"] is None for item in observations))

    def test_memory_maintenance_attempts_are_distinct_under_one_run(self) -> None:
        for phase, status, attempt_id in (
            ("started", "completed", "model-run-1"),
            ("draft_ready", "failed", "model-run-1"),
            ("started", "completed", "model-run-2"),
            ("draft_ready", "waiting", "model-run-2"),
            ("applied", "completed", "model-run-2"),
        ):
            self.hub.emit_memory_event(
                phase=phase,
                status=status,
                summary=f"maintenance {phase} {status}",
                run_id="memory-book-attempts-1",
                attempt_id=attempt_id,
            )

        observations = self.hub.snapshot({"category": "memory"})["items"]
        self.assertEqual({item["traceId"] for item in observations}, {"trace:memory:memory-book-attempts-1"})
        self.assertEqual(
            {item["spanId"] for item in observations},
            {
                "span:memory:memory-book-attempts-1:attempt:model-run-1:started",
                "span:memory:memory-book-attempts-1:attempt:model-run-1:draft_ready",
                "span:memory:memory-book-attempts-1:attempt:model-run-2:started",
                "span:memory:memory-book-attempts-1:attempt:model-run-2:draft_ready",
                "span:memory:memory-book-attempts-1:attempt:model-run-2:applied",
            },
        )
        by_phase = {
            item["phase"] + item["status"]: item
            for item in observations
        }
        self.assertEqual(
            by_phase["draft_readywaiting"]["parentSpanId"],
            "span:memory:memory-book-attempts-1:attempt:model-run-2:started",
        )
        self.assertTrue(all(item["endedAtMs"] is None for item in observations))
        envelope = envelope_from_observations(observations)
        spans = {span.span_id: span for span in envelope.spans}
        self.assertEqual(envelope.status, "completed")
        self.assertEqual(
            spans["span:memory:memory-book-attempts-1:attempt:model-run-1:draft_ready"].status,
            "failed",
        )
        self.assertEqual(
            spans["span:memory:memory-book-attempts-1:attempt:model-run-2:draft_ready"].status,
            "completed",
        )
        self.assertTrue(all(not span.recorded for span in envelope.spans))

    def test_memory_attempt_identity_survives_observation_hub_restart(self) -> None:
        db_path = self.hub.store.db_path
        self.hub.emit_memory_event(
            phase="started",
            status="completed",
            summary="first attempt",
            run_id="memory-book-restart-1",
            attempt_id="model-run-1",
        )
        self.hub.close()
        self.hub = ObservationHub(db_path)
        self.hub.emit_memory_event(
            phase="started",
            status="completed",
            summary="retry attempt",
            run_id="memory-book-restart-1",
            attempt_id="model-run-2",
        )

        observations = self.hub.snapshot({"category": "memory"})["items"]
        self.assertEqual(
            {item["traceId"] for item in observations},
            {"trace:memory:memory-book-restart-1"},
        )
        self.assertEqual(
            {item["spanId"] for item in observations},
            {
                "span:memory:memory-book-restart-1:attempt:model-run-1:started",
                "span:memory:memory-book-restart-1:attempt:model-run-2:started",
            },
        )

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

    def test_projection_queue_overflow_is_visible_and_flush_does_not_claim_no_loss(self) -> None:
        # Hold the real worker on its original queue, then replace the bounded
        # queue with a one-slot queue so overflow is deterministic and cannot
        # make the test depend on thread scheduling.
        original_queue = self.hub._projection_queue
        projection_queue = queue.Queue(maxsize=1)
        projection_queue.put_nowait(("test", None))
        self.hub._projection_queue = projection_queue

        self.hub._enqueue_projection("test", None)

        health = self.hub.projection_health()
        self.assertEqual(health["droppedCount"], 1)
        self.assertEqual(health["errorCount"], 0)
        self.assertEqual(health["lastFailure"], None)
        self.assertFalse(self.hub.flush(timeout_seconds=0))
        self.hub._projection_queue = original_queue

    def test_projection_exception_is_a_structured_durable_failure_and_flush_reports_it(self) -> None:
        with patch.object(
            self.hub,
            "observe_room_event",
            side_effect=RuntimeError("PRIVATE projection detail"),
        ):
            self.hub.enqueue_room_event(
                {
                    "eventId": "room-projection-failure",
                    "roomId": "room-projection-failure",
                    "eventType": "room_post",
                    "createdAtMs": 701,
                    "payload": {},
                }
            )
            self.assertFalse(self.hub.flush())

        health = self.hub.projection_health()
        self.assertEqual(health["droppedCount"], 0)
        self.assertEqual(health["errorCount"], 1)
        failure = health["lastFailure"]
        self.assertIsInstance(failure, dict)
        self.assertEqual(failure["kind"], "room")
        self.assertEqual(failure["errorType"], "RuntimeError")
        self.assertNotIn("PRIVATE projection detail", json.dumps(failure))

        snapshot = self.hub.snapshot({"category": "system"})
        failure_events = [
            item
            for item in snapshot["items"]
            if item["phase"] == "projection_failure"
        ]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0]["status"], "failed")
        self.assertEqual(failure_events[0]["attributes"]["producerKind"], "room")

    def test_input_generation_lifecycle_becomes_one_measured_privacy_safe_trace(self) -> None:
        base = {
            "schemaVersion": "rag-ime.input-generation-observation.v1",
            "sourceKind": "input_generation",
            "traceId": "trace:input-generation:abc123",
            "requestId": "surface-request-abc123",
            "startedAtMs": 100,
            "request": {
                "frontAppBundleId": "com.example.Editor",
                "requestedProvider": "deepseek",
                "requestedModel": "deepseek-v4-flash",
                "requestedThinkingLevel": "high",
                "inputFingerprint": "sha256:" + "a" * 64,
                "currentRequestChars": 21,
                "currentContextChars": 34,
                "selectedChars": 5,
                "latencyBudgetMs": 3_000,
                "currentRequest": "PRIVATE REQUEST",
                "contextMetrics": {
                    "recentInputRequestedCount": 20,
                    "recentInputEffectiveCount": 2,
                    "recentInputActualCount": 2,
                    "recentInputRequestedChars": 12000,
                    "recentInputEffectiveChars": 40,
                    "recentInputActualChars": 40,
                    "recentInputUnavailableReason": "budget_exhausted",
                    "recentInputTruncated": True,
                    "axRequestedNodeCount": 160,
                    "axEffectiveNodeCount": 5,
                    "axActualNodeCount": 7,
                    "axRequestedCharCount": 12000,
                    "axEffectiveCharCount": 280,
                    "axActualCharCount": 321,
                    "axNodeCount": 7,
                    "axCharacterCount": 321,
                    "axTruncated": False,
                    "axUnavailableReason": "budget_exhausted",
                    "contextRequestedTokens": 900,
                    "contextEffectiveTokens": 640,
                    "contextTruncated": True,
                },
            },
            "privacy": {"rawTextIncluded": False},
        }
        self.hub.enqueue_input_generation_record({
            **base,
            "phase": "started",
            "status": "running",
            "timestampMs": 100,
            "generation": {
                "effectiveProvider": "deepseek",
                "effectiveModel": "deepseek-v4-flash",
                "effectiveThinkingLevel": "high",
            },
        })
        self.hub.enqueue_input_generation_record({
            **base,
            "phase": "completed",
            "status": "completed",
            "timestampMs": 125,
            "endedAtMs": 125,
            "durationMs": 25,
            "generation": {
                "effectiveProvider": "deepseek",
                "effectiveModel": "deepseek-v4-flash",
                "effectiveThinkingLevel": "high",
                "ok": True,
                "elapsedMs": 25,
                "firstTokenMs": 9,
                "inputTokens": 11,
                "outputTokens": 4,
                "totalTokens": 15,
                "text": "PRIVATE OUTPUT",
            },
        })

        self.assertTrue(self.hub.flush())
        snapshot = self.hub.snapshot({"traceId": "trace:input-generation:abc123"})
        self.assertEqual(len(snapshot["items"]), 2)
        by_status = {item["status"]: item for item in snapshot["items"]}
        self.assertEqual(set(by_status), {"running", "completed"})
        self.assertEqual(
            {item["spanId"] for item in snapshot["items"]},
            {"span:input-generation:surface-request-abc123"},
        )
        completed = by_status["completed"]
        self.assertEqual(completed["durationMs"], 25)
        self.assertEqual(completed["metrics"]["firstTokenMs"], 9)
        self.assertEqual(completed["metrics"]["recentInputRequestedCount"], 20)
        self.assertEqual(completed["metrics"]["recentInputEffectiveCount"], 2)
        self.assertEqual(completed["metrics"]["recentInputActualCount"], 2)
        self.assertEqual(completed["metrics"]["recentInputRequestedChars"], 12000)
        self.assertEqual(completed["metrics"]["recentInputEffectiveChars"], 40)
        self.assertEqual(completed["metrics"]["recentInputActualChars"], 40)
        self.assertEqual(completed["attributes"]["recentInputUnavailableReason"], "budget_exhausted")
        self.assertEqual(completed["metrics"]["axRequestedNodeCount"], 160)
        self.assertEqual(completed["metrics"]["axEffectiveNodeCount"], 5)
        self.assertEqual(completed["metrics"]["axActualNodeCount"], 7)
        self.assertEqual(completed["metrics"]["axRequestedCharCount"], 12000)
        self.assertEqual(completed["metrics"]["axEffectiveCharCount"], 280)
        self.assertEqual(completed["metrics"]["axActualCharCount"], 321)
        self.assertEqual(completed["attributes"]["axUnavailableReason"], "budget_exhausted")
        self.assertTrue(completed["metrics"]["contextTruncated"])
        self.assertEqual(completed["attributes"]["sourceKind"], "input_generation")
        self.assertEqual(completed["attributes"]["inputFingerprint"], "sha256:" + "a" * 64)
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("PRIVATE REQUEST", serialized)
        self.assertNotIn("PRIVATE OUTPUT", serialized)

        trace = envelope_from_observations(snapshot["items"]).to_dict()
        self.assertEqual(trace["sourceKind"], "input_generation")
        self.assertEqual(trace["status"], "completed")
        self.assertEqual(trace["input"]["fingerprint"], "sha256:" + "a" * 64)
        self.assertEqual(trace["binding"], {"runId": "surface-request-abc123"})
        self.assertEqual(trace["spans"][0]["durationMs"], 25)
        self.assertTrue(trace["spans"][0]["recorded"])

    def test_input_generation_terminal_fence_rejects_contradictory_terminal(self) -> None:
        base = {
            "schemaVersion": "rag-ime.input-generation-observation.v1",
            "sourceKind": "input_generation",
            "traceId": "trace:input-generation:fence",
            "requestId": "surface-fence-1",
            "startedAtMs": 100,
            "request": {},
            "generation": {},
            "privacy": {"rawTextIncluded": False},
        }

        started = self.hub.observe_input_generation_record(
            {**base, "phase": "started", "status": "running", "timestampMs": 100}
        )
        completed = self.hub.observe_input_generation_record(
            {
                **base,
                "phase": "completed",
                "status": "completed",
                "timestampMs": 125,
                "endedAtMs": 125,
                "durationMs": 25,
                "generation": {"ok": True},
            }
        )
        self.assertIsNotNone(started)
        self.assertIsNotNone(completed)
        self.assertTrue(self.hub.flush())

        with self.assertRaisesRegex(ObservationConflict, "terminal fence"):
            self.hub.observe_input_generation_record(
                {
                    **base,
                    "phase": "failed",
                    "status": "failed",
                    "timestampMs": 126,
                    "endedAtMs": 126,
                    "durationMs": 26,
                    "generation": {"ok": False, "failureReason": "runtime_error"},
                }
            )

        snapshot = self.hub.snapshot({"traceId": "trace:input-generation:fence"})
        self.assertEqual({item["status"] for item in snapshot["items"]}, {"running", "completed"})

    def test_input_generation_terminal_replay_remains_idempotent_after_fence(self) -> None:
        base = {
            "schemaVersion": "rag-ime.input-generation-observation.v1",
            "sourceKind": "input_generation",
            "traceId": "trace:input-generation:replay-fence",
            "requestId": "surface-replay-fence",
            "startedAtMs": 100,
            "request": {},
            "generation": {"ok": True},
            "privacy": {"rawTextIncluded": False},
            "phase": "completed",
            "status": "completed",
            "timestampMs": 125,
            "endedAtMs": 125,
            "durationMs": 25,
        }

        first = self.hub.observe_input_generation_record(base)
        replay = self.hub.observe_input_generation_record(dict(base))
        self.assertEqual(first, replay)
        self.assertTrue(self.hub.flush())
        self.assertEqual(
            self.hub.snapshot({"traceId": "trace:input-generation:replay-fence"})["counts"]["total"],
            1,
        )

    def test_input_generation_max_request_id_uses_a_contract_safe_span_identity(self) -> None:
        request_id = "r" * 160
        event = self.hub.observe_input_generation_record(
            {
                "schemaVersion": "rag-ime.input-generation-observation.v1",
                "sourceKind": "input_generation",
                "traceId": "trace:input-generation:max-id",
                "requestId": request_id,
                "phase": "completed",
                "status": "completed",
                "timestampMs": 125,
                "startedAtMs": 100,
                "endedAtMs": 125,
                "durationMs": 25,
                "request": {},
                "generation": {"ok": True},
                "privacy": {"rawTextIncluded": False},
            }
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertLessEqual(len(str(event["spanId"])), 160)
        trace = envelope_from_observations([event]).to_dict()
        self.assertLessEqual(len(str(trace["spans"][0]["spanId"])), 160)

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

    def test_room_async_projection_rejects_free_text_paths_and_urls_before_queue(self) -> None:
        captured: list[tuple[str, object]] = []
        with patch.object(
            self.hub,
            "_enqueue_projection",
            side_effect=lambda kind, value: captured.append((kind, value)),
        ):
            self.hub.enqueue_room_event(
                {
                    "eventId": "room-safe:event",
                    "roomId": "room-safe",
                    "turnId": "https://private.example/PRIVATE_TURN",
                    "participantId": "/tmp/PRIVATE_PARTICIPANT",
                    "sourceSessionId": "PRIVATE SESSION PROSE",
                    "eventType": "participant_activity",
                    "createdAtMs": 700,
                    "payload": {
                        "sourceEventId": "file:///tmp/PRIVATE_SOURCE",
                        "sourceEventType": "PRIVATE EVENT PROSE",
                        "data": {
                            "activityKind": "intercom",
                            "phase": "delivered",
                            "durationMs": "PRIVATE_DURATION",
                            "message": {
                                "id": "intercom-safe",
                                "kind": "ask",
                                "targetParticipantId": "https://private.example/PRIVATE_TARGET",
                                "replyTo": "../PRIVATE_REPLY",
                                "content": "PRIVATE_INTERCOM_BODY",
                            },
                        },
                    },
                }
            )
            self.hub.enqueue_room_event(
                {
                    "eventId": "room-safe:post",
                    "roomId": "room-safe",
                    "eventType": "room_post",
                    "createdAtMs": 701,
                    "payload": {
                        "post": {
                            "postId": "post-safe",
                            "kind": "receipt",
                            "authorActorRef": "../../PRIVATE_AUTHOR",
                            "dispatchId": "https://private.example/PRIVATE_DISPATCH",
                        }
                    },
                }
            )

        self.assertEqual([kind for kind, _ in captured], ["room", "room"])
        serialized = json.dumps(captured, ensure_ascii=False)
        self.assertIn("intercom-safe", serialized)
        self.assertIn("post-safe", serialized)
        for secret in (
            "PRIVATE_TURN",
            "PRIVATE_PARTICIPANT",
            "PRIVATE SESSION PROSE",
            "PRIVATE_SOURCE",
            "PRIVATE EVENT PROSE",
            "PRIVATE_DURATION",
            "PRIVATE_TARGET",
            "PRIVATE_REPLY",
            "PRIVATE_INTERCOM_BODY",
            "PRIVATE_AUTHOR",
            "PRIVATE_DISPATCH",
        ):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
