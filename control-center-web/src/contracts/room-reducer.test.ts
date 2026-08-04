import { describe, expect, it } from 'vitest';

import {
  abortRoomTurn,
  appendOptimisticRoomMessage,
  createRoomProjection,
  parseRoomEventPage,
  parseRoomEventSnapshot,
  reduceRoomEvent,
  reduceRoomEvents,
  replayRoomEventSnapshot,
  roomActivityLaneIdentity,
  selectRoomParticipantPublicProgress,
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

  it('coalesces participant deltas while preserving the final Room cursor', () => {
    const events = Array.from({ length: 200 }, (_, index) => roomEvent(
      index + 1,
      'participant_delta',
      {
        delta: String.fromCharCode(97 + (index % 26)),
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        contentIndex: 0,
      },
    ));
    const state = reduceRoomEvents(createRoomProjection('room-1'), events);

    expect(state.messagesById[
      'room-execution\u001froom-turn-1\u001fparticipant-1\u001fdispatch-1\u001froom-message-1'
    ].text).toBe(events.map((event) => String(event.payload.delta)).join(''));
    expect(state.lastSequence).toBe(200);
    expect(state.lastEventId).toBe('room-1:200');
    expect(state.resumeToken).toBe('room-1:200');
  });

  it('replaces provisional participant content without breaking append or final coalescing', () => {
    const deltas = [
      roomEvent(1, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '过时前缀',
      }),
      roomEvent(2, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '仍会追加',
      }),
      roomEvent(3, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '块替换',
        replaceBlock: true,
      }),
      roomEvent(4, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '后续追加',
      }),
      roomEvent(5, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '内容替换',
        replaceContent: true,
      }),
      roomEvent(6, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        contentIndex: 0,
        delta: '最终追加',
      }),
    ];
    const executionId = [
      'room-execution',
      'room-turn-1',
      'participant-1',
      'dispatch-1',
      'provider-stream-1',
    ].join('\u001f');

    const appended = reduceRoomEvents(createRoomProjection('room-1'), deltas.slice(0, 2));
    expect(appended.messagesById[executionId].text).toBe('过时前缀仍会追加');

    const blockReplaced = reduceRoomEvents(createRoomProjection('room-1'), deltas.slice(0, 4));
    expect(blockReplaced.messagesById[executionId].text).toBe('块替换后续追加');

    const contentReplaced = reduceRoomEvents(createRoomProjection('room-1'), deltas);
    expect(contentReplaced.messagesById[executionId].text).toBe('内容替换最终追加');

    const completed = reduceRoomEvent(
      contentReplaced,
      parseRoomEvent(wireRoomEvent(7, 'participant_message', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        message: roomServerMessage('room-final-1', '最终公开回复'),
      })),
    ).state;
    expect(completed.messageOrder).toEqual(['room-final-1']);
    expect(completed.turnsById['room-turn-1'].messageIds).toEqual(['room-final-1']);
    expect(completed.messagesById[executionId]).toBeUndefined();
    expect(completed.messagesById['room-final-1'].text).toBe('最终公开回复');
  });

  it('keeps completed Room turns referentially stable while another lane streams', () => {
    const user = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'user_message', { messageId: 'stable-user', text: '旧任务' }),
    ).state;
    const completedEvent = roomEvent(2, 'turn_completed', { status: 'completed' });
    completedEvent.participantId = null;
    completedEvent.sourceSessionId = '';
    const completed = reduceRoomEvent(user, completedEvent).state;
    const stableTurn = completed.turnsById['room-turn-1'];
    const stableMessage = completed.messagesById['stable-user'];
    const nextTurnEvent = {
      ...roomEvent(3, 'participant_delta', {
        messageId: 'next-reply',
        delta: '新任务流式内容',
      }),
      turnId: 'room-turn-2',
    };
    const streamed = reduceRoomEvent(completed, nextTurnEvent).state;

    expect(streamed.turnsById['room-turn-1']).toBe(stableTurn);
    expect(streamed.messagesById['stable-user']).toBe(stableMessage);
    expect(streamed.turnsById['room-turn-2']).toBeDefined();
    expect(completed.turnsById['room-turn-2']).toBeUndefined();
  });

  it('keeps the user message and participant reply in one completed room turn', () => {
    const user = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'user_message', {
        messageId: 'room-user-1',
        text: '@澄·远 请整理下一步',
      }),
    ).state;
    const reply = reduceRoomEvent(
      user,
      roomEvent(2, 'participant_delta', {
        messageId: 'room-assistant-1',
        delta: '已整理',
      }),
    ).state;
    const rootCompleted = roomEvent(3, 'turn_completed', { status: 'completed' });
    rootCompleted.participantId = null;
    rootCompleted.sourceSessionId = '';
    const completed = reduceRoomEvent(reply, rootCompleted).state;

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

  it('coalesces live delta aliases and reconnect replay into one final assistant message', () => {
    const events = [
      wireRoomEvent(1, 'participant_delta', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        messageId: 'provider-stream-1',
        blockId: 'room-final-1:text',
        delta: '流式草稿不应重复',
      }),
      wireRoomEvent(2, 'participant_message', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        message: roomServerMessage('room-final-1', '最终公开回复'),
      }),
      wireRoomEvent(3, 'participant_message', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        message: roomServerMessage('room-final-1', '最终公开回复'),
      }),
    ];
    const live = reduceRoomEvents(
      createRoomProjection('room-1'),
      events.map((event) => parseRoomEvent(event)),
    );
    const replayed = replayRoomEventSnapshot(
      createRoomProjection('room-1'),
      parseRoomEventSnapshot(roomSnapshotFixture(events)),
    );

    for (const projection of [live, replayed]) {
      expect(projection.messageOrder).toEqual(['room-final-1']);
      expect(projection.turnsById['room-turn-1'].messageIds).toEqual(['room-final-1']);
      expect(Object.values(projection.messagesById)).toHaveLength(1);
      expect(projection.messagesById['room-final-1']).toMatchObject({
        projectionKind: 'post',
        status: 'completed',
        text: '最终公开回复',
      });
    }
  });

  it('keeps different source events when their assistant text happens to match', () => {
    const events = [
      wireRoomEvent(1, 'participant_message', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        message: roomServerMessage('provider-reply-1', '相同的最终回复'),
      }),
      wireRoomEvent(2, 'room_post', {
        post: roomPost('post-1', '相同的最终回复', 'dispatch-1'),
      }),
      wireRoomEvent(3, 'participant_message', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        message: roomServerMessage('provider-reply-late', '相同的最终回复'),
      }),
    ];
    const projection = reduceRoomEvents(
      createRoomProjection('room-1'),
      events.map((event) => parseRoomEvent(event)),
    );

    expect(projection.messageOrder).toEqual([
      'provider-reply-1',
      'post-1',
      'provider-reply-late',
    ]);
    expect(projection.turnsById['room-turn-1'].messageIds).toEqual([
      'provider-reply-1',
      'post-1',
      'provider-reply-late',
    ]);
    expect(Object.values(projection.messagesById)).toHaveLength(3);
    expect(projection.messagesById['post-1']).toMatchObject({
      postKind: 'result',
      text: '相同的最终回复',
    });
  });

  it('coalesces runtime and RoomPost aliases only when they share publication identity', () => {
    const events = [
      wireRoomEvent(1, 'participant_message', {
        rootId: 'room-turn-1',
        sourceEventId: 'publication:reply-1',
        message: roomServerMessage('provider-reply-1', '流式完成稿'),
      }),
      wireRoomEvent(2, 'room_post', {
        post: {
          ...roomPost('post-1', '正式公开回复', ''),
          chronology: {
            schemaVersion: 'wisdom-weasel.room-post-chronology.v1',
            roomEventId: 'publication:reply-1',
            roomEventSequence: 1,
            createdAtMs: 10,
            afterPostId: null,
            orderKey: 'room-event:00000000000000000001',
          },
        },
      }),
      wireRoomEvent(3, 'participant_message', {
        rootId: 'room-turn-1',
        sourceEventId: 'publication:reply-1',
        message: roomServerMessage('provider-reply-late', '重复回放的运行稿'),
      }),
    ];
    const projection = reduceRoomEvents(
      createRoomProjection('room-1'),
      events.map((event) => parseRoomEvent(event)),
    );

    expect(projection.messageOrder).toEqual(['post-1']);
    expect(projection.turnsById['room-turn-1'].messageIds).toEqual(['post-1']);
    expect(Object.values(projection.messagesById)).toHaveLength(1);
    expect(projection.messagesById['post-1']).toMatchObject({
      sourceEventId: 'publication:reply-1',
      sequence: 1,
      createdAtMs: 10,
      postKind: 'result',
      text: '正式公开回复',
      chronology: {
        roomEventId: 'publication:reply-1',
        roomEventSequence: 1,
        orderKey: 'room-event:00000000000000000001',
      },
    });
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
      postKind: 'result',
      dispatchId: 'dispatch-1',
      text: '正式交付',
      status: 'completed',
    });
    expect(published.turnsById['room-turn-1'].messageIds).toEqual(['post-1']);
    expect(published.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      terminalDispatchIds: ['dispatch-1'],
      terminalParticipantIds: ['participant-1'],
    });
  });

  it('settles published lanes without unlocking the Root before its terminal event', () => {
    const events = [
      roomEvent(1, 'route_decision', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        targetParticipantId: 'participant-1',
      }),
      roomEvent(2, 'route_decision', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-2',
        targetParticipantId: 'participant-1',
      }),
      roomEvent(3, 'room_post', {
        post: roomPost('post-1', '第一份交付', 'dispatch-1'),
      }),
      roomEvent(4, 'room_post', {
        post: roomPost('post-2', '第二份交付', 'dispatch-2'),
      }),
    ];
    let state = createRoomProjection('room-1');
    for (const event of events) state = reduceRoomEvent(state, event).state;

    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      dispatchIds: ['dispatch-1', 'dispatch-2'],
      terminalDispatchIds: ['dispatch-1', 'dispatch-2'],
      terminalParticipantIds: ['participant-1'],
    });

    state = reduceRoomEvent(state, parseRoomEvent({
      ...wireRoomEvent(5, 'turn_completed', { status: 'completed' }),
      participantId: null,
      sourceSessionId: '',
    })).state;

    expect(state.turnsById['room-turn-1'].status).toBe('completed');
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
      status: 'running',
      dispatchIds: ['dispatch-1', 'dispatch-2'],
      terminalDispatchIds: ['dispatch-1', 'dispatch-2'],
    });
    state = reduceRoomEvent(state, parseRoomEvent({
      ...wireRoomEvent(7, 'turn_completed', { status: 'completed' }),
      participantId: null,
      sourceSessionId: '',
    })).state;
    expect(state.turnsById['room-turn-1'].status).toBe('completed');
  });

  it('keeps a scheduled retry lane nonterminal and accepts its later completion', () => {
    const retryWaiting = roomEvent(1, 'participant_activity', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      sourceEventId: 'agent-session:failed-attempt',
      sourceEventType: 'turn_failed',
      status: 'retry_wait',
      retryAttempt: 2,
      summary: '模型连接中断，已进入有界重试等待',
    });
    const completed = roomEvent(2, 'turn_completed', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      status: 'completed',
    });

    let state = reduceRoomEvent(createRoomProjection('room-1'), retryWaiting).state;
    expect(state.activitiesById[state.activityOrder[0]!]).toMatchObject({
      status: 'waiting',
      payload: {
        sourceEventType: 'turn_failed',
        status: 'retry_wait',
        retryAttempt: 2,
      },
    });
    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      dispatchIds: ['dispatch-1'],
      terminalDispatchIds: [],
      failedDispatchIds: [],
      terminalParticipantIds: [],
      failedParticipantIds: [],
    });

    state = reduceRoomEvent(state, completed).state;
    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      terminalDispatchIds: ['dispatch-1'],
      failedDispatchIds: [],
      terminalParticipantIds: ['participant-1'],
      failedParticipantIds: [],
    });
  });

  it('merges optimistic room input by clientMessageId and keeps unknown events', () => {
    const optimistic = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId: 'room-client-1',
      text: '@澄 检查状态',
      nowMs: 1,
    });
    const merged = reduceRoomEvent(
      optimistic,
      roomEvent(1, 'user_message', {
        messageId: 'room-user-1',
        clientMessageId: 'room-client-1',
        text: '@澄 检查状态',
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

  it('reduces started, progress, and finished for one tool call to one terminal activity', () => {
    const started = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        rootId: 'root-tool-1',
        dispatchId: 'dispatch-tool-1',
        sourceEventType: 'tool_started',
        toolCallId: 'tool-call-1',
        toolName: 'memory',
        arguments: {
          path: '…/project/rag_ime',
          pattern: 'room_event_projection',
          limit: 40,
        },
      }),
    ).state;
    const progressed = reduceRoomEvent(
      started,
      roomEvent(2, 'participant_activity', {
        rootId: 'root-tool-1',
        dispatchId: 'dispatch-tool-1',
        sourceEventType: 'tool_progress',
        toolCallId: 'tool-call-1',
        toolName: 'memory',
        summary: '正在筛选公开记录',
      }),
    ).state;
    const finished = reduceRoomEvent(
      progressed,
      roomEvent(3, 'participant_activity', {
        rootId: 'root-tool-1',
        dispatchId: 'dispatch-tool-1',
        sourceEventType: 'tool_finished',
        toolCallId: 'tool-call-1',
        toolName: 'memory',
        summary: '找到了两条可用历史输入',
        isError: false,
        result: {
          outputPreview: 'agent_event_projection.py:350:def room_event_projection',
          outputTruncated: false,
        },
      }),
    ).state;
    const staleProgress = reduceRoomEvent(
      finished,
      roomEvent(4, 'participant_activity', {
        rootId: 'root-tool-1',
        dispatchId: 'dispatch-tool-1',
        sourceEventType: 'tool_progress',
        toolCallId: 'tool-call-1',
        toolName: 'memory',
        summary: '迟到的处理中状态',
      }),
    ).state;

    const activityId = 'root-tool-1:participant-1:dispatch-tool-1:tool-call-1';
    expect(started.activitiesById[activityId]).toMatchObject({
      status: 'running',
      summary: 'memory',
      createdAtMs: 10,
      payload: {
        sourceEventType: 'tool_started',
        arguments: { pattern: 'room_event_projection' },
      },
    });
    expect(progressed.activityOrder).toEqual([activityId]);
    expect(progressed.activitiesById[activityId]).toMatchObject({
      status: 'running',
      summary: '正在筛选公开记录',
    });
    expect(finished.activityOrder).toEqual([activityId]);
    expect(finished.turnsById['room-turn-1'].activityIds).toEqual([activityId]);
    expect(finished.activitiesById[activityId]).toMatchObject({
      status: 'completed',
      summary: '找到了两条可用历史输入',
      createdAtMs: 10,
      updatedAtMs: 30,
      payload: {
        sourceEventType: 'tool_finished',
        arguments: { pattern: 'room_event_projection' },
        result: { outputPreview: 'agent_event_projection.py:350:def room_event_projection' },
      },
    });
    expect(finished.activitiesById[activityId].payload.progressHistory).toHaveLength(3);
    expect(staleProgress.activitiesById[activityId]).toEqual(finished.activitiesById[activityId]);
  });

  it('drops a stale preparatory summary when tool_finished has no terminal summary', () => {
    const started = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        rootId: 'root-room-state',
        dispatchId: 'dispatch-room-state',
        sourceEventType: 'tool_started',
        toolCallId: 'room-state-call',
        toolName: 'room_state',
        summary: '准备查看协作状态',
        status: 'running',
      }),
    ).state;
    const finished = reduceRoomEvent(
      started,
      roomEvent(2, 'participant_activity', {
        rootId: 'root-room-state',
        dispatchId: 'dispatch-room-state',
        sourceEventType: 'tool_finished',
        toolCallId: 'room-state-call',
        toolName: 'room_state',
        result: {
          unchanged: true,
          stateRevision: 12,
        },
      }),
    ).state;
    const activity = finished.activitiesById[
      'root-room-state:participant-1:dispatch-room-state:room-state-call'
    ];

    expect(activity).toMatchObject({
      status: 'completed',
      summary: 'room_state',
      payload: {
        sourceEventType: 'tool_finished',
        result: { unchanged: true, stateRevision: 12 },
      },
    });
    expect(activity.payload).not.toHaveProperty('summary');
    expect(activity.payload).not.toHaveProperty('status');
  });

  it('projects tool lifecycle identically from live SSE and HTTP snapshot replay', () => {
    const events = [
      wireRoomEvent(1, 'participant_activity', {
        rootId: 'root-replay',
        dispatchId: 'dispatch-replay',
        sourceEventType: 'tool_started',
        toolCallId: 'call-replay',
        toolName: 'read',
        arguments: { path: '…/project/src/runtime.ts' },
      }),
      wireRoomEvent(2, 'participant_activity', {
        rootId: 'root-replay',
        dispatchId: 'dispatch-replay',
        sourceEventType: 'tool_progress',
        toolCallId: 'call-replay',
        toolName: 'read',
        summary: '正在读取公开片段',
      }),
      wireRoomEvent(3, 'participant_activity', {
        rootId: 'root-replay',
        dispatchId: 'dispatch-replay',
        sourceEventType: 'tool_finished',
        toolCallId: 'call-replay',
        toolName: 'read',
        summary: '公开片段已返回',
        result: { outputPreview: 'export const roomReady = true;' },
      }),
    ];
    const live = reduceRoomEvents(
      createRoomProjection('room-1'),
      events.map((event) => parseRoomEvent(event)),
    );
    const replayed = replayRoomEventSnapshot(
      createRoomProjection('room-1'),
      parseRoomEventSnapshot(roomSnapshotFixture(events)),
    );
    const activityId = 'root-replay:participant-1:dispatch-replay:call-replay';

    expect(replayed.activityOrder).toEqual(live.activityOrder);
    expect(replayed.turnsById['room-turn-1'].activityIds).toEqual(
      live.turnsById['room-turn-1'].activityIds,
    );
    expect(replayed.activitiesById[activityId]).toEqual(live.activitiesById[activityId]);
    expect(replayed.activitiesById[activityId]).toMatchObject({
      status: 'completed',
      payload: {
        sourceEventType: 'tool_finished',
        result: { outputPreview: 'export const roomReady = true;' },
      },
    });
  });

  it('keeps separate calls to the same tool as separate activities', () => {
    const projection = reduceRoomEvents(createRoomProjection('room-1'), [
      roomEvent(1, 'participant_activity', {
        rootId: 'root-same-tool',
        dispatchId: 'dispatch-same-tool',
        sourceEventType: 'tool_finished',
        toolCallId: 'read-call-1',
        toolName: 'read',
        result: { outputPreview: 'first' },
      }),
      roomEvent(2, 'participant_activity', {
        rootId: 'root-same-tool',
        dispatchId: 'dispatch-same-tool',
        sourceEventType: 'tool_finished',
        toolCallId: 'read-call-2',
        toolName: 'read',
        result: { outputPreview: 'second' },
      }),
    ]);

    expect(projection.activityOrder).toEqual([
      'root-same-tool:participant-1:dispatch-same-tool:read-call-1',
      'root-same-tool:participant-1:dispatch-same-tool:read-call-2',
    ]);
    expect(Object.values(projection.activitiesById)).toHaveLength(2);
  });

  it('coalesces reasoning and current-progress updates into one card per lane', () => {
    const projection = reduceRoomEvents(createRoomProjection('room-1'), [
      roomEvent(1, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'reasoning_summary',
        state: 'running',
        summary: '正在检查边界',
      }),
      roomEvent(2, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'reasoning_summary',
        state: 'completed',
        summary: '边界检查完成',
      }),
      roomEvent(3, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'current_progress',
        summary: '正在整理结果',
      }),
      roomEvent(4, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventType: 'current_progress',
        summary: '正在等待审阅',
      }),
    ]);

    expect(projection.activityOrder).toHaveLength(2);
    expect(Object.values(projection.activitiesById).map((activity) => activity.summary)).toEqual([
      '边界检查完成',
      '正在等待审阅',
    ]);
  });

  it('selects one latest public summary per participant across live events and snapshot hydration', () => {
    const events = [
      wireRoomEvent(1, 'participant_activity', {
        rootId: 'root-public',
        dispatchId: 'dispatch-research',
        participantId: 'participant-research',
        sourceSessionId: 'session-research',
        sourceEventType: 'reasoning_summary',
        state: 'running',
        summary: '正在核对安装栈恢复边界',
      }),
      wireRoomEvent(2, 'participant_activity', {
        rootId: 'root-public',
        dispatchId: 'dispatch-review',
        participantId: 'participant-review',
        sourceSessionId: 'session-review',
        sourceEventType: 'tool_progress',
        toolCallId: 'review-call',
        toolName: 'read',
        summary: '正在检查公开回执',
      }),
      wireRoomEvent(3, 'participant_activity', {
        rootId: 'root-public',
        dispatchId: 'dispatch-research',
        participantId: 'participant-research',
        sourceSessionId: 'session-research',
        sourceEventType: 'reasoning_summary',
        state: 'completed',
        summary: '恢复边界已经确认',
      }),
      wireRoomEvent(4, 'participant_activity', {
        rootId: 'root-public',
        dispatchId: 'dispatch-research',
        participantId: 'participant-research',
        sourceSessionId: 'session-research-next',
        sourceEventType: 'reasoning_summary',
        state: 'running',
        summary: '正在准备共同复核',
      }),
    ];
    const live = reduceRoomEvents(
      createRoomProjection('room-1'),
      events.map((event) => parseRoomEvent(event)),
    );
    const snapshot = parseRoomEventSnapshot(roomSnapshotFixture(events));
    const hydrated = replayRoomEventSnapshot(createRoomProjection('room-1'), snapshot);
    const rehydrated = replayRoomEventSnapshot(hydrated, snapshot);

    expect(selectRoomParticipantPublicProgress(live)).toEqual(
      selectRoomParticipantPublicProgress(hydrated),
    );
    expect(selectRoomParticipantPublicProgress(rehydrated)).toEqual([
      expect.objectContaining({
        participantId: 'participant-research',
        sourceSessionId: 'session-research-next',
        kind: 'reasoning',
        status: 'running',
        summary: '正在准备共同复核',
      }),
      expect.objectContaining({
        participantId: 'participant-review',
        sourceSessionId: 'session-review',
        kind: 'tool',
        summary: '正在检查公开回执',
        data: expect.objectContaining({ toolName: 'read' }),
      }),
    ]);
  });

  it('keeps one authoritative selectable request until its Session resolves it', () => {
    const waiting = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventId: 'session:input:1',
        sourceEventType: 'user_input_required',
        data: {
          requestId: 'input:1',
          requestKind: 'user_input_required',
          method: 'select',
          title: '选择部署环境',
          options: [{ id: 'staging', label: '预发布' }, { id: 'production', label: '生产' }],
        },
      }),
    ).state;
    const resolved = reduceRoomEvent(
      waiting,
      roomEvent(2, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventId: 'session:input:2',
        sourceEventType: 'user_input_required',
        data: {
          requestId: 'input:1',
          requestKind: 'user_input_required',
          method: 'select',
          resolutionState: 'resolved',
          resolutionSource: 'user',
        },
      }),
    ).state;
    const activityId = 'room-turn-1:participant-1:dispatch-1:input:1';

    expect(waiting.activitiesById[activityId]).toMatchObject({
      status: 'waiting',
      sourceSessionId: 'session-room-1',
      payload: { title: '选择部署环境', options: expect.any(Array) },
    });
    expect(resolved.activityOrder).toEqual([activityId]);
    expect(resolved.activitiesById[activityId]).toMatchObject({
      status: 'completed',
      payload: {
        title: '选择部署环境',
        resolutionState: 'resolved',
        resolutionSource: 'user',
      },
    });
  });

  it('keeps grouped clarification waiting even when it does not use a single-input method', () => {
    const pending = reduceRoomEvent(
      createRoomProjection('room-1'),
      roomEvent(1, 'participant_activity', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        sourceEventId: 'session:grouped:1',
        requestId: 'grouped:1',
        requestKind: 'grouped_questions',
        questions: [
          { id: 'scope', question: '先覆盖哪一部分？', options: ['核心流程', '完整流程'] },
          { id: 'review', question: '如何复核？', options: ['伙伴互查', '直接交付'] },
        ],
      }),
    ).state;

    expect(Object.values(pending.activitiesById)).toEqual([
      expect.objectContaining({
        status: 'waiting',
        payload: expect.objectContaining({
          requestKind: 'grouped_questions',
          questions: expect.any(Array),
        }),
      }),
    ]);
  });

  it('prefers explicit public data identities over envelope fallbacks', () => {
    const event = roomEvent(1, 'participant_activity', {
      rootId: 'root-fallback',
      dispatchId: 'dispatch-fallback',
      messageId: 'message-fallback',
      blockId: 'block-fallback',
      sourceEventId: 'source-fallback',
      sourceEventType: 'user_input_required',
      data: {
        rootId: 'root-owner',
        dispatchId: 'dispatch-owner',
        messageId: 'message-owner',
        blockId: 'block-owner',
        sourceEventId: 'source-owner',
        sourceEventType: 'user_input_required',
        participantId: 'participant-owner',
        sourceSessionId: 'session-owner',
        requestId: 'input-owner',
        requestKind: 'plan_review',
        method: 'select',
        options: ['批准', '修改'],
      },
    });
    event.participantId = 'participant-fallback';
    event.sourceSessionId = 'session-fallback';

    const state = reduceRoomEvent(createRoomProjection('room-1'), event).state;
    const activity = state.activitiesById[
      'root-owner:participant-owner:dispatch-owner:input-owner'
    ];

    expect(activity).toMatchObject({
      participantId: 'participant-owner',
      sourceSessionId: 'session-owner',
      status: 'waiting',
      payload: {
        rootId: 'root-owner',
        dispatchId: 'dispatch-owner',
        messageId: 'message-owner',
        blockId: 'block-owner',
        sourceEventId: 'source-owner',
      },
    });
    expect(roomActivityLaneIdentity(activity)).toMatchObject({
      rootId: 'root-owner',
      participantId: 'participant-owner',
      dispatchId: 'dispatch-owner',
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
        toolName: 'memory',
      }),
    ).state;
    const secondEvent = roomEvent(2, 'participant_activity', {
      dispatchId: 'dispatch-b',
      rootId: 'root-a',
      toolCallId: 'call-1',
      sourceEventType: 'tool_started',
      toolName: 'memory',
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

  it('keeps lane failures scoped until the Root terminal closes a multi-Agent turn', () => {
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
    const rootFailedEvent = roomEvent(5, 'turn_failed', {
      rootId: 'room-turn-1',
      error: '一条执行 lane 未完成',
    });
    rootFailedEvent.participantId = null;
    rootFailedEvent.sourceSessionId = '';
    const rootFailed = reduceRoomEvent(allTerminal, rootFailedEvent).state;

    expect(oneTerminal.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      participantIds: ['participant-1', 'participant-2'],
      terminalParticipantIds: ['participant-1'],
    });
    expect(allTerminal.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      terminalParticipantIds: ['participant-1', 'participant-2'],
      failedParticipantIds: ['participant-2'],
    });
    expect(rootFailed.turnsById['room-turn-1']).toMatchObject({
      status: 'failed',
      rootTerminalAtMs: 50,
    });
    expect(rootFailed.turnsById['room-turn-1'].terminalDispatchIds).toEqual([
      'dispatch-1',
      'dispatch-2',
    ]);
    expect(rootFailed.turnsById['room-turn-1'].failedDispatchIds).toEqual([
      'dispatch-2',
    ]);
    expect(rootFailed.turnsById['room-turn-1'].failedParticipantIds).toEqual([
      'participant-2',
    ]);
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
    const rootAborted = roomEvent(5, 'turn_completed', {
      status: 'aborted',
      aborted: true,
      rootId: 'room-turn-1',
    });
    rootAborted.participantId = null;
    rootAborted.sourceSessionId = '';
    const lateCompleted = roomEvent(6, 'turn_completed', {
      status: 'completed',
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
    });

    const routedOne = reduceRoomEvent(createRoomProjection('room-1'), routeOne).state;
    const routedBoth = reduceRoomEvent(routedOne, routeTwo).state;
    const oneStopped = reduceRoomEvent(routedBoth, firstAborted).state;
    const allStopped = reduceRoomEvent(oneStopped, secondAborted).state;
    const stoppedRoot = reduceRoomEvent(allStopped, rootAborted).state;
    const afterLate = reduceRoomEvent(stoppedRoot, lateCompleted).state;

    expect(oneStopped.turnsById['room-turn-1'].status).toBe('running');
    expect(allStopped.turnsById['room-turn-1']).toMatchObject({
      status: 'running',
      terminalParticipantIds: ['participant-1', 'participant-2'],
      abortedParticipantIds: ['participant-1', 'participant-2'],
    });
    expect(afterLate.turnsById['room-turn-1']).toMatchObject({
      status: 'aborted',
      abortedParticipantIds: ['participant-1', 'participant-2'],
    });
  });

  it('settles an interrupted tool activity when its Root is aborted', () => {
    const events = [
      roomEvent(1, 'route_decision', {
        rootId: 'room-turn-1',
        dispatchId: 'dispatch-1',
        targetParticipantId: 'participant-1',
      }),
      parseRoomEvent(wireRoomEvent(2, 'participant_activity', {
        data: {
          rootId: 'room-turn-1',
          dispatchId: 'dispatch-1',
          toolCallId: 'call-bash',
          toolName: 'bash',
        },
        sourceEventId: 'session-room-1:2',
        sourceEventType: 'tool_started',
      })),
    ];
    const rootAborted = parseRoomEvent({
      ...wireRoomEvent(3, 'turn_completed', {
        rootId: 'room-turn-1',
        status: 'aborted',
      }),
      participantId: null,
      sourceSessionId: '',
      createdAtMs: 0,
    });

    let state = createRoomProjection('room-1');
    for (const event of [...events, rootAborted]) {
      state = reduceRoomEvent(state, event).state;
    }
    const activity = Object.values(state.activitiesById).find(
      (candidate) => candidate.payload.toolCallId === 'call-bash',
    );
    const publicProgress = selectRoomParticipantPublicProgress(state).find(
      (candidate) => candidate.kind === 'tool',
    );

    expect(activity).toMatchObject({
      status: 'aborted',
      updatedAtMs: 20,
    });
    expect(publicProgress).toMatchObject({
      kind: 'tool',
      status: 'aborted',
    });
  });

  it('preserves settled lane evidence when Root aborts only unfinished work', () => {
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
    const published = roomEvent(3, 'room_post', {
      post: roomPost('post-settled', '第一项分工已交付', 'dispatch-1'),
    });
    const rootAborted = roomEvent(4, 'turn_completed', {
      status: 'aborted',
      aborted: true,
      rootId: 'room-turn-1',
    });
    rootAborted.participantId = null;
    rootAborted.sourceSessionId = '';

    let state = createRoomProjection('room-1');
    for (const event of [routeOne, routeTwo, published, rootAborted]) {
      state = reduceRoomEvent(state, event).state;
    }

    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'aborted',
      terminalDispatchIds: ['dispatch-1', 'dispatch-2'],
      abortedDispatchIds: ['dispatch-2'],
      terminalParticipantIds: ['participant-1', 'participant-2'],
      abortedParticipantIds: ['participant-2'],
    });
    expect(state.messagesById['post-settled']).toMatchObject({
      status: 'completed',
      text: '第一项分工已交付',
    });
  });

  it('rejects late deltas, RoomPosts, and terminals after the Root fence', () => {
    const events = [
      roomEvent(1, 'route_decision', {
        rootId: 'room-turn-1', dispatchId: 'dispatch-1', targetParticipantId: 'participant-1',
      }),
      roomEvent(2, 'participant_delta', {
        rootId: 'room-turn-1', dispatchId: 'dispatch-1', messageId: 'draft-1', delta: '草稿',
      }),
      roomEvent(3, 'room_post', {
        post: roomPost('post-1', '正式交付', 'dispatch-1'),
      }),
    ];
    let state = createRoomProjection('room-1');
    for (const event of events) state = reduceRoomEvent(state, event).state;
    state = reduceRoomEvent(state, parseRoomEvent({
      ...wireRoomEvent(4, 'turn_completed', { status: 'completed' }),
      participantId: null,
      sourceSessionId: '',
    })).state;
    state = reduceRoomEvent(state, roomEvent(5, 'participant_delta', {
      rootId: 'room-turn-1', dispatchId: 'dispatch-1', messageId: 'late-draft', delta: '迟到草稿',
    })).state;
    state = reduceRoomEvent(state, roomEvent(6, 'room_post', {
      post: roomPost('post-late', '迟到公开 Post', 'dispatch-1'),
    })).state;
    state = reduceRoomEvent(state, roomEvent(7, 'turn_failed', {
      rootId: 'room-turn-1', error: '迟到失败',
    })).state;

    expect(state.lastSequence).toBe(7);
    expect(state.messageOrder).toEqual(['post-1']);
    expect(state.messagesById['post-1']).toMatchObject({
      status: 'completed',
      text: '正式交付',
    });
    expect(state.turnsById['room-turn-1']).toMatchObject({
      status: 'completed',
      rootTerminalAtMs: 40,
    });
    expect(state.diagnostics.filter(
      (item) => item.eventType === 'room_event_after_root_terminal',
    )).toHaveLength(3);
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
      text: '@澄 检查状态',
      nowMs: 1,
    });
    const snapshot = parseRoomEventSnapshot(roomSnapshotFixture([
      wireRoomEvent(5, 'user_message', {
        clientMessageId: 'room-client-1',
        text: '@澄 检查状态',
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

  it('validates bounded Room history pages and their cursor invariants', () => {
    const items = [
      wireRoomEvent(3, 'participant_status', { status: 'working' }),
      wireRoomEvent(4, 'turn_completed', {}),
    ];
    const rawPage = {
      schemaVersion: 'rag-ime.agent-room-event-page.v1',
      ok: true,
      roomId: 'room-1',
      items,
      firstSequence: 3,
      lastSequence: 4,
      nextBeforeSequence: 3,
      hasMore: true,
      retainedFirstSequence: 1,
      retainedLastSequence: 10,
      retainedPrefixTruncated: false,
    };
    const page = parseRoomEventPage(rawPage);

    expect(page.items.map((event) => event.sequence)).toEqual([3, 4]);
    expect(() => parseRoomEventPage({
      ...rawPage,
      lastSequence: 5,
    })).toThrow(/bounds/);
  });
  it('projects model arbitration as running work instead of human review', () => {
    const pending = roomEvent(1, 'participant_activity', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      approvalId: 'approval-model-1',
      payloadSha256: 'c'.repeat(64),
      decisionMode: 'model',
      automatic: true,
      approvalModelDecision: {
        status: 'pending',
        model: 'openai-codex/gpt-5.6-luna',
      },
    });
    const deciding = reduceRoomEvent(createRoomProjection('room-1'), pending).state;
    const activityId = deciding.activityOrder[0]!;

    expect(deciding.activitiesById[activityId]).toMatchObject({
      status: 'running',
      payload: {
        approvalId: 'approval-model-1',
        decisionMode: 'model',
      },
    });

    const denied = roomEvent(2, 'participant_activity', {
      rootId: 'room-turn-1',
      dispatchId: 'dispatch-1',
      approvalId: 'approval-model-1',
      payloadSha256: 'c'.repeat(64),
      state: 'rejected',
      resolutionState: 'rejected',
      decisionMode: 'model',
      automatic: true,
      approvalDecisionReceiptId: 'approval-model-decision:1',
      approvalModelDecision: {
        status: 'decided',
        decision: 'deny',
        model: 'openai-codex/gpt-5.6-luna',
        reasonCodes: ['destructive_command'],
      },
    });
    const settled = reduceRoomEvent(deciding, denied).state;

    expect(settled.activityOrder).toEqual([activityId]);
    expect(settled.activitiesById[activityId]).toMatchObject({
      status: 'completed',
      payload: {
        approvalDecisionReceiptId: 'approval-model-decision:1',
        approvalModelDecision: {
          decision: 'deny',
          reasonCodes: ['destructive_command'],
        },
      },
    });
  });



  it('projects a canonical user wait and clears it only from a later user RoomPost on the same Root', () => {
    const question = wireRoomEvent(1, 'room_post', {
      post: {
        schemaVersion: 'wisdom-weasel.room-post.v2',
        postId: 'wait-post-1',
        roomId: 'room-1',
        rootId: 'room-turn-1',
        generation: 0,
        authorActorRef: 'participant:facilitator',
        kind: 'wait',
        visibility: 'room',
        content: '请选择发布方式。',
        question: {
          prompt: '发布预览版还是稳定版？',
          options: [
            { value: 'preview', label: '预览版', recommended: true },
            { value: 'stable', label: '稳定版' },
          ],
        },
        idempotencyKey: 'wait-post-1',
        publicationSource: { kind: 'room_commit', ref: 'commit:wait-1' },
        createdAtMs: 10,
      },
    });
    let state = reduceRoomEvent(
      createRoomProjection('room-1'),
      parseRoomEvent(question),
    ).state;
    expect(state.pendingUserQuestion).toMatchObject({
      postId: 'wait-post-1',
      roomId: 'room-1',
      rootId: 'room-turn-1',
      sequence: 1,
      prompt: '发布预览版还是稳定版？',
      options: [
        { value: 'preview', label: '预览版', recommended: true },
        { value: 'stable', label: '稳定版' },
      ],
    });

    state = appendOptimisticRoomMessage(state, {
      clientMessageId: 'answer-client-1',
      text: 'stable',
      nowMs: 20,
    });
    state = reduceRoomEvent(state, parseRoomEvent(wireRoomEvent(2, 'user_message', {
      messageId: 'answer-message-1',
      clientMessageId: 'answer-client-1',
      rootId: 'room-turn-1',
      text: 'stable',
    }))).state;
    expect(state.pendingUserQuestion?.postId).toBe('wait-post-1');

    const unrelatedPost = wireRoomEvent(3, 'room_post', {
      post: {
        schemaVersion: 'wisdom-weasel.room-post.v2',
        postId: 'unrelated-user-post',
        roomId: 'room-1',
        rootId: 'another-root',
        generation: 0,
        authorActorRef: 'user:local',
        kind: 'request',
        visibility: 'room',
        content: '另一项任务',
        idempotencyKey: 'user-message:unrelated',
        publicationSource: { kind: 'user', ref: 'unrelated' },
        createdAtMs: 30,
      },
    });
    unrelatedPost.turnId = 'another-root';
    state = reduceRoomEvent(state, parseRoomEvent(unrelatedPost)).state;
    expect(state.pendingUserQuestion?.postId).toBe('wait-post-1');

    let terminalState = reduceRoomEvent(
      createRoomProjection('room-1'),
      parseRoomEvent(question),
    ).state;
    const rootTerminal = wireRoomEvent(2, 'turn_completed', {
      rootId: 'room-turn-1',
      status: 'completed',
    });
    rootTerminal.participantId = null;
    rootTerminal.sourceSessionId = '';
    terminalState = reduceRoomEvent(terminalState, parseRoomEvent(rootTerminal)).state;
    expect(terminalState.pendingUserQuestion).toBeUndefined();
    expect(terminalState.messagesById['wait-post-1']?.question).toMatchObject({
      status: 'pending',
    });

    let abortedState = reduceRoomEvent(
      createRoomProjection('room-1'),
      parseRoomEvent(question),
    ).state;
    abortedState = abortRoomTurn(abortedState, 'room-turn-1', 31);
    expect(abortedState.pendingUserQuestion).toBeUndefined();
    expect(abortedState.turnsById['room-turn-1']?.status).toBe('aborted');
    expect(abortedState.messagesById['wait-post-1']?.question).toMatchObject({
      status: 'pending',
    });

    const acceptedAnswer = wireRoomEvent(4, 'room_post', {
      post: {
        schemaVersion: 'wisdom-weasel.room-post.v2',
        postId: 'answer-post-1',
        roomId: 'room-1',
        rootId: 'room-turn-1',
        generation: 0,
        authorActorRef: 'user:local',
        kind: 'request',
        visibility: 'room',
        content: 'stable',
        idempotencyKey: 'user-message:answer-client-1',
        publicationSource: { kind: 'user', ref: 'answer-client-1' },
        createdAtMs: 40,
      },
    });
    acceptedAnswer.participantId = null;
    state = reduceRoomEvent(state, parseRoomEvent(acceptedAnswer)).state;
    expect(state.pendingUserQuestion).toBeUndefined();
    expect(state.messagesById['wait-post-1']?.question).toMatchObject({
      status: 'answered',
      answer: '稳定版',
    });
    expect(state.messagesById['answer-post-1']?.answerToPostId).toBe('wait-post-1');
  });
  it('reconciles one optimistic answer through user_message and its authoritative user RoomPost', () => {
    const clientMessageId = 'room-web-answer-1';
    let state = appendOptimisticRoomMessage(createRoomProjection('room-1'), {
      clientMessageId,
      text: '采用稳定版',
      nowMs: 1,
    });
    const acceptedMessage = wireRoomEvent(1, 'user_message', {
      messageId: 'accepted-answer-1',
      clientMessageId,
      rootId: 'room-turn-1',
      text: '采用稳定版',
    });
    acceptedMessage.participantId = null;
    state = reduceRoomEvent(state, parseRoomEvent(acceptedMessage)).state;

    const acceptedPost = wireRoomEvent(2, 'room_post', {
      post: {
        schemaVersion: 'wisdom-weasel.room-post.v2',
        postId: 'answer-post-1',
        roomId: 'room-1',
        rootId: 'room-turn-1',
        generation: 0,
        authorActorRef: 'user:local',
        kind: 'request',
        visibility: 'room',
        content: '采用稳定版',
        idempotencyKey: `user-message:${clientMessageId}`,
        publicationSource: { kind: 'user', ref: clientMessageId },
        createdAtMs: 20,
      },
    });
    acceptedPost.participantId = null;
    state = reduceRoomEvent(state, parseRoomEvent(acceptedPost)).state;

    expect(state.messageOrder).toEqual(['answer-post-1']);
    expect(state.turnOrder).toEqual(['room-turn-1']);
    expect(state.turnsById['room-turn-1'].messageIds).toEqual(['answer-post-1']);
    expect(state.messagesById['answer-post-1']).toMatchObject({
      clientMessageId,
      role: 'user',
      projectionKind: 'post',
      rootId: 'room-turn-1',
      text: '采用稳定版',
    });
    expect(state.optimisticByClientMessageId[clientMessageId]).toBeUndefined();
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
    participantId: 'participant-1' as string | null,
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
      executionMode: 'workspace_managed',
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
    ...(dispatchId ? { dispatchId } : {}),
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
    displayName: ordinal === 0 ? '澄·今' : '澄·初',
    collaborationRole: ordinal === 0 ? 'coordinator' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
