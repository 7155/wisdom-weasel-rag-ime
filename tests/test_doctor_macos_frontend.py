from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


class _NativeDoctorSidecarHandler(BaseHTTPRequestHandler):
    payloads: list[dict[str, object]] = []

    @classmethod
    def reset(cls) -> None:
        cls.payloads = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"ok": True, "eventCount": 42})

    def do_POST(self) -> None:
        if self.path != "/rime-suggest":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        self.__class__.payloads.append(payload if isinstance(payload, dict) else {})
        raw_input = str(payload.get("rawInput") or "") if isinstance(payload, dict) else ""
        if raw_input == "git status":
            self._send_json(
                {
                    "schemaVersion": "rag-ime.rime-sidecar.v1",
                    "displayCandidates": [
                        {
                            "label": "1",
                            "selectionKey": "1",
                            "selectionRank": 1,
                            "text": "git status",
                            "insertText": "git status",
                            "sourceType": "raw_english",
                            "selectionAction": "commit_side_candidate",
                        }
                    ],
                }
            )
            return
        self._send_json(
            {
                "schemaVersion": "rag-ime.rime-sidecar.v1",
                "displayCandidates": [
                    {
                        "label": "1",
                        "selectionKey": "1",
                        "selectionRank": 1,
                        "text": "继续预测",
                        "insertText": "继续预测",
                        "sourceType": "model",
                        "selectionAction": "commit_side_candidate",
                    },
                    {
                        "label": "2",
                        "selectionKey": "2",
                        "selectionRank": 2,
                        "text": "RAG 记忆候选",
                        "insertText": "RAG 记忆候选",
                        "sourceType": "rag",
                        "selectionAction": "commit_side_candidate",
                    },
                ],
            }
        )

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DoctorMacosFrontendScriptTests(unittest.TestCase):
    def test_native_doctor_checks_app_bridge_sidecar_and_raw_guard_without_squirrel(self) -> None:
        root = Path(__file__).resolve().parents[1]
        _NativeDoctorSidecarHandler.reset()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _NativeDoctorSidecarHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-native-doctor-") as tmp:
                tmp_path = Path(tmp)
                app = _write_fake_rag_ime_app(tmp_path, server.server_port)
                result = subprocess.run(
                    ["bash", str(root / "scripts" / "doctor_macos_frontend.sh")],
                    cwd=root,
                    env={
                        **{key: value for key, value in os.environ.items() if not key.startswith("RAG_IME_")},
                        "RAG_IME_PYTHON": sys.executable,
                        "RAG_IME_MACOS_APP": str(app),
                        "RAG_IME_SIDECAR_HOST": "127.0.0.1",
                        "RAG_IME_SIDECAR_PORT": str(server.server_port),
                        "RAG_IME_DOCTOR_REQUIRE_INSTALLED": "0",
                        "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "0",
                        "RAG_IME_DOCTOR_REQUIRE_SELECTED_INPUT_SOURCE": "0",
                        "RAG_IME_DOCTOR_REQUIRE_SIDECAR": "0",
                    },
                    text=True,
                    capture_output=True,
                )
                if result.returncode != 0 and "Killed: 9" in result.stderr:
                    self.skipTest("macOS killed the fake RagImeMac.app fixture")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertIn("RAG-IME native macOS frontend doctor", result.stdout)
        self.assertIn("[OK] native app bundle exists", result.stdout)
        self.assertIn("[OK] InputMethodKit plist keys present", result.stdout)
        self.assertIn("[OK] bridge config is readable", result.stdout)
        self.assertIn("[OK] native bridge decodes rime-sidecar preview", result.stdout)
        self.assertIn("[OK] HTTP sidecar prediction and raw-input guard passed", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)
        self.assertEqual(_NativeDoctorSidecarHandler.payloads[0].get("rawInput"), "")
        self.assertEqual(_NativeDoctorSidecarHandler.payloads[1].get("rawInput"), "git status")

    def test_native_doctor_can_require_installed_app(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-native-doctor-missing-") as tmp:
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_macos_frontend.sh")],
                cwd=root,
                env={
                    **os.environ,
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_MACOS_APP": str(Path(tmp) / "missing.app"),
                    "RAG_IME_DOCTOR_REQUIRE_INSTALLED": "1",
                    "RAG_IME_DOCTOR_REQUIRE_SIDECAR": "0",
                },
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] native app bundle missing", result.stdout)


def _write_fake_rag_ime_app(tmp_path: Path, sidecar_port: int) -> Path:
    app = tmp_path / "RagImeMac.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleExecutable": "RagImeMac",
                "CFBundleIdentifier": "dev.local.inputmethod.RagImeMac",
                "CFBundlePackageType": "APPL",
                "InputMethodConnectionName": "dev.local.inputmethod.RagImeMac_Connection",
                "InputMethodServerControllerClass": "RagInputController",
            },
            handle,
        )
    (resources / "bridge-config.json").write_text(
        json.dumps(
            {
                "repoRoot": str(tmp_path),
                "dbPath": str(tmp_path / "rag-ime.sqlite"),
                "pythonExecutable": sys.executable,
                "project": "wisdom-weasel-rag-ime",
                "topK": 5,
                "sidecarBaseUrl": f"http://127.0.0.1:{sidecar_port}",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    executable = macos / "RagImeMac"
    executable.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "root = pathlib.Path(__file__).resolve().parents[1]",
                "config = json.loads((root / 'Resources' / 'bridge-config.json').read_text())",
                "if '--print-config' in sys.argv:",
                "    print(json.dumps(config, ensure_ascii=False))",
                "elif '--preview-rime-sidecar-json' in sys.argv:",
                "    print(json.dumps({'schemaVersion':'rag-ime.rime-sidecar.v1','predictionFirst':{'mode':'post_commit_predicting'},'displayCandidates':[{'text':'继续预测','sourceType':'model'}]}, ensure_ascii=False))",
                "else:",
                "    sys.exit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return app


if __name__ == "__main__":
    unittest.main()
