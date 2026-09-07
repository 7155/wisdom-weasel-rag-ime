from __future__ import annotations

import tempfile
import unittest
import hashlib
import json
import sqlite3
from pathlib import Path

from rag_ime.agent_lab.experiments import (
    AgentLabExperimentConflict,
    AgentLabExperimentStore,
)


def _experiment(*, revision: str = "a" * 64) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-lab-experiment.v1",
        "experimentId": "enterprise-rag.retrieval-selection.v1",
        "revisionSha256": revision,
        "title": "Enterprise RAG retrieval selection",
        "vertical": "enterprise-knowledge-retrieval",
        "evaluationKind": "rag_retrieval",
        "status": "diagnostic",
        "claimStatus": "diagnostic",
        "projectionState": "current",
        "businessProblem": "企业问题同时包含精确标识、语义表达和跨来源完整性。",
        "whyAgent": "最终答案需要跨私有文档检索、证据约束和拒答。",
        "dataset": {
            "datasetId": "enterprise-rag-smoke-validation-v1",
            "split": "validation",
            "caseCount": 16,
            "unit": "frozen retrieval queries over 5,101 documents",
            "manifestSha256": "d" * 64,
            "heldOutConsumed": False,
        },
        "scoring": {
            "primaryMetric": "nDCG@10 with MRR and Recall@10 guardrails",
            "evaluatorAuthority": "host_private_qrels",
            "goldHiddenFromAgent": True,
            "hardGates": ["fixed corpus and split hashes"],
        },
        "factors": [
            {
                "name": "tool",
                "before": "词法检索与固定 Top-10",
                "after": "Hybrid + Qwen3 reranker",
                "reason": "恢复语义问题的召回和排序质量。",
            }
        ],
        "frozenControls": [
            {
                "name": "dataset",
                "value": "16 条 Validation query；manifest 固定。",
                "reason": "保证前后结果可比。",
            }
        ],
        "baseline": {
            "runId": "enterprise-rag-lexical-floor-validation",
            "metrics": {"mrr": 0.604167, "ndcgAt10": 0.612801},
            "evidenceRefs": ["eval/interview-metrics/runs/rag.v1.json"],
        },
        "candidate": {
            "runId": "enterprise-rag-hybrid-qwen3-validation",
            "metrics": {"mrr": 0.867188, "ndcgAt10": 0.887203},
            "evidenceRefs": ["eval/interview-metrics/runs/rag.v1.json"],
        },
        "comparison": {
            "decision": "diagnostic_only",
            "decisionReason": "Answer and citation gates remain open.",
            "metricDeltas": [
                {"metric": "ndcg_at_10", "before": 0.612801, "after": 0.887203, "delta": 0.274402}
            ],
        },
        "star": {
            "situation": "Lexical-only retrieval missed semantic evidence.",
            "task": "Choose one configuration on a frozen Validation split.",
            "action": "Compared 14 retrieval and reranking configurations.",
            "result": "Recall@10 and nDCG@10 improved on Validation.",
        },
        "claim": {
            "resumeBullet": "在冻结 Validation 上将 nDCG@10 从 0.6128 提升至 0.8872。",
            "allowed": "Validation-only retrieval selection.",
            "forbidden": "Held-out or production uplift.",
        },
        "openGaps": ["answer and citation Validation remains open"],
        "importedAtMs": 1000,
    }


class AgentLabExperimentStoreTests(unittest.TestCase):
    def test_persists_idempotently_and_lists_latest_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-") as tmp:
            store = AgentLabExperimentStore(Path(tmp) / "paw.sqlite")
            first = _experiment()
            newer = _experiment(revision="b" * 64)
            newer["importedAtMs"] = 2000
            newer["status"] = "kept"

            self.assertEqual(store.persist(first), first)
            self.assertEqual(store.persist(first), first)
            store.persist(newer)

            latest = store.list_latest()
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["revisionSha256"], "b" * 64)
            self.assertEqual(latest[0]["status"], "kept")

    def test_same_identity_and_revision_rejects_changed_payload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-") as tmp:
            store = AgentLabExperimentStore(Path(tmp) / "paw.sqlite")
            payload = _experiment()
            store.persist(payload)
            changed = _experiment()
            changed["title"] = "Changed after persistence"

            with self.assertRaises(AgentLabExperimentConflict):
                store.persist(changed)

    def test_same_timestamp_prefers_most_recently_imported_revision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-") as tmp:
            store = AgentLabExperimentStore(Path(tmp) / "paw.sqlite")
            first = _experiment(revision="a" * 64)
            second = _experiment(revision="0" * 64)
            store.persist(first)
            store.persist(second)

            self.assertEqual(store.list_latest()[0]["revisionSha256"], "0" * 64)

    def test_legacy_revision_gets_explicit_read_only_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-legacy-") as tmp:
            database = Path(tmp) / "paw.sqlite"
            store = AgentLabExperimentStore(database)
            store.initialize()
            legacy = _experiment()
            legacy.pop("factors")
            legacy.pop("frozenControls")
            raw = json.dumps(legacy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            with sqlite3.connect(database) as conn:
                conn.execute(
                    "INSERT INTO agent_lab_experiment_revisions(experiment_id, revision_sha256, imported_at_ms, payload_hash, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (legacy["experimentId"], legacy["revisionSha256"], 1, payload_hash, raw),
                )
            latest = store.list_latest()[0]
            self.assertEqual(latest["factors"][0]["name"], "workflow")
            self.assertEqual(latest["frozenControls"][0]["name"], "legacy_revision")
            self.assertEqual(latest["projectionState"], "current")


if __name__ == "__main__":
    unittest.main()
