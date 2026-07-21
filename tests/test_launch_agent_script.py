from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_room_skills import RoomSkillPolicy


class LaunchAgentScriptTests(unittest.TestCase):
    def test_stop_runtime_proves_all_launch_agents_ports_and_processes_absent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-stop-proof-") as tmp:
            home = Path(tmp) / "home"
            fake_bin = Path(tmp) / "bin"
            home.mkdir()
            fake_bin.mkdir()
            helpers = {
                "launchctl": "#!/bin/sh\n[ \"$1\" = print ] && exit 1\nexit 0\n",
                "lsof": "#!/bin/sh\nexit 1\n",
                "pgrep": "#!/bin/sh\nexit 1\n",
                "pkill": "#!/bin/sh\nexit 0\n",
                "sleep": "#!/bin/sh\nexit 0\n",
            }
            for name, source in helpers.items():
                path = fake_bin / name
                path.write_text(source, encoding="utf-8")
                path.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                "RAG_IME_DISABLE_FRONTEND_ON_STOP": "0",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "stop_rag_ime_runtime.sh")],
                cwd=root,
                env=env,
                check=False,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime stopped and LaunchAgents disabled", result.stdout)
        source = (root / "scripts" / "stop_rag_ime_runtime.sh").read_text(
            encoding="utf-8"
        )
        for process_name in (
            "RagImeDesktopBridge",
            "RagImeVoice",
            "RagImeControl",
            "Squirrel",
        ):
            self.assertIn(process_name, source)

    def test_sidecar_installer_auto_wires_stable_deepseek_env(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-dsv4-") as tmp:
            home = Path(tmp)
            app_support = home / "Library" / "Application Support" / "RagIme"
            app_support.mkdir(parents=True)
            model_env = app_support / "deepseek.env"
            model_env.write_text(
                "DEEPSEEK_API_KEY=test-only\nRAG_IME_DEEPSEEK_MODEL=deepseek-v4-flash\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_SIDECAR_PORT": "18767",
                "RAG_IME_DEEPSEEK_ENV": "",
                "RAG_IME_MODEL_ENV": "",
                "RAG_IME_DEEPSEEK_ACTIVE_RAG": "",
            }
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        launch_env = payload["EnvironmentVariables"]
        self.assertEqual(launch_env["RAG_IME_DEEPSEEK_ENV"], str(model_env))
        self.assertEqual(launch_env["RAG_IME_DEEPSEEK_ACTIVE_RAG"], "1")

    def test_sidecar_installer_copies_pi_provider_catalog_with_owner_only_permissions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-pi-provider-") as tmp:
            home = Path(tmp) / "home"
            source = Path(tmp) / "pikey.md"
            source.write_text('{"provider":{"openai":{"options":{"apiKey":"test-only"}}}}', encoding="utf-8")
            env = {
                **os.environ,
                "HOME": str(home),
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_SIDECAR_PORT": "18767",
                "RAG_IME_PI_PROVIDER_CONFIG": str(source),
            }
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            installed = home / "Library" / "Application Support" / "RagIme" / "pi-providers.json"
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

            self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PI_PROVIDER_CONFIG"], str(installed))
            self.assertEqual(installed.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            self.assertEqual(installed.stat().st_mode & 0o777, 0o600)

    def test_install_frontend_launch_agent_dry_run_pins_user_app(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-launchd-test-") as tmp:
            home = Path(tmp)
            app = home / "Library" / "Input Methods" / "Squirrel.app"
            executable = app / "Contents" / "MacOS" / "Squirrel"
            executable.parent.mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_text(
                "<plist><dict><key>CFBundleIdentifier</key><string>im.rime.inputmethod.Squirrel</string></dict></plist>",
                encoding="utf-8",
            )
            executable.write_text("#!/usr/bin/env bash\nsleep 60\n", encoding="utf-8")
            executable.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(home),
                "RAG_IME_FRONTEND_LAUNCH_AGENT_DRY_RUN": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_frontend_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.frontend.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertIn(str(plist_path), result.stdout)
        self.assertIn("dry-run", result.stdout)
        self.assertEqual(payload["Label"], "com.rag-ime.frontend")
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertEqual(payload["LimitLoadToSessionType"], "Aqua")
        self.assertEqual(payload["ProgramArguments"], [str(executable)])
        self.assertTrue(payload["WorkingDirectory"].endswith("Squirrel.app/Contents/MacOS"))
        self.assertTrue(payload["StandardOutPath"].endswith("Logs/RagIme/frontend.out.log"))
        self.assertTrue(payload["StandardErrorPath"].endswith("Logs/RagIme/frontend.err.log"))

    def test_install_sidecar_launch_agent_dry_run_writes_plist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_SIDECAR_PORT": "18766",
                "RAG_IME_PREDICTOR_PROVIDER": "ollama",
                "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:11434",
                "RAG_IME_PREDICTOR_MODEL": "qwen3.5:0.8b-mlx",
                "RAG_IME_PREDICTOR_PROFILE": "instant",
                "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                "RAG_IME_PREDICTOR_TIMEOUT_MS": "350",
                "RAG_IME_HISTORY_CONTEXT_EVENTS": "6",
                "RAG_IME_MODEL_CONTEXT_CHARS": "120",
                "RAG_IME_MODEL_LANE_MAX_CANDIDATES": "2",
                "RAG_IME_RIME_CACHE_TTL_MS": "400",
                "RAG_IME_EMBEDDING_PROVIDER": "openai-compatible",
                "RAG_IME_EMBEDDING_BASE_URL": "http://127.0.0.1:18000",
                "RAG_IME_EMBEDDING_MODEL": "bge-small-zh",
                "RAG_IME_EMBEDDING_WARMUP": "0",
                "RAG_IME_VECTOR_CANDIDATES": "48",
                "RAG_IME_VECTOR_WEIGHT": "1.7",
                "RAG_IME_VECTOR_AUTO_REBUILD_LIMIT": "5000",
                "RAG_IME_DEEPSEEK_BASE_URL": "https://api.kukuit.com",
                "RAG_IME_DEEPSEEK_API_KEY": "test-deepseek-key",
                "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                "RAG_IME_DEEPSEEK_ACTIVE_RAG": "1",
                "RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS": "1536",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            app_dir = Path(tmp) / "Library" / "Application Support" / "RagIme" / "app"
            self.assertIn(str(plist_path), result.stdout)
            self.assertIn("dry-run", result.stdout)
            self.assertTrue((app_dir / "rag_ime").is_dir())
            self.assertTrue((app_dir / "sidecar_launch.py").is_file())
            marker = json.loads((app_dir / "rag-ime-install-marker.json").read_text(encoding="utf-8"))
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(marker["schemaVersion"], "rag-ime.component-install-marker.v1")
        self.assertEqual(marker["component"], "sidecar-runtime")
        self.assertEqual(marker["sourceRoot"], str(root))
        self.assertTrue(marker["sourceCommit"])
        self.assertEqual(payload["Label"], "com.rag-ime.sidecar")
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertNotIn("PYTHONPATH", payload["EnvironmentVariables"])
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_SOURCE_ROOT"], str(root))
        self.assertTrue(payload["EnvironmentVariables"]["RAG_IME_ROOT"].endswith("RagIme/app"))
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PREDICTOR_PROVIDER"], "ollama")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PREDICTOR_MODEL"], "qwen3.5:0.8b-mlx")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PREDICTOR_STREAM_FIRST"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_HISTORY_CONTEXT_EVENTS"], "6")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_MODEL_CONTEXT_CHARS"], "120")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_MODEL_LANE_MAX_CANDIDATES"], "2")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_RIME_CACHE_TTL_MS"], "400")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_EMBEDDING_PROVIDER"], "openai-compatible")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_EMBEDDING_BASE_URL"], "http://127.0.0.1:18000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_EMBEDDING_MODEL"], "bge-small-zh")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_EMBEDDING_WARMUP"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_CANDIDATES"], "48")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_WEIGHT"], "1.7")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_AUTO_REBUILD_LIMIT"], "5000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_BASE_URL"], "https://api.kukuit.com")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_API_KEY"], "test-deepseek-key")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_MODEL"], "deepseek-v4-flash")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_ACTIVE_RAG"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS"], "1536")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_KNOWLEDGE_PYTHON"], sys.executable)
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_COMPOSING_MODEL"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS"], "180")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS"], "180")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_COMPLETION_TTL_MS"], "12000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_COMPLETION_CACHE_MAX_JOBS"], "8")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS"], "12000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "900")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_REQUIRE_FOREGROUND_CONTEXT_FOR_POST_COMMIT"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS"], "700")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PROGRESSIVE_FOREGROUND_CONTEXT_MAX_FRESHNESS_MS"], "2500")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PENDING_PREVIEW"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PRESENTATION_STREAM"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_DEMO_SAFE_FALLBACK"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES"], "16")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES"], "128")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_SUGGESTION_CACHE_SIZE"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_RAG_DIRECT_DISPLAY"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_ACTIVE_RAG_BUTTON"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PI_ENABLED"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AGENT_GATEWAY_ENABLED"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_KNOWLEDGE_SHARED_WORKER"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ROOM_KERNEL_MODE"], "kernel_only")

        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_IDLE_MS"], "180")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_MIN_DELTA_CHARS"], "3")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_MAX_CALLS_PER_10S"], "6")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_IGNORE_COOLDOWN_MS"], "600")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE"], "observe")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_THINKING"], "disabled")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_REASONING_EFFORT"], "low")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_DEEPSEEK_MAX_TOKENS"], "96")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_ENABLED"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_PROFILE"], "sichuan-mild")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_S_SH"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_ONG_ON"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_N_L"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PINYIN_FUZZY_F_H"], "0")
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))
        self.assertIn("sidecar-server", payload["ProgramArguments"])
        self.assertIn("18766", payload["ProgramArguments"])
        self.assertIn("sidecar_launch.py", " ".join(payload["ProgramArguments"]))
        script_source = (root / "scripts" / "install_sidecar_launch_agent.sh").read_text(encoding="utf-8")
        self.assertIn("kill_stale_sidecar_processes", script_source)
        self.assertIn("RAG_IME_KILL_STALE_SIDECAR_ON_INSTALL", script_source)
        self.assertIn("wait_for_sidecar_port_release", script_source)
        self.assertIn('RAG_IME_SIDECAR_HEALTH_TIMEOUT_SECONDS:-45', script_source)
        self.assertIn("while (( SECONDS < health_deadline )); do", script_source)
        self.assertNotIn("for _attempt in {1..20}", script_source)
        self.assertNotIn('launchctl kickstart -k "$DOMAIN/$LABEL"', script_source)

    def test_sidecar_install_does_not_publish_marker_before_health(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-sidecar-marker-test-") as tmp:
            home = Path(tmp) / "home"
            fake_bin = Path(tmp) / "bin"
            home.mkdir()
            fake_bin.mkdir()
            launchctl = fake_bin / "launchctl"
            launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            launchctl.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_SIDECAR_PORT": "19876",
                "RAG_IME_SIDECAR_HEALTH_TIMEOUT_SECONDS": "1",
                "RAG_IME_INSTALL_AGENT_GATEWAY": "0",
                "RAG_IME_KILL_STALE_SIDECAR_ON_INSTALL": "0",
                "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=False,
                text=True,
                capture_output=True,
            )
            marker = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "app"
                / "rag-ime-install-marker.json"
            )
            marker_exists = marker.exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("health: not ready", result.stderr)
        self.assertFalse(marker_exists)

    def test_install_agent_gateway_dry_run_uses_managed_runtime_and_scrubs_source_overrides(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-agent-gateway-launchd-") as tmp:
            home = Path(tmp)
            app_support = home / "Library" / "Application Support" / "RagIme"
            app_code = app_support / "app"
            (app_code / "rag_ime").mkdir(parents=True)
            wrapper = app_code / "sidecar_launch.py"
            wrapper.write_text("raise SystemExit(0)\n", encoding="utf-8")
            (app_code / "rag-ime-install-marker.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "rag-ime.component-install-marker.v1",
                        "component": "sidecar-runtime",
                        "sourceCommit": "a" * 40,
                    }
                ),
                encoding="utf-8",
            )
            runtime_root = app_support / "PiRuntime"
            runtime_root.mkdir()
            (runtime_root / "current.json").write_text("{}\n", encoding="utf-8")

            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            side_plist = launch_agents / "com.rag-ime.sidecar.plist"
            with side_plist.open("wb") as handle:
                plistlib.dump(
                    {
                        "ProgramArguments": [sys.executable],
                        "EnvironmentVariables": {
                            "RAG_IME_PI_EXECUTABLE": "/source/pi/dist/cli.js",
                            "RAG_IME_PI_NODE": "/source/node",
                            "RAG_IME_PI_EXTENSION": "/source/rag-ime-control.ts",
                            "RAG_IME_PI_PROTOCOL_VERSION": "1",
                            "RAG_IME_PI_DEBUG_CONTEXT_DIR": "/stale/debug-context",
                            "RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES": "1073741824",
                            "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                        },
                    },
                    handle,
                )
            env = {
                **os.environ,
                "HOME": str(home),
                "RAG_IME_APP_SUPPORT_DIR": str(app_support),
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_REMOTE_ALLOWED_LOGINS": "owner@example.com",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_agent_gateway_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            gateway_plist = launch_agents / "com.rag-ime.agent-gateway.plist"
            with gateway_plist.open("rb") as handle:
                payload = plistlib.load(handle)
            opt_in_directory = home / "private-debug-context"
            opt_in_result = subprocess.run(
                ["bash", str(root / "scripts" / "install_agent_gateway_launch_agent.sh")],
                cwd=root,
                env={
                    **env,
                    "RAG_IME_PI_DEBUG_CONTEXT_DIR": str(opt_in_directory),
                    "RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES": "65536",
                },
                check=True,
                text=True,
                capture_output=True,
            )
            with gateway_plist.open("rb") as handle:
                opt_in_payload = plistlib.load(handle)

        self.assertIn("dry-run", result.stdout)
        self.assertIn("dry-run", opt_in_result.stdout)
        self.assertEqual(payload["Label"], "com.rag-ime.agent-gateway")
        self.assertIn("agent-gateway", payload["ProgramArguments"])
        launch_env = payload["EnvironmentVariables"]
        self.assertEqual(launch_env["RAG_IME_PI_ENABLED"], "1")
        self.assertEqual(launch_env["RAG_IME_PI_VERSION"], "0.80.7")
        self.assertNotIn("RAG_IME_PI_DEBUG_CONTEXT_DIR", launch_env)
        self.assertNotIn("RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES", launch_env)
        self.assertEqual(launch_env["RAG_IME_AGENT_TOOL_URL"], "http://127.0.0.1:8768/api/agent/tool/execute")
        self.assertEqual(launch_env["RAG_IME_REMOTE_ALLOWED_LOGINS"], "owner@example.com")
        self.assertIn("--web-dist", payload["ProgramArguments"])
        self.assertEqual(
            launch_env["RAG_IME_AGENT_GATEWAY_WEB_DIST"],
            str(app_support / "app" / "control-center-web" / "dist"),
        )
        self.assertEqual(launch_env["RAG_IME_DEEPSEEK_MODEL"], "deepseek-v4-flash")
        self.assertNotIn("RAG_IME_PI_EXECUTABLE", launch_env)
        self.assertNotIn("RAG_IME_PI_NODE", launch_env)
        self.assertNotIn("RAG_IME_PI_EXTENSION", launch_env)
        self.assertNotIn("RAG_IME_PI_PROTOCOL_VERSION", launch_env)
        opt_in_env = opt_in_payload["EnvironmentVariables"]
        self.assertEqual(opt_in_env["RAG_IME_PI_DEBUG_CONTEXT_DIR"], str(opt_in_directory))
        self.assertEqual(opt_in_env["RAG_IME_PI_DEBUG_CONTEXT_MAX_BYTES"], "65536")

    def test_restart_runtime_script_defaults_to_foreground_rag_profile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script_text = (root / "scripts" / "restart_rag_ime_runtime.sh").read_text(encoding="utf-8")

        self.assertIn('RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-foreground-rag-proof}"', script_text)
        self.assertIn("-m rag_ime.runtime_profile --profile", script_text)
        self.assertIn('RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-$RAG_IME_PROFILE_POST_COMMIT_COMPLETION_TTL_MS}"', script_text)
        self.assertIn('RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_HARD_TIMEOUT_MS}"', script_text)
        self.assertIn('RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_BUDGET_MS}"', script_text)
        self.assertIn('RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-$RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS}"', script_text)
        self.assertIn('RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-$RAG_IME_PROFILE_SQUIRREL_TIMEOUT_MS}"', script_text)
        self.assertIn('RAG_IME_LOCAL_MODEL_QUALITY_GATE_MODE="observe"', script_text)
        self.assertIn('if [[ "$RUNTIME_PROFILE" == "foreground-rag-proof" ]]', script_text)
        self.assertIn('FRONTEND_ON_RESTART_DEFAULT="1"', script_text)
        self.assertIn('RAG_IME_ENABLE_FRONTEND_ON_RESTART:-$FRONTEND_ON_RESTART_DEFAULT', script_text)

    def test_restart_runtime_prefers_present_mlx_bge_q8_without_overriding_explicit_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script_text = (root / "scripts" / "restart_rag_ime_runtime.sh").read_text(encoding="utf-8")

        self.assertIn('PREFERRED_MLX_BGE_Q8_MODEL=', script_text)
        self.assertIn('MLX_BGE_MODE="${RAG_IME_ENABLE_MLX_BGE:-auto}"', script_text)
        self.assertIn('[[ -d "$PREFERRED_MLX_BGE_Q8_MODEL" ]]', script_text)
        self.assertIn('EMBEDDING_PROVIDER_WAS_EXPLICIT=', script_text)
        self.assertIn('RAG_IME_ENABLE_MLX_BGE=1 conflicts with explicit', script_text)
        self.assertIn('MLX BGE model directory does not exist:', script_text)

    def test_install_sidecar_launch_agent_can_explicitly_disable_keepalive(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-keepalive-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_LAUNCH_KEEP_ALIVE": "0",
            }
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertFalse(payload["KeepAlive"])

    def test_install_sidecar_launch_agent_rejects_broken_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-bad-python-test-") as tmp:
            fake_python = Path(tmp) / "python3"
            fake_python.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": str(fake_python),
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sqlite3/hashlib/ssl", result.stderr)

    def test_install_sidecar_launch_agent_uses_mlx_capable_knowledge_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-mlx-python-test-") as tmp:
            home = Path(tmp) / "home"
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            plist_path.parent.mkdir(parents=True)
            with plist_path.open("wb") as target:
                plistlib.dump(
                    {"EnvironmentVariables": {"RAG_IME_EMBEDDING_PROVIDER": "local-bge-mlx"}},
                    target,
                )

            knowledge_python = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "KnowledgeRuntime"
                / ".venv"
                / "bin"
                / "python"
            )
            knowledge_python.parent.mkdir(parents=True)
            knowledge_python.symlink_to(sys.executable)
            stubs = Path(tmp) / "stubs"
            for package in ("mlx", "transformers"):
                package_dir = stubs / package
                package_dir.mkdir(parents=True)
                (package_dir / "__init__.py").write_text("", encoding="utf-8")

            env = {
                **os.environ,
                "HOME": str(home),
                "PYTHONPATH": str(stubs),
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
            }
            env.pop("RAG_IME_PYTHON", None)
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            with plist_path.open("rb") as source:
                payload = plistlib.load(source)

        self.assertEqual(str(knowledge_python), payload["ProgramArguments"][0])

    def test_install_sidecar_launch_agent_rejects_relative_knowledge_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-knowledge-python-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_KNOWLEDGE_PYTHON": "python3",
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be an absolute executable file", result.stderr)

    def test_install_sidecar_launch_agent_preserves_existing_knowledge_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-preserve-knowledge-python-") as tmp:
            home = Path(tmp) / "home"
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            plist_path.parent.mkdir(parents=True)
            with plist_path.open("wb") as target:
                plistlib.dump(
                    {"EnvironmentVariables": {"RAG_IME_KNOWLEDGE_PYTHON": sys.executable}},
                    target,
                )
            sidecar_python = Path(tmp) / "sidecar-python"
            sidecar_python.symlink_to(sys.executable)
            env = {
                **os.environ,
                "HOME": str(home),
                "RAG_IME_PYTHON": str(sidecar_python),
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
            }
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            with plist_path.open("rb") as source:
                payload = plistlib.load(source)

        self.assertEqual(sys.executable, payload["EnvironmentVariables"]["RAG_IME_KNOWLEDGE_PYTHON"])

    def test_install_sidecar_launch_agent_allows_explicit_v1_budget_override(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-v1-budget-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "1250",
            }
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "1250")

    def test_install_sidecar_launch_agent_preserves_predictor_config_but_resets_product_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-preserve-test-") as tmp:
            home = Path(tmp)
            legacy_extension = home / "legacy-rag-ime-control.ts"
            legacy_extension.write_text("export const staleSecret = 'must-not-be-installed';\n", encoding="utf-8")
            legacy_model_env = home / "legacy-deepseek.env"
            legacy_model_env.write_text(
                "DEEPSEEK_API_KEY=test-only-preserved\n",
                encoding="utf-8",
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            plist_path.parent.mkdir(parents=True)
            with plist_path.open("wb") as fh:
                plistlib.dump(
                    {
                        "Label": "com.rag-ime.sidecar",
                        "EnvironmentVariables": {
                            "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                            "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8767",
                            "RAG_IME_PREDICTOR_MODEL": "/tmp/qwen3.5-0.8b",
                            "RAG_IME_PREDICTOR_PROFILE": "qwen3_06b_ime_hot",
                            "RAG_IME_PREDICTOR_STREAM_FIRST": "1",
                            "RAG_IME_POST_COMMIT_PRESENTATION_STREAM": "1",
                            "RAG_IME_PREDICTOR_ENV": "/tmp/predictor.env",
                            "RAG_IME_PREDICTOR_API_KEY": "preserved-local-secret",
                            "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
                            "RAG_IME_VECTOR_CANDIDATES": "80",
                            "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "4500",
                            "RAG_IME_DEEPSEEK_BASE_URL": "https://api.kukuit.com",
                            "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                            "RAG_IME_DEEPSEEK_ENV": str(legacy_model_env),
                            "RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS": "1536",
                            "RAG_IME_PI_EXECUTABLE": "/tmp/pi/dist/cli.js",
                            "RAG_IME_PI_NODE": "/tmp/node",
                            "RAG_IME_PI_EXTENSION": "/tmp/rag-ime-control.ts",
                            "RAG_IME_PI_VERSION": "0.80.2",
                        },
                    },
                    fh,
                )
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("RAG_IME_") and not key.startswith("DEEPSEEK_")
            }
            env.update(
                {
                    "HOME": str(home),
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_DEEPSEEK_ENV": str(legacy_model_env),
                    "RAG_IME_PI_EXTENSION": str(legacy_extension),
                }
            )
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)
            managed_extension = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "app"
                / "integrations"
                / "pi"
                / "rag-ime-control.ts"
            )
            managed_native_session = managed_extension.with_name("pi-native-session.ts")
            managed_extension_text = managed_extension.read_text(encoding="utf-8")
            managed_native_session_text = managed_native_session.read_text(encoding="utf-8")
            portable_pi_root = managed_extension.parent
            portable_room_policy = portable_pi_root / "room-skill-policy.json"
            portable_room_skills = portable_pi_root / "skills"
            portable_room_skill = (
                portable_room_skills / "room-delivery-closure" / "SKILL.md"
            )
            RoomSkillPolicy(portable_room_policy, portable_room_skills)
            portable_room_policy_text = portable_room_policy.read_text(encoding="utf-8")
            portable_room_skill_text = portable_room_skill.read_text(encoding="utf-8")
            managed_memory_skill = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "Agent"
                / "config"
                / "skills"
                / "rag-ime-memory-curator"
                / "SKILL.md"
            )
            managed_memory_skill_text = managed_memory_skill.read_text(encoding="utf-8")

        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROVIDER"], "mlx")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_BASE_URL"], "http://127.0.0.1:8767")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_MODEL"], "/tmp/qwen3.5-0.8b")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_STREAM_FIRST"], "0")
        self.assertEqual(env_vars["RAG_IME_POST_COMMIT_PRESENTATION_STREAM"], "0")
        self.assertEqual(env_vars["RAG_IME_ROOM_KERNEL_MODE"], "kernel_only")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_ENV"], "/tmp/predictor.env")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_API_KEY"], "preserved-local-secret")
        self.assertNotIn("preserved-local-secret", result.stdout + result.stderr)
        self.assertEqual(env_vars["RAG_IME_EMBEDDING_PROVIDER"], "local-hash")
        self.assertEqual(env_vars["RAG_IME_VECTOR_CANDIDATES"], "80")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_BASE_URL"], "https://api.kukuit.com")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_MODEL"], "deepseek-v4-flash")
        self.assertEqual(
            env_vars["RAG_IME_DEEPSEEK_ENV"],
            str(home / "Library" / "Application Support" / "RagIme" / "deepseek.env"),
        )
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS"], "1536")
        self.assertNotIn("RAG_IME_PI_EXECUTABLE", env_vars)
        self.assertNotIn("RAG_IME_PI_NODE", env_vars)
        self.assertNotIn("RAG_IME_PI_EXTENSION", env_vars)
        self.assertEqual(
            managed_extension_text,
            (root / "integrations" / "pi" / "rag-ime-control.ts").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            managed_native_session_text,
            (root / "integrations" / "pi" / "pi-native-session.ts").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            portable_room_policy_text,
            (root / "integrations" / "pi" / "room-skill-policy.json").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            portable_room_skill_text,
            (
                root
                / "integrations"
                / "pi"
                / "skills"
                / "room-delivery-closure"
                / "SKILL.md"
            ).read_text(encoding="utf-8"),
        )
        self.assertNotIn("must-not-be-installed", managed_extension_text)
        self.assertIn("remember_preview", managed_memory_skill_text)
        self.assertIn("agent_role_book", managed_memory_skill_text)
        self.assertEqual(
            managed_memory_skill_text,
            (
                root
                / "integrations"
                / "pi"
                / "skills"
                / "rag-ime-memory-curator"
                / "SKILL.md"
            ).read_text(encoding="utf-8"),
        )
        self.assertNotIn("RAG_IME_PI_VERSION", env_vars)
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_THINKING"], "disabled")
        self.assertEqual(env_vars["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "900")
        self.assertEqual(env_vars["RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL"], "1")
        self.assertEqual(env_vars["RAG_IME_RAG_DIRECT_DISPLAY"], "1")

    def test_install_sidecar_launch_agent_does_not_shadow_managed_pi_without_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-managed-pi-test-") as tmp:
            home = Path(tmp)
            stale_extension = home / "stale-rag-ime-control.ts"
            stale_extension.write_text("export const stale = true;\n", encoding="utf-8")
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("RAG_IME_") and not key.startswith("DEEPSEEK_")
            }
            env.update(
                {
                    "HOME": str(home),
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_PI_EXTENSION": str(stale_extension),
                }
            )
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

            managed_extension = (
                home
                / "Library"
                / "Application Support"
                / "RagIme"
                / "app"
                / "integrations"
                / "pi"
                / "rag-ime-control.ts"
            )
            self.assertTrue(managed_extension.is_file())
            self.assertNotIn("RAG_IME_PI_EXTENSION", payload["EnvironmentVariables"])
            self.assertNotIn(str(stale_extension), plistlib.dumps(payload).decode("utf-8"))

    def test_install_sidecar_launch_agent_can_enable_local_vector_baseline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-vector-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_ENABLE_LOCAL_VECTOR": "1",
            }
            for key in list(env):
                if key.startswith("RAG_IME_EMBEDDING_") or key in {
                    "RAG_IME_VECTOR_CANDIDATES",
                    "RAG_IME_VECTOR_WEIGHT",
                    "RAG_IME_VECTOR_AUTO_REBUILD_LIMIT",
                }:
                    env.pop(key, None)
            subprocess.run(
                ["bash", str(root / "scripts" / "install_sidecar_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_EMBEDDING_PROVIDER"], "local-hash")
        self.assertEqual(env_vars["RAG_IME_EMBEDDING_DIMENSIONS"], "96")
        self.assertEqual(env_vars["RAG_IME_VECTOR_CANDIDATES"], "80")
        self.assertEqual(env_vars["RAG_IME_VECTOR_WEIGHT"], "1.4")
        self.assertEqual(env_vars["RAG_IME_VECTOR_AUTO_REBUILD_LIMIT"], "5000")

    def test_install_mlx_predictor_launch_agent_dry_run_writes_plist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-launchd-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_MLX_PYTHON": sys.executable,
                "RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_MLX_PORT": "18767",
                "RAG_IME_MLX_MODEL": "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local",
                "RAG_IME_MLX_PROFILE": "qwen3_06b_ime_hot",
                "RAG_IME_MLX_PROMPT_CACHE": "1",
                "RAG_IME_MLX_PREFIX_CACHE": "0",
                "RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES": "8",
                "RAG_IME_MLX_PREFIX_CACHE_MAX_MB": "32",
                "RAG_IME_MLX_PROMPT_MODE": "base-completion",
                "RAG_IME_MEMORY_PROFILE": "low",
                "RAG_IME_HF_HOME": str(Path(tmp) / "hf-cache"),
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_mlx_predictor_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = Path(tmp) / "Library" / "LaunchAgents" / "com.rag-ime.mlx-predictor.plist"
            app_dir = (
                Path(tmp)
                / "Library"
                / "Application Support"
                / "RagIme"
                / "components"
                / "mlx-predictor"
            )
            self.assertIn(str(plist_path), result.stdout)
            self.assertIn("dry-run", result.stdout)
            self.assertTrue((app_dir / "rag_ime").is_dir())
            self.assertTrue((app_dir / "sidecar_launch.py").is_file())
            marker = json.loads((app_dir / "rag-ime-install-marker.json").read_text(encoding="utf-8"))
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(marker["schemaVersion"], "rag-ime.component-install-marker.v1")
        self.assertEqual(marker["component"], "mlx-predictor")
        self.assertEqual(marker["sourceRoot"], str(root))
        self.assertTrue(marker["sourceCommit"])
        self.assertEqual(payload["Label"], "com.rag-ime.mlx-predictor")
        self.assertFalse(payload["KeepAlive"])
        self.assertIn("mlx-predictor-server", payload["ProgramArguments"])
        self.assertIn("18767", payload["ProgramArguments"])
        self.assertIn("/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local", payload["ProgramArguments"])
        self.assertIn("--profile", payload["ProgramArguments"])
        self.assertIn("qwen3_06b_ime_hot", payload["ProgramArguments"])
        self.assertIn("--prompt-cache", payload["ProgramArguments"])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_MLX_MODEL"], "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local")
        self.assertEqual(env_vars["RAG_IME_MLX_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_MLX_PORT"], "18767")
        self.assertEqual(env_vars["RAG_IME_MLX_PROMPT_MODE"], "base-completion")
        self.assertEqual(env_vars["RAG_IME_MLX_PREFIX_CACHE"], "0")
        self.assertEqual(env_vars["RAG_IME_MLX_PREFIX_CACHE_MAX_ENTRIES"], "8")
        self.assertEqual(env_vars["RAG_IME_MLX_PREFIX_CACHE_MAX_MB"], "32")
        self.assertEqual(env_vars["RAG_IME_MEMORY_PROFILE"], "low")
        self.assertEqual(env_vars["HTTP_PROXY"], "")
        self.assertEqual(env_vars["HTTPS_PROXY"], "")
        self.assertEqual(env_vars["ALL_PROXY"], "")
        self.assertEqual(env_vars["HF_HOME"], str(Path(tmp) / "hf-cache"))
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))
        script_source = (root / "scripts" / "install_mlx_predictor_launch_agent.sh").read_text(encoding="utf-8")
        self.assertIn("kill_stale_mlx_predictor_processes", script_source)
        self.assertIn("wait_for_mlx_port_release", script_source)
        self.assertIn('"$MODEL" "$MODEL_FINGERPRINT"', script_source)
        self.assertIn("runtime_fingerprint = str(payload.get(\"modelFingerprint\")", script_source)
        self.assertIn("matching_sha256", script_source)
        self.assertNotIn('launchctl kickstart -k "$DOMAIN/$LABEL"', script_source)

    def test_mlx_installer_reuses_verified_python_from_existing_launch_agent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-python-reuse-") as tmp:
            home = Path(tmp)
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.mlx-predictor.plist"
            plist_path.parent.mkdir(parents=True)
            with plist_path.open("wb") as handle:
                plistlib.dump({"ProgramArguments": [sys.executable]}, handle)
            env = {key: value for key, value in os.environ.items() if not key.startswith("RAG_IME_")}
            env.update(
                {
                    "HOME": str(home),
                    "RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_MLX_MODEL": str(home / "model"),
                }
            )

            subprocess.run(
                ["bash", str(root / "scripts" / "install_mlx_predictor_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)

        self.assertEqual(payload["ProgramArguments"][0], sys.executable)

    def test_standalone_mlx_installer_infers_qwen_profile_and_model_id(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-qwen-inference-test-") as tmp:
            home = Path(tmp)
            model = home / "models" / "mlx-community-Qwen3-0.6B-4bit-local"
            model.mkdir(parents=True)
            env = {key: value for key, value in os.environ.items() if not key.startswith("RAG_IME_")}
            env.update(
                {
                    "HOME": str(home),
                    "RAG_IME_MLX_PYTHON": sys.executable,
                    "RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN": "1",
                    "RAG_IME_MLX_MODEL": str(model),
                }
            )

            subprocess.run(
                ["bash", str(root / "scripts" / "install_mlx_predictor_launch_agent.sh")],
                cwd=root,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            plist_path = home / "Library" / "LaunchAgents" / "com.rag-ime.mlx-predictor.plist"
            with plist_path.open("rb") as handle:
                payload = plistlib.load(handle)

        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_MLX_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_MODEL_ID"], model.name)
        profile_index = payload["ProgramArguments"].index("--profile")
        self.assertEqual(payload["ProgramArguments"][profile_index + 1], "qwen3_06b_ime_hot")

    def test_launch_agent_health_checks_bracket_ipv6_and_disable_proxies(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for script_name in (
            "install_mlx_predictor_launch_agent.sh",
            "install_sidecar_launch_agent.sh",
        ):
            with self.subTest(script=script_name):
                script_source = (root / "scripts" / script_name).read_text(encoding="utf-8")
                self.assertIn(
                    'url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host',
                    script_source,
                )
                self.assertIn(
                    'opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))',
                    script_source,
                )
                self.assertIn(
                    'opener.open(f"http://{url_host}:{port}/health", timeout=1.0)',
                    script_source,
                )

    def test_install_mlx_predictor_launch_agent_rejects_broken_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-mlx-bad-python-test-") as tmp:
            fake_python = Path(tmp) / "python3"
            fake_python.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_MLX_PYTHON": str(fake_python),
                "RAG_IME_MLX_LAUNCH_AGENT_DRY_RUN": "1",
            }
            result = subprocess.run(
                ["bash", str(root / "scripts" / "install_mlx_predictor_launch_agent.sh")],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sqlite3/hashlib/ssl", result.stderr)


if __name__ == "__main__":
    unittest.main()
