/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/collaboration-profile-command-receipt.v1.json
 */

export interface CollaborationProfileCommandReceiptV1 {
  schemaVersion: 'rag-ime.collaboration-profile-command-receipt.v1';
  receiptId: string;
  commandId: string;
  commandHash: string;
  action:
    'inspect' | 'validate' | 'compile' | 'dry_run' | 'stage' | 'activate' | 'rollback' | 'revoke';
  status: 'applied';
  profileId: string | null;
  routeHash: string;
  guardEpoch: number;
  result: {
    [k: string]: unknown;
  };
  createdAtMs: number;
}
