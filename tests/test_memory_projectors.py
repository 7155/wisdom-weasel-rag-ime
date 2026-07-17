from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.hybrid_rag_models import HybridRagHit, HybridRagQuery, MemoryHit
from rag_ime.hybrid_rag_ranker import rank_hybrid_hits_to_memory_hits
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_candidates
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.memory_projectors import AgentMemoryProjector, ImeMemoryProjector
from rag_ime.rag_core_v3 import retrieve_candidates_v3
from rag_ime.retrieval_docs import rebuild_retrieval_docs
from rag_ime.text_utils import now_ms


class MemoryProjectorTests(unittest.TestCase):
    def test_book_is_shared_agent_evidence_but_not_ime_insert_text(self) -> None:
        raw_hit = HybridRagHit(
            doc_id="book:input-method",
            doc_type="book",
            source_id="input-method",
            text="当前输入法已经从 0.8B 模型切换到 100M 自训练模型。",
            surface_hints=(),
            tags=("输入法", "模型切换"),
            source_lane="bm25_raw",
            rank=1,
            raw_score=-2.0,
            metadata={"sourceEventIds": [41, 42]},
        )

        memory_hits = rank_hybrid_hits_to_memory_hits(
            [raw_hit],
            query_text="输入法模型",
        )
        ime = ImeMemoryProjector().project(memory_hits, query_text="输入法模型")
        agent = AgentMemoryProjector().project(
            memory_hits,
            project="wisdom-weasel-rag-ime",
            query="输入法现在用什么模型",
        )

        self.assertEqual(len(memory_hits), 1)
        self.assertEqual(ime, [])
        self.assertIn("100M 自训练模型", agent.block)
        self.assertIn("evidenceEventIds=41,42", agent.block)
        self.assertEqual(agent.source_event_ids, (41, 42))

    def test_local_agent_context_uses_shared_hits_not_legacy_retrieval(self) -> None:
        hit = _memory_hit()
        with tempfile.TemporaryDirectory(prefix="rag-ime-agent-projector-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            with patch(
                "rag_ime.local_sqlite_core.retrieve_hybrid_rag_memory_hit_objects",
                return_value=[hit],
            ) as shared, patch.object(
                core,
                "retrieve_memories",
                side_effect=AssertionError("legacy retrieval must not be used"),
            ):
                injection = core.build_agent_context(
                    project="wisdom-weasel-rag-ime",
                    query="当前模型",
                )

        self.assertIn("100M 自训练模型", injection.block)
        self.assertEqual(injection.source_event_ids, (88,))
        self.assertEqual(shared.call_args.args[1].input_mode, "agent_context")

    def test_explicit_history_query_performs_no_sqlite_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-query-read-only-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            core.initialize()
            with core._connect() as conn:  # type: ignore[attr-defined]
                _insert_archived_book(conn)
                rebuild_retrieval_docs(conn)

            with core._connect() as conn:  # type: ignore[attr-defined]
                denied: list[tuple[int, str]] = []
                write_actions = {
                    sqlite3.SQLITE_INSERT,
                    sqlite3.SQLITE_UPDATE,
                    sqlite3.SQLITE_DELETE,
                    sqlite3.SQLITE_CREATE_INDEX,
                    sqlite3.SQLITE_CREATE_TABLE,
                    sqlite3.SQLITE_DROP_INDEX,
                    sqlite3.SQLITE_DROP_TABLE,
                }

                def authorizer(
                    action: int,
                    arg1: str | None,
                    _arg2: str | None,
                    _database: str | None,
                    _trigger: str | None,
                ) -> int:
                    if action in write_actions:
                        denied.append((action, str(arg1 or "")))
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                conn.set_authorizer(authorizer)
                payload = retrieve_hybrid_rag_candidates(
                    conn,
                    HybridRagQuery(
                        query_text="查找最初需求里的旧输入法主题",
                        top_k=5,
                        latency_budget_ms=1000,
                    ),
                )
                conn.set_authorizer(None)
                status = conn.execute(
                    "SELECT status FROM memory_books WHERE book_id = 'book:topic:legacy-ime'"
                ).fetchone()[0]

        self.assertEqual(denied, [])
        self.assertEqual(status, "archived")
        self.assertEqual(payload["reactivatedBookIds"], [])
        self.assertEqual(payload["historicalBookIds"], ["book:topic:legacy-ime"])

    def test_rag_core_v3_query_path_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rag-ime-v3-read-only-") as tmp:
            core = LocalSqliteCoreClient(Path(tmp) / "rag-ime.sqlite")
            core.initialize()
            with core._connect() as conn:  # type: ignore[attr-defined]
                _insert_archived_book(conn)
                rebuild_retrieval_docs(conn)

            with core._connect() as conn:  # type: ignore[attr-defined]
                writes: list[str] = []
                write_actions = {
                    sqlite3.SQLITE_INSERT,
                    sqlite3.SQLITE_UPDATE,
                    sqlite3.SQLITE_DELETE,
                }

                def authorizer(
                    action: int,
                    arg1: str | None,
                    _arg2: str | None,
                    _database: str | None,
                    _trigger: str | None,
                ) -> int:
                    if action in write_actions:
                        writes.append(str(arg1 or ""))
                        return sqlite3.SQLITE_DENY
                    return sqlite3.SQLITE_OK

                conn.set_authorizer(authorizer)
                retrieve_candidates_v3(
                    conn,
                    current_input="查找最初需求里的旧输入法主题",
                    top_k=5,
                    source_budget_ms=1000,
                )
                conn.set_authorizer(None)

        self.assertEqual(writes, [])


def _memory_hit() -> MemoryHit:
    return MemoryHit(
        hit_id="hybrid:book:model",
        doc_id="book:model",
        doc_type="book",
        source_id="model",
        text="当前使用 100M 自训练模型，旧 0.8B 模型已经下线。",
        surface_hints=(),
        source_type="memory",
        source_lane="bm25_raw",
        score=0.8,
        confidence=0.9,
        tags=("输入法",),
        memory_ids=(),
        atom_ids=(),
        book_ids=("model",),
        evidence_event_ids=(88,),
        evidence_preview="当前使用 100M 自训练模型",
        metadata={"lanes": ["bm25_raw"]},
    )


def _insert_archived_book(conn: sqlite3.Connection) -> None:
    timestamp = now_ms()
    conn.execute(
        """
        INSERT INTO memory_books(
            book_id, book_type, book_key, title, summary, normalized_text,
            project, app, tags_json, surface_hints_json, query_expansions_json,
            source_event_ids_json, memory_atom_ids_json, status, confidence,
            quality_score, created_at_ms, updated_at_ms, metadata_json,
            archived_at_ms, last_active_at_ms, archive_reason
        ) VALUES (
            'book:topic:legacy-ime', 'topic', 'legacy-ime', '旧输入法主题',
            '旧输入法主题的长期摘要', '旧输入法主题', '', '', '[]', '[]', '[]',
            '[]', '[]', 'archived', 0.8, 0.8, ?, ?, '{}', ?, ?, 'inactive'
        )
        """,
        (timestamp, timestamp, timestamp, timestamp),
    )


if __name__ == "__main__":
    unittest.main()
