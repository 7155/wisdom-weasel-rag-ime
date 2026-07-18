/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/activity-timeline-context.v1.json
 */

export interface ActivityTimelineContextV1 {
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
    | [Segment]
    | [Segment, Segment]
    | [Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment]
    | [Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment, Segment]
    | [
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
      ]
    | [
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
        Segment,
      ];
  eventCount: number;
  retainedEventCount: number;
  filteredInternalEventCount: number;
  deduplicatedEventCount: number;
  redactedEventCount: number;
  corroborationOnly: true;
  maySupportFacts: false;
  source?: Source;
  ref?: Ref;
}
export interface Segment {
  segmentId: string;
  position: number;
  app: string;
  /**
   * @maxItems 12
   */
  sourceKinds:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  /**
   * @maxItems 12
   */
  contextGroupIds:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  startMs: number;
  endMs: number;
  eventCount: number;
  summary: string;
  redactedEventCount: number;
  title?: string;
  /**
   * @maxItems 12
   */
  apps?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
      ];
  source?: Source;
  ref?: Ref;
}
export interface Source {
  type: 'activity_timeline';
  id: string;
}
export interface Ref {
  type: 'timeline';
  id: string;
  segmentId?: string;
}
