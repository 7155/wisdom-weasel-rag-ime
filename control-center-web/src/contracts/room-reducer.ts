import type { ProjectionDiagnostic, ProjectionGap, ProjectionReduction } from './agent-reducer';
import type { UiAgentMessage, UiRoomEvent } from './ui-events';
import { tryParseAgentMessage } from './validators';

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
}

export interface RoomTurnProjection {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'aborted';
  messageIds: string[];
  activityIds: string[];
  participantIds: string[];
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
  const payload = record(event.payload);

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
    case 'route_decision':
    case 'participant_status':
    case 'participant_activity':
      upsertActivity(next, event, payload);
      break;
    case 'turn_completed':
      completeTurn(next, event.turnId, 'completed', event.createdAtMs);
      break;
    case 'turn_failed':
      completeTurn(next, event.turnId, 'failed', event.createdAtMs, text(payload.error));
      upsertActivity(next, event, payload, 'failed');
      break;
    case 'snapshot_required':
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
    createdAtMs: input.nowMs,
  };
  next.messagesById[id] = message;
  next.messageOrder.push(id);
  next.optimisticByClientMessageId[input.clientMessageId] = id;
  attachMessage(next, message);
  return next;
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
  for (const [clientMessageId, messageId] of Object.entries(
    state.optimisticByClientMessageId,
  )) {
    if (clientIds.has(clientMessageId)) continue;
    const message = state.messagesById[messageId];
    if (!message) continue;
    next.messagesById[messageId] = message;
    next.messageOrder.push(messageId);
    next.optimisticByClientMessageId[clientMessageId] = messageId;
    attachMessage(next, message);
  }
  return next;
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
  const id =
    text(payload.messageId) || `${event.turnId}:${event.participantId ?? 'participant'}:assistant`;
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
    ...(clientMessageId ? { clientMessageId } : {}),
    createdAtMs: parsed.value.createdAtMs,
    ...(parsed.value.completedAtMs == null
      ? {}
      : { completedAtMs: parsed.value.completedAtMs }),
  };
  upsertMessage(state, message, clientMessageId);
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
  const id =
    text(payload.toolCallId ?? payload.approvalId ?? payload.requestId) ||
    `${event.eventId}:activity`;
  const status =
    forcedStatus ??
    (payload.isError === true || text(payload.status) === 'failed'
      ? 'failed'
      : event.eventType === 'participant_status' && text(payload.status) !== 'completed'
        ? 'running'
        : 'completed');
  const activity: RoomActivityProjection = {
    id,
    turnId: event.turnId,
    participantId: event.participantId,
    sourceSessionId: event.sourceSessionId,
    kind: event.eventType,
    status,
    summary: text(payload.summary ?? payload.message ?? payload.label) || event.eventType,
    payload,
    createdAtMs: event.createdAtMs,
  };
  if (!state.activitiesById[id]) state.activityOrder.push(id);
  state.activitiesById[id] = activity;
  const turn = ensureTurn(state, event.turnId, event.createdAtMs);
  if (!turn.activityIds.includes(id)) turn.activityIds.push(id);
  if (event.participantId && !turn.participantIds.includes(event.participantId)) {
    turn.participantIds.push(event.participantId);
  }
}

function attachMessage(state: RoomProjectionState, message: RoomMessageProjection): void {
  const turn = ensureTurn(state, message.turnId, message.createdAtMs);
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
      status: 'running',
      messageIds: [],
      activityIds: [],
      participantIds: [],
      createdAtMs: nowMs,
      updatedAtMs: nowMs,
    };
    state.turnsById[turnId] = turn;
    state.turnOrder.push(turnId);
  }
  return turn;
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
  turn.updatedAtMs = nowMs;
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

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
