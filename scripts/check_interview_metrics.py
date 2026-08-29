#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = "paw.interview-metrics-ledger.v1"
EVIDENCE_LEVELS = ("E1", "E2", "E3", "E4", "E5", "E6")
CLAIMABLE_STATUSES = frozenset({"headline", "supporting", "diagnostic"})
ALLOWED_STATUSES = CLAIMABLE_STATUSES | frozenset({"blocked", "target"})
ALLOWED_MEASUREMENT_KINDS = frozenset(
    {"deterministic", "ai_estimate", "mixed", "status"}
)
ALLOWED_RUN_OUTCOMES = frozenset({"passed", "failed", "interrupted", "blocked"})


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _repo_ref_path(ref: str, repo_root: Path) -> Path | None:
    if ref.startswith(("http://", "https://")):
        return None
    raw_path = ref.split("#", 1)[0].strip()
    if not raw_path:
        return None
    return repo_root / raw_path


def validate_interview_metrics(
    payload: Mapping[str, object], *, repo_root: Path | None = None
) -> list[str]:
    errors: list[str] = []
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    source_revision = payload.get("sourceRevision")
    if not _non_empty_text(source_revision):
        errors.append("sourceRevision is required")
    elif repo_root is not None:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(source_revision), "HEAD"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            errors.append(f"sourceRevision is not an ancestor of HEAD: {source_revision}")

    levels = payload.get("evidenceLevels")
    if levels != list(EVIDENCE_LEVELS):
        errors.append("evidenceLevels must be exactly E1 through E6")

    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        errors.append("metrics must be a list")
        metrics = []
    metric_ids: set[str] = set()
    for raw_metric in metrics:
        metric = _mapping(raw_metric)
        metric_id = str(metric.get("id") or "").strip() or "<missing-metric-id>"
        if metric_id in metric_ids:
            errors.append(f"duplicate metric id: {metric_id}")
        metric_ids.add(metric_id)

        status = str(metric.get("status") or "")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{metric_id}: unsupported status: {status}")
        level = str(metric.get("evidenceLevel") or "")
        if level not in EVIDENCE_LEVELS:
            errors.append(f"{metric_id}: unsupported evidenceLevel: {level}")
        measurement_kind = str(metric.get("measurementKind") or "")
        if measurement_kind not in ALLOWED_MEASUREMENT_KINDS:
            errors.append(
                f"{metric_id}: unsupported measurementKind: {measurement_kind}"
            )
        if measurement_kind == "ai_estimate" and metric.get("reportedAs") == "deterministic":
            errors.append(
                f"{metric_id}: ai_estimate must not be reportedAs deterministic"
            )

        if status not in CLAIMABLE_STATUSES:
            continue
        values = metric.get("values")
        if not isinstance(values, dict) or not values:
            errors.append(f"{metric_id}: values must be a non-empty object")
        sample = _mapping(metric.get("sample"))
        count = sample.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            errors.append(f"{metric_id}: sample.count must be a positive integer")
        if not _non_empty_text(sample.get("unit")):
            errors.append(f"{metric_id}: sample.unit is required")
        reproduction = _mapping(metric.get("reproduction"))
        if not _non_empty_text(reproduction.get("command")):
            errors.append(f"{metric_id}: reproduction.command is required")
        evidence_refs = metric.get("evidenceRefs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"{metric_id}: evidenceRefs must be non-empty")
            evidence_refs = []
        claim = _mapping(metric.get("claim"))
        if not _non_empty_text(claim.get("allowed")):
            errors.append(f"{metric_id}: claim.allowed is required")
        if not _non_empty_text(claim.get("forbidden")):
            errors.append(f"{metric_id}: claim.forbidden is required")
        limitations = metric.get("limitations")
        if not isinstance(limitations, list):
            errors.append(f"{metric_id}: limitations must be a list")
        if repo_root is not None:
            for raw_ref in evidence_refs:
                if not _non_empty_text(raw_ref):
                    errors.append(f"{metric_id}: evidenceRefs contains an empty value")
                    continue
                ref_path = _repo_ref_path(str(raw_ref), repo_root)
                if ref_path is not None and not ref_path.exists():
                    errors.append(f"{metric_id}: evidence ref does not exist: {raw_ref}")

    runs = payload.get("runs")
    if not isinstance(runs, list):
        errors.append("runs must be a list")
        runs = []
    run_ids: set[str] = set()
    for raw_run in runs:
        run = _mapping(raw_run)
        run_id = str(run.get("id") or "").strip() or "<missing-run-id>"
        if run_id in run_ids:
            errors.append(f"duplicate run id: {run_id}")
        run_ids.add(run_id)
        outcome = str(run.get("outcome") or "")
        if outcome not in ALLOWED_RUN_OUTCOMES:
            errors.append(f"{run_id}: unsupported run outcome: {outcome}")
        if not _non_empty_text(run.get("command")):
            errors.append(f"{run_id}: command is required")
        if not _non_empty_text(run.get("measuredAt")):
            errors.append(f"{run_id}: measuredAt is required")
        if not _non_empty_text(run.get("summary")):
            errors.append(f"{run_id}: summary is required")

    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        errors.append("datasets must be a list")
        datasets = []
    dataset_ids: set[str] = set()
    for raw_dataset in datasets:
        dataset = _mapping(raw_dataset)
        dataset_id = str(dataset.get("id") or "").strip() or "<missing-dataset-id>"
        if dataset_id in dataset_ids:
            errors.append(f"duplicate dataset id: {dataset_id}")
        dataset_ids.add(dataset_id)
        if not _non_empty_text(dataset.get("domain")):
            errors.append(f"{dataset_id}: domain is required")
        if not _non_empty_text(dataset.get("sourceUrl")):
            errors.append(f"{dataset_id}: sourceUrl is required")
        if not _non_empty_text(dataset.get("localStatus")):
            errors.append(f"{dataset_id}: localStatus is required")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the evidence and claim boundaries in the PAW interview metrics ledger."
    )
    parser.add_argument(
        "--ledger",
        default="eval/interview-metrics/evidence-ledger.v1.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    ledger_path = Path(args.ledger).resolve()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("interview metrics ledger must contain a JSON object")
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate_interview_metrics(payload, repo_root=repo_root)
    report = {
        "schemaVersion": "paw.interview-metrics-check.v1",
        "ok": not errors,
        "ledgerPath": str(ledger_path),
        "metricCount": len(payload.get("metrics") or []),
        "runCount": len(payload.get("runs") or []),
        "datasetCount": len(payload.get("datasets") or []),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("OK" if report["ok"] else "FAILED")
        for error in errors:
            print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
