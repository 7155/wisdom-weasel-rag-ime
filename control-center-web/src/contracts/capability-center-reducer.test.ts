import { describe, expect, it } from 'vitest';
import {
  applyCapabilityCenterSnapshot,
  createCapabilityCenterProjection,
  reduceCapabilityCenterEvent,
  type CapabilityCenterEventFixture,
} from './capability-center-reducer';

describe('capability center reducer', () => {
  it('copies authoritative six-state receipts without deriving authorization', () => {
    const reduced = reduceCapabilityCenterEvent(createCapabilityCenterProjection('room-a'), event(1, 3));

    expect(reduced.disposition).toBe('applied');
    expect(reduced.state.capabilitiesBySessionId['session-a']?.['rag.read']?.states).toEqual({
      available: true, authorized: true, disclosed: true,
      loaded: false, invoked: false, revoked: false,
    });
    expect(reduced.state.capabilitiesBySessionId['session-a']?.['rag.read']?.narrowedBy[0]?.layer).toBe('collaboration-profile');
  });

  it('ignores duplicate and old-generation receipts', () => {
    const initial = reduceCapabilityCenterEvent(createCapabilityCenterProjection('room-a'), event(1, 4)).state;
    const duplicate = reduceCapabilityCenterEvent(initial, event(1, 4));
    const stale = reduceCapabilityCenterEvent(initial, event(2, 3));

    expect(duplicate.disposition).toBe('ignored-duplicate');
    expect(stale.disposition).toBe('ignored-stale-generation');
    expect(stale.state.lastSequence).toBe(2);
    expect(stale.state.capabilitiesBySessionId['session-a']?.['rag.read']?.generation).toBe(4);
  });

  it('requires a snapshot after a sequence gap and recovers from a canonical snapshot', () => {
    const initial = reduceCapabilityCenterEvent(createCapabilityCenterProjection('room-a'), event(5, 2)).state;
    const gap = reduceCapabilityCenterEvent(initial, event(7, 2));
    const blocked = reduceCapabilityCenterEvent(gap.state, event(8, 2));

    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.gap).toEqual({ expectedSequence: 6, receivedSequence: 7 });
    expect(blocked.disposition).toBe('ignored-snapshot-pending');

    const restored = applyCapabilityCenterSnapshot(gap.state, {
      schemaVersion: 'capability-center-ui-fixture.v1', roomId: 'room-a', lastSequence: 8,
      snapshotHash: `sha256:${'c'.repeat(64)}`,
      bindings: [binding('session-a', 2), binding('session-b', 1)],
      capabilities: [capability(2), { ...capability(1), sessionId: 'session-b', capabilityId: 'review.read' }],
    });
    expect(restored.needsSnapshot).toBe(false);
    expect(Object.keys(restored.bindingsBySessionId)).toEqual(['session-a', 'session-b']);
  });

  it('keeps concurrent session bindings isolated', () => {
    const first = reduceCapabilityCenterEvent(createCapabilityCenterProjection('room-a'), event(1, 1)).state;
    const secondEvent = event(2, 6);
    secondEvent.payload = { binding: binding('session-b', 6), capability: { ...capability(6), sessionId: 'session-b' } };
    const second = reduceCapabilityCenterEvent(first, secondEvent).state;

    expect(second.bindingsBySessionId['session-a']?.generation).toBe(1);
    expect(second.bindingsBySessionId['session-b']?.generation).toBe(6);
  });
});

function event(sequence: number, generation: number): CapabilityCenterEventFixture {
  return {
    schemaVersion: 'capability-center-ui-fixture.v1', eventId: `event-${sequence}`,
    roomId: 'room-a', sequence, eventType: 'capability_projection_received', createdAtMs: sequence,
    payload: { binding: binding('session-a', generation), capability: capability(generation) },
  };
}

function binding(sessionId: string, generation: number) {
  return {
    bindingId: `binding-${sessionId}`, sessionId, participantId: `participant-${sessionId}`, generation,
    roomBindingRef: { schemaVersion: 'wisdom-weasel.room-binding.v2', bindingId: 'room-binding-a' },
    personaRef: ref('persona', 'zhiyou-v1'), collaborationRoleRef: ref('collaboration-role', 'researcher'),
    agentTemplateRef: ref('agent-template', 'researcher'), collaborationProfileRef: ref('collaboration-profile', 'evidence-review'),
    compiledRuntimeProfileRef: { profileId: 'compiled:binding-a', revision: 'compiler-v1', contentHash: `sha256:${'1'.repeat(64)}` },
    capabilityRevision: 'capability-r4', capabilityEpoch: 4,
  } as const;
}

function capability(generation: number) {
  return {
    capabilityId: 'rag.read', sessionId: 'session-a', generation, displayName: '知识检索',
    summary: '读取经过授权的知识资料，不包含写入或管理权限。',
    states: { available: true, authorized: true, disclosed: true, loaded: false, invoked: false, revoked: false },
    manifestRef: revisionRef('capability-manifest', 'manifest-r8', '2'),
    profileRef: revisionRef('collaboration-profile', 'profile-r4', '1'),
    skillRefs: [revisionRef('skill', 'knowledge-research', '3')],
    toolRefs: [revisionRef('tool', 'knowledge.search', '5')],
    contextRef: revisionRef('context', 'context-r12', '12'),
    receipts: [{ receiptId: 'capability-receipt-44', kind: 'authorized', revision: 'r44', contentHash: `sha256:${'8'.repeat(64)}` }],
    narrowedBy: [{ layer: 'collaboration-profile', decision: 'allowed', reason: '角色书仅保留只读检索', receiptId: 'compile-receipt-4' }],
  } as const;
}

function ref(kind: string, id: string) {
  return { kind, id, version: '1', contentHash: `sha256:${'2'.repeat(64)}` };
}

function revisionRef(kind: string, id: string, revision: string) {
  return { kind, id, revision, contentHash: `sha256:${'3'.repeat(64)}`, receiptId: `${id}-receipt` };
}
