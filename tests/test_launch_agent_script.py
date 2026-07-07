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
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_POST_COMMIT_ASYNC_COMPLETION"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_COMPOSING_MODEL"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_PINYIN_CONSTRAINED_MODEL"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_FIRST_RESPONSE_MS"], "150")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PROGRESSIVE_FOLLOW_UP_RETRY_MS"], "250")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_COMPLETION_TTL_MS"], "12000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS"], "12000")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "900")
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))
        self.assertIn("sidecar-server", payload["ProgramArguments"])
        self.assertIn("18766", payload["ProgramArguments"])
        self.assertIn("sidecar_launch.py", " ".join(payload["ProgramArguments"]))

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

    def test_install_sidecar_launch_agent_preserves_predictor_config_but_resets_v1_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-preserve-test-") as tmp:
            home = Path(tmp)
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
                            "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
                            "RAG_IME_VECTOR_CANDIDATES": "80",
                            "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "4500",
                        },
                    },
                    fh,
                )
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("RAG_IME_") and not key.startswith("X1API_")
            }
            env.update(
                {
                    "HOME": str(home),
                    "RAG_IME_PYTHON": sys.executable,
                    "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
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
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROVIDER"], "mlx")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_BASE_URL"], "http://127.0.0.1:8767")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_MODEL"], "/tmp/qwen3.5-0.8b")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_STREAM_FIRST"], "1")
        self.assertEqual(env_vars["RAG_IME_EMBEDDING_PROVIDER"], "local-hash")
        self.assertEqual(env_vars["RAG_IME_VECTOR_CANDIDATES"], "80")
        self.assertEqual(env_vars["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "900")

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
        self.assertIn("/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local", payload["ProgramArguments"])
        self.assertIn("--profile", payload["ProgramArguments"])
        self.assertIn("qwen3_06b_ime_hot", payload["ProgramArguments"])
        self.assertIn("--prompt-cache", payload["ProgramArguments"])
        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_MLX_MODEL"], "/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-text-4bit-local")
        self.assertEqual(env_vars["RAG_IME_MLX_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_MLX_PORT"], "18767")
        self.assertEqual(env_vars["HTTP_PROXY"], "")
        self.assertEqual(env_vars["HTTPS_PROXY"], "")
        self.assertEqual(env_vars["ALL_PROXY"], "")
        self.assertEqual(env_vars["HF_HOME"], str(Path(tmp) / "hf-cache"))
        self.assertTrue(payload["WorkingDirectory"].endswith("RagIme"))


if __name__ == "__main__":
    unittest.main()
