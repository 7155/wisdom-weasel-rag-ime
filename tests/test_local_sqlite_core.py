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
from rag_ime.models import InputEvent, MemoryAction
from rag_ime.text_utils import now_ms


DAY_MS = 24 * 60 * 60 * 1000


class SemanticTestEmbeddingProvider:
    fingerprint = "test-semantic:v1"

    def embed(self, text: str) -> list[float]:
        if "火星任务" in text or "赤色星球" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


class CapturingEmbeddingProvider:
    fingerprint = "test-capturing:v1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if "embedding 检索" in text or "上下文窗口" in text:
            return [1.0, 0.0]
        return [0.0, 1.0]


class WeakNoisyEmbeddingProvider:
    fingerprint = "test-weak-noisy:v1"

    def embed(self, text: str) -> list[float]:
        if "撤旦" in text:
            return [1.0, 0.0]
        return [0.2, 0.98]


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

    def test_initialize_prunes_orphan_memory_state_and_vectors(self) -> None:
        orphan_event_id = 999_999
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, ?)", (orphan_event_id, now_ms()))
            conn.execute(
                "INSERT INTO memory_vectors(event_id, provider_fingerprint, vector_json, updated_at_ms) VALUES (?, ?, ?, ?)",
                (orphan_event_id, "orphan-provider", "[1.0]", now_ms()),
            )
            conn.execute(
                """
                INSERT INTO memory_actions(created_at_ms, memory_id, event_id, action_type)
                VALUES (?, ?, ?, ?)
                """,
                (now_ms(), f"event:{orphan_event_id}", orphan_event_id, "accepted"),
            )

        self.core.initialize()

        with sqlite3.connect(self.db_path) as conn:
            state_count = conn.execute("SELECT COUNT(*) FROM memory_state WHERE event_id = ?", (orphan_event_id,)).fetchone()[0]
            vector_count = conn.execute("SELECT COUNT(*) FROM memory_vectors WHERE event_id = ?", (orphan_event_id,)).fetchone()[0]
            action_event_id = conn.execute("SELECT event_id FROM memory_actions WHERE memory_id = ?", (f"event:{orphan_event_id}",)).fetchone()[0]
        self.assertEqual(state_count, 0)
        self.assertEqual(vector_count, 0)
        self.assertIsNone(action_event_id)

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

    def test_query_expansion_recalls_product_runtime_terms(self) -> None:
        self.core.reset()
        cases = [
            (
                "候选字和候选段如何共用数字键",
                "Rime candidates share the number sequence with side candidates",
            ),
            (
                "Squirrel 如何区分 Rime 候选和 side candidate 选择",
                "select_candidate_on_current_page keeps Rime selection separate from commit_side_candidate",
            ),
            (
                "RAG 和模型预测如何用同一 case 比较",
                "eval-comparison compares RAG candidates with model prediction on the same case file",
            ),
            (
                "raw pinyin fallback 什么时候跳过 RAG side lane",
                "triggerDecision sets sideCandidatesEnabled=false for rawInputFallback",
            ),
            (
                "模型预测如何使用历史输入上下文",
                "historyContext is built from recent_input_context before prediction",
            ),
            (
                "本地小模型 predictor 怎么接 OpenAI compatible",
                "Set RAG_IME_PREDICTOR_BASE_URL for the openai-compatible predictor",
            ),
            (
                "Rime sidecar 重复刷新如何缓存命中",
                "Debug health reports rimeSuggestCache and cacheStats for cache hit inspection",
            ),
            (
                "WSL embedding endpoint 需要哪些环境变量",
                "RAG_IME_EMBEDDING_BASE_URL and RAG_IME_EMBEDDING_MODEL configure WSL embedding endpoint",
            ),
            (
                "本地 suggestion cache 如何统计命中和失效",
                "suggestionCache uses LRU hitRate evictions invalidations",
            ),
            (
                "Codex history eval 用哪些 ranking metrics",
                "top1Accuracy and meanReciprocalRank report ranking metrics",
            ),
        ]
        for _, target in cases:
            self.adapter.commit_text(target, recent_context="runtime term mapping", tags=("runtime",))
        self.adapter.commit_text("普通中文候选调试", recent_context="无关记录")

        for query, expected in cases:
            with self.subTest(query=query):
                suggestions = self.adapter.suggest(SuggestionRequest(current_input=query, top_k=1))
                self.assertIn(expected, suggestions[0].expanded_evidence)
                self.assertLessEqual(len(suggestions[0].surface_text), 42)
                self.assertEqual(suggestions[0].metadata["insert_text"], suggestions[0].surface_text)

    def test_suggestions_deduplicate_repeated_memory_surfaces(self) -> None:
        self.core.reset()
        self.adapter.commit_text("重复候选内容", recent_context="RAG 输入法候选 重复记录")
        self.adapter.commit_text("重复候选内容", recent_context="RAG 输入法候选 重复记录 第二次")
        self.adapter.commit_text("新的候选内容", recent_context="RAG 输入法候选 另一条")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="RAG 输入法候选 重复", top_k=3))
        surfaces = [item.surface_text for item in suggestions]

        self.assertEqual(surfaces.count("重复候选内容"), 1)
        self.assertIn("新的候选内容", surfaces)

    def test_suggestions_skip_low_value_one_character_memory_surfaces(self) -> None:
        self.core.reset()
        self.adapter.commit_text("嗯", recent_context="RAG 输入法候选 语气词")
        self.adapter.commit_text("当", recent_context="RAG 输入法候选 单字噪声")
        self.adapter.commit_text("高频实时场景里的个人记忆系统", recent_context="RAG 输入法候选 高频记忆")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="RAG 输入法候选", top_k=5))
        surfaces = [item.surface_text for item in suggestions]

        self.assertNotIn("嗯", surfaces)
        self.assertNotIn("当", surfaces)
        self.assertIn("高频实时场景里的个人记忆系统", surfaces)

    def test_suggestions_include_pinyin_metadata_for_prefix_constrained_memory(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "设计一个候选展示方式",
            recent_context="Prediction-first RAG IME 需要用户继续输入 sj 时约束历史短语候选",
            tags=("phrase-memory",),
        )

        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="候选展示",
                recent_context="输入法设计",
                top_k=1,
            )
        )

        self.assertEqual(suggestions[0].surface_text, "设计一个候选展示方式")
        self.assertEqual(suggestions[0].metadata["initials"], "sjyghxzsfs")
        self.assertIn("sjyghxzsfs", suggestions[0].metadata["pinyin_prefixes"])
        self.assertIn("hx", suggestions[0].metadata["pinyin_prefixes"])

    def test_recent_input_context_skips_generated_side_candidates(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "真实用户输入要保留到模型上下文",
            recent_context="用户正在写 RAG 输入法调试记录",
            tags=("user-input",),
        )
        self.adapter.commit_text(
            "模型生成候选不应继续污染历史",
            source="squirrel_rime_sidecar",
            provider_name="rime-sidecar:model",
            tags=("squirrel", "rime-sidecar", "source:model"),
        )
        self.adapter.commit_text(
            "RAG 生成候选不应被模型复读",
            source="squirrel_rime_sidecar",
            provider_name="rime-sidecar:rag",
            tags=("squirrel", "rime-sidecar", "source:rag"),
        )

        context = self.core.recent_input_context(limit=5)

        self.assertIn("真实用户输入要保留到模型上下文", context)
        self.assertNotIn("模型生成候选不应继续污染历史", context)
        self.assertNotIn("RAG 生成候选不应被模型复读", context)

    def test_sqlite_fts_recalls_memory_by_pinyin_prefix(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "设计一个候选展示方式",
            recent_context="Prediction-first RAG IME 需要用户继续输入 sj 时约束历史短语候选",
            tags=("phrase-memory",),
        )
        self.adapter.commit_text("普通中文候选兜底", recent_context="输入法候选")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="sj", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "设计一个候选展示方式")
        self.assertIn("pinyin:", suggestions[0].metadata["reason"])

    def test_accepted_count_boosts_frequently_selected_memory(self) -> None:
        self.core.reset()
        frequent_id = self.adapter.commit_text("高频候选方案", recent_context="输入法 频率 候选方案")
        self.adapter.commit_text("普通候选方案", recent_context="输入法 频率 候选方案")

        for _ in range(4):
            self.core.apply_action(
                MemoryAction(
                    action_id=None,
                    created_at_ms=0,
                    memory_id=frequent_id,
                    action_type="accepted",
                    query="输入法 频率 候选方案",
                )
            )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="输入法 频率 候选方案", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "高频候选方案")
        self.assertIn("accepted:4", suggestions[0].metadata["reason"])

    def test_repeated_committed_text_boosts_input_frequency(self) -> None:
        self.core.reset()
        self.adapter.commit_text("高频候选方案", recent_context="输入法 词频 候选方案")
        self.adapter.commit_text("高频候选方案", recent_context="输入法 词频 候选方案 第二次")
        self.adapter.commit_text("普通候选方案", recent_context="输入法 词频 候选方案 最新")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="输入法 词频 候选方案", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "高频候选方案")
        self.assertIn("frequency:2", suggestions[0].metadata["reason"])
        self.assertEqual(suggestions[0].metadata["state"]["input_frequency"], 2)

    def test_phrase_frequency_uses_recentness_decay(self) -> None:
        self.core.reset()
        now = now_ms()
        for index in range(8):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now - 120 * DAY_MS + index,
                    source="test",
                    committed_text="旧高频候选方案",
                    recent_context="输入法 词频 候选方案",
                    project="wisdom-weasel-rag-ime",
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="近期候选方案",
                recent_context="输入法 词频 候选方案",
                project="wisdom-weasel-rag-ime",
            )
        )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="输入法 词频 候选方案", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "近期候选方案")
        self.assertIn("recent:", suggestions[0].metadata["reason"])
        self.assertGreater(suggestions[0].metadata["state"]["recent_boost"], 0)
        self.assertEqual(suggestions[1].surface_text, "旧高频候选方案")
        self.assertIn("frequency:8", suggestions[1].metadata["reason"])
        self.assertGreater(suggestions[1].metadata["state"]["phrase_age_days"], 100)

    def test_phrase_stats_refreshes_after_delete(self) -> None:
        self.core.reset()
        first_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_000,
                source="test",
                committed_text="可删除高频候选",
                recent_context="输入法 词频 候选方案",
                project="wisdom-weasel-rag-ime",
            )
        )
        second_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_001_000,
                source="test",
                committed_text="可删除高频候选",
                recent_context="输入法 词频 候选方案",
                project="wisdom-weasel-rag-ime",
            )
        )

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=first_id,
                action_type="delete",
                query="输入法 词频 候选方案",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            remaining = conn.execute(
                "SELECT input_frequency FROM phrase_stats WHERE committed_text = ?",
                ("可删除高频候选",),
            ).fetchone()[0]
        self.assertEqual(remaining, 1)

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=second_id,
                action_type="delete",
                query="输入法 词频 候选方案",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            gone = conn.execute(
                "SELECT input_frequency FROM phrase_stats WHERE committed_text = ?",
                ("可删除高频候选",),
            ).fetchone()
        self.assertIsNone(gone)

    def test_hide_codex_history_noise_keeps_user_rows_and_rebuilds_phrase_stats(self) -> None:
        self.core.reset()
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_000_000,
                source="codex_history",
                committed_text="用户真正提出的 RAG 输入法需求",
                recent_context="codex_history:session.jsonl:1 role:user",
                app="codex",
                project="wisdom-weasel-rag-ime",
                tags=("codex-history", "role:user", "record:user01"),
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_001_000,
                source="codex_history",
                committed_text="Working (44m 30s) esc to interrupt",
                recent_context="codex status stream",
                app="codex",
                project="wisdom-weasel-rag-ime",
                tags=("codex-history", "role:event_msg", "record:event01"),
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=1_900_000_002_000,
                source="codex_history",
                committed_text="我会先检查数据库再修改导入器",
                recent_context="codex assistant narration",
                app="codex",
                project="wisdom-weasel-rag-ime",
                tags=("codex-history", "role:assistant", "record:assistant01"),
            )
        )

        dry_run = self.core.hide_codex_history_noise(project="wisdom-weasel-rag-ime", dry_run=True)
        report = self.core.hide_codex_history_noise(project="wisdom-weasel-rag-ime")

        self.assertEqual(dry_run["wouldHide"], 2)
        self.assertEqual(dry_run["hidden"], 0)
        self.assertEqual(report["hidden"], 2)
        with sqlite3.connect(self.db_path) as conn:
            active_rows = conn.execute(
                """
                SELECT e.committed_text
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE e.source = 'codex_history' AND s.deleted = 0
                ORDER BY e.id
                """
            ).fetchall()
            hidden_status_stat = conn.execute(
                "SELECT 1 FROM phrase_stats WHERE committed_text = ?",
                ("Working (44m 30s) esc to interrupt",),
            ).fetchone()
            action_count = conn.execute(
                "SELECT COUNT(*) FROM memory_actions WHERE action_type = 'hide' AND query = 'codex-history-noise-prune'"
            ).fetchone()[0]

        self.assertEqual([row[0] for row in active_rows], ["用户真正提出的 RAG 输入法需求"])
        self.assertIsNone(hidden_status_stat)
        self.assertEqual(action_count, 2)

    def test_project_phrase_frequency_does_not_leak_between_projects(self) -> None:
        self.core.reset()
        now = now_ms()
        for index in range(8):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now - 10_000 + index,
                    source="test",
                    committed_text="npm run dev",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-b",
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="npm run dev",
                recent_context="vibe coding command",
                app="codex",
                project="project-a",
            )
        )
        for index in range(3):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index + 1,
                    source="test",
                    committed_text="npm run test",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-a",
                )
            )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="npm run", project="project-a", top_k=3))

        self.assertEqual(suggestions[0].surface_text, "npm run test")
        self.assertIn("project-frequency:3", suggestions[0].metadata["reason"])
        dev = next(item for item in suggestions if item.surface_text == "npm run dev")
        self.assertEqual(dev.metadata["state"]["input_frequency"], 9)
        self.assertEqual(dev.metadata["state"]["project_input_frequency"], 1)
        self.assertEqual(dev.metadata["state"]["effective_frequency"], 1)
        self.assertEqual(dev.metadata["state"]["effective_frequency_scope"], "project")
        self.assertNotIn("frequency:9", dev.metadata["reason"])

    def test_project_phrase_stats_refreshes_after_delete(self) -> None:
        self.core.reset()
        first_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="test",
                committed_text="项目内高频命令",
                recent_context="vibe coding command",
                project="project-a",
            )
        )
        second_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms() + 1,
                source="test",
                committed_text="项目内高频命令",
                recent_context="vibe coding command",
                project="project-a",
            )
        )

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=first_id,
                action_type="delete",
                query="项目内高频命令",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            remaining = conn.execute(
                "SELECT input_frequency FROM phrase_project_stats WHERE committed_text = ? AND project = ?",
                ("项目内高频命令", "project-a"),
            ).fetchone()[0]
        self.assertEqual(remaining, 1)

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=second_id,
                action_type="delete",
                query="项目内高频命令",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            gone = conn.execute(
                "SELECT input_frequency FROM phrase_project_stats WHERE committed_text = ? AND project = ?",
                ("项目内高频命令", "project-a"),
            ).fetchone()
        self.assertIsNone(gone)

    def test_app_phrase_frequency_does_not_leak_between_apps(self) -> None:
        self.core.reset()
        now = now_ms()
        for index in range(7):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now - 20_000 + index,
                    source="test",
                    committed_text="打开开发者工具",
                    recent_context="浏览器 调试 快捷操作",
                    app="browser",
                    project="",
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="打开开发者工具",
                recent_context="浏览器 调试 快捷操作",
                app="codex",
                project="",
            )
        )
        for index in range(3):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index + 1,
                    source="test",
                    committed_text="打开代码上下文",
                    recent_context="codex 调试 快捷操作",
                    app="codex",
                    project="",
                )
            )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="打开 调试", app="codex", project="", top_k=3))

        self.assertEqual(suggestions[0].surface_text, "打开代码上下文")
        self.assertIn("app-frequency:3", suggestions[0].metadata["reason"])
        browser_phrase = next(item for item in suggestions if item.surface_text == "打开开发者工具")
        self.assertEqual(browser_phrase.metadata["state"]["input_frequency"], 8)
        self.assertEqual(browser_phrase.metadata["state"]["app_input_frequency"], 1)
        self.assertEqual(browser_phrase.metadata["state"]["effective_frequency"], 1)
        self.assertEqual(browser_phrase.metadata["state"]["effective_frequency_scope"], "app")
        self.assertNotIn("frequency:8", browser_phrase.metadata["reason"])

    def test_project_frequency_takes_precedence_over_app_frequency(self) -> None:
        self.core.reset()
        now = now_ms()
        for index in range(5):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index,
                    source="test",
                    committed_text="npm run dev",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-b",
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 10,
                source="test",
                committed_text="npm run dev",
                recent_context="vibe coding command",
                app="codex",
                project="project-a",
            )
        )

        suggestions = self.adapter.suggest(
            SuggestionRequest(current_input="npm run", app="codex", project="project-a", top_k=1)
        )

        self.assertEqual(suggestions[0].surface_text, "npm run dev")
        self.assertEqual(suggestions[0].metadata["state"]["input_frequency"], 6)
        self.assertEqual(suggestions[0].metadata["state"]["app_input_frequency"], 6)
        self.assertEqual(suggestions[0].metadata["state"]["project_input_frequency"], 1)
        self.assertEqual(suggestions[0].metadata["state"]["effective_frequency"], 1)
        self.assertEqual(suggestions[0].metadata["state"]["effective_frequency_scope"], "project")
        self.assertNotIn("app-frequency:6", suggestions[0].metadata["reason"])

    def test_app_phrase_stats_refreshes_after_delete(self) -> None:
        self.core.reset()
        first_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="test",
                committed_text="应用内高频短语",
                recent_context="codex app phrase",
                app="codex",
            )
        )
        second_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms() + 1,
                source="test",
                committed_text="应用内高频短语",
                recent_context="codex app phrase",
                app="codex",
            )
        )

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=first_id,
                action_type="delete",
                query="应用内高频短语",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            remaining = conn.execute(
                "SELECT input_frequency FROM phrase_app_stats WHERE committed_text = ? AND app = ?",
                ("应用内高频短语", "codex"),
            ).fetchone()[0]
        self.assertEqual(remaining, 1)

        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=second_id,
                action_type="delete",
                query="应用内高频短语",
            )
        )
        with sqlite3.connect(self.db_path) as conn:
            gone = conn.execute(
                "SELECT input_frequency FROM phrase_app_stats WHERE committed_text = ? AND app = ?",
                ("应用内高频短语", "codex"),
            ).fetchone()
        self.assertIsNone(gone)

    def test_codex_tool_trace_is_filtered_from_input_candidates(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "[327] tool apply_patch call: added rimeSuggestCache cacheStats wiring",
            recent_context="codex_history:tool-trace",
            tags=("codex-history",),
        )
        self.adapter.commit_text(
            "*** Begin Patch *** Update File: rag_ime/debug_server.py rimeSuggestCache cacheStats",
            recent_context="codex_history:patch-output",
            tags=("codex-history",),
        )
        self.adapter.commit_text(
            "Debug health now reports rimeSuggestCache and cacheStats for sidecar cache inspection.",
            recent_context="codex_history:assistant-summary",
            tags=("codex-history",),
        )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="rimeSuggestCache cacheStats", top_k=2))

        blob = "\n".join(item.surface_text for item in suggestions)
        self.assertNotIn("apply_patch", blob)
        self.assertNotIn("*** Begin Patch", blob)

    def test_runtime_memory_summary_rows_are_filtered_from_retrieval(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "## Memory You have access to a memory folder with guidance from prior runs. MEMORY_SUMMARY memory_summary.md",
            recent_context="codex_history:rollout role:user",
            tags=("codex-history", "role:user"),
        )
        self.adapter.commit_text(
            "index.ts 先改成依赖 core。",
            recent_context="已读取 Read implementation-goal.md Read index.ts",
            tags=("codex-history", "role:user"),
        )
        self.adapter.commit_text(
            "installation.yaml 仍未跟踪 py 通过",
            recent_context="git diff --check 管理员密码",
            tags=("codex-history", "role:user"),
        )
        self.adapter.commit_text(
            "embedding 检索应该结合当前输入和上下文窗口",
            recent_context="用户反馈：RAG query 要包含当前输入、上屏锚点和最近上下文。",
            tags=("curated", "rag", "embedding"),
        )

        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="rag embedding 怎么调用",
                recent_context="检索都是出问题的，需要检查 embedding query",
                top_k=5,
            )
        )

        blob = "\n".join(item.surface_text for item in suggestions)
        self.assertIn("embedding 检索应该结合当前输入和上下文窗口", blob)
        self.assertNotIn("MEMORY_SUMMARY", blob)
        self.assertNotIn("index.ts", blob)
        self.assertNotIn("installation.yaml", blob)

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

    def test_vector_side_index_can_recall_semantic_memory_without_fts_overlap(self) -> None:
        db_path = Path(self.tmp.name) / "vector.sqlite"
        core = LocalSqliteCoreClient(
            db_path,
            embedding_provider=SemanticTestEmbeddingProvider(),
            vector_weight=2.0,
        )
        adapter = InputMethodAdapter(core)
        adapter.commit_text("赤色星球探索计划", recent_context="航天项目背景")
        adapter.commit_text("输入法候选调试", recent_context="普通工程记录")

        suggestions = adapter.suggest(SuggestionRequest(current_input="火星任务", top_k=1))

        self.assertEqual(suggestions[0].surface_text, "赤色星球探索计划")
        self.assertIn("vector:", suggestions[0].metadata["reason"])
        stats = core.vector_index_stats()
        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["activeProviderVectors"], 2)

    def test_weak_vector_only_match_does_not_recall_unrelated_memory(self) -> None:
        db_path = Path(self.tmp.name) / "weak-vector.sqlite"
        core = LocalSqliteCoreClient(
            db_path,
            embedding_provider=WeakNoisyEmbeddingProvider(),
            vector_weight=2.0,
        )
        adapter = InputMethodAdapter(core)
        adapter.commit_text("使徒在圣经中被描述为什么", recent_context="宗教文本学习记录")

        suggestions = adapter.suggest(SuggestionRequest(current_input="撤旦", top_k=5))

        self.assertEqual(suggestions, [])

    def test_rebuild_vector_index_backfills_existing_events(self) -> None:
        db_path = Path(self.tmp.name) / "vector-backfill.sqlite"
        plain_core = LocalSqliteCoreClient(db_path)
        plain_adapter = InputMethodAdapter(plain_core)
        plain_adapter.commit_text("赤色星球探索计划", recent_context="航天项目背景")

        vector_core = LocalSqliteCoreClient(
            db_path,
            embedding_provider=SemanticTestEmbeddingProvider(),
            vector_weight=2.0,
        )
        report = vector_core.rebuild_vector_index()
        suggestions = InputMethodAdapter(vector_core).suggest(SuggestionRequest(current_input="火星任务", top_k=1))

        self.assertEqual(report["indexed"], 1)
        self.assertEqual(suggestions[0].surface_text, "赤色星球探索计划")
        self.assertIn("vector:", suggestions[0].metadata["reason"])

    def test_retrieval_does_not_fill_candidates_with_recent_runtime_noise(self) -> None:
        self.core.reset()
        self.adapter.commit_text("py 通过", recent_context="git diff --check 通过", tags=("runtime-noise",))
        self.adapter.commit_text("installation yaml 仍未跟踪", recent_context="运行安装脚本后输出", tags=("runtime-noise",))

        suggestions = self.adapter.suggest(
            SuggestionRequest(
                current_input="RAG embedding 应该怎么检索",
                recent_context="用户在问 embedding query 需要上下文窗口",
                top_k=5,
            )
        )

        self.assertEqual(suggestions, [])

    def test_embedding_query_uses_clean_current_input_and_context_window(self) -> None:
        provider = CapturingEmbeddingProvider()
        db_path = Path(self.tmp.name) / "embedding-query.sqlite"
        core = LocalSqliteCoreClient(db_path, embedding_provider=provider, vector_weight=2.0)
        adapter = InputMethodAdapter(core)
        adapter.commit_text("embedding 检索应该使用上下文窗口", recent_context="RAG 输入法 query 构造")
        provider.calls.clear()

        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input="怎么调用 embedding",
                recent_context=(
                    "你rag到底是怎么调用embedding，应该输入一些内容再调用embedding。"
                    "```bash\npython3 -m unittest discover -s tests\n```"
                    "检索应该包含上下文窗口。"
                ),
                project="wisdom-weasel-rag-ime",
                top_k=1,
            )
        )

        self.assertEqual(suggestions[0].surface_text, "embedding 检索应该使用上下文窗口")
        query_call = provider.calls[-1]
        self.assertIn("怎么调用 embedding", query_call)
        self.assertIn("上下文窗口", query_call)
        self.assertNotIn("python3 -m unittest", query_call)
        self.assertIn("vector:", suggestions[0].metadata["reason"])

    def test_retrieval_falls_back_when_request_project_has_no_history(self) -> None:
        provider = CapturingEmbeddingProvider()
        db_path = Path(self.tmp.name) / "project-fallback.sqlite"
        core = LocalSqliteCoreClient(db_path, embedding_provider=provider, vector_weight=2.0)
        adapter = InputMethodAdapter(core)
        adapter.commit_text(
            "embedding 检索应该使用上下文窗口",
            recent_context="RAG 输入法 query 构造",
            project="wisdom-weasel-rag-ime",
        )

        suggestions = adapter.suggest(
            SuggestionRequest(
                current_input="怎么调用 embedding",
                recent_context="检索应该包含上下文窗口",
                project="learnA",
                top_k=1,
            )
        )

        self.assertEqual(suggestions[0].surface_text, "embedding 检索应该使用上下文窗口")
        self.assertIn("vector:", suggestions[0].metadata["reason"])


if __name__ == "__main__":
    unittest.main()
