from __future__ import annotations

import sqlite3


def ensure_memory_book_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_books (
            book_id TEXT PRIMARY KEY,
            book_type TEXT NOT NULL,
            book_key TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            normalized_text TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            app TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            surface_hints_json TEXT NOT NULL DEFAULT '[]',
            query_expansions_json TEXT NOT NULL DEFAULT '[]',
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            memory_atom_ids_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            confidence REAL NOT NULL DEFAULT 0.5,
            quality_score REAL NOT NULL DEFAULT 0.5,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_memory_books_type_key
        ON memory_books(book_type, book_key);

        CREATE INDEX IF NOT EXISTS idx_memory_books_project_app
        ON memory_books(project, app);

        CREATE TABLE IF NOT EXISTS memory_retrieval_docs (
            doc_id TEXT PRIMARY KEY,
            doc_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            raw_text TEXT NOT NULL DEFAULT '',
            tags_text TEXT NOT NULL DEFAULT '',
            aliases_text TEXT NOT NULL DEFAULT '',
            surface_hints_text TEXT NOT NULL DEFAULT '',
            query_expansions_text TEXT NOT NULL DEFAULT '',
            time_key TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            app TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            updated_at_ms INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_retrieval_docs_fts USING fts5(
            raw_text,
            tags_text,
            aliases_text,
            surface_hints_text,
            query_expansions_text,
            time_key,
            project,
            app,
            tokenize = 'unicode61'
        );

        CREATE TABLE IF NOT EXISTS memory_compile_state (
            project TEXT PRIMARY KEY,
            last_compiled_event_id INTEGER NOT NULL DEFAULT 0,
            last_run_ms INTEGER NOT NULL DEFAULT 0,
            pending_event_count INTEGER NOT NULL DEFAULT 0,
            last_bundle_hash TEXT NOT NULL DEFAULT ''
        );
        """
    )


def memory_book_table_names() -> tuple[str, ...]:
    return (
        "memory_books",
        "memory_retrieval_docs",
        "memory_retrieval_docs_fts",
        "memory_compile_state",
    )
