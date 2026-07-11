#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_ime.embeddings import embedding_provider_from_env
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import InputEvent, MemoryAction


TOPICS = (
    "连续预测",
    "本地记忆",
    "输入法候选",
    "Rime sidecar",
    "TagGraph",
    "cleanup diff",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe local IME memory-core latency with cached and uncached query paths.")
    parser.add_argument("--db", default=".rag-ime-data/memory-perf-probe.sqlite")
    parser.add_argument("--items", type=int, default=1000, help="Number of synthetic items to seed. Use 0 to probe an existing DB only.")
    parser.add_argument("--repeat", type=int, default=4)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument("--embedding-provider", choices=("none", "local-hash"), default="none")
    parser.add_argument("--vector-candidates", type=int, default=80)
    parser.add_argument("--vector-weight", type=float, default=1.4)
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    provider = embedding_provider_from_env({"RAG_IME_EMBEDDING_PROVIDER": args.embedding_provider})
    if int(args.items) > 0:
        _reset_sqlite_files(db_path)
        _seed_dataset(
            db_path=db_path,
            item_count=max(1, int(args.items)),
            project=args.project,
            provider=provider,
            vector_candidates=max(1, int(args.vector_candidates)),
            vector_weight=max(0.0, float(args.vector_weight)),
        )

    uncached_core = LocalSqliteCoreClient(
        db_path,
        suggestion_cache_size=0,
        embedding_provider=provider,
        vector_candidate_limit=max(1, int(args.vector_candidates)),
        vector_weight=max(0.0, float(args.vector_weight)),
    )
    cached_core = LocalSqliteCoreClient(
        db_path,
        suggestion_cache_size=128,
        embedding_provider=provider,
        vector_candidate_limit=max(1, int(args.vector_candidates)),
        vector_weight=max(0.0, float(args.vector_weight)),
    )
    uncached_core.initialize()
    cached_core.initialize()

    cases = [
        {"query": topic.split()[0], "recentContext": f"{topic} 输入法性能探针"}
        for topic in TOPICS
    ]
    uncached_report = _measure_query_path(
        uncached_core,
        cases=cases,
        repeat=max(1, int(args.repeat)),
        top_k=max(1, int(args.top_k)),
        project=args.project,
        warm_first=False,
    )
    cached_report = _measure_query_path(
        cached_core,
        cases=cases,
        repeat=max(1, int(args.repeat)),
        top_k=max(1, int(args.top_k)),
        project=args.project,
        warm_first=True,
    )

    payload = {
        "schemaVersion": "rag-ime.memory-perf-probe.v1",
        "dbPath": str(db_path),
        "itemCount": uncached_core.event_count(),
        "seeded": max(0, int(args.items)),
        "project": args.project,
        "topK": max(1, int(args.top_k)),
        "repeat": max(1, int(args.repeat)),
        "cases": cases,
        "vector": uncached_core.vector_index_stats(),
        "latency": {
            "uncached": uncached_report,
            "cached": cached_report,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _seed_dataset(
    *,
    db_path: Path,
    item_count: int,
    project: str,
    provider,
    vector_candidates: int,
    vector_weight: float,
) -> None:
    core = LocalSqliteCoreClient(
        db_path,
        suggestion_cache_size=0,
        embedding_provider=provider,
        vector_candidate_limit=vector_candidates,
        vector_weight=vector_weight,
    )
    core.initialize()
    base_ms = 1_900_000_000_000
    for index in range(item_count):
        topic = TOPICS[index % len(TOPICS)]
        is_long_raw = index % 11 == 0
        if is_long_raw:
            text = f"这是 {topic} 的性能探针原始长句 {index}，用于验证输入法候选不要复读旧输入。"
            tags = ("perf", "raw-history", topic)
        else:
            text = f"{topic}候选{index % 37}"
            tags = ("perf", "phrase-memory", topic)
        event_id = core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=base_ms + index,
                source="perf_probe",
                committed_text=text,
                recent_context=f"{topic} 性能基线 {index % 9}",
                project=project,
                app="perf-probe",
                provider_name="local",
                tags=tags,
                privacy_disposition="allowed",
            )
        )
        if not is_long_raw and index % 29 == 0:
            core.apply_action(
                MemoryAction(
                    action_id=None,
                    created_at_ms=base_ms + item_count + index,
                    memory_id=event_id,
                    action_type="accepted",
                    query=topic,
                    metadata={"project": project},
                )
            )


def _measure_query_path(
    core: LocalSqliteCoreClient,
    *,
    cases: list[dict[str, str]],
    repeat: int,
    top_k: int,
    project: str,
    warm_first: bool,
) -> dict[str, object]:
    if warm_first:
        for case in cases:
            core.suggest_for_input(
                current_input=case["query"],
                recent_context=case["recentContext"],
                project=project,
                top_k=top_k,
            )
    latencies_ms: list[float] = []
    top_surfaces: list[str] = []
    for _ in range(repeat):
        for case in cases:
            started = time.perf_counter()
            suggestions = core.suggest_for_input(
                current_input=case["query"],
                recent_context=case["recentContext"],
                project=project,
                top_k=top_k,
            )
            latencies_ms.append((time.perf_counter() - started) * 1000)
            if suggestions:
                top_surfaces.append(suggestions[0].surface_text)
    return {
        **_latency_summary(latencies_ms),
        "queryCount": len(latencies_ms),
        "sampleTopSurfaces": top_surfaces[:6],
        "cacheStats": core.suggestion_cache_stats(),
    }


def _latency_summary(values_ms: list[float]) -> dict[str, float]:
    if not values_ms:
        return {"avgMs": 0.0, "p50Ms": 0.0, "p95Ms": 0.0, "maxMs": 0.0}
    ordered = sorted(values_ms)
    return {
        "avgMs": round(float(statistics.mean(ordered)), 3),
        "p50Ms": round(_percentile(ordered, 0.50), 3),
        "p95Ms": round(_percentile(ordered, 0.95), 3),
        "maxMs": round(float(ordered[-1]), 3),
    }


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * quantile))
    return float(sorted_values[index])


def _reset_sqlite_files(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            candidate.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
