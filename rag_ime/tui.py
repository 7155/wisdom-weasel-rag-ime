"""Conversation-first Textual client for the one Gateway-owned Pi Runtime."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
import uuid
import urllib.error
import urllib.parse
import urllib.request


class RuntimeFacade(Protocol):
    def list_sessions(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...
    def list_rooms(self, payload: dict[str, object] | None = None) -> dict[str, object]: ...
    def create_session(self, payload: Mapping[str, object]) -> dict[str, object]: ...
    def messages(self, session_id: str) -> dict[str, object]: ...
    def prompt(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]: ...
    def abort(self, session_id: str) -> dict[str, object]: ...
    def command_catalog(self, session_id: str) -> dict[str, object]: ...
    def invoke_command(self, session_id: str, payload: Mapping[str, object]) -> dict[str, object]: ...


_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def default_db_path() -> Path:
    """Resolve the installed product DB unless a caller explicitly overrides it."""
    configured = str(os.environ.get("RAG_IME_DB_PATH") or "").strip()
    if configured:
        return Path(configured)
    return Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"


def default_gateway_url() -> str:
    """Resolve the dedicated local Agent Gateway used by projection-only clients."""
    return str(
        os.environ.get("RAG_IME_AGENT_GATEWAY_URL")
        or "http://127.0.0.1:8768"
    ).strip().rstrip("/")


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


class GatewayRuntimeFacade:
    """Thin TUI client for the one authoritative Gateway-owned Pi Runtime."""

    def __init__(
        self,
        gateway_url: str = "",
        *,
        timeout_seconds: float = 15.0,
        turn_timeout_seconds: float = 300.0,
        urlopen: Any | None = None,
    ) -> None:
        self.gateway_url = _validated_loopback_gateway_url(
            gateway_url or default_gateway_url()
        )
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.turn_timeout_seconds = max(
            self.timeout_seconds,
            float(turn_timeout_seconds),
        )
        self._urlopen = urlopen or _DIRECT_HTTP_OPENER.open

    def list_sessions(
        self,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self._request("GET", "/api/agent/sessions", query=payload)

    def list_rooms(
        self,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self._request("GET", "/api/agent/rooms", query=payload)

    def create_session(
        self,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self._request("POST", "/api/agent/sessions", payload=payload)

    def messages(self, session_id: str) -> dict[str, object]:
        return self._request(
            "GET",
            f"/api/agent/sessions/{_path_id(session_id)}/messages",
        )

    def prompt(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self._request(
            "POST",
            f"/api/agent/sessions/{_path_id(session_id)}/prompt",
            payload=payload,
            timeout_seconds=self.turn_timeout_seconds,
        )

    def abort(self, session_id: str) -> dict[str, object]:
        return self._request(
            "POST",
            f"/api/agent/sessions/{_path_id(session_id)}/abort",
            payload={},
        )

    def command_catalog(self, session_id: str) -> dict[str, object]:
        return self._request(
            "GET",
            f"/api/agent/sessions/{_path_id(session_id)}/commands",
        )

    def invoke_command(
        self,
        session_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        return self._request(
            "POST",
            f"/api/agent/sessions/{_path_id(session_id)}/commands",
            payload=payload,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        query_values = {
            str(key): str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in dict(query or {}).items()
            if value is not None and str(value) != ""
        }
        suffix = f"?{urllib.parse.urlencode(query_values)}" if query_values else ""
        body = (
            json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        request = urllib.request.Request(
            f"{self.gateway_url}{path}{suffix}",
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._urlopen(
                request,
                timeout=timeout_seconds or self.timeout_seconds,
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Agent Gateway returned HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Agent Gateway is unavailable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(
                "Agent Gateway request timed out; the Pi turn may still be running. "
                "Refresh this Session before retrying."
            ) from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Agent Gateway returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Agent Gateway returned an invalid response")
        if decoded.get("ok") is False:
            raise RuntimeError(str(decoded.get("error") or "Agent Gateway request failed"))
        return dict(decoded)


def _validated_loopback_gateway_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("TUI Agent Gateway URL must be a loopback HTTP origin")
    hostname = parsed.hostname.lower()
    try:
        is_loopback = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname == "localhost"
    if not is_loopback:
        raise ValueError("TUI Agent Gateway URL must use a loopback host")
    return raw


def _path_id(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Session id is required")
    return urllib.parse.quote(normalized, safe="")


def build_gateway_service(*, gateway_url: str = "") -> RuntimeFacade:
    """Build a projection client that never opens a second Agent Runtime."""
    return GatewayRuntimeFacade(gateway_url or default_gateway_url())


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


def _message_text(message: Mapping[str, object]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else message.get("blocks")
    if isinstance(blocks, list):
        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            data = block.get("data")
            if isinstance(data, Mapping):
                value = (
                    data.get("text")
                    or data.get("content")
                    or data.get("message")
                    or data.get("summary")
                )
            else:
                value = (
                    block.get("text")
                    or block.get("content")
                    or block.get("message")
                    or block.get("summary")
                )
            if value:
                parts.append(str(value))
        if parts:
            return "\n".join(parts)
    return str(message.get("text") or "")


def _render_messages(service: RuntimeFacade, session_id: str) -> str:
    """Render the selected Session's durable message snapshot."""
    if not session_id:
        return "Messages: (select a session)"
    payload = service.messages(session_id)
    return _render_message_payload(payload, session_id)


def _render_message_payload(
    payload: Mapping[str, object],
    session_id: str,
) -> str:
    """Render one already-fetched message payload without doing I/O."""
    messages = payload.get("messages", payload.get("items", []))
    if not isinstance(messages, list) or not messages:
        return f"Messages: (none)\nSession: {session_id}"
    rows = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or message.get("sender") or "message")
        text = _message_text(message)
        rows.append(f"{role}: {text}")
    return "\n".join(rows) or f"Messages: (none)\nSession: {session_id}"


@dataclass(frozen=True)
class TranscriptEntry:
    """One bounded, presentation-neutral row in the TUI transcript."""

    kind: str
    title: str
    body: str
    status: str = ""


def _bounded_text(value: object, *, limit: int = 1_800) -> str:
    """Keep live Runtime payloads readable without dumping unbounded output."""

    if isinstance(value, str):
        text = value
    elif value is None:
        text = ""
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _event_payload(event: Mapping[str, object]) -> Mapping[str, object]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else event


def _project_transcript(
    payload: Mapping[str, object],
    session_id: str,
) -> list[TranscriptEntry]:
    """Project durable messages and bounded live events into readable rows."""

    entries: list[TranscriptEntry] = []
    seen_message_ids: set[str] = set()
    terminal_turn_ids: set[str] = set()
    messages = payload.get("items", payload.get("messages", []))
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            message_identity = str(
                message.get("id")
                or message.get("messageId")
                or message.get("clientMessageId")
                or ""
            )
            if message_identity and message_identity in seen_message_ids:
                continue
            if message_identity:
                seen_message_ids.add(message_identity)
            role = str(message.get("role") or message.get("sender") or "message")
            title = {
                "user": "你",
                "assistant": "Assistant",
                "coordinator": "Assistant",
                "system": "System",
                "tool": "Tool",
            }.get(role, role or "Message")
            body = _bounded_text(_message_text(message), limit=12_000)
            status = str(message.get("status") or "")
            turn_id = str(message.get("turnId") or "")
            if turn_id and status in {"failed", "aborted", "cancelled", "canceled"}:
                terminal_turn_ids.add(turn_id)
            if body or status in {"streaming", "failed", "aborted"}:
                entries.append(
                    TranscriptEntry(
                        kind="message",
                        title=title,
                        body=body or "（等待内容）",
                        status=status,
                    )
                )

    live_events = payload.get("liveEvents")
    seen_event_ids: set[str] = set()
    if isinstance(live_events, list):
        for event in live_events:
            if not isinstance(event, Mapping):
                continue
            event_id = str(event.get("eventId") or event.get("id") or "")
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            event_type = str(event.get("eventType") or event.get("type") or "")
            turn_id = str(event.get("turnId") or "")
            if event_type in {
                "text_delta",
                "message_completed",
                "user_message",
                "assistant_message",
            }:
                continue
            data = _event_payload(event)
            status = str(data.get("status") or data.get("state") or "")
            summary = _bounded_text(
                data.get("summary")
                or data.get("message")
                or data.get("error")
                or data.get("operation")
                or ""
            )
            if event_type in {"reasoning_summary", "thinking_summary"}:
                items = data.get("items")
                if not summary and isinstance(items, list):
                    summary = "\n".join(str(item) for item in items if item)
                entries.append(
                    TranscriptEntry("thinking", "思考摘要", summary or "正在思考", status)
                )
            elif event_type in {"tool_started", "tool_progress", "tool_finished"}:
                tool = str(data.get("toolId") or data.get("tool") or "Tool")
                operation = str(data.get("operation") or "").strip()
                tool_title = f"{tool} · {operation}" if operation else tool
                detail = summary
                if not detail and event_type == "tool_started":
                    detail = _bounded_text(data.get("args")) or "已开始"
                entries.append(
                    TranscriptEntry("tool", tool_title, detail or event_type, status or event_type)
                )
            elif event_type in {"approval_required", "approval_requested"}:
                entries.append(
                    TranscriptEntry("approval", "等待审批", summary or "需要用户确认", status or "pending")
                )
            elif event_type in {"user_input_required", "extension_ui_request"}:
                entries.append(
                    TranscriptEntry("input", "等待你的输入", summary or "Agent 需要补充信息", status or "pending")
                )
            elif event_type in {"turn_failed", "provider_error", "runtime_error"}:
                if turn_id and turn_id in terminal_turn_ids:
                    continue
                entries.append(
                    TranscriptEntry("error", "本轮失败", summary or event_type, status or "failed")
                )
            elif event_type == "turn_completed" and (
                status in {"aborted", "cancelled", "canceled"}
                or data.get("aborted") is True
            ):
                if turn_id and turn_id in terminal_turn_ids:
                    continue
                entries.append(
                    TranscriptEntry("terminal", "本轮已停止", summary or "已取消", status or "aborted")
                )

    for job in payload.get("backgroundJobs") or []:
        if not isinstance(job, Mapping):
            continue
        status = str(job.get("status") or "unknown")
        if status not in {"queued", "running", "failed", "blocked"}:
            continue
        entries.append(
            TranscriptEntry(
                "background",
                str(job.get("title") or job.get("name") or "后台任务"),
                _bounded_text(job.get("summary") or job.get("error") or status),
                status,
            )
        )

    if not entries:
        entries.append(
            TranscriptEntry(
                "empty",
                "新对话",
                f"Session {session_id} 还没有消息。可以从下方输入开始。",
            )
        )
    return entries


def _session_heading(
    session: Mapping[str, object] | None,
    message_payload: Mapping[str, object] | None = None,
) -> str:
    if not session:
        return "选择一个 Session 开始对话"
    status = str(
        (message_payload or {}).get("status")
        or session.get("status")
        or session.get("phase")
        or "idle"
    )
    model = str(session.get("modelProfile") or session.get("model") or "Pi default")
    roots = session.get("workspaceRoots")
    workspace = (
        str(roots[0])
        if isinstance(roots, list) and roots
        else str(session.get("workingDirectory") or session.get("cwd") or "未绑定工作区")
    )
    return (
        f"{_label(dict(session), 'Session')}  ·  {status}\n"
        f"{model}  ·  {workspace}"
    )


def _inspector_text(
    payload: Mapping[str, object],
    catalog_payload: Mapping[str, object],
) -> str:
    lines = [_command_help_payload(catalog_payload)]
    goal = payload.get("goal")
    if isinstance(goal, Mapping):
        goal_text = goal.get("text") or goal.get("title") or goal.get("summary")
        if goal_text:
            lines.append(f"Goal: {_bounded_text(goal_text)}")
    todo = payload.get("todo")
    todo_items = todo.get("items") if isinstance(todo, Mapping) else todo
    if isinstance(todo_items, list) and todo_items:
        completed = sum(
            1
            for item in todo_items
            if isinstance(item, Mapping)
            and str(item.get("status") or "") in {"completed", "done"}
        )
        lines.append(f"Todo: {completed}/{len(todo_items)}")
    queue = payload.get("messageQueue")
    if isinstance(queue, Mapping):
        steering = queue.get("steering")
        follow_up = queue.get("followUp")
        queued = len(steering) if isinstance(steering, list) else 0
        queued += len(follow_up) if isinstance(follow_up, list) else 0
        if queued:
            lines.append(f"等待投递: {queued}")
    return "\n".join(lines)


def _command_help(service: RuntimeFacade, session_id: str) -> str:
    if not session_id:
        return "Pi Package 命令：请先选择一个 Session"
    payload = service.command_catalog(session_id)
    return _command_help_payload(payload)


def _command_help_payload(payload: Mapping[str, object]) -> str:
    """Project Package-owned commands from Pi's live Session catalog."""
    items = payload.get("items")
    commands = [
        f"/{str(item.get('name') or '')}"
        for item in items if isinstance(item, Mapping)
        and item.get("source") == "extension"
        and str(item.get("name") or "")
    ] if isinstance(items, list) else []
    return "已启用 Pi Package 命令（在输入框直接执行）: " + (
        "  ".join(commands) if commands else "（当前 Session 没有启用）"
    )


def _command_source(service: RuntimeFacade, session_id: str, command_text: str) -> str | None:
    """Resolve one slash command against Pi's live Session resource catalog."""
    command = command_text.strip()
    if not command.startswith("/"):
        return None
    name = command[1:].split(maxsplit=1)[0]
    if not name:
        return None
    payload = service.command_catalog(session_id)
    return _command_source_from_payload(payload, command_text)


def _command_source_from_payload(
    payload: Mapping[str, object],
    command_text: str,
) -> str | None:
    """Resolve a command against an already-fetched Pi catalog."""
    command = command_text.strip()
    if not command.startswith("/"):
        return None
    name = command[1:].split(maxsplit=1)[0]
    if not name:
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, Mapping) and str(item.get("name") or "") == name:
            source = str(item.get("source") or "").strip()
            return source or None
    return None


def _render_command_result(payload: Mapping[str, object]) -> str:
    result = payload.get("result")
    result_map = result if isinstance(result, Mapping) else {}
    message = str(result_map.get("message") or "").strip()
    name = str(payload.get("name") or result_map.get("command") or "command").strip()
    return f"/{name}: {message or 'completed'}"


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


def _named_rows(value: object) -> list[dict[str, object]]:
    """Normalize optional Runtime arrays without inventing lifecycle state."""
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _status_line(row: dict[str, object], fallback: str) -> str:
    status = str(row.get("status") or row.get("phase") or "unknown")
    return f"{_label(row, fallback)} ({status})"


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
        lines = [f"Session{star}: {title}", f"ID: {session_id}", f"Status: {status}", f"Room: {room or 'unbound'}"]
        tools = _named_rows(item.get("tools") or item.get("toolStates") or item.get("toolRuns"))
        children = _named_rows(item.get("subAgents") or item.get("childAgents") or item.get("delegations"))
        if tools:
            lines.append("Tools: " + ", ".join(_status_line(row, "Tool") for row in tools))
        if children:
            lines.append("SubAgents: " + ", ".join(_status_line(row, "Agent") for row in children))
        return "\n".join(lines)
    room_id = str(item.get("id") or "")
    routing_policy = str(item.get("routingPolicy") or "")
    members = _room_member_count(item)
    lines = [f"Room: {_label(item, 'Room')}", f"ID: {room_id}", f"Routing Policy: {routing_policy or 'default'}", f"Members: {members}"]
    participants = _named_rows(item.get("participants"))
    tasks = _named_rows(item.get("tasks") or item.get("workItems") or item.get("taskDetails"))
    if participants:
        lines.append("Participants: " + ", ".join(_status_line(row, "Participant") for row in participants))
    if tasks:
        lines.append("Tasks: " + ", ".join(_status_line(row, "Task") for row in tasks))
    return "\n".join(lines)


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
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text
        from textual import events
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.message import Message
        from textual.screen import ModalScreen
        from textual.widgets import (
            Button,
            Footer,
            Label,
            ListItem,
            ListView,
            RichLog,
            Select,
            Static,
            TextArea,
            Input,
        )
    except ImportError as exc:
        raise RuntimeError("Textual is required; install the 'tui' extra") from exc

    class ComposerTextArea(TextArea):
        """Text area with Agent-style Enter/Shift+Enter semantics."""

        class Submitted(Message):
            def __init__(self, value: str) -> None:
                self.value = value
                super().__init__()

        async def _on_key(self, event: events.Key) -> None:
            if event.key == "enter":
                event.stop()
                event.prevent_default()
                self.post_message(self.Submitted(self.text))
                return
            if event.key == "shift+enter":
                event.stop()
                event.prevent_default()
                start, end = self.selection
                self._replace_via_keyboard("\n", start, end)
                return
            await super()._on_key(event)

    class NewSessionScreen(ModalScreen[dict[str, object] | None]):
        CSS = """
        NewSessionScreen {
            align: center middle;
            background: $background 55%;
        }
        #new-session-dialog {
            width: 68;
            height: auto;
            padding: 1 2;
            border: solid #3d716a;
            background: #151c1a;
        }
        #new-session-dialog Input,
        #new-session-dialog Select {
            margin-bottom: 1;
        }
        #new-session-actions {
            height: 3;
            align-horizontal: right;
        }
        #new-session-actions Button {
            margin-left: 1;
        }
        """

        def compose(self) -> ComposeResult:
            with Vertical(id="new-session-dialog"):
                yield Static("新建开发 Session", classes="dialog-title")
                yield Label("标题")
                yield Input(value="新开发对话", id="new-session-title")
                yield Label("工作目录")
                yield Input(value=str(Path.cwd()), id="new-session-workspace")
                yield Label("执行权限")
                yield Select(
                    [
                        ("逐次确认（推荐）", "per_action"),
                        ("只读", "read_only"),
                        ("工作区托管（显式授权当前目录）", "workspace_managed"),
                    ],
                    value="per_action",
                    allow_blank=False,
                    id="new-session-execution",
                )
                yield Static(
                    "不会自动启用 full trust。工作区托管只授权上方目录。",
                    classes="muted",
                )
                with Horizontal(id="new-session-actions"):
                    yield Button("取消", id="new-session-cancel")
                    yield Button("创建 Session", variant="primary", id="new-session-submit")

        def on_mount(self) -> None:
            self.query_one("#new-session-title", Input).focus()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "new-session-cancel":
                self.dismiss(None)
                return
            title = self.query_one("#new-session-title", Input).value.strip()
            workspace = self.query_one("#new-session-workspace", Input).value.strip()
            execution = str(
                self.query_one("#new-session-execution", Select).value
                or "per_action"
            )
            if not workspace:
                self.query_one("#new-session-workspace", Input).focus()
                return
            payload: dict[str, object] = {
                "title": title or "新开发对话",
                "mode": "coordinator",
                "executionMode": execution,
                "workspaceRoots": [workspace],
            }
            if execution == "workspace_managed":
                payload["workspaceScopeConfirmation"] = "APPROVE_WORKSPACE_SCOPE"
            self.dismiss(payload)

    class AgentTui(App[None]):
        TITLE = "PAW — Pi 对话 Agent"
        CSS = """
        Screen {
            background: #0e1312;
            color: #e8eee9;
        }
        #workspace {
            height: 1fr;
        }
        #sidebar {
            width: 31;
            min-width: 24;
            border-right: solid #283b37;
            background: #121817;
        }
        .rail-title {
            height: 3;
            padding: 1 1 0 1;
            color: #a8c9c1;
            text-style: bold;
        }
        #sessions-pager, #rooms-pager {
            height: 2;
            padding: 0 1;
            color: #78908a;
        }
        #sessions, #rooms {
            height: 1fr;
            background: transparent;
            border: none;
        }
        #rooms-pane {
            display: none;
        }
        ListItem {
            padding: 0 1;
        }
        ListItem.--highlight {
            background: #1d302c;
            color: #f4fbf7;
        }
        #conversation {
            width: 1fr;
            padding: 0 1;
        }
        #session-header {
            height: 4;
            padding: 1 1 0 1;
            color: #d9eee8;
            text-style: bold;
            border-bottom: solid #283b37;
        }
        #transcript {
            height: 1fr;
            padding: 1 2;
            background: #101615;
            scrollbar-color: #41675f;
            scrollbar-background: #111a18;
        }
        #inspector {
            display: none;
            max-height: 9;
            padding: 1 2;
            border-top: solid #283b37;
            color: #b9cbc6;
            background: #121a18;
        }
        #action-status {
            height: 2;
            padding: 0 1;
            color: #9fc4bb;
        }
        #composer-hint {
            height: 2;
            padding: 0 1;
            color: #78908a;
        }
        #prompt-input {
            height: 7;
            min-height: 5;
            border: solid #36564f;
            background: #141c1a;
            color: #edf5f0;
            padding: 0 1;
        }
        #prompt-input:focus {
            border: solid #5ca99a;
        }
        #prompt-input:disabled {
            color: #65736f;
            border: solid #28332f;
        }
        .help {
            height: 2;
            padding: 0 1;
            color: #697d77;
        }
        .muted {
            color: #82918d;
        }
        .dialog-title {
            margin-bottom: 1;
            text-style: bold;
            color: #d8efe8;
        }
        """
        BINDINGS = [
            ("r", "refresh", "Refresh"),
            ("j", "next_item", "Next"),
            ("k", "prev_item", "Prev"),
            ("n", "next_page", "Next Page"),
            ("p", "prev_page", "Prev Page"),
            ("t", "focus_sessions", "Sessions"),
            ("y", "focus_rooms", "Rooms"),
            ("d", "detail", "Detail"),
            ("ctrl+l", "focus_input", "Message"),
            ("ctrl+s", "steer", "Steer"),
            ("ctrl+g", "abort", "Stop"),
            ("ctrl+n", "new_session", "New Session"),
            ("ctrl+i", "toggle_inspector", "Inspector"),
            ("escape", "focus_active_list", "List"),
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
            self._last_snapshot: dict[str, object] = {
                "sessions": [],
                "rooms": [],
                "activeSessionId": "",
            }
            self._command_catalog_payload: dict[str, object] = {"items": []}
            self._context_session_id = ""
            self._context_in_flight: set[str] = set()
            self._message_payloads: dict[str, dict[str, object]] = {}
            self._context_fingerprints: dict[str, str] = {}
            self._transcript_entries: list[TranscriptEntry] = []
            self._last_action_status = "正在连接本机 Pi Runtime…"
            self._input_draft = ""
            self._drafts: dict[str, str] = {}
            self._composer_session_id = ""
            self._focus_target = "sessions"
            self._prompt_in_flight = False
            self._retry_request: tuple[str, str, str, str] | None = None
            self._pending_select_session_id = ""
            self._inspector_visible = False

        def compose(self) -> ComposeResult:
            data = self._last_snapshot
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

            selected_session = (
                active_session_page[self._selected_session_index]
                if active_session_page
                else None
            )
            selected_id = (
                str(selected_session.get("id") or "")
                if selected_session and self._active_panel == "sessions"
                else ""
            )
            selected_payload = self._message_payloads.get(selected_id, {})
            session_rows = [
                ListItem(Label(_render_session(item, active_session_id)))
                for item in active_session_page
            ]
            room_rows = [
                ListItem(Label(_render_room(item)))
                for item in active_room_page
            ]

            with Horizontal(id="workspace"):
                with Vertical(id="sidebar"):
                    with Vertical(id="sessions-pane"):
                        yield Static("SESSIONS  ·  Ctrl+N 新建", classes="rail-title")
                        yield Static(
                            _build_pager(
                                "Sessions",
                                self._session_page,
                                self._session_page_size,
                                len(sessions),
                            ),
                            id="sessions-pager",
                        )
                        yield ListView(
                            *session_rows,
                            initial_index=(
                                self._selected_session_index if session_rows else None
                            ),
                            id="sessions",
                        )
                    with Vertical(id="rooms-pane"):
                        yield Static("ROOMS  ·  只读协作视图", classes="rail-title")
                        yield Static(
                            _build_pager(
                                "Rooms",
                                self._room_page,
                                self._room_page_size,
                                len(rooms),
                            ),
                            id="rooms-pager",
                        )
                        yield ListView(
                            *room_rows,
                            initial_index=(self._selected_room_index if room_rows else None),
                            id="rooms",
                        )
                with Vertical(id="conversation"):
                    yield Static(
                        _session_heading(selected_session, selected_payload),
                        id="session-header",
                    )
                    yield RichLog(
                        wrap=True,
                        markup=False,
                        highlight=False,
                        auto_scroll=True,
                        id="transcript",
                    )
                    yield Static("", id="inspector")
                    yield Static(self._last_action_status, id="action-status")
                    yield Static(
                        (
                            "Enter 发送 · Shift+Enter 换行 · Ctrl+S Steer · Ctrl+G Stop"
                            if selected_id
                            else "选择 Session 后开始对话；Room 视图不发送普通 Prompt"
                        ),
                        id="composer-hint",
                    )
                    yield ComposerTextArea(
                        self._drafts.get(selected_id, self._input_draft),
                        soft_wrap=True,
                        tab_behavior="indent",
                        disabled=not bool(selected_id),
                        id="prompt-input",
                    )
                    yield Static(
                        "t Session · y Room · j/k 选择 · Ctrl+L 输入 · Ctrl+I 检查器 · r 刷新",
                        classes="help",
                    )
            yield Footer()

        def on_mount(self) -> None:
            self.action_refresh()
            self.set_interval(1.25, self._poll_selected_context)

        def _run_snapshot_refresh(self) -> None:
            try:
                data = snapshot(
                    self._service,
                    session_limit=500,
                    room_limit=200,
                )
            except Exception as exc:
                self.call_from_thread(self._apply_snapshot_error, str(exc))
            else:
                self.call_from_thread(self._apply_snapshot, data)

        def _apply_snapshot_error(self, message: str) -> None:
            self._last_action_status = f"连接失败：{message}"
            self._set_text("#action-status", self._last_action_status)

        def _apply_snapshot(self, data: dict[str, object]) -> None:
            self._store_current_draft()
            self._composer_session_id = ""
            self._last_snapshot = data
            sessions = list(data.get("sessions") or [])
            rooms = list(data.get("rooms") or [])
            if self._pending_select_session_id:
                for position, session in enumerate(sessions):
                    if (
                        isinstance(session, Mapping)
                        and str(session.get("id") or "")
                        == self._pending_select_session_id
                    ):
                        self._session_page = position // self._session_page_size
                        self._selected_session_index = position % self._session_page_size
                        break
                self._pending_select_session_id = ""
            session_page, self._session_page = _slice_page(
                sessions,
                self._session_page,
                self._session_page_size,
            )
            room_page, self._room_page = _slice_page(
                rooms,
                self._room_page,
                self._room_page_size,
            )
            self._selected_session_index = min(
                self._selected_session_index,
                max(0, len(session_page) - 1),
            )
            self._selected_room_index = min(
                self._selected_room_index,
                max(0, len(room_page) - 1),
            )
            self._last_action_status = "已连接；选择 Session 后可直接对话。"
            self.refresh(recompose=True)
            self.call_after_refresh(self._after_recompose)

        def _after_recompose(self) -> None:
            self._sync_panel_visibility()
            self._sync_inspector_visibility()
            self._update_selected_projection()
            if self._focus_target == "input" and self._active_panel == "sessions":
                self.action_focus_input()
            else:
                self.action_focus_active_list()

        def _selected_payload(self) -> dict[str, object] | None:
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
            list_view = self._active_list()
            if list_view is not None and list_view.index is not None:
                list_view.index = min(list_view.index + 1, max(0, len(list_view) - 1))

        def action_prev_item(self) -> None:
            list_view = self._active_list()
            if list_view is not None and list_view.index is not None:
                list_view.index = max(0, list_view.index - 1)

        def action_next_page(self) -> None:
            if self._active_panel == "sessions":
                total = len(self._last_snapshot["sessions"])
                max_page = max(0, (total - 1) // self._session_page_size)
                if self._session_page < max_page:
                    self._session_page += 1
                    self._selected_session_index = 0
                    self.action_refresh()
            else:
                total = len(self._last_snapshot["rooms"])
                max_page = max(0, (total - 1) // self._room_page_size)
                if self._room_page < max_page:
                    self._room_page += 1
                    self._selected_room_index = 0
                    self.action_refresh()

        def action_prev_page(self) -> None:
            if self._active_panel == "sessions":
                if self._session_page > 0:
                    self._session_page -= 1
                    self._selected_session_index = 0
                    self.action_refresh()
            else:
                if self._room_page > 0:
                    self._room_page -= 1
                    self._selected_room_index = 0
                    self.action_refresh()

        def action_focus_sessions(self) -> None:
            self._store_current_draft()
            self._active_panel = "sessions"
            self._focus_target = "sessions"
            self._sync_panel_visibility()
            self._update_selected_projection()
            self.action_focus_active_list()

        def action_focus_rooms(self) -> None:
            self._store_current_draft()
            self._active_panel = "rooms"
            self._focus_target = "rooms"
            self._sync_panel_visibility()
            self._update_selected_projection()
            self.action_focus_active_list()

        def action_detail(self) -> None:
            self.action_toggle_inspector()

        def action_toggle_inspector(self) -> None:
            self._inspector_visible = not self._inspector_visible
            self._sync_inspector_visibility()

        def _sync_panel_visibility(self) -> None:
            try:
                self.query_one("#sessions-pane", Vertical).styles.display = (
                    "block" if self._active_panel == "sessions" else "none"
                )
                self.query_one("#rooms-pane", Vertical).styles.display = (
                    "block" if self._active_panel == "rooms" else "none"
                )
            except Exception:
                pass

        def _sync_inspector_visibility(self) -> None:
            try:
                self.query_one("#inspector", Static).styles.display = (
                    "block" if self._inspector_visible else "none"
                )
            except Exception:
                pass

        def action_refresh(self) -> None:
            self._last_action_status = "正在刷新本机 Pi Runtime…"
            self._set_text("#action-status", self._last_action_status)
            self.run_worker(
                self._run_snapshot_refresh,
                group="snapshot",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _active_list(self) -> Any | None:
            selector = "#sessions" if self._active_panel == "sessions" else "#rooms"
            try:
                return self.query_one(selector, ListView)
            except Exception:
                return None

        def action_focus_active_list(self) -> None:
            list_view = self._active_list()
            if list_view is not None:
                list_view.focus()

        def action_focus_input(self) -> None:
            if self._active_panel != "sessions":
                return
            try:
                field = self.query_one("#prompt-input", ComposerTextArea)
            except Exception:
                return
            if not field.disabled:
                self._focus_target = "input"
                field.focus()

        def _selected_session_id(self) -> str:
            if self._active_panel != "sessions":
                return ""
            selected = self._selected_payload()
            return str(selected.get("id") or "") if selected else ""

        def _set_text(self, selector: str, value: str) -> None:
            try:
                self.query_one(selector, Static).update(value)
            except Exception:
                pass

        def _store_current_draft(self) -> None:
            if not self._composer_session_id:
                return
            try:
                value = self.query_one("#prompt-input", ComposerTextArea).text
            except Exception:
                return
            self._drafts[self._composer_session_id] = value
            self._input_draft = value

        def _move_composer_to_end(self, field: ComposerTextArea) -> None:
            lines = field.text.split("\n")
            field.move_cursor((len(lines) - 1, len(lines[-1])))

        def _update_selected_projection(self) -> None:
            selected = self._selected_payload()
            self._store_current_draft()
            try:
                field = self.query_one("#prompt-input", ComposerTextArea)
            except Exception:
                field = None
            session_id = self._selected_session_id()
            if field is not None:
                field.disabled = not bool(session_id)
                if session_id != self._composer_session_id:
                    field.text = self._drafts.get(session_id, "")
                    self._move_composer_to_end(field)
                self._composer_session_id = session_id
            if session_id:
                message_payload = self._message_payloads.get(session_id, {})
                self._set_text(
                    "#session-header",
                    _session_heading(selected, message_payload),
                )
                self._set_text(
                    "#composer-hint",
                    "Enter 发送 · Shift+Enter 换行 · Ctrl+S Steer · Ctrl+G Stop",
                )
                if message_payload:
                    self._render_transcript(session_id, message_payload)
                    self._set_text(
                        "#inspector",
                        _inspector_text(
                            message_payload,
                            self._command_catalog_payload,
                        ),
                    )
                else:
                    self._render_loading_transcript()
                self._refresh_selected_context()
            else:
                self._context_session_id = ""
                self._set_text(
                    "#session-header",
                    (
                        _detail_text(selected, "room")
                        if selected
                        else "Room 是只读协作投影"
                    ),
                )
                self._set_text(
                    "#composer-hint",
                    "Room 视图不发送普通 Session Prompt；按 t 返回对话",
                )
                self._render_room_placeholder()

        def _render_loading_transcript(self) -> None:
            try:
                transcript = self.query_one("#transcript", RichLog)
            except Exception:
                return
            transcript.clear()
            transcript.write(Text("正在读取 Session 消息与运行事件…", style="dim"))

        def _render_room_placeholder(self) -> None:
            try:
                transcript = self.query_one("#transcript", RichLog)
            except Exception:
                return
            transcript.clear()
            transcript.write(
                Panel(
                    "这里仅查看 Room/WorkItem 投影。普通对话、Steer 与 Stop 始终属于具体 Pi Session。",
                    title="Room",
                    border_style="#36564f",
                )
            )

        def _render_transcript(
            self,
            session_id: str,
            payload: Mapping[str, object],
        ) -> None:
            entries = _project_transcript(payload, session_id)
            self._transcript_entries = entries
            try:
                transcript = self.query_one("#transcript", RichLog)
            except Exception:
                return
            transcript.clear()
            palette = {
                "message": "#5ca99a",
                "thinking": "#7192b8",
                "tool": "#a68b52",
                "approval": "#d39a52",
                "input": "#d39a52",
                "error": "#d76d78",
                "terminal": "#d76d78",
                "background": "#7192b8",
                "empty": "#526d66",
            }
            for entry in entries:
                title = Text(entry.title, style=f"bold {palette.get(entry.kind, '#9eb4ae')}")
                if entry.status:
                    title.append(f"  {entry.status}", style="dim")
                body = Text(entry.body or "（无内容）")
                transcript.write(
                    Panel(
                        Group(title, body),
                        border_style=palette.get(entry.kind, "#36564f"),
                        padding=(0, 1),
                    )
                )
            transcript.scroll_end(animate=False)

        def _refresh_selected_context(self) -> None:
            session_id = self._selected_session_id()
            if not session_id or session_id in self._context_in_flight:
                return
            self._context_session_id = session_id
            self._context_in_flight.add(session_id)
            self.run_worker(
                lambda: self._run_context_refresh(session_id),
                group=f"session-context:{session_id}",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _poll_selected_context(self) -> None:
            if self._active_panel == "sessions":
                self._refresh_selected_context()

        def _run_context_refresh(self, session_id: str) -> None:
            try:
                message_payload = self._service.messages(session_id)
                catalog_payload = self._service.command_catalog(session_id)
            except Exception as exc:
                self.call_from_thread(
                    self._apply_context_error,
                    session_id,
                    str(exc),
                )
            else:
                self.call_from_thread(
                    self._apply_context,
                    session_id,
                    dict(message_payload),
                    dict(catalog_payload),
                )

        def _apply_context(
            self,
            session_id: str,
            message_payload: dict[str, object],
            catalog_payload: dict[str, object],
        ) -> None:
            self._context_in_flight.discard(session_id)
            self._message_payloads[session_id] = message_payload
            if session_id != self._selected_session_id():
                return
            self._command_catalog_payload = catalog_payload
            fingerprint = json.dumps(
                {
                    "items": message_payload.get("items", message_payload.get("messages", [])),
                    "status": message_payload.get("status"),
                    "liveEvents": message_payload.get("liveEvents"),
                    "messageQueue": message_payload.get("messageQueue"),
                    "backgroundJobs": message_payload.get("backgroundJobs"),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if self._context_fingerprints.get(session_id) != fingerprint:
                self._context_fingerprints[session_id] = fingerprint
                self._render_transcript(session_id, message_payload)
            self._set_text(
                "#session-header",
                _session_heading(self._selected_payload(), message_payload),
            )
            self._set_text(
                "#inspector",
                _inspector_text(message_payload, catalog_payload),
            )

        def _apply_context_error(self, session_id: str, message: str) -> None:
            self._context_in_flight.discard(session_id)
            if session_id != self._selected_session_id():
                return
            self._last_action_status = f"读取 Session 失败：{message}；按 r 重试。"
            self._set_text("#action-status", self._last_action_status)

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            index = event.list_view.index
            if index is None:
                return
            if event.list_view.id == "sessions":
                self._selected_session_index = index
                if event.list_view.has_focus:
                    self._active_panel = "sessions"
                    self._focus_target = "sessions"
                    self._update_selected_projection()
            elif event.list_view.id == "rooms":
                self._selected_room_index = index
                if event.list_view.has_focus:
                    self._active_panel = "rooms"
                    self._focus_target = "rooms"
                    self._update_selected_projection()

        def _deliver(self, delivery: str) -> None:
            session_id = self._selected_session_id()
            if not session_id:
                self._last_action_status = "请先按 t 并选择一个 Session。"
                self._set_text("#action-status", self._last_action_status)
                return
            field = self.query_one("#prompt-input", ComposerTextArea)
            text = field.text.strip()
            if not text:
                return
            if delivery == "prompt" and self._prompt_in_flight:
                self._last_action_status = (
                    "当前 Pi 回合仍在运行；可输入补充内容后按 Ctrl+S 干预。"
                )
                self._set_text("#action-status", self._last_action_status)
                return
            key = (session_id, text, delivery)
            if self._retry_request and self._retry_request[:3] == key:
                client_message_id = self._retry_request[3]
            else:
                client_message_id = f"tui:{uuid.uuid4()}"
            if delivery == "prompt":
                self._prompt_in_flight = True
            self._focus_target = "input"
            self._input_draft = ""
            self._drafts[session_id] = ""
            field.text = ""
            self._last_action_status = (
                "正在请求 Pi Session；可继续输入并按 Ctrl+S 干预…"
                if delivery == "prompt"
                else "正在把补充内容送入当前 Pi 回合…"
            )
            self._set_text("#action-status", self._last_action_status)
            self.run_worker(
                lambda: self._run_delivery(
                    session_id,
                    text,
                    delivery,
                    client_message_id,
                ),
                group="prompt" if delivery == "prompt" else "steer",
                exclusive=delivery == "prompt",
                thread=True,
                exit_on_error=False,
            )

        def _run_delivery(
            self,
            session_id: str,
            text: str,
            delivery: str,
            client_message_id: str,
        ) -> None:
            try:
                status = ""
                if text.startswith("/"):
                    catalog_payload = self._service.command_catalog(session_id)
                    source = _command_source_from_payload(catalog_payload, text)
                    if source == "extension":
                        receipt = self._service.invoke_command(
                            session_id,
                            {"command": text},
                        )
                        status = _render_command_result(receipt)
                    elif source in {"skill", "prompt"}:
                        self._service.prompt(
                            session_id,
                            {
                                "message": text,
                                "delivery": delivery,
                                "clientMessageId": client_message_id,
                            },
                        )
                    else:
                        raise ValueError(
                            "该 Pi 命令不可用；请先安装或启用拥有它的 Package"
                        )
                else:
                    self._service.prompt(
                        session_id,
                        {
                            "message": text,
                            "delivery": delivery,
                            "clientMessageId": client_message_id,
                        },
                    )
                self.call_from_thread(
                    self._complete_delivery,
                    True,
                    session_id,
                    text,
                    delivery,
                    client_message_id,
                    status,
                )
            except Exception as exc:
                self.call_from_thread(
                    self._complete_delivery,
                    False,
                    session_id,
                    text,
                    delivery,
                    client_message_id,
                    str(exc),
                )

        def _complete_delivery(
            self,
            succeeded: bool,
            session_id: str,
            text: str,
            delivery: str,
            client_message_id: str,
            detail: str,
        ) -> None:
            if delivery == "prompt":
                self._prompt_in_flight = False
            if succeeded:
                self._retry_request = None
                self._last_action_status = detail or (
                    "Pi Session 已接收干预。"
                    if delivery == "steer"
                    else "Pi 回合已返回；消息记录已刷新。"
                )
            else:
                self._retry_request = (
                    session_id,
                    text,
                    delivery,
                    client_message_id,
                )
                self._last_action_status = (
                    f"发送未完成：{detail} 同文重试会复用原消息编号。"
                )
                try:
                    field = self.query_one("#prompt-input", ComposerTextArea)
                except Exception:
                    field = None
                if field is not None and not field.text:
                    self._input_draft = text
                    self._drafts[session_id] = text
                    field.text = text
                    self._move_composer_to_end(field)
            self._set_text("#action-status", self._last_action_status)
            if session_id == self._selected_session_id():
                self._refresh_selected_context()

        def action_send(self) -> None:
            self._deliver("prompt")

        def action_steer(self) -> None:
            self._deliver("steer")

        def action_abort(self) -> None:
            session_id = self._selected_session_id()
            if not session_id:
                self._last_action_status = "请先选择要停止的 Session。"
                self._set_text("#action-status", self._last_action_status)
                return
            self._last_action_status = "正在请求 Pi 停止当前回合…"
            self._set_text("#action-status", self._last_action_status)
            self.run_worker(
                lambda: self._run_abort(session_id),
                group=f"abort:{session_id}",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _run_abort(self, session_id: str) -> None:
            try:
                self._service.abort(session_id)
            except Exception as exc:
                self.call_from_thread(
                    self._complete_abort,
                    session_id,
                    False,
                    str(exc),
                )
            else:
                self.call_from_thread(
                    self._complete_abort,
                    session_id,
                    True,
                    "",
                )

        def _complete_abort(
            self,
            session_id: str,
            succeeded: bool,
            detail: str,
        ) -> None:
            self._prompt_in_flight = False
            self._last_action_status = (
                "已请求 Pi 停止；等待权威终态。"
                if succeeded
                else f"停止失败：{detail}"
            )
            self._set_text("#action-status", self._last_action_status)
            if session_id == self._selected_session_id():
                self._refresh_selected_context()

        def action_new_session(self) -> None:
            self.push_screen(NewSessionScreen(), self._begin_create_session)

        def _begin_create_session(
            self,
            payload: dict[str, object] | None,
        ) -> None:
            if payload is None:
                return
            self._last_action_status = "正在创建绑定工作区的 Pi Session…"
            self._set_text("#action-status", self._last_action_status)
            self.run_worker(
                lambda: self._run_create_session(payload),
                group="create-session",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _run_create_session(self, payload: Mapping[str, object]) -> None:
            try:
                receipt = self._service.create_session(payload)
            except Exception as exc:
                self.call_from_thread(self._complete_create_session, "", str(exc))
                return
            session = receipt.get("session")
            session_id = (
                str(session.get("id") or "")
                if isinstance(session, Mapping)
                else ""
            )
            self.call_from_thread(self._complete_create_session, session_id, "")

        def _complete_create_session(self, session_id: str, error: str) -> None:
            if error:
                self._last_action_status = f"创建 Session 失败：{error}"
                self._set_text("#action-status", self._last_action_status)
                return
            self._active_panel = "sessions"
            self._pending_select_session_id = session_id
            self._last_action_status = "Session 已创建，正在载入对话。"
            self.action_refresh()

        def on_composer_text_area_submitted(
            self,
            event: ComposerTextArea.Submitted,
        ) -> None:
            self._input_draft = event.value
            self._deliver("prompt")

        def on_text_area_changed(self, event: TextArea.Changed) -> None:
            if event.text_area.id != "prompt-input":
                return
            self._input_draft = event.text_area.text
            if self._composer_session_id:
                self._drafts[self._composer_session_id] = event.text_area.text

    return AgentTui()


def main(service: RuntimeFacade | None = None, argv: Sequence[str] | None = None) -> int:
    if service is None:
        parser = argparse.ArgumentParser(description="PAW Agent Sessions/Rooms TUI")
        parser.add_argument("--db-path", default=str(default_db_path()))
        parser.add_argument("--session-page", type=int, default=20)
        parser.add_argument("--room-page", type=int, default=20)
        parser.add_argument("--no-runtime-owner", action="store_true", help="Do not own runtime; just query existing runtime state")
        parser.add_argument(
            "--gateway-url",
            default=default_gateway_url(),
            help="Loopback Agent Gateway used with --no-runtime-owner",
        )
        args = parser.parse_args(argv)
        service = (
            build_gateway_service(gateway_url=args.gateway_url)
            if args.no_runtime_owner
            else build_agent_service(db_path=args.db_path, wake_scheduler=True)
        )
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
    "build_gateway_service",
    "default_db_path",
    "default_gateway_url",
    "GatewayRuntimeFacade",
    "main",
    "snapshot",
    "_render_session",
    "_render_room",
    "_detail_text",
    "_command_help",
    "_command_source",
    "_render_command_result",
    "_project_transcript",
    "_session_heading",
    "_inspector_text",
    "TranscriptEntry",
    "_room_member_count",
]
if __name__ == "__main__":
    raise SystemExit(main())
