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


class _DoctorSidecarHandler(BaseHTTPRequestHandler):
    suggest_payloads: list[dict[str, object]] = []
    select_payloads: list[dict[str, object]] = []
    provider_name = "local-ollama"
    model = "qwen3.5:0.8b-mlx"
    stream_first_candidate = True
    capability_probe: dict[str, object] = {}
    model_metadata: dict[str, object] = {}

    @classmethod
    def reset(cls) -> None:
        cls.suggest_payloads = []
        cls.select_payloads = []
        cls.provider_name = "local-ollama"
        cls.model = "qwen3.5:0.8b-mlx"
        cls.stream_first_candidate = True
        cls.capability_probe = {}
        cls.model_metadata = {}

    @classmethod
    def use_mlx_logits(cls) -> None:
        cls.provider_name = "local-mlx"
        cls.model = "/tmp/qwen3.5-0.8b-text-4bit"
        cls.stream_first_candidate = False
        cls.capability_probe = {
            "capabilities": {
                "logitsTopK": True,
                "batchCandidates": True,
                "residentModel": True,
            },
            "promptCache": {
                "enabled": True,
                "prepared": True,
            },
            "modelInfo": {
                "textOnly": True,
                "hasVisionConfig": False,
            },
        }
        cls.model_metadata = {
            "candidate_mode": "next-token-logits",
            "candidate_scores": [
                {"text": "模型候选", "tokenId": 100, "logprob": -1.0, "probability": 0.36}
            ],
            "server_timing": {
                "candidateMode": "next-token-logits",
                "fallbackJson": False,
            },
            "prompt_cache": {
                "enabled": True,
                "prepared": True,
            },
        }

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
                    "providerName": self.__class__.provider_name,
                    "model": self.__class__.model,
                    "streamFirstCandidate": self.__class__.stream_first_candidate,
                    "capabilityProbe": self.__class__.capability_probe,
                },
            }
        )

    def do_POST(self) -> None:
        if self.path == "/rime-select":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            self.__class__.select_payloads.append(payload if isinstance(payload, dict) else {})
            self._send_json(
                {
                    "schemaVersion": "rag-ime.rime-selection.v1",
                    "ok": True,
                    "dryRun": bool(isinstance(payload, dict) and payload.get("dryRun")),
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
        payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        self.__class__.suggest_payloads.append(payload if isinstance(payload, dict) else {})
        raw_input = str(payload.get("rawInput") or "") if isinstance(payload, dict) else ""
        committed_context = str(payload.get("committedContext") or "") if isinstance(payload, dict) else ""
        if raw_input == "jiubiruwopinshishur":
            self._send_json(
                {
                    "schemaVersion": "rag-ime.rime-sidecar.v1",
                    "rawInput": raw_input,
                    "preedit": raw_input,
                    "queryBasis": "rawInputFallback",
                    "triggerDecision": {
                        "shouldRefresh": False,
                        "reason": "skip: raw pinyin fallback",
                    },
                    "mergePolicy": {
                        "sideCandidatesEnabled": False,
                        "rawPinyinFallback": True,
                        "sideFirst": True,
                        "rimeFirst": False,
                        "fallbackOrder": ["model", "rag", "rime"],
                    },
                    "displayCandidates": [],
                }
            )
            return
        if raw_input == "asdioj" and committed_context:
            self._send_json(
                {
                    "schemaVersion": "rag-ime.rime-sidecar.v1",
                    "rawInput": raw_input,
                    "preedit": raw_input,
                    "committedContext": committed_context,
                    "queryBasis": "committedContext",
                    "triggerDecision": {
                        "shouldRefresh": True,
                        "reason": "refresh: recent committed context fallback",
                    },
                    "mergePolicy": {
                        "sideCandidatesEnabled": True,
                        "rawPinyinFallback": False,
                        "sideFirst": True,
                        "rimeFirst": False,
                        "fallbackOrder": ["model", "rag", "rime"],
                    },
                    "displayCandidates": [
                        {
                            "label": "1",
                            "selectionKey": "1",
                            "selectionRank": 1,
                            "text": "继续预测",
                            "insertText": "继续预测",
                            "sourceType": "model",
                            "selectionAction": "commit_side_candidate",
                            "sourceIndex": 0,
                            "displayLayout": "inline",
                            "displayLane": "model",
                            "metadata": dict(self.__class__.model_metadata),
                        }
                    ],
                }
            )
            return
        model_candidates = [
            {
                "label": str(index + 1),
                "selectionKey": str(index + 1),
                "selectionRank": index + 1,
                "text": f"模型候选{index + 1}",
                "insertText": f"模型候选{index + 1}",
                "sourceType": "model",
                "selectionAction": "commit_side_candidate",
                "sourceIndex": index,
                "displayLayout": "inline",
                "displayLane": "model",
                "metadata": dict(self.__class__.model_metadata),
            }
            for index in range(5)
        ]
        self._send_json(
            {
                "schemaVersion": "rag-ime.rime-sidecar.v1",
                "displayCandidates": model_candidates
                + [
                    {
                        "label": str(index + 6),
                        "selectionKey": str(index + 6),
                        "selectionRank": index + 6,
                        "text": f"记忆句子{index + 1}",
                        "insertText": f"记忆句子{index + 1}",
                        "sourceType": "rag",
                        "selectionAction": "commit_side_candidate",
                        "sourceIndex": index,
                        "displayLayout": "block",
                        "displayLane": "memory",
                    }
                    for index in range(3)
                ],
                "modelPredictions": [
                    {
                        "text": item["text"],
                        "rank": index + 1,
                        "providerName": self.__class__.provider_name,
                        "latencyMs": 12,
                        "confidence": 1.0,
                        "metadata": dict(self.__class__.model_metadata),
                    }
                    for index, item in enumerate(model_candidates)
                ],
                "mergePolicy": {
                    "rimeFirst": False,
                    "sideFirst": True,
                    "fallbackOrder": ["model", "rag", "rime"],
                },
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
    def setUp(self) -> None:
        _DoctorSidecarHandler.reset()

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
        _DoctorSidecarHandler.select_payloads = []
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
        self.assertTrue(_DoctorSidecarHandler.select_payloads)
        self.assertTrue(_DoctorSidecarHandler.select_payloads[-1].get("dryRun"))
        self.assertIn(
            "[OK] sidecar predictor: local-ollama qwen3.5:0.8b-mlx streamFirstCandidate=true",
            result.stdout,
        )
        self.assertIn("doctor_latency_budget_ms: 250", result.stdout)
        self.assertTrue(_DoctorSidecarHandler.suggest_payloads)
        self.assertTrue(all(payload.get("latencyBudgetMs") == 250 for payload in _DoctorSidecarHandler.suggest_payloads))
        self.assertIn("[OK] raw pinyin guard: dirty raw input skips side lanes", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_tryout_mode_requires_prepared_squirrel_xcode_and_sidecar(self) -> None:
        root = Path(__file__).resolve().parents[1]
        _DoctorSidecarHandler.use_mlx_logits()
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
                sidecar_plist = _write_sidecar_launch_agent_plist(
                    tmp_path / "sidecar.plist",
                    root=root,
                    model=_DoctorSidecarHandler.model,
                    base_url="http://127.0.0.1:18767",
                )
                mlx_plist = _write_mlx_launch_agent_plist(
                    tmp_path / "mlx.plist",
                    root=root,
                    model=_DoctorSidecarHandler.model,
                    port="18767",
                )

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
                    "RAG_IME_SQUIRREL_APP": str(tmp_path / "missing-app" / "Squirrel.app"),
                    "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": "",
                    "RAG_IME_SIDECAR_HOST": "127.0.0.1",
                    "RAG_IME_SIDECAR_PORT": str(server.server_port),
                    "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                    "RAG_IME_DOCTOR_REQUIRE_TRYOUT": "1",
                    "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "0",
                    "RAG_IME_SIDECAR_LAUNCH_AGENT_PLIST": str(sidecar_plist),
                    "RAG_IME_MLX_LAUNCH_AGENT_PLIST": str(mlx_plist),
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
        self.assertTrue(_DoctorSidecarHandler.select_payloads)
        self.assertTrue(_DoctorSidecarHandler.select_payloads[-1].get("dryRun"))
        self.assertIn("[OK] Squirrel workdir is a git checkout", result.stdout)
        self.assertIn("[OK] xcodebuild can inspect patched Squirrel project", result.stdout)
        self.assertIn("[OK] HTTP sidecar health, rime-suggest, and rime-select passed", result.stdout)
        self.assertIn("[OK] candidate contract: model inline + rag block + shared selection keys passed", result.stdout)
        self.assertIn("[OK] raw pinyin guard: dirty raw input skips side lanes", result.stdout)
        self.assertIn("[OK] model generation path: MLX candidates use next-token logits/top-k", result.stdout)
        self.assertIn("[OK] sidecar LaunchAgent plist: matches current sidecar provider/model env", result.stdout)
        self.assertIn("[OK] MLX predictor LaunchAgent plist: matches text-only MLX model", result.stdout)
        self.assertIn("[OK] tryout runtime path has launchd or healthy HTTP sidecar", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_fails_required_launch_agent_plist_when_model_drifts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        _DoctorSidecarHandler.use_mlx_logits()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _DoctorSidecarHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-launchd-drift-") as tmp:
                tmp_path = Path(tmp)
                sidecar_plist = _write_sidecar_launch_agent_plist(
                    tmp_path / "sidecar.plist",
                    root=root,
                    model="/tmp/old-qwen-model",
                    base_url="http://127.0.0.1:18767",
                )
                mlx_plist = _write_mlx_launch_agent_plist(
                    tmp_path / "mlx.plist",
                    root=root,
                    model="/tmp/old-qwen-model",
                    port="18767",
                )
                env = {
                    **os.environ,
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                    "RAG_IME_SIDECAR_HOST": "127.0.0.1",
                    "RAG_IME_SIDECAR_PORT": str(server.server_port),
                    "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                    "RAG_IME_DOCTOR_REQUIRE_LAUNCH_AGENT_PLIST": "1",
                    "RAG_IME_SIDECAR_LAUNCH_AGENT_PLIST": str(sidecar_plist),
                    "RAG_IME_MLX_LAUNCH_AGENT_PLIST": str(mlx_plist),
                }
                result = subprocess.run(
                    ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                    cwd="/tmp",
                    env=env,
                    text=True,
                    capture_output=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] sidecar LaunchAgent plist: drift:", result.stdout)
        self.assertIn("RAG_IME_PREDICTOR_MODEL='/tmp/old-qwen-model'", result.stdout)
        self.assertIn("[FAIL] MLX predictor LaunchAgent plist: drift:", result.stdout)
        self.assertIn("RAG_IME_MLX_MODEL='/tmp/old-qwen-model'", result.stdout)

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
            calls_log = tmp_path / "squirrel-calls.log"
            app = _write_fake_squirrel_app(
                tmp_path / "Squirrel.app",
                body="#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$SQUIRREL_CALLS_LOG\"\nexit 0\n",
            )

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
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": str(app),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "1",
                "SQUIRREL_CALLS_LOG": str(calls_log),
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            calls = calls_log.read_text(encoding="utf-8")

        self.assertIn("[OK] installed Squirrel.app executable exists", result.stdout)
        self.assertIn("[OK] macOS input source enabled", result.stdout)
        self.assertIn("--register-input-source", calls)
        self.assertIn("--enable-input-source im.rime.inputmethod.Squirrel.Hans", calls)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_can_require_patched_squirrel_app_marker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-patched-app-") as tmp:
            tmp_path = Path(tmp)
            app = _write_fake_squirrel_app(tmp_path / "Squirrel.app", body="#!/usr/bin/env bash\nexit 0\n")
            fake_bin = _write_fake_swift(tmp_path, enabled=True)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": str(app),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_PATCHED_APP": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] installed Squirrel.app lacks current RAG-IME frontend patch", result.stdout)

    def test_doctor_reports_stale_duplicate_squirrel_app_as_warning(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-duplicate-app-") as tmp:
            tmp_path = Path(tmp)
            app = _write_fake_squirrel_app(
                tmp_path / "Squirrel.app",
                body=(
                    "#!/usr/bin/env bash\n"
                    "# rag-ime.squirrel-frontend-trace.v1\n"
                    "# panel_text_layout\n"
                    "# sidecar_request_scheduled\n"
                    "# sidecar_empty_response_ignored\n"
                    "exit 0\n"
                ),
            )
            stale = _write_fake_squirrel_app(tmp_path / "StaleSquirrel.app", body="#!/usr/bin/env bash\nexit 0\n")
            fake_bin = _write_fake_swift(tmp_path, enabled=True)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": f"{app}:{stale}",
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

        self.assertIn("[OK] installed Squirrel.app contains current RAG-IME frontend patch", result.stdout)
        self.assertIn(
            "[WARN] stale Squirrel.app with same bundle id lacks current RAG-IME frontend patch",
            result.stdout,
        )
        self.assertIn("scripts/replace_system_squirrel_app.sh", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_fails_required_patched_app_when_stale_duplicate_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-duplicate-app-") as tmp:
            tmp_path = Path(tmp)
            app = _write_fake_squirrel_app(
                tmp_path / "Squirrel.app",
                body=(
                    "#!/usr/bin/env bash\n"
                    "# rag-ime.squirrel-frontend-trace.v1\n"
                    "# panel_text_layout\n"
                    "# sidecar_request_scheduled\n"
                    "# sidecar_empty_response_ignored\n"
                    "exit 0\n"
                ),
            )
            stale = _write_fake_squirrel_app(tmp_path / "StaleSquirrel.app", body="#!/usr/bin/env bash\nexit 0\n")
            fake_bin = _write_fake_swift(tmp_path, enabled=True)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": f"{app}:{stale}",
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "1",
                "RAG_IME_DOCTOR_REQUIRE_PATCHED_APP": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "[FAIL] stale Squirrel.app with same bundle id lacks current RAG-IME frontend patch",
            result.stdout,
        )
        self.assertIn("scripts/replace_system_squirrel_app.sh", result.stdout)
        self.assertIn("summary: failures=", result.stdout)

    def test_doctor_ignores_original_squirrel_when_configured_app_uses_branded_bundle_id(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-branded-app-") as tmp:
            tmp_path = Path(tmp)
            app = _write_fake_squirrel_app(
                tmp_path / "RAG-IME.app",
                body=(
                    "#!/usr/bin/env bash\n"
                    "# rag-ime.squirrel-frontend-trace.v1\n"
                    "# panel_text_layout\n"
                    "# sidecar_request_scheduled\n"
                    "# sidecar_empty_response_ignored\n"
                    "exit 0\n"
                ),
                bundle_id="im.rag-ime.inputmethod.RagIme",
            )
            original_squirrel = _write_fake_squirrel_app(
                tmp_path / "SystemSquirrel.app",
                body="#!/usr/bin/env bash\nexit 0\n",
            )
            fake_bin = _write_fake_swift(tmp_path, enabled=True)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SQUIRREL_APP": str(app),
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": f"{app}:{original_squirrel}",
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_INPUT_SOURCE": "1",
                "RAG_IME_DOCTOR_REQUIRE_PATCHED_APP": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("[OK] no stale same-bundle Squirrel.app detected", result.stdout)
        self.assertNotIn("stale Squirrel.app with same bundle id", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_can_require_frontend_trace_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-frontend-trace-") as tmp:
            tmp_path = Path(tmp)
            trace_log = tmp_path / "squirrel-frontend.jsonl"
            _write_frontend_trace_log(trace_log)
            env = {
                **os.environ,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE": "1",
                "RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG": str(trace_log),
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertIn("require_frontend_trace: 1", result.stdout)
        self.assertIn("[OK] frontend trace passed: events=4 modelInline=5 ragBlock=3 numberKey=6 sideCommitLabel=6", result.stdout)
        self.assertIn("summary: failures=0", result.stdout)

    def test_doctor_fails_required_frontend_trace_without_events(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-doctor-frontend-trace-") as tmp:
            tmp_path = Path(tmp)
            trace_log = tmp_path / "missing.jsonl"
            env = {
                **os.environ,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SQUIRREL_WORKDIR": str(tmp_path / "missing-squirrel"),
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_DOCTOR_CHECK_LAUNCHD": "0",
                "RAG_IME_DOCTOR_REQUIRE_FRONTEND_TRACE": "1",
                "RAG_IME_SQUIRREL_FRONTEND_TRACE_LOG": str(trace_log),
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "doctor_squirrel_integration.sh")],
                cwd="/tmp",
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[FAIL] frontend trace missing mixed panel or number-key side commit", result.stdout)
        self.assertIn("latestMixedPanel=False", result.stdout)
        self.assertIn("latestSideCommit=False", result.stdout)
        self.assertIn("latestNumberKeySideCommit=False", result.stdout)

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
                "RAG_IME_SQUIRREL_DUPLICATE_APP_CANDIDATES": str(app),
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


def _write_fake_swift(tmp_path: Path, *, enabled: bool) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    swift = fake_bin / "swift"
    swift.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                (
                    "echo 'id=im.rime.inputmethod.Squirrel.Hans name=Squirrel - Simplified "
                    f"enabled={'true' if enabled else 'false'} selectable=true selected=false'"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    swift.chmod(0o755)
    return fake_bin


def _write_fake_squirrel_app(
    path: Path,
    *,
    body: str,
    bundle_id: str = "im.rime.inputmethod.Squirrel",
) -> Path:
    executable = path / "Contents" / "MacOS" / "Squirrel"
    executable.parent.mkdir(parents=True)
    executable.write_text(body, encoding="utf-8")
    executable.chmod(0o755)
    info_plist = path / "Contents" / "Info.plist"
    with info_plist.open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id}, handle)
    return path


def _write_sidecar_launch_agent_plist(path: Path, *, root: Path, model: str, base_url: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "com.rag-ime.sidecar",
        "ProgramArguments": [
            sys.executable,
            str(root / "scripts" / "sidecar_launch.py"),
            "--core-mode",
            "local",
            "--db-path",
            "/tmp/rag-ime.sqlite",
            "sidecar-server",
            "--host",
            "127.0.0.1",
            "--port",
            "8766",
            "--project",
            "wisdom-weasel-rag-ime",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            "RAG_IME_SOURCE_ROOT": str(root),
            "RAG_IME_ROOT": "/tmp/RagIme/app",
            "RAG_IME_DB_PATH": "/tmp/rag-ime.sqlite",
            "RAG_IME_CORE_MODE": "local",
            "RAG_IME_PREDICTOR_PROVIDER": "mlx",
            "RAG_IME_PREDICTOR_BASE_URL": base_url,
            "RAG_IME_PREDICTOR_MODEL": model,
            "RAG_IME_PREDICTOR_PROFILE": "instant",
            "RAG_IME_PREDICTOR_STREAM_FIRST": "0",
        },
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)
    return path


def _write_mlx_launch_agent_plist(path: Path, *, root: Path, model: str, port: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "com.rag-ime.mlx-predictor",
        "ProgramArguments": [
            sys.executable,
            str(root / "scripts" / "sidecar_launch.py"),
            "mlx-predictor-server",
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "--model",
            model,
            "--max-tokens",
            "16",
            "--temperature",
            "0.05",
            "--top-p",
            "0.8",
            "--prompt-cache",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            "RAG_IME_SOURCE_ROOT": str(root),
            "RAG_IME_ROOT": "/tmp/RagIme/app",
            "RAG_IME_MLX_MODEL": model,
            "RAG_IME_MLX_HOST": "127.0.0.1",
            "RAG_IME_MLX_PORT": port,
            "RAG_IME_MLX_MAX_TOKENS": "16",
            "RAG_IME_MLX_TEMPERATURE": "0.05",
            "RAG_IME_MLX_TOP_P": "0.8",
            "RAG_IME_MLX_PROMPT_CACHE": "1",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
            "all_proxy": "",
        },
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)
    return path


def _write_frontend_trace_log(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "event": "panel_display_candidates",
                "timestampMs": 1,
                "forcesHorizontalLayout": True,
                "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "event": "panel_text_layout",
                "timestampMs": 2,
                "forcesHorizontalLayout": True,
                "linear": True,
                "vertical": False,
                "candidateCounts": {"total": 8, "modelInline": 5, "ragBlock": 3, "rime": 0},
                "separators": ["", "  ", "  ", "  ", "  ", "\n", "\n", "\n"],
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "event": "number_key_route",
                "timestampMs": 3,
                "key": "6",
                "candidate": {
                    "label": "6",
                    "selectionKey": "6",
                    "selectionRank": 6,
                    "sourceType": "rag",
                    "selectionAction": "commit_side_candidate",
                    "displayLayout": "block",
                },
            },
            ensure_ascii=False,
        )
        + "\n"
        + json.dumps(
            {
                "event": "side_candidate_commit",
                "timestampMs": 4,
                "candidate": {
                    "label": "6",
                    "selectionKey": "6",
                    "selectionRank": 6,
                    "sourceType": "rag",
                    "selectionAction": "commit_side_candidate",
                    "displayLayout": "block",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
