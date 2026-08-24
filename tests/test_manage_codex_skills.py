from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.manage_codex_skills import (
    install_codex_skills,
    skill_install_status,
    uninstall_codex_skills,
)


class ManageCodexSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="paw-codex-skills-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.codex_home = self.root / "codex"
        self.source.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _skill(self, root: Path, name: str, body: str = "Body\n") -> Path:
        skill = root / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n\n# {name}\n\n{body}",
            encoding="utf-8",
        )
        return skill

    def test_install_is_idempotent_and_owns_only_new_directories(self) -> None:
        self._skill(self.source, "existing")
        self._skill(self.source, "new-skill")
        self._skill(self.codex_home / "skills", "existing")

        installed = install_codex_skills(self.source, self.codex_home)
        repeated = install_codex_skills(self.source, self.codex_home)

        self.assertTrue(installed["ok"])
        self.assertEqual(installed["installed"], ["new-skill"])
        self.assertEqual(repeated["installed"], [])
        receipt = json.loads(
            (self.codex_home / "paw-managed-skills.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sorted(receipt["skills"]), ["new-skill"])
        self.assertEqual(
            skill_install_status(self.source, self.codex_home)["summary"],
            {"managed": 1, "present": 1},
        )

    def test_install_never_overwrites_a_same_name_local_skill(self) -> None:
        self._skill(self.source, "architecture", "PAW source\n")
        target = self._skill(
            self.codex_home / "skills", "architecture", "local custom\n"
        )

        result = install_codex_skills(self.source, self.codex_home)

        self.assertEqual(result["conflicts"], ["architecture"])
        self.assertIn("local custom", (target / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((self.codex_home / "paw-managed-skills.json").exists())

    def test_uninstall_removes_only_unchanged_receipt_owned_skills(self) -> None:
        self._skill(self.source, "owned")
        self._skill(self.source, "external")
        self._skill(self.codex_home / "skills", "external")
        install_codex_skills(self.source, self.codex_home)

        result = uninstall_codex_skills(self.codex_home)

        self.assertEqual(result["removed"], ["owned"])
        self.assertTrue((self.codex_home / "skills" / "external" / "SKILL.md").is_file())
        self.assertFalse((self.codex_home / "skills" / "owned").exists())
        self.assertFalse((self.codex_home / "paw-managed-skills.json").exists())

    def test_uninstall_preserves_locally_modified_managed_skill(self) -> None:
        self._skill(self.source, "owned")
        install_codex_skills(self.source, self.codex_home)
        target = self.codex_home / "skills" / "owned" / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "local edit\n", encoding="utf-8")

        result = uninstall_codex_skills(self.codex_home)

        self.assertEqual(result["preservedModified"], ["owned"])
        self.assertTrue(target.is_file())
        self.assertTrue((self.codex_home / "paw-managed-skills.json").is_file())


if __name__ == "__main__":
    unittest.main()
