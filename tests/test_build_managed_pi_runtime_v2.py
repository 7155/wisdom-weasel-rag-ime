from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_managed_pi_runtime_v2 import ROOT, _runtime_host_banner


class ManagedPiRuntimeV2BuildTests(unittest.TestCase):
    def test_input_method_project_owns_all_managed_skills(self) -> None:
        skills_root = ROOT / "integrations" / "pi" / "skills"
        skill_names = sorted(item.name for item in skills_root.iterdir() if item.is_dir())

        self.assertEqual(skill_names, ["rag-ime-memory-curator", "rag-ime-plugin-creator"])
        for name in skill_names:
            content = (skills_root / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", content)
            self.assertIn("\nwhen:\n", content)
            self.assertIn("\ndoes: ", content)
            self.assertIn("\nnotFor:\n", content)

        routing_catalog = json.loads(
            (ROOT / "integrations" / "pi" / "skill-routing-cards.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            routing_catalog["schemaVersion"],
            "rag-ime.skill-routing-card-catalog.v1",
        )
        cards = routing_catalog["cards"]
        self.assertEqual(len(cards), 40)
        self.assertEqual(len({card["name"] for card in cards}), len(cards))
        for card in cards:
            self.assertTrue(card["when"])
            self.assertTrue(card["does"])
            compact = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
            self.assertLessEqual(len(compact), 200, card["name"])

    def test_runtime_banner_loads_all_product_skills_without_enabling_global_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-runtime-skills-") as temporary:
            root = Path(temporary)
            (root / "rag-ime-memory-curator").mkdir()
            (root / "rag-ime-plugin-creator").mkdir()

            banner = _runtime_host_banner(root)

        self.assertIn('"rag-ime-memory-curator"', banner)
        self.assertIn('"rag-ime-plugin-creator"', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_PATHS', banner)
        self.assertIn('process.env.RAG_IME_PI_SKILL_ROUTING_CARDS', banner)
        self.assertIn('skill-routing-cards.json', banner)
        self.assertIn('__join(__ragImeRuntimeDir, "skills", name)', banner)
        self.assertNotIn("--no-skills", banner)


if __name__ == "__main__":
    unittest.main()
