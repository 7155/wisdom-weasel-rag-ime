import { describe, expect, it } from 'vitest';
import { createRoomProjection, type RoomProjectionState } from '@/contracts/room-reducer';
import type { RoomSummary, RoomWorkItem } from '@/features/rooms/room-types';
import { buildRoomFocusProjection } from './room-focus-projection';

function participant(id: string, ordinal: number, displayName = `Agent ${ordinal + 1}`) {
  return {
    id,
    sessionId: `session-${id}`,
    roleId: `role-${id}`,
    roleVersion: '1',
    displayName,
    collaborationRole: ordinal === 0 ? 'coordinator' as const : 'implementer' as const,
    status: 'active',
    ordinal,
  };
}

function work(overrides: Partial<RoomWorkItem> & Pick<RoomWorkItem, 'id' | 'objective'>): RoomWorkItem {
  const { id, objective, ...rest } = overrides;
  return {
    id,
    roomId: 'room-sol',
    topicId: 'topic-1',
    rootTurnId: 'turn-root',
    rootWorkId: overrides.id,
    parentWorkId: '',
    objective,
    expectedOutput: '可核验交付',
    acceptanceCriteria: [],
    accountableParticipantId: 'p-earth',
    currentOwnerParticipantId: 'p-earth',
    offeredToParticipantId: '',
    createdByParticipantId: 'p-earth',
    clientMessageId: `client-${overrides.id}`,
    state: 'active',
    depth: 0,
    revision: 1,
    resultSummary: '',
    artifactRefs: [],
    evidenceRefs: [],
    blocker: {},
    acceptedTurnId: '',
    createdAtMs: 10,
    updatedAtMs: 10,
    completedAtMs: null,
    ...rest,
  };
}

function room(workItems: RoomWorkItem[] = []): RoomSummary {
  return {
    id: 'room-sol',
    title: '迁移作战室',
    description: '整合前端并交给独立伙伴复核',
    status: 'active',
    routingPolicy: 'parallel',
    moderatorParticipantId: 'p-earth',
    activeTopicId: 'topic-1',
    updatedAtMs: 20,
    participants: [
      participant('p-earth', 0),
      participant('p-mars', 1),
      participant('p-venus', 2),
    ],
    topics: [{
      id: 'topic-1',
      roomId: 'room-sol',
      title: '任务图依赖验证',
      summary: '两个实现分支汇合后复核。',
      status: 'active',
      ordinal: 0,
      createdAtMs: 1,
      updatedAtMs: 2,
    }],
    workItems,
  };
}

function projectionWithParallelRuntime(): RoomProjectionState {
  const projection = createRoomProjection('room-sol');
  projection.activitiesById = {
    'activity-earth': {
      id: 'activity-earth',
      sequence: 2,
      turnId: 'turn-root',
      participantId: 'p-earth',
      sourceSessionId: 'session-p-earth',
      kind: 'tool',
      status: 'completed',
      summary: '任务图交互已通过测试',
      payload: {
        dispatchId: 'dispatch-earth',
        task: '实现 Room 任务图交互',
        expectedOutput: '可复查的任务图交互',
        toolName: 'vitest',
      },
      createdAtMs: 12,
      updatedAtMs: 13,
    },
    'activity-mars': {
      id: 'activity-mars',
      sequence: 3,
      turnId: 'turn-root',
      participantId: 'p-mars',
      sourceSessionId: 'session-p-mars',
      kind: 'tool',
      status: 'running',
      summary: '正在核对依赖投影',
      payload: {
        dispatchId: 'dispatch-mars',
        task: '实现 Room 依赖数据投影',
        expectedOutput: '可核验的依赖投影',
        toolName: 'read_file',
      },
      createdAtMs: 14,
      updatedAtMs: 15,
    },
  };
  projection.activityOrder = ['activity-earth', 'activity-mars'];
  return projection;
}

describe('buildRoomFocusProjection', () => {
  it('keeps the real goal and projects runtime branches beneath the explicit root work item', () => {
    const root = work({
      id: 'work-root',
      objective: '并行实现 Room 任务图，整合后独立复核',
      currentOwnerParticipantId: 'p-venus',
      accountableParticipantId: 'p-venus',
      state: 'review',
      resultSummary: '两个实现分支已汇合，等待独立复核。',
      evidenceRefs: ['test:room-graph-ui', 'test:room-graph-data'],
    });

    const focus = buildRoomFocusProjection(room([root]), projectionWithParallelRuntime());

    expect(focus.goal.title).toBe('任务图依赖验证');
    expect(focus.goal.state).toBe('review');
    expect(focus.workItems.map((item) => [item.id, item.parentId, item.ownerParticipantId, item.state])).toEqual([
      ['work-root', undefined, 'p-venus', 'review'],
      ['runtime:dispatch-earth', 'work-root', 'p-earth', 'completed'],
      ['runtime:dispatch-mars', 'work-root', 'p-mars', 'running'],
    ]);
    expect(focus.workItems[0]?.evidence.map((item) => item.ref)).toEqual([
      'test:room-graph-ui',
      'test:room-graph-data',
    ]);
  });

  it('keeps participant ids behind stable planet presentation names', () => {
    const focus = buildRoomFocusProjection(room(), createRoomProjection('room-sol'));

    expect(focus.partners.map((item) => [item.participantId, item.celestialName, item.displayName])).toEqual([
      ['p-earth', 'Earth', 'Agent 1'],
      ['p-mars', 'Mars', 'Agent 2'],
      ['p-venus', 'Venus', 'Agent 3'],
    ]);
  });

  it('projects the chronological flow ledger from public messages, transfers and WorkItem revisions', () => {
    const withWork = room([work({
      id: 'work-root',
      objective: '并行实现 Room 任务图',
      artifactRefs: ['docs/plan.md'],
      updatedAtMs: 400,
    })]);
    const projection = createRoomProjection('room-sol');
    projection.activityOrder = ['approval-a'];
    projection.activitiesById = {
      'approval-a': {
        id: 'approval-a', sequence: 5, turnId: 'turn-root', participantId: 'p-mars', sourceSessionId: 'session-p-mars',
        kind: 'approval_required', status: 'waiting', summary: '批准发布前检查',
        payload: { sourceEventType: 'approval_required', approvalId: 'approval:a', payloadSha256: 'a'.repeat(64) },
        createdAtMs: 120, updatedAtMs: 120,
      },
    };
    projection.messageOrder = ['message-user'];
    projection.messagesById = {
      'message-user': {
        id: 'message-user', roomId: 'room-sol', turnId: 'turn-root', participantId: null, sourceSessionId: '',
        role: 'user', status: 'completed', text: '请实现主线迁移', projectionKind: 'post',
        mentionedParticipantIds: ['p-earth'], sequence: 4, createdAtMs: 110,
      },
    };

    const focus = buildRoomFocusProjection(withWork, projection);

    expect(focus.flow.map((packet) => [packet.id, packet.kind, packet.sourceParticipantId, packet.targetParticipantIds])).toEqual([
      ['message:message-user', 'request', 'root', ['p-earth']],
      ['activity:approval-a', 'approval', 'p-mars', ['root']],
      ['work:work-root:1', 'document', 'p-earth', ['p-earth']],
    ]);
    expect(focus.flow.at(-1)?.refs).toEqual(['docs/plan.md']);
  });

  it.each([
    { label: 'dispatch（activity.kind）', kind: 'dispatch', payload: { targetParticipantId: 'p-earth' }, expectedKind: 'dispatch', project: true },
    { label: 'route_decision（activity.kind）', kind: 'route_decision', payload: { targetParticipantId: 'p-earth' }, expectedKind: 'dispatch', project: true },
    { label: 'intercom（payload.activityKind）', kind: 'participant_activity', payload: { activityKind: 'intercom', targetParticipantId: 'p-earth' }, expectedKind: 'request', project: true },
    { label: 'ContextRef 移交', kind: 'participant_activity', payload: { contextRefs: ['context://room-sol/brief'], targetParticipantId: 'p-earth' }, expectedKind: 'context', project: true },
    { label: '未知 activity 不投影', kind: 'participant_activity', payload: { sourceEventType: 'not_a_flow_event', targetParticipantId: 'p-earth' }, expectedKind: 'dispatch', project: false },
    { label: '无目标 dispatch 不投影', kind: 'dispatch', payload: {}, participantId: null, expectedKind: 'dispatch', project: false },
  ] as const)('projects $label into the ledger only when it is an authoritative targeted transfer', ({ kind, payload, participantId = 'p-mars', expectedKind, project }) => {
    const projection = createRoomProjection('room-sol');
    projection.activityOrder = ['activity-1'];
    projection.activitiesById = {
      'activity-1': {
        id: 'activity-1', turnId: 'turn-root', participantId, sourceSessionId: 'session-x',
        kind, status: 'completed', summary: 'activity-1', payload: payload as Record<string, unknown>,
        createdAtMs: 200, updatedAtMs: 200,
      },
    };

    const focus = buildRoomFocusProjection(room(), projection);
    const packet = focus.flow.find((candidate) => candidate.id === 'activity:activity-1');

    if (project) {
      expect(packet).toEqual(expect.objectContaining({ kind: expectedKind, targetParticipantIds: ['p-earth'] }));
    } else {
      expect(packet).toBeUndefined();
    }
  });

  it('makes a real offer visible as a directed handoff and preserves blocker recovery copy', () => {
    const blocked = work({
      id: 'work-blocked',
      objective: '恢复前端验收',
      currentOwnerParticipantId: 'p-earth',
      offeredToParticipantId: 'p-mars',
      accountableParticipantId: 'p-venus',
      state: 'blocked',
      blocker: { reason: '等待真实 Browser 权限', nextStep: '恢复连接后重跑前台验收' },
      updatedAtMs: 18,
    });

    const focus = buildRoomFocusProjection(room([blocked]), createRoomProjection('room-sol'));

    expect(focus.goal.state).toBe('blocked');
    expect(focus.workItems[0]?.blocker).toEqual({
      reason: '等待真实 Browser 权限',
      nextStep: '恢复连接后重跑前台验收',
    });
    expect(focus.handoffs).toContainEqual(expect.objectContaining({
      sourceParticipantId: 'p-earth',
      targetParticipantId: 'p-mars',
      workItemId: 'work-blocked',
      state: 'offered',
    }));
  });
});
