import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { PawContextTrace, projectionTraceTurns } from './PawContextTrace';

afterEach(cleanup);

describe('PawContextTrace evidence access', () => {
  it('opens a trace node without captured body to its real capture record with a safe copy', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': {
          ok: true,
          items: [{ traceId: 'trace-a', sessionId: 'session-a', turnId: 'turn-a' }],
        },
        'agent.session.contextTrace.get': contextTraceResponse(),
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('tab', { name: '上下文装配' }));

    const memoryNode = (await screen.findByText('记忆注入', { selector: '.n-label' })).closest('details');
    expect(memoryNode).not.toBeNull();
    await user.click(memoryNode!.querySelector('summary')!);
    expect(memoryNode).toHaveAttribute('open');

    const record = within(memoryNode!).getByRole('region', { name: '节点捕获记录，可滚动原文' });
    expect(record).toHaveTextContent('"stage": "memory"');
    expect(record).toHaveTextContent('"summary": "3 条偏好"');
    expect(record).toHaveTextContent('"itemCount": 3');
    expect(within(memoryNode!).getByText('contextTrace 未附带该阶段的原文捕获；以上为该节点记录的全部真实字段。')).toBeInTheDocument();

    await user.click(within(memoryNode!).getByRole('button', { name: '复制节点捕获记录' }));
    expect(await within(memoryNode!).findByRole('button', { name: '复制节点捕获记录：已复制' })).toBeInTheDocument();
    await expect(navigator.clipboard.readText()).resolves.toContain('"stage": "memory"');
  });

  it('lists context assembly nodes in the authoritative ordinal order', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': {
          ok: true,
          items: [{ traceId: 'trace-a', sessionId: 'session-a', turnId: 'turn-a' }],
        },
        'agent.session.contextTrace.get': contextTraceResponse(),
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('tab', { name: '上下文装配' }));
    await screen.findByText('项目约束', { selector: '.n-label' });

    const nodes = [...document.querySelectorAll('.an-node')];
    expect(nodes.map((node) => node.querySelector('.n-ord')?.textContent)).toEqual(['1', '2', '3']);
    expect(nodes.map((node) => node.querySelector('.n-label')?.textContent))
      .toEqual(['项目约束', '记忆注入', '当前输入']);
    // The token bar reads as the same assembly sequence as the node list.
    expect([...document.querySelectorAll('.an-tokenbar > span')].map((segment) => segment.getAttribute('title')))
      .toEqual(['project 300', 'memory 105', 'input 40']);
  });

  it('shows line and character counts with a copy action on captured assembly evidence', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('tab', { name: '上下文装配' }));

    const systemNode = screen.getByText('系统指令', { selector: '.n-label' }).closest('details');
    expect(systemNode).not.toBeNull();
    await user.click(systemNode!.querySelector('summary')!);

    const evidence = within(systemNode!).getByRole('region', { name: '本次模型调用收到的系统指令，可滚动原文' });
    expect(evidence).toHaveTextContent('真实系统提示');
    expect(within(systemNode!).getByText('1 行 · 6 字符')).toBeInTheDocument();
    await user.click(within(systemNode!).getByRole('button', { name: '复制本次模型调用收到的系统指令' }));
    await expect(navigator.clipboard.readText()).resolves.toBe('真实系统提示');
  });
});

describe('PawContextTrace', () => {
  it('renders the turn-grouped projection trace and keeps real context assembly available', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': {
          ok: true,
          items: [{ traceId: 'trace-a', sessionId: 'session-a', turnId: 'turn-a' }],
        },
        'agent.session.contextTrace.get': contextTraceResponse(),
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace
          active
          projection={{
            turnOrder: ['turn-a'],
            turnsById: {
              'turn-a': {
                id: 'turn-a',
                status: 'completed',
                messageIds: ['message-a'],
                activityIds: [],
                createdAtMs: 100,
                updatedAtMs: 200,
              },
            },
            messageOrder: ['message-a'],
            messagesById: {
              'message-a': {
                id: 'message-a',
                sessionId: 'session-a',
                turnId: 'turn-a',
                role: 'assistant',
                status: 'completed',
                createdAtMs: 120,
                completedAtMs: 180,
                blocks: [{ type: 'text', data: { text: '已完成真实上下文检查' } }],
                attachments: [],
              },
            },
            activitiesById: {},
          } as never}
          sessionId="session-a"
        />
      </ControlTransportProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'T1 · Agent 轨迹' })).toBeInTheDocument();
    expect(screen.getByText('TURN #1')).toBeInTheDocument();
    expect(screen.getByText('Agent 回复')).toBeInTheDocument();
    expect(screen.queryByText('已完成真实上下文检查')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '全部1' })).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining([
        'agent.session.debugContext.get',
        'agent.session.contextTraces.list',
        'agent.session.contextTrace.get',
      ]),
    ));

    const messageEvent = screen.getByText('Agent 回复').closest('details');
    expect(messageEvent).not.toBeNull();
    const messageSummary = messageEvent!.querySelector('summary');
    expect(messageSummary).not.toBeNull();
    expect(messageSummary).toHaveAttribute('aria-controls');
    messageSummary!.focus();
    await user.keyboard('{Enter}');
    expect(messageEvent).toHaveAttribute('open');
    expect(messageSummary).toHaveFocus();
    expect(within(messageEvent!).getByText('已完成真实上下文检查')).toBeInTheDocument();
    const messageEvidence = within(messageEvent!).getByRole('region', { name: 'Agent 回复事件证据' });

    await user.click(messageSummary!);
    expect(messageSummary).toHaveAttribute('aria-expanded', 'false');
    expect(messageEvidence).toBeInTheDocument();
    const messageReveal = messageEvent!.querySelector('.agent-smooth-reveal');
    expect(messageReveal).not.toBeNull();
    expect(messageReveal).toHaveAttribute('aria-hidden', 'true');
    expect(messageReveal).toHaveAttribute('inert');
    fireEvent.transitionEnd(messageReveal!, { propertyName: 'height' });
    expect(within(messageEvent!).queryByText('已完成真实上下文检查')).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '上下文装配' }));
    expect(await screen.findByText('项目约束')).toBeInTheDocument();
    expect(screen.getByText(/模型调用 · 1/)).toBeInTheDocument();
    expect(screen.queryByText('参数已记录')).not.toBeInTheDocument();
    const modelCall = document.querySelector<HTMLElement>('.an-call');
    expect(modelCall).not.toBeNull();
    await user.click(modelCall!.querySelector('summary')!);
    expect(within(modelCall!).getByText('参数已记录')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('rm -rf /private/secret');
    expect(document.body).not.toHaveTextContent('/Users/undo/private.key');
    expect(document.body).not.toHaveTextContent('token=super-secret');
  });

  it('keeps messages, tools and approvals in one real sequence inside their turn', () => {
    const turns = projectionTraceTurns({
      turnOrder: ['turn-a'],
      turnsById: {
        'turn-a': {
          id: 'turn-a', status: 'waiting', messageIds: ['user-a'], activityIds: ['tool-a', 'approval-a', 'subagent-a'], createdAtMs: 100, updatedAtMs: 150,
        },
      },
      messagesById: {
        'user-a': {
          id: 'user-a', sessionId: 'session-a', turnId: 'turn-a', role: 'user', status: 'completed', createdAtMs: 100,
          timelineSequence: 1, blocks: [{ type: 'text', data: { text: '执行真实工作' } }], attachments: [{ id: 'private-attachment' }],
        },
      },
      activitiesById: {
        'tool-a': {
          id: 'tool-a', turnId: 'turn-a', kind: 'tool_finished', status: 'completed', summary: '完成读取',
          payload: { toolName: 'workspace.read' }, createdAtMs: 120, updatedAtMs: 125, timelineSequence: 2,
        },
        'approval-a': {
          id: 'approval-a', turnId: 'turn-a', kind: 'approval_required', status: 'waiting', summary: '等待写入确认',
          payload: {}, createdAtMs: 130, updatedAtMs: 140, timelineSequence: 3,
        },
        'subagent-a': {
          id: 'subagent-a', turnId: 'turn-a', kind: 'tool_finished', status: 'completed', summary: '独立复核完成',
          payload: { toolName: 'subagent' }, createdAtMs: 145, updatedAtMs: 150, timelineSequence: 4,
        },
      },
    } as never);

    expect(turns[0]?.events.map((event) => [event.type, event.category])).toEqual([
      ['user.prompt', 'msg'],
      ['tool.end', 'tool'],
      ['approval.req', 'appr'],
      ['sub.end', 'sub'],
    ]);
    expect(turns[0]?.title).toBe('用户输入 · 6 字 · 含 1 个附件');
    expect(turns[0]?.title).not.toContain('执行真实工作');
  });

  it('filters the event projection structurally and keeps the current Session tail visible', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace
          active
          projection={{
            turnOrder: ['turn-a'],
            turnsById: {
              'turn-a': {
                id: 'turn-a', status: 'running', messageIds: ['user-a'], activityIds: ['tool-a'],
                createdAtMs: 100, updatedAtMs: 150,
              },
            },
            messagesById: {
              'user-a': {
                id: 'user-a', sessionId: 'session-a', turnId: 'turn-a', role: 'user', status: 'completed',
                createdAtMs: 100, timelineSequence: 1,
                blocks: [{ type: 'text', data: { text: '不要把正文复制进轨迹' } }], attachments: [],
              },
            },
            activitiesById: {
              'tool-a': {
                id: 'tool-a', turnId: 'turn-a', kind: 'tool_progress', status: 'running',
                summary: '读取 18 / 24', payload: {
                  toolName: 'workspace.read',
                  args: { path: 'src/features/agent/timeline/AgentTimeline.tsx' },
                  result: { files: 1, lines: 286 },
                  authorization: 'Bearer private-value',
                },
                createdAtMs: 140, updatedAtMs: 150, timelineSequence: 2,
              },
            },
          } as never}
          sessionId="session-a"
        />
      </ControlTransportProvider>,
    );

    expect(await screen.findByText(/Session 进行中 · 最后事件 workspace\.read/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '工具1' }));
    const toolEvent = screen.getByText('workspace.read', { selector: 'strong' }).closest('details');
    expect(toolEvent).not.toBeNull();
    const toolSummary = toolEvent!.querySelector('summary');
    expect(toolSummary).not.toBeNull();
    await user.click(toolSummary!);
    expect(toolEvent).toHaveAttribute('open');
    expect(within(toolEvent!).getByText('调用参数')).toBeInTheDocument();
    expect(within(toolEvent!).getByText('工具返回')).toBeInTheDocument();
    expect(within(toolEvent!).getByText('事件载荷')).toBeInTheDocument();
    expect(toolEvent).not.toHaveTextContent('Bearer private-value');
    expect(toolEvent).not.toHaveTextContent('已隐藏敏感字段');
    const eventPayloadDisclosure = within(toolEvent!).getByText('事件载荷').closest('details');
    expect(eventPayloadDisclosure).not.toBeNull();
    await user.click(eventPayloadDisclosure!.querySelector('summary')!);
    expect(eventPayloadDisclosure).not.toHaveTextContent('Bearer private-value');
    expect(eventPayloadDisclosure).toHaveTextContent('已隐藏敏感字段');
    const argsDisclosure = within(toolEvent!).getByText('调用参数').closest('details');
    expect(argsDisclosure).not.toBeNull();
    expect(within(argsDisclosure!).queryByRole('region', { name: '调用参数，可滚动原文' })).not.toBeInTheDocument();
    await user.click(argsDisclosure!.querySelector('summary')!);
    const argsRegion = within(argsDisclosure!).getByRole('region', { name: '调用参数，可滚动原文' });
    expect(argsRegion).toHaveAttribute('tabindex', '0');
    expect(argsRegion).toHaveTextContent('AgentTimeline.tsx');

    await user.click(screen.getByRole('button', { name: '消息1' }));
    expect(screen.queryByText('workspace.read', { selector: 'strong' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '工具1' }));
    const restoredToolEvent = screen.getByText('workspace.read', { selector: 'strong' }).closest('details');
    expect(restoredToolEvent).toHaveAttribute('open');
    expect(screen.queryByText('用户输入')).not.toBeInTheDocument();
  });

  it('turns the non-resident runtime code into a clear recovery state', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': {
          available: false,
          transient: true,
          sessionId: 'session-sleeping',
          turnId: '',
          error: 'session_not_resident',
          availableTurns: [],
          telemetry: {},
        },
      },
    });

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-sleeping" />
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('这段 Session 当前未驻留 Pi Runtime。重新打开或发送一条消息后，再查看 Agent 轨迹。')).toBeInTheDocument();
  });

  it('turns a Runtime snapshot timeout into readable copy with a working retry', async () => {
    let attempts = 0;
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': () => {
          attempts += 1;
          return attempts === 1 ? {
            available: false,
            transient: true,
            sessionId: 'session-timeout',
            turnId: '',
            error: 'runtime_unresponsive',
            availableTurns: [],
            telemetry: {},
          } : debugContextResponse();
        },
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-timeout" />
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('Runtime 未及时返回轨迹快照；对话不受影响。请稍后重新读取。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重新读取' }));
    expect(await screen.findByRole('heading', { name: 'T1 · Agent 轨迹' })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it('does not let a late turn request replace the newer selected turn', async () => {
    const lateTurnB = deferred<ReturnType<typeof debugContextResponseForTurn>>();
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': (request: ControlRequest) => {
          const turnId = typeof request.query?.turnId === 'string' ? request.query.turnId : '';
          if (turnId === 'turn-b') return lateTurnB.promise;
          return debugContextResponseForTurn('turn-a');
        },
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'T1 · Agent 轨迹' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: '上下文装配' }));
    await user.click(screen.getByRole('button', { name: /T2.*轮次 B/ }));
    await waitFor(() => expect(transport.requests.some(({ request }) => request.query?.turnId === 'turn-b')).toBe(true));
    await user.click(screen.getByRole('button', { name: /T1.*轮次 A/ }));
    await waitFor(() => expect(transport.requests.some(({ request }) => request.query?.turnId === 'turn-a')).toBe(true));

    await act(async () => {
      lateTurnB.resolve(debugContextResponseForTurn('turn-b'));
      await lateTurnB.promise;
    });

    expect(screen.getByRole('heading', { name: 'T1 · Agent 轨迹' })).toBeInTheDocument();
    expect(screen.getByText('model-a')).toBeInTheDocument();
    expect(screen.queryByText('model-b')).not.toBeInTheDocument();
  });

  it('bounds inconsistent cache evidence to a readable percentage', async () => {
    const base = debugContextResponse();
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': {
          ...base,
          context: {
            ...base.context,
            cacheEvidence: [{
              requestIndex: 2,
              prefixSha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
              prefixBytes: 18_240,
              deltaBytes: 2_180,
              duplicateBytes: 18_240,
              inputTokens: 7_200,
              outputTokens: 3_562,
              cacheReadTokens: 64_800,
              cacheWriteTokens: 0,
              capability: 'reported',
            }],
          },
        },
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('tab', { name: '上下文装配' }));
    expect(await screen.findByText(/缓存读取/)).toHaveTextContent('缓存读取 64,800 tok（100%）');
    expect(document.body).not.toHaveTextContent('900%');
  });

  it('opens every fallback assembly node to the concrete captured context with pointer and keyboard', async () => {
    const base = debugContextResponse();
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': {
          ...base,
          context: {
            ...base.context,
            prompt: '本轮用户输入：逐项检查装配',
            systemPrompt: '完整系统指令：遵循项目边界。',
            toolSchemas: [{ name: 'workspace.read', description: '读取工作区文件' }],
            activeTools: ['workspace.read'],
            modelCalls: [{
              ...base.context.modelCalls[0],
              contextMessages: [{ role: 'user', content: '保留上下文消息原文' }],
              providerContext: {
                ...base.context.modelCalls[0].providerContext,
                messages: [{ role: 'user', content: '保留上下文消息原文' }],
              },
            }],
          },
        },
        'agent.session.contextTraces.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('tab', { name: '上下文装配' }));

    const cases = [
      ['系统指令', '完整系统指令：遵循项目边界。'],
      ['工具定义', '读取工作区文件'],
      ['上下文消息', '保留上下文消息原文'],
      ['当前输入', '本轮用户输入：逐项检查装配'],
    ] as const;
    for (const [label, expected] of cases) {
      const details = screen.getByText(label, { selector: '.n-label' }).closest('details');
      expect(details).not.toBeNull();
      expect(details).not.toHaveAttribute('open');
      const summary = details!.querySelector('summary');
      expect(summary).not.toBeNull();
      expect(within(details!).queryByText(expected, { exact: false })).not.toBeInTheDocument();
      await user.click(summary!);
      expect(details).toHaveAttribute('open');
      expect(within(details!).getByText(expected, { exact: false })).toBeInTheDocument();
    }

    const systemDetails = screen.getByText('系统指令', { selector: '.n-label' }).closest('details')!;
    const systemSummary = systemDetails.querySelector('summary')!;
    systemSummary.focus();
    await user.keyboard('{Enter}');
    expect(systemSummary).toHaveAttribute('aria-expanded', 'false');
    expect(systemDetails).toHaveAttribute('open');
    expect(systemDetails.querySelector('.ui-disclosure__reveal')).toHaveAttribute('inert');
    await waitFor(() => expect(systemDetails).not.toHaveAttribute('open'));
    expect(systemSummary).toHaveFocus();
  });

  it('guides an event-empty debug turn to its real context assembly', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.session.debugContext.get': debugContextResponse(),
        'agent.session.contextTraces.list': {
          ok: true,
          items: [{ traceId: 'trace-a', sessionId: 'session-a', turnId: 'turn-a' }],
        },
        'agent.session.contextTrace.get': contextTraceResponse(),
      },
    });
    const user = userEvent.setup();

    render(
      <ControlTransportProvider transport={transport}>
        <PawContextTrace active sessionId="session-a" />
      </ControlTransportProvider>,
    );

    const empty = await screen.findByRole('status', { name: '当前轮次没有可投影事件' });
    expect(empty).toHaveTextContent('T1 暂无可投影的 Session 事件');
    expect(empty).toHaveTextContent('上下文装配记录可用');
    await user.click(screen.getByRole('button', { name: '查看上下文装配' }));
    expect(await screen.findByText('项目约束')).toBeInTheDocument();
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

function debugContextResponseForTurn(turnId: 'turn-a' | 'turn-b') {
  const base = debugContextResponse();
  const turnA = {
    ...base.availableTurns[0],
    turnId: 'turn-a',
    turnOrdinal: 1,
    summary: '轮次 A',
  };
  const turnB = {
    ...base.availableTurns[0],
    turnId: 'turn-b',
    turnOrdinal: 2,
    summary: '轮次 B',
    capturedAtMs: 300,
    updatedAtMs: 400,
  };
  return {
    ...base,
    turnId,
    availableTurns: [turnA, turnB],
    context: {
      ...base.context,
      turnId,
      model: {
        ...base.context.model,
        modelId: turnId === 'turn-a' ? 'model-a' : 'model-b',
      },
    },
  };
}

function debugContextResponse() {
  return {
    available: true,
    transient: true,
    sessionId: 'session-a',
    turnId: 'turn-a',
    availableTurns: [{
      turnId: 'turn-a',
      turnOrdinal: 1,
      assemblyPhase: 'initial',
      summary: '检查真实上下文',
      capturedAtMs: 100,
      updatedAtMs: 200,
      modelCallCount: 1,
      providerRequestCount: 1,
      toolCallCount: 1,
      runningToolCount: 0,
    }],
    context: {
      sessionId: 'session-a',
      turnId: 'turn-a',
      capturedAtMs: 100,
      updatedAtMs: 200,
      prompt: '检查真实上下文',
      systemPrompt: '真实系统提示',
      systemPromptOptions: { cwd: '/work/paw' },
      model: { provider: 'openai', modelId: 'gpt-5.6-sol' },
      activeTools: ['read'],
      toolSchemas: [{ name: 'read' }],
      cacheEvidence: [],
      modelCalls: [{
        index: 0,
        runtimeTurnIndex: 0,
        capturedAtMs: 110,
        updatedAtMs: 190,
        completedAtMs: 190,
        contextMessages: [{ role: 'user', content: '检查真实上下文' }],
        providerContext: { messages: [{ role: 'user', content: '检查真实上下文' }] },
        contextDelta: { commonPrefixMessages: 0, removedMessageCount: 0, addedMessageCount: 1, addedMessages: [] },
        providerExchanges: [{ index: 0, capturedAtMs: 115, status: 200, headers: {}, payload: {} }],
        assistantMessage: { role: 'assistant', content: '完成' },
      }],
      toolExecutions: [{
        toolCallId: 'tool-sensitive',
        toolName: 'exec',
        modelCallIndex: 1,
        runtimeTurnIndex: 0,
        startedAtMs: 130,
        endedAtMs: 150,
        startSequence: 1,
        endSequence: 2,
        args: {
          command: 'rm -rf /private/secret',
          path: '/Users/undo/private.key',
          query: 'token=super-secret',
          payload: { authorization: 'Bearer hidden' },
        },
        result: { ok: true },
        status: 'completed',
        updates: [],
      }],
      toolBatches: [],
    },
    telemetry: {},
  };
}

function contextTraceResponse() {
  return {
    schemaVersion: 'rag-ime.agent-context-trace.v1',
    traceId: 'trace-a',
    sessionId: 'session-a',
    turnId: 'turn-a',
    sourceKind: 'user',
    status: 'accepted',
    finalFingerprint: 'sha256:abcdef0123456789',
    /* Deliberately out of assembly order: the authoritative sequence is
       node.ordinal, not the order this payload happens to arrive in. */
    nodes: [{
      nodeId: 'node-memory',
      ordinal: 2,
      stage: 'memory',
      label: '记忆注入',
      sourceKind: 'memory',
      disposition: 'included',
      summary: '3 条偏好',
      charCount: 420,
      tokenEstimate: 105,
      durationMs: 1,
      fingerprint: 'sha256:fedcba9876543210',
      reason: '',
      metadata: { itemCount: 3 },
      createdAtMs: 103,
    }, {
      nodeId: 'node-input',
      ordinal: 3,
      stage: 'input',
      label: '当前输入',
      sourceKind: 'user',
      disposition: 'included',
      summary: '本轮用户输入',
      charCount: 160,
      tokenEstimate: 40,
      durationMs: 0,
      fingerprint: 'sha256:abcd0123abcd0123',
      reason: '',
      metadata: {},
      createdAtMs: 104,
    }, {
      nodeId: 'node-project',
      ordinal: 1,
      stage: 'project',
      label: '项目约束',
      sourceKind: 'project',
      disposition: 'included',
      summary: 'AGENTS.md',
      charCount: 1200,
      tokenEstimate: 300,
      durationMs: 2,
      fingerprint: 'sha256:0123456789abcdef',
      reason: '',
      metadata: {},
      createdAtMs: 102,
    }],
    edges: [],
    createdAtMs: 100,
    updatedAtMs: 200,
  };
}
