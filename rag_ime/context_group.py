from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from threading import RLock
from typing import Callable, Literal

from .text_utils import compact_whitespace, now_ms, stable_text_hash


ContextGroupLevel = Literal["document", "project", "app", "global"]


@dataclass(frozen=True)
class ContextGroup:
    context_group_id: str
    context_group_level: ContextGroupLevel
    confidence: float
    document_group_id: str = ""
    project_group_id: str = ""
    app_group_id: str = ""
    parent_group_ids: tuple[str, ...] = ()
    app_bundle_id: str = ""
    project: str = ""


@dataclass(frozen=True)
class RecentGroupEvent:
    text: str
    created_at_ms: int
    event_id: int | None = None
    accepted: bool = False
    deleted: bool = False
    source: str = "commit"


def resolve_context_group(
    *,
    app_bundle_id: str,
    document_url: str = "",
    window_title: str = "",
    project: str = "",
) -> ContextGroup:
    """Build stable deterministic scopes without inspecting editable text."""

    app = compact_whitespace(app_bundle_id) or "unknown-app"
    project_name = compact_whitespace(project)
    document_identity = compact_whitespace(document_url)
    document_confidence = 1.0
    if not document_identity:
        document_identity = compact_whitespace(window_title)
        document_confidence = 0.85

    app_group_id = _group_id("app", app)
    project_group_id = _group_id("project", project_name) if project_name else ""
    document_group_id = _group_id("doc", app, document_identity) if document_identity else ""
    parents = tuple(value for value in (project_group_id, app_group_id, "global") if value)
    if document_group_id:
        return ContextGroup(
            context_group_id=document_group_id,
            context_group_level="document",
            confidence=document_confidence,
            document_group_id=document_group_id,
            project_group_id=project_group_id,
            app_group_id=app_group_id,
            parent_group_ids=parents,
            app_bundle_id=app,
            project=project_name,
        )
    if project_group_id:
        return ContextGroup(
            context_group_id=project_group_id,
            context_group_level="project",
            confidence=0.75,
            project_group_id=project_group_id,
            app_group_id=app_group_id,
            parent_group_ids=(app_group_id, "global"),
            app_bundle_id=app,
            project=project_name,
        )
    return ContextGroup(
        context_group_id=app_group_id,
        context_group_level="app",
        confidence=0.5,
        app_group_id=app_group_id,
        parent_group_ids=("global",),
        app_bundle_id=app,
    )


def context_group_compatibility(
    current: ContextGroup,
    *,
    candidate_group_id: str = "",
    candidate_project: str = "",
    candidate_app: str = "",
    short_term: bool = False,
) -> float:
    candidate_group = compact_whitespace(candidate_group_id)
    if candidate_group and candidate_group == current.context_group_id:
        return 1.0
    if short_term:
        return 0.0
    if candidate_group == "global":
        return 0.2
    if current.project and compact_whitespace(candidate_project) == current.project:
        return 0.75
    if current.app_bundle_id and compact_whitespace(candidate_app) == current.app_bundle_id:
        return 0.5
    return 0.05


class GroupShortBuffer:
    """Small process-local commit buffer; it is not persistent session memory."""

    def __init__(
        self,
        *,
        max_events_per_group: int = 20,
        ttl_ms: int = 30 * 60 * 1000,
        clock_ms: Callable[[], int] = now_ms,
    ) -> None:
        self.max_events_per_group = max(1, int(max_events_per_group))
        self.ttl_ms = max(1, int(ttl_ms))
        self._clock_ms = clock_ms
        self._events: dict[str, deque[RecentGroupEvent]] = defaultdict(
            lambda: deque(maxlen=self.max_events_per_group)
        )
        self._lock = RLock()

    def append(
        self,
        group_id: str,
        text: str,
        *,
        event_id: int | None = None,
        accepted: bool = False,
        deleted: bool = False,
        source: str = "commit",
        created_at_ms: int | None = None,
    ) -> RecentGroupEvent | None:
        resolved_group = compact_whitespace(group_id)
        resolved_text = compact_whitespace(text)
        if not resolved_group or not resolved_text:
            return None
        created = self._clock_ms() if created_at_ms is None else max(0, int(created_at_ms))
        event = RecentGroupEvent(
            text=resolved_text,
            created_at_ms=created,
            event_id=event_id,
            accepted=bool(accepted),
            deleted=bool(deleted),
            source=compact_whitespace(source) or "commit",
        )
        with self._lock:
            self._prune_locked(created)
            self._events[resolved_group].append(event)
        return event

    def mark(self, group_id: str, *, event_id: int, accepted: bool = False, deleted: bool = False) -> bool:
        resolved_group = compact_whitespace(group_id)
        with self._lock:
            self._prune_locked(self._clock_ms())
            events = self._events.get(resolved_group)
            if not events:
                return False
            updated = False
            replacement: deque[RecentGroupEvent] = deque(maxlen=self.max_events_per_group)
            for event in events:
                if event.event_id == event_id:
                    event = replace(event, accepted=event.accepted or accepted, deleted=event.deleted or deleted)
                    updated = True
                replacement.append(event)
            self._events[resolved_group] = replacement
            return updated

    def recent(self, group_id: str, *, limit: int = 20, include_deleted: bool = False) -> tuple[RecentGroupEvent, ...]:
        resolved_group = compact_whitespace(group_id)
        with self._lock:
            self._prune_locked(self._clock_ms())
            events = list(self._events.get(resolved_group, ()))
        if not include_deleted:
            events = [event for event in events if not event.deleted]
        return tuple(events[-max(1, int(limit)) :])

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def _prune_locked(self, current_ms: int) -> None:
        cutoff = current_ms - self.ttl_ms
        empty: list[str] = []
        for group_id, events in self._events.items():
            while events and events[0].created_at_ms < cutoff:
                events.popleft()
            if not events:
                empty.append(group_id)
        for group_id in empty:
            self._events.pop(group_id, None)


def _group_id(prefix: str, *parts: str) -> str:
    material = "\x1f".join(compact_whitespace(part) for part in parts)
    return f"{prefix}:{stable_text_hash(material)[:16]}"
