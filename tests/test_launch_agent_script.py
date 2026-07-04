from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LaunchAgentScriptTests(unittest.TestCase):
    def test_install_frontend_launch_agent_dry_run_pins_user_app(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-frontend-launchd-test-") as tmp:
            home = Path(tmp)
            app = home / "Library" / "Input Methods" / "RAG-IME.app"
            executable = app / "Contents" / "MacOS" / "Squirrel"
            executable.parent.mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_text(
                "<plist><dict><key>CFBundleIdentifier</key><string>im.rag-ime.inputmethod.RagIme</string></dict></plist>",
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
        self.assertTrue(payload["WorkingDirectory"].endswith("RAG-IME.app/Contents/MacOS"))
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
                "RAG_IME_VECTOR_CANDIDATES": "48",
                "RAG_IME_VECTOR_WEIGHT": "1.7",
                "RAG_IME_VECTOR_AUTO_REBUILD_LIMIT": "5000",
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
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

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
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_CANDIDATES"], "48")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_WEIGHT"], "1.7")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_VECTOR_AUTO_REBUILD_LIMIT"], "5000")
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))
        self.assertIn("sidecar-server", payload["ProgramArguments"])
        self.assertIn("18766", payload["ProgramArguments"])
        self.assertIn("sidecar_launch.py", " ".join(payload["ProgramArguments"]))

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
                "RAG_IME_MLX_MODEL": "mlx-community/Qwen3-0.6B-4bit",
                "RAG_IME_MLX_PROMPT_CACHE": "1",
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
            app_dir = Path(tmp) / "Library" / "Application Support" / "RagIme" / "app"
            self.assertIn(str(plist_path), result.stdout)
            self.assertIn("dry-run", result.stdout)
            self.assertTrue((app_dir / "rag_ime").is_dir())
            self.assertTrue((app_dir / "sidecar_launch.py").is_file())
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(payload["Label"], "com.rag-ime.mlx-predictor")
        self.assertIn("mlx-predictor-server", payload["ProgramArguments"])
        self.assertIn("18767", payload["ProgramArguments"])
        self.assertIn("mlx-community/Qwen3-0.6B-4bit", payload["ProgramArguments"])
        self.assertIn("--prompt-cache", payload["ProgramArguments"])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_MLX_MODEL"], "mlx-community/Qwen3-0.6B-4bit")
        self.assertEqual(env_vars["RAG_IME_MLX_PORT"], "18767")
        self.assertEqual(env_vars["HTTP_PROXY"], "")
        self.assertEqual(env_vars["HTTPS_PROXY"], "")
        self.assertEqual(env_vars["ALL_PROXY"], "")
        self.assertEqual(env_vars["HF_HOME"], str(Path(tmp) / "hf-cache"))
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))


if __name__ == "__main__":
    unittest.main()
