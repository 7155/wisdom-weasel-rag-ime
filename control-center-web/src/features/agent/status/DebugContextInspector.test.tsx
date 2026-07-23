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
  it('explains that a snapshot was lost after a non-persistent Runtime restarted', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        schemaVersion: 'rag-ime.pi-debug-context-response.v1',
        available: false,
        transient: true,
        context: null,
        storage: {
          persistent: false,
          directory: '',
          usedBytes: 0,
          maxBytes: 64 * 1024 * 1024,
        },
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <DebugContextInspector sessionId="session-lost" turnId="turn-lost" />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(await screen.findByText('仅保留当前 Runtime')).toBeVisible();
    expect(screen.getByText('本轮快照只存在于原 Runtime；Runtime 重启后已经无法恢复')).toBeVisible();
    expect(screen.queryByText('这轮尚未生成上下文快照')).not.toBeInTheDocument();
  });

  it('keeps the exact provider payload visible when the provider returns an error', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        schemaVersion: 'rag-ime.pi-debug-context-response.v1',
        available: true,
        transient: false,
        context: {
          systemPrompt: 'SYSTEM_BEFORE_FAILURE',
          activeTools: ['workspace_read'],
          modelCalls: [{
            providerExchanges: [{ index: 1, status: 400 }],
          }],
          providerRequests: [{
            index: 1,
            payload: {
              model: 'gpt-5.6-luna',
              input: [{ role: 'user', content: 'REQUEST_BEFORE_FAILURE' }],
              reasoning: { effort: 'max' },
            },
          }],
        },
        storage: {
          persistent: true,
          directory: '/tmp/debug-context',
          usedBytes: 2048,
          maxBytes: 64 * 1024 * 1024,
        },
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <DebugContextInspector sessionId="session-failed" turnId="turn-failed" />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    const providerStage = await screen.findByRole('button', { name: /Provider 请求 1/ });
    expect(providerStage).toHaveTextContent('HTTP 400');
    await user.click(providerStage);
    expect(screen.getByText(/REQUEST_BEFORE_FAILURE/)).toBeVisible();
    expect(screen.getByText(/请求已到达 Provider 边界并返回失败/)).toBeVisible();
    expect(screen.queryByText('本轮还没有到达可核对的 Provider 请求边界')).not.toBeInTheDocument();
  });

  it('shows prompt inputs as ordered deltas and separates the provider wire envelope', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        schemaVersion: 'rag-ime.pi-debug-context-response.v1',
        available: true,
        transient: true,
        context: {
          prompt: 'RAW_RUNTIME_INPUT',
          systemPrompt: 'BASE_SYSTEM\nPROJECT_RULES\nCurrent working directory: /tmp/project',
          systemPromptOptions: {
            customPrompt: 'BASE_SYSTEM',
            contextFiles: [{ path: '/tmp/project/AGENTS.md', content: 'PROJECT_RULES' }],
            skills: [{ name: 'inspect', description: 'Inspect runtime state', filePath: '/skills/inspect/SKILL.md' }],
            cwd: '/tmp/project',
          },
          activeTools: ['read'],
          toolSchemas: [{ name: 'read', parameters: { type: 'object' } }],
          contextWindows: [{ index: 1, messages: [{ role: 'user', content: 'RAW_CONTEXT' }] }],
          providerRequests: [{ index: 1, payload: { model: 'model-a', messages: ['RAW_PROVIDER_PAYLOAD'] } }],
        },
        telemetry: {
          latestCacheHitPercent: 75,
          context: { tokens: 12_000, contextWindow: 100_000 },
          latestUsage: { input: 1_000, output: 250, cacheRead: 3_000, cacheWrite: 0 },
        },
        storage: {
          persistent: true,
          directory: '/Volumes/undo 4t/Archives/RagIme/debug-context',
          usedBytes: 1024,
          maxBytes: 1073741824,
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

    expect(await screen.findByText('System 基础指令')).toBeVisible();
    expect(screen.getByLabelText('本轮上下文与缓存指标')).toHaveTextContent('75%');
    expect(screen.getByText('/Volumes/undo 4t/Archives/RagIme/debug-context')).toBeVisible();
    const pipeline = screen.getByRole('list', { name: '模型上下文注入顺序' });
    const stages = within(pipeline).getAllByRole('button').map((item) => item.textContent ?? '');
    expect(stages).toEqual(expect.arrayContaining([
      expect.stringContaining('System 基础指令'),
      expect.stringContaining('AGENTS.md'),
      expect.stringContaining('Skills 目录'),
      expect.stringContaining('活动工具定义'),
      expect.stringContaining('当前用户输入'),
      expect.stringContaining('Provider 请求 1'),
    ]));
    await user.click(within(pipeline).getByText('System 基础指令'));
    expect(screen.getByText('BASE_SYSTEM')).toBeVisible();
    await user.click(within(pipeline).getByText('AGENTS.md'));
    expect(screen.getByText('PROJECT_RULES')).toBeVisible();
    expect(screen.queryByText('BASE_SYSTEM')).not.toBeInTheDocument();
    await user.click(within(pipeline).getByText('Provider 请求 1'));
    expect(screen.getByLabelText('Provider 请求 1详情')).toBeVisible();
    expect(screen.getByText(/RAW_PROVIDER_PAYLOAD/)).toBeVisible();
    expect(screen.getByText(/API 线上的 JSON 信封/)).toBeVisible();
    expect(screen.getByRole('radiogroup', { name: '上下文展示形式' })).toHaveTextContent('模型语义');
    await user.click(screen.getByRole('radio', { name: '原始 JSON' }));
    expect(within(pipeline).getByText('传输 JSON')).toBeVisible();
    expect(screen.getByText(/"messages":/)).toBeVisible();
    await user.click(screen.getByRole('button', { name: '关闭上下文详情' }));
    expect(screen.queryByLabelText('Provider 请求 1详情')).not.toBeInTheDocument();
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId: 'session-1' },
      query: { turnId: 'turn-1' },
    }));
  });
});
