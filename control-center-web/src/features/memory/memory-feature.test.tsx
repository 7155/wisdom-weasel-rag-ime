import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { MemoryFeature } from './index';

afterEach(cleanup);

describe('MemoryFeature relations', () => {
  it('loads bounded tag/group graphs and links keyboard node selection to accessible tables', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.graph.get': (request: ControlRequest) => memoryGraph(String(request.query?.plane ?? '')),
      },
    });
    renderMemory(transport);

    expect(await screen.findByRole('heading', { name: '记忆', level: 1 })).toBeInTheDocument();
    await user.click(await screen.findByRole('tab', { name: '关系图' }));
    expect(await screen.findByText('当前页局部图')).toBeInTheDocument();
    expect(screen.getByText('已截断')).toBeInTheDocument();

    await waitFor(() => {
      const graphRequests = transport.requests.filter((call) =>
        call.request.pathId === 'memory.graph.get');
      expect(graphRequests).toHaveLength(2);
      for (const call of graphRequests) {
        expect(call.request.query).toMatchObject({ depth: 1, minWeight: 0 });
      }
    });

    const memoryNode = screen.getByRole('button', { name: /Memory，5 条记忆/ });
    fireEvent.keyDown(memoryNode, { key: 'Enter' });
    expect(screen.getByRole('heading', { name: 'Memory', level: 3 })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Memory 在当前页可见的标签关系' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Agent Runtime' })).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Group / Tag' }));
    const groupNode = screen.getByRole('button', { name: /Group Agent 工程，12 条知识/ });
    await user.click(groupNode);
    expect(screen.getByRole('table', { name: 'Agent 工程 在当前页可见的 Group 与 Tag 关系' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Agent Runtime' }).length).toBeGreaterThan(0);
  });
});

function renderMemory(transport: MockControlTransport) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <MemoryFeature />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function memoryGraph(plane: string): Record<string, unknown> {
  const tagAgent = graphNode('tag:agent', 'tag', 'Agent Runtime', 11, 'Agent 生命周期与工具边界');
  const tagMemory = graphNode('tag:memory', 'tag', 'Memory', 5, '记忆组织与检索');
  if (plane === 'tags') {
    return graphEnvelope('tags', [tagAgent, tagMemory], [{
      id: 'edge:agent-memory',
      kind: 'tagRelation',
      sourceId: 'tag:agent',
      targetId: 'tag:memory',
      sourceKind: 'tag',
      targetKind: 'tag',
      relation: 'related_to',
      weight: 0.9,
      directionBias: 0,
      evidenceCount: 6,
      source: 'sqlite',
      updatedAtMs: 1,
    }], true);
  }
  return graphEnvelope(
    'groups',
    [graphNode('group:agent', 'group', 'Agent 工程', 12, 'Agent 陪伴与恢复'), tagAgent, tagMemory],
    [tagAgent, tagMemory].map((tag) => ({
      id: `membership:${String(tag.id)}`,
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: tag.id,
      sourceKind: 'group',
      targetKind: 'tag',
      relation: 'contains',
      weight: 1,
      directionBias: 0,
      evidenceCount: 1,
      source: 'sqlite',
      updatedAtMs: 1,
    })),
    false,
  );
}

function graphEnvelope(
  plane: 'tags' | 'groups',
  nodes: Record<string, unknown>[],
  edges: Record<string, unknown>[],
  truncated: boolean,
): Record<string, unknown> {
  return {
      schemaVersion: 'rag-ime.memory-graph.v1',
    ok: true,
    settingsRevision: 'settings:test',
    runtimeRevision: 1,
    graphRevision: `sha256:${'a'.repeat(64)}`,
    plane,
    project: 'wisdom-weasel-rag-ime',
    filters: { status: 'active', query: '', focusId: '', minWeight: 0 },
    nodes,
    edges,
    truncated: { nodes: truncated, edges: false },
    limits: { nodeLimit: 80, edgeLimit: 160, depth: 1 },
  };
}

function graphNode(
  id: string,
  kind: 'tag' | 'group',
  label: string,
  memberCount: number,
  description: string,
): Record<string, unknown> {
  return {
    id,
    entityId: id.split(':').at(-1),
    kind,
    label,
    description,
    color: kind === 'group' ? 'blue' : 'teal',
    status: 'active',
    source: 'sqlite',
    project: 'wisdom-weasel-rag-ime',
    qualityScore: 1,
    memberCount,
    edgeCount: 1,
    updatedAtMs: 1,
  };
}

function memoryPage(kind: string): Record<string, unknown> {
  if (kind === 'tags') {
    return {
      ok: true,
      items: [
        {
          id: 'tag-agent',
          tag: 'Agent Runtime',
          description: 'Agent 生命周期与工具边界',
          item_count: 11,
          edge_count: 1,
          color_token: 'teal',
          connections: [{ id: 'tag-memory', tag: 'Memory', type: 'related_to', weight: 0.9, evidenceCount: 6 }],
        },
        {
          id: 'tag-memory',
          tag: 'Memory',
          description: '记忆组织与检索',
          item_count: 5,
          edge_count: 1,
          color_token: 'green',
          connections: [{ id: 'tag-agent', tag: 'Agent Runtime', type: 'related_to', weight: 0.9, evidenceCount: 6 }],
        },
      ],
      nextCursor: 'tag-next',
      limit: 50,
    };
  }
  if (kind === 'groups') {
    return {
      ok: true,
      items: [
        {
          id: 'group:agent',
          title: 'Agent 工程',
          note: 'Agent 陪伴与恢复',
          tags: ['Agent Runtime', 'Memory'],
          event_count: 12,
          color_token: 'blue',
        },
      ],
      nextCursor: '',
      limit: 50,
    };
  }
  return {
    ok: true,
    items: [{ id: 'book-1', title: '控制中心迁移', summary: 'React 页面与受控 API', status: 'active' }],
    nextCursor: '',
    limit: 50,
  };
}
