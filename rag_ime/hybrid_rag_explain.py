from __future__ import annotations

from .hybrid_rag_models import HybridRagCandidate, HybridRagHit


def explain_hybrid_candidate(candidate: HybridRagCandidate, hits: list[HybridRagHit] | None = None) -> dict[str, object]:
    related_hits = [hit for hit in hits or [] if hit.doc_id == str(candidate.metadata.get("docId") or "")]
    return {
        "candidateId": candidate.candidate_id,
        "text": candidate.text,
        "sourceType": candidate.source_type,
        "sourceLane": candidate.source_lane,
        "score": candidate.score,
        "confidence": candidate.confidence,
        "tags": list(candidate.tags),
        "memoryIds": list(candidate.memory_ids),
        "atomIds": list(candidate.atom_ids),
        "bookIds": list(candidate.book_ids),
        "evidenceEventIds": list(candidate.evidence_event_ids),
        "debugFeatures": dict(candidate.debug_features),
        "lanes": sorted({hit.source_lane for hit in related_hits}) or list(candidate.metadata.get("lanes") or []),
        "evidencePreview": candidate.evidence_preview,
    }
