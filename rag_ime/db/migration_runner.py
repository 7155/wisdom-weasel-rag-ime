from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MIGRATION_NAME_RE = re.compile(r"^(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class MigrationChecksumError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationResult:
    applied_versions: tuple[int, ...]
    current_version: int
    migration_count: int

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": "rag-ime.sqlite-migrations.v1",
            "appliedVersions": list(self.applied_versions),
            "currentVersion": self.current_version,
            "migrationCount": self.migration_count,
        }


MigrationHook = Callable[[sqlite3.Connection], None]


def apply_database_migrations(
    conn: sqlite3.Connection,
    *,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    applied_at_ms: int | None = None,
) -> MigrationResult:
    migrations = load_migrations(migrations_dir)
    _ensure_migration_table(conn)
    applied = {
        int(row[0]): str(row[1])
        for row in conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
    }
    for migration in migrations:
        existing_checksum = applied.get(migration.version)
        if existing_checksum is not None and existing_checksum != migration.checksum:
            raise MigrationChecksumError(
                f"migration {migration.version:04d} checksum changed: "
                f"database={existing_checksum} source={migration.checksum}"
            )

    newly_applied: list[int] = []
    timestamp = int(time.time() * 1000) if applied_at_ms is None else int(applied_at_ms)
    for migration in migrations:
        if migration.version in applied:
            continue
        hook = _MIGRATION_HOOKS.get(migration.version)
        with conn:
            if hook is not None:
                hook(conn)
            if migration.sql.strip():
                _execute_sql_script(conn, migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at_ms, checksum) VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, timestamp, migration.checksum),
            )
        newly_applied.append(migration.version)
        applied[migration.version] = migration.checksum
    return MigrationResult(
        applied_versions=tuple(newly_applied),
        current_version=max(applied, default=0),
        migration_count=len(migrations),
    )


def migration_status(
    conn: sqlite3.Connection,
    *,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
) -> dict[str, object]:
    migrations = load_migrations(migrations_dir)
    _ensure_migration_table(conn)
    rows = conn.execute(
        "SELECT version, name, applied_at_ms, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    source = {migration.version: migration for migration in migrations}
    items = [
        {
            "version": int(row[0]),
            "name": str(row[1]),
            "appliedAtMs": int(row[2]),
            "checksum": str(row[3]),
            "sourceChecksum": source.get(int(row[0])).checksum if int(row[0]) in source else "",
            "checksumMatches": int(row[0]) in source and str(row[3]) == source[int(row[0])].checksum,
        }
        for row in rows
    ]
    applied_versions = {int(row[0]) for row in rows}
    return {
        "schemaVersion": "rag-ime.sqlite-migration-status.v1",
        "currentVersion": max(applied_versions, default=0),
        "latestVersion": max(source, default=0),
        "pendingVersions": [item.version for item in migrations if item.version not in applied_versions],
        "items": items,
        "ok": all(bool(item["checksumMatches"]) for item in items),
    }


def load_migrations(migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR) -> tuple[Migration, ...]:
    root = Path(migrations_dir)
    migrations: list[Migration] = []
    seen_versions: set[int] = set()
    for path in sorted(root.glob("*.sql")):
        match = MIGRATION_NAME_RE.match(path.name)
        if match is None:
            continue
        version = int(match.group("version"))
        if version in seen_versions:
            raise ValueError(f"duplicate migration version: {version:04d}")
        seen_versions.add(version)
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                sql=sql,
                checksum=checksum,
            )
        )
    return tuple(migrations)


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at_ms INTEGER NOT NULL,
            checksum TEXT NOT NULL
        )
        """
    )


def _execute_sql_script(conn: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        if statement.strip():
            conn.execute(statement)
        statement = ""
    remaining = "\n".join(
        line for line in statement.splitlines() if not line.strip().startswith("--")
    ).strip()
    if remaining:
        raise ValueError("incomplete SQL migration statement")


def _canonicalize_memory_feedback_events(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "memory_feedback_events"):
        return
    columns = {str(row[1]): row for row in conn.execute("PRAGMA table_info(memory_feedback_events)")}
    candidate_text = columns.get("candidate_text")
    candidate_source = columns.get("candidate_source")
    if candidate_text is None or candidate_source is None:
        raise RuntimeError("memory_feedback_events is missing candidate columns")
    if str(candidate_text[4] or "") == "''" and str(candidate_source[4] or "") == "'unknown'":
        return
    legacy = "memory_feedback_events_legacy_0001"
    conn.execute(f"DROP TABLE IF EXISTS {legacy}")
    conn.execute(f"ALTER TABLE memory_feedback_events RENAME TO {legacy}")
    conn.execute(
        """
        CREATE TABLE memory_feedback_events (
            id TEXT PRIMARY KEY,
            candidate_id TEXT,
            candidate_text TEXT NOT NULL DEFAULT '',
            candidate_source TEXT NOT NULL DEFAULT 'unknown',
            action TEXT NOT NULL,
            context_hash TEXT,
            front_app_bundle_id TEXT,
            raw_input TEXT,
            preedit TEXT,
            committed_tail TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO memory_feedback_events(
            id, candidate_id, candidate_text, candidate_source, action,
            context_hash, front_app_bundle_id, raw_input, preedit,
            committed_tail, metadata_json, created_at_ms
        )
        SELECT id, candidate_id, COALESCE(candidate_text, ''),
               COALESCE(NULLIF(candidate_source, ''), 'unknown'), action,
               context_hash, front_app_bundle_id, raw_input, preedit,
               committed_tail, COALESCE(metadata_json, '{{}}'), created_at_ms
        FROM {legacy}
        """
    )
    conn.execute(f"DROP TABLE {legacy}")


def _migrate_context_group_columns(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "input_events"):
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(input_events)")}
    if "context_group_id" not in columns:
        conn.execute("ALTER TABLE input_events ADD COLUMN context_group_id TEXT NOT NULL DEFAULT ''")
    if "context_group_level" not in columns:
        conn.execute("ALTER TABLE input_events ADD COLUMN context_group_level TEXT NOT NULL DEFAULT 'app'")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_input_events_context_group "
        "ON input_events(context_group_id, created_at_ms DESC)"
    )


def _canonicalize_input_events(conn: sqlite3.Connection) -> None:
    """Bring early input-event tables up to the legacy-core contract in place."""
    if not _table_exists(conn, "input_events"):
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(input_events)")}
    additions = (
        ("recent_context", "TEXT NOT NULL DEFAULT ''"),
        ("preedit", "TEXT NOT NULL DEFAULT ''"),
        ("schema_id", "TEXT NOT NULL DEFAULT 'default'"),
        ("app", "TEXT NOT NULL DEFAULT 'manual'"),
        ("project", "TEXT NOT NULL DEFAULT ''"),
        ("candidate_rank", "INTEGER"),
        ("provider_name", "TEXT NOT NULL DEFAULT 'local'"),
        ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("context_group_id", "TEXT NOT NULL DEFAULT ''"),
        ("context_group_level", "TEXT NOT NULL DEFAULT 'app'"),
    )
    for name, declaration in additions:
        if name not in columns:
            conn.execute(f"ALTER TABLE input_events ADD COLUMN {name} {declaration}")


def _migrate_agent_identity_column(conn: sqlite3.Connection) -> None:
    """Add the Agent identity column without assuming migration state survived a reset."""

    if not _table_exists(conn, "agent_sessions"):
        return
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(agent_sessions)")}
    if "agent_id" not in columns:
        conn.execute("ALTER TABLE agent_sessions ADD COLUMN agent_id TEXT NOT NULL DEFAULT ''")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


_MIGRATION_HOOKS: dict[int, MigrationHook] = {
    1: _canonicalize_memory_feedback_events,
    3: _migrate_context_group_columns,
    7: _canonicalize_input_events,
    # Versions 26-27 are already in use by the live control-center line.
    # Keep the memory-graph compatibility hook on its collision-free version.
    29: _migrate_agent_identity_column,
}
