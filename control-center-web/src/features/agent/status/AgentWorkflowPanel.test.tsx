import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { AgentWorkflowStateV1 } from '@/contracts/generated/agent-workflow-state.v1';
import type { ControlRequest } from '@/platform/transport';
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

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取最新计划与长期目标');
    expect(screen.queryByRole('region', { name: '计划审阅与执行' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('region', { name: '计划审阅与执行' })).toBeVisible();
    expect(attempts).toBe(2);
  });

  it('keeps a complete Session event projection visible when the workflow read fails', async () => {
    const fallback = workflowState();
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': () => {
        throw new Error('runtime offline');
      },
      'agent.session.plan.mutate': fallback,
      'agent.session.goal.mutate': fallback,
    });
    renderWorkflow(transport, {
      fallbackPlan: fallback.plan,
      fallbackGoal: fallback.goal,
      fallbackActGate: fallback.actGate,
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '实时读取失败，当前继续显示这段对话已经确认的计划与目标。',
    );
    expect(screen.getByText('完成工作流并验证')).toBeVisible();
    expect(screen.getByRole('button', { name: '暂停' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '重新读取' })).toBeEnabled();
  });

  it('distinguishes auditable cancellation from destructive Goal deletion', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': workflowState(),
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': workflowState(),
    });
    const user = userEvent.setup();
    renderWorkflow(transport);

    await screen.findByText('完成 Agent 工作流');
    await user.click(screen.getByRole('button', { name: '取消执行' }));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: '确认取消执行' }));
    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(1));
    expect(transport.requests.find((request) => request.pathId === 'agent.session.plan.mutate')?.body).toEqual({
      action: 'cancel',
      expectedRevision: 2,
    });

    await user.click(screen.getByRole('button', { name: '取消目标' }));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(0);
    expect(screen.getByRole('button', { name: '确认取消目标' })).toBeDisabled();
    await user.type(screen.getByLabelText('目标取消原因'), '目标优先级已经改变');
    await user.click(screen.getByRole('button', { name: '确认取消目标' }));
    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(1));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')[0]?.body).toEqual({
      action: 'cancel',
      expectedRevision: 1,
      reason: '目标优先级已经改变',
    });

    await user.click(screen.getByRole('button', { name: '删除目标' }));
    expect(screen.getByText('永久删除目标、预算和审计记录？')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(2));
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')[1]?.body).toEqual({
      action: 'clear',
      expectedRevision: 1,
    });
  });

  it('requires review feedback before returning a Plan to draft', async () => {
    const state = workflowState();
    state.plan.status = 'review';
    state.plan.actApproved = false;
    state.actGate = {
      allowed: false,
      reason: 'plan_not_approved',
      message: '计划已提交，等待批准。',
      planRevision: state.plan.revision,
      goalRevision: state.goal.revision,
    };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': state,
    });
    const user = userEvent.setup();
    renderWorkflow(transport);

    await user.click(await screen.findByRole('button', { name: '退回修改' }));
    expect(screen.getByRole('button', { name: '发送退回意见' })).toBeDisabled();
    await user.type(screen.getByLabelText('计划退回意见'), '补充失败恢复和验收步骤');
    await user.click(screen.getByRole('button', { name: '发送退回意见' }));

    await waitFor(() => expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(1));
    expect(transport.requests.find((request) => request.pathId === 'agent.session.plan.mutate')?.body).toEqual({
      action: 'return_to_draft',
      expectedRevision: 2,
      note: '补充失败恢复和验收步骤',
    });
  });

  it('offers Plan completion only after every item is complete', async () => {
    const state = workflowState();
    state.plan.items[0] = { ...state.plan.items[0]!, status: 'completed' };
    state.plan.counts = { total: 1, pending: 0, inProgress: 0, completed: 1 };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': state,
    });
    const user = userEvent.setup();
    renderWorkflow(transport);

    await user.click(await screen.findByRole('button', { name: '验收并完成' }));
    await waitFor(() => expect(transport.requests.find((request) => request.pathId === 'agent.session.plan.mutate')?.body).toEqual({
      action: 'complete',
      expectedRevision: 2,
    }));
  });

  it('keeps execution start bound to the first governed workspace write', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': workflowState(),
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport);

    await screen.findByText('完成 Agent 工作流');
    expect(screen.queryByRole('button', { name: '开始执行' })).not.toBeInTheDocument();
    expect(screen.getByText('首个经治理的工作区写操作成功后，计划会自动进入执行中。')).toBeVisible();
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.plan.mutate')).toHaveLength(0);
  });

  it('projects a newer live Plan immediately instead of waiting for the workflow poll', async () => {
    const queried = workflowState();
    queried.plan = {
      ...queried.plan,
      revision: 1,
      status: 'draft',
      title: '执行计划',
      updatedAtMs: 100,
      items: [],
      counts: { total: 0, pending: 0, inProgress: 0, completed: 0 },
    };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': queried,
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport, {
      fallbackPlan: {
        ...workflowState().plan,
        revision: 2,
        status: 'review',
        title: '回顾近期进展',
        updatedAtMs: 200,
        actApproved: false,
      },
      fallbackActGate: {
        allowed: true,
        reason: 'user_execution_request',
        message: '用户已请求执行，可在已授权工作区内继续；高风险操作仍需逐项审批。',
        planRevision: 2,
        goalRevision: 1,
      },
    });

    expect(await screen.findByText('回顾近期进展')).toBeInTheDocument();
    expect(screen.getAllByText('待审阅')).toHaveLength(2);
    expect(screen.getByRole('button', { name: '批准计划' })).toBeEnabled();
    expect(screen.getByText('用户请求已允许继续')).toBeVisible();
    expect(screen.getByText(/高风险操作仍需逐项审批/)).toBeVisible();
    expect(screen.queryByLabelText('计划标题')).not.toBeInTheDocument();
  });

  it('directs unconfigured Goals through chat without presenting a manual setup form', async () => {
    const state = workflowState();
    state.goal = {
      ...state.goal,
      configured: false,
      goalId: '',
      revision: 0,
      objective: '',
      successCriteria: '',
      evidenceExpectations: [],
      status: 'cleared',
      budget: { tokenLimit: null, timeLimitMs: null },
      usage: { tokens: 0, elapsedMs: 0 },
      remaining: { tokens: null, timeMs: null },
      updatedAtMs: 0,
    };
    state.actGate = {
      allowed: false,
      reason: 'plan_not_approved',
      message: '目标尚未设置。',
      planRevision: state.plan.revision,
      goalRevision: 0,
    };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': workflowState(),
    });
    renderWorkflow(transport);

    expect(await screen.findByText('直接在对话中描述你想完成的事')).toBeVisible();
    expect(screen.getByText(/伙伴会逐项询问目标、交付物、验收方式与禁区/)).toBeVisible();
    expect(screen.queryByRole('textbox', { name: '长期目标' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: '目标完成标准' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /确认任务|确认并启用目标|引导设置目标/ })).not.toBeInTheDocument();
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(0);
  });

  it('keeps the authoritative Goal completion outcome and evidence visible', async () => {
    const state = workflowState();
    state.goal = {
      ...state.goal,
      status: 'completed',
      completionAudit: {
        auditId: 'goal-audit-1',
        summary: '完成所有验收',
        evidence: [
          { kind: 'artifact', summary: '浏览器记录', reference: 'receipt:browser' },
          { kind: 'test', summary: '后端测试', reference: 'python3 -m unittest' },
        ],
        completedBy: 'runtime',
        createdAtMs: 100,
      },
    };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': state,
    });
    renderWorkflow(transport);

    expect(await screen.findByText('完成所有验收')).toBeVisible();
    expect(screen.getByText('浏览器记录 · receipt:browser')).toBeVisible();
    expect(screen.getByText('后端测试 · python3 -m unittest')).toBeVisible();
    expect(screen.getByText('已完成')).toBeVisible();
    expect(screen.queryByRole('button', { name: '确认完成' })).not.toBeInTheDocument();
    expect(transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate')).toHaveLength(0);
  });

  it('sends the explicit Plan approval contract', async () => {
    const state = workflowState();
    state.plan.status = 'review';
    state.plan.actApproved = false;
    state.actGate = {
      allowed: false,
      reason: 'plan_not_approved',
      message: '计划已提交，等待批准。',
      planRevision: state.plan.revision,
      goalRevision: state.goal.revision,
    };
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': state,
    });
    renderWorkflow(transport);

    await userEvent.click(await screen.findByRole('button', { name: '批准计划' }));

    await waitFor(() => expect(
      transport.requests.find((request) => request.pathId === 'agent.session.plan.mutate'),
    ).toMatchObject({
      params: { sessionId: 'session-workflow' },
      body: { action: 'approve', expectedRevision: 2 },
    }));
  });

  it('sends the explicit Goal resume contract', async () => {
    const state = workflowState();
    state.goal.status = 'paused';
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': state,
    });
    renderWorkflow(transport);

    await userEvent.click(await screen.findByRole('button', { name: '恢复' }));

    await waitFor(() => expect(
      transport.requests.find((request) => request.pathId === 'agent.session.goal.mutate'),
    ).toMatchObject({
      params: { sessionId: 'session-workflow' },
      body: { action: 'resume', expectedRevision: 1 },
    }));
  });

  it('keeps an in-flight mutation owned by the Session that submitted it', async () => {
    const sessionA = workflowStateFor('session-a', '目标 A');
    const sessionB = workflowStateFor('session-b', '目标 B');
    let resolveMutation!: (value: AgentWorkflowStateV1) => void;
    const pendingMutation = new Promise<AgentWorkflowStateV1>((resolve) => {
      resolveMutation = resolve;
    });
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': (request: ControlRequest) => (
        request.params?.sessionId === 'session-a' ? sessionA : sessionB
      ),
      'agent.session.plan.mutate': sessionA,
      'agent.session.goal.mutate': pendingMutation,
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const tree = (sessionId: string) => (
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <AgentWorkflowPanel sessionId={sessionId} />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    );
    const view = render(tree('session-a'));

    await screen.findByText('目标 A');
    await userEvent.click(screen.getByRole('button', { name: '暂停' }));
    await waitFor(() => expect(
      transport.requests.filter((request) => request.pathId === 'agent.session.goal.mutate'),
    ).toHaveLength(1));

    view.rerender(tree('session-b'));
    await screen.findByText('目标 B');
    expect(screen.getByRole('button', { name: '暂停' })).toBeEnabled();

    resolveMutation(sessionA);
    await waitFor(() => expect(
      client.getQueryData<AgentWorkflowStateV1>(['agent', 'workflow', 'session-a']),
    ).toMatchObject({ sessionId: 'session-a' }));
    expect(client.getQueryData<AgentWorkflowStateV1>(['agent', 'workflow', 'session-b']))
      .toMatchObject({ sessionId: 'session-b' });
  });

  it('rejects a mutation response owned by another Session', async () => {
    const state = workflowStateFor('session-workflow', '当前目标');
    const foreign = workflowStateFor('session-foreign', '其他目标');
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': state,
      'agent.session.plan.mutate': state,
      'agent.session.goal.mutate': foreign,
    });
    const user = userEvent.setup();
    renderWorkflow(transport);

    await screen.findByText('当前目标');
    await user.click(screen.getByRole('button', { name: '暂停' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '返回的是另一段对话的结果，当前对话没有更新。',
    );
    expect(screen.getByText('当前目标')).toBeVisible();
    expect(screen.queryByText('其他目标')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '暂停' })).toBeEnabled();
  });

  it('renders a localized stale Goal error without leaving an unhandled mutation rejection', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.workflow.get': workflowState(),
      'agent.session.plan.mutate': workflowState(),
      'agent.session.goal.mutate': () => {
        throw new Error('agent goal changed; refresh before saving');
      },
    });
    const user = userEvent.setup();
    renderWorkflow(transport);

    await screen.findByText('完成工作流并验证');
    await user.click(screen.getByRole('button', { name: '暂停' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '目标已由其他操作更新，当前已显示最新状态，请重试。',
    );
    expect(screen.getByRole('button', { name: '暂停' })).toBeEnabled();
  });
});

function renderWorkflow(
  transport: StubControlTransport,
  props: Partial<ComponentProps<typeof AgentWorkflowPanel>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <AgentWorkflowPanel sessionId="session-workflow" {...props} />
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
      successCriteria: '所有工作流路径均已验收',
      evidenceExpectations: ['测试回执', '浏览器记录'],
      budget: { tokenLimit: 10_000, timeLimitMs: 60_000 },
      usage: { tokens: 1_000, elapsedMs: 10_000 },
      remaining: { tokens: 9_000, timeMs: 50_000 },
      budgetExceeded: false,
      completionAudit: null,
      cancellationAudit: null,
      updatedAtMs: 100,
    },
    actGate: {
      allowed: true,
      reason: 'approved',
      message: '可以执行。',
      planRevision: 2,
      goalRevision: 1,
    },
  };
}

function workflowStateFor(sessionId: string, objective: string): AgentWorkflowStateV1 {
  const state = workflowState();
  state.sessionId = sessionId;
  state.plan.sessionId = sessionId;
  state.plan.id = `plan:${sessionId}`;
  state.goal.sessionId = sessionId;
  state.goal.goalId = `goal:${sessionId}`;
  state.goal.objective = objective;
  return state;
}
