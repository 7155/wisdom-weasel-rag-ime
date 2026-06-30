from __future__ import annotations

import json
import sqlite3
from pathlib import Path
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


class LocalSqliteCoreClient:
    """Mac-local SQLite/FTS5 implementation of the CoreClient protocol.

    This is the complete local MVP backend. It sits behind the same `CoreClient`
    boundary as the future shared core, so the IME adapter/UI does not need to be
    rewritten when the shared core exposes stable record/action APIs.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.compiler = SuggestionCompiler()

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
        return f"event:{event_id}"

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        memories = self.retrieve_memories(
            current_input=current_input,
            recent_context=recent_context,
            project=project,
            top_k=max(top_k, 10),
        )
        ranked = [RankedMemory(memory=memory, score=memory.score, rank=index) for index, memory in enumerate(memories, start=1)]
        return self.compiler.compile(ranked)[:top_k]

    def retrieve_memories(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        top_k: int = 5,
    ) -> list[CoreMemory]:
        self.initialize()
        query = compact_whitespace(f"{recent_context} {current_input}")
        fts_query = build_fts_query(query)
        if not fts_query:
            rows = self._recent_rows(project=project, limit=top_k)
        else:
            rows = self._search_rows(fts_query=fts_query, project=project, limit=max(top_k * 4, 20))
            if not rows:
                rows = self._recent_rows(project=project, limit=top_k)
            elif len(rows) < top_k:
                rows = self._append_recent_fill(rows, project=project, limit=top_k)

        memories = [self._row_to_memory(row, query=query, project=project) for row in rows]
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

    def _row_to_memory(self, row: sqlite3.Row, *, query: str, project: str) -> CoreMemory:
        event_id = int(row["id"])
        bm25 = float(row["bm25_score"] if row["bm25_score"] is not None else 99.0)
        lexical = 1.0 / (1.0 + max(0.0, bm25))
        overlap = overlap_terms(query, f"{row['committed_text']} {row['recent_context']} {row['tags_json']}")
        overlap_score = min(1.5, len(overlap) * 0.3)
        accepted = int(row["accepted_count"])
        skipped = int(row["skipped_count"])
        downranked = int(row["downranked"])
        pinned = bool(row["pinned"])
        project_boost = 0.4 if project and row["project"] == project else 0.0
        score = (
            lexical
            + overlap_score
            + project_boost
            + (2.0 if pinned else 0.0)
            + accepted * 0.6
            - skipped * 0.3
            - downranked * 0.85
        )
        reason = ["fts5"]
        if overlap:
            reason.append("overlap:" + ",".join(overlap[:4]))
        if pinned:
            reason.append("pinned")
        if accepted:
            reason.append(f"accepted:{accepted}")
        if downranked:
            reason.append(f"downranked:{downranked}")
        tags = tuple(json.loads(row["tags_json"] or "[]"))
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
