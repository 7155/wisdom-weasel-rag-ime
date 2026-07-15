from __future__ import annotations

import unittest

from rag_ime.control_api import (
    ControlAccessContext,
    ControlApiError,
    ControlApiFacade,
    ControlErrorCode,
    ControlPathId,
    Gateway8768Adapter,
    NativeCapabilityState,
)


class ControlApiFacadeTests(unittest.TestCase):
    def test_native_bootstrap_reports_unmounted_facade_and_narrow_bridge_contract(self) -> None:
        facade = ControlApiFacade(
            native_capabilities=NativeCapabilityState(
                file_picker=True,
                managed_agent_image_import=True,
                reveal_path=True,
                keychain_status=True,
                tcc_status=True,
                approved_external_actions=True,
            )
        )

        response = facade.handle(
            {"id": "request-1", "pathId": "control.bootstrap"},
            context=ControlAccessContext.native(),
        )

        self.assertEqual(set(response), {"id", "ok", "result"})
        self.assertEqual(response["id"], "request-1")
        self.assertTrue(response["ok"])
        bootstrap = response["result"]
        self.assertEqual(bootstrap["schemaVersion"], "rag-ime.control-bootstrap.v1")
        self.assertEqual(
            bootstrap["capabilities"]["transport"]["nativeBridgeHandler"],
            "ragImeNativeBridge",
        )
        self.assertEqual(
            bootstrap["capabilities"]["requestContract"]["fields"],
            ["id", "pathId", "params", "query", "body"],
        )
        self.assertFalse(bootstrap["integration"]["httpMounted"])
        self.assertTrue(bootstrap["integration"]["facadeOnly"])
        self.assertFalse(bootstrap["integration"]["adapterWired"])
        self.assertEqual(
            bootstrap["recovery"]["globalSnapshotPathId"],
            "agent.configuration.get",
        )
        self.assertTrue(bootstrap["capabilities"]["native"]["filePicker"])
        self.assertTrue(bootstrap["capabilities"]["native"]["managedAgentImageImport"])
        self.assertFalse(bootstrap["capabilities"]["native"]["keychainValues"])
        self.assertTrue(
            bootstrap["capabilities"]["features"]["inputLexiconWorkContract"]
        )
        self.assertTrue(bootstrap["capabilities"]["features"]["agentPersonaCreate"])
        self.assertTrue(bootstrap["capabilities"]["features"]["memoryEdit"])

    def test_remote_capabilities_force_native_and_privileged_features_off(self) -> None:
        facade = ControlApiFacade(
            adapter=Gateway8768Adapter(),
            native_capabilities=NativeCapabilityState(
                file_picker=True,
                managed_agent_image_import=True,
                reveal_path=True,
                keychain_status=True,
                tcc_status=True,
                approved_external_actions=True,
            ),
        )
        context = ControlAccessContext.remote(device_id="phone-1", scopes={"agent.read"})

        capabilities = facade.capabilities(context=context)

        self.assertEqual(
            capabilities["native"],
            {
                "filePicker": False,
                "managedAgentImageImport": False,
                "revealPath": False,
                "keychainStatus": False,
                "tccStatus": False,
                "approvedExternalActions": False,
                "keychainValues": False,
            },
        )
        self.assertFalse(capabilities["security"]["debugApi"])
        self.assertFalse(capabilities["security"]["corsWildcard"])
        self.assertFalse(capabilities["security"]["cookieCredentials"])
        self.assertTrue(capabilities["security"]["csrfRequiredForCookieAuth"])
        self.assertFalse(capabilities["security"]["arbitraryShell"])
        self.assertFalse(capabilities["security"]["arbitraryFileRead"])
        self.assertFalse(capabilities["security"]["databaseApply"])
        self.assertFalse(capabilities["features"]["inputLexiconWorkContract"])
        self.assertFalse(capabilities["features"]["agentPersonaCreate"])
        self.assertFalse(capabilities["features"]["memoryEdit"])

    def test_anonymous_remote_bootstrap_is_available_but_every_data_route_is_hidden(self) -> None:
        facade = ControlApiFacade(adapter=Gateway8768Adapter())
        context = ControlAccessContext.remote()

        response = facade.handle(
            {"id": "request-1", "pathId": "control.bootstrap"},
            context=context,
        )

        self.assertTrue(response["ok"])
        route_ids = {
            route["pathId"]
            for route in response["result"]["capabilities"]["routes"]
        }
        self.assertEqual(route_ids, {"control.bootstrap", "control.capabilities"})

    def test_facade_dispatches_allowlisted_request_and_wraps_result(self) -> None:
        prepared_requests = []

        def execute(request):
            prepared_requests.append(request)
            return {"schemaVersion": "rag-ime.agent-session-list.v1", "items": []}

        facade = ControlApiFacade(executor=execute)
        response = facade.handle(
            {
                "id": "request-1",
                "pathId": "agent.sessions.list",
                "query": {"limit": 20},
            },
            context=ControlAccessContext.native(),
        )

        self.assertEqual(
            response,
            {
                "id": "request-1",
                "ok": True,
                "result": {"schemaVersion": "rag-ime.agent-session-list.v1", "items": []},
            },
        )
        self.assertEqual(len(prepared_requests), 1)
        self.assertEqual(prepared_requests[0].path_id, "agent.sessions.list")
        self.assertEqual(prepared_requests[0].url, "http://127.0.0.1:8766/api/agent/sessions?limit=20")

    def test_unwired_facade_returns_stable_retryable_error_envelope(self) -> None:
        facade = ControlApiFacade()

        response = facade.handle(
            {"id": "request-1", "pathId": "system.health"},
            context=ControlAccessContext.native(),
        )

        self.assertEqual(set(response), {"id", "ok", "error"})
        self.assertEqual(response["id"], "request-1")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "adapter_unavailable")
        self.assertTrue(response["error"]["retryable"])

    def test_invalid_request_preserves_safe_correlation_id(self) -> None:
        facade = ControlApiFacade()

        response = facade.handle(
            {
                "id": "request-1",
                "pathId": "system.health",
                "url": "http://127.0.0.1:9999/private",
            },
            context=ControlAccessContext.native(),
        )

        self.assertEqual(response["id"], "request-1")
        self.assertEqual(response["error"]["code"], "invalid_request")

        non_object = facade.handle(["not", "an", "object"], context=ControlAccessContext.native())
        self.assertEqual(non_object["id"], "")
        self.assertEqual(non_object["error"]["code"], "invalid_request")

    def test_remote_route_denial_is_a_stable_error_not_an_exception(self) -> None:
        facade = ControlApiFacade(adapter=Gateway8768Adapter(), executor=lambda request: {})

        response = facade.handle(
            {
                "id": "request-1",
                "pathId": "agent.session.delete",
                "params": {"sessionId": "session-1"},
            },
            context=ControlAccessContext.remote(device_id="phone-1", scopes={"agent.write"}),
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "route_not_allowed")

    def test_upstream_exception_is_sanitized(self) -> None:
        def execute(_request):
            raise RuntimeError("private database path /Users/undo/private.sqlite")

        facade = ControlApiFacade(executor=execute)
        response = facade.handle(
            {"id": "request-1", "pathId": "system.health"},
            context=ControlAccessContext.native(),
        )

        self.assertEqual(response["error"]["code"], "upstream_error")
        self.assertNotIn("private.sqlite", str(response))

    def test_subscription_is_not_dispatched_as_a_json_request(self) -> None:
        facade = ControlApiFacade(executor=lambda request: self.fail("executor must not run"))
        payload = {
            "id": "subscription-1",
            "pathId": "agent.session.events",
            "params": {"sessionId": "session-1"},
            "query": {"lastEventId": "session-1:10"},
        }

        response = facade.handle(payload, context=ControlAccessContext.native())
        prepared = facade.prepare_subscription(payload, context=ControlAccessContext.native())

        self.assertEqual(response["error"]["code"], "subscription_required")
        self.assertTrue(prepared.subscription)
        self.assertEqual(prepared.headers["Last-Event-ID"], "session-1:10")

    def test_prepare_subscription_rejects_non_subscription_path(self) -> None:
        facade = ControlApiFacade()

        with self.assertRaises(ControlApiError) as raised:
            facade.prepare_subscription(
                {"id": "request-1", "pathId": ControlPathId.SYSTEM_HEALTH.value},
                context=ControlAccessContext.native(),
            )

        self.assertEqual(raised.exception.code, ControlErrorCode.INVALID_REQUEST)

    def test_internal_route_manifest_is_available_for_integration_but_not_bootstrap(self) -> None:
        facade = ControlApiFacade()

        internal = facade.route_manifest()
        public = facade.capabilities(context=ControlAccessContext.native())["routes"]

        self.assertTrue(all("target" in item for item in internal))
        self.assertTrue(all("target" not in item for item in public))
        control_events = next(
            item for item in internal if item["pathId"] == ControlPathId.CONTROL_EVENTS.value
        )
        self.assertEqual(control_events["target"]["8766"], "/api/agent/events")
        self.assertEqual(control_events["target"]["8768"], "/control/v1/events")


if __name__ == "__main__":
    unittest.main()
