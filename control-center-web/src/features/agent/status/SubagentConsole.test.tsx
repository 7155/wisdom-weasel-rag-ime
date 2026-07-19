import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { StubControlTransport } from '@/test/stub-control-transport';
import { SubagentConsoleDialog } from './SubagentConsole';

afterEach(cleanup);

describe('SubagentConsoleDialog', () => {
  it('shows real console data and sends an idempotent steer command without optimistic state', async () => {
    const run = sampleRun();
    const transport = new StubControlTransport('mock', {
      'agent.subagent.console': consoleSnapshot(run),
      'agent.subagent.control': { ok: true, replayed: false },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={queryClient}>
          <SubagentConsoleDialog run={run} sessionId="session-parent" triggerLabel="打开控制台" />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: '打开控制台' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('执行 Agent控制台')).toBeVisible();
    expect(within(dialog).getByText('1.2K')).toBeVisible();
    await user.click(within(dialog).getByRole('tab', { name: /收件箱/ }));
    expect(within(dialog).getByText('保留兼容层？')).toBeVisible();
    await user.click(within(dialog).getByRole('tab', { name: '概览' }));

    const input = within(dialog).getByRole('textbox', { name: '给子 Agent 的干预消息' });
    await user.type(input, '请保留兼容层');
    await user.click(within(dialog).getByRole('button', { name: /发送干预/ }));

    const request = transport.requests.find((item) => item.pathId === 'agent.subagent.control');
    expect(request).toBeDefined();
    expect(request?.params).toEqual({ runId: run.id });
    expect(request?.body).toEqual(expect.objectContaining({
      sessionId: 'session-parent',
      action: 'steer',
      message: '请保留兼容层',
      clientActionId: expect.any(String),
    }));
    expect(within(dialog).getAllByText('执行中').length).toBeGreaterThan(0);
  });

  it('labels a missing transcript instead of manufacturing conversation text', async () => {
    const run = sampleRun();
    const snapshot = consoleSnapshot(run);
    snapshot.conversation = {
      availability: 'unavailable',
      source: 'legacy_result',
      items: [],
    };
    const transport = new StubControlTransport('mock', {
      'agent.subagent.console': snapshot,
      'agent.subagent.control': { ok: true },
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={queryClient}>
          <SubagentConsoleDialog run={run} sessionId="session-parent" triggerLabel="查看记录" />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: '查看记录' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('tab', { name: '对话' }));
    expect(within(dialog).getByText('当前运行没有可确认的公开对话快照')).toBeVisible();
  });
});

function consoleSnapshot(run: AgentSubagentRunV1): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.agent-subagent-console.v1',
    ok: true,
    run,
    capabilities: {
      steer: { available: true, reason: '' },
      retry: { available: false, reason: '等待当前任务结束' },
      resume: { available: false, reason: '任务仍在运行' },
      abort: { available: true, reason: '' },
      reply: { available: true, reason: '' },
    },
    conversation: {
      availability: 'available',
      source: 'active_runtime',
      items: [{
        id: 'message:1',
        role: 'assistant',
        createdAtMs: 100,
        blocks: [{ type: 'text', data: { text: '正在核对兼容边界。' } }],
      }],
    },
    activity: [{
      id: 'event:1',
      eventType: 'tool_started',
      createdAtMs: 101,
      payload: { toolName: 'ime_knowledge' },
    }],
    inbox: [{
      id: 'inbox:1',
      kind: 'need_decision',
      title: '保留兼容层？',
      message: '需要主持人确认。',
      status: 'pending',
      createdAtMs: 102,
    }],
    controls: [],
  };
}

function sampleRun(): AgentSubagentRunV1 {
  return {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id: 'subagent-run:test',
    batchId: 'subagent-batch:test',
    childSessionId: 'session-child',
    templateId: 'worker',
    templateVersion: '1',
    ordinal: 0,
    task: '实现子 Agent 控制台',
    state: 'running',
    budget: {
      maxTurns: 0,
      maxToolCalls: 0,
      maxTotalTokens: 10_000,
      maxDurationMs: 60_000,
      maxOutputChars: 10_000,
    },
    usage: { turnCount: 2, toolCount: 3, totalTokens: 1_200 },
    result: {},
    error: '',
    createdAtMs: 1,
    startedAtMs: 2,
    updatedAtMs: 3,
    completedAtMs: null,
  };
}
