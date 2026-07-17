from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rag_ime.adapter import InputMethodAdapter, SuggestionRequest
from rag_ime.agent_hook import build_first_run_injection
from rag_ime.cli import main, run_acceptance, seed_demo_memories
from rag_ime.core_client import default_fixture_memories
from rag_ime.input_quality import MEMORY_CONTEXT_OPT_IN_TAG
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

    def _run_cli_json(self, *args: str) -> dict[str, object]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["--db-path", str(self.db_path), *args])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _commit_curated(self, text: str, **kwargs: object) -> str:
        """Insert governed retrieval material instead of an ordinary raw event."""
        tags = tuple(str(item) for item in kwargs.pop("tags", ()))
        return self.adapter.commit_text(
            text,
            tags=tuple(dict.fromkeys((*tags, "curated"))),
            **kwargs,
        )

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

    def test_personal_database_permissions_are_owner_only(self) -> None:
        self.assertEqual(self.db_path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)

    def test_reset_clears_v2_governance_state_for_deterministic_gates(self) -> None:
        self.adapter.commit_text(
            "重置前的真实输入证据",
            source="manual_commit",
            privacy_disposition="allowed",
        )
        self.core.add_memory_tombstone(
            target_type="phrase",
            target_value="默认本地完成, 不上传个人输入历史",
            reason="test",
        )
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": "event:1",
                "candidateText": "默认本地完成, 不上传个人输入历史",
                "sourceType": "memory",
                "contextHash": "ctx:reset",
                "timestampMs": now_ms(),
            }
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            migration_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM memory_tombstones").fetchone()[0], 0)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM memory_feedback_events").fetchone()[0], 0)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)

        self.core.reset()

        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM input_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_tombstones").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_candidate_suppressions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_feedback_events").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM agent_memory_sources").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM memory_source_disposition_events").fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM memory_source_event_links").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], migration_count)

        # Reset clears memory data without replaying already-applied product migrations.
        self.core.reset()

    def test_core_optimization_snapshot_includes_recent_events_and_high_frequency_phrases(self) -> None:
        for _ in range(3):
            self.adapter.commit_text("四川模糊音", project="wisdom-weasel-rag-ime", source="manual", privacy_disposition="allowed")
        self.adapter.commit_text("DSV4 词库优化", project="wisdom-weasel-rag-ime", source="manual", privacy_disposition="allowed")

        snapshot = self.core.core_optimization_snapshot(project="wisdom-weasel-rag-ime", recent_limit=5, phrase_limit=5)

        self.assertEqual(snapshot["schemaVersion"], "rag-ime.core-optimization-snapshot.v1")
        recent_texts = [item["text"] for item in snapshot["recentEvents"]]
        phrase_texts = [item["text"] for item in snapshot["highFrequencyPhrases"]]
        self.assertIn("四川模糊音", recent_texts)
        self.assertIn("四川模糊音", phrase_texts)
        phrase = next(item for item in snapshot["highFrequencyPhrases"] if item["text"] == "四川模糊音")
        self.assertGreaterEqual(phrase["inputFrequency"], 3)

    def test_cli_admin_commands_expose_trace_governance_and_cleanup_runs(self) -> None:
        self.adapter.commit_text(
            "连续预测",
            recent_context="RAG 输入法需要更好的候选",
            project="wisdom-weasel-rag-ime",
            tags=("phrase-memory",),
            privacy_disposition="allowed",
        )
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": "phrase:连续预测",
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:cli-admin",
                "timestampMs": 1,
            }
        )
        self.core.record_memory_feedback(
            {
                "event": "skipped",
                "candidateId": "phrase:连续预测",
                "candidateText": "连续预测",
                "sourceType": "memory",
                "contextHash": "ctx:cli-admin",
                "timestampMs": 2,
            }
        )
        cleanup = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")
        self.core.store_memory_optimizer_trace(
            {
                "traceId": "trace-cli-admin",
                "requestSeq": 7,
                "contextHash": "ctx:cli-admin",
                "contextFrame": {"semantic_query": "连续"},
                "queryPlan": {"retrievers": ["phrase"]},
                "rawResults": [{"id": "phrase:连续预测", "text": "连续预测"}],
                "optimizedCandidates": [],
                "blocked": [{"id": "phrase:连续预测", "reason": "recent_committed_echo"}],
                "latencyMs": 1.2,
                "warnings": [],
                "degraded": False,
                "createdAtMs": 3,
            }
        )

        governance_payload = self._run_cli_json("memory-governance", "--limit", "10")
        cleanup_runs_payload = self._run_cli_json("memory-cleanup-runs", "--limit", "10")
        trace_payload = self._run_cli_json("memory-optimizer-trace", "trace-cli-admin")
        explain_payload = self._run_cli_json("memory-candidate-explain", "phrase:连续预测", "--context-hash", "ctx:cli-admin")

        self.assertEqual(governance_payload["schemaVersion"], "rag-ime.memory-governance.v1")
        self.assertIn("phrase:连续预测", [item["matchValue"] for item in governance_payload["suppressions"]])
        self.assertEqual(cleanup_runs_payload["schemaVersion"], "rag-ime.memory-cleanup-runs.v1")
        self.assertTrue(any(item["runId"] == cleanup["runId"] for item in cleanup_runs_payload["items"]))
        self.assertEqual(trace_payload["traceId"], "trace-cli-admin")
        self.assertEqual(explain_payload["candidateId"], "phrase:连续预测")
        self.assertEqual(explain_payload["recentTrace"]["traceId"], "trace-cli-admin")

    def test_cli_memory_cleanup_review_marks_run_reviewed(self) -> None:
        self._commit_curated(
            "连续预测",
            recent_context="RAG 输入法需要更好的候选",
            project="wisdom-weasel-rag-ime",
            tags=("phrase-memory",),
            privacy_disposition="allowed",
        )
        self._commit_curated(
            "连续预测",
            recent_context="RAG 输入法需要更好的候选",
            project="wisdom-weasel-rag-ime",
            tags=("phrase-memory",),
            privacy_disposition="allowed",
        )
        cleanup = self.core.build_memory_cleanup_plan(project="wisdom-weasel-rag-ime")

        review_payload = self._run_cli_json(
            "memory-cleanup-review",
            "--run-id",
            cleanup["runId"],
            "--status",
            "approved",
        )

        self.assertEqual(review_payload["schemaVersion"], "rag-ime.memory-cleanup-review.v1")
        self.assertEqual(review_payload["run"]["status"], "reviewed")
        self.assertTrue(review_payload["run"]["diffs"])
        self.assertTrue(all(item["status"] == "approved" for item in review_payload["run"]["diffs"]))

    def test_cli_pr5_governance_report_tombstone_and_anti_echo_demo(self) -> None:
        tombstone_payload = self._run_cli_json(
            "tombstone",
            "phrase:连续预测",
            "--target-type",
            "memory_id",
            "--reason",
            "manual review",
            "--metadata-json",
            '{"source":"cli-test"}',
        )
        governance_payload = self._run_cli_json("governance-report", "--limit", "10")
        anti_echo_payload = self._run_cli_json(
            "anti-echo-demo",
            "这是我之前输入过的一整段很长的历史句子，不应该再次出现在候选栏里",
            "--committed-tail",
            "我想设计一个输入法",
            "--semantic-query",
            "设计输入法",
            "--candidate-source",
            "rag",
            "--hit-source",
            "fts",
            "--source-tag",
            "user-input",
        )

        self.assertEqual(tombstone_payload["targetType"], "memory_id")
        self.assertEqual(tombstone_payload["targetValue"], "phrase:连续预测")
        self.assertEqual(tombstone_payload["metadata"]["source"], "cli-test")
        self.assertTrue(any(item["targetValue"] == "phrase:连续预测" for item in governance_payload["tombstones"]))
        self.assertEqual(anti_echo_payload["schemaVersion"], "rag-ime.anti-echo-demo.v1")
        self.assertTrue(anti_echo_payload["decisions"][0]["blocked"])
        self.assertEqual(anti_echo_payload["decisions"][0]["reason"], "raw_history_long_candidate")

    def test_initialize_prunes_orphan_memory_state_and_vectors(self) -> None:
        orphan_event_id = 999_999
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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

        self.core.initialize(force=True)

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            state_count = conn.execute("SELECT COUNT(*) FROM memory_state WHERE event_id = ?", (orphan_event_id,)).fetchone()[0]
            vector_count = conn.execute("SELECT COUNT(*) FROM memory_vectors WHERE event_id = ?", (orphan_event_id,)).fetchone()[0]
            action_event_id = conn.execute("SELECT event_id FROM memory_actions WHERE memory_id = ?", (f"event:{orphan_event_id}",)).fetchone()[0]
        self.assertEqual(state_count, 0)
        self.assertEqual(vector_count, 0)
        self.assertIsNone(action_event_id)

    def test_record_event_reuses_completed_database_initialization(self) -> None:
        with patch("rag_ime.local_sqlite_core.ensure_memory_v2_schema") as ensure_schema:
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now_ms(),
                    source="test",
                    committed_text="初始化只执行一次",
                    privacy_disposition="allowed",
                    project="wisdom-weasel-rag-ime",
                )
            )

        ensure_schema.assert_not_called()

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
        self._commit_curated(
            "生成 PROJECT_MEMORY_BLOCK",
            recent_context="Agent 首次运行自动注入背景记忆",
            tags=("agent-hook", "context"),
            privacy_disposition="allowed",
        )
        self._commit_curated(
            "普通 debug page 背景材料",
            recent_context="浏览器调试页面展示 pipeline",
            tags=("debug",),
            privacy_disposition="allowed",
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
        self._commit_curated(
            "输入法候选需要保持短小",
            recent_context="debug page",
            tags=("debug",),
            privacy_disposition="allowed",
        )
        self._commit_curated(
            "Squirrel side candidates 使用本地记忆作为候选",
            recent_context="Rime sidecar 合并候选 本地记忆",
            source="squirrel_rime_sidecar",
            app="squirrel",
            tags=("squirrel", "rime", "memory"),
            privacy_disposition="allowed",
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
            self._commit_curated(
                target,
                recent_context="runtime term mapping",
                tags=("runtime",),
                privacy_disposition="allowed",
            )
        self.adapter.commit_text("普通中文候选调试", recent_context="无关记录", privacy_disposition="allowed")

        for query, expected in cases:
            with self.subTest(query=query):
                suggestions = self.adapter.suggest(SuggestionRequest(current_input=query, top_k=1))
                self.assertIn(expected, suggestions[0].expanded_evidence)
                self.assertLessEqual(len(suggestions[0].surface_text), 42)
                self.assertEqual(suggestions[0].metadata["insert_text"], suggestions[0].surface_text)

    def test_suggestions_deduplicate_repeated_memory_surfaces(self) -> None:
        self.core.reset()
        self._commit_curated("重复候选内容", recent_context="RAG 输入法候选 重复记录", privacy_disposition="allowed")
        self._commit_curated("重复候选内容", recent_context="RAG 输入法候选 重复记录 第二次", privacy_disposition="allowed")
        self._commit_curated("新的候选内容", recent_context="RAG 输入法候选 另一条", privacy_disposition="allowed")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="RAG 输入法候选 重复", top_k=3))
        surfaces = [item.surface_text for item in suggestions]

        self.assertEqual(surfaces.count("重复候选内容"), 1)
        self.assertIn("新的候选内容", surfaces)

    def test_suggestions_skip_low_value_one_character_memory_surfaces(self) -> None:
        self.core.reset()
        self._commit_curated("嗯", recent_context="RAG 输入法候选 语气词", privacy_disposition="allowed")
        self._commit_curated("当", recent_context="RAG 输入法候选 单字噪声", privacy_disposition="allowed")
        self._commit_curated("高频实时场景里的个人记忆系统", recent_context="RAG 输入法候选 高频记忆", privacy_disposition="allowed")

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
            privacy_disposition="allowed",
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
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "模型生成候选不应继续污染历史",
            source="squirrel_rime_sidecar",
            provider_name="rime-sidecar:model",
            tags=("squirrel", "rime-sidecar", "source:model"),
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "RAG 生成候选不应被模型复读",
            source="squirrel_rime_sidecar",
            provider_name="rime-sidecar:rag",
            tags=("squirrel", "rime-sidecar", "source:rag"),
            privacy_disposition="allowed",
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
            privacy_disposition="allowed",
        )
        self.adapter.commit_text("普通中文候选兜底", recent_context="输入法候选", privacy_disposition="allowed")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="sj", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "设计一个候选展示方式")
        self.assertIn("pinyin:", suggestions[0].metadata["reason"])

    def test_runtime_fuzzy_pinyin_setting_gates_recall_and_rerank(self) -> None:
        self.core.reset()
        with patch.dict(
            "os.environ",
            {
                "RAG_IME_PINYIN_FUZZY_ENABLED": "1",
                "RAG_IME_PINYIN_FUZZY_PROFILE": "sichuan-mild",
                "RAG_IME_PINYIN_FUZZY_S_SH": "1",
            },
            clear=False,
        ):
            self._commit_curated(
                "世界设计",
                recent_context="输入法模糊音候选重排",
                tags=("pinyin",),
                privacy_disposition="allowed",
            )
            enabled = self.adapter.suggest(SuggestionRequest(current_input="sijie", top_k=3))

        with patch.dict(
            "os.environ",
            {
                "RAG_IME_PINYIN_FUZZY_ENABLED": "0",
                "RAG_IME_PINYIN_FUZZY_PROFILE": "none",
                "RAG_IME_PINYIN_FUZZY_S_SH": "0",
            },
            clear=False,
        ):
            disabled = self.adapter.suggest(SuggestionRequest(current_input="sijie", top_k=3))

        self.assertEqual(enabled[0].surface_text, "世界设计")
        self.assertIn("pinyin:", enabled[0].metadata["reason"])
        self.assertNotIn("世界设计", [item.surface_text for item in disabled])

    def test_accepted_count_boosts_frequently_selected_memory(self) -> None:
        self.core.reset()
        frequent_id = self._commit_curated("高频候选方案", recent_context="输入法 频率 候选方案", privacy_disposition="allowed")
        self._commit_curated("普通候选方案", recent_context="输入法 频率 候选方案", privacy_disposition="allowed")

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
        self._commit_curated("高频候选方案", recent_context="输入法 词频 候选方案", privacy_disposition="allowed")
        self._commit_curated("高频候选方案", recent_context="输入法 词频 候选方案 第二次", privacy_disposition="allowed")
        self._commit_curated("普通候选方案", recent_context="输入法 词频 候选方案 最新", privacy_disposition="allowed")

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="输入法 词频 候选方案", top_k=2))

        self.assertEqual(suggestions[0].surface_text, "高频候选方案")
        self.assertIn("frequency:2", suggestions[0].metadata["reason"])
        self.assertEqual(suggestions[0].metadata["state"]["input_frequency"], 2)

    def test_score_breakdown_explains_frequency_and_acceptance_signals(self) -> None:
        self.core.reset()
        frequent_id = self._commit_curated("高频候选方案", recent_context="输入法 词频 候选方案", privacy_disposition="allowed")
        self._commit_curated("高频候选方案", recent_context="输入法 词频 候选方案 第二次", privacy_disposition="allowed")
        self._commit_curated("普通候选方案", recent_context="输入法 词频 候选方案 最新", privacy_disposition="allowed")
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=0,
                memory_id=frequent_id,
                action_type="accepted",
                query="输入法 词频 候选方案",
            )
        )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="输入法 词频 候选方案", top_k=2))

        breakdown = suggestions[0].metadata["score_breakdown"]
        self.assertEqual(breakdown["schemaVersion"], "rag-ime.score-breakdown.v1")
        self.assertEqual(breakdown["rawSignals"]["inputFrequency"], 2)
        self.assertEqual(breakdown["rawSignals"]["acceptedCount"], 1)
        self.assertEqual(breakdown["rawSignals"]["effectiveFrequencyScope"], "project")
        self.assertGreater(breakdown["components"]["frequency"], 0)
        self.assertEqual(breakdown["components"]["accepted"], 0.6)
        self.assertAlmostEqual(
            breakdown["total"],
            sum(breakdown["components"].values()),
            places=3,
        )
        self.assertEqual(suggestions[0].metadata["state"]["score_breakdown"], breakdown)

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
                    privacy_disposition="allowed",
                    recent_context="输入法 词频 候选方案",
                    project="wisdom-weasel-rag-ime",
                    tags=("curated",),
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="近期候选方案",
                privacy_disposition="allowed",
                recent_context="输入法 词频 候选方案",
                project="wisdom-weasel-rag-ime",
                tags=("curated",),
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
                privacy_disposition="allowed",
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
                privacy_disposition="allowed",
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
                privacy_disposition="allowed",
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
                privacy_disposition="allowed",
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
                privacy_disposition="allowed",
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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

    def test_organize_rag_database_hides_generated_oneoffs_and_complaints(self) -> None:
        self.core.reset()
        now = 1_900_000_010_000
        user_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="manual_commit",
                committed_text="真实用户输入要保留",
                privacy_disposition="allowed",
                recent_context="用户正在写输入法设计",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        generated_once_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 1,
                source="squirrel_rime_sidecar",
                committed_text="接入真实记忆候选",
                privacy_disposition="allowed",
                recent_context="模型候选被选中一次",
                project="wisdom-weasel-rag-ime",
                provider_name="rime-sidecar:model",
                tags=("squirrel", "rime-sidecar", "sidecar-selected", "source:model"),
            )
        )
        generated_repeated_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 2,
                source="squirrel_rime_sidecar",
                committed_text="常用模型短语",
                privacy_disposition="allowed",
                recent_context="模型候选多次被选中",
                project="wisdom-weasel-rag-ime",
                provider_name="rime-sidecar:model",
                tags=("squirrel", "rime-sidecar", "sidecar-selected", "source:model"),
            )
        )
        complaint_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 3,
                source="manual_commit",
                committed_text="需要真实生效",
                privacy_disposition="allowed",
                recent_context="用户反馈 RAG 老是之前输入",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        curated_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 4,
                source="curated_user_feedback",
                committed_text="RAG 候选不应直接显示 Codex 工具日志",
                privacy_disposition="allowed",
                recent_context="人工整理的质量门样例",
                project="wisdom-weasel-rag-ime",
                tags=("curated", "demo-quality", "rag", "noise-filter", "user-input"),
            )
        )
        for memory_id, count in ((generated_once_id, 1), (generated_repeated_id, 3), (complaint_id, 1)):
            for _ in range(count):
                self.core.apply_action(
                    MemoryAction(
                        action_id=None,
                        created_at_ms=0,
                        memory_id=memory_id,
                        action_type="accepted",
                        query="输入法 RAG 整理",
                    )
                )

        dry_run = self.core.organize_rag_database(project="wisdom-weasel-rag-ime", dry_run=True)
        report = self.core.organize_rag_database(project="wisdom-weasel-rag-ime")

        self.assertEqual(dry_run["hidden"], 0)
        self.assertEqual(dry_run["wouldHide"], 2)
        self.assertEqual(report["hidden"], 2)
        self.assertEqual(report["reasonCounts"]["generated_side_candidate_oneoff"], 1)
        self.assertEqual(report["reasonCounts"]["ime_complaint_or_debug_feedback"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            active = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT e.committed_text
                    FROM input_events e
                    JOIN memory_state s ON s.event_id = e.id
                    WHERE s.deleted = 0
                    """
                ).fetchall()
            }
            action_count = conn.execute(
                "SELECT COUNT(*) FROM memory_actions WHERE action_type = 'hide' AND query = 'rag-db-organize'"
            ).fetchone()[0]
            user_deleted = conn.execute(
                "SELECT s.deleted FROM memory_state s WHERE s.event_id = ?",
                (int(user_id.removeprefix("event:")),),
            ).fetchone()[0]
            curated_deleted = conn.execute(
                "SELECT s.deleted FROM memory_state s WHERE s.event_id = ?",
                (int(curated_id.removeprefix("event:")),),
            ).fetchone()[0]

        self.assertIn("真实用户输入要保留", active)
        self.assertIn("RAG 候选不应直接显示 Codex 工具日志", active)
        self.assertIn("常用模型短语", active)
        self.assertNotIn("接入真实记忆候选", active)
        self.assertNotIn("需要真实生效", active)
        self.assertEqual(action_count, 2)
        self.assertEqual(user_deleted, 0)
        self.assertEqual(curated_deleted, 0)

    def test_organize_rag_database_reports_and_hides_low_value_duplicate_text(self) -> None:
        self.core.reset()
        now = 1_900_000_020_000
        duplicate_text = "这是一段很长的旧输入内容，重复进入 RAG 后不应该反复出现"
        duplicate_ids = [
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index,
                    source="manual_commit",
                    committed_text=duplicate_text,
                    privacy_disposition="allowed",
                    recent_context="RAG 老是之前输入",
                    project="wisdom-weasel-rag-ime",
                    tags=("user-input", "history"),
                )
            )
            for index in range(3)
        ]
        protected_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 10,
                source="manual_commit",
                committed_text="受保护的重复短语",
                privacy_disposition="allowed",
                recent_context="用户接受过",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        unprotected_peer_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 11,
                source="manual_commit",
                committed_text="受保护的重复短语",
                privacy_disposition="allowed",
                recent_context="重复进入",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now + 12,
                memory_id=protected_id,
                action_type="accepted",
                query="保留用户确认过的短语",
            )
        )

        dry_run = self.core.organize_rag_database(project="wisdom-weasel-rag-ime", dry_run=True)
        report = self.core.organize_rag_database(project="wisdom-weasel-rag-ime")

        self.assertEqual(dry_run["hidden"], 0)
        self.assertEqual(dry_run["duplicateGroupCount"], 2)
        self.assertEqual(dry_run["duplicateEventCount"], 3)
        self.assertEqual(dry_run["wouldHideDuplicates"], 2)
        self.assertEqual(dry_run["reasonCounts"]["duplicate_low_value_text"], 2)
        duplicate_group = next(item for item in dry_run["duplicateGroups"] if item["text"] == duplicate_text)
        self.assertEqual(len(duplicate_group["hideEventIds"]), 2)
        protected_group = next(item for item in dry_run["duplicateGroups"] if item["text"] == "受保护的重复短语")
        self.assertEqual(protected_group["hideEventIds"], [])
        self.assertEqual(protected_group["representativeEventId"], int(protected_id.removeprefix("event:")))
        self.assertEqual(report["hidden"], 2)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            active_duplicate_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE e.committed_text = ? AND s.deleted = 0
                """,
                (duplicate_text,),
            ).fetchone()[0]
            protected_deleted = conn.execute(
                "SELECT deleted FROM memory_state WHERE event_id = ?",
                (int(protected_id.removeprefix("event:")),),
            ).fetchone()[0]
            unprotected_peer_deleted = conn.execute(
                "SELECT deleted FROM memory_state WHERE event_id = ?",
                (int(unprotected_peer_id.removeprefix("event:")),),
            ).fetchone()[0]
            hidden_ids = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT event_id
                    FROM memory_state
                    WHERE deleted = 1
                    """
                ).fetchall()
            }
            action_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_actions
                WHERE action_type = 'hide' AND query = 'rag-db-organize'
                  AND metadata_json LIKE '%duplicate_low_value_text%'
                """
            ).fetchone()[0]

        self.assertEqual(active_duplicate_count, 1)
        self.assertEqual(protected_deleted, 0)
        self.assertEqual(unprotected_peer_deleted, 0)
        self.assertEqual(len(hidden_ids.intersection(int(item.removeprefix("event:")) for item in duplicate_ids)), 2)
        self.assertEqual(action_count, 2)

    def test_organize_rag_database_reports_and_hides_similar_old_input_text(self) -> None:
        self.core.reset()
        now = 1_900_000_030_000
        representative_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="manual_commit",
                committed_text="我今天调试 RAG 输入法上下文管理和候选展示，需要保留真实输入",
                privacy_disposition="allowed",
                recent_context="用户确认过的项目记忆",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        similar_ids = [
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index + 1,
                    source="manual_commit",
                    committed_text=text,
                    privacy_disposition="allowed",
                    recent_context="旧输入重复进入 RAG",
                    project="wisdom-weasel-rag-ime",
                    tags=("user-input", "history"),
                )
            )
            for index, text in enumerate(
                [
                    "我今天调试RAG输入法上下文管理和候选展示，需要保留真实输入。",
                    "今天调试 RAG 输入法上下文管理和候选展示，需要保留真实输入",
                ]
            )
        ]
        short_peer_id = self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 10,
                source="manual_commit",
                committed_text="候选展示",
                privacy_disposition="allowed",
                recent_context="短语词库",
                project="wisdom-weasel-rag-ime",
                tags=("user-input",),
            )
        )
        self.core.apply_action(
            MemoryAction(
                action_id=None,
                created_at_ms=now + 20,
                memory_id=representative_id,
                action_type="accepted",
                query="保留用户确认过的长文本代表",
            )
        )

        dry_run = self.core.organize_rag_database(project="wisdom-weasel-rag-ime", dry_run=True)
        report = self.core.organize_rag_database(project="wisdom-weasel-rag-ime")

        self.assertEqual(dry_run["similarGroupCount"], 1)
        self.assertEqual(dry_run["similarEventCount"], 2)
        self.assertEqual(dry_run["wouldHideSimilar"], 2)
        self.assertEqual(dry_run["reasonCounts"]["similar_low_value_text"], 2)
        group = dry_run["similarGroups"][0]
        self.assertEqual(group["representativeEventId"], int(representative_id.removeprefix("event:")))
        self.assertEqual(sorted(group["hideEventIds"]), sorted(int(item.removeprefix("event:")) for item in similar_ids))
        self.assertEqual(group["similarityReasons"], ["contains", "normalized_equal"])
        self.assertEqual(report["hidden"], 2)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            representative_deleted = conn.execute(
                "SELECT deleted FROM memory_state WHERE event_id = ?",
                (int(representative_id.removeprefix("event:")),),
            ).fetchone()[0]
            short_deleted = conn.execute(
                "SELECT deleted FROM memory_state WHERE event_id = ?",
                (int(short_peer_id.removeprefix("event:")),),
            ).fetchone()[0]
            hidden_similar_ids = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT event_id
                    FROM memory_state
                    WHERE deleted = 1
                    """
                ).fetchall()
            }
            action_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_actions
                WHERE action_type = 'hide' AND query = 'rag-db-organize'
                  AND metadata_json LIKE '%similar_low_value_text%'
                """
            ).fetchone()[0]

        self.assertEqual(representative_deleted, 0)
        self.assertEqual(short_deleted, 0)
        self.assertEqual(hidden_similar_ids, {int(item.removeprefix("event:")) for item in similar_ids})
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
                    privacy_disposition="allowed",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-b",
                    tags=("curated",),
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="npm run dev",
                privacy_disposition="allowed",
                recent_context="vibe coding command",
                app="codex",
                project="project-a",
                tags=("curated",),
            )
        )
        for index in range(3):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index + 1,
                    source="test",
                    committed_text="npm run test",
                    privacy_disposition="allowed",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-a",
                    tags=("curated",),
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
                privacy_disposition="allowed",
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
                privacy_disposition="allowed",
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
                    privacy_disposition="allowed",
                    recent_context="浏览器 调试 快捷操作",
                    app="browser",
                    project="",
                    tags=("curated",),
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now,
                source="test",
                committed_text="打开开发者工具",
                privacy_disposition="allowed",
                recent_context="浏览器 调试 快捷操作",
                app="codex",
                project="",
                tags=("curated",),
            )
        )
        for index in range(3):
            self.core.record_event(
                InputEvent(
                    event_id=None,
                    created_at_ms=now + index + 1,
                    source="test",
                    committed_text="打开代码上下文",
                    privacy_disposition="allowed",
                    recent_context="codex 调试 快捷操作",
                    app="codex",
                    project="",
                    tags=("curated",),
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
                    privacy_disposition="allowed",
                    recent_context="vibe coding command",
                    app="codex",
                    project="project-b",
                    tags=("curated",),
                )
            )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now + 10,
                source="test",
                committed_text="npm run dev",
                privacy_disposition="allowed",
                recent_context="vibe coding command",
                app="codex",
                project="project-a",
                tags=("curated",),
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
                privacy_disposition="allowed",
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
                privacy_disposition="allowed",
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "*** Begin Patch *** Update File: rag_ime/debug_server.py rimeSuggestCache cacheStats",
            recent_context="codex_history:patch-output",
            tags=("codex-history",),
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "Debug health now reports rimeSuggestCache and cacheStats for sidecar cache inspection.",
            recent_context="codex_history:assistant-summary",
            tags=("codex-history",),
            privacy_disposition="allowed",
        )

        suggestions = self.adapter.suggest(SuggestionRequest(current_input="rimeSuggestCache cacheStats", top_k=2))

        blob = "\n".join(item.surface_text for item in suggestions)
        self.assertNotIn("apply_patch", blob)
        self.assertNotIn("*** Begin Patch", blob)

    def test_codex_history_never_enters_recent_context_or_legacy_retrieval(self) -> None:
        self.core.reset()
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms() - 1,
                source="codex_history",
                committed_text="旧 Codex 会话里的火星索引污染。",
                privacy_disposition="allowed",
                project="wisdom-weasel-rag-ime",
                tags=("codex-history", "role:user", "curated"),
            )
        )
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="manual_commit",
                committed_text="最近输入法封口内容应该进入上下文。",
                privacy_disposition="allowed",
                project="wisdom-weasel-rag-ime",
                tags=("curated",),
            )
        )

        recent = self.core.recent_input_context(
            project="wisdom-weasel-rag-ime",
            limit=5,
        )
        memories = self.core.retrieve_memories(
            current_input="火星索引污染",
            project="wisdom-weasel-rag-ime",
            top_k=5,
        )

        self.assertIn("最近输入法封口内容", recent)
        self.assertNotIn("火星索引污染", recent)
        self.assertFalse(any("火星索引污染" in memory.text for memory in memories))
        with closing(sqlite3.connect(self.db_path)) as conn:
            indexed = conn.execute(
                "SELECT COUNT(*) FROM memory_fts f JOIN input_events e ON e.id = f.rowid WHERE e.source = 'codex_history'"
            ).fetchone()[0]
            active = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_items mi
                JOIN input_events e ON e.id = mi.source_event_id
                WHERE e.source = 'codex_history' AND mi.status IN ('active', 'approved')
                """
            ).fetchone()[0]
            phrase_signal = conn.execute(
                "SELECT COUNT(*) FROM phrase_stats WHERE committed_text LIKE '%火星索引污染%'"
            ).fetchone()[0]
        self.assertEqual(indexed, 0)
        self.assertEqual(active, 0)
        self.assertEqual(phrase_signal, 0)

    def test_codex_history_explicit_context_opt_in_enables_retrieval(self) -> None:
        self.core.reset()
        self.core.record_event(
            InputEvent(
                event_id=None,
                created_at_ms=now_ms(),
                source="codex_history",
                committed_text="显式授权的月球索引可以进入个人记忆。",
                privacy_disposition="allowed",
                project="wisdom-weasel-rag-ime",
                tags=("codex-history", "role:user", "curated", MEMORY_CONTEXT_OPT_IN_TAG),
            )
        )

        recent = self.core.recent_input_context(project="wisdom-weasel-rag-ime", limit=5)
        memories = self.core.retrieve_memories(
            current_input="月球索引个人记忆",
            project="wisdom-weasel-rag-ime",
            top_k=5,
        )

        self.assertIn("月球索引", recent)
        self.assertTrue(any("月球索引" in memory.text for memory in memories))
        with closing(sqlite3.connect(self.db_path)) as conn:
            indexed = conn.execute(
                "SELECT COUNT(*) FROM memory_fts f JOIN input_events e ON e.id = f.rowid WHERE e.source = 'codex_history'"
            ).fetchone()[0]
            active = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_items mi
                JOIN input_events e ON e.id = mi.source_event_id
                WHERE e.source = 'codex_history' AND mi.status IN ('active', 'approved')
                """
            ).fetchone()[0]
        self.assertEqual(indexed, 1)
        self.assertEqual(active, 1)

    def test_runtime_memory_summary_rows_are_filtered_from_retrieval(self) -> None:
        self.core.reset()
        self.adapter.commit_text(
            "## Memory You have access to a memory folder with guidance from prior runs. MEMORY_SUMMARY memory_summary.md",
            recent_context="codex_history:rollout role:user",
            tags=("codex-history", "role:user"),
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "index.ts 先改成依赖 core。",
            recent_context="已读取 Read implementation-goal.md Read index.ts",
            tags=("codex-history", "role:user"),
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "installation.yaml 仍未跟踪 py 通过",
            recent_context="git diff --check 管理员密码",
            tags=("codex-history", "role:user"),
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "embedding 检索应该结合当前输入和上下文窗口",
            recent_context="用户反馈：RAG query 要包含当前输入、上屏锚点和最近上下文。",
            tags=("curated", "rag", "embedding"),
            privacy_disposition="allowed",
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

        self.adapter.commit_text("新的缓存失效事件", recent_context="cache invalidation", privacy_disposition="allowed")
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

    def test_suggest_for_input_uses_hybrid_core_when_enabled(self) -> None:
        self._commit_curated(
            "多路召回",
            recent_context="RAG 输入法",
            project="wisdom-weasel-rag-ime",
            tags=("RAG", "检索", "phrase-memory"),
            privacy_disposition="allowed",
        )

        with patch.dict("os.environ", {"RAG_IME_HYBRID_RAG_CORE": "1", "RAG_IME_RAG_CORE_V3_BUDGET_MS": "1000"}):
            suggestions = self.core.suggest_for_input(
                current_input="多路召回",
                project="wisdom-weasel-rag-ime",
                top_k=3,
            )

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0].surface_text, "多路召回")
        self.assertEqual(suggestions[0].metadata["rag_core"], "v3")

    def test_suggest_for_input_legacy_path_when_disabled(self) -> None:
        with patch.dict("os.environ", {"RAG_IME_HYBRID_RAG_CORE": "0"}):
            suggestions = self.core.suggest_for_input(
                current_input="SQLite 和 FTS5 第一版",
                recent_context="MVP 先 local-first, 先验证检索和排序",
                top_k=3,
            )

        self.assertTrue(suggestions)
        self.assertNotEqual(suggestions[0].metadata.get("rag_core"), "v3")

    def test_hybrid_core_fail_closed_to_legacy_or_empty_on_exception(self) -> None:
        with patch.dict("os.environ", {"RAG_IME_HYBRID_RAG_CORE": "1"}), patch.object(
            self.core,
            "retrieve_candidates_v3",
            side_effect=RuntimeError("boom"),
        ):
            suggestions = self.core.suggest_for_input(
                current_input="SQLite 和 FTS5 第一版",
                recent_context="MVP 先 local-first, 先验证检索和排序",
                top_k=3,
            )

        self.assertTrue(suggestions)
        self.assertNotEqual(suggestions[0].metadata.get("rag_core"), "v3")

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

    def test_core_rejects_sensitive_and_unknown_events_before_storage(self) -> None:
        before = self.core.event_count()
        with patch.object(self.core, "initialize") as initialize:
            for disposition in ("sensitive", "unknown"):
                result = self.core.record_event(
                    InputEvent(
                        event_id=None,
                        created_at_ms=now_ms(),
                        source="squirrel_rime_sidecar",
                        committed_text="must-not-be-stored",
                        privacy_disposition=disposition,
                    )
                )
                self.assertEqual(result, f"skipped:privacy_{disposition}")
            initialize.assert_not_called()
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
                    "--privacy-disposition",
                    "allowed",
                    "--tag",
                    "squirrel",
                ]
            )
        self.assertEqual(code, 0)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
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
            privacy_disposition="allowed",
        )
        self.adapter.commit_text(
            "第二条历史输入",
            recent_context="继续写 RAG 输入法",
            preedit="dier",
            tags=("history",),
            privacy_disposition="allowed",
        )
        context = self.core.recent_input_context(project="wisdom-weasel-rag-ime", limit=2, max_chars=220)
        self.assertIn("第一条历史输入", context)
        self.assertIn("第二条历史输入", context)
        self.assertLess(context.index("第一条历史输入"), context.index("第二条历史输入"))
        self.assertIn("继续写 RAG 输入法", context)

    def test_recent_input_context_keeps_tail_of_long_voice_commit(self) -> None:
        suffix = "最后真正的问题是前台上下文能不能完整注入"
        transcript = ("这是语音输入的较早内容。" * 80) + suffix
        self.adapter.commit_text(
            transcript,
            source="voice_streaming_asr",
            provider_name="voice_streaming_asr",
            tags=("voice-input", "recent-input"),
            privacy_disposition="allowed",
        )

        context = self.core.recent_input_context(
            project="wisdom-weasel-rag-ime",
            limit=1,
            max_chars=220,
        )

        self.assertIn(suffix, context)
        self.assertLessEqual(len(context), 220)

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
        adapter.commit_text(
            "赤色星球探索计划",
            recent_context="航天项目背景",
            tags=("curated",),
            privacy_disposition="allowed",
        )
        adapter.commit_text(
            "输入法候选调试",
            recent_context="普通工程记录",
            tags=("curated",),
            privacy_disposition="allowed",
        )

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
        adapter.commit_text("使徒在圣经中被描述为什么", recent_context="宗教文本学习记录", privacy_disposition="allowed")

        suggestions = adapter.suggest(SuggestionRequest(current_input="撤旦", top_k=5))

        self.assertEqual(suggestions, [])

    def test_rebuild_vector_index_backfills_existing_events(self) -> None:
        db_path = Path(self.tmp.name) / "vector-backfill.sqlite"
        plain_core = LocalSqliteCoreClient(db_path)
        plain_adapter = InputMethodAdapter(plain_core)
        plain_adapter.commit_text(
            "赤色星球探索计划",
            recent_context="航天项目背景",
            tags=("curated",),
            privacy_disposition="allowed",
        )

        vector_core = LocalSqliteCoreClient(
            db_path,
            embedding_provider=SemanticTestEmbeddingProvider(),
            vector_weight=2.0,
        )
        report = vector_core.rebuild_vector_index()
        suggestions = InputMethodAdapter(vector_core).suggest(SuggestionRequest(current_input="火星任务", top_k=1))

        self.assertEqual(report["indexed"], 1)
        self.assertGreaterEqual(report["retrievalDocs"]["documents"], 1)
        self.assertGreaterEqual(
            vector_core.vector_index_stats()["activeProviderRetrievalDocVectors"],
            1,
        )
        self.assertEqual(suggestions[0].surface_text, "赤色星球探索计划")
        self.assertIn("vector:", suggestions[0].metadata["reason"])

    def test_retrieval_does_not_fill_candidates_with_recent_runtime_noise(self) -> None:
        self.core.reset()
        self.adapter.commit_text("py 通过", recent_context="git diff --check 通过", tags=("runtime-noise",), privacy_disposition="allowed")
        self.adapter.commit_text("installation yaml 仍未跟踪", recent_context="运行安装脚本后输出", tags=("runtime-noise",), privacy_disposition="allowed")

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
        adapter.commit_text(
            "embedding 检索应该使用上下文窗口",
            recent_context="RAG 输入法 query 构造",
            tags=("curated",),
            privacy_disposition="allowed",
        )
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
            tags=("curated",),
            privacy_disposition="allowed",
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
