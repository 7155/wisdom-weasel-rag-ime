/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/frontend-selection-response.v1.json
 */

export interface FrontendSelectionResponseV1 {
  schemaVersion: 'rag-ime.frontend-selection-response.v1';
  gatewayVersion: 'rag-ime.frontend-gateway.v1';
  ok: boolean;
  session: Session;
  selectionReceipt: SelectionReceipt;
  eventId: string;
  origin: string;
  insertText: string;
  recordedActionCount: number;
  privacy: {
    [k: string]: unknown;
  };
  backendContract: string;
  [k: string]: unknown;
}
export interface Session {
  id: string;
  requestSeq: number;
  inputGeneration: number;
  [k: string]: unknown;
}
export interface SelectionReceipt {
  sessionId: string;
  requestSeq: number;
  inputGeneration: number;
  snapshotId: string;
  snapshotGeneration: number;
  candidateId: string;
  requestConsistencyValidated: boolean;
  runtimeFreshnessValidated: boolean;
  [k: string]: unknown;
}
