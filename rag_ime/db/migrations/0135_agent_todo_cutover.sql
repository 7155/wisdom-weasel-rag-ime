CREATE TABLE agent_todo_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    operation TEXT NOT NULL CHECK (
        operation IN ('init', 'start', 'done', 'drop', 'append', 'rm', 'migrate')
    ),
    phases_json TEXT NOT NULL CHECK (json_valid(phases_json)),
    actor TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, revision)
);

CREATE INDEX idx_agent_todo_events_session_revision
ON agent_todo_events(session_id, revision DESC);

WITH latest_items AS (
    SELECT
        session_id,
        item_id,
        title,
        status,
        position,
        is_deleted,
        created_at_ms,
        MIN(sequence) OVER (PARTITION BY session_id, item_id) AS first_sequence,
        ROW_NUMBER() OVER (
            PARTITION BY session_id, item_id ORDER BY sequence DESC
        ) AS row_number
    FROM agent_plan_events
),
active_items AS (
    SELECT
        session_id,
        title,
        status,
        position,
        first_sequence,
        created_at_ms,
        ROW_NUMBER() OVER (
            PARTITION BY session_id, title
            ORDER BY
                CASE WHEN position > 0 THEN position ELSE 1000000 + first_sequence END,
                first_sequence
        ) AS duplicate_number
    FROM latest_items
    WHERE row_number = 1 AND is_deleted = 0
),
latest_states AS (
    SELECT session_id, title, actor, created_at_ms
    FROM (
        SELECT
            session_id,
            title,
            actor,
            created_at_ms,
            ROW_NUMBER() OVER (
                PARTITION BY session_id ORDER BY sequence DESC
            ) AS row_number
        FROM agent_plan_state_events
    )
    WHERE row_number = 1
),
sessions_with_items AS (
    SELECT
        items.session_id,
        COALESCE(NULLIF(states.title, ''), '任务') AS phase_name,
        COALESCE(NULLIF(states.actor, ''), 'migration') AS actor,
        MAX(MAX(items.created_at_ms), COALESCE(states.created_at_ms, 0)) AS updated_at_ms
    FROM active_items AS items
    LEFT JOIN latest_states AS states ON states.session_id = items.session_id
    GROUP BY items.session_id
)
INSERT INTO agent_todo_events(
    event_id,
    session_id,
    revision,
    operation,
    phases_json,
    actor,
    created_at_ms
)
SELECT
    'todo-migration:' || sessions.session_id,
    sessions.session_id,
    1,
    'migrate',
    json_array(
        json_object(
            'name', substr(sessions.phase_name, 1, 80),
            'tasks', json(
                COALESCE(
                    (
                        SELECT json_group_array(json(ordered.task_json))
                        FROM (
                            SELECT json_object(
                                'content',
                                CASE
                                    WHEN items.duplicate_number = 1 THEN items.title
                                    ELSE items.title || ' (' || items.duplicate_number || ')'
                                END,
                                'status', items.status
                            ) AS task_json
                            FROM active_items AS items
                            WHERE items.session_id = sessions.session_id
                            ORDER BY
                                CASE
                                    WHEN items.position > 0 THEN items.position
                                    ELSE 1000000 + items.first_sequence
                                END,
                                items.first_sequence
                        ) AS ordered
                    ),
                    '[]'
                )
            )
        )
    ),
    sessions.actor,
    sessions.updated_at_ms
FROM sessions_with_items AS sessions;

ALTER TABLE agent_subagent_runs RENAME COLUMN plan_item_id TO todo_task;
ALTER TABLE agent_subagent_runs RENAME COLUMN plan_item_title TO todo_phase;
ALTER TABLE agent_subagent_batches RENAME COLUMN causal_plan_id TO causal_todo_id;
ALTER TABLE agent_subagent_batches RENAME COLUMN causal_plan_revision TO causal_todo_revision;

ALTER TABLE agent_approvals RENAME COLUMN causal_plan_id TO causal_todo_id;
ALTER TABLE agent_approvals RENAME COLUMN causal_plan_revision TO causal_todo_revision;
ALTER TABLE agent_background_jobs RENAME COLUMN causal_plan_id TO causal_todo_id;
ALTER TABLE agent_background_jobs RENAME COLUMN causal_plan_revision TO causal_todo_revision;

DROP INDEX idx_agent_approvals_lifecycle_plan;
CREATE INDEX idx_agent_approvals_todo_context
ON agent_approvals(session_id, causal_todo_id, causal_todo_revision, state)
WHERE causal_todo_id <> '';

DROP INDEX idx_agent_background_jobs_lifecycle_plan;
CREATE INDEX idx_agent_background_jobs_todo_context
ON agent_background_jobs(session_id, causal_todo_id, causal_todo_revision, status)
WHERE causal_todo_id <> '';

DROP INDEX idx_agent_subagent_batches_lifecycle_plan;
CREATE INDEX idx_agent_subagent_batches_todo_context
ON agent_subagent_batches(
    parent_session_id, causal_todo_id, causal_todo_revision, state
)
WHERE causal_todo_id <> '';

DROP TABLE agent_plan_events;
DROP TABLE agent_plan_state_events;
