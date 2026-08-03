-- A verifier must not inherit the adjudicator transcript. Persist the exact
-- internal Session used by each frozen model request so an isolated verifier
-- can resume after Gateway restart and every run-owned Session can be retired.
ALTER TABLE memory_curation_model_requests
ADD COLUMN session_id TEXT NOT NULL DEFAULT '';

UPDATE memory_curation_model_requests
SET session_id = COALESCE(
    (
        SELECT run.session_id
        FROM memory_curation_model_runs AS run
        WHERE run.run_id = memory_curation_model_requests.run_id
    ),
    ''
)
WHERE session_id = '';

CREATE INDEX idx_memory_curation_model_requests_session
ON memory_curation_model_requests(session_id, state, updated_at_ms DESC);
