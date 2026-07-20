/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-tool-invocation-receipt.v1.json
 */

export interface RoomToolInvocationReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-tool-invocation-receipt.v1';
  receiptId: string;
  manifestId: string;
  manifestHash: string;
  loadReceiptId: string;
  invocationKey: string;
  canonicalCommand: {
    [k: string]: unknown;
  };
  authorizationState: 'authorized';
  createdAtMs: number;
}
