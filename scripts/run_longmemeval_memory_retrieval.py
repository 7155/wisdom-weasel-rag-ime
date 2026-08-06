#!/usr/bin/env python3
"""Run a local-only LongMemEval retrieval experiment through Memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
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
from rag_ime.longmemeval_memory_retrieval import LongMemEvalMemoryIndex  # noqa: E402
from rag_ime.rag_benchmark import (  # noqa: E402
    select_validation_config,
    validate_dataset_manifest,
)
from rag_ime.rag_retrieval_experiment import (  # noqa: E402
    deterministic_query_plan,
    evaluate_retrieval_configuration,
)


BASELINE_CONFIG: dict[str, object] = {
    "granularity": "session",
    "mode": "lexical",
    "topK": 10,
    "threshold": 0.0,
    "lexicalWeight": 1.0,
    "denseWeight": 1.0,
    "metadataEnabled": False,
    "metadataWeight": 0.5,
}


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prepared",
        type=Path,
        default=(
            ROOT
            / ".rag-ime-data"
            / "prepared"
            / "rag-interview"
            / "longmemeval-s-cleaned.prepared.json"
        ),
    )
    parser.add_argument(
        "--sandbox-root",
        type=Path,
        default=ROOT / ".rag-ime-data" / "runs" / "memory-retrieval",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / ".rag-ime-data"
            / "results"
            / "rag-interview"
            / "longmemeval-memory-retrieval.json"
        ),
    )
    parser.add_argument("--seed", default="paw-longmemeval-retrieval-v1")
    parser.add_argument("--max-cases-per-split", type=int, default=14)
    parser.add_argument(
        "--evaluation-profile",
        choices=("official-user", "product-all-turn"),
        default="official-user",
        help=(
            "official-user reproduces the public retrieval corpus/qrel filter; "
            "product-all-turn separately diagnoses assistant-side Memory"
        ),
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("none", "local-hash", "mlx-bert", "sentence-transformers"),
        default="none",
    )
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--embedding-dimensions", type=int, default=96)
    parser.add_argument("--embedding-query-prefix", default="")
    parser.add_argument("--embedding-document-prefix", default="")
    parser.add_argument("--embedding-bits", type=int, default=8)
    parser.add_argument("--embedding-group-size", type=int, default=32)
    parser.add_argument("--skip-turn-index", action="store_true")
    parser.add_argument("--skip-vectors", action="store_true")
    parser.add_argument("--keep-sandbox", action="store_true")
    args = parser.parse_args(argv)

    prepared_path = args.prepared.expanduser().resolve(strict=True)
    prepared = _load_prepared(prepared_path)
    evaluation_profile = str(args.evaluation_profile)
    profile_cases = _cases_for_profile(
        list(prepared["cases"]),
        evaluation_profile=evaluation_profile,
    )
    selected_cases = select_balanced_cases(
        profile_cases,
        limit_per_split=int(args.max_cases_per_split),
        seed=str(args.seed),
    )
    validation_cases = [
        case
        for case in selected_cases
        if case.get("split") == "validation"
        and case.get("retrievalEvaluable") is not False
    ]
    held_out_cases = [
        case
        for case in selected_cases
        if case.get("split") == "held_out"
        and case.get("retrievalEvaluable") is not False
    ]
    if not validation_cases or not held_out_cases:
        raise SystemExit("selected Memory slice requires answerable validation and held-out cases")
    retrieval_manifest = _retrieval_slice_manifest(
        dict(prepared["manifest"]),
        validation_cases=validation_cases,
        held_out_cases=held_out_cases,
        seed=str(args.seed),
        evaluation_profile=evaluation_profile,
    )

    embedding_environment = _embedding_environment(args)
    provider = embedding_provider_from_env(embedding_environment)
    provider_public = embedding_provider_info(provider)
    vectors_requested = (
        not bool(args.skip_vectors)
        and str(getattr(provider, "fingerprint", "none")) != "none"
    )
    candidate_configs = _candidate_configs(
        include_turn=not bool(args.skip_turn_index),
        include_dense=vectors_requested,
    )

    sandbox_root = args.sandbox_root.expanduser().resolve(strict=False)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="memory-run-", dir=str(sandbox_root))
    ).resolve(strict=True)
    started_at_ms = int(time.time() * 1_000)
    index: LongMemEvalMemoryIndex | None = None
    report: dict[str, Any] | None = None
    run_root_bytes = 0
    cleanup = {
        "requested": not bool(args.keep_sandbox),
        "passed": False,
        "runRootExistsAfter": True,
        "bytesBefore": 0,
    }
    try:
        index = LongMemEvalMemoryIndex(
            run_root / "memory.sqlite",
            embedding_provider=provider,
        )
        _progress(
            "build_started",
            cases=len(selected_cases),
            provider=provider_public,
            vectorsRequested=vectors_requested,
        )
        build = index.build(
            selected_cases,
            include_turn_index=not bool(args.skip_turn_index),
            build_vectors=vectors_requested,
            content_profile=evaluation_profile,
        )
        _progress(
            "build_completed",
            sessionDocuments=build["sessionDocuments"],
            turnDocuments=build["turnDocuments"],
            vectors=build["vectors"],
        )

        def retrieve(query: dict[str, object], config: dict[str, Any]) -> list[str]:
            assert index is not None
            result = index.retrieve(
                query_id=str(query["queryId"]),
                query_text=str(query["text"]),
                config=config,
            )
            return list(result["sessionIds"])

        selection = select_validation_config(
            manifest=retrieval_manifest,
            validation_cases=validation_cases,
            candidate_configs=candidate_configs,
            retrieve=retrieve,
            objective="ndcgAtK.10",
            k_values=(1, 3, 5, 10),
        )
        winner = dict(selection["winner"]["config"])
        _progress(
            "validation_selected",
            frozenConfigSha256=selection["frozenConfigSha256"],
            winner=winner,
        )
        baseline = evaluate_retrieval_configuration(
            cases=held_out_cases,
            config=BASELINE_CONFIG,
            retrieve=retrieve,
        )
        tuned = evaluate_retrieval_configuration(
            cases=held_out_cases,
            config=winner,
            retrieve=retrieve,
        )
        deterministic_multi_query = evaluate_retrieval_configuration(
            cases=held_out_cases,
            config=winner,
            retrieve=retrieve,
            query_planner=deterministic_query_plan,
            max_queries_per_case=3,
        )
        abstention = _evaluate_abstention(
            index,
            selected_cases,
            winner,
        )
        boundary = index.boundary_receipt()
        completed_at_ms = int(time.time() * 1_000)
        comparison = {
            "baselineToTuned": _metric_deltas(baseline, tuned),
            "baselineToDeterministicMultiQuery": _metric_deltas(
                baseline,
                deterministic_multi_query,
            ),
        }
        quality_non_regression = (
            _metric_value(tuned, "mrr") + 1e-12 >= _metric_value(baseline, "mrr")
            and _metric_value(tuned, "ndcgAtK", "10") + 1e-12
            >= _metric_value(baseline, "ndcgAtK", "10")
        )
        report = {
            "schemaVersion": "rag-ime.longmemeval-memory-retrieval-run.v2",
            "status": "completed",
            "localOnly": True,
            "uploaded": False,
            "system": "memory",
            "tool": "memory",
            "evaluationProfile": evaluation_profile,
            "startedAtMs": started_at_ms,
            "completedAtMs": completed_at_ms,
            "elapsedMs": completed_at_ms - started_at_ms,
            "dataset": {
                "parent": prepared["manifest"],
                "retrievalSlice": retrieval_manifest,
                "sourcePreparedSha256": _file_sha256(prepared_path),
                "adapter": prepared.get("adapter") or {},
                "selectedCaseCount": len(selected_cases),
                "selectedCounts": _selected_counts(selected_cases),
                "retrievalDenominator": {
                    "validation": len(validation_cases),
                    "heldOut": len(held_out_cases),
                    "abstentionExcludedFromLocationRecall": True,
                    "qrels": (
                        "user-side-has_answer"
                        if evaluation_profile == "official-user"
                        else "answer_session_ids"
                    ),
                    "indexedContent": (
                        "user-turns-only"
                        if evaluation_profile == "official-user"
                        else "user-and-assistant-turns"
                    ),
                },
            },
            "embedding": {
                **provider_public,
                "vectorsRequested": vectors_requested,
                "configuredDimensions": int(args.embedding_dimensions),
                "queryPrefix": str(args.embedding_query_prefix),
                "documentPrefix": str(args.embedding_document_prefix),
                "bits": int(args.embedding_bits),
                "groupSize": int(args.embedding_group_size),
            },
            "indexBuild": build,
            "validationSelection": selection,
            "heldOut": {
                "baseline": baseline,
                "tuned": tuned,
                "deterministicMultiQueryDiagnostic": deterministic_multi_query,
            },
            "abstention": abstention,
            "comparison": comparison,
            "hardGates": {
                "memoryKnowledgeBoundary": bool(boundary["passed"]),
                "heldOutLabelsHiddenDuringSelection": not bool(
                    selection["heldOutLabelsObserved"]
                ),
                "splitOverlap": _split_overlap(retrieval_manifest) == 0,
                "qualityNonRegression": quality_non_regression,
                "vectorCoverage": (
                    not vectors_requested
                    or int(build["vectors"]["documents"])
                    == int(build["vectorEligibleDocuments"])
                ),
                "evaluationProfileBound": (
                    build.get("contentProfile") == evaluation_profile
                    and all(
                        case.get("evaluationProfile") == evaluation_profile
                        for case in selected_cases
                    )
                ),
            },
            "boundary": boundary,
            "scopeWarnings": [
                "This is a local retrieval-only LongMemEval-S slice, not an official QA leaderboard submission.",
                "The official protocol excludes abstention cases from answer-location recall; refusal is reported separately.",
                (
                    "The official-user arm indexes only user turns and excludes cases without a user-side has_answer target, matching the public retrieval runner."
                    if evaluation_profile == "official-user"
                    else "The product-all-turn arm includes assistant turns and answer_session_ids qrels; it is a product diagnostic and is not public-retrieval comparable."
                ),
                "Session and turn projections are benchmark-only Memory Books in an isolated SQLite root and are never applied to personal Memory.",
                "The deterministic multi-query arm is an offline diagnostic; it is not the Luna Agentic lane.",
            ],
        }
    finally:
        if index is not None:
            index.close()
        run_root_bytes = _directory_bytes(run_root)
        cleanup["bytesBefore"] = run_root_bytes
        if args.keep_sandbox:
            cleanup["passed"] = True
            cleanup["runRootExistsAfter"] = run_root.exists()
            cleanup["retainedRunRoot"] = str(run_root)
        else:
            _safe_cleanup(run_root, sandbox_root)
            cleanup["runRootExistsAfter"] = run_root.exists()
            cleanup["passed"] = not run_root.exists()

    if report is None:
        raise SystemExit("LongMemEval Memory report was not produced")
    report["sandbox"] = cleanup
    report["hardGates"]["sandboxCleanup"] = bool(cleanup["passed"])
    report["passed"] = all(bool(value) for value in report["hardGates"].values())
    report["reportSha256"] = _sha256_json(report)
    output = args.output.expanduser().resolve(strict=False)
    _write_json(output, report)
    _progress(
        "completed",
        output=str(output),
        passed=report["passed"],
        reportSha256=report["reportSha256"],
        comparison=report["comparison"],
        sandbox=cleanup,
    )
    return 0 if report["passed"] else 2


def select_balanced_cases(
    cases: list[dict[str, Any]],
    *,
    limit_per_split: int,
    seed: str,
) -> list[dict[str, Any]]:
    if limit_per_split < 0:
        raise ValueError("limit_per_split must not be negative")
    selected: list[dict[str, Any]] = []
    for split in ("validation", "held_out"):
        split_cases = [case for case in cases if case.get("split") == split]
        if not split_cases:
            raise ValueError(f"LongMemEval {split} split must not be empty")
        if limit_per_split == 0 or len(split_cases) <= limit_per_split:
            selected.extend(split_cases)
            continue
        strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in split_cases:
            strata[str(case.get("slice") or "unspecified")].append(case)
        for name, values in strata.items():
            values.sort(
                key=lambda case: _sha256(
                    f"{seed}\0{split}\0{name}\0{case['queryId']}"
                )
            )
        allocations = _proportional_allocations(
            {name: len(values) for name, values in strata.items()},
            limit_per_split,
        )
        for name, values in sorted(strata.items()):
            selected.extend(values[: allocations[name]])
    return sorted(selected, key=lambda case: (str(case["split"]), str(case["queryId"])))


def _cases_for_profile(
    cases: list[dict[str, Any]],
    *,
    evaluation_profile: str,
) -> list[dict[str, Any]]:
    if evaluation_profile == "official-user":
        relevant_field = "officialRelevant"
        evaluable_field = "officialRetrievalEvaluable"
    elif evaluation_profile == "product-all-turn":
        relevant_field = "productRelevant"
        evaluable_field = "productRetrievalEvaluable"
    else:
        raise ValueError("unknown LongMemEval evaluation profile")

    projected: list[dict[str, Any]] = []
    for raw_case in cases:
        if relevant_field not in raw_case or evaluable_field not in raw_case:
            raise ValueError(
                "prepared LongMemEval data predates explicit retrieval profiles; "
                "rerun scripts/prepare_longmemeval_benchmark.py"
            )
        abstention = bool(raw_case.get("abstention"))
        evaluable = bool(raw_case.get(evaluable_field))
        if not abstention and not evaluable:
            continue
        relevant = raw_case.get(relevant_field)
        if not isinstance(relevant, Mapping):
            raise ValueError(f"{relevant_field} must be an object")
        case = dict(raw_case)
        case["evaluationProfile"] = evaluation_profile
        case["retrievalEvaluable"] = evaluable
        case["relevant"] = dict(relevant) if evaluable else {}
        projected.append(case)
    if not projected:
        raise ValueError("LongMemEval evaluation profile selected no cases")
    return projected


def _evaluate_abstention(
    index: LongMemEvalMemoryIndex,
    cases: list[dict[str, Any]],
    config: Mapping[str, object],
) -> dict[str, Any]:
    rows: list[dict[str, object]] = []
    for case in cases:
        result = index.retrieve(
            query_id=str(case["queryId"]),
            query_text=str(case["question"]),
            config={**dict(config), "threshold": 0.0},
        )
        rows.append(
            {
                "queryId": str(case["queryId"]),
                "split": str(case["split"]),
                "abstention": bool(case.get("abstention")),
                "hasHits": bool(result["sessionIds"]),
                "topScore": float(result["topScore"]),
            }
        )
    validation = [row for row in rows if row["split"] == "validation"]
    held_out = [row for row in rows if row["split"] == "held_out"]
    threshold, validation_metrics = _select_abstention_threshold(validation)
    held_out_metrics = _abstention_metrics(held_out, threshold)
    return {
        "schemaVersion": "rag-ime.longmemeval-abstention-eval.v1",
        "selectionSplit": "validation",
        "acceptanceSplit": "held_out",
        "threshold": threshold,
        "validation": validation_metrics,
        "heldOut": held_out_metrics,
        "privateCases": rows,
    }


def _select_abstention_threshold(
    rows: list[dict[str, object]],
) -> tuple[float, dict[str, object]]:
    if not rows or not any(bool(row["abstention"]) for row in rows):
        raise ValueError("validation abstention calibration requires abstention cases")
    scores = sorted({float(row["topScore"]) for row in rows})
    candidates = [0.0]
    candidates.extend((left + right) / 2.0 for left, right in zip(scores, scores[1:]))
    candidates.append((scores[-1] if scores else 0.0) + 1e-12)
    best_threshold = candidates[0]
    best_metrics = _abstention_metrics(rows, best_threshold)
    for threshold in candidates[1:]:
        metrics = _abstention_metrics(rows, threshold)
        key = (
            float(metrics["balancedAccuracy"]),
            float(metrics["abstentionF1"]),
            float(metrics["accuracy"]),
            -threshold,
        )
        best_key = (
            float(best_metrics["balancedAccuracy"]),
            float(best_metrics["abstentionF1"]),
            float(best_metrics["accuracy"]),
            -best_threshold,
        )
        if key > best_key:
            best_threshold = threshold
            best_metrics = metrics
    return best_threshold, best_metrics


def _abstention_metrics(
    rows: list[dict[str, object]],
    threshold: float,
) -> dict[str, object]:
    true_abstention = false_abstention = true_answerable = false_answerable = 0
    for row in rows:
        predicts_answerable = bool(row["hasHits"]) and float(row["topScore"]) >= threshold
        is_abstention = bool(row["abstention"])
        if is_abstention and not predicts_answerable:
            true_abstention += 1
        elif is_abstention:
            false_answerable += 1
        elif predicts_answerable:
            true_answerable += 1
        else:
            false_abstention += 1
    total = len(rows)
    abstention_precision = true_abstention / max(1, true_abstention + false_abstention)
    abstention_recall = true_abstention / max(1, true_abstention + false_answerable)
    answerable_recall = true_answerable / max(1, true_answerable + false_abstention)
    return {
        "caseCount": total,
        "abstentionCount": sum(bool(row["abstention"]) for row in rows),
        "answerableCount": sum(not bool(row["abstention"]) for row in rows),
        "accuracy": (true_abstention + true_answerable) / max(1, total),
        "balancedAccuracy": (abstention_recall + answerable_recall) / 2.0,
        "abstentionPrecision": abstention_precision,
        "abstentionRecall": abstention_recall,
        "abstentionF1": (
            2 * abstention_precision * abstention_recall
            / max(1e-12, abstention_precision + abstention_recall)
        ),
        "answerableRecall": answerable_recall,
        "confusion": {
            "trueAbstention": true_abstention,
            "falseAbstention": false_abstention,
            "trueAnswerable": true_answerable,
            "falseAnswerable": false_answerable,
        },
    }


def _candidate_configs(*, include_turn: bool, include_dense: bool) -> list[dict[str, object]]:
    candidates = [dict(BASELINE_CONFIG)]
    if include_turn:
        candidates.extend(
            [
                {**BASELINE_CONFIG, "granularity": "turn"},
                {
                    **BASELINE_CONFIG,
                    "granularity": "turn",
                    "metadataEnabled": True,
                    "metadataWeight": 0.5,
                },
                {
                    **BASELINE_CONFIG,
                    "granularity": "session_turn",
                    "sessionWeight": 1.0,
                    "turnWeight": 1.0,
                    "fusionRrfK": 60,
                    "candidateMultiplier": 2,
                },
                {
                    **BASELINE_CONFIG,
                    "granularity": "session_turn",
                    "sessionWeight": 2.0,
                    "turnWeight": 1.0,
                    "fusionRrfK": 60,
                    "candidateMultiplier": 2,
                },
                {
                    **BASELINE_CONFIG,
                    "granularity": "session_turn",
                    "sessionWeight": 3.0,
                    "turnWeight": 1.0,
                    "fusionRrfK": 60,
                    "candidateMultiplier": 2,
                },
            ]
        )
    if include_dense:
        candidates.extend(
            [
                {**BASELINE_CONFIG, "mode": "dense"},
                {**BASELINE_CONFIG, "mode": "hybrid"},
                {
                    **BASELINE_CONFIG,
                    "mode": "hybrid",
                    "lexicalWeight": 0.5,
                    "denseWeight": 1.5,
                },
                {
                    **BASELINE_CONFIG,
                    "mode": "hybrid",
                    "lexicalWeight": 1.5,
                    "denseWeight": 0.5,
                },
            ]
        )
        if include_turn:
            candidates.extend(
                [
                    {
                        **BASELINE_CONFIG,
                        "granularity": "turn",
                        "mode": "dense",
                    },
                    {
                        **BASELINE_CONFIG,
                        "granularity": "turn",
                        "mode": "hybrid",
                    },
                    {
                        **BASELINE_CONFIG,
                        "granularity": "session_turn",
                        "mode": "dense",
                        "sessionWeight": 3.0,
                        "turnWeight": 1.0,
                        "fusionRrfK": 60,
                        "candidateMultiplier": 2,
                    },
                    {
                        **BASELINE_CONFIG,
                        "granularity": "session_turn",
                        "mode": "hybrid",
                        "sessionWeight": 3.0,
                        "turnWeight": 1.0,
                        "fusionRrfK": 60,
                        "candidateMultiplier": 2,
                    },
                ]
            )
    return candidates


def _retrieval_slice_manifest(
    parent: dict[str, Any],
    *,
    validation_cases: list[dict[str, Any]],
    held_out_cases: list[dict[str, Any]],
    seed: str,
    evaluation_profile: str,
) -> dict[str, Any]:
    splits = {
        "train": [],
        "validation": sorted(str(case["queryId"]) for case in validation_cases),
        "held_out": sorted(str(case["queryId"]) for case in held_out_cases),
    }
    material = {
        "parentBenchmarkId": parent["benchmarkId"],
        "parentSourceSha256": parent["sourceSha256"],
        "seed": seed,
        "splits": splits,
        "abstentionExcluded": True,
        "evaluationProfile": evaluation_profile,
    }
    token = _sha256_json(material)[:12]
    return validate_dataset_manifest(
        {
            "schemaVersion": parent["schemaVersion"],
            "benchmarkId": f"{parent['benchmarkId']}-retrieval-{token}",
            "system": "memory",
            "tool": "memory",
            "sourceUrl": parent["sourceUrl"],
            "version": f"{parent['version']}; retrieval-slice:{token}",
            "sourceSha256": parent["sourceSha256"],
            "licenseReference": parent["licenseReference"],
            "corpusIncluded": False,
            "splits": splits,
        }
    )


def _load_prepared(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("--prepared must be readable UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SystemExit("--prepared must contain an object")
    manifest = value.get("manifest")
    if not isinstance(manifest, Mapping) or manifest.get("system") != "memory":
        raise SystemExit("--prepared must contain a Memory benchmark")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("--prepared must materialize Memory cases")
    return value


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
        candidates = [name for name in counts if allocations[name] < counts[name]]
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


def _embedding_environment(args: argparse.Namespace) -> dict[str, str]:
    return {
        "RAG_IME_EMBEDDING_PROVIDER": str(args.embedding_provider),
        "RAG_IME_EMBEDDING_MODEL": str(args.embedding_model),
        "RAG_IME_EMBEDDING_DIMENSIONS": str(args.embedding_dimensions),
        "RAG_IME_EMBEDDING_QUERY_PREFIX": str(args.embedding_query_prefix),
        "RAG_IME_EMBEDDING_DOCUMENT_PREFIX": str(args.embedding_document_prefix),
        "RAG_IME_EMBEDDING_BITS": str(args.embedding_bits),
        "RAG_IME_EMBEDDING_GROUP_SIZE": str(args.embedding_group_size),
        "RAG_IME_EMBEDDING_CACHE_SIZE": "64",
    }


def _selected_counts(cases: list[dict[str, Any]]) -> dict[str, object]:
    by_split: dict[str, int] = defaultdict(int)
    by_slice: dict[str, int] = defaultdict(int)
    for case in cases:
        by_split[str(case["split"])] += 1
        by_slice[f"{case['split']}:{case.get('slice') or 'unspecified'}"] += 1
    return {
        "bySplit": dict(sorted(by_split.items())),
        "bySplitAndSlice": dict(sorted(by_slice.items())),
    }


def _split_overlap(manifest: Mapping[str, object]) -> int:
    splits = manifest.get("splits")
    if not isinstance(splits, Mapping):
        return 1
    owners: dict[str, str] = {}
    overlap = 0
    for split, values in splits.items():
        for query_id in values if isinstance(values, list) else []:
            text = str(query_id)
            if text in owners and owners[text] != split:
                overlap += 1
            owners[text] = str(split)
    return overlap


def _metric_deltas(
    baseline: Mapping[str, object],
    optimized: Mapping[str, object],
) -> dict[str, dict[str, float | None]]:
    before = _flat_metrics(baseline)
    after = _flat_metrics(optimized)
    return {
        key: {
            "baseline": before[key],
            "optimized": after[key],
            "absoluteDelta": after[key] - before[key],
            "relativeDelta": (
                (after[key] - before[key]) / before[key]
                if before[key] != 0
                else None
            ),
        }
        for key in before
    }


def _flat_metrics(report: Mapping[str, object]) -> dict[str, float]:
    outer = report.get("metrics")
    metrics = outer.get("metrics") if isinstance(outer, Mapping) else None
    if not isinstance(metrics, Mapping):
        raise ValueError("retrieval metrics are missing")
    recall = metrics.get("recallAtK")
    ndcg = metrics.get("ndcgAtK")
    if not isinstance(recall, Mapping) or not isinstance(ndcg, Mapping):
        raise ValueError("retrieval K metrics are missing")
    return {
        **{f"recallAt{key}": float(value) for key, value in recall.items()},
        "mrr": float(metrics["mrr"]),
        **{f"ndcgAt{key}": float(value) for key, value in ndcg.items()},
    }


def _metric_value(report: Mapping[str, object], family: str, key: str = "") -> float:
    metrics_outer = report.get("metrics")
    metrics = metrics_outer.get("metrics") if isinstance(metrics_outer, Mapping) else None
    if not isinstance(metrics, Mapping):
        return 0.0
    value = metrics.get(family)
    if key:
        return float(value.get(key) or 0.0) if isinstance(value, Mapping) else 0.0
    return float(value or 0.0)


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _safe_cleanup(run_root: Path, sandbox_root: Path) -> None:
    resolved_run = run_root.resolve(strict=True)
    resolved_sandbox = sandbox_root.resolve(strict=True)
    if resolved_run.parent != resolved_sandbox or not resolved_run.name.startswith(
        "memory-run-"
    ):
        raise RuntimeError("refusing to clean a path outside the Memory benchmark sandbox")
    shutil.rmtree(resolved_run)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _progress(event: str, **payload: object) -> None:
    print(
        json.dumps({"event": event, **payload}, ensure_ascii=False, sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
