-- Public execution feedback is separate from the immutable final result.
ALTER TABLE agent_lab_app_calls ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}';
