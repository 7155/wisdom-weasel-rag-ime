/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/management-work-receipt.v1.json
 */

export interface ManagementWorkReceiptV1 {
  schemaVersion: 'rag-ime.management-work-receipt.v1';
  ok: true;
  receiptId: string;
  pathId: string;
  payloadSha256: string;
  appliedAtMs: number;
  auditId: number;
  rollbackAvailable: boolean;
  rollbackToken: string;
  rollbackAuthority: {
    [k: string]: unknown;
  };
  restartComponents: string[];
  result: {
    [k: string]: unknown;
  };
  rollbackOfReceiptId?: string;
  [k: string]: unknown;
}
