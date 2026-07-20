/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/incident-occurrence-projection.v1.json
 */

export interface IncidentOccurrenceProjectionV1 {
  schemaVersion: 'wisdom-weasel.incident-occurrence-projection.v1';
  incidentId: string;
  taxonomy: string;
  failureSignature: string;
  evidenceRefs: string[];
  occurrenceCount: number;
  lastObservedAtMs: number;
}
