import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRoomKernelProjection, type RoomKernelProjection } from '@/contracts/room-kernel-reducer';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';

describe('RoomKernelControlPlane', () => {
  afterEach(cleanup);

  it('renders explicit Posts separately from private Session state and receipts', () => {
    renderPlane(projection());

    expect(screen.getByRole('region', { name: 'root-a 公开 Posts' })).toHaveTextContent('经过明确提交的研究发现');
    expect(screen.getByRole('region', { name: 'root-a 私有 Sessions' })).toHaveTextContent('session-private-a');
    expect(screen.getByRole('region', { name: 'root-a 私有 Sessions' })).toHaveTextContent('Transcript私有，不投影到 Room');
    expect(screen.getByRole('region', { name: 'root-a 运行回执' })).toHaveTextContent('context-17');
    expect(screen.getByRole('region', { name: 'root-a 运行回执' })).toHaveTextContent('capability-9');
    expect(screen.getByText('已完成，等待终态回执')).toBeInTheDocument();
    expect(screen.queryByText('Session 私有正文')).not.toBeInTheDocument();
  });

  it('emits a typed Stop target for the selected Root and does not stop another Root', () => {
    const onRequestStop = vi.fn();
    renderPlane(projection(), onRequestStop);

    fireEvent.click(screen.getAllByRole('button', { name: '停止' })[0]!);
    expect(onRequestStop).toHaveBeenCalledTimes(1);
    expect(onRequestStop).toHaveBeenCalledWith({ roomId: 'room-a', rootId: 'root-a', generation: 3 });
  });

  it('shows terminal receipt state without an active Stop command', () => {
    const state = projection();
    state.rootsById['root-a'] = { ...state.rootsById['root-a']!, isFinal: true };
    state.terminalReceiptsByRootId['root-a'] = {
      receiptId: 'terminal-a', rootId: 'root-a', generation: 3,
      terminalState: 'completed', quiescent: true, acceptancePassed: true,
    };
    renderPlane(state);

    expect(screen.getByText('终态已确认')).toBeInTheDocument();
    expect(screen.getByText('completed · terminal-a')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '停止' })).toHaveLength(1);
  });
});

function renderPlane(state: RoomKernelProjection, onRequestStop = vi.fn()) {
  return render(<RoomKernelControlPlane
    projection={state}
    budgetsByRootId={{
      'root-a': { maxDispatches: 8, usedDispatches: 3, maxTokens: 32_000, usedTokens: 12_000, maxWallTimeMs: 300_000, elapsedMs: 80_000 },
      'root-b': { maxDispatches: 4, usedDispatches: 1, maxTokens: 16_000, usedTokens: 2_000, maxWallTimeMs: 180_000, elapsedMs: 20_000 },
    }}
    contextReceiptsByRootId={{ 'root-a': { revision: 'context-17', status: 'sealed', contentHash: `sha256:${'a'.repeat(64)}` } }}
    capabilityReceiptsByRootId={{ 'root-a': { revision: 'capability-9', status: 'sealed', contentHash: `sha256:${'b'.repeat(64)}` } }}
    onRequestStop={onRequestStop}
  />);
}

function projection(): RoomKernelProjection {
  const state = createRoomKernelProjection('room-a');
  state.lastSequence = 12;
  state.rootsById['root-a'] = { rootId: 'root-a', generation: 3, state: 'completed', ownerParticipantId: '研究员', isFinal: false, updatedAtMs: 12 };
  state.rootsById['root-b'] = { rootId: 'root-b', generation: 1, state: 'running', ownerParticipantId: '审查员', isFinal: false, updatedAtMs: 11 };
  state.runtimeByRootId['root-a'] = { generation: 3, stopRequest: null };
  state.runtimeByRootId['root-b'] = { generation: 1, stopRequest: null };
  state.postOrder.push('post-a');
  state.postsById['post-a'] = { postId: 'post-a', roomId: 'room-a', rootId: 'root-a', sequence: 1, authorParticipantId: '研究员', kind: 'finding', visibility: 'room', content: '经过明确提交的研究发现', createdAtMs: 1 };
  state.sessionsById['session-private-a'] = { sessionId: 'session-private-a', rootId: 'root-a', generation: 3, state: 'completed', updatedAtMs: 10 };
  return state;
}
