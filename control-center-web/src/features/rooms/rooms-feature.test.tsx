import type { Key, ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { createRoomProjection, reduceRoomEvent } from '@/contracts/room-reducer';
import { createRoomKernelProjection, type RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import { parseRoomEvent } from '@/contracts/validators';
import { previewPersonas } from '@/features/agent/preview-data';
import type { ControlRequest, PickedFile } from '@/platform/transport';
import { RoomTurn, RoomsFeature, type RoomSummary } from './index';
import { RoomStatusPanel } from './RoomStatusPanel';
import { useRoomLiveStore } from './state/live-store';

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({
    components,
    context,
    computeItemKey,
    data,
    initialTopMostItemIndex,
    itemContent,
  }: {
    components?: { Header?: (props: { context?: unknown }) => ReactNode };
    context?: unknown;
    computeItemKey?: (index: number, item: string) => Key;
    data: string[];
    initialTopMostItemIndex?: { index: string | number; align?: string };
    itemContent: (index: number, item: string) => ReactNode;
  }) => {
    const Header = components?.Header;
    return (
      <div
        data-initial-align={initialTopMostItemIndex?.align}
        data-initial-index={initialTopMostItemIndex?.index}
        data-testid="virtuoso-list"
      >
        {Header ? <Header context={context} /> : null}
        {data.map((item, index) => <div key={computeItemKey?.(index, item) ?? index}>{itemContent(index, item)}</div>)}
      </div>
    );
  },
}));
describe('Rooms experience', () => {
  afterEach(() => {
    cleanup();
    useRoomLiveStore.getState().reset();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
  });

  it('sends messages through the room path and preserves the selected room id', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': {
        ok: true,
        items: [{
          id: 'room-a', title: '迁移作战室', status: 'active', routingPolicy: 'moderator',
          moderatorParticipantId: 'p1', updatedAtMs: Date.now(),
          participants: [
            { id: 'p1', sessionId: 's1', roleId: 'companion-present-v1', roleVersion: '1', displayName: '澄', status: 'active', ordinal: 0 },
            { id: 'p2', sessionId: 's2', roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '澄·初', status: 'active', ordinal: 1 },
          ],
        }],
      },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomEvent('room-a', 1, 'user_message', { text: '快照中的历史消息' }),
      ]),
      'agent.roles.list': { ok: true, items: [] },
      'agent.room.message': { ok: true },
      'agent.rooms.create': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    expect(screen.queryByAltText(/两位伙伴在私有工作区之间显式交接/)).not.toBeInTheDocument();
    const errorSlot = document.querySelector('.room-error-slot');
    expect(errorSlot).toBeInTheDocument();
    expect(errorSlot).toBeEmptyDOMElement();
    expect(errorSlot?.nextElementSibling).toHaveClass('room-timeline');
    expect(errorSlot?.nextElementSibling?.nextElementSibling).toHaveClass('room-composer-dock');
    expect(screen.getByTestId('virtuoso-list')).toHaveAttribute('data-initial-index', 'LAST');
    expect(screen.getByTestId('virtuoso-list')).toHaveAttribute('data-initial-align', 'end');
    await user.type(composer, '并行核对边界');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request;
    expect(request?.params).toEqual({ roomId: 'room-a' });
    expect(request?.body).toMatchObject({ message: '并行核对边界' });
    expect(request?.body).not.toHaveProperty('workItemId');
    expect(transport.subscriptionCalls[0]?.request).toMatchObject({
      pathId: 'agent.room.events',
      params: { roomId: 'room-a' },
      lastEventId: 'room-a:1',
    });
  });

  it('loads older Room history without collapsing an expanded report', async () => {
    const expandedMarker = '历史加载后仍保持展开。';
    const recent = [
      roomEvent('room-a', 3, 'user_message', { text: '最近消息三' }, {
        turnId: 'room-a:recent',
      }),
      roomTerminalPostEvent(
        'room-a',
        4,
        'result',
        `${'展开后保持可见。'.repeat(60)}${expandedMarker}`,
      ),
    ];
    const older = [
      roomEvent('room-a', 1, 'user_message', { text: '较早消息一' }, {
        turnId: 'room-a:older-1',
      }),
      roomEvent('room-a', 2, 'user_message', { text: '较早消息二' }, {
        turnId: 'room-a:older-2',
      }),
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '分页 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', recent),
      'agent.room.history': {
        schemaVersion: 'rag-ime.agent-room-event-page.v1',
        ok: true,
        roomId: 'room-a',
        items: older,
        firstSequence: 1,
        lastSequence: 2,
        nextBeforeSequence: 0,
        hasMore: false,
        retainedFirstSequence: 1,
        retainedLastSequence: 4,
        retainedPrefixTruncated: false,
      },
    } });
    const user = userEvent.setup();
    const { container } = render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('最近消息三')).toBeInTheDocument();
    const report = container.querySelector<HTMLDetailsElement>('.room-agent-lane__report')!;
    await user.click(within(report).getByText('查看完整汇报'));
    expect(within(report).getByText(/历史加载后仍保持展开/)).toBeInTheDocument();
    expect(report).toHaveAttribute('open');
    await user.click(screen.getByRole('button', { name: '载入更早记录' }));

    expect(await screen.findByText('较早消息一')).toBeInTheDocument();
    expect(screen.getByText('较早消息二')).toBeInTheDocument();
    const reportAfterPrepend = container.querySelector<HTMLDetailsElement>('.room-agent-lane__report')!;
    expect(reportAfterPrepend).toBe(report);
    expect(within(reportAfterPrepend).getByText(/历史加载后仍保持展开/)).toBeInTheDocument();
    expect(reportAfterPrepend).toHaveAttribute('open');
    expect(screen.queryByRole('button', { name: '载入更早记录' })).not.toBeInTheDocument();
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.history')?.request).toMatchObject({
      params: { roomId: 'room-a' },
      query: { beforeSequence: 3, limit: 200 },
    });
  });

  it('shows the canonical blocked WorkItem state instead of claiming work is executing', async () => {
    const room = roomSummary('room-a', '阻塞 Room');
    const blockedWork: NonNullable<RoomSummary['workItems']>[number] = {
      id: 'room-work:blocked',
      roomId: room.id,
      topicId: '',
      rootTurnId: 'room-root:blocked',
      rootWorkId: 'room-work:blocked',
      parentWorkId: '',
      objective: '核对失败证据',
      expectedOutput: '明确恢复步骤',
      acceptanceCriteria: ['不再显示执行中'],
      accountableParticipantId: 'room-a:p1',
      currentOwnerParticipantId: 'room-a:p2',
      offeredToParticipantId: '',
      createdByParticipantId: 'room-a:p1',
      clientMessageId: 'test-work-blocked',
      state: 'blocked',
      depth: 1,
      revision: 0,
      resultSummary: '',
      artifactRefs: [],
      evidenceRefs: [],
      blocker: {
        reason: 'Room 执行已阻塞。',
        nextStep: '检查阻塞证据。',
      },
      acceptedTurnId: 'room-root:blocked',
      createdAtMs: 1,
      updatedAtMs: 2,
      completedAtMs: null,
    };
    room.workItems = [blockedWork];
    const snapshot = roomSnapshot(room.id, []);
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': {
        ...snapshot,
        room: { ...snapshot.room, workItems: [blockedWork] },
      },
    } });

    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('learnA · 已阻塞')).toBeInTheDocument();
    expect(screen.queryByText(/正在完成任务/)).not.toBeInTheDocument();
    expect(screen.getByText(/已阻塞 · 澄·初 · 核对失败证据/)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '先继续或停止当前任务' })).toBeDisabled();
    expect(screen.getByText(/当前任务已暂停/)).toBeInTheDocument();
  });

  it('submits the pending wait answer through the busy gate and clears it only from the accepted user RoomPost', async () => {
    const pendingSend = deferred<Record<string, unknown>>();
    const room = roomSummary('room-a', '澄清 Room');
    const activeWork: NonNullable<RoomSummary['workItems']>[number] = {
      id: 'room-work:alignment',
      roomId: room.id,
      topicId: '',
      rootTurnId: 'room-a:turn-1',
      rootWorkId: 'room-work:alignment',
      parentWorkId: '',
      objective: '对齐发布方式',
      expectedOutput: '用户确认',
      acceptanceCriteria: ['记录用户选择'],
      accountableParticipantId: 'room-a:p1',
      currentOwnerParticipantId: 'room-a:p1',
      offeredToParticipantId: '',
      createdByParticipantId: 'room-a:p1',
      clientMessageId: 'opening-message',
      state: 'active',
      depth: 0,
      revision: 1,
      resultSummary: '',
      artifactRefs: [],
      evidenceRefs: [],
      blocker: {},
      acceptedTurnId: 'room-a:turn-1',
      createdAtMs: 1,
      updatedAtMs: 1,
      completedAtMs: null,
    };
    const snapshot = roomSnapshot('room-a', [
      roomQuestionEvent('room-a', 1, {
        content: '我需要你选择发布方式。',
        prompt: '这次采用哪一种发布方式？',
        options: [
          { value: 'A', label: '方案 A', description: '先发布预览版本', recommended: true },
          { value: 'B', label: '方案 B', description: '直接发布稳定版本' },
        ],
      }),
    ]);
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [{ ...room, workItems: [activeWork] }] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': {
        ...snapshot,
        room: { ...snapshot.room, workItems: [activeWork] },
      },
      'agent.room.message': () => pendingSend.promise,
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const questionRegion = await screen.findByRole('region', {
      name: '需要回答：这次采用哪一种发布方式？',
    });
    const questionCard = within(questionRegion);
    expect(questionRegion).toHaveAttribute('aria-live', 'polite');
    expect(questionCard.getByText('这次采用哪一种发布方式？')).toBeInTheDocument();
    expect(questionCard.getByText('推荐')).toBeInTheDocument();
    expect(questionCard.getByText('先发布预览版本')).toBeInTheDocument();
    expect(questionCard.getByText('直接发布稳定版本')).toBeInTheDocument();
    expect(questionRegion).not.toHaveTextContent('等待原因：');
    expect(questionRegion).not.toHaveTextContent('恢复条件：');
    expect(screen.queryByRole('textbox', { name: '协作消息' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '发送问题回答' })).not.toBeInTheDocument();
    expect(questionCard.getByRole('button', { name: '其他' })).toBeInTheDocument();
    expect(questionCard.queryByRole('button', { name: '发送回答' })).not.toBeInTheDocument();
    expect(questionCard.getByRole('button', { name: '确认并发送' })).toBeDisabled();

    const optionA = questionCard.getByRole('radio', { name: /方案 A/ });
    await waitFor(() => expect(optionA).toHaveFocus());
    fireEvent.click(optionA);
    expect(optionA).toBeChecked();
    const optionForm = questionRegion.querySelector('form');
    if (!optionForm) throw new Error('expected the option question form');
    fireEvent.submit(optionForm);
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.room.message'
    ))).toHaveLength(0);
    const optionB = questionCard.getByRole('radio', { name: '方案 B' });
    fireEvent.click(optionB);
    expect(questionCard.getByRole('radio', { name: '方案 B' })).toBeChecked();
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.room.message'
    ))).toHaveLength(0);
    const confirmAnswer = questionCard.getByRole('button', { name: '确认并发送' });
    expect(confirmAnswer).toBeEnabled();
    await user.click(confirmAnswer);

    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));
    const request = transport.requests.find(
      ({ request: item }) => item.pathId === 'agent.room.message',
    )!.request;
    expect(request.body).toMatchObject({
      message: 'B',
      attachmentIds: [],
      answerKind: 'option',
      answerToPostId: 'room-a:question-1',
      answerToRootId: 'room-a:turn-1',
    });
    expect(request.body).not.toHaveProperty('participantIds');
    const optimisticAnswer = document.querySelector('.room-user-message');
    expect(optimisticAnswer).toHaveTextContent('方案 B');
    expect(optimisticAnswer).not.toHaveTextContent(/^B(?:正在发送)?$/);
    expect(screen.getByRole('region', { name: '需要回答：这次采用哪一种发布方式？' })).toBeInTheDocument();

    const clientMessageId = String((request.body as Record<string, unknown>).clientMessageId);
    pendingSend.resolve({
      ok: true,
      timelineEvents: [
        roomEvent('room-a', 2, 'user_message', {
          messageId: 'room-a:answer-message-1',
          clientMessageId,
          rootId: 'room-a:turn-1',
          text: 'B',
        }, { turnId: 'room-a:turn-1' }),
        roomUserPostEvent('room-a', 3, 'room-a:turn-1', clientMessageId, 'B'),
      ],
    });
    await waitFor(() => expect(
      within(screen.getByRole('region', { name: '需要回答：这次采用哪一种发布方式？' }))
        .queryByRole('button', { name: '其他' }),
    ).not.toBeInTheDocument());
    const resolvedQuestion = within(screen.getByRole('region', { name: '需要回答：这次采用哪一种发布方式？' }));
    const resolvedPrompt = resolvedQuestion.getByText('这次采用哪一种发布方式？');
    expect(resolvedQuestion.getByText('已收到回答')).toBeInTheDocument();
    expect(resolvedQuestion.queryByText('已锁定')).not.toBeInTheDocument();
    expect(resolvedQuestion.queryByText('回答保留在下一条用户消息中')).not.toBeInTheDocument();
    const answerMessage = document.querySelector('.room-user-message');
    if (!answerMessage) {
      throw new Error('expected the accepted answer to render as a chronological user message');
    }
    expect(answerMessage).toHaveTextContent('B');
    expect(resolvedPrompt.compareDocumentPosition(answerMessage) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(document.querySelectorAll('.room-user-message')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '等待当前任务完成' })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole('textbox', { name: '协作消息' })).toHaveFocus());
  });

  it('opens free text only after Other and keeps the answer on the same question', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '其他回答 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomQuestionEvent('room-a', 1, {
          content: '请选择首版交付边界。',
          prompt: '首版最重要的交付边界是什么？',
          options: [
            { value: 'loop', label: '可运行闭环' },
            { value: 'ecosystem', label: '完整插件生态' },
          ],
        }),
      ]),
      'agent.room.message': (request: ControlRequest) => ({
        ok: true,
        timelineEvents: [
          roomUserPostEvent(
            'room-a',
            2,
            'room-a:turn-1',
            String((request.body as Record<string, unknown>).clientMessageId),
            String((request.body as Record<string, unknown>).message),
          ),
        ],
      }),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const questionCard = within(await screen.findByRole('region', {
      name: '需要回答：首版最重要的交付边界是什么？',
    }));
    expect(questionCard.queryByRole('textbox', { name: /你的回答/ })).not.toBeInTheDocument();
    expect(questionCard.queryByRole('button', { name: '发送回答' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: '协作消息' })).not.toBeInTheDocument();

    await user.click(questionCard.getByRole('button', { name: '其他' }));

    expect(questionCard.queryByRole('radio')).not.toBeInTheDocument();
    expect(questionCard.getByRole('button', { name: '返回选项' })).toBeInTheDocument();
    const answer = questionCard.getByRole('textbox', { name: /你的回答/ });
    await waitFor(() => expect(answer).toHaveFocus());
    await user.type(answer, 'loop');
    await user.click(questionCard.getByRole('button', { name: '发送回答' }));

    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));
    expect(transport.requests.find(
      ({ request }) => request.pathId === 'agent.room.message',
    )?.request.body).toMatchObject({
      message: 'loop',
      answerKind: 'custom',
      answerToPostId: 'room-a:question-1',
      answerToRootId: 'room-a:turn-1',
    });
  });

  it('reuses the same answer identity when delivery becomes uncertain and the user confirms again', async () => {
    let sendAttempts = 0;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '回答恢复 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomQuestionEvent('room-a', 1, {
          content: '先确认首版范围，我们再继续。',
          prompt: '首版先做到哪一步？',
          options: [
            {
              value: 'loop',
              label: '先跑通闭环',
              description: '先交付可以真实运行和验收的主流程，扩展能力放到下一轮。',
            },
            {
              value: 'ecosystem',
              label: '一次补齐生态',
              description: '同时覆盖插件和扩展接口，范围更大，首轮交付时间也会更长。',
            },
          ],
        }),
      ]),
      'agent.room.message': (request: ControlRequest) => {
        sendAttempts += 1;
        if (sendAttempts === 1) {
          throw new Error('connection closed after the server prepared the answer');
        }
        const body = request.body as Record<string, unknown>;
        return {
          ok: true,
          timelineEvents: [
            roomUserPostEvent(
              'room-a',
              2,
              'room-a:turn-1',
              String(body.clientMessageId),
              String(body.message),
            ),
          ],
        };
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const question = within(await screen.findByRole('region', {
      name: '需要回答：首版先做到哪一步？',
    }));
    await user.click(question.getByRole('radio', { name: '先跑通闭环' }));
    await user.click(question.getByRole('button', { name: '确认并发送' }));

    expect(await question.findByText('这次还没有送达，请稍后再确认一次。')).toBeInTheDocument();
    expect(question.getByRole('radio', { name: '先跑通闭环' })).toBeChecked();
    await user.click(question.getByRole('button', { name: '确认并发送' }));

    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(2));
    const answerRequests = transport.requests
      .filter(({ request }) => request.pathId === 'agent.room.message')
      .map(({ request }) => request.body as Record<string, unknown>);
    expect(answerRequests[0]).toMatchObject({
      answerKind: 'option',
      answerToPostId: 'room-a:question-1',
      answerToRootId: 'room-a:turn-1',
      message: 'loop',
    });
    expect(answerRequests[1]).toMatchObject({
      answerKind: 'option',
      answerToPostId: 'room-a:question-1',
      answerToRootId: 'room-a:turn-1',
      message: 'loop',
    });
    expect(answerRequests[1]?.clientMessageId).toBe(answerRequests[0]?.clientMessageId);
    await waitFor(() => expect(
      screen.queryByRole('button', { name: '确认并发送' }),
    ).not.toBeInTheDocument());
  });

  it('restores the ordinary composer when the Kernel terminates before the pending question event clears', async () => {
    const kernelSnapshot = roomKernelSnapshot('room-a');
    kernelSnapshot.roots = [{
      ...kernelSnapshot.roots[0],
      rootId: 'room-a:turn-1',
      state: 'failed',
    }];
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '终态恢复 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomQuestionEvent('room-a', 1, {
          content: '请选择首版交付边界。',
          prompt: '首版最重要的交付边界是什么？',
          options: [
            { value: 'loop', label: '可运行闭环' },
            { value: 'ecosystem', label: '完整插件生态' },
          ],
        }),
      ]),
      'agent.room.kernel.snapshot': kernelSnapshot,
    } });

    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><RoomsFeature /></TooltipProvider>
      </ControlTransportProvider>,
    );

    const question = within(await screen.findByRole('region', {
      name: '需要回答：首版最重要的交付边界是什么？',
    }));
    await waitFor(() => expect(
      question.getByText('这项问题已不再是当前可回答的问题。'),
    ).toBeInTheDocument());
    expect(question.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeEnabled();
  });


  it('renders and submits a text-only wait without inventing options', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '自由回答 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomQuestionEvent('room-a', 1, {
          content: '请补充不能改变的边界。',
          prompt: '还有哪些实现边界必须保留？',
          options: [],
        }),
      ]),
      'agent.room.message': (request: ControlRequest) => {
        const body = request.body as Record<string, unknown>;
        return {
          ok: true,
          timelineEvents: [
            roomUserPostEvent(
              'room-a',
              2,
              'room-a:turn-1',
              String(body.clientMessageId),
              String(body.message),
            ),
          ],
        };
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const questionCard = within(await screen.findByRole('region', {
      name: '需要回答：还有哪些实现边界必须保留？',
    }));
    expect(questionCard.getByText('还有哪些实现边界必须保留？')).toBeInTheDocument();
    expect(questionCard.queryByRole('radio')).not.toBeInTheDocument();
    const answer = questionCard.getByRole('textbox', { name: /你的回答/ });
    await user.type(answer, '请保留现有 API，并补充错误状态。');
    await user.click(questionCard.getByRole('button', { name: '发送回答' }));

    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));
    const answerRequest = transport.requests.find(
      ({ request }) => request.pathId === 'agent.room.message',
    )?.request.body;
    expect(answerRequest).toMatchObject({
      message: '请保留现有 API，并补充错误状态。',
      attachmentIds: [],
      answerKind: 'custom',
      answerToPostId: 'room-a:question-1',
      answerToRootId: 'room-a:turn-1',
    });
    expect(answerRequest).not.toHaveProperty('workItemId');
    await waitFor(() => expect(
      within(screen.getByRole('region', { name: '需要回答：还有哪些实现边界必须保留？' }))
        .queryByRole('button', { name: '发送回答' }),
    ).not.toBeInTheDocument());
    const resolvedQuestion = within(screen.getByRole('region', { name: '需要回答：还有哪些实现边界必须保留？' }));
    expect(resolvedQuestion.getByText('已收到回答')).toBeInTheDocument();
    expect(resolvedQuestion.queryByText('已锁定')).not.toBeInTheDocument();
    expect(resolvedQuestion.queryByText('回答保留在下一条用户消息中')).not.toBeInTheDocument();
    expect(screen.getByText('请保留现有 API，并补充错误状态。').closest('.room-user-message')).toBeInTheDocument();
    expect(document.querySelectorAll('.room-user-message')).toHaveLength(1);
  });

  it('ignores optimistic-shaped and unrelated user events until the same Root publishes the accepted answer', async () => {
    const question = roomQuestionEvent('room-a', 1, {
      content: '需要你的确认。',
      prompt: '采用哪一种发布方式？',
      options: [{ value: 'preview', label: '预览版' }, { value: 'stable', label: '稳定版' }],
    });
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '权威回答 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        question,
        roomEvent('room-a', 2, 'user_message', {
          clientMessageId: 'optimistic-shaped',
          text: 'stable',
        }, { turnId: 'room-a:turn-1' }),
      ]),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByRole('region', { name: '需要回答：采用哪一种发布方式？' })).toBeInTheDocument();
    transport.emit(
      'agent.room.events',
      roomUserPostEvent('room-a', 3, 'room-a:unrelated-root', 'unrelated-answer', 'stable'),
    );
    await waitFor(() => expect(
      within(screen.getByRole('region', { name: '需要回答：采用哪一种发布方式？' }))
        .getByRole('button', { name: '其他' }),
    ).toBeInTheDocument());

    transport.emit(
      'agent.room.events',
      roomEvent('room-a', 4, 'user_message', {
        answerToPostId: 'room-a:question-1',
        clientMessageId: 'accepted-answer',
        displayText: '稳定版',
        messageId: 'room-a:user-answer-4',
        rootId: 'room-a:turn-1',
        text: 'stable',
      }, { turnId: 'room-a:turn-1' }),
    );
    await waitFor(() => expect(
      within(screen.getByRole('region', { name: '需要回答：采用哪一种发布方式？' }))
        .queryByRole('button', { name: '其他' }),
    ).not.toBeInTheDocument());
    const answeredQuestion = within(screen.getByRole('region', { name: '需要回答：采用哪一种发布方式？' }));
    expect(answeredQuestion.queryByText('已锁定')).not.toBeInTheDocument();
    expect(answeredQuestion.queryByText('回答保留在下一条用户消息中')).not.toBeInTheDocument();
    expect(screen.getByText('稳定版').closest('.room-user-message')).toBeInTheDocument();
    expect(document.querySelectorAll('.room-user-message')).toHaveLength(3);
  });
  it('never exposes a historical native participant question as a second Room answer surface', async () => {
    const groupedRequest = roomEvent('room-a', 1, 'participant_activity', {
      rootId: 'room-a:turn-1',
      dispatchId: 'room-a:dispatch-1',
      sourceEventId: 'room-a:s1:input:grouped-1',
      sourceEventType: 'user_input_required',
      requestId: 'input:grouped-1',
      requestKind: 'grouped_questions',
      method: 'editor',
      title: '需要你做几个选择',
      message: '请一起确认下面两件事，提交后伙伴会继续。',
      questions: [
        { id: 'scope', question: '先覆盖哪一部分？', options: ['核心流程', '完整流程'] },
        { id: 'review', question: '如何复核？', options: ['伙伴互查', '直接交付'] },
      ],
    }, {
      turnId: 'room-a:turn-1',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
    });
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '协作确认')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [groupedRequest]),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await waitFor(() => expect(document.querySelector('.room-composer')).toBeInTheDocument());
    expect(screen.queryByRole('region', { name: '需要你做几个选择' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '需要你做几个选择' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /立即选择|立即回答/ })).not.toBeInTheDocument();
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.session.ui.resolve'
      || request.pathId === 'agent.room.message'
    ))).toHaveLength(0);
  });

  it('keeps an inline question visible across Escape and a full reload', async () => {
    const question = roomQuestionEvent('room-a', 1, {
      content: '请选择发布方式，回答后我会继续。',
      prompt: '发布预览版还是稳定版？',
      options: [
        { value: 'preview', label: '预览版' },
        { value: 'stable', label: '稳定版', recommended: true },
      ],
    });
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '重载 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [question]),
    } });
    const user = userEvent.setup();
    const view = render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const questionName = '需要回答：发布预览版还是稳定版？';
    expect(await screen.findByRole('region', { name: questionName })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('region', { name: questionName })).toBeInTheDocument();
    expect(within(screen.getByLabelText('协作对话时间线')).getByText('请选择发布方式，回答后我会继续。')).toBeInTheDocument();
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.room.message')).toHaveLength(0);

    view.unmount();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const reloadedCard = within(await screen.findByRole('region', { name: questionName }));
    expect(reloadedCard.getByText('推荐')).toBeInTheDocument();
    expect(reloadedCard.getByRole('button', { name: '其他' })).toBeInTheDocument();
    expect(reloadedCard.queryByRole('button', { name: '发送回答' })).not.toBeInTheDocument();
    expect(reloadedCard.getByRole('button', { name: '确认并发送' })).toBeDisabled();
  });

  it('does not reopen a resolved question or fabricate choices for a legacy wait post', async () => {
    const structured = roomQuestionEvent('room-a', 1, {
      content: '先选择一个发布方式。',
      prompt: '选择发布方式',
      options: [
        { value: 'A', label: '方案 A' },
        { value: 'B', label: '方案 B' },
      ],
    });
    const legacy = roomTerminalPostEvent(
      'room-a',
      3,
      'wait',
      '请直接在对话中说明希望怎样继续。',
    );
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '已回答 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        structured,
        roomUserPostEvent('room-a', 2, 'room-a:turn-1', 'answered-question', 'B'),
        legacy,
      ]),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const timeline = within(screen.getByLabelText('协作对话时间线'));
    expect(await timeline.findByText('请直接在对话中说明希望怎样继续。')).toBeInTheDocument();
    expect(timeline.getByText('先选择一个发布方式。')).toBeInTheDocument();
    const answeredCard = within(timeline.getByRole('region', { name: '需要回答：选择发布方式' }));
    expect(answeredCard.queryByText('已锁定')).not.toBeInTheDocument();
    expect(answeredCard.queryByText('回答保留在下一条用户消息中')).not.toBeInTheDocument();
    expect(timeline.getByText('B').closest('.room-user-message')).toBeInTheDocument();
    expect(answeredCard.queryByRole('button', { name: '其他' })).not.toBeInTheDocument();
    expect(answeredCard.queryAllByRole('radio')).toHaveLength(0);
    expect(document.querySelectorAll('.room-question-option')).toHaveLength(0);
  });

  it('labels each terminal public post as a humane report', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '终态 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomTerminalPostEvent('room-a', 1, 'result', '交付已经完成。'),
        roomTerminalPostEvent('room-a', 2, 'handoff', '工作已经转交。'),
        roomTerminalPostEvent('room-a', 3, 'wait', '正在等待必要信息。'),
        roomTerminalPostEvent('room-a', 4, 'blocked', '当前被外部条件阻塞。'),
      ]),
    } });
    const { container } = render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><RoomsFeature /></TooltipProvider>
      </ControlTransportProvider>,
    );

    expect(await within(screen.getByLabelText('协作对话时间线')).findByText('交付已经完成。')).toBeInTheDocument();
    expect(screen.getByText('已交接给 澄·初')).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.room-agent-lane__post-kind')).map(
      (element) => element.textContent,
    )).toEqual(['最终答复', '交接说明', '等待说明', '遇到的问题']);
  });

  it('keeps lifecycle transitions and preserves each chronological public post', () => {
    const room = roomSummary('room-a', '单一汇报 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-report');
    projection.turnsById['turn-report'] = {
      id: 'turn-report',
      rootId: 'turn-report',
      status: 'completed',
      messageIds: ['progress-post', 'wait-post', 'result-post'],
      activityIds: [],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-report'],
      terminalDispatchIds: ['dispatch-report'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      dispatchParticipantIds: { 'dispatch-report': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 3,
    };
    for (const [index, message] of [
      { id: 'progress-post', text: '先同步一条公开进展' },
      { id: 'wait-post', text: '旧的等待说明', postKind: 'wait' as const },
      { id: 'result-post', text: '最终任务汇报', postKind: 'result' as const },
    ].entries()) {
      projection.messagesById[message.id] = {
        id: message.id,
        roomId: room.id,
        turnId: 'turn-report',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
        role: 'assistant',
        status: 'completed',
        text: message.text,
        projectionKind: 'post',
        rootId: 'turn-report',
        dispatchId: 'dispatch-report',
        ...(message.postKind ? { postKind: message.postKind } : {}),
        createdAtMs: index + 1,
        completedAtMs: index + 1,
      };
    }

    const { container } = render(
      <RoomTurn turnId="turn-report" room={room} projection={projection} personas={previewPersonas} />,
    );

    expect(screen.getByText('先同步一条公开进展')).toBeInTheDocument();
    expect(screen.getByText('最终任务汇报')).toBeInTheDocument();
    expect(screen.getByText('旧的等待说明')).toBeInTheDocument();
    expect(screen.getByText('正在等待继续条件')).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.room-agent-lane__post-kind')).map(
      (element) => element.textContent,
    )).toEqual(['进度更新', '等待说明', '最终答复']);
    expect(screen.getByText('这轮协作已完成')).toBeInTheDocument();
    expect(screen.getByText('运行结论')).toBeInTheDocument();
    expect(screen.getByText('1 项分工已经收束。已保留 2 条伙伴公开汇报，可在上方查看。')).toBeInTheDocument();
    expect(container.querySelector('.room-turn__terminal')).toHaveAttribute('data-state', 'completed');
  });

  it('preserves distinct conversational updates within one active dispatch', () => {
    const room = roomSummary('room-a', '工作轮 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-round');
    projection.turnsById['turn-round'] = {
      id: 'turn-round',
      rootId: 'turn-round',
      status: 'running',
      messageIds: ['progress-old', 'progress-current'],
      activityIds: [],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-round'],
      terminalDispatchIds: [],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      terminalParticipantIds: [],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      dispatchParticipantIds: { 'dispatch-round': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    for (const [index, text] of ['旧的过程播报', '正在核对可观察结果'].entries()) {
      const id = index === 0 ? 'progress-old' : 'progress-current';
      projection.messagesById[id] = {
        id,
        roomId: room.id,
        turnId: 'turn-round',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
        role: 'assistant',
        status: 'completed',
        text,
        projectionKind: 'post',
        rootId: 'turn-round',
        dispatchId: 'dispatch-round',
        postKind: 'progress',
        createdAtMs: index + 1,
        completedAtMs: index + 1,
      };
    }

    const { container } = render(
      <RoomTurn turnId="turn-round" room={room} projection={projection} personas={previewPersonas} />,
    );

    expect(screen.getByText('旧的过程播报')).toBeInTheDocument();
    expect(screen.getByText('正在核对可观察结果')).toBeInTheDocument();
    expect(container.querySelectorAll('.room-agent-lane__post')).toHaveLength(2);
  });


  it('shows one reporter final while preserving attributed participant contributions', () => {
    const room = roomSummary('room-a', '汇报人 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-reporter');
    projection.turnsById['turn-reporter'] = {
      id: 'turn-reporter',
      rootId: 'turn-reporter',
      status: 'completed',
      messageIds: ['participant-result', 'reporter-result-old', 'reporter-result-final'],
      activityIds: [],
      participantIds: ['room-a:p1', 'room-a:p2'],
      dispatchIds: ['dispatch-participant', 'dispatch-reporter'],
      terminalDispatchIds: ['dispatch-participant', 'dispatch-reporter'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      terminalParticipantIds: ['room-a:p1', 'room-a:p2'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      dispatchParticipantIds: {
        'dispatch-participant': 'room-a:p1',
        'dispatch-reporter': 'room-a:p2',
      },
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    for (const [index, message] of [
      {
        id: 'participant-result',
        participantId: 'room-a:p1',
        dispatchId: 'dispatch-participant',
        text: '参与者提交了可检查的工作结果',
        postKind: 'work_result' as const,
      },
      {
        id: 'reporter-result-old',
        participantId: 'room-a:p2',
        dispatchId: 'dispatch-reporter',
        text: '较早的汇报人总结',
        postKind: 'result' as const,
      },
      {
        id: 'reporter-result-final',
        participantId: 'room-a:p2',
        dispatchId: 'dispatch-reporter',
        text: '唯一最终汇报人总结',
        postKind: 'result' as const,
      },
    ].entries()) {
      projection.messagesById[message.id] = {
        id: message.id,
        roomId: room.id,
        turnId: 'turn-reporter',
        participantId: message.participantId,
        sourceSessionId: message.participantId === 'room-a:p2' ? 'room-a:s2' : 'room-a:s1',
        role: 'assistant',
        status: 'completed',
        text: message.text,
        projectionKind: 'post',
        rootId: 'turn-reporter',
        dispatchId: message.dispatchId,
        postKind: message.postKind,
        createdAtMs: index + 1,
        completedAtMs: index + 1,
      };
    }
    const root = {
      ...roomKernelRoot(room.id, 'completed', true, 4),
      rootId: 'turn-reporter',
      reporterParticipantId: 'room-a:p2',
    };

    const { container } = render(
      <RoomTurn
        turnId="turn-reporter"
        room={room}
        projection={projection}
        personas={previewPersonas}
        kernelRootsById={{ 'turn-reporter': root }}
      />,
    );

    expect(screen.getByText('唯一最终汇报人总结')).toBeInTheDocument();
    expect(screen.getByText('参与者提交了可检查的工作结果')).toBeInTheDocument();
    expect(screen.queryByText('较早的汇报人总结')).not.toBeInTheDocument();
    expect(screen.getByText('工作交付')).toBeInTheDocument();
    expect(screen.getByText('最终答复')).toBeInTheDocument();
    expect(container.querySelectorAll('.room-agent-lane__post[data-kind="result"]')).toHaveLength(1);
    expect(container.querySelectorAll('.room-agent-lane__post[data-kind="work_result"]')).toHaveLength(1);
    expect(screen.getByText('2 项分工已经收束。已保留 2 条伙伴公开汇报，可在上方查看。')).toBeInTheDocument();
  });
  it('uses only the runtime receipt for response provenance', () => {
    const room = roomSummary('room-a', '回复用量 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-usage');
    projection.turnsById['turn-usage'] = {
      id: 'turn-usage',
      rootId: 'turn-usage',
      status: 'completed',
      messageIds: ['post-usage'],
      activityIds: ['usage-activity'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-usage'],
      terminalDispatchIds: ['dispatch-usage'],
      terminalParticipantIds: ['room-a:p1'],
      dispatchParticipantIds: { 'dispatch-usage': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 3,
    };
    projection.messagesById['post-usage'] = {
      id: 'post-usage',
      roomId: room.id,
      turnId: 'turn-usage',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      role: 'assistant',
      status: 'completed',
      text: '已完成缓存验证。',
      projectionKind: 'post',
      rootId: 'turn-usage',
      dispatchId: 'dispatch-usage',
      postKind: 'result',
      createdAtMs: 2,
      completedAtMs: 2,
      message: {
        schemaVersion: 'rag-ime.agent-message.v1',
        id: 'self-reported-post',
        sessionId: 'room-a:s1',
        turnId: 'turn-usage',
        role: 'assistant',
        status: 'completed',
        blocks: [],
        attachments: [],
        citations: [],
        createdAtMs: 2,
        provider: 'self-reported-provider',
        model: 'self-reported-model',
        usage: { input: 9, output: 9, cacheRead: 9, cacheWrite: 9, totalTokens: 45 },
      },
    };
    projection.activitiesById['usage-activity'] = {
      id: 'usage-activity',
      turnId: 'turn-usage',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'completed',
      summary: '正在整理正式 Post',
      payload: {
        rootId: 'turn-usage',
        dispatchId: 'dispatch-usage',
        sourceEventType: 'message_completed',
        responsePostId: 'post-usage',
        runtimeTurnId: 'runtime:usage:1',
        provider: 'anthropic',
        model: 'claude-sonnet-4-5',
        usageReported: true,
        cacheUsageReported: true,
        usage: {
          input: 1_200,
          output: 80,
          cacheRead: 900,
          cacheWrite: 30,
          totalTokens: 2_210,
        },
      },
      createdAtMs: 3,
      updatedAtMs: 3,
    };

    const view = render(
      <RoomTurn turnId="turn-usage" room={room} projection={projection} personas={previewPersonas} />,
    );

    const usage = screen.getByLabelText(
      '输入 1200 tokens，输出 80 tokens，缓存读取 900 tokens，缓存写入 30 tokens',
    );
    expect(usage).toHaveAttribute('data-cache-hit', 'true');
    expect(usage).toHaveAttribute(
      'title',
      'input=1200, output=80, cacheRead=900, cacheWrite=30',
    );
    expect(screen.getByText('缓存命中 900')).toBeInTheDocument();
    expect(screen.getByText('anthropic · claude-sonnet-4-5')).toBeInTheDocument();
    expect(within(screen.getByLabelText('回复运行记录')).getByText('运行记录')).toBeInTheDocument();
    expect(screen.queryByText(/self-reported-provider|self-reported-model/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看本轮上下文' })).toHaveAttribute(
      'href',
      '#/context-debug?sessionId=room-a%3As1&turnId=runtime%3Ausage%3A1',
    );
    projection.activitiesById['usage-activity'] = {
      ...projection.activitiesById['usage-activity']!,
      payload: {
        ...projection.activitiesById['usage-activity']!.payload,
        cacheUsageReported: false,
      },
    };
    view.rerender(
      <RoomTurn turnId="turn-usage" room={room} projection={projection} personas={previewPersonas} />,
    );
    const noCacheEvidence = screen.queryByLabelText(
      '输入 1200 tokens，输出 80 tokens，缓存用量未上报',
    );
    expect(noCacheEvidence).not.toBeInTheDocument();
    expect(screen.queryByLabelText('回复运行记录')).not.toBeInTheDocument();


    projection.turnsById['turn-usage'] = {
      ...projection.turnsById['turn-usage']!,
      activityIds: [],
    };
    view.rerender(
      <RoomTurn turnId="turn-usage" room={room} projection={projection} personas={previewPersonas} />,
    );
    expect(screen.queryByText('本条回复未上报 Token / 缓存用量')).not.toBeInTheDocument();
    expect(screen.queryByText('模型 / Provider 未上报')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('回复运行记录')).not.toBeInTheDocument();
    expect(screen.queryByText(/self-reported-provider|self-reported-model/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '查看本轮上下文' })).not.toBeInTheDocument();
  });

  it('prefers complete response_evidence and falls back to complete legacy message evidence', () => {
    const room = roomSummary('room-a', '工具提交证据 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-tool-commit');
    projection.turnsById['turn-tool-commit'] = {
      id: 'turn-tool-commit',
      rootId: 'turn-tool-commit',
      status: 'completed',
      messageIds: ['post-tool-commit'],
      activityIds: ['tool-response-evidence', 'legacy-message-evidence'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-tool-commit'],
      terminalDispatchIds: ['dispatch-tool-commit'],
      terminalParticipantIds: ['room-a:p1'],
      dispatchParticipantIds: { 'dispatch-tool-commit': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 3,
    };
    projection.messagesById['post-tool-commit'] = {
      id: 'post-tool-commit',
      roomId: room.id,
      turnId: 'turn-tool-commit',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      role: 'assistant',
      status: 'completed',
      text: '工具提交已经完成。',
      projectionKind: 'post',
      rootId: 'turn-tool-commit',
      dispatchId: 'dispatch-tool-commit',
      postKind: 'result',
      createdAtMs: 2,
      completedAtMs: 2,
    };
    projection.activitiesById['tool-response-evidence'] = {
      id: 'tool-response-evidence',
      turnId: 'turn-tool-commit',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'completed',
      summary: '已保留工具提交的回复证据',
      payload: {
        rootId: 'turn-tool-commit',
        dispatchId: 'dispatch-tool-commit',
        sourceEventType: 'response_evidence',
        responsePostId: 'post-tool-commit',
        runtimeTurnId: 'runtime:tool-commit:1',
        provider: 'openai',
        model: 'gpt-5.6-luna',
        usageReported: true,
        cacheUsageReported: true,
        usage: {
          input: 640,
          output: 48,
          cacheRead: 512,
          cacheWrite: 16,
          totalTokens: 1_216,
        },
      },
      createdAtMs: 3,
      updatedAtMs: 3,
    };
    projection.activitiesById['legacy-message-evidence'] = {
      id: 'legacy-message-evidence',
      turnId: 'turn-tool-commit',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'completed',
      summary: '旧版回复证据',
      payload: {
        rootId: 'turn-tool-commit',
        dispatchId: 'dispatch-tool-commit',
        sourceEventType: 'message_completed',
        responsePostId: 'post-tool-commit',
        runtimeTurnId: 'runtime:legacy:1',
        provider: 'anthropic',
        model: 'claude-sonnet-4-5',
        usageReported: true,
        cacheUsageReported: true,
        usage: {
          input: 320,
          output: 24,
          cacheRead: 128,
          cacheWrite: 8,
          totalTokens: 480,
        },
      },
      createdAtMs: 4,
      updatedAtMs: 4,
    };

    const view = render(
      <RoomTurn
        turnId="turn-tool-commit"
        room={room}
        projection={projection}
        personas={previewPersonas}
      />,
    );

    expect(screen.getByText('openai · gpt-5.6-luna')).toBeInTheDocument();
    expect(screen.getByLabelText(
      '输入 640 tokens，输出 48 tokens，缓存读取 512 tokens，缓存写入 16 tokens',
    )).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看本轮上下文' })).toHaveAttribute(
      'href',
      '#/context-debug?sessionId=room-a%3As1&turnId=runtime%3Atool-commit%3A1',
    );

    projection.turnsById['turn-tool-commit'] = {
      ...projection.turnsById['turn-tool-commit']!,
      activityIds: ['legacy-message-evidence', 'tool-response-evidence'],
    };
    projection.activitiesById['tool-response-evidence'] = {
      ...projection.activitiesById['tool-response-evidence']!,
      payload: {
        ...projection.activitiesById['tool-response-evidence']!.payload,
        provider: '',
      },
    };
    view.rerender(
      <RoomTurn
        turnId="turn-tool-commit"
        room={room}
        projection={projection}
        personas={previewPersonas}
      />,
    );

    expect(screen.getByText('anthropic · claude-sonnet-4-5')).toBeInTheDocument();
    expect(screen.getByLabelText(
      '输入 320 tokens，输出 24 tokens，缓存读取 128 tokens，缓存写入 8 tokens',
    )).toBeInTheDocument();
    expect(screen.queryByText('gpt-5.6-luna')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看本轮上下文' })).toHaveAttribute(
      'href',
      '#/context-debug?sessionId=room-a%3As1&turnId=runtime%3Alegacy%3A1',
    );
  });

  it('turns a terminal blocked Post into a clear final response', () => {
    const room = roomSummary('room-a', '阻塞结果 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-blocked');
    projection.turnsById['turn-blocked'] = {
      id: 'turn-blocked',
      rootId: 'turn-blocked',
      status: 'completed',
      messageIds: ['blocked-post'],
      activityIds: [],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-blocked'],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      terminalDispatchIds: ['dispatch-blocked'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: { 'dispatch-blocked': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.messagesById['blocked-post'] = {
      id: 'blocked-post',
      roomId: room.id,
      turnId: 'turn-blocked',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      role: 'assistant',
      status: 'completed',
      text: '缺少发布凭据，当前无法继续。',
      projectionKind: 'post',
      postKind: 'blocked',
      rootId: 'turn-blocked',
      dispatchId: 'dispatch-blocked',
      createdAtMs: 1,
      completedAtMs: 2,
    };

    const { container } = render(
      <RoomTurn turnId="turn-blocked" room={room} projection={projection} personas={previewPersonas} />,
    );

    expect(screen.getByText('这轮协作受阻')).toBeInTheDocument();
    expect(screen.getByText('1 项分工报告阻塞。已保留 1 条伙伴公开汇报，可在上方查看。')).toBeInTheDocument();
    expect(container.querySelector('.room-turn__terminal')).toHaveAttribute('data-state', 'blocked');
    expect(container.querySelector('.room-agent-lane')).toHaveAttribute('data-outcome', 'blocked');
  });

  it('summarizes a long terminal report before revealing the full text', async () => {
    const room = roomSummary('room-a', '长汇报 Room');
    const projection = createRoomProjection(room.id);
    const longReport = [
      '只读验收完成，未修改任何文件。',
      '命令回执与边界检查均已通过；所有公开结果都保留在受管工作目录中。',
      '第一项检查覆盖入口、键盘交互、移动端断点和无障碍状态。',
      '第二项检查覆盖测试、静态语法、产物目录与最终验收责任。',
      `${'验收补充说明仍在继续。'.repeat(20)}仅在完整汇报中显示的最终标记。`,
    ].join('\n\n');
    projection.turnOrder.push('turn-report');
    projection.turnsById['turn-report'] = {
      id: 'turn-report',
      status: 'completed',
      messageIds: ['result-post'],
      activityIds: [],
      participantIds: ['room-a:p1'],
      terminalParticipantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.messagesById['result-post'] = {
      id: 'result-post',
      roomId: room.id,
      turnId: 'turn-report',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      role: 'assistant',
      status: 'completed',
      text: longReport,
      projectionKind: 'post',
      postKind: 'result',
      createdAtMs: 1,
      completedAtMs: 2,
    };
    const user = userEvent.setup();
    const { container } = render(
      <RoomTurn turnId="turn-report" room={room} projection={projection} personas={previewPersonas} />,
    );
    const report = container.querySelector<HTMLDetailsElement>('.room-agent-lane__report')!;

    expect(report).not.toHaveAttribute('open');
    expect(within(report).getByText('最终答复')).toBeInTheDocument();
    expect(within(report).getByText(/只读验收完成/)).toBeInTheDocument();
    expect(within(report).queryByText(/最终标记/)).not.toBeInTheDocument();
    await user.click(within(report).getByText('查看完整汇报'));
    expect(report).toHaveAttribute('open');
    expect(within(report).getByText(/最终标记/)).toBeInTheDocument();
  });

  it('keeps a superseded question in history and allows only the newest question to answer', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '实时澄清 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', []),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    await screen.findByText('还没有公开消息');

    transport.emit('agent.room.events', roomQuestionEvent('room-a', 1, {
      content: '第一项澄清',
      prompt: '较早的问题',
      options: [{ value: 'A', label: 'A' }, { value: 'B', label: 'B' }],
    }));
    transport.emit('agent.room.events', roomQuestionEvent('room-a', 2, {
      content: '第二项澄清',
      prompt: '最新的问题',
      options: [{ value: 'C', label: 'C' }, { value: 'D', label: 'D' }],
    }));

    const latestCard = within(await screen.findByRole('region', { name: '需要回答：最新的问题' }));
    const supersededCard = within(screen.getByRole('region', { name: '需要回答：较早的问题' }));
    expect(latestCard.getAllByRole('radio')).toHaveLength(2);
    expect(latestCard.getByRole('button', { name: '其他' })).toBeInTheDocument();
    expect(supersededCard.getByText('这项问题已由后续问题替代。')).toBeInTheDocument();
    expect(supersededCard.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('imports a pasted PNG into the Room owner and sends its managed receipt once', async () => {
    const transport = new MockControlTransport({
      importedFiles: [{
        id: 'media_room_attachment01',
        name: 'diagram.png',
        mimeType: 'image/png',
        byteSize: 128,
        roomId: 'room-a',
        sha256: 'a'.repeat(64),
      }],
      routes: {
        'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '图片 Room')] },
        'agent.roles.list': { ok: true, items: previewPersonas },
        'agent.room.snapshot': roomSnapshot('room-a', []),
        'agent.room.message': { ok: true },
      },
    });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    const image = new File(['png'], 'diagram.png', { type: 'image/png' });
    fireEvent.paste(composer, {
      clipboardData: { files: [image], items: [], getData: () => '' },
    });
    expect(await screen.findByLabelText('移除图片：diagram.png')).toBeInTheDocument();
    expect(transport.imagePasteCalls).toEqual([expect.objectContaining({
      roomId: 'room-a',
      maxFiles: 1,
    })]);
    fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));
    const request = transport.requests.find(({ request }) => request.pathId === 'agent.room.message')?.request;
    expect(request?.body).toMatchObject({
      message: '请查看附件。',
      attachmentIds: ['media_room_attachment01'],
    });
  });

  it('keeps a late image import with the Room that started the paste', async () => {
    const pendingPaste = deferred<PickedFile[]>();
    const transport = new MockControlTransport({
      importedFiles: [],
      routes: {
        'agent.rooms.list': { ok: true, items: [roomSummary('room-a', 'Room A'), roomSummary('room-b', 'Room B')] },
        'agent.roles.list': { ok: true, items: previewPersonas },
        'agent.room.snapshot': (request: ControlRequest) => roomSnapshot(String(request.params?.roomId ?? ''), []),
      },
    });
    vi.spyOn(transport, 'pasteImages').mockImplementation(() => pendingPaste.promise);
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    fireEvent.paste(composer, {
      clipboardData: {
        files: [new File(['png'], 'late.png', { type: 'image/png' })],
        items: [],
        getData: () => '',
      },
    });
    await user.click(screen.getByRole('button', { name: '打开协作空间：Room B' }));
    pendingPaste.resolve([{
      id: 'media_room_late_image01',
      name: 'late.png',
      mimeType: 'image/png',
      byteSize: 128,
      roomId: 'room-a',
      sha256: 'b'.repeat(64),
    }]);
    await waitFor(() => expect(transport.pasteImages).toHaveBeenCalledTimes(1));
    expect(screen.queryByLabelText('移除图片：late.png')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '打开协作空间：Room A' }));
    expect(await screen.findByLabelText('移除图片：late.png')).toBeInTheDocument();
  });

  it('keeps newer attachment receipts ahead of restored receipts when a pending send fails', async () => {
    const pendingSend = deferred<{ ok: true }>();
    const submitted = [
      pickedRoomImage('media_room_submitted_a', 'submitted-a.png', 'a'),
      pickedRoomImage('media_room_submitted_b', 'submitted-b.png', 'b'),
    ];
    const addedWhilePending = [
      pickedRoomImage('media_room_submitted_a', 'newer-duplicate.png', 'c'),
      ...Array.from({ length: 6 }, (_, index) => pickedRoomImage(
        `media_room_new_image_${index + 2}`,
        `new-${index + 2}.png`,
        String(index + 2),
      )),
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '附件恢复 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.message': () => pendingSend.promise,
    } });
    vi.spyOn(transport, 'pasteImages')
      .mockResolvedValueOnce(submitted)
      .mockResolvedValueOnce(addedWhilePending);
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: '协作消息' });

    fireEvent.paste(composer, {
      clipboardData: {
        files: [new File(['png'], 'submitted.png', { type: 'image/png' })],
        items: [],
        getData: () => '',
      },
    });
    expect(await screen.findByLabelText('移除图片：submitted-a.png')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));

    fireEvent.paste(composer, {
      clipboardData: {
        files: [new File(['png'], 'newer.png', { type: 'image/png' })],
        items: [],
        getData: () => '',
      },
    });
    expect(await screen.findByLabelText('移除图片：new-7.png')).toBeInTheDocument();
    pendingSend.reject(new Error('send failed'));
    await screen.findByRole('alert');

    const restored = within(screen.getByLabelText('待发送图片'))
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label'));
    expect(restored).toEqual([
      '移除图片：newer-duplicate.png',
      '移除图片：new-2.png',
      '移除图片：new-3.png',
      '移除图片：new-4.png',
      '移除图片：new-5.png',
      '移除图片：new-6.png',
      '移除图片：new-7.png',
      '移除图片：submitted-b.png',
    ]);
  });

  it('shows the user message and routing lane before the server accepts the send', async () => {
    const pending = deferred<{ ok: true }>();
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '即时反馈 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.message': () => pending.promise,
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '发送后不能空白等待');
    await user.click(screen.getByRole('button', { name: '发送消息' }));

    expect(screen.getByText('发送后不能空白等待')).toBeInTheDocument();
    expect(screen.getByText('正在选择伙伴')).toBeInTheDocument();
    expect(screen.getAllByText('正在发送').length).toBeGreaterThan(0);
    expect(composer).toHaveValue('');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true);

    pending.resolve({ ok: true });
  });

  it('keeps task ingress AI-owned without a second manual start form', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '需求对齐 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', []),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await screen.findByText('还没有公开消息');
    expect(screen.queryByRole('button', { name: '确认任务' })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '把任务说清楚' })).not.toBeInTheDocument();
    expect(screen.queryByText('先聊清楚再开工')).not.toBeInTheDocument();
    expect(transport.requests.some(
      ({ request }) => request.pathId === 'agent.room.workItem.create',
    )).toBe(false);
  });

  it('retains an in-flight Room turn while navigating between Rooms', async () => {
    const pendingSend = deferred<{ ok: true }>();
    const pendingRefresh = deferred<ReturnType<typeof roomSnapshot>>();
    let roomASnapshotCalls = 0;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': {
        ok: true,
        items: [roomSummary('room-a', 'Room A'), roomSummary('room-b', 'Room B')],
      },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': (request: ControlRequest) => {
        if (request.params?.roomId === 'room-b') return roomSnapshot('room-b', []);
        roomASnapshotCalls += 1;
        return roomASnapshotCalls === 1 ? roomSnapshot('room-a', []) : pendingRefresh.promise;
      },
      'agent.room.message': () => pendingSend.promise,
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '切换页面也要看得到我');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    expect(screen.getByText('切换页面也要看得到我')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开协作空间：Room B' }));
    await screen.findByText('还没有公开消息');
    await user.click(screen.getByRole('button', { name: '打开协作空间：Room A' }));

    expect(await screen.findByText('切换页面也要看得到我')).toBeInTheDocument();
    expect(screen.getByText('正在选择伙伴')).toBeInTheDocument();
    pendingRefresh.resolve(roomSnapshot('room-a', []));
    await waitFor(() => expect(roomASnapshotCalls).toBe(2));
    expect(screen.getByText('切换页面也要看得到我')).toBeInTheDocument();

    pendingSend.resolve({ ok: true });
  });

  it('deduplicates a rapid send and keeps late failure state inside its source Room', async () => {
    const pendingA = deferred<{ ok: true }>();
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': {
        ok: true,
        items: [roomSummary('room-a', 'Room A'), roomSummary('room-b', 'Room B')],
      },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': (request: ControlRequest) => roomSnapshot(
        String(request.params?.roomId ?? ''),
        [],
      ),
      'agent.room.message': (request: ControlRequest) => (
        request.params?.roomId === 'room-a' ? pendingA.promise : { ok: true }
      ),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, 'A 只应发送一次');
    const send = screen.getByRole('button', { name: '发送消息' });
    fireEvent.click(send);
    fireEvent.click(send);
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.room.message' && request.params?.roomId === 'room-a'
    ))).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '打开协作空间：Room B' }));
    const roomBComposer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(roomBComposer, 'B 可以独立发送');
    await user.click(screen.getByRole('button', { name: '发送消息' }));
    await user.type(roomBComposer, 'B 的未发送草稿');
    expect(transport.requests.filter(({ request }) => (
      request.pathId === 'agent.room.message' && request.params?.roomId === 'room-b'
    ))).toHaveLength(1);

    pendingA.reject(new Error('late Room A rejection'));
    await waitFor(() => expect(roomBComposer).toHaveValue('B 的未发送草稿'));
    expect(screen.queryByText('A 只应发送一次')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开协作空间：Room A' }));
    expect(await screen.findByRole('textbox', { name: '协作消息' })).toHaveValue('A 只应发送一次');
    expect(await screen.findByRole('alert')).toHaveTextContent('消息暂时未发送，请稍后重试。');
  });

  it('removes an optimistic message and restores the draft when the real API rejects it', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '失败恢复协作空间')] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.message': () => {
        throw new Error('POST /api/agent/rooms/room-a/messages failed: receipt=/tmp/private.json');
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '不要留下假的乐观消息');
    await user.click(screen.getByRole('button', { name: '发送消息' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('消息暂时未发送，请稍后重试。');
    expect(alert).not.toHaveTextContent('/api/');
    expect(alert).not.toHaveTextContent('receipt');
    expect(alert).not.toHaveTextContent('/tmp/');
    expect(composer).toHaveValue('不要留下假的乐观消息');
    expect(document.querySelector('.room-user-message')).not.toBeInTheDocument();
  });

  it('creates a user-configured Room through the returned role catalog and selects the real response', async () => {
    const userCreatedPersona = {
      ...previewPersonas[2]!,
      roleId: 'persona-morning-guide',
      version: '1',
      displayName: '澄·晨光',
      tagline: '先看清今天，再稳稳向前',
      selectableModes: ['assistant', 'coordinator'] as ['assistant', 'coordinator'],
    };
    const roleCatalog = [userCreatedPersona, previewPersonas[0]!];
    const created = {
      ...roomSummary('room-created', '发布前检查'),
      participants: roleCatalog.map((persona, index) => ({
        id: `room-created:p${index + 1}`,
        sessionId: `room-created:s${index + 1}`,
        roleId: persona.roleId,
        roleVersion: persona.version,
        displayName: persona.displayName,
        status: 'active',
        ordinal: index,
      })),
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: roleCatalog },
      'agent.sessions.list': { ok: true, items: [{ id: 'existing', mode: 'coordinator', workspaceRoots: ['/Volumes/work/learnA'] }] },
      'agent.rooms.create': { ok: true, room: created },
      'agent.room.snapshot': roomSnapshot('room-created', [], '发布前检查'),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const create = await screen.findByRole('button', { name: '开始新的协作' });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    await user.type(screen.getByRole('textbox', { name: '协作空间名称' }), '发布前检查');
    await user.click(screen.getByRole('button', { name: '开始协作' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.rooms.create')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.rooms.create')?.request;
    expect(request?.body).toEqual({
      title: '发布前检查',
      roomKind: 'collaboration',
      avatar: 'briefcase',
      description: '',
      scenarioPrompt: '',
      participants: roleCatalog.map((persona, index) => ({
        roleId: persona.roleId,
        roleVersion: persona.version,
        displayName: persona.displayName,
        collaborationRole: index === 0 ? 'coordinator' : 'implementer',
      })),
      routingConfig: {
        maxResponders: 1,
        naturalJitter: 0,
        fallbackParticipantId: '',
      },
      routingPolicy: 'parallel',
      workspaceRoots: ['/Volumes/work/learnA'],
      executionMode: 'workspace_managed',
      workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE',
    });
    expect(await screen.findByRole('button', { name: '打开协作空间：发布前检查' })).toHaveAttribute('aria-current', 'true');
    expect(screen.queryByRole('dialog', { name: '开始一起做事' })).not.toBeInTheDocument();
  });

  it('requires a project path and preselects a useful collaboration ensemble', async () => {
    const transport = new MockControlTransport({
      pickedFiles: [{ id: 'workspace', name: 'learnA', mimeType: 'inode/directory', byteSize: 0, path: '/Volumes/work/learnA' }],
      routes: {
        'agent.rooms.list': { ok: true, items: [] },
        'agent.roles.list': { ok: true, items: previewPersonas },
        'agent.sessions.list': { ok: true, items: [] },
      },
    });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '开始新的协作' }));
    expect(screen.getByRole('button', { name: '开始协作' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /澄·远/ })).toHaveAccessibleName(/澄·远.*主持整合与回复/);
    expect(screen.getByRole('checkbox', { name: /澄·远/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·今/ })).toHaveAccessibleName(/澄·今.*实现与验证/);
    expect(screen.getByRole('checkbox', { name: /澄·今/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·初/ })).toHaveAccessibleName(/澄·初.*最终独立复核/);
    expect(screen.getByText(/主持整合者负责拆分、集成和最终回复/)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /澄·初/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·瞬/ })).toHaveAccessibleName(/澄·瞬.*可邀请/);
    expect(screen.queryByRole('combobox', { name: '主持伙伴' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '发言方式' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '选择工作目录' }));
    expect(transport.filePickCalls).toEqual([{
      purpose: 'workspace-root',
      selection: 'directory',
      multiple: false,
      maxFiles: 1,
    }]);
    expect(screen.getAllByText('/Volumes/work/learnA').length).toBeGreaterThan(0);
  });

  it('creates a roleplay Room without forcing a workspace or coordinator mode', async () => {
    const created = {
      ...roomSummary('room-roleplay', '深夜茶话会'),
      roomKind: 'roleplay' as const,
      executionMode: 'per_action' as const,
      avatar: 'sparkles',
      scenarioPrompt: '场景在安静的茶室。',
      routingPolicy: 'natural' as const,
      workspaceRoots: [],
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.sessions.list': { ok: true, items: [] },
      'agent.rooms.create': { ok: true, room: created },
      'agent.room.snapshot': roomSnapshot('room-roleplay', [], '深夜茶话会'),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '开始新的协作' }));
    await user.click(screen.getByRole('radio', { name: /一起聊聊/ }));
    expect(screen.queryByRole('button', { name: '选择工作目录' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '允许伙伴怎样工作' })).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: '协作空间名称' }), '深夜茶话会');
    await user.click(screen.getByText('补充背景与外观'));
    await user.type(screen.getByRole('textbox', { name: '共同背景' }), '场景在安静的茶室。');
    await user.click(screen.getByRole('button', { name: '开始群聊' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.rooms.create')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.rooms.create')?.request.body).toMatchObject({
      title: '深夜茶话会',
      roomKind: 'roleplay',
      avatar: 'sparkles',
      scenarioPrompt: '场景在安静的茶室。',
      routingPolicy: 'natural',
      workspaceRoots: [],
      executionMode: 'per_action',
      routingConfig: { maxResponders: 1, naturalJitter: 0.04, fallbackParticipantId: '' },
    });
  });

  it('restores the collaboration permission default whenever the create dialog reopens', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.sessions.list': { ok: true, items: [] },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '开始新的协作' }));
    await user.click(screen.getByRole('radio', { name: /一起聊聊/ }));
    expect(screen.queryByRole('group', { name: '允许伙伴怎样工作' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '先不开始' }));

    await user.click(screen.getByRole('button', { name: '开始新的协作' }));
    expect(screen.getByRole('radio', { name: /一起完成任务/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /工作区托管/ })).toBeChecked();
  });

  it('sends an invite-only turn with a visible mention and structured participant id', async () => {
    const invitedRoom = {
      ...roomSummary('room-invite', '点名茶话会'),
      roomKind: 'roleplay' as const,
      routingPolicy: 'invite_only' as const,
      workspaceRoots: [],
    };
    const snapshot = roomSnapshot('room-invite', [], '点名茶话会');
    snapshot.room.roomKind = invitedRoom.roomKind;
    snapshot.room.routingPolicy = invitedRoom.routingPolicy;
    snapshot.room.workspaceRoots = invitedRoom.workspaceRoots;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [invitedRoom] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.message': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '说说你的看法');
    expect(screen.getByRole('button', { name: '发送消息' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '点名一位伙伴' }));
    await user.click(screen.getByRole('option', { name: /澄·初/ }));
    expect(composer).toHaveValue('说说你的看法 @澄·初 ');
    await user.click(screen.getByRole('button', { name: '发送消息' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '说说你的看法 @澄·初',
      participantIds: ['room-invite:p2'],
    });
    expect(composer).toHaveValue('');
  });

  it('opens an avatar mention menu when typing at-sign and routes the chosen Agent', async () => {
    const invitedRoom = {
      ...roomSummary('room-mention', '点名协作'),
      routingPolicy: 'invite_only' as const,
    };
    const snapshot = roomSnapshot('room-mention', [], '点名协作');
    snapshot.room.routingPolicy = 'invite_only';
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [invitedRoom] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.message': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '@初');
    expect(await screen.findByRole('option', { name: /澄·初/ })).toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(composer).toHaveValue('@澄·初 ');

    await user.type(composer, '核对记忆召回{Enter}');
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '@澄·初 核对记忆召回',
      participantIds: ['room-mention:p2'],
    });
  });

  it('keeps every explicit mention when dispatching a DuoAgent turn', async () => {
    const duoRoom = {
      ...roomSummary('room-duo', '双 Agent 核对'),
      routingPolicy: 'natural' as const,
    };
    const snapshot = roomSnapshot('room-duo', [], '双 Agent 核对');
    snapshot.room.routingPolicy = 'natural';
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [duoRoom] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.message': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '@澄 @澄·初 分别检查实现和证据');
    await user.click(screen.getByRole('button', { name: '发送消息' }));

    await waitFor(() => expect(
      transport.requests.some((call) => call.request.pathId === 'agent.room.message'),
    ).toBe(true));
    expect(
      transport.requests.find((call) => call.request.pathId === 'agent.room.message')
        ?.request.body,
    ).toMatchObject({
      message: '@澄 @澄·初 分别检查实现和证据',
      participantIds: ['room-duo:p1', 'room-duo:p2'],
    });
  });

  it('saves Room settings as future-turn configuration without changing its kind', async () => {
    const room = {
      ...roomSummary('room-settings', '旧名称'),
      roomKind: 'roleplay' as const,
      description: '旧简介',
      scenarioPrompt: '旧设定',
      routingPolicy: 'natural' as const,
      workspaceRoots: [],
    };
    const updated = { ...room, title: '新名称', description: '新简介', scenarioPrompt: '新设定' };
    const snapshot = roomSnapshot(room.id, [], room.title);
    snapshot.room.roomKind = room.roomKind;
    snapshot.room.description = room.description;
    snapshot.room.scenarioPrompt = room.scenarioPrompt;
    snapshot.room.routingPolicy = room.routingPolicy;
    snapshot.room.workspaceRoots = room.workspaceRoots;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.archive': { ok: true, room: updated },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '设置这个协作空间' }));
    expect(screen.getByRole('button', { name: '保存更改' })).toBeDisabled();
    await user.clear(screen.getByRole('textbox', { name: '协作空间名称' }));
    await user.type(screen.getByRole('textbox', { name: '协作空间名称' }), '新名称');
    await user.clear(screen.getByRole('textbox', { name: '协作空间简介' }));
    await user.type(screen.getByRole('textbox', { name: '协作空间简介' }), '新简介');
    expect(screen.queryByRole('combobox', { name: '工作权限' })).not.toBeInTheDocument();
    await user.clear(screen.getByRole('textbox', { name: '共同背景' }));
    await user.type(screen.getByRole('textbox', { name: '共同背景' }), '新设定');
    await user.click(screen.getByRole('button', { name: '保存更改' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request;
    expect(request).toMatchObject({
      params: { roomId: room.id },
      body: {
        title: '新名称',
        description: '新简介',
        scenarioPrompt: '新设定',
        routingPolicy: room.routingPolicy,
      },
    });
    expect(request?.body).not.toHaveProperty('roomKind');
  });

  it('switches every Room participant to Luna-arbitrated full automation through the Room policy route', async () => {
    const room = roomSummary('room-permissions', '持续开发 Room');
    const fullTrustRoom = { ...room, executionMode: 'full_trust' as const };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot(room.id, [], room.title),
      'agent.room.archive': (request: ControlRequest) => (
        request.body as { executionMode?: string } | undefined
      )?.executionMode === 'full_trust'
        ? { ok: true, room: fullTrustRoom }
        : { ok: true, room },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '设置这个协作空间' }));
    await user.click(screen.getByRole('combobox', { name: '工作权限' }));
    await user.click(await screen.findByRole('option', { name: '全自动' }));
    expect(screen.getByText('所有待审批操作由独立审批助手（Luna Max）依据整个协作空间的审批记录自动判定')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '保存更改' }));

    await waitFor(() => expect(
      transport.requests.filter((call) => call.request.pathId === 'agent.room.archive'),
    ).toHaveLength(1));
    const permissionRequest = transport.requests
      .find((call) => call.request.pathId === 'agent.room.archive')
      ?.request;
    expect(permissionRequest).toMatchObject({
      params: { roomId: room.id },
      body: {
        title: room.title,
        avatar: 'briefcase',
        description: '',
        scenarioPrompt: '',
        routingPolicy: room.routingPolicy,
        executionMode: 'full_trust',
        dangerousModeConfirmation: 'ENABLE_FULL_TRUST',
      },
    });
  });

  it('adds 澄·远 to an existing Room and can remove the member again', async () => {
    const initial = roomSummary('room-members', '成员管理 Room');
    const futurePersona = previewPersonas.find((persona) => persona.roleId === 'companion-future-v1')!;
    const futureParticipant = {
      id: 'room-members:p3', sessionId: 'room-members:s3', roleId: 'companion-future-v1', roleVersion: '1',
      displayName: '澄·远', collaborationRole: 'implementer' as const, status: 'active', ordinal: 2,
    };
    const withFuture = { ...initial, participants: [...initial.participants, futureParticipant] };
    const afterRemoval = {
      ...initial,
      participants: [...initial.participants, { ...futureParticipant, status: 'removed' }],
    };
    let addCompleted = false;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [initial] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot(initial.id, [], initial.title),
      'agent.room.participant.add': () => {
        addCompleted = true;
        return { ok: true, room: withFuture, participant: futureParticipant };
      },
      'agent.room.participant.remove': { ok: true, room: afterRemoval, participant: { ...futureParticipant, status: 'removed' } },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '设置这个协作空间' }));
    const invite = screen.getByRole('button', { name: `邀请 ${futurePersona.displayName}` });
    expect(invite).toBeEnabled();
    expect(screen.getByText(/不会补读此前的完整对话/)).toBeInTheDocument();
    await user.click(invite);

    await waitFor(() => expect(addCompleted).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.add')?.request).toMatchObject({
      params: { roomId: initial.id },
      body: { roleId: 'companion-future-v1', roleVersion: '1', collaborationRole: 'implementer' },
    });
    const remove = await screen.findByRole('button', { name: '移出 澄·远' });
    expect(remove).toBeEnabled();
    await user.click(remove);
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.participant.remove')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.remove')?.request).toMatchObject({
      params: { roomId: initial.id },
      body: { participantId: 'room-members:p3' },
    });
  });

  it('changes a collaboration member job for future dispatches', async () => {
    const room = roomSummary('room-jobs', '岗位设置 Room');
    const target = room.participants[1];
    const updatedParticipant = { ...target, collaborationRole: 'reviewer' as const };
    const updated = {
      ...room,
      participants: room.participants.map((item) => item.id === target.id ? updatedParticipant : item),
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot(room.id, [], room.title),
      'agent.room.participant.update': { ok: true, room: updated, participant: updatedParticipant },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '设置这个协作空间' }));
    await user.click(screen.getByRole('combobox', { name: `${target.displayName} 负责什么` }));
    await user.click(screen.getByRole('option', { name: '最终独立复核' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.participant.update')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.update')?.request).toMatchObject({
      params: { roomId: room.id },
      body: { participantId: target.id, collaborationRole: 'reviewer' },
    });
    expect(screen.getByRole('combobox', { name: `${target.displayName} 负责什么` })).toHaveTextContent('最终独立复核');
  });

  it('permanently deletes only an archived Room after exact-title confirmation', async () => {
    const room = { ...roomSummary('room-delete', '废弃协作 Room'), status: 'archived' };
    const snapshot = roomSnapshot(room.id, [], room.title);
    snapshot.room.status = 'archived';
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.delete': { ok: true, roomId: room.id },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '设置这个协作空间' }));
    await user.click(screen.getByRole('button', { name: '删除协作空间' }));
    const confirm = screen.getByRole('textbox', { name: '输入协作空间名称确认永久删除' });
    const submit = screen.getByRole('button', { name: '永久删除' });
    expect(submit).toBeDisabled();
    await user.type(confirm, room.title);
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.delete')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.delete')?.request).toMatchObject({
      params: { roomId: room.id },
      body: { confirmTitle: room.title },
    });
    expect(screen.queryByRole('button', { name: `打开协作空间：${room.title}` })).not.toBeInTheDocument();
  });

  it('renders the updated topic projection returned by the preview transport', async () => {
    const transport = createPreviewTransport();
    const user = userEvent.setup();
    render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><RoomsFeature /></TooltipProvider>
      </ControlTransportProvider>,
    );

    await user.click(await screen.findByRole('button', { name: '管理话题' }));
    await user.type(screen.getByRole('textbox', { name: '话题名称' }), '发布风险');
    await user.type(screen.getByRole('textbox', { name: '话题摘要' }), '核对上线边界');
    await user.click(screen.getByRole('button', { name: '创建话题' }));

    await waitFor(() => {
      expect(within(screen.getByRole('dialog', { name: '整理话题' })).getByText('发布风险'))
        .toBeInTheDocument();
    });
    expect(screen.queryByText('服务端没有返回更新后的话题')).not.toBeInTheDocument();
  });

  it('creates an independent topic and adds a workspace-scoped shared artifact', async () => {
    const room = {
      ...roomSummary('room-context', '上下文 Room'),
      roomKind: 'collaboration' as const,
      activeTopicId: 'topic:default',
      topics: [
        { id: 'topic:default', roomId: 'room-context', title: '默认话题', summary: '', status: 'active' as const, ordinal: 0, createdAtMs: 1, updatedAtMs: 1 },
      ],
      artifacts: [],
    };
    const withTopic = {
      ...room,
      activeTopicId: 'topic:risk',
      topics: [
        ...room.topics,
        { id: 'topic:risk', roomId: room.id, title: '发布风险', summary: '核对上线边界', status: 'active' as const, ordinal: 1, createdAtMs: 2, updatedAtMs: 2 },
      ],
    };
    const withArtifact = {
      ...withTopic,
      artifacts: [
        { id: 'artifact:report', roomId: room.id, topicId: 'topic:risk', displayName: 'report.md', path: '/Volumes/work/learnA/report.md', mediaType: 'text/markdown', status: 'active' as const, createdAtMs: 3, updatedAtMs: 3 },
      ],
    };
    const snapshot = roomSnapshot(room.id, [], room.title);
    snapshot.room.roomKind = room.roomKind;
    snapshot.room.activeTopicId = room.activeTopicId;
    snapshot.room.topics = room.topics;
    snapshot.room.artifacts = room.artifacts;
    const transport = new MockControlTransport({
      pickedFiles: [{ id: 'report', name: 'report.md', mimeType: 'text/markdown', byteSize: 100, path: '/Volumes/work/learnA/report.md' }],
      routes: {
        'agent.rooms.list': { ok: true, items: [room] },
        'agent.roles.list': { ok: true, items: previewPersonas },
        'agent.room.snapshot': snapshot,
        'agent.room.topic.create': { ok: true, room: withTopic },
        'agent.room.artifact.add': { ok: true, room: withArtifact },
      },
    });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '管理话题' }));
    await user.type(screen.getByRole('textbox', { name: '话题名称' }), '发布风险');
    await user.type(screen.getByRole('textbox', { name: '话题摘要' }), '核对上线边界');
    await user.click(screen.getByRole('button', { name: '创建话题' }));
    await waitFor(() => expect(screen.getAllByText('发布风险').length).toBeGreaterThan(0));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.topic.create')?.request.body).toEqual({
      title: '发布风险',
      summary: '核对上线边界',
    });
    const topicDialog = within(screen.getByRole('dialog', { name: '整理话题' }));
    await user.click(topicDialog.getAllByRole('button', { name: '关闭' }).find((button) => !button.hasAttribute('aria-label'))!);
    await user.click(screen.getByRole('button', { name: '分享工作文件' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.artifact.add')).toBe(true));
    expect(transport.filePickCalls.at(-1)).toEqual({
      purpose: 'room-artifact',
      selection: 'file',
      multiple: false,
      maxFiles: 1,
    });
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.artifact.add')?.request.body).toEqual({
      path: '/Volumes/work/learnA/report.md',
      displayName: 'report.md',
      mediaType: 'text/markdown',
      topicId: 'topic:risk',
    });
  });

  it('keeps a late shared-file failure inside the Room that started the picker', async () => {
    const pendingPick = deferred<Array<{ id: string; name: string; mimeType: string; byteSize: number; path: string }>>();
    const pendingAdd = deferred<{ ok: true }>();
    const transport = new MockControlTransport({
      pickedFiles: [{ id: 'capability-probe', name: 'probe.md', mimeType: 'text/markdown', byteSize: 1, path: '/Volumes/work/learnA/probe.md' }],
      routes: {
        'agent.rooms.list': { ok: true, items: [roomSummary('room-a', 'Room A'), roomSummary('room-b', 'Room B')] },
        'agent.roles.list': { ok: true, items: previewPersonas },
        'agent.room.snapshot': (request: ControlRequest) => roomSnapshot(String(request.params?.roomId ?? ''), []),
        'agent.room.artifact.add': () => pendingAdd.promise,
      },
    });
    vi.spyOn(transport, 'pickFiles').mockImplementation(() => pendingPick.promise);
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '分享工作文件' }));
    await user.click(screen.getByRole('button', { name: '打开协作空间：Room B' }));
    pendingPick.resolve([{
      id: 'late-report',
      name: 'late-report.md',
      mimeType: 'text/markdown',
      byteSize: 100,
      path: '/Volumes/work/learnA/late-report.md',
    }]);
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'agent.room.artifact.add' && request.params?.roomId === 'room-a'
    ))).toBe(true));

    pendingAdd.reject(new Error('late Room A artifact failure'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '打开协作空间：Room A' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法分享这个文件');
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.room.artifact.add')?.request.body).toMatchObject({
      path: '/Volumes/work/learnA/late-report.md',
    });
  });

  it('archives a Room only after the real API confirms the state change', async () => {
    const archived = { ...roomSummary('room-a', '待收起协作空间'), status: 'archived' };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '待收起协作空间')] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.archive': { ok: true, room: archived },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click((await screen.findAllByRole('button', { name: '更多协作空间操作' }))[0]!);
    await user.click(await screen.findByRole('menuitem', { name: '收起协作空间' }));
    await user.click(screen.getByRole('button', { name: '收起协作空间' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request;
    expect(request).toMatchObject({ params: { roomId: 'room-a' }, body: { archived: true } });
    expect(await screen.findByText('选择一个协作空间')).toBeInTheDocument();
    expect(screen.getByText('选择一个协作空间').closest('.ui-empty-state')?.querySelector('img')).toBeNull();
    expect(screen.getByText('从左侧选择，或新建一个协作空间。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开协作空间：待收起协作空间' })).not.toBeInTheDocument();
  });

  it('restores an archived Room directly through the real state transition', async () => {
    const archived = { ...roomSummary('room-a', '已收起协作空间'), status: 'archived' };
    const restored = { ...archived, status: 'active' };
    const snapshot = roomSnapshot('room-a', [], '已收起协作空间');
    snapshot.room.status = 'archived';
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': (request: ControlRequest) => ({
        ok: true,
        items: request.query?.includeArchived ? [archived] : [],
      }),
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.archive': { ok: true, room: restored },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '显示已收起的协作空间' }));
    await user.click((await screen.findAllByRole('button', { name: '更多协作空间操作' }))[0]!);
    await user.click(await screen.findByRole('menuitem', { name: '恢复协作空间' }));
    expect(screen.queryByRole('heading', { name: '恢复这个协作空间？' })).not.toBeInTheDocument();

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request).toMatchObject({
      params: { roomId: 'room-a' },
      body: { archived: false },
    });
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeEnabled();
    await user.click(screen.getAllByRole('button', { name: '更多协作空间操作' })[0]!);
    expect(await screen.findByRole('menuitem', { name: '收起协作空间' })).toBeInTheDocument();
  });

  it('offers real participant addressing for manually routed Rooms', async () => {
    const manualRoom = { ...roomSummary('room-a', '点名协作'), routingPolicy: 'manual_mentions' };
    const snapshot = roomSnapshot('room-a', [], '点名协作');
    snapshot.room.routingPolicy = 'manual_mentions';
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [manualRoom] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': snapshot,
      'agent.room.message': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '核对角色创建契约');
    expect(screen.getByRole('button', { name: '发送消息' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '点名一位伙伴' }));
    await user.click(screen.getByRole('option', { name: /澄·初/ }));
    expect(composer).toHaveValue('核对角色创建契约 @澄·初 ');
    await user.click(screen.getByRole('button', { name: '发送消息' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '核对角色创建契约 @澄·初',
      participantIds: ['room-a:p2'],
    });
  });

  it('disables the composer instead of exposing an inert send action without a Room', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('选择一个协作空间')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '发送消息' })).toBeDisabled();
  });

  it('shows a useful empty conversation state after a real empty snapshot', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-empty', '空 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-empty', [], '空 Room'),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('还没有公开消息')).toBeInTheDocument();
    expect(screen.getByText('说出你想完成的事；只有遇到会影响实现的歧义，伙伴才会继续提问。')).toBeInTheDocument();
    expect(screen.getByText('还没有公开消息').closest('.ui-empty-state')?.querySelector('img')).toBeNull();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeEnabled();
  });

  it('opens the shared status experience for the selected Room', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-status', '状态 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-status', [], '状态 Room'),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await screen.findByText('还没有公开消息');
    await user.click(screen.getByRole('button', { name: '看看协作进展' }));
    expect(screen.getByRole('complementary', { name: '协作进展' })).toHaveAttribute('data-open', 'true');
    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveTextContent('等待开始');
    expect(screen.queryByText('伙伴状态')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收起进展面板' })).toBeInTheDocument();
  });

  it('hydrates authoritative task progress while the public conversation view remains selected', async () => {
    const room = roomSummary(
      'room-status',
      'Fresh installed-stack Room acceptance for automatic collaboration recovery and terminal settlement',
    );
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot(room.id, [], room.title),
      'agent.room.kernel.snapshot': roomKernelSnapshot(room.id),
    } });
    const user = userEvent.setup();
    const { container } = render(
      <ControlTransportProvider transport={transport}>
        <TooltipProvider><RoomsFeature /></TooltipProvider>
      </ControlTransportProvider>,
    );

    await screen.findByText('还没有公开消息');
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'agent.room.kernel.snapshot'
    ))).toBe(true));
    await user.click(screen.getByRole('button', { name: '看看协作进展' }));

    const status = screen.getByRole('complementary', { name: '协作进展' });
    expect(within(status).getByRole('status', { name: '任务进度连接' })).toHaveTextContent(
      '实时进度已连接',
    );
    expect(within(status).getByText(/更新于/)).toBeInTheDocument();
    expect(within(status).queryByText('进度同步异常')).not.toBeInTheDocument();
    expect(within(status).queryByText(/任务进度暂时不可用/)).not.toBeInTheDocument();
    expect(within(status).getByLabelText('整体任务与分工进度')).toHaveTextContent(
      '整体任务工作进行中',
    );
    expect(container.querySelector('.room-execution-workspace')).toHaveAttribute('hidden');
  });

  it('keeps the real role catalog usable when the Room list request fails', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': () => { throw new Error('room catalog unavailable'); },
      'agent.roles.list': { ok: true, items: previewPersonas },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByRole('alert')).toHaveTextContent('协作空间暂时无法读取，请稍后重试。');
    const create = screen.getByRole('button', { name: '开始新的协作' });
    expect(create).toBeEnabled();
    await user.click(create);
    expect(screen.getByRole('dialog', { name: '开始一起做事' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /澄·今/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·初/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·远/ })).toBeChecked();
  });

  it('keeps a Room creation failure inside the dialog and preserves the draft', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.sessions.list': { ok: true, items: [{ id: 'existing', mode: 'coordinator', workspaceRoots: ['/Volumes/work/learnA'] }] },
      'agent.rooms.create': () => { throw new Error('协作空间名称已存在'); },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const create = await screen.findByRole('button', { name: '开始新的协作' });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    await user.type(screen.getByRole('textbox', { name: '协作空间名称' }), '发布前检查');
    await user.click(screen.getByRole('button', { name: '开始协作' }));

    const dialog = screen.getByRole('dialog', { name: '开始一起做事' });
    expect(await screen.findByRole('alert')).toHaveTextContent('协作空间名称已存在');
    expect(dialog).toContainElement(screen.getByRole('alert'));
    expect(screen.getByRole('textbox', { name: '协作空间名称' })).toHaveValue('发布前检查');
  });

  it('reloads a real Room snapshot after snapshot_required and resumes at the new cursor', async () => {
    let snapshotCalls = 0;
    const initial = roomSnapshot('room-a', [
      roomEvent('room-a', 1, 'user_message', { text: '初始消息' }),
    ]);
    const recovered = roomSnapshot('room-a', [
      roomEvent('room-a', 1, 'user_message', { text: '初始消息' }),
      roomEvent('room-a', 2, 'snapshot_required', { reason: 'room_event_replay_gap' }),
      roomEvent('room-a', 3, 'user_message', { text: '恢复后的消息' }),
    ]);
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '恢复协作空间')] },
      'agent.room.snapshot': () => (++snapshotCalls === 1 ? initial : recovered),
      'agent.room.message': { ok: true },
      'agent.rooms.create': { ok: true },
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    expect(await screen.findByText('初始消息')).toBeInTheDocument();

    transport.emit(
      'agent.room.events',
      roomEvent('room-a', 2, 'snapshot_required', { reason: 'room_event_replay_gap' }),
    );

    expect(await screen.findByText('恢复后的消息')).toBeInTheDocument();
    await waitFor(() => expect(snapshotCalls).toBe(2));
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a:3');
  });

  it('keeps the last good transcript and resumes from the recovered cursor after a manual retry', async () => {
    let snapshotCalls = 0;
    const initial = roomSnapshot('room-a', [
      roomEvent('room-a', 1, 'user_message', { text: '仍然保留的历史消息' }),
    ]);
    const recovered = roomSnapshot('room-a', [
      roomEvent('room-a', 1, 'user_message', { text: '仍然保留的历史消息' }),
      roomEvent('room-a', 2, 'snapshot_required', { reason: 'room_event_replay_gap' }),
      roomEvent('room-a', 3, 'user_message', { text: '重新同步后的消息' }),
    ]);
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '恢复失败协作空间')] },
      'agent.room.snapshot': () => {
        snapshotCalls += 1;
        if (snapshotCalls === 1) return initial;
        if (snapshotCalls === 2) throw new Error('snapshot recovery failed');
        return recovered;
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    expect(await screen.findByText('仍然保留的历史消息')).toBeInTheDocument();

    transport.emit(
      'agent.room.events',
      roomEvent('room-a', 2, 'snapshot_required', { reason: 'room_event_replay_gap' }),
    );

    const retry = await screen.findByRole('button', { name: '重试同步' });
    expect(screen.getByRole('alert')).toHaveTextContent('已显示的历史消息会保留，实时更新已暂停');
    expect(screen.getByText('仍然保留的历史消息')).toBeInTheDocument();
    expect(transport.activeSubscriptionCount()).toBe(0);
    await user.type(screen.getByRole('textbox', { name: '协作消息' }), '草稿不会隐藏同步错误');
    expect(screen.getByRole('button', { name: '重试同步' })).toBeInTheDocument();

    await user.click(retry);

    expect(await screen.findByText('重新同步后的消息')).toBeInTheDocument();
    await waitFor(() => expect(snapshotCalls).toBe(3));
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a:3');
    expect(screen.queryByRole('button', { name: '重试同步' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(transport.activeSubscriptionCount()).toBe(1);
  });

  it('stops live Room motion when only the conversation stream disconnects', async () => {
    const now = Date.now();
    const progress = {
      ...roomEvent('room-a', 1, 'participant_activity', {
        rootId: 'room-a:turn-1',
        dispatchId: 'room-a:dispatch-1',
        sourceEventType: 'current_progress',
        status: 'running',
        summary: '正在核对最新界面实现',
      }, {
        turnId: 'room-a:turn-1',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
      }),
      createdAtMs: now,
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '独立连接状态 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [progress]),
      'agent.room.kernel.snapshot': roomKernelSnapshot('room-a'),
    } });
    useRoomLiveStore.getState().setKernelSync('room-a', {
      state: 'synced',
      detail: '任务内核实时更新已连接',
      updatedAtMs: now,
    });
    const view = render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect((await screen.findAllByText('正在核对最新界面实现')).length).toBeGreaterThan(0);
    const lane = view.container.querySelector<HTMLElement>('.room-agent-lane')!;
    await waitFor(() => expect(lane).toHaveAttribute('data-motion', 'fresh'));
    expect(useRoomLiveStore.getState().kernelSyncByRoomId['room-a']?.state).toBe('synced');

    act(() => {
      expect(transport.fail('agent.room.events', new Error('conversation stream interrupted'))).toBe(1);
    });

    await waitFor(() => expect(lane).toHaveAttribute('data-motion', 'disconnected'));
    expect(lane).toHaveTextContent('Room 对话实时更新暂时中断');
    expect(lane.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-motion', 'paused');
    expect(useRoomLiveStore.getState().kernelSyncByRoomId['room-a']?.state).toBe('synced');
  });

  it('refreshes Room metadata without tearing down the live timeline subscription', async () => {
    let snapshotCalls = 0;
    let roomGetCalls = 0;
    const refreshed = roomSummary('room-a', '刷新后的 Room');
    refreshed.configRevision = 2;
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '原 Room')] },
      'agent.room.snapshot': () => {
        snapshotCalls += 1;
        return roomSnapshot('room-a', [
          roomEvent('room-a', 1, 'user_message', { text: '保持可见的消息' }),
        ]);
      },
      'agent.room.get': () => {
        roomGetCalls += 1;
        return { ok: true, room: refreshed };
      },
      'agent.room.message': { ok: true },
      'agent.rooms.create': { ok: true },
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    expect(await screen.findByText('保持可见的消息')).toBeInTheDocument();
    expect(transport.activeSubscriptionCount()).toBe(1);

    transport.emit(
      'agent.room.events',
      roomEvent('room-a', 2, 'room_config_changed', { configRevision: 2 }),
    );
    transport.emit(
      'agent.room.events',
      roomEvent('room-a', 3, 'participant_activity', {
        activityKind: 'work',
        summary: '工作状态已更新',
      }),
    );

    await waitFor(() => expect(roomGetCalls).toBe(1));
    expect(snapshotCalls).toBe(1);
    expect(transport.subscriptionCalls).toHaveLength(1);
    expect(transport.activeSubscriptionCount()).toBe(1);
    expect(screen.getAllByText('刷新后的 Room').length).toBeGreaterThan(0);
    expect(screen.getByText('保持可见的消息')).toBeInTheDocument();
  });

  it('cancels a late snapshot when the user selects another Room', async () => {
    const first = deferred<ReturnType<typeof roomSnapshot>>();
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': {
        ok: true,
        items: [roomSummary('room-a', 'Room A'), roomSummary('room-b', 'Room B')],
      },
      'agent.room.snapshot': (request: ControlRequest) => request.params?.roomId === 'room-a'
        ? first.promise
        : roomSnapshot('room-b', [roomEvent('room-b', 1, 'user_message', { text: 'Room B 历史' })]),
      'agent.room.message': { ok: true },
      'agent.rooms.create': { ok: true },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    await user.click(await screen.findByRole('button', { name: /Room B/ }));
    expect(await screen.findByText('Room B 历史')).toBeInTheDocument();

    first.resolve(roomSnapshot('room-a', [
      roomEvent('room-a', 1, 'user_message', { text: '迟到的 Room A 历史' }),
    ]));

    await Promise.resolve();
    await Promise.resolve();
    expect(screen.queryByText('迟到的 Room A 历史')).not.toBeInTheDocument();
    expect(screen.getByText('Room B 历史')).toBeInTheDocument();
    expect(transport.activeSubscriptionCount()).toBe(1);
  });

  it('shows the complete Room working boundary without per-role permission switches', async () => {
    const room = roomSummary('room-a', '权限 Room');
    const tools = [
      { id: 'overview', displayName: '控制中心概览', description: '查看整体状态', sessionModes: ['assistant', 'coordinator'], operations: ['status'], profileOperations: { 'control-center-v1': ['status'], 'subagent-readonly-v1': ['status'] }, enabled: true },
      { id: 'memory', displayName: '记忆与工具书', description: '检索记忆', sessionModes: ['assistant', 'coordinator'], operations: ['catalog'], profileOperations: { 'control-center-v1': ['catalog'], 'subagent-readonly-v1': ['catalog'] }, enabled: true },
      { id: 'workspace_read', displayName: '工作区读取', description: '读取工作区', sessionModes: ['coordinator'], operations: ['read'], profileOperations: { 'control-center-v1': ['read'], 'subagent-readonly-v1': [] }, enabled: true },
      { id: 'read_file', displayName: 'Read file', description: '旧 Provider 读取别名', sessionModes: ['coordinator'], operations: ['read_range'], profileOperations: { 'control-center-v1': ['read_range'], 'subagent-readonly-v1': [] }, enabled: false },
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.tools.list': { ok: true, items: tools },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('radio', { name: '伙伴' }));
    expect(screen.getByRole('region', { name: '伙伴与权限' })).toHaveTextContent('伙伴与工作权限');
    const sessionListRequestsBeforeBoundary = transport.requests.filter(
      (call) => call.request.pathId === 'agent.sessions.list',
    ).length;
    await user.click((await screen.findAllByRole('button', { name: '查看能做什么' }))[0]!);
    expect(await screen.findByRole('dialog', { name: /澄能做什么/ })).toBeInTheDocument();
    expect(transport.requests.filter(
      (call) => call.request.pathId === 'agent.sessions.list',
    )).toHaveLength(sessionListRequestsBeforeBoundary);
    expect(transport.requests.find((call) => call.request.pathId === 'agent.tools.list')?.request.query).toEqual({ sessionId: 'room-a:s1' });
    expect(screen.getByText('工作区托管')).toBeInTheDocument();
    expect(screen.getAllByText('/Volumes/work/learnA').length).toBeGreaterThan(0);
    expect(screen.queryByRole('radio', { name: '只读' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '保存权限' })).not.toBeInTheDocument();
    expect(screen.queryByText(/私有 Session：/)).not.toBeInTheDocument();
    const toolDisclosure = screen.getByText(/看看可以使用哪些工具/).closest('summary')!;
    expect(toolDisclosure).toHaveTextContent('3 项');
    await user.click(toolDisclosure);
    expect(screen.getAllByText('读取文件')).toHaveLength(1);
    expect(transport.requests.some((call) => call.request.pathId === 'agent.session.mode.update')).toBe(false);
  });

  it('links Room approvals to the exact participant Agent session', () => {
    const room = roomSummary('room-a', '审阅 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.messageOrder.push('assistant');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: ['assistant'], activityIds: [],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.messagesById.assistant = {
      id: 'assistant', roomId: room.id, turnId: 'turn-a', participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1', role: 'assistant', status: 'completed', text: '', createdAtMs: 1,
      message: {
        schemaVersion: 'rag-ime.agent-message.v1', id: 'assistant', sessionId: 'room-a:s1',
        turnId: 'turn-a', role: 'assistant', status: 'completed', attachments: [], citations: [], createdAtMs: 1,
        blocks: [{ id: 'approval', type: 'approval', status: 'running', presentationKind: 'approval', data: { approvalId: 'approval:1', payloadSha256: 'a'.repeat(64), state: 'pending', title: '应用设置' } }],
      },
    };

    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.getByRole('link', { name: /立即审阅/ })).toHaveAttribute('href', '#/agent?session=room-a%3As1');
  });

  it('links a pending plan review to the authoritative participant Session', () => {
    const room = roomSummary('room-a', '计划审阅 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('review:1');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['review:1'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.activitiesById['review:1'] = {
      id: 'review:1', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'waiting', summary: '请选择是否批准计划',
      payload: { requestKind: 'plan_review', requestId: 'plan:review:1' }, createdAtMs: 1,
    };

    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.getByText('等待审阅')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /立即审阅/ })).toHaveLength(1);
    expect(screen.getByRole('link', { name: /立即审阅/ })).toHaveAttribute('href', '#/agent?session=room-a%3As1');
    expect(screen.queryByRole('button', { name: /停止/ })).not.toBeInTheDocument();
  });

  it('does not expose a stale native selectable clarification as a second answer owner', () => {
    const room = roomSummary('room-a', '选择 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['select:1'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.activitiesById['select:1'] = {
      id: 'select:1', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'waiting', summary: '选择部署环境',
      payload: {
        requestKind: 'user_input_required',
        requestId: 'select:1',
        method: 'select',
        options: [{ id: 'staging', label: '预发布' }, { id: 'production', label: '生产' }],
      },
      createdAtMs: 1,
    };

    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.queryByRole('link', { name: /立即选择/ })).not.toBeInTheDocument();
  });

  it('does not expose stale grouped clarification outside the canonical Room question', () => {
    const room = roomSummary('room-a', '协作确认');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['grouped:1'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.activitiesById['grouped:1'] = {
      id: 'grouped:1', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'waiting', summary: '一起确认交付方式',
      payload: {
        requestKind: 'grouped_questions',
        requestId: 'grouped:1',
        questions: [
          { id: 'scope', question: '先覆盖哪一部分？', options: ['核心流程', '完整流程'] },
          { id: 'review', question: '如何复核？', options: ['伙伴互查', '直接交付'] },
        ],
      },
      createdAtMs: 1,
    };

    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.queryByRole('link', { name: /立即回答/ })).not.toBeInTheDocument();
    expect(screen.queryByText('核心流程')).not.toBeInTheDocument();
    expect(screen.queryByText('伙伴互查')).not.toBeInTheDocument();
  });

  it('keeps private activity rows out of the public Post timeline', () => {
    const room: RoomSummary = {
      id: 'room-a', title: '迁移作战室', status: 'active', routingPolicy: 'moderator',
      moderatorParticipantId: 'p1', updatedAtMs: Date.now(),
      participants: [
        { id: 'p1', sessionId: 's1', roleId: 'companion-present-v1', roleVersion: '1', displayName: '澄', status: 'active', ordinal: 0 },
        { id: 'p2', sessionId: 's2', roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '澄·初', status: 'active', ordinal: 1 },
      ],
    };
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('activity-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['activity-a'],
      participantIds: ['p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.activitiesById['activity-a'] = {
      id: 'activity-a', turnId: 'turn-a', participantId: 'p1', sourceSessionId: 's1',
      kind: 'participant_activity', status: 'running', summary: '核对移动端布局', payload: {}, createdAtMs: 1,
    };
    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(document.querySelector('.room-group-activity')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('核对移动端布局');
  });

  it('shows a bounded tool lifecycle with one root-owned stop action', async () => {
    const room = roomSummary('room-a', '实时执行 Room');
    const projection = createRoomProjection(room.id);
    const now = Date.now();
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('tool-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', rootId: 'room-turn:root-a', status: 'running', messageIds: [], activityIds: ['tool-a'],
      participantIds: ['room-a:p1'], createdAtMs: now - 1_200, updatedAtMs: now,
    };
    projection.activitiesById['tool-a'] = {
      id: 'tool-a', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'running', summary: 'grep',
      payload: {
        sourceEventType: 'tool_started',
        toolName: 'grep',
        toolCallId: 'call-a',
        arguments: {
          path: '…/project/rag_ime',
          pattern: 'room_event_projection',
          limit: 40,
        },
      },
      createdAtMs: now - 1_000,
    };
    const onAbortTurn = vi.fn();
    const user = userEvent.setup();

    render(<RoomTurn
      turnId="turn-a"
      room={room}
      projection={projection}
      personas={previewPersonas}
      onAbortTurn={onAbortTurn}
    />);

    const toolTitle = screen.getByText('正在搜索 …/project/rag_ime 中的 “协作记录”');
    expect(toolTitle).toBeInTheDocument();
    const toolSummary = toolTitle.closest('summary')!;
    expect(toolSummary).toHaveTextContent('运行记录 · 搜索文本 · 进行中');
    expect(toolSummary).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByLabelText('工具调用参数')).toHaveTextContent('协作记录');
    await user.click(toolSummary);
    expect(toolSummary).toHaveAttribute('aria-expanded', 'false');
    expect(document.activeElement).toBe(toolSummary);
    await user.click(toolSummary);
    expect(toolSummary).toHaveAttribute('aria-expanded', 'true');
    expect(document.activeElement).toBe(toolSummary);
    expect(screen.getByLabelText('工具调用参数')).not.toHaveTextContent('room_event_projection');
    expect(screen.getByText(/1s/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '停止本轮任务' })).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: '停止本轮任务' }));
    expect(onAbortTurn).toHaveBeenCalledWith('room-turn:root-a');
  });

  it('offers explicit continue and stop actions when the authoritative Root is blocked', async () => {
    const room = roomSummary('room-a', '阻塞恢复 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      rootId: 'room-root:blocked',
      status: 'running',
      messageIds: [],
      activityIds: [],
      participantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    const root: RootProjection = {
      schemaVersion: 'wisdom-weasel.room-root-execution.v3',
      rootId: 'room-root:blocked',
      roomId: room.id,
      generation: 0,
      state: 'blocked',
      facilitatorParticipantId: 'room-a:p1',
      reporterParticipantId: null,
      reporterSelectionReceiptId: null,
      requirementAnchorRef: 'requirement:block',
      createdByActorRef: 'user:local',
      terminalReceiptId: null,
      activeProfileRef: null,
      budgetPolicyRef: 'room-budget:interactive-v1',
      independentReviewRequired: false,
      createdAtMs: 1,
      isFinal: false,
      updatedAtMs: 2,
    };
    const onRetryRoot = vi.fn();
    const onAbortTurn = vi.fn();
    const user = userEvent.setup();

    render(<RoomTurn
      turnId="turn-a"
      room={room}
      projection={projection}
      personas={previewPersonas}
      kernelRootsById={{ [root.rootId]: root }}
      onRetryRoot={onRetryRoot}
      onAbortTurn={onAbortTurn}
    />);

    expect(screen.getByRole('alert')).toHaveTextContent('只重做失败的部分');
    await user.click(screen.getByRole('button', { name: '继续任务' }));
    await user.click(screen.getByRole('button', { name: '停止任务' }));
    expect(onRetryRoot).toHaveBeenCalledWith(root.rootId);
    expect(onAbortTurn).toHaveBeenCalledWith(root.rootId);
  });

  it('keeps internal alignment dispatches out of the conversation surface', () => {
    const room = roomSummary('room-a', '并行对齐 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      rootId: 'root-a',
      status: 'running',
      messageIds: [],
      activityIds: [],
      participantIds: room.participants.map((participant) => participant.id),
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    const alignmentDispatches = room.participants.map((
      participant,
      index,
    ): RoomDispatchEnvelopeV2 => ({
      schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
      dispatchId: `dispatch-align-${index}`,
      rootId: 'root-a',
      taskId: `task-align-${index}`,
      parentDispatchId: null,
      generation: 0,
      hopCount: 0,
      depth: 0,
      budgetCost: 1,
      targetSessionId: participant.sessionId,
      targetParticipantId: participant.id,
      triggerId: 'trigger-a',
      intentKind: 'align',
      idempotencyKey: `align-${index}`,
      attempt: 0,
      capabilityEpoch: 1,
      runtimeProfileRevision: 'runtime-profile:test-v1',
      alignmentOrdinal: index,
      dependsOnDispatchIds: [],
      state: index === 0 ? 'leased' : 'pending',
    }));
    const dispatchesById = Object.fromEntries(
      alignmentDispatches.map((dispatch) => [
        dispatch.dispatchId,
        dispatch,
      ]),
    );

    render(<RoomTurn
      turnId="turn-a"
      room={room}
      projection={projection}
      personas={previewPersonas}
      kernelDispatchesById={dispatchesById}
    />);

    expect(screen.queryByRole('region', {
      name: '并行需求对齐进度',
    })).not.toBeInTheDocument();
    expect(screen.queryByText('开始前 · 并行确认')).not.toBeInTheDocument();
    expect(screen.queryByText('需求对齐')).not.toBeInTheDocument();
  });

  it('shows replayed read arguments and bounded result behind a copyable row disclosure', async () => {
    const room = roomSummary('room-a', '工具回执 Room');
    const projection = createRoomProjection(room.id);
    const now = Date.now();
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('read-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['read-a'],
      participantIds: ['room-a:p1'], createdAtMs: now - 1_200, updatedAtMs: now,
    };
    projection.activitiesById['read-a'] = {
      id: 'read-a', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'completed', summary: 'read',
      payload: {
        sourceEventType: 'tool_finished',
        toolName: 'read',
        toolCallId: 'call-read',
        arguments: {
          path: '…/project/src/runtime.ts',
          offset: 80,
          limit: 24,
        },
        result: {
          path: '…/project/src/runtime.ts',
          offset: 80,
          limit: 24,
          outputPreview: '80:export function settleRoom() {\\n81:  return receipt;\\n82:}',
          outputTruncated: false,
        },
      },
      createdAtMs: now - 1_000,
      updatedAtMs: now - 700,
    };
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { container } = render(
      <TooltipProvider>
        <RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />
      </TooltipProvider>,
    );

    const row = container.querySelector<HTMLDetailsElement>('.room-agent-activity--tool')!;
    expect(row).not.toHaveAttribute('open');
    expect(row).toHaveTextContent('已读取 …/project/src/runtime.ts');
    expect(row).not.toHaveTextContent('settleRoom');
    await user.click(row.querySelector('summary')!);

    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('80');
    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('24');
    expect(within(row).getByLabelText('工具返回片段')).toHaveTextContent('settleRoom');
    await user.click(within(row).getByRole('button', { name: '复制代码' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      '80:export function settleRoom() {\\n81:  return receipt;\\n82:}',
    ));
  });

  it('keeps concrete Room results while dropping opaque receipt filler', async () => {
    const room = roomSummary('room-a', 'Room 状态回执');
    const identity = {
      turnId: 'room-a:turn-1',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
    };
    const started = reduceRoomEvent(
      createRoomProjection(room.id),
      parseRoomEvent(roomEvent('room-a', 1, 'participant_activity', {
        rootId: 'room-a:turn-1',
        dispatchId: 'dispatch-a',
        sourceEventType: 'tool_started',
        toolName: 'room_state',
        toolCallId: 'call-control',
        summary: '准备查看协作状态',
        status: 'running',
        arguments: {
          operation: 'status',
          includeEvidence: true,
          intent: '请伙伴复核状态',
          objective: '确认 Room 是否同步',
          expectedOutput: '一条公开状态回执',
          acceptance: '状态版本可核对',
          kind: 'status_check',
          mentions: ['room-a:p2'],
          waitingFor: 'room-a:p2',
          blocker: '无',
        },
      }, identity)),
    ).state;
    const projection = reduceRoomEvent(
      started,
      parseRoomEvent(roomEvent('room-a', 2, 'participant_activity', {
        rootId: 'room-a:turn-1',
        dispatchId: 'dispatch-a',
        sourceEventType: 'tool_finished',
        toolName: 'room_state',
        toolCallId: 'call-control',
        result: {
          unchanged: true,
          ok: true,
          created: true,
          executionPerformed: true,
          stateRevision: 12,
          evidenceRef: {
            id: 'safe-room-receipt-42',
            revision: 3,
          },
          currentResponsibility: {
            state: 'running',
            objective: '继续核对 Room 状态',
          },
          status: 'ready',
        },
      }, identity)),
    ).state;
    const user = userEvent.setup();
    const { container } = render(
      <RoomTurn turnId="room-a:turn-1" room={room} projection={projection} personas={previewPersonas} />,
    );
    const row = container.querySelector<HTMLDetailsElement>('.room-agent-activity--tool')!;

    expect(row).toHaveAttribute('data-state', 'completed');
    expect(row).toHaveTextContent('查看协作状态 已完成');
    expect(row).not.toHaveTextContent('准备查看协作状态');
    await user.click(row.querySelector('summary')!);
    const request = within(row).getByLabelText('工具调用参数');
    expect(request).toHaveTextContent('协作意图');
    expect(request).toHaveTextContent('任务目标');
    expect(request).toHaveTextContent('预期交付');
    expect(request).toHaveTextContent('操作');
    expect(request).toHaveTextContent('等待对象');
    expect(request).not.toHaveTextContent('room-a:p2');
    expect(request).not.toHaveTextContent('expectedOutput');
    expect(request).not.toHaveTextContent('waitingFor');
    const returned = within(row).getByLabelText('当前协作状态内容');
    expect(returned).toHaveTextContent('继续核对 Room 状态');
    expect(returned).toHaveTextContent('运行中');
    expect(returned).not.toHaveTextContent('状态版本');
    expect(returned).not.toHaveTextContent('第 12 版');
    expect(returned).not.toHaveTextContent('验证依据已保留');
    expect(returned).not.toHaveTextContent('safe-room-receipt-42');
    expect(returned).not.toHaveTextContent('executionPerformed');
    expect(returned).not.toHaveTextContent('stateRevision');
    expect(returned).not.toHaveTextContent('evidenceRef');
  });

  it('puts governed work summaries and current progress in the main work card and chronological feed', () => {
    const room = roomSummary('room-a', '公开进度 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-progress');
    projection.turnsById['turn-progress'] = {
      id: 'turn-progress',
      rootId: 'turn-progress',
      status: 'running',
      messageIds: [],
      activityIds: ['reasoning-a', 'read-a', 'progress-a'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-progress'],
      dispatchParticipantIds: { 'dispatch-progress': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    const base = {
      turnId: 'turn-progress',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity' as const,
      createdAtMs: 1,
    };
    projection.activitiesById['reasoning-a'] = {
      ...base,
      id: 'reasoning-a',
      status: 'running',
      summary: '先确认调用链，再修改入口',
      payload: {
        rootId: 'turn-progress',
        dispatchId: 'dispatch-progress',
        sourceEventType: 'reasoning_summary',
        source: 'provider_reasoning_summary',
        publicSummaryVersion: 'room-work-summary.v1',
        publicSummaryKind: 'implementation',
        updateCount: 2,
        reasoningHistory: [
          {
            sourceEventId: 'reasoning-progress-1',
            summary: 'private provider heading one',
            createdAtMs: 1,
          },
          {
            sourceEventId: 'reasoning-progress-2',
            summary: 'private provider heading two',
            createdAtMs: 2,
          },
        ],
      },
    };
    projection.activitiesById['read-a'] = {
      ...base,
      id: 'read-a',
      status: 'completed',
      summary: '读取 src/runtime.ts',
      payload: {
        rootId: 'turn-progress',
        dispatchId: 'dispatch-progress',
        sourceEventType: 'tool_finished',
        toolName: 'read',
        toolCallId: 'read-call',
        arguments: { path: '…/project/src/runtime.ts' },
      },
      createdAtMs: 2,
    };
    projection.activitiesById['progress-a'] = {
      ...base,
      id: 'progress-a',
      status: 'running',
      summary: '入口已修改，正在核对调用方',
      payload: {
        rootId: 'turn-progress',
        dispatchId: 'dispatch-progress',
        sourceEventType: 'current_progress',
      },
      createdAtMs: 3,
    };

    const { container } = render(
      <RoomTurn turnId="turn-progress" room={room} projection={projection} personas={previewPersonas} />,
    );
    const work = container.querySelector('.room-agent-lane__work')!;
    const rows = [...container.querySelectorAll('.room-agent-activity, .room-reasoning-summary')];

    expect(work).toHaveTextContent('入口已修改，正在核对调用方');
    expect(work).toHaveTextContent('3 个步骤');
    expect(rows).toHaveLength(3);
    expect(work).toHaveTextContent('工作摘要');
    expect(rows[0]).toHaveTextContent('当前任务推进有新进展');
    expect(rows[0]).toHaveTextContent('实时进展 · 工作摘要');
    expect(rows[0]).toHaveTextContent('已更新 2 次');
    expect(within(rows[0] as HTMLElement).queryByRole('list', { name: '最近工作进展' })).not.toBeInTheDocument();
    expect(rows[0]).not.toHaveTextContent('private provider heading');
    expect(rows[1]).toHaveTextContent('运行记录');
    expect(rows[2]).toHaveTextContent('实时进展');
    expect(rows[1]).toHaveTextContent('runtime.ts');
    expect(rows[2]).toHaveTextContent('入口已修改，正在核对调用方');
  });

  it('renders two separate same-name tool calls as two cards', () => {
    const room = roomSummary('room-a', '工具调用 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['read-a', 'read-b'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 4,
    };
    for (const [index, id] of ['read-a', 'read-b'].entries()) {
      projection.activitiesById[id] = {
        id,
        turnId: 'turn-a',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
        kind: 'participant_activity',
        status: 'completed',
        summary: `读取第 ${index + 1} 个文件`,
        payload: {
          sourceEventType: 'tool_finished',
          toolName: 'read',
          toolCallId: `call-${index + 1}`,
          arguments: { path: `…/project/src/file-${index + 1}.ts` },
          result: { outputPreview: `file ${index + 1}`, outputTruncated: false },
        },
        createdAtMs: index + 1,
      };
    }
    const { container } = render(
      <RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />,
    );
    const cards = container.querySelectorAll('.room-agent-activity--tool');

    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('file-1.ts');
    expect(cards[1]).toHaveTextContent('file-2.ts');
    expect(container.querySelector('.room-agent-activity--tool-group')).not.toBeInTheDocument();
    expect(container.querySelector('.room-agent-lane__activity-heading')).toHaveTextContent('读取文件');
    expect(container.querySelector('.room-agent-lane__activity-heading')).toHaveTextContent('2 个步骤 · 2 个步骤已返回 · 正在继续');
  });

  it('separates returned steps from a stopped Root and exposes the concrete step list', () => {
    const room = roomSummary('room-a', '停止后核对 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-stopped');
    projection.turnsById['turn-stopped'] = {
      id: 'turn-stopped',
      rootId: 'turn-stopped',
      status: 'aborted',
      messageIds: [],
      activityIds: ['read-finished', 'write-finished'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-stopped'],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: ['room-a:p1'],
      terminalDispatchIds: ['dispatch-stopped'],
      failedDispatchIds: [],
      abortedDispatchIds: ['dispatch-stopped'],
      dispatchParticipantIds: { 'dispatch-stopped': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 5,
    };
    for (const [index, toolName] of ['read', 'write'].entries()) {
      const id = `${toolName}-finished`;
      projection.activitiesById[id] = {
        id,
        turnId: 'turn-stopped',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
        kind: 'participant_activity',
        status: 'completed',
        summary: `${toolName} 已返回`,
        payload: {
          rootId: 'turn-stopped',
          dispatchId: 'dispatch-stopped',
          sourceEventType: 'tool_finished',
          toolName,
          toolCallId: `call-${index + 1}`,
          arguments: { path: `…/project/file-${index + 1}.ts` },
          result: { outputPreview: `step ${index + 1}`, outputTruncated: false },
        },
        createdAtMs: index + 1,
      };
    }

    const { container } = render(
      <RoomTurn turnId="turn-stopped" room={room} projection={projection} personas={previewPersonas} />,
    );
    const activity = container.querySelector<HTMLElement>('.room-agent-lane__activity')!;

    expect(activity.tagName).toBe('SECTION');
    expect(activity.querySelector('.room-agent-lane__activity-heading')).toHaveTextContent('2 个步骤 · 所有步骤已返回');
    expect(activity).toHaveTextContent('file-1.ts');
    expect(activity).toHaveTextContent('file-2.ts');
    expect(container.querySelector('.room-agent-lane')).toHaveAttribute('data-state', 'aborted');
    expect(screen.getByText('这轮协作已停止')).toBeInTheDocument();
    expect(screen.queryByText('全部完成')).not.toBeInTheDocument();
  });

  it('renders an interrupted Root tool as stopped instead of still running', () => {
    const room = roomSummary('room-a', '中止工具状态 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-stopped-tool');
    projection.turnsById['turn-stopped-tool'] = {
      id: 'turn-stopped-tool',
      rootId: 'turn-stopped-tool',
      status: 'aborted',
      messageIds: [],
      activityIds: ['bash-interrupted'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-stopped-tool'],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: ['room-a:p1'],
      terminalDispatchIds: ['dispatch-stopped-tool'],
      failedDispatchIds: [],
      abortedDispatchIds: ['dispatch-stopped-tool'],
      dispatchParticipantIds: { 'dispatch-stopped-tool': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 5,
    };
    projection.activitiesById['bash-interrupted'] = {
      id: 'bash-interrupted',
      turnId: 'turn-stopped-tool',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'aborted',
      summary: 'participant_activity',
      payload: {
        rootId: 'turn-stopped-tool',
        dispatchId: 'dispatch-stopped-tool',
        sourceEventType: 'tool_started',
        toolName: 'bash',
        toolCallId: 'call-interrupted',
        arguments: { command: 'pnpm run dev' },
      },
      createdAtMs: 2,
      updatedAtMs: 5,
    };

    const turnView = render(
      <RoomTurn turnId="turn-stopped-tool" room={room} projection={projection} personas={previewPersonas} />,
    );
    const activityLog = turnView.container.querySelector('.room-agent-lane__activity')!;
    const toolCard = turnView.container.querySelector('.room-agent-activity--tool')!;
    expect(activityLog.querySelector('.room-agent-lane__activity-heading')).toHaveTextContent('1 个步骤 · 1 个已停止');
    expect(toolCard).toHaveAttribute('data-state', 'aborted');
    expect(toolCard).toHaveTextContent('已停止');
    expect(toolCard).not.toHaveTextContent('进行中');
    turnView.unmount();

    const statusView = render(
      <TooltipProvider><RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} /></TooltipProvider>,
    );
    const statusPhase = statusView.container.querySelector('.room-status-phase')!;
    expect(statusPhase).toHaveAttribute('data-phase', 'aborted');
    expect(statusPhase).toHaveTextContent('已停止');
    expect(statusView.container.querySelector('.room-status-activity')).not.toBeInTheDocument();
  });

  it('reconciles a transient resume lane after its Root completes', () => {
    const room = roomSummary('room-a', '恢复分工终态 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-completed');
    projection.turnsById['turn-completed'] = {
      id: 'turn-completed',
      rootId: 'turn-completed',
      status: 'completed',
      messageIds: [],
      activityIds: ['resume-work'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-primary', 'dispatch-resume'],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      terminalDispatchIds: ['dispatch-primary'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: {
        'dispatch-primary': 'room-a:p1',
        'dispatch-resume': 'room-a:p1',
      },
      createdAtMs: 1,
      updatedAtMs: 5,
    };
    projection.activitiesById['resume-work'] = {
      id: 'resume-work',
      turnId: 'turn-completed',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'completed',
      summary: '协作进度已经同步',
      payload: {
        rootId: 'turn-completed',
        dispatchId: 'dispatch-resume',
        activityKind: 'work',
        phase: 'completed',
      },
      createdAtMs: 4,
    };

    const { container } = render(
      <RoomTurn turnId="turn-completed" room={room} projection={projection} personas={previewPersonas} />,
    );
    const lane = container.querySelector('.room-agent-lane')!;

    expect(lane).toHaveAttribute('data-state', 'completed');
    expect(lane.querySelector('.room-agent-lane__identity')).toHaveTextContent('已完成');
    expect(lane.querySelector('.room-agent-lane__identity')).not.toHaveTextContent('执行中');
    expect(screen.getByText('这轮协作已完成')).toBeInTheDocument();
  });

  it('marks only a live Root terminal transition as an arriving collaboration result', () => {
    const room = roomSummary('room-a', '实时终态 Room');
    const projection = createRoomProjection(room.id);
    const liveAtMs = Date.now();
    projection.turnOrder.push('turn-live');
    projection.turnsById['turn-live'] = {
      id: 'turn-live',
      rootId: 'turn-live',
      status: 'running',
      messageIds: [],
      activityIds: ['route-live'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-live'],
      terminalParticipantIds: [],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      terminalDispatchIds: [],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: { 'dispatch-live': 'room-a:p1' },
      createdAtMs: liveAtMs - 1_000,
      updatedAtMs: liveAtMs,
    };
    projection.activitiesById['route-live'] = {
      id: 'route-live',
      turnId: 'turn-live',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'route_decision',
      status: 'completed',
      summary: '澄·今已接手',
      payload: {
        rootId: 'turn-live',
        dispatchId: 'dispatch-live',
        targetParticipantId: 'room-a:p1',
      },
      createdAtMs: liveAtMs,
    };
    const roomTurn = () => (
      <RoomTurn turnId="turn-live" room={room} projection={projection} personas={previewPersonas} />
    );
    const view = render(roomTurn());

    expect(view.container.querySelector('.room-turn')).toHaveAttribute('data-turn-status', 'running');
    expect(view.container.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'thinking');
    expect(view.container.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-state', 'running');
    expect(view.container.querySelector('.room-agent-lane__work')).toHaveTextContent('已接手');
    projection.turnsById['turn-live'] = {
      ...projection.turnsById['turn-live'],
      status: 'completed',
      terminalParticipantIds: ['room-a:p1'],
      terminalDispatchIds: ['dispatch-live'],
      updatedAtMs: liveAtMs + 1,
    };
    view.rerender(roomTurn());

    expect(view.container.querySelector('.room-turn__terminal')).toHaveAttribute('data-arriving', 'true');
    expect(view.container.querySelector('.agent-persona-avatar')).toHaveAttribute('data-presence', 'done');
    expect(view.container.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-state', 'settled');
    view.unmount();

    const settled = render(roomTurn());
    expect(settled.container.querySelector('.room-turn__terminal')).not.toHaveAttribute('data-arriving');
    expect(settled.container.querySelector('.room-agent-lane__activity')).toHaveAttribute('data-state', 'settled');
  });

  it('keeps a committed lane completed without showing a failed read as successful', () => {
    const room = roomSummary('room-a', '可恢复工具失败 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.messageOrder.push('post-a');
    projection.activityOrder.push('route-a', 'tool-failed-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      rootId: 'turn-a',
      status: 'running',
      messageIds: ['post-a'],
      activityIds: ['route-a', 'tool-failed-a'],
      participantIds: ['room-a:p1'],
      dispatchIds: ['dispatch-a'],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      terminalDispatchIds: ['dispatch-a'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: { 'dispatch-a': 'room-a:p1' },
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    projection.messagesById['post-a'] = {
      id: 'post-a',
      roomId: room.id,
      turnId: 'turn-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      role: 'assistant',
      status: 'completed',
      text: '最终交付',
      projectionKind: 'post',
      postKind: 'result',
      rootId: 'turn-a',
      dispatchId: 'dispatch-a',
      createdAtMs: 4,
      completedAtMs: 4,
    };
    projection.activitiesById['route-a'] = {
      id: 'route-a',
      turnId: 'turn-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'route_decision',
      status: 'completed',
      summary: '澄 已接手',
      payload: { rootId: 'turn-a', dispatchId: 'dispatch-a', targetParticipantId: 'room-a:p1' },
      createdAtMs: 1,
    };
    projection.activitiesById['tool-failed-a'] = {
      id: 'tool-failed-a',
      turnId: 'turn-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'failed',
      summary: '首次参数不完整，已由 Agent 修正后重试',
      payload: {
        rootId: 'turn-a',
        dispatchId: 'dispatch-a',
        sourceEventType: 'tool_finished',
        toolName: 'read',
        arguments: { path: '…/project/game.js' },
        error: '文件不存在',
        isError: true,
      },
      createdAtMs: 2,
      updatedAtMs: 3,
    };

    const { container } = render(
      <RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />,
    );

    expect(screen.getByText('最终交付')).toBeInTheDocument();
    expect(screen.getAllByText('已完成')).not.toHaveLength(0);
    expect(screen.queryByText('未完成')).not.toBeInTheDocument();
    expect(container.querySelector('.room-agent-lane')).toHaveAttribute('data-state', 'completed');
    expect(container).toHaveTextContent('读取文件执行失败');
    expect(container).not.toHaveTextContent('game.js 已读取');
  });

  it('does not render Room lifecycle events without a public Root as a chat turn', () => {
    const projection = createRoomProjection('room-a');
    projection.turnOrder.push('unscoped');
    projection.turnsById.unscoped = {
      id: 'unscoped', status: 'completed', messageIds: [], activityIds: ['room-created'],
      participantIds: [], createdAtMs: 1, updatedAtMs: 2,
    };
    projection.activitiesById['room-created'] = {
      id: 'room-created', turnId: 'unscoped', participantId: null, sourceSessionId: '',
      kind: 'participant_status', status: 'completed', summary: '协作空间已就绪',
      payload: { status: 'room_created' }, createdAtMs: 1,
    };

    const { container } = render(<RoomTurn
      turnId="unscoped"
      projection={projection}
      personas={previewPersonas}
    />);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('正在选择伙伴')).not.toBeInTheDocument();
  });

  it('shows humane terminal fallbacks and retries the owning message when allowed', async () => {
    const room = roomSummary('room-a', '失败恢复 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-failed');
    projection.messageOrder.push('user-failed');
    projection.turnsById['turn-failed'] = {
      id: 'turn-failed',
      status: 'failed',
      messageIds: ['user-failed'],
      activityIds: [],
      participantIds: [],
      failure: 'dispatchId: dispatch-private /Volumes/private/report',
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.messagesById['user-failed'] = {
      id: 'user-failed',
      roomId: room.id,
      turnId: 'turn-failed',
      participantId: null,
      sourceSessionId: '',
      role: 'user',
      status: 'completed',
      text: '请重新核对交付状态',
      createdAtMs: 1,
    };
    const onRetryTurn = vi.fn();
    const user = userEvent.setup();
    const roomTurn = (allowRetry = true) => <RoomTurn
      turnId="turn-failed"
      room={room}
      projection={projection}
      personas={previewPersonas}
      onRetryTurn={allowRetry ? onRetryTurn : undefined}
    />;
    const view = render(roomTurn());

    expect(screen.getByText('这轮协作没有完成')).toBeInTheDocument();
    expect(screen.getByText('伙伴未能完成这轮任务，你可以调整原消息后再试。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '再试一次' }));
    expect(onRetryTurn).toHaveBeenCalledWith('请重新核对交付状态');

    projection.turnsById['turn-failed'].status = 'aborted';
    view.rerender(roomTurn());
    expect(screen.getByText('这轮协作已停止')).toBeInTheDocument();
    expect(screen.getByText('未完成的伙伴、工具和后续任务不会继续。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '再试一次' }));
    expect(onRetryTurn).toHaveBeenCalledTimes(2);

    view.rerender(roomTurn(false));
    expect(screen.queryByRole('button', { name: '再试一次' })).not.toBeInTheDocument();
  });

  it('keeps a retry-wait Root cancellable until the participant completes', () => {
    const rootTurnId = 'room-turn:retry-wait';
    let projection = reduceRoomEvent(
      createRoomProjection('room-a'),
      parseRoomEvent(roomEvent('room-a', 1, 'participant_activity', {
        rootId: rootTurnId,
        dispatchId: 'dispatch:retry-wait',
        sourceEventType: 'turn_failed',
        status: 'retry_wait',
        retryAttempt: 2,
        summary: '模型连接中断，已进入有界重试等待',
        retryDelayMs: 1_000,
      }, {
        turnId: rootTurnId,
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
      })),
    ).state;
    const onAbortTurn = vi.fn();
    const room = roomSummary('room-a', '重试等待 Room');
    const roomTurn = () => <RoomTurn
      turnId={rootTurnId}
      roomId="room-a"
      room={room}
      projection={projection}
      personas={previewPersonas}
      onAbortTurn={onAbortTurn}
    />;

    const view = render(roomTurn());
    expect(screen.getAllByText('澄 正在等待第 2 次尝试')).toHaveLength(2);
    expect(screen.getByText(/1s 后重试/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '停止本轮任务' }));
    expect(onAbortTurn).toHaveBeenCalledWith(rootTurnId);

    projection = reduceRoomEvent(
      projection,
      parseRoomEvent(roomEvent('room-a', 2, 'turn_completed', {
        rootId: rootTurnId,
        dispatchId: 'dispatch:retry-wait',
        status: 'completed',
      }, {
        turnId: rootTurnId,
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
      })),
    ).state;
    view.rerender(roomTurn());

    expect(projection.turnsById[rootTurnId]).toMatchObject({
      status: 'running',
      terminalDispatchIds: ['dispatch:retry-wait'],
      failedDispatchIds: [],
      terminalParticipantIds: ['room-a:p1'],
      failedParticipantIds: [],
    });
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '停止本轮任务' })).not.toBeInTheDocument();
  });

  it('stops the whole server root through one Room cancellation command', async () => {
    const rootTurnId = 'room-turn:root-stop-1';
    const runningEvent = {
      ...roomEvent('room-a', 1, 'participant_status', {
        status: 'accepted',
        summary: '两位 Agent 已接手',
      }),
      turnId: rootTurnId,
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '整轮停止')] },
      'agent.room.snapshot': roomSnapshot('room-a', [runningEvent]),
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.abort': {
        schemaVersion: 'rag-ime.agent-room-abort.v1',
        ok: true,
        roomId: 'room-a',
        roomTurnId: rootTurnId,
        status: 'terminated',
        cancellationReceiptId: 'room-cancel:1',
        surfaces: {},
        pendingTargets: [],
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '停止本轮任务' }));

    await waitFor(() => {
      const request = transport.requests.find(
        (call) => call.request.pathId === 'agent.room.abort',
      )?.request;
      expect(request?.params).toEqual({ roomId: 'room-a' });
      expect(request?.body).toMatchObject({ roomTurnId: rootTurnId });
      expect(String((request?.body as Record<string, unknown>)?.clientRequestId))
        .toMatch(/^room-abort-/);
    });
    expect(screen.queryByRole('button', { name: '停止本轮任务' })).not.toBeInTheDocument();
  });

  it('keeps a root visibly active when any cancellation surface is unverified', async () => {
    const rootTurnId = 'room-turn:root-stop-pending';
    const runningEvent = {
      ...roomEvent('room-a', 1, 'participant_status', {
        status: 'accepted',
        summary: 'Agent 已接手',
      }),
      turnId: rootTurnId,
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
    };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '停止待确认')] },
      'agent.room.snapshot': roomSnapshot('room-a', [runningEvent]),
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.abort': {
        schemaVersion: 'rag-ime.agent-room-abort.v1',
        ok: false,
        roomId: 'room-a',
        roomTurnId: rootTurnId,
        status: 'cancellation_pending',
        cancellationReceiptId: 'room-cancel:pending',
        surfaces: {},
        pendingTargets: [
          { surface: 'provider', state: 'requested', targetIds: ['provider:1'] },
          { surface: 'shell', state: 'unknown', targetIds: ['shell:1', 'shell:2'] },
        ],
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '停止本轮任务' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '仍在确认：模型生成、命令行进程（2 项）',
    );
    expect(screen.getByRole('button', { name: '停止本轮任务' })).toBeEnabled();
  });

  it('shows only explicit Posts and hides internal Room execution events', () => {
    const room = roomSummary('room-a', '人类语言 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('route', 'hidden-tool', 'raw');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: ['assistant'], activityIds: ['route', 'hidden-tool', 'raw'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.messageOrder.push('assistant');
    projection.messagesById.assistant = {
      id: 'assistant', roomId: room.id, turnId: 'turn-a', participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1', role: 'assistant', status: 'completed', text: '公开回答', createdAtMs: 1,
      message: {
        schemaVersion: 'rag-ime.agent-message.v1', id: 'assistant', sessionId: 'room-a:s1',
        turnId: 'turn-a', role: 'assistant', status: 'completed', attachments: [], citations: [], createdAtMs: 1,
        blocks: [
          { id: 'reasoning', type: 'reasoning_summary', status: 'completed', presentationKind: 'reasoning_summary', data: { text: '秘密思考摘要' } },
          { id: 'text', type: 'text', status: 'completed', presentationKind: 'markdown', data: { text: '公开回答' } },
          { id: 'status', type: 'status', status: 'completed', presentationKind: 'status.v1', visibility: 'room_post', data: { title: '交付状态', state: 'completed', summary: '已通过刷新恢复' } },
          { id: 'checklist', type: 'checklist', status: 'completed', presentationKind: 'checklist.v1', visibility: 'room_post', data: { title: '公开验收', items: [{ id: 'room-post', text: 'Room Post 可重渲染', checked: true }] } },
          { id: 'private-card', type: 'card', status: 'completed', presentationKind: 'card.v1', visibility: 'private_session', data: { title: '私有 Session 中间稿', bodyMarkdown: '不应进入 Posts' } },
        ],
      },
    };
    projection.activitiesById.route = {
      id: 'route', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'route_decision', status: 'completed', summary: 'route_decision',
      payload: { routingPolicy: 'moderator', targetDisplayName: '澄' }, createdAtMs: 1,
    };
    projection.activitiesById['hidden-tool'] = {
      id: 'hidden-tool', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'completed', summary: '已完成一项内部工具步骤',
      payload: {}, createdAtMs: 1,
    };
    projection.activitiesById.raw = {
      id: 'raw', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'running', summary: 'participant_activity',
      payload: {}, createdAtMs: 1,
    };

    const { container } = render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.getByText('公开回答')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '交付状态' })).toHaveTextContent('已通过刷新恢复');
    expect(screen.getByText('Room Post 可重渲染')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('私有 Session 中间稿');
    expect(container).not.toHaveTextContent('不应进入 Posts');
    expect(container.querySelector('.room-group-activity')).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent('秘密思考摘要');
    expect(container).not.toHaveTextContent('participant_activity');
    expect(container).not.toHaveTextContent('route_decision');
  });

  it('keeps WorkItem responsibility details on the task page instead of duplicating them in the Room rail', () => {
    const room = roomSummary('room-a', '责任 Room');
    room.workItems = [{
      id: 'room-work:1',
      roomId: room.id,
      topicId: '',
      rootTurnId: 'turn-a',
      rootWorkId: 'room-work:1',
      parentWorkId: '',
      objective: '核对多端网关回放边界',
      expectedOutput: '测试与风险说明',
      acceptanceCriteria: ['回放不重复'],
      accountableParticipantId: 'room-a:p1',
      currentOwnerParticipantId: 'room-a:p2',
      offeredToParticipantId: '',
      createdByParticipantId: 'room-a:p1',
      clientMessageId: 'test-work-1',
      state: 'review',
      depth: 1,
      revision: 1,
      resultSummary: '已完成',
      artifactRefs: [],
      evidenceRefs: ['test:room-replay'],
      blocker: {},
      acceptedTurnId: 'turn-worker',
      createdAtMs: 1,
      updatedAtMs: 2,
      completedAtMs: null,
    }];

    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: [],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 2,
    };
    const onOpenProgress = vi.fn();
    render(<TooltipProvider><RoomStatusPanel
      room={room}
      projection={projection}
      open
      onClose={() => undefined}
      onOpenProgress={onOpenProgress}
    /></TooltipProvider>);

    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveTextContent('协作中');
    expect(screen.queryByText('核对多端网关回放边界')).not.toBeInTheDocument();
    expect(screen.queryByText('测试与风险说明')).not.toBeInTheDocument();
    expect(screen.queryByText('伙伴状态')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开任务页' }));
    expect(onOpenProgress).toHaveBeenCalledTimes(1);
  });

  it('does not duplicate repeated Room status updates in the compact sidebar', () => {
    const room = roomSummary('room-a', '状态聚合 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      status: 'completed',
      messageIds: [],
      activityIds: ['status-1', 'status-2', 'status-3'],
      participantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    for (const [index, id] of ['status-1', 'status-2', 'status-3'].entries()) {
      projection.activitiesById[id] = {
        id,
        turnId: 'turn-a',
        participantId: 'room-a:p1',
        sourceSessionId: 'room-a:s1',
        kind: 'participant_status',
        status: 'completed',
        summary: '协作状态已经同步',
        payload: {},
        createdAtMs: index + 1,
      };
    }
    const { container } = render(
      <TooltipProvider><RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} /></TooltipProvider>,
    );

    expect(container.querySelectorAll('.room-status-activity')).toHaveLength(0);
    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveTextContent('已完成');
  });

  it('keeps the 765x1568 status panel in normal top-to-bottom flow while a review waits', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 765 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 1_568 });
    const room = roomSummary('room-a', '窄屏审阅 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      status: 'completed',
      messageIds: [],
      activityIds: ['plan-review'],
      participantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.activitiesById['plan-review'] = {
      id: 'plan-review',
      turnId: 'turn-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'waiting',
      summary: '等待计划审阅',
      payload: { requestKind: 'plan_review', requestId: 'plan-review' },
      createdAtMs: 1,
    };

    const { container } = render(
      <TooltipProvider><RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} /></TooltipProvider>,
    );
    const body = container.querySelector<HTMLElement>('.agent-status-panel__body')!;
    const sections = [...body.querySelectorAll<HTMLElement>('.agent-status-section')];
    expect(getComputedStyle(body).display).toBe('flex');
    expect(getComputedStyle(body).flexDirection).toBe('column');
    expect(getComputedStyle(body).justifyContent).toBe('flex-start');
    expect(sections.every((section) => getComputedStyle(section).flexGrow === '0')).toBe(true);
    expect(screen.getAllByText('等待审阅')).toHaveLength(2);
    expect(screen.queryByText('协作中')).not.toBeInTheDocument();
    expect(screen.queryByText('已完成')).not.toBeInTheDocument();
  });

  it('keeps a running Room active after a recoverable tool failure', () => {
    const room = roomSummary('room-a', '恢复中 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      status: 'running',
      messageIds: [],
      activityIds: ['tool-failed'],
      participantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.activitiesById['tool-failed'] = {
      id: 'tool-failed',
      turnId: 'turn-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'tool_call',
      status: 'failed',
      summary: '运行命令失败',
      payload: { toolName: 'workspace_shell' },
      createdAtMs: 2,
    };

    const { container } = render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveAttribute('data-phase', 'running');
    expect(screen.getAllByText('协作中')).not.toHaveLength(0);
    expect(container.querySelector('.room-status-activity')).not.toBeInTheDocument();
  });

  it('keeps partner activity in the conversation stream instead of a duplicate sidebar feed', () => {
    const room = roomSummary('room-a', '公开进度 Room');
    const projection = createRoomProjection(room.id);
    projection.activityOrder.push('reasoning-a', 'tool-b');
    projection.activitiesById['reasoning-a'] = {
      id: 'reasoning-a',
      turnId: 'root-a',
      participantId: 'room-a:p1',
      sourceSessionId: 'room-a:s1',
      kind: 'participant_activity',
      status: 'running',
      summary: '正在核对恢复后的任务边界',
      payload: {
        rootId: 'root-a',
        sourceEventType: 'reasoning_summary',
        publicSummaryVersion: 'room-work-summary.v1',
        publicSummaryKind: 'alignment',
      },
      createdAtMs: 2,
      updatedAtMs: 2,
    };
    projection.activitiesById['tool-b'] = {
      id: 'tool-b',
      turnId: 'root-a',
      participantId: 'room-a:p2',
      sourceSessionId: 'room-a:s2',
      kind: 'participant_activity',
      status: 'running',
      summary: '正在读取公开检查记录',
      payload: { rootId: 'root-a', sourceEventType: 'tool_progress' },
      createdAtMs: 3,
      updatedAtMs: 3,
    };
    projection.turnOrder.push('root-a');
    projection.turnsById['root-a'] = {
      id: 'root-a', status: 'running', messageIds: [], activityIds: ['reasoning-a', 'tool-b'],
      participantIds: ['room-a:p1', 'room-a:p2'], createdAtMs: 1, updatedAtMs: 3,
    };

    const { container } = render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} />
      </TooltipProvider>,
    );
    expect(screen.queryByLabelText('实时进展与运行记录')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.room-status-public-lane')).toHaveLength(0);
    expect(container).not.toHaveTextContent('需求与交付边界梳理有新进展');
    expect(container).not.toHaveTextContent('正在读取公开检查记录');
    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveTextContent('协作中');
  });

  it('selects the newest hydrated task when snapshot update timestamps are absent', () => {
    const room = roomSummary('room-a', '任务顺序 Room');
    const kernel = createRoomKernelProjection(room.id);
    const older = {
      ...roomKernelRoot(room.id, 'completed', true, 0),
      rootId: 'root-old',
      createdAtMs: 1,
    };
    const newer = {
      ...roomKernelRoot(room.id, 'blocked', false, 0),
      rootId: 'root-new',
      createdAtMs: 2,
    };
    kernel.rootsById[older.rootId] = older;
    kernel.rootsById[newer.rootId] = newer;
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    const { container } = render(
      <TooltipProvider>
        <RoomStatusPanel
          room={room}
          projection={createRoomProjection(room.id)}
          open
          onClose={() => undefined}
        />
      </TooltipProvider>,
    );

    expect(container.querySelector('.room-status-panel > header')).toHaveTextContent(
      '需要处理阻塞',
    );
  });

  it('keeps confirmed progress visible and exposes recovery when the task stream is stale', () => {
    const room = roomSummary('room-a', '恢复进度 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'running', false, 4);
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);
    useRoomLiveStore.getState().setKernelSync(room.id, {
      state: 'stale',
      detail: '继续显示上次确认的进度',
      updatedAtMs: 120,
      failureAtMs: 140,
    });
    const onOpenProgress = vi.fn();

    render(
      <TooltipProvider>
        <RoomStatusPanel
          room={room}
          projection={createRoomProjection(room.id)}
          open
          onClose={() => undefined}
          onOpenProgress={onOpenProgress}
        />
      </TooltipProvider>,
    );

    const freshness = screen.getByRole('status', { name: '任务进度连接' });
    expect(freshness).toHaveTextContent('显示上次确认的进度');
    expect(screen.getByLabelText('整体任务与分工进度')).toHaveTextContent(
      '整体任务工作进行中',
    );
    fireEvent.click(screen.getByRole('button', { name: '打开任务进度' }));
    expect(onOpenProgress).toHaveBeenCalledTimes(1);
  });

  it('keeps the plain-language phase sequence visible while peer review is running', () => {
    const room = roomSummary('room-a', '共同检查 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'running', false, 4);
    kernel.tasksById['work-a'] = roomKernelTask('work-a', 'work', 'completed');
    kernel.tasksById['review-a'] = {
      ...roomKernelTask('review-a', 'review', 'active'),
      reviewOfTaskIds: ['work-a'],
      reviewAuthorParticipantIds: ['room-a:p2'],
      reviewState: 'in_review',
      reviewRound: 2,
      reviewTargetRevision: `sha256:${'a'.repeat(64)}`,
      reviewFindings: [
        {
          findingId: 'Finding-17',
          fingerprint: `sha256:${'b'.repeat(64)}`,
          gateEffect: 'blocking',
          impact: 'high',
          category: 'correctness',
          scope: { criterionId: 'criterion:gateway-replay' },
          observation: '网关断线重连后仍显示旧结果',
          expected: '重连后应显示最新结果',
          userImpact: '用户会看到过期状态',
          evidenceRefs: ['execution:review-read'],
          reproduction: ['断开网关', '恢复连接并查看状态'],
          state: 'open',
          dispositionRationale: null,
          ownerParticipantId: 'room-a:p1',
          firstSeenRevision: `sha256:${'c'.repeat(64)}`,
          lastCheckedRevision: `sha256:${'a'.repeat(64)}`,
          failedRechecks: 1,
          response: {
            findingId: 'Finding-17',
            action: 'fixed',
            rationale: '已刷新重连后的投影并补充验证',
            evidenceRefs: ['execution:facilitator-fix'],
            participantId: 'room-a:p1',
            createdAtMs: 5,
          },
        },
      ],
    };
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    const phase = screen.getByRole('region', { name: '当前协作阶段' });
    expect(phase).toHaveTextContent('各自工作');
    expect(phase).toHaveTextContent('一起检查');
    expect(phase).toHaveTextContent('0 / 1 位伙伴完成检查');
    const summary = within(phase).getByLabelText('整体任务与分工进度');
    expect(summary).toHaveTextContent('整体任务工作进行中');
    expect(summary).toHaveTextContent('分工完成1 / 2');
    expect(summary).toHaveTextContent('伙伴执行等待开始');
    expect(phase).not.toHaveTextContent('最终回复');
    expect(screen.queryByRole('button', { name: /独立复核/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Finding-17')).not.toBeInTheDocument();
    expect(screen.queryByText('网关断线重连后仍显示旧结果')).not.toBeInTheDocument();
  });

  it('keeps the internal Report task and dispatch out of peer progress', () => {
    const room = roomSummary('room-a', '报告统计 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'running', false, 5);
    kernel.tasksById['work-a'] = roomKernelTask('work-a', 'work', 'completed');
    kernel.tasksById['report-a'] = roomKernelTask('report-a', 'report', 'active');
    kernel.dispatchesById['dispatch-report-a'] = {
      schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
      dispatchId: 'dispatch-report-a',
      rootId: 'root-a',
      taskId: 'report-a',
      parentDispatchId: null,
      generation: 1,
      hopCount: 0,
      depth: 0,
      budgetCost: 1,
      targetSessionId: 'room-a:s1',
      targetParticipantId: 'room-a:p1',
      triggerId: 'trigger:report-a',
      intentKind: 'close',
      idempotencyKey: 'report-a',
      attempt: 1,
      capabilityEpoch: 1,
      runtimeProfileRevision: 'profile:report-a',
      state: 'running',
    };
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    const phase = screen.getByRole('region', { name: '当前协作阶段' });
    const summary = within(phase).getByLabelText('整体任务与分工进度');
    expect(phase).toHaveTextContent('1 / 1 项完成');
    expect(summary).toHaveTextContent('分工完成1 / 1');
    expect(summary).toHaveTextContent('伙伴执行等待开始');
    expect(phase).not.toHaveTextContent('1 / 2');
  });

  it('keeps review correction detail on the task page while the rail stays phase-only', () => {
    const room = roomSummary('room-a', '返修状态 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'running', false, 5);
    kernel.tasksById['work-a'] = roomKernelTask('work-a', 'work', 'completed');
    kernel.tasksById['review-a'] = {
      ...roomKernelTask('review-a', 'review', 'active'),
      reviewOfTaskIds: ['work-a'],
      reviewAuthorParticipantIds: ['room-a:p2'],
      reviewState: 'changes_requested',
      reviewRound: 2,
      reviewTargetRevision: `sha256:${'d'.repeat(64)}`,
    };
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    const phase = screen.getByRole('region', { name: '当前协作阶段' });
    expect(phase).toHaveTextContent('一起检查');
    expect(screen.queryByRole('button', { name: /独立复核/ })).not.toBeInTheDocument();
    expect(screen.queryByText('负责人正在按复核意见返修')).not.toBeInTheDocument();
  });

  it('keeps the final phase in the rail without duplicating the public reply', () => {
    const room = roomSummary('room-a', '最终回复 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'completed', true, 6);
    kernel.tasksById['work-a'] = roomKernelTask('work-a', 'work', 'completed');
    kernel.tasksById['review-a'] = {
      ...roomKernelTask('review-a', 'review', 'completed'),
      reviewOfTaskIds: ['work-a'],
      reviewAuthorParticipantIds: ['room-a:p2'],
      reviewState: 'accepted',
    };
    kernel.postOrder.push('final-post');
    kernel.postsById['final-post'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'final-post',
      roomId: room.id,
      rootId: 'root-a',
      generation: 1,
      authorActorRef: 'room-a:p1',
      kind: 'result',
      visibility: 'room',
      content: '每位伙伴的结果都已互相检查，这是最终公开回复。',
      idempotencyKey: 'final-post',
      publicationSource: { kind: 'room_commit', ref: 'commit-final' },
      createdAtMs: 6,
    };
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    const { container } = render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    const phase = screen.getByRole('region', { name: '当前协作阶段' });
    expect(phase).toHaveTextContent('各自工作');
    expect(phase).toHaveTextContent('一起检查');
    expect(phase).toHaveTextContent('最终回复');
    expect(container.querySelector('.room-status-final-reply')).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent('每位伙伴的结果都已互相检查，这是最终公开回复。');
  });

  it('keeps failure posts in the conversation instead of duplicating them in the status rail', () => {
    const room = roomSummary('room-a', '未完成回复 Room');
    const kernel = createRoomKernelProjection(room.id);
    kernel.rootsById['root-a'] = roomKernelRoot(room.id, 'failed', false, 8);
    kernel.postOrder.push('earlier-post', 'failed-post');
    kernel.postsById['earlier-post'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'earlier-post',
      roomId: room.id,
      rootId: 'root-a',
      generation: 1,
      authorActorRef: 'room-a:p1',
      kind: 'progress',
      visibility: 'room',
      content: '较早的公开进度',
      idempotencyKey: 'earlier-post',
      publicationSource: { kind: 'room_commit', ref: 'commit-earlier' },
      createdAtMs: 7,
    };
    kernel.postsById['failed-post'] = {
      ...kernel.postsById['earlier-post']!,
      postId: 'failed-post',
      kind: 'failure',
      content: '本轮未完成，伙伴已经给出可复核的最后说明。',
      idempotencyKey: 'failed-post',
      publicationSource: { kind: 'room_commit', ref: 'commit-failed' },
      createdAtMs: 8,
    };
    useRoomLiveStore.getState().setKernelProjection(room.id, kernel);

    const { container } = render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    expect(container.querySelectorAll('.room-status-final-reply')).toHaveLength(0);
    expect(container).not.toHaveTextContent('本轮未完成，伙伴已经给出可复核的最后说明。');
    expect(container).not.toHaveTextContent('较早的公开进度');
    expect(screen.getByRole('region', { name: '当前协作阶段' })).toHaveTextContent('最终回复');
  });

  it('labels a completed Room turn without a Post as completed in the status panel', () => {
    const room = roomSummary('room-a', '终态 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      status: 'completed',
      messageIds: [],
      activityIds: [],
      participantIds: ['room-a:p1'],
      createdAtMs: 1,
      updatedAtMs: 2,
    };

    render(
      <TooltipProvider>
        <RoomStatusPanel room={room} projection={projection} open onClose={() => undefined} />
      </TooltipProvider>,
    );

    expect(screen.getAllByText('已完成')).not.toHaveLength(0);
    expect(screen.queryByText('等待后续')).not.toBeInTheDocument();
  });
  it('renders managed image blocks from a Room user-message receipt', () => {
    const room = roomSummary('room-media', '图片 Room');
    const event = parseRoomEvent(roomEvent(room.id, 1, 'user_message', {
      messageId: 'room-media-message',
      text: '请查看这张图',
      attachmentReceipts: [{
        mediaId: 'media_room_image_01',
        ownerType: 'room',
        roomId: room.id,
        fileName: 'diagram.png',
        mimeType: 'image/png',
        byteSize: 128,
        sha256: 'a'.repeat(64),
        width: 640,
        height: 480,
      }],
    }, { turnId: 'room-media-turn' }));
    const projection = reduceRoomEvent(createRoomProjection(room.id), event).state;

    render(<RoomTurn turnId="room-media-turn" room={room} projection={projection} personas={previewPersonas} />);

    expect(screen.getByRole('img', { name: 'diagram.png' })).toHaveAttribute(
      'src',
      '/api/agent/media/media_room_image_01/content?roomId=room-media',
    );
  });

  it('coalesces only a shared event alias while preserving a distinct publication', () => {
    const room = roomSummary('room-identity', '事件身份 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-identity');
    projection.turnsById['turn-identity'] = {
      id: 'turn-identity',
      rootId: 'turn-identity',
      status: 'completed',
      messageIds: ['post-first', 'post-mirror', 'post-distinct'],
      activityIds: [],
      participantIds: ['room-identity:p1'],
      dispatchIds: ['dispatch-identity'],
      terminalParticipantIds: ['room-identity:p1'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      terminalDispatchIds: ['dispatch-identity'],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: { 'dispatch-identity': 'room-identity:p1' },
      createdAtMs: 1,
      updatedAtMs: 4,
    };
    const post = (id: string, sourceEventId: string, text: string, createdAtMs: number) => ({
      id,
      roomId: room.id,
      turnId: 'turn-identity',
      participantId: 'room-identity:p1',
      sourceSessionId: 'room-identity:s1',
      sourceEventId,
      role: 'assistant' as const,
      status: 'completed' as const,
      text,
      projectionKind: 'post' as const,
      rootId: 'turn-identity',
      dispatchId: 'dispatch-identity',
      createdAtMs,
      completedAtMs: createdAtMs,
    });
    projection.messageOrder.push('post-first', 'post-mirror', 'post-distinct');
    projection.messagesById['post-first'] = post('post-first', 'event-shared', '较早镜像', 1);
    projection.messagesById['post-mirror'] = post('post-mirror', 'event-shared', '同一事件的完整投影', 2);
    projection.messagesById['post-distinct'] = post('post-distinct', 'event-distinct', '同一事件的完整投影', 3);

    const { container } = render(
      <RoomTurn turnId="turn-identity" room={room} projection={projection} personas={previewPersonas} />,
    );

    expect(container.querySelectorAll('.room-agent-lane__post')).toHaveLength(2);
    expect(container.querySelectorAll('.room-conversation-post')).toHaveLength(2);
    expect(container.querySelectorAll('.room-agent-lane')).toHaveLength(1);
    expect(container).not.toHaveTextContent('较早镜像');
    expect(screen.getAllByText('同一事件的完整投影')).toHaveLength(2);
  });

});

function roomKernelTask(
  taskId: string,
  taskKind: RoomTaskV3['taskKind'],
  state: RoomTaskV3['state'],
): RoomTaskV3 {
  return {
    schemaVersion: 'wisdom-weasel.room-task.v3',
    taskId,
    rootId: 'root-a',
    parentTaskId: null,
    taskKind,
    currentOwnerParticipantId: taskKind === 'review' ? 'room-a:p2' : 'room-a:p1',
    ownershipRevision: 1,
    ownershipReceiptId: null,
    objective: taskKind === 'review' ? '检查伙伴结果' : '完成自己的部分',
    expectedOutput: '公开结果',
    requirementItemIds: [],
    acceptanceCriterionIds: [],
    contextEvidenceRefs: [],
    invitationId: null,
    reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [],
    reviewState: taskKind === 'review' ? 'required' : 'not_required',
    revision: 1,
    state,
  };
}

function roomKernelRoot(
  roomId: string,
  state: RootProjection['state'],
  isFinal: boolean,
  updatedAtMs: number,
): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root-a',
    roomId,
    generation: 1,
    state,
    facilitatorParticipantId: `${roomId}:p1`,
    reporterParticipantId: isFinal ? `${roomId}:p1` : null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement:root-a',
    createdByActorRef: 'user:1',
    terminalReceiptId: isFinal ? 'terminal:root-a' : null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget:default',
    independentReviewRequired: false,
    createdAtMs: 1,
    updatedAtMs,
    isFinal,
  };
}

function roomKernelSnapshot(roomId: string) {
  const root: Record<string, unknown> = {
    ...roomKernelRoot(roomId, 'running', false, 1),
  };
  delete root.isFinal;
  delete root.updatedAtMs;
  return {
    roomId,
    lastSequence: 1,
    snapshotHash: `sha256:${'0'.repeat(64)}`,
    roots: [root],
    tasks: [],
    dispatches: [],
    posts: [],
    sessions: [],
    receipts: [],
    cancellationSurfaces: [],
  };
}

function pickedRoomImage(
  id: string,
  name: string,
  shaCharacter: string,
): PickedFile {
  return {
    id,
    name,
    mimeType: 'image/png',
    byteSize: 128,
    roomId: 'room-a',
    sha256: shaCharacter.repeat(64).slice(0, 64),
  };
}

function roomSummary(roomId: string, title: string): RoomSummary {
  return {
    id: roomId,
    title,
    status: 'active',
    executionMode: 'workspace_managed',
    routingPolicy: 'moderator',
    moderatorParticipantId: `${roomId}:p1`,
    workspaceRoots: ['/Volumes/work/learnA'],
    updatedAtMs: 2,
    participants: [
      { id: `${roomId}:p1`, sessionId: `${roomId}:s1`, roleId: 'companion-present-v1', roleVersion: '1', displayName: '澄', collaborationRole: 'coordinator', status: 'active', ordinal: 0 },
      { id: `${roomId}:p2`, sessionId: `${roomId}:s2`, roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '澄·初', collaborationRole: 'researcher', status: 'active', ordinal: 1 },
    ],
  };
}


function roomSnapshot(roomId: string, events: ReturnType<typeof roomEvent>[], title?: string) {
  const room = roomSummary(roomId, title ?? (roomId === 'room-a' ? 'Room A' : roomId === 'room-b' ? 'Room B' : 'Room'));
  const lastSequence = events.at(-1)?.sequence ?? 0;
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      ...room,
      schemaVersion: 'rag-ime.agent-room.v1',
      createdAtMs: 1,
      lastEventSequence: lastSequence,
      participants: room.participants.map((participant) => ({
        ...participant,
        schemaVersion: 'rag-ime.agent-participant.v1',
        roomId,
        createdAtMs: 1,
        lastSpokeAtMs: null,
      })),
    },
    events,
    firstSequence: events[0]?.sequence ?? 0,
    lastSequence,
    resumeToken: lastSequence ? `${roomId}:${lastSequence}` : '',
    truncated: (events[0]?.sequence ?? 0) > 1,
  };
}

function roomQuestionEvent(
  roomId: string,
  sequence: number,
  question: {
    content: string;
    prompt: string;
    options: {
      value: string;
      label: string;
      description?: string;
      recommended?: boolean;
    }[];
  },
) {
  const rootId = `${roomId}:turn-${sequence}`;
  return roomEvent(roomId, sequence, 'room_post', {
    post: {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: `${roomId}:question-${sequence}`,
      roomId,
      rootId,
      generation: 0,
      dispatchId: `${roomId}:dispatch-${sequence}`,
      authorActorRef: `${roomId}:p1`,
      kind: 'wait',
      visibility: 'room',
      content: question.content,
      question: { prompt: question.prompt, options: question.options },
      idempotencyKey: `${roomId}:question-${sequence}`,
      publicationSource: { kind: 'room_commit', ref: `${roomId}:commit-${sequence}` },
      createdAtMs: sequence,
    },
  }, {
    turnId: rootId,
    participantId: `${roomId}:p1`,
    sourceSessionId: `${roomId}:s1`,
  });
}


function roomUserPostEvent(
  roomId: string,
  sequence: number,
  rootId: string,
  sourceRef: string,
  content: string,
) {
  return roomEvent(roomId, sequence, 'room_post', {
    post: {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: `${roomId}:user-post-${sequence}`,
      roomId,
      rootId,
      generation: 0,
      authorActorRef: 'user:local',
      kind: 'request',
      visibility: 'room',
      content,
      idempotencyKey: `user-message:${sourceRef}`,
      publicationSource: { kind: 'user', ref: sourceRef },
      createdAtMs: sequence,
    },
  }, {
    turnId: rootId,
    participantId: null,
    sourceSessionId: '',
  });
}

function roomTerminalPostEvent(
  roomId: string,
  sequence: number,
  kind: 'result' | 'handoff' | 'wait' | 'blocked',
  content: string,
) {
  const rootId = `${roomId}:turn-${sequence}`;
  return roomEvent(roomId, sequence, 'room_post', {
    post: {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: `${roomId}:${kind}-${sequence}`,
      roomId,
      rootId,
      generation: 0,
      dispatchId: `${roomId}:dispatch-${sequence}`,
      authorActorRef: `${roomId}:p1`,
      kind,
      visibility: 'room',
      content,
      ...(kind === 'handoff' ? { mentions: [`${roomId}:p2`] } : {}),
      idempotencyKey: `${roomId}:${kind}-${sequence}`,
      publicationSource: { kind: 'room_commit', ref: `${roomId}:commit-${sequence}` },
      createdAtMs: sequence,
    },
  }, {
    turnId: rootId,
    participantId: `${roomId}:p1`,
    sourceSessionId: `${roomId}:s1`,
  });
}

function roomEvent(
  roomId: string,
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
  identity: {
    turnId?: string;
    participantId?: string | null;
    sourceSessionId?: string;
  } = {},
) {
  return {
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `${roomId}:${sequence}`,
    roomId,
    sequence,
    turnId: identity.turnId ?? `${roomId}:turn-1`,
    eventType,
    participantId: identity.participantId ?? null,
    sourceSessionId: identity.sourceSessionId ?? '',
    createdAtMs: sequence,
    payload,
    resumeToken: `${roomId}:${sequence}`,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}
