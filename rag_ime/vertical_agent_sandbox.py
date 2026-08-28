"""Offline self-test runner for the public vertical-Agent examples.

This is a builder-facing harness, not a production Agent runtime.  It runs a
real local Knowledge retrieval inside :class:`RagBenchmarkSandbox`, then
assembles the common Trace/Eval/Sandbox contracts without calling a Provider
or touching the production Knowledge or Memory stores.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

from .eval_run_store import EvalRunStore
from .evidence_eval import evaluate_evidence_ground_truth
from .rag_benchmark_sandbox import RagBenchmarkSandbox
from .trace_runtime import (
    ArtifactRef,
    EvidenceRef,
    build_sandbox_run,
    build_trace_envelope,
    fingerprint_text,
    make_span,
)
from .trace_store import TraceStore
from .vertical_agent_harness import VerticalHarnessError, validate_vertical_manifest, verify_vertical_trace


DEFAULT_SELF_TEST_TIME_MS = 1_700_000_000_000
_SCHEDULE_EXECUTION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


def run_vertical_agent_self_test(
    manifest: Mapping[str, object],
    workspace_root: str | Path,
    *,
    now_ms: int = DEFAULT_SELF_TEST_TIME_MS,
    trace_store: TraceStore | None = None,
    schedule_run_id: str | None = None,
    schedule_due_at_ms: int | None = None,
) -> dict[str, object]:
    """Execute one deterministic public vertical-Agent sandbox run.

    ``workspace_root`` is caller-owned and should normally be a temporary
    directory.  Every generated file and database is placed below it.  The
    memory record is intentionally a fixture receipt because this runner does
    not open the production Memory store.
    """

    validate_vertical_manifest(manifest)
    app_id = _required_text(manifest, "appId")
    execution_id = _schedule_execution_id(schedule_run_id)
    execution_now_ms = _schedule_execution_time(schedule_due_at_ms, fallback=now_ms)
    self_test = _mapping(manifest, "selfTest")
    fixture_id = _first_fixture_id(manifest)
    fixture_path = _fixture_path(self_test.get("fixturePath"))
    document_text = fixture_path.read_text(encoding="utf-8")
    query = _required_text(self_test, "query")
    base_alias = _required_text(self_test, "baseAlias")
    base_name = _required_text(self_test, "baseName")
    memory = _mapping(self_test, "memory")
    memory_id = _required_text(memory, "memoryId")
    memory_source_ref = _required_text(memory, "sourceRef")
    memory_summary_fingerprint = _required_text(memory, "summaryFingerprint")
    document_id = _required_text_value(self_test.get("documentId") or fixture_id, "selfTest.documentId")

    workspace = _prepare_workspace(workspace_root)
    sandbox = RagBenchmarkSandbox(workspace / "rag-runs")
    owner_session_id = f"vertical-self-test:{app_id}"
    try:
        run = sandbox.create_run(owner_session_id, label=f"{app_id} offline self-test")
        run_id = str(run["runId"])
        sandbox.create_base(owner_session_id, run_id, alias=base_alias, name=base_name)
        imported = sandbox.import_documents(
            owner_session_id,
            run_id,
            base_alias=base_alias,
            documents=[{
                "externalId": document_id,
                "name": fixture_path.name,
                "text": document_text,
            }],
        )
        search = sandbox.search(
            owner_session_id,
            run_id,
            base_alias=base_alias,
            query=query,
            top_k=1,
            mode="lexical",
        )
        hits = search.get("hits")
        if not isinstance(hits, list) or not hits:
            raise VerticalHarnessError(f"offline self-test retrieved no result for {app_id}")
        hit = hits[0]
        if not isinstance(hit, Mapping):
            raise VerticalHarnessError("offline self-test returned an invalid retrieval hit")
        external_document_id = _required_text(hit, "externalDocumentId")
        declared_truth_ids = _declared_truth_ids(manifest, fixture_id)
        expected_knowledge_id = next(item for item in declared_truth_ids if item.startswith("knowledge:"))
        if expected_knowledge_id != f"knowledge:{external_document_id}":
            raise VerticalHarnessError(
                f"fixture truth {expected_knowledge_id!r} did not match retrieved document {external_document_id!r}"
            )
        citation_ref = _required_text(hit, "citationRef")
        retrieval_scores = _retrieval_scores(hit)

        memory_receipt = _memory_fixture_receipt(
            app_id=app_id,
            fixture_id=fixture_id,
            memory_id=memory_id,
            source_ref=memory_source_ref,
            summary_fingerprint=memory_summary_fingerprint,
        )
        memory_evidence_id = memory_id if memory_id.startswith("memory:") else f"memory:{memory_id}"
        memory_receipt_json = json.dumps(memory_receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        artifact = ArtifactRef(
            artifact_id=f"memory-recall-fixture:{app_id}:{fixture_id}",
            kind="memory_recall_fixture_receipt",
            media_type="application/json",
            sha256=hashlib.sha256(memory_receipt_json.encode("utf-8")).hexdigest(),
            byte_size=len(memory_receipt_json.encode("utf-8")),
            record_count=1,
        )
        trace_scope = (
            f":schedule:{execution_id}"
            if execution_id is not None
            else ""
        )
        source_loop_scope = (
            f":{execution_id}"
            if execution_id is not None
            else ""
        )
        trace_id = f"trace:{app_id}:self-test:{fixture_id}{trace_scope}"
        trace = build_trace_envelope(
            trace_id=trace_id,
            source_kind="vertical_agent",
            input_text=query,
            binding={
                "sourceLoopId": (
                    f"vertical-self-test:{app_id}:{fixture_id}{source_loop_scope}"
                )
            },
            spans=(
                make_span(
                    span_id="span:input",
                    name="agent.input",
                    started_at_ms=execution_now_ms,
                    ended_at_ms=execution_now_ms + 1,
                ),
                make_span(
                    span_id="span:retrieve",
                    name="rag.retrieve",
                    parent_span_id="span:input",
                    started_at_ms=execution_now_ms + 1,
                    ended_at_ms=execution_now_ms + 2,
                    attributes={"resultCount": len(hits), "retrievalMode": "lexical"},
                ),
                make_span(
                    span_id="span:memory",
                    name="memory.recall",
                    parent_span_id="span:input",
                    started_at_ms=execution_now_ms + 2,
                    ended_at_ms=execution_now_ms + 3,
                    attributes={
                        "producerKind": "fixture",
                        "receiptId": memory_receipt["receiptId"],
                        "memoryId": memory_id,
                    },
                ),
                make_span(
                    span_id="span:answer",
                    name="agent.answer",
                    parent_span_id="span:input",
                    started_at_ms=execution_now_ms + 3,
                    ended_at_ms=execution_now_ms + 4,
                    attributes={"answerFingerprint": fingerprint_text(str(hit.get("content") or ""))},
                ),
            ),
            evidence=(
                EvidenceRef(
                    evidence_id=expected_knowledge_id,
                    source_kind="knowledge",
                    source_ref=citation_ref,
                    source_lane="sandbox_knowledge",
                    evidence_stage="retrieval_output",
                    scores=retrieval_scores,
                    rank_before=1,
                    rank_after=1,
                ),
                EvidenceRef(
                    evidence_id=memory_evidence_id,
                    source_kind="memory",
                    source_ref=memory_source_ref,
                    source_lane="fixture_memory",
                    evidence_stage="memory_recall",
                    rank_before=1,
                    rank_after=1,
                ),
            ),
            artifacts=(artifact,),
            status="completed",
            now_ms=execution_now_ms + 4,
        )
        trace_payload = trace.to_dict()
        if trace_store is not None:
            # The temporary sandbox owns fixtures and intermediate artifacts;
            # the durable Trace authority must retain the exact canonical
            # envelope before that workspace is removed.
            persisted_trace = trace_store.persist(trace)
            if persisted_trace != trace_payload:
                raise VerticalHarnessError(
                    "durable TraceStore returned a different canonical envelope"
                )
        trace_report = verify_vertical_trace(manifest, trace_payload, fixture_id=fixture_id)

        eval_store = EvalRunStore(workspace / "eval.sqlite")
        eval_payload = evaluate_evidence_ground_truth(
            (trace,),
            {trace_id: {"requiredEvidenceIds": declared_truth_ids}},
            dataset_id=f"vertical:{app_id}:public",
            label_revision=str(manifest["suiteRevision"]),
            suite_binding={
                "suiteId": app_id,
                "suiteRevision": str(manifest["suiteRevision"]),
            },
            now_ms=execution_now_ms + 5,
            store=eval_store,
        )
        sandbox_scope = (
            f":schedule:{execution_id}"
            if execution_id is not None
            else ""
        )
        sandbox_payload = build_sandbox_run(
            sandbox_run_id=f"sandbox:{app_id}:self-test:{fixture_id}{sandbox_scope}",
            app_id=app_id,
            workspace_root=str(workspace),
            workspace_binding_id=f"workspace-binding:{app_id}:self-test",
            mutation_mode="staged",
            network="blocked",
            trace_ids=[trace_id],
            eval_run_ids=[str(eval_payload["evalRunId"])],
            now_ms=execution_now_ms + 6,
        ).to_dict()

        artifacts_dir = workspace / "artifacts"
        artifacts_dir.mkdir(mode=0o700, exist_ok=True)
        _write_json(artifacts_dir / "trace.json", trace_payload)
        _write_json(artifacts_dir / "sandbox-run.json", sandbox_payload)
        _write_json(artifacts_dir / "memory-recall-fixture-receipt.json", memory_receipt)
        return {
            "appId": app_id,
            "fixtureId": fixture_id,
            "runId": run_id,
            "importedCount": int(imported.get("importedCount") or 0),
            "retrieval": {
                "externalDocumentId": external_document_id,
                "citationRef": citation_ref,
                "hitCount": len(hits),
                "scores": retrieval_scores,
            },
            "memoryReceipt": memory_receipt,
            "trace": trace_payload,
            "traceVerification": trace_report,
            "evalRun": eval_payload,
            "sandboxRun": sandbox_payload,
            "productionWriteBlocked": True,
            "providerCalls": 0,
            "workspaceBindingId": sandbox_payload["policy"]["workspaceBindingId"],
            "workspaceFingerprint": sandbox_payload["policy"]["workspaceFingerprint"],
        }
    finally:
        sandbox.close()


def _memory_fixture_receipt(
    *,
    app_id: str,
    fixture_id: str,
    memory_id: str,
    source_ref: str,
    summary_fingerprint: str,
) -> dict[str, str]:
    return {
        "schemaVersion": "rag-ime.vertical-agent.memory-recall-fixture-receipt.v1",
        "receiptId": f"memory-recall-fixture:{app_id}:{fixture_id}",
        "producerKind": "fixture",
        "memoryId": memory_id,
        "sourceRef": source_ref,
        "summaryFingerprint": summary_fingerprint,
        "evidenceStage": "memory_recall",
        "disposition": "included",
    }


def _fixture_path(value: object) -> Path:
    relative = _required_text_value(value, "selfTest.fixturePath")
    root = Path(__file__).resolve().parents[1] / "examples" / "vertical_agents"
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise VerticalHarnessError("self-test fixture path must stay inside examples/vertical_agents")
    return candidate


def _first_fixture_id(manifest: Mapping[str, object]) -> str:
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures or not isinstance(fixtures[0], Mapping):
        raise VerticalHarnessError("manifest has no self-test fixture")
    return _required_text(fixtures[0], "fixtureId")


def _declared_truth_ids(manifest: Mapping[str, object], fixture_id: str) -> list[str]:
    fixtures = manifest["fixtures"]
    assert isinstance(fixtures, list) and isinstance(fixtures[0], Mapping)
    selected = next((item for item in fixtures if isinstance(item, Mapping) and item.get("fixtureId") == fixture_id), None)
    if selected is None:
        raise VerticalHarnessError(f"fixture not found: {fixture_id}")
    truth = selected.get("truth")
    if not isinstance(truth, Mapping) or not isinstance(truth.get("requiredEvidenceIds"), list):
        raise VerticalHarnessError("fixture truth is invalid")
    return [
        _required_text_value(value, f"truth.requiredEvidenceIds[{index}]")
        for index, value in enumerate(truth["requiredEvidenceIds"])
    ]


def _mapping(parent: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise VerticalHarnessError(f"{key} must be an object")
    return value


def _required_text(parent: Mapping[str, object], key: str, *, fallback: str | None = None) -> str:
    value = parent.get(key)
    if not value and fallback is not None:
        value = fallback
    return _required_text_value(value, key)


def _required_text_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerticalHarnessError(f"{name} is required")
    return value.strip()


def _schedule_execution_id(value: object) -> str | None:
    """Validate the scheduler-owned identity used to scope one execution."""

    if value is None or value == "":
        return None
    if not isinstance(value, str) or _SCHEDULE_EXECUTION_ID_PATTERN.fullmatch(value) is None:
        raise VerticalHarnessError("schedule run identity must be a bounded token")
    return value


def _schedule_execution_time(value: object, *, fallback: object) -> int:
    """Use the scheduler's due time while keeping direct runs deterministic."""

    candidate = fallback if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
        raise VerticalHarnessError("schedule execution time must be a non-negative integer")
    return candidate


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _retrieval_scores(hit: Mapping[str, object]) -> dict[str, float]:
    if "score" not in hit or hit.get("score") is None:
        return {}
    value = hit.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VerticalHarnessError("retrieval score must be numeric")
    score = float(value)
    if not math.isfinite(score):
        raise VerticalHarnessError("retrieval score must be finite")
    return {"retrieval": score}


def _prepare_workspace(workspace_root: str | Path) -> Path:
    requested = Path(workspace_root).expanduser()
    if requested.is_symlink():
        raise VerticalHarnessError("self-test workspace may not be a symlink")
    if requested.exists():
        if not requested.is_dir():
            raise VerticalHarnessError("self-test workspace must be a directory")
        try:
            next(requested.iterdir())
        except StopIteration:
            pass
        else:
            raise VerticalHarnessError("self-test workspace must be empty")
    else:
        if not requested.parent.exists() or requested.parent.is_symlink():
            raise VerticalHarnessError("self-test workspace parent must already exist and be real")
        try:
            requested.mkdir(mode=0o700)
        except OSError as exc:
            raise VerticalHarnessError(f"self-test workspace could not be created: {exc}") from exc
    requested.chmod(0o700)
    return requested.resolve(strict=True)
