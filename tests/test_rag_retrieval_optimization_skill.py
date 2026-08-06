from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

from scripts.build_managed_pi_runtime_v2 import (
    SKILL_ROUTING_CARDS,
    _product_skill_dirs,
    _validated_skill_routing_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "integrations" / "pi" / "skills"
SKILL_NAME = "rag-retrieval-optimization"


class RagRetrievalOptimizationSkillTests(unittest.TestCase):
    def test_project_skill_is_standard_bundled_and_routable(self) -> None:
        skill_dir = SKILLS_ROOT / SKILL_NAME
        skill_file = skill_dir / "SKILL.md"
        self.assertIn(
            SKILL_NAME,
            {path.name for path in _product_skill_dirs(SKILLS_ROOT)},
        )

        content = skill_file.read_text(encoding="utf-8")
        _empty, raw_frontmatter, body = content.split("---", 2)
        frontmatter = yaml.safe_load(raw_frontmatter)
        self.assertEqual({"name", "description"}, set(frontmatter))
        self.assertEqual(SKILL_NAME, frontmatter["name"])
        self.assertIn("RAG", frontmatter["description"])
        self.assertIn("knowledge base", frontmatter["description"])
        self.assertIn("parsing", frontmatter["description"])

        for marker in (
            "## Optimization Workflow",
            "## Optimization Loop",
            "## Benchmark Sandbox Optimization Workflow",
            "evaluate_validation",
            "qrels",
            "held-out scoring always stays outside",
            "Memory and Knowledge",
            "parser/chunk profile",
            "embedding fingerprint",
            "Agentic retrieval",
            "claim-to-source evidence ledger",
            "every requested sub-item",
            "preview",
            "approval",
            "## Validation Boundary",
            "## Output Contract",
            "## Self-Check",
        ):
            self.assertIn(marker, body)

        evaluation_reference = (
            skill_dir / "references" / "evaluation-contract.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## Layer diagnosis", evaluation_reference)
        self.assertIn("parametric-knowledge or lucky-guess", evaluation_reference)

        parameter_reference = (
            skill_dir / "references" / "parameter-search.md"
        ).read_text(encoding="utf-8")
        self.assertIn("immutable index generation", parameter_reference)
        self.assertIn("## Agentic route search", parameter_reference)
        self.assertIn("## Agent-callable validation search", parameter_reference)
        self.assertIn("qrelsVisibleToAgent=false", parameter_reference)
        self.assertIn("scorer-only", parameter_reference)

        flow_reference = (
            skill_dir / "references" / "rag-flow-optimization.md"
        ).read_text(encoding="utf-8")
        self.assertIn("## Chunking and context representation", flow_reference)
        self.assertIn("## Retrieval stack", flow_reference)
        self.assertIn("## Agentic and graph retrieval", flow_reference)
        self.assertIn("## Failure map", flow_reference)
        self.assertIn("external telemetry/uploads", flow_reference)

        community_reference = (
            skill_dir / "references" / "community-patterns.md"
        ).read_text(encoding="utf-8")
        self.assertIn("c765d90455fe52a864cfe8e4bd89d26d6862bb01", community_reference)
        self.assertIn("Skill activation", community_reference)
        self.assertIn("in-document Find", community_reference)
        self.assertIn("personalized propagation", community_reference)
        self.assertIn("binary answer judge", community_reference)

        agent_metadata = yaml.safe_load(
            (skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertIn(
            "$rag-retrieval-optimization",
            agent_metadata["interface"]["default_prompt"],
        )

        catalog = _validated_skill_routing_catalog(SKILL_ROUTING_CARDS, SKILLS_ROOT)
        card = next(
            item for item in catalog["cards"] if item["name"] == SKILL_NAME
        )
        self.assertIn("RAG", card["does"])
        self.assertIn("Knowledge", card["does"])
        self.assertTrue(card["when"])
        self.assertTrue(card["notFor"])
        compact_card = json.dumps(
            {
                key: card[key]
                for key in ("name", "when", "does", "notFor")
                if key in card
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.assertLessEqual(
            len(compact_card),
            200,
            "routing card must remain compatible with the installed managed Pi runtime",
        )


if __name__ == "__main__":
    unittest.main()
