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
        self.assertIn('requiredString("sessionId", in: payload)', pick_files_block)
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
            "managementWorkContract",
            "planningWorkContract",
            "knowledgeDatabaseWorkContract",
            "memoryGraphRead",
            "memoryEntityRead",
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
