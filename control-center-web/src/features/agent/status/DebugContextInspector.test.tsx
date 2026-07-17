import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { StubControlTransport } from '@/test/stub-control-transport';
import { DebugContextInspector } from './DebugContextInspector';

afterEach(cleanup);

describe('DebugContextInspector', () => {
  it('shows the real runtime prompt, system prompt, provider payload, and cache telemetry', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        schemaVersion: 'rag-ime.pi-debug-context-response.v1',
        available: true,
        transient: true,
        context: {
          prompt: 'RAW_RUNTIME_INPUT',
          systemPrompt: 'RAW_SYSTEM_PROMPT',
          systemPromptOptions: { cwd: '/tmp/project' },
          activeTools: ['read'],
          toolSchemas: [{ name: 'read', parameters: { type: 'object' } }],
          contextWindows: [{ index: 1, messages: [{ role: 'user', content: 'RAW_CONTEXT' }] }],
          providerRequests: [{ index: 1, payload: { model: 'model-a', messages: ['RAW_PROVIDER_PAYLOAD'] } }],
          modelCalls: [{ index: 1, contextDelta: { addedMessageCount: 1 } }],
          toolExecutions: [{ toolCallId: 'call-1', toolName: 'workspace_list', args: { depth: 3 } }],
          toolBatches: [{ id: 'batch-1', executionMode: 'serial', toolCallIds: ['call-1'] }],
        },
        telemetry: {
          latestCacheHitPercent: 75,
          context: { tokens: 12_000, contextWindow: 100_000 },
          latestUsage: { input: 1_000, output: 250, cacheRead: 3_000, cacheWrite: 0 },
        },
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <DebugContextInspector sessionId="session-1" turnId="turn-1" />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('RAW_RUNTIME_INPUT')).toBeVisible();
    expect(screen.getByLabelText('本轮上下文与缓存指标')).toHaveTextContent('75%');
    const sections = screen.getByRole('navigation', { name: '原始上下文部分' });
    await user.click(within(sections).getByRole('button', { name: /System Prompt/ }));
    expect(screen.getByText('RAW_SYSTEM_PROMPT')).toBeVisible();
    await user.click(within(sections).getByRole('button', { name: /Provider 请求 1/ }));
    expect(screen.getByText(/RAW_PROVIDER_PAYLOAD/)).toBeVisible();
    await user.click(within(sections).getByRole('button', { name: /工具调用实录/ }));
    expect(screen.getByText(/workspace_list/)).toBeVisible();
    await user.click(within(sections).getByRole('button', { name: /工具执行批次/ }));
    expect(screen.getByText(/batch-1/)).toBeVisible();
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId: 'session-1' },
      query: { turnId: 'turn-1' },
    }));
  });

  it('shows the concrete runtime error instead of guessing why context is unavailable', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': () => {
        throw new Error('本机原始上下文调试尚未启用');
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <DebugContextInspector sessionId="session-1" turnId="turn-1" />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('本机原始上下文调试尚未启用')).toBeVisible();
  });
});
