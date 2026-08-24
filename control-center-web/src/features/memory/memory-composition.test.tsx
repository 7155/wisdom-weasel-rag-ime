import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import memoryStylesheet from './memory.css?raw';
import { publicMemorySourceLabel } from './public-copy';
import { MemoryFeature } from './index';

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

describe('MemoryFeature composition', () => {
  it('keeps the governed pipeline spine visible across catalog and relations views', async () => {
    renderMemory(catalogTransport());
    const pipeline = await screen.findByRole('list', { name: '记忆内容分类' });
    expect(within(pipeline).getByRole('button', { name: /来源/ })).toBeInTheDocument();
    expect(within(pipeline).getByRole('button', { name: /主题/ })).toBeInTheDocument();
    cleanup();

    renderMemory(relationsTransport(), '/memory?view=relations');
    expect(await screen.findByRole('heading', { name: '记忆关系' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: '记忆内容分类' })).toBeInTheDocument();
  });

  it('routes between memory layers from the pipeline spine', async () => {
    const user = userEvent.setup();
    const transport = catalogTransport();
    renderMemory(transport);

    const pipeline = await screen.findByRole('list', { name: '记忆内容分类' });
    await user.click(within(pipeline).getByRole('button', { name: /来源/ }));

    expect(await screen.findByRole('heading', { name: '记忆来源 目录' })).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'memory.pages' && call.request.params?.kind === 'evidence'
    ))).toBe(true));
  });

  it('describes the relations view with the recorded tag count instead of an atom claim', async () => {
    renderMemory(relationsTransport({ memoryTagCount: 6, memoryAtomCount: 40 }), '/memory?view=relations');

    expect(await screen.findByText('6 个关系标签')).toBeInTheDocument();
    expect(screen.queryByText(/参与关联/)).not.toBeInTheDocument();
  });

  it('keeps the preferences status a scope statement instead of a persistence claim', async () => {
    renderMemory(new MockControlTransport({
      capabilities: { features: {} },
      routes: {
        'memory.summary': { ok: true },
        'configuration.settings': {
          ok: true,
          settings: {
            memory: {
              timeDecay: { temporaryHalfLifeDays: 14, stablePreferenceHalfLifeDays: 365 },
              recall: { detailLevel: 'compact' },
              automaticOrganization: { includeAgentDialogue: true },
            },
          },
          runtimeRevision: 3,
        },
      },
    }), '/memory?view=preferences');

    expect(await screen.findByRole('heading', { name: '记忆偏好' })).toBeInTheDocument();
    expect(screen.getByText('影响整理与联想')).toBeInTheDocument();
    expect(screen.queryByText('本机设置持久化')).not.toBeInTheDocument();
  });

  it('keeps relations usable and honest when the shared memory summary fails', async () => {
    renderMemory(relationsTransport(undefined, () => {
      throw new Error('memory summary unavailable');
    }), '/memory?view=relations');

    expect(await screen.findByRole('heading', { name: '记忆关系' })).toBeInTheDocument();
    expect(await screen.findByText('记忆状态暂不可用')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /输入词汇，5 条记忆/ })).toBeInTheDocument();
  });

  it('labels an input-method source with the shared catalog vocabulary in relations', async () => {
    renderMemory(relationsTransport(), '/memory?view=relations');

    const node = await screen.findByRole('button', { name: /输入词汇，5 条记忆/ });
    expect(node).toHaveAccessibleName(expect.stringContaining('来源 输入记录'));
    expect(within(node).queryByText('其他来源')).not.toBeInTheDocument();
    expect(publicMemorySourceLabel('rime')).toBe('输入记录');
  });

  it('keeps the Memory identity colour tokens defined in the stylesheet owner', () => {
    for (const token of ['--memory-signal:', '--memory-signal-strong:', '--memory-signal-soft:', '--memory-gold:']) {
      expect(memoryStylesheet).toContain(token);
    }
    expect(memoryStylesheet).toContain('outline-color: var(--memory-signal)');
  });

  it('gives every memory layer its own signal identity in the stylesheet owner', () => {
    for (const scope of [
      ".memory-second-brain[data-view='catalog'][data-layer='evidence']",
      ".memory-second-brain[data-view='catalog'][data-layer='books']",
      ".memory-second-brain[data-view='roleBooks']",
      ".memory-second-brain[data-view='timeline']",
      ".memory-second-brain[data-view='relations']",
      ".memory-second-brain[data-view='organize']",
      ".memory-second-brain[data-view='preferences']",
    ]) {
      expect(memoryStylesheet).toContain(scope);
    }
    // The pipeline spine carries all four stage identities at once.
    for (const stage of ['evidence', 'organize', 'atoms', 'books']) {
      expect(memoryStylesheet).toContain(`.memory-pipeline__stage[data-stage='${stage}']`);
    }
  });

  it('runs the catalog search live instead of behind a filter button', async () => {
    const user = userEvent.setup();
    const transport = catalogTransport();
    renderMemory(transport);

    await screen.findByRole('list', { name: '记忆内容分类' });
    expect(screen.queryByRole('button', { name: '筛选' })).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: '搜索' }), '偏好');
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'memory.pages' && call.request.query?.query === '偏好'
    ))).toBe(true));
  });
});

function catalogTransport(): MockControlTransport {
  return new MockControlTransport({
    routes: {
      'memory.summary': { ok: true, memoryAtomCount: 2, memoryBookCount: 1 },
      'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
    },
  });
}

function relationsTransport(
  summaryExtras: Record<string, unknown> = {},
  summaryHandler?: () => unknown,
): MockControlTransport {
  return new MockControlTransport({
    routes: {
      'memory.summary': summaryHandler ?? { ok: true, memoryAtomCount: 2, memoryBookCount: 1, ...summaryExtras },
      'memory.graph.get': (request: ControlRequest) => memoryGraph(String(request.query?.plane ?? '')),
      'memory.entity.get': (request: ControlRequest) => memoryEntity(
        String(request.params?.kind ?? 'tag'),
        String(request.params?.entityId ?? ''),
      ),
    },
  });
}

function memoryGraph(plane: string): Record<string, unknown> {
  const inputTag = graphNode('tag:input-lexicon', 'tag', '输入词汇', 5, '输入法词汇整理', 'rime');
  const localTag = graphNode('tag:memory', 'tag', 'Memory', 3, '记忆组织', 'sqlite');
  const nodes = plane === 'tags'
    ? [inputTag, localTag]
    : [graphNode('group:input', 'group', '输入工程', 8, '输入法整理', 'sqlite'), inputTag, localTag];
  const edges = plane === 'tags'
    ? [{
      id: 'edge:input-memory',
      kind: 'tagRelation',
      sourceId: 'tag:input-lexicon',
      targetId: 'tag:memory',
      sourceKind: 'tag',
      targetKind: 'tag',
      relation: 'related_to',
      weight: 0.8,
      directionBias: 0,
      evidenceCount: 2,
      source: 'sqlite',
      updatedAtMs: 1,
    }]
    : [];
  return {
    schemaVersion: 'rag-ime.memory-graph.v1',
    ok: true,
    settingsRevision: 'settings:test',
    runtimeRevision: 1,
    graphRevision: `sha256:${'a'.repeat(64)}`,
    plane,
    project: 'personal-agent-workbench',
    filters: { status: 'active', query: '', focusId: '', minWeight: 0 },
    nodes,
    edges,
    truncated: { nodes: false, edges: false },
    limits: { nodeLimit: 80, edgeLimit: 160, depth: 1 },
  };
}

function graphNode(
  id: string,
  kind: 'tag' | 'group',
  label: string,
  memberCount: number,
  description: string,
  source: string,
): Record<string, unknown> {
  return {
    id,
    entityId: id.split(':').at(-1),
    kind,
    label,
    description,
    color: kind === 'group' ? 'blue' : 'teal',
    status: 'active',
    source,
    project: 'personal-agent-workbench',
    qualityScore: 1,
    memberCount,
    edgeCount: 1,
    updatedAtMs: 1,
  };
}

function memoryEntity(kind: string, entityId: string): Record<string, unknown> {
  const node = graphNode(
    `${kind}:${entityId}`,
    kind === 'group' ? 'group' : 'tag',
    entityId === 'input-lexicon' ? '输入词汇' : 'Memory',
    5,
    '实体详情',
    entityId === 'input-lexicon' ? 'rime' : 'sqlite',
  );
  return {
    schemaVersion: 'rag-ime.memory-entity.v1',
    ok: true,
    settingsRevision: 'settings:test',
    runtimeRevision: 1,
    kind,
    entityId,
    entityRevision: `sha256:${'b'.repeat(64)}`,
    project: 'personal-agent-workbench',
    entity: node,
    attributes: { type: 'concept', aliases: [], tags: [] },
    connections: { items: [], nextCursor: '', limit: 40, hasMore: false },
    members: { items: [], nextCursor: '', limit: 40, hasMore: false },
    limits: { connectionsLimit: 40, membersLimit: 40 },
  };
}

function renderMemory(transport: MockControlTransport, initialEntry = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}><MemoryFeature /></QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
}
