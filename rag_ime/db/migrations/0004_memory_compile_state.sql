CREATE TABLE IF NOT EXISTS memory_compile_state (
    project TEXT PRIMARY KEY,
    last_compiled_event_id INTEGER NOT NULL DEFAULT 0,
    last_run_ms INTEGER NOT NULL DEFAULT 0,
    pending_event_count INTEGER NOT NULL DEFAULT 0,
    last_bundle_hash TEXT NOT NULL DEFAULT ''
);
