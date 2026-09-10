import { describe, expect, it } from 'vitest';
import { previewBackgroundJobs } from '@/features/agent/preview-data';
import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';
import { backgroundToolRequest, reconcileBackgroundToolWindow } from './background-tool-windows';
import { createPawDesktopStore } from './desktop-store';

function setup() {
  const store = createPawDesktopStore();
  const mainId = store.getState().openApp('agent', { entityId: 'room-a', target: { kind: 'room', id: 'room-a', title: '协作' } });
  const job = previewBackgroundJobs('session-states').find((item) => item.status === 'running')!;
  return { store, mainId, job, request: backgroundToolRequest(job, 'room-a', 'earth') };
}

describe('persistent background tool windows', () => {
  it('opens only after explicit collaboration entry and preserves ordinary frames on exit', () => {
    const { store, request, mainId } = setup();
    const bounds = { ...store.getState().windows[mainId]!.bounds };
    reconcileBackgroundToolWindow(store, request, 'running');
    expect(Object.keys(store.getState().windows)).toEqual([mainId]);
    expect(store.getState().collaborationFocusGroup).toBeNull();
    store.getState().setCollaborationFocusGroup('room:room-a');
    reconcileBackgroundToolWindow(store, request, 'running');
    expect(Object.keys(store.getState().windows)).toHaveLength(2);
    expect(store.getState().activeWindowId).toBe(mainId);
    store.getState().setCollaborationFocusGroup(null);
    expect(store.getState().windows[mainId]!.bounds).toEqual(bounds);
    const later = { ...request, target: { ...request.target, id: 'another-run' } };
    reconcileBackgroundToolWindow(store, later, 'running');
    expect(Object.keys(store.getState().windows)).toHaveLength(2);
    expect(store.getState().collaborationFocusGroup).toBeNull();
  });

  it('keeps a manually closed tool hidden through repeated progress and desktop restore', () => {
    const { store, request } = setup();
    store.getState().setCollaborationFocusGroup('room:room-a');
    reconcileBackgroundToolWindow(store, request, 'running');
    const id = `${request.appId}:${request.target.id}`;
    store.getState().closeWindow(id);
    const restored = createPawDesktopStore(undefined, undefined, store.getState());
    for (let index = 0; index < 3; index++) reconcileBackgroundToolWindow(restored, request, 'running');
    expect(restored.getState().windows[id]).toBeUndefined();
    const next = { ...request, target: { ...request.target, id: 'a-new-background-job' } };
    reconcileBackgroundToolWindow(restored, next, 'running');
    expect(restored.getState().windows[`${next.appId}:${next.target.id}`]).toBeDefined();
  });

  it('closes a finished observer without closing manually opened terminal or browser windows', () => {
    const { store, request } = setup();
    store.getState().setCollaborationFocusGroup('room:room-a');
    const terminal = store.getState().openApp('terminal', { background: true });
    const browser = store.getState().openApp('browser', { background: true });
    reconcileBackgroundToolWindow(store, request, 'running');
    reconcileBackgroundToolWindow(store, request, 'completed');
    expect(store.getState().windows[`${request.appId}:${request.target.id}`]).toBeUndefined();
    expect(store.getState().windows[terminal]).toBeDefined();
    expect(store.getState().windows[browser]).toBeDefined();
    const observer: PawOsWindowRequest = { appId: 'browser', background: true, target: {
      kind: 'browser-target', id: 'observed-target', title: 'Browser', targetId: 'target-1', sessionId: 'session-states',
      toolCallId: '', roomId: 'room-a', backgroundObserver: true,
    } };
    reconcileBackgroundToolWindow(store, observer, 'running');
    reconcileBackgroundToolWindow(store, observer, 'closed');
    expect(store.getState().windows['browser:observed-target']).toBeUndefined();
    expect(store.getState().windows[browser]).toBeDefined();
  });

  it('does not resurrect a finished job or open a foreground tool call', () => {
    const { store, request, mainId } = setup();
    store.getState().setCollaborationFocusGroup('room:room-a');
    reconcileBackgroundToolWindow(store, request, 'completed');
    reconcileBackgroundToolWindow(store, request, 'running');
    reconcileBackgroundToolWindow(store, { ...request, target: { ...request.target, backgroundObserver: false } as typeof request.target }, 'running');
    expect(Object.keys(store.getState().windows)).toEqual([mainId]);
  });
});
