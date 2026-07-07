from __future__ import annotations

import unittest

from rag_ime.memory.curated_store import (
    RealtimeMemoryContext,
    annotate_realtime_memory_candidate,
    decide_realtime_memory_candidate,
)
from rag_ime.models import InputSuggestion


def _suggestion(text: str, *, metadata: dict[str, object] | None = None, suggestion_id: str = "sug-event:1") -> InputSuggestion:
    return InputSuggestion(
        suggestion_id=suggestion_id,
        surface_text=text,
        suggestion_type="phrase",
        source_event_id=1,
        evidence_preview="fixture",
        confidence=0.9,
        metadata=metadata or {},
    )


class CuratedMemoryRealtimePolicyTests(unittest.TestCase):
    def test_curated_memory_used_for_realtime_candidates(self) -> None:
        decision = decide_realtime_memory_candidate(
            _suggestion("真实输入链路跑通", metadata={"tags": ["curated"]}),
            context=RealtimeMemoryContext(committed_context="我想整理项目"),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source_reason, "accepted_memory")

    def test_raw_history_not_displayed_without_compile(self) -> None:
        decision = decide_realtime_memory_candidate(
            _suggestion("然后我还有个需求，就是目前我正在做另一个输入法。"),
            context=RealtimeMemoryContext(committed_context="我想整理项目"),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.source_reason, "rejected_raw_history")

    def test_rejected_memory_not_displayed(self) -> None:
        decision = decide_realtime_memory_candidate(
            _suggestion("候选质量验收", metadata={"state": {"status": "suppressed"}, "tags": ["curated"]}),
            context=RealtimeMemoryContext(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.source_reason, "rejected_tombstone")

    def test_tombstoned_memory_not_displayed(self) -> None:
        decision = decide_realtime_memory_candidate(
            _suggestion("候选质量验收", metadata={"tombstoned": True, "tags": ["curated"]}),
            context=RealtimeMemoryContext(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rejected_reason, "tombstone_or_suppressed")

    def test_source_reason_present(self) -> None:
        suggestion = _suggestion("面试项目讲清楚真实输入链路", metadata={"memory_kind": "project_requirement"})
        decision = decide_realtime_memory_candidate(suggestion, context=RealtimeMemoryContext())
        annotated = annotate_realtime_memory_candidate(suggestion, decision=decision)

        self.assertTrue(decision.allowed)
        self.assertEqual(annotated.metadata["sourceReason"], "project_requirement")


if __name__ == "__main__":
    unittest.main()
