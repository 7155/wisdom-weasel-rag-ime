#!/usr/bin/env python3
"""Aggregate disjoint, accepted four-lane RAG Agent batches."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "rag-ime.rag-agent-ablation-aggregate.v1"
RUN_SCHEMA_VERSION = "rag-ime.rag-agent-ablation-run.v1"
LANES = ("baseline", "skill", "tuned", "agentic")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    paths = [path.expanduser().resolve(strict=True) for path in args.report]
    report = aggregate_reports(paths)
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_json(output, report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "batchCount": report["batchCount"],
                "caseCount": report["caseCount"],
                "reportSha256": report["reportSha256"],
                "agentComparison": report["comparisons"]["baselineToAgentic"]["agent"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] is True else 1


def aggregate_reports(paths: list[Path]) -> dict[str, Any]:
    if len(paths) < 2:
        raise ValueError("at least two Agent batch reports are required")
    loaded = [_verified_report(path) for path in paths]
    first = loaded[0]["report"]
    identity = _condition_identity(first)
    seen_case_ids: set[str] = set()
    batch_records: list[dict[str, object]] = []
    weighted_lanes: dict[str, list[tuple[int, Mapping[str, object]]]] = {
        lane: [] for lane in LANES
    }
    minimum_started = 0
    maximum_completed = 0
    total_elapsed_ms = 0

    for loaded_item in loaded:
        path = loaded_item["path"]
        report = loaded_item["report"]
        if _condition_identity(report) != identity:
            raise ValueError(f"Agent batch conditions differ: {path.name}")
        if report.get("passed") is not True:
            raise ValueError(f"Agent batch did not pass: {path.name}")
        if report.get("localOnly") is not True or report.get("uploaded") is not False:
            raise ValueError(f"Agent batch is not local-only: {path.name}")
        if report.get("cleanupPassed") is not True:
            raise ValueError(f"Agent batch cleanup did not pass: {path.name}")

        evaluation = report.get("evaluation")
        if not isinstance(evaluation, Mapping):
            raise ValueError(f"Agent batch has no evaluation manifest: {path.name}")
        case_ids = evaluation.get("caseIds")
        if not isinstance(case_ids, list) or not case_ids:
            raise ValueError(f"Agent batch has no case IDs: {path.name}")
        normalized_case_ids = [str(value).strip() for value in case_ids]
        if (
            any(not value for value in normalized_case_ids)
            or len(set(normalized_case_ids)) != len(normalized_case_ids)
            or int(evaluation.get("caseCount") or 0) != len(normalized_case_ids)
        ):
            raise ValueError(f"Agent batch case IDs are invalid: {path.name}")
        overlap = seen_case_ids & set(normalized_case_ids)
        if overlap:
            raise ValueError(
                "Agent batches overlap on held-out cases: " + ", ".join(sorted(overlap))
            )
        seen_case_ids.update(normalized_case_ids)

        lane_map = {
            str(item.get("lane") or ""): item
            for item in report.get("lanes") or []
            if isinstance(item, Mapping)
        }
        if set(lane_map) != set(LANES):
            raise ValueError(f"Agent batch does not contain exactly four lanes: {path.name}")
        for lane in LANES:
            record = lane_map[lane]
            hard_gates = record.get("hardGates")
            if (
                not isinstance(hard_gates, Mapping)
                or not hard_gates
                or not all(value is True for value in hard_gates.values())
            ):
                raise ValueError(f"Agent batch lane hard gates failed: {path.name}:{lane}")
            weighted_lanes[lane].append((len(normalized_case_ids), record))

        started_at_ms = int(report.get("startedAtMs") or 0)
        completed_at_ms = int(report.get("completedAtMs") or 0)
        if started_at_ms <= 0 or completed_at_ms < started_at_ms:
            raise ValueError(f"Agent batch timestamps are invalid: {path.name}")
        minimum_started = (
            started_at_ms
            if minimum_started == 0
            else min(minimum_started, started_at_ms)
        )
        maximum_completed = max(maximum_completed, completed_at_ms)
        total_elapsed_ms += int(report.get("elapsedMs") or 0)
        batch_records.append(
            {
                "fileName": path.name,
                "fileSha256": loaded_item["fileSha256"],
                "reportSha256": report["reportSha256"],
                "caseCount": len(normalized_case_ids),
                "caseIdsSha256": _sha256_json(sorted(normalized_case_ids)),
                "selectionSeed": str(evaluation.get("selectionSeed") or ""),
            }
        )

    case_count = len(seen_case_ids)
    lanes = [
        _aggregate_lane(lane, weighted_lanes[lane], total_case_count=case_count)
        for lane in LANES
    ]
    lane_map = {str(item["lane"]): item for item in lanes}
    hard_gates = {
        "allBatchesAccepted": True,
        "allLaneHardGates": True,
        "conditionEquality": True,
        "disjointHeldOutCases": sum(item[0] for item in weighted_lanes["baseline"])
        == case_count,
        "localOnly": True,
        "notUploaded": True,
        "sourceIdentity": True,
    }
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "passed": all(hard_gates.values()),
        "localOnly": True,
        "uploaded": False,
        "startedAtMs": minimum_started,
        "completedAtMs": maximum_completed,
        "elapsedMsSum": total_elapsed_ms,
        "batchCount": len(batch_records),
        "caseCount": case_count,
        "caseIds": sorted(seen_case_ids),
        "caseIdsSha256": _sha256_json(sorted(seen_case_ids)),
        "identity": identity,
        "batches": batch_records,
        "hardGates": hard_gates,
        "lanes": lanes,
        "comparisons": {
            "baselineToSkill": _lane_comparison(
                lane_map["baseline"], lane_map["skill"]
            ),
            "baselineToTuned": _lane_comparison(
                lane_map["baseline"], lane_map["tuned"]
            ),
            "baselineToAgentic": _lane_comparison(
                lane_map["baseline"], lane_map["agentic"]
            ),
        },
    }
    report["reportSha256"] = _sha256_json(report)
    return report


def _verified_report(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Agent batch report must be an object: {path.name}")
    if value.get("schemaVersion") != RUN_SCHEMA_VERSION:
        raise ValueError(f"Agent batch schema is unsupported: {path.name}")
    expected = str(value.get("reportSha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "reportSha256"}
    if not expected or _sha256_json(unsigned) != expected:
        raise ValueError(f"Agent batch report hash is invalid: {path.name}")
    return {
        "path": path,
        "fileSha256": hashlib.sha256(raw).hexdigest(),
        "report": value,
    }


def _condition_identity(report: Mapping[str, object]) -> dict[str, object]:
    conditions = report.get("conditions")
    dataset = report.get("dataset")
    embedding = report.get("embedding")
    reranker = report.get("reranker")
    if not all(
        isinstance(value, Mapping)
        for value in (conditions, dataset, embedding, reranker)
    ):
        raise ValueError("Agent batch is missing condition identity")
    assert isinstance(conditions, Mapping)
    assert isinstance(dataset, Mapping)
    assert isinstance(embedding, Mapping)
    assert isinstance(reranker, Mapping)
    return {
        "sourcePreparedSha256": str(report.get("sourcePreparedSha256") or ""),
        "sourceRetrievalReportSha256": str(
            report.get("sourceRetrievalReportSha256") or ""
        ),
        "benchmarkId": str(conditions.get("benchmarkId") or ""),
        "datasetSourceSha256": str(dataset.get("sourceSha256") or ""),
        "model": str(conditions.get("model") or ""),
        "thinking": str(conditions.get("thinking") or ""),
        "laneTimeoutSeconds": float(conditions.get("laneTimeoutSeconds") or 0.0),
        "episodeCaseCount": int(conditions.get("denominator") or 0),
        "promptContractVersion": str(
            conditions.get("promptContractVersion") or ""
        ),
        "skillName": str(conditions.get("skillName") or ""),
        "skillSha256": str(conditions.get("skillSha256") or ""),
        "runtimeContractSha256": str(
            conditions.get("runtimeContractSha256") or ""
        ),
        "citationReferencePolicy": dict(
            conditions.get("citationReferencePolicy") or {}
        ),
        "answerEvaluationPolicy": dict(
            conditions.get("answerEvaluationPolicy") or {}
        ),
        "agenticRetrievalPolicy": dict(
            conditions.get("agenticRetrievalPolicy") or {}
        ),
        "permissionSha256": str(conditions.get("permissionSha256") or ""),
        "runtimeRetryPolicy": dict(conditions.get("runtimeRetryPolicy") or {}),
        "defaultRetrievalConfigSha256": str(
            report.get("defaultRetrievalConfigSha256") or ""
        ),
        "tunedRetrievalConfigSha256": str(
            report.get("tunedRetrievalConfigSha256") or ""
        ),
        "embeddingFingerprint": str(embedding.get("fingerprint") or ""),
        "rerankerFingerprint": str(reranker.get("fingerprint") or ""),
    }


def _aggregate_lane(
    lane: str,
    weighted: list[tuple[int, Mapping[str, object]]],
    *,
    total_case_count: int,
) -> dict[str, object]:
    agent_metric_rows: list[tuple[int, Mapping[str, object]]] = []
    knowledge_metric_rows: list[tuple[int, Mapping[str, object]]] = []
    total_costs: dict[str, float] = {}
    retrieval_config_hashes: set[str] = set()
    for weight, record in weighted:
        score = record.get("score")
        if not isinstance(score, Mapping):
            raise ValueError(f"Agent batch lane has no score: {lane}")
        agent_metrics = score.get("agentMetrics")
        retrieval = score.get("retrievalMetrics")
        retrieval_metrics = (
            retrieval.get("metrics") if isinstance(retrieval, Mapping) else None
        )
        if not isinstance(agent_metrics, Mapping) or not isinstance(
            retrieval_metrics, Mapping
        ):
            raise ValueError(f"Agent batch lane metrics are incomplete: {lane}")
        recall = retrieval_metrics.get("recallAtK")
        ndcg = retrieval_metrics.get("ndcgAtK")
        if not isinstance(recall, Mapping) or not isinstance(ndcg, Mapping):
            raise ValueError(f"Agent batch retrieval K metrics are incomplete: {lane}")
        flat_knowledge = {
            "mrr": float(retrieval_metrics["mrr"]),
            **{f"recallAt{k}": float(value) for k, value in recall.items()},
            **{f"ndcgAt{k}": float(value) for k, value in ndcg.items()},
        }
        agent_metric_rows.append((weight, agent_metrics))
        knowledge_metric_rows.append((weight, flat_knowledge))
        costs = record.get("costs")
        if not isinstance(costs, Mapping):
            raise ValueError(f"Agent batch lane costs are incomplete: {lane}")
        for key, value in costs.items():
            total_costs[str(key)] = total_costs.get(str(key), 0.0) + float(value)
        retrieval_config_hashes.add(str(record.get("retrievalConfigSha256") or ""))
    if len(retrieval_config_hashes) != 1 or "" in retrieval_config_hashes:
        raise ValueError(f"Agent batch lane retrieval config differs: {lane}")
    return {
        "lane": lane,
        "caseCount": total_case_count,
        "batchCount": len(weighted),
        "retrievalConfigSha256": next(iter(retrieval_config_hashes)),
        "agentMetrics": _weighted_metrics(agent_metric_rows),
        "knowledgeMetrics": _weighted_metrics(knowledge_metric_rows),
        "costs": {
            "total": total_costs,
            "meanPerBatch": {
                key: value / len(weighted) for key, value in total_costs.items()
            },
            "meanPerCase": {
                key: value / total_case_count for key, value in total_costs.items()
            },
        },
    }


def _weighted_metrics(
    rows: list[tuple[int, Mapping[str, object]]],
) -> dict[str, float]:
    keys = set(str(key) for key in rows[0][1])
    if any(set(str(key) for key in metrics) != keys for _, metrics in rows):
        raise ValueError("Agent batch metric keys differ")
    denominator = sum(weight for weight, _ in rows)
    return {
        key: sum(weight * float(metrics[key]) for weight, metrics in rows)
        / denominator
        for key in sorted(keys)
    }


def _lane_comparison(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, object]:
    return {
        "fromLane": baseline["lane"],
        "toLane": optimized["lane"],
        "agent": _metric_comparison(
            baseline["agentMetrics"], optimized["agentMetrics"]
        ),
        "knowledge": _metric_comparison(
            baseline["knowledgeMetrics"], optimized["knowledgeMetrics"]
        ),
        "costsPerCase": _metric_comparison(
            baseline["costs"]["meanPerCase"],
            optimized["costs"]["meanPerCase"],
        ),
    }


def _metric_comparison(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, object]:
    if set(baseline) != set(optimized):
        raise ValueError("aggregate comparison metric keys differ")
    result: dict[str, object] = {}
    for key in sorted(baseline):
        before = float(baseline[key])
        after = float(optimized[key])
        delta = after - before
        result[str(key)] = {
            "baseline": before,
            "optimized": after,
            "absoluteDelta": delta,
            "relativeDelta": delta / before if before else None,
        }
    return result


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
