from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from scripts.build_managed_pi_runtime_v2 import _product_skill_dirs


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "integrations" / "pi" / "skills"
SKILL_DIR = SKILLS_ROOT / "agent-eval-room-optimizer"


def _json_contract(path: Path, marker: str) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    match = re.search(
        rf"<!-- {re.escape(marker)} -->\s*```json\s*(\{{.*?\}})\s*```",
        content,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing {marker} JSON contract in {path}")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise AssertionError(f"{marker} must be a JSON object")
    return value


class AgentEvalRoomOptimizerSkillTests(unittest.TestCase):
    def test_skill_is_discoverable_and_keeps_authority_boundaries_explicit(self) -> None:
        skill_file = SKILL_DIR / "SKILL.md"
        self.assertIn(
            "agent-eval-room-optimizer",
            {path.name for path in _product_skill_dirs(SKILLS_ROOT)},
        )
        content = skill_file.read_text(encoding="utf-8")
        _empty, raw_frontmatter, body = content.split("---", 2)
        frontmatter = yaml.safe_load(raw_frontmatter)

        self.assertEqual({"name", "description"}, set(frontmatter))
        self.assertEqual("agent-eval-room-optimizer", frontmatter["name"])
        self.assertIn("Agent Lab", frontmatter["description"])
        self.assertIn("Room", frontmatter["description"])
        self.assertIn("evaluationKind", body)
        self.assertIn("compact run, case, and evidence references", body)
        self.assertIn("historical evidence", body)
        self.assertIn("same frozen Validation case-set", body)
        self.assertNotIn("new Validation split", body)
        self.assertIn("Host verifier", body)
        self.assertIn("explicit approval", body)
        self.assertIn("one terminal result", body)
        self.assertIn("references/evaluation-routes.md", body)
        self.assertIn("references/result-contract.md", body)
        for required in (
            "pending_data",
            "agent.eval-lab.runs",
            "trace_diagnostics.inspect",
            "scripts/score_agent_lab_optimal_path.py",
            "scripts/build_agent_lab_cost_receipt_from_runtime_db.py",
            "EnterpriseOps CSM",
            "Knowledge RAG",
            "Memory maintenance",
            "parentNodeId",
            "heldOutConsumed=false",
            "不替换 PAW/Pi 的全局",
            "info_not_found",
            "Agent 自述不算成功",
            "重复运行不得新增重复记忆",
            "rag-ime.agent-lab-dispatch.v1",
            "counterfactualProbes",
            "scope.target",
            "targetObject",
            "skill",
            "agent_observed",
            "maxCandidates",
            "maxEstimatedCostUsd",
            "no_improvement",
            "agent.room.abort",
        ):
            self.assertIn(required, body)

        metadata = yaml.safe_load(
            (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertIn(
            "$agent-eval-room-optimizer",
            metadata["interface"]["default_prompt"],
        )

    def test_route_contract_is_complete_and_never_requires_trace(self) -> None:
        contract = _json_contract(
            SKILL_DIR / "references" / "evaluation-routes.md",
            "AGENT_EVAL_ROOM_ROUTE_CONTRACT_V1",
        )
        routes = contract["routes"]
        self.assertIsInstance(routes, list)
        self.assertEqual(
            {
                "rag_retrieval",
                "answer_citation",
                "tool_runtime",
                "workflow",
                "memory",
                "model_cost",
            },
            {route["evaluationKind"] for route in routes},
        )
        for route in routes:
            self.assertEqual("optional", route["tracePolicy"])
            self.assertTrue(route["primaryOwner"])
            self.assertTrue(route["candidateBoundary"])

    def test_result_contract_records_before_after_attribution_and_safe_star(self) -> None:
        contract = _json_contract(
            SKILL_DIR / "references" / "result-contract.md",
            "AGENT_EVAL_ROOM_RESULT_CONTRACT_V1",
        )
        self.assertEqual(
            {
                "schemaVersion",
                "evaluationKind",
                "roomGoalRef",
                "before",
                "finding",
                "candidateChange",
                "after",
                "delta",
                "decision",
                "attribution",
                "facilitatorTerminal",
                "star",
                "boundaries",
            },
            set(contract),
        )
        self.assertEqual(
            {
                "detectedBy",
                "proposedBy",
                "authorizedBy",
                "implementedBy",
                "verifiedBy",
            },
            set(contract["attribution"]),
        )
        self.assertEqual("host_verifier", contract["after"]["passFailAuthority"])
        self.assertEqual(
            {"situation", "task", "action", "result", "proofBoundary", "resumeRef"},
            set(contract["star"]),
        )
        serialized = json.dumps(contract)
        self.assertNotIn("rawGold", serialized)
        self.assertNotIn("privateTranscript", serialized)


if __name__ == "__main__":
    unittest.main()
