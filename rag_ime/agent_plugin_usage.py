from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path

from .db import apply_database_migrations


_SCHEMA_VERSION = "paw.plugin-usage.v1"
_QUERY_SCHEMA_VERSION = "paw.plugin-usage-query.v1"
_RESOURCE_KINDS = frozenset({"extension", "tool", "command", "skill", "prompt", "theme"})
_ACTIVITIES = frozenset({"loaded", "invoked", "finished"})
_OUTCOMES = frozenset({"succeeded", "failed", "cancelled"})
_REQUIRED_FIELDS = frozenset({
    "schemaVersion",
    "eventId",
    "occurredAtMs",
    "sessionId",
    "packageId",
    "packageVersion",
    "resourceKind",
    "resourceId",
    "activity",
})
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"invocationId", "outcome", "durationMs"}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._:-]*$")
_PACKAGE_RE = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$")


class AgentPluginUsageStore:
    """Allowlist-only Package usage ledger and aggregate projection."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        connection_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._connection_factory = connection_factory

    def initialize(self) -> None:
        if self._connection_factory is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def record(self, raw: Mapping[str, object]) -> dict[str, object]:
        event = _validated_event(raw)
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM agent_plugin_usage_events WHERE event_id = ?",
                (event["eventId"],),
            ).fetchone()
            if existing is not None:
                projected = _event_payload(existing)
                if projected != event:
                    raise ValueError("plugin usage eventId was already used for a different event")
                return projected

            if event["activity"] == "finished":
                matching = conn.execute(
                    """
                    SELECT 1 FROM agent_plugin_usage_events
                    WHERE package_id = ? AND package_version = ?
                      AND resource_kind = ? AND resource_id = ?
                      AND session_id = ? AND invocation_id = ?
                      AND activity = 'invoked'
                    """,
                    (
                        event["packageId"],
                        event["packageVersion"],
                        event["resourceKind"],
                        event["resourceId"],
                        event["sessionId"],
                        event["invocationId"],
                    ),
                ).fetchone()
                if matching is None:
                    raise ValueError("plugin usage terminal requires a matching invoked event")

            conn.execute(
                """
                INSERT INTO agent_plugin_usage_events(
                    event_id, occurred_at_ms, session_id, package_id,
                    package_version, resource_kind, resource_id, activity,
                    invocation_id, outcome, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["eventId"],
                    event["occurredAtMs"],
                    event["sessionId"],
                    event["packageId"],
                    event["packageVersion"],
                    event["resourceKind"],
                    event["resourceId"],
                    event["activity"],
                    event.get("invocationId"),
                    event.get("outcome"),
                    event.get("durationMs"),
                ),
            )
        return event

    def query(
        self,
        *,
        package_id: str = "",
        resource_kind: str = "",
        session_id: str = "",
        since_ms: int | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        conditions: list[str] = []
        values: list[object] = []
        if package_id:
            conditions.append("package_id = ?")
            values.append(_package_id(package_id))
        if resource_kind:
            conditions.append("resource_kind = ?")
            values.append(_choice(resource_kind, "resourceKind", _RESOURCE_KINDS))
        if session_id:
            conditions.append("session_id = ?")
            values.append(_identifier(session_id, "sessionId", 240))
        if since_ms is not None:
            conditions.append("occurred_at_ms >= ?")
            values.append(_non_negative_integer(since_ms, "sinceMs"))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        bounded_limit = max(1, min(int(limit), 500))

        with self._connect() as conn:
            events = [
                _event_payload(row)
                for row in conn.execute(
                    "SELECT * FROM agent_plugin_usage_events"
                    + where
                    + " ORDER BY occurred_at_ms DESC, event_id DESC LIMIT ?",
                    (*values, bounded_limit),
                )
            ]
            aggregate_rows = conn.execute(
                """
                SELECT package_id, package_version, resource_kind, resource_id,
                       SUM(CASE WHEN activity = 'loaded' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN activity = 'invoked' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN activity = 'finished' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'succeeded' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'cancelled' THEN 1 ELSE 0 END),
                       AVG(CASE WHEN activity = 'finished' THEN duration_ms END),
                       MAX(CASE WHEN activity = 'loaded' THEN occurred_at_ms END),
                       MAX(CASE WHEN activity = 'invoked' THEN occurred_at_ms END)
                FROM agent_plugin_usage_events
                """
                + where
                + " GROUP BY package_id, package_version, resource_kind, resource_id"
                + " ORDER BY package_id, package_version, resource_kind, resource_id",
                values,
            ).fetchall()

        return {
            "schemaVersion": _QUERY_SCHEMA_VERSION,
            "events": events,
            "aggregates": [_aggregate_payload(row) for row in aggregate_rows],
        }

    def package_summary(
        self,
        package_id: str,
        *,
        package_version: str = "",
    ) -> dict[str, object]:
        resolved_package_id = _package_id(package_id)
        conditions = ["package_id = ?"]
        values: list[object] = [resolved_package_id]
        if package_version:
            conditions.append("package_version = ?")
            values.append(_version(package_version))
        where = " WHERE " + " AND ".join(conditions)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT CASE WHEN activity = 'loaded' THEN session_id END),
                       MAX(CASE WHEN activity = 'loaded' THEN occurred_at_ms END),
                       SUM(CASE WHEN activity = 'invoked' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'succeeded' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN outcome = 'cancelled' THEN 1 ELSE 0 END),
                       AVG(CASE WHEN activity = 'finished' THEN duration_ms END)
                FROM agent_plugin_usage_events
                """
                + where,
                values,
            ).fetchone()
            last = conn.execute(
                "SELECT * FROM agent_plugin_usage_events"
                + where
                + " AND activity = 'finished'"
                + " ORDER BY occurred_at_ms DESC, event_id DESC LIMIT 1",
                values,
            ).fetchone()
            started_at_ms = None
            if last is not None:
                started = conn.execute(
                    """
                    SELECT occurred_at_ms FROM agent_plugin_usage_events
                    WHERE session_id = ? AND package_id = ? AND package_version = ?
                      AND resource_kind = ? AND resource_id = ?
                      AND invocation_id = ? AND activity = 'invoked'
                    LIMIT 1
                    """,
                    (
                        last["session_id"],
                        last["package_id"],
                        last["package_version"],
                        last["resource_kind"],
                        last["resource_id"],
                        last["invocation_id"],
                    ),
                ).fetchone()
                started_at_ms = int(started[0]) if started is not None else None
        average = row[6] if row is not None else None
        return {
            "loadedSessionCount": int(row[0] or 0) if row is not None else 0,
            "lastLoadedAtMs": int(row[1]) if row is not None and row[1] is not None else None,
            "invocationCount": int(row[2] or 0) if row is not None else 0,
            "succeededCount": int(row[3] or 0) if row is not None else 0,
            "failedCount": int(row[4] or 0) if row is not None else 0,
            "cancelledCount": int(row[5] or 0) if row is not None else 0,
            "averageDurationMs": int(round(float(average))) if average is not None else None,
            "lastInvocation": (
                {
                    "resourceKind": str(last["resource_kind"]),
                    "resourceName": str(last["resource_id"]),
                    "sessionId": str(last["session_id"]),
                    "startedAtMs": started_at_ms,
                    "completedAtMs": int(last["occurred_at_ms"]),
                    "durationMs": int(last["duration_ms"]),
                    "status": str(last["outcome"]),
                }
                if last is not None
                else None
            ),
        }

    def route(self, arguments: Mapping[str, object]) -> dict[str, object]:
        since_raw = str(arguments.get("sinceMs") or "").strip()
        limit_raw = str(arguments.get("limit") or "").strip()
        try:
            since_ms = int(since_raw) if since_raw else None
            limit = int(limit_raw) if limit_raw else 100
        except ValueError as exc:
            raise ValueError("plugin usage query integers are invalid") from exc
        return self.query(
            package_id=str(arguments.get("packageId") or "").strip(),
            resource_kind=str(arguments.get("resourceKind") or "").strip(),
            session_id=str(arguments.get("sessionId") or "").strip(),
            since_ms=since_ms,
            limit=limit,
        )

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = (
            self._connection_factory()
            if self._connection_factory is not None
            else sqlite3.connect(self.db_path, timeout=10)
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if immediate:
                conn.commit()
        except Exception:
            if immediate:
                conn.rollback()
            raise
        finally:
            conn.close()


def _validated_event(raw: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("plugin usage event must be an object")
    keys = frozenset(str(key) for key in raw)
    unsupported = sorted(keys - _ALLOWED_FIELDS)
    if unsupported:
        raise ValueError("plugin usage event has unsupported fields: " + ", ".join(unsupported))
    missing = sorted(_REQUIRED_FIELDS - keys)
    if missing:
        raise ValueError("plugin usage event is missing fields: " + ", ".join(missing))
    if raw.get("schemaVersion") != _SCHEMA_VERSION:
        raise ValueError("unsupported plugin usage schemaVersion")

    activity = _choice(raw.get("activity"), "activity", _ACTIVITIES)
    resource_kind = _choice(raw.get("resourceKind"), "resourceKind", _RESOURCE_KINDS)
    event: dict[str, object] = {
        "schemaVersion": _SCHEMA_VERSION,
        "eventId": _identifier(raw.get("eventId"), "eventId", 240),
        "occurredAtMs": _non_negative_integer(raw.get("occurredAtMs"), "occurredAtMs"),
        "sessionId": _identifier(raw.get("sessionId"), "sessionId", 240),
        "packageId": _package_id(raw.get("packageId")),
        "packageVersion": _version(raw.get("packageVersion")),
        "resourceKind": resource_kind,
        "resourceId": _identifier(raw.get("resourceId"), "resourceId", 200),
        "activity": activity,
    }
    optional = keys - _REQUIRED_FIELDS
    expected_optional = {
        "loaded": frozenset(),
        "invoked": frozenset({"invocationId"}),
        "finished": frozenset({"invocationId", "outcome", "durationMs"}),
    }[activity]
    if optional != expected_optional:
        raise ValueError(f"plugin usage {activity} fields do not match the schema")
    if resource_kind in {"extension", "theme"} and activity != "loaded":
        raise ValueError(f"{resource_kind} usage supports loaded activity only")
    if resource_kind == "prompt" and activity == "finished":
        raise ValueError("prompt usage has no truthful terminal callback")
    if activity != "loaded":
        event["invocationId"] = _identifier(raw.get("invocationId"), "invocationId", 240)
    if activity == "finished":
        event["outcome"] = _choice(raw.get("outcome"), "outcome", _OUTCOMES)
        event["durationMs"] = _non_negative_integer(raw.get("durationMs"), "durationMs")
    return event


def _event_payload(row: sqlite3.Row) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": _SCHEMA_VERSION,
        "eventId": str(row["event_id"]),
        "occurredAtMs": int(row["occurred_at_ms"]),
        "sessionId": str(row["session_id"]),
        "packageId": str(row["package_id"]),
        "packageVersion": str(row["package_version"]),
        "resourceKind": str(row["resource_kind"]),
        "resourceId": str(row["resource_id"]),
        "activity": str(row["activity"]),
    }
    if row["invocation_id"] is not None:
        payload["invocationId"] = str(row["invocation_id"])
    if row["outcome"] is not None:
        payload["outcome"] = str(row["outcome"])
    if row["duration_ms"] is not None:
        payload["durationMs"] = int(row["duration_ms"])
    return payload


def _aggregate_payload(row: sqlite3.Row) -> dict[str, object]:
    average = row[10]
    return {
        "packageId": str(row[0]),
        "packageVersion": str(row[1]),
        "resourceKind": str(row[2]),
        "resourceId": str(row[3]),
        "loadedCount": int(row[4] or 0),
        "invocationCount": int(row[5] or 0),
        "terminalCount": int(row[6] or 0),
        "succeededCount": int(row[7] or 0),
        "failedCount": int(row[8] or 0),
        "cancelledCount": int(row[9] or 0),
        "averageDurationMs": (int(round(float(average))) if average is not None else None),
        "lastLoadedAtMs": (int(row[11]) if row[11] is not None else None),
        "lastInvokedAtMs": (int(row[12]) if row[12] is not None else None),
    }


def _identifier(value: object, field: str, maximum: int) -> str:
    text = str(value or "")
    if not text or len(text) > maximum or _IDENTIFIER_RE.fullmatch(text) is None:
        raise ValueError(f"plugin usage {field} is invalid")
    return text


def _package_id(value: object) -> str:
    text = str(value or "")
    if not text or len(text) > 200 or _PACKAGE_RE.fullmatch(text) is None:
        raise ValueError("plugin usage packageId is invalid")
    return text


def _version(value: object) -> str:
    text = str(value or "")
    if not text or len(text) > 80 or _VERSION_RE.fullmatch(text) is None:
        raise ValueError("plugin usage packageVersion is invalid")
    return text


def _choice(value: object, field: str, choices: frozenset[str]) -> str:
    text = str(value or "")
    if text not in choices:
        raise ValueError(f"plugin usage {field} is invalid")
    return text


def _non_negative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"plugin usage {field} must be a non-negative integer")
    return value
