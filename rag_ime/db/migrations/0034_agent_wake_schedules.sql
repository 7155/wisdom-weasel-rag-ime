CREATE TABLE IF NOT EXISTS agent_wake_schedules (
    schedule_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    instruction TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('session', 'role')),
    target_session_id TEXT NOT NULL DEFAULT '',
    target_role_id TEXT NOT NULL DEFAULT '',
    target_role_version TEXT NOT NULL DEFAULT '',
    created_by_session_id TEXT NOT NULL DEFAULT '',
    planning_task_id TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    recurrence_kind TEXT NOT NULL DEFAULT 'once'
        CHECK (recurrence_kind IN ('once', 'daily', 'weekly')),
    recurrence_interval INTEGER NOT NULL DEFAULT 1,
    max_runs INTEGER NOT NULL DEFAULT 1,
    run_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'paused', 'running', 'completed', 'failed', 'cancelled')),
    next_wake_at_ms INTEGER,
    last_wake_at_ms INTEGER,
    last_run_id TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    lease_token TEXT NOT NULL DEFAULT '',
    lease_expires_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK (
        (target_type = 'session' AND target_session_id <> '' AND target_role_id = '')
        OR
        (target_type = 'role' AND target_role_id <> '' AND target_session_id = '')
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_wake_schedules_due
ON agent_wake_schedules(status, next_wake_at_ms, lease_expires_at_ms);

CREATE INDEX IF NOT EXISTS idx_agent_wake_schedules_creator
ON agent_wake_schedules(created_by_session_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS agent_wake_runs (
    run_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES agent_wake_schedules(schedule_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('claimed', 'accepted', 'completed', 'failed', 'deferred')),
    due_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL,
    accepted_at_ms INTEGER,
    finished_at_ms INTEGER,
    session_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_wake_runs_schedule
ON agent_wake_runs(schedule_id, started_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_agent_wake_runs_turn
ON agent_wake_runs(session_id, turn_id, state);
