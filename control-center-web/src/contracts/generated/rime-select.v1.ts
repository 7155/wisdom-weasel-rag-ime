/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/rime-select.v1.json
 */

export interface RimeSelectV1 {
  candidate: Candidate;
  shownCandidates?: Candidate[];
  query?: string;
  recentContext?: string;
  committedContext?: string;
  preedit?: string;
  project?: string;
  app?: string;
  frontAppBundleId?: string;
  frontmostApp?: string;
  bundleId?: string;
  contextGroupId?: string;
  contextGroupLevel?: string;
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
  dryRun?: boolean;
  [k: string]: unknown;
}
export interface Candidate {
  text?: string;
  insertText: string;
  sourceType: string;
  memoryId?: string;
  suggestionId?: string;
  sourceEventId?: number | null;
  [k: string]: unknown;
}
