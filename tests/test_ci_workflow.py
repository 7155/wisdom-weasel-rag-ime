from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CIWorkflowTests(unittest.TestCase):
    def test_provenance_checks_have_full_git_history(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertEqual(workflow.count("fetch-depth: 0"), 2)
        self.assertEqual(workflow.count("actions/checkout@v6"), 2)
        self.assertEqual(workflow.count("actions/setup-python@v6"), 2)

    def test_squirrel_build_uses_a_swift_6_runner(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        patch = (ROOT / "squirrel-patches/0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("throws(ReservedPropertyError)", patch)
        self.assertIn("runs-on: macos-15", workflow)

    def test_macos_job_runs_full_suite_and_linux_mac_tests_are_explicitly_skipped(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        mac_only_modules = (
            "test_check_macos_input_source.py",
            "test_memory_book_maintenance_scripts.py",
            "test_prepare_squirrel_workspace.py",
            "test_product_readiness_gate.py",
            "test_setup_xcode_for_squirrel.py",
            "test_doctor_squirrel_integration.py",
        )

        self.assertEqual(workflow.count("python -m unittest discover -s tests"), 2)
        self.assertIn("Run full macOS unit suite", workflow)
        for name in mac_only_modules:
            source = (ROOT / "tests" / name).read_text(encoding="utf-8")
            self.assertIn('@unittest.skipUnless(sys.platform == "darwin"', source, name)


if __name__ == "__main__":
    unittest.main()
