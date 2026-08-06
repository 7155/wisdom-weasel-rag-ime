from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.embeddings import HashingEmbeddingProvider
from rag_ime.longmemeval_memory_retrieval import (
    LongMemEvalMemoryIndex,
    _weighted_reciprocal_rank_fusion,
)
from scripts.run_longmemeval_memory_retrieval import (
    _abstention_metrics,
    _cases_for_profile,
)


class LongMemEvalMemoryIndexTests(unittest.TestCase):
    def test_weighted_rrf_preserves_session_head_and_adds_turn_evidence(self) -> None:
        fused = _weighted_reciprocal_rank_fusion(
            (["session-a", "session-b"], ["session-c", "session-a"]),
            weights=(3.0, 1.0),
            rrf_k=60,
        )

        self.assertEqual(
            ["session-a", "session-b", "session-c"],
            [session_id for session_id, _score in fused],
        )
        self.assertGreater(fused[0][1], fused[1][1])

    def test_abstention_metrics_count_each_confusion_cell_once(self) -> None:
        metrics = _abstention_metrics(
            [
                {"abstention": True, "hasHits": False, "topScore": 0.0},
                {"abstention": True, "hasHits": True, "topScore": 0.8},
                {"abstention": False, "hasHits": True, "topScore": 0.9},
                {"abstention": False, "hasHits": True, "topScore": 0.2},
            ],
            threshold=0.5,
        )

        self.assertEqual(
            {
                "trueAbstention": 1,
                "falseAbstention": 1,
                "trueAnswerable": 1,
                "falseAnswerable": 1,
            },
            metrics["confusion"],
        )
        self.assertEqual(0.5, metrics["accuracy"])
        self.assertEqual(0.5, metrics["balancedAccuracy"])
        self.assertEqual(0.5, metrics["abstentionPrecision"])
        self.assertEqual(0.5, metrics["abstentionRecall"])
        self.assertEqual(0.5, metrics["answerableRecall"])

    def test_profile_projection_keeps_public_and_product_denominators_separate(self) -> None:
        common = {
            "system": "memory",
            "split": "validation",
            "sessions": [{"sessionId": "s", "date": "d", "turns": []}],
        }
        cases = [
            {
                **common,
                "queryId": "public-target",
                "abstention": False,
                "officialRetrievalEvaluable": True,
                "productRetrievalEvaluable": True,
                "officialRelevant": {"s": 1.0},
                "productRelevant": {"s": 1.0},
            },
            {
                **common,
                "queryId": "assistant-target",
                "abstention": False,
                "officialRetrievalEvaluable": False,
                "productRetrievalEvaluable": True,
                "officialRelevant": {},
                "productRelevant": {"s": 1.0},
            },
            {
                **common,
                "queryId": "abstention",
                "abstention": True,
                "officialRetrievalEvaluable": False,
                "productRetrievalEvaluable": False,
                "officialRelevant": {},
                "productRelevant": {"s": 1.0},
            },
        ]

        official = _cases_for_profile(cases, evaluation_profile="official-user")
        product = _cases_for_profile(cases, evaluation_profile="product-all-turn")

        self.assertEqual(
            ["public-target", "abstention"],
            [case["queryId"] for case in official],
        )
        self.assertEqual(
            ["public-target", "assistant-target", "abstention"],
            [case["queryId"] for case in product],
        )
        self.assertEqual({}, official[-1]["relevant"])
        self.assertEqual("product-all-turn", product[1]["evaluationProfile"])

    def test_product_memory_index_supports_session_turn_and_dense_retrieval(self) -> None:
        case = {
            "schemaVersion": "rag-ime.memory-retrieval-case.v1",
            "system": "memory",
            "queryId": "memory-tea",
            "questionType": "single-session-preference",
            "slice": "single-session-preference",
            "abstention": False,
            "retrievalEvaluable": True,
            "question": "Which tea do I prefer?",
            "answer": "Jasmine tea.",
            "questionDate": "2026/08/04 (Tue) 12:00",
            "sessions": [
                {
                    "sessionId": "session-answer",
                    "date": "2026/08/03 (Mon) 12:00",
                    "turns": [
                        {
                            "role": "user",
                            "content": "I prefer jasmine tea every morning.",
                            "hasAnswer": True,
                        },
                        {
                            "role": "assistant",
                            "content": "I will remember that tea preference.",
                            "hasAnswer": False,
                        },
                    ],
                },
                {
                    "sessionId": "session-weather",
                    "date": "2026/08/02 (Sun) 12:00",
                    "turns": [
                        {
                            "role": "user",
                            "content": "The weather is cloudy today.",
                            "hasAnswer": False,
                        }
                    ],
                },
            ],
            "relevant": {"session-answer": 1.0},
            "split": "validation",
        }
        provider = HashingEmbeddingProvider(dimensions=64)

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-index-") as temporary:
            index = LongMemEvalMemoryIndex(
                Path(temporary) / "memory.sqlite",
                embedding_provider=provider,
            )
            try:
                build = index.build(
                    [case],
                    include_turn_index=True,
                    build_vectors=True,
                    content_profile="product-all-turn",
                )
                session_lexical = index.retrieve(
                    query_id="memory-tea",
                    query_text="Which tea do I prefer?",
                    config={"granularity": "session", "mode": "lexical", "topK": 10},
                )
                turn_lexical = index.retrieve(
                    query_id="memory-tea",
                    query_text="Which tea do I prefer?",
                    config={"granularity": "turn", "mode": "lexical", "topK": 10},
                )
                turn_dense = index.retrieve(
                    query_id="memory-tea",
                    query_text="Which tea do I prefer?",
                    config={"granularity": "turn", "mode": "dense", "topK": 10},
                )
                multi_granularity = index.retrieve(
                    query_id="memory-tea",
                    query_text="Which tea do I prefer?",
                    config={
                        "granularity": "session_turn",
                        "mode": "hybrid",
                        "topK": 10,
                        "sessionWeight": 3.0,
                        "turnWeight": 1.0,
                    },
                )
                session_dense = index.retrieve(
                    query_id="memory-tea",
                    query_text="Which tea do I prefer?",
                    config={"granularity": "session", "mode": "dense", "topK": 10},
                )
                boundary = index.boundary_receipt()
            finally:
                index.close()

        self.assertEqual(2, build["sessionDocuments"])
        self.assertEqual(3, build["turnDocuments"])
        self.assertEqual(5, build["vectorEligibleDocuments"])
        self.assertEqual(5, build["vectors"]["documents"])
        self.assertEqual("session-answer", session_lexical["sessionIds"][0])
        self.assertEqual("session-answer", turn_lexical["sessionIds"][0])
        self.assertEqual("session-answer", turn_dense["sessionIds"][0])
        self.assertEqual("session-answer", multi_granularity["sessionIds"][0])
        self.assertEqual(
            "weighted_rrf",
            multi_granularity["lanes"]["fusion"]["algorithm"],
        )
        self.assertEqual("session-answer", session_dense["sessionIds"][0])
        self.assertEqual("memory", boundary["system"])
        self.assertEqual(0, boundary["documentLibraryRows"])
        self.assertEqual(0, boundary["knowledgeTableRows"])
        self.assertTrue(boundary["passed"])

    def test_official_user_projection_excludes_assistant_text(self) -> None:
        case = {
            "system": "memory",
            "queryId": "memory-role-boundary",
            "sessions": [
                {
                    "sessionId": "assistant-only",
                    "date": "2026/08/03 (Mon) 12:00",
                    "turns": [
                        {"role": "user", "content": "Unrelated request.", "hasAnswer": False},
                        {
                            "role": "assistant",
                            "content": "The secret retrieval token is chrysanthemum.",
                            "hasAnswer": True,
                        },
                    ],
                },
                {
                    "sessionId": "user-target",
                    "date": "2026/08/02 (Sun) 12:00",
                    "turns": [
                        {
                            "role": "user",
                            "content": "The user retrieval token is chrysanthemum.",
                            "hasAnswer": True,
                        }
                    ],
                },
            ],
        }

        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-profile-index-") as temporary:
            official = LongMemEvalMemoryIndex(Path(temporary) / "official.sqlite")
            product = LongMemEvalMemoryIndex(Path(temporary) / "product.sqlite")
            try:
                official_build = official.build(
                    [case],
                    include_turn_index=True,
                    content_profile="official-user",
                )
                product_build = product.build(
                    [case],
                    include_turn_index=True,
                    content_profile="product-all-turn",
                )
                official_result = official.retrieve(
                    query_id="memory-role-boundary",
                    query_text="secret retrieval token chrysanthemum",
                    config={"granularity": "session", "mode": "lexical", "topK": 10},
                )
                product_result = product.retrieve(
                    query_id="memory-role-boundary",
                    query_text="secret retrieval token chrysanthemum",
                    config={"granularity": "session", "mode": "lexical", "topK": 10},
                )
            finally:
                official.close()
                product.close()

        self.assertEqual("official-user", official_build["contentProfile"])
        self.assertEqual("product-all-turn", product_build["contentProfile"])
        self.assertEqual("user-target", official_result["sessionIds"][0])
        self.assertEqual("assistant-only", product_result["sessionIds"][0])

    def test_index_rejects_knowledge_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-longmemeval-boundary-") as temporary:
            index = LongMemEvalMemoryIndex(Path(temporary) / "memory.sqlite")
            try:
                with self.assertRaisesRegex(ValueError, "Memory cases only"):
                    index.build(
                        [
                            {
                                "system": "knowledge",
                                "queryId": "wrong-system",
                                "sessions": [],
                            }
                        ],
                        content_profile="official-user",
                    )
            finally:
                index.close()


if __name__ == "__main__":
    unittest.main()
