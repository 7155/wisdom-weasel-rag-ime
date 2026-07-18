from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_book_compiler import apply_memory_book_plan, memory_book_plan_from_compile_output
from rag_ime.models import InputEvent
from rag_ime.rag_core_v3 import memory_candidates_v2_to_input_suggestions
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import now_ms


class RagCoreV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-rag-core-v3-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_hybrid_core_output_converts_to_input_suggestion(self) -> None:
        self._record_event("多路召回", recent_context="RAG 输入法", tags=("RAG", "检索"))

        candidates = self.core.retrieve_candidates_v3(
            current_input="多路召回",
            project="wisdom-weasel-rag-ime",
            top_k=3,
        )
        suggestions = memory_candidates_v2_to_input_suggestions(candidates)

        self.assertEqual(candidates[0].text, "多路召回")
        self.assertEqual(candidates[0].diagnostics["schemaVersion"], "rag-ime.rag-core-v3.v1")
        self.assertEqual(suggestions[0].surface_text, "多路召回")
        self.assertEqual(suggestions[0].metadata["rag_core"], "v3")

    def test_hybrid_core_does_not_surface_daily_book_summary_as_candidate(self) -> None:
        event_id = self._record_event("RAG 输入法多路召回方案", tags=("RAG",))
        with self.core._connect() as conn:
            apply_memory_book_plan(
                conn,
                memory_book_plan_from_compile_output(
                    _book_compile_output(event_id),
                    project="wisdom-weasel-rag-ime",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                ),
            )
            rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")

        candidates = self.core.retrieve_candidates_v3(
            current_input="Daily Book",
            project="wisdom-weasel-rag-ime",
            top_k=3,
        )
        texts = [item.text for item in candidates]

        self.assertIn("多路召回", texts)
        self.assertNotIn("RAG 输入法多路召回方案", texts)
        self.assertNotIn("用户希望借鉴 VCP 的 BM25、向量、TagMemo 和 Time。", texts)
        self.assertTrue(all("用户希望借鉴" not in text for text in texts))

    def _record_event(self, text: str, *, recent_context: str = "", tags: tuple[str, ...] = ()) -> int:
        memory_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual",
                committed_text=text,
                privacy_disposition="allowed",
                recent_context=recent_context,
                project="wisdom-weasel-rag-ime",
                tags=tags,
            )
        )
        event_id = int(memory_id.split(":", 1)[1])
        if 2 <= len(text) <= 18:
            with self.core._connect() as conn:
                apply_memory_book_plan(
                    conn,
                    memory_book_plan_from_compile_output(
                        {
                            "phraseCandidates": [
                                {"text": text, "tags": list(tags), "sourceEventIds": [event_id], "weight": 0.8}
                            ]
                        },
                        project="wisdom-weasel-rag-ime",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                    ),
                )
                rebuild_retrieval_docs(conn, project="wisdom-weasel-rag-ime")
        return event_id


def _book_compile_output(event_id: int) -> dict[str, object]:
    return {
        "schemaVersion": "rag-ime.memory-book-compile.v1",
        "dailyBooks": [
            {
                "bookKey": "2026-07-06",
                "title": "RAG 输入法多路召回方案",
                "summary": "用户希望借鉴 VCP 的 BM25、向量、TagMemo 和 Time。",
                "tags": ["RAG", "输入法", "VCP"],
                "surfaceHints": ["多路召回", "TagMemo"],
                "queryExpansions": ["VCP RAG", "Daily Book"],
                "sourceEventIds": [event_id],
                "confidence": 0.86,
            }
        ],
        "memoryAtoms": [],
        "tagEdges": [],
        "phraseCandidates": [],
        "warnings": [],
    }


if __name__ == "__main__":
    unittest.main()
