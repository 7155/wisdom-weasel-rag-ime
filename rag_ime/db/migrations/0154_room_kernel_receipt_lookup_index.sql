-- Startup reconciliation reads canonical receipts one Root and kind at a time.
-- Keep the filter and deterministic replay order in one index so a large
-- receipt ledger is never scanned once per historical Root.
CREATE INDEX IF NOT EXISTS idx_room_kernel_receipts_root_kind_created
ON room_kernel_receipts(root_id, receipt_kind, created_at_ms, receipt_id);

CREATE INDEX IF NOT EXISTS idx_room_kernel_receipts_ingest_order
ON room_kernel_receipts(created_at_ms, receipt_id)
WHERE root_id IS NOT NULL;
