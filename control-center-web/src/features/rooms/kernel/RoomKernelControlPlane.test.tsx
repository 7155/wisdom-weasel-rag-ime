import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { createRoomKernelProjection, type RoomKernelProjection, type RootProjection } from '@/contracts/room-kernel-reducer';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { createFixtureRoomKernelCommandTransport } from './room-kernel-command-transport';

describe('RoomKernelControlPlane', () => {
  afterEach(cleanup);

  it('renders generated projections and keeps Session transcript private', () => {
    renderPlane(projection());
    expect(screen.getByRole('region', { name: 'root-a 公开 Posts' })).toHaveTextContent('经过明确提交的研究发现');
    expect(screen.getByRole('region', { name: 'root-a 私有 Sessions' })).toHaveTextContent('session-private-a');
    expect(screen.queryByText('Session 私有正文')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'root-a 运行回执' })).toHaveTextContent('只读，控制命令未授权');
  });

  it('does not expose a production Stop write without a command transport', () => {
    renderPlane(projection());
    const buttons = screen.getAllByRole('button', { name: '停止' });
    expect(buttons[0]).toBeDisabled();
    expect(buttons[0]).toHaveAttribute('title', '后端 command route 尚未接入');
  });

  it('sends canonical room root generation command through fixture transport and displays receipt', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'cancel-root-a', commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    const transport = createFixtureRoomKernelCommandTransport(handler);
    renderPlane(projection(), transport);

    fireEvent.click(screen.getAllByRole('button', { name: '停止' })[0]!);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      schemaVersion: 'wisdom-weasel.room-kernel-command.v1', roomId: 'room-a', rootId: 'root-a',
      targetKind: 'root', targetId: 'root-a', generation: 3, commandKind: 'cancel_root',
    });
    expect(await screen.findByText(/已接受 · root_cancelled · cancel-root-a/)).toBeInTheDocument();
  });

  it('targets the keyboard-selected concurrent Root only', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: `cancel-${command.rootId}`, commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    renderPlane(projection(), createFixtureRoomKernelCommandTransport(handler));
    const buttons = screen.getAllByRole('button', { name: '停止' });
    buttons[1]!.focus();
    fireEvent.keyDown(buttons[1]!, { key: 'Enter' });
    fireEvent.click(buttons[1]!);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({ rootId: 'root-b', generation: 1 });
  });

  it('shows final only from the read projection terminal receipt', () => {
    const state = projection();
    state.rootsById['root-a'] = { ...state.rootsById['root-a']!, state: 'completed', terminalReceiptId: 'terminal-a', isFinal: true };
    state.terminalReceiptByRootId['root-a'] = receipt({
      receiptId: 'terminal-a', commandId: null, receiptKind: 'terminal', rootId: 'root-a', generation: 3,
    });
    renderPlane(state);
    expect(screen.getByText('终态已确认')).toBeInTheDocument();
    expect(screen.getByText('terminal/applied · terminal-a')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '停止' })).toHaveLength(1);
  });

  it('exposes Room panic only for an admin gate and requires explicit confirmation', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'panic-room-a', commandId: command.commandId, rootId: null,
      generation: 0, receiptKind: 'panic', status: 'applied',
    }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPlane(projection(), createFixtureRoomKernelCommandTransport(handler), true);
    const panic = screen.getByRole('button', { name: '紧急停止' });
    fireEvent.click(panic);
    expect(handler).not.toHaveBeenCalled();
    fireEvent.click(panic);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      roomId: 'room-a', rootId: null, commandKind: 'panic', targetKind: null, generation: 0,
    });
    expect(await screen.findByText(/已接受 · panic · panic-room-a/)).toBeInTheDocument();
    confirm.mockRestore();
  });
});

function renderPlane(state: RoomKernelProjection, commandTransport?: ReturnType<typeof createFixtureRoomKernelCommandTransport>, panicEnabled = false) {
  return render(<RoomKernelControlPlane
    projection={state}
    budgetsByRootId={{
      'root-a': { maxDispatches: 8, usedDispatches: 3, maxTokens: 32_000, usedTokens: 12_000, maxWallTimeMs: 300_000, elapsedMs: 80_000 },
      'root-b': { maxDispatches: 4, usedDispatches: 1, maxTokens: 16_000, usedTokens: 2_000, maxWallTimeMs: 180_000, elapsedMs: 20_000 },
    }}
    contextReceiptsByRootId={{ 'root-a': { revision: 'context-17', status: 'sealed', contentHash: `sha256:${'a'.repeat(64)}` } }}
    capabilityReceiptsByRootId={{ 'root-a': { revision: 'capability-9', status: 'sealed', contentHash: `sha256:${'b'.repeat(64)}` } }}
    commandTransport={commandTransport}
    panicEnabled={panicEnabled}
  />);
}

function projection(): RoomKernelProjection {
  const state = createRoomKernelProjection('room-a');
  state.lastSequence = 12;
  state.rootsById['root-a'] = root('root-a', 3, '研究员', 'completed', 12);
  state.rootsById['root-b'] = root('root-b', 1, '审查员', 'running', 11);
  state.postOrder.push('post-a');
  state.postsById['post-a'] = {
    schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-a', roomId: 'room-a', rootId: 'root-a', generation: 3,
    authorActorRef: '研究员', kind: 'finding', visibility: 'room', content: '经过明确提交的研究发现',
    idempotencyKey: 'post-a', publicationSource: { kind: 'room_commit', ref: 'commit-a' }, createdAtMs: 1,
  };
  state.sessionsById['session-private-a'] = { sessionId: 'session-private-a', rootId: 'root-a', generation: 3, state: 'completed', updatedAtMs: 10 };
  return state;
}

function root(rootId: string, generation: number, owner: string, state: RootProjection['state'], updatedAtMs: number): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v2', rootId, roomId: 'room-a', generation, state, owner,
    requirementAnchorRef: `requirement:${rootId}`, createdByActorRef: 'user:1', terminalReceiptId: null,
    activeProfileRef: null, budgetPolicyRef: 'budget:default', createdAtMs: 1, isFinal: false, updatedAtMs,
  };
}

function receipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'receipt-a', rootId: 'root-a', commandId: 'command-a',
    receiptKind: 'accepted', status: 'applied', generation: 3, details: {}, createdAtMs: 4, ...overrides,
  };
}
