/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/foreground-commit.v1.json
 */

export interface ForegroundCommitV1 {
  text: string;
  recentContext?: string;
  preedit?: string;
  project?: string;
  app?: string;
  frontAppBundleId?: string;
  frontmostApp?: string;
  bundleId?: string;
  candidateRank?: number | null;
  providerName?: string;
  tags?: string[];
  source?: string;
  contextGroupId?: string;
  contextGroupLevel?: string;
  captureMetadata?: {
    captureSource?: string;
    fallbackReason?: string;
    fieldContextChars?: number;
    imeBufferChars?: number;
    selectedTextSha256?: string;
    selectionRule?: string;
  };
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
}
