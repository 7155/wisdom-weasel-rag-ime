/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-commit.v3.json
 */

export interface RoomCommitV3 {
  schemaVersion: 'wisdom-weasel.room-commit.v3';
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
  qualityGateReceipt: QualityGateReceipt;
  evidenceRefs: string[];
  requirementCoverage: string[];
  createdAtMs: number;
}
export interface QualityGateReceipt {
  schemaVersion: 'wisdom-weasel.room-quality-gate-receipt.v1';
  receiptId: string;
  rootId: string;
  taskId: string;
  dispatchId: string;
  generation: number;
  originalRequestChecked: boolean;
  verdict: 'ready_to_deliver' | 'not_ready';
  /**
   * @maxItems 64
   */
  items: {
    criterionId: string;
    status: 'pass' | 'fail' | 'not_verified';
    /**
     * @maxItems 64
     */
    evidenceRefs: string[];
  }[];
  /**
   * @maxItems 32
   */
  residualRisks: string[];
  createdAtMs: number;
}
