CREATE TABLE agent_lab_golden_suites (
    suite_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE agent_lab_golden_commands (
    client_request_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES agent_lab_golden_suites(suite_id),
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE agent_lab_golden_jobs (
    job_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES agent_lab_golden_suites(suite_id),
    kind TEXT NOT NULL CHECK (kind IN ('draft', 'calibrate', 'experiment')),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'interrupted')),
    payload_json TEXT NOT NULL,
    input_json TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    execution_started INTEGER NOT NULL DEFAULT 0 CHECK (execution_started IN (0, 1)),
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX agent_lab_golden_jobs_by_suite ON agent_lab_golden_jobs(suite_id, created_at_ms DESC);

CREATE TABLE agent_lab_golden_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL REFERENCES agent_lab_golden_suites(suite_id),
    version INTEGER NOT NULL CHECK (version > 0),
    source_revision INTEGER NOT NULL CHECK (source_revision > 0),
    payload_json TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE (suite_id, version),
    UNIQUE (suite_id, source_revision)
);

CREATE TRIGGER agent_lab_golden_snapshots_no_update
BEFORE UPDATE ON agent_lab_golden_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Golden snapshots are immutable');
END;
CREATE TRIGGER agent_lab_golden_snapshots_no_delete
BEFORE DELETE ON agent_lab_golden_snapshots
BEGIN
    SELECT RAISE(ABORT, 'Golden snapshots are immutable');
END;
CREATE TRIGGER agent_lab_golden_commands_no_update
BEFORE UPDATE ON agent_lab_golden_commands
BEGIN
    SELECT RAISE(ABORT, 'Golden command receipts are immutable');
END;
CREATE TRIGGER agent_lab_golden_commands_no_delete
BEFORE DELETE ON agent_lab_golden_commands
BEGIN
    SELECT RAISE(ABORT, 'Golden command receipts are immutable');
END;
CREATE TRIGGER agent_lab_golden_job_inputs_no_update
BEFORE UPDATE OF input_json ON agent_lab_golden_jobs
BEGIN
    SELECT RAISE(ABORT, 'Golden job inputs are immutable');
END;

-- Pi owns call admission, Session binding, and exact-request recovery.
CREATE TABLE agent_lab_golden_model_calls (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    model_json TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'prepared',
    output_text TEXT NOT NULL DEFAULT '',
    receipt_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
