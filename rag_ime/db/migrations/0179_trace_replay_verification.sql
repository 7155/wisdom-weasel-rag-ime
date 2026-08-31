CREATE TABLE trace_replay_cases (
    replay_case_id TEXT PRIMARY KEY,
    source_trace_id TEXT NOT NULL REFERENCES trace_envelopes(trace_id),
    baseline_eval_run_id TEXT NOT NULL REFERENCES eval_runs(eval_run_id),
    baseline_sandbox_run_id TEXT NOT NULL REFERENCES sandbox_runs(sandbox_run_id),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE trace_verification_receipts (
    verification_receipt_id TEXT PRIMARY KEY,
    replay_case_id TEXT NOT NULL REFERENCES trace_replay_cases(replay_case_id),
    repair_receipt_id TEXT NOT NULL REFERENCES trace_repair_receipts(repair_receipt_id),
    repair_eval_run_id TEXT NOT NULL REFERENCES eval_runs(eval_run_id),
    repair_sandbox_run_id TEXT NOT NULL REFERENCES sandbox_runs(sandbox_run_id),
    decision TEXT NOT NULL CHECK (decision IN ('kept', 'rejected')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_trace_replay_cases_source
    ON trace_replay_cases(source_trace_id, created_at_ms, replay_case_id);

CREATE INDEX idx_trace_verification_receipts_case
    ON trace_verification_receipts(replay_case_id, created_at_ms, verification_receipt_id);

CREATE TRIGGER trace_replay_cases_immutable_update
BEFORE UPDATE ON trace_replay_cases
BEGIN
    SELECT RAISE(ABORT, 'trace replay cases are immutable');
END;

CREATE TRIGGER trace_replay_cases_immutable_delete
BEFORE DELETE ON trace_replay_cases
BEGIN
    SELECT RAISE(ABORT, 'trace replay cases are immutable');
END;

CREATE TRIGGER trace_verification_receipts_immutable_update
BEFORE UPDATE ON trace_verification_receipts
BEGIN
    SELECT RAISE(ABORT, 'trace verification receipts are immutable');
END;

CREATE TRIGGER trace_verification_receipts_immutable_delete
BEFORE DELETE ON trace_verification_receipts
BEGIN
    SELECT RAISE(ABORT, 'trace verification receipts are immutable');
END;
