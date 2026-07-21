import { describe, expect, it } from 'vitest';

import {
  appendOptimisticRoomMessage,
  createRoomProjection,
  parseRoomEventSnapshot,
  reduceRoomEvent,
  replayRoomEventSnapshot,
  roomActivityLaneIdentity,
} from './room-reducer';
import { parseRoomEvent } from './validators';
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

  it('replaces a provisional streaming reply when the final event has a real message id', () => {
    const streaming = reduceRoomEvent(
      createRoomProjection('room-1'),
      parseRoomEvent({
        ...wireRoomEvent(1, 'participant_delta', { delta: '先流式' }),
      }),
    ).state;
    const completed = reduceRoomEvent(
      streaming,
      parseRoomEvent({
        ...wireRoomEvent(2, 'participant_message', {
          message: roomServerMessage('room-final-1', '最终回复'),
        }),
      }),
    ).state;

    expect(completed.messageOrder).toEqual(['room-final-1']);
    expect(completed.turnsById['room-turn-1'].messageIds).toEqual(['room-final-1']);
    expect(completed.messagesById['room-final-1']).toMatchObject({
      status: 'completed',
      text: '最终回复',
    });
    expect(
      completed.messagesById['room-turn-1:participant-1:assistant'],
    ).toBeUndefined();
  });

  it('replaces only the matching execution lane when an authorized RoomPost is published', () => {
    const streaming = reduceRoomEvent(
      createRoomProjection('room-1'),
      parseRoomEvent(wireRoomEvent(1, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'draft-1',
        delta: '尚未发布的草稿',
      })),
    ).state;
    const published = reduceRoomEvent(
      streaming,
      parseRoomEvent(wireRoomEvent(2, 'room_post', {
        post: roomPost('post-1', '正式交付', 'dispatch-1'),
      })),
    ).state;

    expect(published.messageOrder).toEqual(['post-1']);
    expect(Object.values(published.messagesById)).toHaveLength(1);
    expect(published.messagesById['post-1']).toMatchObject({
      projectionKind: 'post',
      dispatchId: 'dispatch-1',
      text: '正式交付',
      status: 'completed',
    });
    expect(published.turnsById['room-turn-1'].messageIds).toEqual(['post-1']);
  });

  it('keeps two concurrent dispatches from the same Agent in separate execution lanes', () => {
    const routeOne = roomEvent(1, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      targetParticipantId: 'participant-1',
    });
    const routeTwo = roomEvent(2, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
      targetParticipantId: 'participant-1',
    });
    const firstDelta = roomEvent(3, 'participant_delta', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      messageId: 'shared-provider-message',
      delta: '第一条任务',
    });
    const secondDelta = roomEvent(4, 'participant_delta', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
      messageId: 'shared-provider-message',
      delta: '第二条任务',
    });
    const firstDone = roomEvent(5, 'turn_completed', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
    });
    const secondDone = roomEvent(6, 'turn_completed', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
    });

    let state = createRoomProjection('room-1');
    for (const event of [routeOne, routeTwo, firstDelta, secondDelta]) {
      state = reduceRoomEvent(state, event).state;
    }

    const messages = state.messageOrder.map((id) => state.messagesById[id]);
    expect(messages).toHaveLength(2);
    expect(messages.map((message) => message.dispatchId)).toEqual([
      'dispatch-1',
      'dispatch-2',
    ]);
    expect(messages.map((message) => message.text)).toEqual([
      '第一条任务',
      '第二条任务',
    ]);

    state = reduceRoomEvent(state, firstDone).state;
    expect(state.turnsById['room-turn-1'].status).toBe('running');
    expect(state.turnsById['room-turn-1'].terminalDispatchIds).toEqual(['dispatch-1']);
    state = reduceRoomEvent(state, secondDone).state;
    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'completed',
      dispatchIds: ['dispatch-1', 'dispatch-2'],
      terminalDispatchIds: ['dispatch-1', 'dispatch-2'],
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

  it('shows an optimistic turn as queued before the router accepts it', () => {
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId: 'room-client-pending',
      text: '立即显示发送状态',
      nowMs: 12,
    });

    expect(optimistic.turnsById['local-room-turn:room-client-pending']).toMatchObject({
      status: 'queued',
      createdAtMs: 12,
    });
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

  it('keeps one live tool activity from start through its final public summary', () => {
    const started = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        sourceEventId: 'agent-session:tool:1',
        sourceEventType: 'tool_started',
        data: {
          toolCallId: 'tool-call-1',
          toolName: 'ime_memory',
        },
      }),
    ).state;
    const finished = reduceRoomEvent(
      started,
      roomEvent(2, 'participant_activity', {
        sourceEventId: 'agent-session:tool:2',
        sourceEventType: 'tool_finished',
        data: {
          toolCallId: 'tool-call-1',
          toolName: 'ime_memory',
          summary: '找到了两条可用历史输入',
          isError: false,
        },
      }),
    ).state;

    const activityId = 'room-turn-1:participant-1:session-room-1:tool-call-1';
    expect(started.activitiesById[activityId]).toMatchObject({
      status: 'running',
      summary: 'ime_memory',
      createdAtMs: 10,
      payload: { sourceEventType: 'tool_started' },
    });
    expect(finished.activityOrder).toEqual([activityId]);
    expect(finished.turnsById['room-turn-1'].activityIds).toEqual([activityId]);
    expect(finished.activitiesById[activityId]).toMatchObject({
      status: 'completed',
      summary: '找到了两条可用历史输入',
      createdAtMs: 10,
      updatedAtMs: 20,
      payload: { sourceEventType: 'tool_finished' },
    });
  });

  it('isolates parallel activities by root, participant, and dispatch', () => {
    const first = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        dispatchId: 'dispatch-a',
        rootId: 'root-a',
        toolCallId: 'call-1',
        sourceEventType: 'tool_started',
        toolName: 'ime_memory',
      }),
    ).state;
    const secondEvent = roomEvent(2, 'participant_activity', {
      dispatchId: 'dispatch-b',
      rootId: 'root-a',
      toolCallId: 'call-1',
      sourceEventType: 'tool_started',
      toolName: 'ime_memory',
    });
    secondEvent.participantId = 'participant-2';
    secondEvent.sourceSessionId = 'session-room-2';
    const second = reduceRoomEvent(first, secondEvent).state;
    const activities = second.activityOrder.map((id) => second.activitiesById[id]);

    expect(second.activityOrder).toHaveLength(2);
    expect(activities.map(roomActivityLaneIdentity).map((identity) => identity.key)).toEqual([
      'root-a\u001fparticipant-1\u001fdispatch-a',
      'root-a\u001fparticipant-2\u001fdispatch-b',
    ]);
  });

  it('waits for every routed Agent before closing a multi-Agent root', () => {
    const routeOne = roomEvent(1, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      targetParticipantId: 'participant-1',
    });
    const routeTwo = roomEvent(2, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
      targetParticipantId: 'participant-2',
    });
    routeTwo.participantId = 'participant-2';
    routeTwo.sourceSessionId = 'session-room-2';
    const firstDone = roomEvent(3, 'turn_completed', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
    });
    const secondFailed = roomEvent(4, 'turn_failed', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
      error: '证据源暂时不可用',
    });
    secondFailed.participantId = 'participant-2';
    secondFailed.sourceSessionId = 'session-room-2';

    const routedOne = reduceRoomEvent(createRoomProjection('room-1'), routeOne).state;
    const routedBoth = reduceRoomEvent(routedOne, routeTwo).state;
    const oneTerminal = reduceRoomEvent(routedBoth, firstDone).state;
    const allTerminal = reduceRoomEvent(oneTerminal, secondFailed).state;

    expect(oneTerminal.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      participantIds: ['participant-1', 'participant-2'],
      terminalParticipantIds: ['participant-1'],
    });
    expect(allTerminal.turnsById['room-turn-1']).toMatchObject({
      status: 'failed',
      terminalParticipantIds: ['participant-1', 'participant-2'],
      failedParticipantIds: ['participant-2'],
    });
  });

  it('closes a root as aborted and never lets a late completed event resurrect it', () => {
    const routeOne = roomEvent(1, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      targetParticipantId: 'participant-1',
    });
    const routeTwo = roomEvent(2, 'route_decision', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
      targetParticipantId: 'participant-2',
    });
    routeTwo.participantId = 'participant-2';
    routeTwo.sourceSessionId = 'session-room-2';
    const firstAborted = roomEvent(3, 'turn_completed', {
      status: 'aborted',
      aborted: true,
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
    });
    const secondAborted = roomEvent(4, 'turn_completed', {
      status: 'aborted',
      aborted: true,
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-2',
    });
    secondAborted.participantId = 'participant-2';
    secondAborted.sourceSessionId = 'session-room-2';
    const lateCompleted = roomEvent(5, 'turn_completed', {
      status: 'completed',
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
    });

    const routedOne = reduceRoomEvent(createRoomProjection('room-1'), routeOne).state;
    const routedBoth = reduceRoomEvent(routedOne, routeTwo).state;
    const oneStopped = reduceRoomEvent(routedBoth, firstAborted).state;
    const allStopped = reduceRoomEvent(oneStopped, secondAborted).state;
    const afterLate = reduceRoomEvent(allStopped, lateCompleted).state;

    expect(oneStopped.turnsById['room-turn-1'].status).toBe('running');
    expect(allStopped.turnsById['room-turn-1']).toMatchObject({
      status: 'aborted',
      terminalParticipantIds: ['participant-1', 'participant-2'],
      abortedParticipantIds: ['participant-1', 'participant-2'],
    });
    expect(afterLate.turnsById['room-turn-1']).toMatchObject({
      status: 'aborted',
      abortedParticipantIds: ['participant-1', 'participant-2'],
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

function roomServerMessage(id: string, text: string) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId: 'session-room-1',
    turnId: 'room-turn-1',
    role: 'assistant',
    status: 'completed',
    blocks: [
      {
        id: `${id}:text`,
        type: 'text',
        status: 'completed',
        presentationKind: 'markdown',
        data: { text },
      },
    ],
    attachments: [],
    citations: [],
    createdAtMs: 10,
    completedAtMs: 20,
  };
}

function roomPost(postId: string, content: string, dispatchId: string) {
  return {
    schemaVersion: 'wisdom-weasel.room-post.v2',
    postId,
    roomId: 'room-1',
    rootId: 'room-turn-1',
    generation: 0,
    dispatchId,
    authorActorRef: 'participant-1',
    kind: 'result',
    visibility: 'room',
    content,
    idempotencyKey: postId,
    publicationSource: { kind: 'room_commit', ref: `commit:${postId}` },
    createdAtMs: 20,
  };
}

function roomParticipant(id: string, sessionId: string, ordinal: number) {
  return {
    schemaVersion: 'rag-ime.agent-participant.v1',
    id,
    roomId: 'room-1',
    sessionId,
    roleId: ordinal === 0 ? 'companion-present-v1' : 'companion-firstlight-v1',
    roleVersion: '1',
    displayName: ordinal === 0 ? '智鼬·此刻' : '智鼬·初识',
    collaborationRole: ordinal === 0 ? 'coordinator' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
