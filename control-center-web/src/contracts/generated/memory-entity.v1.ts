/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-entity.v1.json
 */

export type NodeKind = 'tag' | 'group' | 'atom' | 'book' | 'phrase' | 'memory';

export interface MemoryEntityV1 {
  schemaVersion: 'rag-ime.memory-entity.v1';
  ok: true;
  settingsRevision: string;
  runtimeRevision: number;
  kind: 'tag' | 'group' | 'book';
  entityId: string;
  entityRevision: string;
  project: string;
  entity: Node;
  topicPage?: TopicPage;
  attributes: Attributes;
  connections: Page;
  members: Page;
  limits: {
    connectionsLimit: number;
    membersLimit: number;
  };
}
export interface Node {
  id: string;
  entityId: string;
  kind: NodeKind;
  label: string;
  description: string;
  color: 'blue' | 'teal' | 'green' | 'orange' | 'pink' | 'purple' | 'gray';
  status: string;
  source: string;
  project: string;
  qualityScore: number;
  memberCount: number;
  edgeCount: number;
  updatedAtMs: number;
}
export interface TopicPage {
  schemaVersion: 'rag-ime.memory-topic-page.v1';
  bookId: string;
  revision: string;
  authority: 'atom_projection';
  freshness: 'current' | 'needs_refresh';
  summary: string;
  sections: {
    /**
     * @maxItems 256
     */
    current: TopicEntry[];
    /**
     * @maxItems 256
     */
    constraints: TopicEntry[];
    /**
     * @maxItems 256
     */
    openQuestions: TopicEntry[];
    /**
     * @maxItems 256
     */
    history: TopicEntry[];
  };
  /**
   * @maxItems 80
   */
  sources: TopicReference[];
  coverage: {
    memberCount: number;
    visibleAtomCount: number;
    omittedAtomCount: number;
    truncated: boolean;
  };
}
export interface TopicEntry {
  id: string;
  text: string;
  kind: string;
  status: string;
  claimState: 'current' | 'superseded';
  /**
   * @minItems 1
   * @maxItems 1
   */
  atomIds: [string];
  /**
   * @maxItems 21
   */
  references: TopicReference[];
  sourceStatus: 'available' | 'unavailable';
  lineageId: string;
  validFromMs: number;
  validToMs: number | null;
  supersedesId: string;
  /**
   * @maxItems 256
   */
  supersededByIds: string[];
  reason: null;
}
export interface TopicReference {
  kind: 'atom' | 'evidence' | 'event';
  id: string;
  referenceKind: 'atom' | 'evidence' | 'event';
  referenceId: string;
  label?: string;
}
export interface Attributes {
  type: string;
  /**
   * @maxItems 64
   */
  aliases: string[];
  /**
   * @maxItems 64
   */
  tags: string[];
}
export interface Page {
  /**
   * @maxItems 100
   */
  items: Related[];
  nextCursor: string;
  limit: number;
  hasMore: boolean;
}
export interface Related {
  node: Node;
  edge: Edge;
}
export interface Edge {
  id: string;
  kind: 'tagRelation' | 'groupMember' | 'tagMember';
  sourceId: string;
  targetId: string;
  sourceKind: NodeKind;
  targetKind: NodeKind;
  relation: string;
  weight: number;
  directionBias: number;
  evidenceCount: number;
  source: string;
  updatedAtMs: number;
}
