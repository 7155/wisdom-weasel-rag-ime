from __future__ import annotations

from urllib.parse import unquote


def agent_session_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/sessions/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    session_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else ""
    if not session_id or action not in {
        "",
        "messages",
        "events",
        "prompt",
        "rewrite",
        "forks",
        "abort",
        "review",
        "compact",
        "commands",
        "models",
        "model",
        "thinking",
        "intercom",
        "debug-context",
        "workflow",
        "plan",
        "goal",
    }:
        return "", ""
    return session_id, action


def agent_context_item_route(path: str) -> tuple[str, str, str]:
    prefix = "/api/agent/sessions/"
    if not path.startswith(prefix):
        return "", "", ""
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 2 and parts[1] == "context-items":
        session_id = unquote(parts[0]).strip()
        return (session_id, "", "list") if session_id else ("", "", "")
    if len(parts) == 4 and parts[1] == "context-items" and parts[3] == "ack":
        session_id = unquote(parts[0]).strip()
        item_id = unquote(parts[2]).strip()
        return (session_id, item_id, "ack") if session_id and item_id else ("", "", "")
    return "", "", ""


def agent_context_trace_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/sessions/"
    if not path.startswith(prefix):
        return "", ""
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 2 and parts[1] == "context-traces":
        session_id = unquote(parts[0]).strip()
        return (session_id, "") if session_id else ("", "")
    if len(parts) == 3 and parts[1] == "context-traces":
        session_id = unquote(parts[0]).strip()
        trace_id = unquote(parts[2]).strip()
        return (session_id, trace_id) if session_id and trace_id else ("", "")
    return "", ""


def agent_approval_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/approvals/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    approval_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else ""
    if not approval_id or action not in {"", "decision", "external-result"}:
        return "", ""
    return approval_id, action


def agent_media_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/media/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    media_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else "receipt"
    if not media_id or action not in {"receipt", "content"}:
        return "", ""
    return media_id, action


def agent_artifact_route(path: str) -> str:
    prefix = "/api/agent/artifacts/"
    if not path.startswith(prefix):
        return ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder or "/" in remainder:
        return ""
    return unquote(remainder).strip()


def agent_room_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/rooms/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    room_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else ""
    if not room_id or action not in {
        "",
        "events",
        "messages",
        "snapshot",
        "participants",
        "topics",
        "artifacts",
    }:
        return "", ""
    return room_id, action


def agent_room_work_route(path: str) -> tuple[str, str, str]:
    prefix = "/api/agent/rooms/"
    if not path.startswith(prefix):
        return "", "", ""
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 2 and parts[1] == "work-items":
        room_id = unquote(parts[0]).strip()
        return (room_id, "", "collection") if room_id else ("", "", "")
    if len(parts) == 3 and parts[1] == "work-items":
        room_id = unquote(parts[0]).strip()
        work_item_id = unquote(parts[2]).strip()
        return (
            (room_id, work_item_id, "get")
            if room_id and work_item_id
            else ("", "", "")
        )
    if (
        len(parts) == 4
        and parts[1] == "work-items"
        and parts[3] == "reassign"
    ):
        room_id = unquote(parts[0]).strip()
        work_item_id = unquote(parts[2]).strip()
        return (
            (room_id, work_item_id, "reassign")
            if room_id and work_item_id
            else ("", "", "")
        )
    return "", "", ""


def agent_subagent_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/subagents/runs/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    run_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else ""
    if not run_id or action not in {"", "abort", "console", "control"}:
        return "", ""
    return run_id, action


def agent_wake_schedule_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/wake-schedules/"
    if not path.startswith(prefix):
        return "", ""
    remainder = path[len(prefix) :].strip("/")
    if not remainder:
        return "", ""
    parts = remainder.split("/")
    if len(parts) > 2:
        return "", ""
    schedule_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else ""
    if not schedule_id or action not in {"", "runs", "action"}:
        return "", ""
    return schedule_id, action
