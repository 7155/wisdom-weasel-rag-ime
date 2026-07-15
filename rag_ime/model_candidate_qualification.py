from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path

from .minimind_quality_gate import (
    PROMOTION_QUALITY_CHECK_NAMES,
    PRODUCTION_CANDIDATE_STAGE,
    QUALITY_SCHEMA_VERSION,
    RAW_MODEL_OUTPUT_STAGE,
    audit_completion_dataset,
)
from .model_registry import ModelDeployment, fingerprint_model_artifact, fingerprint_tokenizer_artifact


PLAN_SCHEMA_VERSION = "rag-ime.model-candidate-plan.v1"
REPORT_SCHEMA_VERSION = "rag-ime.model-candidate-qualification.v1"


def prepare_model_candidate_plan(
    *,
    model_path: str | Path,
    model_id: str,
    profile: str,
    dataset_root: str | Path,
    output_path: str | Path,
    runtime: str = "mlx",
    prompt_mode: str = "base-completion",
) -> dict[str, object]:
    artifact = Path(model_path).expanduser().resolve()
    if not artifact.is_dir():
        raise ValueError("candidate model path must be a directory")
    if not model_id.strip() or not profile.strip():
        raise ValueError("model_id and profile are required")
    if runtime != "mlx":
        raise ValueError("MiniMind qualification currently requires an MLX artifact")
    audit = audit_completion_dataset(dataset_root)
    if not audit.get("ok"):
        raise ValueError("completion dataset audit failed")
    dataset_path = Path(dataset_root).expanduser().resolve()
    fingerprint = fingerprint_model_artifact(artifact)
    deployment = ModelDeployment(
        model_id=model_id.strip(),
        path=str(artifact),
        format="mlx",
        fingerprint=fingerprint,
        profile=profile.strip(),
        runtime="mlx",
        lane="candidate",
        prompt_mode=prompt_mode,
        active=False,
    )
    output = Path(output_path).expanduser().resolve()
    evidence_dir = output.parent / f"{model_id}.qualification"
    raw_output = evidence_dir / "raw.jsonl"
    raw_capture_report = evidence_dir / "raw-capture.json"
    raw_quality_report = evidence_dir / "raw-quality.json"
    production_quality_report = evidence_dir / "production-quality.json"
    qualification_report = evidence_dir / "qualification.json"
    quoted = {
        "artifact": shlex.quote(str(artifact)),
        "candidate": shlex.quote(model_id.strip()),
        "dataset": shlex.quote(str(dataset_path)),
        "profile": shlex.quote(profile.strip()),
        "plan": shlex.quote(str(output)),
        "rawOutput": shlex.quote(str(raw_output)),
        "rawCaptureReport": shlex.quote(str(raw_capture_report)),
        "rawQualityReport": shlex.quote(str(raw_quality_report)),
        "productionQualityReport": shlex.quote(str(production_quality_report)),
        "qualificationReport": shlex.quote(str(qualification_report)),
    }
    plan = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "candidateId": model_id.strip(),
        "artifact": {
            "path": str(artifact),
            "fingerprint": fingerprint,
            "tokenizerFingerprint": fingerprint_tokenizer_artifact(artifact),
        },
        "dataset": {
            "path": str(dataset_path),
            "id": audit.get("datasetId"),
            "fingerprint": audit.get("datasetFingerprint"),
        },
        "inactiveRegistryEntry": deployment.payload(),
        "activeModelMutationAllowed": False,
        "requiredStages": [RAW_MODEL_OUTPUT_STAGE, PRODUCTION_CANDIDATE_STAGE],
        "requiredChecks": sorted(PROMOTION_QUALITY_CHECK_NAMES),
        "evidenceDirectory": str(evidence_dir),
        "requiredEnvironment": {
            "RAG_IME_CANDIDATE_ENDPOINT": "loopback URL of the already-running predictor loaded with this artifact",
            "RAG_IME_RAW_JUDGMENTS": "reviewed raw-branch judgments bound to this dataset fingerprint",
            "RAG_IME_PRODUCTION_JUDGMENTS": "reviewed production-candidate judgments bound to this dataset fingerprint",
        },
        "commands": {
            "rawCapture": (
                "python3 scripts/capture_minimind_raw_outputs.py "
                f"--dataset {quoted['dataset']} --split test --endpoint \"$RAG_IME_CANDIDATE_ENDPOINT\" "
                f"--model {quoted['artifact']} --checkpoint {quoted['candidate']} "
                f"--checkpoint-path {quoted['artifact']} --output {quoted['rawOutput']} "
                f"--report {quoted['rawCaptureReport']}"
            ),
            "rawGate": (
                f"python3 scripts/minimind_retraining.py evaluate --stage raw_model_output --provider raw-jsonl "
                f"--dataset {quoted['dataset']} --split test --raw-output-jsonl {quoted['rawOutput']} "
                f"--raw-capture-report {quoted['rawCaptureReport']} --checkpoint {quoted['candidate']} "
                f"--checkpoint-path {quoted['artifact']} --semantic-judgments \"$RAG_IME_RAW_JUDGMENTS\" "
                f"--report {quoted['rawQualityReport']}"
            ),
            "productionGate": (
                "env RAG_IME_PREDICTOR_PROVIDER=mlx "
                "RAG_IME_PREDICTOR_BASE_URL=\"$RAG_IME_CANDIDATE_ENDPOINT\" "
                f"RAG_IME_PREDICTOR_MODEL={quoted['artifact']} RAG_IME_PREDICTOR_PROFILE={quoted['profile']} "
                f"RAG_IME_PREDICTOR_PROMPT_MODE={shlex.quote(prompt_mode)} "
                "python3 scripts/minimind_retraining.py evaluate --stage production_candidate --provider env "
                f"--dataset {quoted['dataset']} --split test --checkpoint {quoted['candidate']} "
                f"--checkpoint-path {quoted['artifact']} --semantic-judgments \"$RAG_IME_PRODUCTION_JUDGMENTS\" "
                f"--report {quoted['productionQualityReport']}"
            ),
            "finalize": (
                f"python3 scripts/qualify_model_candidate.py finalize --plan {quoted['plan']} "
                f"--raw-quality {quoted['rawQualityReport']} "
                f"--production-quality {quoted['productionQualityReport']} "
                f"--output {quoted['qualificationReport']}"
            ),
        },
        "notes": [
            "The candidate lane is inactive and cannot replace the current hot model.",
            "Both quality reports must be bound to the current artifact fingerprint and dataset fingerprint.",
            "Backend qualification does not authorize foreground activation.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "plan": str(output), **plan}


def finalize_model_candidate_qualification(
    *,
    plan_path: str | Path,
    raw_quality_path: str | Path,
    production_quality_path: str | Path,
    output_path: str | Path,
    foreground_evidence_path: str | Path | None = None,
) -> dict[str, object]:
    plan_file = Path(plan_path).expanduser().resolve()
    plan = _load_object(plan_file)
    if plan.get("schemaVersion") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported candidate plan schema")
    artifact = plan.get("artifact") if isinstance(plan.get("artifact"), dict) else {}
    artifact_path = Path(str(artifact.get("path") or "")).expanduser().resolve()
    current_fingerprint = fingerprint_model_artifact(artifact_path)
    expected_fingerprint = str(artifact.get("fingerprint") or "")
    if current_fingerprint != expected_fingerprint:
        raise ValueError("candidate artifact changed after plan creation")
    dataset = plan.get("dataset") if isinstance(plan.get("dataset"), dict) else {}
    candidate_id = str(plan.get("candidateId") or "")
    evidence_files = {
        RAW_MODEL_OUTPUT_STAGE: Path(raw_quality_path).expanduser().resolve(),
        PRODUCTION_CANDIDATE_STAGE: Path(production_quality_path).expanduser().resolve(),
    }
    stage_reports: dict[str, dict[str, object]] = {}
    issues: list[dict[str, object]] = []
    for stage, path in evidence_files.items():
        report = _load_object(path)
        if report.get("schemaVersion") != QUALITY_SCHEMA_VERSION:
            issues.append({"id": "quality_schema_mismatch", "stage": stage})
        stage_reports[stage] = {
            "path": str(path),
            "sha256": _sha256_file(path),
            "gatePassed": report.get("gatePassed"),
            "promotionEligible": report.get("promotionEligible"),
            "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        }
        expected = {
            "evaluationStage": stage,
            "checkpoint": candidate_id,
            "checkpointFingerprint": expected_fingerprint,
            "checkpointPath": str(artifact_path),
            "datasetFingerprint": dataset.get("fingerprint"),
        }
        for field, expected_value in expected.items():
            if report.get(field) != expected_value:
                issues.append(
                    {"id": "evidence_binding_mismatch", "stage": stage, "field": field, "expected": expected_value}
                )
        if report.get("gatePassed") is not True or report.get("promotionEligible") is not True:
            issues.append({"id": "quality_gate_failed", "stage": stage})
        checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        check_names = {
            str(item.get("name") or "")
            for item in checks
            if isinstance(item, dict)
        }
        missing_checks = sorted(PROMOTION_QUALITY_CHECK_NAMES - check_names)
        if missing_checks:
            issues.append({"id": "quality_checks_missing", "stage": stage, "checks": missing_checks})
        if not checks or not all(_valid_passed_check(item) for item in checks):
            issues.append({"id": "quality_checks_incomplete", "stage": stage})
        semantic_scorer = report.get("semanticScorer") if isinstance(report.get("semanticScorer"), dict) else {}
        if semantic_scorer.get("configured") is not True:
            issues.append({"id": "semantic_scorer_missing", "stage": stage})
        evidence_field = "rawCaptureEvidence" if stage == RAW_MODEL_OUTPUT_STAGE else "runtimeModelEvidence"
        _validate_runtime_evidence(
            report.get(evidence_field),
            stage=stage,
            expected_fingerprint=expected_fingerprint,
            expected_dataset_fingerprint=dataset.get("fingerprint"),
            expected_checkpoint=candidate_id,
            issues=issues,
        )

    foreground = _foreground_evidence(foreground_evidence_path, expected_fingerprint, dataset.get("fingerprint"))
    backend_qualified = not issues
    activation_eligible = backend_qualified and foreground.get("passed") is True
    result = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "candidateId": candidate_id,
        "artifactFingerprint": expected_fingerprint,
        "datasetFingerprint": dataset.get("fingerprint"),
        "backendQualified": backend_qualified,
        "activationEligible": activation_eligible,
        "activeModelMutated": False,
        "registryAction": "none",
        "stageEvidence": stage_reports,
        "foregroundEvidence": foreground,
        "issues": issues,
        "nextAction": (
            "manual_review_then_explicit_registry_activation"
            if activation_eligible
            else "collect_or_fix_required_evidence"
        ),
    }
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": backend_qualified, "report": str(output), **result}


def _foreground_evidence(
    path: str | Path | None,
    model_fingerprint: str,
    dataset_fingerprint: object,
) -> dict[str, object]:
    if path is None:
        return {"configured": False, "passed": False, "reason": "foreground_evidence_missing"}
    evidence_path = Path(path).expanduser().resolve()
    payload = _load_object(evidence_path)
    passed = (
        payload.get("passed") is True
        and payload.get("modelFingerprint") == model_fingerprint
        and payload.get("datasetFingerprint") == dataset_fingerprint
        and payload.get("strictSoakPassed") is True
    )
    return {
        "configured": True,
        "passed": passed,
        "path": str(evidence_path),
        "sha256": _sha256_file(evidence_path),
        "reason": "" if passed else "foreground_binding_or_soak_failed",
    }


def _valid_passed_check(item: object) -> bool:
    if not isinstance(item, dict) or item.get("passed") is not True:
        return False
    if not str(item.get("name") or ""):
        return False
    if item.get("operator") not in {">=", "<="}:
        return False
    return isinstance(item.get("actual"), (int, float)) and isinstance(item.get("expected"), (int, float))


def _validate_runtime_evidence(
    evidence: object,
    *,
    stage: str,
    expected_fingerprint: str,
    expected_dataset_fingerprint: object,
    expected_checkpoint: str,
    issues: list[dict[str, object]],
) -> None:
    payload = evidence if isinstance(evidence, dict) else {}
    expected = {
        "verified": True,
        "checkpoint": expected_checkpoint,
        "checkpointFingerprint": expected_fingerprint,
        "datasetFingerprint": expected_dataset_fingerprint,
    }
    mismatches = [field for field, value in expected.items() if payload.get(field) != value]
    if mismatches:
        issues.append({"id": "runtime_evidence_mismatch", "stage": stage, "fields": mismatches})


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
