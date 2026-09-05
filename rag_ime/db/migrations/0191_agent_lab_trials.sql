-- App-owned lifecycle only. Actual Pi calls and immutable Eval receipts retain
-- their existing owners. No runnable command is inferred from a public read.
CREATE TABLE agent_lab_trials (
    job_id TEXT PRIMARY KEY,
    client_request_id TEXT NOT NULL UNIQUE,
    scene_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    public_spec_json TEXT NOT NULL,
    private_input_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted')),
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
    progress TEXT NOT NULL DEFAULT '',
    sessions_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX agent_lab_trials_by_created ON agent_lab_trials(created_at_ms DESC, job_id);
CREATE TRIGGER agent_lab_trial_inputs_immutable
BEFORE UPDATE OF job_id, client_request_id, scene_id, request_sha256, public_spec_json, private_input_json, created_at_ms ON agent_lab_trials
BEGIN
    SELECT RAISE(ABORT, 'Lab trial frozen inputs are immutable');
END;
CREATE TRIGGER agent_lab_trial_terminal_immutable
BEFORE UPDATE ON agent_lab_trials
WHEN OLD.state IN ('completed', 'failed', 'cancelled', 'interrupted')
BEGIN
    SELECT RAISE(ABORT, 'Lab trial terminal state is immutable');
END;
CREATE TRIGGER agent_lab_trial_no_delete
BEFORE DELETE ON agent_lab_trials
BEGIN
    SELECT RAISE(ABORT, 'Lab trial execution identity is retained');
END;
