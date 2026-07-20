/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/guard-eval-run-projection.v1.json
 */

export interface GuardEvalRunProjectionV1 {
  schemaVersion: 'wisdom-weasel.guard-eval-run-projection.v1';
  evalRunId: string;
  guardCandidateId: string;
  mode: string;
  datasetHash: string;
  metrics: {
    [k: string]: unknown;
  };
  status: string;
  createdAtMs: number;
}
