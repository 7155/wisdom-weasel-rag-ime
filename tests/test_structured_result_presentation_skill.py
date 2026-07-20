from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "integrations/pi/skills/structured-result-presentation/SKILL.md"
FIXTURES = ROOT / "eval/room-v2/structured-result-presentation-fixtures.v1.json"


class StructuredResultPresentationSkillTests(unittest.TestCase):
    def test_native_skill_has_compact_routing_card_and_on_demand_body(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        _empty, raw, body = text.split("---", 2)
        frontmatter = yaml.safe_load(raw)
        routing = {
            "name": frontmatter["name"],
            "when": frontmatter["when"],
            "does": frontmatter["does"],
            "notFor": frontmatter["notFor"],
        }
        self.assertLessEqual(
            len(json.dumps(routing, ensure_ascii=False, separators=(",", ":"))), 500
        )
        self.assertNotIn("rag_ime_blocks", json.dumps(routing, ensure_ascii=False))
        self.assertIn("room_post", body)
        self.assertIn("agentBlocks", body)
        self.assertIn("```rag_ime_blocks", body)
        self.assertIn("Never stream a partial fence", body)
        self.assertIn("html_widget", body)

    def test_effect_fixtures_cover_positive_and_negative_trigger_boundaries(self) -> None:
        cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
        positives = {case["expectedType"] for case in cases if case["expectedUse"]}
        negatives = {case["id"] for case in cases if not case["expectedUse"]}
        self.assertEqual(positives, {"table", "checklist", "artifact"})
        self.assertEqual(negatives, {"short-answer", "private-reasoning", "html-widget"})


if __name__ == "__main__":
    unittest.main()
