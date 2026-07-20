import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { ContextDebugFeature } from '.';

afterEach(cleanup);

describe('ContextDebugFeature', () => {
  it('shows every model-call delta and truthful parallel tool batch', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': {
          ok: true,
          sessions: [{
            id: 'session-a',
            title: 'Debug 会话',
            mode: 'assistant',
            status: 'idle',
            roleId: 'companion-present-v1',
            roleVersion: '1',
            updatedAtMs: 100,
            workspaceRoots: ['/Volumes/work'],
          }],
        },
        'agent.session.debugContext.get': debugContextResponse(),
      },
    });
    renderFeature(transport, '/context-debug?sessionId=session-a');

    expect(await screen.findByText('上下文透视')).toBeInTheDocument();
    expect(screen.getByText('Stable prefix')).toBeInTheDocument();
    expect(screen.getByText('来源正文默认隐藏。', { exact: false })).toBeInTheDocument();
    await user.click(screen.getByText('展开原始审计区'));
    expect(await screen.findByText('并行 2 项')).toBeInTheDocument();
    expect(screen.getByText('memory_search')).toBeInTheDocument();
    expect(screen.getByText('ime_overview')).toBeInTheDocument();

    const callRail = screen.getByRole('complementary', { name: 'LLM 调用列表' });
    await user.click(within(callRail).getByRole('button', { name: /模型调用 1/ }));
    expect(screen.getByText('初始上下文')).toBeInTheDocument();
    expect(screen.getAllByText('+1').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('tab', { name: 'Provider 请求' }));
    expect(screen.getByText(/"model": "gpt-test"/)).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.session.debugContext.get'
      && call.request.params?.sessionId === 'session-a'
    ))).toBe(true));
  });

  it('explains that raw context is transient when the runtime has no snapshot', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.sessions.list': { ok: true, sessions: [] },
        'agent.session.debugContext.get': {
          available: false,
          transient: true,
          sessionId: 'session-missing',
          turnId: '',
          error: '本机原始上下文调试尚未启用',
          availableTurns: [],
        },
      },
    });
    renderFeature(transport, '/context-debug?sessionId=session-missing');

    expect(await screen.findByText('本机原始上下文调试尚未启用')).toBeInTheDocument();
    expect(screen.getByText('指定会话', { exact: false })).toBeInTheDocument();
  });

  it('keeps long prompt bodies hidden until the user opens the audit payload', async () => {
    const user = userEvent.setup();
    const payload = debugContextResponse();
    const longPrompt = `LONG_PRIVATE_PROMPT_${'x'.repeat(4_000)}`;
    payload.context.prompt = longPrompt;
    Object.assign(payload.context, { contextProjection: {
      stablePrefixMessages: 18,
      dynamicTailMessages: 3,
      sealedMessages: 44,
      pendingMessages: 1,
      compactionState: 'sealed',
      recoveryState: 'ready',
    }, cacheEvidence: [{ requestIndex: 2, prefixSha256: 'abc', prefixBytes: 1024, deltaBytes: 64, duplicateBytes: 1024, inputTokens: 1400, outputTokens: 20, cacheReadTokens: 1200, cacheWriteTokens: 80, capability: 'reported' }] });
    payload.telemetry = { cumulativeUsage: { cacheRead: 1200, cacheWrite: 80 } };
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': { ok: true, sessions: [{ id: 'session-a', title: 'Long prompt', mode: 'assistant', status: 'idle', roleId: 'companion-future-v1', roleVersion: '1', updatedAtMs: 1, workspaceRoots: [] }] },
      'agent.session.debugContext.get': payload,
    } });
    renderFeature(transport, '/context-debug?sessionId=session-a');

    expect(await screen.findByText('1,200 tokens')).toBeVisible();
    expect(screen.getByText('supported · hit')).toBeVisible();
    expect(screen.getByText(/sealed \/ ready/)).toBeVisible();
    expect(document.body).not.toHaveTextContent(longPrompt);
    await user.click(screen.getByText('展开原始审计区'));
    await user.click(screen.getByRole('tab', { name: 'Runtime 输入' }));
    expect(screen.getByText(longPrompt)).toBeVisible();
  });
});

function renderFeature(transport: MockControlTransport, initialEntry: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <ContextDebugFeature />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function debugContextResponse() {
  return {
    available: true,
    transient: true,
    sessionId: 'session-a',
    turnId: 'turn-a',
    availableTurns: [{ turnId: 'turn-a', capturedAtMs: 100, updatedAtMs: 300, modelCallCount: 2, providerRequestCount: 2, toolCallCount: 2, runningToolCount: 0 }],
    context: {
      sessionId: 'session-a',
      turnId: 'turn-a',
      capturedAtMs: 100,
      updatedAtMs: 300,
      prompt: '原始用户输入',
      systemPrompt: '系统提示词',
      systemPromptOptions: { cwd: '/Volumes/work' },
      model: { provider: 'gpt', name: 'GPT Test' },
      activeTools: ['memory_search', 'ime_overview'],
      toolSchemas: [{ name: 'memory_search' }, { name: 'ime_overview' }],
      modelCalls: [
        {
          index: 1,
          runtimeTurnIndex: 0,
          capturedAtMs: 100,
          updatedAtMs: 180,
          completedAtMs: 180,
          contextMessages: [{ role: 'user', content: '检查缓存' }],
          contextDelta: { commonPrefixMessages: 0, removedMessageCount: 0, addedMessageCount: 1, addedMessages: [{ role: 'user', content: '检查缓存' }] },
          providerExchanges: [{ index: 1, capturedAtMs: 120, status: 200, headers: { request: 'one' }, payload: { model: 'gpt-test', input: '检查缓存' } }],
          assistantMessage: { role: 'assistant', content: [{ type: 'toolCall', name: 'memory_search' }] },
        },
        {
          index: 2,
          runtimeTurnIndex: 1,
          capturedAtMs: 220,
          updatedAtMs: 300,
          completedAtMs: 300,
          contextMessages: [{ role: 'user', content: '检查缓存' }, { role: 'toolResult', content: '命中' }],
          contextDelta: { baseCallIndex: 1, commonPrefixMessages: 1, removedMessageCount: 0, addedMessageCount: 1, addedMessages: [{ role: 'toolResult', content: '命中' }] },
          providerExchanges: [{ index: 2, capturedAtMs: 240, status: 200, headers: { request: 'two' }, payload: { model: 'gpt-test', input: '命中' } }],
          assistantMessage: { role: 'assistant', content: '完成' },
        },
      ],
      toolExecutions: [
        { toolCallId: 'tool-1', toolName: 'memory_search', modelCallIndex: 1, runtimeTurnIndex: 0, startedAtMs: 130, endedAtMs: 170, startSequence: 1, endSequence: 4, args: { query: '缓存' }, result: { count: 2 }, status: 'completed', updates: [] },
        { toolCallId: 'tool-2', toolName: 'ime_overview', modelCallIndex: 1, runtimeTurnIndex: 0, startedAtMs: 135, endedAtMs: 165, startSequence: 2, endSequence: 3, args: { op: 'status' }, result: { healthy: true }, status: 'completed', updates: [] },
      ],
      toolBatches: [{ id: 'batch-1', modelCallIndex: 1, runtimeTurnIndex: 0, stage: 1, executionMode: 'parallel', startedAtMs: 130, endedAtMs: 170, status: 'completed', toolCallIds: ['tool-1', 'tool-2'] }],
    },
    telemetry: {},
  };
}
