/**
 * Temporary UI projection fixtures. Lane A owns the canonical wire schemas;
 * this reducer copies authoritative receipts and never computes permission.
 */

export type CapabilityStateName = 'available' | 'authorized' | 'disclosed' | 'loaded' | 'invoked' | 'revoked';

export type CapabilityStates = Readonly<Record<CapabilityStateName, boolean>>;

export type DefinitionReferenceProjection = {
  readonly kind: string;
  readonly id: string;
  readonly version: string;
  readonly contentHash: string;
};

export type RuntimeRevisionReferenceProjection = {
  readonly kind: string;
  readonly id: string;
  readonly revision: string;
  readonly contentHash: string;
  readonly receiptId: string;
};

export type ParticipantBindingProjection = {
  readonly bindingId: string;
  readonly sessionId: string;
  readonly participantId: string;
  readonly generation: number;
  readonly roomBindingRef: { readonly schemaVersion: 'wisdom-weasel.room-binding.v2'; readonly bindingId: string } | null;
  readonly personaRef: DefinitionReferenceProjection;
  readonly collaborationRoleRef: DefinitionReferenceProjection;
  readonly agentTemplateRef: DefinitionReferenceProjection;
  readonly collaborationProfileRef: DefinitionReferenceProjection | null;
  readonly compiledRuntimeProfileRef: { readonly profileId: string; readonly revision: string; readonly contentHash: string };
  readonly capabilityRevision: string;
  readonly capabilityEpoch: number;
};

export type CapabilityProjection = {
  readonly capabilityId: string;
  readonly sessionId: string;
  readonly generation: number;
  readonly displayName: string;
  readonly summary: string;
  readonly states: CapabilityStates;
  readonly manifestRef: RuntimeRevisionReferenceProjection;
  readonly profileRef: RuntimeRevisionReferenceProjection;
  readonly skillRefs: readonly RuntimeRevisionReferenceProjection[];
  readonly toolRefs: readonly RuntimeRevisionReferenceProjection[];
  readonly contextRef: RuntimeRevisionReferenceProjection;
  readonly receipts: readonly {
    receiptId: string;
    kind: CapabilityStateName;
    revision: string;
    contentHash: string;
  }[];
  readonly narrowedBy: readonly {
    layer: 'authorization' | 'agent-template' | 'collaboration-role' | 'collaboration-profile' | 'revocation';
    decision: 'allowed' | 'removed';
    reason: string;
    receiptId: string;
  }[];
};

export type CapabilityCenterProjection = {
  roomId: string;
  lastSequence: number;
  snapshotHash: string;
  needsSnapshot: boolean;
  gap: { expectedSequence: number; receivedSequence: number } | null;
  bindingsBySessionId: Record<string, ParticipantBindingProjection>;
  capabilitiesBySessionId: Record<string, Record<string, CapabilityProjection>>;
};

export type CapabilityCenterEventFixture = {
  schemaVersion: 'capability-center-ui-fixture.v1';
  eventId: string;
  roomId: string;
  sequence: number;
  eventType: 'capability_projection_received';
  createdAtMs: number;
  payload: { binding: ParticipantBindingProjection; capability: CapabilityProjection };
};

export type CapabilityCenterSnapshotFixture = {
  schemaVersion: 'capability-center-ui-fixture.v1';
  roomId: string;
  lastSequence: number;
  snapshotHash: string;
  bindings: readonly ParticipantBindingProjection[];
  capabilities: readonly CapabilityProjection[];
};

export function createCapabilityCenterProjection(roomId: string): CapabilityCenterProjection {
  return {
    roomId, lastSequence: 0, snapshotHash: '', needsSnapshot: false, gap: null,
    bindingsBySessionId: {}, capabilitiesBySessionId: {},
  };
}

export function reduceCapabilityCenterEvent(
  state: CapabilityCenterProjection,
  event: CapabilityCenterEventFixture,
): {
  state: CapabilityCenterProjection;
  disposition: 'applied' | 'ignored-foreign' | 'ignored-duplicate' | 'ignored-stale-generation' | 'ignored-snapshot-pending' | 'snapshot-required';
} {
  if (event.roomId !== state.roomId) return { state, disposition: 'ignored-foreign' };
  if (event.sequence <= state.lastSequence) return { state, disposition: 'ignored-duplicate' };
  if (state.needsSnapshot) return { state, disposition: 'ignored-snapshot-pending' };
  if (state.lastSequence > 0 && event.sequence !== state.lastSequence + 1) {
    return {
      state: { ...state, needsSnapshot: true, gap: { expectedSequence: state.lastSequence + 1, receivedSequence: event.sequence } },
      disposition: 'snapshot-required',
    };
  }
  const { binding, capability } = event.payload;
  validateProjectionPair(binding, capability);
  const currentBinding = state.bindingsBySessionId[binding.sessionId];
  const currentCapability = state.capabilitiesBySessionId[capability.sessionId]?.[capability.capabilityId];
  if (
    (currentBinding && binding.generation < currentBinding.generation)
    || (currentCapability && capability.generation < currentCapability.generation)
  ) {
    return { state: { ...state, lastSequence: event.sequence }, disposition: 'ignored-stale-generation' };
  }
  return {
    disposition: 'applied',
    state: {
      ...state,
      lastSequence: event.sequence,
      bindingsBySessionId: { ...state.bindingsBySessionId, [binding.sessionId]: binding },
      capabilitiesBySessionId: {
        ...state.capabilitiesBySessionId,
        [capability.sessionId]: {
          ...state.capabilitiesBySessionId[capability.sessionId],
          [capability.capabilityId]: capability,
        },
      },
    },
  };
}

export function applyCapabilityCenterSnapshot(
  state: CapabilityCenterProjection,
  snapshot: CapabilityCenterSnapshotFixture,
): CapabilityCenterProjection {
  if (snapshot.roomId !== state.roomId) throw new TypeError('Capability snapshot belongs to another Room');
  const next = createCapabilityCenterProjection(state.roomId);
  next.lastSequence = nonNegativeInteger(snapshot.lastSequence, 'lastSequence');
  next.snapshotHash = requiredHash(snapshot.snapshotHash);
  for (const binding of snapshot.bindings) {
    if (next.bindingsBySessionId[binding.sessionId]) throw new TypeError('Capability snapshot repeats a Session binding');
    next.bindingsBySessionId[binding.sessionId] = binding;
  }
  for (const capability of snapshot.capabilities) {
    const binding = next.bindingsBySessionId[capability.sessionId];
    if (!binding) throw new TypeError('Capability snapshot has no matching Session binding');
    validateProjectionPair(binding, capability);
    next.capabilitiesBySessionId[capability.sessionId] ??= {};
    if (next.capabilitiesBySessionId[capability.sessionId]![capability.capabilityId]) {
      throw new TypeError('Capability snapshot repeats a capability');
    }
    next.capabilitiesBySessionId[capability.sessionId]![capability.capabilityId] = capability;
  }
  return next;
}

function validateProjectionPair(binding: ParticipantBindingProjection, capability: CapabilityProjection): void {
  if (!binding.sessionId || binding.sessionId !== capability.sessionId) throw new TypeError('Capability and binding Session mismatch');
  if (binding.generation !== capability.generation) throw new TypeError('Capability and binding generation mismatch');
  nonNegativeInteger(binding.generation, 'generation');
  requiredHash(binding.compiledRuntimeProfileRef.contentHash);
  requiredHash(capability.manifestRef.contentHash);
  for (const state of ['available', 'authorized', 'disclosed', 'loaded', 'invoked', 'revoked'] as const) {
    if (typeof capability.states[state] !== 'boolean') throw new TypeError(`Capability state ${state} is missing`);
  }
}

function requiredHash(value: string): string {
  if (!/^sha256:[a-f0-9]{64}$/.test(value)) throw new TypeError('Capability content hash is invalid');
  return value;
}

function nonNegativeInteger(value: number, field: string): number {
  if (!Number.isInteger(value) || value < 0) throw new TypeError(`${field} must be a non-negative integer`);
  return value;
}
