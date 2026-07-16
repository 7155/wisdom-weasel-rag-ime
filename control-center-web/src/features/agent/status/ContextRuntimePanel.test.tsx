import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
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

    expect(transport.requests).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: /查看上下文状态/ }));
    expect(await screen.findByText('研究任务已完成')).toBeVisible();
    const trigger = await screen.findByRole('button', { name: /用户输入/ });
    expect(transport.requests.some((request) => request.pathId === 'agent.session.contextTrace.get')).toBe(false);

    await user.click(trigger);
    const dialog = await screen.findByRole('dialog', { name: '上下文管线' });
    expect(await within(dialog).findByText('动态工具目录')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: /动态工具目录/ }));
    expect(within(dialog).getByText('Token 估算')).toBeVisible();
    expect(transport.requests.some((request) => request.pathId === 'agent.session.contextTrace.get')).toBe(true);

    await user.click(within(dialog).getByRole('button', { name: '关闭' }));
    await user.click(screen.getByRole('button', { name: '确认 研究任务已完成' }));
    await waitFor(() => expect(
      transport.requests.some((request) => request.pathId === 'agent.session.contextItems.ack'),
    ).toBe(true));
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
