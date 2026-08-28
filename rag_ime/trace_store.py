"""Durable, append-only storage for canonical :class:`TraceEnvelope` records.

The observation journal is a useful discovery/progress projection, but it is
not the authority for a completed trace.  ``TraceStore`` keeps the validated
metadata-only envelope produced by a durable evaluator or vertical sandbox so
that a trace remains available after a temporary execution workspace and its
process have gone away.

This store deliberately has no relationship to EvalRun foreign keys.  An
EvalRun may reference a source-owned trace that is not yet (or never) present
in this local store; the evaluator and the trace authority retain independent
lifecycle semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from .db import apply_database_migrations, sqlite_connection
from .trace_runtime import TraceContractError, TraceEnvelope, validate_trace_envelope


_TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_TERMINAL_TRACE_STATUSES = frozenset({"completed", "failed", "cancelled"})


class TraceConflict(RuntimeError):
    """A stable trace identity was replayed with different canonical content."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = str(trace_id)
        super().__init__(
            f"Trace identity {self.trace_id!r} was rebound to different content"
        )


class TraceStore:
    """SQLite-backed append-only canonical TraceEnvelope store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        """Apply the shared schema migrations and return the schema version."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def persist(
        self,
        trace: TraceEnvelope | Mapping[str, object],
    ) -> dict[str, object]:
        """Validate and append one canonical envelope.

        Replaying the same canonical payload is idempotent.  Reusing its
        identity for any other payload raises :class:`TraceConflict`; no
        update path exists for an already persisted row.
        """

        payload, canonical, payload_hash = _canonical_payload(trace)
        trace_id = str(payload["traceId"])

        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT trace_id, source_kind, status, created_at_ms, updated_at_ms, "
                "payload_hash, payload_json FROM trace_envelopes WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_hash"]) != payload_hash
                    or str(existing["payload_json"]) != canonical
                ):
                    raise TraceConflict(trace_id)
                return _decode_payload(
                    str(existing["payload_json"]),
                    expected_hash=str(existing["payload_hash"]),
                    expected_trace_id=trace_id,
                    expected_source_kind=str(existing["source_kind"]),
                    expected_status=str(existing["status"]),
                    expected_created_at_ms=existing["created_at_ms"],
                    expected_updated_at_ms=existing["updated_at_ms"],
                )

            conn.execute(
                """
                INSERT INTO trace_envelopes(
                    trace_id, source_kind, status, created_at_ms, updated_at_ms,
                    payload_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    str(payload["sourceKind"]),
                    str(payload["status"]),
                    int(payload["createdAtMs"]),
                    int(payload["updatedAtMs"]),
                    payload_hash,
                    canonical,
                ),
            )
        return dict(payload)

    def get(self, trace_id: str) -> dict[str, object] | None:
        """Return one validated canonical envelope, or ``None`` if absent."""

        identifier = _required_trace_id(trace_id)
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = conn.execute(
                "SELECT trace_id, source_kind, status, created_at_ms, updated_at_ms, "
                "payload_hash, payload_json FROM trace_envelopes "
                "WHERE trace_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:
            return None
        return _decode_payload(
            str(row["payload_json"]),
            expected_hash=str(row["payload_hash"]),
            expected_trace_id=str(row["trace_id"]),
            expected_source_kind=str(row["source_kind"]),
            expected_status=str(row["status"]),
            expected_created_at_ms=row["created_at_ms"],
            expected_updated_at_ms=row["updated_at_ms"],
        )

    def list(self, *, limit: int | None = None) -> list[dict[str, object]]:
        """Return canonical traces in deterministic creation order.

        ``limit`` is optional for local callers that need the complete ledger;
        when supplied it is bounded to keep an accidental UI request from
        turning this projection into an unbounded read.
        """

        bounded = _optional_limit(limit)
        self.initialize()
        query = (
            "SELECT trace_id, source_kind, status, created_at_ms, updated_at_ms, "
            "payload_hash, payload_json FROM trace_envelopes "
            "ORDER BY created_at_ms ASC, trace_id ASC"
        )
        values: tuple[object, ...] = ()
        if bounded is not None:
            query += " LIMIT ?"
            values = (bounded,)
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(query, values).fetchall()
        return [
            _decode_payload(
                str(row["payload_json"]),
                expected_hash=str(row["payload_hash"]),
                expected_trace_id=str(row["trace_id"]),
                expected_source_kind=str(row["source_kind"]),
                expected_status=str(row["status"]),
                expected_created_at_ms=row["created_at_ms"],
                expected_updated_at_ms=row["updated_at_ms"],
            )
            for row in rows
        ]


def _canonical_payload(
    trace: TraceEnvelope | Mapping[str, object],
) -> tuple[dict[str, object], str, str]:
    if isinstance(trace, TraceEnvelope):
        payload = trace.to_dict()
    elif isinstance(trace, Mapping):
        payload = dict(trace)
        try:
            validate_trace_envelope(payload)
        except TraceContractError:
            raise
        except Exception as exc:  # keep the store's public error stable
            raise TraceContractError(str(exc)) from exc
    else:
        raise TypeError("trace must be a TraceEnvelope or mapping")

    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized = json.loads(canonical)
    except (TypeError, ValueError) as exc:
        raise TraceContractError("trace payload must be JSON serializable") from exc
    if not isinstance(normalized, dict):
        raise TraceContractError("trace payload must be an object")
    # Validate the JSON-shaped value that is actually persisted.  This closes
    # the gap between Python-only Mapping/tuple inputs and the wire contract.
    validate_trace_envelope(normalized)
    if normalized.get("status") not in _TERMINAL_TRACE_STATUSES:
        raise TraceContractError(
            "TraceStore accepts terminal canonical traces only"
        )
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return normalized, canonical, payload_hash


def _decode_payload(
    raw: str,
    *,
    expected_hash: str,
    expected_trace_id: str,
    expected_source_kind: str,
    expected_status: str,
    expected_created_at_ms: object,
    expected_updated_at_ms: object,
) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise TraceContractError("persisted trace payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TraceContractError("persisted trace payload is not an object")
    validate_trace_envelope(payload)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        raise TraceContractError("persisted trace payload hash does not match")
    if payload.get("traceId") != expected_trace_id:
        raise TraceContractError("persisted trace identity does not match its row")
    if payload.get("status") not in _TERMINAL_TRACE_STATUSES:
        raise TraceContractError("persisted trace payload must be terminal")
    if (
        payload.get("sourceKind") != expected_source_kind
        or payload.get("status") != expected_status
        or payload.get("createdAtMs") != expected_created_at_ms
        or payload.get("updatedAtMs") != expected_updated_at_ms
    ):
        raise TraceContractError("persisted trace row metadata does not match payload")
    return payload


def _required_trace_id(value: object) -> str:
    if not isinstance(value, str) or _TRACE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid trace_id")
    return value


def _optional_limit(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("trace list limit must be an integer")
    if not 1 <= value <= 500:
        raise ValueError("trace list limit must be between 1 and 500")
    return value
