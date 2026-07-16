import type { ReactNode } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { createRoomProjection } from '@/contracts/room-reducer';
import { previewPersonas } from '@/features/agent/preview-data';
import type { ControlRequest } from '@/platform/transport';
import { RoomTurn, RoomsFeature, type RoomSummary } from './index';

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
  afterEach(cleanup);

  it('sends messages through the room path and preserves the selected room id', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': {
        ok: true,
        items: [{
          id: 'room-a', title: '迁移作战室', status: 'active', routingPolicy: 'moderator',
          moderatorParticipantId: 'p1', updatedAtMs: Date.now(),
          participants: [
            { id: 'p1', sessionId: 's1', roleId: 'zhiyou-v1', roleVersion: '1', displayName: '智鼬', status: 'active', ordinal: 0 },
            { id: 'p2', sessionId: 's2', roleId: 'hermes-v1', roleVersion: '1', displayName: '智鼬·初识', status: 'active', ordinal: 1 },
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
    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    const errorSlot = document.querySelector('.room-error-slot');
    expect(errorSlot).toBeInTheDocument();
    expect(errorSlot).toBeEmptyDOMElement();
    expect(errorSlot?.nextElementSibling).toHaveClass('room-timeline');
    expect(errorSlot?.nextElementSibling?.nextElementSibling).toHaveClass('room-composer-shell');
    await user.type(composer, '并行核对边界');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request;
    expect(request?.params).toEqual({ roomId: 'room-a' });
    expect(request?.body).toMatchObject({ message: '并行核对边界' });
    expect(transport.subscriptionCalls[0]?.request).toMatchObject({
      pathId: 'agent.room.events',
      params: { roomId: 'room-a' },
      lastEventId: 'room-a:1',
    });
  });

  it('removes an optimistic message and restores the draft when the real API rejects it', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '失败恢复 Room')] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.message': () => {
        throw new Error('POST /api/agent/rooms/room-a/messages failed: receipt=/tmp/private.json');
      },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);
    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '不要留下假的乐观消息');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

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
      displayName: '智鼬·晨光',
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
    const create = await screen.findByRole('button', { name: '新建 Room' });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    await user.type(screen.getByRole('textbox', { name: 'Room 名称' }), '发布前检查');
    await user.click(screen.getByRole('button', { name: '创建 Room' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.rooms.create')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.rooms.create')?.request;
    expect(request?.body).toEqual({
      title: '发布前检查',
      participants: roleCatalog.map((persona) => ({
        roleId: persona.roleId,
        roleVersion: persona.version,
        displayName: persona.displayName,
      })),
      routingPolicy: 'moderator',
      moderatorRoleId: userCreatedPersona.roleId,
      workspaceRoots: ['/Volumes/work/learnA'],
    });
    expect(await screen.findByRole('button', { name: '打开 Room：发布前检查' })).toHaveAttribute('aria-current', 'true');
    expect(screen.queryByRole('dialog', { name: '新建协作 Room' })).not.toBeInTheDocument();
  });

  it('requires a project path and defaults collaboration control to 智鼬·未来', async () => {
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

    await user.click(await screen.findByRole('button', { name: '新建 Room' }));
    expect(screen.getByRole('button', { name: '创建 Room' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /智鼬·未来/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·此刻/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·初识/ })).toBeChecked();
    expect(screen.getByRole('combobox', { name: 'Room 主持人' })).toHaveTextContent('智鼬·未来');

    await user.click(screen.getByRole('button', { name: '选择项目目录' }));
    expect(transport.filePickCalls).toEqual([{
      purpose: 'workspace-root',
      selection: 'directory',
      multiple: false,
      maxFiles: 1,
    }]);
    expect(screen.getByText('/Volumes/work/learnA')).toBeInTheDocument();
  });

  it('archives a Room only after the real API confirms the state change', async () => {
    const archived = { ...roomSummary('room-a', '待归档 Room'), status: 'archived' };
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '待归档 Room')] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.room.archive': { ok: true, room: archived },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '归档 Room' }));
    await user.click(screen.getByRole('button', { name: '归档' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request;
    expect(request).toMatchObject({ params: { roomId: 'room-a' }, body: { archived: true } });
    expect(await screen.findByText('选择一个 Room，或新建协作 Room。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开 Room：待归档 Room' })).not.toBeInTheDocument();
  });

  it('restores an archived Room through the same real state transition', async () => {
    const archived = { ...roomSummary('room-a', '已归档 Room'), status: 'archived' };
    const restored = { ...archived, status: 'active' };
    const snapshot = roomSnapshot('room-a', [], '已归档 Room');
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

    await user.click(await screen.findByRole('button', { name: '显示已归档 Room' }));
    await user.click(await screen.findByRole('button', { name: '恢复 Room' }));
    await user.click(screen.getByRole('button', { name: '恢复' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request).toMatchObject({
      params: { roomId: 'room-a' },
      body: { archived: false },
    });
    expect(screen.getByRole('textbox', { name: 'Room 消息' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '归档 Room' })).toBeInTheDocument();
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '核对角色创建契约');
    expect(screen.getByRole('button', { name: '发送 Room 消息' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '智鼬·初识' }));
    expect(composer).toHaveValue('@智鼬·初识 核对角色创建契约');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '@智鼬·初识 核对角色创建契约',
    });
  });

  it('disables the composer instead of exposing an inert send action without a Room', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('选择一个 Room，或新建协作 Room。')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Room 消息' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '发送 Room 消息' })).toBeDisabled();
  });

  it('shows a useful empty conversation state after a real empty snapshot', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-empty', '空 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-empty', [], '空 Room'),
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('还没有对话，发一条消息开始协作。')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Room 消息' })).toBeEnabled();
  });

  it('opens the shared status experience for the selected Room', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [roomSummary('room-status', '状态 Room')] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.room.snapshot': roomSnapshot('room-status', [], '状态 Room'),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await screen.findByText('还没有对话，发一条消息开始协作。');
    await user.click(screen.getByRole('button', { name: '展开 Room 状态' }));
    expect(screen.getByRole('complementary', { name: 'Room 状态' })).toHaveAttribute('data-open', 'true');
    expect(screen.getByText('协作成员')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '收起 Room 状态' })).toBeInTheDocument();
  });

  it('keeps the real role catalog usable when the Room list request fails', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': () => { throw new Error('room catalog unavailable'); },
      'agent.roles.list': { ok: true, items: previewPersonas },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByRole('alert')).toHaveTextContent('Rooms 暂时无法读取，请稍后重试。');
    const create = screen.getByRole('button', { name: '新建 Room' });
    expect(create).toBeEnabled();
    await user.click(create);
    expect(screen.getByRole('dialog', { name: '新建协作 Room' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /智鼬·此刻/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·初识/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·未来/ })).toBeChecked();
  });

  it('keeps a Room creation failure inside the dialog and preserves the draft', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.sessions.list': { ok: true, items: [{ id: 'existing', mode: 'coordinator', workspaceRoots: ['/Volumes/work/learnA'] }] },
      'agent.rooms.create': () => { throw new Error('Room 名称已存在'); },
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    const create = await screen.findByRole('button', { name: '新建 Room' });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    await user.type(screen.getByRole('textbox', { name: 'Room 名称' }), '发布前检查');
    await user.click(screen.getByRole('button', { name: '创建 Room' }));

    const dialog = screen.getByRole('dialog', { name: '新建协作 Room' });
    expect(await screen.findByRole('alert')).toHaveTextContent('Room 名称已存在');
    expect(dialog).toContainElement(screen.getByRole('alert'));
    expect(screen.getByRole('textbox', { name: 'Room 名称' })).toHaveValue('发布前检查');
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
      'agent.rooms.list': { ok: true, items: [roomSummary('room-a', '恢复 Room')] },
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

  it('loads and saves each Room participant runtime and tool policy', async () => {
    const room = roomSummary('room-a', '权限 Room');
    const session = {
      id: 'room-a:s1', mode: 'assistant', status: 'idle',
      toolProfileVersion: 'control-center-v1', toolAllowlistMode: 'profile', allowedTools: [],
    };
    const tools = [
      { id: 'ime_overview', displayName: '控制中心概览', description: '查看整体状态', sessionModes: ['assistant', 'coordinator'], operations: ['status'], profileOperations: { 'control-center-v1': ['status'], 'subagent-readonly-v1': ['status'] }, enabled: true },
      { id: 'ime_memory', displayName: '记忆与工具书', description: '检索记忆', sessionModes: ['assistant', 'coordinator'], operations: ['catalog'], profileOperations: { 'control-center-v1': ['catalog'], 'subagent-readonly-v1': ['catalog'] }, enabled: true },
      { id: 'workspace_read', displayName: '工作区读取', description: '读取工作区', sessionModes: ['coordinator'], operations: ['read'], profileOperations: { 'control-center-v1': ['read'], 'subagent-readonly-v1': [] }, enabled: false },
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [room] },
      'agent.room.snapshot': roomSnapshot('room-a', []),
      'agent.roles.list': { ok: true, items: previewPersonas },
      'agent.sessions.list': { ok: true, items: [session] },
      'agent.tools.list': { ok: true, items: tools },
      'agent.session.mode.update': (request: ControlRequest) => ({ ok: true, session: { ...session, ...(request.body as Record<string, unknown>), toolAllowlistMode: 'explicit' } }),
    } });
    const user = userEvent.setup();
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    await user.click(await screen.findByRole('button', { name: '配置 智鼬 的权限' }));
    expect(await screen.findByRole('dialog', { name: '智鼬的运行权限' })).toBeInTheDocument();
    expect(transport.requests.find((call) => call.request.pathId === 'agent.tools.list')?.request.query).toEqual({ sessionId: 'room-a:s1' });
    await user.click(screen.getByRole('radio', { name: '协调者' }));
    await user.click(screen.getByRole('radio', { name: '只读' }));
    await user.click(screen.getByRole('checkbox', { name: /记忆与工具书/ }));
    await user.click(screen.getByRole('button', { name: '保存权限' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.session.mode.update')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.session.mode.update')?.request).toMatchObject({
      params: { sessionId: 'room-a:s1' },
      body: {
        mode: 'coordinator',
        toolProfileVersion: 'subagent-readonly-v1',
        allowedTools: ['ime_overview'],
        workspaceRoots: ['/Volumes/work/learnA'],
      },
    });
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
    expect(screen.getByRole('link', { name: /前往审阅/ })).toHaveAttribute('href', '#/agent?session=room-a%3As1');
  });

  it('links a paused memory review activity to the exact participant Agent session', () => {
    const room = roomSummary('room-a', '记忆审阅 Room');
    const projection = createRoomProjection(room.id);
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('review:1');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['review:1'],
      participantIds: ['room-a:p1'], createdAtMs: 1, updatedAtMs: 1,
    };
    projection.activitiesById['review:1'] = {
      id: 'review:1', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'completed', summary: '等待审阅',
      payload: { requestKind: 'memory_review', runId: 'memory:run:1' }, createdAtMs: 1,
    };

    render(<RoomTurn turnId="turn-a" room={room} projection={projection} personas={previewPersonas} />);
    expect(screen.getByRole('link', { name: /立即审阅/ })).toHaveAttribute('href', '#/agent?session=room-a%3As1');
  });

  it('keeps group activity Persona avatars square on narrow layouts', () => {
    const room: RoomSummary = {
      id: 'room-a', title: '迁移作战室', status: 'active', routingPolicy: 'moderator',
      moderatorParticipantId: 'p1', updatedAtMs: Date.now(),
      participants: [
        { id: 'p1', sessionId: 's1', roleId: 'zhiyou-v1', roleVersion: '1', displayName: '智鼬', status: 'active', ordinal: 0 },
        { id: 'p2', sessionId: 's2', roleId: 'hermes-v1', roleVersion: '1', displayName: '智鼬·初识', status: 'active', ordinal: 1 },
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
    const avatar = document.querySelector<HTMLElement>('.room-group-activity p > .agent-persona-avatar');
    expect(avatar).toBeInTheDocument();
    const style = getComputedStyle(avatar!);
    expect(style.width).toBe('28px');
    expect(style.height).toBe('28px');
    expect(style.flex).toContain('0 0 28px');
  });

  it('turns internal Room event names into human-readable collaboration updates', () => {
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
        ],
      },
    };
    projection.activitiesById.route = {
      id: 'route', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'route_decision', status: 'completed', summary: 'route_decision',
      payload: { routingPolicy: 'moderator', targetDisplayName: '智鼬' }, createdAtMs: 1,
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
    expect(screen.getByText('智鼬 已接手')).toBeInTheDocument();
    expect(screen.getByText('由主持人安排处理这轮任务')).toBeInTheDocument();
    expect(screen.getByText('准备工作已经完成')).toBeInTheDocument();
    expect(screen.getByText('智鼬 正在处理')).toBeInTheDocument();
    expect(screen.getByText('公开回答')).toBeInTheDocument();
    expect(container.querySelector('.room-group-activity')).not.toHaveAttribute('open');
    expect(container).not.toHaveTextContent('秘密思考摘要');
    expect(container).not.toHaveTextContent('participant_activity');
    expect(container).not.toHaveTextContent('route_decision');
  });
});

function roomSummary(roomId: string, title: string): RoomSummary {
  return {
    id: roomId,
    title,
    status: 'active',
    routingPolicy: 'moderator',
    moderatorParticipantId: `${roomId}:p1`,
    workspaceRoots: ['/Volumes/work/learnA'],
    updatedAtMs: 2,
    participants: [
      { id: `${roomId}:p1`, sessionId: `${roomId}:s1`, roleId: 'zhiyou-v1', roleVersion: '1', displayName: '智鼬', collaborationRole: 'coordinator', status: 'active', ordinal: 0 },
      { id: `${roomId}:p2`, sessionId: `${roomId}:s2`, roleId: 'hermes-v1', roleVersion: '1', displayName: '智鼬·初识', collaborationRole: 'researcher', status: 'active', ordinal: 1 },
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

function roomEvent(
  roomId: string,
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return {
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `${roomId}:${sequence}`,
    roomId,
    sequence,
    turnId: `${roomId}:turn-1`,
    eventType,
    participantId: null,
    sourceSessionId: '',
    createdAtMs: sequence,
    payload,
    resumeToken: `${roomId}:${sequence}`,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
