#!/usr/bin/env python3
"""Create a private Luna Max candidate for Wayfinder source curation.

This is an offline review tool, not part of the deterministic projection build.
It freezes user-authored session messages and local project documents through a
declared cutoff, removes known injected boilerplate, deduplicates replayed
sessions, and asks Luna Max for a citation-bound candidate.  Raw chat and the
model output stay in a mode-0700 private artifact directory and must never be
committed.  Reviewed Markdown remains the Wayfinder authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from reconstruct_project_field_sources import (
    message_text,
    parse_timestamp,
    primary_files,
    scrub,
    text_blocks,
)


MODEL = "gpt-5.6-luna"
THINKING = "max"
SCHEMA_VERSION = "personal-agent.wayfinder-luna-curation-candidate.v1"
DEFAULT_CUTOFF = "2026-08-04T23:59:59+08:00"
DEFAULT_SINCE = "2026-07-19T00:00:00+08:00"
WAYFINDER_PACKAGE = Path(
    "design-system/rag-ime-control-center/prototypes/room-navigation-wayfinder"
)
MANIFEST_REF = WAYFINDER_PACKAGE / "real-project-reconstruction/reconstruction-manifest.v1.json"
PROJECTION_REF = Path(
    "control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json"
)
PROJECT_FIELD_CONTRACT_REF = Path("design-system/rag-ime-control-center/pages/project-field.md")
SKILL_IDS = (
    "alignment-and-decision",
    "implementation-planning",
    "implementation-execution",
    "quality-gate",
    "independent-review",
)
BOILERPLATE_PREFIXES = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<recommended_plugins>",
    "<permissions instructions>",
)
LOW_SIGNAL_MESSAGES = {
    "hi",
    "hello",
    "你好",
    "进度",
    "进度如何",
    "怎么样了",
    "继续",
}
PROJECT_TERMS = (
    "personal agent workbench",
    "personal-agent-workbench",
    "room",
    "wayfinder",
    "project field",
    "输入法",
    "squirrel",
    "rime",
    "memory",
    "记忆",
    "rag",
    "knowledge",
    "知识库",
    "control center",
    "luna",
    "前端",
    "handoff",
    "技能",
)
WAYFINDER_SIGNAL = re.compile(
    r"wayfinder|project field|岛屿|岛面|当前航程|alignment-and-decision|"
    r"implementation-planning|implementation-execution|test-driven-implementation|"
    r"quality-gate|independent-review|handoff|技能流|模拟技能|确定性投影|manifest|projection",
    re.IGNORECASE,
)
DOCUMENT_SIGNAL = re.compile(
    r"^(?:#{1,4}\s|---$|kind:|status:|as_of:|.*(?:目标|愿景|要求|决定|结论|验收|"
    r"未完成|当前|边界|frontier|fog|wayfinder|room|skill|handoff).*)",
    re.IGNORECASE,
)
ABSOLUTE_PATH = re.compile(r"(?:/Users|/Volumes|/private|/var/folders)/[^\s\]\[<>{}\"']+")
IMAGE_TAG = re.compile(r"<image\b[^>]*>\s*</image>", re.IGNORECASE)
CODEX_ROLLOUT_NAME = re.compile(
    r"^rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-([0-9a-f-]{36})\.jsonl$"
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|token|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)


class CurationError(RuntimeError):
    """Raised when a source freeze or Luna candidate is invalid."""


@dataclass(frozen=True)
class UserEvent:
    timestamp: str
    text: str


@dataclass
class SessionCandidate:
    provider: str
    session_id: str
    ref: str
    timestamp: str
    cwd: str
    events: list[UserEvent]
    source_id: str = ""
    aliases: list[str] | None = None

    def message_digest(self) -> str:
        return sha256_json([sha256_text(event.text) for event in self.events])


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_json(value: Any) -> str:
    return sha256_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CurationError(f"expected a JSON object: {path}")
    return value


def write_private(path: Path, value: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            target.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def normalize_timestamp(value: str, fallback: str) -> str:
    parsed = parse_timestamp(value) or parse_timestamp(fallback)
    if parsed is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def private_text(value: str) -> str:
    compact = scrub(value)
    compact = IMAGE_TAG.sub("[IMAGE OMITTED]", compact)
    compact = ABSOLUTE_PATH.sub("[LOCAL_PATH]", compact)
    for pattern in SECRET_PATTERNS:
        compact = pattern.sub("[REDACTED]", compact)
    return re.sub(r"\s+", " ", compact).strip()


def private_document_text(value: str) -> str:
    """Redact a document without discarding its heading/paragraph structure."""

    return "\n".join(private_text(line) for line in value.splitlines()).strip()


def bounded_document_content(value: str, *, limit: int, target_draft: bool = False) -> str:
    redacted = private_document_text(value)
    if len(redacted) <= limit:
        return redacted
    lines = redacted.splitlines()
    selected: list[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        compact = line.strip()
        if compact and compact not in seen:
            selected.append(line)
            seen.add(compact)

    for line in lines[:80 if target_draft else 35]:
        add(line)
    for line in lines:
        if DOCUMENT_SIGNAL.search(line):
            add(line)
        if sum(len(item) + 1 for item in selected) >= limit - 1200:
            break
    for line in lines[-20:]:
        add(line)
    return "\n".join(selected)[:limit]


def session_excerpt_indexes(events: Sequence[UserEvent], *, limit: int = 20) -> list[int]:
    if len(events) <= limit:
        return list(range(len(events)))
    selected = {0, 1, len(events) - 1}
    selected.update(round(index * (len(events) - 1) / 11) for index in range(12))
    for index, event in enumerate(events):
        if WAYFINDER_SIGNAL.search(event.text):
            selected.add(index)
    ordered = sorted(selected)
    if len(ordered) <= limit:
        return ordered
    signal_indexes = [index for index in ordered if WAYFINDER_SIGNAL.search(events[index].text)]
    anchors = [index for index in ordered if index not in signal_indexes]
    return sorted((signal_indexes[: max(0, limit - len(anchors[:8]))] + anchors[:8])[:limit])


def keep_user_message(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if any(stripped.startswith(prefix) for prefix in BOILERPLATE_PREFIXES):
        return False
    if private_text(stripped).casefold() in LOW_SIGNAL_MESSAGES:
        return False
    return True


def matching_jsonl(
    path: Path,
    pattern: str,
    *,
    maximum: int | None = None,
    fixed: bool = False,
) -> Iterable[dict[str, Any]]:
    """Use ripgrep to avoid JSON-decoding multi-gigabyte tool-result lines."""

    command = ["rg", "--no-line-number", "--color", "never"]
    if fixed:
        command.append("--fixed-strings")
    if maximum is not None:
        command.extend(["--max-count", str(maximum)])
    command.extend([pattern, str(path)])
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode not in {0, 1}:
        raise CurationError(f"cannot scan session {path.name}: {completed.stderr.strip()}")
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def parse_codex_events(path: Path) -> tuple[str, str, str, list[UserEvent]]:
    filename = CODEX_ROLLOUT_NAME.fullmatch(path.name)
    if filename is not None:
        local_time = datetime.strptime(filename.group(1), "%Y-%m-%dT%H-%M-%S").replace(
            tzinfo=ZoneInfo("Asia/Shanghai")
        )
        session_id = filename.group(2)
        session_timestamp = local_time.astimezone(timezone.utc).isoformat()
    else:
        session_id = path.stem
        session_timestamp = ""
    cwd = ""
    events: list[UserEvent] = []
    for item in matching_jsonl(
        path,
        '"type":"response_item","payload":{"type":"message"',
        fixed=True,
    ):
        kind = item.get("type")
        payload = item.get("payload")
        if (
            kind == "response_item"
            and isinstance(payload, dict)
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            text = text_blocks(payload.get("content")).strip()
            if keep_user_message(text):
                events.append(
                    UserEvent(
                        normalize_timestamp(str(item.get("timestamp") or ""), session_timestamp),
                        private_text(text)[:12_000],
                    )
                )
    return session_id or path.stem, session_timestamp, cwd, events


def parse_claude_events(path: Path) -> tuple[str, str, str, list[UserEvent]]:
    session_id = ""
    session_timestamp = ""
    cwd = ""
    events: list[UserEvent] = []
    for item in matching_jsonl(path, '"type":"user"', fixed=True):
        if item.get("type") not in {"user", "assistant"}:
            continue
        session_id = session_id or str(item.get("sessionId") or "")
        cwd = cwd or str(item.get("cwd") or "")
        session_timestamp = session_timestamp or str(item.get("timestamp") or "")
        if item.get("type") == "user":
            text = message_text(item.get("message")).strip()
            if keep_user_message(text):
                events.append(
                    UserEvent(
                        normalize_timestamp(str(item.get("timestamp") or ""), session_timestamp),
                        private_text(text)[:12_000],
                    )
                )
    return session_id or path.stem, session_timestamp, cwd, events


def parse_pi_events(path: Path) -> tuple[str, str, str, list[UserEvent]]:
    session_id = ""
    session_timestamp = ""
    cwd = ""
    events: list[UserEvent] = []
    metadata = next(
        iter(matching_jsonl(path, '"type":"session"', maximum=1, fixed=True)),
        None,
    )
    if isinstance(metadata, dict):
        session_id = str(metadata.get("id") or "")
        cwd = str(metadata.get("cwd") or "")
        session_timestamp = str(metadata.get("timestamp") or "")
    for item in matching_jsonl(path, '"type":"message"', fixed=True):
        kind = item.get("type")
        if kind == "message":
            message = item.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                text = message_text(message).strip()
                if keep_user_message(text):
                    event_timestamp = str(item.get("timestamp") or message.get("timestamp") or "")
                    events.append(
                        UserEvent(
                            normalize_timestamp(event_timestamp, session_timestamp),
                            private_text(text)[:12_000],
                        )
                    )
    return session_id or path.stem, session_timestamp, cwd, events


def probe_session(path: Path, provider: str) -> tuple[str, str]:
    """Read only the first identity-bearing record before scanning user lines."""

    if provider == "codex":
        filename = CODEX_ROLLOUT_NAME.fullmatch(path.name)
        if filename is not None:
            local_time = datetime.strptime(filename.group(1), "%Y-%m-%dT%H-%M-%S").replace(
                tzinfo=ZoneInfo("Asia/Shanghai")
            )
            return filename.group(2), local_time.astimezone(timezone.utc).isoformat()
        item = next(
            iter(matching_jsonl(path, '"type":"session_meta"', maximum=1, fixed=True)),
            None,
        )
        payload = item.get("payload") if isinstance(item, dict) else None
        if isinstance(payload, dict):
            return str(payload.get("id") or path.stem), str(item.get("timestamp") or "")
    elif provider == "claude-code":
        item = next(
            iter(matching_jsonl(path, '"type":"user"', maximum=1, fixed=True)),
            None,
        )
        if isinstance(item, dict):
            return str(item.get("sessionId") or path.stem), str(item.get("timestamp") or "")
    else:
        item = next(
            iter(matching_jsonl(path, '"type":"session"', maximum=1, fixed=True)),
            None,
        )
        if isinstance(item, dict):
            return str(item.get("id") or path.stem), str(item.get("timestamp") or "")
    return path.stem, ""


def source_items(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    project = manifest.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("rooms"), list):
        raise CurationError("manifest.project.rooms is invalid")
    result: dict[str, dict[str, Any]] = {}
    for room in project["rooms"]:
        if not isinstance(room, dict) or not isinstance(room.get("sources"), list):
            continue
        for source in room["sources"]:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            ref = source.get("ref")
            if isinstance(source_id, str) and isinstance(ref, str):
                result[ref] = dict(source)
    return result


def session_roots() -> tuple[tuple[str, Path], ...]:
    return (
        ("codex", Path.home() / ".codex" / "sessions"),
        ("claude-code", Path.home() / ".claude" / "projects"),
        ("pi", Path.home() / ".pi" / "agent" / "sessions"),
        ("omp", Path.home() / ".omp" / "agent" / "sessions"),
    )


def discover_sessions(
    *,
    since: datetime,
    cutoff: datetime,
    new_source_since: datetime,
    selected_refs: Mapping[str, dict[str, Any]],
) -> tuple[list[SessionCandidate], list[dict[str, Any]]]:
    candidates: list[SessionCandidate] = []
    excluded: list[dict[str, Any]] = []
    for provider, root in session_roots():
        for path in primary_files(root, provider, since):
            _probed_id, probed_timestamp = probe_session(path, provider)
            probed_time = parse_timestamp(probed_timestamp)
            if probed_time is not None and not (since <= probed_time <= cutoff):
                # The selected historical corpus begins at --since. A session
                # that started later than the cutoff cannot contain in-range
                # user turns; an older session is intentionally out of scope.
                continue
            is_existing_ref = f"agent-session:{provider}:{_probed_id}" in selected_refs
            if probed_time is not None and probed_time < new_source_since and not is_existing_ref:
                continue
            if provider == "codex":
                session_id, session_timestamp, cwd, events = parse_codex_events(path)
            elif provider == "claude-code":
                session_id, session_timestamp, cwd, events = parse_claude_events(path)
            else:
                session_id, session_timestamp, cwd, events = parse_pi_events(path)
            ref = f"agent-session:{provider}:{session_id}"
            bounded_events = [
                event
                for event in events
                if (parsed := parse_timestamp(event.timestamp)) is not None
                and since <= parsed <= cutoff
            ]
            if not bounded_events:
                continue
            material = "\n".join(event.text for event in bounded_events).casefold()
            is_existing = ref in selected_refs
            is_relevant = any(term in material for term in PROJECT_TERMS)
            if not is_existing and not is_relevant:
                excluded.append({"ref": ref, "reason": "no project-specific user signal"})
                continue
            candidates.append(
                SessionCandidate(
                    provider=provider,
                    session_id=session_id,
                    ref=ref,
                    timestamp=normalize_timestamp(session_timestamp, bounded_events[0].timestamp),
                    cwd=private_text(cwd),
                    events=bounded_events,
                    source_id=str(selected_refs.get(ref, {}).get("id") or ""),
                    aliases=[],
                )
            )

    by_digest: dict[str, SessionCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (item.timestamp, item.ref)):
        digest = candidate.message_digest()
        canonical = by_digest.get(digest)
        if canonical is None:
            if not candidate.source_id:
                candidate.source_id = f"session-{candidate.provider}-{candidate.session_id.split('-')[0]}"
            by_digest[digest] = candidate
        else:
            assert canonical.aliases is not None
            canonical.aliases.append(candidate.ref)
    return list(by_digest.values()), excluded


def git_output(args: Sequence[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise CurationError(f"git {' '.join(args)} failed: {detail.strip()}") from exc
    return completed.stdout


def document_source_id(relative: str, existing: Mapping[str, dict[str, Any]], content: str) -> str:
    source = existing.get(relative)
    if source is not None and isinstance(source.get("id"), str):
        return str(source["id"])
    stem = re.sub(r"[^a-z0-9]+", "-", Path(relative).stem.casefold()).strip("-")[:48]
    return f"doc-{stem}-{sha256_text(content)[:8]}"


def documents_through_cutoff(
    *,
    source_worktree: Path,
    prototype_root: Path,
    cutoff: datetime,
    existing: Mapping[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    cutoff_iso = cutoff.isoformat()
    snapshot_commit = git_output(
        ["rev-list", "-1", f"--before={cutoff_iso}", "HEAD"], source_worktree
    ).strip()
    if not snapshot_commit:
        raise CurationError("no source commit exists before the cutoff")
    documents: list[dict[str, Any]] = []

    readme = git_output(["show", f"{snapshot_commit}:README.md"], source_worktree)
    documents.append(
        {
            "id": document_source_id("README.md", existing, readme),
            "kind": "project-document",
            "ref": "README.md",
            "snapshot": f"git:{snapshot_commit}",
            "sha256": sha256_text(readme),
            "originalByteCount": len(readme.encode("utf-8")),
            "contentExcerpt": bounded_document_content(readme, limit=7_000),
        }
    )

    docs_root = source_worktree / "docs/agent"
    cutoff_epoch = cutoff.timestamp()
    since_epoch = parse_timestamp(DEFAULT_SINCE).timestamp()  # type: ignore[union-attr]
    for path in sorted(docs_root.rglob("*.md")):
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if not (since_epoch <= modified <= cutoff_epoch):
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(source_worktree).as_posix()
        documents.append(
            {
                "id": document_source_id(relative, existing, raw),
                "kind": "project-document",
                "ref": relative,
                "snapshot": datetime.fromtimestamp(modified, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "sha256": sha256_text(raw),
                "originalByteCount": len(raw.encode("utf-8")),
                "contentExcerpt": bounded_document_content(raw, limit=6_000),
            }
        )

    contract = (prototype_root / PROJECT_FIELD_CONTRACT_REF).read_text(encoding="utf-8")
    documents.append(
        {
            "id": document_source_id(PROJECT_FIELD_CONTRACT_REF.as_posix(), existing, contract),
            "kind": "target-draft",
            "ref": PROJECT_FIELD_CONTRACT_REF.as_posix(),
            "snapshot": "current target draft; not historical proof",
            "sha256": sha256_text(contract),
            "originalByteCount": len(contract.encode("utf-8")),
            "contentExcerpt": bounded_document_content(
                contract,
                limit=20_000,
                target_draft=True,
            ),
        }
    )
    for path in sorted((prototype_root / WAYFINDER_PACKAGE).rglob("*.md")):
        relative = path.relative_to(prototype_root).as_posix()
        raw = path.read_text(encoding="utf-8")
        documents.append(
            {
                "id": f"target-{sha256_text(relative)[:10]}",
                "kind": "target-draft",
                "ref": relative,
                "snapshot": "current target draft; not historical proof",
                "sha256": sha256_text(raw),
                "originalByteCount": len(raw.encode("utf-8")),
                "contentExcerpt": bounded_document_content(
                    raw,
                    limit=12_000,
                    target_draft=True,
                ),
            }
        )
    return documents, snapshot_commit


def git_history(
    source_worktree: Path,
    *,
    existing: Mapping[str, dict[str, Any]],
    baseline_commit: str,
    snapshot_commit: str,
) -> list[dict[str, str]]:
    selected: dict[str, str] = {}
    for ref, source in existing.items():
        if not ref.startswith("git:") or not isinstance(source.get("id"), str):
            continue
        sha = git_output(["rev-parse", ref.removeprefix("git:")], source_worktree).strip()
        selected[sha] = str(source["id"])
    if baseline_commit != snapshot_commit:
        new_commits = git_output(
            ["rev-list", "--reverse", f"{baseline_commit}..{snapshot_commit}"], source_worktree
        ).splitlines()
        for sha in new_commits:
            if sha:
                selected.setdefault(sha, f"commit-{sha[:10]}")
    commits: list[dict[str, str]] = []
    for sha, source_id in selected.items():
        raw = git_output(
            ["show", "-s", "--date=iso-strict", "--format=%H%x09%ad%x09%s", sha],
            source_worktree,
        ).strip()
        parts = raw.split("\t", 2)
        if len(parts) == 3:
            commits.append(
                {
                    "id": source_id,
                    "sha": parts[0],
                    "date": parts[1],
                    "subject": private_text(parts[2]),
                }
            )
    return commits


def candidate_schema(cutoff: str) -> dict[str, Any]:
    source_statement = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "evidenceClass": {
                "type": "string",
                "enum": [
                    "user-intent",
                    "project-document",
                    "git-corroboration",
                    "retrospective-synthesis",
                ],
            },
            "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["text", "evidenceClass", "sourceIds"],
        "additionalProperties": False,
    }
    skill_stage = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(SKILL_IDS)},
            "state": {"type": "string", "enum": ["complete", "active", "pending"]},
            "output": {"type": "string"},
            "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["id", "state", "output", "sourceIds"],
        "additionalProperties": False,
    }
    frontier = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "question": {"type": "string"},
            "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["label", "question", "sourceIds"],
        "additionalProperties": False,
    }
    decision = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "basis": {"type": "array", "items": source_statement, "minItems": 1},
            "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["title", "summary", "basis", "sourceIds"],
        "additionalProperties": False,
    }
    room = {
        "type": "object",
        "properties": {
            "roomId": {"type": "string"},
            "whyExists": {"type": "string"},
            "decisions": {"type": "array", "items": decision, "minItems": 1},
            "fog": {"type": "array", "items": source_statement},
            "frontier": frontier,
            "activeSkillStage": {"type": "string", "enum": list(SKILL_IDS)},
            "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": [
            "roomId",
            "whyExists",
            "decisions",
            "fog",
            "frontier",
            "activeSkillStage",
            "sourceIds",
        ],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "schemaVersion": {"type": "string", "const": SCHEMA_VERSION},
            "cutoff": {"type": "string", "const": cutoff},
            "verdict": {"type": "string", "enum": ["ready_to_merge", "needs_human_resolution"]},
            "sourceAudit": {
                "type": "object",
                "properties": {
                    "includedSourceIds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "duplicateSessionGroups": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "canonicalSourceId": {"type": "string"},
                                "aliasRefs": {"type": "array", "items": {"type": "string"}},
                                "reason": {"type": "string"},
                            },
                            "required": ["canonicalSourceId", "aliasRefs", "reason"],
                            "additionalProperties": False,
                        },
                    },
                    "sourceGaps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "impact": {"type": "string"},
                                "sourceIds": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["description", "impact", "sourceIds"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["includedSourceIds", "duplicateSessionGroups", "sourceGaps"],
                "additionalProperties": False,
            },
            "projectMap": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "rooms": {"type": "array", "items": room, "minItems": 1},
                },
                "required": ["destination", "rooms"],
                "additionalProperties": False,
            },
            "currentRoomDocs": {
                "type": "object",
                "properties": {
                    "roomId": {"type": "string", "const": "project-field"},
                    "originalVision": {"type": "array", "items": source_statement, "minItems": 1},
                    "destination": {"type": "string"},
                    "decisions": {"type": "array", "items": decision, "minItems": 2},
                    "fog": {"type": "array", "items": source_statement, "minItems": 1},
                    "frontier": frontier,
                    "skillFlow": {
                        "type": "array",
                        "items": skill_stage,
                        "minItems": len(SKILL_IDS),
                        "maxItems": len(SKILL_IDS),
                    },
                    "fileRecommendations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref": {"type": "string"},
                                "action": {"type": "string", "enum": ["keep", "update", "add", "remove"]},
                                "summary": {"type": "string"},
                                "sourceIds": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                },
                            },
                            "required": ["ref", "action", "summary", "sourceIds"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "roomId",
                    "originalVision",
                    "destination",
                    "decisions",
                    "fog",
                    "frontier",
                    "skillFlow",
                    "fileRecommendations",
                ],
                "additionalProperties": False,
            },
            "conflicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "treatment": {"type": "string"},
                        "sourceIds": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["statement", "treatment", "sourceIds"],
                    "additionalProperties": False,
                },
            },
            "humanReviewQuestions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "schemaVersion",
            "cutoff",
            "verdict",
            "sourceAudit",
            "projectMap",
            "currentRoomDocs",
            "conflicts",
            "humanReviewQuestions",
        ],
        "additionalProperties": False,
    }


def all_source_ids(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"sourceIds", "includedSourceIds"} and isinstance(child, list):
                for source_id in child:
                    if isinstance(source_id, str):
                        yield source_id
            elif key == "canonicalSourceId" and isinstance(child, str):
                yield child
            else:
                yield from all_source_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_source_ids(child)


def validate_candidate(
    candidate: Mapping[str, Any],
    *,
    cutoff: str,
    room_ids: Sequence[str],
    available_source_ids: set[str],
    exact_session_aliases: Mapping[str, Sequence[str]],
) -> None:
    if candidate.get("schemaVersion") != SCHEMA_VERSION or candidate.get("cutoff") != cutoff:
        raise CurationError("Luna candidate identity does not match the requested run")
    project_map = candidate.get("projectMap")
    if not isinstance(project_map, dict) or not isinstance(project_map.get("rooms"), list):
        raise CurationError("Luna candidate projectMap is invalid")
    actual_room_ids = [
        room.get("roomId")
        for room in project_map["rooms"]
        if isinstance(room, dict)
    ]
    if actual_room_ids != list(room_ids):
        raise CurationError(
            f"Luna candidate Room order drifted: expected={list(room_ids)}, actual={actual_room_ids}"
        )
    current = candidate.get("currentRoomDocs")
    if not isinstance(current, dict) or current.get("roomId") != "project-field":
        raise CurationError("Luna candidate current Room is invalid")
    skill_flow = current.get("skillFlow")
    if not isinstance(skill_flow, list) or [
        stage.get("id") for stage in skill_flow if isinstance(stage, dict)
    ] != list(SKILL_IDS):
        raise CurationError("Luna candidate skill flow order drifted")
    unknown = sorted(set(all_source_ids(candidate)) - available_source_ids)
    if unknown:
        raise CurationError(f"Luna candidate cites unknown source IDs: {unknown}")

    source_audit = candidate.get("sourceAudit")
    duplicate_groups = (
        source_audit.get("duplicateSessionGroups")
        if isinstance(source_audit, dict)
        else None
    )
    if not isinstance(duplicate_groups, list):
        raise CurationError("Luna candidate duplicate session groups are invalid")
    alias_owner: dict[str, str] = {}
    for canonical_source_id, aliases in exact_session_aliases.items():
        for alias in aliases:
            if alias in alias_owner:
                raise CurationError(f"source packet repeats exact alias ref: {alias}")
            alias_owner[alias] = canonical_source_id
    observed_alias_owner: dict[str, str] = {}
    for group in duplicate_groups:
        if not isinstance(group, dict):
            raise CurationError("Luna candidate duplicate session group is invalid")
        canonical_source_id = group.get("canonicalSourceId")
        alias_refs = group.get("aliasRefs")
        if not isinstance(canonical_source_id, str) or not isinstance(alias_refs, list):
            raise CurationError("Luna candidate duplicate session group identity is invalid")
        for alias in alias_refs:
            if not isinstance(alias, str):
                raise CurationError("Luna candidate duplicate alias ref is invalid")
            expected_owner = alias_owner.get(alias)
            if expected_owner is None:
                continue
            if canonical_source_id != expected_owner:
                raise CurationError(
                    "Luna candidate reassigned an exact alias ref: "
                    f"{alias} expected={expected_owner} actual={canonical_source_id}"
                )
            if alias in observed_alias_owner:
                raise CurationError(f"Luna candidate repeats exact alias ref: {alias}")
            observed_alias_owner[alias] = canonical_source_id
    missing_aliases = sorted(set(alias_owner) - set(observed_alias_owner))
    if missing_aliases:
        raise CurationError(
            f"Luna candidate omitted exact alias refs from the source packet: {missing_aliases}"
        )


def build_prompt(packet: Mapping[str, Any]) -> str:
    return """你是 Luna Max，只做一次历史资料整理候选，不修改文件、不调用工具。

任务：把 Personal Agent Workbench 截至 2026-08-04 23:59:59 Asia/Shanghai 的聊天记录、项目文档与 Git 旁证，按 Wayfinder 和连续技能流整理。输出必须严格符合给定 JSON Schema。

权威顺序与边界：
1. user-authored session message 只证明用户意图、纠正、选择和验收反馈；不能单独证明实现完成。
2. 截止时存在的 project-document 是需求与已记录状态的主要来源；若文档互相冲突，保留冲突，不自行调和。
3. git-history 和 commit receipt 只作实现旁证；不能代替真实前台或用户验收。
4. target-draft 是当前待整理的 Wayfinder/技能 docs，只是候选，不得反过来证明历史事实。
5. 不按聊天、Spec、Issue、Ticket、代码模块或技能阶段拆 Room。沿用现有 8 个结果型 Room，顺序和 roomId 必须完全保持。
6. 对每个 Room 回答三个问题：为什么存在、已经决定了什么、下一步是什么。Fog 只放仍无法准确落成一个可验证问题的内容。
7. project-field 的技能流固定为 alignment-and-decision → implementation-planning → implementation-execution → quality-gate → independent-review；test-driven-implementation 只作为 implementation-execution 的内层方法，不另建外层阶段。
8. 识别重复会话、环境注入、插件推荐、问候与纯进度催问；它们不应成为决定依据。
9. 所有判断必须引用 packet 中存在的 source id。没有来源就写入 sourceGaps 或 humanReviewQuestions，不得编造。
10. 当前尚无用户对最新岛面的最终视觉验收，不得把自动测试或截图写成用户已接受。
11. packet 中每个 session 的 aliases 是确定性去重结果；duplicateSessionGroups 必须原样保留 alias 与 canonical source id 的映射，不得重新推断或交换 canonical id。语义相似但 digest 不同的会话可以另列，但不能冒充 exact alias。

请输出：
- 截止日的项目 Destination 与 8 个 Room 的 Wayfinder 低分辨率整理；
- current Room project-field 的原始愿景、决定、Fog、唯一 Frontier 与五阶段技能流；
- 对现有模拟 docs 的逐文件 keep/update/add/remove 建议；
- 重复来源、证据缺口、冲突和需要人工决定的问题。

以下是私有、已截断到截止日并去除已知注入噪声的 source packet。不要在输出中复制机器绝对路径或秘密：

""" + json.dumps(packet, ensure_ascii=False, sort_keys=True)


def run_luna(
    *,
    prompt: str,
    schema: Mapping[str, Any],
    artifact_dir: Path,
    codex_bin: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    artifact_dir.chmod(0o700)
    os.umask(0o077)
    prompt_path = artifact_dir / "curation-prompt.txt"
    schema_path = artifact_dir / "curation-schema.json"
    output_path = artifact_dir / "curation-output.json"
    stdout_path = artifact_dir / "curation-stdout.log"
    stderr_path = artifact_dir / "curation-stderr.log"
    receipt_path = artifact_dir / "curation-receipt.json"
    prompt_text = prompt
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    write_private(prompt_path, prompt_text)
    write_private(schema_path, schema_text)
    command = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        MODEL,
        "--config",
        f'model_reasoning_effort="{THINKING}"',
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--cd",
        str(artifact_dir),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "-",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input=prompt_text,
            text=True,
            capture_output=True,
            timeout=max(1.0, timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CurationError(f"Luna Max timed out after {timeout_seconds:.0f}s") from exc
    elapsed = time.monotonic() - started
    write_private(stdout_path, completed.stdout)
    write_private(stderr_path, completed.stderr)
    if completed.returncode != 0:
        raise CurationError(
            f"Luna Max exited {completed.returncode}; private stderr: {stderr_path}"
        )
    try:
        candidate = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CurationError(f"cannot parse Luna output: {exc}") from exc
    if not isinstance(candidate, dict):
        raise CurationError("Luna output must be a JSON object")
    receipt = {
        "schemaVersion": "personal-agent.wayfinder-luna-curation-receipt.v1",
        "model": MODEL,
        "thinking": THINKING,
        "elapsedSeconds": round(elapsed, 3),
        "exitCode": completed.returncode,
        "promptSha256": sha256_text(prompt_text),
        "schemaSha256": sha256_text(schema_text),
        "outputSha256": sha256_text(output_path.read_text(encoding="utf-8")),
    }
    write_private(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return candidate, receipt


def main(argv: Sequence[str] | None = None) -> int:
    script_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-worktree", type=Path, required=True)
    parser.add_argument("--prototype-root", type=Path, default=script_root)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--since", default=DEFAULT_SINCE)
    parser.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout-seconds", type=float, default=1_800.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    since = parse_timestamp(args.since)
    cutoff = parse_timestamp(args.cutoff)
    if since is None or cutoff is None or since >= cutoff:
        raise CurationError("--since and --cutoff must define a valid interval")
    source_worktree = args.source_worktree.expanduser().resolve()
    prototype_root = args.prototype_root.expanduser().resolve()
    artifact_dir = args.artifact_dir.expanduser().resolve()
    if artifact_dir.exists():
        raise CurationError("--artifact-dir must not already exist")
    manifest = read_json(prototype_root / MANIFEST_REF)
    projection = read_json(prototype_root / PROJECTION_REF)
    existing = source_items(manifest)
    curated_at = parse_timestamp(str(manifest.get("curatedAt") or ""))
    if curated_at is None:
        raise CurationError("manifest.curatedAt is invalid")
    sessions, excluded_sessions = discover_sessions(
        since=since,
        cutoff=cutoff,
        new_source_since=curated_at,
        selected_refs=existing,
    )
    documents, snapshot_commit = documents_through_cutoff(
        source_worktree=source_worktree,
        prototype_root=prototype_root,
        cutoff=cutoff,
        existing=existing,
    )
    factual_source = manifest.get("factualSource")
    baseline_commit = (
        str(factual_source.get("gitHead") or "")
        if isinstance(factual_source, dict)
        else ""
    )
    if not baseline_commit:
        raise CurationError("manifest.factualSource.gitHead is invalid")
    commits = git_history(
        source_worktree,
        existing=existing,
        baseline_commit=baseline_commit,
        snapshot_commit=snapshot_commit,
    )
    session_values: list[dict[str, Any]] = []
    for session in sessions:
        excerpt_indexes = session_excerpt_indexes(session.events)
        session_values.append(
            {
                "id": session.source_id,
                "kind": "agent-session",
                "provider": session.provider,
                "ref": session.ref,
                "aliases": session.aliases or [],
                "timestamp": session.timestamp,
                "cwd": session.cwd,
                "userMessageCount": len(session.events),
                "userMessagesSha256": session.message_digest(),
                "userMessageLedger": [
                    {
                        "index": index,
                        "timestamp": event.timestamp,
                        "sha256": sha256_text(event.text),
                    }
                    for index, event in enumerate(session.events)
                ],
                "boundedUserExcerpts": [
                    {
                        "index": index,
                        "timestamp": session.events[index].timestamp,
                        "sha256": sha256_text(session.events[index].text),
                        "text": session.events[index].text[:800],
                    }
                    for index in excerpt_indexes
                ],
            }
        )
    packet = {
        "schemaVersion": "personal-agent.wayfinder-luna-source-packet.v1",
        "cutoff": args.cutoff,
        "sourceSnapshotCommit": snapshot_commit,
        "authorityOrder": [
            "user-authored session intent",
            "project documents present by cutoff",
            "git implementation corroboration",
            "current target draft for reconciliation only",
        ],
        "existingProjectProjection": projection.get("project"),
        "documents": documents,
        "sessions": session_values,
        "gitHistory": commits,
        "excludedSessionMetadata": excluded_sessions,
    }
    source_ids = {
        *(str(item.get("id")) for item in existing.values() if isinstance(item.get("id"), str)),
        *(str(item["id"]) for item in documents),
        *(str(item["id"]) for item in session_values),
        *(str(item["id"]) for item in commits),
    }
    room_ids = [
        str(room.get("id"))
        for room in manifest["project"]["rooms"]
        if isinstance(room, dict)
    ]
    schema = candidate_schema(args.cutoff)
    prompt = build_prompt(packet)
    packet_json = json.dumps(packet, ensure_ascii=False, sort_keys=True)
    summary = {
        "cutoff": args.cutoff,
        "snapshotCommit": snapshot_commit,
        "roomIds": room_ids,
        "documentCount": len(documents),
        "sessionCount": len(session_values),
        "sessionAliasCount": sum(len(item["aliases"]) for item in session_values),
        "userMessageCount": sum(len(item["userMessageLedger"]) for item in session_values),
        "boundedUserExcerptCount": sum(
            len(item["boundedUserExcerpts"]) for item in session_values
        ),
        "commitCount": len(commits),
        "sourcePacketBytes": len(packet_json.encode("utf-8")),
        "promptBytes": len(prompt.encode("utf-8")),
        "sourcePacketSha256": sha256_text(packet_json),
        "promptSha256": sha256_text(prompt),
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    candidate, receipt = run_luna(
        prompt=prompt,
        schema=schema,
        artifact_dir=artifact_dir,
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
    )
    validate_candidate(
        candidate,
        cutoff=args.cutoff,
        room_ids=room_ids,
        available_source_ids=source_ids,
        exact_session_aliases={
            str(item["id"]): tuple(str(alias) for alias in item["aliases"])
            for item in session_values
            if item["aliases"]
        },
    )
    validated_receipt = {
        **receipt,
        **summary,
        "candidateValidated": True,
        "candidateVerdict": candidate.get("verdict"),
    }
    validation_path = artifact_dir / "validated-curation-receipt.json"
    write_private(
        validation_path,
        json.dumps(validated_receipt, ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps(validated_receipt, ensure_ascii=False, indent=2))
    print(f"private candidate: {artifact_dir / 'curation-output.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CurationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
