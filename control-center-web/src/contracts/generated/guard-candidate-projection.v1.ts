/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/guard-candidate-projection.v1.json
 */

export interface GuardCandidateProjectionV1 {
  schemaVersion: 'wisdom-weasel.guard-candidate-projection.v1';
  guardCandidateId: string;
  lessonCandidateId: string;
  version: number;
  condition: {
    [k: string]: unknown;
  };
  action: {
    [k: string]: unknown;
  };
  scope: {
    [k: string]: unknown;
  };
  risk: string;
  thresholds: {
    [k: string]: unknown;
  };
  owner: string;
  sunsetAtMs: number;
  candidateHash: string;
  state: 'candidate_only';
  createdAtMs: number;
}
