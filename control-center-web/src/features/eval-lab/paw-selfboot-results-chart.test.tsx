import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import type { EvalLabExperiment } from './api';
import { PawSelfbootResultsChart } from './PawSelfbootResultsChart';

afterEach(cleanup);
it('shows exact counts, missing baseline and a working usage view without inventing recovery', async () => {
  const experiment = { vertical: 'paw-selfboot', dataset: { caseCount: 1 }, frozenControls: [],
    baseline: { metrics: {} }, candidate: { metrics: { taskCount: 1, taskSuccessCount: 0, verifierCount: 20, verifierPassCount: 6, totalTokens: 108210, providerCalls: 12 } },
  } as unknown as EvalLabExperiment;
  render(<PawSelfbootResultsChart experiment={experiment} />);
  expect(screen.getByRole('img', { name: '完整任务通过，本轮方案 0/1' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: '实现与业务验收，本轮方案 6/20' })).toBeInTheDocument();
  expect(screen.getAllByText('未提供')).toHaveLength(2);
  expect(screen.queryByRole('button', { name: '取消与恢复' })).toBeNull();
  await userEvent.setup().click(screen.getByRole('button', { name: '用量与费用' }));
  expect(screen.getByRole('img', { name: '完整 turn tokens，本轮方案 108,210' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: '模型调用，本轮方案 12' })).toBeInTheDocument();
  expect(screen.queryByText('任务估算费用')).toBeNull();
});

it('separates restart observations from failed completion and exposes incomplete budget usage', async () => {
  const counts = { taskCount: 1, taskSuccessCount: 0, verifierCount: 20, verifierPassCount: 16, deliveryCount: 4, deliveryPassed: 0 };
  const experiment = { vertical: 'paw-selfboot', dataset: { caseCount: 1 },
    frozenControls: [{ name: 'cost_completeness', value: 'partial_after_budget_stop' }],
    baseline: { metrics: { ...counts, continuationEntered: 0, observedTokens: 316246, knownEstimatedApiCostUsd: .02190944 } },
    candidate: { metrics: { ...counts, continuationEntered: 1, restartPreserved: 1, observedTokens: 310758, knownEstimatedApiCostUsd: .03120328 } },
  } as unknown as EvalLabExperiment;
  render(<PawSelfbootResultsChart experiment={experiment} />);
  expect(screen.getByRole('img', { name: '完整任务通过，本轮方案 0/1' })).toBeInTheDocument();
  expect(screen.getByText('尚未进入重启后的接续阶段')).toBeInTheDocument();
  expect(screen.getByText('已进入重启后的接续阶段；产物保留已观察')).toBeInTheDocument();
  expect(screen.queryByText('重启接续通过')).toBeNull();
  expect(screen.getByText(/预算中断；只展示已记录的用量和费用/)).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: '用量与费用' }));
  expect(screen.getByRole('img', { name: '已知估算费用，本轮方案 $0.031203' })).toBeInTheDocument();
  expect(screen.getByRole('img', { name: '已观察 tokens，本轮方案 310,758' })).toBeInTheDocument();
  expect(screen.queryByText('任务估算费用')).toBeNull();
  expect(screen.getByText(/未记录的在途成本未知，不能作为总额或节省/)).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: '取消与恢复' }));
  expect(screen.getByText('已进入重启后的接续阶段；产物保留已观察')).toBeInTheDocument();
  expect(screen.queryByText(/进程内 owner 重建/)).toBeNull();
});
