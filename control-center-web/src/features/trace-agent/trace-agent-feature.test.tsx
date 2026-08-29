import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { ControlRequest } from '@/platform/transport';
import { TRACE_AGENT_SKILL_REF, TraceAgentFeature } from './index';
import { buildTraceAgentHandoffRoute } from './handoff';

afterEach(cleanup);

describe('TraceAgentFeature', () => {
  it('preselects an incoming failure handoff and includes its exact envelope in the diagnostic prompt', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport();
    const route = buildTraceAgentHandoffRoute({
      kind: 'memory',
      entityId: 'memory-maintenance:job-1',
      title: '记忆整理失败',
      summary: '读取或保存失败',
      error: 'invalid Pi Runtime Host JSONL: Unterminated string',
      failureRef: 'memory-maintenance:job-1',
      sourceRoute: '/memory?view=activity',
      refs: { phase: 'managed_memory_model' },
      occurredAtMs: 123,
    });
    const routes: string[] = [];
    renderFeature(transport, routes, [route]);

    const selected = await screen.findByRole('region', { name: '已选择诊断对象' });
    expect(selected).toHaveTextContent('记忆整理失败');
    expect(screen.getByTestId('trace-agent-incoming-handoff')).toHaveTextContent('memory-maintenance:job-1');
    await user.click(within(selected).getByRole('button', { name: '回到原位置' }));
    expect(routes).toContain('/memory?view=activity');

    await user.click(screen.getByRole('button', { name: '开始诊断' }));
    const promptRequest = await waitFor(() => {
      const request = transport.requests.find(({ request }) => request.pathId === 'agent.session.prompt')?.request;
      expect(request).toBeTruthy();
      return request!;
    });
    const prompt = String((promptRequest.body as Record<string, unknown> | undefined)?.message);
    expect(prompt).toContain('paw.trace-agent-handoff.v1');
    expect(prompt).toContain('memory-maintenance:job-1');
    expect(prompt).toContain('Unterminated string');
    expect(prompt).toContain('managed_memory_model');
  });

  it('keeps a handoff-only input usable without inventing a runId or fetching a canonical snapshot', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport();
    const route = buildTraceAgentHandoffRoute({
      kind: 'memory',
      entityId: 'memory-maintenance:job-only',
      title: '记忆维护失败',
      summary: '只有失败交接包，没有可用的 Session、Room 或 Run。',
      error: '读取或保存失败',
      failureRef: 'memory-maintenance:job-only',
      sourceRoute: '/memory?view=activity',
      refs: { phase: 'managed_memory_model' },
      occurredAtMs: 123,
    });
    renderFeature(transport, [], [route]);

    const selected = await screen.findByRole('region', { name: '已选择诊断对象' });
    expect(selected).toHaveTextContent('仅结构化交接包');
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'observability.snapshot' && request.query?.runId === 'memory-maintenance:job-only'
    ))).toBe(false));

    await user.click(screen.getByRole('button', { name: '开始诊断' }));
    const promptRequest = await waitFor(() => {
      const request = transport.requests.find(({ request }) => request.pathId === 'agent.session.prompt')?.request;
      expect(request).toBeTruthy();
      return request!;
    });
    expect(String((promptRequest.body as Record<string, unknown> | undefined)?.message)).toContain('没有可用的 canonical Session / Room / Run');
  });

  it('uses the newly selected target Trace after leaving an incoming handoff', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport();
    const route = buildTraceAgentHandoffRoute({
      kind: 'session',
      entityId: 'session-handoff',
      title: '旧交接对象',
      summary: '从旧对象进入 Trace Agent。',
      sessionId: 'session-handoff',
      traceId: 'trace:handoff',
      sourceRoute: '/agent?session=session-handoff',
      occurredAtMs: 123,
    });
    renderFeature(transport, [], [route]);

    await user.click(await screen.findByRole('option', { name: /失败的对话/ }));
    await user.click(screen.getByRole('button', { name: '开始诊断' }));

    const promptRequest = await waitFor(() => {
      const request = transport.requests.find(({ request }) => request.pathId === 'agent.session.prompt')?.request;
      expect(request).toBeTruthy();
      return request!;
    });
    const prompt = String((promptRequest.body as Record<string, unknown> | undefined)?.message);
    expect(prompt).toContain('trace:source');
    expect(prompt).not.toContain('trace:handoff');
  });

  it('shows transcript and Trace failure evidence, then starts a read-only Skill-bound diagnostic Session', async () => {
    const user = userEvent.setup();
    const routes: string[] = [];
    const transport = traceAgentTransport();
    renderFeature(transport, routes);

    const target = await screen.findByRole('option', { name: /失败的对话/ });
    expect(within(target).getByText(/write\/edit validation error/)).toBeInTheDocument();
    const evidence = await screen.findByRole('region', { name: '已读取的失败证据' });
    await waitFor(() => expect(evidence).toHaveTextContent('write/edit validation error'));
    const timeline = await screen.findByRole('region', { name: '原始对话时间线' });
    expect(timeline).toHaveAttribute('data-scrollable', 'true');
    expect(timeline).toHaveTextContent('用户 · 检查当前实现');
    expect(timeline).toHaveTextContent('思考摘要 · 核对失败证据');
    expect(timeline).toHaveTextContent('工具开始 · 读取目标文件');
    expect(timeline).toHaveTextContent('工具完成 · 读取目标文件完成');
    expect(timeline).toHaveTextContent('助手 · 发现写入版本冲突');
    expect(within(timeline).getAllByTestId('trace-agent-timeline-entry').map((entry) => entry.getAttribute('data-kind'))).toEqual([
      'user',
      'reasoning',
      'tool_started',
      'tool_finished',
      'assistant',
    ]);

    await user.click(screen.getByRole('button', { name: '开始诊断' }));
    await screen.findByRole('region', { name: 'Trace 诊断报告' });

    const createRequest = transport.requests.find(({ request }) => request.pathId === 'agent.sessions.create')?.request;
    expect(createRequest?.body).toMatchObject({
      mode: 'assistant',
      executionMode: 'read_only',
      toolProfileVersion: 'control-center-v1',
      workspaceRoots: [],
    });
    const modeRequest = transport.requests.find(({ request }) => request.pathId === 'agent.session.mode.update')?.request;
    expect(modeRequest?.body).toMatchObject({
      mode: 'assistant',
      executionMode: 'read_only',
      projectContextEnabled: false,
      piSkillsEnabled: true,
      codexSkillsEnabled: false,
    });
    const promptRequest = transport.requests.find(({ request }) => request.pathId === 'agent.session.prompt')?.request;
    expect(promptRequest?.body).toMatchObject({ delivery: 'prompt' });
    expect(String((promptRequest?.body as Record<string, unknown> | undefined)?.message)).toContain(TRACE_AGENT_SKILL_REF);
    expect(String((promptRequest?.body as Record<string, unknown> | undefined)?.message)).toContain('session-source');

    const report = screen.getByRole('region', { name: 'Trace 诊断报告' });
    await user.click(within(report).getByRole('button', { name: '查看关联 Trace' }));
    await user.click(within(report).getByRole('button', { name: '打开诊断 Agent 对话' }));
    expect(routes).toEqual([
      '/observability?traceId=trace%3Asource',
      '/agent?session=agent%3Atrace-diagnostic',
    ]);
  });

  it('switches between Room and recorded runs while preserving precise source deep links', async () => {
    const user = userEvent.setup();
    const routes: string[] = [];
    const transport = traceAgentTransport();
    renderFeature(transport, routes);

    await user.click(await screen.findByRole('tab', { name: 'Room 协作' }));
    const room = await screen.findByRole('option', { name: /失败的协作/ });
    await user.click(room);
    const selected = await screen.findByRole('region', { name: '已选择诊断对象' });
    const timeline = within(selected).getByRole('region', { name: '原始对话时间线' });
    expect(timeline).toHaveTextContent('用户 · Room 用户问题');
    expect(timeline).toHaveTextContent('思考摘要 · 协作者核对分工');
    expect(timeline).toHaveTextContent('工具开始 · 读取 WorkItem');
    expect(timeline).toHaveTextContent('工具完成 · WorkItem 读取完成');
    expect(timeline).toHaveTextContent('助手 · Room 已发布进展');
    expect(within(selected).getByRole('heading', { name: '失败的协作' })).toBeInTheDocument();
    await user.click(within(selected).getByRole('button', { name: '打开原对话' }));
    expect(routes).toContain('/rooms?room=room-source');

    await user.click(screen.getByRole('tab', { name: '运行记录' }));
    const run = await screen.findByRole('option', { name: /运行失败/ });
    await user.click(run);
    const runSelected = await screen.findByRole('region', { name: '已选择诊断对象' });
    await user.click(within(runSelected).getByRole('button', { name: '打开运行记录' }));
    expect(routes).toContain('/observability?runId=run-source');
  });

  it('keeps the selected-object diagnostic action visible and reports its binding scope', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport();
    renderFeature(transport, []);

    await user.click(await screen.findByRole('tab', { name: 'Room 协作' }));
    const selected = await screen.findByRole('region', { name: '已选择诊断对象' });
    const action = screen.getByTestId('trace-agent-diagnostic-action');
    expect(action).toHaveAttribute('data-sticky', 'true');
    expect(action).toHaveTextContent('当前 Room');
    expect(action).toHaveTextContent('全部行星');
    expect(action).toHaveTextContent('WorkItems');

    await user.click(within(action).getByRole('button', { name: '开始诊断' }));
    await waitFor(() => expect(action).toHaveAttribute('data-state', 'complete'));
    expect(within(action).getByRole('button', { name: '诊断已启动' })).toBeDisabled();
    expect(within(action).getByRole('button', { name: '打开诊断 Agent 对话' })).toBeInTheDocument();
  });

  it('hands a completed diagnostic to an ordinary per-action Agent and can return to Trace', async () => {
    const user = userEvent.setup();
    const routes: string[] = [];
    const transport = traceAgentTransport();
    renderFeature(transport, routes);

    await user.click(await screen.findByRole('button', { name: '开始诊断' }));
    const report = await screen.findByRole('region', { name: 'Trace 诊断报告' });
    await user.click(within(report).getByRole('button', { name: '交给 Agent 修复' }));

    await waitFor(() => expect(screen.getByTestId('trace-agent-repair-ready')).toBeInTheDocument());
    expect(within(report).getByRole('button', { name: '修复 Agent 已就绪' })).toBeDisabled();

    const createRequests = transport.requests.filter(({ request }) => request.pathId === 'agent.sessions.create');
    expect(createRequests).toHaveLength(2);
    expect(createRequests[1]?.request.body).toMatchObject({
      mode: 'coordinator',
      executionMode: 'per_action',
      toolProfileVersion: 'control-center-v1',
      workspaceRoots: ['/workspace/paw'],
    });
    const modeRequests = transport.requests.filter(({ request }) => request.pathId === 'agent.session.mode.update');
    expect(modeRequests[1]?.request.body).toMatchObject({
      mode: 'coordinator',
      executionMode: 'per_action',
      projectContextEnabled: true,
      piSkillsEnabled: true,
      codexSkillsEnabled: false,
    });
    const promptRequests = transport.requests.filter(({ request }) => request.pathId === 'agent.session.prompt');
    expect(promptRequests).toHaveLength(2);
    const repairPrompt = String((promptRequests[1]?.request.body as Record<string, unknown> | undefined)?.message);
    expect(repairPrompt).toContain('session-source');
    expect(repairPrompt).toContain('agent:trace-diagnostic');
    expect(repairPrompt).toContain('trace:source');
    expect(repairPrompt).toContain('write/edit validation error: target file changed');
    expect(repairPrompt).toContain('per_action 授权');

    await user.click(within(report).getByRole('button', { name: '打开修复 Session' }));
    expect(routes).toContain('/agent?session=agent%3Atrace-repair');

    await user.click(within(report).getByRole('button', { name: '回到 Trace 重跑诊断' }));
    expect(routes).toContain('/observability?traceId=trace%3Asource');
    expect(screen.getByRole('button', { name: '开始诊断' })).toBeInTheDocument();
  });

  it('reads the repair Session Trace before Eval and shows both trace identities in the persisted receipt', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport();
    renderFeature(transport, []);

    await user.click(await screen.findByRole('button', { name: '开始诊断' }));
    const report = await screen.findByRole('region', { name: 'Trace 诊断报告' });
    await user.click(within(report).getByRole('button', { name: '交给 Agent 修复' }));
    await waitFor(() => expect(screen.getByTestId('trace-agent-repair-ready')).toBeInTheDocument());

    await user.click(within(report).getByRole('button', { name: '修复后运行 Eval 复检' }));

    await waitFor(() => expect(screen.getByTestId('trace-agent-eval-receipt')).toBeInTheDocument());
    const receipt = screen.getByTestId('trace-agent-eval-receipt');
    expect(receipt).toHaveTextContent('eval:trace-agent:recheck:repair');
    expect(receipt).toHaveTextContent('诊断 Trace：trace:source');
    expect(receipt).toHaveTextContent('修复 Trace：trace:repair');
    const repairSnapshotRequest = transport.requests.find(({ request }) => (
      request.pathId === 'observability.snapshot'
      && request.query?.sessionId === 'agent:trace-repair'
    ));
    expect(repairSnapshotRequest?.request.query).toMatchObject({ sessionId: 'agent:trace-repair', limit: 100 });
    const traceRequest = transport.requests.find(({ request }) => request.pathId === 'observability.trace.get');
    expect(traceRequest?.request.params).toEqual({ traceId: 'trace:repair' });
    const evalRequest = transport.requests.find(({ request }) => request.pathId === 'observability.evals.evidence.run');
    expect(evalRequest?.request.body).toMatchObject({
      schemaVersion: 'rag-ime.observability-evidence-eval-request.v1',
      traceId: 'trace:repair',
      requiredEvidenceIds: ['knowledge:repair'],
      truthKind: 'human',
    });
  });

  it('does not evaluate the diagnostic Trace until the repair Session has a completed Trace', async () => {
    const user = userEvent.setup();
    const transport = traceAgentTransport({ repairTrace: false });
    renderFeature(transport, []);

    await user.click(await screen.findByRole('button', { name: '开始诊断' }));
    const report = await screen.findByRole('region', { name: 'Trace 诊断报告' });
    await user.click(within(report).getByRole('button', { name: '交给 Agent 修复' }));
    await waitFor(() => expect(screen.getByTestId('trace-agent-repair-ready')).toBeInTheDocument());

    await user.click(within(report).getByRole('button', { name: '修复后运行 Eval 复检' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('请先完成修复后再复检'));
    expect(transport.requests.some(({ request }) => request.pathId === 'observability.evals.evidence.run')).toBe(false);
    expect(transport.requests.some(({ request }) => request.pathId === 'observability.trace.get')).toBe(false);
  });

  it('keeps more than sixty canonical events reachable in order and expands messages beyond the summary', async () => {
    const user = userEvent.setup();
    const longMessage = `完整消息开头 ${'原始内容'.repeat(50)} 完整消息结尾`;
    const sourceSnapshot = {
      ok: true,
      sessionId: 'session-source',
      status: 'idle',
      items: [{
        id: 'message-long',
        role: 'assistant',
        status: 'completed',
        timelineSequence: 66,
        createdAtMs: 66,
        blocks: [{ id: 'text-long', type: 'text', status: 'completed', data: { text: longMessage } }],
      }],
      liveEvents: Array.from({ length: 65 }, (_, index) => ({
        eventId: `event-${index}`,
        eventType: 'reasoning_summary',
        timelineSequence: index + 1,
        sequence: index + 1,
        createdAtMs: index + 1,
        payload: { summary: `原始事件 ${index}` },
      })),
    };
    renderFeature(traceAgentTransport({ sourceSnapshot }), []);

    const timeline = await screen.findByRole('region', { name: '原始对话时间线' });
    await waitFor(() => expect(within(timeline).getAllByTestId('trace-agent-timeline-entry')).toHaveLength(60));
    expect(timeline).not.toHaveTextContent('原始事件 0');
    expect(timeline).toHaveTextContent('完整消息开头');
    expect(timeline).not.toHaveTextContent('完整消息结尾');

    await user.click(within(timeline).getByRole('button', { name: '展开助手全文' }));
    expect(timeline).toHaveTextContent('完整消息结尾');
    await user.click(within(timeline).getByRole('button', { name: '加载更早 6 条' }));

    const entries = within(timeline).getAllByTestId('trace-agent-timeline-entry');
    expect(entries).toHaveLength(66);
    expect(entries[0]).toHaveAttribute('data-sequence', '1');
    expect(entries.at(-1)).toHaveAttribute('data-sequence', '66');
    expect(entries[0]).toHaveTextContent('原始事件 0');
  });

  it('loads genuinely older Room events through the history cursor and merges them in order', async () => {
    const user = userEvent.setup();
    const snapshot = roomSnapshot();
    const retainedEvents = snapshot.events.slice(2);
    const retainedSnapshot = {
      ...snapshot,
      events: retainedEvents,
      firstSequence: 3,
      lastSequence: 6,
      resumeToken: 'room-source:6',
      truncated: true,
    };
    const olderPage = {
      schemaVersion: 'rag-ime.agent-room-event-page.v1' as const,
      ok: true as const,
      roomId: 'room-source',
      items: snapshot.events.slice(0, 2),
      firstSequence: 1,
      lastSequence: 2,
      nextBeforeSequence: 0,
      hasMore: false,
      retainedFirstSequence: 1,
      retainedLastSequence: 6,
      retainedPrefixTruncated: false,
    };
    const transport = traceAgentTransport({ roomSourceSnapshot: retainedSnapshot, roomHistoryPage: olderPage });
    renderFeature(transport, []);

    await user.click(await screen.findByRole('tab', { name: 'Room 协作' }));
    const timeline = await screen.findByRole('region', { name: '原始对话时间线' });
    expect(timeline).not.toHaveTextContent('Room 用户问题');
    expect(timeline).toHaveTextContent('Room 已发布进展');
    const loadOlder = within(timeline).getByRole('button', { name: '从 Room history 加载更早' });
    await user.click(loadOlder);

    await waitFor(() => expect(timeline).toHaveTextContent('Room 用户问题'));
    const historyRequest = transport.requests.find(({ request }) => request.pathId === 'agent.room.history');
    expect(historyRequest?.request.params).toEqual({ roomId: 'room-source' });
    expect(historyRequest?.request.query).toEqual({ beforeSequence: 3, limit: 200 });
    const entries = within(timeline).getAllByTestId('trace-agent-timeline-entry');
    expect(entries.map((entry) => entry.getAttribute('data-sequence'))).toEqual(['1', '2', '3', '4', '5', '6']);
  });

  it('keeps persisted Trace diagnostic Sessions available as report handles after a fresh mount', async () => {
    const routes: string[] = [];
    const transport = traceAgentTransport({
      sessions: [
        {
          id: 'agent:trace-diagnostic-existing',
          title: 'Trace 诊断 · 已归档的失败对话',
          status: 'idle',
          updatedAtMs: 200,
          workspaceRoots: [],
          messageCount: 8,
          lastMessagePreview: '根因与候选修复已写入 Session',
        },
      ],
    });
    const view = renderFeature(transport, routes);

    const reports = await screen.findByRole('region', { name: '已保存的 Trace 诊断报告' });
    expect(reports).toHaveTextContent('报告正文保存在这个 Agent Session');
    await userEvent.setup().click(within(reports).getByRole('button', { name: '打开诊断报告' }));
    expect(routes).toContain('/agent?session=agent%3Atrace-diagnostic-existing');

    view.unmount();
    renderFeature(transport, routes);
    expect(await screen.findByRole('region', { name: '已保存的 Trace 诊断报告' })).toBeInTheDocument();
  });

  it('loads canonical Session and Room targets beyond the initial selector windows', async () => {
    const user = userEvent.setup();
    const sessions = Array.from({ length: 201 }, (_, index) => ({
      id: `session-${index}`,
      title: index === 200 ? '最早的 Session' : `Session ${index}`,
      status: 'idle',
      updatedAtMs: 1_000 - index,
      workspaceRoots: [],
    }));
    const rooms = Array.from({ length: 101 }, (_, index) => ({
      id: `room-${index}`,
      title: index === 100 ? '最早的 Room' : `Room ${index}`,
      status: 'archived',
      updatedAtMs: 1_000 - index,
      participantCount: 2,
    }));
    const transport = traceAgentTransport({ rooms, sessions });
    renderFeature(transport, []);

    expect(await screen.findAllByRole('option')).toHaveLength(200);
    expect(screen.queryByRole('option', { name: /最早的 Session/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '加载更多 Session' }));
    expect(await screen.findByRole('option', { name: /最早的 Session/ })).toBeInTheDocument();
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.sessions.list'
      && request.query?.limit === 200
      && request.query?.beforeUpdatedAtMs === 801
      && request.query?.beforeId === 'session-199')).toBe(true);

    await user.click(screen.getByRole('tab', { name: 'Room 协作' }));
    expect(screen.queryByRole('option', { name: /最早的 Room/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '加载更多 Room' }));
    expect(await screen.findByRole('option', { name: /最早的 Room/ })).toBeInTheDocument();
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.rooms.list'
      && request.query?.limit === 100
      && request.query?.beforeUpdatedAtMs === 901
      && request.query?.beforeId === 'room-99')).toBe(true);
  });
});

function renderFeature(transport: MockControlTransport, routes: string[], initialEntries = ['/trace-agent']) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <PawOsDesktopProvider openRoute={(route) => routes.push(route)} openWindow={() => undefined}>
              <TraceAgentFeature />
            </PawOsDesktopProvider>
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function traceAgentTransport(options: {
  repairTrace?: boolean;
  rooms?: Array<Record<string, unknown>>;
  sessions?: Array<Record<string, unknown>>;
  sourceSnapshot?: unknown;
  roomSourceSnapshot?: unknown;
  roomHistoryPage?: unknown;
} = {}) {
  return new MockControlTransport({
    routes: {
      'agent.sessions.list': (request: ControlRequest) => paginatedTargetList(options.sessions ?? [{
          id: 'session-source',
          title: '失败的对话',
          mode: 'assistant',
          status: 'idle',
          updatedAtMs: 100,
          workspaceRoots: ['/workspace/paw'],
          messageCount: 4,
          lastMessagePreview: 'write/edit validation error',
        }], request, 200),
      'agent.rooms.list': (request: ControlRequest) => paginatedTargetList(
        options.rooms ?? [{ id: 'room-source', title: '失败的协作', status: 'active', updatedAtMs: 110, participantCount: 3 }],
        request,
        100,
      ),
      'observability.snapshot': (request: ControlRequest) => {
        const sessionId = request.query?.sessionId;
        if (sessionId === 'agent:trace-repair') {
          return options.repairTrace === false ? emptyObservationSnapshot() : repairObservationSnapshot();
        }
        return observationSnapshot();
      },
      'agent.session.snapshot': () => options.sourceSnapshot ?? sessionSourceSnapshot(),
      'observability.trace.get': (request: ControlRequest) => traceResponse(
        request.params?.traceId ?? 'trace:source',
      ),
      'agent.room.snapshot': () => options.roomSourceSnapshot ?? roomSnapshot(),
      'agent.room.history': () => options.roomHistoryPage ?? emptyRoomHistoryPage(),
      'agent.sessions.create': (request: ControlRequest) => ({
        ok: true,
        session: {
          id: String((request.body as Record<string, unknown> | undefined)?.title).includes('修复')
            ? 'agent:trace-repair'
            : 'agent:trace-diagnostic',
        },
      }),
      'agent.session.mode.update': { ok: true },
      'agent.session.prompt': { ok: true },
      'observability.evals.list': (request: ControlRequest) => ({
        schemaVersion: 'rag-ime.observability-eval-list.v1',
        traceId: String(request.query?.traceId ?? ''),
        total: 0,
        truncated: false,
        items: [],
      }),
      'observability.evals.evidence.run': () => ({
        schemaVersion: 'rag-ime.eval-run.v1',
        evalRunId: 'eval:trace-agent:recheck:repair',
        traceIds: ['trace:repair'],
        mode: 'ground_truth',
        metricAuthority: 'ground_truth',
        truth: { status: 'human', datasetId: 'trace-agent:recheck', labelRevision: 'repair:agent:trace-repair' },
        evaluator: { provider: 'deterministic', model: 'labels', thinking: 'none', displayName: 'Human labels' },
        metrics: { precision: 1, recall: 1, f1: 1 },
        status: 'completed',
        createdAtMs: 120,
        updatedAtMs: 120,
      }),
    },
  });
}

function paginatedTargetList(
  items: Array<Record<string, unknown>>,
  request: ControlRequest,
  defaultLimit: number,
) {
  const beforeId = String(request.query?.beforeId ?? '');
  const cursorIndex = beforeId ? items.findIndex((item) => item.id === beforeId) : -1;
  const start = cursorIndex >= 0 ? cursorIndex + 1 : 0;
  const limit = Number(request.query?.limit ?? defaultLimit);
  const pageItems = items.slice(start, start + limit);
  const hasMore = start + pageItems.length < items.length;
  const last = pageItems.at(-1);
  return {
    ok: true,
    items: pageItems,
    hasMore,
    nextBeforeUpdatedAtMs: hasMore ? Number(last?.updatedAtMs ?? 0) : null,
    nextBeforeId: hasMore ? String(last?.id ?? '') : null,
  };
}

function observationSnapshot() {
  const item = {
    schemaVersion: 'rag-ime.observation-event.v1' as const,
    eventType: 'observation' as const,
    eventId: 'observation-source',
    sequence: 1,
    resumeToken: 'observation:1',
    traceId: 'trace:source',
    spanId: 'span:source',
    parentSpanId: '',
    sessionId: 'session-source',
    roomId: 'room-source',
    turnId: 'turn-source',
    runId: 'run-source',
    category: 'tool' as const,
    phase: 'tool_finished',
    name: 'workspace_write',
    status: 'failed' as const,
    summary: 'write/edit validation error: target file changed',
    createdAtMs: 100,
    startedAtMs: 100,
    endedAtMs: 120,
    durationMs: 20,
    privacyClass: 'metadata' as const,
    metrics: {},
    attributes: {},
    refs: [{ kind: 'session', id: 'session-source', label: '失败的对话' }],
  };
  return {
    schemaVersion: 'rag-ime.observation-snapshot.v1' as const,
    generatedAtMs: 120,
    firstSequence: 1,
    lastSequence: 1,
    resumeToken: 'observation:1',
    truncated: false,
    filters: {},
    counts: { total: 1, byCategory: { tool: 1 }, byStatus: { failed: 1 } },
    items: [item],
  };
}

function sessionSourceSnapshot() {
  return {
    ok: true,
    sessionId: 'session-source',
    status: 'idle',
    items: [
      {
        id: 'message-user-source',
        sessionId: 'session-source',
        turnId: 'turn-source',
        role: 'user',
        status: 'completed',
        timelineSequence: 1,
        createdAtMs: 101,
        blocks: [{ id: 'user-text-source', type: 'text', status: 'completed', data: { text: '检查当前实现' } }],
      },
      {
        id: 'message-assistant-source',
        sessionId: 'session-source',
        turnId: 'turn-source',
        role: 'assistant',
        status: 'completed',
        timelineSequence: 5,
        createdAtMs: 150,
        blocks: [{ id: 'assistant-text-source', type: 'text', status: 'completed', data: { text: '发现写入版本冲突' } }],
      },
      {
        id: 'message-error-source',
        sessionId: 'session-source',
        turnId: 'turn-source',
        role: 'assistant',
        status: 'failed',
        createdAtMs: 155,
        blocks: [{ id: 'error-source', type: 'error', status: 'failed', data: { message: 'write/edit validation error: target file changed' } }],
      },
    ],
    liveEvents: [
      {
        eventId: 'reasoning-source',
        eventType: 'reasoning_summary',
        timelineSequence: 2,
        sequence: 2,
        createdAtMs: 110,
        payload: { summary: '核对失败证据' },
      },
      {
        eventId: 'tool-started-source',
        eventType: 'tool_started',
        timelineSequence: 3,
        sequence: 3,
        createdAtMs: 120,
        payload: { summary: '读取目标文件', toolId: 'workspace', operation: 'read' },
      },
      {
        eventId: 'tool-finished-source',
        eventType: 'tool_finished',
        timelineSequence: 4,
        sequence: 4,
        createdAtMs: 140,
        payload: { summary: '读取目标文件完成', toolId: 'workspace', operation: 'read' },
      },
    ],
  };
}

function repairObservationSnapshot() {
  const base = observationSnapshot();
  const item = {
    ...base.items[0],
    eventId: 'observation-repair',
    sequence: 2,
    resumeToken: 'observation:repair:2',
    traceId: 'trace:repair',
    spanId: 'span:repair',
    sessionId: 'agent:trace-repair',
    summary: 'repair completed',
    status: 'completed' as const,
    createdAtMs: 200,
    startedAtMs: 180,
    endedAtMs: 200,
    durationMs: 20,
    refs: [{ kind: 'session', id: 'agent:trace-repair', label: '修复 Session' }],
  };
  return {
    ...base,
    generatedAtMs: 200,
    firstSequence: 2,
    lastSequence: 2,
    resumeToken: 'observation:repair:2',
    counts: { total: 1, byCategory: { tool: 1 }, byStatus: { completed: 1 } },
    items: [item],
  };
}

function emptyObservationSnapshot() {
  const base = observationSnapshot();
  return {
    ...base,
    generatedAtMs: 200,
    firstSequence: 0,
    lastSequence: 0,
    resumeToken: 'observation:repair:0',
    counts: { total: 0, byCategory: {}, byStatus: {} },
    items: [],
  };
}

function traceResponse(traceId: string) {
  const isRepair = traceId === 'trace:repair';
  const sessionId = isRepair ? 'agent:trace-repair' : 'session-source';
  const evidenceId = isRepair ? 'knowledge:repair' : 'knowledge:source';
  return {
    schemaVersion: 'rag-ime.observability-trace-get.v1' as const,
    traceId,
    trace: {
      schemaVersion: 'rag-ime.trace-envelope.v1' as const,
      traceId,
      sourceKind: 'agent' as const,
      status: 'completed' as const,
      binding: { sessionId, roomId: 'room-source', runId: isRepair ? 'run-repair' : 'run-source' },
      input: { fingerprint: 'sha256:' + '0'.repeat(64), contentPolicy: 'hash_only' as const, normalization: 'test' },
      spans: [],
      evidence: [{
        evidenceId,
        sourceKind: 'knowledge' as const,
        sourceRef: `knowledge://${isRepair ? 'repair' : 'source'}`,
        sourceLane: 'test',
        evidenceStage: 'retrieval_output',
        disposition: 'included' as const,
        scores: {},
        rankBefore: null,
        rankAfter: null,
        omissionReason: '',
      }],
      artifacts: [],
      createdAtMs: isRepair ? 200 : 100,
      updatedAtMs: isRepair ? 220 : 120,
    },
    truncated: false,
    projectionSource: 'trace_store' as const,
    observationWindow: {
      firstSequence: isRepair ? 2 : 1,
      lastSequence: isRepair ? 2 : 1,
      resumeToken: `trace-store:${traceId}`,
      nextBeforeSequence: null,
    },
  };
}

function emptyRoomHistoryPage() {
  return {
    schemaVersion: 'rag-ime.agent-room-event-page.v1' as const,
    ok: true as const,
    roomId: 'room-source',
    items: [],
    firstSequence: 0,
    lastSequence: 0,
    nextBeforeSequence: 0,
    hasMore: false,
    retainedFirstSequence: 1,
    retainedLastSequence: 0,
    retainedPrefixTruncated: false,
  };
}

function roomSnapshot() {
  const participant = (id: string, ordinal: number, sessionId: string) => ({
    schemaVersion: 'rag-ime.agent-participant.v1' as const,
    id,
    roomId: 'room-source',
    sessionId,
    roleId: `role-${id}`,
    roleVersion: '1',
    displayName: id,
    collaborationRole: ordinal === 1 ? 'coordinator' as const : 'reviewer' as const,
    status: 'active' as const,
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: 100,
  });
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1' as const,
    ok: true as const,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1' as const,
      id: 'room-source',
      title: '失败的协作',
      status: 'active' as const,
      executionMode: 'read_only' as const,
      roomKind: 'collaboration' as const,
      routingPolicy: 'moderator' as const,
      moderatorParticipantId: 'participant-1',
      workspaceRoots: [] as [],
      createdAtMs: 1,
      updatedAtMs: 110,
      lastEventSequence: 6,
      participants: [participant('participant-1', 1, 'session-source'), participant('participant-2', 2, 'session-secondary')],
      topics: [],
      artifacts: [],
      workItems: [],
    },
    events: [
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-user-source',
        roomId: 'room-source',
        sequence: 1,
        turnId: 'turn-source',
        eventType: 'user_message' as const,
        participantId: null,
        sourceSessionId: 'session-source',
        createdAtMs: 101,
        payload: { text: 'Room 用户问题' },
        resumeToken: 'room-source:1',
      },
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-reasoning-source',
        roomId: 'room-source',
        sequence: 2,
        turnId: 'turn-source',
        eventType: 'participant_activity' as const,
        participantId: 'participant-1',
        sourceSessionId: 'session-source',
        createdAtMs: 110,
        payload: { sourceEventType: 'reasoning_summary', data: { summary: '协作者核对分工' } },
        resumeToken: 'room-source:2',
      },
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-tool-started-source',
        roomId: 'room-source',
        sequence: 3,
        turnId: 'turn-source',
        eventType: 'participant_activity' as const,
        participantId: 'participant-1',
        sourceSessionId: 'session-source',
        createdAtMs: 120,
        payload: { sourceEventType: 'tool_started', data: { toolName: 'read', summary: '读取 WorkItem' } },
        resumeToken: 'room-source:3',
      },
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-tool-finished-source',
        roomId: 'room-source',
        sequence: 4,
        turnId: 'turn-source',
        eventType: 'participant_activity' as const,
        participantId: 'participant-1',
        sourceSessionId: 'session-source',
        createdAtMs: 130,
        payload: { sourceEventType: 'tool_finished', data: { toolName: 'read', summary: 'WorkItem 读取完成' } },
        resumeToken: 'room-source:4',
      },
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-post-source',
        roomId: 'room-source',
        sequence: 5,
        turnId: 'turn-source',
        eventType: 'room_post' as const,
        participantId: 'participant-1',
        sourceSessionId: 'session-source',
        createdAtMs: 140,
        payload: { post: { content: 'Room 已发布进展' } },
        resumeToken: 'room-source:5',
      },
      {
        schemaVersion: 'rag-ime.agent-room-event.v1' as const,
        eventId: 'room-event-source',
        roomId: 'room-source',
        sequence: 6,
        turnId: 'turn-source',
        eventType: 'turn_failed' as const,
        participantId: 'participant-1',
        sourceSessionId: 'session-source',
        createdAtMs: 150,
        payload: { error: '协作失败：重复分派后未能收口' },
        resumeToken: 'room-source:6',
      },
    ],
    firstSequence: 1,
    lastSequence: 6,
    resumeToken: 'room-source:6',
    truncated: false,
  };
}
