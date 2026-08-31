from __future__ import annotations

import unittest
from http import HTTPStatus
from types import SimpleNamespace

from rag_ime.control_api import (
    ControlAccessContext,
    ControlApiError,
    ControlPathId,
    ControlRequest,
    default_route_policy,
)
from rag_ime.control_api.route_table import find_route
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.extension_sandbox_experiment import ExtensionSandboxExperimentService


APP_ID = "extension:demo"
APP_BINDING = "a" * 64


class _Sessions:
    def __init__(self, session: dict[str, object] | None = None) -> None:
        self.session = session or {
            "id": "agent:app-session",
            "surfaceKind": "extension_app",
            "ownerAppId": APP_ID,
            "surfaceKey": "experiment",
        }

    def get(self, session_id: str) -> dict[str, object]:
        if session_id != self.session["id"]:
            raise KeyError(session_id)
        return dict(self.session)


class _Extensions:
    def __init__(self, *, include_connector: bool = True) -> None:
        self.include_connector = include_connector

    def list(self) -> dict[str, object]:
        items: list[dict[str, object]] = [
            {
                "id": "@paw/demo",
                "version": "1.2.3",
                "installed": True,
                "enabled": True,
                "extensionApp": {
                    "id": APP_ID,
                    "packageId": "@paw/demo",
                    "version": "1.2.3",
                    "bindingSha256": APP_BINDING,
                    "verticalSuiteId": "sgg",
                    "verticalSuiteRevision": "fixture-v2",
                },
            }
        ]
        if self.include_connector:
            items.append(
                {
                    "id": "vertical-agent-sandbox",
                    "version": "0.1.1",
                    "installed": True,
                    "enabled": True,
                }
            )
        return {
            "schemaVersion": "rag-ime.plugin-inventory.v1",
            "ok": True,
            "runtimeAvailable": True,
            "items": items,
        }


class _Connector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def execute(
        self,
        session_id: str,
        operation: str,
        args: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((session_id, operation, dict(args)))
        return {
            "sandboxRunId": "sandbox:sgg:one",
            "traceId": "trace:sgg:one",
            "evalRunId": "eval:sgg:one",
        }


def _payload(decision: str = "run") -> dict[str, object]:
    return {
        "sessionId": "agent:app-session",
        "ownerAppId": APP_ID,
        "experimentId": "experiment:one",
        "candidateBindingSha256": APP_BINDING,
        "requestedDecision": decision,
    }


class ExtensionSandboxExperimentTests(unittest.TestCase):
    def test_route_is_local_only_and_rejects_unknown_fields(self) -> None:
        policy = default_route_policy()
        route = policy.resolve(ControlPathId.EXTENSION_SANDBOX_EXPERIMENT_RUN)
        self.assertEqual(route.path_id.value, "extension.sandbox.experiment.run")
        self.assertEqual(route.local_8766_path, "/api/extensions/sandbox/experiments")
        self.assertFalse(route.remote_safe)
        self.assertEqual(
            route.body,
            frozenset(
                {
                    "sessionId",
                    "ownerAppId",
                    "experimentId",
                    "candidateBindingSha256",
                    "requestedDecision",
                }
            ),
        )
        policy.authorize(
            ControlRequest(
                request_id="local",
                path_id=route.path_id.value,
                body=_payload(),
            ),
            ControlAccessContext.loopback_web(),
        )
        with self.assertRaises(ControlApiError):
            policy.authorize(
                ControlRequest(
                    request_id="unknown",
                    path_id=route.path_id.value,
                    body={**_payload(), "command": "python evil.py"},
                ),
                ControlAccessContext.loopback_web(),
            )
        with self.assertRaises(ControlApiError):
            policy.authorize(
                ControlRequest(
                    request_id="remote",
                    path_id=route.path_id.value,
                    body=_payload(),
                ),
                ControlAccessContext.remote(
                    device_id="device-1",
                    scopes={"agent.write"},
                ),
            )

        descriptor = find_route("POST", "/api/extensions/sandbox/experiments")
        self.assertIsNotNone(descriptor)
        assert descriptor is not None
        self.assertEqual(descriptor.handler, "extension_sandbox_experiments.execute")

    def test_owner_mismatch_is_rejected_before_connector_execution(self) -> None:
        connector = _Connector()
        service = ExtensionSandboxExperimentService(
            sessions=_Sessions(
                {
                    "id": "agent:app-session",
                    "surfaceKind": "extension_app",
                    "ownerAppId": "extension:other",
                    "surfaceKey": "experiment",
                }
            ),
            extensions=_Extensions(),
            connector=connector,
        )

        with self.assertRaisesRegex(ValueError, "owner"):
            service.execute(_payload())
        self.assertEqual(connector.calls, [])

    def test_direct_local_service_rejects_execution_controls_outside_the_five_field_contract(self) -> None:
        service = ExtensionSandboxExperimentService(
            sessions=_Sessions(),
            extensions=_Extensions(),
            connector=_Connector(),
        )

        with self.assertRaisesRegex(ValueError, "unknown:network"):
            service.execute({**_payload(), "network": "allowed"})

    def test_candidate_binding_must_match_installed_extension_evidence(self) -> None:
        connector = _Connector()
        service = ExtensionSandboxExperimentService(
            sessions=_Sessions(),
            extensions=_Extensions(),
            connector=connector,
        )

        with self.assertRaisesRegex(ValueError, "binding"):
            service.execute(
                {**_payload(), "candidateBindingSha256": "b" * 64}
            )
        self.assertEqual(connector.calls, [])

    def test_skip_returns_a_receipt_without_requiring_or_calling_connector(self) -> None:
        connector = _Connector()
        service = ExtensionSandboxExperimentService(
            sessions=_Sessions(),
            extensions=_Extensions(include_connector=False),
            connector=connector,
        )

        receipt = service.execute(_payload("skip"))

        self.assertEqual(
            receipt,
            {
                "schemaVersion": "rag-ime.extension-sandbox-experiment-receipt.v1",
                "ok": True,
                "sessionId": "agent:app-session",
                "ownerAppId": APP_ID,
                "experimentId": "experiment:one",
                "candidateBindingSha256": APP_BINDING,
                "requestedDecision": "skip",
                "executionStatus": "skipped",
                "executed": False,
                "appPackageId": "@paw/demo",
                "appVersion": "1.2.3",
                "suiteId": "sgg",
                "suiteRevision": "fixture-v2",
                "connectorPackageId": "vertical-agent-sandbox",
                "connectorVersion": "",
                "policyId": "vertical-readonly-v1",
            },
        )
        self.assertEqual(connector.calls, [])

    def test_run_requires_enabled_connector_and_derives_suite_from_app_evidence(self) -> None:
        missing = ExtensionSandboxExperimentService(
            sessions=_Sessions(),
            extensions=_Extensions(include_connector=False),
            connector=_Connector(),
        )
        with self.assertRaisesRegex(ValueError, "Connector"):
            missing.execute(_payload())

        connector = _Connector()
        service = ExtensionSandboxExperimentService(
            sessions=_Sessions(),
            extensions=_Extensions(),
            connector=connector,
        )
        receipt = service.execute(_payload())

        self.assertEqual(
            connector.calls,
            [
                (
                    "agent:app-session",
                    "run",
                    {"suiteId": "sgg", "suiteRevision": "fixture-v2"},
                )
            ],
        )
        self.assertEqual(receipt["executionStatus"], "completed")
        self.assertTrue(receipt["executed"])
        self.assertEqual(receipt["connectorVersion"], "0.1.1")
        self.assertEqual(receipt["sandboxRunId"], "sandbox:sgg:one")
        self.assertEqual(receipt["traceId"], "trace:sgg:one")
        self.assertEqual(receipt["evalRunId"], "eval:sgg:one")

    def test_descriptor_dispatches_the_structured_local_request(self) -> None:
        calls: list[dict[str, object]] = []
        receipt = {
            "schemaVersion": "rag-ime.extension-sandbox-experiment-receipt.v1",
            "ok": True,
        }
        service = SimpleNamespace(
            extension_sandbox_experiments=SimpleNamespace(
                execute=lambda payload: calls.append(dict(payload)) or receipt
            ),
            config=SimpleNamespace(server_name="test"),
        )
        handler = DebugRequestHandler.__new__(DebugRequestHandler)
        handler.service = service  # type: ignore[assignment]
        handler.path = "/api/extensions/sandbox/experiments"
        handler.headers = {}  # type: ignore[assignment]
        handler._authorize_gateway_request = lambda method, parsed: True  # type: ignore[method-assign]
        handler._management_post_security_error = lambda path, require_json=True: None  # type: ignore[method-assign]
        handler._read_json = lambda: _payload("skip")  # type: ignore[method-assign]
        responses: list[tuple[HTTPStatus, dict[str, object]]] = []
        handler._write_json = lambda status, body, **kwargs: responses.append((status, body))  # type: ignore[method-assign]

        handler.do_POST()

        self.assertEqual(calls, [_payload("skip")])
        self.assertEqual(responses, [(HTTPStatus.OK, receipt)])


if __name__ == "__main__":
    unittest.main()
