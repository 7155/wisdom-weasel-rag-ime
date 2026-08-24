import { describe, expect, it } from 'vitest';
import { createPawDesktopStore } from './desktop-store';

describe('PAWOS desktop store', () => {
  it('keeps one primary window per App and restores it without creating a second process', () => {
    const store = createPawDesktopStore();

    const first = store.getState().openApp('agent');
    store.getState().minimizeWindow(first);
    const reopened = store.getState().openApp('agent');

    expect(reopened).toBe(first);
    expect(Object.keys(store.getState().windows)).toEqual(['agent']);
    expect(store.getState().windows.agent?.minimized).toBe(false);
    expect(store.getState().activeWindowId).toBe('agent');
  });

  it('allows entity windows to coexist without duplicating the App runtime owner', () => {
    const store = createPawDesktopStore();

    store.getState().openApp('agent');
    const sessionWindow = store.getState().openApp('agent', { entityId: 'session-42' });

    expect(sessionWindow).toBe('agent:session-42');
    expect(Object.values(store.getState().windows).map((node) => node.appId)).toEqual(['agent', 'agent']);
    expect(store.getState().windows[sessionWindow]?.entityId).toBe('session-42');
  });

  it('retains the entity target needed by the full feature surface', () => {
    const store = createPawDesktopStore();
    const target = { kind: 'room', id: 'room-42', title: '迁移协作' } as const;

    const windowId = store.getState().openApp('agent', {
      entityId: target.id,
      target,
      title: target.title,
    });

    expect(store.getState().windows[windowId]?.target).toEqual(target);
    expect(store.getState().windows[windowId]?.title).toBe('迁移协作');
  });

  it('routes an already open App to the requested deep link', () => {
    const store = createPawDesktopStore('agent');

    const windowId = store.getState().openApp('agent', { initialRoute: '/roles' });

    expect(windowId).toBe('agent');
    expect(store.getState().windows.agent?.initialRoute).toBe('/roles');
  });

  it('opens the initial App at the requested deep link', () => {
    const store = createPawDesktopStore('agent', '/agent?subagents=open');

    expect(store.getState().windows.agent?.initialRoute).toBe('/agent?subagents=open');
    expect(store.getState().windows.agent?.title).toBe('Agent');
  });

  it('does not publish a new window snapshot when bounds are unchanged', () => {
    const store = createPawDesktopStore('agent');
    const before = store.getState().windows.agent;

    store.getState().commitBounds('agent', { ...before!.bounds });

    expect(store.getState().windows.agent).toBe(before);
  });

  it('keeps the Room main window focused while opening participant satellites in one group', () => {
    const store = createPawDesktopStore();
    const room = { kind: 'room', id: 'room-7', title: '迁移协作' } as const;
    const mainId = store.getState().openApp('agent', { entityId: room.id, target: room, title: room.title });
    const firstId = store.getState().openApp('agent', {
      background: true,
      target: { kind: 'participant', id: 'participant-1', roomId: room.id, title: '实现伙伴' },
    });
    const secondId = store.getState().openApp('agent', {
      background: true,
      target: { kind: 'participant', id: 'participant-2', roomId: room.id, title: '复核伙伴' },
    });
    const state = store.getState();

    expect(state.activeWindowId).toBe(mainId);
    expect(state.windows[firstId]?.target?.kind).toBe('participant');
    expect(state.windows[secondId]?.target?.kind).toBe('participant');
    expect(state.windows[firstId]?.bounds.width).toBeGreaterThan(0);
    expect(state.windows[secondId]?.bounds.width).toBeGreaterThan(0);
    expect(state.stack.at(-1)).toBe(mainId);
  });

  it('binds an existing Agent window to the Room target without creating another main window', () => {
    const store = createPawDesktopStore();
    const mainId = store.getState().openApp('agent');
    store.getState().bindRoomMain({ kind: 'room', id: 'room-8', title: '研究协作' });

    expect(Object.keys(store.getState().windows)).toEqual([mainId]);
    expect(store.getState().windows[mainId]?.target).toEqual({ kind: 'room', id: 'room-8', title: '研究协作' });
  });

  it('keeps the exact Agent window title, icon target, and route aligned while moving between Room and Session', () => {
    const store = createPawDesktopStore();
    const mainId = store.getState().openApp('agent');

    store.getState().bindAgentMain(mainId, { kind: 'room', id: 'room-8', title: '研究协作' });
    store.getState().setCollaborationFocusGroup('room:room-8');
    store.getState().bindAgentMain(mainId, { kind: 'session', id: 'session-8', title: '发布检查' });

    expect(store.getState().windows[mainId]).toMatchObject({
      title: '发布检查',
      initialRoute: '/agent?session=session-8',
      target: { kind: 'session', id: 'session-8', title: '发布检查' },
    });
    expect(store.getState().collaborationFocusGroup).toBeNull();

    store.getState().bindAgentMain(mainId);
    expect(store.getState().windows[mainId]).toMatchObject({ title: 'Agent', initialRoute: '/agent' });
    expect(store.getState().windows[mainId]?.target).toBeUndefined();
  });

  it('does not let a main-window identity update overwrite a participant satellite', () => {
    const store = createPawDesktopStore();
    const satelliteId = store.getState().openApp('agent', {
      target: { kind: 'participant', id: 'participant-8', roomId: 'room-8', title: 'Mercury' },
    });
    const before = store.getState().windows[satelliteId];

    store.getState().bindAgentMain(satelliteId, { kind: 'session', id: 'session-8', title: '发布检查' });

    expect(store.getState().windows[satelliteId]).toBe(before);
  });

  it('keeps Room satellites attached to the matching Room main when other Agent windows are open', () => {
    const store = createPawDesktopStore();
    const sessionId = store.getState().openApp('agent', { entityId: 'session-1', target: { kind: 'session', id: 'session-1', title: '普通 Session' } });
    const room = { kind: 'room', id: 'room-9', title: '并行协作' } as const;
    const roomId = store.getState().openApp('agent', { entityId: room.id, target: room, title: room.title });
    const roomBoundsBeforeSatellite = store.getState().windows[roomId]?.bounds;
    store.getState().focusWindow(sessionId);

    const participantId = store.getState().openApp('agent', {
      background: true,
      target: { kind: 'participant', id: 'participant-9', roomId: room.id, title: '实现伙伴' },
    });
    const state = store.getState();
    const roomWindow = Object.values(state.windows).find((window) => window.target?.kind === 'room' && window.target.id === room.id);

    expect(roomWindow?.bounds.width).toBeGreaterThan(0);
    expect(roomWindow?.bounds).toEqual(roomBoundsBeforeSatellite);
    expect(roomWindow?.target).toEqual(room);
    expect(state.collaborationFocusGroup).toBe('room:room-9');
    expect(state.windows[sessionId]?.target?.kind).toBe('session');
    expect(state.windows[participantId]?.target?.kind).toBe('participant');
  });

  it('binds the matching Room main even when another Agent window is focused', () => {
    const store = createPawDesktopStore();
    const sessionId = store.getState().openApp('agent', { entityId: 'session-2', target: { kind: 'session', id: 'session-2', title: '普通 Session' } });
    store.getState().openApp('agent', { entityId: 'room-10', target: { kind: 'room', id: 'room-10', title: '治理 Room' } });
    store.getState().focusWindow(sessionId);

    store.getState().bindRoomMain({ kind: 'room', id: 'room-10', title: '治理 Room', subtitle: '更新后的 Room' });

    expect(Object.values(store.getState().windows).find((window) => window.target?.kind === 'room' && window.target.id === 'room-10')?.target).toEqual({ kind: 'room', id: 'room-10', title: '治理 Room', subtitle: '更新后的 Room' });
    expect(store.getState().windows[sessionId]?.target?.kind).toBe('session');
  });

  it('closes every window for one App atomically while preserving other Apps and clearing stale focus state', () => {
    const store = createPawDesktopStore();
    const roomId = store.getState().openApp('agent', {
      entityId: 'room-close',
      target: { kind: 'room', id: 'room-close', title: '关闭范围' },
    });
    store.getState().openApp('agent', {
      background: true,
      entityId: 'participant-close',
      target: { kind: 'participant', id: 'participant-close', roomId: 'room-close', title: '伙伴' },
    });
    const browserId = store.getState().openApp('browser', { title: 'Browser' });
    store.getState().setCollaborationFocusGroup('room:room-close');
    store.getState().focusWindow(roomId);

    store.getState().closeAppWindows('agent');

    const state = store.getState();
    expect(Object.keys(state.windows)).toEqual([browserId]);
    expect(state.stack).toEqual([browserId]);
    expect(state.activeWindowId).toBe(browserId);
    expect(state.collaborationFocusGroup).toBeNull();
    expect(state.collaborationFocusReturnWindowId).toBeNull();
    expect(state.overviewOpen).toBe(false);
  });

  it('closes every PAWOS projection without stopping or mutating an underlying Runtime target', () => {
    const store = createPawDesktopStore();
    store.getState().openApp('agent');
    store.getState().openApp('terminal', {
      entityId: 'bg_same_run',
      target: {
        kind: 'process-terminal',
        id: 'bg_same_run',
        title: 'pnpm test',
        sessionId: 'session-1',
        toolCallId: 'call-1',
        runId: 'bg_same_run',
        command: 'pnpm test',
      },
    });
    store.getState().setOverviewOpen(true);

    store.getState().closeAllWindows();

    expect(store.getState()).toMatchObject({
      windows: {},
      stack: [],
      activeWindowId: null,
      collaborationFocusGroup: null,
      collaborationFocusReturnWindowId: null,
      overviewOpen: false,
    });
  });
});
