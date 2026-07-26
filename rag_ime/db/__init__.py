"""Versioned SQLite schema ownership for RAG-IME."""

from .connection import sqlite_connection
from .migration_runner import (
    MigrationChecksumError,
    MigrationResult,
    apply_database_migrations,
    latest_migration_version,
    migration_status,
)

__all__ = [
    "MigrationChecksumError",
    "MigrationResult",
    "apply_database_migrations",
    "latest_migration_version",
    "migration_status",
    "sqlite_connection",
]
