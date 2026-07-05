from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_ingest import normalize_text, upsert_memory_item
from rag_ime.text_utils import now_ms


class MemoryOptimizerFeedbackTests(unittest.TestCase):
    def test_feedback_updates_quality_and_creates_contextual_cooldown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-memory-feedback-") as tmp:
            db_path = Path(tmp) / "feedback.sqlite"
            core = LocalSqliteCoreClient(db_path)
            core.initialize()
            created_at = now_ms()
            with core._connect() as conn:
                upsert_memory_item(
                    conn,
                    memory_id="stable:连续预测",
                    kind="stable_memory",
                    text="连续预测",
                    normalized_text=normalize_text("连续预测"),
                    summary="长期记忆候选",
                    source_event_id=None,
                    project="wisdom-weasel-rag-ime",
                    app="",
                    confidence=0.85,
                    quality_score=0.78,
                    status="approved",
                    privacy_class="local",
                    created_at_ms=created_at,
                    updated_at_ms=created_at,
                    metadata={"direct_candidate_allowed": True},
                    tags=("memory", "连续预测"),
                    embedding_provider=core.embedding_provider,
                )

            core.record_memory_feedback(
                {
                    "event": "accepted",
                    "candidateId": "stable:连续预测",
                    "candidateText": "连续预测",
                    "sourceType": "memory",
                    "contextHash": "ctx:feedback",
                    "timestampMs": created_at + 1,
                }
            )
            core.record_memory_feedback(
                {
                    "event": "skipped",
                    "candidateId": "stable:连续预测",
                    "candidateText": "连续预测",
                    "sourceType": "memory",
                    "contextHash": "ctx:feedback",
                    "timestampMs": created_at + 2,
                }
            )
            core.record_memory_feedback(
                {
                    "event": "skipped",
                    "candidateId": "stable:连续预测",
                    "candidateText": "连续预测",
                    "sourceType": "memory",
                    "contextHash": "ctx:feedback",
                    "timestampMs": created_at + 3,
                }
            )

            explanation = core.explain_memory_candidate("stable:连续预测", "ctx:feedback")
            governance = core.optimizer_governance_snapshot(
                memory_ids=["stable:连续预测"],
                texts=["连续预测"],
                source_event_ids=[None],
                context_hash="ctx:feedback",
                project="wisdom-weasel-rag-ime",
                app="",
            )

        assert explanation is not None
        self.assertGreaterEqual(explanation["memoryItem"]["qualityScore"], 0.8)
        self.assertEqual(
            [item["action"] for item in explanation["recentFeedback"][:3]],
            ["skipped", "skipped", "accepted"],
        )
        self.assertIn("stable:连续预测", governance["suppressedMemoryIds"])
        self.assertIn("连续预测", governance["suppressedTexts"])
