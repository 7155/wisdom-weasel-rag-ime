from __future__ import annotations

import hashlib
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass

from .embeddings import EmbeddingProvider
from .hybrid_rag_models import HybridRagHit, HybridRagQuery
from .hybrid_rag_ranker import (
    DEFAULT_METADATA_FAMILY_FUSION,
    DEFAULT_QUERY_COVERAGE_WEIGHT,
    DEFAULT_RRF_K,
    LANE_WEIGHTS,
    METADATA_FAMILY_LANES,
    MetadataFamilyFusionConfig,
    rank_hybrid_hits_to_memory_hits,
)
from .hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from .memory_evidence_policy import memory_evidence_exclusion_reason
from .memory_ingest import looks_sensitive, normalize_text
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace


REFERENCE_PROFILE = "pre-tuning-20260722"
REFERENCE_LANE_WEIGHTS = {
    "bm25_raw": 1.00,
    "bm25_tags": 1.15,
    "vector_raw": 0.95,
    "vector_tag_boost": 1.05,
    "tagmemo": 1.10,
    "time": 0.90,
    "feedback": 1.20,
}
REFERENCE_METADATA_FUSION = MetadataFamilyFusionConfig(
    max_multiplier=1.20,
    secondary_weight=0.15,
    tertiary_weight=0.05,
)
REFERENCE_RRF_K = 60
REFERENCE_QUERY_COVERAGE_WEIGHT = 0.25
_SUITE_WEIGHTS = {
    "evidence_input": 0.70,
    "metadata_term": 0.20,
    "superseded_value": 0.10,
}


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    key: str
    suite: str
    query_text: str
    expected_doc_ids: frozenset[str]
    split: str


@dataclass(frozen=True)
class PreparedRetrievalCase:
    case: RetrievalEvaluationCase
    hits: tuple[HybridRagHit, ...]
    elapsed_ms: int
    vector_raw_count: int
    vector_tag_count: int


@dataclass(frozen=True)
class RetrievalParameterSet:
    name: str
    lane_weights: tuple[tuple[str, float], ...]
    metadata_fusion: MetadataFamilyFusionConfig
    rrf_k: int = REFERENCE_RRF_K
    query_coverage_weight: float = REFERENCE_QUERY_COVERAGE_WEIGHT

    def weights(self) -> dict[str, float]:
        return dict(self.lane_weights)

    def public_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "laneWeights": {
                key: round(float(value), 6)
                for key, value in self.lane_weights
            },
            "metadataFamily": {
                "maxMultiplier": round(
                    float(self.metadata_fusion.max_multiplier),
                    6,
                ),
                "secondaryWeight": round(
                    float(self.metadata_fusion.secondary_weight),
                    6,
                ),
                "tertiaryWeight": round(
                    float(self.metadata_fusion.tertiary_weight),
                    6,
                ),
            },
            "rrfK": int(self.rrf_k),
            "queryCoverageWeight": round(
                float(self.query_coverage_weight),
                6,
            ),
        }


def evaluate_retrieval_quality(
    conn: sqlite3.Connection,
    *,
    project: str,
    embedding_provider: EmbeddingProvider | None,
    max_cases_per_suite: int = 200,
) -> dict[str, object]:
    cases = build_retrieval_evaluation_cases(
        conn,
        project=project,
        max_cases_per_suite=max_cases_per_suite,
    )
    provider = _provider_gate(conn, embedding_provider)
    prepared, retrieval_safety = _prepare_cases(
        conn,
        cases=cases,
        project=project,
        embedding_provider=embedding_provider,
    )
    baseline = RetrievalParameterSet(
        name=REFERENCE_PROFILE,
        lane_weights=tuple(REFERENCE_LANE_WEIGHTS.items()),
        metadata_fusion=REFERENCE_METADATA_FUSION,
    )
    candidates = _parameter_grid(baseline)
    # This search tunes lexical, vector, and metadata evidence families. Keep
    # age decay out of that comparison: using wall-clock time here made two
    # otherwise identical runs flip between near-tied parameter sets.
    ranking_reference_ms = 0
    baseline_tuning = _score_parameter_set(
        prepared,
        parameters=baseline,
        split="tuning",
        current_ms=ranking_reference_ms,
    )
    baseline_holdout = _score_parameter_set(
        prepared,
        parameters=baseline,
        split="holdout",
        current_ms=ranking_reference_ms,
    )

    best = baseline
    best_tuning = baseline_tuning
    for candidate in candidates:
        if candidate == baseline:
            continue
        scored = _score_parameter_set(
            prepared,
            parameters=candidate,
            split="tuning",
            current_ms=ranking_reference_ms,
        )
        if _parameter_sort_key(scored, candidate) > _parameter_sort_key(
            best_tuning,
            best,
        ):
            best = candidate
            best_tuning = scored

    selected_holdout = _score_parameter_set(
        prepared,
        parameters=best,
        split="holdout",
        current_ms=ranking_reference_ms,
    )
    accepted, reasons = _holdout_gate(
        baseline=baseline_holdout,
        selected=selected_holdout,
        baseline_tuning=baseline_tuning,
        selected_tuning=best_tuning,
        baseline_parameters=baseline,
        selected_parameters=best,
    )
    recommendation = best if accepted else baseline
    recommendation_tuning = best_tuning if accepted else baseline_tuning
    recommendation_holdout = selected_holdout if accepted else baseline_holdout
    runtime_defaults_match = _runtime_defaults_match(recommendation)

    return {
        "evaluationSchemaVersion": "rag-ime.retrieval-quality-eval.v2",
        "referenceProfile": REFERENCE_PROFILE,
        "provider": provider,
        "dataset": _dataset_payload(cases),
        "retrievalExecution": {
            "preparedCases": len(prepared),
            "queriesWithVectorRawHits": sum(
                1 for item in prepared if item.vector_raw_count > 0
            ),
            "queriesWithVectorTagHits": sum(
                1 for item in prepared if item.vector_tag_count > 0
            ),
            "latencyMs": _latency_payload(
                [item.elapsed_ms for item in prepared]
            ),
            "timeLaneEnabled": False,
            "timeDecayEnabled": False,
            "feedbackLaneEnabled": False,
        },
        "safety": retrieval_safety,
        "search": {
            "candidateParameterSets": len(candidates),
            "selectionSplit": "tuning",
            "acceptanceSplit": "holdout",
            "objective": (
                "suite-weighted MRR@10 and Success@5, with a small "
                "correlated-metadata amplification penalty"
            ),
            "holdoutAccepted": accepted,
            "holdoutGateReasons": reasons,
        },
        "baseline": {
            "parameters": baseline.public_payload(),
            "tuning": baseline_tuning,
            "holdout": baseline_holdout,
        },
        "tuningSelected": {
            "parameters": best.public_payload(),
            "tuning": best_tuning,
            "holdout": selected_holdout,
        },
        "recommendation": {
            "parameters": recommendation.public_payload(),
            "tuning": recommendation_tuning,
            "holdout": recommendation_holdout,
            "runtimeDefaultsMatch": runtime_defaults_match,
        },
        "holdoutDelta": _metric_delta(
            baseline_holdout,
            recommendation_holdout,
        ),
        "privateQueriesOrTextsEmitted": False,
        "rawIdentifiersEmitted": False,
    }


def build_retrieval_evaluation_cases(
    conn: sqlite3.Connection,
    *,
    project: str,
    max_cases_per_suite: int,
) -> list[RetrievalEvaluationCase]:
    limit = max(10, min(int(max_cases_per_suite), 500))
    active_docs = {
        str(row["source_id"]): {
            "doc_id": str(row["doc_id"]),
            "raw_text": str(row["raw_text"] or ""),
            "metadata_terms": _metadata_terms(row),
        }
        for row in conn.execute(
            """
            SELECT doc_id, source_id, raw_text, tags_text, aliases_text,
                   surface_hints_text, query_expansions_text
            FROM memory_retrieval_docs
            WHERE status = 'active' AND doc_type = 'atom'
              AND (? = '' OR project = ? OR project = '')
            """,
            (project, project),
        ).fetchall()
    }
    evidence = _evidence_cases(
        conn,
        active_docs=active_docs,
        project=project,
        limit=limit,
    )
    metadata = _metadata_cases(active_docs, limit=limit)
    superseded = _supersession_cases(
        conn,
        active_docs=active_docs,
        project=project,
        limit=limit,
    )
    return [*evidence, *metadata, *superseded]


def _evidence_cases(
    conn: sqlite3.Connection,
    *,
    active_docs: dict[str, dict[str, object]],
    project: str,
    limit: int,
) -> list[RetrievalEvaluationCase]:
    grouped: dict[str, dict[str, object]] = {}
    rows = conn.execute(
        """
        SELECT event.id AS event_id, event.committed_text, atom.id AS atom_id
        FROM memory_atoms AS atom
        JOIN memory_source_event_links AS link
          ON link.source_type = 'atom' AND link.source_id = atom.id
        JOIN input_events AS event ON event.id = link.event_id
        WHERE atom.status IN ('active', 'approved')
          AND atom.claim_state = 'current'
          AND atom.privacy_level != 'sensitive'
          AND (? = '' OR atom.scope_project = ? OR atom.scope_project IS NULL
               OR atom.scope_project = '')
        ORDER BY event.id, atom.id
        """,
        (project, project),
    ).fetchall()
    for row in rows:
        atom_id = str(row["atom_id"] or "")
        doc = active_docs.get(atom_id)
        if doc is None:
            continue
        query = compact_whitespace(str(row["committed_text"] or ""))
        if not _eligible_private_query(query):
            continue
        normalized = normalize_text(query)
        if not normalized:
            continue
        key = _private_key("evidence", normalized)
        item = grouped.setdefault(
            key,
            {
                "query": query,
                "expected": set(),
            },
        )
        expected = item["expected"]
        if isinstance(expected, set):
            expected.add(str(doc["doc_id"]))

    candidates: list[RetrievalEvaluationCase] = []
    per_primary_doc: dict[str, int] = defaultdict(int)
    for key, item in sorted(grouped.items(), key=lambda pair: pair[0]):
        expected = frozenset(str(value) for value in item["expected"])
        # One input may contain several independent facts. Treating all of
        # their docs as interchangeable relevance labels leaks targets across
        # splits and overstates retrieval quality, so keep single-target cases.
        if len(expected) != 1:
            continue
        primary = next(iter(expected))
        if per_primary_doc[primary] >= 4:
            continue
        per_primary_doc[primary] += 1
        candidates.append(
            RetrievalEvaluationCase(
                key=key,
                suite="evidence_input",
                query_text=str(item["query"]),
                expected_doc_ids=expected,
                split=_split_for_key(primary),
            )
        )
    return _balanced_limit(candidates, limit)


def _metadata_cases(
    active_docs: dict[str, dict[str, object]],
    *,
    limit: int,
) -> list[RetrievalEvaluationCase]:
    docs_by_term: dict[str, set[str]] = defaultdict(set)
    display_by_term: dict[str, str] = {}
    for doc in active_docs.values():
        doc_id = str(doc["doc_id"])
        for term in doc["metadata_terms"]:
            normalized = normalize_text(term)
            if len(normalized) < 2:
                continue
            # Prefer a metadata-only cue. Terms already present verbatim in
            # the canonical fact are still retained when no better cue exists.
            docs_by_term[normalized].add(doc_id)
            display_by_term.setdefault(normalized, term)
    candidates: list[RetrievalEvaluationCase] = []
    per_doc: dict[str, int] = defaultdict(int)
    for normalized, doc_ids in sorted(docs_by_term.items()):
        # Shared tags make weak labels ambiguous and can connect most of the
        # catalog across both splits. Keep only cues with one authoritative
        # target, then group every cue for that target into the same split.
        if len(doc_ids) != 1:
            continue
        target_doc_id = next(iter(doc_ids))
        if per_doc[target_doc_id] >= 4:
            continue
        per_doc[target_doc_id] += 1
        term = display_by_term[normalized]
        candidates.append(
            RetrievalEvaluationCase(
                key=_private_key("metadata", normalized),
                suite="metadata_term",
                query_text=term,
                expected_doc_ids=frozenset(doc_ids),
                split=_split_for_key(target_doc_id),
            )
        )
    return _balanced_limit(candidates, limit)


def _supersession_cases(
    conn: sqlite3.Connection,
    *,
    active_docs: dict[str, dict[str, object]],
    project: str,
    limit: int,
) -> list[RetrievalEvaluationCase]:
    rows = conn.execute(
        """
        SELECT historical.id AS historical_id,
               COALESCE(historical.canonical_text, historical.text) AS old_text,
               current.id AS current_id
        FROM memory_atoms AS historical
        JOIN memory_atoms AS current
          ON current.claim_key = historical.claim_key
         AND current.owner_kind = historical.owner_kind
         AND current.owner_id = historical.owner_id
         AND COALESCE(current.scope_project, '') =
             COALESCE(historical.scope_project, '')
         AND COALESCE(current.scope_app, '') =
             COALESCE(historical.scope_app, '')
        WHERE historical.claim_key != ''
          AND historical.claim_state IN ('superseded', 'retracted')
          AND current.claim_state = 'current'
          AND current.status IN ('active', 'approved')
          AND current.privacy_level != 'sensitive'
          AND (? = '' OR current.scope_project = ?
               OR current.scope_project IS NULL OR current.scope_project = '')
        ORDER BY historical.updated_at_ms DESC, historical.id
        """,
        (project, project),
    ).fetchall()
    candidates: list[RetrievalEvaluationCase] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        doc = active_docs.get(str(row["current_id"] or ""))
        if doc is None:
            continue
        query = compact_whitespace(str(row["old_text"] or ""))
        if not _eligible_private_query(query):
            continue
        normalized = normalize_text(query)
        pair = (normalized, str(doc["doc_id"]))
        if pair in seen:
            continue
        seen.add(pair)
        candidates.append(
            RetrievalEvaluationCase(
                key=_private_key("supersession", "\0".join(pair)),
                suite="superseded_value",
                query_text=query,
                expected_doc_ids=frozenset({str(doc["doc_id"])}),
                split=_split_for_key(str(doc["doc_id"])),
            )
        )
    return _balanced_limit(candidates, limit)


def _prepare_cases(
    conn: sqlite3.Connection,
    *,
    cases: list[RetrievalEvaluationCase],
    project: str,
    embedding_provider: EmbeddingProvider | None,
) -> tuple[list[PreparedRetrievalCase], dict[str, object]]:
    historical_source_ids = {
        str(row[0])
        for row in conn.execute(
            """
            SELECT id FROM memory_atoms
            WHERE claim_state IN ('superseded', 'retracted')
               OR status NOT IN ('active', 'approved')
            """
        ).fetchall()
    }
    prepared: list[PreparedRetrievalCase] = []
    stale_hit_occurrences = 0
    empty_hit_queries = 0
    for case in cases:
        payload = retrieve_hybrid_rag_candidates(
            conn,
            HybridRagQuery(
                query_text=case.query_text,
                project=project,
                top_k=64,
                latency_budget_ms=5_000,
                enabled_lanes=(("time", False), ("feedback", False)),
            ),
            embedding_provider,
        )
        hits = tuple(
            hit
            for item in payload.get("hits") or []
            if (hit := _hit_from_payload(item)) is not None
        )
        if not hits:
            empty_hit_queries += 1
        stale_hit_occurrences += sum(
            1 for hit in hits if hit.source_id in historical_source_ids
        )
        lanes = dict(payload.get("lanes") or {})
        prepared.append(
            PreparedRetrievalCase(
                case=case,
                hits=hits,
                elapsed_ms=max(0, int(payload.get("elapsedMs") or 0)),
                vector_raw_count=_lane_count(lanes, "vector_raw"),
                vector_tag_count=_lane_count(lanes, "vector_tag_boost"),
            )
        )
    return prepared, {
        "historicalOrNoncurrentSourceHitOccurrences": stale_hit_occurrences,
        "queriesWithoutAnyLaneHit": empty_hit_queries,
        "passed": stale_hit_occurrences == 0,
    }


def _score_parameter_set(
    prepared: list[PreparedRetrievalCase],
    *,
    parameters: RetrievalParameterSet,
    split: str,
    current_ms: int,
) -> dict[str, object]:
    selected = [item for item in prepared if item.case.split == split]
    by_suite: dict[str, list[dict[str, float]]] = defaultdict(list)
    metadata_ratios: list[float] = []
    for item in selected:
        ranked = rank_hybrid_hits_to_memory_hits(
            list(item.hits),
            query_text=item.case.query_text,
            lane_weights=parameters.weights(),
            current_ms=current_ms,
            metadata_family_config=parameters.metadata_fusion,
            rrf_k=parameters.rrf_k,
            query_coverage_weight=parameters.query_coverage_weight,
        )
        ranked_ids = [hit.doc_id for hit in ranked]
        expected = item.case.expected_doc_ids
        relevant_ranks = [
            index
            for index, doc_id in enumerate(ranked_ids, start=1)
            if doc_id in expected
        ]
        first_rank = min(relevant_ranks, default=0)
        by_suite[item.case.suite].append(
            {
                "success1": float(first_rank == 1),
                "success3": float(0 < first_rank <= 3),
                "success5": float(0 < first_rank <= 5),
                "success10": float(0 < first_rank <= 10),
                "mrr10": 1.0 / first_rank if 0 < first_rank <= 10 else 0.0,
                "labelRecall5": len(
                    expected.intersection(ranked_ids[:5])
                )
                / max(1, len(expected)),
            }
        )
        for hit in ranked[:5]:
            raw = sum(
                float(hit.debug_features.get(lane) or 0.0)
                for lane in METADATA_FAMILY_LANES
            )
            strongest = max(
                (
                    float(hit.debug_features.get(lane) or 0.0)
                    for lane in METADATA_FAMILY_LANES
                ),
                default=0.0,
            )
            fused = raw + float(
                hit.debug_features.get("metadata_family_overlap_penalty") or 0.0
            )
            if strongest > 0.0:
                metadata_ratios.append(max(0.0, fused) / strongest)

    suite_payload = {
        suite: _aggregate_case_metrics(values)
        for suite, values in sorted(by_suite.items())
    }
    overall_values = [value for values in by_suite.values() for value in values]
    quality = _quality_score(suite_payload)
    amplification = max(metadata_ratios, default=1.0)
    objective = quality - 0.002 * max(0.0, amplification - 1.0)
    return {
        "caseCount": len(selected),
        "overall": _aggregate_case_metrics(overall_values),
        "bySuite": suite_payload,
        "qualityScore": round(quality, 6),
        "maxMetadataFamilyAmplification": round(amplification, 6),
        "selectionObjective": round(objective, 6),
    }


def _parameter_grid(
    baseline: RetrievalParameterSet,
) -> list[RetrievalParameterSet]:
    fusion_probes = (
        MetadataFamilyFusionConfig(1.00, 0.00, 0.00),
        MetadataFamilyFusionConfig(1.05, 0.05, 0.00),
        MetadataFamilyFusionConfig(1.10, 0.08, 0.02),
        REFERENCE_METADATA_FUSION,
    )
    candidates: list[RetrievalParameterSet] = [baseline]
    seen = {
        (
            baseline.lane_weights,
            baseline.metadata_fusion,
            baseline.rrf_k,
            baseline.query_coverage_weight,
        )
    }
    for fusion in fusion_probes:
        signature = (
            baseline.lane_weights,
            fusion,
            REFERENCE_RRF_K,
            REFERENCE_QUERY_COVERAGE_WEIGHT,
        )
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(
            RetrievalParameterSet(
                name=f"fusion-probe-c{fusion.max_multiplier:.2f}",
                lane_weights=baseline.lane_weights,
                metadata_fusion=fusion,
            )
        )
    for bm25_raw in (0.95, 1.00, 1.05, 1.10):
        for vector_raw in (0.90, 0.95, 1.00, 1.05):
            for metadata_scale in (0.85, 1.00):
                for rrf_k in (40, 60, 80):
                    for coverage_weight in (0.15, 0.20, 0.25, 0.30):
                        weights = dict(REFERENCE_LANE_WEIGHTS)
                        weights["bm25_raw"] = bm25_raw
                        weights["vector_raw"] = vector_raw
                        for lane in METADATA_FAMILY_LANES:
                            weights[lane] = (
                                REFERENCE_LANE_WEIGHTS[lane] * metadata_scale
                            )
                        lane_weights = tuple(weights.items())
                        signature = (
                            lane_weights,
                            REFERENCE_METADATA_FUSION,
                            rrf_k,
                            coverage_weight,
                        )
                        if signature in seen:
                            continue
                        seen.add(signature)
                        candidates.append(
                            RetrievalParameterSet(
                                name=(
                                    f"grid-r{bm25_raw:.2f}-v{vector_raw:.2f}-"
                                    f"m{metadata_scale:.2f}-k{rrf_k}-"
                                    f"q{coverage_weight:.2f}"
                                ),
                                lane_weights=lane_weights,
                                metadata_fusion=REFERENCE_METADATA_FUSION,
                                rrf_k=rrf_k,
                                query_coverage_weight=coverage_weight,
                            )
                        )
    return candidates


def _parameter_sort_key(
    score: dict[str, object],
    parameters: RetrievalParameterSet,
) -> tuple[float, float, float, float]:
    return (
        float(score.get("selectionObjective") or 0.0),
        float(score.get("qualityScore") or 0.0),
        -float(parameters.metadata_fusion.max_multiplier),
        -_distance_from_reference(parameters),
    )


def _holdout_gate(
    *,
    baseline: dict[str, object],
    selected: dict[str, object],
    baseline_tuning: dict[str, object],
    selected_tuning: dict[str, object],
    baseline_parameters: RetrievalParameterSet,
    selected_parameters: RetrievalParameterSet,
) -> tuple[bool, list[str]]:
    if selected_parameters == baseline_parameters:
        return True, ["tuning retained the reference profile"]
    reasons: list[str] = []
    baseline_quality = float(baseline.get("qualityScore") or 0.0)
    selected_quality = float(selected.get("qualityScore") or 0.0)
    if selected_quality + 0.001 < baseline_quality:
        reasons.append("holdout quality score regressed by more than 0.001")
    for suite, tolerance in (
        ("evidence_input", 0.015),
        ("metadata_term", 0.020),
        ("superseded_value", 0.030),
    ):
        baseline_suite = _suite_metrics(baseline, suite)
        selected_suite = _suite_metrics(selected, suite)
        if not baseline_suite or not selected_suite:
            continue
        if (
            float(selected_suite.get("successAt5") or 0.0) + tolerance
            < float(baseline_suite.get("successAt5") or 0.0)
        ):
            reasons.append(f"{suite} Success@5 exceeded regression tolerance")
        if (
            suite == "evidence_input"
            and float(selected_suite.get("mrrAt10") or 0.0) + 0.010
            < float(baseline_suite.get("mrrAt10") or 0.0)
        ):
            reasons.append("evidence_input MRR@10 regressed by more than 0.010")
    if reasons:
        return False, reasons
    improvement = selected_quality - baseline_quality
    tuning_improvement = (
        float(selected_tuning.get("qualityScore") or 0.0)
        - float(baseline_tuning.get("qualityScore") or 0.0)
    )
    amplification_reduction = (
        float(baseline.get("maxMetadataFamilyAmplification") or 1.0)
        - float(selected.get("maxMetadataFamilyAmplification") or 1.0)
    )
    if (
        improvement < 0.001
        and amplification_reduction < 0.05
        and tuning_improvement < 0.001
    ):
        return False, [
            "calibration showed no material gain and holdout showed neither quality gain nor metadata amplification reduction"
        ]
    return True, [
        "holdout quality stayed within guardrails",
        "calibration quality, holdout quality, or correlated-metadata amplification materially improved",
    ]


def _quality_score(by_suite: dict[str, dict[str, object]]) -> float:
    weighted = 0.0
    total_weight = 0.0
    for suite, suite_weight in _SUITE_WEIGHTS.items():
        metrics = by_suite.get(suite)
        if not metrics or int(metrics.get("count") or 0) <= 0:
            continue
        score = (
            0.65 * float(metrics.get("mrrAt10") or 0.0)
            + 0.35 * float(metrics.get("successAt5") or 0.0)
        )
        weighted += suite_weight * score
        total_weight += suite_weight
    return weighted / total_weight if total_weight else 0.0


def _aggregate_case_metrics(
    values: list[dict[str, float]],
) -> dict[str, object]:
    count = len(values)
    if not count:
        return {
            "count": 0,
            "successAt1": 0.0,
            "successAt3": 0.0,
            "successAt5": 0.0,
            "successAt10": 0.0,
            "mrrAt10": 0.0,
            "meanLabelRecallAt5": 0.0,
        }

    def mean(key: str) -> float:
        return round(sum(value[key] for value in values) / count, 6)

    return {
        "count": count,
        "successAt1": mean("success1"),
        "successAt3": mean("success3"),
        "successAt5": mean("success5"),
        "successAt10": mean("success10"),
        "mrrAt10": mean("mrr10"),
        "meanLabelRecallAt5": mean("labelRecall5"),
    }


def _dataset_payload(
    cases: list[RetrievalEvaluationCase],
) -> dict[str, object]:
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tuning": 0, "holdout": 0, "total": 0}
    )
    for case in cases:
        counts[case.suite][case.split] += 1
        counts[case.suite]["total"] += 1
    target_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for doc_id in case.expected_doc_ids:
            target_splits[doc_id].add(case.split)
    return {
        "totalCases": len(cases),
        "bySuite": {key: value for key, value in sorted(counts.items())},
        "splitMethod": "stable hash; tuning and holdout grouped by target doc",
        "targetDocOverlapAcrossSplits": sum(
            1 for splits in target_splits.values() if len(splits) > 1
        ),
        "ambiguousMultiTargetCases": sum(
            1 for case in cases if len(case.expected_doc_ids) != 1
        ),
        "source": (
            "actual active retrieval docs, linked input events, metadata, "
            "and supersession history"
        ),
        "humanLabels": False,
        "privatePayloadPersisted": False,
    }


def _provider_gate(
    conn: sqlite3.Connection,
    provider: EmbeddingProvider | None,
) -> dict[str, object]:
    total_vectors = int(
        conn.execute(
            "SELECT COUNT(*) FROM memory_retrieval_doc_vectors"
        ).fetchone()[0]
        or 0
    )
    if provider is None or provider.fingerprint == "none":
        return {
            "configured": False,
            "fingerprintMatched": total_vectors == 0,
            "matchingVectors": 0,
            "storedVectors": total_vectors,
        }
    matching = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_retrieval_doc_vectors AS vector
            JOIN memory_retrieval_docs AS doc ON doc.doc_id = vector.doc_id
            WHERE doc.status = 'active'
              AND vector.provider_fingerprint = ?
              AND vector.source_revision = doc.source_revision
              AND vector.projection_version = doc.projection_version
            """,
            (provider.fingerprint,),
        ).fetchone()[0]
        or 0
    )
    if total_vectors > 0 and matching == 0:
        raise ValueError(
            "evaluation embedding provider fingerprint does not match stored vectors"
        )
    return {
        "configured": True,
        "fingerprint": provider.fingerprint,
        "fingerprintMatched": matching > 0 or total_vectors == 0,
        "matchingVectors": matching,
        "storedVectors": total_vectors,
    }


def _runtime_defaults_match(parameters: RetrievalParameterSet) -> bool:
    expected_weights = parameters.weights()
    if set(expected_weights) != set(LANE_WEIGHTS):
        return False
    if any(
        not math.isclose(
            float(LANE_WEIGHTS[key]),
            float(expected_weights[key]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        for key in expected_weights
    ):
        return False
    return bool(
        DEFAULT_METADATA_FAMILY_FUSION == parameters.metadata_fusion
        and DEFAULT_RRF_K == parameters.rrf_k
        and math.isclose(
            DEFAULT_QUERY_COVERAGE_WEIGHT,
            parameters.query_coverage_weight,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    )


def _metric_delta(
    baseline: dict[str, object],
    selected: dict[str, object],
) -> dict[str, object]:
    delta: dict[str, object] = {
        "qualityScore": round(
            float(selected.get("qualityScore") or 0.0)
            - float(baseline.get("qualityScore") or 0.0),
            6,
        ),
        "maxMetadataFamilyAmplification": round(
            float(selected.get("maxMetadataFamilyAmplification") or 1.0)
            - float(baseline.get("maxMetadataFamilyAmplification") or 1.0),
            6,
        ),
        "bySuite": {},
    }
    suite_delta: dict[str, object] = {}
    for suite in _SUITE_WEIGHTS:
        before = _suite_metrics(baseline, suite)
        after = _suite_metrics(selected, suite)
        if not before or not after:
            continue
        suite_delta[suite] = {
            "successAt1": round(
                float(after.get("successAt1") or 0.0)
                - float(before.get("successAt1") or 0.0),
                6,
            ),
            "successAt5": round(
                float(after.get("successAt5") or 0.0)
                - float(before.get("successAt5") or 0.0),
                6,
            ),
            "mrrAt10": round(
                float(after.get("mrrAt10") or 0.0)
                - float(before.get("mrrAt10") or 0.0),
                6,
            ),
        }
    delta["bySuite"] = suite_delta
    return delta


def _suite_metrics(
    score: dict[str, object],
    suite: str,
) -> dict[str, object]:
    by_suite = score.get("bySuite")
    if not isinstance(by_suite, dict):
        return {}
    value = by_suite.get(suite)
    return dict(value) if isinstance(value, dict) else {}


def _distance_from_reference(parameters: RetrievalParameterSet) -> float:
    distance = sum(
        abs(float(value) - float(REFERENCE_LANE_WEIGHTS[key]))
        for key, value in parameters.lane_weights
    )
    distance += abs(
        parameters.metadata_fusion.max_multiplier
        - REFERENCE_METADATA_FUSION.max_multiplier
    )
    distance += abs(parameters.rrf_k - REFERENCE_RRF_K) / 100.0
    distance += abs(
        parameters.query_coverage_weight
        - REFERENCE_QUERY_COVERAGE_WEIGHT
    )
    return distance


def _metadata_terms(row: sqlite3.Row) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for field in (
        "tags_text",
        "aliases_text",
        "surface_hints_text",
        "query_expansions_text",
    ):
        for term in compact_whitespace(str(row[field] or "")).split():
            normalized = normalize_text(term)
            if normalized and normalized not in seen:
                seen.add(normalized)
                terms.append(term)
    return tuple(terms)


def _eligible_private_query(query: str) -> bool:
    if len(query) < 2 or len(query) > 220:
        return False
    if memory_evidence_exclusion_reason(query):
        return False
    if looks_sensitive(query) or contains_sensitive_content(query):
        return False
    return True


def _balanced_limit(
    cases: list[RetrievalEvaluationCase],
    limit: int,
) -> list[RetrievalEvaluationCase]:
    if len(cases) <= limit:
        return cases
    tuning = [case for case in cases if case.split == "tuning"]
    holdout = [case for case in cases if case.split == "holdout"]
    holdout_limit = min(len(holdout), max(1, round(limit * 0.30)))
    tuning_limit = min(len(tuning), limit - holdout_limit)
    selected = [*tuning[:tuning_limit], *holdout[:holdout_limit]]
    if len(selected) < limit:
        selected_keys = {case.key for case in selected}
        selected.extend(
            case
            for case in cases
            if case.key not in selected_keys
        )
    return selected[:limit]


def _split_for_key(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).digest()
    return "tuning" if digest[0] < 179 else "holdout"


def _private_key(kind: str, value: str) -> str:
    digest = hashlib.sha256(
        f"{kind}\0{value}".encode("utf-8", errors="ignore")
    ).hexdigest()
    return f"{kind}:{digest}"


def _latency_payload(values: list[int]) -> dict[str, int]:
    if not values:
        return {"p50": 0, "p95": 0, "max": 0}
    ordered = sorted(max(0, int(value)) for value in values)
    return {
        "p50": int(statistics.median(ordered)),
        "p95": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
        "max": ordered[-1],
    }


def _lane_count(lanes: dict[str, object], lane: str) -> int:
    value = lanes.get(lane)
    return int(value.get("count") or 0) if isinstance(value, dict) else 0


def _hit_from_payload(raw: object) -> HybridRagHit | None:
    if not isinstance(raw, dict):
        return None
    return HybridRagHit(
        doc_id=str(raw.get("doc_id") or ""),
        doc_type=str(raw.get("doc_type") or ""),
        source_id=str(raw.get("source_id") or ""),
        text=str(raw.get("text") or ""),
        surface_hints=tuple(
            str(value) for value in raw.get("surface_hints") or []
        ),
        tags=tuple(str(value) for value in raw.get("tags") or []),
        source_lane=str(raw.get("source_lane") or ""),
        rank=int(raw.get("rank") or 1),
        raw_score=float(raw.get("raw_score") or 0.0),
        metadata=dict(raw.get("metadata") or {}),
    )
