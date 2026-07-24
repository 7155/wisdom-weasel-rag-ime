/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-quality-gate-receipt.v1.json
 */

export interface RoomQualityGateReceiptV1 {
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
