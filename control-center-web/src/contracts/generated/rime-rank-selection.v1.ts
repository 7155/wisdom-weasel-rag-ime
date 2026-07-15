/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/rime-rank-selection.v1.json
 */

export interface RimeRankSelectionV1 {
  schemaVersion: 'rag-ime.rime-rank-selection.v1';
  selectionId: string;
  sourceType: 'rime';
  selectionSource?: string;
  preedit: string;
  acceptedText: string;
  rejectedText?: string;
  candidateRank: number;
  shownCandidateCount?: number;
  app?: string;
  frontAppBundleId?: string;
  frontmostApp?: string;
  bundleId?: string;
  project?: string;
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
  dryRun?: boolean;
}
