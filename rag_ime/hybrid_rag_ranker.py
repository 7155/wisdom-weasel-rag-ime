from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
import time

from .hybrid_rag_models import HybridRagCandidate, HybridRagHit, MemoryHit
from .text_utils import compact_whitespace, token_terms, truncate_text


LANE_WEIGHTS = {
    "bm25_raw": 1.10,
    "bm25_tags": 1.15,
    "vector_raw": 1.05,
    "vector_tag_boost": 1.05,
    "tagmemo": 1.10,
    "time": 0.90,
    "feedback": 1.20,
}
METADATA_FAMILY_LANES = (
    "bm25_tags",
    "tagmemo",
    "vector_tag_boost",
)
METADATA_FAMILY_MODES = frozenset({"capped", "legacy_sum"})
DEFAULT_RRF_K = 40
DEFAULT_QUERY_COVERAGE_WEIGHT = 0.30


@dataclass(frozen=True)
class MetadataFamilyFusionConfig:
    max_multiplier: float = 1.20
    secondary_weight: float = 0.15
    tertiary_weight: float = 0.05

    def __post_init__(self) -> None:
        if not 1.0 <= float(self.max_multiplier) <= 3.0:
            raise ValueError("metadata family max multiplier must be between 1 and 3")
        for name, value in (
            ("secondary", self.secondary_weight),
            ("tertiary", self.tertiary_weight),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"metadata family {name} weight must be between 0 and 1")


DEFAULT_METADATA_FAMILY_FUSION = MetadataFamilyFusionConfig()


def rrf(rank: int, k: int = DEFAULT_RRF_K) -> float:
    return 1.0 / (k + max(1, int(rank)))


def rank_hybrid_hits(
    hits: list[HybridRagHit],
    *,
    query_text: str = "",
    committed_tail: str = "",
    top_k: int = 5,
    lane_weights: dict[str, float] | None = None,
    current_ms: int | None = None,
    decay_settings: dict[str, object] | None = None,
    metadata_family_mode: str = "capped",
    metadata_family_config: MetadataFamilyFusionConfig | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    query_coverage_weight: float = DEFAULT_QUERY_COVERAGE_WEIGHT,
) -> list[HybridRagCandidate]:
    from .memory_projectors import ImeMemoryProjector

    memory_hits = rank_hybrid_hits_to_memory_hits(
        hits,
        query_text=query_text,
        lane_weights=lane_weights,
        current_ms=current_ms,
        decay_settings=decay_settings,
        metadata_family_mode=metadata_family_mode,
        metadata_family_config=metadata_family_config,
        rrf_k=rrf_k,
        query_coverage_weight=query_coverage_weight,
    )
    return ImeMemoryProjector().project(
        memory_hits,
        query_text=query_text,
        committed_tail=committed_tail,
        top_k=top_k,
    )


def rank_hybrid_hits_to_memory_hits(
    hits: list[HybridRagHit],
    *,
    query_text: str = "",
    lane_weights: dict[str, float] | None = None,
    current_ms: int | None = None,
    decay_settings: dict[str, object] | None = None,
    metadata_family_mode: str = "capped",
    metadata_family_config: MetadataFamilyFusionConfig | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    query_coverage_weight: float = DEFAULT_QUERY_COVERAGE_WEIGHT,
) -> list[MemoryHit]:
    if metadata_family_mode not in METADATA_FAMILY_MODES:
        raise ValueError("unsupported metadata family fusion mode")
    if not 1 <= int(rrf_k) <= 10_000:
        raise ValueError("RRF k must be between 1 and 10000")
    if not 0.0 <= float(query_coverage_weight) <= 2.0:
        raise ValueError("query coverage weight must be between 0 and 2")
    effective_lane_weights = {**LANE_WEIGHTS, **(lane_weights or {})}
    grouped: dict[str, list[HybridRagHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.doc_id].append(hit)
    memory_hits: list[MemoryHit] = []
    for doc_id, doc_hits in grouped.items():
        best_hit = _best_hit(doc_hits, lane_weights=effective_lane_weights)
        features = _score_features(
            doc_hits,
            lane_weights=effective_lane_weights,
            query_text=query_text,
            metadata_family_mode=metadata_family_mode,
            metadata_family_config=(
                metadata_family_config or DEFAULT_METADATA_FAMILY_FUSION
            ),
            rrf_k=int(rrf_k),
            query_coverage_weight=float(query_coverage_weight),
        )
        base_score = sum(features.values())
        decay_factor = _time_decay_factor(
            metadata=best_hit.metadata,
            doc_type=best_hit.doc_type,
            query_text=query_text,
            current_ms=int(time.time() * 1000) if current_ms is None else max(0, int(current_ms)),
            decay_settings=decay_settings or {},
        )
        if decay_factor < 1.0:
            features["time_decay_penalty"] = -(base_score * (1.0 - decay_factor))
        score = sum(features.values())
        source_ids = tuple(sorted({hit.source_id for hit in doc_hits if hit.source_id}))
        doc_type = best_hit.doc_type
        memory_hits.append(
            MemoryHit(
                hit_id=f"hybrid:{doc_id}",
                doc_id=doc_id,
                doc_type=doc_type,
                source_id=best_hit.source_id,
                text=compact_whitespace(best_hit.text),
                surface_hints=tuple(_unique(item for hit in doc_hits for item in hit.surface_hints)),
                source_type=_source_type_for_doc(doc_type),
                source_lane=best_hit.source_lane,
                score=score,
                confidence=max(0.0, min(1.0, 0.55 + score * 8.0)),
                tags=tuple(_unique(tag for hit in doc_hits for tag in hit.tags)),
                memory_ids=source_ids if doc_type in {"item", "phrase"} else (),
                atom_ids=source_ids if doc_type == "atom" else (),
                book_ids=source_ids if doc_type == "book" else (),
                evidence_event_ids=tuple(_unique_ints(_metadata_event_ids(hit.metadata) for hit in doc_hits)),
                evidence_preview=truncate_text(best_hit.text, 120),
                debug_features=features,
                metadata={
                    **dict(best_hit.metadata),
                    "docId": doc_id,
                    "docType": doc_type,
                    "lanes": sorted({hit.source_lane for hit in doc_hits}),
                    "rawScores": {hit.source_lane: hit.raw_score for hit in doc_hits},
                    "groupCompatibility": max(
                        float(hit.metadata.get("groupCompatibility") or 0.0) for hit in doc_hits
                    ),
                    "timeDecayFactor": round(decay_factor, 6),
                    "sourceUpdatedAtMs": int(best_hit.metadata.get("sourceUpdatedAtMs") or 0),
                    "archived": bool(best_hit.metadata.get("archived")),
                },
            )
        )
    memory_hits.sort(key=lambda item: (item.score, item.confidence, item.text), reverse=True)
    return memory_hits


def _best_hit(hits: list[HybridRagHit], *, lane_weights: dict[str, float]) -> HybridRagHit:
    return sorted(hits, key=lambda hit: (lane_weights.get(hit.source_lane, 0.1), -hit.rank, hit.raw_score), reverse=True)[0]


def _score_features(
    hits: list[HybridRagHit],
    *,
    lane_weights: dict[str, float],
    query_text: str,
    metadata_family_mode: str,
    metadata_family_config: MetadataFamilyFusionConfig,
    rrf_k: int,
    query_coverage_weight: float,
) -> dict[str, float]:
    features: dict[str, float] = {}
    for hit in hits:
        lane = hit.source_lane
        lane_score = lane_weights.get(lane, 0.5) * rrf(hit.rank, k=rrf_k)
        features[lane] = max(features.get(lane, 0.0), lane_score)
    if metadata_family_mode == "capped":
        family_scores = sorted(
            (
                features[lane]
                for lane in METADATA_FAMILY_LANES
                if lane in features
            ),
            reverse=True,
        )
        if family_scores:
            strongest = family_scores[0]
            second = family_scores[1] if len(family_scores) > 1 else 0.0
            third = family_scores[2] if len(family_scores) > 2 else 0.0
            fused = min(
                strongest * float(metadata_family_config.max_multiplier),
                strongest
                + (float(metadata_family_config.secondary_weight) * second)
                + (float(metadata_family_config.tertiary_weight) * third),
            )
            raw_family_sum = sum(family_scores)
            if fused < raw_family_sum:
                # Keep each lane visible in debug output, then subtract only
                # the correlated overlap so the final sum equals the capped
                # family score instead of pretending three Tag views agree.
                features["metadata_family_overlap_penalty"] = (
                    fused - raw_family_sum
                )
    best_metadata = hits[0].metadata if hits else {}
    if bool(best_metadata.get("projectScope")):
        features["project_scope"] = 0.30
    if bool(best_metadata.get("appScope")):
        features["app_scope"] = 0.20
    if bool(best_metadata.get("feedbackAccepted")):
        features["feedback_bonus"] = max(features.get("feedback_bonus", 0.0), 1.20)
    group_compatibility = float(best_metadata.get("groupCompatibility") or 0.0)
    if group_compatibility > 0.0:
        features["group_compatibility"] = group_compatibility * 0.8
    query_terms = token_terms(query_text, max_terms=32)
    if query_terms and hits:
        best = hits[0]
        haystack = compact_whitespace(
            " ".join((best.text, " ".join(best.surface_hints), " ".join(best.tags)))
        ).lower()
        matched = {term for term in query_terms if term.lower() in haystack}
        if matched:
            # RRF combines lanes, while this bounded coverage feature answers
            # a different question: does the final fact itself contain the
            # concepts asked for? It prevents broad tags from beating an exact
            # Atom merely because they appear in more expansion lanes.
            features["query_coverage"] = (
                query_coverage_weight * len(matched) / len(set(query_terms))
            )
    return features


def _source_type_for_doc(doc_type: str) -> str:
    if doc_type == "timeline":
        return "timeline"
    if doc_type == "book":
        return "memory"
    if doc_type == "atom":
        return "rag"
    if doc_type == "phrase":
        return "phrase"
    return "rag"


_EXPLICIT_TIME_RE = re.compile(
    r"(?:今天|今日|昨天|昨日|前天|本周|这周|上周|本月|上月|去年|今年|"
    r"之前|以前|最初|初版|旧版|旧项目|历史|当时|过去|"
    r"\d{4}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?)",
    re.IGNORECASE,
)


def _time_decay_factor(
    *,
    metadata: dict[str, object],
    doc_type: str,
    query_text: str,
    current_ms: int,
    decay_settings: dict[str, object],
) -> float:
    # An explicit temporal request asks for historical truth, so age must not
    # hide the requested day/week. Normal semantic retrieval still favors the
    # user's latest decisions and corrections.
    if _EXPLICIT_TIME_RE.search(compact_whitespace(query_text)):
        return 1.0
    updated_at_ms = int(
        metadata.get("lastActiveAtMs")
        or metadata.get("sourceUpdatedAtMs")
        or 0
    )
    if updated_at_ms <= 0 or current_ms <= updated_at_ms:
        age_factor = 1.0
    else:
        age_days = max(0.0, (current_ms - updated_at_ms) / 86_400_000.0)
        half_life_days = _half_life_days(
            metadata=metadata,
            doc_type=doc_type,
            decay_settings=decay_settings,
        )
        age_factor = math.exp(-math.log(2.0) * age_days / half_life_days)
    archive_factor = 0.15 if bool(metadata.get("archived")) else 1.0
    return max(0.02, min(1.0, age_factor * archive_factor))


def _half_life_days(
    *,
    metadata: dict[str, object],
    doc_type: str,
    decay_settings: dict[str, object],
) -> float:
    kind = compact_whitespace(str(metadata.get("kind") or "")).lower()
    book_type = compact_whitespace(str(metadata.get("bookType") or "")).lower()
    if any(marker in kind for marker in ("task", "temporary", "todo", "plan")):
        return _decay_days(decay_settings.get("temporaryHalfLifeDays"), 14.0)
    if any(marker in kind for marker in ("preference", "identity", "stable")):
        return _decay_days(decay_settings.get("stablePreferenceHalfLifeDays"), 365.0)
    if doc_type == "phrase":
        return 90.0
    if doc_type == "timeline":
        return 14.0
    if doc_type == "book":
        return 30.0 if book_type == "daily" else _decay_days(decay_settings.get("topicBookHalfLifeDays"), 180.0)
    if doc_type == "atom" and "project" in kind:
        return _decay_days(decay_settings.get("projectHalfLifeDays"), 120.0)
    return 90.0


def _decay_days(value: object, default: float) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(1.0, min(3650.0, parsed))


def _metadata_event_ids(metadata: dict[str, object]) -> list[int]:
    raw = metadata.get("sourceEventIds")
    if not isinstance(raw, list):
        raw = [metadata.get("sourceEventId")]
    values: list[int] = []
    for item in raw:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            values.append(number)
    return values


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = compact_whitespace(str(value))
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _unique_ints(values) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for group in values:
        for value in group:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return result
