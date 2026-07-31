import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { createRoomProjection, reduceRoomEvent } from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import { previewPersonas } from '@/features/agent/preview-data';
import type { ControlRequest, PickedFile } from '@/platform/transport';
import { RoomTurn, RoomsFeature, type RoomSummary } from './index';
import { RoomStatusPanel } from './RoomStatusPanel';
import { useRoomLiveStore } from './state/live-store';

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({
    data,
    itemContent,
  }: {
    data: string[];
    itemContent: (index: number, item: string) => ReactNode;
  }) => (
    <div data-testid="virtuoso-list">
      {data.map((item, index) => <div key={`${index}:${item}`}>{itemContent(index, item)}</div>)}
    </div>
  ),
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
  });

  it('opens the latest structured wait question and sends the selected contract value exactly once', async () => {
    const pendingSend = deferred<{ ok: true }>();
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '澄清 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-a', [
        roomQuestionEvent('room-a', 1, {
          content: '我需要你选择发布方式。',
          prompt: '这次采用哪一种发布方式？',
          options: [
            { value: 'A', label: '方案 A', description: '先发布预览版本', recommended: true },
            { value: 'B', label: '方案 B', description: '直接发布稳定版本' },
          ],
        }),
      ]),
      'agent.room.message': () => pendingSend.promise,
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const dialog = within(await screen.findByRole('dialog', { name: '伙伴需要你确认下一步' }));
    expect(dialog.getByText('这次采用哪一种发布方式？')).toBeInTheDocument();
    expect(dialog.getByText('推荐')).toBeInTheDocument();
    expect(dialog.getByRole('radio', { name: /方案 A/ })).not.toBeChecked();
    expect(dialog.getByRole('radio', { name: '方案 B' })).not.toBeChecked();

    dialog.getByRole('radio', { name: /方案 A/ }).focus();
    await user.keyboard('{ArrowDown}');
    expect(dialog.getByRole('radio', { name: '方案 B' })).toBeChecked();
    const submit = dialog.getByRole('button', { name: '发送回答' });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.room.message'),
    ).toHaveLength(1));
    expect(screen.getByRole('dialog', { name: '伙伴需要你确认下一步' })).toBeInTheDocument();
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: 'B',
      attachmentIds: [],
    });

    pendingSend.resolve({ ok: true });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '伙伴需要你确认下一步' })).not.toBeInTheDocument());
    expect(screen.getByRole('textbox', { name: '协作消息' })).toHaveFocus();
  });

  it('allows Escape and Cancel without hiding the inline post, then reopens after a full reload', async () => {
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

    await screen.findByRole('dialog', { name: '伙伴需要你确认下一步' });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '伙伴需要你确认下一步' })).not.toBeInTheDocument());
    expect(screen.getByText('请选择发布方式，回答后我会继续。')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toHaveFocus();
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.room.message')).toHaveLength(0);

    view.unmount();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const reloadedDialog = within(await screen.findByRole('dialog', { name: '伙伴需要你确认下一步' }));
    await user.click(reloadedDialog.getByRole('button', { name: '取消' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '伙伴需要你确认下一步' })).not.toBeInTheDocument());
    expect(screen.getByText('请选择发布方式，回答后我会继续。')).toBeInTheDocument();
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
        roomEvent('room-a', 2, 'user_message', { text: 'B' }, { turnId: 'room-a:turn-2' }),
        legacy,
      ]),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('请直接在对话中说明希望怎样继续。')).toBeInTheDocument();
    expect(screen.getByText('先选择一个发布方式。')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: '伙伴需要你确认下一步' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(3);
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

    expect(await screen.findByText('交付已经完成。')).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.room-agent-lane__post-kind')).map(
      (element) => element.textContent,
    )).toEqual(['任务汇报', '进度更新', '进度更新', '遇到的问题']);
  });

  it('keeps progress plus only the latest terminal post in one lane report', () => {
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
    expect(screen.queryByText('旧的等待说明')).not.toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('.room-agent-lane__post-kind')).map(
      (element) => element.textContent,
    )).toEqual(['进度更新', '任务汇报']);
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
    expect(within(report).getByText('任务汇报')).toBeInTheDocument();
    expect(within(report).getByText(/只读验收完成/)).toBeInTheDocument();
    expect(within(report).queryByText(/最终标记/)).not.toBeInTheDocument();
    await user.click(within(report).getByText('查看完整汇报'));
    expect(report).toHaveAttribute('open');
    expect(within(report).getByText(/最终标记/)).toBeInTheDocument();
  });

  it('opens only the newest unresolved structured question delivered live', async () => {
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

    const dialog = within(await screen.findByRole('dialog', { name: '伙伴需要你确认下一步' }));
    expect(dialog.getByText('最新的问题')).toBeInTheDocument();
    expect(dialog.queryByText('较早的问题')).not.toBeInTheDocument();
    expect(dialog.getAllByRole('radio')).toHaveLength(2);
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
      routingPolicy: 'natural',
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
    expect(screen.getByRole('checkbox', { name: /澄·远/ })).toHaveAccessibleName(/澄·远.*组织协作/);
    expect(screen.getByRole('checkbox', { name: /澄·远/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·今/ })).toHaveAccessibleName(/澄·今.*动手实现/);
    expect(screen.getByRole('checkbox', { name: /澄·今/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /澄·初/ })).toHaveAccessibleName(/澄·初.*独立验收/);
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
    expect(screen.getByText('所有待审批操作由独立审批 Agent（Luna Max）依据 Room 全局审批历史自动判定')).toBeInTheDocument();
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
    await user.click(screen.getByRole('option', { name: '独立验收' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.participant.update')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.update')?.request).toMatchObject({
      params: { roomId: room.id },
      body: { participantId: target.id, collaborationRole: 'reviewer' },
    });
    expect(screen.getByRole('combobox', { name: `${target.displayName} 负责什么` })).toHaveTextContent('独立验收');
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
    expect(screen.getByText('先对话澄清目标、交付物、验收和禁区；确认后再开始任务。')).toBeInTheDocument();
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
    expect(screen.getByText('伙伴状态')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收起进展面板' })).toBeInTheDocument();
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
    await user.click(screen.getByText(/看看可以使用哪些工具/));
    expect(screen.getByText('读取项目文件')).toBeInTheDocument();
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

  it('opens a generic selectable clarification in the owning Session', () => {
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
    expect(screen.getByText('等待选择')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /立即选择/ })).toHaveAttribute('href', '#/agent?session=room-a%3As1');
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

    expect(screen.getByText('在 …/project/rag_ime 搜索 “协作记录”')).toBeInTheDocument();
    expect(screen.getByText('搜索文本 · 进行中')).toBeInTheDocument();
    const toolSummary = screen.getByText('在 …/project/rag_ime 搜索 “协作记录”').closest('summary')!;
    expect(toolSummary).toHaveAttribute('aria-expanded', 'false');
    await user.click(toolSummary);
    expect(toolSummary).toHaveAttribute('aria-expanded', 'true');
    expect(document.activeElement).toBe(toolSummary);
    expect(screen.getByLabelText('工具调用参数')).toHaveTextContent('协作记录');
    expect(screen.getByLabelText('工具调用参数')).not.toHaveTextContent('room_event_projection');
    expect(screen.getByText(/1s/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '停止本轮任务' })).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: '停止本轮任务' }));
    expect(onAbortTurn).toHaveBeenCalledWith('room-turn:root-a');
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
      <RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />,
    );

    const row = container.querySelector<HTMLDetailsElement>('.room-agent-activity--tool')!;
    expect(row).not.toHaveAttribute('open');
    expect(row).toHaveTextContent('…/project/src/runtime.ts 已读取');
    expect(row).not.toHaveTextContent('settleRoom');
    await user.click(row.querySelector('summary')!);

    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('80');
    expect(within(row).getByLabelText('工具调用参数')).toHaveTextContent('24');
    expect(within(row).getByLabelText('工具返回内容')).toHaveTextContent('settleRoom');
    await user.click(within(row).getByRole('button', { name: '复制结果' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(
      '80:export function settleRoom() {\\n81:  return receipt;\\n82:}',
    ));
  });

  it('keeps humane Room receipt semantics while hiding protocol identifiers', async () => {
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
    const returned = within(row).getByLabelText('工具结果明细');
    expect(returned).toHaveTextContent('成功');
    expect(returned).toHaveTextContent('可用');
    expect(returned).toHaveTextContent('无变更');
    expect(returned).toHaveTextContent('状态版本');
    expect(returned).toHaveTextContent('第 12 版');
    expect(returned).toHaveTextContent('验证依据已保留');
    expect(returned).toHaveTextContent('当前职责');
    expect(returned).toHaveTextContent('状态：进行中');
    expect(returned).not.toHaveTextContent('safe-room-receipt-42');
    expect(returned).not.toHaveTextContent('executionPerformed');
    expect(returned).not.toHaveTextContent('stateRevision');
    expect(returned).not.toHaveTextContent('evidenceRef');
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
    expect(container.querySelector('.room-agent-lane__activity > summary')).toHaveTextContent('读取文件');
    expect(container.querySelector('.room-agent-lane__activity > summary')).toHaveTextContent('2 个步骤 · 全部完成');
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

  it('shows WorkItem responsibility, owner, and review state in the Room status panel', () => {
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

    render(<TooltipProvider><RoomStatusPanel room={room} projection={createRoomProjection(room.id)} open onClose={() => undefined} /></TooltipProvider>);

    expect(screen.getByText('任务分工')).toBeInTheDocument();
    const workRow = screen.getByText('核对多端网关回放边界').closest<HTMLElement>('.room-status-work__item')!;
    expect(within(workRow).getByText('待验收')).toBeInTheDocument();
    expect(within(workRow).getByText('澄·初')).toBeInTheDocument();
    expect(within(workRow).getByText('澄')).toBeInTheDocument();
    expect(within(workRow).getByText('第 1 次')).toBeInTheDocument();
    expect(within(workRow).getByText('测试与风险说明')).toBeInTheDocument();
    const rulesButton = screen.getByRole('button', { name: /协作规则/ });
    expect(rulesButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('最终验收人保持明确')).toBeInTheDocument();
    expect(screen.getByText('不会无限循环')).toBeInTheDocument();
    expect(screen.getByText('查资料与核对 · 已加入')).toBeInTheDocument();
    expect(screen.queryByText(/只读调研/)).not.toBeInTheDocument();
  });

  it('collapses repeated Room status updates into one readable sidebar step', () => {
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

    expect(container.querySelectorAll('.room-status-activity')).toHaveLength(1);
    expect(container.querySelector('.room-status-activity')).toHaveTextContent('状态同步');
    expect(container.querySelector('.room-status-activity')).toHaveTextContent('合并 3 次更新');
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
});

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
