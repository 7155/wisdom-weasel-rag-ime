CREATE TABLE work_documents (
    document_id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('session_plan', 'session_goal', 'room_work_item')
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

CREATE INDEX idx_work_documents_state_updated
ON work_documents(state, updated_at_ms DESC);

CREATE TABLE work_document_terminal_receipts (
    receipt_id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL,
    authority_id TEXT NOT NULL,
    authority_revision INTEGER NOT NULL CHECK (authority_revision >= 0),
    terminal_state TEXT NOT NULL CHECK (
        terminal_state IN ('completed', 'cancelled', 'failed', 'cleared')
    ),
    receipt_sha256 TEXT NOT NULL CHECK (length(receipt_sha256) = 64),
    created_at_ms INTEGER NOT NULL,
    UNIQUE(authority_kind, authority_id, authority_revision)
);

CREATE TABLE work_document_outbox (
    outbox_id TEXT PRIMARY KEY,
    operation_key TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES work_documents(document_id) ON DELETE CASCADE,
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

CREATE INDEX idx_work_document_outbox_pending
ON work_document_outbox(state, updated_at_ms ASC)
WHERE state IN ('pending', 'processing');

CREATE TABLE work_document_observer_failures (
    authority_key TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK (
        authority_kind IN ('session_plan', 'session_goal', 'room_work_item')
    ),
    authority_id TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES work_documents(document_id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK (state IN ('pending', 'failed', 'applied')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    applied_at_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_work_document_observer_failures_pending
ON work_document_observer_failures(state, updated_at_ms ASC)
WHERE state IN ('pending', 'failed');

CREATE TABLE work_document_operation_receipts (
    receipt_id TEXT PRIMARY KEY,
    operation_key TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('register', 'archive', 'repair', 'reopen', 'erase')),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'applied', 'failed')),
    idempotent INTEGER NOT NULL DEFAULT 0 CHECK (idempotent IN (0, 1)),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL
);
