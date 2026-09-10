import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { useEffect } from 'react';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { previewBackgroundJobs } from '@/features/agent/preview-data';
import type { ControlRequest } from '@/platform/transport';
import { PawDesktopProvider, usePawDesktopApi } from '../runtime/desktop-context';
import type { PawDesktopStore } from '../runtime/desktop-store';
import { PawBackgroundToolWindows } from './PawBackgroundToolWindows';

afterEach(() => { cleanup(); window.localStorage.clear(); });

it('joins real resource receipts only in explicit focus, hides on close, and never sends stop commands', async () => {
  let api!: PawDesktopStore;
  let job = previewBackgroundJobs('session-states').find((value) => value.status === 'running')!;
  let tabs = [{ tabId: 7, targetId: 'target-7', title: '后台网页', url: 'https://example.com' }];
  let liveSnapshot = true;
  const calls: ControlRequest[] = [];
  const transport = createPreviewTransport();
  transport.request = async <T,>(request: ControlRequest): Promise<T> => {
    calls.push(request);
    const values: Record<string, unknown> = {
      'agent.room.get': { room: { id: 'room-a', participants: [{ id: 'earth', sessionId: 'session-states', status: 'active' }] } },
      'agent.session.backgroundJobs.list': { ok: true, schemaVersion: 'rag-ime.agent-background-job-list.v1', sessionId: 'session-states', items: [job] },
      'agent.session.backgroundJob.get': { ok: true, job },
      'browser.tabs': { ok: true, liveSnapshot, items: tabs },
      'browser.traces': { ok: true, items: [{ sessionId: 'session-states', tabId: 7, status: 'completed' }] },
    };
    return values[request.pathId] as T;
  };
  function Capture() {
    const store = usePawDesktopApi();
    useEffect(() => { api = store; store.getState().bindAgentMain('agent', { kind: 'room', id: 'room-a', title: 'Room' }); }, [store]);
    return null;
  }
  render(<ControlTransportProvider transport={transport}><PawDesktopProvider initialAppId="agent"><Capture /><PawBackgroundToolWindows /></PawDesktopProvider></ControlTransportProvider>);
  expect(calls).toHaveLength(0);
  act(() => api.getState().setCollaborationFocusGroup('room:room-a'));
  await waitFor(() => expect(Object.keys(api.getState().windows)).toHaveLength(3));
  const terminal = Object.values(api.getState().windows).find((window) => window.target?.kind === 'process-terminal')!;
  const browser = Object.values(api.getState().windows).find((window) => window.target?.kind === 'browser-target')!;
  act(() => api.getState().closeWindow(terminal.id));
  await waitFor(() => expect(calls.filter((call) => call.pathId === 'agent.session.backgroundJobs.list').length).toBeGreaterThan(1));
  expect(api.getState().windows[terminal.id]).toBeUndefined();
  expect(job.status).toBe('running');

  // A disconnected/failed tab read is not a closed-tab receipt.
  tabs = [];
  liveSnapshot = false;
  act(() => api.getState().setCollaborationFocusGroup(null));
  await waitFor(() => expect(calls.filter((call) => call.pathId === 'browser.tabs').length).toBeGreaterThan(2));
  expect(api.getState().windows[browser.id]).toBeDefined();
  liveSnapshot = true;
  job = { ...job, status: 'completed', exitCode: 0, endedAtMs: Date.now() };
  act(() => api.getState().setCollaborationFocusGroup('room:room-a'));
  await waitFor(() => expect(api.getState().windows[browser.id]).toBeUndefined());
  expect(api.getState().windows[terminal.id]).toBeUndefined();
  expect(calls.some((call) => call.pathId === 'agent.session.backgroundJob.cancel' || call.pathId === 'browser.command')).toBe(false);
});
