import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { AgentBackgroundJobV1 } from '@/contracts/generated/agent-background-job.v1';
import type { AgentWorkflowStateV1 } from '@/contracts/generated/agent-workflow-state.v1';
import { StubControlTransport } from '@/test/stub-control-transport';
import { useAgentLiveStore } from '../state/live-store';
import { AgentStatusPanel } from './AgentStatusPanel';

const sessionId = 'session-status-empty';

beforeEach(() => {
  useAgentLiveStore.setState({ projections: {} });
});

afterEach(() => {
  cleanup();
  useAgentLiveStore.setState({ projections: {} });
});

describe('AgentStatusPanel information architecture', () => {
  it('collapses an empty Session into one natural-language state plus technical details', async () => {
    const transport = panelTransport([]);
    const user = userEvent.setup();
    renderPanel(transport);

    const panel = screen.getByLabelText('当前对话任务中心');
    expect(await within(panel).findByText('这段对话还没有正在执行的任务')).toBeVisible();
    expect(within(panel).getAllByRole('status')).toHaveLength(1);
    for (const name of ['后台任务', '消息队列', '关键步骤', '附件与文件', '产物', '子智能体']) {
      expect(within(panel).queryByRole('button', { name: new RegExp(name) })).not.toBeInTheDocument();
    }
    expect(screen.queryByText('当前没有 Todo')).not.toBeInTheDocument();
    expect(screen.queryByText('当前会话没有后台任务；后台运行命令后会显示在这里。')).not.toBeVisible();
    expect(screen.queryByText('当前会话没有委派任务')).not.toBeInTheDocument();

    const technicalToggle = within(panel).getByRole('button', { name: /技术详情/ });
    expect(technicalToggle).toHaveAttribute('aria-expanded', 'false');
    expect(within(panel).queryByRole('link', { name: /运行记录/ })).not.toBeInTheDocument();

    await user.click(technicalToggle);
    expect(within(panel).getByRole('link', { name: /运行记录/ })).toHaveAttribute(
      'href',
      `#/observability?sessionId=${sessionId}`,
    );
    await user.click(within(panel).getByRole('button', { name: /查看上下文检查/ }));
    await waitFor(() => expect(transport.requests).toContainEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId },
    })));
  });

  it('keeps the background-job transport live while the empty section is visually hidden', async () => {
    const runningJob = backgroundJob();
    const transport = panelTransport([runningJob]);
    renderPanel(transport);

    const panel = screen.getByLabelText('当前对话任务中心');
    expect(await within(panel).findByRole('button', { name: /构建项目/ })).toBeVisible();
    expect(within(panel).getByRole('button', { name: /^后台任务/ })).toBeVisible();
    expect(within(panel).queryByText('这段对话还没有正在执行的任务')).not.toBeInTheDocument();
    expect(transport.requests).toContainEqual(expect.objectContaining({
      pathId: 'agent.session.backgroundJobs.list',
      params: { sessionId },
    }));
  });

  it('keeps the authoritative background-job loading state visible', async () => {
    const pending = deferred<ReturnType<typeof backgroundJobList>>();
    const transport = panelTransport([], () => pending.promise);
    renderPanel(transport);

    const panel = screen.getByLabelText('当前对话任务中心');
    expect(await within(panel).findByText('正在读取后台任务')).toBeVisible();
    expect(within(panel).getByRole('button', { name: /^后台任务/ })).toBeVisible();
    expect(within(panel).queryByText('这段对话还没有正在执行的任务')).not.toBeInTheDocument();

    pending.resolve(backgroundJobList([]));
    expect(await within(panel).findByText('这段对话还没有正在执行的任务')).toBeVisible();
    expect(within(panel).queryByRole('button', { name: /^后台任务/ })).not.toBeInTheDocument();
  });
});

function renderPanel(transport: StubControlTransport) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <AgentStatusPanel
              sessionId={sessionId}
              open
              tools={[]}
              toolCatalogStatus="failed"
              busy={false}
              onCapabilityPreferenceChange={() => {}}
              onCapabilityPolicyRetry={() => {}}
              onCapabilityCatalogRetry={() => {}}
              onClose={() => {}}
            />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function panelTransport(
  jobs: AgentBackgroundJobV1[],
  backgroundJobsResponse: unknown = backgroundJobList(jobs),
): StubControlTransport {
  return new StubControlTransport('native', {
    'agent.session.workflow.get': emptyWorkflow(),
    'agent.session.goal.mutate': emptyWorkflow(),
    'agent.session.backgroundJobs.list': backgroundJobsResponse,
    'agent.subagents.list': { ok: true, items: [] },
    'agent.session.debugContext.get': {
      available: false,
      transient: true,
      context: null,
      telemetry: null,
    },
  });
}

function backgroundJobList(jobs: AgentBackgroundJobV1[]) {
  return {
    schemaVersion: 'rag-ime.agent-background-job-list.v1' as const,
    ok: true as const,
    sessionId,
    items: jobs,
    activeCount: jobs.filter((job) => job.status === 'running').length,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function emptyWorkflow(): AgentWorkflowStateV1 {
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId,
    todo: {
      schemaVersion: 'rag-ime.agent-todo.v1',
      id: `todo:${sessionId}`,
      sessionId,
      revision: 0,
      actor: '',
      updatedAtMs: 0,
      roomLineage: null,
      phases: [],
      counts: { total: 0, pending: 0, inProgress: 0, completed: 0, abandoned: 0 },
    },
    goal: {
      schemaVersion: 'rag-ime.agent-goal.v1',
      sessionId,
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
      budgetExceeded: false,
      completionAudit: null,
      cancellationAudit: null,
      updatedAtMs: 0,
    },
    actGate: {
      allowed: false,
      reason: 'goal_completed',
      message: '当前没有需要执行的任务。',
      todoRevision: 0,
      goalRevision: 0,
    },
  };
}

function backgroundJob(): AgentBackgroundJobV1 {
  return {
    schemaVersion: 'rag-ime.agent-background-job.v1',
    jobId: 'bg_0123456789abcdef0123456789abcdef',
    sessionId,
    label: '构建项目',
    status: 'running',
    command: 'pnpm build',
    commandSha256: 'a'.repeat(64),
    cwd: '/workspace',
    networkAllowed: false,
    maxRunSeconds: 120,
    pid: 42,
    createdAtMs: 100,
    startedAtMs: 110,
    updatedAtMs: 120,
    endedAtMs: 0,
    exitCode: null,
    outputBytes: 0,
    logStartCursor: 0,
    logTruncated: false,
    cancelRequestedAtMs: 0,
    error: '',
    approvalId: 'approval-1',
    causalMetadata: {
      todoId: '',
      todoRevision: 0,
      goalId: '',
      goalRevision: 0,
      turnId: '',
      roomBound: false,
    },
  };
}
