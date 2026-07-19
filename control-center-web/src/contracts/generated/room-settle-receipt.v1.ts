/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-settle-receipt.v1.json
 */

export interface RoomSettleReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-settle-receipt.v1';
  settleReceiptId: string;
  eventKind: 'agent_settled';
  status: 'settled';
  dispatchId: string;
  sessionId: string;
  generation: number;
  capabilityEpoch: number;
  createdAtMs: number;
}
