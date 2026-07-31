UPDATE agent_approvals
SET causal_plan_id = COALESCE((
        SELECT CASE
            WHEN state.status IN ('approved', 'executing')
            THEN 'plan:' || agent_approvals.session_id
            ELSE ''
        END
        FROM agent_plan_state_events state
        WHERE state.session_id = agent_approvals.session_id
          AND state.created_at_ms <= agent_approvals.requested_at_ms
        ORDER BY state.sequence DESC
        LIMIT 1
    ), ''),
    causal_plan_revision = CASE
        WHEN COALESCE((
            SELECT state.status
            FROM agent_plan_state_events state
            WHERE state.session_id = agent_approvals.session_id
              AND state.created_at_ms <= agent_approvals.requested_at_ms
            ORDER BY state.sequence DESC
            LIMIT 1
        ), '') IN ('approved', 'executing')
        THEN
            (SELECT COALESCE(MAX(event.sequence), 0)
             FROM agent_plan_events event
             WHERE event.session_id = agent_approvals.session_id
               AND event.created_at_ms <= agent_approvals.requested_at_ms)
            +
            (SELECT COALESCE(MAX(state.sequence), 0)
             FROM agent_plan_state_events state
             WHERE state.session_id = agent_approvals.session_id
               AND state.created_at_ms <= agent_approvals.requested_at_ms)
        ELSE 0
    END,
    causal_goal_id = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.goal_id
            ELSE ''
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_approvals.session_id
          AND goal.created_at_ms <= agent_approvals.requested_at_ms
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
          AND goal.created_at_ms <= agent_approvals.requested_at_ms
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), 0)
WHERE requested_at_ms <= (
    SELECT applied_at_ms
    FROM schema_migrations
    WHERE version = 115
);

UPDATE agent_background_jobs
SET causal_plan_id = COALESCE((
        SELECT CASE
            WHEN state.status IN ('approved', 'executing')
            THEN 'plan:' || agent_background_jobs.session_id
            ELSE ''
        END
        FROM agent_plan_state_events state
        WHERE state.session_id = agent_background_jobs.session_id
          AND state.created_at_ms <= agent_background_jobs.created_at_ms
        ORDER BY state.sequence DESC
        LIMIT 1
    ), ''),
    causal_plan_revision = CASE
        WHEN COALESCE((
            SELECT state.status
            FROM agent_plan_state_events state
            WHERE state.session_id = agent_background_jobs.session_id
              AND state.created_at_ms <= agent_background_jobs.created_at_ms
            ORDER BY state.sequence DESC
            LIMIT 1
        ), '') IN ('approved', 'executing')
        THEN
            (SELECT COALESCE(MAX(event.sequence), 0)
             FROM agent_plan_events event
             WHERE event.session_id = agent_background_jobs.session_id
               AND event.created_at_ms <= agent_background_jobs.created_at_ms)
            +
            (SELECT COALESCE(MAX(state.sequence), 0)
             FROM agent_plan_state_events state
             WHERE state.session_id = agent_background_jobs.session_id
               AND state.created_at_ms <= agent_background_jobs.created_at_ms)
        ELSE 0
    END,
    causal_goal_id = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.goal_id
            ELSE ''
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_background_jobs.session_id
          AND goal.created_at_ms <= agent_background_jobs.created_at_ms
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), ''),
    causal_goal_revision = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.sequence
            ELSE 0
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_background_jobs.session_id
          AND goal.created_at_ms <= agent_background_jobs.created_at_ms
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), 0)
WHERE created_at_ms <= (
    SELECT applied_at_ms
    FROM schema_migrations
    WHERE version = 115
);

UPDATE agent_subagent_batches
SET causal_plan_id = COALESCE((
        SELECT CASE
            WHEN state.status IN ('approved', 'executing')
            THEN 'plan:' || agent_subagent_batches.parent_session_id
            ELSE ''
        END
        FROM agent_plan_state_events state
        WHERE state.session_id = agent_subagent_batches.parent_session_id
          AND state.created_at_ms <= agent_subagent_batches.created_at_ms
        ORDER BY state.sequence DESC
        LIMIT 1
    ), ''),
    causal_plan_revision = CASE
        WHEN COALESCE((
            SELECT state.status
            FROM agent_plan_state_events state
            WHERE state.session_id = agent_subagent_batches.parent_session_id
              AND state.created_at_ms <= agent_subagent_batches.created_at_ms
            ORDER BY state.sequence DESC
            LIMIT 1
        ), '') IN ('approved', 'executing')
        THEN
            (SELECT COALESCE(MAX(event.sequence), 0)
             FROM agent_plan_events event
             WHERE event.session_id = agent_subagent_batches.parent_session_id
               AND event.created_at_ms <= agent_subagent_batches.created_at_ms)
            +
            (SELECT COALESCE(MAX(state.sequence), 0)
             FROM agent_plan_state_events state
             WHERE state.session_id = agent_subagent_batches.parent_session_id
               AND state.created_at_ms <= agent_subagent_batches.created_at_ms)
        ELSE 0
    END,
    causal_goal_id = COALESCE((
        SELECT CASE
            WHEN goal.status IN ('active', 'paused') THEN goal.goal_id
            ELSE ''
        END
        FROM agent_thread_goal_events goal
        WHERE goal.session_id = agent_subagent_batches.parent_session_id
          AND goal.created_at_ms <= agent_subagent_batches.created_at_ms
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
          AND goal.created_at_ms <= agent_subagent_batches.created_at_ms
        ORDER BY goal.sequence DESC
        LIMIT 1
    ), 0)
WHERE created_at_ms <= (
    SELECT applied_at_ms
    FROM schema_migrations
    WHERE version = 115
);
