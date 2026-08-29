import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import { TooltipProvider } from '@/components/primitives';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { ControlRequest } from '@/platform/transport';
import type { RoomSummary } from '@/features/rooms/room-types';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { PawRoomWorkspace } from './PawRoomWorkspace';

/* Lazy-bundle proof: this flag flips only when the PawStarfield module is
 * actually evaluated. Rendering the Room conversation must never flip it;
 * only pressing the 星空 button may. */
const starfieldChunk = vi.hoisted(() => ({ evaluated: false }));
vi.mock('./PawStarfield', async (importOriginal) => {
  starfieldChunk.evaluated = true;
  return await importOriginal();
});

afterEach(cleanup);

describe('PAWOS Room collaboration tools', () => {
  it('hydrates a planet mention into the one shared Room composer', async () => {
    renderRoom(900, vi.fn(), undefined, undefined, '@Mars ');

    expect(await screen.findByRole('textbox', { name: '协作消息' })).toHaveValue('@Mars ');
  });

  it('uses one round sheet by default and enters collaboration mode only on explicit request', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const setCollaborationFocusGroup = vi.fn();
    const { container, room } = renderRoom(900, openWindow, undefined, undefined, undefined, undefined, setCollaborationFocusGroup);
    await screen.findByRole('textbox', { name: '协作消息' });

    const primaryNavigation = screen.getByRole('navigation', { name: 'Room 工作台视图' });
    expect(within(primaryNavigation).getAllByRole('button')).toHaveLength(4);
    expect(within(primaryNavigation).getByRole('button', { name: '任务表' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(primaryNavigation).getByRole('button', { name: '协同模式' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(primaryNavigation).getByRole('button', { name: '公开记录' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(primaryNavigation).getByRole('button', { name: '星空' })).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'rounds');

    const rounds = screen.getByRole('region', { name: 'Room 行星任务表' });
    expect(within(rounds).getByText('并行实现 Room 任务图与依赖数据，整合后交给独立伙伴复核。')).toBeInTheDocument();
    expect(within(rounds).getAllByRole('row')).toHaveLength(4);
    expect(screen.queryByRole('log', { name: 'Room 公开对话' })).not.toBeInTheDocument();
    expect(openWindow).not.toHaveBeenCalled();

    await user.click(within(primaryNavigation).getByRole('button', { name: '协同模式' }));
    expect(setCollaborationFocusGroup).toHaveBeenCalledWith(`room:${room.id}`);

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    expect(within(tools).getAllByRole('tab')).toHaveLength(2);
    expect(within(tools).getByRole('tab', { name: '态势' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('region', { name: 'Room 当前协作' })).toHaveTextContent('任务图依赖验证');
    expect(within(tools).getByRole('group', { name: '协作网状图' })).toHaveTextContent('实现 Room 依赖数据投影');
    /* 协同模式展开 Room 名册里的全部 active 行星；Runtime activity
       只负责窗口流光和状态，不能让空闲行星消失。 */
    await waitFor(() => expect(openWindow).toHaveBeenCalledTimes(3));
    expect(openWindow.mock.calls.map(([request]) => request.target.id)).toEqual([
      'participant-present',
      'participant-firstlight',
      'participant-future',
    ]);

    /* PF-CM-013/PF-CM-020：态势弹出是真实可达的协作窗口入口，指向 focus 面板。 */
    openWindow.mockClear();
    await user.click(within(tools).getByRole('button', { name: '在协作窗口中打开协作态势' }));
    expect(openWindow).toHaveBeenLastCalledWith(expect.objectContaining({
      appId: 'agent',
      target: expect.objectContaining({ kind: 'room', id: room.id, panel: 'focus' }),
    }));

    await user.click(within(tools).getByRole('button', { name: '关闭协作态势' }));

    expect(screen.getByRole('main', { name: /主 Room/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'rounds');

    /* Default conversation path pays nothing for the sky: no region, no
     * canvas, and the starfield module itself was never evaluated. */
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
    expect(starfieldChunk.evaluated).toBe(false);
  });

  it('opens every active Room planet when collaboration mode is requested', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    /* A distinct Room id keeps this running snapshot independent from the
       terminal preview Room already replayed by the preceding test. */
    const completed = previewRoomSnapshot('room-running-collaboration');
    /* Stop before either dispatched Partner reaches a terminal event. The
       Room roster also contains a third reviewer; all three active planets
       remain visible even though only two are currently executing. */
    const events = completed.events.slice(0, 6);
    const running = {
      ...completed,
      room: {
        ...completed.room,
        lastEventSequence: events.length,
      },
      events,
      lastSequence: events.length,
      resumeToken: `room-running-collaboration:${events.length}`,
    };
    renderRoom(
      900,
      openWindow,
      running.room as unknown as RoomSummary,
      running,
    );
    await screen.findByRole('textbox', { name: '协作消息' });
    expect(openWindow).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '协同模式' }));

    await waitFor(() => expect(openWindow).toHaveBeenCalledTimes(3));
    expect(openWindow.mock.calls.map(([request]) => request)).toEqual([
      expect.objectContaining({
        background: true,
        target: expect.objectContaining({ id: 'participant-present', title: 'Earth' }),
      }),
      expect.objectContaining({
        background: true,
        target: expect.objectContaining({ id: 'participant-firstlight', title: 'Mars' }),
      }),
      expect.objectContaining({
        background: true,
        target: expect.objectContaining({ id: 'participant-future', title: 'Venus' }),
      }),
    ]);
  });

  it('resumes a blocked WorkItem through the active Root and keeps failure retryable', async () => {
    const user = userEvent.setup();
    const completed = previewRoomSnapshot('room-blocked-resume');
    const events = completed.events.slice(0, 6);
    const blocked = {
      ...(completed.room as unknown as RoomSummary).workItems?.[0],
      id: 'room-work:blocked',
      rootTurnId: 'room-blocked-resume:turn-1',
      state: 'blocked',
      blocker: { reason: 'Runtime 暂时不可用', nextStep: '恢复后重新分派' },
    };
    const runningRoom = {
      ...completed.room,
      lastEventSequence: events.length,
      workItems: [blocked],
    };
    const running = {
      ...completed,
      room: runningRoom,
      events,
      lastSequence: events.length,
      resumeToken: `room-blocked-resume:${events.length}`,
    };
    const { transport } = renderRoom(
      900,
      vi.fn(),
      runningRoom as unknown as RoomSummary,
      running as unknown as ReturnType<typeof previewRoomSnapshot>,
      undefined,
      { ...blocked, state: 'active' },
    );
    await screen.findByRole('textbox', { name: '协作消息' });

    const resume = screen.getByRole('button', { name: '恢复 Earth 并重新分派' });
    await user.click(resume);
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'agent.room.workItem.resume'
      && request.params?.roomId === 'room-blocked-resume'
      && request.params?.workItemId === 'room-work:blocked'
      && (request.body as { actorParticipantId?: string }).actorParticipantId === 'participant-present'
    ))).toBe(true));
    expect(screen.queryByText('恢复失败')).not.toBeInTheDocument();
  });

  it('keeps opening later planets when one planet fails and retries that planet in place', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn()
      .mockImplementationOnce(() => { throw new Error('window unavailable'); })
      .mockImplementation(() => undefined);
    const completed = previewRoomSnapshot('room-collaboration-retry');
    const events = completed.events.slice(0, 6);
    const running = {
      ...completed,
      room: { ...completed.room, lastEventSequence: events.length },
      events,
      lastSequence: events.length,
      resumeToken: `room-collaboration-retry:${events.length}`,
    };
    renderRoom(
      900,
      openWindow,
      running.room as unknown as RoomSummary,
      running,
    );
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协同模式' }));

    await waitFor(() => expect(openWindow).toHaveBeenCalledTimes(3));
    expect(openWindow.mock.calls[0]?.[0]).toMatchObject({
      background: true,
      target: { id: 'participant-present', title: 'Earth' },
    });
    expect(openWindow.mock.calls[1]?.[0]).toMatchObject({
      background: true,
      target: { id: 'participant-firstlight', title: 'Mars' },
    });
    expect(openWindow.mock.calls[2]?.[0]).toMatchObject({
      background: true,
      target: { id: 'participant-future', title: 'Venus' },
    });
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('1 颗活跃行星未能打开');
    expect(within(alert).getByRole('button', { name: '重试打开 Earth' })).toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: '交给 Trace Agent' })).toBeInTheDocument();

    await user.click(within(alert).getByRole('button', { name: '重试打开 Earth' }));

    expect(openWindow).toHaveBeenCalledTimes(4);
    expect(openWindow.mock.calls[3]?.[0]).toMatchObject({
      background: true,
      target: { id: 'participant-present', title: 'Earth' },
    });
    expect(screen.queryByText('1 颗活跃行星未能打开')).not.toBeInTheDocument();
  });

  it('turns the whole Room into one clickable solar system in 星空 mode', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const { container } = renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    // Before the explicit 星空 click nothing starfield exists — neither the
    // region nor the module (the chunk stays un-fetched in production).
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
    expect(starfieldChunk.evaluated).toBe(false);

    await user.click(screen.getByRole('button', { name: '星空' }));

    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'starfield');
    // The sky is an immersive fullscreen overlay portaled to <body>; it
    // resolves through the lazy boundary, so the lookup awaits the chunk.
    const sky = await screen.findByRole('region', { name: 'Room 星空' });
    expect(starfieldChunk.evaluated).toBe(true);
    expect(sky).toHaveAttribute('data-immersive');
    expect(within(sky).getByText('Sol')).toBeInTheDocument();
    // The workspace behind the overlay keeps its state for the way back.
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();

    // Picking a planet opens its detail card; opening the partner window is
    // an explicit second action, so a stray click never steals the stage.
    await user.click(within(sky).getByRole('button', { name: /^Mars，/ }));
    const card = within(sky).getByRole('complementary', { name: '天体详情' });
    await user.click(within(card).getByRole('button', { name: '打开伙伴窗口' }));

    const foregroundCalls = openWindow.mock.calls.filter(([request]) => request.background === false);
    expect(foregroundCalls).toHaveLength(1);
    expect(foregroundCalls[0]?.[0]).toMatchObject({
      target: expect.objectContaining({
        kind: 'participant',
        id: 'participant-firstlight',
        title: 'Mars',
      }),
    });

    // The exit control returns to the conversation view and tears the whole
    // stage down: no region, no leftover sky DOM, nothing left animating.
    await user.click(within(sky).getByRole('button', { name: /返回 Room/ }));
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
    expect(document.querySelector('.paw-sf')).toBeNull();
    expect(document.querySelector('.paw-sf__canvas')).toBeNull();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-view', 'conversation');
  });

  it('links a selected task-table planet and its graph node while keeping collaboration open', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协同模式' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    const marsRow = document.querySelector<HTMLElement>('[data-planet-row$=":participant-firstlight"]')!;
    await user.click(marsRow.querySelector('td:nth-child(2)')!);

    expect(marsRow).toHaveAttribute('aria-selected', 'true');
    expect(within(tools).getByRole('button', { name: /^Mars，/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('complementary', { name: 'Room 协作态势' })).toBeInTheDocument();
    expect(openWindow).toHaveBeenCalledWith(expect.objectContaining({
      background: false,
      target: expect.objectContaining({ kind: 'participant', id: 'participant-firstlight', title: 'Mars' }),
    }));

    const mesh = within(tools).getByRole('group', { name: '协作网状图' });
    await user.click(within(mesh).getByRole('button', { name: /^Earth，/ }));
    const earthRow = document.querySelector<HTMLElement>('[data-planet-row$=":participant-present"]')!;
    expect(earthRow).toHaveAttribute('aria-selected', 'true');
    expect(within(mesh).getByRole('button', { name: /^Earth，/ })).toHaveAttribute('aria-pressed', 'true');
    expect(openWindow).toHaveBeenCalledWith(expect.objectContaining({
      background: false,
      target: expect.objectContaining({ kind: 'participant', id: 'participant-present', title: 'Earth' }),
    }));

    expect(screen.queryByRole('button', { name: /铺开 .* 位/ })).not.toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Room 协作态势' })).toBeInTheDocument();
    /* 自动展开只允许 background 调用；前台调用只来自用户选择的行星。 */
    const foregroundCalls = openWindow.mock.calls.filter(([request]) => request.background === false);
    expect(foregroundCalls).toHaveLength(2);
    expect(foregroundCalls[1]?.[0]).toMatchObject({
      target: expect.objectContaining({
        id: 'participant-present',
        title: 'Earth',
        subtitle: expect.not.stringContaining('Agent 2'),
      }),
    });
  });
  it('opens the tools panel on the same edge as the control that opens it', async () => {
    /* 按钮在右、面板在左 was the complaint: the 协作态势 control portals into
       the titlebar's trailing chrome slot, so the aside it opens has to land
       on the trailing edge too — declared, not left to DOM order. */
    const user = userEvent.setup();
    const { container } = renderRoom(900);
    await screen.findByRole('textbox', { name: '协作消息' });

    const chromeSlot = container.querySelector('.paw-window-titlebar > .paw-window-chrome-slot')!;
    expect(chromeSlot).not.toBeNull();
    expect(chromeSlot.querySelector('.paw-room-window-chrome')).not.toBeNull();
    expect(container.querySelector('.paw-window-leading-slot .paw-room-window-chrome')).toBeNull();

    await user.click(screen.getByRole('button', { name: '协同模式' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    expect(tools).toHaveAttribute('data-side', 'trailing');
    const body = container.querySelector('.paw-room-workspace__body')!;
    expect(body.lastElementChild).toBe(tools);
    expect(body.firstElementChild).toHaveClass('paw-room-workspace__main');
  });

  it('names the Room origin Sol only while a connected coordinator hosts it', async () => {
    const hosted = renderRoom(900);
    await screen.findByRole('textbox', { name: '协作消息' });
    expect(screen.getByLabelText('Agent 中的 Sol 协作模式')).toBeInTheDocument();
    expect(hosted.container.querySelector('.paw-room-window-chrome'))
      .toHaveAttribute('data-coordinator', 'true');
    expect(screen.getByLabelText('Sol 当前状态')).toBeInTheDocument();

    cleanup();

    const unhosted = previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
    const demoted = {
      ...unhosted,
      participants: unhosted.participants.map((participant) => ({
        ...participant,
        collaborationRole: participant.collaborationRole === 'coordinator'
          ? 'implementer'
          : participant.collaborationRole,
      })),
    };
    const { container } = renderRoom(900, vi.fn(), demoted);
    await screen.findByRole('textbox', { name: '协作消息' });

    expect(screen.queryByLabelText('Agent 中的 Sol 协作模式')).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-window-chrome')).not.toHaveAttribute('data-coordinator');
    expect(screen.queryByLabelText('Sol 当前状态')).not.toBeInTheDocument();
    expect(screen.getByLabelText('主 Room 当前状态')).toBeInTheDocument();
  });

  it('governs the Room with the product picker and one vocabulary for every choice', async () => {
    const user = userEvent.setup();
    const { container, transport } = renderRoom(900);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协同模式' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    await user.click(within(tools).getByRole('tab', { name: '治理' }));
    const governance = container.querySelector('.paw-room-governance') as HTMLElement;
    expect(governance).not.toBeNull();

    // Native dropdowns were the last previous-generation control left in the
    // Room: an OS-drawn popup opening over the PAWOS window.
    expect(governance.querySelector('select')).toBeNull();

    // Every picker used to spell its own choices out, so a member row saying
    // 实现与验证 sat beside a picker saying 实现, and the 空间设置 header saying
    // 每次确认 sat beside a picker saying 逐项确认.
    const roleRow = governance.querySelector('.paw-room-governance__members article') as HTMLElement;
    const memberName = within(roleRow).getByRole('combobox').getAttribute('aria-label')?.replace(' 的分工', '') ?? '';
    expect(within(roleRow).getByRole('combobox')).toHaveTextContent(roleRow.querySelector('small')?.textContent ?? '');
    expect(memberName).not.toBe('');

    await user.click(within(roleRow).getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getByRole('option', { name: '最终独立复核' })).toBeInTheDocument();
    expect(within(listbox).queryByRole('option', { name: '复核' })).toBeNull();

    await user.click(within(listbox).getByRole('option', { name: '最终独立复核' }));
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'agent.room.participant.update'
      && (request.body as { collaborationRole?: string }).collaborationRole === 'reviewer'
    ))).toBe(true));
  });
});

function renderRoom(
  width: number,
  openWindow = vi.fn(),
  record?: RoomSummary,
  snapshotOverride?: ReturnType<typeof previewRoomSnapshot>,
  initialDraft?: string,
  resumeResponse?: Record<string, unknown>,
  setCollaborationFocusGroup = vi.fn(),
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const room = record ?? previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
  const transport = createPreviewTransport();
  const requests: { request: ControlRequest }[] = [];
  const send = transport.request.bind(transport);
  transport.request = async <Response = unknown>(request: ControlRequest): Promise<Response> => {
    requests.push({ request });
    if (snapshotOverride && request.pathId === 'agent.room.snapshot') {
      return snapshotOverride as Response;
    }
    if (snapshotOverride && request.pathId === 'agent.room.get') {
      return { ok: true, room: snapshotOverride.room } as Response;
    }
    if (resumeResponse && request.pathId === 'agent.room.workItem.resume') {
      return { ok: true, workItem: resumeResponse } as Response;
    }
    return send<Response>(request);
  };
  return {
    transport: { requests },
    ...render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={openWindow} setCollaborationFocusGroup={setCollaborationFocusGroup}>
            <TooltipProvider>
              <PawWindowFrame
                active
                appId="agent"
                bounds={{ x: 0, y: 0, width, height: 720 }}
                onBoundsCommit={() => undefined}
                onClose={() => undefined}
                onFocus={() => undefined}
                onMinimize={() => undefined}
                onToggleMaximize={() => undefined}
                title={`Room ${width}`}
                windowChrome="agent-room"
                windowId={`room-${width}`}
                zIndex={10}
              >
                <PawRoomWorkspace
                  initialDraft={initialDraft}
                  personas={[]}
                  record={room}
                  recordId={room.id}
                  onRoomUpdated={vi.fn()}
                />
              </PawWindowFrame>
            </TooltipProvider>
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    ),
    room,
  };
}
