import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
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
  it('renders the authoritative phased Todo and Goal without a second lifecycle', async () => {
    const state = workflowState();
    const transport = transportFor(state);

    renderWorkflow(transport);

    const todo = await screen.findByRole('region', { name: 'Todo' });
    expect(todo).toHaveTextContent('1/3 已收束');
    expect(todo).toHaveTextContent('实现');
    expect(todo).toHaveTextContent('验证');
    expect(todo).toHaveTextContent('完成前端状态同步');
    expect(todo).toHaveTextContent('进行中');
    expect(screen.getByRole('region', { name: '长期目标' })).toHaveTextContent('完成 Agent 工作流并验证');
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(0);
  });

  it('keeps a blocked Todo open and shows its recovery reason', async () => {
    const state = workflowState();
    state.todo.phases[1]!.tasks[0] = {
      content: '等待用户选择',
      status: 'blocked',
      reason: '等待用户决定兼容性范围',
    };
    state.todo.counts.pending = 0;
    state.todo.counts.blocked = 1;

    renderWorkflow(transportFor(state));

    const todo = await screen.findByRole('region', { name: 'Todo' });
    expect(todo).toHaveTextContent('等待用户选择');
    expect(todo).toHaveTextContent('已阻塞');
    expect(todo).toHaveTextContent('等待用户决定兼容性范围');
    expect(todo).toHaveTextContent('1/3 已收束');
  });

  it('shows a read error and retries instead of presenting an empty Todo as current state', async () => {
    let attempts = 0;
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': () => {
        attempts += 1;
        if (attempts === 1) throw new Error('runtime offline');
        return workflowState();
      },
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport);

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取最新 Todo 与长期目标');
    expect(screen.queryByRole('region', { name: 'Todo' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('region', { name: 'Todo' })).toBeVisible();
    expect(attempts).toBe(2);
  });

  it('treats an absent participant workflow as Room-managed instead of a sync failure', async () => {
    const absent = Object.assign(new Error('workflow not found'), { status: 404 });
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': () => {
        throw absent;
      },
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport);

    expect(await screen.findByText(
      '当前没有 Todo。如果这段工作来自协作空间，分工、公开进度和最终回复会继续在那里显示。',
    )).toBeVisible();
    expect(screen.getByRole('status')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps a live Todo visible while the persisted workflow is temporarily absent', async () => {
    const fallback = workflowState();
    const absent = Object.assign(new Error('workflow not found'), { status: 404 });
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': () => {
        throw absent;
      },
      'agent.session.goal.mutate': fallback,
    });
    renderWorkflow(transport, { fallbackTodo: fallback.todo });

    const todo = await screen.findByRole('region', { name: 'Todo' });
    expect(todo).toHaveTextContent('完成前端状态同步');
    expect(screen.queryByText(/当前没有 Todo。如果这段工作来自协作空间/)).not.toBeInTheDocument();
  });

  it('projects a newer live Todo immediately instead of waiting for the workflow poll', async () => {
    const queried = workflowState();
    const live = workflowState();
    live.todo.revision = queried.todo.revision + 1;
    live.todo.updatedAtMs = queried.todo.updatedAtMs + 1;
    live.todo.phases[0]!.tasks[1]!.content = '立即显示最新任务';
    const transport = transportFor(queried);

    renderWorkflow(transport, { fallbackTodo: live.todo });

    expect(await screen.findByText('立即显示最新任务')).toBeVisible();
    expect(screen.queryByText('完成前端状态同步')).not.toBeInTheDocument();
  });

  it('keeps Goal cancellation auditable and requires an explicit reason', async () => {
    const state = workflowState();
    const transport = transportFor(state);
    const user = userEvent.setup();
    renderWorkflow(transport);

    await user.click(await screen.findByRole('button', { name: '取消目标' }));
    const confirm = screen.getByRole('button', { name: '确认取消目标' });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText('目标取消原因'), '用户不再需要这个目标');
    await user.click(confirm);

    await waitFor(() => expect(
      transport.requests.find((request) => request.pathId === 'agent.session.goal.mutate'),
    ).toMatchObject({
      params: { sessionId: 'session-workflow' },
      body: {
        action: 'cancel',
        expectedRevision: 1,
        reason: '用户不再需要这个目标',
      },
    }));
  });

  it('sends the explicit Goal resume contract', async () => {
    const state = workflowState();
    state.goal.status = 'paused';
    state.actGate = {
      allowed: false,
      reason: 'goal_paused',
      message: 'Goal 已暂停。',
      todoRevision: state.todo.revision,
      goalRevision: state.goal.revision,
    };
    const transport = transportFor(state);
    renderWorkflow(transport);

    await userEvent.click(await screen.findByRole('button', { name: '恢复' }));

    await waitFor(() => expect(
      transport.requests.find((request) => request.pathId === 'agent.session.goal.mutate'),
    ).toMatchObject({
      params: { sessionId: 'session-workflow' },
      body: { action: 'resume', expectedRevision: 1 },
    }));
  });
});

function renderWorkflow(
  transport: StubControlTransport,
  props: Partial<ComponentProps<typeof AgentWorkflowPanel>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <AgentWorkflowPanel sessionId="session-workflow" {...props} />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function transportFor(state: AgentWorkflowStateV1): StubControlTransport {
  return new StubControlTransport('mock', {
    'agent.session.workflow.get': state,
    'agent.session.goal.mutate': state,
  });
}

function workflowState(): AgentWorkflowStateV1 {
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId: 'session-workflow',
    todo: {
      schemaVersion: 'rag-ime.agent-todo.v1',
      id: 'todo:session-workflow',
      sessionId: 'session-workflow',
      revision: 2,
      actor: 'agent',
      updatedAtMs: 100,
      roomLineage: null,
      phases: [
        {
          name: '实现',
          tasks: [
            { content: '核对 Todo 与 Goal 契约', status: 'completed' },
            { content: '完成前端状态同步', status: 'in_progress' },
          ],
        },
        {
          name: '验证',
          tasks: [{ content: '核对真实 Provider 载荷', status: 'pending' }],
        },
      ],
      counts: { total: 3, pending: 1, inProgress: 1, completed: 1, abandoned: 0 },
    },
    goal: {
      schemaVersion: 'rag-ime.agent-goal.v1',
      sessionId: 'session-workflow',
      configured: true,
      goalId: 'goal:session-workflow',
      revision: 1,
      objective: '完成 Agent 工作流并验证',
      successCriteria: 'Todo 全部收束',
      evidenceExpectations: ['聚焦测试结果'],
      status: 'active',
      budget: { tokenLimit: 10_000, timeLimitMs: 3_600_000 },
      usage: { tokens: 1_000, elapsedMs: 60_000 },
      remaining: { tokens: 9_000, timeMs: 3_540_000 },
      budgetExceeded: false,
      completionAudit: null,
      cancellationAudit: null,
      updatedAtMs: 100,
    },
    actGate: {
      allowed: true,
      reason: 'user_execution_request',
      message: '用户已请求执行。',
      todoRevision: 2,
      goalRevision: 1,
    },
  };
}
