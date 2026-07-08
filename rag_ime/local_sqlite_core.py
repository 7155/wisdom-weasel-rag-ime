from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from .core_client import CoreMemory
from .embeddings import EmbeddingProvider, NullEmbeddingProvider, cosine_similarity
from .memory_cleanup import (
    apply_cleanup_diff,
    apply_cleanup_run,
    build_cleanup_plan,
    cleanup_plan_to_payload,
    cleanup_run_payload,
    load_cleanup_run_from_file,
    persist_cleanup_plan,
    review_cleanup_run,
    rollback_cleanup_diff,
    rollback_cleanup_run,
)
from .memory_dedup import select_diverse
from .memory_ingest import sync_event_to_memory_v2
from .memory_models import CandidateFeedbackV2, CleanupRunPlan, ImeQueryContext, MemoryCandidateV2
from .memory_optimizer_models import ContextFrame, OptimizerResult, RawRetrievalHit
from .memory_schema_v2 import ensure_memory_v2_schema, memory_v2_table_names
from .memory_tag_graph import propagate_tag_energy, recompute_tag_graph, score_memory_items_from_tag_energy
from .models import AgentContextInjection, InputEvent, InputSuggestion, MemoryAction
from .pinyin_index import pinyin_search_document, pinyin_search_terms
from .rag_core_v3 import (
    memory_candidates_v2_to_input_suggestions,
    retrieve_candidates_v3 as retrieve_rag_core_v3_candidates,
)
from .runtime_flags import load_hybrid_rag_runtime_flags
from .suggestion_compiler import RankedMemory, SuggestionCompiler
from .text_utils import (
    build_fts_document,
    build_fts_query,
    compact_whitespace,
    now_ms,
    overlap_terms,
    stable_text_hash,
    token_terms,
    truncate_text,
)


_IMPORTANT_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{2,}")
_VECTOR_ONLY_MIN_SCORE_DEFAULT = 0.35
_MS_PER_DAY = 24 * 60 * 60 * 1000
_PHRASE_FEEDBACK_SELECT_COLUMNS = """
                COALESCE(pfb.phrase_accepted_count, s.accepted_count) AS phrase_accepted_count,
                COALESCE(pfb.phrase_skipped_count, s.skipped_count) AS phrase_skipped_count,
                COALESCE(pfb.phrase_downranked_count, s.downranked) AS phrase_downranked_count
"""
_PHRASE_FEEDBACK_JOIN = """
            LEFT JOIN (
                SELECT
                    e2.committed_text,
                    SUM(s2.accepted_count) AS phrase_accepted_count,
                    SUM(s2.skipped_count) AS phrase_skipped_count,
                    SUM(s2.downranked) AS phrase_downranked_count
                FROM input_events e2
                JOIN memory_state s2 ON s2.event_id = e2.id
                WHERE s2.deleted = 0
                GROUP BY e2.committed_text
            ) pfb ON pfb.committed_text = e.committed_text
"""


class LocalSqliteCoreClient:
    """Mac-local SQLite/FTS5 implementation of the CoreClient protocol.

    This is the complete local MVP backend. It sits behind the same `CoreClient`
    boundary as the future shared core, so the IME adapter/UI does not need to be
    rewritten when the shared core exposes stable record/action APIs.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        suggestion_cache_size: int = 128,
        embedding_provider: EmbeddingProvider | None = None,
        vector_candidate_limit: int = 80,
        vector_weight: float = 1.4,
        legacy_governance_filter_enabled: bool = True,
        v2_governance_filter_enabled: bool = True,
    ):
        self.db_path = Path(db_path)
        self.compiler = SuggestionCompiler()
        self.suggestion_cache_size = max(0, int(suggestion_cache_size))
        self.embedding_provider = embedding_provider or NullEmbeddingProvider()
        self.vector_candidate_limit = max(0, int(vector_candidate_limit))
        self.vector_weight = max(0.0, float(vector_weight))
        self.legacy_governance_filter_enabled = bool(legacy_governance_filter_enabled)
        self.v2_governance_filter_enabled = bool(v2_governance_filter_enabled)
        self.memory_v2_enabled = True
        self._suggestion_cache: OrderedDict[tuple[str, str, str, str, str, str, int], tuple[InputSuggestion, ...]] = OrderedDict()
        self._suggestion_cache_lock = RLock()
        self._suggestion_cache_hits = 0
        self._suggestion_cache_misses = 0
        self._suggestion_cache_evictions = 0
        self._suggestion_cache_invalidations = 0

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS input_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    committed_text TEXT NOT NULL,
                    recent_context TEXT NOT NULL DEFAULT '',
                    preedit TEXT NOT NULL DEFAULT '',
                    schema_id TEXT NOT NULL DEFAULT 'default',
                    app TEXT NOT NULL DEFAULT 'manual',
                    project TEXT NOT NULL DEFAULT '',
                    candidate_rank INTEGER,
                    provider_name TEXT NOT NULL DEFAULT 'local',
                    tags_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS memory_state (
                    event_id INTEGER PRIMARY KEY,
                    accepted_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    downranked INTEGER NOT NULL DEFAULT 0,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS phrase_stats (
                    committed_text TEXT PRIMARY KEY,
                    input_frequency INTEGER NOT NULL DEFAULT 0,
                    first_seen_ms INTEGER NOT NULL,
                    last_seen_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS phrase_project_stats (
                    committed_text TEXT NOT NULL,
                    project TEXT NOT NULL,
                    input_frequency INTEGER NOT NULL DEFAULT 0,
                    first_seen_ms INTEGER NOT NULL,
                    last_seen_ms INTEGER NOT NULL,
                    PRIMARY KEY(committed_text, project)
                );

                CREATE TABLE IF NOT EXISTS phrase_app_stats (
                    committed_text TEXT NOT NULL,
                    app TEXT NOT NULL,
                    input_frequency INTEGER NOT NULL DEFAULT 0,
                    first_seen_ms INTEGER NOT NULL,
                    last_seen_ms INTEGER NOT NULL,
                    PRIMARY KEY(committed_text, app)
                );

                CREATE TABLE IF NOT EXISTS memory_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_ms INTEGER NOT NULL,
                    memory_id TEXT NOT NULL,
                    event_id INTEGER,
                    action_type TEXT NOT NULL,
                    query TEXT NOT NULL DEFAULT '',
                    suggestion_id TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS memory_feedback_events (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT,
                    candidate_text TEXT NOT NULL DEFAULT '',
                    candidate_source TEXT NOT NULL DEFAULT 'unknown',
                    action TEXT NOT NULL,
                    context_hash TEXT,
                    front_app_bundle_id TEXT,
                    raw_input TEXT,
                    preedit TEXT,
                    committed_tail TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rime_rank_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_ms INTEGER NOT NULL,
                    preedit TEXT NOT NULL,
                    rejected_text TEXT NOT NULL DEFAULT '',
                    accepted_text TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    app TEXT NOT NULL DEFAULT '',
                    project TEXT NOT NULL DEFAULT '',
                    candidate_rank INTEGER,
                    context_hash TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_rime_rank_feedback_lookup
                ON rime_rank_feedback(project, preedit, accepted_text, rejected_text, action);

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    content_text,
                    committed_text,
                    recent_context,
                    project,
                    tags,
                    tokenize = 'unicode61'
                );

                CREATE TABLE IF NOT EXISTS memory_vectors (
                    event_id INTEGER PRIMARY KEY,
                    provider_fingerprint TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES input_events(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_memory_vectors_provider
                ON memory_vectors(provider_fingerprint);
                """
            )
            ensure_memory_v2_schema(conn)
            conn.executescript(
                """
                DELETE FROM memory_state
                WHERE event_id NOT IN (SELECT id FROM input_events);

                DELETE FROM memory_vectors
                WHERE event_id NOT IN (SELECT id FROM input_events);

                UPDATE memory_actions
                SET event_id = NULL
                WHERE event_id IS NOT NULL
                  AND event_id NOT IN (SELECT id FROM input_events);
                """
            )
            conn.execute(
                """
                INSERT INTO phrase_stats(committed_text, input_frequency, first_seen_ms, last_seen_ms)
                SELECT e.committed_text, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE s.deleted = 0
                GROUP BY e.committed_text
                ON CONFLICT(committed_text) DO UPDATE SET
                    input_frequency = excluded.input_frequency,
                    first_seen_ms = excluded.first_seen_ms,
                    last_seen_ms = excluded.last_seen_ms
                """
            )
            conn.execute(
                """
                INSERT INTO phrase_project_stats(committed_text, project, input_frequency, first_seen_ms, last_seen_ms)
                SELECT e.committed_text, e.project, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE s.deleted = 0 AND e.project != ''
                GROUP BY e.committed_text, e.project
                ON CONFLICT(committed_text, project) DO UPDATE SET
                    input_frequency = excluded.input_frequency,
                    first_seen_ms = excluded.first_seen_ms,
                    last_seen_ms = excluded.last_seen_ms
                """
            )
            conn.execute(
                """
                INSERT INTO phrase_app_stats(committed_text, app, input_frequency, first_seen_ms, last_seen_ms)
                SELECT e.committed_text, e.app, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE s.deleted = 0 AND e.app != ''
                GROUP BY e.committed_text, e.app
                ON CONFLICT(committed_text, app) DO UPDATE SET
                    input_frequency = excluded.input_frequency,
                    first_seen_ms = excluded.first_seen_ms,
                    last_seen_ms = excluded.last_seen_ms
                """
            )

    def reset(self) -> None:
        table_names = tuple(
            dict.fromkeys(
                (
                    *memory_v2_table_names(),
                    "memory_vectors",
                    "memory_actions",
                    "memory_state",
                    "input_events",
                    "memory_fts",
                    "phrase_stats",
                    "phrase_project_stats",
                    "phrase_app_stats",
                )
            )
        )
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            for table in table_names:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()
        self._clear_suggestion_cache()

    def record_event(self, event: InputEvent) -> str:
        self.initialize()
        text = compact_whitespace(event.committed_text)
        if not text:
            raise ValueError("committed_text must not be empty")
        created_at = event.created_at_ms or now_ms()
        tags_json = json.dumps(list(event.tags), ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO input_events (
                    created_at_ms, source, committed_text, recent_context, preedit,
                    schema_id, app, project, candidate_rank, provider_name, tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    event.source,
                    text,
                    compact_whitespace(event.recent_context),
                    event.preedit,
                    event.schema_id,
                    event.app,
                    event.project,
                    event.candidate_rank,
                    event.provider_name,
                    tags_json,
                ),
            )
            event_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO memory_state(event_id, updated_at_ms) VALUES (?, ?)",
                (event_id, created_at),
            )
            conn.execute(
                """
                INSERT INTO phrase_stats(committed_text, input_frequency, first_seen_ms, last_seen_ms)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(committed_text) DO UPDATE SET
                    input_frequency = phrase_stats.input_frequency + 1,
                    last_seen_ms = excluded.last_seen_ms
                """,
                (text, created_at, created_at),
            )
            if event.project:
                conn.execute(
                    """
                    INSERT INTO phrase_project_stats(committed_text, project, input_frequency, first_seen_ms, last_seen_ms)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(committed_text, project) DO UPDATE SET
                        input_frequency = phrase_project_stats.input_frequency + 1,
                        last_seen_ms = excluded.last_seen_ms
                    """,
                    (text, event.project, created_at, created_at),
                )
            if event.app:
                conn.execute(
                    """
                    INSERT INTO phrase_app_stats(committed_text, app, input_frequency, first_seen_ms, last_seen_ms)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(committed_text, app) DO UPDATE SET
                        input_frequency = phrase_app_stats.input_frequency + 1,
                        last_seen_ms = excluded.last_seen_ms
                    """,
                    (text, event.app, created_at, created_at),
                )
            document = _event_fts_document(
                text,
                event.recent_context,
                event.project,
                " ".join(event.tags),
                event.preedit,
            )
            conn.execute(
                """
                INSERT INTO memory_fts(rowid, content_text, committed_text, recent_context, project, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, document, text, event.recent_context, event.project, " ".join(event.tags)),
            )
            self._upsert_event_vector(conn, event_id=event_id, document=document, updated_at_ms=created_at)
            if self.memory_v2_enabled:
                sync_event_to_memory_v2(
                    conn,
                    event_id=event_id,
                    created_at_ms=created_at,
                    source=event.source,
                    committed_text=text,
                    recent_context=event.recent_context,
                    preedit=event.preedit,
                    project=event.project,
                    app=event.app,
                    provider_name=event.provider_name,
                    tags=tuple(event.tags),
                    embedding_provider=self.embedding_provider,
                )
        self._clear_suggestion_cache()
        return f"event:{event_id}"

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        flags = load_hybrid_rag_runtime_flags()
        cache_key = self._suggestion_cache_key(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            mode="v3" if flags.hybrid_rag_core else "legacy",
            top_k=top_k,
        )
        cached = self._get_cached_suggestions(cache_key)
        if cached is not None:
            return cached
        if flags.hybrid_rag_core:
            try:
                candidates = self.retrieve_candidates_v3(
                    current_input=current_input,
                    recent_context=recent_context,
                    committed_context=recent_context,
                    project=project,
                    app=app,
                    top_k=top_k,
                    source_budget_ms=flags.rag_core_v3_budget_ms,
                )
                suggestions = memory_candidates_v2_to_input_suggestions(candidates)[:top_k]
                self._store_cached_suggestions(cache_key, suggestions)
                return _copy_suggestions(suggestions)
            except Exception:
                pass
        suggestions = self._legacy_suggest_for_input(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=top_k,
        )
        if self.memory_v2_enabled:
            context_v2 = ImeQueryContext(
                current_input=current_input,
                recent_context=recent_context,
                project=project,
                app=app,
                top_k=top_k,
            )
            if not suggestions:
                suggestions = self.suggest_for_ime_context_v2(context=context_v2)
            elif _legacy_suggestions_need_v2_recovery(
                suggestions,
                current_input=current_input,
                recent_context=recent_context,
            ):
                v2_suggestions = self.suggest_for_ime_context_v2(context=context_v2)
                if _should_prefer_v2_ime_suggestions(
                    legacy_suggestions=suggestions,
                    v2_suggestions=v2_suggestions,
                    current_input=current_input,
                    recent_context=recent_context,
                ):
                    suggestions = _merge_prefer_v2_suggestions(
                        v2_suggestions=v2_suggestions,
                        legacy_suggestions=suggestions,
                        top_k=top_k,
                        current_input=current_input,
                        recent_context=recent_context,
                    )
        self._store_cached_suggestions(cache_key, suggestions)
        return _copy_suggestions(suggestions)

    def retrieve_candidates_v3(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        committed_context: str = "",
        preedit: str = "",
        rime_candidates: tuple[str, ...] = (),
        project: str = "",
        app: str = "",
        top_k: int = 5,
        source_budget_ms: int = 25,
    ) -> list[MemoryCandidateV2]:
        self.initialize()
        with self._connect() as conn:
            return retrieve_rag_core_v3_candidates(
                conn,
                current_input=current_input,
                recent_context=recent_context,
                committed_context=committed_context,
                preedit=preedit,
                rime_candidates=tuple(rime_candidates),
                project=project,
                app=app,
                top_k=top_k,
                source_budget_ms=source_budget_ms,
            )

    def _legacy_suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        memories = self.retrieve_memories(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=max(top_k * 4, 20),
        )
        ranked = [RankedMemory(memory=memory, score=memory.score, rank=index) for index, memory in enumerate(memories, start=1)]
        return self.compiler.compile(ranked)[:top_k]

    def retrieve_memories(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
    ) -> list[CoreMemory]:
        self.initialize()
        raw_query = _build_retrieval_query(current_input=current_input, recent_context=recent_context, project=project, app=app)
        query = _expand_query_for_local_rerank(raw_query)
        fts_query = build_fts_query(query)
        rows, vector_scores = self._retrieve_candidate_rows(
            query=query,
            raw_query=raw_query,
            fts_query=fts_query,
            project=project,
            app=app,
            top_k=top_k,
        )
        if not rows and project:
            rows, vector_scores = self._retrieve_candidate_rows(
                query=query,
                raw_query=raw_query,
                fts_query=fts_query,
                project="",
                app=app,
                top_k=top_k,
            )
        if not rows and _recent_fill_enabled():
            rows = self._recent_rows(project=project, app=app, limit=top_k)
        elif rows and len(rows) < top_k and _recent_fill_enabled():
            rows = self._append_recent_fill(rows, project=project, app=app, limit=top_k)

        present_ms = now_ms()
        memories = [
            self._row_to_memory(
                row,
                query=query,
                project=project,
                app=app,
                raw_query=raw_query,
                vector_score=vector_scores.get(int(row["id"]), 0.0),
                present_ms=present_ms,
            )
            for row in rows
        ]
        memories.sort(key=lambda item: item.score, reverse=True)
        if self.memory_v2_enabled and self.legacy_governance_filter_enabled and memories:
            memories = self._filter_legacy_memories_with_governance(
                memories,
                current_input=current_input,
                recent_context=recent_context,
                project=project,
                app=app,
            )
        return memories[:top_k]

    def _filter_legacy_memories_with_governance(
        self,
        memories: list[CoreMemory],
        *,
        current_input: str,
        recent_context: str,
        project: str,
        app: str,
    ) -> list[CoreMemory]:
        if not memories:
            return memories
        governance = self.optimizer_governance_snapshot(
            memory_ids=[memory.memory_id for memory in memories],
            texts=[memory.text for memory in memories],
            source_event_ids=[
                int(memory.source_event_id)
                if compact_whitespace(str(memory.source_event_id or "")).isdigit()
                else None
                for memory in memories
            ],
            context_hash="",
            project=project,
            app=app,
        )
        tombstoned_ids = set(governance.get("tombstonedMemoryIds") or [])
        tombstoned_texts = set(governance.get("tombstonedTexts") or [])
        suppressed_ids = set(governance.get("suppressedMemoryIds") or [])
        suppressed_texts = set(governance.get("suppressedTexts") or [])
        filtered: list[CoreMemory] = []
        removed_any = False
        for memory in memories:
            normalized_text = _optimizer_norm(memory.text)
            if memory.memory_id in tombstoned_ids or normalized_text in tombstoned_texts:
                removed_any = True
                continue
            if memory.memory_id in suppressed_ids or normalized_text in suppressed_texts:
                removed_any = True
                continue
            filtered.append(memory)
        if removed_any:
            return filtered
        return memories

    def _retrieve_candidate_rows(
        self,
        *,
        query: str,
        raw_query: str,
        fts_query: str,
        project: str,
        app: str,
        top_k: int,
    ) -> tuple[list[sqlite3.Row], dict[int, float]]:
        rows: list[sqlite3.Row] = []
        if fts_query:
            rows = self._search_rows(fts_query=fts_query, project=project, app=app, limit=max(top_k * 8, 50))
        vector_rows, vector_scores = self._vector_rows(
            query=query,
            project=project,
            app=app,
            limit=max(top_k * 8, self.vector_candidate_limit),
        )
        rows = _merge_rows(rows, vector_rows)
        rows = [row for row in rows if not _row_looks_like_retrieval_noise(row)]
        filtered_rows = [
            row
            for row in rows
            if _row_matches_required_query(row, raw_query=raw_query)
            or _vector_only_match_allowed(raw_query=raw_query, vector_score=vector_scores.get(int(row["id"]), 0.0))
        ]
        if not filtered_rows and query != raw_query:
            filtered_rows = [
                row
                for row in rows
                if _row_matches_required_query(row, raw_query=query, allow_pinyin=False, relaxed=True)
                or _vector_only_match_allowed(raw_query=raw_query, vector_score=vector_scores.get(int(row["id"]), 0.0))
            ]
        return filtered_rows, vector_scores

    def apply_action(self, action: MemoryAction) -> MemoryAction:
        self.initialize()
        event_id = self._memory_id_to_event_id(action.memory_id)
        created_at = action.created_at_ms or now_ms()
        metadata_json = json.dumps(action.metadata or {}, ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM input_events WHERE id = ?", (event_id,)).fetchone()
            if exists is None:
                raise ValueError(f"unknown memory_id: {action.memory_id}")
            cur = conn.execute(
                """
                INSERT INTO memory_actions (
                    created_at_ms, memory_id, event_id, action_type, query, suggestion_id, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    action.memory_id,
                    event_id,
                    action.action_type,
                    action.query,
                    action.suggestion_id,
                    metadata_json,
                ),
            )
            self._apply_state_update(conn, event_id, action.action_type, created_at)
            if action.action_type in ("delete", "hide", "restore"):
                self._refresh_phrase_stats_for_event(conn, event_id)
                self._refresh_phrase_project_stats_for_event(conn, event_id)
                self._refresh_phrase_app_stats_for_event(conn, event_id)
            if self.memory_v2_enabled:
                self._record_feedback_v2(
                    conn,
                    feedback=CandidateFeedbackV2(
                        query_hash=_query_hash(action.query or action.suggestion_id or action.memory_id),
                        candidate_text=self._event_text(conn, event_id),
                        source_type="memory",
                        memory_ids=(action.memory_id,),
                        action=action.action_type,
                        app=action.metadata.get("app", "") if isinstance(action.metadata, dict) else "",
                        project=action.metadata.get("project", "") if isinstance(action.metadata, dict) else "",
                        metadata=action.metadata,
                    ),
                )
                self._sync_memory_item_status_for_action(conn, action=action, event_id=event_id)
            action_id = int(cur.lastrowid)
        self._clear_suggestion_cache()
        return MemoryAction(
            action_id=action_id,
            created_at_ms=created_at,
            memory_id=action.memory_id,
            action_type=action.action_type,
            query=action.query,
            suggestion_id=action.suggestion_id,
            source_event_id=event_id,
            metadata=action.metadata,
        )

    def build_agent_context(self, *, project: str, query: str, top_k: int = 5) -> AgentContextInjection:
        memories = self.retrieve_memories(current_input=query, project=project, top_k=top_k)
        lines = [
            "PROJECT_MEMORY_BLOCK",
            f"- 当前项目: {project or 'wisdom-weasel-rag-ime'}",
            "- 来源: local SQLite/FTS5 personal memory",
            "- 隐私边界: 默认本地检索和排序, 不上传个人输入历史。",
        ]
        for index, memory in enumerate(memories, start=1):
            lines.append(f"  {index}. [{memory.memory_id}] {truncate_text(memory.text, 90)}")
            lines.append(f"     preview: {truncate_text(memory.evidence_preview, 160)}")
        if not memories:
            lines.append("  (no local memories matched)")
        return AgentContextInjection(
            project=project,
            generated_at_ms=now_ms(),
            block="\n".join(lines),
            source_event_ids=tuple(self._memory_id_to_event_id(memory.memory_id) for memory in memories),
            query=query,
        )

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        self.initialize()
        if limit <= 0 or max_chars <= 0:
            return ""
        params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        sql = f"""
            SELECT e.committed_text, e.recent_context, e.preedit, e.created_at_ms, e.source, e.provider_name, e.tags_json
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
            ORDER BY e.id DESC
            LIMIT ?
        """
        params.append(max(1, min(40, max(limit * 4, limit))))
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())

        selected: list[str] = []
        used_chars = 0
        separator_len = len(" / ")
        for row in rows:
            if _row_should_skip_recent_context(row):
                continue
            text = compact_whitespace(str(row["committed_text"]))
            if not text:
                continue
            context = compact_whitespace(str(row["recent_context"]))
            preedit = compact_whitespace(str(row["preedit"]))
            parts = [truncate_text(text, 90)]
            if context and context != text:
                parts.append(f"context: {truncate_text(context, 90)}")
            if preedit and preedit != text:
                parts.append(f"preedit: {truncate_text(preedit, 48)}")
            snippet = " | ".join(parts)
            next_len = len(snippet) + (separator_len if selected else 0)
            if selected and used_chars + next_len > max_chars:
                break
            if not selected and len(snippet) > max_chars:
                snippet = _tail_chars(snippet, max_chars)
                next_len = len(snippet)
            selected.append(snippet)
            used_chars += next_len
            if len(selected) >= limit:
                break
        return compact_whitespace(" / ".join(reversed(selected)))

    def retrieve_candidates_v2(self, *, context: ImeQueryContext) -> dict[str, object]:
        memories, stats = self._retrieve_memories_v2(context)
        return {
            "ok": True,
            "candidates": [
                {
                    "text": item.text,
                    "sourceType": _source_type_from_tags_v2(item.tags),
                    "memoryKind": str(item.state.get("memory_kind", "")),
                    "score": round(item.score, 4),
                    "memoryIds": [item.memory_id],
                    "evidencePreview": item.evidence_preview,
                    "diagnostics": {
                        "scoreBreakdown": item.state.get("score_breakdown", {}),
                        "evidence": [item.memory_id, f"kind:{item.state.get('memory_kind', '')}"],
                    },
                }
                for item in memories
            ],
            "stats": stats,
        }

    def suggest_for_ime_context_v2(self, *, context: ImeQueryContext) -> list[InputSuggestion]:
        memories, _stats = self._retrieve_memories_v2(context)
        ranked = [RankedMemory(memory=memory, score=memory.score, rank=index) for index, memory in enumerate(memories, start=1)]
        suggestions = self.compiler.compile(ranked)[: max(1, context.top_k)]
        return _copy_suggestions(suggestions)

    def record_feedback_v2(self, feedback: CandidateFeedbackV2) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            self._record_feedback_v2(conn, feedback=feedback)
        self._clear_suggestion_cache()
        return {
            "ok": True,
            "queryHash": feedback.query_hash,
            "action": feedback.action,
            "memoryIds": list(feedback.memory_ids),
        }

    def inspect_memory_v2(self, *, project: str = "", limit: int = 20, kind: str = "", status: str = "") -> dict[str, object]:
        self.initialize()
        params: list[Any] = []
        where = ["1 = 1"]
        if project:
            where.append("(project = ? OR project = '')")
            params.append(project)
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(max(1, min(200, int(limit))))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, memory_id, kind, text, normalized_text, source_event_id, project, app,
                       confidence, quality_score, status, privacy_class, created_at_ms, updated_at_ms, metadata_json
                FROM memory_items
                WHERE {' AND '.join(where)}
                ORDER BY updated_at_ms DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return {
            "schemaVersion": "rag-ime.memory-inspect.v2",
            "project": project,
            "limit": max(1, min(200, int(limit))),
            "items": [
                {
                    "id": int(row["id"]),
                    "memoryId": str(row["memory_id"]),
                    "kind": str(row["kind"]),
                    "text": str(row["text"]),
                    "normalizedText": str(row["normalized_text"]),
                    "sourceEventId": int(row["source_event_id"] or 0),
                    "project": str(row["project"]),
                    "app": str(row["app"]),
                    "confidence": float(row["confidence"]),
                    "qualityScore": float(row["quality_score"]),
                    "status": str(row["status"]),
                    "privacyClass": str(row["privacy_class"]),
                    "createdAtMs": int(row["created_at_ms"]),
                    "updatedAtMs": int(row["updated_at_ms"]),
                    "metadata": _json_loads_dict(row["metadata_json"]),
                }
                for row in rows
            ],
        }

    def optimizer_governance_snapshot(
        self,
        *,
        memory_ids: list[str],
        texts: list[str],
        source_event_ids: list[int | None] | None = None,
        context_hash: str = "",
        project: str = "",
        app: str = "",
    ) -> dict[str, object]:
        del context_hash
        self.initialize()
        normalized_texts = [_optimizer_norm(text) for text in texts if _optimizer_norm(text)]
        source_event_tokens = {
            f"event:{int(source_event_id)}"
            for source_event_id in (source_event_ids or [])
            if int(source_event_id or 0) > 0
        }
        candidate_records = list(
            zip(
                memory_ids,
                [_optimizer_norm(text) for text in texts],
                [int(source_event_id or 0) for source_event_id in (source_event_ids or [None] * len(memory_ids))],
            )
        )
        with self._connect() as conn:
            tombstoned_memory_ids = {
                str(row["target_value"])
                for row in conn.execute(
                    """
                    SELECT target_value
                    FROM memory_tombstones
                    WHERE active = 1 AND target_type = 'memory_id'
                    """
                ).fetchall()
                if str(row["target_value"]) in set(memory_ids)
            }
            tombstoned_texts = {
                _optimizer_norm(str(row["target_value"]))
                for row in conn.execute(
                    """
                    SELECT target_value
                    FROM memory_tombstones
                    WHERE active = 1 AND target_type IN ('normalized_text', 'phrase')
                    """
                ).fetchall()
                if _optimizer_norm(str(row["target_value"])) in set(normalized_texts)
            }
            suppressed_rows = conn.execute(
                """
                SELECT match_type, match_value
                FROM memory_candidate_suppressions
                WHERE expires_at_ms IS NULL OR expires_at_ms > ?
                """,
                (now_ms(),),
            ).fetchall()
            suppressed_memory_ids = {
                str(row["match_value"])
                for row in suppressed_rows
                if str(row["match_type"]) == "memory_id" and str(row["match_value"]) in set(memory_ids)
            }
            suppressed_texts = {
                _optimizer_norm(str(row["match_value"]))
                for row in suppressed_rows
                if str(row["match_type"]) in {"text", "normalized_text"} and _optimizer_norm(str(row["match_value"])) in set(normalized_texts)
            }
            suppressed_event_tokens = {
                str(row["match_value"])
                for row in suppressed_rows
                if str(row["match_type"]) == "memory_id" and str(row["match_value"]) in source_event_tokens
            }
            if suppressed_event_tokens:
                for memory_id, normalized_text, source_event_id in candidate_records:
                    if source_event_id <= 0:
                        continue
                    if f"event:{source_event_id}" not in suppressed_event_tokens:
                        continue
                    suppressed_memory_ids.add(memory_id)
                    if normalized_text:
                        suppressed_texts.add(normalized_text)
            params: list[Any] = [max(0, now_ms() - 30_000)]
            where = ["e.created_at_ms >= ?", "s.deleted = 0"]
            if project:
                where.append("(e.project = ? OR e.project = '')")
                params.append(project)
            if app:
                where.append("(e.app = ? OR e.app = '')")
                params.append(app)
            recent_rows = conn.execute(
                f"""
                SELECT e.committed_text
                FROM input_events e
                JOIN memory_state s ON s.event_id = e.id
                WHERE {' AND '.join(where)}
                ORDER BY e.created_at_ms DESC
                LIMIT 12
                """,
                params,
            ).fetchall()
        return {
            "tombstonedMemoryIds": sorted(tombstoned_memory_ids),
            "tombstonedTexts": sorted(tombstoned_texts),
            "suppressedMemoryIds": sorted(suppressed_memory_ids),
            "suppressedTexts": sorted(suppressed_texts),
            "recentCommittedTexts": sorted({_optimizer_norm(str(row["committed_text"])) for row in recent_rows if _optimizer_norm(str(row["committed_text"]))}),
        }

    def record_memory_feedback(self, event: dict[str, Any]) -> None:
        self.initialize()
        action = compact_whitespace(str(event.get("event") or event.get("action") or "")).lower()
        candidate_id = compact_whitespace(str(event.get("candidateId") or event.get("memoryId") or ""))
        candidate_text = compact_whitespace(str(event.get("candidateText") or event.get("text") or ""))
        candidate_source = compact_whitespace(str(event.get("sourceType") or event.get("candidateSource") or event.get("source") or ""))
        if not action or (not candidate_id and not candidate_text):
            return
        created_at_ms = int(event.get("timestampMs") or event.get("createdAtMs") or now_ms())
        context_hash = compact_whitespace(str(event.get("contextHash") or ""))
        metadata = dict(event.get("metadata") or {}) if isinstance(event.get("metadata"), dict) else {}
        for key in (
            "lane",
            "rank",
            "project",
            "traceId",
            "requestSeq",
            "sessionId",
            "suggestionId",
            "sourceEventId",
            "selectedCandidateId",
            "selectedText",
            "selectedRank",
            "shownCandidateIds",
            "shownCandidateCount",
        ):
            if key in event and key not in metadata:
                metadata[key] = event.get(key)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_feedback_events(
                    id, candidate_id, candidate_text, candidate_source, action, context_hash,
                    front_app_bundle_id, raw_input, preedit, committed_tail, metadata_json, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _memory_feedback_event_id(
                        action=action,
                        candidate_id=candidate_id,
                        candidate_text=candidate_text,
                        created_at_ms=created_at_ms,
                    ),
                    candidate_id or None,
                    candidate_text,
                    candidate_source or "unknown",
                    action,
                    context_hash or None,
                    compact_whitespace(str(event.get("frontAppBundleId") or event.get("app") or "")) or None,
                    compact_whitespace(str(event.get("rawInput") or "")) or None,
                    compact_whitespace(str(event.get("preedit") or "")) or None,
                    compact_whitespace(str(event.get("committedTail") or event.get("recentContext") or "")) or None,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    created_at_ms,
                ),
            )
            governance_changed = self._apply_optimizer_feedback_governance(
                conn,
                action=action,
                candidate_id=candidate_id,
                candidate_text=candidate_text,
                candidate_source=candidate_source,
                context_hash=context_hash,
                created_at_ms=created_at_ms,
                metadata=metadata,
            )
        if governance_changed:
            self._clear_suggestion_cache()

    def optimize_memory_candidates(
        self,
        context: ContextFrame,
        base_hits: list[RawRetrievalHit],
        *,
        top_k: int,
        latency_budget_ms: int,
    ) -> OptimizerResult:
        self.initialize()
        from .memory_optimizer import MemoryOptimizerConfig, RagMemoryOptimizer

        config = MemoryOptimizerConfig.from_env()
        optimizer = RagMemoryOptimizer(config=config)
        governance = self.optimizer_governance_snapshot(
            memory_ids=[hit.id for hit in base_hits],
            texts=[hit.text for hit in base_hits],
            source_event_ids=[int(hit.metadata.get("source_event_id") or 0) or None for hit in base_hits],
            context_hash=context.context_hash,
            project=context.project_scope or "",
            app=context.front_app_bundle_id or "",
        )
        return optimizer.optimize_memory_candidates(
            context,
            base_hits,
            top_k=top_k,
            latency_budget_ms=min(latency_budget_ms, config.max_ms),
            governance=governance,
        )

    def explain_memory_candidate(self, candidate_id: str, context_hash: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        candidate_key = compact_whitespace(candidate_id)
        if not candidate_key:
            return None
        normalized_context_hash = compact_whitespace(context_hash or "")
        with self._connect() as conn:
            memory_row = conn.execute(
                """
                SELECT id, memory_id, kind, text, normalized_text, source_event_id, project, app,
                       confidence, quality_score, status, privacy_class, created_at_ms, updated_at_ms, metadata_json
                FROM memory_items
                WHERE memory_id = ?
                   OR (source_event_id = ? AND ? != '')
                ORDER BY updated_at_ms DESC, id DESC
                LIMIT 1
                """,
                (
                    candidate_key,
                    self._memory_id_to_event_id(candidate_key) if candidate_key.startswith("event:") else 0,
                    candidate_key if candidate_key.startswith("event:") else "",
                ),
            ).fetchone()
            feedback_rows = conn.execute(
                """
                SELECT candidate_id, candidate_text, candidate_source, action, context_hash,
                       front_app_bundle_id, raw_input, preedit, committed_tail, metadata_json, created_at_ms
                FROM memory_feedback_events
                WHERE candidate_id = ? OR candidate_text = ?
                ORDER BY created_at_ms DESC
                LIMIT 12
                """,
                (candidate_key, candidate_key),
            ).fetchall()
            trace_rows = conn.execute(
                """
                SELECT id, request_seq, context_hash, query_plan_json, raw_results_json,
                       optimized_candidates_json, blocked_json, latency_ms, created_at_ms
                FROM memory_optimizer_traces
                WHERE (? != '' AND context_hash = ?)
                   OR optimized_candidates_json LIKE ?
                   OR blocked_json LIKE ?
                ORDER BY created_at_ms DESC
                LIMIT 8
                """,
                (
                    normalized_context_hash,
                    normalized_context_hash,
                    f'%"{candidate_key}"%',
                    f'%"{candidate_key}"%',
                ),
            ).fetchall()
        if memory_row is None and not feedback_rows and not trace_rows:
            return None
        traces = [
            _optimizer_trace_row_payload(row)
            for row in trace_rows
        ]
        recent_trace = traces[0] if traces else None
        return {
            "schemaVersion": "rag-ime.memory-candidate-explain.v1",
            "candidateId": candidate_key,
            "contextHash": normalized_context_hash or (recent_trace.get("contextHash") if isinstance(recent_trace, dict) else "") or "",
            "memoryItem": _memory_item_explanation_payload(memory_row) if memory_row is not None else None,
            "recentFeedback": [_memory_feedback_row_payload(row) for row in feedback_rows],
            "recentTrace": recent_trace,
            "traceCount": len(traces),
            "traces": traces,
        }

    def store_memory_optimizer_trace(self, trace: dict[str, Any]) -> None:
        self.initialize()
        trace_id = compact_whitespace(str(trace.get("traceId") or ""))
        if not trace_id:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_optimizer_traces(
                    id, request_seq, context_hash, query_plan_json, raw_results_json,
                    optimized_candidates_json, blocked_json, latency_ms, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    int(trace.get("requestSeq") or 0),
                    compact_whitespace(str(trace.get("contextHash") or "")),
                    json.dumps(
                        {
                            "contextFrame": trace.get("contextFrame") or {},
                            "queryPlan": trace.get("queryPlan") or {},
                            "warnings": list(trace.get("warnings") or []),
                            "degraded": bool(trace.get("degraded")),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(list(trace.get("rawResults") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(trace.get("optimizedCandidates") or []), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(trace.get("blocked") or []), ensure_ascii=False, sort_keys=True),
                    float(trace.get("latencyMs") or 0.0),
                    int(trace.get("createdAtMs") or now_ms()),
                ),
            )

    def get_memory_optimizer_trace(self, trace_id: str) -> dict[str, Any] | None:
        self.initialize()
        trace_key = compact_whitespace(trace_id)
        if not trace_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, request_seq, context_hash, query_plan_json, raw_results_json,
                       optimized_candidates_json, blocked_json, latency_ms, created_at_ms
                FROM memory_optimizer_traces
                WHERE id = ?
                LIMIT 1
                """,
                (trace_key,),
            ).fetchone()
        if row is None:
            return None
        return _optimizer_trace_row_payload(row)

    def inspect_memory_governance(self, *, limit: int = 20, include_inactive: bool = False) -> dict[str, object]:
        self.initialize()
        bounded_limit = max(1, min(200, int(limit)))
        with self._connect() as conn:
            suppression_rows = conn.execute(
                """
                SELECT id, match_type, match_value, action, reason, strength, expires_at_ms, created_at_ms
                FROM memory_candidate_suppressions
                ORDER BY created_at_ms DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
            tombstone_rows = conn.execute(
                f"""
                SELECT id, created_at_ms, target_type, target_value, reason, active, metadata_json
                FROM memory_tombstones
                {'WHERE active = 1' if not include_inactive else ''}
                ORDER BY created_at_ms DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        suppressions = [_memory_suppression_row_payload(row) for row in suppression_rows]
        if not include_inactive:
            suppressions = [item for item in suppressions if item["active"]]
        return {
            "schemaVersion": "rag-ime.memory-governance.v1",
            "limit": bounded_limit,
            "includeInactive": bool(include_inactive),
            "suppressions": suppressions,
            "tombstones": [_memory_tombstone_row_payload(row) for row in tombstone_rows],
        }

    def add_memory_tombstone(
        self,
        *,
        target_type: str,
        target_value: str,
        reason: str = "manual",
        metadata: dict[str, object] | None = None,
        active: bool = True,
    ) -> dict[str, object]:
        self.initialize()
        normalized_target_type = compact_whitespace(target_type)
        normalized_target_value = compact_whitespace(target_value)
        if normalized_target_type not in {"memory_id", "normalized_text", "phrase", "source_event_id"}:
            raise ValueError(f"unsupported tombstone target_type: {target_type}")
        if not normalized_target_value:
            raise ValueError("target_value is required")
        created_at_ms = now_ms()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at_ms,
                    normalized_target_type,
                    normalized_target_value,
                    compact_whitespace(reason) or "manual",
                    1 if active else 0,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
            tombstone_id = int(cur.lastrowid)
            if normalized_target_type == "memory_id":
                row = conn.execute(
                    """
                    SELECT normalized_text, source_event_id
                    FROM memory_items
                    WHERE memory_id = ?
                    LIMIT 1
                    """,
                    (normalized_target_value,),
                ).fetchone()
                conn.execute(
                    "UPDATE memory_items SET status = 'tombstoned', updated_at_ms = ? WHERE memory_id = ?",
                    (created_at_ms, normalized_target_value),
                )
                related_clauses: list[str] = ["memory_id = ?"]
                related_params: list[Any] = [created_at_ms, normalized_target_value]
                related_normalized_text = compact_whitespace(str(row["normalized_text"] or "")) if row is not None else ""
                related_source_event_id = int(row["source_event_id"] or 0) if row is not None else 0
                if related_normalized_text:
                    related_clauses.append("normalized_text = ?")
                    related_params.append(related_normalized_text)
                if related_source_event_id > 0:
                    related_clauses.append("source_event_id = ?")
                    related_params.append(related_source_event_id)
                elif normalized_target_value.startswith("phrase:"):
                    derived_text = compact_whitespace(normalized_target_value.split(":", 1)[1])
                    if derived_text:
                        related_clauses.append("normalized_text = ?")
                        related_params.append(derived_text)
                if len(related_clauses) > 1:
                    conn.execute(
                        f"""
                        UPDATE memory_items
                        SET status = 'tombstoned', updated_at_ms = ?
                        WHERE {' OR '.join(related_clauses)}
                        """,
                        related_params,
                    )
            elif normalized_target_type == "source_event_id":
                conn.execute(
                    "UPDATE memory_items SET status = 'tombstoned', updated_at_ms = ? WHERE source_event_id = ?",
                    (created_at_ms, int(normalized_target_value)),
                )
            elif normalized_target_type == "normalized_text":
                conn.execute(
                    "UPDATE memory_items SET status = 'tombstoned', updated_at_ms = ? WHERE normalized_text = ?",
                    (created_at_ms, normalized_target_value),
                )
            elif normalized_target_type == "phrase":
                conn.execute(
                    "UPDATE memory_items SET status = 'tombstoned', updated_at_ms = ? WHERE text = ?",
                    (created_at_ms, normalized_target_value),
                )
            row = conn.execute(
                """
                SELECT id, created_at_ms, target_type, target_value, reason, active, metadata_json
                FROM memory_tombstones
                WHERE id = ?
                LIMIT 1
                """,
                (tombstone_id,),
            ).fetchone()
        self._clear_suggestion_cache()
        if row is None:
            raise RuntimeError("failed to create tombstone")
        return _memory_tombstone_row_payload(row)

    def list_memory_cleanup_runs(self, *, limit: int = 20, run_id: str = "", status: str = "") -> dict[str, object]:
        self.initialize()
        bounded_limit = max(1, min(100, int(limit)))
        params: list[Any] = []
        where = ["1 = 1"]
        if run_id:
            where.append("run_id = ?")
            params.append(run_id)
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(bounded_limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id
                FROM memory_cleanup_runs
                WHERE {' AND '.join(where)}
                ORDER BY created_at_ms DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            runs = [
                cleanup_run_payload(conn, run_id=str(row["run_id"]))
                for row in rows
            ]
        return {
            "schemaVersion": "rag-ime.memory-cleanup-runs.v1",
            "limit": bounded_limit,
            "items": runs,
        }

    def recompute_memory_tags(self, *, project: str = "") -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            report = recompute_tag_graph(conn, project=project)
        self._clear_suggestion_cache()
        return {"schemaVersion": "rag-ime.memory-tags.v2", **report}

    def build_memory_cleanup_plan(self, *, project: str = "", since_days: int = 90, provider: str = "", model: str = "") -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            plan = build_cleanup_plan(conn, project=project, since_days=since_days, provider=provider, model=model)
            persist_cleanup_plan(conn, plan)
        return cleanup_plan_to_payload(plan)

    def preview_memory_cleanup_plan(self, *, project: str = "", since_days: int = 90, provider: str = "", model: str = "") -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            plan = build_cleanup_plan(conn, project=project, since_days=since_days, provider=provider, model=model)
        return cleanup_plan_to_payload(plan)

    def store_memory_cleanup_plan(self, plan: CleanupRunPlan) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            payload = persist_cleanup_plan(conn, plan)
        return payload

    def review_memory_cleanup_plan(
        self,
        *,
        run_id: str,
        status: str,
        diff_ids: list[int] | tuple[int, ...] = (),
        diff_indexes: list[int] | tuple[int, ...] = (),
    ) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            payload = review_cleanup_run(
                conn,
                run_id=run_id,
                status=status,
                diff_ids=tuple(int(item) for item in diff_ids),
                diff_indexes=tuple(int(item) for item in diff_indexes),
            )
        return payload

    def apply_memory_cleanup_plan(self, *, run_path: str = "", run_id: str = "", only_approved: bool = False) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            if run_path:
                persist_cleanup_plan(conn, load_cleanup_run_from_file(run_path))
                run_id = load_cleanup_run_from_file(run_path).run_id
            if not run_id:
                raise ValueError("run_id or run_path is required")
            payload = apply_cleanup_run(conn, run_id=run_id, only_approved=only_approved)
        self._clear_suggestion_cache()
        return payload

    def rollback_memory_cleanup_plan(self, *, run_id: str) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            payload = rollback_cleanup_run(conn, run_id=run_id)
        self._clear_suggestion_cache()
        return payload

    def apply_memory_cleanup_diff(self, *, diff_id: int) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            payload = apply_cleanup_diff(conn, diff_id=int(diff_id))
            run_payload = cleanup_run_payload(conn, run_id=str(payload["runId"]))
        self._clear_suggestion_cache()
        return {
            "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
            "diff": payload,
            "run": run_payload,
        }

    def rollback_memory_cleanup_diff(self, *, diff_id: int) -> dict[str, object]:
        self.initialize()
        with self._connect() as conn:
            payload = rollback_cleanup_diff(conn, diff_id=int(diff_id))
            run_payload = cleanup_run_payload(conn, run_id=str(payload["runId"]))
        self._clear_suggestion_cache()
        return {
            "schemaVersion": "rag-ime.memory-cleanup-diff.v1",
            "diff": payload,
            "run": run_payload,
        }

    def event_count(self) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM input_events").fetchone()
        return int(row["count"])

    def action_count(self) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM memory_actions").fetchone()
        return int(row["count"])

    def suggestion_cache_stats(self) -> dict[str, object]:
        with self._suggestion_cache_lock:
            total = self._suggestion_cache_hits + self._suggestion_cache_misses
            return {
                "enabled": self.suggestion_cache_size > 0,
                "size": len(self._suggestion_cache),
                "maxSize": self.suggestion_cache_size,
                "hits": self._suggestion_cache_hits,
                "misses": self._suggestion_cache_misses,
                "hitRate": (self._suggestion_cache_hits / total) if total else 0.0,
                "evictions": self._suggestion_cache_evictions,
                "invalidations": self._suggestion_cache_invalidations,
            }

    def vector_index_stats(self) -> dict[str, object]:
        self.initialize()
        fingerprint = self.embedding_provider.fingerprint
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) AS count FROM memory_vectors").fetchone()["count"])
            active = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM memory_vectors WHERE provider_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()["count"]
            )
        return {
            "enabled": self._embedding_enabled(),
            "providerFingerprint": fingerprint,
            "totalVectors": total,
            "activeProviderVectors": active,
            "candidateLimit": self.vector_candidate_limit,
            "weight": self.vector_weight,
        }

    def rebuild_vector_index(self, *, project: str = "", limit: int = 0) -> dict[str, object]:
        self.initialize()
        if not self._embedding_enabled():
            return {
                "enabled": False,
                "providerFingerprint": self.embedding_provider.fingerprint,
                "scanned": 0,
                "indexed": 0,
            }
        params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        sql = f"""
            SELECT e.*
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
            ORDER BY e.id DESC
        """
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        scanned = 0
        indexed = 0
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())
            for row in rows:
                scanned += 1
                document = build_fts_document(
                    str(row["committed_text"]),
                    str(row["recent_context"]),
                    str(row["project"]),
                    " ".join(json.loads(row["tags_json"] or "[]")),
                    str(row["preedit"]),
                )
                if self._upsert_event_vector(
                    conn,
                    event_id=int(row["id"]),
                    document=document,
                    updated_at_ms=now_ms(),
                ):
                    indexed += 1
        self._clear_suggestion_cache()
        return {
            "enabled": True,
            "providerFingerprint": self.embedding_provider.fingerprint,
            "scanned": scanned,
            "indexed": indexed,
        }

    def has_event_tag(self, tag: str) -> bool:
        self.initialize()
        needle = compact_whitespace(tag)
        if not needle:
            return False
        with self._connect() as conn:
            rows = conn.execute("SELECT tags_json FROM input_events WHERE tags_json LIKE ?", (f'%"{needle}"%',)).fetchall()
        for row in rows:
            try:
                tags = json.loads(row["tags_json"] or "[]")
            except json.JSONDecodeError:
                continue
            if needle in tags:
                return True
        return False

    def list_memory_events(
        self,
        *,
        project: str = "",
        query: str = "",
        source: str = "",
        include_deleted: bool = False,
        generated_only: bool = False,
        limit: int = 80,
    ) -> dict[str, object]:
        self.initialize()
        params: list[Any] = []
        where = ["1 = 1"]
        if not include_deleted:
            where.append("s.deleted = 0")
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        if source:
            where.append("e.source = ?")
            params.append(source)
        if generated_only:
            where.append("e.tags_json LIKE ?")
            params.append('%"generated-memory"%')
        normalized_query = compact_whitespace(query)
        if normalized_query:
            like = f"%{normalized_query}%"
            where.append("(e.committed_text LIKE ? OR e.recent_context LIKE ? OR e.tags_json LIKE ?)")
            params.extend([like, like, like])
        capped_limit = max(1, min(500, int(limit)))
        sql = f"""
            SELECT
                e.id, e.created_at_ms, e.source, e.committed_text, e.recent_context,
                e.preedit, e.schema_id, e.app, e.project, e.candidate_rank,
                e.provider_name, e.tags_json,
                s.deleted, s.accepted_count, s.skipped_count, s.downranked, s.pinned,
                COALESCE(ps.input_frequency, 0) AS input_frequency
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            WHERE {' AND '.join(where)}
            ORDER BY e.id DESC
            LIMIT ?
        """
        params.append(capped_limit)
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())
            totals = {
                "active": int(conn.execute("SELECT COUNT(*) AS count FROM memory_state WHERE deleted = 0").fetchone()["count"]),
                "hidden": int(conn.execute("SELECT COUNT(*) AS count FROM memory_state WHERE deleted = 1").fetchone()["count"]),
                "generated": int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM input_events e
                        JOIN memory_state s ON s.event_id = e.id
                        WHERE s.deleted = 0 AND e.tags_json LIKE '%"generated-memory"%'
                        """
                    ).fetchone()["count"]
                ),
            }
        return {
            "schemaVersion": "rag-ime.memory-history.v1",
            "project": project,
            "query": normalized_query,
            "limit": capped_limit,
            "totals": totals,
            "items": [_memory_event_row_payload(row) for row in rows],
        }

    def core_optimization_snapshot(
        self,
        *,
        project: str = "",
        recent_limit: int = 80,
        phrase_limit: int = 60,
    ) -> dict[str, object]:
        self.initialize()
        recent_limit = max(1, min(300, int(recent_limit)))
        phrase_limit = max(1, min(300, int(phrase_limit)))
        params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        recent_sql = f"""
            SELECT
                e.id, e.created_at_ms, e.source, e.committed_text, e.recent_context,
                e.preedit, e.schema_id, e.app, e.project, e.candidate_rank,
                e.provider_name, e.tags_json,
                s.deleted, s.accepted_count, s.skipped_count, s.downranked, s.pinned,
                COALESCE(ps.input_frequency, 0) AS input_frequency
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            WHERE {' AND '.join(where)}
            ORDER BY e.id DESC
            LIMIT ?
        """
        recent_params = [*params, recent_limit]
        phrase_params: list[Any] = []
        phrase_where = ["s.deleted = 0", "LENGTH(e.committed_text) BETWEEN 2 AND 40"]
        if project:
            phrase_where.append("(e.project = ? OR e.project = '')")
            phrase_params.append(project)
        phrase_sql = f"""
            SELECT
                e.committed_text,
                COUNT(*) AS input_frequency,
                MAX(e.created_at_ms) AS last_seen_ms,
                SUM(s.accepted_count) AS accepted_count,
                SUM(s.skipped_count) AS skipped_count,
                MAX(s.pinned) AS pinned,
                GROUP_CONCAT(DISTINCT e.source) AS sources,
                GROUP_CONCAT(DISTINCT e.provider_name) AS providers
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(phrase_where)}
            GROUP BY e.committed_text
            ORDER BY input_frequency DESC, last_seen_ms DESC
            LIMIT ?
        """
        phrase_params.append(phrase_limit)
        with self._connect() as conn:
            recent_rows = list(conn.execute(recent_sql, recent_params).fetchall())
            phrase_rows = list(conn.execute(phrase_sql, phrase_params).fetchall())
            totals = {
                "active": int(conn.execute("SELECT COUNT(*) FROM memory_state WHERE deleted = 0").fetchone()[0]),
                "hidden": int(conn.execute("SELECT COUNT(*) FROM memory_state WHERE deleted = 1").fetchone()[0]),
                "phrases": int(conn.execute("SELECT COUNT(*) FROM phrase_stats").fetchone()[0]),
            }
        return {
            "schemaVersion": "rag-ime.core-optimization-snapshot.v1",
            "project": project,
            "totals": totals,
            "recentEvents": [_memory_event_row_payload(row) for row in recent_rows],
            "highFrequencyPhrases": [
                {
                    "text": str(row["committed_text"]),
                    "inputFrequency": int(row["input_frequency"] or 0),
                    "acceptedCount": int(row["accepted_count"] or 0),
                    "skippedCount": int(row["skipped_count"] or 0),
                    "pinned": bool(row["pinned"]),
                    "lastSeenMs": int(row["last_seen_ms"] or 0),
                    "sources": _csv_field(str(row["sources"] or "")),
                    "providers": _csv_field(str(row["providers"] or "")),
                }
                for row in phrase_rows
            ],
        }

    def hide_codex_history_noise(
        self,
        *,
        project: str = "",
        keep_roles: tuple[str, ...] = ("user",),
        dry_run: bool = False,
    ) -> dict[str, object]:
        self.initialize()
        keep_role_tags = {f"role:{compact_whitespace(role).lower()}" for role in keep_roles if compact_whitespace(role)}
        params: list[Any] = ["codex_history"]
        where = ["e.source = ?"]
        if project:
            where.append("e.project = ?")
            params.append(project)
        sql = f"""
            SELECT e.id, e.tags_json, s.deleted
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
        """
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())
            matched = 0
            already_deleted = 0
            role_counts: dict[str, int] = {}
            event_ids_to_hide: list[int] = []
            for row in rows:
                tags = _row_tags(row)
                role_tags = {tag.lower() for tag in tags if tag.lower().startswith("role:")}
                if role_tags:
                    for tag in sorted(role_tags):
                        role_counts[tag.removeprefix("role:")] = role_counts.get(tag.removeprefix("role:"), 0) + 1
                else:
                    role_counts["unlabeled"] = role_counts.get("unlabeled", 0) + 1
                should_keep = bool(keep_role_tags and role_tags.intersection(keep_role_tags))
                if should_keep:
                    continue
                matched += 1
                if int(row["deleted"]):
                    already_deleted += 1
                    continue
                event_ids_to_hide.append(int(row["id"]))
            if event_ids_to_hide and not dry_run:
                updated_at = now_ms()
                conn.executemany(
                    "UPDATE memory_state SET deleted = 1, updated_at_ms = ? WHERE event_id = ?",
                    [(updated_at, event_id) for event_id in event_ids_to_hide],
                )
                metadata_json = json.dumps(
                    {
                        "reason": "codex-history-role-prune",
                        "keepRoles": sorted(role.removeprefix("role:") for role in keep_role_tags),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                conn.executemany(
                    """
                    INSERT INTO memory_actions (
                        created_at_ms, memory_id, event_id, action_type, query, suggestion_id, metadata_json
                    )
                    VALUES (?, ?, ?, 'hide', 'codex-history-noise-prune', '', ?)
                    """,
                    [(updated_at, f"event:{event_id}", event_id, metadata_json) for event_id in event_ids_to_hide],
                )
                self._rebuild_all_phrase_stats(conn)
        if event_ids_to_hide and not dry_run:
            self._clear_suggestion_cache()
        return {
            "source": "codex_history",
            "project": project,
            "keepRoles": sorted(role.removeprefix("role:") for role in keep_role_tags),
            "dryRun": dry_run,
            "scanned": len(rows),
            "matchedNoise": matched,
            "alreadyDeleted": already_deleted,
            "hidden": 0 if dry_run else len(event_ids_to_hide),
            "wouldHide": len(event_ids_to_hide),
            "roleCounts": role_counts,
        }

    def organize_rag_database(
        self,
        *,
        project: str = "",
        dry_run: bool = False,
        min_generated_accepts: int = 3,
        sample_size: int = 12,
    ) -> dict[str, object]:
        self.initialize()
        min_accepts = max(1, int(min_generated_accepts))
        params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("e.project = ?")
            params.append(project)
        sql = f"""
            SELECT
                e.id, e.committed_text, e.recent_context, e.preedit, e.source,
                e.provider_name, e.tags_json, e.project, e.app, e.schema_id,
                s.deleted, s.accepted_count, s.skipped_count, s.downranked,
                s.pinned,
                COALESCE(ps.input_frequency, 0) AS input_frequency,
                COALESCE(pps.input_frequency, 0) AS project_input_frequency,
                COALESCE(pas.input_frequency, 0) AS app_input_frequency
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            LEFT JOIN phrase_project_stats pps
                ON pps.committed_text = e.committed_text AND pps.project = e.project
            LEFT JOIN phrase_app_stats pas
                ON pas.committed_text = e.committed_text AND pas.app = e.app
            WHERE {' AND '.join(where)}
            ORDER BY e.id
        """
        matched: dict[int, tuple[str, sqlite3.Row]] = {}
        reason_counts: dict[str, int] = {}
        samples: list[dict[str, object]] = []
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())
            for row in rows:
                reason = _rag_database_noise_reason(row, min_generated_accepts=min_accepts)
                if not reason:
                    continue
                event_id = int(row["id"])
                matched[event_id] = (reason, row)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if len(samples) < max(0, int(sample_size)):
                    samples.append(
                        {
                            "eventId": event_id,
                            "reason": reason,
                            "text": truncate_text(str(row["committed_text"]), 80),
                            "source": str(row["source"]),
                            "providerName": str(row["provider_name"]),
                            "tags": _row_tags(row),
                            "acceptedCount": int(row["accepted_count"]),
                            "inputFrequency": int(row["input_frequency"]),
                        }
                    )
            duplicate_plan = _rag_database_duplicate_plan(rows, sample_size=max(0, int(sample_size)))
            for item in duplicate_plan["hideCandidates"]:
                event_id = int(item["eventId"])
                row = item["row"]
                if event_id in matched:
                    continue
                reason = str(item["reason"])
                matched[event_id] = (reason, row)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if len(samples) < max(0, int(sample_size)):
                    samples.append(
                        {
                            "eventId": event_id,
                            "reason": reason,
                            "text": truncate_text(str(row["committed_text"]), 80),
                            "source": str(row["source"]),
                            "providerName": str(row["provider_name"]),
                            "tags": _row_tags(row),
                            "acceptedCount": int(row["accepted_count"]),
                            "inputFrequency": int(row["input_frequency"]),
                        }
                    )
            similar_plan = _rag_database_similar_duplicate_plan(
                rows,
                already_hidden_event_ids=set(matched),
                sample_size=max(0, int(sample_size)),
            )
            for item in similar_plan["hideCandidates"]:
                event_id = int(item["eventId"])
                row = item["row"]
                if event_id in matched:
                    continue
                reason = str(item["reason"])
                matched[event_id] = (reason, row)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                if len(samples) < max(0, int(sample_size)):
                    samples.append(
                        {
                            "eventId": event_id,
                            "reason": reason,
                            "text": truncate_text(str(row["committed_text"]), 80),
                            "source": str(row["source"]),
                            "providerName": str(row["provider_name"]),
                            "tags": _row_tags(row),
                            "acceptedCount": int(row["accepted_count"]),
                            "inputFrequency": int(row["input_frequency"]),
                        }
                    )
            hidden_vector_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM memory_vectors v
                    JOIN memory_state s ON s.event_id = v.event_id
                    WHERE s.deleted = 1
                    """
                ).fetchone()[0]
            )
            if (matched or hidden_vector_count) and not dry_run:
                updated_at = now_ms()
                event_ids = sorted(matched)
                if event_ids:
                    conn.executemany(
                        "UPDATE memory_state SET deleted = 1, updated_at_ms = ? WHERE event_id = ?",
                        [(updated_at, event_id) for event_id in event_ids],
                    )
                    action_rows = []
                    for event_id in event_ids:
                        reason, row = matched[event_id]
                        metadata_json = json.dumps(
                            {
                                "reason": reason,
                                "organizer": "rag-db-organize",
                                "minGeneratedAccepts": min_accepts,
                                "tags": _row_tags(row),
                                "providerName": str(row["provider_name"]),
                                "source": str(row["source"]),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        action_rows.append((updated_at, f"event:{event_id}", event_id, metadata_json))
                    conn.executemany(
                        """
                        INSERT INTO memory_actions (
                            created_at_ms, memory_id, event_id, action_type, query, suggestion_id, metadata_json
                        )
                        VALUES (?, ?, ?, 'hide', 'rag-db-organize', '', ?)
                        """,
                        action_rows,
                    )
                removed_hidden_vectors = int(
                    conn.execute(
                        """
                        DELETE FROM memory_vectors
                        WHERE event_id IN (
                            SELECT event_id FROM memory_state WHERE deleted = 1
                        )
                        """
                    ).rowcount
                    or 0
                )
                if event_ids:
                    self._rebuild_all_phrase_stats(conn)
            else:
                removed_hidden_vectors = 0
        if (matched or removed_hidden_vectors) and not dry_run:
            self._clear_suggestion_cache()
        return {
            "project": project,
            "dryRun": dry_run,
            "scanned": len(rows),
            "matchedNoise": len(matched),
            "hidden": 0 if dry_run else len(matched),
            "wouldHide": len(matched),
            "staleHiddenVectors": hidden_vector_count,
            "removedHiddenVectors": 0 if dry_run else removed_hidden_vectors,
            "minGeneratedAccepts": min_accepts,
            "reasonCounts": reason_counts,
            "duplicateGroups": duplicate_plan["groups"],
            "duplicateGroupCount": len(duplicate_plan["groups"]),
            "duplicateEventCount": duplicate_plan["duplicateEventCount"],
            "wouldHideDuplicates": duplicate_plan["wouldHideCount"],
            "similarGroups": similar_plan["groups"],
            "similarGroupCount": len(similar_plan["groups"]),
            "similarEventCount": similar_plan["similarEventCount"],
            "wouldHideSimilar": similar_plan["wouldHideCount"],
            "samples": samples,
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _embedding_enabled(self) -> bool:
        return self.embedding_provider.fingerprint != "none"

    def _upsert_event_vector(
        self,
        conn: sqlite3.Connection,
        *,
        event_id: int,
        document: str,
        updated_at_ms: int,
    ) -> bool:
        if not self._embedding_enabled():
            return False
        vector = self.embedding_provider.embed(document)
        if not vector:
            return False
        conn.execute(
            """
            INSERT INTO memory_vectors(event_id, provider_fingerprint, vector_json, updated_at_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                provider_fingerprint = excluded.provider_fingerprint,
                vector_json = excluded.vector_json,
                updated_at_ms = excluded.updated_at_ms
            """,
            (
                event_id,
                self.embedding_provider.fingerprint,
                json.dumps(vector, separators=(",", ":")),
                updated_at_ms,
            ),
        )
        return True

    def _suggestion_cache_key(
        self,
        *,
        current_input: str,
        recent_context: str,
        project: str,
        app: str,
        mode: str,
        top_k: int,
    ) -> tuple[str, str, str, str, str, str, int]:
        return (
            compact_whitespace(current_input),
            compact_whitespace(recent_context),
            compact_whitespace(project),
            compact_whitespace(app),
            compact_whitespace(mode),
            _pinyin_runtime_cache_fingerprint(),
            int(top_k),
        )

    def _get_cached_suggestions(self, key: tuple[str, str, str, str, str, str, int]) -> list[InputSuggestion] | None:
        if self.suggestion_cache_size <= 0:
            return None
        with self._suggestion_cache_lock:
            cached = self._suggestion_cache.get(key)
            if cached is None:
                self._suggestion_cache_misses += 1
                return None
            self._suggestion_cache.move_to_end(key)
            self._suggestion_cache_hits += 1
            return _copy_suggestions(cached)

    def _store_cached_suggestions(self, key: tuple[str, str, str, str, str, str, int], suggestions: list[InputSuggestion]) -> None:
        if self.suggestion_cache_size <= 0:
            return
        with self._suggestion_cache_lock:
            self._suggestion_cache[key] = tuple(_copy_suggestions(suggestions))
            self._suggestion_cache.move_to_end(key)
            while len(self._suggestion_cache) > self.suggestion_cache_size:
                self._suggestion_cache.popitem(last=False)
                self._suggestion_cache_evictions += 1

    def _clear_suggestion_cache(self) -> None:
        if self.suggestion_cache_size <= 0:
            return
        with self._suggestion_cache_lock:
            if self._suggestion_cache:
                self._suggestion_cache_invalidations += 1
            self._suggestion_cache.clear()

    def _memory_item_rows(
        self,
        conn: sqlite3.Connection,
        *,
        kind: str,
        project: str,
        app: str,
        limit: int,
        fts_query: str,
    ) -> list[sqlite3.Row]:
        params: list[Any] = []
        joins = ""
        where = ["mi.status IN ('active', 'approved')", "mi.privacy_class != 'sensitive'"]
        order = "mi.updated_at_ms DESC"
        if kind:
            where.append("mi.kind = ?")
            params.append(kind)
        if project:
            where.append("(mi.project = ? OR mi.project = '')")
            params.append(project)
        if app:
            where.append("(mi.app = ? OR mi.app = '')")
            params.append(app)
        if fts_query:
            joins = "JOIN memory_items_fts ON memory_items_fts.rowid = mi.id"
            where.insert(0, "memory_items_fts MATCH ?")
            params.insert(0, fts_query)
            order = "bm25(memory_items_fts) ASC, mi.updated_at_ms DESC"
        sql = f"""
            SELECT
                mi.*,
                {'bm25(memory_items_fts) AS bm25_score,' if fts_query else '0.0 AS bm25_score,'}
                COALESCE(ms.accepted_count, 0) AS accepted_count,
                COALESCE(ms.skipped_count, 0) AS skipped_count,
                COALESCE(tag_map.tags_joined, '') AS tags_joined
            FROM memory_items mi
            {joins}
            LEFT JOIN memory_state ms ON ms.event_id = mi.source_event_id
            LEFT JOIN (
                SELECT mit.memory_item_id, GROUP_CONCAT(mt.tag, ',') AS tags_joined
                FROM memory_item_tags mit
                JOIN memory_tags mt ON mt.id = mit.tag_id
                GROUP BY mit.memory_item_id
            ) tag_map ON tag_map.memory_item_id = mi.id
            WHERE {' AND '.join(where)}
            ORDER BY {order}
            LIMIT ?
        """
        params.append(max(1, limit))
        return list(conn.execute(sql, params).fetchall())

    def _memory_item_rows_by_ids(
        self,
        conn: sqlite3.Connection,
        *,
        memory_item_ids: list[int] | tuple[int, ...],
        project: str = "",
        app: str = "",
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        ids = [int(item) for item in memory_item_ids if int(item) > 0]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids[: max(1, limit)])
        params: list[Any] = list(ids[: max(1, limit)])
        where = [
            f"mi.id IN ({placeholders})",
            "mi.status IN ('active', 'approved')",
            "mi.privacy_class != 'sensitive'",
        ]
        if project:
            where.append("(mi.project = ? OR mi.project = '')")
            params.append(project)
        if app:
            where.append("(mi.app = ? OR mi.app = '')")
            params.append(app)
        sql = f"""
            SELECT
                mi.*,
                0.0 AS bm25_score,
                COALESCE(ms.accepted_count, 0) AS accepted_count,
                COALESCE(ms.skipped_count, 0) AS skipped_count,
                COALESCE(tag_map.tags_joined, '') AS tags_joined
            FROM memory_items mi
            LEFT JOIN memory_state ms ON ms.event_id = mi.source_event_id
            LEFT JOIN (
                SELECT mit.memory_item_id, GROUP_CONCAT(mt.tag, ',') AS tags_joined
                FROM memory_item_tags mit
                JOIN memory_tags mt ON mt.id = mit.tag_id
                GROUP BY mit.memory_item_id
            ) tag_map ON tag_map.memory_item_id = mi.id
            WHERE {' AND '.join(where)}
            ORDER BY mi.updated_at_ms DESC, mi.id DESC
            LIMIT ?
        """
        params.append(max(1, limit))
        return list(conn.execute(sql, params).fetchall())

    def _retrieve_memories_v2(self, context: ImeQueryContext) -> tuple[list[CoreMemory], dict[str, object]]:
        self.initialize()
        started_at = now_ms()
        query = compact_whitespace(" ".join(part for part in (context.current_input, context.recent_context, context.committed_context) if part))
        fts_query = build_fts_query(query)
        pool_counts = {"phrase": 0, "fts": 0, "vector": 0, "tag": 0}
        filtered = {"tombstone": 0, "suppressed": 0, "rawEcho": 0, "contextMismatch": 0, "duplicate": 0}
        candidates: list[MemoryCandidateV2] = []
        with self._connect() as conn:
            phrase_rows = self._memory_item_rows(
                conn,
                kind="phrase",
                project=context.project,
                app=context.app,
                limit=max(context.top_k * 3, 10),
                fts_query=fts_query,
            )
            pool_counts["phrase"] = len(phrase_rows)
            general_rows = self._memory_item_rows(
                conn,
                kind="",
                project=context.project,
                app=context.app,
                limit=max(context.top_k * 5, 18),
                fts_query=fts_query,
            )
            pool_counts["fts"] = len(general_rows)
            energy = propagate_tag_energy(conn, query_text=query, max_hops=2, max_neighbors=8)
            tag_scores = score_memory_items_from_tag_energy(conn, energy, limit=max(context.top_k * 4, 12))
            pool_counts["tag"] = len(tag_scores)
            vector_scores = self._memory_item_vector_scores(conn, query=query, project=context.project, app=context.app, limit=max(context.top_k * 4, 12))
            pool_counts["vector"] = len(vector_scores)
            tag_rows = self._memory_item_rows_by_ids(
                conn,
                memory_item_ids=tuple(tag_scores.keys()),
                project=context.project,
                app=context.app,
                limit=max(context.top_k * 4, 12),
            )
            for row in _merge_rows(phrase_rows, general_rows, tag_rows):
                memory_id = str(row["memory_id"])
                normalized_text = _optimizer_norm(str(row["normalized_text"] or row["text"] or ""))
                source_event_id = int(row["source_event_id"] or 0)
                if self.v2_governance_filter_enabled:
                    if self._memory_item_tombstoned(
                        conn,
                        memory_id=memory_id,
                        normalized_text=normalized_text,
                        source_event_id=source_event_id,
                    ):
                        filtered["tombstone"] += 1
                        continue
                    if self._memory_item_suppressed(
                        conn,
                        memory_id=memory_id,
                        normalized_text=normalized_text,
                        source_event_id=source_event_id,
                    ):
                        filtered["suppressed"] += 1
                        continue
                metadata = _json_loads_dict(row["metadata_json"])
                direct_allowed = bool(metadata.get("direct_candidate_allowed", False))
                kind = str(row["kind"])
                text = str(row["text"])
                if kind == "raw_event" and not context.allow_raw_event_candidates and not direct_allowed:
                    filtered["rawEcho"] += 1
                    continue
                if _candidate_repeats_current_input(text=text, current_input=context.current_input):
                    filtered["rawEcho"] += 1
                    continue
                lexical_score = float(row["bm25_score"])
                vector_score = vector_scores.get(int(row["id"]), 0.0)
                tag_energy = tag_scores.get(int(row["id"]), 0.0)
                accepted_count_state = int(row["accepted_count"] or 0)
                query_feedback_bonus = self._memory_item_feedback_bonus(conn, memory_id=memory_id, query=query)
                feedback_bonus = accepted_count_state * 0.6 + query_feedback_bonus
                tags = _split_tags_joined(str(row["tags_joined"] or ""))
                if not tags:
                    tags = ("memory",) if kind in {"phrase", "stable_memory"} else ("rag",)
                if feedback_bonus > 0 and _accepted_feedback_context_mismatch(context=context, row=row, tags=tags):
                    filtered["contextMismatch"] += 1
                    continue
                stale_penalty = 0.6 if kind == "raw_event" and len(text) > 12 else 0.0
                score = (
                    0.26 * lexical_score
                    + 0.24 * vector_score
                    + 0.16 * tag_energy
                    + 0.12 * _affinity_score(row=row, project=context.project, app=context.app)
                    + 0.10 * feedback_bonus
                    + 0.07 * _freshness_score(updated_at_ms=int(row["updated_at_ms"]))
                    + 0.05 * float(row["quality_score"])
                    - 0.35 * stale_penalty
                )
                candidates.append(
                    MemoryCandidateV2(
                        text=text,
                        source_type=_source_type_from_tags_v2(tags),
                        memory_kind=kind,
                        score=score,
                        memory_ids=(memory_id,),
                        evidence_preview=truncate_text(f"{text} | kind: {kind} | project: {row['project']} | app: {row['app']}", 180),
                        diagnostics={
                            "scoreBreakdown": {
                                "lexical": round(0.26 * lexical_score, 4),
                                "vector": round(0.24 * vector_score, 4),
                                "tagEnergy": round(0.16 * tag_energy, 4),
                                "feedback": round(feedback_bonus, 4),
                                "stalePenalty": round(-0.35 * stale_penalty, 4),
                                "acceptedCount": accepted_count_state,
                            },
                            "memoryKind": kind,
                        },
                        source_event_id=source_event_id or None,
                        normalized_text=normalized_text,
                        tags=tags,
                        reason=_build_v2_reason(
                            lexical_score=lexical_score,
                            vector_score=vector_score,
                            tag_energy=tag_energy,
                            feedback_bonus=feedback_bonus,
                            stale_penalty=stale_penalty,
                            tags=tags,
                        ),
                    )
                )
        selected = select_diverse(candidates, top_k=max(1, context.top_k))
        filtered["duplicate"] = max(0, len(candidates) - len(selected) - filtered["tombstone"] - filtered["rawEcho"])
        memories = [
            CoreMemory(
                memory_id=item.memory_ids[0],
                text=item.text,
                source_ref=f"memory_item:{item.memory_ids[0]}",
                score=item.score,
                reason=item.reason,
                evidence_preview=item.evidence_preview,
                project=context.project,
                tags=item.tags,
                source_event_id=str(item.source_event_id) if item.source_event_id is not None else None,
                created_at_ms=None,
                state={
                    "score_breakdown": _score_breakdown_payload_v2(item),
                    "memory_kind": item.memory_kind,
                },
            )
            for item in selected
        ]
        return memories, {
            "latencyMs": max(0, now_ms() - started_at),
            "pools": pool_counts,
            "filtered": filtered,
        }

    def _memory_item_vector_scores(
        self,
        conn: sqlite3.Connection,
        *,
        query: str,
        project: str,
        app: str,
        limit: int,
    ) -> dict[int, float]:
        if not self._embedding_enabled():
            return {}
        query_vector = self.embedding_provider.embed(query)
        if not query_vector:
            return {}
        params: list[Any] = [self.embedding_provider.fingerprint]
        where = ["v.provider_fingerprint = ?", "mi.status IN ('active', 'approved')", "mi.privacy_class != 'sensitive'"]
        if project:
            where.append("(mi.project = ? OR mi.project = '')")
            params.append(project)
        if app:
            where.append("(mi.app = ? OR mi.app = '')")
            params.append(app)
        rows = conn.execute(
            f"""
            SELECT mi.id, v.vector_json
            FROM memory_item_vectors v
            JOIN memory_items mi ON mi.id = v.memory_item_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()
        scores: list[tuple[int, float]] = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"] or "[]")
            except json.JSONDecodeError:
                continue
            score = cosine_similarity(query_vector, [float(value) for value in vector if isinstance(value, (int, float))])
            if score > 0:
                scores.append((int(row["id"]), score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return dict(scores[: max(1, limit)])

    def _memory_item_feedback_bonus(self, conn: sqlite3.Connection, *, memory_id: str, query: str) -> float:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN action = 'accepted' THEN 1 ELSE 0 END) AS accepted_count,
                SUM(CASE WHEN action IN ('skipped', 'skip', 'rejected') THEN 1 ELSE 0 END) AS negative_count
            FROM candidate_feedback
            WHERE memory_id = ? AND query_hash = ?
            """,
            (memory_id, _query_hash(query)),
        ).fetchone()
        accepted = int(row["accepted_count"] or 0) if row is not None else 0
        negative = int(row["negative_count"] or 0) if row is not None else 0
        return max(0.0, accepted * 0.5 - negative * 0.35)

    def _memory_item_tombstoned(self, conn: sqlite3.Connection, *, memory_id: str, normalized_text: str, source_event_id: int) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM memory_tombstones
            WHERE active = 1
              AND (
                    (target_type = 'memory_id' AND target_value = ?)
                 OR (target_type = 'normalized_text' AND target_value = ?)
                 OR (target_type = 'source_event_id' AND target_value = ?)
              )
            LIMIT 1
            """,
            (memory_id, normalized_text, str(source_event_id)),
        ).fetchone()
        return row is not None

    def _memory_item_suppressed(self, conn: sqlite3.Connection, *, memory_id: str, normalized_text: str, source_event_id: int) -> bool:
        clauses = [
            "(match_type = 'memory_id' AND match_value = ?)",
        ]
        params: list[Any] = [now_ms(), memory_id]
        normalized_value = _optimizer_norm(normalized_text)
        if normalized_value:
            clauses.append("(match_type IN ('text', 'normalized_text') AND match_value = ?)")
            params.append(normalized_value)
        if source_event_id > 0:
            clauses.append("(match_type = 'memory_id' AND match_value = ?)")
            params.append(f"event:{source_event_id}")
        row = conn.execute(
            f"""
            SELECT 1
            FROM memory_candidate_suppressions
            WHERE (expires_at_ms IS NULL OR expires_at_ms > ?)
              AND ({' OR '.join(clauses)})
            LIMIT 1
            """,
            params,
        ).fetchone()
        return row is not None

    def _record_feedback_v2(self, conn: sqlite3.Connection, *, feedback: CandidateFeedbackV2) -> None:
        for memory_id in feedback.memory_ids or ("",):
            conn.execute(
                """
                INSERT INTO candidate_feedback(
                    created_at_ms, query_hash, candidate_text, source_type, memory_id, action, app, project, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ms(),
                    feedback.query_hash,
                    feedback.candidate_text,
                    feedback.source_type,
                    memory_id,
                    feedback.action,
                    feedback.app,
                    feedback.project,
                    json.dumps(feedback.metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )

    def _sync_memory_item_status_for_action(self, conn: sqlite3.Connection, *, action: MemoryAction, event_id: int) -> None:
        if action.action_type in ("delete", "hide"):
            conn.execute(
                "UPDATE memory_items SET status = 'hidden', updated_at_ms = ? WHERE source_event_id = ? OR memory_id = ?",
                (now_ms(), event_id, action.memory_id),
            )
            conn.execute(
                """
                INSERT INTO memory_tombstones(created_at_ms, target_type, target_value, reason, active, metadata_json)
                VALUES (?, 'memory_id', ?, ?, 1, ?)
                """,
                (
                    now_ms(),
                    action.memory_id,
                    f"action:{action.action_type}",
                    json.dumps(action.metadata or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
        elif action.action_type == "restore":
            conn.execute(
                "UPDATE memory_items SET status = 'active', updated_at_ms = ? WHERE source_event_id = ? OR memory_id = ?",
                (now_ms(), event_id, action.memory_id),
            )
            conn.execute("UPDATE memory_tombstones SET active = 0 WHERE target_type = 'memory_id' AND target_value = ?", (action.memory_id,))
        elif action.action_type in ("accepted", "accept", "pin"):
            conn.execute(
                """
                UPDATE memory_items
                SET quality_score = MIN(1.0, quality_score + 0.08), updated_at_ms = ?
                WHERE source_event_id = ? OR memory_id = ?
                """,
                (now_ms(), event_id, action.memory_id),
            )
        elif action.action_type in ("skipped", "skip", "downrank"):
            conn.execute(
                """
                UPDATE memory_items
                SET quality_score = MAX(0.05, quality_score - 0.05), updated_at_ms = ?
                WHERE source_event_id = ? OR memory_id = ?
                """,
                (now_ms(), event_id, action.memory_id),
            )

    def _event_text(self, conn: sqlite3.Connection, event_id: int) -> str:
        row = conn.execute("SELECT committed_text FROM input_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return ""
        return str(row["committed_text"])

    def _apply_optimizer_feedback_governance(
        self,
        conn: sqlite3.Connection,
        *,
        action: str,
        candidate_id: str,
        candidate_text: str,
        candidate_source: str,
        context_hash: str,
        created_at_ms: int,
        metadata: dict[str, object],
    ) -> bool:
        changed = False
        effective_now_ms = max(created_at_ms, now_ms())
        memory_id = candidate_id
        normalized_text = _optimizer_norm(candidate_text)
        if memory_id and action in {"accepted", "accept", "active_rag_accept"}:
            conn.execute(
                """
                UPDATE memory_items
                SET updated_at_ms = ?, quality_score = MIN(1.0, quality_score + 0.02)
                WHERE memory_id = ?
                """,
                (effective_now_ms, memory_id),
            )
            changed = True
        if memory_id and action in {"deleted", "delete", "hide"}:
            self._upsert_candidate_suppression(
                conn,
                match_type="memory_id",
                match_value=memory_id,
                action="block",
                reason="feedback_delete",
                strength=1.0,
                created_at_ms=effective_now_ms,
            )
            changed = True
        if memory_id and action in {"downranked", "downrank"}:
            self._upsert_candidate_suppression(
                conn,
                match_type="memory_id",
                match_value=memory_id,
                action="cooldown",
                reason="feedback_downrank",
                strength=0.8,
                created_at_ms=effective_now_ms,
                expires_at_ms=effective_now_ms + 7 * 24 * 60 * 60 * 1000,
            )
            changed = True
        if memory_id and action in {
            "backspace_after_accept",
            "backspace_after_active_rag_accept",
            "edited_after_accept",
            "active_rag_edited_after_accept",
            "ignored_repeatedly",
            "session_invalidated",
        }:
            self._upsert_candidate_suppression(
                conn,
                match_type="memory_id",
                match_value=memory_id,
                action="cooldown",
                reason=action,
                strength=0.75,
                created_at_ms=effective_now_ms,
                expires_at_ms=effective_now_ms + 24 * 60 * 60 * 1000,
            )
            changed = True
        if memory_id and action in {"skipped", "skip", "active_rag_skip"}:
            cooldown_scope = context_hash or _optimizer_feedback_scope(metadata)
            params: list[Any] = [memory_id, max(0, created_at_ms - 7 * 24 * 60 * 60 * 1000)]
            where = ["candidate_id = ?", "action IN ('skipped', 'skip')", "created_at_ms >= ?"]
            if cooldown_scope:
                where.append("COALESCE(context_hash, '') = ?")
                params.append(cooldown_scope)
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS skipped_count
                FROM memory_feedback_events
                WHERE {' AND '.join(where)}
                """,
                params,
            ).fetchone()
            skipped_count = int(count_row["skipped_count"] or 0) if count_row is not None else 0
            if skipped_count >= 2:
                self._upsert_candidate_suppression(
                    conn,
                    match_type="memory_id",
                    match_value=memory_id,
                    action="cooldown",
                    reason="repeated_skip",
                    strength=min(1.0, 0.4 + 0.1 * skipped_count),
                    created_at_ms=effective_now_ms,
                    expires_at_ms=effective_now_ms + 6 * 60 * 60 * 1000,
                )
                changed = True
                if normalized_text:
                    self._upsert_candidate_suppression(
                        conn,
                        match_type="normalized_text",
                        match_value=normalized_text,
                        action="cooldown",
                        reason="repeated_skip_text",
                        strength=min(1.0, 0.35 + 0.08 * skipped_count),
                        created_at_ms=effective_now_ms,
                        expires_at_ms=effective_now_ms + 6 * 60 * 60 * 1000,
                    )
        if normalized_text and candidate_source in {"rag", "memory"} and action in {"deleted", "delete", "hide"}:
            self._upsert_candidate_suppression(
                conn,
                match_type="normalized_text",
                match_value=normalized_text,
                action="block",
                reason="feedback_delete_text",
                strength=1.0,
                created_at_ms=effective_now_ms,
            )
            changed = True
        return changed

    def _upsert_candidate_suppression(
        self,
        conn: sqlite3.Connection,
        *,
        match_type: str,
        match_value: str,
        action: str,
        reason: str,
        strength: float,
        created_at_ms: int,
        expires_at_ms: int | None = None,
    ) -> None:
        normalized_match_value = compact_whitespace(match_value)
        if not normalized_match_value:
            return
        row = conn.execute(
            """
            SELECT id
            FROM memory_candidate_suppressions
            WHERE match_type = ? AND match_value = ?
            ORDER BY created_at_ms DESC
            LIMIT 1
            """,
            (match_type, normalized_match_value),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO memory_candidate_suppressions(
                    id, match_type, match_value, action, reason, strength, expires_at_ms, created_at_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _candidate_suppression_id(match_type=match_type, match_value=normalized_match_value),
                    match_type,
                    normalized_match_value,
                    action,
                    reason,
                    max(0.0, min(1.0, strength)),
                    expires_at_ms,
                    created_at_ms,
                ),
            )
            return
        conn.execute(
            """
            UPDATE memory_candidate_suppressions
            SET action = ?, reason = ?, strength = ?, expires_at_ms = ?, created_at_ms = ?
            WHERE id = ?
            """,
            (
                action,
                reason,
                max(0.0, min(1.0, strength)),
                expires_at_ms,
                created_at_ms,
                str(row["id"]),
            ),
        )

    def _search_rows(self, *, fts_query: str, project: str, app: str, limit: int) -> list[sqlite3.Row]:
        where_params: list[Any] = [fts_query]
        where = ["memory_fts MATCH ?", "s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            where_params.append(project)
        sql = f"""
            SELECT
                e.*, s.*, bm25(memory_fts) AS bm25_score,
                COALESCE(ps.input_frequency, 1) AS input_frequency,
                COALESCE(ps.first_seen_ms, e.created_at_ms) AS phrase_first_seen_ms,
                COALESCE(ps.last_seen_ms, e.created_at_ms) AS phrase_last_seen_ms,
                COALESCE(pps.input_frequency, 0) AS project_input_frequency,
                COALESCE(pps.first_seen_ms, e.created_at_ms) AS project_phrase_first_seen_ms,
                COALESCE(pps.last_seen_ms, e.created_at_ms) AS project_phrase_last_seen_ms,
                COALESCE(pas.input_frequency, 0) AS app_input_frequency,
                COALESCE(pas.first_seen_ms, e.created_at_ms) AS app_phrase_first_seen_ms,
                COALESCE(pas.last_seen_ms, e.created_at_ms) AS app_phrase_last_seen_ms,
{_PHRASE_FEEDBACK_SELECT_COLUMNS}
            FROM memory_fts
            JOIN input_events e ON e.id = memory_fts.rowid
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            LEFT JOIN phrase_project_stats pps ON pps.committed_text = e.committed_text AND pps.project = ?
            LEFT JOIN phrase_app_stats pas ON pas.committed_text = e.committed_text AND pas.app = ?
{_PHRASE_FEEDBACK_JOIN}
            WHERE {' AND '.join(where)}
            ORDER BY s.pinned DESC, bm25(memory_fts) ASC, e.created_at_ms DESC
            LIMIT ?
        """
        params = [project, app, *where_params, limit]
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def _vector_rows(self, *, query: str, project: str, app: str, limit: int) -> tuple[list[sqlite3.Row], dict[int, float]]:
        if not self._embedding_enabled() or self.vector_candidate_limit <= 0 or self.vector_weight <= 0:
            return [], {}
        query_vector = self.embedding_provider.embed(query)
        if not query_vector:
            return [], {}
        where_params: list[Any] = [self.embedding_provider.fingerprint]
        where = ["v.provider_fingerprint = ?", "s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            where_params.append(project)
        sql = f"""
            SELECT
                e.*, s.*, 99.0 AS bm25_score,
                COALESCE(ps.input_frequency, 1) AS input_frequency,
                COALESCE(ps.first_seen_ms, e.created_at_ms) AS phrase_first_seen_ms,
                COALESCE(ps.last_seen_ms, e.created_at_ms) AS phrase_last_seen_ms,
                COALESCE(pps.input_frequency, 0) AS project_input_frequency,
                COALESCE(pps.first_seen_ms, e.created_at_ms) AS project_phrase_first_seen_ms,
                COALESCE(pps.last_seen_ms, e.created_at_ms) AS project_phrase_last_seen_ms,
                COALESCE(pas.input_frequency, 0) AS app_input_frequency,
                COALESCE(pas.first_seen_ms, e.created_at_ms) AS app_phrase_first_seen_ms,
                COALESCE(pas.last_seen_ms, e.created_at_ms) AS app_phrase_last_seen_ms,
{_PHRASE_FEEDBACK_SELECT_COLUMNS},
                v.vector_json
            FROM memory_vectors v
            JOIN input_events e ON e.id = v.event_id
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            LEFT JOIN phrase_project_stats pps ON pps.committed_text = e.committed_text AND pps.project = ?
            LEFT JOIN phrase_app_stats pas ON pas.committed_text = e.committed_text AND pas.app = ?
{_PHRASE_FEEDBACK_JOIN}
            WHERE {' AND '.join(where)}
        """
        params = [project, app, *where_params]
        candidates: list[tuple[float, sqlite3.Row]] = []
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())
        for row in rows:
            try:
                vector = json.loads(row["vector_json"] or "[]")
            except json.JSONDecodeError:
                continue
            if not isinstance(vector, list):
                continue
            score = cosine_similarity(query_vector, [float(value) for value in vector if isinstance(value, (int, float))])
            if score <= 0:
                continue
            candidates.append((score, row))
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[: max(1, limit)]
        return [row for _, row in selected], {int(row["id"]): score for score, row in selected}

    def _recent_rows(self, *, project: str, app: str, limit: int) -> list[sqlite3.Row]:
        where_params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            where_params.append(project)
        sql = f"""
            SELECT
                e.*, s.*, 99.0 AS bm25_score,
                COALESCE(ps.input_frequency, 1) AS input_frequency,
                COALESCE(ps.first_seen_ms, e.created_at_ms) AS phrase_first_seen_ms,
                COALESCE(ps.last_seen_ms, e.created_at_ms) AS phrase_last_seen_ms,
                COALESCE(pps.input_frequency, 0) AS project_input_frequency,
                COALESCE(pps.first_seen_ms, e.created_at_ms) AS project_phrase_first_seen_ms,
                COALESCE(pps.last_seen_ms, e.created_at_ms) AS project_phrase_last_seen_ms,
                COALESCE(pas.input_frequency, 0) AS app_input_frequency,
                COALESCE(pas.first_seen_ms, e.created_at_ms) AS app_phrase_first_seen_ms,
                COALESCE(pas.last_seen_ms, e.created_at_ms) AS app_phrase_last_seen_ms,
{_PHRASE_FEEDBACK_SELECT_COLUMNS}
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            LEFT JOIN phrase_stats ps ON ps.committed_text = e.committed_text
            LEFT JOIN phrase_project_stats pps ON pps.committed_text = e.committed_text AND pps.project = ?
            LEFT JOIN phrase_app_stats pas ON pas.committed_text = e.committed_text AND pas.app = ?
{_PHRASE_FEEDBACK_JOIN}
            WHERE {' AND '.join(where)}
            ORDER BY s.pinned DESC, e.created_at_ms DESC
            LIMIT ?
        """
        params = [project, app, *where_params, limit]
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def _append_recent_fill(self, rows: list[sqlite3.Row], *, project: str, app: str, limit: int) -> list[sqlite3.Row]:
        seen = {int(row["id"]) for row in rows}
        filled = list(rows)
        for row in self._recent_rows(project=project, app=app, limit=max(limit * 2, 10)):
            if int(row["id"]) in seen:
                continue
            filled.append(row)
            seen.add(int(row["id"]))
            if len(filled) >= limit:
                break
        return filled

    def _row_to_memory(
        self,
        row: sqlite3.Row,
        *,
        query: str,
        project: str,
        app: str,
        raw_query: str = "",
        vector_score: float = 0.0,
        present_ms: int | None = None,
    ) -> CoreMemory:
        present_ms = present_ms or now_ms()
        event_id = int(row["id"])
        bm25 = float(row["bm25_score"] if row["bm25_score"] is not None else 99.0)
        lexical = _bm25_relevance(bm25)
        tags = tuple(json.loads(row["tags_json"] or "[]"))
        tags_text = " ".join(tags)
        committed_text = str(row["committed_text"])
        recent_context = str(row["recent_context"])
        source_fields = f"{row['source']} {row['app']} {row['schema_id']} {row['provider_name']}"
        overlap = overlap_terms(query, f"{committed_text} {recent_context} {tags_text}")
        overlap_score = min(1.5, len(overlap) * 0.3)
        field_boosts = _field_rerank_boosts(
            query=query,
            raw_query=raw_query,
            committed_text=committed_text,
            recent_context=recent_context,
            tags_text=tags_text,
            source_fields=source_fields,
        )
        pinyin_boost = _pinyin_rerank_boost(raw_query, committed_text, recent_context)
        input_frequency = _row_int(row, "input_frequency", default=1)
        phrase_first_seen_ms = _row_int(row, "phrase_first_seen_ms", default=int(row["created_at_ms"]))
        phrase_last_seen_ms = _row_int(row, "phrase_last_seen_ms", default=int(row["created_at_ms"]))
        project_input_frequency = _row_int(row, "project_input_frequency", default=0)
        project_phrase_first_seen_ms = _row_int(row, "project_phrase_first_seen_ms", default=int(row["created_at_ms"]))
        project_phrase_last_seen_ms = _row_int(row, "project_phrase_last_seen_ms", default=int(row["created_at_ms"]))
        app_input_frequency = _row_int(row, "app_input_frequency", default=0)
        app_phrase_first_seen_ms = _row_int(row, "app_phrase_first_seen_ms", default=int(row["created_at_ms"]))
        app_phrase_last_seen_ms = _row_int(row, "app_phrase_last_seen_ms", default=int(row["created_at_ms"]))
        event_project = str(row["project"])
        event_app = str(row["app"])
        use_project_frequency = bool(project and project_input_frequency > 0)
        use_app_frequency = bool(not use_project_frequency and app and app_input_frequency > 0)
        if use_project_frequency:
            effective_frequency = project_input_frequency
            effective_first_seen_ms = project_phrase_first_seen_ms
            effective_last_seen_ms = project_phrase_last_seen_ms
            frequency_scope = "project"
        elif use_app_frequency:
            effective_frequency = app_input_frequency
            effective_first_seen_ms = app_phrase_first_seen_ms
            effective_last_seen_ms = app_phrase_last_seen_ms
            frequency_scope = "app"
        else:
            effective_frequency = input_frequency
            effective_first_seen_ms = phrase_first_seen_ms
            effective_last_seen_ms = phrase_last_seen_ms
            frequency_scope = "global"
        frequency_boost = _input_frequency_boost(effective_frequency, effective_last_seen_ms, present_ms=present_ms)
        recent_boost = _last_seen_recency_boost(effective_last_seen_ms, present_ms=present_ms)
        age_days = _age_days(effective_last_seen_ms, present_ms)
        event_accepted = int(row["accepted_count"])
        event_skipped = int(row["skipped_count"])
        event_downranked = int(row["downranked"])
        accepted = _row_int(row, "phrase_accepted_count", default=event_accepted)
        skipped = _row_int(row, "phrase_skipped_count", default=event_skipped)
        downranked = _row_int(row, "phrase_downranked_count", default=event_downranked)
        pinned = bool(row["pinned"])
        project_boost = 0.4 if project and row["project"] == project else 0.0
        runtime_penalty = _runtime_trace_penalty(committed_text)
        tag_boost = _tag_quality_boost(tags)
        field_boost_total = sum(boost for _, boost in field_boosts)
        vector_boost = max(0.0, vector_score) * self.vector_weight
        pinned_boost = 8.0 if pinned else 0.0
        accepted_boost = accepted * 0.6
        skipped_penalty = skipped * 0.3
        downrank_penalty = downranked * 0.85
        score = (
            lexical
            + overlap_score
            + field_boost_total
            + pinyin_boost
            + frequency_boost
            + recent_boost
            + vector_boost
            + project_boost
            + tag_boost
            + pinned_boost
            + accepted_boost
            - skipped_penalty
            - downrank_penalty
            - runtime_penalty
        )
        score_breakdown = _score_breakdown_payload(
            query=query,
            raw_query=raw_query,
            total=score,
            lexical=lexical,
            overlap_score=overlap_score,
            field_boosts=field_boosts,
            pinyin_boost=pinyin_boost,
            frequency_boost=frequency_boost,
            recent_boost=recent_boost,
            vector_score=vector_score,
            vector_weight=self.vector_weight,
            vector_boost=vector_boost,
            project_boost=project_boost,
            tag_boost=tag_boost,
            pinned_boost=pinned_boost,
            accepted_boost=accepted_boost,
            skipped_penalty=skipped_penalty,
            downrank_penalty=downrank_penalty,
            runtime_penalty=runtime_penalty,
            input_frequency=input_frequency,
            project_input_frequency=project_input_frequency,
            app_input_frequency=app_input_frequency,
            effective_frequency=effective_frequency,
            frequency_scope=frequency_scope,
            accepted=accepted,
            skipped=skipped,
            downranked=downranked,
            pinned=pinned,
        )
        reason = [f"fts5:{lexical:.3f}"]
        if overlap:
            reason.append("overlap:" + ",".join(overlap[:4]))
        if vector_score > 0:
            reason.append(f"vector:{vector_score:.3f}")
        if tag_boost:
            reason.append(f"tag:{tag_boost:.2f}")
        for label, boost in field_boosts:
            if boost > 0:
                reason.append(f"{label}:{boost:.2f}")
        if pinyin_boost:
            reason.append(f"pinyin:{pinyin_boost:.2f}")
        if use_project_frequency:
            if project_input_frequency > 1:
                reason.append(f"project-frequency:{project_input_frequency}")
        elif use_app_frequency:
            if app_input_frequency > 1:
                reason.append(f"app-frequency:{app_input_frequency}")
        elif input_frequency > 1:
            reason.append(f"frequency:{input_frequency}")
        if recent_boost:
            reason.append(f"recent:{recent_boost:.2f}")
        if pinned:
            reason.append("pinned")
        if accepted:
            reason.append(f"accepted:{accepted}")
        if downranked:
            reason.append(f"downranked:{downranked}")
        if runtime_penalty:
            reason.append(f"runtime-trace:-{runtime_penalty:.2f}")
        evidence = truncate_text(
            f"{row['committed_text']} | context: {row['recent_context']} | source: {row['source']}",
            260,
        )
        return CoreMemory(
            memory_id=f"event:{event_id}",
            source_event_id=str(event_id),
            text=str(row["committed_text"]),
            source_ref=f"input_event:{event_id}",
            score=score,
            reason=";".join(reason),
            evidence_preview=evidence,
            project=event_project,
            tags=tags,
            created_at_ms=int(row["created_at_ms"]),
            state={
                "accepted_count": accepted,
                "skipped_count": skipped,
                "event_accepted_count": event_accepted,
                "event_skipped_count": event_skipped,
                "pinned": pinned,
                "downranked": downranked,
                "event_downranked": event_downranked,
                "deleted": bool(row["deleted"]),
                "input_frequency": input_frequency,
                "project_input_frequency": project_input_frequency,
                "app_input_frequency": app_input_frequency,
                "effective_frequency": effective_frequency,
                "effective_frequency_scope": frequency_scope,
                "phrase_first_seen_ms": phrase_first_seen_ms,
                "phrase_last_seen_ms": phrase_last_seen_ms,
                "project_phrase_first_seen_ms": project_phrase_first_seen_ms,
                "project_phrase_last_seen_ms": project_phrase_last_seen_ms,
                "app_phrase_first_seen_ms": app_phrase_first_seen_ms,
                "app_phrase_last_seen_ms": app_phrase_last_seen_ms,
                "effective_phrase_first_seen_ms": effective_first_seen_ms,
                "effective_phrase_last_seen_ms": effective_last_seen_ms,
                "phrase_age_days": round(age_days, 2),
                "frequency_boost": round(frequency_boost, 3),
                "recent_boost": round(recent_boost, 3),
                "score_breakdown": score_breakdown,
            },
        )

    @staticmethod
    def _memory_id_to_event_id(memory_id: str) -> int:
        if memory_id.startswith("event:"):
            return int(memory_id.split(":", 1)[1])
        if memory_id.startswith("sug-event:"):
            return int(memory_id.removeprefix("sug-event:"))
        return int(memory_id)

    @staticmethod
    def _apply_state_update(conn: sqlite3.Connection, event_id: int, action_type: str, updated_at: int) -> None:
        if action_type in ("accepted", "accept"):
            conn.execute(
                "UPDATE memory_state SET accepted_count = accepted_count + 1, updated_at_ms = ? WHERE event_id = ?",
                (updated_at, event_id),
            )
        elif action_type in ("skipped", "skip"):
            conn.execute(
                "UPDATE memory_state SET skipped_count = skipped_count + 1, updated_at_ms = ? WHERE event_id = ?",
                (updated_at, event_id),
            )
        elif action_type == "pin":
            conn.execute("UPDATE memory_state SET pinned = 1, updated_at_ms = ? WHERE event_id = ?", (updated_at, event_id))
        elif action_type == "unpin":
            conn.execute("UPDATE memory_state SET pinned = 0, updated_at_ms = ? WHERE event_id = ?", (updated_at, event_id))
        elif action_type == "downrank":
            conn.execute(
                "UPDATE memory_state SET downranked = downranked + 1, updated_at_ms = ? WHERE event_id = ?",
                (updated_at, event_id),
            )
        elif action_type in ("delete", "hide"):
            conn.execute("UPDATE memory_state SET deleted = 1, updated_at_ms = ? WHERE event_id = ?", (updated_at, event_id))
        elif action_type == "restore":
            conn.execute("UPDATE memory_state SET deleted = 0, updated_at_ms = ? WHERE event_id = ?", (updated_at, event_id))
        else:
            raise ValueError(f"unsupported action_type: {action_type}")

    @staticmethod
    def _refresh_phrase_stats_for_event(conn: sqlite3.Connection, event_id: int) -> None:
        row = conn.execute("SELECT committed_text FROM input_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return
        committed_text = str(row["committed_text"])
        stats = conn.execute(
            """
            SELECT COUNT(*) AS input_frequency, MIN(e.created_at_ms) AS first_seen_ms, MAX(e.created_at_ms) AS last_seen_ms
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE e.committed_text = ? AND s.deleted = 0
            """,
            (committed_text,),
        ).fetchone()
        input_frequency = int(stats["input_frequency"] or 0) if stats else 0
        if input_frequency <= 0:
            conn.execute("DELETE FROM phrase_stats WHERE committed_text = ?", (committed_text,))
            return
        conn.execute(
            """
            INSERT INTO phrase_stats(committed_text, input_frequency, first_seen_ms, last_seen_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(committed_text) DO UPDATE SET
                input_frequency = excluded.input_frequency,
                first_seen_ms = excluded.first_seen_ms,
                last_seen_ms = excluded.last_seen_ms
            """,
            (committed_text, input_frequency, int(stats["first_seen_ms"]), int(stats["last_seen_ms"])),
        )

    @staticmethod
    def _refresh_phrase_project_stats_for_event(conn: sqlite3.Connection, event_id: int) -> None:
        row = conn.execute("SELECT committed_text, project FROM input_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return
        committed_text = str(row["committed_text"])
        project = str(row["project"])
        if not project:
            return
        stats = conn.execute(
            """
            SELECT COUNT(*) AS input_frequency, MIN(e.created_at_ms) AS first_seen_ms, MAX(e.created_at_ms) AS last_seen_ms
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE e.committed_text = ? AND e.project = ? AND s.deleted = 0
            """,
            (committed_text, project),
        ).fetchone()
        input_frequency = int(stats["input_frequency"] or 0) if stats else 0
        if input_frequency <= 0:
            conn.execute("DELETE FROM phrase_project_stats WHERE committed_text = ? AND project = ?", (committed_text, project))
            return
        conn.execute(
            """
            INSERT INTO phrase_project_stats(committed_text, project, input_frequency, first_seen_ms, last_seen_ms)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(committed_text, project) DO UPDATE SET
                input_frequency = excluded.input_frequency,
                first_seen_ms = excluded.first_seen_ms,
                last_seen_ms = excluded.last_seen_ms
            """,
            (committed_text, project, input_frequency, int(stats["first_seen_ms"]), int(stats["last_seen_ms"])),
        )

    @staticmethod
    def _refresh_phrase_app_stats_for_event(conn: sqlite3.Connection, event_id: int) -> None:
        row = conn.execute("SELECT committed_text, app FROM input_events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return
        committed_text = str(row["committed_text"])
        app = str(row["app"])
        if not app:
            return
        stats = conn.execute(
            """
            SELECT COUNT(*) AS input_frequency, MIN(e.created_at_ms) AS first_seen_ms, MAX(e.created_at_ms) AS last_seen_ms
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE e.committed_text = ? AND e.app = ? AND s.deleted = 0
            """,
            (committed_text, app),
        ).fetchone()
        input_frequency = int(stats["input_frequency"] or 0) if stats else 0
        if input_frequency <= 0:
            conn.execute("DELETE FROM phrase_app_stats WHERE committed_text = ? AND app = ?", (committed_text, app))
            return
        conn.execute(
            """
            INSERT INTO phrase_app_stats(committed_text, app, input_frequency, first_seen_ms, last_seen_ms)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(committed_text, app) DO UPDATE SET
                input_frequency = excluded.input_frequency,
                first_seen_ms = excluded.first_seen_ms,
                last_seen_ms = excluded.last_seen_ms
            """,
            (committed_text, app, input_frequency, int(stats["first_seen_ms"]), int(stats["last_seen_ms"])),
        )

    @staticmethod
    def _rebuild_all_phrase_stats(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM phrase_stats")
        conn.execute("DELETE FROM phrase_project_stats")
        conn.execute("DELETE FROM phrase_app_stats")
        conn.execute(
            """
            INSERT INTO phrase_stats(committed_text, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0
            GROUP BY e.committed_text
            """
        )
        conn.execute(
            """
            INSERT INTO phrase_project_stats(committed_text, project, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, e.project, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0 AND e.project != ''
            GROUP BY e.committed_text, e.project
            """
        )
        conn.execute(
            """
            INSERT INTO phrase_app_stats(committed_text, app, input_frequency, first_seen_ms, last_seen_ms)
            SELECT e.committed_text, e.app, COUNT(*), MIN(e.created_at_ms), MAX(e.created_at_ms)
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE s.deleted = 0 AND e.app != ''
            GROUP BY e.committed_text, e.app
            """
        )


def _candidate_repeats_current_input(*, text: str, current_input: str) -> bool:
    normalized_text = compact_whitespace(text)
    normalized_input = compact_whitespace(current_input)
    if not normalized_text or not normalized_input:
        return False
    return normalized_text == normalized_input or normalized_text.endswith(normalized_input) or normalized_input.endswith(normalized_text)


def _affinity_score(*, row: sqlite3.Row, project: str, app: str) -> float:
    score = 0.0
    if project and str(row["project"]) == project:
        score += 1.0
    if app and str(row["app"]) == app:
        score += 0.6
    return score


def _accepted_feedback_context_mismatch(*, context: ImeQueryContext, row: sqlite3.Row, tags: tuple[str, ...]) -> bool:
    current_context = compact_whitespace(" ".join(part for part in (context.recent_context, context.committed_context) if part))
    if not current_context:
        return False
    source_context = compact_whitespace(
        " ".join(
            part
            for part in (
                str(row["summary"] or ""),
                str(row["text"] or ""),
                " ".join(tags),
            )
            if part
        )
    )
    if not source_context:
        return True
    return not bool(overlap_terms(current_context, source_context))


def _freshness_score(*, updated_at_ms: int) -> float:
    age_ms = max(0, now_ms() - updated_at_ms)
    if age_ms <= _MS_PER_DAY:
        return 1.0
    if age_ms <= 7 * _MS_PER_DAY:
        return 0.55
    if age_ms <= 30 * _MS_PER_DAY:
        return 0.2
    return 0.0


def _json_loads_dict(raw: object) -> dict[str, object]:
    try:
        loaded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _query_hash(query: str) -> str:
    return stable_text_hash(query)


def _memory_feedback_event_id(*, action: str, candidate_id: str, candidate_text: str, created_at_ms: int) -> str:
    seed = f"{action}:{candidate_id}:{candidate_text}:{created_at_ms}"
    return f"feedback:{created_at_ms}:{stable_text_hash(seed)[:12]}"


def _candidate_suppression_id(*, match_type: str, match_value: str) -> str:
    return f"suppression:{stable_text_hash(f'{match_type}:{match_value}')[:16]}"


def _optimizer_feedback_scope(metadata: dict[str, object]) -> str:
    candidates = metadata.get("shownCandidateIds")
    if isinstance(candidates, list):
        normalized = [compact_whitespace(str(item)) for item in candidates if compact_whitespace(str(item))]
        if normalized:
            return stable_text_hash("|".join(normalized))
    selected_id = compact_whitespace(str(metadata.get("selectedCandidateId") or ""))
    selected_text = compact_whitespace(str(metadata.get("selectedText") or ""))
    if selected_id or selected_text:
        return stable_text_hash(f"{selected_id}|{selected_text}")
    return ""


def _optimizer_norm(text: str) -> str:
    return compact_whitespace(text).lower()


def _json_loads_list(raw: object) -> list[object]:
    try:
        loaded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _memory_item_explanation_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "memoryId": str(row["memory_id"]),
        "kind": str(row["kind"]),
        "text": str(row["text"]),
        "normalizedText": str(row["normalized_text"]),
        "sourceEventId": int(row["source_event_id"] or 0) or None,
        "project": str(row["project"]),
        "app": str(row["app"]),
        "confidence": float(row["confidence"]),
        "qualityScore": float(row["quality_score"]),
        "status": str(row["status"]),
        "privacyClass": str(row["privacy_class"]),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "metadata": _json_loads_dict(row["metadata_json"]),
    }


def _memory_feedback_row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "candidateId": str(row["candidate_id"] or ""),
        "candidateText": str(row["candidate_text"]),
        "candidateSource": str(row["candidate_source"]),
        "action": str(row["action"]),
        "contextHash": str(row["context_hash"] or ""),
        "frontAppBundleId": str(row["front_app_bundle_id"] or ""),
        "rawInput": str(row["raw_input"] or ""),
        "preedit": str(row["preedit"] or ""),
        "committedTail": str(row["committed_tail"] or ""),
        "metadata": _json_loads_dict(row["metadata_json"]),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _optimizer_trace_row_payload(row: sqlite3.Row) -> dict[str, object]:
    query_plan = _json_loads_dict(row["query_plan_json"])
    return {
        "traceId": str(row["id"]),
        "requestSeq": int(row["request_seq"]),
        "contextHash": str(row["context_hash"]),
        "contextFrame": query_plan.get("contextFrame", {}) if isinstance(query_plan.get("contextFrame"), dict) else {},
        "queryPlan": query_plan.get("queryPlan", {}) if isinstance(query_plan.get("queryPlan"), dict) else {},
        "warnings": list(query_plan.get("warnings") or []),
        "degraded": bool(query_plan.get("degraded")),
        "rawResults": _json_loads_list(row["raw_results_json"]),
        "optimizedCandidates": _json_loads_list(row["optimized_candidates_json"]),
        "blocked": _json_loads_list(row["blocked_json"]),
        "latencyMs": float(row["latency_ms"]),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _memory_suppression_row_payload(row: sqlite3.Row) -> dict[str, object]:
    expires_at_ms = int(row["expires_at_ms"] or 0) or None
    now = now_ms()
    return {
        "id": str(row["id"]),
        "matchType": str(row["match_type"]),
        "matchValue": str(row["match_value"]),
        "action": str(row["action"]),
        "reason": str(row["reason"]),
        "strength": float(row["strength"]),
        "expiresAtMs": expires_at_ms,
        "createdAtMs": int(row["created_at_ms"]),
        "active": expires_at_ms is None or expires_at_ms > now,
    }


def _memory_tombstone_row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "createdAtMs": int(row["created_at_ms"]),
        "targetType": str(row["target_type"]),
        "targetValue": str(row["target_value"]),
        "reason": str(row["reason"]),
        "active": bool(row["active"]),
        "metadata": _json_loads_dict(row["metadata_json"]),
    }


def _split_tags_joined(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(tag for tag in (compact_whitespace(part) for part in raw.split(",")) if tag)


def _source_type_from_tags_v2(tags: tuple[str, ...]) -> str:
    tag_set = {tag.lower() for tag in tags}
    if tag_set.intersection({"cold_knowledge", "cold-knowledge", "external-knowledge"}):
        return "cold_knowledge"
    if tag_set.intersection({"memory", "frequency", "phrase-memory", "user-input", "curated"}):
        return "memory"
    return "rag"


def _build_v2_reason(
    *,
    lexical_score: float,
    vector_score: float,
    tag_energy: float,
    feedback_bonus: float,
    stale_penalty: float,
    tags: tuple[str, ...],
) -> str:
    reason = [f"fts5:{round(0.26 * lexical_score, 3)}"]
    if vector_score > 0:
        reason.append(f"vector:{round(vector_score, 3)}")
    if tag_energy > 0:
        reason.append(f"tag:{round(tag_energy, 3)}")
    if feedback_bonus > 0:
        reason.append(f"accepted:{max(1, round(feedback_bonus / 0.6))}")
    if stale_penalty > 0:
        reason.append(f"stale:-{round(stale_penalty, 3)}")
    if tags:
        reason.append("raw:" + ",".join(tag.lower() for tag in tags[:3]))
    return ";".join(reason)


def _score_breakdown_payload_v2(candidate: MemoryCandidateV2) -> dict[str, object]:
    components = dict(candidate.diagnostics.get("scoreBreakdown") or {})
    return {
        "schemaVersion": "rag-ime.score-breakdown.v1",
        "components": {
            "fts5": components.get("lexical", 0.0),
            "vector": components.get("vector", 0.0),
            "tag": components.get("tagEnergy", 0.0),
            "accepted": components.get("feedback", 0.0),
            "stalePenalty": components.get("stalePenalty", 0.0),
        },
        "rawSignals": {
            "acceptedCount": int(components.get("acceptedCount", 0) or 0),
            "memoryKind": candidate.memory_kind,
            "sourceType": candidate.source_type,
        },
        "weights": {
            "lexical": 0.26,
            "vector": 0.24,
            "tag": 0.16,
            "accepted": 0.6,
            "stalePenalty": -0.35,
        },
        "query": "",
        "total": round(candidate.score, 4),
    }


def _tail_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _event_fts_document(*parts: str) -> str:
    return build_fts_document(*parts, pinyin_search_document(*parts))


def _build_retrieval_query(*, current_input: str, recent_context: str, project: str, app: str) -> str:
    current = _clean_retrieval_text(current_input, max_chars=180)
    context = _clean_retrieval_text(recent_context, max_chars=260)
    return compact_whitespace(" ".join(part for part in (current, context) if part))


def _clean_retrieval_text(text: str, *, max_chars: int) -> str:
    compact = compact_whitespace(text)
    if not compact:
        return ""
    compact = re.sub(r"```.*?```", " ", compact, flags=re.DOTALL)
    compact = re.sub(r"`[^`]{1,180}`", " ", compact)
    segments: list[str] = []
    for segment in re.split(r"[。！？；;\n\r]+", compact):
        cleaned = compact_whitespace(segment)
        if not cleaned or _looks_like_retrieval_noise(cleaned):
            continue
        segments.append(cleaned)
    result = compact_whitespace(" ".join(segments))
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result


def _looks_like_retrieval_noise(text: str) -> bool:
    stripped = compact_whitespace(text)
    lowered = stripped.lower()
    if not stripped:
        return True
    if stripped.startswith(
        (
            "*** Begin Patch",
            "*** Update File:",
            "diff --git",
            "Chunk ID:",
            "Output:",
            "Wall time:",
            "Original token count:",
            "Process exited",
            "已读取",
            "已搜索",
            "已列出",
            "已完成",
            "导入完成",
            "提交完成",
            "我现在判断",
            "我会先",
            "这里的可切分点",
            "这个截图说明",
            "然后另一个对话正在把这个rag和记忆系统做成一个底层",
        )
    ):
        return True
    if (
        "esc to interrupt" in lowered
        or "yield_time_ms" in lowered
        or "max_output_tokens" in lowered
        or "memory_summary" in lowered
        or "rollout_summaries" in lowered
        or "<subagent_notification>" in lowered
        or "codex_internal_context" in lowered
        or "index.ts 先改成依赖 core" in lowered
    ):
        return True
    if re.fullmatch(r"(?:python3|git|bash|zsh|pytest|xcodebuild|rg|sed|sqlite3)\b.*", lowered):
        return True
    if re.search(r"/(?:Users|Volumes|Library|Applications)/", stripped):
        return True
    return False


def _row_looks_like_retrieval_noise(row: sqlite3.Row) -> bool:
    tags = _row_tags(row)
    tag_set = {tag.lower() for tag in tags}
    if "runtime-noise" in tag_set or "role:event_msg" in tag_set or "role:assistant" in tag_set:
        return True
    text = compact_whitespace(
        " ".join(
            [
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
                str(row["schema_id"]),
                str(row["provider_name"]),
                " ".join(tags),
            ]
        )
    )
    if _looks_like_retrieval_noise(text):
        return True
    lowered = text.lower()
    markers = (
        "memory_summary",
        "rollout_summaries",
        "<subagent_notification>",
        "# agents.md instructions",
        "codex_internal_context",
        "working (",
        "chunk id:",
        "original token count:",
        "read implementation-goal.md",
        "searched for ",
        "listed files ",
        "index.ts 先改成依赖 core",
        "py 通过",
        "git diff --check",
        "installation.yaml",
        "管理员密码",
        "未跟踪",
    )
    return any(marker in lowered for marker in markers)


def _row_tags(row: sqlite3.Row) -> list[str]:
    try:
        raw = json.loads(row["tags_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _rag_database_duplicate_plan(rows: list[sqlite3.Row], *, sample_size: int) -> dict[str, object]:
    groups_by_key: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        text = compact_whitespace(str(row["committed_text"]))
        key_text = text.lower()
        if len(key_text) < 2:
            continue
        project = compact_whitespace(str(row["project"] or ""))
        key = f"{project}\0{key_text}"
        groups_by_key.setdefault(key, []).append(row)

    groups: list[dict[str, object]] = []
    hide_candidates: list[dict[str, object]] = []
    duplicate_event_count = 0
    for group_rows in groups_by_key.values():
        if len(group_rows) <= 1:
            continue
        duplicate_event_count += len(group_rows) - 1
        ordered = sorted(group_rows, key=_rag_duplicate_representative_score, reverse=True)
        representative = ordered[0]
        group_hide: list[sqlite3.Row] = []
        for row in ordered[1:]:
            if _rag_duplicate_row_protected(row):
                continue
            if not _rag_duplicate_row_hideable(row):
                continue
            group_hide.append(row)
            hide_candidates.append(
                {
                    "eventId": int(row["id"]),
                    "reason": "duplicate_low_value_text",
                    "row": row,
                }
            )
        if len(groups) < max(0, int(sample_size)):
            groups.append(
                {
                    "text": truncate_text(str(representative["committed_text"]), 80),
                    "project": str(representative["project"] or ""),
                    "count": len(group_rows),
                    "representativeEventId": int(representative["id"]),
                    "hideEventIds": [int(row["id"]) for row in group_hide],
                    "protectedEventIds": [int(row["id"]) for row in ordered[1:] if _rag_duplicate_row_protected(row)],
                    "sources": sorted({str(row["source"]) for row in group_rows if str(row["source"])}),
                    "tags": sorted({tag for row in group_rows for tag in _row_tags(row)}),
                }
            )
    return {
        "groups": groups,
        "hideCandidates": hide_candidates,
        "duplicateEventCount": duplicate_event_count,
        "wouldHideCount": len(hide_candidates),
    }


def _rag_database_similar_duplicate_plan(
    rows: list[sqlite3.Row],
    *,
    already_hidden_event_ids: set[int],
    sample_size: int,
) -> dict[str, object]:
    candidates: list[tuple[sqlite3.Row, str]] = []
    for row in rows:
        event_id = int(row["id"])
        if event_id in already_hidden_event_ids:
            continue
        if not (_rag_duplicate_row_protected(row) or _rag_duplicate_row_hideable(row)):
            continue
        normalized = _rag_similarity_text(str(row["committed_text"]))
        if len(normalized) < 18:
            continue
        candidates.append((row, normalized))

    by_project: dict[str, list[tuple[sqlite3.Row, str]]] = {}
    for row, normalized in candidates:
        project = compact_whitespace(str(row["project"] or ""))
        by_project.setdefault(project, []).append((row, normalized))

    groups: list[dict[str, object]] = []
    hide_candidates: list[dict[str, object]] = []
    similar_event_count = 0
    hidden_ids: set[int] = set()
    for project, project_rows in by_project.items():
        ordered = sorted(project_rows, key=lambda item: _rag_duplicate_representative_score(item[0]), reverse=True)
        rows_by_id = {int(row["id"]): (row, normalized) for row, normalized in ordered}
        block_index: dict[str, list[int]] = {}
        for row, normalized in ordered:
            event_id = int(row["id"])
            for key in _rag_similarity_block_keys(normalized):
                block_index.setdefault(key, []).append(event_id)
        for representative, rep_norm in ordered:
            rep_id = int(representative["id"])
            if rep_id in hidden_ids:
                continue
            group_rows: list[tuple[sqlite3.Row, str, str]] = []
            candidate_ids: set[int] = set()
            for key in _rag_similarity_block_keys(rep_norm):
                candidate_ids.update(block_index.get(key, ()))
            for event_id in sorted(candidate_ids):
                row, normalized = rows_by_id[event_id]
                event_id = int(row["id"])
                if event_id == rep_id or event_id in hidden_ids:
                    continue
                if compact_whitespace(str(row["committed_text"])) == compact_whitespace(str(representative["committed_text"])):
                    continue
                similarity_reason = _rag_similarity_reason(rep_norm, normalized)
                if not similarity_reason:
                    continue
                if _rag_duplicate_row_protected(row) or not _rag_duplicate_row_hideable(row):
                    continue
                group_rows.append((row, normalized, similarity_reason))
            if not group_rows:
                continue
            similar_event_count += len(group_rows)
            group_hide: list[sqlite3.Row] = []
            reasons: set[str] = set()
            for row, _normalized, similarity_reason in group_rows:
                event_id = int(row["id"])
                hidden_ids.add(event_id)
                group_hide.append(row)
                reasons.add(similarity_reason)
                hide_candidates.append(
                    {
                        "eventId": event_id,
                        "reason": "similar_low_value_text",
                        "similarityReason": similarity_reason,
                        "row": row,
                    }
                )
            if len(groups) < max(0, int(sample_size)):
                groups.append(
                    {
                        "text": truncate_text(str(representative["committed_text"]), 80),
                        "project": project,
                        "count": 1 + len(group_rows),
                        "representativeEventId": rep_id,
                        "hideEventIds": [int(row["id"]) for row in group_hide],
                        "similarityReasons": sorted(reasons),
                        "sources": sorted(
                            {str(row["source"]) for row, _norm, _reason in group_rows if str(row["source"])}
                            | {str(representative["source"])}
                        ),
                        "tags": sorted(
                            {tag for row, _norm, _reason in group_rows for tag in _row_tags(row)}
                            | set(_row_tags(representative))
                        ),
                    }
                )
    return {
        "groups": groups,
        "hideCandidates": hide_candidates,
        "similarEventCount": similar_event_count,
        "wouldHideCount": len(hide_candidates),
    }


def _rag_duplicate_representative_score(row: sqlite3.Row) -> tuple[int, int, int, int, int]:
    return (
        1 if _row_has_curated_memory_tags(row) else 0,
        1 if int(row["pinned"]) else 0,
        int(row["accepted_count"]),
        int(row["input_frequency"]),
        int(row["id"]),
    )


def _rag_duplicate_row_protected(row: sqlite3.Row) -> bool:
    return bool(
        _row_has_curated_memory_tags(row)
        or int(row["pinned"])
        or int(row["accepted_count"]) > 0
    )


def _rag_duplicate_row_hideable(row: sqlite3.Row) -> bool:
    text = compact_whitespace(str(row["committed_text"]))
    if len(text) >= 12:
        return True
    tags = {tag.lower() for tag in _row_tags(row)}
    if tags.intersection({"runtime-noise", "source:model", "source:rag", "codex-history", "raw", "history"}):
        return True
    return _row_is_generated_side_candidate(row) or _row_looks_like_retrieval_noise(row)


def _rag_similarity_text(text: str) -> str:
    return "".join(ch.lower() for ch in compact_whitespace(text) if ch.isalnum())


def _rag_similarity_block_keys(text: str) -> tuple[str, ...]:
    """Build deterministic blocking keys before expensive fuzzy comparison."""
    if not text:
        return ()
    keys = {f"len:{len(text) // 12}"}
    window = 8
    if len(text) <= window:
        keys.add(f"all:{text}")
        return tuple(sorted(keys))
    keys.add(f"prefix:{text[:window]}")
    keys.add(f"suffix:{text[-window:]}")
    middle = max(0, (len(text) - window) // 2)
    keys.add(f"middle:{text[middle:middle + window]}")
    step = max(1, window)
    for start in range(0, max(1, len(text) - window + 1), step):
        keys.add(f"gram:{text[start:start + window]}")
        if len(keys) >= 24:
            break
    return tuple(sorted(keys))


def _rag_similarity_reason(left: str, right: str) -> str:
    if not left or not right:
        return ""
    if left == right:
        return "normalized_equal" if len(left) >= 18 else ""
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 18:
        return ""
    if shorter in longer and len(shorter) / max(1, len(longer)) >= 0.72:
        return "contains"
    ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return "high_similarity" if ratio >= 0.9 else ""


def _row_should_skip_recent_context(row: sqlite3.Row) -> bool:
    tags = {tag.lower() for tag in _row_tags(row)}
    generated_tags = {"source:model", "source:rag"}
    if tags.intersection(generated_tags):
        return True
    if "runtime-noise" in tags or "role:event_msg" in tags or "role:assistant" in tags or "role:system" in tags:
        return True
    if str(row["source"]).strip().lower() in {"codex_internal_context", "tool_output"}:
        return True
    text = compact_whitespace(
        " ".join(
            [
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
                str(row["provider_name"]),
                " ".join(tags),
            ]
        )
    )
    return _looks_like_retrieval_noise(text)


def _rag_database_noise_reason(row: sqlite3.Row, *, min_generated_accepts: int) -> str:
    protected = _row_has_curated_memory_tags(row)
    if protected and not _row_is_generated_side_candidate(row):
        return ""
    if _row_looks_like_retrieval_noise(row):
        return "runtime_or_import_noise"
    text = compact_whitespace(
        " ".join(
            [
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
            ]
        )
    )
    if _looks_like_ime_complaint_or_debug_memory(text):
        return "ime_complaint_or_debug_feedback"
    if _row_is_generated_side_candidate(row) and not _row_has_durable_generated_signal(
        row,
        min_generated_accepts=min_generated_accepts,
    ):
        return "generated_side_candidate_oneoff"
    return ""


def _memory_event_row_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "eventId": int(row["id"]),
        "createdAtMs": int(row["created_at_ms"]),
        "source": str(row["source"]),
        "text": str(row["committed_text"]),
        "recentContext": str(row["recent_context"]),
        "preedit": str(row["preedit"]),
        "schemaId": str(row["schema_id"]),
        "app": str(row["app"]),
        "project": str(row["project"]),
        "candidateRank": int(row["candidate_rank"]) if row["candidate_rank"] is not None else None,
        "providerName": str(row["provider_name"]),
        "tags": _row_tags(row),
        "deleted": bool(row["deleted"]),
        "acceptedCount": int(row["accepted_count"]),
        "skippedCount": int(row["skipped_count"]),
        "downranked": int(row["downranked"]),
        "pinned": bool(row["pinned"]),
        "inputFrequency": int(row["input_frequency"]),
    }


def _csv_field(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(",")) if item]


def _row_has_curated_memory_tags(row: sqlite3.Row) -> bool:
    tags = {tag.lower() for tag in _row_tags(row)}
    return bool(tags.intersection({"curated", "demo-quality", "phrase-memory"}))


def _row_is_generated_side_candidate(row: sqlite3.Row) -> bool:
    tags = {tag.lower() for tag in _row_tags(row)}
    if tags.intersection({"source:model", "source:rag"}):
        return True
    provider_name = compact_whitespace(str(row["provider_name"])).lower()
    source = compact_whitespace(str(row["source"])).lower()
    return provider_name.startswith("rime-sidecar:") or source == "squirrel_rime_sidecar"


def _row_has_durable_generated_signal(row: sqlite3.Row, *, min_generated_accepts: int) -> bool:
    if int(row["pinned"]):
        return True
    values = (
        int(row["accepted_count"]),
        int(row["input_frequency"]),
        int(row["project_input_frequency"]),
        int(row["app_input_frequency"]),
    )
    return max(values) >= max(1, int(min_generated_accepts))


def _looks_like_ime_complaint_or_debug_memory(text: str) -> bool:
    surface = compact_whitespace(text)
    lowered = surface.lower()
    if not surface:
        return False
    complaint_markers = (
        "不能用",
        "用不了",
        "没办法",
        "没法",
        "没区别",
        "没意义",
        "没记录",
        "没有记录",
        "感觉随机",
        "真实生效",
        "输入不了",
        "依旧没有",
        "老是我之前输入",
        "展示不好",
        "不会弹出",
        "崩溃",
        "报错",
        "错误",
        "失败",
        "切成豆包",
    )
    if any(marker in surface for marker in complaint_markers):
        return True
    debug_markers = (
        "traceback",
        "brokenpipe",
        "stale_fingerprint",
        "sidecar_response_dropped",
        "fallbackjson",
        "doctor",
        "failure",
        "timeout",
    )
    return any(marker in lowered for marker in debug_markers)


def _recent_fill_enabled() -> bool:
    value = os.environ.get("RAG_IME_RECENT_MEMORY_FILL", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _pinyin_runtime_cache_fingerprint() -> str:
    keys = (
        "RAG_IME_PINYIN_FUZZY_ENABLED",
        "RAG_IME_PINYIN_FUZZY_PROFILE",
        "RAG_IME_PINYIN_FUZZY_Z_ZH",
        "RAG_IME_PINYIN_FUZZY_C_CH",
        "RAG_IME_PINYIN_FUZZY_S_SH",
        "RAG_IME_PINYIN_FUZZY_EN_ENG",
        "RAG_IME_PINYIN_FUZZY_IN_ING",
        "RAG_IME_PINYIN_FUZZY_N_L",
        "RAG_IME_PINYIN_FUZZY_F_H",
    )
    return "|".join(f"{key}={os.environ.get(key, '').strip().lower()}" for key in keys)


def _vector_only_match_allowed(*, raw_query: str, vector_score: float) -> bool:
    if vector_score <= 0:
        return False
    threshold = _vector_only_min_score()
    if vector_score < threshold:
        return False
    query = compact_whitespace(raw_query)
    if not query:
        return False
    required = _required_query_terms(query)
    pinyin_terms = _short_ascii_query_terms(query)
    if not required and not pinyin_terms:
        return False
    return True


def _vector_only_min_score() -> float:
    raw = os.environ.get("RAG_IME_VECTOR_ONLY_MIN_SCORE", "").strip()
    if not raw:
        return _VECTOR_ONLY_MIN_SCORE_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return _VECTOR_ONLY_MIN_SCORE_DEFAULT
    return max(0.0, min(0.95, value))


def _row_matches_required_query(
    row: sqlite3.Row,
    *,
    raw_query: str,
    allow_pinyin: bool = True,
    relaxed: bool = False,
) -> bool:
    required = _required_query_terms(raw_query)
    pinyin_terms = _short_ascii_query_terms(raw_query) if allow_pinyin else []
    if not required:
        if not pinyin_terms:
            return True
        pinyin_doc = set(
            pinyin_search_document(
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
            ).split()
        )
        return any(term in pinyin_doc or any(item.startswith(term) for item in pinyin_doc) for term in pinyin_terms)
    haystack = compact_whitespace(
        " ".join(
            [
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
                str(row["schema_id"]),
                str(row["provider_name"]),
                " ".join(json.loads(row["tags_json"] or "[]")),
            ]
        )
    ).lower()
    if pinyin_terms:
        pinyin_doc = set(
            pinyin_search_document(
                str(row["committed_text"]),
                str(row["recent_context"]),
                str(row["preedit"]),
            ).split()
        )
        if any(term in pinyin_doc or any(item.startswith(term) for item in pinyin_doc) for term in pinyin_terms):
            return True
    hits = [term for term in required if term.lower() in haystack]
    if not hits:
        return False
    if relaxed:
        return True
    if len(required) <= 2:
        return True
    return len(hits) >= 2 or any(len(term) >= 6 for term in hits)


def _required_query_terms(raw_query: str) -> list[str]:
    generic = {
        "agent",
        "candidate",
        "candidates",
        "codex",
        "debug",
        "ime",
        "input",
        "local",
        "memory",
        "model",
        "rag",
        "rime",
        "side",
        "squirrel",
        "test",
        "tests",
        "wisdom",
        "weasel",
    }
    terms: list[str] = []
    for term in token_terms(raw_query, max_terms=32):
        lowered = term.lower()
        if lowered in generic or len(lowered) < 2:
            continue
        if re.fullmatch(r"\d+", lowered):
            continue
        if re.fullmatch(r"[a-z]{1,3}", lowered):
            continue
        if lowered not in terms:
            terms.append(lowered)
    return terms[:8]


def _short_ascii_query_terms(raw_query: str) -> list[str]:
    generic = {
        "api",
        "app",
        "cli",
        "css",
        "dev",
        "git",
        "ime",
        "ios",
        "json",
        "llm",
        "mac",
        "mlx",
        "rag",
        "sql",
        "ui",
        "url",
        "web",
    }
    terms: list[str] = []
    for term in token_terms(raw_query, max_terms=32):
        lowered = term.lower()
        if lowered in generic:
            continue
        if re.fullmatch(r"[a-z]{2,8}", lowered) and lowered not in terms:
            terms.append(lowered)
    return terms[:4]


def _row_int(row: sqlite3.Row, key: str, *, default: int = 0) -> int:
    if key not in row.keys():
        return default
    value = row[key]
    if value is None:
        return default
    return int(value)


def _age_days(last_seen_ms: int, present_ms: int) -> float:
    return max(0.0, (present_ms - last_seen_ms) / _MS_PER_DAY)


def _frequency_recency_multiplier(last_seen_ms: int, present_ms: int) -> float:
    age_days = _age_days(last_seen_ms, present_ms)
    return 0.25 + 0.75 * math.pow(0.5, age_days / 30.0)


def _last_seen_recency_boost(last_seen_ms: int, *, present_ms: int) -> float:
    age_days = _age_days(last_seen_ms, present_ms)
    boost = 0.85 * math.pow(0.5, age_days / 7.0)
    return boost if boost >= 0.05 else 0.0


def _input_frequency_boost(input_frequency: int, last_seen_ms: int, *, present_ms: int) -> float:
    if input_frequency <= 1:
        return 0.0
    raw_boost = min(2.2, math.log1p(input_frequency - 1) * 0.9)
    return raw_boost * _frequency_recency_multiplier(last_seen_ms, present_ms)


def _score_breakdown_payload(
    *,
    query: str,
    raw_query: str,
    total: float,
    lexical: float,
    overlap_score: float,
    field_boosts: list[tuple[str, float]],
    pinyin_boost: float,
    frequency_boost: float,
    recent_boost: float,
    vector_score: float,
    vector_weight: float,
    vector_boost: float,
    project_boost: float,
    tag_boost: float,
    pinned_boost: float,
    accepted_boost: float,
    skipped_penalty: float,
    downrank_penalty: float,
    runtime_penalty: float,
    input_frequency: int,
    project_input_frequency: int,
    app_input_frequency: int,
    effective_frequency: int,
    frequency_scope: str,
    accepted: int,
    skipped: int,
    downranked: int,
    pinned: bool,
) -> dict[str, Any]:
    """Stable Alpha-style ranking diagnostics for debug surfaces.

    The IME panel should stay compact. This payload is for doctor/debug tools
    that need to explain why a RAG or memory candidate outranked alternatives.
    """

    return {
        "schemaVersion": "rag-ime.score-breakdown.v1",
        "total": _round_score(total),
        "query": truncate_text(raw_query or query, 120),
        "expandedQuery": truncate_text(query, 120),
        "components": {
            "fts5": _round_score(lexical),
            "overlap": _round_score(overlap_score),
            "field": _round_score(sum(boost for _, boost in field_boosts)),
            "pinyin": _round_score(pinyin_boost),
            "frequency": _round_score(frequency_boost),
            "recent": _round_score(recent_boost),
            "vector": _round_score(vector_boost),
            "project": _round_score(project_boost),
            "tag": _round_score(tag_boost),
            "pinned": _round_score(pinned_boost),
            "accepted": _round_score(accepted_boost),
            "skipped": _round_score(-skipped_penalty),
            "downranked": _round_score(-downrank_penalty),
            "runtimeTrace": _round_score(-runtime_penalty),
        },
        "fieldBoosts": [
            {"name": label, "score": _round_score(boost)}
            for label, boost in field_boosts
            if abs(boost) > 0.0005
        ],
        "rawSignals": {
            "vectorScore": _round_score(vector_score),
            "inputFrequency": input_frequency,
            "projectInputFrequency": project_input_frequency,
            "appInputFrequency": app_input_frequency,
            "effectiveFrequency": effective_frequency,
            "effectiveFrequencyScope": frequency_scope,
            "acceptedCount": accepted,
            "skippedCount": skipped,
            "downrankedCount": downranked,
            "pinned": pinned,
        },
        "weights": {
            "vector": _round_score(vector_weight),
            "accepted": 0.6,
            "skipped": -0.3,
            "downranked": -0.85,
            "pinned": 8.0,
        },
    }


def _round_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(float(value), 3)


def _tag_quality_boost(tags: tuple[str, ...]) -> float:
    tag_set = {str(tag).lower() for tag in tags}
    boost = 0.0
    if "curated" in tag_set:
        boost += 1.4
    if "demo-quality" in tag_set:
        boost += 0.8
    if "user-input" in tag_set:
        boost += 0.35
    if "source-label" in tag_set:
        boost += 0.25
    if "frequency" in tag_set or "phrase-memory" in tag_set:
        boost += 0.2
    return boost


def _expand_query_for_local_rerank(query: str) -> str:
    """Add cheap local synonyms before FTS, without calling an embedding model."""

    text = compact_whitespace(query)
    lowered = text.lower()
    extras: list[str] = []

    def add(*terms: str) -> None:
        for term in terms:
            if term and term not in extras:
                extras.append(term)

    if "project_memory_block" in lowered or ("注入" in text and ("首次" in text or "背景" in text or "agent" in lowered)):
        add("PROJECT_MEMORY_BLOCK", "agent-hook", "agent_hook", "first-run", "context injection", "背景注入")
    if "squirrel" in lowered or "rime" in lowered or ("输入法" in text and ("候选" in text or "拼音" in text)):
        add("Squirrel", "Rime", "librime", "sidecar", "候选面板", "拼音解析", "词库")
    if "脏拼音" in text or "便拼音" in text or "raw pinyin" in lowered:
        add("Rime", "librime", "拼音解析", "词库", "raw input", "raw pinyin fallback", "rawInputFallback")
    if "本地记忆" in text or "个人记忆" in text or "rag" in lowered or "隐私" in text or "云端" in text:
        add("local-first", "SQLite", "FTS5", "memory", "personal memory", "本地记忆")
    if "数字键" in text or ("候选" in text and ("共用" in text or "候选段" in text)):
        add(
            "Rime candidates",
            "side candidates",
            "number sequence",
            "selection key",
            "displayCandidates",
            "selectionAction",
            "候选编号",
        )
    if ("区分" in text or "选择" in text or "路由" in text) and (
        "squirrel" in lowered or "rime" in lowered or "side candidate" in lowered or "候选" in text
    ):
        add("select_candidate_on_current_page", "commit_side_candidate", "selectionAction", "selection routing")
    if "raw pinyin" in lowered or "fallback" in lowered or ("跳过" in text and ("side" in lowered or "刷新" in text)):
        add("raw pinyin fallback", "rawInputFallback", "sideCandidatesEnabled", "triggerDecision")
    if "缓存" in text and ("sidecar" in lowered or "重复" in text or "刷新" in text or "命中" in text):
        add("rimeSuggestCache", "cacheStats", "cache hit", "suggestion cache", "semantic cache")
    if "embedding" in lowered and ("endpoint" in lowered or "wsl" in lowered or "环境变量" in text):
        add("RAG_IME_EMBEDDING_BASE_URL", "RAG_IME_EMBEDDING_MODEL", "embedding endpoint", "WSL endpoint")
    if "suggestion cache" in lowered or ("缓存" in text and ("命中" in text or "失效" in text or "统计" in text)):
        add("suggestionCache", "LRU", "hitRate", "evictions", "invalidations", "suggestion_cache_stats")
    if ("codex" in lowered and "history" in lowered and "eval" in lowered) or (
        "ranking" in lowered and "metrics" in lowered
    ):
        add("top1Accuracy", "meanReciprocalRank", "meanFirstMatchRank", "eval_report", "ranking metrics")
    if "side slots" in lowered or ("模型" in text and ("占满" in text or "候选" in text)):
        add("maxModelSideCandidates", "maxSideCandidates", "side slots", "model side candidates")
    if "rag" in lowered and "模型" in text and ("比较" in text or "同一 case" in lowered or "同一个 case" in lowered):
        add("eval-comparison", "eval-prediction", "model prediction", "same case comparison")
    if "历史输入" in text or ("上下文" in text and "模型" in text):
        add("historyContext", "recent_input_context", "recent input context", "build_prediction_context")
    if "wisdom-weasel" in lowered or ("快速预测" in text and ("靠" in text or "什么" in text)):
        add("KV cache", "batch", "batch candidates", "llama.cpp", "LlamaCppProvider", "stale guard")
    if "openai compatible" in lowered or "openai-compatible" in lowered or ("predictor" in lowered and ("接" in text or "本地" in text)):
        add("RAG_IME_PREDICTOR_BASE_URL", "RAG_IME_PREDICTOR_MODEL", "openai-compatible", "predictor")
    if "旧候选" in text or "旧输入" in text or "覆盖" in text or "stale" in lowered:
        add("requestSeq", "stale", "stale guard", "request sequence", "latest request")
    if "trigger" in lowered or "触发" in text or ("什么时候" in text and ("跳过" in text or "刷新" in text)):
        add("triggerDecision", "sideCandidatesEnabled", "shouldRefresh")
    if "runtime 噪声" in text or "runtime noise" in lowered or "tool call" in lowered or ("过滤" in text and "codex" in lowered):
        add(
            "runtime noise",
            "tool call output",
            "tool output",
            "tool-output",
            "developer prompts",
            "system prompts",
            "AGENTS",
            "environment",
            "sandbox",
            "shell output",
            "shell 输出",
            "Codex history import",
        )

    return compact_whitespace(" ".join([text, *extras]))


def _field_rerank_boosts(
    *,
    query: str,
    raw_query: str,
    committed_text: str,
    recent_context: str,
    tags_text: str,
    source_fields: str,
) -> list[tuple[str, float]]:
    text_hits = overlap_terms(query, committed_text)
    raw_text_hits = overlap_terms(raw_query, committed_text)
    context_hits = overlap_terms(query, recent_context)
    tag_hits = overlap_terms(query, tags_text)
    source_hits = overlap_terms(query, source_fields)
    raw_ascii_hits = _important_ascii_hits(raw_query, f"{committed_text} {recent_context} {tags_text} {source_fields}")
    expanded_ascii_hits = [
        hit
        for hit in _important_ascii_hits(query, f"{committed_text} {recent_context} {tags_text} {source_fields}")
        if hit not in raw_ascii_hits
    ]
    canonical_alias = _canonical_alias_boost(query, f"{committed_text} {recent_context}")

    exact_phrase = 0.0
    raw = compact_whitespace(raw_query).lower()
    if raw and len(raw) >= 4:
        combined = f"{committed_text} {recent_context}".lower()
        if raw in combined:
            exact_phrase = 0.8

    boosts = [
        ("text", min(1.2, len(text_hits) * 0.12 + len(raw_text_hits) * 0.08 + exact_phrase)),
        ("context", min(1.1, len(context_hits) * 0.18)),
        ("tag", min(1.6, len(tag_hits) * 0.45)),
        ("source", min(0.8, len(source_hits) * 0.25)),
        ("raw", min(2.4, len(raw_ascii_hits) * 0.8)),
        ("expanded", min(2.1, len(expanded_ascii_hits) * 0.7)),
        ("canonical", canonical_alias),
    ]
    return [(label, boost) for label, boost in boosts if boost > 0]


def _pinyin_rerank_boost(raw_query: str, committed_text: str, recent_context: str) -> float:
    query = re.sub(r"[^A-Za-z0-9]", "", raw_query or "").lower()
    if len(query) < 2:
        return 0.0
    terms = pinyin_search_terms(committed_text, recent_context)
    if query in terms:
        return 1.15 if terms[query] == "exact" else 0.82
    exact_prefix = False
    fuzzy_prefix = False
    for term, source in terms.items():
        if not term.startswith(query):
            continue
        if source == "exact":
            exact_prefix = True
        else:
            fuzzy_prefix = True
    if exact_prefix:
        return 0.75
    if fuzzy_prefix:
        return 0.45
    return 0.0


def _important_ascii_hits(query: str, text: str) -> list[str]:
    haystack = (text or "").lower()
    hits: list[str] = []
    seen: set[str] = set()
    for match in _IMPORTANT_ASCII_RE.finditer(query or ""):
        term = match.group(0).lower()
        if term in seen:
            continue
        seen.add(term)
        if term in haystack:
            hits.append(term)
    return hits


def _canonical_alias_boost(query: str, text: str) -> float:
    query_lower = (query or "").lower()
    compact = compact_whitespace(text or "")
    lowered = compact.lower()
    score = 0.0
    if "rag_ime_embedding_base_url" in query_lower and "embedding endpoint" in lowered and (
        "wsl" in lowered or "openai-compatible" in lowered or "rag_ime_embedding_provider" in lowered
    ):
        score += 0.9
    if "maxmodelsidecandidates" in query_lower and (
        "模型候选挤掉" in compact or ("最多 1 个模型" in compact and "side" in lowered)
    ):
        score += 1.0
    return min(1.4, score)


def _bm25_relevance(bm25_score: float) -> float:
    """Convert SQLite FTS5 bm25, where lower and often negative is better, to a positive boost."""

    if bm25_score < 0:
        return min(4.0, math.log1p(-bm25_score))
    return 1.0 / (1.0 + bm25_score)


def _runtime_trace_penalty(text: str) -> float:
    """Downrank raw Codex tool transcripts without deleting useful code identifiers."""

    stripped = compact_whitespace(text)
    lowered = stripped.lower()
    prefix = lowered[:120]
    if stripped.startswith(("*** Begin Patch", "*** Update File:", "*** Add File:", "diff --git")):
        return 2.4
    if "*** begin patch" in lowered or " apply_patch " in lowered or "tool apply_patch" in lowered:
        return 2.4
    if stripped.startswith("<subagent_notification>"):
        return 1.2
    if stripped.startswith("**只读结论**") or stripped.startswith("只读结论"):
        return 0.8
    if re.match(r"^\[\d+\]\s+tool\s+", stripped):
        return 0.35
    if prefix.startswith("tool ") and (" call" in prefix or " result" in prefix):
        return 0.35
    if "chunk id:" in lowered and ("process exited" in lowered or "wall time:" in lowered):
        return 0.35
    return 0.0


def _copy_suggestions(suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...]) -> list[InputSuggestion]:
    return [replace(item, metadata=dict(item.metadata)) for item in suggestions]


def _legacy_suggestions_need_v2_recovery(
    suggestions: list[InputSuggestion],
    *,
    current_input: str,
    recent_context: str,
) -> bool:
    return any(
        _suggestion_looks_like_raw_history_echo(
            suggestion,
            current_input=current_input,
            recent_context=recent_context,
        )
        for suggestion in suggestions[:3]
    )


def _should_prefer_v2_ime_suggestions(
    *,
    legacy_suggestions: list[InputSuggestion],
    v2_suggestions: list[InputSuggestion],
    current_input: str,
    recent_context: str,
) -> bool:
    if not v2_suggestions:
        return False
    if not any(
        _suggestion_looks_like_raw_history_echo(
            suggestion,
            current_input=current_input,
            recent_context=recent_context,
        )
        for suggestion in legacy_suggestions[:3]
    ):
        return False
    return any(_suggestion_looks_like_compiled_memory(item) for item in v2_suggestions[:3])


def _merge_prefer_v2_suggestions(
    *,
    v2_suggestions: list[InputSuggestion],
    legacy_suggestions: list[InputSuggestion],
    top_k: int,
    current_input: str,
    recent_context: str,
) -> list[InputSuggestion]:
    merged: list[InputSuggestion] = []
    seen: set[str] = set()
    for item in [*v2_suggestions, *legacy_suggestions]:
        if item in legacy_suggestions and _suggestion_looks_like_raw_history_echo(
            item,
            current_input=current_input,
            recent_context=recent_context,
        ):
            continue
        key = _legacy_v2_suggestion_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= max(1, top_k):
            break
    return merged


def _legacy_v2_suggestion_key(suggestion: InputSuggestion) -> str:
    metadata = dict(suggestion.metadata)
    insert_text = compact_whitespace(str(metadata.get("insert_text") or suggestion.surface_text)).lower()
    memory_id = compact_whitespace(str(metadata.get("memory_id") or ""))
    return memory_id or insert_text


def _suggestion_looks_like_compiled_memory(suggestion: InputSuggestion) -> bool:
    metadata = dict(suggestion.metadata)
    tags = {str(tag).lower() for tag in metadata.get("tags") or []}
    surface = compact_whitespace(suggestion.surface_text)
    if not surface or len(surface) > 24:
        return False
    if tags.intersection({"phrase-memory", "compiled-memory", "compiled-phrase", "curated", "structure", "outline"}):
        return True
    source_type = str(metadata.get("source_type") or "")
    return source_type == "memory" and suggestion.suggestion_type in {"phrase", "structure", "continue"}


def _suggestion_looks_like_raw_history_echo(
    suggestion: InputSuggestion,
    *,
    current_input: str,
    recent_context: str,
) -> bool:
    metadata = dict(suggestion.metadata)
    tags = {str(tag).lower() for tag in metadata.get("tags") or []}
    surface = compact_whitespace(suggestion.surface_text)
    if not surface or len(surface) <= 24:
        return False
    if tags.intersection({"phrase-memory", "compiled-memory", "compiled-phrase", "curated", "structure", "outline"}):
        return False
    if tags.intersection({"user-input", "raw", "history", "codex-history"}):
        return True
    if suggestion.suggestion_type not in {"sentence", "paragraph"}:
        return False
    if str(metadata.get("source_type") or "") not in {"memory", "rag"}:
        return False
    normalized_input = compact_whitespace(current_input).lower()
    normalized_context = compact_whitespace(recent_context).lower()
    normalized_surface = surface.lower()
    if normalized_input and normalized_input in normalized_surface:
        return True
    if normalized_context and len(normalized_context) >= 4 and normalized_context in normalized_surface:
        return True
    return False


def _merge_rows(*groups: list[sqlite3.Row]) -> list[sqlite3.Row]:
    merged: list[sqlite3.Row] = []
    seen: set[int] = set()
    for group in groups:
        for row in group:
            event_id = int(row["id"])
            if event_id in seen:
                continue
            seen.add(event_id)
            merged.append(row)
    return merged
