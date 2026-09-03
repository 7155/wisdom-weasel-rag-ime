#!/usr/bin/env python3
"""Deterministically score PAW Trace closed-loop historical replay predictions.

The public manifest is a post-evaluation UI projection. The scorer accepts gold
only through an explicit host-private input and never copies gold labels or the
gold path into its public result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT / "eval" / "trace-agent" / "closed-loop-v1" / "public-manifest.json"
)
MANIFEST_SCHEMA = (
    ROOT
    / "eval"
    / "trace-agent"
    / "closed-loop-v1"
    / "public-manifest.schema.json"
)

_GOLD_ROOT_FIELDS = frozenset({"schemaVersion", "suiteId", "cases"})
_GOLD_CASE_FIELDS = frozenset(
    {
        "caseId",
        "acceptableFirstFailingSpanIds",
        "rootOwner",
        "targetLayer",
        "requiredEvidenceGroups",
        "validEvidenceIds",
        "supportedConclusionCodes",
        "repair",
    }
)
_REPAIR_FIELDS = frozenset({"eligible", "successful", "regression", "decision"})
_PREDICTION_ROOT_FIELDS = frozenset({"schemaVersion", "suiteId", "cases"})
_PREDICTION_CASE_FIELDS = frozenset(
    {
        "caseId",
        "firstFailingSpanId",
        "rootOwner",
        "targetLayer",
        "evidenceRefs",
        "conclusionCodes",
        "repairAssessment",
    }
)
_DECISIONS = frozenset({"Keep", "Reject", "Rollback"})
_LAYERS = frozenset({"system_prompt", "tool", "workflow", "skill"})


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_object(path: str | Path, *, label: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _required_text(value: object, *, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{label} must be non-empty text")
    return result


def _strict_fields(value: Mapping[str, object], expected: frozenset[str], *, label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"{label} fields drifted; missing={missing}, unexpected={unexpected}"
        )


def _string_list(value: object, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    result = [_required_text(item, label=f"{label} item") for item in value]
    if not allow_empty and not result:
        raise ValueError(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{label} must contain unique values")
    return result


def _case_map(value: object, *, label: str) -> dict[str, dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} cases must be a non-empty array")
    result: dict[str, dict[str, object]] = {}
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{label} case must be an object")
        item = dict(raw)
        case_id = _required_text(item.get("caseId"), label=f"{label} caseId")
        if case_id in result:
            raise ValueError(f"{label} case IDs must be unique")
        result[case_id] = item
    return result


def validate_public_manifest(manifest: Mapping[str, object]) -> None:
    schema = _read_object(MANIFEST_SCHEMA, label="public manifest schema")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(manifest)),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(item) for item in first.absolute_path) or "<root>"
        raise ValueError(f"public manifest is invalid at {location}: {first.message}")
    if manifest.get("notAgentInput") is not True:
        raise ValueError("public manifest must be marked notAgentInput")


def _validate_gold(gold: Mapping[str, object]) -> dict[str, dict[str, object]]:
    _strict_fields(gold, _GOLD_ROOT_FIELDS, label="host gold")
    if gold.get("schemaVersion") != "paw.trace-closed-loop-host-gold.v1":
        raise ValueError("host gold schemaVersion is unsupported")
    cases = _case_map(gold.get("cases"), label="host gold")
    for case_id, case in cases.items():
        _strict_fields(case, _GOLD_CASE_FIELDS, label=f"host gold {case_id}")
        _string_list(
            case.get("acceptableFirstFailingSpanIds"),
            label=f"host gold {case_id} acceptable spans",
        )
        _required_text(case.get("rootOwner"), label=f"host gold {case_id} rootOwner")
        if case.get("targetLayer") not in _LAYERS:
            raise ValueError(f"host gold {case_id} targetLayer is unsupported")
        valid_evidence = set(
            _string_list(
                case.get("validEvidenceIds"),
                label=f"host gold {case_id} valid evidence",
            )
        )
        groups = case.get("requiredEvidenceGroups")
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"host gold {case_id} evidence groups must not be empty")
        for index, group in enumerate(groups, start=1):
            alternatives = set(
                _string_list(
                    group,
                    label=f"host gold {case_id} evidence group {index}",
                )
            )
            if not alternatives <= valid_evidence:
                raise ValueError(
                    f"host gold {case_id} evidence group contains an invalid evidence ID"
                )
        _string_list(
            case.get("supportedConclusionCodes"),
            label=f"host gold {case_id} supported conclusions",
            allow_empty=True,
        )
        repair = case.get("repair")
        if not isinstance(repair, Mapping):
            raise ValueError(f"host gold {case_id} repair must be an object")
        _strict_fields(repair, _REPAIR_FIELDS, label=f"host gold {case_id} repair")
        for field in ("eligible", "successful", "regression"):
            if not isinstance(repair.get(field), bool):
                raise ValueError(f"host gold {case_id} repair {field} must be boolean")
        if repair.get("decision") not in _DECISIONS:
            raise ValueError(f"host gold {case_id} repair decision is unsupported")
    return cases


def _validate_predictions(
    predictions: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    _strict_fields(predictions, _PREDICTION_ROOT_FIELDS, label="predictions")
    if predictions.get("schemaVersion") != "paw.trace-closed-loop-predictions.v1":
        raise ValueError("predictions schemaVersion is unsupported")
    cases = _case_map(predictions.get("cases"), label="predictions")
    for case_id, case in cases.items():
        _strict_fields(
            case,
            _PREDICTION_CASE_FIELDS,
            label=f"predictions {case_id}",
        )
        for field in ("firstFailingSpanId", "rootOwner"):
            _required_text(case.get(field), label=f"predictions {case_id} {field}")
        if case.get("targetLayer") not in _LAYERS:
            raise ValueError(f"predictions {case_id} targetLayer is unsupported")
        _string_list(
            case.get("evidenceRefs"),
            label=f"predictions {case_id} evidenceRefs",
            allow_empty=True,
        )
        _string_list(
            case.get("conclusionCodes"),
            label=f"predictions {case_id} conclusionCodes",
            allow_empty=True,
        )
        repair = case.get("repairAssessment")
        if not isinstance(repair, Mapping):
            raise ValueError(f"predictions {case_id} repairAssessment must be an object")
        _strict_fields(
            repair,
            frozenset({"successful", "regression", "decision"}),
            label=f"predictions {case_id} repairAssessment",
        )
        for field in ("successful", "regression"):
            if not isinstance(repair.get(field), bool):
                raise ValueError(
                    f"predictions {case_id} repairAssessment {field} must be boolean"
                )
        if repair.get("decision") not in _DECISIONS:
            raise ValueError(f"predictions {case_id} decision is unsupported")
    return cases


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score_trace_closed_loop(
    manifest: Mapping[str, object],
    host_gold: Mapping[str, object],
    predictions: Mapping[str, object],
) -> dict[str, object]:
    """Score predictions without publishing host-private labels."""

    validate_public_manifest(manifest)
    suite_id = _required_text(manifest.get("suiteId"), label="manifest suiteId")
    if host_gold.get("suiteId") != suite_id or predictions.get("suiteId") != suite_id:
        raise ValueError("manifest, host gold, and predictions suiteId must match")

    manifest_cases = _case_map(manifest.get("cases"), label="public manifest")
    gold_cases = _validate_gold(host_gold)
    prediction_cases = _validate_predictions(predictions)
    expected_case_ids = set(manifest_cases)
    if set(gold_cases) != expected_case_ids or set(prediction_cases) != expected_case_ids:
        raise ValueError("manifest, host gold, and predictions case IDs must match exactly")

    span_correct = 0
    owner_correct = 0
    layer_correct = 0
    predicted_refs = 0
    valid_predicted_refs = 0
    required_groups = 0
    hit_required_groups = 0
    conclusion_count = 0
    unsupported_conclusion_count = 0
    eligible_repairs = 0
    actual_repair_successes = 0
    repair_assessment_correct = 0
    actual_regressions = 0
    regression_detection_correct = 0
    decision_correct = 0
    diagnostic_successes = 0
    per_case: list[dict[str, object]] = []

    for case_id in sorted(expected_case_ids):
        gold = gold_cases[case_id]
        prediction = prediction_cases[case_id]
        predicted_evidence = set(
            _string_list(
                prediction["evidenceRefs"],
                label=f"predictions {case_id} evidenceRefs",
                allow_empty=True,
            )
        )
        valid_evidence = set(str(item) for item in gold["validEvidenceIds"])
        groups = [set(str(item) for item in group) for group in gold["requiredEvidenceGroups"]]
        predicted_conclusions = set(
            _string_list(
                prediction["conclusionCodes"],
                label=f"predictions {case_id} conclusionCodes",
                allow_empty=True,
            )
        )
        supported_conclusions = set(
            str(item) for item in gold["supportedConclusionCodes"]
        )

        case_span_correct = prediction["firstFailingSpanId"] in set(
            str(item) for item in gold["acceptableFirstFailingSpanIds"]
        )
        case_owner_correct = prediction["rootOwner"] == gold["rootOwner"]
        case_layer_correct = prediction["targetLayer"] == gold["targetLayer"]
        case_hit_groups = sum(bool(group & predicted_evidence) for group in groups)
        case_unsupported = len(predicted_conclusions - supported_conclusions)

        span_correct += int(case_span_correct)
        owner_correct += int(case_owner_correct)
        layer_correct += int(case_layer_correct)
        predicted_refs += len(predicted_evidence)
        valid_predicted_refs += len(predicted_evidence & valid_evidence)
        required_groups += len(groups)
        hit_required_groups += case_hit_groups
        conclusion_count += len(predicted_conclusions)
        unsupported_conclusion_count += case_unsupported

        gold_repair = gold["repair"]
        prediction_repair = prediction["repairAssessment"]
        assert isinstance(gold_repair, Mapping)
        assert isinstance(prediction_repair, Mapping)
        repair_eligible = gold_repair["eligible"] is True
        case_repair_assessment_correct = False
        case_regression_detection_correct = False
        if repair_eligible:
            eligible_repairs += 1
            actual_repair_successes += int(gold_repair["successful"] is True)
            actual_regressions += int(gold_repair["regression"] is True)
            case_repair_assessment_correct = (
                prediction_repair["successful"] == gold_repair["successful"]
            )
            case_regression_detection_correct = (
                prediction_repair["regression"] == gold_repair["regression"]
            )
            repair_assessment_correct += int(case_repair_assessment_correct)
            regression_detection_correct += int(case_regression_detection_correct)
        case_decision_correct = (
            prediction_repair["decision"] == gold_repair["decision"]
        )
        decision_correct += int(case_decision_correct)

        case_diagnostic_success = (
            case_span_correct
            and case_owner_correct
            and case_hit_groups == len(groups)
            and case_unsupported == 0
        )
        diagnostic_successes += int(case_diagnostic_success)
        per_case.append(
            {
                "caseId": case_id,
                "firstFailingSpanCorrect": case_span_correct,
                "rootOwnerCorrect": case_owner_correct,
                "targetLayerCorrect": case_layer_correct,
                "validPredictedEvidenceRefs": len(predicted_evidence & valid_evidence),
                "predictedEvidenceRefs": len(predicted_evidence),
                "hitRequiredEvidenceGroups": case_hit_groups,
                "requiredEvidenceGroupCount": len(groups),
                "unsupportedConclusions": case_unsupported,
                "conclusions": len(predicted_conclusions),
                "repairAssessmentCorrect": (
                    case_repair_assessment_correct if repair_eligible else None
                ),
                "regressionDetectionCorrect": (
                    case_regression_detection_correct if repair_eligible else None
                ),
                "decisionCorrect": case_decision_correct,
                "diagnosticCaseSuccess": case_diagnostic_success,
            }
        )

    case_count = len(expected_case_ids)
    evidence_precision = _ratio(valid_predicted_refs, predicted_refs)
    evidence_recall = _ratio(hit_required_groups, required_groups)
    evidence_f1 = (
        2 * evidence_precision * evidence_recall / (evidence_precision + evidence_recall)
        if evidence_precision + evidence_recall
        else 0.0
    )
    payload: dict[str, object] = {
        "schemaVersion": "paw.trace-closed-loop-score.v1",
        "suiteId": suite_id,
        "split": str(manifest.get("split") or ""),
        "caseCount": case_count,
        "firstFailingSpan": {
            "correct": span_correct,
            "total": case_count,
            "accuracy": _ratio(span_correct, case_count),
        },
        "rootOwner": {
            "correct": owner_correct,
            "total": case_count,
            "accuracy": _ratio(owner_correct, case_count),
        },
        "targetLayer": {
            "correct": layer_correct,
            "total": case_count,
            "accuracy": _ratio(layer_correct, case_count),
        },
        "evidence": {
            "validPredictedRefs": valid_predicted_refs,
            "predictedRefs": predicted_refs,
            "hitRequiredGroups": hit_required_groups,
            "requiredGroups": required_groups,
            "precision": evidence_precision,
            "recall": evidence_recall,
            "f1": evidence_f1,
        },
        "unsupportedConclusions": {
            "unsupported": unsupported_conclusion_count,
            "total": conclusion_count,
            "rate": _ratio(unsupported_conclusion_count, conclusion_count),
        },
        "repair": {
            "eligibleCases": eligible_repairs,
            "actualSuccessfulCases": actual_repair_successes,
            "actualSuccessRate": _ratio(actual_repair_successes, eligible_repairs),
            "assessmentCorrect": repair_assessment_correct,
            "assessmentAccuracy": _ratio(repair_assessment_correct, eligible_repairs),
        },
        "regression": {
            "eligibleCases": eligible_repairs,
            "actualRegressedCases": actual_regressions,
            "actualRate": _ratio(actual_regressions, eligible_repairs),
            "detectionCorrect": regression_detection_correct,
            "detectionAccuracy": _ratio(regression_detection_correct, eligible_repairs),
        },
        "decision": {
            "correct": decision_correct,
            "total": case_count,
            "accuracy": _ratio(decision_correct, case_count),
        },
        "diagnosticCaseSuccess": {
            "successful": diagnostic_successes,
            "total": case_count,
            "rate": _ratio(diagnostic_successes, case_count),
        },
        "cases": per_case,
        "boundaries": [
            "This score covers known historical replay cases, not blind or Held-out diagnosis.",
            "Repair outcomes come from host-private gold; proposed but unauthorized changes must be excluded from repair denominators.",
            "The public score omits span gold, owner gold, evidence groups, supported conclusion labels, and host paths.",
        ],
    }
    payload["scoreSha256"] = _sha256(payload)
    return payload


def _write_json_atomic(path: str | Path, value: Mapping[str, object]) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--host-gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = _read_object(args.manifest, label="public manifest")
    host_gold = _read_object(args.host_gold, label="host gold")
    predictions = _read_object(args.predictions, label="predictions")
    result = score_trace_closed_loop(manifest, host_gold, predictions)
    _write_json_atomic(args.output, result)
    print(
        json.dumps(
            {
                "status": "scored",
                "suiteId": result["suiteId"],
                "caseCount": result["caseCount"],
                "scoreSha256": result["scoreSha256"],
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
