from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


class ProductReadinessGateScriptTests(unittest.TestCase):
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
        self.assertIn("-m rag_ime.cli --db-path /tmp/rag-ime-product-gate.sqlite quality-gate", result.stdout)
        self.assertIn("--force-side-candidates", result.stdout)
        self.assertIn("--require-suggestion-cache", result.stdout)
        self.assertIn("--max-old-input-echo-rate 0.01", result.stdout)
        self.assertIn("--require-predictor-capability seededPromptReplay", result.stdout)
        self.assertIn("macOS Squirrel foreground checks skipped", result.stdout)
        self.assertNotIn("squirrel-tryout-gate", result.stdout)
        self.assertNotIn("check_squirrel_soak_report.py", result.stdout)

    def test_product_gate_dry_run_can_require_macos_frontend(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "run_product_readiness_gate.sh"
        env = dict(os.environ)
        env["RAG_IME_REQUIRE_MACOS_FRONTEND"] = "1"

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
        self.assertIn("squirrel-tryout-gate", result.stdout)
        self.assertIn("scripts/check_squirrel_soak_report.py", result.stdout)
        self.assertIn("--report-path /tmp/custom-rag-ime-soak-report.json", result.stdout)
        self.assertIn("--max-stale-applied 0", result.stdout)
        self.assertIn("--min-side-commits 50", result.stdout)
        self.assertIn("--min-post-commit-followups 30", result.stdout)
        self.assertIn("--require-commit-observed", result.stdout)
        self.assertIn("--require-modern-prediction-session", result.stdout)


if __name__ == "__main__":
    unittest.main()
