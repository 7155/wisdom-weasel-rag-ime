/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-skill-load-receipt.v1.json
 */

export interface RoomSkillLoadReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-skill-load-receipt.v1';
  receiptId: string;
  rootId: string;
  taskId: string;
  dispatchId: string;
  sessionId: string;
  skillId: string;
  skillHash: string;
  hashRule: 'sha256-skill-body-utf8-v1';
  catalogRevision: string;
  policyId: string;
  policyVersion: number;
  loadReason: 'stage_required' | 'model_selected' | 'compaction_restore';
  capabilityEpoch: number;
  idempotencyKey: string;
  state: 'active' | 'revoked';
  sourceReceiptId: string;
  createdAtMs: number;
  revokedAtMs: number | null;
}
