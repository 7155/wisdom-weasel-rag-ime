UPDATE agent_todo_events AS todo
SET phases_json = (
    SELECT json_array(
        json_object(
            'name', json_extract(todo.phases_json, '$[0].name'),
            'tasks', json(
                COALESCE(
                    (
                        SELECT json_group_array(json(ordered.task_json))
                        FROM (
                            SELECT json_object(
                                'content', json_extract(task.value, '$.content'),
                                'status', CASE receipt.terminal_state
                                    WHEN 'completed' THEN 'completed'
                                    WHEN 'cancelled' THEN 'abandoned'
                                    ELSE json_extract(task.value, '$.status')
                                END
                            ) AS task_json
                            FROM json_each(todo.phases_json, '$[0].tasks') AS task
                            ORDER BY CAST(task.key AS INTEGER)
                        ) AS ordered
                    ),
                    '[]'
                )
            )
        )
    )
    FROM work_document_terminal_receipts AS receipt
    WHERE receipt.authority_kind = 'session_plan'
      AND receipt.authority_id = todo.session_id
      AND receipt.terminal_state IN ('completed', 'cancelled')
    ORDER BY receipt.created_at_ms DESC, receipt.receipt_id DESC
    LIMIT 1
)
WHERE todo.operation = 'migrate'
  AND EXISTS (
      SELECT 1
      FROM work_document_terminal_receipts AS receipt
      WHERE receipt.authority_kind = 'session_plan'
        AND receipt.authority_id = todo.session_id
        AND receipt.terminal_state IN ('completed', 'cancelled')
  );

UPDATE agent_subagent_runs
SET
    todo_task = todo_phase,
    todo_phase = COALESCE(
        (
            SELECT json_extract(todo.phases_json, '$[0].name')
            FROM agent_subagent_batches AS batch
            JOIN agent_todo_events AS todo
              ON todo.session_id = batch.parent_session_id
            WHERE batch.id = agent_subagent_runs.batch_id
            ORDER BY todo.revision DESC
            LIMIT 1
        ),
        ''
    );

UPDATE agent_approvals
SET
    causal_todo_id = CASE
        WHEN causal_todo_id <> '' THEN 'todo:' || session_id
        ELSE ''
    END,
    causal_todo_revision = CASE
        WHEN causal_todo_id <> '' THEN COALESCE(
            (
                SELECT MAX(todo.revision)
                FROM agent_todo_events AS todo
                WHERE todo.session_id = agent_approvals.session_id
            ),
            0
        )
        ELSE 0
    END;

UPDATE agent_background_jobs
SET
    causal_todo_id = CASE
        WHEN causal_todo_id <> '' THEN 'todo:' || session_id
        ELSE ''
    END,
    causal_todo_revision = CASE
        WHEN causal_todo_id <> '' THEN COALESCE(
            (
                SELECT MAX(todo.revision)
                FROM agent_todo_events AS todo
                WHERE todo.session_id = agent_background_jobs.session_id
            ),
            0
        )
        ELSE 0
    END;

UPDATE agent_subagent_batches
SET
    causal_todo_id = CASE
        WHEN causal_todo_id <> '' THEN 'todo:' || parent_session_id
        ELSE ''
    END,
    causal_todo_revision = CASE
        WHEN causal_todo_id <> '' THEN COALESCE(
            (
                SELECT MAX(todo.revision)
                FROM agent_todo_events AS todo
                WHERE todo.session_id = agent_subagent_batches.parent_session_id
            ),
            0
        )
        ELSE 0
    END;

CREATE TABLE agent_lifecycle_cancellation_audits_todo_cutover (
    request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL CHECK (scope_kind = 'goal'),
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

INSERT INTO agent_lifecycle_cancellation_audits_todo_cutover
SELECT *
FROM agent_lifecycle_cancellation_audits
WHERE scope_kind = 'goal';

DROP TABLE agent_lifecycle_cancellation_audits;
ALTER TABLE agent_lifecycle_cancellation_audits_todo_cutover
RENAME TO agent_lifecycle_cancellation_audits;

CREATE UNIQUE INDEX idx_agent_lifecycle_cancellation_transition
ON agent_lifecycle_cancellation_audits(
    session_id, scope_kind, scope_id, transition_revision, action
);

CREATE INDEX idx_agent_lifecycle_cancellation_session
ON agent_lifecycle_cancellation_audits(
    session_id, created_at_ms DESC, request_id
);

CREATE TABLE work_documents_todo_cutover (
    document_id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('session_todo', 'session_goal', 'room_work_item')
    ),
    authority_id TEXT NOT NULL,
    authority_revision INTEGER NOT NULL CHECK (authority_revision >= 0),
    authority_key TEXT NOT NULL UNIQUE,
    document_revision INTEGER NOT NULL DEFAULT 1 CHECK (document_revision >= 1),
    title TEXT NOT NULL DEFAULT '',
    workspace_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    active_relative_path TEXT NOT NULL,
    archive_relative_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    state TEXT NOT NULL CHECK (
        state IN ('active', 'archive_pending', 'archived', 'reopen_pending', 'error')
    ),
    terminal_receipt_id TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

INSERT INTO work_documents_todo_cutover
SELECT
    document_id,
    CASE
        WHEN authority_kind = 'session_plan' THEN 'session_todo'
        ELSE authority_kind
    END,
    authority_id,
    CASE
        WHEN authority_kind = 'session_plan' THEN COALESCE(
            (
                SELECT MAX(todo.revision)
                FROM agent_todo_events AS todo
                WHERE todo.session_id = work_documents.authority_id
            ),
            0
        )
        ELSE authority_revision
    END,
    CASE
        WHEN authority_kind = 'session_plan'
        THEN 'session_todo:' || authority_id
        ELSE authority_key
    END,
    document_revision,
    title,
    workspace_root,
    relative_path,
    active_relative_path,
    archive_relative_path,
    content_sha256,
    state,
    CASE
        WHEN authority_kind = 'session_plan' THEN ''
        ELSE terminal_receipt_id
    END,
    error,
    created_at_ms,
    updated_at_ms
FROM work_documents;

CREATE TABLE work_document_outbox_todo_cutover (
    outbox_id TEXT PRIMARY KEY,
    operation_key TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL
        REFERENCES work_documents_todo_cutover(document_id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation IN ('activate', 'archive', 'reopen')),
    source_relative_path TEXT NOT NULL,
    target_relative_path TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'processing', 'applied', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    applied_at_ms INTEGER NOT NULL DEFAULT 0
);

INSERT INTO work_document_outbox_todo_cutover
SELECT *
FROM work_document_outbox;

CREATE TABLE work_document_observer_failures_todo_cutover (
    authority_key TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('session_todo', 'session_goal', 'room_work_item')
    ),
    authority_id TEXT NOT NULL,
    document_id TEXT NOT NULL
        REFERENCES work_documents_todo_cutover(document_id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('pending', 'failed', 'applied')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    applied_at_ms INTEGER NOT NULL DEFAULT 0
);

INSERT INTO work_document_observer_failures_todo_cutover
SELECT
    CASE
        WHEN authority_kind = 'session_plan'
        THEN 'session_todo:' || authority_id
        ELSE authority_key
    END,
    CASE
        WHEN authority_kind = 'session_plan' THEN 'session_todo'
        ELSE authority_kind
    END,
    authority_id,
    document_id,
    state,
    attempt_count,
    error,
    created_at_ms,
    updated_at_ms,
    applied_at_ms
FROM work_document_observer_failures;

DROP TABLE work_document_observer_failures;
DROP TABLE work_document_outbox;
DROP TABLE work_documents;

ALTER TABLE work_documents_todo_cutover RENAME TO work_documents;
ALTER TABLE work_document_outbox_todo_cutover RENAME TO work_document_outbox;
ALTER TABLE work_document_observer_failures_todo_cutover
RENAME TO work_document_observer_failures;

CREATE INDEX idx_work_documents_state_updated
ON work_documents(state, updated_at_ms DESC);

CREATE INDEX idx_work_document_outbox_pending
ON work_document_outbox(state, updated_at_ms ASC)
WHERE state IN ('pending', 'processing');

CREATE INDEX idx_work_document_observer_failures_pending
ON work_document_observer_failures(state, updated_at_ms ASC)
WHERE state IN ('pending', 'failed');

DELETE FROM work_document_terminal_receipts
WHERE authority_kind = 'session_plan';
