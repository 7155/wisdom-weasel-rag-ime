#!/usr/bin/env python3
"""Build a public-safe, three-namespace RAG interview scorecard.

The scorecard intentionally keeps Knowledge, personal Memory and Agent
metrics separate.  It consumes local reports, verifies their content hashes,
and refuses to turn a failed/development-only Agent report into a headline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "rag-ime.rag-interview-scorecard.v1"
_RETRIEVAL_SCHEMA_VERSIONS = frozenset(
    {
        "rag-ime.rag-retrieval-run.v1",
        "rag-ime.rag-retrieval-run.v2",
        "rag-ime.longmemeval-memory-retrieval-run.v2",
    }
)
_AGENT_SCHEMA_VERSION = "rag-ime.rag-agent-ablation-run.v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-report", type=Path, required=True)
    parser.add_argument("--memory-report", type=Path, required=True)
    parser.add_argument(
        "--agent-report",
        type=Path,
        help="Optional formal four-lane Agent report; failed/development reports stay pending.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    scorecard = build_scorecard(
        knowledge_report=args.knowledge_report.expanduser().resolve(strict=True),
        memory_report=args.memory_report.expanduser().resolve(strict=True),
        agent_report=(
            args.agent_report.expanduser().resolve(strict=True)
            if args.agent_report is not None
            else None
        ),
    )
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "reportSha256": scorecard["scorecardSha256"],
                "knowledgeEligible": scorecard["knowledge"]["eligible"],
                "memoryEligible": scorecard["memory"]["eligible"],
                "agentStatus": scorecard["agent"]["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def build_scorecard(
    *,
    knowledge_report: Path,
    memory_report: Path,
    agent_report: Path | None = None,
) -> dict[str, Any]:
    knowledge = _retrieval_namespace(
        name="knowledge",
        path=knowledge_report,
        baseline_names=("productionLexicalFloor", "baseline"),
        optimized_name="tuned",
    )
    memory = _retrieval_namespace(
        name="memory",
        path=memory_report,
        baseline_names=("baseline", "productionLexicalFloor"),
        optimized_name="tuned",
        slice_aliases={
            "temporalReasoning": "temporal-reasoning",
            "updateOrConflict": "knowledge-update",
        },
    )
    memory_raw = _read_report(memory_report)
    abstention = memory_raw.get("abstention")
    if isinstance(abstention, Mapping):
        memory["abstention"] = _public_abstention(abstention)

    agent = _agent_namespace(agent_report)
    scorecard: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "localOnly": True,
        "uploaded": False,
        "metricNamespaces": ["knowledge", "memory", "agent"],
        "knowledge": knowledge,
        "memory": memory,
        "agent": agent,
        "fourLaneContract": {
            "lanes": ["baseline", "skill", "tuned", "agentic"],
            "sameModel": "openai-codex/gpt-5.6-luna",
            "samePermissions": True,
            "heldOutLabelsVisibleToAgent": False,
            "formalEvidenceAvailable": agent["status"] == "formal",
        },
        "safety": {
            "memoryKnowledgeSeparated": True,
            "noCombinedHeadline": True,
            "failedAgentRunsExcluded": True,
        },
    }
    scorecard["scorecardSha256"] = _sha256_json(scorecard)
    return scorecard


def _retrieval_namespace(
    *,
    name: str,
    path: Path,
    baseline_names: tuple[str, ...],
    optimized_name: str,
    slice_aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    report = _read_report(path)
    if report.get("schemaVersion") not in _RETRIEVAL_SCHEMA_VERSIONS:
        raise ValueError(f"{name} report schema is not a retrieval report: {path.name}")
    held_out = report.get("heldOut")
    if not isinstance(held_out, Mapping):
        raise ValueError(f"{name} report has no heldOut section: {path.name}")
    baseline_name = next((candidate for candidate in baseline_names if candidate in held_out), "")
    baseline = held_out.get(baseline_name)
    optimized = held_out.get(optimized_name)
    if not isinstance(baseline, Mapping) or not isinstance(optimized, Mapping):
        raise ValueError(f"{name} report lacks baseline/tuned metrics: {path.name}")
    baseline_metrics = _metrics(baseline)
    optimized_metrics = _metrics(optimized)
    metrics = {
        key: _delta(baseline_metrics[key], optimized_metrics[key])
        for key in sorted(set(baseline_metrics) & set(optimized_metrics))
    }
    slices = _slice_deltas(
        baseline,
        optimized,
        aliases=slice_aliases or {},
    )
    eligible = bool(
        report.get("status") == "completed"
        and report.get("localOnly") is True
        and report.get("uploaded") is False
        and _hard_gates_pass(report)
    )
    result: dict[str, Any] = {
        "system": name,
        "eligible": eligible,
        "baselineLabel": baseline_name,
        "optimizedLabel": optimized_name,
        "configs": {
            "baseline": dict(baseline.get("config") or {}),
            "optimized": dict(optimized.get("config") or {}),
        },
        "metrics": metrics,
        "caseCount": int((baseline.get("metrics") or {}).get("queryCount") or 0),
        "source": _source_receipt(path, report),
        "reason": "" if eligible else "retrieval report hard gates/status are not formally eligible",
    }
    if slices:
        result["slices"] = slices
    return result


def _slice_deltas(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
    *,
    aliases: Mapping[str, str],
) -> dict[str, Any]:
    if not aliases:
        return {}
    baseline_slices = baseline.get("perSlice")
    optimized_slices = optimized.get("perSlice")
    if not isinstance(baseline_slices, Mapping) or not isinstance(optimized_slices, Mapping):
        return {}
    result: dict[str, Any] = {}
    for public_name, source_name in aliases.items():
        baseline_slice = baseline_slices.get(source_name)
        optimized_slice = optimized_slices.get(source_name)
        if not isinstance(baseline_slice, Mapping) or not isinstance(optimized_slice, Mapping):
            continue
        baseline_metrics = _metrics_from_metric_payload(_metric_payload(baseline_slice))
        optimized_metrics = _metrics_from_metric_payload(_metric_payload(optimized_slice))
        common = sorted(set(baseline_metrics) & set(optimized_metrics))
        if not common:
            continue
        result[public_name] = {
            "sourceSlice": source_name,
            "caseCount": int(baseline_slice.get("queryCount") or 0),
            "metrics": {
                key: _delta(baseline_metrics[key], optimized_metrics[key])
                for key in common
            },
        }
    return result


def _agent_namespace(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "system": "agent",
            "status": "pending_formal_run",
            "eligible": False,
            "metrics": {},
            "reason": "No formal four-lane Luna report supplied.",
        }
    report = _read_report(path)
    if report.get("schemaVersion") != _AGENT_SCHEMA_VERSION:
        raise ValueError(f"agent report schema is unsupported: {path.name}")
    formal = bool(
        report.get("passed") is True
        and report.get("formalAcceptanceEligible") is True
        and report.get("localOnly") is True
        and report.get("uploaded") is False
        and report.get("cleanupPassed") is True
    )
    result: dict[str, Any] = {
        "system": "agent",
        "status": "formal" if formal else "ineligible_development_or_failure",
        "eligible": formal,
        "metrics": {},
        "source": _source_receipt(path, report),
        "reason": "" if formal else str(report.get("failure") or "formal hard gates not passed"),
    }
    if formal:
        result["lanes"] = _public_agent_lanes(report)
    return result


def _public_agent_lanes(report: Mapping[str, object]) -> dict[str, Any]:
    lanes: dict[str, Any] = {}
    for item in report.get("lanes") or []:
        if not isinstance(item, Mapping):
            continue
        lane = str(item.get("lane") or "")
        metrics = item.get("metrics")
        if lane and isinstance(metrics, Mapping):
            lanes[lane] = dict(metrics)
    return lanes


def _public_abstention(value: Mapping[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    held_out = value.get("heldOut")
    if isinstance(held_out, Mapping):
        for key in (
            "abstentionF1",
            "abstentionPrecision",
            "abstentionRecall",
            "balancedAccuracy",
            "accuracy",
        ):
            if key in held_out:
                result[key] = held_out[key]
    return result


def _metrics(section: Mapping[str, object]) -> dict[str, float]:
    wrapper = section.get("metrics")
    metrics = wrapper.get("metrics") if isinstance(wrapper, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise ValueError("retrieval section has no metrics.metrics")
    return _metrics_from_metric_payload(metrics)


def _metric_payload(section: Mapping[str, object]) -> Mapping[str, object]:
    nested = section.get("metrics")
    return nested if isinstance(nested, Mapping) else section


def _metrics_from_metric_payload(metrics: Mapping[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in ("mrr",):
        if key in metrics:
            result[key] = float(metrics[key])
    for group, prefix in (("recallAtK", "recallAt"), ("ndcgAtK", "ndcgAt")):
        values = metrics.get(group)
        if isinstance(values, Mapping):
            for cutoff, value in values.items():
                result[f"{prefix}{cutoff}"] = float(value)
    return result


def _delta(baseline: float, optimized: float) -> dict[str, float]:
    absolute = float(optimized) - float(baseline)
    relative = absolute / float(baseline) if float(baseline) != 0.0 else 0.0
    return {
        "baseline": float(baseline),
        "optimized": float(optimized),
        "absoluteDelta": absolute,
        "relativeDelta": relative,
    }


def _read_report(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report must be a JSON object: {path.name}")
    expected = str(value.get("reportSha256") or "")
    if expected:
        unsigned = {key: item for key, item in value.items() if key != "reportSha256"}
        if _sha256_json(unsigned) != expected:
            raise ValueError(f"report hash is invalid: {path.name}")
    return value


def _source_receipt(path: Path, report: Mapping[str, object]) -> dict[str, str]:
    raw = path.read_bytes()
    return {
        "fileName": path.name,
        "fileSha256": hashlib.sha256(raw).hexdigest(),
        "reportSha256": str(report.get("reportSha256") or ""),
    }


def _hard_gates_pass(report: Mapping[str, object]) -> bool:
    gates = report.get("hardGates")
    if isinstance(gates, Mapping):
        return all(value is True for value in gates.values())
    return True


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
