import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RootProjection } from '@/contracts/room-kernel-reducer';
import { createRoomProjection } from '@/contracts/room-reducer';
import { RoomTurn } from './RoomTurn';
import { RoomStartActionGate, roomRootRequiresStartAction } from './RoomStartActionGate';

describe('RoomStartActionGate', () => {
  afterEach(cleanup);

  it('only asks for a start confirmation after a real clarification gate', () => {
    const waitingRoot = root('waiting');
    expect(roomRootRequiresStartAction(waitingRoot, [
      receipt(1, { operation: 'room_define', requiresStartAction: false }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'execution_ready',
        clarificationOccurred: false,
      }),
    ])).toBe(false);

    expect(roomRootRequiresStartAction(waitingRoot, [
      receipt(1, { operation: 'room_define', requiresStartAction: true }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'awaiting_start',
        clarificationOccurred: true,
      }),
    ])).toBe(true);

    expect(roomRootRequiresStartAction(waitingRoot, [
      receipt(1, { operation: 'room_define', requiresStartAction: true }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'awaiting_start',
        clarificationOccurred: true,
      }),
      receipt(3, {
        purpose: 'intake_phase',
        phase: 'executing',
        clarificationOccurred: true,
      }),
    ])).toBe(false);
    expect(roomRootRequiresStartAction(waitingRoot, [
      receipt(1, { operation: 'room_define', requiresStartAction: true }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'awaiting_start',
        clarificationOccurred: true,
      }),
      receipt(3, { operation: 'room_define', requiresStartAction: false }),
    ])).toBe(false);
    expect(roomRootRequiresStartAction(root('running'), [
      receipt(1, { operation: 'room_define', requiresStartAction: true }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'awaiting_start',
        clarificationOccurred: true,
      }),
    ])).toBe(false);
  });

  it('publishes one explicit human action without exposing protocol language', () => {
    const onStart = vi.fn();
    const { rerender } = render(<RoomStartActionGate onStart={onStart} starting={false} />);

    expect(screen.getByRole('group', { name: '确认开始行动' })).toHaveTextContent('现在开始行动吗？');
    expect(screen.queryByText('目标、交付和边界已经对齐')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '开始行动' }));
    expect(onStart).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toMatch(/Kernel|Root|Dispatch|Receipt|schemaVersion|root-|dispatch-/);

    rerender(<RoomStartActionGate onStart={onStart} starting />);
    expect(screen.getByRole('button', { name: '正在开始' })).toBeDisabled();
  });

  it('renders the action in the real turn only for the clarified waiting state', () => {
    const projection = createRoomProjection('room-a');
    projection.turnsById['turn-a'] = {
      id: 'turn-a',
      rootId: 'root-a',
      status: 'running',
      messageIds: ['alignment-a'],
      activityIds: [],
      participantIds: [],
      createdAtMs: 1,
      updatedAtMs: 2,
    };
    projection.messagesById['alignment-a'] = {
      id: 'alignment-a',
      roomId: 'room-a',
      turnId: 'turn-a',
      participantId: 'participant-a',
      sourceSessionId: 'session-a',
      role: 'assistant',
      status: 'completed',
      text: '已经对齐：目标是“完成实现”，交付边界是“实现与验证记录”。',
      projectionKind: 'post',
      postKind: 'alignment',
      rootId: 'root-a',
      dispatchId: 'dispatch-align',
      createdAtMs: 2,
    };
    projection.messageOrder.push('alignment-a');
    const onStart = vi.fn();
    const clarifiedReceipts = [
      receipt(1, { operation: 'room_define', requiresStartAction: true }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'awaiting_start',
        clarificationOccurred: true,
      }),
    ];
    const turn = (receipts: RoomKernelReceiptV1[]) => <RoomTurn
      kernelReceiptsById={Object.fromEntries(receipts.map((item) => [item.receiptId, item]))}
      kernelRootsById={{ 'root-a': root('waiting') }}
      onStartExecution={onStart}
      personas={[]}
      projection={projection}
      turnId="turn-a"
    />;
    const view = render(turn(clarifiedReceipts));

    fireEvent.click(screen.getByRole('button', { name: '开始行动' }));
    expect(onStart).toHaveBeenCalledWith('root-a');
    view.rerender(turn([
      receipt(1, { operation: 'room_define', requiresStartAction: false }),
      receipt(2, {
        purpose: 'intake_phase',
        phase: 'execution_ready',
        clarificationOccurred: false,
      }),
    ]));
    expect(screen.queryByRole('button', { name: '开始行动' })).not.toBeInTheDocument();
  });
});

function root(state: RootProjection['state']): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root-a',
    roomId: 'room-a',
    generation: 2,
    state,
    facilitatorParticipantId: 'participant-a',
    reporterParticipantId: null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement-a',
    createdByActorRef: 'user-a',
    terminalReceiptId: null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget-a',
    independentReviewRequired: false,
    createdAtMs: 1,
    isFinal: false,
    updatedAtMs: 2,
  };
}

function receipt(createdAtMs: number, details: Record<string, unknown>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1',
    receiptId: `receipt-${createdAtMs}`,
    rootId: 'root-a',
    commandId: null,
    receiptKind: 'accepted',
    status: 'applied',
    generation: 2,
    details,
    createdAtMs,
  };
}
