/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lab-path-search-request.v1.json
 */

export type Text = string;
export type Sha256 = string;

export interface AgentLabPathSearchRequestV1 {
  schemaVersion: 'rag-ime.agent-lab-path-search-request.v1';
  searchId: string;
  title: string;
  objective: Objective;
  /**
   * @minItems 1
   * @maxItems 32
   */
  frozenControls: [FrozenControl, ...FrozenControl[]];
  baseline: Node;
  /**
   * @minItems 1
   * @maxItems 128
   */
  candidates: [Node, ...Node[]];
}
export interface Objective {
  userNeed: Text;
  /**
   * @minItems 1
   * @maxItems 32
   */
  metrics: [MetricSpec, ...MetricSpec[]];
  /**
   * @minItems 1
   * @maxItems 32
   */
  gates: [GateSpec, ...GateSpec[]];
  selectionPolicy: 'lexicographic_pareto' | 'weighted_pareto';
}
export interface MetricSpec {
  name: string;
  direction: 'max' | 'min';
  weight: number;
  class: 'quality' | 'reliability' | 'efficiency' | 'cost';
  scale?: number;
  nonRegression?: boolean;
}
export interface GateSpec {
  name: string;
  metric: string;
  operator: 'gte' | 'lte' | 'eq';
  value: number;
}
export interface FrozenControl {
  name: string;
  value: Text;
}
export interface Node {
  nodeId: string;
  parentNodeId: string | null;
  changedFactor: string;
  configRevision: string;
  frozenControlHash: Sha256;
  metrics: {
    [k: string]: number;
  };
  /**
   * @maxItems 64
   */
  evidenceRefs: string[];
  status: 'eligible' | 'rejected' | 'not_evaluated' | 'unknown';
  reason?: Text;
}
