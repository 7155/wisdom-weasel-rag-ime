#!/usr/bin/env python3
"""Promote or reject validation-only RAG Agent evidence without opening held-out."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROMOTION_SCHEMA_VERSION = "paw.enterprise-rag-validation-promotion.v1"
HELDOUT_GATE_SCHEMA_VERSION = "paw.enterprise-rag-heldout-gate.v1"
VALIDATION_REPORT_SCHEMA_VERSION = "rag-ime.rag-agent-ablation-run.v1"
RETRIEVAL_REPORT_SCHEMA_VERSION = "rag-ime.rag-retrieval-run.v2"
LANES = ("baseline", "skill", "tuned", "agentic")
REQUIRED_HARD_GATES = (
    "splitIntegrity",
    "answerCaseBinding",
    "runtimePinned",
    "scopeBoundary",
    "citationResolution",
    "abstention",
    "crossSystemLeakage",
    "terminalCompletion",
    "toolContract",
    "agenticPolicy",
    "semanticIndex",
    "independentReranker",
    "answerJudge",
    "cleanup",
)


def sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def produce_authority(
    validation_agent_report_path: Path,
    retrieval_report_path: Path,
    *,
    decision: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Validate frozen validation evidence and return signed authority documents."""

    if decision not in {"keep", "reject"}:
        raise ValueError("decision must be keep or reject")
    validation_loaded = _load_verified_report(
        validation_agent_report_path,
        schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
        label="validation Agent report",
    )
    retrieval_loaded = _load_verified_report(
        retrieval_report_path,
        schema_version=RETRIEVAL_REPORT_SCHEMA_VERSION,
        label="retrieval report",
    )
    validation = validation_loaded["report"]
    retrieval = retrieval_loaded["report"]
    assert isinstance(validation, dict)
    assert isinstance(retrieval, dict)

    identity = _validation_identity(
        validation,
        retrieval,
        decision=decision,
        retrieval_file_sha256=str(retrieval_loaded["fileSha256"]),
    )
    bindings = {
        "validationAgentReportFileSha256": str(validation_loaded["fileSha256"]),
        "validationAgentReportSha256": str(validation["reportSha256"]),
        "retrievalReportFileSha256": str(retrieval_loaded["fileSha256"]),
        "retrievalReportSha256": str(retrieval["reportSha256"]),
        **identity["bindings"],
    }
    promotion: dict[str, Any] = {
        "schemaVersion": PROMOTION_SCHEMA_VERSION,
        "decision": decision,
        "state": "promoted" if decision == "keep" else "rejected",
        "heldOutObserved": False,
        "validationAgentReport": {
            "fileSha256": validation_loaded["fileSha256"],
            "reportSha256": validation["reportSha256"],
        },
        "retrievalReport": {
            "fileSha256": retrieval_loaded["fileSha256"],
            "reportSha256": retrieval["reportSha256"],
        },
        "bindings": bindings,
        "identity": {
            "piRuntime": identity["piRuntime"],
            "modelRoute": identity["modelRoute"],
        },
        "winner": {
            "reportSha256": retrieval["reportSha256"],
            "retrievalConfig": identity["retrievalConfig"],
            "retrievalConfigSha256": bindings["retrievalConfigSha256"],
        },
    }
    if decision == "reject":
        promotion["failureSummary"] = identity["failureSummary"]
    promotion["promotionReceiptSha256"] = sha256_json(promotion)

    if decision == "reject":
        return promotion, None
    gate: dict[str, Any] = {
        "schemaVersion": HELDOUT_GATE_SCHEMA_VERSION,
        "state": "unlocked",
        "heldOutObserved": False,
        "maximumEvaluations": 1,
        "consumedEvaluations": 0,
        "promotionReceiptSha256": promotion["promotionReceiptSha256"],
        **bindings,
    }
    gate["gateReceiptSha256"] = sha256_json(gate)
    return promotion, gate


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-agent-report", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--decision", choices=("keep", "reject"), required=True)
    parser.add_argument("--output-promotion", type=Path, required=True)
    parser.add_argument("--output-heldout-gate", type=Path)
    args = parser.parse_args(argv)

    if args.decision == "keep" and args.output_heldout_gate is None:
        parser.error("--output-heldout-gate is required for Keep")
    if args.decision == "reject" and args.output_heldout_gate is not None:
        parser.error("--output-heldout-gate is allowed only for Keep")
    output_promotion = args.output_promotion.expanduser().resolve(strict=False)
    output_gate = (
        args.output_heldout_gate.expanduser().resolve(strict=False)
        if args.output_heldout_gate is not None
        else None
    )
    if output_gate is not None and output_gate == output_promotion:
        parser.error("promotion and held-out gate outputs must be different files")

    try:
        promotion, gate = produce_authority(
            args.validation_agent_report.expanduser().resolve(strict=True),
            args.retrieval_report.expanduser().resolve(strict=True),
            decision=args.decision,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    _write_json(output_promotion, promotion)
    if output_gate is not None:
        assert gate is not None
        _write_json(output_gate, gate)
    print(
        json.dumps(
            {
                "decision": args.decision,
                "heldOutObserved": False,
                "promotionReceiptSha256": promotion["promotionReceiptSha256"],
                "gateReceiptSha256": gate["gateReceiptSha256"] if gate else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _load_verified_report(
    path: Path,
    *,
    schema_version: str,
    label: str,
) -> dict[str, object]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    if value.get("schemaVersion") != schema_version:
        raise ValueError(f"{label} schema is unsupported")
    expected = str(value.get("reportSha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "reportSha256"}
    if not expected or sha256_json(unsigned) != expected:
        raise ValueError(f"{label} logical self hash is invalid")
    return {
        "report": value,
        "fileSha256": hashlib.sha256(raw).hexdigest(),
    }


def _validation_identity(
    validation: Mapping[str, object],
    retrieval: Mapping[str, object],
    *,
    decision: str,
    retrieval_file_sha256: str,
) -> dict[str, object]:
    validation_passed = validation.get("passed")
    if not isinstance(validation_passed, bool):
        raise ValueError("validation Agent report passed status must be boolean")
    if decision == "keep" and validation_passed is not True:
        raise ValueError("validation Agent report did not pass")
    if (
        validation.get("formalAcceptanceEligible") is not False
        or validation.get("formalAcceptancePassed") is not False
    ):
        raise ValueError("validation Agent report must not claim formal acceptance")
    if validation.get("localOnly") is not True or validation.get("uploaded") is not False:
        raise ValueError("validation Agent report must be local-only")
    evaluation = _object(validation.get("evaluation"), "validation evaluation")
    conditions = _object(validation.get("conditions"), "validation conditions")
    if evaluation.get("mode") != "answer-only" or conditions.get(
        "evaluationMode"
    ) != "answer-only":
        raise ValueError("validation evaluation mode must be answer-only")
    if evaluation.get("split") != "validation" or conditions.get(
        "evaluationSplit"
    ) != "validation":
        raise ValueError("validation evaluation split must be validation")
    if evaluation.get("formalAcceptanceEligible") is not False:
        raise ValueError("validation evaluation must not be formal-acceptance eligible")
    heldout_authorization = _object(
        validation.get("heldOutAuthorization"), "held-out authorization"
    )
    if (
        heldout_authorization.get("authorized") is not False
        or evaluation.get("heldOutLabelsInPrompt") is not False
        or validation.get("heldOut") not in (None, False)
    ):
        raise ValueError("validation Agent report observed or authorized held-out data")
    cleanup_passed = validation.get("cleanupPassed")
    if not isinstance(cleanup_passed, bool):
        raise ValueError("validation Agent report cleanup status must be boolean")
    if decision == "keep" and cleanup_passed is not True:
        raise ValueError("validation Agent report cleanup did not pass")

    lanes = validation.get("lanes")
    if not isinstance(lanes, list) or len(lanes) != len(LANES):
        raise ValueError("validation Agent report must contain exactly four lanes")
    lane_map = {
        str(item.get("lane") or ""): item
        for item in lanes
        if isinstance(item, Mapping)
    }
    if set(lane_map) != set(LANES):
        raise ValueError("validation Agent report must contain the four named lanes")
    failed_hard_gates_by_lane: dict[str, list[str]] = {}
    for lane in LANES:
        hard_gates = _object(lane_map[lane].get("hardGates"), f"{lane} hard gates")
        missing = [name for name in REQUIRED_HARD_GATES if name not in hard_gates]
        if missing or any(not isinstance(value, bool) for value in hard_gates.values()):
            detail = ", ".join(missing) if missing else "one or more gates are not boolean"
            raise ValueError(f"{lane} hard gate failure: {detail}")
        failed_hard_gates_by_lane[lane] = sorted(
            name for name, value in hard_gates.items() if value is False
        )
        if decision == "keep" and failed_hard_gates_by_lane[lane]:
            detail = ", ".join(missing) if missing else "one or more gates are false"
            raise ValueError(f"{lane} hard gate failure: {detail}")

    if retrieval.get("status") != "completed":
        raise ValueError("retrieval report did not complete")
    if retrieval.get("localOnly") is not True or retrieval.get("uploaded") is not False:
        raise ValueError("retrieval report must be local-only")
    selection = _object(retrieval.get("validationSelection"), "retrieval selection")
    retrieval_gates = _object(retrieval.get("hardGates"), "retrieval hard gates")
    if (
        retrieval.get("evaluationScope") != "validation-only"
        or retrieval.get("heldOut") is not None
        or retrieval.get("comparison") is not None
        or selection.get("heldOutLabelsObserved") is not False
        or not retrieval_gates
        or any(value is not True for value in retrieval_gates.values())
    ):
        raise ValueError("retrieval report is not clean validation-only evidence")

    _same(
        validation.get("sourcePreparedSha256"),
        retrieval.get("sourcePreparedSha256"),
        "sourcePreparedSha256",
    )
    _same(
        validation.get("sourceRetrievalReportSha256"),
        retrieval_file_sha256,
        "sourceRetrievalReportSha256",
    )
    winner = _object(selection.get("winner"), "retrieval winner")
    retrieval_config = _object(winner.get("config"), "winner retrieval config")
    retrieval_config_sha256 = sha256_json(retrieval_config)
    _same(
        winner.get("configSha256"),
        retrieval_config_sha256,
        "winner retrievalConfigSha256",
    )
    _same(
        selection.get("frozenConfigSha256"),
        retrieval_config_sha256,
        "frozen retrievalConfigSha256",
    )
    _same(
        validation.get("tunedRetrievalConfig"),
        retrieval_config,
        "tuned retrievalConfig",
    )
    _same(
        validation.get("tunedRetrievalConfigSha256"),
        retrieval_config_sha256,
        "tuned retrievalConfigSha256",
    )
    default_config = _object(
        validation.get("defaultRetrievalConfig"), "default retrieval config"
    )
    default_config_sha256 = sha256_json(default_config)
    _same(
        validation.get("defaultRetrievalConfigSha256"),
        default_config_sha256,
        "default retrievalConfigSha256",
    )
    for lane in LANES:
        expected_config_sha256 = (
            default_config_sha256
            if lane in {"baseline", "skill"}
            else retrieval_config_sha256
        )
        _same(
            lane_map[lane].get("retrievalConfigSha256"),
            expected_config_sha256,
            f"{lane} retrievalConfigSha256",
        )

    case_ids = evaluation.get("caseIds")
    if (
        not isinstance(case_ids, list)
        or not case_ids
        or any(not isinstance(value, str) or not value for value in case_ids)
        or len(set(case_ids)) != len(case_ids)
        or evaluation.get("caseCount") != len(case_ids)
    ):
        raise ValueError("validation caseIds are invalid")
    case_ids_sha256 = sha256_json(case_ids)
    _same(evaluation.get("caseIdsSha256"), case_ids_sha256, "caseIdsSha256")
    _same(conditions.get("caseIdsSha256"), case_ids_sha256, "condition caseIdsSha256")

    answer_manifest = _object(
        validation.get("answerCaseManifest"), "answer case manifest"
    )
    equality_fields = (
        "answerCaseManifestSha256",
        "answerCaseSetSha256",
        "promptConfigSha256",
    )
    for field in equality_fields:
        _same(evaluation.get(field), conditions.get(field), field)
    _same(
        evaluation.get("answerCaseManifestSha256"),
        answer_manifest.get("manifestSha256"),
        "answerCaseManifestSha256",
    )
    _same(
        evaluation.get("answerCaseSetSha256"),
        answer_manifest.get("answerCaseSetSha256"),
        "answerCaseSetSha256",
    )
    _same(
        evaluation.get("caseSetSha256"),
        answer_manifest.get("selectedCaseSetSha256"),
        "caseSetSha256",
    )
    _same(
        evaluation.get("caseSetSha256"),
        conditions.get("selectedAnswerCaseSetSha256"),
        "condition caseSetSha256",
    )

    pi_runtime = _object(validation.get("piRuntime"), "Pi Runtime identity")
    _same(pi_runtime, conditions.get("piRuntime"), "Pi Runtime identity")
    pi_runtime_sha256 = _verify_identity_hash(pi_runtime, "Pi Runtime identity")
    runtime_pinned = pi_runtime.get("sourceAccess") == "explicit-verified-payload-v1"
    for lane in LANES:
        hard_gates = lane_map[lane]["hardGates"]
        assert isinstance(hard_gates, Mapping)
        if hard_gates.get("runtimePinned") is not runtime_pinned:
            raise ValueError(
                f"validation identity drift: {lane} runtimePinned status"
            )
        if hard_gates.get("cleanup") is not cleanup_passed:
            raise ValueError(f"validation identity drift: {lane} cleanup status")
    if (
        decision == "keep"
        and not runtime_pinned
    ):
        raise ValueError("Pi Runtime identity is not source-pinned")
    agent_config = _object(validation.get("agentConfig"), "model route identity")
    _same(agent_config, conditions.get("agentConfig"), "model route identity")
    _verify_identity_hash(agent_config, "Agent configuration identity")
    model_route = _object(agent_config.get("modelRouting"), "model route identity")
    model_route_sha256 = _verify_identity_hash(model_route, "model route identity")

    bindings = {
        "sourcePreparedSha256": str(validation.get("sourcePreparedSha256") or ""),
        "sourceAnswerCasesSha256": str(
            validation.get("sourceAnswerCasesSha256") or ""
        ),
        "sourceRetrievalReportSha256": str(
            validation.get("sourceRetrievalReportSha256") or ""
        ),
        "caseIds": list(case_ids),
        "caseIdsSha256": case_ids_sha256,
        "caseSetSha256": str(evaluation.get("caseSetSha256") or ""),
        "answerCaseManifestSha256": str(
            evaluation.get("answerCaseManifestSha256") or ""
        ),
        "answerCaseSetSha256": str(
            evaluation.get("answerCaseSetSha256") or ""
        ),
        "promptConfigSha256": str(evaluation.get("promptConfigSha256") or ""),
        "runtimeContractSha256": str(
            conditions.get("runtimeContractSha256") or ""
        ),
        "piRuntimeIdentitySha256": pi_runtime_sha256,
        "modelRouteIdentitySha256": model_route_sha256,
        "retrievalConfigSha256": retrieval_config_sha256,
    }
    if any(value in (None, "", []) for value in bindings.values()):
        raise ValueError("validation identity binding is incomplete")
    return {
        "bindings": bindings,
        "piRuntime": dict(pi_runtime),
        "modelRoute": dict(model_route),
        "retrievalConfig": dict(retrieval_config),
        "failureSummary": {
            "status": (
                "passed_validation_rejected"
                if validation_passed
                else "validation_failed"
            ),
            "validationPassed": validation_passed,
            "acceptanceStatus": str(validation.get("acceptanceStatus") or ""),
            "cleanupPassed": cleanup_passed,
            "failedHardGateNames": sorted(
                {
                    gate
                    for failures in failed_hard_gates_by_lane.values()
                    for gate in failures
                }
            ),
            "failedHardGatesByLane": failed_hard_gates_by_lane,
            "reportFailure": str(validation.get("failure") or ""),
        },
    }


def _verify_identity_hash(value: Mapping[str, object], label: str) -> str:
    expected = str(value.get("identitySha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "identitySha256"}
    if not expected or sha256_json(unsigned) != expected:
        raise ValueError(f"{label} self hash is invalid")
    return expected


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _same(left: object, right: object, label: str) -> None:
    if left != right or left in (None, "", []):
        raise ValueError(f"validation/retrieval identity drift: {label}")


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
