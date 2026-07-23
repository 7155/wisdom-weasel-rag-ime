/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-commit.v2.json
 */

export interface RoomCommitV2 {
  schemaVersion: 'wisdom-weasel.room-commit.v2';
  commitId: string;
  dispatchId: string;
  action: 'post' | 'dispatch' | 'wait' | 'complete' | 'block';
  contentHash: string;
  postProposal: {
    [k: string]: unknown;
  } | null;
  postInvocationReceiptId?: string;
  continuation?: null | {
    [k: string]: unknown;
  };
  evidenceRefs: string[];
  requirementCoverage: string[];
  createdAtMs: number;
}
