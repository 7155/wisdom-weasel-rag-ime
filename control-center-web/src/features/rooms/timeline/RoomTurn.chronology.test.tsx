import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RootProjection } from '@/contracts/room-kernel-reducer';
import {
  createRoomProjection,
  parseRoomEventSnapshot,
  reduceRoomEvents,
  replayRoomEventSnapshot,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import { RoomTurn } from './RoomTurn';

describe('RoomTurn canonical conversation chronology', () => {
  afterEach(cleanup);

  it('renders question, answer, question, answer, alignment, and typed start in server order', () => {
    const projection = liveProjection(alignmentEvents());
    const view = render(roomTurn(projection));

    expectTextOrder(view.container, [
      '@澄·今 我准备写 TUI',
      '目标界面是什么？',
      '终端原生 TUI',
      '首版交付边界是什么？',
      '可运行闭环',
      '我明白了：先完成终端原生 TUI 的可运行闭环。',
      '开始行动',
    ]);
    expect(messageOrder(view.container)).toEqual([
      'opening',
      'question-1',
      'answer-1',
      'question-2',
      'answer-2',
      'alignment',
      'start',
    ]);
  });

  it('preserves A/B/A public posts across participant lanes', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请一起完成跨角色任务'),
      postEvent(2, 'a-first', 'work_result', '澄·今先确认边界', 'participant-a', 'dispatch-a'),
      postEvent(3, 'b-middle', 'work_result', '澄·初补充独立检查', 'participant-b', 'dispatch-b'),
      postEvent(4, 'a-last', 'work_result', '澄·今完成最终整合', 'participant-a', 'dispatch-a'),
    ]);
    const view = render(roomTurn(projection));

    expectTextOrder(view.container, [
      '请一起完成跨角色任务',
      '澄·今先确认边界',
      '澄·初补充独立检查',
      '澄·今完成最终整合',
    ]);
    expect(messageOrder(view.container)).toEqual([
      'opening',
      'a-first',
      'b-middle',
      'a-last',
    ]);
    expect(view.container.querySelectorAll('.agent-persona-avatar')).toHaveLength(2);
    expect(
      view.container.querySelector('[data-room-message-id="a-last"]'),
    ).toHaveAttribute('data-continuation', 'true');
  });

  it('interleaves a public handoff between earlier and later role activity', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请一起完成 TUI'),
      postEvent(2, 'accepted', 'progress', '我已经接手，先核对现有入口', 'participant-a', 'dispatch-a'),
      toolActivityEvent(3, '读取并更新了 TUI 入口', 'participant-a', 'dispatch-a'),
      postEvent(4, 'result', 'work_result', '入口与验证已经完成', 'participant-a', 'dispatch-a'),
      activityEvent(5, '继续完成交接后的验证', 'participant-a', 'dispatch-a'),
    ]);

    const view = render(roomTurn(projection));
    const opening = textElement(view.container, '请一起完成 TUI');
    const accepted = textElement(view.container, '我已经接手，先核对现有入口');
    const activity = view.container.querySelector<HTMLElement>('.room-agent-activity--tool')!;
    const handoff = textElement(view.container, '入口与验证已经完成');
    const laterActivity = [...view.container.querySelectorAll<HTMLElement>('.room-agent-activity strong')]
      .find((element) => element.textContent === '继续完成交接后的验证')!
      .closest('.room-agent-activity')!;

    expect(activity).toBeInTheDocument();
    expect(opening.compareDocumentPosition(accepted) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(accepted.compareDocumentPosition(activity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(activity.compareDocumentPosition(handoff) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(handoff.compareDocumentPosition(laterActivity) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('uses one role identity when activity is followed by the same role public reply', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请完成这个入口'),
      activityEvent(2, '正在检查现有入口', 'participant-a', 'dispatch-a'),
      postEvent(3, 'reply', 'progress', '入口已经找到，我继续处理', 'participant-a', 'dispatch-a'),
    ]);
    const view = render(roomTurn(projection));

    expect(view.container.querySelectorAll('.agent-persona-avatar')).toHaveLength(1);
    expect(view.container.querySelector('.room-participant-message')).toHaveAttribute(
      'data-continuation',
      'true',
    );
    expect(view.container).toHaveTextContent('入口已经找到，我继续处理');
  });

  it('keeps parallel lane segments and public messages in one server-ordered stream', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请并行完成两个部分'),
      activityEvent(2, '澄·今开始实现', 'participant-a', 'dispatch-a'),
      activityEvent(3, '澄·初开始复核', 'participant-b', 'dispatch-b'),
      postEvent(4, 'b-handoff', 'handoff', '澄·初先交回复核线索', 'participant-b', 'dispatch-b'),
      postEvent(5, 'a-update', 'progress', '澄·今补充实现说明', 'participant-a', 'dispatch-a'),
      activityEvent(6, '澄·初继续验证', 'participant-b', 'dispatch-b'),
      activityEvent(7, '澄·今完成收尾', 'participant-a', 'dispatch-a'),
    ]);
    const view = render(roomTurn(projection));

    expectTextOrder(view.container, [
      '请并行完成两个部分',
      '澄·今开始实现',
      '澄·初开始复核',
      '澄·初先交回复核线索',
      '澄·今补充实现说明',
      '澄·初继续验证',
      '澄·今完成收尾',
    ]);
    expect(view.container.querySelectorAll('.room-agent-lane[data-continuation="true"]')).toHaveLength(2);
    expect(view.container.querySelectorAll('.room-agent-lane .agent-persona-avatar')).toHaveLength(2);
  });

  it('stops live motion when a companion is waiting for the user', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请完成这个入口'),
      activityEvent(2, '正在检查入口', 'participant-a', 'dispatch-a'),
      postEvent(3, 'wait-user', 'wait', '请选择要继续的入口', 'participant-a', 'dispatch-a'),
    ]);
    const view = render(roomTurn(projection));
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-state', 'waiting');
    expect(lane).toHaveAttribute('data-motion', 'settled');
    expect(lane).not.toHaveAttribute('data-live');
    expect(lane.querySelector('.room-agent-lane__live-indicator')).toHaveAttribute(
      'data-active',
      'false',
    );
    expect(lane.querySelector('.agent-persona-avatar')).not.toHaveAttribute(
      'data-presence',
      'thinking',
    );
  });

  it('uses authoritative sequence when a message and activity share a timestamp', () => {
    const message = postEvent(
      2,
      'same-time-message',
      'progress',
      '先公开这条说明',
      'participant-a',
      'dispatch-a',
    );
    message.createdAtMs = 3_000;
    const post = (message.payload as { post: { createdAtMs: number; chronology: { createdAtMs: number } } }).post;
    post.createdAtMs = 3_000;
    post.chronology.createdAtMs = 3_000;
    const activity = activityEvent(3, '随后记录工具进展', 'participant-a', 'dispatch-a');
    activity.createdAtMs = 3_000;
    const projection = liveProjection([
      userEvent(1, 'opening', '核对同一时间的顺序'),
      message,
      activity,
    ]);
    const view = render(roomTurn(projection));

    expectTextOrder(view.container, [
      '核对同一时间的顺序',
      '先公开这条说明',
      '随后记录工具进展',
    ]);
  });

  it('uses authoritative sequence across lanes when every update shares a timestamp', () => {
    const facilitatorActivity = activityEvent(
      2,
      '澄·今先完成状态模型',
      'participant-a',
      'dispatch-a',
    );
    facilitatorActivity.createdAtMs = 4_000;
    const reviewerActivity = activityEvent(
      3,
      '澄·初随后开始独立复核',
      'participant-b',
      'dispatch-b',
    );
    reviewerActivity.createdAtMs = 4_000;
    const reviewerPost = postEvent(
      4,
      'same-time-review',
      'review_result',
      '澄·初最后提交复核结果',
      'participant-b',
      'dispatch-b',
    );
    reviewerPost.createdAtMs = 4_000;
    const post = (reviewerPost.payload as {
      post: { createdAtMs: number; chronology: { createdAtMs: number } };
    }).post;
    post.createdAtMs = 4_000;
    post.chronology.createdAtMs = 4_000;
    const projection = liveProjection([
      userEvent(1, 'opening', '同一时刻并行完成并复核'),
      facilitatorActivity,
      reviewerActivity,
      reviewerPost,
    ]);
    const view = render(roomTurn(projection));

    expectTextOrder(view.container, [
      '同一时刻并行完成并复核',
      '澄·今先完成状态模型',
      '澄·初随后开始独立复核',
      '澄·初最后提交复核结果',
    ]);
  });

  it('renders live reduction and reconnect replay with the same canonical order', () => {
    const events = alignmentEvents();
    const live = liveProjection(events);
    const replayed = replayRoomEventSnapshot(
      createRoomProjection('room-a'),
      parseRoomEventSnapshot(snapshot(events)),
    );
    const liveView = render(roomTurn(live));
    expectTextOrder(liveView.container, [
      '@澄·今 我准备写 TUI',
      '目标界面是什么？',
      '终端原生 TUI',
      '首版交付边界是什么？',
      '可运行闭环',
      '我明白了：先完成终端原生 TUI 的可运行闭环。',
      '开始行动',
    ]);
    const liveOrder = messageOrder(liveView.container);
    liveView.unmount();
    const replayedView = render(roomTurn(replayed));

    expectTextOrder(replayedView.container, [
      '@澄·今 我准备写 TUI',
      '目标界面是什么？',
      '终端原生 TUI',
      '首版交付边界是什么？',
      '可运行闭环',
      '我明白了：先完成终端原生 TUI 的可运行闭环。',
      '开始行动',
    ]);
    expect(messageOrder(replayedView.container)).toEqual(liveOrder);
    expect(liveOrder).toEqual([
      'opening',
      'question-1',
      'answer-1',
      'question-2',
      'answer-2',
      'alignment',
      'start',
    ]);
  });

  it('places the start action immediately after the final alignment summary', () => {
    const projection = liveProjection(alignmentEvents().slice(0, -1));
    const view = render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('waiting') },
      kernelReceiptsById: Object.fromEntries([
        receipt(1, { operation: 'room_define', requiresStartAction: true }),
        receipt(2, {
          purpose: 'intake_phase',
          phase: 'awaiting_start',
          clarificationOccurred: true,
        }),
      ].map((item) => [item.receiptId, item])),
      onStartExecution: () => undefined,
    }));
    const alignment = textElement(
      view.container,
      '我明白了：先完成终端原生 TUI 的可运行闭环。',
    );
    const gate = screen.getByRole('group', { name: '确认开始行动' });

    expect(alignment.compareDocumentPosition(gate) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(gate).toHaveTextContent('现在开始行动吗？');
  });

  it('does not render an unanchored start action before the canonical alignment post arrives', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请先澄清交付边界'),
    ]);
    render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('waiting') },
      kernelReceiptsById: Object.fromEntries([
        receipt(1, { operation: 'room_define', requiresStartAction: true }),
        receipt(2, {
          purpose: 'intake_phase',
          phase: 'awaiting_start',
          clarificationOccurred: true,
        }),
      ].map((item) => [item.receiptId, item])),
      onStartExecution: () => undefined,
    }));

    expect(screen.queryByRole('group', { name: '确认开始行动' })).not.toBeInTheDocument();
  });

  it('keeps a pending clarification in the message flow without duplicate lane controls', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '@澄·今 我准备写 TUI'),
      questionEvent(2, 'question-1', '目标界面是什么？', ['终端原生 TUI', '网页界面']),
      userEvent(3, 'answer-1', '终端原生 TUI', 'question-1'),
      questionEvent(
        4,
        'question-2',
        '首版交付边界是什么？',
        ['可运行闭环', '完整插件生态'],
        'dispatch-resume',
      ),
    ]);
    const view = render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('waiting') },
      onAbortTurn: () => undefined,
    }));

    expect(screen.getByRole('region', { name: '需要回答：首版交付边界是什么？' })).toBeInTheDocument();
    expect(view.container).toHaveTextContent('终端原生 TUI');
    expect(screen.queryByRole('button', { name: '停止本轮任务' })).not.toBeInTheDocument();
    expect(view.container.querySelector('.room-agent-lane')).not.toBeInTheDocument();
  });

  it('locks a pending question when the Kernel terminal snapshot arrives first', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请先澄清交付边界'),
      postEvent(2, 'progress', 'progress', '我先核对当前范围', 'participant-a', 'dispatch-a'),
      questionEvent(3, 'question-terminal', '首版交付边界是什么？', ['可运行闭环', '完整插件生态']),
    ]);
    projection.turnsById['root-a'] = {
      ...projection.turnsById['root-a']!,
      terminalParticipantIds: [],
      terminalDispatchIds: [],
    };
    const view = render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('cancelled') },
      onAnswerQuestion: async () => true,
    }));

    expect(screen.getByText('这项问题已不再是当前可回答的问题。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '可运行闭环' })).not.toBeInTheDocument();
    expect(view.container.querySelector('.room-agent-lane')).toHaveAttribute('data-state', 'aborted');
    expect(view.container).toHaveTextContent('我先核对当前范围');
    expect(view.container).toHaveTextContent('已停止');
    expect(view.container).not.toHaveTextContent('已完成');
  });

  it('keeps a lane failed when the Kernel failure arrives before the Room turn terminal event', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '请完成当前任务'),
      postEvent(2, 'progress', 'progress', '我正在核对实现范围', 'participant-a', 'dispatch-a'),
    ]);
    projection.turnsById['root-a'] = {
      ...projection.turnsById['root-a']!,
      terminalParticipantIds: [],
      terminalDispatchIds: [],
    };
    const view = render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('failed') },
    }));

    expect(view.container.querySelector('.room-agent-lane')).toHaveAttribute('data-state', 'failed');
    expect(view.container).toHaveTextContent('未完成');
    expect(view.container).not.toHaveTextContent('已完成');
  });

  it('keeps a clear request on the direct path without a confirmation gate', () => {
    const projection = liveProjection([
      userEvent(1, 'opening', '把已确认的标题改成新标题并运行现有聚焦测试'),
      postEvent(2, 'direct-work', 'work_result', '标题与测试已经更新', 'participant-a', 'dispatch-a'),
    ]);
    render(roomTurn(projection, {
      kernelRootsById: { 'root-a': root('running') },
      kernelReceiptsById: {
        'receipt-1': receipt(1, {
          purpose: 'intake_phase',
          phase: 'execution_ready',
          clarificationOccurred: false,
        }),
      },
      onStartExecution: () => undefined,
    }));

    expect(screen.queryByRole('button', { name: '开始行动' })).not.toBeInTheDocument();
  });
});

function roomTurn(
  projection: RoomProjectionState,
  props: Partial<Parameters<typeof RoomTurn>[0]> = {},
) {
  return <RoomTurn
    personas={[]}
    projection={projection}
    room={{
      participants: [
        {
          id: 'participant-a',
          sessionId: 'session-a',
          roleId: 'companion-present-v1',
          roleVersion: '1',
          displayName: '澄·今',
        },
        {
          id: 'participant-b',
          sessionId: 'session-b',
          roleId: 'companion-firstlight-v1',
          roleVersion: '1',
          displayName: '澄·初',
        },
      ],
    }}
    turnId="root-a"
    {...props}
  />;
}

function messageOrder(container: HTMLElement): string[] {
  return [...container.querySelectorAll<HTMLElement>('[data-room-message-id]')]
    .map((element) => element.dataset.roomMessageId ?? '');
}

function expectTextOrder(container: HTMLElement, texts: string[]): void {
  const elements = texts.map((text) => textElement(container, text));
  for (let index = 1; index < elements.length; index += 1) {
    expect(
      elements[index - 1]!.compareDocumentPosition(elements[index]!)
      & Node.DOCUMENT_POSITION_FOLLOWING,
      `${texts[index - 1]} should precede ${texts[index]}`,
    ).toBeTruthy();
  }
}

function textElement(container: HTMLElement, text: string): HTMLElement {
  const element = [...container.querySelectorAll<HTMLElement>('p, strong')]
    .find((candidate) => candidate.textContent === text);
  if (!element) throw new TypeError(`Missing public message text: ${text}`);
  return element;
}

function liveProjection(events: ReturnType<typeof event>[]): RoomProjectionState {
  return reduceRoomEvents(
    createRoomProjection('room-a'),
    events.map((item) => parseRoomEvent(item)),
  );
}

function alignmentEvents() {
  return [
    userEvent(1, 'opening', '@澄·今 我准备写 TUI'),
    questionEvent(2, 'question-1', '目标界面是什么？', ['终端原生 TUI', '网页界面']),
    userEvent(3, 'answer-1', '终端原生 TUI', 'question-1'),
    questionEvent(4, 'question-2', '首版交付边界是什么？', ['可运行闭环', '完整插件生态']),
    userEvent(5, 'answer-2', '可运行闭环', 'question-2'),
    postEvent(6, 'alignment', 'alignment', '我明白了：先完成终端原生 TUI 的可运行闭环。'),
    userEvent(7, 'start', '开始行动'),
  ];
}

function userEvent(sequence: number, messageId: string, text: string, answerToPostId = '') {
  return event(sequence, 'user_message', {
    messageId,
    text,
    rootId: 'root-a',
    ...(answerToPostId ? { answerToPostId } : {}),
  }, null, '');
}

function questionEvent(
  sequence: number,
  postId: string,
  prompt: string,
  labels: string[],
  dispatchId = 'dispatch-align',
) {
  return postEvent(sequence, postId, 'wait', prompt, 'participant-a', dispatchId, {
    prompt,
    options: labels.map((label, index) => ({ value: `choice-${index}`, label })),
  });
}

function postEvent(
  sequence: number,
  postId: string,
  kind: string,
  content: string,
  participantId = 'participant-a',
  dispatchId = 'dispatch-align',
  question?: { prompt: string; options: { value: string; label: string }[] },
) {
  return event(sequence, 'room_post', {
    post: {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId,
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 1,
      dispatchId,
      authorActorRef: participantId,
      kind,
      visibility: 'room',
      content,
      chronology: {
        schemaVersion: 'wisdom-weasel.room-post-chronology.v1',
        roomEventId: `room-a:${sequence}`,
        roomEventSequence: sequence,
        createdAtMs: sequence * 1_000,
        afterPostId: null,
        orderKey: `room-event:${String(sequence).padStart(20, '0')}`,
      },
      ...(question ? { question } : {}),
      idempotencyKey: `post:${postId}`,
      publicationSource: { kind: 'room_commit', ref: `commit:${postId}` },
      createdAtMs: sequence * 1_000,
    },
  }, participantId, participantId === 'participant-b' ? 'session-b' : 'session-a');
}

function activityEvent(
  sequence: number,
  summary: string,
  participantId: string,
  dispatchId: string,
) {
  return event(sequence, 'participant_activity', {
    rootId: 'root-a',
    dispatchId,
    sourceEventType: 'current_progress',
    requestId: `progress-${sequence}`,
    summary,
    status: 'completed',
  }, participantId, participantId === 'participant-b' ? 'session-b' : 'session-a');
}

function toolActivityEvent(
  sequence: number,
  summary: string,
  participantId: string,
  dispatchId: string,
) {
  return event(sequence, 'participant_activity', {
    rootId: 'root-a',
    dispatchId,
    sourceEventType: 'tool_finished',
    toolName: 'edit',
    toolCallId: `tool-${sequence}`,
    summary,
    status: 'completed',
  }, participantId, participantId === 'participant-b' ? 'session-b' : 'session-a');
}

function event(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
  participantId: string | null = 'participant-a',
  sourceSessionId = 'session-a',
) {
  return {
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `room-a:${sequence}`,
    roomId: 'room-a',
    sequence,
    turnId: 'root-a',
    eventType,
    participantId,
    sourceSessionId,
    createdAtMs: sequence * 1_000,
    payload,
    resumeToken: `room-a:${sequence}`,
  };
}

function snapshot(events: ReturnType<typeof event>[]) {
  const lastSequence = events.at(-1)?.sequence ?? 0;
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1',
      id: 'room-a',
      title: 'Chronology Room',
      status: 'active',
      executionMode: 'workspace_managed',
      routingPolicy: 'moderator',
      moderatorParticipantId: 'participant-a',
      workspaceRoots: ['/Volumes/work/learnA'],
      createdAtMs: 1,
      updatedAtMs: lastSequence * 1_000,
      lastEventSequence: lastSequence,
      participants: [
        participant('participant-a', 'session-a', 0),
        participant('participant-b', 'session-b', 1),
      ],
    },
    events,
    firstSequence: events[0]?.sequence ?? 0,
    lastSequence,
    resumeToken: lastSequence ? `room-a:${lastSequence}` : '',
    truncated: false,
  };
}

function participant(id: string, sessionId: string, ordinal: number) {
  return {
    schemaVersion: 'rag-ime.agent-participant.v1',
    id,
    roomId: 'room-a',
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

function root(state: RootProjection['state']): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root-a',
    roomId: 'room-a',
    generation: 1,
    state,
    facilitatorParticipantId: 'participant-a',
    reporterParticipantId: null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement-a',
    createdByActorRef: 'user-a',
    terminalReceiptId: null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget-a',
    independentReviewRequired: false,
    createdAtMs: 1,
    updatedAtMs: 2,
    isFinal: false,
  };
}

function receipt(createdAtMs: number, details: Record<string, unknown>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1',
    receiptId: `receipt-${createdAtMs}`,
    rootId: 'root-a',
    commandId: null,
    receiptKind: 'accepted',
    status: 'applied',
    generation: 1,
    details,
    createdAtMs,
  };
}
