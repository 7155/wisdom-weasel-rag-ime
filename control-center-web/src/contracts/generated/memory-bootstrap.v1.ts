/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-bootstrap.v1.json
 */

export interface MemoryBootstrapV1 {
  schemaVersion: 'rag-ime.memory-bootstrap.v1';
  bootstrapId: string;
  sessionId: string;
  project: string;
  roleId: string;
  generatedAtMs: number;
  queryFree: true;
  sections: {
    stablePreferences: ContextSource[];
    projectState: ContextSource[];
    topicBooks: ContextSource[];
    recentTimeline: ContextSource[];
    activeAtoms: ContextSource[];
    oneRing: ContextSource[];
    [k: string]: unknown;
  };
  sourceIds: string[];
  budget: {
    maxChars: number;
    usedChars: number;
    omittedCounts: {
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
  policy: {
    automaticRecall: 'session_start_only';
    lifecycle: 'once';
    oneRingMaySupportFacts: false;
    rawDialogueIsLongTermFact: false;
    layerBoundaries?: {
      evidence: string;
      atom: string;
      topicBook: string;
      roleBook: string;
      timeline: string;
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
}
export interface ContextSource {
  sourceType: 'memory_atom' | 'memory_book' | 'memory_evidence' | 'planning_item';
  sourceId: string;
  text: string;
  kind?: string;
  occurredAtMs: number;
  maySupportFacts: boolean;
  provenance: {
    [k: string]: unknown;
  };
  source?: SourceRef;
  ref?: SourceRef;
  [k: string]: unknown;
}
export interface SourceRef {
  type: string;
  id: string;
  bookId?: string;
  [k: string]: unknown;
}
