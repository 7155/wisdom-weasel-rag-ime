"""Deterministic evidence-set evaluation for completed Trace envelopes.

This module compares the evidence references marked ``included`` by a
producer (the prediction) with frozen or human ``requiredEvidenceIds``
labels (the truth).  It intentionally has no model/AI-Judge path: metrics
created here are always built with ``ground_truth`` authority.

There is no closed negative evidence universe in a ``requiredEvidenceIds``
label.  Consequently conventional micro accuracy (which needs true
negatives) is not reported.  Precision, recall, and F1 are micro-averaged
over evidence IDs and remain well-defined with an explicit zero-denominator
policy of 0.0.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from .eval_run_store import EvalRunStore
from .trace_runtime import (
    EvalRun,
    TraceContractError,
    TraceEnvelope,
    build_eval_run,
    validate_trace_envelope,
)


_LABEL_FIELDS = frozenset({"requiredEvidenceIds"})


def evaluate_evidence_ground_truth(
    traces: Sequence[TraceEnvelope | Mapping[str, object]],
    labels: Mapping[str, Sequence[str] | Mapping[str, object]],
    *,
    dataset_id: str,
    label_revision: str,
    truth_kind: str = "frozen",
    evaluator: Mapping[str, str] | None = None,
    suite_binding: Mapping[str, str] | None = None,
    store: EvalRunStore | None = None,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Build (and optionally persist) one reproducible evidence EvalRun.

    ``traces`` must be schema-valid and completed.  Each label is either a
    sequence of required evidence IDs or an object containing exactly
    ``requiredEvidenceIds``.  A label's trace IDs must match the input set
    exactly; unknown evidence IDs count as false negatives because a trace
    can have failed to produce a gold-required reference.

    The returned mapping is the validated EvalRun payload.  Persistence uses
    the stable content-derived run ID, so repeating the same evaluation is
    idempotent under :class:`EvalRunStore`.
    """

    if not isinstance(traces, Sequence) or isinstance(traces, (str, bytes)) or not traces:
        raise TraceContractError("evidence evaluation requires a non-empty trace set")
    if not isinstance(labels, Mapping) or not labels:
        raise TraceContractError("evidence evaluation requires a non-empty label set")
    if evaluator is not None and not isinstance(evaluator, Mapping):
        raise TraceContractError("evaluator must be a mapping")
    if evaluator is not None:
        expected = {"provider": "deterministic", "model": "labels", "thinking": "none"}
        for key, value in evaluator.items():
            if key in expected and str(value) != expected[key]:
                raise TraceContractError("AI Judge evaluator cannot be mixed into ground-truth evaluation")
    normalized: dict[str, dict[str, object]] = {}
    for item in traces:
        payload = item.to_dict() if isinstance(item, TraceEnvelope) else _mapping(item, "trace")
        validate_trace_envelope(payload)
        trace_id = _required_text(payload.get("traceId"), "traceId")
        if trace_id in normalized:
            raise TraceContractError(f"duplicate trace ID: {trace_id}")
        if payload.get("status") != "completed":
            raise TraceContractError("evidence evaluation accepts completed traces only")
        normalized[trace_id] = payload

    trace_ids = set(normalized)
    normalized_labels = {str(key): value for key, value in labels.items()}
    if len(normalized_labels) != len(labels):
        raise TraceContractError("labels contain duplicate trace IDs after normalization")
    label_ids = set(normalized_labels)
    if trace_ids != label_ids:
        missing = sorted(trace_ids - label_ids)
        extra = sorted(label_ids - trace_ids)
        raise TraceContractError(f"trace/label IDs do not match (missing={missing}, extra={extra})")

    truth: dict[str, frozenset[str]] = {}
    for trace_id in sorted(trace_ids):
        truth[trace_id] = _required_ids(normalized_labels[trace_id])

    predicted: dict[str, frozenset[str]] = {}
    for trace_id in sorted(trace_ids):
        evidence = normalized[trace_id].get("evidence")
        if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
            raise TraceContractError(f"trace {trace_id} evidence must be a sequence")
        included: set[str] = set()
        for item in evidence:
            if not isinstance(item, Mapping):
                raise TraceContractError(f"trace {trace_id} contains an invalid evidence reference")
            evidence_id = _required_text(item.get("evidenceId"), "evidenceId")
            if item.get("disposition") == "included":
                included.add(evidence_id)
        predicted[trace_id] = frozenset(included)

    true_positive = sum(len(predicted[key] & truth[key]) for key in sorted(trace_ids))
    false_positive = sum(len(predicted[key] - truth[key]) for key in sorted(trace_ids))
    false_negative = sum(len(truth[key] - predicted[key]) for key in sorted(trace_ids))
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _ratio(2 * precision * recall, precision + recall)

    timestamp = max(int(normalized[key]["updatedAtMs"]) for key in trace_ids) if now_ms is None else int(now_ms)
    # The persisted payload contains this timestamp.  Include it in the
    # identity so explicit runs at different times cannot share an ID while
    # differing in stored content (which EvalRunStore correctly rejects).
    canonical_input = {
        "datasetId": str(dataset_id),
        "labelRevision": str(label_revision),
        "truthKind": str(truth_kind),
        "createdAtMs": timestamp,
        # Identity follows only inputs that can change these metrics.  Random
        # sandbox bindings, timing, and span metadata are validated as part of
        # the source Trace but must not make an otherwise identical
        # deterministic evaluation look like a new EvalRun.
        "predictions": {
            key: sorted(predicted[key])
            for key in sorted(trace_ids)
        },
        "labels": {key: sorted(truth[key]) for key in sorted(trace_ids)},
    }
    eval_run_id = "eval:evidence-ground-truth:" + hashlib.sha256(
        json.dumps(canonical_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    run: EvalRun = build_eval_run(
        eval_run_id=eval_run_id,
        trace_ids=tuple(sorted(trace_ids)),
        mode="ground_truth",
        truth_kind=truth_kind,
        dataset_id=dataset_id,
        label_revision=label_revision,
        evaluator=evaluator,
        suite_binding=suite_binding,
        metrics={"precision": precision, "recall": recall, "f1": f1},
        now_ms=timestamp,
    )
    payload = run.to_dict()
    if store is not None:
        return store.persist(run)
    return payload


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TraceContractError(f"{name} must be a mapping")
    return dict(value)


def _required_text(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TraceContractError(f"{name} is required")
    return text


def _required_ids(value: object) -> frozenset[str]:
    if isinstance(value, Mapping):
        if set(value) != _LABEL_FIELDS:
            raise TraceContractError("labels must contain requiredEvidenceIds only; AI Judge fields are not accepted")
        value = value.get("requiredEvidenceIds")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TraceContractError("requiredEvidenceIds must be a sequence")
    result: list[str] = []
    for item in value:
        evidence_id = _required_text(item, "requiredEvidenceId")
        if evidence_id in result:
            raise TraceContractError(f"duplicate required evidence ID: {evidence_id}")
        result.append(evidence_id)
    return frozenset(result)


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0
