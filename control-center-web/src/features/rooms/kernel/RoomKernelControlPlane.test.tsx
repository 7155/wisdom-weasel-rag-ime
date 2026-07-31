import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { createRoomKernelProjection, type RoomKernelProjection, type RootProjection } from '@/contracts/room-kernel-reducer';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import { createFixtureRoomKernelCommandTransport } from './room-kernel-command-transport';

describe('RoomKernelControlPlane', () => {
  afterEach(cleanup);

  it('renders generated projections and keeps Session transcript private', () => {
    renderPlane(projection());
    expect(screen.getByRole('region', { name: 'root-a 公开交付' })).toHaveTextContent('经过明确提交的研究发现');
    expect(screen.getByRole('region', { name: 'root-a 伙伴运行状态' })).toHaveTextContent('session-private-a');
    expect(screen.queryByText('Session 私有正文')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'root-a 运行回执' })).toHaveTextContent('当前连接没有停止权限');
  });

  it('shows each durable Task owner, state, and accepted handoff path', () => {
    renderPlane(projection());
    const ownership = screen.getByRole('region', { name: 'root-a 任务归属' });
    expect(ownership).toHaveTextContent('核对索引证据');
    expect(ownership).toHaveTextContent('当前负责人审查员');
    expect(ownership).toHaveTextContent('研究员审查员第 1 版');
    expect(within(ownership).getByTitle('task-a')).toHaveTextContent('task-a');
  });

  it('does not expose a production Stop write without a command transport', () => {
    renderPlane(projection());
    const buttons = screen.getAllByRole('button', { name: '停止此任务' });
    expect(buttons[0]).toBeDisabled();
    expect(buttons[0]).toHaveAttribute('title', '当前连接没有停止任务的权限');
  });

  it('sends canonical room root generation command through fixture transport and displays receipt', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'cancel-root-a', commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    const transport = createFixtureRoomKernelCommandTransport(handler);
    renderPlane(projection(), transport);

    fireEvent.click(screen.getAllByRole('button', { name: '停止此任务' })[0]!);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      schemaVersion: 'wisdom-weasel.room-kernel-command.v1', roomId: 'room-a', rootId: 'root-a',
      targetKind: 'root', targetId: 'root-a', generation: 3, commandKind: 'cancel_root',
    });
    expect(await screen.findByText('停止请求已接受')).toBeInTheDocument();
  });

  it('targets the keyboard-selected concurrent Root only', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: `cancel-${command.rootId}`, commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    renderPlane(projection(), createFixtureRoomKernelCommandTransport(handler));
    const buttons = screen.getAllByRole('button', { name: '停止此任务' });
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
      details: {
        qualityGateVerdict: 'ready_to_deliver',
        deliveryGateObservation: {
          gateObservationRef: 'gate-a', gateStatus: 'warn_blocked', mode: 'observe_warn',
          enforcementApplied: false, reasons: ['unresolved_unknown'],
        },
      },
    });
    renderPlane(state);
    expect(screen.getByText('任务已结束')).toBeInTheDocument();
    expect(screen.getByText('已结束，仍有检查提醒')).toBeInTheDocument();
    expect(screen.getByText('全部验收项已有有效证据')).toBeInTheDocument();
    expect(screen.getByText('发现阻塞或未知项')).toBeInTheDocument();
    expect(screen.queryByText('已完成并通过检查')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '停止此任务' })).toHaveLength(1);
  });

  it('exposes Room panic only for an admin gate and requires explicit inline confirmation', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'panic-room-a', commandId: command.commandId, rootId: null,
      generation: 0, receiptKind: 'panic', status: 'applied',
    }));
    renderPlane(projection(), createFixtureRoomKernelCommandTransport(handler), true);
    fireEvent.click(screen.getByRole('button', { name: '停止全部任务' }));
    expect(screen.getByRole('alert')).toHaveTextContent('正在运行的伙伴、工具和后续任务');
    expect(handler).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '继续运行' }));
    expect(screen.queryByRole('button', { name: '确认停止全部' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '停止全部任务' }));
    fireEvent.click(screen.getByRole('button', { name: '确认停止全部' }));
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      roomId: 'room-a', rootId: null, commandKind: 'panic', targetKind: null, generation: 0,
    });
    expect(await screen.findByText('停止请求已接受')).toBeInTheDocument();
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
    participantLabels={{ researcher: '研究员', reviewer: '审查员' }}
    commandTransport={commandTransport}
    panicEnabled={panicEnabled}
  />);
}

function projection(): RoomKernelProjection {
  const state = createRoomKernelProjection('room-a');
  state.lastSequence = 12;
  state.rootsById['root-a'] = root('root-a', 3, '研究员', 'completed', 12);
  state.rootsById['root-b'] = root('root-b', 1, '审查员', 'running', 11);
  state.tasksById['task-a'] = {
    schemaVersion: 'wisdom-weasel.room-task.v3', taskId: 'task-a', rootId: 'root-a', parentTaskId: null,
    taskKind: 'work', currentOwnerParticipantId: 'reviewer', ownershipRevision: 1,
    ownershipReceiptId: 'receipt:ownership:1', objective: '核对索引证据', expectedOutput: '证据回执',
    requirementItemIds: ['requirement:1'], acceptanceCriterionIds: ['criterion:1'],
    contextEvidenceRefs: [], invitationId: null, reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [], reviewState: 'not_required', revision: 1, state: 'active',
  };
  state.receiptsById['receipt:ownership:1'] = receipt({
    receiptId: 'receipt:ownership:1',
    details: {
      operation: 'task_owner_transfer', taskId: 'task-a',
      fromParticipantId: 'researcher', toParticipantId: 'reviewer', ownershipRevision: 1,
    },
    createdAtMs: 8,
  });
  state.postOrder.push('post-a');
  state.postsById['post-a'] = {
    schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-a', roomId: 'room-a', rootId: 'root-a', generation: 3,
    authorActorRef: '研究员', kind: 'finding', visibility: 'room', content: '经过明确提交的研究发现',
    idempotencyKey: 'post-a', publicationSource: { kind: 'room_commit', ref: 'commit-a' }, createdAtMs: 1,
  };
  state.sessionsById['session-private-a'] = { sessionId: 'session-private-a', rootId: 'root-a', generation: 3, state: 'completed', updatedAtMs: 10 };
  return state;
}

function root(rootId: string, generation: number, facilitatorParticipantId: string, state: RootProjection['state'], updatedAtMs: number): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3', rootId, roomId: 'room-a', generation, state,
    facilitatorParticipantId, reporterParticipantId: null, reporterSelectionReceiptId: null,
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
