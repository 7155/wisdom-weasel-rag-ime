ALTER TABLE agent_subagent_events
RENAME TO agent_subagent_events_before_fleet_queue;

ALTER TABLE agent_subagent_controls
RENAME TO agent_subagent_controls_before_fleet_queue;

ALTER TABLE agent_subagent_inbox
RENAME TO agent_subagent_inbox_before_fleet_queue;

ALTER TABLE agent_subagent_runs
RENAME TO agent_subagent_runs_before_fleet_queue;

CREATE TABLE agent_subagent_runs (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES agent_subagent_batches(id) ON DELETE CASCADE,
    child_session_id TEXT NOT NULL UNIQUE,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 63),
    task_text TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'queued', 'running', 'completed', 'failed', 'aborted', 'timed_out'
    )),
    max_turns INTEGER NOT NULL CHECK (max_turns BETWEEN 0 AND 32),
    max_tool_calls INTEGER NOT NULL CHECK (max_tool_calls BETWEEN 0 AND 64),
    max_total_tokens INTEGER NOT NULL CHECK (max_total_tokens BETWEEN 256 AND 262144),
    max_duration_ms INTEGER NOT NULL CHECK (max_duration_ms BETWEEN 1000 AND 900000),
    max_output_chars INTEGER NOT NULL CHECK (max_output_chars BETWEEN 256 AND 100000),
    turn_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    started_at_ms INTEGER,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    todo_task TEXT NOT NULL DEFAULT '',
    todo_phase TEXT NOT NULL DEFAULT '',
    expected_output TEXT NOT NULL DEFAULT '',
    acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
    output_schema_json TEXT NOT NULL DEFAULT '{}',
    result_context_scheduled_at_ms INTEGER,
    UNIQUE(batch_id, ordinal)
);

INSERT INTO agent_subagent_runs(
    id, batch_id, child_session_id, template_id, template_version, ordinal,
    task_text, state, max_turns, max_tool_calls, max_total_tokens,
    max_duration_ms, max_output_chars, turn_count, tool_count, total_tokens,
    result_json, error, created_at_ms, started_at_ms, updated_at_ms,
    completed_at_ms, todo_task, todo_phase, expected_output,
    acceptance_criteria_json, output_schema_json, result_context_scheduled_at_ms
)
SELECT
    id, batch_id, child_session_id, template_id, template_version, ordinal,
    task_text, state, max_turns, max_tool_calls, max_total_tokens,
    max_duration_ms, max_output_chars, turn_count, tool_count, total_tokens,
    result_json, error, created_at_ms, started_at_ms, updated_at_ms,
    completed_at_ms, todo_task, todo_phase, expected_output,
    acceptance_criteria_json, output_schema_json, result_context_scheduled_at_ms
FROM agent_subagent_runs_before_fleet_queue;

CREATE TABLE agent_subagent_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'queued', 'started', 'progress', 'budget_exceeded',
        'completed', 'failed', 'aborted', 'timed_out'
    )),
    created_at_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(run_id, sequence)
);

INSERT INTO agent_subagent_events(
    event_id, run_id, sequence, event_type, created_at_ms, payload_json
)
SELECT event_id, run_id, sequence, event_type, created_at_ms, payload_json
FROM agent_subagent_events_before_fleet_queue;

CREATE TABLE agent_subagent_controls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    parent_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    client_action_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN (
        'steer', 'retry', 'resume', 'abort', 'reply'
    )),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL CHECK (state IN ('accepted', 'completed', 'failed')),
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    UNIQUE(run_id, client_action_id)
);

INSERT INTO agent_subagent_controls
SELECT * FROM agent_subagent_controls_before_fleet_queue;

CREATE TABLE agent_subagent_inbox (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_subagent_runs(id) ON DELETE CASCADE,
    parent_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    child_session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('need_decision', 'interview', 'progress')),
    title TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('pending', 'replied', 'observed')),
    response_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    UNIQUE(run_id, request_id)
);

INSERT INTO agent_subagent_inbox
SELECT * FROM agent_subagent_inbox_before_fleet_queue;

DROP TABLE agent_subagent_events_before_fleet_queue;
DROP TABLE agent_subagent_controls_before_fleet_queue;
DROP TABLE agent_subagent_inbox_before_fleet_queue;
DROP TABLE agent_subagent_runs_before_fleet_queue;

CREATE INDEX idx_agent_subagent_runs_state_recent
ON agent_subagent_runs(state, created_at_ms DESC);

CREATE INDEX idx_agent_subagent_runs_plan_item_recent
ON agent_subagent_runs(todo_task, created_at_ms DESC)
WHERE todo_task <> '';

CREATE INDEX idx_agent_subagent_events_run_sequence
ON agent_subagent_events(run_id, sequence DESC);

CREATE INDEX idx_agent_subagent_controls_run_recent
ON agent_subagent_controls(run_id, created_at_ms DESC);

CREATE INDEX idx_agent_subagent_inbox_parent_status_recent
ON agent_subagent_inbox(parent_session_id, status, created_at_ms DESC);

ALTER TABLE agent_subagent_batches
ADD COLUMN request_key TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN request_sha256 TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX idx_agent_subagent_batches_parent_request
ON agent_subagent_batches(parent_session_id, request_key)
WHERE request_key <> '';

