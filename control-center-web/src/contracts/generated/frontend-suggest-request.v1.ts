/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/frontend-suggest-request.v1.json
 */

export interface FrontendSuggestRequestV1 {
  schemaVersion: 'rag-ime.frontend-suggest-request.v1';
  frontend: Frontend;
  session: Session;
  privacy: Privacy;
  input: Input;
  context?: {
    [k: string]: unknown;
  };
  nativeCandidates?: NativeCandidate[];
  nativeState?: {
    [k: string]: unknown;
  };
  limits?: {
    [k: string]: unknown;
  };
  flags?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
export interface Frontend {
  id: string;
  build?: string;
  platform: string;
  inputFramework?: string;
  inputEngine: string;
  [k: string]: unknown;
}
export interface Session {
  id: string;
  requestSeq: number;
  inputGeneration: number;
  [k: string]: unknown;
}
export interface Privacy {
  disposition: 'allowed' | 'sensitive' | 'unknown';
  reason?: string;
  sensitiveField?: boolean;
  secureInput?: boolean;
  [k: string]: unknown;
}
export interface Input {
  raw?: string;
  preedit?: string;
  commitPreview?: string;
  committedContext?: string;
  idleMs?: number;
  [k: string]: unknown;
}
export interface NativeCandidate {
  id?: string;
  label?: string;
  text: string;
  annotation?: string;
  rank?: number;
  nativeIndex?: number;
  metadata?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
