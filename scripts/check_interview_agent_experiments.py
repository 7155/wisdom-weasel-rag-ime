#!/usr/bin/env python3
"""Validate interview-facing Agent experiment cards and their proof boundaries."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping, Sequence
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
            if item.get("id") == "agent-lab.model-cost.luna-max-validation.v1"
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
        "runtimeProvenanceSha256",
        "promptContractSha256",
        "timeoutSeconds",
        "effectiveTimeoutSeconds",
        "transport",
        "mcpEndpoint",
    )
    for field in frozen_contract_fields:
        if baseline_contract.get(field) != candidate_contract.get(field):
            errors.append(f"{prefix}: frozen contract field {field} must match")

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
        "agent-lab.model-cost.luna-max-validation.v1", "EnterpriseOps"
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
            "EnterpriseOps: model-cost Reject must retain the matched quality regression despite a lower price estimate"
        )

    rag = experiment("enterprise-rag.retrieval-selection.v1", "RAG")
    rag_comparison = _mapping(rag.get("comparison")) if rag else {}
    if rag and not (
        rag.get("status") == "diagnostic"
        and rag.get("effectStatus") == "improved"
        and rag_comparison.get("decision") == "diagnostic_only"
    ):
        errors.append(
            "RAG: enterprise-rag.retrieval-selection.v1 must remain the non-rejected Validation retrieval winner"
        )
    if rag and not all(
        (metric(rag, "candidate", name) or -math.inf)
        > (metric(rag, "baseline", name) or math.inf)
        for name in ("mrr", "ndcgAt10", "recallAt10")
    ):
        errors.append(
            "RAG: retrieval winner must improve MRR, nDCG@10 and Recall@10 over the frozen lexical floor"
        )

    cloudops = experiment("cloudops.validation-baseline.v1", "CloudOps")
    cloudops_reason = str(
        _mapping(cloudops.get("comparison")).get("decisionReason") or ""
    ) if cloudops else ""
    if cloudops and not (
        cloudops.get("status") == "kept"
        and cloudops.get("effectStatus") == "improved"
        and _mapping(cloudops.get("comparison")).get("decision") == "keep"
        and metric(cloudops, "baseline", "formalScoreProduced") == 0
        and metric(cloudops, "candidate", "formalScoreProduced") == 1
        and metric(cloudops, "candidate", "answerCoverage") == 1
        and metric(cloudops, "candidate", "ca") == 1
        and metric(cloudops, "candidate", "toolCalls") == 98
        and metric(cloudops, "candidate", "failedToolCalls") == 0
        and "模型质量提升" in cloudops_reason
    ):
        errors.append(
            "CloudOps: Keep must mean Tool/Eval scoring recovery to 12/12 and 98/98, not a model-quality uplift"
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
