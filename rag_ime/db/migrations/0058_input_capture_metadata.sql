ALTER TABLE input_events
ADD COLUMN capture_metadata_json TEXT NOT NULL DEFAULT '{}';
