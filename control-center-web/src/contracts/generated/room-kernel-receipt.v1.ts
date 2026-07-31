/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-kernel-receipt.v1.json
 */

export interface RoomKernelReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1';
  receiptId: string;
  rootId: string | null;
  commandId: string | null;
  receiptKind:
    | 'accepted'
    | 'duplicate'
    | 'rejected'
    | 'target_cancelled'
    | 'root_cancelled'
    | 'panic'
    | 'runtime_accepted'
    | 'runtime_failed'
    | 'runtime_retry_scheduled'
    | 'dispatch_unknown'
    | 'dead_letter'
    | 'settle_retry_required'
    | 'settle_blocked'
    | 'terminal';
  status: 'applied' | 'noop' | 'rejected' | 'unknown';
  generation: number;
  details: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
