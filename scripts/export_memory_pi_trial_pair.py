#!/usr/bin/env python3
"""Project the retained Memory Pi pair into public aggregate evidence, without running it.

The source directory contains the six explicitly named receipts. No database,
transcript, credentials, or Provider is opened. --check verifies a prior export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.contracts.json_schema import validate_contract
from rag_ime.personal_memory_luna_evaluation import SYNTHETIC_PERSONAL_MEMORY_RAG_CASES

SOURCE_FILES = (
    "pair-receipts.json", "baseline-receipt.json", "candidate-receipt.json",
    "reconciled-runtime-cost.json", "source-hashes.json", "model-catalog-pricing.json",
)
CODE_FILES = (
    "rag_ime/agent_lab/memory_trial.py", "rag_ime/agent_lab/memory_pi.py",
    "rag_ime/agent_lab/golden_pi.py", "scripts/eval_personal_memory_luna.py",
    "rag_ime/personal_memory_luna_evaluation.py",
)
CONTROLS = {
    "contextProfile": "full-json-v1", "embeddingMode": "local-hashing",
    "evaluationMode": "synthetic-fixture", "fixtureCaseCount": 5,
    "personalMemoryQualityMeasured": False, "promptContract": "standard-v1",
    "provider": "openai-codex", "sourceAssetId": "", "thinkingLevel": "max",
}
METRIC_FIELDS = {
    "curation": ("sourceCount", "modelDecisionCount", "ok", "currentAtomCount",
                 "governedCurrentAtomCount", "legalLineageCurrentAtomCount"),
    "retrieval": ("caseCount", "durableCaseCount", "passed", "projectionFresh"),
    "recovery": ("rollbackPassed", "rollbackRestoredBaseline", "replayAttempted",
                 "replayPassed", "replayReusedModelRequests"),
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build_receipt(source_root: Path, *, repo_root: Path = ROOT) -> dict:
    raw = {name: (source_root / name).read_bytes() for name in SOURCE_FILES}
    sources = {name: json.loads(value) for name, value in raw.items()}
    source_hashes = sources["source-hashes.json"]
    require(set(source_hashes) == set(CODE_FILES), "unexpected source hash inventory")
    for name in CODE_FILES:
        require(hashlib.sha256((repo_root / name).read_bytes()).hexdigest() == source_hashes[name],
                "source changed since the retained run: " + name)
    pair = [sources["baseline-receipt.json"], sources["candidate-receipt.json"]]
    require(sources["pair-receipts.json"]["receipts"] == pair,
            "pair and individual receipts differ")
    cost = sources["reconciled-runtime-cost.json"]
    require(cost["schemaVersion"] == "rag-ime.agent-lab-multi-model-cost-receipt.v1"
            and cost["authority"] == "runtime_cost_reconciled_estimate"
            and cost["providerBillAvailable"] is False, "unexpected cost authority")
    require(len(cost["perModel"]) == 2 and len(cost["reconciliation"]) == 2,
            "expected two reconciled models")
    by_model = {r["pricingIdentity"]["model"]: r for r in cost["perModel"]}
    reconciled = {r["model"]: r for r in cost["reconciliation"]}
    require(set(by_model) == set(reconciled) == {"gpt-5.6-sol", "gpt-5.6-luna"},
            "unexpected model pair")
    projected = {}
    for label, model, raw_side in zip(("baseline", "candidate"),
                                     ("gpt-5.6-sol", "gpt-5.6-luna"), pair):
        job, receipt, reconciliation = raw_side["job"], by_model[model], reconciled[model]
        require(raw_side["label"] == label and raw_side["model"] == model,
                "side identity differs")
        require(job["publicSpec"] == {**CONTROLS, "model": model}, "pair controls differ")
        require(job["state"] == "completed" and job["error"] in (None, "", {})
                and job["cancelRequested"] is False, "Trial did not complete")
        result = job["result"]
        require(result["status"] == "completed" and result["qualityVerdict"] == "pass"
                and result["caseCount"] == 5, "lifecycle gate did not pass")
        for field in ("personalMemoryQualityMeasured", "heldOutEvaluated",
                      "productionMutationPerformed", "installedAcceptanceEvaluated"):
            require(result["signals"][field] is False, "unexpected evaluation boundary")
        metrics = {section: {key: result["metrics"][section][key] for key in fields}
                   for section, fields in METRIC_FIELDS.items()}
        require(all(type(v) in (int, bool) for section in metrics.values() for v in section.values()),
                "missing aggregate metric")
        require(metrics["curation"]["ok"] is True and metrics["retrieval"]["passed"] is True
                and all(metrics["recovery"].values()), "incomplete lifecycle or recovery")
        turns = sorted({(s["sessionId"], s["turnId"]) for s in job["sessions"] if s["turnId"]})
        validate_contract(receipt, "agent-lab-cost-receipt.v1.json")
        require(canonical_hash({k: v for k, v in receipt.items() if k != "receiptSha256"})
                == receipt["receiptSha256"], "cost receipt hash differs")
        require(receipt["authority"] == "runtime_cost_reconciled"
                and receipt["billing"]["status"] == "not_provided", "cost is not reconciled")
        require(reconciliation["usageStatus"] == "matched"
                and reconciliation["databaseUsage"] == reconciliation["transcriptUsage"]
                and reconciliation["failedRequestCount"] == 0
                and reconciliation["requestCount"] == len(turns) == 2
                and receipt["runtimeCostReceipt"]["requestCount"] == 2,
                "request or usage reconciliation differs")
        amount = Decimal(receipt["estimate"]["totalCostUsd"])
        require(amount == Decimal(receipt["runtimeCostReceipt"]["reportedCostUsd"]["total"])
                == Decimal(str(result["cost"]["estimatedCostUsd"])), "cost totals differ")
        require(result["cost"]["available"] is True and result["cost"]["requestCount"] == 2,
                "Trial cost is incomplete")
        report_ref = "memory-trial:" + hashlib.sha256(job["jobId"].encode()).hexdigest() + ":report"
        require(result["evidence"]["reportRef"] == report_ref, "report identity differs")
        projected[label] = {
            "model": model, "trialId": job["jobId"], "reportRef": report_ref,
            "sourceReceipt": f"{label}-receipt.json", "publicSpec": job["publicSpec"],
            "configSha256": canonical_hash(job["publicSpec"]), "state": "completed",
            "qualityVerdict": "pass", "createdAtMs": job["createdAtMs"],
            "completedAtMs": job["updatedAtMs"], "caseCount": 5, "metrics": metrics,
            "runtimeRequestCount": len(turns), "failedRequestCount": 0,
            "sessionBindingsSha256": canonical_hash(turns),
            "runtimeCostReceiptSha256": receipt["receiptSha256"],
            "estimatedCostUsd": str(amount),
        }
    aggregate = cost["aggregate"]
    total = sum(Decimal(side["estimatedCostUsd"]) for side in projected.values())
    require(aggregate["requestCount"] == 4 and aggregate["failedRequestCount"] == 0
            and aggregate["modelCount"] == 2 and Decimal(aggregate["totalCostUsd"]) == total,
            "pair aggregate differs")
    before, after = (Decimal(projected[side]["estimatedCostUsd"]) for side in ("baseline", "candidate"))
    catalog = sources["model-catalog-pricing.json"]
    require(catalog["source"] == "Pi frozen build catalog", "unexpected pricing catalog source")
    catalog_models = []
    for model in catalog["gpt"]["models"]:
        require(model["id"] in by_model, "unexpected catalog model")
        rates = by_model[model["id"]]["pricingIdentity"]["rates"]
        for field, rate_field in (("input", "uncachedInputUsd"), ("output", "outputUsd"),
                                  ("cacheRead", "cachedInputUsd")):
            require(Decimal(str(model["cost"][field])) == Decimal(rates[rate_field]),
                    "catalog and reconciled pricing differ")
        catalog_models.append({"id": model["id"], "provider": model["provider"],
            "cost": {key: model["cost"][key] for key in ("input", "output", "cacheRead", "cacheWrite")},
            "tierInputTokensAbove": [tier["inputTokensAbove"] for tier in model["cost"].get("tiers", [])]})
    return {
        "schemaVersion": "paw.memory-pi-trial-pair-evidence.v1",
        "runId": "memory-pi-current-pair-20260905-r3",
        "scope": "current-runtime synthetic validation through Pi Sessions",
        "publicSafe": True,
        "sourceFiles": [{"file": name, "sha256": hashlib.sha256(raw[name]).hexdigest()} for name in SOURCE_FILES],
        "sourceCodeSha256": source_hashes,
        "fixture": {"caseCount": 5, "durableCaseCount": 4, "nonMemoryControlCount": 1,
            "sha256": canonical_hash(SYNTHETIC_PERSONAL_MEMORY_RAG_CASES),
            "hashEncoding": "Trial prepare canonical UTF-8 JSON of SYNTHETIC_PERSONAL_MEMORY_RAG_CASES; sorted keys; compact separators; ensure_ascii=false"},
        "frozenControls": CONTROLS,
        **projected,
        "runtimeCostReceipt": cost,
        "pricingCatalog": {"source": catalog["source"], "sourceSha256": catalog["sourceSha256"],
                           "models": catalog_models},
        "comparison": {"changedFactor": "model", "qualityGatesEqual": True,
            "estimatedCostUsdBefore": str(before), "estimatedCostUsdAfter": str(after),
            "estimatedCostUsdDelta": str(after - before),
            "costDecreasePercent": str((before - after) / before * 100)},
        "boundaries": {"syntheticFixture": True, "heldOutEvaluated": False,
            "personalMemoryQualityMeasured": False, "productionMutationPerformed": False,
            "installedAcceptanceEvaluated": False, "providerBillAvailable": False,
            "oldCliPairReproduced": False, "latencyIsKeepGate": False,
            "repeatedTrialsPerModel": 1},
        "notes": ["A new Pi / standard-v1 pair; the retained CLI / concise-json-v1 pair is a different experiment.",
            "Counts, aggregate lifecycle gates and pricing estimates are retained; no per-case answers or personal memory bodies are exported.",
            "Pricing originates in the frozen Pi build catalog; the pricing URL in its receipt is a source label, not an independently verified provider bill."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build_receipt(args.source_root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.check:
        require(args.output.read_text(encoding="utf-8") == encoded, "export differs from retained receipts")
    else:
        args.output.write_text(encoded, encoding="utf-8")
    print("Verified Memory Pi pair: 5 synthetic fixtures, 4 requests, 0 failures; no Provider call")


if __name__ == "__main__":
    main()
