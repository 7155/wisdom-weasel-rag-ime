from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_protocol import AgentEventEnvelope
from rag_ime.agent_service import AgentService
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.observability import ObservationHub
from rag_ime.trace_adapters import envelope_from_observations


class KnowledgeToolTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rag-ime-knowledge-tool-trace-")
        self.hub = ObservationHub(Path(self.temporary.name) / "rag-ime.sqlite")

    def tearDown(self) -> None:
        self.hub.close()
        self.temporary.cleanup()

    def test_knowledge_search_tool_result_enters_the_turn_trace_as_retrieval(self) -> None:
        public_result = {
            "activityKind": "knowledge_retrieval",
            "operation": "search",
            "kbId": "kb:project-docs",
            "retrievalMode": "hybrid",
            "evidenceStage": "retrieval_output",
            "evidenceCount": 1,
            "traceEvidence": [
                {
                    "evidenceId": "knowledge:kb:project-docs:chunk:grounding",
                    "sourceKind": "knowledge",
                    "sourceRef": "knowledge://kb:project-docs/chunk:grounding",
                    "sourceLane": "hybrid",
                    "disposition": "included",
                    "scores": {"score": 0.91},
                    "rankBefore": None,
                    "rankAfter": 1,
                    "omissionReason": "",
                }
            ],
            "query": "PRIVATE_QUERY_IN_PUBLIC_RESULT",
            "content": "PRIVATE_CONTENT_IN_PUBLIC_RESULT",
        }
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-knowledge:1",
                session_id="session-knowledge",
                turn_id="turn-knowledge",
                sequence=1,
                created_at_ms=100,
                event_type="tool_finished",
                payload={
                    "toolCallId": "call-knowledge-search",
                    "toolName": "knowledge",
                    "args": {"query": "PRIVATE_QUERY", "operation": "search"},
                    "result": {"content": "PRIVATE_RESULT"},
                    "publicResult": public_result,
                    "durationMs": 42,
                    "isError": False,
                },
                resume_token="session-knowledge:1",
            )
        )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot({"traceId": "trace:turn:turn-knowledge"})
        self.assertEqual(snapshot["counts"]["total"], 1)
        event = snapshot["items"][0]
        self.assertEqual(event["category"], "retrieval")
        self.assertEqual(event["name"], "knowledge.retrieval")
        self.assertEqual(event["spanId"], "span:tool:call-knowledge-search")
        self.assertEqual(event["sessionId"], "session-knowledge")
        self.assertEqual(event["turnId"], "turn-knowledge")
        self.assertEqual(event["durationMs"], 42)
        self.assertEqual(event["metrics"]["evidenceCount"], 1)
        self.assertEqual(event["attributes"]["sourceKind"], "knowledge")
        self.assertEqual(event["attributes"]["retrievalMode"], "hybrid")
        self.assertEqual(event["attributes"]["evidenceStage"], "retrieval_output")
        self.assertEqual(event["attributes"]["knowledgeBaseId"], "kb:project-docs")
        self.assertEqual(
            event["attributes"]["traceEvidence"][0]["sourceRef"],
            "knowledge://kb:project-docs/chunk:grounding",
        )
        self.assertTrue(
            any(
                ref["kind"] == "retrieval_evidence"
                and ref["id"] == "knowledge:kb:project-docs:chunk:grounding"
                for ref in event["refs"]
            )
        )

        trace = envelope_from_observations(snapshot["items"]).to_dict()
        self.assertEqual(trace["sourceKind"], "knowledge")
        self.assertEqual(trace["binding"]["sessionId"], "session-knowledge")
        self.assertEqual(trace["binding"]["turnId"], "turn-knowledge")
        self.assertEqual(trace["spans"][0]["name"], "knowledge.retrieval")
        self.assertEqual(
            trace["spans"][0]["attributes"]["knowledgeBaseId"],
            "kb:project-docs",
        )
        knowledge_evidence = next(
            item for item in trace["evidence"] if item["sourceKind"] == "knowledge"
        )
        self.assertEqual(
            knowledge_evidence["sourceRef"],
            "knowledge://kb:project-docs/chunk:grounding",
        )
        self.assertFalse(
            any(
                str(item["evidenceId"]).startswith(("agent_event:", "tool_call:"))
                for item in trace["evidence"]
            )
        )

        service = AgentService.__new__(AgentService)
        service.observations = self.hub
        service.eval_runs = EvalRunStore(Path(self.temporary.name) / "eval.sqlite")
        detail = service.observation_trace({"traceId": "trace:turn:turn-knowledge"})
        evaluated = service.evaluate_observation_evidence(
            {
                "schemaVersion": "rag-ime.observability-evidence-eval-request.v1",
                "traceId": "trace:turn:turn-knowledge",
                "requiredEvidenceIds": [
                    "knowledge:kb:project-docs:chunk:grounding"
                ],
                "datasetId": "manual:knowledge-tool-trace",
                "labelRevision": "review:knowledge-tool-trace-1",
                "truthKind": "human",
            }
        )
        self.assertEqual(detail["trace"]["sourceKind"], "knowledge")
        self.assertEqual(
            evaluated["metrics"],
            {"precision": 1.0, "recall": 1.0, "f1": 1.0},
        )
        self.assertEqual(
            service.observation_evals({"traceId": "trace:turn:turn-knowledge"})[
                "items"
            ][0]["evalRunId"],
            evaluated["evalRunId"],
        )
        serialized = json.dumps({"snapshot": snapshot, "trace": trace}, ensure_ascii=False)
        for secret in (
            "PRIVATE_QUERY",
            "PRIVATE_RESULT",
            "PRIVATE_CONTENT",
        ):
            self.assertNotIn(secret, serialized)

    def test_knowledge_search_transport_failure_stays_failed_without_public_error_text(
        self,
    ) -> None:
        self.hub.enqueue_agent_event(
            AgentEventEnvelope(
                event_id="session-knowledge-failed:1",
                session_id="session-knowledge-failed",
                turn_id="turn-knowledge-failed",
                sequence=1,
                created_at_ms=200,
                event_type="tool_finished",
                payload={
                    "toolCallId": "call-knowledge-failed",
                    "toolName": "knowledge",
                    "args": {
                        "operation": "search",
                        "kbId": "kb:project-docs",
                        "query": "PRIVATE_FAILED_QUERY",
                    },
                    "result": {"error": "PRIVATE_TRANSPORT_ERROR"},
                    "publicResult": {
                        "activityKind": "knowledge_retrieval",
                        "operation": "search",
                        "kbId": "kb:project-docs",
                        "evidenceStage": "retrieval_output",
                        "evidenceCount": 0,
                        "traceEvidence": [],
                    },
                    # Knowledge Tools raise at their execution boundary. Pi's
                    # transport error bit, rather than an ad-hoc `{ok:false}`
                    # result convention, is therefore the terminal authority.
                    "isError": True,
                },
                resume_token="session-knowledge-failed:1",
            )
        )
        self.assertTrue(self.hub.flush())

        snapshot = self.hub.snapshot(
            {"traceId": "trace:turn:turn-knowledge-failed"}
        )
        self.assertEqual(snapshot["counts"]["total"], 1)
        self.assertEqual(snapshot["items"][0]["status"], "failed")
        trace = envelope_from_observations(snapshot["items"]).to_dict()
        self.assertEqual(trace["status"], "failed")
        self.assertEqual(trace["spans"][0]["status"], "failed")
        self.assertEqual(trace["spans"][0]["attributes"]["knowledgeBaseId"], "kb:project-docs")
        serialized = json.dumps(
            {"snapshot": snapshot, "trace": trace},
            ensure_ascii=False,
        )
        self.assertNotIn("PRIVATE_FAILED_QUERY", serialized)
        self.assertNotIn("PRIVATE_TRANSPORT_ERROR", serialized)


if __name__ == "__main__":
    unittest.main()
