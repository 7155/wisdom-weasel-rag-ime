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
        "workspace",
        "workspace-file",
        "events",
        "prompt",
        "rewrite",
        "forks",
        "abort",
        "review",
        "ui-response",
        "compact",
        "commands",
        "models",
        "model",
        "thinking",
        "intercom",
        "debug-context",
        "workflow",
        "goal",
        "knowledge-search",
        "knowledge-read",
    }:
        return "", ""
    return session_id, action

def agent_background_job_route(path: str) -> tuple[str, str, str]:
    prefix = "/api/agent/sessions/"
    if not path.startswith(prefix):
        return "", "", ""
    parts = path[len(prefix) :].strip("/").split("/")
    if len(parts) == 2 and parts[1] == "background-jobs":
        session_id = unquote(parts[0]).strip()
        return (session_id, "", "collection") if session_id else ("", "", "")
    if len(parts) == 3 and parts[1] == "background-jobs":
        session_id = unquote(parts[0]).strip()
        job_id = unquote(parts[2]).strip()
        return (
            (session_id, job_id, "status")
            if session_id and _valid_background_job_id(job_id)
            else ("", "", "")
        )
    if (
        len(parts) == 4
        and parts[1] == "background-jobs"
        and parts[3] in {"logs", "cancel"}
    ):
        session_id = unquote(parts[0]).strip()
        job_id = unquote(parts[2]).strip()
        return (
            (session_id, job_id, parts[3])
            if session_id and _valid_background_job_id(job_id)
            else ("", "", "")
        )
    return "", "", ""

def _valid_background_job_id(value: str) -> bool:
    return (
        len(value) == 35
        and value.startswith("bg_")
        and all(character in "0123456789abcdef" for character in value[3:])
    )


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


def agent_work_document_route(path: str) -> tuple[str, str]:
    prefix = "/api/agent/work-documents/"
    if not path.startswith(prefix):
        return "", ""
    parts = path[len(prefix) :].strip("/").split("/")
    if not parts or parts[:2] == ["history", "search"] or len(parts) > 2:
        return "", ""
    document_id = unquote(parts[0]).strip()
    action = parts[1] if len(parts) == 2 else "detail"
    if (
        len(document_id) != 40
        or not document_id.startswith("workdoc_")
        or action
        not in {"detail", "archive", "repair", "reopen", "erase-preview", "erase"}
    ):
        return "", ""
    return document_id, action


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
    if not media_id or action not in {"receipt", "content", "preview"}:
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
        "steer",
        "abort",
        "snapshot",
        "history",
        "participants",
        "topics",
        "artifacts",
    }:
        return "", ""
    return room_id, action


def agent_collaboration_profile_route(path: str) -> str:
    prefix = "/api/agent/collaboration-profiles/"
    if not path.startswith(prefix):
        return ""
    profile_id = unquote(path[len(prefix) :].strip("/")).strip()
    if not profile_id or "/" in profile_id or profile_id == "commands":
        return ""
    return profile_id


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
