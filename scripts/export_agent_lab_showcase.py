#!/usr/bin/env python3
"""Export an explicit public subset of current Lab experiments, never run bodies.

Usage: python3 scripts/export_agent_lab_showcase.py --output /path/to/snapshot.json
Pass --check to compare an existing snapshot without writing. The standalone
showcase consumes this file; its build does not depend on the private checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = (
    ("enterpriseops", "enterpriseops-csm.luna-prompt-adaptation-r7.v1"),
    ("rag", "enterprise-rag.luna-prompt-v4-standard-r6.v1"),
    ("cloudops", "cloudops.luna-owner-mechanism-prompt-r5.v1"),
    ("memory", "memory.maintenance-pi-model-only-20260905-r3.v1"),
)
METRICS = frozenset("""
taskSuccessCount taskCount taskSuccessRate verifierPassCount verifierCount verifierPassRate
toolCalls failedToolCalls databasesCleaned allDatabasesCleaned apiCostUsd totalTokens
exactCitationFactsCovered citationFactCount exactCitationFactCoverage agentSuccessRate
answerJudgeCorrectnessRate answerableCitationSupportRate infoNotFoundAbstentionRecall
outputProtocolRate toolSuccessRate citationHardGatePassed answerCoverage ca formalScoreProduced
fa jra top3Jra curationCases curationPassed durableRecallPassed durableRecallTotal
abstentionPassed abstentionTotal vectorCoverage legalLineagePassed bookProjectionPassed
rollbackPassed replayPassed receiptJsonValid
modelDecisionCount curationOk currentAtomCount governedCurrentAtomCount legalLineageCurrentAtomCount
retrievalCases durableCaseCount retrievalPassed projectionFresh rollbackRestoredBaseline
replayAttempted replayReusedModelRequests requestCount failedRequestCount
uncachedInputTokens cachedInputTokens outputTokens
""".split())
BOUNDARY_KEYS = (
    "candidateAware", "candidateBlind", "heldOutOpened",
    "unbiasedPromotionClaimAllowed", "standardRevisionIsModelCapabilityImprovement",
    "latencyIsKeepGate", "offlineRescoreProviderCalls", "offlineRescoreJudgeCalls",
    "offlineRescoreCandidateRuns",
    "syntheticFixture", "currentRuntimeValidation", "personalMemoryQualityMeasured",
    "installedAcceptanceEvaluated", "productionMutationPerformed", "oldCliPairReproduced",
)
PRIVATE_PATH = re.compile(r"(?:/(?:Users|Volumes|home|private|tmp)/|[A-Za-z]:\\|file://|https?://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")


def text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or PRIVATE_PATH.search(value):
        raise ValueError("Public metadata must be nonempty text without host paths, URLs or personal contact data")
    return value


def number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Public metric must be a finite number")
    return value


def metrics(values: dict) -> dict:
    return {key: number(values[key]) for key in sorted(METRICS & values.keys())}


def prose_fields(value: dict, fields: tuple[str, ...]) -> dict:
    return {key: text(value[key]) for key in fields}


def evidence(experiment: dict, repo_root: Path) -> list[dict]:
    # Traverse reference identities only, not their contents or arbitrary paths.
    refs = set()
    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidenceRefs" and isinstance(child, list):
                    refs.update(child)
                elif key in {"ref", "standardRef", "calibrationReceiptRef"} and isinstance(child, str):
                    refs.add(child)
                elif key not in {"outputExamples", "outputComparisons"}:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    for key in ("baseline", "candidate", "comparison"):
        collect(experiment[key])
    receipt_root = (repo_root / "eval/interview-metrics").resolve()
    result = []
    for ref in sorted(refs):
        path = (repo_root / ref).resolve()
        if not path.is_relative_to(receipt_root) or path.suffix != ".json":
            raise ValueError("Evidence reference outside the metrics receipt boundary")
        result.append({"file": text(path.name), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def project(document: dict, *, repo_root: Path = ROOT) -> dict:
    selected = []
    for key, experiment_id in EXPERIMENTS:
        matches = [e for e in document["experiments"] if e["id"] == experiment_id]
        if len(matches) != 1 or matches[0].get("projectionState") != "current":
            raise ValueError(f"Expected one current experiment: {experiment_id}")
        e = matches[0]
        comparison = e["comparison"]
        baseline = {"runId": text(e["baseline"]["runId"]), "metrics": metrics(e["baseline"]["metrics"])}
        candidate = {"runId": text(e["candidate"]["runId"]), "metrics": metrics(e["candidate"]["metrics"])}
        stages = []
        if key == "memory":
            if comparison.get("promptAdaptationNeeded") is not False:
                raise ValueError("Memory projection requires the measured model-only comparison")
            for stage_name, run, decision in (("sol_baseline", baseline, "baseline"), ("luna_model_only", candidate, comparison["decision"])):
                stages.append({"stage": stage_name, **run, "costUsd": run["metrics"]["apiCostUsd"], "decision": text(decision)})
        else:
            for stage in comparison["stageChain"]:
                stages.append({**prose_fields(stage, ("stage", "runId", "decision")), "metrics": metrics(stage), "costUsd": number(stage["costUsd"])})
            if len(stages) != 3:
                raise ValueError("Current staged experiments require all three measured stages")
        for run in (e["baseline"], e["candidate"]):
            if run["metrics"].get("providerBillAvailable") != 0:
                raise ValueError("This projection only represents non-billed estimates")
        before, after = baseline["metrics"]["apiCostUsd"], candidate["metrics"]["apiCostUsd"]
        if before <= 0 or after < 0:
            raise ValueError("Invalid cost comparison")
        for stage, run in ((stages[0], baseline), (stages[-1], candidate)):
            if stage["runId"] != run["runId"] or stage["costUsd"] != run["metrics"]["apiCostUsd"]:
                raise ValueError("Stage endpoints differ from baseline/candidate receipts")
            for name in stage["metrics"].keys() & run["metrics"].keys():
                if not math.isclose(stage["metrics"][name], run["metrics"][name], rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError("Stage quality differs from baseline/candidate receipts")
        boundary = comparison.get("validationBoundary", {})
        if key == "rag" and not (boundary.get("candidateAware") is True and boundary.get("candidateBlind") is False and boundary.get("unbiasedPromotionClaimAllowed") is False):
            raise ValueError("RAG r6 must retain its candidate-aware boundary")
        selected.append({
            "key": key, **prose_fields(e, ("id", "title", "businessProblem", "status")),
            "dataset": {**prose_fields(e["dataset"], ("id", "split", "unit", "manifestSha256")), "caseCount": number(e["dataset"]["caseCount"]), "heldOutConsumed": e["dataset"]["heldOutConsumed"] is True},
            "factors": [prose_fields(f, ("name", "before", "after", "reason")) for f in e["factors"]],
            "frozenControls": [prose_fields(f, ("name", "value", "reason")) for f in e["frozenControls"]],
            "hardGates": [text(gate) for gate in e["scoringContract"]["hardGates"]],
            "baseline": baseline, "candidate": candidate, "stages": stages,
            "decision": text(comparison["decision"]),
            "costAuthority": text(comparison.get("costAuthority", boundary.get("costAuthority"))),
            "costDecreasePercent": (before - after) / before * 100,
            "providerBillAvailable": False,
            "promptAdaptationNeeded": comparison.get("promptAdaptationNeeded", True),
            "validationBoundary": {k: boundary[k] for k in BOUNDARY_KEYS if k in boundary and isinstance(boundary[k], (bool, int))},
            "openGaps": [text(gap) for gap in e["openGaps"]],
            "evidence": evidence(e, repo_root),
        })
    canonical = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "schemaVersion": "paw.story.agent-lab-current.v1",
        "sourceDocument": "agent-experiments.v1.json",
        "sourceSha256": hashlib.sha256(canonical).hexdigest(),
        "sourceHashEncoding": "UTF-8 JSON; sorted keys; compact separators; ensure_ascii=false",
        "sourceGeneratedAt": text(document["generatedAt"]),
        "projection": "Explicit public metadata and aggregate metrics only; no task, answer, Gold or transcript bodies. Receipt filenames and content hashes preserve provenance without host paths.",
        "multiAgentMatchedBenefitMeasured": False,
        "experiments": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "eval/interview-metrics/agent-experiments.v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = project(json.loads(args.source.read_text(encoding="utf-8")))
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != encoded:
            raise SystemExit("Showcase snapshot differs from its current source projection")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(f"{'Verified' if args.check else 'Exported'} {len(result['experiments'])} current experiments")


if __name__ == "__main__":
    main()
