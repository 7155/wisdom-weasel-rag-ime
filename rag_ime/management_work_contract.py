from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from .db.migration_runner import apply_database_migrations
from .settings_store import record_management_audit


PREVIEW_SCHEMA_VERSION = "rag-ime.management-work-preview.v1"
RECEIPT_SCHEMA_VERSION = "rag-ime.management-work-receipt.v1"
ERROR_SCHEMA_VERSION = "rag-ime.management-work-error.v1"
DEFAULT_PREVIEW_TTL_MS = 5 * 60 * 1000
MAX_CANONICAL_PAYLOAD_BYTES = 128 * 1024


class ManagementWorkError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current_revision: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.current_revision = dict(current_revision or {})

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": ERROR_SCHEMA_VERSION,
            "ok": False,
            "errorCode": self.code,
            "error": self.message,
            "currentRevision": self.current_revision,
        }


@dataclass(frozen=True)
class WorkExecution:
    result: Mapping[str, object]
    audit_action: str
    target_type: str
    target_id: str
    rollback_available: bool = False
    rollback_path_id: str = ""
    rollback_confirm: str = "rollback"
    rollback_authority: Mapping[str, object] = field(default_factory=dict)
    rollback_data: Mapping[str, object] = field(default_factory=dict)
    restart_components: tuple[str, ...] = ()
    audit_id: int | None = None


@dataclass(frozen=True)
class StoredReceipt:
    receipt_id: str
    path_id: str
    payload_sha256: str
    audit_id: int
    rollback_path_id: str
    rollback_confirm: str
    rollback_authority: Mapping[str, object]
    rollback_data: Mapping[str, object]


class ManagementWorkContract:
    """Persisted preview/apply/rollback contract for bounded management writes."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        preview_ttl_ms: int = DEFAULT_PREVIEW_TTL_MS,
        clock_ms: Callable[[], int] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.preview_ttl_ms = max(1_000, min(int(preview_ttl_ms), 30 * 60 * 1000))
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def create_preview(
        self,
        *,
        path_id: str,
        payload: Mapping[str, object],
        expected_revision: Mapping[str, object],
        required_confirm: str,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        normalized_path_id = _required_text(path_id, "pathId")
        normalized_confirm = _required_text(required_confirm, "requiredConfirm")
        payload_json = canonical_json(payload)
        revision_json = canonical_json(expected_revision)
        summary_json = canonical_json(summary)
        payload_sha256 = canonical_payload_sha256(payload)
        now = self._clock_ms()
        expires_at = now + self.preview_ttl_ms
        preview_token = self._token_factory()
        preview_id = f"work-preview:{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO management_work_previews(
                    preview_id, preview_token_sha256, path_id, payload_sha256,
                    payload_json, expected_revision_json, required_confirm,
                    summary_json, status, created_at_ms, expires_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    preview_id,
                    _secret_sha256(preview_token),
                    normalized_path_id,
                    payload_sha256,
                    payload_json,
                    revision_json,
                    normalized_confirm,
                    summary_json,
                    now,
                    expires_at,
                ),
            )
        return {
            "schemaVersion": PREVIEW_SCHEMA_VERSION,
            "ok": True,
            "previewToken": preview_token,
            "pathId": normalized_path_id,
            "payloadSha256": payload_sha256,
            "expectedRevision": dict(expected_revision),
            "expiresAtMs": expires_at,
            "requiredConfirm": normalized_confirm,
            "summary": dict(summary),
        }

    def execute_apply(
        self,
        *,
        path_id: str,
        payload: Mapping[str, object],
        preview_token: str,
        payload_sha256: str,
        confirm_text: str,
        current_revision: Callable[[sqlite3.Connection], Mapping[str, object]],
        executor: Callable[[sqlite3.Connection], WorkExecution],
    ) -> dict[str, object]:
        normalized_path_id = _required_text(path_id, "pathId")
        expected_hash = canonical_payload_sha256(payload)
        provided_hash = _required_text(payload_sha256, "payloadSha256")
        if not hmac.compare_digest(provided_hash, expected_hash):
            raise ManagementWorkError(
                "payload_hash_mismatch",
                "The apply payload does not match its canonical SHA-256.",
            )
        now = self._clock_ms()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT preview_id, path_id, payload_sha256, payload_json,
                       expected_revision_json, required_confirm, status,
                       expires_at_ms
                FROM management_work_previews
                WHERE preview_token_sha256 = ?
                """,
                (_secret_sha256(_required_text(preview_token, "previewToken")),),
            ).fetchone()
            if row is None:
                raise ManagementWorkError("preview_not_found", "The management preview token is invalid.")
            live_revision = dict(current_revision(conn))
            self._validate_preview(
                row=row,
                path_id=normalized_path_id,
                payload_sha256=provided_hash,
                payload_json=canonical_json(payload),
                confirm_text=confirm_text,
                live_revision=live_revision,
                now=now,
            )
            execution = executor(conn)
            audit_id = _execution_audit_id(
                conn,
                execution=execution,
                payload=dict(payload),
            )
            receipt_id = f"work-receipt:{uuid.uuid4().hex}"
            rollback_token = self._token_factory() if execution.rollback_available else ""
            conn.execute(
                """
                INSERT INTO management_work_receipts(
                    receipt_id, path_id, payload_sha256, applied_at_ms, audit_id,
                    rollback_available, rollback_token_sha256, rollback_path_id,
                    rollback_confirm, rollback_authority_json, rollback_data_json,
                    restart_components_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    normalized_path_id,
                    provided_hash,
                    now,
                    audit_id,
                    int(execution.rollback_available),
                    _secret_sha256(rollback_token) if rollback_token else "",
                    execution.rollback_path_id,
                    execution.rollback_confirm,
                    canonical_json(execution.rollback_authority),
                    canonical_json(execution.rollback_data),
                    canonical_json(list(execution.restart_components)),
                ),
            )
            updated = conn.execute(
                """
                UPDATE management_work_previews
                SET status = 'applied', consumed_at_ms = ?, receipt_id = ?
                WHERE preview_id = ? AND status = 'pending'
                """,
                (now, receipt_id, str(row["preview_id"])),
            )
            if updated.rowcount != 1:
                raise ManagementWorkError("preview_already_used", "The management preview was already consumed.")
        return _receipt_response(
            receipt_id=receipt_id,
            path_id=normalized_path_id,
            payload_sha256=provided_hash,
            applied_at_ms=now,
            audit_id=audit_id,
            rollback_available=execution.rollback_available,
            rollback_token=rollback_token,
            rollback_authority=execution.rollback_authority,
            restart_components=execution.restart_components,
            result=execution.result,
        )

    def execute_rollback(
        self,
        *,
        path_id: str,
        receipt_id: str,
        rollback_token: str,
        payload_sha256: str,
        confirm_text: str,
        expected_apply_path_id: str | tuple[str, ...],
        executor: Callable[[sqlite3.Connection, StoredReceipt], WorkExecution],
    ) -> dict[str, object]:
        normalized_path_id = _required_text(path_id, "pathId")
        original_receipt_id = _required_text(receipt_id, "receiptId")
        provided_hash = _required_text(payload_sha256, "payloadSha256")
        now = self._clock_ms()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT receipt_id, path_id, payload_sha256, audit_id,
                       rollback_available, rollback_token_sha256,
                       rollback_path_id, rollback_confirm,
                       rollback_authority_json, rollback_data_json,
                       rolled_back_at_ms
                FROM management_work_receipts
                WHERE receipt_id = ?
                """,
                (original_receipt_id,),
            ).fetchone()
            if row is None:
                raise ManagementWorkError("receipt_not_found", "The apply receipt was not found.")
            expected_apply_paths = (
                {expected_apply_path_id}
                if isinstance(expected_apply_path_id, str)
                else set(expected_apply_path_id)
            )
            if str(row["path_id"]) not in expected_apply_paths:
                raise ManagementWorkError("receipt_path_mismatch", "The receipt belongs to another mutation.")
            if int(row["rolled_back_at_ms"] or 0):
                raise ManagementWorkError("receipt_already_rolled_back", "This receipt was already rolled back.")
            if not bool(row["rollback_available"]):
                raise ManagementWorkError("rollback_unavailable", "This receipt cannot be rolled back.")
            if str(row["rollback_path_id"]) != normalized_path_id:
                raise ManagementWorkError("rollback_path_mismatch", "The receipt does not allow this rollback route.")
            if not hmac.compare_digest(str(row["payload_sha256"]), provided_hash):
                raise ManagementWorkError("payload_hash_mismatch", "The rollback hash does not match the apply receipt.")
            expected_token_hash = str(row["rollback_token_sha256"])
            if not expected_token_hash or not hmac.compare_digest(
                expected_token_hash,
                _secret_sha256(_required_text(rollback_token, "rollbackToken")),
            ):
                raise ManagementWorkError("rollback_token_mismatch", "The rollback token is invalid.")
            required_confirm = str(row["rollback_confirm"])
            if not hmac.compare_digest(_normalized_confirm(confirm_text), required_confirm):
                raise ManagementWorkError(
                    "confirmation_mismatch",
                    f'Confirmation required: enter "{required_confirm}" exactly.',
                )
            stored = StoredReceipt(
                receipt_id=original_receipt_id,
                path_id=str(row["path_id"]),
                payload_sha256=str(row["payload_sha256"]),
                audit_id=int(row["audit_id"] or 0),
                rollback_path_id=str(row["rollback_path_id"]),
                rollback_confirm=required_confirm,
                rollback_authority=_json_object(row["rollback_authority_json"]),
                rollback_data=_json_object(row["rollback_data_json"]),
            )
            execution = executor(conn, stored)
            audit_id = _execution_audit_id(
                conn,
                execution=execution,
                payload={
                    "receiptId": original_receipt_id,
                    "payloadSha256": provided_hash,
                    "rollbackAuthority": dict(stored.rollback_authority),
                },
            )
            rollback_receipt_id = f"work-receipt:{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO management_work_receipts(
                    receipt_id, path_id, payload_sha256, applied_at_ms, audit_id,
                    rollback_available, rollback_token_sha256, rollback_path_id,
                    rollback_confirm, rollback_authority_json, rollback_data_json,
                    restart_components_json, rollback_of_receipt_id
                ) VALUES (?, ?, ?, ?, ?, 0, '', '', '', '{}', '{}', ?, ?)
                """,
                (
                    rollback_receipt_id,
                    normalized_path_id,
                    provided_hash,
                    now,
                    audit_id,
                    canonical_json(list(execution.restart_components)),
                    original_receipt_id,
                ),
            )
            updated = conn.execute(
                """
                UPDATE management_work_receipts
                SET rollback_available = 0, rolled_back_at_ms = ?, rollback_receipt_id = ?
                WHERE receipt_id = ? AND rolled_back_at_ms IS NULL
                """,
                (now, rollback_receipt_id, original_receipt_id),
            )
            if updated.rowcount != 1:
                raise ManagementWorkError("receipt_already_rolled_back", "This receipt was already rolled back.")
        response = _receipt_response(
            receipt_id=rollback_receipt_id,
            path_id=normalized_path_id,
            payload_sha256=provided_hash,
            applied_at_ms=now,
            audit_id=audit_id,
            rollback_available=False,
            rollback_token="",
            rollback_authority=stored.rollback_authority,
            restart_components=execution.restart_components,
            result=execution.result,
        )
        response["rollbackOfReceiptId"] = original_receipt_id
        return response

    @staticmethod
    def error_payload(error: BaseException, *, current_revision: Mapping[str, object]) -> dict[str, object]:
        if isinstance(error, ManagementWorkError):
            if not error.current_revision:
                error.current_revision = dict(current_revision)
            return error.payload()
        return ManagementWorkError(
            "domain_rejected",
            "The domain mutation was rejected without changing managed state.",
            current_revision=current_revision,
        ).payload()

    def _validate_preview(
        self,
        *,
        row: sqlite3.Row,
        path_id: str,
        payload_sha256: str,
        payload_json: str,
        confirm_text: str,
        live_revision: Mapping[str, object],
        now: int,
    ) -> None:
        if str(row["status"]) != "pending":
            raise ManagementWorkError("preview_already_used", "The management preview was already consumed.")
        if int(row["expires_at_ms"]) <= now:
            raise ManagementWorkError("preview_expired", "The management preview has expired.")
        if str(row["path_id"]) != path_id:
            raise ManagementWorkError("preview_path_mismatch", "The preview belongs to another mutation.")
        if not hmac.compare_digest(str(row["payload_sha256"]), payload_sha256):
            raise ManagementWorkError("payload_hash_mismatch", "The apply hash does not match the preview.")
        if not hmac.compare_digest(
            str(row["payload_json"]).encode("utf-8"),
            payload_json.encode("utf-8"),
        ):
            raise ManagementWorkError("payload_hash_mismatch", "The apply payload does not match the preview.")
        required_confirm = str(row["required_confirm"])
        if not hmac.compare_digest(_normalized_confirm(confirm_text), required_confirm):
            raise ManagementWorkError(
                "confirmation_mismatch",
                f'Confirmation required: enter "{required_confirm}" exactly.',
                current_revision=live_revision,
            )
        expected_revision = _json_object(row["expected_revision_json"])
        if canonical_json(expected_revision) != canonical_json(live_revision):
            raise ManagementWorkError(
                "revision_mismatch",
                "The managed state changed after this preview was created.",
                current_revision=live_revision,
            )

    def _connect(self) -> "_ConnectionContext":
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Work-contract executors perform domain writes on this connection,
        # including rollback of parent rows such as Memory Atoms. Keep the
        # same referential-integrity contract as LocalSqliteCoreClient so a
        # management apply/rollback cannot strand child projections.
        conn.execute("PRAGMA foreign_keys = ON")
        apply_database_migrations(conn)
        return _ConnectionContext(conn)


class _ConnectionContext:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


def canonical_json(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ManagementWorkError("invalid_payload", "The management payload is not canonical JSON.") from exc
    if len(encoded.encode("utf-8")) > MAX_CANONICAL_PAYLOAD_BYTES:
        raise ManagementWorkError("payload_too_large", "The management payload exceeds 128 KiB.")
    return encoded


def canonical_payload_sha256(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _execution_audit_id(
    conn: sqlite3.Connection,
    *,
    execution: WorkExecution,
    payload: Mapping[str, object],
) -> int:
    if execution.audit_id is None:
        return record_management_audit(
            conn,
            action=execution.audit_action,
            target_type=execution.target_type,
            target_id=execution.target_id,
            payload=payload,
            result=dict(execution.result),
        )
    audit_id = int(execution.audit_id)
    if audit_id < 1:
        raise ManagementWorkError("stored_contract_invalid", "The execution audit id is invalid.")
    row = conn.execute(
        """
        SELECT id, action, target_type, target_id
        FROM management_audit_log
        WHERE id = ?
        LIMIT 1
        """,
        (audit_id,),
    ).fetchone()
    if row is None:
        raise ManagementWorkError("stored_contract_invalid", "The execution audit record is missing.")
    if (
        str(row["action"]) != execution.audit_action
        or str(row["target_type"]) != execution.target_type
        or str(row["target_id"]) != execution.target_id
    ):
        raise ManagementWorkError(
            "stored_contract_invalid",
            "The execution audit record does not match the mutation.",
        )
    return audit_id


def _receipt_response(
    *,
    receipt_id: str,
    path_id: str,
    payload_sha256: str,
    applied_at_ms: int,
    audit_id: int,
    rollback_available: bool,
    rollback_token: str,
    rollback_authority: Mapping[str, object],
    restart_components: tuple[str, ...],
    result: Mapping[str, object],
) -> dict[str, object]:
    domain = dict(result)
    response = {
        **{key: value for key, value in domain.items() if key not in {"schemaVersion", "ok"}},
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "ok": True,
        "receiptId": receipt_id,
        "pathId": path_id,
        "payloadSha256": payload_sha256,
        "appliedAtMs": applied_at_ms,
        "auditId": audit_id,
        "rollbackAvailable": rollback_available,
        "rollbackToken": rollback_token,
        "rollbackAuthority": dict(rollback_authority),
        "restartComponents": list(restart_components),
        "result": domain,
    }
    return response


def _secret_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ManagementWorkError("invalid_request", f"{field} is required.")
    return normalized


def _normalized_confirm(value: object) -> str:
    return str(value or "").strip()


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise ManagementWorkError("stored_contract_invalid", "Stored management contract data is invalid.") from exc
    if not isinstance(parsed, dict):
        raise ManagementWorkError("stored_contract_invalid", "Stored management contract data is invalid.")
    return parsed
