import { describe, expect, it } from 'vitest';

import { createRoomProjection } from '@/contracts/room-reducer';

import {
  roomActivityNeedsSessionAction,
  selectPublicRoomTurnOrder,
  selectRoomTurnExecution,
} from './room-execution-lanes';

describe('selectRoomTurnExecution', () => {
  it('removes the unscoped lifecycle slot before timeline virtualization', () => {
    const projection = createRoomProjection('room-1');
    projection.turnOrder.push('unscoped', 'root-1');

    expect(selectPublicRoomTurnOrder(projection)).toEqual(['root-1']);
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

});
