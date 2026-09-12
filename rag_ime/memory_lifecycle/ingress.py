"""Adapters used by the existing capture/evidence/source owners."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .common import excluded
from .privacy import CapturePolicy, assess_capture, redact_text


def gate_input_event(core: Any, event: Any, capture_receipts: list[dict[str, object]] | None) -> tuple[Any | None, str]:
    """Return a sanitized copy or a no-store result before the first content write.

    A v2 receipt binds the native original hash. Redacting its text would forge
    that identity, so redacted typed captures receive a text-free no-store ack.
    """
    metadata = dict(event.capture_metadata)
    disposition = " ".join(str(event.privacy_disposition).split()).lower()
    if disposition not in {"allowed", "sensitive", "unknown"}:
        raise ValueError("privacy_disposition must be allowed, sensitive, or unknown")
    decision = assess_capture(source=event.source, text=event.committed_text,
        metadata=metadata, tags=tuple(event.tags), disposition=disposition)
    recent = redact_text(event.recent_context) if decision.allowed else ""
    preedit = redact_text(event.preedit) if decision.allowed else ""
    typed = capture_receipts is not None or metadata.get("schemaVersion") in {
        "rag-ime.input-capture.v2", "rag-ime.input-capture-contract.v2"} or "captureId" in metadata
    reason = decision.reason
    allow = decision.allowed
    if allow and typed and (decision.redacted or recent != event.recent_context or preedit != event.preedit):
        allow, reason = False, "typed_capture_requires_no_store"
    if allow:
        core.initialize()
        session = str(metadata.get("sessionId") or "")
        if not session and event.context_group_id.startswith("agent-session:"):
            session = event.context_group_id.removeprefix("agent-session:")
        with core._connect() as conn:
            if excluded(conn, project=event.project, session_id=session, source_id=str(metadata.get("captureId") or "")):
                allow, reason = False, "capture_scope_excluded"
    if not allow:
        if capture_receipts is not None:
            receipt = core.record_capture_outcome(text=event.committed_text, source=event.source, app=event.app,
                capture_metadata=metadata, outcome="no_store", reason_code=reason, created_at_ms=event.created_at_ms)
            capture_receipts.append(receipt)
        return None, "skipped:" + reason
    return replace(event, committed_text=decision.text, recent_context=recent, preedit=preedit,
                   capture_metadata=decision.metadata), ""


def configured_policy() -> CapturePolicy:
    return CapturePolicy.from_environment()
