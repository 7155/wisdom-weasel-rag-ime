from __future__ import annotations

from collections import defaultdict
import math
import re
import time

from .hybrid_rag_models import HybridRagCandidate, HybridRagHit
from .text_utils import compact_whitespace, truncate_text


LANE_WEIGHTS = {
    "bm25_raw": 1.00,
    "bm25_tags": 1.15,
    "vector_raw": 0.95,
    "vector_tag_boost": 1.05,
    "tagmemo": 1.10,
    "time": 0.90,
    "feedback": 1.20,
}


def rrf(rank: int, k: int = 60) -> float:
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
) -> list[HybridRagCandidate]:
    effective_lane_weights = {**LANE_WEIGHTS, **(lane_weights or {})}
    grouped: dict[str, list[HybridRagHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.doc_id].append(hit)
    candidates: list[HybridRagCandidate] = []
    for doc_id, doc_hits in grouped.items():
        best_hit = _best_hit(doc_hits, lane_weights=effective_lane_weights)
        text = _candidate_text(best_hit)
        if not text or _raw_echo_penalty(text=text, query_text=query_text, committed_tail=committed_tail) >= 1.0:
            continue
        features = _score_features(doc_hits, lane_weights=effective_lane_weights)
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
        candidates.append(
            HybridRagCandidate(
                candidate_id=f"hybrid:{doc_id}",
                text=text,
                insert_text=text,
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
                    **_tag_activation_metadata(doc_hits),
                },
            )
        )
    candidates.sort(key=lambda item: (item.score, item.confidence, item.text), reverse=True)
    return candidates[: max(1, int(top_k))]


def _best_hit(hits: list[HybridRagHit], *, lane_weights: dict[str, float]) -> HybridRagHit:
    return sorted(hits, key=lambda hit: (lane_weights.get(hit.source_lane, 0.1), -hit.rank, hit.raw_score), reverse=True)[0]


def _score_features(hits: list[HybridRagHit], *, lane_weights: dict[str, float]) -> dict[str, float]:
    features: dict[str, float] = {}
    for hit in hits:
        lane = hit.source_lane
        lane_score = lane_weights.get(lane, 0.5) * rrf(hit.rank)
        features[lane] = max(features.get(lane, 0.0), lane_score)
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
    return features


def _candidate_text(hit: HybridRagHit) -> str:
    surface = next((compact_whitespace(item) for item in hit.surface_hints if compact_whitespace(item)), "")
    if surface:
        return surface
    if hit.doc_type in {"book", "atom"}:
        return ""
    if hit.doc_type == "phrase":
        return compact_whitespace(hit.text)
    if hit.doc_type == "item":
        if str(hit.metadata.get("kind") or "") == "raw_event":
            return ""
        text = compact_whitespace(hit.text)
        return text if len(text) <= 24 else ""
    return ""


def _source_type_for_doc(doc_type: str) -> str:
    if doc_type == "book":
        return "memory"
    if doc_type == "atom":
        return "rag"
    if doc_type == "phrase":
        return "phrase"
    return "rag"


def _tag_activation_metadata(hits: list[HybridRagHit]) -> dict[str, object]:
    tagged = [hit for hit in hits if float(hit.metadata.get("tagActivationEnergy") or 0.0) > 0.0]
    if not tagged:
        return {}
    best = max(tagged, key=lambda hit: float(hit.metadata.get("tagActivationEnergy") or 0.0))
    return {
        "tagActivationEnergy": float(best.metadata.get("tagActivationEnergy") or 0.0),
        "tagActivationHop": int(best.metadata.get("tagActivationHop") or 0),
        "tagActivationPath": list(best.metadata.get("tagActivationPath") or []),
        "tagActivationEvidenceCount": int(best.metadata.get("tagActivationEvidenceCount") or 0),
    }


def _raw_echo_penalty(*, text: str, query_text: str, committed_tail: str) -> float:
    candidate = compact_whitespace(text)
    if not candidate:
        return 1.0
    if len(candidate) > 32:
        return 1.0
    query = compact_whitespace(query_text)
    tail = compact_whitespace(committed_tail)
    if query and candidate == query and len(candidate) > 8:
        return 1.0
    if tail and candidate and candidate in tail[-80:]:
        return 1.0
    return 0.0


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
