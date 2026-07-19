/**
 * Temporary Room V2 projection fixtures. These types intentionally do not
 * duplicate lane A's wire schemas; the reducer will consume generated v2
 * contracts after the merge window.
 */

export type RootState = 'queued' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled';
export type SessionState = 'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type RoomPostProjection = {
  postId: string;
  roomId: string;
  rootId: string | null;
  sequence: number;
  authorParticipantId: string | null;
  kind: 'user_request' | 'answer' | 'finding' | 'decision' | 'question' | 'result' | 'blocker' | 'announcement';
  visibility: 'room' | 'participants';
  content: string;
  createdAtMs: number;
};

export type PrivateSessionProjection = {
  sessionId: string;
  rootId: string | null;
  generation: number;
  state: SessionState;
  updatedAtMs: number;
};

export type RootTerminalReceiptProjection = {
  receiptId: string;
  rootId: string;
  generation: number;
  terminalState: Extract<RootState, 'completed' | 'failed' | 'cancelled'>;
  quiescent: boolean;
  acceptancePassed: boolean;
};

export type RootProjection = {
  rootId: string;
  generation: number;
  state: RootState;
  ownerParticipantId: string | null;
  isFinal: boolean;
  updatedAtMs: number;
};

export type RootStopRequestProjection = {
  generation: number;
  idempotencyKey: string;
  requestedAtMs: number;
  state: 'requested' | 'acknowledged';
};

export type RootRuntimeProjection = {
  generation: number;
  stopRequest: RootStopRequestProjection | null;
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
  postsById: Record<string, RoomPostProjection>;
  postOrder: string[];
  sessionsById: Record<string, PrivateSessionProjection>;
  rootsById: Record<string, RootProjection>;
  terminalReceiptsByRootId: Record<string, RootTerminalReceiptProjection>;
  runtimeByRootId: Record<string, RootRuntimeProjection>;
  diagnostics: RoomKernelDiagnostic[];
};

export type RoomKernelEventFixture = {
  schemaVersion: 'room-kernel-ui-fixture.v1';
  eventId: string;
  roomId: string;
  sequence: number;
  eventType:
    | 'post_published'
    | 'session_state_changed'
    | 'root_state_changed'
    | 'root_terminal_receipt'
    | 'root_stop_acknowledged'
    | 'legacy_message_completed'
    | 'legacy_turn_completed';
  createdAtMs: number;
  payload: Record<string, unknown>;
};

export type RoomKernelSnapshotFixture = {
  schemaVersion: 'room-kernel-ui-fixture.v1';
  roomId: string;
  lastSequence: number;
  snapshotHash: string;
  roots: Array<Omit<RootProjection, 'isFinal' | 'updatedAtMs'>>;
  sessions: Array<Omit<PrivateSessionProjection, 'updatedAtMs'>>;
  posts: RoomPostProjection[];
  terminalReceipts: RootTerminalReceiptProjection[];
};

export type RoomKernelReduction = {
  state: RoomKernelProjection;
  disposition: 'applied' | 'ignored-foreign' | 'ignored-duplicate' | 'ignored-snapshot-pending' | 'snapshot-required';
};

export function createRoomKernelProjection(roomId: string): RoomKernelProjection {
  return {
    roomId,
    lastSequence: 0,
    snapshotHash: '',
    needsSnapshot: false,
    gap: null,
    postsById: {},
    postOrder: [],
    sessionsById: {},
    rootsById: {},
    terminalReceiptsByRootId: {},
    runtimeByRootId: {},
    diagnostics: [],
  };
}

export function reduceRoomKernelEvent(
  state: RoomKernelProjection,
  event: RoomKernelEventFixture,
): RoomKernelReduction {
  if (event.roomId !== state.roomId) return { state, disposition: 'ignored-foreign' };
  if (event.sequence <= state.lastSequence) return { state, disposition: 'ignored-duplicate' };
  if (state.needsSnapshot) return { state, disposition: 'ignored-snapshot-pending' };
  if (state.lastSequence > 0 && event.sequence !== state.lastSequence + 1) {
    return {
      state: {
        ...state,
        needsSnapshot: true,
        gap: { expectedSequence: state.lastSequence + 1, receivedSequence: event.sequence },
      },
      disposition: 'snapshot-required',
    };
  }

  const next = cloneProjection(state);
  next.lastSequence = event.sequence;
  switch (event.eventType) {
    case 'post_published':
      applyPost(next, event.payload.post);
      break;
    case 'session_state_changed':
      applySessionState(next, event.payload, event.createdAtMs, event.eventId);
      break;
    case 'root_state_changed':
      applyRootState(next, event.payload, event.createdAtMs, event.eventId);
      break;
    case 'root_terminal_receipt':
      applyTerminalReceipt(next, event.payload.receipt, event.eventId);
      break;
    case 'root_stop_acknowledged':
      applyStopAcknowledged(next, event.payload, event.eventId);
      break;
    case 'legacy_message_completed':
    case 'legacy_turn_completed':
      appendDiagnostic(next, {
        eventId: event.eventId,
        kind: 'legacy-private-event',
        summary: `${event.eventType} is not a RoomPost or Root terminal receipt`,
      });
      break;
  }
  return { state: next, disposition: 'applied' };
}

export function applyRoomKernelSnapshot(
  state: RoomKernelProjection,
  snapshot: RoomKernelSnapshotFixture,
): RoomKernelProjection {
  if (snapshot.roomId !== state.roomId) throw new TypeError('Room snapshot belongs to another Room');
  const next = createRoomKernelProjection(state.roomId);
  next.lastSequence = nonNegativeInteger(snapshot.lastSequence, 'lastSequence');
  next.snapshotHash = requiredText(snapshot.snapshotHash, 'snapshotHash');
  for (const root of snapshot.roots) {
    const rootId = requiredText(root.rootId, 'rootId');
    const generation = nonNegativeInteger(root.generation, 'generation');
    next.rootsById[rootId] = {
      ...root,
      rootId,
      generation,
      ownerParticipantId: optionalText(root.ownerParticipantId),
      isFinal: false,
      updatedAtMs: 0,
    };
    next.runtimeByRootId[rootId] = { generation, stopRequest: null };
  }
  for (const session of snapshot.sessions) {
    const sessionId = requiredText(session.sessionId, 'sessionId');
    next.sessionsById[sessionId] = { ...session, sessionId, updatedAtMs: 0 };
  }
  for (const post of snapshot.posts) applyPost(next, post);
  for (const receipt of snapshot.terminalReceipts) applyTerminalReceipt(next, receipt, 'snapshot');
  return next;
}

export function requestRootStop(
  state: RoomKernelProjection,
  request: {
    rootId: string;
    generation: number;
    idempotencyKey: string;
    requestedAtMs: number;
  },
): RoomKernelProjection {
  const rootId = requiredText(request.rootId, 'rootId');
  const root = state.rootsById[rootId];
  if (!root) throw new TypeError('Cannot Stop an unknown Root');
  if (root.generation !== request.generation) throw new TypeError('Stop generation does not match Root');
  if (root.isFinal) throw new TypeError('Cannot Stop a final Root');
  const runtime = state.runtimeByRootId[rootId] ?? { generation: root.generation, stopRequest: null };
  if (runtime.stopRequest?.idempotencyKey === request.idempotencyKey) return state;
  if (runtime.stopRequest?.state === 'requested') throw new TypeError('Root already has a pending Stop');
  const next = cloneProjection(state);
  next.runtimeByRootId[rootId] = {
    generation: root.generation,
    stopRequest: {
      generation: root.generation,
      idempotencyKey: requiredText(request.idempotencyKey, 'idempotencyKey'),
      requestedAtMs: nonNegativeInteger(request.requestedAtMs, 'requestedAtMs'),
      state: 'requested',
    },
  };
  return next;
}

function applyPost(state: RoomKernelProjection, value: unknown): void {
  const post = record(value);
  const postId = requiredText(post.postId, 'postId');
  const roomId = requiredText(post.roomId, 'post.roomId');
  if (roomId !== state.roomId) throw new TypeError('RoomPost belongs to another Room');
  const visibility = post.visibility;
  if (visibility !== 'room' && visibility !== 'participants') {
    throw new TypeError('RoomPost visibility is invalid');
  }
  const kind = post.kind;
  if (!isPostKind(kind)) throw new TypeError('RoomPost kind is invalid');
  const projection: RoomPostProjection = {
    postId,
    roomId,
    rootId: optionalText(post.rootId),
    sequence: nonNegativeInteger(post.sequence, 'post.sequence'),
    authorParticipantId: optionalText(post.authorParticipantId),
    kind,
    visibility,
    content: requiredText(post.content, 'post.content'),
    createdAtMs: nonNegativeInteger(post.createdAtMs, 'post.createdAtMs'),
  };
  if (!state.postsById[postId]) state.postOrder.push(postId);
  state.postsById[postId] = projection;
}

function applySessionState(
  state: RoomKernelProjection,
  payload: Record<string, unknown>,
  createdAtMs: number,
  eventId: string,
): void {
  try {
    const sessionId = requiredText(payload.sessionId, 'sessionId');
    const generation = nonNegativeInteger(payload.generation, 'generation');
    const current = state.sessionsById[sessionId];
    if (current && generation < current.generation) {
      appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Stale Session state ignored' });
      return;
    }
    const sessionState = payload.state;
    if (!isSessionState(sessionState)) throw new TypeError('Session state is invalid');
    state.sessionsById[sessionId] = {
      sessionId,
      rootId: optionalText(payload.rootId),
      generation,
      state: sessionState,
      updatedAtMs: createdAtMs,
    };
  } catch (error) {
    appendDiagnostic(state, { eventId, kind: 'invalid-event', summary: publicError(error) });
  }
}

function applyRootState(
  state: RoomKernelProjection,
  payload: Record<string, unknown>,
  createdAtMs: number,
  eventId: string,
): void {
  try {
    const rootId = requiredText(payload.rootId, 'rootId');
    const generation = nonNegativeInteger(payload.generation, 'generation');
    const current = state.rootsById[rootId];
    if (current && generation < current.generation) {
      appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Stale Root state ignored' });
      return;
    }
    const rootState = payload.state;
    if (!isRootState(rootState)) throw new TypeError('Root state is invalid');
    const generationChanged = current?.generation !== generation;
    state.rootsById[rootId] = {
      rootId,
      generation,
      state: rootState,
      ownerParticipantId: optionalText(payload.ownerParticipantId),
      isFinal: generationChanged ? false : current?.isFinal ?? false,
      updatedAtMs: createdAtMs,
    };
    if (generationChanged) {
      delete state.terminalReceiptsByRootId[rootId];
      state.runtimeByRootId[rootId] = { generation, stopRequest: null };
    }
  } catch (error) {
    appendDiagnostic(state, { eventId, kind: 'invalid-event', summary: publicError(error) });
  }
}

function applyTerminalReceipt(
  state: RoomKernelProjection,
  value: unknown,
  eventId: string,
): void {
  const receipt = record(value);
  const rootId = optionalText(receipt.rootId);
  const root = rootId ? state.rootsById[rootId] : undefined;
  const generation = integer(receipt.generation);
  if (!rootId || !root || generation === null || generation !== root.generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Unmatched Root terminal receipt ignored' });
    return;
  }
  const terminalState = receipt.terminalState;
  if (!isTerminalState(terminalState) || receipt.quiescent !== true) {
    appendDiagnostic(state, { eventId, kind: 'invalid-event', summary: 'Root terminal receipt is incomplete' });
    return;
  }
  if (terminalState === 'completed' && receipt.acceptancePassed !== true) {
    appendDiagnostic(state, { eventId, kind: 'invalid-event', summary: 'Completed Root has no acceptance receipt' });
    return;
  }
  const projection: RootTerminalReceiptProjection = {
    receiptId: requiredText(receipt.receiptId, 'receiptId'),
    rootId,
    generation,
    terminalState,
    quiescent: true,
    acceptancePassed: receipt.acceptancePassed === true,
  };
  state.terminalReceiptsByRootId[rootId] = projection;
  state.rootsById[rootId] = { ...root, state: terminalState, isFinal: true };
}

function applyStopAcknowledged(
  state: RoomKernelProjection,
  payload: Record<string, unknown>,
  eventId: string,
): void {
  const rootId = optionalText(payload.rootId);
  const generation = integer(payload.generation);
  const runtime = rootId ? state.runtimeByRootId[rootId] : undefined;
  if (!rootId || generation === null || !runtime || runtime.generation !== generation) {
    appendDiagnostic(state, { eventId, kind: 'stale-generation', summary: 'Unmatched Stop acknowledgement ignored' });
    return;
  }
  if (!runtime.stopRequest || runtime.stopRequest.idempotencyKey !== payload.idempotencyKey) {
    appendDiagnostic(state, { eventId, kind: 'invalid-event', summary: 'Stop acknowledgement has no request' });
    return;
  }
  state.runtimeByRootId[rootId] = {
    ...runtime,
    stopRequest: { ...runtime.stopRequest, state: 'acknowledged' },
  };
}

function cloneProjection(state: RoomKernelProjection): RoomKernelProjection {
  return {
    ...state,
    gap: state.gap ? { ...state.gap } : null,
    postsById: { ...state.postsById },
    postOrder: [...state.postOrder],
    sessionsById: { ...state.sessionsById },
    rootsById: { ...state.rootsById },
    terminalReceiptsByRootId: { ...state.terminalReceiptsByRootId },
    runtimeByRootId: Object.fromEntries(Object.entries(state.runtimeByRootId).map(([rootId, runtime]) => [
      rootId,
      { ...runtime, stopRequest: runtime.stopRequest ? { ...runtime.stopRequest } : null },
    ])),
    diagnostics: [...state.diagnostics],
  };
}

function appendDiagnostic(state: RoomKernelProjection, diagnostic: RoomKernelDiagnostic): void {
  state.diagnostics.push(diagnostic);
  if (state.diagnostics.length > 50) state.diagnostics.splice(0, state.diagnostics.length - 50);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
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

function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new TypeError(`${field} must be nonnegative`);
  return Number(value);
}

function integer(value: unknown): number | null {
  return Number.isInteger(value) ? Number(value) : null;
}

function publicError(error: unknown): string {
  return error instanceof Error ? error.message : 'Invalid Room event';
}

function isRootState(value: unknown): value is RootState {
  return ['queued', 'running', 'waiting', 'completed', 'failed', 'cancelled'].includes(String(value));
}

function isTerminalState(value: unknown): value is RootTerminalReceiptProjection['terminalState'] {
  return ['completed', 'failed', 'cancelled'].includes(String(value));
}

function isSessionState(value: unknown): value is SessionState {
  return ['idle', 'queued', 'running', 'completed', 'failed', 'cancelled'].includes(String(value));
}

function isPostKind(value: unknown): value is RoomPostProjection['kind'] {
  return ['user_request', 'answer', 'finding', 'decision', 'question', 'result', 'blocker', 'announcement']
    .includes(String(value));
}
