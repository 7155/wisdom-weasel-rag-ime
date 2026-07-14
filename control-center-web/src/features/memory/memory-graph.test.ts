import { describe, expect, it } from 'vitest';
import {
  buildGroupTagGraph,
  buildTagGraph,
  parseMemoryGroupPage,
  parseMemoryTagPage,
  safeGraphColor,
  tagEdgeStrokeWidth,
  tagNodeRadius,
} from './memory-graph';

describe('memory graph parsing', () => {
  it('accepts only the existing tag and group page shapes', () => {
    const tags = parseMemoryTagPage({
      items: [
        {
          id: '7',
          tag: 'Agent Runtime',
          description: '运行时边界',
          aliases: ['Agent', 42, 'Agent'],
          item_count: 9,
          edge_count: 2,
          color_token: 'teal',
          connections: [
            { id: '8', tag: 'Memory', type: 'related_to', weight: 0.8, evidenceCount: 4 },
            { id: 9, weight: '1.0' },
          ],
        },
        { id: 8, tag: null },
        'not-an-item',
      ],
      nextCursor: '7',
    });
    const groups = parseMemoryGroupPage({
      items: [
        { id: 'group:runtime', title: 'Agent 工程', note: '边界与恢复', tags: ['Agent Runtime', 8, 'Memory'], event_count: 12, color_token: 'green' },
        { id: 3, title: 'invalid' },
      ],
      nextCursor: '',
    });

    expect(tags.hasMore).toBe(true);
    expect(tags.items).toEqual([
      expect.objectContaining({ id: '7', label: 'Agent Runtime', aliases: ['Agent'], itemCount: 9, edgeCount: 2 }),
    ]);
    expect(tags.items[0]?.connections).toEqual([
      expect.objectContaining({ targetId: '8', weight: 0.8, evidenceCount: 4 }),
    ]);
    expect(groups).toEqual({
      hasMore: false,
      items: [expect.objectContaining({ id: 'group:runtime', label: 'Agent 工程', tags: ['Agent Runtime', 'Memory'], eventCount: 12 })],
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
    const page = parseMemoryTagPage({
      items: [
        { id: 'b', tag: 'Memory', item_count: 5, edge_count: 1, connections: [{ id: 'a', type: 'related_to', weight: 0.4, evidenceCount: 1 }] },
        { id: 'a', tag: 'Agent', item_count: 8, edge_count: 2, connections: [{ id: 'b', type: 'related_to', weight: 0.8, evidenceCount: 4 }] },
      ],
    });
    const forward = buildTagGraph(page.items);
    const reverse = buildTagGraph([...page.items].reverse());

    expect(forward).toEqual(reverse);
    expect(forward.nodes.map((node) => node.id)).toEqual(['a', 'b']);
    expect(forward.edges).toHaveLength(1);
    expect(forward.edges[0]).toEqual(expect.objectContaining({ source: 'a', target: 'b', weight: 0.8, evidenceCount: 4 }));
  });

  it('builds the Group and Tag bipartite graph from group tags without inventing counts', () => {
    const groups = parseMemoryGroupPage({
      items: [
        { id: 'g1', title: 'Agent 工程', tags: ['Agent', 'Missing'], event_count: 20 },
        { id: 'g2', title: '输入法', tags: ['Agent'], event_count: 4 },
      ],
    });
    const tags = parseMemoryTagPage({
      items: [{ id: 't1', tag: 'Agent', item_count: 11, edge_count: 1, color_token: 'teal' }],
    });
    const graph = buildGroupTagGraph(groups.items, tags.items);

    expect(graph.groups.map((group) => group.id)).toEqual(['g1', 'g2']);
    expect(graph.tags.map((tag) => [tag.label, tag.itemCount, tag.presentOnTagPage])).toEqual([
      ['Agent', 11, true],
      ['Missing', 0, false],
    ]);
    expect(graph.edges).toEqual([
      { groupId: 'g1', tagId: 'group-tag:missing' },
      { groupId: 'g1', tagId: 't1' },
      { groupId: 'g2', tagId: 't1' },
    ]);
    expect(graph.groups[0]!.width).toBeGreaterThan(graph.groups[1]!.width);
  });
});
