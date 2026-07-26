"""One owner for a SQLite handle and its transaction.

`with sqlite3.connect(path) as conn:` reads like resource management but is
not: `sqlite3.Connection.__exit__` commits or rolls back the transaction and
leaves the handle open. Every such call site leaks a file descriptor until the
garbage collector happens to run, which is why long test runs and the resident
sidecar emit `ResourceWarning: unclosed database`.

`sqlite_connection` keeps the same commit-on-success / rollback-on-error
semantics and additionally closes the handle, so the two lifecycles have a
single owner.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def sqlite_connection(
    database: str | Path,
    *,
    uri: bool = False,
    row_factory: object | None = None,
    foreign_keys: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Yield a connection that commits on success and always closes."""

    conn = sqlite3.connect(str(database), uri=uri)
    try:
        if row_factory is not None:
            conn.row_factory = row_factory  # type: ignore[assignment]
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            yield conn
    finally:
        conn.close()
