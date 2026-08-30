-- Durable, append-only authority for Trace repair evidence and repair receipts.
CREATE TABLE trace_repair_evidence (
    evidence_id TEXT PRIMARY KEY,
    evidence_kind TEXT NOT NULL CHECK (evidence_kind IN ('change', 'test')),
    source_scope TEXT NOT NULL,
    source_trace_id TEXT NOT NULL,
    test_status TEXT NOT NULL DEFAULT '' CHECK (test_status IN ('', 'passed', 'failed', 'blocked')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);

CREATE TABLE trace_repair_receipts (
    repair_receipt_id TEXT PRIMARY KEY,
    source_scope TEXT NOT NULL,
    source_trace_id TEXT NOT NULL,
    failure_ref TEXT NOT NULL,
    change_receipt_id TEXT NOT NULL REFERENCES trace_repair_evidence(evidence_id),
    test_evidence_id TEXT NOT NULL REFERENCES trace_repair_evidence(evidence_id),
    test_status TEXT NOT NULL CHECK (test_status IN ('passed', 'failed', 'blocked')),
    repair_trace_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);

CREATE INDEX idx_trace_repair_evidence_trace
    ON trace_repair_evidence(source_trace_id, created_at_ms, evidence_id);

CREATE INDEX idx_trace_repair_receipts_source
    ON trace_repair_receipts(source_trace_id, created_at_ms, repair_receipt_id);

CREATE INDEX idx_trace_repair_receipts_repair_trace
    ON trace_repair_receipts(repair_trace_id, created_at_ms, repair_receipt_id);

CREATE TRIGGER trace_repair_evidence_immutable_update
BEFORE UPDATE ON trace_repair_evidence
BEGIN
    SELECT RAISE(ABORT, 'Trace repair evidence is immutable');
END;

CREATE TRIGGER trace_repair_evidence_immutable_delete
BEFORE DELETE ON trace_repair_evidence
BEGIN
    SELECT RAISE(ABORT, 'Trace repair evidence is permanent');
END;

CREATE TRIGGER trace_repair_receipts_immutable_update
BEFORE UPDATE ON trace_repair_receipts
BEGIN
    SELECT RAISE(ABORT, 'Trace repair receipt is immutable');
END;

CREATE TRIGGER trace_repair_receipts_immutable_delete
BEFORE DELETE ON trace_repair_receipts
BEGIN
    SELECT RAISE(ABORT, 'Trace repair receipt is permanent');
END;
