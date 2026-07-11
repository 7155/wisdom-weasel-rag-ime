from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LicenseDecisionTests(unittest.TestCase):
    def test_decision_keeps_owner_approval_and_model_license_separate(self) -> None:
        decision = (ROOT / "docs/license-decision.md").read_text(encoding="utf-8")

        self.assertIn("Status: owner decision pending", decision)
        self.assertIn("GPL-3.0-only", decision)
        self.assertIn("split Apache-2.0 + GPL-3.0-only", decision)
        self.assertIn("model weights, and training data are three separate licensing decisions", decision)
        self.assertIn("copyright holder: <owner-approved legal name or entity>", decision)

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
