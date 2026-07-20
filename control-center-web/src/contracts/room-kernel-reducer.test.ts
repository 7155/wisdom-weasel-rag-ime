import { describe, expect, it } from 'vitest';
import type { RoomDispatchEnvelopeV2 } from './generated/room-dispatch-envelope.v2';
import type { RoomEventEnvelopeV2 } from './generated/room-event-envelope.v2';
import type { RoomKernelReceiptV1 } from './generated/room-kernel-receipt.v1';
import type { RoomPostV2 } from './generated/room-post.v2';
import type { RoomRootExecutionV2 } from './generated/room-root-execution.v2';
import type { RoomTaskV2 } from './generated/room-task.v2';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  reduceRoomKernelEvent,
  type RoomKernelSnapshot,
} from './room-kernel-reducer';

describe('generated-contract Room Kernel projection', () => {
  it('publishes only canonical RoomPost and discards private legacy text', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() }));
    state = apply(state, envelope(2, 'binding', 'session-a', 'session_projection', {
      session: { sessionId: 'session-a', rootId: 'root-a', generation: 3, state: 'completed', updatedAtMs: 2 },
    }));
    state = apply(state, envelope(3, 'binding', 'session-a', 'legacy_message_completed', {
      text: 'private answer', reasoning: 'private reasoning', audio: 'private bytes',
    }));

    expect(state.postOrder).toEqual([]);
    expect(JSON.stringify(state)).not.toContain('private answer');
    expect(JSON.stringify(state)).not.toContain('private reasoning');
    expect(JSON.stringify(state)).not.toContain('private bytes');

    state = apply(state, envelope(4, 'post', 'post-a', 'published', { post: post() }));
    expect(state.postsById['post-a']?.content).toBe('explicit finding');
  });

  it('projects Root Task Dispatch without inventing their state in components', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() }));
    state = apply(state, envelope(2, 'task', 'task-a', 'upserted', { task: task() }));
    state = apply(state, envelope(3, 'dispatch', 'dispatch-a', 'upserted', { dispatch: dispatch() }));

    expect(state.rootsById['root-a']?.state).toBe('running');
    expect(state.tasksById['task-a']?.state).toBe('active');
    expect(state.dispatchesById['dispatch-a']?.state).toBe('running');
  });

  it('ignores an out-of-order Task revision even when its event sequence is newer', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() }));
    state = apply(state, envelope(2, 'task', 'task-a', 'upserted', { task: task({ revision: 4, state: 'review' }) }));
    state = apply(state, envelope(3, 'task', 'task-a', 'state_changed', { task: task({ revision: 3, state: 'completed' }) }));
    expect(state.tasksById['task-a']).toMatchObject({ revision: 4, state: 'review' });
    expect(state.diagnostics.at(-1)).toMatchObject({ kind: 'stale-generation', summary: 'Stale Task revision ignored' });
  });

  it('requires a matching canonical terminal receipt and Root pointer before final', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', {
      root: root({ state: 'completed', terminalReceiptId: null }),
    }));
    state = apply(state, envelope(2, 'root', 'root-a', 'kernel_receipt', {
      receipt: receipt({ receiptId: 'terminal-a', receiptKind: 'terminal' }),
    }));
    expect(state.rootsById['root-a']?.isFinal).toBe(false);

    state = apply(state, envelope(3, 'root', 'root-a', 'state_changed', {
      root: root({ state: 'completed', terminalReceiptId: 'terminal-a' }),
    }));
    expect(state.rootsById['root-a']?.isFinal).toBe(true);
  });

  it('rejects stale generation for receipt dispatch session and post', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() }));
    state = apply(state, envelope(2, 'root', 'root-a', 'kernel_receipt', {
      receipt: receipt({ generation: 2, receiptId: 'stale-terminal', receiptKind: 'terminal' }),
    }));
    state = apply(state, envelope(3, 'dispatch', 'dispatch-stale', 'upserted', {
      dispatch: dispatch({ dispatchId: 'dispatch-stale', generation: 2 }),
    }));
    state = apply(state, envelope(4, 'binding', 'session-a', 'session_projection', {
      session: { sessionId: 'session-a', rootId: 'root-a', generation: 2, state: 'running', updatedAtMs: 4 },
    }));
    state = apply(state, envelope(5, 'post', 'post-stale', 'published', {
      post: post({ postId: 'post-stale', generation: 2 }),
    }));

    expect(state.receiptsById['stale-terminal']).toBeUndefined();
    expect(state.dispatchesById['dispatch-stale']).toBeUndefined();
    expect(state.sessionsById['session-a']).toBeUndefined();
    expect(state.postsById['post-stale']).toBeUndefined();
    expect(state.diagnostics.filter((item) => item.kind === 'stale-generation')).toHaveLength(3);
    expect(state.diagnostics.at(-1)?.kind).toBe('invalid-event');
  });

  it('detects gap, ignores duplicate and freezes until snapshot', () => {
    let state = createRoomKernelProjection('room-a');
    state = apply(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() }));
    expect(reduceRoomKernelEvent(state, envelope(1, 'root', 'root-a', 'upserted', { root: root() })).disposition)
      .toBe('ignored-duplicate');
    const gap = reduceRoomKernelEvent(state, envelope(3, 'task', 'task-a', 'upserted', { task: task() }));
    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.gap).toEqual({ expectedSequence: 2, receivedSequence: 3 });
    expect(reduceRoomKernelEvent(gap.state, envelope(4, 'task', 'task-a', 'upserted', { task: task() })).disposition)
      .toBe('ignored-snapshot-pending');
  });

  it('keeps concurrent Roots isolated and replaces the projection with a snapshot', () => {
    const rootB = root({ rootId: 'root-b', generation: 8, owner: 'reviewer' });
    const snapshot: RoomKernelSnapshot = {
      roomId: 'room-a', lastSequence: 20, snapshotHash: `sha256:${'a'.repeat(64)}`,
      roots: [root(), rootB], tasks: [task()], dispatches: [dispatch()], posts: [post()],
      sessions: [{
        sessionId: 'session-b', rootId: 'root-b', generation: 8, state: 'running', updatedAtMs: 9,
        capabilityManifest: {
          manifestId: 'manifest-b', manifestHash: 'b'.repeat(64), status: 'active', rootId: 'root-b',
          taskId: 'task-b', dispatchId: 'dispatch-b', generation: 8, capabilityEpoch: 4,
          promptCompileReceiptId: 'prompt-b', promptPlanHash: 'c'.repeat(64),
          compiledRuntimeProfileRef: { profileId: 'profile-b', revision: '1', contentHash: 'sha256:profile-b' },
        },
      }],
      receipts: [],
    };
    const state = applyRoomKernelSnapshot(createRoomKernelProjection('room-a'), snapshot);
    expect(Object.keys(state.rootsById)).toEqual(['root-a', 'root-b']);
    expect(state.sessionsById['session-b']?.rootId).toBe('root-b');
    expect(state.sessionsById['session-b']?.capabilityManifest?.manifestHash).toBe('b'.repeat(64));
    expect(state.snapshotHash).toBe(snapshot.snapshotHash);
    expect(state.postOrder).toEqual(['post-a']);
  });
});

function apply(state: ReturnType<typeof createRoomKernelProjection>, event: RoomEventEnvelopeV2) {
  const result = reduceRoomKernelEvent(state, event);
  expect(result.disposition).toBe('applied');
  return result.state;
}

function envelope(
  sequence: number,
  entityKind: RoomEventEnvelopeV2['entityKind'],
  entityId: string,
  eventKind: string,
  payload: Record<string, unknown>,
): RoomEventEnvelopeV2 {
  return { schemaVersion: 'wisdom-weasel.room-event-envelope.v2', entityKind, entityId, eventKind, sequence, occurredAtMs: sequence, payload };
}

function root(overrides: Partial<RoomRootExecutionV2> = {}): RoomRootExecutionV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v2', rootId: 'root-a', roomId: 'room-a', generation: 3,
    state: 'running', owner: 'researcher', requirementAnchorRef: 'requirement:1', createdByActorRef: 'user:1',
    terminalReceiptId: null, activeProfileRef: null, budgetPolicyRef: 'budget:default', createdAtMs: 1, ...overrides,
  };
}

function task(overrides: Partial<RoomTaskV2> = {}): RoomTaskV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-task.v2', taskId: 'task-a', rootId: 'root-a', parentTaskId: null,
    ownerParticipantId: 'researcher', assigneeParticipantId: 'researcher', objective: 'investigate', expectedOutput: 'evidence',
    requirementItemIds: ['requirement:1'], acceptanceCriterionIds: ['criterion:1'], revision: 1, state: 'active', ...overrides,
  };
}

function dispatch(overrides: Partial<RoomDispatchEnvelopeV2> = {}): RoomDispatchEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2', dispatchId: 'dispatch-a', rootId: 'root-a', taskId: 'task-a',
    parentDispatchId: null, generation: 3, hopCount: 1, depth: 1, budgetCost: 1, targetSessionId: 'session-a',
    targetParticipantId: 'researcher', triggerId: 'trigger:1', intentKind: 'execute', idempotencyKey: 'dispatch:1', attempt: 1,
    capabilityEpoch: 1, runtimeProfileRevision: 'profile:1', state: 'running', ...overrides,
  };
}

function post(overrides: Partial<RoomPostV2> = {}): RoomPostV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-a', roomId: 'room-a', rootId: 'root-a', generation: 3,
    authorActorRef: 'participant:researcher', kind: 'finding', visibility: 'room', content: 'explicit finding',
    idempotencyKey: 'post:1', publicationSource: { kind: 'room_commit', ref: 'commit:1' }, createdAtMs: 4, ...overrides,
  };
}

function receipt(overrides: Partial<RoomKernelReceiptV1> = {}): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'receipt-a', rootId: 'root-a', commandId: 'command-a',
    receiptKind: 'accepted', status: 'applied', generation: 3, details: {}, createdAtMs: 4, ...overrides,
  };
}
