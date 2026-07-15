from __future__ import annotations

import sqlite3

from .db import apply_database_migrations
from .memory_book_schema import memory_book_table_names


def ensure_memory_v2_schema(conn: sqlite3.Connection) -> None:
    apply_database_migrations(conn)


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
        "memory_entity_sources",
        "memory_relation_sources",
        "memory_entity_aliases",
        "memory_relations",
        "memory_entities",
        "memory_projection_outbox",
        "memory_projection_checkpoints",
        "memory_graph_projection_map",
        *memory_book_table_names(),
    )
