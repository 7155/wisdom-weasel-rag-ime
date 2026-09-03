from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .agent_sessions import AgentSessionStore


IMPORT_SCHEMA_VERSION = "rag-ime.codex-conversation-import.v1"
PROVENANCE_CUSTOM_TYPE = "paw.external-conversation.v1"
IMPORT_FIDELITY = "conversation-text"
_MAX_PI_TRANSCRIPT_BYTES = 64 * 1024 * 1024
_MAX_MESSAGES = 200_000
_MAX_MESSAGE_CHARS = 8 * 1024 * 1024
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INTERNAL_BLOCK_PREFIXES = (
    "<recommended_plugins>",
    "<environment_context>",
    "<skills_instructions>",
    "<apps_instructions>",
    "<plugins_instructions>",
    "<permissions instructions>",
    "<collaboration_mode>",
    "<codex_internal_context",
    "<subagent_notification>",
    "<turn_aborted>",
    "# AGENTS.md instructions",
    "You are Codex,",
    "You are an AI assistant",
    "## Memory\n",
    "MEMORY_SUMMARY",
    "The following is the Codex agent history",
    "The attached pasted text file(s) contain",
)
_TOOL_CALL_TYPES = frozenset(
    {
        "custom_tool_call",
        "function_call",
        "local_shell_call",
        "computer_call",
        "web_search_call",
    }
)
_TOOL_OUTPUT_TYPES = frozenset(
    {
        "custom_tool_call_output",
        "function_call_output",
        "local_shell_call_output",
        "computer_call_output",
    }
)


class CodexConversationImportError(RuntimeError):
    pass


class CodexConversationIncomplete(CodexConversationImportError):
    pass


class CodexConversationConflict(CodexConversationImportError):
    pass


@dataclass(frozen=True)
class CodexConversationMessage:
    role: str
    text: str
    timestamp: str
    timestamp_ms: int
    phase: str = ""
    source_message_id: str = ""
    model: str = ""


@dataclass(frozen=True)
class CodexConversation:
    source_session_id: str
    source_file: str
    source_sha256: str
    cwd: str
    model: str
    started_at: str
    created_at_ms: int
    updated_at_ms: int
    complete: bool
    messages: tuple[CodexConversationMessage, ...]
    omitted_kinds: tuple[str, ...]


@dataclass(frozen=True)
class CodexConversationSource:
    source_session_id: str
    path: Path
    title: str
    indexed: bool
    candidate_count: int


@dataclass(frozen=True)
class CodexConversationDiscovery:
    sources: tuple[CodexConversationSource, ...]
    scanned_paths: int
    unique_files: int
    files_without_session_meta: int
    state_path_mismatches: int
    missing_state_paths: int
    missing_source_roots: tuple[str, ...]


def discover_codex_conversation_sources(
    *,
    source_roots: Iterable[str | Path],
    state_db: str | Path,
) -> CodexConversationDiscovery:
    """Discover one canonical JSONL per embedded Codex Session identity.

    Codex state rows supply titles and preferred paths, but historical rows can
    point at an alias or another rollout after migrations. The session_meta id
    inside each JSONL therefore owns identity; filesystem device/inode identity
    removes local symlink aliases before candidates are selected.
    """

    database = Path(state_db).expanduser()
    if not database.is_file():
        raise CodexConversationImportError("Codex state database is unavailable")
    try:
        with sqlite3.connect(
            f"file:{database.resolve(strict=True).as_posix()}?mode=ro",
            uri=True,
        ) as connection:
            state_rows = connection.execute(
                "SELECT id, rollout_path, title FROM threads"
            ).fetchall()
    except sqlite3.Error as exc:
        raise CodexConversationImportError(
            f"could not read the Codex state database: {exc}"
        ) from exc

    state_index: dict[str, tuple[Path, str]] = {}
    candidate_paths: set[Path] = set()
    for raw_session_id, raw_path, raw_title in state_rows:
        session_id = str(raw_session_id or "").strip()
        if not session_id:
            continue
        path = Path(str(raw_path or "")).expanduser()
        state_index[session_id] = (path, " ".join(str(raw_title or "").split()))
        if str(path):
            candidate_paths.add(path)

    missing_roots: list[str] = []
    for raw_root in source_roots:
        root = Path(raw_root).expanduser()
        if not root.is_dir():
            missing_roots.append(root.as_posix())
            continue
        for directory, _subdirectories, filenames in os.walk(root, followlinks=False):
            parent = Path(directory)
            for filename in filenames:
                if filename.casefold().endswith(".jsonl"):
                    candidate_paths.add(parent / filename)

    physical_files: dict[
        tuple[int, int], tuple[Path, int, int]
    ] = {}
    path_keys: dict[Path, tuple[int, int]] = {}
    for path in candidate_paths:
        try:
            stat = path.stat()
            if not path.is_file():
                continue
            key = (int(stat.st_dev), int(stat.st_ino))
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        path_keys[path] = key
        current = physical_files.get(key)
        candidate = (resolved, int(stat.st_size), int(stat.st_mtime_ns))
        if current is None or candidate[0].as_posix() < current[0].as_posix():
            physical_files[key] = candidate

    embedded_ids: dict[tuple[int, int], str] = {}
    grouped: dict[str, list[tuple[tuple[int, int], Path, int, int]]] = {}
    files_without_session_meta = 0
    for key, (path, size, mtime_ns) in physical_files.items():
        session_id = _embedded_session_id(path)
        embedded_ids[key] = session_id
        if not session_id:
            files_without_session_meta += 1
            continue
        if not _SAFE_SESSION_ID.fullmatch(session_id):
            files_without_session_meta += 1
            continue
        grouped.setdefault(session_id, []).append((key, path, size, mtime_ns))

    state_path_mismatches = 0
    missing_state_paths = 0
    preferred_keys: dict[str, tuple[int, int]] = {}
    for session_id, (path, _title) in state_index.items():
        key = path_keys.get(path)
        if key is None:
            try:
                stat = path.stat()
                key = (int(stat.st_dev), int(stat.st_ino))
            except OSError:
                missing_state_paths += 1
                continue
        embedded_id = embedded_ids.get(key, "")
        if embedded_id == session_id:
            preferred_keys[session_id] = key
        elif embedded_id:
            state_path_mismatches += 1

    sources: list[CodexConversationSource] = []
    for session_id, candidates in grouped.items():
        preferred_key = preferred_keys.get(session_id)
        preferred = next(
            (candidate for candidate in candidates if candidate[0] == preferred_key),
            None,
        )
        chosen = preferred or max(
            candidates,
            key=lambda item: (item[2], item[3], item[1].as_posix()),
        )
        title = state_index.get(session_id, (Path(), ""))[1]
        sources.append(
            CodexConversationSource(
                source_session_id=session_id,
                path=chosen[1],
                title=title,
                indexed=session_id in state_index,
                candidate_count=len(candidates),
            )
        )

    return CodexConversationDiscovery(
        sources=tuple(sorted(sources, key=lambda source: source.source_session_id)),
        scanned_paths=len(candidate_paths),
        unique_files=len(physical_files),
        files_without_session_meta=files_without_session_meta,
        state_path_mismatches=state_path_mismatches,
        missing_state_paths=missing_state_paths,
        missing_source_roots=tuple(sorted(missing_roots)),
    )


def parse_codex_conversation(path: str | Path) -> CodexConversation:
    source = _source_file(path)
    digest = hashlib.sha256()
    source_session_id = ""
    cwd = ""
    current_model = ""
    started_at = ""
    created_at_ms = 0
    updated_at_ms = 0
    complete = False
    messages: list[CodexConversationMessage] = []
    omitted: set[str] = set()
    seen_message_ids: set[str] = set()

    with source.open("rb") as handle:
        for raw_line in handle:
            digest.update(raw_line)
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except (UnicodeDecodeError, json.JSONDecodeError):
                omitted.add("malformed-record")
                continue
            if not isinstance(value, Mapping):
                omitted.add("malformed-record")
                continue
            top_type = str(value.get("type") or "")
            timestamp = _iso_timestamp(value.get("timestamp"))
            timestamp_ms = _timestamp_ms(timestamp)
            if not started_at and timestamp:
                started_at = timestamp
                created_at_ms = timestamp_ms

            payload = value.get("payload")
            payload_map = payload if isinstance(payload, Mapping) else {}
            if top_type == "session_meta":
                if not source_session_id:
                    source_session_id = str(payload_map.get("id") or "").strip()
                    cwd = str(payload_map.get("cwd") or cwd).strip()
                continue
            if top_type == "turn_context":
                cwd = str(payload_map.get("cwd") or cwd).strip()
                current_model = str(payload_map.get("model") or current_model).strip()
                continue
            if top_type == "event_msg":
                if str(payload_map.get("type") or "") == "task_complete":
                    complete = True
                else:
                    omitted.add("runtime-event")
                continue
            if top_type in {"world_state", "session_meta"}:
                continue
            if top_type != "response_item":
                continue

            payload_type = str(payload_map.get("type") or "")
            role = str(payload_map.get("role") or "").strip().lower()
            if payload_type == "reasoning":
                omitted.add("reasoning")
                continue
            if payload_type in _TOOL_CALL_TYPES:
                omitted.add("tool-call")
                continue
            if payload_type in _TOOL_OUTPUT_TYPES:
                omitted.add("tool-output")
                continue
            if payload_type != "message":
                continue
            if role in {"developer", "system"}:
                omitted.add(role)
                continue
            if role not in {"user", "assistant"}:
                omitted.add("non-conversation-message")
                continue

            source_message_id = str(payload_map.get("id") or "").strip()
            if source_message_id and source_message_id in seen_message_ids:
                continue
            text, filtered_context = _message_text(payload_map, role=role)
            if filtered_context:
                omitted.add("runtime-context")
            if not text:
                continue
            if len(messages) >= _MAX_MESSAGES:
                raise CodexConversationImportError(
                    f"Codex conversation exceeds {_MAX_MESSAGES} visible messages"
                )
            if len(text) > _MAX_MESSAGE_CHARS:
                raise CodexConversationImportError(
                    "Codex conversation contains an oversized visible message"
                )
            if source_message_id:
                seen_message_ids.add(source_message_id)
            resolved_timestamp = timestamp or started_at or _epoch_iso()
            resolved_ms = timestamp_ms or created_at_ms or _timestamp_ms(resolved_timestamp)
            messages.append(
                CodexConversationMessage(
                    role=role,
                    text=text,
                    timestamp=resolved_timestamp,
                    timestamp_ms=resolved_ms,
                    phase=str(payload_map.get("phase") or "").strip(),
                    source_message_id=source_message_id,
                    model=current_model,
                )
            )
            updated_at_ms = max(updated_at_ms, resolved_ms)

    if not source_session_id:
        raise CodexConversationImportError("Codex session metadata is missing its id")
    if not _SAFE_SESSION_ID.fullmatch(source_session_id):
        raise CodexConversationImportError("Codex session id is not safe for a Pi transcript")
    if not messages:
        raise CodexConversationImportError("Codex session has no visible conversation messages")
    if not started_at:
        started_at = messages[0].timestamp
        created_at_ms = messages[0].timestamp_ms
    if created_at_ms <= 0:
        created_at_ms = messages[0].timestamp_ms
    if updated_at_ms <= 0:
        updated_at_ms = messages[-1].timestamp_ms
    model = next(
        (message.model for message in reversed(messages) if message.model),
        current_model,
    )
    return CodexConversation(
        source_session_id=source_session_id,
        source_file=source.name,
        source_sha256=digest.hexdigest(),
        cwd=cwd,
        model=model,
        started_at=started_at,
        created_at_ms=created_at_ms,
        updated_at_ms=updated_at_ms,
        complete=complete,
        messages=tuple(messages),
        omitted_kinds=tuple(sorted(omitted)),
    )


def import_codex_conversation(
    path: str | Path,
    *,
    sessions: AgentSessionStore,
    session_dir: str | Path,
    title: str = "",
    allow_incomplete: bool = False,
) -> dict[str, object]:
    conversation = parse_codex_conversation(path)
    if not conversation.complete and not allow_incomplete:
        raise CodexConversationIncomplete(
            f"Codex session {conversation.source_session_id} has no task_complete marker"
        )

    existing = _existing_import(sessions, conversation.source_session_id)
    if existing is not None:
        session, binding = existing
        transcript = Path(str(binding.get("transcriptRef") or ""))
        if not transcript.is_file():
            raise CodexConversationConflict(
                "the registered Codex conversation transcript is missing"
            )
        # Runtime activation is allowed to replace binding metadata with its
        # current protocol handshake. The stable import identity is the
        # external Pi session id, while the transcript's provenance row owns
        # the immutable source hash check.
        _verify_existing_transcript(transcript, conversation)
        return _receipt(
            status="already_imported",
            conversation=conversation,
            session=session,
            transcript=transcript,
        )

    root = Path(session_dir).expanduser()
    if root.is_symlink():
        raise CodexConversationImportError("PAW Pi session directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir():
        raise CodexConversationImportError("PAW Pi session directory is not a directory")
    transcript = root / _transcript_filename(conversation)
    if transcript.is_symlink():
        raise CodexConversationConflict(
            "the target Pi transcript path must not be a symlink"
        )
    rows = _pi_transcript_rows(conversation)
    encoded = "".join(
        f"{json.dumps(row, ensure_ascii=False, separators=(',', ':'))}\n"
        for row in rows
    ).encode("utf-8")
    if len(encoded) > _MAX_PI_TRANSCRIPT_BYTES:
        raise CodexConversationImportError(
            "converted Pi transcript exceeds PAW's 64 MiB durable-history limit"
        )

    created_transcript = False
    created_session_id = ""
    if transcript.exists():
        _verify_existing_transcript(transcript, conversation)
    else:
        _write_exclusive(transcript, encoded)
        created_transcript = True

    try:
        display_title = _display_title(title, conversation)
        session = sessions.create(
            title=display_title,
            model_profile=_model_profile(conversation.model),
            thinking_level="max",
            created_at_ms=conversation.created_at_ms,
        )
        created_session_id = str(session["id"])
        sessions.bind_runtime_session(
            created_session_id,
            driver_id="managed-pi",
            runtime_kind="pi_rpc",
            external_session_id=_pi_session_id(conversation.source_session_id),
            transcript_ref=transcript.as_posix(),
            branch_anchor=str(rows[-1]["id"]),
            binding_state="prepared",
            metadata={
                "externalProvider": "codex",
                "sourceSessionId": conversation.source_session_id,
                "sourceFile": conversation.source_file,
                "sourceSha256": conversation.source_sha256,
                "sourceComplete": conversation.complete,
                "importFidelity": IMPORT_FIDELITY,
                "omittedKinds": list(conversation.omitted_kinds),
                "importSchemaVersion": IMPORT_SCHEMA_VERSION,
            },
            updated_at_ms=conversation.updated_at_ms,
        )
        session = sessions.set_status(
            created_session_id,
            "idle",
            message_count=len(conversation.messages),
            last_message_preview=conversation.messages[-1].text,
            updated_at_ms=conversation.updated_at_ms,
        )
    except BaseException:
        if created_session_id:
            try:
                sessions.delete(created_session_id)
            except BaseException:
                pass
        if created_transcript:
            try:
                transcript.unlink()
            except OSError:
                pass
        raise

    return _receipt(
        status="imported",
        conversation=conversation,
        session=session,
        transcript=transcript,
    )


def resolve_codex_session(
    value: str | Path,
    *,
    state_db: str | Path | None = None,
) -> tuple[Path, str]:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve(strict=True), ""
    session_id = str(value).strip()
    if not session_id or not _SAFE_SESSION_ID.fullmatch(session_id):
        raise CodexConversationImportError(
            "source must be an existing Codex JSONL path or a safe session id"
        )
    database = Path(
        state_db or Path.home() / ".codex" / "state_5.sqlite"
    ).expanduser()
    if not database.is_file():
        raise CodexConversationImportError("Codex state database is unavailable")
    uri = f"file:{database.resolve(strict=True).as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute(
                "SELECT rollout_path, title FROM threads WHERE id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise CodexConversationImportError(
            f"could not read the Codex state database: {exc}"
        ) from exc
    if row is None:
        raise CodexConversationImportError(f"Codex session was not found: {session_id}")
    source = Path(str(row[0] or "")).expanduser()
    if not source.is_file():
        raise CodexConversationImportError(
            f"Codex rollout file is unavailable for session {session_id}"
        )
    return source.resolve(strict=True), " ".join(str(row[1] or "").split())


def _message_text(payload: Mapping[str, object], *, role: str) -> tuple[str, bool]:
    content = payload.get("content")
    if not isinstance(content, list):
        return "", False
    wanted_type = "input_text" if role == "user" else "output_text"
    texts: list[str] = []
    filtered_context = False
    for raw_block in content:
        if not isinstance(raw_block, Mapping):
            continue
        if str(raw_block.get("type") or "") != wanted_type:
            continue
        text = str(raw_block.get("text") or "").strip()
        if not text:
            continue
        if text.startswith(_INTERNAL_BLOCK_PREFIXES):
            filtered_context = True
            continue
        texts.append(text)
    return "\n\n".join(texts).strip(), filtered_context


def _pi_transcript_rows(conversation: CodexConversation) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "type": "session",
            "version": 3,
            "id": _pi_session_id(conversation.source_session_id),
            "timestamp": conversation.started_at,
            "cwd": conversation.cwd,
        }
    ]
    used_ids: set[str] = set()
    provenance_id = _entry_id(
        conversation.source_session_id,
        "provenance",
        conversation.source_sha256,
        used=used_ids,
    )
    rows.append(
        {
            "type": "custom",
            "id": provenance_id,
            "parentId": None,
            "timestamp": conversation.started_at,
            "customType": PROVENANCE_CUSTOM_TYPE,
            "data": {
                "externalProvider": "codex",
                "sourceSessionId": conversation.source_session_id,
                "sourceFile": conversation.source_file,
                "sourceSha256": conversation.source_sha256,
                "sourceComplete": conversation.complete,
                "importFidelity": IMPORT_FIDELITY,
                "includedRoles": ["user", "assistant"],
                "omittedKinds": list(conversation.omitted_kinds),
                "messageCount": len(conversation.messages),
                "schemaVersion": IMPORT_SCHEMA_VERSION,
            },
        }
    )
    parent_id = provenance_id
    for index, item in enumerate(conversation.messages):
        entry_id = _entry_id(
            conversation.source_session_id,
            str(index),
            item.source_message_id or item.text,
            used=used_ids,
        )
        message: dict[str, object]
        if item.role == "user":
            message = {
                "role": "user",
                "content": item.text,
                "timestamp": item.timestamp_ms,
            }
        else:
            message = {
                "role": "assistant",
                "content": [{"type": "text", "text": item.text}],
                "api": "openai-codex-responses",
                "provider": "openai-codex",
                "model": item.model or conversation.model or "codex-import",
                "usage": _zero_usage(),
                "stopReason": "stop",
                "timestamp": item.timestamp_ms,
            }
        rows.append(
            {
                "type": "message",
                "id": entry_id,
                "parentId": parent_id,
                "timestamp": item.timestamp,
                "message": message,
            }
        )
        parent_id = entry_id
    return rows


def _zero_usage() -> dict[str, object]:
    return {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": 0,
        },
    }


def _existing_import(
    sessions: AgentSessionStore,
    source_session_id: str,
) -> tuple[dict[str, object], dict[str, object]] | None:
    with sqlite3.connect(sessions.db_path) as connection:
        rows = connection.execute(
            """
            SELECT session_id, external_session_id, metadata_json
            FROM agent_runtime_bindings
            WHERE driver_id = 'managed-pi' AND runtime_kind = 'pi_rpc'
            ORDER BY updated_at_ms DESC
            """
        ).fetchall()
    expected_external_id = _pi_session_id(source_session_id)
    for session_id, external_session_id, metadata_json in rows:
        if str(external_session_id or "") == expected_external_id:
            session = sessions.get(str(session_id))
            binding = sessions.runtime_binding(str(session_id))
            if binding is not None:
                return session, binding
        try:
            metadata = json.loads(str(metadata_json or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, Mapping):
            continue
        if (
            metadata.get("externalProvider") == "codex"
            and metadata.get("sourceSessionId") == source_session_id
        ):
            session = sessions.get(str(session_id))
            binding = sessions.runtime_binding(str(session_id))
            if binding is not None:
                return session, binding
    return None


def _verify_existing_transcript(
    transcript: Path,
    conversation: CodexConversation,
) -> None:
    try:
        with transcript.open("r", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            provenance = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexConversationConflict(
            "the existing Pi transcript is not a readable PAW Codex import"
        ) from exc
    data = provenance.get("data") if isinstance(provenance, Mapping) else None
    metadata = data if isinstance(data, Mapping) else {}
    if (
        not isinstance(header, Mapping)
        or header.get("id") != _pi_session_id(conversation.source_session_id)
        or provenance.get("customType") != PROVENANCE_CUSTOM_TYPE
        or metadata.get("sourceSha256") != conversation.source_sha256
    ):
        raise CodexConversationConflict(
            "the target Pi transcript belongs to different imported content"
        )


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _receipt(
    *,
    status: str,
    conversation: CodexConversation,
    session: Mapping[str, object],
    transcript: Path,
) -> dict[str, object]:
    return {
        "schemaVersion": IMPORT_SCHEMA_VERSION,
        "ok": True,
        "status": status,
        "source": {
            "provider": "codex",
            "sessionId": conversation.source_session_id,
            "file": conversation.source_file,
            "sha256": conversation.source_sha256,
            "complete": conversation.complete,
        },
        "fidelity": {
            "mode": IMPORT_FIDELITY,
            "includedRoles": ["user", "assistant"],
            "omittedKinds": list(conversation.omitted_kinds),
        },
        "messageCount": len(conversation.messages),
        "piSessionId": _pi_session_id(conversation.source_session_id),
        "sessionFile": transcript.as_posix(),
        "session": dict(session),
    }


def _display_title(title: str, conversation: CodexConversation) -> str:
    normalized = " ".join(str(title or "").split())
    if not normalized:
        normalized = " ".join(conversation.messages[0].text.split())[:96]
    return normalized[:120]


def _model_profile(model: str) -> str:
    normalized = str(model or "").strip()
    if normalized.startswith("openai-codex/"):
        return normalized[:240]
    return f"openai-codex/{normalized or 'gpt-5.6-sol'}"[:240]


def _pi_session_id(source_session_id: str) -> str:
    return f"codex-{source_session_id}"


def _transcript_filename(conversation: CodexConversation) -> str:
    stamp = conversation.started_at.replace(":", "-")
    return f"{stamp}_{_pi_session_id(conversation.source_session_id)}.jsonl"


def _entry_id(
    source_session_id: str,
    *parts: str,
    used: set[str],
) -> str:
    digest = hashlib.sha256(
        "\0".join((source_session_id, *parts)).encode("utf-8", errors="replace")
    ).hexdigest()
    for length in range(8, len(digest) + 1, 4):
        candidate = digest[:length]
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise CodexConversationImportError("could not allocate a unique Pi entry id")


def _source_file(path: str | Path) -> Path:
    source = Path(path).expanduser()
    if not source.is_file():
        raise CodexConversationImportError(f"Codex rollout file does not exist: {source}")
    if source.suffix.casefold() != ".jsonl":
        raise CodexConversationImportError("Codex rollout source must be a JSONL file")
    return source.resolve(strict=True)


def _embedded_session_id(path: Path) -> str:
    consumed = 0
    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                consumed += len(raw_line)
                if consumed > 4 * 1024 * 1024:
                    break
                try:
                    value = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(value, Mapping) or value.get("type") != "session_meta":
                    continue
                payload = value.get("payload")
                if isinstance(payload, Mapping):
                    return str(payload.get("id") or "").strip()
    except OSError:
        return ""
    return ""


def _iso_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def _timestamp_ms(value: str) -> int:
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _epoch_iso() -> str:
    return "1970-01-01T00:00:00.000Z"


__all__ = [
    "CodexConversation",
    "CodexConversationConflict",
    "CodexConversationImportError",
    "CodexConversationIncomplete",
    "CodexConversationMessage",
    "IMPORT_FIDELITY",
    "IMPORT_SCHEMA_VERSION",
    "import_codex_conversation",
    "parse_codex_conversation",
    "resolve_codex_session",
]
