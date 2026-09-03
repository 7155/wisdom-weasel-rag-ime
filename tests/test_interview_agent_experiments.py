from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.check_interview_agent_experiments import (
    validate_agent_experiments,
    validate_business_project_keep_paths,
    validate_controlled_model_cost_receipts,
)


def _valid_experiment() -> dict[str, object]:
    return {
        "id": "enterpriseops.execution-contract.v1",
        "title": "EnterpriseOps execution contract repair",
        "vertical": "enterprise-customer-support",
        "status": "kept",
        "claimStatus": "supporting",
        "effectStatus": "improved",
        "candidateType": "single_factor",
        "businessProblem": "Execute governed customer-support mutations safely.",
        "whyAgent": "The task requires cross-entity lookup, ordered mutations and verification.",
        "star": {
            "situation": "Enterprise customer-support mutations crossed multiple entities and failure boundaries.",
            "task": "Build a reproducible, governed Agent execution and evaluation path.",
            "action": "Used Trace evidence to repair Tool transport, authority and cleanup contracts.",
            "result": "Verifier execution advanced from 3/31 to 26/31 with 47 successful business Tool calls.",
        },
        "dataset": {
            "id": "enterpriseops-csm-validation-v2",
            "split": "validation",
            "caseCount": 3,
            "unit": "end-to-end tasks",
            "manifestSha256": "a" * 64,
            "heldOutConsumed": False,
        },
        "scoringContract": {
            "primaryMetric": "verifier_pass_rate",
            "hardGates": ["terminal completion", "database cleanup"],
            "evaluatorAuthority": "host_private_deterministic",
            "goldHiddenFromAgent": True,
        },
        "optimizationContract": {
            "objective": "Maximize verifier pass rate without weakening hard gates.",
            "candidateSearchSpace": [
                {"axis": "tool", "candidatesEvaluated": 2, "values": ["spool", "loopback_gateway"]}
            ],
            "frozenVariables": ["task manifest", "database seed", "host-private verifiers"],
            "selectionRule": "Keep only a strict quality improvement with all hard gates passing.",
            "stopRule": "Stop when the candidate ties quality with higher cost or regresses a protected metric.",
            "heldOutRule": "Consume Held-out once only after a Validation winner is frozen.",
        },
        "bestKnown": {
            "configId": "execution-chain-v1",
            "configSha256": "b" * 64,
            "decision": "keep",
        },
        "metricFamilies": [
            {"family": "outcome_quality", "status": "measured", "metrics": ["task success", "verifier pass rate"], "reason": "Host-private verifiers exist."},
            {"family": "evidence_grounding", "status": "open_gap", "metrics": [], "reason": "No answer citation task in this vertical."},
            {"family": "runtime_reliability", "status": "measured", "metrics": ["Tool success"], "reason": "Runtime receipts exist."},
            {"family": "efficiency_cost", "status": "measured", "metrics": ["Tool calls", "latency"], "reason": "Run totals exist."},
            {"family": "safety_recovery", "status": "measured", "metrics": ["database cleanup"], "reason": "Cleanup receipts exist."},
        ],
        "factors": [
            {
                "name": "tool",
                "before": "file spool",
                "after": "capability-token loopback gateway",
                "reason": "The Tool transport failed before business execution.",
            }
        ],
        "frozenControls": [
            {
                "name": "validation_contract",
                "value": "same three tasks and 31 verifiers",
                "reason": "Keep the before/after denominator comparable.",
            }
        ],
        "createdOrModifiedAssets": [
            {"kind": "tool", "ref": "rag_ime/cloudops_benchmark_agent.py", "change": "Added a governed gateway contract."}
        ],
        "baseline": {
            "runId": "baseline-v1",
            "outputExamples": [
                {"caseId": "case-01", "input": "request", "output": "failed before tools"}
            ],
            "metrics": {"verifierPassed": 3, "verifierTotal": 31},
            "evidenceRefs": ["eval/interview-metrics/runs/baseline.json"],
        },
        "recommendations": [
            {
                "id": "rec-tool-transport",
                "targetLayer": "tool",
                "observation": "Business Tool fetch failed before execution.",
                "hypothesis": "The file spool did not intercept the runtime fetch path.",
                "evidenceRefs": ["eval/interview-metrics/runs/baseline.json"],
                "proposedChange": "Use a capability-token loopback gateway.",
                "attribution": {
                    "detectedBy": "trace_agent",
                    "proposedBy": "trace_agent",
                    "authorizedBy": "user",
                    "implementedBy": "ordinary_agent",
                    "verifiedBy": "eval_agent",
                },
                "status": "implemented",
            }
        ],
        "layerAssessments": [
            {"layer": "system_prompt", "status": "considered_no_change", "reason": "No prompt change."},
            {"layer": "tool", "status": "changed", "reason": "Transport was repaired."},
            {"layer": "workflow", "status": "considered_no_change", "reason": "Workflow stayed frozen."},
            {"layer": "skill", "status": "not_applicable", "reason": "No task Skill participated."},
        ],
        "candidate": {
            "runId": "candidate-v1",
            "outputExamples": [
                {"caseId": "case-01", "input": "request", "output": "completed with receipts"}
            ],
            "metrics": {"verifierPassed": 26, "verifierTotal": 31},
            "evidenceRefs": ["eval/interview-metrics/runs/candidate.json"],
        },
        "comparison": {
            "metricDeltas": [
                {"metric": "verifier_pass_rate", "before": 0.0968, "after": 0.8387, "delta": 0.7419}
            ],
            "outputComparisons": [
                {"caseId": "case-01", "before": "failed before tools", "after": "completed with receipts"}
            ],
            "decision": "keep",
            "decisionReason": "The same frozen checks advanced without weakening the evaluator.",
        },
        "claim": {
            "resumeBullet": "Repaired the execution contract and advanced deterministic verification.",
            "allowed": "Validation execution-chain improvement.",
            "forbidden": "Production or held-out success.",
        },
        "openGaps": ["held-out remains sealed"],
    }


class InterviewAgentExperimentContractTests(unittest.TestCase):
    def test_repository_matrix_preserves_21_rows_and_adds_retry3_repair(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            "enterpriseops-csm.execution-chain.v1": ("kept", "keep", ("execution_policy", "tool", "workflow")),
            "enterpriseops-csm.state-contract-suite-v2": ("rejected", "reject", ("prompt", "workflow", "tool")),
            "enterprise-rag.retrieval-selection.v1": ("diagnostic", "diagnostic_only", ("memory_rag", "context", "guardrail")),
            "trace-agent.closed-loop-historical-replay.v1": ("open_gap", "not_run", ("skill", "workflow", "human_loop")),
            "cloudops.agent-validation-and-falsification.v1": ("rejected", "reject", ("tool", "workflow", "guardrail")),
            "cloudops.agent-validation-luna-max-timeout.v1": ("rejected", "reject", ("model",)),
            "memory.personal-shadow-evaluation.v1": ("diagnostic", "diagnostic_only", ("memory_rag", "context", "guardrail")),
            "memory.maintenance-luna-shadow-v5.v1": ("kept", "keep", ("memory_rag", "workflow")),
            "agent-lab.model-cost.luna-max-validation.v1": ("rejected", "reject", ("model",)),
            "enterprise-rag.tag-graph-readiness.v1": ("open_gap", "not_run", ("memory_rag",)),
            "enterprise-rag.answer-luna-baseline.v20": ("rejected", "reject", ("model",)),
            "enterprise-rag.answer-luna-skill.v20": ("rejected", "reject", ("model",)),
            "enterprise-rag.answer-luna-tuned.v20": ("rejected", "reject", ("model",)),
            "enterprise-rag.answer-luna-agentic.v20": ("rejected", "reject", ("model",)),
            "cloudops.validation-baseline.v1": ("kept", "keep", ("tool",)),
            "cloudops.evidence-search.v2": ("rejected", "reject", ("workflow",)),
            "cloudops.observation-id.v4": ("rejected", "reject", ("tool",)),
            "memory.maintenance-observed-failure.v0": ("diagnostic", "reject", ("workflow",)),
            "memory.maintenance-shadow-v1": ("rejected", "reject", ("workflow",)),
            "memory.maintenance-shadow-v3": ("rejected", "reject", ("workflow",)),
            "memory.maintenance-shadow-v4": ("rejected", "reject", ("workflow",)),
            "cloudops.runtime-selection-repair-retry3.v1": ("rejected", "reject", ("workflow",)),
        }
        by_id = {item["id"]: item for item in payload["experiments"]}

        self.assertEqual(set(by_id), set(expected))
        for experiment_id, (status, decision, factors) in expected.items():
            experiment = by_id[experiment_id]
            self.assertEqual(experiment["status"], status, experiment_id)
            self.assertEqual(experiment["comparison"]["decision"], decision, experiment_id)
            self.assertEqual(
                tuple(item["name"] for item in experiment["factors"]),
                factors,
                experiment_id,
            )

    def test_repository_experiment_ledger_satisfies_required_interview_fields(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(validate_agent_experiments(payload, repo_root=root), [])
        self.assertEqual(validate_business_project_keep_paths(payload), [])

        self.assertEqual(
            validate_controlled_model_cost_receipts(payload, repo_root=root),
            [],
        )

    def test_model_cost_receipts_reject_thinking_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "agent-lab.model-cost.luna-max-validation.v1"
        )
        experiment["baseline"]["runId"] = (
            "enterpriseops-csm-state-contract-validation-20260901-v2"
        )
        experiment["baseline"]["evidenceRefs"] = [
            "eval/interview-metrics/runs/"
            "enterpriseops-csm-state-contract-validation-20260901-v2.v1.json",
            "eval/interview-metrics/runs/"
            "agent-lab-cost-sol-state-contract-20260901.v1.json",
        ]

        errors = validate_controlled_model_cost_receipts(
            payload, repo_root=root
        )

        self.assertIn(
            "EnterpriseOps model-cost: baseline and candidate thinking must match",
            errors,
        )

    def test_state_contract_separates_shared_contract_repairs_from_candidate_attribution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "enterpriseops-csm.state-contract-suite-v2"
        )
        factors = {item["name"]: item for item in experiment["factors"]}
        controls = {item["name"]: item for item in experiment["frozenControls"]}

        self.assertIn("不能计入 candidate 收益", factors["prompt"]["reason"])
        self.assertIn("公平性前置修复", factors["tool"]["reason"])
        self.assertIn("不写入任务答案", factors["workflow"]["reason"])
        self.assertIn("同一 overlay hash", controls["evaluator"]["reason"])
        self.assertEqual("reject", experiment["comparison"]["decision"])

    def test_reject_rows_cannot_substitute_for_four_business_keep_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        rag_winner = next(
            item for item in payload["experiments"]
            if item["id"] == "enterprise-rag.retrieval-selection.v1"
        )
        rag_winner["status"] = "rejected"
        rag_winner["comparison"]["decision"] = "reject"

        errors = validate_business_project_keep_paths(payload)

        self.assertIn(
            "RAG: enterprise-rag.retrieval-selection.v1 must remain the non-rejected Validation retrieval winner",
            errors,
        )

    def test_single_factor_requires_one_factor_and_matching_search_axis(self) -> None:
        experiment = _valid_experiment()
        experiment["factors"].append({
            "name": "workflow",
            "before": "best effort",
            "after": "fail closed",
            "reason": "second factor must be a separate candidate",
        })
        experiment["optimizationContract"]["candidateSearchSpace"][0]["axis"] = "workflow"

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: single_factor experiments must contain exactly one factor",
            errors,
        )

        mismatched_axis = _valid_experiment()
        mismatched_axis["optimizationContract"]["candidateSearchSpace"][0]["axis"] = "workflow"
        axis_errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [mismatched_axis],
            }
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1: single_factor search axis must match factor tool",
            axis_errors,
        )

    def test_cloudops_luna_failure_receipt_preserves_runtime_only_boundary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "cloudops.agent-validation-luna-max-timeout.v1"
        )

        self.assertEqual(experiment["candidate"]["runId"], "cloudops--cloudops-luna-max-baseline-validation-20260902")
        self.assertEqual(experiment["candidate"]["metrics"]["transcriptToolCalls"], 278)
        self.assertEqual(experiment["candidate"]["metrics"]["failedTranscriptToolCalls"], 14)
        self.assertEqual(experiment["candidate"]["metrics"]["inputTokens"], 916112)
        self.assertEqual(experiment["candidate"]["metrics"]["outputTokens"], 57057)
        self.assertEqual(experiment["candidate"]["metrics"]["cacheReadTokens"], 18809344)
        self.assertEqual(experiment["candidate"]["metrics"]["latencyMs"], 1718516)
        self.assertEqual(experiment["candidate"]["metrics"]["thirdBatchTimeout"], 1)
        self.assertEqual(experiment["candidate"]["metrics"]["abortTimeout"], 1)
        self.assertEqual(experiment["candidate"]["metrics"]["hostFormalCaJraAvailable"], 0)
        self.assertEqual(experiment["effectStatus"], "not_run")
        self.assertFalse(experiment["dataset"]["heldOutConsumed"])
        self.assertEqual(experiment["comparison"]["decision"], "reject")
        self.assertEqual(experiment["factors"], [
            {
                "name": "model",
                "before": "gpt-5.6-sol / max",
                "after": "gpt-5.6-luna / max",
                "reason": "只替换模型；Prompt、Skill、Tool、Workflow 和 scorer 保持冻结。",
            }
        ])

    def test_requires_all_four_change_layers_and_owner_attribution(self) -> None:
        experiment = _valid_experiment()
        experiment["layerAssessments"] = experiment["layerAssessments"][:3]
        recommendation = experiment["recommendations"][0]
        recommendation["attribution"].pop("implementedBy")

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: layerAssessments must cover system_prompt, tool, workflow and skill exactly once",
            errors,
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1/rec-tool-transport: attribution.implementedBy is required",
            errors,
        )

    def test_requires_star_story_and_truthful_headline_boundaries(self) -> None:
        experiment = _valid_experiment()
        experiment["star"].pop("result")
        experiment["claim"].pop("forbidden")

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "narrativePolicy": {
                    "headline": "Lead with the strongest supported result.",
                    "deepDive": "Retain baseline, denominator, rejected runs and limitations.",
                    "noFabrication": "Never invent, relabel or leak gold to improve a score.",
                },
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: star.result is required",
            errors,
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1: claim.forbidden is required",
            errors,
        )

    def test_kept_or_rejected_experiment_requires_before_after_outputs_and_metrics(self) -> None:
        experiment = _valid_experiment()
        experiment["baseline"]["outputExamples"] = []
        experiment["candidate"]["metrics"] = {}
        experiment["comparison"]["outputComparisons"] = []

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: baseline.outputExamples must be non-empty",
            errors,
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1: candidate.metrics must be non-empty",
            errors,
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1: comparison.outputComparisons must be non-empty",
            errors,
        )

    def test_held_out_requires_one_shot_receipt(self) -> None:
        experiment = _valid_experiment()
        experiment["dataset"]["heldOutConsumed"] = True

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: consumed held-out requires dataset.oneShotReceiptRef",
            errors,
        )

    def test_requires_search_space_and_all_five_metric_families(self) -> None:
        experiment = _valid_experiment()
        experiment["optimizationContract"]["candidateSearchSpace"] = []
        experiment["metricFamilies"] = experiment["metricFamilies"][:4]

        errors = validate_agent_experiments(
            {
                "schemaVersion": "paw.interview-agent-experiment-ledger.v1",
                "generatedAt": "2026-09-01",
                "experiments": [experiment],
            }
        )

        self.assertIn(
            "enterpriseops.execution-contract.v1: optimizationContract.candidateSearchSpace must be non-empty",
            errors,
        )
        self.assertIn(
            "enterpriseops.execution-contract.v1: metricFamilies must cover outcome_quality, evidence_grounding, runtime_reliability, efficiency_cost and safety_recovery exactly once",
            errors,
        )


if __name__ == "__main__":
    unittest.main()
