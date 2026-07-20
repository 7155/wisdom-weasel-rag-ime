/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/delivery-gate-observation.v1.json
 */

export interface DeliveryGateObservationV1 {
  schemaVersion: 'wisdom-weasel.delivery-gate-observation.v1';
  gateReceiptId: string;
  rootId: string;
  catalogRevisionId: string;
  targetCommit: string;
  mode: 'observe_warn';
  gateStatus: 'observed_pass' | 'warn_blocked';
  enforcementApplied: false;
  blindReviewStatus: 'pending' | 'passed' | 'failed' | 'unavailable';
  reasons: string[];
  proofMatrix: {
    [k: string]: unknown;
  }[];
  createdAtMs: number;
}
