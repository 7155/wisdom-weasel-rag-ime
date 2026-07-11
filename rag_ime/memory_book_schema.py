from __future__ import annotations

import sqlite3

from .db import apply_database_migrations


def ensure_memory_book_schema(conn: sqlite3.Connection) -> None:
    apply_database_migrations(conn)


def memory_book_table_names() -> tuple[str, ...]:
    return (
        "memory_books",
        "memory_retrieval_docs",
        "memory_retrieval_docs_fts",
        "memory_compile_state",
    )
