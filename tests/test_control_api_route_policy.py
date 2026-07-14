from __future__ import annotations

import unittest

from rag_ime.control_api import (
    ControlAccessContext,
    ControlApiError,
    ControlErrorCode,
    ControlPathId,
    ControlRequest,
    ControlScope,
    default_route_policy,
)


class ControlRoutePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_route_policy()

    def test_manifest_covers_every_canonical_path_id_once(self) -> None:
        manifest = self.policy.manifest(include_targets=True)

        self.assertEqual(len(manifest), len(ControlPathId))
        self.assertEqual(
            {item["pathId"] for item in manifest},
            {path_id.value for path_id in ControlPathId},
        )
        self.assertEqual(
            {
                "planning.dashboard",
                "planning.mutation.preview",
                "planning.task.save",
                "planning.task.action",
                "planning.taskEvent.undo",
                "planning.mutation.rollback",
                "memory.summary",
                "memory.pages",
                "memory.graph.get",
                "memory.entity.get",
                "history.page",
                "knowledge.start",
                "knowledge.cancel",
                "knowledge.status",
                "knowledge.routeStatus",
                "knowledge.database.apply.preview",
                "knowledge.database.apply",
                "knowledge.database.rollback",
                "diagnostics.runtime",
                "diagnostics.predictor",
                "diagnostics.models",
                "configuration.settings",
                "configuration.schema",
            },
            {
                path_id.value
                for path_id in ControlPathId
                if path_id.name.startswith(
                    (
                        "PLANNING_",
                        "MEMORY_",
                        "HISTORY_",
                        "KNOWLEDGE_",
                        "DIAGNOSTICS_",
                        "CONFIGURATION_",
                    )
                )
            },
        )

    def test_manifest_marks_method_targets_remote_safety_and_subscription(self) -> None:
        entries = {item["pathId"]: item for item in self.policy.manifest(include_targets=True)}

        prompt = entries[ControlPathId.AGENT_SESSION_PROMPT.value]
        self.assertEqual(prompt["method"], "POST")
        self.assertEqual(prompt["target"]["8766"], "/api/agent/sessions/{sessionId}/prompt")
        self.assertEqual(
            prompt["target"]["8768"],
            "/control/v1/agent/sessions/{sessionId}/prompt",
        )
        self.assertTrue(prompt["remoteSafe"])
        self.assertFalse(prompt["subscription"])

        events = entries[ControlPathId.AGENT_SESSION_EVENTS.value]
        self.assertTrue(events["subscription"])
        self.assertIn("lastEventId", events["query"])

        control_events = entries[ControlPathId.CONTROL_EVENTS.value]
        self.assertEqual(control_events["target"]["8766"], "/api/agent/events")

        templates = entries[ControlPathId.AGENT_SUBAGENTS_TEMPLATES.value]
        self.assertEqual(
            templates["target"]["8766"],
            "/api/agent/subagents/templates",
        )

        room_snapshot = entries[ControlPathId.AGENT_ROOM_SNAPSHOT.value]
        self.assertEqual(room_snapshot["method"], "GET")
        self.assertEqual(
            room_snapshot["target"]["8766"],
            "/api/agent/rooms/{roomId}/snapshot",
        )
        self.assertTrue(room_snapshot["remoteSafe"])
        self.assertFalse(room_snapshot["subscription"])

        tools = entries[ControlPathId.AGENT_TOOLS_LIST.value]
        self.assertFalse(tools["remoteSafe"])

    def test_unknown_path_id_fails_closed(self) -> None:
        with self.assertRaises(ControlApiError) as raised:
            self.policy.resolve("debug.anything")

        self.assertEqual(raised.exception.code, ControlErrorCode.ROUTE_NOT_FOUND)

    def test_request_payload_rejects_url_host_and_headers(self) -> None:
        for forbidden in ("url", "host", "headers"):
            with self.subTest(forbidden=forbidden), self.assertRaises(ControlApiError) as raised:
                ControlRequest.from_payload(
                    {
                        "id": "request-1",
                        "pathId": "system.health",
                        forbidden: "http://attacker.invalid",
                    }
                )
            self.assertEqual(raised.exception.code, ControlErrorCode.INVALID_REQUEST)

    def test_request_body_must_be_json_shaped_and_size_bounded(self) -> None:
        with self.assertRaises(ControlApiError) as raised:
            ControlRequest(
                request_id="request-1",
                path_id=ControlPathId.AGENT_SESSION_PROMPT.value,
                params={"sessionId": "session-1"},
                body={"message": object()},
            )
        self.assertEqual(raised.exception.code, ControlErrorCode.INVALID_REQUEST)

        with self.assertRaises(ControlApiError):
            ControlRequest(
                request_id="request-2",
                path_id=ControlPathId.AGENT_SESSION_PROMPT.value,
                params={"sessionId": "session-1"},
                body={"message": "x" * 2_000_001},
            )

    def test_path_parameters_reject_traversal_and_encoded_escape(self) -> None:
        for value in ("../../etc/passwd", "abc/def", "abc%2Fdef", "..", ""):
            request = ControlRequest(
                request_id="request-1",
                path_id=ControlPathId.AGENT_SESSION_SNAPSHOT.value,
                params={"sessionId": value},
            )
            with self.subTest(value=value), self.assertRaises(ControlApiError):
                self.policy.authorize(request, ControlAccessContext.native())

    def test_memory_page_kind_is_an_enum_not_an_arbitrary_path(self) -> None:
        allowed = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.MEMORY_PAGES.value,
            params={"kind": "books"},
        )
        self.policy.authorize(allowed, ControlAccessContext.native())

        rejected = ControlRequest(
            request_id="request-2",
            path_id=ControlPathId.MEMORY_PAGES.value,
            params={"kind": "private-table"},
        )
        with self.assertRaises(ControlApiError):
            self.policy.authorize(rejected, ControlAccessContext.native())

    def test_subscriptions_require_explicit_last_event_id_even_when_empty(self) -> None:
        missing = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_EVENTS.value,
            params={"sessionId": "session-1"},
        )
        with self.assertRaises(ControlApiError) as raised:
            self.policy.authorize(missing, ControlAccessContext.native())
        self.assertEqual(raised.exception.code, ControlErrorCode.INVALID_REQUEST)

        fresh = ControlRequest(
            request_id="request-2",
            path_id=ControlPathId.AGENT_SESSION_EVENTS.value,
            params={"sessionId": "session-1"},
            query={"lastEventId": ""},
        )
        self.policy.authorize(fresh, ControlAccessContext.native())

    def test_remote_clients_need_a_paired_device_and_each_required_scope(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSIONS_LIST.value,
        )
        contexts = (
            ControlAccessContext.remote(),
            ControlAccessContext.remote(device_id="phone-1"),
            ControlAccessContext.remote(device_id="phone-1", scopes={ControlScope.CONTROL_READ.value}),
        )
        for context in contexts:
            with self.subTest(context=context), self.assertRaises(ControlApiError) as raised:
                self.policy.authorize(request, context)
            self.assertEqual(raised.exception.code, ControlErrorCode.SCOPE_REQUIRED)

        authorized = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_READ.value},
        )
        self.policy.authorize(request, authorized)

    def test_remote_clients_cannot_enable_local_only_routes_with_a_wildcard_scope(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_DELETE.value,
            params={"sessionId": "session-1"},
        )
        context = ControlAccessContext.remote(device_id="phone-1", scopes={"*", "agent.write"})

        with self.assertRaises(ControlApiError) as raised:
            self.policy.authorize(request, context)

        self.assertEqual(raised.exception.code, ControlErrorCode.ROUTE_NOT_ALLOWED)

    def test_remote_body_allowlist_blocks_workspace_paths_and_privileged_modes(self) -> None:
        context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_WRITE.value},
        )
        workspace_request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSIONS_CREATE.value,
            body={"title": "remote", "workspaceRoots": ["/Users/undo"]},
        )
        with self.assertRaises(ControlApiError):
            self.policy.authorize(workspace_request, context)

        privileged_request = ControlRequest(
            request_id="request-2",
            path_id=ControlPathId.AGENT_SESSIONS_CREATE.value,
            body={"title": "remote", "mode": "coding"},
        )
        with self.assertRaises(ControlApiError):
            self.policy.authorize(privileged_request, context)

        assistant_request = ControlRequest(
            request_id="request-3",
            path_id=ControlPathId.AGENT_SESSIONS_CREATE.value,
            body={"title": "remote", "mode": "assistant"},
        )
        self.policy.authorize(assistant_request, context)

    def test_remote_session_list_cannot_request_internal_sessions(self) -> None:
        context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_READ.value},
        )
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSIONS_LIST.value,
            query={"includeInternal": True},
        )

        with self.assertRaises(ControlApiError):
            self.policy.authorize(request, context)

    def test_remote_configuration_update_cannot_spoof_audit_identity(self) -> None:
        context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_WRITE.value},
        )
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_CONFIGURATION_UPDATE.value,
            body={
                "expectedRevision": 4,
                "changes": {"defaultModel": "local"},
                "updatedBy": "spoofed-device",
            },
        )

        with self.assertRaises(ControlApiError):
            self.policy.authorize(request, context)

    def test_bounded_artifact_reads_require_session_ownership(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_ARTIFACT_GET.value,
            params={"artifactId": "artifact-1"},
        )

        with self.assertRaises(ControlApiError):
            self.policy.authorize(request, ControlAccessContext.native())

    def test_intercom_rejects_client_supplied_source_identity(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_SESSION_INTERCOM_SEND.value,
            params={"sessionId": "session-1"},
            body={
                "kind": "send",
                "clientMessageId": "message-1",
                "content": "hello",
                "sourceSessionId": "session-2",
            },
        )

        with self.assertRaises(ControlApiError):
            self.policy.authorize(request, ControlAccessContext.native())

    def test_deep_search_remains_local_only(self) -> None:
        request = ControlRequest(
            request_id="request-1",
            path_id=ControlPathId.AGENT_DEEP_SEARCH.value,
            body={"query": "hello", "privacyDisposition": "allowed"},
        )
        context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={ControlScope.AGENT_WRITE.value},
        )

        with self.assertRaises(ControlApiError) as raised:
            self.policy.authorize(request, context)
        self.assertEqual(raised.exception.code, ControlErrorCode.ROUTE_NOT_ALLOWED)

    def test_remote_manifest_contains_only_explicit_remote_safe_routes_and_no_targets(self) -> None:
        context = ControlAccessContext.remote(
            device_id="phone-1",
            scopes={
                ControlScope.CONTROL_READ.value,
                ControlScope.AGENT_READ.value,
            },
        )
        manifest = self.policy.manifest(context=context)

        self.assertTrue(manifest)
        self.assertTrue(all(item["remoteSafe"] for item in manifest))
        self.assertTrue(all("target" not in item for item in manifest))
        self.assertNotIn(ControlPathId.AGENT_TOOLS_LIST.value, {item["pathId"] for item in manifest})

    def test_no_generic_or_privileged_escape_route_is_registered(self) -> None:
        manifest = self.policy.manifest(include_targets=True)
        path_ids = {str(item["pathId"]).lower() for item in manifest}
        targets = {
            str(path).lower()
            for item in manifest
            for path in item["target"].values()
            if path != "facade"
        }

        for forbidden in ("shell", "keychain", "file.read", "file.write"):
            self.assertFalse(any(forbidden in path_id for path_id in path_ids))
        self.assertNotIn("/api/action", targets)
        self.assertNotIn("/api/configuration/import-apply", targets)
        self.assertNotIn("agent.media.import", path_ids)
        self.assertNotIn("agent.tool.execute", path_ids)
        self.assertNotIn("agent.session.get", path_ids)

        entries = {item["pathId"]: item for item in manifest}
        for path_id in (
            "knowledge.database.apply.preview",
            "knowledge.database.apply",
            "knowledge.database.rollback",
        ):
            self.assertFalse(entries[path_id]["remoteSafe"])

        apply_route = self.policy.resolve(ControlPathId.KNOWLEDGE_DATABASE_APPLY)
        self.assertEqual(
            apply_route.required_body,
            {"runId", "confirm", "previewToken", "payloadSha256", "expectedRuntimeRevision"},
        )


if __name__ == "__main__":
    unittest.main()
