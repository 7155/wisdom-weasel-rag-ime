import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
  RoomTurnProjection,
} from '@/contracts/room-reducer';
import {
  roomDispatchPlanFromActivity,
  roomDispatchPlanSummary,
  roomToolActivityLine,
  roomToolEvidence,
} from '@/paw-os/apps/room-gravity-projection';
import type {
  AssistantBlock,
  AssistantMessage,
  RunPhase,
  ToolStatus,
  TranscriptMessage,
} from '../model/types';

export interface RoomTranscriptOptions {
  /** Reader-facing actor name for a Room participant (Sol, Mars, …). */
  actorName(participantId: string | null | undefined): string;
  /** Secondary actor line — collaboration role, when the Room knows one. */
  actorRole?(participantId: string | null | undefined): string;
  /** Restrict the transcript to one partner's public lane (satellite view). */
  participantId?: string;
}

export interface RoomTranscript {
  messages: TranscriptMessage[];
  /** Runtime activity behind a block, so a host can keep approvals and
   *  background-process links inside the shared card. */
  activityByBlockId: Record<string, RoomActivityProjection>;
  phase: RunPhase;
}

const EMPTY_TRANSCRIPT: RoomTranscript = { messages: [], activityByBlockId: {}, phase: 'idle' };

const RESOLVED_APPROVAL_STATES = ['approved', 'rejected', 'applied', 'resolved', 'cancelled'];

/**
 * Project the authoritative Room reducer state onto the shared conversation
 * model: one Runtime loop becomes one assistant card, and that loop's public
 * reasoning, routing and tool work become blocks inside it.
 *
 * Folding happens in presentation only — no event is dropped or reordered,
 * and every block keeps a link back to its Runtime activity.
 */
export function roomTranscript(
  projection: RoomProjectionState | undefined,
  options: RoomTranscriptOptions,
): RoomTranscript {
  if (!projection) return EMPTY_TRANSCRIPT;

  const messages: TranscriptMessage[] = [];
  const activityByBlockId: Record<string, RoomActivityProjection> = {};
  const cardByKey = new Map<string, AssistantMessage>();
  let openKey = '';

  const cardFor = (
    turnId: string,
    participantId: string | null,
    timestamp: number,
  ): AssistantMessage => {
    const key = `${turnId || 'room:ungrouped'}|${participantId ?? 'sol'}`;
    const existing = key === openKey ? cardByKey.get(key) : undefined;
    if (existing) return existing;
    const card: AssistantMessage = {
      id: `loop:${key}:${messages.length}`,
      role: 'assistant',
      timestamp,
      blocks: [],
      actor: options.actorName(participantId),
      turnId,
      ...(options.actorRole?.(participantId) ? { actorRole: options.actorRole(participantId) } : {}),
    };
    cardByKey.set(key, card);
    openKey = key;
    messages.push(card);
    return card;
  };

  for (const entry of roomChronology(projection, options.participantId)) {
    if (entry.kind === 'message' && entry.message.role === 'user') {
      openKey = '';
      messages.push({
        id: entry.message.id,
        role: 'user',
        text: entry.message.text,
        timestamp: entry.message.createdAtMs,
        deliveryStatus: userDeliveryStatus(entry.message),
      });
      continue;
    }
    if (entry.kind === 'message') {
      const card = cardFor(entry.message.turnId, entry.message.participantId, entry.message.createdAtMs);
      card.blocks.push({
        id: `text:${entry.message.id}`,
        kind: 'text',
        text: entry.message.text,
        ...(entry.message.status === 'streaming' ? { streaming: true } : {}),
      });
      continue;
    }
    if (entry.kind === 'activity') {
      const card = cardFor(entry.activity.turnId, entry.activity.participantId, entry.activity.createdAtMs);
      const block = activityBlock(entry.activity);
      card.blocks.push(block);
      activityByBlockId[block.id] = entry.activity;
      continue;
    }
    const card = cardFor(entry.turn.id, entry.turn.participantIds[0] ?? null, entry.turn.updatedAtMs || entry.turn.createdAtMs);
    card.error = entry.turn.status === 'aborted'
      ? entry.turn.failure || '这轮协作已停止。'
      : entry.turn.failure || '这轮协作未完成。';
    openKey = '';
  }

  return { messages, activityByBlockId, phase: roomPhase(projection) };
}

/** Which turn a failed/aborted card can safely retry from, if any. */
export function roomTranscriptRetrySource(
  projection: RoomProjectionState,
  turnId: string,
): { rootId: string; text: string } | undefined {
  const turn = projection.turnsById[turnId];
  if (!turn || roomTurnSupersededByUserInput(turn, projection)) return undefined;
  const source = turn.messageIds
    .map((messageId) => projection.messagesById[messageId])
    .find((message) => message?.role === 'user' && message.text.trim());
  if (!source) return undefined;
  return { rootId: turn.rootId || turn.id, text: source.text };
}

export function roomPhase(projection: RoomProjectionState | undefined): RunPhase {
  if (!projection) return 'idle';
  for (let index = projection.turnOrder.length - 1; index >= 0; index -= 1) {
    const status = projection.turnsById[projection.turnOrder[index] ?? '']?.status;
    if (status === 'queued') return 'sending';
    if (status === 'running') return 'responding';
  }
  return 'idle';
}

/** Approval blocks stay visible and undecided until Runtime resolves them. */
export function roomApprovalDecision(activity: RoomActivityProjection): {
  approvalId: string;
  payloadSha256: string;
} | undefined {
  const approvalId = text(activity.payload.approvalId);
  const payloadSha256 = text(activity.payload.payloadSha256);
  const resolutionState = text(activity.payload.resolutionState || activity.payload.state);
  if (!approvalId || !payloadSha256) return undefined;
  if (!approvalNeedsHumanDecision(activity.payload)) return undefined;
  if (RESOLVED_APPROVAL_STATES.includes(resolutionState)) return undefined;
  return { approvalId, payloadSha256 };
}

/* --------------------------------------------------------------------------- */

type RoomChronologyEntry =
  | { kind: 'message'; message: RoomMessageProjection; order: number; id: string }
  | { kind: 'activity'; activity: RoomActivityProjection; order: number; id: string }
  | { kind: 'terminal'; turn: RoomTurnProjection; order: number; id: string };

function roomChronology(
  projection: RoomProjectionState,
  participantId?: string,
): RoomChronologyEntry[] {
  const entries: RoomChronologyEntry[] = [];
  for (const messageId of projection.messageOrder) {
    const message = projection.messagesById[messageId];
    if (!message || message.projectionKind === 'execution') continue;
    if (!message.text.trim() && !message.question) continue;
    if (participantId && !messageBelongsToParticipant(message, participantId, projection)) continue;
    entries.push({
      kind: 'message',
      message,
      order: message.sequence ?? message.createdAtMs,
      id: `message:${message.id}`,
    });
  }
  for (const activityId of projection.activityOrder) {
    const activity = projection.activitiesById[activityId];
    if (!activity || !activityVisible(activity)) continue;
    if (participantId && !activityBelongsToParticipant(activity, participantId)) continue;
    entries.push({
      kind: 'activity',
      activity,
      order: activity.sequence ?? activity.createdAtMs,
      id: `activity:${activity.id}`,
    });
  }
  if (!participantId) {
    for (const turnId of projection.turnOrder) {
      const turn = projection.turnsById[turnId];
      if (!turn || (turn.status !== 'failed' && turn.status !== 'aborted')) continue;
      entries.push({
        kind: 'terminal',
        turn,
        order: (turn.updatedAtMs || turn.createdAtMs) + 0.75,
        id: `terminal:${turn.id}`,
      });
    }
  }
  return entries.sort((left, right) => left.order - right.order || left.id.localeCompare(right.id));
}

function messageBelongsToParticipant(
  message: RoomMessageProjection,
  participantId: string,
  projection: RoomProjectionState,
): boolean {
  if (message.participantId === participantId) return true;
  if (message.mentionedParticipantIds?.includes(participantId)) return true;
  if (!message.answerToPostId) return false;
  return projection.messagesById[message.answerToPostId]?.participantId === participantId;
}

function activityBelongsToParticipant(activity: RoomActivityProjection, participantId: string): boolean {
  const target = text(activity.payload.targetParticipantId);
  return target ? target === participantId : activity.participantId === participantId;
}

function activityVisible(activity: RoomActivityProjection): boolean {
  const eventType = text(activity.payload.sourceEventType, activity.kind);
  return Boolean(text(activity.payload.approvalId))
    || eventType === 'tool'
    || eventType.startsWith('tool_')
    || ['reasoning', 'progress', 'route', 'route_decision', 'dispatch', 'status'].includes(activity.kind)
    || eventType.includes('route')
    || eventType.includes('dispatch');
}

function activityBlock(activity: RoomActivityProjection): AssistantBlock {
  const eventType = text(activity.payload.sourceEventType, activity.kind);
  if (roomApprovalDecision(activity) || text(activity.payload.approvalId)) {
    return {
      id: `approval:${activity.id}`,
      kind: 'tool',
      name: '受控操作审批',
      summary: compact(activity.summary) || '等待你确认这项受控操作',
      status: roomApprovalDecision(activity) ? 'pending' : toolStatus(activity.status),
      startedAt: activity.createdAtMs,
    };
  }
  const plan = roomDispatchPlanFromActivity(activity);
  if (plan) {
    return {
      id: `dispatch:${activity.id}`,
      kind: 'tool',
      name: '任务分派',
      summary: roomDispatchPlanSummary(plan),
      status: toolStatus(activity.status),
      ...(plan.candidates.length ? {
        output: plan.candidates
          .map((candidate) => `${candidate.displayName} · ${candidate.score.toFixed(1)}${candidate.selected ? ' · 已选择' : ''}${candidate.signals.length ? ` · ${candidate.signals.join('、')}` : ''}`)
          .join('\n'),
      } : {}),
      startedAt: activity.createdAtMs,
    };
  }
  if (eventType === 'tool' || eventType.startsWith('tool_')) {
    const evidence = roomToolEvidence(activity.payload);
    /* Runtime often echoes a raw argument blob as the summary. A reader line
     * is derived from real evidence instead; the blob stays reachable as the
     * card's input, so folding never costs a trace. */
    const raw = rawDetail(activity.summary);
    return {
      id: `tool:${activity.id}`,
      kind: 'tool',
      name: evidence?.label || '工具',
      summary: roomToolActivityLine(raw ? '' : activity.summary, activity.payload, activity.status),
      status: toolStatus(activity.status),
      ...(raw ? { input: activity.summary.trim() } : {}),
      ...(evidence?.facts.length
        ? { output: evidence.facts.map((fact) => `${fact.label}：${fact.value}`).join('\n') }
        : {}),
      startedAt: activity.createdAtMs,
    };
  }
  return {
    id: `note:${activity.id}`,
    kind: 'thinking',
    summary: compact(activity.summary) || (activity.kind === 'reasoning' ? '正在形成可公开的思考摘要' : '公开进展已更新'),
    status: activity.status === 'running' || activity.status === 'waiting' ? 'running' : 'done',
    ...(rawDetail(activity.summary) ? { detail: activity.summary.trim() } : {}),
    startedAt: activity.createdAtMs,
  };
}

function toolStatus(status: RoomActivityProjection['status']): ToolStatus {
  if (status === 'running' || status === 'waiting') return 'running';
  if (status === 'failed') return 'error';
  if (status === 'aborted') return 'cancelled';
  return 'success';
}

function userDeliveryStatus(message: RoomMessageProjection): 'sending' | 'sent' | 'failed' {
  if (message.status === 'failed' || message.status === 'aborted') return 'failed';
  if (message.status === 'queued' && message.projectionKind === 'optimistic') return 'sending';
  return 'sent';
}

function roomTurnSupersededByUserInput(
  turn: RoomTurnProjection,
  projection: RoomProjectionState,
): boolean {
  const indexes = turn.messageIds
    .map((messageId) => projection.messageOrder.indexOf(messageId))
    .filter((index) => index >= 0);
  const boundary = indexes.length ? Math.max(...indexes) : -1;
  if (boundary >= 0) {
    return projection.messageOrder.slice(boundary + 1).some((messageId) => {
      const message = projection.messagesById[messageId];
      return message?.role === 'user' && message.text.trim().length > 0;
    });
  }
  const turnIndex = projection.turnOrder.indexOf(turn.id);
  if (turnIndex < 0) return false;
  return projection.turnOrder.slice(turnIndex + 1).some((turnId) => (
    projection.turnsById[turnId]?.messageIds.some((messageId) => {
      const message = projection.messagesById[messageId];
      return message?.role === 'user' && message.text.trim().length > 0;
    }) ?? false
  ));
}

function rawDetail(value: string): boolean {
  const source = value.trim();
  return source.includes('\n')
    || /```|(?:^|\s)[{[]\s*["']/u.test(source)
    || source.length > 180;
}

function compact(value: string): string {
  const source = value.replace(/\s+/gu, ' ').trim();
  if (!source) return '';
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/iu.test(source)) return '';
  return source.length > 180 ? `${source.slice(0, 177).trimEnd()}…` : source;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}
