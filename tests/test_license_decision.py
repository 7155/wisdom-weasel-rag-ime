from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LicenseDecisionTests(unittest.TestCase):
    def test_project_license_and_metadata_are_gpl_v3_only(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertRegex(readme, r"Copyright (?:\(C\)|©) 2026 7155")
        self.assertIn("[GPL-3.0-only](LICENSE)", readme)
        self.assertIn('license = "GPL-3.0-only"', pyproject)

    def test_notices_name_every_code_or_design_boundary(self) -> None:
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        for project in (
            "Squirrel",
            "librime",
            "MiniMind",
            "MLX",
            "Ollama",
            "llama.cpp",
            "Wisdom-Weasel",
            "VCPToolBox",
            "OpenLess",
            "LazyTyper",
            "Volcengine",
            "Notion",
        ):
            self.assertIn(project, notices)
        self.assertIn("No source file is intentionally", notices)
        self.assertIn("custom checkpoint and training corpus", notices)


if __name__ == "__main__":
    unittest.main()
