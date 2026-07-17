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
  approvedBookId: string;
  approvedBy: string;
  approvedAtMs: number;
  createdAtMs: number;
  updatedAtMs: number;
  policy: {
    derivedFromInputEvents: true;
    longTermFact: false;
    automaticPromotion: false;
    explicitApprovalRequired: true;
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
  eventCount: number;
  sourceEventIds: number[];
  sourceEventHash: string;
  summary: string;
  redactedEventCount: number;
}
