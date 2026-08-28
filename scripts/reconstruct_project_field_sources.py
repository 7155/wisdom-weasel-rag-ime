#!/usr/bin/env python3
"""Build a private, bounded inventory of project-related Agent sessions.

The script never copies tool results or assistant reasoning. By default it emits
only metadata and SHA-256 references for user-authored messages. Pass
``--include-excerpts`` for a local review file; do not commit that output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_TERMS = (
    "personal agent workbench",
    "personal-agent-workbench",
    "main-release",
    "room",
    "control center",
    "输入法",
    "squirrel",
    "rime",
    "memory",
    "记忆",
    "omp",
    "cat cafe",
    "workdocument",
    "prompt",
    "todo",
    "lsp",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|token|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)


@dataclass
class SessionRecord:
    provider: str
    source_path: Path
    session_id: str = ""
    timestamp: str = ""
    cwd: str = ""
    title: str = ""
    user_messages: list[str] = field(default_factory=list)

    def relevance(self, workspace_root: str) -> tuple[int, list[str]]:
        material = "\n".join((self.cwd, self.title, *self.user_messages)).lower()
        hits = [term for term in PROJECT_TERMS if term in material]
        score = len(hits)
        if workspace_root and workspace_root.lower() in material:
            score += 8
            hits.insert(0, "canonical-workspace")
        elif self.cwd.lower().rstrip("/").endswith("/git/learna"):
            score += 1
        return score, list(dict.fromkeys(hits))


def text_blocks(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "")
        if kind not in {"text", "input_text"}:
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    return text_blocks(message.get("content"))


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def iter_jsonl(source_path: Path) -> Iterable[dict[str, Any]]:
    try:
        with source_path.open("r", encoding="utf-8") as source:
            for line in source:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except (OSError, UnicodeError):
        return


def parse_codex(source_path: Path) -> SessionRecord:
    record = SessionRecord("codex", source_path)
    for item in iter_jsonl(source_path):
        kind = item.get("type")
        payload = item.get("payload")
        if kind == "session_meta" and isinstance(payload, dict):
            record.session_id = record.session_id or str(payload.get("id") or "")
            record.cwd = record.cwd or str(payload.get("cwd") or "")
            record.timestamp = record.timestamp or str(item.get("timestamp") or "")
        elif kind == "turn_context" and isinstance(payload, dict):
            record.cwd = record.cwd or str(payload.get("cwd") or "")
        elif kind == "response_item" and isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user":
            text = text_blocks(payload.get("content")).strip()
            if text:
                record.user_messages.append(text)
    return record


def parse_claude(source_path: Path) -> SessionRecord:
    record = SessionRecord("claude-code", source_path)
    for item in iter_jsonl(source_path):
        if item.get("type") not in {"user", "assistant"}:
            continue
        record.session_id = record.session_id or str(item.get("sessionId") or "")
        record.cwd = record.cwd or str(item.get("cwd") or "")
        record.timestamp = record.timestamp or str(item.get("timestamp") or "")
        if item.get("type") == "user":
            text = message_text(item.get("message")).strip()
            if text:
                record.user_messages.append(text)
    return record


def parse_pi_family(source_path: Path, provider: str) -> SessionRecord:
    record = SessionRecord(provider, source_path)
    for item in iter_jsonl(source_path):
        kind = item.get("type")
        if kind == "session":
            record.session_id = record.session_id or str(item.get("id") or "")
            record.cwd = record.cwd or str(item.get("cwd") or "")
            record.title = record.title or str(item.get("title") or "")
            record.timestamp = record.timestamp or str(item.get("timestamp") or "")
        elif kind == "message":
            message = item.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                text = message_text(message).strip()
                if text:
                    record.user_messages.append(text)
    return record


def scrub(value: str) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    for pattern in SECRET_PATTERNS:
        compact = pattern.sub("[REDACTED]", compact)
    return compact


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def primary_files(root: Path, provider: str, since: datetime) -> Iterable[Path]:
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for source_path in root.rglob("*.jsonl"):
        relative = source_path.relative_to(root)
        if provider == "claude-code" and ("subagents" in relative.parts or len(relative.parts) > 2):
            continue
        if provider in {"pi", "omp"} and len(relative.parts) > 2:
            continue
        try:
            modified = datetime.fromtimestamp(source_path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified >= since:
            candidates.append(source_path)
    return sorted(candidates)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--since", default="2026-07-19T00:00:00+00:00")
    parser.add_argument("--minimum-score", type=int, default=2)
    parser.add_argument("--include-excerpts", action="store_true")
    args = parser.parse_args()

    since = parse_timestamp(args.since)
    if since is None:
        raise SystemExit("--since must be an ISO-8601 timestamp")

    roots = (
        ("codex", Path.home() / ".codex" / "sessions", parse_codex),
        ("claude-code", Path.home() / ".claude" / "projects", parse_claude),
        ("pi", Path.home() / ".pi" / "agent" / "sessions", lambda path: parse_pi_family(path, "pi")),
        ("omp", Path.home() / ".omp" / "agent" / "sessions", lambda path: parse_pi_family(path, "omp")),
    )
    sessions: list[dict[str, Any]] = []
    scanned: dict[str, int] = {}
    for provider, root, loader in roots:
        files = list(primary_files(root, provider, since))
        scanned[provider] = len(files)
        for source_path in files:
            record = loader(source_path)
            timestamp = parse_timestamp(record.timestamp)
            if timestamp is not None and timestamp < since:
                continue
            score, hits = record.relevance(args.workspace_root)
            if score < args.minimum_score or not record.user_messages:
                continue
            user_digests = [digest(message) for message in record.user_messages]
            item: dict[str, Any] = {
                "provider": provider,
                "sessionId": record.session_id or source_path.stem,
                "timestamp": record.timestamp,
                "cwd": record.cwd,
                "title": scrub(record.title),
                "userMessageCount": len(record.user_messages),
                "userMessageDigests": user_digests,
                "relevanceScore": score,
                "matchedTerms": hits,
            }
            if args.include_excerpts:
                item["userExcerpts"] = [scrub(message)[:320] for message in record.user_messages]
            sessions.append(item)

    sessions.sort(key=lambda item: (str(item["timestamp"]), str(item["sessionId"])), reverse=True)
    result = {
        "schemaVersion": "personal-agent.project-field-source-inventory.v1",
        "workspaceRoot": args.workspace_root,
        "since": since.isoformat(),
        "scannedPrimarySessions": scanned,
        "matchedSessionCount": len(sessions),
        "sessions": sessions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
