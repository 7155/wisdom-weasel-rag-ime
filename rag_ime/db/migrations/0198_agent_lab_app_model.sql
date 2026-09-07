-- Per-call user selection is separate from the evaluated frozen App default.
ALTER TABLE agent_lab_app_calls ADD COLUMN model_json TEXT NOT NULL DEFAULT '{}';
