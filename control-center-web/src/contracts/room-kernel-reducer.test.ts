import { describe, expect, it } from 'vitest';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  requestRootStop,
  type RoomKernelEventFixture,
  type RoomKernelSnapshotFixture,
} from './room-kernel-reducer';

describe('Room Kernel projection boundaries', () => {
  it('publishes only an explicit RoomPost and never a private Session completion', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, event(1, 'root_state_changed', {
      rootId: 'root-a', generation: 1, state: 'running', ownerParticipantId: 'p1',
    }));
    state = apply(state, event(2, 'session_state_changed', {
      sessionId: 'session-private', rootId: 'root-a', generation: 1, state: 'completed',
    }));
    state = apply(state, event(3, 'legacy_message_completed', {
      sessionId: 'session-private', text: '不应公开的回答', reasoningSummary: '秘密摘要', audio: 'bytes',
    }));

    expect(state.postOrder).toEqual([]);
    expect(state.sessionsById['session-private']?.state).toBe('completed');
    expect(JSON.stringify(state)).not.toContain('不应公开的回答');
    expect(JSON.stringify(state)).not.toContain('秘密摘要');
    expect(JSON.stringify(state)).not.toContain('bytes');

    state = apply(state, event(4, 'post_published', {
      post: post('post-public', 'root-a', '经过明确提交的发现'),
    }));
    expect(state.postOrder).toEqual(['post-public']);
    expect(state.postsById['post-public']?.content).toBe('经过明确提交的发现');
  });

  it('requires a matching terminal receipt before a Root is final', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, event(1, 'root_state_changed', {
      rootId: 'root-a', generation: 2, state: 'completed', ownerParticipantId: 'p1',
    }));
    state = apply(state, event(2, 'legacy_turn_completed', { turnId: 'turn-a' }));
    expect(state.rootsById['root-a']).toMatchObject({ state: 'completed', isFinal: false });

    state = apply(state, event(3, 'root_terminal_receipt', {
      receipt: {
        receiptId: 'receipt-a', rootId: 'root-a', generation: 2,
        terminalState: 'completed', quiescent: true, acceptancePassed: true,
      },
    }));
    expect(state.rootsById['root-a']).toMatchObject({ state: 'completed', isFinal: true });
    expect(state.terminalReceiptsByRootId['root-a']?.receiptId).toBe('receipt-a');
  });

  it('rejects a stale terminal receipt from an older generation', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, event(1, 'root_state_changed', {
      rootId: 'root-a', generation: 3, state: 'running', ownerParticipantId: 'p1',
    }));
    state = apply(state, event(2, 'root_terminal_receipt', {
      receipt: {
        receiptId: 'receipt-stale', rootId: 'root-a', generation: 2,
        terminalState: 'completed', quiescent: true, acceptancePassed: true,
      },
    }));

    expect(state.rootsById['root-a']?.isFinal).toBe(false);
    expect(state.terminalReceiptsByRootId['root-a']).toBeUndefined();
    expect(state.diagnostics.at(-1)?.kind).toBe('stale-generation');
  });

  it('isolates concurrent Roots and targets Stop by root and generation', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, event(1, 'root_state_changed', {
      rootId: 'root-a', generation: 4, state: 'running', ownerParticipantId: 'p1',
    }));
    state = apply(state, event(2, 'root_state_changed', {
      rootId: 'root-b', generation: 7, state: 'running', ownerParticipantId: 'p2',
    }));
    state = requestRootStop(state, {
      rootId: 'root-b', generation: 7, idempotencyKey: 'stop-root-b-7', requestedAtMs: 12,
    });

    expect(state.runtimeByRootId['root-a']?.stopRequest).toBeNull();
    expect(state.runtimeByRootId['root-b']?.stopRequest).toMatchObject({
      generation: 7, idempotencyKey: 'stop-root-b-7', state: 'requested',
    });
    expect(() => requestRootStop(state, {
      rootId: 'root-b', generation: 6, idempotencyKey: 'stale-stop', requestedAtMs: 13,
    })).toThrow(/generation/);
  });

  it('requires a snapshot on a gap and ignores duplicate or pending events', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, event(1, 'root_state_changed', {
      rootId: 'root-a', generation: 1, state: 'running', ownerParticipantId: 'p1',
    }));
    const duplicate = reduceRoomKernelEvent(state, event(1, 'legacy_turn_completed', {}));
    expect(duplicate.disposition).toBe('ignored-duplicate');

    const gap = reduceRoomKernelEvent(state, event(3, 'root_state_changed', {
      rootId: 'root-b', generation: 1, state: 'running', ownerParticipantId: 'p2',
    }));
    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.gap).toEqual({ expectedSequence: 2, receivedSequence: 3 });
    expect(reduceRoomKernelEvent(gap.state, event(4, 'legacy_turn_completed', {})).disposition)
      .toBe('ignored-snapshot-pending');
  });

  it('restores an authoritative snapshot without turning completed Sessions into Posts', () => {
    const snapshot: RoomKernelSnapshotFixture = {
      schemaVersion: 'room-kernel-ui-fixture.v1',
      roomId: 'room-a',
      lastSequence: 9,
      snapshotHash: `sha256:${'a'.repeat(64)}`,
      roots: [{ rootId: 'root-a', generation: 2, state: 'running', ownerParticipantId: 'p1' }],
      sessions: [{ sessionId: 'session-a', rootId: 'root-a', generation: 2, state: 'completed' }],
      posts: [post('post-a', 'root-a', '唯一公开材料')],
      terminalReceipts: [],
    };
    const state = applyRoomKernelSnapshot(createRoomKernelProjection('room-a'), snapshot);

    expect(state.lastSequence).toBe(9);
    expect(state.snapshotHash).toBe(snapshot.snapshotHash);
    expect(state.postOrder).toEqual(['post-a']);
    expect(state.sessionsById['session-a']?.state).toBe('completed');
    expect(state.rootsById['root-a']?.isFinal).toBe(false);
  });
});

function apply(state: ReturnType<typeof createRoomKernelProjection>, next: RoomKernelEventFixture) {
  const reduced = reduceRoomKernelEvent(state, next);
  expect(reduced.disposition).toBe('applied');
  return reduced.state;
}

function event(
  sequence: number,
  eventType: RoomKernelEventFixture['eventType'],
  payload: Record<string, unknown>,
): RoomKernelEventFixture {
  return {
    schemaVersion: 'room-kernel-ui-fixture.v1',
    eventId: `event-${sequence}`,
    roomId: 'room-a',
    sequence,
    eventType,
    createdAtMs: sequence,
    payload,
  };
}

function post(postId: string, rootId: string, content: string) {
  return {
    postId, roomId: 'room-a', rootId, sequence: 1, authorParticipantId: 'p1',
    kind: 'finding' as const, visibility: 'room' as const, content, createdAtMs: 1,
  };
}
