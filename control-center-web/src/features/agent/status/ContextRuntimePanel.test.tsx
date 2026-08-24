import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { StubControlTransport } from '@/test/stub-control-transport';
import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import {
  ContextRuntimeSections,
  contextTraceLayers,
} from './ContextRuntimePanel';

afterEach(cleanup);

describe('Agent context runtime panel', () => {
  it('loads trace details only after the user opens the pipeline', async () => {
    const trace = traceFixture();
    const transport = new StubControlTransport('mock', {
      'agent.session.contextItems.list': {
        ok: true,
        items: [{
          schemaVersion: 'rag-ime.agent-context-item.v1',
          itemId: 'context-item:1',
          sessionId: 'session-1',
          sourceKind: 'long_task',
          sourceId: 'research-1',
          lane: 'result',
          lifecycle: 'until_ack',
          status: 'delivered',
          title: '研究任务已完成',
          summary: '等待当前角色确认',
          availableAtMs: 1,
          expiresAtMs: null,
          deliveredTurnId: 'turn-1',
          createdAtMs: 1,
          updatedAtMs: 2,
        }],
      },
      'agent.session.contextItems.ack': { ok: true },
      'agent.session.contextTraces.list': {
        ok: true,
        items: [{
          traceId: trace.traceId,
          sessionId: trace.sessionId,
          turnId: trace.turnId,
          sourceKind: trace.sourceKind,
          status: trace.status,
          finalFingerprint: trace.finalFingerprint,
          nodeCount: trace.nodes.length,
          createdAtMs: trace.createdAtMs,
          updatedAtMs: trace.updatedAtMs,
        }],
      },
      'agent.session.contextTrace.get': trace,
      'agent.session.debugContext.get': debugContextFixture(),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <ContextRuntimeSections open sessionId="session-1" />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    expect(transport.requests).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: /查看上下文状态/ }));
    expect(await screen.findByText('研究任务已完成')).toBeVisible();
    const trigger = await screen.findByRole('button', { name: /用户输入/ });
    expect(transport.requests.some((request) => request.pathId === 'agent.session.contextTrace.get')).toBe(false);
    expect(transport.requests.some((request) => request.pathId === 'agent.session.debugContext.get')).toBe(false);

    await user.click(trigger);
    const dialog = await screen.findByRole('dialog', { name: '上下文管线' });
    const resizer = within(dialog).getByRole('separator', { name: '调整上下文面板宽度' });
    const initialWidth = Number(resizer.getAttribute('aria-valuenow'));
    resizer.focus();
    await user.keyboard('{ArrowRight}');
    expect(Number(resizer.getAttribute('aria-valuenow'))).toBeLessThan(initialWidth);
    await user.keyboard('{ArrowLeft}');
    expect(Number(resizer.getAttribute('aria-valuenow'))).toBe(initialWidth);
    expect(await within(dialog).findByText('动态工具目录')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: /动态工具目录/ }));
    expect(within(dialog).getByText('Token 估算')).toBeVisible();
    expect(transport.requests.some((request) => request.pathId === 'agent.session.contextTrace.get')).toBe(true);

    // PF-CM-010：选中的装配节点不是死行——它直接展示该阶段的捕获原文。
    const toolEvidence = await within(dialog).findByRole('region', { name: '本次模型调用收到的工具 Schema，可滚动原文' });
    expect(toolEvidence).toHaveTextContent('PIPELINE_TOOL_SCHEMA_TEXT');
    expect(toolEvidence).toHaveAttribute('tabindex', '0');
    await user.click(within(dialog).getByRole('button', { name: /当前输入/ }));
    const promptEvidence = await within(dialog).findByRole('region', { name: '本轮用户输入原文，可滚动原文' });
    expect(promptEvidence).toHaveTextContent('PIPELINE_PROMPT_TEXT');

    await user.click(within(dialog).getByRole('button', { name: '关闭' }));
    await user.click(screen.getByRole('button', { name: '确认 研究任务已完成' }));
    await waitFor(() => expect(
      transport.requests.some((request) => request.pathId === 'agent.session.contextItems.ack'),
    ).toBe(true));
  });

  it('keeps independent context query failures scoped to their owner and retry control', async () => {
    let itemAttempts = 0;
    let traceAttempts = 0;
    const transport = new StubControlTransport('mock', {
      'agent.session.contextItems.list': () => {
        itemAttempts += 1;
        if (itemAttempts === 1) throw new Error('items offline');
        return { ok: true, items: [] };
      },
      'agent.session.contextTraces.list': () => {
        traceAttempts += 1;
        if (traceAttempts === 1) throw new Error('traces offline');
        return { ok: true, items: [] };
      },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <ContextRuntimeSections open sessionId="session-1" />
        </QueryClientProvider>
      </ControlTransportProvider>,
    );

    await user.click(screen.getByRole('button', { name: /查看上下文状态/ }));
    const inbox = (await screen.findByText('上下文收件箱')).closest('section')!;
    const pipeline = screen.getByText('上下文管线').closest('section')!;

    expect(await within(inbox).findByRole('alert')).toHaveTextContent('上下文收件箱读取失败');
    expect(within(pipeline).getByRole('alert')).toHaveTextContent('上下文组装记录读取失败');
    expect(within(inbox).queryByText('没有等待处理的异步信息')).not.toBeInTheDocument();
    expect(within(pipeline).queryByText('发送消息后会记录组装阶段')).not.toBeInTheDocument();

    await user.click(within(inbox).getByRole('button', { name: '重新读取上下文收件箱' }));
    await user.click(within(pipeline).getByRole('button', { name: '重新读取上下文组装记录' }));

    await waitFor(() => expect(itemAttempts).toBe(2));
    await waitFor(() => expect(traceAttempts).toBe(2));
    expect(within(inbox).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(pipeline).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(inbox).getByText('没有等待处理的异步信息')).toBeVisible();
    expect(within(pipeline).getByText('发送消息后会记录组装阶段')).toBeVisible();
  });

  it('shows a bounded context inbox with an explicit path to every loaded active item', async () => {
    const user = userEvent.setup();
    const transport = new StubControlTransport('mock', {
      'agent.session.contextItems.list': {
        ok: true,
        items: Array.from({ length: 5 }, (_, index) => ({
          schemaVersion: 'rag-ime.agent-context-item.v1', itemId: `context-item:${index + 1}`, sessionId: 'session-1', sourceKind: 'long_task', sourceId: `task-${index + 1}`,
          lane: 'result', lifecycle: 'until_ack', status: 'delivered', title: `待处理 ${index + 1}`, summary: '等待确认', availableAtMs: 1, expiresAtMs: null, deliveredTurnId: 'turn-1', createdAtMs: 1, updatedAtMs: 2,
        })),
      },
      'agent.session.contextTraces.list': { ok: true, items: [] },
      'agent.session.contextItems.ack': { ok: true },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<ControlTransportProvider transport={transport}><QueryClientProvider client={client}><ContextRuntimeSections open sessionId="session-1" /></QueryClientProvider></ControlTransportProvider>);

    await user.click(screen.getByRole('button', { name: /查看上下文状态/ }));
    const inbox = (await screen.findByText('上下文收件箱')).closest('section')!;
    expect(within(inbox).queryByText('待处理 5')).not.toBeInTheDocument();
    await user.click(within(inbox).getByRole('button', { name: '显示更多（4/5）' }));
    expect(within(inbox).getByText('待处理 5')).toBeVisible();
  });

  it('places converging trace nodes into topological layers', () => {
    const layers = contextTraceLayers(traceFixture());
    expect(layers.map((layer) => layer.map((node) => node.stage))).toEqual([
      ['input'],
      ['session'],
      ['tools', 'context_inbox'],
      ['runtime_request'],
    ]);
  });
});

function traceFixture(): AgentContextTraceV1 {
  return {
    schemaVersion: 'rag-ime.agent-context-trace.v1',
    traceId: 'context-trace:1',
    sessionId: 'session-1',
    turnId: 'turn-1',
    sourceKind: 'user',
    status: 'accepted',
    finalFingerprint: 'sha256:0123456789abcdef',
    nodes: [
      node('node:1:input', 1, 'input', '当前输入'),
      node('node:2:session', 2, 'session', 'Session 与角色'),
      node('node:3:tools', 3, 'tools', '动态工具目录', { toolCount: 12 }),
      node('node:4:context', 4, 'context_inbox', '异步上下文收件箱', { itemCount: 1 }),
      node('node:5:request', 5, 'runtime_request', 'Pi Runtime 请求'),
    ],
    edges: [
      { source: 'node:1:input', target: 'node:2:session' },
      { source: 'node:2:session', target: 'node:3:tools' },
      { source: 'node:2:session', target: 'node:4:context' },
      { source: 'node:1:input', target: 'node:5:request' },
      { source: 'node:3:tools', target: 'node:5:request' },
      { source: 'node:4:context', target: 'node:5:request' },
    ],
    createdAtMs: 1_720_000_000_000,
    updatedAtMs: 1_720_000_000_100,
  };
}

function debugContextFixture(): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.pi-debug-context-response.v1',
    available: true,
    transient: false,
    sessionId: 'session-1',
    turnId: 'turn-1',
    context: {
      sessionId: 'session-1',
      turnId: 'turn-1',
      capturedAtMs: 1_720_000_000_000,
      updatedAtMs: 1_720_000_000_100,
      prompt: 'PIPELINE_PROMPT_TEXT',
      systemPrompt: 'PIPELINE_SYSTEM_PROMPT_TEXT',
      model: { provider: 'test', modelId: 'test-model' },
      toolSchemas: [{ name: 'test-tool', description: 'PIPELINE_TOOL_SCHEMA_TEXT' }],
      activeTools: ['test-tool'],
      modelCalls: [{
        index: 1,
        providerContext: {
          systemPrompt: 'PIPELINE_SYSTEM_PROMPT_TEXT',
          tools: [{ name: 'test-tool', description: 'PIPELINE_TOOL_SCHEMA_TEXT' }],
          messages: [{ role: 'user', content: 'PIPELINE_PROMPT_TEXT' }],
        },
        contextMessages: [{ role: 'user', content: 'PIPELINE_PROMPT_TEXT' }],
      }],
    },
    storage: {
      persistent: true,
      directory: '/tmp/debug-context',
      usedBytes: 1024,
      maxBytes: 64 * 1024 * 1024,
    },
  };
}

function node(
  nodeId: string,
  ordinal: number,
  stage: string,
  label: string,
  metadata: Record<string, unknown> = {},
): AgentContextTraceV1['nodes'][number] {
  return {
    nodeId,
    ordinal,
    stage,
    label,
    sourceKind: 'gateway',
    disposition: 'included',
    summary: `${label} 已完成`,
    charCount: 12,
    tokenEstimate: 3,
    durationMs: 1,
    fingerprint: 'sha256:0123456789abcdef',
    reason: '',
    metadata,
    createdAtMs: 1_720_000_000_000 + ordinal,
  };
}
