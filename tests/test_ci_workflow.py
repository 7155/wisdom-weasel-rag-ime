from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CIWorkflowTests(unittest.TestCase):
    def test_provenance_checks_have_full_git_history(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertEqual(workflow.count("fetch-depth: 0"), 2)

    def test_squirrel_build_uses_a_swift_6_runner(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        patch = (ROOT / "squirrel-patches/0001-add-rag-ime-sidecar.patch").read_text(encoding="utf-8")

        self.assertIn("throws(ReservedPropertyError)", patch)
        self.assertIn("runs-on: macos-15", workflow)


if __name__ == "__main__":
    unittest.main()
