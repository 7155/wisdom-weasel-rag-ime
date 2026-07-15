/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/assistant-candidate-action.v1.json
 */

export interface AssistantCandidateActionV1 {
  action: 'remember' | 'suppress';
  candidate: {
    text?: string;
    insertText?: string;
    sourceType?: string;
    memoryId?: string;
    sourceEventId?: number | null;
    suggestionId?: string;
    candidateStableId?: string;
    [k: string]: unknown;
  };
  query?: string;
  project?: string;
  app?: string;
  frontAppBundleId?: string;
  frontmostApp?: string;
  bundleId?: string;
  privacyDisposition?: 'allowed' | 'sensitive' | 'unknown';
  sensitiveField?: boolean;
  secureInput?: boolean;
}
