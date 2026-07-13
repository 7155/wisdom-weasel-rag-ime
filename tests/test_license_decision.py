from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LicenseDecisionTests(unittest.TestCase):
    def test_decision_records_selected_project_license_and_model_boundary(self) -> None:
        decision = (ROOT / "docs/license-decision.md").read_text(encoding="utf-8")

        self.assertIn("Status: `GPL-3.0-only` selected by the repository owner", decision)
        self.assertIn("GPL-3.0-only", decision)
        self.assertIn("A split policy is possible", decision)
        self.assertIn("Apache-2.0", decision)
        self.assertIn("model weights, and training data are three separate licensing decisions", decision)
        self.assertIn("copyright holder: 7155", decision)
        self.assertIn("copyright year: 2026", decision)

    def test_project_license_and_metadata_are_gpl_v3_only(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn("Copyright (C) 2026 7155", readme)
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
