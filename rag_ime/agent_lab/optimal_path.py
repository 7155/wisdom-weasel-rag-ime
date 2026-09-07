from __future__ import annotations

"""Deterministic, read-only selection of a best-known Agent Lab path.

The module never runs an Agent and never mutates an old receipt.  It consumes a
user-owned search request containing frozen controls and already measured
candidate nodes, then emits an append-only selection receipt.  Quality and
reliability gates are checked before soft efficiency/cost preferences so a
cheap but incorrect candidate cannot win.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..contracts.json_schema import validate_contract


_QUALITY_CLASSES = {"quality", "reliability"}


def evaluate_path_search(
    request: Mapping[str, object],
    *,
    generated_at_ms: int,
) -> dict[str, object]:
    """Evaluate a frozen candidate tree and return a contract-valid receipt."""

    request_value = dict(request)
    validate_contract(request_value, "agent-lab-path-search-request.v1.json")
    objective = _mapping(request_value["objective"], "objective")
    metric_specs = _metric_specs(objective["metrics"])
    gate_specs = _gate_specs(objective["gates"])
    controls = _controls(request_value["frozenControls"])
    frozen_hash = _sha256_json(controls)
    baseline = _node(request_value["baseline"], "baseline")
    _validate_baseline(baseline, frozen_hash)
    candidates = [_node(value, f"candidates[{index}]") for index, value in enumerate(request_value["candidates"])]
    all_nodes = {str(baseline["nodeId"]): baseline}
    for candidate in candidates:
        node_id = str(candidate["nodeId"])
        if node_id in all_nodes:
            raise ValueError(f"duplicate path node: {node_id}")
        all_nodes[node_id] = candidate

    evaluated: list[dict[str, object]] = []
    for candidate in candidates:
        result = dict(candidate)
        reasons: list[str] = []
        if candidate["frozenControlHash"] != frozen_hash:
            result["status"] = "rejected"
            reasons.append("frozen control hash does not match this search request")
        elif not _valid_parent(candidate, all_nodes):
            result["status"] = "rejected"
            reasons.append("parent node is missing, self-referential, or cyclic")
        elif not candidate["evidenceRefs"]:
            result["status"] = "rejected"
            reasons.append("candidate evidenceRefs are required for selection")
        elif candidate["status"] != "eligible":
            result["status"] = str(candidate["status"])
            reasons.append("candidate was not marked eligible by its producing run")
        else:
            gate_results = _gate_results(candidate["metrics"], gate_specs)
            quality_results = _quality_non_regression(
                baseline["metrics"], candidate["metrics"], metric_specs
            )
            failures = [item["name"] for item in [*gate_results, *quality_results] if item["status"] == "fail"]
            unknowns = [item["name"] for item in [*gate_results, *quality_results] if item["status"] == "unknown"]
            missing_quality = _missing_required_quality(candidate["metrics"], metric_specs)
            if failures:
                result["status"] = "rejected"
                reasons.append(f"hard or quality gate failed: {', '.join(failures)}")
            elif unknowns or missing_quality:
                result["status"] = "unknown"
                if unknowns:
                    reasons.append(f"gate evidence unavailable: {', '.join(unknowns)}")
                if missing_quality:
                    reasons.append(f"quality metric unavailable: {', '.join(missing_quality)}")
            else:
                result["status"] = "eligible"
                reasons.append("all required hard and quality gates passed")
        if not reasons:
            reasons.append("candidate retained")
        result["reason"] = "; ".join(reasons)
        evaluated.append(result)

    eligible = [node for node in evaluated if node["status"] == "eligible"]
    pareto = _pareto_front(eligible, metric_specs, baseline["metrics"])
    selected = _select_candidate(
        pareto,
        metric_specs,
        baseline["metrics"],
        all_nodes,
        selection_policy=str(objective["selectionPolicy"]),
    )
    selected_node = selected or baseline
    selected_gates = [
        *_gate_results(selected_node["metrics"], gate_specs),
        *_quality_non_regression(baseline["metrics"], selected_node["metrics"], metric_specs),
    ]
    selected_path = _selected_path(selected_node, baseline, all_nodes)
    path_steps: list[dict[str, str]] = []
    for node in selected_path:
        node_id = str(node["nodeId"])
        if node_id == str(baseline["nodeId"]):
            path_steps.append({"nodeId": node_id, "decision": "baseline", "reason": "用户指定的比较基线。"})
        else:
            path_steps.append({
                "nodeId": node_id,
                "decision": "keep" if node is selected_node else "keep",
                "reason": str(node.get("reason") or "该节点位于当前选中路径。"),
            })

    missing_soft = _missing_metrics(selected_node["metrics"], metric_specs, classes={"efficiency", "cost"})
    all_metrics_known = not _missing_metrics(selected_node["metrics"], metric_specs, classes=None)
    gate_failures = [item["name"] for item in selected_gates if item["status"] == "fail"]
    gate_unknowns = [item["name"] for item in selected_gates if item["status"] == "unknown"]
    if selected is None:
        claim_status = "insufficient_evidence"
        summary = "没有候选同时通过硬门禁和质量非回退约束，当前只能保留基线。"
    elif gate_failures:
        claim_status = "insufficient_evidence"
        summary = f"候选 {selected['nodeId']} 仍有门禁失败，不能作为最优路径。"
    elif gate_unknowns or not all_metrics_known:
        claim_status = "insufficient_evidence"
        summary = f"当前选中路径为 {selected['nodeId']}；质量门禁通过，但仍缺少部分效率/成本证据。"
    else:
        claim_status = "best_known"
        summary = f"当前选中路径为 {selected['nodeId']}，在声明搜索空间内通过门禁且综合效用最高。"

    limitations = [
        "结果只代表本次声明的搜索空间和冻结控制，不是全局最优证明。",
        "Validation 用于路径选择；不得把本回执改写为 Held-out 或生产结论。",
    ]
    if missing_soft:
        limitations.append(f"选中节点缺少软指标：{', '.join(missing_soft)}；成本比较需要独立 usage receipt。")
    if not eligible:
        limitations.append("当前没有可用于 Pareto 比较的候选节点。")

    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-path-search.v1",
        "searchId": str(request_value["searchId"]),
        "title": str(request_value["title"]),
        "objective": objective,
        "frozenControls": controls,
        "baseline": baseline,
        "candidates": evaluated,
        "selectedPath": path_steps,
        "hardGates": [
            {"name": str(item["name"]), "status": str(item["status"]), "reason": str(item["reason"])}
            for item in selected_gates
        ],
        "claim": {
            "status": claim_status,
            "summary": summary,
            "limitations": limitations,
        },
        "generatedAtMs": max(0, int(generated_at_ms)),
    }
    validate_contract(receipt, "agent-lab-path-search.v1.json")
    return receipt


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _controls(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("frozenControls must be a list")
    result: list[dict[str, str]] = []
    for item in value:
        control = _mapping(item, "frozenControl")
        result.append({"name": str(control["name"]), "value": str(control["value"])})
    return result


def _node(value: object, label: str) -> dict[str, object]:
    node = _mapping(value, label)
    metrics = _mapping(node["metrics"], f"{label}.metrics")
    return {
        "nodeId": str(node["nodeId"]),
        "parentNodeId": node.get("parentNodeId"),
        "changedFactor": str(node["changedFactor"]),
        "configRevision": str(node["configRevision"]),
        "frozenControlHash": str(node["frozenControlHash"]),
        "metrics": {str(key): float(value) for key, value in metrics.items()},
        "evidenceRefs": [str(value) for value in node.get("evidenceRefs", [])],
        "status": str(node["status"]),
        **({"reason": str(node["reason"])} if node.get("reason") else {}),
    }


def _validate_baseline(baseline: Mapping[str, object], frozen_hash: str) -> None:
    if baseline["status"] != "eligible":
        raise ValueError("baseline must be eligible")
    if baseline["frozenControlHash"] != frozen_hash:
        raise ValueError("baseline frozen control hash does not match this search request")
    if not baseline["evidenceRefs"]:
        raise ValueError("baseline evidenceRefs are required for selection")


def _metric_specs(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("objective.metrics must be a list")
    return [_mapping(item, "metric spec") for item in value]


def _gate_specs(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("objective.gates must be a list")
    return [_mapping(item, "gate spec") for item in value]


def _valid_parent(node: Mapping[str, object], all_nodes: Mapping[str, Mapping[str, object]]) -> bool:
    parent = node.get("parentNodeId")
    if not isinstance(parent, str) or parent not in all_nodes or parent == node["nodeId"]:
        return False
    seen: set[str] = set()
    current: Mapping[str, object] = node
    while True:
        current_id = str(current["nodeId"])
        if current_id in seen:
            return False
        seen.add(current_id)
        parent_id = current.get("parentNodeId")
        if parent_id is None:
            return True
        if not isinstance(parent_id, str) or parent_id not in all_nodes:
            return False
        current = all_nodes[parent_id]


def _gate_results(metrics: Mapping[str, object], specs: list[Mapping[str, object]]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for spec in specs:
        name = str(spec["name"])
        metric = str(spec["metric"])
        actual = metrics.get(metric)
        if actual is None:
            results.append({"name": name, "status": "unknown", "reason": f"缺少 metric {metric}。"})
            continue
        expected = float(spec["value"])
        value = float(actual)
        operator = str(spec["operator"])
        passed = {"gte": value >= expected, "lte": value <= expected, "eq": value == expected}[operator]
        results.append({
            "name": name,
            "status": "pass" if passed else "fail",
            "reason": f"{metric}={value:g}，门槛 {operator} {expected:g}。",
        })
    return results


def _quality_non_regression(
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
    specs: list[Mapping[str, object]],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for spec in specs:
        if str(spec["class"]) not in _QUALITY_CLASSES or spec.get("nonRegression", True) is False:
            continue
        name = str(spec["name"])
        before = baseline.get(name)
        after = candidate.get(name)
        if before is None or after is None:
            results.append({"name": f"quality_non_regression:{name}", "status": "unknown", "reason": f"缺少 {name} 的前后指标。"})
            continue
        direction = str(spec["direction"])
        passed = float(after) >= float(before) if direction == "max" else float(after) <= float(before)
        results.append({
            "name": f"quality_non_regression:{name}",
            "status": "pass" if passed else "fail",
            "reason": f"baseline={float(before):g}，candidate={float(after):g}。",
        })
    return results


def _missing_required_quality(metrics: Mapping[str, object], specs: list[Mapping[str, object]]) -> list[str]:
    return [str(spec["name"]) for spec in specs if str(spec["class"]) in _QUALITY_CLASSES and str(spec["name"]) not in metrics]


def _missing_metrics(
    metrics: Mapping[str, object],
    specs: list[Mapping[str, object]],
    *,
    classes: set[str] | None,
) -> list[str]:
    return [
        str(spec["name"])
        for spec in specs
        if (classes is None or str(spec["class"]) in classes) and str(spec["name"]) not in metrics
    ]


def _normalized_improvement(
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
    spec: Mapping[str, object],
) -> float | None:
    name = str(spec["name"])
    if name not in baseline or name not in candidate:
        return None
    scale = float(spec.get("scale") or max(abs(float(baseline[name])), 1.0))
    delta = float(candidate[name]) - float(baseline[name])
    return (delta if spec["direction"] == "max" else -delta) / scale


def _utility(
    node: Mapping[str, object],
    specs: list[Mapping[str, object]],
    baseline: Mapping[str, object],
) -> float:
    weighted = 0.0
    weight_sum = 0.0
    for spec in specs:
        improvement = _normalized_improvement(baseline, node["metrics"], spec)
        if improvement is None:
            continue
        weight = float(spec["weight"])
        weighted += weight * improvement
        weight_sum += weight
    return weighted / weight_sum if weight_sum else float("-inf")


def _lexicographic_scores(
    node: Mapping[str, object],
    specs: list[Mapping[str, object]],
    baseline: Mapping[str, object],
) -> tuple[float, ...]:
    """Rank declared metrics in order, with missing evidence always worst."""

    return tuple(
        score if score is not None else float("-inf")
        for spec in specs
        for score in (_normalized_improvement(baseline, node["metrics"], spec),)
    )


def _pareto_front(
    nodes: list[dict[str, object]],
    specs: list[Mapping[str, object]],
    baseline: Mapping[str, object],
) -> list[dict[str, object]]:
    front: list[dict[str, object]] = []
    for node in nodes:
        if any(_dominates(other, node, specs, baseline) for other in nodes if other is not node):
            continue
        front.append(node)
    return front


def _dominates(
    left: Mapping[str, object],
    right: Mapping[str, object],
    specs: list[Mapping[str, object]],
    baseline: Mapping[str, object],
) -> bool:
    left_scores: list[float] = []
    right_scores: list[float] = []
    for spec in specs:
        left_score = _normalized_improvement(baseline, left["metrics"], spec)
        right_score = _normalized_improvement(baseline, right["metrics"], spec)
        if left_score is None or right_score is None:
            continue
        left_scores.append(left_score)
        right_scores.append(right_score)
    return bool(left_scores) and all(left_score >= right_score for left_score, right_score in zip(left_scores, right_scores)) and any(left_score > right_score for left_score, right_score in zip(left_scores, right_scores))


def _select_candidate(
    nodes: list[dict[str, object]],
    specs: list[Mapping[str, object]],
    baseline: Mapping[str, object],
    all_nodes: Mapping[str, Mapping[str, object]],
    *,
    selection_policy: str,
) -> dict[str, object] | None:
    if not nodes:
        return None
    if selection_policy == "lexicographic_pareto":
        return max(
            nodes,
            key=lambda node: (
                _lexicographic_scores(node, specs, baseline),
                -len(_path_ids(node, all_nodes)),
                str(node["nodeId"]),
            ),
        )
    if selection_policy != "weighted_pareto":
        raise ValueError(f"unsupported selection policy: {selection_policy}")
    return max(
        nodes,
        key=lambda node: (
            _utility(node, specs, baseline),
            -len(_path_ids(node, all_nodes)),
            str(node["nodeId"]),
        ),
    )


def _selected_path(
    selected: Mapping[str, object],
    baseline: Mapping[str, object],
    all_nodes: Mapping[str, Mapping[str, object]],
) -> list[Mapping[str, object]]:
    path: list[Mapping[str, object]] = []
    current: Mapping[str, object] | None = selected
    while current is not None:
        path.append(current)
        parent = current.get("parentNodeId")
        if parent is None:
            break
        current = all_nodes.get(str(parent))
    if path[-1]["nodeId"] != baseline["nodeId"]:
        path.append(baseline)
    return list(reversed(path))


def _path_ids(node: Mapping[str, object], all_nodes: Mapping[str, Mapping[str, object]]) -> list[str]:
    ids: list[str] = []
    current: Mapping[str, object] | None = node
    while current is not None:
        ids.append(str(current["nodeId"]))
        parent = current.get("parentNodeId")
        current = all_nodes.get(str(parent)) if parent is not None else None
    return ids


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
