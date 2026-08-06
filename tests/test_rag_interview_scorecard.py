from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_rag_interview_scorecard import build_scorecard


def _write_report(path: Path, value: dict[str, object]) -> None:
    unsigned = dict(value)
    unsigned.pop("reportSha256", None)
    unsigned["reportSha256"] = hashlib.sha256(
        json.dumps(
            {key: item for key, item in unsigned.items() if key != "reportSha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(unsigned) + "\n", encoding="utf-8")


def _retrieval_report(schema: str, baseline: float, tuned: float) -> dict[str, object]:
    def section(value: float) -> dict[str, object]:
        return {
            "metrics": {
                "queryCount": 2,
                "metrics": {
                    "mrr": value,
                    "recallAtK": {"1": value, "10": value},
                    "ndcgAtK": {"10": value},
                },
            }
        }

    return {
        "schemaVersion": schema,
        "status": "completed",
        "localOnly": True,
        "uploaded": False,
        "hardGates": {"split": True, "cleanup": True},
        "heldOut": {"productionLexicalFloor": section(baseline), "tuned": section(tuned)},
    }


class RagInterviewScorecardTests(unittest.TestCase):
    def test_namespaces_have_explicit_deltas_and_failed_agent_stays_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            knowledge = root_path / "knowledge.json"
            memory = root_path / "memory.json"
            agent = root_path / "agent.json"
            _write_report(knowledge, _retrieval_report("rag-ime.rag-retrieval-run.v2", 0.2, 0.8))
            memory_value = _retrieval_report("rag-ime.rag-retrieval-run.v2", 0.5, 0.6)
            for section in memory_value["heldOut"].values():
                section["perSlice"] = {
                    "temporal-reasoning": {
                        "queryCount": 1,
                        "mrr": 0.4 if section is memory_value["heldOut"]["productionLexicalFloor"] else 0.7,
                        "recallAtK": {"1": 0.2 if section is memory_value["heldOut"]["productionLexicalFloor"] else 0.5},
                        "ndcgAtK": {"10": 0.3 if section is memory_value["heldOut"]["productionLexicalFloor"] else 0.6},
                    },
                    "knowledge-update": {
                        "queryCount": 1,
                        "mrr": 0.5,
                        "recallAtK": {"1": 0.5},
                        "ndcgAtK": {"10": 0.5},
                    },
                }
            _write_report(memory, memory_value)
            _write_report(
                agent,
                {
                    "schemaVersion": "rag-ime.rag-agent-ablation-run.v1",
                    "passed": False,
                    "formalAcceptanceEligible": False,
                    "localOnly": True,
                    "uploaded": False,
                    "cleanupPassed": True,
                    "failure": "provider_transient_before_tool",
                },
            )
            scorecard = build_scorecard(
                knowledge_report=knowledge,
                memory_report=memory,
                agent_report=agent,
            )

        self.assertEqual(0.2, scorecard["knowledge"]["metrics"]["mrr"]["baseline"])
        self.assertEqual(0.8, scorecard["knowledge"]["metrics"]["mrr"]["optimized"])
        self.assertEqual({}, scorecard["knowledge"]["configs"]["baseline"])
        self.assertAlmostEqual(0.6, scorecard["knowledge"]["metrics"]["mrr"]["absoluteDelta"])
        self.assertAlmostEqual(3.0, scorecard["knowledge"]["metrics"]["mrr"]["relativeDelta"])
        self.assertTrue(scorecard["knowledge"]["eligible"])
        self.assertTrue(scorecard["memory"]["eligible"])
        temporal = scorecard["memory"]["slices"]["temporalReasoning"]["metrics"]
        self.assertAlmostEqual(0.3, temporal["mrr"]["absoluteDelta"])
        self.assertAlmostEqual(0.3, temporal["recallAt1"]["absoluteDelta"])
        self.assertEqual("knowledge-update", scorecard["memory"]["slices"]["updateOrConflict"]["sourceSlice"])
        self.assertEqual("ineligible_development_or_failure", scorecard["agent"]["status"])
        self.assertFalse(scorecard["agent"]["eligible"])
        self.assertTrue(scorecard["safety"]["noCombinedHeadline"])
        self.assertTrue(scorecard["scorecardSha256"])

    def test_report_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            knowledge = root_path / "knowledge.json"
            memory = root_path / "memory.json"
            _write_report(knowledge, _retrieval_report("rag-ime.rag-retrieval-run.v1", 0.2, 0.8))
            _write_report(memory, _retrieval_report("rag-ime.rag-retrieval-run.v1", 0.5, 0.6))
            knowledge.write_text(knowledge.read_text(encoding="utf-8").replace("0.8", "0.81"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash is invalid"):
                build_scorecard(knowledge_report=knowledge, memory_report=memory)
