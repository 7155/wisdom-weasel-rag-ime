ALTER TABLE agent_todo_events
ADD COLUMN room_lineage_json TEXT NOT NULL DEFAULT 'null'
CHECK (
    json_valid(room_lineage_json)
    AND json_type(room_lineage_json) IN ('null', 'object')
);
