from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rag_ime.adapter import InputMethodAdapter, SuggestionRequest
from rag_ime.agent_hook import build_first_run_injection
from rag_ime.cli import main, run_acceptance, seed_demo_memories
from rag_ime.core_client import default_fixture_memories
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.models import MemoryAction


class LocalSqliteCoreClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="rag-ime-core-test-")
        self.db_path = Path(self.tmp.name) / "rag-ime.sqlite"
        self.core = LocalSqliteCoreClient(self.db_path)
        self.core.initialize()
        self.adapter = InputMethodAdapter(self.core)
        seed_demo_memories(self.adapter, default_fixture_memories())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_records_events_into_sqlite_and_retrieves_with_fts5(self) -> None:
        self.assertGreaterEqual(self.core.event_count(), 8)
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="SQLite 和 FTS5 第一版",
                recent_context="MVP 先 local-first, 先验证检索和排序",
                top_k=5,
            )
        )
        surfaces = [item.surface_text for item in suggestions]
        self.assertIn("先用 FTS5 证明召回收益", surfaces)
        self.assertTrue(all(item.evidence_preview for item in suggestions))
        self.assertTrue(all(item.metadata.get("memory_id", "").startswith("event:") for item in suggestions))

    def test_negative_fts5_bm25_score_affects_ranking(self) -> None:
        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="Squirrel RAG 输入法候选",
                recent_context="本地记忆",
                top_k=3,
            )
        )
        self.assertEqual(suggestions[0].surface_text, "把本地记忆注入 Agent 首次运行上下文")
        self.assertIn("fts5:", suggestions[0].metadata["reason"])

    def test_query_expansion_recalls_agent_context_injection_memory(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "生成 PROJECT_MEMORY_BLOCK",
            recent_context="Agent 首次运行自动注入背景记忆",
            tags=("agent-hook", "context"),
        )
        self.adapter.commit_text(
            "普通 debug page 背景材料",
            recent_context="浏览器调试页面展示 pipeline",
            tags=("debug",),
        )

        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="首次运行自动注入背景记忆",
                top_k=2,
            )
        )

        self.assertEqual(suggestions[0].surface_text, "生成 PROJECT_MEMORY_BLOCK")
        self.assertIn("context:", suggestions[0].metadata["reason"])

    def test_squirrel_rime_tags_and_source_boost_side_candidate_memory(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "输入法候选需要保持短小",
            recent_context="debug page",
            tags=("debug",),
        )
        self.adapter.commit_text(
            "Squirrel side candidates 使用本地记忆作为候选",
            recent_context="Rime sidecar 合并候选 本地记忆",
            source="squirrel_rime_sidecar",
            app="squirrel",
            tags=("squirrel", "rime", "memory"),
        )

        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="Squirrel RAG 输入法候选",
                recent_context="本地记忆",
                top_k=2,
            )
        )

        self.assertEqual(suggestions[0].surface_text, "Squirrel side candidates 使用本地记忆作为候选")
        self.assertIn("tag:", suggestions[0].metadata["reason"])
        self.assertIn("raw:", suggestions[0].metadata["reason"])

    def test_suggestion_cache_hits_and_invalidates_on_write(self) -> None:
        request = SuggestionRequest(
            current_input="SQLite 和 FTS5 第一版",
            recent_context="MVP 先 local-first, 先验证检索和排序",
            top_k=5,
        )
        first = self.adapter.suggest(request)
        after_first = self.core.suggestion_cache_stats()
        second = self.adapter.suggest(request)
        after_second = self.core.suggestion_cache_stats()
        self.assertEqual([item.suggestion_id for item in first], [item.suggestion_id for item in second])
        self.assertEqual(after_first["misses"], 1)
        self.assertEqual(after_second["hits"], 1)
        self.assertEqual(after_second["size"], 1)

        self.adapter.commit_text("新的缓存失效事件", recent_context="cache invalidation")
        after_commit = self.core.suggestion_cache_stats()
        self.assertEqual(after_commit["size"], 0)
        self.assertEqual(after_commit["invalidations"], 1)

        self.adapter.suggest(request)
        after_refill = self.core.suggestion_cache_stats()
        self.assertEqual(after_refill["misses"], 2)
        self.assertEqual(after_refill["size"], 1)

    def test_suggestion_cache_eviction_uses_lru_bound(self) -> None:
        core = LocalSqliteCoreClient(self.db_path, suggestion_cache_size=1)
        adapter = InputMethodAdapter(core)
        adapter.suggest(SuggestionRequest(current_input="FTS5", top_k=2))
        adapter.suggest(SuggestionRequest(current_input="PROJECT_MEMORY_BLOCK", top_k=2))
        stats = core.suggestion_cache_stats()
        self.assertEqual(stats["size"], 1)
        self.assertEqual(stats["evictions"], 1)

    def test_delete_pin_and_downrank_are_durable_actions(self) -> None:
        request = SuggestionRequest(
            current_input="SQLite 和 FTS5 第一版",
            recent_context="MVP 先 local-first, 先验证检索和排序",
            top_k=4,
        )
        before = self.adapter.suggest(request)
        deleted = before[0]
        pinned = before[-1]
        self.adapter.delete(deleted, query=request.current_input)
        self.adapter.pin(pinned, query=request.current_input)
        self.adapter.downrank(before[1], query=request.current_input)
        after = self.adapter.suggest(request)
        self.assertNotIn(deleted.surface_text, [item.surface_text for item in after])
        self.assertEqual(after[0].metadata["memory_id"], pinned.metadata["memory_id"])
        self.assertEqual(self.core.action_count(), 3)

    def test_apply_action_accepts_suggestion_id_fallback_shape(self) -> None:
        suggestions = self.adapter.suggest(SuggestionRequest(current_input="FTS5", top_k=1))
        suggestion = suggestions[0]
        action = self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=suggestion.suggestion_id,
                action_type="pin",
                query="FTS5",
                suggestion_id=suggestion.suggestion_id,
            )
        )
        self.assertEqual(action.source_event_id, suggestion.source_event_id)

    def test_sensitive_commit_is_not_written_to_local_db(self) -> None:
        before = self.core.event_count()
        result = self.adapter.commit_text("银行卡密码", field_is_sensitive=True)
        self.assertEqual(result, "skipped:sensitive_field")
        self.assertEqual(self.core.event_count(), before)

    def test_cli_commit_accepts_source_for_squirrel_events(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "--db-path",
                    str(self.db_path),
                    "commit",
                    "Squirrel side candidate",
                    "--source",
                    "squirrel_rime_sidecar",
                    "--tag",
                    "squirrel",
                ]
            )
        self.assertEqual(code, 0)
        with sqlite3.connect(self.db_path) as conn:
            source = conn.execute(
                "SELECT source FROM input_events WHERE committed_text = ?",
                ("Squirrel side candidate",),
            ).fetchone()[0]
        self.assertEqual(source, "squirrel_rime_sidecar")

    def test_agent_hook_reads_from_local_memory_db(self) -> None:
        injection = build_first_run_injection(
            self.adapter,
            project="wisdom-weasel-rag-ime",
            query="Agent 首次运行 PROJECT_MEMORY_BLOCK",
            top_k=3,
        )
        self.assertIn("PROJECT_MEMORY_BLOCK", injection.block)
        self.assertIn("local SQLite/FTS5", injection.block)
        self.assertGreaterEqual(len(injection.source_event_ids), 1)

    def test_recent_input_context_uses_recent_committed_history(self) -> None:
        self.adapter.commit_text(
            "第一条历史输入",
            recent_context="设计 outbox 方案",
            preedit="diyi",
            tags=("history",),
        )
        self.adapter.commit_text(
            "第二条历史输入",
            recent_context="继续写 RAG 输入法",
            preedit="dier",
            tags=("history",),
        )
        context = self.core.recent_input_context(project="wisdom-weasel-rag-ime", limit=2, max_chars=220)
        self.assertIn("第一条历史输入", context)
        self.assertIn("第二条历史输入", context)
        self.assertLess(context.index("第一条历史输入"), context.index("第二条历史输入"))
        self.assertIn("继续写 RAG 输入法", context)

    def test_acceptance_can_run_against_local_sqlite_core(self) -> None:
        report = run_acceptance(self.adapter)
        self.assertTrue(report["local_first"])
        self.assertFalse(report["cloud_default"])
        self.assertTrue(report["action_result"]["deleted_removed"])
        self.assertTrue(report["agent_hook"]["has_project_memory_block"])


if __name__ == "__main__":
    unittest.main()
