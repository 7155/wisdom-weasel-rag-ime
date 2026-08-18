"""Optional Textual surface for inspecting Agent Sessions and Rooms."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


class RuntimeFacade(Protocol):
    def list_sessions(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...

    def list_rooms(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...


def default_db_path() -> Path:
    """Resolve the DB path using the same default as CLI bootstrap behavior."""
    return Path(os.environ.get("RAG_IME_DB_PATH", ".rag-ime-data/rag-ime.sqlite"))


def _coerce_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return default
    return default


def build_agent_service(*, db_path: str | Path | None = None, wake_scheduler: bool = False) -> RuntimeFacade:
    """Build an Authoritative Agent service adapter bound to local DB settings."""
    from .agent_service import agent_service_from_environment

    path = _coerce_path(db_path or default_db_path())
    return agent_service_from_environment(
        db_path=str(path),
        wake_scheduler_enabled=wake_scheduler,
    )


def snapshot(
    service: RuntimeFacade,
    *,
    session_limit: int | None = 500,
    room_limit: int | None = 200,
) -> dict[str, object]:
    """Read existing authoritative projections; no second runtime is created."""
    session_payload = service.list_sessions({"limit": session_limit} if session_limit is not None else {})
    room_payload = service.list_rooms({"limit": room_limit} if room_limit is not None else {})
    return {
        "sessions": [dict(x) for x in session_payload.get("items", []) if isinstance(x, dict)],
        "rooms": [dict(x) for x in room_payload.get("items", []) if isinstance(x, dict)],
        "activeSessionId": str(session_payload.get("activeSessionId") or ""),
    }


def _label(item: dict[str, object], fallback: str) -> str:
    return str(item.get("title") or item.get("name") or item.get("id") or fallback)


def _status_style(status: str) -> tuple[str, str]:
    color = {
        "active": "green",
        "running": "green",
        "busy": "yellow",
        "thinking": "yellow",
        "paused": "blue",
        "failed": "red",
        "error": "red",
        "completed": "grey54",
        "done": "grey54",
        "archived": "grey70",
    }.get(status, "white")
    return color, status or "unknown"


def _render_session(item: dict[str, object], active_session_id: str, *, is_selected: bool = False) -> str:
    title = _label(item, "Session")
    status = str(item.get("status") or item.get("phase") or "unknown")
    color, status_text = _status_style(status.lower())
    session_id = str(item.get("id") or "")
    marker = "*" if session_id and active_session_id == session_id else " "
    pointer = ">" if is_selected else " "
    return f"[{color}]{marker} {status_text}[/{color}] {pointer}{title} [{session_id}]"


def _room_member_count(item: dict[str, object]) -> int:
    participants = item.get("participants")
    if isinstance(participants, list):
        return len(participants)
    return _as_int(item.get("participantCount"))


def _render_room(item: dict[str, object], *, is_selected: bool = False) -> str:
    title = _label(item, "Room")
    room_id = str(item.get("id") or "")
    routing_policy = str(item.get("routingPolicy") or "")
    members = _room_member_count(item)
    pointer = ">" if is_selected else " "
    policy = f"/{routing_policy}" if routing_policy else ""
    return f"{pointer}{title}{policy} [{members}人] [{room_id}]"


def _slice_page(items: list[dict[str, object]], page: int, page_size: int) -> tuple[list[dict[str, object]], int]:
    size = max(1, page_size)
    total = max(1, (len(items) + size - 1) // size)
    current_page = max(0, min(page, total - 1))
    start = current_page * size
    return items[start:start + size], current_page


def _detail_text(item: dict[str, object] | None, kind: str, *, active_session_id: str = "") -> str:
    if item is None:
        return f"{kind}: (none)"
    if kind == "session":
        title = _label(item, "Session")
        session_id = str(item.get("id") or "")
        status = str(item.get("status") or item.get("phase") or "unknown")
        room_binding = item.get("roomParticipant")
        room = (
            str(room_binding.get("roomId") or room_binding.get("participantId") or "")
            if isinstance(room_binding, Mapping)
            else str(room_binding or "")
        )
        star = "*" if session_id == active_session_id else ""
        return f"Session{star}: {title}\nID: {session_id}\nStatus: {status}\nRoom: {room or 'unbound'}"
    room_id = str(item.get("id") or "")
    routing_policy = str(item.get("routingPolicy") or "")
    members = _room_member_count(item)
    return f"Room: {_label(item, 'Room')}\nID: {room_id}\nRouting Policy: {routing_policy or 'default'}\nMembers: {members}"


def _build_pager(prefix: str, page: int, page_size: int, total_items: int) -> str:
    if not total_items:
        return f"{prefix}: 0/0"
    total_pages = max(1, (total_items + max(1, page_size) - 1) // max(1, page_size))
    return f"{prefix}: page {page + 1}/{total_pages} ({total_items})"


def build_app(
    service: RuntimeFacade,
    *,
    session_page_size: int = 20,
    room_page_size: int = 20,
) -> Any:
    """Build, but don't start, the Textual application."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Label, ListItem, ListView, Static
    except ImportError as exc:
        raise RuntimeError("Textual is required; install the 'tui' extra") from exc

    class AgentTui(App[None]):
        TITLE = "PAW — Sessions & Rooms"
        BINDINGS = [
            ("r", "refresh", "Refresh"),
            ("j", "next_item", "Next"),
            ("k", "prev_item", "Prev"),
            ("n", "next_page", "Next Page"),
            ("p", "prev_page", "Prev Page"),
            ("t", "focus_sessions", "Sessions"),
            ("y", "focus_rooms", "Rooms"),
            ("d", "detail", "Detail"),
            ("q", "quit", "Quit"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self._service = service
            self._session_page = 0
            self._room_page = 0
            self._session_page_size = max(1, int(session_page_size))
            self._room_page_size = max(1, int(room_page_size))
            self._active_panel = "sessions"
            self._selected_session_index = 0
            self._selected_room_index = 0
            self._last_snapshot: dict[str, object] | None = None

        def compose(self) -> ComposeResult:
            data = self._snapshot()
            sessions = list(data["sessions"])
            rooms = list(data["rooms"])
            active_session_id = str(data.get("activeSessionId") or "")
            active_session_page, session_page = _slice_page(sessions, self._session_page, self._session_page_size)
            active_room_page, room_page = _slice_page(rooms, self._room_page, self._room_page_size)
            self._session_page = session_page
            self._room_page = room_page
            self._selected_session_index = min(self._selected_session_index, max(0, len(active_session_page) - 1))
            self._selected_room_index = min(self._selected_room_index, max(0, len(active_room_page) - 1))
            if not active_session_page:
                self._selected_session_index = 0
            if not active_room_page:
                self._selected_room_index = 0

            if self._active_panel == "sessions":
                selected_session = active_session_page[self._selected_session_index] if active_session_page else None
                selected_room = active_room_page[self._selected_room_index] if active_room_page else None
            else:
                selected_room = active_room_page[self._selected_room_index] if active_room_page else None
                selected_session = active_session_page[self._selected_session_index] if active_session_page else None

            with Vertical():
                yield Header()
                with Horizontal():
                    with Vertical():
                        session_rows = [
                            ListItem(
                                Label(
                                    _render_session(
                                        item,
                                        active_session_id,
                                        is_selected=(idx == self._selected_session_index),
                                    )
                                )
                            )
                            for idx, item in enumerate(active_session_page)
                        ]
                        yield Static(_build_pager("Sessions", self._session_page, self._session_page_size, len(sessions)), id="sessions-pager")
                        yield ListView(*session_rows, id="sessions")
                    with Vertical():
                        room_rows = [
                            ListItem(
                                Label(
                                    _render_room(
                                        item,
                                        is_selected=(idx == self._selected_room_index),
                                    )
                                )
                            )
                            for idx, item in enumerate(active_room_page)
                        ]
                        yield Static(_build_pager("Rooms", self._room_page, self._room_page_size, len(rooms)), id="rooms-pager")
                        yield ListView(*room_rows, id="rooms")
                    with Vertical():
                        yield Static(
                            _detail_text(
                                selected_session if self._active_panel == "sessions" else selected_room,
                                "session" if self._active_panel == "sessions" else "room",
                                active_session_id=active_session_id,
                            ),
                            id="detail",
                        )
                yield Static(f"Focus: {self._active_panel} | j/k move | n/p page | t/y panel | d detail", classes="help")
                yield Footer()

        def _snapshot(self) -> dict[str, object]:
            # The authoritative list APIs expose bounded limits but no offset
            # or total count. Read their supported local maxima once per
            # refresh, then page this immutable projection in the TUI; asking
            # only for the current page makes page 1 look like the last page.
            data = snapshot(self._service)
            self._last_snapshot = data
            return data

        def _selected_payload(self) -> dict[str, object] | None:
            if not self._last_snapshot:
                return None
            data = self._last_snapshot
            sessions = list(data["sessions"])
            rooms = list(data["rooms"])
            session_page, _ = _slice_page(
                sessions,
                self._session_page,
                self._session_page_size,
            )
            room_page, _ = _slice_page(
                rooms,
                self._room_page,
                self._room_page_size,
            )
            if self._active_panel == "sessions":
                if not session_page:
                    return None
                return session_page[self._selected_session_index]
            if not room_page:
                return None
            return room_page[self._selected_room_index]

        def action_next_item(self) -> None:
            if self._active_panel == "sessions":
                data = self._snapshot()
                sessions = data["sessions"]
                page, _ = _slice_page(sessions, self._session_page, self._session_page_size)
                if self._selected_session_index + 1 < len(page):
                    self._selected_session_index += 1
                    self.refresh(recompose=True)
            else:
                data = self._snapshot()
                rooms = data["rooms"]
                page, _ = _slice_page(rooms, self._room_page, self._room_page_size)
                if self._selected_room_index + 1 < len(page):
                    self._selected_room_index += 1
                    self.refresh(recompose=True)

        def action_prev_item(self) -> None:
            if self._active_panel == "sessions":
                if self._selected_session_index > 0:
                    self._selected_session_index -= 1
                    self.refresh(recompose=True)
            else:
                if self._selected_room_index > 0:
                    self._selected_room_index -= 1
                    self.refresh(recompose=True)

        def action_next_page(self) -> None:
            if self._active_panel == "sessions":
                data = self._snapshot()
                total = len(data["sessions"])
                max_page = max(0, (total - 1) // self._session_page_size)
                if self._session_page < max_page:
                    self._session_page += 1
                    self._selected_session_index = 0
                    self.refresh(recompose=True)
            else:
                data = self._snapshot()
                total = len(data["rooms"])
                max_page = max(0, (total - 1) // self._room_page_size)
                if self._room_page < max_page:
                    self._room_page += 1
                    self._selected_room_index = 0
                    self.refresh(recompose=True)

        def action_prev_page(self) -> None:
            if self._active_panel == "sessions":
                if self._session_page > 0:
                    self._session_page -= 1
                    self._selected_session_index = 0
                    self.refresh(recompose=True)
            else:
                if self._room_page > 0:
                    self._room_page -= 1
                    self._selected_room_index = 0
                    self.refresh(recompose=True)

        def action_focus_sessions(self) -> None:
            self._active_panel = "sessions"
            self.refresh(recompose=True)

        def action_focus_rooms(self) -> None:
            self._active_panel = "rooms"
            self.refresh(recompose=True)

        def action_detail(self) -> None:
            _ = self._selected_payload()
            self.refresh(recompose=True)

        def action_refresh(self) -> None:
            self.refresh(recompose=True)

    return AgentTui()


def main(service: RuntimeFacade | None = None, argv: Sequence[str] | None = None) -> int:
    if service is None:
        parser = argparse.ArgumentParser(description="PAW Agent Sessions/Rooms TUI")
        parser.add_argument("--db-path", default=str(default_db_path()))
        parser.add_argument("--session-page", type=int, default=20)
        parser.add_argument("--room-page", type=int, default=20)
        parser.add_argument("--no-runtime-owner", action="store_true", help="Do not own runtime; just query existing runtime state")
        args = parser.parse_args(argv)
        service = build_agent_service(db_path=args.db_path, wake_scheduler=not args.no_runtime_owner)
        app = build_app(
            service,
            session_page_size=max(1, args.session_page),
            room_page_size=max(1, args.room_page),
        )
        app.run()
        return 0

    build_app(service).run()
    return 0


__all__ = [
    "RuntimeFacade",
    "build_app",
    "build_agent_service",
    "default_db_path",
    "main",
    "snapshot",
    "_render_session",
    "_render_room",
    "_detail_text",
    "_room_member_count",
]
if __name__ == "__main__":
    raise SystemExit(main())
