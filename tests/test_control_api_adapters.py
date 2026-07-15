from __future__ import annotations

import unittest

from rag_ime.control_api import (
    ControlAccessContext,
    ControlApiError,
    ControlPathId,
    ControlRequest,
    Gateway8768Adapter,
    Local8766Adapter,
    default_route_policy,
)


class ControlTargetAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_route_policy()

    def test_local_adapter_maps_path_id_to_existing_8766_endpoint(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_PROMPT.value,
            params={"sessionId": "session:abc"},
            body={"message": "hello"},
        )
        route = self.policy.authorize(request, ControlAccessContext.native())

        prepared = Local8766Adapter().prepare(route, request, ControlAccessContext.native())

        self.assertEqual(prepared.adapter_id, "local-8766")
        self.assertEqual(prepared.method.value, "POST")
        self.assertEqual(prepared.path, "/api/agent/sessions/session%3Aabc/prompt")
        self.assertEqual(prepared.url, "http://127.0.0.1:8766/api/agent/sessions/session%3Aabc/prompt")
        self.assertEqual(prepared.body, {"message": "hello"})

    def test_gateway_adapter_preserves_semantics_with_canonical_8768_target(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_PROMPT.value,
            params={"sessionId": "session-1"},
            body={"message": "hello"},
        )
        context = ControlAccessContext.remote(device_id="phone-1", scopes={"agent.write"})
        route = self.policy.authorize(request, context)

        prepared = Gateway8768Adapter().prepare(route, request, context)

        self.assertEqual(prepared.adapter_id, "gateway-8768")
        self.assertEqual(prepared.method.value, "POST")
        self.assertEqual(prepared.path, "/control/v1/agent/sessions/session-1/prompt")
        self.assertEqual(
            prepared.url,
            "http://127.0.0.1:8768/control/v1/agent/sessions/session-1/prompt",
        )
        self.assertEqual(prepared.body, {"message": "hello"})

    def test_remote_client_cannot_be_sent_to_local_8766(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.SYSTEM_HEALTH.value,
        )
        context = ControlAccessContext.remote(device_id="phone-1", scopes={"control.read"})
        route = self.policy.authorize(request, context)

        with self.assertRaises(ControlApiError):
            Local8766Adapter().prepare(route, request, context)

    def test_subscription_moves_last_event_id_to_header_not_arbitrary_query(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_EVENTS.value,
            params={"sessionId": "session-1"},
            query={"lastEventId": "session-1:42"},
        )
        route = self.policy.authorize(request, ControlAccessContext.native())

        prepared = Local8766Adapter().prepare(route, request, ControlAccessContext.native())

        self.assertTrue(prepared.subscription)
        self.assertEqual(prepared.headers["Accept"], "text/event-stream")
        self.assertEqual(prepared.headers["Last-Event-ID"], "session-1:42")
        self.assertEqual(prepared.query, {})
        self.assertNotIn("?", prepared.url)

    def test_query_encoding_is_deterministic_and_scalar_only(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSIONS_LIST.value,
            query={"limit": 25, "includeArchived": True},
        )
        route = self.policy.authorize(request, ControlAccessContext.native())

        prepared = Local8766Adapter().prepare(route, request, ControlAccessContext.native())

        self.assertEqual(
            prepared.url,
            "http://127.0.0.1:8766/api/agent/sessions?includeArchived=true&limit=25",
        )

    def test_local_adapter_rejects_non_loopback_or_wrong_port(self) -> None:
        for url in (
            "http://example.com:8766",
            "http://127.0.0.1:9999",
            "http://user:pass@127.0.0.1:8766",
            "http://127.0.0.1:8766/api",
            "http://127.0.0.1:8766?target=evil",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Local8766Adapter(url)

    def test_non_loopback_gateway_requires_https_and_has_no_request_host_override(self) -> None:
        with self.assertRaises(ValueError):
            Gateway8768Adapter("http://gateway.example.test")

        adapter = Gateway8768Adapter("https://gateway.example.test")
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.SYSTEM_HEALTH.value,
        )
        context = ControlAccessContext.remote(device_id="phone-1", scopes={"control.read"})
        route = self.policy.authorize(request, context)
        prepared = adapter.prepare(route, request, context)
        self.assertEqual(prepared.url, "https://gateway.example.test/control/v1/health")

    def test_prepared_request_owns_a_copy_of_nested_body(self) -> None:
        body = {"message": "hello", "attachments": ["media-1"]}
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_PROMPT.value,
            params={"sessionId": "session-1"},
            body=body,
        )
        route = self.policy.authorize(request, ControlAccessContext.native())
        prepared = Local8766Adapter().prepare(route, request, ControlAccessContext.native())

        body["attachments"].append("media-2")

        self.assertEqual(prepared.body["attachments"], ["media-1"])


if __name__ == "__main__":
    unittest.main()
