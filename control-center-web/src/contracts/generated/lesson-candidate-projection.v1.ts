/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/lesson-candidate-projection.v1.json
 */

export interface LessonCandidateProjectionV1 {
  schemaVersion: 'wisdom-weasel.lesson-candidate-projection.v1';
  lessonCandidateId: string;
  incidentId: string;
  facts: unknown[];
  causes: unknown[];
  applicabilityBoundary: {
    [k: string]: unknown;
  };
  counterexamples: unknown[];
  provenance: unknown[];
  candidateHash: string;
  state: 'candidate_only';
  createdAtMs: number;
}
