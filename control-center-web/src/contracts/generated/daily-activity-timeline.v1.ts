/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/daily-activity-timeline.v1.json
 */

export interface DailyActivityTimelineV1 {
  schemaVersion: 'rag-ime.daily-activity-timeline.v1';
  timelineId: string;
  project: string;
  date: string;
  timezone: string;
  status: 'draft' | 'approved' | 'rejected' | 'superseded';
  sourceEventIds: number[];
  sourceEventHash: string;
  segments: Segment[];
  summary: string;
  eventCount: number;
  segmentCount: number;
  observedStartMs: number;
  observedEndMs: number;
  spanSemantics: 'first_to_last_source_event';
  ordinaryActivityCount: number;
  consolidatedActivityCount: number;
  approvedBookId: string;
  approvedBy: string;
  approvedAtMs: number;
  createdAtMs: number;
  updatedAtMs: number;
  segmentationMode?:
    | 'semantic_task_v5'
    | 'semantic_task_v4'
    | 'semantic_task_v3'
    | 'semantic_task_v2'
    | 'legacy_app_interval_v1';
  source?: Source;
  ref?: Ref;
  policy: {
    derivedFromInputEvents: true;
    longTermFact: false;
    automaticPromotion: true;
    explicitApprovalRequired: false;
    minimumConsolidatedSpanMs: number;
  };
}
export interface Segment {
  segmentId: string;
  position: number;
  app: string;
  sourceKinds: string[];
  contextGroupIds: string[];
  startMs: number;
  endMs: number;
  period: 'day' | 'morning' | 'afternoon' | 'evening';
  eventCount: number;
  sourceEventIds: number[];
  sourceEventHash: string;
  summary: string;
  redactedEventCount: number;
  activityKind: 'ordinary_activity' | 'consolidated_activity';
  spanSemantics: 'first_to_last_source_event';
  title?: string;
  apps?: string[];
  evidenceRefs?: EvidenceRef[];
  source?: Source;
  ref?: Ref;
}
export interface EvidenceRef {
  sourceType: 'input_event';
  sourceId: string;
  eventId: number;
  app: string;
  sourceKind: string;
  occurredAtMs: number;
  redacted: boolean;
}
export interface Source {
  type: string;
  id: string;
}
export interface Ref {
  type: string;
  id: string;
}
