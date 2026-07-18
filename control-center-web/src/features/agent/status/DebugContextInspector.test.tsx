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
    const summaries = within(pipeline).getAllByRole('group').map((item) => item.querySelector('summary')?.textContent ?? '');
    expect(summaries).toEqual(expect.arrayContaining([
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
    await user.click(within(pipeline).getByText('Provider 请求 1'));
    expect(screen.getByText(/RAW_PROVIDER_PAYLOAD/)).toBeVisible();
    expect(screen.getByText(/API 线上的 JSON 信封/)).toBeVisible();
    expect(screen.getByRole('radiogroup', { name: '上下文展示形式' })).toHaveTextContent('模型语义');
    await user.click(screen.getByRole('radio', { name: '原始 JSON' }));
    expect(within(pipeline).getByText('传输 JSON')).toBeVisible();
    expect(screen.getByText(/"messages":/)).toBeVisible();
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId: 'session-1' },
      query: { turnId: 'turn-1' },
    }));
  });
});
