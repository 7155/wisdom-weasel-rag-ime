from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_prompt_plans import _model_visible_projection_content
from rag_ime.agent_room_skills import RoomSkillPolicy
from rag_ime.room_effect_eval import evaluate_room_task_effects, render_room_task_effect_report


ROOT = Path(__file__).resolve().parents[1]


class RoomTaskEffectEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy_path = ROOT / "integrations/pi/room-skill-policy.json"
        self.skills_root = ROOT / "integrations/pi/skills"
        self.fixtures = ROOT / "eval/room-v2/task-effect-fixtures.v1.json"

    def test_task_fixtures_pass_separate_precision_recall_and_chain_metrics(self) -> None:
        result = evaluate_room_task_effects(
            self.fixtures, policy_path=self.policy_path, skills_root=self.skills_root
        )
        self.assertTrue(result["passed"], json.dumps(result, ensure_ascii=False, indent=2))
        metrics = result["metrics"]
        self.assertEqual(metrics["skillPrecision"], 1.0)
        self.assertEqual(metrics["skillRecall"], 1.0)
        self.assertEqual(metrics["toolPrecision"], 1.0)
        self.assertEqual(metrics["toolRecall"], 1.0)
        self.assertEqual(metrics["promptErrorCount"], 0)
        self.assertEqual(metrics["chainBreakCount"], 0)
        self.assertLess(metrics["progressiveDisclosureRatio"], 0.4)
        self.assertLess(metrics["toolProgressiveDisclosureRatio"], 1.0)

    def test_skill_catalog_has_no_body_and_load_is_exact(self) -> None:
        policy = RoomSkillPolicy(self.policy_path, self.skills_root)
        catalog = policy.catalog()
        expected_keys = {"name", "when", "notFor", "input", "output", "does"}
        self.assertEqual(len(catalog), 10)
        self.assertTrue(all(set(item) == expected_keys for item in catalog))
        loaded = policy.load_exact("room-structured-handoff")
        self.assertEqual(set(loaded), expected_keys | {"body", "contentRevision"})
        self.assertIn("## Output Contract", loaded["body"])
        self.assertNotIn("room-delivery-closure", loaded["body"])
        with self.assertRaises(ValueError):
            policy.load_exact("structured-handoff")
        with self.assertRaises(ValueError):
            policy.load_exact("../room-structured-handoff")

    def test_room_model_context_strips_retrieval_internals_but_keeps_audit_input(self) -> None:
        audit_content = json.dumps(
            {
                "taskId": "task:secret",
                "objective": "修复取消传播",
                "valid": True,
                "relevance": 0.97,
                "scoreBreakdown": {"vector": 0.8},
                "internalId": "row:4",
                "contentHash": "sha256:secret",
                "debugReason": "vector lane",
                "sources": [
                    {"title": "取消设计", "path": "docs/cancel.md", "sourceId": "chunk:2", "rank": 1}
                ],
            },
            ensure_ascii=False,
        )
        visible = _model_visible_projection_content(
            {"entryKind": "knowledge_receipt", "content": audit_content}
        )
        for forbidden in (
            "relevance", "score", "rank", "internalId", "Hash", "debugReason",
            "receipt", "task:secret", "chunk:2",
        ):
            self.assertNotIn(forbidden.casefold(), visible.casefold())
        self.assertIn("修复取消传播", visible)
        self.assertIn('"valid":true', visible)
        self.assertIn("取消设计", visible)
        self.assertIn("docs/cancel.md", visible)
        self.assertIn("scoreBreakdown", audit_content)

    def test_report_is_deterministic_and_contains_explicit_limitations(self) -> None:
        result = evaluate_room_task_effects(
            self.fixtures, policy_path=self.policy_path, skills_root=self.skills_root
        )
        first = render_room_task_effect_report(result)
        second = render_room_task_effect_report(result)
        self.assertEqual(first, second)
        self.assertIn("real configured Provider canary", first)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_text(first, encoding="utf-8")
            self.assertEqual(path.read_text(encoding="utf-8"), first)


if __name__ == "__main__":
    unittest.main()
