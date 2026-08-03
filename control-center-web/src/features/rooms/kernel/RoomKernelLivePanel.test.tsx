import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { Todo } from '@/contracts/generated/agent-workflow-state.v1';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RoomRootExecutionV3 } from '@/contracts/generated/room-root-execution.v3';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import { applyRoomKernelSnapshot, createRoomKernelProjection } from '@/contracts/room-kernel-reducer';
import { MockControlTransport } from '@/test/mock-transport';
import type { ControlRequest } from '@/platform/transport';
import { useRoomLiveStore } from '../state/live-store';
import {
  parseRoomTaskSubagentResponse,
  parseSnapshot,
  roomSubagentPollDelay,
  RoomKernelLivePanel,
} from './RoomKernelLivePanel';

describe('RoomKernelLivePanel production adapter', () => {
  afterEach(() => {
    cleanup();
    useRoomLiveStore.getState().reset();
    vi.useRealTimers();
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

  it('keeps authoritative Task times through live updates and a snapshot reload', async () => {
    let snapshotSequence = 1;
    let snapshotTaskRevision = 1;
    let snapshotTaskUpdatedAtMs = 1_000;
    let snapshotAuthorityRevision = 1;
    const snapshot = vi.fn(() => {
      const value = taskKernelSnapshot('room-a', 'running', 3, snapshotAuthorityRevision);
      value.lastSequence = snapshotSequence;
      value.tasks[0]!.revision = snapshotTaskRevision;
      value.taskUpdatedAtMsById[value.tasks[0]!.taskId] = snapshotTaskUpdatedAtMs;
      return value;
    });
    const transport = mockTransport({ snapshot });
    renderPanel(transport);

    await screen.findByText('进度已同步');
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.taskUpdatedAtMsById['room-a:task'],
    ).toBe(1_000);
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.sessionsById['session-a']?.todo?.revision,
    ).toBe(1);
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.tasksById['room-a:task']?.resultSummary,
    ).toBe('权威成果 1');

    transport.emit('agent.room.kernel.events', taskEvent(2, 2_000, 2, 2));
    await waitFor(() => expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.taskUpdatedAtMsById['room-a:task'],
    ).toBe(2_000));
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.tasksById['room-a:task']?.workspaceDelivery?.deliveryRevision,
    ).toBe(`sha256:${'2'.repeat(64)}`);

    transport.emit('agent.room.kernel.events', sessionEvent(3, 2, 2_500));
    await waitFor(() => expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.sessionsById['session-a']?.todo?.revision,
    ).toBe(2));

    snapshotSequence = 6;
    snapshotTaskRevision = 3;
    snapshotTaskUpdatedAtMs = 3_000;
    snapshotAuthorityRevision = 3;
    transport.emit('agent.room.kernel.events', taskEvent(5, 4_000, 4, 4));
    await waitFor(() => expect(snapshot).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.taskUpdatedAtMsById['room-a:task'],
    ).toBe(3_000));
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.sessionsById['session-a']?.todo?.revision,
    ).toBe(3);
    expect(
      useRoomLiveStore.getState().kernelProjections['room-a']?.tasksById['room-a:task']?.resultSummary,
    ).toBe('权威成果 3');
    expect(transport.subscriptionCalls.at(-1)?.request.lastEventId).toBe('room-a#6');
  });

  it('parses snapshot Task update times and rejects invalid values', () => {
    const raw = taskKernelSnapshot('room-a', 'running');
    raw.taskUpdatedAtMsById['room-a:task'] = 8_765;
    expect(parseSnapshot(raw, 'room-a').taskUpdatedAtMsById).toEqual({
      'room-a:task': 8_765,
    });
    expect(() => parseSnapshot({
      ...raw,
      taskUpdatedAtMsById: { 'room-a:task': -1 },
    }, 'room-a')).toThrow(/taskUpdatedAtMsById/);
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

  it('groups only matching Room-bound batches by causal task and drops protocol/private fields', () => {
    const matching = roomSubagentBatch({
      roomId: 'room-a',
      parentSessionId: 'session-a',
      taskId: 'task-a',
      task: '核对实时任务投影',
      state: 'completed',
    });
    const parsed = parseRoomTaskSubagentResponse({
      ok: true,
      items: [
        matching,
        {
          ...matching,
          id: 'batch-standalone',
          causalMetadata: {
            ...(matching.causalMetadata as Record<string, unknown>),
            roomBound: false,
          },
        },
        {
          ...matching,
          id: 'batch-other-room',
          causalMetadata: {
            ...(matching.causalMetadata as Record<string, unknown>),
            roomId: 'room-b',
          },
        },
        { ...matching, id: 'batch-other-parent', parentSessionId: 'session-b' },
      ],
    }, 'room-a', 'session-a', taskLineage('room-a', 'task-a'));

    expect(Object.keys(parsed.runsByTaskId)).toEqual(['task-a']);
    expect(parsed.runsByTaskId['task-a']).toEqual([
      expect.objectContaining({
        templateId: 'worker',
        ordinal: 0,
        task: '核对实时任务投影',
        state: 'completed',
        resultSummary: '已返回可复核的任务内结论',
      }),
    ]);
    const publicProjection = JSON.stringify(parsed);
    expect(publicProjection).not.toContain('run:session-a');
    expect(publicProjection).not.toContain('batch:session-a');
    expect(publicProjection).not.toContain('child-session-private');
    expect(publicProjection).not.toContain('private transcript');
  });

  it('purges stale Root generations and rejects foreign task dispatch lineage', async () => {
    let calls = 0;
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': () => taskKernelSnapshot('room-a', 'completed', 3),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': () => {
          calls += 1;
          return {
            ok: true,
            items: calls === 1
              ? [roomSubagentBatch({
                  generation: 3,
                  roomId: 'room-a',
                  parentSessionId: 'session-a',
                  taskId: 'room-a:task',
                  task: '旧一代任务内结果',
                  state: 'completed',
                })]
              : [
                  roomSubagentBatch({
                    generation: 3,
                    roomId: 'room-a',
                    parentSessionId: 'session-a',
                    taskId: 'room-a:task',
                    task: '不应保留的旧一代结果',
                    state: 'completed',
                  }),
                  roomSubagentBatch({
                    dispatchId: 'room-a:foreign-dispatch',
                    generation: 4,
                    roomId: 'room-a',
                    parentSessionId: 'session-a',
                    taskId: 'room-a:task',
                    task: '不应接纳的其他调度结果',
                    state: 'completed',
                  }),
                ],
          };
        },
      },
    });
    renderPanel(transport, true, ['session-a']);
    expect(await screen.findByText('旧一代任务内结果')).toBeInTheDocument();

    act(() => {
      useRoomLiveStore.getState().setKernelProjection(
        'room-a',
        applyRoomKernelSnapshot(
          createRoomKernelProjection('room-a'),
          parseSnapshot(taskKernelSnapshot('room-a', 'completed', 4), 'room-a'),
        ),
      );
    });

    await waitFor(() => expect(calls).toBe(2));
    await waitFor(() => expect(screen.queryByText('旧一代任务内结果')).not.toBeInTheDocument());
    expect(screen.queryByText('不应保留的旧一代结果')).not.toBeInTheDocument();
    expect(screen.queryByText('不应接纳的其他调度结果')).not.toBeInTheDocument();
  });

  it('deduplicates participant Sessions and keeps a healthy nested-run result when another endpoint fails', async () => {
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': () => taskKernelSnapshot('room-a', 'completed'),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': (request: ControlRequest) => {
          const sessionId = String(request.query?.sessionId ?? '');
          if (sessionId === 'session-failed') throw new Error('participant endpoint unavailable');
          return {
            ok: true,
            items: [roomSubagentBatch({
              roomId: 'room-a',
              parentSessionId: sessionId,
              taskId: 'room-a:task',
              task: '展示健康伙伴返回的子任务',
              state: 'completed',
            })],
          };
        },
      },
    });
    renderPanel(
      transport,
      true,
      ['session-healthy', 'session-healthy', 'session-failed'],
    );

    expect(await screen.findByText('执行助手 1')).toBeInTheDocument();
    expect(screen.getByText('展示健康伙伴返回的子任务')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private transcript');
    expect(document.body).not.toHaveTextContent('child-session-private');
    expect(document.body).not.toHaveTextContent('session-healthy');
    const subagentRequests = transport.requests.filter(({ request }) => (
      request.pathId === 'agent.subagents.list'
    ));
    expect(subagentRequests).toHaveLength(2);
    expect(subagentRequests.map(({ request }) => request.query?.sessionId).sort()).toEqual([
      'session-failed',
      'session-healthy',
    ]);
    expect(subagentRequests.every(({ request }) => request.query?.limit === 50)).toBe(true);
  });

  it('replaces a private child failure with Room-safe state text', async () => {
    const privateError = 'ENOENT /Users/alice/.ssh/id_ed25519; token=secret-child-token';
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': () => taskKernelSnapshot('room-a', 'completed'),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': () => ({
          ok: true,
          items: [roomSubagentBatch({
            roomId: 'room-a',
            parentSessionId: 'session-a',
            rawError: privateError,
            taskId: 'room-a:task',
            task: '处理失败但不公开私有诊断的子任务',
            state: 'failed',
          })],
        }),
      },
    });
    renderPanel(transport, true, ['session-a']);

    expect(await screen.findByText(
      '任务内协作者未能完成；负责人可检查任务状态后决定是否重试。',
    )).toBeInTheDocument();
    expect(screen.getByText('调用失败')).toBeInTheDocument();
    expect(screen.queryByText(privateError)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('/Users/alice/.ssh/id_ed25519');
    expect(document.body).not.toHaveTextContent('secret-child-token');
  });

  it('polls a known active child until its terminal response, then stops for a terminal Room', async () => {
    vi.useFakeTimers();
    expect(roomSubagentPollDelay(true, false)).toBe(1_000);
    expect(roomSubagentPollDelay(false, true)).toBe(5_000);
    expect(roomSubagentPollDelay(false, false)).toBeNull();
    let calls = 0;
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': () => taskKernelSnapshot('room-a', 'completed'),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': () => {
          calls += 1;
          return {
            ok: true,
            items: [roomSubagentBatch({
              roomId: 'room-a',
              parentSessionId: 'session-a',
              taskId: 'room-a:task',
              task: '完成后停止轮询的子任务',
              state: calls === 1 ? 'running' : 'completed',
            })],
          };
        },
      },
    });
    act(() => {
      useRoomLiveStore.getState().setKernelProjection(
        'room-a',
        applyRoomKernelSnapshot(
          createRoomKernelProjection('room-a'),
          parseSnapshot(taskKernelSnapshot('room-a', 'completed'), 'room-a'),
        ),
      );
    });
    renderPanel(transport, true, ['session-a']);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls).toBe(1);
    expect(screen.getByText('执行助手 1')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(calls).toBe(2);
    expect(screen.getByText('已返回')).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(calls).toBe(2);
  });

  it('ignores a late participant response after switching Rooms', async () => {
    const stale = deferred<unknown>();
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': (request: ControlRequest) => taskKernelSnapshot(
          String(request.params?.roomId ?? ''),
          'completed',
        ),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': (request: ControlRequest) => {
          const sessionId = String(request.query?.sessionId ?? '');
          if (sessionId === 'session-a') return stale.promise;
          return {
            ok: true,
            items: [roomSubagentBatch({
              roomId: 'room-b',
              parentSessionId: 'session-b',
              taskId: 'room-b:task',
              task: '新协作空间的子任务',
              state: 'completed',
            })],
          };
        },
      },
    });
    const view = render(
      <ControlTransportProvider transport={transport}>
        <RoomKernelLivePanel
          participantSessionIds={['session-a']}
          roomId="room-a"
          visible
        />
      </ControlTransportProvider>,
    );
    await waitFor(() => expect(transport.requests.some(({ request }) => (
      request.pathId === 'agent.subagents.list'
      && request.query?.sessionId === 'session-a'
    ))).toBe(true));

    view.rerender(
      <ControlTransportProvider transport={transport}>
        <RoomKernelLivePanel
          participantSessionIds={['session-b']}
          roomId="room-b"
          visible
        />
      </ControlTransportProvider>,
    );
    expect(await screen.findByText('新协作空间的子任务')).toBeInTheDocument();

    stale.resolve({
      ok: true,
      items: [roomSubagentBatch({
        roomId: 'room-a',
        parentSessionId: 'session-a',
        taskId: 'room-a:task',
        task: '旧协作空间的迟到私有结果',
        state: 'completed',
      })],
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByText('旧协作空间的迟到私有结果')).not.toBeInTheDocument();
    expect(screen.getByText('新协作空间的子任务')).toBeInTheDocument();
  });

  it('aborts an in-flight participant status read when the live panel unmounts', async () => {
    const pending = deferred<unknown>();
    let requestSignal: AbortSignal | undefined;
    const transport = new MockControlTransport({
      capabilities: capabilityValue(),
      routes: {
        'agent.room.kernel.snapshot': () => taskKernelSnapshot('room-a', 'completed'),
        'agent.room.kernel.command': () => kernelReceipt({}),
        'agent.subagents.list': (request: ControlRequest) => {
          requestSignal = request.signal;
          return pending.promise;
        },
      },
    });
    const view = renderPanel(transport, true, ['session-a']);
    await waitFor(() => expect(requestSignal).toBeDefined());

    view.unmount();
    expect(requestSignal?.aborted).toBe(true);
    pending.resolve({ ok: true, items: [] });
    await act(async () => {
      await Promise.resolve();
    });
  });
});

function renderPanel(
  transport: MockControlTransport,
  visible = true,
  participantSessionIds: readonly string[] = [],
) {
  return render(
    <ControlTransportProvider transport={transport}>
      <RoomKernelLivePanel
        participantSessionIds={participantSessionIds}
        roomId="room-a"
        visible={visible}
      />
    </ControlTransportProvider>,
  );
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
    taskUpdatedAtMsById: {},
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
    terminalReceiptId: null, activeProfileRef: null, budgetPolicyRef: 'budget:default',
    independentReviewRequired: false, createdAtMs: 1,
  };
}

function rootEvent(sequence: number): RoomEventEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-event-envelope.v2', entityKind: 'root', entityId: 'root-a',
    eventKind: 'state_changed', sequence, occurredAtMs: sequence, payload: { root: root() },
  };
}

function taskEvent(
  sequence: number,
  occurredAtMs: number,
  revision: number,
  authorityRevision = 0,
): RoomEventEnvelopeV2 {
  const task = taskKernelSnapshot('room-a', 'running', 3, authorityRevision).tasks[0]!;
  return {
    schemaVersion: 'wisdom-weasel.room-event-envelope.v2',
    entityKind: 'task',
    entityId: task.taskId,
    eventKind: 'state_changed',
    sequence,
    occurredAtMs,
    payload: { task: { ...task, revision } },
  };
}

function sessionEvent(
  sequence: number,
  todoRevision: number,
  occurredAtMs: number,
): RoomEventEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-event-envelope.v2',
    entityKind: 'binding',
    entityId: 'session-a',
    eventKind: 'session_projection',
    sequence,
    occurredAtMs,
    payload: { session: authoritySession(todoRevision, occurredAtMs) },
  };
}

function kernelReceipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'cancel-a', rootId: 'root-a', commandId: 'command-a',
    receiptKind: 'root_cancelled', status: 'applied', generation: 4, details: {}, createdAtMs: 4, ...overrides,
  };
}

function taskKernelSnapshot(
  roomId: string,
  rootState: RoomRootExecutionV3['state'],
  generation = 3,
  authorityRevision = 0,
) {
  const rootId = `${roomId}:root`;
  const terminal = ['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(rootState);
  const task: RoomTaskV3 = {
    schemaVersion: 'wisdom-weasel.room-task.v3',
    taskId: `${roomId}:task`,
    rootId,
    parentTaskId: null,
    taskKind: 'work',
    currentOwnerParticipantId: 'researcher',
    ownershipRevision: 0,
    ownershipReceiptId: null,
    objective: '核对任务内协作投影',
    expectedOutput: '可复核的公开任务状态',
    requirementItemIds: [],
    acceptanceCriterionIds: [],
    contextEvidenceRefs: [],
    invitationId: null,
    reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [],
    reviewState: 'not_required',
    revision: 1,
    state: terminal ? 'completed' : 'active',
    ...(authorityRevision ? authorityTaskFields(authorityRevision) : {}),
  };
  return {
    roomId,
    lastSequence: 1,
    snapshotHash: `sha256:${'c'.repeat(64)}`,
    roots: [{
      ...root(),
      rootId,
      roomId,
      generation,
      state: rootState,
      terminalReceiptId: null,
    }],
    tasks: [task],
    taskUpdatedAtMsById: { [task.taskId]: 1_500 },
    dispatches: [{
      schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
      dispatchId: `${roomId}:dispatch`,
      rootId,
      taskId: task.taskId,
      parentDispatchId: null,
      generation,
      hopCount: 1,
      depth: 1,
      budgetCost: 1,
      targetSessionId: 'session-a',
      targetParticipantId: 'researcher',
      triggerId: `${roomId}:trigger`,
      intentKind: 'execute',
      idempotencyKey: `${roomId}:dispatch`,
      attempt: 0,
      capabilityEpoch: 1,
      runtimeProfileRevision: 'test-v1',
      alignmentOrdinal: 1,
      dependsOnDispatchIds: [],
      attachmentIds: [],
      state: 'committed',
    }],
    posts: [],
    sessions: authorityRevision ? [authoritySession(authorityRevision, authorityRevision * 1_000)] : [],
    receipts: [],
    cancellationSurfaces: [],
  };
}

function authorityTaskFields(revision: number): Pick<
  RoomTaskV3,
  | 'workItemId'
  | 'resultSummary'
  | 'resultKind'
  | 'resultAtMs'
  | 'verificationCount'
  | 'verifications'
  | 'artifactRefs'
  | 'residualRisks'
  | 'workspaceDelivery'
> {
  return {
    workItemId: 'work-item-a',
    resultSummary: `权威成果 ${revision}`,
    resultKind: 'complete',
    resultAtMs: revision * 1_000,
    verificationCount: 1,
    verifications: [{ label: `验证 ${revision}`, result: 'pass', source: 'quality_gate' }],
    artifactRefs: [`artifact:${revision}`],
    residualRisks: [],
    workspaceDelivery: {
      schemaVersion: 'wisdom-weasel.room-workspace-delivery.v1',
      ownerParticipantId: 'researcher',
      ownerSessionId: 'session-a',
      workItemId: 'work-item-a',
      taskId: 'room-a:task',
      deliveryRevision: `sha256:${String(revision).repeat(64)}`,
      baseCommit: 'git:base',
      workspaceSnapshotSha256: 'a'.repeat(64),
      patchSha256: 'b'.repeat(64),
      deliveredAtMs: revision * 1_000,
      resultSummary: `权威成果 ${revision}`,
      manifestSha256: String(revision).repeat(64),
      files: [{
        path: 'control-center-web/src/RoomTaskCard.tsx',
        additions: revision,
        deletions: 0,
        binary: false,
        generated: false,
        redacted: false,
      }],
      totals: {
        fileCount: 1,
        additions: revision,
        deletions: 0,
        binaryFiles: 0,
        generatedFiles: 0,
        redactedFiles: 0,
      },
      artifactRefs: [`artifact:${revision}`],
      verificationCount: 1,
      verifications: [{ label: `验证 ${revision}`, result: 'pass', source: 'quality_gate' }],
      verificationRefs: [`verification:${revision}`],
      residualRisks: [],
    },
  };
}

function authoritySession(todoRevision: number, updatedAtMs: number) {
  const todo: Todo = {
    schemaVersion: 'rag-ime.agent-todo.v1',
    id: 'todo:session-a',
    sessionId: 'session-a',
    revision: todoRevision,
    actor: 'agent-runtime',
    updatedAtMs,
    roomLineage: {
      schemaVersion: 'wisdom-weasel.room-todo-lineage.v1',
      roomId: 'room-a',
      rootId: 'room-a:root',
      taskId: 'room-a:task',
      workItemId: 'work-item-a',
      dispatchId: 'room-a:dispatch',
      sessionId: 'session-a',
      participantId: 'researcher',
      generation: 3,
      taskRevision: todoRevision,
      ownershipRevision: 1,
      workItemRevision: 1,
    },
    phases: [{
      name: '执行',
      tasks: [{ content: `权威 Todo ${todoRevision}`, status: 'in_progress' }],
    }],
    counts: {
      total: 1,
      pending: 0,
      inProgress: 1,
      blocked: 0,
      completed: 0,
      abandoned: 0,
    },
  };
  return {
    sessionId: 'session-a',
    participantId: 'researcher',
    rootId: 'room-a:root',
    taskId: 'room-a:task',
    taskKind: 'work' as const,
    workItemId: 'work-item-a',
    dispatchId: 'room-a:dispatch',
    generation: 3,
    state: 'running' as const,
    updatedAtMs,
    todo,
  };
}

function roomSubagentBatch({
  roomId,
  dispatchId = `${roomId}:dispatch`,
  generation = 3,
  parentSessionId,
  rawError = '',
  state,
  task,
  taskId,
}: {
  roomId: string;
  dispatchId?: string;
  generation?: number;
  parentSessionId: string;
  rawError?: string;
  state: 'running' | 'completed' | 'failed';
  task: string;
  taskId: string;
}): Record<string, unknown> {
  const batchId = `batch:${parentSessionId}`;
  const now = Date.now();
  return {
    schemaVersion: 'rag-ime.agent-subagent-batch.v1',
    id: batchId,
    parentSessionId,
    parentRunId: `parent:${parentSessionId}`,
    contextMode: 'fork',
    resultDeliveryMode: 'inline',
    state,
    depth: 1,
    maxDepth: 2,
    abortRequested: false,
    causalMetadata: {
      todoId: `todo:${taskId}`,
      todoRevision: 1,
      goalId: `goal:${roomId}`,
      goalRevision: 1,
      roomBound: true,
      roomId,
      rootId: `${roomId}:root`,
      taskId,
      dispatchId,
      generation,
    },
    createdAtMs: now - 10_000,
    updatedAtMs: now,
    completedAtMs: state === 'running' ? null : now,
    privateTranscript: 'private transcript',
    runs: [{
      schemaVersion: 'rag-ime.agent-subagent-run.v1',
      id: `run:${parentSessionId}`,
      batchId,
      childSessionId: 'child-session-private',
      todoTask: '验证投影',
      todoPhase: '执行',
      templateId: 'worker',
      templateVersion: '1',
      ordinal: 0,
      task,
      expectedOutput: '可复核结果',
      acceptanceCriteria: ['显示状态'],
      outputSchema: {},
      state,
      budget: {
        maxTurns: 6,
        maxToolCalls: 8,
        maxTotalTokens: 12_000,
        maxDurationMs: 180_000,
        maxOutputChars: 8_000,
      },
      usage: { turnCount: 2, toolCount: 3, totalTokens: 1_200 },
      result: state === 'completed'
        ? { summary: '已返回可复核的任务内结论', transcript: 'private transcript' }
        : {},
      error: rawError,
      resultContextScheduledAtMs: state === 'completed' ? now : null,
      createdAtMs: now - 10_000,
      startedAtMs: now - 9_000,
      updatedAtMs: now,
      completedAtMs: state === 'running' ? null : now,
    }],
  };
}

function taskLineage(
  roomId: string,
  taskId: string,
  generation = 3,
  dispatchIds: readonly string[] = [`${roomId}:dispatch`],
) {
  return new Map([[
    taskId,
    {
      rootId: `${roomId}:root`,
      generation,
      validDispatchIds: new Set(dispatchIds),
    },
  ]]);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}
