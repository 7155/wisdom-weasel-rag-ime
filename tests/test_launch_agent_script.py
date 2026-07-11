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
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

        self.assertEqual(payload["Label"], "com.rag-ime.sidecar")
        self.assertTrue(payload["RunAtLoad"])
        self.assertFalse(payload["KeepAlive"])
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
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PENDING_PREVIEW"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PRESENTATION_STREAM"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_ENABLE_DEMO_SAFE_FALLBACK"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_MODEL_HOLDOVER_MAX_ENTRIES"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_PREDICTION_MANAGER_MAX_ENTRIES"], "16")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_REFRESH_DEBOUNCE_MAX_ENTRIES"], "128")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_PRESENTATION_STREAM_MAX_ENTRIES"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_SUGGESTION_CACHE_SIZE"], "32")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_RAG_DIRECT_DISPLAY"], "0")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_POST_COMMIT_ACTIVE_RAG_BUTTON"], "1")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_IDLE_MS"], "180")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_MIN_DELTA_CHARS"], "3")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_MAX_CALLS_PER_10S"], "6")
        self.assertEqual(payload["EnvironmentVariables"]["RAG_IME_AUTO_PREDICT_IGNORE_COOLDOWN_MS"], "600")
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
        self.assertNotIn('launchctl kickstart -k "$DOMAIN/$LABEL"', script_source)

    def test_restart_runtime_script_exposes_safe_dev_and_v1_proof_profiles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script_text = (root / "scripts" / "restart_rag_ime_runtime.sh").read_text(encoding="utf-8")

        self.assertIn('RUNTIME_PROFILE="${RAG_IME_RUNTIME_PROFILE:-v1-proof}"', script_text)
        self.assertIn("-m rag_ime.runtime_profile --profile", script_text)
        self.assertIn('RAG_IME_POST_COMMIT_COMPLETION_TTL_MS="${RAG_IME_POST_COMMIT_COMPLETION_TTL_MS:-$RAG_IME_PROFILE_POST_COMMIT_COMPLETION_TTL_MS}"', script_text)
        self.assertIn('RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS="${RAG_IME_POST_COMMIT_MODEL_HARD_TIMEOUT_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_HARD_TIMEOUT_MS}"', script_text)
        self.assertIn('RAG_IME_POST_COMMIT_MODEL_BUDGET_MS="${RAG_IME_POST_COMMIT_MODEL_BUDGET_MS:-$RAG_IME_PROFILE_POST_COMMIT_MODEL_BUDGET_MS}"', script_text)
        self.assertIn('RAG_IME_SQUIRREL_LATENCY_BUDGET_MS="${RAG_IME_SQUIRREL_LATENCY_BUDGET_MS:-$RAG_IME_PROFILE_SQUIRREL_LATENCY_BUDGET_MS}"', script_text)
        self.assertIn('RAG_IME_SQUIRREL_TIMEOUT_MS="${RAG_IME_SQUIRREL_TIMEOUT_MS:-$RAG_IME_PROFILE_SQUIRREL_TIMEOUT_MS}"', script_text)

    def test_restart_runtime_prefers_present_mlx_bge_q8_without_overriding_explicit_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script_text = (root / "scripts" / "restart_rag_ime_runtime.sh").read_text(encoding="utf-8")

        self.assertIn('PREFERRED_MLX_BGE_Q8_MODEL=', script_text)
        self.assertIn('MLX_BGE_MODE="${RAG_IME_ENABLE_MLX_BGE:-auto}"', script_text)
        self.assertIn('[[ -d "$PREFERRED_MLX_BGE_Q8_MODEL" ]]', script_text)
        self.assertIn('EMBEDDING_PROVIDER_WAS_EXPLICIT=', script_text)
        self.assertIn('RAG_IME_ENABLE_MLX_BGE=1 conflicts with explicit', script_text)
        self.assertIn('MLX BGE model directory does not exist:', script_text)

    def test_install_sidecar_launch_agent_can_opt_into_keepalive(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-launchd-keepalive-test-") as tmp:
            env = {
                **os.environ,
                "HOME": tmp,
                "RAG_IME_PYTHON": sys.executable,
                "RAG_IME_LAUNCH_AGENT_DRY_RUN": "1",
                "RAG_IME_LAUNCH_KEEP_ALIVE": "1",
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

        self.assertTrue(payload["KeepAlive"])

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
                            "RAG_IME_PREDICTOR_ENV": "/tmp/predictor.env",
                            "RAG_IME_PREDICTOR_API_KEY": "preserved-local-secret",
                            "RAG_IME_EMBEDDING_PROVIDER": "local-hash",
                            "RAG_IME_VECTOR_CANDIDATES": "80",
                            "RAG_IME_POST_COMMIT_MODEL_BUDGET_MS": "4500",
                            "RAG_IME_DEEPSEEK_BASE_URL": "https://api.kukuit.com",
                            "RAG_IME_DEEPSEEK_MODEL": "deepseek-v4-flash",
                            "RAG_IME_DEEPSEEK_ENV": "/tmp/deepseek.env",
                            "RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS": "1536",
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

        env_vars = payload["EnvironmentVariables"]
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROVIDER"], "mlx")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_BASE_URL"], "http://127.0.0.1:8767")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_MODEL"], "/tmp/qwen3.5-0.8b")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_PROFILE"], "qwen3_06b_ime_hot")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_STREAM_FIRST"], "1")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_ENV"], "/tmp/predictor.env")
        self.assertEqual(env_vars["RAG_IME_PREDICTOR_API_KEY"], "preserved-local-secret")
        self.assertNotIn("preserved-local-secret", result.stdout + result.stderr)
        self.assertEqual(env_vars["RAG_IME_EMBEDDING_PROVIDER"], "local-hash")
        self.assertEqual(env_vars["RAG_IME_VECTOR_CANDIDATES"], "80")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_BASE_URL"], "https://api.kukuit.com")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_MODEL"], "deepseek-v4-flash")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_ENV"], "/tmp/deepseek.env")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_ACTIVE_RAG_MAX_TOKENS"], "1536")
        self.assertEqual(env_vars["RAG_IME_DEEPSEEK_THINKING"], "disabled")
        self.assertEqual(env_vars["RAG_IME_POST_COMMIT_MODEL_BUDGET_MS"], "900")
        self.assertEqual(env_vars["RAG_IME_ENABLE_POST_COMMIT_AUTO_MODEL"], "1")
        self.assertEqual(env_vars["RAG_IME_RAG_DIRECT_DISPLAY"], "0")

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
            app_dir = Path(tmp) / "Library" / "Application Support" / "RagIme" / "app"
            self.assertIn(str(plist_path), result.stdout)
            self.assertIn("dry-run", result.stdout)
            self.assertTrue((app_dir / "rag_ime").is_dir())
            self.assertTrue((app_dir / "sidecar_launch.py").is_file())
            with plist_path.open("rb") as fh:
                payload = plistlib.load(fh)

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
