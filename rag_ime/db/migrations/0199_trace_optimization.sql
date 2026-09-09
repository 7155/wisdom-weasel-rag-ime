-- Proposals, comparisons and application bindings retain their distinct
-- authorities. Reports join these immutable records without rewriting a
-- completed model diagnosis or the strict v1 replay contract.
CREATE TABLE trace_optimization_records (
    record_id TEXT PRIMARY KEY,
    record_kind TEXT NOT NULL CHECK (record_kind IN ('candidate', 'comparison', 'application')),
    report_id TEXT NOT NULL REFERENCES trace_diagnostic_reports(report_id),
    candidate_id TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL CHECK (length(request_sha256) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    UNIQUE (record_kind, report_id, client_request_id)
);
CREATE INDEX trace_optimization_report_records
    ON trace_optimization_records(report_id, created_at_ms, record_id);
CREATE INDEX trace_optimization_candidate_records
    ON trace_optimization_records(candidate_id, record_kind, created_at_ms);
CREATE TRIGGER trace_optimization_records_no_update
BEFORE UPDATE ON trace_optimization_records
BEGIN
    SELECT RAISE(ABORT, 'Trace optimization records are immutable');
END;
CREATE TRIGGER trace_optimization_records_no_delete
BEFORE DELETE ON trace_optimization_records
BEGIN
    SELECT RAISE(ABORT, 'Trace optimization attempts are retained');
END;
