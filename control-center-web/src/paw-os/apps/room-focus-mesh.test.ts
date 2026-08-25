import { describe, expect, it } from 'vitest';
import { buildRoomFocusMesh, roomFocusMeshEdgeKindLabel } from './room-focus-mesh';
import type {
  RoomFocusPartner,
  RoomFocusProjection,
  RoomFocusWorkItem,
} from './room-focus-projection';

function partner(participantId: string, celestialName: string, overrides: Partial<RoomFocusPartner> = {}): RoomFocusPartner {
  return {
    participantId,
    sessionId: `session-${participantId}`,
    displayName: `Agent ${celestialName}`,
    celestialName,
    state: 'running',
    ownedWorkItemIds: [],
    currentAction: '推进中',
    unread: false,
    ...overrides,
  };
}

function work(id: string, overrides: Partial<RoomFocusWorkItem> = {}): RoomFocusWorkItem {
  return {
    id,
    source: 'work-item',
    objective: `任务 ${id}`,
    acceptanceCriteria: [],
    state: 'running',
    reviewRequired: false,
    evidence: [],
    updatedAtMs: 1,
    ...overrides,
  };
}

function projection(overrides: Partial<RoomFocusProjection> = {}): RoomFocusProjection {
  return {
    goal: { title: '目标', description: '', rootId: 'turn-root', state: 'running' },
    workItems: [],
    partners: [],
    handoffs: [],
    flow: [],
    rootEvidence: [],
    counts: { active: 0, review: 0, blocked: 0, completed: 0 },
    ...overrides,
  };
}

describe('buildRoomFocusMesh', () => {
  const focus = projection({
    partners: [
      partner('p-earth', 'Earth'),
      partner('p-mars', 'Mars'),
      partner('p-venus', 'Venus', { state: 'review' }),
    ],
    workItems: [
      work('work-root', {
        ownerParticipantId: 'p-venus',
        accountableParticipantId: 'p-earth',
        state: 'review',
        review: { operability: 'passed', requirement: 'satisfied', reviewerParticipantId: 'p-venus' },
      }),
      work('work-child', {
        parentId: 'work-root',
        ownerParticipantId: 'p-mars',
        wave: { waveId: 'wave-a', parallelIndex: 1, parallelSize: 2 },
      }),
    ],
    handoffs: [{
      id: 'handoff-1',
      sourceParticipantId: 'p-earth',
      targetParticipantId: 'p-mars',
      state: 'dispatched',
      createdAtMs: 5,
    }],
  });

  it('projects Sol, every partner and every WorkItem as one node each', () => {
    const mesh = buildRoomFocusMesh(focus);

    // Work nodes take ring slots grouped near their owner, so assert the set.
    expect(mesh.nodes.map((node) => node.id).sort()).toEqual([
      'partner:p-earth', 'partner:p-mars', 'partner:p-venus', 'root', 'work:work-child', 'work:work-root',
    ]);
    const root = mesh.nodes[0]!;
    expect(root.id).toBe('root');
    expect(root.state).toBe('running');
    // Partner nodes keep celestial identity plus the real display name.
    const earth = mesh.nodes.find((node) => node.id === 'partner:p-earth')!;
    expect(earth).toMatchObject({ label: 'Earth', sublabel: 'Agent Earth', orbit: 0, refId: 'p-earth' });
    // A real wave slot becomes the readable lane sublabel — never invented.
    const child = mesh.nodes.find((node) => node.id === 'work:work-child')!;
    expect(child.sublabel).toBe('∥ 轨道 2/2');
    expect(mesh.nodes.find((node) => node.id === 'work:work-root')!.sublabel).toBeUndefined();
  });

  it('draws only recorded relations as edges', () => {
    const mesh = buildRoomFocusMesh(focus);
    const byKind = (kind: string) => mesh.edges.filter((edge) => edge.kind === kind);

    // Lineage: root work hangs off Sol, the child off its real parent.
    expect(byKind('parent').map((edge) => `${edge.sourceId}->${edge.targetId}`)).toEqual([
      'root->work:work-root', 'work:work-root->work:work-child',
    ]);
    // Ownership per WorkItem owner, colored by the work state.
    expect(byKind('ownership').map((edge) => `${edge.sourceId}->${edge.targetId}`)).toEqual([
      'partner:p-venus->work:work-root', 'partner:p-mars->work:work-child',
    ]);
    expect(byKind('ownership')[0]!.state).toBe('review');
    // Accountability only when it differs from the owner.
    expect(byKind('accountable').map((edge) => `${edge.sourceId}->${edge.targetId}`)).toEqual([
      'partner:p-earth->work:work-root',
    ]);
    // Review only from a recorded verdict.
    expect(byKind('review').map((edge) => `${edge.sourceId}->${edge.targetId}`)).toEqual([
      'partner:p-venus->work:work-root',
    ]);
    // Handoffs stay directed partner→partner with their lifecycle state.
    const handoff = byKind('handoff')[0]!;
    expect(handoff).toMatchObject({ sourceId: 'partner:p-earth', targetId: 'partner:p-mars', state: 'dispatched' });
    expect(handoff.tip).toBeDefined();
    expect(mesh.edges).toHaveLength(7);
    expect(mesh.edgeKinds).toEqual(['ownership', 'accountable', 'review', 'parent', 'handoff']);
  });

  it('never fabricates edges for unknown actors, self-handoffs or duplicates', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth')],
      workItems: [work('work-a', { ownerParticipantId: 'p-gone', parentId: 'work-missing' })],
      handoffs: [
        { id: 'h-unknown', sourceParticipantId: 'p-earth', targetParticipantId: 'p-gone', state: 'offered', createdAtMs: 1 },
        { id: 'h-self', sourceParticipantId: 'p-earth', targetParticipantId: 'p-earth', state: 'offered', createdAtMs: 2 },
      ],
    }));

    // The missing parent falls back to Sol; nothing points at absent partners.
    expect(mesh.edges.map((edge) => edge.id)).toEqual(['parent:root->work:work-a']);
    expect(mesh.edgeKinds).toEqual(['parent']);

    const twice = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      handoffs: [
        { id: 'h-1', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', state: 'dispatched', createdAtMs: 1 },
        { id: 'h-2', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', state: 'completed', createdAtMs: 2 },
      ],
    }));
    // One visual relation per pair — repeats never stack into spaghetti.
    expect(twice.edges.filter((edge) => edge.kind === 'handoff')).toHaveLength(1);
  });

  it('is deterministic and keeps every node inside the canvas', () => {
    const first = buildRoomFocusMesh(focus);
    const second = buildRoomFocusMesh(focus);
    expect(second).toEqual(first);

    for (const node of first.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(100);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(100);
    }
    // Owned work slots sit nearer their owner than any other partner.
    const mars = first.nodes.find((node) => node.id === 'partner:p-mars')!;
    const venus = first.nodes.find((node) => node.id === 'partner:p-venus')!;
    const child = first.nodes.find((node) => node.id === 'work:work-child')!;
    const distance = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
    expect(distance(child, mars)).toBeLessThan(distance(child, venus));
  });

  it('labels every edge kind for the legend', () => {
    expect(roomFocusMeshEdgeKindLabel('ownership')).toBe('负责');
    expect(roomFocusMeshEdgeKindLabel('handoff')).toBe('交接');
  });
});
