from __future__ import annotations

import unittest

from rag_ime.memory_optimizer import AntiEchoGovernor, MemoryOptimizerConfig
from rag_ime.memory_optimizer_models import ContextFrame, RawRetrievalHit


class MemoryOptimizerAntiEchoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = AntiEchoGovernor(MemoryOptimizerConfig(enabled=True))
        self.context = ContextFrame(
            session_id="anti-echo",
            request_seq=1,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="post_commit_continuation",
            raw_input="",
            preedit="",
            committed_tail="我想设计一个输入法",
            selected_rime_candidates=["设计"],
            semantic_query="设计输入法",
            semantic_query_source="rime_candidate",
            composition_hash="sha256:compose",
            context_hash="sha256:context",
            active_tags=["设计", "输入法"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=1,
        )

    def test_blocks_long_raw_history_candidate_by_default(self) -> None:
        hit = RawRetrievalHit(
            id="event:123",
            text="这是我之前输入过的一整段很长的历史句子，不应该再次出现在候选栏里",
            source="fts",
            score=0.9,
            memory_atom_id=None,
            evidence="old raw history",
            metadata={"tags": ["user-input"], "source_type": "rag"},
        )
        decision = self.governor.should_block(hit=hit, context=self.context, governance={})
        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "raw_history_long_candidate")

    def test_blocks_candidate_that_repeats_committed_tail(self) -> None:
        hit = RawRetrievalHit(
            id="event:124",
            text="我想设计一个输入法",
            source="stable_memory",
            score=0.8,
            memory_atom_id="mem-1",
            evidence="context echo",
            metadata={"tags": ["memory"], "source_type": "memory"},
        )
        decision = self.governor.should_block(hit=hit, context=self.context, governance={})
        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "committed_tail_overlap")

    def test_blocks_tombstoned_and_suppressed_candidates(self) -> None:
        tombstoned = RawRetrievalHit(
            id="event:125",
            text="连续预测",
            source="stable_memory",
            score=0.8,
            memory_atom_id="mem-2",
            evidence="tombstoned",
            metadata={"tags": ["memory"], "source_type": "memory"},
        )
        suppressed = RawRetrievalHit(
            id="event:126",
            text="候选排序",
            source="stable_memory",
            score=0.8,
            memory_atom_id="mem-3",
            evidence="suppressed",
            metadata={"tags": ["memory"], "source_type": "memory"},
        )
        tombstone_decision = self.governor.should_block(
            hit=tombstoned,
            context=self.context,
            governance={"tombstonedMemoryIds": ["event:125"], "suppressedTexts": []},
        )
        suppressed_decision = self.governor.should_block(
            hit=suppressed,
            context=self.context,
            governance={"tombstonedMemoryIds": [], "suppressedTexts": ["候选排序"]},
        )
        self.assertEqual(tombstone_decision.reason, "tombstone_memory_id")
        self.assertEqual(suppressed_decision.reason, "suppressed_text")

    def test_blocks_recent_committed_echo_during_pinyin_composition(self) -> None:
        context = ContextFrame(
            session_id="anti-echo-pinyin",
            request_seq=2,
            front_app_bundle_id="com.apple.TextEdit",
            input_mode="pinyin_composition",
            raw_input="sj",
            preedit="sj",
            committed_tail="",
            selected_rime_candidates=["设计", "世纪"],
            semantic_query="设计",
            semantic_query_source="rime_candidate",
            composition_hash="sha256:compose2",
            context_hash="sha256:context2",
            active_tags=["设计"],
            project_scope="wisdom-weasel-rag-ime",
            timestamp_ms=2,
        )
        hit = RawRetrievalHit(
            id="event:127",
            text="刚才旧句子",
            source="fts",
            score=0.9,
            memory_atom_id=None,
            evidence="recent raw history",
            metadata={"tags": ["user-input"], "source_type": "rag"},
        )

        decision = self.governor.should_block(
            hit=hit,
            context=context,
            governance={"recentCommittedTexts": ["刚才旧句子"]},
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "recent_committed_echo")
