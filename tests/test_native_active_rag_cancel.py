"""Exercise the patched Swift cancellation client against a local HTTP server."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "squirrel-patches/0001-add-rag-ime-sidecar.patch"
OUTBOX = ROOT / "squirrel-patches/sources/RagImeInputCaptureOutbox.swift"


class _CancelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler.
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        state = self.server.request_state  # type: ignore[attr-defined]
        state["requests"].append(
            {
                "path": self.path,
                "body": body,
                "content_type": self.headers.get("Content-Type", ""),
            }
        )
        status = int(state["status"])
        response = state["response"]
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


def _extract_added_file(patch_text: str, path: str) -> str:
    marker = f"+++ b/{path}\n"
    start = patch_text.index(marker) + len(marker)
    end = patch_text.index("\ndiff --git ", start)
    return "\n".join(
        line[1:]
        for line in patch_text[start:end].splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ) + "\n"


def _swift_harness() -> str:
    return r'''
import Foundation

@main
struct Harness {
  static func main() {
    precondition(CommandLine.arguments.count == 3, "expected sidecar URL and outcome")
    let sidecarURL = CommandLine.arguments[1]
    let expectedSuccess = CommandLine.arguments[2] == "success"
    let config = SquirrelConfig([
      "rag_ime/enabled": true,
      "rag_ime/repo_root": "/tmp/rag-ime-native-cancel-test",
      "rag_ime/sidecar_url": sidecarURL,
    ])
    guard let client = RagImeSidecarClient(config: config) else {
      preconditionFailure("test client did not initialize")
    }

    var callbackCount = 0
    var callbackResult: Bool?
    let startedAt = Date()
    client.postActiveRagCancel(sessionId: "native-cancel-session") { result in
      callbackCount += 1
      callbackResult = result
    }
    let callDuration = Date().timeIntervalSince(startedAt)
    precondition(callDuration < 0.25, "cancellation call blocked for \(callDuration)s")

    let deadline = Date().addingTimeInterval(5)
    while callbackCount == 0 && Date() < deadline {
      RunLoop.main.run(until: Date().addingTimeInterval(0.01))
    }
    precondition(callbackCount == 1, "cancellation callback was not delivered")
    guard let callbackResult else {
      preconditionFailure("cancellation callback omitted its result")
    }
    precondition(callbackResult == expectedSuccess, "unexpected cancellation result")
  }
}
'''


class NativeActiveRagCancelTests(unittest.TestCase):
    def test_cancel_uses_identity_only_and_no_cli_fallback(self) -> None:
        client = _extract_added_file(PATCH.read_text(encoding="utf-8"), "sources/RagImeSidecarClient.swift")
        start = client.index("  func postActiveRagCancel")
        end = client.index("\n  func ", start + 1)
        cancel_method = client[start:end]

        self.assertIn('postJSON(["sessionId": sessionId]', cancel_method)
        self.assertIn('endpoint("active-rag/cancel"', cancel_method)
        self.assertIn("timeoutOverride: 3", cancel_method)
        self.assertIn("DispatchQueue.global", cancel_method)
        self.assertIn("DispatchQueue.main.async", cancel_method)
        self.assertNotIn("runCli", cancel_method)
        self.assertNotIn("active-rag-demo", cancel_method)

    def test_cancel_posts_exact_request_and_reports_http_failure(self) -> None:
        if sys.platform != "darwin":
            self.skipTest("the patched Squirrel client uses the macOS Swift toolchain")
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        patch_text = PATCH.read_text(encoding="utf-8")
        models = _extract_added_file(patch_text, "sources/RagImeSidecarModels.swift")
        client = _extract_added_file(patch_text, "sources/RagImeSidecarClient.swift")
        config_stub = r'''
final class SquirrelConfig {
  private let values: [String: Any]

  init(_ values: [String: Any]) {
    self.values = values
  }

  func getBool(_ key: String) -> Bool? { values[key] as? Bool }
  func getString(_ key: String) -> String? { values[key] as? String }
  func getDouble(_ key: String) -> Double? { values[key] as? Double }
}
'''

        with tempfile.TemporaryDirectory(prefix="paw-native-cancel-test-") as directory:
            temp = Path(directory)
            source = temp / "Harness.swift"
            binary = temp / "native-cancel-test"
            source.write_text(
                config_stub
                + "\n"
                + models
                + "\n"
                + client
                + "\n"
                + OUTBOX.read_text(encoding="utf-8")
                + "\n"
                + _swift_harness(),
                encoding="utf-8",
            )
            compiled = subprocess.run(
                [swiftc, "-parse-as-library", str(source), "-o", str(binary)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

            for mode, status, response in (
                ("success", 200, b'{"status":"cancelled"}'),
                ("failure", 500, b'{"status":"failed"}'),
            ):
                server = ThreadingHTTPServer(("127.0.0.1", 0), _CancelHandler)
                server.request_state = {  # type: ignore[attr-defined]
                    "status": status,
                    "response": response,
                    "requests": [],
                }
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = subprocess.run(
                        [str(binary), f"http://127.0.0.1:{server.server_port}", mode],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                requests = server.request_state["requests"]  # type: ignore[attr-defined]
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(request["path"], "/active-rag/cancel")
                self.assertEqual(request["content_type"], "application/json; charset=utf-8")
                self.assertEqual(
                    json.loads(request["body"].decode("utf-8")),
                    {"sessionId": "native-cancel-session"},
                )


if __name__ == "__main__":
    unittest.main()
