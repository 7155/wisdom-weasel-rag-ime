import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import { createRoomProjection } from '@/contracts/room-reducer';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { AgentBackgroundJobV1 } from '@/contracts/generated/agent-background-job.v1';
import type { RoomSummary } from '@/features/rooms/room-types';
import { useRoomLiveStore } from '@/features/rooms/state/live-store';
import { MockControlTransport } from '@/test/mock-transport';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import { PawOsSatelliteHost } from './PawOsSatelliteHost';
import satelliteCss from './paw-os-satellite.css?raw';

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.reduceMotion;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useAgentLiveStore.setState({ projections: {} });
  useRoomLiveStore.setState({ projections: {} });
});

describe('PawOsSatelliteHost', () => {
  it('does not recreate a second Room conversation for a panel-less Room target', () => {
    const transport = new MockControlTransport();

    renderSatellite(transport, {
      kind: 'room', id: 'room-main', title: '产品协作室',
    });

    expect(document.querySelector('.paw-os-satellite')).not.toBeInTheDocument();
    expect(transport.requests).toEqual([]);
  });

  it('renders the real Pi child conversation blocks and event-driven tool state', async () => {
    const run = sampleRun();
    const transport = new MockControlTransport({ routes: {
      'agent.subagents.list': { tree: { roots: [{ run, children: [] }] } },
      'agent.subagent.console': {
        conversation: {
          items: [{
            id: 'message:1',
            role: 'assistant',
            status: 'streaming',
            createdAtMs: 100,
            blocks: [{ type: 'text', data: { text: '正在核对兼容边界。' } }],
          }],
        },
        activity: [{
          id: 'event:1',
          eventType: 'tool_started',
          createdAtMs: 101,
          payload: { toolName: 'read' },
        }],
        inbox: [],
      },
    } });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={queryClient}>
          <PawOsSatelliteHost target={{ kind: 'subagent', id: run.id, sessionId: 'session-parent', title: run.task }} />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('正在核对兼容边界。')).toBeInTheDocument();
    expect(screen.getByText('开始调用 read')).toBeInTheDocument();
    const timeline = screen.getByRole('log', { name: '子 Agent 实现子 Agent 卫星窗 公开对话与运行事件' });
    expect(timeline).toHaveAttribute('aria-live', 'polite');
    expect(screen.getAllByRole('img', { name: '执行中' })).toHaveLength(3);
    expect(document.querySelector('.agent-persona-avatar')).not.toBeInTheDocument();
    expect(document.querySelector('.paw-os-satellite__hero')).not.toBeInTheDocument();
    const statusline = screen.getByLabelText('当前工作与状态');
    expect(statusline).toHaveAttribute('data-state', 'running');
    expect(statusline).toHaveTextContent('进行中');
    expect(statusline).toHaveTextContent('实现子 Agent 卫星窗');
    expect(screen.getByRole('button', { name: '在 Agent 中打开所属 Session' })).toBeInTheDocument();
  });

  it('reads one authoritative background run log without starting a second command', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.session.backgroundJob.logs': {
        schemaVersion: 'rag-ime.agent-background-job-log.v1', ok: true,
        sessionId: 'session-1', jobId: 'bg_0123456789abcdef0123456789abcdef',
        cursor: 0, nextCursor: 13, logStartCursor: 0, truncatedBeforeCursor: false,
        hasMore: false, text: 'server ready\n',
      },
    } });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={queryClient}>
          <PawOsSatelliteHost target={{
            kind: 'process-terminal', id: 'call-job-1', title: 'pnpm dev',
            sessionId: 'session-1', toolCallId: 'call-job-1',
            runId: 'bg_0123456789abcdef0123456789abcdef', command: 'pnpm dev', cwd: '/workspace/paw',
          }} />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('server ready')).toBeInTheDocument();
    expect(screen.getByText('$ pnpm dev')).toBeInTheDocument();
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(['agent.session.backgroundJob.logs']);
  });

  it('stops the exact cancellable job and applies its authoritative receipt', async () => {
    const user = userEvent.setup();
    const jobId = 'bg_44444444444444444444444444444444';
    const cancellingJob = backgroundJob('cancelling', jobId);
    const transport = new MockControlTransport({ routes: {
      'agent.session.backgroundJob.logs': {
        schemaVersion: 'rag-ime.agent-background-job-log.v1', ok: true,
        sessionId: 'session-1', jobId, cursor: 0, nextCursor: 0,
        logStartCursor: 0, truncatedBeforeCursor: false, hasMore: false, text: '',
      },
      'agent.session.backgroundJob.cancel': {
        schemaVersion: 'rag-ime.agent-background-job-cancel-receipt.v1',
        ok: true,
        summary: '已请求停止后台任务',
        alreadyTerminal: false,
        job: cancellingJob,
        cancelReceipt: { jobId, requestedAtMs: 200, status: 'cancelling' },
      },
    } });
    renderSatellite(transport, {
      kind: 'process-terminal', id: 'call-job-4', title: 'pnpm dev',
      sessionId: 'session-1', toolCallId: 'call-job-4', runId: jobId,
      command: 'pnpm dev', cwd: '/workspace/paw', runStatus: 'running', roomBound: false,
    });

    await user.click(await screen.findByRole('button', { name: '停止后台任务' }));
    await user.click(screen.getByRole('button', { name: '确认停止后台任务' }));

    await waitFor(() => expect(useAgentLiveStore.getState().projections['session-1']?.backgroundJobsById[jobId])
      .toMatchObject({ status: 'cancelling' }));
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.session.backgroundJob.cancel')?.request).toMatchObject({
      params: { sessionId: 'session-1', jobId },
      body: { reason: 'control_center_requested' },
    });
    expect(screen.getByText('已请求停止后台任务')).toBeVisible();
    expect(screen.queryByRole('button', { name: /停止后台任务/ })).not.toBeInTheDocument();
  });

  it('uses the exact owning session, job, and Room turn when stopping from Room Focus', async () => {
    const user = userEvent.setup();
    const jobId = 'bg_55555555555555555555555555555555';
    const cancellingJob = backgroundJob('cancelling', jobId, {
      sessionId: 'session-room-worker',
      causalMetadata: { todoId: '', todoRevision: 0, goalId: '', goalRevision: 0, turnId: 'room-root-1', roomBound: true },
    });
    const transport = new MockControlTransport({ routes: {
      'agent.session.backgroundJob.logs': {
        schemaVersion: 'rag-ime.agent-background-job-log.v1', ok: true,
        sessionId: 'session-room-worker', jobId,
        cursor: 0, nextCursor: 0, logStartCursor: 0, truncatedBeforeCursor: false,
        hasMore: false, text: '',
      },
      'agent.session.backgroundJob.cancel': {
        schemaVersion: 'rag-ime.agent-background-job-cancel-receipt.v1', ok: true,
        summary: '已请求停止 Room 后台任务', alreadyTerminal: false,
        job: cancellingJob,
        cancelReceipt: { jobId, requestedAtMs: 200, status: 'cancelling' },
      },
    } });
    renderSatellite(transport, {
      kind: 'process-terminal', id: 'call-job-5', title: 'pnpm build',
      sessionId: 'session-room-worker', roomId: 'room-1', toolCallId: 'call-job-5',
      runId: jobId, command: 'pnpm build', runStatus: 'running', roomBound: true,
      roomTurnId: 'room-root-1',
    });

    await user.click(await screen.findByRole('button', { name: '停止后台任务' }));
    await user.click(screen.getByRole('button', { name: '确认停止后台任务' }));

    await waitFor(() => expect(transport.requests.find(({ request }) => request.pathId === 'agent.session.backgroundJob.cancel')?.request).toMatchObject({
      params: { sessionId: 'session-room-worker', jobId },
      body: { reason: 'control_center_requested', roomTurnId: 'room-root-1' },
    }));
    expect(screen.getByText('已请求停止 Room 后台任务')).toBeVisible();
  });

  it('does not guess Room cancel authority when the exact current Room turn is absent', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.session.backgroundJob.logs': {
        schemaVersion: 'rag-ime.agent-background-job-log.v1', ok: true,
        sessionId: 'session-room-worker', jobId: 'bg_66666666666666666666666666666666',
        cursor: 0, nextCursor: 0, logStartCursor: 0, truncatedBeforeCursor: false,
        hasMore: false, text: '',
      },
    } });
    renderSatellite(transport, {
      kind: 'process-terminal', id: 'call-job-6', title: 'pnpm build',
      sessionId: 'session-room-worker', roomId: 'room-1', toolCallId: 'call-job-6',
      runId: 'bg_66666666666666666666666666666666', command: 'pnpm build',
      runStatus: 'running', roomBound: true,
    });

    expect(await screen.findByText('等待运行输出…')).toBeVisible();
    expect(screen.queryByRole('button', { name: /停止后台任务/ })).not.toBeInTheDocument();
  });

  it('renders participant dialogue and Tool lifecycle without a duplicate WorkItem line', async () => {
    const room = participantRoom();
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('tool-a');
    projection.activitiesById['tool-a'] = {
      id: 'tool-a',
      turnId: 'root-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'tool',
      status: 'running',
      summary: '正在读取 PawWindowLayer.tsx',
      payload: { sourceEventType: 'tool_started', toolName: 'read' },
      createdAtMs: 101,
      updatedAtMs: 101,
    };
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: {
      'agent.room.get': { room },
    } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    expect(document.querySelector('.paw-participant-chat__workline')).not.toBeInTheDocument();
    expect(timeline.querySelector('article[data-status="running"]')).toHaveTextContent('正在读取 PawWindowLayer.tsx');
    expect(screen.queryByRole('banner', { name: '实现伙伴 当前上下文' })).not.toBeInTheDocument();
    expect(document.querySelector('.paw-os-satellite__hero')).not.toBeInTheDocument();
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(['agent.room.get']);
  });

  it('shows one thin statusline with current work, text+colour state, and a full Session route', async () => {
    const room = participantRoom();
    const projection = participantProjectionWithActivities(room.id, [
      roomActivity('participant-tool-1', 'participant-a', 101, '正在读取 PawWindowLayer.tsx'),
    ]);
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });
    const openRoute = vi.fn();

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    }, { openRoute });

    const statusline = await screen.findByLabelText('当前工作与状态');
    expect(statusline).toHaveClass('paw-participant-chat__statusline');
    expect(statusline).toHaveAttribute('data-state', 'running');
    expect(statusline).toHaveTextContent('进行中');
    expect(statusline).toHaveTextContent('正在读取 PawWindowLayer.tsx');
    await userEvent.setup().click(screen.getByRole('button', { name: '在 Agent 中打开 实现伙伴 的完整 Session' }));
    expect(openRoute).toHaveBeenCalledWith('/agent?session=session-a');
  });

  it('compresses each tool activity into one line with the time at the end', async () => {
    const room = participantRoom();
    const projection = participantProjectionWithActivities(room.id, [
      { ...roomActivity('participant-tool-1', 'participant-a', 101, '已创建 interface.js'), status: 'completed' },
    ]);
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    await userEvent.setup().click(await screen.findByRole('button', { name: /运行活动 1 项/ }));
    const row = timeline.querySelector('article[data-kind="activity"]');
    expect(row).not.toBeNull();
    expect(row?.querySelector('header')).toBeNull();
    expect(row?.querySelector('p')).toBeNull();
    expect(row?.querySelector('strong')).toHaveTextContent('工具');
    expect(row?.querySelector('.paw-participant-chat__activity-message')).toHaveTextContent('已创建 interface.js');
    expect(row?.querySelector('.paw-participant-chat__activity-message')).toHaveAttribute('title', '已创建 interface.js');
    expect(row?.querySelector('time')).toHaveTextContent(/\d/);
  });

  it('keeps the failure alarm visible on the one-line tool row', async () => {
    const room = participantRoom();
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('tool-failed');
    projection.activitiesById['tool-failed'] = {
      id: 'tool-failed', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
      kind: 'tool', status: 'failed', summary: '命令执行完成，退出码 1',
      payload: { sourceEventType: 'tool_failed', toolName: 'bash' }, createdAtMs: 130, updatedAtMs: 130,
    };
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    await userEvent.setup().click(await screen.findByRole('button', { name: /运行活动 1 项/ }));
    const row = timeline.querySelector<HTMLElement>('article[data-kind="activity"][data-status="failed"]');
    expect(row).not.toBeNull();
    expect(within(row!).getByRole('img', { name: '执行失败' })).toBeInTheDocument();
    expect(row?.querySelector('.paw-participant-chat__activity-message')).toHaveTextContent('命令执行完成，退出码 1');
  });

  it('turns a machine event name in the statusline into readable completion copy', async () => {
    const room = { ...participantRoom(), workItems: [] };
    const projection = participantProjectionWithActivities(room.id, [
      { ...roomActivity('participant-tool-1', 'participant-a', 101, 'participant_activity'), status: 'completed' },
    ]);
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const statusline = await screen.findByLabelText('当前工作与状态');
    expect(statusline).toHaveAttribute('data-state', 'completed');
    expect(statusline).toHaveTextContent('活动已完成');
    expect(statusline).not.toHaveTextContent('participantactivity');
  });

  it('projects only supported activities addressed to this participant across all event fields', async () => {
    const room = participantRoom();
    const projection = createRoomProjection(room.id);
    const activities = [
      {
        id: 'route-kind', turnId: 'root-a', participantId: null, sourceSessionId: 'session-root',
        kind: 'route_decision', status: 'completed' as const, summary: '路由已确定',
        payload: { targetParticipantId: 'participant-a' }, createdAtMs: 101,
      },
      {
        id: 'dispatch-source', turnId: 'root-a', participantId: null, sourceSessionId: 'session-root',
        kind: 'status', status: 'completed' as const, summary: '已派发',
        payload: { sourceEventType: 'dispatch', targetParticipantId: 'participant-a' }, createdAtMs: 102,
      },
      {
        id: 'intercom-kind', turnId: 'root-a', participantId: null, sourceSessionId: 'session-root',
        kind: 'status', status: 'completed' as const, summary: '伙伴请求已送达',
        payload: { activityKind: 'intercom', targetParticipantId: 'participant-a' }, createdAtMs: 103,
      },
      {
        id: 'tool-kind', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
        kind: 'tool', status: 'running' as const, summary: '正在读取',
        payload: { toolName: 'read' }, createdAtMs: 104,
      },
      {
        id: 'tool-source', turnId: 'root-a', participantId: null, sourceSessionId: 'session-root',
        kind: 'status', status: 'completed' as const, summary: '读取完成',
        payload: { sourceEventType: 'tool_finished', targetParticipantId: 'participant-a', toolName: 'read' }, createdAtMs: 105,
      },
      {
        id: 'route-other', turnId: 'root-a', participantId: null, sourceSessionId: 'session-root',
        kind: 'route_decision', status: 'completed' as const, summary: '不属于当前伙伴',
        payload: { targetParticipantId: 'participant-other' }, createdAtMs: 106,
      },
      {
        id: 'unknown', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
        kind: 'status', status: 'completed' as const, summary: '未知事件不应出现',
        payload: { activityKind: 'not_a_public_event' }, createdAtMs: 107,
      },
      {
        id: 'target-wins', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
        kind: 'dispatch', status: 'completed' as const, summary: '应归属其他目标',
        payload: { targetParticipantId: 'participant-other' }, createdAtMs: 108,
      },
    ];
    projection.activityOrder.push(...activities.map((activity) => activity.id));
    for (const activity of activities) projection.activitiesById[activity.id] = activity;
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    expect(timeline.querySelectorAll('article[data-kind="activity"]')).toHaveLength(5);
    expect(timeline).toHaveTextContent('路由已确定');
    expect(timeline).toHaveTextContent('已派发');
    expect(timeline).toHaveTextContent('伙伴请求已送达');
    expect(timeline).toHaveTextContent('正在读取');
    expect(timeline).toHaveTextContent('读取完成');
    expect(timeline.querySelector('article[data-event-type="tool"] [role="img"]')).toHaveAttribute('data-kind', 'tool');
    expect(timeline).not.toHaveTextContent('不属于当前伙伴');
    expect(timeline).not.toHaveTextContent('未知事件不应出现');
    expect(timeline).not.toHaveTextContent('应归属其他目标');
  });

  it('shows a RoomPanel missing state when a successful response has another Room id', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.room.get': { room: { ...participantRoom(), id: 'room-other' } },
      'agent.roles.list': { ok: true, items: [] },
    } });

    renderSatellite(transport, {
      kind: 'room', id: 'room-live', panel: 'flow', title: '产品协作室',
    });

    expect(await screen.findByText('找不到这个 Room')).toBeInTheDocument();
    expect(screen.getByText('这个 Room 已不在当前 Room 清单中，可能已归档或删除。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '回到 Room' })).toBeInTheDocument();
  });

  it('projects the execution satellite as a compact WorkItem flow instead of the full Room cockpit', async () => {
    const room = {
      ...participantRoom(),
      workItems: [{
        id: 'work-a', roomId: 'room-participant', topicId: '', rootTurnId: 'root-a', rootWorkId: 'work-a', parentWorkId: '',
        objective: '实现 Room 任务图交互', expectedOutput: '可复查的任务图交互', acceptanceCriteria: ['保持真实依赖关系'],
        accountableParticipantId: 'participant-a', currentOwnerParticipantId: 'participant-a', offeredToParticipantId: '',
        createdByParticipantId: 'participant-a', clientMessageId: '', state: 'review' as const, depth: 0, revision: 2,
        resultSummary: '等待独立复核', artifactRefs: [], evidenceRefs: ['test:room-graph-ui'], blocker: {}, acceptedTurnId: '',
        createdAtMs: 100, updatedAtMs: 120, completedAtMs: null,
      }],
    };
    const transport = new MockControlTransport({ routes: {
      'agent.room.get': { room },
      'agent.roles.list': { ok: true, items: [] },
    } });

    const { container } = renderSatellite(transport, {
      kind: 'room', id: room.id, panel: 'execution', title: room.title,
    });

    const flow = await screen.findByRole('list', { name: 'Room WorkItem 任务流' });
    expect(flow).toHaveTextContent('实现 Room 任务图交互');
    expect(flow).toHaveTextContent('实现伙伴');
    expect(flow).toHaveTextContent('WorkItem r2');
    expect(screen.getByText('等待独立复核')).toBeVisible();
    expect(container.querySelector('.room-cockpit')).not.toBeInTheDocument();
    expect(container.querySelector('.paw-os-satellite__hero')).not.toBeInTheDocument();
  });

  it('follows participant updates only while the reader is near the latest entry', async () => {
    const room = participantRoom();
    const projection = participantProjectionWithActivities(room.id, [
      roomActivity('participant-tool-1', 'participant-a', 101, '正在读取第一份文件'),
    ]);
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    setScrollMetrics(timeline, 600);
    fireEvent.scroll(timeline);
    const nearBottomProjection = participantProjectionWithActivities(room.id, [
      roomActivity('participant-tool-1', 'participant-a', 101, '正在读取第一份文件'),
      roomActivity('participant-tool-2', 'participant-a', 102, '正在读取第二份文件'),
    ]);
    act(() => useRoomLiveStore.setState({ projections: { [room.id]: nearBottomProjection } }));
    await waitFor(() => expect(timeline).toHaveTextContent('正在读取第二份文件'));
    expect(timeline.scrollTop).toBe(timeline.scrollHeight);

    timeline.scrollTop = 100;
    fireEvent.scroll(timeline);
    const historyProjection = participantProjectionWithActivities(room.id, [
      roomActivity('participant-tool-1', 'participant-a', 101, '正在读取第一份文件'),
      roomActivity('participant-tool-2', 'participant-a', 102, '正在读取第二份文件'),
      roomActivity('participant-tool-3', 'participant-a', 103, '正在读取第三份文件'),
    ]);
    act(() => useRoomLiveStore.setState({ projections: { [room.id]: historyProjection } }));
    await waitFor(() => expect(timeline).toHaveTextContent('正在读取第三份文件'));
    expect(timeline.scrollTop).toBe(100);
  });

  it('preserves subagent history position when a new console entry arrives', async () => {
    const run = sampleRun();
    const consoleSnapshot = {
      conversation: { items: [{ id: 'message:1', role: 'assistant', status: 'completed', createdAtMs: 100, blocks: [{ type: 'text', data: { text: '第一条公开消息。' } }] }] },
      activity: [],
      inbox: [],
    };
    const transport = new MockControlTransport({ routes: {
      'agent.subagents.list': { tree: { roots: [{ run, children: [] }] } },
      'agent.subagent.console': consoleSnapshot,
    } });
    const { queryClient } = renderSatellite(transport, {
      kind: 'subagent', id: run.id, sessionId: 'session-parent', title: run.task,
    });

    const timeline = await screen.findByRole('log', { name: '子 Agent 实现子 Agent 卫星窗 公开对话与运行事件' });
    setScrollMetrics(timeline, 100);
    fireEvent.scroll(timeline);
    await act(async () => {
      queryClient.setQueryData(['agent', 'subagent-satellite', 'session-parent', run.id], {
        ...consoleSnapshot,
        conversation: {
          items: [
            ...consoleSnapshot.conversation.items,
            { id: 'message:2', role: 'assistant', status: 'completed', createdAtMs: 101, blocks: [{ type: 'text', data: { text: '第二条公开消息。' } }] },
          ],
        },
      });
    });

    await waitFor(() => expect(timeline).toHaveTextContent('第二条公开消息。'));
    expect(timeline.scrollTop).toBe(100);
  });

  it('keeps raw public JSON, paths, and hashes behind an explicit participant disclosure', async () => {
    const room = participantRoom();
    const rawDetail = '```json\n{"path":"/Volumes/private/workspace/PawWindowLayer.tsx","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n```';
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('tool-raw');
    projection.activitiesById['tool-raw'] = {
      id: 'tool-raw', turnId: 'root-a', participantId: 'participant-a', sourceSessionId: 'session-a',
      kind: 'tool', status: 'running', summary: rawDetail,
      payload: { sourceEventType: 'tool_started', toolName: 'read' },
      createdAtMs: 120, updatedAtMs: 120,
    };
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    expect(timeline.querySelector('article[data-status="running"]')).toHaveTextContent('read 工具执行中');
    const disclosure = document.querySelector<HTMLElement>('.paw-participant-chat__raw-detail');
    expect(disclosure).not.toBeNull();
    expect(screen.queryByText('/Volumes/private/workspace/PawWindowLayer.tsx')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('查看公开原文'));
    expect(await screen.findByText(/PawWindowLayer\.tsx/)).toBeInTheDocument();
    expect(disclosure?.querySelector('pre')).toHaveTextContent('a'.repeat(64));
    fireEvent.click(screen.getByText('查看公开原文'));
    expect(disclosure?.querySelector('.agent-smooth-reveal')).toHaveAttribute('data-state', 'closing');
    expect(disclosure?.querySelector('pre')).toHaveTextContent('/Volumes/private/workspace/PawWindowLayer.tsx');
    fireEvent.transitionEnd(disclosure?.querySelector('.agent-smooth-reveal')!, { propertyName: 'height' });
    await waitFor(() => expect(disclosure?.querySelector('pre')).not.toBeInTheDocument());
  });

  it('makes the participant history window explicit and lets the reader load the older 48-entry page', async () => {
    const room = participantRoom();
    const projection = participantProjectionWithActivities(room.id, Array.from({ length: 49 }, (_, index) => (
      roomActivity(`participant-tool-${index}`, 'participant-a', index + 1, `活动 ${index}`)
    )));
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });

    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    expect(await screen.findByText('最近 48 / 共 49 条')).toBeInTheDocument();
    expect(screen.queryByText('活动 0')).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '加载更早的 1 条' }));
    expect(await screen.findByText('活动 0')).toBeInTheDocument();
    /* PF-CM-013/UR-056：历史全部可见后，边界行让位给真实对话。 */
    expect(screen.queryByText(/最近 \d+ \/ 共 \d+ 条/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /加载更早的/ })).not.toBeInTheDocument();
  });

  it('keeps a manually collapsed running participant group collapsed after completion', async () => {
    const room = participantRoom();
    const running = participantProjectionWithActivities(room.id, [roomActivity('participant-tool-1', 'participant-a', 101, '仍在读取')]);
    useRoomLiveStore.setState({ projections: { [room.id]: running } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });
    renderSatellite(transport, {
      kind: 'participant', id: 'participant-a', roomId: room.id,
      title: '实现伙伴', subtitle: '实现 · session-a',
    });

    const trigger = await screen.findByRole('button', { name: /运行活动 1 项/ });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await userEvent.setup().click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    const completed = participantProjectionWithActivities(room.id, [{ ...roomActivity('participant-tool-1', 'participant-a', 101, '读取已完成'), status: 'completed' }]);
    act(() => useRoomLiveStore.setState({ projections: { [room.id]: completed } }));
    await waitFor(() => expect(trigger).toHaveAttribute('aria-expanded', 'false'));
  });

  it('makes the 50-run subagent directory bound explicit without inventing a total', async () => {
    const run = sampleRun();
    const runs = Array.from({ length: 50 }, (_, index) => ({ ...run, id: index === 49 ? run.id : `subagent-run:${index}` }));
    const transport = new MockControlTransport({ routes: {
      'agent.subagents.list': { tree: { roots: runs.map((candidate) => ({ run: candidate, children: [] })) } },
      'agent.subagent.console': { conversation: { items: [] }, activity: [], inbox: [] },
    } });
    renderSatellite(transport, { kind: 'subagent', id: run.id, sessionId: 'session-parent', title: run.task });

    expect(await screen.findByText('子 Agent 目录当前加载 50 条；接口未提供总数，较早运行可能未加载（每次最多 50 条）。')).toBeInTheDocument();
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.subagents.list')?.request.query).toMatchObject({ limit: 50 });
    expect(screen.getByRole('button', { name: '在 Agent 中查看' })).toBeInTheDocument();
  });

  it('uses the reduced-motion disclosure path without leaving closing content mounted', async () => {
    document.documentElement.dataset.reduceMotion = 'true';
    const user = userEvent.setup();
    const room = participantRoom();
    const projection = participantProjectionWithActivities(room.id, [roomActivity('participant-tool-1', 'participant-a', 101, '正文很长\n需要在公开原文中逐层读取')]);
    useRoomLiveStore.setState({ projections: { [room.id]: projection } });
    const transport = new MockControlTransport({ routes: { 'agent.room.get': { room } } });
    renderSatellite(transport, { kind: 'participant', id: 'participant-a', roomId: room.id, title: '实现伙伴', subtitle: '实现 · session-a' });

    const timeline = await screen.findByRole('log', { name: '实现伙伴 公开消息与运行事件' });
    await user.click(await screen.findByRole('button', { name: '查看公开原文' }));
    expect(await within(timeline).findByText(/需要在公开原文中逐层读取/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '查看公开原文' }));
    expect(within(timeline).queryByText(/需要在公开原文中逐层读取/)).not.toBeInTheDocument();
  });

  it('keeps history actions and disclosure controls reachable in a narrow satellite', () => {
    expect(satelliteCss).toContain('@container paw-window (max-width: 320px)');
    expect(satelliteCss).toContain('.paw-participant-chat__history-boundary { align-items: stretch; flex-direction: column; }');
    expect(satelliteCss).toContain('.paw-participant-chat__activity-group__summary { grid-template-columns: minmax(0, 1fr) 16px 12px; padding-inline: 8px; }');
  });

  it('keeps the statusline one text row that never squeezes the dialogue at 280 width', () => {
    expect(satelliteCss).toContain('.paw-os-satellite--participant-chat {\n  display: grid;\n  grid-template-rows: minmax(0, 1fr) auto;');
    expect(satelliteCss).toContain('.paw-participant-chat__statusline > p { min-width: 0; flex: 1; margin: 0; overflow: hidden; color: var(--paw-ink); text-overflow: ellipsis; white-space: nowrap; }');
    expect(satelliteCss).toContain(".paw-participant-chat__statusline[data-state='running'] { --paw-satellite-state: #2783de; }");
    expect(satelliteCss).toContain(".paw-participant-chat__statusline[data-state='blocked'],\n.paw-participant-chat__statusline[data-state='failed'] { --paw-satellite-state: #c64747; }");
    expect(satelliteCss).toContain('.paw-participant-chat__statusline > button > span { display: none; }');
  });
});

function renderSatellite(
  transport: MockControlTransport,
  target: Parameters<typeof PawOsSatelliteHost>[0]['target'],
  desktop?: { openRoute?: (route: string) => void },
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = (
    <ControlTransportProvider transport={transport}>
      <QueryClientProvider client={queryClient}>
        <PawOsSatelliteHost target={target} />
      </QueryClientProvider>
    </ControlTransportProvider>
  );
  const rendered = render(desktop
    ? <PawOsDesktopProvider openRoute={desktop.openRoute} openWindow={() => undefined}>{host}</PawOsDesktopProvider>
    : host);
  return { ...rendered, queryClient };
}

function roomActivity(id: string, participantId: string, createdAtMs: number, summary: string) {
  return {
    id,
    turnId: 'root-a',
    participantId,
    sourceSessionId: 'session-a',
    kind: 'tool',
    status: 'running' as 'running' | 'completed',
    summary,
    payload: { sourceEventType: 'tool_started', toolName: 'read' },
    createdAtMs,
  };
}

function participantProjectionWithActivities(roomId: string, activities: ReturnType<typeof roomActivity>[]) {
  const projection = createRoomProjection(roomId);
  projection.activityOrder.push(...activities.map((activity) => activity.id));
  for (const activity of activities) projection.activitiesById[activity.id] = activity;
  return projection;
}

function setScrollMetrics(element: Element, scrollTop: number): asserts element is HTMLElement {
  Object.defineProperties(element, {
    clientHeight: { configurable: true, value: 400 },
    scrollHeight: { configurable: true, value: 1_000 },
    scrollTop: { configurable: true, value: scrollTop, writable: true },
  });
}

function backgroundJob(status: AgentBackgroundJobV1['status'], jobId: string, overrides: Partial<AgentBackgroundJobV1> = {}): AgentBackgroundJobV1 {
  return {
    schemaVersion: 'rag-ime.agent-background-job.v1', jobId, sessionId: 'session-1',
    label: 'pnpm dev', status, command: 'pnpm dev', commandSha256: 'a'.repeat(64),
    cwd: '/workspace/paw', networkAllowed: false, maxRunSeconds: 120, pid: 42,
    createdAtMs: 100, startedAtMs: 110, updatedAtMs: 200, endedAtMs: 0,
    exitCode: null, outputBytes: 0, logStartCursor: 0, logTruncated: false,
    cancelRequestedAtMs: status === 'cancelling' ? 200 : 0, error: '', approvalId: 'approval-1',
    causalMetadata: { todoId: '', todoRevision: 0, goalId: '', goalRevision: 0, turnId: 'turn-1', roomBound: false },
    ...overrides,
  };
}

function sampleRun(): AgentSubagentRunV1 {
  return {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id: 'subagent-run:test',
    nodeId: 'subagent-node:test',
    attemptId: 'subagent-attempt:test:1',
    attemptNumber: 1,
    predecessorAttemptId: '',
    ownerRunId: 'session:parent',
    parentRunId: '',
    depth: 1,
    batchId: 'subagent-batch:test',
    childSessionId: 'session-child',
    todoTask: '核对子 Agent 证据',
    todoPhase: '验证',
    templateId: 'worker',
    templateVersion: '1',
    ordinal: 0,
    task: '实现子 Agent 卫星窗',
    expectedOutput: '真实对话与事件状态',
    acceptanceCriteria: ['真实上下文可见'],
    launchDigest: {
      schemaVersion: 'rag-ime.agent-subagent-launch-digest.v1',
      contextMode: 'fresh',
      templateId: 'worker',
      templateVersion: '1',
      modelProfile: 'openai-codex/gpt-5.6-sol',
      thinkingLevel: 'high',
      toolProfileVersion: 'subagent-v1',
      toolAllowlistMode: 'profile',
      tools: ['read'],
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
      workspaceAccess: 'read_only',
      workspaceRootCount: 1,
      outputContract: { required: false, schemaSha256: '' },
      extensionRuntime: 'pi_host_managed',
    },
    contract: { status: 'not_requested', error: '', toolCallId: '', validatedAtMs: null },
    state: 'running',
    budget: { maxTurns: 0, maxToolCalls: 0, maxTotalTokens: 10_000, maxDurationMs: 60_000, maxOutputChars: 10_000 },
    usage: { turnCount: 1, toolCount: 1, totalTokens: 300 },
    result: {},
    error: '',
    resultContextScheduledAtMs: null,
    createdAtMs: 1,
    startedAtMs: 2,
    updatedAtMs: 3,
    completedAtMs: null,
  };
}

function participantRoom(): RoomSummary {
  return {
    id: 'room-live',
    title: 'PAWOS 完整迁移',
    status: 'active',
    description: '将网页模型结构接入真实 Room reducer。',
    routingPolicy: 'natural',
    moderatorParticipantId: 'participant-root',
    updatedAtMs: 110,
    participants: [{
      id: 'participant-a', sessionId: 'session-a', roleId: 'implementer', roleVersion: '1',
      displayName: '实现伙伴', collaborationRole: 'implementer', status: 'active', ordinal: 1,
    }],
    workItems: [{
      id: 'work-a', roomId: 'room-live', topicId: '', rootTurnId: 'root-a', rootWorkId: 'work-a', parentWorkId: '',
      objective: '完成 Room Focus 生产迁移', expectedOutput: '真实 WorkItem 与 Tool 上下文', acceptanceCriteria: ['不使用静态候选数据'],
      accountableParticipantId: 'participant-a', currentOwnerParticipantId: 'participant-a', offeredToParticipantId: '',
      createdByParticipantId: 'participant-root', clientMessageId: 'client-a', state: 'active', depth: 0, revision: 1,
      resultSummary: '', artifactRefs: [], evidenceRefs: [], blocker: {}, acceptedTurnId: 'turn-a',
      createdAtMs: 100, updatedAtMs: 110, completedAtMs: null,
    }],
  };
}
