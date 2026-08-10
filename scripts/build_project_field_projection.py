#!/usr/bin/env python3
"""Build the public Project Field projection from reviewed local evidence.

The manifest owns human-reviewed Room boundaries, geometry, and source
receipts.  The simulated skill Markdown package owns Wayfinder meaning.  This
builder verifies the factual sources and deterministically parses the Markdown
before emitting one versioned frontend projection.  Raw chat, tool results,
and assistant reasoning never enter the projection.

An optional organizer packet can be written for local review. It contains
bounded, scrubbed user excerpts and must not be sent to Luna (or any other
provider) without explicit user approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from reconstruct_project_field_sources import (
    SessionRecord,
    digest,
    parse_claude,
    parse_codex,
    parse_pi_family,
    scrub,
)
from wayfinder_projection import (
    WAYFINDER_PACKAGE_RELATIVE,
    WayfinderProjectionError as ProjectionBuildError,
    build_wayfinder_projection,
)


MANIFEST_SCHEMA = "personal-agent.project-field-reconstruction-manifest.v1"
PROJECTION_SCHEMA = "personal-agent.project-field-projection.v1"
ORGANIZER_SCHEMA = "personal-agent.project-field-organizer-packet.v1"
CURATION_AUDIT_SCHEMA = "personal-agent.wayfinder-luna-source-audit.v1"
SOURCE_KINDS = {"project-document", "agent-session", "git-commit"}
SOURCE_ROLES = {"intent", "decision", "acceptance"}
SOURCE_AUTHORITIES = {"primary", "corroborating"}
SESSION_PROVIDERS = {"codex", "claude-code", "pi", "omp"}
DOCUMENT_SNAPSHOT_MODES = {"git-head", "exact-working-file", "exact-prototype-file"}
SESSION_REF = re.compile(r"^agent-session:(codex|claude-code|pi|omp):([0-9a-f-]{36})$")
COMMIT_REF = re.compile(r"^git:([0-9a-f]{7,40})$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ABSOLUTE_PATH = re.compile(r"(?:^|[\s'\"])(?:/Users/|/Volumes/|[A-Za-z]:\\)")


@dataclass(frozen=True)
class SourceReceipt:
    source_id: str
    kind: str
    payload: Mapping[str, Any]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectionBuildError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProjectionBuildError(f"expected a JSON object: {path}")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionBuildError(f"{label} must be a non-empty string")
    if ABSOLUTE_PATH.search(value):
        raise ProjectionBuildError(f"{label} contains an absolute machine path")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProjectionBuildError(f"{label} must be an array")
    return value


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionBuildError(f"{label} must be an object")
    return value


def validate_curation_audit(
    curation: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    curated_at: str,
    git_head: str,
) -> None:
    require_string(curation.get("method"), "manifest.curation.method")
    if curation.get("userApprovalRequired") is not True:
        raise ProjectionBuildError("manifest curation must require user approval")
    if curation.get("humanReviewed") is not True:
        raise ProjectionBuildError("manifest curation must record human review")
    organizer = require_mapping(curation.get("modelOrganizer"), "manifest.curation.modelOrganizer")
    expected_organizer_keys = {
        "model",
        "reasoningEffort",
        "role",
        "candidateVerdict",
        "auditRef",
        "sourcePacketSha256",
        "outputSha256",
    }
    if set(organizer) != expected_organizer_keys:
        raise ProjectionBuildError("manifest Luna organizer receipt shape drifted")
    if organizer.get("model") != "gpt-5.6-luna" or organizer.get("reasoningEffort") != "max":
        raise ProjectionBuildError("manifest Luna organizer identity drifted")
    if organizer.get("role") != "draft-only":
        raise ProjectionBuildError("Luna organizer must remain draft-only")
    if organizer.get("candidateVerdict") not in {"ready_to_merge", "needs_human_resolution"}:
        raise ProjectionBuildError("manifest Luna candidate verdict is invalid")
    for key in ("sourcePacketSha256", "outputSha256"):
        value = organizer.get(key)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            raise ProjectionBuildError(f"manifest Luna {key} is invalid")

    if audit.get("schemaVersion") != CURATION_AUDIT_SCHEMA:
        raise ProjectionBuildError("Luna curation audit schema is invalid")
    if audit.get("status") != "reviewed_with_open_user_acceptance":
        raise ProjectionBuildError("Luna curation audit status is invalid")
    if audit.get("cutoff") != curated_at:
        raise ProjectionBuildError("Luna curation audit cutoff drifted")
    source_snapshot = require_mapping(audit.get("sourceSnapshot"), "curationAudit.sourceSnapshot")
    if source_snapshot.get("commit") != git_head:
        raise ProjectionBuildError("Luna curation audit Git snapshot drifted")
    if source_snapshot.get("workingTreeDirtyAtCuration") is not True:
        raise ProjectionBuildError("Luna curation audit must preserve the dirty source marker")

    luna_run = require_mapping(audit.get("lunaRun"), "curationAudit.lunaRun")
    if (
        luna_run.get("model") != organizer["model"]
        or luna_run.get("reasoningEffort") != organizer["reasoningEffort"]
        or luna_run.get("candidateVerdict") != organizer["candidateVerdict"]
    ):
        raise ProjectionBuildError("Luna curation run receipt drifted")
    if luna_run.get("candidateSchemaValidated") is not True:
        raise ProjectionBuildError("Luna candidate must be schema validated before human review")
    if luna_run.get("outputSha256") != organizer["outputSha256"]:
        raise ProjectionBuildError("Luna candidate output receipt drifted")
    for key in ("promptSha256", "schemaSha256", "outputSha256"):
        value = luna_run.get(key)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            raise ProjectionBuildError(f"Luna run {key} is invalid")

    receipt = require_mapping(audit.get("corpusReceipt"), "curationAudit.corpusReceipt")
    if receipt.get("sourcePacketSha256") != organizer["sourcePacketSha256"]:
        raise ProjectionBuildError("Luna source packet receipt drifted")
    inventory = require_mapping(audit.get("inventory"), "curationAudit.inventory")
    historical_documents = require_list(
        inventory.get("historicalDocuments"), "curationAudit.inventory.historicalDocuments"
    )
    target_drafts = require_list(inventory.get("targetDrafts"), "curationAudit.inventory.targetDrafts")
    sessions = require_list(inventory.get("primarySessions"), "curationAudit.inventory.primarySessions")
    commits = require_list(inventory.get("commits"), "curationAudit.inventory.commits")
    expected_counts = {
        "historicalDocumentCount": len(historical_documents),
        "targetDraftCount": len(target_drafts),
        "primarySessionCount": len(sessions),
        "sessionAliasRefCount": 0,
        "userMessageCount": 0,
        "gitCommitCount": len(commits),
    }
    for index, document in enumerate([*historical_documents, *target_drafts]):
        item = require_mapping(document, f"curationAudit document {index}")
        require_string(item.get("id"), f"curationAudit document {index}.id")
        require_string(item.get("ref"), f"curationAudit document {index}.ref")
        digest_value = item.get("sha256")
        if not isinstance(digest_value, str) or SHA256.fullmatch(digest_value) is None:
            raise ProjectionBuildError(f"curationAudit document {index}.sha256 is invalid")
        if not isinstance(item.get("byteCount"), int) or item["byteCount"] < 1:
            raise ProjectionBuildError(f"curationAudit document {index}.byteCount is invalid")
    inventory_aliases: dict[str, list[str]] = {}
    for index, session in enumerate(sessions):
        item = require_mapping(session, f"curationAudit session {index}")
        source_id = require_string(item.get("id"), f"curationAudit session {index}.id")
        aliases = require_list(item.get("aliases"), f"curationAudit session {source_id}.aliases")
        if not all(isinstance(alias, str) and alias for alias in aliases):
            raise ProjectionBuildError(f"curationAudit session {source_id} has invalid aliases")
        count = item.get("userMessageCount")
        digest_value = item.get("userMessagesSha256")
        if not isinstance(count, int) or count < 1:
            raise ProjectionBuildError(f"curationAudit session {source_id} count is invalid")
        if not isinstance(digest_value, str) or SHA256.fullmatch(digest_value) is None:
            raise ProjectionBuildError(f"curationAudit session {source_id} digest is invalid")
        expected_counts["sessionAliasRefCount"] += len(aliases)
        expected_counts["userMessageCount"] += count
        if aliases:
            inventory_aliases[source_id] = aliases
    for key, expected in expected_counts.items():
        if receipt.get(key) != expected:
            raise ProjectionBuildError(f"Luna curation corpus count drifted: {key}")
    packet_digest = receipt.get("sourcePacketSha256")
    if not isinstance(packet_digest, str) or SHA256.fullmatch(packet_digest) is None:
        raise ProjectionBuildError("Luna source packet digest is invalid")

    deduplication = require_mapping(audit.get("deduplication"), "curationAudit.deduplication")
    exact_groups = require_list(
        deduplication.get("exactAliasGroups"), "curationAudit.deduplication.exactAliasGroups"
    )
    reviewed_aliases: dict[str, list[str]] = {}
    for index, group in enumerate(exact_groups):
        item = require_mapping(group, f"curationAudit exact alias group {index}")
        canonical = require_string(
            item.get("canonicalSourceId"), f"curationAudit exact alias group {index}.canonicalSourceId"
        )
        aliases = require_list(item.get("aliasRefs"), f"curationAudit exact alias group {index}.aliasRefs")
        if not all(isinstance(alias, str) and alias for alias in aliases):
            raise ProjectionBuildError(f"curationAudit exact alias group {index} is invalid")
        reviewed_aliases[canonical] = aliases
    if reviewed_aliases != inventory_aliases:
        raise ProjectionBuildError("human-reviewed exact alias mappings drifted from the frozen inventory")

    privacy = require_mapping(audit.get("privacy"), "curationAudit.privacy")
    forbidden_privacy = (
        "rawChatIncluded",
        "boundedExcerptsIncluded",
        "userMessageLedgerIncluded",
        "toolResultsIncluded",
        "assistantReasoningIncluded",
        "absolutePathsIncluded",
    )
    if any(privacy.get(key) is not False for key in forbidden_privacy):
        raise ProjectionBuildError("Luna curation audit privacy contract drifted")
    human_review = require_mapping(audit.get("humanReview"), "curationAudit.humanReview")
    open_questions = require_list(human_review.get("openQuestions"), "curationAudit.humanReview.openQuestions")
    if not any(
        isinstance(question, dict)
        and question.get("id") == "project-field-visual-acceptance"
        and question.get("status") == "not_verified"
        for question in open_questions
    ):
        raise ProjectionBuildError("Luna curation audit closed the user visual gate without evidence")
    if ABSOLUTE_PATH.search(json.dumps(audit, ensure_ascii=False, sort_keys=True)):
        raise ProjectionBuildError("Luna curation audit contains an absolute machine path")


def validate_curation_manifest(
    manifest: Mapping[str, Any],
    prototype_root: Path,
    *,
    curated_at: str,
    git_head: str,
) -> None:
    curation = require_mapping(manifest.get("curation"), "manifest.curation")
    organizer = require_mapping(curation.get("modelOrganizer"), "manifest.curation.modelOrganizer")
    audit_ref = require_string(organizer.get("auditRef"), "manifest.curation.modelOrganizer.auditRef")
    relative = Path(audit_ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProjectionBuildError("manifest Luna audit ref is unsafe")
    audit_path = prototype_root / relative
    if not audit_path.is_file():
        raise ProjectionBuildError(f"manifest Luna audit does not exist: {audit_ref}")
    validate_curation_audit(
        curation,
        read_json(audit_path),
        curated_at=curated_at,
        git_head=git_head,
    )


def command_output(args: Sequence[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ProjectionBuildError(f"command failed: {' '.join(args)}: {detail.strip()}") from exc
    return completed.stdout.strip()


def command_bytes(args: Sequence[str], cwd: Path) -> bytes:
    try:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", b"")
        rendered = detail.decode("utf-8", errors="replace") if isinstance(detail, bytes) else str(detail)
        raise ProjectionBuildError(f"command failed: {' '.join(args)}: {rendered.strip()}") from exc
    return completed.stdout


def validate_project(project: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    expected_project_keys = {
        "id",
        "name",
        "compactTitle",
        "shortName",
        "subtitle",
        "defaultRoomId",
        "routeCamera",
        "reconstruction",
        "rooms",
    }
    if set(project) != expected_project_keys:
        raise ProjectionBuildError(
            "manifest project must own only identity, camera, reconstruction, and Room boundaries"
        )
    require_string(project.get("id"), "project.id")
    require_string(project.get("name"), "project.name")
    require_string(project.get("compactTitle"), "project.compactTitle")
    require_string(project.get("shortName"), "project.shortName")
    require_string(project.get("subtitle"), "project.subtitle")
    require_string(project.get("defaultRoomId"), "project.defaultRoomId")
    route_camera = require_mapping(project.get("routeCamera"), "project.routeCamera")
    if set(route_camera) != {"x", "y", "scale"}:
        raise ProjectionBuildError("project.routeCamera keys drifted")
    for coordinate in ("x", "y", "scale"):
        if not isinstance(route_camera.get(coordinate), (int, float)):
            raise ProjectionBuildError(f"project.routeCamera.{coordinate} must be numeric")
    rooms = require_list(project.get("rooms"), "project.rooms")
    if not rooms:
        raise ProjectionBuildError("project.rooms must not be empty")

    room_ids: set[str] = set()
    unique_sources: dict[str, dict[str, Any]] = {}
    for room_index, room_value in enumerate(rooms):
        room = require_mapping(room_value, f"project.rooms[{room_index}]")
        if set(room) != {"id", "title", "x", "y", "shape", "sources"}:
            raise ProjectionBuildError(
                f"Room boundary {room_index} may own only identity, geometry, and sources"
            )
        room_id = require_string(room.get("id"), f"project.rooms[{room_index}].id")
        if room_id in room_ids:
            raise ProjectionBuildError(f"duplicate Room id: {room_id}")
        room_ids.add(room_id)
        require_string(room.get("title"), f"Room {room_id}.title")
        shape = room.get("shape")
        if shape not in {1, 2, 3, 4}:
            raise ProjectionBuildError(f"Room {room_id}.shape must be 1, 2, 3, or 4")
        for coordinate in ("x", "y"):
            if not isinstance(room.get(coordinate), (int, float)):
                raise ProjectionBuildError(f"Room {room_id}.{coordinate} must be numeric")

        sources = require_list(room.get("sources"), f"Room {room_id}.sources")
        if not sources:
            raise ProjectionBuildError(f"Room {room_id} must cite at least one source")
        for source_index, source_value in enumerate(sources):
            source = require_mapping(source_value, f"Room {room_id}.sources[{source_index}]")
            source_id = require_string(source.get("id"), f"Room {room_id}.sources[{source_index}].id")
            kind = require_string(source.get("kind"), f"source {source_id}.kind")
            role = require_string(source.get("role"), f"source {source_id}.role")
            authority = require_string(source.get("authority"), f"source {source_id}.authority")
            require_string(source.get("label"), f"source {source_id}.label")
            require_string(source.get("detail"), f"source {source_id}.detail")
            require_string(source.get("ref"), f"source {source_id}.ref")
            require_string(source.get("observedAt"), f"source {source_id}.observedAt")
            if kind not in SOURCE_KINDS:
                raise ProjectionBuildError(f"source {source_id} has unsupported kind: {kind}")
            if role not in SOURCE_ROLES:
                raise ProjectionBuildError(f"source {source_id} has unsupported role: {role}")
            if authority not in SOURCE_AUTHORITIES:
                raise ProjectionBuildError(f"source {source_id} has unsupported authority: {authority}")
            existing = unique_sources.get(source_id)
            if existing is not None and existing != source:
                raise ProjectionBuildError(f"source {source_id} is defined inconsistently across Rooms")
            unique_sources[source_id] = source

    default_room_id = str(project.get("defaultRoomId"))
    if default_room_id not in room_ids:
        raise ProjectionBuildError(f"default Room does not exist: {default_room_id}")

    reconstruction = require_mapping(project.get("reconstruction"), "project.reconstruction")
    expected_counts = require_mapping(reconstruction.get("sourceCounts"), "project.reconstruction.sourceCounts")
    actual_counts = {
        "projectDocuments": sum(source.get("kind") == "project-document" for source in unique_sources.values()),
        "agentSessions": sum(source.get("kind") == "agent-session" for source in unique_sources.values()),
        "gitCommits": sum(source.get("kind") == "git-commit" for source in unique_sources.values()),
    }
    if expected_counts != actual_counts:
        raise ProjectionBuildError(
            f"sourceCounts do not match unique cited sources: expected {expected_counts}, actual {actual_counts}"
        )
    return unique_sources


def safe_document_path(ref: str, source_worktree: Path, prototype_root: Path) -> tuple[Path, str]:
    relative = Path(ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProjectionBuildError(f"unsafe document ref: {ref}")
    factual_path = source_worktree / relative
    if factual_path.is_file():
        return factual_path, "main-release"
    prototype_path = prototype_root / relative
    if prototype_path.is_file():
        return prototype_path, "prototype-contract"
    raise ProjectionBuildError(f"document source does not exist in an allowed root: {ref}")


def session_roots(overrides: Sequence[str]) -> dict[str, Path]:
    roots = {
        "codex": Path.home() / ".codex" / "sessions",
        "claude-code": Path.home() / ".claude" / "projects",
        "pi": Path.home() / ".pi" / "agent" / "sessions",
        "omp": Path.home() / ".omp" / "agent" / "sessions",
    }
    for override in overrides:
        provider, separator, raw_path = override.partition("=")
        if not separator or provider not in SESSION_PROVIDERS or not raw_path:
            raise ProjectionBuildError(
                "--session-root must use provider=/path for codex, claude-code, pi, or omp"
            )
        roots[provider] = Path(raw_path).expanduser()
    return roots


def candidate_session_files(root: Path, provider: str, session_id: str) -> Iterable[Path]:
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for source_path in root.rglob(f"*{session_id}*.jsonl"):
        relative = source_path.relative_to(root)
        if provider == "claude-code" and "subagents" in relative.parts:
            continue
        if provider in {"pi", "omp"} and len(relative.parts) > 2:
            continue
        candidates.append(source_path)
    return sorted(candidates)


def load_session(provider: str, session_id: str, root: Path) -> SessionRecord:
    candidates = list(candidate_session_files(root, provider, session_id))
    if len(candidates) != 1:
        raise ProjectionBuildError(
            f"expected one primary {provider} session for {session_id}, found {len(candidates)}"
        )
    source_path = candidates[0]
    if provider == "codex":
        record = parse_codex(source_path)
    elif provider == "claude-code":
        record = parse_claude(source_path)
    else:
        record = parse_pi_family(source_path, provider)
    if record.session_id != session_id:
        raise ProjectionBuildError(
            f"session identity mismatch for {provider}: expected {session_id}, parsed {record.session_id or '(missing)'}"
        )
    if not record.user_messages:
        raise ProjectionBuildError(f"selected session has no user-authored messages: {provider}:{session_id}")
    return record


def verify_document(
    source: Mapping[str, Any],
    source_worktree: Path,
    prototype_root: Path,
    snapshot: Mapping[str, Any],
    git_head: str,
) -> tuple[SourceReceipt, bytes]:
    source_id = str(source["id"])
    ref = str(source["ref"])
    path, root_role = safe_document_path(ref, source_worktree, prototype_root)
    mode = snapshot.get("mode")
    expected_count = snapshot.get("byteCount")
    expected_digest = snapshot.get("sha256")
    if mode not in DOCUMENT_SNAPSHOT_MODES:
        raise ProjectionBuildError(f"document snapshot mode is invalid for source {source_id}")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1:
        raise ProjectionBuildError(f"document snapshot byte count is invalid for source {source_id}")
    if not isinstance(expected_digest, str) or SHA256.fullmatch(expected_digest) is None:
        raise ProjectionBuildError(f"document snapshot digest is invalid for source {source_id}")
    if mode == "git-head":
        if root_role != "main-release":
            raise ProjectionBuildError(f"git-head document must belong to main-release: {source_id}")
        content = command_bytes(["git", "show", f"{git_head}:{ref}"], source_worktree)
    elif mode == "exact-working-file":
        if root_role != "main-release":
            raise ProjectionBuildError(f"working document must belong to main-release: {source_id}")
        content = path.read_bytes()
    else:
        if root_role != "prototype-contract":
            raise ProjectionBuildError(f"prototype document must belong to the projection contract: {source_id}")
        content = path.read_bytes()
    actual_digest = sha256_bytes(content)
    if len(content) != expected_count or actual_digest != expected_digest:
        raise ProjectionBuildError(f"reviewed document snapshot changed for source {source_id}")
    return (
        SourceReceipt(
            source_id,
            "project-document",
            {
                "id": source_id,
                "kind": "project-document",
                "ref": ref,
                "observedAt": source["observedAt"],
                "root": root_role,
                "snapshotMode": mode,
                "sha256": actual_digest,
                "byteCount": len(content),
            },
        ),
        content,
    )


def verify_session(
    source: Mapping[str, Any],
    roots: Mapping[str, Path],
    snapshot: Mapping[str, Any],
) -> tuple[SourceReceipt, SessionRecord]:
    source_id = str(source["id"])
    match = SESSION_REF.fullmatch(str(source["ref"]))
    if match is None:
        raise ProjectionBuildError(f"invalid Agent session ref: {source['ref']}")
    provider, session_id = match.groups()
    if source.get("provider") != provider:
        raise ProjectionBuildError(f"provider mismatch for source {source_id}")
    record = load_session(provider, session_id, roots[provider])
    snapshot_count = snapshot.get("userMessageCount")
    expected_digest = snapshot.get("userMessagesSha256")
    if not isinstance(snapshot_count, int) or isinstance(snapshot_count, bool) or snapshot_count < 1:
        raise ProjectionBuildError(f"session snapshot count is invalid for source {source_id}")
    if not isinstance(expected_digest, str) or SHA256.fullmatch(expected_digest) is None:
        raise ProjectionBuildError(f"session snapshot digest is invalid for source {source_id}")
    if len(record.user_messages) < snapshot_count:
        raise ProjectionBuildError(
            f"session {source_id} now has fewer user messages than its reviewed snapshot"
        )
    record.user_messages = record.user_messages[:snapshot_count]
    user_message_digests = [digest(message) for message in record.user_messages]
    aggregate_digest = sha256_json(user_message_digests)
    if aggregate_digest != expected_digest:
        raise ProjectionBuildError(
            f"reviewed user-message prefix changed for source {source_id}"
        )
    return (
        SourceReceipt(
            source_id,
            "agent-session",
            {
                "id": source_id,
                "kind": "agent-session",
                "provider": provider,
                "sessionId": session_id,
                "observedAt": source["observedAt"],
                "userMessageCount": len(record.user_messages),
                "userMessagesSha256": aggregate_digest,
            },
        ),
        record,
    )


def verify_commit(source: Mapping[str, Any], source_worktree: Path) -> SourceReceipt:
    source_id = str(source["id"])
    match = COMMIT_REF.fullmatch(str(source["ref"]))
    if match is None:
        raise ProjectionBuildError(f"invalid Git commit ref: {source['ref']}")
    requested_hash = match.group(1)
    raw = command_output(
        ["git", "show", "-s", "--format=%H%x00%cI%x00%s", requested_hash],
        source_worktree,
    )
    parts = raw.split("\x00", 2)
    if len(parts) != 3:
        raise ProjectionBuildError(f"unexpected Git metadata for {requested_hash}")
    full_hash, committed_at, subject = parts
    if not full_hash.startswith(requested_hash):
        raise ProjectionBuildError(f"Git ref did not resolve to requested commit: {requested_hash}")
    return SourceReceipt(
        source_id,
        "git-commit",
        {
            "id": source_id,
            "kind": "git-commit",
            "ref": f"git:{requested_hash}",
            "observedAt": source["observedAt"],
            "commit": full_hash,
            "committedAt": committed_at,
            "subject": scrub(subject),
        },
    )


def aggregate_receipts(receipts: Iterable[SourceReceipt], kind: str) -> str:
    payloads = [receipt.payload for receipt in receipts if receipt.kind == kind]
    payloads.sort(key=lambda payload: str(payload["id"]))
    return sha256_json(payloads)


def project_manifest_boundary(project: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only the fields the reconstruction manifest is allowed to own."""

    rooms = []
    for raw_room in require_list(project.get("rooms"), "project.rooms"):
        room = require_mapping(raw_room, "project room")
        rooms.append(
            {
                key: deepcopy(room[key])
                for key in ("id", "title", "x", "y", "shape", "sources")
            }
        )
    return {
        key: deepcopy(project[key])
        for key in (
            "id",
            "name",
            "compactTitle",
            "shortName",
            "subtitle",
            "defaultRoomId",
            "routeCamera",
            "reconstruction",
        )
    } | {"rooms": rooms}


def materialize_project(
    project_boundary: Mapping[str, Any],
    wayfinder: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive all display meaning from docs while preserving manifest geometry."""

    projected_rooms = {
        str(room["roomId"]): room
        for room in require_list(wayfinder.get("rooms"), "wayfinder.rooms")
        if isinstance(room, dict)
    }
    stage_titles = {
        str(stage["id"]): str(stage["title"])
        for stage in require_list(
            require_mapping(wayfinder.get("deliveryEngine"), "wayfinder.deliveryEngine").get("stages"),
            "wayfinder.deliveryEngine.stages",
        )
        if isinstance(stage, dict)
    }
    stage_order = list(stage_titles)
    current_room_id = require_string(wayfinder.get("currentRoomId"), "wayfinder.currentRoomId")
    rooms: list[dict[str, Any]] = []
    for raw_boundary in require_list(project_boundary.get("rooms"), "project.rooms"):
        boundary = require_mapping(raw_boundary, "project room")
        room_id = str(boundary["id"])
        content = require_mapping(projected_rooms.get(room_id), f"wayfinder Room {room_id}")
        stage = str(content["currentStage"])
        delivery_state = str(content["deliveryState"])
        if room_id == current_room_id:
            phase = "foreground"
            phase_label = "当前 Room"
        elif delivery_state == "accepted":
            phase = "settled"
            phase_label = "已验收"
        elif delivery_state == "queued":
            phase = "planned"
            phase_label = stage_titles[stage]
        elif stage in {"quality-gate", "independent-review"}:
            phase = "attention"
            phase_label = stage_titles[stage]
        else:
            phase = "running"
            phase_label = stage_titles[stage]
        area_state = (
            "settled"
            if delivery_state == "accepted"
            else "planned"
            if delivery_state == "queued"
            else "attention"
            if stage in {"quality-gate", "independent-review"}
            else "active"
        )
        rooms.append(
            {
                **deepcopy(boundary),
                "goal": content["requirement"],
                "phase": phase,
                "phaseLabel": phase_label,
                "recentResult": content["currentDelivery"],
                "unresolved": content["problem"],
                "nextStep": content["nextMove"],
                "areas": [
                    {
                        "title": item["label"],
                        "note": "已核验证据" if item["state"] == "verified" else "待核验",
                        "state": "settled" if item["state"] == "verified" else area_state,
                    }
                    for item in require_list(
                        require_mapping(content.get("progress"), f"wayfinder Room {room_id}.progress").get("items"),
                        f"wayfinder Room {room_id}.progress.items",
                    )
                    if isinstance(item, dict)
                ],
                "workflow": [
                    stage_titles[stage_id]
                    for stage_id in stage_order[: stage_order.index(stage) + 1]
                ],
                "keywords": [content["title"], content["requirement"], content["problem"]],
                "retrospective": True,
            }
        )

    relations = require_list(wayfinder.get("relations"), "wayfinder.relations")
    edges = [
        {
            "from": relation["from"],
            "to": relation["to"],
            "kind": "dependency" if relation["kind"] == "requires" else "course",
        }
        for relation in relations
        if isinstance(relation, dict)
        and relation.get("from") in projected_rooms
        and relation.get("to") in projected_rooms
    ]
    initial = require_mapping(wayfinder.get("initialVision"), "wayfinder.initialVision")
    destination = require_mapping(wayfinder.get("destination"), "wayfinder.destination")
    anchors = require_list(initial.get("observableAnchors"), "wayfinder.initialVision.observableAnchors")
    return {
        **deepcopy(dict(project_boundary)),
        "destination": destination["title"],
        "heading": anchors[1] if len(anchors) > 1 else initial["statement"],
        "origin": initial["title"],
        "rooms": rooms,
        "edges": edges,
        "wayfinder": deepcopy(dict(wayfinder)),
    }


def reuse_verified_receipts(
    existing_projection: Mapping[str, Any],
    *,
    project: Mapping[str, Any],
    unique_sources: Mapping[str, Mapping[str, Any]],
    document_snapshots: Mapping[str, Any],
    session_snapshots: Mapping[str, Any],
    expected_git_head: str,
    expected_dirty_at_curation: bool,
    source_counts: Mapping[str, Any],
) -> list[SourceReceipt]:
    """Reuse a sealed receipt bundle while rebuilding derived Markdown content.

    This migration path does not claim source freshness. It requires every
    receipt to match the pinned manifest snapshot while comparing only the
    identity, geometry, and receipts that the manifest is allowed to own.
    """

    if existing_projection.get("schemaVersion") != PROJECTION_SCHEMA:
        raise ProjectionBuildError("reused receipt projection has an unsupported schema")
    if ABSOLUTE_PATH.search(json.dumps(existing_projection, ensure_ascii=False, sort_keys=True)):
        raise ProjectionBuildError("reused receipt projection contains an absolute machine path")
    revision = require_mapping(
        existing_projection.get("sourceRevision"),
        "reused projection.sourceRevision",
    )
    if revision.get("gitHead") != expected_git_head:
        raise ProjectionBuildError("reused receipt projection belongs to a different Git revision")
    if revision.get("sourceWorktreeDirtyAtCuration") is not expected_dirty_at_curation:
        raise ProjectionBuildError("reused receipt projection dirty-at-curation marker drifted")
    if existing_projection.get("sourceCounts") != source_counts:
        raise ProjectionBuildError("reused receipt projection source counts drifted")
    expected_privacy = {
        "rawChatIncluded": False,
        "toolResultsIncluded": False,
        "assistantReasoningIncluded": False,
        "absolutePathsIncluded": False,
    }
    if existing_projection.get("privacy") != expected_privacy:
        raise ProjectionBuildError("reused receipt projection privacy contract drifted")
    existing_project = require_mapping(existing_projection.get("project"), "reused projection.project")
    if project_manifest_boundary(existing_project) != project:
        raise ProjectionBuildError(
            "reused receipt projection differs from the manifest-owned boundary"
        )

    raw_receipts = require_list(
        existing_projection.get("sourceReceipts"),
        "reused projection.sourceReceipts",
    )
    payloads_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_receipt in enumerate(raw_receipts):
        payload = require_mapping(raw_receipt, f"reused projection.sourceReceipts[{index}]")
        source_id = require_string(payload.get("id"), f"reused receipt {index}.id")
        if source_id in payloads_by_id:
            raise ProjectionBuildError(f"duplicate reused source receipt: {source_id}")
        payloads_by_id[source_id] = payload
    if set(payloads_by_id) != set(unique_sources):
        raise ProjectionBuildError("reused receipts do not cover exactly the manifest sources")

    receipts: list[SourceReceipt] = []
    for source_id in sorted(unique_sources):
        source = unique_sources[source_id]
        payload = payloads_by_id[source_id]
        kind = str(source["kind"])
        if payload.get("kind") != kind or payload.get("observedAt") != source.get("observedAt"):
            raise ProjectionBuildError(f"reused receipt identity drifted for source {source_id}")
        if kind == "project-document":
            snapshot = require_mapping(
                document_snapshots.get(source_id),
                f"manifest.documentSnapshots.{source_id}",
            )
            mode = snapshot.get("mode")
            expected_root = "prototype-contract" if mode == "exact-prototype-file" else "main-release"
            expected_payload = {
                "id": source_id,
                "kind": "project-document",
                "ref": source["ref"],
                "observedAt": source["observedAt"],
                "root": expected_root,
                "snapshotMode": mode,
                "sha256": snapshot.get("sha256"),
                "byteCount": snapshot.get("byteCount"),
            }
            if payload != expected_payload:
                raise ProjectionBuildError(f"reused document receipt drifted for source {source_id}")
        elif kind == "agent-session":
            snapshot = require_mapping(
                session_snapshots.get(source_id),
                f"manifest.sessionSnapshots.{source_id}",
            )
            match = SESSION_REF.fullmatch(str(source["ref"]))
            if match is None:
                raise ProjectionBuildError(f"invalid Agent session ref: {source['ref']}")
            provider, session_id = match.groups()
            expected_payload = {
                "id": source_id,
                "kind": "agent-session",
                "provider": provider,
                "sessionId": session_id,
                "observedAt": source["observedAt"],
                "userMessageCount": snapshot.get("userMessageCount"),
                "userMessagesSha256": snapshot.get("userMessagesSha256"),
            }
            if payload != expected_payload:
                raise ProjectionBuildError(f"reused session receipt drifted for source {source_id}")
        else:
            if set(payload) != {
                "id",
                "kind",
                "ref",
                "observedAt",
                "commit",
                "committedAt",
                "subject",
            }:
                raise ProjectionBuildError(f"reused commit receipt shape drifted for source {source_id}")
            match = COMMIT_REF.fullmatch(str(source["ref"]))
            if (
                match is None
                or payload.get("ref") != source.get("ref")
                or not str(payload.get("commit", "")).startswith(match.group(1))
            ):
                raise ProjectionBuildError(f"reused commit receipt drifted for source {source_id}")
            require_string(payload.get("committedAt"), f"reused commit {source_id}.committedAt")
            require_string(payload.get("subject"), f"reused commit {source_id}.subject")
        receipts.append(SourceReceipt(source_id, kind, payload))

    for kind, revision_key in (
        ("project-document", "documentsSha256"),
        ("agent-session", "sessionsSha256"),
        ("git-commit", "commitsSha256"),
    ):
        if revision.get(revision_key) != aggregate_receipts(receipts, kind):
            raise ProjectionBuildError(f"reused {kind} receipt aggregate drifted")
    return receipts


def build_projection(
    manifest_path: Path,
    source_worktree: Path,
    prototype_root: Path,
    roots: Mapping[str, Path],
    reused_projection: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[Mapping[str, Any], SessionRecord | None, bytes | None]]]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = read_json(manifest_path)
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise ProjectionBuildError(f"unsupported manifest schema: {manifest.get('schemaVersion')}")
    privacy = require_mapping(manifest.get("privacy"), "manifest.privacy")
    expected_privacy = {
        "rawChatIncluded": False,
        "toolResultsIncluded": False,
        "assistantReasoningIncluded": False,
        "absolutePathsIncluded": False,
    }
    if privacy != expected_privacy:
        raise ProjectionBuildError("manifest privacy contract must fail closed")
    curated_at = require_string(manifest.get("curatedAt"), "manifest.curatedAt")
    factual_source = require_mapping(manifest.get("factualSource"), "manifest.factualSource")
    if factual_source.get("repository") != "7155/personal-agent-workbench":
        raise ProjectionBuildError("manifest factual repository is not the canonical product")
    if factual_source.get("branch") != "main":
        raise ProjectionBuildError("manifest factual branch must remain main")
    expected_git_head = require_string(factual_source.get("gitHead"), "manifest.factualSource.gitHead")
    if re.fullmatch(r"[0-9a-f]{40}", expected_git_head) is None:
        raise ProjectionBuildError("manifest factual Git head is invalid")
    validate_curation_manifest(
        manifest,
        prototype_root,
        curated_at=curated_at,
        git_head=expected_git_head,
    )
    if reused_projection is None:
        actual_git_head = command_output(["git", "rev-parse", "HEAD"], source_worktree)
        if actual_git_head != expected_git_head:
            raise ProjectionBuildError(
                "main-release HEAD changed after curation; review sources before updating the manifest"
            )
    dirty_at_curation = factual_source.get("workingTreeDirtyAtCuration")
    if not isinstance(dirty_at_curation, bool):
        raise ProjectionBuildError("manifest factual dirty-at-curation marker must be boolean")
    project = require_mapping(manifest.get("project"), "manifest.project")
    unique_sources = validate_project(project)
    document_snapshots = require_mapping(
        manifest.get("documentSnapshots"),
        "manifest.documentSnapshots",
    )
    document_source_ids = {
        source_id
        for source_id, source in unique_sources.items()
        if source.get("kind") == "project-document"
    }
    if set(document_snapshots) != document_source_ids:
        raise ProjectionBuildError(
            "manifest.documentSnapshots must cover exactly the selected project documents"
        )
    snapshots = require_mapping(manifest.get("sessionSnapshots"), "manifest.sessionSnapshots")
    session_source_ids = {
        source_id
        for source_id, source in unique_sources.items()
        if source.get("kind") == "agent-session"
    }
    if set(snapshots) != session_source_ids:
        raise ProjectionBuildError(
            "manifest.sessionSnapshots must cover exactly the selected Agent session sources"
        )

    organizer_material: dict[str, tuple[Mapping[str, Any], SessionRecord | None, bytes | None]] = {}
    source_counts = dict(require_mapping(project["reconstruction"], "project.reconstruction")["sourceCounts"])
    if reused_projection is None:
        receipts: list[SourceReceipt] = []
        for source_id in sorted(unique_sources):
            source = unique_sources[source_id]
            kind = str(source["kind"])
            if kind == "project-document":
                receipt, content = verify_document(
                    source,
                    source_worktree,
                    prototype_root,
                    require_mapping(
                        document_snapshots[source_id],
                        f"manifest.documentSnapshots.{source_id}",
                    ),
                    expected_git_head,
                )
                organizer_material[source_id] = (source, None, content)
            elif kind == "agent-session":
                receipt, record = verify_session(
                    source,
                    roots,
                    require_mapping(snapshots[source_id], f"manifest.sessionSnapshots.{source_id}"),
                )
                organizer_material[source_id] = (source, record, None)
            else:
                receipt = verify_commit(source, source_worktree)
                organizer_material[source_id] = (source, None, None)
            receipts.append(receipt)
    else:
        receipts = reuse_verified_receipts(
            reused_projection,
            project=project,
            unique_sources=unique_sources,
            document_snapshots=document_snapshots,
            session_snapshots=snapshots,
            expected_git_head=expected_git_head,
            expected_dirty_at_curation=dirty_at_curation,
            source_counts=source_counts,
        )

    package_root = prototype_root / WAYFINDER_PACKAGE_RELATIVE
    room_boundaries = {
        str(room["id"]): str(room["title"])
        for room in require_list(project.get("rooms"), "project.rooms")
        if isinstance(room, dict)
    }
    available_source_ids_by_room = {
        str(room["id"]): {
            str(source["id"])
            for source in require_list(room.get("sources"), f"Room {room.get('id')}.sources")
            if isinstance(source, dict)
        }
        for room in require_list(project.get("rooms"), "project.rooms")
        if isinstance(room, dict)
    }
    wayfinder = build_wayfinder_projection(
        package_root,
        expected_project_id=str(project["id"]),
        expected_current_room_id=str(project["defaultRoomId"]),
        room_boundaries=room_boundaries,
        available_source_ids_by_room=available_source_ids_by_room,
    )
    projection_project = materialize_project(project, wayfinder)

    receipt_payloads = [receipt.payload for receipt in sorted(receipts, key=lambda item: item.source_id)]
    projection = {
        "schemaVersion": PROJECTION_SCHEMA,
        "generatedAt": curated_at,
        "sourceRevision": {
            "gitHead": expected_git_head,
            "sourceWorktreeDirtyAtCuration": dirty_at_curation,
            "manifestSha256": sha256_bytes(manifest_bytes),
            "documentsSha256": aggregate_receipts(receipts, "project-document"),
            "sessionsSha256": aggregate_receipts(receipts, "agent-session"),
            "commitsSha256": aggregate_receipts(receipts, "git-commit"),
        },
        "sourceCounts": source_counts,
        "privacy": {
            "rawChatIncluded": False,
            "toolResultsIncluded": False,
            "assistantReasoningIncluded": False,
            "absolutePathsIncluded": False,
        },
        "sourceReceipts": receipt_payloads,
        "project": projection_project,
    }
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    if ABSOLUTE_PATH.search(serialized):
        raise ProjectionBuildError("projection contains an absolute machine path")
    return projection, organizer_material


def bounded_document_excerpt(content: bytes) -> str:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError:
        return ""
    selected: list[str] = []
    signal = re.compile(r"^(?:#{1,4}\s|.*(?:目标|愿景|要求|决定|结论|验收|未完成|frontier|fog).*)", re.IGNORECASE)
    for line in lines:
        compact = scrub(line)
        if compact and signal.search(compact):
            selected.append(compact[:360])
        if sum(len(value) for value in selected) >= 3200:
            break
    return "\n".join(selected)[:3200]


def bounded_session_excerpts(record: SessionRecord) -> list[str]:
    messages = record.user_messages
    if len(messages) <= 12:
        selected = messages
    else:
        indexes = sorted({0, 1, *(round(index * (len(messages) - 1) / 9) for index in range(10)), len(messages) - 1})
        selected = [messages[index] for index in indexes]
    return [scrub(message)[:360] for message in selected if scrub(message)]


def build_organizer_packet(
    projection: Mapping[str, Any],
    material: Mapping[str, tuple[Mapping[str, Any], SessionRecord | None, bytes | None]],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    for source_id in sorted(material):
        source, record, document_content = material[source_id]
        item: dict[str, Any] = {
            "id": source_id,
            "kind": source["kind"],
            "role": source["role"],
            "label": source["label"],
            "detail": source["detail"],
            "observedAt": source["observedAt"],
        }
        if document_content is not None:
            item["boundedExcerpt"] = bounded_document_excerpt(document_content)
        elif record is not None:
            item["boundedUserExcerpts"] = bounded_session_excerpts(record)
        else:
            receipt = next(
                entry for entry in projection["sourceReceipts"] if entry.get("id") == source_id
            )
            item["commitSubject"] = receipt.get("subject", "")
        evidence.append(item)
    return {
        "schemaVersion": ORGANIZER_SCHEMA,
        "generatedAt": projection["generatedAt"],
        "containsPrivateUserText": True,
        "externalTransmissionRequiresExplicitApproval": True,
        "instruction": (
            "Draft Room grouping and Wayfinder changes from this bounded evidence. "
            "Do not invent facts; cite source IDs; preserve the original user vision; "
            "return a draft for human review only."
        ),
        "currentProject": projection["project"],
        "evidence": evidence,
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    script_root = Path(__file__).resolve().parent.parent
    default_manifest = (
        script_root
        / "design-system/rag-ime-control-center/prototypes/room-navigation-wayfinder/real-project-reconstruction/reconstruction-manifest.v1.json"
    )
    default_output = (
        script_root
        / "control-center-web/src/features/project-field/generated/personal-agent-workbench.v1.json"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-worktree", type=Path, required=True)
    parser.add_argument("--prototype-root", type=Path, default=script_root)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--output", type=Path, default=default_output)
    parser.add_argument(
        "--session-root",
        action="append",
        default=[],
        metavar="PROVIDER=PATH",
        help="override a local primary-session root (repeatable; intended for tests)",
    )
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--reuse-verified-receipts",
        type=Path,
        help=(
            "reuse an existing sealed source-receipt bundle while rebuilding only "
            "the manifest and authoritative Wayfinder docs projection"
        ),
    )
    parser.add_argument(
        "--organizer-packet",
        type=Path,
        help="write a private local packet with bounded user excerpts; never commit it",
    )
    args = parser.parse_args(argv)

    source_worktree = args.source_worktree.expanduser().resolve()
    prototype_root = args.prototype_root.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not (source_worktree / ".git").exists():
        raise ProjectionBuildError(f"--source-worktree is not a Git worktree: {source_worktree}")

    reused_projection = (
        read_json(args.reuse_verified_receipts.expanduser().resolve())
        if args.reuse_verified_receipts is not None
        else None
    )
    if reused_projection is not None and args.organizer_packet is not None:
        raise ProjectionBuildError(
            "--organizer-packet requires live source verification and cannot reuse receipts"
        )
    projection, material = build_projection(
        manifest_path,
        source_worktree,
        prototype_root,
        session_roots(args.session_root),
        reused_projection=reused_projection,
    )
    if args.verify_only:
        existing = read_json(output_path)
        if existing != projection:
            raise ProjectionBuildError(
                "generated projection is stale; rebuild without --verify-only after reviewing source changes"
            )
    else:
        write_json(output_path, projection)

    if args.organizer_packet is not None:
        organizer_path = args.organizer_packet.expanduser().resolve()
        write_json(organizer_path, build_organizer_packet(projection, material))
        print(f"private organizer packet: {organizer_path}", file=sys.stderr)

    mode = "verified" if args.verify_only else "built"
    counts = projection["sourceCounts"]
    print(
        f"{mode} {output_path}: {len(projection['project']['rooms'])} Rooms, "
        f"{counts['projectDocuments']} docs, {counts['agentSessions']} sessions, "
        f"{counts['gitCommits']} commits"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProjectionBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
