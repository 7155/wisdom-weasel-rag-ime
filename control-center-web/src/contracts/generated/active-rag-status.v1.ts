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
    progress?: {
      stage: string;
      elapsedMs: number;
      context: {
        foregroundChars?: number;
        windowNodeCount?: number;
        windowCaptureMode?: string;
        recentInputCount?: number;
        recentInputChars?: number;
        recentInputUsed?: boolean;
        [k: string]: unknown;
      };
      retrieval: {
        attempted?: boolean;
        elapsedMs?: number;
        retrievedCount?: number;
        evidenceCount?: number;
        contextEvidenceCount?: number;
        /**
         * @maxItems 3
         */
        items?:
          | []
          | [
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
            ]
          | [
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
            ]
          | [
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
              {
                sourceType?: string;
                sourceLane?: string;
                title?: string;
                preview?: string;
                [k: string]: unknown;
              },
            ];
        [k: string]: unknown;
      };
      model: {
        attempted?: boolean;
        partialVisible?: boolean;
        partialChars?: number;
        firstTokenMs?: number;
        providerFirstTokenMs?: number;
        providerElapsedMs?: number;
        qualityRetry?: boolean;
        qualityRetryReason?: string;
        [k: string]: unknown;
      };
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
  traceEvents?: unknown[];
  [k: string]: unknown;
}
