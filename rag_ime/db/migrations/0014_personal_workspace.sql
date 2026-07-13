CREATE TABLE IF NOT EXISTS planning_daily (
    plan_id TEXT PRIMARY KEY,
    plan_date TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '',
    intention TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    reflection TEXT NOT NULL DEFAULT '',
    assistant_summary TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(plan_date, project)
);

CREATE INDEX IF NOT EXISTS idx_planning_daily_date_project
ON planning_daily(plan_date DESC, project);

CREATE TABLE IF NOT EXISTS planning_goals (
    goal_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    horizon TEXT NOT NULL DEFAULT 'long_term',
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 1,
    target_date TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_planning_goals_status_priority
ON planning_goals(status, priority DESC, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS planning_tasks (
    task_id TEXT PRIMARY KEY,
    plan_date TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    priority INTEGER NOT NULL DEFAULT 1,
    due_at_ms INTEGER,
    project TEXT NOT NULL DEFAULT '',
    goal_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_planning_tasks_date_status
ON planning_tasks(plan_date DESC, status, priority DESC, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_planning_tasks_goal
ON planning_tasks(goal_id, status);

CREATE TABLE IF NOT EXISTS planning_task_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT NOT NULL DEFAULT '',
    next_status TEXT NOT NULL DEFAULT '',
    source_event_id INTEGER,
    source_text_hash TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_planning_task_events_task
ON planning_task_events(task_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS planning_completion_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    source_event_id INTEGER,
    source_text_hash TEXT NOT NULL DEFAULT '',
    candidate_task_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_planning_completion_suggestions_status
ON planning_completion_suggestions(status, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS memory_supersessions (
    supersession_id TEXT PRIMARY KEY,
    old_memory_id TEXT NOT NULL,
    new_memory_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    source_event_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    created_at_ms INTEGER NOT NULL,
    rolled_back_at_ms INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memory_supersessions_old
ON memory_supersessions(old_memory_id, status, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_memory_supersessions_new
ON memory_supersessions(new_memory_id, status, created_at_ms DESC);

ALTER TABLE memory_books ADD COLUMN archived_at_ms INTEGER;
ALTER TABLE memory_books ADD COLUMN last_active_at_ms INTEGER;
ALTER TABLE memory_books ADD COLUMN archive_reason TEXT NOT NULL DEFAULT '';
