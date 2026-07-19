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
  activityContext: ActivityContext;
  sourceCounts: {
    [k: string]: unknown;
  };
  summary: string;
  highlights: DigestItem[];
  recentWork: DigestItem[];
  caveats: string[];
  generatedAtMs: number;
}
export interface ActivityContext {
  schemaVersion: 'rag-ime.activity-timeline-context.v1';
  available: boolean;
  date: string;
  timelineId: string;
  status: 'unavailable' | 'draft' | 'approved';
  sourceEventHash: string;
  summary: string;
  /**
   * @maxItems 12
   */
  segments:
    | []
    | [
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ]
    | [
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
        {
          [k: string]: unknown;
        },
      ];
  eventCount: number;
  retainedEventCount: number;
  filteredInternalEventCount: number;
  deduplicatedEventCount: number;
  redactedEventCount: number;
  corroborationOnly: true;
  maySupportFacts: false;
  source?: ActivitySource;
  ref?: ActivityRef;
}
export interface ActivitySource {
  type: 'activity_timeline';
  id: string;
}
export interface ActivityRef {
  type: 'timeline';
  id: string;
}
export interface DigestItem {
  evidenceId: string;
  sourceKind: string;
  text: string;
  occurredAtMs: number;
  [k: string]: unknown;
}
