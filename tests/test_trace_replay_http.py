from __future__ import annotations

import unittest
from http import HTTPStatus
from types import SimpleNamespace
from urllib.parse import quote

from rag_ime.agent_routes import observability_trace_replay_route
from rag_ime.agent_service import AgentService
from rag_ime.control_api import ControlPathId, default_route_policy
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.trace_replay_verification import TraceVerificationValidationError


class TraceReplayRouteTests(unittest.TestCase):
    def test_routes_are_loopback_only_and_strict(self) -> None:
        replay_case_id = "replay-case:case-one"
        verification_id = "trace-verification:case-one"
        self.assertEqual(
            observability_trace_replay_route(
                "/api/observability/trace-replay/cases"
            ),
            ("", "case-create"),
        )
        self.assertEqual(
            observability_trace_replay_route(
                "/api/observability/trace-replay/cases/"
                + quote(replay_case_id, safe="")
            ),
            (replay_case_id, "case-get"),
        )
        self.assertEqual(
            observability_trace_replay_route(
                "/api/observability/trace-replay/verify"
            ),
            ("", "verify"),
        )
        self.assertEqual(
            observability_trace_replay_route(
                "/api/observability/trace-replay/verifications/"
                + quote(verification_id, safe="")
            ),
            (verification_id, "verification-get"),
        )
        for path in (
            "/api/observability/trace-replay",
            "/api/observability/trace-replay/cases/",
            "/api/observability/trace-replay/cases/a/b",
            "/api/observability/trace-replay//verify",
            "/control/v1/observability/trace-replay/cases",
        ):
            with self.subTest(path=path):
                self.assertEqual(observability_trace_replay_route(path), ("", ""))

    def test_route_policy_has_no_gateway_alias_and_exact_payloads(self) -> None:
        policy = default_route_policy()
        expected = {
            ControlPathId.OBSERVABILITY_TRACE_REPLAY_CASE_CREATE: (
                "/api/observability/trace-replay/cases",
                {
                    "schemaVersion",
                    "sourceScope",
                    "failureRef",
                    "sourceTraceId",
                    "baselineEvalRunId",
                    "baselineSandboxRunId",
                    "successMetric",
                    "successThreshold",
                    "rollbackTarget",
                },
                set(),
            ),
            ControlPathId.OBSERVABILITY_TRACE_REPLAY_CASE_GET: (
                "/api/observability/trace-replay/cases/{replayCaseId}",
                set(),
                {"replayCaseId"},
            ),
            ControlPathId.OBSERVABILITY_TRACE_REPLAY_VERIFY: (
                "/api/observability/trace-replay/verify",
                {
                    "schemaVersion",
                    "replayCaseId",
                    "repairReceiptId",
                    "repairEvalRunId",
                    "repairSandboxRunId",
                    "regressionEvalRunIds",
                },
                set(),
            ),
            ControlPathId.OBSERVABILITY_TRACE_VERIFICATION_GET: (
                "/api/observability/trace-replay/verifications/"
                "{verificationReceiptId}",
                set(),
                {"verificationReceiptId"},
            ),
        }
        for path_id, (path, body, params) in expected.items():
            with self.subTest(path_id=path_id):
                route = policy.resolve(path_id)
                self.assertEqual(route.local_8766_path, path)
                self.assertIsNone(route.gateway_8768_path)
                self.assertFalse(route.remote_safe)
                self.assertEqual(route.body, frozenset(body))
                self.assertEqual(route.required_body, frozenset(body))
                self.assertEqual(route.params, frozenset(params))


class _ReplayStore:
    def __init__(self) -> None:
        self.replay_case = {
            "schemaVersion": "rag-ime.trace-replay-case.v1",
            "replayCaseId": "replay-case:case-one",
        }
        self.verification = {
            "schemaVersion": "rag-ime.trace-verification-receipt.v1",
            "verificationReceiptId": "trace-verification:case-one",
        }
        self.freeze_calls: list[dict[str, object]] = []
        self.verify_calls: list[dict[str, object]] = []

    def freeze_case(self, **kwargs: object) -> dict[str, object]:
        self.freeze_calls.append(dict(kwargs))
        return dict(self.replay_case)

    def get_case(self, replay_case_id: str) -> dict[str, object] | None:
        return (
            dict(self.replay_case)
            if replay_case_id == self.replay_case["replayCaseId"]
            else None
        )

    def verify_repair(self, **kwargs: object) -> dict[str, object]:
        self.verify_calls.append(dict(kwargs))
        return dict(self.verification)

    def get_verification(
        self, verification_receipt_id: str
    ) -> dict[str, object] | None:
        return (
            dict(self.verification)
            if verification_receipt_id
            == self.verification["verificationReceiptId"]
            else None
        )


class TraceReplayServiceTests(unittest.TestCase):
    def _service(self) -> tuple[AgentService, _ReplayStore]:
        store = _ReplayStore()
        service = AgentService.__new__(AgentService)
        service.trace_replay_verifications = store
        return service, store

    def test_service_accepts_only_frozen_create_and_verify_contracts(self) -> None:
        service, store = self._service()
        created = service.create_trace_replay_case(
            {
                "schemaVersion": "rag-ime.trace-replay-case-create.v1",
                "sourceScope": "trace-runtime",
                "failureRef": "failure:one",
                "sourceTraceId": "trace:before",
                "baselineEvalRunId": "eval:before",
                "baselineSandboxRunId": "sandbox:before",
                "successMetric": "accuracy",
                "successThreshold": 1.0,
                "rollbackTarget": "git:before",
            }
        )
        self.assertTrue(created["ok"])
        self.assertEqual(
            store.freeze_calls[0]["baseline_sandbox_run_id"], "sandbox:before"
        )

        verified = service.verify_trace_replay_case(
            {
                "schemaVersion": "rag-ime.trace-verification-request.v1",
                "replayCaseId": "replay-case:case-one",
                "repairReceiptId": "repair-receipt:one",
                "repairEvalRunId": "eval:after",
                "repairSandboxRunId": "sandbox:after",
                "regressionEvalRunIds": ["eval:regression"],
            }
        )
        self.assertTrue(verified["ok"])
        self.assertEqual(
            store.verify_calls[0]["regression_eval_run_ids"], ["eval:regression"]
        )

        with self.assertRaisesRegex(
            TraceVerificationValidationError, "unsupported fields"
        ):
            service.create_trace_replay_case(
                {
                    "schemaVersion": "rag-ime.trace-replay-case-create.v1",
                    "sourceScope": "trace-runtime",
                    "failureRef": "failure:one",
                    "sourceTraceId": "trace:before",
                    "baselineEvalRunId": "eval:before",
                    "baselineSandboxRunId": "sandbox:before",
                    "successMetric": "accuracy",
                    "successThreshold": 1.0,
                    "rollbackTarget": "git:before",
                    "clientDecision": "kept",
                }
            )


def _invoke_get(
    agent: object,
    path: str,
    *,
    remote: bool = False,
) -> tuple[HTTPStatus, dict[str, object]]:
    handler = DebugRequestHandler.__new__(DebugRequestHandler)
    handler.service = SimpleNamespace(agent=agent)  # type: ignore[assignment]
    handler.path = path
    if remote:
        handler.client_address = ("203.0.113.8", 48123)
    handler._authorize_gateway_request = lambda method, parsed: True  # type: ignore[method-assign]
    handler._serve_gateway_static = lambda request_path: False  # type: ignore[method-assign]
    responses: list[tuple[HTTPStatus, dict[str, object]]] = []
    handler._write_json = lambda status, payload, **kwargs: responses.append((status, payload))  # type: ignore[method-assign]
    handler.do_GET()
    if len(responses) != 1:
        raise AssertionError(f"expected one response, received {len(responses)}")
    return responses[0]


def _invoke_post(
    agent: object,
    path: str,
    body: dict[str, object],
    *,
    remote: bool = False,
) -> tuple[HTTPStatus, dict[str, object]]:
    handler = DebugRequestHandler.__new__(DebugRequestHandler)
    handler.service = SimpleNamespace(agent=agent)  # type: ignore[assignment]
    handler.path = path
    if remote:
        handler.client_address = ("203.0.113.8", 48123)
    handler._authorize_gateway_request = lambda method, parsed: True  # type: ignore[method-assign]
    handler._management_post_security_error = lambda request_path, **kwargs: None  # type: ignore[method-assign]
    handler._read_json = lambda: dict(body)  # type: ignore[method-assign]
    responses: list[tuple[HTTPStatus, dict[str, object]]] = []
    handler._write_json = lambda status, payload, **kwargs: responses.append((status, payload))  # type: ignore[method-assign]
    handler.do_POST()
    if len(responses) != 1:
        raise AssertionError(f"expected one response, received {len(responses)}")
    return responses[0]


class TraceReplayHttpDispatchTests(unittest.TestCase):
    def test_http_dispatches_local_records_and_rejects_remote_callers(self) -> None:
        calls: list[tuple[str, object]] = []
        agent = SimpleNamespace(
            create_trace_replay_case=lambda payload: calls.append(
                ("create", dict(payload))
            )
            or {"ok": True, "replayCase": {"replayCaseId": "replay-case:one"}},
            verify_trace_replay_case=lambda payload: calls.append(
                ("verify", dict(payload))
            )
            or {
                "ok": True,
                "verificationReceipt": {
                    "verificationReceiptId": "trace-verification:one"
                },
            },
            get_trace_replay_case=lambda replay_case_id: calls.append(
                ("get-case", replay_case_id)
            )
            or {"ok": True, "replayCase": {"replayCaseId": replay_case_id}},
            get_trace_verification_receipt=lambda receipt_id: calls.append(
                ("get-verification", receipt_id)
            )
            or {
                "ok": True,
                "verificationReceipt": {"verificationReceiptId": receipt_id},
            },
        )
        create_status, _ = _invoke_post(
            agent,
            "/api/observability/trace-replay/cases",
            {"schemaVersion": "rag-ime.trace-replay-case-create.v1"},
        )
        verify_status, _ = _invoke_post(
            agent,
            "/api/observability/trace-replay/verify",
            {"schemaVersion": "rag-ime.trace-verification-request.v1"},
        )
        case_status, _ = _invoke_get(
            agent,
            "/api/observability/trace-replay/cases/"
            + quote("replay-case:one", safe=""),
        )
        receipt_status, _ = _invoke_get(
            agent,
            "/api/observability/trace-replay/verifications/"
            + quote("trace-verification:one", safe=""),
        )
        self.assertEqual(
            [create_status, verify_status, case_status, receipt_status],
            [HTTPStatus.CREATED, HTTPStatus.CREATED, HTTPStatus.OK, HTTPStatus.OK],
        )
        self.assertEqual(
            [label for label, _value in calls],
            ["create", "verify", "get-case", "get-verification"],
        )

        before_remote = list(calls)
        remote_status, remote_payload = _invoke_post(
            agent,
            "/api/observability/trace-replay/cases",
            {"schemaVersion": "rag-ime.trace-replay-case-create.v1"},
            remote=True,
        )
        self.assertEqual(remote_status, HTTPStatus.FORBIDDEN)
        self.assertEqual(remote_payload["errorCode"], "trace_replay_loopback_only")
        self.assertEqual(calls, before_remote)


if __name__ == "__main__":
    unittest.main()
