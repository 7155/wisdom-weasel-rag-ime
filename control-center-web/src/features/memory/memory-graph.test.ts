import { describe, expect, it } from 'vitest';
import {
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
    expect(tags.tags).toEqual([
      expect.objectContaining({ id: 'tag:agent', entityId: 'agent', label: 'Agent Runtime', itemCount: 11 }),
      expect.objectContaining({ id: 'tag:memory', entityId: 'memory', label: 'Memory', itemCount: 5 }),
    ]);
    expect(tags.tags[0]?.connections).toEqual([
      expect.objectContaining({ targetId: 'tag:memory', weight: 0.9, evidenceCount: 6 }),
    ]);
    expect(groups.groups).toEqual([
      expect.objectContaining({
        id: 'group:agent',
        entityId: 'agent',
        label: 'Agent 工程',
        tagIds: ['tag:agent', 'tag:memory'],
        tags: ['Agent Runtime', 'Memory'],
        eventCount: 12,
      }),
    ]);
    expect(parseMemoryGraph({ items: [] })).toEqual({ groups: [], tags: [], truncated: false });
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
});

function graphNode(
  id: string,
  kind: 'tag' | 'group',
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
    plane: 'groups',
    nodes: [graphNode('group:agent', 'group', 'Agent 工程', 12), ...tags],
    edges: tags.map((tag) => ({
      id: `membership:${String(tag.id)}`,
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: tag.id,
      relation: 'contains',
      weight: 1,
      evidenceCount: 1,
    })),
    truncated: { nodes: false, edges: false },
  };
}
