from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any

from .core_client import CoreMemory
from .models import AgentContextInjection, InputEvent, InputSuggestion, MemoryAction
from .suggestion_compiler import RankedMemory, SuggestionCompiler
from .text_utils import (
    build_fts_document,
    build_fts_query,
    compact_whitespace,
    now_ms,
    overlap_terms,
    truncate_text,
)


_IMPORTANT_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{2,}")


class LocalSqliteCoreClient:
    """Mac-local SQLite/FTS5 implementation of the CoreClient protocol.

    This is the complete local MVP backend. It sits behind the same `CoreClient`
    boundary as the future shared core, so the IME adapter/UI does not need to be
    rewritten when the shared core exposes stable record/action APIs.
    """

    def __init__(self, db_path: str | Path, *, suggestion_cache_size: int = 128):
        self.db_path = Path(db_path)
        self.compiler = SuggestionCompiler()
        self.suggestion_cache_size = max(0, int(suggestion_cache_size))
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
                """
            )

    def reset(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                DROP TABLE IF EXISTS memory_actions;
                DROP TABLE IF EXISTS memory_state;
                DROP TABLE IF EXISTS input_events;
                DROP TABLE IF EXISTS memory_fts;
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
            document = build_fts_document(text, event.recent_context, event.project, " ".join(event.tags), event.preedit)
            conn.execute(
                """
                INSERT INTO memory_fts(rowid, content_text, committed_text, recent_context, project, tags)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, document, text, event.recent_context, event.project, " ".join(event.tags)),
            )
        self._clear_suggestion_cache()
        return f"event:{event_id}"

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        cache_key = self._suggestion_cache_key(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            top_k=top_k,
        )
        cached = self._get_cached_suggestions(cache_key)
        if cached is not None:
            return cached
        memories = self.retrieve_memories(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
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
        top_k: int = 5,
    ) -> list[CoreMemory]:
        self.initialize()
        raw_query = compact_whitespace(f"{recent_context} {current_input}")
        query = _expand_query_for_local_rerank(raw_query)
        fts_query = build_fts_query(query)
        if not fts_query:
            rows = self._recent_rows(project=project, limit=top_k)
        else:
            rows = self._search_rows(fts_query=fts_query, project=project, limit=max(top_k * 8, 50))
            if not rows:
                rows = self._recent_rows(project=project, limit=top_k)
            elif len(rows) < top_k:
                rows = self._append_recent_fill(rows, project=project, limit=top_k)

        memories = [self._row_to_memory(row, query=query, project=project, raw_query=raw_query) for row in rows]
        memories.sort(key=lambda item: item.score, reverse=True)
        return memories[:top_k]

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
            SELECT e.committed_text, e.recent_context, e.preedit, e.created_at_ms
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
            ORDER BY e.id DESC
            LIMIT ?
        """
        params.append(max(1, min(20, limit)))
        with self._connect() as conn:
            rows = list(conn.execute(sql, params).fetchall())

        selected: list[str] = []
        used_chars = 0
        separator_len = len(" / ")
        for row in rows:
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

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _suggestion_cache_key(
        self,
        *,
        current_input: str,
        recent_context: str,
        project: str,
        top_k: int,
    ) -> tuple[str, str, str, int]:
        return (
            compact_whitespace(current_input),
            compact_whitespace(recent_context),
            compact_whitespace(project),
            int(top_k),
        )

    def _get_cached_suggestions(self, key: tuple[str, str, str, int]) -> list[InputSuggestion] | None:
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

    def _store_cached_suggestions(self, key: tuple[str, str, str, int], suggestions: list[InputSuggestion]) -> None:
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

    def _search_rows(self, *, fts_query: str, project: str, limit: int) -> list[sqlite3.Row]:
        params: list[Any] = [fts_query]
        where = ["memory_fts MATCH ?", "s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        sql = f"""
            SELECT e.*, s.*, bm25(memory_fts) AS bm25_score
            FROM memory_fts
            JOIN input_events e ON e.id = memory_fts.rowid
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
            ORDER BY s.pinned DESC, bm25(memory_fts) ASC, e.created_at_ms DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def _recent_rows(self, *, project: str, limit: int) -> list[sqlite3.Row]:
        params: list[Any] = []
        where = ["s.deleted = 0"]
        if project:
            where.append("(e.project = ? OR e.project = '')")
            params.append(project)
        sql = f"""
            SELECT e.*, s.*, 99.0 AS bm25_score
            FROM input_events e
            JOIN memory_state s ON s.event_id = e.id
            WHERE {' AND '.join(where)}
            ORDER BY s.pinned DESC, e.created_at_ms DESC
            LIMIT ?
        """
        params.append(limit)
        with self._connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def _append_recent_fill(self, rows: list[sqlite3.Row], *, project: str, limit: int) -> list[sqlite3.Row]:
        seen = {int(row["id"]) for row in rows}
        filled = list(rows)
        for row in self._recent_rows(project=project, limit=max(limit * 2, 10)):
            if int(row["id"]) in seen:
                continue
            filled.append(row)
            seen.add(int(row["id"]))
            if len(filled) >= limit:
                break
        return filled

    def _row_to_memory(self, row: sqlite3.Row, *, query: str, project: str, raw_query: str = "") -> CoreMemory:
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
        accepted = int(row["accepted_count"])
        skipped = int(row["skipped_count"])
        downranked = int(row["downranked"])
        pinned = bool(row["pinned"])
        project_boost = 0.4 if project and row["project"] == project else 0.0
        score = (
            lexical
            + overlap_score
            + sum(boost for _, boost in field_boosts)
            + project_boost
            + (8.0 if pinned else 0.0)
            + accepted * 0.6
            - skipped * 0.3
            - downranked * 0.85
        )
        reason = [f"fts5:{lexical:.3f}"]
        if overlap:
            reason.append("overlap:" + ",".join(overlap[:4]))
        for label, boost in field_boosts:
            if boost > 0:
                reason.append(f"{label}:{boost:.2f}")
        if pinned:
            reason.append("pinned")
        if accepted:
            reason.append(f"accepted:{accepted}")
        if downranked:
            reason.append(f"downranked:{downranked}")
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
            project=str(row["project"]),
            tags=tags,
            created_at_ms=int(row["created_at_ms"]),
            state={
                "accepted_count": accepted,
                "skipped_count": skipped,
                "pinned": pinned,
                "downranked": downranked,
                "deleted": bool(row["deleted"]),
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


def _tail_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


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
        add("Rime", "librime", "拼音解析", "词库", "raw input")
    if "本地记忆" in text or "个人记忆" in text or "rag" in lowered:
        add("local-first", "SQLite", "FTS5", "memory", "personal memory", "本地记忆")

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
    ]
    return [(label, boost) for label, boost in boosts if boost > 0]


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


def _bm25_relevance(bm25_score: float) -> float:
    """Convert SQLite FTS5 bm25, where lower and often negative is better, to a positive boost."""

    if bm25_score < 0:
        return min(4.0, math.log1p(-bm25_score))
    return 1.0 / (1.0 + bm25_score)


def _copy_suggestions(suggestions: list[InputSuggestion] | tuple[InputSuggestion, ...]) -> list[InputSuggestion]:
    return [replace(item, metadata=dict(item.metadata)) for item in suggestions]
