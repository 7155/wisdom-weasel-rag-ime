/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/frontend-selection.v1.json
 */

export interface FrontendSelectionV1 {
  schemaVersion: 'rag-ime.frontend-selection.v1';
  frontend: {
    [k: string]: unknown;
  };
  session: Session;
  privacy: {
    disposition: 'allowed' | 'sensitive' | 'unknown';
    reason?: string;
    sensitiveField?: boolean;
    secureInput?: boolean;
    [k: string]: unknown;
  };
  candidate: Candidate;
  visibleCandidates?: Candidate[];
  context?: {
    [k: string]: unknown;
  };
  providerName?: string;
  dryRun?: boolean;
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
  rank?: number;
  nativeIndex?: number | null;
  selectionAction?: string;
  suggestionId?: string;
  memoryId?: string;
  sourceEventId?: number | null;
  metadata?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
