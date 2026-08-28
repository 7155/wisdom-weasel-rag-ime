from __future__ import annotations

import os
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import patch

from rag_ime.active_rag_service import ActiveRagService, ActiveRagStartRequest
from rag_ime.agent_service import AgentService
from rag_ime.agent_surface_runtime import AgentSurfaceRuntime
from rag_ime.contracts.json_schema import load_contract, validate_contract
from rag_ime.control_api import ControlAccessContext, ControlPathId, ControlScope, default_route_policy
from rag_ime.debug_server import DebugImeService, DebugRequestHandler
from rag_ime.deepseek_completion import CompletionCandidateDelta
from rag_ime.observability import ObservationHub
from rag_ime.text_utils import stable_text_hash
from rag_ime.trace_adapters import envelope_from_browser_trace, envelope_from_prediction_frame
from rag_ime.trace_runtime import TraceContractError, build_trace_envelope


def _observation(*, sequence: int = 1, status: str = "completed") -> dict[str, object]:
    return {
        "traceId": "trace:api:1",
        "spanId": "span:api:1",
        "parentSpanId": "",
        "sessionId": "session:api",
        "turnId": "turn:api",
        "runId": "run:api",
        "sequence": sequence,
        "category": "agent",
        "name": "turn",
        "status": status,
        "createdAtMs": 100 + sequence,
        "startedAtMs": 100 + sequence,
        "endedAtMs": 100 + sequence if status == "completed" else None,
        "durationMs": 0 if status == "completed" else None,
        "metrics": {},
        "attributes": {},
        "refs": [],
    }


class _ObservationReader:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot_value = snapshot
        self.calls: list[dict[str, object]] = []

    def snapshot(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(payload)
        return self.snapshot_value


def _invoke_get(service: object, path: str) -> tuple[object, dict[str, object]]:
    class Handler(DebugRequestHandler):
        pass

    handler = Handler.__new__(Handler)
    handler.service = service  # type: ignore[assignment]
    handler.path = path
    handler._authorize_gateway_request = lambda method, parsed: True  # type: ignore[method-assign]
    handler._serve_gateway_static = lambda request_path: False  # type: ignore[method-assign]
    responses: list[tuple[object, dict[str, object]]] = []
    handler._write_json = lambda status, payload, **kwargs: responses.append((status, payload))  # type: ignore[method-assign]
    handler.do_GET()
    if len(responses) != 1:
        raise AssertionError(f"expected one response, received {len(responses)}")
    return responses[0]


class ObservabilityTraceServiceTests(unittest.TestCase):
    def test_browser_trace_resolver_tolerates_a_release_browser_without_exact_reader(self) -> None:
        service = DebugImeService.__new__(DebugImeService)
        service.browser_control = SimpleNamespace()

        resolved = service._resolve_external_common_trace(
            "trace:browser:command:bcmd_legacy_release"
        )

        self.assertIsNone(resolved)

    def test_surface_generation_callback_reaches_the_common_trace_api(self) -> None:
        class Runtime:
            def complete_once(self, **_kwargs):
                return {
                    "text": "PRIVATE GENERATED ANSWER",
                    "elapsedMs": 25,
                    "firstTokenMs": 9,
                    "usage": {"inputTokens": 11, "outputTokens": 4, "totalTokens": 15},
                }

        wall_clock_values = iter((1.0, 1.025))
        monotonic_clock_values = iter((10.0, 10.025))
        with tempfile.TemporaryDirectory(prefix="input-generation-trace-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            try:
                surface = AgentSurfaceRuntime(
                    SimpleNamespace(runtime=Runtime()),
                    settings_provider=lambda: {"activeRag": {
                        "quickModel": "deepseek/deepseek-v4-flash",
                        "quickThinkingLevel": "high",
                    }},
                    observation_callback=observations.enqueue_input_generation_record,
                    clock=lambda: next(wall_clock_values),
                    monotonic_clock=lambda: next(monotonic_clock_values),
                )
                surface.complete({
                    "privacyDisposition": "allowed",
                    "requestId": "surface-e2e-1",
                    "frontAppBundleId": "com.example.Editor",
                    "currentRequest": "PRIVATE USER REQUEST",
                })
                self.assertTrue(observations.flush())
                snapshot = observations.snapshot({"category": "runtime"})
                self.assertEqual(len(snapshot["items"]), 2)
                trace_id = str(snapshot["items"][0]["traceId"])

                service = AgentService.__new__(AgentService)
                service.observations = observations
                detail = service.observation_trace({"traceId": trace_id})

                self.assertEqual(detail["projectionSource"], "observation_journal")
                self.assertEqual(detail["trace"]["sourceKind"], "input_generation")
                self.assertEqual(detail["trace"]["status"], "completed")
                self.assertEqual(detail["trace"]["spans"][0]["durationMs"], 25)
                self.assertEqual(detail["trace"]["spans"][0]["metrics"]["totalTokens"], 15)
                serialized = repr(detail)
                self.assertNotIn("PRIVATE USER REQUEST", serialized)
                self.assertNotIn("PRIVATE GENERATED ANSWER", serialized)
            finally:
                observations.close()

    def test_active_rag_enqueue_preserves_measured_stage_timing_in_trace_api(self) -> None:
        with tempfile.TemporaryDirectory(prefix="active-rag-trace-api-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            try:
                base = {
                    "sessionId": "active-rag:trace-api",
                    "status": "ready",
                    "request": {
                        "selectedText": {"chars": 4},
                        "currentContext": {"chars": 8},
                        "providedEvidenceCount": 0,
                    },
                    "retrieval": {"evidenceCount": 0},
                    "generation": {"candidateCount": 1},
                    "stageTiming": {
                        "context": {"startedAtMs": 100},
                        "retrieval": {
                            "startedAtMs": 110,
                            "endedAtMs": 125,
                            "durationMs": 15,
                        },
                        "generation": {
                            "startedAtMs": 130,
                            "endedAtMs": 170,
                            "durationMs": 40,
                        },
                    },
                }
                observations.enqueue_active_rag_record(
                    {**base, "timestampMs": 100, "phase": "started", "stageStatus": {"context": "completed"}}
                )
                observations.enqueue_active_rag_record(
                    {
                        **base,
                        "timestampMs": 125,
                        "phase": "retrieval_complete",
                        "stageStatus": {"retrieval": "completed"},
                    }
                )
                observations.enqueue_active_rag_record(
                    {
                        **base,
                        "timestampMs": 170,
                        "phase": "ready",
                        "traceStatus": "completed",
                        "stageStatus": {
                            "retrieval": "completed",
                            "generation": "completed",
                        },
                    }
                )
                self.assertTrue(observations.flush())
                service = AgentService.__new__(AgentService)
                service.observations = observations
                result = service.observation_trace({"traceId": "trace:active-rag:active-rag:trace-api"})

                spans = {span["name"]: span for span in result["trace"]["spans"]}
                self.assertEqual(result["projectionSource"], "observation_journal")
                self.assertEqual(spans["active_rag_retrieval"]["durationMs"], 15)
                self.assertEqual(spans["active_rag_generation"]["durationMs"], 40)
                self.assertEqual(spans["active_rag_retrieval"]["startedAtMs"], 110)
                self.assertEqual(spans["active_rag_generation"]["startedAtMs"], 130)
            finally:
                observations.close()

    def test_active_rag_timeout_trace_stays_building_then_same_generation_span_settles(self) -> None:
        class BlockingProvider:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def stream_candidates(self, _request):
                self.started.set()
                self.release.wait(timeout=2)
                yield CompletionCandidateDelta(text="最终候选", insert_text="最终候选")

        with tempfile.TemporaryDirectory(prefix="active-rag-trace-timeout-e2e-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            provider = BlockingProvider()
            service = ActiveRagService(
                completion_provider=provider,
                observation_observer=observations.enqueue_active_rag_record,
            )
            request = ActiveRagStartRequest(
                selected_text="超时 Trace 终态",
                selected_text_hash=stable_text_hash("超时 Trace 终态"),
                frontend_revision=1,
                selection_epoch=1,
                context="验证 timeout 生命周期",
                evidence_pack=({"surfaceHints": ["候选"]},),
                latency_budget_ms=120_000,
            )
            try:
                with patch.dict(os.environ, {"RAG_IME_DEEPSEEK_ACTIVE_RAG": "1"}):
                    started = service.start(request)
                    session_id = str(started["sessionId"])
                    self.assertTrue(provider.started.wait(timeout=1))
                    with service._lock:
                        service._sessions[session_id].created_at_ms -= 121_000
                    visible = service.status(session_id)
                    self.assertEqual(visible["status"], "ready")
                    self.assertTrue(observations.flush())

                    service_double = AgentService.__new__(AgentService)
                    service_double.observations = observations
                    trace_id = f"trace:active-rag:{session_id}"
                    building = service_double.observation_trace({"traceId": trace_id})
                    self.assertEqual(building["trace"]["status"], "building")
                    building_generation = next(
                        span for span in building["trace"]["spans"]
                        if span["name"] == "active_rag_generation"
                    )
                    self.assertEqual(building_generation["status"], "running")
                    self.assertFalse(building_generation["recorded"])

                    provider.release.set()
                    deadline = time.monotonic() + 2
                    final = None
                    while time.monotonic() < deadline:
                        observations.flush()
                        try:
                            candidate = service_double.observation_trace({"traceId": trace_id})
                        except KeyError:
                            candidate = None
                        if candidate is not None and candidate["trace"]["status"] == "completed":
                            final = candidate
                            break
                        time.sleep(0.01)
                    self.assertIsNotNone(final)
                    assert final is not None
                    spans = [
                        span for span in final["trace"]["spans"]
                        if span["name"] == "active_rag_generation"
                    ]
                    self.assertEqual(len(spans), 1)
                    self.assertEqual(spans[0]["status"], "completed")
                    self.assertTrue(spans[0]["recorded"])
                    self.assertIsInstance(spans[0]["durationMs"], int)
            finally:
                observations.close()

    def test_active_rag_cancel_during_retrieval_trace_has_no_generation_span(self) -> None:
        with tempfile.TemporaryDirectory(prefix="active-rag-trace-cancel-e2e-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            service = ActiveRagService(
                observation_observer=observations.enqueue_active_rag_record,
            )
            retrieval_started = threading.Event()
            release_retrieval = threading.Event()

            def blocked_retrieval(*_args, **_kwargs):
                retrieval_started.set()
                release_retrieval.wait(timeout=2)
                return ()

            service._retrieve_local_evidence = blocked_retrieval  # type: ignore[method-assign]
            request = ActiveRagStartRequest(
                selected_text="检索中取消 Trace",
                selected_text_hash=stable_text_hash("检索中取消 Trace"),
                frontend_revision=1,
                selection_epoch=1,
            )
            try:
                started = service.start(request)
                session_id = str(started["sessionId"])
                self.assertTrue(retrieval_started.wait(timeout=1))
                service.cancel(session_id)
                release_retrieval.set()
                time.sleep(0.05)
                self.assertTrue(observations.flush())

                service_double = AgentService.__new__(AgentService)
                service_double.observations = observations
                result = service_double.observation_trace(
                    {"traceId": f"trace:active-rag:{session_id}"}
                )
                spans = result["trace"]["spans"]
                self.assertEqual(result["trace"]["status"], "cancelled")
                self.assertEqual({span["name"] for span in spans}, {"active_rag_context", "active_rag_retrieval"})
                retrieval = next(span for span in spans if span["name"] == "active_rag_retrieval")
                self.assertEqual(retrieval["status"], "cancelled")
            finally:
                observations.close()

    def test_active_rag_direct_retrieval_exception_is_failed_without_generation_span(self) -> None:
        with tempfile.TemporaryDirectory(prefix="active-rag-trace-retrieval-failure-e2e-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            service = ActiveRagService(
                observation_observer=observations.enqueue_active_rag_record,
            )

            def fail_retrieval(*_args, **_kwargs):
                raise RuntimeError("PRIVATE retrieval failure")

            service._retrieve_local_evidence = fail_retrieval  # type: ignore[method-assign]
            request = ActiveRagStartRequest(
                selected_text="直接检索异常 Trace",
                selected_text_hash=stable_text_hash("直接检索异常 Trace"),
                frontend_revision=1,
                selection_epoch=1,
            )
            try:
                started = service.start(request)
                session_id = str(started["sessionId"])
                deadline = time.monotonic() + 2
                visible = service.status(session_id)
                while visible["status"] == "pending" and time.monotonic() < deadline:
                    time.sleep(0.01)
                    visible = service.status(session_id)
                self.assertEqual(visible["status"], "ready")
                self.assertTrue(observations.flush())

                service_double = AgentService.__new__(AgentService)
                service_double.observations = observations
                result = service_double.observation_trace(
                    {"traceId": f"trace:active-rag:{session_id}"}
                )

                self.assertEqual(result["trace"]["status"], "failed")
                spans = result["trace"]["spans"]
                self.assertEqual(
                    {span["name"] for span in spans},
                    {"active_rag_context", "active_rag_retrieval"},
                )
                retrieval = next(
                    span for span in spans if span["name"] == "active_rag_retrieval"
                )
                self.assertEqual(retrieval["status"], "failed")
                self.assertNotIn("PRIVATE retrieval failure", repr(result))
            finally:
                observations.close()

    def test_active_rag_fractional_stage_timing_is_unavailable_through_trace_api(self) -> None:
        with tempfile.TemporaryDirectory(prefix="active-rag-trace-fractional-timing-") as tmp:
            observations = ObservationHub(Path(tmp) / "observations.sqlite")
            try:
                observations.enqueue_active_rag_record(
                    {
                        "sessionId": "active-rag:fractional-timing",
                        "timestampMs": 130,
                        "phase": "ready",
                        "status": "ready",
                        "traceStatus": "completed",
                        "terminalStage": "generation",
                        "stageStatus": {
                            "retrieval": "completed",
                            "generation": "completed",
                        },
                        "stageTiming": {
                            "generation": {
                                "startedAtMs": 100.5,
                                "endedAtMs": 130.5,
                                "durationMs": 30.0,
                            },
                        },
                        "request": {},
                        "retrieval": {"evidenceCount": 0},
                        "generation": {"candidateCount": 1},
                    }
                )
                self.assertTrue(observations.flush())
                projected = observations.snapshot(
                    {"sessionId": "active-rag:fractional-timing"}
                )["items"][0]
                self.assertNotIn("stageTiming", projected)

                service = AgentService.__new__(AgentService)
                service.observations = observations
                result = service.observation_trace(
                    {"traceId": "trace:active-rag:active-rag:fractional-timing"}
                )
                generation = next(
                    span
                    for span in result["trace"]["spans"]
                    if span["name"] == "active_rag_generation"
                )
                self.assertFalse(generation["recorded"])
                self.assertIsNone(generation["endedAtMs"])
                self.assertIsNone(generation["durationMs"])
            finally:
                observations.close()

    def test_trace_get_embedded_trace_schema_stays_in_lockstep_with_envelope(self) -> None:
        envelope = load_contract("trace-envelope.v1.json")
        response = load_contract("observability-trace-get.v1.json")
        embedded = response["properties"]["trace"]

        self.assertEqual(embedded["required"], envelope["required"])
        self.assertEqual(embedded["properties"], envelope["properties"])
        self.assertEqual(
            response["$defs"],
            envelope["$defs"],
        )
        self.assertEqual(
            response["$defs"]["traceLink"]["properties"]["relation"]["enum"],
            ["retry", "related"],
        )

    def test_trace_get_accepts_legacy_and_current_trace_envelopes(self) -> None:
        legacy = build_trace_envelope(
            trace_id="trace:api:legacy",
            source_kind="agent",
            input_text="",
            now_ms=1,
        ).to_dict()
        current = build_trace_envelope(
            trace_id="trace:api:current",
            source_kind="vertical_agent",
            input_text="",
            binding={"workItemId": "work:sgg", "caseId": "case:001"},
            parent_trace_id="trace:api:root",
            links=(
                {
                    "traceId": "trace:api:retry",
                    "relation": "retry",
                    "targetKind": "trace",
                },
                {
                    "traceId": "trace:api:related",
                    "relation": "related",
                    "targetKind": "trace",
                },
            ),
            now_ms=1,
        ).to_dict()

        for trace in (legacy, current):
            with self.subTest(traceId=trace["traceId"]):
                validate_contract(
                    {
                        "schemaVersion": "rag-ime.observability-trace-get.v1",
                        "traceId": trace["traceId"],
                        "trace": trace,
                        "truncated": False,
                        "projectionSource": "source_adapter",
                        "observationWindow": {
                            "firstSequence": 0,
                            "lastSequence": 0,
                            "resumeToken": f"source:{trace['traceId']}",
                            "nextBeforeSequence": None,
                        },
                    },
                    "observability-trace-get.v1.json",
                )

    def test_service_projects_snapshot_without_persisting_a_second_trace(self) -> None:
        snapshot = {
            "items": [_observation(sequence=41)],
            "truncated": False,
            "firstSequence": 1,
            "lastSequence": 99,
            "resumeToken": "observation:99",
        }
        reader = _ObservationReader(snapshot)
        service = AgentService.__new__(AgentService)
        service.observations = reader  # type: ignore[attr-defined]

        result = service.observation_trace(
            {"traceId": "trace:api:1", "limit": "17", "beforeSequence": "33"}
        )

        self.assertEqual(reader.calls, [{"traceId": "trace:api:1", "limit": "17", "beforeSequence": "33"}])
        self.assertEqual(result["traceId"], "trace:api:1")
        self.assertEqual(result["trace"]["schemaVersion"], "rag-ime.trace-envelope.v1")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["observationWindow"]["firstSequence"], 41)
        self.assertEqual(result["observationWindow"]["lastSequence"], 41)
        self.assertEqual(result["observationWindow"]["resumeToken"], "observation:41")
        self.assertIsNone(result["observationWindow"]["nextBeforeSequence"])

    def test_truncated_snapshot_cannot_claim_completed(self) -> None:
        snapshot = {
            "items": [_observation(sequence=7)],
            "truncated": True,
            "firstSequence": 1,
            "lastSequence": 9,
            "resumeToken": "observation:9",
        }
        service = AgentService.__new__(AgentService)
        service.observations = _ObservationReader(snapshot)  # type: ignore[attr-defined]

        result = service.observation_trace({"traceId": "trace:api:1"})

        self.assertTrue(result["truncated"])
        self.assertEqual(result["trace"]["status"], "building")
        self.assertEqual(result["observationWindow"]["firstSequence"], 7)
        self.assertEqual(result["observationWindow"]["lastSequence"], 7)
        self.assertEqual(result["observationWindow"]["resumeToken"], "observation:7")
        self.assertEqual(result["observationWindow"]["nextBeforeSequence"], 7)

    def test_missing_or_invalid_trace_is_rejected(self) -> None:
        service = AgentService.__new__(AgentService)
        service.observations = _ObservationReader(  # type: ignore[attr-defined]
            {
                "items": [],
                "truncated": False,
                "firstSequence": 0,
                "lastSequence": 0,
                "resumeToken": "observation:0",
            }
        )
        with self.assertRaises(KeyError):
            service.observation_trace({"traceId": "trace:missing"})
        with self.assertRaisesRegex(ValueError, "invalid_trace_id"):
            service.observation_trace({"traceId": "trace/api/1"})

    def test_trace_api_accepts_the_contract_maximum_id_and_rejects_one_more(self) -> None:
        maximum_trace_id = "t" + "a" * 159
        observation = {**_observation(), "traceId": maximum_trace_id}
        service = AgentService.__new__(AgentService)
        service.observations = _ObservationReader({  # type: ignore[attr-defined]
            "items": [observation],
            "truncated": False,
            "firstSequence": 1,
            "lastSequence": 1,
            "resumeToken": "observation:1",
        })

        result = service.observation_trace({"traceId": maximum_trace_id})

        self.assertEqual(result["traceId"], maximum_trace_id)
        with self.assertRaisesRegex(ValueError, "invalid_trace_id"):
            service.observation_trace({"traceId": maximum_trace_id + "a"})

    def test_source_owned_trace_resolver_uses_canonical_wrapper_without_journal_copy(self) -> None:
        trace_id = "trace:prediction:session-api:request-4"
        envelope = envelope_from_prediction_frame({
            "recordedAtMs": 200,
            "sessionId": "session-api",
            "requestSeq": 4,
            "ragLane": {"elapsedMs": 0},
            "display": {"visibleCandidateCount": 0},
        })
        service = AgentService.__new__(AgentService)
        service.observations = _ObservationReader({
            "items": [],
            "truncated": False,
            "firstSequence": 0,
            "lastSequence": 0,
            "resumeToken": "observation:0",
        })  # type: ignore[attr-defined]
        service._external_trace_resolvers = [
            lambda requested: envelope if requested == trace_id else None
        ]

        result = service.observation_trace({"traceId": trace_id})

        self.assertEqual(result["projectionSource"], "source_adapter")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["trace"]["sourceKind"], "rime_prediction")
        self.assertEqual(result["observationWindow"]["resumeToken"], f"source:{trace_id}")

    def test_source_authority_wins_over_a_discovery_journal_projection(self) -> None:
        trace_id = "trace:browser:command:bcmd_api_1"
        envelope = envelope_from_browser_trace({
            "commandId": "bcmd_api_1",
            "deviceId": "chrome-api",
            "sessionId": "session-api",
            "action": "navigate",
            "status": "completed",
            "createdAtMs": 100,
            "completedAtMs": 125,
            "durationMs": 25,
        })
        reader = _ObservationReader({
            "items": [{**_observation(), "traceId": trace_id, "category": "runtime"}],
            "truncated": False,
            "firstSequence": 1,
            "lastSequence": 1,
            "resumeToken": "observation:1",
        })
        service = AgentService.__new__(AgentService)
        service.observations = reader  # type: ignore[attr-defined]
        service._external_trace_resolvers = [lambda requested: envelope if requested == trace_id else None]

        result = service.observation_trace({"traceId": trace_id})

        self.assertEqual(result["projectionSource"], "source_adapter")
        self.assertEqual(result["trace"]["sourceKind"], "browser_control")
        self.assertEqual(result["trace"]["spans"][0]["durationMs"], 25)
        self.assertEqual(reader.calls, [])


class ObservabilityTraceRouteTests(unittest.TestCase):
    def test_route_policy_exposes_read_only_trace_get(self) -> None:
        policy = default_route_policy()
        route = policy.resolve(ControlPathId.OBSERVABILITY_TRACE_GET)
        self.assertEqual(route.local_8766_path, "/api/observability/traces/{traceId}")
        self.assertEqual(route.gateway_8768_path, "/control/v1/observability/traces/{traceId}")
        self.assertEqual(route.params, frozenset({"traceId"}))
        self.assertTrue(route.remote_safe)
        self.assertEqual(route.remote_scopes, frozenset({ControlScope.AGENT_READ.value}))

        policy.authorize_http(
            method="GET",
            path="/api/observability/traces/trace%3Aapi%3A1",
            query={},
            body={},
            context=ControlAccessContext.remote(
                device_id="device-1", scopes={ControlScope.AGENT_READ.value}
            ),
        )

    def test_request_handler_decodes_one_path_parameter_and_returns_wrapper(self) -> None:
        snapshot = {
            "items": [_observation()],
            "truncated": False,
            "firstSequence": 1,
            "lastSequence": 1,
            "resumeToken": "observation:1",
        }
        agent = SimpleNamespace(observation_trace=lambda payload: {
            "schemaVersion": "rag-ime.observability-trace-get.v1",
            "traceId": payload["traceId"],
            "trace": {
                "schemaVersion": "rag-ime.trace-envelope.v1",
                "traceId": payload["traceId"],
                "sourceKind": "agent",
                "status": "completed",
                "binding": {},
                "input": {
                    "fingerprint": "sha256:" + "0" * 64,
                    "contentPolicy": "hash_only",
                    "normalization": "none",
                },
                "spans": [], "evidence": [], "artifacts": [],
                "createdAtMs": 1, "updatedAtMs": 1,
            },
            "truncated": False,
            "projectionSource": "observation_journal",
            "observationWindow": {
                "firstSequence": 1, "lastSequence": 1,
                "resumeToken": "observation:1", "nextBeforeSequence": None,
            },
        })
        service = SimpleNamespace(agent=agent, config=SimpleNamespace(server_name="test"))

        status, payload = _invoke_get(
            service,
            f"/api/observability/traces/{quote('trace:api:1', safe='')}",
        )

        self.assertEqual(int(status), 200)
        self.assertEqual(payload["traceId"], "trace:api:1")

    def test_request_handler_not_found_uses_stable_trace_error_code(self) -> None:
        agent = SimpleNamespace(
            observation_trace=lambda payload: (_ for _ in ()).throw(KeyError(payload["traceId"]))
        )
        service = SimpleNamespace(agent=agent, config=SimpleNamespace(server_name="test"))

        status, payload = _invoke_get(
            service,
            "/api/observability/traces/trace%3Amissing",
        )

        self.assertEqual(int(status), 404)
        self.assertEqual(payload["schemaVersion"], "rag-ime.observability-trace-error.v1")
        self.assertEqual(payload["errorCode"], "trace_not_found")
        validate_contract(payload, "observability-trace-error.v1.json")

    def test_request_handler_never_reflects_contract_or_internal_error_text(self) -> None:
        sentinel = "PRIVATE_TRACE_CONTENT /Users/private/project/secret.txt"
        agent = SimpleNamespace(
            observation_trace=lambda payload: (_ for _ in ()).throw(TraceContractError(sentinel))
        )
        service = SimpleNamespace(agent=agent, config=SimpleNamespace(server_name="test"))

        status, payload = _invoke_get(
            service,
            "/api/observability/traces/trace%3Ainvalid",
        )

        self.assertEqual(int(status), 500)
        self.assertEqual(payload["errorCode"], "trace_invalid")
        self.assertEqual(payload["error"], "Trace is invalid")
        self.assertNotIn("PRIVATE_TRACE_CONTENT", str(payload))
        self.assertNotIn("/Users/private", str(payload))
        validate_contract(payload, "observability-trace-error.v1.json")

    def test_request_handler_maps_invalid_id_to_stable_public_copy(self) -> None:
        agent = SimpleNamespace(
            observation_trace=lambda payload: (_ for _ in ()).throw(ValueError("invalid_trace_id"))
        )
        service = SimpleNamespace(agent=agent, config=SimpleNamespace(server_name="test"))

        status, payload = _invoke_get(
            service,
            "/api/observability/traces/not-a-trace",
        )

        self.assertEqual(int(status), 400)
        self.assertEqual(payload["errorCode"], "invalid_trace_id")
        self.assertEqual(payload["error"], "Invalid Trace ID")
        validate_contract(payload, "observability-trace-error.v1.json")


if __name__ == "__main__":
    unittest.main()
