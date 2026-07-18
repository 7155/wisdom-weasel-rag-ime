from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations
from .memory_ingest import normalize_text
from .memory_projection import RETRIEVAL_DOCS_PROJECTION, enqueue_memory_projection
from .sensitive_content import contains_sensitive_content
from .text_utils import compact_whitespace, now_ms, truncate_text

if TYPE_CHECKING:
    from .personal_context_observability import PersonalContextObservability


DAILY_ACTIVITY_TIMELINE_SCHEMA_VERSION = "rag-ime.daily-activity-timeline.v1"
DEFAULT_SEGMENT_GAP_MS = 30 * 60 * 1_000

_INTERNAL_EVENT_SOURCES = frozenset(
    {
        "api_core_optimizer",
        "api_lexicon_optimizer",
        "squirrel_rime_sidecar",
        "vcp_memory_generator",
        "ime_demo_fixture",
    }
)


class StaleActivityTimelineError(ValueError):
    """The reviewed draft no longer represents the current input-event set."""


@dataclass(frozen=True)
class ActivityTimelineSegment:
    segment_id: str
    position: int
    app: str
    source_kinds: tuple[str, ...]
    context_group_ids: tuple[str, ...]
    start_ms: int
    end_ms: int
    event_count: int
    source_event_ids: tuple[int, ...]
    source_event_hash: str
    summary: str
    redacted_event_count: int

    def payload(self) -> dict[str, object]:
        return {
            "segmentId": self.segment_id,
            "position": self.position,
            "app": self.app,
            "sourceKinds": list(self.source_kinds),
            "contextGroupIds": list(self.context_group_ids),
            "startMs": self.start_ms,
            "endMs": self.end_ms,
            "eventCount": self.event_count,
            "sourceEventIds": list(self.source_event_ids),
            "sourceEventHash": self.source_event_hash,
            "summary": self.summary,
            "redactedEventCount": self.redacted_event_count,
        }


@dataclass(frozen=True)
class _ActivityEvent:
    event_id: int
    created_at_ms: int
    source: str
    text: str
    recent_context: str
    preedit: str
    app: str
    project: str
    context_group_id: str
    context_group_level: str


class DailyActivityTimelineStore:
    """Derive reviewable cross-app daily activity without creating user facts."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        project: str = "",
        timezone_name: str = "",
        segment_gap_ms: int = DEFAULT_SEGMENT_GAP_MS,
        observability: PersonalContextObservability | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.project = compact_whitespace(project)
        self.timezone = _resolve_timezone(timezone_name)
        self.timezone_name = _timezone_name(self.timezone)
        self.segment_gap_ms = max(60_000, int(segment_gap_ms))
        self.observability = observability

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def projects_for_date(self, timeline_date: str) -> tuple[str, ...]:
        day = _validated_date(timeline_date)
        start_ms, end_ms = _day_bounds_ms(day, self.timezone)
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT e.project
                FROM input_events e
                LEFT JOIN memory_state s ON s.event_id = e.id
                WHERE e.created_at_ms >= ? AND e.created_at_ms < ?
                  AND COALESCE(s.deleted, 0) = 0
                  AND e.source NOT IN ({_placeholders(_INTERNAL_EVENT_SOURCES)})
                ORDER BY e.project
                """,
                (start_ms, end_ms, *sorted(_INTERNAL_EVENT_SOURCES)),
            ).fetchall()
        projects = tuple(str(row["project"] or "") for row in rows)
        if self.project:
            return tuple(value for value in projects if value == self.project)
        return projects

    def build_draft(
        self,
        timeline_date: str,
        *,
        generated_at_ms: int | None = None,
    ) -> dict[str, object]:
        day = _validated_date(timeline_date)
        timestamp = now_ms() if generated_at_ms is None else max(0, int(generated_at_ms))
        self.initialize()
        with self._connect(immediate=True) as conn:
            events = self._events(conn, day)
            if not events:
                return {
                    "schemaVersion": "rag-ime.daily-activity-timeline-build.v1",
                    "ok": True,
                    "created": False,
                    "status": "no_events",
                    "project": self.project,
                    "date": day.isoformat(),
                    "timeline": {},
                }
            event_hash = _event_hash(events)
            existing = conn.execute(
                """
                SELECT * FROM daily_activity_timelines
                WHERE project = ? AND timeline_date = ? AND source_event_hash = ?
                """,
                (self.project, day.isoformat(), event_hash),
            ).fetchone()
            if existing is not None and str(existing["status"]) != "superseded":
                timeline = _timeline_payload(existing)
                validate_contract(timeline, "daily-activity-timeline.v1.json")
                return {
                    "schemaVersion": "rag-ime.daily-activity-timeline-build.v1",
                    "ok": True,
                    "created": False,
                    "status": str(existing["status"]),
                    "project": self.project,
                    "date": day.isoformat(),
                    "timeline": timeline,
                }

            segments = _segments(
                events,
                timezone=self.timezone,
                max_gap_ms=self.segment_gap_ms,
            )
            summary = _timeline_summary(segments, timezone=self.timezone)
            timeline_id = (
                "activity-timeline:"
                f"{_stable_digest(self.project, day.isoformat(), event_hash)[:28]}"
            )
            source_ids = [event.event_id for event in events]
            segments_json = json.dumps(
                [segment.payload() for segment in segments],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            metadata = {
                "derivedFrom": "input_events",
                "segmentGapMs": self.segment_gap_ms,
                "longTermFact": False,
                "automaticPromotion": False,
                "explicitApprovalRequired": True,
            }
            conn.execute(
                """
                UPDATE daily_activity_timelines
                SET status = 'superseded', updated_at_ms = ?
                WHERE project = ? AND timeline_date = ? AND status = 'draft'
                  AND source_event_hash <> ?
                """,
                (timestamp, self.project, day.isoformat(), event_hash),
            )
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO daily_activity_timelines(
                        timeline_id, project, timeline_date, timezone, status,
                        source_event_ids_json, source_event_hash, segments_json,
                        summary_text, event_count, segment_count, metadata_json,
                        created_at_ms, updated_at_ms
                    ) VALUES (
                        ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        timeline_id,
                        self.project,
                        day.isoformat(),
                        self.timezone_name,
                        json.dumps(source_ids, separators=(",", ":")),
                        event_hash,
                        segments_json,
                        summary,
                        len(events),
                        len(segments),
                        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                timeline_id = str(existing["timeline_id"])
                conn.execute(
                    """
                    UPDATE daily_activity_timelines
                    SET status = 'draft', timezone = ?,
                        source_event_ids_json = ?, segments_json = ?,
                        summary_text = ?, event_count = ?, segment_count = ?,
                        approved_book_id = '', approved_by = '',
                        approved_at_ms = NULL, rejection_reason = '',
                        metadata_json = ?, updated_at_ms = ?
                    WHERE timeline_id = ?
                    """,
                    (
                        self.timezone_name,
                        json.dumps(source_ids, separators=(",", ":")),
                        segments_json,
                        summary,
                        len(events),
                        len(segments),
                        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                        timestamp,
                        timeline_id,
                    ),
                )
            row = conn.execute(
                "SELECT * FROM daily_activity_timelines WHERE timeline_id = ?",
                (timeline_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("daily activity timeline draft was not persisted")
        timeline = _timeline_payload(row)
        validate_contract(timeline, "daily-activity-timeline.v1.json")
        return {
            "schemaVersion": "rag-ime.daily-activity-timeline-build.v1",
            "ok": True,
            "created": True,
            "status": "draft",
            "project": self.project,
            "date": day.isoformat(),
            "timeline": timeline,
        }

    def review(self, timeline_id: str) -> dict[str, object]:
        identifier = _required_text(timeline_id, "timeline_id")
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM daily_activity_timelines
                WHERE timeline_id = ? AND project = ?
                """,
                (identifier, self.project),
            ).fetchone()
        if row is None:
            raise ValueError("daily activity timeline does not exist in this project")
        payload = _timeline_payload(row)
        validate_contract(payload, "daily-activity-timeline.v1.json")
        return payload

    def latest(
        self,
        timeline_date: str,
        *,
        status: str = "",
    ) -> dict[str, object] | None:
        day = _validated_date(timeline_date)
        state = compact_whitespace(status)
        if state and state not in {"draft", "approved", "rejected", "superseded"}:
            raise ValueError("unsupported timeline status")
        self.initialize()
        query = """
            SELECT * FROM daily_activity_timelines
            WHERE project = ? AND timeline_date = ?
        """
        params: list[object] = [self.project, day.isoformat()]
        if state:
            query += " AND status = ?"
            params.append(state)
        query += """
            ORDER BY
              CASE status
                WHEN 'draft' THEN 0
                WHEN 'approved' THEN 1
                WHEN 'rejected' THEN 2
                ELSE 3
              END,
              updated_at_ms DESC, timeline_id DESC
            LIMIT 1
        """
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        payload = _timeline_payload(row)
        validate_contract(payload, "daily-activity-timeline.v1.json")
        return payload

    def approve(
        self,
        timeline_id: str,
        *,
        expected_source_event_hash: str,
        approved_by: str,
        confirm_text: str,
        approved_at_ms: int | None = None,
    ) -> dict[str, object]:
        identifier = _required_text(timeline_id, "timeline_id")
        expected_hash = _required_text(
            expected_source_event_hash,
            "expected_source_event_hash",
        )
        actor = _required_text(approved_by, "approved_by")
        if compact_whitespace(confirm_text).lower() != "approve":
            raise ValueError("confirm_text must be approve")
        timestamp = now_ms() if approved_at_ms is None else max(0, int(approved_at_ms))
        self.initialize()
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM daily_activity_timelines
                WHERE timeline_id = ? AND project = ?
                """,
                (identifier, self.project),
            ).fetchone()
            if row is None:
                raise ValueError("daily activity timeline does not exist in this project")
            if str(row["source_event_hash"]) != expected_hash:
                raise StaleActivityTimelineError(
                    "timeline approval hash does not match the reviewed draft"
                )
            if str(row["status"]) == "approved":
                payload = _timeline_payload(row)
                validate_contract(payload, "daily-activity-timeline.v1.json")
                return payload
            if str(row["status"]) != "draft":
                raise ValueError("only a current draft timeline can be approved")

            day = _validated_date(str(row["timeline_date"]))
            current_events = self._events(conn, day)
            if not current_events or _event_hash(current_events) != expected_hash:
                raise StaleActivityTimelineError(
                    "input events changed after review; rebuild the timeline draft"
                )

            old_rows = conn.execute(
                """
                SELECT timeline_id, approved_book_id
                FROM daily_activity_timelines
                WHERE project = ? AND timeline_date = ? AND status = 'approved'
                  AND timeline_id <> ?
                """,
                (self.project, day.isoformat(), identifier),
            ).fetchall()
            for old in old_rows:
                old_book_id = compact_whitespace(str(old["approved_book_id"] or ""))
                if old_book_id:
                    conn.execute(
                        """
                        UPDATE memory_books
                        SET status = 'archived', archived_at_ms = ?,
                            archive_reason = 'superseded_activity_timeline',
                            updated_at_ms = ?
                        WHERE book_id = ?
                        """,
                        (timestamp, timestamp, old_book_id),
                    )
            conn.execute(
                """
                UPDATE daily_activity_timelines
                SET status = 'superseded', updated_at_ms = ?
                WHERE project = ? AND timeline_date = ? AND status = 'approved'
                  AND timeline_id <> ?
                """,
                (timestamp, self.project, day.isoformat(), identifier),
            )

            book_id = f"book:daily:activity:{_stable_digest(identifier)[:24]}"
            source_event_ids = _json_ints(row["source_event_ids_json"])
            segments = _json_objects(row["segments_json"])
            apps = list(
                dict.fromkeys(
                    compact_whitespace(str(segment.get("app") or ""))
                    for segment in segments
                    if compact_whitespace(str(segment.get("app") or ""))
                )
            )
            app = apps[0] if len(apps) == 1 else "multiple"
            title = f"{day.isoformat()} 跨应用活动时间线"
            summary = compact_whitespace(str(row["summary_text"] or ""))
            metadata = {
                "schemaVersion": "rag-ime.approved-activity-timeline-book.v1",
                "derivedArtifactType": "daily_activity_timeline",
                "timelineId": identifier,
                "sourceEventHash": expected_hash,
                "approvalStatus": "approved",
                "approvedBy": actor,
                "approvedAtMs": timestamp,
                "maySupportFacts": False,
                "longTermFact": False,
                "automaticPromotion": False,
                "segmentCount": int(row["segment_count"]),
            }
            conn.execute(
                """
                INSERT INTO memory_books(
                    book_id, book_type, book_key, title, summary,
                    normalized_text, project, app, tags_json,
                    surface_hints_json, query_expansions_json,
                    source_event_ids_json, memory_atom_ids_json, status,
                    confidence, quality_score, created_at_ms, updated_at_ms,
                    metadata_json, archived_at_ms, last_active_at_ms,
                    archive_reason, owner_kind, owner_id
                ) VALUES (
                    ?, 'daily', ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, '[]',
                    'active', 0.8, 0.8, ?, ?, ?, NULL, ?, '', 'user', 'default'
                )
                ON CONFLICT(book_id) DO UPDATE SET
                    book_key = excluded.book_key,
                    title = excluded.title,
                    summary = excluded.summary,
                    normalized_text = excluded.normalized_text,
                    project = excluded.project,
                    app = excluded.app,
                    tags_json = excluded.tags_json,
                    source_event_ids_json = excluded.source_event_ids_json,
                    status = 'active',
                    confidence = excluded.confidence,
                    quality_score = excluded.quality_score,
                    updated_at_ms = excluded.updated_at_ms,
                    metadata_json = excluded.metadata_json,
                    archived_at_ms = NULL,
                    last_active_at_ms = excluded.last_active_at_ms,
                    archive_reason = ''
                """,
                (
                    book_id,
                    f"activity:{day.isoformat()}",
                    title,
                    summary,
                    normalize_text(f"{title} {summary}"),
                    self.project,
                    app,
                    json.dumps(
                        ["daily", "activity-timeline", day.isoformat()],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    json.dumps(source_event_ids, separators=(",", ":")),
                    timestamp,
                    timestamp,
                    json.dumps(
                        metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    timestamp,
                ),
            )
            conn.execute(
                """
                UPDATE daily_activity_timelines
                SET status = 'approved', approved_book_id = ?,
                    approved_by = ?, approved_at_ms = ?, updated_at_ms = ?
                WHERE timeline_id = ? AND status = 'draft'
                """,
                (book_id, actor, timestamp, timestamp, identifier),
            )
            if self.observability is not None:
                self.observability.record_draft_decision_in_connection(
                    conn,
                    draft_kind="activity_timeline",
                    draft_id=identifier,
                    decision="accepted",
                    decided_by=actor,
                    created_at_ms=timestamp,
                )
            enqueue_memory_projection(
                conn,
                projection_kind=RETRIEVAL_DOCS_PROJECTION,
                aggregate_type="daily_activity_timeline",
                aggregate_id=identifier,
                operation="approve",
                project=self.project,
                revision=max(1, timestamp),
                payload={
                    "timelineId": identifier,
                    "bookId": book_id,
                    "sourceEventHash": expected_hash,
                },
                available_at_ms=timestamp,
            )
            approved = conn.execute(
                "SELECT * FROM daily_activity_timelines WHERE timeline_id = ?",
                (identifier,),
            ).fetchone()
        if approved is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("approved timeline disappeared")
        payload = _timeline_payload(approved)
        validate_contract(payload, "daily-activity-timeline.v1.json")
        return payload

    def reject(
        self,
        timeline_id: str,
        *,
        reason: str,
        rejected_by: str = "control-center-user",
        rejected_at_ms: int | None = None,
    ) -> dict[str, object]:
        identifier = _required_text(timeline_id, "timeline_id")
        rejection = _required_text(reason, "reason")
        actor = _required_text(rejected_by, "rejected_by")
        timestamp = now_ms() if rejected_at_ms is None else max(0, int(rejected_at_ms))
        self.initialize()
        with self._connect(immediate=True) as conn:
            changed = conn.execute(
                """
                UPDATE daily_activity_timelines
                SET status = 'rejected', rejection_reason = ?, updated_at_ms = ?
                WHERE timeline_id = ? AND project = ? AND status = 'draft'
                """,
                (truncate_text(rejection, 500), timestamp, identifier, self.project),
            )
            if changed.rowcount != 1:
                raise ValueError("only a current draft timeline can be rejected")
            if self.observability is not None:
                self.observability.record_draft_decision_in_connection(
                    conn,
                    draft_kind="activity_timeline",
                    draft_id=identifier,
                    decision="rejected",
                    decided_by=actor,
                    reason=rejection,
                    created_at_ms=timestamp,
                )
            row = conn.execute(
                "SELECT * FROM daily_activity_timelines WHERE timeline_id = ?",
                (identifier,),
            ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("rejected timeline disappeared")
        payload = _timeline_payload(row)
        validate_contract(payload, "daily-activity-timeline.v1.json")
        return payload

    def _events(
        self,
        conn: sqlite3.Connection,
        day: date,
    ) -> list[_ActivityEvent]:
        start_ms, end_ms = _day_bounds_ms(day, self.timezone)
        rows = conn.execute(
            f"""
            SELECT e.id, e.created_at_ms, e.source, e.committed_text,
                   e.recent_context, e.preedit, e.app, e.project,
                   e.context_group_id, e.context_group_level
            FROM input_events e
            LEFT JOIN memory_state s ON s.event_id = e.id
            WHERE e.created_at_ms >= ? AND e.created_at_ms < ?
              AND e.project = ?
              AND COALESCE(s.deleted, 0) = 0
              AND e.source NOT IN ({_placeholders(_INTERNAL_EVENT_SOURCES)})
            ORDER BY e.created_at_ms ASC, e.id ASC
            """,
            (
                start_ms,
                end_ms,
                self.project,
                *sorted(_INTERNAL_EVENT_SOURCES),
            ),
        ).fetchall()
        return [
            _ActivityEvent(
                event_id=int(row["id"]),
                created_at_ms=int(row["created_at_ms"]),
                source=str(row["source"] or ""),
                text=str(row["committed_text"] or ""),
                recent_context=str(row["recent_context"] or ""),
                preedit=str(row["preedit"] or ""),
                app=str(row["app"] or ""),
                project=str(row["project"] or ""),
                context_group_id=str(row["context_group_id"] or ""),
                context_group_level=str(row["context_group_level"] or ""),
            )
            for row in rows
        ]

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
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


def _segments(
    events: Sequence[_ActivityEvent],
    *,
    timezone: tzinfo,
    max_gap_ms: int,
) -> list[ActivityTimelineSegment]:
    groups: list[list[_ActivityEvent]] = []
    for event in events:
        app = _safe_label(event.app, fallback=_safe_label(event.source, fallback="unknown-app"))
        if (
            not groups
            or _safe_label(
                groups[-1][-1].app,
                fallback=_safe_label(groups[-1][-1].source, fallback="unknown-app"),
            )
            != app
            or event.created_at_ms - groups[-1][-1].created_at_ms > max_gap_ms
        ):
            groups.append([event])
        else:
            groups[-1].append(event)

    segments: list[ActivityTimelineSegment] = []
    for position, group in enumerate(groups):
        app = _safe_label(group[0].app, fallback=_safe_label(group[0].source, fallback="unknown-app"))
        source_kinds = tuple(
            dict.fromkeys(
                _safe_label(event.source, fallback="unknown-source")
                for event in group
            )
        )
        context_groups = tuple(
            dict.fromkeys(
                value
                for event in group
                if (
                    value := _safe_optional_label(event.context_group_id)
                )
            )
        )
        source_ids = tuple(event.event_id for event in group)
        source_hash = _event_hash(group)
        snippets: list[str] = []
        redacted_count = 0
        for event in group:
            text = compact_whitespace(event.text)
            if contains_sensitive_content(text):
                redacted_count += 1
                text = "[敏感内容已脱敏]"
            else:
                text = truncate_text(text, 180)
            if text and text not in snippets:
                snippets.append(text)
        if not snippets:
            snippets = ["[无可显示文本]"]
        summary = f"{app}：{'；'.join(snippets[:4])}"
        if len(group) > 4:
            summary += f"；另有 {len(group) - 4} 条输入"
        segment_id = (
            "activity-segment:"
            f"{_stable_digest(str(position), app, source_hash)[:24]}"
        )
        segments.append(
            ActivityTimelineSegment(
                segment_id=segment_id,
                position=position,
                app=app,
                source_kinds=source_kinds,
                context_group_ids=context_groups,
                start_ms=group[0].created_at_ms,
                end_ms=group[-1].created_at_ms,
                event_count=len(group),
                source_event_ids=source_ids,
                source_event_hash=source_hash,
                summary=truncate_text(summary, 760),
                redacted_event_count=redacted_count,
            )
        )
    return segments


def _timeline_summary(
    segments: Sequence[ActivityTimelineSegment],
    *,
    timezone: tzinfo,
) -> str:
    parts: list[str] = []
    for segment in segments:
        start = datetime.fromtimestamp(segment.start_ms / 1_000, tz=timezone)
        end = datetime.fromtimestamp(segment.end_ms / 1_000, tz=timezone)
        time_label = start.strftime("%H:%M")
        if end.strftime("%H:%M") != time_label:
            time_label = f"{time_label}-{end.strftime('%H:%M')}"
        parts.append(f"{time_label} {segment.summary}")
    return truncate_text("；".join(parts), 1_800)


def _event_hash(events: Sequence[_ActivityEvent]) -> str:
    canonical = [
        {
            "id": event.event_id,
            "createdAtMs": event.created_at_ms,
            "source": event.source,
            "text": event.text,
            "recentContext": event.recent_context,
            "preedit": event.preedit,
            "app": event.app,
            "project": event.project,
            "contextGroupId": event.context_group_id,
            "contextGroupLevel": event.context_group_level,
        }
        for event in events
    ]
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _timeline_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "schemaVersion": DAILY_ACTIVITY_TIMELINE_SCHEMA_VERSION,
        "timelineId": str(row["timeline_id"]),
        "project": str(row["project"] or ""),
        "date": str(row["timeline_date"]),
        "timezone": str(row["timezone"] or "local"),
        "status": str(row["status"]),
        "sourceEventIds": _json_ints(row["source_event_ids_json"]),
        "sourceEventHash": str(row["source_event_hash"]),
        "segments": _json_objects(row["segments_json"]),
        "summary": str(row["summary_text"]),
        "eventCount": int(row["event_count"]),
        "segmentCount": int(row["segment_count"]),
        "approvedBookId": str(row["approved_book_id"] or ""),
        "approvedBy": str(row["approved_by"] or ""),
        "approvedAtMs": int(row["approved_at_ms"] or 0),
        "createdAtMs": int(row["created_at_ms"]),
        "updatedAtMs": int(row["updated_at_ms"]),
        "policy": {
            "derivedFromInputEvents": True,
            "longTermFact": False,
            "automaticPromotion": False,
            "explicitApprovalRequired": True,
        },
    }


def _day_bounds_ms(day: date, timezone: tzinfo) -> tuple[int, int]:
    start = datetime.combine(day, time.min, tzinfo=timezone)
    next_day = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone)
    return int(start.timestamp() * 1_000), int(next_day.timestamp() * 1_000)


def _validated_date(value: str) -> date:
    text = compact_whitespace(value)
    try:
        day = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("timeline_date must use YYYY-MM-DD") from exc
    if day.isoformat() != text:
        raise ValueError("timeline_date must use YYYY-MM-DD")
    return day


def _resolve_timezone(value: str) -> tzinfo:
    name = compact_whitespace(value)
    if name:
        try:
            return ZoneInfo(name)
        except Exception as exc:
            raise ValueError(f"unknown timezone: {name}") from exc
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def _timezone_name(value: tzinfo) -> str:
    key = compact_whitespace(str(getattr(value, "key", "") or ""))
    return key or compact_whitespace(str(value)) or "local"


def _safe_label(value: object, *, fallback: str) -> str:
    text = compact_whitespace(str(value or ""))
    if not text or contains_sensitive_content(text):
        return fallback
    return truncate_text(text, 160)


def _safe_optional_label(value: object) -> str:
    text = compact_whitespace(str(value or ""))
    if not text or contains_sensitive_content(text):
        return ""
    return truncate_text(text, 240)


def _required_text(value: object, name: str) -> str:
    text = compact_whitespace(str(value or ""))
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _stable_digest(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _json_ints(raw: object) -> list[int]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [
        int(item)
        for item in value
        if isinstance(item, int) and not isinstance(item, bool) and item > 0
    ]


def _json_objects(raw: object) -> list[dict[str, object]]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _placeholders(values: Sequence[object] | frozenset[str]) -> str:
    return ",".join("?" for _ in values)
