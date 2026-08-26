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
  it('keeps layer content collapsed by default and opens each injected layer to its real text', async () => {
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

    expect(screen.getByText('上下文检查')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /查看上下文检查/ }));

    const layers = await screen.findByRole('list', { name: '上下文分层指标' });
    for (const label of [
      'System',
      '项目规则',
      '伙伴画像',
      '工作状态',
      'Goal',
      'Lifecycle Hook',
      'Session Memory',
      'Timeline',
      '压缩摘要',
      'Skills',
      'Tools',
      '用户消息',
      'Agent 消息',
      '工具调用',
      '其他消息',
      'Tool Results',
    ]) {
      expect(within(layers).getByText(label)).toBeVisible();
    }
    expect(within(layers).getAllByText('已接收')).toHaveLength(15);
    expect(within(layers).getAllByText(/Token 未单独统计/u).length).toBeGreaterThan(0);
    expect(within(layers).getByText('其他消息').closest('li')).toHaveTextContent('本轮未注入');
    expect(screen.getByText('68%')).toBeVisible();
    expect(screen.getByText('12.0K → 4.2K')).toBeVisible();
    expect(screen.queryByText('ROLE_BOOK_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('PROJECT_RULES_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('WORKFLOW_CONTROL_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('GOAL_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('LIFECYCLE_HOOK_PRIVATE_TEXT')).not.toBeInTheDocument();
    expect(screen.queryByText('PRIVATE_TOOL_RESULT')).not.toBeInTheDocument();
    expect(transport.requests).toContainEqual(expect.objectContaining({
      pathId: 'agent.session.debugContext.get',
      params: { sessionId: 'session-xray' },
    }));

    // PF-CM-010：分层摘要行不是死行——本人点开某一层时，能看到该层实际
    // 注入的原文；再次点击恢复默认折叠，原文离开 DOM。
    const roleToggle = within(layers).getByRole('button', { name: /伙伴画像/ });
    expect(roleToggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(roleToggle);
    const roleContent = await screen.findByRole('region', { name: '伙伴画像 实际注入内容，可滚动原文' });
    expect(roleContent).toHaveTextContent('ROLE_BOOK_PRIVATE_TEXT');
    expect(roleContent).toHaveAttribute('tabindex', '0');
    await user.click(roleToggle);
    expect(screen.queryByText('ROLE_BOOK_PRIVATE_TEXT')).not.toBeInTheDocument();
  });

  it('shows an explicit unavailable state instead of inventing metrics', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        available: false,
        transient: true,
        context: null,
        telemetry: null,
        reason: 'session_not_resident',
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

    await user.click(screen.getByRole('button', { name: /查看上下文检查/ }));
    expect(await screen.findByText('该 Session 当前未驻留；上下文检查不会为诊断强制唤醒它')).toBeVisible();
    expect(screen.queryByRole('list', { name: '上下文分层指标' })).not.toBeInTheDocument();
  });

  it('ends a slow Runtime diagnostic as unavailable instead of implying the Session is blocked', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.session.debugContext.get': {
        available: false,
        transient: true,
        context: null,
        telemetry: null,
        reason: 'runtime_unresponsive',
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <ContextXraySections sessionId="session-slow-xray" open />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: /查看上下文检查/ }));
    expect(await screen.findByText('Runtime 未及时返回上下文快照；正常对话不会被诊断请求阻塞')).toBeVisible();
    expect(transport.requests).toHaveLength(1);
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
    expect(snapshot.layers.filter((layer) => layer.state === 'present').every(
      (layer) => layer.providerDelivery === 'pending',
    )).toBe(true);
  });

  it('accepts Pi message-end usage as a completed provider receipt', () => {
    const response = debugResponse();
    const context = response.context as Record<string, unknown>;
    const modelCalls = context.modelCalls as Array<Record<string, unknown>>;
    const exchanges = modelCalls[0]?.providerExchanges as Array<Record<string, unknown>>;
    delete exchanges[0]?.status;
    context.providerRequestReceipts = [{
      schemaVersion: 'rag-ime.provider-request-receipt.v1',
      index: 1,
      usage: { input: 100, output: 10, totalTokens: 110 },
    }];

    const snapshot = buildContextXraySnapshot(normalizeDebugContextResponse(response));

    expect(snapshot.providerStatus).toBeNull();
    expect(snapshot.layers.filter((layer) => layer.state === 'present').every(
      (layer) => layer.providerDelivery === 'delivered',
    )).toBe(true);
  });

  it('reports Pi-loaded project rules as their own layer instead of hiding them in System', () => {
    const snapshot = buildContextXraySnapshot(normalizeDebugContextResponse(debugResponse()));
    const system = snapshot.layers.find((layer) => layer.id === 'system');
    const projectContext = snapshot.layers.find((layer) => layer.id === 'project-context');

    expect(projectContext).toEqual(
      expect.objectContaining({
        label: '项目规则',
        state: 'present',
        characters: 'PROJECT_RULES_PRIVATE_TEXT'.length,
        providerDelivery: 'delivered',
      }),
    );
    expect(system?.characters).toBe('BASE_SYSTEM_PROMPT'.length);
  });

  it('separates reliably typed user, assistant, and tool-result messages without guessing unknown roles', () => {
    const snapshot = buildContextXraySnapshot(normalizeDebugContextResponse(debugResponse()));

    expect(snapshot.layers.find((layer) => layer.id === 'user-messages')?.content).toContain('CURRENT_USER_TEXT');
    expect(snapshot.layers.find((layer) => layer.id === 'user-messages')?.content).toContain('HISTORY_USER_TEXT');
    expect(snapshot.layers.find((layer) => layer.id === 'assistant-messages')?.content).toContain('HISTORY_ASSISTANT_TEXT');
    expect(snapshot.layers.find((layer) => layer.id === 'assistant-messages')?.content).not.toContain('read_file');
    expect(snapshot.layers.find((layer) => layer.id === 'tool-calls')?.content).toContain('read_file');
    expect(snapshot.layers.find((layer) => layer.id === 'tool-results')?.content).toContain('PRIVATE_TOOL_RESULT');
    expect(snapshot.layers.find((layer) => layer.id === 'compaction-summary')?.content).toContain('COMPACTED_HISTORY_TEXT');
    expect(snapshot.layers.find((layer) => layer.id === 'history')?.state).toBe('absent');
  });

  it('uses Pi final provider-neutral context when the bounded RPC projection omits wire payloads', () => {
    const response = debugResponse();
    const context = response.context as Record<string, unknown>;
    const modelCalls = context.modelCalls as Array<Record<string, unknown>>;
    const call = modelCalls[0]!;
    call.providerContext = {
      systemPrompt: context.systemPrompt,
      tools: context.toolSchemas,
    };
    const exchanges = call.providerExchanges as Array<Record<string, unknown>>;
    delete exchanges[0]?.payload;
    context.providerRequestReceipts = [{ index: 1, usage: { input: 18_000 } }];

    const snapshot = buildContextXraySnapshot(normalizeDebugContextResponse(response));

    expect(snapshot.providerCaptured).toBe(true);
    expect(snapshot.layers.find((layer) => layer.id === 'system')?.providerDelivery).toBe('delivered');
    expect(snapshot.layers.find((layer) => layer.id === 'user-messages')?.providerDelivery).toBe('delivered');
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
    'PROJECT_RULES_PRIVATE_TEXT',
    '<agent-profile>',
    'ROLE_BOOK_PRIVATE_TEXT',
    '</agent-profile>',
    '<workflow-state>',
    'WORKFLOW_CONTROL_PRIVATE_TEXT',
    '</workflow-state>',
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
    name: 'memory',
    description: 'Search memory',
    parameters: { type: 'object' },
  }];
  const messages = [
    { role: 'compactionSummary', summary: 'COMPACTED_HISTORY_TEXT', tokensBefore: 12_000 },
    { role: 'user', content: 'HISTORY_USER_TEXT' },
    { role: 'assistant', content: [
      { type: 'text', text: 'HISTORY_ASSISTANT_TEXT' },
      { type: 'toolCall', id: 'call-1', name: 'read_file', arguments: { path: 'src/app.ts' } },
    ] },
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
      systemPromptOptions: {
        contextFiles: [{
          path: '/tmp/project/AGENTS.md',
          content: 'PROJECT_RULES_PRIVATE_TEXT',
        }],
        skills,
      },
      activeTools: ['memory'],
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
