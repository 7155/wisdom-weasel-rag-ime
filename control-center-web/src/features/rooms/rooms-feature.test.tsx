import type { ReactNode } from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { createRoomProjection } from '@/contracts/room-reducer';
import { previewPersonas } from '@/features/agent/preview-data';
import type { ControlRequest } from '@/platform/transport';
import { RoomTurn, RoomsFeature, type RoomSummary } from './index';
import { RoomStatusPanel } from './RoomStatusPanel';

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
            { id: 'p1', sessionId: 's1', roleId: 'companion-present-v1', roleVersion: '1', displayName: '智鼬', status: 'active', ordinal: 0 },
            { id: 'p2', sessionId: 's2', roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '智鼬·初识', status: 'active', ordinal: 1 },
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
    expect(screen.queryByAltText(/两位智鼬在私有工作区之间显式交接/)).not.toBeInTheDocument();
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '发送后不能空白等待');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

    expect(screen.getByText('发送后不能空白等待')).toBeInTheDocument();
    expect(screen.getByText('Room 路由')).toBeInTheDocument();
    expect(screen.getAllByText('正在发送').length).toBeGreaterThan(0);
    expect(composer).toHaveValue('');
    expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true);

    pending.resolve({ ok: true });
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '切换页面也要看得到我');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));
    expect(screen.getByText('切换页面也要看得到我')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '打开 Room：Room B' }));
    await screen.findByText('还没有公开 Post');
    await user.click(screen.getByRole('button', { name: '打开 Room：Room A' }));

    expect(await screen.findByText('切换页面也要看得到我')).toBeInTheDocument();
    expect(screen.getByText('Room 路由')).toBeInTheDocument();
    pendingRefresh.resolve(roomSnapshot('room-a', []));
    await waitFor(() => expect(roomASnapshotCalls).toBe(2));
    expect(screen.getByText('切换页面也要看得到我')).toBeInTheDocument();

    pendingSend.resolve({ ok: true });
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
      roomKind: 'collaboration',
      avatar: 'briefcase',
      description: '',
      scenarioPrompt: '',
      participants: roleCatalog.map((persona) => ({
        roleId: persona.roleId,
        roleVersion: persona.version,
        displayName: persona.displayName,
      })),
      routingConfig: {
        maxResponders: 1,
        naturalJitter: 0,
        fallbackParticipantId: '',
      },
      routingPolicy: 'natural',
      workspaceRoots: ['/Volumes/work/learnA'],
    });
    expect(await screen.findByRole('button', { name: '打开 Room：发布前检查' })).toHaveAttribute('aria-current', 'true');
    expect(screen.queryByRole('dialog', { name: '新建 Room' })).not.toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: '新建 Room' }));
    expect(screen.getByRole('button', { name: '创建 Room' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: /智鼬·未来/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·此刻/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /智鼬·初识/ })).toBeChecked();
    expect(screen.queryByRole('combobox', { name: 'Room 主持人' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: '发言方式' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '选择项目目录' }));
    expect(transport.filePickCalls).toEqual([{
      purpose: 'workspace-root',
      selection: 'directory',
      multiple: false,
      maxFiles: 1,
    }]);
    expect(screen.getByText('/Volumes/work/learnA')).toBeInTheDocument();
  });

  it('creates a roleplay Room without forcing a workspace or coordinator mode', async () => {
    const created = {
      ...roomSummary('room-roleplay', '深夜茶话会'),
      roomKind: 'roleplay' as const,
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

    await user.click(await screen.findByRole('button', { name: '新建 Room' }));
    await user.click(screen.getByRole('radio', { name: /角色群聊/ }));
    expect(screen.queryByRole('button', { name: '选择项目目录' })).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Room 名称' }), '深夜茶话会');
    await user.type(screen.getByRole('textbox', { name: 'Room 共同设定' }), '场景在安静的茶室。');
    await user.click(screen.getByRole('button', { name: '创建 Room' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.rooms.create')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.rooms.create')?.request.body).toMatchObject({
      title: '深夜茶话会',
      roomKind: 'roleplay',
      avatar: 'sparkles',
      scenarioPrompt: '场景在安静的茶室。',
      routingPolicy: 'natural',
      workspaceRoots: [],
      routingConfig: { maxResponders: 1, naturalJitter: 0.04, fallbackParticipantId: '' },
    });
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '说说你的看法');
    expect(screen.getByRole('button', { name: '发送 Room 消息' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '点名 Room 角色' }));
    await user.click(screen.getByRole('option', { name: /智鼬·初识/ }));
    expect(composer).toHaveValue('说说你的看法 @智鼬·初识 ');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '说说你的看法 @智鼬·初识',
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '@初');
    expect(await screen.findByRole('option', { name: /智鼬·初识/ })).toBeInTheDocument();
    await user.keyboard('{Enter}');
    expect(composer).toHaveValue('@智鼬·初识 ');

    await user.type(composer, '核对记忆召回{Enter}');
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '@智鼬·初识 核对记忆召回',
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

    const composer = await screen.findByRole('textbox', { name: 'Room 消息' });
    await user.type(composer, '@智鼬 @智鼬·初识 分别检查实现和证据');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

    await waitFor(() => expect(
      transport.requests.some((call) => call.request.pathId === 'agent.room.message'),
    ).toBe(true));
    expect(
      transport.requests.find((call) => call.request.pathId === 'agent.room.message')
        ?.request.body,
    ).toMatchObject({
      message: '@智鼬 @智鼬·初识 分别检查实现和证据',
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

    await user.click(await screen.findByRole('button', { name: 'Room 设置' }));
    await user.clear(screen.getByRole('textbox', { name: 'Room 设置名称' }));
    await user.type(screen.getByRole('textbox', { name: 'Room 设置名称' }), '新名称');
    await user.clear(screen.getByRole('textbox', { name: 'Room 设置简介' }));
    await user.type(screen.getByRole('textbox', { name: 'Room 设置简介' }), '新简介');
    await user.clear(screen.getByRole('textbox', { name: 'Room 设置共同设定' }));
    await user.type(screen.getByRole('textbox', { name: 'Room 设置共同设定' }), '新设定');
    await user.click(screen.getByRole('button', { name: '保存设置' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.archive')).toBe(true));
    const request = transport.requests.find((call) => call.request.pathId === 'agent.room.archive')?.request;
    expect(request).toMatchObject({
      params: { roomId: room.id },
      body: {
        title: '新名称',
        description: '新简介',
        scenarioPrompt: '新设定',
        routingPolicy: 'natural',
      },
    });
    expect(request?.body).not.toHaveProperty('roomKind');
  });

  it('adds 智鼬·未来 to an existing Room and can remove the member again', async () => {
    const initial = roomSummary('room-members', '成员管理 Room');
    const futurePersona = previewPersonas.find((persona) => persona.roleId === 'companion-future-v1')!;
    const futureParticipant = {
      id: 'room-members:p3', sessionId: 'room-members:s3', roleId: 'companion-future-v1', roleVersion: '1',
      displayName: '智鼬·未来', collaborationRole: 'executor' as const, status: 'active', ordinal: 2,
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

    await user.click(await screen.findByRole('button', { name: 'Room 设置' }));
    const invite = screen.getByRole('button', { name: `邀请 ${futurePersona.displayName} 加入 Room` });
    expect(invite).toBeEnabled();
    expect(screen.getByText(/不会重放此前完整聊天/)).toBeInTheDocument();
    await user.click(invite);

    await waitFor(() => expect(addCompleted).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.add')?.request).toMatchObject({
      params: { roomId: initial.id },
      body: { roleId: 'companion-future-v1', roleVersion: '1', collaborationRole: 'executor' },
    });
    const remove = await screen.findByRole('button', { name: '将 智鼬·未来 移出 Room' });
    expect(remove).toBeEnabled();
    await user.click(remove);
    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.participant.remove')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.participant.remove')?.request).toMatchObject({
      params: { roomId: initial.id },
      body: { participantId: 'room-members:p3' },
    });
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

    await user.click(await screen.findByRole('button', { name: 'Room 设置' }));
    await user.click(screen.getByRole('button', { name: '删除 Room' }));
    const confirm = screen.getByRole('textbox', { name: '输入 Room 名称确认永久删除' });
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
    expect(screen.queryByRole('button', { name: `打开 Room：${room.title}` })).not.toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: '管理 Room 话题' }));
    await user.type(screen.getByRole('textbox', { name: '话题名称' }), '发布风险');
    await user.type(screen.getByRole('textbox', { name: '话题摘要' }), '核对上线边界');
    await user.click(screen.getByRole('button', { name: '创建话题' }));
    await waitFor(() => expect(screen.getAllByText('发布风险').length).toBeGreaterThan(0));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.topic.create')?.request.body).toEqual({
      title: '发布风险',
      summary: '核对上线边界',
    });
    const topicDialog = within(screen.getByRole('dialog', { name: '话题管理' }));
    await user.click(topicDialog.getAllByRole('button', { name: '关闭' }).find((button) => !button.hasAttribute('aria-label'))!);
    await user.click(screen.getByRole('button', { name: '添加共享文件' }));

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
    expect(await screen.findByText('选择一个 Room')).toBeInTheDocument();
    const scene = screen.getByAltText(/此刻与未来两种任务角色核对结构化产物/);
    expect(scene).toHaveAttribute('width', '960');
    expect(scene).toHaveAttribute('height', '720');
    expect(scene).toHaveAttribute('loading', 'lazy');
    expect(screen.getByText('从 Rooms 列表选择，或新建协作 Room。')).toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: '发送 Room 消息' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '点名 Room 角色' }));
    await user.click(screen.getByRole('option', { name: /智鼬·初识/ }));
    expect(composer).toHaveValue('核对角色创建契约 @智鼬·初识 ');
    await user.click(screen.getByRole('button', { name: '发送 Room 消息' }));

    await waitFor(() => expect(transport.requests.some((call) => call.request.pathId === 'agent.room.message')).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.room.message')?.request.body).toMatchObject({
      message: '核对角色创建契约 @智鼬·初识',
      participantIds: ['room-a:p2'],
    });
  });

  it('disables the composer instead of exposing an inert send action without a Room', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.rooms.list': { ok: true, items: [] },
      'agent.roles.list': { ok: true, items: [] },
    } });
    render(<ControlTransportProvider transport={transport}><TooltipProvider><RoomsFeature /></TooltipProvider></ControlTransportProvider>);

    expect(await screen.findByText('选择一个 Room')).toBeInTheDocument();
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

    expect(await screen.findByText('还没有公开 Post')).toBeInTheDocument();
    expect(screen.getByText('发一条消息开始协作。')).toBeInTheDocument();
    expect(screen.getByAltText(/此刻与未来两种任务角色核对结构化产物/)).toHaveAttribute('src', '/companions/scenes/room-duoagent-handoff-v1.webp');
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

    await screen.findByText('还没有公开 Post');
    await user.click(screen.getByRole('button', { name: '展开 Room 证据' }));
    expect(screen.getByRole('complementary', { name: 'Room 状态' })).toHaveAttribute('data-open', 'true');
    expect(screen.getByText('协作成员上下文')).toBeInTheDocument();
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
    expect(screen.getByRole('dialog', { name: '新建 Room' })).toBeInTheDocument();
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

    const dialog = screen.getByRole('dialog', { name: '新建 Room' });
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

    await user.click(await screen.findByRole('radio', { name: 'Sessions' }));
    await user.click((await screen.findAllByRole('button', { name: '检查 Session' }))[0]!);
    expect(await screen.findByRole('dialog', { name: /智鼬 · 私有 Session Inspector/ })).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'agent.sessions.list').at(-1)?.request.query).toEqual({ includeArchived: true, includeInternal: true, limit: 500 });
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

  it('keeps private activity rows out of the public Post timeline', () => {
    const room: RoomSummary = {
      id: 'room-a', title: '迁移作战室', status: 'active', routingPolicy: 'moderator',
      moderatorParticipantId: 'p1', updatedAtMs: Date.now(),
      participants: [
        { id: 'p1', sessionId: 's1', roleId: 'companion-present-v1', roleVersion: '1', displayName: '智鼬', status: 'active', ordinal: 0 },
        { id: 'p2', sessionId: 's2', roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '智鼬·初识', status: 'active', ordinal: 1 },
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

  it('shows a bounded tool lifecycle immediately and stops only its participant session', async () => {
    const room = roomSummary('room-a', '实时执行 Room');
    const projection = createRoomProjection(room.id);
    const now = Date.now();
    projection.turnOrder.push('turn-a');
    projection.activityOrder.push('tool-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a', status: 'running', messageIds: [], activityIds: ['tool-a'],
      participantIds: ['room-a:p1'], createdAtMs: now - 1_200, updatedAtMs: now,
    };
    projection.activitiesById['tool-a'] = {
      id: 'tool-a', turnId: 'turn-a', participantId: 'room-a:p1', sourceSessionId: 'room-a:s1',
      kind: 'participant_activity', status: 'running', summary: '正在查找用户确认的历史输入',
      payload: {
        sourceEventType: 'tool_progress',
        toolName: 'ime_memory',
        toolCallId: 'call-a',
      },
      createdAtMs: now - 1_000,
    };
    const onAbortSession = vi.fn();
    const user = userEvent.setup();

    render(<RoomTurn
      turnId="turn-a"
      room={room}
      projection={projection}
      personas={previewPersonas}
      onAbortSession={onAbortSession}
    />);

    expect(screen.getByText('ime_memory 正在执行')).toBeInTheDocument();
    expect(screen.getByText('正在查找用户确认的历史输入')).toBeInTheDocument();
    expect(screen.getByText(/1s/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(onAbortSession).toHaveBeenCalledWith('room-a:s1');
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

    await user.click(await screen.findByRole('button', { name: '停止全部' }));

    await waitFor(() => {
      const request = transport.requests.find(
        (call) => call.request.pathId === 'agent.room.abort',
      )?.request;
      expect(request?.params).toEqual({ roomId: 'room-a' });
      expect(request?.body).toMatchObject({ roomTurnId: rootTurnId });
      expect(String((request?.body as Record<string, unknown>)?.clientRequestId))
        .toMatch(/^room-abort-/);
    });
    expect(screen.queryByRole('button', { name: '停止全部' })).not.toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: '停止全部' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '仍在确认：模型生成、命令行进程（2 项）',
    );
    expect(screen.getByRole('button', { name: '停止全部' })).toBeEnabled();
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

    expect(screen.getByText('责任账本')).toBeInTheDocument();
    expect(screen.getByText('核对多端网关回放边界')).toBeInTheDocument();
    expect(screen.getByText(/待验收 · A 最终负责：智鼬 · R 当前执行：智鼬·初识 · 第 1 次修订/)).toBeInTheDocument();
    expect(screen.getByText('责任边界')).toBeInTheDocument();
    expect(screen.getByText('A · 最终验收')).toBeInTheDocument();
    expect(screen.getByText('责任深度 3 · 根任务分派 6 · 最多返修 2 次')).toBeInTheDocument();
    expect(screen.getByText('调研者 · 已加入')).toBeInTheDocument();
    expect(screen.queryByText(/只读调研/)).not.toBeInTheDocument();
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
      { id: `${roomId}:p1`, sessionId: `${roomId}:s1`, roleId: 'companion-present-v1', roleVersion: '1', displayName: '智鼬', collaborationRole: 'coordinator', status: 'active', ordinal: 0 },
      { id: `${roomId}:p2`, sessionId: `${roomId}:s2`, roleId: 'companion-firstlight-v1', roleVersion: '1', displayName: '智鼬·初识', collaborationRole: 'researcher', status: 'active', ordinal: 1 },
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
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
