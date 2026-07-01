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
        if self.path == "/rime-select":
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            self._send_json(
                {
                    "schemaVersion": "rag-ime.rime-selection.v1",
                    "ok": True,
                    "eventId": "event:doctor",
                    "recordedAction": False,
                    "action": None,
                }
            )
            return
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
        self.assertIn("[OK] HTTP sidecar health, rime-suggest, and rime-select passed", result.stdout)
        self.assertIn(
            "[OK] sidecar predictor: local-ollama qwen3.5:0.8b-mlx streamFirstCandidate=true",
            result.stdout,
        )
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_tryout_mode_requires_prepared_squirrel_xcode_and_sidecar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DoctorSidecarHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-tryout-") as tmp:
                tmp_path = Path(tmp)
                workdir = tmp_path / "squirrel"
                workdir.mkdir()
                subprocess.run(["git", "init"], cwd=workdir, check=True, capture_output=True, text=True)
                (workdir / "sources").mkdir()
                (workdir / "sources" / "RagImeSidecarClient.swift").write_text("// client\n", encoding="utf-8")
                (workdir / "sources" / "RagImeSidecarModels.swift").write_text("// models\n", encoding="utf-8")
                (workdir / "Squirrel.xcodeproj").mkdir()
                (workdir / "Squirrel.xcodeproj" / "project.pbxproj").write_text("// pbxproj\n", encoding="utf-8")
                (workdir / "rag-ime.squirrel.custom.yaml").write_text("rag_ime:\n  enabled: true\n", encoding="utf-8")

                fake_bin = tmp_path / "bin"
                fake_bin.mkdir()
                xcodebuild = fake_bin / "xcodebuild"
                xcodebuild.write_text(
                    "\n".join(
                        [
                            "#!/usr/bin/env bash",
                            "if [[ \"$1\" == \"-version\" ]]; then",
                            "  echo 'Xcode 16.0'",
                            "  echo 'Build version 16A000'",
                            "  exit 0",
                            "fi",
                            "if [[ \"$1\" == \"-project\" && \"$3\" == \"-list\" ]]; then",
                            "  echo 'Targets:'",
                            "  echo '  Squirrel'",
                            "  exit 0",
                            "fi",
                            "exit 1",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
                xcodebuild.chmod(0o755)
                env = {
                    **os.environ,
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_SQUIRREL_WORKDIR": str(workdir),
                    "RAG_IME_SIDECAR_HOST": "127.0.0.1",
                    "RAG_IME_SIDECAR_PORT": str(server.server_port),
                    "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                    "RAG_IME_DOCTOR_REQUIRE_TRYOUT": "1",
                    "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "0",
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

        self.assertIn("tryout_readiness: 1", result.stdout)
        self.assertIn("[OK] Squirrel workdir is a git checkout", result.stdout)
        self.assertIn("[OK] xcodebuild can inspect patched Squirrel project", result.stdout)
        self.assertIn("[OK] HTTP sidecar health, rime-suggest, and rime-select passed", result.stdout)
        self.assertIn("[OK] tryout runtime path has launchd or healthy HTTP sidecar", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_tryout_mode_fails_when_squirrel_workdir_is_missing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-tryout-") as tmp:
            env = {
                **os.environ,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(Path(tmp) / "missing-squirrel"),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_TRYOUT": "1",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "0",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                text=True,
                capture_output=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] Squirrel workdir not prepared", result.stdout)
        self.assertIn("summary: failures=", result.stdout)

    def test_doctor_can_require_enabled_macos_input_source(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-input-source-") as tmp:
            tmp_path = Path(tmp)
            app = tmp_path / "Squirrel.app"
            executable = app / "Contents" / "MacOS" / "Squirrel"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)

            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            swift = fake_bin / "swift"
            swift.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=true selectable=true selected=false'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            swift.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("[OK] installed Squirrel.app executable exists", result.stdout)
        self.assertIn("[OK] macOS input source enabled", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_fails_required_macos_input_source_when_not_enabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-input-source-") as tmp:
            tmp_path = Path(tmp)
            app = tmp_path / "Squirrel.app"
            executable = app / "Contents" / "MacOS" / "Squirrel"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)

            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            swift = fake_bin / "swift"
            swift.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified enabled=false selectable=true selected=false'",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            swift.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] macOS input source is registered but not enabled/selectable", result.stdout)


if __name__ == "__main__":
    unittest.main()
