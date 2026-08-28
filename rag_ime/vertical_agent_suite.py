"""Deterministic suite runner for the public vertical-Agent self-tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .contracts.json_schema import validate_contract
from .eval_run_store import EvalRunStore
from .evidence_eval import evaluate_evidence_ground_truth
from .vertical_agent_harness import (
    VerticalHarnessError,
    VerticalSuiteResolutionError,
    load_builtin_manifests,
    resolve_builtin_vertical_suite,
    verify_vertical_trace,
)
from .vertical_agent_sandbox import (
    DEFAULT_SELF_TEST_TIME_MS,
    run_vertical_agent_self_test,
)
from .trace_store import TraceStore


VERTICAL_SUITE_SCHEMA_VERSION = "rag-ime.vertical-agent-self-test-suite.v1"


class BuiltinVerticalSuiteError(VerticalHarnessError):
    """A safe, structured failure at the built-in suite boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = str(code)
        super().__init__(message)


def evaluate_vertical_agent_case_trace(
    manifest: Mapping[str, object],
    trace: Mapping[str, object],
    *,
    eval_store: EvalRunStore,
    trace_store: TraceStore | None = None,
    fixture_id: str | None = None,
    now_ms: int | None = None,
) -> dict[str, object]:
    """Evaluate one externally produced vertical-Agent Trace.

    The caller owns execution of the Agent and supplies its completed,
    canonical Trace envelope.  This boundary verifies the declared Trace,
    optionally retains that exact envelope, and creates the deterministic
    ground-truth EvalRun from the manifest's evidence labels.  It deliberately
    does not invoke the built-in fixture runner or make a sandbox/runtime
    claim.
    """

    verification = verify_vertical_trace(
        manifest,
        trace,
        fixture_id=fixture_id,
    )
    trace_id = str(verification["traceId"])
    if trace_store is not None:
        persisted_trace = trace_store.persist(trace)
        if persisted_trace != dict(trace):
            raise VerticalHarnessError(
                "durable TraceStore returned a different canonical envelope"
            )

    truth = verification["truth"]
    assert isinstance(truth, Mapping)
    required_evidence_ids = truth["requiredEvidenceIds"]
    app_id = str(manifest["appId"])
    suite_revision = str(manifest["suiteRevision"])
    eval_payload = evaluate_evidence_ground_truth(
        (trace,),
        {trace_id: {"requiredEvidenceIds": required_evidence_ids}},
        dataset_id=f"vertical:{app_id}:public",
        label_revision=suite_revision,
        suite_binding={
            "suiteId": app_id,
            "suiteRevision": suite_revision,
        },
        store=eval_store,
        now_ms=now_ms,
    )
    return {
        "traceId": trace_id,
        "evalRunId": str(eval_payload["evalRunId"]),
        "verification": verification,
    }


def run_builtin_vertical_agent_eval(
    suite_id: object,
    suite_revision: object,
    workspace_root: str | Path,
    *,
    eval_store: EvalRunStore,
    trace_store: TraceStore | None = None,
    now_ms: int = DEFAULT_SELF_TEST_TIME_MS,
    schedule_run_id: str | None = None,
    schedule_due_at_ms: int | None = None,
) -> dict[str, str]:
    """Run one allowlisted fixture suite and persist its real EvalRun.

    This is deliberately the narrow bridge used by the scheduled Runtime
    executor.  It accepts only checked-in registered examples, requires the
    manifest's exact revision, runs below the caller-owned temporary workspace,
    and returns only the EvalRun identity after persisting it in ``eval_store``.
    The underlying self-test remains fixture-only: no Provider or production
    Memory/Knowledge store is opened.
    """

    if not isinstance(suite_id, str) or not suite_id.strip():
        raise BuiltinVerticalSuiteError(
            "vertical suite id is required",
            code="suite_id_required",
        )
    try:
        manifest = resolve_builtin_vertical_suite(suite_id, suite_revision)
    except VerticalSuiteResolutionError as exc:
        raise BuiltinVerticalSuiteError(str(exc), code=exc.code) from exc

    try:
        result = run_vertical_agent_self_test(
            manifest,
            workspace_root,
            now_ms=now_ms,
            trace_store=trace_store,
            schedule_run_id=schedule_run_id,
            schedule_due_at_ms=schedule_due_at_ms,
        )
    except VerticalHarnessError as exc:
        raise BuiltinVerticalSuiteError(
            "vertical fixture self-test failed",
            code="vertical_fixture_failed",
        ) from exc
    eval_payload = result.get("evalRun")
    if not isinstance(eval_payload, Mapping):
        raise BuiltinVerticalSuiteError(
            "vertical fixture did not return an EvalRun",
            code="eval_run_missing",
        )
    try:
        persisted = eval_store.persist(eval_payload)
    except Exception as exc:
        raise BuiltinVerticalSuiteError(
            "vertical fixture EvalRun could not be persisted",
            code="eval_run_persist_failed",
        ) from exc
    eval_run_id = persisted.get("evalRunId")
    if not isinstance(eval_run_id, str) or not eval_run_id.strip():
        raise BuiltinVerticalSuiteError(
            "persisted EvalRun has no identity",
            code="eval_run_missing",
        )
    return {"evalRunId": eval_run_id}


def run_vertical_agent_self_test_suite(
    output_root: str | Path,
    *,
    app_ids: Sequence[str] | None = None,
    now_ms: int = DEFAULT_SELF_TEST_TIME_MS,
    trace_store: TraceStore | None = None,
) -> dict[str, object]:
    """Run selected built-in examples without Provider or production writes.

    The suite root must be new or empty.  Each example gets its own isolated
    child workspace, while the returned/written report contains only bounded
    identifiers, metrics, and truthful sandbox flags—not fixture queries or
    retrieved document content.
    """

    manifests = load_builtin_manifests()
    selected_ids = _selected_app_ids(manifests, app_ids)
    suite_root = _prepare_suite_root(output_root)
    results: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    for app_id in selected_ids:
        try:
            result = run_vertical_agent_self_test(
                manifests[app_id],
                suite_root / app_id,
                now_ms=now_ms,
                trace_store=trace_store,
            )
            trace = result["trace"]
            eval_run = result["evalRun"]
            sandbox_run = result["sandboxRun"]
            if not isinstance(trace, dict) or not isinstance(eval_run, dict) or not isinstance(sandbox_run, dict):
                raise VerticalHarnessError("vertical self-test returned an invalid receipt chain")
            results.append({
                "appId": app_id,
                "fixtureId": str(result["fixtureId"]),
                "traceId": str(trace["traceId"]),
                "evalRunId": str(eval_run["evalRunId"]),
                "sandboxRunId": str(sandbox_run["sandboxRunId"]),
                "metrics": dict(eval_run["metrics"]),
                "providerCalls": int(result["providerCalls"]),
                "productionWriteBlocked": result["productionWriteBlocked"] is True,
                "status": "passed",
            })
        except Exception as exc:  # keep independent examples independently accountable
            error_fingerprint = hashlib.sha256(
                str(exc).encode("utf-8")
            ).hexdigest()
            failures.append({
                "appId": app_id,
                "status": "failed",
                "errorCode": type(exc).__name__,
                "errorFingerprint": f"sha256:{error_fingerprint}",
            })

    report: dict[str, object] = {
        "schemaVersion": VERTICAL_SUITE_SCHEMA_VERSION,
        "status": "completed" if not failures else "failed",
        "totalCount": len(selected_ids),
        "passedCount": len(results),
        "failedCount": len(failures),
        "results": results,
        "failures": failures,
    }
    if len(results) + len(failures) != len(selected_ids):
        raise RuntimeError("vertical self-test suite counts do not reconcile")
    validate_contract(report, "vertical-agent-self-test-suite.v1.json")
    (suite_root / "suite-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _selected_app_ids(
    manifests: dict[str, dict[str, object]],
    requested: Sequence[str] | None,
) -> list[str]:
    if requested is None:
        return sorted(manifests)
    normalized = [str(value).strip() for value in requested]
    if not normalized or any(not value for value in normalized):
        raise VerticalHarnessError("at least one non-empty vertical app id is required")
    if len(normalized) != len(set(normalized)):
        raise VerticalHarnessError("vertical app ids must be unique")
    unknown = sorted(set(normalized) - set(manifests))
    if unknown:
        raise VerticalHarnessError(f"unknown vertical app ids: {unknown}")
    return normalized


def _prepare_suite_root(output_root: str | Path) -> Path:
    requested = Path(output_root).expanduser()
    if requested.is_symlink():
        raise VerticalHarnessError("vertical suite output root may not be a symlink")
    if requested.exists():
        if not requested.is_dir():
            raise VerticalHarnessError("vertical suite output root must be a directory")
        try:
            next(requested.iterdir())
        except StopIteration:
            pass
        else:
            raise VerticalHarnessError("vertical suite output root must be empty")
    else:
        if not requested.parent.exists() or requested.parent.is_symlink():
            raise VerticalHarnessError("vertical suite output parent must already exist and be real")
        requested.mkdir(mode=0o700)
    requested.chmod(0o700)
    return requested.resolve(strict=True)
