from __future__ import annotations

from pathlib import Path
from typing import Any

from .foreground_privacy import assess_foreground_write, storage_receipt
from .rime_rank_export import record_rime_rank_feedback
from .text_utils import compact_whitespace


SCHEMA_VERSION = "rag-ime.rime-rank-selection.v1"


def record_native_rime_selection(
    payload: dict[str, Any],
    *,
    db_path: str | Path,
    default_project: str = "wisdom-weasel-rag-ime",
) -> dict[str, object]:
    privacy_assessment = assess_foreground_write(payload)
    if privacy_assessment["storeAllowed"] is not True:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "recorded": False,
            "stored": False,
            "noStore": True,
            "dryRun": bool(payload.get("dryRun", False)),
            "eventId": 0,
            "action": "none",
            "candidateRank": 0,
            "sourceType": "rime",
            "privacyAssessment": privacy_assessment,
            "storageReceipt": storage_receipt(privacy_assessment, stored=False),
        }

    source_type = compact_whitespace(str(payload.get("sourceType") or "")).lower()
    if source_type != "rime":
        raise ValueError("native Rime feedback requires sourceType=rime")

    preedit = compact_whitespace(str(payload.get("preedit") or ""))
    accepted_text = compact_whitespace(str(payload.get("acceptedText") or ""))
    selection_id = compact_whitespace(str(payload.get("selectionId") or ""))
    if not preedit:
        raise ValueError("preedit must not be empty")
    if not accepted_text:
        raise ValueError("acceptedText must not be empty")
    if not selection_id:
        raise ValueError("selectionId must not be empty")

    candidate_rank = _bounded_rank(payload.get("candidateRank"))
    rejected_text = compact_whitespace(str(payload.get("rejectedText") or ""))
    if rejected_text == accepted_text:
        rejected_text = ""
    action = "correction_pair" if candidate_rank > 1 and rejected_text else "accepted"
    dry_run = bool(payload.get("dryRun", False))
    event_id = 0
    if not dry_run:
        event_id = record_rime_rank_feedback(
            db_path,
            preedit=preedit,
            accepted_text=accepted_text,
            rejected_text=rejected_text,
            action=action,
            app=compact_whitespace(str(payload.get("app") or "squirrel")),
            project=compact_whitespace(str(payload.get("project") or default_project)),
            candidate_rank=candidate_rank,
            context_hash=selection_id,
            metadata={
                "candidateSource": "rime",
                "selectionSource": compact_whitespace(str(payload.get("selectionSource") or "patched_squirrel")),
                "selectionId": selection_id,
                "shownCandidateCount": _non_negative_int(payload.get("shownCandidateCount")),
            },
        )
    stored = not dry_run
    return {
        "schemaVersion": SCHEMA_VERSION,
        "ok": True,
        "recorded": stored,
        "stored": stored,
        "noStore": False,
        "dryRun": dry_run,
        "eventId": event_id,
        "action": action,
        "candidateRank": candidate_rank,
        "sourceType": "rime",
        "privacyAssessment": privacy_assessment,
        "storageReceipt": storage_receipt(
            privacy_assessment,
            stored=stored,
            event_id=event_id,
            outcome=None if stored else "dry_run",
            reason=None if stored else "dry_run",
        ),
    }


def _bounded_rank(value: object) -> int:
    try:
        return max(1, min(999, int(value or 1)))
    except (TypeError, ValueError):
        return 1


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
