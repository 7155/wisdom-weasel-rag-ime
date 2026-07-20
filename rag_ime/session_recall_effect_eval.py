from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .hybrid_rag_retriever import _semantic_query_vector


RECEIPT_SCHEMA_VERSION = "rag-ime.session-recall-effect-receipt.v1"


class _FixtureEmbeddingProvider:
    fingerprint = "fixture-vector:v1"

    def __init__(self, values: Mapping[str, Sequence[float]]) -> None:
        self.values = values

    def embed(self, text: str) -> list[float]:
        return [float(value) for value in self.values[text]]

    def embed_many(self, texts: list[str], *, batch_size: int = 32) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def evaluate_session_recall_weights(fixtures: Mapping[str, object]) -> dict[str, object]:
    cases = [case for case in fixtures.get("cases", []) if isinstance(case, Mapping)]
    weights = [float(value) for value in fixtures.get("weights", [])]
    top_k = max(1, int(fixtures.get("topK") or 1))
    results: list[dict[str, object]] = []
    for weight in weights:
        counters = {
            "factHit": 0,
            "preferenceHit": 0,
            "projectHit": 0,
            "taskHit": 0,
            "irrelevantInjection": 0,
            "crossScopeLeak": 0,
            "duplicateBytes": 0,
            "tokenBytes": 0,
            "compactionForgettingRecovery": 0,
            "wrongOldTopic": 0,
        }
        selections: list[dict[str, object]] = []
        seen_text: set[str] = set()
        for case in cases:
            values: dict[str, Sequence[float]] = {
                "query": case.get("query", []),
                "summary": case.get("summary", []),
            }
            candidates = [item for item in case.get("candidates", []) if isinstance(item, Mapping)]
            for candidate in candidates:
                values[str(candidate["id"])] = candidate.get("vector", [])
            provider = _FixtureEmbeddingProvider(values)
            blended, fusion = _semantic_query_vector(
                provider, "query", context_text="summary", context_weight=weight
            )
            ranked = sorted(
                candidates,
                key=lambda candidate: (
                    -_cosine(blended, values[str(candidate["id"])]),
                    str(candidate["id"]),
                ),
            )[:top_k]
            selected_ids = [str(item["id"]) for item in ranked]
            expected = str(case.get("expected") or "")
            metric = str(case.get("metric") or "")
            if expected in selected_ids and metric in counters:
                counters[metric] += 1
            for candidate in ranked:
                candidate_id = str(candidate["id"])
                body = str(candidate.get("text") or "")
                encoded = len(body.encode("utf-8"))
                counters["tokenBytes"] += encoded
                if body in seen_text:
                    counters["duplicateBytes"] += encoded
                seen_text.add(body)
                if candidate_id == "cross-scope":
                    counters["crossScopeLeak"] += 1
                if candidate_id == "wrong-old-topic":
                    counters["wrongOldTopic"] += 1
                if candidate_id not in {expected}:
                    counters["irrelevantInjection"] += 1
            selections.append(
                {"caseId": str(case.get("id") or ""), "selected": selected_ids, "fusion": fusion}
            )
        desired_hits = sum(
            counters[key]
            for key in (
                "factHit", "preferenceHit", "projectHit", "taskHit",
                "compactionForgettingRecovery",
            )
        )
        score = (
            desired_hits * 100
            - counters["irrelevantInjection"] * 80
            - counters["crossScopeLeak"] * 500
            - counters["wrongOldTopic"] * 200
            - counters["duplicateBytes"]
        )
        results.append(
            {
                "queryWeight": round(1.0 - weight, 4),
                "summaryWeight": weight,
                "score": score,
                "metrics": counters,
                "selections": selections,
            }
        )
    chosen = max(results, key=lambda item: (int(item["score"]), -float(item["summaryWeight"])))
    fixture_hash = hashlib.sha256(
        json.dumps(fixtures, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "fixtureSha256": fixture_hash,
        "candidateWeights": results,
        "selected": {
            "queryWeight": chosen["queryWeight"],
            "summaryWeight": chosen["summaryWeight"],
            "reason": "highest deterministic task-hit score after leak, stale-topic, and duplicate penalties",
        },
    }


def evaluate_file(fixtures_path: str | Path) -> dict[str, object]:
    payload = json.loads(Path(fixtures_path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("fixtures must be a JSON object")
    return evaluate_session_recall_weights(payload)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(float(a) ** 2 for a in left)) * math.sqrt(
        sum(float(b) ** 2 for b in right)
    )
    return numerator / denominator if denominator else 0.0


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "eval/session-recall/session-recall-fixtures.v1.json"
    )
    print(json.dumps(evaluate_file(source), ensure_ascii=False, indent=2))
