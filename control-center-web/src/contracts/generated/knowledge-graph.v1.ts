/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/knowledge-graph.v1.json
 */

export interface KnowledgeGraphV1 {
  schemaVersion: 'rag-ime.knowledge-graph.v1';
  kbId: string;
  revision: number;
  sourceRevision: string;
  status: 'ready' | 'building' | 'stale' | 'failed';
  updatedAtMs: number;
  jobId?: string;
  error?: string;
  /**
   * @maxItems 1000
   */
  nodes: Node[];
  /**
   * @maxItems 3000
   */
  edges: Edge[];
  stats: {
    nodeCount: number;
    edgeCount: number;
    documentCount: number;
    chunkCount: number;
    indexedDocumentCount: number;
    pendingDocumentCount: number;
  };
  truncated: boolean;
}
export interface Node {
  id: string;
  label: string;
  kind: 'document' | 'chunk' | 'topic' | 'entity' | 'term';
  documentId?: string;
  documentName?: string;
  /**
   * @maxItems 1000
   */
  documentIds?: string[];
  chunkId?: string;
  heading?: string;
  excerpt?: string;
  page?: number;
  weight: number;
}
export interface Edge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label?: string;
  weight: number;
}
