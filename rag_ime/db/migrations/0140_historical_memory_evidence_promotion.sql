-- A recovered legacy input remains audit Evidence.  A user-authorized,
-- offline full-history run may create a second canonical Evidence row, but
-- only with an immutable receipt tying it back to the recovered source and
-- exact input event.  The receipt grants review eligibility, never an Atom.
CREATE TABLE memory_evidence_historical_promotion_receipts (
    receipt_id TEXT PRIMARY KEY,
    promoted_evidence_id TEXT NOT NULL UNIQUE
        REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    legacy_evidence_id TEXT NOT NULL UNIQUE
        REFERENCES agent_memory_evidence(evidence_id) ON DELETE RESTRICT,
    source_id TEXT NOT NULL
        REFERENCES agent_memory_sources(source_id) ON DELETE RESTRICT,
    input_event_id INTEGER NOT NULL
        REFERENCES input_events(id) ON DELETE RESTRICT,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    authorization_kind TEXT NOT NULL
        CHECK (authorization_kind = 'user_authorized_full_history_v1'),
    authorization_run_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    CHECK (promoted_evidence_id != legacy_evidence_id)
);

CREATE INDEX idx_memory_evidence_historical_promotion_source
ON memory_evidence_historical_promotion_receipts(
    source_id, input_event_id, created_at_ms
);

CREATE TRIGGER trg_memory_evidence_historical_promotion_no_update
BEFORE UPDATE ON memory_evidence_historical_promotion_receipts
BEGIN
    SELECT RAISE(ABORT, 'HistoricalEvidencePromotionReceipt is immutable');
END;

CREATE TRIGGER trg_memory_evidence_historical_promotion_no_delete
BEFORE DELETE ON memory_evidence_historical_promotion_receipts
BEGIN
    SELECT RAISE(ABORT, 'HistoricalEvidencePromotionReceipt is permanent');
END;
