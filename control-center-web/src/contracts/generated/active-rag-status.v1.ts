/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/active-rag-status.v1.json
 */

export interface ActiveRagStatusV1 {
  schemaVersion: 'rag-ime.active-rag-service.v1';
  sessionId: string;
  status: string;
  evidenceCount: number;
  candidateCount: number;
  candidates?: unknown[];
  stored?: boolean;
  noStore?: boolean;
  privacyAssessment?: {
    [k: string]: unknown;
  };
  storageReceipt?: {
    [k: string]: unknown;
  };
  diagnostics: {
    contextInjection: {
      applied: boolean;
      source: string;
      contextChars: number;
      contextHash: string;
      selectedTextChars: number;
      warnings: string[];
      [k: string]: unknown;
    };
    retrieval: {
      called: boolean;
      evidenceCount: number;
      lanes: {
        [k: string]: unknown;
      };
      elapsedMs: number;
      [k: string]: unknown;
    };
    remoteModel: {
      requested: boolean;
      allowed: boolean;
      provider: string;
      model: string;
      skipReason: string;
      elapsedMs: number;
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
  traceEvents?: unknown[];
  [k: string]: unknown;
}
