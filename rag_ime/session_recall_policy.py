from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping


_POLICY_PATH = Path(__file__).with_name("memory") / "session-recall-policy.v1.json"


@dataclass(frozen=True)
class SessionRecallPolicy:
    revision: str
    start_summary_weight: float
    compaction_summary_weight: float
    receipt_sha256: str


@lru_cache(maxsize=1)
def session_recall_policy() -> SessionRecallPolicy:
    """Load the evaluated recall policy instead of burying weights in call sites."""

    payload = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("Session recall policy must be a JSON object")
    weights = payload.get("weights")
    evidence = payload.get("evidence")
    if not isinstance(weights, Mapping) or not isinstance(evidence, Mapping):
        raise RuntimeError("Session recall policy is missing weights/evidence")
    start = float(weights.get("sessionStartSummary") or 0.0)
    compaction = float(weights.get("compactionSummary") or 0.0)
    if not 0.0 <= start <= 0.5 or not 0.0 <= compaction <= 0.5:
        raise RuntimeError("Session recall weights must be between 0 and 0.5")
    return SessionRecallPolicy(
        revision=str(payload.get("revision") or ""),
        start_summary_weight=start,
        compaction_summary_weight=compaction,
        receipt_sha256=str(evidence.get("receiptSha256") or ""),
    )
