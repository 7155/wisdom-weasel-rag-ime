"""Small, transaction-explicit helpers; no migrations or I/O on import."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MAX_OBJECTS = 10_000
MAX_BUNDLE_BYTES = 16 * 1024 * 1024


class LifecycleError(ValueError):
    """Stable, content-free error code safe to show in a receipt."""


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise LifecycleError("invalid_json") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identifier(value: Any, *, field: str = "identifier", allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 400 or (not value and not allow_empty) or any(ord(c) < 32 for c in value):
        raise LifecycleError(f"invalid_{field}")
    return value


def timestamp(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 253402300799999:
        raise LifecycleError("invalid_timestamp")
    return value


def load_json(value: str, expected: type = dict) -> Any:
    try:
        result = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        raise LifecycleError("invalid_stored_json") from None
    if not isinstance(result, expected):
        raise LifecycleError("invalid_stored_json_shape")
    return result


@contextmanager
def transaction(conn: sqlite3.Connection, *, write: bool = True) -> Iterator[None]:
    """One snapshot and one commit. Never silently commit a caller's work."""
    nested = conn.in_transaction
    name = "memory_lifecycle_" + uuid.uuid4().hex
    conn.execute(f"SAVEPOINT {name}" if nested else ("BEGIN IMMEDIATE" if write else "BEGIN"))
    try:
        yield
    except BaseException:
        if nested:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
        else:
            conn.rollback()
        raise
    else:
        if nested:
            conn.execute(f"RELEASE {name}")
        else:
            conn.commit()


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    # A typo must not silently create an empty database and appear successful.
    path = Path(db_path).expanduser().resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def require_schema(conn: sqlite3.Connection) -> None:
    needed = {"memory_atoms", "agent_memory_evidence", "memory_evidence_input_event_links",
              "memory_lifecycle_atom_evidence_links", "memory_portable_imports", "memory_refresh_checkpoints"}
    actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not needed <= actual:
        raise LifecycleError("memory_lifecycle_migration_required")
    if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise LifecycleError("foreign_keys_required")


def row_dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [col[0] for col in cursor.description or []]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def bounded_rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    names = [col[0] for col in cursor.description or []]
    rows = cursor.fetchmany(MAX_OBJECTS + 1)
    if len(rows) > MAX_OBJECTS:
        raise LifecycleError("project_too_large_split_export")
    return [dict(zip(names, row)) for row in rows]


def instance_namespace(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT namespace FROM memory_portable_identity WHERE singleton=1").fetchone()
    if row:
        return str(row[0])
    value = "paw:" + uuid.uuid4().hex
    conn.execute("INSERT INTO memory_portable_identity(singleton,namespace) VALUES (1,?)", (value,))
    return value


def excluded(conn: sqlite3.Connection, *, project: str, session_id: str = "", source_id: str = "") -> bool:
    # Called only after startup migrations. It deliberately never creates tables.
    return conn.execute("""SELECT 1 FROM memory_capture_exclusions WHERE project IN ('',?)
        AND ((target_kind='session' AND target_id=? AND ?!='')
          OR (target_kind='source' AND target_id=? AND ?!='')) LIMIT 1""",
        (project, session_id, session_id, source_id, source_id)).fetchone() is not None


def insert_row(conn: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    # Every identifier is application-owned, never read from an import bundle.
    allowed = {"input_events", "memory_state", "agent_memory_sources", "agent_memory_evidence",
               "memory_evidence_input_event_links", "memory_atoms", "memory_lifecycle_atom_evidence_links",
               "memory_evidence_admission_events", "memory_source_disposition_events"}
    if table not in allowed:
        raise LifecycleError("invalid_insert_target")
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if not set(values) <= columns:
        raise LifecycleError("incompatible_canonical_schema")
    names = list(values)
    sql = f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})"
    conn.execute(sql, tuple(values.values()))
