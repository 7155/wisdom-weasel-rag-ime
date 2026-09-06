import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { buildTraceAuditReportModel, type TraceAuditFailureLayer } from '@/features/trace-agent/report-model';
import type { EvalLabEvidenceRun, EvalLabEvidenceTask, EvalLabExperiment, EvalLabRun, EvalLabTask } from '../api';
import { evidenceRunMatchesVersion, evidenceTraceIds, experimentBaselineTraceIds } from '../evidence-identity';

export interface OptimizationWorkbenchModel {
  attribution?: {
    layers: Array<TraceAuditFailureLayer & { evidenceAliases: string[] }>;
    reportId: string;
    summary: string;
  };
  comparison?: { after: string; before: string; caseId: string };
  decision: { label: 'Keep' | 'Reject' | '待定'; reason: string };
  failure?: {
    actual: string;
    caseId: string;
    failedGates: string[];
    expected: string;
    runId: string;
    terminal: string;
  };
  frozenControls: Array<{ name: string; reason: string; value: string }>;
  historical: boolean;
  identity: {
    baselineRunId: string;
    baselineTraceIds: string[];
    candidateRunId: string;
    evidenceRefs: string[];
    experimentId: string;
    traceIds: string[];
  };
  changes: Array<{ after: string; before: string; layer: string; reason: string }>;
}

export function buildOptimizationWorkbenchModel(input: {
  evidenceRuns: readonly EvalLabEvidenceRun[];
  experiment: EvalLabExperiment;
  linkedRuns: readonly EvalLabRun[];
  traceReport?: TraceDiagnosticReportV1;
}): OptimizationWorkbenchModel {
  const { evidenceRuns, experiment, linkedRuns, traceReport } = input;
  const scoredCases = experiment.optimizationEvidence?.caseComparisons ?? [];
  const scoredCaseIds = new Set(scoredCases.map((item) => item.caseId));
  const baseline = linkedRuns.find((run) => run.runId === experiment.baseline.runId);
  const failedTask = baseline?.tasks.find((task) => taskFailed(task) && (!scoredCaseIds.size || scoredCaseIds.has(task.explanation?.caseId ?? '')));
  const baselineEvidence = evidenceRuns.find((run) => evidenceRunMatchesVersion(run, experiment.baseline));
  const failedEvidenceTask = baselineEvidence?.tasks.find((task) => evidenceTaskFailed(task) && (!scoredCaseIds.size || scoredCaseIds.has(task.taskLabel.trim())));
  const failedScoredCase = scoredCases.find((item) => item.before.status === 'failed');
  const explicitCaseId = failedTask?.explanation?.caseId?.trim()
    || failedEvidenceTask?.taskLabel.trim()
    || failedScoredCase?.caseId
    || '';
  const baselineTraceIds = experimentBaselineTraceIds(evidenceRuns, experiment);
  const traceIds = unique([...baselineTraceIds, ...evidenceTraceIds(evidenceRuns, experiment.candidate)]);
  const failure = failedTask
    ? {
        actual: failedTask.explanation?.agentOutcome.normalizedSummary || '实际输出未记录',
        caseId: explicitCaseId || `${baseline?.runId ?? experiment.baseline.runId}#${failedTask.taskIndex}`,
        failedGates: failedTask.explanation?.acceptance.items
          .filter((item) => item.status !== 'pass')
          .map((item) => `${item.label}：${item.explanation}`) ?? [],
        expected: failedTask.explanation?.businessRequest.normalizedText || '任务要求未记录',
        runId: baseline?.runId ?? experiment.baseline.runId,
        terminal: failedTask.terminalEvent || '终态未记录',
      }
    : failedEvidenceTask
      ? {
          actual: '实际输出未记录',
          caseId: explicitCaseId || `${experiment.baseline.runId}#${failedEvidenceTask.taskIndex}`,
          failedGates: evidenceFailureGates(failedEvidenceTask),
          expected: '任务要求未记录',
          runId: baselineEvidence?.runId ?? experiment.baseline.runId,
          terminal: failedEvidenceTask.terminalEvent || '终态未记录',
        }
      : failedScoredCase ? {
          actual: '该 Case 的评分未通过；原始输出可从所在批次报告核对。',
          caseId: failedScoredCase.caseId,
          failedGates: [],
          expected: '沿用本实验冻结的任务与验收标准。',
          runId: experiment.baseline.runId,
          terminal: '未记录独立的单 Case 终态',
        } : undefined;
  const attribution = traceReportIsExactlyLinked(traceReport, experiment.baseline.runId, baselineTraceIds)
    ? receiptAttribution(traceReport)
    : undefined;
  const comparison = explicitCaseId && experiment.baseline.runId !== experiment.candidate.runId
    ? exactComparison(experiment, linkedRuns, explicitCaseId)
    : undefined;
  const normalizedDecision = experiment.comparison.decision.trim().toLowerCase();

  return {
    attribution,
    comparison,
    decision: {
      label: normalizedDecision === 'keep' ? 'Keep' : normalizedDecision === 'reject' ? 'Reject' : '待定',
      reason: experiment.comparison.decisionReason,
    },
    failure,
    frozenControls: experiment.frozenControls.map((control) => ({ ...control })),
    historical: experiment.projectionState === 'history',
    identity: {
      baselineRunId: experiment.baseline.runId,
      baselineTraceIds,
      candidateRunId: experiment.candidate.runId,
      evidenceRefs: unique([...experiment.baseline.evidenceRefs, ...experiment.candidate.evidenceRefs]),
      experimentId: experiment.experimentId,
      traceIds,
    },
    changes: experiment.factors.map((factor) => ({
      after: factor.after,
      before: factor.before,
      layer: factor.name,
      reason: factor.reason,
    })),
  };
}

function taskFailed(task: EvalLabTask): boolean {
  if (task.taskSucceeded === false) return true;
  return typeof task.verifierPassed === 'number'
    && typeof task.verifierTotal === 'number'
    && task.verifierPassed < task.verifierTotal;
}

function evidenceTaskFailed(task: EvalLabEvidenceTask): boolean {
  if (task.taskSucceeded === false) return true;
  if (task.failedVerifierNames?.length || task.failedVerifierIndexes?.length || task.toolFailures > 0) return true;
  return typeof task.verifierPassed === 'number'
    && typeof task.verifierTotal === 'number'
    && task.verifierPassed < task.verifierTotal;
}

function evidenceFailureGates(task: EvalLabEvidenceTask): string[] {
  if (task.failedVerifierNames?.length) return [...task.failedVerifierNames];
  if (task.failedVerifierIndexes?.length) return task.failedVerifierIndexes.map((index) => `Verifier #${index}`);
  if (task.toolFailures > 0) return [`Tool 失败 ${task.toolFailures}`];
  return [];
}

function traceReportIsExactlyLinked(
  report: TraceDiagnosticReportV1 | undefined,
  baselineRunId: string,
  baselineTraceIds: readonly string[],
): report is TraceDiagnosticReportV1 {
  if (!report || report.status !== 'completed' || !report.result) return false;
  if (report.targets.some((target) => target.kind === 'run' && target.id === baselineRunId)) return true;
  const expectedTraceIds = new Set(baselineTraceIds);
  return report.traceIds.some((traceId) => expectedTraceIds.has(traceId));
}

function receiptAttribution(report: TraceDiagnosticReportV1): OptimizationWorkbenchModel['attribution'] {
  const model = buildTraceAuditReportModel(report);
  return {
    layers: model.failureAttribution.layers.map((layer) => ({
      ...layer,
      evidenceAliases: layer.evidenceIds.map((evidenceId) => model.evidenceAliases[evidenceId] ?? evidenceId),
    })),
    reportId: report.reportId,
    summary: model.failureAttribution.summary,
  };
}

function exactComparison(
  experiment: EvalLabExperiment,
  linkedRuns: readonly EvalLabRun[],
  caseId: string,
): OptimizationWorkbenchModel['comparison'] {
  const recorded = experiment.comparison.outputComparisons?.find((item) => item.caseId === caseId);
  if (recorded) return { after: recorded.after, before: recorded.before, caseId };

  const before = linkedRuns.find((run) => run.runId === experiment.baseline.runId)
    ?.tasks.find((task) => task.explanation?.caseId === caseId)?.explanation?.agentOutcome.normalizedSummary;
  const after = linkedRuns.find((run) => run.runId === experiment.candidate.runId)
    ?.tasks.find((task) => task.explanation?.caseId === caseId)?.explanation?.agentOutcome.normalizedSummary;
  return before && after ? { after, before, caseId } : undefined;
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}
