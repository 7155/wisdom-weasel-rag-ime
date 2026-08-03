from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Mapping

from .text_utils import compact_whitespace


CAPTURE_SCHEMA_VERSION = "rag-ime.input-capture.v2"
CAPTURE_RECEIPT_SCHEMA_VERSION = "rag-ime.input-capture-receipt.v2"
_CHANNELS = {"input_method", "voice"}
_BOUNDARIES = {
    "host_return",
    "focus_change",
    "app_change",
    "deactivate",
    "voice_final",
}
_CAPTURE_SOURCES = {
    "text_input_client",
    "accessibility",
    "ime_active_buffer",
    "voice_insertion",
}
_HEX = frozenset("0123456789abcdef")


class InputCaptureContractError(ValueError):
    pass


class InputCaptureIdentityConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class InputCaptureContractV2:
    capture_id: str
    transaction_id: str
    sequence: int
    channel: str
    boundary_kind: str
    boundary_confidence: str
    native_composition_before: bool
    rime_handled: bool
    host_forwarded: bool
    modified_return: bool
    final_committed: bool
    controller_epoch: int
    focus_epoch: int
    app_bundle_id: str
    field_identity_sha256: str
    privacy_revision: str
    occurred_start_ms: int
    occurred_end_ms: int
    content_sha256: str
    capture_source: str
    fallback_reason: str
    field_context_chars: int
    ime_buffer_chars: int
    selection_rule: str

    @property
    def is_strong_final(self) -> bool:
        return self.boundary_confidence == "strong" and self.final_committed

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "schemaVersion": CAPTURE_SCHEMA_VERSION,
            "captureId": self.capture_id,
            "transactionId": self.transaction_id,
            "sequence": self.sequence,
            "channel": self.channel,
            "boundaryKind": self.boundary_kind,
            "boundaryConfidence": self.boundary_confidence,
            "nativeCompositionBefore": self.native_composition_before,
            "rimeHandled": self.rime_handled,
            "hostForwarded": self.host_forwarded,
            "modifiedReturn": self.modified_return,
            "finalCommitted": self.final_committed,
            "controllerEpoch": self.controller_epoch,
            "focusEpoch": self.focus_epoch,
            "appBundleId": self.app_bundle_id,
            "fieldIdentitySha256": self.field_identity_sha256,
            "privacyRevision": self.privacy_revision,
            "occurredStartMs": self.occurred_start_ms,
            "occurredEndMs": self.occurred_end_ms,
            "contentSha256": self.content_sha256,
            "captureSource": self.capture_source,
            "fallbackReason": self.fallback_reason,
            "fieldContextChars": self.field_context_chars,
            "imeBufferChars": self.ime_buffer_chars,
            "selectionRule": self.selection_rule,
        }

    @property
    def metadata_sha256(self) -> str:
        payload = json.dumps(
            self.metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def sanitize_input_capture_metadata(
    value: object,
    *,
    text: str,
    source: str,
    app: str,
) -> dict[str, object]:
    """Return bounded text-free metadata, validating v2 contracts fail closed."""

    if not isinstance(value, Mapping):
        return {}
    schema_version = compact_whitespace(str(value.get("schemaVersion") or ""))
    if not schema_version:
        return _legacy_capture_metadata(value)
    if schema_version != CAPTURE_SCHEMA_VERSION:
        raise InputCaptureContractError("unsupported input capture schemaVersion")
    return parse_input_capture_contract(
        value,
        text=text,
        source=source,
        app=app,
    ).metadata


def capture_contract_from_metadata(
    value: object,
    *,
    text: str,
    source: str,
    app: str,
) -> InputCaptureContractV2 | None:
    if not isinstance(value, Mapping):
        return None
    schema_version = compact_whitespace(str(value.get("schemaVersion") or ""))
    if not schema_version:
        return None
    if schema_version != CAPTURE_SCHEMA_VERSION:
        raise InputCaptureContractError("unsupported input capture schemaVersion")
    return parse_input_capture_contract(value, text=text, source=source, app=app)


def parse_input_capture_contract(
    value: Mapping[str, object],
    *,
    text: str,
    source: str,
    app: str,
) -> InputCaptureContractV2:
    capture_id = _required_token(value.get("captureId"), "captureId", maximum=160)
    transaction_id = _required_token(
        value.get("transactionId"), "transactionId", maximum=160
    )
    sequence = _required_int(value.get("sequence"), "sequence", minimum=1)
    channel = _required_choice(value.get("channel"), "channel", _CHANNELS)
    boundary_kind = _required_choice(
        value.get("boundaryKind"), "boundaryKind", _BOUNDARIES
    )
    boundary_confidence = _required_choice(
        value.get("boundaryConfidence"),
        "boundaryConfidence",
        {"strong", "weak"},
    )
    native_composition_before = _required_bool(
        value.get("nativeCompositionBefore"), "nativeCompositionBefore"
    )
    rime_handled = _required_bool(value.get("rimeHandled"), "rimeHandled")
    host_forwarded = _required_bool(value.get("hostForwarded"), "hostForwarded")
    modified_return = _required_bool(value.get("modifiedReturn"), "modifiedReturn")
    final_committed = _required_bool(value.get("finalCommitted"), "finalCommitted")
    controller_epoch = _required_int(
        value.get("controllerEpoch"), "controllerEpoch", minimum=0
    )
    focus_epoch = _required_int(value.get("focusEpoch"), "focusEpoch", minimum=0)
    app_bundle_id = _required_token(
        value.get("appBundleId"), "appBundleId", maximum=300
    )
    normalized_app = compact_whitespace(app)
    if normalized_app and app_bundle_id != normalized_app:
        raise InputCaptureContractError("capture appBundleId does not match request app")
    field_identity_sha256 = _required_sha256(
        value.get("fieldIdentitySha256"), "fieldIdentitySha256"
    )
    privacy_revision = _required_token(
        value.get("privacyRevision"), "privacyRevision", maximum=120
    )
    occurred_start_ms = _required_int(
        value.get("occurredStartMs"), "occurredStartMs", minimum=0
    )
    occurred_end_ms = _required_int(
        value.get("occurredEndMs"), "occurredEndMs", minimum=occurred_start_ms
    )
    content_sha256 = _required_sha256(value.get("contentSha256"), "contentSha256")
    expected_content_sha256 = hashlib.sha256(
        compact_whitespace(text).encode("utf-8")
    ).hexdigest()
    if content_sha256 != expected_content_sha256:
        raise InputCaptureContractError("capture contentSha256 does not match text")
    capture_source = _required_choice(
        value.get("captureSource"), "captureSource", _CAPTURE_SOURCES
    )
    if channel == "voice" and capture_source != "voice_insertion":
        raise InputCaptureContractError("voice capture requires voice_insertion source")
    if channel == "input_method" and capture_source == "voice_insertion":
        raise InputCaptureContractError("input_method capture cannot use voice_insertion source")
    fallback_reason = _bounded_text(value.get("fallbackReason"), maximum=120)
    field_context_chars = _required_int(
        value.get("fieldContextChars"), "fieldContextChars", minimum=0, maximum=100_000
    )
    ime_buffer_chars = _required_int(
        value.get("imeBufferChars"), "imeBufferChars", minimum=0, maximum=100_000
    )
    selection_rule = _bounded_text(value.get("selectionRule"), maximum=120)

    normalized_source = compact_whitespace(source).lower()
    if channel == "input_method" and normalized_source != "squirrel_input_segment":
        raise InputCaptureContractError("input_method capture requires squirrel_input_segment")
    if channel == "voice" and normalized_source != "voice_final":
        raise InputCaptureContractError("voice capture requires voice_final")
    _validate_boundary(
        channel=channel,
        boundary_kind=boundary_kind,
        boundary_confidence=boundary_confidence,
        native_composition_before=native_composition_before,
        rime_handled=rime_handled,
        host_forwarded=host_forwarded,
        modified_return=modified_return,
        final_committed=final_committed,
    )
    return InputCaptureContractV2(
        capture_id=capture_id,
        transaction_id=transaction_id,
        sequence=sequence,
        channel=channel,
        boundary_kind=boundary_kind,
        boundary_confidence=boundary_confidence,
        native_composition_before=native_composition_before,
        rime_handled=rime_handled,
        host_forwarded=host_forwarded,
        modified_return=modified_return,
        final_committed=final_committed,
        controller_epoch=controller_epoch,
        focus_epoch=focus_epoch,
        app_bundle_id=app_bundle_id,
        field_identity_sha256=field_identity_sha256,
        privacy_revision=privacy_revision,
        occurred_start_ms=occurred_start_ms,
        occurred_end_ms=occurred_end_ms,
        content_sha256=content_sha256,
        capture_source=capture_source,
        fallback_reason=fallback_reason,
        field_context_chars=field_context_chars,
        ime_buffer_chars=ime_buffer_chars,
        selection_rule=selection_rule,
    )


def read_capture_receipt(
    conn: sqlite3.Connection,
    capture_id: str,
    *,
    duplicate: bool = True,
) -> dict[str, object] | None:
    if not _table_exists(conn, "input_capture_receipts"):
        return None
    row = conn.execute(
        "SELECT * FROM input_capture_receipts WHERE capture_id = ?",
        (capture_id,),
    ).fetchone()
    return None if row is None else _receipt_payload(row, duplicate=duplicate)


def find_capture_receipt(
    conn: sqlite3.Connection,
    contract: InputCaptureContractV2,
) -> dict[str, object] | None:
    """Resolve an exact replay and reject either form of identity reuse."""

    if not _table_exists(conn, "input_capture_receipts"):
        return None
    existing = conn.execute(
        "SELECT * FROM input_capture_receipts WHERE capture_id = ?",
        (contract.capture_id,),
    ).fetchone()
    if existing is not None:
        _verify_existing_receipt(existing, contract)
        return _receipt_payload(existing, duplicate=True)
    transaction_row = conn.execute(
        """
        SELECT * FROM input_capture_receipts
        WHERE channel = ? AND transaction_id = ? AND sequence = ?
        """,
        (contract.channel, contract.transaction_id, contract.sequence),
    ).fetchone()
    if transaction_row is not None:
        raise InputCaptureIdentityConflict(
            "capture transaction sequence was reused with another captureId"
        )
    return None


def record_capture_receipt(
    conn: sqlite3.Connection,
    contract: InputCaptureContractV2,
    *,
    outcome: str,
    reason_code: str,
    input_event_id: int | None,
    created_at_ms: int,
) -> dict[str, object]:
    if outcome not in {"stored", "no_store", "quarantined"}:
        raise ValueError("invalid capture receipt outcome")
    if not _table_exists(conn, "input_capture_receipts"):
        raise RuntimeError("input_capture_receipts table is unavailable")
    existing = find_capture_receipt(conn, contract)
    if existing is not None:
        return existing
    conn.execute(
        """
        INSERT INTO input_capture_receipts(
            capture_id, transaction_id, sequence, channel, boundary_kind,
            boundary_confidence, content_sha256, metadata_sha256,
            input_event_id, outcome, reason_code, occurred_start_ms,
            occurred_end_ms, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contract.capture_id,
            contract.transaction_id,
            contract.sequence,
            contract.channel,
            contract.boundary_kind,
            contract.boundary_confidence,
            contract.content_sha256,
            contract.metadata_sha256,
            input_event_id,
            outcome,
            compact_whitespace(reason_code)[:120] or "unspecified",
            contract.occurred_start_ms,
            contract.occurred_end_ms,
            max(0, int(created_at_ms)),
        ),
    )
    row = conn.execute(
        "SELECT * FROM input_capture_receipts WHERE capture_id = ?",
        (contract.capture_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("capture receipt did not persist")
    return _receipt_payload(row, duplicate=False)


def _validate_boundary(
    *,
    channel: str,
    boundary_kind: str,
    boundary_confidence: str,
    native_composition_before: bool,
    rime_handled: bool,
    host_forwarded: bool,
    modified_return: bool,
    final_committed: bool,
) -> None:
    if boundary_kind == "host_return":
        if channel != "input_method":
            raise InputCaptureContractError("host_return must use input_method channel")
        if boundary_confidence != "strong":
            raise InputCaptureContractError("host_return must be a strong boundary")
        if native_composition_before or rime_handled or not host_forwarded:
            raise InputCaptureContractError(
                "host_return requires no prior composition, unhandled Rime, and host forwarding"
            )
        if modified_return or not final_committed:
            raise InputCaptureContractError(
                "modified or uncommitted Return cannot be a strong final boundary"
            )
        return
    if boundary_kind == "voice_final":
        if (
            channel != "voice"
            or boundary_confidence != "strong"
            or native_composition_before
            or rime_handled
            or not host_forwarded
            or modified_return
            or not final_committed
        ):
            raise InputCaptureContractError(
                "voice_final requires a strong successfully inserted final boundary"
            )
        return
    if channel != "input_method" or boundary_confidence != "weak":
        raise InputCaptureContractError(
            "focus/app/deactivate captures must be weak input_method boundaries"
        )
    if host_forwarded or final_committed:
        raise InputCaptureContractError("weak lifecycle boundary cannot claim host commit")


def _verify_existing_receipt(
    row: sqlite3.Row,
    contract: InputCaptureContractV2,
) -> None:
    identity = (
        str(row["transaction_id"]),
        int(row["sequence"]),
        str(row["channel"]),
        str(row["content_sha256"]),
        str(row["metadata_sha256"]),
    )
    expected = (
        contract.transaction_id,
        contract.sequence,
        contract.channel,
        contract.content_sha256,
        contract.metadata_sha256,
    )
    if identity != expected:
        raise InputCaptureIdentityConflict(
            "captureId was replayed with different immutable content"
        )


def _receipt_payload(row: sqlite3.Row, *, duplicate: bool) -> dict[str, object]:
    event_id = row["input_event_id"]
    columns = set(row.keys())
    return {
        "schemaVersion": CAPTURE_RECEIPT_SCHEMA_VERSION,
        "captureId": str(row["capture_id"]),
        "transactionId": str(row["transaction_id"]),
        "sequence": int(row["sequence"]),
        "channel": str(row["channel"]),
        "boundaryKind": str(row["boundary_kind"]),
        "boundaryConfidence": str(row["boundary_confidence"]),
        "contentSha256": str(row["content_sha256"]),
        "eventId": "" if event_id is None else f"event:{int(event_id)}",
        "outcome": str(row["outcome"]),
        "reason": str(row["reason_code"]),
        "evidenceId": str(row["evidence_id"]) if "evidence_id" in columns else "",
        "evidenceState": (
            str(row["evidence_state"])
            if "evidence_state" in columns
            else "not_evaluated"
        ),
        "evidenceReason": (
            str(row["evidence_reason"])
            if "evidence_reason" in columns
            else ""
        ),
        "duplicate": duplicate,
    }


def _legacy_capture_metadata(value: Mapping[str, object]) -> dict[str, object]:
    source = compact_whitespace(str(value.get("captureSource") or ""))
    if source not in _CAPTURE_SOURCES - {"voice_insertion"}:
        source = "unknown"
    digest = _optional_sha256(value.get("selectedTextSha256"))
    return {
        "captureSource": source,
        "fallbackReason": _bounded_text(value.get("fallbackReason"), maximum=120),
        "fieldContextChars": _optional_int(
            value.get("fieldContextChars"), minimum=0, maximum=100_000
        ),
        "imeBufferChars": _optional_int(
            value.get("imeBufferChars"), minimum=0, maximum=100_000
        ),
        "selectedTextSha256": digest,
        "selectionRule": _bounded_text(value.get("selectionRule"), maximum=120),
    }


def _required_token(value: object, field: str, *, maximum: int) -> str:
    result = compact_whitespace(str(value or ""))
    if not result or len(result) > maximum or any(ord(char) < 32 for char in result):
        raise InputCaptureContractError(f"{field} is missing or invalid")
    return result


def _required_choice(value: object, field: str, choices: set[str]) -> str:
    result = compact_whitespace(str(value or "")).lower()
    if result not in choices:
        raise InputCaptureContractError(f"{field} is invalid")
    return result


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise InputCaptureContractError(f"{field} must be boolean")
    return value


def _required_int(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int = 9_223_372_036_854_775_807,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputCaptureContractError(f"{field} must be integer")
    if value < minimum or value > maximum:
        raise InputCaptureContractError(f"{field} is out of range")
    return value


def _required_sha256(value: object, field: str) -> str:
    digest = _optional_sha256(value)
    if not digest:
        raise InputCaptureContractError(f"{field} must be a SHA-256 digest")
    return digest


def _optional_sha256(value: object) -> str:
    digest = compact_whitespace(str(value or "")).lower().removeprefix("sha256:")
    if len(digest) != 64 or any(character not in _HEX for character in digest):
        return ""
    return digest


def _bounded_text(value: object, *, maximum: int) -> str:
    return compact_whitespace(str(value or ""))[:maximum]


def _optional_int(value: object, *, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, result))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )
