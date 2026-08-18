from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "control-center-web" / "src" / "platform"
HOST = ROOT / "macos" / "RagImeControlWebHost"
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "native_control_bridge_contract.json").read_text(
        encoding="utf-8"
    )
)


class NativeControlBridgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routes = (WEB / "routes.ts").read_text(encoding="utf-8")
        cls.transport = (WEB / "transport.ts").read_text(encoding="utf-8")
        cls.native_types = (WEB / "native-bridge.d.ts").read_text(encoding="utf-8")
        cls.native_transport = (WEB / "native-transport.ts").read_text(
            encoding="utf-8"
        )
        cls.native_bridge = (HOST / "NativeBridge.swift").read_text(encoding="utf-8")
        cls.native_events = (HOST / "NativeEventBridge.swift").read_text(
            encoding="utf-8"
        )
        cls.native_routes = (HOST / "NativeRoutePolicy.swift").read_text(
            encoding="utf-8"
        )

    def test_path_ids_are_identical_in_python_typescript_swift_and_fixture(self) -> None:
        from rag_ime.control_api.route_policy import ControlPathId

        expected = set(FIXTURE["pathIds"])
        python_ids = {item.value for item in ControlPathId}
        typescript_ids = set(
            re.findall(r"^\s{2}'([A-Za-z][A-Za-z0-9.-]+)':", self.routes, re.MULTILINE)
        )
        swift_ids = set(
            re.findall(
                r'^\s{12}"([A-Za-z][A-Za-z0-9.-]+)":\s*route\(',
                self.native_routes,
                re.MULTILINE,
            )
        )
        facade_block = _required_match(
            r"facadePathIds:\s*Set<String>\s*=\s*\[(.*?)\]",
            self.native_routes,
        )
        swift_ids.update(re.findall(r'"([A-Za-z][A-Za-z0-9.]+)"', facade_block))

        self.assertEqual(len(expected), FIXTURE["routeCount"])
        self.assertEqual(python_ids, expected)
        self.assertEqual(typescript_ids, expected)
        self.assertEqual(swift_ids, expected)

    def test_subagent_launch_contract_matches_frontend_python_and_native_bridge(self) -> None:
        from rag_ime.control_api import (
            ControlAccessContext,
            ControlPathId,
            ControlRequest,
            ControlScope,
            default_route_policy,
        )

        expected = {
            "sessionId",
            "tasks",
            "agent",
            "version",
            "task",
            "expectedOutput",
            "acceptanceCriteria",
            "outputSchema",
            "modelProfile",
            "thinkingLevel",
            "access",
            "allowedTools",
            "piSkillsEnabled",
            "codexSkillsEnabled",
            "workspaceRoots",
            "todoTask",
            "contextMode",
            "forkEntryId",
            "wait",
        }
        typescript_route = _required_match(
            r"'agent\.subagents\.create':\s*\{(.*?)\n\s{2}\},",
            self.routes,
        )
        typescript_body = _required_match(r"body:\s*\[(.*?)\]", typescript_route)
        swift_route = _required_match(
            r'"agent\.subagents\.create":\s*route\((.*?)\),\n',
            self.native_routes,
        )
        swift_body = _required_match(r"bodyKeys:\s*\[(.*?)\]", swift_route)
        policy = default_route_policy()
        python_route = policy.resolve(
            ControlPathId.AGENT_SUBAGENTS_CREATE,
        )

        self.assertEqual(set(re.findall(r"'([^']+)'", typescript_body)), expected)
        self.assertEqual(set(re.findall(r'"([^"]+)"', swift_body)), expected)
        self.assertEqual(set(python_route.body), expected)
        self.assertEqual(set(python_route.remote_body), expected)
        self.assertNotIn("contextMode", python_route.remote_body_values)

        request = ControlRequest(
            request_id="subagent-launch-contract",
            path_id=ControlPathId.AGENT_SUBAGENTS_CREATE.value,
            body={
                "sessionId": "agent:parent",
                "agent": "reviewer",
                "version": "1",
                "task": "核对实现",
                "expectedOutput": "证据与风险",
                "acceptanceCriteria": ["不得修改文件"],
                "outputSchema": {"type": "object"},
                "modelProfile": "pi/default",
                "thinkingLevel": "high",
                "access": "read_only",
                "allowedTools": ["workspace_read"],
                "piSkillsEnabled": True,
                "codexSkillsEnabled": False,
                "workspaceRoots": ["/workspace"],
                "todoTask": "核对实现",
                "contextMode": "fork",
                "forkEntryId": "latest",
                "wait": False,
            },
        )
        policy.authorize(request, ControlAccessContext.native())
        policy.authorize(
            request,
            ControlAccessContext.remote(
                device_id="paired-device",
                scopes={ControlScope.AGENT_DELEGATE.value},
            ),
        )

    def test_approval_list_supports_cross_session_inbox_without_required_session_id(self) -> None:
        from rag_ime.control_api import (
            ControlAccessContext,
            ControlPathId,
            ControlRequest,
            ControlScope,
            default_route_policy,
        )

        typescript_route = _required_match(
            r"'agent\.approvals\.list':\s*\{(.*?)\n\s{2}\},",
            self.routes,
        )
        swift_route = _required_match(
            r'"agent\.approvals\.list":\s*route\((.*?)\),\n',
            self.native_routes,
        )
        python_route = default_route_policy().resolve(ControlPathId.AGENT_APPROVALS_LIST)

        self.assertNotIn("requiredQuery", typescript_route)
        self.assertNotIn("requiredQuery", swift_route)
        self.assertEqual(python_route.required_query, frozenset())

        default_route_policy().authorize(
            ControlRequest(
                request_id="approval-inbox-contract",
                path_id=ControlPathId.AGENT_APPROVALS_LIST.value,
                query={"limit": "500"},
            ),
            ControlAccessContext.remote(
                device_id="paired-device",
                scopes={ControlScope.AGENT_APPROVE.value},
            ),
        )

    def test_bridge_method_and_response_envelopes_are_locked(self) -> None:
        type_block = _required_match(
            r"export type NativeBridgeMethod\s*=\s*(.*?);", self.native_types
        )
        swift_block = _required_match(
            r"allowedMethods:\s*Set<String>\s*=\s*\[(.*?)\]", self.native_bridge
        )
        self.assertEqual(set(re.findall(r"'([^']+)'", type_block)), set(FIXTURE["methods"]))
        self.assertEqual(set(re.findall(r'"([^"]+)"', swift_block)), set(FIXTURE["methods"]))
        self.assertIn(
            f'static let handlerName = "{FIXTURE["handlerName"]}"', self.native_bridge
        )

        self.assertEqual(
            _typescript_interface_fields(self.native_types, "NativeBridgeRequestEnvelope"),
            set(FIXTURE["requestEnvelopeKeys"]),
        )
        self.assertIn("{ id: string; ok: true; result: unknown }", self.native_types)
        self.assertIn("{ id: string; ok: false; error: NativeBridgeError }", self.native_types)
        self.assertIn('sendToWeb(["id": id, "ok": true, "result": result])', self.native_bridge)
        self.assertIn('sendToWeb(["id": id, "ok": false, "error": error])', self.native_bridge)

    def test_subscribe_payload_and_all_outbound_kinds_match(self) -> None:
        self.assertRegex(
            self.native_transport,
            r"this\.call\('subscribe',\s*\{\s*subscriptionId,\s*"
            r"request:\s*controlSubscriptionWirePayload\(request\)",
        )
        subscribe_block = _required_match(
            r"private func subscribe\(.*?\n    \}", self.native_bridge
        )
        self.assertIn('payload["request"] as? [String: Any]', subscribe_block)
        self.assertIn('requiredString("pathId", in: request)', subscribe_block)
        for key in ("params", "query", "lastEventId"):
            self.assertIn(f'request["{key}"]', subscribe_block)
        self.assertIn('requiredString("subscriptionId", in: payload)', subscribe_block)

        for kind in FIXTURE["subscription"]["outboundKinds"]:
            self.assertIn(f"kind: '{kind}'", self.native_types)
            self.assertIn(f'"kind": "{kind}"', self.native_events)
        self.assertIn("if (envelope.kind === 'error')", self.native_transport)
        self.assertIn("if (envelope.kind === 'complete')", self.native_transport)
        self.assertIn("scheduleSubscriptionReconnect", self.native_transport)

    def test_pick_files_returns_the_shared_receipt_array_shape(self) -> None:
        picked_file_fields = _typescript_interface_fields(self.transport, "PickedFile")
        self.assertEqual(picked_file_fields, set(FIXTURE["pickedFileKeys"]))

        pick_files_block = _required_match(
            r"private func pickFiles\(.*?\n    \}\n\n    private func revealPath",
            self.native_bridge,
        )
        for key in FIXTURE["pickedFileKeys"]:
            self.assertIn(f'"{key}"', pick_files_block)
        self.assertIn("replySuccess(id: id, result: Array(files))", pick_files_block)
        self.assertNotIn('result: ["files":', pick_files_block)
        self.assertIn("parsePickedFile(value, options)", self.native_transport)

    def test_attachment_picker_imports_only_managed_images_to_the_fixed_loopback_route(self) -> None:
        pick_files_block = _required_match(
            r"private func pickFiles\(.*?\n    \}\n\n    private func revealPath",
            self.native_bridge,
        )
        for value in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            self.assertIn(f'"{value}"', pick_files_block)
        self.assertIn("managedMediaOwner(in: payload)", pick_files_block)
        self.assertIn('components.host = "127.0.0.1"', pick_files_block)
        self.assertIn('components.port = 8766', pick_files_block)
        self.assertIn('components.path = "/api/agent/media/import"', pick_files_block)
        self.assertIn('forHTTPHeaderField: "Content-Type"', pick_files_block)
        self.assertIn('forHTTPHeaderField: "Content-Length"', pick_files_block)
        self.assertIn("uploadTask(with: request, fromFile: fileURL", pick_files_block)
        self.assertIn("uploadTask(with: request, from: data", pick_files_block)
        self.assertIn("NSPasteboard.general", pick_files_block)
        self.assertIn("CFGetTypeID(number) != CFBooleanGetTypeID()", pick_files_block)
        self.assertIn('"rag-ime.agent-media.v1"', pick_files_block)
        receipt_block = _required_match(
            r"private func validatedAgentMediaResponse\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertNotIn('"path"', receipt_block)

    def test_clipboard_image_paste_is_typed_owner_bound_and_reuses_managed_import(self) -> None:
        paste_block = _required_match(
            r"private func pasteImages\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn('["sessionId", "roomId", "maxFiles"]', paste_block)
        self.assertIn("managedMediaOwner(in: payload)", paste_block)
        self.assertIn("CFGetTypeID(number) != CFBooleanGetTypeID()", paste_block)
        self.assertIn("pastedAgentImages(maxFiles: number.intValue)", paste_block)
        self.assertIn(
            "uploadAgentImages(id: id, ownerKey: owner.key, ownerId: owner.id, files: selected)",
            paste_block,
        )
        self.assertIn('"agent_media_paste_rejected"', paste_block)

        pasteboard_block = _required_match(
            r"private func pastedAgentImages\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn("NSPasteboard.general", pasteboard_block)
        self.assertIn(".urlReadingFileURLsOnly: true", pasteboard_block)
        self.assertIn("pasteboard.pasteboardItems", pasteboard_block)
        self.assertIn("selected.count < maxFiles", pasteboard_block)

        pasteboard_item_block = _required_match(
            r"private func pastedAgentImage\(.*?\n    \}",
            self.native_bridge,
        )
        for value in ("public.png", "public.jpeg", "com.compuserve.gif", "org.webmproject.webp"):
            self.assertIn(value, pasteboard_item_block)
        self.assertIn("item.data(forType: .tiff)", pasteboard_item_block)
        self.assertIn("bitmap.representation(using: .png", pasteboard_item_block)

        request_block = _required_match(
            r"private func agentMediaImportRequest\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn('components.host = "127.0.0.1"', request_block)
        self.assertIn("components.port = 8766", request_block)
        self.assertIn('components.path = "/api/agent/media/import"', request_block)
        self.assertIn('URLQueryItem(name: ownerKey, value: ownerId)', request_block)

        receipt_block = _required_match(
            r"private func validatedAgentMediaResponse\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn('media[ownerKey] as? String == ownerId', receipt_block)
        self.assertIn('media["ownerId"] as? String == ownerId', receipt_block)
        self.assertIn('ownerKey: ownerId', receipt_block)
        self.assertNotIn('"path"', receipt_block)

    def test_knowledge_picker_streams_only_validated_files_to_the_fixed_loopback_route(self) -> None:
        pick_files_block = _required_match(
            r"private func pickFiles\(.*?\n    \}\n\n    private func pasteImages",
            self.native_bridge,
        )
        self.assertIn('"knowledge-import"', pick_files_block)
        self.assertIn('requiredString("kbId", in: payload)', pick_files_block)
        self.assertNotIn('requiredString("path", in: payload)', pick_files_block)

        validate_block = _required_match(
            r"private func validatedKnowledgeDocument\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn(".isRegularFileKey", validate_block)
        self.assertIn(".isSymbolicLinkKey", validate_block)
        self.assertIn("200 * 1024 * 1024", validate_block)

        request_block = _required_match(
            r"private func knowledgeDocumentImportRequest\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn('components.host = "127.0.0.1"', request_block)
        self.assertIn("components.port = 8766", request_block)
        self.assertIn('components.path = "/api/knowledge-bases/\\(kbId)/documents/import"', request_block)
        self.assertIn('forHTTPHeaderField: "Content-Type"', request_block)
        self.assertIn('forHTTPHeaderField: "Content-Length"', request_block)

        response_block = _required_match(
            r"private func validatedKnowledgeDocumentResponse\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn('"rag-ime.knowledge-document-import.v1"', response_block)
        for key in ("kbId", "documentId", "fileName", "byteSize", "sha256", "status"):
            self.assertIn(f'"{key}"', response_block)
        self.assertNotIn('"path"', response_block)

    def test_knowledge_asset_reader_is_id_bound_bounded_and_returns_a_blob(self) -> None:
        read_block = _required_match(
            r"private func readKnowledgeAsset\(.*?\n    \}",
            self.native_bridge,
        )
        for key in ("kbId", "fileId", "assetId"):
            self.assertIn(f'"{key}"', read_block)
        self.assertIn('pathId: "knowledgeBases.asset.get"', read_block)
        self.assertNotIn('requiredString("path"', read_block)
        self.assertNotIn('requiredString("url"', read_block)

        validate_block = _required_match(
            r"private func validatedKnowledgeAssetResponse\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn("25 * 1024 * 1024", validate_block)
        for mime_type in ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"):
            self.assertIn(f'"{mime_type}"', validate_block)
        self.assertIn('forHTTPHeaderField: "ETag"', validate_block)
        self.assertIn("SHA256.hash(data: data)", validate_block)

        send_block = _required_match(
            r"private func sendKnowledgeBinaryToWeb\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn("NativeBinaryTransferPlan.chunkRanges", send_block)
        self.assertNotIn('"path"', send_block)

        finish_block = _required_match(
            r"private func finishKnowledgeBinaryTransfer\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn("new Blob", finish_block)
        self.assertIn("transfer.received !== transfer.metadata.byteSize", finish_block)
        self.assertNotIn('"path"', finish_block)

        source_block = _required_match(
            r"private func readKnowledgeDocumentSource\(.*?\n    \}",
            self.native_bridge,
        )
        for key in ("kbId", "fileId"):
            self.assertIn(f'"{key}"', source_block)
        self.assertIn('pathId: "knowledgeBases.document.source"', source_block)
        self.assertNotIn('requiredString("path"', source_block)
        self.assertNotIn('requiredString("url"', source_block)

        source_validate_block = _required_match(
            r"private func validatedKnowledgeSourceResponse\(.*?\n    \}",
            self.native_bridge,
        )
        self.assertIn("50 * 1024 * 1024", source_validate_block)
        self.assertIn('"application/pdf"', source_validate_block)
        self.assertIn("SHA256.hash(data: data)", source_validate_block)

    def test_external_action_request_and_receipt_share_hash_bound_fields(self) -> None:
        self.assertEqual(
            _typescript_interface_fields(self.transport, "ExternalActionRequest"),
            set(FIXTURE["externalActionRequestKeys"]),
        )
        self.assertEqual(
            _typescript_interface_fields(self.transport, "ExternalActionReceipt"),
            set(FIXTURE["externalActionReceiptKeys"]),
        )

        external_block = _required_match(
            r"private func runApprovedExternalAction\(.*?\n    \}\n\n    private func requiredString",
            self.native_bridge,
        )
        for key in FIXTURE["externalActionRequestKeys"]:
            self.assertIn(f'"{key}"', external_block)
        for key in ("receiptId", "action", "accepted", "completed", "exitCode"):
            self.assertIn(f'"{key}"', external_block)
        self.assertNotIn('"actionId"', external_block)
        self.assertNotIn('"approval"', external_block)
        self.assertIn("^[a-fA-F0-9]{64}$", external_block)
        self.assertIn('pathId: "diagnostics.action.job"', external_block)
        self.assertIn("validateApprovedExternalActionJob", external_block)
        self.assertIn("expectedRuntimeActionCommandSha256", external_block)
        self.assertNotIn('requiredString("path"', external_block)
        self.assertNotIn('requiredString("command"', external_block)
        self.assertIn('trustedDiagnosticsHelper(named: "apply_predictor_configuration.sh")', external_block)
        self.assertIn('trustedDiagnosticsHelper(named: "apply_input_method_configuration.sh")', external_block)
        self.assertIn('"apply_predictor_configuration.sh"', external_block)
        self.assertIn('"apply_input_method_configuration.sh"', external_block)
        self.assertIn('action == "restart_predictor" ? 115 : 90', external_block)
        self.assertIn(
            "this.call('runApprovedExternalAction', request, undefined, 120_000)",
            self.native_transport,
        )

    def test_capabilities_keep_native_features_nested_and_route_ids_explicit(self) -> None:
        capability_block = _required_match(
            r"private func capabilities\(\).*?\n    \}\n\n    private func performRequest",
            self.native_bridge,
        )
        for key in FIXTURE["capabilityTopLevelKeys"]:
            self.assertIn(f'"{key}"', capability_block)
        for key in FIXTURE["nativeCapabilityKeys"]:
            self.assertIn(f'"{key}"', capability_block)
        self.assertIn('"routeIds": NativeRoutePolicy.knownPathIds.sorted()', capability_block)
        self.assertIn('"native": [', capability_block)
        for key in (
            "agentPersonaCreate",
            "piProviderCredentials",
            "managementWorkContract",
            "inputLexiconWorkContract",
            "planningWorkContract",
            "knowledgeDatabaseWorkContract",
            "documentKnowledgeLibrary",
            "knowledgeDocumentImport",
            "knowledgeParserStatus",
            "knowledgeAssetRead",
            "knowledgeDocumentSourceRead",
            "historyWorkContract",
            "configurationSettingsWorkContract",
            "memoryGraphRead",
            "memoryEntityRead",
            "memoryEdit",
            "memoryBookArchiveWorkContract",
        ):
            self.assertIn(f'"{key}": true', capability_block)

        normalizer = _required_match(
            r"function normalizeNativeCapabilities\(.*?\n\}", self.native_transport
        )
        self.assertIn("payload.routeIds", normalizer)
        self.assertIn("payload.routes", normalizer)
        self.assertIn("payload.native", normalizer)
        for key in FIXTURE["nativeCapabilityKeys"]:
            self.assertIn(key, normalizer)


def _required_match(pattern: str, source: str) -> str:
    match = re.search(pattern, source, re.DOTALL)
    if match is None:
        raise AssertionError(f"source block did not match: {pattern}")
    return match.group(1) if match.lastindex else match.group(0)


def _typescript_interface_fields(source: str, name: str) -> set[str]:
    block = _required_match(rf"export interface {re.escape(name)}\s*\{{(.*?)\n\}}", source)
    return set(re.findall(r"^\s{2}([A-Za-z][A-Za-z0-9]*)\??:", block, re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
