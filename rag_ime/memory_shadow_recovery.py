from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence
from urllib.parse import quote

from .db.migration_runner import (
    DEFAULT_MIGRATIONS_DIR,
    apply_database_migrations,
    load_migrations,
)
from .embeddings import EmbeddingProvider
from .memory_pipeline_diagnostics import (
    build_memory_pipeline_recovery_preview,
    write_private_recovery_report,
)
from .semantic_memory_migration import migrate_semantic_memory_database
from .text_utils import compact_whitespace


SHADOW_REPORT_SCHEMA_VERSION = "rag-ime.memory-pipeline-shadow-recovery.v1"
RECOVERY_RECEIPT_SCHEMA_VERSION = "rag-ime.memory-pipeline-recovery-receipt.v1"
ROW_FINGERPRINT_ALGORITHM = "sha256-framed-sqlite-rows-v1"
_EVENT_COLUMNS = (
    "id",
    "created_at_ms",
    "source",
    "committed_text",
    "project",
    "app",
    "tags_json",
)
_SOURCE_KEY = "source_id"
_AUDIT_KEY = "event_id"
_HINT_KEY = "hint_id"
_RECOVERY_SOURCE_TABLE = "memory_recovery_source_ids"
_CANONICAL_EVIDENCE_COLUMNS = (
    "evidence_id",
    "project",
    "role_id",
    "session_id",
    "source_kind",
    "source_id",
    "idempotency_key",
    "content_text",
    "content_sha256",
    "provenance_json",
    "metadata_json",
    "privacy_class",
    "status",
    "occurred_at_ms",
    "recorded_at_ms",
    "owner_kind",
    "owner_id",
    "knowledge_domain",
    "scope_kind",
    "scope_id",
    "visibility",
    "authorization_revision",
    "binding_id",
    "scope_mode",
    "evidence_domain",
    "origin_kind",
    "admission_state",
    "admission_reason",
    "trust_class",
    "boundary_kind",
    "admission_revision",
    "admission_updated_at_ms",
)
_EVIDENCE_LINK_COLUMNS = (
    "evidence_id",
    "input_event_id",
    "ordinal",
    "relation",
    "content_sha256",
    "created_at_ms",
)
_ADMISSION_EVENT_COLUMNS = (
    "event_id",
    "evidence_id",
    "previous_state",
    "new_state",
    "reason_code",
    "actor_kind",
    "run_id",
    "source_disposition_event_id",
    "source_previous_disposition",
    "source_new_disposition",
    "created_at_ms",
    "metadata_json",
)


class MemoryShadowRecoveryError(RuntimeError):
    pass


def build_memory_pipeline_shadow(
    current_db: str | Path,
    historical_backup_db: str | Path,
    *,
    output_db: str | Path,
    rollback_db: str | Path,
    report_path: str | Path,
    embedding_provider: EmbeddingProvider,
    project: str = "",
    timezone_name: str = "Asia/Shanghai",
    migrations_dir: str | Path = DEFAULT_MIGRATIONS_DIR,
    allowed_applied_checksum_mismatch_versions: Iterable[int] = (),
) -> dict[str, object]:
    """Build, migrate, recover, and verify one private shadow database.

    The current database and historical backup are opened read-only. The output,
    rollback baseline, and report must be new files outside Git. A known source
    checksum collision may be acknowledged for this shadow build only; the
    database's recorded migration is retained and the conflicting source file is
    excluded from the temporary migration view.
    """

    os.umask(0o077)
    current = _existing_single_link_file(current_db, label="current database")
    backup = _existing_single_link_file(
        historical_backup_db,
        label="historical backup database",
    )
    output = _new_private_path(output_db, label="shadow database")
    rollback = _new_private_path(rollback_db, label="rollback database")
    report_output = _new_private_path(report_path, label="shadow recovery report")
    _require_distinct_files(current, backup, output, rollback, report_output)

    provider_fingerprint = compact_whitespace(
        str(getattr(embedding_provider, "fingerprint", "") or "")
    )
    if not provider_fingerprint or provider_fingerprint == "none":
        raise ValueError("shadow recovery requires an enabled embedding provider")

    allowed_versions = {
        int(version) for version in allowed_applied_checksum_mismatch_versions
    }
    output_created = False
    report_created = False
    rollback_created = False
    try:
        _online_backup(current, output)
        output_created = True
        _copy_exclusive(output, rollback)
        rollback_created = True
        baseline_sha256 = _sha256_file(rollback)
        input_before = _input_event_fingerprint_path(output)

        preview = build_memory_pipeline_recovery_preview(
            output,
            backup,
            migrations_dir=migrations_dir,
        )
        readiness = dict(preview["readiness"])
        if not bool(readiness.get("zeroMutationProof")):
            raise MemoryShadowRecoveryError(
                "read-only recovery preview changed a database"
            )
        if not bool(readiness.get("exactRecoveryCompatible")):
            raise MemoryShadowRecoveryError(
                "historical backup is not exactly compatible with the shadow"
            )
        mismatch_versions = _preview_mismatch_versions(preview)
        unexpected_mismatches = mismatch_versions - allowed_versions
        unused_acknowledgements = allowed_versions - mismatch_versions
        if unexpected_mismatches:
            raise MemoryShadowRecoveryError(
                "unacknowledged migration checksum mismatch versions: "
                + ",".join(str(value) for value in sorted(unexpected_mismatches))
            )
        if unused_acknowledgements:
            raise MemoryShadowRecoveryError(
                "checksum mismatch acknowledgement did not match the database: "
                + ",".join(str(value) for value in sorted(unused_acknowledgements))
            )

        with _filtered_migrations(
            migrations_dir,
            excluded_versions=mismatch_versions,
        ) as filtered_migrations:
            with _writable_connection(output) as conn:
                migration_result = apply_database_migrations(
                    conn,
                    migrations_dir=filtered_migrations,
                )
                runtime_host_lease_isolation = (
                    _isolate_copied_runtime_host_leases(conn)
                )

            first_recovery = recover_memory_history_into_candidate(output, backup)
            repeat_recovery = recover_memory_history_into_candidate(output, backup)
            if any(
                int(repeat_recovery[key]) != 0
                for key in (
                    "insertedSourceRows",
                    "insertedAuditRows",
                    "insertedHintRows",
                    "insertedEvidenceRows",
                    "insertedEvidenceLinkRows",
                    "insertedAdmissionRows",
                )
            ):
                raise MemoryShadowRecoveryError(
                    "repeat recovery was not an insertion no-op"
                )
            if (
                repeat_recovery["receiptId"] != first_recovery["receiptId"]
                or not bool(repeat_recovery["receiptReused"])
            ):
                raise MemoryShadowRecoveryError(
                    "repeat recovery did not reuse the original receipt"
                )

            semantic = migrate_semantic_memory_database(
                output,
                project=project,
                timezone_name=timezone_name,
                embedding_provider=embedding_provider,
                require_vector_freshness=True,
                migrations_dir=filtered_migrations,
            )

        input_after = _input_event_fingerprint_path(output)
        if input_after != input_before:
            raise MemoryShadowRecoveryError(
                "input_events changed while building the shadow candidate"
            )
        with _writable_connection(output) as conn:
            quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
            foreign_key_violations = int(
                conn.execute("SELECT COUNT(*) FROM pragma_foreign_key_check").fetchone()[0]
            )
        if quick_check != "ok" or foreign_key_violations:
            raise MemoryShadowRecoveryError(
                "shadow database failed SQLite verification"
            )

        candidate_sha256 = _sha256_file(output)
        rollback_exercise = _exercise_rollback(
            candidate=output,
            rollback=rollback,
        )
        report = {
            "schemaVersion": SHADOW_REPORT_SCHEMA_VERSION,
            "status": "verified",
            "rawPrivateTextIncluded": False,
            "sourceAccess": "read_only_online_backup",
            "productionApplyPerformed": False,
            "pathIdentities": {
                "current": _path_identity(current),
                "historicalBackup": _path_identity(backup),
                "shadow": _path_identity(output),
                "rollback": _path_identity(rollback),
            },
            "preview": {
                "eventPrefixExact": preview["compatibility"]["eventPrefix"]["exact"],
                "exactRecoveryCompatible": readiness["exactRecoveryCompatible"],
                "zeroMutationProof": readiness["zeroMutationProof"],
                "sourceRows": preview["migrationPreview"]["exactRecovery"][
                    "sourceRows"
                ]["count"],
                "auditRows": preview["migrationPreview"]["exactRecovery"][
                    "auditRows"
                ]["count"],
            },
            "migration": {
                "appliedVersions": list(migration_result.applied_versions),
                "currentVersion": migration_result.current_version,
                "acknowledgedChecksumMismatchVersions": sorted(mismatch_versions),
                "acknowledgementScope": "this_shadow_build_only",
            },
            "runtimeHostLeaseIsolation": runtime_host_lease_isolation,
            "recovery": first_recovery,
            "repeatRecovery": repeat_recovery,
            "semanticMigration": _semantic_report_summary(semantic),
            "inputEvents": {
                "before": input_before,
                "after": input_after,
                "unchanged": True,
            },
            "sqlite": {
                "quickCheck": quick_check,
                "foreignKeyViolationCount": foreign_key_violations,
            },
            "artifacts": {
                "candidateSha256": candidate_sha256,
                "candidateMode": oct(stat.S_IMODE(output.stat().st_mode)),
                "rollbackSha256": baseline_sha256,
                "rollbackMode": oct(stat.S_IMODE(rollback.stat().st_mode)),
            },
            "rollbackExercise": rollback_exercise,
            "embeddingProviderFingerprint": provider_fingerprint,
            "verifiedAtMs": int(time.time() * 1000),
        }
        written_report = write_private_recovery_report(report_output, report)
        report_created = True
        report["reportPath"] = str(written_report)
        report["shadowPath"] = str(output)
        report["rollbackPath"] = str(rollback)
        return report
    except Exception:
        if output_created:
            _remove_sqlite_bundle(output)
        if report_created:
            report_output.unlink(missing_ok=True)
        # The rollback file is deliberately retained once created. It is the
        # immutable online-backup baseline and remains useful after a failed
        # migration attempt.
        if rollback_created:
            os.chmod(rollback, 0o600)
        raise


def recover_memory_history_into_candidate(
    candidate_db: str | Path,
    historical_backup_db: str | Path,
) -> dict[str, object]:
    """Recover exact legacy source state into canonical Evidence atomically.

    The candidate must already contain migration 0133. Repeating this function
    against the same candidate is a no-op and returns the same recovery receipt.
    """

    candidate = _existing_single_link_file(candidate_db, label="candidate database")
    backup = _existing_single_link_file(
        historical_backup_db,
        label="historical backup database",
    )
    _require_distinct_files(candidate, backup)
    with _read_only_connection(backup) as backup_conn:
        backup_tables = {
            "agent_memory_sources": _load_table_rows(
                backup_conn,
                "agent_memory_sources",
                key_column=_SOURCE_KEY,
            ),
            "memory_source_disposition_events": _load_table_rows(
                backup_conn,
                "memory_source_disposition_events",
                key_column=_AUDIT_KEY,
            ),
            "memory_capture_hints": _load_table_rows(
                backup_conn,
                "memory_capture_hints",
                key_column=_HINT_KEY,
            ),
        }
        backup_event_prefix = _input_event_fingerprint(backup_conn)
        backup_events = _load_event_rows(
            backup_conn,
            max_id=int(backup_event_prefix["maxId"]),
        )

    with _writable_connection(candidate) as conn:
        _require_recovery_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            candidate_prefix = _input_event_fingerprint(
                conn,
                max_id=int(backup_event_prefix["maxId"]),
            )
            if candidate_prefix != backup_event_prefix:
                raise MemoryShadowRecoveryError(
                    "candidate input-event prefix does not match the historical backup"
                )
            candidate_events = _load_event_rows(
                conn,
                max_id=int(backup_event_prefix["maxId"]),
            )
            if set(candidate_events) != set(backup_events):
                raise MemoryShadowRecoveryError(
                    "candidate input-event identifiers do not match the historical backup"
                )

            source_result = _import_exact_rows(
                conn,
                table="agent_memory_sources",
                key_column=_SOURCE_KEY,
                backup_table=backup_tables["agent_memory_sources"],
                unique_columns=(
                    "session_id",
                    "pi_entry_id",
                    "source_role",
                    "source_revision",
                ),
            )
            _verify_source_event_hashes(
                backup_tables["agent_memory_sources"],
                candidate_events,
            )
            audit_result = _import_exact_rows(
                conn,
                table="memory_source_disposition_events",
                key_column=_AUDIT_KEY,
                backup_table=backup_tables["memory_source_disposition_events"],
            )
            hint_result = _import_exact_rows(
                conn,
                table="memory_capture_hints",
                key_column=_HINT_KEY,
                backup_table=backup_tables["memory_capture_hints"],
                unique_columns=("source_id", "kind", "normalized_claim"),
            )

            source_ids = tuple(
                sorted(backup_tables["agent_memory_sources"].rows)
            )
            _populate_recovery_source_ids(conn, source_ids)
            canonical = _canonicalize_recovered_sources(conn, source_ids)
            receipt = _record_recovery_receipt(
                conn,
                backup_event_prefix=backup_event_prefix,
                source_fingerprint=backup_tables["agent_memory_sources"].fingerprint,
                audit_fingerprint=backup_tables[
                    "memory_source_disposition_events"
                ].fingerprint,
                hint_fingerprint=backup_tables["memory_capture_hints"].fingerprint,
                canonical_evidence_rows=int(canonical["verifiedEvidenceRows"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "schemaVersion": RECOVERY_RECEIPT_SCHEMA_VERSION,
        "receiptId": receipt["receiptId"],
        "receiptKeySha256": receipt["recoveryKeySha256"],
        "receiptPayloadSha256": receipt["payloadSha256"],
        "receiptReused": receipt["reused"],
        "backupSourceRows": source_result["totalRows"],
        "backupAuditRows": audit_result["totalRows"],
        "backupHintRows": hint_result["totalRows"],
        "insertedSourceRows": source_result["insertedRows"],
        "insertedAuditRows": audit_result["insertedRows"],
        "insertedHintRows": hint_result["insertedRows"],
        "insertedEvidenceRows": canonical["insertedEvidenceRows"],
        "insertedEvidenceLinkRows": canonical["insertedEvidenceLinkRows"],
        "insertedAdmissionRows": canonical["insertedAdmissionRows"],
        "verifiedEvidenceRows": canonical["verifiedEvidenceRows"],
        "inputEventPrefix": backup_event_prefix,
        "rawPrivateTextIncluded": False,
    }


def shadow_recovery_summary(report: Mapping[str, object]) -> dict[str, object]:
    recovery = dict(report["recovery"])
    artifacts = dict(report["artifacts"])
    return {
        "schemaVersion": report["schemaVersion"],
        "status": report["status"],
        "shadowPath": report.get("shadowPath", ""),
        "rollbackPath": report.get("rollbackPath", ""),
        "reportPath": report.get("reportPath", ""),
        "receiptId": recovery["receiptId"],
        "recoveredSourceRows": recovery["backupSourceRows"],
        "recoveredAuditRows": recovery["backupAuditRows"],
        "recoveredHintRows": recovery["backupHintRows"],
        "verifiedEvidenceRows": recovery["verifiedEvidenceRows"],
        "candidateSha256": artifacts["candidateSha256"],
        "rollbackSha256": artifacts["rollbackSha256"],
        "inputEventsUnchanged": report["inputEvents"]["unchanged"],
        "productionApplyPerformed": False,
    }


def _isolate_copied_runtime_host_leases(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Detach source-runtime leases without probing or signalling processes.

    A shadow database is a new ownership domain.  A copied ``running`` row may
    still describe a healthy Runtime Host owned by the source database, so the
    shadow must neither inherit its authority nor try to reconcile that process.
    ``unknown`` preserves the historical observation while releasing the
    shadow-only uniqueness fence.
    """

    _require_table(conn, "room_v2_runtime_host_processes")
    running_count = int(
        conn.execute(
            """SELECT COUNT(*) FROM room_v2_runtime_host_processes
               WHERE state='running'"""
        ).fetchone()[0]
    )
    if running_count:
        conn.execute(
            """UPDATE room_v2_runtime_host_processes
               SET state='unknown', updated_at_ms=?
               WHERE state='running'""",
            (int(time.time() * 1000),),
        )
    remaining = int(
        conn.execute(
            """SELECT COUNT(*) FROM room_v2_runtime_host_processes
               WHERE state='running'"""
        ).fetchone()[0]
    )
    if remaining:
        raise MemoryShadowRecoveryError(
            "shadow retained copied Runtime Host ownership"
        )
    return {
        "detachedRunningLeaseCount": running_count,
        "detachedState": "unknown",
        "processSignalsSent": False,
        "sourceDatabaseMutation": False,
    }


class _TableRows:
    def __init__(
        self,
        *,
        columns: Sequence[str],
        rows: Mapping[str, tuple[object, ...]],
        fingerprint: Mapping[str, object],
    ) -> None:
        self.columns = tuple(columns)
        self.rows = dict(rows)
        self.fingerprint = dict(fingerprint)


def _load_table_rows(
    conn: sqlite3.Connection,
    table: str,
    *,
    key_column: str,
) -> _TableRows:
    _require_table(conn, table)
    columns = tuple(_table_columns(conn, table))
    if key_column not in columns:
        raise MemoryShadowRecoveryError(
            f"{table} is missing key column {key_column}"
        )
    order = ", ".join(_quote_identifier(column) for column in columns)
    digest = hashlib.sha256()
    rows: dict[str, tuple[object, ...]] = {}
    for row in conn.execute(
        f"SELECT {order} FROM {_quote_identifier(table)} "
        f"ORDER BY {_quote_identifier(key_column)}"
    ):
        values = tuple(row[column] for column in columns)
        key = str(row[key_column])
        if key in rows:
            raise MemoryShadowRecoveryError(f"duplicate key in {table}")
        rows[key] = values
        _update_frame(digest, [key, _row_sha256(columns, values)])
    return _TableRows(
        columns=columns,
        rows=rows,
        fingerprint={
            "algorithm": ROW_FINGERPRINT_ALGORITHM,
            "rowCount": len(rows),
            "sha256": digest.hexdigest(),
        },
    )


def _import_exact_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    backup_table: _TableRows,
    unique_columns: Sequence[str] = (),
) -> dict[str, int]:
    _require_table(conn, table)
    target_columns = tuple(_table_columns(conn, table))
    missing_columns = set(backup_table.columns) - set(target_columns)
    if missing_columns:
        raise MemoryShadowRecoveryError(
            f"{table} cannot accept backup columns: {sorted(missing_columns)}"
        )
    column_indexes = {
        column: backup_table.columns.index(column) for column in backup_table.columns
    }
    key_index = column_indexes[key_column]
    existing: dict[str, tuple[object, ...]] = {}
    select_columns = ", ".join(
        _quote_identifier(column) for column in backup_table.columns
    )
    for row in conn.execute(
        f"SELECT {select_columns} FROM {_quote_identifier(table)}"
    ):
        existing[str(row[key_column])] = tuple(
            row[column] for column in backup_table.columns
        )

    unique_owners: dict[tuple[object, ...], str] = {}
    if unique_columns:
        for column in unique_columns:
            if column not in target_columns or column not in backup_table.columns:
                raise MemoryShadowRecoveryError(
                    f"{table} is missing unique identity column {column}"
                )
        unique_sql = ", ".join(
            [_quote_identifier(key_column)]
            + [_quote_identifier(column) for column in unique_columns]
        )
        for row in conn.execute(
            f"SELECT {unique_sql} FROM {_quote_identifier(table)}"
        ):
            unique_owners[tuple(row[column] for column in unique_columns)] = str(
                row[key_column]
            )

    missing_rows: list[tuple[object, ...]] = []
    conflict_refs: list[str] = []
    for key, values in backup_table.rows.items():
        current = existing.get(key)
        if current is not None:
            if not _rows_equal(backup_table.columns, current, values):
                conflict_refs.append(_id_ref(key))
            continue
        if unique_columns:
            identity = tuple(values[column_indexes[column]] for column in unique_columns)
            owner = unique_owners.get(identity)
            if owner is not None and owner != key:
                conflict_refs.append(_id_ref(key))
                continue
        missing_rows.append(values)
    if conflict_refs:
        raise MemoryShadowRecoveryError(
            f"{table} exact-row conflict count={len(conflict_refs)} "
            f"sample={','.join(conflict_refs[:4])}"
        )
    if missing_rows:
        placeholders = ", ".join("?" for _ in backup_table.columns)
        columns_sql = ", ".join(
            _quote_identifier(column) for column in backup_table.columns
        )
        conn.executemany(
            f"INSERT INTO {_quote_identifier(table)} ({columns_sql}) "
            f"VALUES ({placeholders})",
            missing_rows,
        )
    return {
        "totalRows": len(backup_table.rows),
        "insertedRows": len(missing_rows),
        "existingExactRows": len(backup_table.rows) - len(missing_rows),
    }


def _canonicalize_recovered_sources(
    conn: sqlite3.Connection,
    source_ids: Sequence[str],
) -> dict[str, int]:
    _require_columns(conn, "agent_memory_evidence", _CANONICAL_EVIDENCE_COLUMNS)
    _require_columns(
        conn,
        "memory_evidence_input_event_links",
        _EVIDENCE_LINK_COLUMNS,
    )
    _require_columns(
        conn,
        "memory_evidence_admission_events",
        _ADMISSION_EVENT_COLUMNS,
    )
    recovered = set(source_ids)
    source_rows = {
        str(row["source_id"]): dict(row)
        for row in conn.execute(
            f"""SELECT source.*
                FROM agent_memory_sources AS source
                JOIN temp.{_RECOVERY_SOURCE_TABLE} AS recovered
                  ON recovered.source_id = source.source_id
                ORDER BY source.source_id"""
        )
    }
    if set(source_rows) != recovered:
        raise MemoryShadowRecoveryError(
            "not every historical source is present in the candidate"
        )
    input_ids = {int(row["input_event_id"]) for row in source_rows.values()}
    events = {
        int(row["id"]): dict(row)
        for row in conn.execute(
            "SELECT * FROM input_events WHERE id IN "
            f"(SELECT input_event_id FROM agent_memory_sources AS source "
            f"JOIN temp.{_RECOVERY_SOURCE_TABLE} AS recovered "
            "ON recovered.source_id = source.source_id)"
        )
    }
    if set(events) != input_ids:
        raise MemoryShadowRecoveryError(
            "not every historical source has a candidate input event"
        )

    expected_evidence: dict[str, tuple[object, ...]] = {}
    expected_links: dict[tuple[str, int, str], tuple[object, ...]] = {}
    expected_admissions: dict[str, tuple[object, ...]] = {}
    for source_id in sorted(source_rows):
        source = source_rows[source_id]
        event = events[int(source["input_event_id"])]
        evidence_id = f"evidence:source:{source_id}"
        disposition = str(source["disposition"])
        source_status = str(source["status"])
        personal = disposition in {
            "pending",
            "remember",
            "needs_review",
            "consolidated",
        }
        admission_state = (
            "forgotten"
            if source_status == "tombstoned"
            else "needs_review"
            if personal
            else "rejected"
        )
        admission_reason = (
            "legacy_source_tombstoned"
            if source_status == "tombstoned"
            else "legacy_source_requires_revalidation"
            if personal
            else compact_whitespace(str(source["disposition_reason"] or ""))
            or "legacy_source_not_for_memory"
        )
        origin_kind = (
            "explicit_user_memory"
            if str(source["source_kind"]) == "explicit_memory"
            else "legacy_tool_receipt"
            if str(source["source_kind"]) == "tool_receipt"
            else "legacy_untyped_input"
        )
        evidence_values = (
            evidence_id,
            str(event["project"] or ""),
            str(source["role_id"] or ""),
            str(source["session_id"] or ""),
            "tool_receipt"
            if str(source["source_kind"]) == "tool_receipt"
            else "user_message",
            source_id,
            f"canonical-source:{source_id}",
            str(event["committed_text"] or ""),
            str(source["canonical_text_sha256"]),
            _json(
                {
                    "sourceType": "agent_memory_source",
                    "sourceId": source_id,
                    "inputEventId": int(source["input_event_id"]),
                    "sessionId": str(source["session_id"] or ""),
                }
            ),
            str(source["metadata_json"] or "{}"),
            "local",
            "tombstoned" if source_status == "tombstoned" else "active",
            int(source["created_at_ms"]),
            int(source["created_at_ms"]),
            str(source["owner_kind"]),
            str(source["owner_id"]),
            str(source["knowledge_domain"]),
            str(source["scope_kind"]),
            str(source["scope_id"]),
            str(source["visibility"]),
            str(source["authorization_revision"]),
            str(source["binding_id"]),
            str(source["scope_mode"]),
            "personal_memory" if personal else "audit_context",
            origin_kind,
            admission_state,
            admission_reason,
            str(source["trust_class"]),
            "",
            1,
            int(source["disposition_updated_at_ms"] or source["created_at_ms"]),
        )
        expected_evidence[evidence_id] = evidence_values
        link_values = (
            evidence_id,
            int(source["input_event_id"]),
            0,
            "source",
            str(source["canonical_text_sha256"]),
            int(source["created_at_ms"]),
        )
        expected_links[(evidence_id, int(source["input_event_id"]), "source")] = (
            link_values
        )
        initial_id = f"evidence-admission:migration-0130:{source_id}"
        expected_admissions[initial_id] = (
            initial_id,
            evidence_id,
            "",
            admission_state,
            admission_reason,
            "migration",
            "",
            "",
            "",
            disposition,
            int(source["disposition_updated_at_ms"] or source["created_at_ms"]),
            _json({"migrationVersion": 130}),
        )

    for row in conn.execute(
        f"""SELECT audit.*
            FROM memory_source_disposition_events AS audit
            JOIN temp.{_RECOVERY_SOURCE_TABLE} AS recovered
              ON recovered.source_id = audit.source_id
            ORDER BY audit.event_id"""
    ):
        event_id = str(row["event_id"])
        admission_id = f"evidence-admission:source-event:{event_id}"
        disposition = str(row["new_disposition"])
        expected_admissions[admission_id] = (
            admission_id,
            f"evidence:source:{row['source_id']}",
            "",
            "needs_review"
            if disposition in {
                "pending",
                "remember",
                "needs_review",
                "consolidated",
            }
            else "rejected",
            str(row["reason_code"]),
            "migration",
            str(row["run_id"] or ""),
            event_id,
            str(row["previous_disposition"]),
            disposition,
            int(row["created_at_ms"]),
            str(row["metadata_json"] or "{}"),
        )

    inserted_evidence = _insert_and_verify_expected(
        conn,
        table="agent_memory_evidence",
        key_columns=("evidence_id",),
        columns=_CANONICAL_EVIDENCE_COLUMNS,
        expected=expected_evidence,
        json_columns={"provenance_json", "metadata_json"},
    )
    inserted_links = _insert_and_verify_expected(
        conn,
        table="memory_evidence_input_event_links",
        key_columns=("evidence_id", "input_event_id", "relation"),
        columns=_EVIDENCE_LINK_COLUMNS,
        expected=expected_links,
    )
    inserted_admissions = _insert_and_verify_expected(
        conn,
        table="memory_evidence_admission_events",
        key_columns=("event_id",),
        columns=_ADMISSION_EVENT_COLUMNS,
        expected=expected_admissions,
        json_columns={"metadata_json"},
    )
    return {
        "insertedEvidenceRows": inserted_evidence,
        "insertedEvidenceLinkRows": inserted_links,
        "insertedAdmissionRows": inserted_admissions,
        "verifiedEvidenceRows": len(expected_evidence),
    }


def _insert_and_verify_expected(
    conn: sqlite3.Connection,
    *,
    table: str,
    key_columns: Sequence[str],
    columns: Sequence[str],
    expected: Mapping[object, tuple[object, ...]],
    json_columns: set[str] | None = None,
) -> int:
    json_columns = json_columns or set()
    present = set(_table_columns(conn, table))
    missing = set(columns) - present
    if missing:
        raise MemoryShadowRecoveryError(
            f"{table} is missing canonical columns: {sorted(missing)}"
        )
    existing_keys: set[object] = set()
    key_indexes = [columns.index(column) for column in key_columns]
    select_sql = ", ".join(_quote_identifier(column) for column in columns)
    for row in conn.execute(f"SELECT {select_sql} FROM {_quote_identifier(table)}"):
        key_values = tuple(row[column] for column in key_columns)
        key: object = key_values[0] if len(key_values) == 1 else key_values
        if key not in expected:
            continue
        actual = tuple(row[column] for column in columns)
        if not _rows_equal(columns, actual, expected[key], json_columns=json_columns):
            raise MemoryShadowRecoveryError(
                f"{table} canonical-row conflict key={_id_ref(str(key))}"
            )
        existing_keys.add(key)
    missing_rows = [
        values for key, values in expected.items() if key not in existing_keys
    ]
    if missing_rows:
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(
            f"INSERT OR IGNORE INTO {_quote_identifier(table)} "
            f"({select_sql}) VALUES ({placeholders})",
            missing_rows,
        )

    verified = 0
    for row in conn.execute(f"SELECT {select_sql} FROM {_quote_identifier(table)}"):
        key_values = tuple(row[column] for column in key_columns)
        key = key_values[0] if len(key_values) == 1 else key_values
        expected_row = expected.get(key)
        if expected_row is None:
            continue
        actual = tuple(row[column] for column in columns)
        if not _rows_equal(columns, actual, expected_row, json_columns=json_columns):
            raise MemoryShadowRecoveryError(
                f"{table} canonical verification failed key={_id_ref(str(key))}"
            )
        verified += 1
    if verified != len(expected):
        raise MemoryShadowRecoveryError(
            f"{table} canonical rows missing count={len(expected) - verified}"
        )
    return len(missing_rows)


def _record_recovery_receipt(
    conn: sqlite3.Connection,
    *,
    backup_event_prefix: Mapping[str, object],
    source_fingerprint: Mapping[str, object],
    audit_fingerprint: Mapping[str, object],
    hint_fingerprint: Mapping[str, object],
    canonical_evidence_rows: int,
) -> dict[str, object]:
    payload = {
        "schemaVersion": RECOVERY_RECEIPT_SCHEMA_VERSION,
        "inputEventPrefix": dict(backup_event_prefix),
        "backupSourceRows": dict(source_fingerprint),
        "backupAuditRows": dict(audit_fingerprint),
        "backupHintRows": dict(hint_fingerprint),
        "canonicalEvidenceRows": int(canonical_evidence_rows),
        "policy": {
            "exactRowsOnly": True,
            "sessionIndependentEvidence": True,
            "legacyAutoAdmission": False,
            "physicalDeletion": False,
        },
    }
    payload_json = _json(payload)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    recovery_key = payload_sha256
    receipt_id = f"memory-recovery:{recovery_key}"
    existing = conn.execute(
        """SELECT * FROM memory_pipeline_recovery_receipts
           WHERE recovery_key_sha256 = ?""",
        (recovery_key,),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["receipt_id"]) != receipt_id
            or str(existing["payload_sha256"]) != payload_sha256
            or str(existing["payload_json"]) != payload_json
            or str(existing["status"]) != "verified"
        ):
            raise MemoryShadowRecoveryError(
                "existing recovery receipt does not match deterministic payload"
            )
        return {
            "receiptId": receipt_id,
            "recoveryKeySha256": recovery_key,
            "payloadSha256": payload_sha256,
            "reused": True,
        }

    timestamp = int(time.time() * 1000)
    conn.execute(
        """INSERT INTO memory_pipeline_recovery_receipts(
               receipt_id, recovery_key_sha256, input_event_max_id,
               input_event_prefix_sha256, backup_source_rows_sha256,
               backup_audit_rows_sha256, recovered_source_rows,
               recovered_audit_rows, recovered_hint_rows,
               canonical_evidence_rows, payload_sha256, payload_json,
               status, created_at_ms, verified_at_ms
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'verified', ?, ?)""",
        (
            receipt_id,
            recovery_key,
            int(backup_event_prefix["maxId"]),
            str(backup_event_prefix["sha256"]),
            str(source_fingerprint["sha256"]),
            str(audit_fingerprint["sha256"]),
            int(source_fingerprint["rowCount"]),
            int(audit_fingerprint["rowCount"]),
            int(hint_fingerprint["rowCount"]),
            int(canonical_evidence_rows),
            payload_sha256,
            payload_json,
            timestamp,
            timestamp,
        ),
    )
    return {
        "receiptId": receipt_id,
        "recoveryKeySha256": recovery_key,
        "payloadSha256": payload_sha256,
        "reused": False,
    }


def _verify_source_event_hashes(
    sources: _TableRows,
    events: Mapping[int, Mapping[str, object]],
) -> None:
    indexes = {column: sources.columns.index(column) for column in sources.columns}
    required = {"source_id", "input_event_id", "canonical_text_sha256"}
    if not required.issubset(indexes):
        raise MemoryShadowRecoveryError(
            "historical source table lacks event-integrity columns"
        )
    mismatches: list[str] = []
    for source_id, values in sources.rows.items():
        event_id = int(values[indexes["input_event_id"]])
        event = events.get(event_id)
        expected = str(values[indexes["canonical_text_sha256"]]).lower()
        actual = (
            hashlib.sha256(
                compact_whitespace(str(event["committed_text"] or "")).encode("utf-8")
            ).hexdigest()
            if event is not None
            else ""
        )
        if actual != expected:
            mismatches.append(_id_ref(source_id))
    if mismatches:
        raise MemoryShadowRecoveryError(
            "historical source text-hash mismatch count="
            f"{len(mismatches)} sample={','.join(mismatches[:4])}"
        )


def _populate_recovery_source_ids(
    conn: sqlite3.Connection,
    source_ids: Sequence[str],
) -> None:
    conn.execute(f"DROP TABLE IF EXISTS temp.{_RECOVERY_SOURCE_TABLE}")
    conn.execute(
        f"CREATE TEMP TABLE {_RECOVERY_SOURCE_TABLE}(source_id TEXT PRIMARY KEY)"
    )
    conn.executemany(
        f"INSERT INTO temp.{_RECOVERY_SOURCE_TABLE}(source_id) VALUES (?)",
        ((source_id,) for source_id in source_ids),
    )


def _require_recovery_schema(conn: sqlite3.Connection) -> None:
    for table in (
        "input_events",
        "agent_memory_sources",
        "memory_source_disposition_events",
        "memory_capture_hints",
        "agent_memory_evidence",
        "memory_evidence_input_event_links",
        "memory_evidence_admission_events",
        "memory_pipeline_recovery_receipts",
    ):
        _require_table(conn, table)
    evidence_columns = set(_table_columns(conn, "agent_memory_evidence"))
    if not {"evidence_domain", "origin_kind", "admission_state"}.issubset(
        evidence_columns
    ):
        raise MemoryShadowRecoveryError(
            "candidate must apply canonical Evidence migration before recovery"
        )
    foreign_keys = {
        (str(row["from"]), str(row["table"]), str(row["on_delete"]))
        for row in conn.execute("PRAGMA foreign_key_list(agent_memory_sources)")
    }
    if any(column == "session_id" for column, _table, _delete in foreign_keys):
        raise MemoryShadowRecoveryError(
            "candidate source ledger is still coupled to Agent Session lifetime"
        )


def _input_event_fingerprint_path(path: Path) -> dict[str, object]:
    with _read_only_connection(path) as conn:
        return _input_event_fingerprint(conn)


def _input_event_fingerprint(
    conn: sqlite3.Connection,
    *,
    max_id: int | None = None,
) -> dict[str, object]:
    _require_columns(conn, "input_events", _EVENT_COLUMNS)
    where = "" if max_id is None else " WHERE id <= ?"
    params: tuple[object, ...] = () if max_id is None else (int(max_id),)
    columns_sql = ", ".join(_quote_identifier(column) for column in _EVENT_COLUMNS)
    digest = hashlib.sha256()
    count = 0
    observed_max = 0
    for row in conn.execute(
        f"SELECT {columns_sql} FROM input_events{where} ORDER BY id",
        params,
    ):
        values = tuple(row[column] for column in _EVENT_COLUMNS)
        _update_frame(digest, [int(row["id"]), _row_sha256(_EVENT_COLUMNS, values)])
        count += 1
        observed_max = max(observed_max, int(row["id"]))
    return {
        "algorithm": ROW_FINGERPRINT_ALGORITHM,
        "rowCount": count,
        "maxId": observed_max,
        "sha256": digest.hexdigest(),
    }


def _load_event_rows(
    conn: sqlite3.Connection,
    *,
    max_id: int,
) -> dict[int, dict[str, object]]:
    columns_sql = ", ".join(_quote_identifier(column) for column in _EVENT_COLUMNS)
    return {
        int(row["id"]): {column: row[column] for column in _EVENT_COLUMNS}
        for row in conn.execute(
            f"SELECT {columns_sql} FROM input_events WHERE id <= ? ORDER BY id",
            (max_id,),
        )
    }


def _semantic_report_summary(report: Mapping[str, object]) -> dict[str, object]:
    verification = dict(report["verification"])
    legacy = dict(report["legacyItems"])
    timelines = dict(report["timelines"])
    projections = dict(report["projections"])
    projection_runs = [
        dict(value)
        for value in projections.get("runs") or ()
        if isinstance(value, Mapping)
    ]
    return {
        "schemaVersion": report["schemaVersion"],
        "mode": report["mode"],
        "legacyPromoted": legacy.get("promoted", 0),
        "legacyQuarantined": legacy.get("quarantined", 0),
        "timelineDraftsRebuilt": len(timelines.get("rebuilt") or ()),
        "projectionProcessed": sum(
            int(value.get("processed") or 0) for value in projection_runs
        ),
        "projectionApplied": sum(
            len(value.get("applied") or ()) for value in projection_runs
        ),
        "verificationOk": verification.get("ok", False),
        "verificationErrorCount": len(verification.get("errors") or ()),
        "verificationErrorCodeHashes": [
            hashlib.sha256(str(value).encode("utf-8")).hexdigest()
            for value in verification.get("errors") or ()
        ],
        "activationEligible": verification.get("activationEligible", False),
        "vectorProviderFingerprint": verification.get(
            "vectorProviderFingerprint", ""
        ),
    }


def _preview_mismatch_versions(report: Mapping[str, object]) -> set[int]:
    versions: set[int] = set()
    databases = dict(report["databases"])
    for database in databases.values():
        migrations = dict(database["migrations"])
        versions.update(
            int(item["version"])
            for item in migrations.get("checksumMismatches", ())
        )
    return versions


@contextmanager
def _filtered_migrations(
    migrations_dir: str | Path,
    *,
    excluded_versions: set[int],
) -> Iterator[Path]:
    migrations = load_migrations(migrations_dir)
    with tempfile.TemporaryDirectory(prefix="rag-ime-memory-migrations-") as raw:
        root = Path(raw)
        os.chmod(root, 0o700)
        for migration in migrations:
            if migration.version in excluded_versions:
                continue
            destination = root / migration.path.name
            shutil.copyfile(migration.path, destination)
            os.chmod(destination, 0o600)
        yield root


def _online_backup(source: Path, output: Path) -> None:
    _reserve_empty_file(output)
    try:
        with _read_only_connection(source) as source_conn:
            with closing(sqlite3.connect(output)) as target_conn, target_conn:
                target_conn.execute("PRAGMA journal_mode=DELETE")
                source_conn.backup(target_conn)
                # SQLite backup copies the source header, including WAL mode,
                # over the destination header. Normalize the completed copy a
                # second time so the first read-only verification pass cannot
                # create/remove WAL sidecars and falsely report a mutation.
                target_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                target_conn.execute("PRAGMA journal_mode=DELETE")
                quick_check = str(target_conn.execute("PRAGMA quick_check").fetchone()[0])
                if quick_check != "ok":
                    raise MemoryShadowRecoveryError(
                        "online backup failed SQLite quick_check"
                    )
        os.chmod(output, 0o600)
        _fsync_file(output)
    except Exception:
        _remove_sqlite_bundle(output)
        raise


def _copy_exclusive(source: Path, destination: Path) -> None:
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | (getattr(os, "O_NOFOLLOW", 0)),
        0o600,
    )
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(source_handle, output, length=8 * 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    os.chmod(destination, 0o600)


def _exercise_rollback(*, candidate: Path, rollback: Path) -> dict[str, object]:
    parent = candidate.parent
    probe = parent / f".{candidate.name}.rollback-probe-{os.getpid()}"
    replacement = parent / f".{candidate.name}.rollback-replacement-{os.getpid()}"
    if probe.exists() or replacement.exists():
        raise FileExistsError("rollback probe path already exists")
    candidate_before = _sha256_file(candidate)
    try:
        _copy_exclusive(candidate, probe)
        _copy_exclusive(rollback, replacement)
        os.replace(replacement, probe)
        _fsync_directory(parent)
        expected = _sha256_file(rollback)
        actual = _sha256_file(probe)
        if actual != expected:
            raise MemoryShadowRecoveryError(
                "atomic rollback probe did not restore the baseline hash"
            )
        candidate_after = _sha256_file(candidate)
        if candidate_after != candidate_before:
            raise MemoryShadowRecoveryError(
                "rollback exercise changed the recovered candidate"
            )
        return {
            "performed": True,
            "atomicReplace": True,
            "baselineSha256": expected,
            "restoredSha256": actual,
            "candidateUnchanged": True,
            "candidateSha256": candidate_after,
        }
    finally:
        probe.unlink(missing_ok=True)
        replacement.unlink(missing_ok=True)


@contextmanager
def _read_only_connection(path: Path) -> Iterator[sqlite3.Connection]:
    wal = Path(str(path) + "-wal")
    immutable = not wal.exists() or wal.stat().st_size == 0
    immutable_query = "&immutable=1" if immutable else ""
    uri = f"file:{quote(str(path))}?mode=ro{immutable_query}"
    conn = sqlite3.connect(uri, uri=True, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        if int(conn.execute("PRAGMA query_only").fetchone()[0]) != 1:
            raise MemoryShadowRecoveryError("could not enable SQLite query_only")
        yield conn
    finally:
        conn.close()


@contextmanager
def _writable_connection(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        with conn:
            yield conn
    finally:
        conn.close()


def _new_private_path(path: str | Path, *, label: str) -> Path:
    candidate = Path(path).expanduser().absolute()
    _require_outside_git(candidate)
    parent = candidate.parent
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} parent must be a real directory: {parent}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"{label} parent must be mode 0700 or stricter: {parent}")
    if _lexists(candidate):
        raise FileExistsError(f"{label} already exists: {candidate}")
    for sidecar in (Path(str(candidate) + "-wal"), Path(str(candidate) + "-shm")):
        if _lexists(sidecar):
            raise FileExistsError(f"{label} sidecar already exists: {sidecar}")
    return candidate


def _existing_single_link_file(path: str | Path, *, label: str) -> Path:
    candidate = Path(path).expanduser()
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(f"{label} does not exist: {candidate}") from None
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{label} must not be a symlink: {candidate}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file: {candidate}")
    if int(metadata.st_nlink) != 1:
        raise ValueError(f"{label} must have exactly one hard link: {candidate}")
    return candidate.resolve(strict=True)


def _require_distinct_files(*paths: Path) -> None:
    identities: set[tuple[int, int]] = set()
    lexical: set[str] = set()
    for path in paths:
        rendered = str(path.absolute())
        if rendered in lexical:
            raise ValueError("recovery paths must be distinct")
        lexical.add(rendered)
        if path.exists():
            metadata = path.stat()
            identity = (int(metadata.st_dev), int(metadata.st_ino))
            if identity in identities:
                raise ValueError("recovery paths must not reference the same file")
            identities.add(identity)


def _require_outside_git(path: Path) -> None:
    for parent in (path.parent, *path.parents):
        if (parent / ".git").exists():
            raise ValueError(f"private recovery artifact must stay outside Git: {path}")


def _reserve_empty_file(path: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    os.close(descriptor)


def _remove_sqlite_bundle(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    ):
        candidate.unlink(missing_ok=True)


def _require_table(conn: sqlite3.Connection, table: str) -> None:
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is None
    ):
        raise MemoryShadowRecoveryError(f"required table is missing: {table}")


def _require_columns(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
) -> None:
    _require_table(conn, table)
    missing = set(columns) - set(_table_columns(conn, table))
    if missing:
        raise MemoryShadowRecoveryError(
            f"{table} is missing required columns: {sorted(missing)}"
        )


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})")
    ]


def _rows_equal(
    columns: Sequence[str],
    first: Sequence[object],
    second: Sequence[object],
    *,
    json_columns: set[str] | None = None,
) -> bool:
    json_columns = json_columns or set()
    for index, column in enumerate(columns):
        if column in json_columns:
            if _canonical_json(first[index]) != _canonical_json(second[index]):
                return False
        elif _canonical_sqlite_value(first[index]) != _canonical_sqlite_value(
            second[index]
        ):
            return False
    return True


def _canonical_json(value: object) -> object:
    try:
        return json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return object()


def _row_sha256(columns: Sequence[str], values: Sequence[object]) -> str:
    digest = hashlib.sha256()
    _update_frame(digest, list(columns))
    _update_frame(digest, [_canonical_sqlite_value(value) for value in values])
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


def _id_ref(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _path_identity(path: Path) -> dict[str, object]:
    metadata = path.stat()
    return {
        "fileName": path.name,
        "resolvedPathSha256": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True
