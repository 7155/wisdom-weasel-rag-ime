/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/frontend-suggest-response.v1.json
 */

export interface FrontendSuggestResponseV1 {
  schemaVersion: 'rag-ime.frontend-suggest-response.v1';
  gatewayVersion: 'rag-ime.frontend-gateway.v1';
  frontend: {
    [k: string]: unknown;
  };
  session: Session;
  input: {
    [k: string]: unknown;
  };
  candidates: Candidate[];
  presentation: {
    [k: string]: unknown;
  };
  selectionPolicy: {
    [k: string]: unknown;
  };
  predictionSession: {
    [k: string]: unknown;
  };
  progressive?: {
    [k: string]: unknown;
  };
  privacy: {
    [k: string]: unknown;
  };
  diagnostics?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
export interface Session {
  id: string;
  requestSeq: number;
  inputGeneration: number;
  [k: string]: unknown;
}
export interface Candidate {
  id: string;
  snapshotId: string;
  snapshotGeneration: number;
  inputGeneration: number;
  label?: string;
  text: string;
  insertText: string;
  origin:
    'native' | 'model' | 'retrieval' | 'memory' | 'action' | 'status' | 'literal' | 'assistant';
  provider?: string;
  rank: number;
  nativeIndex?: number | null;
  selectionAction: string;
  metadata?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
