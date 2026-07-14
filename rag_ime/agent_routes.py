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
        "abort",
        "compact",
        "models",
        "model",
        "thinking",
        "intercom",
    }:
        return "", ""
    return session_id, action


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
    if not room_id or action not in {"", "events", "messages"}:
        return "", ""
    return room_id, action


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
    if not run_id or action not in {"", "abort"}:
        return "", ""
    return run_id, action
