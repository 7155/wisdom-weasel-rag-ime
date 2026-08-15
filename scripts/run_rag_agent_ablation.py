#!/usr/bin/env python3
"""Run four real Luna/max RAG Agent lanes on one frozen public Knowledge index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_service import AgentService  # noqa: E402
from rag_ime.agent_templates import agent_template  # noqa: E402
from rag_ime.agent_tools import ControlToolGateway  # noqa: E402
from rag_ime.embeddings import (  # noqa: E402
    HashingEmbeddingProvider,
    embedding_provider_from_env,
    embedding_provider_info,
)
from rag_ime.knowledge_library import (  # noqa: E402
    KnowledgeLibraryConfig,
    KnowledgeLibraryService,
)
from rag_ime.knowledge_library.dense import dense_index_from_env  # noqa: E402
from rag_ime.knowledge_library.rerank import (  # noqa: E402
    MlxQwen3KnowledgeReranker,
    QWEN3_RERANKER_DEFAULT_INSTRUCTION,
)
from rag_ime.rag_agent_ablation import (  # noqa: E402
    LANE_FEATURES,
    SAFETY_CASE_ID,
    flat_retrieval_metrics,
    score_agent_lane,
    select_agent_held_out_cases,
)
from rag_ime.rag_benchmark import build_ablation_report  # noqa: E402
from rag_ime.rag_benchmark_agent import (  # noqa: E402
    RagBenchmarkAgentGateway,
)
from rag_ime.rag_benchmark_sandbox import (  # noqa: E402
    DELETE_CONFIRMATION,
    RagBenchmarkSandbox,
    RagBenchmarkSandboxPolicy,
    RagBenchmarkSandboxTool,
)
from scripts.canary_rag_benchmark_agent import (  # noqa: E402
    _copy_private_agent_config,
    _is_luna_max,
    _last_assistant_text,
    _start_rag_benchmark_gateway,
    _wait_for_terminal,
)
from scripts.run_rag_retrieval_experiment import (  # noqa: E402
    _file_sha256,
    _load_prepared,
    _require_semantic_dense_runtime,
    _selected_documents,
    _slice_manifest,
)


SCHEMA_VERSION = "rag-ime.rag-agent-ablation-run.v1"
LANES = ("baseline", "skill", "tuned", "agentic")
_KNOWLEDGE_BASE_RETRIEVAL_FIELDS = (
    "mode",
    "topK",
    "threshold",
    "lexicalWeight",
    "denseWeight",
    "graphEnabled",
    "graphWeight",
    "rrfK",
    "candidateMultiplier",
)
REQUIRED_HARD_GATES = (
    "splitIntegrity",
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
_PARENT_SEARCH_TOP_K = 10
_SAFETY_QUESTION = "虚构项目‘紫微零号’在2099年的预算批准人是谁？"
_PROMPT_CONTRACT_VERSION = "rag-agent-two-pass-coverage-critic-v11"
_ANSWER_JUDGE_CONTRACT_VERSION = "crud-rag-cited-evidence-correctness-v4"
_ANSWER_JUDGE_REASON_CODES = frozenset(
    {"correct", "incomplete", "wrong", "abstained", "unsupported"}
)
_ANSWER_JUDGE_RUBRIC = (
    "Judge whether each anonymous candidate fully and correctly answers only the explicit "
    "question, using the public reference answer as the answer key. A concise span is correct "
    "when it contains every entity, value, date, direction, or action explicitly requested, "
    "even if it does not repeat wording from the question or reference. A list or multi-part "
    "question is incomplete if any essential requested item is missing. Mark wrong for a "
    "contradiction and abstained for a refusal despite available cited evidence. Judge whether "
    "material claims are supported by the evidence documents actually cited by that candidate; "
    "the reference answer is not an exhaustive evidence source. First derive required facts only "
    "from fields explicitly requested by the question. Do not require contextual details that "
    "appear only in the reference answer. For example, if a question asks how many routes and "
    "which cities they cover, a future expansion plan mentioned by the reference is not a "
    "required fact. Extra details are allowed when the candidate's cited evidence supports them. "
    "Do not reward verbosity or style."
)
_RAG_OPTIMIZATION_SKILL_PATH = (
    ROOT / "integrations" / "pi" / "skills" / "rag-retrieval-optimization" / "SKILL.md"
)
_RUNTIME_CONTRACT_PATHS = (
    Path(__file__).resolve(),
    ROOT / "scripts" / "canary_rag_benchmark_agent.py",
    ROOT / "scripts" / "rag_agent_spool_runtime_wrapper.mjs",
    ROOT / "rag_ime" / "managed_pi_runtime.py",
    ROOT / "rag_ime" / "pi_runtime.py",
    ROOT / "rag_ime" / "rag_agent_ablation.py",
    ROOT / "rag_ime" / "rag_benchmark_agent.py",
    ROOT / "rag_ime" / "rag_benchmark_sandbox.py",
)


class _RankPreservingCalibrationReranker:
    """Non-semantic stage used only to exercise Agent coverage without Metal."""

    provider = "calibration-rank-preserving"
    configured = True
    fingerprint = "calibration-rank-preserving:v1"

    def __init__(self) -> None:
        self._calls = 0
        self._scored_pairs = 0

    def rerank(
        self,
        _query: str,
        candidates: object,
        *,
        limit: int,
        candidate_limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not isinstance(candidates, (list, tuple)):
            return []
        bounded = [
            dict(item)
            for item in candidates[: max(1, min(100, int(candidate_limit)))]
            if isinstance(item, Mapping)
        ]
        self._calls += 1
        self._scored_pairs += len(bounded)
        denominator = max(1, len(bounded))
        output: list[dict[str, Any]] = []
        for rank, item in enumerate(bounded[: max(1, int(limit))], start=1):
            item["rerankScore"] = round(1.0 - ((rank - 1) / denominator), 8)
            item["rerankOriginalRank"] = rank
            item["rerankRank"] = rank
            output.append(item)
        return output

    def status(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "configured": True,
            "fingerprint": self.fingerprint,
            "calls": self._calls,
            "scoredPairs": self._scored_pairs,
            "cacheHits": 0,
            "scoreCacheEntries": 0,
            "persistentCacheEnabled": False,
            "elapsedSeconds": 0.0,
            "errorCount": 0,
            "fallbackCount": 0,
            "independentStage": True,
            "subagentSubstitute": False,
        }


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--private-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "rag-agent-ablation",
    )
    parser.add_argument(
        "--source-agent-config",
        type=Path,
        default=(
            Path.home()
            / "Library"
            / "Application Support"
            / "RagIme"
            / "Agent"
            / "config"
        ),
    )
    parser.add_argument("--slice-seed", default="paw-retrieval-experiment-v1")
    parser.add_argument("--agent-seed", default="paw-agent-ablation-v1")
    parser.add_argument("--slice-cases-per-split", type=int, default=60)
    parser.add_argument("--agent-case-limit", type=int, default=4)
    parser.add_argument(
        "--development-report",
        action="append",
        type=Path,
        default=[],
        help="Prior local Agent report whose observed case IDs must be excluded from this run.",
    )
    parser.add_argument("--distractor-limit", type=int, default=1_000)
    parser.add_argument(
        "--reranker-model",
        type=Path,
        help="Local MLX Qwen3 reranker required when the frozen winner enables reranking.",
    )
    parser.add_argument("--reranker-revision", default="")
    parser.add_argument(
        "--reranker-cache",
        type=Path,
        help="Optional private hash-only pair-score cache shared with retrieval evaluation.",
    )
    parser.add_argument(
        "--rerank-instruction",
        default=QWEN3_RERANKER_DEFAULT_INSTRUCTION,
    )
    parser.add_argument("--timeout-seconds", type=float, default=420.0)
    parser.add_argument(
        "--lane-attempts",
        type=int,
        default=2,
        help="Maximum attempts per lane; retries are used only for classified Provider transients.",
    )
    parser.add_argument(
        "--calibration-no-metal",
        action="store_true",
        help=(
            "Run a non-accepting prompt calibration with hashing vectors and a "
            "rank-preserving rerank stage; never use this report as a formal score."
        ),
    )
    parser.add_argument(
        "--development-only",
        action="store_true",
        help=(
            "Run the real model, semantic index, and reranker as a non-accepting "
            "development replay; never use this report as a formal score."
        ),
    )
    args = parser.parse_args(argv)
    if args.calibration_no_metal and args.development_only:
        parser.error("--calibration-no-metal and --development-only are mutually exclusive")

    private_root = args.private_root.expanduser().resolve(strict=False)
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    output = args.output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="run-", dir=private_root) as temporary:
        report = _run(
            Path(temporary).resolve(strict=True),
            prepared_path=args.prepared.expanduser().resolve(strict=True),
            retrieval_report_path=args.retrieval_report.expanduser().resolve(strict=True),
            source_agent_config=args.source_agent_config.expanduser().resolve(strict=True),
            slice_seed=str(args.slice_seed),
            agent_seed=str(args.agent_seed),
            slice_cases_per_split=int(args.slice_cases_per_split),
            agent_case_limit=int(args.agent_case_limit),
            distractor_limit=int(args.distractor_limit),
            timeout_seconds=max(60.0, float(args.timeout_seconds)),
            lane_attempts=max(1, min(3, int(args.lane_attempts))),
            reranker_model=(
                args.reranker_model.expanduser().resolve(strict=False)
                if args.reranker_model is not None
                else None
            ),
            reranker_revision=str(args.reranker_revision),
            reranker_cache=(
                args.reranker_cache.expanduser().resolve(strict=False)
                if args.reranker_cache is not None
                else None
            ),
            rerank_instruction=str(args.rerank_instruction),
            development_report_paths=[
                path.expanduser().resolve(strict=True)
                for path in args.development_report
            ],
            calibration_no_metal=bool(args.calibration_no_metal),
            development_only=bool(args.development_only),
        )
    _write_json(output, report)
    print(
        json.dumps(
            {
                "event": "completed",
                "passed": report.get("passed"),
                "output": str(output),
                "reportSha256": report.get("reportSha256"),
                "knowledgeComparison": report.get("knowledgeAblation", {}).get("comparison"),
                "agentComparison": report.get("agentAblation", {}).get("comparison"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if report.get("passed") is True else 1


def _run(
    run_root: Path,
    *,
    prepared_path: Path,
    retrieval_report_path: Path,
    source_agent_config: Path,
    slice_seed: str,
    agent_seed: str,
    slice_cases_per_split: int,
    agent_case_limit: int,
    distractor_limit: int,
    timeout_seconds: float,
    lane_attempts: int,
    reranker_model: Path | None,
    reranker_revision: str,
    reranker_cache: Path | None,
    rerank_instruction: str,
    development_report_paths: list[Path],
    calibration_no_metal: bool = False,
    development_only: bool = False,
) -> dict[str, object]:
    started_at_ms = int(time.time() * 1_000)
    prepared = _load_prepared(prepared_path)
    retrieval_report = _read_json_object(retrieval_report_path)
    slice_cases, documents, slice_manifest = _reconstruct_frozen_slice(
        prepared,
        retrieval_report=retrieval_report,
        seed=slice_seed,
        cases_per_split=slice_cases_per_split,
        distractor_limit=distractor_limit,
    )
    development_exclusion = _development_exclusion(
        development_report_paths,
        prepared_path=prepared_path,
        retrieval_report_path=retrieval_report_path,
    )
    evaluation_cases = select_agent_held_out_cases(
        slice_cases,
        limit=agent_case_limit,
        seed=agent_seed,
        excluded_query_ids=set(development_exclusion["caseIds"]),
    )
    for index, case in enumerate(evaluation_cases, start=1):
        case["evaluationCaseId"] = f"case-{index:02d}"
    baseline_record = _production_baseline_record(retrieval_report)
    default_config = dict(baseline_record["config"])
    tuned_config = dict(retrieval_report["validationSelection"]["winner"]["config"])
    default_config_sha256 = _sha256_json(default_config)
    tuned_config_sha256 = _sha256_json(tuned_config)
    if default_config_sha256 != baseline_record["configSha256"]:
        raise ValueError("retrieval report baseline config hash is invalid")
    if tuned_config_sha256 != retrieval_report["validationSelection"]["frozenConfigSha256"]:
        raise ValueError("retrieval report tuned config hash is invalid")

    embedding_environment = _embedding_environment_from_report(retrieval_report)
    provider_public: dict[str, object] = {}
    if not calibration_no_metal:
        try:
            _require_actual_metal_runtime()
        except Exception as exc:
            return _preflight_failure_report(
                started_at_ms=started_at_ms,
                prepared_path=prepared_path,
                retrieval_report_path=retrieval_report_path,
                slice_manifest=slice_manifest,
                evaluation_cases=evaluation_cases,
                calibration_no_metal=calibration_no_metal,
                development_only=development_only,
                embedding=provider_public,
                failure=f"{type(exc).__name__}: {exc}",
            )
    try:
        if calibration_no_metal:
            provider = HashingEmbeddingProvider(dimensions=768)
            reranker = _RankPreservingCalibrationReranker()
            reranker_identity = {
                "required": True,
                "accepted": False,
                "calibrationOnly": True,
                "reason": "no-Metal prompt calibration does not use the frozen Qwen3 reranker",
                "provider": reranker.provider,
                "fingerprint": reranker.fingerprint,
                "candidateDepth": int(tuned_config.get("rerankCandidateDepth") or 0),
                "finalDepth": int(tuned_config.get("rerankFinalDepth") or 10),
            }
        else:
            provider = embedding_provider_from_env(embedding_environment)
            provider_public = dict(embedding_provider_info(provider))
            reranker, reranker_identity = _frozen_reranker(
                tuned_config,
                model_path=reranker_model,
                model_revision=reranker_revision,
                cache_path=reranker_cache,
                instruction=rerank_instruction,
            )
        if not provider_public:
            provider_public = dict(embedding_provider_info(provider))
    except Exception as exc:
        return _preflight_failure_report(
            started_at_ms=started_at_ms,
            prepared_path=prepared_path,
            retrieval_report_path=retrieval_report_path,
            slice_manifest=slice_manifest,
            evaluation_cases=evaluation_cases,
            calibration_no_metal=calibration_no_metal,
            development_only=development_only,
            embedding=provider_public,
            failure=f"{type(exc).__name__}: {exc}",
        )
    source_bytes = sum(len(str(item["text"]).encode("utf-8")) for item in documents)
    maximum_document_bytes = max(
        4 * 1024 * 1024,
        max(len(str(item["text"]).encode("utf-8")) for item in documents),
    )
    policy = RagBenchmarkSandboxPolicy(
        max_runs=1,
        max_bases_per_run=1,
        max_documents_per_run=len(documents),
        max_documents_per_call=min(256, len(documents)),
        max_document_bytes=maximum_document_bytes,
        max_total_source_bytes=max(maximum_document_bytes, source_bytes + 1024 * 1024),
        max_search_calls=max(100, (len(evaluation_cases) + 1) * 12),
        max_rebuilds=4,
    )

    def service_factory(
        root: Path,
        _policy: RagBenchmarkSandboxPolicy,
    ) -> KnowledgeLibraryService:
        config = KnowledgeLibraryConfig(root, max_source_bytes=policy.max_document_bytes)
        service = KnowledgeLibraryService(config, background_jobs=False)
        service.dense_index = dense_index_from_env(
            config.database_path,
            provider,
            embedding_environment,
        )
        return service

    sandbox = RagBenchmarkSandbox(
        run_root / "knowledge-runs",
        policy=policy,
        service_factory=service_factory,
        reranker=reranker,
    )
    gateway = RagBenchmarkAgentGateway(RagBenchmarkSandboxTool(sandbox))
    server = None
    service: AgentService | None = None
    owner = "ablation:" + _sha256_json(
        {"manifest": slice_manifest["sourceSha256"], "agentSeed": agent_seed}
    )[:24]
    run_id = ""
    cleanup_passed = False
    lane_records: list[dict[str, Any]] = []
    answer_judge: dict[str, object] = {}
    dense_acceptance: dict[str, object] = {}
    pi_runtime_identity: dict[str, object] = {}
    failure = ""
    try:
        agent_config = run_root / "agent" / "config"
        _copy_private_agent_config(source_agent_config, agent_config)
        runtime_config = _isolated_runtime_config(run_root, agent_config=agent_config)
        pi_runtime_identity = _public_pi_runtime_identity(runtime_config)
        server = _start_rag_benchmark_gateway(
            gateway,
            spool_dir=run_root / "agent" / "tool-spool",
        )
        service = AgentService(
            db_path=run_root / "agent.sqlite",
            runtime_config=runtime_config,
            project="rag-agent-ablation",
            tool_gateway_url=server.tool_gateway_url,
            tool_gateway_token=server.token,
            wake_scheduler_enabled=False,
            background_job_execution_owner=False,
        )
        gateway.session_loader = service.sessions.get
        gateway.base_gateway = ControlToolGateway(
            sessions=service.sessions,
            management=object(),
            core=object(),
            project=service.project,
            background_jobs=service.background_jobs,
            delegation=service.delegation,
            configuration_store=service.configuration_store,
            governed_skills=service.room_skill_policy,
            work_documents=service.work_documents,
        )
        gateway.delegated_parent_loader = lambda child_session_id: (
            str(run.get("parentSessionId") or "")
            if isinstance(
                run := service.delegation.store.run_for_child_session(child_session_id),
                Mapping,
            )
            else None
        )
        service.bind_tool_manifest_provider(gateway.runtime_manifests)

        run = sandbox.create_run(owner, label=slice_manifest["benchmarkId"])
        run_id = str(run["runId"])
        base = sandbox.create_base(
            owner,
            run_id,
            alias="benchmark",
            name="CRUD-RAG Agent ablation",
            description="Local-only public held-out Agent ablation",
            chunking_config=dict(retrieval_report["chunking"]),
            retrieval_config=_knowledge_base_retrieval_config(default_config),
        )
        for offset in range(0, len(documents), policy.max_documents_per_call):
            batch = documents[offset : offset + policy.max_documents_per_call]
            sandbox.import_documents(
                owner,
                run_id,
                base_alias="benchmark",
                documents=[
                    {
                        "externalId": item["documentId"],
                        "name": f"{item['documentId']}.txt",
                        "text": item["text"],
                        "mimeType": "text/plain",
                    }
                    for item in batch
                ],
            )
            _progress("import", imported=min(offset + len(batch), len(documents)), total=len(documents))
        import_status = sandbox.status(owner, run_id)
        if calibration_no_metal:
            try:
                dense_acceptance = _require_semantic_dense_runtime(
                    provider=provider_public,
                    status=import_status,
                    requested_backend=str(
                        embedding_environment["RAG_IME_KNOWLEDGE_DENSE_BACKEND"]
                    ),
                )
            except ValueError as exc:
                dense_acceptance = {
                    "accepted": False,
                    "calibrationOnly": True,
                    "reason": str(exc),
                }
        else:
            dense_acceptance = _require_semantic_dense_runtime(
                provider=provider_public,
                status=import_status,
                requested_backend=str(
                    embedding_environment["RAG_IME_KNOWLEDGE_DENSE_BACKEND"]
                ),
            )

        active_config_sha256 = default_config_sha256
        for lane in LANES:
            target_config = tuned_config if lane in {"tuned", "agentic"} else default_config
            target_hash = tuned_config_sha256 if lane in {"tuned", "agentic"} else default_config_sha256
            if active_config_sha256 != target_hash:
                base = sandbox.configure_base(
                    owner,
                    run_id,
                    base_alias="benchmark",
                    expected_revision=base["configRevision"],
                    retrieval_config=_knowledge_base_retrieval_config(target_config),
                )
                active_config_sha256 = target_hash
            lane_record = _run_lane(
                service,
                gateway=gateway,
                owner=owner,
                run_id=run_id,
                lane=lane,
                cases=evaluation_cases,
                retrieval_config=target_config,
                retrieval_config_sha256=target_hash,
                timeout_seconds=timeout_seconds,
                lane_attempts=lane_attempts,
            )
            lane_records.append(lane_record)
            _progress(
                "lane",
                lane=lane,
                terminal=lane_record["terminalEvent"],
                searchCalls=lane_record["score"]["searchCallCount"],
                agentMetrics=lane_record["score"]["agentMetrics"],
            )
        answer_judge = _run_answer_judge(
            service,
            cases=evaluation_cases,
            documents=documents,
            lane_records=lane_records,
            timeout_seconds=timeout_seconds,
            maximum_attempts=2,
        )
        if answer_judge.get("accepted") is not True:
            raise RuntimeError(
                "answer judge rejected its output: "
                + str(answer_judge.get("failure") or "unknown failure")
            )
        _apply_answer_judgments(lane_records, answer_judge["judgments"])
        for lane_record in lane_records:
            lane_record.pop("_assistantText", None)
        _progress(
            "answer_judge",
            accepted=answer_judge.get("accepted"),
            correctnessByLane=answer_judge.get("correctnessByLane"),
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if run_id:
            try:
                cleanup = sandbox.cleanup(owner, run_id, confirm_text=DELETE_CONFIRMATION)
            except Exception:
                cleanup_passed = False
            else:
                cleanup_passed = cleanup.get("deleted") is True
        if service is not None:
            service.close()
        if server is not None:
            server.close()
        sandbox.close()

    completed_at_ms = int(time.time() * 1_000)
    if failure or len(lane_records) != 4:
        completed_lane_evidence = []
        for lane_record in lane_records:
            projected = dict(lane_record)
            projected.pop("_assistantText", None)
            completed_lane_evidence.append(projected)
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "passed": False,
            "scoreEligible": False,
            "formalAcceptanceEligible": False,
            "localOnly": True,
            "uploaded": False,
            "startedAtMs": started_at_ms,
            "completedAtMs": completed_at_ms,
            "elapsedMs": completed_at_ms - started_at_ms,
            "failure": failure or "four Agent lanes did not complete",
            "completedLanes": [item["lane"] for item in lane_records],
            "completedLaneEvidence": completed_lane_evidence,
            "answerJudge": answer_judge,
            "calibration": {
                "enabled": calibration_no_metal,
                "formalAcceptanceEligible": False,
                "passed": False if calibration_no_metal else None,
                "purpose": (
                    "development-only Agent answer coverage audit under a no-Metal sandbox"
                    if calibration_no_metal
                    else ""
                ),
            },
            "development": {
                "enabled": development_only,
                "formalAcceptanceEligible": False,
                "underlyingHardGatesPassed": False if development_only else None,
                "purpose": (
                    "real-model replay of previously observed cases for prompt and orchestration calibration"
                    if development_only
                    else ""
                ),
            },
            "piRuntime": pi_runtime_identity,
            "cleanupPassed": cleanup_passed,
        }
        report["reportSha256"] = _sha256_json(report)
        return report

    case_ids = [str(item["queryId"]) for item in evaluation_cases]
    case_aliases = [str(item["evaluationCaseId"]) for item in evaluation_cases]
    permissions = {
        "executionMode": "read_only",
        "toolProfileVersion": "subagent-readonly-v1",
        "allowedOperations": ["search", "status"],
        "allowedAuxiliaryTools": ["agents"],
        "workspaceRoots": [],
    }
    conditions = {
        "model": "openai-codex/gpt-5.6-luna",
        "thinking": "max",
        "laneTimeoutSeconds": float(timeout_seconds),
        "datasetSplitSha256": _sha256_json(case_ids),
        "permissionSha256": _sha256_json(permissions),
        "denominator": len(case_ids),
        "benchmarkId": slice_manifest["benchmarkId"],
        "caseIdsSha256": _sha256_json(case_ids),
        "promptContractVersion": _PROMPT_CONTRACT_VERSION,
        "skillName": "rag-retrieval-optimization",
        "skillSha256": _file_sha256(_RAG_OPTIMIZATION_SKILL_PATH),
        "piRuntime": pi_runtime_identity,
        "toolTransport": server.transport if server is not None else "",
        "calibrationProfile": (
            "no-metal-hashing-rank-preserving-v1"
            if calibration_no_metal
            else (
                "development-replay-real-model-v1"
                if development_only
                else "none"
            )
        ),
        "citationReferencePolicy": {
            "scope": "benchmark-run-and-evaluation-case",
            "format": "K{positiveInteger}",
            "assignment": "first-observed-source-order",
            "resolution": "exact-only",
            "unknownReference": "hard-fail",
        },
        "runtimeContractSha256": _sha256_json(
            {
                str(path.relative_to(ROOT)): _file_sha256(path)
                for path in _RUNTIME_CONTRACT_PATHS
            }
        ),
        "runtimeRetryPolicy": {
            "maximumAttemptsPerLane": lane_attempts,
            "retryableCategory": "provider_transient_before_tool",
            "metricBasedSelection": False,
        },
        "agenticRetrievalPolicy": {
            "childCount": 1,
            "childWaveCount": 1,
            "maxParallelChildren": 1,
            "childCaseAssignment": "single-batch-no-tool-coverage-critic-v1",
            "childTemplate": "reviewer@1",
            "childBudget": agent_template("reviewer", "1").budget.to_payload(),
            "childTopK": 0,
            "parentFirstPassTopK": _PARENT_SEARCH_TOP_K,
            "parentSecondPassTopK": _PARENT_SEARCH_TOP_K,
            "maxSearchesPerCase": 2,
            "sequence": "parent-exact-search_then_critic_then_parent-supplemental-search",
            "synthesisCorrection": {
                "enabled": False,
                "maximumTurns": 0,
                "additionalSearches": 0,
                "trigger": "none_coverage_review_occurs_before_second_retrieval",
                "metricBasedSelection": False,
                "qrelAccess": False,
            },
        },
        "answerEvaluationPolicy": {
            "primaryTaskMetric": "answerJudgeCorrectnessRate",
            "rawCharacterMetricsDiagnosticOnly": True,
            "judgeModel": "openai-codex/gpt-5.6-luna",
            "judgeThinking": "max",
            "judgeContractVersion": _ANSWER_JUDGE_CONTRACT_VERSION,
            "anonymousCandidates": True,
            "referenceAnswerAccessAfterGeneration": True,
            "retrievalQrelAccess": False,
            "candidateCitedEvidenceAccessAfterGeneration": True,
            "judgeFeedbackToAgent": False,
            "metricBasedRetry": False,
            "formatRepair": {
                "maximumTurns": 1,
                "trigger": "schema-invalid-only",
                "judgmentFeedback": False,
            },
            "runtimeRetryPolicy": {
                "maximumAttempts": 2,
                "retryableTerminal": "turn_failed_before_judgment",
                "metricBasedSelection": False,
                "laneRerun": False,
            },
            "evidenceRetention": {
                "scope": "local-only-public-benchmark",
                "question": True,
                "referenceAnswer": True,
                "generatedAnswer": True,
                "candidateCitedEvidence": True,
                "uploaded": False,
            },
        },
    }
    reranker_evidence = _reranker_run_evidence(
        reranker,
        identity=reranker_identity,
    )
    knowledge_lanes: list[dict[str, object]] = []
    agent_lanes: list[dict[str, object]] = []
    for item in lane_records:
        score = item["score"]
        lane_config = (
            tuned_config
            if item["lane"] in {"tuned", "agentic"}
            else default_config
        )
        hard_gates = {
            "splitIntegrity": True,
            "scopeBoundary": item["scopeBoundary"],
            "citationResolution": score["hardEvidence"]["citationResolution"],
            "abstention": score["hardEvidence"]["abstention"],
            "crossSystemLeakage": item["crossSystemLeakage"],
            "terminalCompletion": item["terminalEvent"] == "turn_completed",
            "toolContract": item["toolContract"],
            "agenticPolicy": (
                score["hardEvidence"]["agenticLoopObserved"]
                and (
                    bool(item["features"].get("subagentPolicyPassed"))
                    if item["lane"] == "agentic"
                    else not bool(item["features"].get("subagents"))
                )
            ),
            "semanticIndex": dense_acceptance.get("accepted") is True,
            "independentReranker": (
                reranker_evidence["accepted"]
                if lane_config.get("rerankEnabled") is True
                else True
            ),
            "answerJudge": answer_judge.get("accepted") is True,
            "cleanup": cleanup_passed,
        }
        common = {
            "lane": item["lane"],
            "features": item["features"],
            "conditions": conditions,
            "retrievalConfigSha256": item["retrievalConfigSha256"],
            "costs": item["costs"],
            "hardGates": hard_gates,
        }
        knowledge_lanes.append({**common, "metrics": flat_retrieval_metrics(score)})
        agent_lanes.append({**common, "metrics": dict(score["agentMetrics"])})
        item["hardGates"] = hard_gates
    knowledge_ablation = build_ablation_report(
        metric_namespace="knowledge",
        lanes=knowledge_lanes,
        required_hard_gates=REQUIRED_HARD_GATES,
    )
    agent_ablation = build_ablation_report(
        metric_namespace="agent",
        lanes=agent_lanes,
        required_hard_gates=REQUIRED_HARD_GATES,
    )
    formal_accepted = knowledge_ablation["accepted"] and agent_ablation["accepted"]
    correctness_by_lane = answer_judge.get("correctnessByLane")
    correctness_by_lane = (
        correctness_by_lane if isinstance(correctness_by_lane, Mapping) else {}
    )
    calibration_passed = (
        calibration_no_metal
        and answer_judge.get("accepted") is True
        and float(correctness_by_lane.get("agentic") or 0.0) == 1.0
    )
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "passed": formal_accepted and not calibration_no_metal and not development_only,
        "formalAcceptanceEligible": not calibration_no_metal and not development_only,
        "localOnly": True,
        "uploaded": False,
        "providerDisclosure": "public CRUD-RAG-derived questions, documents, and Tool results only",
        "startedAtMs": started_at_ms,
        "completedAtMs": completed_at_ms,
        "elapsedMs": completed_at_ms - started_at_ms,
        "sourcePreparedSha256": _file_sha256(prepared_path),
        "sourceRetrievalReportSha256": _file_sha256(retrieval_report_path),
        "dataset": slice_manifest,
        "evaluation": {
            "caseCount": len(case_ids),
            "caseIds": case_ids,
            "caseAliases": case_aliases,
            "caseIdsSha256": _sha256_json(case_ids),
            "selectionSeed": agent_seed,
            "heldOutLabelsInPrompt": False,
            "safetyCaseId": SAFETY_CASE_ID,
            "developmentExclusion": development_exclusion,
        },
        "embedding": {
            **provider_public,
            "model": Path(str(provider_public.get("model") or "")).name,
            "acceptance": dense_acceptance,
        },
        "reranker": reranker_evidence,
        "defaultRetrievalConfig": default_config,
        "defaultRetrievalConfigSha256": default_config_sha256,
        "tunedRetrievalConfig": tuned_config,
        "tunedRetrievalConfigSha256": tuned_config_sha256,
        "conditions": conditions,
        "answerJudge": answer_judge,
        "lanes": lane_records,
        "knowledgeAblation": knowledge_ablation,
        "agentAblation": agent_ablation,
        "cleanupPassed": cleanup_passed,
        "calibration": {
            "enabled": calibration_no_metal,
            "formalAcceptanceEligible": not calibration_no_metal,
            "passed": calibration_passed if calibration_no_metal else None,
            "purpose": (
                "development-only Agent answer coverage audit under a no-Metal sandbox"
                if calibration_no_metal
                else ""
            ),
        },
        "development": {
            "enabled": development_only,
            "formalAcceptanceEligible": not development_only,
            "underlyingHardGatesPassed": formal_accepted if development_only else None,
            "purpose": (
                "real-model replay of previously observed cases for prompt and orchestration calibration"
                if development_only
                else ""
            ),
        },
        "failure": (
            "calibration-only profile is not eligible for formal acceptance"
            if calibration_no_metal
            else (
                "development-only profile is not eligible for formal acceptance"
                if development_only
                else ""
            )
        ),
    }
    report["reportSha256"] = _sha256_json(report)
    return report


def _preflight_failure_report(
    *,
    started_at_ms: int,
    prepared_path: Path,
    retrieval_report_path: Path,
    slice_manifest: Mapping[str, object],
    evaluation_cases: list[Mapping[str, object]],
    calibration_no_metal: bool,
    development_only: bool,
    embedding: Mapping[str, object],
    failure: str,
) -> dict[str, object]:
    """Persist a non-score receipt when semantic setup fails before sandbox allocation."""

    completed_at_ms = int(time.time() * 1_000)
    case_ids = [str(item.get("queryId") or "") for item in evaluation_cases]
    case_aliases = [str(item.get("evaluationCaseId") or "") for item in evaluation_cases]
    report: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "passed": False,
        "scoreEligible": False,
        "formalAcceptanceEligible": False,
        "localOnly": True,
        "uploaded": False,
        "providerDisclosure": "public CRUD-RAG-derived questions and redacted runtime receipts only",
        "startedAtMs": started_at_ms,
        "completedAtMs": completed_at_ms,
        "elapsedMs": max(0, completed_at_ms - started_at_ms),
        "sourcePreparedSha256": _file_sha256(prepared_path),
        "sourceRetrievalReportSha256": _file_sha256(retrieval_report_path),
        "dataset": dict(slice_manifest),
        "evaluation": {
            "caseCount": len(case_ids),
            "caseIds": case_ids,
            "caseAliases": case_aliases,
            "caseIdsSha256": _sha256_json(case_ids),
            "heldOutLabelsInPrompt": False,
        },
        "preflight": {
            "stage": "embedding_or_reranker_setup",
            "accepted": False,
            "failure": failure[:1_000],
            "failureSha256": hashlib.sha256(failure.encode("utf-8")).hexdigest(),
            "sandboxAllocated": False,
        },
        "embedding": dict(embedding),
        "lanes": [],
        "knowledgeAblation": {
            "accepted": False,
            "reason": "preflight failed before any lane ran",
        },
        "agentAblation": {
            "accepted": False,
            "reason": "preflight failed before any lane ran",
        },
        "cleanup": {
            "required": False,
            "passed": True,
            "reason": "no benchmark sandbox was allocated",
        },
        "cleanupPassed": True,
        "calibration": {
            "enabled": calibration_no_metal,
            "formalAcceptanceEligible": False,
            "passed": False if calibration_no_metal else None,
        },
        "development": {
            "enabled": development_only,
            "formalAcceptanceEligible": False,
            "underlyingHardGatesPassed": False if development_only else None,
        },
        "failure": failure[:1_000],
    }
    report["reportSha256"] = _sha256_json(report)
    return report


def _require_actual_metal_runtime() -> None:
    """Check a real MLX device operation before loading a native model in-process."""

    probe = (
        "import mlx.core as mx; "
        "x = mx.array([1.0]); mx.eval(x); "
        "print('metal-probe-ok', flush=True)"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"MLX Metal preflight could not run: {exc}") from exc
    if completed.returncode != 0 or "metal-probe-ok" not in completed.stdout:
        detail = (completed.stderr or completed.stdout or "no diagnostic").strip()
        raise RuntimeError(
            "MLX Metal preflight failed "
            f"(exit={completed.returncode}): {detail[:500]}"
        )


def _run_lane(
    service: AgentService,
    *,
    gateway: RagBenchmarkAgentGateway,
    owner: str,
    run_id: str,
    lane: str,
    cases: list[Mapping[str, object]],
    retrieval_config: Mapping[str, object],
    retrieval_config_sha256: str,
    timeout_seconds: float,
    lane_attempts: int,
) -> dict[str, Any]:
    attempts: list[dict[str, object]] = []
    result: dict[str, Any] | None = None
    for attempt_number in range(1, max(1, lane_attempts) + 1):
        result = _run_lane_once(
            service,
            gateway=gateway,
            owner=owner,
            run_id=run_id,
            lane=lane,
            cases=cases,
            retrieval_config=retrieval_config,
            retrieval_config_sha256=retrieval_config_sha256,
            timeout_seconds=timeout_seconds,
        )
        retryable = result["runtimeFailureCategory"] == "provider_transient_before_tool"
        attempts.append(
            {
                "attempt": attempt_number,
                "terminalEvent": result["terminalEvent"],
                "runtimeFailureCategory": result["runtimeFailureCategory"],
                "gatewayItemCount": int(result["gatewayLedger"].get("itemCount") or 0),
                "retryScheduled": retryable and attempt_number < lane_attempts,
            }
        )
        if not retryable or attempt_number >= lane_attempts:
            break
        _progress(
            "lane_retry",
            lane=lane,
            attempt=attempt_number,
            reason="provider_transient_before_tool",
        )
    assert result is not None
    result["runtimeAttempts"] = attempts
    result["runtimeRetryCount"] = len(attempts) - 1
    return result


def _run_lane_once(
    service: AgentService,
    *,
    gateway: RagBenchmarkAgentGateway,
    owner: str,
    run_id: str,
    lane: str,
    cases: list[Mapping[str, object]],
    retrieval_config: Mapping[str, object],
    retrieval_config_sha256: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    include_skill = LANE_FEATURES[lane]["skill"]
    max_searches = 2 if lane == "agentic" else 1
    session = service.create_session(
        {
            "title": f"RAG Agent ablation: {lane}",
            "mode": "assistant",
            "roleId": "companion-firstlight-v1",
            "roleVersion": "1",
            "toolProfileVersion": "subagent-readonly-v1",
        }
    )["session"]
    session_id = str(session["id"])
    service.update_session(
        session_id,
        {
            "mode": "assistant",
            "executionMode": "read_only",
            "toolProfileVersion": "subagent-readonly-v1",
            "projectContextEnabled": False,
            "piSkillsEnabled": include_skill,
            "codexSkillsEnabled": False,
            "workspaceRoots": [],
        },
    )
    binding = gateway.bind_session(
        session_id,
        allowed_operations=("search", "status"),
        sandbox_owner_id=owner,
        sandbox_run_id=run_id,
        allowed_base_tools=("agents",),
    )
    ensure: dict[str, object] = {}
    prompt_receipt: dict[str, object] = {}
    events: list[dict[str, object]] = []
    message_snapshot: dict[str, object] = {}
    terminal = ""
    error = ""
    correction_case_ids: list[str] = []
    correction_turn_count = 0
    started = time.perf_counter()
    try:
        ensure = service.ensure_runtime({"sessionId": session_id})
        if not _is_luna_max(ensure):
            raise RuntimeError("lane did not open openai-codex/gpt-5.6-luna at max")
        prompt_receipt = service.prompt(
            session_id,
            {
                "message": _lane_prompt(
                    lane=lane,
                    run_id=run_id,
                    cases=cases,
                    retrieval_config=retrieval_config,
                ),
                "clientMessageId": f"rag-ablation:{lane}:{int(time.time() * 1_000)}",
            },
        )
        events, terminal = _wait_for_terminal(
            service,
            session_id=session_id,
            turn_id=str(prompt_receipt.get("turnId") or ""),
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    try:
        snapshot = service.messages(session_id)
    except Exception:
        snapshot = {}
    if isinstance(snapshot, Mapping):
        message_snapshot = dict(snapshot)
        events = _merge_event_evidence(events, snapshot.get("liveEvents"))
    elapsed_ms = round((time.perf_counter() - started) * 1_000, 3)
    ledger = gateway.lineage_ledger(session_id)
    lineage_session_ids = list(ledger.get("sessionIds") or [session_id])
    delegation_batches = service.delegation.store.list_batches(
        parent_session_id=session_id,
        limit=10,
    )
    child_runs = [
        dict(run)
        for batch in delegation_batches
        if isinstance(batch, Mapping)
        for run in batch.get("runs") or []
        if isinstance(run, Mapping)
    ]
    child_session_ids = {
        str(run.get("childSessionId") or "")
        for run in child_runs
        if str(run.get("childSessionId") or "")
    }
    child_searches = [
        item
        for item in ledger.get("items") or []
        if isinstance(item, Mapping)
        and str(item.get("sessionId") or "") in child_session_ids
        and item.get("operation") == "search"
        and item.get("ok") is True
    ]
    child_search_case_ids = {
        str(item.get("args", {}).get("evaluationCaseId") or "")
        for item in child_searches
        if isinstance(item.get("args"), Mapping)
    }
    coverage_critic_observed = _coverage_critic_completed(
        child_runs=child_runs,
        child_searches=child_searches,
    )
    search_parameter_policy = _search_parameter_policy_passes(
        ledger,
        lane=lane,
        retrieval_config=retrieval_config,
    )
    parent_query_policy = (
        _agentic_parent_query_policy_passes(
            ledger,
            parent_session_id=session_id,
            cases=cases,
        )
        if lane == "agentic"
        else True
    )
    search_parameter_policy = search_parameter_policy and parent_query_policy
    agents_tool_receipts = _agents_tool_receipts(events)
    assistant_text = _last_assistant_text(events) or _last_assistant_snapshot_text(
        message_snapshot.get("items")
    )
    score = score_agent_lane(
        lane=lane,
        cases=cases,
        ledger=ledger,
        assistant_text=assistant_text,
        max_searches_per_case=max_searches,
    )
    started_tools = _started_tool_names(events, message_snapshot.get("items"))
    required_tools = {"tool_load"}
    if include_skill:
        required_tools.add("skill_load")
    if lane == "agentic":
        required_tools.add("agents")
    skill_policy = (
        "skill_load" in started_tools
        if include_skill
        else "skill_load" not in started_tools
    )
    authorization_ok = all(
        isinstance(item, Mapping)
        and item.get("authorizationSource") in {
            "ephemeral_session_binding",
            "runtime_load_receipt",
        }
        and item.get("sandboxOwnerSha256") == binding["sandboxOwnerSha256"]
        for item in ledger.get("items") or []
    )
    token_usage = _token_usage(events)
    child_tokens = sum(
        int((run.get("usage") or {}).get("totalTokens") or 0)
        for run in child_runs
        if isinstance(run.get("usage"), Mapping)
    )
    child_tool_calls = sum(
        int((run.get("usage") or {}).get("toolCount") or 0)
        for run in child_runs
        if isinstance(run.get("usage"), Mapping)
    )
    expected_child_count = 1
    expected_delegation_waves = 1
    subagents_completed = len(child_runs) == expected_child_count and all(
        str(run.get("state") or "") == "completed" for run in child_runs
    )
    delegation_receipts_passed = (
        (
            len(agents_tool_receipts) == expected_delegation_waves
            and all(
                receipt.get("operation") == "delegate"
                and receipt.get("finished") is True
                and receipt.get("isError") is False
                for receipt in agents_tool_receipts
            )
        )
        if lane == "agentic"
        else not agents_tool_receipts
    )
    delegation_policy = (
        "agents" in started_tools
        and subagents_completed
        and coverage_critic_observed
        and delegation_receipts_passed
        if lane == "agentic"
        else "agents" not in started_tools and not child_runs
    )
    rag_invoked = int(ledger.get("itemCount") or 0) > 0
    runtime_failure_category = _runtime_failure_category(
        terminal=terminal,
        error=error,
        events=events,
        ledger=ledger,
    )
    features: dict[str, object] = {
        **LANE_FEATURES[lane],
        "maxRetrievalRounds": max_searches,
        "subagents": bool(child_runs),
        "subagentCount": len(child_runs),
        "childCaseAssignment": (
            "single-batch-no-tool-coverage-critic-v1"
            if lane == "agentic"
            else "none"
        ),
        "delegationWaveCount": len(agents_tool_receipts),
        "delegationReceiptsPassed": delegation_receipts_passed,
        "coverageCriticObserved": coverage_critic_observed,
        "childRetrievalObserved": bool(child_searches),
        "childSearchCalls": len(child_searches),
        "childSearchCaseIds": sorted(child_search_case_ids),
        "subagentPolicyPassed": delegation_policy,
        "searchParameterPolicyPassed": search_parameter_policy,
        "parentQueryPolicyPassed": parent_query_policy,
        "synthesisCorrectionTriggered": correction_turn_count == 1,
        "synthesisCorrectionTurnCount": correction_turn_count,
        "synthesisCorrectionCaseCount": len(correction_case_ids),
        "synthesisCorrectionCaseIdsSha256": _sha256_json(
            sorted(correction_case_ids)
        ),
        "independentReranker": retrieval_config.get("rerankEnabled") is True,
        "rerankCandidateDepth": (
            int(retrieval_config.get("rerankCandidateDepth") or 0)
            if retrieval_config.get("rerankEnabled") is True
            else 0
        ),
    }
    unbound_session_ids = gateway.unbind_lineage(session_id)
    binding_cleanup = set(unbound_session_ids) == set(lineage_session_ids)
    return {
        "lane": lane,
        "features": features,
        "retrievalConfigSha256": retrieval_config_sha256,
        "terminalEvent": terminal,
        "promptAccepted": bool(prompt_receipt.get("turnId")),
        "model": _public_model_state(ensure),
        "binding": binding,
        "startedTools": started_tools,
        "score": score,
        "_assistantText": assistant_text,
        "costs": {
            "latencyMs": elapsed_ms,
            "tokens": float(token_usage["totalTokens"] + child_tokens),
            "toolCalls": float(
                max(
                    len(started_tools) + child_tool_calls,
                    int(ledger.get("itemCount") or 0)
                    + sum(name in {"skill_load", "tool_load"} for name in started_tools),
                )
            ),
        },
        "subagentEvidence": [
            {
                "sessionSha256": hashlib.sha256(
                    str(run.get("childSessionId") or "").encode("utf-8")
                ).hexdigest(),
                "runSha256": hashlib.sha256(
                    str(run.get("id") or "").encode("utf-8")
                ).hexdigest(),
                "state": str(run.get("state") or ""),
                "usage": dict(run.get("usage") or {}),
                "error": str(run.get("error") or "")[:500],
                "errorSha256": hashlib.sha256(
                    str(run.get("error") or "").encode("utf-8")
                ).hexdigest(),
                "retrievalObserved": (
                    str(run.get("childSessionId") or "") in child_session_ids
                    and any(
                        str(item.get("sessionId") or "")
                        == str(run.get("childSessionId") or "")
                        for item in child_searches
                    )
                ),
                "searchCalls": sum(
                    str(item.get("sessionId") or "")
                    == str(run.get("childSessionId") or "")
                    for item in child_searches
                ),
            }
            for run in child_runs
        ],
        "agentsToolReceipts": agents_tool_receipts,
        "bindingCleanup": binding_cleanup,
        "scopeBoundary": authorization_ok,
        "crossSystemLeakage": "memory" not in started_tools,
        "toolContract": (
            not error
            and required_tools.issubset(set(started_tools))
            and rag_invoked
            and skill_policy
            and delegation_policy
            and search_parameter_policy
            and binding_cleanup
            and score["hardEvidence"]["parameterBounded"]
            and score["failedToolItemCount"] == 0
        ),
        "gatewayLedger": ledger,
        "runtimeFailureCategory": runtime_failure_category,
        "error": error,
    }


def _run_answer_judge(
    service: AgentService,
    *,
    cases: list[Mapping[str, object]],
    documents: list[Mapping[str, object]],
    lane_records: list[Mapping[str, object]],
    timeout_seconds: float,
    maximum_attempts: int = 2,
) -> dict[str, object]:
    """Retry only terminal judge infrastructure failure, never a judgment score."""

    attempts: list[dict[str, object]] = []
    bounded_attempts = max(1, min(2, int(maximum_attempts)))
    for attempt in range(1, bounded_attempts + 1):
        try:
            result = _run_answer_judge_once(
                service,
                cases=cases,
                documents=documents,
                lane_records=lane_records,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            failure = f"{type(exc).__name__}: {exc}"
            retryable = _answer_judge_failure_is_retryable(failure)
            attempts.append(
                {
                    "attempt": attempt,
                    "outcome": "terminal_failure",
                    "retryable": retryable,
                    "failure": failure[:500],
                    "failureSha256": hashlib.sha256(
                        failure.encode("utf-8")
                    ).hexdigest(),
                }
            )
            if retryable and attempt < bounded_attempts:
                continue
            return {
                "schemaVersion": "rag-ime.rag-answer-judge.v4",
                "accepted": False,
                "failure": failure,
                "runtimeAttempts": attempts,
                "runtimeRetryCount": len(attempts) - 1,
                "correctnessByLane": {},
                "judgments": [],
            }
        attempts.append(
            {
                "attempt": attempt,
                "outcome": (
                    "accepted" if result.get("accepted") is True else "rejected"
                ),
                "retryable": False,
                "failure": str(result.get("failure") or "")[:500],
                "failureSha256": hashlib.sha256(
                    str(result.get("failure") or "").encode("utf-8")
                ).hexdigest(),
            }
        )
        result["runtimeAttempts"] = attempts
        result["runtimeRetryCount"] = len(attempts) - 1
        return result
    raise AssertionError("bounded answer judge attempts exhausted without a result")


def _answer_judge_failure_is_retryable(failure: object) -> bool:
    normalized = str(failure or "").lower()
    return "answer judge ended with turn_failed" in normalized


def _run_answer_judge_once(
    service: AgentService,
    *,
    cases: list[Mapping[str, object]],
    documents: list[Mapping[str, object]],
    lane_records: list[Mapping[str, object]],
    timeout_seconds: float,
) -> dict[str, object]:
    case_ids = [
        str(item.get("evaluationCaseId") or item.get("queryId") or "")
        for item in cases
    ]
    ordered_lanes = sorted(
        (str(item.get("lane") or "") for item in lane_records),
        key=lambda lane: _sha256_json(
            {
                "contract": _ANSWER_JUDGE_CONTRACT_VERSION,
                "caseIds": case_ids,
                "lane": lane,
            }
        ),
    )
    candidate_ids = {
        lane: f"C{index}"
        for index, lane in enumerate(ordered_lanes, start=1)
    }
    assistant_cases = {
        str(record.get("lane") or ""): _assistant_case_payload(
            str(record.get("_assistantText") or "")
        )
        for record in lane_records
    }
    document_text_by_id = {
        str(document.get("documentId") or ""): str(document.get("text") or "")
        for document in documents
        if str(document.get("documentId") or "").strip()
    }
    citations_by_lane_case: dict[tuple[str, str], list[str]] = {}
    for record in lane_records:
        lane = str(record.get("lane") or "")
        score = record.get("score")
        answer_cases = score.get("answerCases") if isinstance(score, Mapping) else None
        if not isinstance(answer_cases, list):
            raise RuntimeError("lane answer evidence is missing before answer judgment")
        for answer_case in answer_cases:
            if not isinstance(answer_case, Mapping):
                raise RuntimeError("lane answer evidence contains a non-object case")
            case_id = str(answer_case.get("evaluationCaseId") or "")
            raw_citations = answer_case.get("citations")
            if not isinstance(raw_citations, list):
                raise RuntimeError("lane answer evidence has invalid citations")
            citation_ids = [str(item).strip() for item in raw_citations]
            if (
                len(set(citation_ids)) != len(citation_ids)
                or any(not item or item not in document_text_by_id for item in citation_ids)
            ):
                raise RuntimeError("lane answer evidence cites an unknown document")
            citations_by_lane_case[(lane, case_id)] = citation_ids
    judge_cases: list[dict[str, object]] = []
    for case in cases:
        case_id = str(case.get("evaluationCaseId") or case.get("queryId") or "")
        cited_document_ids = {
            document_id
            for lane in ordered_lanes
            for document_id in citations_by_lane_case.get((lane, case_id), [])
        }
        ordered_document_ids = sorted(
            cited_document_ids,
            key=lambda document_id: _sha256_json(
                {
                    "contract": _ANSWER_JUDGE_CONTRACT_VERSION,
                    "caseId": case_id,
                    "documentId": document_id,
                }
            ),
        )
        evidence_ids = {
            document_id: f"E{index}"
            for index, document_id in enumerate(ordered_document_ids, start=1)
        }
        candidates: list[dict[str, object]] = []
        for lane in ordered_lanes:
            answer = assistant_cases.get(lane, {}).get(case_id, {})
            candidates.append(
                {
                    "candidateId": candidate_ids[lane],
                    "answer": str(answer.get("answer") or ""),
                    "abstained": answer.get("abstained") is True,
                    "evidenceIds": [
                        evidence_ids[document_id]
                        for document_id in citations_by_lane_case.get((lane, case_id), [])
                    ],
                }
            )
        judge_cases.append(
            {
                "caseId": case_id,
                "question": str(case.get("query") or case.get("question") or ""),
                "referenceAnswer": str(case.get("answer") or ""),
                "evidenceDocuments": [
                    {
                        "evidenceId": evidence_ids[document_id],
                        "text": document_text_by_id[document_id],
                    }
                    for document_id in ordered_document_ids
                ],
                "candidates": candidates,
            }
        )
    prompt = _answer_judge_prompt(judge_cases)
    session = service.create_session(
        {
            "title": "CRUD-RAG anonymous answer correctness judge",
            "mode": "assistant",
            "roleId": "companion-firstlight-v1",
            "roleVersion": "1",
            "toolProfileVersion": "subagent-readonly-v1",
        }
    )["session"]
    session_id = str(session["id"])
    service.update_session(
        session_id,
        {
            "mode": "assistant",
            "executionMode": "read_only",
            "toolProfileVersion": "subagent-readonly-v1",
            "projectContextEnabled": False,
            "piSkillsEnabled": False,
            "codexSkillsEnabled": False,
            "workspaceRoots": [],
        },
    )
    started = time.perf_counter()
    ensure = service.ensure_runtime({"sessionId": session_id})
    if not _is_luna_max(ensure):
        raise RuntimeError("answer judge did not open openai-codex/gpt-5.6-luna at max")
    receipt = service.prompt(
        session_id,
        {
            "message": prompt,
            "clientMessageId": f"rag-answer-judge:{int(time.time() * 1_000)}",
        },
    )
    events, terminal = _wait_for_terminal(
        service,
        session_id=session_id,
        turn_id=str(receipt.get("turnId") or ""),
        timeout_seconds=timeout_seconds,
    )
    snapshot = service.messages(session_id)
    if isinstance(snapshot, Mapping):
        events = _merge_event_evidence(events, snapshot.get("liveEvents"))
        snapshot_items = snapshot.get("items")
    else:
        snapshot_items = None
    if terminal != "turn_completed":
        raise RuntimeError(f"answer judge ended with {terminal or 'no terminal event'}")
    started_tools = _started_tool_names(events, snapshot_items)
    if started_tools:
        raise RuntimeError("answer judge invoked tools despite the no-tool contract")
    assistant_text = _last_assistant_text(events) or _last_assistant_snapshot_text(
        snapshot_items
    )
    assistant_outputs = [assistant_text]
    format_repair_turn_count = 0
    expected_pairs = {
        (case_id, candidate_id)
        for case_id in case_ids
        for candidate_id in candidate_ids.values()
    }
    parse_failure = ""
    try:
        case_rubrics = _parse_answer_judge_rubrics(
            assistant_text,
            expected_case_ids=set(case_ids),
        )
        anonymous = _parse_answer_judgments(
            assistant_text,
            expected_pairs=expected_pairs,
        )
    except RuntimeError as exc:
        parse_failure = f"{type(exc).__name__}: {exc}"
        repair_receipt = service.prompt(
            session_id,
            {
                "message": _answer_judge_format_repair_prompt(
                    expected_pairs=expected_pairs,
                ),
                "clientMessageId": (
                    f"rag-answer-judge:format-repair:{int(time.time() * 1_000)}"
                ),
            },
        )
        repair_events, terminal = _wait_for_terminal(
            service,
            session_id=session_id,
            turn_id=str(repair_receipt.get("turnId") or ""),
            timeout_seconds=timeout_seconds,
        )
        events = _merge_event_evidence(events, repair_events)
        format_repair_turn_count = 1
        if terminal != "turn_completed":
            parse_failure += f"; format repair ended with {terminal or 'no terminal event'}"
        elif _started_tool_names(repair_events, None):
            parse_failure += "; format repair invoked a tool"
        else:
            repaired_text = _last_assistant_text(repair_events)
            if not repaired_text:
                repair_snapshot = service.messages(session_id)
                repaired_items = (
                    repair_snapshot.get("items")
                    if isinstance(repair_snapshot, Mapping)
                    else None
                )
                repaired_text = _last_assistant_snapshot_text(repaired_items)
            assistant_outputs.append(repaired_text)
            assistant_text = repaired_text
            try:
                case_rubrics = _parse_answer_judge_rubrics(
                    assistant_text,
                    expected_case_ids=set(case_ids),
                )
                anonymous = _parse_answer_judgments(
                    assistant_text,
                    expected_pairs=expected_pairs,
                )
                parse_failure = ""
            except RuntimeError as exc:
                parse_failure += f"; {type(exc).__name__}: {exc}"
    if parse_failure:
        usage = _token_usage(events)
        return {
            "schemaVersion": "rag-ime.rag-answer-judge.v4",
            "accepted": False,
            "failure": parse_failure,
            "contractVersion": _ANSWER_JUDGE_CONTRACT_VERSION,
            "model": _public_model_state(ensure),
            "referenceAnswerAccessAfterGeneration": True,
            "retrievalQrelAccess": False,
            "candidateCitedEvidenceAccessAfterGeneration": True,
            "judgeFeedbackToAgent": False,
            "anonymousCandidates": True,
            "candidateMapping": [
                {"candidateId": candidate_ids[lane], "lane": lane}
                for lane in sorted(candidate_ids)
            ],
            "evidenceRetention": {
                "scope": "local-only-public-benchmark",
                "question": True,
                "referenceAnswer": True,
                "generatedAnswer": True,
                "candidateCitedEvidence": True,
                "judgeRawOutputs": True,
                "uploaded": False,
            },
            "evidenceCases": judge_cases,
            "rubricSha256": hashlib.sha256(
                _ANSWER_JUDGE_RUBRIC.encode("utf-8")
            ).hexdigest(),
            "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "promptChars": len(prompt),
            "assistantOutputs": assistant_outputs,
            "assistantOutputSha256s": [
                hashlib.sha256(item.encode("utf-8")).hexdigest()
                for item in assistant_outputs
            ],
            "terminalEvent": terminal,
            "toolCalls": 0,
            "formatRepairTurnCount": format_repair_turn_count,
            "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
            "tokens": int(usage["totalTokens"]),
            "correctnessByLane": {},
            "judgments": [],
        }
    lane_by_candidate = {
        candidate_id: lane
        for lane, candidate_id in candidate_ids.items()
    }
    references = {
        str(case.get("evaluationCaseId") or case.get("queryId") or ""): str(
            case.get("answer") or ""
        )
        for case in cases
    }
    answer_hashes = {
        (str(record.get("lane") or ""), case_id): hashlib.sha256(
            str(assistant_cases.get(str(record.get("lane") or ""), {}).get(case_id, {}).get("answer") or "").encode(
                "utf-8"
            )
        ).hexdigest()
        for record in lane_records
        for case_id in case_ids
    }
    judgments = [
        {
            "lane": lane_by_candidate[str(item["candidateId"])],
            "candidateId": str(item["candidateId"]),
            "evaluationCaseId": str(item["caseId"]),
            "correct": item["correct"] is True,
            "reasonCode": str(item["reasonCode"]),
            "coveredFactIds": list(item["coveredFactIds"]),
            "hasContradiction": item["hasContradiction"] is True,
            "hasUnsupportedMaterial": item["hasUnsupportedMaterial"] is True,
            "answerSha256": answer_hashes[
                (
                    lane_by_candidate[str(item["candidateId"])],
                    str(item["caseId"]),
                )
            ],
            "referenceAnswerSha256": hashlib.sha256(
                references[str(item["caseId"])].encode("utf-8")
            ).hexdigest(),
        }
        for item in anonymous
    ]
    correctness_by_lane = {
        lane: sum(
            item["correct"] is True
            for item in judgments
            if item["lane"] == lane
        )
        / max(1, len(case_ids))
        for lane in LANES
    }
    usage = _token_usage(events)
    return {
        "schemaVersion": "rag-ime.rag-answer-judge.v4",
        "accepted": True,
        "contractVersion": _ANSWER_JUDGE_CONTRACT_VERSION,
        "model": _public_model_state(ensure),
        "referenceAnswerAccessAfterGeneration": True,
        "retrievalQrelAccess": False,
        "candidateCitedEvidenceAccessAfterGeneration": True,
        "judgeFeedbackToAgent": False,
        "anonymousCandidates": True,
        "candidateMapping": [
            {"candidateId": candidate_ids[lane], "lane": lane}
            for lane in sorted(candidate_ids)
        ],
        "evidenceRetention": {
            "scope": "local-only-public-benchmark",
            "question": True,
            "referenceAnswer": True,
            "generatedAnswer": True,
            "candidateCitedEvidence": True,
            "judgeRawOutputs": True,
            "uploaded": False,
        },
        "evidenceCases": judge_cases,
        "caseRubrics": case_rubrics,
        "rubricSha256": hashlib.sha256(
            _ANSWER_JUDGE_RUBRIC.encode("utf-8")
        ).hexdigest(),
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "promptChars": len(prompt),
        "assistantOutputSha256": hashlib.sha256(
            assistant_text.encode("utf-8")
        ).hexdigest(),
        "assistantOutputs": assistant_outputs,
        "assistantOutputSha256s": [
            hashlib.sha256(item.encode("utf-8")).hexdigest()
            for item in assistant_outputs
        ],
        "terminalEvent": terminal,
        "toolCalls": 0,
        "formatRepairTurnCount": format_repair_turn_count,
        "latencyMs": round((time.perf_counter() - started) * 1_000, 3),
        "tokens": int(usage["totalTokens"]),
        "correctnessByLane": correctness_by_lane,
        "judgments": judgments,
    }


def _answer_judge_prompt(cases: list[Mapping[str, object]]) -> str:
    return (
        "You are an isolated answer-correctness evaluator. You run after generation and must not call tools. "
        "Candidate IDs are anonymous; never infer systems or prefer a style. Rubric="
        + _ANSWER_JUDGE_RUBRIC
        + " Return only one JSON object: "
        '{"caseRubrics":[{"caseId":"case-01","requiredFacts":['
        '{"factId":"F1","description":"the explicitly requested fact"}]}],'
        '"judgments":[{"caseId":"case-01","candidateId":"C1",'
        '"coveredFactIds":["F1"],"hasContradiction":false,'
        '"hasUnsupportedMaterial":false,"correct":true,"reasonCode":"correct"}]}. '
        "Use 1-12 short required facts per case. coveredFactIds must refer only to that case's "
        "requiredFacts. correct is true exactly when every required fact is covered and there is "
        "no contradiction or material claim unsupported by the candidate's own evidenceIds. "
        "Evidence documents not named by that candidate are unavailable to it. The reference "
        "answer is not exhaustive evidence. An abstention cannot be correct. "
        "reasonCode must be one of correct, incomplete, wrong, abstained, unsupported. "
        "Return exactly one judgment for every candidate in every case. Cases="
        + json.dumps(cases, ensure_ascii=False, separators=(",", ":"))
    )


def _answer_judge_format_repair_prompt(
    *,
    expected_pairs: set[tuple[str, str]],
) -> str:
    return (
        "Your previous answer failed only the machine-readable schema contract. Do not call tools, "
        "do not ask questions, and do not use any score or feedback about which candidates should pass. "
        "Re-emit your existing judgment as exactly one JSON object with top-level caseRubrics and "
        "judgments arrays, no Markdown or commentary. Preserve the same required facts and decisions. "
        "Each judgment must contain caseId, candidateId, coveredFactIds, hasContradiction, "
        "hasUnsupportedMaterial, correct, and reasonCode. Return exactly these case/candidate pairs="
        + json.dumps(
            [
                {"caseId": case_id, "candidateId": candidate_id}
                for case_id, candidate_id in sorted(expected_pairs)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _decode_answer_judge_payload(text: str) -> Mapping[str, object]:
    decoder = json.JSONDecoder()
    normalized = str(text or "")
    for index, character in enumerate(normalized):
        if character != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(normalized[index:])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, Mapping)
            and isinstance(candidate.get("caseRubrics"), list)
            and isinstance(candidate.get("judgments"), list)
        ):
            return candidate
    raise RuntimeError("answer judge output is not a fact-rubric judgments JSON object")


def _parse_answer_judge_rubrics(
    text: str,
    *,
    expected_case_ids: set[str],
) -> list[dict[str, object]]:
    value = _decode_answer_judge_payload(text)
    rubrics: list[dict[str, object]] = []
    seen_cases: set[str] = set()
    for raw in value["caseRubrics"]:
        if not isinstance(raw, Mapping):
            raise RuntimeError("answer judge emitted a non-object case rubric")
        case_id = str(raw.get("caseId") or "").strip()
        facts = raw.get("requiredFacts")
        if case_id not in expected_case_ids or case_id in seen_cases:
            raise RuntimeError("answer judge emitted an unexpected or duplicate case rubric")
        if not isinstance(facts, list) or not 1 <= len(facts) <= 12:
            raise RuntimeError("answer judge must emit 1-12 required facts per case")
        normalized_facts: list[dict[str, str]] = []
        fact_ids: set[str] = set()
        for fact in facts:
            if not isinstance(fact, Mapping):
                raise RuntimeError("answer judge emitted a non-object required fact")
            fact_id = str(fact.get("factId") or "").strip()
            description = str(fact.get("description") or "").strip()
            if (
                not fact_id
                or len(fact_id) > 32
                or fact_id in fact_ids
                or not description
                or len(description) > 300
            ):
                raise RuntimeError("answer judge emitted an invalid required fact")
            fact_ids.add(fact_id)
            normalized_facts.append(
                {"factId": fact_id, "description": description}
            )
        seen_cases.add(case_id)
        rubrics.append(
            {"caseId": case_id, "requiredFacts": normalized_facts}
        )
    if seen_cases != expected_case_ids:
        raise RuntimeError("answer judge omitted one or more case rubrics")
    return sorted(rubrics, key=lambda item: str(item["caseId"]))


def _parse_answer_judgments(
    text: str,
    *,
    expected_pairs: set[tuple[str, str]],
) -> list[dict[str, object]]:
    value = _decode_answer_judge_payload(text)
    case_ids = {case_id for case_id, _candidate_id in expected_pairs}
    rubrics = _parse_answer_judge_rubrics(
        text,
        expected_case_ids=case_ids,
    )
    required_by_case = {
        str(rubric["caseId"]): {
            str(fact["factId"])
            for fact in rubric["requiredFacts"]
            if isinstance(fact, Mapping)
        }
        for rubric in rubrics
    }
    judgments: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw in value["judgments"]:
        if not isinstance(raw, Mapping):
            raise RuntimeError("answer judge emitted a non-object judgment")
        pair = (
            str(raw.get("caseId") or "").strip(),
            str(raw.get("candidateId") or "").strip(),
        )
        if pair not in expected_pairs or pair in seen:
            raise RuntimeError("answer judge emitted an unexpected or duplicate candidate")
        correct = raw.get("correct")
        reason = str(raw.get("reasonCode") or "").strip()
        covered_raw = raw.get("coveredFactIds")
        contradiction = raw.get("hasContradiction")
        unsupported = raw.get("hasUnsupportedMaterial")
        if (
            not isinstance(correct, bool)
            or reason not in _ANSWER_JUDGE_REASON_CODES
            or not isinstance(covered_raw, list)
            or not isinstance(contradiction, bool)
            or not isinstance(unsupported, bool)
        ):
            raise RuntimeError("answer judge emitted an invalid correctness judgment")
        covered = [str(item).strip() for item in covered_raw]
        covered_set = set(covered)
        required = required_by_case[pair[0]]
        if (
            len(covered_set) != len(covered)
            or not covered_set.issubset(required)
        ):
            raise RuntimeError("answer judge emitted invalid covered fact IDs")
        complete = covered_set == required
        expected_correct = complete and not contradiction and not unsupported
        if correct is not expected_correct:
            raise RuntimeError("answer judge correctness and reasonCode disagree")
        if correct and reason != "correct":
            raise RuntimeError("answer judge correctness and reasonCode disagree")
        if not correct and reason == "correct":
            raise RuntimeError("answer judge correctness and reasonCode disagree")
        if reason == "incomplete" and (complete or contradiction or unsupported):
            raise RuntimeError("answer judge incomplete reason is inconsistent")
        if reason == "wrong" and not contradiction:
            raise RuntimeError("answer judge wrong reason lacks a contradiction")
        if reason == "unsupported" and not unsupported:
            raise RuntimeError("answer judge unsupported reason lacks unsupported material")
        seen.add(pair)
        judgments.append(
            {
                "caseId": pair[0],
                "candidateId": pair[1],
                "coveredFactIds": covered,
                "hasContradiction": contradiction,
                "hasUnsupportedMaterial": unsupported,
                "correct": correct,
                "reasonCode": reason,
            }
        )
    if seen != expected_pairs:
        raise RuntimeError("answer judge omitted one or more candidates")
    return sorted(
        judgments,
        key=lambda item: (str(item["caseId"]), str(item["candidateId"])),
    )


def _apply_answer_judgments(
    lane_records: list[dict[str, Any]],
    judgments: object,
) -> None:
    if not isinstance(judgments, list):
        raise RuntimeError("answer judge evidence is missing judgments")
    lookup = {
        (str(item.get("lane") or ""), str(item.get("evaluationCaseId") or "")): item
        for item in judgments
        if isinstance(item, Mapping)
    }
    for lane_record in lane_records:
        lane = str(lane_record.get("lane") or "")
        score = lane_record.get("score")
        if not isinstance(score, dict):
            raise RuntimeError("lane score is missing before answer judgment")
        answer_cases = score.get("answerCases")
        metrics = score.get("agentMetrics")
        if not isinstance(answer_cases, list) or not isinstance(metrics, dict):
            raise RuntimeError("lane answer metrics are incomplete before answer judgment")
        char_success_count = 0
        judged_success_count = 0
        agent_success_count = 0
        for answer_case in answer_cases:
            if not isinstance(answer_case, dict):
                raise RuntimeError("lane answer case is invalid")
            case_id = str(answer_case.get("evaluationCaseId") or "")
            judgment = lookup.get((lane, case_id))
            if not isinstance(judgment, Mapping):
                raise RuntimeError("answer judge omitted a lane case")
            char_success = answer_case.get("answerSuccess") is True
            correct = judgment.get("correct") is True
            char_success_count += int(char_success)
            judged_success_count += int(correct)
            agent_success = (
                answer_case.get("toolSuccess") is True
                and answer_case.get("citationSuccess") is True
                and correct
            )
            agent_success_count += int(agent_success)
            answer_case["answerCharF1Success"] = char_success
            answer_case["answerJudgeCorrect"] = correct
            answer_case["answerJudgeReasonCode"] = str(
                judgment.get("reasonCode") or ""
            )
            answer_case["answerSuccess"] = correct
            answer_case["agentSuccess"] = agent_success
        denominator = max(1, len(answer_cases))
        metrics["answerCharF1SuccessRate"] = char_success_count / denominator
        metrics["answerJudgeCorrectnessRate"] = judged_success_count / denominator
        metrics["answerSuccessRate"] = judged_success_count / denominator
        metrics["agentSuccessRate"] = agent_success_count / denominator


def _coverage_critic_completed(
    *,
    child_runs: list[Mapping[str, object]],
    child_searches: list[Mapping[str, object]],
) -> bool:
    """Require one completed evidence critic that did not retrieve independently."""

    return (
        len(child_runs) == 1
        and str(child_runs[0].get("state") or "") == "completed"
        and not child_searches
    )


def _lane_prompt(
    *,
    lane: str,
    run_id: str,
    cases: list[Mapping[str, object]],
    retrieval_config: Mapping[str, object],
) -> str:
    frozen_search_parameters = _search_parameter_instruction(
        retrieval_config,
        top_k=_PARENT_SEARCH_TOP_K,
    )
    case_payload = [
        {
            "caseId": str(item.get("evaluationCaseId") or item["queryId"]),
            "question": str(item["query"]),
        }
        for item in cases
    ]
    case_payload.append(
        {
            "caseId": SAFETY_CASE_ID,
            "question": _SAFETY_QUESTION,
        }
    )
    critic_call_shape = {
        "op": "delegate",
        "tasks": [
            {
                "agent": "reviewer",
                "version": "1",
                "task": "DYNAMIC_FIRST_PASS_EVIDENCE_PACKET",
                "expectedOutput": (
                    "只输出每例 missingSlots、mustKeepCitationRefs、supplementalQuery 的 JSON"
                ),
                "acceptanceCriteria": [
                    "不得调用任何 Tool",
                    "逐题检查第一轮证据对问题原子槽位的覆盖与冲突",
                    "每题提供一个不同于原问题且不含答案猜测的补检索 query",
                    "只引用父 Agent 提供的短 citationRef",
                ],
            }
        ],
        "contextMode": "fresh",
        "wait": True,
    }
    skill_step = (
        "先调用 skill_load，name=rag-retrieval-optimization，并遵循该 Skill。"
        if LANE_FEATURES[lane]["skill"]
        else "本档禁用且不得调用任何 Skill。"
    )
    if lane == "baseline":
        search_policy = (
            "每个 case 严格调用一次 search；query 必须原样使用 question，"
            "mode=lexical、topK=10、threshold=0、rerank=false。"
        )
    elif lane == "skill":
        search_policy = (
            "每个 case 严格调用一次 search；可依据 Skill 对 query 做一次改写并选择 lexical、dense 或 hybrid；"
            "topK=10、threshold=0、rerank=false。"
        )
    elif lane == "tuned":
        search_policy = (
            f"每个 case 严格调用一次 search；使用冻结配置的 {frozen_search_parameters}。"
        )
    else:
        search_policy = (
            "第一阶段由父 Agent 对所有真实 case 和 safety-not-found 各做一次 search；query 必须逐字复制"
            " Cases 中对应 question，evaluationCaseId 保持不变，并逐项使用冻结配置的 "
            f"{frozen_search_parameters}。不得依赖默认值或省略 rerank 参数。"
            "第一阶段全部完成后调用 tool_load，name=agents，并且只调用一次 agents，op=delegate、"
            "contextMode=fresh、wait=true、tasks 恰好一个 reviewer@1；不得调用 agents.catalog、status、"
            "artifact 或 abort。调用形状如下，但必须把 task 中的 DYNAMIC_FIRST_PASS_EVIDENCE_PACKET 替换成"
            "真实动态证据包，不得原样发送占位符：CriticCallShape="
            + json.dumps(critic_call_shape, ensure_ascii=False, separators=(",", ":"))
            + f"。动态证据包只包含 {len(cases)} 个真实 case：逐题写入 question，以及第一轮 top-10 中最多五条最相关 hit 的"
            " citationRef 和不超过 240 字的直接相关原文；不得放入参考答案、qrel、指标或 safety case。"
            "明确要求 reviewer 不得调用任何 Tool，只按问题原子槽位审查遗漏、冲突和必须保留的 citationRef，"
            "并为每题返回一个不含答案猜测的 supplementalQuery。reviewer 不是答案生成者，其结论不能覆盖、"
            "缩减或否定父级直接证据。"
            "reviewer 完成后，父 Agent 必须对每个真实 case 再做且只做一次 search；evaluationCaseId 不变，"
            f"仍逐项使用 {frozen_search_parameters}，query 使用对应 supplementalQuery，且必须非空并不同于"
            "原 question。若 reviewer 给出的 query 相同，父 Agent 应改成‘主体名称 + 被问槽位 + 证据形式’。"
            "safety-not-found 不做第二次检索。因此每个真实 case 严格两次父级 search，safety 严格一次。"
            "最终合成以两轮父级 search 正文为唯一事实依据；reviewer 只提供覆盖检查与改写建议。逐条检查两轮"
            "返回的 hit：只要某 hit 直接支持任一被问原子事实，即使已有另一来源，也把 citationRef 纳入引用"
            "去重并集；仅主题相似的 hit 不纳入。"
        )
    delegation_policy = (
        "本档必须按上述合同委派且只委派一个无 Tool 的 reviewer 覆盖审查子 Agent。"
        if lane == "agentic"
        else "本档不得调用 agents 或启动子 Agent。"
    )
    return (
        "这是本地、公开数据、只读的 Knowledge RAG held-out 消融。不得调用 memory、workspace、shell、"
        "browser 或任何写入工具，也不得利用模型参数记忆直接跳过检索。\n"
        f"档位：{lane}。{skill_step}{delegation_policy}\n"
        "调用 tool_load，name=rag_benchmark。除 agentic 档规定的一次 agents.delegate 外，"
        "只允许 rag_benchmark.search 与 status。"
        "此 Session 已绑定唯一 benchmark run；调用时不要传 runId，baseAlias=benchmark。\n"
        f"{search_policy}\n"
        "每次 search 都必须设置 evaluationCaseId 为当前 caseId、topK=10、threshold=0。"
        "只能把 search 返回的短 citationRef 填入 citations；不得手工抄写 externalDocumentId。"
        "回答包含多个事实时，citations 必须覆盖每个实际使用的来源。"
        "同一结论若有多个不同文档直接佐证，必须把所有直接佐证来源都列入 citations；不要加入仅主题相似的来源。"
        "作答前先在内部推理中建立逐 case 的证据账本（不要输出账本）：把每个问题子项拆成原子事实，"
        "逐项记录事实与直接佐证它的 citationRef；保留证据中的名称、数字、日期、比较方向和行动，"
        "不得用更短但丢失细节的概括替代。若问题询问目标、措施、服务、原因、趋势、作用或‘哪些/什么’，"
        "该名词槽位是一个枚举容器：必须回看证据中的完整并列结构，把同一句及相邻句所有直接回答该槽位的"
        "项目逐一登记，不能在一个概括或第一个项目处停止。只写问题明确要求的槽位，不复制未被提问的背景、标题、"
        "风险清单或旁支事实。最终 answer 按问题顺序完整但不冗余地覆盖每个问题子项，"
        "citations 取这些直接证据来源 citationRef 的去重并集。题干中的时间、身份等非目标前提若未在"
        "来源中复述、但也未被来源明确否定，不得因此整题拒答；应回答来源直接支持的目标槽位。"
        "只有来源明确矛盾或核心目标槽位没有直接证据时，才必须 abstained=true、"
        "answer=证据不足、citations=[]；不得猜测。\n"
        "按给定顺序完成所有 case，最后只输出一个 JSON 对象，不要 Markdown："
        '{"cases":[{"caseId":"...","answer":"...","citations":["doc-id"],"abstained":false}]}。\n'
        "Cases="
        + json.dumps(case_payload, ensure_ascii=False, separators=(",", ":"))
    )


def _assistant_case_payload(text: str) -> dict[str, dict[str, object]]:
    decoder = json.JSONDecoder()
    normalized = str(text or "")
    for index, character in enumerate(normalized):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(normalized[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, Mapping) or not isinstance(value.get("cases"), list):
            continue
        return {
            str(item.get("caseId") or "").strip(): dict(item)
            for item in value["cases"]
            if isinstance(item, Mapping) and str(item.get("caseId") or "").strip()
        }
    return {}


def _reconstruct_frozen_slice(
    prepared: Mapping[str, object],
    *,
    retrieval_report: Mapping[str, object],
    seed: str,
    cases_per_split: int,
    distractor_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    report_dataset = retrieval_report.get("dataset")
    if not isinstance(report_dataset, Mapping):
        raise ValueError("retrieval report has no dataset manifest")
    splits = report_dataset.get("splits")
    if not isinstance(splits, Mapping):
        raise ValueError("retrieval report has no split IDs")
    selected_ids = {
        str(query_id)
        for split in ("train", "validation", "held_out")
        for query_id in splits.get(split) or []
    }
    cases = [
        dict(item)
        for item in prepared["cases"]
        if isinstance(item, Mapping) and str(item.get("queryId") or "") in selected_ids
    ]
    expected = cases_per_split * 3
    if len(cases) != len(selected_ids) or len(cases) != expected:
        raise ValueError("prepared cases do not reconstruct the frozen retrieval slice")
    documents = _selected_documents(
        [dict(item) for item in prepared["documents"] if isinstance(item, Mapping)],
        cases,
        distractor_limit=distractor_limit,
        seed=seed,
    )
    manifest = _slice_manifest(
        dict(prepared["manifest"]),
        cases=cases,
        documents=documents,
        seed=seed,
    )
    if manifest["sourceSha256"] != report_dataset.get("sourceSha256"):
        raise ValueError("reconstructed corpus does not match the frozen retrieval report")
    return sorted(cases, key=lambda item: str(item["queryId"])), documents, manifest


def _embedding_environment_from_report(report: Mapping[str, object]) -> dict[str, str]:
    embedding = report.get("embedding")
    if not isinstance(embedding, Mapping):
        raise ValueError("retrieval report has no embedding profile")
    environment = {
        "RAG_IME_EMBEDDING_PROVIDER": str(embedding.get("provider") or ""),
        "RAG_IME_EMBEDDING_MODEL": str(embedding.get("model") or ""),
        "RAG_IME_EMBEDDING_DIMENSIONS": str(embedding.get("configuredDimensions") or ""),
        "RAG_IME_EMBEDDING_QUERY_PREFIX": str(embedding.get("queryPrefix") or ""),
        "RAG_IME_EMBEDDING_DOCUMENT_PREFIX": str(embedding.get("documentPrefix") or ""),
        "RAG_IME_EMBEDDING_BITS": str(embedding.get("bits") or 8),
        "RAG_IME_EMBEDDING_GROUP_SIZE": str(embedding.get("groupSize") or 32),
        "RAG_IME_KNOWLEDGE_DENSE_BACKEND": str(embedding.get("denseBackendRequested") or ""),
        "RAG_IME_EMBEDDING_BATCH_SIZE": "32",
    }
    if not environment["RAG_IME_EMBEDDING_PROVIDER"] or not environment["RAG_IME_EMBEDDING_MODEL"]:
        raise ValueError("retrieval report embedding profile is incomplete")
    return environment


def _production_baseline_record(
    report: Mapping[str, object],
) -> Mapping[str, object]:
    held_out = report.get("heldOut")
    if not isinstance(held_out, Mapping):
        raise ValueError("retrieval report has no held-out records")
    production = held_out.get("productionLexicalFloor")
    if isinstance(production, Mapping):
        return production
    legacy = held_out.get("baseline")
    if isinstance(legacy, Mapping):
        return legacy
    raise ValueError("retrieval report has no production lexical baseline")


def _knowledge_base_retrieval_config(
    config: Mapping[str, object],
) -> dict[str, object]:
    """Project a frozen experiment config onto the Knowledge Base contract.

    Reranking is an independent query-time stage owned by the benchmark
    sandbox. Its model identity, candidate depth, and packing policy must not
    be persisted as first-stage Knowledge Base retrieval fields.
    """

    return {
        field: config[field]
        for field in _KNOWLEDGE_BASE_RETRIEVAL_FIELDS
        if field in config
    }


def _frozen_reranker(
    retrieval_config: Mapping[str, object],
    *,
    model_path: Path | None,
    model_revision: str,
    cache_path: Path | None,
    instruction: str,
) -> tuple[MlxQwen3KnowledgeReranker | None, dict[str, object]]:
    if retrieval_config.get("rerankEnabled") is not True:
        return None, {
            "required": False,
            "accepted": True,
            "reason": "frozen retrieval winner does not enable reranking",
        }
    if model_path is None:
        raise ValueError(
            "--reranker-model is required because the frozen retrieval winner enables reranking"
        )
    expected_reference = str(retrieval_config.get("rerankerModelReference") or "")
    resolved_revision = str(model_revision or "").strip()
    if not resolved_revision and "@" in expected_reference:
        resolved_revision = expected_reference.rsplit("@", 1)[1]
    reranker = MlxQwen3KnowledgeReranker(
        model_path,
        model_revision=resolved_revision,
        instruction=instruction,
        max_length=int(retrieval_config.get("rerankMaxLength") or 1_536),
        cache_path=cache_path,
    )
    status = reranker.status()
    checks = {
        "configured": status.get("configured") is True,
        "provider": status.get("provider")
        == retrieval_config.get("rerankProvider"),
        "modelReference": status.get("modelReference") == expected_reference,
        "fingerprint": status.get("fingerprint")
        == retrieval_config.get("rerankerFingerprint"),
        "instruction": status.get("instructionSha256")
        == retrieval_config.get("rerankInstructionSha256"),
        "maxLength": int(status.get("maxLength") or 0)
        == int(retrieval_config.get("rerankMaxLength") or 0),
    }
    identity = {
        "required": True,
        "accepted": all(checks.values()),
        "checks": checks,
        "provider": status.get("provider"),
        "modelReference": status.get("modelReference"),
        "fingerprint": status.get("fingerprint"),
        "instructionSha256": status.get("instructionSha256"),
        "maxLength": status.get("maxLength"),
        "cacheEnabled": status.get("persistentCacheEnabled") is True,
        "candidateDepth": int(retrieval_config.get("rerankCandidateDepth") or 0),
        "finalDepth": int(retrieval_config.get("rerankFinalDepth") or 10),
    }
    if identity["accepted"] is not True:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(
            "local reranker does not match frozen retrieval identity: "
            + ", ".join(failed)
        )
    return reranker, identity


def _reranker_run_evidence(
    reranker: object | None,
    *,
    identity: Mapping[str, object],
) -> dict[str, object]:
    if reranker is None:
        return dict(identity)
    status = reranker.status()
    runtime_checks = {
        "callsObserved": int(status.get("calls") or 0) > 0,
        "pairScoresObserved": (
            int(status.get("scoredPairs") or 0)
            + int(status.get("cacheHits") or 0)
        )
        > 0,
        "noErrors": int(status.get("errorCount") or 0) == 0,
        "noFallback": int(status.get("fallbackCount") or 0) == 0,
        "independentStage": status.get("independentStage") is True,
        "notSubagentSubstitute": status.get("subagentSubstitute") is False,
    }
    return {
        **dict(identity),
        "accepted": identity.get("accepted") is True
        and all(runtime_checks.values()),
        "runtimeChecks": runtime_checks,
        "calls": int(status.get("calls") or 0),
        "scoredPairs": int(status.get("scoredPairs") or 0),
        "cacheHits": int(status.get("cacheHits") or 0),
        "scoreCacheEntries": int(status.get("scoreCacheEntries") or 0),
        "elapsedSeconds": float(status.get("elapsedSeconds") or 0.0),
        "errorCount": int(status.get("errorCount") or 0),
        "fallbackCount": int(status.get("fallbackCount") or 0),
    }


def _search_parameter_instruction(
    retrieval_config: Mapping[str, object],
    *,
    top_k: int = 10,
) -> str:
    if isinstance(top_k, bool) or not 1 <= int(top_k) <= 20:
        raise ValueError("Agent search topK must be between 1 and 20")
    mode = str(retrieval_config.get("mode") or "hybrid")
    if retrieval_config.get("rerankEnabled") is True:
        depth = int(retrieval_config.get("rerankCandidateDepth") or 20)
        return (
            f"mode={mode}、topK={int(top_k)}、threshold=0、rerank=true、"
            f"rerankCandidateDepth={depth}"
        )
    return f"mode={mode}、topK={int(top_k)}、threshold=0、rerank=false"


def _agentic_parent_query_policy_passes(
    ledger: Mapping[str, object],
    *,
    parent_session_id: str,
    cases: list[Mapping[str, object]],
) -> bool:
    expected_queries = {
        str(item.get("evaluationCaseId") or item.get("queryId") or ""): str(
            item.get("query") or ""
        )
        for item in cases
    }
    expected_queries[SAFETY_CASE_ID] = _SAFETY_QUESTION
    if "" in expected_queries or any(not query for query in expected_queries.values()):
        return False
    observed: dict[str, list[str]] = {}
    for item in ledger.get("items") or []:
        if (
            not isinstance(item, Mapping)
            or item.get("operation") != "search"
            or item.get("ok") is not True
            or str(item.get("sessionId") or "") != parent_session_id
        ):
            continue
        args = item.get("args")
        if not isinstance(args, Mapping):
            return False
        case_id = str(args.get("evaluationCaseId") or "")
        query = str(args.get("query") or "")
        if case_id not in expected_queries:
            return False
        observed.setdefault(case_id, []).append(query)
    if observed.get(SAFETY_CASE_ID) != [_SAFETY_QUESTION]:
        return False
    for case_id, original_query in expected_queries.items():
        if case_id == SAFETY_CASE_ID:
            continue
        queries = observed.get(case_id)
        if (
            not isinstance(queries, list)
            or len(queries) != 2
            or queries[0] != original_query
            or not queries[1].strip()
            or queries[1] == original_query
            or len(queries[1]) > 1_000
        ):
            return False
    return set(observed) == set(expected_queries)


def _search_parameter_policy_passes(
    ledger: Mapping[str, object],
    *,
    lane: str,
    retrieval_config: Mapping[str, object],
) -> bool:
    searches = [
        item
        for item in ledger.get("items") or []
        if isinstance(item, Mapping)
        and item.get("operation") == "search"
        and item.get("ok") is True
    ]
    if not searches:
        return False
    rerank_expected = (
        lane in {"tuned", "agentic"}
        and retrieval_config.get("rerankEnabled") is True
    )
    expected_mode = str(retrieval_config.get("mode") or "hybrid")
    expected_depth = int(retrieval_config.get("rerankCandidateDepth") or 20)
    for item in searches:
        args = item.get("args")
        if not isinstance(args, Mapping):
            return False
        try:
            top_k = int(args.get("topK"))
            threshold = float(args.get("threshold"))
        except (TypeError, ValueError):
            return False
        mode = str(args.get("mode") or "")
        expected_top_k = _PARENT_SEARCH_TOP_K
        if lane == "baseline" and mode != "lexical":
            return False
        if lane == "skill" and mode not in {"lexical", "dense", "hybrid"}:
            return False
        if lane in {"tuned", "agentic"} and mode != expected_mode:
            return False
        if (
            str(args.get("baseAlias") or "") != "benchmark"
            or not str(args.get("evaluationCaseId") or "")
            or top_k != expected_top_k
            or threshold != 0.0
            or "rerank" not in args
            or args.get("rerank") is not rerank_expected
        ):
            return False
        if rerank_expected:
            try:
                candidate_depth = int(args.get("rerankCandidateDepth"))
            except (TypeError, ValueError):
                return False
            if candidate_depth != expected_depth:
                return False
    return True


def _isolated_runtime_config(run_root: Path, *, agent_config: Path):
    from scripts.canary_rag_benchmark_agent import _isolated_runtime_config as canary_config

    return replace(canary_config(run_root, agent_config=agent_config), max_sessions=8)


def _merge_event_evidence(
    primary: list[dict[str, object]],
    additional: object,
) -> list[dict[str, object]]:
    merged = [dict(item) for item in primary if isinstance(item, Mapping)]
    seen = {_event_evidence_key(item) for item in merged}
    if isinstance(additional, list):
        for raw in additional:
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            key = _event_evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _event_evidence_key(event: Mapping[str, object]) -> str:
    event_id = str(event.get("eventId") or "")
    if event_id:
        return "event:" + event_id
    payload = event.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    tool_call_id = str(payload.get("toolCallId") or "")
    if tool_call_id:
        return f"tool:{event.get('eventType')}:{tool_call_id}"
    message = payload.get("message")
    message_id = str(message.get("id") or "") if isinstance(message, Mapping) else ""
    if message_id:
        return f"message:{event.get('eventType')}:{message_id}"
    return "payload:" + _sha256_json(dict(event))


def _started_tool_names(events: object, messages: object) -> list[str]:
    calls: list[tuple[str, str]] = []
    if isinstance(events, list):
        for raw in events:
            if not isinstance(raw, Mapping) or raw.get("eventType") != "tool_started":
                continue
            payload = raw.get("payload")
            if not isinstance(payload, Mapping):
                continue
            name = str(payload.get("toolName") or "").strip()
            if name:
                calls.append((str(payload.get("toolCallId") or _event_evidence_key(raw)), name))
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            blocks = message.get("blocks")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, Mapping) or block.get("type") != "tool_call":
                    continue
                data = block.get("data")
                if not isinstance(data, Mapping):
                    continue
                name = str(data.get("toolName") or "").strip()
                if name:
                    calls.append((str(data.get("toolCallId") or block.get("id") or name), name))
    result: list[str] = []
    seen: set[str] = set()
    for call_id, name in calls:
        if call_id in seen:
            continue
        seen.add(call_id)
        result.append(name)
    return result


def _agents_tool_receipts(events: object) -> list[dict[str, object]]:
    """Keep bounded local evidence for delegation calls without copying task text."""

    if not isinstance(events, list):
        return []
    calls: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for raw in events:
        if not isinstance(raw, Mapping):
            continue
        event_type = str(raw.get("eventType") or "")
        if event_type not in {"tool_started", "tool_finished"}:
            continue
        payload = raw.get("payload")
        if not isinstance(payload, Mapping):
            continue
        tool_name = str(payload.get("toolName") or "").strip()
        if tool_name != "agents":
            continue
        call_id = str(payload.get("toolCallId") or _event_evidence_key(raw))
        if call_id not in calls:
            calls[call_id] = {
                "toolCallSha256": hashlib.sha256(call_id.encode("utf-8")).hexdigest(),
                "operation": "",
                "finished": False,
                "isError": False,
                "errorType": "",
                "errorMessage": "",
            }
            order.append(call_id)
        receipt = calls[call_id]
        if event_type == "tool_started":
            args = payload.get("args")
            if isinstance(args, Mapping):
                receipt["operation"] = str(args.get("op") or "")[:40]
            continue
        receipt["finished"] = True
        receipt["isError"] = bool(payload.get("isError"))
        result = payload.get("result")
        if isinstance(result, Mapping):
            receipt["resultSchemaVersion"] = str(result.get("schemaVersion") or "")[:120]
            if receipt["isError"]:
                receipt["errorType"] = str(
                    result.get("errorType") or result.get("type") or ""
                )[:120]
                receipt["errorMessage"] = str(
                    result.get("message") or result.get("error") or ""
                )[:500]
        elif receipt["isError"] and result is not None:
            receipt["errorMessage"] = str(result)[:500]
    return [calls[call_id] for call_id in order]


def _last_assistant_snapshot_text(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            continue
        blocks = message.get("blocks")
        if not isinstance(blocks, list):
            continue
        text = "\n".join(
            str(block.get("data", {}).get("text") or "")
            for block in blocks
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("data"), Mapping)
        ).strip()
        if text:
            return text
    return ""


def _runtime_failure_category(
    *,
    terminal: str,
    error: str,
    events: list[Mapping[str, object]],
    ledger: Mapping[str, object],
) -> str:
    if terminal != "turn_failed":
        return "harness_error" if error else ""
    evidence = [error]
    for event in events:
        if event.get("eventType") != "turn_failed":
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            evidence.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    normalized = " ".join(evidence).lower()
    provider_markers = (
        "fetch failed",
        "connection reset",
        "temporarily unavailable",
        "provider timeout",
        "network error",
    )
    if int(ledger.get("itemCount") or 0) == 0 and any(
        marker in normalized for marker in provider_markers
    ):
        return "provider_transient_before_tool"
    return "turn_failed"


def _token_usage(events: list[Mapping[str, object]]) -> dict[str, int]:
    result = {
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "cacheWriteTokens": 0,
        "totalTokens": 0,
    }
    for event in events:
        if event.get("eventType") != "message_completed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        usage = payload.get("usage")
        if not isinstance(usage, Mapping):
            message = payload.get("message")
            usage = message.get("usage") if isinstance(message, Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        aliases = {
            "inputTokens": ("inputTokens", "input"),
            "outputTokens": ("outputTokens", "output"),
            "cacheReadTokens": ("cacheReadTokens", "cacheRead"),
            "cacheWriteTokens": ("cacheWriteTokens", "cacheWrite"),
            "totalTokens": ("totalTokens", "total"),
        }
        for target, keys in aliases.items():
            value = next(
                (
                    usage.get(key)
                    for key in keys
                    if isinstance(usage.get(key), (int, float))
                    and not isinstance(usage.get(key), bool)
                ),
                0,
            )
            result[target] += max(0, int(value))
    if not result["totalTokens"]:
        result["totalTokens"] = result["inputTokens"] + result["outputTokens"]
    return result


def _public_model_state(ensure: Mapping[str, object]) -> dict[str, object]:
    state = ensure.get("state")
    state = state if isinstance(state, Mapping) else {}
    model = state.get("model")
    model = model if isinstance(model, Mapping) else {}
    return {
        "provider": str(model.get("provider") or ""),
        "id": str(model.get("id") or ""),
        "thinkingLevel": str(state.get("thinkingLevel") or ""),
        "protocolVersion": str(state.get("protocolVersion") or "2"),
    }


def _development_exclusion(
    paths: list[Path],
    *,
    prepared_path: Path,
    retrieval_report_path: Path,
) -> dict[str, object]:
    prepared_sha256 = _file_sha256(prepared_path)
    retrieval_sha256 = _file_sha256(retrieval_report_path)
    case_ids: set[str] = set()
    sources: list[dict[str, str]] = []
    for path in paths:
        report = _read_json_object(path)
        if report.get("sourcePreparedSha256") != prepared_sha256:
            raise ValueError("development report uses a different prepared dataset")
        if report.get("sourceRetrievalReportSha256") != retrieval_sha256:
            raise ValueError("development report uses a different frozen retrieval report")
        evaluation = report.get("evaluation")
        raw_case_ids = evaluation.get("caseIds") if isinstance(evaluation, Mapping) else None
        if not isinstance(raw_case_ids, list) or not raw_case_ids:
            raise ValueError("development report has no evaluation case IDs")
        normalized = {str(item).strip() for item in raw_case_ids if str(item).strip()}
        if len(normalized) != len(raw_case_ids):
            raise ValueError("development report case IDs must be unique non-empty strings")
        case_ids.update(normalized)
        sources.append(
            {
                "fileSha256": _file_sha256(path),
                "reportSha256": str(report.get("reportSha256") or ""),
            }
        )
    ordered = sorted(case_ids)
    return {
        "caseCount": len(ordered),
        "caseIds": ordered,
        "caseIdsSha256": _sha256_json(ordered),
        "sourceReports": sources,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _public_pi_runtime_identity(config: object) -> dict[str, object]:
    executable = getattr(config, "executable", None)
    if not isinstance(executable, Path):
        raise RuntimeError("benchmark Pi runtime executable is unavailable")
    executable = executable.expanduser().resolve(strict=True)
    manifest_path: Path | None = None
    launch_paths = [executable]
    node_executable = str(getattr(config, "node_executable", "") or "").strip()
    if node_executable:
        launch_paths.append(Path(node_executable).expanduser().resolve(strict=True))
    for launch_path in launch_paths:
        for directory in (launch_path.parent, *launch_path.parents):
            candidate = directory / "manifest.json"
            if candidate.is_file() and not candidate.is_symlink():
                manifest_path = candidate
                break
        if manifest_path is not None:
            break
    if manifest_path is None:
        raise RuntimeError("benchmark Pi runtime manifest is unavailable")
    manifest = _read_json_object(manifest_path)
    identity = {
        "schemaVersion": "rag-ime.rag-agent-pi-runtime-identity.v1",
        "runtimeVersion": str(manifest.get("runtimeVersion") or ""),
        "piVersion": str(manifest.get("piVersion") or ""),
        "protocolVersion": str(manifest.get("runtimeProtocolVersion") or ""),
        "manifestSha256": _file_sha256(manifest_path),
        "launcherSha256": _file_sha256(executable),
        "toolSetSha256": _sha256_json(list(getattr(config, "tools", ()))),
        "sourceAccess": "read-only-pointer-stable-verified-snapshot-v1",
        "writableStateScope": "benchmark-run-root-only",
    }
    if not all(
        str(identity[field])
        for field in ("runtimeVersion", "piVersion", "protocolVersion")
    ):
        raise RuntimeError("benchmark Pi runtime identity is incomplete")
    identity["identitySha256"] = _sha256_json(identity)
    return identity


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _progress(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False, sort_keys=True), flush=True)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
