import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ExperimentArtifactVisual, ExperimentTableVisual, MetricComparison, RawArtifactData } from './ExperimentArtifactVisual';
import type { JsonValue } from './types';

afterEach(cleanup);
const snapshot: JsonValue = { schemaVersion: 'paw.lab-imported-experiments.v1', executionPerformed: false, experiments: [
  { experimentId: 'a', title: '起始方案', supersededBy: 'c', comparison: { decision: 'reject' }, factors: [{ name: 'Prompt', before: 'v1', after: 'v2', reason: '补充证据引用规则' }] },
  { experimentId: 'b', title: '无关实验', comparison: { decision: 'inconclusive' } },
  { experimentId: 'c', title: '引用修复', comparison: { decision: 'keep', decisionReason: '通过固定验证集' }, baseline: { metrics: { agentSuccessRate: 0, apiCostUsd: null } }, candidate: { metrics: { agentSuccessRate: .75, apiCostUsd: .001 } }, dataset: { caseCount: 4, split: 'validation' } },
] };

describe('structured Lab results', () => {
  it('uses explicit lineage, supports structure inspection and preserves raw data behind disclosure', () => {
    render(<><ExperimentArtifactVisual content={snapshot} /><RawArtifactData content={snapshot} /></>);
    expect(screen.getByText(/本次导入没有重新执行/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '从基线到候选，改了什么' })).toBeInTheDocument();
    expect(screen.getByText('补充证据引用规则')).toBeInTheDocument();
    const timeline = screen.getByRole('navigation', { name: '实验演进' });
    const next = within(timeline).getByRole('button', { name: /引用修复/ });
    expect(next).toHaveTextContent('承接：起始方案');
    expect(next).not.toHaveTextContent('承接：无关实验');
    fireEvent.click(next);
    fireEvent.click(screen.getByRole('button', { name: /指标与判定/ }));
    expect(screen.getByLabelText('基线：0%')).toBeInTheDocument();
    expect(screen.getByLabelText('候选：75%')).toBeInTheDocument();
    expect(screen.getByLabelText('基线：未记录')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /评测条件/ }));
    expect(screen.getByText('validation')).toBeInTheDocument();
    expect(screen.getByText('原始数据').closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText('原始数据').closest('details')?.querySelector('pre')?.textContent).toContain('"executionPerformed": false');
  });
  it('does not coerce null or numeric strings, or hide real zeroes', () => {
    render(<MetricComparison baseline={{ passRate: 0, latencyMs: null, tokens: '10' }} candidate={{ passRate: .5, latencyMs: 20, tokens: 5 }} />);
    expect(screen.getByLabelText('基线：0%')).toBeInTheDocument();
    expect(screen.getAllByLabelText('基线：未记录')).toHaveLength(2);
    expect(screen.getByLabelText('候选：20')).toBeInTheDocument();
  });
  it('distinguishes actual experiment results from imported history', () => {
    render(<ExperimentArtifactVisual content={{ schemaVersion: 'paw.lab-experiment-steps.v1', executionPerformed: true, experiments: [{ experimentId: 'run-1', title: '实际对照' }] }} />);
    expect(screen.getByText('实验结果 · 1 条记录')).toBeInTheDocument();
    expect(screen.queryByText(/历史实验/)).not.toBeInTheDocument();
    expect(screen.queryByText(/导入没有重新执行/)).not.toBeInTheDocument();
  });
  it('scopes paired table charts to the chosen experiment', () => {
    render(<ExperimentTableVisual content={{ columns: ['experiment', 'metric', 'baseline', 'candidate'].map((key) => ({ key, label: key })), rows: [
      { experiment: '实验 A', metric: 'passRate', baseline: 0, candidate: .5 },
      { experiment: '实验 B', metric: 'passRate', baseline: .75, candidate: 1 },
    ] }} />);
    expect(screen.getByLabelText('候选：50%')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: '实验 B' } });
    expect(screen.queryByLabelText('候选：50%')).not.toBeInTheDocument();
    expect(screen.getByLabelText('候选：100%')).toBeInTheDocument();
  });
  it('renders project steps as saved observations, not live execution claims', () => {
    render(<ExperimentArtifactVisual content={{ schemaVersion: 'paw.lab-project-progress.v1', observedAt: '2026-09-12T13:00:00Z', steps: [
      { id: 'materials', title: '接入材料', state: 'completed', summary: '已读取三份示例材料', evidenceRefs: ['materials:v1'] },
      { id: 'eval', title: '准备评测', state: 'blocked', summary: '等待通过标准', dependsOn: ['materials'], nextAction: '选择业务通过标准' },
    ] }} />);
    expect(screen.getByText(/Agent 保存的步骤快照/)).toBeInTheDocument();
    expect(screen.getByText('需要补充')).toBeInTheDocument();
    expect(screen.getByText('下一步：选择业务通过标准')).toBeInTheDocument();
  });
  it('falls back to a readable tree for unknown shapes and safe text for HTML-looking values', () => {
    const { container } = render(<ExperimentArtifactVisual content={{ title: '<img src=x onerror=alert(1)>', status: null, cases: [{ passed: false }] }} />);
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('false')).toBeInTheDocument();
  });
});
