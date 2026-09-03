/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lab-path-search.v1.json
 */

export type Text = string;
export type Sha256 = string;

export interface AgentLabPathSearchV1 {
  schemaVersion: 'rag-ime.agent-lab-path-search.v1';
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
  /**
   * @minItems 1
   * @maxItems 64
   */
  selectedPath: [PathStep, ...PathStep[]];
  /**
   * @minItems 1
   * @maxItems 32
   */
  hardGates: [GateResult, ...GateResult[]];
  claim: Claim;
  generatedAtMs: number;
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
export interface PathStep {
  nodeId: string;
  decision: 'baseline' | 'keep' | 'reject' | 'not_evaluated' | 'unknown';
  reason: Text;
}
export interface GateResult {
  name: string;
  status: 'pass' | 'fail' | 'unknown';
  reason: Text;
}
export interface Claim {
  status: 'best_known' | 'blocked' | 'insufficient_evidence';
  summary: Text;
  /**
   * @minItems 1
   * @maxItems 16
   */
  limitations:
    | [Text]
    | [Text, Text]
    | [Text, Text, Text]
    | [Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text, Text]
    | [
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
        Text,
      ];
}
