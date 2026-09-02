/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-diagnostic-result.v1.json
 */

/**
 * @maxItems 128
 */
export type EvidenceIds = string[];
export type DimensionId =
  | 'task_completion'
  | 'evidence_diagnosis'
  | 'tool_runtime'
  | 'context'
  | 'room_collaboration'
  | 'memory_rag'
  | 'efficiency'
  | 'repair_quality';
/**
 * @maxItems 32
 */
export type PresentationEvidenceIds = string[];
export type FailureAttributionLayer = {
  [k: string]: unknown;
} & {
  layer: 'tool' | 'skill' | 'template' | 'workflow' | 'model';
  verdict: 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';
  explanation: string;
  evidenceIds: FailureAttributionEvidenceIds;
} & {
  layer: 'tool' | 'skill' | 'template' | 'workflow' | 'model';
  verdict: 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';
  explanation: string;
  evidenceIds: FailureAttributionEvidenceIds;
} & {
  layer: 'tool' | 'skill' | 'template' | 'workflow' | 'model';
  verdict: 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';
  explanation: string;
  evidenceIds: FailureAttributionEvidenceIds;
} & {
  layer: 'tool' | 'skill' | 'template' | 'workflow' | 'model';
  verdict: 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';
  explanation: string;
  evidenceIds: FailureAttributionEvidenceIds;
} & {
  layer: 'tool' | 'skill' | 'template' | 'workflow' | 'model';
  verdict: 'primary' | 'contributing' | 'healthy' | 'unknown' | 'not_applicable';
  explanation: string;
  evidenceIds: FailureAttributionEvidenceIds;
};
/**
 * @maxItems 32
 */
export type FailureAttributionEvidenceIds = string[];

export interface TraceDiagnosticResultV1 {
  schemaVersion: 'rag-ime.trace-diagnostic-result.v1';
  summary: string;
  /**
   * @maxItems 16
   */
  hardGates:
    | []
    | [Gate]
    | [Gate, Gate]
    | [Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate, Gate]
    | [
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
        Gate,
      ];
  /**
   * @maxItems 8
   */
  judgeScores:
    | []
    | [Judge]
    | [Judge, Judge]
    | [Judge, Judge, Judge]
    | [Judge, Judge, Judge, Judge]
    | [Judge, Judge, Judge, Judge, Judge]
    | [Judge, Judge, Judge, Judge, Judge, Judge]
    | [Judge, Judge, Judge, Judge, Judge, Judge, Judge]
    | [Judge, Judge, Judge, Judge, Judge, Judge, Judge, Judge];
  /**
   * @maxItems 100
   */
  requirementAssessments?: RequirementAssessment[];
  /**
   * @maxItems 120
   */
  causalLinks?: CausalLink[];
  /**
   * @maxItems 100
   */
  findings: Finding[];
  presentation?: Presentation;
}
export interface Gate {
  gateId: string;
  status: 'passed' | 'failed' | 'unknown';
  reason: string;
  evidenceIds: EvidenceIds;
}
export interface Judge {
  dimensionId: DimensionId;
  score: number | null;
  authority: 'ai_judge_estimate';
  explanation: string;
  evidenceIds: EvidenceIds;
}
export interface RequirementAssessment {
  requirementId: string;
  status: 'satisfied' | 'partial' | 'unsatisfied' | 'unverified';
  owner: string;
  authority: 'ai_judge_estimate';
  evidenceIds: EvidenceIds;
  note: string;
}
export interface CausalLink {
  linkId: string;
  fromEvidenceId: string;
  toEvidenceId: string;
  relation:
    'triggered' | 'delegated' | 'responded_to' | 'returned' | 'verified' | 'caused' | 'recovered';
  authority: 'ai_judge_estimate';
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  explanation: string;
}
export interface Finding {
  findingId: string;
  dimensionId: DimensionId;
  severity: 'critical' | 'high' | 'medium' | 'low';
  observation: string;
  hypothesis: string;
  conclusion: string;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  evidenceIds: EvidenceIds;
  candidateRepair: string;
  verification: string;
}
export interface Presentation {
  headline: string;
  impact: string;
  primaryFindingId: string;
  /**
   * @maxItems 12
   */
  knownFacts:
    | []
    | [PresentationKnownFact]
    | [PresentationKnownFact, PresentationKnownFact]
    | [PresentationKnownFact, PresentationKnownFact, PresentationKnownFact]
    | [PresentationKnownFact, PresentationKnownFact, PresentationKnownFact, PresentationKnownFact]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ]
    | [
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
        PresentationKnownFact,
      ];
  /**
   * @maxItems 12
   */
  evidenceGaps:
    | []
    | [PresentationEvidenceGap]
    | [PresentationEvidenceGap, PresentationEvidenceGap]
    | [PresentationEvidenceGap, PresentationEvidenceGap, PresentationEvidenceGap]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ]
    | [
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
        PresentationEvidenceGap,
      ];
  /**
   * @maxItems 16
   */
  causalNodes:
    | []
    | [PresentationCausalNode]
    | [PresentationCausalNode, PresentationCausalNode]
    | [PresentationCausalNode, PresentationCausalNode, PresentationCausalNode]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ]
    | [
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
        PresentationCausalNode,
      ];
  expectedStageCount: number;
  recordedStageReceiptEvidenceIds: PresentationEvidenceIds;
  failureAttribution?: FailureAttribution;
}
export interface PresentationKnownFact {
  fact: string;
  /**
   * @minItems 1
   * @maxItems 32
   */
  evidenceIds: [string, ...string[]];
}
export interface PresentationEvidenceGap {
  gap: string;
  consequence: string;
  howToObtain: string;
}
export interface PresentationCausalNode {
  label: string;
  detail: string;
  status: 'confirmed' | 'unverified';
  /**
   * @minItems 1
   * @maxItems 32
   */
  evidenceIds: [string, ...string[]];
}
export interface FailureAttribution {
  primaryLayer: 'tool' | 'skill' | 'template' | 'workflow' | 'model' | 'unknown';
  summary: string;
  /**
   * @minItems 5
   * @maxItems 5
   */
  layers: [
    FailureAttributionLayer,
    FailureAttributionLayer,
    FailureAttributionLayer,
    FailureAttributionLayer,
    FailureAttributionLayer,
  ];
}
