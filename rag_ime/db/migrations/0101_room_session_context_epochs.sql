CREATE TABLE room_v2_session_context_epochs (
    session_id TEXT PRIMARY KEY
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    context_epoch INTEGER NOT NULL CHECK (context_epoch >= 1),
    root_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    epoch_reason TEXT NOT NULL,
    last_transition_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE room_v2_session_context_epoch_transitions (
    transition_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL
        REFERENCES agent_sessions(id) ON DELETE CASCADE,
    source_ref TEXT NOT NULL,
    root_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    from_epoch INTEGER NOT NULL CHECK (from_epoch >= 0),
    to_epoch INTEGER NOT NULL CHECK (to_epoch >= 1),
    epoch_reason TEXT NOT NULL,
    epoch_changed INTEGER NOT NULL CHECK (epoch_changed IN (0, 1)),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    transition_hash TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    UNIQUE(session_id, source_ref)
);

CREATE INDEX idx_room_v2_session_context_epoch_history
ON room_v2_session_context_epoch_transitions(session_id, to_epoch, created_at_ms);
