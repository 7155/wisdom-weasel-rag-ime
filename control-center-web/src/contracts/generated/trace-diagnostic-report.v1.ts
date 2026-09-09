/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/trace-diagnostic-report.v1.json
 */

export interface TraceDiagnosticReportV1 {
  intent?: OptimizationIntent;
  optimizationProjectId?: string;
  optimization?: Optimization;
  distillation?: Distillation;
  schemaVersion: 'rag-ime.trace-diagnostic-report.v1';
  reportId: string;
  revision: number;
  status: 'generating' | 'completed' | 'failed';
  title: string;
  diagnosticSessionId: string;
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
  inspectionSha256: string;
  inspection: {
    [k: string]: unknown;
  };
  result: {
    [k: string]: unknown;
  } | null;
  repairLifecycle?: RepairLifecycle;
  failureReason: string;
  createdAtMs: number;
  updatedAtMs: number;
}
export interface OptimizationIntent {
  mode: 'improve' | 'distill';
  scopeMode: 'all' | 'selected';
  /**
   * @minItems 1
   * @maxItems 5
   */
  focusAreas:
    | ['tool' | 'skill' | 'prompt' | 'workflow' | 'model']
    | [
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
      ]
    | [
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
      ]
    | [
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
      ]
    | [
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
        'tool' | 'skill' | 'prompt' | 'workflow' | 'model',
      ];
  objective: string;
}
export interface Optimization {
  schemaVersion: 'rag-ime.trace-optimization.v1';
  /**
   * @minItems 0
   * @maxItems 128
   */
  candidates: OptimizationCandidate[];
  /**
   * @minItems 0
   * @maxItems 512
   */
  comparisons: OptimizationComparison[];
  /**
   * @minItems 0
   * @maxItems 512
   */
  applications: OptimizationApplication[];
  executions?: OptimizationExecution[];
  /**
   * @maxItems 512
   */
  pendingApplications?: OptimizationPendingApplication[];
}
export interface OptimizationCandidate {
  targetKind: 'tool' | 'skill' | 'prompt' | 'workflow' | 'model';
  targetRef: string;
  parentVersionRef: string;
  candidateVersionRef: string;
  /**
   * @minItems 0
   * @maxItems 128
   */
  findingIds: string[];
  /**
   * @minItems 1
   * @maxItems 128
   */
  evidenceIds: [string, ...string[]];
  /**
   * @minItems 0
   * @maxItems 128
   */
  historicalPatternRefs: string[];
  summary: string;
  expectedEffect: string;
  actualDiffRef: string;
  comparisonContract: OptimizationContract;
  candidateId: string;
  reportId: string;
  optimizationProjectId: string;
  comparisonContractSha256: string;
  intent: OptimizationIntent;
  executionStatus: 'not_started';
  diffStatus: 'verified' | 'unverified';
  /**
   * @minItems 0
   * @maxItems 6
   */
  availableActions:
    | []
    | ['run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback']
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ];
  /**
   * @minItems 0
   * @maxItems 6
   */
  supportedActions:
    | []
    | ['run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback']
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ]
    | [
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
        'run_candidate' | 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback',
      ];
  actualDiff?: {
    before: string;
    after: string;
    unifiedDiff: string;
  };
  createdAtMs: number;
  contentSha256: string;
}
export interface OptimizationContract {
  caseSetRef: string;
  /**
   * @minItems 1
   * @maxItems 128
   */
  caseIds: [string, ...string[]];
  controls: {
    [k: string]: string;
  };
  /**
   * @minItems 1
   * @maxItems 5
   */
  declaredChanges:
    | [OptimizationChange]
    | [OptimizationChange, OptimizationChange]
    | [OptimizationChange, OptimizationChange, OptimizationChange]
    | [OptimizationChange, OptimizationChange, OptimizationChange, OptimizationChange]
    | [
        OptimizationChange,
        OptimizationChange,
        OptimizationChange,
        OptimizationChange,
        OptimizationChange,
      ];
  /**
   * @minItems 1
   * @maxItems 16
   */
  qualityGates:
    | [OptimizationQualityGate]
    | [OptimizationQualityGate, OptimizationQualityGate]
    | [OptimizationQualityGate, OptimizationQualityGate, OptimizationQualityGate]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ]
    | [
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
        OptimizationQualityGate,
      ];
  costMetric: '' | 'totalCost';
}
export interface OptimizationChange {
  kind: 'tool' | 'skill' | 'prompt' | 'workflow' | 'model';
  targetRef: string;
  beforeVersionRef: string;
  afterVersionRef: string;
}
export interface OptimizationQualityGate {
  metricId: string;
  minimum: number;
}
export interface OptimizationComparison {
  comparisonId: string;
  reportId: string;
  candidateId: string;
  optimizationProjectId: string;
  baselineTrialId: string;
  candidateTrialId: string;
  executionStatus: 'not_started' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  effectStatus: 'improved' | 'neutral' | 'regressed' | 'not_run' | 'unverified';
  decision: 'kept' | 'rejected' | 'needs_validation';
  comparable: boolean;
  reason: string;
  /**
   * @minItems 0
   * @maxItems 17
   */
  pairedMetrics:
    | []
    | [OptimizationMetric]
    | [OptimizationMetric, OptimizationMetric]
    | [OptimizationMetric, OptimizationMetric, OptimizationMetric]
    | [OptimizationMetric, OptimizationMetric, OptimizationMetric, OptimizationMetric]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ]
    | [
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
        OptimizationMetric,
      ];
  /**
   * @minItems 0
   * @maxItems 128
   */
  cases: OptimizationCase[];
  /**
   * @minItems 0
   * @maxItems 128
   */
  regressions: string[];
  usage: {
    baselineCost: number | null;
    candidateCost: number | null;
    currency: string;
    complete: boolean;
  };
  /**
   * @minItems 0
   * @maxItems 1024
   */
  evidenceRefs: string[];
  actualLoadedVersions: {
    baseline: {
      [k: string]: string;
    };
    candidate: {
      [k: string]: string;
    };
  };
  createdAtMs: number;
  contentSha256: string;
  validationScope: 'unverified' | 'frozen_local_task_fixture' | 'registered_task_execution';
}
export interface OptimizationMetric {
  metricId: string;
  kind: 'quality' | 'cost';
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  baselineNumerator: number | null;
  baselineDenominator: number | null;
  candidateNumerator: number | null;
  candidateDenominator: number | null;
}
export interface OptimizationCase {
  caseId: string;
  baseline: number | null;
  candidate: number | null;
  regressed: boolean;
}
export interface OptimizationApplication {
  applicationId: string;
  reportId: string;
  candidateId: string;
  comparisonId: string;
  action: 'install' | 'replace' | 'apply' | 'keep_original' | 'rollback';
  status: 'kept_original' | 'applied' | 'failed' | 'rolled_back' | 'interrupted';
  receiptRef: string;
  targetRef: string;
  versionRef: string;
  createdAtMs: number;
  contentSha256: string;
}
export interface OptimizationExecution {
  requestId: string;
  candidateId: string;
  baselineJobId: string;
  candidateJobId: string;
  baselineState:
    | 'queued'
    | 'preparing'
    | 'running'
    | 'cancelling'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'interrupted'
    | 'unavailable';
  candidateState:
    | 'queued'
    | 'preparing'
    | 'running'
    | 'cancelling'
    | 'completed'
    | 'failed'
    | 'cancelled'
    | 'interrupted'
    | 'unavailable';
  baselineSummary: string;
  candidateSummary: string;
  comparisonId: string;
  createdAtMs: number;
}
export interface OptimizationPendingApplication {
  candidateId: string;
  comparisonId: string;
  receiptRef: string;
  versionRef: string;
  action: 'install' | 'replace' | 'apply' | 'rollback';
  status: 'applying' | 'interrupted';
  createdAtMs: number;
}
export interface Distillation {
  /**
   * @maxItems 24
   */
  items: {
    suggestionId: string;
    outcome: 'update_existing' | 'new_skill' | 'new_tool' | 'experience_only' | 'no_change';
    requestedOutcome:
      'update_existing' | 'new_skill' | 'new_tool' | 'experience_only' | 'no_change';
    title: string;
    reason: string;
    proposedChange: string;
    /**
     * @maxItems 128
     */
    evidenceIds: string[];
    /**
     * @maxItems 24
     */
    sourceRefs: {
      evidenceId: string;
      sourceRef: string;
      /**
       * @maxItems 12
       */
      targetKeys:
        | []
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
          ];
      sourceSha256: string;
    }[];
    /**
     * @maxItems 128
     */
    existingCapabilityIds: string[];
    /**
     * @maxItems 32
     */
    capabilityNeeds: string[];
    validationStatus: 'candidate_draft' | 'not_applicable';
    /**
     * @maxItems 128
     */
    candidateIds: string[];
  }[];
  authority: 'analysis_proposal';
  inventorySha256: string;
  sourceInspectionSha256: string;
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
export interface RepairLifecycle {
  authorization: RepairAuthorization;
  verification: RepairVerification;
}
export interface RepairAuthorization {
  state: 'authorized' | 'declined' | 'blocked' | 'expired';
  authorizationKind: 'repair_handoff';
  writeAuthority:
    'per_action_required' | 'model_arbitrated_full_trust' | 'auto_approved_full_trust';
  authorizationId: string;
  findingId: string;
  sourceScope: string;
  sourceTraceId: string;
  failureRef: string;
  repairSessionId: string;
  authorizedAtMs: number;
}
export interface RepairVerification {
  state: 'pending' | 'verified' | 'failed';
  repairReceiptId: string;
  repairTraceId: string;
  evalRunId: string;
  verificationReceiptId?: string;
  replayCaseId?: string;
  decision?: '' | 'kept' | 'rejected';
  testStatus: '' | 'passed' | 'failed' | 'blocked';
  sandboxStatus: '' | 'passed' | 'not_required' | 'blocked';
  sandboxedTestCount: number;
  verifiedAtMs: number;
  comparison: Comparison;
}
export interface Comparison {
  status: 'pending' | 'incomparable' | 'failed' | 'unknown';
  reason: string;
  sourceStatus: string;
  repairStatus: string;
  sourceFingerprint: string;
  repairFingerprint: string;
  beforeMetrics: {
    [k: string]: number;
  };
  afterMetrics: {
    [k: string]: number;
  };
  deltas: {
    [k: string]: number;
  };
}
