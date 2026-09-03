/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-lab-experiment.v1.json
 */

export type Sha256 = string;
export type Label = string;
export type Text = string;

export interface AgentLabExperimentV1 {
  schemaVersion: 'rag-ime.agent-lab-experiment.v1';
  experimentId: string;
  revisionSha256: Sha256;
  title: Label;
  vertical: string;
  evaluationKind:
    | 'workflow'
    | 'rag_retrieval'
    | 'answer_evidence'
    | 'tool_runtime'
    | 'trace_repair'
    | 'memory'
    | 'model_cost'
    | 'other';
  status: 'kept' | 'rejected' | 'diagnostic' | 'open_gap';
  claimStatus: 'headline' | 'supporting' | 'diagnostic' | 'blocked';
  effectStatus?: 'improved' | 'neutral' | 'regressed' | 'not_run' | 'unverified';
  candidateType?: 'single_factor' | 'compound_repair' | 'baseline' | 'unknown';
  businessProblem: Text;
  whyAgent: Text;
  dataset: Dataset;
  scoring: Scoring;
  /**
   * @minItems 1
   * @maxItems 16
   */
  factors:
    | [Factor]
    | [Factor, Factor]
    | [Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor]
    | [Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor, Factor]
    | [
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
      ]
    | [
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
      ]
    | [
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
      ]
    | [
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
      ]
    | [
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
        Factor,
      ];
  /**
   * @minItems 1
   * @maxItems 32
   */
  frozenControls: [FrozenControl, ...FrozenControl[]];
  baseline: RunSummary;
  candidate: RunSummary;
  comparison: Comparison;
  star: Star;
  claim: Claim;
  /**
   * @maxItems 32
   */
  openGaps: Text[];
  importedAtMs: number;
}
export interface Dataset {
  datasetId: string;
  split: string;
  caseCount: number;
  unit: Text;
  manifestSha256: Sha256;
  heldOutConsumed: boolean;
}
export interface Scoring {
  primaryMetric: Text;
  evaluatorAuthority: string;
  goldHiddenFromAgent: boolean;
  /**
   * @maxItems 32
   */
  hardGates: Text[];
}
export interface Factor {
  name:
    | 'model'
    | 'prompt'
    | 'skill'
    | 'tool'
    | 'workflow'
    | 'context'
    | 'memory_rag'
    | 'guardrail'
    | 'execution_policy'
    | 'human_loop'
    | 'pricing';
  before: Text;
  after: Text;
  reason: Text;
}
export interface FrozenControl {
  name: string;
  value: Text;
  reason: Text;
}
export interface RunSummary {
  runId: string;
  metrics: Metrics;
  /**
   * @maxItems 64
   */
  evidenceRefs: string[];
  /**
   * @maxItems 8
   */
  outputExamples?:
    | []
    | [OutputExample]
    | [OutputExample, OutputExample]
    | [OutputExample, OutputExample, OutputExample]
    | [OutputExample, OutputExample, OutputExample, OutputExample]
    | [OutputExample, OutputExample, OutputExample, OutputExample, OutputExample]
    | [OutputExample, OutputExample, OutputExample, OutputExample, OutputExample, OutputExample]
    | [
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
      ]
    | [
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
        OutputExample,
      ];
}
export interface Metrics {
  [k: string]: number;
}
export interface OutputExample {
  caseId: string;
  input: string;
  output: string;
}
export interface Comparison {
  decision: string;
  decisionReason: Text;
  /**
   * @maxItems 64
   */
  metricDeltas: MetricDelta[];
  /**
   * @maxItems 8
   */
  outputComparisons?:
    | []
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ]
    | [
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
        {
          caseId: string;
          before: string;
          after: string;
        },
      ];
}
export interface MetricDelta {
  metric: string;
  before: number;
  after: number;
  delta: number;
}
export interface Star {
  situation: Text;
  task: Text;
  action: Text;
  result: Text;
}
export interface Claim {
  resumeBullet: Text;
  allowed: Text;
  forbidden: Text;
}
