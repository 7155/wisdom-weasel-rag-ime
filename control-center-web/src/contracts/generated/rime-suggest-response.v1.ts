/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/rime-suggest-response.v1.json
 */

export interface RimeSuggestResponseV1 {
  schemaVersion: string;
  sessionId: string;
  requestSeq: number;
  runtimeRevision?: number;
  runtimeConfig?: {
    [k: string]: unknown;
  };
  displayCandidates: unknown[];
  predictionSession: {
    [k: string]: unknown;
  };
  keyPolicy: {
    [k: string]: unknown;
  };
  assistantOverlay: {
    [k: string]: unknown;
  };
  overlayConfig?: {
    [k: string]: unknown;
  };
  frontendTransaction?: {
    [k: string]: unknown;
  };
  stored?: boolean;
  noStore?: boolean;
  privacyAssessment?: {
    [k: string]: unknown;
  };
  storageReceipt?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
