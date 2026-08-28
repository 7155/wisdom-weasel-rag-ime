CREATE TABLE trace_envelopes (
    trace_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    -- A canonical row is immutable, so a live/building envelope could never
    -- be advanced to its terminal state. Live progress remains in the
    -- Observation journal; this authority stores terminal traces only.
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed', 'cancelled')),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);

CREATE INDEX idx_trace_envelopes_created
    ON trace_envelopes(created_at_ms, trace_id);

CREATE INDEX idx_trace_envelopes_source
    ON trace_envelopes(source_kind, created_at_ms, trace_id);

CREATE TRIGGER trace_envelopes_immutable_insert
BEFORE INSERT ON trace_envelopes
WHEN EXISTS (
    SELECT 1 FROM trace_envelopes WHERE trace_id = NEW.trace_id
)
BEGIN
    SELECT RAISE(ABORT, 'TraceEnvelope is immutable');
END;

CREATE TRIGGER trace_envelopes_immutable_update
BEFORE UPDATE ON trace_envelopes
BEGIN
    SELECT RAISE(ABORT, 'TraceEnvelope is immutable');
END;

CREATE TRIGGER trace_envelopes_immutable_delete
BEFORE DELETE ON trace_envelopes
BEGIN
    SELECT RAISE(ABORT, 'TraceEnvelope is permanent');
END;
