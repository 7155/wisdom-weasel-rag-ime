import { describe, expect, it } from 'vitest';

import {
  createRoomProjection,
  type RoomActivityProjection,
} from '@/contracts/room-reducer';

import {
  roomActivityNeedsSessionAction,
  selectActivePublicRoomTurn,
  selectPublicRoomTurnOrder,
  selectRoomExecutionOverview,
  selectRoomTurnExecution,
} from './room-execution-lanes';

describe('selectRoomTurnExecution', () => {
  it('lets only the latest public root decide whether the Room is active', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('stale-root', 'latest-root');
    projection.turnsById['stale-root'] = {
      id: 'stale-root', rootId: 'stale-root', status: 'running',
      messageIds: [], activityIds: [], participantIds: [],
      createdAtMs: 1, updatedAtMs: 2,
    };
    projection.turnsById['latest-root'] = {
      id: 'latest-root', rootId: 'latest-root', status: 'completed',
      messageIds: [], activityIds: [], participantIds: [],
      createdAtMs: 3, updatedAtMs: 4,
    };

    expect(selectActivePublicRoomTurn(projection)).toBeUndefined();

    projection.turnsById['latest-root']!.status = 'running';
    expect(selectActivePublicRoomTurn(projection)?.id).toBe('latest-root');
  });

  it('projects an active Pi Session dispatch into the task overview without a WorkItem', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1', rootId: 'root-1', status: 'running',
      messageIds: ['request-1'], activityIds: ['tool-1'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1, updatedAtMs: 3,
    };
    projection.messagesById['request-1'] = {
      id: 'request-1', roomId: 'room-1', turnId: 'root-1',
      participantId: null, sourceSessionId: '', role: 'user',
      status: 'completed', text: '修好 Room 的任务页', rootId: 'root-1',
      createdAtMs: 1,
    };
    projection.activitiesById['tool-1'] = {
      id: 'tool-1', turnId: 'root-1', participantId: 'participant-1',
      sourceSessionId: 'session-1', kind: 'participant_activity', status: 'running',
      summary: '正在读取真实运行',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'tool_started' },
      createdAtMs: 2,
    };

    expect(selectRoomExecutionOverview(projection)).toEqual([expect.objectContaining({
      id: 'root-1',
      objective: '修好 Room 的任务页',
      status: 'running',
      participantIds: ['participant-1'],
      laneCount: 1,
      toolCount: 1,
      lastSummary: '正在读取真实运行',
    })]);
  });

  it('removes the unscoped lifecycle slot before timeline virtualization', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('unscoped', 'root-1');

    expect(selectPublicRoomTurnOrder(projection)).toEqual(['root-1']);
  });

  it('keeps delivered intercom receipts out of the public turn lifecycle', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1', 'peer-delivery-turn');
    projection.turnsById['root-1'] = {
      id: 'root-1', rootId: 'root-1', status: 'completed',
      messageIds: ['request-1'], activityIds: [], participantIds: ['participant-a'],
      createdAtMs: 1, updatedAtMs: 4,
    };
    projection.messagesById['request-1'] = {
      id: 'request-1', roomId: 'room-1', turnId: 'root-1',
      participantId: null, sourceSessionId: '', role: 'user',
      status: 'completed', text: '直接询问伙伴', rootId: 'root-1',
      createdAtMs: 1,
    };
    projection.turnsById['peer-delivery-turn'] = {
      id: 'peer-delivery-turn', rootId: 'peer-delivery-turn', status: 'running',
      messageIds: [], activityIds: ['intercom-delivered'], participantIds: ['participant-b'],
      createdAtMs: 2, updatedAtMs: 3,
    };
    projection.activitiesById['intercom-delivered'] = {
      id: 'intercom-delivered', turnId: 'peer-delivery-turn',
      participantId: 'participant-b', sourceSessionId: 'session-b',
      kind: 'participant_activity', status: 'completed', summary: '伙伴沟通',
      payload: {
        activityKind: 'intercom',
        phase: 'delivered',
        message: {
          id: 'room-message-1', kind: 'reply', status: 'delivered',
          sourceParticipantId: 'participant-b',
          targetParticipantId: 'participant-a',
        },
      },
      createdAtMs: 2,
    };

    expect(selectPublicRoomTurnOrder(projection)).toEqual(['root-1']);
    expect(selectRoomExecutionOverview(projection)).toEqual([
      expect.objectContaining({ id: 'root-1', status: 'completed' }),
    ]);
  });

  it('projects a linked retry as one logical Room turn', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1', 'root-2', 'root-3');
    projection.turnsById['root-1'] = {
      id: 'root-1', status: 'failed', messageIds: [], activityIds: [], participantIds: [],
      createdAtMs: 1, updatedAtMs: 2,
    };
    projection.turnsById['root-2'] = {
      id: 'root-2', status: 'failed', retryOfRootId: 'root-1', messageIds: [], activityIds: [], participantIds: [],
      createdAtMs: 3, updatedAtMs: 4,
    };
    projection.turnsById['root-3'] = {
      id: 'root-3', status: 'running', retryOfRootId: 'root-2', messageIds: [], activityIds: [], participantIds: [],
      createdAtMs: 5, updatedAtMs: 6,
    };

    expect(selectPublicRoomTurnOrder(projection)).toEqual(['root-3']);
  });

  it('merges a payload-addressed route and its reply into one participant lane', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.activityOrder.push('route-1');
    projection.messageOrder.push('reply-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: ['reply-1'],
      activityIds: ['route-1'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.activitiesById['route-1'] = {
      id: 'route-1',
      turnId: 'root-1',
      participantId: null,
      sourceSessionId: 'session-1',
      kind: 'route_decision',
      status: 'completed',
      summary: '伙伴已接手',
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        targetParticipantId: 'participant-1',
      },
      createdAtMs: 1,
    };
    projection.messagesById['reply-1'] = {
      id: 'reply-1',
      roomId: 'room-1',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      role: 'assistant',
      status: 'streaming',
      text: '正在处理',
      projectionKind: 'execution',
      rootId: 'root-1',
      dispatchId: 'dispatch-1',
      createdAtMs: 2,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes).toHaveLength(1);
    expect(selected.lanes[0]).toMatchObject({
      participantId: 'participant-1',
      dispatchId: 'dispatch-1',
      messageIds: ['reply-1'],
    });
    expect(selected.lanes[0].activities.map((item) => item.id)).toEqual(['route-1']);
  });

  it('keeps an accepted answer in canonical message order after its question', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: ['opening', 'question', 'answer'],
      activityIds: [],
      participantIds: ['participant-1'],
      createdAtMs: 1,
      updatedAtMs: 3,
    };
    projection.messagesById.opening = {
      id: 'opening',
      roomId: 'room-1',
      turnId: 'root-1',
      participantId: null,
      sourceSessionId: '',
      role: 'user',
      status: 'completed',
      text: '开始改进',
      rootId: 'root-1',
      createdAtMs: 1,
    };
    projection.messagesById.question = {
      id: 'question',
      roomId: 'room-1',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      role: 'assistant',
      status: 'completed',
      text: '请选择方案',
      projectionKind: 'post',
      postKind: 'wait',
      rootId: 'root-1',
      dispatchId: 'dispatch-1',
      question: {
        prompt: '采用哪个方案？',
        options: [
          { value: 'safe', label: '稳妥方案' },
          { value: 'fast', label: '快速方案' },
        ],
        status: 'answered',
        answer: '稳妥方案',
      },
      createdAtMs: 2,
    };
    projection.messagesById.answer = {
      id: 'answer',
      roomId: 'room-1',
      turnId: 'root-1',
      participantId: null,
      sourceSessionId: '',
      role: 'user',
      status: 'completed',
      text: '稳妥方案',
      rootId: 'root-1',
      answerToPostId: 'question',
      createdAtMs: 3,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.messageIds).toEqual(['opening', 'question', 'answer']);
    expect(selected.userMessageIds).toEqual(['opening', 'answer']);
    expect(selected.lanes).toHaveLength(1);
    expect(selected.lanes[0]?.messageIds).toEqual(['question']);
  });

  it('uses authoritative event sequence before timestamp and a stable fallback for legacy messages', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: [
        'legacy-b',
        'server-late',
        'legacy-a',
        'server-early',
        'legacy-newer',
      ],
      activityIds: [],
      participantIds: [],
      createdAtMs: 1,
      updatedAtMs: 500,
    };
    const messages = [
      { id: 'legacy-b', text: 'legacy b', createdAtMs: 100 },
      {
        id: 'server-late',
        text: 'server late',
        createdAtMs: 1,
        sequence: 999,
        chronology: {
          schemaVersion: 'wisdom-weasel.room-post-chronology.v1' as const,
          roomEventId: 'event-2',
          roomEventSequence: 2,
          createdAtMs: 1,
          afterPostId: 'server-early',
          orderKey: 'room-event:00000000000000000002',
        },
      },
      { id: 'legacy-a', text: 'legacy a', createdAtMs: 100 },
      { id: 'server-early', text: 'server early', createdAtMs: 500, sequence: 1 },
      { id: 'legacy-newer', text: 'legacy newer', createdAtMs: 200 },
    ];
    for (const message of messages) {
      projection.messagesById[message.id] = {
        roomId: 'room-1',
        turnId: 'root-1',
        participantId: null,
        sourceSessionId: '',
        role: 'user',
        status: 'completed',
        rootId: 'root-1',
        ...message,
      };
    }

    expect(selectRoomTurnExecution(projection, 'root-1').messageIds).toEqual([
      'server-early',
      'server-late',
      'legacy-a',
      'legacy-b',
      'legacy-newer',
    ]);
  });

  it('keeps two dispatches owned by the same participant in separate slots', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: ['reply-a', 'reply-b'],
      activityIds: [],
      participantIds: ['participant-1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    for (const dispatchId of ['dispatch-a', 'dispatch-b']) {
      const messageId = `reply-${dispatchId.at(-1)}`;
      projection.messagesById[messageId] = {
        id: messageId,
        roomId: 'room-1',
        turnId: 'root-1',
        participantId: 'participant-1',
        sourceSessionId: 'session-1',
        role: 'assistant',
        status: 'streaming',
        text: dispatchId,
        projectionKind: 'execution',
        rootId: 'root-1',
        dispatchId,
        createdAtMs: 2,
      };
    }

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes.map((lane) => lane.dispatchId)).toEqual([
      'dispatch-a',
      'dispatch-b',
    ]);
  });

  it('keeps every Pi loop in its own lane even when the participant and dispatch are unchanged', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'completed',
      messageIds: ['first-result', 'root-final'],
      activityIds: ['first-loop', 'final-loop'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1,
      updatedAtMs: 6,
    };
    projection.activitiesById['first-loop'] = {
      ...activity('first-loop', 'dispatch-1', 'completed', 2),
      sequence: 2,
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        sourceTurnId: 'turn:facilitator',
        sourceLoopId: 'loop:facilitator-open',
        sourceEventType: 'tool_finished',
      },
    };
    projection.activitiesById['final-loop'] = {
      ...activity('final-loop', 'dispatch-1', 'completed', 5),
      sequence: 5,
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        sourceTurnId: 'turn:facilitator',
        sourceLoopId: 'loop:facilitator-final',
        sourceEventType: 'tool_finished',
      },
    };
    projection.messagesById['first-result'] = {
      id: 'first-result', roomId: 'room-1', turnId: 'root-1',
      participantId: 'participant-1', sourceSessionId: 'session-1',
      role: 'assistant', status: 'completed', text: '已完成分工',
      projectionKind: 'post', postKind: 'progress', rootId: 'root-1',
      dispatchId: 'dispatch-1', sourceTurnId: 'turn:facilitator',
      sourceLoopId: 'loop:facilitator-open',
      sequence: 3, createdAtMs: 3,
    };
    projection.messagesById['root-final'] = {
      id: 'root-final', roomId: 'room-1', turnId: 'root-1',
      participantId: 'participant-1', sourceSessionId: 'session-1',
      role: 'assistant', status: 'completed', text: 'Root 最终汇合',
      projectionKind: 'post', postKind: 'result', rootId: 'root-1',
      dispatchId: 'dispatch-1', sourceTurnId: 'turn:facilitator',
      sourceLoopId: 'loop:facilitator-final',
      sequence: 6, createdAtMs: 6,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes).toHaveLength(2);
    expect(selected.lanes.map((lane) => ({
      sourceTurnId: lane.sourceTurnId,
      sourceLoopId: lane.sourceLoopId,
      activities: lane.activities.map((item) => item.id),
      messages: lane.messageIds,
    }))).toEqual([
      {
        sourceTurnId: 'turn:facilitator',
        sourceLoopId: 'loop:facilitator-open',
        activities: ['first-loop'],
        messages: ['first-result'],
      },
      {
        sourceTurnId: 'turn:facilitator',
        sourceLoopId: 'loop:facilitator-final',
        activities: ['final-loop'],
        messages: ['root-final'],
      },
    ]);
  });

  it('hides superseded internal attempts once a later public step exists', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: ['alignment'],
      activityIds: ['failed-attempt', 'aligned-attempt', 'active-attempt'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-a', 'dispatch-b', 'dispatch-c'],
      dispatchParticipantIds: {
        'dispatch-a': 'participant-1',
        'dispatch-b': 'participant-1',
        'dispatch-c': 'participant-1',
      },
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    projection.activitiesById['failed-attempt'] = activity(
      'failed-attempt', 'dispatch-a', 'failed', 1,
    );
    projection.activitiesById['aligned-attempt'] = activity(
      'aligned-attempt', 'dispatch-b', 'completed', 2,
    );
    projection.activitiesById['active-attempt'] = activity(
      'active-attempt', 'dispatch-c', 'running', 4,
    );
    projection.messagesById.alignment = {
      id: 'alignment',
      roomId: 'room-1',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      role: 'assistant',
      status: 'completed',
      text: '需求已经对齐',
      projectionKind: 'post',
      postKind: 'alignment',
      rootId: 'root-1',
      dispatchId: 'dispatch-b',
      createdAtMs: 3,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes.map((lane) => lane.dispatchId)).toEqual([
      'dispatch-b',
      'dispatch-c',
    ]);
  });

  it('keeps a bounded Provider failure visible in its dispatch lane', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.activityOrder.push('provider-error');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: [],
      activityIds: ['provider-error'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.activitiesById['provider-error'] = {
      id: 'provider-error',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      kind: 'participant_activity',
      status: 'failed',
      summary: '模型响应中断，正在按运行策略处理',
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'message_completed',
        status: 'provider_error',
        isError: true,
      },
      createdAtMs: 2,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes).toHaveLength(1);
    expect(selected.lanes[0]).toMatchObject({
      dispatchId: 'dispatch-1',
      participantId: 'participant-1',
    });
    expect(selected.lanes[0].activities).toHaveLength(1);
    expect(selected.lanes[0].activities[0]).toMatchObject({
      status: 'failed',
      summary: '模型响应中断，正在按运行策略处理',
    });
  });

  it('keeps generic and plan-review waiting actions in their owning Session lane', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('root-1');
    projection.activityOrder.push('plan-review', 'select-input');
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: [],
      activityIds: ['plan-review', 'select-input'],
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1,
      updatedAtMs: 3,
    };
    projection.activitiesById['plan-review'] = {
      id: 'plan-review',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-owner',
      kind: 'participant_activity',
      status: 'waiting',
      summary: '等待计划审阅',
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        requestId: 'request-plan',
        requestKind: 'plan_review',
      },
      createdAtMs: 2,
    };
    projection.activitiesById['select-input'] = {
      id: 'select-input',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-owner',
      kind: 'participant_activity',
      status: 'waiting',
      summary: '选择部署环境',
      payload: {
        rootId: 'root-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'user_input_required',
        requestId: 'request-select',
        requestKind: 'user_input_required',
        method: 'select',
        options: ['预发布', '生产'],
      },
      createdAtMs: 3,
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.activities.map((activity) => activity.id)).toEqual([
      'plan-review',
      'select-input',
    ]);
    expect(selected.lanes).toHaveLength(1);
    expect(selected.lanes[0]).toMatchObject({
      dispatchId: 'dispatch-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-owner',
    });
  });
  it('keeps model arbitration in the Room lane without creating a Session review action', () => {
    const base = {
      id: 'approval-model-1',
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-owner',
      kind: 'participant_activity',
      status: 'waiting' as const,
      summary: 'Luna Max 正在评估',
      createdAtMs: 1,
      payload: {
        approvalId: 'approval-model-1',
        payloadSha256: 'd'.repeat(64),
        decisionMode: 'model',
        automatic: true,
        approvalModelDecision: {
          status: 'pending',
          model: 'openai-codex/gpt-5.6-luna',
        },
      },
    };

    expect(roomActivityNeedsSessionAction(base)).toBe(false);
    expect(roomActivityNeedsSessionAction({
      ...base,
      id: 'approval-human-1',
      payload: {
        approvalId: 'approval-human-1',
        payloadSha256: 'e'.repeat(64),
      },
    })).toBe(true);
  });
  it('keeps governed progress interleaved with read and write tools while filtering noise', () => {
    const projection = createRoomProjection('room-1');
    const activityIds = ['reasoning-1', 'read-1', 'internal-1', 'write-1', 'progress-1'];
    projection.turnOrder.push('root-1');
    projection.activityOrder.push(...activityIds);
    projection.turnsById['root-1'] = {
      id: 'root-1',
      rootId: 'root-1',
      status: 'running',
      messageIds: [],
      activityIds,
      participantIds: ['participant-1'],
      dispatchIds: ['dispatch-1'],
      dispatchParticipantIds: { 'dispatch-1': 'participant-1' },
      createdAtMs: 1,
      updatedAtMs: 5,
    };
    const base = {
      turnId: 'root-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      kind: 'participant_activity' as const,
      status: 'completed' as const,
      createdAtMs: 1,
    };
    projection.activitiesById['reasoning-1'] = {
      ...base,
      id: 'reasoning-1',
      status: 'running',
      summary: '先确认现有调用链，再修改入口',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'reasoning_summary' },
    };
    projection.activitiesById['read-1'] = {
      ...base,
      id: 'read-1',
      summary: '读取 src/runtime.ts',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'tool_finished', toolName: 'workspace_read' },
    };
    projection.activitiesById['internal-1'] = {
      ...base,
      id: 'internal-1',
      summary: '内部状态同步',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'message_completed' },
    };
    projection.activitiesById['write-1'] = {
      ...base,
      id: 'write-1',
      summary: '写入 src/runtime.ts',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'tool_finished', toolName: 'workspace_write' },
    };
    projection.activitiesById['progress-1'] = {
      ...base,
      id: 'progress-1',
      status: 'running',
      summary: '入口已修改，正在核对调用方',
      payload: { rootId: 'root-1', dispatchId: 'dispatch-1', sourceEventType: 'current_progress' },
    };

    const selected = selectRoomTurnExecution(projection, 'root-1');

    expect(selected.lanes).toHaveLength(1);
    expect(selected.lanes[0].activities.map((item) => item.id)).toEqual([
      'reasoning-1',
      'read-1',
      'write-1',
      'progress-1',
    ]);
  });


});

function activity(
  id: string,
  dispatchId: string,
  status: RoomActivityProjection['status'],
  createdAtMs: number,
): RoomActivityProjection {
  return {
    id,
    turnId: 'root-1',
    participantId: 'participant-1',
    sourceSessionId: 'session-1',
    kind: 'participant_activity',
    status,
    summary: id,
    payload: {
      rootId: 'root-1',
      dispatchId,
      sourceEventType: status === 'running' ? 'current_progress' : 'tool_finished',
    },
    createdAtMs,
  };
}
