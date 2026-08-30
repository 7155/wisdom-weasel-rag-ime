/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-diagnostic-inspection.v1.json
 */

export interface TraceDiagnosticInspectionV1 {
  schemaVersion: 'rag-ime.trace-diagnostic-inspection.v1';
  generatedAtMs: number;
  /**
   * @minItems 1
   * @maxItems 12
   */
  targets:
    | [Target]
    | [Target, Target]
    | [Target, Target, Target]
    | [Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [Target, Target, Target, Target, Target, Target, Target, Target, Target, Target, Target]
    | [
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
        Target,
      ];
  /**
   * @maxItems 32
   */
  traceIds: string[];
  /**
   * @maxItems 240
   */
  timeline: Timeline[];
  /**
   * @maxItems 512
   */
  evidence: Evidence[];
  requirements?: Requirements;
  environment?: Environment;
  scorecard: Scorecard;
  truncated: {
    timeline: boolean;
    evidence: boolean;
    traceIds: boolean;
  };
}
export interface Target {
  targetKey: string;
  kind: 'session' | 'room' | 'run';
  id: string;
  title: string;
  /**
   * @maxItems 32
   */
  traceIds: string[];
  sourceAvailable: boolean;
}
export interface Timeline {
  evidenceId: string;
  targetKey: string;
  kind: string;
  status: string;
  summary: string;
  sequence: number;
  createdAtMs: number;
  sourceRef: string;
  traceId: string;
}
export interface Evidence {
  evidenceId: string;
  targetKey: string;
  sourceKind: string;
  sourceRef: string;
  status: string;
  summary: string;
  createdAtMs: number;
  traceId: string;
}
export interface Requirements {
  source: 'user_input' | 'work_item' | 'eval' | 'unknown';
  /**
   * @maxItems 100
   */
  items: Requirement[];
  truncated: boolean;
}
export interface Requirement {
  requirementId: string;
  statement: string;
  targetKey: string;
  sourceRef: string;
  /**
   * @minItems 1
   * @maxItems 16
   */
  evidenceIds:
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
      ]
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
        string,
      ]
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
        string,
        string,
      ]
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
        string,
        string,
        string,
      ]
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
        string,
        string,
        string,
        string,
      ];
}
export interface Environment {
  capturedAtMs: number;
  rubricVersion: string;
  /**
   * @minItems 1
   * @maxItems 12
   */
  targets:
    | [EnvironmentTarget]
    | [EnvironmentTarget, EnvironmentTarget]
    | [EnvironmentTarget, EnvironmentTarget, EnvironmentTarget]
    | [EnvironmentTarget, EnvironmentTarget, EnvironmentTarget, EnvironmentTarget]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ]
    | [
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
        EnvironmentTarget,
      ];
  /**
   * @maxItems 32
   */
  limitations: string[];
}
export interface EnvironmentTarget {
  targetKey: string;
  sourceSha256: string;
  modelProfile: string;
  toolProfileVersion: string;
  executionMode: string;
  policyRevision: number | null;
  workspaceScopeSha256: string;
  shellPolicyVersion: string;
  runtimeKind: string;
  runtimeGeneration: number | null;
  /**
   * @maxItems 32
   */
  traceInputFingerprints: string[];
  /**
   * @maxItems 32
   */
  traceStatuses: string[];
}
export interface Scorecard {
  rubricVersion: 'trace-score-v1';
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
   * @minItems 8
   * @maxItems 8
   */
  dimensions: [
    Dimension,
    Dimension,
    Dimension,
    Dimension,
    Dimension,
    Dimension,
    Dimension,
    Dimension,
  ];
  comparison: {
    eligible: boolean;
    status: 'comparable' | 'conditionally_comparable' | 'incomparable' | 'unknown';
    reason: string;
  };
}
export interface Gate {
  gateId: string;
  status: 'passed' | 'failed' | 'unknown';
  /**
   * @maxItems 128
   */
  evidenceIds: string[];
  reason: string;
}
export interface Dimension {
  dimensionId:
    | 'task_completion'
    | 'evidence_diagnosis'
    | 'tool_runtime'
    | 'context'
    | 'room_collaboration'
    | 'memory_rag'
    | 'efficiency'
    | 'repair_quality';
  title: string;
  applicability: 'measured' | 'partial' | 'not_applicable' | 'unavailable' | 'unknown';
  authority: 'deterministic' | 'ground_truth' | 'mixed';
  score: number | null;
  scoreMax: 100;
  /**
   * @maxItems 32
   */
  metrics: Metric[];
  /**
   * @maxItems 256
   */
  evidenceIds: string[];
  note: string;
}
export interface Metric {
  metricId: string;
  label: string;
  value: number | null;
  unit: string;
  authority: 'deterministic' | 'ground_truth' | 'ai_judge_estimate';
  /**
   * @maxItems 128
   */
  evidenceIds: string[];
  note: string;
}
