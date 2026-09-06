import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlTransport } from '@/platform/transport';
import { PawRoomLiveFocusOverview } from './PawRoomLiveFocusOverview';
import type { RoomFocusProjection } from './room-focus-projection';

afterEach(() => { cleanup(); vi.useRealTimers(); });
const focus: RoomFocusProjection = {
  goal: { title: '真实通信', description: '', rootId: 'turn-1', state: 'running' },
  workItems: [], handoffs: [], flow: [], rootEvidence: [], counts: { active: 0, review: 0, blocked: 0, completed: 0 },
  partners: [
    { participantId: 'earth', sessionId: 's-earth', celestialName: 'Earth', displayName: 'Earth', collaborationRole: 'coordinator', state: 'running', currentAction: '整合结果', ownedWorkItemIds: [], unread: false },
    { participantId: 'mars', sessionId: 's-mars', celestialName: 'Mars', displayName: 'Mars', state: 'running', currentAction: '核对结果', ownedWorkItemIds: [], unread: false },
  ],
};

function mount(request: ControlTransport['request'], active = true, projection = focus) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const transport = { request } as ControlTransport;
  const result = render(<QueryClientProvider client={client}><ControlTransportProvider transport={transport}><PawRoomLiveFocusOverview focus={projection} roomId="room-1" active={active} /></ControlTransportProvider></QueryClientProvider>);
  return { ...result, client };
}

describe('live Room traffic reads', () => {
  it('reads a finished Room once instead of repeatedly fetching heavy retained trees', async () => {
    vi.useFakeTimers();
    const request = vi.fn(async (call) => call.pathId === 'agent.session.intercom.list' ? { ok: true, items: [] }
      : { ok: true, tree: { rootSessionId: call.query.sessionId, roots: [], nodeCount: 0 } });
    const terminal: RoomFocusProjection = { ...focus, goal: { ...focus.goal, state: 'completed' }, partners: focus.partners.map((partner) => ({ ...partner, state: 'completed' })) };
    mount(request as ControlTransport['request'], true, terminal);
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    expect(request).toHaveBeenCalledTimes(3);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(request).toHaveBeenCalledTimes(3);
  });

  it('uses one Room-wide queue read and one private-tree read per planet, keeping a failed read unknown', async () => {
    const request = vi.fn(async (call) => {
      if (call.pathId === 'agent.session.intercom.list') return { ok: true, items: [] };
      if (call.query?.sessionId === 's-mars') throw new Error('temporarily unavailable');
      return { ok: true, tree: { rootSessionId: 's-earth', roots: [], nodeCount: 0 } };
    });
    mount(request as ControlTransport['request']);
    const mesh = screen.getByRole('group', { name: '协作网状图' });
    await waitFor(() => expect(within(mesh).getByRole('button', { name: /^Earth，/ })).toHaveTextContent('卫星 0'));
    await waitFor(() => expect(within(mesh).getByRole('button', { name: /^Mars，/ })).toHaveTextContent('卫星暂不可用'));
    expect(request.mock.calls.filter(([call]) => call.pathId === 'agent.session.intercom.list')).toHaveLength(1);
    expect(request.mock.calls.filter(([call]) => call.pathId === 'agent.subagents.list')).toHaveLength(2);
    expect(request.mock.calls.every(([call]) => ['agent.session.intercom.list', 'agent.subagents.list'].includes(call.pathId))).toBe(true);
  });

  it('does not poll an inactive view or turn its missing data into zero', () => {
    const request = vi.fn();
    mount(request as ControlTransport['request'], false);
    expect(request).not.toHaveBeenCalled();
    expect(screen.getAllByText('卫星读取中')).toHaveLength(2);
    expect(screen.getByText('正在恢复 Room 的直接通信与消息记录…')).toBeInTheDocument();
    expect(screen.queryByText(/当前筛选没有可读取/)).not.toBeInTheDocument();
  });
});
