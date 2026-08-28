"""Small SQLite ledger for Host-owned SandboxRun records."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from .db import apply_database_migrations, sqlite_connection
from .trace_runtime import SandboxRun, validate_sandbox_run


class SandboxRunConflict(RuntimeError):
    """A SandboxRun id already belongs to another payload."""


class SandboxRunStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def persist(
        self,
        run: SandboxRun | Mapping[str, object],
    ) -> dict[str, object]:
        payload = run.to_dict() if isinstance(run, SandboxRun) else dict(run)
        validate_sandbox_run(payload)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        sandbox_run_id = str(payload["sandboxRunId"])

        self.initialize()
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO sandbox_runs(
                        sandbox_run_id, app_id, status, created_at_ms,
                        updated_at_ms, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sandbox_run_id,
                        str(payload["appId"]),
                        str(payload["status"]),
                        int(payload["createdAtMs"]),
                        int(payload["updatedAtMs"]),
                        canonical,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = conn.execute(
                    "SELECT payload_json FROM sandbox_runs WHERE sandbox_run_id = ?",
                    (sandbox_run_id,),
                ).fetchone()
                if existing is not None and str(existing[0]) == canonical:
                    return payload
                raise SandboxRunConflict(sandbox_run_id) from exc
        return payload

    def get(self, sandbox_run_id: str) -> dict[str, object] | None:
        self.initialize()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM sandbox_runs WHERE sandbox_run_id = ?",
                (sandbox_run_id,),
            ).fetchone()
        return None if row is None else dict(json.loads(str(row[0])))

    def list(self, *, limit: int | None = None) -> list[dict[str, object]]:
        self.initialize()
        query = (
            "SELECT payload_json FROM sandbox_runs "
            "ORDER BY created_at_ms DESC, sandbox_run_id DESC"
        )
        values: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            values = (limit,)
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(query, values).fetchall()
        return [dict(json.loads(str(row[0]))) for row in rows]

    def count(self) -> int:
        self.initialize()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM sandbox_runs").fetchone()
        return int(row[0]) if row else 0
