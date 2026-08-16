from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_project_harness import (
    validate_project_harness,
    validate_release_candidate_scope,
)


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

    def test_release_scope_rejects_a_base_to_head_path_that_was_not_classified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "release").mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            scope = {
                "schemaVersion": "personal-agent-workbench.release-candidate-scope.v1",
                "source": {"baseCommit": base},
                "summary": {
                    "pathCount": 0,
                    "dispositionCounts": {},
                    "groupCounts": {},
                    "unclassifiedPathCount": 0,
                    "otherWorkNotInReleasePathCount": 0,
                },
                "items": [],
            }
            (root / "release" / "release-candidate-scope.json").write_text(
                json.dumps(scope), encoding="utf-8"
            )
            (root / "new.txt").write_text("new\n", encoding="utf-8")
            subprocess.run(["git", "add", "new.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "new"], cwd=root, check=True)

            errors = validate_release_candidate_scope(root)

        self.assertTrue(any("misses base-to-HEAD paths: new.txt" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
