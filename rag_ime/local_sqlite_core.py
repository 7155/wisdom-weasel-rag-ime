from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from .core_client import CoreMemory
from .embeddings import EmbeddingProvider, NullEmbeddingProvider, cosine_similarity
from .models import AgentContextInjection, InputEvent, InputSuggestion, MemoryAction
from .pinyin_index import pinyin_search_document
from .suggestion_compiler import RankedMemory, SuggestionCompiler
from .text_utils import (
    build_fts_document,
    build_fts_query,
    compact_whitespace,
    now_ms,
    overlap_terms,
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
    ):
        self.db_path = Path(db_path)
        self.compiler = SuggestionCompiler()
        self.suggestion_cache_size = max(0, int(suggestion_cache_size))
        self.embedding_provider = embedding_provider or NullEmbeddingProvider()
        self.vector_candidate_limit = max(0, int(vector_candidate_limit))
        self.vector_weight = max(0.0, float(vector_weight))
        self._suggestion_cache: OrderedDict[tuple[str, str, str, int], tuple[InputSuggestion, ...]] = OrderedDict()
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
        with self._connect() as conn:
            conn.executescript(
                """
                DROP TABLE IF EXISTS memory_vectors;
                DROP TABLE IF EXISTS memory_actions;
                DROP TABLE IF EXISTS memory_state;
                DROP TABLE IF EXISTS input_events;
                DROP TABLE IF EXISTS memory_fts;
                DROP TABLE IF EXISTS phrase_stats;
                DROP TABLE IF EXISTS phrase_project_stats;
                DROP TABLE IF EXISTS phrase_app_stats;
                """
            )
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
        cache_key = self._suggestion_cache_key(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=top_k,
        )
        cached = self._get_cached_suggestions(cache_key)
        if cached is not None:
            return cached
        memories = self.retrieve_memories(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            app=app,
            top_k=max(top_k * 4, 20),
        )
        ranked = [RankedMemory(memory=memory, score=memory.score, rank=index) for index, memory in enumerate(memories, start=1)]
        suggestions = self.compiler.compile(ranked)[:top_k]
        self._store_cached_suggestions(cache_key, suggestions)
        return _copy_suggestions(suggestions)

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
        return memories[:top_k]

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
        top_k: int,
    ) -> tuple[str, str, str, str, int]:
        return (
            compact_whitespace(current_input),
            compact_whitespace(recent_context),
            compact_whitespace(project),
            compact_whitespace(app),
            int(top_k),
        )

    def _get_cached_suggestions(self, key: tuple[str, str, str, str, int]) -> list[InputSuggestion] | None:
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

    def _store_cached_suggestions(self, key: tuple[str, str, str, str, int], suggestions: list[InputSuggestion]) -> None:
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
    terms = set(pinyin_search_document(committed_text, recent_context).split())
    if query in terms:
        return 1.15
    if any(term.startswith(query) for term in terms):
        return 0.75
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


def _merge_rows(primary: list[sqlite3.Row], secondary: list[sqlite3.Row]) -> list[sqlite3.Row]:
    merged: list[sqlite3.Row] = []
    seen: set[int] = set()
    for row in [*primary, *secondary]:
        event_id = int(row["id"])
        if event_id in seen:
            continue
        seen.add(event_id)
        merged.append(row)
    return merged
