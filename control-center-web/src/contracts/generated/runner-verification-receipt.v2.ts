/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/runner-verification-receipt.v2.json
 */

export interface RunnerVerificationReceiptV2 {
  schemaVersion: 'wisdom-weasel.runner-verification-receipt.v2';
  receiptId: string;
  rootId: string;
  catalogRevisionId: string;
  receiptType: 'test' | 'build' | 'install' | 'browser' | 'evidence';
  sourceCommit: string;
  environment: string;
  worktreeHash: string;
  commandOrAction: string;
  exitStatus: number;
  outputHash: string;
  artifactHash: string;
  toolVersion: string;
  issuerId: string;
  contentHash: string;
  issuerSignature: string;
  createdAtMs: number;
}
