-- Add durable per-project catalog admission leases and successful committed digests.
-- The receipt history remains append-only; the lease table is the CAS guard for
-- the one live worker allowed to append the next transition.
ALTER TABLE memory_catalog_consolidation_receipts
    ADD COLUMN admission_token TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_catalog_consolidation_receipts
    ADD COLUMN lease_expires_at_ms INTEGER NOT NULL DEFAULT 0;

ALTER TABLE memory_catalog_consolidation_receipts
    ADD COLUMN last_successful_catalog_digest TEXT NOT NULL DEFAULT '';

ALTER TABLE memory_catalog_consolidation_receipts
    ADD COLUMN last_successful_catalog_committed_at_ms INTEGER NOT NULL DEFAULT 0;

-- Existing completed receipts predate the explicit committed-digest marker.
-- Preserve their already successful digest as the baseline for unchanged checks.
UPDATE memory_catalog_consolidation_receipts
SET last_successful_catalog_digest = catalog_digest,
    last_successful_catalog_committed_at_ms = last_completion_at_ms
WHERE state = 'completed'
  AND catalog_digest <> ''
  AND last_successful_catalog_digest = '';

CREATE TABLE IF NOT EXISTS memory_catalog_consolidation_leases (
    project TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    lease_expires_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_catalog_consolidation_committed
    ON memory_catalog_consolidation_receipts(
        project,
        state,
        last_successful_catalog_committed_at_ms DESC,
        receipt_sequence DESC
    );
