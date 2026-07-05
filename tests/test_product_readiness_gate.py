from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from rag_ime.adapter import InputMethodAdapter
from rag_ime.cli import run_acceptance
from rag_ime.local_sqlite_core import LocalSqliteCoreClient


class ProductReadinessGateScriptTests(unittest.TestCase):
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
        self.assertIn("--max-stale-applied", soak_help.stdout)
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
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertIn("python3 -W error::ResourceWarning -m unittest discover -s tests", result.stdout)
        self.assertIn("python3 scripts/acceptance.py", result.stdout)
        self.assertIn("seed demo memories into gate DB", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite seed-demo", result.stdout)
        self.assertIn("seed eval-case memories into gate DB", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite seed-eval-cases", result.stdout)
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite quality-gate", result.stdout)
        self.assertIn("--force-side-candidates", result.stdout)
        self.assertIn("--require-suggestion-cache", result.stdout)
        self.assertIn("--max-visible-candidates 8", result.stdout)
        self.assertIn("--max-side-candidates 5", result.stdout)
        self.assertIn("--max-old-input-echo-rate 0.01", result.stdout)
        self.assertIn("require_predictor_capability=none", result.stdout)
        self.assertNotIn("--require-predictor-capability", result.stdout)
        self.assertIn("macOS Squirrel foreground checks skipped", result.stdout)
        self.assertNotIn("squirrel-tryout-gate", result.stdout)
        self.assertNotIn("check_squirrel_soak_report.py", result.stdout)

    def test_product_gate_dry_run_can_require_macos_frontend_and_predictor_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        env = dict(os.environ)
        env["RAG_IME_REQUIRE_MACOS_FRONTEND"] = "1"
        env["RAG_IME_REQUIRE_PREDICTOR_CAPABILITY"] = "seededPromptReplay"

        result = subprocess.run(
            [
                "bash",
                str(script),
                "--dry-run",
                "--skip-unit-tests",
                "--skip-acceptance",
                "--skip-quality-gate",
                "--soak-report",
                "/tmp/custom-rag-ime-soak-report.json",
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
        self.assertIn("require_predictor_capability=seededPromptReplay", result.stdout)
        self.assertIn("squirrel-tryout-gate", result.stdout)
        self.assertIn("--require-predictor-capability seededPromptReplay", result.stdout)
        self.assertIn("scripts/check_squirrel_soak_report.py", result.stdout)
        self.assertIn("--report-path /tmp/custom-rag-ime-soak-report.json", result.stdout)
        self.assertIn("--max-stale-applied 0", result.stdout)
        self.assertIn("--min-side-commits 50", result.stdout)
        self.assertIn("--min-post-commit-followups 30", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-modern-prediction-session", result.stdout)

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
