import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { AgentWorkflowStateV1 } from '@/contracts/generated/agent-workflow-state.v1';
import { StubControlTransport } from '@/test/stub-control-transport';
import { AgentWorkflowPanel } from './AgentWorkflowPanel';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AgentWorkflowPanel', () => {
  it('shows a real read error and retries instead of presenting an empty fallback as current state', async () => {
    let attempts = 0;
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': () => {
        attempts += 1;
        if (attempts === 1) throw new Error('runtime offline');
        return workflowState();
      },
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport);

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取实时 Plan 与 Goal');
    expect(screen.queryByRole('region', { name: 'Plan 审阅与执行门禁' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('region', { name: 'Plan 审阅与执行门禁' })).toBeVisible();
    expect(attempts).toBe(2);
  });

  it('requires confirmation before cancelling a Plan or clearing a Goal', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': workflowState(),
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': workflowState(),
    });
    const confirm = vi.spyOn(window, 'confirm')
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    const user = userEvent.setup();
    renderWorkflow(transport);

    await screen.findByText('完成 Agent 工作流');
    await user.click(screen.getByRole('button', { name: '取消执行' }));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: '取消执行' }));
    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(1));

    await user.click(screen.getByRole('button', { name: '清除' }));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: '清除' }));
    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(1));
    expect(confirm).toHaveBeenCalledTimes(4);
  });
});

function renderWorkflow(transport: StubControlTransport) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <AgentWorkflowPanel sessionId="session-workflow" />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function workflowState(): AgentWorkflowStateV1 {
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId: 'session-workflow',
    plan: {
      schemaVersion: 'rag-ime.agent-plan.v2',
      id: 'plan:workflow',
      sessionId: 'session-workflow',
      revision: 2,
      title: '完成 Agent 工作流',
      status: 'approved',
      actor: 'agent',
      note: '',
      updatedAtMs: 100,
      editable: false,
      actApproved: true,
      items: [{
        id: 'plan:item:1',
        title: '完成前端接入',
        status: 'in_progress',
        position: 1,
        sequence: 1,
        updatedAtMs: 100,
      }],
      counts: { total: 1, pending: 0, inProgress: 1, completed: 0 },
    },
    goal: {
      schemaVersion: 'rag-ime.agent-goal.v1',
      sessionId: 'session-workflow',
      configured: true,
      goalId: 'goal:workflow',
      revision: 1,
      objective: '完成工作流并验证',
      status: 'active',
      budget: { tokenLimit: 10_000, timeLimitMs: 60_000 },
      usage: { tokens: 1_000, elapsedMs: 10_000 },
      remaining: { tokens: 9_000, timeMs: 50_000 },
      budgetExceeded: false,
      completionAudit: null,
      updatedAtMs: 100,
    },
    actGate: { allowed: true, reason: 'approved', message: '可以执行。' },
  };
}
