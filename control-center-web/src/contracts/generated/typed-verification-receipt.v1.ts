/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/typed-verification-receipt.v1.json
 */

export interface TypedVerificationReceiptV1 {
  schemaVersion: 'wisdom-weasel.typed-verification-receipt.v1';
  receiptId: string;
  rootId: string;
  catalogRevisionId: string;
  receiptType: 'test' | 'build' | 'install' | 'evidence';
  sourceCommit: string;
  environment: string;
  commandOrAction: string;
  exitStatus: number;
  outputHash: string;
  artifactHash: string;
  verifier: string;
  createdAtMs: number;
}
