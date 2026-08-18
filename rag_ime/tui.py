"""Optional Textual surface for inspecting Agent Sessions and Rooms."""
from __future__ import annotations
from typing import Any, Protocol

class RuntimeFacade(Protocol):
    def list_sessions(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...
    def list_rooms(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...

def snapshot(service: RuntimeFacade) -> dict[str, list[dict[str, object]]]:
    """Read existing authoritative projections; no second runtime is created."""
    return {"sessions": [dict(x) for x in service.list_sessions({}).get("items", []) if isinstance(x, dict)], "rooms": [dict(x) for x in service.list_rooms({}).get("items", []) if isinstance(x, dict)]}

def _label(item: dict[str, object], fallback: str) -> str:
    return str(item.get("title") or item.get("name") or item.get("id") or fallback)

def build_app(service: RuntimeFacade) -> Any:
    """Build, but don't start, the Textual application."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Label, ListItem, ListView, Static
    except ImportError as exc:
        raise RuntimeError("Textual is required; install the 'tui' extra") from exc
    class AgentTui(App[None]):
        TITLE = "PAW — Sessions & Rooms"
        BINDINGS = [("r", "refresh", "Refresh"), ("q", "quit", "Quit")]
        def compose(self) -> ComposeResult:
            data = snapshot(service)
            with Vertical():
                yield Header()
                with Horizontal():
                    with Vertical():
                        yield Static("Sessions", classes="section-title")
                        yield ListView(*(ListItem(Label(_label(x, "Session"))) for x in data["sessions"]), id="sessions")
                    with Vertical():
                        yield Static("Rooms", classes="section-title")
                        yield ListView(*(ListItem(Label(_label(x, "Room"))) for x in data["rooms"]), id="rooms")
                yield Footer()
        def action_refresh(self) -> None:
            self.refresh(recompose=True)
    return AgentTui()

def main(service: RuntimeFacade | None = None) -> None:
    if service is None:
        raise RuntimeError("Pass an AgentService instance to main(); service bootstrap is not defined")
    build_app(service).run()

__all__ = ["RuntimeFacade", "build_app", "main", "snapshot"]
if __name__ == "__main__":
    main()
