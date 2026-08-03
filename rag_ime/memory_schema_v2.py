from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import apply_database_migrations
from .db.migration_runner import DEFAULT_MIGRATIONS_DIR
from .memory_book_schema import memory_book_table_names


def ensure_memory_v2_schema(
    conn: sqlite3.Connection,
    *,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    apply_database_migrations(conn, migrations_dir=migrations_dir)


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
