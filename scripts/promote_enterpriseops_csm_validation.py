#!/usr/bin/env python3
"""Authorize exactly one EnterpriseOps Suite v2 Held-out evaluation.

This command compares already-persisted Validation reports only. It never
starts a Runtime or contacts the Provider. The resulting receipt is the sole
authorization input accepted by the Held-out runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_enterpriseops_csm_eval import ENTERPRISEOPS_SUITE_V2_REVISION


class PromotionError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_report(path: str | Path) -> dict[str, object]:
    report_path = Path(path).expanduser().resolve(strict=True)
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise PromotionError(f"report is not an object: {report_path}")
    if raw.get("schemaVersion") != "paw.enterpriseops-csm-eval.v1":
        raise PromotionError("report schema is unsupported")
    if raw.get("status") != "completed" or raw.get("split") != "validation":
        raise PromotionError("promotion requires completed Validation reports")
    if not isinstance(raw.get("manifest"), Mapping) or not isinstance(raw.get("evaluationContract"), Mapping):
        raise PromotionError("report contract is incomplete")
    if not isinstance(raw.get("lane"), Mapping):
        raise PromotionError("report lane is missing")
    report_hash = str(raw.get("reportSha256") or "")
    report_payload = {key: value for key, value in raw.items() if key != "reportSha256"}
    if not report_hash or report_hash != _sha256(report_payload):
        raise PromotionError("Validation report hash is invalid")
    return dict(raw)


def _binding(report: Mapping[str, object]) -> dict[str, object]:
    manifest = _mapping(report, "manifest")
    contract = _mapping(report, "evaluationContract")
    lane = _mapping(report, "lane")
    return {
        "suiteRevision": str(manifest.get("suiteRevision") or contract.get("suiteRevision") or ""),
        "overlaySha256": str(manifest.get("overlaySha256") or contract.get("overlaySha256") or ""),
        "validationTaskManifestSha256": str(manifest.get("manifestSha256") or contract.get("taskManifestSha256") or ""),
        "taskIds": list(manifest.get("taskIds") or []),
        "runtimeIdentitySha256": str(contract.get("runtimeIdentitySha256") or ""),
        "toolCatalogSha256": str(contract.get("toolCatalogSha256") or ""),
        "runnerSha256": str(contract.get("runnerSha256") or ""),
        "provider": str(contract.get("provider") or ""),
        "model": str(contract.get("model") or ""),
        "thinking": str(contract.get("thinking") or ""),
        "workflowProfile": str(lane.get("workflowProfile") or ""),
    }


def promote_validation(
    baseline_path: str | Path,
    candidate_path: str | Path,
    output_path: str | Path,
    *,
    authorize_held_out_once: bool,
) -> dict[str, object]:
    if not authorize_held_out_once:
        raise PromotionError("explicit --authorize-held-out-once is required")
    baseline = _read_report(baseline_path)
    candidate = _read_report(candidate_path)
    baseline_binding = _binding(baseline)
    candidate_binding = _binding(candidate)
    for key in (
        "suiteRevision",
        "overlaySha256",
        "validationTaskManifestSha256",
        "taskIds",
        "runtimeIdentitySha256",
        "toolCatalogSha256",
        "runnerSha256",
        "provider",
        "model",
        "thinking",
    ):
        if baseline_binding[key] != candidate_binding[key]:
            raise PromotionError(f"baseline/candidate binding mismatch: {key}")
    if baseline_binding["suiteRevision"] != ENTERPRISEOPS_SUITE_V2_REVISION:
        raise PromotionError("promotion requires Suite v2")
    if not baseline_binding["overlaySha256"] or not baseline_binding["validationTaskManifestSha256"]:
        raise PromotionError("promotion binding hashes are missing")
    if len(candidate_binding["taskIds"]) != 3:
        raise PromotionError("promotion requires the three-task Validation manifest")

    baseline_lane = _mapping(baseline, "lane")
    candidate_lane = _mapping(candidate, "lane")
    candidate_task_count = _int(candidate_lane, "taskCount")
    candidate_success = _int(candidate_lane, "taskSuccessCount")
    candidate_verifier_count = _int(candidate_lane, "verifierCount")
    candidate_verifier_pass = _int(candidate_lane, "verifierPassCount")
    if (
        candidate_task_count != 3
        or candidate_success != 3
        or candidate_verifier_count != 31
        or candidate_verifier_pass != 31
        or _int(candidate_lane, "failedToolCalls") != 0
        or candidate_lane.get("allDatabasesCleaned") is not True
    ):
        raise PromotionError("candidate does not satisfy the full Validation promotion gate")
    if candidate_success < _int(baseline_lane, "taskSuccessCount") + 1:
        raise PromotionError("candidate must complete at least one more Validation task")
    if str(candidate_binding["workflowProfile"]) == "baseline-v1":
        raise PromotionError("candidate workflow profile is not an optimization candidate")
    if str(baseline_binding["workflowProfile"]) != "baseline-v1":
        raise PromotionError("baseline workflow profile must be baseline-v1")

    baseline_report_hash = str(baseline.get("reportSha256") or "")
    candidate_report_hash = str(candidate.get("reportSha256") or "")
    if not baseline_report_hash or not candidate_report_hash:
        raise PromotionError("Validation report hashes are required")
    receipt: dict[str, object] = {
        "schemaVersion": "paw.enterpriseops-csm-validation-promotion.v1",
        "status": "authorized",
        "heldOutAuthorized": True,
        "authorization": "one-shot",
        "baseline": {
            "reportSha256": baseline_report_hash,
            "workflowProfile": baseline_binding["workflowProfile"],
            "taskSuccessCount": _int(baseline_lane, "taskSuccessCount"),
            "verifierPassCount": _int(baseline_lane, "verifierPassCount"),
        },
        "winner": {
            **candidate_binding,
            "reportSha256": candidate_report_hash,
            "taskSuccessCount": candidate_success,
            "verifierPassCount": candidate_verifier_pass,
            "toolCalls": _int(candidate_lane, "toolCalls"),
            "failedToolCalls": _int(candidate_lane, "failedToolCalls"),
            "allDatabasesCleaned": True,
        },
        "comparison": {
            "taskSuccessDelta": candidate_success - _int(baseline_lane, "taskSuccessCount"),
            "verifierPassDelta": candidate_verifier_pass - _int(baseline_lane, "verifierPassCount"),
        },
    }
    receipt["receiptSha256"] = _sha256(receipt)
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_canonical(receipt) + "\n")
    except FileExistsError as exc:
        raise PromotionError("promotion receipt already exists") from exc
    return receipt


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise PromotionError(f"report field is not an object: {key}")
    return nested


def _int(value: Mapping[str, object], key: str) -> int:
    raw = value.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise PromotionError(f"report metric is missing: {key}")
    return int(raw)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorize-held-out-once", action="store_true")
    args = parser.parse_args(argv)
    promote_validation(
        args.baseline,
        args.candidate,
        args.output,
        authorize_held_out_once=args.authorize_held_out_once,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
