from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.desktop_bridge import (
    DESKTOP_BRIDGE_MAX_MESSAGE_BYTES,
    DesktopBridgeClient,
    DesktopBridgeError,
)


class _FakeSocket:
    def __init__(self, responder):
        self.responder = responder
        self.response = b""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def settimeout(self, _timeout):
        return None

    def connect(self, _path):
        return None

    def sendall(self, payload):
        request = json.loads(payload)
        self.response = self.responder(request)

    def recv(self, _size):
        response, self.response = self.response, b""
        return response


class DesktopBridgeClientTests(unittest.TestCase):
    def test_status_round_trip_requires_matching_request_identity(self) -> None:
        def respond(request):
            return (
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                        "requestId": request["requestId"],
                        "ok": True,
                        "result": {
                            "accessibilityTrusted": True,
                            "captureMode": "accessibility_semantics",
                            "usesScreenCapture": False,
                        },
                    }
                ).encode()
                + b"\n"
            )

        client = DesktopBridgeClient(
            socket_path="/tmp/unused-desktop-bridge.sock",
            verify_socket_owner=False,
        )
        with patch("rag_ime.desktop_bridge.socket.socket", return_value=_FakeSocket(respond)):
            result = client.status()

        self.assertTrue(result["accessibilityTrusted"])
        self.assertEqual(result["captureMode"], "accessibility_semantics")
        self.assertFalse(result["usesScreenCapture"])

    def test_native_error_and_request_id_mismatch_fail_closed(self) -> None:
        client = DesktopBridgeClient(
            socket_path="/tmp/unused-desktop-bridge.sock",
            verify_socket_owner=False,
        )

        def stale(request):
            return (
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                        "requestId": request["requestId"],
                        "ok": False,
                        "error": {"code": "stale_state", "message": "desktop_changed"},
                    }
                ).encode()
                + b"\n"
            )

        with patch("rag_ime.desktop_bridge.socket.socket", return_value=_FakeSocket(stale)):
            with self.assertRaisesRegex(DesktopBridgeError, "stale_state"):
                client.inspect()

        def mismatch(_request):
            return (
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.desktop-bridge-response.v1",
                        "requestId": "wrong",
                        "ok": True,
                        "result": {},
                    }
                ).encode()
                + b"\n"
            )

        with patch("rag_ime.desktop_bridge.socket.socket", return_value=_FakeSocket(mismatch)):
            with self.assertRaisesRegex(DesktopBridgeError, "request_id_mismatch"):
                client.status()

    def test_oversized_response_is_rejected(self) -> None:
        client = DesktopBridgeClient(
            socket_path="/tmp/unused-desktop-bridge.sock",
            verify_socket_owner=False,
        )

        def oversized(_request):
            return b"x" * (DESKTOP_BRIDGE_MAX_MESSAGE_BYTES + 1)

        with patch("rag_ime.desktop_bridge.socket.socket", return_value=_FakeSocket(oversized)):
            with self.assertRaisesRegex(DesktopBridgeError, "response_too_large"):
                client.status()

    def test_native_source_is_accessibility_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((root / "macos" / "RagImeDesktopBridge").glob("*.swift"))
        )
        forbidden = (
            "ScreenCaptureKit",
            "CGWindowListCreateImage",
            "CGDisplayCreateImage",
            "VNRecognizeTextRequest",
            "screenshot",
        )
        for symbol in forbidden:
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, source)
        self.assertIn("AXUIElementCopyMultipleAttributeValues", source)
        self.assertIn("currentFlags & ~O_NONBLOCK", source)
        self.assertIn("kAXVisibleChildrenAttribute", source)
        self.assertIn('"AXChildrenInNavigationOrder"', source)
        self.assertIn("kAXContentsAttribute", source)
        self.assertIn("semanticChildren", source)
        self.assertIn("AXObserverAddNotification", source)
        self.assertIn("refreshSnapshotForAction", source)
        self.assertIn("desktop_changed_after_approval", source)
        self.assertIn("AXUIElementCopyElementAtPosition", source)
        self.assertIn("ax_bounds_hit_test_changed", source)
        self.assertIn('"returnedNodeCount": responseRecords.count', source)
        self.assertIn("deadline: Date().addingTimeInterval(0.9)", source)
        self.assertIn("usesScreenCapture", source)


if __name__ == "__main__":
    unittest.main()
