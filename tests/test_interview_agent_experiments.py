from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rag_ime.contracts.json_schema import validate_contract
from scripts.check_interview_agent_experiments import (
    validate_agent_experiments,
    validate_business_project_keep_paths,
    validate_controlled_model_cost_receipts,
    validate_retained_api_pricing_estimates,
)


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _seal_receipt(payload: dict[str, object], field: str) -> None:
    body = copy.deepcopy(payload)
    body.pop(field, None)
    payload[field] = _canonical_sha256(body)


def _retained_cost_fixture(repo_root: Path, target_root: Path) -> dict[str, object]:
    payload = json.loads(
        (repo_root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
            encoding="utf-8"
        )
    )
    retained_ids = {
        "enterpriseops-csm.luna-model-only-r5.v1",
        "enterpriseops-csm.luna-prompt-adaptation-r7.v1",
        "memory.maintenance-luna-model-only-r1.v1",
        "cloudops.alert-first-luna-model-only-r1.v1",
        "cloudops.luna-owner-mechanism-prompt-r5.v1",
    }
    payload["experiments"] = [
        copy.deepcopy(item)
        for item in payload["experiments"]
        if item["id"] in retained_ids
    ]
    evidence_refs = {
        ref
        for experiment in payload["experiments"]
        for side_name in ("baseline", "candidate")
        for ref in experiment[side_name]["evidenceRefs"]
    }
    evidence_refs.update(
        {
            "eval/interview-metrics/runs/"
            "enterpriseops-csm-sol-to-luna-prompt-adaptation-20260904.r1.json",
            "eval/interview-metrics/runs/"
            "memory-maintenance-sol-to-luna-model-only-optimization-20260904.r1.json",
            "eval/interview-metrics/runs/"
            "cloudops-sol-to-luna-owner-mechanism-prompt-20260904.r1.json",
        }
    )
    for ref in evidence_refs:
        source = repo_root / ref
        target = target_root / ref
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return payload


def _refresh_enterprise_comparison_cost_binding(
    root: Path, *, evidence_name: str, cost_path: Path
) -> None:
    comparison_path = root / (
        "eval/interview-metrics/runs/"
        "enterpriseops-csm-sol-to-luna-prompt-adaptation-20260904.r1.json"
    )
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
    evidence = comparison["evidence"][evidence_name]
    evidence["costFileSha256"] = hashlib.sha256(cost_path.read_bytes()).hexdigest()
    evidence["costReceiptSha256"] = cost["receiptSha256"]
    _seal_receipt(comparison, "receiptSha256")
    comparison_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
    def test_completed_enterprise_rag_r6_model_prompt_transition_is_current(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        by_id = {item["id"]: item for item in payload["experiments"]}
        sol_id = "enterprise-rag.sol-max-standard-r6.v1"
        model_only_id = "enterprise-rag.luna-model-only-standard-r6.v1"
        current_id = "enterprise-rag.luna-prompt-v4-standard-r6.v1"

        self.assertEqual(
            ("history", current_id),
            (
                by_id["enterprise-rag.sol-max-budget3-r3.v1"]["projectionState"],
                by_id["enterprise-rag.sol-max-budget3-r3.v1"]["supersededBy"],
            ),
        )

        sol = by_id[sol_id]
        self.assertEqual(("rejected", "history"), (sol["status"], sol["projectionState"]))
        self.assertEqual(current_id, sol["supersededBy"])
        self.assertEqual(7, sol["candidate"]["metrics"]["exactCitationFactsCovered"])
        self.assertEqual(2.170603, sol["candidate"]["metrics"]["apiCostUsd"])

        model_only = by_id[model_only_id]
        self.assertEqual(
            ("rejected", "history"),
            (model_only["status"], model_only["projectionState"]),
        )
        self.assertEqual(current_id, model_only["supersededBy"])
        self.assertEqual(8, model_only["candidate"]["metrics"]["exactCitationFactsCovered"])
        self.assertEqual(0.10594896, model_only["candidate"]["metrics"]["apiCostUsd"])

        current = by_id[current_id]
        self.assertEqual(("kept", "current"), (current["status"], current["projectionState"]))
        self.assertEqual(("model", "prompt"), tuple(item["name"] for item in current["factors"]))
        stages = current["comparison"]["stageChain"]
        self.assertEqual(
            ["sol_baseline", "luna_model_only", "luna_prompt_v4"],
            [stage["stage"] for stage in stages],
        )
        self.assertEqual([7, 8, 9], [stage["exactCitationFactsCovered"] for stage in stages])
        self.assertEqual([2.170603, 0.10594896, 0.1029376], [stage["costUsd"] for stage in stages])
        self.assertEqual(["reject", "reject", "keep"], [stage["decision"] for stage in stages])
        self.assertEqual(
            95.2576496024,
            current["comparison"]["costComparisons"]["solToPromptV4"]["decreasePercent"],
        )
        self.assertEqual(
            2.84227424224,
            current["comparison"]["costComparisons"]["modelOnlyToPromptV4"]["decreasePercent"],
        )
        boundary = current["comparison"]["validationBoundary"]
        self.assertTrue(boundary["candidateAware"])
        self.assertFalse(boundary["candidateBlind"])
        self.assertFalse(boundary["heldOutOpened"])
        self.assertFalse(boundary["unbiasedPromotionClaimAllowed"])
        self.assertFalse(boundary["standardRevisionIsModelCapabilityImprovement"])
        self.assertFalse(boundary["latencyIsKeepGate"])
        self.assertEqual("runtime_cost_reconciled", boundary["costAuthority"])
        self.assertFalse(boundary["providerBillAvailable"])

    def test_completed_cloudops_model_prompt_transition_is_current(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        by_id = {item["id"]: item for item in payload["experiments"]}
        model_only_id = "cloudops.alert-first-luna-model-only-r1.v1"
        current_id = "cloudops.luna-owner-mechanism-prompt-r5.v1"

        self.assertEqual("history", by_id["cloudops.alert-first-sol-max.v1"]["projectionState"])
        self.assertEqual(
            current_id,
            by_id["cloudops.alert-first-sol-max.v1"]["supersededBy"],
        )
        model_only = by_id[model_only_id]
        self.assertEqual(("rejected", "history"), (model_only["status"], model_only["projectionState"]))
        self.assertEqual(0.9166666666666666, model_only["candidate"]["metrics"]["ca"])
        self.assertEqual(6, model_only["candidate"]["metrics"]["failedToolCalls"])
        self.assertEqual(0.33593112, model_only["candidate"]["metrics"]["apiCostUsd"])

        current = by_id[current_id]
        self.assertEqual(("kept", "current"), (current["status"], current["projectionState"]))
        self.assertEqual(("model", "prompt"), tuple(item["name"] for item in current["factors"]))
        stages = current["comparison"]["stageChain"]
        self.assertEqual(
            ["sol_baseline", "luna_model_only", "luna_prompt_adapted"],
            [stage["stage"] for stage in stages],
        )
        self.assertEqual([4.568166, 0.33593112, 0.27613024], [stage["costUsd"] for stage in stages])
        self.assertEqual([1.0, 0.9166666666666666, 1.0], [stage["ca"] for stage in stages])
        self.assertEqual([1, 6, 0], [stage["failedToolCalls"] for stage in stages])
        self.assertEqual(
            93.9553369996,
            current["comparison"]["costComparisons"]["solToPromptAdapted"]["decreasePercent"],
        )
        self.assertEqual(
            17.8015302661,
            current["comparison"]["costComparisons"]["modelOnlyToPromptAdapted"]["decreasePercent"],
        )
        prompt = current["comparison"]["promptAdaptation"]
        self.assertTrue(prompt["generalOnly"])
        self.assertEqual(
            [
                "exact_family_evidence_lookup",
                "owner_before_mechanism_gate",
                "unresolved_discriminator_stop_rule",
            ],
            prompt["changes"],
        )
        self.assertEqual(
            ["case_id", "expected_answer", "predicted_root", "host_private_gold"],
            prompt["forbidden"],
        )

    def test_completed_enterprise_and_memory_model_transitions_are_current(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        by_id = {item["id"]: item for item in payload["experiments"]}
        enterprise_model_id = "enterpriseops-csm.luna-model-only-r5.v1"
        enterprise_current_id = "enterpriseops-csm.luna-prompt-adaptation-r7.v1"
        memory_current_id = "memory.maintenance-luna-model-only-r1.v1"
        self.assertTrue(
            {enterprise_model_id, enterprise_current_id, memory_current_id}
            <= set(by_id),
            "completed model-transition rows must be registered",
        )

        self.assertEqual("history", by_id["enterpriseops-csm.preloaded-tool-cost.v1"]["projectionState"])
        self.assertEqual(
            enterprise_current_id,
            by_id["enterpriseops-csm.preloaded-tool-cost.v1"]["supersededBy"],
        )
        model_only = by_id[enterprise_model_id]
        self.assertEqual(("rejected", "history"), (model_only["status"], model_only["projectionState"]))
        self.assertEqual(1.0, model_only["baseline"]["metrics"]["taskSuccessRate"])
        self.assertEqual(2 / 3, model_only["candidate"]["metrics"]["taskSuccessRate"])
        self.assertEqual(30 / 31, model_only["candidate"]["metrics"]["verifierPassRate"])
        self.assertEqual(0.09453296, model_only["candidate"]["metrics"]["apiCostUsd"])

        enterprise = by_id[enterprise_current_id]
        self.assertEqual(("kept", "current"), (enterprise["status"], enterprise["projectionState"]))
        self.assertEqual(("model", "prompt"), tuple(item["name"] for item in enterprise["factors"]))
        stages = enterprise["comparison"]["stageChain"]
        self.assertEqual(
            ["sol_baseline", "luna_model_only", "luna_prompt_adapted"],
            [stage["stage"] for stage in stages],
        )
        self.assertEqual([1.711214, 0.09453296, 0.07291692], [stage["costUsd"] for stage in stages])
        self.assertEqual([3, 2, 3], [stage["taskSuccessCount"] for stage in stages])
        self.assertEqual([31, 30, 31], [stage["verifierPassCount"] for stage in stages])
        self.assertEqual(95.738878, enterprise["comparison"]["costComparisons"]["solToPromptAdapted"]["decreasePercent"])
        self.assertEqual(22.866141, enterprise["comparison"]["costComparisons"]["modelOnlyToPromptAdapted"]["decreasePercent"])
        prompt_guard = enterprise["comparison"]["promptAdaptation"]
        self.assertTrue(prompt_guard["generalOnly"])
        self.assertEqual(
            ["role_region_tenure", "selected_tool_catalog_authority", "exact_enum_precedence"],
            prompt_guard["changes"],
        )
        self.assertEqual(["case_id", "expected_answer", "gold"], prompt_guard["forbidden"])
        self.assertTrue(enterprise["comparison"]["runtimeControls"]["binaryToolDatasetRunnerFrozen"])
        self.assertTrue(enterprise["comparison"]["runtimeControls"]["runtimeIdentityShaChangedWithModel"])

        self.assertEqual("history", by_id["memory.maintenance-concise-contract-sol-max.v1"]["projectionState"])
        self.assertEqual(
            memory_current_id,
            by_id["memory.maintenance-concise-contract-sol-max.v1"]["supersededBy"],
        )
        memory = by_id[memory_current_id]
        self.assertEqual(("kept", "current"), (memory["status"], memory["projectionState"]))
        self.assertFalse(memory["comparison"]["promptAdaptationNeeded"])
        self.assertEqual(0.269115, memory["baseline"]["metrics"]["apiCostUsd"])
        self.assertEqual(0.0107502, memory["candidate"]["metrics"]["apiCostUsd"])
        self.assertEqual(96.0053508723, memory["comparison"]["costDecreasePercent"])
        self.assertGreater(
            memory["candidate"]["metrics"]["latencyMs"],
            memory["baseline"]["metrics"]["latencyMs"],
        )
        self.assertFalse(memory["comparison"]["latencyIsKeepGate"])

    def test_enterprise_optimal_path_projects_three_real_stage_nodes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / (
            "eval/interview-metrics/runs/"
            "agent-lab-optimal-path-enterpriseops-luna-prompt-20260904.v1.json"
        )
        receipt = json.loads(path.read_text(encoding="utf-8"))
        validate_contract(receipt, "agent-lab-path-search.v1.json")

        self.assertEqual(
            [
                "enterpriseops-sol-r8",
                "enterpriseops-luna-model-only-r5",
                "enterpriseops-luna-prompt-r7",
            ],
            [step["nodeId"] for step in receipt["selectedPath"]],
        )
        self.assertEqual(
            ["baseline", "reject", "keep"],
            [step["decision"] for step in receipt["selectedPath"]],
        )
        self.assertEqual(
            "enterpriseops-luna-prompt-r7",
            receipt["selectedPath"][-1]["nodeId"],
        )
        nodes = [receipt["baseline"], *receipt["candidates"]]
        for node in nodes:
            self.assertEqual(
                {
                    "taskSuccessRate",
                    "verifierPassRate",
                    "failedToolCalls",
                    "toolCalls",
                    "apiCostUsd",
                    "latencyMs",
                },
                {
                    "taskSuccessRate",
                    "verifierPassRate",
                    "failedToolCalls",
                    "toolCalls",
                    "apiCostUsd",
                    "latencyMs",
                }
                & set(node["metrics"]),
            )
        limitations = "\n".join(receipt["claim"]["limitations"])
        self.assertIn("单轮 Validation", limitations)
        self.assertIn("Provider 账单", limitations)

    def test_repository_matrix_preserves_history_and_adds_current_four_project_results(self) -> None:
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
            "enterpriseops-csm.preloaded-tool-cost.v1": ("kept", "keep", ("tool",)),
            "enterprise-rag.sol-max-budget3-r3.v1": ("rejected", "reject", ("skill", "tool", "workflow")),
            "cloudops.alert-first-sol-max.v1": ("kept", "keep", ("prompt",)),
            "memory.maintenance-concise-contract-sol-max.v1": ("kept", "keep", ("prompt",)),
            "enterpriseops-csm.luna-model-only-r5.v1": ("rejected", "reject", ("model",)),
            "enterpriseops-csm.luna-prompt-adaptation-r7.v1": ("kept", "keep", ("model", "prompt")),
            "memory.maintenance-luna-model-only-r1.v1": ("kept", "keep", ("model",)),
            "memory.maintenance-pi-model-only-20260905-r3.v1": ("kept", "keep", ("model",)),
            "cloudops.alert-first-luna-model-only-r1.v1": ("rejected", "reject", ("model",)),
            "cloudops.luna-owner-mechanism-prompt-r5.v1": ("kept", "keep", ("model", "prompt")),
            "enterprise-rag.sol-max-standard-r6.v1": ("rejected", "reject", ("guardrail",)),
            "enterprise-rag.luna-model-only-standard-r6.v1": ("rejected", "reject", ("model",)),
            "enterprise-rag.luna-prompt-v4-standard-r6.v1": ("kept", "keep", ("model", "prompt")),
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
        self.assertEqual(
            validate_retained_api_pricing_estimates(payload, repo_root=root),
            [],
        )

    def test_retained_api_pricing_estimates_fail_closed_on_ledger_cost_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "memory.maintenance-luna-model-only-r1.v1"
        )
        experiment["candidate"]["metrics"]["apiCostUsd"] = 0.01

        errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "Memory retained cost: candidate.apiCostUsd must match its deterministic cost receipt",
            errors,
        )

    def test_runtime_cost_receipt_is_authority_over_legacy_ledger_numbers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "enterpriseops-csm.luna-prompt-adaptation-r7.v1"
        )
        experiment["baseline"]["metrics"]["apiCostUsd"] = 0.01
        experiment["baseline"]["metrics"]["totalTokens"] = 1
        experiment["candidate"]["metrics"]["apiCostUsd"] = 0.001
        experiment["candidate"]["metrics"]["totalTokens"] = 1

        self.assertEqual(
            validate_retained_api_pricing_estimates(payload, repo_root=root),
            [],
        )

    def test_runtime_cost_reconciled_receipt_validates_exact_authority_fields(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="paw-retained-cost-") as tmp:
            root = Path(tmp)
            payload = _retained_cost_fixture(repo_root, root)
            cost_path = root / (
                "eval/interview-metrics/runs/"
                "agent-lab-cost-enterpriseops-sol-max-preloaded-current-runtime-20260904.r8.v1.json"
            )
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            cost["pricingIdentity"]["pricingId"] = "pricing:sha256:" + "0" * 64
            runtime = cost["runtimeCostReceipt"]
            runtime["requestCount"] = 0
            runtime["databaseUsage"]["cachedInputTokens"] = -1
            runtime["reportedCostUsd"]["total"] = "2.258371"
            _seal_receipt(runtime, "sourceSha256")
            cost["usage"]["sourceSha256"] = runtime["sourceSha256"]
            _seal_receipt(cost, "receiptSha256")
            cost_path.write_text(
                json.dumps(cost, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "EnterpriseOps retained cost: baseline pricingId must match its content-addressed pricing identity",
            errors,
        )
        self.assertIn(
            "EnterpriseOps retained cost: baseline runtime requestCount must be a positive integer",
            errors,
        )
        self.assertIn(
            "EnterpriseOps retained cost: baseline runtime databaseUsage must contain three non-negative integers",
            errors,
        )
        self.assertIn(
            "EnterpriseOps retained cost: baseline runtime reportedCostUsd must match the receipt estimate",
            errors,
        )

    def test_runtime_trial_aggregate_is_an_independent_raw_report_diagnostic(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="paw-retained-cost-") as tmp:
            root = Path(tmp)
            payload = _retained_cost_fixture(repo_root, root)
            raw_path = root / (
                "eval/interview-metrics/runs/"
                "enterpriseops-csm-sol-max-preloaded-current-runtime-validation-20260904.r8.v1.json"
            )
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            aggregate = {
                "uncachedInputTokens": sum(
                    task["usage"]["input"] for task in raw["lane"]["tasks"]
                ),
                "cachedInputTokens": sum(
                    task["usage"]["cacheRead"] for task in raw["lane"]["tasks"]
                ),
                "outputTokens": sum(
                    task["usage"]["output"] for task in raw["lane"]["tasks"]
                ),
            }
            cost_path = root / (
                "eval/interview-metrics/runs/"
                "agent-lab-cost-enterpriseops-sol-max-preloaded-current-runtime-20260904.r8.v1.json"
            )
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            runtime = cost["runtimeCostReceipt"]
            self.assertNotEqual(aggregate, runtime["databaseUsage"])
            runtime["trialAggregate"] = {
                "sourceRef": (
                    "agent-artifact:"
                    "enterpriseops-csm-sol-max-preloaded-current-runtime-validation-20260904-r8:"
                    "trial_completed"
                ),
                "sourceSha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                **aggregate,
            }
            _seal_receipt(runtime, "sourceSha256")
            cost["usage"]["sourceSha256"] = runtime["sourceSha256"]
            _seal_receipt(cost, "receiptSha256")
            cost_path.write_text(
                json.dumps(cost, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _refresh_enterprise_comparison_cost_binding(
                root,
                evidence_name="solBaseline",
                cost_path=cost_path,
            )

            errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertEqual(errors, [])

    def test_runtime_database_usage_must_match_exact_receipt_usage(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="paw-retained-cost-") as tmp:
            root = Path(tmp)
            payload = _retained_cost_fixture(repo_root, root)
            cost_path = root / (
                "eval/interview-metrics/runs/"
                "agent-lab-cost-enterpriseops-sol-max-preloaded-current-runtime-20260904.r8.v1.json"
            )
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            runtime = cost["runtimeCostReceipt"]
            runtime["databaseUsage"]["uncachedInputTokens"] += 1
            _seal_receipt(runtime, "sourceSha256")
            cost["usage"]["sourceSha256"] = runtime["sourceSha256"]
            _seal_receipt(cost, "receiptSha256")
            cost_path.write_text(
                json.dumps(cost, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "EnterpriseOps retained cost: baseline runtime databaseUsage must match the receipt usage",
            errors,
        )

    def test_cloudops_exact_runtime_receipt_is_checked(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="paw-retained-cost-") as tmp:
            root = Path(tmp)
            payload = _retained_cost_fixture(repo_root, root)
            cost_path = root / (
                "eval/interview-metrics/runs/"
                "agent-lab-cost-cloudops-luna-max-owner-mechanism-prompt-20260904.r5.v1.json"
            )
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            runtime = cost["runtimeCostReceipt"]
            runtime["databaseUsage"]["uncachedInputTokens"] += 1
            _seal_receipt(runtime, "sourceSha256")
            cost["usage"]["sourceSha256"] = runtime["sourceSha256"]
            _seal_receipt(cost, "receiptSha256")
            cost_path.write_text(
                json.dumps(cost, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "CloudOps retained cost: candidate runtime databaseUsage must match the receipt usage",
            errors,
        )

    def test_legacy_pricing_estimate_cannot_masquerade_as_exact_runtime_cost(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="paw-retained-cost-") as tmp:
            root = Path(tmp)
            payload = _retained_cost_fixture(repo_root, root)
            cost_path = root / (
                "eval/interview-metrics/runs/"
                "agent-lab-cost-memory-sol-max-model-baseline-20260904.r4.v1.json"
            )
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            cost["authority"] = "runtime_cost_reconciled"
            _seal_receipt(cost, "receiptSha256")
            cost_path.write_text(
                json.dumps(cost, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "Memory retained cost: baseline runtime_cost_reconciled requires runtimeCostReceipt",
            errors,
        )

    def test_completed_luna_rows_supersede_but_preserve_prompt_history(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        by_id = {item["id"]: item for item in payload["experiments"]}

        enterprise_history = by_id["enterpriseops-csm.preloaded-tool-cost.v1"]
        memory_prompt_history = by_id[
            "memory.maintenance-concise-contract-sol-max.v1"
        ]
        self.assertEqual("history", enterprise_history["projectionState"])
        self.assertEqual(
            "enterpriseops-csm.luna-prompt-adaptation-r7.v1",
            enterprise_history["supersededBy"],
        )
        self.assertEqual("history", memory_prompt_history["projectionState"])
        self.assertEqual(
            "memory.maintenance-luna-model-only-r1.v1",
            memory_prompt_history["supersededBy"],
        )
        self.assertIn("6.6%", memory_prompt_history["star"]["result"])

    def test_model_cost_receipts_reject_thinking_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "enterpriseops-csm.luna-model-only-r5.v1"
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
            if item["id"] == "enterprise-rag.luna-prompt-v4-standard-r6.v1"
        )
        rag_winner["status"] = "rejected"
        rag_winner["comparison"]["decision"] = "reject"

        errors = validate_business_project_keep_paths(payload)

        self.assertIn(
            "RAG: current Luna Prompt-v4 r6 Keep must retain the 7/9 to 8/9 to 9/9 three-stage path and exact Runtime cost reductions",
            errors,
        )

    def test_enterprise_rag_r6_cost_receipts_fail_closed_on_ledger_cost_drift(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        experiment = next(
            item for item in payload["experiments"]
            if item["id"] == "enterprise-rag.luna-prompt-v4-standard-r6.v1"
        )
        experiment["candidate"]["metrics"]["apiCostUsd"] = 0.1

        errors = validate_retained_api_pricing_estimates(payload, repo_root=root)

        self.assertIn(
            "Enterprise RAG retained cost: final apiCostUsd must match its Runtime cost receipt",
            errors,
        )

    def test_cloudops_current_path_cannot_be_replaced_by_historical_baseline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads(
            (root / "eval/interview-metrics/agent-experiments.v1.json").read_text(
                encoding="utf-8"
            )
        )
        current = next(
            item for item in payload["experiments"]
            if item["id"] == "cloudops.luna-owner-mechanism-prompt-r5.v1"
        )
        current["projectionState"] = "history"

        errors = validate_business_project_keep_paths(payload)

        self.assertIn(
            "CloudOps: current Luna Prompt r5 Keep must retain the three-stage quality, Tool and exact Runtime cost result",
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
