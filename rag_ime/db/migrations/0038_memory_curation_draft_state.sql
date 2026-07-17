ALTER TABLE memory_compile_state
ADD COLUMN last_drafted_event_id INTEGER NOT NULL DEFAULT 0;

ALTER TABLE memory_compile_state
ADD COLUMN last_draft_ms INTEGER NOT NULL DEFAULT 0;

ALTER TABLE memory_compile_state
ADD COLUMN last_draft_bundle_hash TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_compile_state
ADD COLUMN last_draft_run_id TEXT NOT NULL DEFAULT '';
