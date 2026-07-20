/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/reflection-dead-letter-projection.v1.json
 */

export interface ReflectionDeadLetterProjectionV1 {
  schemaVersion: 'wisdom-weasel.reflection-dead-letter-projection.v1';
  deadLetterId: string;
  incidentId: string;
  ownerRef: string;
  reasonCode: string;
  lastEvidenceRefs: unknown[];
  nextAction: string;
  attemptCount: number;
  createdAtMs: number;
}
