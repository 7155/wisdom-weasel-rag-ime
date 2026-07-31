import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { createRoomKernelProjection, type RoomKernelProjection, type RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import {
  createFixtureRoomKernelCommandTransport,
  type RoomKernelCommandTransport,
} from './room-kernel-command-transport';

describe('RoomKernelControlPlane', () => {
  afterEach(cleanup);

  it('renders public results while keeping private participant details behind an optional disclosure', () => {
    renderPlane(projection());
    expect(screen.getAllByRole('region', { name: '公开结果与回复' })[0]).toHaveTextContent('经过明确提交的研究发现');
    const sessions = screen.getAllByRole('region', { name: '伙伴运行状态' })[0]!;
    expect(sessions).not.toHaveTextContent('Session 私有正文');
    expect(screen.getAllByRole('region', { name: '运行确认' })[0]).toHaveTextContent('当前连接没有停止权限');
  });

  it('presents optional handoff details without exposing protocol identifiers', () => {
    renderPlane(projection());
    const summary = screen.getByText('查看分工与交接详情');
    const ownership = summary.closest('details');
    expect(ownership).not.toBeNull();
    fireEvent.click(summary);
    expect(ownership).toHaveTextContent('核对索引证据');
    expect(ownership).toHaveTextContent('当前伙伴审查员');
    expect(ownership).toHaveTextContent('研究员审查员第 1 版');
    expect(ownership).toHaveTextContent('分工关系直接分配');
    expect(ownership).not.toHaveTextContent('task-a');
    expect(ownership).not.toHaveTextContent('receipt:ownership:1');
  });

  it('renders every participant as an equal work lane with its public reasoning or tool progress', () => {
    const progress: RoomParticipantPublicProgressProjection[] = [
      {
        rootId: 'root-a',
        dispatchId: 'dispatch-review',
        participantId: 'reviewer',
        sourceSessionId: 'session-private-a',
        kind: 'reasoning',
        status: 'running',
        summary: '正在核对恢复后的任务边界',
        updatedAtMs: 12,
      },
      {
        rootId: 'root-a',
        dispatchId: 'dispatch-research',
        participantId: 'researcher',
        sourceSessionId: 'session-research',
        kind: 'tool',
        status: 'running',
        summary: 'read',
        data: { toolName: 'read' },
        updatedAtMs: 13,
      },
    ];
    renderPlane(projection(), undefined, false, progress);

    const phase = screen.getAllByRole('region', { name: '伙伴并行进度' })[0]!;
    const lanes = phase.querySelectorAll('.room-kernel-participant-lane');
    expect(lanes).toHaveLength(2);
    expect([...lanes].every((lane) => lane.className === 'room-kernel-participant-lane')).toBe(true);
    expect(phase).toHaveTextContent('研究员同时帮大家对齐进度 · 完成自己的部分');
    expect(phase).toHaveTextContent('审查员完成自己的部分');
    expect(phase).toHaveTextContent('正在核对恢复后的任务边界');
    expect(phase).toHaveTextContent('读取文件正在处理');
    expect(phase).not.toHaveTextContent(/\bread\b/);
    expect(phase).not.toHaveTextContent('Session 私有正文');
  });

  it('reveals shared final check only after every owned slice settles and keeps the final Room reply after it', () => {
    const running = projection();
    const first = renderPlane(running);
    expect(screen.queryByRole('region', { name: '一起检查' })).not.toBeInTheDocument();
    first.unmount();

    const settled = projection();
    settled.tasksById['task-a'] = { ...settled.tasksById['task-a']!, state: 'completed' };
    settled.rootsById['root-a'] = {
      ...settled.rootsById['root-a']!,
      state: 'completed',
      isFinal: true,
      terminalReceiptId: 'terminal-a',
    };
    settled.terminalReceiptByRootId['root-a'] = receipt({
      receiptId: 'terminal-a',
      commandId: null,
      receiptKind: 'terminal',
      details: { qualityGateVerdict: 'ready_to_deliver' },
    });
    settled.postOrder.push('post-final');
    settled.postsById['post-final'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'post-final',
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      authorActorRef: '研究员',
      kind: 'result',
      visibility: 'room',
      content: '每位伙伴的部分都已核验，这是最终回复。',
      idempotencyKey: 'post-final',
      publicationSource: { kind: 'room_commit', ref: 'commit-final' },
      createdAtMs: 20,
    };
    renderPlane(settled);

    const sharedCheck = screen.getByRole('region', { name: '一起检查' });
    const publicDelivery = screen.getAllByRole('region', { name: '公开结果与回复' })[0]!;
    expect(sharedCheck).toHaveTextContent('每个人的部分都已完成检查');
    expect(publicDelivery.firstElementChild?.nextElementSibling).toHaveAttribute('data-terminal', 'true');
    expect(publicDelivery).toHaveTextContent('每位伙伴的部分都已核验，这是最终回复。');
    expect(sharedCheck.compareDocumentPosition(publicDelivery) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    ['completed', true],
    ['failed', false],
    ['cancelled', false],
    ['cancelled_with_unknowns', false],
  ] as const)('keeps one latest authoritative reply when the task ends as %s', (state, isFinal) => {
    const terminal = projection();
    terminal.rootsById['root-a'] = {
      ...terminal.rootsById['root-a']!,
      state,
      isFinal,
      terminalReceiptId: isFinal ? 'terminal-a' : null,
    };
    terminal.postOrder.push('post-earlier', 'post-latest');
    terminal.postsById['post-earlier'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'post-earlier',
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      authorActorRef: '研究员',
      kind: 'progress',
      visibility: 'room',
      content: '较早的公开进度',
      idempotencyKey: 'post-earlier',
      publicationSource: { kind: 'room_commit', ref: 'commit-earlier' },
      createdAtMs: 10,
    };
    terminal.postsById['post-latest'] = {
      ...terminal.postsById['post-earlier']!,
      postId: 'post-latest',
      kind: 'result',
      content: '本轮最后一份权威公开回复',
      idempotencyKey: 'post-latest',
      publicationSource: { kind: 'room_commit', ref: 'commit-latest' },
      createdAtMs: 20,
    };

    renderPlane(terminal);

    const publicDelivery = screen.getAllByRole('region', { name: '公开结果与回复' })[0]!;
    expect(publicDelivery).toHaveTextContent('本轮最后一份权威公开回复');
    expect(publicDelivery).not.toHaveTextContent('较早的公开进度');
    expect(publicDelivery.querySelectorAll('[data-terminal="true"]')).toHaveLength(1);
  });

  it('keeps the shared-check phase visible while peer review tasks are still running', () => {
    const state = projection();
    state.tasksById['task-a'] = { ...state.tasksById['task-a']!, state: 'completed' };
    state.tasksById['review-a'] = {
      ...state.tasksById['task-a']!,
      taskId: 'review-a',
      taskKind: 'review',
      currentOwnerParticipantId: 'researcher',
      ownershipReceiptId: null,
      objective: '检查伙伴公开结果',
      reviewOfTaskIds: ['task-a'],
      reviewAuthorParticipantIds: ['researcher'],
      reviewState: 'in_review',
      state: 'active',
    };
    state.rootsById['root-a'] = {
      ...state.rootsById['root-a']!,
      state: 'running',
      isFinal: false,
      terminalReceiptId: null,
    };
    renderPlane(state);

    const sharedCheck = screen.getByRole('region', { name: '一起检查' });
    expect(sharedCheck).toHaveTextContent('伙伴正在互相检查');
    expect(sharedCheck).toHaveTextContent('0 / 1 位伙伴已经完成检查');
    expect(sharedCheck).not.toHaveTextContent('最终回复');
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
    expect(screen.getByText('任务已完成')).toBeInTheDocument();
    expect(screen.getAllByText('已结束，仍有检查提醒')).not.toHaveLength(0);
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

  it('shows overall, owned-work, and collaboration execution progress without inspector jargon', () => {
    renderPlane(projection());
    const overview = screen.getByRole('region', { name: '整体任务、分工与协作执行总进度' });
    expect(overview).toHaveTextContent('整体任务');
    expect(overview).toHaveTextContent('分工');
    expect(overview).toHaveTextContent('协作执行');
    expect(overview).not.toHaveTextContent('Dispatch');
  });
});


function renderPlane(
  state: RoomKernelProjection,
  commandTransport?: RoomKernelCommandTransport,
  panicEnabled = false,
  participantProgress: RoomParticipantPublicProgressProjection[] = [],
) {
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
    participantProgress={participantProgress}
  />);
}

function projection(): RoomKernelProjection {
  const state = createRoomKernelProjection('room-a');
  state.lastSequence = 12;
  state.rootsById['root-a'] = root('root-a', 3, 'researcher', 'running', 12);
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
