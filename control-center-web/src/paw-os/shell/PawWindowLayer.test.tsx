import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { memo, useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { pawApps, type PawAppId } from '../runtime/app-registry';
import type { PawWindowBounds, PawWindowNode } from '../runtime/desktop-store';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { usePawDesktopApi } from '../runtime/desktop-context';
import { PawWindowChromePortal } from './PawWindowChrome';
import { PawRoomFocusRail, PawWindowFrame, PawWindowLayer, roomWindowFlowGroups } from './PawWindowLayer';

vi.mock('../apps/PawApps', () => ({ PawAppProcess: () => null }));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('PAWOS compositor window frame', () => {
  it('does not bind Room flow to an unrelated Agent when the exact Room main is absent', () => {
    const projection = createRoomProjection('room-a');
    const windows = {
      session: windowNode('session', { kind: 'session', id: 'session-a', title: '普通 Session' }),
      participant: windowNode('participant', { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' }),
    };

    expect(roomWindowFlowGroups(windows, { 'room-a': projection })).toEqual([]);
  });

  it.each([
    {
      label: '普通 dispatch',
      id: 'dispatch-a',
      kind: 'dispatch',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      targetIds: ['participant-a'],
    },
    {
      label: '普通 route',
      id: 'route-a',
      kind: 'route',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      targetIds: ['participant-a'],
    },
    {
      label: 'ContextRef',
      id: 'context-a',
      kind: 'participant_activity',
      payload: { targetParticipantId: 'participant-a', contextRefs: ['context://room-a/brief'] },
      expectedKind: 'context',
      targetIds: ['participant-a'],
    },
    {
      label: 'approval',
      id: 'approval-a',
      kind: 'approval_required',
      payload: { approvalId: 'approval:a' },
      expectedKind: 'approval',
      targetIds: ['root'],
    },
    {
      label: 'intercom',
      id: 'intercom-a',
      kind: 'participant_activity',
      payload: { activityKind: 'intercom', targetParticipantId: 'participant-a' },
      expectedKind: 'request',
      targetIds: ['participant-a'],
    },
    {
      label: 'route_decision',
      id: 'route-decision-a',
      kind: 'route_decision',
      payload: { targetParticipantId: 'participant-a' },
      expectedKind: 'dispatch',
      targetIds: ['participant-a'],
    },
  ] as const)('projects $label activities into a WindowFlowPacket', ({ id, kind, payload, expectedKind, targetIds }) => {
    const projection = projectionWithActivity({ id, kind, payload, participantId: kind === 'approval_required' ? 'participant-a' : null });
    const windows = roomWindows();

    const groups = roomWindowFlowGroups(windows, { 'room-a': projection });

    expect(groups[0]?.packets).toEqual([
      expect.objectContaining({ id: `activity:${id}`, kind: expectedKind, targetIds }),
    ]);
  });

  it('only projects dispatch activity to participant points that are actually mounted', () => {
    const projection = createRoomProjection('room-a');
    projection.activityOrder.push('dispatch-a', 'dispatch-missing');
    projection.activitiesById['dispatch-a'] = activity({
      id: 'dispatch-a',
      kind: 'dispatch',
      payload: { targetParticipantId: 'participant-a' },
    });
    projection.activitiesById['dispatch-missing'] = activity({
      id: 'dispatch-missing',
      kind: 'dispatch',
      payload: { targetParticipantId: 'participant-missing' },
    });

    const groups = roomWindowFlowGroups(roomWindows(), { 'room-a': projection });

    expect(groups[0]?.packets.map((packet) => packet.id)).toEqual(['activity:dispatch-a']);
  });

  it('keeps narrow Room rail satellites draggable and resizable without duplicating host window chrome', async () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 560 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    const windows = narrowRoomWindows();
    window.localStorage.setItem('pawos.desktop.v1', JSON.stringify({
      windows,
      stack: Object.keys(windows),
      activeWindowId: 'main',
    }));

    try {
      render(
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawDesktopProvider>
            <EnterRoomFocus />
            <PawWindowLayer />
          </PawDesktopProvider>
        </ControlTransportProvider>,
      );

      await screen.findByRole('region', { name: 'Sol 行星窗口，横向滚动查看全部 5 个窗口' });
      const shell = await screen.findByLabelText('伙伴 1窗口');
      expect(shell).not.toHaveAttribute('data-focus-locked');
      expect(shell).toHaveAttribute('data-frame-mode', 'focus-card');
      expect(shell.querySelector('.paw-traffic-lights')).not.toBeInTheDocument();
      expect(within(shell).queryByRole('button', { name: '最小化窗口' })).not.toBeInTheDocument();
      expect(within(shell).getByRole('button', { name: '关闭伙伴窗口：伙伴 1' })).toBeInTheDocument();
      expect((await screen.findByLabelText('Room A窗口')).querySelectorAll('.paw-traffic-lights')).toHaveLength(1);
      expect(shell.querySelectorAll('.paw-window-resize')).toHaveLength(8);

      const initialTransform = shell.style.transform;
      const initialY = transformCoordinate(initialTransform, 'y');
      const initialWidth = Number.parseFloat(shell.style.width);
      const titlebar = shell.querySelector('.paw-window-titlebar')!;
      fireEvent.pointerDown(titlebar, { button: 0, clientX: 220, clientY: 500, pointerId: 41 });
      fireEvent.pointerMove(window, { clientX: 232, clientY: 508, pointerId: 41 });
      fireEvent.pointerUp(window, { clientX: 232, clientY: 508, pointerId: 41 });
      await waitFor(() => expect(transformCoordinate(shell.style.transform, 'y')).toBe(initialY + 8));

      const eastResize = shell.querySelector('[data-handle="east"]') as HTMLElement;
      fireEvent.pointerDown(eastResize, { button: 0, clientX: 500, clientY: 500, pointerId: 42 });
      fireEvent.pointerMove(window, { clientX: 520, clientY: 500, pointerId: 42 });
      fireEvent.pointerUp(window, { clientX: 520, clientY: 500, pointerId: 42 });
      await waitFor(() => expect(Number.parseFloat(shell.style.width)).toBe(initialWidth + 20));

      const lastShell = await screen.findByLabelText('伙伴 5窗口');
      const lastInitialX = transformCoordinate(lastShell.style.transform, 'x');
      expect(lastInitialX).toBeGreaterThan(window.innerWidth);
      const lastTitlebar = lastShell.querySelector('.paw-window-titlebar')!;
      fireEvent.pointerDown(lastTitlebar, { button: 0, clientX: 220, clientY: 500, pointerId: 43 });
      fireEvent.pointerMove(window, { clientX: 228, clientY: 500, pointerId: 43 });
      fireEvent.pointerUp(window, { clientX: 228, clientY: 500, pointerId: 43 });
      await waitFor(() => expect(transformCoordinate(lastShell.style.transform, 'x')).toBe(lastInitialX + 8));

      fireEvent.click(within(shell).getByRole('button', { name: '关闭伙伴窗口：伙伴 1' }));
      await waitFor(() => expect(screen.queryByLabelText('伙伴 1窗口')).not.toBeInTheDocument());
      await waitFor(() => expect(screen.queryByRole('region', { name: 'Sol 行星窗口，横向滚动查看全部 5 个窗口' })).not.toBeInTheDocument());
      expect(screen.getByLabelText('伙伴 2窗口')).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight });
    }
  });

  it('does not let the activation pointer overwrite a satellite focus frame with stale desktop bounds', async () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 900 });
    const windows = roomWindows();
    windows.participant = {
      ...windows.participant!,
      bounds: { x: 20, y: 26, width: 300, height: 228 },
    };
    window.localStorage.setItem('pawos.desktop.v1', JSON.stringify({
      windows,
      stack: ['participant', 'main'],
      activeWindowId: 'main',
      collaborationFocusGroup: null,
    }));

    try {
      render(
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawDesktopProvider>
            <PawWindowLayer />
          </PawDesktopProvider>
        </ControlTransportProvider>,
      );

      const shell = await screen.findByLabelText('伙伴 A窗口');
      const titlebar = shell.querySelector('.paw-window-titlebar')!;
      fireEvent.pointerDown(titlebar, { button: 0, clientX: 160, clientY: 80, pointerId: 44 });
      fireEvent.pointerUp(window, { clientX: 160, clientY: 80, pointerId: 44 });

      await waitFor(() => expect(shell).toHaveAttribute('data-focus-layout', 'true'));
      await waitFor(() => expect(shell.style.transform)
        .toBe(shell.style.getPropertyValue('--paw-focus-frame-transform')));
      expect(transformCoordinate(shell.style.transform, 'y')).toBeGreaterThanOrEqual(56);
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight });
    }
  });

  it('keeps every narrow Room satellite mounted in a keyboard-accessible horizontal rail', () => {
    render(
      <PawRoomFocusRail count={7} height={250} top={430} trackWidth={2040}>
        {Array.from({ length: 7 }, (_, index) => <button key={index} type="button">伙伴 {index + 1}</button>)}
      </PawRoomFocusRail>,
    );

    const rail = screen.getByRole('region', { name: 'Sol 行星窗口，横向滚动查看全部 7 个窗口' });
    expect(rail).toHaveAttribute('tabindex', '0');
    expect(rail).toHaveAttribute('data-satellite-count', '7');
    expect(rail).toHaveStyle({ height: '250px', top: '430px' });
    expect(rail.firstElementChild).toHaveStyle({ width: '2040px' });
    expect(within(rail).getAllByRole('button')).toHaveLength(7);
  });

  it('moves on the compositor and commits state only when the pointer finishes', () => {
    const commit = vi.fn();
    let processRenders = 0;
    const Process = memo(() => {
      processRenders += 1;
      return <div>independent App process</div>;
    });
    const initial = { x: 20, y: 30, width: 760, height: 560 };

    render(<FrameHarness initial={initial} onCommit={commit}><Process /></FrameHarness>);
    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;
    const shell = titlebar.closest('.paw-window-shell') as HTMLElement;

    fireEvent.pointerDown(titlebar, { button: 0, clientX: 100, clientY: 80, pointerId: 7 });
    fireEvent.pointerMove(window, { clientX: 164, clientY: 122, pointerId: 7 });

    expect(commit).not.toHaveBeenCalled();
    expect(processRenders).toBe(1);

    fireEvent.pointerUp(window, { clientX: 164, clientY: 122, pointerId: 7 });

    expect(commit).toHaveBeenCalledWith({ x: 84, y: 72, width: 760, height: 560 });
    expect(shell.style.transform).toBe('translate3d(84px, 72px, 0)');
    expect(processRenders).toBe(1);
  });

  it('exposes restore identity after a window is maximized', () => {
    render(<FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} placement="maximized" onCommit={() => undefined}><div /></FrameHarness>);

    expect(screen.getByRole('button', { name: '还原窗口' })).toHaveAttribute('data-action', 'restore');
    expect(screen.getByLabelText('Rooms窗口')).toHaveAttribute('data-placement', 'maximized');
  });

  it('drags and resizes the temporary focus frame instead of the ordinary desktop bounds', () => {
    const commit = vi.fn();
    render(<FrameHarness
      focusFrame={{ x: 100, y: 60, width: 420, height: 300 }}
      initial={{ x: 20, y: 30, width: 760, height: 560 }}
      onCommit={commit}
    ><div /></FrameHarness>);
    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;
    const shell = titlebar.closest('.paw-window-shell') as HTMLElement;

    expect(shell).toHaveStyle({ width: '420px', height: '300px', transform: 'translate3d(100px, 60px, 0)' });
    expect(shell.querySelectorAll('.paw-window-resize')).toHaveLength(8);
    fireEvent.pointerDown(titlebar, { button: 0, clientX: 120, clientY: 80, pointerId: 9 });
    fireEvent.pointerMove(window, { clientX: 180, clientY: 110, pointerId: 9 });
    fireEvent.pointerUp(window, { clientX: 180, clientY: 110, pointerId: 9 });

    expect(commit).toHaveBeenCalledWith({ x: 160, y: 90, width: 420, height: 300 });
  });

  it('lets a keyboard user resize the active window from a named edge handle', () => {
    const commit = vi.fn();
    render(<FrameHarness initial={{ x: 40, y: 50, width: 420, height: 300 }} onCommit={commit}><div /></FrameHarness>);

    const eastHandle = screen.getByRole('button', { name: '调整窗口右边缘' });
    expect(eastHandle).toHaveAttribute('aria-keyshortcuts', 'ArrowLeft ArrowRight');
    expect(eastHandle).toHaveAttribute('tabindex', '0');

    fireEvent.keyDown(eastHandle, { key: 'ArrowRight' });

    expect(commit).toHaveBeenCalledWith({ x: 40, y: 50, width: 436, height: 300 });
  });

  it('projects live Browser tabs into the window titlebar without copying their state', () => {
    render(
      <FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} onCommit={() => undefined} windowChrome="browser-tabs">
        <LiveBrowserTabs />
      </FrameHarness>,
    );

    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar') as HTMLElement;
    const tablist = within(titlebar).getByRole('tablist', { name: 'Browser tabs' });
    expect(within(tablist).getByRole('tab', { name: 'PAW' })).toHaveAttribute('aria-selected', 'true');
    fireEvent.click(within(tablist).getByRole('button', { name: 'New tab' }));
    fireEvent.click(within(tablist).getByRole('tab', { name: 'Docs' }));

    expect(within(titlebar).getByRole('tab', { name: 'Docs' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('selected-tab')).toHaveTextContent('Docs');
    expect(titlebar).toHaveAttribute('data-window-chrome', 'browser-tabs');
  });

  it('hosts Room view, runtime, and actions in the single compositor titlebar', () => {
    render(
      <FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} onCommit={() => undefined} windowChrome="room-workspace">
        <LiveRoomChrome />
      </FrameHarness>,
    );

    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar') as HTMLElement;
    expect(within(titlebar).getByRole('navigation', { name: 'Room 工作台视图' })).toHaveTextContent('对话');
    expect(within(titlebar).getByRole('status')).toHaveTextContent('协作中');
    expect(titlebar).toHaveAttribute('data-window-chrome', 'room-workspace');
    expect(screen.getByTestId('room-canvas').querySelector('header')).toBeNull();
  });

  it('uses the purple Room identity for an Agent window in Room mode', () => {
    render(
      <FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} onCommit={() => undefined} overview targetKind="room">
        <div />
      </FrameHarness>,
    );

    const shell = screen.getByLabelText('Rooms窗口');
    expect(shell).toHaveAttribute('data-app', 'agent');
    expect(shell.querySelector('.paw-window-title [data-paw-app-icon="room"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '打开 Rooms' }).querySelector('[data-paw-app-icon="room"]')).toBeInTheDocument();
    expect(shell.querySelector('.paw-window-title [data-paw-app-icon="agent"]')).toBeNull();
  });

  it.each(pawApps)('uses the original $id identity in the titlebar and window overview', (app) => {
    const { container } = render(
      <FrameHarness appId={app.id} initial={{ x: 0, y: 0, width: 760, height: 560 }} onCommit={() => undefined} overview>
        <div />
      </FrameHarness>,
    );

    const shell = screen.getByLabelText('Rooms窗口');
    expect(shell).toHaveAttribute('data-app', app.id);
    const titlebar = shell.querySelector('.paw-window-title') as HTMLElement;
    const overviewTarget = screen.getByRole('button', { name: '打开 Rooms' });
    expect(titlebar.querySelector(`[data-paw-app-icon="${app.id}"]`)).toBeInTheDocument();
    expect(overviewTarget.querySelector(`[data-paw-app-icon="${app.id}"]`)).toBeInTheDocument();
    expect(container.querySelector('.paw-os-app-icon, .paw-app-glyph')).toBeNull();
    expect(titlebar.querySelector('[data-lucide]')).toBeNull();
    expect(overviewTarget.querySelector('[data-lucide]')).toBeNull();
  });
});

function roomWindows(): Record<string, PawWindowNode> {
  return {
    main: windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' }),
    participant: windowNode('participant', { kind: 'participant', id: 'participant-a', roomId: 'room-a', title: '伙伴 A' }),
  };
}

function narrowRoomWindows(): Record<string, PawWindowNode> {
  return Object.fromEntries([
    ['main', windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' })],
    ...Array.from({ length: 5 }, (_, index) => {
      const id = `participant-${index + 1}`;
      return [id, windowNode(id, { kind: 'participant', id, roomId: 'room-a', title: `伙伴 ${index + 1}` })];
    }),
  ]);
}

function windowNode(id: string, target: NonNullable<PawWindowNode['target']>): PawWindowNode {
  return {
    id,
    appId: 'agent',
    title: target.title,
    target,
    bounds: { x: 0, y: 0, width: 420, height: 300 },
    minimized: false,
  };
}

function projectionWithActivity({ id, kind, payload, participantId = 'participant-a' }: {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  participantId?: string | null;
}) {
  const projection = createRoomProjection('room-a');
  projection.activityOrder.push(id);
  projection.activitiesById[id] = activity({ id, kind, payload, participantId });
  return projection;
}

function activity({ id, kind, payload, participantId = 'participant-a' }: {
  id: string;
  kind: string;
  payload: Record<string, unknown>;
  participantId?: string | null;
}): RoomActivityProjection {
  return {
    id,
    turnId: 'turn-a',
    participantId,
    sourceSessionId: 'session-a',
    kind,
    status: 'completed',
    summary: id,
    payload,
    createdAtMs: 10,
    updatedAtMs: 10,
  };
}

function EnterRoomFocus() {
  const store = usePawDesktopApi();
  useEffect(() => {
    store.getState().setCollaborationFocusGroup('room:room-a');
  }, [store]);
  return null;
}

function transformCoordinate(transform: string, axis: 'x' | 'y'): number {
  const match = transform.match(/translate3d\((-?[\d.]+)px, (-?[\d.]+)px/);
  if (!match) throw new Error(`Missing transform coordinate: ${transform}`);
  return Number.parseFloat(axis === 'x' ? match[1]! : match[2]!);
}

function LiveBrowserTabs() {
  const [tabs, setTabs] = useState(['PAW']);
  const [selected, setSelected] = useState('PAW');
  return (
    <>
      <PawWindowChromePortal>
        <div aria-label="Browser tabs" role="tablist">
          {tabs.map((tab) => <button aria-selected={selected === tab} key={tab} onClick={() => setSelected(tab)} role="tab" type="button">{tab}</button>)}
          <button onClick={() => setTabs((current) => [...current, 'Docs'])} type="button">New tab</button>
        </div>
      </PawWindowChromePortal>
      <output data-testid="selected-tab">{selected}</output>
    </>
  );
}

function LiveRoomChrome() {
  return (
    <>
      <PawWindowChromePortal>
        <div aria-label="Room 窗口控制">
          <nav aria-label="Room 工作台视图"><button type="button">对话</button></nav>
          <span role="status">协作中</span>
        </div>
      </PawWindowChromePortal>
      <main data-testid="room-canvas">公开对话</main>
    </>
  );
}

function FrameHarness({ appId = 'agent', children, focusFrame, initial, onCommit, overview, placement, targetKind, windowChrome }: { appId?: PawAppId; children: React.ReactNode; focusFrame?: PawWindowBounds; initial: PawWindowBounds; onCommit: (bounds: PawWindowBounds) => void; overview?: boolean; placement?: 'maximized' | 'left' | 'right'; targetKind?: 'room'; windowChrome?: string }) {
  const [bounds, setBounds] = useState(initial);
  return (
    <PawWindowFrame
      active
      appId={appId}
      bounds={bounds}
      focusFrame={focusFrame}
      onBoundsCommit={(next) => { onCommit(next); setBounds(next); }}
      onClose={() => undefined}
      onFocus={() => undefined}
      onMinimize={() => undefined}
      onToggleMaximize={() => undefined}
      overview={overview}
      onOpenFromOverview={() => undefined}
      placement={placement}
      targetKind={targetKind}
      title="Rooms"
      windowChrome={windowChrome}
      windowId="rooms"
      zIndex={10}
    >
      {children}
    </PawWindowFrame>
  );
}
