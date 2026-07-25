ALTER TABLE memory_capture_hints
ADD COLUMN basis TEXT NOT NULL DEFAULT 'explicit_user_statement'
CHECK (
    basis IN (
        'explicit_user_request',
        'explicit_user_statement',
        'user_correction',
        'repeated_user_signal',
        'verified_outcome'
    )
);

ALTER TABLE memory_capture_hints
ADD COLUMN future_use TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_capture_hints
ADD COLUMN supersedes TEXT NOT NULL DEFAULT '';
