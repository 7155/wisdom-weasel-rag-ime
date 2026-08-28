from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Mapping

from .db import apply_database_migrations, sqlite_connection
from .trace_runtime import EvalRun, validate_eval_run


class EvalRunConflict(RuntimeError):
    """A stable EvalRun identity was rebound to different content."""


class EvalRunStore:
    """Append-only local persistence for validated Trace EvalRun envelopes."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def persist(self, run: EvalRun | Mapping[str, object]) -> dict[str, object]:
        payload = _validated_payload(run)
        canonical = _canonical_json(payload)
        eval_run_id = str(payload["evalRunId"])
        payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        trace_ids = _unique_trace_ids(payload["traceIds"])

        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT payload_hash, payload_json FROM eval_runs WHERE eval_run_id = ?",
                (eval_run_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_hash"]) != payload_hash or str(existing["payload_json"]) != canonical:
                    raise EvalRunConflict(
                        f"EvalRun identity {eval_run_id!r} was rebound to different content"
                    )
                return _decode_payload(str(existing["payload_json"]))

            conn.execute(
                """
                INSERT INTO eval_runs(
                    eval_run_id, created_at_ms, updated_at_ms, mode,
                    metric_authority, status, payload_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_run_id,
                    int(payload["createdAtMs"]),
                    int(payload["updatedAtMs"]),
                    str(payload["mode"]),
                    str(payload["metricAuthority"]),
                    str(payload["status"]),
                    payload_hash,
                    canonical,
                ),
            )
            conn.executemany(
                "INSERT INTO eval_run_trace_refs(eval_run_id, trace_id) VALUES (?, ?)",
                [(eval_run_id, trace_id) for trace_id in trace_ids],
            )
        return dict(payload)

    def get(self, eval_run_id: str) -> dict[str, object] | None:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                "SELECT payload_json FROM eval_runs WHERE eval_run_id = ?",
                (str(eval_run_id),),
            ).fetchone()
        return _decode_payload(str(row["payload_json"])) if row is not None else None

    def list(self) -> list[dict[str, object]]:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM eval_runs ORDER BY created_at_ms, eval_run_id"
            ).fetchall()
        return [_decode_payload(str(row["payload_json"])) for row in rows]

    def for_trace(self, trace_id: str) -> list[dict[str, object]]:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                """
                SELECT runs.payload_json
                FROM eval_runs AS runs
                JOIN eval_run_trace_refs AS refs
                  ON refs.eval_run_id = runs.eval_run_id
                WHERE refs.trace_id = ?
                ORDER BY runs.created_at_ms, runs.eval_run_id
                """,
                (str(trace_id),),
            ).fetchall()
        return [_decode_payload(str(row["payload_json"])) for row in rows]

    def recent_for_trace(
        self,
        trace_id: str,
        *,
        limit: int = 100,
    ) -> tuple[list[dict[str, object]], int]:
        """Return a bounded newest-first page plus the authoritative count."""

        safe_limit = int(limit)
        if safe_limit < 1 or safe_limit > 500:
            raise ValueError("EvalRun trace page limit must be between 1 and 500")
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS total FROM eval_run_trace_refs WHERE trace_id = ?",
                (str(trace_id),),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT runs.payload_json
                FROM eval_runs AS runs
                JOIN eval_run_trace_refs AS refs
                  ON refs.eval_run_id = runs.eval_run_id
                WHERE refs.trace_id = ?
                ORDER BY runs.created_at_ms DESC, runs.eval_run_id DESC
                LIMIT ?
                """,
                (str(trace_id), safe_limit),
            ).fetchall()
        total = int(total_row["total"]) if total_row is not None else 0
        return (
            [_decode_payload(str(row["payload_json"])) for row in rows],
            total,
        )


def _validated_payload(run: EvalRun | Mapping[str, object]) -> dict[str, object]:
    if isinstance(run, EvalRun):
        payload = run.to_dict()
    elif isinstance(run, Mapping):
        payload = dict(run)
        validate_eval_run(payload)
    else:
        raise TypeError("run must be an EvalRun or mapping")
    return payload


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _unique_trace_ids(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("validated EvalRun traceIds must be a sequence")
    result: list[str] = []
    for trace_id in value:
        normalized = str(trace_id)
        if normalized not in result:
            result.append(normalized)
    return result


def _decode_payload(raw: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("persisted EvalRun payload is not an object")
    validate_eval_run(value)
    return value
