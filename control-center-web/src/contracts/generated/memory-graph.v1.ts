/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/memory-graph.v1.json
 */

export type NodeKind = 'tag' | 'group' | 'atom' | 'book' | 'phrase';

export interface MemoryGraphV1 {
  schemaVersion: 'rag-ime.memory-graph.v1';
  ok: true;
  settingsRevision: string;
  runtimeRevision: number;
  graphRevision: string;
  plane: 'tags' | 'groups';
  project: string;
  filters: {
    status: 'active' | 'merged' | 'all';
    query: string;
    focusId: string;
    minWeight: number;
  };
  /**
   * @maxItems 200
   */
  nodes: Node[];
  /**
   * @maxItems 500
   */
  edges: Edge[];
  truncated: {
    nodes: boolean;
    edges: boolean;
  };
  limits: {
    nodeLimit: number;
    edgeLimit: number;
    depth: number;
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
export interface Edge {
  id: string;
  kind: 'tagRelation' | 'groupMember';
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
