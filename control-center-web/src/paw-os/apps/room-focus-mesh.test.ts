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
    expect(mesh.nodes[0]).toMatchObject({ label: 'Earth', sublabel: '进行中', responsibility: '整合协作图', tone: 0 });
    expect(mesh.nodes[1]).toMatchObject({ label: 'Mars', responsibility: '实现关系投影', tone: 1 });
    expect(mesh.nodes[2]).toMatchObject({ label: 'Venus', responsibility: '独立复核', tone: 2 });
  });

  it('projects only real peer relations and keeps structural WorkItems out of gravity', () => {
    const mesh = buildRoomFocusMesh(focus);
    const endpoint = (kind: string) => mesh.edges
      .filter((edge) => edge.kind === kind)
      .map((edge) => `${edge.sourceId}->${edge.targetId}`);

    expect(endpoint('responsibility')).toEqual([]);
    expect(endpoint('dependency')).toEqual([]);
    expect(endpoint('handoff')).toEqual(['partner:p-earth->partner:p-mars']);
    expect(endpoint('question')).toEqual(['partner:p-mars->partner:p-venus']);
    expect(endpoint('receipt')).toEqual(['partner:p-venus->partner:p-mars']);
    expect(endpoint('review')).toEqual([]);
    expect(mesh.edgeKinds).toEqual([
      'handoff', 'question', 'receipt',
    ]);
    expect(mesh.nonDagRelations.some((relation) => (
      relation.kind === 'responsibility' || relation.kind === 'dependency' || relation.kind === 'review'
    ))).toBe(false);
    expect(mesh.edges.every((edge) => edge.label && edge.tip)).toBe(true);
    expect(mesh.edges.every((edge) => (edge.path.match(/\bQ\b/g) ?? []).length === 2)).toBe(true);
  });

  it('keeps a pending review request inspectable and places a confirmed conclusion in the review DAG', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-venus', 'Venus')],
      flow: [
        {
          id: 'review-request', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-venus'],
          kind: 'review', summary: '请求 Venus 复核', status: 'waiting', createdAtMs: 1, sequence: 1,
          workItemId: 'work-review', refs: ['trace:request'],
        },
        {
          id: 'review-conclusion', sourceParticipantId: 'p-venus', targetParticipantIds: ['p-earth'],
          kind: 'review', summary: '复核通过', status: 'completed', createdAtMs: 2, sequence: 2,
          workItemId: 'work-review', refs: ['trace:conclusion'],
        },
      ],
    }));

    expect(mesh.edges).toEqual([
      expect.objectContaining({
        kind: 'review', sourceId: 'partner:p-venus', targetId: 'partner:p-earth',
        provenance: {
          eventIds: ['review-conclusion'], workItemIds: ['work-review'], dispatchIds: [], refs: ['trace:conclusion'],
        },
      }),
    ]);
    expect(mesh.nonDagRelations).toEqual([
      expect.objectContaining({
        kind: 'review', sourceId: 'partner:p-earth', targetId: 'partner:p-venus', state: 'waiting',
        reason: '尚未确认，未建立成功关系',
        provenance: {
          eventIds: ['review-request'], workItemIds: ['work-review'], dispatchIds: [], refs: ['trace:request'],
        },
      }),
    ]);
  });

  it('does not create an edge, non-DAG attempt, or flow packet from structural WorkItems alone', () => {
    const structural = projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars'), partner('p-venus', 'Venus')],
      workItems: [
        work('structural-root', {
          ownerParticipantId: 'p-earth',
          accountableParticipantId: 'p-mars',
          objective: '结构任务表中的主任务',
        }),
        work('structural-child', {
          parentId: 'structural-root',
          ownerParticipantId: 'p-mars',
          verifierParticipantId: 'p-venus',
          reviewRequired: true,
          review: { operability: 'passed', requirement: 'satisfied', reviewerParticipantId: 'p-venus' },
          objective: '结构任务表中的复核任务',
        }),
      ],
    });

    const mesh = buildRoomFocusMesh(structural);

    expect(mesh.edges).toEqual([]);
    expect(mesh.nonDagRelations).toEqual([]);
    expect(mesh.edgeKinds).toEqual([]);
  });

  it('projects direct peer mentions, dispatches, receipts and results with their real terminal state', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars'), partner('p-venus', 'Venus')],
      flow: [
        {
          id: 'mention-earth-mars', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'request', summary: '@Mars 请补充证据', status: 'completed', createdAtMs: 1, sequence: 1, refs: [],
        },
        {
          id: 'dispatch-mars-venus', sourceParticipantId: 'p-mars', targetParticipantIds: ['p-venus'],
          kind: 'dispatch', summary: '委派复核', status: 'failed', createdAtMs: 2, sequence: 2,
          dispatchId: 'dispatch-mars-venus', refs: [],
        },
        {
          id: 'result-venus-earth', sourceParticipantId: 'p-venus', targetParticipantIds: ['p-earth'],
          kind: 'result', summary: '复核结果已回执', status: 'completed', createdAtMs: 3, sequence: 3,
          refs: [],
        },
        {
          id: 'receipt-earth-venus', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-venus'],
          kind: 'answer', summary: '收到', status: 'delivered', createdAtMs: 4, sequence: 4, refs: [],
        },
      ],
    }));
    const edge = (kind: string) => mesh.edges.find((candidate) => candidate.kind === kind);

    expect(edge('mention')).toMatchObject({
      sourceId: 'partner:p-earth', targetId: 'partner:p-mars', state: 'completed',
    });
    expect(edge('dispatch')).toBeUndefined();
    expect(mesh.nonDagRelations.find((relation) => relation.kind === 'dispatch')).toMatchObject({
      sourceId: 'partner:p-mars', targetId: 'partner:p-venus', state: 'failed',
    });
    expect(edge('result')).toMatchObject({
      sourceId: 'partner:p-venus', targetId: 'partner:p-earth', state: 'completed',
    });
    expect(edge('receipt')).toBeUndefined();
    expect(mesh.nonDagRelations.find((relation) => relation.kind === 'receipt')).toMatchObject({
      sourceId: 'partner:p-earth', targetId: 'partner:p-venus', state: 'delivered',
    });
    expect(mesh.edgeKinds).toEqual(['mention', 'result']);
  });

  it('keeps delivery lifecycle states distinct and only establishes confirmed or completed relations', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        'sent', 'delivered', 'received', 'replied', 'accepted', 'confirmed', 'completed',
      ].map((status, sequence) => ({
        id: `lifecycle-${status}`,
        sourceParticipantId: 'p-earth',
        targetParticipantIds: ['p-mars'],
        kind: 'request' as const,
        summary: status,
        status,
        createdAtMs: sequence + 1,
        sequence,
        refs: [],
      })),
    }));

    expect(mesh.edges).toHaveLength(1);
    expect(mesh.edges[0]).toMatchObject({ state: 'completed' });
    expect(mesh.nonDagRelations.map((relation) => relation.state)).toEqual([
      'sent', 'delivered', 'received', 'replied', 'accepted',
    ]);
  });

  it('keeps an intercom request distinct from an explicit @ mention', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [{
        id: 'intercom-earth-mars',
        sourceParticipantId: 'p-earth',
        targetParticipantIds: ['p-mars'],
        kind: 'intercom',
        summary: '请同步当前进展',
        status: 'completed',
        createdAtMs: 1,
        sequence: 1,
        refs: [],
      }],
    }));

    expect(mesh.edges).toEqual([
      expect.objectContaining({
        kind: 'request', label: '请求', sourceId: 'partner:p-earth', targetId: 'partner:p-mars',
      }),
    ]);
    expect(mesh.edges.some((edge) => edge.kind === 'mention')).toBe(false);
  });

  it('keeps the confirmed retry relation and discloses the failed attempt', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        {
          id: 'mention-attempt-1', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'request', summary: '@Mars 第一次请求', status: 'completed', createdAtMs: 1, sequence: 1, refs: [],
        },
        {
          id: 'mention-attempt-2', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'request', summary: '@Mars 重试失败', status: 'failed', createdAtMs: 2, sequence: 2, refs: [],
        },
      ],
    }));
    const mention = mesh.edges.find((edge) => edge.kind === 'mention');

    expect(mention).toMatchObject({
      state: 'completed',
      provenance: { eventIds: ['mention-attempt-1'] },
    });
    expect(mesh.nonDagRelations).toEqual([
      expect.objectContaining({
        kind: 'mention',
        state: 'failed',
        provenance: expect.objectContaining({ eventIds: ['mention-attempt-2'] }),
      }),
    ]);
  });

  it('honors sequence zero when choosing the latest real relation state', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        {
          id: 'mention-sequence-zero', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'request', summary: '@Mars 首次请求', status: 'completed', createdAtMs: 100, sequence: 0, refs: [],
        },
        {
          id: 'mention-sequence-one', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'request', summary: '@Mars 后续失败', status: 'failed', createdAtMs: 2, sequence: 1, refs: [],
        },
      ],
    }));

    expect(mesh.edges.find((edge) => edge.kind === 'mention')).toMatchObject({
      state: 'completed',
      provenance: { eventIds: ['mention-sequence-zero'] },
    });
    expect(mesh.nonDagRelations).toEqual([
      expect.objectContaining({
        kind: 'mention',
        state: 'failed',
        provenance: expect.objectContaining({ eventIds: ['mention-sequence-one'] }),
      }),
    ]);
  });

  it('keeps a confirmed dispatch in the DAG while exposing its failed retry separately', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        {
          id: 'dispatch-success', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '成功分派', status: 'completed', createdAtMs: 1, sequence: 1,
          dispatchId: 'dispatch-shared', refs: [],
        },
        {
          id: 'dispatch-failed', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '失败分派重试', status: 'failed', createdAtMs: 2, sequence: 2,
          dispatchId: 'dispatch-shared', refs: [],
        },
      ],
    }));

    expect(mesh.edges).toHaveLength(1);
    expect(mesh.edges[0]).toMatchObject({
      kind: 'dispatch',
      state: 'completed',
        provenance: expect.objectContaining({ eventIds: ['dispatch-success'], dispatchIds: ['dispatch-shared'] }),
    });
    expect(mesh.nonDagRelations).toEqual([
      expect.objectContaining({
        kind: 'dispatch',
        sourceId: 'partner:p-earth',
        targetId: 'partner:p-mars',
        state: 'failed',
        summary: '失败分派重试',
        reason: expect.stringContaining('失败'),
        provenance: expect.objectContaining({ eventIds: ['dispatch-failed'], dispatchIds: ['dispatch-shared'] }),
      }),
    ]);
  });

  it('keeps every confirmed attempt as an ordered receipt on one established edge', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        {
          id: 'dispatch-success-2', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '第二次成功分派', status: 'completed', createdAtMs: 20, sequence: 2,
          dispatchId: 'dispatch-shared', refs: [],
        },
        {
          id: 'dispatch-success-1', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '第一次成功分派', status: 'completed', createdAtMs: 10, sequence: 1,
          dispatchId: 'dispatch-shared', refs: [],
        },
      ],
    }));
    const edge = mesh.edges[0];

    expect(edge).toMatchObject({
      kind: 'dispatch',
      state: 'completed',
      provenance: expect.objectContaining({ eventIds: ['dispatch-success-1', 'dispatch-success-2'] }),
    });
    expect(edge?.attempts).toEqual([
      expect.objectContaining({
        state: 'completed', summary: '第一次成功分派', createdAtMs: 10, sequence: 1,
        provenance: expect.objectContaining({ eventIds: ['dispatch-success-1'], dispatchIds: ['dispatch-shared'] }),
      }),
      expect.objectContaining({
        state: 'completed', summary: '第二次成功分派', createdAtMs: 20, sequence: 2,
        provenance: expect.objectContaining({ eventIds: ['dispatch-success-2'], dispatchIds: ['dispatch-shared'] }),
      }),
    ]);
  });

  it('keeps confirmed workflow relations acyclic and surfaces a confirmed cycle as a conflict', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars')],
      flow: [
        {
          id: 'dispatch-forward', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '向 Mars 分派', status: 'completed', createdAtMs: 1, sequence: 1,
          dispatchId: 'dispatch-forward', refs: [],
        },
        {
          id: 'dispatch-backward', sourceParticipantId: 'p-mars', targetParticipantIds: ['p-earth'],
          kind: 'dispatch', summary: '反向分派', status: 'completed', createdAtMs: 2, sequence: 2,
          dispatchId: 'dispatch-backward', refs: [],
        },
        {
          id: 'dispatch-backward-retry', sourceParticipantId: 'p-mars', targetParticipantIds: ['p-earth'],
          kind: 'dispatch', summary: '反向分派重试', status: 'completed', createdAtMs: 3, sequence: 3,
          dispatchId: 'dispatch-backward-retry', refs: [],
        },
      ],
    }));

    expect(mesh.edges.map((edge) => `${edge.sourceId}->${edge.targetId}`)).toEqual([
      'partner:p-earth->partner:p-mars',
    ]);
    const conflicts = mesh.nonDagRelations.filter((relation) => (
      relation.sourceId === 'partner:p-mars' && relation.targetId === 'partner:p-earth'
    ));
    expect(conflicts).toHaveLength(2);
    expect(conflicts.map((relation) => relation.provenance.eventIds)).toEqual([
      ['dispatch-backward'],
      ['dispatch-backward-retry'],
    ]);
    expect(conflicts.every((relation) => (
      relation.state === 'completed' && relation.reason.includes('循环')
    ))).toBe(true);
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
    expect(mesh.edges[0]).toMatchObject({ kind: 'handoff', sourceId: 'partner:p-earth', targetId: 'partner:p-mars', state: 'completed' });
  });

  it('lays all eight established planet names in a readable two-column grid', () => {
    const names = ['Earth', 'Mars', 'Venus', 'Jupiter', 'Saturn', 'Mercury', 'Neptune', 'Uranus'];
    const mesh = buildRoomFocusMesh(projection({
      partners: names.map((name, index) => partner(`p-${index}`, name, {
        currentAction: '核对一段足够长的职责说明，确保两排行星节点不会互相覆盖',
      })),
    }));
    expect(mesh.nodes.map((node) => node.label)).toEqual(names);
    expect(new Set(mesh.nodes.map((node) => node.x))).toHaveLength(2);
    const rows = [...new Set(mesh.nodes.map((node) => node.y))];
    expect(rows).toHaveLength(4);
    expect(rows[1]! - rows[0]!).toBeGreaterThanOrEqual(40);
    expect(mesh.height - rows[1]!).toBeGreaterThanOrEqual(20);
    expect(buildRoomFocusMesh(projection({
      partners: names.map((name, index) => partner(`p-${index}`, name, {
        currentAction: '核对一段足够长的职责说明，确保两排行星节点不会互相覆盖',
      })),
    }))).toEqual(mesh);
  });

  it('lays confirmed workflow relations from earlier to later layers', () => {
    const mesh = buildRoomFocusMesh(projection({
      partners: [partner('p-earth', 'Earth'), partner('p-mars', 'Mars'), partner('p-venus', 'Venus')],
      flow: [
        {
          id: 'dispatch-earth-mars', sourceParticipantId: 'p-earth', targetParticipantIds: ['p-mars'],
          kind: 'dispatch', summary: '分派实现', status: 'completed', createdAtMs: 1, sequence: 1, refs: [],
        },
        {
          id: 'review-mars-venus', sourceParticipantId: 'p-mars', targetParticipantIds: ['p-venus'],
          kind: 'review', summary: '交给复核', status: 'completed', createdAtMs: 2, sequence: 2, refs: [],
        },
      ],
    }));
    const node = (id: string) => mesh.nodes.find((candidate) => candidate.refId === id)!;

    expect(node('p-earth').y).toBeLessThan(node('p-mars').y);
    expect(node('p-mars').y).toBeLessThan(node('p-venus').y);
    expect(new Set(mesh.edges.map((edge) => `${edge.labelX}:${edge.labelY}`)).size).toBe(mesh.edges.length);
  });

  it('labels every supported relation for the graph legend', () => {
    expect(roomFocusMeshEdgeKindLabel('responsibility')).toBe('职责');
    expect(roomFocusMeshEdgeKindLabel('dependency')).toBe('任务依赖');
    expect(roomFocusMeshEdgeKindLabel('handoff')).toBe('交接');
    expect(roomFocusMeshEdgeKindLabel('question')).toBe('询问');
    expect(roomFocusMeshEdgeKindLabel('answer')).toBe('回复');
    expect(roomFocusMeshEdgeKindLabel('review')).toBe('复核');
    expect(roomFocusMeshEdgeKindLabel('mention')).toBe('@ 提及');
    expect(roomFocusMeshEdgeKindLabel('dispatch')).toBe('分派');
    expect(roomFocusMeshEdgeKindLabel('receipt')).toBe('回执');
    expect(roomFocusMeshEdgeKindLabel('result')).toBe('结果');
  });
});
