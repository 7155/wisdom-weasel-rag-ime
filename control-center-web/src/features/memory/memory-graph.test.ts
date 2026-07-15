import { describe, expect, it } from 'vitest';
import {
  buildGroupBookGraph,
  buildGroupTagGraph,
  buildTagGraph,
  mergeMemoryGraphTags,
  parseMemoryGraph,
  safeGraphColor,
  tagEdgeStrokeWidth,
  tagNodeRadius,
} from './memory-graph';

describe('memory graph parsing', () => {
  it('accepts the bounded memory graph contract and rejects legacy page payloads', () => {
    const tags = parseMemoryGraph(tagGraphPayload());
    const groups = parseMemoryGraph(groupGraphPayload());

    expect(tags.truncated).toBe(true);
    expect(tags).toMatchObject({ nodeCount: 2, edgeCount: 1, graphRevision: `sha256:${'a'.repeat(64)}` });
    expect(tags.tags).toEqual([
      expect.objectContaining({ id: 'tag:agent', entityId: 'agent', label: 'Agent Runtime', itemCount: 11, source: 'sqlite' }),
      expect.objectContaining({ id: 'tag:memory', entityId: 'memory', label: 'Memory', itemCount: 5 }),
    ]);
    expect(tags.tags[0]?.connections).toEqual([
      expect.objectContaining({ targetId: 'tag:memory', weight: 0.9, evidenceCount: 6, source: 'dsv4' }),
    ]);
    expect(groups.groups).toEqual([
      expect.objectContaining({
        id: 'group:agent',
        entityId: 'agent',
        label: 'Agent 工程',
        tagIds: ['tag:agent', 'tag:memory'],
        tags: ['Agent Runtime', 'Memory'],
        bookIds: ['book:input'],
        books: ['输入法知识册'],
        eventCount: 12,
        source: 'sqlite',
        tagMemberships: [
          expect.objectContaining({ tagId: 'tag:agent', source: 'dsv4' }),
          expect.objectContaining({ tagId: 'tag:memory', source: 'dsv4' }),
        ],
        bookMemberships: [
          expect.objectContaining({ bookId: 'book:input', source: 'dsv4' }),
        ],
      }),
    ]);
    expect(groups.books).toEqual([
      expect.objectContaining({ id: 'book:input', entityId: 'input', label: '输入法知识册', memberCount: 6 }),
    ]);
    expect(parseMemoryGraph({ items: [] })).toEqual({
      books: [],
      groups: [],
      tags: [],
      nodeCount: 0,
      edgeCount: 0,
      graphRevision: '',
      truncated: false,
    });
  });

  it('maps untrusted color values only through the safe token table', () => {
    expect(safeGraphColor('green')).toBe('var(--color-success)');
    expect(safeGraphColor('url(javascript:alert(1))')).toBe('var(--color-info)');
    expect(safeGraphColor({ token: 'red' })).toBe('var(--color-info)');
  });
});

describe('memory graph layout', () => {
  it('derives node size and relation width from bounded counts and evidence', () => {
    expect(tagNodeRadius(100)).toBeGreaterThan(tagNodeRadius(1));
    expect(tagNodeRadius(Number.POSITIVE_INFINITY)).toBe(tagNodeRadius(0));
    expect(tagEdgeStrokeWidth(0.9, 8)).toBeGreaterThan(tagEdgeStrokeWidth(0.2, 0));
    expect(tagEdgeStrokeWidth(999, 999_999)).toBeLessThanOrEqual(5);
  });

  it('produces deterministic tag nodes and deduplicated visible edges', () => {
    const tags = parseMemoryGraph(tagGraphPayload()).tags;
    const forward = buildTagGraph(tags);
    const reverse = buildTagGraph([...tags].reverse());

    expect(forward).toEqual(reverse);
    expect(forward.nodes.map((node) => node.id)).toEqual(['tag:agent', 'tag:memory']);
    expect(forward.edges).toHaveLength(1);
    expect(forward.edges[0]).toEqual(expect.objectContaining({
      source: 'tag:agent',
      target: 'tag:memory',
      weight: 0.9,
      evidenceCount: 6,
    }));
  });

  it('builds a collision-free Group and Tag graph at the maximum visible node count', () => {
    const parsedGroups = parseMemoryGraph(groupGraphPayload(12));
    const parsedTags = parseMemoryGraph(tagGraphPayload(12));
    const tags = mergeMemoryGraphTags(parsedTags.tags, parsedGroups.tags);
    const graph = buildGroupTagGraph(parsedGroups.groups, tags);

    expect(graph.tags).toHaveLength(12);
    expect(graph.height).toBeGreaterThan(620);
    for (let index = 1; index < graph.tags.length; index += 1) {
      const previous = graph.tags[index - 1]!;
      const current = graph.tags[index]!;
      expect(current.y - previous.y).toBeGreaterThanOrEqual(previous.radius + current.radius + 12);
    }
  });

  it('builds a clickable Group and Book graph without exposing unsupported member kinds', () => {
    const parsed = parseMemoryGraph(groupGraphPayload());
    const graph = buildGroupBookGraph(parsed.groups, parsed.books);

    expect(graph.groups).toHaveLength(1);
    expect(graph.books).toEqual([
      expect.objectContaining({ id: 'book:input', label: '输入法知识册', memberCount: 6 }),
    ]);
    expect(graph.edges).toEqual([
      expect.objectContaining({ groupId: 'group:agent', bookId: 'book:input', relation: 'contains' }),
    ]);
  });
});

function graphNode(
  id: string,
  kind: 'tag' | 'group' | 'book',
  label: string,
  memberCount: number,
): Record<string, unknown> {
  return {
    id,
    entityId: id.split(':').at(-1),
    kind,
    label,
    description: `${label} description`,
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

function tagGraphPayload(count = 2): Record<string, unknown> {
  const nodes = Array.from({ length: count }, (_, index) => graphNode(
    index === 0 ? 'tag:agent' : index === 1 ? 'tag:memory' : `tag:${index}`,
    'tag',
    index === 0 ? 'Agent Runtime' : index === 1 ? 'Memory' : `Tag ${index}`,
    index === 0 ? 11 : index === 1 ? 5 : 5 + index,
  ));
  return {
    schemaVersion: 'rag-ime.memory-graph.v1',
    graphRevision: `sha256:${'a'.repeat(64)}`,
    plane: 'tags',
    nodes,
    edges: count > 1 ? [{
      id: 'edge:agent-memory',
      kind: 'tagRelation',
      sourceId: 'tag:agent',
      targetId: 'tag:memory',
      relation: 'related_to',
      weight: 0.9,
      evidenceCount: 6,
      source: 'dsv4',
    }] : [],
    truncated: { nodes: true, edges: false },
  };
}

function groupGraphPayload(tagCount = 2): Record<string, unknown> {
  const tags = Array.from({ length: tagCount }, (_, index) => graphNode(
    index === 0 ? 'tag:agent' : index === 1 ? 'tag:memory' : `tag:${index}`,
    'tag',
    index === 0 ? 'Agent Runtime' : index === 1 ? 'Memory' : `Tag ${index}`,
    5 + index,
  ));
  return {
    schemaVersion: 'rag-ime.memory-graph.v1',
    graphRevision: `sha256:${'b'.repeat(64)}`,
    plane: 'groups',
    nodes: [graphNode('group:agent', 'group', 'Agent 工程', 12), graphNode('book:input', 'book', '输入法知识册', 6), ...tags],
    edges: [...tags.map((tag) => ({
      id: `membership:${String(tag.id)}`,
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: tag.id,
      relation: 'contains',
      weight: 1,
      evidenceCount: 1,
      source: 'dsv4',
    })), {
      id: 'membership:book:input',
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: 'book:input',
      relation: 'contains',
      weight: 0.8,
      evidenceCount: 1,
      source: 'dsv4',
    }],
    truncated: { nodes: false, edges: false },
  };
}
