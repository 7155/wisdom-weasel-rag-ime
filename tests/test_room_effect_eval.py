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

    def test_full_auto_room_fixture_freezes_sequence_and_skill_boundaries(self) -> None:
        document = json.loads(self.fixtures.read_text(encoding="utf-8"))
        contract = document["fullAutoRoomContract"]
        self.assertEqual(contract["authority"], "Personal Agent Workbench")
        self.assertEqual(contract["referenceOnly"], "Cat Cafe")
        self.assertEqual(
            contract["sequence"],
            [
                "room_state",
                "room_commit(wait, waitingFor=user)",
                "ordinary-user-message resume under the same Root",
                "progressively disclose/load room_define",
                "room_define",
                "room_state for final acceptance aliases",
                "room_commit(handoff)",
                "Facilitator decomposition and directed Worker Dispatches",
                "bounded implementation",
                "Facilitator-owned integration workspace",
                "optional distinct-reviewer handoff after integration",
                "Kernel settlement",
                "facilitator/reporter-only final public summary",
            ],
        )

        cases = {item["id"]: item for item in contract["cases"]}
        self.assertEqual(
            set(cases),
            {
                "intake-no-fanout",
                "wait-resume-same-root",
                "define-bind-and-fence",
                "workspace-and-review-boundary",
            },
        )
        boundary = cases["workspace-and-review-boundary"]
        self.assertIn(
            "Facilitator owns decomposition, assignment, reassignment, and integration",
            boundary["required"],
        )
        self.assertIn(
            "one Facilitator-owned integration workspace",
            boundary["required"],
        )
        self.assertIn(
            "review is optional and only after integration",
            boundary["required"],
        )
        self.assertIn(
            "integration evidence plus Kernel gates when review is not chosen",
            boundary["required"],
        )
        self.assertIn("review before integration", boundary["forbidden"])
        self.assertIn("assignment by free-text mention", boundary["forbidden"])
        self.assertTrue(all(item["required"] for item in cases.values()))
        self.assertTrue(all(item["forbidden"] for item in cases.values()))

        skill_text = {
            skill_id: " ".join(
                (self.skills_root / skill_id / "SKILL.md")
                .read_text(encoding="utf-8")
                .casefold()
                .split()
            )
            for skill_id in contract["skillExpectations"]
        }
        for skill_id, terms in contract["skillExpectations"].items():
            with self.subTest(skill=skill_id):
                for term in terms:
                    with self.subTest(term=term):
                        self.assertIn(term.casefold(), skill_text[skill_id])

        combined_skill_text = "\n".join(skill_text.values())
        for term in contract["prohibitionExpectations"]:
            with self.subTest(prohibition=term):
                self.assertIn(term.casefold(), combined_skill_text)

    def test_confirmed_requirements_can_route_directly_to_planning(self) -> None:
        document = json.loads(self.fixtures.read_text(encoding="utf-8"))
        case = next(
            item
            for item in document["cases"]
            if item["id"] == "confirmed-requirements-direct-plan"
        )
        self.assertEqual(case["stage"], "planning")
        self.assertEqual(case["expectedSkills"], ["implementation-planning"])
        self.assertEqual(case["forbiddenSkills"], ["alignment-and-decision"])

        policy = json.loads(self.policy_path.read_text(encoding="utf-8"))
        alignment = next(
            item
            for item in policy["skills"]
            if item["skillId"] == "alignment-and-decision"
        )
        self.assertEqual(
            alignment["stages"],
            ["requirements", "solution"],
        )
        self.assertEqual(
            alignment["nextCandidates"],
            ["implementation-planning"],
        )
        planning = next(
            item
            for item in policy["skills"]
            if item["skillId"] == "implementation-planning"
        )
        self.assertEqual(
            planning["nextCandidates"],
            ["implementation-execution"],
        )

    def test_skill_catalog_has_no_body_and_load_is_exact(self) -> None:
        policy = RoomSkillPolicy(self.policy_path, self.skills_root)
        catalog = policy.catalog()
        expected_keys = {"name", "when", "notFor", "input", "output", "does"}
        self.assertEqual(len(catalog), 9)
        self.assertTrue(all(set(item) == expected_keys for item in catalog))
        loaded = policy.load_exact("structured-handoff")
        self.assertEqual(set(loaded), expected_keys | {"body", "contentRevision"})
        self.assertIn("## Output Contract", loaded["body"])
        self.assertNotIn("room-delivery-closure", loaded["body"])
        legacy = policy.load_exact("room-structured-handoff")
        self.assertEqual(legacy["name"], "structured-handoff")
        self.assertNotIn("room-structured-handoff", {item["name"] for item in catalog})
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
