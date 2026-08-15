from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_project_harness import validate_project_harness


class ProjectHarnessTests(unittest.TestCase):
    def test_current_root_harness_is_bounded_and_consistent(self) -> None:
        root = Path(__file__).resolve().parents[1]

        self.assertEqual(validate_project_harness(root), [])

    def test_missing_harness_is_reported_without_inventing_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_project_harness(Path(directory))

        self.assertIn("missing root harness document: AGENTS.md", errors)
        self.assertTrue(any("missing core Skill body" in error for error in errors))
        self.assertFalse(any("Session is not running" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
