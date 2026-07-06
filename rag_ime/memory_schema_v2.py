from __future__ import annotations

import sqlite3

from .memory_book_schema import ensure_memory_book_schema, memory_book_table_names


def ensure_memory_v2_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            normalized_text TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            source_event_id INTEGER,
            project TEXT NOT NULL DEFAULT '',
            app TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0.5,
            quality_score REAL NOT NULL DEFAULT 0.5,
            status TEXT NOT NULL DEFAULT 'active',
            privacy_class TEXT NOT NULL DEFAULT 'local',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            ttl_ms INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(source_event_id) REFERENCES input_events(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_items_kind_status
        ON memory_items(kind, status);

        CREATE INDEX IF NOT EXISTS idx_memory_items_project_app
        ON memory_items(project, app);

        CREATE TABLE IF NOT EXISTS memory_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT UNIQUE NOT NULL,
            normalized_tag TEXT NOT NULL,
            tag_type TEXT NOT NULL DEFAULT 'concept',
            vector_json TEXT,
            model_fingerprint TEXT NOT NULL DEFAULT '',
            quality_score REAL NOT NULL DEFAULT 0.5,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_item_tags (
            memory_item_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            position INTEGER NOT NULL DEFAULT 0,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(memory_item_id, tag_id),
            FOREIGN KEY(memory_item_id) REFERENCES memory_items(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES memory_tags(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_tag_edges (
            src_tag_id INTEGER NOT NULL,
            dst_tag_id INTEGER NOT NULL,
            edge_type TEXT NOT NULL DEFAULT 'cooccur',
            weight REAL NOT NULL DEFAULT 1.0,
            direction_bias REAL NOT NULL DEFAULT 0.0,
            evidence_count INTEGER NOT NULL DEFAULT 1,
            updated_at_ms INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY(src_tag_id, dst_tag_id, edge_type),
            FOREIGN KEY(src_tag_id) REFERENCES memory_tags(id) ON DELETE CASCADE,
            FOREIGN KEY(dst_tag_id) REFERENCES memory_tags(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_memory_tag_edges_src
        ON memory_tag_edges(src_tag_id, weight DESC);

        CREATE TABLE IF NOT EXISTS memory_item_vectors (
            memory_item_id INTEGER NOT NULL,
            provider_fingerprint TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY(memory_item_id, provider_fingerprint),
            FOREIGN KEY(memory_item_id) REFERENCES memory_items(id) ON DELETE CASCADE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
            text,
            normalized_text,
            summary,
            project,
            app,
            tags,
            tokenize = 'unicode61'
        );

        CREATE TABLE IF NOT EXISTS memory_cleanup_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            created_at_ms INTEGER NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            summary TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS memory_cleanup_diffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            op TEXT NOT NULL,
            target_memory_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at_ms INTEGER NOT NULL,
            applied_at_ms INTEGER,
            rollback_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(run_id) REFERENCES memory_cleanup_runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS candidate_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_ms INTEGER NOT NULL,
            query_hash TEXT NOT NULL,
            candidate_text TEXT NOT NULL,
            source_type TEXT NOT NULL,
            memory_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            app TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS memory_tombstones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at_ms INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_value TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_memory_tombstones_target
        ON memory_tombstones(target_type, target_value, active);

        CREATE TABLE IF NOT EXISTS memory_atoms (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            canonical_text TEXT,
            source_event_ids_json TEXT NOT NULL DEFAULT '[]',
            source_memory_ids_json TEXT NOT NULL DEFAULT '[]',
            scope_app TEXT,
            scope_project TEXT,
            language TEXT DEFAULT 'zh',
            confidence REAL NOT NULL DEFAULT 0.5,
            quality_score REAL NOT NULL DEFAULT 0.5,
            echo_risk REAL NOT NULL DEFAULT 0.0,
            privacy_level TEXT NOT NULL DEFAULT 'local',
            status TEXT NOT NULL DEFAULT 'active',
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            last_used_at_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS memory_aliases (
            id TEXT PRIMARY KEY,
            memory_atom_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            alias_type TEXT NOT NULL,
            pinyin TEXT,
            weight REAL NOT NULL DEFAULT 0.5,
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY(memory_atom_id) REFERENCES memory_atoms(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_atom_tags (
            memory_atom_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5,
            source TEXT NOT NULL DEFAULT 'offline',
            PRIMARY KEY(memory_atom_id, tag_id),
            FOREIGN KEY(memory_atom_id) REFERENCES memory_atoms(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES memory_tags(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS memory_candidate_suppressions (
            id TEXT PRIMARY KEY,
            match_type TEXT NOT NULL,
            match_value TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            strength REAL NOT NULL DEFAULT 1.0,
            expires_at_ms INTEGER,
            created_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_feedback_events (
            id TEXT PRIMARY KEY,
            candidate_id TEXT,
            candidate_text TEXT NOT NULL,
            candidate_source TEXT NOT NULL,
            action TEXT NOT NULL,
            context_hash TEXT,
            front_app_bundle_id TEXT,
            raw_input TEXT,
            preedit TEXT,
            committed_tail TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_optimizer_traces (
            id TEXT PRIMARY KEY,
            request_seq INTEGER NOT NULL,
            context_hash TEXT NOT NULL,
            query_plan_json TEXT NOT NULL,
            raw_results_json TEXT NOT NULL,
            optimized_candidates_json TEXT NOT NULL,
            blocked_json TEXT NOT NULL DEFAULT '[]',
            latency_ms REAL NOT NULL,
            created_at_ms INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_atoms_status_quality
        ON memory_atoms(status, quality_score, confidence);

        CREATE INDEX IF NOT EXISTS idx_memory_atoms_scope
        ON memory_atoms(scope_project, scope_app);

        CREATE INDEX IF NOT EXISTS idx_memory_aliases_alias
        ON memory_aliases(alias);

        CREATE INDEX IF NOT EXISTS idx_memory_feedback_context
        ON memory_feedback_events(context_hash, created_at_ms);

        CREATE INDEX IF NOT EXISTS idx_memory_suppressions_match
        ON memory_candidate_suppressions(match_type, match_value);
        """
    )
    ensure_memory_book_schema(conn)


def memory_v2_table_names() -> tuple[str, ...]:
    return (
        "memory_items",
        "memory_tags",
        "memory_item_tags",
        "memory_tag_edges",
        "memory_item_vectors",
        "memory_items_fts",
        "memory_cleanup_runs",
        "memory_cleanup_diffs",
        "candidate_feedback",
        "memory_tombstones",
        "memory_atoms",
        "memory_aliases",
        "memory_atom_tags",
        "memory_candidate_suppressions",
        "memory_feedback_events",
        "memory_optimizer_traces",
        *memory_book_table_names(),
    )
