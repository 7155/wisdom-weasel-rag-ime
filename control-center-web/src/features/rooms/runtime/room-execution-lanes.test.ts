import { describe, expect, it } from 'vitest';

import { createRoomProjection } from '@/contracts/room-reducer';

import {
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
});
