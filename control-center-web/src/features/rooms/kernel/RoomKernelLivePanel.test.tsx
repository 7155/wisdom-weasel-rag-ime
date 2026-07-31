import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RoomRootExecutionV3 } from '@/contracts/generated/room-root-execution.v3';
import { applyRoomKernelSnapshot, createRoomKernelProjection } from '@/contracts/room-kernel-reducer';
import { MockControlTransport } from '@/test/mock-transport';
import { useRoomLiveStore } from '../state/live-store';
import { parseSnapshot, RoomKernelLivePanel } from './RoomKernelLivePanel';

describe('RoomKernelLivePanel production adapter', () => {
  afterEach(() => {
    cleanup();
    useRoomLiveStore.getState().reset();
  });

  it('loads canonical snapshot, resumes SSE and sends authorized typed Stop', async () => {
    const command = vi.fn((request) => kernelReceipt({
      commandId: (request.body as Record<string, unknown>).commandId as string,
      generation: 4,
    }));
    const transport = mockTransport({ command });
    renderPanel(transport);

    expect(await screen.findByText('进度已同步')).toBeInTheDocument();
    expect(transport.subscriptionCalls[0]?.request.lastEventId).toBe('room-a#1');
    const stop = screen.getByRole('button', { name: '停止此任务' });
    expect(stop).toBeEnabled();
    fireEvent.click(stop);
    expect(await screen.findByText('停止请求已接受')).toBeInTheDocument();
    expect(command).toHaveBeenCalledTimes(1);
    expect(command.mock.calls[0]?.[0].body).toMatchObject({
      roomId: 'room-a', rootId: 'root-a', generation: 3, commandKind: 'cancel_root',
    });
  });

  it.each([
    ['rejected', '停止请求被拒绝'],
    ['unknown', '仍在确认停止状态'],
  ] as const)('shows a %s command receipt without deriving Root state', async (status, label) => {
    const transport = mockTransport({
      command: (request) => kernelReceipt({
        commandId: (request.body as Record<string, unknown>).commandId as string,
        generation: 4,
        status,
        receiptKind: status === 'unknown' ? 'dispatch_unknown' : 'rejected',
      }),
    });
    renderPanel(transport);
    fireEvent.click(await screen.findByRole('button', { name: '停止此任务' }));
    expect(await screen.findByText(new RegExp(label))).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '协作任务进展' })).toHaveTextContent('执行中');
  });

  it('reports reconnect and recovers a sequence gap from a fresh snapshot', async () => {
    let snapshotSequence = 1;
    const snapshot = vi.fn(() => kernelSnapshot(snapshotSequence));
    const transport = mockTransport({ snapshot });
    renderPanel(transport);
    await screen.findByText('进度已同步');

    transport.simulateReconnect('agent.room.kernel.events', 25);
    expect(await screen.findByText(/第 1 次重连 · 25ms/)).toBeInTheDocument();
    snapshotSequence = 5;
    transport.emit('agent.room.kernel.events', rootEvent(3));
    await waitFor(() => expect(snapshot).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('region', { name: '协作任务进展' })).toHaveTextContent('状态已同步');
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a#5');
  });

  it('keeps unknown cancellation non-final after reconnect and shows pending targets', async () => {
    let unknown = false;
    const snapshot = vi.fn(() => kernelSnapshot(unknown ? 8 : 1, unknown));
    const transport = mockTransport({ snapshot });
    renderPanel(transport);
    await screen.findByText('进度已同步');

    unknown = true;
    transport.emit('agent.room.kernel.events', rootEvent(3));
    await waitFor(() => expect(snapshot).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('alert')).toHaveTextContent('还有后台工作没有确认停止');
    expect(screen.getByRole('button', { name: '再次确认停止' })).toBeInTheDocument();
    expect(screen.queryByText('任务已结束')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('模型服务等待确认1 个后台目标');
  });

  it('keeps the command disabled when authorization or route hash does not match', async () => {
    const capabilities = capabilityValue();
    const raw = capabilities.raw as { routes: Array<Record<string, unknown>> };
    raw.routes.find((route) => route.pathId === 'agent.room.kernel.command')!.method = 'PATCH';
    const transport = mockTransport({ capabilities });
    renderPanel(transport);
    const stop = await screen.findByRole('button', { name: '停止此任务' });
    expect(stop).toBeDisabled();
    expect(stop).toHaveAttribute('title', '停止任务的控制通道已发生变化，请刷新或更新应用');
  });

  it('reads a valid Room-managed Kernel snapshot even when capability metadata is stale', async () => {
    const capabilities = capabilityValue();
    const raw = capabilities.raw as { routes: Array<Record<string, unknown>> };
    raw.routes.find((route) => route.pathId === 'agent.room.kernel.events')!.query = [];
    const transport = mockTransport({ capabilities });

    renderPanel(transport);

    expect(await screen.findByText('进度已同步')).toBeInTheDocument();
    expect(screen.queryByText('进度同步异常')).not.toBeInTheDocument();
    expect(screen.queryByText(/任务进度暂时不可用/)).not.toBeInTheDocument();
    expect(screen.getByText(/更新于/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止此任务' })).toHaveAttribute(
      'title',
      '任务进度已连接，但任务控制能力清单尚未确认',
    );
  });

  it('does not regress a confirmed projection when reconnect hydration returns an older snapshot', async () => {
    const cached = applyRoomKernelSnapshot(
      createRoomKernelProjection('room-a'),
      parseSnapshot(kernelSnapshot(5), 'room-a'),
    );
    useRoomLiveStore.getState().setKernelProjection('room-a', cached);
    const snapshot = vi.fn(() => kernelSnapshot(3));
    const transport = mockTransport({ snapshot });

    renderPanel(transport);

    expect(await screen.findByText('进度已同步')).toBeInTheDocument();
    expect(useRoomLiveStore.getState().kernelProjections['room-a']?.lastSequence).toBe(5);
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a#5');
  });

  it('rejects an old-generation Stop receipt and leaves the Root projection unchanged', async () => {
    const transport = mockTransport({
      command: (request) => kernelReceipt({
        commandId: (request.body as Record<string, unknown>).commandId as string,
        generation: 3,
      }),
    });
    renderPanel(transport);
    fireEvent.click(await screen.findByRole('button', { name: '停止此任务' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('停止结果与当前任务状态不一致');
    expect(screen.getByRole('region', { name: '协作任务进展' })).toHaveTextContent('执行中');
  });

  it('hydrates authoritative task progress while its visual panel is hidden', async () => {
    const transport = mockTransport();
    renderPanel(transport, false);

    await waitFor(() => expect(transport.requests.some((request) => (
      request.request.pathId === 'agent.room.kernel.snapshot'
    ))).toBe(true));
    expect(screen.queryByRole('region', { name: '协作任务状态' })).not.toBeInTheDocument();
  });

  it('offers an in-place retry when the task snapshot cannot be read', async () => {
    const snapshot = vi.fn()
      .mockImplementationOnce(() => { throw new Error('temporary snapshot failure'); })
      .mockImplementation(() => kernelSnapshot(2));
    const transport = mockTransport({ snapshot });
    renderPanel(transport);

    expect(await screen.findByRole('alert')).toHaveTextContent('任务进度暂时不可用');
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }));

    expect(await screen.findByText('进度已同步')).toBeInTheDocument();
    expect(snapshot).toHaveBeenCalledTimes(2);
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a#2');
  });

  it('keeps the last confirmed projection visible when reconnect recovery fails', async () => {
    const snapshot = vi.fn()
      .mockImplementationOnce(() => kernelSnapshot(1))
      .mockImplementation(() => { throw new Error('recovery snapshot offline'); });
    const transport = mockTransport({ snapshot });
    renderPanel(transport);
    await screen.findByText('进度已同步');

    transport.emit('agent.room.kernel.events', rootEvent(3));

    expect(await screen.findByText('实时更新暂时中断')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '协作任务进展' })).toHaveTextContent('执行中');
    expect(screen.getByText(/继续显示上次确认的进度/)).toBeInTheDocument();
    expect(screen.queryByText('进度同步异常')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新读取' })).toBeEnabled();
  });

  it('shows permission denial and never subscribes or renders mutation controls', async () => {
    const denied = Object.assign(new Error('agent.read scope required'), { status: 403 });
    const transport = mockTransport({ snapshot: () => { throw denied; } });
    renderPanel(transport);
    expect(await screen.findByRole('alert')).toHaveTextContent('当前连接没有查看任务进度的权限');
    expect(transport.activeSubscriptionCount()).toBe(0);
    expect(screen.queryByRole('button', { name: '停止此任务' })).not.toBeInTheDocument();
  });
});

function renderPanel(transport: MockControlTransport, visible = true) {
  return render(<ControlTransportProvider transport={transport}><RoomKernelLivePanel roomId="room-a" visible={visible} /></ControlTransportProvider>);
}

function mockTransport(options: {
  snapshot?: () => unknown;
  command?: (request: { body?: unknown }) => RoomKernelReceiptV1;
  capabilities?: ReturnType<typeof capabilityValue>;
} = {}) {
  return new MockControlTransport({
    capabilities: options.capabilities ?? capabilityValue(),
    routes: {
      'agent.room.kernel.snapshot': options.snapshot ?? (() => kernelSnapshot(1)),
      'agent.room.kernel.command': options.command ?? ((request: { body?: unknown }) => kernelReceipt({
        commandId: (request.body as Record<string, unknown>).commandId as string, generation: 4,
      })),
    },
  });
}

function capabilityValue() {
  return {
    schemaVersion: 'rag-ime.control-capabilities.v1',
    routeIds: ['agent.room.kernel.snapshot', 'agent.room.kernel.events', 'agent.room.kernel.command'] as const,
    features: {},
    native: {
      pickFiles: false, managedAgentImageImport: false, revealPath: false,
      approvedExternalActions: false, keychain: false, tcc: false,
    },
    raw: {
      client: { remote: false, deviceAuthenticated: false, grantedScopes: [] },
      features: {},
      routes: [
        route('agent.room.kernel.snapshot', 'GET', false, ['agent.read'], []),
        route('agent.room.kernel.events', 'GET', true, ['agent.read'], ['lastEventId']),
        route('agent.room.kernel.command', 'POST', false, ['agent.write'], []),
      ],
    },
  };
}

function route(pathId: string, method: string, subscription: boolean, remoteScopes: string[], query: string[]) {
  return { pathId, method, remoteSafe: true, subscription, params: ['roomId'], query, remoteScopes };
}

function kernelSnapshot(lastSequence: number, unknown = false) {
  const rootValue = root();
  if (unknown) {
    rootValue.state = 'cancelled_with_unknowns';
    rootValue.terminalReceiptId = 'terminal-stale';
  }
  return {
    roomId: 'room-a', lastSequence, snapshotHash: `sha256:${'a'.repeat(64)}`,
    roots: [rootValue], tasks: [], dispatches: [], posts: [], sessions: [],
    receipts: unknown ? [kernelReceipt({ receiptId: 'terminal-stale', receiptKind: 'terminal', generation: 3 })] : [],
    cancellationSurfaces: unknown ? [{
      cancelId: 'cancel:1', rootId: 'root-a', dispatchId: 'dispatch:1', surface: 'provider', state: 'unknown',
      targetRef: '', detail: { targetIds: ['provider:turn-1'] }, updatedAtMs: 8,
    }] : [],
  };
}

function root(): RoomRootExecutionV3 {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3', rootId: 'root-a', roomId: 'room-a', generation: 3,
    state: 'running', facilitatorParticipantId: 'researcher', reporterParticipantId: null,
    reporterSelectionReceiptId: null, requirementAnchorRef: 'requirement:1', createdByActorRef: 'user:1',
    terminalReceiptId: null, activeProfileRef: null, budgetPolicyRef: 'budget:default', createdAtMs: 1,
  };
}

function rootEvent(sequence: number): RoomEventEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-event-envelope.v2', entityKind: 'root', entityId: 'root-a',
    eventKind: 'state_changed', sequence, occurredAtMs: sequence, payload: { root: root() },
  };
}

function kernelReceipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'cancel-a', rootId: 'root-a', commandId: 'command-a',
    receiptKind: 'root_cancelled', status: 'applied', generation: 4, details: {}, createdAtMs: 4, ...overrides,
  };
}
