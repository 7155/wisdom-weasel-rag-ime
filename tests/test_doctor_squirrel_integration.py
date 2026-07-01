from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


class _DoctorSidecarHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json(
            {
                "ok": True,
                "eventCount": 2,
                "predictor": {
                    "configured": True,
                    "providerName": "local-ollama",
                    "model": "qwen3.5:0.8b-mlx",
                    "streamFirstCandidate": True,
                },
            }
        )

    def do_POST(self) -> None:
        if self.path != "/rime-suggest":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._send_json(
            {
                "schemaVersion": "rag-ime.rime-sidecar.v1",
                "displayCandidates": [{"label": "1", "text": "本地记忆"}],
            }
        )

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DoctorSquirrelIntegrationScriptTests(unittest.TestCase):
    def test_doctor_default_mode_warns_without_sidecar_but_exits_zero(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-squirrel-") as tmp:
            env = {
                **os.environ,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertIn("RAG-IME Squirrel integration doctor", result.stdout)
        self.assertIn("[OK] Squirrel patch exists", result.stdout)
        self.assertIn("[WARN] Squirrel workdir not prepared", result.stdout)
        self.assertIn("[WARN] HTTP sidecar is not healthy", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_can_require_matching_predictor_configuration(self) -> None:
        root = Path(__file__).resolve().parents[1]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DoctorSidecarHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-squirrel-") as tmp:
                env = {
                    **os.environ,
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                    "RAG_IME_SIDECAR_HOST": "127.0.0.1",
                    "RAG_IME_SIDECAR_PORT": str(server.server_port),
                    "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                    "RAG_IME_DOCTOR_REQUIRE_PREDICTOR": "1",
                    "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                    "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b-mlx",
                    "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                }
                result = subprocess.run(
                    ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                    cwd="/tmp",
                    env=env,
                    check=True,
                    text=True,
                    capture_output=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertIn("[OK] HTTP sidecar health and rime-suggest passed", result.stdout)
        self.assertIn(
            "[OK] sidecar predictor: local-ollama qwen3.5:0.8b-mlx streamFirstCandidate=true",
            result.stdout,
        )
        self.assertIn("summary: failures=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
