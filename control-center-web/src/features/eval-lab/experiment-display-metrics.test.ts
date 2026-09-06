import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildExperimentDisplayMetrics, type ExperimentMetricSource } from './experiment-display-metrics';

const ledger = JSON.parse(readFileSync(resolve(process.cwd(), '../eval/interview-metrics/agent-experiments.v1.json'), 'utf8')) as {
  experiments: (ExperimentMetricSource & { id: string })[];
};
function recorded(id: string): ExperimentMetricSource {
  const experiment = ledger.experiments.find((item) => item.id === id);
  if (!experiment) throw new Error(`Missing recorded experiment: ${id}`);
  return structuredClone(experiment);
}

describe('four scenario display metrics from the checked-in run ledger', () => {
  it.each([
    ['enterpriseops-csm.luna-prompt-adaptation-r7.v1', [['3/3', '3/3'], ['31/31', '31/31'], ['$1.7112', '$0.0729']]],
    ['enterprise-rag.luna-prompt-v4-standard-r6.v1', [['3/4', '4/4'], ['7/9', '9/9'], ['$2.1706', '$0.1029']]],
    ['cloudops.luna-owner-mechanism-prompt-r5.v1', [['10/12', '11/12'], ['98/99', '130/130'], ['$4.5682', '$0.2761']]],
    ['memory.maintenance-luna-model-only-r1.v1', [['5/5', '5/5'], ['4/4', '4/4'], ['$0.2691', '$0.0108']]],
  ])('projects explicit before/after populations for %s', (id, values) => {
    const metrics = buildExperimentDisplayMetrics(recorded(id as string));
    expect(metrics.map((metric) => [metric.before?.display, metric.after?.display])).toEqual(values);
    expect(metrics.every((metric) => metric.source)).toBe(true);
    expect(metrics[2].label).toBe('API 估算成本');
    expect(metrics[2].note).toContain('非 Provider 账单');
  });

  it('preserves missing denominators and zero numerators without inventing a population', () => {
    const experiment = recorded('memory.maintenance-luna-model-only-r1.v1');
    const before = { ...experiment.baseline.metrics, curationPassed: 0 };
    const after = { ...experiment.candidate.metrics };
    delete after.curationCases;
    const metrics = buildExperimentDisplayMetrics({ ...experiment, baseline: { metrics: before }, candidate: { metrics: after } });
    expect(metrics[0].before?.display).toBe('0/5');
    expect(metrics[0].after).toBeUndefined();
    expect(metrics[0].direction).toBeUndefined();
    expect(metrics[0].note).toContain('分母未提供');
  });

  it('does not round fractional CloudOps outcomes into invented successful cases', () => {
    const experiment = recorded('cloudops.luna-owner-mechanism-prompt-r5.v1');
    const metrics = buildExperimentDisplayMetrics({ ...experiment, baseline: { metrics: { ...experiment.baseline.metrics, jra: .88 } } });
    expect(metrics[0].before?.display).toBe('88.0%');
    expect(metrics[0].source).toContain('dataset.caseCount=12');
    expect(buildExperimentDisplayMetrics({ ...experiment, dataset: {} })[0].before).toBeUndefined();
  });

  it('keeps early retrieval metrics as recorded aggregates rather than forcing a cost claim', () => {
    const metrics = buildExperimentDisplayMetrics({ ...recorded('enterprise-rag.retrieval-selection.v1'), evaluationKind: 'rag_retrieval' });
    expect(metrics.map((metric) => metric.label)).toEqual(['Recall@10', 'MRR', 'nDCG@10']);
    expect(metrics.map((metric) => metric.after?.display)).toEqual(['0.9554', '0.8672', '0.8872']);
    expect(metrics.every((metric) => metric.source?.includes('不能反推命中题数'))).toBe(true);
  });

  it('shows unavailable costs without using token totals as money or inferring scope', () => {
    const experiment = recorded('memory.maintenance-luna-model-only-r1.v1');
    const result = buildExperimentDisplayMetrics({ ...experiment, frozenControls: [], baseline: { metrics: {} }, candidate: { metrics: { apiCostUsd: 0, totalTokens: 99 } } });
    expect(result[2].before).toBeUndefined();
    expect(result[2].after?.display).toBe('$0.0000');
    expect(result[2].direction).toBeUndefined();
    expect(result[2].source).toContain('成本范围：未提供');
  });
});
