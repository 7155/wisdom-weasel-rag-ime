/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-tool-disclosure-receipt.v1.json
 */

export interface RoomToolDisclosureReceiptV1 {
  schemaVersion: 'wisdom-weasel.room-tool-disclosure-receipt.v1';
  receiptId: string;
  manifestId: string;
  manifestHash: string;
  kind: 'search' | 'load';
  query: string;
  toolName: string;
  schemaHash: string;
  items: {
    [k: string]: unknown;
  }[];
  createdAtMs: number;
}
