ALTER TABLE agent_approvals
ADD COLUMN causal_plan_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN causal_plan_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_approvals
ADD COLUMN causal_goal_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN causal_goal_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_approvals
ADD COLUMN causal_turn_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_approvals
ADD COLUMN room_bound INTEGER NOT NULL DEFAULT 0 CHECK (room_bound IN (0, 1));

UPDATE agent_approvals
SET causal_plan_id = COALESCE((
        SELECT CASE
            WHEN state.status IN ('approved', 'executing')
            THEN 'plan:' || agent_approvals.session_id
            ELSE ''
        END
        FROM agent_plan_state_events state
        WHERE state.session_id = agent_approvals.session_id
        ORDER BY state.sequence DESC
        LIMIT 1
    ), ''),
    causal_plan_revision = CASE
        WHEN COALESCE((
            SELECT state.status
            FROM agent_plan_state_events state
            WHERE state.session_id = agent_approvals.session_id
            ORDER BY state.sequence DESC
            LIMIT 1
        ), '') IN ('approved', 'executing')
        THEN
            (SELECT COALESCE(MAX(event.sequence), 0)
             FROM agent_plan_events event
             WHERE event.session_id = agent_approvals.session_id)
            +
            (SELECT COALESCE(MAX(state.sequence), 0)
             FROM agent_plan_state_events state
             WHERE state.session_id = agent_approvals.session_id)
        ELSE 0
    END,
    causal_goal_id = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.goal_id
            ELSE ''
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_approvals.session_id
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), ''),
    causal_goal_revision = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.sequence
            ELSE 0
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_approvals.session_id
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), 0),
    causal_turn_id = COALESCE((
        SELECT runtime.turn_id
        FROM agent_runtime_events runtime
        WHERE runtime.session_id = agent_approvals.session_id
          AND runtime.turn_id <> ''
        ORDER BY runtime.sequence DESC
        LIMIT 1
    ), ''),
    room_bound = CASE
        WHEN preview_json LIKE '%"roomInvocationReceiptId":"_%' THEN 1
        ELSE room_bound
    END
WHERE state IN ('pending', 'approved', 'external_pending');


CREATE INDEX idx_agent_approvals_lifecycle_plan
ON agent_approvals(session_id, causal_plan_id, causal_plan_revision, state)
WHERE room_bound = 0 AND causal_plan_id <> '';

CREATE INDEX idx_agent_approvals_lifecycle_goal
ON agent_approvals(session_id, causal_goal_id, state)
WHERE room_bound = 0 AND causal_goal_id <> '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_plan_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_plan_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_background_jobs
ADD COLUMN causal_goal_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN causal_goal_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_background_jobs
ADD COLUMN causal_turn_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_background_jobs
ADD COLUMN room_bound INTEGER NOT NULL DEFAULT 0 CHECK (room_bound IN (0, 1));

ALTER TABLE agent_background_jobs
ADD COLUMN lifecycle_cancel_request_id TEXT NOT NULL DEFAULT '';

UPDATE agent_background_jobs
SET causal_plan_id = COALESCE((
        SELECT approval.causal_plan_id
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), ''),
    causal_plan_revision = COALESCE((
        SELECT approval.causal_plan_revision
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), 0),
    causal_goal_id = COALESCE((
        SELECT approval.causal_goal_id
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), ''),
    causal_goal_revision = COALESCE((
        SELECT approval.causal_goal_revision
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), 0),
    causal_turn_id = COALESCE((
        SELECT approval.causal_turn_id
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), ''),
    room_bound = COALESCE((
        SELECT approval.room_bound
        FROM agent_approvals approval
        WHERE approval.approval_id = agent_background_jobs.approval_id
    ), room_bound)
WHERE approval_id <> '';

CREATE INDEX idx_agent_background_jobs_lifecycle_cancel_request
ON agent_background_jobs(lifecycle_cancel_request_id)
WHERE lifecycle_cancel_request_id <> '';

CREATE INDEX idx_agent_background_jobs_lifecycle_plan
ON agent_background_jobs(session_id, causal_plan_id, causal_plan_revision, status)
WHERE room_bound = 0 AND causal_plan_id <> '';

CREATE INDEX idx_agent_background_jobs_lifecycle_goal
ON agent_background_jobs(session_id, causal_goal_id, status)
WHERE room_bound = 0 AND causal_goal_id <> '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_plan_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_plan_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_goal_id TEXT NOT NULL DEFAULT '';

ALTER TABLE agent_subagent_batches
ADD COLUMN causal_goal_revision INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_subagent_batches
ADD COLUMN room_bound INTEGER NOT NULL DEFAULT 0 CHECK (room_bound IN (0, 1));

ALTER TABLE agent_subagent_batches
ADD COLUMN lifecycle_cancel_request_id TEXT NOT NULL DEFAULT '';

UPDATE agent_subagent_batches
SET causal_plan_id = COALESCE((
        SELECT CASE
            WHEN state.status IN ('approved', 'executing')
            THEN 'plan:' || agent_subagent_batches.parent_session_id
            ELSE ''
        END
        FROM agent_plan_state_events state
        WHERE state.session_id = agent_subagent_batches.parent_session_id
        ORDER BY state.sequence DESC
        LIMIT 1
    ), ''),
    causal_plan_revision = CASE
        WHEN COALESCE((
            SELECT state.status
            FROM agent_plan_state_events state
            WHERE state.session_id = agent_subagent_batches.parent_session_id
            ORDER BY state.sequence DESC
            LIMIT 1
        ), '') IN ('approved', 'executing')
        THEN
            (SELECT COALESCE(MAX(event.sequence), 0)
             FROM agent_plan_events event
             WHERE event.session_id = agent_subagent_batches.parent_session_id)
            +
            (SELECT COALESCE(MAX(state.sequence), 0)
             FROM agent_plan_state_events state
             WHERE state.session_id = agent_subagent_batches.parent_session_id)
        ELSE 0
    END,
    causal_goal_id = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.goal_id
            ELSE ''
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_subagent_batches.parent_session_id
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), ''),
    causal_goal_revision = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.sequence
            ELSE 0
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_subagent_batches.parent_session_id
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), 0);

CREATE INDEX idx_agent_subagent_batches_lifecycle_plan
ON agent_subagent_batches(
    parent_session_id, causal_plan_id, causal_plan_revision, state
)
WHERE room_bound = 0 AND causal_plan_id <> '';

CREATE INDEX idx_agent_subagent_batches_lifecycle_goal
ON agent_subagent_batches(parent_session_id, causal_goal_id, state)
WHERE room_bound = 0 AND causal_goal_id <> '';

CREATE INDEX idx_agent_subagent_batches_lifecycle_cancel_request
ON agent_subagent_batches(lifecycle_cancel_request_id)
WHERE lifecycle_cancel_request_id <> '';

CREATE TABLE agent_lifecycle_cancellation_audits (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('plan', 'goal')),
    scope_id TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    transition_revision INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('cancel', 'pause')),
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed', 'partial', 'unknown')),
    source_turn_id TEXT NOT NULL DEFAULT '',
    runtime_status TEXT NOT NULL CHECK (runtime_status IN ('pending', 'succeeded', 'excluded', 'partial', 'unknown')),
    runtime_receipt_json TEXT NOT NULL DEFAULT '{}',
    approval_status TEXT NOT NULL CHECK (approval_status IN ('pending', 'succeeded', 'excluded', 'partial', 'unknown')),
    approval_receipt_json TEXT NOT NULL DEFAULT '{}',
    job_status TEXT NOT NULL CHECK (job_status IN ('pending', 'succeeded', 'excluded', 'partial', 'unknown')),
    job_receipt_json TEXT NOT NULL DEFAULT '{}',
    delegation_status TEXT NOT NULL CHECK (delegation_status IN ('pending', 'succeeded', 'excluded', 'partial', 'unknown')),
    delegation_receipt_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE UNIQUE INDEX idx_agent_lifecycle_cancellation_transition
ON agent_lifecycle_cancellation_audits(
    session_id, scope_kind, scope_id, transition_revision, action
);

CREATE INDEX idx_agent_lifecycle_cancellation_session
ON agent_lifecycle_cancellation_audits(session_id, created_at_ms DESC, request_id);
