ALTER TABLE room_application_outbox
ADD COLUMN lease_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_room_application_outbox_lease
ON room_application_outbox(outbox_id, state, lease_id, attempt);
