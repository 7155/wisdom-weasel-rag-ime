import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { memo, useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { createRoomProjection, type RoomActivityProjection } from '@/contracts/room-reducer';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { pawApps, type PawAppId } from '../runtime/app-registry';
import { fitReachablePawWindowBounds, pawWindowArea, type PawWindowBounds, type PawWindowNode } from '../runtime/desktop-store';
import { PawDesktopProvider } from '../runtime/desktop-context';
import { usePawDesktopApi } from '../runtime/desktop-context';
import { PawWindowChromePortal } from './PawWindowChrome';
import { PAW_WINDOW_FLOW_GEOMETRY_EVENT, PawRoomFocusRail, PawWindowFrame, PawWindowLayer, resizeWindowBounds, roomWindowFlowGroups } from './PawWindowLayer';
import windowLayerSource from './PawWindowLayer.tsx?raw';

const appProcessRenders = vi.hoisted(() => new Map<string, number>());
vi.mock('../apps/PawApps', () => ({
  PawAppProcess: ({ appId }: { appId: string }) => {
    appProcessRenders.set(appId, (appProcessRenders.get(appId) ?? 0) + 1);
    return null;
  },
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  appProcessRenders.clear();
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
      /* One chrome language: a focus-card satellite carries the same
         traffic-light cluster, in the same slot and the same order, as the
         Room window it orbits — never a lone top-right X. Inside the focus
         layout both drop maximize together, because the layout owns
         geometry, so the two clusters stay verb-for-verb identical. */
      const roomShell = await screen.findByLabelText('Room A窗口');
      expect(roomShell.querySelectorAll('.paw-traffic-lights')).toHaveLength(1);
      const clusterVerbs = (host: HTMLElement) => [...host.querySelectorAll('.paw-traffic-lights button')]
        .map((button) => button.getAttribute('data-action'));
      expect(clusterVerbs(shell)).toEqual(['close', 'minimize']);
      expect(clusterVerbs(roomShell)).toEqual(['close', 'minimize']);
      expect(within(shell).getByRole('button', { name: '关闭窗口' })).toBeInTheDocument();
      expect(within(shell).getByRole('button', { name: '最小化窗口' })).toBeInTheDocument();
      /* The lights stay the first children so the shared nth-child
         red/yellow/green rules never slide onto the wrong verb. */
      expect(shell.querySelector('.paw-traffic-lights')!.firstElementChild)
        .toHaveAttribute('data-action', 'close');
      expect(roomShell.querySelector('.paw-traffic-lights')!.firstElementChild)
        .toHaveAttribute('data-action', 'close');
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

      fireEvent.click(within(shell).getByRole('button', { name: '关闭窗口' }));
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

  it('moves eight Room satellites into the accessible rail at an 800px desktop width', async () => {
    const originalWidth = window.innerWidth;
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 800 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    const windows = narrowRoomWindows(8);
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

      const rail = await screen.findByRole('region', { name: 'Sol 行星窗口，横向滚动查看全部 8 个窗口' });
      expect(rail).toHaveAttribute('data-satellite-count', '8');
      const satelliteShells = Array.from({ length: 8 }, (_, index) => screen.getByLabelText(`伙伴 ${index + 1}窗口`));
      expect(Math.min(...satelliteShells.map((shell) => Number.parseFloat(shell.style.height)))).toBeGreaterThanOrEqual(210);
      expect(transformCoordinate(satelliteShells.at(-1)!.style.transform, 'x')).toBeGreaterThan(window.innerWidth);
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth });
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight });
    }
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

  it('never resizes a window below its minimum or past the desktop edge', () => {
    const bounds = { x: 100, y: 100, width: 400, height: 300 };
    const area = { x: 8, y: 8, width: 1000, height: 600 };

    // A window has a floor: below it the titlebar can no longer hold three
    // verbs beside an App's own chrome.
    expect(resizeWindowBounds(bounds, 'east', -900, 0, area).width).toBe(280);
    expect(resizeWindowBounds(bounds, 'south', 0, -900, area).height).toBe(210);
    // And a ceiling: the far edge stops at the desktop instead of growing a
    // frame whose corner handle no longer exists on screen.
    expect(resizeWindowBounds(bounds, 'east', 900, 0, area)).toEqual({ x: 100, y: 100, width: 908, height: 300 });
    // North and west move the opposite edge, so without the limit they push
    // the titlebar above the desktop where no pointer can reach it.
    expect(resizeWindowBounds(bounds, 'north', 0, -900, area)).toEqual({ x: 100, y: 8, width: 400, height: 392 });
    expect(resizeWindowBounds(bounds, 'west', -900, 0, area)).toEqual({ x: 8, y: 100, width: 492, height: 300 });
    // A Room focus card is laid out inside its own mode, which clamps on
    // commit; the gesture floor there is that mode's own origin, never a
    // negative frame.
    expect(resizeWindowBounds(bounds, 'north', 0, -900).y).toBe(0);
    expect(resizeWindowBounds(bounds, 'west', -900, 0).x).toBe(0);
  });

  it('tracks the pointer 1:1 while dragging and keeps a recoverable titlebar grip on screen', () => {
    const commit = vi.fn();
    // The gesture paints inside one rAF slot per frame; running that slot
    // inline is what lets the assertion read the frame mid-drag.
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    });
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    try {
      render(
        <div className="paw-desktop-root">
          <FrameHarness initial={{ x: 20, y: 30, width: 760, height: 560 }} onCommit={commit}><div /></FrameHarness>
        </div>,
      );
      const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;
      const shell = titlebar.closest('.paw-window-shell') as HTMLElement;
      const area = pawWindowArea();

      fireEvent.pointerDown(titlebar, { button: 0, clientX: 400, clientY: 300, pointerId: 31 });
      // Inside the desktop the frame follows the pointer exactly: no easing,
      // no rounding, no lag between the grab point and the window.
      fireEvent.pointerMove(window, { clientX: 464, clientY: 342, pointerId: 31 });
      expect(shell.style.transform).toBe('translate3d(84px, 72px, 0)');
      // Past the edge the frame may remain partially outside the OS canvas,
      // but a stable titlebar grip stays reachable so the user can pull it
      // back without an artificial full-window clamp.
      fireEvent.pointerMove(window, { clientX: -600, clientY: -600, pointerId: 31 });
      const reachable = fitReachablePawWindowBounds({ x: -980, y: -870, width: 760, height: 560 }, area);
      expect(reachable.x).toBeLessThan(area.x);
      expect(shell.style.transform).toBe(`translate3d(${reachable.x}px, ${reachable.y}px, 0)`);
      fireEvent.pointerUp(window, { clientX: -600, clientY: -600, pointerId: 31 });

      expect(commit).toHaveBeenLastCalledWith(reachable);
      expect(shell.style.transform).toBe(`translate3d(${reachable.x}px, ${reachable.y}px, 0)`);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('writes the snap preview only when the zone changes and clears it on release', () => {
    const { container } = render(
      <div className="paw-desktop-root">
        <FrameHarness initial={{ x: 200, y: 200, width: 420, height: 300 }} onCommit={() => undefined}><div /></FrameHarness>
      </div>,
    );
    const root = container.querySelector('.paw-desktop-root') as HTMLElement;
    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;
    const observer = new MutationObserver(() => undefined);
    observer.observe(root, { attributes: true, attributeFilter: ['data-snap-preview'] });
    const snapPreviewWrites = () => observer.takeRecords().length;

    try {
      fireEvent.pointerDown(titlebar, { button: 0, clientX: 300, clientY: 240, pointerId: 32 });
      snapPreviewWrites();
      fireEvent.pointerMove(window, { clientX: 6, clientY: 240, pointerId: 32 });
      expect(root).toHaveAttribute('data-snap-preview', 'left');
      expect(snapPreviewWrites()).toBe(1);
      // Staying inside the same zone must not rewrite the attribute: pointer
      // moves outpace the frame rate, and each write would invalidate style
      // for the whole desktop subtree.
      fireEvent.pointerMove(window, { clientX: 4, clientY: 260, pointerId: 32 });
      fireEvent.pointerMove(window, { clientX: 2, clientY: 280, pointerId: 32 });
      expect(snapPreviewWrites()).toBe(0);

      fireEvent.pointerUp(window, { clientX: 2, clientY: 280, pointerId: 32 });
      expect(root).not.toHaveAttribute('data-snap-preview');
      expect(snapPreviewWrites()).toBe(1);
    } finally {
      observer.disconnect();
    }
  });

  it('refits window size after viewport shrink while preserving a recoverable partial offset', () => {
    const windows = {
      agent: { ...desktopWindowNode('agent', 'agent'), bounds: { x: 40, y: 40, width: 1180, height: 900 } },
    };
    window.localStorage.setItem('pawos.desktop.v1', JSON.stringify({
      windows,
      stack: ['agent'],
      activeWindowId: 'agent',
    }));

    withViewport(1280, 1000, () => {
      render(
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawDesktopProvider>
            <CaptureDesktopApi />
            <PawWindowLayer />
          </PawDesktopProvider>
        </ControlTransportProvider>,
      );

      withViewport(900, 640, () => {
        act(() => capturedDesktopApi!.getState().fitWindowsToViewport());
        const area = pawWindowArea();
        const bounds = capturedDesktopApi!.getState().windows.agent!.bounds;

        expect(bounds.x).toBeLessThanOrEqual(area.x + area.width - 120);
        expect(bounds.y).toBeGreaterThanOrEqual(area.y);
        expect(bounds.width).toBeLessThanOrEqual(area.width);
        expect(bounds.height).toBeLessThanOrEqual(area.height);
        // Viewport fitting no longer erases a deliberate partial offset; it
        // only guarantees a 120px horizontal grip and one titlebar row.
        expect(bounds.x + bounds.width).toBeGreaterThanOrEqual(area.x + 120);
        expect(bounds.y).toBeLessThanOrEqual(area.y + area.height - 40);
      });
    });
  });

  it('exposes restore identity after a window is maximized', () => {
    render(<FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} placement="maximized" onCommit={() => undefined}><div /></FrameHarness>);

    expect(screen.getByRole('button', { name: '还原窗口' })).toHaveAttribute('data-action', 'restore');
    expect(screen.getByLabelText('Rooms窗口')).toHaveAttribute('data-placement', 'maximized');
  });

  it('renders exactly one traffic light cluster with the three window verbs', () => {
    render(<FrameHarness initial={{ x: 0, y: 0, width: 760, height: 560 }} onCommit={() => undefined}><div /></FrameHarness>);

    const shell = screen.getByLabelText('Rooms窗口');
    const clusters = shell.querySelectorAll('.paw-traffic-lights');
    expect(clusters).toHaveLength(1);
    const lights = within(clusters[0] as HTMLElement).getAllByRole('button');
    expect(lights.map((light) => light.getAttribute('aria-label'))).toEqual(['关闭窗口', '最小化窗口', '最大化窗口']);
  });

  it('re-renders only the committed window App tree when one window changes bounds', async () => {
    const windows = {
      agent: desktopWindowNode('agent', 'agent'),
      files: desktopWindowNode('files', 'files'),
    };
    window.localStorage.setItem('pawos.desktop.v1', JSON.stringify({
      windows,
      stack: ['agent', 'files'],
      activeWindowId: 'files',
    }));
    render(
      <ControlTransportProvider transport={createPreviewTransport()}>
        <PawDesktopProvider>
          <CaptureDesktopApi />
          <PawWindowLayer />
        </PawDesktopProvider>
      </ControlTransportProvider>,
    );
    await screen.findByLabelText('agent窗口');
    const agentBefore = appProcessRenders.get('agent') ?? 0;
    const filesBefore = appProcessRenders.get('files') ?? 0;

    act(() => capturedDesktopApi!.getState().commitBounds('files', { x: 60, y: 70, width: 480, height: 340 }));

    // The committed window may re-render for its new bounds; every other
    // window's App tree bails out at the memo boundary — a geometry commit
    // with many windows open must never fan out into every open App.
    expect(appProcessRenders.get('files') ?? 0).toBeGreaterThanOrEqual(filesBefore);
    expect(appProcessRenders.get('agent') ?? 0).toBe(agentBefore);
  });

  it('marks the desktop root for the exact duration of a drag or resize so the wallpaper can pause', () => {
    const { container } = render(
      <div className="paw-desktop-root">
        <FrameHarness initial={{ x: 20, y: 30, width: 760, height: 560 }} onCommit={() => undefined}><div /></FrameHarness>
      </div>,
    );
    const root = container.querySelector('.paw-desktop-root') as HTMLElement;
    const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;

    expect(root).not.toHaveAttribute('data-window-interaction');
    fireEvent.pointerDown(titlebar, { button: 0, clientX: 100, clientY: 80, pointerId: 21 });
    expect(root).toHaveAttribute('data-window-interaction', 'true');
    fireEvent.pointerMove(window, { clientX: 130, clientY: 90, pointerId: 21 });
    expect(root).toHaveAttribute('data-window-interaction', 'true');
    fireEvent.pointerUp(window, { clientX: 130, clientY: 90, pointerId: 21 });
    expect(root).not.toHaveAttribute('data-window-interaction');

    fireEvent.pointerDown(screen.getByRole('button', { name: '调整窗口右边缘' }), { button: 0, clientX: 500, clientY: 300, pointerId: 22 });
    expect(root).toHaveAttribute('data-window-interaction', 'true');
    fireEvent.pointerUp(window, { clientX: 520, clientY: 300, pointerId: 22 });
    expect(root).not.toHaveAttribute('data-window-interaction');
  });

  it('coalesces a viewport resize burst into one refit per animation frame', () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.push(callback);
      return frames.length;
    });
    vi.stubGlobal('cancelAnimationFrame', (handle: number) => {
      frames[handle - 1] = () => undefined;
    });
    try {
      render(
        <ControlTransportProvider transport={createPreviewTransport()}>
          <PawDesktopProvider>
            <PawWindowLayer />
          </PawDesktopProvider>
        </ControlTransportProvider>,
      );
      expect(frames).toHaveLength(0);

      act(() => {
        for (let index = 0; index < 5; index += 1) fireEvent(window, new Event('resize'));
      });
      // A viewport drag emits resize far faster than the frame rate; the whole
      // burst owes exactly one refit of every window.
      expect(frames).toHaveLength(1);

      act(() => {
        frames.splice(0).forEach((callback) => callback(performance.now()));
      });
      act(() => {
        fireEvent(window, new Event('resize'));
      });
      expect(frames).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('keeps live window geometry out of the layer subscription on an ordinary desktop', () => {
    // Only collaboration focus frames and Room flow paths read bounds. Without
    // them the layer holds a frozen empty record, so moving one window cannot
    // re-render the layer, the focus frames, the flow groups or the rail.
    expect(windowLayerSource).toMatch(/const wantsWindowGeometry = Boolean\(collaborationFocusGroup\) \|\| Boolean\(participantSignature\)/);
    expect(windowLayerSource).toMatch(/usePawDesktopStore\(wantsWindowGeometry \? selectWindows : selectNoWindows\)/);
    // Room projection keepalive answers inside the subscription, so geometry
    // churn produces the same string instead of a new render.
    expect(windowLayerSource).toMatch(/roomProjectionKeepaliveIds\(state\.windows, overviewOpen\)\.join/);
  });

  it('coalesces live flow geometry into one React write per animation frame', () => {
    expect(windowLayerSource).toContain('function useLiveWindowFlowPoints');
    // Leading edge applies synchronously (the publisher already paces one
    // event per frame), the trailing rAF slot folds same-frame bursts, and
    // unchanged points bail before creating a new record.
    expect(windowLayerSource).toMatch(/requestAnimationFrame\(flush\)/);
    expect(windowLayerSource).toMatch(/prior\.x === point\.x && prior\.y === point\.y/);
  });

  it('keeps an untracked window drag free of live flow geometry work', () => {
    const seenPoints: Array<{ x: number; y: number } | null> = [];
    const listen = (event: Event) => seenPoints.push((event as CustomEvent<{ point: { x: number; y: number } | null }>).detail.point);
    window.addEventListener(PAW_WINDOW_FLOW_GEOMETRY_EVENT, listen);
    try {
      render(
        <div className="paw-window-layer">
          <FrameHarness initial={{ x: 20, y: 30, width: 760, height: 560 }} onCommit={() => undefined}><div /></FrameHarness>
        </div>,
      );
      const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;

      fireEvent.pointerDown(titlebar, { button: 0, clientX: 100, clientY: 80, pointerId: 11 });
      fireEvent.pointerMove(window, { clientX: 164, clientY: 122, pointerId: 11 });
      fireEvent.pointerUp(window, { clientX: 164, clientY: 122, pointerId: 11 });

      // An ordinary window publishes no live points while moving — only the
      // final clear signal, which carries no geometry and forces no reads.
      expect(seenPoints.length).toBeGreaterThanOrEqual(1);
      expect(seenPoints.every((point) => point === null)).toBe(true);
    } finally {
      window.removeEventListener(PAW_WINDOW_FLOW_GEOMETRY_EVENT, listen);
    }
  });

  it('publishes live flow geometry for windows that sit in a Room flow group', () => {
    const seenPoints: Array<{ x: number; y: number } | null> = [];
    const listen = (event: Event) => seenPoints.push((event as CustomEvent<{ point: { x: number; y: number } | null }>).detail.point);
    window.addEventListener(PAW_WINDOW_FLOW_GEOMETRY_EVENT, listen);
    try {
      render(
        <div className="paw-window-layer">
          <FrameHarness flowTracked initial={{ x: 20, y: 30, width: 760, height: 560 }} onCommit={() => undefined}><div /></FrameHarness>
        </div>,
      );
      const shell = screen.getByLabelText('Rooms窗口');
      expect(shell).toHaveAttribute('data-flow-tracked', 'true');
      const titlebar = screen.getByText('Rooms').closest('.paw-window-titlebar')!;

      fireEvent.pointerDown(titlebar, { button: 0, clientX: 100, clientY: 80, pointerId: 12 });
      fireEvent.pointerMove(window, { clientX: 164, clientY: 122, pointerId: 12 });
      fireEvent.pointerUp(window, { clientX: 164, clientY: 122, pointerId: 12 });

      expect(seenPoints.some((point) => point !== null)).toBe(true);
      expect(seenPoints.at(-1)).toBeNull();
    } finally {
      window.removeEventListener(PAW_WINDOW_FLOW_GEOMETRY_EVENT, listen);
    }
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

function narrowRoomWindows(count = 5): Record<string, PawWindowNode> {
  return Object.fromEntries([
    ['main', windowNode('main', { kind: 'room', id: 'room-a', title: 'Room A' })],
    ...Array.from({ length: count }, (_, index) => {
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

function desktopWindowNode(id: string, appId: PawAppId): PawWindowNode {
  return {
    id,
    appId,
    title: id,
    bounds: { x: 10, y: 12, width: 420, height: 300 },
    minimized: false,
  };
}

let capturedDesktopApi: ReturnType<typeof usePawDesktopApi> | null = null;
function CaptureDesktopApi() {
  capturedDesktopApi = usePawDesktopApi();
  return null;
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

function withViewport(width: number, height: number, run: () => void): void {
  const original = { width: window.innerWidth, height: window.innerHeight };
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
  try {
    run();
  } finally {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: original.width });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: original.height });
  }
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

function FrameHarness({ appId = 'agent', children, flowTracked, focusFrame, initial, onCommit, overview, placement, targetKind, windowChrome }: { appId?: PawAppId; children: React.ReactNode; flowTracked?: boolean; focusFrame?: PawWindowBounds; initial: PawWindowBounds; onCommit: (bounds: PawWindowBounds) => void; overview?: boolean; placement?: 'maximized' | 'left' | 'right'; targetKind?: 'room'; windowChrome?: string }) {
  const [bounds, setBounds] = useState(initial);
  return (
    <PawWindowFrame
      active
      appId={appId}
      bounds={bounds}
      flowTracked={flowTracked}
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
