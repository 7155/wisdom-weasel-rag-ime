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
