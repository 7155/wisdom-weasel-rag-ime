import { describe, expect, it } from 'vitest';
import { buildExperimentDisplayMetrics } from './experiment-display-metrics';
import { projectExperimentResultSummary } from './ExperimentResultSummary';
import { pawSelfbootEfficiency, pawSelfbootQuality, pawSelfbootReliability } from './paw-selfboot-metrics';

const observation = {
  vertical: 'paw-selfboot', evaluationKind: 'memory', dataset: { caseCount: 4 },
  baseline: { metrics: {} }, candidate: { metrics: { taskSuccessCount: 4, taskCount: 4, recallPassed: 2, recallTotal: 2, staleExposureCount: 0, totalTokens: 10746, providerCalls: 4, estimatedApiCostUsd: .00197072 } },
};

describe('PAW selfboot evidence display', () => {
  it('labels a verified observation without claiming a paired improvement', () => {
    const result = projectExperimentResultSummary({ comparison: { decision: 'observation', decisionReason: '本轮通过。', metricDeltas: [] } }, buildExperimentDisplayMetrics(observation));
    expect(result.title).toBe('本轮验证已完成');
    expect(result.description).toBe('展示本轮验收；未提供配对基线，不声明改善。');
    expect(result.metrics.every((m) => m.change === 'unverified')).toBe(true);
  });

  it('keeps a missing baseline distinct from zero and does not invent a gain', () => {
    const metrics = buildExperimentDisplayMetrics(observation);
    expect(metrics.map((m) => m.after?.display)).toEqual(['4/4', '2/2', '$0.001971']);
    expect(metrics.every((m) => m.before === undefined && m.direction === undefined)).toBe(true);
    expect(pawSelfbootQuality(observation)).toContain('未提供基线 → 4/4');
    expect(pawSelfbootReliability(observation)).toContain('过期或错误信息暴露数 0');
    expect(pawSelfbootEfficiency(observation)).toContain('模型调用 4');
    expect(pawSelfbootEfficiency(observation)).toContain('10,746');
  });

  it('does not turn implementation checks into independent completed tasks or claim untested recovery', () => {
    const source = { ...observation, candidate: { metrics: { taskSuccessCount: 0, taskCount: 1, verifierPassCount: 6, verifierCount: 20 } } };
    const result = buildExperimentDisplayMetrics(source);
    expect(result.map((m) => m.after?.display)).toEqual(['0/1', '6/20']);
    expect(result.some((m) => m.id === 'resumePassed')).toBe(false);
  });

  it('compares only an explicitly paired observation and preserves unchanged quality', () => {
    const source = { ...observation, baseline: { metrics: { taskSuccessCount: 1, taskCount: 1, estimatedApiCostUsd: .00203172 } },
      candidate: { metrics: { taskSuccessCount: 1, taskCount: 1, estimatedApiCostUsd: .0015298 } }, frozenControls: [{ name: 'comparison_scope', value: 'paired' }] };
    const result = buildExperimentDisplayMetrics(source);
    expect(result[0]).toMatchObject({ before: { display: '1/1' }, after: { display: '1/1' }, direction: 'higher' });
    expect(result[1].direction).toBe('lower');
    expect(buildExperimentDisplayMetrics({ ...source, frozenControls: [] }).every((m) => m.direction === undefined)).toBe(true);
  });
});
