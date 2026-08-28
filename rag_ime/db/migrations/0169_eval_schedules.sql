CREATE TABLE eval_schedules (
    schedule_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL,
    suite_revision TEXT NOT NULL DEFAULT '',
    recurrence_kind TEXT NOT NULL CHECK (recurrence_kind IN ('daily', 'weekly')),
    recurrence_interval INTEGER NOT NULL CHECK (recurrence_interval BETWEEN 1 AND 30),
    max_runs INTEGER NOT NULL CHECK (max_runs BETWEEN 1 AND 100),
    run_count INTEGER NOT NULL DEFAULT 0 CHECK (run_count >= 0),
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'running', 'completed', 'failed')),
    initial_due_at_ms INTEGER NOT NULL CHECK (initial_due_at_ms >= 0),
    next_due_at_ms INTEGER NOT NULL CHECK (next_due_at_ms >= 0),
    last_due_at_ms INTEGER,
    last_run_id TEXT NOT NULL DEFAULT '',
    last_error_code TEXT NOT NULL DEFAULT '',
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
);

CREATE INDEX idx_eval_schedules_due
    ON eval_schedules(status, next_due_at_ms, lease_expires_at_ms);

CREATE TABLE eval_schedule_runs (
    run_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES eval_schedules(schedule_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    state TEXT NOT NULL CHECK (state IN ('claimed', 'succeeded', 'failed')),
    due_at_ms INTEGER NOT NULL CHECK (due_at_ms >= 0),
    claimed_at_ms INTEGER NOT NULL CHECK (claimed_at_ms >= 0),
    finished_at_ms INTEGER,
    lease_token TEXT NOT NULL,
    eval_run_id TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_eval_schedule_runs_schedule
    ON eval_schedule_runs(schedule_id, claimed_at_ms DESC);
