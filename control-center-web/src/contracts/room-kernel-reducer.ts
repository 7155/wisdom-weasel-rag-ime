import type { RoomDispatchEnvelopeV2 } from './generated/room-dispatch-envelope.v2';
import type { RoomEventEnvelopeV2 } from './generated/room-event-envelope.v2';
import type { RoomKernelReceiptV1 } from './generated/room-kernel-receipt.v1';
import type { RoomPostV2 } from './generated/room-post.v2';
import type { RoomRootExecutionV3 } from './generated/room-root-execution.v3';
import type { RoomTaskV3 } from './generated/room-task.v3';
import { parseContract } from './validators';

export type SessionState = 'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

/** Session is a private inspector read model. It is never promoted to a RoomPost. */
export type PrivateSessionProjection = {
  sessionId: string;
  rootId: string | null;
  generation: number;
  state: SessionState;
  updatedAtMs: number;
  capabilityManifest?: {
    manifestId: string;
    manifestHash: string;
    status: 'active' | 'revoked';
    rootId: string;
    taskId: string;
    dispatchId: string;
    generation: number;
    capabilityEpoch: number;
    promptCompileReceiptId: string;
    promptPlanHash: string;
    compiledRuntimeProfileRef: { profileId: string; revision: string; contentHash: string };
  };
  requirementObservation?: {
    anchorRefs: string[];
    catalogRevisionId: string | null;
    proofReceiptRefs: string[];
    warnings: string[];
    gateObservationRef: string | null;
    state: 'prepared' | 'active' | 'terminal';
  };
};

export type RootProjection = RoomRootExecutionV3 & {
  /** Computed by the adapter from an authoritative, matching terminal receipt. */
  isFinal: boolean;
  updatedAtMs: number;
};

export type CancellationSurfaceProjection = {
  cancelId: string;
  rootId: string;
  dispatchId: string;
  surface: 'provider' | 'tool' | 'exec' | 'retry' | 'compaction' | 'branch_summary' | 'timer' | 'continuation' | 'session';
  state: 'requested' | 'acknowledged' | 'terminated' | 'unknown';
  targetRef: string;
  detail: Record<string, unknown>;
  updatedAtMs: number;
};

export type RoomKernelDiagnostic = {
  eventId: string;
  kind: 'legacy-private-event' | 'stale-generation' | 'invalid-event';
  summary: string;
};

export type RoomKernelProjection = {
  roomId: string;
  lastSequence: number;
  snapshotHash: string;
  needsSnapshot: boolean;
  gap: { expectedSequence: number; receivedSequence: number } | null;
  rootsById: Record<string, RootProjection>;
  tasksById: Record<string, RoomTaskV3>;
  dispatchesById: Record<string, RoomDispatchEnvelopeV2>;
  postsById: Record<string, RoomPostV2>;
  postOrder: string[];
  sessionsById: Record<string, PrivateSessionProjection>;
  receiptsById: Record<string, RoomKernelReceiptV1>;
  terminalReceiptByRootId: Record<string, RoomKernelReceiptV1>;
  cancelReceiptByRootId: Record<string, RoomKernelReceiptV1>;
  cancellationSurfaces: CancellationSurfaceProjection[];
  diagnostics: RoomKernelDiagnostic[];
};

export type RoomKernelSnapshot = {
  roomId: string;
  lastSequence: number;
  snapshotHash: string;
  roots: RoomRootExecutionV3[];
  tasks: RoomTaskV3[];
  dispatches: RoomDispatchEnvelopeV2[];
  posts: RoomPostV2[];
  sessions: PrivateSessionProjection[];
  receipts: RoomKernelReceiptV1[];
  cancellationSurfaces: CancellationSurfaceProjection[];
};

export type RoomKernelReduction = {
  state: RoomKernelProjection;
  disposition: 'applied' | 'ignored-duplicate' | 'ignored-snapshot-pending' | 'snapshot-required';
};

export function createRoomKernelProjection(roomId: string): RoomKernelProjection {
  return {
    roomId: requiredText(roomId, 'roomId'),
    lastSequence: 0,
    snapshotHash: '',
    needsSnapshot: false,
    gap: null,
    rootsById: {},
    tasksById: {},
    dispatchesById: {},
    postsById: {},
    postOrder: [],
    sessionsById: {},
    receiptsById: {},
    terminalReceiptByRootId: {},
    cancelReceiptByRootId: {},
    cancellationSurfaces: [],
    diagnostics: [],
  };
}

export function reduceRoomKernelEvent(
  state: RoomKernelProjection,
  input: RoomEventEnvelopeV2,
): RoomKernelReduction {
  const event = parseContract('room-event-envelope.v2', input);
  if (event.sequence <= state.lastSequence) return { state, disposition: 'ignored-duplicate' };
  if (state.needsSnapshot) return { state, disposition: 'ignored-snapshot-pending' };
  if (state.lastSequence > 0 && event.sequence !== state.lastSequence + 1) {
    return {
      state: { ...state, needsSnapshot: true, gap: { expectedSequence: state.lastSequence + 1, receivedSequence: event.sequence } },
      disposition: 'snapshot-required',
    };
  }

  const next = cloneProjection(state);
  next.lastSequence = event.sequence;
  const eventId = `${event.entityKind}:${event.entityId}:${event.sequence}`;
  try {
    applyCanonicalEvent(next, event, eventId);
  } catch (error) {
    appendDiagnostic(next, { eventId, kind: 'invalid-event', summary: publicError(error) });
  }
  return { state: next, disposition: 'applied' };
}

export function applyRoomKernelSnapshot(
  state: RoomKernelProjection,
  snapshot: RoomKernelSnapshot,
): RoomKernelProjection {
  if (snapshot.roomId !== state.roomId) throw new TypeError('Room snapshot belongs to another Room');
  const next = createRoomKernelProjection(state.roomId);
  next.lastSequence = nonNegativeInteger(snapshot.lastSequence, 'lastSequence');
  next.snapshotHash = requiredText(snapshot.snapshotHash, 'snapshotHash');
  for (const root of snapshot.roots) applyRoot(next, root, 0, 'snapshot');
  for (const task of snapshot.tasks) applyTask(next, task, 'snapshot');
  for (const dispatch of snapshot.dispatches) applyDispatch(next, dispatch, 'snapshot');
  for (const post of snapshot.posts) applyPost(next, post);
  for (const session of snapshot.sessions) applySession(next, session, 'snapshot');
  for (const receipt of snapshot.receipts) applyReceipt(next, receipt, 'snapshot');
  next.cancellationSurfaces = snapshot.cancellationSurfaces.map((item) => ({ ...item, detail: { ...item.detail } }));
  return next;
}

function applyCanonicalEvent(state: RoomKernelProjection, event: RoomEventEnvelopeV2, eventId: string): void {
  if (event.eventKind === 'legacy_message_completed' || event.eventKind === 'legacy_turn_completed') {
    appendDiagnostic(state, {
      eventId,
      kind: 'legacy-private-event',
      summary: `${event.eventKind} is private and cannot publish a RoomPost`,
    });
    return;
  }
  switch (`${event.entityKind}:${event.eventKind}`) {
    case 'root:upserted':
    case 'root:state_changed':
      applyRoot(state, event.payload.root, event.occurredAtMs, eventId);
      return;
    case 'root:kernel_receipt':
      applyReceipt(state, event.payload.receipt, eventId);
      return;
    case 'task:upserted':
    case 'task:state_changed':
      applyTask(state, event.payload.task, eventId);
      return;
    case 'dispatch:upserted':
    case 'dispatch:state_changed':
      applyDispatch(state, event.payload.dispatch, eventId);
      return;
    case 'post:published':
      applyPost(state, event.payload.post);
      return;
    case 'binding:session_projection':
      applySession(state, event.payload.session, eventId);
      return;
    default:
      throw new TypeError(`Unsupported Room kernel event: ${event.entityKind}:${event.eventKind}`);
  }
}

function applyRoot(state: RoomKernelProjection, value: unknown, updatedAtMs: number, eventId: string): void {
  const root = parseContract('room-root-execution.v3', value);
  if (root.roomId !== state.roomId) throw new TypeError('Root belongs to another Room');
  const current = state.rootsById[root.rootId];
  if (current && root.generation < current.generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Stale Root projection ignored' });
    return;
  }
  if (current && root.generation === current.generation && updatedAtMs < current.updatedAtMs) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Out-of-order Root projection ignored' });
    return;
  }
  if (!current || root.generation !== current.generation) {
    delete state.terminalReceiptByRootId[root.rootId];
    delete state.cancelReceiptByRootId[root.rootId];
  }
  state.rootsById[root.rootId] = { ...root, isFinal: false, updatedAtMs };
  reconcileFinal(state, root.rootId);
}

function applyTask(state: RoomKernelProjection, value: unknown, eventId: string): void {
  const task = parseContract('room-task.v3', value);
  const root = state.rootsById[task.rootId];
  if (!root) throw new TypeError('Task has no projected Root');
  const current = state.tasksById[task.taskId];
  if (current && task.revision < current.revision) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Stale Task revision ignored' });
    return;
  }
  state.tasksById[task.taskId] = task;
}

function applyDispatch(state: RoomKernelProjection, value: unknown, eventId: string): void {
  const dispatch = parseContract('room-dispatch-envelope.v2', value);
  const root = state.rootsById[dispatch.rootId];
  if (!root || dispatch.generation !== root.generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Dispatch generation does not match Root' });
    return;
  }
  state.dispatchesById[dispatch.dispatchId] = dispatch;
}

function applyPost(state: RoomKernelProjection, value: unknown): void {
  const post = parseContract('room-post.v2', value);
  if (post.roomId !== state.roomId) throw new TypeError('RoomPost belongs to another Room');
  const root = state.rootsById[post.rootId];
  if (!root || post.generation !== root.generation) throw new TypeError('RoomPost generation does not match Root');
  if (!state.postsById[post.postId]) state.postOrder.push(post.postId);
  state.postsById[post.postId] = post;
}

function applySession(state: RoomKernelProjection, value: unknown, eventId: string): void {
  const session = privateSession(value);
  const root = session.rootId ? state.rootsById[session.rootId] : undefined;
  if (root && session.generation !== root.generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Session generation does not match Root' });
    return;
  }
  const current = state.sessionsById[session.sessionId];
  if (current && (session.generation < current.generation || session.updatedAtMs < current.updatedAtMs)) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Stale Session projection ignored' });
    return;
  }
  state.sessionsById[session.sessionId] = session;
}

function applyReceipt(state: RoomKernelProjection, value: unknown, eventId: string): void {
  const receipt = parseContract('room-kernel-receipt.v1', value);
  if (!receipt.rootId) return;
  const root = state.rootsById[receipt.rootId];
  if (!root || receipt.generation !== root.generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Kernel receipt generation does not match Root' });
    return;
  }
  state.receiptsById[receipt.receiptId] = receipt;
  if (receipt.receiptKind === 'terminal') state.terminalReceiptByRootId[receipt.rootId] = receipt;
  if (receipt.receiptKind === 'root_cancelled' || receipt.receiptKind === 'target_cancelled') {
    state.cancelReceiptByRootId[receipt.rootId] = receipt;
  }
  reconcileFinal(state, receipt.rootId);
}

function reconcileFinal(state: RoomKernelProjection, rootId: string): void {
  const root = state.rootsById[rootId];
  if (!root) return;
  const receipt = state.terminalReceiptByRootId[rootId];
  const terminal = Boolean(
    receipt
      && receipt.status === 'applied'
      && receipt.generation === root.generation
      && root.terminalReceiptId === receipt.receiptId
      && ['completed', 'failed', 'cancelled'].includes(root.state),
  );
  state.rootsById[rootId] = { ...root, isFinal: terminal };
}

function privateSession(value: unknown): PrivateSessionProjection {
  const item = record(value);
  const sessionState = item.state;
  if (!isSessionState(sessionState)) throw new TypeError('Session state is invalid');
  const capabilityManifest = item.capabilityManifest === undefined
    ? undefined
    : privateCapabilityManifest(item.capabilityManifest);
  const requirementObservation = item.requirementObservation === undefined
    ? undefined
    : privateRequirementObservation(item.requirementObservation);
  return {
    sessionId: requiredText(item.sessionId, 'sessionId'),
    rootId: optionalText(item.rootId),
    generation: nonNegativeInteger(item.generation, 'generation'),
    state: sessionState,
    updatedAtMs: nonNegativeInteger(item.updatedAtMs, 'updatedAtMs'),
    ...(capabilityManifest ? { capabilityManifest } : {}),
    ...(requirementObservation ? { requirementObservation } : {}),
  };
}

function privateRequirementObservation(value: unknown): NonNullable<PrivateSessionProjection['requirementObservation']> {
  const item = record(value);
  const state = item.state;
  if (state !== 'prepared' && state !== 'active' && state !== 'terminal') {
    throw new TypeError('Requirement observation state is invalid');
  }
  return {
    anchorRefs: textArray(item.anchorRefs),
    catalogRevisionId: optionalText(item.catalogRevisionId),
    proofReceiptRefs: textArray(item.proofReceiptRefs),
    warnings: textArray(item.warnings),
    gateObservationRef: optionalText(item.gateObservationRef),
    state,
  };
}

function privateCapabilityManifest(value: unknown): NonNullable<PrivateSessionProjection['capabilityManifest']> {
  const item = record(value);
  const status = item.status;
  if (status !== 'active' && status !== 'revoked') throw new TypeError('Capability Manifest status is invalid');
  const profile = record(item.compiledRuntimeProfileRef);
  const manifestHash = requiredText(item.manifestHash, 'manifestHash');
  const promptPlanHash = requiredText(item.promptPlanHash, 'promptPlanHash');
  if (!/^[a-f0-9]{64}$/.test(manifestHash) || !/^[a-f0-9]{64}$/.test(promptPlanHash)) {
    throw new TypeError('Capability Manifest hashes are invalid');
  }
  return {
    manifestId: requiredText(item.manifestId, 'manifestId'),
    manifestHash,
    status,
    rootId: requiredText(item.rootId, 'rootId'),
    taskId: requiredText(item.taskId, 'taskId'),
    dispatchId: requiredText(item.dispatchId, 'dispatchId'),
    generation: nonNegativeInteger(item.generation, 'generation'),
    capabilityEpoch: nonNegativeInteger(item.capabilityEpoch, 'capabilityEpoch'),
    promptCompileReceiptId: requiredText(item.promptCompileReceiptId, 'promptCompileReceiptId'),
    promptPlanHash,
    compiledRuntimeProfileRef: {
      profileId: requiredText(profile.profileId, 'profileId'),
      revision: requiredText(profile.revision, 'profileRevision'),
      contentHash: requiredText(profile.contentHash, 'profileContentHash'),
    },
  };
}

function cloneProjection(state: RoomKernelProjection): RoomKernelProjection {
  return {
    ...state,
    gap: state.gap ? { ...state.gap } : null,
    rootsById: { ...state.rootsById },
    tasksById: { ...state.tasksById },
    dispatchesById: { ...state.dispatchesById },
    postsById: { ...state.postsById },
    postOrder: [...state.postOrder],
    sessionsById: { ...state.sessionsById },
    receiptsById: { ...state.receiptsById },
    terminalReceiptByRootId: { ...state.terminalReceiptByRootId },
    cancelReceiptByRootId: { ...state.cancelReceiptByRootId },
    cancellationSurfaces: state.cancellationSurfaces.map((item) => ({ ...item, detail: { ...item.detail } })),
    diagnostics: [...state.diagnostics],
  };
}

function appendDiagnostic(state: RoomKernelProjection, diagnostic: RoomKernelDiagnostic): void {
  state.diagnostics.push(diagnostic);
  if (state.diagnostics.length > 50) state.diagnostics.splice(0, state.diagnostics.length - 50);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function requiredText(value: unknown, field: string): string {
  const normalized = typeof value === 'string' ? value.trim() : '';
  if (!normalized) throw new TypeError(`${field} is required`);
  return normalized;
}

function optionalText(value: unknown): string | null {
  const normalized = typeof value === 'string' ? value.trim() : '';
  return normalized || null;
}

function textArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || !item.trim())) {
    throw new TypeError('Expected a non-empty string array');
  }
  return value.map((item) => item.trim());
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new TypeError(`${field} must be nonnegative`);
  return Number(value);
}

function publicError(error: unknown): string {
  return error instanceof Error ? error.message : 'Invalid Room event';
}

function isSessionState(value: unknown): value is SessionState {
  return ['idle', 'queued', 'running', 'completed', 'failed', 'cancelled'].includes(String(value));
}
