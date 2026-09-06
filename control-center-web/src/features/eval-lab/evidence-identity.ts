import type { EvalLabEvidenceResponse, EvalLabEvidenceRun, EvalLabExperiment } from './api';

function evidenceRefRunId(ref: string): string {
  const value = ref.trim();
  if (!value) return '';
  return (value.split(/[\\/]/u).at(-1) ?? value).replace(/\.json$/u, '');
}

/** Only the evidence adapter's explicit namespaces are aliases. No title,
 * date, family, substring, or model-name matching may bind formal evidence. */
export function canonicalEvidenceRunId(value: string): string {
  let normalized = evidenceRefRunId(value);
  for (const namespace of ['ledger--', 'enterpriseops-local--', 'cloudops--', 'rag--', 'trace--']) {
    if (!normalized.startsWith(namespace)) continue;
    normalized = normalized.slice(namespace.length);
    break;
  }
  return normalized.replace(/\.v1$/u, '');
}

export function evidenceRunMatches(expected: string, actual: string): boolean {
  const identity = canonicalEvidenceRunId(expected);
  return Boolean(identity) && identity === canonicalEvidenceRunId(actual);
}

export function experimentRunBindings(run: EvalLabExperiment['baseline']): string[] {
  return [run.runId, ...run.evidenceRefs.map(evidenceRefRunId)].filter(Boolean);
}

export function evidenceRunMatchesVersion(run: EvalLabEvidenceRun, version: EvalLabExperiment['baseline']): boolean {
  return experimentRunBindings(version).some((binding) => evidenceRunMatches(binding, run.runId));
}

export function matchingEvidenceRuns(catalog: EvalLabEvidenceResponse | undefined, experiment: EvalLabExperiment): EvalLabEvidenceRun[] {
  return catalog?.runs.filter((run) => evidenceRunMatchesVersion(run, experiment.baseline) || evidenceRunMatchesVersion(run, experiment.candidate)) ?? [];
}

export function evidenceTraceIds(runs: readonly EvalLabEvidenceRun[], version: EvalLabExperiment['baseline']): string[] {
  return [...new Set(runs.filter((run) => evidenceRunMatchesVersion(run, version))
    .flatMap((run) => run.environment.traceIds ?? [])
    .map((traceId) => traceId.trim()).filter(Boolean))];
}

export function experimentBaselineTraceIds(runs: readonly EvalLabEvidenceRun[], experiment: EvalLabExperiment): string[] {
  const receipt = experiment.optimizationEvidence?.baselineTrace;
  return [...new Set([...evidenceTraceIds(runs, experiment.baseline),
    ...(receipt?.status === 'bound' && receipt.runId === experiment.baseline.runId ? receipt.traceIds : []),
  ])];
}
