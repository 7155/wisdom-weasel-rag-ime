import { describe, expect, it } from 'vitest';

import {
  appendOptimisticRoomMessage,
  createRoomProjection,
  parseRoomEventSnapshot,
  reduceRoomEvent,
  replayRoomEventSnapshot,
} from './room-reducer';
import { roomEventFixture as roomEvent } from '@/test/fixtures/events';

describe('RoomEventReducer', () => {
  it('projects participant deltas once and requests a snapshot on a gap', () => {
    const first = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_delta', { delta: '并' }),
    );
    const second = reduceRoomEvent(
      first.state,
      roomEvent(2, 'participant_delta', { delta: '行' }),
    );
    const duplicate = reduceRoomEvent(
      second.state,
      roomEvent(2, 'participant_delta', { delta: '行' }),
    );
    const gap = reduceRoomEvent(second.state, roomEvent(4, 'turn_completed', {}));

    expect(duplicate.disposition).toBe('ignored-duplicate');
    expect(second.state.messagesById['room-message-1'].text).toBe('并行');
    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.needsSnapshot).toBe(true);
  });

  it('keeps the user message and participant reply in one completed room turn', () => {
    const user = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'user_message', {
        messageId: 'room-user-1',
        text: '@智鼬·未来 请整理下一步',
      }),
    ).state;
    const reply = reduceRoomEvent(
      user,
      roomEvent(2, 'participant_delta', {
        messageId: 'room-assistant-1',
        delta: '已整理',
      }),
    ).state;
    const completed = reduceRoomEvent(
      reply,
      roomEvent(3, 'turn_completed', { status: 'completed' }),
    ).state;

    expect(completed.turnOrder).toEqual(['room-turn-1']);
    expect(completed.turnsById['room-turn-1']).toMatchObject({
      status: 'completed',
      messageIds: ['room-user-1', 'room-assistant-1'],
    });
    expect(completed.messagesById['room-assistant-1']).toMatchObject({
      role: 'assistant',
      status: 'completed',
      text: '已整理',
    });
  });

  it('merges optimistic room input by clientMessageId and keeps unknown events', () => {
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId: 'room-client-1',
      text: '@智鼬 检查状态',
      nowMs: 1,
    });
    const merged = reduceRoomEvent(
      optimistic,
      roomEvent(1, 'user_message', {
        messageId: 'room-user-1',
        clientMessageId: 'room-client-1',
        text: '@智鼬 检查状态',
      }),
    ).state;
    const unknown = reduceRoomEvent(
      merged,
      roomEvent(2, 'future_room_vote', { result: 'kept' }),
    ).state;

    expect(merged.messageOrder).toEqual(['room-user-1']);
    expect(unknown.diagnostics[0]).toMatchObject({ eventType: 'future_room_vote' });
  });

  it('unwraps the public data envelope used by real participant runtime events', () => {
    const delta = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_delta', {
        sourceEventId: 'agent-session:1',
        sourceEventType: 'text_delta',
        data: { messageId: 'real-message', delta: '真实对话' },
      }),
    ).state;
    const activity = reduceRoomEvent(
      delta,
      roomEvent(2, 'participant_activity', {
        sourceEventId: 'agent-session:2',
        sourceEventType: 'tool_finished',
        data: { status: 'completed', summary: '已整理相关资料' },
      }),
    ).state;

    expect(activity.messagesById['real-message'].text).toBe('真实对话');
    expect(activity.activitiesById['room-1:2:activity']).toMatchObject({
      summary: '已整理相关资料',
      status: 'completed',
    });
  });

  it('projects Room lifecycle events as completed instead of leaving a false running turn', () => {
    const created = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_status', { status: 'room_created' }),
    ).state;

    expect(created.activitiesById['room-1:1:activity'].status).toBe('completed');
    expect(created.turnsById['room-turn-1'].status).toBe('completed');
  });

  it('strictly validates and replays a retained event snapshot without looping on old gap markers', () => {
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId: 'room-client-1',
      text: '@智鼬 检查状态',
      nowMs: 1,
    });
    const snapshot = parseRoomEventSnapshot(roomSnapshotFixture([
      wireRoomEvent(5, 'user_message', {
        clientMessageId: 'room-client-1',
        text: '@智鼬 检查状态',
      }),
      wireRoomEvent(6, 'snapshot_required', { reason: 'old_replay_gap' }),
      wireRoomEvent(7, 'participant_delta', {
        messageId: 'room-message-1',
        delta: '已恢复',
      }),
    ], { firstSequence: 5, truncated: true }));

    const replayed = replayRoomEventSnapshot(optimistic, snapshot);

    expect(replayed.lastSequence).toBe(7);
    expect(replayed.resumeToken).toBe('room-1:7');
    expect(replayed.needsSnapshot).toBe(false);
    expect(replayed.messageOrder).not.toContain('local-room:room-client-1');
    expect(replayed.messageOrder).toContain('room-1:5:user');
    expect(replayed.messagesById['room-message-1'].text).toBe('已恢复');
    expect(replayed.diagnostics).toEqual([
      expect.objectContaining({ eventType: 'snapshot_required', sequence: 6 }),
    ]);
  });

  it('rejects extra snapshot fields and non-contiguous retained events', () => {
    expect(() => parseRoomEventSnapshot({ ...roomSnapshotFixture([]), arbitrary: true })).toThrow(
      /Invalid agent-room-snapshot.v1 payload/,
    );
    expect(() => parseRoomEventSnapshot(roomSnapshotFixture([
      wireRoomEvent(1, 'user_message', { text: 'one' }),
      wireRoomEvent(3, 'turn_completed', {}),
    ], { firstSequence: 1 }))).toThrow(/contiguous/);
  });
});

function wireRoomEvent(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return {
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `room-1:${sequence}`,
    roomId: 'room-1',
    sequence,
    turnId: 'room-turn-1',
    eventType,
    participantId: 'participant-1',
    sourceSessionId: 'session-room-1',
    createdAtMs: sequence * 10,
    payload,
    resumeToken: `room-1:${sequence}`,
  };
}

function roomSnapshotFixture(
  events: ReturnType<typeof wireRoomEvent>[],
  options: { firstSequence?: number; truncated?: boolean } = {},
) {
  const firstSequence = options.firstSequence ?? (events[0]?.sequence ?? 0);
  const lastSequence = events.at(-1)?.sequence ?? 0;
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1',
      id: 'room-1',
      title: '快照 Room',
      status: 'active',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-1',
      workspaceRoots: ['/Volumes/work/learnA'],
      createdAtMs: 1,
      updatedAtMs: 2,
      lastEventSequence: lastSequence,
      participants: [
        roomParticipant('participant-1', 'session-room-1', 0),
        roomParticipant('participant-2', 'session-room-2', 1),
      ],
    },
    events,
    firstSequence,
    lastSequence,
    resumeToken: lastSequence ? `room-1:${lastSequence}` : '',
    truncated: options.truncated ?? false,
  };
}

function roomParticipant(id: string, sessionId: string, ordinal: number) {
  return {
    schemaVersion: 'rag-ime.agent-participant.v1',
    id,
    roomId: 'room-1',
    sessionId,
    roleId: ordinal === 0 ? 'zhiyou-v1' : 'hermes-v1',
    roleVersion: '1',
    displayName: ordinal === 0 ? '智鼬·此刻' : '智鼬·初识',
    collaborationRole: ordinal === 0 ? 'coordinator' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
