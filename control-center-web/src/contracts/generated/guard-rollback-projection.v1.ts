/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/guard-rollback-projection.v1.json
 */

export interface GuardRollbackProjectionV1 {
  schemaVersion: 'wisdom-weasel.guard-rollback-projection.v1';
  rollbackReceiptId: string;
  scopeKey: string;
  fromGuardCandidateId: string;
  restoredGuardCandidateId: string | null;
  guardEpoch: number;
  cancelledDispatchIds: unknown[];
  authorityRef: string;
  reason: string;
  createdAtMs: number;
}
