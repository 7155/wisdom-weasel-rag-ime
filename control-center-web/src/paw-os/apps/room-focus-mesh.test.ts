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
      partner('p-earth', 'Earth', { collaborationRole: 'coordinator' }),
      partner('p-mars', 'Mars'),
      partner('p-venus', 'Venus', { collaborationRole: 'reviewer', state: 'review' }),
    ],
    workItems: [
      work('work-root', {
        ownerParticipantId: 'p-earth',
        accountableParticipantId: 'p-mars',
        objective: '整合协作图',
      }),
      work('work-child', {
        parentId: 'work-root',
        ownerParticipantId: 'p-mars',
        objective: '实现关系投影',
        review: { operability: 'passed', requirement: 'satisfied', reviewerParticipantId: 'p-venus' },
      }),
    ],
    handoffs: [{
      id: 'handoff-earth-mars',
      sourceParticipantId: 'p-earth',
      targetParticipantId: 'p-mars',
      state: 'completed',
      createdAtMs: 2,
    }],
    flow: [
      {
        id: 'question-mars-venus', sourceParticipantId: 'p-mars', targetParticipantIds: ['p-venus'],
        kind: 'question', summary: '请复核', status: 'completed', createdAtMs: 3, sequence: 1, refs: [],
      },
      {
        id: 'answer-venus-mars', sourceParticipantId: 'p-venus', targetParticipantIds: ['p-mars'],
        kind: 'answer', summary: '已复核', status: 'completed', createdAtMs: 4, sequence: 2, refs: [],
      },
    ],
  });

  it('keeps the graph partner-only even when a coordinator hosts the Room', () => {
    const mesh = buildRoomFocusMesh(focus);

    expect(mesh.nodes.map((node) => node.id)).toEqual([
      'partner:p-earth', 'partner:p-mars', 'partner:p-venus',
    ]);
    expect(mesh.nodes.every((node) => node.kind === 'partner')).toBe(true);
    expect(mesh.nodes.some((node) => node.id === 'root' || node.label === 'Sol')).toBe(false);
    expect(mesh.edges.every((edge) => (
      edge.sourceId.startsWith('partner:') && edge.targetId.startsWith('partner:')
    ))).toBe(true);
  });

  it('keeps planet identity and a readable responsibility on every node', () => {
    const mesh = buildRoomFocusMesh(focus);
    expect(mesh.nodes[0]).toMatchObject({ label: 'Earth', responsibility: '整合协作图', tone: 0 });
    expect(mesh.nodes[0]).not.toHaveProperty('sublabel');
    expect(mesh.nodes[1]).toMatchObject({ label: 'Mars', responsibility: '实现关系投影', tone: 1 });
    expect(mesh.nodes[2]).toMatchObject({ label: 'Venus', responsibility: '独立复核', tone: 2 });
  });

  it('projects only real peer responsibility, dependency, handoff, question, answer and review relations', () => {
    const mesh = buildRoomFocusMesh(focus);
    const endpoint = (kind: string) => mesh.edges
      .filter((edge) => edge.kind === kind)
      .map((edge) => `${edge.sourceId}->${edge.targetId}`);

    expect(endpoint('responsibility')).toEqual(['partner:p-mars->partner:p-earth']);
    expect(endpoint('dependency')).toEqual(['partner:p-earth->partner:p-mars']);
    expect(endpoint('handoff')).toEqual(['partner:p-earth->partner:p-mars']);
    expect(endpoint('question')).toEqual(['partner:p-mars->partner:p-venus']);
    expect(endpoint('answer')).toEqual(['partner:p-venus->partner:p-mars']);
    expect(endpoint('review')).toEqual(['partner:p-venus->partner:p-mars']);
    expect(mesh.edgeKinds).toEqual([
      'responsibility', 'dependency', 'handoff', 'question', 'answer', 'review',
    ]);
    expect(mesh.edges.every((edge) => edge.label && edge.tip)).toBe(true);
  });

  it('ignores root packets, unknown partners, self-relations and duplicate visual edges', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      handoffs: [
        { id: 'unknown', sourceParticipantId: 'p-earth', targetParticipantId: 'p-gone', state: 'offered', createdAtMs: 1 },
        { id: 'self', sourceParticipantId: 'p-earth', targetParticipantId: 'p-earth', state: 'offered', createdAtMs: 2 },
        { id: 'first', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', state: 'offered', createdAtMs: 3 },
        { id: 'repeat', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', state: 'completed', createdAtMs: 4 },
      ],
      flow: [{
        id: 'root-question', sourceParticipantId: 'root', targetParticipantIds: ['p-earth'],
        kind: 'question', summary: 'root', status: 'completed', createdAtMs: 1, sequence: 1, refs: [],
      }],
    }));

    expect(mesh.edges).toHaveLength(1);
    expect(mesh.edges[0]).toMatchObject({ kind: 'handoff', sourceId: 'partner:p-earth', targetId: 'partner:p-mars' });
  });

  it('lays all eight established planet names in a stable four-column grid', () => {
    const names = ['Earth', 'Mars', 'Venus', 'Jupiter', 'Saturn', 'Mercury', 'Neptune', 'Uranus'];
    const mesh = buildRoomFocusMesh(projection({
      partners: names.map((name, index) => partner(`p-${index}`, name)),
    }));
    expect(mesh.nodes.map((node) => node.label)).toEqual(names);
    expect(new Set(mesh.nodes.map((node) => node.x))).toHaveLength(4);
    expect(new Set(mesh.nodes.map((node) => node.y))).toHaveLength(2);
    expect(buildRoomFocusMesh(projection({ partners: names.map((name, index) => partner(`p-${index}`, name)) }))).toEqual(mesh);
  });

  it('labels every supported relation for the graph legend', () => {
    expect(roomFocusMeshEdgeKindLabel('responsibility')).toBe('职责');
    expect(roomFocusMeshEdgeKindLabel('dependency')).toBe('任务依赖');
    expect(roomFocusMeshEdgeKindLabel('handoff')).toBe('交接');
    expect(roomFocusMeshEdgeKindLabel('question')).toBe('询问');
    expect(roomFocusMeshEdgeKindLabel('answer')).toBe('回复');
    expect(roomFocusMeshEdgeKindLabel('review')).toBe('复核');
  });
});
