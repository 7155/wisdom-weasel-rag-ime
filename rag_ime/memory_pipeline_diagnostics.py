from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import quote

from .db.migration_runner import DEFAULT_MIGRATIONS_DIR, load_migrations
from .text_utils import compact_whitespace


REPORT_SCHEMA_VERSION = "rag-ime.memory-pipeline-recovery-preview.v1"
EVENT_FINGERPRINT_ALGORITHM = "sha256-framed-sqlite-values-v1"
_EVENT_COLUMNS = (
    "id",
    "created_at_ms",
    "source",
    "committed_text",
    "project",
    "app",
    "tags_json",
)
_REQUIRED_TABLES = (
    "input_events",
    "agent_sessions",
    "agent_memory_sources",
    "memory_source_disposition_events",
    "agent_memory_evidence",
    "memory_atoms",
    "memory_books",
    "schema_migrations",
)
_LEGACY_FRAGMENT_SOURCE = "squirrel_rime_commit_burst"
_FINALIZED_SEGMENT_SOURCE = "squirrel_input_segment"
_ID_SAMPLE_LIMIT = 16


@dataclass(frozen=True)
class EventIdentity:
    event_id: int
    row_sha256: str
    canonical_text_sha256: str
    source: str


@dataclass(frozen=True)
class EventIndex:
    rows: Mapping[int, EventIdentity]
    fingerprint: Mapping[str, object]


@dataclass(frozen=True)
class SourceIdentity:
    source_id: str
    row_sha256: str
    input_event_id: int
    canonical_text_sha256: str
    session_id: str
    source_kind: str


@dataclass(frozen=True)
class SourceIndex:
    rows: Mapping[str, SourceIdentity]
    columns: tuple[str, ...]
    fingerprint: Mapping[str, object]


@dataclass(frozen=True)
class AuditIdentity:
    event_id: str
    row_sha256: str
    source_id: str


@dataclass(frozen=True)
class AuditIndex:
    rows: Mapping[str, AuditIdentity]
    columns: tuple[str, ...]
    fingerprint: Mapping[str, object]


def build_memory_pipeline_recovery_preview(
    current_db: str | Path,
    backup_db: str | Path,
    *,
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    generated_at_ms: int | None = None,
) -> dict[str, object]:
    """Build a raw-text-free recovery preview without opening either DB writable."""

    current_path = _existing_regular_file(current_db, label="current database")
    backup_path = _existing_regular_file(backup_db, label="backup database")
    if _same_inode(current_path, backup_path):
        raise ValueError("current and backup databases must be different files")

    current_file_before = _database_bundle_state(current_path)
    backup_file_before = _database_bundle_state(backup_path)

    current_conn = _open_read_only(current_path)
    backup_conn = _open_read_only(backup_path)
    try:
        current_conn.execute("BEGIN")
        backup_conn.execute("BEGIN")
        current_schema = _schema_census(current_conn)
        backup_schema = _schema_census(backup_conn)
        current_migrations = _migration_status_read_only(current_conn, migrations_dir)
        backup_migrations = _migration_status_read_only(backup_conn, migrations_dir)
        current_events = _load_event_index(current_conn)
        backup_events = _load_event_index(backup_conn)
        current_sources = _load_source_index(current_conn)
        backup_sources = _load_source_index(backup_conn)
        current_audits = _load_audit_index(current_conn)
        backup_audits = _load_audit_index(backup_conn)
        preview, compatibility = _build_migration_preview(
            current_conn=current_conn,
            current_events=current_events,
            backup_events=backup_events,
            current_sources=current_sources,
            backup_sources=backup_sources,
            current_audits=current_audits,
            backup_audits=backup_audits,
        )
        current_logical_before = _logical_fingerprint(
            current_events,
            current_sources,
            current_audits,
            event_max_id=max(current_events.rows, default=0),
        )
        backup_logical_before = _logical_fingerprint(
            backup_events,
            backup_sources,
            backup_audits,
            event_max_id=max(backup_events.rows, default=0),
        )
    finally:
        current_conn.rollback()
        backup_conn.rollback()
        current_conn.close()
        backup_conn.close()

    current_logical_after = _read_logical_fingerprint(
        current_path,
        event_max_id=int(current_logical_before["inputEventPrefix"]["maxId"]),
    )
    backup_logical_after = _read_logical_fingerprint(
        backup_path,
        event_max_id=int(backup_logical_before["inputEventPrefix"]["maxId"]),
    )
    current_file_after = _database_bundle_state(current_path)
    backup_file_after = _database_bundle_state(backup_path)

    current_proof = _mutation_proof(
        file_before=current_file_before,
        file_after=current_file_after,
        logical_before=current_logical_before,
        logical_after=current_logical_after,
    )
    backup_proof = _mutation_proof(
        file_before=backup_file_before,
        file_after=backup_file_after,
        logical_before=backup_logical_before,
        logical_after=backup_logical_after,
    )
    blockers = ["p0_preview_only_no_apply"]
    if not bool(compatibility["eventPrefix"]["exact"]):
        blockers.append("backup_event_prefix_not_exact")
    if not bool(compatibility["sourceRecovery"]["allRowsEventCompatible"]):
        blockers.append("backup_source_event_mismatch")
    if int(preview["quarantine"]["sourceRowConflicts"]["count"]) > 0:
        blockers.append("current_source_id_conflict")
    if int(preview["quarantine"]["auditRowConflicts"]["count"]) > 0:
        blockers.append("current_audit_id_conflict")
    mismatch_versions = {
        int(item["version"])
        for status_payload in (current_migrations, backup_migrations)
        for item in status_payload["checksumMismatches"]
    }
    if mismatch_versions:
        blockers.append("migration_checksum_mismatch")
    blockers.append("session_independent_evidence_owner_not_implemented")
    if not current_proof["ok"] or not backup_proof["ok"]:
        blockers.append("database_changed_during_preview")

    timestamp = int(time.time() * 1000) if generated_at_ms is None else int(generated_at_ms)
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "generatedAtMs": max(0, timestamp),
        "invariants": {
            "applyPerformed": False,
            "databaseOpenMode": "mode=ro + PRAGMA query_only=ON",
            "rawPrivateTextIncluded": False,
            "newerEventsAssignedHistoricalDisposition": False,
            "legacyRowsPhysicallyDeleted": False,
            "eventFingerprintAlgorithm": EVENT_FINGERPRINT_ALGORITHM,
        },
        "databases": {
            "current": {
                "identity": _path_identity(current_path),
                "schema": current_schema,
                "migrations": current_migrations,
                "fileStateBefore": current_file_before,
                "fileStateAfter": current_file_after,
                "logicalBefore": current_logical_before,
                "logicalAfter": current_logical_after,
                "mutationProof": current_proof,
            },
            "backup": {
                "identity": _path_identity(backup_path),
                "schema": backup_schema,
                "migrations": backup_migrations,
                "fileStateBefore": backup_file_before,
                "fileStateAfter": backup_file_after,
                "logicalBefore": backup_logical_before,
                "logicalAfter": backup_logical_after,
                "mutationProof": backup_proof,
            },
        },
        "compatibility": compatibility,
        "migrationPreview": preview,
        "readiness": {
            "readOnlyPreviewComplete": True,
            "zeroMutationProof": bool(current_proof["ok"] and backup_proof["ok"]),
            "exactRecoveryCompatible": bool(
                compatibility["eventPrefix"]["exact"]
                and compatibility["sourceRecovery"]["allRowsEventCompatible"]
                and int(preview["quarantine"]["sourceRowConflicts"]["count"]) == 0
                and int(preview["quarantine"]["auditRowConflicts"]["count"]) == 0
            ),
            "productionApplyAllowed": False,
            "blockers": list(dict.fromkeys(blockers)),
        },
    }


def write_private_recovery_report(
    output_path: str | Path,
    report: Mapping[str, object],
) -> Path:
    """Write one exclusive mode-0600 report outside any Git worktree."""

    output = Path(output_path).expanduser()
    _require_outside_git(output)
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(output, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        output.unlink(missing_ok=True)
        raise
    os.chmod(output, 0o600)
    directory_fd = os.open(output.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return output.resolve(strict=True)


def recovery_report_summary(
    report: Mapping[str, object],
    *,
    report_path: str | Path | None = None,
) -> dict[str, object]:
    preview = report["migrationPreview"]
    quarantine = preview["quarantine"]
    retire_rebind = preview["retireRebind"]
    payload: dict[str, object] = {
        "schemaVersion": report["schemaVersion"],
        "eventPrefixExact": report["compatibility"]["eventPrefix"]["exact"],
        "exactRecoverySourceRows": preview["exactRecovery"]["sourceRows"]["count"],
        "exactRecoveryAuditRows": preview["exactRecovery"]["auditRows"]["count"],
        "newPendingCandidateEvents": preview["newPendingCandidate"]["events"]["count"],
        "quarantineObjects": sum(
            int(item["count"])
            for item in quarantine.values()
            if isinstance(item, Mapping) and "count" in item
        ),
        "retireRebindObjects": (
            int(retire_rebind["atoms"]["count"])
            + int(retire_rebind["books"]["count"])
        ),
        "zeroMutationProof": report["readiness"]["zeroMutationProof"],
        "productionApplyAllowed": False,
    }
    if report_path is not None:
        payload["reportPath"] = str(Path(report_path))
    return payload


def _build_migration_preview(
    *,
    current_conn: sqlite3.Connection,
    current_events: EventIndex,
    backup_events: EventIndex,
    current_sources: SourceIndex,
    backup_sources: SourceIndex,
    current_audits: AuditIndex,
    backup_audits: AuditIndex,
) -> tuple[dict[str, object], dict[str, object]]:
    backup_ids = set(backup_events.rows)
    backup_max_id = max(backup_ids, default=0)
    current_prefix_ids = {
        event_id for event_id in current_events.rows if event_id <= backup_max_id
    }
    matched_event_ids = {
        event_id
        for event_id in backup_ids & current_prefix_ids
        if backup_events.rows[event_id].row_sha256
        == current_events.rows[event_id].row_sha256
    }
    missing_event_ids = backup_ids - current_prefix_ids
    mismatched_event_ids = {
        event_id
        for event_id in backup_ids & current_prefix_ids
        if event_id not in matched_event_ids
    }
    current_only_prefix_ids = current_prefix_ids - backup_ids
    prefix_exact = not (
        missing_event_ids or mismatched_event_ids or current_only_prefix_ids
    )

    exact_source_ids: set[str] = set()
    no_op_source_ids: set[str] = set()
    incompatible_source_ids: set[str] = set()
    source_conflict_ids: set[str] = set()
    compatible_source_ids: set[str] = set()
    for source_id, backup_source in backup_sources.rows.items():
        backup_event = backup_events.rows.get(backup_source.input_event_id)
        current_event = current_events.rows.get(backup_source.input_event_id)
        event_compatible = bool(
            backup_event is not None
            and current_event is not None
            and backup_event.row_sha256 == current_event.row_sha256
            and backup_source.canonical_text_sha256
            == backup_event.canonical_text_sha256
        )
        if not event_compatible:
            incompatible_source_ids.add(source_id)
            continue
        compatible_source_ids.add(source_id)
        current_source = current_sources.rows.get(source_id)
        if current_source is None:
            exact_source_ids.add(source_id)
        elif (
            current_sources.columns == backup_sources.columns
            and current_source.row_sha256 == backup_source.row_sha256
        ):
            no_op_source_ids.add(source_id)
        else:
            source_conflict_ids.add(source_id)

    exact_audit_ids: set[str] = set()
    no_op_audit_ids: set[str] = set()
    incompatible_audit_ids: set[str] = set()
    audit_conflict_ids: set[str] = set()
    recoverable_source_ids = exact_source_ids | no_op_source_ids
    for event_id, backup_audit in backup_audits.rows.items():
        if backup_audit.source_id not in recoverable_source_ids:
            incompatible_audit_ids.add(event_id)
            continue
        current_audit = current_audits.rows.get(event_id)
        if current_audit is None:
            exact_audit_ids.add(event_id)
        elif (
            current_audits.columns == backup_audits.columns
            and current_audit.row_sha256 == backup_audit.row_sha256
        ):
            no_op_audit_ids.add(event_id)
        else:
            audit_conflict_ids.add(event_id)

    linked_current_event_ids = {
        source.input_event_id for source in current_sources.rows.values()
    }
    new_pending_event_ids = {
        event_id
        for event_id, event in current_events.rows.items()
        if event_id not in backup_ids
        and event.source == _FINALIZED_SEGMENT_SOURCE
        and event_id not in linked_current_event_ids
    }
    legacy_fragment_event_ids = {
        event_id
        for event_id, event in current_events.rows.items()
        if event.source == _LEGACY_FRAGMENT_SOURCE
    }
    current_sources_missing_events = {
        source_id
        for source_id, source in current_sources.rows.items()
        if source.input_event_id not in current_events.rows
    }
    current_sources_on_legacy_fragments = {
        source_id
        for source_id, source in current_sources.rows.items()
        if source.input_event_id in legacy_fragment_event_ids
    }
    current_only_source_ids = set(current_sources.rows) - set(backup_sources.rows)
    preserved_current_only_sources = (
        current_only_source_ids
        - current_sources_missing_events
        - current_sources_on_legacy_fragments
    )
    current_only_audit_ids = set(current_audits.rows) - set(backup_audits.rows)
    quarantined_source_ids = (
        source_conflict_ids
        | incompatible_source_ids
        | current_sources_missing_events
        | current_sources_on_legacy_fragments
    )
    preserved_current_only_audits = {
        event_id
        for event_id in current_only_audit_ids
        if current_audits.rows[event_id].source_id not in quarantined_source_ids
    }
    sessions = {
        backup_sources.rows[source_id].session_id
        for source_id in exact_source_ids
        if backup_sources.rows[source_id].session_id
    }
    retire_rebind = _projection_retire_rebind_preview(
        current_conn,
        current_events=current_events,
        quarantine_event_ids=(
            legacy_fragment_event_ids
            | missing_event_ids
            | mismatched_event_ids
            | current_only_prefix_ids
        ),
    )

    preview = {
        "exactRecovery": {
            "reason": "backup_row_is_absent_and_its_input_event_matches_exactly",
            "sourceRows": _id_group(exact_source_ids),
            "auditRows": _id_group(exact_audit_ids),
            "legacySessionDependencies": _id_group(sessions),
            "applyTarget": "future_session_independent_canonical_evidence_owner",
        },
        "newPendingCandidate": {
            "reason": "post_backup_finalized_segment_has_no_ledger_row_and_capture_v2_is_not_proven",
            "events": _id_group(new_pending_event_ids),
            "historicalDispositionAssigned": False,
        },
        "quarantine": {
            "eventIdentityConflicts": _id_group(
                missing_event_ids | mismatched_event_ids | current_only_prefix_ids
            ),
            "backupSourcesWithIncompatibleEvent": _id_group(incompatible_source_ids),
            "sourceRowConflicts": _id_group(source_conflict_ids),
            "auditRowsWithIncompatibleSource": _id_group(incompatible_audit_ids),
            "auditRowConflicts": _id_group(audit_conflict_ids),
            "legacyFragmentEvents": _id_group(legacy_fragment_event_ids),
            "currentSourcesWithMissingEvent": _id_group(current_sources_missing_events),
            "currentSourcesOnLegacyFragments": _id_group(
                current_sources_on_legacy_fragments
            ),
        },
        "retireRebind": retire_rebind,
        "noOp": {
            "exactInputEvents": _id_group(matched_event_ids),
            "sourceRowsAlreadyIdentical": _id_group(no_op_source_ids),
            "auditRowsAlreadyIdentical": _id_group(no_op_audit_ids),
            "currentOnlySourceRowsPreserved": _id_group(
                preserved_current_only_sources
            ),
            "currentOnlyAuditRowsPreserved": _id_group(
                preserved_current_only_audits
            ),
        },
    }
    compatibility = {
        "eventPrefix": {
            "exact": prefix_exact,
            "backupMaxId": backup_max_id,
            "backup": _event_fingerprint(backup_events.rows.values()),
            "currentThroughBackupMaxId": _event_fingerprint(
                current_events.rows[event_id] for event_id in current_prefix_ids
            ),
            "matched": _id_group(matched_event_ids),
            "missingInCurrent": _id_group(missing_event_ids),
            "differentInCurrent": _id_group(mismatched_event_ids),
            "currentOnlyWithinPrefix": _id_group(current_only_prefix_ids),
        },
        "sourceRecovery": {
            "schemaColumnsMatch": current_sources.columns == backup_sources.columns,
            "allRowsEventCompatible": not incompatible_source_ids,
            "backupRowCount": len(backup_sources.rows),
            "eventCompatible": _id_group(compatible_source_ids),
            "eventIncompatible": _id_group(incompatible_source_ids),
        },
        "auditRecovery": {
            "schemaColumnsMatch": current_audits.columns == backup_audits.columns,
            "backupRowCount": len(backup_audits.rows),
            "recoverableOrNoOp": _id_group(exact_audit_ids | no_op_audit_ids),
            "incompatible": _id_group(incompatible_audit_ids | audit_conflict_ids),
        },
    }
    return preview, compatibility


def _projection_retire_rebind_preview(
    conn: sqlite3.Connection,
    *,
    current_events: EventIndex,
    quarantine_event_ids: set[int],
) -> dict[str, object]:
    atom_reasons: dict[str, set[str]] = {}
    if _table_exists(conn, "memory_atoms"):
        rows = _select_optional_columns(
            conn,
            "memory_atoms",
            (
                "id",
                "status",
                "scope_project",
                "owner_kind",
                "owner_id",
                "source_event_ids_json",
            ),
        )
        for row in rows:
            if str(row["status"] or "").lower() not in {"active", "current"}:
                continue
            atom_id = str(row["id"] or "")
            if not atom_id:
                continue
            reasons: set[str] = set()
            if str(row["scope_project"] or "").strip():
                reasons.add("current_atom_is_project_scoped")
            owner_kind = str(row["owner_kind"] or "user")
            owner_id = str(row["owner_id"] or "default")
            if owner_kind != "user" or owner_id != "default":
                reasons.add("current_atom_is_not_global_personal_owner")
            source_event_ids, valid_json = _json_integer_ids(
                row["source_event_ids_json"]
            )
            if not valid_json:
                reasons.add("source_event_links_are_invalid")
            elif not source_event_ids:
                reasons.add("canonical_evidence_link_is_missing")
            elif any(event_id not in current_events.rows for event_id in source_event_ids):
                reasons.add("source_event_is_missing")
            elif all(event_id in quarantine_event_ids for event_id in source_event_ids):
                reasons.add("only_quarantined_source_events")
            if reasons:
                atom_reasons[atom_id] = reasons

    book_reasons: dict[str, set[str]] = {}
    if _table_exists(conn, "memory_books"):
        rows = _select_optional_columns(
            conn,
            "memory_books",
            ("book_id", "status", "project", "owner_kind", "owner_id"),
        )
        for row in rows:
            if str(row["status"] or "").lower() not in {"active", "current"}:
                continue
            book_id = str(row["book_id"] or "")
            if not book_id:
                continue
            reasons: set[str] = set()
            if str(row["project"] or "").strip():
                reasons.add("current_book_is_project_scoped")
            owner_kind = str(row["owner_kind"] or "user")
            owner_id = str(row["owner_id"] or "default")
            if owner_kind != "user" or owner_id != "default":
                reasons.add("current_book_is_not_global_personal_owner")
            if reasons:
                book_reasons[book_id] = reasons
    return {
        "reason": "preserve_history_but_retire_or_exactly_rebind_invalid_current_projection",
        "atoms": _reasoned_id_group(atom_reasons),
        "books": _reasoned_id_group(book_reasons),
        "physicalDeleteAllowed": False,
    }


def _load_event_index(
    conn: sqlite3.Connection,
    *,
    max_id: int | None = None,
) -> EventIndex:
    _require_columns(conn, "input_events", _EVENT_COLUMNS)
    where = "" if max_id is None else " WHERE id <= ?"
    parameters: tuple[object, ...] = () if max_id is None else (max(0, int(max_id)),)
    rows: dict[int, EventIdentity] = {}
    sql = (
        "SELECT "
        + ", ".join(_quote_identifier(column) for column in _EVENT_COLUMNS)
        + " FROM input_events"
        + where
        + " ORDER BY id"
    )
    for row in conn.execute(sql, parameters):
        event_id = int(row["id"])
        committed_text = str(row["committed_text"] or "")
        rows[event_id] = EventIdentity(
            event_id=event_id,
            row_sha256=_row_sha256(_EVENT_COLUMNS, row),
            canonical_text_sha256=hashlib.sha256(
                compact_whitespace(committed_text).encode("utf-8")
            ).hexdigest(),
            source=compact_whitespace(str(row["source"] or "")).lower(),
        )
    return EventIndex(rows=rows, fingerprint=_event_fingerprint(rows.values()))


def _load_source_index(conn: sqlite3.Connection) -> SourceIndex:
    table = "agent_memory_sources"
    if not _table_exists(conn, table):
        return SourceIndex(rows={}, columns=(), fingerprint=_missing_fingerprint(table))
    columns = tuple(_table_columns(conn, table))
    required = {"source_id", "input_event_id", "canonical_text_sha256", "session_id"}
    missing = required - set(columns)
    if missing:
        raise RuntimeError(f"{table} is missing required columns: {sorted(missing)}")
    rows: dict[str, SourceIdentity] = {}
    sql = (
        "SELECT "
        + ", ".join(_quote_identifier(column) for column in columns)
        + f" FROM {_quote_identifier(table)} ORDER BY source_id"
    )
    digest = hashlib.sha256()
    count = 0
    for row in conn.execute(sql):
        source_id = str(row["source_id"])
        row_sha = _row_sha256(columns, row)
        _update_frame(digest, [source_id, row_sha])
        rows[source_id] = SourceIdentity(
            source_id=source_id,
            row_sha256=row_sha,
            input_event_id=int(row["input_event_id"]),
            canonical_text_sha256=str(row["canonical_text_sha256"] or "").lower(),
            session_id=str(row["session_id"] or ""),
            source_kind=(
                str(row["source_kind"] or "") if "source_kind" in columns else ""
            ),
        )
        count += 1
    return SourceIndex(
        rows=rows,
        columns=columns,
        fingerprint={
            "present": True,
            "rowCount": count,
            "sha256": digest.hexdigest(),
            "keyColumn": "source_id",
        },
    )


def _load_audit_index(conn: sqlite3.Connection) -> AuditIndex:
    table = "memory_source_disposition_events"
    if not _table_exists(conn, table):
        return AuditIndex(rows={}, columns=(), fingerprint=_missing_fingerprint(table))
    columns = tuple(_table_columns(conn, table))
    required = {"event_id", "source_id"}
    missing = required - set(columns)
    if missing:
        raise RuntimeError(f"{table} is missing required columns: {sorted(missing)}")
    rows: dict[str, AuditIdentity] = {}
    sql = (
        "SELECT "
        + ", ".join(_quote_identifier(column) for column in columns)
        + f" FROM {_quote_identifier(table)} ORDER BY event_id"
    )
    digest = hashlib.sha256()
    count = 0
    for row in conn.execute(sql):
        event_id = str(row["event_id"])
        row_sha = _row_sha256(columns, row)
        _update_frame(digest, [event_id, row_sha])
        rows[event_id] = AuditIdentity(
            event_id=event_id,
            row_sha256=row_sha,
            source_id=str(row["source_id"] or ""),
        )
        count += 1
    return AuditIndex(
        rows=rows,
        columns=columns,
        fingerprint={
            "present": True,
            "rowCount": count,
            "sha256": digest.hexdigest(),
            "keyColumn": "event_id",
        },
    )


def _logical_fingerprint(
    events: EventIndex,
    sources: SourceIndex,
    audits: AuditIndex,
    *,
    event_max_id: int,
) -> dict[str, object]:
    return {
        "inputEventPrefix": {
            **_event_fingerprint(
                event
                for event_id, event in events.rows.items()
                if event_id <= event_max_id
            ),
            "maxId": max(0, int(event_max_id)),
        },
        "agentMemorySources": dict(sources.fingerprint),
        "memorySourceDispositionEvents": dict(audits.fingerprint),
    }


def _read_logical_fingerprint(path: Path, *, event_max_id: int) -> dict[str, object]:
    conn = _open_read_only(path)
    try:
        conn.execute("BEGIN")
        return _logical_fingerprint(
            _load_event_index(conn, max_id=event_max_id),
            _load_source_index(conn),
            _load_audit_index(conn),
            event_max_id=event_max_id,
        )
    finally:
        conn.rollback()
        conn.close()


def _event_fingerprint(events: Iterable[EventIdentity]) -> dict[str, object]:
    ordered = sorted(events, key=lambda event: event.event_id)
    digest = hashlib.sha256()
    for event in ordered:
        _update_frame(digest, [event.event_id, event.row_sha256])
    return {
        "rowCount": len(ordered),
        "maxId": max((event.event_id for event in ordered), default=0),
        "sha256": digest.hexdigest(),
    }


def _schema_census(conn: sqlite3.Connection) -> dict[str, object]:
    objects = conn.execute(
        """
        SELECT type, name, tbl_name, COALESCE(sql, '') AS sql
        FROM sqlite_master
        ORDER BY type, name
        """
    ).fetchall()
    object_counts = Counter(str(row["type"]) for row in objects)
    schema_digest = hashlib.sha256()
    for row in objects:
        _update_frame(
            schema_digest,
            [str(row["type"]), str(row["name"]), str(row["tbl_name"]), str(row["sql"])],
        )
    table_names = sorted(
        str(row["name"]) for row in objects if str(row["type"]) == "table"
    )
    foreign_keys: list[dict[str, object]] = []
    for table in table_names:
        for row in conn.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})"):
            foreign_keys.append(
                {
                    "table": table,
                    "from": str(row["from"]),
                    "toTable": str(row["table"]),
                    "to": str(row["to"]),
                    "onUpdate": str(row["on_update"]),
                    "onDelete": str(row["on_delete"]),
                }
            )
    required: dict[str, object] = {}
    for table in _REQUIRED_TABLES:
        if table not in table_names:
            required[table] = {"present": False, "rowCount": 0, "columns": []}
            continue
        columns = [
            {
                "name": str(row["name"]),
                "type": str(row["type"]),
                "notNull": bool(row["notnull"]),
                "primaryKeyPosition": int(row["pk"]),
            }
            for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")
        ]
        row_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()[0]
        )
        required[table] = {
            "present": True,
            "rowCount": row_count,
            "columns": columns,
            "foreignKeys": [item for item in foreign_keys if item["table"] == table],
        }
    return {
        "schemaSha256": schema_digest.hexdigest(),
        "objectCounts": dict(sorted(object_counts.items())),
        "tableCount": len(table_names),
        "tableNames": table_names,
        "tableNameSetSha256": _id_set_sha256(table_names),
        "foreignKeyCount": len(foreign_keys),
        "foreignKeys": foreign_keys,
        "requiredTables": required,
    }


def _migration_status_read_only(
    conn: sqlite3.Connection,
    migrations_dir: str | Path,
) -> dict[str, object]:
    source_migrations = load_migrations(migrations_dir)
    source = {migration.version: migration for migration in source_migrations}
    if not _table_exists(conn, "schema_migrations"):
        return {
            "present": False,
            "currentVersion": 0,
            "sourceLatestVersion": max(source, default=0),
            "pendingVersions": sorted(source),
            "databaseOnlyVersions": [],
            "checksumMismatches": [],
            "ok": False,
        }
    rows = conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row["version"]): row for row in rows}
    mismatches = []
    for version, row in applied.items():
        migration = source.get(version)
        if migration is None or str(row["checksum"]) != migration.checksum:
            mismatches.append(
                {
                    "version": version,
                    "name": str(row["name"]),
                    "databaseChecksum": str(row["checksum"]),
                    "sourceChecksum": migration.checksum if migration is not None else "",
                }
            )
    return {
        "present": True,
        "currentVersion": max(applied, default=0),
        "sourceLatestVersion": max(source, default=0),
        "pendingVersions": sorted(set(source) - set(applied)),
        "databaseOnlyVersions": sorted(set(applied) - set(source)),
        "checksumMismatches": mismatches,
        "ok": not mismatches,
    }


def _mutation_proof(
    *,
    file_before: Mapping[str, object],
    file_after: Mapping[str, object],
    logical_before: Mapping[str, object],
    logical_after: Mapping[str, object],
) -> dict[str, object]:
    file_unchanged = file_before == file_after
    logical_unchanged = logical_before == logical_after
    return {
        "toolOpenedDatabaseReadOnly": True,
        "fileStateUnchanged": file_unchanged,
        "logicalFingerprintUnchanged": logical_unchanged,
        "ok": bool(file_unchanged and logical_unchanged),
    }


def _open_read_only(path: Path) -> sqlite3.Connection:
    # SQLite may update an existing shared-memory sidecar even for a
    # query-only connection. A settled backup with no WAL frames can be opened
    # immutable so diagnostics do not change `-shm` metadata. A live database
    # with WAL frames must remain a normal read-only view so committed rows in
    # the WAL are included in the fingerprint.
    wal_path = Path(str(path) + "-wal")
    immutable = not wal_path.exists() or wal_path.stat().st_size == 0
    immutable_query = "&immutable=1" if immutable else ""
    uri = f"file:{quote(str(path))}?mode=ro{immutable_query}"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    query_only = int(conn.execute("PRAGMA query_only").fetchone()[0])
    if query_only != 1:
        conn.close()
        raise RuntimeError("SQLite query_only could not be enabled")
    return conn


def _database_bundle_state(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for label, candidate in (
        ("database", path),
        ("wal", Path(str(path) + "-wal")),
        ("shm", Path(str(path) + "-shm")),
    ):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            result[label] = {"present": False}
            continue
        result[label] = {
            "present": True,
            "device": int(metadata.st_dev),
            "inode": int(metadata.st_ino),
            "size": int(metadata.st_size),
            "mtimeNs": int(metadata.st_mtime_ns),
            "mode": int(stat.S_IMODE(metadata.st_mode)),
            "regularFile": stat.S_ISREG(metadata.st_mode),
        }
    return result


def _path_identity(path: Path) -> dict[str, object]:
    return {
        "fileName": path.name,
        "resolvedPathSha256": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
    }


def _existing_regular_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} does not exist: {candidate}") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file: {candidate}")
    return candidate.resolve(strict=True)


def _same_inode(first: Path, second: Path) -> bool:
    first_stat = first.stat()
    second_stat = second.stat()
    return (first_stat.st_dev, first_stat.st_ino) == (
        second_stat.st_dev,
        second_stat.st_ino,
    )


def _require_outside_git(path: Path) -> None:
    candidate = path.absolute()
    for parent in (candidate.parent, *candidate.parents):
        if (parent / ".git").exists():
            raise ValueError(f"private recovery report must stay outside Git: {path}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")
    ]


def _require_columns(
    conn: sqlite3.Connection,
    table: str,
    required: Sequence[str],
) -> None:
    if not _table_exists(conn, table):
        raise RuntimeError(f"required table is missing: {table}")
    missing = set(required) - set(_table_columns(conn, table))
    if missing:
        raise RuntimeError(f"{table} is missing required columns: {sorted(missing)}")


def _select_optional_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
) -> list[sqlite3.Row]:
    present = set(_table_columns(conn, table))
    expressions = [
        _quote_identifier(column)
        if column in present
        else f"NULL AS {_quote_identifier(column)}"
        for column in columns
    ]
    return conn.execute(
        f"SELECT {', '.join(expressions)} FROM {_quote_identifier(table)}"
    ).fetchall()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _row_sha256(columns: Sequence[str], row: sqlite3.Row) -> str:
    digest = hashlib.sha256()
    _update_frame(digest, list(columns))
    _update_frame(digest, [_canonical_sqlite_value(row[column]) for column in columns])
    return digest.hexdigest()


def _canonical_sqlite_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float)):
        return value
    if isinstance(value, bytes):
        return {
            "byteCount": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    return str(value)


def _update_frame(digest: "hashlib._Hash", values: Sequence[object]) -> None:
    payload = json.dumps(
        list(values),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _id_group(values: Iterable[object]) -> dict[str, object]:
    original = list(values)
    unique = sorted({str(value) for value in original})
    numeric_values = {
        str(value)
        for value in original
        if isinstance(value, int) and not isinstance(value, bool)
    }
    return {
        "count": len(unique),
        "idSetSha256": _id_set_sha256(unique),
        "sampleIdRefs": [
            value
            if value in numeric_values
            else "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
            for value in unique[:_ID_SAMPLE_LIMIT]
        ],
        "sampleTruncated": len(unique) > _ID_SAMPLE_LIMIT,
    }


def _reasoned_id_group(values: Mapping[str, set[str]]) -> dict[str, object]:
    reason_counts = Counter(
        reason for reasons in values.values() for reason in sorted(reasons)
    )
    digest = hashlib.sha256()
    for item_id in sorted(values):
        _update_frame(digest, [item_id, *sorted(values[item_id])])
    return {
        "count": len(values),
        "idAndReasonSetSha256": digest.hexdigest(),
        "sampleIdRefs": [
            "sha256:" + hashlib.sha256(item_id.encode("utf-8")).hexdigest()
            for item_id in sorted(values)[:_ID_SAMPLE_LIMIT]
        ],
        "sampleTruncated": len(values) > _ID_SAMPLE_LIMIT,
        "reasonCounts": dict(sorted(reason_counts.items())),
    }


def _id_set_sha256(values: Iterable[object]) -> str:
    digest = hashlib.sha256()
    for value in sorted({str(item) for item in values}):
        _update_frame(digest, [value])
    return digest.hexdigest()


def _json_integer_ids(value: object) -> tuple[set[int], bool]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set(), False
    if not isinstance(parsed, list):
        return set(), False
    result: set[int] = set()
    for item in parsed:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            return set(), False
    return result, True


def _missing_fingerprint(table: str) -> dict[str, object]:
    return {
        "present": False,
        "rowCount": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
        "keyColumn": "",
        "table": table,
    }
