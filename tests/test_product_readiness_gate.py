from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import run_acceptance
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


class ProductReadinessGateScriptTests(unittest.TestCase):
    _GATE_ENV_KEYS = (
        "RAG_IME_REQUIRE_MACOS_FRONTEND",
        "RAG_IME_REQUIRE_SICHUAN_FUZZY",
        "RAG_IME_REQUIRE_PREDICTOR_CAPABILITY",
        "RAG_IME_REQUIRE_MODEL_CANDIDATE_COUNT",
        "RAG_IME_PREPARE_SQUIRREL_FOREGROUND_CHECK_SCRIPT",
        "RAG_IME_FRONTEND_DB_PATH",
        "RAG_IME_FOREGROUND_READINESS_REPORT",
        "RAG_IME_SQUIRREL_SOAK_REPORT",
    )

    def _gate_env(self, **overrides: str) -> dict[str, str]:
        env = dict(os.environ)
        for key in self._GATE_ENV_KEYS:
            env.pop(key, None)
        env.update(overrides)
        return env

    def test_acceptance_empty_local_db_returns_failed_report_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-empty-acceptance-") as tmp:
            db_path = Path(tmp) / "acceptance-empty.sqlite"
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            report = run_acceptance(InputMethodAdapter(core))

        self.assertFalse(report["action_result"]["deleted_removed"])
        self.assertEqual(report["action_result"]["before"], [])
        self.assertEqual(report["action_result"]["after"], [])

    def test_gate_related_cli_flags_are_exposed(self) -> None:
        root = Path(__file__).resolve().parents[1]

        quality_help = subprocess.run(
            ["python3", "-m", "rag_ime.cli", "quality-gate", "--help"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        soak_help = subprocess.run(
            ["python3", "scripts/check_squirrel_soak_report.py", "--help"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("--max-old-input-echo-rate", quality_help.stdout)
        self.assertIn("--require-production-rag-governance", quality_help.stdout)
        self.assertIn("--max-stale-applied", soak_help.stdout)
        self.assertIn("--max-flicker-count", soak_help.stdout)
        self.assertIn("--max-min-visible-violations", soak_help.stdout)
        self.assertIn("--max-rag-empty-cleared-panel", soak_help.stdout)
        self.assertIn("--min-chain-depth", soak_help.stdout)
        self.assertIn("--min-model-candidates-per-panel", soak_help.stdout)
        self.assertIn("--min-model-multi-candidate-panels", soak_help.stdout)
        self.assertIn("--min-source-triplet-panels", soak_help.stdout)
        self.assertIn("--require-snapshot-selection-trace", soak_help.stdout)
        seed_help = subprocess.run(
            ["python3", "-m", "rag_ime.cli", "seed-eval-cases", "--help"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("--cases-file", seed_help.stdout)

    def test_product_gate_dry_run_lists_backend_and_optional_frontend_gates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"

        self.assertTrue(os.access(script, os.X_OK))
        subprocess.run(["bash", "-n", str(script)], cwd=root, check=True)

        result = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--db-path",
                "/tmp/rag-ime-product-gate.sqlite",
                "--cases-file",
                "docs/eval/codex-history-cases.example.jsonl",
            ],
            cwd=root,
            env=self._gate_env(),
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("python3 -W error::ResourceWarning -m unittest discover -s tests", result.stdout)
        self.assertIn("python3 scripts/acceptance.py", result.stdout)
        self.assertIn("db_path=/tmp/rag-ime-product-gate.sqlite", result.stdout)
        self.assertIn("frontend_db_path=", result.stdout)
        self.assertIn("sidecar_latency_budget_ms=300", result.stdout)
        self.assertIn("reset_gate_db=1", result.stdout)
        self.assertIn("require_sichuan_fuzzy=0", result.stdout)
        self.assertIn("seed demo memories into gate DB", result.stdout)
        self.assertIn("require_model_candidate_count=0", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite seed-demo --reset", result.stdout)
        self.assertIn("seed eval-case memories into gate DB", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite seed-eval-cases", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite quality-gate", result.stdout)
        self.assertIn("--skip-acceptance-check", result.stdout)
        self.assertIn("--sidecar-latency-budget-ms 300", result.stdout)
        self.assertIn("--force-side-candidates", result.stdout)
        self.assertIn("--require-suggestion-cache", result.stdout)
        self.assertIn("--require-production-rag-governance", result.stdout)
        self.assertIn("--max-visible-candidates 8", result.stdout)
        self.assertIn("--max-side-candidates 5", result.stdout)
        self.assertIn("--max-old-input-echo-rate 0.01", result.stdout)
        self.assertIn("require_predictor_capability=none", result.stdout)
        self.assertNotIn("--require-predictor-capability", result.stdout)
        self.assertIn("Sichuan fuzzy profile check skipped", result.stdout)
        self.assertNotIn("check_sichuan_fuzzy_profile.sh", result.stdout)
        self.assertIn("macOS Squirrel foreground checks skipped", result.stdout)
        self.assertNotIn("squirrel-tryout-gate", result.stdout)
        self.assertNotIn("check_squirrel_soak_report.py", result.stdout)

    def test_product_gate_dry_run_can_require_sichuan_fuzzy_profile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        env = self._gate_env()
        env["RAG_IME_REQUIRE_SICHUAN_FUZZY"] = "1"

        result = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--skip-unit-tests",
                "--skip-acceptance",
                "--skip-quality-gate",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("require_sichuan_fuzzy=1", result.stdout)
        self.assertIn("Sichuan fuzzy profile check", result.stdout)
        self.assertIn("scripts/check_sichuan_fuzzy_profile.sh", result.stdout)

    def test_product_gate_dry_run_can_require_macos_frontend_and_predictor_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        env = self._gate_env()
        env["RAG_IME_REQUIRE_MACOS_FRONTEND"] = "1"
        env["RAG_IME_REQUIRE_PREDICTOR_CAPABILITY"] = "seededPromptReplay"
        env["RAG_IME_REQUIRE_MODEL_CANDIDATE_COUNT"] = "3"

        result = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--skip-unit-tests",
                "--skip-acceptance",
                "--skip-quality-gate",
                "--db-path",
                "/tmp/rag-ime-backend-gate.sqlite",
                "--frontend-db-path",
                "/tmp/rag-ime-frontend-runtime.sqlite",
                "--soak-report",
                "/tmp/custom-rag-ime-soak-report.json",
                "--foreground-readiness-report",
                "/tmp/custom-rag-ime-foreground-readiness.json",
            ],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("unit tests skipped", result.stdout)
        self.assertIn("acceptance skipped", result.stdout)
        self.assertIn("quality gate skipped", result.stdout)
        self.assertIn("db_path=/tmp/rag-ime-backend-gate.sqlite", result.stdout)
        self.assertIn("frontend_db_path=/tmp/rag-ime-frontend-runtime.sqlite", result.stdout)
        self.assertIn("foreground_readiness_report=/tmp/custom-rag-ime-foreground-readiness.json", result.stdout)
        self.assertIn("require_sichuan_fuzzy=1", result.stdout)
        self.assertIn("require_predictor_capability=seededPromptReplay", result.stdout)
        self.assertIn("require_model_candidate_count=3", result.stdout)
        self.assertIn("scripts/check_sichuan_fuzzy_profile.sh", result.stdout)
        self.assertIn("foreground readiness preflight", result.stdout)
        self.assertIn("scripts/prepare_squirrel_foreground_check.sh", result.stdout)
        self.assertIn("--refresh-registration --no-open --no-wait-typing", result.stdout)
        self.assertIn("--summary-path /tmp/custom-rag-ime-foreground-readiness.json", result.stdout)
        self.assertIn("squirrel-tryout-gate", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-frontend-runtime.sqlite squirrel-tryout-gate", result.stdout)
        self.assertIn("--quality-db-path /tmp/rag-ime-backend-gate.sqlite", result.stdout)
        self.assertNotIn("-m rag_ime.cli --db-path /tmp/rag-ime-backend-gate.sqlite squirrel-tryout-gate", result.stdout)
        self.assertIn("--include-input-source-audit", result.stdout)
        self.assertIn("--require-predictor-capability seededPromptReplay", result.stdout)
        self.assertIn("--require-model-candidate-count 3", result.stdout)
        self.assertIn("scripts/check_squirrel_soak_report.py", result.stdout)
        self.assertIn("--report-path /tmp/custom-rag-ime-soak-report.json", result.stdout)
        self.assertIn("--max-stale-applied 0", result.stdout)
        self.assertIn("--max-flicker-count 0", result.stdout)
        self.assertIn("--max-min-visible-violations 0", result.stdout)
        self.assertIn("--max-rag-empty-cleared-panel 0", result.stdout)
        self.assertIn("--min-side-commits 50", result.stdout)
        self.assertIn("--min-post-commit-followups 30", result.stdout)
        self.assertIn("--min-backspaces 1", result.stdout)
        self.assertIn("--min-app-switches 1", result.stdout)
        self.assertIn("--min-source-triplet-panels 1", result.stdout)
        self.assertIn("--min-chain-depth 10", result.stdout)
        self.assertIn("--min-model-candidates-per-panel 3", result.stdout)
        self.assertIn("--min-model-multi-candidate-panels 1", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-delete-resync", result.stdout)
        self.assertIn("--require-modern-prediction-session", result.stdout)
        self.assertIn("--require-balanced-quota", result.stdout)
        self.assertIn("--require-snapshot-selection-trace", result.stdout)

    def test_product_gate_macos_frontend_stops_after_failed_readiness_preflight(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-gate-preflight-") as tmp:
            tmp_path = Path(tmp)
            prepare_script = tmp_path / "prepare.sh"
            call_log = tmp_path / "calls.log"
            summary_path = tmp_path / "readiness.json"
            prepare_script.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        f"printf '%s\\n' \"$@\" > {call_log}",
                        "while [[ $# -gt 0 ]]; do",
                        "  case \"$1\" in",
                        "    --summary-path) summary=\"$2\"; shift 2 ;;",
                        "    *) shift ;;",
                        "  esac",
                        "done",
                        "cat > \"$summary\" <<'JSON'",
                        '{"schemaVersion":"rag-ime.foreground-readiness.v1","ok":false,"readinessState":"third-party-missing","foregroundReady":false}',
                        "JSON",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            prepare_script.chmod(0o755)
            env = self._gate_env()
            env["RAG_IME_REQUIRE_MACOS_FRONTEND"] = "1"
            env["RAG_IME_PREPARE_SQUIRREL_FOREGROUND_CHECK_SCRIPT"] = str(prepare_script)

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--skip-unit-tests",
                    "--skip-acceptance",
                    "--skip-quality-gate",
                    "--foreground-readiness-report",
                    str(summary_path),
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            prepare_args = call_log.read_text(encoding="utf-8")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreground readiness preflight", result.stdout)
        self.assertIn("--summary-path", prepare_args)
        self.assertIn(str(summary_path), prepare_args)
        self.assertNotIn("squirrel-tryout-gate", result.stdout)

    def test_product_gate_recovers_predictor_env_from_sidecar_launch_agent_plist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-gate-plist-") as tmp:
            tmp_path = Path(tmp)
            plist_path = tmp_path / "Library" / "LaunchAgents" / "com.rag-ime.sidecar.plist"
            plist_path.parent.mkdir(parents=True)
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "com.rag-ime.sidecar",
                        "EnvironmentVariables": {
                            "RAG_IME_PREDICTOR_PROVIDER": "mlx",
                            "RAG_IME_PREDICTOR_BASE_URL": "http://127.0.0.1:8767",
                            "RAG_IME_PREDICTOR_MODEL": "/tmp/local-mlx-model",
                            "RAG_IME_PREDICTOR_PROFILE": "instant",
                            "RAG_IME_PREDICTOR_TIMEOUT_MS": "4321",
                        },
                    }
                )
            )
            env = self._gate_env()
            env["HOME"] = str(tmp_path)
            env["RAG_IME_REQUIRE_PREDICTOR_CAPABILITY"] = "seededPromptReplay"
            for key in list(env):
                if key.startswith("RAG_IME_PREDICTOR_"):
                    env.pop(key)

            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--dry-run",
                    "--skip-unit-tests",
                    "--skip-acceptance",
                    "--skip-quality-gate",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn("predictor_env_source=launch-agent-plist", result.stdout)
        self.assertIn("predictor_provider=mlx", result.stdout)
        self.assertIn("predictor_base_url=http://127.0.0.1:8767", result.stdout)
        self.assertIn("sidecar_latency_budget_ms=4321", result.stdout)
        self.assertIn(f"sidecar_plist={plist_path}", result.stdout)

    def test_product_gate_can_preserve_gate_db_when_explicitly_requested(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"

        result = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--skip-unit-tests",
                "--skip-acceptance",
                "--skip-quality-gate",
                "--no-reset-gate-db",
                "--db-path",
                "/tmp/rag-ime-product-gate.sqlite",
            ],
            cwd=root,
            env=self._gate_env(),
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("reset_gate_db=0", result.stdout)

    def test_squirrel_registration_refresh_defaults_to_product_squirrel_route(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script_text = (root / "scripts" / "refresh_squirrel_input_source_registration.sh").read_text(encoding="utf-8")

        self.assertIn('Input Methods/Squirrel.app', script_text)
        self.assertIn('BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rime.inputmethod.Squirrel}"', script_text)
        self.assertIn('INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"', script_text)
        self.assertIn('RAG_IME_QUARANTINE_STALE_SQUIRREL_APPS:-0', script_text)
        self.assertIn('disabled-input-method-backups', script_text)
        self.assertIn('.disabled-bundle-', script_text)
        self.assertNotIn('Input Methods/RAG-IME.app}"', script_text)
        self.assertNotIn('BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-im.rag-ime.inputmethod.RagIme}"', script_text)

    def test_product_gate_backend_path_passes_against_temp_eval_db(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        with tempfile.TemporaryDirectory(prefix="rag-ime-product-gate-") as tmp:
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--skip-unit-tests",
                    "--skip-acceptance",
                    "--db-path",
                    str(Path(tmp) / "gate.sqlite"),
                ],
                cwd=root,
                env=self._gate_env(),
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertIn("seeded_eval_cases", result.stdout)
        self.assertIn('"passed": true', result.stdout)
        self.assertIn('"name": "rag-pass-rate"', result.stdout)
        self.assertIn('"name": "rime-sidecar-pass-rate"', result.stdout)
        self.assertIn("[product-gate] passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
