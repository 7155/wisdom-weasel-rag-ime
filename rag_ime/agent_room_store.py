from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


class ShadowObservationConflict(RuntimeError):
    """A shadow identity was reused for different immutable content."""


class RoomShadowLedgerStore:
    """Append-only Room V2 observations with no execution or delivery surface.

    The canonical Room contracts belong to the Kernel. This store only persists
    their opaque JSON projections and the legacy paths that observed them.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            result = apply_database_migrations(conn)
        return result.current_version

    def record_observation(
        self,
        observation: Mapping[str, object],
        *,
        source_kind: str,
        source_id: str,
        observed_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        normalized = _normalize_observation(observation)
        source_kind = _required_text(source_kind, "source_kind")
        source_id = _required_text(source_id, "source_id")
        observed_at_ms = _non_negative_int(observed_at_ms, "observed_at_ms")
        encoded = _canonical_json(normalized)
        content_hash = _sha256(encoded)
        identity = (
            str(normalized["rootId"]),
            str(normalized["triggerId"]),
            str(normalized["recordKind"]),
            str(normalized["entityId"]),
        )
        observation_id = f"room-shadow:{_sha256(_canonical_json(identity))[:32]}"

        with self._connect(immediate=True) as conn:
            existing_ref = conn.execute(
                """
                SELECT observation_id FROM room_v2_shadow_legacy_refs
                WHERE source_kind = ? AND source_id = ?
                """,
                (source_kind, source_id),
            ).fetchone()
            if existing_ref is not None and str(existing_ref["observation_id"]) != observation_id:
                raise ShadowObservationConflict(
                    "legacy Room source is already bound to another shadow observation"
                )

            row = conn.execute(
                """
                SELECT * FROM room_v2_shadow_observations
                WHERE root_id = ? AND trigger_id = ?
                  AND record_kind = ? AND entity_id = ?
                """,
                identity,
            ).fetchone()
            created = row is None
            if row is None:
                sequence = int(
                    conn.execute(
                        """
                        SELECT COALESCE(MAX(sequence), 0) + 1
                        FROM room_v2_shadow_observations WHERE root_id = ?
                        """,
                        (identity[0],),
                    ).fetchone()[0]
                )
                conn.execute(
                    """
                    INSERT INTO room_v2_shadow_observations(
                        id, root_id, task_id, dispatch_id, trigger_id,
                        record_kind, entity_id, sequence, content_hash,
                        payload_json, first_observed_at_ms, last_observed_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        identity[0],
                        str(normalized.get("taskId") or ""),
                        str(normalized.get("dispatchId") or ""),
                        identity[1],
                        identity[2],
                        identity[3],
                        sequence,
                        content_hash,
                        encoded,
                        observed_at_ms,
                        observed_at_ms,
                    ),
                )
            elif str(row["content_hash"]) != content_hash:
                raise ShadowObservationConflict(
                    "canonical Room shadow identity was reused with different content"
                )
            else:
                observation_id = str(row["id"])
                conn.execute(
                    """
                    UPDATE room_v2_shadow_observations
                    SET last_observed_at_ms = MAX(last_observed_at_ms, ?)
                    WHERE id = ?
                    """,
                    (observed_at_ms, observation_id),
                )

            conn.execute(
                """
                INSERT INTO room_v2_shadow_legacy_refs(
                    source_kind, source_id, observation_id, observed_at_ms
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_kind, source_id) DO UPDATE SET
                    observed_at_ms = MAX(observed_at_ms, excluded.observed_at_ms)
                WHERE observation_id = excluded.observation_id
                """,
                (source_kind, source_id, observation_id, observed_at_ms),
            )
            row = self._observation_row(conn, observation_id)
            legacy_refs = self._legacy_refs(conn, observation_id)
        return _observation_payload(row, legacy_refs), created

    def quarantine(
        self,
        *,
        source_kind: str,
        source_id: str,
        reason_code: str,
        raw_payload: Mapping[str, object],
        observed_at_ms: int,
        root_id: str = "",
    ) -> tuple[dict[str, object], bool]:
        source_kind = _required_text(source_kind, "source_kind")
        source_id = _required_text(source_id, "source_id")
        reason_code = _required_text(reason_code, "reason_code")
        observed_at_ms = _non_negative_int(observed_at_ms, "observed_at_ms")
        root_id = str(root_id or "").strip()
        encoded = _canonical_json(dict(raw_payload))
        raw_hash = _sha256(encoded)
        identity = (source_kind, source_id, reason_code, raw_hash)
        quarantine_id = f"room-shadow-quarantine:{_sha256(_canonical_json(identity))[:32]}"

        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM room_v2_shadow_quarantine
                WHERE source_kind = ? AND source_id = ?
                  AND reason_code = ? AND raw_payload_hash = ?
                """,
                identity,
            ).fetchone()
            created = row is None
            if row is None:
                conn.execute(
                    """
                    INSERT INTO room_v2_shadow_quarantine(
                        id, source_kind, source_id, root_id, reason_code,
                        raw_payload_hash, raw_payload_json,
                        first_observed_at_ms, last_observed_at_ms, occurrence_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        quarantine_id,
                        source_kind,
                        source_id,
                        root_id,
                        reason_code,
                        raw_hash,
                        encoded,
                        observed_at_ms,
                        observed_at_ms,
                    ),
                )
            else:
                quarantine_id = str(row["id"])
                if root_id and str(row["root_id"] or "") not in {"", root_id}:
                    raise ShadowObservationConflict(
                        "quarantined Room source was reused with another root"
                    )
                conn.execute(
                    """
                    UPDATE room_v2_shadow_quarantine
                    SET root_id = CASE WHEN root_id = '' THEN ? ELSE root_id END,
                        last_observed_at_ms = MAX(last_observed_at_ms, ?),
                        occurrence_count = occurrence_count + 1
                    WHERE id = ?
                    """,
                    (root_id, observed_at_ms, quarantine_id),
                )
            row = conn.execute(
                "SELECT * FROM room_v2_shadow_quarantine WHERE id = ?",
                (quarantine_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("Room shadow quarantine write did not persist")
        return _quarantine_payload(row), created

    def replay_root(self, root_id: str) -> list[dict[str, object]]:
        root_id = _required_text(root_id, "root_id")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM room_v2_shadow_observations
                WHERE root_id = ? ORDER BY sequence ASC
                """,
                (root_id,),
            ).fetchall()
            return [
                _observation_payload(row, self._legacy_refs(conn, str(row["id"])))
                for row in rows
            ]

    @staticmethod
    def _observation_row(conn: sqlite3.Connection, observation_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM room_v2_shadow_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("Room shadow observation write did not persist")
        return row

    @staticmethod
    def _legacy_refs(conn: sqlite3.Connection, observation_id: str) -> list[sqlite3.Row]:
        return conn.execute(
            """
            SELECT source_kind, source_id FROM room_v2_shadow_legacy_refs
            WHERE observation_id = ? ORDER BY source_kind, source_id
            """,
            (observation_id,),
        ).fetchall()

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _normalize_observation(observation: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(observation)
    validate_contract(normalized, "room-shadow-observation.v1.json")
    for key in ("rootId", "triggerId", "recordKind", "entityId"):
        normalized[key] = _required_text(normalized.get(key), key)
    normalized["taskId"] = str(normalized.get("taskId") or "").strip()
    normalized["dispatchId"] = str(normalized.get("dispatchId") or "").strip()
    payload = normalized.get("payload")
    if not isinstance(payload, Mapping):  # kept explicit for static type narrowing
        raise ValueError("Room shadow payload must be an object")
    normalized["payload"] = dict(payload)
    return normalized


def _observation_payload(
    row: sqlite3.Row,
    legacy_refs: list[sqlite3.Row],
) -> dict[str, object]:
    observation = json.loads(str(row["payload_json"]))
    return {
        "id": str(row["id"]),
        "rootId": str(row["root_id"]),
        "taskId": str(row["task_id"] or ""),
        "dispatchId": str(row["dispatch_id"] or ""),
        "triggerId": str(row["trigger_id"]),
        "recordKind": str(row["record_kind"]),
        "entityId": str(row["entity_id"]),
        "sequence": int(row["sequence"]),
        "contentHash": str(row["content_hash"]),
        "payload": dict(observation["payload"]),
        "firstObservedAtMs": int(row["first_observed_at_ms"]),
        "lastObservedAtMs": int(row["last_observed_at_ms"]),
        "legacyRefs": [
            {"sourceKind": str(ref["source_kind"]), "sourceId": str(ref["source_id"])}
            for ref in legacy_refs
        ],
    }


def _quarantine_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "sourceKind": str(row["source_kind"]),
        "sourceId": str(row["source_id"]),
        "rootId": str(row["root_id"] or ""),
        "reasonCode": str(row["reason_code"]),
        "rawPayloadHash": str(row["raw_payload_hash"]),
        "rawPayload": json.loads(str(row["raw_payload_json"])),
        "firstObservedAtMs": int(row["first_observed_at_ms"]),
        "lastObservedAtMs": int(row["last_observed_at_ms"]),
        "occurrenceCount": int(row["occurrence_count"]),
    }


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Room shadow payload must be JSON serializable") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _non_negative_int(value: object, field: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized
