import type {
  AgentEventV1,
  AgentMessageV1,
  AgentRoomEventV1,
  ObservationEventV1,
} from './generated';

export const knownAgentEventTypes = [
  'snapshot',
  'text_delta',
  'reasoning_summary',
  'status_changed',
  'workflow_changed',
  'lifecycle_cancellation_changed',
  'message_queue_updated',
  'tool_started',
  'tool_progress',
  'tool_finished',
  'approval_required',
  'approval_resolved',
  'background_job_started',
  'background_job_progress',
  'background_job_completed',
  'background_job_failed',
  'background_job_cancelled',
  'memory_checkpointed',
  'memory_maintenance_updated',
  'session_configuration_changed',
  'user_input_required',
  'message_completed',
  'compaction_started',
  'compaction_completed',
  'turn_completed',
  'turn_failed',
  'snapshot_required',
  'heartbeat',
] as const satisfies readonly AgentEventV1['eventType'][];

export const knownRoomEventTypes = [
  'user_message',
  'route_decision',
  'participant_status',
  'participant_delta',
  'participant_activity',
  'participant_message',
  'room_post',
  'turn_completed',
  'turn_failed',
  'room_config_changed',
  'topic_changed',
  'artifact_changed',
  'snapshot_required',
] as const satisfies readonly AgentRoomEventV1['eventType'][];

export const knownAgentBlockTypes = [
  'text',
  'card',
  'checklist',
  'table',
  'code',
  'artifact',
  'reference',
  'status',
  'reasoning_summary',
  'progress',
  'tool_call',
  'tool_result',
  'citation',
  'image',
  'audio',
  'file',
  'sticker',
  'task_plan',
  'diff',
  'approval',
  'error',
  'unknown',
] as const satisfies readonly AgentMessageV1['blocks'][number]['type'][];

export type KnownAgentEventType = (typeof knownAgentEventTypes)[number];
export type KnownRoomEventType = (typeof knownRoomEventTypes)[number];
export type KnownAgentBlockType = (typeof knownAgentBlockTypes)[number];

export interface UiAgentEvent {
  schemaVersion: AgentEventV1['schemaVersion'];
  eventId: string;
  sessionId: string;
  turnId: string;
  sequence: number;
  createdAtMs: number;
  payload: Record<string, unknown>;
  resumeToken: string;
  streamKind: 'agent';
  eventType: KnownAgentEventType | 'unknown';
  rawEventType?: string;
}

export interface UiRoomEvent {
  schemaVersion: AgentRoomEventV1['schemaVersion'];
  eventId: string;
  roomId: string;
  sequence: number;
  turnId: string;
  topicId: string;
  participantId: string | null;
  sourceSessionId: string;
  createdAtMs: number;
  payload: Record<string, unknown>;
  resumeToken: string;
  streamKind: 'room';
  eventType: KnownRoomEventType | 'unknown';
  rawEventType?: string;
}

export type UiObservationEvent = ObservationEventV1 & {
  streamKind: 'observation';
};

interface UiAgentBlockDataByType {
  card: {
    title?: unknown;
    bodyMarkdown?: unknown;
    tone?: unknown;
    fields?: unknown;
  };
  checklist: { title?: unknown; items?: unknown };
  table: { title?: unknown; columns?: unknown; rows?: unknown; caption?: unknown };
  artifact: {
    title?: unknown;
    name?: unknown;
    fileName?: unknown;
    artifactId?: unknown;
    mediaType?: unknown;
    byteSize?: unknown;
    receiptUrl?: unknown;
    href?: unknown;
    url?: unknown;
    summary?: unknown;
  };
  reference: { title?: unknown; label?: unknown; href?: unknown; url?: unknown; source?: unknown; excerpt?: unknown };
  status: { title?: unknown; label?: unknown; state?: unknown; detail?: unknown; summary?: unknown; fields?: unknown };
}

type UiAgentBlockForType<T extends KnownAgentBlockType> = {
  schemaVersion?: 'rag-ime.agent-block.v1';
  id: string;
  type: T;
  status: AgentMessageV1['blocks'][number]['status'];
  presentationKind: string;
  data: T extends keyof UiAgentBlockDataByType
    ? UiAgentBlockDataByType[T] & Record<string, unknown>
    : Record<string, unknown>;
  rawType?: string;
  summary?: string;
  source?: { kind: string; ref: string };
  visibility?: 'private_session' | 'room_post' | 'root_post';
  digest?: string;
  ref?: string;
  generation?: number;
};

export type UiAgentBlock = {
  [T in KnownAgentBlockType]: UiAgentBlockForType<T>
}[KnownAgentBlockType];

export interface UiAgentMessage {
  schemaVersion: AgentMessageV1['schemaVersion'];
  id: string;
  sessionId: string;
  turnId: string;
  role: AgentMessageV1['role'];
  status: AgentMessageV1['status'];
  blocks: UiAgentBlock[];
  attachments: string[];
  citations: string[];
  createdAtMs: number;
  completedAtMs?: number | null;
  clientMessageId?: string;
  retryOfClientMessageId?: string;
  admissionState?: 'ambiguous' | 'pending' | 'unresolved';
  /** Local projection of a steer/follow-up receipt. Runtime messages do not
   * persist this UI-only lifecycle field. */
  deliveryState?: 'sending' | 'accepted' | 'applied';
  deliveryAcceptedAtMs?: number;
  provider?: string;
  model?: string;
  usage?: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
    totalTokens: number;
  };
}

export type UiControlEvent = UiAgentEvent | UiRoomEvent | UiObservationEvent;

const agentEventTypeSet = new Set<string>(knownAgentEventTypes);
const roomEventTypeSet = new Set<string>(knownRoomEventTypes);
const agentBlockTypeSet = new Set<string>(knownAgentBlockTypes);

export function normalizeAgentEvent(value: Record<string, unknown>): UiAgentEvent {
  const rawEventType = String(value.eventType ?? '');
  const known = agentEventTypeSet.has(rawEventType);
  return {
    schemaVersion: value.schemaVersion as AgentEventV1['schemaVersion'],
    eventId: String(value.eventId),
    sessionId: String(value.sessionId),
    turnId: String(value.turnId),
    sequence: Number(value.sequence),
    createdAtMs: Number(value.createdAtMs),
    payload: value.payload as Record<string, unknown>,
    resumeToken: String(value.resumeToken),
    streamKind: 'agent',
    eventType: known ? (rawEventType as KnownAgentEventType) : 'unknown',
    ...(known ? {} : { rawEventType }),
  };
}

export function normalizeRoomEvent(value: Record<string, unknown>): UiRoomEvent {
  const rawEventType = String(value.eventType ?? '');
  const known = roomEventTypeSet.has(rawEventType);
  return {
    schemaVersion: value.schemaVersion as AgentRoomEventV1['schemaVersion'],
    eventId: String(value.eventId),
    roomId: String(value.roomId),
    sequence: Number(value.sequence),
    turnId: String(value.turnId),
    topicId: String(value.topicId ?? ''),
    participantId: value.participantId === null ? null : String(value.participantId),
    sourceSessionId: String(value.sourceSessionId),
    createdAtMs: Number(value.createdAtMs),
    payload: value.payload as Record<string, unknown>,
    resumeToken: String(value.resumeToken),
    streamKind: 'room',
    eventType: known ? (rawEventType as KnownRoomEventType) : 'unknown',
    ...(known ? {} : { rawEventType }),
  };
}

export function normalizeObservationEvent(
  value: ObservationEventV1,
): UiObservationEvent {
  return { ...value, streamKind: 'observation' };
}

export function normalizeAgentMessage(value: Record<string, unknown>): UiAgentMessage {
  const source = value as AgentMessageV1 & {
    clientMessageId?: unknown;
    retryOfClientMessageId?: unknown;
  };
  const blocks = Array.isArray(source.blocks)
    ? source.blocks.map((block) => normalizeAgentBlock(block as Record<string, unknown>))
    : [];
  const clientMessageId =
    typeof source.clientMessageId === 'string' && source.clientMessageId.length > 0
      ? source.clientMessageId
      : undefined;
  const retryOfClientMessageId =
    typeof source.retryOfClientMessageId === 'string'
      && source.retryOfClientMessageId.length > 0
      ? source.retryOfClientMessageId
      : undefined;
  const usage = source.usage
    ? {
        input: source.usage.input,
        output: source.usage.output,
        cacheRead: source.usage.cacheRead,
        cacheWrite: source.usage.cacheWrite,
        totalTokens: source.usage.totalTokens,
      }
    : undefined;
  return {
    schemaVersion: source.schemaVersion,
    id: source.id,
    sessionId: source.sessionId,
    turnId: source.turnId,
    role: source.role,
    status: source.status,
    blocks,
    attachments: [...source.attachments],
    citations: [...source.citations],
    createdAtMs: source.createdAtMs,
    ...(source.completedAtMs === undefined ? {} : { completedAtMs: source.completedAtMs }),
    ...(clientMessageId ? { clientMessageId } : {}),
    ...(retryOfClientMessageId ? { retryOfClientMessageId } : {}),
    ...(source.provider ? { provider: source.provider } : {}),
    ...(source.model ? { model: source.model } : {}),
    ...(usage ? { usage } : {}),
  };
}

function normalizeAgentBlock(value: Record<string, unknown>): UiAgentBlock {
  const rawType = String(value.type ?? 'unknown');
  const known = agentBlockTypeSet.has(rawType);
  const source = value.source && typeof value.source === 'object' && !Array.isArray(value.source)
    ? value.source as Record<string, unknown>
    : undefined;
  return {
    ...(value.schemaVersion === 'rag-ime.agent-block.v1' ? { schemaVersion: value.schemaVersion } : {}),
    id: String(value.id),
    type: known ? (rawType as KnownAgentBlockType) : 'unknown',
    status: value.status as AgentMessageV1['blocks'][number]['status'],
    presentationKind: String(value.presentationKind),
    data: value.data as Record<string, unknown>,
    ...(known ? {} : { rawType }),
    ...(typeof value.summary === 'string' ? { summary: value.summary } : {}),
    ...(source && typeof source.kind === 'string' && typeof source.ref === 'string'
      ? { source: { kind: source.kind, ref: source.ref } }
      : {}),
    ...(['private_session', 'room_post', 'root_post'].includes(String(value.visibility))
      ? { visibility: value.visibility as 'private_session' | 'room_post' | 'root_post' }
      : {}),
    ...(typeof value.digest === 'string' ? { digest: value.digest } : {}),
    ...(typeof value.ref === 'string' ? { ref: value.ref } : {}),
    ...(typeof value.generation === 'number' && Number.isInteger(value.generation) ? { generation: value.generation } : {}),
  } as UiAgentBlock;
}
