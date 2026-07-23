import type { UiAgentEvent, UiAgentMessage } from './ui-events';
import type { AgentSessionTelemetryV1 } from './generated/agent-session-telemetry.v1';
import type {
  ActGate as AgentActGateProjection,
  Goal as AgentGoalProjection,
} from './generated/agent-workflow-state.v1';
import { parseAgentEvent, tryParseAgentMessage, validateContract } from './validators';

export type AgentTurnStatus =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'aborted';

export interface AgentTurnProjection {
  id: string;
  status: AgentTurnStatus;
  messageIds: string[];
  activityIds: string[];
  createdAtMs: number;
  updatedAtMs: number;
  failure?: string;
}

export interface AgentActivityProjection {
  id: string;
  turnId: string;
  kind: string;
  status: 'running' | 'waiting' | 'completed' | 'failed';
  summary: string;
  payload: Record<string, unknown>;
  createdAtMs: number;
  updatedAtMs: number;
  /** First source-event sequence, used only as a stable timeline tie-breaker. */
  timelineSequence?: number;
}

export type AgentMessageProjection = UiAgentMessage & {
  /** First source-event sequence; snapshots created before this field still sort by timestamp. */
  timelineSequence?: number;
};

export interface AgentToolProgressEntry {
  eventId: string;
  kind: 'tool_started' | 'tool_progress' | 'tool_finished';
  status: AgentActivityProjection['status'];
  summary: string;
  createdAtMs: number;
}

export interface ProjectionDiagnostic {
  id: string;
  streamKind: 'agent' | 'room';
  eventType: string;
  summary: string;
  sequence: number;
  payload: Record<string, unknown>;
}

export interface ProjectionGap {
  expectedSequence: number;
  receivedSequence: number;
  receivedEventId: string;
}

export interface AgentProjectionState {
  sessionId: string;
  lastSequence: number;
  lastEventId: string;
  resumeToken: string;
  needsSnapshot: boolean;
  gap?: ProjectionGap;
  status: string;
  messagesById: Record<string, AgentMessageProjection>;
  messageOrder: string[];
  turnsById: Record<string, AgentTurnProjection>;
  turnOrder: string[];
  activitiesById: Record<string, AgentActivityProjection>;
  activityOrder: string[];
  optimisticByClientMessageId: Record<string, string>;
  diagnostics: ProjectionDiagnostic[];
  telemetry?: AgentSessionTelemetryV1;
  messageQueue: AgentMessageQueue;
  plan: AgentPlanProjection;
  goal: AgentGoalProjection;
  actGate: AgentActGateProjection;
}

export interface AgentMessageQueue {
  steering: string[];
  followUp: string[];
}

export type AgentPlanItemStatus = 'pending' | 'in_progress' | 'completed';

export interface AgentPlanItemProjection {
  id: string;
  title: string;
  status: AgentPlanItemStatus;
  position: number;
  sequence: number;
  updatedAtMs: number;
}

export interface AgentPlanProjection {
  id: string;
  sessionId: string;
  revision: number;
  title: string;
  status: 'draft' | 'review' | 'approved' | 'executing' | 'completed' | 'cancelled';
  actor: string;
  note: string;
  updatedAtMs: number;
  editable: boolean;
  actApproved: boolean;
  items: AgentPlanItemProjection[];
  counts: {
    total: number;
    pending: number;
    inProgress: number;
    completed: number;
  };
}

export type ProjectionDisposition =
  | 'applied'
  | 'ignored-duplicate'
  | 'ignored-foreign'
  | 'ignored-snapshot-pending'
  | 'snapshot-required';

export interface ProjectionReduction<State> {
  state: State;
  disposition: ProjectionDisposition;
}

export interface AgentSnapshot {
  messages: unknown[];
  liveEvents: unknown[];
  lastSequence: number;
  resumeToken: string;
  status?: string;
  telemetry?: unknown;
  messageQueue?: unknown;
  plan?: unknown;
  goal?: unknown;
  actGate?: unknown;
}

export interface OptimisticAgentMessageInput {
  clientMessageId: string;
  text: string;
  attachments?: string[];
  nowMs: number;
  turnId?: string;
  delivery?: 'prompt' | 'steer' | 'followUp';
}

const diagnosticLimit = 50;

export function createAgentProjection(sessionId: string): AgentProjectionState {
  return {
    sessionId,
    lastSequence: 0,
    lastEventId: '',
    resumeToken: '',
    needsSnapshot: false,
    status: 'idle',
    messagesById: {},
    messageOrder: [],
    turnsById: {},
    turnOrder: [],
    activitiesById: {},
    activityOrder: [],
    optimisticByClientMessageId: {},
    diagnostics: [],
    telemetry: undefined,
    messageQueue: { steering: [], followUp: [] },
    plan: emptyAgentPlan(),
    goal: emptyAgentGoal(),
    actGate: closedActGate(),
  };
}

export function reduceAgentEvent(
  state: AgentProjectionState,
  event: UiAgentEvent,
): ProjectionReduction<AgentProjectionState> {
  if (event.sessionId !== state.sessionId) {
    return { state, disposition: 'ignored-foreign' };
  }
  if (event.sequence <= state.lastSequence) {
    return { state, disposition: 'ignored-duplicate' };
  }
  if (state.needsSnapshot && event.eventType !== 'snapshot') {
    return { state, disposition: 'ignored-snapshot-pending' };
  }
  if (
    event.eventType !== 'snapshot' &&
    state.lastSequence > 0 &&
    event.sequence !== state.lastSequence + 1
  ) {
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

  if (event.eventType === 'snapshot') {
    const snapshot = snapshotFromEvent(event, state.lastSequence);
    const replaced = applyAgentSnapshot(state, snapshot);
    return {
      state: {
        ...replaced,
        lastSequence: Math.max(event.sequence, snapshot.lastSequence),
        lastEventId: event.eventId,
        resumeToken: snapshot.resumeToken || event.resumeToken,
      },
      disposition: 'applied',
    };
  }

  let next = cloneState(state);
  next.lastSequence = event.sequence;
  next.lastEventId = event.eventId;
  next.resumeToken = event.resumeToken;
  const payload = record(event.payload);
  const telemetry = parseTelemetry(payload.telemetry);
  if (telemetry) next.telemetry = telemetry;

  switch (event.eventType) {
    case 'text_delta':
      applyTextDelta(next, event, payload);
      break;
    case 'message_completed':
      applyCompletedMessage(next, event, payload);
      break;
    case 'compaction_started':
      upsertCompactionActivity(next, event, payload, 'running');
      break;
    case 'compaction_completed':
      upsertCompactionActivity(next, event, payload, payload.error ? 'failed' : 'completed');
      break;
    case 'status_changed':
      if (text(payload.phase) === 'provider_retry') {
        const activityState = text(payload.activityState);
        const retryStatus: AgentActivityProjection['status'] =
          activityState === 'completed'
            ? 'completed'
            : activityState === 'failed'
              ? 'failed'
              : 'running';
        upsertActivity(next, event, payload, retryStatus);
      }
      next.status = text(payload.status) || next.status;
      touchTurn(next, event.turnId, turnStatusFromRuntime(next.status), event.createdAtMs);
      break;
    case 'message_queue_updated':
      next.messageQueue = parseMessageQueue(payload);
      break;
    case 'workflow_changed':
      next.plan = parseAgentPlan(payload.plan) ?? next.plan;
      next.goal = parseAgentGoal(payload.goal) ?? next.goal;
      next.actGate = parseActGate(payload.actGate) ?? next.actGate;
      break;
    case 'reasoning_summary':
      upsertActivity(next, event, payload, 'completed');
      break;
    case 'tool_started':
    case 'tool_progress':
      upsertActivity(next, event, payload, payload.isError === true ? 'failed' : 'running');
      next.status = payload.isError === true ? 'failed' : 'working';
      break;
    case 'tool_finished':
      upsertActivity(next, event, payload, payload.isError === true ? 'failed' : 'completed');
      break;
    case 'approval_required':
    case 'user_input_required':
      upsertActivity(next, event, payload, 'waiting');
      next.status = 'waiting';
      touchTurn(next, event.turnId, 'waiting', event.createdAtMs);
      break;
    case 'approval_resolved':
      upsertActivity(
        next,
        event,
        payload,
        ['approved', 'applied', 'external_pending'].includes(text(payload.state))
          ? 'completed'
          : 'failed',
      );
      break;
    case 'memory_checkpointed':
      // Older journals may contain a bookkeeping event for every captured
      // user message. Capturing a source is not memory recall or context
      // injection, so keep those legacy events out of the visible activity
      // trail while preserving explicit tool-receipt checkpoints.
      if (text(payload.sourceRole) === 'user') break;
      upsertActivity(next, event, payload, 'completed');
      break;
    case 'memory_maintenance_updated':
      upsertActivity(next, event, payload, 'completed');
      break;
    case 'session_configuration_changed':
      // Model/thinking state is refreshed from the authoritative Pi catalog
      // by AgentFeature; it is not a visible timeline activity.
      break;
    case 'turn_completed':
      completeTurn(
        next,
        event.turnId,
        payload.status === 'aborted' || payload.aborted === true ? 'aborted' : 'completed',
        event.createdAtMs,
      );
      next.status = 'idle';
      break;
    case 'turn_failed':
      completeTurn(next, event.turnId, 'failed', event.createdAtMs, text(payload.error));
      next.status = 'failed';
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
        streamKind: 'agent',
        eventType: event.rawEventType || 'unknown',
        summary: 'Unsupported agent event was retained for diagnostics.',
        sequence: event.sequence,
        payload,
      });
      break;
    case 'heartbeat':
      break;
  }
  return { state: next, disposition: 'applied' };
}

export function appendOptimisticAgentMessage(
  state: AgentProjectionState,
  input: OptimisticAgentMessageInput,
): AgentProjectionState {
  if (!input.clientMessageId.trim()) throw new TypeError('clientMessageId must not be empty');
  if (state.optimisticByClientMessageId[input.clientMessageId]) return state;

  const next = cloneState(state);
  const messageId = `local:${input.clientMessageId}`;
  const turnId = input.turnId || `local-turn:${input.clientMessageId}`;
  const existingTurnStatus = next.turnsById[turnId]?.status;
  const message: UiAgentMessage = {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: messageId,
    sessionId: state.sessionId,
    turnId,
    role: 'user',
    status: 'queued',
    blocks: [
      {
        id: `${messageId}:text`,
        type: 'text',
        status: 'completed',
        presentationKind: 'plain_text',
        data: {
          text: input.text,
          ...(input.delivery && input.delivery !== 'prompt' ? { delivery: input.delivery } : {}),
        },
      },
    ],
    attachments: [...(input.attachments ?? [])],
    citations: [],
    createdAtMs: input.nowMs,
    completedAtMs: null,
    clientMessageId: input.clientMessageId,
  };
  next.messagesById[messageId] = message;
  next.messageOrder.push(messageId);
  next.optimisticByClientMessageId[input.clientMessageId] = messageId;
  attachMessageToTurn(next, message);
  if (!existingTurnStatus) touchTurn(next, turnId, 'queued', input.nowMs);
  next.status = 'busy';
  return next;
}

export function failOptimisticAgentMessage(
  state: AgentProjectionState,
  clientMessageId: string,
  error: string,
  nowMs: number,
): AgentProjectionState {
  const messageId = state.optimisticByClientMessageId[clientMessageId];
  if (!messageId) return state;
  const message = state.messagesById[messageId];
  if (!message) return state;
  const next = cloneState(state);
  next.messagesById[messageId] = { ...message, status: 'failed' };
  completeTurn(next, message.turnId, 'failed', nowMs, error);
  next.status = 'failed';
  return next;
}

export function discardOptimisticAgentMessage(
  state: AgentProjectionState,
  clientMessageId: string,
): AgentProjectionState {
  const messageId = state.optimisticByClientMessageId[clientMessageId];
  if (!messageId) return state;
  const message = state.messagesById[messageId];
  if (!message) return state;

  const next = cloneState(state);
  delete next.optimisticByClientMessageId[clientMessageId];
  delete next.messagesById[messageId];
  next.messageOrder = next.messageOrder.filter((id) => id !== messageId);
  detachMessageFromTurn(next, message);
  const turn = next.turnsById[message.turnId];
  if (turn && turn.messageIds.length === 0 && turn.activityIds.length === 0) {
    delete next.turnsById[message.turnId];
    next.turnOrder = next.turnOrder.filter((id) => id !== message.turnId);
  }
  next.status = next.turnOrder.some((turnId) => {
    const status = next.turnsById[turnId]?.status;
    return status === 'queued' || status === 'running' || status === 'waiting';
  }) ? 'busy' : 'idle';
  return next;
}

export function abortAgentTurn(
  state: AgentProjectionState,
  turnId: string,
  nowMs: number,
): AgentProjectionState {
  if (!state.turnsById[turnId]) return state;
  const next = cloneState(state);
  completeTurn(next, turnId, 'aborted', nowMs);
  next.status = 'idle';
  return next;
}

export function applyAgentSnapshot(
  state: AgentProjectionState,
  snapshot: AgentSnapshot,
): AgentProjectionState {
  let next = createAgentProjection(state.sessionId);
  next.status = snapshot.status ?? state.status;
  next.telemetry = parseTelemetry(snapshot.telemetry) ?? state.telemetry;
  next.messageQueue = parseMessageQueue(snapshot.messageQueue);
  next.plan = parseAgentPlan(snapshot.plan) ?? state.plan;
  next.goal = parseAgentGoal(snapshot.goal) ?? state.goal;
  next.actGate = parseActGate(snapshot.actGate) ?? state.actGate;

  const serverClientIds = new Set<string>();
  for (const rawMessage of snapshot.messages) {
    const parsed = tryParseAgentMessage(rawMessage);
    if (!parsed.ok || parsed.value.sessionId !== state.sessionId) {
      appendDiagnostic(next, {
        id: `snapshot-invalid:${next.diagnostics.length}`,
        streamKind: 'agent',
        eventType: 'snapshot_message_invalid',
        summary: 'A malformed snapshot message was skipped.',
        sequence: next.lastSequence,
        payload: {},
      });
      continue;
    }
    upsertMessage(next, parsed.value);
    if (parsed.value.clientMessageId) serverClientIds.add(parsed.value.clientMessageId);
  }

  // The transcript restores durable conversation text; the bounded live event
  // projection restores current reasoning, tool and approval state. Snapshot
  // events are normalized locally so their historical sequence gaps do not
  // trigger another snapshot. The server cursor below remains authoritative
  // for the following SSE subscription.
  for (const rawEvent of snapshot.liveEvents) {
    try {
      const parsed = parseAgentEvent(rawEvent);
      if (parsed.sessionId !== state.sessionId) throw new TypeError('foreign snapshot event');
      const hydrated = {
        ...parsed,
        sequence: next.lastSequence + 1,
      };
      next = reduceAgentEvent(next, hydrated).state;
    } catch {
      appendDiagnostic(next, {
        id: `snapshot-event-invalid:${next.diagnostics.length}`,
        streamKind: 'agent',
        eventType: 'snapshot_event_invalid',
        summary: 'A malformed snapshot event was skipped.',
        sequence: snapshot.lastSequence,
        payload: {},
      });
    }
  }

  // liveEvents is a bounded journal and may end with an old busy/aborting
  // marker after a runtime restart. `active` means the persisted Pi transcript
  // is open; only `busy`/`working`/`waiting` mean a turn is running. Treat an
  // active-but-quiescent snapshot as terminal so reopening an old conversation
  // cannot turn its last completed answer into a multi-day "thinking" turn.
  const replayStatus = next.status;
  if (snapshot.status && ['idle', 'ready', 'stopped', 'active'].includes(snapshot.status)) {
    next.status = snapshot.status;
    const lastTurn = next.turnsById[next.turnOrder[next.turnOrder.length - 1] ?? ''];
    if (lastTurn && ['queued', 'running', 'waiting'].includes(lastTurn.status)) {
      completeTurn(
        next,
        lastTurn.id,
        replayStatus === 'aborting' ? 'aborted' : 'completed',
        lastTurn.updatedAtMs,
      );
    }
  }

  for (const [clientMessageId, messageId] of Object.entries(
    state.optimisticByClientMessageId,
  )) {
    if (serverClientIds.has(clientMessageId)) continue;
    const optimistic = state.messagesById[messageId];
    if (!optimistic) continue;
    next.messagesById[messageId] = optimistic;
    next.messageOrder.push(messageId);
    next.optimisticByClientMessageId[clientMessageId] = messageId;
    attachMessageToTurn(next, optimistic);
    const previousTurn = state.turnsById[optimistic.turnId];
    const restoredTurn = next.turnsById[optimistic.turnId];
    if (previousTurn && restoredTurn) {
      next.turnsById[optimistic.turnId] = {
        ...restoredTurn,
        status: previousTurn.status,
        updatedAtMs: Math.max(restoredTurn.updatedAtMs, previousTurn.updatedAtMs),
        failure: previousTurn.failure,
      };
    }
  }
  reconcileSnapshotTurnStatuses(next);
  next.lastSequence = Math.max(0, snapshot.lastSequence);
  next.lastEventId = snapshot.resumeToken;
  next.resumeToken = snapshot.resumeToken;
  next.needsSnapshot = false;
  next.gap = undefined;
  return next;
}

export function agentSnapshotFromResponse(value: unknown): AgentSnapshot {
  const payload = record(value);
  const messages = Array.isArray(payload.messages)
    ? payload.messages
    : Array.isArray(payload.items)
      ? payload.items
      : [];
  return {
    messages,
    liveEvents: Array.isArray(payload.liveEvents) ? payload.liveEvents : [],
    lastSequence: integer(payload.lastSequence ?? payload.lastEventSequence),
    resumeToken: text(payload.resumeToken ?? payload.lastEventId),
    ...(typeof payload.status === 'string' ? { status: payload.status } : {}),
    ...(payload.telemetry === undefined ? {} : { telemetry: payload.telemetry }),
    ...(payload.messageQueue === undefined ? {} : { messageQueue: payload.messageQueue }),
    ...(payload.plan === undefined ? {} : { plan: payload.plan }),
    ...(payload.goal === undefined ? {} : { goal: payload.goal }),
    ...(payload.actGate === undefined ? {} : { actGate: payload.actGate }),
  };
}

function applyTextDelta(
  state: AgentProjectionState,
  event: UiAgentEvent,
  payload: Record<string, unknown>,
): void {
  const delta = text(payload.delta);
  if (!delta) return;
  const baseMessageId = text(payload.messageId) || `${event.turnId}:assistant`;
  const messageId = streamingAssistantSegmentId(
    state,
    event.turnId,
    baseMessageId,
    payload.replaceBlock === true,
    event.sequence,
  );
  const blockId = messageId === baseMessageId
    ? text(payload.blockId) || `${messageId}:text`
    : `${messageId}:text`;
  const existing = state.messagesById[messageId];
  const blocks = existing ? [...existing.blocks] : [];
  const blockIndex = blocks.findIndex((block) => block.id === blockId || block.type === 'text');
  if (blockIndex >= 0) {
    const block = blocks[blockIndex];
    const previous = text(record(block.data).text);
    blocks[blockIndex] = {
      ...block,
      status: 'running',
      type: 'text',
      presentationKind: 'markdown',
      data: { ...record(block.data), text: previous + delta },
    };
  } else {
    blocks.push({
      id: blockId,
      type: 'text',
      status: 'running',
      presentationKind: 'markdown',
      data: { text: delta },
    });
  }
  const message: AgentMessageProjection = existing
    ? { ...existing, status: 'streaming', blocks, completedAtMs: null }
    : {
        schemaVersion: 'rag-ime.agent-message.v1',
        id: messageId,
        sessionId: event.sessionId,
        turnId: event.turnId,
        role: 'assistant',
        status: 'streaming',
        blocks,
        attachments: [],
        citations: [],
        createdAtMs: event.createdAtMs,
        completedAtMs: null,
        timelineSequence: event.sequence,
      };
  upsertMessage(state, message);
  touchTurn(state, event.turnId, 'running', event.createdAtMs);
  state.status = 'responding';
}

function applyCompletedMessage(
  state: AgentProjectionState,
  event: UiAgentEvent,
  payload: Record<string, unknown>,
): void {
  const parsed = tryParseAgentMessage(payload.message);
  if (!parsed.ok) {
    appendDiagnostic(state, {
      id: `${event.eventId}:invalid-message`,
      streamKind: 'agent',
      eventType: 'message_completed_invalid',
      summary: 'A malformed completed message was skipped.',
      sequence: event.sequence,
      payload,
    });
    return;
  }
  const clientMessageId = text(payload.clientMessageId) || parsed.value.clientMessageId || '';
  const usage = parseUsage(payload.usage);
  const model = state.telemetry?.model;
  const enriched = parsed.value.role === 'assistant'
    ? {
        ...parsed.value,
        ...(parsed.value.usage || !usage ? {} : { usage }),
        ...(parsed.value.provider || !model?.provider ? {} : { provider: model.provider }),
        ...(parsed.value.model || !model?.id ? {} : { model: model.id }),
      }
    : parsed.value;
  const completedMessage = enriched.role === 'assistant'
    ? completedAssistantSegment(state, event, enriched)
    : { ...parsed.value, timelineSequence: event.sequence };
  upsertMessage(
    state,
    clientMessageId ? { ...completedMessage, clientMessageId } : completedMessage,
    clientMessageId,
  );
  touchTurn(
    state,
    parsed.value.turnId,
    parsed.value.status === 'failed' ? 'failed' : 'running',
    event.createdAtMs,
  );
}

function upsertCompactionActivity(
  state: AgentProjectionState,
  event: UiAgentEvent,
  payload: Record<string, unknown>,
  status: AgentActivityProjection['status'],
): void {
  const runningId = [...state.activityOrder]
    .reverse()
    .find((activityId) => {
      const activity = state.activitiesById[activityId];
      return activity?.kind === 'context_compaction' && activity.status === 'running';
    });
  const id = runningId ?? `compaction:${event.eventId}`;
  const previous = state.activitiesById[id];
  const reason = text(payload.reason) || 'threshold';
  const activity: AgentActivityProjection = {
    id,
    turnId: previous?.turnId || event.turnId || `maintenance:${event.sequence}`,
    kind: 'context_compaction',
    status,
    summary: status === 'running' ? '正在压缩上下文' : '上下文压缩完成',
    payload: { ...previous?.payload, ...payload },
    createdAtMs: previous?.createdAtMs ?? event.createdAtMs,
    updatedAtMs: event.createdAtMs,
    timelineSequence: previous?.timelineSequence ?? event.sequence,
  };
  activity.summary = status === 'failed'
    ? '上下文压缩失败'
    : status === 'running'
      ? `${compactionReasonLabel(reason)}，正在压缩上下文`
      : `${compactionReasonLabel(reason)}，上下文压缩完成`;
  if (!previous) state.activityOrder.push(id);
  state.activitiesById[id] = activity;
  const turn = ensureTurn(state, activity.turnId, activity.createdAtMs);
  if (!turn.activityIds.includes(id)) turn.activityIds.push(id);
}

function compactionReasonLabel(reason: string): string {
  if (reason === 'manual') return '手动触发';
  if (reason === 'overflow') return '溢出恢复';
  return '达到自动阈值';
}

function parseTelemetry(value: unknown): AgentSessionTelemetryV1 | undefined {
  if (!value) return undefined;
  const parsed = validateContract('agent-session-telemetry.v1', value);
  return parsed.ok ? parsed.value : undefined;
}

function parseUsage(value: unknown): UiAgentMessage['usage'] | undefined {
  const usage = record(value);
  const fields = ['input', 'output', 'cacheRead', 'cacheWrite', 'totalTokens'] as const;
  if (!fields.every((field) => typeof usage[field] === 'number' && Number.isFinite(usage[field]))) {
    return undefined;
  }
  return {
    input: integer(usage.input),
    output: integer(usage.output),
    cacheRead: integer(usage.cacheRead),
    cacheWrite: integer(usage.cacheWrite),
    totalTokens: integer(usage.totalTokens),
  };
}

function streamingAssistantSegmentId(
  state: AgentProjectionState,
  turnId: string,
  baseMessageId: string,
  startsNewMessage: boolean,
  sequence: number,
): string {
  const segments = assistantSegmentsForBase(state, turnId, baseMessageId);
  const latest = segments[segments.length - 1];
  if (!latest) return baseMessageId;
  if (startsNewMessage) return `${baseMessageId}:segment:${sequence}`;
  return latest.id;
}

function completedAssistantSegment(
  state: AgentProjectionState,
  event: UiAgentEvent,
  message: UiAgentMessage,
): AgentMessageProjection {
  const segments = assistantSegmentsForBase(state, message.turnId, message.id);
  const latest = segments[segments.length - 1];
  const targetId = latest?.status === 'streaming'
    ? latest.id
    : latest
      ? `${message.id}:segment:${event.sequence}`
      : message.id;
  return {
    ...message,
    id: targetId,
    createdAtMs: latest?.status === 'streaming' ? latest.createdAtMs : message.createdAtMs,
    timelineSequence: latest?.status === 'streaming'
      ? latest.timelineSequence ?? event.sequence
      : event.sequence,
  };
}

function assistantSegmentsForBase(
  state: AgentProjectionState,
  turnId: string,
  baseMessageId: string,
): AgentMessageProjection[] {
  const turn = state.turnsById[turnId];
  if (!turn) return [];
  const segmentPrefix = `${baseMessageId}:segment:`;
  return turn.messageIds.flatMap((messageId) => {
    const message = state.messagesById[messageId];
    if (!message || message.role !== 'assistant') return [];
    return message.id === baseMessageId || message.id.startsWith(segmentPrefix) ? [message] : [];
  });
}

function upsertMessage(
  state: AgentProjectionState,
  message: AgentMessageProjection,
  clientMessageId = message.clientMessageId ?? '',
): void {
  if (message.role !== 'user' && message.role !== 'assistant') return;
  const previous = state.messagesById[message.id];
  if (previous && previous.turnId !== message.turnId) detachMessageFromTurn(state, previous);
  const optimisticId = clientMessageId
    ? state.optimisticByClientMessageId[clientMessageId]
    : undefined;
  let replacedOptimistic = false;
  if (optimisticId && optimisticId !== message.id) {
    const index = state.messageOrder.indexOf(optimisticId);
    const optimistic = state.messagesById[optimisticId];
    delete state.messagesById[optimisticId];
    delete state.optimisticByClientMessageId[clientMessageId];
    if (index >= 0) state.messageOrder[index] = message.id;
    if (optimistic) detachMessageFromTurn(state, optimistic);
    replacedOptimistic = index >= 0;
  }

  if (!state.messagesById[message.id] && !replacedOptimistic) state.messageOrder.push(message.id);
  state.messagesById[message.id] = message;
  attachMessageToTurn(state, message);
}

function upsertActivity(
  state: AgentProjectionState,
  event: UiAgentEvent,
  payload: Record<string, unknown>,
  status: AgentActivityProjection['status'],
): void {
  const id =
    text(payload.toolCallId ?? payload.approvalId ?? payload.requestId) ||
    `${event.turnId}:${event.eventType}`;
  const previous = state.activitiesById[id];
  if (previous && previous.turnId !== event.turnId) {
    const previousTurn = writableTurn(state, previous.turnId);
    if (previousTurn) {
      previousTurn.activityIds = previousTurn.activityIds.filter((activityId) => activityId !== id);
    }
  }
  const activityPayload = mergeActivityPayload(previous, event, payload, status);
  const activity: AgentActivityProjection = {
    id,
    turnId: event.turnId,
    kind: event.eventType,
    status,
    summary: activitySummary(payload, event.eventType),
    payload: activityPayload,
    createdAtMs: previous?.createdAtMs ?? event.createdAtMs,
    updatedAtMs: event.createdAtMs,
    timelineSequence: previous?.timelineSequence ?? event.sequence,
  };
  if (!previous) state.activityOrder.push(id);
  state.activitiesById[id] = activity;
  updateAgentPlanFromActivity(state, activityPayload);
  const turn = ensureTurn(state, event.turnId, event.createdAtMs);
  if (!turn.activityIds.includes(id)) turn.activityIds.push(id);
}

function mergeActivityPayload(
  previous: AgentActivityProjection | undefined,
  event: UiAgentEvent,
  payload: Record<string, unknown>,
  status: AgentActivityProjection['status'],
): Record<string, unknown> {
  if (!isToolActivityEvent(event.eventType)) return payload;

  const previousPayload = previous && isToolActivityEvent(previous.kind)
    ? previous.payload
    : {};
  const history = agentToolProgressHistory(previousPayload.progressHistory);
  const nextEntry: AgentToolProgressEntry = {
    eventId: event.eventId,
    kind: event.eventType,
    status,
    summary: toolProgressSummary(payload, previousPayload, event.eventType, status),
    createdAtMs: event.createdAtMs,
  };
  const progressHistory = history.some((entry) => entry.eventId === event.eventId)
    ? history
    : [...history, nextEntry].slice(-20);

  // These events are updates for one logical tool call. Keep stable metadata
  // and prior partial results while the latest event advances its status.
  const merged: Record<string, unknown> = {
    ...previousPayload,
    ...payload,
    progressHistory,
  };
  if (
    Object.keys(record(payload.args)).length === 0
    && Object.keys(record(previousPayload.args)).length > 0
  ) {
    merged.args = previousPayload.args;
  }
  return merged;
}

export function agentToolProgressHistory(value: unknown): AgentToolProgressEntry[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): AgentToolProgressEntry[] => {
    const entry = record(item);
    const kind = text(entry.kind);
    const status = text(entry.status);
    if (
      !['tool_started', 'tool_progress', 'tool_finished'].includes(kind)
      || !['running', 'waiting', 'completed', 'failed'].includes(status)
    ) return [];
    return [{
      eventId: text(entry.eventId),
      kind: kind as AgentToolProgressEntry['kind'],
      status: status as AgentToolProgressEntry['status'],
      summary: boundedToolProgressText(entry.summary),
      createdAtMs: finiteTimestamp(entry.createdAtMs),
    }];
  }).filter((entry) => entry.eventId && entry.createdAtMs > 0);
}

function toolProgressSummary(
  payload: Record<string, unknown>,
  previousPayload: Record<string, unknown>,
  eventType: AgentToolProgressEntry['kind'],
  status: AgentActivityProjection['status'],
): string {
  const carrier = record(payload.result ?? payload.partialResult);
  const details = record(carrier.details);
  const domain = record(details.result ?? carrier.result);
  const explicit = boundedToolProgressText(
    domain.summary
      ?? details.summary
      ?? carrier.summary
      ?? payload.summary
      ?? payload.message
      ?? payload.label,
  );
  if (explicit) return explicit;
  const toolName = boundedToolProgressText(
    payload.toolName ?? payload.toolId ?? previousPayload.toolName ?? previousPayload.toolId,
  ) || '工具';
  if (status === 'failed') return `${toolName}执行失败`;
  if (eventType === 'tool_finished') return `${toolName}执行完成`;
  if (eventType === 'tool_started') return `${toolName}已开始`;
  return `${toolName}正在处理`;
}

function boundedToolProgressText(value: unknown): string {
  if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') return '';
  const normalized = String(value)
    .replace(/\s+/g, ' ')
    .replace(/(?:\/Users|\/Volumes|\/private|\/tmp)\/[^\s,;，。]+/g, '本地资源')
    .replace(/(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+/gi, '敏感信息已隐藏')
    .trim();
  return normalized.length > 240 ? `${normalized.slice(0, 240)}…` : normalized;
}

function finiteTimestamp(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function isToolActivityEvent(value: string): value is AgentToolProgressEntry['kind'] {
  return value === 'tool_started' || value === 'tool_progress' || value === 'tool_finished';
}

function activitySummary(payload: Record<string, unknown>, fallback: string): string {
  return text(payload.summary ?? payload.label ?? payload.message ?? payload.toolName) || fallback;
}

function touchTurn(
  state: AgentProjectionState,
  turnId: string,
  status: AgentTurnStatus,
  nowMs: number,
): void {
  const turn = ensureTurn(state, turnId, nowMs);
  turn.status = status;
  turn.updatedAtMs = nowMs;
}

function completeTurn(
  state: AgentProjectionState,
  turnId: string,
  status: Extract<AgentTurnStatus, 'completed' | 'failed' | 'aborted'>,
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
    const messageStatus = status === 'completed' ? 'completed' : status;
    state.messagesById[messageId] = {
      ...message,
      status: messageStatus,
      blocks: message.blocks.map((block) => ({
        ...block,
        status: block.status === 'running' ? messageStatus : block.status,
      })),
      completedAtMs: nowMs,
    };
  }
}

function ensureTurn(
  state: AgentProjectionState,
  requestedTurnId: string,
  nowMs: number,
): AgentTurnProjection {
  const turnId = requestedTurnId || 'unscoped';
  let turn = writableTurn(state, turnId);
  if (!turn) {
    turn = {
      id: turnId,
      status: 'running',
      messageIds: [],
      activityIds: [],
      createdAtMs: nowMs,
      updatedAtMs: nowMs,
    };
    state.turnsById[turnId] = turn;
    state.turnOrder.push(turnId);
  }
  return turn;
}

function attachMessageToTurn(state: AgentProjectionState, message: UiAgentMessage): void {
  const turn = ensureTurn(state, message.turnId, message.createdAtMs);
  if (!turn.messageIds.includes(message.id)) turn.messageIds.push(message.id);
  turn.updatedAtMs = Math.max(turn.updatedAtMs, message.completedAtMs ?? message.createdAtMs);
}

function reconcileSnapshotTurnStatuses(state: AgentProjectionState): void {
  for (const turnId of state.turnOrder) {
    const turn = writableTurn(state, turnId);
    if (!turn) continue;
    const messages = turn.messageIds
      .map((messageId) => state.messagesById[messageId])
      .filter((message): message is UiAgentMessage => Boolean(message));
    const statuses = new Set(messages.map((message) => message.status));
    if (statuses.has('failed')) turn.status = 'failed';
    else if (statuses.has('streaming')) turn.status = 'running';
    else if (statuses.has('queued')) turn.status = 'queued';
    else if (statuses.has('aborted')) turn.status = 'aborted';
    else turn.status = 'completed';
  }

  const lastTurn = writableTurn(
    state,
    state.turnOrder[state.turnOrder.length - 1] ?? '',
  );
  const runtimeStatus = turnStatusFromRuntime(state.status);
  if (lastTurn && runtimeStatus !== 'completed' && lastTurn.status === 'completed') {
    lastTurn.status = runtimeStatus;
  }
}

function detachMessageFromTurn(state: AgentProjectionState, message: UiAgentMessage): void {
  const turn = writableTurn(state, message.turnId);
  if (!turn) return;
  turn.messageIds = turn.messageIds.filter((id) => id !== message.id);
  if (turn.messageIds.length === 0 && turn.activityIds.length === 0) {
    delete state.turnsById[turn.id];
    state.turnOrder = state.turnOrder.filter((id) => id !== turn.id);
  }
}

function appendDiagnostic(state: AgentProjectionState, diagnostic: ProjectionDiagnostic): void {
  state.diagnostics.push(diagnostic);
  if (state.diagnostics.length > diagnosticLimit) {
    state.diagnostics.splice(0, state.diagnostics.length - diagnosticLimit);
  }
}

function snapshotFromEvent(event: UiAgentEvent, fallbackSequence: number): AgentSnapshot {
  const payload = record(event.payload);
  const snapshot = agentSnapshotFromResponse(payload.snapshot ?? payload);
  return {
    ...snapshot,
    lastSequence: snapshot.lastSequence || event.sequence || fallbackSequence,
    resumeToken: snapshot.resumeToken || event.resumeToken,
  };
}

function turnStatusFromRuntime(status: string): AgentTurnStatus {
  if (status === 'waiting') return 'waiting';
  if (status === 'failed' || status === 'faulted') return 'failed';
  if (status === 'idle' || status === 'ready' || status === 'stopped' || status === 'active') {
    return 'completed';
  }
  return 'running';
}

function cloneState(state: AgentProjectionState): AgentProjectionState {
  return {
    ...state,
    messagesById: { ...state.messagesById },
    messageOrder: [...state.messageOrder],
    // Turn values are copied only when a reducer writes to them. Streaming
    // deltas therefore keep every completed turn referentially stable instead
    // of cloning the whole conversation on every token batch.
    turnsById: { ...state.turnsById },
    turnOrder: [...state.turnOrder],
    activitiesById: { ...state.activitiesById },
    activityOrder: [...state.activityOrder],
    optimisticByClientMessageId: { ...state.optimisticByClientMessageId },
    diagnostics: [...state.diagnostics],
    messageQueue: {
      steering: [...state.messageQueue.steering],
      followUp: [...state.messageQueue.followUp],
    },
    plan: {
      ...state.plan,
      items: state.plan.items.map((item) => ({ ...item })),
      counts: { ...state.plan.counts },
    },
    goal: {
      ...state.goal,
      budget: { ...state.goal.budget },
      usage: { ...state.goal.usage },
      remaining: { ...state.goal.remaining },
      completionAudit: state.goal.completionAudit
        ? { ...state.goal.completionAudit, evidence: state.goal.completionAudit.evidence }
        : null,
    },
    actGate: { ...state.actGate },
    ...(state.gap ? { gap: { ...state.gap } } : {}),
  };
}

function writableTurn(
  state: AgentProjectionState,
  turnId: string,
): AgentTurnProjection | undefined {
  const current = state.turnsById[turnId];
  if (!current) return undefined;
  const copy = {
    ...current,
    messageIds: [...current.messageIds],
    activityIds: [...current.activityIds],
  };
  state.turnsById[turnId] = copy;
  return copy;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function parseMessageQueue(value: unknown): AgentMessageQueue {
  const source = record(value);
  return {
    steering: Array.isArray(source.steering)
      ? source.steering.filter((item): item is string => typeof item === 'string')
      : [],
    followUp: Array.isArray(source.followUp)
      ? source.followUp.filter((item): item is string => typeof item === 'string')
      : [],
  };
}

function emptyAgentPlan(): AgentPlanProjection {
  return {
    id: '',
    sessionId: '',
    revision: 0,
    title: '执行计划',
    status: 'draft',
    actor: '',
    note: '',
    updatedAtMs: 0,
    editable: true,
    actApproved: false,
    items: [],
    counts: {
      total: 0,
      pending: 0,
      inProgress: 0,
      completed: 0,
    },
  };
}

export function parseAgentPlan(value: unknown): AgentPlanProjection | undefined {
  const source = record(value);
  if (!Array.isArray(source.items)) return undefined;
  const items = source.items.slice(0, 100).flatMap((rawItem, index): AgentPlanItemProjection[] => {
    const item = record(rawItem);
    const title = text(item.title ?? item.label).replace(/\s+/g, ' ').trim().slice(0, 240);
    const status = text(item.status);
    if (!title || !['pending', 'in_progress', 'completed'].includes(status)) return [];
    const id = text(item.id ?? item.itemId).trim().slice(0, 160) || `plan-item:${index + 1}`;
    return [{
      id,
      title,
      status: status as AgentPlanItemStatus,
      position: integer(item.position) || index + 1,
      sequence: integer(item.sequence),
      updatedAtMs: integer(item.updatedAtMs ?? item.createdAtMs),
    }];
  });
  const completed = items.filter((item) => item.status === 'completed').length;
  const inProgress = items.filter((item) => item.status === 'in_progress').length;
  return {
    id: text(source.id),
    sessionId: text(source.sessionId),
    revision: integer(source.revision),
    title: text(source.title).trim().slice(0, 160) || '执行计划',
    status: ['draft', 'review', 'approved', 'executing', 'completed', 'cancelled'].includes(text(source.status))
      ? text(source.status) as AgentPlanProjection['status']
      : 'draft',
    actor: text(source.actor).slice(0, 120),
    note: text(source.note).slice(0, 600),
    updatedAtMs: integer(source.updatedAtMs),
    editable: source.editable === undefined ? true : source.editable === true,
    actApproved: source.actApproved === true,
    items,
    counts: {
      total: items.length,
      pending: items.length - completed - inProgress,
      inProgress,
      completed,
    },
  };
}

function emptyAgentGoal(): AgentGoalProjection {
  return {
    schemaVersion: 'rag-ime.agent-goal.v1',
    sessionId: '',
    configured: false,
    goalId: '',
    revision: 0,
    objective: '',
    status: 'cleared',
    budget: { tokenLimit: null, timeLimitMs: null },
    usage: { tokens: 0, elapsedMs: 0 },
    remaining: { tokens: null, timeMs: null },
    budgetExceeded: false,
    completionAudit: null,
    updatedAtMs: 0,
  };
}

function closedActGate(): AgentActGateProjection {
  return {
    allowed: false,
    reason: 'plan_required',
    message: '先创建执行计划并提交审阅。',
  };
}

function parseAgentGoal(value: unknown): AgentGoalProjection | undefined {
  const source = record(value);
  if (source.schemaVersion !== 'rag-ime.agent-goal.v1') return undefined;
  const status = text(source.status);
  if (!['active', 'paused', 'completed', 'cleared'].includes(status)) return undefined;
  const budget = record(source.budget);
  const usage = record(source.usage);
  const remaining = record(source.remaining);
  const auditSource = record(source.completionAudit);
  const evidence = Array.isArray(auditSource.evidence)
    ? auditSource.evidence.flatMap((rawEvidence) => {
      const item = record(rawEvidence);
      const kind = text(item.kind);
      const summary = text(item.summary);
      const reference = text(item.reference);
      return ['test', 'artifact', 'commit', 'receipt', 'note'].includes(kind) && summary && reference
        ? [{ kind, summary, reference }]
        : [];
    })
    : [];
  return {
    schemaVersion: 'rag-ime.agent-goal.v1',
    sessionId: text(source.sessionId),
    configured: source.configured === true,
    goalId: text(source.goalId),
    revision: integer(source.revision),
    objective: text(source.objective).slice(0, 4_000),
    status: status as AgentGoalProjection['status'],
    budget: {
      tokenLimit: nullableInteger(budget.tokenLimit),
      timeLimitMs: nullableInteger(budget.timeLimitMs),
    },
    usage: { tokens: integer(usage.tokens), elapsedMs: integer(usage.elapsedMs) },
    remaining: {
      tokens: nullableInteger(remaining.tokens),
      timeMs: nullableInteger(remaining.timeMs),
    },
    budgetExceeded: source.budgetExceeded === true,
    completionAudit: auditSource.auditId && evidence.length
      ? {
          auditId: text(auditSource.auditId),
          summary: text(auditSource.summary),
          evidence: evidence as NonNullable<AgentGoalProjection['completionAudit']>['evidence'],
          completedBy: text(auditSource.completedBy),
          createdAtMs: integer(auditSource.createdAtMs),
        }
      : null,
    updatedAtMs: integer(source.updatedAtMs),
  };
}

function parseActGate(value: unknown): AgentActGateProjection | undefined {
  const source = record(value);
  const reason = text(source.reason);
  if (![
    'approved',
    'plan_required',
    'plan_not_approved',
    'plan_completed',
    'plan_cancelled',
    'goal_paused',
    'goal_completed',
    'goal_budget_exhausted',
  ].includes(reason)) return undefined;
  return {
    allowed: source.allowed === true,
    reason: reason as AgentActGateProjection['reason'],
    message: text(source.message),
  };
}

function nullableInteger(value: unknown): number | null {
  return value === null ? null : integer(value);
}

function updateAgentPlanFromActivity(
  state: AgentProjectionState,
  payload: Record<string, unknown>,
): void {
  const toolId = text(payload.toolId ?? payload.toolName);
  if (toolId !== 'agent_plan') return;
  const carrier = record(payload.result ?? payload.partialResult);
  const details = record(carrier.details);
  const candidates = [
    record(record(details.result).plan),
    record(record(carrier.result).plan),
    record(details.plan),
    record(carrier.plan),
    record(payload.plan),
    record(details.result),
    record(carrier.result),
    details,
    carrier,
    payload,
  ];
  for (const candidate of candidates) {
    const plan = parseAgentPlan(candidate);
    if (!plan) continue;
    state.plan = plan;
    return;
  }
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function integer(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) ? Math.max(0, value) : 0;
}
