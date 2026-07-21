import type { ProjectionDiagnostic, ProjectionGap, ProjectionReduction } from './agent-reducer';
import type { AgentRoomSnapshotV1, RoomPostV2 } from './generated';
import type { UiAgentMessage, UiRoomEvent } from './ui-events';
import { parseContract, parseRoomEvent, tryParseAgentMessage } from './validators';

export interface RoomMessageProjection {
  id: string;
  roomId: string;
  turnId: string;
  participantId: string | null;
  sourceSessionId: string;
  role: 'user' | 'assistant';
  status: 'queued' | 'streaming' | 'completed' | 'failed' | 'aborted';
  text: string;
  message?: UiAgentMessage;
  clientMessageId?: string;
  projectionKind?: 'optimistic' | 'execution' | 'post';
  rootId?: string;
  dispatchId?: string;
  createdAtMs: number;
  completedAtMs?: number;
}

export interface RoomActivityProjection {
  id: string;
  turnId: string;
  participantId: string | null;
  sourceSessionId: string;
  kind: string;
  status: 'running' | 'completed' | 'failed';
  summary: string;
  payload: Record<string, unknown>;
  createdAtMs: number;
  updatedAtMs?: number;
}

export interface RoomActivityLaneIdentity {
  rootId: string;
  participantId: string;
  dispatchId: string;
  key: string;
}

export interface RoomTurnProjection {
  id: string;
  rootId?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted';
  messageIds: string[];
  activityIds: string[];
  participantIds: string[];
  terminalParticipantIds?: string[];
  failedParticipantIds?: string[];
  abortedParticipantIds?: string[];
  dispatchIds?: string[];
  terminalDispatchIds?: string[];
  failedDispatchIds?: string[];
  abortedDispatchIds?: string[];
  dispatchParticipantIds?: Record<string, string>;
  rootTerminalAtMs?: number;
  createdAtMs: number;
  updatedAtMs: number;
  failure?: string;
}

export interface RoomProjectionState {
  roomId: string;
  lastSequence: number;
  lastEventId: string;
  resumeToken: string;
  needsSnapshot: boolean;
  gap?: ProjectionGap;
  messagesById: Record<string, RoomMessageProjection>;
  messageOrder: string[];
  activitiesById: Record<string, RoomActivityProjection>;
  activityOrder: string[];
  turnsById: Record<string, RoomTurnProjection>;
  turnOrder: string[];
  optimisticByClientMessageId: Record<string, string>;
  diagnostics: ProjectionDiagnostic[];
}

export interface RoomSnapshot {
  messages: RoomMessageProjection[];
  lastSequence: number;
  resumeToken: string;
}

export type RoomEventSnapshot = Omit<AgentRoomSnapshotV1, 'events'> & {
  events: UiRoomEvent[];
};

export interface RoomEventReductionOptions {
  snapshotReplay?: boolean;
}

export interface OptimisticRoomMessageInput {
  clientMessageId: string;
  text: string;
  nowMs: number;
}

const diagnosticLimit = 50;

export function createRoomProjection(roomId: string): RoomProjectionState {
  return {
    roomId,
    lastSequence: 0,
    lastEventId: '',
    resumeToken: '',
    needsSnapshot: false,
    messagesById: {},
    messageOrder: [],
    activitiesById: {},
    activityOrder: [],
    turnsById: {},
    turnOrder: [],
    optimisticByClientMessageId: {},
    diagnostics: [],
  };
}

export function reduceRoomEvent(
  state: RoomProjectionState,
  event: UiRoomEvent,
  options: RoomEventReductionOptions = {},
): ProjectionReduction<RoomProjectionState> {
  if (event.roomId !== state.roomId) return { state, disposition: 'ignored-foreign' };
  if (event.sequence <= state.lastSequence) {
    return { state, disposition: 'ignored-duplicate' };
  }
  if (state.needsSnapshot) return { state, disposition: 'ignored-snapshot-pending' };
  if (state.lastSequence > 0 && event.sequence !== state.lastSequence + 1) {
    return {
      state: {
        ...state,
        needsSnapshot: true,
        gap: {
          expectedSequence: state.lastSequence + 1,
          receivedSequence: event.sequence,
          receivedEventId: event.eventId,
        },
      },
      disposition: 'snapshot-required',
    };
  }

  const next = cloneState(state);
  next.lastSequence = event.sequence;
  next.lastEventId = event.eventId;
  next.resumeToken = event.resumeToken;
  const payload = publicRoomPayload(event.payload);

  if (isExecutionEventAfterRootTerminal(next, event, payload)) {
    appendDiagnostic(next, {
      id: `${event.eventId}:after-root-terminal`,
      streamKind: 'room',
      eventType: 'room_event_after_root_terminal',
      summary: 'A late Room execution event was ignored after the Root terminal fence.',
      sequence: event.sequence,
      payload,
    });
    return { state: next, disposition: 'applied' };
  }

  switch (event.eventType) {
    case 'user_message':
      applyUserMessage(next, event, payload);
      break;
    case 'participant_delta':
      applyParticipantDelta(next, event, payload);
      break;
    case 'participant_message':
      applyParticipantMessage(next, event, payload);
      break;
    case 'room_post':
      applyRoomPost(next, event, payload);
      break;
    case 'route_decision':
    case 'participant_status':
    case 'participant_activity':
      upsertActivity(next, event, payload);
      break;
    case 'turn_completed':
      completeParticipantTurn(
        next,
        event,
        text(payload.dispatchId),
        text(payload.status) === 'aborted' || payload.aborted === true
          ? 'aborted'
          : 'completed',
        event.createdAtMs,
      );
      break;
    case 'turn_failed':
      completeParticipantTurn(
        next,
        event,
        text(payload.dispatchId),
        'failed',
        event.createdAtMs,
        text(payload.error),
      );
      upsertActivity(next, event, payload, 'failed');
      break;
    case 'room_config_changed':
    case 'topic_changed':
    case 'artifact_changed':
      appendDiagnostic(next, {
        id: event.eventId,
        streamKind: 'room',
        eventType: event.eventType,
        summary: 'Room metadata changed and is represented by the latest snapshot.',
        sequence: event.sequence,
        payload,
      });
      break;
    case 'snapshot_required':
      if (options.snapshotReplay) {
        appendDiagnostic(next, {
          id: event.eventId,
          streamKind: 'room',
          eventType: event.eventType,
          summary: 'A historical Room snapshot marker was replayed as an inert diagnostic.',
          sequence: event.sequence,
          payload,
        });
        break;
      }
      next.needsSnapshot = true;
      next.gap = {
        expectedSequence: state.lastSequence + 1,
        receivedSequence: event.sequence,
        receivedEventId: event.eventId,
      };
      return { state: next, disposition: 'snapshot-required' };
    case 'unknown':
      appendDiagnostic(next, {
        id: event.eventId,
        streamKind: 'room',
        eventType: event.rawEventType || 'unknown',
        summary: 'Unsupported room event was retained for diagnostics.',
        sequence: event.sequence,
        payload,
      });
      break;
  }
  return { state: next, disposition: 'applied' };
}

export function appendOptimisticRoomMessage(
  state: RoomProjectionState,
  input: OptimisticRoomMessageInput,
): RoomProjectionState {
  if (!input.clientMessageId.trim()) throw new TypeError('clientMessageId must not be empty');
  if (state.optimisticByClientMessageId[input.clientMessageId]) return state;
  const next = cloneState(state);
  const id = `local-room:${input.clientMessageId}`;
  const turnId = `local-room-turn:${input.clientMessageId}`;
  const message: RoomMessageProjection = {
    id,
    roomId: state.roomId,
    turnId,
    participantId: null,
    sourceSessionId: '',
    role: 'user',
    status: 'queued',
    text: input.text,
    clientMessageId: input.clientMessageId,
    projectionKind: 'optimistic',
    rootId: turnId,
    createdAtMs: input.nowMs,
  };
  next.messagesById[id] = message;
  next.messageOrder.push(id);
  next.optimisticByClientMessageId[input.clientMessageId] = id;
  attachMessage(next, message);
  next.turnsById[turnId].status = 'queued';
  return next;
}

export function roomActivityLaneIdentity(
  activity: RoomActivityProjection,
): RoomActivityLaneIdentity {
  const rootId = text(activity.payload.rootId) || activity.turnId;
  const participantId =
    text(activity.payload.targetParticipantId)
    || activity.participantId
    || activity.sourceSessionId
    || 'router';
  const dispatchId =
    text(activity.payload.dispatchId)
    || activity.sourceSessionId
    || text(activity.payload.sourceEventId)
    || activity.id;
  return {
    rootId,
    participantId,
    dispatchId,
    key: `${rootId}\u001f${participantId}\u001f${dispatchId}`,
  };
}

export function applyRoomSnapshot(
  state: RoomProjectionState,
  snapshot: RoomSnapshot,
): RoomProjectionState {
  const next = createRoomProjection(state.roomId);
  next.lastSequence = Math.max(0, snapshot.lastSequence);
  next.lastEventId = snapshot.resumeToken;
  next.resumeToken = snapshot.resumeToken;
  const clientIds = new Set(snapshot.messages.map((message) => message.clientMessageId).filter(Boolean));
  for (const message of snapshot.messages) upsertMessage(next, message);
  preserveOptimisticMessages(state, next, clientIds);
  return next;
}

export function parseRoomEventSnapshot(value: unknown): RoomEventSnapshot {
  const snapshot = parseContract('agent-room-snapshot.v1', value);
  const events = snapshot.events.map((event) => parseRoomEvent(event));
  if (snapshot.room.lastEventSequence !== snapshot.lastSequence) {
    throw new TypeError('Room snapshot metadata cursor does not match lastSequence');
  }
  if (events.length === 0) {
    if (
      snapshot.firstSequence !== 0 ||
      snapshot.lastSequence !== 0 ||
      snapshot.resumeToken !== ''
    ) {
      throw new TypeError('Empty Room snapshot must use a zero cursor');
    }
  } else {
    const first = events[0];
    const last = events[events.length - 1];
    if (
      first.sequence !== snapshot.firstSequence ||
      last.sequence !== snapshot.lastSequence ||
      last.resumeToken !== snapshot.resumeToken
    ) {
      throw new TypeError('Room snapshot bounds do not match its retained events');
    }
    for (const [index, event] of events.entries()) {
      if (
        event.roomId !== snapshot.room.id ||
        event.sequence !== snapshot.firstSequence + index
      ) {
        throw new TypeError('Room snapshot events must be contiguous and belong to the room');
      }
    }
    if (snapshot.firstSequence > 1 && !snapshot.truncated) {
      throw new TypeError('Room snapshot must disclose a truncated retained prefix');
    }
  }
  return { ...snapshot, events };
}

export function replayRoomEventSnapshot(
  state: RoomProjectionState,
  snapshot: RoomEventSnapshot,
): RoomProjectionState {
  if (state.roomId !== snapshot.room.id) {
    throw new TypeError('Room snapshot does not belong to the active Room');
  }
  let next = createRoomProjection(state.roomId);
  if (snapshot.firstSequence > 1) next.lastSequence = snapshot.firstSequence - 1;
  for (const event of snapshot.events) {
    const reduced = reduceRoomEvent(next, event, { snapshotReplay: true });
    if (reduced.disposition !== 'applied') {
      throw new TypeError(`Room snapshot replay failed: ${reduced.disposition}`);
    }
    next = reduced.state;
  }
  if (next.lastSequence !== snapshot.lastSequence) {
    throw new TypeError('Room snapshot replay did not reach its declared cursor');
  }
  next.lastEventId = snapshot.resumeToken;
  next.resumeToken = snapshot.resumeToken;
  const clientIds = new Set(
    Object.values(next.messagesById)
      .map((message) => message.clientMessageId)
      .filter((value): value is string => Boolean(value)),
  );
  preserveOptimisticMessages(state, next, clientIds);
  return next;
}

function preserveOptimisticMessages(
  state: RoomProjectionState,
  next: RoomProjectionState,
  serverClientIds: ReadonlySet<string | undefined>,
): void {
  for (const [clientMessageId, messageId] of Object.entries(
    state.optimisticByClientMessageId,
  )) {
    if (serverClientIds.has(clientMessageId)) continue;
    const message = state.messagesById[messageId];
    if (!message) continue;
    if (next.messagesById[messageId]) continue;
    next.messagesById[messageId] = message;
    next.messageOrder.push(messageId);
    next.optimisticByClientMessageId[clientMessageId] = messageId;
    attachMessage(next, message);
  }
}

export function abortRoomTurn(
  state: RoomProjectionState,
  turnId: string,
  nowMs: number,
): RoomProjectionState {
  if (!state.turnsById[turnId]) return state;
  const next = cloneState(state);
  completeTurn(next, turnId, 'aborted', nowMs);
  return next;
}

export function abortRoomParticipantTurn(
  state: RoomProjectionState,
  turnId: string,
  participantId: string,
  nowMs: number,
): RoomProjectionState {
  if (!state.turnsById[turnId] || !participantId) return state;
  const next = cloneState(state);
  completeParticipantTurn(
    next,
    {
      turnId,
      participantId,
    },
    '',
    'aborted',
    nowMs,
  );
  return next;
}

function applyUserMessage(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): void {
  const clientMessageId = text(payload.clientMessageId);
  const message: RoomMessageProjection = {
    id: text(payload.messageId) || `${event.eventId}:user`,
    roomId: event.roomId,
    turnId: event.turnId,
    participantId: event.participantId,
    sourceSessionId: event.sourceSessionId,
    role: 'user',
    status: 'completed',
    text: text(payload.text ?? payload.message),
    projectionKind: 'post',
    rootId: text(payload.rootId) || event.turnId,
    ...(clientMessageId ? { clientMessageId } : {}),
    createdAtMs: event.createdAtMs,
    completedAtMs: event.createdAtMs,
  };
  upsertMessage(state, message, clientMessageId);
}

function applyParticipantDelta(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): void {
  const rootId = text(payload.rootId) || event.turnId;
  const dispatchId = text(payload.dispatchId);
  const id = executionMessageId(event, payload);
  const existing = state.messagesById[id];
  const message: RoomMessageProjection = existing
    ? {
        ...existing,
        status: 'streaming',
        text: existing.text + text(payload.delta),
      }
    : {
        id,
        roomId: event.roomId,
        turnId: event.turnId,
        participantId: event.participantId,
        sourceSessionId: event.sourceSessionId,
        role: 'assistant',
        status: 'streaming',
        text: text(payload.delta),
        projectionKind: 'execution',
        rootId,
        ...(dispatchId ? { dispatchId } : {}),
        createdAtMs: event.createdAtMs,
      };
  upsertMessage(state, message);
}

function applyParticipantMessage(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): void {
  const parsed = tryParseAgentMessage(payload.message);
  if (!parsed.ok) {
    appendDiagnostic(state, {
      id: `${event.eventId}:invalid-message`,
      streamKind: 'room',
      eventType: 'participant_message_invalid',
      summary: 'A malformed participant message was skipped.',
      sequence: event.sequence,
      payload,
    });
    return;
  }
  const clientMessageId = text(payload.clientMessageId) || parsed.value.clientMessageId || '';
  const message: RoomMessageProjection = {
    id: parsed.value.id,
    roomId: event.roomId,
    turnId: event.turnId || parsed.value.turnId,
    participantId: event.participantId,
    sourceSessionId: event.sourceSessionId,
    role: parsed.value.role === 'user' ? 'user' : 'assistant',
    status: parsed.value.status,
    text: messageText(parsed.value),
    message: parsed.value,
    projectionKind: 'post',
    rootId: text(payload.rootId) || event.turnId,
    ...(text(payload.dispatchId) ? { dispatchId: text(payload.dispatchId) } : {}),
    ...(clientMessageId ? { clientMessageId } : {}),
    createdAtMs: parsed.value.createdAtMs,
    ...(parsed.value.completedAtMs == null
      ? {}
      : { completedAtMs: parsed.value.completedAtMs }),
  };
  const provisionalId = executionMessageId(event, payload);
  if (
    provisionalId !== message.id &&
    state.messagesById[provisionalId]?.status === 'streaming'
  ) {
    replaceProvisionalMessage(state, provisionalId, message);
    return;
  }
  upsertMessage(state, message, clientMessageId);
}

function applyRoomPost(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): void {
  let post: RoomPostV2;
  try {
    post = parseContract('room-post.v2', payload.post);
  } catch {
    appendDiagnostic(state, {
      id: `${event.eventId}:invalid-room-post`,
      streamKind: 'room',
      eventType: 'room_post_invalid',
      summary: 'A malformed RoomPost was skipped.',
      sequence: event.sequence,
      payload,
    });
    return;
  }
  const fallbackBlock: UiAgentMessage['blocks'][number] = {
    schemaVersion: 'rag-ime.agent-block.v1',
    id: `${post.postId}:text`,
    type: 'text',
    status: 'completed',
    presentationKind: 'markdown',
    data: { text: post.content },
    source: { kind: post.publicationSource.kind, ref: post.publicationSource.ref },
    visibility: post.visibility === 'room' ? 'room_post' : 'root_post',
    generation: post.generation,
  };
  const message: RoomMessageProjection = {
    id: post.postId,
    roomId: event.roomId,
    turnId: post.rootId,
    participantId: event.participantId,
    sourceSessionId: event.sourceSessionId,
    role: post.publicationSource.kind === 'user' ? 'user' : 'assistant',
    status: 'completed',
    text: post.content,
    projectionKind: 'post',
    rootId: post.rootId,
    ...(post.dispatchId ? { dispatchId: post.dispatchId } : {}),
    message: {
      schemaVersion: 'rag-ime.agent-message.v1',
      id: post.postId,
      sessionId: event.sourceSessionId || `room:${event.roomId}`,
      turnId: post.rootId,
      role: post.publicationSource.kind === 'user' ? 'user' : 'assistant',
      status: 'completed',
      blocks: (post.blocks?.length ? post.blocks : [fallbackBlock]) as UiAgentMessage['blocks'],
      attachments: [],
      citations: [],
      createdAtMs: post.createdAtMs,
      completedAtMs: post.createdAtMs,
    },
    createdAtMs: post.createdAtMs,
    completedAtMs: post.createdAtMs,
  };
  const provisional = Object.values(state.messagesById)
    .filter((candidate) => (
      candidate.projectionKind === 'execution'
      && candidate.rootId === post.rootId
      && candidate.dispatchId === (post.dispatchId ?? '')
      && candidate.participantId === event.participantId
    ))
    .sort((left, right) => right.createdAtMs - left.createdAtMs)[0];
  if (provisional) {
    replaceProvisionalMessage(state, provisional.id, message);
  } else {
    upsertMessage(state, message);
  }
  markPublishedDispatchTerminal(state, event, post);
}

function markPublishedDispatchTerminal(
  state: RoomProjectionState,
  event: UiRoomEvent,
  post: RoomPostV2,
): void {
  if (post.publicationSource.kind !== 'room_commit' || !post.dispatchId) return;

  const participantId = event.participantId ?? '';
  const turn = ensureTurn(state, post.rootId, post.createdAtMs);
  turn.rootId = post.rootId;
  turn.dispatchIds ??= [];
  turn.terminalDispatchIds ??= [];
  turn.dispatchParticipantIds ??= {};
  if (!turn.dispatchIds.includes(post.dispatchId)) {
    turn.dispatchIds.push(post.dispatchId);
  }
  if (participantId) {
    turn.dispatchParticipantIds[post.dispatchId] = participantId;
    if (!turn.participantIds.includes(participantId)) {
      turn.participantIds.push(participantId);
    }
  }
  if (!turn.terminalDispatchIds.includes(post.dispatchId)) {
    turn.terminalDispatchIds.push(post.dispatchId);
  }

  if (participantId) {
    const participantDispatches = turn.dispatchIds.filter(
      (dispatchId) => turn.dispatchParticipantIds?.[dispatchId] === participantId,
    );
    if (
      participantDispatches.length > 0
      && participantDispatches.every(
        (dispatchId) => turn.terminalDispatchIds?.includes(dispatchId),
      )
    ) {
      turn.terminalParticipantIds ??= [];
      if (!turn.terminalParticipantIds.includes(participantId)) {
        turn.terminalParticipantIds.push(participantId);
      }
    }
  }
  // Publishing settles one Dispatch lane. Only the participant-less Root
  // terminal event may unlock the whole turn.
  turn.updatedAtMs = Math.max(turn.updatedAtMs, post.createdAtMs);
}

function replaceProvisionalMessage(
  state: RoomProjectionState,
  provisionalId: string,
  message: RoomMessageProjection,
): void {
  const provisional = state.messagesById[provisionalId];
  if (!provisional) {
    upsertMessage(state, message);
    return;
  }

  const orderIndex = state.messageOrder.indexOf(provisionalId);
  const finalAlreadyProjected = Boolean(state.messagesById[message.id]);
  if (orderIndex >= 0) {
    if (finalAlreadyProjected) {
      state.messageOrder.splice(orderIndex, 1);
    } else {
      state.messageOrder[orderIndex] = message.id;
    }
  }
  delete state.messagesById[provisionalId];
  state.messagesById[message.id] = message;

  const turn = state.turnsById[provisional.turnId];
  if (turn) {
    turn.messageIds = turn.messageIds.filter(
      (id) => id !== provisionalId && id !== message.id,
    );
    turn.messageIds.push(message.id);
    turn.updatedAtMs = Math.max(
      turn.updatedAtMs,
      message.completedAtMs ?? message.createdAtMs,
    );
  } else {
    attachMessage(state, message);
  }
}

function upsertMessage(
  state: RoomProjectionState,
  message: RoomMessageProjection,
  clientMessageId = message.clientMessageId ?? '',
): void {
  const optimisticId = clientMessageId
    ? state.optimisticByClientMessageId[clientMessageId]
    : undefined;
  let replacedOptimistic = false;
  if (optimisticId && optimisticId !== message.id) {
    const index = state.messageOrder.indexOf(optimisticId);
    const optimistic = state.messagesById[optimisticId];
    delete state.messagesById[optimisticId];
    delete state.optimisticByClientMessageId[clientMessageId];
    if (index >= 0) {
      state.messageOrder[index] = message.id;
      replacedOptimistic = true;
    }
    if (optimistic) detachMessage(state, optimistic);
  }
  if (!state.messagesById[message.id] && !replacedOptimistic) state.messageOrder.push(message.id);
  state.messagesById[message.id] = message;
  attachMessage(state, message);
}

function upsertActivity(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
  forcedStatus?: RoomActivityProjection['status'],
): void {
  const participantStatus = text(payload.status);
  const sourceEventType = text(payload.sourceEventType);
  const isCompletedRoomLifecycle =
    event.eventType === 'participant_status' &&
    ['room_created', 'room_archived', 'room_restored'].includes(
      participantStatus,
    );
  const lifecycleId = text(
    payload.toolCallId ?? payload.approvalId ?? payload.requestId,
  );
  const executionScope =
    text(payload.dispatchId)
    || event.sourceSessionId
    || event.participantId
    || 'room';
  const id = lifecycleId
    ? `${event.turnId}:${event.participantId ?? 'participant'}:${executionScope}:${lifecycleId}`
    : `${event.eventId}:activity`;
  const status = forcedStatus ?? (
    payload.isError === true || participantStatus === 'failed'
      ? 'failed'
      : sourceEventType === 'tool_started' || sourceEventType === 'tool_progress'
        ? 'running'
        : event.eventType === 'participant_status' && !isCompletedRoomLifecycle
          ? 'running'
          : 'completed'
  );
  const existing = state.activitiesById[id];
  const activity: RoomActivityProjection = {
    id,
    turnId: event.turnId,
    participantId: event.participantId,
    sourceSessionId: event.sourceSessionId,
    kind: event.eventType,
    status,
    summary:
      text(payload.summary ?? payload.message ?? payload.label ?? payload.toolName)
      || sourceEventType
      || event.eventType,
    payload,
    createdAtMs: existing?.createdAtMs ?? event.createdAtMs,
    updatedAtMs: event.createdAtMs,
  };
  if (!state.activitiesById[id]) state.activityOrder.push(id);
  state.activitiesById[id] = activity;
  const turn = ensureTurn(state, event.turnId, event.createdAtMs);
  turn.rootId = text(payload.rootId) || turn.rootId || event.turnId;
  const dispatchId = text(payload.dispatchId);
  if (dispatchId) {
    turn.dispatchIds ??= [];
    turn.dispatchParticipantIds ??= {};
    if (!turn.dispatchIds.includes(dispatchId)) turn.dispatchIds.push(dispatchId);
    turn.dispatchParticipantIds[dispatchId] = event.participantId ?? '';
  }
  if (!turn.activityIds.includes(id)) turn.activityIds.push(id);
  if (event.participantId && !turn.participantIds.includes(event.participantId)) {
    turn.participantIds.push(event.participantId);
  }
  if (isCompletedRoomLifecycle) {
    completeTurn(state, event.turnId, 'completed', event.createdAtMs);
  }
}

function attachMessage(state: RoomProjectionState, message: RoomMessageProjection): void {
  const turn = ensureTurn(state, message.turnId, message.createdAtMs);
  turn.rootId = message.rootId || turn.rootId || message.turnId;
  if (message.dispatchId) {
    turn.dispatchIds ??= [];
    turn.dispatchParticipantIds ??= {};
    if (!turn.dispatchIds.includes(message.dispatchId)) {
      turn.dispatchIds.push(message.dispatchId);
    }
    turn.dispatchParticipantIds[message.dispatchId] = message.participantId ?? '';
  }
  if (!turn.messageIds.includes(message.id)) turn.messageIds.push(message.id);
  if (message.participantId && !turn.participantIds.includes(message.participantId)) {
    turn.participantIds.push(message.participantId);
  }
  turn.updatedAtMs = Math.max(turn.updatedAtMs, message.completedAtMs ?? message.createdAtMs);
}

function detachMessage(state: RoomProjectionState, message: RoomMessageProjection): void {
  const turn = state.turnsById[message.turnId];
  if (!turn) return;
  turn.messageIds = turn.messageIds.filter((id) => id !== message.id);
  if (turn.messageIds.length === 0 && turn.activityIds.length === 0) {
    delete state.turnsById[turn.id];
    state.turnOrder = state.turnOrder.filter((id) => id !== turn.id);
  }
}

function ensureTurn(
  state: RoomProjectionState,
  requestedTurnId: string,
  nowMs: number,
): RoomTurnProjection {
  const turnId = requestedTurnId || 'unscoped';
  let turn = state.turnsById[turnId];
  if (!turn) {
    turn = {
      id: turnId,
      rootId: turnId,
      status: 'running',
      messageIds: [],
      activityIds: [],
      participantIds: [],
      terminalParticipantIds: [],
      failedParticipantIds: [],
      abortedParticipantIds: [],
      dispatchIds: [],
      terminalDispatchIds: [],
      failedDispatchIds: [],
      abortedDispatchIds: [],
      dispatchParticipantIds: {},
      createdAtMs: nowMs,
      updatedAtMs: nowMs,
    };
    state.turnsById[turnId] = turn;
    state.turnOrder.push(turnId);
  }
  return turn;
}

function completeParticipantTurn(
  state: RoomProjectionState,
  event: Pick<UiRoomEvent, 'turnId' | 'participantId'>,
  dispatchId: string,
  status: Extract<RoomTurnProjection['status'], 'completed' | 'failed' | 'aborted'>,
  nowMs: number,
  failure = '',
): void {
  const participantId = event.participantId ?? '';
  if (!participantId && !dispatchId) {
    completeTurn(state, event.turnId, status, nowMs, failure);
    return;
  }
  const turn = ensureTurn(state, event.turnId, nowMs);
  turn.dispatchIds ??= [];
  turn.terminalDispatchIds ??= [];
  turn.failedDispatchIds ??= [];
  turn.abortedDispatchIds ??= [];
  turn.dispatchParticipantIds ??= {};
  if (dispatchId) {
    if (!turn.dispatchIds.includes(dispatchId)) turn.dispatchIds.push(dispatchId);
    turn.dispatchParticipantIds[dispatchId] = participantId;
    if (
      turn.abortedDispatchIds.includes(dispatchId)
      || (status === 'completed' && turn.failedDispatchIds.includes(dispatchId))
    ) {
      return;
    }
    if (!turn.terminalDispatchIds.includes(dispatchId)) {
      turn.terminalDispatchIds.push(dispatchId);
    }
    if (status === 'failed' && !turn.failedDispatchIds.includes(dispatchId)) {
      turn.failedDispatchIds.push(dispatchId);
    }
    if (status === 'aborted' && !turn.abortedDispatchIds.includes(dispatchId)) {
      turn.abortedDispatchIds.push(dispatchId);
    }
  } else if (participantId) {
    for (const id of turn.dispatchIds) {
      if (turn.dispatchParticipantIds[id] !== participantId) continue;
      if (!turn.terminalDispatchIds.includes(id)) turn.terminalDispatchIds.push(id);
      if (status === 'failed' && !turn.failedDispatchIds.includes(id)) {
        turn.failedDispatchIds.push(id);
      }
      if (status === 'aborted' && !turn.abortedDispatchIds.includes(id)) {
        turn.abortedDispatchIds.push(id);
      }
    }
  }
  if (participantId && !turn.participantIds.includes(participantId)) {
    turn.participantIds.push(participantId);
  }
  turn.terminalParticipantIds ??= [];
  turn.failedParticipantIds ??= [];
  turn.abortedParticipantIds ??= [];
  const participantDispatches = turn.dispatchIds.filter(
    (id) => turn.dispatchParticipantIds?.[id] === participantId,
  );
  const participantTerminal = !dispatchId || participantDispatches.every(
    (id) => turn.terminalDispatchIds?.includes(id),
  );
  if (participantId && participantTerminal) {
    if (!turn.terminalParticipantIds.includes(participantId)) {
      turn.terminalParticipantIds.push(participantId);
    }
    if (
      participantDispatches.some((id) => turn.failedDispatchIds?.includes(id))
      || (!dispatchId && status === 'failed')
    ) {
      if (!turn.failedParticipantIds.includes(participantId)) {
        turn.failedParticipantIds.push(participantId);
      }
    }
    if (
      participantDispatches.some((id) => turn.abortedDispatchIds?.includes(id))
      || (!dispatchId && status === 'aborted')
    ) {
      if (!turn.abortedParticipantIds.includes(participantId)) {
        turn.abortedParticipantIds.push(participantId);
      }
    }
  }
  turn.updatedAtMs = Math.max(turn.updatedAtMs, nowMs);
  if (failure) turn.failure = failure;
  for (const messageId of turn.messageIds) {
    const message = state.messagesById[messageId];
    if (
      !message
      || (participantId && message.participantId !== participantId)
      || (dispatchId && message.dispatchId && message.dispatchId !== dispatchId)
    ) continue;
    state.messagesById[messageId] = {
      ...message,
      status: status === 'completed' ? 'completed' : status,
      completedAtMs: nowMs,
    };
  }
  // A participant/Dispatch terminal only settles its execution lane. The
  // participant-less Root terminal remains the sole input-unlock authority.
  turn.status = 'running';
}

function completeTurn(
  state: RoomProjectionState,
  turnId: string,
  status: Extract<RoomTurnProjection['status'], 'completed' | 'failed' | 'aborted'>,
  nowMs: number,
  failure = '',
): void {
  const turn = ensureTurn(state, turnId, nowMs);
  turn.status = status;
  turn.rootTerminalAtMs = nowMs;
  turn.updatedAtMs = nowMs;
  turn.terminalParticipantIds = [...turn.participantIds];
  turn.failedParticipantIds = status === 'failed' ? [...turn.participantIds] : [];
  turn.abortedParticipantIds = status === 'aborted' ? [...turn.participantIds] : [];
  turn.terminalDispatchIds = [...(turn.dispatchIds ?? [])];
  turn.failedDispatchIds = status === 'failed' ? [...(turn.dispatchIds ?? [])] : [];
  turn.abortedDispatchIds = status === 'aborted' ? [...(turn.dispatchIds ?? [])] : [];
  if (failure) turn.failure = failure;
  for (const messageId of turn.messageIds) {
    const message = state.messagesById[messageId];
    if (!message) continue;
    state.messagesById[messageId] = {
      ...message,
      status: status === 'completed' ? 'completed' : status,
      completedAtMs: nowMs,
    };
  }
}

function appendDiagnostic(state: RoomProjectionState, diagnostic: ProjectionDiagnostic): void {
  state.diagnostics.push(diagnostic);
  if (state.diagnostics.length > diagnosticLimit) {
    state.diagnostics.splice(0, state.diagnostics.length - diagnosticLimit);
  }
}

function messageText(message: UiAgentMessage): string {
  return message.blocks
    .filter((block) => block.type === 'text' || block.type === 'code')
    .map((block) => text(record(block.data).text ?? record(block.data).code))
    .filter(Boolean)
    .join('\n');
}

function executionMessageId(
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): string {
  const messageId = text(payload.messageId);
  const dispatchId = text(payload.dispatchId);
  if (!dispatchId) {
    return messageId
      || `${event.turnId}:${event.participantId ?? 'participant'}:assistant`;
  }
  const rootId = text(payload.rootId) || event.turnId;
  const participantId = (event.participantId ?? event.sourceSessionId) || 'participant';
  return [
    'room-execution',
    rootId,
    participantId,
    dispatchId,
    messageId || 'assistant',
  ].join('\u001f');
}

function cloneState(state: RoomProjectionState): RoomProjectionState {
  return {
    ...state,
    messagesById: { ...state.messagesById },
    messageOrder: [...state.messageOrder],
    activitiesById: { ...state.activitiesById },
    activityOrder: [...state.activityOrder],
    turnsById: Object.fromEntries(
      Object.entries(state.turnsById).map(([id, turn]) => [
        id,
        {
          ...turn,
          messageIds: [...turn.messageIds],
          activityIds: [...turn.activityIds],
          participantIds: [...turn.participantIds],
          terminalParticipantIds: [...(turn.terminalParticipantIds ?? [])],
          failedParticipantIds: [...(turn.failedParticipantIds ?? [])],
          abortedParticipantIds: [...(turn.abortedParticipantIds ?? [])],
          dispatchIds: [...(turn.dispatchIds ?? [])],
          terminalDispatchIds: [...(turn.terminalDispatchIds ?? [])],
          failedDispatchIds: [...(turn.failedDispatchIds ?? [])],
          abortedDispatchIds: [...(turn.abortedDispatchIds ?? [])],
          dispatchParticipantIds: { ...(turn.dispatchParticipantIds ?? {}) },
        },
      ]),
    ),
    turnOrder: [...state.turnOrder],
    optimisticByClientMessageId: { ...state.optimisticByClientMessageId },
    diagnostics: [...state.diagnostics],
    ...(state.gap ? { gap: { ...state.gap } } : {}),
  };
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function isExecutionEventAfterRootTerminal(
  state: RoomProjectionState,
  event: UiRoomEvent,
  payload: Record<string, unknown>,
): boolean {
  if (![
    'participant_delta',
    'participant_message',
    'room_post',
    'route_decision',
    'participant_status',
    'participant_activity',
    'turn_completed',
    'turn_failed',
  ].includes(event.eventType)) return false;
  const post = record(payload.post);
  const rootId = text(payload.rootId) || text(post.rootId) || event.turnId;
  return state.turnsById[rootId]?.rootTerminalAtMs != null;
}

function publicRoomPayload(value: unknown): Record<string, unknown> {
  const envelope = record(value);
  if (
    typeof envelope.sourceEventId === 'string' &&
    typeof envelope.sourceEventType === 'string' &&
    typeof envelope.data === 'object' &&
    envelope.data !== null &&
    !Array.isArray(envelope.data)
  ) {
    return {
      ...record(envelope.data),
      sourceEventId: envelope.sourceEventId,
      sourceEventType: envelope.sourceEventType,
    };
  }
  return envelope;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
