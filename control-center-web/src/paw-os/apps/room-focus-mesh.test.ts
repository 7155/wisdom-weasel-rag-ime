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
        updatedAtMs: 40,
      }),
      work('work-child', {
        parentId: 'work-root',
        ownerParticipantId: 'p-mars',
        wave: { waveId: 'wave-a', parallelIndex: 1, parallelSize: 2 },
        updatedAtMs: 25,
      }),
    ],
    handoffs: [{
      id: 'handoff-1',
      sourceParticipantId: 'p-earth',
      targetParticipantId: 'p-mars',
      state: 'dispatched',
      createdAtMs: 5,
    }],
    flow: [{
      id: 'packet-1',
      sourceParticipantId: 'root',
      targetParticipantIds: ['p-earth'],
      kind: 'request',
      summary: '目标交给 Earth',
      status: 'completed',
      createdAtMs: 2,
      sequence: 1,
      refs: [],
    }],
  });

  it('projects Sol, every partner and every WorkItem as one node each', () => {
    const mesh = buildRoomFocusMesh(focus);

    expect(mesh.nodes.map((node) => node.id).sort()).toEqual([
      'partner:p-earth', 'partner:p-mars', 'partner:p-venus', 'root', 'work:work-child', 'work:work-root',
    ]);
    const root = mesh.nodes[0]!;
    expect(root.id).toBe('root');
    expect(root.state).toBe('running');
    // Partner nodes keep celestial identity plus the real display name.
    const earth = mesh.nodes.find((node) => node.id === 'partner:p-earth')!;
    expect(earth).toMatchObject({ label: 'Earth', sublabel: 'Agent Earth', tone: 0, refId: 'p-earth' });
    // A real wave slot becomes the readable lane sublabel — never invented.
    const child = mesh.nodes.find((node) => node.id === 'work:work-child')!;
    expect(child.sublabel).toBe('∥ 轨道 2/2');
    expect(mesh.nodes.find((node) => node.id === 'work:work-root')!.sublabel).toBeUndefined();
  });

  it('lays nodes on chronological rows — reading down is reading real event order', () => {
    const mesh = buildRoomFocusMesh(focus);

    // Earth enters at the flow packet (t=2), Mars at the handoff (t=5), the
    // child WorkItem updated at t=25, Venus first named at t=40 just ahead of
    // the WorkItem that names her. Sol is the origin row.
    const ordered = [...mesh.nodes].sort((left, right) => left.y - right.y).map((node) => node.id);
    expect(ordered).toEqual([
      'root', 'partner:p-earth', 'partner:p-mars', 'work:work-child', 'partner:p-venus', 'work:work-root',
    ]);
    // One row per node: no two nodes share a y, so the order stays readable.
    const rows = [...mesh.nodes].map((node) => node.y).sort((left, right) => left - right);
    for (let index = 1; index < rows.length; index += 1) expect(rows[index]!).toBeGreaterThan(rows[index - 1]!);
  });

  it('keeps every node in its actor identity lane with a lifeline per actor', () => {
    const mesh = buildRoomFocusMesh(focus);
    const at = (id: string) => mesh.nodes.find((node) => node.id === id)!;

    // Sol owns the leftmost origin lane; work sits in its owner's lane.
    for (const node of mesh.nodes) if (node.id !== 'root') expect(at('root').x).toBeLessThan(node.x);
    expect(at('work:work-child').x).toBe(at('partner:p-mars').x);
    expect(at('work:work-root').x).toBe(at('partner:p-venus').x);

    // One lifeline per actor, dropping from the actor's entry row.
    expect(mesh.lanes.map((lane) => lane.id)).toEqual(['root', 'p-earth', 'p-mars', 'p-venus']);
    for (const lane of mesh.lanes) {
      const node = at(lane.id === 'root' ? 'root' : `partner:${lane.id}`);
      expect(lane.x).toBe(node.x);
      expect(lane.y0).toBe(node.y);
      expect(lane.y1).toBeLessThanOrEqual(mesh.height);
    }
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
    // Ownership drops straight down the lane; the review verdict on the same
    // endpoints bows aside so both relations stay legible.
    expect(byKind('ownership')[0]!.path).not.toBe(byKind('review')[0]!.path);
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

    // The missing parent falls back to Sol — and so does the lane; nothing
    // points at absent partners.
    expect(mesh.edges.map((edge) => edge.id)).toEqual(['parent:root->work:work-a']);
    expect(mesh.edgeKinds).toEqual(['parent']);
    expect(mesh.nodes.find((node) => node.id === 'work:work-a')!.x)
      .toBe(mesh.nodes.find((node) => node.id === 'root')!.x);

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

  it('never invents a time — a partner with no recorded involvement waits on the origin row', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      workItems: [work('work-a', { ownerParticipantId: 'p-earth', updatedAtMs: 10 })],
    }));
    const at = (id: string) => mesh.nodes.find((node) => node.id === id)!;

    expect(at('partner:p-mars').y).toBe(at('root').y);
    expect(at('partner:p-earth').y).toBeGreaterThan(at('root').y);
    expect(at('work:work-a').y).toBeGreaterThan(at('partner:p-earth').y);
  });

  it('is deterministic, keeps every node inside the canvas and grows with the timeline', () => {
    const first = buildRoomFocusMesh(focus);
    const second = buildRoomFocusMesh(focus);
    expect(second).toEqual(first);

    for (const node of first.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(100);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(first.height);
    }

    // More recorded events → a taller timeline, never a denser orbit.
    const longer = buildRoomFocusMesh(projection({
      partners: focus.partners,
      workItems: [
        ...focus.workItems,
        work('work-late-1', { ownerParticipantId: 'p-earth', updatedAtMs: 50 }),
        work('work-late-2', { ownerParticipantId: 'p-mars', updatedAtMs: 60 }),
      ],
      handoffs: focus.handoffs,
      flow: focus.flow,
    }));
    expect(longer.height).toBeGreaterThan(first.height);

    // A quiet room still renders a readable band, not a zero-height strip.
    const quiet = buildRoomFocusMesh(projection({ partners: [partner('p-earth', 'Earth')] }));
    expect(quiet.height).toBeGreaterThanOrEqual(36);
  });

  it('labels every edge kind for the legend', () => {
    expect(roomFocusMeshEdgeKindLabel('ownership')).toBe('负责');
    expect(roomFocusMeshEdgeKindLabel('handoff')).toBe('交接');
  });
});
