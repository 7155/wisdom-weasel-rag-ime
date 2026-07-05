from __future__ import annotations

import time
import unittest

from rag_ime.memory_optimizer import MemoryOptimizerConfig, RagMemoryOptimizer
from rag_ime.memory_optimizer_models import ContextFrame, RawRetrievalHit


class MemoryOptimizerLatencyTests(unittest.TestCase):
    def test_optimizer_p95_stays_within_budget_on_deterministic_fixture(self) -> None:
        optimizer = RagMemoryOptimizer(
            MemoryOptimizerConfig(
                enabled=True,
                trace_enabled=True,
                max_ms=15,
                allow_cold_knowledge=False,
                allow_raw_memory_candidates=False,
            )
        )
        context = ContextFrame(
            session_id="latency-fixture",
            request_seq=1,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="post_commit_continuation",
            raw_input="",
            preedit="",
            committed_tail="我想继续写输入法候选优化",
            selected_rime_candidates=["输入法", "优化"],
            semantic_query="输入法候选优化",
            semantic_query_source="rime_candidate",
            composition_hash="latency-composition",
            context_hash="latency-context",
            active_tags=["输入法", "优化", "候选"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=1,
        )
        base_hits = [
            RawRetrievalHit(
                id=f"phrase:{index}",
                text=f"输入法优化{index}",
                source="phrase",
                score=0.8 - index * 0.01,
                memory_atom_id=f"mem:{index}",
                evidence="latency fixture phrase",
                metadata={"tags": ["phrase-memory"], "source_type": "memory"},
            )
            for index in range(12)
        ]
        base_hits.append(
            RawRetrievalHit(
                id="event:raw-long",
                text="这是我之前输入过的一整段很长的历史句子，不应该再次出现在候选栏里",
                source="fts",
                score=0.9,
                memory_atom_id="raw:event:1",
                evidence="latency fixture raw history",
                metadata={"tags": ["user-input"], "source_type": "rag"},
            )
        )
        governance = {
            "recentCommittedTexts": [],
            "tombstonedMemoryIds": [],
            "tombstonedTexts": [],
            "suppressedMemoryIds": [],
            "suppressedTexts": [],
        }

        latencies_ms: list[float] = []
        wall_latencies_ms: list[float] = []
        for _ in range(200):
            started = time.perf_counter()
            result = optimizer.optimize_memory_candidates(
                context,
                base_hits,
                top_k=5,
                latency_budget_ms=15,
                governance=governance,
            )
            wall_latencies_ms.append((time.perf_counter() - started) * 1000)
            latencies_ms.append(float(result.latency_ms))

        self.assertTrue(all(latency >= 0.0 for latency in latencies_ms))
        self.assertLessEqual(_p95(latencies_ms), 15.0)
        self.assertLessEqual(_p95(wall_latencies_ms), 15.0)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

