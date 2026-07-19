import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { ContextXraySections, buildContextXraySnapshot } from './ContextXrayPanel';
import { normalizeDebugContextResponse } from '@/features/context-debug/model';

afterEach(cleanup);

describe('ContextXraySections', () => {
  it('reports real layer metrics and provider delivery without exposing raw content', async () => {
    const response = debugResponse();
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': response,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <ContextXraySections sessionId="session-xray" open />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: /查看上下文透视/ }));

    const layers = await screen.findByRole('list', { name: '上下文分层指标' });
    for (const label of [
      'System',
      'Role Book',
      'Workflow Control',
      'Goal',
      'Lifecycle Hook',
      'Session Memory',
      'Timeline',
      'Skills',
      'Tools',
      'History',
      'Tool Results',
    ]) {
      expect(within(layers).getByText(label)).toBeVisible();
    }
    expect(within(layers).getAllByText('已接收')).toHaveLength(11);
    expect(screen.getByText('68%')).toBeVisible();
    expect(screen.getByText('12.0K → 4.2K')).toBeVisible();
    expect(screen.queryByText('ROLE_BOOK_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('WORKFLOW_CONTROL_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('GOAL_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('LIFECYCLE_HOOK_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_TOOL_RESULT')).not.toBeInTheDocument();
    expect(transport.requests).toContainEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId: 'session-xray' },
    }));
  });

  it('shows an explicit unavailable state instead of inventing metrics', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        available: false,
        transient: true,
        context: null,
        telemetry: null,
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <ContextXraySections sessionId="session-empty" open />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: /查看上下文透视/ }));
    expect(await screen.findByText('这轮尚未形成可核对的上下文快照')).toBeVisible();
    expect(screen.queryByRole('list', { name: '上下文分层指标' })).not.toBeInTheDocument();
  });
});

describe('buildContextXraySnapshot', () => {
  it('marks provider delivery pending until a response status exists', () => {
    const response = debugResponse();
    const context = response.context as Record<string, unknown>;
    const modelCalls = context.modelCalls as Array<Record<string, unknown>>;
    const exchanges = modelCalls[0]?.providerExchanges as Array<Record<string, unknown>>;
    delete exchanges[0]?.status;

    const snapshot = buildContextXraySnapshot(normalizeDebugContextResponse(response));

    expect(snapshot.providerCaptured).toBe(true);
    expect(snapshot.providerStatus).toBeNull();
    expect(snapshot.layers.every((layer) => layer.providerDelivery === 'pending')).toBe(true);
  });
});

function debugResponse(): Record<string, unknown> {
  const sessionMemory = [
    '## 当前任务',
    '完成 Context X-ray',
    '## Session 记忆',
    '### 近期时间线',
    '今天完成上下文透视',
    '### 主题书',
    '记忆系统采用 Atom-first',
  ].join('\n');
  const systemPrompt = [
    'BASE_SYSTEM_PROMPT',
    '<agent-role-book>',
    'ROLE_BOOK_PRIVATE_TEXT',
    '</agent-role-book>',
    '<rag-ime-context priority="developer" type="workflow_control">',
    'WORKFLOW_CONTROL_PRIVATE_TEXT',
    '</rag-ime-context>',
    '<rag-ime-context type="goal" lifecycle="session">',
    'GOAL_PRIVATE_TEXT',
    '</rag-ime-context>',
    '<rag-ime-context source="runtime" type="lifecycle_hook">',
    'LIFECYCLE_HOOK_PRIVATE_TEXT',
    '</rag-ime-context>',
    '<rag-ime-context type="session_memory" current_time="2026-07-19T10:00:00+08:00">',
    sessionMemory,
    '</rag-ime-context>',
  ].join('\n');
  const skills = [{
    name: 'context-inspector',
    description: 'Inspect provider context',
    filePath: '/skills/context-inspector/SKILL.md',
  }];
  const tools = [{
    name: 'ime_memory',
    description: 'Search memory',
    parameters: { type: 'object' },
  }];
  const messages = [
    { role: 'user', content: 'HISTORY_USER_TEXT' },
    { role: 'assistant', content: 'HISTORY_ASSISTANT_TEXT' },
    { role: 'toolResult', content: 'PRIVATE_TOOL_RESULT' },
    { role: 'user', content: 'CURRENT_USER_TEXT' },
  ];
  return {
    schemaVersion: 'rag-ime.pi-debug-context-response.v1',
    available: true,
    transient: false,
    sessionId: 'session-xray',
    turnId: 'turn-xray',
    context: {
      sessionId: 'session-xray',
      turnId: 'turn-xray',
      capturedAtMs: 100,
      updatedAtMs: 200,
      prompt: 'CURRENT_USER_TEXT',
      systemPrompt,
      systemPromptOptions: { skills },
      activeTools: ['ime_memory'],
      toolSchemas: tools,
      modelCalls: [{
        index: 1,
        capturedAtMs: 100,
        updatedAtMs: 200,
        contextMessages: messages,
        contextDelta: {
          commonPrefixMessages: 0,
          removedMessageCount: 0,
          addedMessageCount: messages.length,
          addedMessages: messages,
        },
        providerExchanges: [{
          index: 1,
          capturedAtMs: 150,
          status: 200,
          payload: {
            model: 'gpt-test',
            instructions: systemPrompt,
            input: messages,
            tools,
            metadata: {
              skills,
            },
          },
        }],
      }],
      toolExecutions: [],
      toolBatches: [],
    },
    telemetry: {
      context: { tokens: 18_000, contextWindow: 128_000 },
      latestUsage: { input: 2_000, output: 500, cacheRead: 4_250, cacheWrite: 0 },
      latestCacheHitPercent: 68,
      compactionCount: 1,
      latestCompaction: {
        status: 'completed',
        tokensBefore: 12_000,
        estimatedTokensAfter: 4_200,
      },
      updatedAtMs: 220,
    },
  };
}
