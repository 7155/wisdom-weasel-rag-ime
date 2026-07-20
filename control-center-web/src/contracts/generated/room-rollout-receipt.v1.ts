/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-rollout-receipt.v1.json
 */

export interface RoomRolloutReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-rollout-receipt.v1';
  receiptId: string;
  policyId: string;
  action: 'promote' | 'rollback';
  fromStage: string;
  toStage: string;
  affectedRootIds: string[];
  ledgerHash: string;
  createdAtMs: number;
}
