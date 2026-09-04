#!/usr/bin/env python3
"""Validate interview-facing Agent experiment cards and their proof boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path


SCHEMA_VERSION = "paw.interview-agent-experiment-ledger.v1"
LAYERS = ("system_prompt", "tool", "workflow", "skill")
METRIC_FAMILIES = (
    "outcome_quality",
    "evidence_grounding",
    "runtime_reliability",
    "efficiency_cost",
    "safety_recovery",
)
STATUSES = frozenset({"kept", "rejected", "diagnostic", "open_gap"})
CLAIM_STATUSES = frozenset({"headline", "supporting", "diagnostic", "blocked"})
EFFECT_STATUSES = frozenset({"improved", "neutral", "regressed", "not_run", "unverified"})
CANDIDATE_TYPES = frozenset({"single_factor", "compound_repair", "baseline", "unknown"})
PROJECTION_STATES = frozenset({"current", "history"})
RECOMMENDATION_STATUSES = frozenset(
    {"proposed", "authorized", "implemented", "verified", "rejected"}
)
LAYER_STATUSES = frozenset(
    {"changed", "considered_no_change", "not_applicable", "open_gap"}
)
FACTOR_NAMES = frozenset(
    {
        "model", "prompt", "skill", "tool", "workflow", "context",
        "memory_rag", "guardrail", "execution_policy", "human_loop", "pricing",
    }
)
METRIC_FAMILY_STATUSES = frozenset({"measured", "open_gap", "not_applicable"})
ATTRIBUTION_FIELDS = (
    "detectedBy",
    "proposedBy",
    "authorizedBy",
    "implementedBy",
    "verifiedBy",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _repo_ref_path(ref: str, repo_root: Path) -> Path | None:
    if ref.startswith(("http://", "https://", "local://")):
        return None
    raw_path = ref.split("#", 1)[0].strip()
    return repo_root / raw_path if raw_path else None


def _require_text(
    errors: list[str], prefix: str, payload: Mapping[str, object], field: str
) -> None:
    if not _text(payload.get(field)):
        errors.append(f"{prefix}: {field} is required")


def _validate_refs(
    errors: list[str],
    *,
    prefix: str,
    value: object,
    repo_root: Path | None,
) -> None:
    refs = _sequence(value)
    if not refs:
        errors.append(f"{prefix}: evidenceRefs must be non-empty")
        return
    for raw_ref in refs:
        if not _text(raw_ref):
            errors.append(f"{prefix}: evidenceRefs contains an empty value")
            continue
        if repo_root is None:
            continue
        path = _repo_ref_path(str(raw_ref), repo_root)
        if path is not None and not path.exists():
            errors.append(f"{prefix}: evidence ref does not exist: {raw_ref}")


def _validate_run_side(
    errors: list[str],
    *,
    experiment_id: str,
    name: str,
    value: object,
    repo_root: Path | None,
    require_outputs: bool,
) -> None:
    side = _mapping(value)
    prefix = f"{experiment_id}: {name}"
    _require_text(errors, prefix, side, "runId")
    metrics = side.get("metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        errors.append(f"{prefix}.metrics must be non-empty")
    outputs = _sequence(side.get("outputExamples"))
    if require_outputs and not outputs:
        errors.append(f"{prefix}.outputExamples must be non-empty")
    for index, raw_output in enumerate(outputs, start=1):
        output = _mapping(raw_output)
        output_prefix = f"{prefix}.outputExamples[{index}]"
        for field in ("caseId", "input", "output"):
            _require_text(errors, output_prefix, output, field)
    _validate_refs(
        errors,
        prefix=prefix,
        value=side.get("evidenceRefs"),
        repo_root=repo_root,
    )


def validate_agent_experiments(
    payload: Mapping[str, object], *, repo_root: Path | None = None
) -> list[str]:
    errors: list[str] = []
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")
    if not _text(payload.get("generatedAt")):
        errors.append("generatedAt is required")

    narrative = _mapping(payload.get("narrativePolicy"))
    for field in ("headline", "deepDive", "noFabrication"):
        _require_text(errors, "narrativePolicy", narrative, field)

    experiments = payload.get("experiments")
    if not isinstance(experiments, list) or not experiments:
        errors.append("experiments must be a non-empty list")
        experiments = []
    seen_ids: set[str] = set()
    for raw_experiment in experiments:
        experiment = _mapping(raw_experiment)
        experiment_id = str(experiment.get("id") or "").strip() or "<missing-experiment-id>"
        if experiment_id in seen_ids:
            errors.append(f"duplicate experiment id: {experiment_id}")
        seen_ids.add(experiment_id)

        for field in ("title", "vertical", "businessProblem", "whyAgent"):
            _require_text(errors, experiment_id, experiment, field)
        status = str(experiment.get("status") or "")
        if status not in STATUSES:
            errors.append(f"{experiment_id}: unsupported status: {status}")
        claim_status = str(experiment.get("claimStatus") or "")
        if claim_status not in CLAIM_STATUSES:
            errors.append(f"{experiment_id}: unsupported claimStatus: {claim_status}")
        projection_state = str(experiment.get("projectionState") or "current")
        if projection_state not in PROJECTION_STATES:
            errors.append(
                f"{experiment_id}: unsupported projectionState: {projection_state}"
            )
        superseded_by = experiment.get("supersededBy")
        if superseded_by is not None and not _text(superseded_by):
            errors.append(f"{experiment_id}: supersededBy must be a non-empty id")
        effect_status = str(experiment.get("effectStatus") or "")
        if effect_status not in EFFECT_STATUSES:
            errors.append(f"{experiment_id}: unsupported effectStatus: {effect_status}")
        candidate_type = str(experiment.get("candidateType") or "")
        if candidate_type not in CANDIDATE_TYPES:
            errors.append(f"{experiment_id}: unsupported candidateType: {candidate_type}")

        star = _mapping(experiment.get("star"))
        for field in ("situation", "task", "action", "result"):
            if not _text(star.get(field)):
                errors.append(f"{experiment_id}: star.{field} is required")

        dataset = _mapping(experiment.get("dataset"))
        for field in ("id", "split", "unit"):
            _require_text(errors, f"{experiment_id}: dataset", dataset, field)
        case_count = dataset.get("caseCount")
        if not isinstance(case_count, int) or isinstance(case_count, bool) or case_count < 1:
            errors.append(f"{experiment_id}: dataset.caseCount must be a positive integer")
        manifest_hash = dataset.get("manifestSha256")
        if not isinstance(manifest_hash, str) or _SHA256.fullmatch(manifest_hash) is None:
            errors.append(f"{experiment_id}: dataset.manifestSha256 must be a lowercase SHA-256")
        held_out_consumed = dataset.get("heldOutConsumed")
        if not isinstance(held_out_consumed, bool):
            errors.append(f"{experiment_id}: dataset.heldOutConsumed must be boolean")
        elif held_out_consumed and not _text(dataset.get("oneShotReceiptRef")):
            errors.append(
                f"{experiment_id}: consumed held-out requires dataset.oneShotReceiptRef"
            )

        scoring = _mapping(experiment.get("scoringContract"))
        for field in ("primaryMetric", "evaluatorAuthority"):
            _require_text(errors, f"{experiment_id}: scoringContract", scoring, field)
        if not _sequence(scoring.get("hardGates")):
            errors.append(f"{experiment_id}: scoringContract.hardGates must be non-empty")
        if not isinstance(scoring.get("goldHiddenFromAgent"), bool):
            errors.append(
                f"{experiment_id}: scoringContract.goldHiddenFromAgent must be boolean"
            )

        factors = _sequence(experiment.get("factors"))
        if not factors:
            errors.append(f"{experiment_id}: factors must be non-empty")
        if candidate_type == "single_factor" and len(factors) != 1:
            errors.append(
                f"{experiment_id}: single_factor experiments must contain exactly one factor"
            )
        if candidate_type == "compound_repair" and len(factors) < 2:
            errors.append(
                f"{experiment_id}: compound_repair experiments must contain at least two factors"
            )
        for index, raw_factor in enumerate(factors, start=1):
            factor = _mapping(raw_factor)
            prefix = f"{experiment_id}: factors[{index}]"
            name = factor.get("name")
            if name not in FACTOR_NAMES:
                errors.append(f"{prefix}: unsupported name: {name}")
            for field in ("before", "after", "reason"):
                _require_text(errors, prefix, factor, field)

        controls = _sequence(experiment.get("frozenControls"))
        if not controls:
            errors.append(f"{experiment_id}: frozenControls must be non-empty")
        for index, raw_control in enumerate(controls, start=1):
            control = _mapping(raw_control)
            prefix = f"{experiment_id}: frozenControls[{index}]"
            for field in ("name", "value", "reason"):
                _require_text(errors, prefix, control, field)

        optimization = _mapping(experiment.get("optimizationContract"))
        for field in ("objective", "selectionRule", "stopRule", "heldOutRule"):
            _require_text(
                errors,
                f"{experiment_id}: optimizationContract",
                optimization,
                field,
            )
        search_space = _sequence(optimization.get("candidateSearchSpace"))
        if not search_space:
            errors.append(
                f"{experiment_id}: optimizationContract.candidateSearchSpace must be non-empty"
            )
        for index, raw_axis in enumerate(search_space, start=1):
            axis = _mapping(raw_axis)
            prefix = (
                f"{experiment_id}: optimizationContract.candidateSearchSpace[{index}]"
            )
            _require_text(errors, prefix, axis, "axis")
            count = axis.get("candidatesEvaluated")
            minimum_count = 0 if status == "open_gap" else 1
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < minimum_count
            ):
                requirement = "non-negative" if minimum_count == 0 else "positive"
                errors.append(
                    f"{prefix}: candidatesEvaluated must be {requirement}"
                )
            if not _sequence(axis.get("values")):
                errors.append(f"{prefix}: values must be non-empty")
        if candidate_type == "single_factor" and len(factors) == 1:
            factor_name = str(_mapping(factors[0]).get("name") or "")
            if len(search_space) != 1:
                errors.append(
                    f"{experiment_id}: single_factor optimization must contain exactly one search axis"
                )
            elif factor_name not in str(
                _mapping(search_space[0]).get("axis") or ""
            ):
                errors.append(
                    f"{experiment_id}: single_factor search axis must match factor {factor_name}"
                )
        if not _sequence(optimization.get("frozenVariables")):
            errors.append(
                f"{experiment_id}: optimizationContract.frozenVariables must be non-empty"
            )

        best_known = _mapping(experiment.get("bestKnown"))
        _require_text(errors, f"{experiment_id}: bestKnown", best_known, "configId")
        best_hash = best_known.get("configSha256")
        if not isinstance(best_hash, str) or _SHA256.fullmatch(best_hash) is None:
            errors.append(
                f"{experiment_id}: bestKnown.configSha256 must be a lowercase SHA-256"
            )
        if str(best_known.get("decision") or "") not in {
            "keep",
            "reject",
            "diagnostic",
            "not_run",
        }:
            errors.append(
                f"{experiment_id}: unsupported bestKnown.decision: {best_known.get('decision')}"
            )

        metric_families = _sequence(experiment.get("metricFamilies"))
        family_ids = [
            str(_mapping(item).get("family") or "") for item in metric_families
        ]
        if (
            len(family_ids) != len(METRIC_FAMILIES)
            or sorted(family_ids) != sorted(METRIC_FAMILIES)
        ):
            errors.append(
                f"{experiment_id}: metricFamilies must cover outcome_quality, evidence_grounding, runtime_reliability, efficiency_cost and safety_recovery exactly once"
            )
        for index, raw_family in enumerate(metric_families, start=1):
            family = _mapping(raw_family)
            prefix = f"{experiment_id}: metricFamilies[{index}]"
            family_status = str(family.get("status") or "")
            if family_status not in METRIC_FAMILY_STATUSES:
                errors.append(
                    f"{prefix}: unsupported status: {family_status}"
                )
            metrics = _sequence(family.get("metrics"))
            if family_status == "measured" and not metrics:
                errors.append(f"{prefix}: measured family requires metrics")
            _require_text(errors, prefix, family, "reason")

        assets = _sequence(experiment.get("createdOrModifiedAssets"))
        if not assets:
            errors.append(
                f"{experiment_id}: createdOrModifiedAssets must be non-empty"
            )
        for index, raw_asset in enumerate(assets, start=1):
            asset = _mapping(raw_asset)
            prefix = f"{experiment_id}: createdOrModifiedAssets[{index}]"
            if str(asset.get("kind") or "") not in {
                "system_prompt",
                "tool",
                "workflow",
                "skill",
                "evaluator",
                "dataset",
            }:
                errors.append(f"{prefix}: unsupported kind: {asset.get('kind')}")
            for field in ("ref", "change"):
                _require_text(errors, prefix, asset, field)
            if repo_root is not None and _text(asset.get("ref")):
                asset_path = _repo_ref_path(str(asset["ref"]), repo_root)
                if asset_path is not None and not asset_path.exists():
                    errors.append(
                        f"{prefix}: asset ref does not exist: {asset['ref']}"
                    )

        require_comparison = status in {"kept", "rejected"}
        _validate_run_side(
            errors,
            experiment_id=experiment_id,
            name="baseline",
            value=experiment.get("baseline"),
            repo_root=repo_root,
            require_outputs=require_comparison,
        )
        _validate_run_side(
            errors,
            experiment_id=experiment_id,
            name="candidate",
            value=experiment.get("candidate"),
            repo_root=repo_root,
            require_outputs=require_comparison,
        )

        recommendations = _sequence(experiment.get("recommendations"))
        if not recommendations:
            errors.append(f"{experiment_id}: recommendations must be non-empty")
        recommendation_ids: set[str] = set()
        for raw_recommendation in recommendations:
            recommendation = _mapping(raw_recommendation)
            recommendation_id = str(recommendation.get("id") or "").strip() or "<missing-recommendation-id>"
            prefix = f"{experiment_id}/{recommendation_id}"
            if recommendation_id in recommendation_ids:
                errors.append(f"{experiment_id}: duplicate recommendation id: {recommendation_id}")
            recommendation_ids.add(recommendation_id)
            target = str(recommendation.get("targetLayer") or "")
            if target not in LAYERS:
                errors.append(f"{prefix}: unsupported targetLayer: {target}")
            for field in ("observation", "hypothesis", "proposedChange"):
                _require_text(errors, prefix, recommendation, field)
            _validate_refs(
                errors,
                prefix=prefix,
                value=recommendation.get("evidenceRefs"),
                repo_root=repo_root,
            )
            attribution = _mapping(recommendation.get("attribution"))
            for field in ATTRIBUTION_FIELDS:
                if not _text(attribution.get(field)):
                    errors.append(f"{prefix}: attribution.{field} is required")
            recommendation_status = str(recommendation.get("status") or "")
            if recommendation_status not in RECOMMENDATION_STATUSES:
                errors.append(
                    f"{prefix}: unsupported recommendation status: {recommendation_status}"
                )

        layers = _sequence(experiment.get("layerAssessments"))
        layer_ids = [str(_mapping(item).get("layer") or "") for item in layers]
        if len(layer_ids) != len(LAYERS) or sorted(layer_ids) != sorted(LAYERS):
            errors.append(
                f"{experiment_id}: layerAssessments must cover system_prompt, tool, workflow and skill exactly once"
            )
        for index, raw_layer in enumerate(layers, start=1):
            layer = _mapping(raw_layer)
            prefix = f"{experiment_id}: layerAssessments[{index}]"
            if str(layer.get("status") or "") not in LAYER_STATUSES:
                errors.append(f"{prefix}: unsupported status: {layer.get('status')}")
            _require_text(errors, prefix, layer, "reason")
        if candidate_type == "single_factor" and len(factors) == 1:
            factor_name = str(_mapping(factors[0]).get("name") or "")
            changed_layers = [
                str(_mapping(item).get("layer") or "")
                for item in layers
                if str(_mapping(item).get("status") or "") == "changed"
            ]
            expected_changed = {
                "model": [],
                "prompt": ["system_prompt"],
                "skill": ["skill"],
                "tool": ["tool"],
                "workflow": ["workflow"],
                "context": ["system_prompt"],
                "memory_rag": ["workflow"],
                "guardrail": ["workflow"],
            }.get(factor_name)
            if expected_changed is not None and changed_layers != expected_changed:
                expected_text = ", ".join(expected_changed) or "none of the four legacy layers"
                errors.append(
                    f"{experiment_id}: single_factor {factor_name} must mark exactly {expected_text} as changed"
                )

        comparison = _mapping(experiment.get("comparison"))
        if require_comparison:
            if not _sequence(comparison.get("metricDeltas")):
                errors.append(f"{experiment_id}: comparison.metricDeltas must be non-empty")
            if not _sequence(comparison.get("outputComparisons")):
                errors.append(f"{experiment_id}: comparison.outputComparisons must be non-empty")
        for index, raw_delta in enumerate(_sequence(comparison.get("metricDeltas")), start=1):
            delta = _mapping(raw_delta)
            prefix = f"{experiment_id}: comparison.metricDeltas[{index}]"
            _require_text(errors, prefix, delta, "metric")
            for field in ("before", "after", "delta"):
                value = delta.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"{prefix}: {field} must be numeric")
            before = delta.get("before")
            after = delta.get("after")
            change = delta.get("delta")
            if all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (before, after, change)
            ) and not math.isclose(
                float(change),
                float(after) - float(before),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                errors.append(f"{prefix}: delta must equal after - before")
        decision = str(comparison.get("decision") or "")
        expected_decision = {"kept": "keep", "rejected": "reject"}.get(status)
        if expected_decision is not None and decision != expected_decision:
            errors.append(
                f"{experiment_id}: comparison.decision must be {expected_decision} for status {status}"
            )
        _require_text(errors, f"{experiment_id}: comparison", comparison, "decisionReason")

        claim = _mapping(experiment.get("claim"))
        for field in ("resumeBullet", "allowed", "forbidden"):
            if not _text(claim.get(field)):
                errors.append(f"{experiment_id}: claim.{field} is required")
        if not isinstance(experiment.get("openGaps"), list):
            errors.append(f"{experiment_id}: openGaps must be a list")

    return errors


def validate_controlled_model_cost_receipts(
    payload: Mapping[str, object],
    *,
    repo_root: Path,
) -> list[str]:
    """Cross-bind the model-cost decision to comparable run and cost receipts."""

    prefix = "EnterpriseOps model-cost"
    errors: list[str] = []
    experiments = [
        item for item in _sequence(payload.get("experiments"))
        if isinstance(item, Mapping)
    ]
    experiment = next(
        (
            item for item in experiments
            if item.get("id") == "enterpriseops-csm.luna-model-only-r5.v1"
        ),
        None,
    )
    if experiment is None:
        return [f"{prefix}: required experiment row is missing"]
    experiment_status = str(experiment.get("status") or "")

    factor = next(
        (
            item for item in _sequence(experiment.get("factors"))
            if isinstance(item, Mapping) and item.get("name") == "model"
        ),
        {},
    )
    dataset = _mapping(experiment.get("dataset"))

    def load_receipts(
        side_name: str,
    ) -> tuple[
        Mapping[str, object],
        Mapping[str, object],
        Mapping[str, object],
    ]:
        side = _mapping(experiment.get(side_name))
        run_receipts: list[Mapping[str, object]] = []
        cost_receipts: list[Mapping[str, object]] = []
        for raw_ref in _sequence(side.get("evidenceRefs")):
            if not _text(raw_ref):
                continue
            path = _repo_ref_path(str(raw_ref), repo_root)
            if path is None or path.suffix != ".json" or not path.is_file():
                continue
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                errors.append(f"{prefix}: unreadable JSON evidence ref: {raw_ref}")
                continue
            if not isinstance(receipt, Mapping):
                continue
            if (
                receipt.get("schemaVersion") == "paw.enterpriseops-csm-eval.v1"
                and isinstance(receipt.get("evaluationContract"), Mapping)
            ):
                run_receipts.append(receipt)
            if receipt.get("schemaVersion") == "rag-ime.agent-lab-cost-receipt.v1":
                cost_receipts.append(receipt)
        if len(run_receipts) != 1:
            errors.append(
                f"{prefix}: {side_name} must reference exactly one raw EnterpriseOps evaluation receipt"
            )
        if len(cost_receipts) != 1:
            errors.append(
                f"{prefix}: {side_name} must reference exactly one Agent Lab cost receipt"
            )
        return (
            side,
            run_receipts[0] if len(run_receipts) == 1 else {},
            cost_receipts[0] if len(cost_receipts) == 1 else {},
        )

    baseline, baseline_run, baseline_cost = load_receipts("baseline")
    candidate, candidate_run, candidate_cost = load_receipts("candidate")
    if not baseline_run or not candidate_run or not baseline_cost or not candidate_cost:
        return errors

    baseline_contract = _mapping(baseline_run.get("evaluationContract"))
    candidate_contract = _mapping(candidate_run.get("evaluationContract"))
    baseline_thinking = str(baseline_contract.get("thinking") or "")
    candidate_thinking = str(candidate_contract.get("thinking") or "")
    if baseline_thinking != candidate_thinking:
        errors.append(f"{prefix}: baseline and candidate thinking must match")

    frozen_contract_fields = (
        "split",
        "workflowProfile",
        "suiteRevision",
        "overlaySha256",
        "taskManifestSha256",
        "toolCatalogSha256",
        "runnerSha256",
        "promptContractSha256",
        "timeoutSeconds",
        "effectiveTimeoutSeconds",
        "transport",
        "mcpEndpoint",
    )
    for field in frozen_contract_fields:
        if baseline_contract.get(field) != candidate_contract.get(field):
            errors.append(f"{prefix}: frozen contract field {field} must match")

    baseline_runtime = _mapping(baseline_run.get("runtimeIdentity"))
    candidate_runtime = _mapping(candidate_run.get("runtimeIdentity"))
    runtime_binary_fields = (
        "runtimeVersion",
        "manifestSha256",
        "entrypointSha256",
        "extensionSha256",
        "nodeSha256",
        "toolProfileSha256",
        "provider",
    )
    for field in runtime_binary_fields:
        if baseline_runtime.get(field) != candidate_runtime.get(field):
            errors.append(f"{prefix}: frozen Runtime binary field {field} must match")
    if baseline_runtime.get("identitySha256") == candidate_runtime.get("identitySha256"):
        errors.append(
            f"{prefix}: Runtime identitySha must change with the model-bearing identity"
        )
    if baseline_contract.get("runtimeProvenanceSha256") == candidate_contract.get(
        "runtimeProvenanceSha256"
    ):
        errors.append(
            f"{prefix}: Runtime provenanceSha must change with the model configuration"
        )

    manifest_sha = dataset.get("manifestSha256")
    for side_name, contract in (
        ("baseline", baseline_contract),
        ("candidate", candidate_contract),
    ):
        if contract.get("taskManifestSha256") != manifest_sha:
            errors.append(
                f"{prefix}: {side_name} receipt must match the ledger dataset manifest"
            )

    baseline_identity = (
        f"{baseline_contract.get('model', '')} / {baseline_thinking}"
    )
    candidate_identity = (
        f"{candidate_contract.get('model', '')} / {candidate_thinking}"
    )
    if factor.get("before") != baseline_identity:
        errors.append(f"{prefix}: baseline model identity must match the declared factor")
    if factor.get("after") != candidate_identity:
        errors.append(f"{prefix}: candidate model identity must match the declared factor")
    if baseline_contract.get("provider") != candidate_contract.get("provider"):
        errors.append(f"{prefix}: baseline and candidate provider route must match")
    if baseline_contract.get("model") == candidate_contract.get("model"):
        errors.append(f"{prefix}: single-factor comparison must change the model")

    def number(value: object) -> float | None:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    for side_name, side, run in (
        ("baseline", baseline, baseline_run),
        ("candidate", candidate, candidate_run),
    ):
        lane = _mapping(run.get("lane"))
        quality_gates_pass = (
            lane.get("taskSuccessRate") == 1
            and lane.get("verifierPassRate") == 1
            and lane.get("allDatabasesCleaned") is True
        )
        if side_name == "baseline" and not quality_gates_pass:
            errors.append(
                f"{prefix}: baseline raw receipt must pass task, verifier and cleanup gates"
            )
        if side_name == "candidate" and experiment_status == "kept" and not quality_gates_pass:
            errors.append(
                f"{prefix}: kept candidate raw receipt must pass task, verifier and cleanup gates"
            )
        ledger_metrics = _mapping(side.get("metrics"))
        for metric_name, receipt_name in (
            ("taskSuccessRate", "taskSuccessRate"),
            ("verifierPassRate", "verifierPassRate"),
            ("toolCalls", "toolCalls"),
            ("failedToolCalls", "failedToolCalls"),
            ("latencyMs", "latencyMs"),
        ):
            ledger_value = number(ledger_metrics.get(metric_name))
            receipt_value = number(lane.get(receipt_name))
            if (
                ledger_value is None
                or receipt_value is None
                or not math.isclose(
                    ledger_value,
                    receipt_value,
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                )
            ):
                errors.append(
                    f"{prefix}: {side_name}.{metric_name} must match its raw receipt"
                )
        cleanup_value = number(ledger_metrics.get("allDatabasesCleaned"))
        if cleanup_value != 1:
            errors.append(
                f"{prefix}: {side_name}.allDatabasesCleaned must match its raw receipt"
            )

    if experiment_status == "kept":
        baseline_failed_tools = number(_mapping(baseline_run.get("lane")).get("failedToolCalls"))
        candidate_failed_tools = number(_mapping(candidate_run.get("lane")).get("failedToolCalls"))
        if (
            baseline_failed_tools is None
            or candidate_failed_tools is None
            or candidate_failed_tools > baseline_failed_tools
        ):
            errors.append(
                f"{prefix}: kept candidate failed Tool calls must not exceed baseline"
            )

    def validate_cost(
        side_name: str,
        side: Mapping[str, object],
        contract: Mapping[str, object],
        cost: Mapping[str, object],
    ) -> None:
        usage = _mapping(cost.get("usage"))
        pricing = _mapping(cost.get("pricingIdentity"))
        estimate = _mapping(cost.get("estimate"))
        run_id = str(side.get("runId") or "")
        if usage.get("available") is not True:
            errors.append(f"{prefix}: {side_name} usage receipt must be available")
        if run_id not in str(usage.get("sourceRef") or ""):
            errors.append(f"{prefix}: {side_name} cost receipt must bind its run id")
        if pricing.get("model") != contract.get("model"):
            errors.append(f"{prefix}: {side_name} pricing model must match its run")
        ledger_metrics = _mapping(side.get("metrics"))
        receipt_cost = number(estimate.get("totalCostUsd"))
        ledger_cost = number(ledger_metrics.get("apiCostUsd"))
        if (
            receipt_cost is None
            or ledger_cost is None
            or not math.isclose(
                receipt_cost,
                ledger_cost,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        ):
            errors.append(
                f"{prefix}: {side_name}.apiCostUsd must match its cost receipt"
            )
        usage_total = sum(
            int(usage.get(name) or 0)
            for name in (
                "uncachedInputTokens",
                "cachedInputTokens",
                "outputTokens",
            )
        )
        if number(ledger_metrics.get("totalTokens")) != float(usage_total):
            errors.append(
                f"{prefix}: {side_name}.totalTokens must match its cost receipt"
            )

    validate_cost("baseline", baseline, baseline_contract, baseline_cost)
    validate_cost("candidate", candidate, candidate_contract, candidate_cost)
    baseline_pricing = _mapping(baseline_cost.get("pricingIdentity"))
    candidate_pricing = _mapping(candidate_cost.get("pricingIdentity"))
    for field in ("publishedDate", "sourceSha256", "sourceUrl", "currency", "unit"):
        if baseline_pricing.get(field) != candidate_pricing.get(field):
            errors.append(f"{prefix}: pricing snapshot field {field} must match")

    return errors


def validate_retained_api_pricing_estimates(
    payload: Mapping[str, object],
    *,
    repo_root: Path,
) -> list[str]:
    """Fail closed unless current model/cost optimizations bind price evidence.

    A lower token count is not a price claim.  Each side must bind one immutable
    raw report and one cost receipt, use one hashed pricing source, retain the
    project-specific quality gates, and preserve the absence of a Provider bill.
    Runtime-reconciled receipts are exact cost authority; older pricing estimates
    remain valid only under their original raw-report-bound contract.
    """

    errors: list[str] = []
    experiments = {
        str(item.get("id") or ""): item
        for item in _sequence(payload.get("experiments"))
        if isinstance(item, Mapping)
    }
    specs = (
        {
            "id": "enterpriseops-csm.luna-prompt-adaptation-r7.v1",
            "prefix": "EnterpriseOps retained cost",
            "rawSchema": "paw.enterpriseops-csm-eval.v1",
            "comparisonRef": (
                "eval/interview-metrics/runs/"
                "enterpriseops-csm-sol-to-luna-prompt-adaptation-20260904.r1.json"
            ),
            "status": "kept",
            "candidateType": "compound_repair",
            "comparisonKind": "enterprise_final",
            "qualityRule": "non_regression",
            "qualityMetrics": (
                "taskSuccessRate",
                "verifierPassRate",
                "failedToolCalls",
                "databasesCleaned",
            ),
        },
        {
            "id": "enterpriseops-csm.luna-model-only-r5.v1",
            "prefix": "EnterpriseOps model-only cost",
            "rawSchema": "paw.enterpriseops-csm-eval.v1",
            "comparisonRef": (
                "eval/interview-metrics/runs/"
                "enterpriseops-csm-sol-to-luna-prompt-adaptation-20260904.r1.json"
            ),
            "status": "rejected",
            "candidateType": "single_factor",
            "comparisonKind": "enterprise_model_only",
            "qualityRule": "expected_regression",
            "qualityMetrics": (
                "taskSuccessRate",
                "verifierPassRate",
                "failedToolCalls",
                "databasesCleaned",
            ),
        },
        {
            "id": "cloudops.luna-owner-mechanism-prompt-r5.v1",
            "prefix": "CloudOps retained cost",
            "rawSchema": "paw.cloudops-case-score-projection.v1",
            "comparisonRef": (
                "eval/interview-metrics/runs/"
                "cloudops-sol-to-luna-owner-mechanism-prompt-20260904.r1.json"
            ),
            "status": "kept",
            "candidateType": "compound_repair",
            "comparisonKind": "cloudops_final",
            "qualityRule": "non_regression",
            "qualityMetrics": (
                "answerCoverage",
                "ca",
                "fa",
                "jra",
                "top3Jra",
                "failedToolCalls",
            ),
            "pricingProvenanceFields": (
                "sourceSha256",
                "currency",
                "unit",
            ),
            "requireTargetExampleBoundary": False,
        },
        {
            "id": "cloudops.alert-first-luna-model-only-r1.v1",
            "prefix": "CloudOps model-only cost",
            "rawSchema": "paw.cloudops-case-score-projection.v1",
            "comparisonRef": (
                "eval/interview-metrics/runs/"
                "cloudops-sol-to-luna-owner-mechanism-prompt-20260904.r1.json"
            ),
            "status": "rejected",
            "candidateType": "single_factor",
            "comparisonKind": "cloudops_model_only",
            "qualityRule": "cloudops_expected_regression",
            "qualityMetrics": (
                "answerCoverage",
                "ca",
                "fa",
                "jra",
                "top3Jra",
                "failedToolCalls",
            ),
            "requireTargetExampleBoundary": False,
        },
        {
            "id": "memory.maintenance-luna-model-only-r1.v1",
            "prefix": "Memory retained cost",
            "rawSchema": "paw.memory-maintenance-validation-receipt.v1",
            "comparisonRef": (
                "eval/interview-metrics/runs/"
                "memory-maintenance-sol-to-luna-model-only-optimization-20260904.r1.json"
            ),
            "status": "kept",
            "candidateType": "single_factor",
            "comparisonKind": "memory_model_only",
            "qualityRule": "non_regression",
            "qualityMetrics": (
                "curationPassed",
                "durableRecallPassed",
                "abstentionPassed",
                "vectorCoverage",
                "rollbackPassed",
                "replayPassed",
                "receiptJsonValid",
            ),
        },
    )

    def number(value: object) -> Decimal | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    def decimal_text(value: Decimal) -> str:
        if value == 0:
            return "0"
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def canonical_sha256(value: Mapping[str, object]) -> str:
        try:
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return ""
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def token_count(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def receipt_usage(value: object) -> dict[str, int] | None:
        usage = _mapping(value)
        fields = (
            "uncachedInputTokens",
            "cachedInputTokens",
            "outputTokens",
        )
        counts = {name: token_count(usage.get(name)) for name in fields}
        if any(count is None for count in counts.values()):
            return None
        return {name: int(counts[name]) for name in fields}

    def estimate_from_usage(
        usage: Mapping[str, int], rates: Mapping[str, object]
    ) -> dict[str, str] | None:
        rate_fields = (
            "uncachedInputUsd",
            "cachedInputUsd",
            "outputUsd",
        )
        if any(not isinstance(rates.get(name), str) for name in rate_fields):
            return None
        parsed_rates = {name: number(rates.get(name)) for name in rate_fields}
        if any(value is None or value < 0 for value in parsed_rates.values()):
            return None
        with localcontext() as context:
            context.prec = 96
            uncached_cost = (
                Decimal(usage["uncachedInputTokens"])
                * parsed_rates["uncachedInputUsd"]
                / Decimal(1_000_000)
            )
            cached_cost = (
                Decimal(usage["cachedInputTokens"])
                * parsed_rates["cachedInputUsd"]
                / Decimal(1_000_000)
            )
            output_cost = (
                Decimal(usage["outputTokens"])
                * parsed_rates["outputUsd"]
                / Decimal(1_000_000)
            )
        return {
            "uncachedInputCostUsd": decimal_text(uncached_cost),
            "cachedInputCostUsd": decimal_text(cached_cost),
            "outputCostUsd": decimal_text(output_cost),
            "totalCostUsd": decimal_text(
                uncached_cost + cached_cost + output_cost
            ),
        }

    def content_addressed_pricing_id(
        pricing: Mapping[str, object],
    ) -> str | None:
        rates = _mapping(pricing.get("rates"))
        parsed_rates = {
            name: number(rates.get(name))
            for name in (
                "uncachedInputUsd",
                "cachedInputUsd",
                "outputUsd",
            )
        }
        if (
            any(not isinstance(rates.get(name), str) for name in parsed_rates)
            or any(value is None or value < 0 for value in parsed_rates.values())
            or not _text(pricing.get("provider"))
            or not _text(pricing.get("model"))
            or pricing.get("currency") != "USD"
            or pricing.get("unit") != "per_million_tokens"
            or not _text(pricing.get("publishedDate"))
            or not _text(pricing.get("sourceUrl"))
            or not _SHA256.fullmatch(str(pricing.get("sourceSha256") or ""))
        ):
            return None
        identity = {
            "provider": str(pricing["provider"]),
            "model": str(pricing["model"]),
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": {
                name: decimal_text(parsed_rates[name])
                for name in parsed_rates
            },
            "publishedDate": str(pricing["publishedDate"]),
            "sourceUrl": str(pricing["sourceUrl"]),
            "sourceSha256": str(pricing["sourceSha256"]),
        }
        return f"pricing:sha256:{canonical_sha256(identity)}"

    def load_json(path: Path, *, prefix: str) -> Mapping[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"{prefix}: unreadable JSON evidence: {path.relative_to(repo_root)}")
            return {}
        if not isinstance(value, Mapping):
            errors.append(f"{prefix}: JSON evidence must be an object: {path.relative_to(repo_root)}")
            return {}
        return value

    def raw_usage(
        raw: Mapping[str, object], *, raw_schema: str
    ) -> tuple[dict[str, int] | None, str, str]:
        if raw_schema == "paw.enterpriseops-csm-eval.v1":
            tasks = _sequence(_mapping(raw.get("lane")).get("tasks"))
            usage = {"uncachedInputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0}
            for task in tasks:
                task_usage = _mapping(_mapping(task).get("usage"))
                counts = {
                    "uncachedInputTokens": token_count(task_usage.get("input")),
                    "cachedInputTokens": token_count(task_usage.get("cacheRead")),
                    "outputTokens": token_count(task_usage.get("output")),
                }
                if any(count is None for count in counts.values()):
                    return None, "", ""
                for name, count in counts.items():
                    usage[name] += int(count)
            contract = _mapping(raw.get("evaluationContract"))
            return usage, str(contract.get("model") or ""), str(contract.get("thinking") or "")
        if raw_schema == "paw.cloudops-case-score-projection.v1":
            raw_counts = _mapping(raw.get("usage"))
            counts = {
                "uncachedInputTokens": token_count(raw_counts.get("input")),
                "cachedInputTokens": token_count(raw_counts.get("cacheRead")),
                "outputTokens": token_count(raw_counts.get("output")),
            }
            usage = (
                None
                if any(count is None for count in counts.values())
                else {name: int(counts[name]) for name in counts}
            )
            runtime = _mapping(raw.get("runtime"))
            return (
                usage,
                str(runtime.get("model") or ""),
                str(runtime.get("thinking") or ""),
            )
        return (
            receipt_usage(raw.get("usage")),
            str(raw.get("model") or ""),
            str(raw.get("thinking") or ""),
        )

    for spec in specs:
        experiment_id = str(spec["id"])
        prefix = str(spec["prefix"])
        experiment = experiments.get(experiment_id)
        if not isinstance(experiment, Mapping):
            errors.append(f"{prefix}: required experiment row is missing")
            continue
        if (
            experiment.get("status") != spec["status"]
            or experiment.get("candidateType") != spec["candidateType"]
        ):
            errors.append(
                f"{prefix}: price qualification requires a {spec['status']} "
                f"{spec['candidateType']} experiment"
            )
        if experiment.get("projectionState") not in {"current", "history"}:
            errors.append(f"{prefix}: experiment projection state is invalid")

        loaded: dict[str, tuple[Mapping[str, object], Mapping[str, object], Path, Path]] = {}
        for side_name in ("baseline", "candidate"):
            side = _mapping(experiment.get(side_name))
            raw_matches: list[tuple[Mapping[str, object], Path]] = []
            cost_matches: list[tuple[Mapping[str, object], Path]] = []
            for raw_ref in _sequence(side.get("evidenceRefs")):
                if not _text(raw_ref):
                    continue
                path = _repo_ref_path(str(raw_ref), repo_root)
                if path is None or path.suffix != ".json" or not path.is_file():
                    continue
                receipt = load_json(path, prefix=prefix)
                if receipt.get("schemaVersion") == spec["rawSchema"]:
                    raw_matches.append((receipt, path))
                if receipt.get("schemaVersion") == "rag-ime.agent-lab-cost-receipt.v1":
                    cost_matches.append((receipt, path))
            if len(raw_matches) != 1:
                errors.append(f"{prefix}: {side_name} must bind exactly one raw usage report")
            if len(cost_matches) != 1:
                errors.append(f"{prefix}: {side_name} must bind exactly one deterministic cost receipt")
            if len(raw_matches) == 1 and len(cost_matches) == 1:
                loaded[side_name] = (
                    raw_matches[0][0],
                    cost_matches[0][0],
                    raw_matches[0][1],
                    cost_matches[0][1],
                )
        if set(loaded) != {"baseline", "candidate"}:
            continue

        pricing_snapshots: list[Mapping[str, object]] = []
        authorities: dict[str, str] = {}
        side_costs: dict[str, Decimal] = {}
        cost_names: dict[str, str] = {}
        for side_name in ("baseline", "candidate"):
            side = _mapping(experiment.get(side_name))
            metrics = _mapping(side.get("metrics"))
            raw, cost, raw_path, cost_path = loaded[side_name]
            cost_names[side_name] = cost_path.name
            usage = _mapping(cost.get("usage"))
            pricing = _mapping(cost.get("pricingIdentity"))
            rates = _mapping(pricing.get("rates"))
            estimate = _mapping(cost.get("estimate"))
            billing = _mapping(cost.get("billing"))
            pricing_snapshots.append(pricing)

            authority = str(cost.get("authority") or "")
            authorities[side_name] = authority
            if authority not in {"pricing_estimate", "runtime_cost_reconciled"}:
                errors.append(
                    f"{prefix}: {side_name} authority must be pricing_estimate "
                    "or runtime_cost_reconciled"
                )
            if billing.get("status") != "not_provided" or metrics.get("providerBillAvailable") != 0:
                errors.append(f"{prefix}: {side_name} must not claim a Provider bill")
            run_id = str(side.get("runId") or "")
            if run_id not in str(usage.get("sourceRef") or ""):
                errors.append(f"{prefix}: {side_name} cost receipt must bind its exact run id")
            source_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            trial_source_sha = source_sha
            if spec["rawSchema"] == "paw.cloudops-case-score-projection.v1":
                raw_evidence = _mapping(raw.get("evidence"))
                trial_source_sha = str(
                    raw_evidence.get("sourceArtifactSha256")
                    or raw_evidence.get("privateArtifactSha256")
                    or ""
                )
                if not _SHA256.fullmatch(trial_source_sha):
                    errors.append(
                        f"{prefix}: {side_name} CloudOps projection must bind "
                        "its source trial artifact hash"
                    )

            expected_usage, raw_model, raw_thinking = raw_usage(
                raw, raw_schema=str(spec["rawSchema"])
            )
            if expected_usage is None:
                errors.append(
                    f"{prefix}: {side_name} raw report usage must contain three "
                    "non-negative integer categories"
                )
                expected_usage = {
                    "uncachedInputTokens": 0,
                    "cachedInputTokens": 0,
                    "outputTokens": 0,
                }
            if pricing.get("model") != raw_model or raw_thinking != "max":
                errors.append(f"{prefix}: {side_name} pricing must bind the raw model/max identity")

            measured_usage = receipt_usage(usage)
            if usage.get("available") is not True or measured_usage is None:
                errors.append(
                    f"{prefix}: {side_name} receipt usage must contain three "
                    "non-negative integers"
                )
                measured_usage = {
                    "uncachedInputTokens": 0,
                    "cachedInputTokens": 0,
                    "outputTokens": 0,
                }
            expected_estimate = estimate_from_usage(measured_usage, rates)
            if expected_estimate is None:
                errors.append(f"{prefix}: {side_name} pricing rates must be complete exact decimals")
            elif dict(estimate) != expected_estimate:
                errors.append(f"{prefix}: {side_name} estimate must be recomputed from usage and rates")

            runtime_value = cost.get("runtimeCostReceipt")
            if authority == "pricing_estimate":
                if runtime_value is not None:
                    errors.append(
                        f"{prefix}: {side_name} pricing_estimate must not include "
                        "runtimeCostReceipt"
                    )
                if usage.get("sourceSha256") != source_sha:
                    errors.append(
                        f"{prefix}: {side_name} usage source hash must match the raw report"
                    )
                if measured_usage != expected_usage:
                    errors.append(
                        f"{prefix}: {side_name} usage must match all three raw categories"
                    )
            elif authority == "runtime_cost_reconciled":
                expected_pricing_id = content_addressed_pricing_id(pricing)
                if (
                    expected_pricing_id is None
                    or pricing.get("pricingId") != expected_pricing_id
                ):
                    errors.append(
                        f"{prefix}: {side_name} pricingId must match its "
                        "content-addressed pricing identity"
                    )
                if not isinstance(runtime_value, Mapping):
                    errors.append(
                        f"{prefix}: {side_name} runtime_cost_reconciled requires "
                        "runtimeCostReceipt"
                    )
                else:
                    runtime = runtime_value
                    request_count = runtime.get("requestCount")
                    if (
                        isinstance(request_count, bool)
                        or not isinstance(request_count, int)
                        or request_count < 1
                        or request_count > 1_000_000
                    ):
                        errors.append(
                            f"{prefix}: {side_name} runtime requestCount must be "
                            "a positive integer"
                        )
                    database_value = _mapping(runtime.get("databaseUsage"))
                    database_usage = receipt_usage(database_value)
                    if (
                        set(database_value)
                        != {
                            "uncachedInputTokens",
                            "cachedInputTokens",
                            "outputTokens",
                        }
                        or database_usage is None
                    ):
                        errors.append(
                            f"{prefix}: {side_name} runtime databaseUsage must "
                            "contain three non-negative integers"
                        )
                    elif database_usage != measured_usage:
                        errors.append(
                            f"{prefix}: {side_name} runtime databaseUsage must "
                            "match the receipt usage"
                        )
                    runtime_db_sha = str(runtime.get("runtimeDbSha256") or "")
                    transcript_shas = runtime.get("transcriptSha256s")
                    if not _SHA256.fullmatch(runtime_db_sha):
                        errors.append(
                            f"{prefix}: {side_name} runtimeDbSha256 must be a "
                            "lowercase SHA-256"
                        )
                    if (
                        not isinstance(transcript_shas, list)
                        or not transcript_shas
                        or any(
                            not isinstance(value, str)
                            or not _SHA256.fullmatch(value)
                            for value in transcript_shas
                        )
                        or len(transcript_shas) != len(set(transcript_shas))
                    ):
                        errors.append(
                            f"{prefix}: {side_name} runtime transcript hashes "
                            "must be non-empty, unique lowercase SHA-256 values"
                        )

                    reported = _mapping(runtime.get("reportedCostUsd"))
                    reported_to_estimate = {
                        "input": "uncachedInputCostUsd",
                        "cacheRead": "cachedInputCostUsd",
                        "output": "outputCostUsd",
                        "total": "totalCostUsd",
                    }
                    if (
                        set(reported) != set(reported_to_estimate)
                        or any(
                            not isinstance(reported.get(reported_name), str)
                            or number(reported.get(reported_name)) is None
                            or number(reported.get(reported_name))
                            != number(estimate.get(estimate_name))
                            for reported_name, estimate_name in reported_to_estimate.items()
                        )
                    ):
                        errors.append(
                            f"{prefix}: {side_name} runtime reportedCostUsd must "
                            "match the receipt estimate"
                        )

                    runtime_body = dict(runtime)
                    runtime_sha = str(runtime_body.pop("sourceSha256", ""))
                    if (
                        not _SHA256.fullmatch(runtime_sha)
                        or runtime_sha != canonical_sha256(runtime_body)
                    ):
                        errors.append(
                            f"{prefix}: {side_name} runtimeCostReceipt source hash "
                            "is invalid"
                        )
                    if (
                        usage.get("sourceRef") != f"runtime-cost:{run_id}"
                        or usage.get("sourceSha256") != runtime_sha
                    ):
                        errors.append(
                            f"{prefix}: {side_name} usage must bind the exact "
                            "runtimeCostReceipt"
                        )

                    trial_value = runtime.get("trialAggregate")
                    if trial_value is not None:
                        trial = _mapping(trial_value)
                        trial_usage = receipt_usage(trial)
                        if (
                            set(trial)
                            != {
                                "sourceRef",
                                "sourceSha256",
                                "uncachedInputTokens",
                                "cachedInputTokens",
                                "outputTokens",
                            }
                            or trial_usage is None
                            or run_id not in str(trial.get("sourceRef") or "")
                            or trial.get("sourceSha256") != trial_source_sha
                            or trial_usage != expected_usage
                        ):
                            errors.append(
                                f"{prefix}: {side_name} trialAggregate must "
                                "independently bind the raw trial report"
                            )

            receipt_body = dict(cost)
            receipt_sha = receipt_body.pop("receiptSha256", None)
            if receipt_sha != canonical_sha256(receipt_body):
                errors.append(f"{prefix}: {side_name} receipt hash is invalid")

            total_cost = number(estimate.get("totalCostUsd"))
            if total_cost is not None and expected_estimate is not None:
                side_costs[side_name] = total_cost
            if authority == "pricing_estimate":
                ledger_cost = number(metrics.get("apiCostUsd"))
                if total_cost is None or ledger_cost != total_cost:
                    errors.append(
                        f"{prefix}: {side_name}.apiCostUsd must match its "
                        "deterministic cost receipt"
                    )
                expected_total_tokens = sum(expected_usage.values())
                if number(metrics.get("totalTokens")) != Decimal(expected_total_tokens):
                    errors.append(
                        f"{prefix}: {side_name}.totalTokens must match its three "
                        "usage categories"
                    )
            if metrics.get("costReceiptAvailable") != 1:
                errors.append(f"{prefix}: {side_name}.costReceiptAvailable must be 1")

        pricing_provenance_fields = tuple(
            spec.get(
                "pricingProvenanceFields",
                (
                    "publishedDate",
                    "sourceSha256",
                    "sourceUrl",
                    "currency",
                    "unit",
                ),
            )
        )
        if any(
            pricing_snapshots[0].get(field) != pricing_snapshots[1].get(field)
            for field in pricing_provenance_fields
        ):
            errors.append(
                f"{prefix}: baseline and candidate pricing source provenance must be identical"
            )
        if authorities.get("baseline") != authorities.get("candidate"):
            errors.append(
                f"{prefix}: baseline and candidate cost authority must match"
            )

        baseline_metrics = _mapping(_mapping(experiment.get("baseline")).get("metrics"))
        candidate_metrics = _mapping(_mapping(experiment.get("candidate")).get("metrics"))
        for metric_name in spec["qualityMetrics"]:
            before = number(baseline_metrics.get(metric_name))
            after = number(candidate_metrics.get(metric_name))
            if before is None or after is None:
                errors.append(f"{prefix}: quality metric {metric_name} must be complete")
                continue
            if metric_name == "failedToolCalls":
                non_regressed = after <= before
            else:
                non_regressed = after >= before
            if spec["qualityRule"] == "non_regression" and not non_regressed:
                errors.append(f"{prefix}: quality metric {metric_name} regressed")
        if spec["qualityRule"] == "expected_regression" and not (
            number(baseline_metrics.get("taskSuccessCount")) == Decimal(3)
            and number(candidate_metrics.get("taskSuccessCount")) == Decimal(2)
            and number(baseline_metrics.get("verifierPassCount")) == Decimal(31)
            and number(candidate_metrics.get("verifierPassCount")) == Decimal(30)
        ):
            errors.append(
                f"{prefix}: model-only Reject must retain the 3/3 to 2/3 and "
                "31/31 to 30/31 quality regression"
            )
        if spec["qualityRule"] == "cloudops_expected_regression" and not (
            number(baseline_metrics.get("ca")) == Decimal(1)
            and number(candidate_metrics.get("ca"))
            == Decimal("0.9166666666666666")
            and number(baseline_metrics.get("jra"))
            == Decimal("0.8333333333333334")
            and number(candidate_metrics.get("jra")) == Decimal("0.75")
            and number(baseline_metrics.get("top3Jra")) == Decimal(1)
            and number(candidate_metrics.get("top3Jra"))
            == Decimal("0.9166666666666666")
            and number(baseline_metrics.get("failedToolCalls")) == Decimal(1)
            and number(candidate_metrics.get("failedToolCalls")) == Decimal(6)
        ):
            errors.append(
                f"{prefix}: model-only Reject must retain the CA/JRA/Top3JRA "
                "and Tool reliability regression"
            )

        if set(side_costs) == {"baseline", "candidate"}:
            before = side_costs["baseline"]
            after = side_costs["candidate"]
            if before <= 0 or after >= before:
                errors.append(f"{prefix}: candidate deterministic API estimate must decrease")
            decrease_percent = (before - after) * Decimal(100) / before
            authority = authorities.get("baseline")
            if authority == "pricing_estimate":
                comparison = _mapping(experiment.get("comparison"))
                cost_delta = next(
                    (
                        _mapping(item)
                        for item in _sequence(comparison.get("metricDeltas"))
                        if _mapping(item).get("metric") == "apiCostUsd"
                    ),
                    {},
                )
                if (
                    number(cost_delta.get("before")) != before
                    or number(cost_delta.get("after")) != after
                    or number(cost_delta.get("delta")) != after - before
                ):
                    errors.append(
                        f"{prefix}: ledger apiCostUsd delta must match both receipts"
                    )

            comparison_path = repo_root / str(spec["comparisonRef"])
            comparison_receipt = load_json(comparison_path, prefix=prefix)
            comparison_body = _mapping(comparison_receipt.get("comparison"))
            comparison_kind = str(spec["comparisonKind"])

            def evidence_binding_matches(
                evidence: Mapping[str, object],
                *,
                raw_ref_field: str,
                raw_hash_field: str,
                cost_ref_field: str,
                cost_hash_field: str,
                side_name: str,
            ) -> bool:
                raw, cost, raw_path, cost_path = loaded[side_name]
                raw_ref = str(raw_path.relative_to(repo_root))
                cost_ref = str(cost_path.relative_to(repo_root))
                return (
                    evidence.get(raw_ref_field) == raw_ref
                    and evidence.get(raw_hash_field)
                    == hashlib.sha256(raw_path.read_bytes()).hexdigest()
                    and evidence.get(cost_ref_field) == cost_ref
                    and evidence.get(cost_hash_field)
                    == hashlib.sha256(cost_path.read_bytes()).hexdigest()
                    and (
                        "costReceiptSha256" not in evidence
                        or evidence.get("costReceiptSha256")
                        == cost.get("receiptSha256")
                    )
                )

            if comparison_kind.startswith("enterprise_"):
                comparison_evidence = _mapping(comparison_receipt.get("evidence"))
                candidate_evidence_name = (
                    "lunaPromptAdapted"
                    if comparison_kind == "enterprise_final"
                    else "lunaModelOnly"
                )
                baseline_evidence = _mapping(comparison_evidence.get("solBaseline"))
                candidate_evidence = _mapping(
                    comparison_evidence.get(candidate_evidence_name)
                )
                evidence_ok = evidence_binding_matches(
                    baseline_evidence,
                    raw_ref_field="rawRef",
                    raw_hash_field="rawFileSha256",
                    cost_ref_field="costRef",
                    cost_hash_field="costFileSha256",
                    side_name="baseline",
                ) and evidence_binding_matches(
                    candidate_evidence,
                    raw_ref_field="rawRef",
                    raw_hash_field="rawFileSha256",
                    cost_ref_field="costRef",
                    cost_hash_field="costFileSha256",
                    side_name="candidate",
                )
                stages = {
                    str(_mapping(item).get("stage") or ""): _mapping(item)
                    for item in _sequence(comparison_body.get("stages"))
                }
                stage_name = (
                    "luna_prompt_adapted"
                    if comparison_kind == "enterprise_final"
                    else "luna_model_only"
                )
                costs_match = (
                    number(_mapping(stages.get("sol_baseline")).get("costUsd"))
                    == before
                    and number(_mapping(stages.get(stage_name)).get("costUsd"))
                    == after
                )
                decrease_matches = True
                if comparison_kind == "enterprise_final":
                    cost_comparison = _mapping(
                        _mapping(comparison_body.get("costComparisons")).get(
                            "solToPromptAdapted"
                        )
                    )
                    reported_decrease = number(
                        cost_comparison.get("decreasePercent")
                    )
                    decrease_matches = (
                        number(cost_comparison.get("baselineTotalUsd")) == before
                        and number(cost_comparison.get("candidateTotalUsd")) == after
                        and reported_decrease is not None
                        and abs(reported_decrease - decrease_percent)
                        <= Decimal("0.000000000001")
                    )
                receipt_body = dict(comparison_receipt)
                receipt_sha = receipt_body.pop("receiptSha256", None)
                receipt_sealed = receipt_sha == canonical_sha256(receipt_body)
                if not (
                    comparison_body.get("costAuthority")
                    == "runtime_cost_reconciled"
                    and comparison_body.get("providerBillAvailable") is False
                    and evidence_ok
                    and costs_match
                    and decrease_matches
                    and receipt_sealed
                ):
                    errors.append(
                        f"{prefix}: comparison receipt must bind its qualified cost authority"
                    )
            elif comparison_kind.startswith("cloudops_"):
                comparison_evidence = _mapping(comparison_receipt.get("evidence"))
                candidate_evidence_name = (
                    "lunaPromptAdapted"
                    if comparison_kind == "cloudops_final"
                    else "lunaModelOnly"
                )
                baseline_evidence = _mapping(comparison_evidence.get("solBaseline"))
                candidate_evidence = _mapping(
                    comparison_evidence.get(candidate_evidence_name)
                )
                evidence_ok = evidence_binding_matches(
                    baseline_evidence,
                    raw_ref_field="runRef",
                    raw_hash_field="runFileSha256",
                    cost_ref_field="costRef",
                    cost_hash_field="costFileSha256",
                    side_name="baseline",
                ) and evidence_binding_matches(
                    candidate_evidence,
                    raw_ref_field="runRef",
                    raw_hash_field="runFileSha256",
                    cost_ref_field="costRef",
                    cost_hash_field="costFileSha256",
                    side_name="candidate",
                )
                stages = {
                    str(_mapping(item).get("stage") or ""): _mapping(item)
                    for item in _sequence(comparison_body.get("stages"))
                }
                stage_name = (
                    "luna_prompt_adapted"
                    if comparison_kind == "cloudops_final"
                    else "luna_model_only"
                )
                costs_match = (
                    number(_mapping(stages.get("sol_baseline")).get("costUsd"))
                    == before
                    and number(_mapping(stages.get(stage_name)).get("costUsd"))
                    == after
                )
                decrease_matches = True
                if comparison_kind == "cloudops_final":
                    cost_comparison = _mapping(
                        _mapping(comparison_body.get("costComparisons")).get(
                            "solToPromptAdapted"
                        )
                    )
                    reported_decrease = number(
                        cost_comparison.get("decreasePercent")
                    )
                    decrease_matches = (
                        number(cost_comparison.get("baselineTotalUsd")) == before
                        and number(cost_comparison.get("candidateTotalUsd")) == after
                        and reported_decrease is not None
                        and abs(reported_decrease - decrease_percent)
                        <= Decimal("0.000000000001")
                    )
                receipt_body = dict(comparison_receipt)
                receipt_sha = receipt_body.pop("receiptSha256", None)
                receipt_sealed = receipt_sha == canonical_sha256(receipt_body)
                pricing_source_sha = comparison_body.get("pricingSourceSha256")
                if not (
                    comparison_body.get("costAuthority")
                    == "runtime_cost_reconciled"
                    and comparison_body.get("providerBillAvailable") is False
                    and pricing_source_sha
                    == pricing_snapshots[0].get("sourceSha256")
                    == pricing_snapshots[1].get("sourceSha256")
                    and evidence_ok
                    and costs_match
                    and decrease_matches
                    and receipt_sealed
                ):
                    errors.append(
                        f"{prefix}: comparison receipt must bind its qualified cost authority"
                    )
            elif comparison_kind == "memory_model_only":
                cost_comparison = _mapping(comparison_body.get("cost"))
                comparison_evidence = _mapping(comparison_receipt.get("evidence"))
                evidence_ok = evidence_binding_matches(
                    comparison_evidence,
                    raw_ref_field="baselineRef",
                    raw_hash_field="baselineFileSha256",
                    cost_ref_field="baselineCostReceiptRef",
                    cost_hash_field="baselineCostReceiptFileSha256",
                    side_name="baseline",
                ) and evidence_binding_matches(
                    comparison_evidence,
                    raw_ref_field="candidateRef",
                    raw_hash_field="candidateFileSha256",
                    cost_ref_field="candidateCostReceiptRef",
                    cost_hash_field="candidateCostReceiptFileSha256",
                    side_name="candidate",
                )
                reported_decrease = number(cost_comparison.get("decreasePercent"))
                if not (
                    comparison_body.get("costAuthority")
                    == "deterministic_pricing_estimate_from_reported_usage"
                    and number(cost_comparison.get("baselineTotalUsd")) == before
                    and number(cost_comparison.get("candidateTotalUsd")) == after
                    and reported_decrease is not None
                    and abs(reported_decrease - decrease_percent)
                    <= Decimal("0.000000000001")
                    and cost_comparison.get("pricingSourceSha256")
                    == pricing_snapshots[0].get("sourceSha256")
                    and cost_comparison.get("providerBillAvailable") is False
                    and comparison_body.get("promptAdaptationNeeded") is False
                    and evidence_ok
                ):
                    errors.append(
                        f"{prefix}: comparison receipt must bind its qualified cost authority"
                    )

        forbidden = str(_mapping(experiment.get("claim")).get("forbidden") or "")
        if (
            spec.get("requireTargetExampleBoundary", True)
            and "80%" not in forbidden
        ) or "Provider 实际账单节省" not in forbidden:
            errors.append(f"{prefix}: claim boundary must forbid 80% and Provider-billed savings")

    rag_ids = {
        "enterprise-rag.sol-max-standard-r6.v1",
        "enterprise-rag.luna-model-only-standard-r6.v1",
        "enterprise-rag.luna-prompt-v4-standard-r6.v1",
    }
    if rag_ids & set(experiments):
        prefix = "Enterprise RAG retained cost"
        missing = sorted(rag_ids - set(experiments))
        if missing:
            errors.append(
                f"{prefix}: incomplete r6 stage rows: {', '.join(missing)}"
            )
            return errors

        rag_sol = _mapping(
            experiments["enterprise-rag.sol-max-standard-r6.v1"]
        )
        rag_model = _mapping(
            experiments["enterprise-rag.luna-model-only-standard-r6.v1"]
        )
        rag_final = _mapping(
            experiments["enterprise-rag.luna-prompt-v4-standard-r6.v1"]
        )
        rag_comparison = _mapping(rag_final.get("comparison"))
        cost_evidence = _mapping(rag_comparison.get("costEvidence"))
        rescore_evidence = _mapping(rag_comparison.get("rescoreEvidence"))
        standard_evidence = _mapping(rag_comparison.get("standardEvidence"))

        standard_ref = (
            "eval/interview-metrics/"
            "enterprise-rag-answer-evidence-standard.validation-"
            "candidate-aware-attention-r6.json"
        )
        calibration_ref = (
            "eval/interview-metrics/runs/"
            "enterprise-rag-answer-evidence-standard-candidate-aware-"
            "attention-r6-calibration-20260905.v1.json"
        )
        expected_standard_file_sha = (
            "f424ac5343c67880ede77cee241428f83d50aa562ba0905dceac5b3d5fdb01e8"
        )
        expected_standard_manifest_sha = (
            "6a4f6e35dbc0987a346649a19a48de5938f1b06e9c60e9be7dd2d4a2f6466c3e"
        )
        expected_calibration_file_sha = (
            "e3665f3ac3c59e8c25ace3a09f1515f4574c27f2d4096ac259e692c792c72df9"
        )
        expected_calibration_receipt_sha = (
            "f7d7a9e3002fb186401c4f11e2aaf6e1e70bcf67e91e00991c40459ef19084d0"
        )

        def file_sha256(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        standard_path = repo_root / standard_ref
        calibration_path = repo_root / calibration_ref
        standard = load_json(standard_path, prefix=prefix)
        calibration = load_json(calibration_path, prefix=prefix)
        standard_body = dict(standard)
        standard_manifest_sha = standard_body.pop("manifestSha256", None)
        calibration_body = dict(calibration)
        calibration_receipt_sha = calibration_body.pop("receiptSha256", None)
        if not (
            standard_evidence.get("standardRef") == standard_ref
            and standard_evidence.get("standardFileSha256")
            == expected_standard_file_sha
            and standard_path.is_file()
            and file_sha256(standard_path) == expected_standard_file_sha
            and standard_manifest_sha == expected_standard_manifest_sha
            and canonical_sha256(standard_body) == expected_standard_manifest_sha
            and standard.get("schemaVersion")
            == "rag-ime.rag-answer-evidence-standard.v2"
            and standard.get("calibrationLabel") == "post-validation-calibrated"
            and standard.get("evaluationScope") == "validation-development-only"
            and standard.get("candidateBlind") is False
            and standard.get("heldOutOpened") is False
            and standard.get("unbiasedPromotionClaimAllowed") is False
        ):
            errors.append(
                f"{prefix}: r6 Standard hash and post-Validation boundary must remain fixed"
            )
        if not (
            standard_evidence.get("calibrationReceiptRef") == calibration_ref
            and standard_evidence.get("calibrationReceiptFileSha256")
            == expected_calibration_file_sha
            and standard_evidence.get("calibrationReceiptSha256")
            == expected_calibration_receipt_sha
            and calibration_path.is_file()
            and file_sha256(calibration_path) == expected_calibration_file_sha
            and calibration_receipt_sha == expected_calibration_receipt_sha
            and canonical_sha256(calibration_body)
            == expected_calibration_receipt_sha
            and calibration.get("status") == "passed"
            and calibration.get("evaluationScope")
            == "validation-development-only"
            and calibration.get("candidateAware") is True
            and calibration.get("candidateBlind") is False
            and calibration.get("heldOutOpened") is False
            and calibration.get("unbiasedPromotionClaimAllowed") is False
            and calibration.get("providerCalls") == 0
            and calibration.get("judgeCalls") == 0
            and calibration.get("candidateRuns") == 0
            and _mapping(calibration.get("qrels")).get("factCount") == 9
            and _mapping(calibration.get("qrels")).get("evidenceBindingCount")
            == 20
            and _mapping(calibration.get("solControl")).get("coveredFactCount")
            == 7
            and _mapping(calibration.get("solControl")).get("decision")
            == "reject"
            and _mapping(calibration.get("lunaModelOnlyControl")).get(
                "coveredFactCount"
            )
            == 8
            and _mapping(calibration.get("lunaModelOnlyControl")).get(
                "decision"
            )
            == "reject"
            and _mapping(calibration.get("lunaPromptV4Rescore")).get(
                "coveredFactCount"
            )
            == 9
            and _mapping(calibration.get("lunaPromptV4Rescore")).get("decision")
            == "keep"
            and all(
                value is False
                for value in _mapping(calibration.get("publicSafety")).values()
            )
        ):
            errors.append(
                f"{prefix}: r6 calibration receipt must retain candidate-aware "
                "7/9 Reject, 8/9 Reject and 9/9 Keep evidence"
            )

        stage_specs = {
            "solBaseline": {
                "runId": "enterprise-rag-sol-max-frozen-v19-20260904-r4",
                "model": "openai-codex/gpt-5.6-sol",
                "ledgerSide": _mapping(rag_final.get("baseline")),
                "facts": 7,
                "decision": "reject",
                "cost": Decimal("2.170603"),
                "totalTokens": 892697,
                "costRef": (
                    "eval/interview-metrics/runs/"
                    "agent-lab-cost-enterprise-rag-sol-max-frozen-v19-"
                    "20260904.r4.v1.json"
                ),
                "costFileSha": (
                    "efb49554a3d5840ea824f9bbbb70edeffce0a8f9a55205fdc0c78e8b2dc2b0ae"
                ),
                "costReceiptSha": (
                    "42a2c8244ff8bf8610f05103266b6d780b49b136820b87a55484f358dee5c186"
                ),
                "rescoreRef": (
                    "eval/interview-metrics/runs/"
                    "enterprise-rag-answer-evidence-sol-max-frozen-v19-r4-"
                    "attention-r6-exact-offline-rescore-20260905.v1.json"
                ),
                "rescoreFileSha": (
                    "1ef90fc42ffa05fc0f8550a49165965b2871169aadde951e12b22defd9191ae9"
                ),
                "rescoreReceiptSha": (
                    "4f4fda6266dc84fd5145b7cb0e270c8d1fd5c7caf8c7855b48f206fb94a018e9"
                ),
                "sourceReportFileSha": (
                    "667ca9403f70dca05b0d2cf4864ef21e6dce610f4c939656efae64fce1a95671"
                ),
                "ledgerLabel": "Sol baseline",
            },
            "lunaModelOnly": {
                "runId": "enterprise-rag-luna-max-model-only-v19-20260904-r4",
                "model": "openai-codex/gpt-5.6-luna",
                "ledgerSide": _mapping(rag_model.get("candidate")),
                "facts": 8,
                "decision": "reject",
                "cost": Decimal("0.10594896"),
                "totalTokens": 926570,
                "costRef": (
                    "eval/interview-metrics/runs/"
                    "agent-lab-cost-enterprise-rag-luna-max-model-only-v19-"
                    "20260904.r4.v1.json"
                ),
                "costFileSha": (
                    "950efa276b713af8219d7501f49720fcca2dfc3afb9b283e762eab084fd77f9a"
                ),
                "costReceiptSha": (
                    "cfe23362c3aa5bf2e8f7465e52499342df4ddba65746e8c73a3db26a3840deb4"
                ),
                "rescoreRef": (
                    "eval/interview-metrics/runs/"
                    "enterprise-rag-answer-evidence-luna-max-model-only-v19-"
                    "r4-attention-r6-exact-offline-rescore-20260905.v1.json"
                ),
                "rescoreFileSha": (
                    "7f358101d6231d631f6328e9dff48ca8c147c88255426b0a26e3004301c413f3"
                ),
                "rescoreReceiptSha": (
                    "4b093ea26ec9e5c6a9ea99aabc5fe907d34e7f242d3a1d25f0a527901f6241d7"
                ),
                "sourceReportFileSha": (
                    "e46cf24687170bb768e8ae9cfe434a199f8b1c2be550b328f42b02b151192dd4"
                ),
                "ledgerLabel": "model-only",
            },
            "lunaPromptV4": {
                "runId": (
                    "enterprise-rag-luna-max-coverage-balanced-v4-20260904-r4"
                ),
                "model": "openai-codex/gpt-5.6-luna",
                "ledgerSide": _mapping(rag_final.get("candidate")),
                "facts": 9,
                "decision": "keep",
                "cost": Decimal("0.1029376"),
                "totalTokens": 763923,
                "costRef": (
                    "eval/interview-metrics/runs/"
                    "agent-lab-cost-enterprise-rag-luna-max-coverage-balanced-"
                    "v4-20260904.r4.v1.json"
                ),
                "costFileSha": (
                    "f1665186295a1958f335162997f986f027d56a9542708e49bd44e396438b472e"
                ),
                "costReceiptSha": (
                    "4082dfdfeefbf8dc5201d0fd2c290bc44d28009fbb1fcec8a8069cc751986ee5"
                ),
                "rescoreRef": (
                    "eval/interview-metrics/runs/"
                    "enterprise-rag-answer-evidence-luna-max-coverage-"
                    "balanced-v4-r4-attention-r6-exact-offline-rescore-"
                    "20260905.v1.json"
                ),
                "rescoreFileSha": (
                    "f1f9c643d0fc17a5c8738b6e68faad65c107b919c2b4a4f15f496e19481ce0a1"
                ),
                "rescoreReceiptSha": (
                    "06b154fe144bf5572a93d5892aac5454767d74d9e5e9925826c31afa88c59247"
                ),
                "sourceReportFileSha": (
                    "f7a4443c41b6738f9fdb8b5831d65d91a7ac7de71c54c3fd4c76e8b0d8edc252"
                ),
                "ledgerLabel": "final",
            },
        }
        pricing_source_shas: set[str] = set()
        for stage_name, raw_spec in stage_specs.items():
            spec = _mapping(raw_spec)
            ledger_side = _mapping(spec.get("ledgerSide"))
            ledger_metrics = _mapping(ledger_side.get("metrics"))
            expected_cost = number(spec.get("cost"))
            ledger_label = str(spec.get("ledgerLabel") or stage_name)
            if number(ledger_metrics.get("apiCostUsd")) != expected_cost:
                errors.append(
                    f"{prefix}: {ledger_label} apiCostUsd must match its "
                    "Runtime cost receipt"
                )
            if ledger_metrics.get("totalTokens") != spec.get("totalTokens"):
                errors.append(
                    f"{prefix}: {ledger_label} totalTokens must match its "
                    "Runtime cost receipt"
                )
            if (
                ledger_side.get("runId") != spec.get("runId")
                or spec.get("costRef") not in _sequence(ledger_side.get("evidenceRefs"))
                or spec.get("rescoreRef")
                not in _sequence(ledger_side.get("evidenceRefs"))
                or ledger_metrics.get("providerBillAvailable") != 0
                or ledger_metrics.get("costReceiptAvailable") != 1
            ):
                errors.append(
                    f"{prefix}: {ledger_label} ledger side must bind its exact "
                    "run, rescore and no-bill cost evidence"
                )

            ledger_cost_evidence = _mapping(cost_evidence.get(stage_name))
            cost_path = repo_root / str(spec.get("costRef"))
            cost = load_json(cost_path, prefix=prefix)
            cost_body = dict(cost)
            cost_receipt_sha = cost_body.pop("receiptSha256", None)
            usage = _mapping(cost.get("usage"))
            runtime = _mapping(cost.get("runtimeCostReceipt"))
            pricing = _mapping(cost.get("pricingIdentity"))
            estimate = _mapping(cost.get("estimate"))
            measured_usage = receipt_usage(usage)
            expected_estimate = (
                estimate_from_usage(measured_usage, _mapping(pricing.get("rates")))
                if measured_usage is not None
                else None
            )
            runtime_body = dict(runtime)
            runtime_source_sha = runtime_body.pop("sourceSha256", None)
            runtime_reported = _mapping(runtime.get("reportedCostUsd"))
            pricing_source_shas.add(str(pricing.get("sourceSha256") or ""))
            if not (
                cost_path.is_file()
                and file_sha256(cost_path) == spec.get("costFileSha")
                and ledger_cost_evidence.get("ref") == spec.get("costRef")
                and ledger_cost_evidence.get("fileSha256")
                == spec.get("costFileSha")
                and ledger_cost_evidence.get("receiptSha256")
                == spec.get("costReceiptSha")
                and number(ledger_cost_evidence.get("totalCostUsd"))
                == expected_cost
                and cost.get("schemaVersion")
                == "rag-ime.agent-lab-cost-receipt.v1"
                and cost.get("authority") == "runtime_cost_reconciled"
                and _mapping(cost.get("billing")).get("status")
                == "not_provided"
                and cost_receipt_sha == spec.get("costReceiptSha")
                and canonical_sha256(cost_body) == spec.get("costReceiptSha")
                and usage.get("available") is True
                and measured_usage is not None
                and sum(measured_usage.values()) == spec.get("totalTokens")
                and dict(estimate) == expected_estimate
                and number(estimate.get("totalCostUsd")) == expected_cost
                and pricing.get("model")
                == str(spec.get("model")).split("/", 1)[-1]
                and pricing.get("sourceUrl")
                == "https://platform.openai.com/docs/pricing"
                and pricing.get("sourceSha256")
                == "16af3bb757bca04299fbe1272ee250cfb30faa1e0fc7d852bb83e85fdce0be39"
                and pricing.get("pricingId")
                == content_addressed_pricing_id(pricing)
                and receipt_usage(runtime.get("databaseUsage")) == measured_usage
                and runtime_source_sha == canonical_sha256(runtime_body)
                and usage.get("sourceSha256") == runtime_source_sha
                and usage.get("sourceRef")
                == f"runtime-cost:{spec.get('runId')}"
                and number(runtime_reported.get("total")) == expected_cost
                and runtime_reported.get("input")
                == estimate.get("uncachedInputCostUsd")
                and runtime_reported.get("cacheRead")
                == estimate.get("cachedInputCostUsd")
                and runtime_reported.get("output")
                == estimate.get("outputCostUsd")
            ):
                errors.append(
                    f"{prefix}: {ledger_label} Runtime receipt hash, usage, "
                    "pricing and no-bill authority must remain exact"
                )

            ledger_rescore_evidence = _mapping(rescore_evidence.get(stage_name))
            rescore_path = repo_root / str(spec.get("rescoreRef"))
            rescore = load_json(rescore_path, prefix=prefix)
            rescore_body = dict(rescore)
            rescore_receipt_sha = rescore_body.pop("receiptSha256", None)
            agentic = _mapping(rescore.get("agenticResult"))
            rescore_decision = _mapping(rescore.get("rescoreDecision"))
            frozen_candidate = _mapping(
                _mapping(rescore.get("sourceEvidence")).get(
                    "frozenCandidateReport"
                )
            )
            rescore_standard = _mapping(rescore.get("standard"))
            rescore_qrels = _mapping(rescore.get("qrels"))
            cost_source = _mapping(agentic.get("costSourceReference"))
            companion_cost = _mapping(cost_source.get("companionCostReceipt"))
            expected_failed_gates = (
                [] if spec.get("decision") == "keep" else ["agentic:citationResolution"]
            )
            if not (
                rescore_path.is_file()
                and file_sha256(rescore_path) == spec.get("rescoreFileSha")
                and ledger_rescore_evidence.get("ref") == spec.get("rescoreRef")
                and ledger_rescore_evidence.get("fileSha256")
                == spec.get("rescoreFileSha")
                and ledger_rescore_evidence.get("receiptSha256")
                == spec.get("rescoreReceiptSha")
                and rescore_receipt_sha == spec.get("rescoreReceiptSha")
                and canonical_sha256(rescore_body) == spec.get("rescoreReceiptSha")
                and rescore.get("schemaVersion")
                == "paw.enterprise-rag-answer-evidence-exact-offline-rescore.v2"
                and rescore.get("calibrationLabel")
                == "post-validation-calibrated"
                and rescore.get("evaluationScope")
                == "validation-development-only"
                and rescore.get("heldOutOpened") is False
                and rescore.get("unbiasedPromotionClaimAllowed") is False
                and rescore.get("providerCalls") == 0
                and rescore.get("judgeCalls") == 0
                and rescore.get("candidateRuns") == 0
                and agentic.get("exactCitationFactsCovered") == spec.get("facts")
                and agentic.get("citationFactCount") == 9
                and agentic.get("decision") == spec.get("decision")
                and agentic.get("failedHardGates") == expected_failed_gates
                and frozen_candidate.get("model") == spec.get("model")
                and frozen_candidate.get("fileSha256")
                == spec.get("sourceReportFileSha")
                and rescore_standard.get("fileSha256")
                == expected_standard_file_sha
                and rescore_standard.get("manifestSha256")
                == expected_standard_manifest_sha
                and rescore_qrels.get("factCount") == 9
                and rescore_qrels.get("evidenceBindingCount") == 20
                and rescore_qrels.get("standardManifestSha256")
                == expected_standard_manifest_sha
                and rescore_decision.get("qrelsRevisionIsModelImprovement")
                is False
                and _mapping(rescore.get("qualityComparability")).get(
                    "modelQualityImprovementClaimAllowed"
                )
                is False
                and _mapping(rescore.get("costComparability")).get("latencyRole")
                == "diagnostic-only"
                and _mapping(rescore.get("costComparability")).get(
                    "sourceUsageCopiedFromHashBoundRun"
                )
                is True
                and companion_cost.get("path") == spec.get("costRef")
                and companion_cost.get("fileSha256") == spec.get("costFileSha")
                and companion_cost.get("receiptSha256")
                == spec.get("costReceiptSha")
                and number(companion_cost.get("estimatedTotalCostUsd"))
                == expected_cost
                and companion_cost.get("authority") == "runtime_cost_reconciled"
                and companion_cost.get("providerBillStatus") == "not_provided"
                and all(
                    value is False
                    for value in _mapping(rescore.get("publicSafety")).values()
                )
            ):
                errors.append(
                    f"{prefix}: {ledger_label} public rescore must bind r6, "
                    "its exact frozen run and diagnostic-only latency"
                )

        if pricing_source_shas != {
            "16af3bb757bca04299fbe1272ee250cfb30faa1e0fc7d852bb83e85fdce0be39"
        }:
            errors.append(
                f"{prefix}: all three stages must share one hashed pricing source"
            )

        stages = [
            _mapping(item) for item in _sequence(rag_comparison.get("stageChain"))
        ]
        cost_comparisons = _mapping(rag_comparison.get("costComparisons"))
        sol_to_final = _mapping(cost_comparisons.get("solToPromptV4"))
        model_to_final = _mapping(cost_comparisons.get("modelOnlyToPromptV4"))
        sol_cost = Decimal("2.170603")
        model_cost = Decimal("0.10594896")
        final_cost = Decimal("0.1029376")
        sol_decrease = (sol_cost - final_cost) * Decimal(100) / sol_cost
        model_decrease = (model_cost - final_cost) * Decimal(100) / model_cost
        reported_sol_decrease = number(sol_to_final.get("decreasePercent"))
        reported_model_decrease = number(
            model_to_final.get("decreasePercent")
        )
        if not (
            [number(stage.get("costUsd")) for stage in stages]
            == [sol_cost, model_cost, final_cost]
            and number(sol_to_final.get("before")) == sol_cost
            and number(sol_to_final.get("after")) == final_cost
            and reported_sol_decrease is not None
            and abs(reported_sol_decrease - sol_decrease)
            <= Decimal("0.00000000005")
            and number(model_to_final.get("before")) == model_cost
            and number(model_to_final.get("after")) == final_cost
            and reported_model_decrease is not None
            and abs(reported_model_decrease - model_decrease)
            <= Decimal("0.00000000005")
        ):
            errors.append(
                f"{prefix}: 95.2576496024% and 2.84227424224% must be "
                "recomputed from the three exact Runtime receipts"
            )

        rag_model_baseline = _mapping(rag_model.get("baseline"))
        rag_sol_candidate = _mapping(rag_sol.get("candidate"))
        if not (
            number(_mapping(rag_model_baseline.get("metrics")).get("apiCostUsd"))
            == sol_cost
            and rag_model_baseline.get("runId")
            == stage_specs["solBaseline"]["runId"]
            and number(_mapping(rag_sol_candidate.get("metrics")).get("apiCostUsd"))
            == sol_cost
            and _mapping(rag_sol_candidate.get("metrics")).get(
                "exactCitationFactsCovered"
            )
            == 7
        ):
            errors.append(
                f"{prefix}: Sol history and model-only baseline must reuse the "
                "same r6 control receipt"
            )

        boundary = _mapping(rag_comparison.get("validationBoundary"))
        claim_forbidden = str(_mapping(rag_final.get("claim")).get("forbidden") or "")
        if not (
            boundary.get("candidateAware") is True
            and boundary.get("candidateBlind") is False
            and boundary.get("heldOutOpened") is False
            and boundary.get("unbiasedPromotionClaimAllowed") is False
            and boundary.get("standardRevisionIsModelCapabilityImprovement")
            is False
            and boundary.get("latencyIsKeepGate") is False
            and boundary.get("costAuthority") == "runtime_cost_reconciled"
            and boundary.get("providerBillAvailable") is False
            and boundary.get("offlineRescoreProviderCalls") == 0
            and boundary.get("offlineRescoreJudgeCalls") == 0
            and boundary.get("offlineRescoreCandidateRuns") == 0
            and "Provider 实际账单节省" in claim_forbidden
            and "unbiased" in claim_forbidden
            and "Held-out" in claim_forbidden
            and "model capability improvement" in claim_forbidden
            and "latency improvement" in claim_forbidden
        ):
            errors.append(
                f"{prefix}: final claim must remain post-Validation "
                "candidate-aware, non-bill, non-Held-out and latency-diagnostic"
            )

    return errors


def validate_business_project_keep_paths(payload: Mapping[str, object]) -> list[str]:
    """Lock the four evidence-backed retained paths; rejected rows cannot substitute."""

    errors: list[str] = []
    raw_experiments = payload.get("experiments")
    experiments = raw_experiments if isinstance(raw_experiments, list) else []
    by_id = {
        str(item.get("id") or ""): item
        for item in experiments
        if isinstance(item, Mapping)
    }

    def experiment(experiment_id: str, project: str) -> Mapping[str, object]:
        value = by_id.get(experiment_id)
        if not isinstance(value, Mapping):
            errors.append(f"{project}: required retained-path row is missing: {experiment_id}")
            return {}
        return value

    def metric(value: Mapping[str, object], side: str, name: str) -> float | None:
        metrics = _mapping(_mapping(value.get(side)).get("metrics"))
        number = metrics.get(name)
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            return float(number)
        return None

    enterpriseops = experiment(
        "enterpriseops-csm.execution-chain.v1", "EnterpriseOps"
    )
    if enterpriseops and not (
        enterpriseops.get("status") == "kept"
        and _mapping(enterpriseops.get("comparison")).get("decision") == "keep"
        and metric(enterpriseops, "baseline", "verifierPassed") == 3
        and metric(enterpriseops, "candidate", "verifierPassed") == 26
        and metric(enterpriseops, "baseline", "businessToolCalls") == 0
        and metric(enterpriseops, "candidate", "businessToolCalls") == 47
    ):
        errors.append(
            "EnterpriseOps: execution-chain Keep must preserve 3/31 to 26/31 verifier and 0 to 47 business Tool evidence"
        )

    state_contract = experiment(
        "enterpriseops-csm.state-contract-suite-v2", "EnterpriseOps"
    )
    if state_contract and not (
        state_contract.get("status") == "rejected"
        and _mapping(state_contract.get("comparison")).get("decision") == "reject"
    ):
        errors.append(
            "EnterpriseOps: state-contract row must retain its rejected Promotion boundary"
        )

    cost_gate = experiment(
        "enterpriseops-csm.luna-model-only-r5.v1", "EnterpriseOps"
    )
    if cost_gate and not (
        cost_gate.get("status") == "rejected"
        and _mapping(cost_gate.get("comparison")).get("decision") == "reject"
        and metric(cost_gate, "baseline", "taskSuccessRate") == 1
        and metric(cost_gate, "candidate", "taskSuccessRate") == 2 / 3
        and metric(cost_gate, "baseline", "verifierPassRate") == 1
        and metric(cost_gate, "candidate", "verifierPassRate") == 30 / 31
        and (metric(cost_gate, "candidate", "apiCostUsd") or math.inf)
        < (metric(cost_gate, "baseline", "apiCostUsd") or -math.inf)
    ):
        errors.append(
            "EnterpriseOps: model-only r5 Reject must retain the matched quality regression despite a lower exact Runtime cost"
        )

    enterprise_current = experiment(
        "enterpriseops-csm.luna-prompt-adaptation-r7.v1", "EnterpriseOps"
    )
    enterprise_comparison = (
        _mapping(enterprise_current.get("comparison")) if enterprise_current else {}
    )
    enterprise_costs = _mapping(enterprise_comparison.get("costComparisons"))
    sol_to_final = _mapping(enterprise_costs.get("solToPromptAdapted"))
    model_to_prompt = _mapping(
        enterprise_costs.get("modelOnlyToPromptAdapted")
    )
    if enterprise_current and not (
        enterprise_current.get("status") == "kept"
        and enterprise_current.get("projectionState") == "current"
        and enterprise_comparison.get("decision") == "keep"
        and metric(enterprise_current, "candidate", "taskSuccessRate") == 1
        and metric(enterprise_current, "candidate", "verifierPassRate") == 1
        and metric(enterprise_current, "candidate", "failedToolCalls") == 0
        and metric(enterprise_current, "candidate", "apiCostUsd") == 0.07291692
        and sol_to_final.get("decreasePercent") == 95.738878
        and model_to_prompt.get("decreasePercent") == 22.866141
    ):
        errors.append(
            "EnterpriseOps: current Luna Prompt r7 Keep must restore 3/3 and "
            "31/31 and retain both exact Runtime cost reductions"
        )

    rag_retrieval_history = experiment(
        "enterprise-rag.retrieval-selection.v1", "RAG"
    )
    rag_retrieval_comparison = (
        _mapping(rag_retrieval_history.get("comparison"))
        if rag_retrieval_history
        else {}
    )
    if rag_retrieval_history and not (
        rag_retrieval_history.get("status") == "diagnostic"
        and rag_retrieval_history.get("projectionState") == "history"
        and rag_retrieval_history.get("effectStatus") == "improved"
        and rag_retrieval_comparison.get("decision") == "diagnostic_only"
        and all(
            (metric(rag_retrieval_history, "candidate", name) or -math.inf)
            > (metric(rag_retrieval_history, "baseline", name) or math.inf)
            for name in ("mrr", "ndcgAt10", "recallAt10")
        )
    ):
        errors.append(
            "RAG: retrieval-selection diagnostic must remain immutable history"
        )

    rag_current_id = "enterprise-rag.luna-prompt-v4-standard-r6.v1"
    rag_old_current = experiment(
        "enterprise-rag.sol-max-budget3-r3.v1", "RAG"
    )
    rag_sol = experiment("enterprise-rag.sol-max-standard-r6.v1", "RAG")
    rag_model_only = experiment(
        "enterprise-rag.luna-model-only-standard-r6.v1", "RAG"
    )
    rag_current = experiment(rag_current_id, "RAG")
    rag_comparison = (
        _mapping(rag_current.get("comparison")) if rag_current else {}
    )
    rag_stages = [
        _mapping(item) for item in _sequence(rag_comparison.get("stageChain"))
    ]
    rag_costs = _mapping(rag_comparison.get("costComparisons"))
    rag_sol_to_final = _mapping(rag_costs.get("solToPromptV4"))
    rag_model_to_prompt = _mapping(rag_costs.get("modelOnlyToPromptV4"))
    rag_boundary = _mapping(rag_comparison.get("validationBoundary"))
    if rag_current and not (
        rag_current.get("status") == "kept"
        and rag_current.get("projectionState") == "current"
        and rag_comparison.get("decision") == "keep"
        and [str(stage.get("stage") or "") for stage in rag_stages]
        == ["sol_baseline", "luna_model_only", "luna_prompt_v4"]
        and [stage.get("exactCitationFactsCovered") for stage in rag_stages]
        == [7, 8, 9]
        and [stage.get("citationFactCount") for stage in rag_stages]
        == [9, 9, 9]
        and [stage.get("decision") for stage in rag_stages]
        == ["reject", "reject", "keep"]
        and [stage.get("costUsd") for stage in rag_stages]
        == [2.170603, 0.10594896, 0.1029376]
        and metric(rag_current, "baseline", "exactCitationFactsCovered") == 7
        and metric(rag_current, "candidate", "exactCitationFactsCovered") == 9
        and metric(rag_current, "candidate", "agentSuccessRate") == 1
        and metric(rag_current, "candidate", "answerableCitationSupportRate") == 1
        and metric(rag_current, "candidate", "citationHardGatePassed") == 1
        and metric(rag_current, "candidate", "apiCostUsd") == 0.1029376
        and rag_sol_to_final.get("decreasePercent") == 95.2576496024
        and rag_model_to_prompt.get("decreasePercent") == 2.84227424224
        and rag_boundary.get("candidateAware") is True
        and rag_boundary.get("candidateBlind") is False
        and rag_boundary.get("heldOutOpened") is False
        and rag_boundary.get("unbiasedPromotionClaimAllowed") is False
        and rag_boundary.get("standardRevisionIsModelCapabilityImprovement")
        is False
        and rag_boundary.get("latencyIsKeepGate") is False
        and rag_boundary.get("costAuthority") == "runtime_cost_reconciled"
        and rag_boundary.get("providerBillAvailable") is False
    ):
        errors.append(
            "RAG: current Luna Prompt-v4 r6 Keep must retain the 7/9 to 8/9 "
            "to 9/9 three-stage path and exact Runtime cost reductions"
        )
    if rag_old_current and not (
        rag_old_current.get("projectionState") == "history"
        and rag_old_current.get("supersededBy") == rag_current_id
    ):
        errors.append(
            "RAG: old Sol budget3 r3 row must be history superseded by the current r6 path"
        )
    if rag_sol and not (
        rag_sol.get("status") == "rejected"
        and rag_sol.get("projectionState") == "history"
        and rag_sol.get("supersededBy") == rag_current_id
        and metric(rag_sol, "candidate", "exactCitationFactsCovered") == 7
        and metric(rag_sol, "candidate", "apiCostUsd") == 2.170603
    ):
        errors.append("RAG: Sol r6 must remain a 7/9 rejected history control")
    if rag_model_only and not (
        rag_model_only.get("status") == "rejected"
        and rag_model_only.get("projectionState") == "history"
        and rag_model_only.get("supersededBy") == rag_current_id
        and metric(rag_model_only, "candidate", "exactCitationFactsCovered") == 8
        and metric(rag_model_only, "candidate", "apiCostUsd") == 0.10594896
    ):
        errors.append(
            "RAG: Luna model-only r6 must remain an 8/9 rejected history stage"
        )

    cloudops_validation_history = experiment(
        "cloudops.validation-baseline.v1", "CloudOps"
    )
    cloudops_validation_reason = str(
        _mapping(cloudops_validation_history.get("comparison")).get(
            "decisionReason"
        )
        or ""
    ) if cloudops_validation_history else ""
    if cloudops_validation_history and not (
        cloudops_validation_history.get("status") == "kept"
        and cloudops_validation_history.get("projectionState") == "history"
        and cloudops_validation_history.get("supersededBy")
        == "cloudops.alert-first-sol-max.v1"
        and cloudops_validation_history.get("effectStatus") == "improved"
        and _mapping(cloudops_validation_history.get("comparison")).get(
            "decision"
        )
        == "keep"
        and metric(cloudops_validation_history, "baseline", "formalScoreProduced")
        == 0
        and metric(cloudops_validation_history, "candidate", "formalScoreProduced")
        == 1
        and metric(cloudops_validation_history, "candidate", "answerCoverage")
        == 1
        and metric(cloudops_validation_history, "candidate", "ca") == 1
        and metric(cloudops_validation_history, "candidate", "toolCalls") == 98
        and metric(cloudops_validation_history, "candidate", "failedToolCalls")
        == 0
        and "模型质量提升" in cloudops_validation_reason
    ):
        errors.append(
            "CloudOps: historical scoring recovery must remain 12/12 and "
            "98/98 without becoming a model-quality uplift"
        )

    cloudops_history = experiment(
        "cloudops.alert-first-sol-max.v1", "CloudOps"
    )
    cloudops_model_only = experiment(
        "cloudops.alert-first-luna-model-only-r1.v1", "CloudOps"
    )
    cloudops = experiment(
        "cloudops.luna-owner-mechanism-prompt-r5.v1", "CloudOps"
    )
    cloudops_comparison = (
        _mapping(cloudops.get("comparison")) if cloudops else {}
    )
    cloudops_costs = _mapping(cloudops_comparison.get("costComparisons"))
    cloudops_sol_to_final = _mapping(
        cloudops_costs.get("solToPromptAdapted")
    )
    cloudops_model_to_prompt = _mapping(
        cloudops_costs.get("modelOnlyToPromptAdapted")
    )
    cloudops_stages = [
        str(_mapping(item).get("stage") or "")
        for item in _sequence(cloudops_comparison.get("stageChain"))
    ]
    cloudops_current_id = "cloudops.luna-owner-mechanism-prompt-r5.v1"
    if cloudops and not (
        cloudops.get("status") == "kept"
        and cloudops.get("projectionState") == "current"
        and cloudops_comparison.get("decision") == "keep"
        and cloudops_stages
        == ["sol_baseline", "luna_model_only", "luna_prompt_adapted"]
        and metric(cloudops, "baseline", "ca") == 1
        and metric(cloudops, "candidate", "ca") == 1
        and metric(cloudops, "candidate", "fa") == 11 / 12
        and metric(cloudops, "candidate", "jra") == 11 / 12
        and metric(cloudops, "candidate", "top3Jra") == 1
        and metric(cloudops, "candidate", "toolCalls") == 130
        and metric(cloudops, "candidate", "failedToolCalls") == 0
        and metric(cloudops, "candidate", "apiCostUsd") == 0.27613024
        and cloudops_sol_to_final.get("decreasePercent") == 93.9553369996
        and cloudops_model_to_prompt.get("decreasePercent") == 17.8015302661
    ):
        errors.append(
            "CloudOps: current Luna Prompt r5 Keep must retain the three-stage "
            "quality, Tool and exact Runtime cost result"
        )
    if cloudops_history and not (
        cloudops_history.get("projectionState") == "history"
        and cloudops_history.get("supersededBy") == cloudops_current_id
    ):
        errors.append(
            "CloudOps: Sol alert-first r7 must remain history superseded by "
            "the current Luna Prompt r5 path"
        )
    if cloudops_model_only and not (
        cloudops_model_only.get("status") == "rejected"
        and cloudops_model_only.get("projectionState") == "history"
        and cloudops_model_only.get("supersededBy") == cloudops_current_id
        and metric(cloudops_model_only, "candidate", "ca") == 11 / 12
        and metric(cloudops_model_only, "candidate", "jra") == 9 / 12
        and metric(cloudops_model_only, "candidate", "failedToolCalls") == 6
    ):
        errors.append(
            "CloudOps: Luna model-only r1 must remain a rejected history stage"
        )

    memory = experiment("memory.maintenance-luna-shadow-v5.v1", "Memory")
    if memory and not (
        memory.get("status") == "kept"
        and memory.get("effectStatus") == "improved"
        and _mapping(memory.get("comparison")).get("decision") == "keep"
        and metric(memory, "baseline", "vectorCoverage") == 0
        and metric(memory, "candidate", "vectorCoverage") == 1
        and metric(memory, "baseline", "receiptJsonValid") == 0
        and metric(memory, "candidate", "receiptJsonValid") == 1
        and metric(memory, "candidate", "rollbackPassed") == 1
        and metric(memory, "candidate", "replayPassed") == 1
    ):
        errors.append(
            "Memory: v5 Keep must close dense, JSON receipt, rollback and replay gates in private shadow"
        )

    memory_current = experiment(
        "memory.maintenance-luna-model-only-r1.v1", "Memory"
    )
    memory_comparison = (
        _mapping(memory_current.get("comparison")) if memory_current else {}
    )
    if memory_current and not (
        memory_current.get("status") == "kept"
        and memory_current.get("projectionState") == "current"
        and memory_comparison.get("decision") == "keep"
        and memory_comparison.get("promptAdaptationNeeded") is False
        and memory_comparison.get("latencyIsKeepGate") is False
        and memory_comparison.get("costDecreasePercent") == 96.0053508723
        and metric(memory_current, "candidate", "curationPassed") == 5
        and metric(memory_current, "candidate", "durableRecallPassed") == 4
        and metric(memory_current, "candidate", "abstentionPassed") == 1
        and metric(memory_current, "candidate", "vectorCoverage") == 1
        and metric(memory_current, "candidate", "rollbackPassed") == 1
        and metric(memory_current, "candidate", "replayPassed") == 1
    ):
        errors.append(
            "Memory: current Luna model-only r1 Keep must preserve the complete "
            "lifecycle and its no-Prompt-adaptation boundary"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        default="eval/interview-metrics/agent-experiments.v1.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    ledger_path = Path(args.ledger).resolve()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("Agent experiment ledger must contain a JSON object")
    repo_root = Path(__file__).resolve().parents[1]
    errors = [
        *validate_agent_experiments(payload, repo_root=repo_root),
        *validate_business_project_keep_paths(payload),
        *validate_controlled_model_cost_receipts(payload, repo_root=repo_root),
        *validate_retained_api_pricing_estimates(payload, repo_root=repo_root),
    ]
    report = {
        "schemaVersion": "paw.interview-agent-experiment-check.v1",
        "ok": not errors,
        "experimentCount": len(payload.get("experiments") or []),
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
