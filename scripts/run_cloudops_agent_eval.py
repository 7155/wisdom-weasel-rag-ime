#!/usr/bin/env python3
"""Run a frozen CloudOps blind suite through real PAW AgentService Sessions.

The orchestration entry point is dependency-injected so tests never launch a
model.  A Host caller supplies its already configured AgentService and the
append-only Trace/Eval/Sandbox/Artifact stores.  Gold is passed only to the
post-terminal scorer callable and never to a Session or Tool gateway.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_artifacts import AgentArtifactStore
from rag_ime.agent_service import AgentService
from rag_ime.cloudops_benchmark_agent import (
    CloudOpsBenchmarkGateway,
    CloudOpsBenchmarkGatewayServer,
    CloudOpsBlindSuite,
)
from rag_ime.eval_run_store import EvalRunStore
from rag_ime.managed_pi_runtime import snapshot_managed_pi_runtime_payload
from rag_ime.pi_runtime import PiRuntimeConfig
from rag_ime.sandbox_run_store import SandboxRunStore
from rag_ime.trace_runtime import (
    ArtifactRef,
    EvidenceRef,
    TraceLink,
    build_eval_run,
    build_sandbox_run,
    build_trace_envelope,
    make_span,
)
from rag_ime.trace_store import TraceStore

HostScorer = Callable[[Path, list[dict[str, object]]], Mapping[str, object]]
_TRIAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\Z")
_SCORE_METRICS = ("AnswerCoverage", "CA", "FA", "JRA", "Top3JRA")
_USAGE_KEYS = ("input", "output", "cacheRead", "cacheWrite", "totalTokens")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    raw = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_trial_id(value: object) -> str:
    normalized = str(value or "").strip()
    if _TRIAL_ID.fullmatch(normalized) is None:
        raise ValueError("CloudOps trial id must be a bounded basename")
    return normalized


def invoke_host_scorer(
    scorer_script: str | Path,
    gold_path: str | Path,
    answers: list[dict[str, object]],
) -> dict[str, object]:
    """Invoke the existing host scorer without putting labels in Agent state."""

    script = Path(scorer_script).expanduser().resolve(strict=True)
    gold = Path(gold_path).expanduser().resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="cloudops-host-score-") as temporary:
        root = Path(temporary)
        answer_path = root / "answers.jsonl"
        output_path = root / "score.json"
        answer_path.write_text(
            "".join(_canonical(answer) + "\n" for answer in answers),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                "python3",
                str(script),
                "--gold",
                str(gold),
                "--answers",
                str(answer_path),
                "--output",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            raise RuntimeError("CloudOps host scorer failed")
        value = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("CloudOps host scorer returned an invalid report")
        return value


def _candidate_runtime_config(
    candidate_root: str | Path,
    *,
    run_root: str | Path,
    source_agent_config: str | Path,
    provider: str,
    model: str,
    tool_gateway_url: str,
    tool_gateway_token: str,
    runtime_wrapper: str | Path | None = None,
    spool_dir: str | Path | None = None,
) -> tuple[PiRuntimeConfig, dict[str, object]]:
    """Verify one explicit payload and create an isolated, non-installed config."""

    candidate = Path(candidate_root).expanduser().resolve(strict=True)
    installation = snapshot_managed_pi_runtime_payload(candidate)
    private_root = Path(run_root).expanduser().resolve(strict=False)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    agent_config = private_root / "agent" / "config"
    agent_config.mkdir(parents=True, exist_ok=True, mode=0o700)
    agent_config.chmod(0o700)
    source = Path(source_agent_config).expanduser().resolve(strict=True)
    copied: list[str] = []
    for name in ("auth.json", "models.json", "models-store.json", "settings.json"):
        source_path = source / name
        if not source_path.is_file() or source_path.is_symlink():
            continue
        target = agent_config / name
        shutil.copy2(source_path, target)
        target.chmod(0o600)
        copied.append(name)
    if "auth.json" not in copied:
        raise RuntimeError("CloudOps candidate Runtime requires an existing auth.json")

    base = PiRuntimeConfig.from_environment(enabled_default=True)
    provider_environment = dict(base.provider_environment)
    executable = Path(installation.executable)
    if runtime_wrapper is not None:
        wrapper = Path(runtime_wrapper).expanduser().resolve(strict=True)
        if spool_dir is None:
            raise ValueError("CloudOps spool Runtime requires a spool directory")
        spool = Path(spool_dir).expanduser().resolve(strict=True)
        provider_environment.update(
            {
                "RAG_IME_BENCHMARK_GATEWAY_SPOOL": str(spool),
                "RAG_IME_BENCHMARK_RUNTIME_ENTRYPOINT": str(executable),
            }
        )
        executable = wrapper
    config = replace(
        base,
        enabled=True,
        executable=executable,
        extension_path=Path(installation.extension_path),
        node_executable=str(installation.node_executable),
        agent_dir=agent_config,
        session_dir=private_root / "agent" / "sessions",
        logs_dir=private_root / "agent" / "logs",
        debug_context_dir=private_root / "agent" / "debug-context",
        provider=str(provider),
        model=str(model),
        tools=tuple(installation.tools),
        tool_gateway_url=str(tool_gateway_url),
        tool_gateway_token=str(tool_gateway_token),
        provider_environment=provider_environment,
        model_configured=True,
        model_configuration_error="",
        pi_version=str(installation.pi_version),
        protocol_version=str(installation.protocol_version),
        installation_error="",
        idle_timeout_seconds=0,
        command_timeout_seconds=60.0,
        max_sessions=1,
    )
    identity = {
        "schemaVersion": "paw.cloudops-runtime-candidate.v1",
        "runtimeVersion": str(installation.runtime_version),
        "piVersion": str(installation.pi_version),
        "protocolVersion": str(installation.protocol_version),
        "manifestSha256": str(installation.manifest_sha256),
        "entrypointSha256": _file_sha256(Path(installation.executable)),
        "nodeSha256": _file_sha256(Path(installation.node_executable)),
        "extensionSha256": _file_sha256(Path(installation.extension_path)),
        "provider": str(provider),
        "model": str(model),
        "toolProfileSha256": _sha256(list(installation.tools)),
        "sourceConfigFiles": sorted(copied),
        "installActionPerformed": False,
    }
    identity["identitySha256"] = _sha256(identity)
    return config, identity


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _public_host_invocation(args: Any, *, transport: str) -> dict[str, object]:
    """Project the reproducibility contract without publishing host locators.

    The private command contains the auth-config, gold, scorer, candidate and
    output paths.  Their identities belong in the bounded runtime/suite/score
    receipts, not in a public argv echo.
    """

    payload: dict[str, object] = {
        "schemaVersion": "paw.cloudops-host-invocation.v1",
        "trialId": _normalize_trial_id(args.trial_id),
        "provider": str(args.provider),
        "model": str(args.model),
        "thinking": str(args.thinking),
        "transport": str(transport),
        "timeoutSeconds": float(args.timeout_seconds),
        "maxReadsPerCase": int(args.max_reads_per_case),
        "workflowProfile": str(getattr(args, "workflow_profile", "baseline-v1")),
        "hostPathsPublished": False,
    }
    payload["commandSha256"] = _sha256(payload)
    return payload


def _assert_expected_runtime(
    receipt: Mapping[str, object],
    *,
    provider: str,
    model: str,
    thinking_level: str,
) -> None:
    state = receipt.get("state")
    selected = state.get("model") if isinstance(state, Mapping) else None
    actual_provider = str(selected.get("provider") or "") if isinstance(selected, Mapping) else ""
    actual_model = str(selected.get("id") or "") if isinstance(selected, Mapping) else ""
    actual_thinking = str(state.get("thinkingLevel") or "") if isinstance(state, Mapping) else ""
    if (actual_provider, actual_model) != (str(provider), str(model)):
        raise RuntimeError("CloudOps evaluation model route drifted from the frozen Runtime identity")
    if actual_thinking != str(thinking_level):
        raise RuntimeError("CloudOps evaluation thinking level drifted from the frozen Runtime identity")


def run_cloudops_agent_eval(
    *,
    suite: CloudOpsBlindSuite,
    gateway: CloudOpsBenchmarkGateway,
    service: Any,
    trial_id: str,
    gold_path: str | Path,
    score_host_only: HostScorer,
    trace_store: TraceStore,
    eval_store: EvalRunStore,
    sandbox_store: SandboxRunStore,
    artifact_store: AgentArtifactStore,
    now_ms: Callable[[], int] | None = None,
    timeout_seconds: float = 600.0,
    runtime_identity: Mapping[str, object] | None = None,
    thinking_level: str = "max",
    workflow_profile: str = "baseline-v1",
) -> dict[str, object]:
    """Execute the frozen batches sequentially and persist one truthful chain."""

    clock = now_ms or (lambda: int(time.time() * 1_000))
    normalized_trial = _normalize_trial_id(trial_id)
    gold = Path(gold_path).expanduser().resolve(strict=True)
    if not gold.is_file():
        raise ValueError("CloudOps host scorer input is unavailable")
    if tuple(suite.batch_ids) != ("batch-1", "batch-2", "batch-3"):
        raise ValueError("CloudOps P0 runner requires the frozen 3x4 batch plan")
    if any(len(suite.assigned_case_ids(batch_id)) != 4 for batch_id in suite.batch_ids):
        raise ValueError("CloudOps P0 runner requires exactly four cases per batch")
    if workflow_profile not in {"baseline-v1", "evidence-search-v1"}:
        raise ValueError("CloudOps workflow profile is unsupported")
    artifact_store.initialize()
    batch_plan = {
        batch_id: list(suite.assigned_case_ids(batch_id)) for batch_id in suite.batch_ids
    }
    input_fingerprint = "sha256:" + _sha256(
        {"suite": suite.suite_sha256, "contract": suite.contract_sha256, "batches": batch_plan}
    )
    public_runtime_identity = dict(runtime_identity or {})
    expected_provider = str(public_runtime_identity.get("provider") or "")
    expected_model = str(public_runtime_identity.get("model") or "")
    expected_model_profile = (
        f"{expected_provider}/{expected_model}"
        if expected_provider and expected_model
        else ""
    )

    artifact_kind = "cloudops_eval"
    record_sequence = 0

    def append(event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
        nonlocal record_sequence
        record_sequence += 1
        return artifact_store.append_records(
            owner_kind="connector_run",
            owner_id=normalized_trial,
            artifact_kind=artifact_kind,
            records=[
                {
                    "recordId": f"{normalized_trial}:{record_sequence:04d}",
                    "eventType": event_type,
                    "sequence": record_sequence,
                    "createdAtMs": clock(),
                    "payload": dict(payload),
                }
            ],
        )

    started_at = clock()
    append(
        "trial_started",
        {
            "trialId": normalized_trial,
            "suiteSha256": suite.suite_sha256,
            "contractSha256": suite.contract_sha256,
            "sourceRevision": suite.source_revision,
            "batchPlanSha256": _sha256(batch_plan),
            "goldVisibleToAgent": False,
            "runtimeIdentity": public_runtime_identity,
            "thinkingLevel": thinking_level,
            "workflowProfile": workflow_profile,
        },
    )
    service.bind_tool_manifest_provider(gateway.runtime_manifests)
    batch_results: list[dict[str, object]] = []
    merged_answers: list[dict[str, object]] = []

    for batch_index, batch_id in enumerate(suite.batch_ids, start=1):
        append(
            "batch_started",
            {
                "batchId": batch_id,
                "assignedCaseIdsSha256": _sha256(list(suite.assigned_case_ids(batch_id))),
            },
        )
        session_payload: dict[str, object] = {
            "title": f"CloudOps blind evaluation {batch_id}",
            "mode": "assistant",
            "roleId": "companion-firstlight-v1",
            "roleVersion": "1",
            "toolProfileVersion": "subagent-readonly-v1",
            "toolAllowlistMode": "explicit",
            "allowedTools": [],
            "_modelRoute": "primary",
        }
        if expected_model_profile:
            session_payload["modelProfile"] = expected_model_profile
        session = service.create_session(session_payload)["session"]
        session_id = str(session["id"])
        service.update_session(
            session_id,
            {
                "mode": "assistant",
                "executionMode": "read_only",
                "toolProfileVersion": "subagent-readonly-v1",
                "toolAllowlistMode": "explicit",
                "allowedTools": [],
                "projectContextEnabled": False,
                "piSkillsEnabled": False,
                "codexSkillsEnabled": False,
                "workspaceRoots": [],
                "thinkingLevel": thinking_level,
            },
        )
        binding = gateway.bind_session(
            session_id,
            batch_id=batch_id,
            workflow_profile=workflow_profile,
        )
        tool_manifest_sha256 = _sha256(gateway.runtime_manifests({"id": session_id})[0])
        prompt = _batch_prompt(
            batch_id,
            suite.assigned_case_ids(batch_id),
            workflow_profile=workflow_profile,
        )
        accepted_at = clock()
        terminal = ""
        turn_id = ""
        events: list[dict[str, object]] = []
        try:
            ensured = service.ensure_runtime({"sessionId": session_id})
            if expected_model_profile:
                _assert_expected_runtime(
                    ensured,
                    provider=expected_provider,
                    model=expected_model,
                    thinking_level=thinking_level,
                )
            receipt = service.prompt(
                session_id,
                {
                    "message": prompt,
                    "clientMessageId": f"cloudops:{normalized_trial}:{batch_id}",
                },
            )
            turn_id = str(receipt.get("turnId") or "")
            events, terminal = _wait_for_terminal(
                service,
                session_id=session_id,
                turn_id=turn_id,
                timeout_seconds=timeout_seconds,
            )
            answers = gateway.answers(session_id)
            if terminal != "turn_completed" or len(answers) != 4:
                raise RuntimeError("CloudOps batch did not complete one canonical submission")
            ledger = gateway.ledger(session_id=session_id)
            merged_answers.extend(answers)
            batch = {
                "batchId": batch_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "promptSha256": _sha256(prompt),
                "acceptedAtMs": accepted_at,
                "terminalEvent": terminal,
                "answersSha256": _sha256(answers),
                "answerCount": len(answers),
                "bindingReceiptId": str(binding["bindingReceiptId"]),
                "ledger": ledger,
                "usage": _token_usage(events),
                "eventCount": len(events),
                "batchIndex": batch_index,
                "modelIdentitySha256": _sha256(ensured),
                "toolManifestSha256": tool_manifest_sha256,
                "workflowProfile": workflow_profile,
            }
            batch_results.append(batch)
            append(
                "batch_completed",
                {
                    "batchId": batch_id,
                    "sessionSha256": _sha256(session_id),
                    "turnSha256": _sha256(turn_id),
                    "answerCount": len(answers),
                    "answersSha256": _sha256(answers),
                    "ledgerSha256": str(ledger["ledgerSha256"]),
                    "terminalEvent": terminal,
                },
            )
        except Exception as exc:
            append(
                "batch_failed",
                {
                    "batchId": batch_id,
                    "sessionSha256": _sha256(session_id),
                    "turnSha256": _sha256(turn_id) if turn_id else "",
                    "errorType": type(exc).__name__,
                    "errorFingerprint": "sha256:" + _sha256(f"{type(exc).__name__}:{exc}"),
                },
            )
            _persist_failed_sandbox(
                sandbox_store,
                trial_id=normalized_trial,
                suite=suite,
                now_ms=clock(),
            )
            raise
        finally:
            removed = gateway.unbind_session(session_id)
            append(
                "batch_cleanup",
                {
                    "batchId": batch_id,
                    "sessionSha256": _sha256(session_id),
                    "gatewayBindingRemoved": removed,
                },
            )

    if len(merged_answers) != 12 or {item["case_id"] for item in merged_answers} != set(suite.case_ids):
        raise RuntimeError("CloudOps merged answers do not cover the frozen suite")
    score = dict(score_host_only(gold, merged_answers))
    metrics, per_case = _validated_score(score, case_ids=suite.case_ids)
    process_signals = _process_signals(score.get("process"))

    batch_trace_ids = [f"trace:cloudops:{normalized_trial}:{item['batchId']}" for item in batch_results]
    aggregate_trace_id = f"trace:cloudops:{normalized_trial}:aggregate"
    batch_eval_ids = [f"eval:cloudops:{normalized_trial}:{item['batchId']}" for item in batch_results]
    aggregate_eval_id = f"eval:cloudops:{normalized_trial}:aggregate"
    sandbox_run_id = f"sandbox:cloudops:{normalized_trial}"
    completed_at = clock()
    total_usage = _sum_usage(batch_results)
    signals = _execution_signals(batch_results, started_at_ms=started_at, completed_at_ms=completed_at)
    append(
        "trial_completed",
        {
            "trialId": normalized_trial,
            "answerSetSha256": _sha256(merged_answers),
            "scoreSha256": _sha256(score),
            "answers": merged_answers,
            "metrics": metrics,
            "processSignals": process_signals,
            "signals": signals,
            "traceIds": [*batch_trace_ids, aggregate_trace_id],
            "evalRunIds": [*batch_eval_ids, aggregate_eval_id],
            "sandboxRunId": sandbox_run_id,
            "cleanup": {"gatewayBindingsRemoved": True, "temporaryOutputsRetained": False},
        },
    )
    artifact_store.checkpoint(
        owner_kind="connector_run",
        owner_id=normalized_trial,
        artifact_kind=artifact_kind,
        projection={
            "state": "completed",
            "completedBatchIds": list(suite.batch_ids),
            "metrics": metrics,
        },
        runtime_checkpoint={"terminal": True},
        updated_at_ms=completed_at,
    )
    artifact_reference = artifact_store.reference(
        owner_kind="connector_run",
        owner_id=normalized_trial,
        artifact_kind=artifact_kind,
    )
    trace_artifact = ArtifactRef(
        artifact_id=str(artifact_reference["artifactId"]),
        kind="cloudops_eval_receipt",
        media_type=str(artifact_reference["mediaType"]),
        sha256=str(artifact_reference["sha256"]),
        byte_size=int(artifact_reference["byteSize"]),
        record_count=int(artifact_reference["recordCount"]),
    )

    persisted_batch_traces: list[dict[str, object]] = []
    persisted_batch_evals: list[dict[str, object]] = []
    for result, trace_id, eval_id in zip(
        batch_results, batch_trace_ids, batch_eval_ids, strict=True
    ):
        trace = _build_batch_trace(
            result,
            trace_id=trace_id,
            trial_id=normalized_trial,
            artifact=trace_artifact,
            now_ms=completed_at,
        )
        persisted_batch_traces.append(trace_store.persist(trace))
        case_ids = suite.assigned_case_ids(str(result["batchId"]))
        values = [float(per_case.get(case_id, {}).get("JRA") or 0.0) for case_id in case_ids]
        batch_accuracy = sum(values) / len(values)
        evaluated = build_eval_run(
            eval_run_id=eval_id,
            trace_ids=[trace_id],
            mode="ground_truth",
            truth_kind="frozen",
            metrics={"accuracy": batch_accuracy},
            dataset_id=f"cloudops-{suite.suite_sha256[:16]}",
            label_revision=f"labels-{suite.contract_sha256[:16]}",
            suite_binding={
                "suiteId": "cloudops-smoke-v1",
                "suiteRevision": suite.suite_sha256[:16],
            },
            latency_ms=_batch_latency_ms(result),
            usage=_numeric_usage(result.get("usage")),
            now_ms=completed_at,
        )
        persisted_batch_evals.append(eval_store.persist(evaluated))

    aggregate_trace = build_trace_envelope(
        trace_id=aggregate_trace_id,
        source_kind="vertical_agent",
        input_text="",
        input_fingerprint=input_fingerprint,
        input_normalization="cloudops-frozen-suite-v1",
        binding={"runId": normalized_trial, "caseId": "cloudops-smoke-v1-3x4"},
        spans=tuple(
            make_span(
                span_id=f"span:batch:{index}",
                name="cloudops.batch",
                started_at_ms=completed_at + index,
                ended_at_ms=completed_at + index + 1,
                attributes={"action": str(item["batchId"])},
                metrics={"count": int(item["answerCount"])},
            )
            for index, item in enumerate(batch_results, start=1)
        ),
        artifacts=(trace_artifact,),
        links=tuple(TraceLink(target_trace_id=value, relation="related") for value in batch_trace_ids),
        status="completed",
        created_at_ms=started_at,
        updated_at_ms=completed_at + 4,
    )
    trace_store.persist(aggregate_trace)
    aggregate_eval = eval_store.persist(
        build_eval_run(
            eval_run_id=aggregate_eval_id,
            trace_ids=[aggregate_trace_id],
            mode="ground_truth",
            truth_kind="frozen",
            metrics={"accuracy": metrics["JRA"]},
            dataset_id=f"cloudops-{suite.suite_sha256[:16]}",
            label_revision=f"labels-{suite.contract_sha256[:16]}",
            suite_binding={
                "suiteId": "cloudops-smoke-v1",
                "suiteRevision": suite.suite_sha256[:16],
            },
            latency_ms=max(0, completed_at - started_at),
            usage=_numeric_usage(total_usage),
            now_ms=completed_at + 5,
        )
    )
    cohort = {
        "suiteId": "cloudops-smoke-v1",
        "suiteRevision": suite.suite_sha256[:16],
        "caseId": "cloudops-smoke-v1-3x4",
        "inputFingerprint": input_fingerprint,
        "environmentFingerprint": "sha256:" + _sha256(
            {"python": sys.version_info[:3], "platform": platform.platform(), "runner": "cloudops-p0-v1"}
        ),
        "configFingerprint": "sha256:" + _sha256(
            {
                "batchPlan": batch_plan,
                "sequential": True,
                "maxReadsPerCase": gateway.max_reads_per_case,
                "workflowProfile": workflow_profile,
            }
        ),
        "modelProfileFingerprint": "sha256:" + _sha256(
            public_runtime_identity.get("identitySha256")
            or [item.get("modelIdentitySha256", "") for item in batch_results]
        ),
        "toolProfileFingerprint": "sha256:" + _sha256(
            [item.get("toolManifestSha256", "") for item in batch_results]
        ),
        "skillProfileFingerprint": "sha256:" + _sha256("none"),
    }
    sandbox_store.persist(
        build_sandbox_run(
            sandbox_run_id=sandbox_run_id,
            app_id="changeops",
            workspace_root=f"cloudops-blind:{suite.suite_sha256}",
            workspace_binding_id=f"workspace-binding:cloudops:{suite.suite_sha256[:24]}",
            mutation_mode="read_only",
            network="allowlisted",
            trace_ids=[*batch_trace_ids, aggregate_trace_id],
            eval_run_ids=[*batch_eval_ids, aggregate_eval_id],
            replay_cohort=cohort,
            status="completed",
            now_ms=completed_at + 6,
        )
    )
    public_batches = []
    for item in batch_results:
        ledger = item.get("ledger")
        ledger_items = ledger.get("items") if isinstance(ledger, Mapping) else []
        if not isinstance(ledger_items, list):
            ledger_items = []
        batch_id = str(item["batchId"])
        public_batches.append(
            {
                "batchId": batch_id,
                "batchIndex": int(item["batchIndex"]),
                "assignedCaseIdsSha256": _sha256(list(suite.assigned_case_ids(batch_id))),
                "terminalEvent": str(item["terminalEvent"]),
                "answerCount": int(item["answerCount"]),
                "answersSha256": str(item["answersSha256"]),
                "ledgerSha256": str(ledger.get("ledgerSha256") or "")
                if isinstance(ledger, Mapping)
                else "",
                "usage": dict(item.get("usage") or {}),
                "toolCalls": len(ledger_items),
                "successfulToolCalls": sum(
                    entry.get("ok") is True for entry in ledger_items if isinstance(entry, Mapping)
                ),
                "latencyMs": _batch_latency_ms(item),
            }
        )
    return {
        "schemaVersion": "paw.cloudops-agent-eval-run.v1",
        "trialId": normalized_trial,
        "status": "completed",
        "suiteSha256": suite.suite_sha256,
        "contractSha256": suite.contract_sha256,
        "batchPlan": "3x4-sequential",
        "batchPlanSha256": _sha256(batch_plan),
        "batchCount": 3,
        "caseCount": 12,
        "batches": public_batches,
        "metrics": metrics,
        "processSignals": process_signals,
        "usage": total_usage,
        "signals": signals,
        "traceIds": [*batch_trace_ids, aggregate_trace_id],
        "evalRunIds": [*batch_eval_ids, aggregate_eval_id],
        "aggregateTraceId": aggregate_trace_id,
        "aggregateEvalRunId": str(aggregate_eval["evalRunId"]),
        "sandboxRunId": sandbox_run_id,
        "artifactId": str(artifact_reference["artifactId"]),
        "cleanup": {"gatewayBindingsRemoved": True, "temporaryOutputsRetained": False},
        "goldVisibleToAgent": False,
        "runtimeIdentity": public_runtime_identity,
        "thinkingLevel": thinking_level,
        "workflowProfile": workflow_profile,
        "replayCohort": cohort,
    }


def _batch_prompt(
    batch_id: str,
    case_ids: tuple[str, ...],
    *,
    workflow_profile: str = "baseline-v1",
) -> str:
    base = (
        "This is a frozen, read-only CloudOps blind evaluation. "
        "Use only cloudops_benchmark. Call index, selectively list and read exact observations, "
        "then call submit once with exactly the four assigned cases. Do not use workspace, shell, "
        f"network, or external context. Batch={batch_id}; cases={','.join(case_ids)}."
    )
    if workflow_profile == "baseline-v1":
        return base
    if workflow_profile != "evidence-search-v1":
        raise ValueError("CloudOps workflow profile is unsupported")
    return (
        base
        + " Use search before paging list when a symptom, service, Tool or competing root cause is known; "
        "read only the discriminating observations returned by search. For performance cases, first localize "
        "the affected component, then inspect connectivity and network evidence before choosing between a "
        "network fault and an application-code delay. Empty application logs do not distinguish those causes; "
        "do not choose a code delay without direct code or runtime evidence."
    )


def _persist_failed_sandbox(
    store: SandboxRunStore,
    *,
    trial_id: str,
    suite: CloudOpsBlindSuite,
    now_ms: int,
) -> dict[str, object]:
    return store.persist(
        build_sandbox_run(
            sandbox_run_id=f"sandbox:cloudops:{trial_id}",
            app_id="changeops",
            workspace_root=f"cloudops-blind:{suite.suite_sha256}",
            workspace_binding_id=f"workspace-binding:cloudops:{suite.suite_sha256[:24]}",
            mutation_mode="read_only",
            network="allowlisted",
            trace_ids=[],
            eval_run_ids=[],
            status="failed",
            now_ms=now_ms,
        )
    )


def _wait_for_terminal(
    service: Any,
    *,
    session_id: str,
    turn_id: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, object]], str]:
    deadline = time.monotonic() + max(0.01, float(timeout_seconds))
    while time.monotonic() < deadline:
        events, gap = service.events.replay(session_id)
        if gap:
            raise RuntimeError("CloudOps Agent event replay developed a gap")
        selected = [event.to_payload() for event in events if not turn_id or event.turn_id in {"", turn_id}]
        terminal = next(
            (
                event.event_type
                for event in reversed(events)
                if event.turn_id == turn_id and event.event_type in {"turn_completed", "turn_failed"}
            ),
            "",
        )
        if terminal:
            return selected, terminal
        time.sleep(0.05)
    service.abort(session_id)
    raise TimeoutError("CloudOps Agent turn did not settle before its timeout")


def _validated_score(
    score: Mapping[str, object],
    *,
    case_ids: tuple[str, ...],
) -> tuple[dict[str, float], dict[str, Mapping[str, object]]]:
    aggregate = score.get("aggregate")
    if not isinstance(aggregate, Mapping):
        raise RuntimeError("CloudOps host scorer returned no aggregate")
    metrics: dict[str, float] = {}
    for key in _SCORE_METRICS:
        raw = aggregate.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise RuntimeError(f"CloudOps host scorer omitted required metric {key}")
        value = float(raw)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise RuntimeError(f"CloudOps host scorer returned invalid metric {key}")
        metrics[key] = value

    raw_per_case = score.get("perCase")
    if not isinstance(raw_per_case, list):
        raise RuntimeError("CloudOps host scorer returned no per-case metrics")
    per_case: dict[str, Mapping[str, object]] = {}
    expected = set(case_ids)
    for raw in raw_per_case:
        if not isinstance(raw, Mapping):
            raise RuntimeError("CloudOps host scorer returned an invalid per-case metric")
        case_id = str(raw.get("case_id") or "")
        jra = raw.get("JRA")
        if case_id not in expected or case_id in per_case:
            raise RuntimeError("CloudOps host scorer returned duplicate or unknown cases")
        if isinstance(jra, bool) or not isinstance(jra, (int, float)):
            raise RuntimeError("CloudOps host scorer omitted a per-case JRA metric")
        numeric = float(jra)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise RuntimeError("CloudOps host scorer returned an invalid per-case JRA metric")
        per_case[case_id] = dict(raw)
    if set(per_case) != expected:
        raise RuntimeError("CloudOps host scorer did not cover the frozen case set")
    return metrics, per_case


def _token_usage(events: list[Mapping[str, object]]) -> dict[str, object]:
    totals = {key: 0 for key in _USAGE_KEYS}
    available = False
    for event in events:
        usage = event.get("usage")
        if not isinstance(usage, Mapping):
            continue
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[key] += value
                available = True
    if not available:
        return {"available": False}
    if totals["totalTokens"] == 0:
        totals["totalTokens"] = totals["input"] + totals["output"] + totals["cacheRead"] + totals["cacheWrite"]
    return {"available": True, **totals}


def _sum_usage(batch_results: list[Mapping[str, object]]) -> dict[str, object]:
    result = {key: 0 for key in _USAGE_KEYS}
    available = bool(batch_results)
    for batch in batch_results:
        usage = batch.get("usage")
        if not isinstance(usage, Mapping) or usage.get("available") is not True:
            available = False
            continue
        for key in result:
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                available = False
                break
            result[key] += value
    return {"available": True, **result} if available else {"available": False}


def _numeric_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or value.get("available") is not True:
        return {}
    return {
        key: int(value[key])
        for key in _USAGE_KEYS
        if isinstance(value.get(key), int) and not isinstance(value.get(key), bool)
    }


def _execution_signals(
    batch_results: list[Mapping[str, object]],
    *,
    started_at_ms: int,
    completed_at_ms: int,
) -> dict[str, object]:
    items = [
        item
        for batch in batch_results
        if isinstance(batch.get("ledger"), Mapping)
        for item in batch["ledger"].get("items") or []
        if isinstance(item, Mapping)
    ]
    first_started = min(
        (int(item.get("startedAtMs") or 0) for item in items if int(item.get("startedAtMs") or 0) > 0),
        default=started_at_ms,
    )
    return {
        "batchCount": len(batch_results),
        "toolCalls": len(items),
        "successfulToolCalls": sum(item.get("ok") is True for item in items),
        "failedToolCalls": sum(item.get("ok") is not True for item in items),
        "readCalls": sum(item.get("operation") == "read" for item in items),
        "listCalls": sum(item.get("operation") == "list" for item in items),
        "searchCalls": sum(item.get("operation") == "search" for item in items),
        "firstToolLatencyMs": max(0, first_started - started_at_ms),
        "elapsedMs": max(0, completed_at_ms - started_at_ms),
    }


def _process_signals(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {"available": False, "authority": "diagnostic"}
    result: dict[str, object] = {
        "available": True,
        "authority": str(value.get("authority") or "diagnostic"),
    }
    for key in ("MC", "EOC", "EE", "processCompleteRate", "meanSteps"):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            result[key] = float(raw)
    return result


def _batch_latency_ms(result: Mapping[str, object]) -> int:
    ledger = result.get("ledger")
    items = ledger.get("items") if isinstance(ledger, Mapping) else []
    if not isinstance(items, list) or not items:
        return 0
    starts = [int(item.get("startedAtMs") or 0) for item in items if isinstance(item, Mapping)]
    ends = [int(item.get("endedAtMs") or 0) for item in items if isinstance(item, Mapping)]
    return max(0, max(ends, default=0) - min(starts, default=0))


def _build_batch_trace(
    result: Mapping[str, object],
    *,
    trace_id: str,
    trial_id: str,
    artifact: ArtifactRef,
    now_ms: int,
):
    ledger = result.get("ledger")
    items = ledger.get("items") if isinstance(ledger, Mapping) else []
    if not isinstance(items, list):
        items = []
    spans = [
        make_span(
            span_id="span:agent-turn",
            name="agent.turn",
            started_at_ms=now_ms,
            ended_at_ms=now_ms + 1,
            attributes={"action": str(result["batchId"])},
            metrics={"count": int(result["answerCount"])},
        )
    ]
    evidence: list[EvidenceRef] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            continue
        start = int(item.get("startedAtMs") or now_ms)
        end = max(start, int(item.get("endedAtMs") or start))
        operation = str(item.get("operation") or "unknown")
        spans.append(
            make_span(
                span_id=f"span:tool:{index}",
                name=f"cloudops.{operation}",
                parent_span_id="span:agent-turn",
                started_at_ms=start,
                ended_at_ms=end,
                status="completed" if item.get("ok") is True else "failed",
                attributes={"action": operation},
            )
        )
        summary = item.get("resultSummary")
        args = item.get("args")
        if operation == "read" and item.get("ok") is True and isinstance(summary, Mapping):
            observation_sha = str(summary.get("observationSha256") or "")
            case_id = str(args.get("caseId") or "") if isinstance(args, Mapping) else ""
            if observation_sha and case_id:
                evidence.append(
                    EvidenceRef(
                        evidence_id=str(summary.get("evidenceId") or f"evidence:cloudops:{observation_sha[:32]}"),
                        source_kind="tool",
                        source_ref=(
                            "fixture://cloudops/"
                            + _sha256(trial_id)[:16]
                            + "/"
                            + _sha256(case_id)[:16]
                            + "/"
                            + observation_sha
                        ),
                        source_lane="cloudops_blind",
                        evidence_stage="tool_observation",
                    )
                )
    return build_trace_envelope(
        trace_id=trace_id,
        source_kind="vertical_agent",
        input_text="",
        input_fingerprint="sha256:" + str(result["promptSha256"]),
        input_normalization=f"cloudops-batch-prompt:{result.get('workflowProfile') or 'baseline-v1'}",
        binding={
            "sessionId": str(result["sessionId"]),
            "turnId": str(result["turnId"]),
            "runId": trial_id,
            "sourceLoopId": str(result["turnId"]),
            "caseId": str(result["batchId"]),
        },
        spans=tuple(spans),
        evidence=tuple(evidence),
        artifacts=(artifact,),
        status="completed",
        created_at_ms=now_ms,
        updated_at_ms=now_ms + max(2, len(spans)),
    )


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-candidate", type=Path, required=True)
    parser.add_argument("--blind-root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True)
    parser.add_argument("--source-agent-config", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--provider", default="openai-codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--thinking", default="max")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--max-reads-per-case", type=int, default=40)
    parser.add_argument(
        "--workflow-profile",
        choices=("baseline-v1", "evidence-search-v1"),
        default="baseline-v1",
    )
    parser.add_argument("--transport", choices=("spool", "loopback"), default="spool")
    args = parser.parse_args(argv)

    args.trial_id = _normalize_trial_id(args.trial_id)
    private_root = args.private_root.expanduser().resolve(strict=False)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_root = (private_root / args.trial_id).resolve(strict=False)
    try:
        run_root.relative_to(private_root)
    except ValueError as exc:
        raise ValueError("CloudOps trial root escapes the private root") from exc
    if run_root.exists():
        raise FileExistsError("CloudOps trial root already exists")
    run_root.mkdir(mode=0o700)
    suite = CloudOpsBlindSuite(args.blind_root)
    gateway = CloudOpsBenchmarkGateway(
        suite,
        max_reads_per_case=max(1, int(args.max_reads_per_case)),
    )
    transport: object
    runtime_wrapper: Path | None = None
    spool_dir: Path | None = None
    if args.transport == "spool":
        from rag_ime.rag_benchmark_agent import RagBenchmarkAgentSpoolGateway

        spool_dir = run_root / "agent" / "tool-spool"
        transport = RagBenchmarkAgentSpoolGateway(gateway, spool_dir=spool_dir)
        runtime_wrapper = ROOT / "scripts" / "rag_agent_spool_runtime_wrapper.mjs"
    else:
        transport = CloudOpsBenchmarkGatewayServer(gateway)
    transport.start()
    service: AgentService | None = None
    try:
        config, runtime_identity = _candidate_runtime_config(
            args.runtime_candidate,
            run_root=run_root,
            source_agent_config=args.source_agent_config,
            provider=args.provider,
            model=args.model,
            tool_gateway_url=transport.tool_gateway_url,
            tool_gateway_token=transport.token,
            runtime_wrapper=runtime_wrapper,
            spool_dir=spool_dir,
        )
        database = run_root / "observability.sqlite"
        service = AgentService(
            db_path=database,
            runtime_config=config,
            project="cloudops-benchmark-agent",
            tool_gateway_url=transport.tool_gateway_url,
            tool_gateway_token=transport.token,
            wake_scheduler_enabled=False,
            background_job_execution_owner=False,
        )
        report = run_cloudops_agent_eval(
            suite=suite,
            gateway=gateway,
            service=service,
            trial_id=args.trial_id,
            gold_path=args.gold,
            score_host_only=lambda gold, answers: invoke_host_scorer(
                args.scorer,
                gold,
                answers,
            ),
            trace_store=service.trace_store,
            eval_store=service.eval_runs,
            sandbox_store=service.sandbox_runs,
            artifact_store=AgentArtifactStore(
                database,
                root=run_root / "agent-artifacts",
            ),
            timeout_seconds=max(30.0, float(args.timeout_seconds)),
            runtime_identity=runtime_identity,
            thinking_level=str(args.thinking),
            workflow_profile=str(args.workflow_profile),
        )
        report["hostInvocation"] = _public_host_invocation(
            args,
            transport=str(getattr(transport, "transport", "")),
        )
    except Exception as exc:
        failure = {
            "schemaVersion": "paw.cloudops-agent-eval-failure.v1",
            "trialId": args.trial_id,
            "status": "failed",
            "errorType": type(exc).__name__,
            "errorFingerprint": "sha256:" + _sha256(f"{type(exc).__name__}:{exc}"),
            "hostInvocation": _public_host_invocation(
                args,
                transport=str(getattr(transport, "transport", "")),
            ),
        }
        _write_json_atomic(args.output, failure)
        raise
    finally:
        if service is not None:
            service.close()
        transport.close()
    _write_json_atomic(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _write_json_atomic(path: str | Path, value: Mapping[str, object]) -> None:
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(target)


if __name__ == "__main__":
    raise SystemExit(main())
