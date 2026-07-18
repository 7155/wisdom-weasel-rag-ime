/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/daily-conversation-digest.v1.json
 */

export interface DailyConversationDigestV1 {
  schemaVersion: 'rag-ime.daily-conversation-digest.v1';
  digestId: string;
  project: string;
  roleId: string;
  window: {
    startMs: number;
    endMs: number;
    [k: string]: unknown;
  };
  sourceEvidenceIds: string[];
  activityTimelineId: string;
  sourceCounts: {
    [k: string]: unknown;
  };
  summary: string;
  highlights: DigestItem[];
  recentWork: DigestItem[];
  caveats: string[];
  generatedAtMs: number;
}
export interface DigestItem {
  evidenceId: string;
  sourceKind: string;
  text: string;
  occurredAtMs: number;
  [k: string]: unknown;
}
