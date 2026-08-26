import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewRoomSnapshot } from '@/app/preview-room-data';
import { TooltipProvider } from '@/components/primitives';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest, ControlTransport } from '@/platform/transport';
import type { RoomSummary } from '@/features/rooms/room-types';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PawWindowFrame } from '../shell/PawWindowLayer';
import { followRoomTimelineIfReaderAtEnd, PawRoomWorkspace } from './PawRoomWorkspace';

/* Lazy-bundle proof: this flag flips only when the PawStarfield module is
 * actually evaluated. Rendering the Room conversation must never flip it;
 * only pressing the 星空 button may. */
const starfieldChunk = vi.hoisted(() => ({ evaluated: false }));
vi.mock('./PawStarfield', async (importOriginal) => {
  starfieldChunk.evaluated = true;
  return await importOriginal();
});

const transcriptScrollTo = vi.fn();
Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
  configurable: true,
  value: transcriptScrollTo,
});

afterEach(() => {
  cleanup();
  transcriptScrollTo.mockReset();
});

describe('PAWOS Room collaboration tools', () => {
  it('does not let a late send receipt steal the Room timeline from a reader', () => {
    const timeline = document.createElement('div');
    const scrollTo = vi.fn();
    const scheduled: FrameRequestCallback[] = [];
    Object.defineProperties(timeline, {
      clientHeight: { configurable: true, value: 400 },
      scrollHeight: { configurable: true, value: 1_200 },
      scrollTo: { configurable: true, value: scrollTo },
    });

    timeline.scrollTop = 240;
    expect(followRoomTimelineIfReaderAtEnd(timeline, (callback) => {
      scheduled.push(callback);
      return scheduled.length;
    })).toBe(false);
    expect(scheduled).toHaveLength(0);

    timeline.scrollTop = 800;
    expect(followRoomTimelineIfReaderAtEnd(timeline, (callback) => {
      scheduled.push(callback);
      return scheduled.length;
    })).toBe(true);
    timeline.scrollTop = 300;
    scheduled[0]?.(0);
    expect(scrollTo).not.toHaveBeenCalled();

    timeline.scrollTop = 800;
    followRoomTimelineIfReaderAtEnd(timeline, (callback) => {
      scheduled.push(callback);
      return scheduled.length;
    });
    scheduled[1]?.(0);
    expect(scrollTo).toHaveBeenCalledOnce();
    expect(scrollTo).toHaveBeenCalledWith({ top: 1_200, behavior: 'smooth' });
  });

  it('steers an explicitly mentioned participant and keeps an ack-only receipt until the Room event arrives', async () => {
    const user = userEvent.setup();
    const snapshot = activeRoomSnapshot('room-steer-target');
    const room = snapshot.room as unknown as RoomSummary;
    const transport = new MockControlTransport({ routes: {
      'agent.room.snapshot': snapshot,
      'agent.room.participant.steer': { ok: true },
    } });
    renderRoom(901, vi.fn(), room, [], transport);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '@Mars 请优先核对依赖边界');
    await waitFor(() => expect(screen.getByRole('button', { name: '立即干预当前回合' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: '立即干预当前回合' }));

    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.room.participant.steer')).toBe(true));
    const request = transport.requests.find(({ request }) => request.pathId === 'agent.room.participant.steer')?.request;
    expect(request?.body).toMatchObject({
      participantId: 'participant-firstlight',
      message: '@Mars 请优先核对依赖边界',
    });
    expect(screen.getByRole('status', { name: '等待 Room 回执' })).toHaveTextContent('尚未送达伙伴 · Mars');
    expect(screen.getByText('@Mars 请优先核对依赖边界')).toBeInTheDocument();

    const clientActionId = String((request?.body as Record<string, unknown>).clientActionId);
    transport.emit('agent.room.events', {
      ...snapshot.events.at(-1),
      eventId: 'room-steer-target:4',
      sequence: 4,
      eventType: 'user_message',
      participantId: 'participant-firstlight',
      sourceSessionId: 'session-room-firstlight',
      payload: {
        text: '@Mars 请优先核对依赖边界',
        delivery: 'steer',
        rootId: 'room-steer-target:turn-1',
        clientActionId,
      },
      resumeToken: 'room-steer-target:4',
    });

    await waitFor(() => expect(screen.queryByRole('status', { name: '等待 Room 回执' })).not.toBeInTheDocument());
    expect(within(screen.getByRole('log', { name: 'Room 公开对话时间线' })).getByText('@Mars 请优先核对依赖边界')).toBeInTheDocument();

    await user.type(composer, '请继续同步');
    await user.click(screen.getByRole('button', { name: '立即干预当前回合' }));
    await waitFor(() => expect(transport.requests.filter(({ request }) => request.pathId === 'agent.room.participant.steer')).toHaveLength(2));
    const defaultRequest = transport.requests.filter(({ request }) => request.pathId === 'agent.room.participant.steer').at(-1)?.request;
    expect(defaultRequest?.body).toMatchObject({ participantId: 'participant-present', message: '请继续同步' });
  });

  it('rejects multiple active-turn mentions instead of silently choosing one participant', async () => {
    const user = userEvent.setup();
    const snapshot = activeRoomSnapshot('room-steer-ambiguous');
    const room = snapshot.room as unknown as RoomSummary;
    const transport = new MockControlTransport({ routes: {
      'agent.room.snapshot': snapshot,
      'agent.room.participant.steer': { ok: true },
    } });
    renderRoom(902, vi.fn(), room, [], transport);

    const composer = await screen.findByRole('textbox', { name: '协作消息' });
    await user.type(composer, '@Earth @Mars 请先对齐边界');
    await waitFor(() => expect(screen.getByRole('button', { name: '立即干预当前回合' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: '立即干预当前回合' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('当前回合只能点名一位伙伴');
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.room.participant.steer')).toBe(false);
    expect(composer).toHaveValue('@Earth @Mars 请先对齐边界');
  });

  it('opens as the same conversation-first workspace as Session and discloses collaboration on demand', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    const { container, room } = renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    const primaryNavigation = screen.getByRole('navigation', { name: 'Room 工作台视图' });
    expect(within(primaryNavigation).getAllByRole('button')).toHaveLength(3);
    expect(within(primaryNavigation).getByRole('button', { name: '公开对话' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(primaryNavigation).getByRole('button', { name: '协作态势' })).toHaveAttribute('aria-pressed', 'false');
    expect(within(primaryNavigation).getByRole('button', { name: '星空' })).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(openWindow).not.toHaveBeenCalled();

    const timeline = screen.getByRole('log', { name: 'Room 公开对话时间线' });
    const userMessage = within(timeline).getByText('并行实现 Room 任务图与依赖数据，整合后交给独立伙伴复核。').closest('article');
    expect(userMessage).not.toBeNull();
    expect(within(userMessage!).queryByText('你')).not.toBeInTheDocument();
    const earthMessage = within(timeline).getByText('我已把实时进展收拢在同一条消息里；完成后会在原处留下清晰结果。').closest('article');
    expect(within(earthMessage!).getByText('Earth')).toBeInTheDocument();
    expect(container.querySelector('.room-turn, .room-agent-lane')).toBeNull();

    await user.click(within(primaryNavigation).getByRole('button', { name: '协作态势' }));

    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    expect(within(tools).getAllByRole('tab')).toHaveLength(2);
    expect(within(tools).getByRole('tab', { name: '态势' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('region', { name: 'Room 当前协作' })).toHaveTextContent('任务图依赖验证');
    const mesh = within(tools).getByRole('group', { name: '协作网状图' });
    expect(mesh).toHaveTextContent('实现 Room 依赖数据投影');
    expect(mesh.querySelector(':scope > svg, .paw-room-focus-overview__mesh-edge-label')).toBeNull();
    expect(within(mesh).getByRole('list', { name: '协作关系' })).toBeInTheDocument();
    /* PF-CM-013/PF-CM-020：态势弹出是真实可达的卫星入口，指向 focus 面板。 */
    await user.click(within(tools).getByRole('button', { name: '在卫星窗中打开协作态势' }));
    expect(openWindow).toHaveBeenLastCalledWith(expect.objectContaining({
      appId: 'agent',
      target: expect.objectContaining({ kind: 'room', id: room.id, panel: 'focus' }),
    }));

    await user.click(within(tools).getByRole('button', { name: '关闭协作态势' }));

    expect(screen.getByRole('main', { name: /主 Room/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '协作消息' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(container.querySelector('.paw-room-workspace')).toHaveAttribute('data-panel', 'none');

    /* Default conversation path pays nothing for the sky: no region, no
     * canvas, and the starfield module itself was never evaluated. */
    expect(screen.queryByRole('region', { name: 'Room 星空' })).not.toBeInTheDocument();
    expect(starfieldChunk.evaluated).toBe(false);
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

  it('fronts a partner satellite only when the user explicitly clicks that planet', async () => {
    const user = userEvent.setup();
    const openWindow = vi.fn();
    renderRoom(900, openWindow);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协作态势' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    const mesh = within(tools).getByRole('group', { name: '协作网状图' });
    await user.click(within(mesh).getByRole('button', { name: /^Mars，/ }));
    await user.click(within(tools).getByRole('button', { name: '打开 Mars 伙伴窗口' }));

    expect(screen.queryByRole('button', { name: /铺开 .* 位/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Room 协作态势' })).not.toBeInTheDocument();
    expect(openWindow).toHaveBeenCalledTimes(1);
    expect(openWindow).toHaveBeenCalledWith(expect.objectContaining({
      target: expect.objectContaining({
        id: 'participant-firstlight',
        title: 'Mars',
        subtitle: '调研与证据',
      }),
    }));
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

    await user.click(screen.getByRole('button', { name: '协作态势' }));
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

    await user.click(screen.getByRole('button', { name: '协作态势' }));
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

  it.each([1, 7])('keeps the invite entry enabled with %i active participants', async (participantCount) => {
    const user = userEvent.setup();
    const room = roomWithParticipantCount(participantCount);
    const { container } = renderRoom(900, vi.fn(), room, [persona('candidate')]);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协作态势' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    await user.click(within(tools).getByRole('tab', { name: '治理' }));
    const governance = container.querySelector('.paw-room-governance') as HTMLElement;

    expect(within(governance).getByText(`${participantCount}/8`)).toBeInTheDocument();
    expect(within(governance).getByRole('combobox', { name: '邀请伙伴' })).toBeEnabled();
  });

  it('keeps the invite entry visible but disables it at the eight-participant backend limit', async () => {
    const user = userEvent.setup();
    const room = roomWithParticipantCount(8);
    const { container } = renderRoom(900, vi.fn(), room, [persona('candidate')]);
    await screen.findByRole('textbox', { name: '协作消息' });

    await user.click(screen.getByRole('button', { name: '协作态势' }));
    const tools = screen.getByRole('complementary', { name: 'Room 协作态势' });
    await user.click(within(tools).getByRole('tab', { name: '治理' }));
    const governance = container.querySelector('.paw-room-governance') as HTMLElement;

    expect(within(governance).getByText('8/8')).toBeInTheDocument();
    expect(within(governance).getByRole('combobox', { name: '邀请伙伴' })).toBeDisabled();
    expect(within(governance).getByRole('combobox', { name: '邀请伙伴' })).toHaveTextContent('已达 8 人上限');
  });
});

function renderRoom(
  width: number,
  openWindow = vi.fn(),
  record?: RoomSummary,
  personas: AgentPersonaV1[] = [],
  transport: ControlTransport = createPreviewTransport(),
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const room = record ?? previewRoomSnapshot('room-preview').room as unknown as RoomSummary;
  const requests: { request: ControlRequest }[] = [];
  const send = transport.request.bind(transport);
  transport.request = (request: ControlRequest) => {
    requests.push({ request });
    return send(request);
  };
  return {
    transport: { requests },
    ...render(
      <QueryClientProvider client={queryClient}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={openWindow}>
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
                  personas={personas}
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

function activeRoomSnapshot(roomId: string) {
  const snapshot = previewRoomSnapshot(roomId);
  const events = snapshot.events.slice(0, 3);
  return {
    ...snapshot,
    room: {
      ...snapshot.room,
      lastEventSequence: events.length,
    },
    events,
    firstSequence: 1,
    lastSequence: events.length,
    resumeToken: `${roomId}:${events.length}`,
  };
}

function roomWithParticipantCount(count: number): RoomSummary {
  const base = previewRoomSnapshot('room-capacity').room as unknown as RoomSummary;
  const seed = base.participants[0]!;
  return {
    ...base,
    moderatorParticipantId: 'participant-0',
    participants: Array.from({ length: count }, (_, ordinal) => ({
      ...seed,
      id: `participant-${ordinal}`,
      sessionId: `session-${ordinal}`,
      roleId: `role-${ordinal}`,
      displayName: `Agent ${ordinal + 1}`,
      ordinal,
    })),
  };
}

function persona(roleId: string): AgentPersonaV1 {
  return {
    schemaVersion: 'rag-ime.agent-persona.v1',
    roleId,
    version: '1',
    displayName: '候选伙伴',
    tagline: '候选',
    summary: '可邀请的候选伙伴',
    traits: ['协作'],
    visualProfile: { avatarAssetId: 'candidate', symbolName: 'person', accentToken: 'blue' },
    defaults: { modelPolicy: 'default', memoryPolicy: 'default', toolProfileVersion: '1' },
    runtimeCharacteristics: {
      intelligence: 'balanced', speed: 'balanced', context: 'balanced',
      suitableTasks: ['协作'], unsuitableTasks: ['无'], isDefault: false,
    },
    safetyPolicyVersion: 'agent-core-v2',
    selectableModes: ['assistant'],
  };
}
