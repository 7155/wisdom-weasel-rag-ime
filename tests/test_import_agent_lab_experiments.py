from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rag_ime.agent_lab_experiments import AgentLabExperimentStore
from scripts.import_agent_lab_experiments import (
    build_agent_experiment_ledger,
    import_experiments,
    read_public_experiments,
)


class ImportAgentLabExperimentsTests(unittest.TestCase):
    def test_repository_ledger_matches_current_receipt_recipes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger = root / "eval/interview-metrics/agent-experiments.v1.json"
        expected = build_agent_experiment_ledger(
            ledger_path=ledger,
            evidence_ledger_path=root / "eval/interview-metrics/evidence-ledger.v1.json",
            runs_dir=root / "eval/interview-metrics/runs",
            refresh_derived=True,
        )
        actual = json.loads(ledger.read_text(encoding="utf-8"))

        self.assertEqual(actual, expected)

    def test_refreshes_materialized_recipe_rows_without_touching_hand_authored_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        canonical_path = root / "eval/interview-metrics/agent-experiments.v1.json"
        evidence_ledger = root / "eval/interview-metrics/evidence-ledger.v1.json"
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        hand_authored_id = "enterpriseops-csm.execution-chain.v1"
        hand_authored = next(
            item for item in canonical["experiments"]
            if item["id"] == hand_authored_id
        )

        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-refresh-") as tmp:
            stale_path = Path(tmp) / "agent-experiments.v1.json"
            stale = json.loads(json.dumps(canonical))
            stale_row = next(
                item for item in stale["experiments"]
                if item["id"] == "enterprise-rag.answer-luna-skill.v20"
            )
            stale_row["factors"] = [{
                "name": "skill",
                "before": "stale before",
                "after": "stale after",
                "reason": "stale derived row",
            }]
            stale_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

            refreshed = build_agent_experiment_ledger(
                ledger_path=stale_path,
                evidence_ledger_path=evidence_ledger,
                runs_dir=evidence_ledger.parent / "runs",
                refresh_derived=True,
            )

        by_id = {item["id"]: item for item in refreshed["experiments"]}
        self.assertEqual(by_id[hand_authored_id], hand_authored)
        refreshed_rag = by_id["enterprise-rag.answer-luna-skill.v20"]
        self.assertEqual(
            refreshed_rag["factors"],
            [{
                "name": "model",
                "before": "GPT-5.6 Sol / max + 冻结 Citation Skill",
                "after": "GPT-5.6 Luna / max + 同一 Citation Skill",
                "reason": "该回执只替换模型；Prompt、Skill、Tool、Workflow、语料和评分合同全部冻结。",
            }],
        )
        self.assertFalse(
            any(
                layer["status"] == "changed"
                for layer in refreshed_rag["layerAssessments"]
            )
        )
        self.assertEqual(
            refreshed_rag["recommendations"][0]["targetLayer"],
            "workflow",
        )
        single_factor_control = next(
            control for control in refreshed_rag["frozenControls"]
            if control["name"] == "single_factor"
        )
        self.assertEqual(
            single_factor_control["value"],
            "只改变 Model；Prompt、Skill、Tool、Workflow、Context/Memory/RAG 和 evaluator 冻结",
        )

    def test_repository_ledger_contains_cloudops_and_cost_gate(self) -> None:
        ledger = Path(__file__).resolve().parents[1] / "eval/interview-metrics/agent-experiments.v1.json"
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-import-repo-") as tmp:
            receipt = import_experiments(
                ledger_path=ledger,
                target_db=Path(tmp) / "unused.sqlite",
                write=False,
                imported_at_ms=123,
            )
        self.assertEqual(receipt["experimentCount"], 35)
        self.assertIn("cloudops.agent-validation-and-falsification.v1", receipt["experimentIds"])
        self.assertIn("agent-lab.model-cost.luna-max-validation.v1", receipt["experimentIds"])
        self.assertIn("enterpriseops-csm.preloaded-tool-cost.v1", receipt["experimentIds"])
        self.assertIn("enterprise-rag.sol-max-budget3-r3.v1", receipt["experimentIds"])
        self.assertIn("cloudops.alert-first-sol-max.v1", receipt["experimentIds"])
        self.assertIn("memory.maintenance-concise-contract-sol-max.v1", receipt["experimentIds"])
        self.assertIn("enterpriseops-csm.luna-model-only-r5.v1", receipt["experimentIds"])
        self.assertIn("enterpriseops-csm.luna-prompt-adaptation-r7.v1", receipt["experimentIds"])
        self.assertIn("memory.maintenance-luna-model-only-r1.v1", receipt["experimentIds"])
        self.assertIn("memory.maintenance-pi-model-only-20260905-r3.v1", receipt["experimentIds"])
        self.assertIn("cloudops.alert-first-luna-model-only-r1.v1", receipt["experimentIds"])
        self.assertIn("cloudops.luna-owner-mechanism-prompt-r5.v1", receipt["experimentIds"])
        self.assertIn("enterprise-rag.sol-max-standard-r6.v1", receipt["experimentIds"])
        self.assertIn("enterprise-rag.luna-model-only-standard-r6.v1", receipt["experimentIds"])
        self.assertIn("enterprise-rag.luna-prompt-v4-standard-r6.v1", receipt["experimentIds"])

    def test_projects_preview_ablation_rows_from_evidence_and_run_receipts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger = root / "eval/interview-metrics/agent-experiments.v1.json"
        evidence_ledger = root / "eval/interview-metrics/evidence-ledger.v1.json"
        # Exercise the real receipt/evidence projection instead of merely
        # reading the already-materialized canonical rows.  The checked-in
        # ledger is the release artifact; this stripped copy models an older
        # checkout that still needs the importer to add the derived rows.
        canonical = json.loads(ledger.read_text(encoding="utf-8"))
        required_ids = {
            "enterprise-rag.tag-graph-readiness.v1",
            "enterprise-rag.answer-luna-baseline.v20",
            "enterprise-rag.answer-luna-skill.v20",
            "enterprise-rag.answer-luna-tuned.v20",
            "enterprise-rag.answer-luna-agentic.v20",
            "cloudops.validation-baseline.v1",
            "cloudops.evidence-search.v2",
            "cloudops.observation-id.v4",
            "memory.maintenance-observed-failure.v0",
            "memory.maintenance-shadow-v1",
            "memory.maintenance-shadow-v3",
            "memory.maintenance-shadow-v4",
            "cloudops.runtime-selection-repair-retry3.v1",
        }
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-derived-") as tmp:
            stripped = Path(tmp) / "agent-experiments.v1.json"
            canonical["experiments"] = [
                item for item in canonical["experiments"]
                if item.get("id") not in required_ids
            ]
            stripped.write_text(
                json.dumps(canonical, ensure_ascii=False), encoding="utf-8"
            )
            _, _, experiments = read_public_experiments(
                ledger_path=stripped,
                evidence_ledger_path=evidence_ledger,
                runs_dir=evidence_ledger.parent / "runs",
                imported_at_ms=123,
            )
        by_id = {str(item["experimentId"]): item for item in experiments}
        required = {
            "enterprise-rag.tag-graph-readiness.v1": ("open_gap", "not_run", 16),
            "enterprise-rag.answer-luna-baseline.v20": ("rejected", "reject", 4),
            "enterprise-rag.answer-luna-skill.v20": ("rejected", "reject", 4),
            "enterprise-rag.answer-luna-tuned.v20": ("rejected", "reject", 4),
            "enterprise-rag.answer-luna-agentic.v20": ("rejected", "reject", 4),
            "cloudops.validation-baseline.v1": ("kept", "keep", 12),
            "cloudops.evidence-search.v2": ("rejected", "reject", 12),
            "cloudops.observation-id.v4": ("rejected", "reject", 12),
            "memory.maintenance-observed-failure.v0": ("diagnostic", "reject", 1),
            "memory.maintenance-shadow-v1": ("rejected", "reject", 5),
            "memory.maintenance-shadow-v3": ("rejected", "reject", 5),
            "memory.maintenance-shadow-v4": ("rejected", "reject", 5),
            "cloudops.runtime-selection-repair-retry3.v1": ("rejected", "reject", 12),
        }
        self.assertEqual(len(by_id), 35)
        for experiment_id, (status, decision, case_count) in required.items():
            experiment = by_id[experiment_id]
            self.assertEqual(experiment["status"], status, experiment_id)
            self.assertEqual(experiment["comparison"]["decision"], decision, experiment_id)
            self.assertEqual(experiment["dataset"]["caseCount"], case_count, experiment_id)
            self.assertEqual(len(experiment["factors"]), 1, experiment_id)
            self.assertGreater(len(experiment["baseline"]["evidenceRefs"]), 0, experiment_id)
            self.assertGreater(len(experiment["candidate"]["evidenceRefs"]), 0, experiment_id)

        self.assertEqual(
            by_id["enterprise-rag.answer-luna-agentic.v20"]["candidate"]["metrics"]["tokensComplete"],
            0,
        )
        self.assertEqual(
            by_id["memory.maintenance-shadow-v4"]["candidate"]["metrics"]["vectorCoverage"],
            0,
        )
        self.assertFalse(
            any(item["dataset"]["heldOutConsumed"] for item in by_id.values() if item["experimentId"] in required)
        )
        runtime_repair = by_id["cloudops.runtime-selection-repair-retry3.v1"]
        self.assertEqual(runtime_repair["projectionState"], "history")
        self.assertEqual(
            runtime_repair["supersededBy"],
            "cloudops.validation-baseline.v1",
        )
        self.assertEqual(runtime_repair["factors"][0]["name"], "workflow")
        self.assertEqual(runtime_repair["baseline"]["metrics"]["promptEntered"], 0)
        self.assertEqual(runtime_repair["candidate"]["metrics"]["promptEntered"], 1)
        self.assertEqual(runtime_repair["candidate"]["metrics"]["providerRequestFailures"], 8)
        self.assertEqual(runtime_repair["candidate"]["metrics"]["toolCalls"], 0)
        self.assertEqual(runtime_repair["candidate"]["metrics"]["formalScoreProduced"], 0)
        self.assertEqual(runtime_repair["candidate"]["metrics"]["usageAvailable"], 0)
        self.assertNotIn("estimatedApiCostUsd", runtime_repair["candidate"]["metrics"])
        self.assertEqual(
            runtime_repair["candidate"]["evidenceRefs"][:3],
            [
                "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry1.v1.json",
                "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry2.v1.json",
                "eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry3.v1.json",
            ],
        )

    def test_binds_failed_run_cost_only_to_original_cloudops_timeout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        ledger = root / "eval/interview-metrics/agent-experiments.v1.json"
        refreshed = build_agent_experiment_ledger(
            ledger_path=ledger,
            evidence_ledger_path=root / "eval/interview-metrics/evidence-ledger.v1.json",
            runs_dir=root / "eval/interview-metrics/runs",
            refresh_derived=True,
        )
        by_id = {item["id"]: item for item in refreshed["experiments"]}
        cost_ref = "eval/interview-metrics/runs/agent-lab-cost-cloudops-luna-failed-run-20260902.v1.json"
        timeout = by_id["cloudops.agent-validation-luna-max-timeout.v1"]
        retry3 = by_id["cloudops.runtime-selection-repair-retry3.v1"]

        self.assertIn(cost_ref, timeout["candidate"]["evidenceRefs"])
        self.assertEqual(timeout["candidate"]["metrics"]["costReceiptAvailable"], 1)
        self.assertAlmostEqual(
            timeout["candidate"]["metrics"]["estimatedApiCostUsd"],
            0.62787768,
        )
        self.assertNotIn(cost_ref, retry3["candidate"]["evidenceRefs"])
        self.assertNotIn("estimatedApiCostUsd", retry3["candidate"]["metrics"])

    def test_cloudops_luna_projection_is_report_only_without_readable_transcripts(self) -> None:
        ledger = Path(__file__).resolve().parents[1] / "eval/interview-metrics/agent-experiments.v1.json"
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-import-luna-") as tmp:
            from scripts.import_agent_lab_experiments import read_public_experiments

            _, _, experiments = read_public_experiments(ledger_path=ledger, imported_at_ms=123)
        experiment = next(
            item for item in experiments
            if item["experimentId"] == "cloudops.agent-validation-luna-max-timeout.v1"
        )
        self.assertEqual(experiment["effectStatus"], "not_run")
        self.assertEqual(experiment["comparison"]["decision"], "拒绝候选，仅保留失败回执")
        candidate = experiment["candidate"]
        self.assertEqual(candidate["metrics"]["sessionCount"], 3)
        self.assertEqual(candidate["metrics"]["receiptCount"], 3)
        self.assertEqual(candidate["metrics"]["transcriptCount"], 0)
        self.assertLessEqual(len(candidate.get("outputExamples", [])), 1)
        self.assertEqual(experiment["projectionState"], "history")
        self.assertEqual(experiment["supersededBy"], "cloudops.validation-baseline.v1")

    def test_maps_public_ledger_without_private_output_examples(self) -> None:
        with tempfile.TemporaryDirectory(prefix="paw-agent-lab-import-") as tmp:
            root = Path(tmp)
            ledger = root / "ledger.json"
            database = root / "paw.sqlite"
            ledger.write_text(
                json.dumps(
                    {
                        "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                        "experiments": [
                            {
                                "id": "rag.demo.v1",
                                "title": "RAG demo",
                                "vertical": "knowledge",
                                "status": "diagnostic",
                                "claimStatus": "diagnostic",
                                "businessProblem": "Find evidence.",
                                "whyAgent": "Requires search and abstention.",
                                "star": {"situation": "S", "task": "T", "action": "A", "result": "R"},
                                "dataset": {"id": "d1", "split": "validation", "caseCount": 2, "unit": "queries", "manifestSha256": "d" * 64, "heldOutConsumed": False},
                                "scoringContract": {"primaryMetric": "MRR", "hardGates": ["frozen"], "evaluatorAuthority": "qrels", "goldHiddenFromAgent": True},
                                "factors": [{"name": "tool", "before": "Lexical", "after": "Hybrid", "reason": "语义问题需要补召回。"}],
                                "frozenControls": [{"name": "query_set", "value": "2 frozen queries", "reason": "保证可比。"}],
                                "baseline": {"runId": "b", "metrics": {"mrr": 0.5}, "evidenceRefs": ["safe/b.json"], "outputExamples": [{"private": "must not import"}]},
                                "candidate": {"runId": "c", "metrics": {"mrr": 0.75}, "evidenceRefs": ["safe/c.json"], "outputExamples": [{"private": "must not import"}]},
                                "comparison": {"decision": "keep", "decisionReason": "Better.", "metricDeltas": [{"metric": "mrr", "before": 0.5, "after": 0.75, "delta": 0.25}]},
                                "claim": {"resumeBullet": "Improved MRR.", "allowed": "Validation.", "forbidden": "Production."},
                                "openGaps": ["Held-out sealed"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            dry = import_experiments(ledger_path=ledger, target_db=database, write=False, imported_at_ms=123)
            self.assertEqual(dry["status"], "dry_run")
            self.assertFalse(database.exists())

            receipt = import_experiments(ledger_path=ledger, target_db=database, write=True, imported_at_ms=123)
            self.assertEqual(receipt["status"], "imported")
            experiment = AgentLabExperimentStore(database).list_latest()[0]
            self.assertEqual(experiment["evaluationKind"], "rag_retrieval")
            self.assertNotIn("outputExamples", str(experiment))
            self.assertNotIn("must not import", str(experiment))

    def test_customer_support_repair_is_routed_as_workflow_not_trace(self) -> None:
        from scripts.import_agent_lab_experiments import _evaluation_kind

        self.assertEqual(
            _evaluation_kind({
                "id": "enterpriseops-csm.execution-chain.v1",
                "title": "execution-chain repair",
                "vertical": "enterprise-customer-support",
            }),
            "workflow",
        )


if __name__ == "__main__":
    unittest.main()
