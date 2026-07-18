/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/rime-suggest-request.v1.json
 */

export interface RimeSuggestRequestV1 {
  schemaVersion?: string;
  sessionId: string;
  requestSeq: number;
  rawInput?: string;
  preedit?: string;
  commitTextPreview?: string;
  committedContext?: string;
  project?: string;
  app?: string;
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  privacyLeaseId?: string;
  privacyLeaseEpoch?: number;
  privacyFocusEpoch?: number;
  sensitiveField?: boolean;
  secureInput?: boolean;
  progressiveFollowUp?: boolean;
  frontendRevision?: number;
  selectionEpoch?: number;
  inputGeneration?: number;
  foregroundText?: ForegroundContext;
  [k: string]: unknown;
}
export interface ForegroundContext {
  available: boolean;
  source: string;
  freshnessMs: number;
  surroundingBefore?: string;
  surroundingAfter?: string;
  selectedText?: string;
  canReplaceSelection?: boolean;
  contextGroupId?: string;
  contextGroupLevel?: 'document' | 'project' | 'app' | 'global' | '';
  [k: string]: unknown;
}
