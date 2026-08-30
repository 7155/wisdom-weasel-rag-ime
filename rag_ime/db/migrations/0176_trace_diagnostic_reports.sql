-- Runtime-owned Trace diagnostic reports.  Report revisions are immutable;
-- the small head row only identifies the current revision and lifecycle state.
CREATE TABLE trace_diagnostic_reports (
    report_id TEXT PRIMARY KEY,
    diagnostic_session_id TEXT NOT NULL UNIQUE,
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    status TEXT NOT NULL CHECK (status IN ('generating', 'completed', 'failed')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms)
);

CREATE TABLE trace_diagnostic_report_revisions (
    report_id TEXT NOT NULL REFERENCES trace_diagnostic_reports(report_id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY (report_id, revision)
);

CREATE TABLE trace_diagnostic_report_targets (
    report_id TEXT NOT NULL REFERENCES trace_diagnostic_reports(report_id),
    target_kind TEXT NOT NULL CHECK (target_kind IN ('session', 'room', 'run')),
    target_id TEXT NOT NULL,
    PRIMARY KEY (report_id, target_kind, target_id)
);

CREATE INDEX idx_trace_diagnostic_reports_updated
    ON trace_diagnostic_reports(updated_at_ms DESC, report_id DESC);

CREATE INDEX idx_trace_diagnostic_report_targets_lookup
    ON trace_diagnostic_report_targets(target_kind, target_id, report_id);

CREATE TRIGGER trace_diagnostic_report_revisions_immutable_update
BEFORE UPDATE ON trace_diagnostic_report_revisions
BEGIN
    SELECT RAISE(ABORT, 'Trace diagnostic report revisions are immutable');
END;

CREATE TRIGGER trace_diagnostic_report_revisions_immutable_delete
BEFORE DELETE ON trace_diagnostic_report_revisions
BEGIN
    SELECT RAISE(ABORT, 'Trace diagnostic report revisions are permanent');
END;
