import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { projectWayfinderWork } from './wayfinder-work-projection';
import { PawWorkDirectoryProvider, usePawWorkDirectory } from './PawWorkDirectory';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('PawWorkDirectoryProvider', () => {
  it('polls the lightweight directory without repeating the heavy maintenance status cadence', async () => {
    vi.useFakeTimers({ now: 1_000 });
    const transport = directoryTransport();
    renderDirectory(transport, { maintenancePollIntervalMs: 30_000, pollIntervalMs: 7_500 });
    await flushRequests();

    expect(requestCount(transport, 'agent.sessions.list')).toBe(1);
    expect(requestCount(transport, 'agent.rooms.list')).toBe(1);
    expect(requestCount(transport, 'agent.memoryMaintenance.run')).toBe(1);
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.memoryMaintenance.run')?.request.query).toEqual({
      limit: 1,
      projectionOnly: 1,
    });

    await act(async () => { await vi.advanceTimersByTimeAsync(7_500); });
    expect(requestCount(transport, 'agent.sessions.list')).toBe(2);
    expect(requestCount(transport, 'agent.rooms.list')).toBe(2);
    expect(requestCount(transport, 'agent.memoryMaintenance.run')).toBe(1);
  });

  it('marks expired Runtime provenance unknown instead of retaining a stale running state', async () => {
    vi.useFakeTimers({ now: 1_000 });
    let rejectDirectory = false;
    const transport = new MockControlTransport({ routes: {
      'agent.sessions.list': () => {
        if (rejectDirectory) throw new Error('offline');
        return { ok: true, items: [session('busy')] };
      },
      'agent.rooms.list': () => {
        if (rejectDirectory) throw new Error('offline');
        return { ok: true, items: [] };
      },
      'agent.memoryMaintenance.run': { ok: true, projection: { running: false } },
    } });
    renderDirectory(transport, { maintenancePollIntervalMs: 60_000, pollIntervalMs: 10_000 });
    await flushRequests();
    expect(screen.getByTestId('directory-state')).toHaveTextContent('fresh:进行中');

    rejectDirectory = true;
    vi.setSystemTime(32_000);
    fireEvent.click(screen.getByRole('button', { name: '刷新目录状态' }));
    await flushRequests();
    expect(screen.getByTestId('directory-state')).toHaveTextContent('stale:状态未知');
  });
});

function renderDirectory(
  transport: MockControlTransport,
  props: { maintenancePollIntervalMs: number; pollIntervalMs: number },
) {
  return render(
    <ControlTransportProvider transport={transport}>
      <PawWorkDirectoryProvider {...props}>
        <DirectoryProbe />
      </PawWorkDirectoryProvider>
    </ControlTransportProvider>,
  );
}

function DirectoryProbe() {
  const directory = usePawWorkDirectory();
  const item = projectWayfinderWork({
    nowMs: Date.now(),
    roomStatusFresh: directory.roomStatusFresh,
    rooms: directory.rooms,
    sessionStatusFresh: directory.sessionStatusFresh,
    sessions: directory.sessions,
  }).projects[0]?.items[0];
  return (
    <>
      <output data-testid="directory-state">
        {directory.sessionStatusFresh && directory.roomStatusFresh ? 'fresh' : 'stale'}:{item?.statusLabel ?? 'none'}
      </output>
      <button onClick={() => void directory.refresh()} type="button">刷新目录状态</button>
    </>
  );
}

function directoryTransport() {
  return new MockControlTransport({ routes: {
    'agent.sessions.list': { ok: true, items: [session('busy')] },
    'agent.rooms.list': { ok: true, items: [] },
    'agent.memoryMaintenance.run': { ok: true, projection: { running: false } },
  } });
}

function session(status: string) {
  return {
    id: 'session-1',
    title: '真实运行对话',
    mode: 'assistant',
    status,
    roleId: 'default',
    roleVersion: '1',
    roleBookRevisionId: 'r1',
    updatedAtMs: 1,
    workspaceRoots: ['/work/paw'],
  };
}

function requestCount(transport: MockControlTransport, pathId: string): number {
  return transport.requests.filter(({ request }) => request.pathId === pathId).length;
}

async function flushRequests() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
