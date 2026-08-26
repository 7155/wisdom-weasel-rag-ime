import { describe, expect, it } from 'vitest';

import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import type { RoomSummary } from './room-types';
import { roomPeerGraphLayout, roomPeerRelations, roomPeerRelationsFromProjection } from './RoomTaskGraph';

describe('RoomTaskGraph peer relations', () => {
  it('projects direct ask and reply edges between equal Room participants', () => {
    const room: RoomSummary = {
      id: 'room-peer',
      title: '平等协作',
      status: 'active',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-a',
      updatedAtMs: 1,
      participants: [
        { id: 'participant-a', sessionId: 'session-a', roleId: 'a', roleVersion: '1', displayName: '澄·远', status: 'active', ordinal: 0 },
        { id: 'participant-b', sessionId: 'session-b', roleId: 'b', roleVersion: '1', displayName: '澄·今', status: 'active', ordinal: 1 },
      ],
    };
    const activity = (
      id: string,
      kind: 'ask' | 'reply',
      sourceParticipantId: string,
      targetParticipantId: string,
      status: string,
    ): RoomActivityProjection => ({
      id,
      turnId: 'root-peer',
      participantId: sourceParticipantId,
      sourceSessionId: sourceParticipantId === 'participant-a' ? 'session-a' : 'session-b',
      kind: 'participant_activity',
      status: status === 'failed' ? 'failed' : 'completed',
      summary: kind,
      payload: {
        activityKind: 'intercom',
        phase: status,
        message: {
          id: 'message-' + id,
          kind,
          sourceParticipantId,
          targetParticipantId,
          status,
          content: kind === 'ask' ? '请直接核对边界' : '已核对，边界成立',
          replyTo: kind === 'reply' ? 'message-ask' : '',
        },
      },
      createdAtMs: 1,
    });

    const relations = roomPeerRelations([
      activity('ask', 'ask', 'participant-a', 'participant-b', 'delivered'),
      activity('reply', 'reply', 'participant-b', 'participant-a', 'delivered'),
    ], room);

    expect(relations).toMatchObject([
      {
        sourceName: 'Earth',
        targetName: 'Mars',
        kind: 'ask',
        state: 'complete',
      },
      {
        sourceName: 'Mars',
        targetName: 'Earth',
        kind: 'reply',
        state: 'complete',
        replyTo: 'message-ask',
      },
    ]);
  });

  it('keeps a failed peer message local to its edge', () => {
    const room: RoomSummary = {
      id: 'room-peer',
      title: '局部失败',
      status: 'active',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-a',
      updatedAtMs: 1,
      participants: [
        { id: 'participant-a', sessionId: 'session-a', roleId: 'a', roleVersion: '1', displayName: 'A', status: 'active', ordinal: 0 },
        { id: 'participant-b', sessionId: 'session-b', roleId: 'b', roleVersion: '1', displayName: 'B', status: 'active', ordinal: 1 },
      ],
    };
    const relation = roomPeerRelations([{
      id: 'failed-edge',
      turnId: 'root-peer',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      kind: 'participant_activity',
      status: 'failed',
      summary: 'delivery failed',
      payload: {
        activityKind: 'intercom',
        phase: 'failed',
        message: {
          id: 'message-failed',
          kind: 'send',
          sourceParticipantId: 'participant-a',
          targetParticipantId: 'participant-b',
          status: 'failed',
          content: '局部失败',
        },
      },
      createdAtMs: 1,
    }], room)[0];

    expect(relation.state).toBe('attention');
    expect(relation.sourceParticipantId).toBe('participant-a');
    expect(relation.targetParticipantId).toBe('participant-b');
  });

  it('reads peer edges across detached delivery Session turns', () => {
    const room: RoomSummary = {
      id: 'room-peer', title: '跨回合直连', status: 'active',
      routingPolicy: 'moderator', moderatorParticipantId: 'participant-a', updatedAtMs: 1,
      participants: [
        { id: 'participant-a', sessionId: 'session-a', roleId: 'a', roleVersion: '1', displayName: 'A', status: 'active', ordinal: 0 },
        { id: 'participant-b', sessionId: 'session-b', roleId: 'b', roleVersion: '1', displayName: 'B', status: 'active', ordinal: 1 },
      ],
    };
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('detached-reply');
    projection.activitiesById['detached-reply'] = {
      id: 'detached-reply', turnId: 'delivery-session-turn',
      participantId: 'participant-b', sourceSessionId: 'session-b',
      kind: 'participant_activity', status: 'completed', summary: '直接回复',
      payload: {
        activityKind: 'intercom', phase: 'delivered',
        message: {
          id: 'message-reply', kind: 'reply', status: 'delivered',
          sourceParticipantId: 'participant-b', targetParticipantId: 'participant-a',
          content: 'DIRECT_REPLY', replyTo: 'message-ask',
        },
      },
      createdAtMs: 2,
    };

    expect(roomPeerRelationsFromProjection(projection, room)).toEqual([
      expect.objectContaining({
        id: 'message-reply', sourceName: 'Mars', targetName: 'Earth',
        kind: 'reply', state: 'complete', content: 'DIRECT_REPLY',
      }),
    ]);
  });

  it('lays out curved edges from source node boundaries to target node boundaries', () => {
    const relations = [
      { id: 'ask', sourceParticipantId: 'a', sourceName: 'A', targetParticipantId: 'b', targetName: 'B', kind: 'ask' as const, state: 'complete' as const, content: 'ask', replyTo: '' },
      { id: 'reply', sourceParticipantId: 'b', sourceName: 'B', targetParticipantId: 'a', targetName: 'A', kind: 'reply' as const, state: 'complete' as const, content: 'reply', replyTo: 'ask' },
    ];

    const layout = roomPeerGraphLayout(['a', 'b'], relations);

    expect(layout.nodes).toHaveLength(2);
    expect(layout.edges).toHaveLength(2);
    expect(layout.edges[0]?.path).toMatch(/^M \d+\.\d \d+\.\d Q /);
    expect(layout.edges[0]?.path).not.toBe(layout.edges[1]?.path);
    expect(layout.edges[0]?.labelY).not.toBe(layout.edges[1]?.labelY);
    expect(layout.edges.every((edge) => edge.labelX > 120 && edge.labelX < layout.width - 120)).toBe(true);
  });
});
