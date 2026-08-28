from __future__ import annotations

import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from rag_ime.agent_service import AgentService
from rag_ime.control_api import ControlAccessContext, ControlPathId, ControlScope, default_route_policy
from rag_ime.debug_server import DebugRequestHandler
from rag_ime.sandbox_run_store import SandboxRunStore
from rag_ime.trace_runtime import build_sandbox_run


def _invoke_get(service: object, path: str) -> tuple[HTTPStatus, dict[str, object]]:
    handler = DebugRequestHandler.__new__(DebugRequestHandler)
    handler.service = service  # type: ignore[assignment]
    handler.path = path
    handler._authorize_gateway_request = lambda method, parsed: True  # type: ignore[method-assign]
    handler._serve_gateway_static = lambda request_path: False  # type: ignore[method-assign]
    responses: list[tuple[HTTPStatus, dict[str, object]]] = []
    handler._write_json = lambda status, payload, **kwargs: responses.append((status, payload))  # type: ignore[method-assign]
    handler.do_GET()
    if len(responses) != 1:
        raise AssertionError(f"expected one response, received {len(responses)}")
    return responses[0]


class ObservabilitySandboxApiTests(unittest.TestCase):
    def test_policy_exposes_only_read_routes(self) -> None:
        policy = default_route_policy()
        listing = policy.resolve(ControlPathId.OBSERVABILITY_SANDBOX_RUNS_LIST)
        detail = policy.resolve(ControlPathId.OBSERVABILITY_SANDBOX_RUN_GET)
        self.assertEqual(listing.local_8766_path, "/api/observability/sandbox-runs")
        self.assertEqual(detail.params, frozenset({"sandboxRunId"}))
        self.assertTrue(listing.remote_safe)
        self.assertTrue(detail.remote_safe)
        self.assertEqual(listing.remote_scopes, frozenset({ControlScope.AGENT_READ.value}))
        policy.authorize_http(
            method="GET",
            path="/api/observability/sandbox-runs/sandbox%3Aone",
            query={},
            body={},
            context=ControlAccessContext.remote(
                device_id="device-1", scopes={ControlScope.AGENT_READ.value}
            ),
        )

    def test_list_and_get_return_the_host_store_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sandbox-api-") as temporary:
            store = SandboxRunStore(Path(temporary) / "observability.sqlite")
            payload = build_sandbox_run(
                sandbox_run_id="sandbox:one",
                app_id="sgg",
                workspace_root="/workspace/demo",
                workspace_binding_id="workspace-binding:demo",
                trace_ids=["trace:one"],
                eval_run_ids=["eval:one"],
                now_ms=10,
            ).to_dict()
            store.persist(payload)
            agent = AgentService.__new__(AgentService)
            agent.sandbox_runs = store
            service = SimpleNamespace(agent=agent, config=SimpleNamespace(server_name="test"))

            status, listing = _invoke_get(
                service,
                "/api/observability/sandbox-runs?limit=20",
            )
            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(listing["schemaVersion"], "rag-ime.observability-sandbox-run-list.v1")
            self.assertEqual(listing["ok"], True)
            self.assertEqual(listing["total"], 1)
            self.assertEqual(listing["items"], [payload])

            status, detail = _invoke_get(
                service,
                f"/api/observability/sandbox-runs/{quote('sandbox:one', safe='')}",
            )
            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(detail, payload)

            status, error = _invoke_get(
                service,
                "/api/observability/sandbox-runs/sandbox%3Amissing",
            )
            self.assertEqual(status, HTTPStatus.NOT_FOUND)
            self.assertEqual(error["errorCode"], "sandbox_run_not_found")


if __name__ == "__main__":
    unittest.main()
