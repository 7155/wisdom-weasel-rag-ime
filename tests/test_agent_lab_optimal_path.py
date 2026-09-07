from __future__ import annotations

import hashlib
import json
import unittest

from rag_ime.agent_lab.optimal_path import evaluate_path_search


def _controls() -> list[dict[str, str]]:
    return [
        {"name": "suite", "value": "enterpriseops-csm-suite-v2"},
        {"name": "split", "value": "validation"},
        {"name": "cases", "value": "3 tasks / 31 host-private verifiers"},
    ]


def _control_hash() -> str:
    raw = json.dumps(_controls(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _node(
    node_id: str,
    parent: str | None,
    metrics: dict[str, float],
    *,
    changed_factor: str = "workflow",
    status: str = "eligible",
    frozen_hash: str | None = None,
) -> dict[str, object]:
    return {
        "nodeId": node_id,
        "parentNodeId": parent,
        "changedFactor": changed_factor,
        "configRevision": node_id,
        "frozenControlHash": frozen_hash or _control_hash(),
        "metrics": metrics,
        "evidenceRefs": [f"receipt:{node_id}"],
        "status": status,
    }


def _request(candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.agent-lab-path-search-request.v1",
        "searchId": "enterpriseops-csm-optimal-path-v1",
        "title": "EnterpriseOps CSM optimal path",
        "objective": {
            "userNeed": "完成全部客户支持任务，同时平衡运行成本和延迟。",
            "metrics": [
                {"name": "taskSuccessRate", "direction": "max", "weight": 0.55, "class": "quality", "scale": 1},
                {"name": "verifierPassRate", "direction": "max", "weight": 0.25, "class": "quality", "scale": 1},
                {"name": "toolCalls", "direction": "min", "weight": 0.05, "class": "efficiency", "scale": 100},
                {"name": "latencyMs", "direction": "min", "weight": 0.15, "class": "efficiency", "scale": 1_000},
                {"name": "apiCostUsd", "direction": "min", "weight": 0.10, "class": "cost", "scale": 1},
            ],
            "gates": [
                {"name": "all tasks complete", "metric": "taskSuccessRate", "operator": "gte", "value": 1},
                {"name": "all verifiers pass", "metric": "verifierPassRate", "operator": "gte", "value": 1},
                {"name": "no tool failures", "metric": "failedToolCalls", "operator": "lte", "value": 0},
                {"name": "cleanup complete", "metric": "allDatabasesCleaned", "operator": "eq", "value": 1},
            ],
            "selectionPolicy": "lexicographic_pareto",
        },
        "frozenControls": _controls(),
        "baseline": _node("sol-baseline", None, {
            "taskSuccessRate": 0.6666667,
            "verifierPassRate": 0.9032258,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 72,
            "latencyMs": 529349.673,
        }, changed_factor="baseline"),
        "candidates": candidates,
    }


class AgentLabOptimalPathTests(unittest.TestCase):
    def test_non_eligible_baseline_fails_closed(self) -> None:
        for status in ("rejected", "not_evaluated", "unknown"):
            with self.subTest(status=status):
                request = _request([_node("candidate", "sol-baseline", {
                    "taskSuccessRate": 1,
                    "verifierPassRate": 1,
                    "failedToolCalls": 0,
                    "allDatabasesCleaned": 1,
                    "toolCalls": 1,
                    "latencyMs": 1,
                })])
                baseline = request["baseline"]
                assert isinstance(baseline, dict)
                baseline["status"] = status

                with self.assertRaisesRegex(ValueError, "baseline must be eligible"):
                    evaluate_path_search(request, generated_at_ms=123)

    def test_baseline_frozen_hash_mismatch_fails_closed(self) -> None:
        request = _request([_node("candidate", "sol-baseline", {
            "taskSuccessRate": 1,
            "verifierPassRate": 1,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 1,
            "latencyMs": 1,
        })])
        baseline = request["baseline"]
        assert isinstance(baseline, dict)
        baseline["frozenControlHash"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "baseline frozen control hash"):
            evaluate_path_search(request, generated_at_ms=123)

    def test_baseline_without_evidence_fails_closed(self) -> None:
        request = _request([_node("candidate", "sol-baseline", {
            "taskSuccessRate": 1,
            "verifierPassRate": 1,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 1,
            "latencyMs": 1,
        })])
        baseline = request["baseline"]
        assert isinstance(baseline, dict)
        baseline["evidenceRefs"] = []

        with self.assertRaisesRegex(ValueError, "baseline evidenceRefs"):
            evaluate_path_search(request, generated_at_ms=123)

    def test_candidate_without_evidence_is_rejected(self) -> None:
        candidate = _node("unproven", "sol-baseline", {
            "taskSuccessRate": 1,
            "verifierPassRate": 1,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 1,
            "latencyMs": 1,
            "apiCostUsd": 0.01,
        })
        candidate["evidenceRefs"] = []

        receipt = evaluate_path_search(_request([candidate]), generated_at_ms=123)

        self.assertEqual(receipt["candidates"][0]["status"], "rejected")
        self.assertIn("evidenceRefs", receipt["candidates"][0]["reason"])
        self.assertEqual(receipt["claim"]["status"], "insufficient_evidence")
        self.assertEqual(receipt["selectedPath"][-1]["nodeId"], "sol-baseline")

    def test_selection_policy_changes_pareto_tie_break(self) -> None:
        few_calls = _node("few-calls", "sol-baseline", {
            "taskSuccessRate": 1,
            "verifierPassRate": 1,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 1,
            "latencyMs": 1_000_000,
            "apiCostUsd": 0.01,
        })
        low_latency = _node("low-latency", "sol-baseline", {
            "taskSuccessRate": 1,
            "verifierPassRate": 1,
            "failedToolCalls": 0,
            "allDatabasesCleaned": 1,
            "toolCalls": 100,
            "latencyMs": 1,
            "apiCostUsd": 0.01,
        })
        lexicographic = _request([few_calls, low_latency])
        weighted = _request([few_calls, low_latency])
        weighted_objective = weighted["objective"]
        assert isinstance(weighted_objective, dict)
        weighted_objective["selectionPolicy"] = "weighted_pareto"

        lexicographic_receipt = evaluate_path_search(lexicographic, generated_at_ms=123)
        weighted_receipt = evaluate_path_search(weighted, generated_at_ms=123)

        self.assertEqual(lexicographic_receipt["selectedPath"][-1]["nodeId"], "few-calls")
        self.assertEqual(weighted_receipt["selectedPath"][-1]["nodeId"], "low-latency")

    def test_selects_quality_safe_pareto_candidate_and_reports_cost_gap(self) -> None:
        receipt = evaluate_path_search(
            _request([
                _node("sol-state-contract", "sol-baseline", {
                    "taskSuccessRate": 1,
                    "verifierPassRate": 1,
                    "failedToolCalls": 0,
                    "allDatabasesCleaned": 1,
                    "toolCalls": 64,
                    "latencyMs": 758437.096,
                }),
                _node("luna-state-contract", "sol-state-contract", {
                    "taskSuccessRate": 1,
                    "verifierPassRate": 1,
                    "failedToolCalls": 0,
                    "allDatabasesCleaned": 1,
                    "toolCalls": 66,
                    "latencyMs": 959310.002,
                }, changed_factor="model"),
            ]),
            generated_at_ms=123,
        )

        self.assertEqual(receipt["claim"]["status"], "insufficient_evidence")
        self.assertEqual([step["nodeId"] for step in receipt["selectedPath"]], ["sol-baseline", "sol-state-contract"])
        self.assertIn("apiCostUsd", receipt["claim"]["limitations"][-1])
        luna = next(node for node in receipt["candidates"] if node["nodeId"] == "luna-state-contract")
        self.assertEqual(luna["status"], "eligible")

    def test_quality_regression_is_pruned_even_when_cheaper(self) -> None:
        receipt = evaluate_path_search(
            _request([_node("cheap-bad", "sol-baseline", {
                "taskSuccessRate": 0.6666667,
                "verifierPassRate": 0.9032258,
                "failedToolCalls": 0,
                "allDatabasesCleaned": 1,
                "toolCalls": 4,
                "latencyMs": 10,
            })]),
            generated_at_ms=123,
        )
        candidate = receipt["candidates"][0]
        self.assertEqual(candidate["status"], "rejected")
        self.assertTrue("quality_non_regression" in candidate["reason"] or "hard or quality gate failed" in candidate["reason"])
        self.assertEqual(receipt["selectedPath"][-1]["nodeId"], "sol-baseline")

    def test_frozen_hash_mismatch_is_rejected_without_rewriting_receipt(self) -> None:
        receipt = evaluate_path_search(
            _request([_node("changed-control", "sol-baseline", {
                "taskSuccessRate": 1,
                "verifierPassRate": 1,
                "failedToolCalls": 0,
                "allDatabasesCleaned": 1,
                "toolCalls": 1,
                "latencyMs": 1,
            }, frozen_hash="0" * 64)]),
            generated_at_ms=123,
        )
        self.assertEqual(receipt["candidates"][0]["status"], "rejected")
        self.assertIn("frozen control hash", receipt["candidates"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
