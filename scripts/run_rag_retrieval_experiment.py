#!/usr/bin/env python3
"""Run a local-only Knowledge retrieval matrix through the product index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.embeddings import (  # noqa: E402
    embedding_provider_from_env,
    embedding_provider_info,
)
from rag_ime.knowledge_library import KnowledgeLibraryConfig, KnowledgeLibraryService  # noqa: E402
from rag_ime.knowledge_library.dense import dense_index_from_env  # noqa: E402
from rag_ime.knowledge_library.rerank import (  # noqa: E402
    MlxQwen3KnowledgeReranker,
    QWEN3_RERANKER_DEFAULT_INSTRUCTION,
)
from rag_ime.rag_benchmark import select_validation_config, validate_dataset_manifest  # noqa: E402
from rag_ime.rag_benchmark_exact_dense import BenchmarkExactDenseIndex  # noqa: E402
from rag_ime.rag_benchmark_sandbox import (  # noqa: E402
    DELETE_CONFIRMATION,
    RagBenchmarkSandbox,
    RagBenchmarkSandboxPolicy,
)
from rag_ime.rag_benchmark_luna_graph import (  # noqa: E402
    benchmark_graph_extractor_factory,
)
from rag_ime.rag_retrieval_experiment import (  # noqa: E402
    deterministic_query_plan,
    evaluate_retrieval_configuration,
)


DEFAULT_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "mode": "lexical",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.0,
        "denseWeight": 1.0,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "dense",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.0,
        "denseWeight": 1.0,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.0,
        "denseWeight": 1.0,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.5,
        "denseWeight": 0.5,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 0.5,
        "denseWeight": 1.5,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.0,
        "denseWeight": 2.0,
        "graphEnabled": False,
        "graphWeight": 0.0,
        "rrfK": 20,
        "candidateMultiplier": 8,
    },
)

GRAPH_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 0.5,
        "denseWeight": 1.5,
        "graphEnabled": True,
        "graphWeight": 0.3,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 0.5,
        "denseWeight": 1.5,
        "graphEnabled": True,
        "graphWeight": 0.7,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 0.25,
        "denseWeight": 1.5,
        "graphEnabled": True,
        "graphWeight": 1.0,
        "rrfK": 60,
        "candidateMultiplier": 4,
    },
    {
        "mode": "hybrid",
        "topK": 10,
        "threshold": 0.0,
        "lexicalWeight": 1.0,
        "denseWeight": 2.0,
        "graphEnabled": True,
        "graphWeight": 0.5,
        "rrfK": 20,
        "candidateMultiplier": 8,
    },
)

RERANK_BASE_CANDIDATES: tuple[dict[str, object], ...] = (
    DEFAULT_CANDIDATES[1],
    DEFAULT_CANDIDATES[4],
    DEFAULT_CANDIDATES[5],
)

_RETRIEVAL_CONFIG_KEYS = frozenset(
    {
        "mode",
        "topK",
        "threshold",
        "lexicalWeight",
        "denseWeight",
        "graphEnabled",
        "graphWeight",
        "rrfK",
        "candidateMultiplier",
    }
)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument(
        "--sandbox-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "retrieval",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="paw-retrieval-experiment-v1")
    parser.add_argument("--max-cases-per-split", type=int, default=0)
    parser.add_argument(
        "--include-slice",
        action="append",
        default=[],
        help="Repeat to restrict every split to named public benchmark slices.",
    )
    parser.add_argument("--distractor-limit", type=int, default=0)
    parser.add_argument(
        "--evaluation-scope",
        choices=("validation-only", "full"),
        default="full",
    )
    parser.add_argument(
        "--chunk-strategy",
        choices=("general", "markdown", "book", "qa", "laws", "separator", "fixed"),
        default="general",
    )
    parser.add_argument("--chunk-size", type=int, default=1_200)
    parser.add_argument("--chunk-overlap", type=int, default=160)
    parser.add_argument("--chunk-separator", default="")
    parser.add_argument(
        "--respect-headings",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--respect-page-boundaries",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("local-hash", "mlx-bert", "sentence-transformers", "openai-compatible"),
        default="local-hash",
    )
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--embedding-dimensions", type=int, default=96)
    parser.add_argument("--embedding-query-prefix", default="")
    parser.add_argument("--embedding-document-prefix", default="")
    parser.add_argument("--embedding-bits", type=int, default=8)
    parser.add_argument("--embedding-group-size", type=int, default=32)
    parser.add_argument(
        "--dense-backend",
        choices=("sqlite-exact", "usearch"),
        default="usearch",
    )
    parser.add_argument(
        "--reranker",
        choices=("none", "mlx-qwen3"),
        default="none",
        help="Enable an independent local Knowledge reranker for validation candidates.",
    )
    parser.add_argument("--reranker-model", default="")
    parser.add_argument("--reranker-revision", default="")
    parser.add_argument(
        "--reranker-cache",
        type=Path,
        default=None,
        help="Optional local hash-only score cache; never place it in public eval artifacts.",
    )
    parser.add_argument(
        "--rerank-instruction",
        default=QWEN3_RERANKER_DEFAULT_INSTRUCTION,
    )
    parser.add_argument("--rerank-max-length", type=int, default=1_536)
    parser.add_argument(
        "--rerank-candidate-depth",
        type=int,
        action="append",
        dest="rerank_candidate_depths",
        help="Repeat to compare multiple bounded rerank depths in one frozen run.",
    )
    parser.add_argument("--rerank-final-depth", type=int, default=10)
    parser.add_argument(
        "--knowledge-graph",
        action="store_true",
        help="Build the independent Knowledge graph and include graph-fusion candidates.",
    )
    parser.add_argument(
        "--graph-extractor",
        choices=("luna", "deterministic"),
        default="luna",
        help="Luna is required for accepted graph-effect claims; deterministic is diagnostic only.",
    )
    parser.add_argument("--graph-batch-size", type=int, default=8)
    parser.add_argument("--graph-extraction-concurrency", type=int, default=4)
    parser.add_argument("--graph-max-entities", type=int, default=5)
    parser.add_argument("--graph-max-relations", type=int, default=4)
    parser.add_argument("--graph-max-topics", type=int, default=2)
    parser.add_argument("--graph-codex-bin", default="codex")
    parser.add_argument("--graph-timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--keep-sandbox", action="store_true")
    parser.add_argument(
        "--held-out-multi-query-diagnostic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the deterministic multi-query diagnostic in full mode; it is not the Luna Agentic lane.",
    )
    args = parser.parse_args(argv)

    # MLX can report a capability flag in a headless/virtualized session even
    # though its first device operation aborts the native process. Check one
    # real operation before constructing a semantic index or reranker so an
    # unavailable host produces a bounded, non-score diagnostic.
    if str(args.embedding_provider) == "mlx-bert":
        try:
            _require_actual_metal_runtime()
        except RuntimeError as exc:
            raise SystemExit(
                "semantic dense runtime is not ready: actual MLX Metal preflight failed: "
                f"{exc}"
            ) from exc

    candidate_configs = [dict(item) for item in DEFAULT_CANDIDATES]
    if bool(args.knowledge_graph):
        candidate_configs.extend(dict(item) for item in GRAPH_CANDIDATES)
    reranker: MlxQwen3KnowledgeReranker | None = None
    if str(args.reranker) == "mlx-qwen3":
        if not str(args.reranker_model).strip():
            raise SystemExit("--reranker-model is required for --reranker mlx-qwen3")
        reranker = MlxQwen3KnowledgeReranker(
            str(args.reranker_model),
            model_revision=str(args.reranker_revision),
            instruction=str(args.rerank_instruction),
            max_length=int(args.rerank_max_length),
            cache_path=(
                args.reranker_cache.expanduser().resolve(strict=False)
                if args.reranker_cache is not None
                else None
            ),
        )
        if not reranker.configured:
            raise SystemExit("MLX Qwen3 reranker model is not ready")
        try:
            _require_actual_metal_runtime()
        except RuntimeError as exc:
            raise SystemExit(
                "MLX Qwen3 reranker runtime is not ready: actual MLX Metal preflight failed: "
                f"{exc}"
            ) from exc
        rerank_depths = sorted(
            {
                max(2, min(100, int(value)))
                for value in (args.rerank_candidate_depths or [20])
            }
        )
        for rerank_depth in rerank_depths:
            candidate_configs.extend(
                _rerank_candidate_configs(
                    RERANK_BASE_CANDIDATES,
                    reranker=reranker,
                    candidate_depth=rerank_depth,
                    final_depth=int(args.rerank_final_depth),
                )
            )
            if bool(args.knowledge_graph):
                candidate_configs.extend(
                    _rerank_candidate_configs(
                        GRAPH_CANDIDATES,
                        reranker=reranker,
                        candidate_depth=rerank_depth,
                        final_depth=int(args.rerank_final_depth),
                    )
                )

    prepared_path = args.prepared.expanduser().resolve(strict=True)
    prepared = _load_prepared(prepared_path)
    prepared_cases = list(prepared["cases"])
    included_slices = {
        str(value).strip()
        for value in args.include_slice
        if str(value).strip()
    }
    if included_slices:
        prepared_cases = [
            item
            for item in prepared_cases
            if str(item.get("slice") or item.get("questionType") or "unknown")
            in included_slices
        ]
        if not prepared_cases:
            raise SystemExit("--include-slice matched no benchmark cases")
    cases = _selected_cases(
        prepared_cases,
        limit=int(args.max_cases_per_split),
        seed=str(args.seed),
    )
    documents = _selected_documents(
        list(prepared["documents"]),
        cases,
        distractor_limit=int(args.distractor_limit),
        seed=str(args.seed),
    )
    manifest = _slice_manifest(
        dict(prepared["manifest"]),
        cases=cases,
        documents=documents,
        seed=str(args.seed),
    )
    validation_cases = [
        item
        for item in cases
        if item.get("split") == "validation"
        and item.get("retrievalEvaluable") is not False
    ]
    held_out_cases = [
        item
        for item in cases
        if item.get("split") == "held_out"
        and item.get("retrievalEvaluable") is not False
    ]
    if not validation_cases or not held_out_cases:
        raise SystemExit("selected slice requires retrieval-evaluable validation and held_out cases")

    embedding_environment = _embedding_environment(args)
    provider = embedding_provider_from_env(embedding_environment)
    provider_public = embedding_provider_info(provider)
    source_bytes = sum(len(str(item["text"]).encode("utf-8")) for item in documents)
    maximum_document_bytes = max(
        4 * 1024 * 1024,
        max(len(str(item["text"]).encode("utf-8")) for item in documents),
    )
    policy = RagBenchmarkSandboxPolicy(
        max_runs=1,
        max_bases_per_run=1,
        max_documents_per_run=max(1, len(documents)),
        max_documents_per_call=min(256, max(1, len(documents))),
        max_document_bytes=maximum_document_bytes,
        max_total_source_bytes=max(
            maximum_document_bytes,
            source_bytes + 1024 * 1024,
        ),
        max_search_calls=max(
            10_000,
            len(validation_cases) * len(candidate_configs)
            + len(held_out_cases) * 8,
        ),
        max_rebuilds=8,
    )

    def service_factory(
        root: Path,
        _policy: RagBenchmarkSandboxPolicy,
    ) -> KnowledgeLibraryService:
        config = KnowledgeLibraryConfig(
            root,
            max_source_bytes=policy.max_document_bytes,
        )
        service = KnowledgeLibraryService(
            config,
            background_jobs=False,
        )
        service.dense_index = (
            BenchmarkExactDenseIndex(
                config.database_path,
                provider,
                batch_size=32,
            )
            if str(args.dense_backend) == "sqlite-exact"
            else dense_index_from_env(
                config.database_path,
                provider,
                embedding_environment,
            )
        )
        service.graph.extractor_factory = benchmark_graph_extractor_factory(
            root.parent / "luna-knowledge-graph",
            codex_bin=str(args.graph_codex_bin),
            timeout_seconds=float(args.graph_timeout_seconds),
        )
        return service

    sandbox_root = args.sandbox_root.expanduser().resolve(strict=False)
    sandbox = RagBenchmarkSandbox(
        sandbox_root,
        policy=policy,
        service_factory=service_factory,
        reranker=reranker,
    )
    owner = f"retrieval-{_sha256(str(args.output))[:16]}"
    run_id = ""
    run_passed = True
    started_at_ms = int(time.time() * 1_000)
    try:
        run = sandbox.create_run(owner, label=manifest["benchmarkId"])
        run_id = str(run["runId"])
        # The installed Knowledge runtime currently has no active dense
        # provider, so lexical is the faithful current-runtime baseline even
        # when its desired retrieval mode says "hybrid".
        baseline_config = dict(DEFAULT_CANDIDATES[0])
        base = sandbox.create_base(
            owner,
            run_id,
            alias="benchmark",
            name="RAG retrieval experiment",
            description="Local-only public benchmark slice",
            chunking_config={
                "strategy": str(args.chunk_strategy),
                "size": int(args.chunk_size),
                "overlap": int(args.chunk_overlap),
                "separator": str(args.chunk_separator),
                "respectHeadings": bool(args.respect_headings),
                "respectPageBoundaries": bool(args.respect_page_boundaries),
            },
            retrieval_config=baseline_config,
        )
        _progress(
            "created",
            documents=len(documents),
            validation=len(validation_cases),
            heldOut=len(held_out_cases),
            provider=provider_public,
        )
        imported = 0
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
            imported += len(batch)
            _progress("import", imported=imported, total=len(documents))

        import_status = sandbox.status(owner, run_id)
        dense_acceptance = _require_semantic_dense_runtime(
            provider=provider_public,
            status=import_status,
            requested_backend=str(args.dense_backend),
        )
        graph_build: dict[str, object] | None = None
        if bool(args.knowledge_graph):
            _progress(
                "graph_rebuild_started",
                extractor=str(args.graph_extractor),
                model="openai-codex/gpt-5.6-luna" if args.graph_extractor == "luna" else "",
                documentCount=len(documents),
            )
            graph_build = sandbox.rebuild_graph(
                owner,
                run_id,
                base_alias="benchmark",
                expected_revision=0,
                extractor_mode=str(args.graph_extractor),
                batch_size=int(args.graph_batch_size),
                extraction_concurrency=int(args.graph_extraction_concurrency),
                max_entities=int(args.graph_max_entities),
                max_relations=int(args.graph_max_relations),
                max_topics=int(args.graph_max_topics),
            )
            _progress(
                "graph_rebuild_completed",
                status=graph_build.get("status"),
                revision=graph_build.get("revision"),
                stats=graph_build.get("stats"),
                lunaExtractionPassed=graph_build.get("lunaExtractionPassed"),
                lunaReceipts=graph_build.get("lunaReceipts"),
            )

        active_candidate_sha256 = ""
        active_base_config_sha256 = ""

        def retrieve(query: dict[str, object], config: dict[str, Any]) -> list[str]:
            nonlocal active_candidate_sha256, active_base_config_sha256, base
            candidate_sha256 = _sha256_json(config)
            base_config = {
                key: value
                for key, value in config.items()
                if key in _RETRIEVAL_CONFIG_KEYS
            }
            base_config_sha256 = _sha256_json(base_config)
            if active_base_config_sha256 != base_config_sha256:
                base = sandbox.configure_base(
                    owner,
                    run_id,
                    base_alias="benchmark",
                    expected_revision=base["configRevision"],
                    retrieval_config=base_config,
                )
                active_base_config_sha256 = base_config_sha256
            if active_candidate_sha256 != candidate_sha256:
                active_candidate_sha256 = candidate_sha256
                _progress(
                    "candidate",
                    configSha256=candidate_sha256,
                    config=config,
                )
            rerank_enabled = config.get("rerankEnabled") is True
            candidate_depth = (
                max(1, min(100, int(config.get("rerankCandidateDepth") or 20)))
                if rerank_enabled
                else max(1, min(100, int(config.get("topK") or 10)))
            )
            final_depth = max(
                1,
                min(
                    20,
                    int(
                        config.get("rerankFinalDepth")
                        if rerank_enabled
                        else config.get("topK") or 10
                    ),
                )
            )
            result = sandbox.search(
                owner,
                run_id,
                base_alias="benchmark",
                query=str(query["text"]),
                top_k=final_depth if rerank_enabled else candidate_depth,
                mode=config.get("mode", "hybrid"),
                threshold=config.get("threshold", 0.0),
                rerank=rerank_enabled,
                rerank_candidate_depth=candidate_depth,
            )
            hits = list(result["hits"])
            return list(
                dict.fromkeys(str(hit["externalDocumentId"]) for hit in hits)
            )[:final_depth]

        selection = select_validation_config(
            manifest=manifest,
            validation_cases=validation_cases,
            candidate_configs=candidate_configs,
            retrieve=retrieve,
            objective="ndcgAtK.10",
            k_values=(1, 3, 5, 10),
        )
        winner = dict(selection["winner"]["config"])
        production_floor_validation = _selection_candidate(selection, DEFAULT_CANDIDATES[0])
        strong_dense_validation = _selection_candidate(selection, DEFAULT_CANDIDATES[1])
        validation_comparison = {
            "productionLexicalFloorToWinner": _selection_metric_deltas(
                production_floor_validation,
                selection["winner"],
            ),
            "strongNaiveDenseToWinner": _selection_metric_deltas(
                strong_dense_validation,
                selection["winner"],
            ),
        }
        held_out_report: dict[str, object] | None = None
        comparison: dict[str, object] | None = None
        if args.evaluation_scope == "full":
            baseline = evaluate_retrieval_configuration(
                cases=held_out_cases,
                config=baseline_config,
                retrieve=retrieve,
            )
            strong_dense = evaluate_retrieval_configuration(
                cases=held_out_cases,
                config=dict(DEFAULT_CANDIDATES[1]),
                retrieve=retrieve,
            )
            tuned = evaluate_retrieval_configuration(
                cases=held_out_cases,
                config=winner,
                retrieve=retrieve,
            )
            multi_query = (
                evaluate_retrieval_configuration(
                    cases=held_out_cases,
                    config=winner,
                    retrieve=retrieve,
                    query_planner=deterministic_query_plan,
                    max_queries_per_case=3,
                )
                if bool(args.held_out_multi_query_diagnostic)
                else None
            )
            held_out_report = {
                "productionLexicalFloor": baseline,
                "strongNaiveDenseBaseline": strong_dense,
                "tuned": tuned,
                "deterministicMultiQueryDiagnostic": multi_query,
            }
            comparison = {
                "productionLexicalFloorToTuned": _metric_deltas(baseline, tuned),
                "strongNaiveDenseToTuned": _metric_deltas(strong_dense, tuned),
                "productionLexicalFloorToDeterministicMultiQuery": (
                    _metric_deltas(baseline, multi_query)
                    if multi_query is not None
                    else None
                ),
            }
        status = sandbox.status(owner, run_id)
        completed_at_ms = int(time.time() * 1_000)
        relevant_document_ids = {
            str(document_id)
            for case in (
                cases
                if args.evaluation_scope == "full"
                else validation_cases
            )
            for document_id in dict(case.get("relevant") or {})
        }
        source_corpus_distractors = sum(
            item.get("source") == "crud_corpus_distractor"
            for item in documents
            if str(item["documentId"]) not in relevant_document_ids
        )
        graph_ready = graph_build is None or str(graph_build.get("status") or "") == "ready"
        luna_graph_passed = graph_build is None or (
            str(args.graph_extractor) == "luna"
            and graph_build.get("lunaExtractionPassed") is True
        )
        memory_mutation_performed = bool(
            graph_build is not None
            and graph_build.get("memoryMutationPerformed") is not False
        )
        reranker_status = (
            reranker.status()
            if reranker is not None
            else {
                "provider": "none",
                "configured": False,
                "enabled": False,
                "independentStage": True,
                "subagentSubstitute": False,
            }
        )
        reranker_ready = reranker is None or _reranker_acceptance_passes(
            reranker_status
        )
        hard_gates = {
            "heldOutLabelsHiddenDuringSelection": not bool(
                selection["heldOutLabelsObserved"]
            ),
            "heldOutMetricsSuppressedDuringChunkSelection": (
                args.evaluation_scope != "validation-only"
                or (held_out_report is None and comparison is None)
            ),
            "corpusFrozenBeforeCandidateEvaluation": True,
            "qrelsNotPassedToRetriever": True,
            "knowledgeGraphReady": graph_ready,
            "lunaKnowledgeGraphExtractionPassed": luna_graph_passed,
            "memoryMutationNotPerformed": not memory_mutation_performed,
            "independentRerankerReady": reranker_ready,
        }
        run_passed = all(hard_gates.values())
        report = {
            "schemaVersion": "rag-ime.rag-retrieval-run.v2",
            "status": "completed" if run_passed else "rejected",
            "localOnly": True,
            "uploaded": False,
            "evaluationScope": str(args.evaluation_scope),
            "startedAtMs": started_at_ms,
            "completedAtMs": completed_at_ms,
            "elapsedMs": completed_at_ms - started_at_ms,
            "dataset": manifest,
            "sourcePreparedSha256": _file_sha256(prepared_path),
            "corpus": {
                "documentCount": len(documents),
                "sourceBytes": source_bytes,
                "selection": {
                    "method": (
                        "full-prepared-corpus"
                        if int(args.distractor_limit) == 0
                        else "selected-split-qrels-plus-deterministic-distractors"
                    ),
                    "maxCasesPerSplit": int(args.max_cases_per_split),
                    "includedSlices": sorted(included_slices),
                    "distractorLimit": int(args.distractor_limit),
                    "seed": str(args.seed),
                    "frozenBeforeCandidateEvaluation": True,
                    "qrelsPassedToRetriever": False,
                },
                "relevantDocumentCount": len(relevant_document_ids),
                "distractorDocumentCount": (
                    len(documents) - len(relevant_document_ids)
                ),
                "distractorSourceBreakdown": {
                    "crudCorpus": source_corpus_distractors,
                    "otherGoldDocuments": (
                        len(documents)
                        - len(relevant_document_ids)
                        - source_corpus_distractors
                    ),
                },
            },
            "embedding": {
                **provider_public,
                "configuredDimensions": int(args.embedding_dimensions),
                "denseBackendRequested": str(args.dense_backend),
                "queryPrefix": str(args.embedding_query_prefix),
                "documentPrefix": str(args.embedding_document_prefix),
                "bits": int(args.embedding_bits),
                "groupSize": int(args.embedding_group_size),
                "acceptance": dense_acceptance,
                "runtime": status["dense"],
            },
            "chunking": base["chunkingConfig"],
            "knowledgeGraph": graph_build,
            "reranker": reranker_status,
            "validationBaselines": {
                "productionLexicalFloor": production_floor_validation,
                "strongNaiveDenseBaseline": strong_dense_validation,
            },
            "validationSelection": selection,
            "validationComparison": validation_comparison,
            "heldOut": held_out_report,
            "comparison": comparison,
            "hardGates": hard_gates,
            "scopeWarnings": [
                "The production lexical floor mirrors the observed installed Knowledge runtime without an active dense provider; the same report also carries a strong Chinese dense baseline to avoid a strawman comparison.",
                "This is a local product retrieval run, not an official benchmark leaderboard submission.",
                "The deterministic multi-query arm is an offline diagnostic, not the final Luna Agentic lane.",
                (
                    "The deterministic multi-query held-out diagnostic was disabled for this reranker-only run; Agentic effects are measured in the separate Luna four-lane suite."
                    if not bool(args.held_out_multi_query_diagnostic)
                    else "The deterministic multi-query held-out diagnostic is reported separately and is never labeled as Luna Agentic retrieval."
                ),
                "The strong naive dense baseline uses the same Chinese embedding, corpus, chunk profile and single-query budget without Skill, graph, rerank or Agentic iteration.",
                "A subagent is a query planner and evidence sufficiency judge, not a substitute for candidate reranking.",
                (
                    "The local MLX Qwen3 reranker is an independently fingerprinted query-passage scoring stage; validation decides whether it is retained."
                    if reranker is not None
                    else "No independent Knowledge reranker was enabled in this run."
                ),
                (
                    "Knowledge graph extraction is pinned to openai-codex/gpt-5.6-luna at max; any model fallback rejects the graph-effect claim."
                    if args.knowledge_graph and args.graph_extractor == "luna"
                    else "Deterministic graph extraction is a diagnostic and cannot satisfy the Luna graph acceptance gate."
                    if args.knowledge_graph
                    else "Knowledge graph candidates were not included in this run."
                ),
                (
                    "Validation-only mode suppresses every held-out metric and is safe for chunk-profile selection."
                    if args.evaluation_scope == "validation-only"
                    else "Full mode evaluates held-out once after the chunk profile is frozen."
                ),
                (
                    "Exact validation uses a deterministic benchmark-local matrix cache over the same SQLite vectors; USearch ANN quality and latency are reported separately and never used as the parameter-selection truth."
                    if str(args.dense_backend) == "sqlite-exact"
                    else "USearch is the scalable deployment lane; small cross-run ANN deltas must not be interpreted as model gains without an exact-scan control."
                ),
                (
                    "When a bounded corpus is requested, selected-split qrels are used only to assemble the frozen benchmark corpus; retrieval candidates receive query text, never qrels."
                ),
            ],
        }
        report["reportSha256"] = _sha256_json(report)
        _write_json(args.output.expanduser().resolve(strict=False), report)
        _progress(
            "completed",
            output=str(args.output),
            reportSha256=report["reportSha256"],
            comparison=report["comparison"],
            evaluationScope=report["evaluationScope"],
        )
    finally:
        if run_id and not args.keep_sandbox:
            try:
                sandbox.cleanup(owner, run_id, confirm_text=DELETE_CONFIRMATION)
            except Exception as exc:
                _progress("cleanup_failed", errorType=type(exc).__name__)
        sandbox.close()
    return 0 if run_passed else 1


def _load_prepared(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("--prepared must be a readable UTF-8 JSON file") from exc
    if not isinstance(value, dict):
        raise SystemExit("--prepared must contain an object")
    manifest = value.get("manifest")
    if not isinstance(manifest, Mapping) or manifest.get("system") != "knowledge":
        raise SystemExit("--prepared must be a Knowledge benchmark")
    if not isinstance(value.get("documents"), list) or not value["documents"]:
        raise SystemExit("--prepared must materialize documents")
    if not isinstance(value.get("cases"), list) or not value["cases"]:
        raise SystemExit("--prepared must materialize cases")
    return value


def _selected_cases(
    cases: list[dict[str, Any]],
    *,
    limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    if limit < 0:
        raise SystemExit("--max-cases-per-split must not be negative")
    selected: list[dict[str, Any]] = []
    for split in ("train", "validation", "held_out"):
        split_cases = [item for item in cases if item.get("split") == split]
        if not limit or len(split_cases) <= limit:
            selected.extend(split_cases)
            continue
        strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in split_cases:
            strata[str(item.get("slice") or item.get("questionType") or "unknown")].append(item)
        for name in strata:
            strata[name].sort(
                key=lambda item: _sha256(f"{seed}\0{split}\0{item['queryId']}")
            )
        allocations = _proportional_allocations(
            {name: len(items) for name, items in strata.items()},
            limit,
        )
        for name, items in sorted(strata.items()):
            selected.extend(items[: allocations[name]])
    return sorted(selected, key=lambda item: str(item["queryId"]))


def _proportional_allocations(counts: dict[str, int], limit: int) -> dict[str, int]:
    if limit < len(counts):
        ordered = sorted(counts, key=lambda name: (-counts[name], name))
        return {name: int(name in ordered[:limit]) for name in counts}
    total = sum(counts.values())
    allocations = {name: min(1, count) for name, count in counts.items()}
    remaining = limit - sum(allocations.values())
    ideals = {
        name: max(0.0, limit * count / total - allocations[name])
        for name, count in counts.items()
    }
    while remaining > 0:
        candidates = [
            name for name in counts if allocations[name] < counts[name]
        ]
        if not candidates:
            break
        name = max(
            candidates,
            key=lambda item: (
                ideals[item] - max(0, allocations[item] - 1),
                counts[item] - allocations[item],
                item,
            ),
        )
        allocations[name] += 1
        remaining -= 1
    return allocations


def _selected_documents(
    documents: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    distractor_limit: int,
    seed: str,
) -> list[dict[str, Any]]:
    if distractor_limit < 0:
        raise SystemExit("--distractor-limit must not be negative")
    by_id = {str(item.get("documentId") or ""): item for item in documents}
    if len(by_id) != len(documents) or "" in by_id:
        raise SystemExit("prepared documents must have unique documentId values")
    if distractor_limit == 0:
        return [by_id[document_id] for document_id in sorted(by_id)]
    relevant_ids = {
        str(document_id)
        for case in cases
        for document_id in dict(case.get("relevant") or {})
    }
    unknown = relevant_ids - by_id.keys()
    if unknown:
        raise SystemExit(f"selected cases reference missing documents: {sorted(unknown)[:3]}")
    distractors = sorted(
        (document_id for document_id in by_id if document_id not in relevant_ids),
        key=lambda document_id: _sha256(f"{seed}\0document\0{document_id}"),
    )[:distractor_limit]
    selected_ids = relevant_ids | set(distractors)
    return [by_id[document_id] for document_id in sorted(selected_ids)]


def _slice_manifest(
    parent: dict[str, Any],
    *,
    cases: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    seed: str,
) -> dict[str, Any]:
    splits = {
        split: sorted(
            str(item["queryId"])
            for item in cases
            if item.get("split") == split
        )
        for split in ("train", "validation", "held_out")
    }
    material = {
        "parentBenchmarkId": parent["benchmarkId"],
        "parentSourceSha256": parent["sourceSha256"],
        "seed": seed,
        "splits": splits,
        "documentIds": [str(item["documentId"]) for item in documents],
    }
    return validate_dataset_manifest(
        {
            "schemaVersion": parent["schemaVersion"],
            "benchmarkId": f"{parent['benchmarkId']}-local-slice-{_sha256_json(material)[:10]}",
            "system": "knowledge",
            "tool": "knowledge",
            "sourceUrl": parent["sourceUrl"],
            "version": f"{parent['version']}; local-slice:{_sha256_json(material)[:12]}",
            "sourceSha256": _sha256_json(material),
            "licenseReference": parent["licenseReference"],
            "corpusIncluded": False,
            "splits": splits,
        }
    )


def _rerank_candidate_configs(
    bases: tuple[dict[str, object], ...],
    *,
    reranker: MlxQwen3KnowledgeReranker,
    candidate_depth: int,
    final_depth: int,
) -> list[dict[str, object]]:
    bounded_candidates = max(2, min(100, int(candidate_depth)))
    bounded_final = max(1, min(20, int(final_depth), bounded_candidates))
    status = reranker.status()
    return [
        {
            **dict(base),
            "topK": bounded_final,
            "rerankEnabled": True,
            "rerankProvider": str(status["provider"]),
            "rerankerModelReference": str(status["modelReference"]),
            "rerankerFingerprint": str(status["fingerprint"]),
            "rerankCandidateDepth": bounded_candidates,
            "rerankFinalDepth": bounded_final,
            "rerankDiversityKey": "externalDocumentId",
            "rerankMaxChunksPerDocument": 1,
            "rerankMaxLength": int(status["maxLength"]),
            "rerankInstructionSha256": str(status["instructionSha256"]),
        }
        for base in bases
    ]


def _embedding_environment(args: argparse.Namespace) -> dict[str, str]:
    result = {
        "RAG_IME_EMBEDDING_PROVIDER": str(args.embedding_provider),
        "RAG_IME_EMBEDDING_DIMENSIONS": str(args.embedding_dimensions),
        "RAG_IME_EMBEDDING_BITS": str(args.embedding_bits),
        "RAG_IME_EMBEDDING_GROUP_SIZE": str(args.embedding_group_size),
        "RAG_IME_KNOWLEDGE_DENSE_BACKEND": str(args.dense_backend),
        "RAG_IME_EMBEDDING_BATCH_SIZE": "32",
    }
    optional = {
        "RAG_IME_EMBEDDING_MODEL": args.embedding_model,
        "RAG_IME_EMBEDDING_QUERY_PREFIX": args.embedding_query_prefix,
        "RAG_IME_EMBEDDING_DOCUMENT_PREFIX": args.embedding_document_prefix,
    }
    result.update({key: str(value) for key, value in optional.items() if value})
    return result


def _require_actual_metal_runtime() -> None:
    """Check one real MLX device operation before loading a native model."""

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


def _require_semantic_dense_runtime(
    *,
    provider: Mapping[str, object],
    status: Mapping[str, object],
    requested_backend: str,
) -> dict[str, object]:
    """Fail closed before scoring a requested semantic retrieval run."""

    dense = status.get("dense")
    bases = status.get("bases")
    if not isinstance(dense, Mapping) or not isinstance(bases, list):
        raise SystemExit("semantic dense runtime is not ready: status is incomplete")
    chunk_count = sum(
        int(base.get("chunkCount") or 0)
        for base in bases
        if isinstance(base, Mapping)
    )
    vector_count = int(dense.get("vectorCount") or 0)
    semantic = provider.get("semantic") is True
    effective_backend = str(dense.get("backend") or "")
    requested = str(requested_backend or "").strip().lower()
    reasons: list[str] = []
    if semantic:
        if dense.get("available") is not True:
            reasons.append("dense backend unavailable")
        if dense.get("degraded") is True:
            reasons.append("dense backend degraded")
        if chunk_count <= 0:
            reasons.append("knowledge import produced no chunks")
        if vector_count != chunk_count:
            reasons.append(
                f"vector coverage {vector_count}/{chunk_count} does not match imported chunks"
            )
        if requested in {"usearch", "hnsw", "usearch-hnsw"} and effective_backend != "usearch":
            reasons.append(
                f"requested usearch but runtime selected {effective_backend or 'none'}"
            )
    if reasons:
        detail = str(dense.get("reason") or "").strip()
        suffix = f" ({detail})" if detail else ""
        raise SystemExit(
            "semantic dense runtime is not ready: " + "; ".join(reasons) + suffix
        )
    return {
        "semanticRequired": semantic,
        "accepted": True,
        "requestedBackend": requested,
        "effectiveBackend": effective_backend,
        "chunkCount": chunk_count,
        "vectorCount": vector_count,
        "vectorCoverage": (
            vector_count / chunk_count
            if chunk_count > 0
            else 0.0
        ),
    }


def _reranker_acceptance_passes(status: Mapping[str, object]) -> bool:
    calls = int(status.get("calls") or 0)
    scored_pairs = int(status.get("scoredPairs") or 0)
    cache_hits = int(status.get("cacheHits") or 0)
    loaded_entries = int(status.get("persistentCacheLoadedEntries") or 0)
    cache_entries = int(status.get("scoreCacheEntries") or 0)
    observed_scores = scored_pairs > 0 or (
        cache_hits > 0
        and loaded_entries > 0
        and cache_entries >= loaded_entries
    )
    return (
        status.get("configured") is True
        and calls > 0
        and observed_scores
        and int(status.get("errorCount") or 0) == 0
        and int(status.get("fallbackCount") or 0) == 0
    )


def _metric_deltas(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, dict[str, float | None]]:
    baseline_values = _flat_metrics(baseline)
    optimized_values = _flat_metrics(optimized)
    return {
        key: {
            "baseline": baseline_values[key],
            "optimized": optimized_values[key],
            "absoluteDelta": optimized_values[key] - baseline_values[key],
            "relativeDelta": (
                (optimized_values[key] - baseline_values[key]) / baseline_values[key]
                if baseline_values[key] != 0
                else None
            ),
        }
        for key in baseline_values
    }


def _selection_candidate(
    selection: Mapping[str, object],
    config: Mapping[str, object],
) -> dict[str, object]:
    target_sha256 = _sha256_json(dict(config))
    candidates = selection.get("candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if (
                isinstance(item, Mapping)
                and str(item.get("configSha256") or "") == target_sha256
            ):
                return dict(item)
    raise RuntimeError(f"validation selection omitted required baseline {target_sha256}")


def _selection_metric_deltas(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, dict[str, float | None]]:
    baseline_validation = baseline.get("validation")
    optimized_validation = optimized.get("validation")
    if not isinstance(baseline_validation, Mapping) or not isinstance(
        optimized_validation,
        Mapping,
    ):
        raise ValueError("validation selection metrics are missing")
    return _metric_deltas(
        {"metrics": baseline_validation},
        {"metrics": optimized_validation},
    )


def _flat_metrics(report: Mapping[str, object]) -> dict[str, float]:
    outer = report.get("metrics")
    metrics = outer.get("metrics") if isinstance(outer, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise ValueError("retrieval report metrics are missing")
    recall = metrics.get("recallAtK")
    ndcg = metrics.get("ndcgAtK")
    if not isinstance(recall, Mapping) or not isinstance(ndcg, Mapping):
        raise ValueError("retrieval report K metrics are missing")
    return {
        **{f"recallAt{key}": float(value) for key, value in recall.items()},
        "mrr": float(metrics["mrr"]),
        **{f"ndcgAt{key}": float(value) for key, value in ndcg.items()},
    }


def _progress(event: str, **payload: object) -> None:
    print(
        json.dumps({"event": event, **payload}, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
