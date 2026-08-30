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
  findings: Finding[];
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
