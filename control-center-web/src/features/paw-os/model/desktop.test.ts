import { describe, expect, it } from 'vitest';
import {
  createPawOsDesktopState,
  pawOsDesktopReducer,
  type PawOsDesktopWindow,
} from './desktop';

const agentWindow: PawOsDesktopWindow = {
  id: 'agent:primary',
  appId: 'agent',
  title: '对话',
  rect: { x: 96, y: 72, width: 880, height: 620 },
  restoreRect: null,
  minimized: false,
  maximized: false,
};

const roomWindow: PawOsDesktopWindow = {
  id: 'rooms:primary',
  appId: 'rooms',
  title: '多人协作',
  rect: { x: 184, y: 108, width: 960, height: 650 },
  restoreRect: null,
  minimized: false,
  maximized: false,
};

describe('pawOsDesktopReducer', () => {
  it('opens windows once and raises the requested App without duplicating business state', () => {
    const initial = createPawOsDesktopState({ windows: [agentWindow] });
    const withRoom = pawOsDesktopReducer(initial, { type: 'open', window: roomWindow });
    const refocused = pawOsDesktopReducer(withRoom, { type: 'open', window: agentWindow });

    expect(refocused.windows).toHaveLength(2);
    expect(refocused.stack).toEqual(['rooms:primary', 'agent:primary']);
    expect(refocused.activeWindowId).toBe('agent:primary');
  });

  it('minimizes the active window, exposes the next visible window, and restores on focus', () => {
    const initial = createPawOsDesktopState({
      windows: [agentWindow, roomWindow],
      stack: ['agent:primary', 'rooms:primary'],
    });
    const minimized = pawOsDesktopReducer(initial, { type: 'minimize', windowId: 'rooms:primary' });

    expect(minimized.windows.find((item) => item.id === 'rooms:primary')?.minimized).toBe(true);
    expect(minimized.activeWindowId).toBe('agent:primary');

    const restored = pawOsDesktopReducer(minimized, { type: 'focus', windowId: 'rooms:primary' });
    expect(restored.windows.find((item) => item.id === 'rooms:primary')?.minimized).toBe(false);
    expect(restored.activeWindowId).toBe('rooms:primary');
  });

  it('keeps a restore frame while maximizing and returns to it afterwards', () => {
    const initial = createPawOsDesktopState({ windows: [agentWindow] });
    const maximized = pawOsDesktopReducer(initial, { type: 'toggleMaximize', windowId: agentWindow.id });

    expect(maximized.windows[0]?.rect).toEqual({ x: 14, y: 14, width: 1412, height: 760 });
    expect(maximized.windows[0]?.restoreRect).toEqual(agentWindow.rect);

    const restored = pawOsDesktopReducer(maximized, { type: 'toggleMaximize', windowId: agentWindow.id });
    expect(restored.windows[0]?.rect).toEqual(agentWindow.rect);
    expect(restored.windows[0]?.restoreRect).toBeNull();
  });

  it('clamps direct manipulation so a title bar and minimum body remain usable', () => {
    const initial = createPawOsDesktopState({ windows: [agentWindow] });
    const moved = pawOsDesktopReducer(initial, {
      type: 'move',
      windowId: agentWindow.id,
      rect: { x: -2_000, y: 2_000, width: 880, height: 620 },
    });
    const resized = pawOsDesktopReducer(moved, {
      type: 'resize',
      windowId: agentWindow.id,
      rect: { x: 10, y: 10, width: 120, height: 90 },
    });

    expect(moved.windows[0]?.rect.x).toBeGreaterThanOrEqual(-720);
    expect(moved.windows[0]?.rect.y).toBeLessThanOrEqual(746);
    expect(resized.windows[0]?.rect.width).toBe(420);
    expect(resized.windows[0]?.rect.height).toBe(280);
  });

  it('tracks launchpad and mission control as mutually exclusive desktop overlays', () => {
    const initial = createPawOsDesktopState({ windows: [agentWindow] });
    const launchpad = pawOsDesktopReducer(initial, { type: 'showOverlay', overlay: 'launchpad' });
    const missionControl = pawOsDesktopReducer(launchpad, { type: 'showOverlay', overlay: 'mission-control' });

    expect(launchpad.overlay).toBe('launchpad');
    expect(missionControl.overlay).toBe('mission-control');
  });

  it('fits restored desktop windows into a smaller browser surface', () => {
    const initial = createPawOsDesktopState({ windows: [agentWindow] });
    const compact = pawOsDesktopReducer(initial, { type: 'setSurface', width: 720, height: 640 });

    expect(compact.windows[0]?.rect).toEqual({ x: 10, y: 10, width: 700, height: 620 });
  });
});
