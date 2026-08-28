from __future__ import annotations

import unittest

from rag_ime.trace_adapters import (
    envelope_from_browser_trace,
    envelope_from_observations,
    envelope_from_prediction_frame,
)
from rag_ime.trace_runtime import TraceContractError, fingerprint_text


class TraceAdapterTests(unittest.TestCase):
    def test_prediction_frame_projects_safe_frontend_metadata_without_input_history(self) -> None:
        trace = envelope_from_prediction_frame(
            {
                "schemaVersion": "rag-ime.prediction-frame.v1",
                "recordedAtMs": 500,
                "sessionId": "prediction-session-1",
                "requestSeq": 7,
                "frontendRevision": 12,
                "selectionEpoch": 3,
                "panelSessionId": "panel-1",
                "input": {"length": 2, "hash": "sha256:input-hash"},
                "preedit": {"length": 2, "hash": "sha256:preedit-hash"},
                "committedContext": {"length": 8, "hash": "sha256:context-hash"},
                "predictionSession": {
                    "phase": "prefix_constrained",
                    "inputMode": "composing",
                    "snapshotId": "snapshot-private",
                },
                "ragLane": {"called": True, "timedOut": True, "elapsedMs": 18, "suggestionCount": 2},
                "modelLane": {"called": True, "elapsedMs": 0, "predictionCount": 1},
                "display": {
                    "visibleCandidateCount": 3,
                    "sourceCounts": {"model": 1, "wanxiang": 2},
                    "candidates": [{"text": "PRIVATE_CANDIDATE"}],
                },
                "traceEvents": [{"reason": "PRIVATE_FAILURE_REASON", "snapshotId": "snap"}],
            }
        ).to_dict()

        self.assertEqual("trace:prediction:prediction-session-1:request-7", trace["traceId"])
        self.assertEqual("rime_prediction", trace["sourceKind"])
        self.assertEqual(
            {"sessionId": "prediction-session-1", "sourceLoopId": "prediction-frame:prediction-session-1:7"},
            trace["binding"],
        )
        self.assertEqual("completed", trace["status"])
        span = trace["spans"][0]
        self.assertEqual("input.prediction", span["name"])
        self.assertFalse(span["recorded"])
        self.assertIsNone(span["durationMs"])
        self.assertEqual("duration_not_recorded", span["unavailableReason"])
        self.assertEqual(18, span["metrics"]["ragElapsedMs"])
        self.assertEqual(0, span["metrics"]["modelElapsedMs"])
        self.assertTrue(span["attributes"]["ragTimedOut"])
        self.assertEqual(3, span["attributes"]["visibleCandidateCount"])
        self.assertNotIn("PRIVATE_CANDIDATE", str(trace))
        self.assertNotIn("PRIVATE_FAILURE_REASON", str(trace))
        self.assertNotIn("snapshot-private", str(trace))
        self.assertNotIn("sha256:input-hash", str(trace))

    def test_prediction_frame_requires_stable_identity_and_rejects_untrusted_duration(self) -> None:
        base = {
            "recordedAtMs": 500,
            "requestSeq": 0,
            "predictionSession": {},
            "ragLane": {"elapsedMs": 12},
        }
        with self.assertRaisesRegex(TraceContractError, "identity unavailable"):
            envelope_from_prediction_frame(base)

        with self.assertRaisesRegex(TraceContractError, "duration"):
            envelope_from_prediction_frame(
                {
                    **base,
                    "sessionId": "prediction-session-1",
                    "requestSeq": 7,
                    "ragLane": {"elapsedMs": "12"},
                }
            )

    def test_browser_command_trace_projects_only_authoritative_redacted_lifecycle(self) -> None:
        trace = envelope_from_browser_trace(
            {
                "commandId": "bcmd_abc123",
                "deviceId": "chrome-test",
                "sessionId": "session-browser",
                "action": "navigate",
                "status": "completed",
                "createdAtMs": 100,
                "claimedAtMs": 110,
                "completedAtMs": 145,
                "durationMs": 45,
                "result": {
                    "url": "https://reader:password@example.com/private?token=secret",
                    "snapshotId": "snap_private",
                    "summary": "PRIVATE RAW RESULT",
                },
            }
        ).to_dict()

        self.assertEqual("trace:browser:command:bcmd_abc123", trace["traceId"])
        self.assertEqual("browser_control", trace["sourceKind"])
        self.assertEqual("completed", trace["status"])
        self.assertEqual(
            {"sessionId": "session-browser", "sourceLoopId": "browser-command:bcmd_abc123"},
            trace["binding"],
        )
        span = trace["spans"][0]
        self.assertEqual("browser.command.navigate", span["name"])
        self.assertEqual(45, span["durationMs"])
        self.assertTrue(span["recorded"])
        self.assertEqual("bcmd_abc123", span["attributes"]["commandId"])
        self.assertEqual("chrome-test", span["attributes"]["deviceId"])
        self.assertNotIn("https://", str(trace))
        self.assertNotIn("snap_private", str(trace))
        self.assertNotIn("PRIVATE RAW RESULT", str(trace))

    def test_browser_pending_command_keeps_duration_unknown(self) -> None:
        trace = envelope_from_browser_trace(
            {
                "commandId": "bcmd_pending",
                "deviceId": "chrome-test",
                "sessionId": "session-browser",
                "action": "click",
                "status": "queued",
                "createdAtMs": 100,
                "claimedAtMs": None,
                "completedAtMs": None,
                "durationMs": None,
                "result": {"url": "https://should-not-appear.example"},
            }
        ).to_dict()

        self.assertEqual("building", trace["status"])
        span = trace["spans"][0]
        self.assertEqual("queued", span["status"])
        self.assertFalse(span["recorded"])
        self.assertIsNone(span["durationMs"])
        self.assertEqual("duration_not_recorded", span["unavailableReason"])
        self.assertNotIn("should-not-appear", str(trace))

    def test_browser_trace_rejects_inconsistent_duration_and_unknown_status(self) -> None:
        inconsistent = envelope_from_browser_trace(
            {
                "commandId": "bcmd_bad-timing",
                "action": "wait",
                "status": "failed",
                "createdAtMs": 100,
                "completedAtMs": 140,
                "durationMs": 5,
            }
        ).to_dict()
        span = inconsistent["spans"][0]
        self.assertEqual("failed", inconsistent["status"])
        self.assertFalse(span["recorded"])
        self.assertIsNone(span["endedAtMs"])
        self.assertEqual("inconsistent_timing", span["unavailableReason"])

        with self.assertRaisesRegex(TraceContractError, "unsupported browser command status"):
            envelope_from_browser_trace(
                {
                    "commandId": "bcmd_unknown",
                    "action": "wait",
                    "status": "mystery",
                    "createdAtMs": 100,
                }
            )

    def test_tool_lifecycle_collapses_and_keeps_zero_duration_turn(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:tool:1",
                    "spanId": "span:turn:1",
                    "parentSpanId": "",
                    "sessionId": "session:1",
                    "turnId": "turn:1",
                    "sequence": 3,
                    "category": "agent",
                    "name": "turn",
                    "status": "completed",
                    "createdAtMs": 130,
                    "startedAtMs": 130,
                    "endedAtMs": 130,
                    "durationMs": 0,
                },
                {
                    "traceId": "trace:tool:1",
                    "spanId": "span:tool:call-1",
                    "parentSpanId": "span:turn:1",
                    "sessionId": "session:1",
                    "turnId": "turn:1",
                    "sequence": 1,
                    "category": "tool",
                    "name": "tool.call",
                    "status": "running",
                    "createdAtMs": 100,
                    "startedAtMs": 100,
                    "endedAtMs": None,
                    "durationMs": None,
                    "refs": [{"kind": "tool", "id": "call-1"}],
                },
                {
                    "traceId": "trace:tool:1",
                    "spanId": "span:tool:call-1",
                    "parentSpanId": "span:turn:1",
                    "sessionId": "session:1",
                    "turnId": "turn:1",
                    "sequence": 2,
                    "category": "tool",
                    "name": "tool.call",
                    "status": "completed",
                    "createdAtMs": 135,
                    "startedAtMs": 135,
                    "endedAtMs": 135,
                    "durationMs": 35,
                    "refs": [{"kind": "tool", "id": "call-1"}],
                },
            ]
        ).to_dict()

        self.assertEqual([span["spanId"] for span in trace["spans"]], ["span:tool:call-1", "span:turn:1"])
        tool = trace["spans"][0]
        self.assertEqual(tool["status"], "completed")
        self.assertEqual(tool["startedAtMs"], 100)
        self.assertEqual(tool["endedAtMs"], 135)
        self.assertEqual(tool["durationMs"], 35)
        self.assertTrue(tool["recorded"])
        self.assertEqual(trace["spans"][1]["durationMs"], 0)
        self.assertTrue(trace["spans"][1]["recorded"])
        self.assertEqual(len(trace["evidence"]), 1)

    def test_sequence_zero_is_not_replaced_by_created_time(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:sequence:1",
                    "spanId": "span:sequence:1",
                    "name": "sequence",
                    "status": "running",
                    "sequence": 0,
                    "createdAtMs": 999,
                    "startedAtMs": 10,
                    "endedAtMs": None,
                    "durationMs": None,
                },
                {
                    "traceId": "trace:sequence:1",
                    "spanId": "span:sequence:1",
                    "name": "sequence",
                    "status": "completed",
                    "sequence": 1,
                    "createdAtMs": 10,
                    "startedAtMs": 20,
                    "endedAtMs": 20,
                    "durationMs": 10,
                },
            ]
        ).to_dict()

        span = trace["spans"][0]
        self.assertEqual(span["status"], "completed")
        self.assertEqual(span["startedAtMs"], 10)
        self.assertEqual(span["durationMs"], 10)
        self.assertTrue(span["recorded"])

    def test_lifecycle_duration_mismatch_is_explicitly_unavailable(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:timing:1",
                    "spanId": "span:tool:timing",
                    "name": "tool.call",
                    "status": "running",
                    "sequence": 0,
                    "createdAtMs": 50,
                    "startedAtMs": 50,
                    "endedAtMs": None,
                    "durationMs": None,
                },
                {
                    "traceId": "trace:timing:1",
                    "spanId": "span:tool:timing",
                    "name": "tool.call",
                    "status": "completed",
                    "sequence": 1,
                    "createdAtMs": 100,
                    "startedAtMs": 100,
                    "endedAtMs": 100,
                    "durationMs": 40,
                },
            ]
        ).to_dict()

        span = trace["spans"][0]
        self.assertFalse(span["recorded"])
        self.assertIsNone(span["endedAtMs"])
        self.assertIsNone(span["durationMs"])
        self.assertEqual(span["unavailableReason"], "inconsistent_timing")

    def test_missing_parent_becomes_root_with_safe_metadata(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:parent:1",
                    "spanId": "span:child:1",
                    "parentSpanId": "span:missing",
                    "name": "child",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "attributes": {
                        "promptText": "PRIVATE_PROMPT",
                        "url": "https://private.example/token",
                        "title": "PRIVATE_TITLE",
                        "page": "PRIVATE_PAGE",
                        "candidateText": "PRIVATE_CANDIDATE",
                        "snapshotId": "PRIVATE_SNAPSHOT",
                        "failureReason": "PRIVATE_FAILURE_REASON",
                        "reason": "PRIVATE_REASON",
                        "error": "PRIVATE_ERROR",
                        "targetParticipantId": "p1",
                    },
                }
            ]
        ).to_dict()

        span = trace["spans"][0]
        self.assertIsNone(span["parentSpanId"])
        self.assertTrue(span["attributes"]["parentUnavailable"])
        self.assertEqual(span["attributes"]["parentUnavailableReason"], "span_not_in_trace")
        self.assertEqual(span["attributes"]["targetParticipantId"], "p1")
        self.assertNotIn("span:missing", str(trace))
        for sentinel in (
            "PRIVATE_PROMPT",
            "private.example",
            "PRIVATE_TITLE",
            "PRIVATE_PAGE",
            "PRIVATE_CANDIDATE",
            "PRIVATE_SNAPSHOT",
            "PRIVATE_FAILURE_REASON",
            "PRIVATE_REASON",
            "PRIVATE_ERROR",
        ):
            self.assertNotIn(sentinel, str(trace))

    def test_binding_conflicts_are_omitted_and_refs_artifacts_are_deduped(self) -> None:
        artifact = {
            "artifactId": "artifact:1",
            "kind": "eval",
            "mediaType": "application/json",
            "sha256": "a" * 64,
            "byteSize": 12,
            "recordCount": 1,
        }
        observations = []
        for index, turn_id in enumerate(("turn:1", "turn:2"), start=1):
            observations.append(
                {
                    "traceId": "trace:dedupe:1",
                    "spanId": f"span:{index}",
                    "name": "event",
                    "status": "completed",
                    "createdAtMs": index,
                    "startedAtMs": index,
                    "endedAtMs": index,
                    "durationMs": 0,
                    "sessionId": "session:1",
                    "turnId": turn_id,
                    "roomId": "room:1",
                    "runId": f"run:{index}",
                    "sourceLoopId": "loop:1",
                    "refs": [{"kind": "knowledge", "id": "doc:1"}],
                    "attributes": {"artifactRefs": [artifact]},
                }
            )

        trace = envelope_from_observations(observations).to_dict()

        self.assertEqual(trace["binding"], {"sessionId": "session:1", "roomId": "room:1", "sourceLoopId": "loop:1"})
        self.assertEqual(len(trace["evidence"]), 1)
        self.assertEqual(len(trace["artifacts"]), 1)

    def test_room_binding_reads_authoritative_work_and_case_ids_from_metadata(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:room-correlation:one",
                    "spanId": "span:room:one",
                    "name": "room.work",
                    "status": "running",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": None,
                    "durationMs": None,
                    "attributes": {
                        "workItemId": "work:one",
                        "caseId": "case:one",
                    },
                },
                {
                    "traceId": "trace:room-correlation:one",
                    "spanId": "span:room:two",
                    "name": "room.work",
                    "status": "completed",
                    "createdAtMs": 2,
                    "startedAtMs": 2,
                    "endedAtMs": 2,
                    "durationMs": 0,
                    "attributes": {
                        "workItemId": "work:one",
                        "caseId": "case:one",
                    },
                },
            ]
        ).to_dict()

        self.assertEqual(
            trace["binding"],
            {"workItemId": "work:one", "caseId": "case:one"},
        )

    def test_room_binding_omits_ambiguous_ids_instead_of_picking_one(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:room-correlation:ambiguous",
                    "spanId": "span:room:one",
                    "name": "room.work",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "attributes": {
                        "workItemId": "work:one",
                        "caseId": "case:one",
                    },
                },
                {
                    "traceId": "trace:room-correlation:ambiguous",
                    "spanId": "span:room:two",
                    "name": "room.work",
                    "status": "completed",
                    "createdAtMs": 2,
                    "startedAtMs": 2,
                    "endedAtMs": 2,
                    "durationMs": 0,
                    "attributes": {
                        "workItemId": "work:two",
                        "caseId": "case:two",
                    },
                },
            ]
        ).to_dict()

        self.assertNotIn("workItemId", trace["binding"])
        self.assertNotIn("caseId", trace["binding"])

    def test_room_partner_turn_links_are_explicit_deduped_and_not_inferred(self) -> None:
        observations = [
            {
                "traceId": "trace:room-turn:root",
                "spanId": "span:room:one",
                "name": "room.intercom",
                "status": "completed",
                "createdAtMs": 1,
                "startedAtMs": 1,
                "endedAtMs": 1,
                "durationMs": 0,
                "attributes": {
                    "acceptedTurnId": "turn:partner",
                    "sourceTurnId": "turn:partner",
                },
            },
            {
                "traceId": "trace:room-turn:root",
                "spanId": "span:room:two",
                "name": "room.intercom",
                "status": "completed",
                "createdAtMs": 2,
                "startedAtMs": 2,
                "endedAtMs": 2,
                "durationMs": 0,
                "participantId": "participant-turn-looking",
                "refs": [
                    {"kind": "participant", "id": "turn:not-a-session"},
                ],
                "attributes": {"acceptedTurnId": "turn:partner"},
            },
        ]

        trace = envelope_from_observations(observations).to_dict()

        self.assertEqual(
            trace["links"],
            [
                {
                    "traceId": "trace:turn:turn:partner",
                    "relation": "related",
                    "targetKind": "trace",
                }
            ],
        )

        without_explicit_turn = envelope_from_observations(
            [
                {
                    **observations[0],
                    "attributes": {},
                    "refs": [
                        {"kind": "participant", "id": "turn:not-a-session"},
                    ],
                }
            ]
        ).to_dict()
        self.assertNotIn("links", without_explicit_turn)

    def test_room_partner_turn_link_does_not_self_link(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:turn:partner",
                    "spanId": "span:room:one",
                    "name": "room.intercom",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "attributes": {"acceptedTurnId": "partner"},
                }
            ]
        ).to_dict()

        self.assertNotIn("links", trace)

    def test_operational_trace_link_refs_are_not_evidence(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:room-correlation:evidence",
                    "spanId": "span:room:one",
                    "name": "room.post",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "refs": [
                        {"kind": "trace_link", "id": "trace:turn:partner"},
                        {"kind": "knowledge", "id": "doc:one"},
                    ],
                }
            ]
        ).to_dict()

        self.assertEqual(
            [item["sourceRef"] for item in trace["evidence"]],
            ["doc:one"],
        )

    def test_operational_lifecycle_refs_are_never_eval_evidence(self) -> None:
        generic_only = envelope_from_observations(
            [
                {
                    "traceId": "trace:evidence:generic",
                    "spanId": "span:evidence:generic",
                    "name": "agent.event",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "refs": [
                        {"kind": kind, "id": f"{kind}:one"}
                        for kind in (
                            "active_rag",
                            "agent_event",
                            "agent_message",
                            "approval",
                            "browser_command",
                            "dispatch",
                            "input_generation",
                            "intercom",
                            "knowledge_retrieval",
                            "memory_recall",
                            "memory_run",
                            "participant",
                            "room_event",
                            "room_post",
                            "tool_call",
                            "work_item",
                        )
                    ],
                }
            ]
        ).to_dict()
        self.assertEqual(generic_only["evidence"], [])

        structured = envelope_from_observations(
            [
                {
                    "traceId": "trace:evidence:structured",
                    "spanId": "span:evidence:structured",
                    "name": "knowledge.retrieve",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "attributes": {
                        "evidenceStage": "retrieval_output",
                        "traceEvidence": [
                            {
                                "evidenceId": "knowledge:doc:one",
                                "sourceKind": "knowledge",
                                "sourceRef": "doc:one",
                                "sourceLane": "hybrid",
                                "disposition": "included",
                                "scores": {"score": 0.9},
                                "rankBefore": 2,
                                "rankAfter": 1,
                                "omissionReason": "",
                            }
                        ],
                    },
                    "refs": [
                        {"kind": "agent_event", "id": "agent:event:one"},
                        {"kind": "tool_call", "id": "tool:one"},
                        {"kind": "knowledge", "id": "doc:one"},
                    ],
                }
            ]
        ).to_dict()
        self.assertEqual(
            {
                (item["sourceKind"], item["sourceRef"], item["evidenceStage"])
                for item in structured["evidence"]
            },
            {
                ("knowledge", "doc:one", "observation_ref"),
                ("knowledge", "doc:one", "retrieval_output"),
            },
        )
        self.assertNotIn(
            ("agent_event", "agent:event:one"),
            {(item["sourceKind"], item["sourceRef"]) for item in structured["evidence"]},
        )
        self.assertNotIn(
            ("tool_call", "tool:one"),
            {(item["sourceKind"], item["sourceRef"]) for item in structured["evidence"]},
        )

    def test_active_trace_keeps_running_span_and_building_status(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:active:1",
                    "spanId": "span:turn:active",
                    "name": "turn",
                    "status": "running",
                    "sequence": 0,
                    "createdAtMs": 100,
                    "startedAtMs": 100,
                    "endedAtMs": None,
                    "durationMs": None,
                },
                {
                    "traceId": "trace:active:1",
                    "spanId": "span:tool:active",
                    "parentSpanId": "span:turn:active",
                    "name": "tool.call",
                    "status": "running",
                    "sequence": 1,
                    "createdAtMs": 110,
                    "startedAtMs": 110,
                    "endedAtMs": None,
                    "durationMs": None,
                },
            ]
        ).to_dict()

        self.assertEqual(trace["status"], "building")
        self.assertEqual(len(trace["spans"]), 2)
        self.assertFalse(trace["spans"][1]["recorded"])
        self.assertEqual(trace["spans"][1]["unavailableReason"], "duration_not_recorded")

    def test_room_root_fails_only_after_every_known_dispatch_is_terminal(self) -> None:
        def observation(
            span_id: str,
            status: str,
            sequence: int,
            *,
            parent_span_id: str = "",
            name: str = "room.dispatch",
        ) -> dict[str, object]:
            return {
                "traceId": "trace:room-turn:root-fence",
                "spanId": span_id,
                "parentSpanId": parent_span_id,
                "name": name,
                "status": status,
                "sequence": sequence,
                "createdAtMs": 100 + sequence,
                "startedAtMs": 100 + sequence,
                "endedAtMs": 100 + sequence if status in {"completed", "failed", "cancelled"} else None,
                "durationMs": 0 if status in {"completed", "failed", "cancelled"} else None,
            }

        root = observation(
            "span:room-turn:root-fence",
            "running",
            0,
            name="room.turn",
        )
        first = observation(
            "span:room-dispatch:first",
            "failed",
            1,
            parent_span_id="span:room-turn:root-fence",
        )
        second_running = observation(
            "span:room-dispatch:second",
            "running",
            2,
            parent_span_id="span:room-turn:root-fence",
        )

        building = envelope_from_observations([root, first, second_running]).to_dict()
        self.assertEqual(building["status"], "failed")
        building_root = next(item for item in building["spans"] if item["spanId"] == root["spanId"])
        self.assertEqual(building_root["status"], "running")

        second_complete = observation(
            "span:room-dispatch:second",
            "completed",
            3,
            parent_span_id="span:room-turn:root-fence",
        )
        terminal = envelope_from_observations([root, first, second_running, second_complete]).to_dict()
        terminal_root = next(item for item in terminal["spans"] if item["spanId"] == root["spanId"])
        self.assertEqual(terminal_root["status"], "failed")
        self.assertEqual(terminal_root["attributes"]["terminalDispatchCount"], 2)

    def test_observation_records_become_one_ordered_common_trace(self) -> None:
        observations = [
            {
                "traceId": "trace:sgg:1",
                "spanId": "span:retrieve",
                "parentSpanId": "",
                "sessionId": "session:sgg",
                "turnId": "turn:1",
                "runId": "run:sgg",
                "category": "retrieval",
                "phase": "retrieval_complete",
                "name": "rag.retrieve",
                "status": "completed",
                "createdAtMs": 100,
                "startedAtMs": 100,
                "endedAtMs": 135,
                "durationMs": 35,
                "attributes": {
                    "targetParticipantId": "participant-b",
                    "promptText": "PRIVATE_PROMPT",
                    "prompt_text": "PRIVATE_PROMPT_SNAKE",
                    "prompt.text": "PRIVATE_PROMPT_DOTTED",
                },
                "refs": [{"kind": "knowledge", "id": "doc:revenue", "label": "收入表"}],
            },
            {
                "traceId": "trace:sgg:1",
                "spanId": "span:judge",
                "parentSpanId": "span:retrieve",
                "sessionId": "session:sgg",
                "turnId": "turn:1",
                "runId": "run:sgg",
                "category": "agent",
                "phase": "judge_waiting",
                "name": "eval.judge",
                "status": "waiting",
                "createdAtMs": 140,
                "startedAtMs": 140,
                "endedAtMs": None,
                "durationMs": None,
                "refs": [],
            },
        ]

        trace = envelope_from_observations(
            observations,
            input_text="PRIVATE 掌柜问数输入",
        ).to_dict()

        self.assertEqual(trace["traceId"], "trace:sgg:1")
        self.assertEqual(trace["sourceKind"], "retrieval")
        self.assertEqual(trace["binding"]["runId"], "run:sgg")
        self.assertEqual(trace["input"]["fingerprint"], fingerprint_text("PRIVATE 掌柜问数输入"))
        self.assertEqual(trace["spans"][0]["durationMs"], 35)
        self.assertEqual(trace["spans"][0]["attributes"]["targetParticipantId"], "participant-b")
        self.assertNotIn("promptText", trace["spans"][0]["attributes"])
        self.assertNotIn("prompt_text", trace["spans"][0]["attributes"])
        self.assertNotIn("prompt.text", trace["spans"][0]["attributes"])
        self.assertEqual(trace["spans"][1]["status"], "waiting")
        self.assertIsNone(trace["spans"][1]["durationMs"])
        self.assertEqual(trace["evidence"][0]["sourceRef"], "doc:revenue")
        self.assertNotIn("PRIVATE 掌柜问数输入", str(trace))

    def test_input_generation_adapter_rejects_contradictory_terminal_statuses(self) -> None:
        common = {
            "traceId": "trace:input-generation:adapter-fence",
            "spanId": "span:input-generation:adapter-fence",
            "category": "runtime",
            "name": "input.generation",
            "startedAtMs": 100,
            "requestId": "surface-adapter-fence",
            "attributes": {"sourceKind": "input_generation"},
        }
        records = [
            {
                **common,
                "sequence": 1,
                "phase": "completed",
                "status": "completed",
                "createdAtMs": 125,
                "endedAtMs": 125,
                "durationMs": 25,
            },
            {
                **common,
                "sequence": 2,
                "phase": "failed",
                "status": "failed",
                "createdAtMs": 126,
                "endedAtMs": 126,
                "durationMs": 26,
            },
        ]

        with self.assertRaisesRegex(TraceContractError, "contradictory input-generation terminal"):
            envelope_from_observations(records)

    def test_input_generation_adapter_uses_lifecycle_phase_when_wall_clock_rolls_back(self) -> None:
        records = [
            {
                "traceId": "trace:input-generation:clock-rollback",
                "spanId": "span:input-generation:clock-rollback",
                "category": "runtime",
                "name": "input.generation",
                "phase": "started",
                "status": "running",
                "createdAtMs": 100_000,
                "startedAtMs": 100_000,
                "attributes": {"sourceKind": "input_generation"},
            },
            {
                "traceId": "trace:input-generation:clock-rollback",
                "spanId": "span:input-generation:clock-rollback",
                "category": "runtime",
                "name": "input.generation",
                "phase": "completed",
                "status": "completed",
                "createdAtMs": 99_000,
                "startedAtMs": 100_000,
                "endedAtMs": 100_000,
                "durationMs": 2_345,
                "attributes": {"sourceKind": "input_generation"},
            },
        ]

        trace = envelope_from_observations(records).to_dict()
        self.assertEqual(trace["status"], "completed")
        self.assertFalse(trace["spans"][0]["recorded"])
        self.assertEqual(trace["spans"][0]["unavailableReason"], "inconsistent_timing")

    def test_observation_adapter_uses_first_valid_fingerprint_across_ordered_records(self) -> None:
        first_valid = "sha256:" + "b" * 64
        later_valid = "sha256:" + "c" * 64
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:fingerprint:1",
                    "spanId": "span:fingerprint:first",
                    "status": "completed",
                    "name": "first",
                    "createdAtMs": 30,
                    "startedAtMs": 30,
                    "endedAtMs": 30,
                    "durationMs": 0,
                    "attributes": {"inputFingerprint": "sha256:not-valid"},
                },
                {
                    "traceId": "trace:fingerprint:1",
                    "spanId": "span:fingerprint:second",
                    "status": "completed",
                    "name": "second",
                    "createdAtMs": 40,
                    "startedAtMs": 40,
                    "endedAtMs": 40,
                    "durationMs": 0,
                    "attributes": {"inputFingerprint": first_valid},
                },
                {
                    "traceId": "trace:fingerprint:1",
                    "spanId": "span:fingerprint:third",
                    "status": "completed",
                    "name": "third",
                    "createdAtMs": 50,
                    "startedAtMs": 50,
                    "endedAtMs": 50,
                    "durationMs": 0,
                    "attributes": {"inputFingerprint": later_valid},
                },
            ]
        ).to_dict()

        self.assertEqual(trace["input"]["fingerprint"], first_valid)

    def test_active_rag_receipt_becomes_stage_specific_common_evidence(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:active-rag:1",
                    "spanId": "span:active-rag:1:retrieval",
                    "sessionId": "active-rag:1",
                    "runId": "active-rag:1",
                    "category": "retrieval",
                    "name": "active_rag_retrieval",
                    "status": "completed",
                    "createdAtMs": 120,
                    "startedAtMs": 100,
                    "endedAtMs": 120,
                    "durationMs": 20,
                    "refs": [
                        {"kind": "active_rag", "id": "active-rag:1"},
                        {"kind": "retrieval_evidence", "id": "hit:memory-7"},
                    ],
                    "attributes": {
                        "evidenceStage": "retrieval_output",
                        "traceEvidence": [
                            {
                                "evidenceId": "hit:memory-7",
                                "sourceKind": "memory",
                                "sourceRef": "memory:7",
                                "sourceLane": "vector_raw",
                                "disposition": "included",
                                "scores": {"score": -0.25, "confidence": 0.8},
                                "rankBefore": 4,
                                "rankAfter": 1,
                                "omissionReason": "",
                                "text": "PRIVATE_EVIDENCE_TEXT",
                            }
                        ],
                    },
                }
            ]
        ).to_dict()

        evidence = next(item for item in trace["evidence"] if item["evidenceId"] == "hit:memory-7")
        self.assertEqual(evidence["sourceKind"], "memory")
        self.assertEqual(evidence["sourceRef"], "memory:7")
        self.assertEqual(evidence["sourceLane"], "vector_raw")
        self.assertEqual(evidence["evidenceStage"], "retrieval_output")
        self.assertEqual(evidence["scores"]["score"], -0.25)
        self.assertEqual(evidence["rankBefore"], 4)
        self.assertEqual(evidence["rankAfter"], 1)
        self.assertFalse(any(item["evidenceId"] == "retrieval_evidence:hit:memory-7" for item in trace["evidence"]))

    def test_structured_memory_and_knowledge_evidence_do_not_duplicate_their_refs(self) -> None:
        for ref_kind, trace_id in (
            ("memory_evidence", "trace:memory-recall:dedupe"),
            ("knowledge_evidence", "trace:knowledge-retrieval:dedupe"),
        ):
            with self.subTest(ref_kind=ref_kind):
                trace = envelope_from_observations(
                    [
                        {
                            "traceId": trace_id,
                            "spanId": f"span:{ref_kind}:dedupe",
                            "name": ref_kind,
                            "status": "completed",
                            "createdAtMs": 100,
                            "startedAtMs": 100,
                            "endedAtMs": 100,
                            "durationMs": 0,
                            "attributes": {
                                "evidenceStage": "retrieval_output",
                                "traceEvidence": [
                                    {
                                        "evidenceId": "evidence:shared",
                                        "sourceKind": "memory",
                                        "sourceRef": "memory:shared",
                                        "sourceLane": "vector_raw",
                                        "disposition": "included",
                                        "scores": {"score": 0.9},
                                        "rankBefore": 1,
                                        "rankAfter": 1,
                                        "omissionReason": "",
                                    }
                                ],
                            },
                            "refs": [{"kind": ref_kind, "id": "evidence:shared"}],
                        }
                    ]
                ).to_dict()

                self.assertEqual(
                    [item["evidenceId"] for item in trace["evidence"]],
                    ["evidence:shared"],
                )

    def test_room_structured_evidence_does_not_count_lifecycle_refs_as_eval_evidence(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:room:structured-evidence",
                    "spanId": "span:room:work",
                    "name": "room.work",
                    "status": "completed",
                    "createdAtMs": 1,
                    "startedAtMs": 1,
                    "endedAtMs": 1,
                    "durationMs": 0,
                    "attributes": {
                        "evidenceStage": "work_review",
                        "traceEvidence": [
                            {
                                "evidenceId": "room_evidence_ref:abc",
                                "sourceKind": "room_evidence_ref",
                                "sourceRef": "trace:review:one",
                                "sourceLane": "room_work_item",
                                "disposition": "included",
                                "scores": {},
                                "rankBefore": None,
                                "rankAfter": None,
                                "omissionReason": "",
                            }
                        ],
                    },
                    "metrics": {"evidenceCount": 1},
                    "refs": [
                        {"kind": "room_event", "id": "room:event:one"},
                        {"kind": "participant", "id": "participant:one"},
                        {"kind": "dispatch", "id": "dispatch:one"},
                        {"kind": "work_item", "id": "work:one"},
                    ],
                },
                {
                    "traceId": "trace:room:structured-evidence",
                    "spanId": "span:room:work",
                    "name": "room.work",
                    "status": "completed",
                    "createdAtMs": 2,
                    "startedAtMs": 1,
                    "endedAtMs": 2,
                    "durationMs": 1,
                    "attributes": {},
                    "metrics": {},
                    "refs": [
                        {"kind": "room_event", "id": "room:event:two"},
                        {"kind": "work_item", "id": "work:one"},
                    ],
                },
            ]
        ).to_dict()

        span = trace["spans"][0]
        self.assertEqual(span["status"], "completed")
        self.assertEqual(span["attributes"]["evidenceStage"], "work_review")
        self.assertEqual(span["metrics"]["evidenceCount"], 1)
        self.assertEqual(
            [(item["sourceKind"], item["sourceRef"]) for item in trace["evidence"]],
            [("room_evidence_ref", "trace:review:one")],
        )
        self.assertNotIn("PRIVATE_EVIDENCE_TEXT", str(trace))

    def test_missing_duration_is_unavailable_even_when_terminal_event_has_end(self) -> None:
        trace = envelope_from_observations(
            [
                {
                    "traceId": "trace:memory:1",
                    "spanId": "span:memory:1",
                    "parentSpanId": "",
                    "category": "memory",
                    "status": "completed",
                    "name": "memory.curation",
                    "phase": "completed",
                    "createdAtMs": 200,
                    "startedAtMs": 200,
                    "endedAtMs": 220,
                    "durationMs": None,
                    "refs": [],
                }
            ]
        ).to_dict()

        span = trace["spans"][0]
        self.assertFalse(span["recorded"])
        self.assertIsNone(span["durationMs"])
        self.assertEqual(span["unavailableReason"], "duration_not_recorded")

    def test_adapter_rejects_empty_or_mixed_trace_ids(self) -> None:
        with self.assertRaisesRegex(TraceContractError, "at least one"):
            envelope_from_observations([])
        with self.assertRaisesRegex(TraceContractError, "same trace"):
            envelope_from_observations(
                [
                    {"traceId": "trace:1", "spanId": "span:1", "status": "completed", "createdAtMs": 1, "startedAtMs": 1, "endedAtMs": 1, "durationMs": 0},
                    {"traceId": "trace:2", "spanId": "span:2", "status": "completed", "createdAtMs": 2, "startedAtMs": 2, "endedAtMs": 2, "durationMs": 0},
                ]
            )


if __name__ == "__main__":
    unittest.main()
